"""Chat assistita dentro Trasi: proxy **server-to-server** verso Onyx (scheda !NEW 6, US-6.2).

Perché un proxy e non un redirect — correzione #3 del piano, ed è la ragione per cui questo modulo esiste. La via
breve sarebbe mandare il browser sul sottodominio di Onyx: due domini, due login, e l'operatore esce dalla Home con
una persona davanti allo sportello. Qui invece il **browser non vede mai Onyx**: parla con lo shim (cookie di
sessione della Casa), e lo shim parla con Onyx come servizio. Onyx non sa che esiste un browser, il browser non sa
che esiste Onyx — vede una risposta con la sua fonte.

Tre scelte, e dove vivono:

- **L'identità della conversazione è quella della Casa.** La sessione del cookie dà la Casa; da `trasi.identita_onyx`
  si prende l'email **attiva** dell'operatore (`email LIKE 'op.%'`, non quella del gestore: è l'identità di
  sportello, la stessa che il piano usa per `op.san-bao`). La lettura è fatta come `shim_rw` e **fuori** dal ruolo
  della Casa: `identita_onyx` è leggibile solo da `shim_rw` (misurato: `SET ROLE casa_sanbao` → «permission denied»),
  ed è giusto così — è la mappa delle identità di servizio, non un dato della Casa.
- **Nessun segreto nel codice.** Il PAT arriva da `ONYX_CHAT_TOKEN` (ambiente, oppure `deployment/.env` come fanno i
  flussi: la suite gira anche da host, dove il compose non ha esportato nulla). Se manca, la chat risponde **503**
  con un motivo leggibile: un token assente è una configurazione mancante, non un guasto da far esplodere come 500.
- **V3 vale anche qui.** La fonte la compone lo **shim** dai metadati delle citazioni che Onyx restituisce
  (`top_documents[].metadata`), con le stesse funzioni di `badge.py` usate da `vicino_a` e dal biglietto. Se la
  componesse il modello, due risposte alla stessa domanda porterebbero due etichette diverse e la provenienza — il
  primo principio del progetto — non sarebbe più verificabile a colpo d'occhio.

**Limite dichiarato (V5/§12), scritto qui perché non si scopra dopo.** Il messaggio è testo libero dell'operatore e
il canale **non è filtrato a monte**: il piano dichiara che se l'operatore digita il nome o il telefono del cittadino,
quel testo arriva al provider insieme ai chunk RAG. Il filtro anti-PII di questo endpoint copre ciò che lo shim può
vedere (il messaggio in ingresso → 422 `dato_personale_sospetto`); la mitigazione del resto è nel prompt dell'assistente
e nel DPO, non in questo file.

**Nessun endpoint scrive il dominio.** La chat legge (una identità) e inoltra; `oggetto`, `proposta`, `audit` restano
dove sono. L'unica scrittura è di Onyx, nella sua memoria a retention 30 giorni.

**Limite misurato (da decidere, non da aggirare qui).** Onyx attribuisce la conversazione — e quindi le *tool call*
del LLM — al **proprietario del PAT**, non a un'intestazione della richiesta: verificato live, con
`X-Onyx-User-Email: op.san-bao@trasi.local` la chiamata del LLM a `vicino_a` arriva allo shim come
`admin@onyx-onice.example.com` → 403 «identità non riconosciuta». Con un PAT unico di servizio la chat risponde
dalla KB, ma gli strumenti del contratto non funzionano: la correzione è un PAT per identità (`op.<casa>@trasi.local`),
cioè una colonna/una tabella oltre a `identita_onyx` e un PAT per Casa in Onyx. L'intestazione qui sotto è
**dichiarativa** (dice a Onyx quale identità Trasi attribuisce alla conversazione), non un enforcement: quando i PAT
per Casa ci saranno, l'identità viaggia già nel punto giusto.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, FastAPI
from pydantic import BaseModel, ConfigDict, Field

from . import pii
from .auth import SessioneOperatore, sessione_corrente
from .badge import FUSO_ITALIANO, badge_esterna, badge_kb, nome_fonte
from .db import _pool_corrente
from .errori import errore

logger = logging.getLogger("trasi.shim")

router = APIRouter()

# `deployment/.env` è la stessa sorgente del compose e dei flussi. Da **container** questo percorso non esiste
# (il Dockerfile copia solo `app/` e `openapi.yaml`): là il token arriva dall'ambiente. Fuori dal container
# (suite pytest, diagnosi a mano) il file c'è ed è l'unico posto in cui il PAT vive senza finire nel codice.
PERCORSO_ENV = Path(__file__).resolve().parents[2] / "deployment" / ".env"

# Base URL di Onyx **vista dalla rete `trasi_net`**. Il default non è `http://nginx/api` come per le automazioni:
# quello presuppone che il chiamante stia anche su `onyx_default`, e lo shim **non** ci sta. Verificato dal
# container dello shim: `nginx` e `onyx-nginx-1` non risolvono (NXDOMAIN), `172.19.0.1` e `host.docker.internal`
# rifiutano la connessione, `onyx-api_server-1:8080` risponde 200 su `/health`. Se un domani lo shim entra nella
# rete di Onyx (raccomandato: `networks: [trasi_net, onyx_net]` nel compose), la variabile d'ambiente vince su
# questo default senza toccare una riga di codice.
URL_ONYX_DEFAULT = "http://onyx-api_server-1:8080"

# La variabile si chiama `ONYX_CHAT_API_URL` e **non** `ONYX_API_URL`, che è già presa: quel nome, in
# `deployment/.env`, è l'indirizzo di Onyx **per le automazioni e l'export KB** (`http://nginx/api`, il default
# di `docker-compose.automazioni.yml`) — un container che sta anche su `onyx_default`, dove l'alias `nginx`
# risolve. Lo shim sta solo su `trasi_net`, dove `nginx` **non** risolve: `socket.gethostbyname('nginx')` →
# `Name or service not known` (verificato).
#
# Il nome condiviso era una trappola silenziosa, e non ipotetica: `_variabile()` legge prima l'ambiente e poi
# `deployment/.env`, quindi bastava che `.env` contenesse `ONYX_API_URL=http://nginx/api` — cioè **esattamente
# quello che `.env.example` insegna a scrivere** — perché la chat usasse un indirizzo che da qui non esiste,
# fallendo con un errore di connessione al posto del default corretto. Misurato in questa stessa sessione:
# passando `ONYX_API_URL` allo shim nel compose, la chat smette di funzionare. Un nome di variabile è
# un'interfaccia: due servizi su reti diverse non possono condividerlo con due valori diversi.
#
# Nessun ripiego sul vecchio nome: leggerlo «solo se il nuovo manca» rimetterebbe in piedi la trappola, perché
# il caso in cui il nuovo manca è proprio quello in cui `ONYX_API_URL` è configurato — e sbagliato.
NOME_VARIABILE_URL = "ONYX_CHAT_API_URL"

# L'assistente «Trasi Casa» (id 2 in `shim/.onyx-kb.json`): quello che sta all'operatore con una persona davanti.
PERSONA_DEFAULT = 2

# Un LLM risponde in decine di secondi: i 3 s di `SHIM_TIMEOUT_S` vanno bene per Overpass, non per la chat. Il
# budget è dichiarato al chiamante e vale per l'**intera** conversazione (creazione sessione + invio messaggio).
#
# 120 e non 60, ed è una misura, non una preferenza: sulla istanza in esercizio tre domande reali all'assistente
# «Trasi Casa» hanno impiegato 31,8 s · 60,0 s · 67,9 s (cronometrate in `docker exec trasi-shim-1`, che è la stessa
# rete del container). Con 60 s la chat avrebbe risposto 503 su **due** domande su tre — e un 503 su una risposta che
# stava per arrivare è peggio di un'attesa: l'operatore ha una persona davanti e riprova. Il criterio del piano per la
# chat è «risposta < 2 min» (B7, §10): 120 s è quel criterio, 60 era una stima. Il valore resta configurabile
# (`ONYX_CHAT_TIMEOUT_S`) per chi vorrà stringerlo quando il modello sarà più rapido.
TIMEOUT_DEFAULT_S = 120

# Dettagli d'errore, in un punto solo: la forma della risposta è contratto, non una scelta locale.
DETAIL_CHAT_NON_CONFIGURATA = "chat non configurata: manca il token Onyx (ONYX_CHAT_TOKEN)"
DETAIL_CASA_SENZA_IDENTITA = "chat non configurata per questa Casa: nessuna identità Onyx attiva (op.…)"
DETAIL_CHAT_NON_DISPONIBILE = "chat non disponibile: Onyx non ha risposto entro il tempo dichiarato"
DETAIL_RISPOSTA_NON_LEGGIBILE = "risposta non leggibile dalla chat"

# La dichiarazione di assenza di fonte (V3): «non c'è fonte» è un'informazione, un'etichetta inventata no.
FONTE_NON_DICHIARATA = "nessuna fonte citata nella risposta"


class MessaggioIn(BaseModel):
    """Il corpo di `POST /op/chat`: **una** chiave, e nient'altro (`extra="forbid"`, V5).

    `messaggio` è testo libero fino a 2000 caratteri — il tetto è quello della chat interna e tiene una domanda di
    sportello con il contesto necessario. Nessun altro campo: la Casa viene dalla sessione, l'assistente dalla
    configurazione, l'identità da `identita_onyx`; un `casa`, un `persona_id` o un `token` nel corpo sarebbero
    tre modi per parlare a nome di qualcun altro.
    """

    model_config = ConfigDict(extra="forbid")

    messaggio: str = Field(
        min_length=1,
        max_length=2000,
        description="Domanda dell'operatore per l'assistente (max 2000 caratteri).",
    )


@dataclass(frozen=True)
class ConfigurazioneChat:
    """Dove sta Onyx e come ci si presenta: base, token, assistente, budget di tempo."""

    base_url: str
    token: str
    persona_id: int
    timeout_s: int


@dataclass(frozen=True)
class Conversazione:
    """Una risposta utilizzabile: il testo e il badge di provenienza (V3)."""

    testo: str
    fonte: str


@dataclass(frozen=True)
class Guasto:
    """Un esito non utilizzabile, con il `detail` **della diagnosi**: rete assente o risposta illeggibile.

    I due casi restano due valori e non un `None` condiviso: un container di Onyx spento e un modello che risponde
    senza testo si riparano in modi diversi, e un solo messaggio li renderebbe indistinguibili a chi legge il log
    dello sportello (§9.1: il guasto si legge, non si indovina).
    """

    detail: str


def _da_env_file(nome: str) -> str:
    """Un valore da `deployment/.env`, la stessa sorgente del compose. Mai stampato.

    Stessa forma di `flussi/comune.py`: la suite e le diagnosi girano **da host**, dove il compose non ha esportato
    le variabili, e leggere il file rende «da host» e «da container» lo stesso caso.
    """
    try:
        for riga in PERCORSO_ENV.read_text(encoding="utf-8").splitlines():
            riga = riga.strip()
            if riga.startswith(f"{nome}="):
                return riga.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        return ""
    return ""


def _intero(valore: str, default: int) -> int:
    """Un intero da configurazione, col default se il valore è assente o non numerico.

    Una configurazione sbagliata non deve far cadere la chat: il token mancante è già un 503 dichiarato, e un
    `ONYX_CHAT_TIMEOUT_S=60s` scritto male non deve diventare un 500 (regola §9.1).
    """
    try:
        numero = int(str(valore).strip())
    except (TypeError, ValueError):
        return default
    return numero if numero > 0 else default


def _variabile(nome: str) -> str:
    """Ambiente prima, `deployment/.env` poi: l'ambiente è ciò che il compose inietta, il file è il ripiego da host."""
    return (os.environ.get(nome) or _da_env_file(nome) or "").strip()


