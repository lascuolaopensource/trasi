"""La proposta di modifica della sezione «Registra» (servizi e orari della Casa).

Un solo endpoint, `POST /op/proponi_modifica`, che **riusa** `scritture.proponi_modifica`: è la via con cui
la UI tocca il dominio, e non lo tocca — inserisce una `proposta` e si ferma lì (V4). L'applicazione al
dominio resta del flusso F9 (alle 05:00), dopo l'approvazione umana.

Da questo modulo **nessun** `UPDATE` e nessun `INSERT` su `luogo`, `casa`, `scheda_servizio` o `evento`:
servizi e orari si propongono, non si scrivono. È la parte più facile da sbagliare di tutta la sezione
«Registra» — il pulsante «salva» che scrive direttamente il dominio è la tentazione che `T-PROP-02`
intercetta — quindi la scrittura diretta non esiste qui come opzione: non c'è un ramo che la scelga.

**Perché la rotta non è quella del contratto.** `proponi_modifica` sta sotto `/v1/u/{email}` (identità
asserita da Onyx con la `X-Trasi-Key`); qui l'identità viene dal cookie di sessione, e la Casa della
proposta è quella della sessione.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import pii
from .auth import SessioneOperatore, sessione_corrente
from .errori import DETAIL_RUOLO_SENZA_ACCESSO, errore
from .scritture import ProponiModificaIn, proponi_modifica

router = APIRouter()


class PropostaIn(BaseModel):
    """Il corpo di `POST /op/proponi_modifica`: gli stessi campi del contratto, con `casa_id` fuori dal payload.

    `payload` è dichiarato come dizionario aperto e **non** come un modello proprio, ma non è una riduzione
    del presidio: `ProponiModificaIn` di `scritture` valida subito dopo con lo stesso `extra="forbid"`, e il
    campo di troppo esce come `422` che lo nomina. Un modello duplicato qui sarebbe un secondo elenco di
    campi ammessi da tenere allineato al primo — e i due divergerebbero al primo campo nuovo, con l'effetto
    che la pagina non potrebbe più proporre proprio il campo aggiunto.

    `tipo`, `entita` e `motivazione` sono invece stringhe validate a valle: l'enum dei tipi di proposta e
    l'elenco delle entità del dominio vivono in `scritture`, e ripeterli qui creerebbe la seconda copia che
    questo modello esiste per evitare.
    """

    model_config = ConfigDict(extra="forbid")

    tipo: str = Field(min_length=1)
    entita: str = Field(min_length=1)
    entita_id: int | None = Field(default=None, ge=1)
    payload: dict[str, Any]
    motivazione: str = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def _casa_non_nel_payload(self) -> "PropostaIn":
        """`payload.casa_id` è rifiutato: la Casa della proposta è quella della **sessione**.

        Il campo esiste nell'elenco chiuso del contratto congelato perché serve all'AT, che propone per
        una Casa diversa dalla propria attraverso un'identità che Onyx asserisce. Nel canale del browser
        quell'uso non esiste — l'operatore propone per la propria Casa — e ammetterlo qui sarebbe la
        prima via con cui un operatore scrive nella coda di un'altra Casa. È il criterio di `T-SHIM-10`
        («un `casa_id` nel corpo → 422») applicato **anche** al payload: senza questo controllo, il campo
        vietato al primo livello entrerebbe dal secondo, e il divieto sarebbe aggirabile con un livello
        di annidamento.
        """
        if "casa_id" in self.payload:
            raise ValueError("payload.casa_id non ammesso: la Casa della proposta è quella della sessione")
        return self


@router.post(
    "/proponi_modifica",
    operation_id="op_proponi_modifica",
    status_code=201,
    summary="Propone una modifica ai servizi, agli orari o ai dati di un elemento della rete. La modifica "
    "non è immediata: la decisione è di chi compete e l'applicazione avviene dopo l'approvazione.",
    tags=["op"],
)
async def op_proponi_modifica(
    corpo: PropostaIn, sess: SessioneOperatore = Depends(sessione_corrente)
) -> dict[str, Any]:
    """POST /op/proponi_modifica — delega a `scritture.proponi_modifica` (V4: nulla del dominio cambia qui).

    La Casa della proposta è quella della **sessione**. `casa_id` è rifiutato dal corpo di questo endpoint
    (`extra="forbid"`), e nel payload non è ammesso: senza questo, un operatore potrebbe scrivere nella coda
    di un'altra Casa, con la RLS a fare da seconda barriera invece che da prima.

    L'anti-PII è quello di `proponi_modifica` — **motivazione e payload**, perché il payload ammette campi
    testuali liberi (`indirizzo`, `descrizione`, `luogo_testo`) e una proposta è memoria permanente. Qui non
    si anticipa né si salta: `rifiuta_se_presente` viene chiamata anche prima, sul corpo di questo endpoint,
    così un payload annidato con un telefono non arriva nemmeno alla costruzione del modello a valle.

    L'esito `in_chat` dichiara se la proposta riguarda la Casa dell'operatore — cioè se la decisione è di un
    umano della rete — e **non** se l'operatore possa deciderla: `no_self_approve` (db/005) vieta alla stessa
    identità che ha proposto di approvare, e la conseguenza operativa è dichiarata nel contratto §5.4.
    """
    if sess.casa_id is None:
        raise errore(403, DETAIL_RUOLO_SENZA_ACCESSO)

    pii.rifiuta_se_presente(corpo.model_dump(exclude_unset=True, mode="json"))

    try:
        corpo_contratto = ProponiModificaIn(
            tipo=corpo.tipo,  # type: ignore[arg-type] — l'enum è verificato da pydantic, che nomina il valore
            entita=corpo.entita,
            entita_id=corpo.entita_id,
            payload=corpo.payload,
            motivazione=corpo.motivazione,
        )
    except ValueError as exc:
        # Un tipo fuori vocabolario o un campo di troppo nel payload escono come `422` con l'elenco ammesso:
        # è lo stesso testo che riceve il chiamante del contratto, perché è lo stesso modello a produrlo.
        raise errore(422, _frase(exc)) from exc

    esito = await proponi_modifica(corpo_contratto, sess)
    return {
        "proposta_id": esito["proposta_id"],
        "approvatore_ruolo": esito["approvatore_ruolo"],
        "in_chat": esito["in_chat"],
        "casa": sess.casa_slug,
    }


def _frase(exc: Exception) -> str:
    """Il messaggio di pydantic ridotto alla sua frase utile: il chiamante legge un motivo, non un preambolo."""
    for riga in str(exc).splitlines():
        riga = riga.strip()
        if riga and not riga.lower().startswith(("1 validation error", "value error", "assertion")):
            return riga
    return "parametri non ammessi"


__all__ = ["PropostaIn", "op_proponi_modifica", "router"]
