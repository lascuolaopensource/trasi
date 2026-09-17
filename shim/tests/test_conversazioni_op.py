"""Conversazioni della Home: multi-turno reale, storico per Casa, riferimenti (T-SHIM-01/02/03).

Tre cose si provano qui, e sono tre decisioni diverse:

**Il multi-turno.** Il difetto che questo modulo corregge è che ogni messaggio apriva una `chat_session` nuova e
mandava `parent_message_id: -1`: due domande di fila erano due conversazioni scollegate. La prova non è «il codice
passa un padre», è che il **corpo della seconda richiesta** porti il `message_id` della prima risposta e che Onyx
riceva **una sola** `create-chat-session`. Onyx è mockato con `respx`, quindi si legge esattamente cosa gli è stato
mandato — che è l'unica cosa che questo modulo decide.

**La visibilità.** `404` per una conversazione di un'altra Casa, con lo **stesso** dettaglio di «non esiste»: il
doppio della sessione restituisce `None` per la riga, che è ciò che la RLS fa per davvero (la policy `conv_sel_casa`
non lascia vedere la riga). Un `403` con un dettaglio diverso direbbe a chi prova che la conversazione esiste.

**Il filtro anti-PII prima della scrittura.** Un `422` non deve lasciare niente in `turno`: il doppio registra le
query, quindi si verifica che l'`INSERT` non sia stato nemmeno tentato. È il presidio di V5 applicato alla chat, e
vale la pena provarlo **qui** e non solo su `op_chat`, perché questo è il percorso che scrive il testo su disco.

Il database non serve: la sessione è un doppio che risponde con le righe preparate dal test e registra le query.
Onyx è mockato. La configurazione si prepara con `monkeypatch` e `PERCORSO_ENV` punta a un file inesistente, così
`deployment/.env` non diventa una seconda fonte di verità.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

import ambiente

BASE_ONYX = "http://onyx-di-prova:8080"
TOKEN_DI_PROVA = "onyx_pat_di_prova_non_reale"
URL_CREA = f"{BASE_ONYX}/chat/create-chat-session"
URL_INVIA = f"{BASE_ONYX}/chat/send-chat-message"

DETAIL_CONVERSAZIONE_NON_TROVATA = "conversazione non trovata"
DETAIL_DATO_PERSONALE_SOSPETTO = "dato_personale_sospetto"
DETAIL_CHAT_NON_CONFIGURATA = "chat non configurata: manca il token Onyx (ONYX_CHAT_TOKEN)"
DETAIL_CHAT_NON_DISPONIBILE = "chat non disponibile: Onyx non ha risposto entro il tempo dichiarato"

CASA_SANBAO = 5
EMAIL_OPERATORE = "op.san-bao@trasi.local"
FUSO = ZoneInfo("Europe/Rome")
MESSAGGIO = "Dove si fa l'ISEE vicino a La Rosa?"


# --- doppi: pool, connessione, sessione ------------------------------------------------------------------------


class PoolSpia:
    """Il pool: restituisce l'identità di sportello della Casa, come fa la query vera."""

    def __init__(self, identita: str | None = EMAIL_OPERATORE) -> None:
        self.identita = identita
        self.query: list[tuple[str, tuple[Any, ...]]] = []

    def acquire(self) -> "Acquisizione":
        return Acquisizione(self)


class Acquisizione:
    def __init__(self, pool: PoolSpia) -> None:
        self.pool = pool

    async def __aenter__(self) -> "ConnessioneSpia":
        return ConnessioneSpia(self.pool)

    async def __aexit__(self, *_: Any) -> bool:
        return False


class ConnessioneSpia:
    def __init__(self, pool: PoolSpia) -> None:
        self.pool = pool

    async def fetchval(self, sql: str, *args: Any) -> Any:
        self.pool.query.append((sql, args))
        return self.pool.identita


