"""`GET /op/config` — la configurazione a runtime che la Home statica non può conoscere da sola.

Onyx è l'unica superficie di conversazione umano↔AI: il tasto «Chiedi» della Home apre l'assistente «Trasi Casa»
in una nuova scheda, e l'indirizzo di Onyx vive solo in `deployment/.env` (`ONYX_DOMAIN`) e nel Caddyfile. Il
frontend è statico e non ha un passo di build che possa iniettarlo: lo chiede allo shim, nello stesso modo in cui
chiede chi è entrato (`GET /me`) e la scheda della Casa (`GET /op/casa`).

Risposta: `{"onyx_url": "https://<ONYX_DOMAIN>/chat?agentId=<persona>"}`. Nell'URL c'è **solo** l'id
dell'assistente (V5: nessuna email, nessun identificatore della sessione o della Casa). L'assistente è lo stesso
che usa il proxy `POST /op/chat` — `chat.configurazione().persona_id`, cioè `ONYX_PERSONA_ID` o il default 2 —
perché due costanti per la stessa persona divergerebbero al primo cambio.

Richiede la sessione operatore come ogni altro `/op/…`: l'indirizzo di Onyx non è un segreto, ma la Home non
espone niente a chi non è entrato. Fuori dal contratto congelato con Onyx (`include_in_schema=False` lo mette
`main.py` all'inclusione, come per gli altri router nudi dell'area operatore).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from .auth import SessioneOperatore, sessione_corrente
from .chat import configurazione
from .errori import errore
from .settings import get_settings

router = APIRouter()

DETAIL_ONYX_NON_CONFIGURATO = "Onyx non configurato: manca ONYX_DOMAIN"


def url_onyx(dominio: str, persona_id: int) -> str:
    """Il collegamento all'assistente: `https://<dominio>/chat?agentId=<persona>`, con il dominio senza schema né barra finale."""
    dominio = dominio.strip().removeprefix("https://").removeprefix("http://").rstrip("/")
    return f"https://{dominio}/chat?agentId={persona_id}"


@router.get("/config", operation_id="op_config", summary="Configurazione a runtime per la Home (indirizzo di Onyx).")
async def op_config(sess: SessioneOperatore = Depends(sessione_corrente)) -> dict[str, Any]:
    """GET /op/config → 200 `{onyx_url}`; 401 senza sessione; 503 se `ONYX_DOMAIN` è vuoto."""
    dominio = get_settings().onyx_domain.strip()
    if not dominio:
        raise errore(503, DETAIL_ONYX_NON_CONFIGURATO)
    return {"onyx_url": url_onyx(dominio, configurazione().persona_id)}


__all__ = ["DETAIL_ONYX_NON_CONFIGURATO", "op_config", "router", "url_onyx"]
