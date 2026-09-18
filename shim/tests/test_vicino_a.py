"""`vicino_a`: l'unione di memoria della rete e OpenStreetMap (B3-SHM-03/04).

I test sono divisi in due famiglie, e la divisione è deliberata:

- **deterministici** (nessun database, nessuna rete): usano un doppio della sessione e `respx` per Overpass. Sono
  quelli che provano il *comportamento* — ordinamento, timeout dichiarato, scarto per fiducia, tetto ai risultati,
  tipo fuori vocabolario, badge su ogni item — perché ogni esito è costruito dal test.
- **live** (database vero, Overpass vero): provano che le **query** dicano davvero quello che i test deterministici
  assumono, e che i POI esterni arrivino con lo User-Agent identificativo. Si saltano se lo stack non è acceso.

La copertura OSM è il vincolo che dà forma a tutto: 0 bar entro 800 m da San Bao (misurato su OSM il 15/09), quindi
il criterio «≥1 item esterno» non è verificabile con un raggio urbano su quella Casa — i test lo provano dove i POI
ci sono davvero (Bozzano, Santa Spazio) o con un raggio esplicito più ampio, e il caso San Bao verifica il resto.
"""

import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from attese import EMAIL_OP_SANBAO, EMAIL_OP_BOZZANO, TIPI_VICINO_A
from conftest import _valore_da_env_file

URL = "/v1/u/{email}"
FUSO_LOCALE = ZoneInfo("Europe/Rome")


def _dsn_admin() -> str:
    """Il DSN amministrativo per le fixture dei test che devono cambiare lo stato del database.

    La password viene da `deployment/.env` (`POSTGRES_PASSWORD`), la stessa sorgente del compose: nessun segreto nel
    codice. Ogni test che la usa ripristina lo stato iniziale.
    """
    return (
        f"postgresql://postgres:{_valore_da_env_file('POSTGRES_PASSWORD')}@127.0.0.1:5432/"
        f"{_valore_da_env_file('TRASI_DB') or 'trasi_db'}"
    )


# L'indirizzo interrogato davvero in produzione: la fixture di `respx` deve intercettare **questo**, altrimenti il
# test non proverebbe il percorso reale.
ENDPOINT_OVERPASS = "https://overpass.openstreetmap.fr/api/interpreter"
NOME_FONTE_OSM = "OpenStreetMap contributors (ODbL)"

# Un bar vicino a San Bao, con orari OSM. I numeri sono quelli della risposta Overpass reale.
BAR_APERTO = {
    "type": "node",
    "id": 111111,
    "lat": 40.60650,
    "lon": 17.95250,
    "tags": {"amenity": "bar", "name": "Bar di prova aperto", "opening_hours": "24/7"},
}
BAR_SENZA_ORARI = {
    "type": "node",
    "id": 222222,
    "lat": 40.60700,
    "lon": 17.95200,
    "tags": {"amenity": "bar", "name": "Bar di prova senza orari"},
}
BAR_CHIUSO = {
    "type": "node",
    "id": 333333,
    "lat": 40.60620,
    "lon": 17.95160,
    "tags": {
        "amenity": "bar",
        "name": "Bar di prova chiuso",
        # Chiuso in ogni istante: `is_open` è sempre falso, quindi la fonte è certa della chiusura.
        "opening_hours": "Mo-Su 00:00-00:01",
    },
}


def _risposta_overpass(elementi: list[dict]) -> httpx.Response:
    """La risposta di Overpass nella forma reale (`{"elements": [...]}`)."""
    return httpx.Response(200, json={"version": 0.6, "elements": elementi})


def _vicino_a(client, query: str, email: str = EMAIL_OP_SANBAO):
    return client.get(f"{URL.format(email=email)}/vicino_a?{query}")


# --- Deterministici -------------------------------------------------------------------------------------------


def test_vicino_a_tipo_non_supportato_422(client, sessione_finta):
    """Un tipo fuori dal vocabolario chiuso è 422 e il messaggio elenca quelli ammessi.

    `tipo` diventa una query OpenStreetMap: un valore ignoto non è traducibile, e restituire una lista vuota farebbe
    credere all'assistente che non esiste nulla — che è peggio di un errore dichiarato.
    """
    sessione_finta()
    risposta = _vicino_a(client, "casa=san-bao&tipo=discoteca")

    assert risposta.status_code == 422
    dettaglio = risposta.json()["detail"]
    for tipo in TIPI_VICINO_A:
        assert tipo in dettaglio, f"il 422 deve elencare i tipi ammessi, manca «{tipo}»"


