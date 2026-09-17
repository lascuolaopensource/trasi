#!/usr/bin/env bash
# Trasi — ops/provisiona_utenti_onyx.sh
# Crea in Onyx gli utenti di `trasi.identita_onyx` che non esistono ancora.
#
#   ops/provisiona_utenti_onyx.sh --dry-run     # dice cosa farebbe, non scrive
#   ops/provisiona_utenti_onyx.sh               # crea gli utenti mancanti
#   ops/provisiona_utenti_onyx.sh --password X  # password esplicita (altrimenti: generata e stampata)
#
# ------------------------------------------------------------------------------------------------
# PERCHÉ QUESTO SCRIPT ESISTE (il difetto che lo ha reso necessario)
# ------------------------------------------------------------------------------------------------
# Il seed `db/010_seed_case.sql` dichiara **22 identità**: `op.<slug>` e `gestore.<slug>` per 10 Case,
# più `rete` e `ti`. In Onyx ne esistevano **6** (`op.san-bao`, `gestore.san-bao`, `op.bozzano`,
# `gestore.bozzano`, `rete`, `ti`), create a mano in B3. Le altre **16** — 8 Case con i loro due
# operatori — esistevano nel database ma **non avevano un accesso**: nessuno di loro poteva entrare in
# chat. La documentazione riferiva prove su «10 Case»: 10 nel database, 2 usabili.
#
# Creato a mano una volta, il difetto si ripresenta identico alla prossima Casa o al prossimo
# operatore. Da qui uno script: il provisioning è configurazione, e una configurazione che vive solo
# in una sessione non è riproducibile.
#
# ------------------------------------------------------------------------------------------------
# PERCHÉ COSÌ: i tre vincoli che hanno deciso l'implementazione
# ------------------------------------------------------------------------------------------------
# 1. **Non si scrive `INSERT` a mano.** Onyx 4.7.2 verifica la password con **argon2id** e il formato
#    dell'hash non è replicabile a mano in modo affidabile. Qui l'hash lo calcola `PasswordHelper` **di
#    Onyx**, dentro il container che ha la stessa versione del codice: l'hash che ne esce è, per
#    costruzione, quello che il login si aspetta. (Verificato: `$argon2id$v=19$m=65536,t=3,p=4$…`,
#    identico per forma a quello delle 6 utenze preesistenti.)
#
# 2. **Non si usa `POST /api/auth/register`.** Quell'endpoint valida l'email con `email_validator`, che
#    rifiuta i domini riservati: `@trasi.local` è **special-use** e viene respinto con 422. È anche il
#    motivo per cui le 6 utenze esistenti sono state create fuori dall'API. (Il fatto che quell'endpoint
#    sia aperto e raggiungibile da internet è un problema **separato e più grave**, segnalato nel report:
#    qui non lo si usa, ma non è questo script a chiuderlo.)
#
# 3. **`effective_permissions` non si dimentica.** È una colonna **denormalizzata** di `user`: il ruolo
#    (`UserRole`) è un tombstone mai letto, e con `[]` ogni scrittura risponde **403** con un messaggio
#    che non spiega perché. È la trappola già pagata in B3 (lezione 2 di `docs/verifiche.md`) e la
#    ragione per cui questo script la popola esplicitamente con `["basic"]`, come le 6 esistenti.
#
# Idempotente: chi esiste **non** viene toccato (né la sua password né i suoi permessi). Rieseguirlo
# dopo aver aggiunto una Casa al seed crea solo i nuovi.
set -euo pipefail

cd "$(dirname "$0")/.."

SERVIZIO_DB="onyx-relational_db-1"
SERVIZIO_API="onyx-api_server-1"
DB_ONYX="postgres"
DB_TRASI="trasi_db"

DRY_RUN=0
PASSWORD=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)  DRY_RUN=1; shift ;;
    --password) PASSWORD="${2:?--password vuole un valore}"; shift 2 ;;
    *) echo "opzione non riconosciuta: $1" >&2; exit 2 ;;
  esac
