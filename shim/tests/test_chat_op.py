"""Chat dentro Trasi: proxy server-to-server verso Onyx (scheda !NEW 6, US-6.2).

Onyx è **mockato** (`respx`): il proxy non si prova chiamando un LLM, si prova su ciò che il proxy decide — quale
identità usa, cosa risponde quando il token manca, che fonte dichiara (V3), cosa fa quando Onyx non c'è. Un test che
dipendesse da quello che il modello risponde davvero proverebbe il modello, non questo modulo.

Il database non serve: `_pool_corrente` è sostituito da una spia che registra le query e restituisce l'identità
preparata dal test. È la stessa forma usata da `test_identita.py`, e serve a due cose che un database vero non
permetterebbe di provare: **quale** query viene eseguita (il `LIKE 'op.%'` che sceglie l'operatore e non il gestore) e
quante volte viene toccato il database prima di un rifiuto.

La configurazione si prepara con `monkeypatch`, e `PERCORSO_ENV` viene puntato a un file inesistente: senza,
`deployment/.env` diventerebbe una seconda fonte di verità e un `ONYX_CHAT_TOKEN` aggiunto là cambierebbe l'esito del
test «token mancante» senza che nessuno tocchi questo file.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx
import pytest
import respx

import ambiente

BASE_ONYX = "http://onyx-di-prova:8080"
TOKEN_DI_PROVA = "onyx_pat_di_prova_non_reale"
URL_CREA = f"{BASE_ONYX}/chat/create-chat-session"
URL_INVIA = f"{BASE_ONYX}/chat/send-chat-message"

# Il dettaglio del 503 quando la risposta di Onyx non contiene un testo: ripetuto a mano, non letto dal codice che
# lo produce (se il messaggio cambia senza una decisione, questo test deve fallire).
DETAIL_CHAT_NON_CONFIGURATA = "chat non configurata: manca il token Onyx (ONYX_CHAT_TOKEN)"
DETAIL_CASA_SENZA_IDENTITA = "chat non configurata per questa Casa: nessuna identità Onyx attiva (op.…)"
DETAIL_CHAT_NON_DISPONIBILE = "chat non disponibile: Onyx non ha risposto entro il tempo dichiarato"
DETAIL_RISPOSTA_NON_LEGGIBILE = "risposta non leggibile dalla chat"
FONTE_NON_DICHIARATA = "nessuna fonte citata nella risposta"
DETAIL_DATO_PERSONALE_SOSPETTO = "dato_personale_sospetto"

CASA_SANBAO = 5
EMAIL_OPERATORE = "op.san-bao@trasi.local"
MESSAGGIO = "Dove si fa l'ISEE vicino alla Casa?"


# --- doppi: pool e sessione -----------------------------------------------------------------------------------


class PoolSpia:
    """Un pool che registra le query e restituisce l'identità preparata dal test.

    `identita` a `None` significa «questa Casa non ha un'identità di operatore attiva»: è il caso della Casa con
    il solo `gestore.…`, cioè l'unica riga che `email LIKE 'op.%'` non sceglie.
    """

    def __init__(self, identita: str | None = EMAIL_OPERATORE) -> None:
        self.identita = identita
        self.query: list[tuple[str, tuple[Any, ...]]] = []
        self.acquisizioni = 0

    def acquire(self) -> "Acquisizione":
        self.acquisizioni += 1
        return Acquisizione(self)


class Acquisizione:
    """Il context manager di `pool.acquire()` (asyncpg lo espone così)."""

    def __init__(self, pool: PoolSpia) -> None:
        self.pool = pool

    async def __aenter__(self) -> "ConnessioneSpia":
        return ConnessioneSpia(self.pool)

    async def __aexit__(self, *_: Any) -> bool:
        return False


class ConnessioneSpia:
    """La connessione: registra la query (così il test legge il SQL davvero eseguito) e risponde."""

    def __init__(self, pool: PoolSpia) -> None:
        self.pool = pool

    async def fetchval(self, sql: str, *args: Any) -> Any:
        self.pool.query.append((sql, args))
        return self.pool.identita


class SessioneFinta:
    """La sessione dell'operatore: l'unica cosa che `op_chat` usa è `casa_id` (l'identità è della Casa)."""

    def __init__(self, *, casa_id: int | None = CASA_SANBAO) -> None:
        self.casa_id = casa_id
        self.ruolo = "casa_sanbao"
        self.casa_slug = "san-bao"
        self.email = ""


@pytest.fixture
def app_cliente(monkeypatch, tmp_path):
    """`TestClient` sull'app reale: sessione sostituita, token e base URL di Onyx dall'ambiente di prova."""
    monkeypatch.setattr("app.chat.PERCORSO_ENV", tmp_path / "env-inesistente")
    monkeypatch.setenv("ONYX_CHAT_TOKEN", TOKEN_DI_PROVA)
    monkeypatch.setenv("ONYX_CHAT_API_URL", BASE_ONYX)
    monkeypatch.delenv("ONYX_CHAT_TIMEOUT_S", raising=False)
    monkeypatch.delenv("ONYX_PERSONA_ID", raising=False)
    ambiente.configura_ambiente()

    from fastapi.testclient import TestClient

    from app import auth
    from app import chat as modulo_chat
    from app import main as modulo_main

    def costruisci(
        sessione: SessioneFinta | None = None, pool: PoolSpia | None = None
    ) -> tuple[TestClient, PoolSpia]:
        pool = pool or PoolSpia()
        monkeypatch.setattr(modulo_chat, "_pool_corrente", lambda: pool)
        applicazione = modulo_main.crea_app()
        applicazione.dependency_overrides[auth.sessione_corrente] = lambda: sessione or SessioneFinta()
        return TestClient(applicazione, raise_server_exceptions=False), pool

    return costruisci


def _invia(client: TestClient, messaggio: str = MESSAGGIO, **extra: Any):
    return client.post("/op/chat", json={"messaggio": messaggio, **extra})


def _corpo_onyx(
    answer: str = "Il CAF La Rosa, in via…",
    *,
    documents: list[dict[str, Any]] | None = None,
    error_msg: str | None = None,
) -> dict[str, Any]:
    """La risposta di `/chat/send-chat-message` nella forma reale (ispezionata su Onyx v4.7.2)."""
    return {
        "answer": answer,
        "answer_citationless": answer,
        "pre_answer_reasoning": None,
        "tool_calls": [],
        "top_documents": documents or [],
        "citation_info": [],
        "message_id": 298,
        "chat_session_id": "c244ac59-a8a7-427d-ac1d-852f89b1ee49",
        "incognito": False,
        "error_msg": error_msg,
    }


def _documento_kb(fonte: str = "Rete-kb-3", data: str = "2026-09-15", affidabilita: str = "3") -> dict[str, Any]:
    """Un documento della KB Trasi, con i metadati che scrive l'export (`flussi/export_kb.py`)."""
    return {
        "document_id": "trasi%3Aluogo%3A13",
        "semantic_identifier": "CAF La Rosa",
        "link": "",
        "source_type": "ingestion_api",
        "is_internet": False,
        "metadata": {"fonte": fonte, "data_aggiornamento": data, "affidabilita": affidabilita},
    }


def _documento_esterno() -> dict[str, Any]:
    """Un documento di ricerca web: Onyx lo marca `is_internet`."""
    return {
        "document_id": "internet__1",
        "semantic_identifier": "ANSA",
        "link": "https://www.ansa.it",
        "source_type": "web",
        "is_internet": True,
        "metadata": {},
    }


def _mock_onyx(
    *, risposta: dict[str, Any] | None = None, creazione: httpx.Response | None = None
) -> None:
    """Prepara le due chiamate del proxy: creazione sessione e invio messaggio."""
    respx.post(URL_CREA).mock(
        return_value=creazione or httpx.Response(200, json={"chat_session_id": "sessione-di-prova"})
    )
    respx.post(URL_INVIA).mock(return_value=httpx.Response(200, json=risposta or _corpo_onyx()))


# --- autenticazione e configurazione --------------------------------------------------------------------------


def test_senza_sessione_risponde_401(client_anonimo):
    """Senza cookie di sessione la chat non esiste: 401, e il database non viene nemmeno cercato.

    Il client è quello vero (nessun override): la dipendenza di sessione legge il cookie, non lo trova e risponde —
    il che è anche la prova che `/op/chat` è montata dietro la stessa guardia degli altri endpoint `/op/…`.
    """
    risposta = client_anonimo.post("/op/chat", json={"messaggio": MESSAGGIO})

    assert risposta.status_code == 401
    assert risposta.json() == {"detail": "sessione assente o scaduta"}


def test_token_mancante_risponde_503_con_messaggio_parlante(app_cliente, monkeypatch, tmp_path):
    """Senza `ONYX_CHAT_TOKEN` la chat dichiara di non essere configurata: 503, mai 500, e nessuna query.

    È il comportamento che l'operatore vede quando il PAT non è ancora stato messo: un messaggio in italiano che dice
    **cosa manca**. Il database non viene toccato — la configurazione si controlla prima dell'identità — e la spia lo
    prova: se il 503 arrivasse dopo la lettura dell'identità, il test lo vedrebbe in `query`.
    """
    monkeypatch.delenv("ONYX_CHAT_TOKEN", raising=False)
    monkeypatch.setattr("app.chat.PERCORSO_ENV", tmp_path / "env-inesistente")
    client, pool = app_cliente()

    risposta = _invia(client)

    assert risposta.status_code == 503
    assert risposta.json() == {"detail": DETAIL_CHAT_NON_CONFIGURATA}
    assert pool.query == [], "il token mancante si vede prima di qualunque query"


def test_casa_senza_identita_operatore_risponde_503(app_cliente):
    """Una Casa il cui unico indirizzo è `gestore.…` non ha un'identità di sportello: la chat lo dichiara.

    La scelta `email LIKE 'op.%'` è deliberata (l'operatore, non il gestore): qui il doppio restituisce `None`, che è
    esattamente ciò che la query fa per una Casa senza riga `op.…` attiva. La chat non inventa un'identità né ripiega
    sul gestore: risponde 503 con il motivo.
    """
    client, _ = app_cliente(pool=PoolSpia(identita=None))

    risposta = _invia(client)

    assert risposta.status_code == 503
    assert risposta.json() == {"detail": DETAIL_CASA_SENZA_IDENTITA}


def test_identita_cercata_e_quella_dell_operatore_della_casa_della_sessione(app_cliente):
    """L'identità viene da `identita_onyx`, è attiva, è quella **dell'operatore** e della Casa della sessione.

    Tre cose in un solo esito osservabile, perché sono la stessa decisione: la tabella letta, il filtro `op.%`
    (che esclude il gestore), e il `casa_id` preso dalla sessione (una Casa non parla a nome di un'altra).
    """
    client, pool = app_cliente(sessione=SessioneFinta(casa_id=CASA_SANBAO))

    with respx.mock:
        _mock_onyx()
        risposta = _invia(client)

    assert risposta.status_code == 200
    assert len(pool.query) == 1, f"una sola lettura: l'identità della Casa. Trovate: {pool.query}"
    sql, argomenti = pool.query[0]
    assert "trasi.identita_onyx" in sql
    assert "attiva" in sql
    assert "email LIKE 'op.%'" in sql, "deve essere l'operatore, non il gestore"
    assert argomenti == (CASA_SANBAO,), "la Casa è quella della sessione, non un valore del corpo"


def test_sessione_senza_casa_non_cerca_identita_e_risponde_503(app_cliente):
    """Una sessione senza Casa (es. ruolo `rete`) non ha un'identità di sportello: 503 senza interrogare il database."""
    client, pool = app_cliente(sessione=SessioneFinta(casa_id=None))

    risposta = _invia(client)

    assert risposta.status_code == 503
    assert risposta.json() == {"detail": DETAIL_CASA_SENZA_IDENTITA}
    assert pool.query == [], "senza Casa non c'è nulla da cercare"


# --- filtro anti-PII (V5) -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "messaggio",
    [
        pytest.param("Il signor Rossi mi ha dato l'email mario.rossi@example.it", id="email"),
        pytest.param("Richiamarlo al 333 123 4567 domani", id="telefono"),
        pytest.param("Il codice fiscale è RSSMRA80A01H501U", id="codice_fiscale"),
    ],
)
def test_dato_personale_nel_messaggio_risponde_422(app_cliente, messaggio):
    """Un dato personale nel messaggio non arriva al provider: 422 `dato_personale_sospetto`, prima di ogni query.

    Il test è il presidio che il messaggio — testo libero — non esca dallo shim verso Ollama Cloud: il rifiuto è
    prima della configurazione e prima dell'identità, quindi non dipende né dal PAT né dal database. Il corpo non
    compare nella risposta.
    """
    client, pool = app_cliente()

    risposta = _invia(client, messaggio)

    assert risposta.status_code == 422
    detail = risposta.json()["detail"]
    assert DETAIL_DATO_PERSONALE_SOSPETTO in detail
    assert "messaggio" in detail, "il campo sospetto è nominato, il valore no"
    assert "mario.rossi" not in detail and "333" not in detail and "RSSMRA" not in detail
    assert pool.query == [], "un dato personale si rifiuta prima di toccare il database"


