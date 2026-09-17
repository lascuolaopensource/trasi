"""Monitoraggio del servizio per la PA (US-4): report mensili, confronto, lacune e chat di approfondimento.

Perché questo modulo, e perché **due** router. Il report di rete è un oggetto che la PA deve **leggere** e il
referente AT deve **approvare**: è la stessa informazione vista da due identità diverse, ed entrambe passano per lo
stesso cookie di sessione — la differenza è il ruolo, non il canale. Da qui `router_pa`, che serve il browser di
`/pa.html`: lettura dei report approvati (più le proprie bozze, per `rete`), confronto fra mesi, lacune di
risposta, esportazione stampabile e la chat di approfondimento.

`router_m` invece è la via di Onyx — le tool call del LLM, identiche come forma agli altri `/v1/u/…`: email nel
percorso, `X-Trasi-Key` nell'header, transazione a ruolo. Serve le **stesse** viste in JSON, perché Onyx non deve
scoprire un meccanismo diverso per lo stesso dominio: il monitoraggio PA è una conversazione (§8), quindi il tool
parla come gli altri tool del contratto, e un solo ruolo (`pa`) può usarlo — non è un'identità generica che chiede
i report: sarebbe un modo per aggirare la policy che solo `pa`, `rete` e `ti` hanno per lettura.

Tre cose da difendere, e dove vivono:

- **Nessun dato grezzo sotto soglia.** Ogni conteggio che esce da questo modulo passa da `k_anon`;
  `n_label` è il formato («<5», «—»), `n` è l'intero **solo quando** è sopra soglia. L'export stampabile usa
  gli stessi valori: stampare un numero che il browser non vedrebbe sarebbe una via laterale al k-anonimato.
- **Mai un testo di chat nei log Trasi.** Il modulo scrive in `chat_interazione_log` la *traccia* (esito,
  fonte, k-anon) e **non** il testo: la conversazione sta nella memoria di Onyx (retention 30 giorni),
  e Trasi deve poter dire che non la conserva (V5).
- **L'approvazione è una transazione sola.** `approva_report` è `SECURITY DEFINER` e porta audit: lo shim
  la chiama e, se Postgres dice che lo stato non era `bozza`, risponde 409. Non c'è un «controlla e poi
  approva»: sarebbero due letture da tenere coerenti sotto concorrenza, e il database è l'autorità.

**Nessun endpoint scrive il dominio.** Il modulo legge le viste di report e delega a Onyx la risposta, o chiama una
funzione di transizione esplicita (`approva_report`, con il proprio audit). La chat PA scrive solo la traccia della
conversazione (canale='pa'), che è l'eccezione dichiarata al flusso proposte: è un log di interazione, non una
modifica della memoria.
"""

from __future__ import annotations

import html
import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from . import chat as modulo_chat
from . import pii
from .auth import SessioneServizio, sessione_servizio_corrente, sessione_servizio_tra
from .db import Sessione, _pool_corrente, sessione
from .errori import errore

logger = logging.getLogger("trasi.shim")

router_pa = APIRouter(prefix="/pa", tags=["pa"])
router_m = APIRouter(prefix="/v1/m/{email}", tags=["pa"])

EMAIL_PA = "pa@trasi.local"

# La persona Onyx che risponde alla chat di approfondimento: default 7 (provisioning reale 2026-09-17:
# la 5 era occupata dai Portinaio). Il commento del .env segue questo valore.
PERSONA_PA_DEFAULT = 7

# Dettagli d'errore, dichiarati una volta sola: la forma della risposta è contratto, non una scelta locale.
DETAIL_REPORT_NON_TROVATO = "report non trovato"
DETAIL_STATO_NON_APPROVABILE = "il report non è in stato approvabile"
DETAIL_CHAT_PA_NON_CONFIGURATA = "chat non configurata per la PA"
DETAIL_NON_AUTORIZZATO = "identità non autorizzata al canale di monitoraggio"

# Il testo di chatura di approfondimento ha lo stesso tetto dello sportello (2000 caratteri), ed è testo libero
# dell'operatore: il filtro anti-PII si applica qui come su `op_chat`, perché il messaggio esce verso il provider.
MESSAGGIO_MASSIMO = 2000


