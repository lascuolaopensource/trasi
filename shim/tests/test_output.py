"""Test degli output: `biglietto`, `oggi`, `cerca_web` (B3-SHM-07/08/12).

SearXNG è **mockato** (`respx`) e il database è sostituito da una sessione finta per i test del contratto: un test
che dipendesse da ciò che il motore restituisce davvero non proverebbe il filtro — proverebbe il motore. Il caso
«tutti i risultati filtrati» è testato esplicitamente perché, con l'allow-list reale (5 fonti istituzionali) e i
risultati commerciali delle query tipiche (`paginegialle.it`, `paginebianche.it`), è il caso **normale**.

Il confronto dei domini è per **host**, non per sottostringa: `falso-inps.it.example` non è autorizzato da `inps.it`.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

import ambiente

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
        fonti_web: list[dict[str, Any]] | None = None,
        parametri_valori: dict[str, Any] | None = None,
    ) -> None:
        self.casa_id = casa_id
        self.ruolo = ruolo
        self.email = ambiente.EMAIL_SANBAO
        self.eseguite: list[tuple[str, tuple[Any, ...]]] = []
        self.riga_oggi = riga_oggi
        self.luogo = luogo
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
        return []

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        self.eseguite.append((sql, args))
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
        return None

    def eseguita(self, sql: str, args: tuple[Any, ...]) -> None:
        self.eseguite.append((sql, args))


@pytest.fixture
def app_cliente(monkeypatch):
    """`TestClient` sull'app reale con la sessione sostituita."""
    ambiente.configura_ambiente()

    from app import main as modulo_main
    from app.db import sessione as dipendenza

    def costruisci(sessione_finta: SessioneFinta) -> TestClient:
        applicazione = modulo_main.crea_app()
        applicazione.dependency_overrides[dipendenza] = lambda: sessione_finta
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
        "testo": "Oggi a San Bao: 2 eventi · 1 scheda in scadenza · 3 proposte",
    }


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
                "SELECT casa_id, slug, eventi, schede_in_scadenza, proposte, testo FROM trasi.v_oggi_casa WHERE slug = $1",
                ambiente.SLUG_SANBAO,
            )
            return dict(riga)
        finally:
            await conn.close()

    atteso = asyncio.run(dalla_vista())
    corpo = risposta.json()
    assert (corpo["casa"], corpo["eventi"], corpo["schede_in_scadenza"], corpo["proposte"], corpo["testo"]) == (
        atteso["slug"],
        atteso["eventi"],
        atteso["schede_in_scadenza"],
        atteso["proposte"],
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
