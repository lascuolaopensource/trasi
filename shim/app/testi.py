"""Output: `biglietto`, `oggi`, `cerca_web` (B3-SHM-07/08/12) e la scheda evento dell'area operatore (US-1.3).

Tre endpoint che non scrivono nulla e che condividono una sola idea: **ciò che esce è già pronto per essere usato**.
Il biglietto è HTML A6 da stampare senza dati del cittadino; la riga «Oggi» è il testo della Home composto dalla
vista; `cerca_web` restituisce solo risultati di fonti in allow-list, ognuno con il badge già formato.

La **scheda evento** (`GET /op/scheda_evento`, in coda) è il quarto foglio, e sta fuori dal contratto congelato per
una ragione di canale, non di formato: la chiama il browser dell'operatore con il cookie di sessione, non Onyx con la
chiave dello shim. Stessa pipeline e stessi divieti del biglietto — un solo costruttore di pagina (`_foglio`) per
entrambi, così le regole di stampa e i divieti non possono divergere fra i due fogli.

**`cerca_web` — la ragione per cui esiste.** Il gate V-07 è **negativo**: la ricerca web nativa di Onyx v4.7.2 espone
solo `queries` e non ha alcuna restrizione per dominio (`plan.md` §0.3). Lo shim interroga SearXNG interno e **filtra
lui** i risultati: si scarta ogni URL il cui host non sia fra i domini di `fonte WHERE tipo_accesso='web' AND attiva`.
Su query reali questo significa spesso `items: []` — verificato dal coordinatore: i primi risultati di «CAF Brindisi»
sono `paginegialle.it` e `paginebianche.it`, fuori allow-list. **È il comportamento corretto** (V3: solo fonti
autorevoli), e si dichiara con la `nota` invece di allentare il filtro.

Il confronto è per **host**, non per sottostringa: `inps.it` non deve autorizzare `falso-inps.it.example`, e
`comune.brindisi.it` deve autorizzare `www.comune.brindisi.it` (il `www.` è lo stesso host, non un altro dominio).
"""

from __future__ import annotations

import html
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, FastAPI, Query
from fastapi.responses import HTMLResponse

from .auth import SessioneOperatore, sessione_corrente
from .badge import NOTA_ORARI_ASSENTI, badge_esterna, badge_kb, nome_fonte
from .contratto import prefisso_path
from .db import Sessione, parametri, parametro_int, sessione, slug_casa_da_identita
from .errori import errore
from .operazioni import dichiarazione
from .settings import get_settings
from .vicinanza import (
    FUSO,
    STATO_ERRORE,
    STATO_OK,
    STATO_SCARTATA_FIDUCIA,
    STATO_TIMEOUT,
    adesso_locale,
    distanza_m,
    nodo_osm,
)

# Due router, perché due sono i canali. `router` è la via di Onyx (chiave `X-Trasi-Key`, email nel
# percorso, contratto congelato); `router_op` è la via del browser dell'operatore (cookie di sessione,
# nessun identificatore nell'URL) e viene montato sotto `/op`. La distinzione non è formale: tenendo i
# due router separati, nessuna route può essere valida per entrambi i canali, e la scheda evento — che
# è per il browser — non entra nell'OpenAPI che il gate V-09 confronta con le nove operazioni.
router = APIRouter()
router_op = APIRouter()

# Nome della fonte esterna interrogata da `cerca_web`, come compare in `fonti_esterna[].fonte`.
MOTORE_WEB = "SearXNG"

# Sorgente dei POI esterni nel biglietto: la riga di `trasi.fonte` con `tipo_accesso='osm_overpass'`.
TIPO_ACCESSO_OSM = "osm_overpass"

# Sorgente degli eventi importati da un calendario esterno: l'unica scrittura automatica ammessa su
# `evento` (§8 F4). È il discriminante del badge V3: `ical` → `[Esterna …]`, tutto il resto (fonte
# della rete, o nessuna fonte = inserimento a mano) → `[KB …]`.
TIPO_ACCESSO_ICAL = "ical"


def monta(applicazione: FastAPI) -> None:
    """Monta le route degli output sotto il prefisso del contratto (`/v1/u/{email}`) e la scheda evento sotto `/op`.

    Due prefissi perché i canali sono due: il contratto congelato per Onyx e `/op` per il browser
    dell'operatore. `include_in_schema=False` sulla seconda è ciò che tiene la scheda fuori dall'OpenAPI
    dell'applicazione — che per il gate V-09 è il contratto con Onyx, e che deve esporre esattamente le
    nove `operationId` congelate.
    """
    applicazione.include_router(router, prefix=prefisso_path())
    applicazione.include_router(router_op, prefix="/op", include_in_schema=False)


def _argomenti(operation_id: str) -> dict[str, Any]:
    """Gli argomenti del decoratore, letti dal contratto congelato."""
    dati = dichiarazione(operation_id)
    return {
        "path": dati["path"],
        "operation_id": dati["operation_id"],
        "summary": dati["summary"],
        "tags": dati["tags"],
        "responses": dati["responses"],
    }


# --- `oggi` ---------------------------------------------------------------------------------------------------

