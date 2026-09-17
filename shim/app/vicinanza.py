"""`vicino_a`: unione della memoria della rete (KB) con i punti di interesse esterni di OpenStreetMap.

Questo modulo è il pezzo più delicato dello shim, per tre ragioni che vale la pena scrivere qui una volta sola.

**1. Lo User-Agent è obbligatorio.** Verificato in B0 (`docs/verifiche.md` §1): Overpass risponde **403** a un UA
generico e **200** a `Trasi/0.1 (portierato Brindisi)`. Non è una cortesia verso il servizio: senza UA identificativo
ogni chiamata fallisce in modo opaco, e lo shim direbbe «errore» su una fonte che risponde.

**2. Il guasto di una fonte non è un errore dello shim.** Il timeout dichiarato è 5 s per Overpass; allo scadere si
risponde **200** con `fonti_esterne[].stato = "timeout"` e i soli item KB. La regola §9.1 — «mai eccezione al
chiamante» — è la ragione per cui ogni funzione di I/O esterna di questo modulo ritorna uno stato invece di
sollevare.

**3. La copertura OSM reale è scarsa** (7.7% di `opening_hours` sui bar di Brindisi, `docs/verifiche.md` V-extra).
Un POI senza orari **non si scarta**: resta in coda agli aperti noti con `aperto_adesso: null` e
`orari_nota: "orari non disponibili"`. È la mitigazione del rischio §13 del documento di architettura, e scartarlo
significherebbe nascondere il 92% dei POI reali.

**Ordinamento** (`plan.md` §B3): prima il gruppo KB, poi gli esterni; dentro il gruppo `aperto_adesso: true` → `null`
→ `false`; a parità, la distanza. Con `aperto_adesso=true` i chiusi **noti** escono, gli altri restano.

**Raggio.** La KB **non** è filtrata dal raggio: è la memoria della rete, e il criterio di done di B3-SHM-04 chiede
che `vicino_a?casa=san-bao&tipo=bar` mostri il bar di Bozzano, che dista 2.099 m (l'unico bar in memoria, e la sua
Casa è Bozzano). Il raggio si applica alle **fonti esterne**, dove serve a non sommergere la risposta di POI: è
quanto dice l'architettura §3 («query Overpass entro `casa.raggio_m`») e §8 F1 («Overpass entro raggio_m»). La
distanza resta dichiarata su ogni item, quindi il LLM vede che quel bar è a 2 km.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from opening_hours import OpeningHours, ParserError

from .badge import FUSO_ITALIANO, NOTA_ORARI_ASSENTI, badge_esterna, badge_kb, nome_fonte

# --- Vocabolario chiuso dei tipi (plan.md §B3) ---------------------------------------------------------------
# La mappa è `tipo shim → tag OpenStreetMap`. Un tipo fuori da questo dizionario risponde 422 con l'elenco ammesso:
# è un vocabolario, non un filtro libero, perché il LLM deve poter sapere *prima* quali domande sono possibili.
TIPI_OSM: dict[str, tuple[tuple[str, str], ...]] = {
    "bar": (("amenity", "bar"), ("amenity", "pub")),
    "farmacia": (("amenity", "pharmacy"),),
    # OpenStreetMap non ha un tag standard per i CAF/patronati: si interrogano le due forme effettivamente usate in
    # Italia. Se non trovano nulla la risposta resta valida (soli item KB), non è un errore.
    "caf": (("amenity", "social_facility"), ("office", "patronato")),
    "fermata": (("highway", "bus_stop"),),
    "poste": (("amenity", "post_office"),),
    "medico": (("amenity", "doctors"),),
    "ospedale": (("amenity", "hospital"),),
    "supermercato": (("shop", "supermarket"),),
    "biblioteca": (("amenity", "library"),),
    "parco": (("leisure", "park"),),
    "banca": (("amenity", "bank"),),
    "comune": (("amenity", "townhall"),),
}

TIPI_AMMESSI: tuple[str, ...] = tuple(sorted(TIPI_OSM))

# Quanti elementi chiedere a Overpass prima di ordinare e applicare `max_risultati_esterni`: il tetto finale è un
# parametro [P] piccolo (5), quindi serve margine per scegliere i *migliori* e non i primi arrivati.
TETTO_INTERROGAZIONE = 60

# Sorgente OSM: la riga di `trasi.fonte` con `tipo_accesso='osm_overpass'` è l'autorità su nome e fiducia.
TIPO_ACCESSO_OSM = "osm_overpass"

STATO_OK = "ok"
STATO_TIMEOUT = "timeout"
STATO_ERRORE = "errore"
STATO_SCARTATA_FIDUCIA = "scartata_fiducia"

NOME_SENZA_NOME = "nome non indicato su OpenStreetMap"

GIORNI = ("lun", "mar", "mer", "gio", "ven", "sab", "dom")


# --- Geometria ------------------------------------------------------------------------------------------------

RAGGIO_TERRA_M = 6_371_008.8


def distanza_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distanza in metri fra due punti WGS84 (formula di Haversine).

    Il calcolo sta in Python e non in PostGIS perché i POI esterni non sono nel database: portarli dentro per
    misurare una distanza costerebbe una scrittura, che lo shim non può fare (V4). L'errore della formula sferica
    rispetto a `geography` è sotto lo 0,3% alle distanze in gioco (chilometri), irrilevante per una risposta che
    dichiara i metri arrotondati.
    """
    fi1, fi2 = math.radians(lat1), math.radians(lat2)
    d_fi = fi2 - fi1
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_fi / 2) ** 2 + math.cos(fi1) * math.cos(fi2) * math.sin(d_lambda / 2) ** 2
    return 2 * RAGGIO_TERRA_M * math.asin(math.sqrt(a))


