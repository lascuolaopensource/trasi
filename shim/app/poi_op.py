"""`GET /op/poi?bbox=…&tipi[]=…&aperto_adesso=…`: i punti di interesse di OpenStreetMap dentro il riquadro visibile.

È l'endpoint che rende possibile la mappa dell'Osservatorio (§5.2, `T-SHIM-05`, gate **G-06 chiuso**), e la ragione
per cui esiste è una misura, non un'idea: `vicino_a` accetta **un tipo per chiamata** e misura dalla **Casa**, non
dalla bbox. Una mappa con sei caselle attive farebbe **sei** chiamate a Overpass a ogni movimento, su un servizio che
durante la verifica di B0 ha già risposto `504` in 11,6 s. Qui si fa **una** query per N tipi: è l'unico punto di
questo modulo che merita di essere scritto, il resto è composizione.

**Cosa si riusa, e perché non si duplica.** `costruisci_query` (per il vocabolario), `orari_da_jsonb` (per gli orari
della KB), l'`_elemento_a_poi`/`PoiOsm` di `vicinanza.py` (per la normalizzazione dell'elemento OSM) e la regola
`rank_apertura`. La **sola** cosa nuova della query è il costruttore per bbox e più tipi: `costruisci_query` è
tarato su `around:<raggio>,<lat>,<lon>` e non ha un modo di esprimere un riquadro, quindi si scrive qui — ma i tag
vengono da `TIPI_OSM`, che resta l'unica autorità sul vocabolario.

**Una sola chiamata HTTP, con `_chiama_overpass`.** Non si riscrive la chiamata: `vicinanza._chiama_overpass` porta
lo User-Agent identificativo (obbligatorio: senza, Overpass risponde **403**, verificato in B0), impone il budget con
`asyncio.wait_for` (i timeout di `httpx` sono **per fase**, quindi un `timeout=5` può arrivare a 10 s) e ritorna uno
**stato** invece di sollevare. Il failover è lo stesso di `interroga_overpass`: si tenta il secondo endpoint solo se
il primo non ha risposto, e solo con il tempo che resta nel budget dichiarato.

**Cache in memoria, TTL 10 minuti, tetto 200 voci.** La chiave è la bbox arrotondata, i tipi **ordinati** e
`aperto_adesso`: due richieste identiche entro 10 minuti fanno **zero** chiamate. Il tetto è dichiarato nel piano e
non è un dettaglio: lo shim vive in un container da 256 MB (`mem_limit` del compose), e una cache senza tetto su un
endpoint che accetta una bbox arbitraria è una perdita lenta. L'eviction è FIFO sull'ordine di inserimento
(`OrderedDict.popitem(last=False)`), non LRU: il caso d'uso è «l'operatore esplora un quartiere», e una voce vecchia
ma riusata vale quanto una nuova — pagare il contatore di accessi per guadagnare nulla non è giustificato.

**`aperto_adesso=true` non scarta i POI senza orari.** Esce solo chi è **noto** come chiuso; un POI senza
`opening_hours` resta in coda agli aperti noti con `aperto_adesso: null` e `orari_nota: "orari non disponibili"`. La
copertura reale di `opening_hours` sui bar di Brindisi è **7,7%**: scartarli nasconderebbe il 92% dei POI, ed è la
mitigazione dichiarata del rischio §13.

**Il guasto di una fonte non è un errore dello shim** (§9.1): allo scadere del budget si risponde **200** con
`poi: []` e `fonti_esterne[].stato = "timeout"`. Mai un'eccezione al chiamante, mai un 503 per una fonte esterna.
"""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Query

from .auth import SessioneOperatore, sessione_corrente
from .badge import badge_esterna, nome_fonte
from .db import parametri, parametro_int
from .errori import errore
from .settings import get_settings
from .vicinanza import (
    STATO_OK,
    STATO_SCARTATA_FIDUCIA,
    TIPI_OSM,
    _chiama_overpass,
    _elemento_a_poi,
    adesso_locale,
    distanza_m,
    rank_apertura,
)

router = APIRouter()

# Tetto e durata della cache, dal piano §5.2. Sono costanti e non parametri [P] perché il loro effetto non è una
# scelta di esercizio: 200 voci stanno nel budget di memoria dello shim, 10 minuti sono la finestra oltre la quale
# una risposta di Overpass su un quartiere può essere invecchiata (una farmacia che chiude, un bar che apre).
CACHE_TTL_S = 600
CACHE_MAX_VOCI = 200