# La riga «Oggi» di una Casa, dai dati della vista. Una sola query, usata sia per verificare che la
# Casa esista sia per comporre la risposta: due query sarebbero due posti da tenere allineati, e il
# caso in cui divergono è quello in cui l'endpoint risponde su una Casa che non esiste.
#
# Il filtro «solo la propria Casa» sta **nella query** e usa `trasi.casa_corrente()`, la stessa
# funzione da cui la RLS ricava la Casa del ruolo: per un operatore `casa_*` è la sua Casa, per
# `rete` e `ti` (che non ne hanno una) è `NULL`, quindi vedono tutte le Case (§11). La decisione
# resta del database, non di un confronto fatto dallo shim.
SQL_OGGI = """
SELECT casa_id, slug, nome, data, eventi, schede_in_scadenza, proposte, giorni_piu_vecchia, testo
  FROM trasi.v_oggi_casa
 WHERE slug = $1
   AND (trasi.casa_corrente() IS NULL OR casa_id = trasi.casa_corrente())
"""



@router.get(**_argomenti("oggi"))
async def oggi(
    casa: str | None = Query(default=None, description="Slug della Casa; se omesso, quella dell'operatore."),
    sess: Sessione = Depends(sessione),
) -> dict[str, Any]:
    """La riga «Oggi» della Casa, dalla vista `v_oggi_casa`.

    Il `testo` arriva **già composto dalla vista** («Oggi a San Bao: 2 eventi · 1 scheda in scadenza · 3 proposte»):
    ricomporlo in Python significherebbe due formattazioni da tenere allineate, e la vista è la stessa che alimenta
    la Home statica — quindi la chat e la Home non possono dire numeri diversi.

    `giorni_piu_vecchia` è l'età della proposta più vecchia in attesa, calcolata dalla vista: dice *da quanto* la coda
    è ferma, dove `proposte` dice solo *quante* ce ne sono. Vale `0` (mai `null`) quando la coda è vuota, così il
    consumatore può usarlo come booleano.

    La vista è `security_invoker=false`, cioè gira con i privilegi del proprietario: **la RLS non limita le righe che
    restituisce**, e tutte le dieci Case sarebbero leggibili da qualunque ruolo. Il filtro «solo la propria Casa» sta
    quindi nella query e usa `trasi.casa_corrente()`, la stessa funzione da cui la RLS ricava la Casa del ruolo: per
    un operatore `casa_*` è la sua Casa, per `rete` e `ti` (che non ne hanno una) è `NULL` — vedono tutte le Case,
    come dice §11. La decisione resta del database, non di un confronto fatto dallo shim.
    """
    slug = (casa or "").strip() or await slug_casa_da_identita(sess)
    if not slug:
        raise errore(422, "casa: obbligatoria per un ruolo senza Casa (es. rete)")

    # Una sola lettura. Uno slug inesistente non è un errore quando l'operatore ha una Casa propria:
    # il modello, vedendo `casa` nel contratto, tende a riempirlo con il nome invece dello slug (v.
    # la nota nell'helper), e un 422 farebbe dichiarare all'assistente un guasto che non esiste.
    riga = await sess.fetchrow(SQL_OGGI, slug)
    if riga is None:
        slug_identita = await slug_casa_da_identita(sess)
        if slug_identita and slug_identita != slug:
            riga = await sess.fetchrow(SQL_OGGI, slug_identita)
    if riga is None:
        raise errore(404, "Casa non presente fra quelle accessibili a questo ruolo")

    return {
        "casa": riga["slug"],
        "eventi": riga["eventi"],
        "schede_in_scadenza": riga["schede_in_scadenza"],
        "proposte": riga["proposte"],
        "giorni_piu_vecchia": riga["giorni_piu_vecchia"],
        "testo": riga["testo"],
    }


# --- `biglietto` ----------------------------------------------------------------------------------------------


def _voce(etichetta: str, valore: str | None) -> str:
    """Una riga del biglietto, omessa interamente quando il valore manca: meglio niente che «None» su carta."""
    if not valore or not valore.strip():
        return ""
    return (
        f'      <tr><th scope="row">{html.escape(etichetta)}</th>'
        f"<td>{html.escape(valore)}</td></tr>\n"
    )


def _arrivo(distanza: float | None, casa_nome: str | None, indirizzo: str | None) -> str:
    """«Come arrivare»: la distanza dalla Casa di riferimento e l'indirizzo del luogo.

    Non è un itinerario — lo shim non calcola percorsi e non deve inventarne uno. Dice la distanza in linea d'aria e
    l'indirizzo: sono i due dati che l'operatore legge al telefono, ed entrambi sono verificabili.
    """
    pezzi: list[str] = []
    if indirizzo:
        pezzi.append(indirizzo)
    if distanza is not None and casa_nome:
        pezzi.append(f"a circa {_metri(distanza)} dalla Casa {casa_nome} (distanza in linea d'aria)")
    return " — ".join(pezzi)


def _metri(valore: float) -> str:
    """`840 m` oppure `2,1 km`: la forma che una persona legge ad alta voce."""
    if valore < 1000:
        return f"{round(valore)} m"
    return f"{valore / 1000:.1f}".replace(".", ",") + " km"