# --- Orari ----------------------------------------------------------------------------------------------------


def orari_da_jsonb(orari: Any, adesso: datetime) -> bool | None:
    """Stato di apertura da un `orari` jsonb del modello dati (`{lun..dom: ["HH:MM","HH:MM", …]}`).

    `[]` significa **chiuso** quel giorno (è la convenzione di `db/004_views.sql`); una chiave **assente** significa
    «non lo sappiamo». Distinguerli è essenziale: trattare una chiave assente come «chiuso» farebbe sparire le Case
    che non dichiarano la domenica, ed è esattamente il tipo di dato inventato che la V3 vieta.

    Una stringa JSON viene interpretata: `asyncpg` restituisce `jsonb` come testo se non ha il codec (vedi
    `db._prepara_connessione`, che lo imposta), e senza questa tolleranza un `orari` perfettamente valido verrebbe
    trattato come illeggibile — un difetto silenzioso, perché ogni luogo risulterebbe «senza orari noti».

    Ritorna `None` quando lo stato non è determinabile (orari assenti, giorno non dichiarato, fasce malformate).
    """
    if isinstance(orari, (str, bytes)):
        try:
            orari = json.loads(orari)
        except (ValueError, TypeError):
            return None
    if not isinstance(orari, dict):
        return None
    fasce = orari.get(GIORNI[adesso.weekday()])
    if not isinstance(fasce, list):
        return None
    if not fasce:
        return False
    for indice in range(0, len(fasce) - 1, 2):
        apertura, chiusura = fasce[indice], fasce[indice + 1]
        if not isinstance(apertura, str) or not isinstance(chiusura, str):
            continue
        if apertura <= adesso.strftime("%H:%M") < chiusura:
            return True
    return False


def stato_apertura_osm(opening_hours: str | None, adesso: datetime) -> bool | None:
    """Stato di apertura da una stringa `opening_hours` di OpenStreetMap, con la libreria di riferimento.

    `opening-hours-py` è la libreria indicata dal piano (§B3-SHM-04) e l'unica che interpreta la sintassi OSM reale
    (`Mo-Fr 09:00-13:00; PH off`, `sunrise-sunset`, …): una regex approssimativa direbbe «chiuso» su orari aperti.
    Una stringa non interpretabile non è un errore da dichiarare al chiamante: è un orario che non possiamo
    valutare, quindi `None`.
    """
    if not opening_hours:
        return None
    try:
        orari = OpeningHours(opening_hours)
    except (ParserError, ValueError):
        return None
    try:
        if orari.is_unknown(adesso):
            return None
        return orari.is_open(adesso)
    except Exception:  # pragma: no cover - la libreria può inciampare su sintassi esotiche
        return None