# Le dipendenze sono istanziate **una volta sola** per ruolo, non a ogni endpoint: `sessione_servizio_corrente`
# è una factory e due chiamate danno due funzioni distinte, e se le dipendenze fossero create nel decoratore gli
# override dei test non saprebbero quale chiave usare.
_DIPENDENZA_PA = sessione_servizio_corrente("pa")
_DIPENDENZA_RETE = sessione_servizio_corrente("rete")
# La dashboard la leggono entrambi i ruoli di servizio: `pa` (Pubblica Amministrazione) e `rete` (referente AT,
# che in più approva). L'approvazione resta una dipendenza a parte, solo `rete`.
_DIPENDENZA_DASHBOARD = sessione_servizio_tra(("pa", "rete"))


class MessaggioPA(BaseModel):
    """Il corpo di `POST /pa/chat`: **una** chiave, e nient'altro (`extra="forbid"`, V5)."""

    model_config = ConfigDict(extra="forbid")

    messaggio: str = Field(min_length=1, max_length=MESSAGGIO_MASSIMO)


def _data_o_niente(valore: str | None) -> date | None:
    """Il primo giorno del mese, oppure `None` se il parametro non è una data ISO."""
    if valore is None:
        return None
    try:
        return date.fromisoformat(str(valore).strip()[:10])
    except ValueError:
        return None


def _riga_dict(riga: Any) -> dict[str, Any]:
    """Una riga del driver come dizionario Python: l'endpoint risponde sempre nello stesso formato, e i test con
    doppi leggono la stessa struttura della produzione."""
    return dict(riga)


def _mese_parametro(mese: str | None) -> date | None:
    """Il mese come data, normalizzato al primo giorno. `None` se il parametro non è interpretabile."""
    if not mese:
        return None
    testo = mese.strip()
    # `YYYY-MM`: primo del mese. Nient'altro: «gennaio» o «2026-09-15 a caso» restano fuori, e il chiamante
    # trova un 422 parlante invece di un risultato vuoto incomprensibile.
    if len(testo) == 7 and testo[4] == "-":
        testo = f"{testo}-01"
    return _data_o_niente(testo)


def _mese_corrente(sess: SessioneServizio | Sessione) -> Any:
    """Il mese più recente per cui esiste un report o una statistica di servizio.

    `COALESCE` e non `MAX(report.mese)`: un ciclo senza report (report non ancora persistito) non deve
    rendere il parametro obbligatorio — così i tool di Onyx, chiamati dal LLM senza un parametro esplicito,
    trovano comunque un mese da cui partire.
    """
    return sess.fetchval(
        """
        SELECT COALESCE(
            (SELECT max(mese) FROM trasi.report WHERE stato IN ('approvato','inviato_pa')),
            date_trunc('month', current_date)::date
        )
        """
    )


async def _righe_report(
    sess: SessioneServizio | Sessione, mese: date | None, ambito: str | None = None
) -> list[dict[str, Any]]:
    """Le righe di `trasi.report` che il ruolo può vedere (la RLS decide; qui si espone solo la vista).

    La SELECT è fatta con `security_invoker=true` (`v_report`): i bozze arrivano a `rete` e `ti`, solo gli
    approvati/inviati a `pa`. Lo stesso risultato con una WHERE nello shim duplicherebbe la policy del database
    in un secondo punto da tenere allineato, e la policy resta la sola autorità.
    """
    condizioni: list[str] = []
    argomenti: list[Any] = []
    if mese is not None:
        condizioni.append(f"mese = ${len(argomenti) + 1}")
        argomenti.append(mese)
    if ambito is not None:
        condizioni.append(f"ambito = ${len(argomenti) + 1}")
        argomenti.append(ambito)
    where = " WHERE " + " AND ".join(condizioni) if condizioni else ""
    righe = await sess.fetch(
        f"""
SELECT r.id, r.casa_id, r.casa_slug, r.casa_nome, r.mese, r.ambito,
       r.contenuti, r.generato_ts, r.generato_da, r.ha_csv, r.commenti,
       r.ultimo_commento_ts, r.stato
  FROM trasi.v_report r
{where}
 ORDER BY r.mese DESC, r.casa_slug NULLS LAST
        """,
        *argomenti,
    )
    return [_riga_dict(r) for r in righe]


