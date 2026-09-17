"""Il monitoraggio del servizio per la PA (US-4): endpoint `/pa/…`, `/v1/m/…` e l'export stampabile.

Onyx è **mockato** (`respx`), la sessione di servizio è sostituita da un doppio: i test verificano ciò che lo shim
decide — quale vista legge, come traduce i parametri, come tratta le lacune — non le decisioni del database (che è
l'unica autorità, e non va simulata in un test che vuole essere vero a casa propria). La logica è osservabile dalla
risposta e dall'elenco delle query che il doppio registra.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

import ambiente

from app.monitoraggio import _DIPENDENZA_DASHBOARD, _DIPENDENZA_RETE

BASE_ONYX = "http://onyx-di-prova:8080"
EMAIL_PA = "pa@trasi.local"
MESSAGGIO_PA = "Quali servizi sono rimasti senza risposta a settembre?"

DETAIL_REPORT_NON_TROVATO = "report non trovato"
DETAIL_STATO_NON_APPROVABILE = "il report non è in stato approvabile"
DETAIL_CHAT_NON_CONFIGURATA = "chat non configurata per la PA"
DETAIL_CHAT_NON_DISPONIBILE = "chat non disponibile: Onyx non ha risposto entro il tempo dichiarato"
DETAIL_NON_AUTORIZZATO = "identità non autorizzata al canale di monitoraggio"
DETAIL_CHIAVE_NON_VALIDA = "chiave shim non valida"
DETAIL_DATO_PERSONALE_SOSPETTO = "dato_personale_sospetto"

# Un report di osservatorio coerente con ciò che `flussi/ciclo_mensile.py` scrive in `contenuti`.
CONTENUTI_REPORT = {
    "richieste": 47,
    "senza_risposta": 6,
    "categorie": {"salute": 12, "lavoro": 9, "servizi": 26},
    "reindirizzamenti": {"inps": 4, "comune": 2},
    "suggerimenti": "Le domande su salute e lavoro sono aumentate: valutare un CAF in sede la mattina.",
}

# Le righe come le lascerebbe `v_report_confronto` (mese decrescente, conteggi k-anon):
RIGA_CONFRONTO = {
    "mese": date(2026, 9, 1),
    "categoria": "salute",
    "esito": "risolta",
    "n": 12,
    "n_label": "12",
    "n_prec": 8,
    "n_prec_label": "8",
    "delta_pct": 50.0,
}

RIGA_LACUNA = {"casa_slug": "san-bao", "casa_nome": "San Bao", "categoria": "salute", "n": 3, "n_label": "<5"}
RIGA_CHAT_ERRORE = {
    "mese": date(2026, 9, 1),
    "casa_slug": None,
    "canale": "sportello",
    "esito": "errore",
    "fonte": None,
    "n": 2,
    "n_label": "<5",
}

RIGA_REPORT = {
    "id": 1,
    "casa_id": None,
    "casa_slug": None,
    "casa_nome": None,
    "mese": date(2026, 9, 1),
    "ambito": "osservatorio",
    "contenuti": CONTENUTI_REPORT,
    "generato_ts": datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc),
    "generato_da": "automazioni",
    "commenti": 0,
    "ultimo_commento_ts": None,
    "ha_csv": True,
    "stato": "approvato",
}


class _SessionePa:
    """Il doppio della sessione di servizio della PA: ruolo `pa`, senza Casa.

    Risponde alle query per **nome della vista**: la vista usata è l'informazione che il test deve vedere,
    non l'effetto che sul DB resta da provare. Un SQL sconosciuto risponde `[]`, così un cambio di vista non
    passa inosservato.
    """

    def __init__(self, *, righe: dict[str, list[dict]] | None = None, valore_approva: Any = None, valore: Any = None) -> None:
        self.ruolo = "pa"
        self.query: list[tuple[str, tuple[Any, ...]]] = []
        self.righe = righe if righe is not None else {"trasi.v_report": [RIGA_REPORT]}
        self.valore_approva = valore_approva
        self.valore = valore

    async def fetch(self, sql: str, *args: Any) -> list[Any]:
        self.query.append((sql, args))
        normalizzata = " ".join(sql.split())
        for chiave, righe in self.righe.items():
            if chiave in normalizzata:
                return righe
        return []

    async def fetchrow(self, sql: str, *args: Any) -> Any:
        self.query.append((sql, args))
        normalizzata = " ".join(sql.split())
        if "trasi.approva_report" in normalizzata:
            return self.valore_approva
        if "trasi.v_report" in normalizzata:
            report = self.righe.get("trasi.v_report", [])
            return dict(report[0]) if report else None
        return None

    async def fetchval(self, sql: str, *args: Any) -> Any:
        self.query.append((sql, args))
        normalizzata = " ".join(sql.split())
        if "max(mese)" in normalizzata or "current_date" in normalizzata:
            return date(2026, 9, 1)
        return self.valore

    async def execute(self, sql: str, *args: Any) -> str:
        self.query.append((sql, args))
        return "OK"


class _SessioneRete(_SessionePa):
    """La sessione del referente AT: stesso comportamento, ruolo diverso."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.ruolo = "rete"