# --- Overpass -------------------------------------------------------------------------------------------------


@dataclass
class PoiOsm:
    """Un punto di interesse di OpenStreetMap, già normalizzato per il contratto dello shim."""

    node_id: int
    nome: str
    tipo: str
    indirizzo: str
    lat: float
    lon: float
    orari_testo: str | None
    aperto_adesso: bool | None
    orari_nota: str | None
    url: str | None


@dataclass
class EsitoOverpass:
    """L'esito del tentativo di interrogare Overpass: uno stato dichiarato, mai un'eccezione."""

    stato: str
    ms: int
    poi: list[PoiOsm] = field(default_factory=list)


def _url_elemento(elemento: str, identificativo: int) -> str:
    """L'URL pubblico dell'elemento OSM: è il `url` che l'operatore può aprire per verificare di persona."""
    return f"https://www.openstreetmap.org/{elemento}/{identificativo}"


def _elemento_a_poi(elemento: dict[str, Any], tipo: str, adesso: datetime) -> PoiOsm | None:
    """Un elemento della risposta Overpass → `PoiOsm`, o `None` se non ha coordinate utilizzabili."""
    tag = elemento.get("tags") or {}
    centro = elemento.get("center") or {}
    lat = elemento.get("lat", centro.get("lat"))
    lon = elemento.get("lon", centro.get("lon"))
    if lat is None or lon is None:
        return None

    orari_grezzi = tag.get("opening_hours")
    civico = " ".join(parte for parte in (tag.get("addr:street"), tag.get("addr:housenumber")) if parte)
    nome = tag.get("name") or tag.get("name:it") or ""
    elemento_osm = elemento.get("type", "node")

    return PoiOsm(
        node_id=int(elemento["id"]),
        nome=nome.strip() or NOME_SENZA_NOME,
        tipo=tipo,
        indirizzo=civico,
        lat=float(lat),
        lon=float(lon),
        # La stringa OSM è già leggibile da una persona (`Mo-Fr 09:00-13:00`): riscriverla sarebbe una traduzione
        # che può solo perdere informazione. Non si converte nella forma chiusa lun..dom della KB perché la sintassi
        # OSM è molto più espressiva (stagioni, festivi, `sunrise-sunset`) e una conversione approssimata
        # produrrebbe orari falsi.
        orari_testo=orari_grezzi,
        aperto_adesso=stato_apertura_osm(orari_grezzi, adesso),
        orari_nota=None if orari_grezzi else NOTA_ORARI_ASSENTI,
        url=_url_elemento(elemento_osm, int(elemento["id"])),
    )


def costruisci_query(tipo: str, lat: float, lon: float, raggio_m: int, *, tetto: int = TETTO_INTERROGAZIONE) -> str:
    """La query Overpass QL per un tipo del vocabolario.

    `nwr` e non `node`: un bar mappato come area è una way, e chiedere solo i nodi perderebbe POI reali. `center`
    fa restituire il centro anche per way e relation, così ogni elemento ha coordinate utilizzabili.
    """
    clausole = "\n".join(
        f'  nwr["{chiave}"="{valore}"](around:{raggio_m},{lat},{lon});' for chiave, valore in TIPI_OSM[tipo]
    )
    return f"[out:json][timeout:25];\n(\n{clausole}\n);\nout center {tetto};"


def _intestazioni(user_agent: str) -> dict[str, str]:
    """Le intestazioni di ogni chiamata a Overpass.

    Lo User-Agent identificativo è **obbligatorio** (403 senza, verificato in B0): è la ragione per cui non si usa il
    default di httpx. L'`Accept` esplicito evita di ricevere una pagina HTML di errore scambiata per JSON.
    """
    return {"User-Agent": user_agent, "Accept": "application/json"}


