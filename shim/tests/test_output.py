"""Test degli output: `biglietto`, `oggi`, `cerca_web` (B3-SHM-07/08/12) e `scheda_evento` (US-1.3).

SearXNG è **mockato** (`respx`) e il database è sostituito da una sessione finta per i test del contratto: un test
che dipendesse da ciò che il motore restituisce davvero non proverebbe il filtro — proverebbe il motore. Il caso
«tutti i risultati filtrati» è testato esplicitamente perché, con l'allow-list reale (5 fonti istituzionali) e i
risultati commerciali delle query tipiche (`paginegialle.it`, `paginebianche.it`), è il caso **normale**.

Il confronto dei domini è per **host**, non per sottostringa: `falso-inps.it.example` non è autorizzato da `inps.it`.

La **scheda evento** (`GET /op/scheda_evento`) è provata come il biglietto — formato `@page`, divieti lessicali,
badge V3, 404 — e in più sul **divieto di scrittura**, contando le query che riceve: è l'unica prova di «read-only»
che non dipende da come si legge il codice. Il test `live` difende la query contro il database vero, perché
l'ambiguità di colonna di una JOIN (`column reference "id" is ambiguous`) su un doppio non comparirebbe.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

import ambiente

# Il fuso di riferimento del progetto (`badge.FUSO_ITALIANO`): gli eventi di prova sono istanti locali, come
# quelli che `asyncpg` restituisce convertiti — un `datetime` ingenuo renderebbe il test dipendente dalla TZ
# del processo invece che dal comportamento dell'endpoint.
FUSO = ZoneInfo("Europe/Rome")

CHIAVE = ambiente.CHIAVE_SHIM or "chiave-di-test"

# Le fonti web attive del seed (`db/011_seed_fonti.sql`), con la fiducia dichiarata.
DOMINI_ALLOWLIST = {
    "www.comune.brindisi.it": ("Comune di Brindisi", 3),
    "www.asl.brindisi.it": ("ASL della Provincia di Brindisi", 3),
    "www.inps.it": ("INPS", 3),
    "www.regione.puglia.it": ("Regione Puglia", 3),
    "questure.poliziadistato.it": ("Ministero dell'Interno — Polizia di Stato", 3),
}


class SessioneFinta:
    """Sessione senza database: risponde alle tre query degli output con dati di seed realistici."""

    def __init__(
        self,
        *,
        casa_id: int | None = 5,
        ruolo: str = "casa_sanbao",
        riga_oggi: dict[str, Any] | None = None,
        luogo: dict[str, Any] | None = None,
        evento: dict[str, Any] | None = None,
        fonti_web: list[dict[str, Any]] | None = None,
        parametri_valori: dict[str, Any] | None = None,
        righe_statistiche: list[dict[str, Any]] | None = None,
        casa_esiste: bool | None = None,
    ) -> None:
        self.casa_id = casa_id
        self.ruolo = ruolo
        self.email = ambiente.EMAIL_SANBAO
        self.eseguite: list[tuple[str, tuple[Any, ...]]] = []
        self.riga_oggi = riga_oggi
        self.righe_statistiche = righe_statistiche
        self.casa_esiste = casa_esiste
        self.luogo = luogo
        self.evento = evento
        self.fonti_web = fonti_web if fonti_web is not None else [
            {"fonte": nome, "url": f"https://{dominio}", "livello_fiducia": fiducia, "tecnica": dominio}
            for dominio, (nome, fiducia) in DOMINI_ALLOWLIST.items()
        ]
        self.parametri_valori = parametri_valori or {
            "fiducia_min_esterna": 2,
            "max_risultati_esterni": 5,
        }

    async def fetch(self, sql: str, *args: Any) -> list[Any]:
        self.eseguite.append((sql, args))
        if "FROM trasi.fonte" in sql and "tipo_accesso" in sql:
            return self.fonti_web
        if "FROM trasi.parametro" in sql:
            chiavi = args[0] if args else []
            return [
                {"chiave": chiave, "valore": str(self.parametri_valori[chiave]), "tipo": "int"}
                for chiave in chiavi
                if chiave in self.parametri_valori
            ]
        if "FROM trasi.v_report_mensile" in sql:
            return self.righe_statistiche or []
        return []

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        self.eseguite.append((sql, args))
        # L'evento per primo: la sua query porta una sotto-select su `trasi.luogo` (la nota di accesso
        # della Casa) e una JOIN su `trasi.casa`, quindi senza questo ordine il doppio risponderebbe con
        # la riga del luogo o della Casa — cioè il test proverebbe una pagina costruita su dati sbagliati.
        if "FROM trasi.evento" in sql:
            return self.evento
        if "v_oggi_casa" in sql:
            return self.riga_oggi
        if "FROM trasi.luogo" in sql:
            return self.luogo
        if "FROM trasi.casa" in sql:
            return {"id": self.casa_id, "slug": args[0] if args else None, "nome": "San Bao", "lat": 40.60609, "lon": 17.95196}
        if "FROM trasi.fonte" in sql:
            return {"fonte": "OpenStreetMap contributors (ODbL)"}
        return None

    async def fetchval(self, sql: str, *args: Any) -> Any:
        self.eseguita(sql, args)
        # `statistiche` verifica l'esistenza della Casa con `SELECT id FROM trasi.casa WHERE slug = $1`
        # e il nome con `SELECT nome FROM trasi.casa …`: il doppio risponde con lo stato che il test ha
        # preparato (default: la Casa esiste, come nel seed).
        if "FROM trasi.casa" in sql and "slug = $1" in sql:
            if self.casa_esiste is False:
                return None
            return self.casa_id if "SELECT id" in sql else "San Bao"
        return None

    def eseguita(self, sql: str, args: tuple[Any, ...]) -> None:
        self.eseguite.append((sql, args))


@pytest.fixture
def app_cliente(monkeypatch):
    """`TestClient` sull'app reale con la sessione sostituita.

    Due dipendenze di sessione e non una, perché lo shim ne ha due: `db.sessione` è la via di Onyx
    (chiave + email nel percorso) e `auth.sessione_corrente` è la via dell'operatore (cookie) sotto
    `/op`. Il doppio risponde a entrambe, così un test dell'area operatore non deve costruire una
    sessione diversa — e una differenza di comportamento fra i due canali resta visibile.
    """
    ambiente.configura_ambiente()

    from app import main as modulo_main
    from app.auth import sessione_corrente
    from app.db import sessione as dipendenza

    def costruisci(sessione_finta: SessioneFinta) -> TestClient:
        applicazione = modulo_main.crea_app()
        applicazione.dependency_overrides[dipendenza] = lambda: sessione_finta
        applicazione.dependency_overrides[sessione_corrente] = lambda: sessione_finta
        return TestClient(applicazione, raise_server_exceptions=False)

    return costruisci


def _intestazioni() -> dict[str, str]:
    return {"X-Trasi-Key": CHIAVE}


# --- `oggi` ---------------------------------------------------------------------------------------------------


RIGA_OGGI = {
    "casa_id": 5,
    "slug": "san-bao",
    "nome": "San Bao",
    "data": "2026-09-15",
    "eventi": 2,
    "schede_in_scadenza": 1,
    "proposte": 3,
    "giorni_piu_vecchia": 27,
    "testo": "Oggi a San Bao: 2 eventi · 1 scheda in scadenza · 3 proposte",
}


def test_oggi_riporta_i_conteggi_e_il_testo_della_vista(app_cliente):
    """`oggi` restituisce i conteggi della vista e il `testo` già composto: le due cose non possono divergere."""
    client = app_cliente(SessioneFinta(riga_oggi=RIGA_OGGI))

    risposta = client.get(
        f"/v1/u/{ambiente.EMAIL_SANBAO}/oggi", headers=_intestazioni(), params={"casa": "san-bao"}
    )

    assert risposta.status_code == 200
    assert risposta.json() == {
        "casa": "san-bao",
        "eventi": 2,
        "schede_in_scadenza": 1,
        "proposte": 3,
        "giorni_piu_vecchia": 27,
        "testo": "Oggi a San Bao: 2 eventi · 1 scheda in scadenza · 3 proposte",
    }


def test_oggi_senza_proposte_in_attesa_riporta_zero_giorni(app_cliente):
    """Coda vuota → `giorni_piu_vecchia == 0`, mai `null`: il consumatore lo usa come booleano (`if (giorni)`).

    Il valore è verificato contro il contratto congelato, che dichiara `type: integer` **senza** `nullable`: un `NULL`
    sfuggito dal `COALESCE` della vista arriverebbe qui come `null` e questo test fallirebbe sia sul confronto sia sulla
    validazione di schema — che è il modo in cui il difetto si manifesterebbe davvero, cioè nel consumatore.
    """
    pytest.importorskip("jsonschema")
    import yaml
    from jsonschema import Draft7Validator

    contratto = yaml.safe_load(
        (Path(__file__).resolve().parent.parent / "openapi.yaml").read_text(encoding="utf-8")
    )
    validatore = Draft7Validator(_schema_risolto(contratto, "RispostaOggi"))

    client = app_cliente(SessioneFinta(riga_oggi={**RIGA_OGGI, "proposte": 0, "giorni_piu_vecchia": 0}))

    risposta = client.get(
        f"/v1/u/{ambiente.EMAIL_SANBAO}/oggi", headers=_intestazioni(), params={"casa": "san-bao"}
    )

    assert risposta.status_code == 200
    corpo = risposta.json()
    assert corpo["giorni_piu_vecchia"] == 0
    assert corpo["giorni_piu_vecchia"] is not None
    errori = sorted(validatore.iter_errors(corpo), key=str)
    assert errori == [], errori


def test_oggi_conteggi_coincidono_con_v_oggi_casa(app_cliente):
    """I numeri della risposta sono quelli della vista: si verifica sul database vero con la stessa vista.

    Il test confronta la risposta HTTP con una lettura diretta di `v_oggi_casa`, quindi non può passare se l'endpoint
    riformattasse i conteggi per conto suo.
    """
    if not ambiente.dsn_disponibile():
        pytest.skip(f"database non raggiungibile ({ambiente.dsn_test()})")
    ambiente.configura_ambiente()

    from app.main import crea_app

    with TestClient(crea_app(), raise_server_exceptions=False) as client:
        risposta = client.get(
            f"/v1/u/{ambiente.EMAIL_SANBAO}/oggi", headers=_intestazioni(), params={"casa": ambiente.SLUG_SANBAO}
        )
    assert risposta.status_code == 200, risposta.text

    async def dalla_vista() -> dict[str, Any]:
        conn = await ambiente.connessione(ruolo="casa_sanbao")
        try:
            riga = await conn.fetchrow(
                "SELECT casa_id, slug, eventi, schede_in_scadenza, proposte, giorni_piu_vecchia, testo "
                "FROM trasi.v_oggi_casa WHERE slug = $1",
                ambiente.SLUG_SANBAO,
            )
            return dict(riga)
        finally:
            await conn.close()

    atteso = asyncio.run(dalla_vista())
    corpo = risposta.json()
    assert (
        corpo["casa"],
        corpo["eventi"],
        corpo["schede_in_scadenza"],
        corpo["proposte"],
        corpo["giorni_piu_vecchia"],
        corpo["testo"],
    ) == (
        atteso["slug"],
        atteso["eventi"],
        atteso["schede_in_scadenza"],
        atteso["proposte"],
        atteso["giorni_piu_vecchia"],
        atteso["testo"],
    )


def test_oggi_di_un_altra_casa_non_esiste_per_il_ruolo(app_cliente):
    """La vista è `security_invoker=false`: il filtro sulla Casa corrente deve stare nella query, o l'operatore
    leggerebbe i conteggi di tutte e dieci le Case. Qui la vista non restituisce la riga richiesta → 404."""
    client = app_cliente(SessioneFinta(riga_oggi=None))

    risposta = client.get(
        f"/v1/u/{ambiente.EMAIL_SANBAO}/oggi", headers=_intestazioni(), params={"casa": "bozzano"}
    )

    assert risposta.status_code == 404


def test_oggi_filtra_sulla_casa_corrente_nella_query(app_cliente):
    """La query chiede al database la Casa corrente: la decisione di visibilità resta del database (§11)."""
    sessione_finta = SessioneFinta(riga_oggi=RIGA_OGGI)
    client = app_cliente(sessione_finta)

    client.get(f"/v1/u/{ambiente.EMAIL_SANBAO}/oggi", headers=_intestazioni(), params={"casa": "san-bao"})

    query = [q for q, _ in sessione_finta.eseguite if "v_oggi_casa" in q]
    assert query, "nessuna lettura di v_oggi_casa"
    assert "casa_corrente" in query[0]


# --- `statistiche` --------------------------------------------------------------------------------------------


RIGHE_SANBAO_SETTEMBRE = [
    {"casa_slug": "san-bao", "mese": "2026-09-01", "categoria": "fiscale_isee", "esito": "inviata_altrove", "n": None, "n_label": "<5"},
    {"casa_slug": "san-bao", "mese": "2026-09-01", "categoria": "orientamento", "esito": "risolta", "n": 375, "n_label": "375"},
]


def test_statistiche_riporta_le_righe_e_il_testo_della_vista(app_cliente):
    """`statistiche` restituisce le righe della vista e il `testo` composto su `n_label`: i due non possono divergere."""
    client = app_cliente(SessioneFinta(righe_statistiche=RIGHE_SANBAO_SETTEMBRE))

    risposta = client.get(
        f"/v1/u/{ambiente.EMAIL_SANBAO}/statistiche",
        headers=_intestazioni(),
        params={"casa": "san-bao", "mese": "2026-09"},
    )

    assert risposta.status_code == 200
    corpo = risposta.json()
    assert corpo["casa"] == "san-bao"
    assert corpo["mese"] == "2026-09"
    assert [(a["categoria"], a["esito"], a["n"], a["n_label"]) for a in corpo["ambiti"]] == [
        ("fiscale_isee", "inviata_altrove", None, "<5"),
        ("orientamento", "risolta", 375, "375"),
    ]
    # Il testo dice ciò che la vista dichiara: «375» al netto, «<5» dove il k-anonimato maschera.
    assert "375 richieste risolte" in corpo["testo"]
    assert "<5" in corpo["testo"]


def test_statistiche_mese_default_e_quello_corrente(app_cliente):
    """Senza `mese` la risposta riguarda il mese corrente, calcolato nel fuso italiano."""
    client = app_cliente(SessioneFinta(righe_statistiche=RIGHE_SANBAO_SETTEMBRE))

    risposta = client.get(
        f"/v1/u/{ambiente.EMAIL_SANBAO}/statistiche", headers=_intestazioni(), params={"casa": "san-bao"}
    )

    assert risposta.status_code == 200
    from datetime import date

    assert risposta.json()["mese"] == date.today().strftime("%Y-%m")


def test_statistiche_mese_senza_richieste_200_con_lista_vuota(app_cliente):
    """Un mese senza richieste è 200 con `ambiti: []`: è «mese senza attività», non un errore."""
    client = app_cliente(SessioneFinta(righe_statistiche=[]))

    risposta = client.get(
        f"/v1/u/{ambiente.EMAIL_SANBAO}/statistiche",
        headers=_intestazioni(),
        params={"casa": "san-bao", "mese": "2026-02"},
    )

    assert risposta.status_code == 200
    corpo = risposta.json()
    assert corpo["ambiti"] == []
    assert "nessuna richiesta" in corpo["testo"]


def test_statistiche_mese_fuori_formato_422(app_cliente):
    """`mese=2026-2` non è `AAAA-MM`: 422, senza arrivare al database."""
    client = app_cliente(SessioneFinta(righe_statistiche=RIGHE_SANBAO_SETTEMBRE))

    risposta = client.get(
        f"/v1/u/{ambiente.EMAIL_SANBAO}/statistiche",
        headers=_intestazioni(),
        params={"casa": "san-bao", "mese": "2026-2"},
    )

    assert risposta.status_code == 422
    assert "mese" in risposta.json()["detail"]


def test_statistiche_mese_impossibile_422(app_cliente):
    """`2026-13` passa il pattern ma non è un mese: 422, non un 500 dal `::date`."""
    client = app_cliente(SessioneFinta(righe_statistiche=RIGHE_SANBAO_SETTEMBRE))

    risposta = client.get(
        f"/v1/u/{ambiente.EMAIL_SANBAO}/statistiche",
        headers=_intestazioni(),
        params={"casa": "san-bao", "mese": "2026-13"},
    )

    assert risposta.status_code == 422


def test_statistiche_di_un_altra_casa_non_esiste_per_il_ruolo(app_cliente):
    """Casa inesistente (e operatore senza fallback) → 404, come `eventi_oggi`: vocabolario chiuso."""
    client = app_cliente(SessioneFinta(righe_statistiche=[], casa_esiste=False))

    risposta = client.get(
        f"/v1/u/{ambiente.EMAIL_SANBAO}/statistiche",
        headers=_intestazioni(),
        params={"casa": "casa-che-non-c'e"},
    )

    assert risposta.status_code == 404


def test_statistiche_filtra_sulla_casa_corrente_nella_query(app_cliente):
    """La vista è `security_invoker=false`: il filtro sulla Casa corrente deve stare nella query (§11)."""
    sessione_finta = SessioneFinta(righe_statistiche=RIGHE_SANBAO_SETTEMBRE)
    client = app_cliente(sessione_finta)

    client.get(
        f"/v1/u/{ambiente.EMAIL_SANBAO}/statistiche", headers=_intestazioni(), params={"casa": "san-bao"}
    )

    query = [q for q, _ in sessione_finta.eseguite if "v_report_mensile" in q]
    assert query, "nessuna lettura di v_report_mensile"
    assert "casa_corrente" in query[0]


def test_statistiche_risposta_conforme_al_contratto(app_cliente):
    """La risposta valida contro lo schema `RispostaStatistiche` del contratto congelato (jsonschema)."""
    pytest.importorskip("jsonschema")
    import yaml
    from jsonschema import Draft7Validator

    contratto = yaml.safe_load(
        (Path(__file__).resolve().parent.parent / "openapi.yaml").read_text(encoding="utf-8")
    )

    # L'helper del modulo (sotto, usato anche da `test_oggi_*`) traduce `nullable` per draft7: senza,
    # `n: null` sarebbe respinto anche se il contratto lo dichiara.
    validatore = Draft7Validator(_schema_risolto(contratto, "RispostaStatistiche"))
    client = app_cliente(SessioneFinta(righe_statistiche=RIGHE_SANBAO_SETTEMBRE))

    risposta = client.get(
        f"/v1/u/{ambiente.EMAIL_SANBAO}/statistiche",
        headers=_intestazioni(),
        params={"casa": "san-bao", "mese": "2026-09"},
    )

    errori = sorted(validatore.iter_errors(risposta.json()), key=str)
    assert errori == [], errori


# --- `biglietto` ----------------------------------------------------------------------------------------------


LUOGO_BOZZANO = {
    "id": 6,
    "nome": "Bar interno — Centro di Aggregazione Bozzano",
    "tipo": "bar",
    "indirizzo": "Via Bozzano 1",
    "note_accesso": "Ingresso dalla Casa",
    "lat": 40.6235,
    "lon": 17.9427,
    "orari_testo": "lun-ven 08:00-20:00",
    "data_aggiornamento": None,
    "affidabilita": 3,
    "url": None,
    "ext_ref": None,
    "fonte_autorita": "Rete delle Case di Quartiere di Brindisi",
    "fonte_tecnica": "Rete-kb-3",
    "casa_slug": "bozzano",
    "casa_nome": "Centro di Aggregazione Bozzano",
}


def test_biglietto_html_a6_senza_campi_cittadino(app_cliente):
    """Il biglietto è un foglio A6, senza moduli e senza campi del cittadino: è il criterio di B3-SHM-07.

    Le parole vietate sono cercate nel documento intero — comprese le etichette e i commenti — perché ciò che conta è
    che il foglio non offra alcun posto dove scrivere un nome o un telefono.
    """
    client = app_cliente(SessioneFinta(luogo=LUOGO_BOZZANO, casa_id=5))

    risposta = client.get(
        f"/v1/u/{ambiente.EMAIL_SANBAO}/biglietto",
        headers=_intestazioni(),
        params={"luogo_id": 6, "casa": "san-bao"},
    )

    assert risposta.status_code == 200
    assert risposta.headers["content-type"].startswith("text/html")
    corpo = risposta.text

    assert "@page { size: A6" in corpo
    assert "margin: 8mm" in corpo
    assert re.search(r"<h1[^>]*>Bar interno — Centro di Aggregazione Bozzano</h1>", corpo)
    assert "Via Bozzano 1" in corpo
    assert "lun-ven 08:00-20:00" in corpo
    assert "[KB · Rete delle Case di Quartiere di Brindisi · agg. — · affidabilità 3]" in corpo

    for vietato in ("<input", "<form", "<textarea", "<select", "cittadino", "nome_persona", "telefono"):
        assert vietato not in corpo.lower(), f"il biglietto non deve contenere «{vietato}»"


def test_biglietto_senza_orari_dichiara_la_nota(app_cliente):
    """Un luogo senza orari noti non inventa un orario: dichiara «orari non disponibili» (copertura OSM reale)."""
    luogo = dict(LUOGO_BOZZANO, orari_testo=None)
    client = app_cliente(SessioneFinta(luogo=luogo))

    risposta = client.get(
        f"/v1/u/{ambiente.EMAIL_SANBAO}/biglietto", headers=_intestazioni(), params={"luogo_id": 6}
    )

    assert risposta.status_code == 200
    assert "orari non disponibili" in risposta.text


def test_biglietto_luogo_inesistente_404(app_cliente):
    """Un identificativo che non è in memoria è 404, non un biglietto vuoto."""
    client = app_cliente(SessioneFinta(luogo=None))

    risposta = client.get(f"/v1/u/{ambiente.EMAIL_SANBAO}/biglietto", headers=_intestazioni(), params={"luogo_id": 999999})

    assert risposta.status_code == 404


def test_biglietto_luogo_id_non_numerico_ne_osm_422(app_cliente):
    """`luogo_id` ammette un intero o `osm:<tipo>:<id>`: qualunque altro testo è 422."""
    client = app_cliente(SessioneFinta(luogo=LUOGO_BOZZANO))

    risposta = client.get(
        f"/v1/u/{ambiente.EMAIL_SANBAO}/biglietto", headers=_intestazioni(), params={"luogo_id": "bar-di-bozzano"}
    )

    assert risposta.status_code == 422


@respx.mock
def test_biglietto_accetta_osm_node_e_mostra_badge_esterna(app_cliente):
    """Un POI esterno (`osm:node:<id>`) produce un biglietto con badge `[Esterna …]`, senza scrivere nulla in memoria.

    Overpass è mockato: il test prova la **forma del foglio** per una destinazione esterna (piano §397), non il
    contenuto di OpenStreetMap.
    """
    risposta_overpass = {
        "elements": [
            {
                "type": "node",
                "id": 123456,
                "lat": 40.6321,
                "lon": 17.9451,
                "tags": {
                    "name": "Farmacia Centrale",
                    "amenity": "pharmacy",
                    "addr:street": "Corso Umberto",
                    "addr:housenumber": "12",
                    "opening_hours": "Mo-Fr 08:30-12:30",
                },
            }
        ]
    }
    respx.post(re.compile(r"https://overpass\.openstreetmap\.fr/.*|.*overpass.*")).mock(
        return_value=Response(200, json=risposta_overpass)
    )

    client = app_cliente(SessioneFinta(luogo=None))
    risposta = client.get(
        f"/v1/u/{ambiente.EMAIL_SANBAO}/biglietto",
        headers=_intestazioni(),
        params={"luogo_id": "osm:node:123456"},
    )

    assert risposta.status_code == 200, risposta.text
    corpo = risposta.text
    assert "@page { size: A6" in corpo
    assert "Farmacia Centrale" in corpo
    assert "Corso Umberto 12" in corpo
    assert "[Esterna · OpenStreetMap contributors (ODbL) · consultata " in corpo
    assert "non verificata dalla rete" in corpo
    for vietato in ("<input", "<form", "cittadino", "nome_persona", "telefono"):
        assert vietato not in corpo.lower()


@respx.mock
def test_biglietto_osm_node_non_raggiungibile_404(app_cliente):
    """Se Overpass non risponde per quel nodo, il biglietto non esiste: 404, mai un 500 (§9.1)."""
    import httpx

    respx.post(re.compile(r".*overpass.*")).mock(side_effect=httpx.ConnectError("giù"))

    client = app_cliente(SessioneFinta(luogo=None))
    risposta = client.get(
        f"/v1/u/{ambiente.EMAIL_SANBAO}/biglietto",
        headers=_intestazioni(),
        params={"luogo_id": "osm:node:999999"},
    )

    assert risposta.status_code == 404


# --- `cerca_web` ----------------------------------------------------------------------------------------------


def _risultati_searxng() -> dict[str, Any]:
    """Una risposta di SearXNG con 3 URL in allow-list e 2 fuori, come richiesto dal criterio (2 su 5 → 3 item)."""
    return {
        "query": "CAF Brindisi",
        "results": [
            {
                "title": "Comune di Brindisi — sportello ISEE",
                "url": "https://www.comune.brindisi.it/servizi/isee",
                "content": "Lo sportello ISEE riceve su appuntamento.",
            },
            {
                "title": "Trova il CAF a Brindisi più vicino a te",
                "url": "https://www.paginegialle.it/brindisi/caf",
                "content": "Elenco commerciale di CAF.",
            },
            {
                "title": "INPS — assegno unico",
                "url": "https://www.inps.it/it/it/prestazioni.html",
                "content": "Informazioni sulle prestazioni.",
            },
            {
                "title": "CAF online non ufficiale",
                "url": "https://falso-inps.it.example/caf",
                "content": "Dominio civetta: non deve passare.",
            },
            {
                "title": "Questura di Brindisi",
                "url": "https://questure.poliziadistato.it/Brindisi",
                "content": "Uffici e contatti.",
            },
        ],
    }


@respx.mock
def test_cerca_web_scarta_dominio_fuori_allowlist(app_cliente):
    """Su 5 risultati del motore, 2 fuori allow-list vengono scartati e restano 3 item (criterio B3-SHM-12).

    Fra i due scartati c'è `falso-inps.it.example`, che una verifica per sottostringa («`inps.it` è contenuto
    nell'URL?») lascerebbe passare: il confronto deve essere per host.
    """
    respx.get(re.compile(r".*searxng.*")).mock(return_value=Response(200, json=_risultati_searxng()))

    client = app_cliente(SessioneFinta())
    risposta = client.get(f"/v1/u/{ambiente.EMAIL_SANBAO}/cerca_web", headers=_intestazioni(), params={"q": "CAF Brindisi"})

    assert risposta.status_code == 200, risposta.text
    corpo = risposta.json()
    assert len(corpo["items"]) == 3
    url = {item["url"] for item in corpo["items"]}
    assert url == {
        "https://www.comune.brindisi.it/servizi/isee",
        "https://www.inps.it/it/it/prestazioni.html",
        "https://questure.poliziadistato.it/Brindisi",
    }
    assert "https://www.paginegialle.it/brindisi/caf" not in url
    assert "https://falso-inps.it.example/caf" not in url
    assert corpo["fonti_esterne"][0]["stato"] == "ok"


@respx.mock
def test_cerca_web_ogni_item_porta_badge_provenienza_e_fiducia(app_cliente):
    """V3: nessun item senza etichetta. Ogni risultato dichiara provenienza, fonte, ora, fiducia e badge."""
    respx.get(re.compile(r".*searxng.*")).mock(return_value=Response(200, json=_risultati_searxng()))

    client = app_cliente(SessioneFinta())
    corpo = client.get(
        f"/v1/u/{ambiente.EMAIL_SANBAO}/cerca_web", headers=_intestazioni(), params={"q": "CAF Brindisi"}
    ).json()

    for item in corpo["items"]:
        assert item["provenienza"] == "esterna"
        assert item["fonte"] in {nome for nome, _ in DOMINI_ALLOWLIST.values()}
        assert item["fiducia"] == 3
        assert item["consultato_ts"]
        assert item["badge"].startswith("[Esterna · ")
        assert item["badge"].endswith("non verificata dalla rete]")
        assert item["titolo"] and item["url"]


@respx.mock
def test_cerca_web_tutti_i_risultati_filtrati_200_con_items_vuoti(app_cliente):
    """Quando nessun risultato è in allow-list si risponde 200 con `items: []`: mai un 500, mai un'eccezione.

    È il caso **normale** con l'allow-list reale (5 fonti istituzionali) su query come «CAF Brindisi», i cui primi
    risultati sono commerciali: la risposta corretta è dichiarare che nulla è ammesso, non allentare il filtro.

    La risposta è **conforme al contratto congelato**: `RispostaCercaWeb` ha `additionalProperties: false` con le sole
    proprietà `items` e `fonti_esterne`, quindi l'esito «nessuna fonte ha risposto» del piano viaggia in
    `fonti_esterne[].stato`, non in un campo `nota` (vedi la docstring di `cerca_web`).
    """
    respx.get(re.compile(r".*searxng.*")).mock(
        return_value=Response(
            200,
            json={
                "results": [
                    {"title": "Pagine Gialle", "url": "https://www.paginegialle.it/brindisi/caf", "content": "x"},
                    {"title": "Pagine Bianche", "url": "https://www.paginebianche.it/brindisi", "content": "y"},
                ]
            },
        )
    )

    client = app_cliente(SessioneFinta())
    risposta = client.get(f"/v1/u/{ambiente.EMAIL_SANBAO}/cerca_web", headers=_intestazioni(), params={"q": "CAF Brindisi"})

    assert risposta.status_code == 200
    corpo = risposta.json()
    assert corpo["items"] == []
    assert set(corpo) == {"items", "fonti_esterne"}, "nessun campo fuori dal contratto (additionalProperties: false)"
    assert corpo["fonti_esterne"][0]["fonte"] == "SearXNG"
    assert corpo["fonti_esterne"][0]["stato"] == "ok"
    assert corpo["fonti_esterne"][0]["ms"] >= 0


@respx.mock
def test_cerca_web_motore_non_raggiungibile_200_con_stato_errore(app_cliente):
    """Un motore giù non è un errore dello shim: 200 con `fonti_esterne[0].stato = "errore"` e zero item (§9.1)."""
    import httpx

    respx.get(re.compile(r".*searxng.*")).mock(side_effect=httpx.ConnectError("giù"))

    client = app_cliente(SessioneFinta())
    risposta = client.get(f"/v1/u/{ambiente.EMAIL_SANBAO}/cerca_web", headers=_intestazioni(), params={"q": "turni farmacie"})

    assert risposta.status_code == 200
    assert risposta.json()["items"] == []
    assert risposta.json()["fonti_esterne"][0]["stato"] == "errore"
    assert set(risposta.json()) == {"items", "fonti_esterne"}


@respx.mock
def test_cerca_web_timeout_dichiarato_200(app_cliente):
    """Il timeout è **dichiarato**, non sollevato: `fonti_esterne[0].stato = "timeout"` e risposta 200."""
    import httpx

    respx.get(re.compile(r".*searxng.*")).mock(side_effect=httpx.ReadTimeout("lento"))

    client = app_cliente(SessioneFinta())
    risposta = client.get(f"/v1/u/{ambiente.EMAIL_SANBAO}/cerca_web", headers=_intestazioni(), params={"q": "qualcosa"})

    assert risposta.status_code == 200
    assert risposta.json()["fonti_esterne"][0]["stato"] == "timeout"


@respx.mock
def test_cerca_web_rispetta_max_risultati_esterni(app_cliente):
    """Il tetto `max_risultati_esterni` taglia la risposta, e `max` richiesto può solo abbassarlo."""
    risultati = {
        "results": [
            {
                "title": f"Comune di Brindisi — pagina {indice}",
                "url": f"https://www.comune.brindisi.it/pagina-{indice}",
                "content": "x",
            }
            for indice in range(9)
        ]
    }
    respx.get(re.compile(r".*searxng.*")).mock(return_value=Response(200, json=risultati))

    client = app_cliente(SessioneFinta(parametri_valori={"fiducia_min_esterna": 2, "max_risultati_esterni": 3}))
    corpo = client.get(
        f"/v1/u/{ambiente.EMAIL_SANBAO}/cerca_web", headers=_intestazioni(), params={"q": "ISEE"}
    ).json()
    assert len(corpo["items"]) == 3

    corpo = client.get(
        f"/v1/u/{ambiente.EMAIL_SANBAO}/cerca_web", headers=_intestazioni(), params={"q": "ISEE", "max": 2}
    ).json()
    assert len(corpo["items"]) == 2


@respx.mock
def test_cerca_web_scarta_sotto_la_soglia_di_fiducia(app_cliente):
    """Una fonte attiva ma sotto `fiducia_min_esterna` non entra in risposta: `scartata_fiducia` (§7.2)."""
    respx.get(re.compile(r".*searxng.*")).mock(
        return_value=Response(
            200,
            json={"results": [{"title": "Blog locale", "url": "https://www.comune.brindisi.it/blog", "content": "x"}]},
        )
    )
    # La fonte è in allow-list ma con fiducia 1: sotto la soglia 2 non si usa.
    fonti = [{"fonte": "Blog della Casa", "url": "https://www.comune.brindisi.it", "livello_fiducia": 1, "tecnica": "b"}]

    client = app_cliente(SessioneFinta(fonti_web=fonti))
    risposta = client.get(f"/v1/u/{ambiente.EMAIL_SANBAO}/cerca_web", headers=_intestazioni(), params={"q": "x"})

    assert risposta.status_code == 200
    assert risposta.json()["items"] == []
    assert risposta.json()["fonti_esterne"][0]["stato"] == "scartata_fiducia"


@pytest.mark.parametrize(
    ("url", "ammesso"),
    [
        ("https://www.comune.brindisi.it/x", True),
        ("https://comune.brindisi.it/x", True),
        ("https://sportello.comune.brindisi.it/x", True),
        ("https://falso-inps.it.example/x", False),
        ("https://inps.it.example/x", False),
        ("https://notinps.it/x", False),
        ("https://www.inps.it/x", True),
        ("https://evil.com/?u=https://www.inps.it", False),
    ],
)
def test_in_allowlist_confronta_l_host_non_una_sottostringa(url, ammesso):
    """Il filtro è per host (o sottodominio del dominio autorizzato), mai per sottostringa.

    `notinps.it` contiene `inps.it` come sottostringa ma è un altro dominio; `www.inps.it` è lo stesso host. Una
    verifica con `in` lascerebbe passare i primi due URL civetta, ed è il motivo per cui il confronto è esplicito.
    """
    from app.testi import _in_allowlist

    domini = ("inps.it", "comune.brindisi.it")

    assert _in_allowlist(url, domini) is ammesso


def _schema_risolto(contratto: dict[str, Any], nome: str) -> dict[str, Any]:
    """Lo schema `nome`, con i `$ref` interni sostituiti e `nullable` tradotto per draft7.

    `jsonschema` in modalità draft7 non conosce l'estensione `nullable` di OpenAPI 3.0 e non risolve i riferimenti da
    solo senza un registro: due conversioni minime, scritte qui, valgono più di una dipendenza in più nel progetto.
    """
    def risolvi(nodo: Any) -> Any:
        if isinstance(nodo, dict):
            if "$ref" in nodo:
                cammino = nodo["$ref"].lstrip("#/").split("/")
                bersaglio: Any = contratto
                for parte in cammino:
                    bersaglio = bersaglio[parte]
                return risolvi(bersaglio)
            nodo = dict(nodo)
            if nodo.get("nullable") is True and isinstance(nodo.get("type"), str):
                nodo["type"] = [nodo["type"], "null"]
            return {chiave: risolvi(valore) for chiave, valore in nodo.items()}
        if isinstance(nodo, list):
            return [risolvi(valore) for valore in nodo]
        return nodo

    return risolvi(contratto["components"]["schemas"][nome])


@respx.mock
def test_cerca_web_risposta_conforme_al_contratto(app_cliente):
    """Ogni risposta di `cerca_web` è valida contro lo schema congelato `RispostaCercaWeb`.

    Il test esiste perché il piano (§6) chiede un campo `nota` che il contratto **non ammette**
    (`additionalProperties: false`, proprietà `items` e `fonti_esterne`). Verificare la conformità sulla risposta
    reale, e non solo sulla forma attesa, è ciò che impedisce a quel campo di rientrare per distrazione: la risposta
    è il contratto che Onyx registra come tool `trasi_shim`, e un campo in più la rende invalida.
    """
    pytest.importorskip("jsonschema")
    import yaml
    from jsonschema import Draft7Validator

    contratto = yaml.safe_load(
        (Path(__file__).resolve().parent.parent / "openapi.yaml").read_text(encoding="utf-8")
    )
    validatore = Draft7Validator(_schema_risolto(contratto, "RispostaCercaWeb"))

    respx.get(re.compile(r".*searxng.*")).mock(return_value=Response(200, json=_risultati_searxng()))
    client = app_cliente(SessioneFinta())
    risposte = [
        client.get(f"/v1/u/{ambiente.EMAIL_SANBAO}/cerca_web", headers=_intestazioni(), params={"q": "ISEE"}),
    ]
    # Seconda risposta dal motore: tutti i risultati filtrati (il caso normale con l'allow-list reale).
    respx.get(re.compile(r".*searxng.*")).mock(
        return_value=Response(200, json={"results": [{"title": "x", "url": "https://paginegialle.it/x"}]})
    )
    risposte.append(
        client.get(f"/v1/u/{ambiente.EMAIL_SANBAO}/cerca_web", headers=_intestazioni(), params={"q": "CAF"})
    )

    for risposta in risposte:
        assert risposta.status_code == 200
        errori = [
            f"{'/'.join(str(p) for p in e.path) or '<radice>'}: {e.message}"
            for e in validatore.iter_errors(risposta.json())
        ]
        assert errori == [], errori


# --- `scheda_evento` (area operatore, US-1.3) -----------------------------------------------------------------


def _evento_di_prova(**sovrascritture: Any) -> dict[str, Any]:
    """Una riga di `trasi.evento` con i suoi riferimenti, come la restituisce `SQL_EVENTO`.

    I valori sono quelli di un evento **inserito a mano** (nessun `fonte_id`, quindi nessun
    `fonte_nome`/`fonte_autorita`): è il caso che il badge V3 deve saper dichiarare come «inserito a
    mano», ed è anche lo stato in cui la memoria reale si trova — l'unico evento presente nel seed
    (`Festa di fine estate`, 20/09/2026) non ha fonte.
    """
    riga = {
        "id": 1427,
        "titolo": "Festa di fine estate",
        "descrizione": "Musica e laboratori per il quartiere, ingresso libero.",
        "inizio": datetime(2026, 9, 20, 18, 0, tzinfo=FUSO),
        "fine": datetime(2026, 9, 20, 22, 0, tzinfo=FUSO),
        "luogo_testo": "Cortile della Casa, San Bao",
        "url": None,
        "annullato": False,
        "uid_ical": None,
        "affidabilita": 3,
        "creato_ts": datetime(2026, 9, 16, 17, 26, tzinfo=FUSO),
        "aggiornato_ts": datetime(2026, 9, 16, 17, 26, tzinfo=FUSO),
        "aggiornato_da": "casa_sanbao",
        "fonte_nome": None,
        "fonte_autorita": None,
        "fonte_tipo": None,
        "casa_slug": "san-bao",
        "casa_nome": "San Bao",
        "casa_zona": "La Rosa",
        "casa_ente": "Coop. NauKleros",
        "casa_accesso": "Portierato attivo",
    }
    riga.update(sovrascritture)
    return riga


def _scheda(client: TestClient, evento_id: int = 1427):
    """La chiamata che fa la UI: `home.js` apre `/api/shim/op/scheda_evento?evento_id=…` (Caddy toglie `/api/shim`)."""
    return client.get("/op/scheda_evento", headers=_intestazioni(), params={"evento_id": evento_id})


def test_scheda_evento_html_a5_senza_campi_e_senza_parole_vietate(app_cliente):
    """La scheda è un foglio **A5** senza moduli: gli stessi divieti del biglietto A6, verificati sul documento intero.

    A5 e non A6 perché la scheda porta più contenuto (titolo, periodo, luogo, accesso, descrizione,
    contatto, fonte): su A6 il testo andrebbe a capo a ogni riga. Il formato è quindi un'asserzione del
    test, non un dettaglio di stile — un `@page { size: A6` qui significherebbe che il costruttore del
    biglietto è stato riusato per un contenuto che non gli appartiene.
    """
    client = app_cliente(SessioneFinta(evento=_evento_di_prova()))

    risposta = _scheda(client)

    assert risposta.status_code == 200, risposta.text
    assert risposta.headers["content-type"].startswith("text/html")
    corpo = risposta.text

    assert "@page { size: A5" in corpo
    assert "margin: 8mm" in corpo
    assert re.search(r"<h1[^>]*>Festa di fine estate</h1>", corpo)
    # Gli orari sono quelli **locali** dell'evento: un `strftime` sul timestamp UTC mostrerebbe 16:00.
    assert "domenica 20/09/2026" in corpo
    assert "18:00–22:00" in corpo
    assert "Cortile della Casa, San Bao" in corpo
    assert "Coop. NauKleros" in corpo

    for vietato in ("<input", "<form", "<textarea", "<select", "cittadino", "nome_persona", "telefono"):
        assert vietato not in corpo.lower(), f"la scheda evento non deve contenere «{vietato}»"


def test_scheda_evento_inserito_a_mano_porta_badge_kb_con_la_fonte_dichiarata(app_cliente):
    """Un evento senza `fonte_id` è inserito a mano: il badge lo dichiara invece di tacere (V3).

    La formulazione è quella di `routes_lettura.py` per gli eventi senza fonte esterna: un evento della
    rete non è «non verificato» (sarebbe il badge delle fonti esterne) e non ha una fonte istituzionale
    da citare; dire «inserito a mano» è l'informazione vera, e l'operatore sa da chi andare a verificare.
    """
    client = app_cliente(SessioneFinta(evento=_evento_di_prova()))

    corpo = _scheda(client).text

    assert "[KB · inserito a mano · agg. 16/09/2026 · affidabilità 3]" in corpo
    assert "Fonte: inserito a mano" in corpo
    assert "[Esterna" not in corpo


def test_scheda_evento_da_calendario_esterno_porta_badge_esterna(app_cliente):
    """Un evento con fonte iCal è importato da un calendario: badge `[Esterna …]`, non verificato dalla rete.

    È la distinzione che l'AC di US-1.3 chiede esplicitamente («badge `[KB …]`/`[Esterna …]`»): il
    calendario di una Casa è una fonte esterna come OpenStreetMap, e la rete non l'ha verificata. Se
    questo evento portasse un badge KB, l'operatore lo tratterebbe come memoria verificata.
    """
    evento = _evento_di_prova(
        id=2001,
        uid_ical="festa-2026@san-bao",
        fonte_nome="Google Calendar-ical-2",
        fonte_autorita="Calendari ufficiali delle Case",
        fonte_tipo="ical",
    )
    client = app_cliente(SessioneFinta(evento=evento))

    corpo = _scheda(client, evento["id"]).text

    assert "[Esterna · Calendari ufficiali delle Case · consultata " in corpo
    assert "non verificata dalla rete]" in corpo
    assert "[KB" not in corpo


def test_scheda_evento_inesistente_o_annullato_404(app_cliente):
    """Un evento che non c'è (o è annullato: la query lo esclude) è 404, mai una scheda vuota da appendere."""
    client = app_cliente(SessioneFinta(evento=None))

    risposta = _scheda(client, 999999)

    assert risposta.status_code == 404
    assert "annullato" in risposta.json()["detail"]


