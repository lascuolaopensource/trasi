"""La coda delle proposte vista dalla Casa — `GET /op/proposte` (`T-SHIM-08`, gate **G-05**).

Questa è la parte più delicata del piano, e il motivo è una regola di governance che funziona come previsto e
produce un effetto controintuitivo sulla UI.

**Che cosa succede davvero.** La policy RESTRICTIVE `no_self_approve` (`db/005_rls_proposta.sql`) confronta
`proposto_da` con `current_user` — cioè il **ruolo DB**, non l'email. Poiché operatore e gestore della stessa Casa
condividono lo stesso ruolo (un ruolo per Casa), una proposta creata da `casa_bozzano` ha
`proposto_da = 'casa_bozzano'` e **nessun** `UPDATE` dello stesso ruolo la tocca: `UPDATE 0`, quindi 403 «da
approvare in coda». Misurato sul database reale:

- la coda di Bozzano (`v_da_approvare` con `SET LOCAL ROLE casa_bozzano`) ha **0 righe**;
- le proposte **aperte** che riguardano Bozzano (`v_proposte_aperte`, `casa_id = 8`) sono **1**: la `chiudi_luogo`
  id 2106 su `luogo_id = 1`, `approvatore_ruolo = 'at'`, `proposto_da = 'casa_bozzano'`.

Le due liste sono entrambe vere e dicono cose diverse. Una UI che leggesse solo la prima direbbe «nessuna proposta
in attesa» mentre una decisione **esiste** e aspetta qualcun altro: è una dichiarazione falsa, ed è il difetto che
questo endpoint esiste per evitare. Da qui la forma della risposta: **una lista sola**, con il campo `decidibile`
che distingue i due fatti, e `motivo_non_decidibile` che dice **chi** decide.

**Perché `decidibile` viene dalla vista e non da una condizione riscritta qui.** `v_da_approvare` è la stessa
autorità che governa l'`UPDATE` di `POST /op/proposte/{id}/decisione`. Ricostruire il predicato in SQL — o in
Python, o in JavaScript — sarebbe una seconda copia della policy: la prima volta che Processi risponde alla domanda
§11 Q-01 e cambia la regola in `upd_client`, la coda mostrerebbe pulsanti su proposte che il database rifiuta. Qui
si legge la vista e basta; l'unica cosa che il database non può dire è **perché** una riga non è decidibile, ed è
l'unica cosa che si compone qui (da `approvatore_ruolo`, `casa_id` e `proposto_da`, che non escono nella risposta).

**Minimizzazione (V5/§12).** `proposto_da` e `approvato_da` **non escono**: si usano solo dentro la query per
distinguere «la decisione è di AT» da «nessuno decide una proposta propria», e non compaiono nella risposta.
`payload` non esce intero: esce `diff_leggibile`, che è la forma che l'umano legge per decidere.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, FastAPI

from .auth import SessioneOperatore, sessione_corrente

router = APIRouter()

# Il diff di 4 proposte in database (id 2106, 2715, 2729, 2730) è **doppiamente codificato**: `diff->'dopo'` è una
# *stringa* che contiene JSON, non un oggetto. È l'eredità del difetto descritto in `scritture.py` (`json.dumps`
# più il codec `jsonb` del pool = una stringa JSON dentro un `jsonb`), riparato a monte ma già scritto in queste
# righe. Su una di esse `trasi.diff_leggibile` **solleva** — `cannot call jsonb_object_keys on a scalar` — e poiché
# la proposta 2106 è esattamente il caso di accettazione di G-05, senza questa guardia la coda dell'AT risponde
# 500 sulla riga che deve mostrare.
#
# La guardia ripara **in lettura**, senza riscrivere la riga: `jsonb_set` rimpiazza `dopo` con il valore
# decodificato solo quando è una stringa *che è JSON valido* (`IS JSON`, PG16), altrimenti lascia il diff com'è e
# `diff_leggibile` degrada al suo messaggio. Se `db/006` un giorno riparasse `diff_leggibile`, questa espressione
# ricadrebbe nel ramo `ELSE` e resterebbe un passaggio in più, non una divergenza.
DIFF_RIPARATO = """
  CASE WHEN jsonb_typeof(p.diff -> 'dopo') = 'string' AND (p.diff ->> 'dopo') IS JSON
       THEN jsonb_set(p.diff, '{dopo}', (p.diff ->> 'dopo')::jsonb)
       ELSE p.diff END
