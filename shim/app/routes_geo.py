"""`vicino_a`: l'unico endpoint geografico (B3-SHM-03/04).

Unisce due fonti che non si conoscono fra loro — la memoria della rete (`trasi.luogo`) e i punti di interesse di
OpenStreetMap — e le presenta in una lista sola, in cui ogni item dichiara da dove viene (V3). Le decisioni non
ovvie sono raccolte qui, perché ognuna ha una ragione che va letta prima di cambiarla.

**Il raggio filtra gli esterni, non la memoria della rete.** La KB è la memoria verificata della rete: il criterio di
done di B3-SHM-04 chiede che `vicino_a?casa=san-bao&tipo=bar` mostri il bar di Bozzano, che dista 2.099 m da San Bao
(l'unico `bar` in memoria, e la sua Casa è Bozzano). Filtrare la KB col raggio lo farebbe sparire. Il raggio serve
invece a non sommergere la risposta di POI: è quanto dice l'architettura §3 («query Overpass entro `casa.raggio_m`»)
e §8 F1. La distanza resta dichiarata su ogni item, quindi il LLM vede e può citare i 2 km.

**`aperto_adesso` separa due cose che vengono confuse.** Senza il parametro l'ordine è gruppo → distanza, e i chiusi
restano in lista (l'operatore vuole sapere che il bar c'è ma è chiuso). Con `aperto_adesso=true` i **chiusi noti**
escono e i POI **senza orari non escono**: restano dopo gli aperti noti con `aperto_adesso: null` e
`orari_nota: "orari non disponibili"`. Scartarli nasconderebbe il 92% dei POI reali (copertura `opening_hours` 7.7%
sui bar di Brindisi, `docs/verifiche.md` V-extra) ed è la mitigazione dichiarata del rischio §13.

**Casa inesistente → 422, non 404.** Il contratto congelato di `vicino_a` non dichiara un 404, e la descrizione del
parametro `casa` rinvia al vocabolario `casa.slug`: un valore fuori vocabolario è un parametro non ammesso, come per
`tipo`. Inventare un 404 non dichiarato romperebbe il contratto con Onyx per un caso che il vocabolario già copre.

**Il tipo è un vocabolario chiuso → 422 con l'elenco ammesso.** `tipo` determina i tag OpenStreetMap da interrogare:
un valore ignoto non è traducibile in una query, e restituire una lista vuota farebbe credere all'assistente che non
esiste nulla, che è peggio di un errore dichiarato.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from .badge import nome_fonte
from .contratto import meta
from .db import Sessione, dipendenza_sessione, parametri, parametro_int, slug_casa_da_identita
from .errori import errore
from .schemi import FonteEsterna, ItemVicinanza, RispostaVicinoA
from .settings import get_settings
from .vicinanza import (
    CHIAVI_PARAMETRI,
    STATO_ERRORE,
    STATO_OK,
    STATO_SCARTATA_FIDUCIA,
    TIPI_AMMESSI,
    TIPI_OSM,
    adesso_locale,
    interroga_overpass,
    item_esterno,
    item_kb,
    ordina_items,
    orari_da_jsonb,
)

router = APIRouter()

RAGGIO_DEFAULT_M = 800
FIDUCIA_MIN_DEFAULT = 2
MAX_ESTERNI_DEFAULT = 5

TIPO_ACCESSO_OSM = "osm_overpass"
NOME_OSM_DEFAULT = "OpenStreetMap"

SQL_CASA = """
SELECT c.id, c.slug, c.nome, c.raggio_m,
       round(st_y(c.geom::geometry)::numeric, 6) AS lat,
       round(st_x(c.geom::geometry)::numeric, 6) AS lon
FROM trasi.casa c
WHERE c.slug = $1
"""

# La memoria della rete per tipo, **senza filtro di raggio** (vedi docstring del modulo). `l.geom IS NOT NULL`
# è obbligatorio: `distanza_m` è richiesto dal contratto, e un luogo senza coordinate non ha una distanza da
# dichiarare. `st_distance` con `geography` è in metri reali, non in gradi.
SQL_KB = """
SELECT l.id, l.nome, l.tipo, COALESCE(l.indirizzo, '') AS indirizzo, l.orari,
       trasi.orari_testo(l.orari) AS orari_testo,
       round(st_y(l.geom::geometry)::numeric, 6) AS lat,
       round(st_x(l.geom::geometry)::numeric, 6) AS lon,
       round(st_distance(l.geom, c.geom)::numeric, 1) AS distanza_m,
       COALESCE(l.url, f.url) AS url, l.data_aggiornamento, l.affidabilita,
       f.nome AS fonte_nome, f.autorita AS fonte_autorita