def test_scheda_evento_dichiara_la_data_di_aggiornamento_mancante(app_cliente):
    """Se `aggiornato_ts` manca, la scheda **lo dichiara**: non inventa una data (US-1.2, US-1.4).

    È il caso delle righe seminate prima del trigger `scrittura_00_ts`: l'informazione manca davvero, e
    una data plausibile sulla locandina sarebbe la sola affermazione falsa che il foglio potrebbe fare.
    """
    evento = _evento_di_prova(aggiornato_ts=None, aggiornato_da=None, casa_accesso=None)
    client = app_cliente(SessioneFinta(evento=evento))

    corpo = _scheda(client, evento["id"]).text

    assert "data di aggiornamento non disponibile" in corpo
    assert "agg. —" in corpo, "il badge non inventa una data quando non la conosce"
    # Accesso e contatto: quando la memoria non li ha, la scheda lo dice invece di dedurli.
    assert "modalità di accesso non dichiarate nella memoria" in corpo


def test_scheda_evento_oltre_la_mezzanotte_dichiara_il_giorno_di_fine(app_cliente):
    """Un evento che finisce il giorno dopo dichiara **anche la data di fine**: «22:00–02:00» senza data sarebbe falso.

    È il confine del formattatore: dentro lo stesso giorno l'orario di fine basta (`18:00–22:00`), oltre la
    mezzanotte il solo orario farebbe leggere la fine come precedente all'inizio. La scheda è una locandina:
    un orario ambiguo è un errore che l'operatore scopre solo davanti alla persona che ha davanti.
    """
    evento = _evento_di_prova(
        inizio=datetime(2026, 9, 20, 22, 0, tzinfo=FUSO),
        fine=datetime(2026, 9, 21, 2, 0, tzinfo=FUSO),
    )
    client = app_cliente(SessioneFinta(evento=evento))

    corpo = _scheda(client, evento["id"]).text

    assert "domenica 20/09/2026, 22:00 — fino a lunedì 21/09/2026, 02:00" in corpo