class SessioneFinta:
    """La sessione della Casa: risponde con le righe preparate e **registra** le query eseguite.

    `fetchrow` distingue le due letture che il router fa (`conversazione` e `turno`), perché sono due domande
    diverse e un doppio che rispondesse sempre la stessa riga non proverebbe né l'una né l'altra. Le righe di
    `fetch` sono quelle della conversazione passata dal test (dettaglio o elenco, secondo la colonna presente).
    """

    def __init__(
        self,
        *,
        conversazione: dict[str, Any] | None = None,
        ultimo_turno: dict[str, Any] | None = None,
        righe: list[dict[str, Any]] | None = None,
    ) -> None:
        self.conversazione = conversazione
        self.ultimo_turno = ultimo_turno
        self.righe = righe if righe is not None else []
        self.ruolo = "casa_sanbao"
        self.casa_slug = "san-bao"
        self.casa_id = CASA_SANBAO
        self.email = ""
        self.query: list[tuple[str, tuple[Any, ...]]] = []
        self.scritture: list[tuple[str, tuple[Any, ...]]] = []
        self._id_turno = 1000

    async def fetch(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        self.query.append((sql, args))
        return self.righe

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        self.query.append((sql, args))
        normalizzato = " ".join(sql.split())
        if normalizzato.startswith("INSERT INTO trasi.turno"):
            self.scritture.append((normalizzato, args))
            self._id_turno += 1
            return {"id": self._id_turno, "ts": datetime(2026, 9, 17, 11, 42, tzinfo=FUSO)}
        if normalizzato.startswith("INSERT INTO trasi.conversazione"):
            self.scritture.append((normalizzato, args))
            return {"id": 42, "creato_ts": datetime(2026, 9, 17, 11, 42, tzinfo=FUSO)}
        if "FROM trasi.turno" in normalizzato:
            return self.ultimo_turno
        return self.conversazione

    async def fetchval(self, sql: str, *args: Any) -> Any:
        self.query.append((sql, args))
        return None

    async def execute(self, sql: str, *args: Any) -> str:
        self.query.append((sql, args))
        return "OK"

    def turni_scritti(self) -> list[dict[str, Any]]:
        """I turni come sono stati passati al database: `ruolo`, `testo`, `fonte`, `riferimenti`, `onyx_message_id`."""
        return [
            {
                "ruolo": argomenti[1],
                "testo": argomenti[2],
                "fonte": argomenti[3],
                "riferimenti": argomenti[4],
                "onyx_message_id": argomenti[5],
            }
            for sql, argomenti in self.scritture
            if sql.startswith("INSERT INTO trasi.turno")
        ]

    @property
    def ultimo_id_turno(self) -> int:
        """L'id del **ultimo** turno scritto, cioè quello dell'assistente: è l'id che l'endpoint restituisce."""
        return self._id_turno


@pytest.fixture
def app_cliente(monkeypatch, tmp_path):
    """`TestClient` sull'app reale: sessione e pool sostituiti, token e base URL di Onyx dall'ambiente di prova."""
    monkeypatch.setattr("app.chat.PERCORSO_ENV", tmp_path / "env-inesistente")
    monkeypatch.setenv("ONYX_CHAT_TOKEN", TOKEN_DI_PROVA)
    monkeypatch.setenv("ONYX_CHAT_API_URL", BASE_ONYX)
    monkeypatch.delenv("ONYX_CHAT_TIMEOUT_S", raising=False)
    monkeypatch.delenv("ONYX_PERSONA_ID", raising=False)
    ambiente.configura_ambiente()

    from fastapi.testclient import TestClient

    from app import auth
    from app import chat as modulo_chat
    from app import conversazioni_op, main as modulo_main

    def costruisci(sessione: SessioneFinta | None = None, pool: PoolSpia | None = None):
        sessione = sessione or SessioneFinta(
            conversazione={
                "id": 42,
                "titolo": "Dove si fa l'ISEE vicino a La Rosa?",
                "onyx_session_id": "sessione-onyx-della-conversazione",
                "creato_ts": datetime(2026, 9, 17, 11, 42, tzinfo=FUSO),
                "ultimo_ts": datetime(2026, 9, 17, 11, 42, tzinfo=FUSO),
            }
        )
        pool = pool or PoolSpia()
        monkeypatch.setattr(modulo_chat, "_pool_corrente", lambda: pool)
        applicazione = modulo_main.crea_app()
        applicazione.dependency_overrides[auth.sessione_corrente] = lambda: sessione
        return TestClient(applicazione, raise_server_exceptions=False), sessione, pool

    return costruisci


def _corpo_onyx(
    answer: str = "Il CAF La Rosa, in via provinciale per La Rosa.",
    *,
    documents: list[dict[str, Any]] | None = None,
    message_id: int = 731,
) -> dict[str, Any]:
    """La risposta di `/chat/send-chat-message` nella forma reale (ispezionata su Onyx v4.7.2)."""
    return {
        "answer": answer,
        "answer_citationless": answer,
        "tool_calls": [],
        "top_documents": documents or [],
        "citation_info": [],
        "message_id": message_id,
        "chat_session_id": "sessione-onyx-della-conversazione",
        "incognito": False,
        "error_msg": None,
    }


def _documento(document_id: str, nome: str = "CAF ACLI La Rosa", **extra: Any) -> dict[str, Any]:
    """Un documento citato, nella forma reale: `document_id` **URL-encoded**, metadati dell'export."""
    corpo = {
        "document_id": document_id,
        "semantic_identifier": nome,
        "is_internet": False,
        "metadata": {"fonte": "Rete-kb-3", "data_aggiornamento": "2026-09-15", "affidabilita": "3"},
    }
    corpo.update(extra)
    return corpo


def _messaggio(client, conversazione_id: int = 42, messaggio: str = MESSAGGIO, **extra: Any):
    return client.post(f"/op/conversazioni/{conversazione_id}/messaggi", json={"messaggio": messaggio, **extra})


# --- autenticazione e configurazione ---------------------------------------------------------------------------


def test_senza_sessione_risponde_401(client_anonimo):
    """Senza cookie il router risponde 401: è la stessa guardia degli altri endpoint `/op/…`."""
    for richiesta in (
        client_anonimo.post("/op/conversazioni", json={}),
        client_anonimo.post("/op/conversazioni/1/messaggi", json={"messaggio": MESSAGGIO}),
        client_anonimo.get("/op/conversazioni"),
        client_anonimo.get("/op/conversazioni/1"),
    ):
        assert richiesta.status_code == 401
        assert richiesta.json() == {"detail": "sessione assente o scaduta"}


def test_token_mancante_risponde_503_senza_toccare_onyx(app_cliente, monkeypatch, tmp_path):
    """Senza `ONYX_CHAT_TOKEN` la creazione dichiara la configurazione mancante e **non** chiama Onyx.

    Il token si controlla prima della rete: una chiamata che non potrebbe riuscire non si fa. Il `503` è dichiarato,
    mai un `500`.
    """
    monkeypatch.delenv("ONYX_CHAT_TOKEN", raising=False)
    monkeypatch.setattr("app.chat.PERCORSO_ENV", tmp_path / "env-inesistente")
    client, _, _ = app_cliente()

    with respx.mock(assert_all_called=False):
        rotta = respx.post(URL_CREA).mock(return_value=httpx.Response(500))
        risposta = client.post("/op/conversazioni", json={})

    assert risposta.status_code == 503
    assert risposta.json() == {"detail": DETAIL_CHAT_NON_CONFIGURATA}
    assert not rotta.called, "Onyx non si chiama senza token"


def test_casa_senza_identita_operatore_risponde_503(app_cliente):
    """Una Casa senza riga `op.…` attiva non ha un'identità di sportello: `503` con il motivo, non un'identità inventata."""
    client, _, _ = app_cliente(pool=PoolSpia(identita=None))

    risposta = client.post("/op/conversazioni", json={})

    assert risposta.status_code == 503
    assert "nessuna identità Onyx attiva" in risposta.json()["detail"]


# --- creazione: una sola sessione Onyx, legata alla conversazione -----------------------------------------------


def test_creazione_lega_la_sessione_onyx_alla_conversazione(app_cliente):
    """`POST /op/conversazioni` apre **una** sessione Onyx e la scrive nella riga, in un solo `INSERT`.

    Legare la sessione alla **nascita** e non al primo messaggio è ciò che rende il multi-turno possibile: sui ruoli
    Casa non c'è `UPDATE` su `conversazione`, quindi un `onyx_session_id` scritto dopo non sarebbe scrivibile. Il
    test lo verifica sul dato davvero passato all'`INSERT`.
    """
    client, sessione, _ = app_cliente()

    with respx.mock(assert_all_called=True) as mock:
        mock.post(URL_CREA).mock(return_value=httpx.Response(200, json={"chat_session_id": "sessione-onyx-nuova"}))
        risposta = client.post("/op/conversazioni", json={})

    assert risposta.status_code == 201
    assert risposta.json() == {"conversazione_id": 42, "creato_ts": "2026-09-17T11:42:00+02:00"}
    scritture = [s for s, _ in sessione.scritture if s.startswith("INSERT INTO trasi.conversazione")]
    assert len(scritture) == 1, "una sola riga di conversazione"
    _, argomenti = sessione.scritture[-1]
    assert argomenti == ("sessione-onyx-nuova",), "l'id della sessione Onyx è legato alla conversazione"
    assert "trasi.casa_corrente()" in scritture[0], "la Casa viene dall'identità, mai dal corpo"


def test_creazione_con_chiave_extra_nel_corpo_risponde_422(app_cliente):
    """`extra="forbid"`: un `casa_id` nel corpo è un `422` — la Casa è quella della sessione, non una scelta."""
    client, _, _ = app_cliente()

    risposta = client.post("/op/conversazioni", json={"casa_id": 8})

    assert risposta.status_code == 422
    assert risposta.json()["detail"].startswith("parametri non ammessi")


def test_creazione_con_onyx_giu_non_crea_la_conversazione(app_cliente):
    """Se la sessione Onyx non si apre si risponde `503` e **nessuna** conversazione viene scritta.

    Una conversazione senza la sua sessione sarebbe uno storico di domande senza contesto: il difetto che questo
    modulo corregge, reintrodotto per un'altra via.
    """
    client, sessione, _ = app_cliente()

    with respx.mock:
        respx.post(URL_CREA).mock(side_effect=httpx.ConnectError("Onyx spento"))
        risposta = client.post("/op/conversazioni", json={})

    assert risposta.status_code == 503
    assert risposta.json() == {"detail": DETAIL_CHAT_NON_DISPONIBILE}
    assert sessione.scritture == [], "niente conversazione se la sessione Onyx non esiste"


# --- multi-turno: la sessione è riusata e il padre è il turno precedente ----------------------------------------


def test_primo_turno_non_crea_una_seconda_sessione_e_manda_meno_uno(app_cliente):
    """Il primo turno riusa la sessione della conversazione e manda `parent_message_id: -1`.

    Due cose in una: **una sola** `create-chat-session` per conversazione (non una per messaggio — il difetto
    corretto) e nessun padre, che è la verità del primo turno.
    """
    client, _, _ = app_cliente()

    with respx.mock(assert_all_called=False) as mock:
        creazione = mock.post(URL_CREA).mock(return_value=httpx.Response(500))
        invio = mock.post(URL_INVIA).mock(return_value=httpx.Response(200, json=_corpo_onyx()))
        risposta = _messaggio(client)

    assert risposta.status_code == 200
    assert not creazione.called, "la conversazione ha già la sua sessione: non se ne apre un'altra"
    corpo = json.loads(invio.calls[0].request.content)
    assert corpo["chat_session_id"] == "sessione-onyx-della-conversazione"
    assert corpo["parent_message_id"] == -1, "il primo turno non ha un padre"
    assert corpo["stream"] is False


def test_secondo_turno_usa_il_message_id_della_risposta_precedente(app_cliente):
    """Il secondo turno manda il `message_id` del turno dell'assistente precedente: è il contesto.

    È il difetto centrale di questa fetta. Si legge il corpo **realmente inviato** a Onyx: `parent_message_id` è il
    `onyx_message_id` salvato dal turno precedente (`729`), non `-1`, e la sessione è la stessa.
    """
    sessione = SessioneFinta(
        conversazione={
            "id": 42,
            "titolo": "Prima domanda",
            "onyx_session_id": "sessione-onyx-della-conversazione",
            "creato_ts": datetime(2026, 9, 17, 11, 42, tzinfo=FUSO),
            "ultimo_ts": datetime(2026, 9, 17, 11, 42, tzinfo=FUSO),
        },
        ultimo_turno={"onyx_message_id": 729},
    )
    client, _, _ = app_cliente(sessione=sessione)

    with respx.mock(assert_all_called=False) as mock:
        creazione = mock.post(URL_CREA).mock(return_value=httpx.Response(500))
        invio = mock.post(URL_INVIA).mock(return_value=httpx.Response(200, json=_corpo_onyx(message_id=731)))
        risposta = _messaggio(client, messaggio="E il CAF CISL Perrino?")

    assert risposta.status_code == 200
    assert not creazione.called
    corpo = json.loads(invio.calls[0].request.content)
    assert corpo["parent_message_id"] == 729, "il padre è l'onyx_message_id del turno precedente"
    assert corpo["message"] == "E il CAF CISL Perrino?"
    assert risposta.json()["onyx_message_id"] == 731, "il nuovo id è quello che il turno dopo userà come padre"


def test_i_due_turni_sono_scritti_e_il_secondo_porta_il_padre_del_primo(app_cliente):
    """Una domanda scrive **due** turni — operatore e assistente — e il turno dell'assistente porta l'id di Onyx.

    Il turno dell'operatore non ha `onyx_message_id` (non è un messaggio di Onyx) e non ha `fonte`: è ciò che
    rende il dialogo ricostruibile al ricaricamento della pagina.
    """
    client, sessione, _ = app_cliente()

    with respx.mock:
        respx.post(URL_INVIA).mock(return_value=httpx.Response(200, json=_corpo_onyx(message_id=731)))
        risposta = _messaggio(client)

    assert risposta.status_code == 200
    turni = sessione.turni_scritti()
    assert [t["ruolo"] for t in turni] == ["operatore", "assistente"]
    assert turni[0]["testo"] == MESSAGGIO
    assert turni[0]["onyx_message_id"] is None
    assert turni[1]["onyx_message_id"] == 731
    # `turno_id` è l'id del turno **dell'assistente** (il secondo `INSERT`): è quello che la UI usa per collegare
    # le azioni sulla risposta, e le azioni stanno sulla risposta, non sulla domanda.
    assert risposta.json()["turno_id"] == sessione.ultimo_id_turno


# --- riferimenti (T-SHIM-01) ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "document_id, tipo, id_atteso",
    [
        pytest.param("trasi%3Aluogo%3A21", "luogo", 21, id="luogo"),
        pytest.param("trasi%3Acasa_quartiere%3A8", "casa", 8, id="casa_quartiere_forma_della_vista"),
        pytest.param("trasi%3Acasa%3A8", "casa", 8, id="casa_forma_del_piano"),
        pytest.param("trasi%3Aevento%3A470", "evento", 470, id="evento"),
    ],
)
def test_riferimenti_dai_document_id_url_encoded(app_cliente, document_id, tipo, id_atteso):
    """`trasi%3Aluogo%3A21` → `{tipo: luogo, id: 21, nome: …}`: si **decodifica**, non si indovina.

    Il prefisso non si trova nella forma grezza (`trasi%3Aluogo%3A21` non inizia per `trasi:luogo:`), ed è la
    trappola documentata in `README.md` §7.2: cercarlo prima di decodificare non troverebbe **mai** nulla.
    """
    client, _, _ = app_cliente()

    with respx.mock:
        respx.post(URL_INVIA).mock(
            return_value=httpx.Response(200, json=_corpo_onyx(documents=[_documento(document_id)]))
        )
        risposta = _messaggio(client)

    assert risposta.status_code == 200
    assert risposta.json()["riferimenti"] == [{"tipo": tipo, "id": id_atteso, "nome": "CAF ACLI La Rosa"}]