"""

# Le due popolazioni, e da dove vengono — nessuna condizione riscritta:
#   * `coda`       = `v_da_approvare`: ciò che questo ruolo può **davvero** decidere (RLS compresa). La vista è
#                    `security_invoker=true`, quindi vede esattamente il chiamante;
#   * `riguardanti` = `v_proposte_aperte` filtrata su `casa_corrente()`: le proposte aperte che riguardano la
#                    nostra Casa e **non** sono nella coda. Il `WHERE` sulla Casa è indispensabile e non ridondante:
#                    `v_proposte_aperte` è `security_invoker=false` (legge con i privilegi del proprietario, come
#                    `v_movimenti_da_confermare`), quindi al suo interno la RLS di `proposta` **non vede il
#                    chiamante** e senza il filtro si leggerebbe la coda di tutte e dieci le Case.
#                    Per `rete` e `ti` `casa_corrente()` è NULL: nessuna riga, che è la risposta giusta — un AT non
#                    ha «la propria Casa».
SQL_PROPOSTE = f"""
WITH riguardanti AS (
  SELECT ap.id
    FROM trasi.v_proposte_aperte ap
   WHERE ap.casa_id = trasi.casa_corrente()
     AND NOT EXISTS (SELECT 1 FROM trasi.v_da_approvare d WHERE d.id = ap.id)
),
scelte AS (
  SELECT id, true  AS decidibile FROM trasi.v_da_approvare
  UNION ALL
  SELECT id, false AS decidibile FROM riguardanti
)
SELECT s.decidibile,
       p.id, p.origine, p.tipo, p.entita, p.entita_id, p.motivazione,
       p.approvatore_ruolo, p.proposto_ts, p.proposto_da, p.scade_il,
       (p.scade_il IS NOT NULL AND p.scade_il < current_date) AS scaduta,
       c.slug AS casa_slug, c.nome AS casa_nome,
       (current_date - p.proposto_ts::date) AS eta_giorni,
       trasi.diff_leggibile({DIFF_RIPARATO}) AS diff_leggibile
  FROM scelte s
  JOIN trasi.proposta p ON p.id = s.id
  LEFT JOIN trasi.casa c ON c.id = p.casa_id
 ORDER BY s.decidibile DESC, eta_giorni DESC NULLS LAST, p.id