def test_scheda_evento_senza_fine_mostra_il_solo_inizio(app_cliente):
    """Un evento senza `fine` (facoltativa nello schema) mostra l'inizio e non un trattino sospeso."""
    evento = _evento_di_prova(fine=None)
    client = app_cliente(SessioneFinta(evento=evento))

    corpo = _scheda(client, evento["id"]).text

    assert "domenica 20/09/2026, 18:00" in corpo
    assert "18:00–" not in corpo


def test_scheda_evento_non_scrive_nulla_sul_dominio(app_cliente):
    """L'endpoint è **read-only**: una sola lettura, e nessuna istruzione di scrittura (V4).

    La verifica è sulle query effettivamente ricevute dalla sessione: è l'unica prova che non dipende da
    una convenzione di lettura del codice, e regge anche se in futuro qualcuno aggiungesse un `execute`
    «innocuo» per timbrare la stampa.
    """
    sessione_finta = SessioneFinta(evento=_evento_di_prova())
    client = app_cliente(sessione_finta)

    assert _scheda(client).status_code == 200

    assert len(sessione_finta.eseguite) == 1, [q for q, _ in sessione_finta.eseguite]
    query, argomenti = sessione_finta.eseguite[0]
    assert "FROM trasi.evento" in query
    assert argomenti == (1427,)
    for scrittura in ("INSERT", "UPDATE", "DELETE"):
        assert scrittura not in query.upper()


