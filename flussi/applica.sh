#!/usr/bin/env bash
# Trasi — flussi/applica.sh · F9 «Applica» (B4-FLW-02, §8 F9, §10 B4)
#
# Applica le proposte approvate e marca le scadute, poi lascia traccia in `flusso_run`.
# Tutto in **una sola transazione**: se la registrazione del run fallisse, non resterebbe una
# memoria modificata senza traccia — la contabilità è parte del lavoro, non un passo successivo.
#
# Perché il dominio non viene toccato qui. La scrittura della memoria applicativa è di
# `trasi.applica_proposte_approvate`: SECURITY DEFINER owner `applicatore`, ed è l'unico percorso
# che porta una proposta ad `applicata` scrivendo in `audit` il `prima`/`dopo` dell'entità. Una
# modifica scritta a mano in questo file sarebbe una seconda via di scrittura al dominio, cioè
# esattamente ciò che V4 vieta. Criterio osservabile della spec: i verbi di modifica del dominio
# (`luogo`, `scheda_servizio`, `evento`, `opportunita`, `casa`) non compaiono affatto qui —
# `grep -ci "…" flussi/applica.sh` → 0, verificato in `flussi/tests/test_applica.py`.
#
# Uso:
#     flussi/applica.sh                        # dall'host, via `docker compose exec`
#     TRASI_DB_VIA=diretta flussi/applica.sh   # dentro il container `automazioni`
#     TRASI_TRIGGER=cron flussi/applica.sh     # da crontab (dichiara il trigger del run)
#
# Esito: exit 0 se il flusso ha concluso (anche con proposte in errore: quelle restano `approvata`,
# ritentabili, ed è il *batch* a non dover abortire); exit 1 solo se il flusso non ha potuto girare.
set -uo pipefail

cd "$(dirname "$0")/.."

COMPOSE_FILE="deployment/docker-compose.yml"
SERVICE="db_trasi"
DB="${TRASI_DB:-trasi_db}"
ADMIN="${POSTGRES_USER:-postgres}"
LIMIT="${TRASI_APPLICA_LIMIT:-200}"
TRIGGER="${TRASI_TRIGGER:-manuale}"
VIA="${TRASI_DB_VIA:-}"
RUOLO_FLUSSI="${TRASI_DB_ROLE:-automazioni}"

if [[ -f deployment/.env ]]; then
  set -a; . deployment/.env; set +a
  DB="${TRASI_DB:-trasi_db}"; ADMIN="${POSTGRES_USER:-postgres}"
fi

# Trasporto: `docker compose exec` da host, `psql` diretto nel container `automazioni`
# (dove `docker` non esiste). La scelta è esplicita con TRASI_DB_VIA, altrimenti dedotta.
if [[ -z "$VIA" ]]; then
  if command -v docker >/dev/null 2>&1; then VIA=docker; else VIA=diretta; fi
fi

# **Identità dei flussi: la connessione, non un `SET ROLE`.** `automazioni` è un ruolo LOGIN e i flussi
# si connettono *come* `automazioni`: `session_user` resta `automazioni`, che è ciò che il trigger
# `evento_ical_01_audit` (db/006) legge per attribuire la riga `ical_upsert` e ciò che
# `v_scritture_senza_audit` usa per distinguere una scrittura dichiarata da una violazione di V4.
# Un `SET ROLE automazioni` da una connessione amministrativa lascerebbe `session_user='postgres'`:
# le scritture girerebbero, ma l'audit iCal non le registrerebbe — una perdita silenziosa di
# tracciabilità che nessun exit code segnalerebbe. Il test `test_identita.py` lo verifica.
if [[ "$VIA" == "docker" ]]; then
  if ! docker compose -f "$COMPOSE_FILE" ps --format '{{.Service}} {{.State}}' 2>/dev/null \
       | grep -q "^${SERVICE} running"; then
    echo "applica.sh: il servizio ${SERVICE} non è in esecuzione" >&2
    exit 1
  fi
  psql_flussi() {
    docker compose -f "$COMPOSE_FILE" exec -T "$SERVICE" \
      psql -U "$RUOLO_FLUSSI" -d "$DB" -X -q --no-psqlrc -v ON_ERROR_STOP=1 "$@"
  }
else
  export PGUSER="${PGUSER:-$RUOLO_FLUSSI}"
  export PGDATABASE="${PGDATABASE:-$DB}"
  psql_flussi() { psql -X -q --no-psqlrc -v ON_ERROR_STOP=1 "$@"; }
fi