done

# --- precondizioni: i container rispondono? ------------------------------------------------
for c in "$SERVIZIO_DB" "$SERVIZIO_API"; do
  if ! docker inspect "$c" --format '{{.State.Running}}' 2>/dev/null | grep -q true; then
    echo "provisiona_utenti_onyx: il container $c non è in esecuzione" >&2
    exit 1
  fi
done

psql_onyx() { docker exec -i "$SERVIZIO_DB" psql -U postgres -d "$DB_ONYX" -X -q -v ON_ERROR_STOP=1 "$@"; }
psql_trasi() {
  docker compose -f deployment/docker-compose.yml exec -T db_trasi \
    psql -U postgres -d "$DB_TRASI" -X -q -v ON_ERROR_STOP=1 "$@"
}

# --- 1. Chi manca? Il confronto è fra le DUE fonti di verità --------------------------------
# `identita_onyx` dice chi deve esistere; `user` dice chi esiste. Il difetto era esattamente lo scarto
# fra queste due, quindi lo scarto è ciò che si calcola — non una lista scritta qui, che invecchierebbe.
echo "provisiona_utenti_onyx: confronto identita_onyx (Trasi) con user (Onyx)"
ATTESI="$(psql_trasi -tAc "SELECT email FROM trasi.identita_onyx WHERE attiva ORDER BY email")"
PRESENTI="$(psql_onyx -tAc "SELECT email FROM \"user\" ORDER BY email")"

MANCANTI="$(comm -23 <(printf '%s\n' "$ATTESI" | sort) <(printf '%s\n' "$PRESENTI" | sort) | grep -v '^$' || true)"
N_ATTESI="$(printf '%s\n' "$ATTESI" | grep -c . || true)"
N_PRESENTI_ATTESI="$(comm -12 <(printf '%s\n' "$ATTESI" | sort) <(printf '%s\n' "$PRESENTI" | sort) | grep -c . || true)"
N_MANCANTI="$(printf '%s\n' "$MANCANTI" | grep -c . || true)"

echo "  attese da identita_onyx : $N_ATTESI"
echo "  già presenti in Onyx    : $N_PRESENTI_ATTESI"
echo "  da creare               : $N_MANCANTI"

if [[ "$N_MANCANTI" -eq 0 ]]; then
  echo "provisiona_utenti_onyx: niente da fare (idempotente)"
  exit 0
fi
printf '  %s\n' $MANCANTI

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "provisiona_utenti_onyx: (dry-run) NON creo nulla"
  exit 0
fi

# --- 2. La password -------------------------------------------------------------------------
# Una sola password per gli account di servizio della rete: sono account di sportello, condivisi da chi
# lavora in quella Casa, e una password per utente moltiplicherebbe i posti in cui un segreto va
# custodito senza aumentare la sicurezza — chi ha accesso alla Casa ha accesso all'account.
# Se non è data, si genera e si **stampa una volta sola**: senza, gli account sarebbero inutilizzabili.
GENERATA=0
if [[ -z "$PASSWORD" ]]; then
  PASSWORD="$(openssl rand -base64 24 | tr -d '/+=' | head -c 20)"
  GENERATA=1
fi

# --- 3. Gli hash, calcolati da Onyx ---------------------------------------------------------
# Un hash per email: la stessa password produce hash diversi (salt casuale), ed è corretto.
# La password NON passa da `psql` né dalla riga di comando di `docker exec`: entra nello stdin di un
# interprete Python dentro il container, che stampa solo l'hash.
echo "provisiona_utenti_onyx: calcolo gli hash con il codice di Onyx (argon2id)"
# Un solo flusso su stdin: **prima la password**, poi le email una per riga. Non due redirezioni (una
# pipe per le email e un `<<<` per la password): `<<<` sovrascrive la pipe e il Python riceverebbe solo
# la password, con zero email e zero hash — e il passo successivo inserirebbe nulla "con successo".
HASH_JSON="$(
  { printf '%s\n' "$PASSWORD"; printf '%s\n' $MANCANTI; } | \
  docker exec -i "$SERVIZIO_API" python -c '
