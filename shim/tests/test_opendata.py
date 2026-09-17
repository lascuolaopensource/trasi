"""`cerca_opendata` e `leggi_dataset`: i cataloghi CKAN in allow-list come strumenti dello shim.

I portali sono **mockati** (`respx`) e il database è un doppio: un test che dipendesse da ciò che dati.puglia.it
restituisce oggi proverebbe il portale, non lo shim. Ciò che si prova è quello che lo shim **decide**: quali portali
interroga (tutti quelli in allow-list, mai Nominatim, mai quelli sotto soglia), come dichiara un portale che non
risponde (200 con `stato`, gli altri rispondono comunque), come etichetta ogni item (V3), come serializza il filtro
del datastore e come rende leggibile un record.

Le forme delle risposte CKAN sono quelle reali verificate dal coordinatore il 16/09/2026 (`package_search` e
`datastore_search` su dati.puglia.it), ridotte ai campi che lo shim legge.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from attese import EMAIL_OP_SANBAO

URL = f"/v1/u/{EMAIL_OP_SANBAO}"

# Le righe `api` del seed (db/011): tre cataloghi CKAN **e** Nominatim, che l'allow-list deve saper separare.
FONTE_PUGLIA = {
    "fonte": "Regione Puglia — Open Data",
    "tecnica": "Open Data Puglia-3",
    "url": "https://dati.puglia.it/ckan",
    "livello_fiducia": 3,
}
FONTE_GOV = {
    "fonte": "dati.gov.it — Catalogo nazionale dei dati aperti (AgID)",
    "tecnica": "dati.gov.it-3",
    "url": "https://www.dati.gov.it/opendata",
    "livello_fiducia": 3,
}
FONTE_IPRES = {
    "fonte": "IPRES — Istituto Pugliese di Ricerche Economiche e Sociali",
    "tecnica": "IPRES Open Data-2",
    "url": "http://www.opendataipres.it",
    "livello_fiducia": 2,
}
FONTE_NOMINATIM = {
    "fonte": "OpenStreetMap contributors (ODbL) — Nominatim",
    "tecnica": "Nominatim-2",
    "url": "https://nominatim.openstreetmap.org",
    "livello_fiducia": 2,
}
FONTI_API = [FONTE_PUGLIA, FONTE_GOV, FONTE_IPRES, FONTE_NOMINATIM]

API_PUGLIA = "https://dati.puglia.it/ckan/api/3/action"
API_GOV = "https://www.dati.gov.it/opendata/api/3/action"
API_IPRES = "http://www.opendataipres.it/api/3/action"
API_NOMINATIM = "https://nominatim.openstreetmap.org"

RISORSA_REGISTRI = "7aa651c7-b536-494e-861e-2adbcf798223"


class SessioneOpenData:
    """Sessione senza database: risponde all'allow-list `api` e ai parametri `[P]` con valori scelti dal test."""

    def __init__(
        self,
        *,
        fonti: list[dict[str, Any]] | None = None,
        fiducia_min: int = 2,
        max_risultati: int = 5,
    ) -> None:
        self.fonti = FONTI_API if fonti is None else fonti
        self.parametri_valori = {"fiducia_min_esterna": fiducia_min, "max_risultati_esterni": max_risultati}
        self.email = EMAIL_OP_SANBAO
        self.ruolo = "casa_sanbao"
        self.casa_id = 5
        self.query: list[str] = []

    async def fetch(self, sql: str, *args: Any) -> list[Any]:
        self.query.append(sql)
        if "FROM trasi.fonte" in sql:
            return self.fonti
        if "FROM trasi.parametro" in sql:
            return [
                {"chiave": chiave, "valore": str(self.parametri_valori[chiave]), "tipo": "int"}
                for chiave in args[0]
                if chiave in self.parametri_valori
            ]
        return []

    async def fetchrow(self, sql: str, *args: Any) -> None:
        self.query.append(sql)
        return None

    async def fetchval(self, sql: str, *args: Any) -> None:
        self.query.append(sql)
        return None


