#!/usr/bin/env bash
# Trasi — ops/retention_chat.sh · la retention delle chat di Onyx (blocco B6, job delle 03:00).
#
# È il guscio host di `ops/retention_chat.py`: il lavoro vero lo fa quello, **dentro** il container di
# Onyx, perché servono il suo codice e il suo accesso a MinIO. Qui c'è ciò che dall'host si fa meglio:
# leggere il parametro dal database di Trasi, verificare che i container ci siano, misurare prima e
# dopo, e ritornare un exit code che il cron può registrare.
#
# **Perché non si esegue sul container `automazioni`**: i flussi notturni girano lì e parlano al
# *database Trasi*. Questo job parla al *database di Onyx* e usa il *codice di Onyx*. Metterlo in
# `automazioni` significherebbe montare il codice di Onyx in un container che non lo possiede, e dare
# a un esecutore del dominio i privilegi su un'altra applicazione. È il confine che V4 esiste per
# tenere: ogni servizio tocca il proprio database, e il coordinamento sta sull'host.
#
# **Il parametro arriva dal database, non da una costante qui.** `[P] gg_retention_chat` (30, §7.2) sta
# in `trasi.parametro`, che è la fonte unica dei parametri del progetto: il TI lo cambia con un
# `UPDATE`, senza modificare questo file e senza un deploy. Una soglia scritta in due posti è una
# soglia che prima o poi vale due valori diversi.
#
# Uso:
#     ops/retention_chat.sh                 # soglia da trasi.parametro
#     ops/retention_chat.sh --giorni 30     # soglia esplicita (per una prova)
#     ops/retention_chat.sh --dry-run       # mostra cosa cancellerebbe, non cancella
#     ops/retention_chat.sh --giorni 1 --dry-run   # prova reale: c'è qualcosa oltre 1 giorno
#
# Exit: 0 = eseguito senza errori; ≠0 altrimenti (il cron lo registra). **Una retention che non trova
# niente da cancellare esce 0**: non è un errore, è il caso normale di un sistema in equilibrio.
set -uo pipefail

cd "$(dirname "$0")/.."

GIORNI=""
DRY_RUN=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --giorni)  GIORNI="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "retention_chat.sh: argomento non riconosciuto: $1" >&2; exit 2 ;;
  esac
done

if [[ -f deployment/.env ]]; then
  set -a; . deployment/.env; set +a
fi
POSTGRES_USER="${POSTGRES_USER:-postgres}"
TRASI_DB="${TRASI_DB:-trasi_db}"
COMPOSE_FILE="deployment/docker-compose.yml"
SERVICE="db_trasi"
ONYX_CONTAINER="${ONYX_CONTAINER:-onyx-background-1}"

echo "Trasi · retention chat — $(date '+%Y-%m-%d %H:%M:%S %Z')"

# --- la soglia ----------------------------------------------------------------------------------
if [[ -z "$GIORNI" ]]; then
  # `trasi.parametro.chiave='gg_retention_chat'`. Se la riga manca **non si inventa 30**: si esce con
  # un errore. Un default silenzioso su una soglia di cancellazione è il modo in cui un parametro
  # assente diventa una cancellazione con la soglia sbagliata.
  GIORNI=$(docker compose -f "$COMPOSE_FILE" exec -T "$SERVICE" \
             psql -U "$POSTGRES_USER" -X -q -tA -d "$TRASI_DB" \
             -c "SELECT valore FROM trasi.parametro WHERE chiave='gg_retention_chat'" 2>/dev/null \
           | tr -d '[:space:]')
  if [[ -z "$GIORNI" ]]; then
    echo "retention_chat.sh: il parametro gg_retention_chat non è leggibile da trasi.parametro." >&2
    echo "retention_chat.sh: verifica che ${SERVICE} sia su e che db/003_parametri.sql sia applicato." >&2
    exit 1
  fi
  echo "  soglia: ${GIORNI} giorni (da trasi.parametro.gg_retention_chat)"
else
  echo "  soglia: ${GIORNI} giorni (esplicita, non dal parametro)"
fi

# --- precondizioni -------------------------------------------------------------------------------
if ! docker inspect "$ONYX_CONTAINER" --format '{{.State.Status}}' 2>/dev/null | grep -q running; then
  echo "retention_chat.sh: il container ${ONYX_CONTAINER} non è in esecuzione." >&2
  echo "retention_chat.sh: è il container di Onyx — la retention delle chat vive lì." >&2
  exit 1
fi

# --- l'esecuzione --------------------------------------------------------------------------------
ARGS=("$GIORNI")
[[ "$DRY_RUN" -eq 1 ]] && ARGS+=("--dry-run")

# Lo script si passa su **stdin**: non c'è bisogno di montare `ops/` nel container di Onyx, e quindi
# non si aggiunge un volume a un container che è di un'altra applicazione. È anche il motivo per cui
# questo file non ha bisogno di sapere dove sta l'installazione di Onyx.
docker exec -i "$ONYX_CONTAINER" python3 - "${ARGS[@]}" < ops/retention_chat.py
rc=$?

echo "retention_chat.sh: exit ${rc}"
exit "$rc"
