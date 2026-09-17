"""Decidere una proposta dal browser dell'operatore — `POST /op/proposte/{id}/decisione` (`T-PROP-01`).

**Il canale è nuovo, la decisione non lo è.** `shim/app/scritture.py::approva_proposta` è la via di Onyx
(`/v1/u/{email}/approva_proposta`, `X-Trasi-Key`): lì l'identità è nell'URL ed è il LLM a portarla. Qui l'identità è
il **cookie di sessione** della Casa e il chiamante è il browser. Fra i due canali cambia come si arriva alla
decisione; non deve cambiare **come la decisione è presa**.

Per questo l'unica cosa che questo modulo fa è tradurre il corpo del canale nuovo e **delegare alla funzione
esistente**: `await approva_proposta(ApprovaPropostaIn(...), sess)`. Non è una scorciatoia di stile — è l'unico modo
di rispettare la regola del piano («lo **stesso** `UPDATE` di `approva_proposta`: il database non viene riscritto
con una seconda logica», §5.4) senza duplicare nemmeno una riga di SQL. Le conseguenze che si ottengono gratis, e
che una copia avrebbe dovuto reimplementare:

- **la RLS è l'autorità.** `_righe(statuscommand) == 0` → `403 «da approvare in coda»`: nessun pre-controllo del tipo
  «questa proposta è tua?», che sarebbe una seconda copia di `upd_client` e divergerebbe alla prima modifica di
  Processi (§11 Q-01).
- **`409` prima dell'`UPDATE`**, in sola lettura: proposta già decisa (`stato != 'proposta'`) e proposta oltre
  `scade_il`. È la classificazione di uno stato che il 403 confonderebbe con una coda.
- **`422` sulla nota con dati personali** (`pii.rifiuta_se_presente`), e la nota **non** entra nei log.
- **la transizione è quella del trigger** `proposta_01_transition_tg`, con `approvato_da`/`approvato_ts` firmati dal
  database (`current_user`, `now()`) e non dal chiamante: chi decide non si firma da solo.
- **l'applicazione al dominio non è di questa chiamata.** La proposta passa a `approvata`; a scrivere la memoria è
  `applica_proposte_approvate` (F9) alle 05:00. La UI lo dichiara («in applicazione»), lo shim no: qui non c'è
  nulla da dichiarare, perché non succede.

**Il tetto della nota.** Il contratto congelato dichiara `nota: maxLength 80` e il database ha il CHECK
`proposta_nota_decisione_len ≤ 80`: 80 è quindi il limite **operativo**, e una nota più lunga è un 422 dichiarato
qui invece di un 23514 dal database. Il piano §5.4 scrive «≤200»; è il piano a essere disallineato dal contratto
congelato e dal CHECK, che sono i due documenti che non si toccano — quindi si segue il contratto, e il
disallineamento resta dichiarato invece di essere risolto in silenzio in una direzione scelta da questo file.

**Perché il corpo è ridichiarato e non riusato.** `ApprovaPropostaIn` di `scritture.py` è già la forma giusta del
corpo e viene usata per la delega; il modello qui sotto esiste solo per il **percorso** (`/op/proposte/{id}/…`), dove
l'identificativo non è nel corpo ma nell'URL: tenerlo fuori da `ApprovaPropostaIn` è ciò che rende impossibile il
caso in cui l'id dell'URL e l'id del corpo divergono — che è un modo silenzioso di decidere una proposta diversa da
quella che si stava guardando.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, FastAPI
from pydantic import BaseModel, ConfigDict, Field

from .auth import SessioneOperatore, sessione_corrente
from .scritture import ApprovaPropostaIn, approva_proposta

router = APIRouter()

# Il tetto operativo della nota: contratto congelato (`shim/openapi.yaml`, `nota: maxLength 80`) **e** CHECK
# `proposta_nota_decisione_len` di `db/001`. Uno solo dei due non basterebbe: il primo è ciò che Onyx vede, il
# secondo è ciò che il database accetta, e devono coincidere.
MAX_NOTA = 80


class DecisioneIn(BaseModel):
    """Il corpo di `POST /op/proposte/{id}/decisione`: la decisione e, facoltativa, una nota per chi legge.

    `extra="forbid"` è il presidio strutturale (V5/§12): `nota` è l'unico campo libero, e un campo in più —
    `casa_id`, `proposta_id`, `stato` — è un 422 prima di toccare il database. L'id della proposta **non** è qui:
    è nel percorso, così ce n'è uno solo.
    """

    model_config = ConfigDict(extra="forbid")

    decisione: Literal["approva", "rifiuta"]
    nota: str | None = Field(default=None, max_length=MAX_NOTA)


@router.post(
    "/proposte/{proposta_id}/decisione",
    operation_id="op_proposta_decisione",
    status_code=200,
    summary="Approva o rifiuta una proposta. Decidibile solo se la RLS lo consente al ruolo della sessione: "
    "quando la decisione è di un altro (AT) risponde 403 «da approvare in coda». L'applicazione al dominio "
    "avviene dopo, dal flusso notturno.",
    tags=["op"],
)
async def op_proposta_decisione(
    proposta_id: int,
    corpo: DecisioneIn,
    sess: SessioneOperatore = Depends(sessione_corrente),
) -> dict[str, Any]:
    """POST /op/proposte/{id}/decisione → `{"proposta_id":…, "stato":"approvata"|"rifiutata"}`.

    Tutti gli esiti — 200, 403, 409, 422 — sono prodotti da `approva_proposta`, che è la stessa funzione che serve
    la via di Onyx: qui non si traduce nessuno stato e non si intercetta nessuna eccezione. Un `except` che
    rimappasse il 403 in qualcos'altro renderebbe i due canali divergenti proprio sul caso che G-05 rende frequente.
    """
    # `Field(ge=1)` sul modello non si applica qui perché l'id è nel percorso: un id non positivo non identifica
    # una proposta, e passarlo all'`UPDATE` sarebbe una query in più per un esito già noto (403 «da approvare in
    # coda», che è ciò che `approva_proposta` risponde quando la SELECT non trova righe). La guardia è quindi la
    # stessa risposta, senza toccare il database.
    if proposta_id < 1:
        from .errori import DETAIL_DA_APPROVARE_IN_CODA, errore

        raise errore(403, DETAIL_DA_APPROVARE_IN_CODA)

    return await approva_proposta(
        ApprovaPropostaIn(proposta_id=proposta_id, decisione=corpo.decisione, nota=corpo.nota),
        sess,  # type: ignore[arg-type] — `SessioneOperatore` espone gli stessi cinque metodi di `Sessione`
    )


def monta(applicazione: FastAPI) -> None:
    """Monta il router sotto `/op`, fuori dallo schema OpenAPI congelato (lo chiama il browser, non il LLM)."""
    applicazione.include_router(router, prefix="/op", include_in_schema=False)


__all__ = ["MAX_NOTA", "DecisioneIn", "monta", "op_proposta_decisione", "router"]