def test_vicino_a_senza_tipo_422(client, sessione_finta):
    """`tipo` è obbligatorio nel contratto: la sua assenza è un parametro non ammesso."""
    sessione_finta()
    risposta = _vicino_a(client, "casa=san-bao")

    assert risposta.status_code == 422


@pytest.mark.live
def test_vicino_a_casa_inesistente_ricade_sull_identita(client, db_vivo):
    """Una Casa che non esiste non fa fallire la chiamata se l'operatore ha una Casa propria.

    Il comportamento è cambiato il 2026-09-16 dopo aver visto il difetto **nel percorso
    end-to-end**: il modello, vedendo `casa` nel contratto, tende a riempirlo e ci mette il nome
    della Casa o il nome dell'applicazione («Trasi»), non lo slug. Con la semantica precedente
    (422) l'assistente rispondeva «la rete non riconosce nessuna Casa con questo nome»: dichiarava
    un guasto inesistente al posto di rispondere.

    Ora vince l'identità — il dato che il sistema conosce con certezza — e la risposta è 200.
    Per un ruolo **senza** Casa (es. `rete`) resta invece il 422: lì la Casa serve davvero e non
    è deducibile (v. `test_vicino_a_rete_senza_casa_422`).
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    risposta = _vicino_a(client, "casa=casa-che-non-esiste&tipo=bar")

    assert risposta.status_code == 200, (
        "uno slug inesistente non deve rompere la chiamata quando l'operatore ha una Casa"
    )
    # E la Casa usata è quella dell'identità, non lo slug inventato.
    assert risposta.json()["casa"] != "casa-che-non-esiste"


@pytest.mark.live
def test_vicino_a_raggio_negativo_422(client, db_vivo):
    """Un raggio non positivo è un parametro non ammesso (il contratto dichiara `minimum: 1`)."""
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    assert _vicino_a(client, "casa=san-bao&tipo=bar&raggio_m=0").status_code == 422


@pytest.mark.live
@respx.mock
def test_vicino_a_overpass_timeout_fallback_dichiarato(client, db_vivo):
    """Il timeout di Overpass è **dichiarato**, non un'eccezione: 200, stato `timeout`, soli item KB.

    È il criterio di done di B3-SHM-04 e la regola §9.1: il guasto di una fonte esterna si legge in
    `fonti_esterne[].stato`. Il test simula un timeout di rete, non una risposta: è il caso peggiore, quello in cui
    una `httpx` eccezione arriverebbe al chiamante se non fosse gestita.
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    respx.post(ENDPOINT_OVERPASS).mock(side_effect=httpx.ConnectTimeout("timeout simulato"))

    risposta = _vicino_a(client, "casa=san-bao&tipo=bar")

    assert risposta.status_code == 200
    corpo = risposta.json()
    assert corpo["fonti_esterne"][0]["stato"] == "timeout"
    assert corpo["fonti_esterne"][0]["ms"] >= 0
    assert all(item["provenienza"] == "kb" for item in corpo["items"]), "in timeout restano solo i dati in memoria"
    assert corpo["items"], "la memoria della rete deve comunque rispondere"


@pytest.mark.live
@respx.mock
def test_vicino_a_overpass_errore_http_dichiarato(client, db_vivo):
    """Un errore HTTP di Overpass (es. 500) è `stato="errore"`, non un 5xx dello shim."""
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    respx.post(ENDPOINT_OVERPASS).mock(return_value=httpx.Response(500, text="boom"))

    risposta = _vicino_a(client, "casa=san-bao&tipo=bar")

    assert risposta.status_code == 200
    assert risposta.json()["fonti_esterne"][0]["stato"] == "errore"