def configurazione() -> ConfigurazioneChat:
    """Base, token, assistente e budget, letti a ogni richiesta.

    Per-richiesta e non memorizzati: la rotazione del PAT e il cambio di assistente devono avere effetto senza
    riavviare il container (stessa scelta del TTL di sessione in `auth.py`), e il costo è una `read` su un file di
    poche righe davanti a una chiamata a un LLM che dura decine di secondi.
    """
    return ConfigurazioneChat(
        base_url=(_variabile(NOME_VARIABILE_URL) or URL_ONYX_DEFAULT).rstrip("/"),
        token=_variabile("ONYX_CHAT_TOKEN"),
        persona_id=_intero(_variabile("ONYX_PERSONA_ID"), PERSONA_DEFAULT),
        timeout_s=_intero(_variabile("ONYX_CHAT_TIMEOUT_S"), TIMEOUT_DEFAULT_S),
    )


async def email_onyx_della_casa(casa_id: int | None) -> str | None:
    """L'email Onyx **dell'operatore** della Casa, o `None` se la Casa non ne ha una attiva.

    Si legge come `shim_rw`, con una connessione del pool e **non** con la sessione della Casa: la transazione di
    `sessione_corrente` ha già fatto `SET LOCAL ROLE <ruolo_casa>`, e `casa_*` non ha `SELECT` su `identita_onyx`
    (misurato: «permission denied for table identita_onyx»). Non è una scorciatoia — è la stessa lettura che la
    dipendenza di Onyx fa per risolvere l'identità, e resta l'unica query non-Casa della richiesta.

    `email LIKE 'op.%'` e non `gestore.%`: è l'identità di sportello (decisione 2026-09-16), quella che il piano usa
    in B7 (`op.san-bao`). Una Casa senza riga attiva non ha una voce in Onyx: la chat lo dichiara, non la inventa.
    """
    if casa_id is None:
        # Una sessione senza Casa (es. ruolo `rete`) non ha un'identità di sportello da cui parlare.
        return None
    async with _pool_corrente().acquire() as conn:
        email = await conn.fetchval(
            """
            SELECT email
              FROM trasi.identita_onyx
             WHERE casa_id = $1 AND attiva AND email LIKE 'op.%'
             ORDER BY id
             LIMIT 1
            """,
            casa_id,
        )
    return email or None


