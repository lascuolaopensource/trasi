#!/usr/bin/env python3
# Trasi — ops/retention_chat.py · la retention delle chat di Onyx (blocco B6, §8 del piano).
#
# **Questo file gira DENTRO il container di Onyx** (`onyx-background-1`), non sull'host: ha bisogno
# del codice di Onyx per cancellare una chat nella stessa forma in cui la cancella Onyx. Viene
# invocato da `ops/retention_chat.sh` con
#
#     docker exec -i onyx-background-1 python3 - < ops/retention_chat.py <giorni>
#
# --------------------------------------------------------------------------------------------
# DOVE ONYX CONSERVA LE CHAT, E SE HA UNA RETENTION NATIVA
# --------------------------------------------------------------------------------------------
# Verificato in prima persona su questa installazione (Onyx v4.7.2, `onyxdotapp/onyx-backend`), non
# dedotto dalla documentazione. I risultati, con i comandi che li producono, sono in
# `docs/verifiche.md`.
#
# **Dove**: PostgreSQL `postgres` sul container `onyx-relational_db-1`, tabelle
# `chat_session` (54 righe) e `chat_message` (210 righe), legate da
# `chat_message.chat_session_id → chat_session.id ON DELETE CASCADE`. Verificato con
# `\d chat_message`. Un messaggio non ha una tabella propria in un altro posto: sta lì.
# I file allegati alle chat stanno invece **fuori** dal database, nel bucket MinIO
# `onyx-file-store-bucket` (`onyx-minio-1`), referenziati da `chat_message.files` (12 messaggi) e
# registrati in `file_record` (245 righe). È il motivo per cui questo script usa la funzione di
# cancellazione di Onyx invece di un `DELETE`: `delete_chat_session` rimuove **anche** gli oggetti su
# MinIO (`delete_messages_and_files_from_chat_session`), e un `DELETE` a mano lascerebbe i file lì —
# una cancellazione che cancella i metadati e conserva i dati non è una cancellazione.
#
# **Retention nativa: esiste, ed è inutilizzabile su questa installazione.** Onyx ha una retention
# di chat con TTL: `maximum_chat_retention_days` nelle settings, consumata dal task Celery
# `check_ttl_management_task` → `perform_ttl_management_task`
# (`backend/ee/onyx/background/celery/tasks/ttl_management/tasks.py`), schedulato da `beat` ogni
# `CHECK_TTL_MANAGEMENT_TASK_FREQUENCY_IN_HOURS` (1 ora). **Il beat lo esegue davvero**:
#
#     $ docker logs onyx-background-1 | grep check-ttl-management | tail -1
#     beat.py:279 : celery.beat Scheduler: Sending due task check-ttl-management-public
#
# **Ma è chiuso dal tier.** In `backend/onyx/server/settings/api.py:119-124`:
#
#     if (merged.maximum_chat_retention_days != existing.maximum_chat_retention_days
#             and not tier_at_least(current_tier, Tier.ENTERPRISE)):
#         raise OnyxError(OnyxErrorCode.FEATURE_NOT_AVAILABLE,
#                         "Chat history retention requires the Enterprise plan.")
#
# Questa installazione è **Community**: `ENABLE_PAID_ENTERPRISE_EDITION_FEATURES=false`,
# `license` → **0 righe**, `get_tier()` → `Tier.COMMUNITY`. Misurato:
#
#     $ curl -X PATCH .../api/admin/settings -d '{"maximum_chat_retention_days": 30}'
#     {"error_code":"FEATURE_NOT_AVAILABLE","detail":"Chat history retention requires the Enterprise plan."}
#     HTTP 402
#
# E quindi il task nativo non fa nulla, perché `should_perform_chat_ttl_check(None, …)` esce subito
# (`ee/onyx/background/celery_utils.py:16`: `if not retention_limit_days: return False`). La catena
# è: beat invia il task ogni ora → il task legge una soglia che è `None` → nessuna cancellazione.
# **Container sano, beat vivo, retention ferma.** È esattamente il modo in cui questo difetto non si
# vede.
#
# **Il gap, dichiarato senza inventare niente**: non esiste un interruttore di configurazione che
# attivi la retention su questa installazione. Le due strade sono (a) una licenza Enterprise per
# Onyx, oppure (b) la cancellazione periodica di questo script. **Non** si aggira il gate scrivendo
# il valore direttamente in `key_value_store`, e la ragione va detta con precisione perché è una
# tentazione concreta: il codice EE **è presente** in questa immagine
# (`is_ee_version()` → `True`, perché `LICENSE_ENFORCEMENT_ENABLED` è attivo di default nel sorgente),
# e il task gira già ogni ora — quindi un `UPDATE` sulla KV lo farebbe effettivamente funzionare.
# Ma sarebbe (1) l'aggiramento di un controllo di **licenza**, che non è una scelta di ingegneria;
# (2) un deployment la cui interfaccia **rifiuta** con 402 la configurazione che il database contiene,
# cioè un sistema che dichiara uno stato che non può mostrare; (3) una cancellazione di dati
# governata da un interruttore che nessuna schermata amministra, e quindi non tracciato per chi
# risponde della retention. Se il TI vuole la strada nativa, la strada è la licenza — non una riga
# scritta a mano nel KV store.
#
# La strada (b) è quella che il piano prevede come fallback
# (`§6 S2: «Cron 03:00 retention chat — retention nativa Onyx se disponibile, altrimenti script API
# nel container automazioni»`), ed è questo script.
#
# --------------------------------------------------------------------------------------------
# COME CANCELLA
# --------------------------------------------------------------------------------------------
# Usa **le stesse funzioni del task nativo**, non una `DELETE` propria:
#
#   * `get_chat_sessions_older_than(days, …)` — la stessa selezione del codice EE. La definizione di
#     «vecchia» è quindi identica a quella che userebbe Onyx: **ultima attività** (`max(time_sent)`
#     dei messaggi, o `time_created` per una sessione senza messaggi). Una chat vecchia ma ancora in
#     uso non viene toccata — che è il comportamento corretto e quello che l'utente si aspetta.
#   * `delete_chat_session(…, include_deleted=True, hard_delete=True)` — la stessa cancellazione,
#     con la rimozione dei file su MinIO e le CASCADE di `tool_call`, `chat_message__search_doc`,
#     `chat_message__standard_answer`.
#   * `SqlEngine.init_engine()` — l'inizializzazione del motore che fa il worker Celery all'avvio.
#     Senza, `get_session_with_current_tenant` solleva «Engine not initialized».
#
# **Idempotenza**: rieseguire nello stesso giorno non cancella niente di nuovo (le sessioni già
# cancellate non sono più selezionate: sono righe che non esistono più). Il conteggio in output è la
# prova.
#
# Uso (dentro il container):
#     python3 - < ops/retention_chat.py 30            # cancella le chat più vecchie di 30 giorni
#     python3 - < ops/retention_chat.py 30 --dry-run  # mostra quali, senza cancellare
#
# Exit: 0 = eseguito (anche se non c'era niente da cancellare); 1 = errore.
import sys