@pytest.fixture
def sessione_opendata():
    """Installa il doppio come dipendenza di sessione dell'app reale, e lo rimuove alla fine."""
    from app import db
    from app.main import app

    def installa(**kwargs) -> SessioneOpenData:
        doppio = SessioneOpenData(**kwargs)
        app.dependency_overrides[db.sessione] = lambda: doppio
        return doppio

    yield installa
    app.dependency_overrides.pop(db.sessione, None)


def _dataset(nome: str, titolo: str, aggiornato: str, *, organizzazione: str = "Regione Puglia", risorse=None) -> dict:
    """Un dataset nella forma di `package_search.result.results[]`."""
    return {
        "name": nome,
        "title": titolo,
        "notes": "Elenco delle strutture. " * 30,
        "metadata_modified": f"{aggiornato}T10:15:00.000000",
        "organization": {"title": organizzazione},
        "resources": risorse
        if risorse is not None
        else [
            {
                "id": RISORSA_REGISTRI,
                "name": "registri2023od.csv",
                "format": "CSV",
                "url": f"https://dati.puglia.it/ckan/dataset/{nome}/resource/{RISORSA_REGISTRI}/download/registri.csv",
                "datastore_active": True,
            },
            {
                "id": "pdf-0001",
                "name": "nota metodologica",
                "format": "PDF",
                "url": f"https://dati.puglia.it/ckan/dataset/{nome}/resource/pdf-0001/download/nota.pdf",
                "datastore_active": False,
            },
        ],
    }


def _package_search(*dataset: dict) -> httpx.Response:
    return httpx.Response(200, json={"success": True, "result": {"count": len(dataset), "results": list(dataset)}})


def _mock_portali(
    puglia: httpx.Response | Exception | None = None,
    gov: httpx.Response | Exception | None = None,
    ipres: httpx.Response | Exception | None = None,
) -> dict[str, respx.Route]:
    """Le tre route `package_search`, ognuna con la risposta (o l'eccezione) scelta dal test."""
    predefinite = {
        "puglia": (API_PUGLIA, puglia or _package_search(_dataset("registri-2023", "Registri regionali 2023", "2026-03-01"))),
        "gov": (API_GOV, gov or _package_search(_dataset("popolazione-brindisi", "Popolazione residente", "2026-08-20"))),
        "ipres": (API_IPRES, ipres or _package_search(_dataset("osservatorio-sociale", "Osservatorio sociale", "2026-09-01"))),
    }
    route = {}
    for chiave, (base, esito) in predefinite.items():
        r = respx.get(f"{base}/package_search")
        if isinstance(esito, Exception):
            r.mock(side_effect=esito)
        else:
            r.mock(return_value=esito)
        route[chiave] = r
    return route


def _parametri(request: httpx.Request) -> dict[str, str]:
    """I parametri della richiesta intercettata, come li ha visti il portale."""
    return {chiave: valori[0] for chiave, valori in parse_qs(request.url.query.decode()).items()}


# --- `cerca_opendata` -----------------------------------------------------------------------------------------