# --- corpo della richiesta ------------------------------------------------------------------------------------


def test_chiave_extra_nel_corpo_risponde_422(app_cliente):
    """`extra="forbid"`: un `casa` nel corpo è un 422 — la Casa è quella della sessione, non una scelta del chiamante."""
    client, _ = app_cliente()

    risposta = _invia(client, casa="bozzano")

    assert risposta.status_code == 422
    assert risposta.json()["detail"].startswith("parametri non ammessi")


@pytest.mark.parametrize(
    "messaggio",
    [pytest.param("", id="vuoto"), pytest.param("a" * 2001, id="oltre_2000")],
)
def test_messaggio_fuori_dai_limiti_risponde_422(app_cliente, messaggio):
    """Il messaggio ha un minimo e un tetto dichiarati (1..2000): fuori da lì è 422, non una chiamata a Onyx."""
    client, _ = app_cliente()

    risposta = _invia(client, messaggio)

    assert risposta.status_code == 422
    assert risposta.json()["detail"].startswith("parametri non ammessi")


# --- risposta, fonte e guasti ----------------------------------------------------------------------------------


def test_risposta_riporta_il_testo_e_il_badge_della_fonte_kb(app_cliente):
    """200 `{risposta, fonte, riferimenti}` e la fonte è il badge KB composto dallo shim (V3, non dal modello).

    Il badge atteso è la stringa di `badge_kb` sui metadati del primo documento citato: la stessa forma che
    l'operatore legge in `cerca_luogo` e sul biglietto. Comporla qui — e non lasciarla al LLM — è ciò che rende la
    provenienza verificabile a colpo d'occhio.

    `riferimenti` è la novità di `T-SHIM-01`: il documento citato è un `trasi%3Aluogo%3A13` URL-encoded, e il test
    dell'estrazione sta in `test_conversazioni_op.py`. Qui si verifica solo che il campo ci sia nella risposta della
    via a un colpo solo, con l'id **decodificato**.
    """
    client, _ = app_cliente()

    with respx.mock:
        _mock_onyx(risposta=_corpo_onyx("Il CAF La Rosa è in via…", documents=[_documento_kb()]))
        risposta = _invia(client)

    assert risposta.status_code == 200
    assert risposta.json() == {
        "risposta": "Il CAF La Rosa è in via…",
        "fonte": "[KB · Rete-kb-3 · agg. 15/09/2026 · affidabilità 3]",
        "riferimenti": [{"tipo": "luogo", "id": 13, "nome": "CAF La Rosa"}],
    }