@pytest.mark.live
@respx.mock
def test_vicino_a_overpass_con_user_agent_generico_403_diventa_errore_dichiarato(client, db_vivo):
    """Overpass risponde 403 a uno User-Agent generico: lo shim lo dichiara come `errore`, senza eccezioni.

    Il test **non** prova che lo shim sbaglia lo UA (lo prova il test live con Overpass vero): prova che se Overpass
    rifiuta — comunque vada — il chiamante riceve 200 con lo stato, non un 500.
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    respx.post(ENDPOINT_OVERPASS).mock(
        return_value=httpx.Response(403, text="This service is only available to white-listed usages")
    )

    risposta = _vicino_a(client, "casa=san-bao&tipo=bar")

    assert risposta.status_code == 200
    assert risposta.json()["fonti_esterne"][0]["stato"] == "errore"


@pytest.mark.live
@respx.mock
def test_vicino_a_ordina_kb_prima_di_esterna_e_aperti_prima_dei_senza_orari(client, db_vivo):
    """L'ordinamento del contratto: KB prima, poi `aperto_adesso` `true` → `null` → `false`, poi distanza.

    Il test costruisce le tre categorie contemporaneamente, così la verifica non dipende da quali POI esistono su OSM
    in questo momento.
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    respx.post(ENDPOINT_OVERPASS).mock(
        return_value=_risposta_overpass([BAR_SENZA_ORARI, BAR_CHIUSO, BAR_APERTO])
    )

    corpo = _vicino_a(client, "casa=san-bao&tipo=bar&raggio_m=3000").json()
    items = corpo["items"]

    provenienze = [item["provenienza"] for item in items]
    assert provenienze == sorted(provenienze, key=lambda p: 0 if p == "kb" else 1), "prima la memoria della rete"

    esterni = [item for item in items if item["provenienza"] == "esterna"]
    assert esterni, "attesi item esterni"
    ranghi = [0 if item["aperto_adesso"] is True else 1 if item["aperto_adesso"] is None else 2 for item in esterni]
    assert ranghi == sorted(ranghi), f"aperti → senza orari → chiusi, trovato {ranghi}"
    assert esterni[0]["nome"] == BAR_APERTO["tags"]["name"]

    # La distanza ordina **dentro** il gruppo di apertura: si verifica per gruppo, non sulla lista intera (un bar
    # chiuso più vicino viene dopo uno aperto più lontano, ed è il comportamento dichiarato).
    for rango in set(ranghi):
        distanze = [item["distanza_m"] for item, r in zip(esterni, ranghi) if r == rango]
        assert distanze == sorted(distanze), f"gruppo {rango}: la distanza deve ordinare, trovato {distanze}"


@pytest.mark.live
@respx.mock
def test_vicino_a_ogni_item_porta_badge_e_provenienza(client, db_vivo):
    """V3 su `vicino_a`: **nessun** item senza badge, e il badge distingue KB da Esterna.

    Il test scorre tutti gli item, non solo il primo: l'invariante è che *nessuna* riga resti senza etichetta, ed è
    esattamente il caso che il piano verifica («mai un item senza etichetta»).
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    respx.post(ENDPOINT_OVERPASS).mock(return_value=_risposta_overpass([BAR_APERTO, BAR_SENZA_ORARI]))

    corpo = _vicino_a(client, "casa=san-bao&tipo=bar&raggio_m=3000").json()

    assert corpo["items"], "attesi item"
    for item in corpo["items"]:
        assert item["badge"], f"item senza badge: {item['nome']}"
        assert item["consultato_ts"]
        if item["provenienza"] == "kb":
            assert item["badge"].startswith("[KB · ")
        else:
            assert item["badge"].startswith("[Esterna · ")
            assert item["badge"].endswith("· non verificata dalla rete]")
            assert item["fonte"] == NOME_FONTE_OSM

    esterni = [item for item in corpo["items"] if item["provenienza"] == "esterna"]
    assert esterni, "attesi item esterni"
    assert all(item["url"].startswith("https://www.openstreetmap.org/") for item in esterni)


@pytest.mark.live
@respx.mock
def test_vicino_a_aperto_adesso_true_tiene_i_poi_senza_orari_ma_esclude_i_chiusi(client, db_vivo):
    """Con `aperto_adesso=true` i POI senza orari **restano** con `null` + `orari_nota`; i chiusi noti escono.

    È il cuore della mitigazione del rischio §13: la copertura `opening_hours` su OSM è del 7.7%, quindi scartare i
    POI senza orari nasconderebbe il 92% dei luoghi reali. Il test verifica le tre categorie in una sola risposta.
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    respx.post(ENDPOINT_OVERPASS).mock(
        return_value=_risposta_overpass([BAR_APERTO, BAR_SENZA_ORARI, BAR_CHIUSO])
    )

    corpo = _vicino_a(client, "casa=san-bao&tipo=bar&raggio_m=3000&aperto_adesso=true").json()
    per_nome = {item["nome"]: item for item in corpo["items"]}

    assert BAR_APERTO["tags"]["name"] in per_nome, "un POI aperto deve restare"
    assert BAR_SENZA_ORARI["tags"]["name"] in per_nome, "un POI senza orari non va mai scartato"
    assert BAR_CHIUSO["tags"]["name"] not in per_nome, "un POI noto come chiuso esce"

    senza_orari = per_nome[BAR_SENZA_ORARI["tags"]["name"]]
    assert senza_orari["aperto_adesso"] is None
    assert senza_orari["orari_nota"] == "orari non disponibili"
    assert senza_orari["orari_testo"] is None

    # E nella lista i senza orari vengono **dopo** gli aperti noti, come dichiara il contratto.
    nomi_esterni = [item["nome"] for item in corpo["items"] if item["provenienza"] == "esterna"]
    assert nomi_esterni.index(BAR_APERTO["tags"]["name"]) < nomi_esterni.index(
        BAR_SENZA_ORARI["tags"]["name"]
    )


