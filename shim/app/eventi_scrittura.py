"""La scrittura dell'evento della Casa (sezione «Registra» dell'Account).

Un solo endpoint, `POST /op/eventi`, che **riusa** `scritture.crea_evento`: è la scrittura diretta ammessa
per gli eventi della propria Casa (decisione S2, «opzione A»). L'operatore della Casa è anche il gestore,
quindi far passare l'aggiunta di un evento in bacheca da una proposta significherebbe aspettare la notte per
una cosa che nessun secondo umano deve approvare. Il dominio resta protetto dalla policy `evento_ins_casa`
(`casa_id = casa_corrente()`) e la tracciabilità dai trigger di scrittura.

**Perché questo modulo non contiene l'INSERT.** Il corpo è validato qui, ma la scrittura è **la stessa
funzione** dell'operazione del contratto congelato — non una copia della query. Due INSERT paralleli
divergerebbero al primo campo aggiunto, e il secondo non passerebbe dal filtro anti-PII né dai controlli di
coerenza delle date: sarebbe una seconda via di scrittura travestita da riuso.

**Perché la rotta non è quella del contratto.** `crea_evento` sta sotto `/v1/u/{email}` e la chiama Onyx con
la `X-Trasi-Key`: l'email nel percorso è l'identità che **Onyx** asserisce. Qui l'identità viene dal cookie
di sessione (`casa_id` in `trasi.sessione`), ed è la ragione per cui questo indirizzo non porta un'email.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from .auth import SessioneOperatore, sessione_corrente
from .errori import DETAIL_RUOLO_SENZA_ACCESSO, errore
from .scritture import CreaEventoIn, crea_evento

router = APIRouter()


class EventoIn(BaseModel):
    """Il corpo di `POST /op/eventi`: gli stessi campi di `CreaEventoIn`, senza `casa_id` (V5).

    È un modello a sé e non il riuso di `CreaEventoIn`, per una ragione sola ma sufficiente: `CreaEventoIn` è
    il corpo **del contratto congelato**, e legare la forma di questo endpoint a un documento che Onyx ha
    registrato come tool lo renderebbe modificabile solo da un accordo con Onyx. La validazione dei campi
    resta comunque una sola — quella di `CreaEventoIn`, invocata qui sotto.

    `casa_id` non esiste proprio: la Casa è quella della sessione, e un tentativo di scriverla è un `422`
    (`extra="forbid"`) **prima** di toccare il database. È il criterio di done del task (`T-SHIM-13`).
    """

    model_config = ConfigDict(extra="forbid")

    titolo: str = Field(min_length=1, max_length=200)
    inizio: str = Field(min_length=1, description="Data e ora di inizio, ISO (es. 2026-09-20T18:00).")
    fine: str | None = Field(default=None, description="Data e ora di fine, ISO; se indicata, non prima di inizio.")
    luogo_testo: str | None = Field(default=None, max_length=200, description="Dove si tiene, in parole.")
    descrizione: str | None = Field(default=None, max_length=2000)
    url: str | None = Field(default=None, max_length=500)
    ricorrenza: Literal["settimanale", "bisettimanale", "mensile", "annuale"] | None = Field(
        default=None, description="Regola di ripetizione; assente = evento singolo."
    )


@router.post(
    "/eventi",
    operation_id="op_eventi_crea",
    status_code=201,
    summary="Aggiunge un evento al calendario della propria Casa: titolo, inizio e, se serve, fine, luogo, "
    "descrizione e collegamento. Scrittura diretta: l'evento è della Casa di chi lo inserisce.",
    tags=["op"],
)
async def op_eventi_crea(
    corpo: EventoIn, sess: SessioneOperatore = Depends(sessione_corrente)
) -> dict[str, Any]:
    """POST /op/eventi — delega a `scritture.crea_evento`, senza duplicarne né l'INSERT né i controlli.

    La conversione fra i due corpi è intenzionalmente **meccanica**: `EventoIn` dichiara le date come stringhe
    ISO perché il browser manda quello che il campo `<input type="datetime-local">` produce, e `CreaEventoIn`
    le vuole `datetime`; la conversione avviene **qui**, così una data scritta male è un `422` di pydantic in
    italiano con il nome del campo, e non un `DataError` di asyncpg (cioè un 500) al momento dell'INSERT.

    Il filtro anti-PII resta quello di `crea_evento`: `descrizione` e `luogo_testo` sono testo libero, e un
    telefono dettato a voce finirebbe in un evento **pubblico** — un `422` è la risposta giusta, e la seconda
    barriera non si salta perché «tanto il campo è facoltativo».

    La Casa non si passa: `crea_evento` la prende da `sess.casa_id`, e la policy `evento_ins_casa` la
    verifica comunque. Una `casa_id` nulla è l'unico caso in cui la scrittura non avrebbe soggetto.
    """
    if sess.casa_id is None:
        raise errore(403, DETAIL_RUOLO_SENZA_ACCESSO)

    try:
        corpo_contratto = CreaEventoIn(
            titolo=corpo.titolo,
            descrizione=corpo.descrizione,
            inizio=corpo.inizio,  # type: ignore[arg-type] — pydantic converte la stringa ISO in `datetime`
            fine=corpo.fine,  # type: ignore[arg-type]
            luogo_testo=corpo.luogo_testo,
            url=corpo.url,
            ricorrenza=corpo.ricorrenza,
        )
    except ValueError as exc:
        # L'unico validatore che `CreaEventoIn` può far scattare è `fine` prima di `inizio`, e il suo
        # messaggio è già in italiano e senza i valori. Una data malformata non arriva qui: la ferma il tipo.
        raise errore(422, _frase(exc)) from exc

    esito = await crea_evento(corpo_contratto, sess)

    # La risposta è quella dell'area operatore, non quella del contratto: `badge` non serve alla pagina —
    # la provenienza delle righe la compone `GET /op/eventi` dal database — e restituirne una seconda copia
    # qui sarebbe una seconda composizione del badge da tenere allineata alla prima.
    return {"evento_id": esito["evento_id"], "casa": sess.casa_slug}


def _frase(exc: Exception) -> str:
    """Il messaggio di pydantic ridotto alla sua frase utile: il chiamante legge un motivo, non un preambolo."""
    for riga in str(exc).splitlines():
        riga = riga.strip()
        if riga and not riga.lower().startswith(("1 validation error", "value error", "assertion")):
            return riga
    return "parametri non ammessi"


__all__ = ["EventoIn", "op_eventi_crea", "router"]