DRY_RUN = "--dry-run" in sys.argv
giorni = None
for arg in sys.argv[1:]:
    if not arg.startswith("-"):
        try:
            giorni = float(arg)
        except ValueError:
            print(f"retention_chat: giorni non numerico: {arg}", file=sys.stderr)
            sys.exit(2)

if giorni is None:
    print("retention_chat: manca il numero di giorni di retention.", file=sys.stderr)
    sys.exit(2)

if giorni <= 0:
    # Una retention a 0 giorni cancellerebbe **tutto**, incluso ciò che è appena stato scritto: è la
    # differenza fra un parametro sbagliato e la perdita di tutte le chat. Si rifiuta.
    print(f"retention_chat: rifiuto — giorni={giorni} cancellerebbe ogni chat.", file=sys.stderr)
    sys.exit(2)

from sqlalchemy import func, select  # noqa: E402

from onyx.db.chat import delete_chat_session, get_chat_sessions_older_than  # noqa: E402
from onyx.db.models import ChatMessage, ChatSession  # noqa: E402
from onyx.db.engine.sql_engine import (  # noqa: E402
    SqlEngine,
    get_session_with_current_tenant,
)
from onyx.server.settings.store import load_settings  # noqa: E402

# `init_engine` come fa il worker: senza, le sessioni del database non si aprono.
SqlEngine.init_engine(pool_size=5, max_overflow=2)