def _testo_della_risposta(corpo: Any) -> str | None:
    """Il testo della risposta di Onyx, o `None` se non c'è niente di leggibile.

    La struttura è stata ispezionata sulla versione in esercizio (Onyx v4.7.2): `answer`, più `answer_citationless`,
    `error_msg`, `top_documents`, `citation_info`. Il fallback su `message` non è decorativo: è l'altro nome con cui
    una risposta di chat può arrivare, e cercarlo costa un `get` — dipendere da un solo nome di campo significherebbe
    che un giorno, senza toccare questo modulo, ogni risposta diventa «non leggibile».

    `error_msg` non nullo vale «non leggibile»: il messaggio d'errore di Onyx non viene rimandato al chiamante
    (potrebbe portare dettagli del provider) né registrato.
    """
    if not isinstance(corpo, dict) or corpo.get("error_msg"):
        return None
    for chiave in ("answer", "message"):
        valore = corpo.get(chiave)
        if isinstance(valore, str) and valore.strip():
            return valore.strip()
    return None


def _data_metadato(valore: Any) -> date | None:
    """`data_aggiornamento` dai metadati di Onyx (JSON: `"2026-09-15"`) come data, o `None` se non interpretabile."""
    if not isinstance(valore, str):
        return None
    try:
        return date.fromisoformat(valore.strip()[:10])
    except ValueError:
        return None


