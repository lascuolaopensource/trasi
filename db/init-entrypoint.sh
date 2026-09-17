#!/usr/bin/env bash
# Trasi — db/init-entrypoint.sh · inizializzazione one-shot del database di dominio.
#
# Fa le stesse cose di db/apply.sh, ma senza dipendere da docker compose exec: gira come
# servizio `db_init` del compose (anche sotto Coolify, dove non c'è un `.env` locale del repo).
# Idempotente come apply.sh: i file girano in una transazione con ON_ERROR_STOP=1.
#
# Due passate: alcuni file fanno riferimento a tabelle definite più avanti nell'ordine
# (misurato: db/006_fn_proposte.sql crea v_scritture_senza_audit che legge trasi.oggetto,
# definita in db/014_attrezzoteca.sql). La seconda passata parte quando tutto lo strato
# esiste: le NOTICE «already exists, skipping» sono il comportamento idempotente atteso.
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

# ---------------------------------------------------------------- password shim_rw ------------
# 000_roles.sql crea shim_rw ma la password la passa apply.sh da deployment/.env (che qui non
# c'è): se la variabile c'è, la imposta qui. Senza password, l'autenticazione dello shim fallisce.
if [ -n "${SHIM_DB_PASSWORD:-}" ]; then
  psql -c "ALTER ROLE shim_rw WITH PASSWORD '${SHIM_DB_PASSWORD}';" > /dev/null
  echo "[db_init] password shim_rw impostata"
fi

# ---------------------------------------------------------------- strato dati di dominio ------
applica_passata() {
  local passata=$1
  local falliti=""
  for file in $(ls "$DB_DIR"/[0-9]*.sql 2>/dev/null | sort); do
    base=$(basename "$file")
    echo "[db_init] passata $passata → $base" >&2
    if ! psql -v ON_ERROR_STOP=1 -q -f "$file" > /dev/null; then
      echo "[db_init] rinvio a passata $((passata+1)): $base" >&2
      falliti="$falliti $base"
    fi
  done
  echo "$falliti"
}

risultato1=$(applica_passata 1)
if [ -n "${risultato1// /}" ]; then
  risultato2=$(applica_passata 2)
  if [ -n "${risultato2// /}" ]; then
    echo "[db_init] FALLITI alla seconda passata: $risultato2" >&2
    exit 1
  fi
fi

echo "[db_init] completato"