def test_documento_esterno_prende_il_badge_esterna(app_cliente):
    """Un documento di ricerca web è dichiarato `[Esterna · … · non verificata dalla rete]`, con l'ora della consultazione."""
    client, _ = app_cliente()

    with respx.mock:
        _mock_onyx(risposta=_corpo_onyx(documents=[_documento_esterno()]))
        risposta = _invia(client)

    assert risposta.status_code == 200
    assert re.fullmatch(
        r"\[Esterna · ANSA · consultata \d{2}:\d{2} · non verificata dalla rete\]", risposta.json()["fonte"]
    ), risposta.json()["fonte"]


def test_senza_documenti_citati_la_fonte_e_dichiarata_non_inventata(app_cliente):
    """Una risposta senza citazioni non resta senza etichetta: dice che nessuna fonte è stata citata (V3).

    È il caso più importante da non nascondere: un campo vuoto farebbe sembrare «senza fonte» un difetto di stampa,
    e una fonte inventata sarebbe peggio. Il testo della dichiarazione è quello del modulo.
    """
    client, _ = app_cliente()

    with respx.mock:
        _mock_onyx(risposta=_corpo_onyx(documents=[]))
        risposta = _invia(client)

    assert risposta.status_code == 200
    assert risposta.json()["fonte"] == FONTE_NON_DICHIARATA