def _fiducia_metadato(valore: Any) -> int | None:
    """Il livello di affidabilità dai metadati (arriva come stringa nel JSON), o `None` se non è un intero."""
    try:
        return int(str(valore).strip())
    except (TypeError, ValueError):
        return None


def fonte_dal_corpo(corpo: Any, adesso: datetime) -> str:
    """Il badge di provenienza (V3) del **primo** documento citato da Onyx, composto dalle tre funzioni di `badge.py`.

    Onyx restituisce `top_documents` già ordinati per pertinenza e, per i documenti della KB Trasi, i metadati che
    l'export ha scritto (`fonte`, `data_aggiornamento`, `affidabilita`): sono la stessa informazione che alimenta il
    badge di `cerca_luogo` e del biglietto, quindi il badge qui è quello che l'operatore ha già imparato a leggere.
    Un documento `is_internet` è una fonte esterna e prende `badge_esterna` — «non verificata dalla rete», con l'ora
    della consultazione.

    Nessun documento citato → `FONTE_NON_DICHIARATA`. Il campo non resta vuoto e non inventa una fonte: la risposta
    senza citazioni è un caso che V3 vuole **visibile**, non nascosto.
    """
    documenti = corpo.get("top_documents") if isinstance(corpo, dict) else None
    if not isinstance(documenti, list):
        return FONTE_NON_DICHIARATA
    for documento in documenti:
        if not isinstance(documento, dict):
            continue
        metadati = documento.get("metadata") or {}
        if not isinstance(metadati, dict):
            metadati = {}
        # `autorita` è `None` di proposito: Onyx porta il `fonte` scritto dall'export («Rete-kb-3», «Comune di
        # Brindisi-3»), che è il nome tecnico con il suffisso di fiducia — la stessa forma che il badge della chat
        # ha sempre mostrato. Qui non si legge `trasi.fonte` per risalire al nome umano: sarebbe una query in più per
        # una sfumatura del badge, e la chat non è il posto in cui la provenienza si arricchisce.
        etichetta = nome_fonte(None, metadati.get("fonte") or documento.get("semantic_identifier"))
        if documento.get("is_internet"):
            return badge_esterna(etichetta, adesso)
        return badge_kb(
            etichetta,
            _data_metadato(metadati.get("data_aggiornamento")),
            _fiducia_metadato(metadati.get("affidabilita")),
        )
    return FONTE_NON_DICHIARATA