@pytest.mark.live
@respx.mock
def test_vicino_a_senza_aperto_adesso_include_anche_i_chiusi(client, db_vivo):
    """Senza `aperto_adesso` i chiusi restano: l'operatore vuole sapere che il bar c'è ma è chiuso."""
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    respx.post(ENDPOINT_OVERPASS).mock(return_value=_risposta_overpass([BAR_CHIUSO]))

    corpo = _vicino_a(client, "casa=san-bao&tipo=bar&raggio_m=3000").json()
    per_nome = {item["nome"]: item for item in corpo["items"]}

    assert BAR_CHIUSO["tags"]["name"] in per_nome
    assert per_nome[BAR_CHIUSO["tags"]["name"]]["aperto_adesso"] is False


@pytest.mark.live
@respx.mock
def test_vicino_a_chiama_overpass_con_user_agent_identificativo(client, db_vivo):
    """La richiesta uscente porta lo User-Agent identificativo: senza, Overpass risponde 403 (verificato in B0).

    Il test ispeziona l'**intestazione della richiesta intercettata**: è l'unica prova diretta che il vincolo sia
    rispettato, e vale più di un test che si limita a contare gli item.
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    route = respx.post(ENDPOINT_OVERPASS).mock(return_value=_risposta_overpass([]))

    _vicino_a(client, "casa=san-bao&tipo=bar")

    assert route.called, "Overpass deve essere interrogato"
    intestazioni = route.calls.last.request.headers
    user_agent = intestazioni.get("user-agent", "")
    assert user_agent, "la richiesta a Overpass deve portare uno User-Agent"
    assert "python" not in user_agent.lower(), f"User-Agent generico = 403 su Overpass, trovato «{user_agent}»"
    assert "Trasi" in user_agent, f"lo User-Agent deve identificare lo shim, trovato «{user_agent}»"


@pytest.mark.live
@respx.mock
def test_vicino_a_query_overpass_usa_i_tag_del_vocabolario(client, db_vivo):
    """La query Overpass traduce il tipo nei tag OSM attesi, e usa `nwr` (non solo i nodi) con `around`.

    Una query che chiedesse solo `node` perderebbe i POI mappati come area: è il modo silenzioso in cui la copertura
    si dimezza senza che nessuno se ne accorga.
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    route = respx.post(ENDPOINT_OVERPASS).mock(return_value=_risposta_overpass([]))

    _vicino_a(client, "casa=san-bao&tipo=farmacia")

    query = route.calls.last.request.content.decode("utf-8")
    assert 'nwr["amenity"="pharmacy"]' in query
    assert "around:" in query


# --- Fiducia, tetto, parametri [P] ---------------------------------------------------------------------------


@pytest.fixture
def parametro_esterno(monkeypatch):
    """Sostituisce i parametri [P] letti dalla sessione, senza toccare il database.

    Il parametro è la leva con cui il TI decide quanto fidarsi delle fonti esterne e quanti risultati mostrarne: i
    test dei due comportamenti devono poterli cambiare **senza** mutare il database condiviso con gli altri worker.
    """
    from app import routes_geo

    def applica(chiave: str, valore):
        originale = routes_geo.parametro_int

        def finto(valori, chiave_letta, default):
            return valore if chiave_letta == chiave else originale(valori, chiave_letta, default)

        monkeypatch.setattr(routes_geo, "parametro_int", finto)

    return applica