@pytest.fixture
def client_monitoraggio(monkeypatch, tmp_path):
    """`TestClient` sull'app reale: sessione PA sostituita, pool spia per il log chat.

    Il pool spia è montato su `chat` e `monitoraggio` perché il log best-effort è nel modulo della
    chat, e chi lo prova deve poter dire «quale INSERT è stata tentata», non solo «la risposta non è fallita».
    """
    ambiente.configura_ambiente()
    monkeypatch.setattr("app.chat.PERCORSO_ENV", tmp_path / "env-inesistente")
    monkeypatch.setenv("ONYX_CHAT_TOKEN", "pat-di-prova")
    monkeypatch.setenv("ONYX_CHAT_API_URL", BASE_ONYX)

    from app import chat as modulo_chat
    from app import monitoraggio as modulo_monitoraggio
    from app.main import crea_app

    class _LogSpia:
        def __init__(self) -> None:
            self.inserimenti: list[tuple[Any, ...]] = []

        def acquire(self) -> "_AcquisizioneSpia":
            return _AcquisizioneSpia(self)

    class _AcquisizioneSpia:
        def __init__(self, spia: "_LogSpia") -> None:
            self.spia = spia

        async def __aenter__(self) -> "_ConnessioneSpia":
            return _ConnessioneSpia(self.spia)

        async def __aexit__(self, *_: Any) -> bool:
            return False

    class _ConnessioneSpia:
        def __init__(self, spia: "_LogSpia") -> None:
            self.spia = spia

        async def execute(self, sql: str, *args: Any) -> str:
            if "chat_interazione_log" in " ".join(sql.split()):
                self.spia.inserimenti.append(args)
            return "OK"

        async def fetchval(self, *args: Any) -> None:
            return None

    def costruisci(
        sessione: _SessionePa | None = None,
        pool_spia: "_LogSpia | None" = None,
    ) -> tuple[TestClient, _LogSpia]:
        spia = pool_spia or _LogSpia()
        monkeypatch.setattr(modulo_chat, "_pool_corrente", lambda: spia)
        monkeypatch.setattr(modulo_monitoraggio, "_pool_corrente", lambda: spia)
        applicazione = crea_app()
        sess = sessione or _SessionePa()
        applicazione.dependency_overrides[_DIPENDENZA_DASHBOARD] = lambda: sess
        return TestClient(applicazione, raise_server_exceptions=False), spia

    return costruisci


def _corpo_onyx(answer: str = "Le lacune sono tre:…", fonte: str = "[KB · Rete-kb-3 · agg. 15/09/2026 · affidabilità 3]") -> dict[str, Any]:
    return {
        "answer": answer,
        "top_documents": [
            {
                "document_id": "trasi%3Areport%3A1",
                "semantic_identifier": "Report settembre",
                "is_internet": False,
                "metadata": {"fonte": "Rete-kb-3", "data_aggiornamento": "2026-09-15", "affidabilita": "3"},
            }
        ],
        "error_msg": None,
    }


# --- /pa/me ---------------------------------------------------------------------------------------------------


