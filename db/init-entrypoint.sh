#!/usr/bin/env bash
# Trasi — db/init-entrypoint.sh · inizializzazione one-shot del database di dominio.
#
# Fa le stesse cose di db/apply.sh, ma senza dipendere da docker compose exec: gira come
# servizio `db_init` del compose (anche sotto Coolify, dove non c'è un `.env` locale del repo).
# Idempotente come apply.sh: i file girano in una transazione con ON_ERROR_STOP=1.
#
# Variabili attese (dal compose):
#   PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE  — connessione amministratore
#   TRASI_DB                                        — nome del DB di dominio
#   SHIM_DB_PASSWORD                                — password del ruolo applicativo shim_rw
#   NOCODB_DB_NAME                                  — database di NocoDB, creato se assente
set -euo pipefail

DB_DIR="/db"
cd "$DB_DIR"

echo "[db_init] target: ${PGHOST}:${PGPORT}/${PGDATABASE} utente=${PGUSER}"

# ---------------------------------------------------------------- database di NocoDB ----------
# NocoDB vuole un database proprio (le sue migrazioni toccano `public`, che sul dominio non è suo).
if [ -n "${NOCODB_DB_NAME:-}" ]; then
  esiste=$(psql -Atc "SELECT 1 FROM pg_database WHERE datname = '${NOCODB_DB_NAME}'")
  if [ "$esiste" != "1" ]; then
    echo "[db_init] creo il database NocoDB: ${NOCODB_DB_NAME}"
    psql -c "CREATE DATABASE ${NOCODB_DB_NAME};"
  else
    echo "[db_init] database NocoDB già presente: ${NOCODB_DB_NAME}"
  fi
fi

# ---------------------------------------------------------------- strato dati di dominio ------
# Stesso ordine del contratto B1: 000 ruoli, poi schema, RLS, e il resto in ordine di file.
echo "[db_init] applico i file SQL in $DB_DIR"
for file in $(ls "$DB_DIR"/[0-9]*.sql 2>/dev/null | sort); do
  base=$(basename "$file")
  echo "[db_init] → $base"
  if ! psql -v ON_ERROR_STOP=1 -q -f "$file"; then
    # apply.sh salta con NOTICE i file di altri worker: qui lo stesso, con fallimento esplicito.
    echo "[db_init] FALLITO: $base" >&2
    exit 1
  fi
done

echo "[db_init] completato"