@pytest.mark.live
@respx.mock
def test_vicino_a_scarta_fiducia_sotto_soglia(client, db_vivo, monkeypatch):
    """Una fonte sotto `fiducia_min_esterna` è **scartata**: stato `scartata_fiducia` e zero item esterni.

    Il test abbassa la fiducia della fonte OSM *in memoria*, per la durata del test, e la ripristina: è la verifica
    che il piano prescrive (`UPDATE fonte SET livello_fiducia=1` → `stato="scartata_fiducia"`).
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    async def abbassa() -> int | None:
        import asyncpg

        conn = await asyncpg.connect(_dsn_admin())
        try:
            return await conn.fetchval(
                "UPDATE trasi.fonte SET livello_fiducia = 1 WHERE tipo_accesso = 'osm_overpass' "
                "RETURNING livello_fiducia"
            )
        finally:
            await conn.close()

    async def ripristina() -> None:
        import asyncpg

        conn = await asyncpg.connect(_dsn_admin())
        try:
            await conn.execute(
                "UPDATE trasi.fonte SET livello_fiducia = 2 WHERE tipo_accesso = 'osm_overpass'"
            )
        finally:
            await conn.close()

    route = respx.post(ENDPOINT_OVERPASS).mock(return_value=_risposta_overpass([BAR_APERTO]))
    asyncio.run(abbassa())
    try:
        risposta = _vicino_a(client, "casa=san-bao&tipo=bar")
    finally:
        asyncio.run(ripristina())

    assert risposta.status_code == 200
    corpo = risposta.json()
    assert corpo["fonti_esterne"][0]["stato"] == "scartata_fiducia"
    assert not [item for item in corpo["items"] if item["provenienza"] == "esterna"]
    assert not route.called, "una fonte scartata non viene nemmeno interrogata"


@pytest.mark.live
@respx.mock
def test_vicino_a_max_risultati_esterni_limita_gli_item(client, db_vivo, parametro_esterno):
    """`max_risultati_esterni` limita gli item **esterni**, e non tocca quelli della memoria della rete."""
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    parametro_esterno("max_risultati_esterni", 2)
    respx.post(ENDPOINT_OVERPASS).mock(
        return_value=_risposta_overpass(
            [
                {
                    "type": "node",
                    "id": 900000 + indice,
                    "lat": 40.60600 + indice * 0.0002,
                    "lon": 17.95190 + indice * 0.0002,
                    "tags": {"amenity": "bar", "name": f"Bar tetto {indice}"},
                }
                for indice in range(8)
            ]
        )
    )

    corpo = _vicino_a(client, "casa=san-bao&tipo=bar&raggio_m=3000").json()

    esterni = [item for item in corpo["items"] if item["provenienza"] == "esterna"]
    assert len(esterni) == 2, f"il tetto [P] deve valere, trovati {len(esterni)} esterni"
    assert len([item for item in corpo["items"] if item["provenienza"] == "kb"]) >= 1, "la KB non è soggetta al tetto"


@pytest.mark.live
@respx.mock
def test_vicino_a_raggio_esplicito_prevale_su_casa_e_parametro(client, db_vivo):
    """`raggio_m` esplicito vince su `casa.raggio_m` e sul parametro [P], e viene riportato in risposta.

    Il campo `raggio_m` della risposta è ciò che permette al LLM di dire «entro 3 km» senza dedurlo: se dichiarasse
    il valore di default mentre la query ne usa un altro, la risposta mentirebbe sull'evidenza.
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    route = respx.post(ENDPOINT_OVERPASS).mock(return_value=_risposta_overpass([]))

    corpo = _vicino_a(client, "casa=san-bao&tipo=bar&raggio_m=3000").json()

    assert corpo["raggio_m"] == 3000
    assert "around:3000" in route.calls.last.request.content.decode("utf-8")


@pytest.mark.live
@respx.mock
def test_vicino_a_raggio_di_tuturano_viene_dalla_casa(client, db_vivo):
    """Tuturano ha `raggio_m=2000` in `casa`: la vicinanza è distanza reale, non zona (§2.1).

    È il caso che l'architettura cita esplicitamente: la frazione è fuori dal centro urbano e il raggio di default
    (800 m) non basterebbe a mostrare nulla.
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    route = respx.post(ENDPOINT_OVERPASS).mock(return_value=_risposta_overpass([]))

    corpo = _vicino_a(client, "casa=tuturano&tipo=bar", email="op.tuturano@trasi.local").json()

    assert corpo["raggio_m"] == 2000
    assert "around:2000" in route.calls.last.request.content.decode("utf-8")


@pytest.mark.live
@respx.mock
def test_vicino_a_p95_sotto_il_tempo_dichiarato(client, db_vivo):
    """20 chiamate a `vicino_a` (con Overpass mockato) restano molto sotto il timeout dichiarato di 3 s.

    Il criterio di B3-SHM-04 chiede p95 < 800 ms. Il margine misurato qui è ampio (p95 intorno ai 10 ms), e la ragione
    per cui vale la pena fissarlo come test è che la regressione tipica non è «un po' più lento»: è una query che
    perde l'indice o un `N+1` che moltiplica le andate e ritorno per ogni item.
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    import time

    respx.post(ENDPOINT_OVERPASS).mock(return_value=_risposta_overpass([BAR_APERTO, BAR_SENZA_ORARI]))

    _vicino_a(client, "casa=san-bao&tipo=bar")  # riscaldamento: la prima chiamata paga il pool e la cache
    tempi = []
    for _ in range(20):
        inizio = time.perf_counter()
        assert _vicino_a(client, "casa=san-bao&tipo=bar").status_code == 200
        tempi.append((time.perf_counter() - inizio) * 1000)

    tempi.sort()
    p95 = tempi[int(0.95 * len(tempi)) - 1]

    assert p95 < 800, f"p95 = {p95:.1f} ms, atteso < 800 ms (tempi: {[round(t, 1) for t in tempi]})"


