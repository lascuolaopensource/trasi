"""Errori dello shim: un solo involucro, `{"detail": <stringa italiana>}`.

Il contratto congelato (§`components.schemas.Errore`) ammette un solo campo, `detail`, e dichiara che gli errori di
validazione di pydantic vengono **normalizzati** a quell'involucro da un handler dedicato. Questo modulo è quel
punto unico: senza di esso FastAPI risponderebbe 422 con la struttura `{"detail": [{...}]}` di pydantic, che non è il
contratto, e un errore inatteso uscirebbe come stacktrace invece che come messaggio leggibile dal LLM.

Regola §9.1: **mai un'eccezione al chiamante**. Ogni errore interno diventa una risposta dichiarata.
"""

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

# Dettagli condivisi: stringhe esatte del contratto, scritte una volta sola.
DETAIL_CHIAVE_NON_VALIDA = "chiave shim non valida"
DETAIL_IDENTITA_NON_RICONOSCIUTA = "identità non riconosciuta"
DETAIL_DA_APPROVARE_IN_CODA = "da approvare in coda"
DETAIL_DATO_PERSONALE_SOSPETTO = "dato_personale_sospetto"
DETAIL_ERRORE_INTERNO = "errore interno dello shim"
DETAIL_DATABASE_NON_RAGGIUNGIBILE = "database non raggiungibile"


def errore(status: int, detail: str) -> HTTPException:
    """L'`HTTPException` con l'involucro del contratto.

    Esiste per non ripetere `HTTPException(status_code=…, detail=…)` in ogni punto di decisione: la forma
    dell'errore è una regola del contratto, non una scelta locale.
    """
    return HTTPException(status_code=status, detail=detail)


def _dettaglio_validazione(errore_pydantic: RequestValidationError) -> str:
    """Il messaggio di un 422 di validazione, in italiano, senza il corpo della richiesta.

    Il messaggio di pydantic contiene il nome del campo e il motivo, mai il valore: i valori non vengono registrati
    né rimandati indietro (V5, log senza corpo). `loc` esclude il segmento `body`/`query`, che non serve al LLM.
    """
    pezzi = []
    for voce in errore_pydantic.errors():
        campo = ".".join(str(parte) for parte in voce.get("loc", ()) if parte not in ("body", "query", "path"))
        pezzi.append(f"{campo}: {voce.get('msg', 'valore non ammesso')}" if campo else voce.get("msg", "valore non ammesso"))
    return "parametri non ammessi — " + "; ".join(pezzi) if pezzi else "parametri non ammessi"


def installa_handler(applicazione: FastAPI) -> None:
    """Installa gli handler che tengono ogni risposta dentro il contratto.

    Va chiamata **una volta sola** in `crea_app()`: installarla due volte sostituirebbe l'handler precedente, che per
    FastAPI è idempotente ma rende ambiguo chi risponde.
    """

    @applicazione.exception_handler(RequestValidationError)
    async def _validazione(_: Any, exc: RequestValidationError) -> JSONResponse:
        """422 con l'involucro del contratto, anche quando il campo è un `extra` vietato da `extra="forbid"`."""
        return JSONResponse(status_code=422, content={"detail": _dettaglio_validazione(exc)})

    @applicazione.exception_handler(StarletteHTTPException)
    async def _http(_: Any, exc: StarletteHTTPException) -> JSONResponse:
        """Un `HTTPException` è già una risposta dichiarata: si conserva lo status e si normalizza il corpo.

        Senza questo handler FastAPI risponderebbe `{"detail": exc.detail}`, che per un `detail` non stringa (es. il
        dizionario degli errori di validazione) violerebbe lo schema `Errore`.
        """
        detail = exc.detail if isinstance(exc.detail, str) else DETAIL_ERRORE_INTERNO
        return JSONResponse(status_code=exc.status_code, content={"detail": detail})

    @applicazione.exception_handler(Exception)
    async def _inatteso(_: Any, __: Exception) -> JSONResponse:
        """Un errore non previsto diventa un 500 leggibile: il chiamante non vede mai uno stacktrace (§9.1)."""
        return JSONResponse(status_code=500, content={"detail": DETAIL_ERRORE_INTERNO})
