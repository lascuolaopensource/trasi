"""`GET /mappa_case`: le dieci Case della rete per la mappa della Home (pagina `mappa.html`).

**Fuori dal contratto congelato** (`include_in_schema=False`): non è uno strumento del LLM, è la lettura della
pagina statica «Mappa», che è pubblica come la Home e passa dallo stesso canale con chiave
(`/api/shim/v1/u/rete@trasi.local/…`, Caddy inietta `X-Trasi-Key`). Il gate V-09 resta `esposte == attese`.

La fonte è `trasi.v_mappa_case` (db/004 V7: lat/lon numerici, raggio effettivo, qualità della geometria, orari in
parole) con il legame Casa → riga di memoria del luogo `casa_quartiere` per fonte, affidabilità e data — lo stesso
ordinamento di `testi.SQL_EVENTO` (la riga più affidabile, a parità la più vecchia per id), così il badge (V3) è
deterministico e lo compone `badge_kb`, non questo modulo.

`casa` è facoltativa: se nomina una Casa (slug o nome, `risolvi_slug_casa`) quella voce porta `evidenziata: true` e la
risposta dice quale (`casa_evidenziata`); se non nomina nessuna Casa della rete è **404** (vocabolario chiuso, come
`eventi_oggi`); se manca, nessuna evidenziata. Nessun cerchio del raggio: `raggio_m_eff` viaggia come dato, la
pagina non lo disegna (miglioria non approvata).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query

from .badge import badge_kb, nome_fonte
from .db import Sessione, dipendenza_sessione, risolvi_slug_casa
from .errori import errore
from .schemi import RispostaMappaCase, VoceMappaCasa
from .vicinanza import FUSO

router = APIRouter()

SQL_CASA_ESISTE = "SELECT id FROM trasi.casa WHERE slug = $1"

SQL_CASE = """
SELECT vc.slug, vc.nome, vc.zona, vc.ente_gestore, vc.lat, vc.lon,
       vc.raggio_m_eff, vc.geom_qualita, vc.da_validare, vc.orari_provvisori, vc.orari_testo,
       f.nome AS fonte_nome, f.autorita AS fonte_autorita,
       l.affidabilita, l.data_aggiornamento
  FROM trasi.v_mappa_case vc
  LEFT JOIN LATERAL (
      SELECT l2.fonte_id, l2.affidabilita, l2.data_aggiornamento
        FROM trasi.luogo l2
       WHERE l2.casa_id = vc.id AND l2.tipo = 'casa_quartiere' AND l2.chiuso_il IS NULL
       ORDER BY l2.affidabilita DESC NULLS LAST, l2.id
       LIMIT 1
  ) l ON true
  LEFT JOIN trasi.fonte f ON f.id = l.fonte_id
 WHERE vc.lat IS NOT NULL AND vc.lon IS NOT NULL
 ORDER BY vc.nome
"""


def voce_casa(riga: Any, *, evidenziata: bool) -> VoceMappaCasa:
    """Una riga di `v_mappa_case` → la voce che la mappa disegna come quadrato pieno e l'elenco legge."""
    fonte = nome_fonte(riga["fonte_autorita"], riga["fonte_nome"])
    return VoceMappaCasa(
        slug=riga["slug"],
        nome=riga["nome"],
        zona=riga["zona"],
        ente_gestore=riga["ente_gestore"],
        lat=float(riga["lat"]),
        lon=float(riga["lon"]),
        raggio_m_eff=riga["raggio_m_eff"],
        geom_qualita=riga["geom_qualita"],
        da_validare=bool(riga["da_validare"]),
        orari_provvisori=bool(riga["orari_provvisori"]),
        orari_testo=riga["orari_testo"] or None,
        fonte=fonte,
        fiducia=riga["affidabilita"],
        data_aggiornamento=riga["data_aggiornamento"],
        badge=badge_kb(fonte, riga["data_aggiornamento"], riga["affidabilita"]),
        evidenziata=evidenziata,
    )


@router.get(
    "/mappa_case",
    summary="Le dieci Case della rete per la mappa della Home, con la Casa scelta evidenziata.",
    include_in_schema=False,
    response_model=RispostaMappaCase,
)
async def mappa_case(
    casa: str | None = Query(default=None, description="Slug o nome della Casa da evidenziare; facoltativo."),
    sess: Sessione = Depends(dipendenza_sessione),
) -> RispostaMappaCase:
    """GET /mappa_case?casa= → `{casa_evidenziata, consultato_ts, case: [...]}`; 404 se `casa` non è una Casa della rete."""
    evidenziata: str | None = None
    if casa and casa.strip():
        richiesta = casa.strip()
        if await sess.fetchval(SQL_CASA_ESISTE, richiesta) is not None:
            evidenziata = richiesta
        else:
            evidenziata = await risolvi_slug_casa(sess, richiesta)
            if evidenziata is None:
                raise errore(404, f"casa non trovata: nessuna Casa di Quartiere con slug «{richiesta}»")

    righe = await sess.fetch(SQL_CASE)
    return RispostaMappaCase(
        casa_evidenziata=evidenziata,
        consultato_ts=datetime.now(FUSO),
        case=[voce_casa(riga, evidenziata=riga["slug"] == evidenziata) for riga in righe],
    )


__all__ = ["SQL_CASE", "mappa_case", "router", "voce_casa"]