async def _report_dettaglio(sess: SessioneServizio | Sessione, report_id: int) -> dict[str, Any] | None:
    """La riga piena del report (contenuti jsonb) e i commenti: una sola coppia di query.

    La riga senza policy è esclusa dalla RLS di `v_report`: qui non si fa una seconda WHERE, si restituisce
    `None` se la riga non esce, perché il database ha già deciso.
    """
    riga = await sess.fetchrow(
        """
SELECT r.id, r.casa_id, r.casa_slug, r.casa_nome, r.mese, r.ambito,
       r.contenuti, r.generato_ts, r.generato_da, r.commenti, r.ultimo_commento_ts,
       r.stato, r.approvato_da, r.approvato_ts, r.inviato_pa_ts, r.csv
  FROM trasi.v_report r
 WHERE r.id = $1
        """,
        report_id,
    )
    if riga is None:
        return None
    report = _riga_dict(riga)
    commenti = await sess.fetch(
        """
SELECT c.id, c.casa_slug, c.casa_nome, c.testo, c.ts
  FROM trasi.v_commento c
 WHERE c.entita = 'report' AND c.entita_id = $1
 ORDER BY c.ts
        """,
        report_id,
    )
    report["commenti_lista"] = [_riga_dict(c) for c in commenti]
    return report


async def _righe_confronto(mesi: int, sess: SessioneServizio | Sessione) -> list[dict[str, Any]]:
    """Le righe di `v_report_confronto` per gli ultimi `mesi` mesi, ordinate per data decrescente.

    La vista restituisce una riga per (mese, categoria, esito). Il filtro per mese è `>=` un mese limite, non
    `IN` un elenco: è la forma più semplice per il LLM e non presuppone dati continui.
    """
    righe = await sess.fetch(
        """
SELECT mese, categoria, esito, n, n_label, n_prec, n_prec_label, delta_pct
  FROM trasi.v_report_confronto
 WHERE mese >= date_trunc('month', current_date)::date - ($1::int - 1) * interval '1 month'
 ORDER BY mese DESC, categoria, esito
        """,
        mesi,
    )
    return [_riga_dict(r) for r in righe]


async def _righe_lacune(mese: date, sess: SessioneServizio | Sessione) -> dict[str, Any]:
    """Le due metà delle lacune: richieste senza risposta e chat in errore.

    La prima viene da `v_report_mensile` per conteggi k-anon per Casa; la seconda da `v_chat_mensile` per la
    traccia di utilizzo del canale (sportello + PA). Restano due elenchi, non una fusione: il LLM deve poter
    distinguere «la risposta non c'era» da «il canale non ha funzionato».
    """
    richieste = await sess.fetch(
        """
SELECT casa_slug, casa_nome, categoria, n, n_label
  FROM trasi.v_report_mensile
 WHERE mese = $1 AND esito = 'non_trovata'
 ORDER BY n DESC NULLS LAST, casa_slug
        """,
        mese,
    )
    chat = await sess.fetch(
        """
SELECT mese, casa_slug, canale, esito, fonte, n, n_label
  FROM trasi.v_chat_mensile
 WHERE mese = $1 AND esito = 'errore'
 ORDER BY canale, casa_slug
        """,
        mese,
    )
    return {
        "mese": str(mese),
        "richieste_non_trovate": [_riga_dict(r) for r in richieste],
        "chat_errori": [_riga_dict(r) for r in chat],
    }


async def _righe_chat_stats(mese: date, sess: SessioneServizio | Sessione) -> list[dict[str, Any]]:
    """Le righe di `v_chat_mensile` per il mese: canale, esito e fonte, mai il testo.

    La vista espone già la forma k-anon, quindi qui non si aggrega: si legge e si risponde. Lo stesso criterio
    è nel modulo: un numero sotto soglia non è un'eccezione da trattare, è il formato della risposta.
    """
    righe = await sess.fetch(
        """
SELECT mese, casa_slug, canale, esito, fonte, n, n_label
  FROM trasi.v_chat_mensile
 WHERE mese = $1
 ORDER BY canale, esito, fonte NULLS LAST, casa_slug
        """,
        mese,
    )
    return [_riga_dict(r) for r in righe]


