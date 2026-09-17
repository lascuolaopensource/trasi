#!/usr/bin/env bash
# Trasi — ops/provenienza_stack.sh
# Dice **quale codice sta girando davvero** nello stack, e se è quello di questo checkout.
#
#   ops/provenienza_stack.sh            # dichiara l'origine e il verdetto
#   ops/provenienza_stack.sh --riga     # una riga sola (da incollare in un report)
#
# Esce 0 se lo stack vivo è quello di questo checkout, 1 se è **di un altro** (con il dettaglio).
#
# ------------------------------------------------------------------------------------------------
# PERCHÉ QUESTO SCRIPT ESISTE (il difetto che lo ha reso necessario)
# ------------------------------------------------------------------------------------------------
# Il progetto compose si chiama `name: trasi` — **uno solo**, condiviso da tutti i worktree. Chiunque
# ricostruisca un'immagine impone il proprio branch a tutte le sessioni che poi lo interrogano.
#
# Misurato il 2026-09-16: lo shim in esecuzione era stato costruito da
# `/root/orca/workspaces/onice/installazione-connettori-mancanti/deployment` e serviva **12
# operazioni** (`+ /cerca_opendata`, `/leggi_dataset`) invece delle **10** di `main`, con dentro un
# modulo `shim/app/opendata.py` che in `HEAD` **non esiste**.
#
# La conseguenza non è tecnica, è epistemica: chi verifica lo stack senza saperlo **misura il codice di
# qualcun altro** e attribuisce i difetti alla codebase sbagliata. Una verifica che non distingue «la
# codebase» da «l'istanza viva» non è una verifica.
#
# ------------------------------------------------------------------------------------------------
# COSA GUARDA: tre indizi indipendenti, perché uno solo può ingannare
# ------------------------------------------------------------------------------------------------
# 1. **`com.docker.compose.project.working_dir`** — il percorso da cui Docker Compose ha costruito il
#    container. È l'indizio più diretto: se non è il `deployment/` di questo checkout, l'istanza è di
#    un altro.
# 2. **I moduli presenti nell'immagine ma assenti in `git ls-files`** — un file non tracciato in
#    `shim/app/` è lavoro in corso di qualcuno, e non è un giudizio: è un fatto.
# 3. **Il numero di operazioni del contratto** (`^  /` in `openapi.yaml`) — un intero, confrontabile in
#    un secondo fra container e checkout.
#
# Non usa l'hash dei file: un'immagine può essere ricostruita dallo stesso codice con hash diversi, e
# un hash diverso non dice *di chi* è il codice — che è esattamente la domanda.
set -euo pipefail

cd "$(dirname "$0")/.."

RIGA=0
[[ "${1:-}" == "--riga" ]] && RIGA=1

RADICE_CHECKOUT="$(pwd)"
SERVIZIO="trasi-shim-1"

if ! docker inspect "$SERVIZIO" --format '{{.State.Running}}' 2>/dev/null | grep -q true; then
  echo "provenienza_stack: il container $SERVIZIO non è in esecuzione" >&2
  exit 2
fi

# --- 1. chi ha costruito ----------------------------------------------------------------
WORKING_DIR="$(docker inspect "$SERVIZIO" \
  --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' 2>/dev/null || echo "")"
ATTESO="$RADICE_CHECKOUT/deployment"
STESSO_CHECKOUT=0
[[ "$WORKING_DIR" == "$ATTESO" ]] && STESSO_CHECKOUT=1

# --- 2. moduli non tracciati ------------------------------------------------------------
# `git ls-files shim/app` dà i file versionati; ciò che è nell'immagine e non nell'elenco è lavoro in
# corso (o un file rimasto da un'immagine vecchia: entrambe cose da sapere).
NELL_IMAGE="$(docker exec "$SERVIZIO" sh -c 'ls /app/app 2>/dev/null' | grep -v '__pycache__' | sort || true)"
TRACCIATI="$(git ls-files shim/app | xargs -n1 basename 2>/dev/null | sort || true)"
NON_TRACCIATI="$(comm -23 <(printf '%s\n' "$NELL_IMAGE") <(printf '%s\n' "$TRACCIATI") | grep -v '^$' || true)"
N_NON_TRACCIATI="$(printf '%s\n' "$NON_TRACCIATI" | grep -c . || true)"

# --- 3. operazioni del contratto --------------------------------------------------------
OP_VIVA="$(docker exec "$SERVIZIO" sh -c "grep -cE '^  /' /app/openapi.yaml" 2>/dev/null || echo "?")"
OP_LOCALE="$(grep -cE '^  /' shim/openapi.yaml 2>/dev/null || echo "?")"

# --- verdetto ---------------------------------------------------------------------------
# «Diverso» = uno qualunque dei tre indizi discorda. Il verdetto è sul **congiunto**, non su un
# singolo indizio: un'immagine stantia dello stesso checkout è legittima (nessuno ha ricostruito), un
# modulo non tracciato no.
DIVERSO=0
[[ "$OP_VIVA" != "$OP_LOCALE" ]] && DIVERSO=1
[[ "$N_NON_TRACCIATI" -ne 0 ]] && DIVERSO=1
[[ "$STESSO_CHECKOUT" -eq 0 ]] && DIVERSO=1

BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "(sconosciuto)")"
COMMIT="$(git rev-parse --short HEAD 2>/dev/null || echo "(sconosciuto)")"

if [[ "$RIGA" -eq 1 ]]; then
  if [[ "$DIVERSO" -eq 0 ]]; then
    echo "stack: questo checkout ($BRANCH@$COMMIT) · $OP_VIVA operazioni · nessun modulo estraneo"
  else
    echo "stack: NON questo checkout — costruito da $WORKING_DIR · $OP_VIVA operazioni contro $OP_LOCALE di $BRANCH@$COMMIT · moduli estranei: ${NON_TRACCIATI//$'\n'/, }"
  fi
  exit $(( DIVERSO ))
fi

echo "provenienza_stack: quale codice sta girando"
echo
echo "  checkout locale     : $RADICE_CHECKOUT"
echo "  branch              : $BRANCH @ $COMMIT"
echo "  container           : $SERVIZIO"
echo "  costruito da        : ${WORKING_DIR:-(etichetta assente)}"
echo "  operazioni contratto: $OP_VIVA (istanza viva) vs $OP_LOCALE (checkout)"
echo "  moduli non tracciati: $N_NON_TRACCIATI"
if [[ "$N_NON_TRACCIATI" -ne 0 ]]; then
  printf '      %s\n' $NON_TRACCIATI
fi
echo

if [[ "$DIVERSO" -eq 0 ]]; then
  echo "  VERDETTO: l'istanza viva è questo checkout. Le misure sullo stack valgono per $BRANCH@$COMMIT."
  exit 0
fi

cat <<'AVVISO'
  VERDETTO: l'istanza viva NON è questo checkout.

  Cosa significa: misurando lo stack stai misurando il codice di un'altra sessione, non quello
  di questo checkout. Non attribuire i difetti dell'una all'altro, in nessuna delle due direzioni.

  Cosa NON fare: `docker compose build`/`up`/`restart` per "allineare".
  Lo stack è condiviso: sovrascriveresti lavoro non committato di qualcun altro.

  Cosa fare, invece:
    * nei report, dichiarare l'origine dell'istanza misurata (questo output);
    * per verificare il TUO codice, usare un worktree isolato o i test in-process;
    * se serve davvero allineare lo stack, concordarlo con chi lo usa — è una decisione, non un fix.
AVVISO
exit 1
