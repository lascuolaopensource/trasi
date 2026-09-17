#!/usr/bin/env bash
# Trasi — flussi/notte.sh · la catena notturna completa, eseguibile a mano.
#
# Perché esiste, se c'è il crontab. Perché un flusso che si può far girare **solo** alle 5 del mattino
# è un flusso che nessuno prova e che nessuno ripara: questo wrapper esegue i sei passi in ordine,
# con lo stesso esito che avrebbero da cron, e serve a chi deve verificare («è passata la notte?»),
# a chi deve diagnosticare («perché la chat non cita il dato nuovo?») e alla verifica manuale del
# criterio §10 B4.
#
# Differenza con il crontab, dichiarata: il crontab esegue i passi **indipendenti** (un fallimento non
# ferma gli altri: l'export della KB non deve dipendere dall'alert). Questo wrapper propaga invece
# l'exit code — chi lo esegue a mano vuole sapere se *qualcosa* è andato storto.
#
# Fuori da questa catena, di proposito: `fonti_documenti.py` (file istituzionali ZIP/CSV/PDF → KB) è
# **settimanale** (crontab, domenica 01:30) perché le sue fonti cambiano una volta l'anno; non è uno
# dei sei passi e si prova a mano con `python3 flussi/fonti_documenti.py --dry-run`.
#
# Uso:
#     flussi/notte.sh                  # tutti e sei i passi
#     flussi/notte.sh --solo applica   # un solo passo
#     TRASI_TRIGGER=cron flussi/notte.sh   # dichiara il trigger nel registro
#     flussi/notte.sh --dry-run        # mostra cosa eseguirebbe
set -uo pipefail

cd "$(dirname "$0")/.."

# I sei passi, nell'ordine dell'architettura §6. Il nome è quello che compare in `flusso_run`.
PASSI=(export_kb applica fonti_ical fonti_http alert scadi_messaggi)
DICHIARAZIONE=(
  "F3  export KB → KB di Onyx (upsert per doc_id, mai duplicati)"
  "F9  applica + scadi → il dominio, con riga di audit per variazione"
  "F4  iCal → upsert diretto su evento (unica eccezione a V4)"
  "F4  HTTP → change-detection: crea proposte, non scrive"
  "F6  alert → proposte in attesa, coerenza fonti e schede evento, a chi decide"
  "F9  scadi_messaggi → elimina i messaggi letti oltre [P] (retention, mai dominio: registro)"
)

SOLO=""
DRY_RUN=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --solo)    SOLO="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
    *) echo "notte.sh: argomento non riconosciuto: $1" >&2; exit 2 ;;
  esac
done

if [[ -n "$SOLO" ]]; then
  trovato=0
  for passo in "${PASSI[@]}"; do [[ "$passo" == "$SOLO" ]] && trovato=1; done
  if [[ $trovato -eq 0 ]]; then
    echo "notte.sh: passo sconosciuto: ${SOLO} (ammessi: ${PASSI[*]})" >&2
    exit 2
  fi
fi

# L'ordine è significativo: `applica` (05:00) precede `fonti` (06:00) precede `alert` (07:30), così
# l'avviso delle 07:30 contiene anche ciò che la notte ha trovato. `scadi_messaggi` è ultimo: la
# retention dei messaggi letti non ha dipendenze sugli altri passi e chiude la notte.

# Trasporto verso il database, la stessa scelta di applica.sh: il passo SQL inline gira come
# `automazioni` (l'identità dei flussi), via `docker compose exec` da host o `psql` diretto nel
# container automazioni. Dichiarata una volta, usata dal solo passo che ne ha bisogno.
psql_flussi() {
  local compose_file="deployment/docker-compose.yml"
  local servizio="db_trasi"
  local db="${TRASI_DB:-trasi_db}"
  local ruolo="${TRASI_DB_ROLE:-automazioni}"
  local via="${TRASI_DB_VIA:-}"
  if [[ -z "$via" ]]; then
    if command -v docker >/dev/null 2>&1; then via=docker; else via=diretta; fi
  fi
  if [[ "$via" == "docker" ]]; then
    docker compose -f "$compose_file" exec -T "$servizio" \
      psql -U "$ruolo" -d "$db" -X -q --no-psqlrc -v ON_ERROR_STOP=1 "$@"
  else
    PGUSER="${PGUSER:-$ruolo}" PGDATABASE="${PGDATABASE:-$db}" \
      psql -X -q --no-psqlrc -v ON_ERROR_STOP=1 "$@"
  fi
}