# La bbox è validata, non solo limitata: 4 numeri, lat −90..90, lon −180..180, e un'area ≤ 0,02°² (~ 5×5 km a
# Brindisi). Il tetto di area è la traduzione del «nessuna chiamata in bulk» della policy Overpass: una bbox grande
# quanto una provincia non è un viewport, è un'estrazione.
AREA_MAX_GRADI_QUADRATI = 0.02

# Quanti elementi chiedere a Overpass: lo stesso tetto di `vicinanza` (60). `out center` è obbligatorio — un bar
# mappato come way non ha coordinate proprie, e senza `center` metà dei POI sparirebbe in silenzio.
TETTO_INTERROGAZIONE = 60

# Vocabolario esteso: `vicino_a` non conosce `scuola` (l'enum del contratto congelato non la prevede), ma la mappa
# sì — è il gate G-06, verificato dal vivo: 30 scuole nella bbox di Brindisi.
TIPI_OSM_ESTESI: dict[str, tuple[tuple[str, str], ...]] = {**TIPI_OSM, "scuola": (("amenity", "school"),)}

TIPI_MAPPA: tuple[str, ...] = tuple(sorted(TIPI_OSM_ESTESI))

TIPO_ACCESSO_OSM = "osm_overpass"
NOME_OSM_DEFAULT = "OpenStreetMap"

CHIAVI_PARAMETRI = ("fiducia_min_esterna",)
FIDUCIA_MIN_DEFAULT = 2

# Nome della fonte OSM con l'autorità umana, con la stessa risoluzione di `routes_geo.SQL_FONTE_OSM`.
SQL_FONTE_OSM = """
SELECT f.nome, f.autorita, f.livello_fiducia
  FROM trasi.fonte f
 WHERE f.tipo_accesso = 'osm_overpass' AND f.attiva
 ORDER BY f.livello_fiducia DESC, f.id
 LIMIT 1
"""


# --- Cache ----------------------------------------------------------------------------------------------------
#
# Tre funzioni e non un decoratore: la cache va **misurata** dai test («la seconda chiamata identica fa zero
# richieste»), e un decoratore opaco non si svuota fra un test e l'altro. `_cache` è di modulo perché il processo è
# uno solo (un worker uvicorn), e questo è il punto: se un giorno i worker diventano due, la cache resta corretta ma
# dimezzata, e la riga da cambiare è questa.

_cache: "OrderedDict[str, tuple[float, list[dict[str, Any]]]]" = OrderedDict()


def chiave_cache(bbox: str, tipi: list[str], aperto_adesso: bool) -> str:
    """La chiave della cache: `md5(bbox | tipi ordinati | aperto_adesso)`.

    I tipi si ordinano perché l'ordine in cui il browser manda le caselle spuntate non è un fatto: `tipi[]=bar&
    tipi[]=farmacia` e l'inverso sono la stessa domanda, e senza l'ordinamento sarebbero due voci di cache e due
    chiamate a Overpass. La bbox si normalizza a 6 decimali (~ 10 cm): due riquadri identici che differiscono
    nell'ultimo bit del float sono la stessa richiesta.
    """
    materiale = "|".join([bbox, ",".join(sorted(tipi)), "1" if aperto_adesso else "0"])
    return hashlib.md5(materiale.encode("utf-8")).hexdigest()


def _cache_leggi(chiave: str) -> list[dict[str, Any]] | None:
    """I POI in cache se non sono scaduti; `None` altrimenti. Una voce scaduta esce anche dalla mappa."""
    voce = _cache.get(chiave)
    if voce is None:
        return None
    inserito, poi = voce
    if time.monotonic() - inserito >= CACHE_TTL_S:
        del _cache[chiave]
        return None
    return poi


def _cache_scrivi(chiave: str, poi: list[dict[str, Any]]) -> None:
    """Mette i POI in cache, applicando il tetto FIFO: si butta la voce **più vecchia per inserimento**.

    `move_to_end` non si usa di proposito: sarebbe una LRU, e la scelta di FIFO è dichiarata nella docstring del
    modulo. Una voce riscritta (stessa chiave) va comunque in fondo, che è corretto — è appena stata aggiornata.
    """
    _cache[chiave] = (time.monotonic(), poi)
    _cache.move_to_end(chiave)
    while len(_cache) > CACHE_MAX_VOCI:
        _cache.popitem(last=False)