def test_risposta_senza_testo_leggibile_risponde_503(app_cliente):
    """Onyx risponde 200 ma con `error_msg`: 503 «risposta non leggibile», non un 200 con `risposta` vuota.

    Il testo d'errore di Onyx **non** viene rimandato al chiamante né registrato (potrebbe portare dettagli del
    provider): al chiamante arriva la diagnosi dello shim, e il messaggio di Onyx resta fuori.
    """
    client, _ = app_cliente()

    with respx.mock:
        _mock_onyx(risposta=_corpo_onyx(answer="", error_msg="provider quota exceeded: sk-XXX"))
        risposta = _invia(client)

    assert risposta.status_code == 503
    assert risposta.json() == {"detail": DETAIL_RISPOSTA_NON_LEGGIBILE}
    assert "sk-XXX" not in risposta.text


def test_onyx_non_raggiungibile_risponde_503_dichiarato(app_cliente):
    """Onyx giù non è un 500 dello shim: 503 con il guasto dichiarato (§9.1, mai eccezione al chiamante)."""
    client, _ = app_cliente()

    with respx.mock:
        respx.post(URL_CREA).mock(side_effect=httpx.ConnectError("Onyx spento"))
        risposta = _invia(client)

    assert risposta.status_code == 503
    assert risposta.json() == {"detail": DETAIL_CHAT_NON_DISPONIBILE}


