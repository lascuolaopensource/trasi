"""`GET /op/biglietto?luogo_id`: il biglietto A6 stampabile di un luogo, per il browser dell'operatore (§5.2, `T-SHIM-14`).

**Perché serve un endpoint nuovo.** `biglietto` è nel contratto **congelato** con Onyx
(`GET /v1/u/{email}/biglietto`): il browser non può chiamarlo, perché quel percorso porta l'email dell'operatore e
richiede la `X-Trasi-Key`, che il browser non deve vedere mai. Stessa funzione, canale diverso: cookie di sessione
sotto `/op`, nessun identificatore nell'URL.

**Il foglio è uno solo.** `_documento_biglietto` si **importa** da `shim/app/testi.py`, non si ricopia: due
costruttori della stessa pagina divergono alla prima modifica (un formato, un divieto, una nota) e il difetto si
scopre solo confrontando due biglietti stampati. Il piano lo dice esplicitamente — «riusa `_documento_biglietto`»
(§5.5, `T-SHIM-14`).

**Cosa può essere `luogo_id`.** Un intero (un luogo di `trasi.luogo`) oppure `osm:<node|way|relation>:<id>`: la
seconda forma è ciò che la scheda del luogo ha in mano quando l'operatore guarda un **POI di OpenStreetMap**, che non
ha un id in memoria. La forma è già gestita da `testi._identificativo_osm`, e la si riusa: un POI esterno ricaricato
da Overpass produce un biglietto con badge `[Esterna …]`, senza **mai** scrivere in `trasi.luogo` (V4).

**La Casa di riferimento è quella della sessione.** Il biglietto dice «a circa 840 m dalla Casa San Bao (distanza in
linea d'aria)»: quel riferimento è l'unico punto che l'operatore può chiamare «qui», quindi non arriva dal corpo né
da un parametro scelto dal browser — si legge da `sessione.casa_id`. Il contratto congelato ammette un `casa`
facoltativo (per Onyx, che non ha sessione); qui non c'è, ed è una semplificazione deliberata: un parametro in meno
che il browser potrebbe sbagliare.

**Nessun campo compilabile, nessun dato personale.** Il documento non contiene `<form>`, `<input>`, né le parole
«cittadino», «nome_persona», «telefono»: è un'indicazione di luogo da appendere, non un modulo. I divieti sono
verificati dai test di `test_output.py` sulla stessa funzione, quindi valgono anche per questo foglio.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Query
from fastapi.responses import HTMLResponse

from .auth import SessioneOperatore, sessione_corrente
from .badge import NOTA_ORARI_ASSENTI, badge_esterna, badge_kb, nome_fonte
from .errori import errore
from .settings import get_settings
from .testi import _arrivo, _documento_biglietto, _identificativo_osm
from .vicinanza import adesso_locale, distanza_m, nodo_osm

router = APIRouter()

TIPO_ACCESSO_OSM = "osm_overpass"
NOME_OSM_DEFAULT = "OpenStreetMap"

# Il luogo della memoria con fonte e orari leggibili. Stessa forma di `testi._luogo_kb` — ma **senza** il parametro
# `casa`, perché qui la Casa di riferimento è quella della sessione: la distanza si calcola dalla sua geometria, che
# si legge nella stessa query con una join invece di una seconda andata e ritorno.
SQL_LUOGO = """
SELECT l.id, l.nome, l.tipo, COALESCE(l.indirizzo, '') AS indirizzo,
       COALESCE(l.note_accesso, '') AS note_accesso,
       st_y(l.geom::geometry) AS lat, st_x(l.geom::geometry) AS lon,
       trasi.orari_testo(l.orari) AS orari_testo,
       l.data_aggiornamento, l.affidabilita, l.url, l.ext_ref,
       f.autorita AS fonte_autorita, f.nome AS fonte_tecnica,
       c.slug AS casa_slug, c.nome AS casa_nome,
       rc.nome AS riferimento_nome,
       CASE WHEN rc.geom IS NULL OR l.geom IS NULL THEN NULL
            ELSE round(st_distance(l.geom, rc.geom)::numeric, 1) END AS distanza_m
  FROM trasi.luogo l
  LEFT JOIN trasi.fonte f ON f.id = l.fonte_id
  LEFT JOIN trasi.casa c ON c.id = l.casa_id
  LEFT JOIN trasi.casa rc ON rc.id = $2
 WHERE l.id = $1
   AND l.chiuso_il IS NULL
"""

# La fonte OSM in allow-list, con l'URL dell'interprete: la stessa risoluzione di `testi._configurazione_osm`.
SQL_FONTE_OSM = """
SELECT COALESCE(NULLIF(f.autorita, ''), f.nome) AS fonte
  FROM trasi.fonte f
 WHERE f.tipo_accesso = $1 AND f.attiva
 ORDER BY f.livello_fiducia DESC, f.id
 LIMIT 1