@pytest.mark.live
def test_vicino_a_conosce_lo_stato_di_apertura_dei_luoghi_in_memoria(client, db_vivo):
    """Un luogo della memoria **con orari** dichiara `aperto_adesso: true|false`, non `null`.

    È un test di regressione su un difetto vero: `asyncpg` restituisce `jsonb` come **stringa**, quindi `orari`
    arrivava a `orari_da_jsonb` come testo e ogni luogo della rete risultava «senza orari noti». La risposta restava
    valida e plausibile — `aperto_adesso: null` è legittimo — quindi il difetto era invisibile; si vedeva solo
    guardando un bar con orari noti rispondere «orari non disponibili».

    Il test verifica la **relazione** fra i campi, non un valore: se c'è `orari_testo` allora lo stato deve essere
    determinato, e viceversa. È la proprietà che il difetto violava.
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    corpo = _vicino_a(client, "casa=bozzano&tipo=bar", email=EMAIL_OP_BOZZANO).json()
    kb = [item for item in corpo["items"] if item["provenienza"] == "kb"]

    assert kb, "il bar in memoria deve esserci"
    bar = kb[0]
    assert bar["orari_testo"], "il bar interno ha orari in memoria"
    assert bar["aperto_adesso"] is not None, (
        "un luogo con orari noti deve avere uno stato di apertura determinato: "
        "`null` qui significa che gli orari non sono stati interpretati"
    )
    assert bar["orari_nota"] is None, "con orari noti non c'è nota sugli orari mancanti"


@pytest.mark.live
def test_vicino_a_un_luogo_senza_orari_dichiara_la_nota(client, db_vivo):
    """Un luogo della memoria **senza** orari ha `aperto_adesso: null` e la nota: è il caso opposto, e va distinto."""
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    corpo = _vicino_a(client, "casa=buscicchio&tipo=caf", email="op.buscicchio@trasi.local").json()
    senza_orari = [item for item in corpo["items"] if not item["orari_testo"]]

    for item in senza_orari:
        assert item["aperto_adesso"] is None
        assert item["orari_nota"] == "orari non disponibili"


def test_orari_da_jsonb_interpreta_anche_una_stringa_json():
    """`orari_da_jsonb` accetta sia un dizionario sia la sua forma testuale.

    La tolleranza è deliberata e documentata: il codec del pool (`db._prepara_connessione`) è la correzione vera, ma
    se una connessione arrivasse senza codec — un pool creato altrove, un test, una futura aggiunta — l'orario valido
    non deve diventare «illeggibile». Il test blocca la regressione in entrambe le direzioni.
    """
    from datetime import datetime

    from app.vicinanza import orari_da_jsonb

    lunedi = datetime(2026, 9, 14, 10, 0, tzinfo=FUSO_LOCALE)

    assert orari_da_jsonb({"lun": ["08:00", "18:30"]}, lunedi) is True
    assert orari_da_jsonb('{"lun": ["08:00", "18:30"]}', lunedi) is True
    assert orari_da_jsonb({"lun": []}, lunedi) is False, "elenco vuoto = chiuso quel giorno"
    assert orari_da_jsonb({"mar": ["08:00", "18:30"]}, lunedi) is None, "chiave assente = stato non noto"
    assert orari_da_jsonb("{non json}", lunedi) is None, "una stringa non interpretabile non è un errore"


@pytest.mark.live
@respx.mock
def test_vicino_a_il_tempo_dichiarato_e_un_budget_complessivo(client, db_vivo, monkeypatch):
    """Con il failover configurato, il tempo dichiarato vale per **tutti** i tentativi, non per ciascuno.

    È un test di regressione su un difetto misurato nel container: senza questo vincolo, Overpass primario e failover
    ricevevano 5 s ciascuno e la risposta arrivava a 12,9 s — il doppio di quanto il contratto dichiara al chiamante.
    Il criterio «3 s shim, 5 s Overpass» è un tempo di risposta, non un tempo per endpoint.
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    from app.settings import get_settings

    impostazioni = get_settings()
    monkeypatch.setattr(impostazioni, "overpass_url_2", "https://failover.test/api/interpreter")

    respx.post(ENDPOINT_OVERPASS).mock(side_effect=httpx.ConnectTimeout("timeout simulato"))
    failover = respx.post("https://failover.test/api/interpreter").mock(
        side_effect=httpx.ConnectTimeout("timeout simulato")
    )

    import time

    inizio = time.monotonic()
    risposta = _vicino_a(client, "casa=san-bao&tipo=bar")
    durata = time.monotonic() - inizio

    assert risposta.status_code == 200
    assert risposta.json()["fonti_esterne"][0]["stato"] == "timeout"
    # Il budget è 5 s; il limite di 7 s lascia margine alla latenza della macchina senza ammettere due budget pieni.
    assert durata < 7.0, f"il budget dichiarato è 5 s complessivi, la risposta ha impiegato {durata:.1f} s"
    # Con un budget già esaurito il failover non viene nemmeno tentato: sarebbe tempo speso per un timeout certo.
    assert not failover.called or failover.call_count == 1