@respx.mock
def test_cerca_opendata_interroga_tutti_i_portali_in_allowlist_e_ordina_per_fiducia(client, sessione_opendata):
    """Tutti i portali CKAN vengono interrogati (non Nominatim), e gli item escono per fiducia decrescente.

    L'ordine fra fonti di pari fiducia è per data di aggiornamento decrescente: dati.gov.it (agosto) prima di Regione
    Puglia (marzo), ed entrambe prima di IPRES (fiducia 2) anche se il suo dataset è il più recente. È V3: prima
    l'autorevolezza, poi la novità.
    """
    sessione_opendata()
    route = _mock_portali()
    nominatim = respx.get(f"{API_NOMINATIM}/search").mock(return_value=httpx.Response(200, json=[]))

    risposta = client.get(f"{URL}/cerca_opendata", params={"q": "strutture sociali Brindisi"})

    assert risposta.status_code == 200, risposta.text
    corpo = risposta.json()
    assert all(r.called for r in route.values()), "ogni portale in allow-list va interrogato"
    assert not nominatim.called, "Nominatim non è un catalogo"

    assert [item["fiducia"] for item in corpo["items"]] == [3, 3, 2]
    assert [item["titolo"] for item in corpo["items"]] == [
        "Popolazione residente",
        "Registri regionali 2023",
        "Osservatorio sociale",
    ]
    assert {voce["fonte"]: voce["stato"] for voce in corpo["fonti_esterne"]} == {
        FONTE_PUGLIA["fonte"]: "ok",
        FONTE_GOV["fonte"]: "ok",
        FONTE_IPRES["fonte"]: "ok",
    }
    # La query e il tetto arrivano al portale così come lo shim li ha decisi.
    parametri = _parametri(route["puglia"].calls.last.request)
    assert parametri == {"q": "strutture sociali Brindisi", "rows": "5"}
    assert route["puglia"].calls.last.request.headers["User-Agent"].startswith("Trasi/")


@respx.mock
def test_cerca_opendata_portale_in_timeout_dichiarato_gli_altri_rispondono(client, sessione_opendata):
    """Un portale in timeout è `stato: timeout` — non un'eccezione — e gli item degli altri ci sono (§9.1)."""
    sessione_opendata()
    _mock_portali(gov=httpx.ConnectTimeout("timeout simulato"))

    risposta = client.get(f"{URL}/cerca_opendata", params={"q": "popolazione"})

    assert risposta.status_code == 200, risposta.text
    corpo = risposta.json()
    stati = {voce["fonte"]: voce["stato"] for voce in corpo["fonti_esterne"]}
    assert stati[FONTE_GOV["fonte"]] == "timeout"
    assert stati[FONTE_PUGLIA["fonte"]] == "ok" and stati[FONTE_IPRES["fonte"]] == "ok"
    assert {item["fonte"] for item in corpo["items"]} == {FONTE_PUGLIA["fonte"], FONTE_IPRES["fonte"]}
    assert all(voce["ms"] >= 0 for voce in corpo["fonti_esterne"])


@respx.mock
def test_cerca_opendata_errore_http_e_risposta_ckan_non_riuscita_sono_errore(client, sessione_opendata):
    """Un 500 del portale e un `success: false` di CKAN sono entrambi `errore`: la fonte non ha dato un dato usabile."""
    sessione_opendata()
    _mock_portali(
        puglia=httpx.Response(500, text="boom"),
        gov=httpx.Response(200, json={"success": False, "error": {"message": "Not found"}}),
    )

    corpo = client.get(f"{URL}/cerca_opendata", params={"q": "x"}).json()

    stati = {voce["fonte"]: voce["stato"] for voce in corpo["fonti_esterne"]}
    assert stati[FONTE_PUGLIA["fonte"]] == "errore"
    assert stati[FONTE_GOV["fonte"]] == "errore"
    assert [item["fonte"] for item in corpo["items"]] == [FONTE_IPRES["fonte"]]


