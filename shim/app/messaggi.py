"""Chat interna della rete (scheda !NEW 7): messaggi CdQ ↔ CdQ ↔ PA, **senza AI**.

Il canale è una bacheca nel DB Trasi con audit e retention — **decisione §2** già presa — non uno strumento esterno
integrato: la scheda dichiara esplicitamente «Cosa ci aspettiamo che faccia l'AI: niente», e ogni integrazione di un
agente qui sarebbe fuori scopo e fuori V4/V5.

Regole dello schema (che la RLS fa rispettare, e questo modulo **non** ripete né aggira):

- `da_casa_id` NULL = messaggio della PA; `a_casa_id` NULL = **broadcast** (solo PA può inviare broadcast — la
  policy lo impone, l'endpoint non aggiunge un secondo controllo che divergerebbe);
- una Casa vede **solo le proprie conversazioni** e i broadcast (policy `SELECT`);
- un operatore CdQ inserisce solo `da_casa_id = propria Casa` e **mai** broadcast: `POST` qui accetta solo
  `a_casa` valorizzato, e l'eventuale tentativo di broadcast da una Casa è rifiutato dal DB.

Retention: i messaggi **letti** più vecchi di `[P] messaggi_retention_days` sono cancellati dal passo notturno
(`trasi.scadi_messaggi()`, chiamato da FLUSSI): questo modulo non cancella nulla. I non letti non scadono — un
sollecito mai aperto non sparisce da solo.

V5: il **testo** è libero (serve a scrivere «il microfono è rotto»), e proprio perché è libero passa dal filtro
anti-PII sui valori: una chat interna non è il posto per il codice fiscale di un cittadino. Se c'è, è 422
`dato_personale_sospetto`, non una riga scritta per distrazione.
"""

from __future__ import annotations

from typing import Any

from asyncpg.exceptions import CheckViolationError, ForeignKeyViolationError, RaiseError
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from . import pii
from .auth import SessioneOperatore, sessione_corrente
from .errori import errore

router = APIRouter()

# Tetto di pagina dichiarato (e hard-capped) per il GET: la bacheca è fatta per essere scorsa, non esportata in
# blocco; un numero più grande appartiene a Metabase, non a questa API.
TETTO_MESSAGGI = 100


class MessaggioIn(BaseModel):
    """Il corpo di `POST /op/messaggi`: destinatario e testo, nient'altro (`extra="forbid"`, V5).

    `a_casa` è lo **slug** della Casa destinataria (es. `bozzano`), obbligatorio per un operatore CdQ: il broadcast
    (`a_casa_id NULL`) è riservato alla PA dalla policy del DB, e un operatore non lo può richiedere né per via
    esplicita né per omissione.
    """

    model_config = ConfigDict(extra="forbid")

    a_casa: str = Field(min_length=1, description="Slug della Casa destinataria (es. bozzano).")
    testo: str = Field(min_length=1, max_length=2000, description="Testo del messaggio (max 2000 caratteri).")


def _traduci_db(exc: Exception) -> None:
    """Traduce le violazioni del DB in 422 parlanti, poi rilancia: mai un 500 su un input cattivo.

    I messaggi di `RaiseError` delle funzioni/policy di dominio sono in italiano e non contengono valori del chiamante.
    """
    if isinstance(exc, RaiseError):
        raise errore(422, str(exc).strip()) from exc
    if isinstance(exc, CheckViolationError):
        raise errore(422, "valore non ammesso dal modello messaggi (testo troppo lungo o campo mancante)") from exc
    if isinstance(exc, ForeignKeyViolationError):
        raise errore(422, "Casa destinataria sconosciuta") from exc
    raise