def test_onyx_piu_lento_del_budget_dichiarato_risponde_503(app_cliente, monkeypatch):
    """Il budget `ONYX_CHAT_TIMEOUT_S` è **dichiarato**: allo scadere si risponde 503, non si aspetta il chiamante.

    Un LLM risponde in decine di secondi, quindi il budget della chat è dedicato (60 s di default) e diverso dai 3 s
    di `SHIM_TIMEOUT_S`. Il test lo abbassa a 1 s e fa rispondere Onyx dopo: la prova non è «arriva un timeout», è che
    il tempo dichiarato **vince** sulla lentezza della risposta — l'`asyncio.wait_for` che copre l'intera coppia di
    chiamate, non solo una fase di `httpx`.
    """
    monkeypatch.setenv("ONYX_CHAT_TIMEOUT_S", "1")
    client, _ = app_cliente()

    async def lento(_: httpx.Request) -> httpx.Response:
        import asyncio

        await asyncio.sleep(5)
        return httpx.Response(200, json=_corpo_onyx())

    with respx.mock:
        respx.post(URL_CREA).mock(side_effect=lento)
        risposta = _invia(client)

    assert risposta.status_code == 503
    assert risposta.json() == {"detail": DETAIL_CHAT_NON_DISPONIBILE}


# --- contratto e log (V5/§12) ----------------------------------------------------------------------------------


def test_chat_e_montata_sotto_op_e_fuori_dal_contratto_con_onyx(app_cliente):
    """`/op/chat` risponde all'indirizzo che la UI chiama, e **non** compare nello schema OpenAPI.

    Le due cose insieme non sono una coincidenza da verificare: il documento che FastAPI genera è il contratto
    congelato con Onyx (gate V-09, nove `operationId` per uguaglianza), e un endpoint del browser dentro quel
    documento lo romperebbe. `include_in_schema=False` toglie dal documento, non dal routing.
    """
    client, _ = app_cliente()

    with respx.mock:
        _mock_onyx()
        risposta = _invia(client)

    from app.main import app as applicazione

    percorsi = applicazione.openapi()["paths"]
    assert risposta.status_code == 200, "il percorso /op/chat deve esistere e rispondere"
    assert "/op/chat" not in percorsi, "gli endpoint del browser non appartengono al contratto con Onyx"


def test_log_non_contiene_messaggio_ne_token_ne_email(app_cliente, caplog):
    """Il log porta `operationId` e stato, mai il messaggio, il PAT o l'email dell'identità (V5/§12).

    È la stessa invariante che `main.py` difende scegliendo l'`operationId` al posto dell'URL: qui il rischio in più è
    il **token**, che viaggia in un header verso Onyx e non deve finire in una riga di log dello sportello.
    """
    client, _ = app_cliente()
    segreto = "Il signor Bianchi ha lasciato la tessera in portineria"

    registratore = logging.getLogger("trasi.shim")
    registratore.addHandler(caplog.handler)
    livello = registratore.level
    registratore.setLevel(logging.INFO)
    try:
        with caplog.at_level(logging.INFO, logger="trasi.shim"):
            with respx.mock:
                _mock_onyx()
                risposta = _invia(client, segreto)
    finally:
        registratore.setLevel(livello)
        registratore.removeHandler(caplog.handler)

    testo = "\n".join(voce.getMessage() for voce in caplog.records)

    assert risposta.status_code == 200
    assert "op_chat" in testo, "il log deve nominare l'operationId"
    assert segreto not in testo, "il messaggio dell'operatore non entra nel log"
    assert TOKEN_DI_PROVA not in testo, "il PAT non entra nel log"
    assert EMAIL_OPERATORE not in testo, "l'email dell'identità non entra nel log"
    assert BASE_ONYX not in testo, "l'URL di Onyx non entra nel log"