@respx.mock
def test_cerca_opendata_ogni_item_porta_badge_e_risorse_interrogabili(client, sessione_opendata):
    """V3: ogni dataset è etichettato (provenienza, fonte, ora, fiducia, badge) e dice quali risorse si possono leggere.

    `portale` e `risorse[].interrogabile` sono ciò che rende possibile la chiamata successiva a `leggi_dataset`: senza,
    il LLM non saprebbe **quale** risorsa chiedere né **a chi**.
    """
    sessione_opendata()
    _mock_portali()

    corpo = client.get(f"{URL}/cerca_opendata", params={"q": "registri"}).json()

    assert corpo["items"], "attesi item"
    for item in corpo["items"]:
        assert item["provenienza"] == "esterna"
        assert item["badge"].startswith(f"[Esterna · {item['fonte']} · consultata ")
        assert item["badge"].endswith("· non verificata dalla rete]")
        assert item["consultato_ts"] and 1 <= item["fiducia"] <= 3
        assert item["aggiornato"] and len(item["aggiornato"]) == 10, "solo la data, non l'ora"
        assert len(item["descrizione"]) <= 300

    puglia = next(item for item in corpo["items"] if item["fonte"] == FONTE_PUGLIA["fonte"])
    assert puglia["portale"] == "dati.puglia.it"
    assert puglia["url"] == "https://dati.puglia.it/ckan/dataset/registri-2023"
    assert puglia["organizzazione"] == "Regione Puglia"
    assert [(r["id"], r["formato"], r["interrogabile"]) for r in puglia["risorse"]] == [
        (RISORSA_REGISTRI, "CSV", True),
        ("pdf-0001", "PDF", False),
    ]
    gov = next(item for item in corpo["items"] if item["fonte"] == FONTE_GOV["fonte"])
    assert gov["portale"] == "dati.gov.it", "il `www.` non è un altro host"


@respx.mock
def test_cerca_opendata_portale_sotto_soglia_non_interrogato_e_dichiarato(client, sessione_opendata):
    """Sotto `fiducia_min_esterna` il portale **non si chiama** e compare come `scartata_fiducia` (§7.2)."""
    sessione_opendata(fiducia_min=3)
    route = _mock_portali()

    corpo = client.get(f"{URL}/cerca_opendata", params={"q": "osservatorio"}).json()

    assert not route["ipres"].called, "interrogare per poi scartare costerebbe il timeout per nulla"
    stati = {voce["fonte"]: voce for voce in corpo["fonti_esterne"]}
    assert stati[FONTE_IPRES["fonte"]] == {"fonte": FONTE_IPRES["fonte"], "stato": "scartata_fiducia", "ms": 0}
    assert all(item["fiducia"] >= 3 for item in corpo["items"])


@respx.mock
def test_cerca_opendata_scarta_dataset_senza_nome_e_risorse_senza_url(client, sessione_opendata):
    """Un dataset senza `name` non ha una pagina da citare, una risorsa senza `url` non è né leggibile né scaricabile.

    Tenerli produrrebbe `…/dataset/None` o una risorsa che il LLM proporrebbe di aprire senza un indirizzo: si
    scartano in silenzio, perché non sono dati ma buchi nei metadati del portale.
    """
    sessione_opendata(fonti=[FONTE_PUGLIA])
    _mock_portali(
        puglia=_package_search(
            {"title": "Senza nome", "resources": []},
            _dataset(
                "con-nome",
                "Con nome",
                "2026-01-01",
                risorse=[
                    {"id": "r1", "name": "senza url", "format": "CSV", "datastore_active": True},
                    {"id": "r2", "url": "https://dati.puglia.it/x.csv", "datastore_active": False},
                ],
            ),
        )
    )

    corpo = client.get(f"{URL}/cerca_opendata", params={"q": "x"}).json()

    assert [item["titolo"] for item in corpo["items"]] == ["Con nome"]
    assert corpo["items"][0]["risorse"] == [
        {"id": "r2", "nome": None, "formato": None, "url": "https://dati.puglia.it/x.csv", "interrogabile": False}
    ]


@respx.mock
def test_cerca_opendata_applica_il_tetto_max_e_max_risultati_esterni(client, sessione_opendata):
    """Il tetto è il minore fra `max` richiesto e `max_risultati_esterni`, ed è anche il `rows` chiesto ai portali."""
    sessione_opendata(max_risultati=5)
    route = _mock_portali(
        puglia=_package_search(*(_dataset(f"d{i}", f"Dataset {i}", f"2026-01-{i + 1:02d}") for i in range(4)))
    )

    corpo = client.get(f"{URL}/cerca_opendata", params={"q": "x", "max": 2}).json()

    assert len(corpo["items"]) == 2
    assert _parametri(route["puglia"].calls.last.request)["rows"] == "2"