def test_documenti_fuori_dalla_kb_sono_ignorati_in_silenzio(app_cliente):
    """Un documento che non è un'entità di Trasi non produce un riferimento, e non fa fallire la risposta.

    Onyx cita anche fonti esterne (verificato dal vivo: `MEDIAWIKI_…` e un URL): un errore su quelle spegnerebbe la
    risposta per un documento che non ci riguarda. La lista resta quella dei soli riferimenti risolvibili.
    """
    client, _, _ = app_cliente()

    documenti = [
        _documento("MEDIAWIKI_2098867_https://it.wikipedia.org/wiki/CAF"),
        _documento("trasi%3Aluogo%3A21"),
        _documento("https://www.inps.it/prestazioni"),
        _documento("trasi%3Aluogo%3Anon_un_numero"),
    ]

    with respx.mock:
        respx.post(URL_INVIA).mock(return_value=httpx.Response(200, json=_corpo_onyx(documents=documenti)))
        risposta = _messaggio(client)

    assert risposta.status_code == 200
    assert risposta.json()["riferimenti"] == [{"tipo": "luogo", "id": 21, "nome": "CAF ACLI La Rosa"}]


def test_lo_stesso_luogo_citato_due_volte_produce_un_riferimento_solo(app_cliente):
    """Due chunk dello stesso documento sono **un** riferimento: mostrarne due non aggiunge nulla.

    Onyx restituisce un documento per chunk, quindi lo stesso luogo compare più volte quando la risposta è lunga.
    """
    client, _, _ = app_cliente()

    with respx.mock:
        respx.post(URL_INVIA).mock(
            return_value=httpx.Response(
                200,
                json=_corpo_onyx(
                    documents=[
                        _documento("trasi%3Aluogo%3A21"),
                        _documento("trasi%3Aluogo%3A21"),
                        _documento("trasi%3Aluogo%3A22", nome="CAF CISL Perrino"),
                    ]
                ),
            )
        )
        risposta = _messaggio(client)

    assert [r["id"] for r in risposta.json()["riferimenti"]] == [21, 22]