import json, sys
from fastapi_users.password import PasswordHelper

password = sys.stdin.readline().rstrip("\n")        # la password, dal canale: mai in argv
emails = [riga.strip() for riga in sys.stdin if riga.strip()]
helper = PasswordHelper()
print(json.dumps({e: helper.hash(password) for e in emails}))
'
)"

# Il controllo che conta: tanti hash quante sono le email attese. Senza, un flusso vuoto passerebbe.
N_HASH="$(printf '%s' "$HASH_JSON" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))' 2>/dev/null || echo 0)"
if [[ "$N_HASH" -ne "$N_MANCANTI" ]]; then
  echo "provisiona_utenti_onyx: ERRORE — calcolati $N_HASH hash su $N_MANCANTI attesi" >&2
  exit 1
fi

# --- 4. L'inserimento, in transazione unica --------------------------------------------------
# Una transazione sola: o nascono tutti gli utenti, o nessuno. Un provisioning a metà è lo stato
# peggiore — metà Case dentro, metà fuori, e nessun modo di sapere dove si è fermato.
echo "provisiona_utenti_onyx: creo $N_MANCANTI utenti"
{
  echo "BEGIN;"
  printf '%s' "$HASH_JSON" | python3 -c '
import json, sys
d = json.load(sys.stdin)
for email, hashed in sorted(d.items()):
    # Apostrofi nell email: nessuna (sono generate da uno slug), ma la quota si raddoppia per sicurezza.
    e = email.replace("\x27", "\x27\x27")
    h = hashed.replace("\x27", "\x27\x27")
    # `effective_permissions` = ["basic"]: la colonna denormalizzata che decide le 403 silenziose.
    print(f"""INSERT INTO \"user\" (id, email, hashed_password, is_active, is_superuser, is_verified,
                                 role, visible_assistants, hidden_assistants, account_type,
                                 effective_permissions)
VALUES (gen_random_uuid(), \x27{e}\x27, \x27{h}\x27, true, false, true,
        \x27BASIC\x27, \x27[]\x27::jsonb, \x27[]\x27::jsonb, \x27STANDARD\x27, \x27[\"basic\"]\x27::jsonb);""")
'
  echo "COMMIT;"
} | psql_onyx

# --- 5. Verifica: il conteggio, non l'intenzione --------------------------------------------
# Le due fonti di verità devono ora coincidere: se lo scarto è 0, il provisioning è completo.
NUOVI="$(psql_onyx -tAc "SELECT email FROM \"user\" ORDER BY email")"
RESIDUI="$(comm -23 <(printf '%s\n' "$ATTESI" | sort) <(printf '%s\n' "$NUOVI" | sort) | grep -v '^$' || true)"
N_RESIDUI="$(printf '%s\n' "$RESIDUI" | grep -c . || true)"

if [[ "$N_RESIDUI" -ne 0 ]]; then
  echo "provisiona_utenti_onyx: ERRORE — restano $N_RESIDUI identità senza utente:" >&2
  printf '  %s\n' $RESIDUI >&2
  exit 1
fi

echo "provisiona_utenti_onyx: OK — $N_ATTESI/$N_ATTESI identità hanno un utente Onyx"
if [[ "$GENERATA" -eq 1 ]]; then
  echo
  echo "  ┌─────────────────────────────────────────────────────────────────────────┐"
  echo "  │ PASSWORD GENERATA — annotala ora, non è recuperabile da qui.            │"
  echo "  │ Vale per TUTTI gli account creati in questa esecuzione.                 │"
  echo "  └─────────────────────────────────────────────────────────────────────────┘"
  echo "  $PASSWORD"
  echo
  echo "  Gli account già esistenti NON sono stati toccati: la loro password è immutata."
fi