@router.get(
    "/messaggi",
    operation_id="op_messaggi_lista",
    summary="Elenca gli ultimi messaggi della propria Casa e i broadcast della rete: solo conversazioni "
    "in cui la Casa è coinvolta. Letti/non letti distinti, mai testi di altre Case.",
    tags=["op"],
)
async def op_messaggi_lista(
    limite: int = Query(default=TETTO_MESSAGGI, ge=1, le=TETTO_MESSAGGI, description="Quanti messaggi (max 100)."),
    sess: SessioneOperatore = Depends(sessione_corrente),
) -> dict[str, Any]:
    """GET /op/messaggi — ultimi 100 messaggi propri + broadcast, dal più recente.

    La visibilità è decisa dalla policy `SELECT` del DB (proprie conversazioni e broadcast), non da un filtro qui:
    il `WHERE` chiede già tutto ciò che il ruolo può leggere, e ripeterlo creerebbe una seconda copia della regola.
    `letto_ts` è esposto così la UI può marcare «non letto» senza ricalcolare nulla.

    Ogni colonna è qualificata con `m.` (l'alias di `trasi.messaggio`), e non è cosmesi: le due `JOIN` su
    `trasi.casa` portano nella query una seconda e una terza colonna `id`, quindi un `SELECT id` — o `ts`, o
    `testo` — è **ambiguo** e PostgreSQL rifiuta la query con `column reference "id" is ambiguous`. L'effetto era un
    **500** su un endpoint dell'area operatore: la bacheca dei messaggi non si apriva affatto, con l'errore
    visibile solo come «errore interno dello shim» (il traceback lo mostrava, il chiamante no).
    """
    righe = await sess.fetch(
        """
        SELECT m.id, m.da_casa_id, m.a_casa_id, m.testo, m.ts, m.letto_ts,
               CASE WHEN m.da_casa_id IS NULL THEN 'pa' ELSE cd.slug END AS da_casa,
               CASE WHEN m.a_casa_id IS NULL THEN 'broadcast' ELSE ca.slug END AS a_casa
          FROM trasi.messaggio m
          LEFT JOIN trasi.casa cd ON cd.id = m.da_casa_id
          LEFT JOIN trasi.casa ca ON ca.id = m.a_casa_id
         ORDER BY m.ts DESC, m.id DESC
         LIMIT $1
        """,
        limite,
    )
    items = [
        {
            "id": r["id"],
            "da_casa": r["da_casa"],
            "a_casa": r["a_casa"],
            "testo": r["testo"],
            "ts": r["ts"].isoformat(),
            "letto": r["letto_ts"] is not None,
            "letto_ts": r["letto_ts"].isoformat() if r["letto_ts"] is not None else None,
            # Vero se il messaggio è *della* Casa corrente: serve alla UI per distinguere «mio»/«ricevuto» senza
            # fidarsi del solo mittente testuale (la PA manda con da_casa NULL).
            "proprio": r["da_casa_id"] == sess.casa_id,
        }
        for r in righe
    ]
    return {"items": items}


@router.post(
    "/messaggi",
    operation_id="op_messaggi_invia",
    status_code=201,
    summary="Invia un messaggio dalla propria Casa a un'altra Casa della rete. Solo testo (max 2000), "
    "nessun allegato. Il broadcast è riservato alla PA: da qui si scrive solo a una Casa.",
    tags=["op"],
)
async def op_messaggi_invia(
    corpo: MessaggioIn, sess: SessioneOperatore = Depends(sessione_corrente)
) -> dict[str, Any]:
    """POST /op/messaggi — INSERT diretto (la chat interna non è dominio, V4 non la riguarda: decisione §2).

    Il filtro anti-PII è sui **valori** (`testo`), perché una chat interna non è il posto per dati personali del
    cittadino. La regola «da_casa = mia Casa» e «niente broadcast da una Casa» è della policy `INSERT`; qui la Casa
    mittente si prende dalla sessione e basta, mai dal corpo.
    """
    pii.rifiuta_se_presente(corpo.model_dump(exclude_unset=True, mode="json"))
    try:
        riga = await sess.fetchrow(
            """
            INSERT INTO trasi.messaggio (da_casa_id, a_casa_id, testo)
            VALUES ($1, (SELECT c.id FROM trasi.casa c WHERE c.slug = $2), $3)
            RETURNING id, a_casa_id, ts
            """,
            sess.casa_id,
            corpo.a_casa,
            corpo.testo,
        )
    except Exception as exc:  # noqa: BLE001 — la traduzione è compito di `_traduci_db`
        _traduci_db(exc)
    if riga is None:
        # La sotto-select non ha trovato lo slug (FK NULL violerebbe il NOT NULL prima del RETURNING): è il caso
        # «destinataria sconosciuta», già tradotto sopra se arrivasse come errore.
        raise errore(422, f"Casa destinataria sconosciuta: «{corpo.a_casa}»")
    return {"id": riga["id"], "a_casa_id": riga["a_casa_id"], "ts": riga["ts"].isoformat()}


__all__ = ["MessaggioIn", "TETTO_MESSAGGI", "op_messaggi_invia", "op_messaggi_lista", "router"]
