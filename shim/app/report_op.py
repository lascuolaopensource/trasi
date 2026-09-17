"""`GET /op/report`, `GET /op/report/{id}`, `GET /op/report/{id}/export` — il report mensile nell'area operatore.

**Che cos'è il report.** L'oggetto di dominio di `db/024`: una riga di `trasi.report` per (Casa, mese), scritta dal
ciclo mensile (`flussi/ciclo_mensile.py`) con i contenuti del foglio 4.3 — richieste, esiti per categoria, proposte,
schede in scadenza — già **mascherati** dalle viste k-anonime (`«<5»`, `«—»`). Si legge e si commenta; non si
modifica (US-3/US-4, regola del gruppo Processi).

**Chi vede cosa lo decide la RLS, non questo file.** `rep_sel` (db/024): una Casa legge il proprio report,
`rete`/`ti` li leggono tutti. Le query qui sotto leggono `trasi.report` **nudo**, con la sessione che impersona il
ruolo della Casa: un report altrui non è una riga da filtrare, è una riga che non arriva. Per lo stesso motivo il
`404` del dettaglio vale sia per «non esiste» sia per «non è tuo»: distinguerli direbbe a un estraneo che il report
esiste.

**Perché la tabella e non `v_report`.** La vista è stata ridefinita dal ramo del monitoraggio PA (db/031) con
colonne in più: leggere la tabella con colonne **nominate** funziona su entrambe le forme del database, e le colonne
lette (id, casa, mese, ambito, contenuti, csv, generato_ts) sono quelle di db/024 — le stesse ovunque.

**L'export è un file `.html`, non un PDF** (P2.3): `Content-Disposition: attachment` con nome
`report_<slug>_<AAAA-MM>.html`, documento autonomo (nessun asset esterno) che si apre in qualunque browser e si
stampa. Stessi divieti del biglietto: nessun `<form>`, nessun campo compilabile, nessun dato personale — i
contenuti sono conteggi e categorie, e la fonte è dichiarata in calce perché un file scaricato si legge fuori dal
sistema.
"""

from __future__ import annotations

import json
from datetime import date
from html import escape
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, FastAPI, Query
from fastapi.responses import Response

from .auth import SessioneOperatore, sessione_corrente
from .errori import errore

router = APIRouter()

FUSO = ZoneInfo("Europe/Rome")

DETAIL_REPORT_NON_TROVATO = "report non presente nella memoria della rete"

# Quanti report elenca la Home: dodici mesi bastano a «l'anno scorso», e un elenco più lungo è un archivio, non
# una vista. `rete` vede tutte le Case: 12 mesi × 10 Case è comunque una pagina, non un'estrazione.
TETTO_ELENCO = 120

SQL_ELENCO = """
SELECT r.id, r.casa_id, c.slug AS casa_slug, c.nome AS casa_nome,
       r.mese, r.ambito, r.contenuti, r.generato_ts, (r.csv IS NOT NULL) AS ha_csv,
       (SELECT count(*) FROM trasi.commento cm WHERE cm.entita = 'report' AND cm.entita_id = r.id) AS commenti
  FROM trasi.report r
  LEFT JOIN trasi.casa c ON c.id = r.casa_id
 WHERE ($1::integer IS NULL OR r.casa_id = $1)
 ORDER BY r.mese DESC, r.ambito, c.nome
 LIMIT $2
"""

SQL_DETTAGLIO = """
SELECT r.id, r.casa_id, c.slug AS casa_slug, c.nome AS casa_nome,
       r.mese, r.ambito, r.contenuti, r.csv, r.generato_ts, r.generato_da,
       (SELECT count(*) FROM trasi.commento cm WHERE cm.entita = 'report' AND cm.entita_id = r.id) AS commenti
  FROM trasi.report r
  LEFT JOIN trasi.casa c ON c.id = r.casa_id
 WHERE r.id = $1
"""

# I nomi in parole delle categorie e degli esiti del registro (`trasi.richiesta`, db/001): il report è un documento
# per chi non legge codici. Un valore fuori elenco esce così com'è — non si inventa una parola per un codice nuovo.
CATEGORIE = {
    "orientamento": "Orientamento",
    "fiscale_isee": "Fiscale e ISEE",
    "servizi_sociali": "Servizi sociali",
    "lavoro": "Lavoro",
    "abitare": "Abitare",
    "salute": "Salute",
    "interculturale": "Interculturale",
    "ascolto_solitudine": "Ascolto e solitudine",
    "eventi_attivita": "Eventi e attività",
    "altro": "Altro",
}
ESITI = {
    "risolta": "risolte",
    "inviata_altrove": "inviate altrove",
    "non_trovata": "senza destinazione",
    "rinviata": "rinviate",
}
MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
        "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"]


