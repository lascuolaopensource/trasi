#!/usr/bin/env bash
# Trasi — flussi/provisiona.sh · la password di `automazioni`.
#
# `automazioni` è l'unico ruolo dei flussi e si connette **via TCP** dal proprio container
# (hostname `db_trasi`), dove `pg_hba.conf` richiede `scram-sha-256`. Un ruolo LOGIN senza password
# non autentica: il container `automazioni` partirebbe e ogni notte fallirebbe con
# «fe_sendauth: no password supplied» — un guasto che nessun exit code del build segnala.
#
# Cosa fa:
#   1. genera una password se `AUTOMAZIONI_DB_PASSWORD` non è già in `deployment/.env`;
#   2. la scrive in `deployment/.env` (mode 600, gitignored) — il valore non viene **mai** stampato;
#   3. la imposta sul ruolo con `ALTER ROLE automazioni WITH LOGIN PASSWORD …` (idempotente);
#   4. verifica la connessione da host con quella password.
#
# Perché la password sta in `deployment/.env` e non nel compose: è un segreto, e quel file è la
# sorgente che il compose legge — la stessa scelta già fatta per `SHIM_DB_PASSWORD` e per la PAT di
# Onyx. Il compose la passa come `PGPASSWORD`, che non compare in `docker inspect` in chiaro più di
# quanto non compaia già qualsiasi variabile d'ambiente di un container.
#
# Uso:
#     flussi/provisiona.sh            # genera (se serve), applica, verifica
#     flussi/provisiona.sh --rotate   # rigenera la password e la sostituisce
set -euo pipefail

cd "$(dirname "$0")/.."

COMPOSE_FILE="deployment/docker-compose.yml"
SERVICE="db_trasi"
ENV_FILE="deployment/.env"
RUOLO="automazioni"
CHIAVE="AUTOMAZIONI_DB_PASSWORD"
ROTATE=0
[[ "${1:-}" == "--rotate" ]] && ROTATE=1

[[ -f "$ENV_FILE" ]] || { echo "provisiona.sh: manca $ENV_FILE" >&2; exit 1; }
DB="$(sed -n 's/^TRASI_DB=//p' "$ENV_FILE" | head -1)"
ADMIN="$(sed -n 's/^POSTGRES_USER=//p' "$ENV_FILE" | head -1)"
DB="${DB:-trasi_db}"; ADMIN="${ADMIN:-postgres}"

psql_admin() {
  docker compose -f "$COMPOSE_FILE" exec -T "$SERVICE" psql -U "$ADMIN" -d "$DB" -X -q "$@"
}

# --- 1. La password: quella esistente, o una nuova -------------------------------------------
esistente="$(sed -n "s/^${CHIAVE}=//p" "$ENV_FILE" | head -1)"
if [[ $ROTATE -eq 1 || -z "$esistente" ]]; then
  # `openssl rand -base64 | tr -d '/+='`: URL-safe e senza caratteri che il parser di `.env`
  # o la riga di comando potrebbero interpretare. 32 caratteri: la stessa lunghezza usata per gli
  # altri segreti dello stack.
  if command -v openssl >/dev/null 2>&1; then
    nuova="$(openssl rand -base64 48 | tr -d '/+=' | head -c 32)"
  else
    # Fallback senza openssl: /dev/urandom con `base64`. Meno elegante, stessa entropia.
    nuova="$(head -c 48 /dev/urandom | base64 | tr -d '/+=' | head -c 32)"
  fi
  if [[ -z "$esistente" ]]; then
    printf '\n# Ruolo applicativo dei flussi notturni (B4). Generata da flussi/provisiona.sh.\n# Usata dal container `automazioni` (PGPASSWORD). Mai stampata.\n%s=%s\n' \
      "$CHIAVE" "$nuova" >> "$ENV_FILE"
  else
    # Sostituzione in place, senza mai mostrare il valore.
    tmp="$(mktemp)"
    sed "s|^${CHIAVE}=.*|${CHIAVE}=${nuova}|" "$ENV_FILE" > "$tmp"
    cat "$tmp" > "$ENV_FILE"; rm -f "$tmp"
  fi
  echo "provisiona.sh: password di ${RUOLO} ${esistente:+ruotata}${esistente:-generata} e scritta in ${ENV_FILE}"
else
  echo "provisiona.sh: password di ${RUOLO} già presente in ${ENV_FILE} (usa --rotate per rigenerarla)"
fi
chmod 600 "$ENV_FILE"

# `ALTER ROLE` richiede il valore: lo si legge e lo si passa come **variabile psql**, mai sulla riga
# di comando (che finirebbe in `ps` e nella history del container).
password="$(sed -n "s/^${CHIAVE}=//p" "$ENV_FILE" | head -1)"

# --- 2. Il ruolo -----------------------------------------------------------------------------
# `ALTER ROLE … LOGIN PASSWORD :'pw'` con `:'pw'` quotato da psql: il valore non è mai concatenato.
printf "ALTER ROLE %s WITH LOGIN PASSWORD :'pw';\n" "$RUOLO" \
  | psql_admin -v ON_ERROR_STOP=1 -v "pw=${password}" -f - > /dev/null
echo "provisiona.sh: ${RUOLO} ha una password (valore non stampato)"

# --- 3. Verifica: la stessa via del container -----------------------------------------------
# Dal container `automazioni` la connessione è TCP verso `db_trasi`; qui si prova la stessa via con
# l'immagine del servizio, se c'è. Senza, si verifica via TCP dall'host (127.0.0.1), che è la stessa
# riga di `pg_hba` (`host all all … scram-sha-256`) e quindi la stessa autenticazione.
if docker image inspect trasi-automazioni:local >/dev/null 2>&1; then
  esito="$(docker run --rm --network trasi_net \
    -e PGHOST=db_trasi -e PGUSER="$RUOLO" -e PGDATABASE="$DB" -e PGPASSWORD="$password" \
    --entrypoint psql trasi-automazioni:local -X -q -tAc \
    "SELECT session_user || ' / ' || current_user || ' / exec=' || \
            has_function_privilege('${RUOLO}', 'trasi.applica_proposte_approvate(int)', 'EXECUTE')" \
    2>&1 | tail -1)"
  via="container automazioni → db_trasi (TCP)"
else
  esito="$(docker compose -f "$COMPOSE_FILE" exec -T "$SERVICE" \
    env PGPASSWORD="$password" psql -h 127.0.0.1 -U "$RUOLO" -d "$DB" -X -q -tAc \
    "SELECT session_user || ' / ' || current_user || ' / exec=' || \
            has_function_privilege('${RUOLO}', 'trasi.applica_proposte_approvate(int)', 'EXECUTE')" \
    2>&1 | tail -1)"
  via="host → 127.0.0.1 (TCP)"
fi

if [[ "$esito" == *"${RUOLO} / ${RUOLO}"* ]]; then
  echo "provisiona.sh: verifica OK via ${via} → ${esito}"
else
  echo "provisiona.sh: verifica FALLITA via ${via} → ${esito}" >&2
  exit 1
fi