def test_senza_documenti_citati_i_riferimenti_sono_una_lista_vuota(app_cliente):
    """Nessun documento → `riferimenti: []` e `fonte: null` (l'astensione non ha etichetta).

    `[]` e non `None`: chi legge non deve distinguere «assente» da «nessuno». E `fonte` è `null` perché l'astensione
    — «Non trovo informazioni su questo nella memoria della rete.» — è un'informazione **senza** provenienza, e la
    UI non deve disegnare un'etichetta che non esiste.
    """
    client, sessione, _ = app_cliente()

    with respx.mock:
        respx.post(URL_INVIA).mock(
            return_value=httpx.Response(
                200,
                json=_corpo_onyx("Non trovo informazioni su questo nella memoria della rete.", documents=[]),
            )
        )
        risposta = _messaggio(client)

    assert risposta.status_code == 200
    assert risposta.json()["riferimenti"] == []
    assert risposta.json()["fonte"] is None
    assert sessione.turni_scritti()[1]["fonte"] is None, "il turno salvato non porta un'etichetta inventata"


def test_la_fonte_e_il_badge_dello_shim_verbatim_nel_turno(app_cliente):
    """Il turno salvato porta la **stessa** stringa che lo shim ha composto: verbatim, mai riformattata.

    È ciò che rende la provenienza verificabile anche dopo un ricaricamento della pagina: leggendo il turno dal
    database, l'etichetta è identica a quella che l'operatore ha visto dal vivo.
    """
    client, sessione, _ = app_cliente()

    with respx.mock:
        respx.post(URL_INVIA).mock(
            return_value=httpx.Response(200, json=_corpo_onyx(documents=[_documento("trasi%3Aluogo%3A21")]))
        )
        risposta = _messaggio(client)

    badge = risposta.json()["fonte"]
    assert badge == "[KB · Rete-kb-3 · agg. 15/09/2026 · affidabilità 3]"
    assert sessione.turni_scritti()[1]["fonte"] == badge