def mese_in_parole(mese: date) -> str:
    return f"{MESI[mese.month - 1]} {mese.year}"


def _contenuti(valore: Any) -> dict[str, Any]:
    """`contenuti` come dizionario: asyncpg rende `jsonb` come stringa, e un report antico può avere `{}`."""
    if isinstance(valore, str):
        try:
            valore = json.loads(valore)
        except ValueError:
            valore = {}
    return valore if isinstance(valore, dict) else {}


def voce_report(riga: Any, *, con_csv: bool = False) -> dict[str, Any]:
    """Una riga di `report` → il JSON della pagina, con i contenuti già nella forma che la Home disegna."""
    contenuti = _contenuti(riga["contenuti"])
    mese: date = riga["mese"]
    voce = {
        "id": riga["id"],
        "casa_id": riga["casa_id"],
        "casa_slug": riga["casa_slug"],
        "casa_nome": riga["casa_nome"],
        "ambito": riga["ambito"],
        "mese": mese.isoformat(),
        "mese_testo": mese_in_parole(mese),
        "generato_ts": riga["generato_ts"].astimezone(FUSO).isoformat(),
        "commenti": int(riga["commenti"] or 0),
        "richieste": int(contenuti.get("richieste") or 0),
        "senza_risposta": int(contenuti.get("senza_risposta") or 0),
        "proposte_in_attesa": int(contenuti.get("proposte_in_attesa") or 0),
        "proposte_applicate": int(contenuti.get("proposte_applicate") or 0),
        "schede_in_scadenza": int(contenuti.get("schede_in_scadenza") or 0),
        "per_categoria_esito": [
            {
                "categoria": cella.get("categoria"),
                "categoria_testo": CATEGORIE.get(cella.get("categoria"), cella.get("categoria") or "—"),
                "esito": cella.get("esito"),
                "esito_testo": ESITI.get(cella.get("esito"), cella.get("esito") or "—"),
                "n": str(cella.get("n") if cella.get("n") is not None else "—"),
            }
            for cella in contenuti.get("per_categoria_esito") or []
            if isinstance(cella, dict)
        ],
        "suggerimenti": contenuti.get("suggerimenti") or None,
        "export_url": f"/op/report/{riga['id']}/export",
    }
    if con_csv:
        voce["csv"] = riga["csv"]
    return voce


@router.get(
    "/report",
    operation_id="op_report",
    summary="I report mensili leggibili da questa sessione: la propria Casa per un operatore, tutte le Case per la "
    "rete. Dal più recente; ogni voce porta i numeri di sintesi già mascherati e il collegamento all'export.",
    tags=["op"],
)
async def op_report(
    casa_id: int | None = Query(default=None, ge=1, description="Solo i report di questa Casa (per la rete)."),
    sess: SessioneOperatore = Depends(sessione_corrente),
) -> dict[str, Any]:
    """GET /op/report → `{report: [...]}`. `report: []` è una risposta valida: nessun ciclo ha ancora generato nulla."""
    righe = await sess.fetch(SQL_ELENCO, casa_id, TETTO_ELENCO)
    return {"report": [voce_report(riga) for riga in righe]}


@router.get(
    "/report/{report_id}",
    operation_id="op_report_dettaglio",
    summary="Un report mensile con tutte le celle per categoria ed esito.",
    tags=["op"],
)
async def op_report_dettaglio(
    report_id: int,
    sess: SessioneOperatore = Depends(sessione_corrente),
) -> dict[str, Any]:
    riga = await sess.fetchrow(SQL_DETTAGLIO, report_id)
    if riga is None:
        raise errore(404, DETAIL_REPORT_NON_TROVATO)
    return voce_report(riga)


@router.get(
    "/report/{report_id}/export",
    operation_id="op_report_export",
    summary="Il report come file .html da scaricare (Content-Disposition: attachment), autonomo e stampabile.",
    tags=["op"],
    response_class=Response,
)
async def op_report_export(
    report_id: int,
    sess: SessioneOperatore = Depends(sessione_corrente),
) -> Response:
    riga = await sess.fetchrow(SQL_DETTAGLIO, report_id)
    if riga is None:
        raise errore(404, DETAIL_REPORT_NON_TROVATO)
    voce = voce_report(riga, con_csv=True)
    nome_file = nome_file_export(voce)
    return Response(
        content=documento_report(voce),
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nome_file}"'},
    )


