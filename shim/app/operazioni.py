"""Dichiarazione delle route a partire dal contratto congelato.

`summary`, `tags` e le risposte d'errore di ogni operazione sono già scritti, in italiano, in `shim/openapi.yaml`:
è il testo che il LLM legge per scegliere lo strumento. Ricopiarli nei decoratori creerebbe una seconda copia da
tenere allineata a mano; qui vengono **letti dal contratto**, quindi l'`OpenAPI` che l'applicazione espone e il
documento registrato in Onyx non possono divergere.

Restano dichiarati nel codice — e non letti — due valori, perché sono l'unica cosa che il documento non può dire:
il **percorso relativo** (il prefisso `/v1/u/{email}` lo aggiunge `APIRouter`) e il **codice di stato di successo**
della risposta (il contratto ne dichiara più d'uno per gli errori, non per il successo).
"""

from functools import lru_cache
from typing import Any

from .contratto import METODI_HTTP, contratto

# Codici che ogni operazione dichiara nel contratto. Il 200/201 di successo è deciso dalla route.
CODICI_ERRORE = (401, 403, 404, 409, 422)


@lru_cache
def _descrizioni() -> dict[str, str]:
    """Le descrizioni di `components.responses`, indicizzate per nome dello schema di risposta."""
    return {
        nome: " ".join(risposta.get("description", "").split())
        for nome, risposta in contratto().get("components", {}).get("responses", {}).items()
    }


def _descrizione(risposta: dict[str, Any]) -> str:
    """La descrizione di una risposta, risolta se è un `$ref` a `components.responses`."""
    riferimento = risposta.get("$ref", "")
    if riferimento.startswith("#/components/responses/"):
        return _descrizioni().get(riferimento.rsplit("/", 1)[-1], "")
    return " ".join(risposta.get("description", "").split())


@lru_cache
def _dichiarazioni() -> dict[str, dict[str, Any]]:
    """Le operazioni del contratto indicizzate per `operationId`."""
    indice: dict[str, dict[str, Any]] = {}
    for percorso, elemento in contratto()["paths"].items():
        for chiave, operazione in elemento.items():
            if chiave in METODI_HTTP:
                indice[operazione["operationId"]] = {"path": percorso, **operazione}
    return indice


def dichiarazione(operation_id: str) -> dict[str, Any]:
    """Gli argomenti del decoratore di route per un'`operationId` del contratto.

    `responses` viene popolato con le descrizioni del contratto per i codici d'errore dichiarati dall'operazione:
    l'`OpenAPI` servito dall'applicazione documenta così gli stessi errori del documento congelato, senza duplicarli.
    """
    try:
        operazione = _dichiarazioni()[operation_id]
    except KeyError as exc:  # pragma: no cover — un'operationId assente è un errore di programmazione
        raise RuntimeError(f"operationId assente dal contratto congelato: {operation_id}") from exc

    responses = {
        codice: {"description": _descrizione(operazione["responses"][str(codice)])}
        for codice in CODICI_ERRORE
        if str(codice) in operazione.get("responses", {})
    }
    return {
        "path": operazione["path"],
        "operation_id": operation_id,
        "summary": " ".join(operazione["summary"].split()),
        "tags": operazione.get("tags", []),
        "responses": responses,
    }