def _foglio(
    *,
    titolo: str,
    intestazione: str,
    formato: str,
    larghezza: str,
    badge: str,
    righe: str,
    didascalia: str | None,
    fonte: str,
    consultato: datetime,
    nota: str,
) -> str:
    """La pagina stampabile: testa, stile, tabella e piè di pagina. Il guscio di **ogni** foglio dello shim.

    Un guscio solo per il biglietto e per la scheda evento, e non è una questione di righe risparmiate: i due fogli
    condividono i **divieti** — niente `<form>`, niente `<input>`, niente campi compilabili — e le regole di stampa.
    Con lo stile in due copie, una correzione ai margini o a `@page` arriverebbe a un foglio e non all'altro, e il
    divieto resterebbe verificato su uno solo dei due. Chi aggiunge un terzo foglio eredita gli stessi vincoli.

    Ogni valore interpolato passa da `html.escape` (qui il titolo, il badge, la fonte; nelle righe, `_voce`): i dati
    arrivano da OpenStreetMap, dai calendari delle Case e dalla memoria — fonti che non controlliamo — e un `<` in un
    titolo non deve rompere il documento. Il piè di pagina dichiara che il foglio non contiene dati personali: è
    un'affermazione su ciò che **non** c'è, non un campo da compilare.
    """
    caption = f'\n    <caption class="luogo">{html.escape(didascalia)}</caption>' if didascalia else ""
    return f"""<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <title>{html.escape(titolo)}</title>
  <style>
    @page {{ size: {formato}; margin: 8mm }}
    @media print {{ body {{ margin: 0 }} .no-print {{ display: none }} }}
    :root {{ color-scheme: light }}
    body {{ font-family: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
            font-size: 10pt; line-height: 1.35; color: #14181f; margin: 8mm; max-width: {larghezza} }}
    h1 {{ font-size: 14pt; margin: 0 0 .4rem; line-height: 1.2 }}
    .badge {{ font-size: 8pt; color: #3d4756; border: 1px solid #c8cfd9; border-radius: 3px;
              padding: .15rem .35rem; display: inline-block; margin-bottom: .5rem }}
    table {{ border-collapse: collapse; width: 100% }}
    th, td {{ text-align: left; vertical-align: top; padding: .18rem .3rem .18rem 0 }}
    th {{ font-weight: 600; width: 32%; color: #3d4756 }}
    footer {{ margin-top: .6rem; font-size: 8pt; color: #3d4756; border-top: 1px solid #c8cfd9; padding-top: .3rem }}
    .luogo {{ font-weight: 600 }}
    .nota {{ font-size: 8pt; color: #3d4756; margin-top: .4rem }}
  </style>
</head>
<body>
  <h1>{html.escape(intestazione)}</h1>
  <p class="badge">{html.escape(badge)}</p>
  <table>{caption}
    <tbody>
{righe}    </tbody>
  </table>
  <footer>
    Fonte: {html.escape(fonte)} · consultato il {consultato.strftime('%d/%m/%Y')} alle {consultato.strftime('%H:%M')}
    <p class="nota">{html.escape(nota)}</p>
  </footer>
</body>
</html>
"""


def _documento_biglietto(
    *,
    nome: str,
    indirizzo: str,
    orari_testo: str | None,
    orari_nota: str | None,
    come_arrivare: str,
    fonte: str,
    badge: str,
    consultato: datetime,
    tipo: str,
) -> str:
    """Il biglietto: una pagina A6, senza moduli e senza campi del cittadino (§4.4, §12), dal guscio `_foglio`."""
    orari = orari_testo or ""
    nota = orari_nota or (NOTA_ORARI_ASSENTI if not orari else "")
    righe = "".join(
        [
            _voce("Indirizzo", indirizzo),
            _voce("Orari", orari),
            _voce("Nota orari", nota),
            _voce("Come arrivare", come_arrivare),
            _voce("Tipo", tipo),
        ]
    )
    return _foglio(
        titolo=f"{nome} — biglietto",
        intestazione=nome,
        formato="A6",
        larghezza="105mm",
        badge=badge,
        righe=righe,
        didascalia=nome,
        fonte=fonte,
        consultato=consultato,
        nota="Questo foglio è una indicazione di luogo: non contiene dati personali e non è un modulo da compilare.",
    )


async def _luogo_kb(sess: Sessione, luogo_id: int) -> dict[str, Any] | None:
    """Un luogo della memoria della rete, con fonte e orari leggibili.

    La distanza dalla Casa di riferimento si calcola in Python (`vicinanza.distanza_m`): portare la Casa nella query
    servirebbe una seconda join solo per un valore che è già tutto in memoria.
    """
    return await sess.fetchrow(
        """
        SELECT l.id, l.nome, l.tipo, COALESCE(l.indirizzo, '') AS indirizzo,
               COALESCE(l.note_accesso, '') AS note_accesso,
               st_y(l.geom::geometry) AS lat, st_x(l.geom::geometry) AS lon,
               trasi.orari_testo(l.orari) AS orari_testo,
               l.data_aggiornamento, l.affidabilita, l.url, l.ext_ref,
               f.autorita AS fonte_autorita, f.nome AS fonte_tecnica,
               c.slug AS casa_slug, c.nome AS casa_nome
          FROM trasi.luogo l
          LEFT JOIN trasi.fonte f ON f.id = l.fonte_id
          LEFT JOIN trasi.casa c ON c.id = l.casa_id
         WHERE l.id = $1
        """,
        luogo_id,
    )


async def _casa_riferimento(sess: Sessione, slug: str | None) -> dict[str, Any] | None:
    """La Casa da cui misurare la distanza nel biglietto (facoltativa: l'operatore può indicarne una)."""
    if not slug:
        return None
    return await sess.fetchrow(
        "SELECT id, slug, nome, st_y(geom::geometry) AS lat, st_x(geom::geometry) AS lon FROM trasi.casa WHERE slug = $1",
        slug,
    )