def nome_file_export(voce: dict[str, Any]) -> str:
    """`report_<slug>_<AAAA-MM>.html`: chi lo trova nella cartella Download sa di che Casa e di che mese è."""
    slug = voce["casa_slug"] or voce["ambito"]
    return f"report_{slug}_{voce['mese'][:7]}.html"


def documento_report(voce: dict[str, Any]) -> str:
    """La pagina autonoma dell'export: sintesi, tabella per categoria ed esito, fonte in calce.

    Nessun asset esterno (si apre da file), nessun `<form>`/`<input>`, nessun dato personale: conteggi e categorie.
    Le celle sono `n` così com'è — «<5» e «—» sono la forma k-anonima del progetto e non si «traducono» in numeri.
    """
    titolo = f"Report mensile — {voce['casa_nome'] or 'rete delle Case'} — {voce['mese_testo']}"
    righe_tabella = "".join(
        f"<tr><td>{escape(c['categoria_testo'])}</td><td>{escape(c['esito_testo'])}</td>"
        f"<td class=\"n\">{escape(c['n'])}</td></tr>"
        for c in voce["per_categoria_esito"]
    ) or '<tr><td colspan="3" class="vuoto">Nessuna richiesta registrata nel mese.</td></tr>'
    suggerimenti = (
        f"<section><h2>Osservazioni del ciclo mensile</h2><p>{escape(str(voce['suggerimenti']))}</p></section>"
        if voce.get("suggerimenti") else ""
    )
    generato = voce["generato_ts"][:16].replace("T", " alle ")
    return f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(titolo)}</title>
<style>
  @page {{ size: A4; margin: 18mm; }}
  body {{ font-family: Commissioner, "Helvetica Neue", Arial, sans-serif; color: #1a1a1a; margin: 0; padding: 2rem; line-height: 1.45; max-width: 46rem; }}
  h1 {{ font-size: 1.5rem; margin: 0 0 .25rem; }}
  .sotto {{ margin: 0 0 1.5rem; color: #555; }}
  h2 {{ font-size: 1.05rem; margin: 1.5rem 0 .5rem; letter-spacing: .02em; text-transform: uppercase; color: #444; }}
  dl {{ display: grid; grid-template-columns: max-content 1fr; gap: .25rem 1.25rem; margin: 0; }}
  dt {{ color: #555; }} dd {{ margin: 0; font-variant-numeric: tabular-nums; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ text-align: left; padding: .4rem .5rem; border-bottom: 1px solid #ddd; }}
  th {{ font-weight: 600; color: #444; }}
  td.n {{ text-align: right; font-variant-numeric: tabular-nums; }}
  td.vuoto {{ color: #555; }}
  footer {{ margin-top: 2rem; padding-top: .75rem; border-top: 1px solid #ccc; color: #555; font-size: .9rem; }}
  @media print {{ body {{ padding: 0; }} }}
</style>
</head>
<body>
<header>
  <h1>{escape(titolo)}</h1>
  <p class="sotto">Rendiconto del mese, dalla memoria della rete delle Case di Quartiere. Il report si legge e si commenta; non si modifica.</p>
</header>
<section>
  <h2>Sintesi</h2>
  <dl>
    <dt>Richieste registrate</dt><dd>{voce['richieste']}</dd>
    <dt>Senza destinazione trovata</dt><dd>{voce['senza_risposta']}</dd>
    <dt>Proposte in attesa di decisione</dt><dd>{voce['proposte_in_attesa']}</dd>
    <dt>Proposte applicate nel mese</dt><dd>{voce['proposte_applicate']}</dd>
    <dt>Schede di servizio in scadenza</dt><dd>{voce['schede_in_scadenza']}</dd>
  </dl>
</section>
<section>
  <h2>Richieste per categoria ed esito</h2>
  <table>
    <thead><tr><th>Categoria</th><th>Esito</th><th class="n">Quante</th></tr></thead>
    <tbody>{righe_tabella}</tbody>
  </table>
  <p class="sotto">Le celle «&lt;5» indicano un numero sotto la soglia di riservatezza della rete; «—» nessuna richiesta.</p>
</section>
{suggerimenti}
<footer>
  Fonte: memoria della rete Trasi, viste k-anonime · generato dal ciclo mensile il {escape(generato)} ·
  {escape(voce['casa_nome'] or 'osservatorio di rete')} · {escape(voce['mese_testo'])}
</footer>
</body>
</html>
"""


def monta(applicazione: FastAPI) -> None:
    """Monta il router sotto `/op`, fuori dal documento OpenAPI (stessa regola di `eventi_op.monta`)."""
    applicazione.include_router(router, prefix="/op", include_in_schema=False)


__all__ = ["documento_report", "monta", "nome_file_export", "router", "voce_report"]