def test_scheda_evento_e_fuori_dal_contratto_congelato(app_cliente):
    """La scheda non compare nell'OpenAPI dell'applicazione: quel documento è il contratto con Onyx (gate V-09).

    La scheda la chiama il browser, non il LLM, e `include_in_schema=False` è ciò che la tiene fuori dalle
    nove operazioni congelate. Il test guarda lo schema generato dall'app — non lo YAML, che nessuno tocca
    — perché è da lì che un `include_in_schema` dimenticato farebbe divergere il contratto che Onyx
    registra. L'insieme completo delle `operationId` esposte è già verificato da
    `test_openapi_contract.py`: qui si difende l'assenza di questa, non si ripete quel confronto.
    """
    client = app_cliente(SessioneFinta(evento=_evento_di_prova()))
    client.get("/healthz")

    from app.main import app

    esposte = {
        operazione["operationId"]
        for elemento in app.openapi()["paths"].values()
        for metodo, operazione in elemento.items()
        if metodo in ("get", "post", "put", "patch", "delete")
    }
    assert "op_scheda_evento" not in esposte
    assert not any("/op/" in percorso for percorso in app.openapi()["paths"]), app.openapi()["paths"].keys()


@pytest.mark.live
def test_scheda_evento_sul_database_vero_mostra_l_evento_di_seed(db_vivo):
    """Sul database reale, la scheda dell'evento di seed si genera e dichiara la sua provenienza.

    Il test è `live` perché il valore qui non è la forma del foglio — già provata sopra su un doppio — ma
    la **query** e l'**accesso**: che `SQL_EVENTO` sia eseguibile dal ruolo della Casa (JOIN su `casa` e
    `fonte`, sotto-select su `luogo`), che le colonne esistano con quei nomi e che il filtro `annullato`
    regga. Un errore di SQL si vede solo qui: `column reference "id" is ambiguous` è il difetto tipico di
    questa JOIN, e su un doppio non comparirebbe.

    La sessione è quella **vera**, come negli altri test dell'area operatore: login con le credenziali
    seminate da db/013 e cookie `trasi_sessione` fino a `/op/…`, senza `dependency_overrides`. Sostituire
    la dipendenza renderebbe il test verde anche se l'accesso dell'operatore fosse rotto — cioè
    lascerebbe scoperto proprio il tratto da cui dipende questa pagina.
    """
    if not db_vivo:
        pytest.skip(f"database non raggiungibile ({ambiente.dsn_test()})")
    ambiente.configura_ambiente()

    async def evento_di_seed() -> dict[str, Any] | None:
        """L'evento più recente non annullato della Casa: si legge, non si assume un id."""
        conn = await ambiente.connessione(ruolo="casa_sanbao")
        try:
            riga = await conn.fetchrow(
                """
                SELECT e.id, e.titolo, e.annullato, c.slug AS casa_slug
                  FROM trasi.evento e JOIN trasi.casa c ON c.id = e.casa_id
                 WHERE e.annullato = false AND c.slug = $1
                 ORDER BY e.inizio DESC LIMIT 1
                """,
                ambiente.SLUG_SANBAO,
            )
            return dict(riga) if riga else None
        finally:
            await conn.close()

    evento = asyncio.run(evento_di_seed())
    if evento is None:
        pytest.skip(f"nessun evento per la Casa {ambiente.SLUG_SANBAO}")

    from app.main import crea_app

    # Un solo `TestClient` per test: il pool di connessioni dello shim è globale al processo e vive nel
    # ciclo di eventi del client che l'ha aperto (v. `test_attrezzoteca_op.py`). Il `logout` alla fine
    # revoca il token: la sessione è credenziale, e un test che ne lascia una aperta a ogni esecuzione
    # riempirebbe `trasi.sessione` di righe che nessuno usa.
    with TestClient(crea_app(), raise_server_exceptions=False) as client:
        accesso = client.post(
            "/login",
            json={"casa": ambiente.SLUG_SANBAO, "password": ambiente.SLUG_SANBAO.replace("-", "") + "2026!"},
        )
        assert accesso.status_code == 200, f"login della Casa non riuscito: {accesso.status_code} {accesso.text}"

        try:
            risposta = client.get("/op/scheda_evento", params={"evento_id": evento["id"]})
            # `evento_id` è dichiarato `ge=1`: zero non è un identificativo, ed è un 422 di validazione.
            annullato = client.get("/op/scheda_evento", params={"evento_id": 0})
            inesistente = client.get("/op/scheda_evento", params={"evento_id": 999999})
        finally:
            client.post("/logout")

    assert risposta.status_code == 200, risposta.text
    assert inesistente.status_code == 404
    assert annullato.status_code == 422, "`evento_id` è dichiarato `ge=1`: zero non è un identificativo"

    corpo = risposta.text
    assert "@page { size: A5" in corpo
    assert f"<h1>{evento['titolo']}</h1>" in corpo
    assert "[KB · " in corpo or "[Esterna · " in corpo
    for vietato in ("<input", "<form", "<textarea", "<select", "cittadino", "nome_persona", "telefono"):
        assert vietato not in corpo.lower()