# --- PII (V5): prima di Onyx e prima di qualunque scrittura -----------------------------------------------------


@pytest.mark.parametrize(
    "messaggio",
    [
        pytest.param("Il signor Rossi mi ha dato l'email mario.rossi@example.it", id="email"),
        pytest.param("Richiamarlo al 333 123 4567 domani", id="telefono"),
        pytest.param("Il codice fiscale è RSSMRA80A01H501U", id="codice_fiscale"),
    ],
)
def test_dato_personale_non_arriva_a_onyx_e_non_scrive_niente(app_cliente, messaggio):
    """Un dato personale è `422` **prima** di Onyx e non lascia nessun turno: V5 vale anche sul percorso che scrive.

    Tre esiti osservabili in una prova sola, perché sono la stessa decisione: nessuna chiamata a Onyx (il testo non
    esce dallo shim), nessun `INSERT` in `turno` (il testo rifiutato non entra nello storico) e il valore non
    compare nel messaggio d'errore.
    """
    client, sessione, _ = app_cliente()

    with respx.mock(assert_all_called=False) as mock:
        invio = mock.post(URL_INVIA).mock(return_value=httpx.Response(500))
        risposta = _messaggio(client, messaggio=messaggio)

    assert risposta.status_code == 422
    detail = risposta.json()["detail"]
    assert DETAIL_DATO_PERSONALE_SOSPETTO in detail
    assert "messaggio" in detail, "il campo sospetto è nominato, il valore no"
    assert "mario.rossi" not in detail and "333" not in detail and "RSSMRA" not in detail
    assert not invio.called, "il testo non arriva al provider"
    assert sessione.scritture == [], "un testo rifiutato non entra nello storico"