FROM trasi.luogo l
JOIN trasi.casa c ON c.slug = $1
LEFT JOIN trasi.fonte f ON f.id = l.fonte_id
WHERE l.chiuso_il IS NULL
  AND l.geom IS NOT NULL
  AND l.tipo = $2
ORDER BY distanza_m
"""

# La fonte esterna: riga di allow-list (`fonte`) con `tipo_accesso='osm_overpass'`. Si prende quella con la fiducia
# più alta perché è l'autorità che il badge deve citare.
SQL_FONTE_OSM = """
SELECT f.nome, f.autorita, f.livello_fiducia, f.url
FROM trasi.fonte f
WHERE f.tipo_accesso = 'osm_overpass' AND f.attiva
ORDER BY f.livello_fiducia DESC, f.id
LIMIT 1
"""


def valuta_fonte(fiducia: int, soglia: int) -> str:
    """La fonte esterna è utilizzabile? Ritorna lo stato da dichiarare in `fonti_esterne[].stato`.

    Sta in una funzione pura perché è la regola di §7.2 («sotto questa soglia la fonte esterna non viene usata»),
    e una regola che vive dentro un `if` in mezzo a una chiamata di rete non è verificabile da sola.
    """
    return STATO_OK if fiducia >= soglia else STATO_SCARTATA_FIDUCIA


async def fonte_esterna_osm(sess: Sessione) -> dict[str, Any] | None:
    """La riga di allow-list della fonte OpenStreetMap/Overpass attiva, o `None` se non ce n'è una."""
    riga = await sess.fetchrow(SQL_FONTE_OSM)
    return dict(riga) if riga else None


@router.get("/vicino_a", response_model=RispostaVicinoA, **meta("vicino_a"))
async def vicino_a(
    tipo: str = Query(description="Tipo di luogo cercato (obbligatorio); mappa chiusa verso i tag OpenStreetMap."),
    casa: str | None = Query(
        default=None,
        description="Slug della Casa di Quartiere da cui misurare la distanza. Se omesso si usa la Casa dell'operatore autenticato.",
    ),
    aperto_adesso: bool | None = Query(
        default=None, description="Se `true`, esclude i luoghi noti come chiusi e ordina prima gli aperti."
    ),
    raggio_m: int | None = Query(default=None, ge=1, description="Raggio di ricerca in metri, facoltativo."),
    sess: Sessione = Depends(dipendenza_sessione),
) -> RispostaVicinoA:
    """I luoghi di un tipo vicino a una Casa, dalla memoria della rete e da OpenStreetMap.

    Se `casa` non è indicata, si misura dalla Casa dell'operatore autenticato: l'identità
    (`identita_onyx.casa_id`) la determina, così l'assistente non deve conoscerla né indovinarla.
    Un ruolo senza Casa (es. `rete`) deve indicarla esplicitamente.

    Uno slug **che non esiste** non è un errore quando l'operatore ha una Casa propria: il modello,
    vedendo `casa` nel contratto, tende a riempirlo con il nome della Casa o il nome
    dell'applicazione («Centro di Aggregazione Bozzano», «Trasi») invece dello slug, e rispondere 422
    faceva dire all'assistente «la rete non riconosce questa Casa» — un guasto dichiarato che non
    esiste. Si ricade sull'identità, che è il dato certo.
    """
    # L'ordine conta: prima il `tipo`, che è una validazione **locale** (non richiede il database e
    # il suo errore deve arrivare anche quando `casa` è assente), poi la Casa.
    tipo_normalizzato = (tipo or "").strip().lower()
    if tipo_normalizzato not in TIPI_OSM:
        raise errore(422, f"parametri non ammessi — tipo: valori ammessi {', '.join(TIPI_AMMESSI)}")

    slug = (casa or "").strip() or await slug_casa_da_identita(sess)
    if not slug:
        raise errore(
            422,
            "parametri non ammessi — casa: obbligatoria per un ruolo senza Casa (es. rete); indicare lo slug",
        )

    # Una sola lettura della Casa. Se lo slug richiesto non esiste e l'operatore ha una Casa sua, si
    # riprova con quella: così il controllo di esistenza è la query che serve alla risposta e non una
    # seconda query da tenere allineata.
    riga_casa = await sess.fetchrow(SQL_CASA, slug)
    if riga_casa is None:
        slug_identita = await slug_casa_da_identita(sess)
        if slug_identita and slug_identita != slug:
            riga_casa = await sess.fetchrow(SQL_CASA, slug_identita)
            slug = slug_identita
    if riga_casa is None:
        raise errore(422, f"parametri non ammessi — casa: nessuna Casa di Quartiere con slug «{slug}»")

    valori = await parametri(sess, CHIAVI_PARAMETRI)
    raggio_effettivo = (
        raggio_m
        or riga_casa["raggio_m"]
        or parametro_int(valori, "raggio_vicinanza_m", RAGGIO_DEFAULT_M)
    )
    soglia_fiducia = parametro_int(valori, "fiducia_min_esterna", FIDUCIA_MIN_DEFAULT)
    max_esterni = parametro_int(valori, "max_risultati_esterni", MAX_ESTERNI_DEFAULT)

    adesso = adesso_locale()
    casa_lat = float(riga_casa["lat"])
    casa_lon = float(riga_casa["lon"])

    items = [
        item_kb(
            dict(riga) | {"aperto_adesso": orari_da_jsonb(riga["orari"], adesso)},
            casa_lat=casa_lat,
            casa_lon=casa_lon,
            tipo=tipo_normalizzato,
            adesso=adesso,
        )
        for riga in await sess.fetch(SQL_KB, slug, tipo_normalizzato)
    ]

    esterni, esito = await _esterni(
        tipo=tipo_normalizzato,
        casa_lat=casa_lat,
        casa_lon=casa_lon,
        raggio_m=raggio_effettivo,
        max_esterni=max_esterni,
        soglia_fiducia=soglia_fiducia,
        sess=sess,
        adesso=adesso,
    )
    items.extend(esterni)

    if aperto_adesso:
        # Escono i soli chiusi **noti**: `aperto_adesso is not False` tiene dentro i POI senza orari, che sono la
        # maggioranza reale e non vanno persi (§13, criterio B3-SHM-04).
        items = [item for item in items if item["aperto_adesso"] is not False]

    return RispostaVicinoA(
        casa=slug,
        tipo=tipo_normalizzato,
        raggio_m=raggio_effettivo,
        items=[ItemVicinanza(**item) for item in ordina_items(items)],
        fonti_esterne=[esito],
    )


