"""Open data: `cerca_opendata` e `leggi_dataset`, i cataloghi CKAN in allow-list come strumenti dello shim.

Perché esistono. Il connettore `web` di Onyx non può indicizzare un'API: i portali open data (Regione Puglia,
dati.gov.it, IPRES) rispondono JSON a `package_search` e `datastore_search`, non pagine da leggere. Sono però la fonte
delle domande «quante strutture socio-assistenziali hanno sede a Brindisi?» o «qual è la popolazione per età?», che la
memoria della rete non copre e non deve inventare. Qui quei cataloghi diventano due strumenti **a richiesta**: il primo
trova i dataset, il secondo legge i record di una risorsa interrogabile.

Tre regole ereditate da `cerca_web` e da `vicino_a`, che valgono anche qui:

- **L'allow-list è `trasi.fonte`.** I portali sono le righe con `tipo_accesso='api'` e `attiva`, tolta quella di
  Nominatim (che è un geocodificatore, non un catalogo: la si riconosce dall'host di `settings.nominatim_url`). Il TI
  aggiunge un portale con una riga, senza deploy (§3, §11). Sotto `fiducia_min_esterna` il portale **non si
  interroga** e si dichiara `scartata_fiducia`.
- **Il guasto di una fonte non è un errore dello shim** (§9.1): timeout o errore di un portale si leggono in
  `fonti_esterne[].stato`, gli altri portali rispondono comunque, e il chiamante riceve 200.
- **Ogni item è etichettato** (V3): `provenienza: esterna`, `fonte`, `consultato_ts`, `fiducia` e il `badge` già
  composto da `badge_esterna`. Il LLM lo riporta, non lo ricompone.

Il log resta senza corpo: `q`, `campo` e `valore` non vengono registrati da questo modulo (il middleware di `main.py`
scrive solo `operationId`, stato e durata), perché una ricerca può contenere il nome di una persona.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

import httpx
from fastapi import APIRouter, Depends, FastAPI, Query

from .badge import badge_esterna, nome_fonte
from .contratto import prefisso_path
from .db import Sessione, sessione
from .errori import errore
from .settings import get_settings
from .testi import _argomenti, _fiducia_minima, _host, _tetto_risultati
from .vicinanza import STATO_ERRORE, STATO_OK, STATO_SCARTATA_FIDUCIA, STATO_TIMEOUT, adesso_locale

router = APIRouter()

# Il tetto assoluto dei record per chiamata a `leggi_dataset` (il contratto dichiara `maximum: 50`): una risposta più
# lunga non è leggibile in chat e il datastore la restituirebbe comunque a pagine.
MAX_RECORD = 50

# Quanti caratteri della descrizione di un dataset (`notes`) si riportano: le note CKAN sono spesso pagine intere.
LUNGHEZZA_DESCRIZIONE = 300

# Campi che un record del datastore porta per ragioni interne, non per chi lo legge: `_id` è la riga, `rank` e
# `_full_text` sono il motore di ricerca. Non vanno nel `testo` — direbbero al LLM cose che non riguardano il dato.
CAMPI_TECNICI = frozenset({"_id", "rank", "_full_text"})

# V5: le colonne che portano una **persona** — cognome e nome del legale rappresentante, codice fiscale — non
# escono dallo shim, come non entrano nella KB (`flussi/fonti_documenti.py`, `CAMPI_PERSONALI`: stessa espressione,
# stessa ragione). I registri regionali le hanno (`COGNOME_LEGALE`, `NOME_LEGALE`); il dato utile è la struttura,
# la sede e l'ente titolare, non chi la rappresenta. `nome` da solo non c'è: `nomeDelloSpazio` è il nome di un luogo.
CAMPI_PERSONALI = re.compile(r"cognome|nome_legale|codice_fiscale|cod_?fisc", re.IGNORECASE)

# Il titolo di un record: il primo di questi campi che ha un valore. L'ordine riflette le risorse reali verificate
# (registri regionali: `DENOMINAZIONE_SEDE_OP`; strutture socio-sanitarie: `DENOMINAZIONE`; punti di facilitazione:
# `nomeDelloSpazio`), poi le forme generiche.
CAMPI_TITOLO = (
    "DENOMINAZIONE_SEDE_OP",
    "DENOMINAZIONE",
    "DENOMINAZIONE_TITOLARE",
    "nomeDelloSpazio",
    "NOME",
    "nome",
    "TITOLO",
    "title",
)

# Le fonti con accesso `api`: i portali CKAN **e** Nominatim, che si separano in Python per host (vedi `e_nominatim`).
# Il nome umano è `autorita` quando c'è (il `nome` tecnico porta il suffisso di fiducia, es. «Open Data Puglia-3»).
SQL_FONTI_API = """
SELECT COALESCE(NULLIF(f.autorita, ''), f.nome) AS fonte, f.nome AS tecnica, f.url, f.livello_fiducia
  FROM trasi.fonte f
 WHERE f.tipo_accesso = 'api' AND f.attiva AND f.url IS NOT NULL AND f.url <> ''