@respx.mock
def test_cerca_opendata_senza_portali_in_allowlist_risponde_vuoto_senza_chiamate(client, sessione_opendata):
    """Solo Nominatim in allow-list: nessun catalogo, quindi `items: []`, `fonti_esterne: []` e nessuna richiesta."""
    sessione_opendata(fonti=[FONTE_NOMINATIM])
    route = _mock_portali()

    corpo = client.get(f"{URL}/cerca_opendata", params={"q": "x"}).json()

    assert corpo == {"items": [], "fonti_esterne": []}
    assert not any(r.called for r in route.values())


def test_cerca_opendata_senza_q_422(client, sessione_opendata):
    """`q` è obbligatoria e non vuota: la sua assenza è un parametro non ammesso, con l'involucro `detail`."""
    sessione_opendata()

    risposta = client.get(f"{URL}/cerca_opendata")

    assert risposta.status_code == 422
    assert isinstance(risposta.json()["detail"], str)


# --- `leggi_dataset` ------------------------------------------------------------------------------------------


RECORD_STRUTTURA = {
    "_id": 17,
    "REGISTRO": "Strutture",
    "ARTICOLO": "Art. 60",
    "TIPOLOGIA": "Centro diurno per anziani",
    "DENOMINAZIONE_TITOLARE": "Cooperativa di prova",
    "DENOMINAZIONE_SEDE_OP": "Centro Il Faro",
    "INDIRIZZO_SEDE_OP": "Via Appia 120",
    "COMUNE_SEDE_OP": "Brindisi",
    "COGNOME_LEGALE": "Rossi",
    "NOME_LEGALE": "Maria",
    "CANCELLATO": "NO",
    "NOTE": "",
    "rank": 0.0573,
    "_full_text": "'anziani':3 'brindisi':7",
}
RECORD_SENZA_NOME = {"_id": 18, "REGISTRO": "Servizi", "COMUNE_SEDE_OP": "Brindisi", "rank": 0.01}


def _datastore_search(*records: dict, totale: int = 95) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "success": True,
            "result": {
                "resource_id": RISORSA_REGISTRI,
                "fields": [{"id": chiave, "type": "text"} for chiave in RECORD_STRUTTURA],
                "records": list(records),
                "total": totale,
            },
        },
    )


@respx.mock
def test_leggi_dataset_filtro_campo_valore_e_record_in_testo(client, sessione_opendata):
    """Il filtro esatto arriva al datastore come `filters` JSON; ogni record diventa `titolo` + `testo` leggibile.

    Il `testo` esclude `_id`, `rank` e `_full_text` (sono il motore, non il dato), i campi vuoti e — V5 — le colonne
    del legale rappresentante (`COGNOME_LEGALE`, `NOME_LEGALE`), che i registri regionali portano davvero; il
    `titolo` è la denominazione della sede quando c'è, altrimenti `record <_id>` — così un record senza nome resta
    citabile.
    """
    sessione_opendata()
    route = respx.get(f"{API_PUGLIA}/datastore_search").mock(
        return_value=_datastore_search(RECORD_STRUTTURA, RECORD_SENZA_NOME)
    )

    risposta = client.get(
        f"{URL}/leggi_dataset",
        params={"risorsa_id": RISORSA_REGISTRI, "portale": "dati.puglia.it", "campo": "COMUNE_SEDE_OP", "valore": "Brindisi"},
    )

    assert risposta.status_code == 200, risposta.text
    parametri = _parametri(route.calls.last.request)
    assert parametri["resource_id"] == RISORSA_REGISTRI
    assert json.loads(parametri["filters"]) == {"COMUNE_SEDE_OP": "Brindisi"}
    assert parametri["limit"] == "5"
    assert "q" not in parametri

    corpo = risposta.json()
    assert corpo["totale"] == 95
    assert corpo["fonti_esterne"] == [{"fonte": FONTE_PUGLIA["fonte"], "stato": "ok", "ms": corpo["fonti_esterne"][0]["ms"]}]

    struttura, senza_nome = corpo["items"]
    assert struttura["titolo"] == "Centro Il Faro"
    assert struttura["testo"].startswith("REGISTRO: Strutture · ARTICOLO: Art. 60 · ")
    assert "COMUNE_SEDE_OP: Brindisi" in struttura["testo"]
    for escluso in ("_id", "rank", "_full_text", "NOTE", "COGNOME_LEGALE", "NOME_LEGALE", "Rossi", "Maria"):
        assert escluso not in struttura["testo"], f"{escluso} non deve comparire nel testo"
    assert struttura["provenienza"] == "esterna" and struttura["fiducia"] == 3
    assert struttura["badge"].startswith(f"[Esterna · {FONTE_PUGLIA['fonte']} · consultata ")

    assert senza_nome["titolo"] == "record 18"
    assert senza_nome["testo"] == "REGISTRO: Servizi · COMUNE_SEDE_OP: Brindisi"