# --- visibilità: 404, mai 403 -----------------------------------------------------------------------------------


def test_conversazione_di_un_altra_casa_risponde_404(app_cliente):
    """Una conversazione che la Casa non può vedere è `404` con il dettaglio di «non esiste».

    Il doppio restituisce `None` per la riga, che è esattamente ciò che fa la RLS: la policy `conv_sel_casa` non
    lascia passare la riga, quindi la query non trova nulla. Il `403` è vietato perché un dettaglio diverso direbbe
    a chi prova che la conversazione **esiste** e appartiene a un altro.
    """
    client, sessione, _ = app_cliente(sessione=SessioneFinta(conversazione=None))

    with respx.mock(assert_all_called=False) as mock:
        invio = mock.post(URL_INVIA).mock(return_value=httpx.Response(500))
        risposta = _messaggio(client, conversazione_id=999)

    assert risposta.status_code == 404
    assert risposta.json() == {"detail": DETAIL_CONVERSAZIONE_NON_TROVATA}
    assert not invio.called, "una conversazione non visibile non deve far partire una chiamata a Onyx"
    assert sessione.scritture == []


def test_dettaglio_di_un_altra_casa_risponde_404_con_lo_stesso_dettaglio(app_cliente):
    """`GET /op/conversazioni/{id}` di un'altra Casa: lo **stesso** dettaglio della conversazione inesistente."""
    client, _, _ = app_cliente(sessione=SessioneFinta(conversazione=None))

    risposta = client.get("/op/conversazioni/999")

    assert risposta.status_code == 404
    assert risposta.json() == {"detail": DETAIL_CONVERSAZIONE_NON_TROVATA}


def test_il_dettaglio_non_filtra_per_casa_nella_query(app_cliente):
    """La visibilità la decide la RLS, non un `WHERE casa_id` scritto qui: una seconda copia della regola divergerebbe.

    Il test legge il SQL davvero eseguito: se un giorno qualcuno aggiungesse un filtro qui, la policy resterebbe
    l'autorità ma esisterebbero due verità — ed è il difetto che il progetto evita in ogni tabella.
    """
    client, sessione, _ = app_cliente(
        sessione=SessioneFinta(
            conversazione={
                "id": 42,
                "titolo": "Titolo",
                "onyx_session_id": "s",
                "creato_ts": datetime(2026, 9, 17, 11, 42, tzinfo=FUSO),
                "ultimo_ts": datetime(2026, 9, 17, 11, 42, tzinfo=FUSO),
            },
            righe=[],
        )
    )

    risposta = client.get("/op/conversazioni/42")

    assert risposta.status_code == 200
    letture = [s for s, _ in sessione.query if "FROM trasi.conversazione" in " ".join(s.split())]
    assert letture, "la conversazione si legge"
    assert all("casa_id" not in s for s in letture), "il filtro per Casa è della RLS"


# --- elenco e dettaglio -----------------------------------------------------------------------------------------


def test_elenco_riporta_titolo_conteggio_e_istanti_nel_fuso_della_rete(app_cliente):
    """`GET /op/conversazioni` → titolo, primo e ultimo istante, numero di turni; dalla più recente.

    Gli istanti arrivano **nel fuso della rete** (`+02:00`), non in UTC come li dà la sessione del database: l'ora di
    un turno e l'ora dentro un badge di provenienza devono essere lo stesso orologio, o la stessa riga di UI
    mostrerebbe due ore diverse. Il valore è quello reale dell'istante, non una stringa riformattata.
    """
    righe = [
        {
            "id": 42,
            "titolo": "Dove si fa l'ISEE vicino a La Rosa?",
            "creato_ts": datetime(2026, 9, 17, 11, 42, tzinfo=FUSO),
            "ultimo_ts": datetime(2026, 9, 17, 12, 5, tzinfo=FUSO),
            "turni": 4,
        },
        {
            "id": 41,
            "titolo": "Bar aperti adesso a Bozzano?",
            "creato_ts": datetime(2026, 9, 16, 9, 0, tzinfo=FUSO),
            "ultimo_ts": datetime(2026, 9, 16, 9, 0, tzinfo=FUSO),
            "turni": 2,
        },
    ]
    client, _, _ = app_cliente(sessione=SessioneFinta(righe=righe))

    risposta = client.get("/op/conversazioni?limite=10")

    assert risposta.status_code == 200
    assert risposta.json()["conversazioni"] == [
        {
            "id": 42,
            "titolo": "Dove si fa l'ISEE vicino a La Rosa?",
            "primo_ts": "2026-09-17T11:42:00+02:00",
            "ultimo_ts": "2026-09-17T12:05:00+02:00",
            "turni": 4,
        },
        {
            "id": 41,
            "titolo": "Bar aperti adesso a Bozzano?",
            "primo_ts": "2026-09-16T09:00:00+02:00",
            "ultimo_ts": "2026-09-16T09:00:00+02:00",
            "turni": 2,
        },
    ]