def _identificativo_osm(valore: str) -> int | None:
    """`osm:node:123456` (o `osm:way:…`) → identificativo, se la forma è quella attesa.

    Il contratto dichiara `luogo_id` come intero, ma il piano (§397) chiede il biglietto anche per una destinazione
    esterna, che nel modello dati vive come `ext_ref` testuale `osm:node:…` e non ha un `id` in `luogo`. Accettare
    la forma testuale **sullo stesso parametro** è la soluzione che non cambia il contratto congelato: un valore non
    numerico che non sia `osm:<tipo>:<id>` è un 422, come dichiarato.
    """
    parti = valore.split(":")
    if len(parti) == 3 and parti[0] == "osm" and parti[1] in ("node", "way", "relation"):
        try:
            return int(parti[2])
        except ValueError:
            return None
    return None


@router.get(**_argomenti("biglietto"), response_class=HTMLResponse)
async def biglietto(
    luogo_id: str = Query(..., min_length=1),
    casa: str | None = Query(default=None, min_length=1),
    sess: Sessione = Depends(sessione),
) -> HTMLResponse:
    """Il biglietto stampabile (A6) del luogo scelto: `text/html`, l'unica risposta non JSON del contratto.

    Due origini, un solo foglio: un luogo della memoria della rete (badge `[KB …]`) o un POI esterno indicato come
    `osm:node:<id>` (badge `[Esterna …]`, ricaricato da Overpass). Nel secondo caso il POI **non viene scritto** in
    `luogo` — lo shim non scrive il dominio (V4): il foglio serve a indicare la destinazione, e la promozione in
    memoria resta una proposta.
    """
    riferimento = await _casa_riferimento(sess, casa)
    consultato = adesso_locale()

    identificativo = _identificativo_osm(luogo_id)
    if identificativo is None:
        if not luogo_id.isdigit():
            raise errore(
                422,
                "luogo_id deve essere un identificativo numerico di luogo oppure un riferimento esterno «osm:node:<id>»",
            )
        riga = await _luogo_kb(sess, int(luogo_id))
        if riga is None:
            raise errore(404, "luogo non presente nella memoria della rete")

        fonte = nome_fonte(riga["fonte_autorita"], riga["fonte_tecnica"])
        distanza = None
        if riferimento is not None and riga["lat"] is not None and riferimento["lat"] is not None:
            distanza = distanza_m(riferimento["lat"], riferimento["lon"], riga["lat"], riga["lon"])
        arrivo = _arrivo(
            distanza,
            riferimento["nome"] if riferimento else None,
            riga["indirizzo"] or riga["note_accesso"],
        )
        return HTMLResponse(
            _documento_biglietto(
                nome=riga["nome"],
                indirizzo=riga["indirizzo"],
                orari_testo=riga["orari_testo"],
                orari_nota=None if riga["orari_testo"] else NOTA_ORARI_ASSENTI,
                come_arrivare=arrivo,
                fonte=fonte,
                badge=badge_kb(fonte, riga["data_aggiornamento"], riga["affidabilita"]),
                consultato=consultato,
                tipo=riga["tipo"],
            )
        )

    config = await _configurazione_osm(sess)
    poi = await nodo_osm(
        identificativo,
        indirizzo=config["url"],
        timeout_s=config["timeout_s"],
        user_agent=config["user_agent"],
        adesso=consultato,
    )
    if poi is None:
        raise errore(404, "POI esterno non raggiungibile su OpenStreetMap")

    fonte = config["fonte"]
    distanza = (
        distanza_m(riferimento["lat"], riferimento["lon"], poi.lat, poi.lon)
        if riferimento is not None and riferimento["lat"] is not None
        else None
    )
    return HTMLResponse(
        _documento_biglietto(
            nome=poi.nome,
            indirizzo=poi.indirizzo,
            orari_testo=poi.orari_testo,
            orari_nota=poi.orari_nota,
            come_arrivare=_arrivo(distanza, riferimento["nome"] if riferimento else None, poi.indirizzo),
            fonte=fonte,
            badge=badge_esterna(fonte, consultato),
            consultato=consultato,
            tipo=poi.tipo or "luogo esterno",
        )
    )


async def _configurazione_osm(sess: Sessione) -> dict[str, Any]:
    """URL, timeout, User-Agent e nome della fonte OSM, dalla configurazione e da `trasi.fonte`."""
    impostazioni = get_settings()
    riga = await sess.fetchrow(
        "SELECT COALESCE(NULLIF(autorita, ''), nome) AS fonte FROM trasi.fonte WHERE tipo_accesso = $1 LIMIT 1",
        TIPO_ACCESSO_OSM,
    )
    return {
        "url": impostazioni.overpass_url,
        "timeout_s": impostazioni.overpass_timeout_s,
        "user_agent": impostazioni.overpass_user_agent,
        "fonte": nome_fonte(riga["fonte"] if riga else None, "OpenStreetMap"),
    }


# --- `cerca_web` ----------------------------------------------------------------------------------------------