"""


def monta(applicazione: FastAPI) -> None:
    """Monta le due operazioni sotto il prefisso del contratto (`/v1/u/{email}`), come `scritture` e `testi`."""
    applicazione.include_router(router, prefix=prefisso_path())


# --- Allow-list -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Portale:
    """Un catalogo CKAN in allow-list: nome umano, URL base dell'istanza, host e fiducia."""

    fonte: str
    url: str
    host: str
    fiducia: int

    def api(self, azione: str) -> str:
        """L'URL di un'azione dell'API CKAN v3 (`<base>/api/3/action/<azione>`)."""
        return f"{self.url}/api/3/action/{azione}"

    def pagina_dataset(self, nome: str) -> str:
        """La pagina pubblica di un dataset: è l'`url` che l'operatore può aprire per verificare."""
        return f"{self.url}/dataset/{nome}"


def host_portale(valore: str) -> str:
    """Un host come lo scrive il chiamante (`dati.puglia.it`, `https://www.dati.puglia.it/ckan`) → host normalizzato.

    `_host` accetta un URL; qui il parametro `portale` è un host nudo, che `urlparse` leggerebbe come percorso. Si
    antepone `//` quando manca lo schema, così le due forme danno lo stesso risultato e il confronto è per host.
    """
    testo = valore.strip()
    if not testo:
        return ""
    return _host(testo if "//" in testo else f"//{testo}")


def e_nominatim(url: str) -> bool:
    """La riga `api` è il geocodificatore e non un catalogo? Si decide per host, confrontando con la configurazione."""
    return _host(url) == _host(get_settings().nominatim_url)


async def fonti_api(sess: Sessione) -> list[dict[str, Any]]:
    """Le righe `api` attive di `trasi.fonte` (portali CKAN e Nominatim insieme), come dizionari."""
    return [dict(riga) for riga in await sess.fetch(SQL_FONTI_API)]


async def portali_allowlist(sess: Sessione) -> list[Portale]:
    """I portali CKAN in allow-list, per fiducia decrescente e poi per nome: il primo è il portale di default."""
    portali = [
        Portale(
            fonte=nome_fonte(riga["fonte"], riga["tecnica"]),
            url=riga["url"].rstrip("/"),
            host=_host(riga["url"]),
            fiducia=riga["livello_fiducia"],
        )
        for riga in await fonti_api(sess)
        if not e_nominatim(riga["url"]) and _host(riga["url"])
    ]
    return sorted(portali, key=lambda portale: (-portale.fiducia, portale.fonte))


# --- Chiamate CKAN --------------------------------------------------------------------------------------------


@dataclass
class EsitoCkan:
    """L'esito di un'azione CKAN: stato dichiarato, durata e il `result` della risposta (vuoto se non `ok`)."""

    stato: str
    ms: int
    result: dict[str, Any] = field(default_factory=dict)