def svuota_cache() -> None:
    """Azzera la cache (usata dai test: una cache calda fra due test renderebbe invisibile una regressione)."""
    _cache.clear()


# --- Geometria della bbox -------------------------------------------------------------------------------------


def analizza_bbox(grezza: str) -> tuple[float, float, float, float]:
    """`minlon,minlat,maxlon,maxlat` → quattro float validati, o **422** con il motivo.

    La validazione è qui e non in pydantic perché il parametro è una stringa sola: il contratto della mappa la vuole
    nel formato OGC (`minlon,minlat,maxlon,maxlat`), che è quello che `map.getBounds().toBBoxString()` produce nel
    browser, e scomporla in quattro parametri separati obbligherebbe la pagina a tradurre un formato che riceve già
    pronto. Un valore assente o malformato è un 422 **dichiarato**, non un 500.
    """
    parti = [parte.strip() for parte in (grezza or "").split(",")]
    if len(parti) != 4:
        raise errore(422, "parametri non ammessi — bbox: attesi quattro numeri «minlon,minlat,maxlon,maxlat»")
    try:
        minlon, minlat, maxlon, maxlat = (float(parte) for parte in parti)
    except ValueError:
        raise errore(422, "parametri non ammessi — bbox: i quattro valori devono essere numeri") from None

    if not -90.0 <= minlat <= 90.0 or not -90.0 <= maxlat <= 90.0:
        raise errore(422, "parametri non ammessi — bbox: la latitudine sta fra -90 e 90")
    if not -180.0 <= minlon <= 180.0 or not -180.0 <= maxlon <= 180.0:
        raise errore(422, "parametri non ammessi — bbox: la longitudine sta fra -180 e 180")
    if maxlat < minlat or maxlon < minlon:
        raise errore(422, "parametri non ammessi — bbox: gli angoli sono invertiti (attesi minlon,minlat,maxlon,maxlat)")
    if (maxlon - minlon) * (maxlat - minlat) > AREA_MAX_GRADI_QUADRATI:
        raise errore(
            422,
            "parametri non ammessi — bbox: riquadro troppo ampio; la mappa interroga il riquadro visibile, non una zona",
        )
    return minlon, minlat, maxlon, maxlat


def costruisci_query_bbox(tipi: list[str], bbox: tuple[float, float, float, float], *, tetto: int = TETTO_INTERROGAZIONE) -> str:
    """La query Overpass QL per **N tipi in una volta sola**, dentro un riquadro.

    È il cuore del gate G-06, e la differenza rispetto a `vicinanza.costruisci_query` è tutta qui: le clausole dei
    tipi finiscono nella **stessa** `(...)`, quindi Overpass le risolve in un'unica passata. `nwr` e non `node` (un
    POI mappato come area è una way), `(bbox)` invece di `(around:…)` (il riquadro è quello che l'operatore vede), e
    `out center` perché way e relation non hanno coordinate proprie.
    """
    angolo = ",".join(f"{valore:.6f}" for valore in bbox)
    clausole = "\n".join(
        f'  nwr["{chiave}"="{valore}"]({angolo});'
        for tipo in tipi
        for chiave, valore in TIPI_OSM_ESTESI[tipo]
    )
    return f"[out:json][timeout:25];\n(\n{clausole}\n);\nout center {tetto};"


# --- Composizione degli item ----------------------------------------------------------------------------------


async def _nome_fonte_osm(sess: SessioneOperatore) -> tuple[str, int]:
    """Il nome leggibile della fonte OSM attiva e la sua fiducia, dalla riga di allow-list `trasi.fonte`."""
    riga = await sess.fetchrow(SQL_FONTE_OSM)
    if riga is None:
        return NOME_OSM_DEFAULT, 0
    return nome_fonte(riga["autorita"], riga["nome"]), riga["livello_fiducia"]