def test_elenco_esclude_le_conversazioni_senza_risposta_e_conta_tutti_i_turni(app_cliente):
    """Lo storico mostra solo le conversazioni **avvenute**, e `turni` conta domande e risposte.

    Due cose che si sbagliano insieme: il filtro è «esiste una risposta dell'assistente» (§4.1.3, punto c: una
    conversazione «esiste» solo se ha almeno una risposta, altrimenti lo storico è una lista di tentativi falliti),
    mentre `turni` conta **tutti** i turni — due domande con due risposte fanno `4`. Con un solo `JOIN` filtrato le
    due condizioni collasserebbero e il conteggio mostrerebbe la metà.
    """
    righe = [{"id": 42, "titolo": "T", "creato_ts": None, "ultimo_ts": None, "turni": 4}]
    client, sessione, _ = app_cliente(sessione=SessioneFinta(righe=righe))

    risposta = client.get("/op/conversazioni")

    assert risposta.status_code == 200
    assert risposta.json()["conversazioni"][0]["turni"] == 4
    sql = " ".join(sessione.query[0][0].split())
    assert "EXISTS" in sql and "r.ruolo = $2" in sql, "il filtro è «esiste una risposta», dichiarato"
    assert sql.count("trasi.turno") == 2, "il conteggio è una sotto-query: conta tutti i turni, non solo le risposte"


@pytest.mark.parametrize(
    "limite", [pytest.param(0, id="zero"), pytest.param(201, id="oltre_il_tetto")],
)
def test_limite_fuori_dai_valori_ammessi_risponde_422(app_cliente, limite):
    """Il tetto di pagina è dichiarato (1-200): fuori da lì è `422`, non una query più grande del previsto."""
    client, _, _ = app_cliente()

    risposta = client.get(f"/op/conversazioni?limite={limite}")

    assert risposta.status_code == 422
    assert risposta.json()["detail"].startswith("parametri non ammessi")


def test_dettaglio_riporta_i_turni_in_ordine_con_fonte_e_riferimenti(app_cliente):
    """I turni tornano in ordine, con `fonte` sul turno dell'assistente e `None` su quello dell'operatore.

    È ciò che la Home disegna quando si ricarica `?c=<id>`: turno OPERATORE senza etichetta, turno ASSISTENTE con
    l'etichetta di provenienza verbatim su riga propria.
    """
    righe = [
        {
            "id": 1,
            "ruolo": "operatore",
            "testo": MESSAGGIO,
            "fonte": None,
            "riferimenti": None,
            "ts": datetime(2026, 9, 17, 11, 42, tzinfo=FUSO),
        },
        {
            "id": 2,
            "ruolo": "assistente",
            "testo": "Il CAF La Rosa, in via provinciale per La Rosa.",
            "fonte": "[KB · ACLI — patronato · agg. 17/09/2026 · affidabilità 1]",
            "riferimenti": [{"tipo": "luogo", "id": 21, "nome": "CAF ACLI La Rosa"}],
            "ts": datetime(2026, 9, 17, 11, 43, tzinfo=FUSO),
        },
    ]
    sessione = SessioneFinta(
        conversazione={
            "id": 42,
            "titolo": "Dove si fa l'ISEE vicino a La Rosa?",
            "onyx_session_id": "s",
            "creato_ts": datetime(2026, 9, 17, 11, 42, tzinfo=FUSO),
            "ultimo_ts": datetime(2026, 9, 17, 11, 43, tzinfo=FUSO),
        },
        righe=righe,
    )
    client, _, _ = app_cliente(sessione=sessione)

    risposta = client.get("/op/conversazioni/42")

    assert risposta.status_code == 200
    corpo = risposta.json()
    assert corpo["id"] == 42
    assert corpo["titolo"] == "Dove si fa l'ISEE vicino a La Rosa?"
    assert [t["ruolo"] for t in corpo["turni"]] == ["operatore", "assistente"]
    assert corpo["turni"][0]["fonte"] is None
    assert corpo["turni"][0]["riferimenti"] == [], "lista vuota, mai `None`"
    assert corpo["turni"][1]["fonte"] == "[KB · ACLI — patronato · agg. 17/09/2026 · affidabilità 1]"
    assert corpo["turni"][1]["riferimenti"] == [{"tipo": "luogo", "id": 21, "nome": "CAF ACLI La Rosa"}]


# --- corpo della richiesta --------------------------------------------------------------------------------------


def test_chiave_extra_nel_corpo_del_messaggio_risponde_422(app_cliente):
    """`extra="forbid"` sul messaggio: la Casa e la conversazione non si scelgono dal corpo."""
    client, _, _ = app_cliente()

    risposta = _messaggio(client, casa_id=8)

    assert risposta.status_code == 422
    assert risposta.json()["detail"].startswith("parametri non ammessi")


@pytest.mark.parametrize(
    "messaggio", [pytest.param("", id="vuoto"), pytest.param("a" * 2001, id="oltre_2000")],
)
def test_messaggio_fuori_dai_limiti_risponde_422(app_cliente, messaggio):
    """Il messaggio ha un minimo e un tetto dichiarati (1..2000): fuori da lì è `422`, non una chiamata a Onyx."""
    client, _, _ = app_cliente()

    risposta = _messaggio(client, messaggio=messaggio)

    assert risposta.status_code == 422
    assert risposta.json()["detail"].startswith("parametri non ammessi")


# --- guasti di Onyx ---------------------------------------------------------------------------------------------