async def _azione_ckan(portale: Portale, azione: str, parametri: dict[str, Any]) -> EsitoCkan:
    """`GET <base>/api/3/action/<azione>` con i parametri dati. Non solleva mai (§9.1).

    Il budget di tempo è `overpass_timeout_s` imposto con `wait_for`, per la stessa ragione di `_chiama_overpass`: i
    timeout di `httpx` sono per fase e un `timeout=5` può durare 10 s. Un `success: false` di CKAN (risorsa
    inesistente, filtro su una colonna che non c'è) è `errore`: la fonte ha risposto, ma non con un dato utilizzabile.
    """
    impostazioni = get_settings()
    inizio = time.monotonic()

    async def tentativo() -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=impostazioni.overpass_timeout_s,
            headers={"User-Agent": impostazioni.overpass_user_agent, "Accept": "application/json"},
            follow_redirects=True,
        ) as client:
            risposta = await client.get(portale.api(azione), params=parametri)
            risposta.raise_for_status()
            return risposta.json()

    try:
        corpo = await asyncio.wait_for(tentativo(), timeout=impostazioni.overpass_timeout_s)
    except (TimeoutError, httpx.TimeoutException):
        return EsitoCkan(stato=STATO_TIMEOUT, ms=_ms(inizio))
    except (httpx.HTTPError, ValueError):
        return EsitoCkan(stato=STATO_ERRORE, ms=_ms(inizio))

    ms = _ms(inizio)
    if not isinstance(corpo, dict) or not corpo.get("success") or not isinstance(corpo.get("result"), dict):
        return EsitoCkan(stato=STATO_ERRORE, ms=ms)
    return EsitoCkan(stato=STATO_OK, ms=ms, result=corpo["result"])


def _ms(inizio: float) -> int:
    """I millisecondi trascorsi da `inizio` (`time.monotonic()`)."""
    return int((time.monotonic() - inizio) * 1000)


def _voce_fonte(portale: Portale, stato: str, ms: int) -> dict[str, Any]:
    """Una voce di `fonti_esterne`, nella forma del contratto."""
    return {"fonte": portale.fonte, "stato": stato, "ms": ms}


# --- `cerca_opendata` -----------------------------------------------------------------------------------------


def _testo_o_none(valore: Any, *, massimo: int | None = None) -> str | None:
    """Una stringa ripulita, `None` se vuota; troncata a `massimo` caratteri con un'ellissi, se richiesto."""
    testo = " ".join(str(valore).split()) if valore is not None else ""
    if not testo:
        return None
    if massimo is not None and len(testo) > massimo:
        return testo[: massimo - 1].rstrip() + "…"
    return testo


def _risorsa(dati: dict[str, Any]) -> dict[str, Any] | None:
    """Una risorsa CKAN → `RisorsaOpenData`, o `None` se non ha identificativo o URL (non sarebbe né leggibile né citabile)."""
    identificativo = _testo_o_none(dati.get("id"))
    url = _testo_o_none(dati.get("url"))
    if not identificativo or not url:
        return None
    return {
        "id": identificativo,
        "nome": _testo_o_none(dati.get("name")),
        "formato": _testo_o_none(dati.get("format")),
        "url": url,
        "interrogabile": bool(dati.get("datastore_active")),
    }


def item_dataset(dati: dict[str, Any], portale: Portale, consultato) -> dict[str, Any] | None:
    """Un dataset di `package_search` → `ItemOpenData`, o `None` se non ha un nome (non avrebbe una pagina da citare).

    `aggiornato` è la sola data (`metadata_modified` è un timestamp ISO): al LLM serve dire «aggiornato a marzo 2026»,
    non l'ora. Le risorse restano nell'ordine del portale, che è quello della pagina del dataset.
    """
    nome = _testo_o_none(dati.get("name"))
    if not nome:
        return None
    organizzazione = dati.get("organization") or {}
    aggiornato = _testo_o_none(dati.get("metadata_modified"))
    return {
        "provenienza": "esterna",
        "titolo": _testo_o_none(dati.get("title")) or nome,
        "url": portale.pagina_dataset(nome),
        "descrizione": _testo_o_none(dati.get("notes"), massimo=LUNGHEZZA_DESCRIZIONE),
        "organizzazione": _testo_o_none(organizzazione.get("title")) if isinstance(organizzazione, dict) else None,
        "aggiornato": aggiornato[:10] if aggiornato else None,
        "portale": portale.host,
        "risorse": [
            risorsa for dati_risorsa in dati.get("resources") or [] if (risorsa := _risorsa(dati_risorsa)) is not None
        ],
        "fonte": portale.fonte,
        "consultato_ts": consultato.isoformat(),
        "fiducia": portale.fiducia,
        "badge": badge_esterna(portale.fonte, consultato),
    }