async def _esterni(
    *,
    tipo: str,
    casa_lat: float,
    casa_lon: float,
    raggio_m: int,
    max_esterni: int,
    soglia_fiducia: int,
    sess: Sessione,
    adesso,
) -> tuple[list[dict[str, Any]], FonteEsterna]:
    """Interroga Overpass e ritorna (item esterni, esito dichiarato). **Mai** un'eccezione al chiamante.

    Se la fonte è sotto la soglia di fiducia non viene interrogata affatto: interrogarla per poi scartarne i
    risultati costerebbe il timeout dichiarato (5 s) per una risposta che non si userà. Lo stato `scartata_fiducia`
    dice esattamente questo, ed è la lettura che il piano si aspetta (`UPDATE fonte SET livello_fiducia=1` →
    `stato="scartata_fiducia"`).
    """
    fonte = await fonte_esterna_osm(sess)
    if fonte is None:
        # Nessuna fonte OSM in allow-list: non c'è nulla da interrogare, e lo shim non inventa un risultato.
        return [], FonteEsterna(fonte=NOME_OSM_DEFAULT, stato=STATO_ERRORE, ms=0)

    nome = nome_fonte(fonte["autorita"], fonte["nome"])
    stato = valuta_fonte(fonte["livello_fiducia"], soglia_fiducia)
    if stato == STATO_SCARTATA_FIDUCIA:
        return [], FonteEsterna(fonte=nome, stato=stato, ms=0)

    impostazioni = get_settings()
    esito = await interroga_overpass(
        tipo,
        casa_lat,
        casa_lon,
        raggio_m,
        indirizzo=impostazioni.overpass_url,
        timeout_s=impostazioni.overpass_timeout_s,
        user_agent=impostazioni.overpass_user_agent,
        adesso=adesso,
        indirizzo_failover=impostazioni.overpass_url_2,
    )

    if esito.stato != STATO_OK:
        # Timeout o errore: gli item KB restano, la fonte dichiara il proprio stato. `fonti_esterne[].stato` è
        # l'unico posto in cui il guasto di una fonte esterna compare (§9.1, «mai eccezione al chiamante»).
        return [], FonteEsterna(fonte=nome, stato=esito.stato, ms=esito.ms)

    tutti = [
        item_esterno(
            poi,
            casa_lat=casa_lat,
            casa_lon=casa_lon,
            fonte=nome,
            fiducia=fonte["livello_fiducia"],
            tipo=tipo,
            adesso=adesso,
        )
        for poi in esito.poi
    ]
    # Il tetto si applica dopo l'ordinamento: si tengono i più vicini, non i primi che Overpass ha restituito.
    ordinati = ordina_items(tutti)
    return ordinati[:max_esterni], FonteEsterna(fonte=nome, stato=esito.stato, ms=esito.ms)


__all__ = ["RAGGIO_DEFAULT_M", "router", "valuta_fonte"]