@pytest.mark.live
@respx.mock
def test_vicino_a_senza_failover_non_interroga_il_secondo_endpoint(client, db_vivo):
    """Senza `OVERPASS_URL_2` configurato non si tenta nessun secondo endpoint: il failover è opt-in."""
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    primario = respx.post(ENDPOINT_OVERPASS).mock(side_effect=httpx.ConnectTimeout("timeout simulato"))

    risposta = _vicino_a(client, "casa=san-bao&tipo=bar")

    assert risposta.status_code == 200
    assert risposta.json()["fonti_esterne"][0]["stato"] == "timeout"
    assert primario.call_count == 1, "un solo tentativo quando il failover non è configurato"


@pytest.mark.live
@respx.mock
def test_vicino_a_rispetta_il_budget_anche_con_una_risposta_lenta(client, db_vivo, monkeypatch):
    """Una risposta che si trascina non sfonda il budget dichiarato: il tempo vale per l'intera chiamata.

    Regressione su un difetto **misurato** nel container: `httpx` applica il timeout per fase (connessione, scrittura,
    lettura), quindi un `timeout=5` con una risposta lenta arrivava a 6,3 s reali — oltre i 5 s che il contratto
    dichiara al chiamante. Qui la sorgente è simulata lenta e si verifica il tempo **totale** misurato dal chiamante.
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    import time

    from app.settings import get_settings

    impostazioni = get_settings()
    # Budget breve: il test deve durare poco, e la proprietà verificata (il tempo è complessivo) non dipende dal
    # valore. Il default di produzione è 5 s (`OVERPASS_TIMEOUT_S` nel compose).
    monkeypatch.setattr(impostazioni, "overpass_timeout_s", 1)

    async def lenta(*_args, **_kwargs):
        import asyncio

        await asyncio.sleep(5)
        return httpx.Response(200, json={"elements": [BAR_APERTO]})

    respx.post(ENDPOINT_OVERPASS).mock(side_effect=lenta)

    inizio = time.monotonic()
    risposta = _vicino_a(client, "casa=san-bao&tipo=bar")
    durata = time.monotonic() - inizio

    assert risposta.status_code == 200, "un timeout è una risposta, non un guasto dello shim"
    assert risposta.json()["fonti_esterne"][0]["stato"] == "timeout"
    assert durata < 3.0, f"budget dichiarato 1 s, la risposta ha impiegato {durata:.1f} s"


# --- Live senza mock: Overpass vero ------------------------------------------------------------------------


@pytest.mark.live
def test_vicino_a_sanbao_bar_kb_e_osm(client, db_vivo):
    """Il criterio di done di B3-SHM-04, con Overpass **vero**: item KB e item esterni con badge.

    Due cose vanno dette perché il test non sia fuorviante:

    - il bar della memoria che il criterio cita è a **2.099 m** da San Bao (è il bar interno di Bozzano, e la sua
      Casa è Bozzano): la KB non è filtrata dal raggio, quindi compare — ed è la ragione per cui la risposta dichiara
      `distanza_m`, che il LLM riporta;
    - OSM **non ha bar entro 800 m** da San Bao (misurato: 0 sui tag `bar`/`pub`), quindi la parte «esterna» del
      criterio si verifica con il raggio della Casa di Bozzano, dove un bar OSM c'è davvero (127 m). Su San Bao si
      verifica invece che la risposta sia completa e coerente, non che il vuoto di OSM sia pieno.
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    corpo = _vicino_a(client, "casa=san-bao&tipo=bar").json()

    kb = [item for item in corpo["items"] if item["provenienza"] == "kb"]
    assert kb, "la memoria della rete deve rispondere con il bar interno di Bozzano"
    assert kb[0]["nome"].startswith("Bar interno"), f"atteso il bar in memoria, trovato {kb[0]['nome']}"
    assert kb[0]["distanza_m"] > 2000, "il bar in memoria è quello di Bozzano: la distanza lo dichiara"
    assert corpo["fonti_esterne"][0]["stato"] == "ok", "Overpass deve rispondere (User-Agent identificativo)"
    assert all(item["badge"] for item in corpo["items"])