@respx.mock
def test_leggi_dataset_con_q_usa_la_ricerca_libera_e_il_max_richiesto(client, sessione_opendata):
    """`q` va al datastore come ricerca full-text, `max` come `limit` (mai oltre 50), senza `filters`."""
    sessione_opendata()
    route = respx.get(f"{API_PUGLIA}/datastore_search").mock(return_value=_datastore_search(RECORD_STRUTTURA))

    risposta = client.get(
        f"{URL}/leggi_dataset", params={"risorsa_id": RISORSA_REGISTRI, "portale": "dati.puglia.it", "q": "anziani", "max": 20}
    )

    assert risposta.status_code == 200, risposta.text
    parametri = _parametri(route.calls.last.request)
    assert parametri["q"] == "anziani" and parametri["limit"] == "20"
    assert "filters" not in parametri


@pytest.mark.parametrize(
    ("parametri", "frammento"),
    [
        pytest.param({}, "indicare q oppure campo e valore", id="nessun_criterio"),
        pytest.param({"campo": "COMUNE_SEDE_OP"}, "campo e valore vanno indicati insieme", id="campo_senza_valore"),
        pytest.param({"valore": "Brindisi"}, "campo e valore vanno indicati insieme", id="valore_senza_campo"),
    ],
)
@respx.mock
def test_leggi_dataset_senza_q_ne_filtro_422(client, sessione_opendata, parametri, frammento):
    """Senza criterio (o con mezzo filtro) la lettura è 422 **prima** di chiamare il portale: non è una ricerca."""
    sessione_opendata()
    route = respx.get(f"{API_PUGLIA}/datastore_search").mock(return_value=_datastore_search())

    risposta = client.get(f"{URL}/leggi_dataset", params={"risorsa_id": RISORSA_REGISTRI, **parametri})

    assert risposta.status_code == 422
    assert frammento in risposta.json()["detail"]
    assert not route.called


@respx.mock
def test_leggi_dataset_portale_fuori_allowlist_422(client, sessione_opendata):
    """Un `portale` non in allow-list è 422 e il messaggio elenca gli host ammessi, così il LLM può correggersi."""
    sessione_opendata()

    risposta = client.get(
        f"{URL}/leggi_dataset", params={"risorsa_id": RISORSA_REGISTRI, "portale": "dati.comune.altrove.it", "q": "x"}
    )

    assert risposta.status_code == 422
    dettaglio = risposta.json()["detail"]
    for host in ("dati.puglia.it", "dati.gov.it", "opendataipres.it"):
        assert host in dettaglio, f"il 422 deve elencare i portali ammessi, manca «{host}»"
    assert "nominatim" not in dettaglio