async def _chiama_overpass(
    query: str, indirizzo: str, timeout_s: float, user_agent: str
) -> tuple[str, list[dict[str, Any]]]:
    """Una singola chiamata a Overpass: ritorna (stato, elementi). Non solleva mai.

    Il tempo è imposto con `asyncio.wait_for`, non solo con il timeout di `httpx`: i timeout di `httpx` sono **per
    fase** (connessione, scrittura, lettura, pool), quindi un `timeout=5` può arrivare a 10 s sommando una
    connessione lenta a una lettura lenta — misurato: 6,3 s su una risposta reale, contro i 5 s dichiarati al
    chiamante. `wait_for` chiude il tentativo entro il budget, che è ciò che il contratto promette.

    Il client è creato per chiamata: è il prezzo di non avere stato condiviso fra richieste e fra cicli di eventi
    diversi (i test lo fanno), e su una risposta che può pesare centinaia di kB il costo del handshake è marginale.
    Un `timeout_s` a zero significa «budget esaurito»: si dichiara il timeout senza nemmeno aprire la connessione.
    """
    if timeout_s <= 0:
        return STATO_TIMEOUT, []

    async def tentativo() -> tuple[str, list[dict[str, Any]]]:
        async with httpx.AsyncClient(timeout=timeout_s, headers=_intestazioni(user_agent)) as client:
            risposta = await client.post(indirizzo, content=query.encode("utf-8"))
            risposta.raise_for_status()
            return STATO_OK, risposta.json().get("elements") or []

    try:
        return await asyncio.wait_for(tentativo(), timeout=timeout_s)
    except (TimeoutError, httpx.TimeoutException):
        return STATO_TIMEOUT, []
    except (httpx.HTTPError, ValueError):
        return STATO_ERRORE, []


async def interroga_overpass(
    tipo: str,
    lat: float,
    lon: float,
    raggio_m: int,
    *,
    indirizzo: str,
    timeout_s: int,
    user_agent: str,
    adesso: datetime,
    indirizzo_failover: str = "",
) -> EsitoOverpass:
    """I POI di un tipo entro il raggio, con lo stato del tentativo e la sua durata.

    Il tempo dichiarato (`OVERPASS_TIMEOUT_S=5`) è un **budget complessivo**, non un tempo per endpoint: con il
    failover configurato, dare 5 s a ciascuno porterebbe la risposta a oltre 10 s — misurato 12,9 s nel container —
    cioè il doppio di quanto il contratto dichiara al chiamante. Al secondo endpoint si passa quindi solo il tempo
    che resta, e se non ne resta si dichiara il timeout senza tentarlo.

    Il failover è tentato **solo** quando il primo non ha risposto: in B0 `overpass-api.de` ha risposto 504
    (`docs/verifiche.md` §1), quindi è trattato come instabile. Se il primo risponde `ok` — anche con zero elementi —
    il secondo non viene interrogato: zero POI è una risposta, non un guasto.
    """
    scadenza = time.monotonic() + timeout_s

    def rimanente() -> float:
        """Il tempo che resta nel budget dichiarato, mai negativo."""
        return max(0.0, scadenza - time.monotonic())

    inizio = time.monotonic()
    query = costruisci_query(tipo, lat, lon, raggio_m)
    stato, elementi = await _chiama_overpass(query, indirizzo, rimanente(), user_agent)

    if stato != STATO_OK and indirizzo_failover and rimanente() > 0:
        stato, elementi = await _chiama_overpass(query, indirizzo_failover, rimanente(), user_agent)

    ms = int((time.monotonic() - inizio) * 1000)
    if stato != STATO_OK:
        return EsitoOverpass(stato=stato, ms=ms)

    poi = [poi for elemento in elementi if (poi := _elemento_a_poi(elemento, tipo, adesso)) is not None]
    return EsitoOverpass(stato=STATO_OK, ms=ms, poi=poi)


async def nodo_osm(
    identificativo: int,
    *,
    indirizzo: str,
    timeout_s: int,
    user_agent: str,
    adesso: datetime,
    tipo: str = "",
) -> PoiOsm | None:
    """Un singolo elemento OSM per identificativo (`osm:node:<id>`), o `None`.

    Serve al biglietto per una destinazione esterna (`plan.md` §397: «Biglietto anche per destinazione esterna»).
    Ritorna `None` su assenza, timeout o errore — **mai** un'eccezione: chi chiama decide se il biglietto può
    esistere, e un POI non raggiungibile non deve far cadere l'endpoint.
    """
    query = f"[out:json][timeout:25];\nnode({identificativo});\nout;"
    stato, elementi = await _chiama_overpass(query, indirizzo, timeout_s, user_agent)
    if stato != STATO_OK or not elementi:
        return None
    return _elemento_a_poi(elementi[0], tipo, adesso)