@pytest.mark.live
def test_vicino_a_bozzano_unisce_kb_e_poi_osm_reali(client, db_vivo):
    """Dove OSM ha POI, la risposta unisce davvero le due fonti: bar OSM a 127 m + bar della rete a 31 m.

    È la prova che la parte esterna funziona **senza mock**, con lo User-Agent obbligatorio e con dati reali: se lo
    UA fosse quello di default di httpx, Overpass risponderebbe 403 e qui ci sarebbe `stato="errore"`.
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    corpo = _vicino_a(client, "casa=bozzano&tipo=bar", email=EMAIL_OP_BOZZANO).json()

    kb = [item for item in corpo["items"] if item["provenienza"] == "kb"]
    esterni = [item for item in corpo["items"] if item["provenienza"] == "esterna"]

    assert kb, "il bar interno di Bozzano è in memoria"
    assert esterni, "OSM ha bar entro il raggio di Bozzano (verificato: 3 entro 800 m)"
    assert corpo["fonti_esterne"][0]["stato"] == "ok"
    for item in esterni:
        assert item["badge"].startswith("[Esterna · ")
        assert item["aperto_adesso"] is None or isinstance(item["aperto_adesso"], bool)
    # L'ordinamento del contratto, verificato su dati reali.
    assert [item["provenienza"] for item in corpo["items"]][0] == "kb"


@pytest.mark.live
def test_vicino_a_ogni_item_rispetta_lo_schema_del_contratto(client, db_vivo, contratto):
    """La risposta reale rispetta i campi `required` dello schema congelato `ItemVicinanza`.

    Il contratto è la fonte di verità: se un campo `required` mancasse, Onyx non potrebbe leggere la risposta del
    tool e il LLM riceverebbe un errore invece dei dati.
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    richiesti = set(contratto["components"]["schemas"]["ItemVicinanza"]["required"])
    corpo = _vicino_a(client, "casa=bozzano&tipo=bar", email=EMAIL_OP_BOZZANO).json()

    assert corpo["items"], "attesi item per verificare lo schema"
    for item in corpo["items"]:
        assert richiesti <= set(item), f"campi mancanti: {richiesti - set(item)}"
        assert set(item) == richiesti, f"campi non dichiarati nel contratto: {set(item) - richiesti}"

    richiesti_risposta = set(contratto["components"]["schemas"]["RispostaVicinoA"]["required"])
    assert richiesti_risposta <= set(corpo)


@pytest.mark.live
def test_vicino_a_rete_senza_casa_422(client, db_vivo):
    """Un ruolo SENZA Casa propria non può ricadere sull'identità: lì la Casa serve davvero.

    È la controprova del comportamento introdotto il 2026-09-16: la tolleranza verso uno slug
    inesistente vale solo quando il sistema **sa** quale Casa usare (identità). Per `rete`, che non
    ne ha una, la richiesta senza `casa` valida resta un errore — altrimenti si leggerebbe la
    memoria di una Casa a caso.
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    risposta = _vicino_a(client, "tipo=bar", email="rete@trasi.local")

    assert risposta.status_code == 422
    assert "casa" in risposta.json()["detail"]


@pytest.mark.live
def test_vicino_a_nome_casa_al_posto_dello_slug(client, db_vivo):
    """Il modello passa il NOME della Casa invece dello slug: la Casa viene riconosciuta dal nome.

    È il caso reale osservato dal tunnel: `casa=«Centro di Aggregazione Bozzano»` — il nome, non
    `bozzano`. Con il 422 l'assistente dichiarava un guasto inesistente; dal 2026-09-17 (commit
    61df9d8) la risoluzione per nome ha sostituito il ripiego silenzioso sull'identità: ripiegare
    faceva ricevere all'operatore di POP gli eventi di San Bao, e l'operatore concludeva di non
    poter leggere le altre Case. Il ripiego resta per un testo che non è nessuna Casa
    (`test_vicino_a_casa_inesistente_ricade_sull_identita`).
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    risposta = _vicino_a(client, "casa=Centro+di+Aggregazione+Bozzano&tipo=bar")

    assert risposta.status_code == 200
    assert risposta.json()["casa"] == "bozzano", (
        "la Casa nominata per nome deve risolversi nel suo slug, non ripiegare sull'identità"
    )