async def _conversa(
    configurazione_chat: ConfigurazioneChat, messaggio: str, email: str
) -> Conversazione | Guasto:
    """Crea la sessione di chat e manda il messaggio: testo+fonte, oppure la diagnosi del guasto. Mai un'eccezione.

    Due chiamate, una sola connessione: `create-chat-session` (assistente `persona_id`) e `send-chat-message` con
    `stream=false` — la risposta completa in JSON, che è quella di cui il proxy ha bisogno (con `stream=true` la
    risposta sarebbe un event-stream da riassemblare per mostrare un testo che qui non serve a nessuno).

    Il tempo è imposto **due volte**, e non è ridondanza: i timeout di `httpx` sono per fase (connessione, scrittura,
    lettura), quindi un `timeout=N` può valere `2N` sommando una connessione lenta a una lettura lenta — la stessa
    misura che in `vicinanza.py` ha portato a `asyncio.wait_for`. Il budget dichiarato (`ONYX_CHAT_TIMEOUT_S`) è
    quello della **coppia** di chiamate, perché è il tempo che il chiamante aspetta davvero.

    Ogni guasto — timeout, errore HTTP, corpo non JSON — diventa un `Guasto`: la decisione sullo status è di chi
    chiama, qui non si solleva nulla (§9.1, «mai eccezione al chiamante»).
    """
    intestazioni = {
        # Il PAT viaggia solo nell'header: mai in URL, mai nei log. `httpx` a INFO registra l'URL, e per questo
        # `main.py` lo zittisce — qui vale anche per l'email, che nell'URL non compare mai.
        "Authorization": f"Bearer {configurazione_chat.token}",
        "Content-Type": "application/json",
        # Dichiarativa: dice a Onyx quale identità Trasi attribuisce alla conversazione. Oggi Onyx attribuisce al
        # proprietario del PAT (verificato), quindi questo header non cambia le tool call; quando ci sarà un PAT per
        # identità, l'email è già nel punto giusto della richiesta.
        "X-Onyx-User-Email": email,
    }

    async def scambio() -> Conversazione | Guasto:
        async with httpx.AsyncClient(timeout=configurazione_chat.timeout_s, headers=intestazioni) as client:
            creazione = await client.post(
                f"{configurazione_chat.base_url}/chat/create-chat-session",
                json={"persona_id": configurazione_chat.persona_id, "description": None, "project_id": None},
            )
            creazione.raise_for_status()
            session_id = (creazione.json() or {}).get("chat_session_id")
            if not session_id:
                return Guasto(DETAIL_RISPOSTA_NON_LEGGIBILE)

            invio = await client.post(
                f"{configurazione_chat.base_url}/chat/send-chat-message",
                json={
                    "chat_session_id": session_id,
                    "message": messaggio,
                    "stream": False,
                    # -1 = nessun messaggio padre: la sessione è appena nata, quindi la domanda è la prima.
                    "parent_message_id": -1,
                },
            )
            invio.raise_for_status()
            corpo = invio.json()

        testo = _testo_della_risposta(corpo)
        if testo is None:
            return Guasto(DETAIL_RISPOSTA_NON_LEGGIBILE)
        return Conversazione(testo, fonte_dal_corpo(corpo, datetime.now(tz=ZoneInfo(FUSO_ITALIANO))))

    try:
        return await asyncio.wait_for(scambio(), timeout=configurazione_chat.timeout_s)
    except (TimeoutError, httpx.TimeoutException):
        logger.warning("chat: Onyx non ha risposto entro il tempo dichiarato")
        return Guasto(DETAIL_CHAT_NON_DISPONIBILE)
    except (httpx.HTTPError, ValueError):
        # Il corpo della risposta di Onyx non entra nel log: qui si registra il fatto, non il contenuto.
        logger.warning("chat: Onyx ha risposto con un errore o con un corpo non JSON")
        return Guasto(DETAIL_CHAT_NON_DISPONIBILE)