@respx.mock
def test_leggi_dataset_senza_portale_usa_il_piu_fidato_e_accetta_l_host_anche_come_url(client, sessione_opendata):
    """Senza `portale` si interroga un portale di fiducia massima; `portale` come URL (`https://www.…`) è lo stesso host."""
    sessione_opendata()
    puglia = respx.get(f"{API_PUGLIA}/datastore_search").mock(return_value=_datastore_search())
    gov = respx.get(f"{API_GOV}/datastore_search").mock(return_value=_datastore_search())
    ipres = respx.get(f"{API_IPRES}/datastore_search").mock(return_value=_datastore_search())

    assert client.get(f"{URL}/leggi_dataset", params={"risorsa_id": "r", "q": "x"}).status_code == 200
    assert (puglia.called or gov.called) and not ipres.called

    risposta = client.get(
        f"{URL}/leggi_dataset", params={"risorsa_id": "r", "q": "x", "portale": "https://www.opendataipres.it/"}
    )
    assert risposta.status_code == 200
    assert ipres.called


@respx.mock
def test_leggi_dataset_portale_in_timeout_200_dichiarato(client, sessione_opendata):
    """Il portale che non risponde è `stato: timeout`, `items: []`, `totale: null` — mai un 5xx (§9.1)."""
    sessione_opendata()
    respx.get(f"{API_PUGLIA}/datastore_search").mock(side_effect=httpx.ReadTimeout("lento"))

    risposta = client.get(
        f"{URL}/leggi_dataset", params={"risorsa_id": RISORSA_REGISTRI, "portale": "dati.puglia.it", "q": "x"}
    )

    assert risposta.status_code == 200, risposta.text
    corpo = risposta.json()
    assert corpo["items"] == [] and corpo["totale"] is None
    assert corpo["fonti_esterne"][0]["fonte"] == FONTE_PUGLIA["fonte"]
    assert corpo["fonti_esterne"][0]["stato"] == "timeout"


@respx.mock
def test_leggi_dataset_portale_sotto_soglia_non_interrogato(client, sessione_opendata):
    """Un portale richiesto ma sotto `fiducia_min_esterna` non si chiama: `scartata_fiducia`, senza record."""
    sessione_opendata(fiducia_min=3)
    route = respx.get(f"{API_IPRES}/datastore_search").mock(return_value=_datastore_search(RECORD_STRUTTURA))

    corpo = client.get(
        f"{URL}/leggi_dataset", params={"risorsa_id": "r", "portale": "opendataipres.it", "q": "x"}
    ).json()

    assert not route.called
    assert corpo["items"] == []
    assert corpo["fonti_esterne"] == [{"fonte": FONTE_IPRES["fonte"], "stato": "scartata_fiducia", "ms": 0}]


# --- Live (portali veri): saltati senza rete o su richiesta -----------------------------------------------------


@pytest.mark.live
def test_live_cerca_opendata_su_dati_puglia_restituisce_dataset_con_risorse(client, sessione_opendata):
    """Con il portale vero, «strutture» su dati.puglia.it trova almeno un dataset con una risorsa interrogabile.

    Verificato dal coordinatore il 16/09/2026 con `curl`; il test conferma che la forma reale di `package_search` è
    quella che lo shim legge. Si salta se la rete non c'è: un portale giù non è un difetto dello shim.
    """
    import socket

    try:
        socket.create_connection(("dati.puglia.it", 443), timeout=3).close()
    except OSError:
        pytest.skip("dati.puglia.it non raggiungibile")

    sessione_opendata(fonti=[FONTE_PUGLIA])
    corpo = client.get(f"{URL}/cerca_opendata", params={"q": "strutture", "max": 3}).json()

    stato = corpo["fonti_esterne"][0]["stato"]
    if stato != "ok":
        pytest.skip(f"dati.puglia.it ha risposto {stato}")
    assert corpo["items"]
    assert any(r["interrogabile"] for item in corpo["items"] for r in item["risorse"])