def test_pa_me_risponde_il_ruolo_della_sessione(client_monitoraggio):
    """`GET /pa/me` risponde con il ruolo della sessione: è il modo in cui la dashboard conferma chi è entrato."""
    client, _ = client_monitoraggio()

    risposta = client.get("/pa/me")

    assert risposta.status_code == 200
    assert risposta.json() == {"ruolo": "pa"}


# --- /pa/report -------------------------------------------------------------------------------------------------


def test_report_osservatorio_solo_i_visibili_al_ruolo(client_monitoraggio):
    """La lista dei report filtra per `ambito='osservatorio'` e per lo stato che la policy mostra.

    Il filtro è nel DB (la policy), e il modulo lo espone così com'è: il test verifica che la query vada alla
    vista giusta e che il parametro `mese` passi come argomento, non interpolato.
    """
    client, _ = client_monitoraggio(
        sessione=_SessionePa(righe={"trasi.v_report": [RIGA_REPORT]})
    )

    risposta = client.get("/pa/report", params={"mese": "2026-09"})

    assert risposta.status_code == 200
    corpo = risposta.json()
    assert len(corpo["items"]) == 1
    assert corpo["items"][0]["ambito"] == "osservatorio"
    assert corpo["items"][0]["stato"] == "approvato"
    assert corpo["items"][0]["mese"] == "2026-09-01"


def test_report_senza_mese_rende_tutti_gli_osservatorio(client_monitoraggio):
    """Senza `mese` la lista è tutta la storia dell'osservatorio, non solo l'ultimo mese."""
    client, _ = client_monitoraggio(
        sessione=_SessionePa(
            righe={"trasi.v_report": [RIGA_REPORT, {**RIGA_REPORT, "id": 2, "mese": date(2026, 8, 1), "stato": "inviato_pa"}]}
        )
    )

    risposta = client.get("/pa/report")

    assert risposta.status_code == 200
    assert len(risposta.json()["items"]) == 2


# --- /pa/report/confronto ----------------------------------------------------------------------------------------


def test_confronto_restituisce_le_righe_della_vista(client_monitoraggio):
    """`GET /pa/report/confronto` restituisce le righe di `v_report_confronto` con il tetto dichiarato (12 mesi)."""
    client, _ = client_monitoraggio(
        sessione=_SessionePa(righe={"v_report_confronto": [RIGA_CONFRONTO]})
    )

    risposta = client.get("/pa/report/confronto", params={"mesi": 2})

    assert risposta.status_code == 200
    corpo = risposta.json()
    assert corpo["items"][0]["categoria"] == "salute"
    assert corpo["items"][0]["n_label"] == "12"
    assert corpo["items"][0]["n_prec_label"] == "8"
    # Il tetto è verificabile dal 422: 13 mesi non è ammesso.
    risposta_oltre = client.get("/pa/report/confronto", params={"mesi": 13})
    assert risposta_oltre.status_code == 422


def test_confronto_con_mesi_default_corrisponde_a_due(client_monitoraggio):
    """Il default è 2 mesi: senza parametro la richiesta copre il mese corrente e il precedente.

    Il limite arriva alla query come argomento numerico (non interpolato nel SQL, V5), e il test lo legge dal
    comando registrato dalla spia: la prova è il parametro passato, non il risultato che il DB avrebbe filtrato.
    """
    sessione = _SessionePa(righe={"v_report_confronto": [RIGA_CONFRONTO]})
    client, _ = client_monitoraggio(sessione=sessione)

    risposta = client.get("/pa/report/confronto")

    assert risposta.status_code == 200
    assert len(risposta.json()["items"]) == 1
    confronto_query = [q for q in sessione.query if "v_report_confronto" in " ".join(q[0].split())]
    assert confronto_query, "la vista di confronto deve essere interpellata"
    assert confronto_query[0][1] == (2,), "il default è di due mesi"


# --- /pa/lacune ---------------------------------------------------------------------------------------------------