def _host(url: str) -> str:
    """L'host di un URL, senza porta e senza `www.` di prefisso, in minuscolo.

    `www.comune.brindisi.it` e `comune.brindisi.it` sono lo stesso servizio: trattarli come due domini diversi
    scarterebbe risultati legittimi. Il `www.` è l'unica normalizzazione applicata — non si toccano i sottodomini
    veri (`sportello.comune.brindisi.it` resta un host diverso e va autorizzato esplicitamente).
    """
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def _in_allowlist(url: str, domini: tuple[str, ...]) -> bool:
    """Vero se l'host dell'URL è in allow-list, per uguaglianza o come sottodominio di un dominio autorizzato.

    Il confronto è **per etichetta di dominio** e non per sottostringa: `falso-inps.it.example` non è autorizzato da
    `inps.it`, e `inps.it.example` nemmeno. Un dominio in allow-list autorizza i propri sottodomini, che è il
    comportamento dichiarato da V3 (il TI autorizza un ente, non un singolo host).
    """
    host = _host(url)
    if not host:
        return False
    return any(host == dominio or host.endswith("." + dominio) for dominio in domini)


async def _dominio_allowlist(sess: Sessione) -> dict[str, dict[str, Any]]:
    """I domini ammessi da `fonte WHERE tipo_accesso='web' AND attiva`, indicizzati per host.

    Fonte unica dell'allow-list: la tabella `fonte`, che il TI amplia con una riga senza deploy (§3, §11). Le fonti
    senza `url` non contribuiscono domini (sono gli ETS non ancora verificati).
    """
    righe = await sess.fetch(
        """
        SELECT COALESCE(NULLIF(f.autorita, ''), f.nome) AS fonte, f.url, f.livello_fiducia, f.nome AS tecnica
          FROM trasi.fonte f
         WHERE f.tipo_accesso = 'web' AND f.attiva AND f.url IS NOT NULL AND f.url <> ''
        """
    )
    domini: dict[str, dict[str, Any]] = {}
    for riga in righe:
        dominio = _host(riga["url"])
        if dominio:
            domini[dominio] = {
                "fonte": nome_fonte(riga["fonte"], riga["tecnica"]),
                "fiducia": riga["livello_fiducia"],
            }
    return domini