@router.post(
    "/chat",
    operation_id="op_chat",
    summary="Pone una domanda all'assistente della rete e riceve la risposta con la sua fonte (V3). "
    "L'operatore resta dentro Trasi: Onyx non vede il browser.",
    tags=["op"],
)
async def op_chat(
    corpo: MessaggioIn, sess: SessioneOperatore = Depends(sessione_corrente)
) -> dict[str, Any]:
    """POST /op/chat `{messaggio}` → 200 `{risposta, fonte}`; 401 senza sessione; 422 su dati personali; 503 se la chat non è configurata o Onyx non risponde.

    L'ordine dei controlli è deliberato: **prima** ciò che dipende solo dalla richiesta (PII: un messaggio con un
    telefono non deve arrivare al provider, e non deve nemmeno dipendere dalla configurazione), **poi** la
    configurazione (token, identità della Casa), **infine** la rete. Un 503 su token mancante non deve nascondere un
    422 su un dato personale — altrimenti l'operatore correggerebbe il testo solo dopo che qualcuno ha messo a posto
    il PAT.

    I due guasti della chat sono distinti e lo restano: «Onyx non risponde» (rete, timeout, errore HTTP) e «Onyx ha
    risposto qualcosa che non contiene un testo» sono due diagnosi diverse per chi legge il messaggio, e collassarle
    in un solo `detail` renderebbe indistinguibile un container spento da una risposta vuota del modello.

    Nessuna scrittura nel dominio: la chat legge un'identità e inoltra. L'audit non c'entra (V4 riguarda le scritture)
    e il messaggio non viene conservato da Trasi: l'unica memoria è quella di Onyx, a retention dichiarata.
    """
    pii.rifiuta_se_presente({"messaggio": corpo.messaggio})

    configurazione_chat = configurazione()
    if not configurazione_chat.token:
        raise errore(503, DETAIL_CHAT_NON_CONFIGURATA)

    email = await email_onyx_della_casa(sess.casa_id)
    if not email:
        raise errore(503, DETAIL_CASA_SENZA_IDENTITA)

    esito = await _conversa(configurazione_chat, corpo.messaggio, email)
    # Il ramo «guasto» si logga prima del raise: la traccia è best-effort e non deve far fallire la risposta,
    # ma deve rispondere a «è successo qualcosa» anche quando l'operatore non la vede (es. sessione Onyx lenta).
    if isinstance(esito, Guasto):
        await _log_chat_mensile(sess.casa_id, "sportello", "errore", None)
        raise errore(503, esito.detail)

    await _log_chat_mensile(sess.casa_id, "sportello", "risposta", _fonte_log(esito))
    return {"risposta": esito.testo, "fonte": esito.fonte}