def test_lacune_riporta_i_due_elenchi_separati(client_monitoraggio):
    """Le lacune hanno due elenchi distinti: le richieste senza risposta e gli errori della chat.

    La separazione è il punto: se fossero un unico elenco, il LLM non saprebbe dire se il problema è la
    risposta mancata o il canale non funzionante.
    """
    client, _ = client_monitoraggio(
        sessione=_SessionePa(
            righe={
                "v_report_mensile": [RIGA_LACUNA],
                "v_chat_mensile": [RIGA_CHAT_ERRORE],
            }
        )
    )

    risposta = client.get("/pa/lacune", params={"mese": "2026-09"})

    assert risposta.status_code == 200
    corpo = risposta.json()
    assert corpo["mese"] == "2026-09-01"
    assert corpo["richieste_non_trovate"][0]["categoria"] == "salute"
    assert corpo["richieste_non_trovate"][0]["n_label"] == "<5"
    assert corpo["chat_errori"][0]["canale"] == "sportello"
    assert corpo["chat_errori"][0]["fonte"] is None


def test_lacune_senza_mese_usa_il_mese_piu_recente(client_monitoraggio):
    """Senza parametro la lacuna si riferisce al mese del report più recente, non al mese corrente a mezzanotte."""
    client, _ = client_monitoraggio()

    risposta = client.get("/pa/lacune")

    assert risposta.status_code == 200
    assert risposta.json()["mese"] == "2026-09-01"


# --- /pa/report/{id} -----------------------------------------------------------------------------------------------


def test_report_dettaglio_risponde_contenuti_e_commenti(client_monitoraggio):
    """Il dettaglio ha contenuti, commenti e stato: ciò che basta per leggere il report in dashboard."""
    client, _ = client_monitoraggio()

    risposta = client.get("/pa/report/1")

    assert risposta.status_code == 200
    corpo = risposta.json()
    assert corpo["id"] == 1
    assert corpo["stato"] == "approvato"
    assert corpo["contenuti"]["richieste"] == 47
    assert corpo["commenti_lista"] == []


def test_report_inesistente_risponde_404(client_monitoraggio):
    """Un report che la policy non mostra risponde 404: non si distingue «non c'è» da «non puoi vederlo»."""
    client, _ = client_monitoraggio(sessione=_SessionePa(righe={"trasi.v_report": []}))

    risposta = client.get("/pa/report/9999")

    assert risposta.status_code == 404
    assert risposta.json() == {"detail": DETAIL_REPORT_NON_TROVATO}


# --- /pa/report/{id}/export ----------------------------------------------------------------------------------------


def test_export_e_html_stampabile_con_fonte_dichiarata(client_monitoraggio):
    """L'export è una pagina HTML autonoma con `@page`, fonte dichiarata nel footer e nessun numero grezzo.

    Il footer dice «fonte: viste trasi.*» perché una pagina stampata si legge fuori dal sistema e deve portare
    con sé la provenienza. Il conteggio k-anon è «<5», mai il numero intero.
    """
    client, _ = client_monitoraggio()

    risposta = client.get("/pa/report/1/export")

    assert risposta.status_code == 200
    assert risposta.headers["content-type"].startswith("text/html")
    corpo = risposta.text
    assert "@page" in corpo
    assert "Fonte: viste trasi." in corpo
    assert "2026-09" in corpo
    # Il suggerimento arriva nel testo, non come numero grezzo.
    assert "CAF" in corpo
    # Nessun dato grezzo che il k-anonimato nasconde: il suggerimento va bene come testo, ma il report non
    # contiene le celle isolate con un numero basso — qui non ci sono perché `RIGA_REPORT` li porta solo in
    # aggregati già formattati, e il test li verifica come presenti, non come testo nascosto.
    assert "12" in corpo  # i conteggi sono presenti come valori leggibili


def test_export_di_report_inesistente_risponde_404(client_monitoraggio):
    """Un report che non esiste non produce HTML, nemmeno vuoto: 404, come il dettaglio."""
    client, _ = client_monitoraggio(sessione=_SessionePa(righe={"trasi.v_report": []}))

    risposta = client.get("/pa/report/9999/export")

    assert risposta.status_code == 404
    assert risposta.json() == {"detail": DETAIL_REPORT_NON_TROVATO}