def _fonte_per(url: str, domini: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """La fonte che autorizza un URL: l'host esatto, o il dominio più specifico fra quelli che lo contengono."""
    host = _host(url)
    if not host:
        return None
    candidati = [
        (dominio, dati)
        for dominio, dati in domini.items()
        if host == dominio or host.endswith("." + dominio)
    ]
    if not candidati:
        return None
    # Il dominio più lungo è il più specifico: `questure.poliziadistato.it` batte `poliziadistato.it`.
    return max(candidati, key=lambda voce: len(voce[0]))[1]


async def _interroga_searxng(url: str, query: str, timeout_s: int) -> tuple[str, list[dict[str, Any]], int]:
    """Una ricerca su SearXNG: ritorna (stato, risultati, ms). Non solleva mai (§9.1)."""
    inizio = datetime.now()
    try:
        async with httpx.AsyncClient(timeout=timeout_s, headers={"Accept": "application/json"}) as client:
            risposta = await client.get(url, params={"q": query, "format": "json"})
            risposta.raise_for_status()
            risultati = risposta.json().get("results") or []
    except httpx.TimeoutException:
        return STATO_TIMEOUT, [], _ms(inizio)
    except (httpx.HTTPError, ValueError):
        return STATO_ERRORE, [], _ms(inizio)
    return STATO_OK, risultati, _ms(inizio)


def _ms(inizio: datetime) -> int:
    """La durata in millisecondi di un tentativo, come dichiarata in `fonti_esterne[].ms`."""
    return int((datetime.now() - inizio).total_seconds() * 1000)


@router.get(**_argomenti("cerca_web"))
async def cerca_web(
    q: str = Query(..., min_length=1),
    max: int | None = Query(default=None, ge=1),
    sess: Sessione = Depends(sessione),
) -> dict[str, Any]:
    """Ricerca web **solo** su fonti in allow-list (V-07 negativo: la restrizione è dello shim, non del motore).

    Ordine deliberato delle operazioni: prima l'allow-list dal database, poi la query al motore, poi il filtro, poi il
    tetto. Filtrare *dopo* è l'unico modo di poter dire, con onestà, quanti risultati sono stati scartati — e di non
    dover chiedere al motore una restrizione di dominio (`site:`) che dipenderebbe dal motore stesso.

    Un motore che non risponde **non** è un errore dello shim: si risponde **200** con `items: []` e lo stato
    dichiarato in `fonti_esterne` (`timeout`, `errore`), come prescrive §9.1 — mai un'eccezione al chiamante.

    **Nota sul campo `nota` del piano.** `.specs/B3-shim.md` §6 chiede `{"items":[], "nota":"nessuna fonte ha
    risposto"}`, ma il contratto congelato dichiara `RispostaCercaWeb` con `additionalProperties: false` e le sole
    proprietà `items` e `fonti_esterne`: un campo `nota` renderebbe la risposta **non conforme allo schema** che Onyx
    ha registrato come tool `trasi_shim`. Il conflitto è reale e la scelta è dichiarata, non silenziosa: il contratto è
    congelato (V-09) e il piano dice di **fermarsi e segnalare** invece di modificarlo, quindi l'informazione «nessuna
    fonte ha risposto» viaggia nei campi che il contratto prevede — `items: []` più
    `fonti_esterne[].stato`, che è esattamente lo stato della fonte. Se il PM/TI vuole il campo `nota`, va aggiunto al
    contratto con B2 (una riga) e poi qui: è una modifica al contratto, non all'implementazione.
    """
    impostazioni = get_settings()
    domini = await _dominio_allowlist(sess)
    tetto = await _tetto_risultati(sess, max)

    stato, risultati, ms = await _interroga_searxng(
        f"{impostazioni.searxng_url.rstrip('/')}/search", q, impostazioni.overpass_timeout_s
    )
    if stato != STATO_OK:
        return {"items": [], "fonti_esterne": [{"fonte": MOTORE_WEB, "stato": stato, "ms": ms}]}

    # `consultato_ts` è uno solo per l'intera risposta: è l'istante della consultazione, non quello di ogni riga.
    consultato = adesso_locale()
    items: list[dict[str, Any]] = []
    for risultato in risultati:
        url = risultato.get("url") or ""
        sorgente = _fonte_per(url, domini)
        if sorgente is None:
            continue
        items.append(
            {
                "provenienza": "esterna",
                "titolo": (risultato.get("title") or "").strip() or url,
                "url": url,
                "estratto": (risultato.get("content") or "").strip() or None,
                "fonte": sorgente["fonte"],
                "consultato_ts": consultato.isoformat(),
                "fiducia": sorgente["fiducia"],
                "badge": badge_esterna(sorgente["fonte"], consultato),
            }
        )

    # Soglia e tetto si leggono dal database (`[P]`): sotto la soglia la fonte non si usa (§B3-SHM-12), oltre il
    # tetto non si allarga la risposta. Il tetto è il più piccolo fra `max` richiesto e `max_risultati_esterni`.
    fiducia_minima = await _fiducia_minima(sess)
    sopra_soglia = [item for item in items if item["fiducia"] >= fiducia_minima]
    ammessi = sopra_soglia[:tetto]

    stato_motore = STATO_OK
    if not ammessi and not sopra_soglia and items:
        # Il motore ha risposto e i risultati c'erano, ma nessuno supera `fiducia_min_esterna`: è esattamente lo
        # stato `scartata_fiducia` dichiarato dal contratto, distinto da «il motore non ha dato nulla».
        stato_motore = STATO_SCARTATA_FIDUCIA

    # Risposta conforme al contratto: solo `items` e `fonti_esterne` (vedi la nota nella docstring). Quando nulla è
    # ammesso, `items: []` con `fonti_esterne[].stato` dichiara l'esito: `scartata_fiducia` se il motore ha risposto ma
    # la fiducia era sotto soglia, `ok` se semplicemente nessun risultato era in allow-list.
    return {
        "items": ammessi,
        "fonti_esterne": [{"fonte": MOTORE_WEB, "stato": stato_motore, "ms": ms}],
    }


async def _fiducia_minima(sess: Sessione) -> int:
    """La soglia `p_int('fiducia_min_esterna')`: sotto, la fonte non si usa (contratto, `scartata_fiducia`)."""
    valori = await parametri(sess, ("fiducia_min_esterna",))
    return parametro_int(valori, "fiducia_min_esterna", 1)


async def _tetto_risultati(sess: Sessione, richiesti: int | None) -> int:
    """Il tetto effettivo: il più piccolo fra `max` richiesto e `max_risultati_esterni` (§B3-SHM-12)."""
    valori = await parametri(sess, ("max_risultati_esterni",))
    tetto = parametro_int(valori, "max_risultati_esterni", 5)
    return min(richiesti, tetto) if richiesti else tetto


# --- `scheda_evento` (area operatore, US-1.3) -----------------------------------------------------------------
#
# La scheda stampabile di un evento: stesso mestiere del biglietto, canale diverso. Il biglietto è uno
# strumento del LLM (`/v1/u/{email}/biglietto`, nel contratto congelato); questa la apre il browser
# dell'operatore dal pulsante «stampa» della Home (`/op/scheda_evento`, cookie di sessione). Il canale
# è diverso, la pipeline è la stessa: una query, `_foglio`, gli stessi divieti.
#
# La query porta anche la Casa e la fonte — con alias `e.` su ogni colonna dell'evento, perché `casa` ha
# a sua volta `id` e `nome` e senza qualificazione PostgreSQL rifiuta la JOIN con «column reference "id"
# is ambiguous» (difetto già visto su un altro endpoint di quest'area). Si seleziona **solo** ciò che la
# scheda stampa: `uid_ical` e `creato_ts` esistono su `trasi.evento` ma non dicono nulla all'operatore, e
# `annullato` è già il filtro del `WHERE`.
SQL_EVENTO = """
SELECT e.titolo, e.descrizione, e.inizio, e.fine, e.luogo_testo, e.url,
       e.affidabilita, e.aggiornato_ts, e.aggiornato_da,
       f.nome AS fonte_nome, f.autorita AS fonte_autorita, f.tipo_accesso AS fonte_tipo,
       c.nome AS casa_nome, c.zona AS casa_zona, c.ente_gestore AS casa_ente,
       (SELECT cl.note_accesso
          FROM trasi.luogo cl
         WHERE cl.casa_id = c.id AND cl.tipo = 'casa_quartiere' AND cl.chiuso_il IS NULL
         ORDER BY cl.affidabilita DESC NULLS LAST, cl.id
         LIMIT 1) AS casa_accesso
  FROM trasi.evento e
  JOIN trasi.casa c ON c.id = e.casa_id
  LEFT JOIN trasi.fonte f ON f.id = e.fonte_id
 WHERE e.id = $1
   AND e.annullato = false
"""

# Dalla riga dell'evento al badge V3. Due casi, e la differenza è la **provenienza**, non la fiducia:
# un evento con fonte iCal l'ha scritto un calendario esterno (`automazioni`, §8 F4) ed è «non
# verificato dalla rete»; uno senza `fonte_id` l'ha inserito una persona della rete — «a mano», e la
# formulazione è quella che `routes_lettura.py` usa per gli eventi senza fonte esterna. Il nome della
# fonte viene da `nome_fonte`, che preferisce `autorita` (il nome umano) al `nome` tecnico.
NOME_FONTE_MANO = "inserito a mano"
NOME_FONTE_CALENDARIO = "calendario della Casa"

# Data di aggiornamento assente: si **dichiara**, non si inventa. `aggiornato_ts` lo scrive il trigger
# `scrittura_00_ts` a ogni scrittura mediata, quindi manca solo per le righe seminate prima del trigger
# — che per l'operatore è un'informazione vera (e il motivo per cui la scheda la mostra invece di
# stampare una data plausibile).
NOTA_AGGIORNAMENTO_ASSENTE = "data di aggiornamento non disponibile"
NOTA_DESCRIZIONE_ASSENTE = "descrizione non disponibile nella memoria"
NOTA_LUOGO_ASSENTE = "luogo non indicato: la Casa di riferimento è il punto di ritrovo dichiarato"
NOTA_ACCESSO_ASSENTE = "modalità di accesso non dichiarate nella memoria"
NOTA_CONTATTO_ASSENTE = "contatto pubblico non dichiarato nella memoria"


_GIORNI = ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica")


def _periodo(inizio: datetime, fine: datetime | None) -> str:
    """`domenica 20/09/2026, 18:00–22:00` — giorno esteso, orari locali.

    Le ore si convertono **esplicitamente** nel fuso italiano: `asyncpg` restituisce i `timestamptz` in
    UTC, e un `strftime` diretto mostrerebbe l'evento delle 18:30 come «16:30» (difetto verificato su
    `eventi_oggi`). La fine è facoltativa e l'evento può chiudersi il giorno dopo: se la data di fine
    differisce, la si scrive per esteso invece di lasciare un orario ambiguo.
    """
    locale_inizio = inizio.astimezone(FUSO)
    testo = f"{_GIORNI[locale_inizio.weekday()]} {locale_inizio.strftime('%d/%m/%Y')}, {locale_inizio.strftime('%H:%M')}"
    if fine is None:
        return testo
    locale_fine = fine.astimezone(FUSO)
    if locale_fine.date() == locale_inizio.date():
        return f"{testo}–{locale_fine.strftime('%H:%M')}"
    return f"{testo} — fino a {_GIORNI[locale_fine.weekday()]} {locale_fine.strftime('%d/%m/%Y')}, {locale_fine.strftime('%H:%M')}"


def _documento_scheda_evento(
    *,
    titolo: str,
    periodo: str,
    dove: str,
    accesso: str,
    descrizione: str,
    contatto: str,
    fonte: str,
    badge: str,
    aggiornamento: str,
    casa: str,
    url: str | None,
    consultato: datetime,
) -> str:
    """La scheda evento: una pagina **A5** (US-1.3), senza moduli e senza campi del cittadino.

    A5 e non A6 come il biglietto: il biglietto indica un luogo (nome, indirizzo, orari) e sta su mezzo
    foglio; la scheda evento porta in più titolo, periodo, descrizione, accesso e contatto — su A6 il
    testo andrebbe a capo a ogni riga e la locandina non sarebbe più leggibile. Il guscio (`_foglio`) è
    lo stesso: cambia il formato del foglio, non le regole.

    Gli stessi divieti del biglietto, e per la stessa ragione: nessun `<form>`, nessun `<input>`, nessuna
    parola «cittadino»/«nome_persona»/«telefono» nel documento. La scheda è una locandina da appendere,
    non un modulo da compilare, e i dati che mostra sono quelli pubblici dell'evento.
    """
    righe = "".join(
        [
            _voce("Quando", periodo),
            _voce("Dove", dove),
            _voce("Come si accede", accesso),
            _voce("Descrizione", descrizione),
            _voce("Contatto pubblico", contatto),
            _voce("Casa di Quartiere", casa),
            _voce("Aggiornamento", aggiornamento),
            _voce("Riferimento", url),
        ]
    )
    return _foglio(
        titolo=f"{titolo} — scheda evento",
        intestazione=titolo,
        formato="A5",
        larghezza="148mm",
        badge=badge,
        righe=righe,
        didascalia=None,
        fonte=fonte,
        consultato=consultato,
        nota=(
            "Questa scheda descrive un evento della rete: non contiene dati personali e non è un modulo "
            "da compilare. Chi decide su date, luogo e accesso è la Casa di Quartiere."
        ),
    )


async def _evento_kb(sess: SessioneOperatore, evento_id: int) -> dict[str, Any] | None:
    """L'evento con Casa e fonte, o `None` se non esiste (o è annullato: il `WHERE` è nella query).

    Stessa forma di `_luogo_kb` per il biglietto: la riga della memoria e i suoi riferimenti, in una
    sola lettura. Il filtro `annullato = false` sta **nella query** e non in Python, perché «esiste»
    per l'operatore significa «esiste e non è annullato»: separare le due condizioni creerebbe un 404
    con due messaggi diversi per lo stesso fatto.
    """
    return await sess.fetchrow(SQL_EVENTO, evento_id)


@router_op.get(
    "/scheda_evento",
    operation_id="op_scheda_evento",
    response_class=HTMLResponse,
    summary="Scheda stampabile di un evento (US-1.3): titolo, data/ora, luogo, accesso, contatto "
    "pubblico, fonte e data di aggiornamento, badge di provenienza. Nessun campo compilabile.",
    tags=["op"],
)
async def op_scheda_evento(
    evento_id: int = Query(..., ge=1, description="Identificativo dell'evento (`trasi.evento.id`)."),
    sess: SessioneOperatore = Depends(sessione_corrente),
) -> HTMLResponse:
    """GET /op/scheda_evento?evento_id= — il foglio stampabile di un evento, per il browser dell'operatore.

    **Read-only**, come tutti gli output dello shim: legge `trasi.evento` unito a `casa` e `fonte` e
    compone la pagina. Nessun `INSERT`, nessun `UPDATE` — se l'operatore vuole correggere qualcosa,
    quella è una proposta (V4), non una scrittura da qui.

    **404** se l'evento non esiste *o è annullato*: `annullato` è l'annullamento soft del flusso iCal
    (§8 F4) e un evento annullato non deve poter essere stampato e appeso in bacheca. Le due condizioni
    sono lo stesso esito perché per l'operatore sono lo stesso fatto: quell'evento non c'è.

    La provenienza (V3) si dichiara sul badge: `[Esterna …]` per un evento importato da un calendario
    (`fonte.tipo_accesso='ical'`, scritto da `automazioni` e mai verificato dalla rete), `[KB …]` per un
    evento della rete — compreso quello **inserito a mano**, che non ha `fonte_id` e per il quale il
    nome della fonte è «inserito a mano» (la stessa formulazione di `routes_lettura.py`).

    La data di aggiornamento è quella di `aggiornato_ts`; se manca, la scheda **lo dichiara** invece di
    stampare una data inventata (US-1.2: «la risposta include la data di aggiornamento», US-1.4:
    l'informazione mancante si dichiara).
    """
    riga = await _evento_kb(sess, evento_id)
    if riga is None:
        raise errore(404, "evento non presente nella memoria della rete, oppure annullato")

    consultato = adesso_locale()
    titolo = (riga["titolo"] or "").strip() or "Evento senza titolo"
    fonte_esterna = riga["fonte_tipo"] == TIPO_ACCESSO_ICAL

    if fonte_esterna:
        # Calendario esterno: il badge dichiara che la rete non l'ha verificato, con l'ora della
        # consultazione (la scheda è appena stata generata, quindi «consultata adesso»).
        nome = nome_fonte(riga["fonte_autorita"], riga["fonte_nome"] or NOME_FONTE_CALENDARIO)
        badge = badge_esterna(nome, consultato)
    else:
        # Rete (o inserimento a mano): il badge KB porta la data di aggiornamento e la fiducia.
        nome = nome_fonte(riga["fonte_autorita"], riga["fonte_nome"] or NOME_FONTE_MANO)
        badge = badge_kb(nome, riga["aggiornato_ts"], riga["affidabilita"])

    aggiornamento = (
        f"{riga['aggiornato_ts'].astimezone(FUSO).strftime('%d/%m/%Y')} alle "
        f"{riga['aggiornato_ts'].astimezone(FUSO).strftime('%H:%M')}"
        if riga["aggiornato_ts"]
        else NOTA_AGGIORNAMENTO_ASSENTE
    )
    if riga["aggiornato_da"]:
        # Chi ha scritto il dato **per ruolo**, mai una persona: è il vocabolario del runbook.
        aggiornamento = f"{aggiornamento} ({riga['aggiornato_da']})"

    casa = f"{riga['casa_nome']} — {riga['casa_zona']}" if riga["casa_zona"] else riga["casa_nome"]
    if riga["casa_ente"]:
        casa = f"{casa} ({riga['casa_ente']})"

    descrizione = (riga["descrizione"] or "").strip() or NOTA_DESCRIZIONE_ASSENTE
    dove = (riga["luogo_testo"] or "").strip() or NOTA_LUOGO_ASSENTE
    # L'accesso è dichiarato dalla Casa (US-1.2: «garanzie di accesso»). La memoria non ha una colonna
    # «accesso» su `evento`: l'unica nota di accesso che il sistema possiede è `luogo.note_accesso` del
    # luogo della Casa che organizza. Quando non c'è, la scheda **lo dichiara** invece di dedurre
    # «gratuito» o «su prenotazione» — sono affermazioni che solo la Casa può fare.
    accesso = (riga["casa_accesso"] or "").strip() or NOTA_ACCESSO_ASSENTE

    return HTMLResponse(
        _documento_scheda_evento(
            titolo=titolo,
            periodo=_periodo(riga["inizio"], riga["fine"]),
            dove=dove,
            accesso=accesso,
            descrizione=descrizione,
            # Il contatto pubblico è quello della Casa che organizza l'evento: l'ente gestore, che è
            # un'informazione pubblica e istituzionale (V5). Nessun recapito di persona, mai.
            contatto=riga["casa_ente"] or NOTA_CONTATTO_ASSENTE,
            fonte=nome,
            badge=badge,
            aggiornamento=aggiornamento,
            casa=casa,
            url=riga["url"],
            consultato=consultato,
        )
    )