def _item(
    poi: Any,
    *,
    tipo: str,
    osm_tipo: str,
    fonte: str,
    fiducia: int,
    consultato: Any,
    lat_rif: float | None,
    lon_rif: float | None,
) -> dict[str, Any]:
    """Un `PoiOsm` → l'elemento che la mappa disegna come **cerchio vuoto** (`[Esterna · …]`, tratteggiato).

    `osm_tipo` (`node`/`way`/`relation`) è il segmento che manca per ricostruire il riferimento
    `osm:<tipo>:<id>`: è la forma che `GET /op/biglietto` accetta per un punto che non è in memoria, e senza di
    essa la pagina potrebbe scrivere solo `osm:node:<id>` — che è sbagliato per un bar mappato come **way**, cioè
    per metà dei POI reali (`nwr` esiste proprio per prenderli).

    `distanza_m` è `null` quando non c'è una Casa di riferimento (ruolo `rete`): la distanza si misura da un punto,
    e quel punto qui è la Casa della sessione. Il piano §5.2 non elenca `distanza_m` fra i campi dell'output dei POI
    (a differenza di `vicino_a`, che la esige), ma la scheda del luogo la mostra nella testata (§4.2.2): «distanza
    dalla Casa (`840 m`, `1,2 km`)». Averla dallo shim evita alla pagina di rifare in JavaScript un conto che
    `distanza_m` fa già, e con la stessa formula.
    """
    return {
        "provenienza": "esterna",
        "id": None,
        "osm_id": poi.node_id,
        "osm_tipo": osm_tipo,
        "nome": poi.nome,
        "tipo": tipo,
        "zona": None,
        "lat": poi.lat,
        "lon": poi.lon,
        "indirizzo": poi.indirizzo,
        "orari_testo": poi.orari_testo,
        "orari_nota": poi.orari_nota,
        "aperto_adesso": poi.aperto_adesso,
        "distanza_m": (
            round(distanza_m(lat_rif, lon_rif, poi.lat, poi.lon), 1)
            if lat_rif is not None and lon_rif is not None
            else None
        ),
        "casa_id": None,
        "casa_slug": None,
        "casa_nome": None,
        "url": poi.url,
        "fonte": fonte,
        "fiducia": fiducia,
        "data_aggiornamento": None,
        "consultato_ts": consultato.isoformat(),
        "badge": badge_esterna(fonte, consultato),
    }