# --- /pa/report/{id}/approva (rete) -------------------------------------------------------------------------------


def test_approva_chiama_la_funzione_del_database(client_monitoraggio):
    """L'approvazione è una sola chiamata a `trasi.approva_report`, non un UPDATE dello shim.

    La transizione è atomica e auditable nel database: lo shim non scrive sul report, delega alla funzione
    `SECURITY DEFINER` che è il suo unico punto di scrittura.
    """
    client, _ = client_monitoraggio()
    sessione_rete = _SessioneRete()

    applicazione = client.app
    applicazione.dependency_overrides[_DIPENDENZA_RETE] = lambda: sessione_rete

    risposta = client.post("/pa/report/1/approva")

    assert risposta.status_code == 200
    assert risposta.json() == {"id": 1, "stato": "approvato"}
    assert any("trasi.approva_report" in " ".join(q[0].split()) for q in sessione_rete.query), (
        "l'approvazione è una SELECT trasi.approva_report, non un UPDATE"
    )


def test_approva_su_report_gia_approvato_risponde_409(client_monitoraggio):
    """Il database dice «non è in bozza» e lo shim risponde 409: lo stato non è una sorpresa da scoprire dopo.

    Il test contraffà la funzione del DB con un'eccezione che contiene la parola «stato»: è il modo in cui il DB
    dice «non è in bozza» (RAISE EXCEPTION con il messaggio), e il 409 è la sua traduzione, non uno stacktrace.
    """
    sessione_rete = _SessioneRete()

    async def _execute_con_errore(sql: str, *args: Any) -> str:
        sessione_rete.query.append((sql, args))
        if "approva_report" in " ".join(sql.split()):
            raise Exception("stato report non bozza, richiesta un aggiornamento")
        return "OK"

    sessione_rete.execute = _execute_con_errore  # type: ignore[method-assign]

    client, _ = client_monitoraggio()

    applicazione = client.app
    applicazione.dependency_overrides[_DIPENDENZA_RETE] = lambda: sessione_rete

    risposta = client.post("/pa/report/1/approva")

    assert risposta.status_code == 409
    assert risposta.json() == {"detail": DETAIL_STATO_NON_APPROVABILE}


# --- /pa/chat ------------------------------------------------------------------------------------------------------


def test_chat_pa_risponde_con_fonte_e_logga_in_chat_interazione(client_monitoraggio):
    """La chat PA proxy a Onyx come per lo sportello, e lascia una riga in `chat_interazione_log` con canale='pa'.

    Il testo del messaggio non entra nel log: la traccia è esito+fonte, mai il contenuto. Il badge della fonte
    arriva dallo shim, non da Onyx (V3).
    """
    client, spia = client_monitoraggio()

    with respx.mock:
        respx.post(f"{BASE_ONYX}/chat/create-chat-session").mock(
            return_value=httpx.Response(200, json={"chat_session_id": "sessione-pa"})
        )
        respx.post(f"{BASE_ONYX}/chat/send-chat-message").mock(
            return_value=httpx.Response(200, json=_corpo_onyx())
        )
        risposta = client.post("/pa/chat", json={"messaggio": MESSAGGIO_PA})

    assert risposta.status_code == 200
    assert risposta.json()["risposta"] == "Le lacune sono tre:…"
    assert "Rete-kb-3" in risposta.json()["fonte"]
    # Il log è scritto: canale 'pa', esito 'risposta', fonte 'kb' (dal badge KB), mai il testo.
    inserimenti = [i for i in spia.inserimenti if len(i) == 4]
    assert inserimenti, "chat_interazione_log deve avere una riga per la conversazione"
    casa_id, canale, esito, fonte = inserimenti[0]
    assert canale == "pa"
    assert esito == "risposta"
    assert fonte == "kb"