# ---------------------------------------------------------------------------------------
# Il corpo: una transazione, una riga di `flusso_run`.
#
# La connessione è già nel ruolo `automazioni` (vedi sopra: `session_user` è l'identità, e i flussi
# girano sempre come `automazioni`, mai come amministratore — `EXECUTE` su
# `applica_proposte_approvate` è concesso esattamente a `automazioni` e `ti`, e un run da
# amministratore non proverebbe che il flusso *reale* ha i privilegi che gli servono).
#
# `\gset` raccoglie i conteggi: la funzione ritorna una riga per proposta, e l'esito aggregato
# (`ok`/`parziale`) dipende da quante ne sono cadute.
# ---------------------------------------------------------------------------------------
read -r -d '' CORPO <<'SQL' || true
\set QUIET on
BEGIN;
SET LOCAL search_path = trasi, public, pg_temp;

-- 0. Fotografia dell'audit PRIMA: il conteggio delle righe scritte da *questo* run è una differenza,
--    non una stima. Un `count(*)` a fine transazione includerebbe l'audit delle transizioni umane
--    (approvazioni) precedenti al run e falserebbe il criterio «3 righe di audit».
SELECT COALESCE(max(id), 0) AS audit_prima FROM trasi.audit
\gset

-- 1. Le proposte approvate diventano dato reale, con la loro riga di audit (prima/dopo).
CREATE TEMP TABLE esito_applica ON COMMIT DROP AS
  SELECT * FROM trasi.applica_proposte_approvate(:'limite'::int);

SELECT count(*) FILTER (WHERE esito = 'ok')                  AS applicate,
       count(*) FILTER (WHERE esito LIKE 'errore:%')         AS errori,
       count(*)                                              AS esaminate,
       COALESCE(jsonb_agg(jsonb_build_object('id', proposta_id, 'tipo', tipo, 'esito', esito))
                  FILTER (WHERE esito <> 'ok'), '[]'::jsonb) AS dettaglio_errori
  FROM esito_applica
\gset

-- 2. Le proposte non trattate oltre la finestra di validità diventano `scaduta` (mai cancellate).
SELECT trasi.scadi_proposte() AS scadute
\gset

-- 3. L'audit scritto da questo run: differenza sull'id, e conteggio per azione. Una scrittura di
--    dominio senza riga di audit resta il segnale che `v_scritture_senza_audit` intercetta; qui si
--    registra quante ne ha prodotte il flusso, così il criterio è verificabile dall'esterno.
SELECT count(*)                                        AS audit_run,
       count(*) FILTER (WHERE azione = 'applicata')     AS audit_applicata,
       count(*) FILTER (WHERE azione = 'transizione'
                          AND dopo->>'stato' = 'scaduta') AS audit_scadenza
  FROM trasi.audit WHERE id > :'audit_prima'::bigint
\gset

-- 4. Il registro: una riga per esecuzione, con l'esito aggregato.
INSERT INTO trasi.flusso_run (nome, trigger, inizio_ts, fine_ts, esito, n_righe, dettaglio)
VALUES ('applica', :'trigger', now(), now(),
        CASE WHEN :'errori'::int > 0 THEN 'parziale' ELSE 'ok' END,
        (:'applicate'::int + :'scadute'::int),
        jsonb_build_object(
          'applicate',        :'applicate'::int,
          'scadute',          :'scadute'::int,
          'errori',           :'errori'::int,
          'esaminate',        :'esaminate'::int,
          'limite',           :'limite'::int,
          'audit_run',        :'audit_run'::int,
          'audit_applicata',  :'audit_applicata'::int,
          'audit_scadenza',   :'audit_scadenza'::int,
          'errori_dettaglio', :'dettaglio_errori'::jsonb));

SELECT 'APPLICA' AS flusso, :'applicate' AS applicate, :'scadute' AS scadute,
       :'errori' AS errori, :'esaminate' AS esaminate, :'audit_run' AS audit_run;
COMMIT;
SQL

# `-v limite=… -v trigger=…`: passati come variabili psql, mai concatenati nel corpo.
uscita=$(printf '%s\n' "$CORPO" | psql_flussi -v "limite=$LIMIT" -v "trigger=$TRIGGER" -f - 2>&1)
stato=$?

if [[ $stato -ne 0 ]]; then
  echo "applica.sh: il flusso non ha concluso (exit $stato)" >&2
  echo "$uscita" >&2
  exit 1
fi

printf '%s\n' "$uscita"
echo "applica.sh: flusso concluso (trigger=$TRIGGER, limite=$LIMIT, via=$VIA)"
exit 0