"""

# La geometria della Casa della sessione, per la distanza del POI esterno (i POI non sono nel database: V4).
SQL_RIFERIMENTO = """
SELECT nome, st_y(geom::geometry) AS lat, st_x(geom::geometry) AS lon
  FROM trasi.casa WHERE id = $1
"""


async def _riferimento(sess: SessioneOperatore) -> dict[str, Any] | None:
    """La Casa della sessione come punto di riferimento (nome e coordinate), o `None` per un ruolo senza Casa."""
    if sess.casa_id is None:
        return None
    riga = await sess.fetchrow(SQL_RIFERIMENTO, sess.casa_id)
    return dict(riga) if riga else None


@router.get(
    "/biglietto",
    operation_id="op_biglietto",
    response_class=HTMLResponse,
    summary="Biglietto A6 stampabile di un luogo (della memoria della rete o un punto di OpenStreetMap indicato come "
    "«osm:node:<id>»): nome, indirizzo, orari, come arrivare, badge di provenienza. Nessun campo compilabile e "
    "nessun dato personale.",
    tags=["op"],
)
async def op_biglietto(
    luogo_id: str = Query(
        ...,
        min_length=1,
        description="Identificativo del luogo (`trasi.luogo.id`) oppure un riferimento esterno «osm:node:<id>» per "
        "un punto di OpenStreetMap non presente nella memoria della rete.",
    ),
    sess: SessioneOperatore = Depends(sessione_corrente),
) -> HTMLResponse:
    """GET /op/biglietto?luogo_id= → **HTML A6** (`text/html`, l'unica risposta non JSON dell'area operatore).

    Due origini, un solo foglio:

    * **luogo in memoria** → badge `[KB · …]`, con l'orari leggibili di `trasi.orari_testo` e la nota di accesso;
    * **`osm:node:<id>`** → il POI si ricarica da Overpass e il badge è `[Esterna · …]`; il POI **non** viene scritto
      in `trasi.luogo` (V4: la promozione in memoria resta una proposta, non un effetto collaterale della stampa).

    Sul POI esterno, se Overpass non risponde entro il budget dichiarato, si risponde **404** e non **503**: il
    guasto è di una fonte esterna, e un 503 direbbe invece che il servizio Trasi è giù. Il biglietto è un foglio
    opzionale — la scheda del luogo resta leggibile con i suoi dati — quindi la sua assenza si dichiara come tale.
    """
    consultato = adesso_locale()
    riferimento = await _riferimento(sess)

    identificativo = _identificativo_osm(luogo_id)
    if identificativo is None:
        if not luogo_id.isdigit():
            raise errore(
                422,
                "luogo_id deve essere un identificativo numerico di luogo oppure un riferimento esterno «osm:node:<id>»",
            )
        riga = await sess.fetchrow(SQL_LUOGO, int(luogo_id), sess.casa_id)
        if riga is None:
            raise errore(404, "luogo non presente nella memoria della rete")

        fonte = nome_fonte(riga["fonte_autorita"], riga["fonte_tecnica"])
        return HTMLResponse(
            _documento_biglietto(
                nome=riga["nome"],
                indirizzo=riga["indirizzo"],
                orari_testo=riga["orari_testo"],
                orari_nota=None if riga["orari_testo"] else NOTA_ORARI_ASSENTI,
                come_arrivare=_arrivo(
                    float(riga["distanza_m"]) if riga["distanza_m"] is not None else None,
                    riga["riferimento_nome"],
                    riga["indirizzo"] or riga["note_accesso"],
                ),
                fonte=fonte,
                badge=badge_kb(fonte, riga["data_aggiornamento"], riga["affidabilita"]),
                consultato=consultato,
                tipo=riga["tipo"],
            )
        )

    impostazioni = get_settings()
    riga_fonte = await sess.fetchrow(SQL_FONTE_OSM, TIPO_ACCESSO_OSM)
    fonte = nome_fonte(riga_fonte["fonte"] if riga_fonte else None, NOME_OSM_DEFAULT)

    poi = await nodo_osm(
        identificativo,
        indirizzo=impostazioni.overpass_url,
        timeout_s=impostazioni.overpass_timeout_s,
        user_agent=impostazioni.overpass_user_agent,
        adesso=consultato,
    )
    if poi is None:
        raise errore(404, "POI esterno non raggiungibile su OpenStreetMap")

    distanza = (
        distanza_m(float(riferimento["lat"]), float(riferimento["lon"]), poi.lat, poi.lon)
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


def monta(applicazione: FastAPI) -> None:
    """Monta il router sotto `/op`, **fuori** dal documento OpenAPI (stessa regola di `mappa_op.monta`)."""
    applicazione.include_router(router, prefix="/op", include_in_schema=False)


__all__ = ["monta", "op_biglietto", "router"]