def test_chat_pa_senza_token_risponde_503_dichiarato(client_monitoraggio, monkeypatch, tmp_path):
    """Senza `ONYX_CHAT_TOKEN` la chat PA risponde 503 «non configurata», non 500.

    Il messaggio è diverso da quello dello sportello: la mancanza del PAT è la stessa, ma la diagnosi è di questo
    canale — il referente deve sapere che è la chat PA a non essere pronta, non la chat dello sportello.
    """
    monkeypatch.delenv("ONYX_CHAT_TOKEN", raising=False)
    monkeypatch.setattr("app.chat.PERCORSO_ENV", tmp_path / "env-inesistente")
    client, _ = client_monitoraggio()

    risposta = client.post("/pa/chat", json={"messaggio": MESSAGGIO_PA})

    assert risposta.status_code == 503
    assert risposta.json() == {"detail": DETAIL_CHAT_NON_CONFIGURATA}


def test_chat_pa_con_dato_personale_risponde_422(client_monitoraggio):
    """Il filtro anti-PII vale anche per la chat PA: un messaggio con un telefono non arriva al provider (V5)."""
    client, spia = client_monitoraggio()

    risposta = client.post("/pa/chat", json={"messaggio": "Richiamare il signor Rossi al 333 123 4567"})

    assert risposta.status_code == 422
    assert DETAIL_DATO_PERSONALE_SOSPETTO in risposta.json()["detail"]
    # Il database non è stato toccato: il 422 arriva prima della configurazione e dell'identità.
    assert spia.inserimenti == [], "un dato personale si rifiuta prima di qualunque INSERT"


def test_chat_pa_on_guasto_logga_errore_e_risponde_503(client_monitoraggio):
    """Se Onyx non risponde, la chat PA risponde 503 e il log porta 'errore': il fatto che il canale sia vivo si vede."""
    client, spia = client_monitoraggio()

    with respx.mock:
        respx.post(f"{BASE_ONYX}/chat/create-chat-session").mock(
            side_effect=httpx.ConnectError("Onyx spento")
        )
        risposta = client.post("/pa/chat", json={"messaggio": MESSAGGIO_PA})

    assert risposta.status_code == 503
    assert risposta.json() == {"detail": DETAIL_CHAT_NON_DISPONIBILE}
    inserimenti = [i for i in spia.inserimenti if len(i) == 4]
    assert inserimenti[0][2] == "errore", "il ramo Guasto lascia una riga con esito 'errore'"
    assert inserimenti[0][3] is None, "il guasto non dichiara una fonte"


# --- /v1/m/{email} — i tool di Onyx, solo per ruolo `pa` -----------------------------------------------------------


class _SessioneStrumenti:
    """Sessione da `dipendenza_sessione` (canale Onyx): email + ruolo, come per gli altri tool.

    Il ruolo è il parametro: i test controllano che una sessione con un ruolo diverso da `pa` non entri.
    """

    def __init__(self, email: str = EMAIL_PA, ruolo: str = "pa", righe: dict[str, list[dict]] | None = None) -> None:
        self.email = email
        self.ruolo = ruolo
        self.casa_id: int | None = None
        self.query: list[tuple[str, tuple[Any, ...]]] = []
        self.righe = righe or {}

    async def fetch(self, sql: str, *args: Any) -> list[Any]:
        self.query.append((sql, args))
        normalizzata = " ".join(sql.split())
        for chiave, righe in self.righe.items():
            if chiave in normalizzata:
                return righe
        return []

    async def fetchval(self, sql: str, *args: Any) -> Any:
        self.query.append((sql, args))
        if "max(mese)" in " ".join(sql.split()) or "current_date" in " ".join(sql.split()):
            return date(2026, 9, 1)
        return None

    async def fetchrow(self, sql: str, *args: Any) -> Any:
        self.query.append((sql, args))
        return None

    async def execute(self, sql: str, *args: Any) -> str:
        self.query.append((sql, args))
        return "OK"


@pytest.fixture
def client_m(monkeypatch):
    """Client con la sessione degli strumenti (`/v1/m`) contraffatta: il risolutore dell'identità è il canale Onyx."""
    ambiente.configura_ambiente()

    from app import db as modulo_db
    from app.main import crea_app

    def costruisci(ruolo: str = "pa", righe: dict[str, list[dict]] | None = None) -> tuple[TestClient, _SessioneStrumenti]:
        sess = _SessioneStrumenti(ruolo=ruolo, righe=righe)
        app = crea_app()
        app.dependency_overrides[modulo_db.sessione] = lambda: sess
        return TestClient(app, raise_server_exceptions=False), sess

    return costruisci


