#!/usr/bin/env bash
# Trasi — ops/ciclo_mensile.sh · il ciclo mensile F5 (giorno 3, 08:00) — schedulazione (B6).
#
# **Questo file non implementa il ciclo mensile.** Il codice è `flussi/ciclo_mensile.py` (owner
# `trasi-flussi`, B6-FLW-02): lui sa quali sono i destinatari (`v_flusso_recapiti`), compone i
# digest con i quattro campi V6, gestisce il fallback AT per le Case senza `email_digest`, produce il
# CSV k-anonimo e scrive in `flusso_run`. Reimplementarlo qui avrebbe duplicato il presidio V6 e la
# catena di recapito — le due cose che non si vogliono avere in due copie.
#
# **Questo file fa tre cose sole**, ed è tutto ciò che serve perché la schedulazione stia da questa
# parte del confine:
#   1. verifica che **oggi sia il giorno del ciclo** secondo `trasi.parametro` (`giorno_ciclo_mensile`,
#      default 3). Il crontab non legge il database: la sua riga `0 8 3 * *` è fissa. Se il TI cambia
#      il parametro, senza questo controllo il digest partirebbe il giorno sbagliato — un messaggio
#      sbagliato, che è peggio di un messaggio mancante;
#   2. esegue il flusso **dentro** il container `automazioni`, che è dove vivono le credenziali
#      (`/run/trasi/env`) e il `job.sh` che le carica;
#   3. passa `TRASI_TRIGGER=cron`, così `flusso_run` distingue la notte da una diagnosi umana.
#
# Uso:
#     ops/ciclo_mensile.sh                 # esegue se oggi è il giorno del ciclo
#     ops/ciclo_mensile.sh --forza         # esegue comunque (il flusso ha il suo --forza per il mese)
#     ops/ciclo_mensile.sh --dry-run       # non esegue: mostra cosa farebbe e con quali parametri
#     ops/ciclo_mensile.sh --giorno 3      # verifica contro un giorno diverso (per una prova)
#
# Exit: 0 = eseguito (o correttamente saltato); ≠0 = errore reale.
# **«Non è il giorno del ciclo» esce 0**: un job che esce 1 quando non deve fare niente riempie un
# log di errori che non sono errori, e il giorno in cui c'è un errore vero nessuno lo guarda.
set -uo pipefail

cd "$(dirname "$0")/.."

FORZA=0
DRY_RUN=0
GIORNO_ATTESO=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --forza)    FORZA=1; shift ;;
    --dry-run)  DRY_RUN=1; shift ;;
    --giorno)   GIORNO_ATTESO="${2:-}"; shift 2 ;;
    -h|--help)  sed -n '2,26p' "$0"; exit 0 ;;
    *) echo "ciclo_mensile.sh: argomento non riconosciuto: $1" >&2; exit 2 ;;
  esac
done

if [[ -f deployment/.env ]]; then
  set -a; . deployment/.env; set +a
fi
POSTGRES_USER="${POSTGRES_USER:-postgres}"
TRASI_DB="${TRASI_DB:-trasi_db}"
COMPOSE_FILE="deployment/docker-compose.yml"
SERVICE="db_trasi"
CONTAINER="${AUTOMAZIONI_CONTAINER:-trasi-automazioni-1}"

echo "Trasi · ciclo mensile — $(date '+%Y-%m-%d %H:%M:%S %Z')"

# --- 1. che giorno è, secondo il parametro ------------------------------------------------------
# Il giorno atteso viene dal **parametro del progetto**, non da una costante: è la stessa disciplina
# di `retention_chat.sh` con `gg_retention_chat`. Un `3` scritto qui e un `3` scritto in
# `trasi.parametro` sono due cose che oggi coincidono e domani no.
if [[ -z "$GIORNO_ATTESO" ]]; then
  GIORNO_ATTESO=$(docker compose -f "$COMPOSE_FILE" exec -T "$SERVICE" \
                    psql -U "$POSTGRES_USER" -X -q -tA -d "$TRASI_DB" \
                    -c "SELECT valore FROM trasi.parametro WHERE chiave='giorno_ciclo_mensile'" 2>/dev/null \
                  | tr -d '[:space:]')
  if [[ -z "$GIORNO_ATTESO" ]]; then
    echo "ciclo_mensile.sh: il parametro giorno_ciclo_mensile non è leggibile da trasi.parametro." >&2
    echo "ciclo_mensile.sh: verifica che ${SERVICE} sia su e che db/003_parametri.sql sia applicato." >&2
    exit 1
  fi
  echo "  giorno atteso: ${GIORNO_ATTESO} (da trasi.parametro.giorno_ciclo_mensile)"
else
  echo "  giorno atteso: ${GIORNO_ATTESO} (esplicito, non dal parametro)"
fi

oggi=$(date +%-d)
if [[ "$oggi" != "$GIORNO_ATTESO" && "$FORZA" -eq 0 ]]; then
  echo "  oggi è il giorno ${oggi}, il ciclo è il giorno ${GIORNO_ATTESO}: nessuna azione."
  echo "  (per eseguirlo comunque: ops/ciclo_mensile.sh --forza)"
  exit 0
fi
[[ "$oggi" != "$GIORNO_ATTESO" ]] && echo "  oggi è il giorno ${oggi}, non ${GIORNO_ATTESO} — --forza attivo"

# --- 2. i prerequisiti --------------------------------------------------------------------------
if ! docker inspect "$CONTAINER" --format '{{.State.Status}}' 2>/dev/null | grep -q running; then
  echo "ciclo_mensile.sh: il container ${CONTAINER} non è in esecuzione." >&2
  echo "ciclo_mensile.sh: avvialo con: docker compose -f ${COMPOSE_FILE} up -d automazioni" >&2
  exit 1
fi
# La verifica che il codice ci sia **prima** di provare a eseguirlo: se `trasi-flussi` non l'ha
# ancora consegnato, l'errore deve dirlo esplicitamente. Un `docker exec` fallito con «No such file
# or directory» dal di dentro del container è un errore che si legge come «il container è rotto».
if ! docker exec "$CONTAINER" test -f /app/flussi/ciclo_mensile.py; then
  echo "ciclo_mensile.sh: /app/flussi/ciclo_mensile.py non esiste nel container." >&2
  echo "ciclo_mensile.sh: è il deliverable B6-FLW-02 (owner trasi-flussi) — non ancora consegnato?" >&2
  exit 1
fi

# --- 3. l'esecuzione ----------------------------------------------------------------------------
# `job.sh` carica le credenziali da `/run/trasi/env`: la stessa via dei job del crontab di B4, così
# le credenziali di `automazioni` non sono dichiarate due volte.
# `TRASI_TRIGGER=cron` è passato con `-e`: `cron` dell'host non entra nel container, e senza questa
# variabile il registro scriverebbe `trigger='manuale'` — una schedulazione che si dichiara
# intervento umano. (In `flussi/crontab` la stessa variabile è nel crontab del container, perché lì
# `cron` la legge; qui arriva dall'esterno.)
if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "  (dry-run) eseguirebbe:"
  echo "    docker exec -e TRASI_TRIGGER=cron ${CONTAINER} /app/flussi/job.sh /app/flussi/ciclo_mensile.py"
  exit 0
fi

echo "  eseguo: ciclo_mensile.py nel container ${CONTAINER} (trigger=cron)"
docker exec -e TRASI_TRIGGER=cron "$CONTAINER" /app/flussi/job.sh /app/flussi/ciclo_mensile.py
rc=$?
echo "  → exit ${rc}"
exit "$rc"