async def _cerca_su(portale: Portale, q: str, righe: int, consultato) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """`package_search` su un portale: (item, voce di `fonti_esterne`)."""
    esito = await _azione_ckan(portale, "package_search", {"q": q, "rows": righe})
    if esito.stato != STATO_OK:
        return [], _voce_fonte(portale, esito.stato, esito.ms)
    items = [
        item
        for dati in esito.result.get("results") or []
        if isinstance(dati, dict) and (item := item_dataset(dati, portale, consultato)) is not None
    ]
    return items, _voce_fonte(portale, STATO_OK, esito.ms)


@router.get(**_argomenti("cerca_opendata"))
async def cerca_opendata(
    q: str = Query(..., min_length=1),
    max: int | None = Query(default=None, ge=1),
    sess: Sessione = Depends(sessione),
) -> dict[str, Any]:
    """Cerca dataset in **tutti** i portali CKAN in allow-list, in parallelo, e li unisce per fiducia.

    In parallelo perché il budget di tempo dichiarato è uno solo (5 s): tre portali in sequenza costerebbero fino a
    15 s, e il contratto promette al chiamante il tempo di *una* fonte. Il tetto `rows` per portale è lo stesso tetto
    finale: chiedere di più a ogni portale per poi scartare non porta risultati migliori, perché l'ordine finale è
    per fiducia della fonte — non per pertinenza — e dentro una fonte i primi `tetto` sono già i più pertinenti.

    Ordine: fiducia decrescente, poi data di aggiornamento decrescente. Un dataset di una fonte fidata viene prima di
    uno più recente di una fonte meno fidata: è la scelta di V3 (l'autorevolezza prima della novità).
    """
    portali = await portali_allowlist(sess)
    if not portali:
        # Nessun catalogo in allow-list: non c'è nulla da interrogare e lo shim non inventa un risultato.
        return {"items": [], "fonti_esterne": []}

    tetto = await _tetto_risultati(sess, max)
    soglia = await _fiducia_minima(sess)
    consultato = adesso_locale()

    da_interrogare = [portale for portale in portali if portale.fiducia >= soglia]
    esiti = await asyncio.gather(*(_cerca_su(portale, q, tetto, consultato) for portale in da_interrogare))

    per_portale: dict[str, tuple[list[dict[str, Any]], dict[str, Any]]] = {
        portale.host: esito for portale, esito in zip(da_interrogare, esiti)
    }
    items: list[dict[str, Any]] = []
    fonti_esterne: list[dict[str, Any]] = []
    for portale in portali:
        if portale.host in per_portale:
            trovati, voce = per_portale[portale.host]
            items.extend(trovati)
            fonti_esterne.append(voce)
        else:
            fonti_esterne.append(_voce_fonte(portale, STATO_SCARTATA_FIDUCIA, 0))

    # `reverse=True` su (fiducia, aggiornato): fiducia decrescente, poi data decrescente, con i dataset senza data in
    # coda al proprio gruppo di fiducia ("" ordina dopo ogni data ISO in ordine inverso).
    ordinati = sorted(items, key=lambda item: (item["fiducia"], item["aggiornato"] or ""), reverse=True)
    return {"items": ordinati[:tetto], "fonti_esterne": fonti_esterne}


# --- `leggi_dataset` ------------------------------------------------------------------------------------------


def titolo_record(record: dict[str, Any]) -> str:
    """Il titolo di un record: il primo campo di denominazione con un valore, altrimenti `record <_id>`."""
    for campo in CAMPI_TITOLO:
        titolo = _testo_o_none(record.get(campo))
        if titolo:
            return titolo
    return f"record {record.get('_id', '?')}"


def testo_record(record: dict[str, Any]) -> str:
    """Tutti i campi non vuoti del record, esclusi quelli tecnici e quelli personali (V5), come `CAMPO: valore · …`.

    L'ordine è quello delle colonne della risorsa (i dizionari conservano l'ordine di inserimento del JSON): è
    l'ordine con cui l'ente ha pensato la tabella, e quello che l'operatore ritrova aprendo il CSV.
    """
    pezzi = []
    for campo, valore in record.items():
        if campo in CAMPI_TECNICI or CAMPI_PERSONALI.search(campo):
            continue
        testo = _testo_o_none(valore)
        if testo:
            pezzi.append(f"{campo}: {testo}")
    return " · ".join(pezzi)