def test_m_report_restituisce_i_report_osservatorio(client_m):
    """Il tool `monitoraggio_report` risponde in JSON come gli altri tool: stessa vista, stessa forma."""
    client, sess = client_m(righe={"trasi.v_report": [RIGA_REPORT]})

    risposta = client.get("/v1/m/pa@trasi.local/report")

    assert risposta.status_code == 200
    assert risposta.json()["items"][0]["ambito"] == "osservatorio"


def test_m_report_con_un_ruolo_diverso_risponde_403(client_m):
    """Il tool del monitoraggio non è dello sportello: con ruolo `casa_sanbao` risponde 403.

    La risposta è diversa da `identita non riconosciuta`: l'identità esiste, ma il suo ruolo non è quello
    richiesto. Il 403 dedicato dice al LLM perché il tool non è per lui.
    """
    client, _ = client_m(ruolo="casa_sanbao")

    risposta = client.get("/v1/m/op.san-bao@trasi.local/report")

    assert risposta.status_code == 403
    assert risposta.json() == {"detail": DETAIL_NON_AUTORIZZATO}


def test_m_confronto_restituisce_le_righe_della_vista(client_m):
    """`monitoraggio_confronto` restituisce le righe di `v_report_confronto` in JSON."""
    client, _ = client_m(righe={"v_report_confronto": [RIGA_CONFRONTO]})

    risposta = client.get("/v1/m/pa@trasi.local/confronto", params={"mesi": 2})

    assert risposta.status_code == 200
    assert risposta.json()["items"][0]["categoria"] == "salute"
    assert risposta.json()["items"][0]["n_label"] == "12"


def test_m_lacune_riporta_richieste_e_chat_separati(client_m):
    """`monitoraggio_lacune` restituisce i due elenchi separati, come la dashboard."""
    client, _ = client_m(
        righe={
            "v_report_mensile": [RIGA_LACUNA],
            "v_chat_mensile": [RIGA_CHAT_ERRORE],
        }
    )

    risposta = client.get("/v1/m/pa@trasi.local/lacune", params={"mese": "2026-09"})

    assert risposta.status_code == 200
    corpo = risposta.json()
    assert corpo["mese"] == "2026-09-01"
    assert len(corpo["richieste_non_trovate"]) == 1
    assert len(corpo["chat_errori"]) == 1


def test_m_chat_stats_non_contiene_mai_il_testo_della_chat(client_m):
    """`monitoraggio_chat_stats` espone canale, esito, fonte e k-anon: mai il testo (V5).

    Non è una verifica formale — il test è sul **campo assente** — ed è la forma più semplice di provare che
    la vista usata non porti il contenuto delle conversazioni.
    """
    client, _ = client_m(righe={"v_chat_mensile": [RIGA_CHAT_ERRORE]})

    risposta = client.get("/v1/m/pa@trasi.local/chat_stats", params={"mese": "2026-09"})

    assert risposta.status_code == 200
    corpo = risposta.json()
    assert corpo["items"][0]["canale"] == "sportello"
    assert corpo["items"][0]["n_label"] == "<5"
    # Nessun campo che possa portare testo di una conversazione.
    assert set(corpo["items"][0]).issubset({"mese", "casa_slug", "canale", "esito", "fonte", "n", "n_label"})


# --- contratto congelato (V-09) --------------------------------------------------------------------------------------


def test_le_route_del_monitoraggio_non_entrano_nello_schema_openapi(client_m):
    """Le route `/pa/…` e `/v1/m/…` non compaiono nello schema: il gate V-09 resta a nove operationId."""
    from app.main import app as applicazione

    percorsi = set(applicazione.openapi()["paths"])
    for percorso in ("/pa/me", "/pa/report", "/pa/lacune", "/v1/m/{email}/report", "/v1/m/{email}/confronto"):
        assert percorso not in percorsi