# --- Composizione degli item del contratto -------------------------------------------------------------------


def rank_apertura(aperto_adesso: bool | None) -> int:
    """`true` → 0, `null` → 1, `false` → 2: l'ordine dichiarato dal contratto (`plan.md` §B3)."""
    if aperto_adesso is True:
        return 0
    if aperto_adesso is None:
        return 1
    return 2


def _stampa_ts(ts: datetime) -> str:
    """`consultato_ts` in ISO 8601 con fuso, come dichiarato dal contratto (`format: date-time`)."""
    return ts.isoformat()


def item_kb(
    riga: dict[str, Any],
    *,
    casa_lat: float,
    casa_lon: float,
    tipo: str,
    adesso: datetime,
) -> dict[str, Any]:
    """Un item del contratto a partire da una riga della memoria della rete.

    `fonte` è `fonte.autorita` quando c'è: le fonti del seed si chiamano «Rete-kb-3», dove il suffisso è il livello
    di fiducia, non parte del nome (vedi `badge.py`).
    """
    fonte = nome_fonte(riga["fonte_autorita"], riga["fonte_nome"])
    distanza = riga.get("distanza_m")
    if distanza is None:
        distanza = distanza_m(casa_lat, casa_lon, riga["lat"], riga["lon"])
    orari_testo = riga["orari_testo"]
    return {
        "provenienza": "kb",
        "nome": riga["nome"],
        "tipo": tipo,
        "indirizzo": riga["indirizzo"] or "",
        "lat": riga["lat"],
        "lon": riga["lon"],
        "distanza_m": round(float(distanza), 1),
        "aperto_adesso": riga["aperto_adesso"],
        "orari_testo": orari_testo,
        "orari_nota": None if orari_testo else NOTA_ORARI_ASSENTI,
        "fonte": fonte,
        "url": riga["url"],
        "data_aggiornamento": riga["data_aggiornamento"],
        "fiducia": riga["affidabilita"],
        "consultato_ts": _stampa_ts(adesso),
        "badge": badge_kb(fonte, riga["data_aggiornamento"], riga["affidabilita"]),
    }


def item_esterno(
    poi: PoiOsm,
    *,
    casa_lat: float,
    casa_lon: float,
    fonte: str,
    fiducia: int,
    tipo: str,
    adesso: datetime,
) -> dict[str, Any]:
    """Un item del contratto a partire da un POI esterno.

    `data_aggiornamento` è `None`: OpenStreetMap non dichiara una data di aggiornamento affidabile per l'elemento,
    e mettere la data di consultazione fingerebbe un aggiornamento che nessuno ha verificato.
    """
    return {
        "provenienza": "esterna",
        "nome": poi.nome,
        "tipo": tipo,
        "indirizzo": poi.indirizzo,
        "lat": poi.lat,
        "lon": poi.lon,
        "distanza_m": round(distanza_m(casa_lat, casa_lon, poi.lat, poi.lon), 1),
        "aperto_adesso": poi.aperto_adesso,
        "orari_testo": poi.orari_testo,
        "orari_nota": poi.orari_nota,
        "fonte": fonte,
        "url": poi.url,
        "data_aggiornamento": None,
        "fiducia": fiducia,
        "consultato_ts": _stampa_ts(adesso),
        "badge": badge_esterna(fonte, adesso),
    }


def ordina_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Ordina per gruppo (KB prima), poi apertura (`true` → `null` → `false`), poi distanza.

    L'ordinamento sta in un punto solo: la risposta `vicino_a` è la stessa lista sia con sia senza
    `aperto_adesso`, e due implementazioni finirebbero per divergere.
    """
    return sorted(
        items,
        key=lambda item: (
            0 if item["provenienza"] == "kb" else 1,
            rank_apertura(item["aperto_adesso"]),
            item["distanza_m"],
        ),
    )


# Parametri [P] usati da `vicino_a`, letti in una sola query (`db.parametri`).
CHIAVI_PARAMETRI = ("raggio_vicinanza_m", "fiducia_min_esterna", "max_risultati_esterni")

FUSO = ZoneInfo(FUSO_ITALIANO)


def adesso_locale() -> datetime:
    """L'istante corrente nel fuso di riferimento: «aperto adesso» è una domanda locale, non UTC."""
    return datetime.now(FUSO)