def item_record(record: dict[str, Any], portale: Portale, consultato) -> dict[str, Any]:
    """Un record del datastore → `RecordDataset`, con badge e provenienza (V3)."""
    return {
        "provenienza": "esterna",
        "titolo": titolo_record(record),
        "testo": testo_record(record),
        "fonte": portale.fonte,
        "consultato_ts": consultato.isoformat(),
        "fiducia": portale.fiducia,
        "badge": badge_esterna(portale.fonte, consultato),
    }


def _portale_richiesto(portali: list[Portale], richiesto: str | None) -> Portale:
    """Il portale da interrogare: quello indicato (per host) o, se omesso, il primo — cioè il più fidato.

    Un host fuori allow-list è 422 con l'elenco ammesso: il LLM può correggersi con un valore che funziona, mentre
    una lista vuota gli farebbe credere che il dataset non ha record.
    """
    if not richiesto or not richiesto.strip():
        return portali[0]
    host = host_portale(richiesto)
    for portale in portali:
        if portale.host == host:
            return portale
    raise errore(
        422,
        "parametri non ammessi — portale: valori ammessi " + ", ".join(portale.host for portale in portali),
    )


@router.get(**_argomenti("leggi_dataset"))
async def leggi_dataset(
    risorsa_id: str = Query(..., min_length=1),
    portale: str | None = Query(default=None, min_length=1),
    q: str | None = Query(default=None, min_length=1),
    campo: str | None = Query(default=None, min_length=1),
    valore: str | None = Query(default=None, min_length=1),
    max: int | None = Query(default=None, ge=1, le=MAX_RECORD),
    sess: Sessione = Depends(sessione),
) -> dict[str, Any]:
    """I record di una risorsa interrogabile (`datastore_search`) di **un** portale, resi leggibili come testo.

    Almeno un criterio è obbligatorio — `q` oppure la coppia `campo`/`valore` — perché una lettura senza criterio
    restituirebbe le prime righe di una tabella da migliaia di record: non è una risposta, è un campione casuale che
    il LLM presenterebbe come «i dati». La coppia va insieme: un `campo` senza `valore` non è un filtro.

    `totale` è `result.total` del datastore, cioè quanti record corrispondono **sul portale**, non quanti sono
    tornati: è il numero che permette di dire «95 strutture, ne mostro 5» invece di «5 strutture».
    """
    filtro_completo = bool(campo) and bool(valore)
    if bool(campo) != bool(valore):
        raise errore(422, "parametri non ammessi — campo e valore vanno indicati insieme")
    if not q and not filtro_completo:
        raise errore(422, "parametri non ammessi — indicare q oppure campo e valore")

    portali = await portali_allowlist(sess)
    if not portali:
        return {"items": [], "totale": None, "fonti_esterne": []}
    scelto = _portale_richiesto(portali, portale)

    soglia = await _fiducia_minima(sess)
    if scelto.fiducia < soglia:
        return {"items": [], "totale": None, "fonti_esterne": [_voce_fonte(scelto, STATO_SCARTATA_FIDUCIA, 0)]}

    limite = min(max or await _tetto_risultati(sess, None), MAX_RECORD)
    parametri_ricerca: dict[str, Any] = {"resource_id": risorsa_id, "limit": limite}
    if q:
        parametri_ricerca["q"] = q
    if filtro_completo:
        parametri_ricerca["filters"] = json.dumps({campo: valore}, ensure_ascii=False)

    consultato = adesso_locale()
    esito = await _azione_ckan(scelto, "datastore_search", parametri_ricerca)
    if esito.stato != STATO_OK:
        return {"items": [], "totale": None, "fonti_esterne": [_voce_fonte(scelto, esito.stato, esito.ms)]}

    records = [record for record in esito.result.get("records") or [] if isinstance(record, dict)]
    totale = esito.result.get("total")
    return {
        "items": [item_record(record, scelto, consultato) for record in records[:limite]],
        "totale": totale if isinstance(totale, int) and totale >= 0 else None,
        "fonti_esterne": [_voce_fonte(scelto, STATO_OK, esito.ms)],
    }


__all__ = [
    "Portale",
    "cerca_opendata",
    "e_nominatim",
    "fonti_api",
    "host_portale",
    "item_dataset",
    "item_record",
    "leggi_dataset",
    "monta",
    "portali_allowlist",
    "router",
    "testo_record",
    "titolo_record",
]