def _fonte_log(esito: Conversazione) -> str:
    """La fonte della risposta come valore per `chat_interazione_log.fonte`: `kb`, `esterna` o `nessuna`.

    Il badge leggibile resta nella risposta al browser; qui si traduce nella forma che il database accetta,
    perché la tabella non conserva testo (V5) e serve a contare per k-anonimato, non a ricostruire il testo.
    """
    if esito.fonte.startswith("[Esterna"):
        return "esterna"
    if esito.fonte.startswith("[KB"):
        return "kb"
    return "nessuna"


async def _log_chat_mensile(casa_id: int | None, canale: str, esito: str, fonte: str | None) -> None:
    """Traccia la conversazione in `trasi.chat_interazione_log`. Mai far fallire la risposta all'operatore.

    È l'eccezione dichiarata al flusso proposte (come `messaggio`/`richiesta`): serve a contare quante volte la
    chat è stata usata e con quale esito, senza conservare il testo. Se il DB non accetta la riga, il log resta
    nel container e il flusso continua.
    """
    try:
        async with _pool_corrente().acquire() as conn:
            await conn.execute(
                """
INSERT INTO trasi.chat_interazione_log (casa_id, canale, esito, fonte)
VALUES ($1, $2, $3, $4)
                """,
                casa_id,
                canale,
                esito,
                fonte,
            )
    except Exception:
        logger.warning("log chat non scritto: la risposta resta valida")


def monta(applicazione: FastAPI) -> None:
    """Monta il router sotto `/op`, **fuori** dal documento OpenAPI.

    Il prefisso è lo stesso di `attrezzoteca` e `messaggi` perché è ciò che la UI chiama (`/api/shim/op/chat`,
    con Caddy che toglie `/api/shim`), e `include_in_schema=False` non è una formalità: lo schema che FastAPI genera
    è il contratto congelato con Onyx, e il gate V-09 lo verifica per uguaglianza — un endpoint del browser in più
    farebbe fallire `test_openapi_contract.py`. La visibilità non cambia: `include_in_schema` riguarda il documento,
    non il routing.
    """
    applicazione.include_router(router, prefix="/op", include_in_schema=False)


__all__ = [
    "DETAIL_CASA_SENZA_IDENTITA",
    "DETAIL_CHAT_NON_CONFIGURATA",
    "DETAIL_CHAT_NON_DISPONIBILE",
    "DETAIL_RISPOSTA_NON_LEGGIBILE",
    "FONTE_NON_DICHIARATA",
    "ConfigurazioneChat",
    "Conversazione",
    "Guasto",
    "MessaggioIn",
    "monta",
    "op_chat",
    "router",
]
