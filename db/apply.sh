#!/usr/bin/env bash
# Trasi — db/apply.sh
# Applica lo strato dati nell'ordine del contratto B1 ed è IDEMPOTENTE: due esecuzioni di fila,
# entrambe exit 0.
#
#   ./db/apply.sh              applica tutto
#   ./db/apply.sh 000 001      applica solo i prefissi indicati (utile in corso d'opera)
#
# Regole:
#   * ogni script gira in una transazione con ON_ERROR_STOP=1 (psql -1): un errore = rollback + exit 1;
#   * 000_roles.sql gira come utente amministratore del container (CREATE ROLE / GRANT ruolo→ruolo
#     richiedono CREATEROLE, che trasi_owner non ha per contratto);
#   * i file che non esistono vengono saltati con NOTICE (i db/005-006 sono di un altro worker e
#     possono non essere ancora presenti: l'ordine li prevede, non li pretende);
#   * la password di shim_rw non compare mai in output: è passata come variabile psql da deployment/.env.
set -euo pipefail

cd "$(dirname "$0")/.."

COMPOSE_FILE="deployment/docker-compose.yml"
SERVICE="db_trasi"
DB="${TRASI_DB:-trasi_db}"
ADMIN="${POSTGRES_USER:-postgres}"

# --- credenziali: solo da deployment/.env (mode 600), mai sulla riga di comando né nei log -------
if [[ -f deployment/.env ]]; then
  set -a; . deployment/.env; set +a
  DB="${TRASI_DB:-trasi_db}"
  ADMIN="${POSTGRES_USER:-postgres}"
fi
SHIM_PW="${SHIM_DB_PASSWORD:-}"

psql_admin() { docker compose -f "$COMPOSE_FILE" exec -T "$SERVICE" psql -U "$ADMIN" -d "$DB" -X -q "$@"; }
psql_owner() {
  if [[ -n "${SHIM_PW}" ]]; then
    docker compose -f "$COMPOSE_FILE" exec -T "$SERVICE" \
      psql -U "$ADMIN" -d "$DB" -X -q -v ON_ERROR_STOP=1 -v shim_pw="$SHIM_PW" "$@"
  else
    docker compose -f "$COMPOSE_FILE" exec -T "$SERVICE" \
      psql -U "$ADMIN" -d "$DB" -X -q -v ON_ERROR_STOP=1 "$@"
  fi
}

# La 000 definisce i ruoli: se manca QUALSIASI ruolo atteso, la 000 gira comunque (è idempotente).
ORDER=(000_roles.sql 001_schema.sql 002_rls.sql 003_parametri.sql 004_views.sql
       005_rls_proposta.sql 006_fn_proposte.sql 007_dash.sql 008_eventi.sql
       010_seed_case.sql 011_seed_fonti.sql 012_seed_luoghi.sql)

# filtri opzionali da riga di comando (prefissi)
FILTERS=("$@")
selected() {
  [[ ${#FILTERS[@]} -eq 0 ]] && return 0
  local f; for f in "${FILTERS[@]}"; do [[ "$1" == "$f"* ]] && return 0; done
  return 1
}

# --- precondizioni ---------------------------------------------------------------
if ! docker compose -f "$COMPOSE_FILE" ps --format '{{.Service}} {{.State}}' 2>/dev/null | grep -q "^${SERVICE} running"; then
  echo "apply.sh: il servizio ${SERVICE} non è in esecuzione (docker compose -f ${COMPOSE_FILE} up -d ${SERVICE})" >&2
  exit 1
fi

if ! psql_admin -tAc "SELECT 1 FROM pg_extension WHERE extname='postgis'" | grep -q 1; then
  echo "apply.sh: PostGIS non installato in ${DB} — atteso dal B0 (V-03a)" >&2
  exit 1
fi

echo "apply.sh: db=${DB} amministratore=${ADMIN} (le password non vengono stampate)"
rc=0
for f in "${ORDER[@]}"; do
  selected "$f" || continue
  if [[ ! -f "db/$f" ]]; then
    echo "  skip   db/$f (assente)"
    continue
  fi
  t0=$(date +%s)
  if [[ "$f" == 000_* ]]; then
    # amministratore: ruoli e schema (la transazione è unica, ON_ERROR_STOP via -v)
    if psql_owner -1 -f - < "db/$f" > /tmp/trasi_apply_$f.log 2>&1; then
      echo "  ok     db/$f ($(( $(date +%s) - t0 ))s)"
    else
      echo "  ERRORE db/$f"; cat /tmp/trasi_apply_$f.log >&2; rc=1; break
    fi
  else
    # utente amministratore che impersona trasi_owner dentro lo script (SET ROLE): un solo percorso,
    # così il controllo degli oggetti resta quello dell'owner e non del superuser.
    if psql_owner -1 -f - < "db/$f" > /tmp/trasi_apply_$f.log 2>&1; then
      echo "  ok     db/$f ($(( $(date +%s) - t0 ))s)"
    else
      echo "  ERRORE db/$f"; cat /tmp/trasi_apply_$f.log >&2; rc=1; break
    fi
  fi
done

exit "$rc"