def _ordina_poi(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Apertura (`true` → `null` → `false`) e poi distanza; a parità di distanza, il nome.

    Non si riusa `vicinanza.ordina_items` perché quello ordina per **gruppo** (KB prima, esterni dopo) e qui il
    gruppo è uno solo: resterebbe un ordinamento identico ma dipendente da un campo che questi item non hanno, e una
    riga di codice che finge di fare qualcosa. La scala di apertura è `rank_apertura`, che è l'unica autorità su
    «aperto prima di chiuso».
    """
    return sorted(
        items,
        key=lambda item: (
            rank_apertura(item["aperto_adesso"]),
            item["distanza_m"] if item["distanza_m"] is not None else float("inf"),
            item["nome"],
        ),
    )


async def _poi_da_overpass(
    *,
    tipi: list[str],
    bbox: tuple[float, float, float, float],
    aperto_adesso: bool,
    fonte: str,
    fiducia: int,
    consultato: Any,
    lat_rif: float | None,
    lon_rif: float | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Interroga Overpass **una volta** e ritorna (item, esito dichiarato). **Mai** un'eccezione.

    Il budget è quello dichiarato (`OVERPASS_TIMEOUT_S=5`) e vale per **tutti** i tentativi: al failover si passa
    solo il tempo che resta, e se non ne resta si dichiara il timeout senza tentarlo. È la stessa regola di
    `interroga_overpass`, e la ragione è la stessa: con un budget per endpoint la risposta arriverebbe a oltre 10 s,
    cioè il doppio di quanto il contratto dichiara al chiamante.
    """
    impostazioni = get_settings()
    inizio = time.monotonic()
    scadenza = inizio + impostazioni.overpass_timeout_s
    query = costruisci_query_bbox(tipi, bbox)

    def rimanente() -> float:
        return max(0.0, scadenza - time.monotonic())

    stato, elementi = await _chiama_overpass(query, impostazioni.overpass_url, rimanente(), impostazioni.overpass_user_agent)
    if stato != STATO_OK and impostazioni.overpass_url_2 and rimanente() > 0:
        stato, elementi = await _chiama_overpass(
            query, impostazioni.overpass_url_2, rimanente(), impostazioni.overpass_user_agent
        )

    ms = int((time.monotonic() - inizio) * 1000)
    if stato != STATO_OK:
        # Timeout o errore: la lista è vuota, lo stato dice il perché. Il chiamante non vede un 503 per una fonte
        # che non è sua, e la pagina disegna «l'elenco mostra solo la memoria della rete» (§4.2.1).
        return [], {"fonte": fonte, "stato": stato, "ms": ms}

    # Il tipo di ogni elemento si ritrova dai **tag**, non dall'ordine della risposta: Overpass non garantisce di
    # restituire gli elementi raggruppati per clausola, e un POI etichettato col tipo sbagliato finirebbe sotto il
    # filtro sbagliato della pagina. `TIPI_OSM_ESTESI` è l'autorità sulla traduzione, quindi si scorre **quello**.
    associati: list[dict[str, Any]] = []
    for elemento in elementi:
        tag = elemento.get("tags") or {}
        for tipo in tipi:
            if any(tag.get(chiave) == valore for chiave, valore in TIPI_OSM_ESTESI[tipo]):
                poi = _elemento_a_poi(elemento, tipo, consultato)
                if poi is not None:
                    associati.append(_item(
                        poi,
                        tipo=tipo,
                        # Il tipo dell'elemento viene dalla risposta grezza, non dalla dataclass: `PoiOsm` porta
                        # l'identificativo ma non se è un nodo, una way o una relation, e serve per comporre il
                        # riferimento `osm:<tipo>:<id>` del biglietto.
                        osm_tipo=elemento.get("type", "node"),
                        fonte=fonte,
                        fiducia=fiducia,
                        consultato=consultato,
                        lat_rif=lat_rif,
                        lon_rif=lon_rif,
                    ))
                break

    if aperto_adesso:
        # Escono i soli chiusi **noti**: `is not False` tiene dentro i POI senza orari, che sono la maggioranza
        # reale (§13) e la ragione per cui il filtro non è un semplice `aperto_adesso == True`.
        associati = [item for item in associati if item["aperto_adesso"] is not False]

    return _ordina_poi(associati), {"fonte": fonte, "stato": STATO_OK, "ms": ms}


@router.get(
    "/poi",
    operation_id="op_poi",
    summary="Punti di interesse di OpenStreetMap dentro il riquadro visibile della mappa, per più tipi in una sola "
    "interrogazione: bar, farmacie, scuole, fermate e gli altri tipi del vocabolario. Ogni voce porta il badge "
    "«non verificata dalla rete»; se OpenStreetMap non risponde, l'elenco resta vuoto e lo stato della fonte lo dice.",
    tags=["op"],
)
async def op_poi(
    bbox: str = Query(
        description="Riquadro geografico «minlon,minlat,maxlon,maxlat» (come `map.getBounds().toBBoxString()`), "
        "obbligatorio. Area massima 0,02 gradi quadrati: è il riquadro visibile, non un'estrazione."
    ),
    tipi: list[str] = Query(
        default=[],
        description="Tipi di punto di interesse, ripetibile (`tipi=bar&tipi=farmacia`). Uno a otto valori dal "
        "vocabolario; i tipi si risolvono in **una sola** interrogazione a OpenStreetMap.",
    ),
    aperto_adesso: bool = Query(
        default=False,
        description="Se `true`, esclude i punti noti come chiusi. I punti **senza orari** restano in elenco con "
        "`aperto_adesso: null` e `orari_nota`: la copertura degli orari su OpenStreetMap è parziale.",
    ),
    sess: SessioneOperatore = Depends(sessione_corrente),
) -> dict[str, Any]:
    """GET /op/poi → `{poi, fonti_esterne, consultato_ts, dalla_cache, bbox}`.

    L'ordine dei controlli è deliberato: **prima** la validazione locale (bbox e vocabolario), che non dipende da
    nulla e deve dare un 422 utile anche con Overpass giù; **poi** la fonte di allow-list (una lettura); **infine**
    la rete. Un tipo fuori vocabolario è un 422 **con l'elenco ammesso nel messaggio**: il browser manda solo le
    caselle che la pagina disegna, quindi un valore ignoto è un difetto di programmazione, e l'elenco è ciò che lo
    rende correggibile senza leggere il codice.

    Nessun parametro sceglie la Casa: la distanza si misura dalla Casa **della sessione** (§4.2.2), che è l'unica che
    l'operatore può chiamare «qui». La bbox invece la sceglie la pagina, perché è ciò che l'operatore sta guardando.
    """
    angolo = analizza_bbox(bbox)

    richiesti = [tipo.strip().lower() for tipo in tipi if tipo and tipo.strip()]
    if not richiesti:
        # Nessun tipo attivo: non c'è nulla da interrogare, e una query senza clausole restituirebbe *tutto* il
        # riquadro — cioè l'estrazione che la policy Overpass vieta. Si dichiara, non si indovina.
        raise errore(422, "parametri non ammessi — tipi: indicare almeno un tipo; valori ammessi " + ", ".join(TIPI_MAPPA))
    ignoti = sorted({tipo for tipo in richiesti if tipo not in TIPI_OSM_ESTESI})
    if ignoti:
        raise errore(
            422,
            f"parametri non ammessi — tipi: valori non ammessi {', '.join(ignoti)}; valori ammessi " + ", ".join(TIPI_MAPPA),
        )
    if len(set(richiesti)) > 8:
        raise errore(422, "parametri non ammessi — tipi: al massimo 8 tipi per interrogazione")
    tipi_unici = sorted(set(richiesti))

    consultato = adesso_locale()

    fonte, fiducia = await _nome_fonte_osm(sess)
    valori = await parametri(sess, CHIAVI_PARAMETRI)
    soglia = parametro_int(valori, "fiducia_min_esterna", FIDUCIA_MIN_DEFAULT)

    bbox_normalizzata = ",".join(f"{valore:.6f}" for valore in angolo)
    chiave = chiave_cache(bbox_normalizzata, tipi_unici, aperto_adesso)

    if fiducia < soglia:
        # La fonte è sotto la soglia di fiducia: non si interroga affatto. Interrogarla per poi scartarne i risultati
        # costerebbe il budget dichiarato (5 s) per una risposta che non si userà, ed è lo stesso criterio di
        # `routes_geo.valuta_fonte`.
        return {
            "bbox": bbox_normalizzata,
            "tipi": tipi_unici,
            "aperto_adesso": aperto_adesso,
            "consultato_ts": consultato.isoformat(),
            "dalla_cache": False,
            "poi": [],
            "fonti_esterne": [{"fonte": fonte, "stato": STATO_SCARTATA_FIDUCIA, "ms": 0}],
        }

    in_cache = _cache_leggi(chiave)
    if in_cache is not None:
        # Seconda chiamata identica entro 10 minuti: **zero** richieste a Overpass. È il criterio osservabile di
        # `T-SHIM-05`, e per questo la risposta dichiara `dalla_cache`: senza, il test dovrebbe contare le richieste
        # per distinguere una cache che funziona da una fonte che risponde sempre uguale.
        return {
            "bbox": bbox_normalizzata,
            "tipi": tipi_unici,
            "aperto_adesso": aperto_adesso,
            "consultato_ts": consultato.isoformat(),
            "dalla_cache": True,
            "poi": in_cache,
            "fonti_esterne": [{"fonte": fonte, "stato": STATO_OK, "ms": 0}],
        }

    riferimento = await sess.fetchrow(
        "SELECT round(st_y(geom::geometry)::numeric, 6) AS lat, round(st_x(geom::geometry)::numeric, 6) AS lon "
        "FROM trasi.casa WHERE id = $1",
        sess.casa_id,
    ) if sess.casa_id is not None else None

    poi, esito = await _poi_da_overpass(
        tipi=tipi_unici,
        bbox=angolo,
        aperto_adesso=aperto_adesso,
        fonte=fonte,
        fiducia=fiducia,
        consultato=consultato,
        lat_rif=float(riferimento["lat"]) if riferimento else None,
        lon_rif=float(riferimento["lon"]) if riferimento else None,
    )

    # Si mette in cache **anche** l'esito `ok` con lista vuota (zero POI è una risposta, non un guasto), ma non un
    # timeout: una fonte che non ha risposto non merita 10 minuti di silenzio, la prossima richiesta la ritenta.
    if esito["stato"] == STATO_OK:
        _cache_scrivi(chiave, poi)

    return {
        "bbox": bbox_normalizzata,
        "tipi": tipi_unici,
        "aperto_adesso": aperto_adesso,
        "consultato_ts": consultato.isoformat(),
        "dalla_cache": False,
        "poi": poi,
        "fonti_esterne": [esito],
    }


def monta(applicazione: FastAPI) -> None:
    """Monta il router sotto `/op`, **fuori** dal documento OpenAPI (stessa regola di `mappa_op.monta`)."""
    applicazione.include_router(router, prefix="/op", include_in_schema=False)


__all__ = [
    "AREA_MAX_GRADI_QUADRATI",
    "CACHE_MAX_VOCI",
    "CACHE_TTL_S",
    "TIPI_MAPPA",
    "TIPI_OSM_ESTESI",
    "analizza_bbox",
    "chiave_cache",
    "costruisci_query_bbox",
    "monta",
    "op_poi",
    "router",
    "svuota_cache",
]