async def _log_chat(
    sess: SessioneServizio, canale: str, esito: str, fonte: str | None, pool: Any | None = None
) -> None:
    """La traccia della conversazione in `chat_interazione_log`, senza il testo (V5). Mai far fallire la risposta.

    **L'INSERT passa dalla connessione della sessione** (ruolo `pa` già assunto), per la stessa ragione dello
    sportello: la policy `chatlog_ins_pa` (db/026) ammette il ruolo `pa`, mentre una connessione presa dal pool
    avrebbe il ruolo `shim_rw`, che non ha policy INSERT — la riga non entrava mai (misurato il 17/09).
    Il log resta **best-effort**: se il database non accetta la riga, la conversazione risponde lo stesso e il
    guasto resta nel log dello shim. `pool` è il parametro che i test passano per intercettare l'INSERT.
    """
    try:
        if pool is not None:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
INSERT INTO trasi.chat_interazione_log (casa_id, canale, esito, fonte)
VALUES ($1, $2, $3, $4)
                    """,
                    None,
                    canale,
                    esito,
                    fonte,
                )
            return
        await sess.execute(
            """
INSERT INTO trasi.chat_interazione_log (casa_id, canale, esito, fonte)
VALUES ($1, $2, $3, $4)
            """,
            None,
            canale,
            esito,
            fonte,
        )
    except Exception as guasto:
        # Il **tipo** dell'errore, non il contenuto della conversazione: senza questo, «il log non entra»
        # resta una diagnosi impossibile (è già successo: l'INSERT passava da una connessione col ruolo
        # sbagliato e l'unico sintomo era un warning muto).
        logger.warning("log chat non scritto (%s: %s): la risposta resta valida", type(guasto).__name__, guasto)


def _fonte_conversazione(esito: Any) -> str:
    """La fonte dichiarata da `_conversa` come valore per `chat_interazione_log.fonte`.

    Il badge di `chat.fonte_dal_corpo` è una stringa leggibile per la risposta; il CHECK della tabella accetta
    solo `kb`/`esterna`/`nessuna`, quindi qui si traduce la forma del badge nella forma del database.
    """
    if not isinstance(esito, modulo_chat.Conversazione):
        return "nessuna"
    if esito.fonte.startswith("[Esterna"):
        return "esterna"
    if esito.fonte.startswith("[KB"):
        return "kb"
    return "nessuna"


# ---------------------------------------------------------------------------
# Router `/pa` — il browser del ruolo `pa` (e anche di `rete`, che approva)
# ---------------------------------------------------------------------------


@router_pa.get(
    "/me",
    operation_id="pa_me",
    summary="Chi è questa sessione di servizio: il ruolo, senza altri dati. 401 se il cookie è assente o scaduto.",
)
async def pa_me(sess: SessioneServizio = Depends(_DIPENDENZA_DASHBOARD)) -> dict[str, Any]:
    """GET /pa/me → `{ruolo}`: ciò che la dashboard mostra per confermare «sei entrato come PA».

    Il ruolo è esposto perché è il vocabolario del runbook; niente email e niente Casa: questo canale non li
    conosce.
    """
    return {"ruolo": sess.ruolo}


@router_pa.get(
    "/report",
    operation_id="pa_report",
    summary="I report mensili dell'osservatorio che il ruolo può vedere (approvati e inviati alla PA; "
    "per `rete` anche quelli in bozza).",
)
async def pa_report(
    mese: str | None = Query(default=None, description="Mese (YYYY-MM); se omesso, tutti"),
    sess: SessioneServizio = Depends(_DIPENDENZA_DASHBOARD),
) -> dict[str, Any]:
    """GET /pa/report → `{items}`: lo storico dei report, con lo stato visibile a questo ruolo.

    Per `pa` la policy mostra solo `approvato`/`inviato_pa`; per `rete` anche le bozze, perché è il referente che
    decide. Il parametro `mese` riduce l'elenco a un solo mese; senza, la lista è tutta l'osservatorio.
    """
    return {"items": await _righe_report(sess, _mese_parametro(mese), ambito="osservatorio")}


@router_pa.get(
    "/report/confronto",
    operation_id="pa_confronto",
    summary="I confronti mese-su-mese della rete, con conteggi k-anon e delta rispetto al mese precedente.",
)
async def pa_confronto(
    mesi: int = Query(default=2, ge=1, le=12, description="Quanti mesi guardare indietro"),
    sess: SessioneServizio = Depends(_DIPENDENZA_DASHBOARD),
) -> dict[str, Any]:
    """GET /pa/report/confronto?mesi=2 → `{items}`: i dati di `v_report_confronto`.

    Il tetto di 12 mesi è dichiarato: il confronto copre un anno, che è la scala utile per l'osservatorio di rete.
    I conteggi escono solo in forma k-anonima (`n_label` è la forma leggibile; `n` è l'intero solo sopra soglia).
    """
    return {"items": await _righe_confronto(mesi, sess)}


@router_pa.get(
    "/lacune",
    operation_id="pa_lacune",
    summary="Le lacune del servizio per il mese: richieste senza risposta (per Casa) ed errori della chat.",
)
async def pa_lacune(
    mese: str | None = Query(default=None, description="Mese (YYYY-MM); se omesso, il più recente con report"),
    sess: SessioneServizio = Depends(_DIPENDENZA_DASHBOARD),
) -> dict[str, Any]:
    """GET /pa/lacune?mese=… → `{mese, richieste_non_trovate, chat_errori}`.

    Le due metà sono volutamente separate: «la risposta non c'era» e «il canale non ha funzionato» sono due
    problemi diversi, e fonderli darebbe al LLM un unico elenco da cui non saprebbe distinguere la diagnosi.
    """
    il_mese = _mese_parametro(mese) or await _mese_corrente(sess)
    return await _righe_lacune(il_mese, sess)


@router_pa.get(
    "/report/{report_id}",
    operation_id="pa_report_dettaglio",
    summary="Il dettaglio di un report: contenuti, commenti e stato di approvazione.",
)
async def pa_report_dettaglio(
    report_id: int,
    sess: SessioneServizio = Depends(_DIPENDENZA_DASHBOARD),
) -> dict[str, Any]:
    """GET /pa/report/{id} → il report completo, o 404 se non è visibile a questo ruolo.

    Il 404 è la risposta della RLS (la riga non esce dalla `SELECT`), non un controllo applicativo: così il ruolo
    `pa` non può distinguere «report inesistente» da «report in bozza», e non scopre lo stato altrui enumerando id.
    """
    report = await _report_dettaglio(sess, report_id)
    if report is None:
        raise errore(404, DETAIL_REPORT_NON_TROVATO)
    return report


@router_pa.get(
    "/report/{report_id}/export",
    operation_id="pa_report_export",
    summary="Il report come pagina HTML stampabile, con le tabelle k-anonime e la fonte dichiarata nel footer.",
    response_class=HTMLResponse,
)
async def pa_report_export(
    report_id: int,
    sess: SessioneServizio = Depends(_DIPENDENZA_DASHBOARD),
) -> HTMLResponse:
    """GET /pa/report/{id}/export → HTML stampabile.

    Stessa filosofia del biglietto dell'operatore: una pagina autonoma, con `@page`/`@media print`, che la PA può
    aprire e stampare. I conteggi sono quelli k-anonimi delle viste; i testi sotto forma di suggerimento sono
    quelli che il flusso mensile ha scritto. La fonte è dichiarata nel footer, perché una pagina stampata si legge
    fuori dal sistema e deve portare con sé la provenienza.
    """
    report = await _report_dettaglio(sess, report_id)
    if report is None:
        raise errore(404, DETAIL_REPORT_NON_TROVATO)
    return HTMLResponse(_documento_report(report))


def _documento_report(report: dict[str, Any]) -> str:
    """La pagina HTML dell'export: autonoma, stampabile, con fonte dichiarata nel footer.

    I conteggi non sono formattati qui — sono già in `n_label`, che è la forma che il progetto dichiara k-anonima.
    Se i suggerimenti del ciclo mensile sono presenti in `contenuti.suggerimenti`, sono testo, non numeri, e non
    passano filtri: sono l'output informativo deliberato del report.
    """
    mese = report["mese"]
    titolo_mese = f"{mese.year}-{mese.month:02d}" if hasattr(mese, "year") else str(mese)
    contenuti = report.get("contenuti") or {}
    if isinstance(contenuti, str):
        import json

        try:
            contenuti = json.loads(contenuti)
        except ValueError:
            contenuti = {}
    if not isinstance(contenuti, dict):
        contenuti = {}

    # I contenuti sono un oggetto libero: si esclude solo ciò che è chiaramente un dato grezzo (un elenco di
    # richieste con data/ora singola), perché una pagina di report deve essere leggibile da un tavolo.
    voci = {
        chiave: valore
        for chiave, valore in contenuti.items()
        if chiave not in ("richieste", "csv") and valore is not None
    }

    def _tabella(dati: dict[str, Any] | list[Any] | None, etichetta: str) -> str:
        if not dati:
            return ""
        if isinstance(dati, dict):
            righe = "".join(f"<tr><th>{html.escape(str(k))}</th><td>{html.escape(str(v))}</td></tr>" for k, v in dati.items())
            return f"<h2>{html.escape(etichetta)}</h2><table>{righe}</table>"
        if isinstance(dati, list):
            if not dati:
                return ""
            intestazione = ""
            corpo = ""
            if isinstance(dati[0], dict):
                colonne = list(dati[0].keys())
                intestazione = "<tr>" + "".join(f"<th>{html.escape(str(c))}</th>" for c in colonne) + "</tr>"
                corpo = "".join(
                    "<tr>"
                    + "".join(f"<td>{html.escape(str(voce.get(c, '')))}</td>" for c in colonne)
                    + "</tr>"
                    for voce in dati
                )
                return (
                    f"<h2>{html.escape(etichetta)}</h2><table><thead>{intestazione}</thead><tbody>{corpo}</tbody></table>"
                )
            return (
                f"<h2>{html.escape(etichetta)}</h2><ul>"
                + "".join(f"<li>{html.escape(str(v))}</li>" for v in dati)
                + "</ul>"
            )
        return ""

    corpo_voci = "".join(
        _tabella(valore, chiave.replace("_", " ")) if isinstance(valore, (dict, list)) else f"<p><strong>{html.escape(chiave)}</strong>: {html.escape(str(valore))}</p>"
        for chiave, valore in voci.items()
    )

    suggerimenti = contenuti.get("suggerimenti")
    blocco_suggerimenti = (
        f"<h2>Suggerimenti</h2><p>{html.escape(str(suggerimenti))}</p>" if suggerimenti else ""
    )

    return f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8">
<title>Report osservatorio Trasi — {html.escape(titolo_mese)}</title>
<style>
@page {{ margin: 2cm; size: A4; }}
@media print {{ .no-print {{ display: none; }} }}
body {{ font-family: sans-serif; font-size: 11pt; color: #000; max-width: 21cm; margin: 0 auto; padding: 1em; }}
h1 {{ font-size: 16pt; margin-bottom: 0.3em; }}
h2 {{ font-size: 13pt; margin-top: 1.2em; }}
table {{ border-collapse: collapse; width: 100%; margin: 0.5em 0; }}
th, td {{ border: 1px solid #444; padding: 0.3em 0.5em; text-align: left; vertical-align: top; }}
th {{ background: #eee; }}
footer {{ margin-top: 2em; font-size: 9pt; color: #333; border-top: 1px solid #999; padding-top: 0.5em; }}
</style>
</head>
<body>
<header>
<h1>Report mensile dell'osservatorio Trasi</h1>
<p>Mese di riferimento: <strong>{html.escape(titolo_mese)}</strong> · Casa: {html.escape(str(report.get("casa_nome") or "Rete intera"))} · stato: {html.escape(str(report["stato"]))}</p>
</header>
<main>
{corpo_voci}
{blocco_suggerimenti}
</main>
<footer>
Fonte: viste trasi.* — mese {html.escape(titolo_mese)}.
I conteggi sotto soglia sono espressi come «&lt;5» o «—» (k-anonimato, §12): nessun numero grezzo è presente in questo report.
</footer>
</body>
</html>
"""


@router_pa.post(
    "/report/{report_id}/approva",
    operation_id="pa_approva",
    summary="Il referente di rete approva un report in bozza: transizione atomica, 409 se non è più in bozza.",
)
async def pa_approva(
    report_id: int,
    sess: SessioneServizio = Depends(_DIPENDENZA_RETE),
) -> dict[str, Any]:
    """POST /pa/report/{id}/approva → 200 `{id, stato}`; 404 se il report non è visibile; 409 su stato non valido.

    È l'unica scrittura di questo modulo. Non è fatta dallo shim: è `trasi.approva_report`, `SECURITY DEFINER`, con
    il suo audit, e lo shim traduce il suo errore in 409. Quindi «lo stato è cambiato» e «il report è sparito sotto
    le mani» sono due risposte diverse, entrambe dichiarate.
    """
    try:
        await sess.execute("SELECT trasi.approva_report($1)", report_id)
    except Exception as exc:
        # Postgres solleva quando lo stato non è 'bozza': il 409 è questo, e il messaggio della funzione non è
        # contratto. Qualunque altro errore (permesso negato, funzione assente) diventa 500 come da regola §9.1.
        if "bozza" in str(exc) or "stato" in str(exc):
            raise errore(409, DETAIL_STATO_NON_APPROVABILE) from exc
        raise
    return {"id": report_id, "stato": "approvato"}


@router_pa.post(
    "/chat",
    operation_id="pa_chat",
    summary="Approfondisce un report con l'assistente Onyx: la domanda va al provider come identità PA.",
)
async def pa_chat(
    corpo: MessaggioPA,
    sess: SessioneServizio = Depends(_DIPENDENZA_DASHBOARD),
) -> dict[str, Any]:
    """POST /pa/chat `{messaggio}` → 200 `{risposta, fonte}`; 422 su dato personale; 503 se la chat non è configurata.

    Stessa logica di `op_chat` — lo stesso `_conversa`, lo stesso budget di tempo — con la differenza che qui la
    conversazione è attribuita a `pa@trasi.local` (persona «Trasi Monitoraggio PA») e la traccia va su
    `chat_interazione_log` con `canale='pa'`. Il messaggio non finisce nei log Trasi: il solo fatto che la chat
    sia avvenuta e il suo esito sono la traccia (V5).
    """
    pii.rifiuta_se_presente({"messaggio": corpo.messaggio})

    configurazione_chat = modulo_chat.configurazione()
    if not configurazione_chat.token:
        raise errore(503, DETAIL_CHAT_PA_NON_CONFIGURATA)

    # **La chat PA usa una PAT propria** (`ONYX_CHAT_PA_TOKEN`), non quella dello sportello: la PAT decide
    # l'identità con cui Onyx invoca i tool, e il canale di monitoraggio accetta solo `pa@trasi.local`
    # (guardia `_sessione_pa`). Con la PAT dello sportello — che appartiene a una Casa — ogni tool del
    # monitoraggio risponde 403 e l'assistente non ha dati: verificato in esercizio il 17/09.
    # Se la PAT dedicata non è configurata, la chat PA **dichiara** di non essere configurata invece di
    # usare quella sbagliata: un 503 leggibile è meglio di una risposta costruita su un rifiuto.
    token_pa = modulo_chat._variabile("ONYX_CHAT_PA_TOKEN")
    if not token_pa:
        raise errore(503, DETAIL_CHAT_PA_NON_CONFIGURATA)

    configurazione_pa = modulo_chat.ConfigurazioneChat(
        base_url=configurazione_chat.base_url,
        token=token_pa,
        # La persona PA ha una variabile **sua** (`ONYX_PERSONA_PA_ID`), non quella dello sportello: gli assistenti
        # sono due identità distinte in Onyx, e il default è l'id reale provisionato (7).
        persona_id=modulo_chat._intero(modulo_chat._variabile("ONYX_PERSONA_PA_ID"), PERSONA_PA_DEFAULT),
        timeout_s=configurazione_chat.timeout_s,
    )

    email = EMAIL_PA  # la conversazione è attribuita alla PA; nessuna email di persona in questa via
    esito = await modulo_chat._conversa(configurazione_pa, corpo.messaggio, email)
    if isinstance(esito, modulo_chat.Guasto):
        await _log_chat(sess, "pa", "errore", None)
        raise errore(503, esito.detail)

    await _log_chat(sess, "pa", "risposta", _fonte_conversazione(esito))
    return {"risposta": esito.testo, "fonte": esito.fonte}


# ---------------------------------------------------------------------------
# Router `/v1/m/{email}` — i tool di Onyx, solo per ruolo `pa`
# ---------------------------------------------------------------------------


async def _sessione_pa(sess: Sessione = Depends(sessione)) -> Sessione:
    """La guardia dei tool di monitoraggio: l'identità Onyx deve essere quella della PA.

    `sessione` risolve l'identità e assume il ruolo DB; qui si aggiunge il vincolo che il ruolo sia esattamente
    `pa`, perché il monitoraggio non è uno strumento generico dello shim. La risposta è 403 dedicato, così il LLM
    capisce che il tool non è per l'identità che sta usando.
    """
    if sess.ruolo != "pa":
        raise errore(403, DETAIL_NON_AUTORIZZATO)
    return sess


@router_m.get(
    "/report",
    operation_id="monitoraggio_report",
    summary="I report approvati dell'osservatorio più recenti, in forma JSON: il punto di ingresso del monitoraggio.",
)
async def m_report(
    mese: str | None = Query(default=None, description="Mese (YYYY-MM); se omesso, il più recente approvato"),
    sess: Sessione = Depends(_sessione_pa),
) -> dict[str, Any]:
    """GET /v1/m/{email}/report → `{items}`: i report che la PA vede in dashboard.

    Solo `ambito='osservatorio'`: il report per Casa è un oggetto della Casa, non del monitoraggio PA.
    """
    return {"items": await _righe_report(sess, _mese_parametro(mese), ambito="osservatorio")}


@router_m.get(
    "/confronto",
    operation_id="monitoraggio_confronto",
    summary="Confronto fra gli ultimi mesi della rete, con conteggi k-anon e delta percentuale.",
)
async def m_confronto(
    mesi: int = Query(default=2, ge=1, le=12, description="Quanti mesi guardare indietro"),
    sess: Sessione = Depends(_sessione_pa),
) -> dict[str, Any]:
    """GET /v1/m/{email}/confronto?mesi=2 → `{items}`: i dati di `v_report_confronto` in JSON."""
    return {"items": await _righe_confronto(mesi, sess)}


@router_m.get(
    "/lacune",
    operation_id="monitoraggio_lacune",
    summary="Le lacune del servizio: richieste senza risposta per Casa ed errori della chat per il mese.",
)
async def m_lacune(
    mese: str | None = Query(default=None, description="Mese (YYYY-MM); se omesso, il più recente con report"),
    sess: Sessione = Depends(_sessione_pa),
) -> dict[str, Any]:
    """GET /v1/m/{email}/lacune → `{mese, richieste_non_trovate, chat_errori}`.

    Le due metà restano separate, come nella dashboard: «manca la risposta» e «il canale non ha funzionato»
    sono due diagnosi diverse, e il LLM deve poterle nominare separatamente.
    """
    il_mese = _mese_parametro(mese) or await _mese_corrente(sess)
    return await _righe_lacune(il_mese, sess)


@router_m.get(
    "/chat_stats",
    operation_id="monitoraggio_chat_stats",
    summary="L'utilizzo della chat (sportello e PA) per il mese: canale, esito e fonte, mai il testo.",
)
async def m_chat_stats(
    mese: str | None = Query(default=None, description="Mese (YYYY-MM); se omesso, il più recente con report"),
    sess: Sessione = Depends(_sessione_pa),
) -> dict[str, Any]:
    """GET /v1/m/{email}/chat_stats → `{items}`: le righe di `v_chat_mensile` in JSON.

    La vista espone già la forma k-anonimo (`n_label` è «<5» sotto soglia): qui non si riformatta, si passa. Il
    testo della conversazione non esiste da nessuna parte di questa risposta.
    """
    il_mese = _mese_parametro(mese) or await _mese_corrente(sess)
    return {"items": await _righe_chat_stats(il_mese, sess)}


def monta(applicazione: FastAPI) -> None:
    """Monta i due router fuori dallo schema OpenAPI del contratto congelato.

    - `router_pa` sotto `/pa`, `include_in_schema=False`: la dashboard PA è un'area del browser, non un tool di Onyx.
    - `router_m` sotto `/v1/m`, **anch'esso** `include_in_schema=False`: il documento deve restare uguale alle nove
      operazioni del gate V-09. La specifica di questi quattro strumenti è scritta in `openapi_monitoraggio.yaml`,
      che Onyx registra come secondo tool custom — il contratto congelato non deve cambiare per un'aggiunta.
    """
    applicazione.include_router(router_pa, include_in_schema=False)
    applicazione.include_router(router_m, include_in_schema=False)


__all__ = [
    "EMAIL_PA",
    "MessaggioPA",
    "PERSONA_PA_DEFAULT",
    "m_chat_stats",
    "m_confronto",
    "m_lacune",
    "m_report",
    "monta",
    "pa_approva",
    "pa_chat",
    "pa_confronto",
    "pa_lacune",
    "pa_me",
    "pa_report",
    "pa_report_dettaglio",
    "pa_report_export",
    "router_m",
    "router_pa",
]