esegui_scadi_messaggi() {
  # Un solo statement SQL con la sua riga di `flusso_run`, in una transazione: la scrittura è della
  # funzione `trasi.scadi_messaggi()` (SECURITY DEFINER di DBA, eccezione documentata a V4), qui c'è
  # solo la chiamata e la traccia — mai un DELETE scritto a mano nel flusso. Idempotente per
  # costruzione: una seconda esecuzione elimina 0 righe e lo registra.
  local trigger="${TRASI_TRIGGER:-manuale}"
  local uscita
  if ! uscita=$(psql_flussi -v "trigger=$trigger" -f - <<'SQL'
\set QUIET on
BEGIN;
SET LOCAL search_path = trasi, public, pg_temp;
SELECT trasi.scadi_messaggi() AS eliminate
\gset
INSERT INTO trasi.flusso_run (nome, trigger, inizio_ts, fine_ts, esito, n_righe, dettaglio)
VALUES ('scadi_messaggi', :'trigger', now(), now(), 'ok', :'eliminate'::int,
        jsonb_build_object('eliminate', :'eliminate'::int,
                           'retention_days', trasi.p_int('messaggi_retention_days')));
SELECT 'SCADI_MESSAGGI' AS flusso, :'eliminate' AS eliminate;
COMMIT;
SQL
); then
    echo "$uscita" >&2
    return 1
  fi
  printf '%s\n' "$uscita"
}

esegui_passo() {
  local passo="$1"
  case "$passo" in
    applica)        comando=(bash flussi/applica.sh) ;;
    export_kb)      comando=(python3 flussi/export_kb.py) ;;
    fonti_ical)     comando=(python3 flussi/fonti_ical.py) ;;
    fonti_http)     comando=(python3 flussi/fonti_http.py) ;;
    alert)          comando=(python3 flussi/alert.py) ;;
    scadi_messaggi)
      # Lo step è SQL inline: il dry-run si dichiara (come per `applica`), non si simula — un
      # `--dry-run` che non esegue `scadi_messaggi` sarebbe indistinguibile da un passo saltato.
      if [[ $DRY_RUN -eq 1 ]]; then
        echo "  (dry-run) NON eseguito: SELECT trasi.scadi_messaggi() — eliminerebbe i messaggi letti oltre retention"
        return 0
      fi
      esegui_scadi_messaggi
      return $?
      ;;
    *) echo "notte.sh: passo non implementato: $passo" >&2; return 2 ;;
  esac

  # `--dry-run` si propaga ai flussi che lo prevedono. `applica.sh` non lo ha: l'unica cosa che sa
  # fare è applicare, e un `--dry-run` che si limitasse a *non* eseguirlo sarebbe indistinguibile da
  # un passo saltato. Nel dry-run di `applica` si dichiara che non viene eseguito.
  if [[ $DRY_RUN -eq 1 ]]; then
    if [[ "$passo" == "applica" ]]; then
      echo "  (dry-run) NON eseguito: ${comando[*]} — applicherebbe le proposte approvate"
      return 0
    fi
    comando+=(--dry-run)
    echo "  (dry-run) ${comando[*]}"
    return 0
  fi
  "${comando[@]}"
}

echo "Trasi · catena notturna — $(date '+%Y-%m-%d %H:%M:%S %Z') · trigger=${TRASI_TRIGGER:-manuale}"
rc=0
eseguiti=0

for indice in "${!PASSI[@]}"; do
  passo="${PASSI[$indice]}"
  [[ -n "$SOLO" && "$passo" != "$SOLO" ]] && continue
  echo
  echo "── ${DICHIARAZIONE[$indice]}"
  if esegui_passo "$passo"; then
    echo "   → ${passo}: ok"
  else
    echo "   → ${passo}: FALLITO (exit $?)" >&2
    rc=1
  fi
  eseguiti=$((eseguiti + 1))
done

echo
if [[ $rc -eq 0 ]]; then
  echo "notte.sh: ${eseguiti} passi conclusi — «è passata la notte?» si verifica con:"
  echo "  psql -c \"SELECT nome, trigger, esito, n_righe, fine_ts FROM trasi.flusso_run ORDER BY id DESC LIMIT 10\""
else
  echo "notte.sh: almeno un passo è fallito; il registro dice quale:" >&2
  echo "  psql -c \"SELECT nome, esito, dettaglio FROM trasi.flusso_run WHERE esito <> 'ok' ORDER BY id DESC LIMIT 10\"" >&2
fi
exit "$rc"