def oggi_locale() -> date:
    """La data locale: `eventi_oggi` con fuso Europe/Rome deve cambiare giorno a mezzanotte italiana."""
    return adesso_locale().date()


# --- Nominatim ------------------------------------------------------------------------------------------------

# La finestra geografica entro cui Nominatim cerca (`viewbox` = lon min, lat max, lon max, lat min; `bounded=1` la
# rende un vincolo e non una preferenza). Copre la provincia di Brindisi: «via Appia 120» esiste in decine di comuni
# italiani, e senza confine il primo risultato sarebbe plausibile e sbagliato — un dato inventato con l'aria di quello
# giusto, che è l'errore peggiore per uno strumento di sportello.
VIEWBOX_BRINDISI = "17.30,40.90,18.20,40.30"


@dataclass
class EsitoGeocodifica:
    """L'esito di una geocodifica: uno stato dichiarato, mai un'eccezione.

    `centro` è `None` sia quando la fonte non ha risposto (`stato` ≠ `ok`) sia quando ha risposto **che l'indirizzo non
    esiste** (`stato == "ok"`): il chiamante distingue i due casi dallo stato, perché il primo è un guasto della fonte da
    dichiarare in `fonti_esterne` e il secondo è un parametro sbagliato (422).
    """

    stato: str
    ms: int
    centro: dict[str, Any] | None = None


async def geocodifica(indirizzo: str, *, url: str, user_agent: str, timeout_s: float) -> EsitoGeocodifica:
    """`indirizzo` → `{lat, lon, etichetta}` con Nominatim, entro la viewbox di Brindisi. Non solleva mai (§9.1).

    `limit=1`: si prende il miglior risultato e lo si **mostra** (`etichetta` = `display_name`) invece di scegliere fra
    alternative — è l'operatore che riconosce se il posto è quello, e lo shim non deve fingere una certezza che non ha.
    Lo User-Agent identificativo è obbligatorio per la policy d'uso di Nominatim, come per Overpass. Il budget di tempo è
    imposto con `wait_for` per la stessa ragione di `_chiama_overpass`: i timeout di `httpx` sono per fase.
    """
    inizio = time.monotonic()
    parametri_ricerca = {
        "q": indirizzo,
        "format": "jsonv2",
        "limit": 1,
        "countrycodes": "it",
        "viewbox": VIEWBOX_BRINDISI,
        "bounded": 1,
    }

    async def tentativo() -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=timeout_s, headers=_intestazioni(user_agent)) as client:
            risposta = await client.get(f"{url.rstrip('/')}/search", params=parametri_ricerca)
            risposta.raise_for_status()
            corpo = risposta.json()
            return corpo if isinstance(corpo, list) else []

    try:
        risultati = await asyncio.wait_for(tentativo(), timeout=timeout_s)
    except (TimeoutError, httpx.TimeoutException):
        return EsitoGeocodifica(stato=STATO_TIMEOUT, ms=_trascorsi_ms(inizio))
    except (httpx.HTTPError, ValueError):
        return EsitoGeocodifica(stato=STATO_ERRORE, ms=_trascorsi_ms(inizio))

    ms = _trascorsi_ms(inizio)
    for risultato in risultati:
        try:
            centro = {
                "lat": float(risultato["lat"]),
                "lon": float(risultato["lon"]),
                "etichetta": str(risultato.get("display_name") or indirizzo),
            }
        except (KeyError, TypeError, ValueError):
            continue
        return EsitoGeocodifica(stato=STATO_OK, ms=ms, centro=centro)
    return EsitoGeocodifica(stato=STATO_OK, ms=ms)


def _trascorsi_ms(inizio: float) -> int:
    """I millisecondi trascorsi da `inizio` (`time.monotonic()`), come dichiarati in `fonti_esterne[].ms`."""
    return int((time.monotonic() - inizio) * 1000)