def test_onyx_giu_risponde_503_e_non_scrive_turni(app_cliente):
    """Onyx giù è un `503` dichiarato, e la domanda **non** entra nello storico (§4.1.3).

    Uno storico pieno di domande senza risposta è rumore che l'operatore non può ripulire: il turno si scrive a
    risposta arrivata, mai prima.
    """
    client, sessione, _ = app_cliente()

    with respx.mock:
        respx.post(URL_INVIA).mock(side_effect=httpx.ConnectError("Onyx spento"))
        risposta = _messaggio(client)

    assert risposta.status_code == 503
    assert risposta.json() == {"detail": DETAIL_CHAT_NON_DISPONIBILE}
    assert sessione.scritture == [], "un 503 non lascia una domanda senza risposta nello storico"


def test_onyx_piu_lento_del_budget_risponde_503(app_cliente, monkeypatch):
    """Il budget `ONYX_CHAT_TIMEOUT_S` è dichiarato e **vince** sulla lentezza della risposta."""
    monkeypatch.setenv("ONYX_CHAT_TIMEOUT_S", "1")
    client, sessione, _ = app_cliente()

    async def lento(_: httpx.Request) -> httpx.Response:
        import asyncio

        await asyncio.sleep(5)
        return httpx.Response(200, json=_corpo_onyx())

    with respx.mock:
        respx.post(URL_INVIA).mock(side_effect=lento)
        risposta = _messaggio(client)

    assert risposta.status_code == 503
    assert risposta.json() == {"detail": DETAIL_CHAT_NON_DISPONIBILE}
    assert sessione.scritture == []


def test_risposta_senza_testo_leggibile_risponde_503(app_cliente):
    """Onyx risponde 200 con `error_msg`: `503` «risposta non leggibile», non un 200 con testo vuoto."""
    client, sessione, _ = app_cliente()

    with respx.mock:
        respx.post(URL_INVIA).mock(
            return_value=httpx.Response(200, json={"answer": "", "error_msg": "provider quota exceeded", "message_id": 1})
        )
        risposta = _messaggio(client)

    assert risposta.status_code == 503
    assert risposta.json() == {"detail": "risposta non leggibile dalla chat"}
    assert "provider quota" not in risposta.text
    assert sessione.scritture == []


# --- contratto e log (V5/§12) -----------------------------------------------------------------------------------


def test_gli_endpoint_stanno_sotto_op_e_fuori_dal_contratto_con_onyx(app_cliente):
    """Le quattro rotte rispondono sotto `/op` e **non** compaiono nel documento OpenAPI generato.

    Lo schema che FastAPI genera è il contratto congelato con Onyx (gate V-09, verifica per uguaglianza): un endpoint
    del browser dentro quel documento lo romperebbe. `include_in_schema=False` toglie dal documento, non dal routing.
    """
    client, _, _ = app_cliente()

    from app.main import app as applicazione

    percorsi = applicazione.openapi()["paths"]

    with respx.mock:
        respx.post(URL_INVIA).mock(return_value=httpx.Response(200, json=_corpo_onyx()))
        assert _messaggio(client).status_code == 200

    assert client.get("/op/conversazioni").status_code == 200
    assert client.get("/op/conversazioni/42").status_code == 200
    for percorso in (
        "/op/conversazioni",
        "/op/conversazioni/{conversazione_id}",
        "/op/conversazioni/{conversazione_id}/messaggi",
    ):
        assert percorso not in percorsi, f"{percorso} non appartiene al contratto con Onyx"


def test_log_non_contiene_messaggio_ne_risposta(app_cliente, caplog):
    """Il log porta l'`operationId` e lo stato, mai il testo della domanda o della risposta (V5/§12).

    È il presidio che vale di più su questi endpoint: sono quelli che scrivono il testo dell'operatore su disco, e
    una riga di log con la domanda dentro vanificherebbe il filtro anti-PII a monte.
    """
    client, _, _ = app_cliente()
    domanda = "Il signor Bianchi ha lasciato la tessera in portineria"
    risposta_testo = "Nessuna tessera risulta tra i luoghi della rete."

    import logging

    registratore = logging.getLogger("trasi.shim")
    registratore.addHandler(caplog.handler)
    livello = registratore.level
    registratore.setLevel(logging.INFO)
    try:
        with caplog.at_level(logging.INFO, logger="trasi.shim"):
            with respx.mock:
                respx.post(URL_INVIA).mock(
                    return_value=httpx.Response(200, json=_corpo_onyx(risposta_testo, documents=[_documento("trasi%3Aluogo%3A21")]))
                )
                assert _messaggio(client, messaggio=domanda).status_code == 200
    finally:
        registratore.setLevel(livello)
        registratore.removeHandler(caplog.handler)

    testo = "\n".join(voce.getMessage() for voce in caplog.records)

    assert "op_conversazioni_messaggio" in testo, "il log deve nominare l'operationId"
    assert domanda not in testo, "la domanda dell'operatore non entra nel log"
    assert risposta_testo not in testo, "la risposta dell'assistente non entra nel log"
    assert TOKEN_DI_PROVA not in testo, "il PAT non entra nel log"
    assert EMAIL_OPERATORE not in testo, "l'email dell'identità non entra nel log"