def conta(modello: type) -> int:
    """Il conteggio di una tabella, via ORM.

    Non si costruisce una stringa SQL con il nome della tabella (`SELECT count(*) FROM {nome}`):
    le due tabelle sono note, e una query costruita a stringa è una query che un giorno qualcuno
    userà con un nome che viene da fuori. `select(func.count())` non ha questo problema.
    """
    with get_session_with_current_tenant() as db:
        return int(db.execute(select(func.count()).select_from(modello)).scalar() or 0)


# Il valore **nativo** di Onyx, letto per trasparenza: se un giorno la licenza Enterprise arriva e
# qualcuno imposta `maximum_chat_retention_days`, questo script lo dice invece di applicare in
# silenzio una soglia diversa da quella che Onyx crede di avere. Due retention che non si conoscono
# fra loro sono peggio di una sola.
nativa = load_settings().maximum_chat_retention_days

sessioni_prima = conta(ChatSession)
messaggi_prima = conta(ChatMessage)

with get_session_with_current_tenant() as db:
    vecchie = get_chat_sessions_older_than(giorni, db, limit=None)

print(f"retention_chat: soglia {giorni} giorni · retention nativa di Onyx: "
      f"{nativa if nativa is not None else 'non impostata (Community — v. testa del file)'}")
print(f"retention_chat: chat_session={sessioni_prima} · chat_message={messaggi_prima} · "
      f"sessioni oltre la soglia: {len(vecchie)}")

if not vecchie:
    print("retention_chat: niente da cancellare (idempotente: nessuna sessione oltre la soglia)")
    sys.exit(0)

if DRY_RUN:
    # In dry-run si elencano le sessioni che **sarebbero** cancellate, con la loro età: è
    # l'informazione che serve per decidere se la soglia è giusta prima di applicarla.
    # L'età è quella che usa la selezione: `max(time_sent)` dei messaggi, con `time_created` come
    # ripiego per una sessione senza messaggi — la stessa definizione di «vecchia» di Onyx.
    print(f"retention_chat: (dry-run) NON cancello. Prime {min(10, len(vecchie))} sessioni:")
    with get_session_with_current_tenant() as db:
        for _user_id, session_id in vecchie[:10]:
            ultima = db.execute(
                select(
                    func.coalesce(
                        select(func.max(ChatMessage.time_sent))
                        .where(ChatMessage.chat_session_id == session_id)
                        .scalar_subquery(),
                        select(ChatSession.time_created)
                        .where(ChatSession.id == session_id)
                        .scalar_subquery(),
                    )
                )
            ).scalar()
            print(f"    {session_id}  ultima attività: {ultima}")
    sys.exit(0)

# La cancellazione, una sessione per volta e ognuna nel proprio commit — esattamente come fa il task
# nativo. Un errore su una sessione non ferma le altre: una chat che non si riesce a cancellare
# (un file bloccato su MinIO, un lock) non deve impedire la retention di tutte le altre.
cancellate = 0
errori = 0
for _user_id, session_id in vecchie:
    try:
        with get_session_with_current_tenant() as db:
            delete_chat_session(
                None, session_id, db, include_deleted=True, hard_delete=True
            )
        cancellate += 1
    except Exception as exc:  # noqa: BLE001
        # Si stampa l'eccezione **e si continua**: il conteggio degli errori è l'esito, e un log che
        # si ferma alla prima eccezione non dice quante sessioni restano.
        errori += 1
        print(f"retention_chat: errore su {session_id}: {type(exc).__name__}: {exc}", file=sys.stderr)

sessioni_dopo = conta(ChatSession)
messaggi_dopo = conta(ChatMessage)
print(f"retention_chat: cancellate {cancellate} sessioni ({errori} errori) · "
      f"chat_session {sessioni_prima}→{sessioni_dopo} · chat_message {messaggi_prima}→{messaggi_dopo}")

sys.exit(1 if errori else 0)