"""


def monta(applicazione: FastAPI) -> None:
    """Monta il router sotto `/op`, fuori dallo schema OpenAPI congelato (lo chiama il browser, non il LLM)."""
    applicazione.include_router(router, prefix="/op", include_in_schema=False)


def _motivo_non_decidibile(riga: Any, ruolo: str) -> str:
    """Perché questa riga non è nella coda di chi la sta leggendo — in terza persona, senza imperativi (V6).

    L'ordine dei rami è quello dell'informazione più utile, ed è deliberato: **prima lo stato della proposta**, poi
    chi decide, poi perché l'accesso non lo può fare. Sulla riga di accettazione di G-05 (id 2106:
    `approvatore_ruolo='at'`, `proposto_da='casa_bozzano'`) due cause sono vere insieme, e il piano richiede che si
    legga «la decisione è di AT»: è quella la frase che dice all'operatore a chi rivolgersi, mentre la nota
    sull'auto-approvazione da sola lascerebbe la riga senza un destinatario.

    **La scadenza sta per prima perché è la sola causa che rende la riga non decidibile per chiunque.** Il filtro
    `scade_il >= current_date` è in `v_da_approvare` ma **non** in `v_proposte_aperte`: una proposta scaduta arriva
    quindi qui come «riguardante» con `decidibile = false`, e senza questo ramo l'operatore leggerebbe «la decisione
    è di AT» su una proposta che nemmeno l'AT può più decidere — e il 409 dell'endpoint di decisione arriverebbe
    senza che niente nella lista lo avesse annunciato.

    I quattro casi, in ordine:

    1. **scaduta** (`scade_il < current_date`): non più decidibile per nessuno.
    2. **`at`/`ti`**: la decisione è della rete (il vocabolario «AT» è quello che il piano usa nella riga di
       presenza). Vale anche quando la proposta l'ha scritta questa Casa: quella coda è di un altro accesso.
    3. **gestore della propria Casa su una proposta che questa stessa Casa ha creato.** Qui la nota sull'auto-
       approvazione è l'unica spiegazione possibile, e senza di essa i pulsanti assenti sembrerebbero un difetto:
       V4 vieta l'auto-approvazione, e con un ruolo per Casa significa che la Casa non decide ciò che ha proposto.
    4. **gestore di un'altra Casa** — il nome si legge dalla riga.
    """
    if riga["scaduta"]:
        return "proposta scaduta: non è più decidibile"
    if riga["approvatore_ruolo"] == "at":
        return "la decisione è di AT"
    if riga["approvatore_ruolo"] == "ti":
        return "la decisione è del TI"
    if riga["approvatore_ruolo"] == "gestore":
        if riga["proposto_da"] is not None and riga["proposto_da"] == ruolo:
            return "la decisione è di un altro accesso: questa Casa non decide una proposta che ha creato (V4)"
        return f"la decisione è del gestore di {riga['casa_nome'] or 'un altra Casa'}"
    return "la decisione è di un altro ruolo"


def _voce(riga: Any, ruolo: str) -> dict[str, Any]:
    """Una riga della coda nella forma che la UI legge.

    `chi_decide` è il **vocabolario del database** (`at`, `gestore`, `ti`) e non una frase: la frase la compone il
    motivo, e la UI ha bisogno del valore per decidere *se* mostrare i pulsanti. Tradurlo qui in «AT» renderebbe
    impossibile distinguere il vocabolario dal testo, e il primo consumatore che confronta `chi_decide === "at"`
    smetterebbe di funzionare in silenzio.
    """
    return {
        "id": riga["id"],
        "tipo": riga["tipo"],
        "entita": riga["entita"],
        "entita_id": riga["entita_id"],
        "origine": riga["origine"],
        "eta_giorni": riga["eta_giorni"],
        "chi_decide": riga["approvatore_ruolo"],
        "decidibile": bool(riga["decidibile"]),
        "motivo_non_decidibile": None if riga["decidibile"] else _motivo_non_decidibile(riga, ruolo),
        "motivazione": riga["motivazione"],
        "diff_leggibile": riga["diff_leggibile"],
        "scade_il": riga["scade_il"].isoformat() if riga["scade_il"] else None,
    }


@router.get(
    "/proposte",
    operation_id="op_proposte",
    summary="Elenca le proposte che aspettano una decisione: quelle che questa Casa può decidere e quelle "
    "che la riguardano ma la cui decisione è di altri (AT). Per ogni riga il diff leggibile e chi decide. "
    "Sola lettura: decidere è `POST /op/proposte/{id}/decisione`.",
    tags=["op"],
)
async def op_proposte(sess: SessioneOperatore = Depends(sessione_corrente)) -> dict[str, Any]:
    """GET /op/proposte → `{"proposte":[…]}` con `decidibile` che distingue i due fatti di G-05.

    Nessuno stato della sessione produce un errore qui: un ruolo senza Casa (`rete`, `ti`) e una Casa senza
    proposte danno **lo stesso** risultato — una lista vuota — perché la vista filtra già per competenza. Un 403
    su «nessuna proposta» renderebbe la sezione «Proposte» rotta per l'AT, che è l'unico ruolo che *decide*
    davvero su queste righe.
    """
    righe = await sess.fetch(SQL_PROPOSTE)
    return {"proposte": [_voce(riga, sess.ruolo) for riga in righe]}


__all__ = ["SQL_PROPOSTE", "monta", "op_proposte", "router"]
