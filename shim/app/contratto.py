"""Accesso al contratto congelato `shim/openapi.yaml`.

Il documento YAML è la fonte di verità del contratto (gate V-09). Qui si legge l'unico valore che anche l'applicazione
deve conoscere e che non deve mai divergere: l'URL del server. Tutto il resto viene dichiarato direttamente dalle route
in `main.py`, così il test di coerenza confronta due dichiarazioni indipendenti invece di confrontare il file con sé
stesso.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml
from fastapi import Request

from .errori import errore

METODI_HTTP = ("get", "post", "put", "delete", "patch", "options", "head")

# Segnaposto che Onyx sostituisce lato server con l'email dell'utente autenticato
# (`tools/tool_constructor.py:436-447`). Dev'essere letterale nell'URL di `servers`.
SEGNAPOSTO_EMAIL = "USER_EMAIL"

PERCORSO_CONTRATTO = Path(__file__).resolve().parent.parent / "openapi.yaml"


class ContrattoNonValido(RuntimeError):
    """Il contratto congelato è assente o non rispetta l'invariante su `servers`."""


def _carica() -> dict[str, Any]:
    try:
        with PERCORSO_CONTRATTO.open(encoding="utf-8") as f:
            documento = yaml.safe_load(f)
    except OSError as exc:
        raise ContrattoNonValido(f"contratto non leggibile: {PERCORSO_CONTRATTO}") from exc
    if not isinstance(documento, dict):
        raise ContrattoNonValido(f"contratto non valido: {PERCORSO_CONTRATTO}")
    return documento


@lru_cache
def contratto() -> dict[str, Any]:
    """Il contratto congelato, già interpretato."""
    return _carica()


@lru_cache
def url_server() -> str:
    """L'unico `servers[].url` ammesso: `http://shim:8000/v1/u/USER_EMAIL`.

    Onyx pretende esattamente un URL in `servers` (`openapi_parsing.openapi_to_url`): con zero o due valori la
    registrazione del tool fallisce. Qui l'invariante è verificata anche lato applicazione.
    """
    servers = contratto().get("servers", [])
    url = [s["url"] for s in servers if isinstance(s, dict) and s.get("url")]
    if len(url) != 1:
        raise ContrattoNonValido(f"atteso un solo server, trovati {len(url)}: {url}")
    return url[0]


@lru_cache
def prefisso_path() -> str:
    """Prefisso di montaggio delle operazioni, ricavato dall'unico `servers[].url`.

    Onyx compone l'URL chiamato come `servers[0].url` + path dell'operazione: con
    `http://shim:8000/v1/u/USER_EMAIL` la richiesta reale è `GET /v1/u/<email>/cerca_luogo`. Le route
    dell'applicazione devono quindi stare sotto questo prefisso, altrimenti lo stub risponderebbe 501 a un indirizzo
    che Onyx non chiama mai e il gate V-09 proverebbe qualcosa di diverso dal contratto. Derivare il prefisso dal
    documento congelato impedisce che i due valori divergano; il segnaposto diventa il parametro di percorso
    `{email}`.
    """
    percorso = urlsplit(url_server()).path
    prefisso = percorso.replace(SEGNAPOSTO_EMAIL, "{email}")
    if prefisso in ("", "/"):
        raise ContrattoNonValido(f"l'URL del server non indica un prefisso: {url_server()}")
    return prefisso.rstrip("/")


def operazioni() -> list[dict[str, Any]]:
    """Le operazioni del contratto, come elenco piatto di dict del documento."""
    elenco = []
    for percorso, elemento in contratto()["paths"].items():
        for chiave, operazione in elemento.items():
            if chiave in METODI_HTTP:
                elenco.append({"path": percorso, "metodo": chiave.upper(), **operazione})
    return elenco


@lru_cache
def _dichiarazioni() -> dict[str, dict[str, Any]]:
    """Le operazioni indicizzate per `operationId`."""
    return {operazione["operationId"]: operazione for operazione in operazioni()}


def meta(operation_id: str) -> dict[str, Any]:
    """`operation_id`, `summary` e `tags` di un'operazione, **dal contratto congelato**.

    I router non riscrivono il summary in italiano: quello del contratto è il testo che il LLM legge per scegliere lo
    strumento (gate V-09), e duplicarlo qui creerebbe due testi che divergono. Un `operationId` assente dal contratto
    fa fallire l'import dell'applicazione, non una richiesta a caso.
    """
    dichiarazione = _dichiarazioni().get(operation_id)
    if dichiarazione is None:
        raise ContrattoNonValido(f"operationId assente dal contratto congelato: {operation_id}")
    return {
        "operation_id": operation_id,
        "summary": " ".join(dichiarazione["summary"].split()),
        "tags": dichiarazione.get("tags", []),
    }


def solo_parametri_dichiarati(request: Request) -> None:
    """Dipendenza: un parametro di query che la rotta **non dichiara** è un 422 che lo nomina, non un silenzio.

    FastAPI ignora i parametri di query sconosciuti. Per un'API chiamata da un modello è il difetto peggiore: il
    2026-09-18 gli assistenti passavano `finestra_gg=30` a uno shim che non lo conosceva, ricevevano il solo giorno
    `data` e rispondevano «nessun evento nel mese» — un dato falso, con status 200, e nessuna traccia del perché.
    Lo stesso principio che V5 applica ai corpi (`extra="forbid"`) vale qui per le query: la chiave sconosciuta
    torna al chiamante, e l'errore elenca i nomi ammessi così il modello (e chi legge il log) può correggersi.

    I parametri dichiarati si leggono dalla rotta stessa (`request.scope["route"]`), non da un elenco a mano che
    divergerebbe alla prima aggiunta.
    """
    rotta = request.scope.get("route")
    dichiarati = {
        campo.alias
        for campo in getattr(getattr(rotta, "dependant", None), "query_params", [])
    }
    sconosciuti = sorted(set(request.query_params.keys()) - dichiarati)
    if sconosciuti:
        raise errore(
            422,
            "parametri non ammessi — sconosciuti: " + ", ".join(sconosciuti)
            + "; ammessi: " + ", ".join(sorted(dichiarati)),
        )
