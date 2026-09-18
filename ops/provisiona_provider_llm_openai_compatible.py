#!/usr/bin/env python3
"""Provisiona in Onyx un provider LLM OpenAI-compatible puntato a Ollama Cloud.

**Perché esiste.** Il provider iniziale di Trasi era `ollama_chat` (host: `https://ollama.com`).
Con quel provider Onyx usa `_OllamaHistoryMessageFormatter` (`/opt/onyx/backend/onyx/chat/llm_step.py`),
che serializza nella history le tool call come righe di testo `[Tool Call] name=X id=Y args={…}`
invece del formato strutturato OpenAI. I modelli cloud (glm-5.3-flash, deepseek-v4-flash, …) imparano
quel pattern dalla history stessa e, a intermittenza, lo riemettono come *testo visibile* al posto di
una tool call strutturata: l'utente vede il payload grezzo, la tool call non viene eseguita, la chat
resta muta. Il fallback di estrazione (`extract_tool_calls_from_response_text`) non riconosce quel
formato: cattura solo JSON/XML.

**Cosa cambia passando a `openai_compatible`.** `https://ollama.com/v1` è l'endpoint OpenAI-compatible
di Ollama Cloud (stessa chiave, stesso modello). Con un provider di questo tipo Onyx usa
`_DefaultHistoryMessageFormatter`: le tool call viaggiano nel campo strutturato `tool_calls`,
il modello non vede mai il pattern testuale e non ha nulla da imitare. Verificato a mano il
2026-09-18: `POST /v1/chat/completions` con `tools=[…]` restituisce `finish_reason=tool_calls` con
tool call strutturata, e accetta history con `assistant.tool_calls` + `role:tool` senza errori.

**Idempotenza.** Può essere rieseguito senza effetti collaterali: aggiorna il provider esistente
per nome se lo trova, altrimenti lo crea; imposta il modello di default; marca il vecchio
provider `ollama_chat` come non-visibile (nessuna cancellazione, rollback banale).

**Sicurezza.** La chiave API non è mai stampata né passata via argv. È letta da
`/opt/onyx/deployment/docker_compose/.env` (variabile `OLLAMA_API_KEY`, mode 600) e inviata solo
nel corpo JSON cifrato della PUT verso `/api/admin/llm/provider`.

**Uso** (dalla radice del repo, sul server dove gira Onyx):

    python3 ops/provisiona_provider_llm_openai_compatible.py            # applica
    python3 ops/provisiona_provider_llm_openai_compatible.py --dry-run  # mostra cosa farebbe

Richiede: `/root/.onyx_admin_creds` (per il login admin a Onyx) e la variabile
`OLLAMA_API_KEY` nel `.env` del deployment Onyx.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from onyx_admin import richiesta, sessione  # noqa: E402

ENV_FILE = Path(
    os.environ.get(
        "ONYX_DEPLOY_ENV",
        "/opt/onyx/deployment/docker_compose/.env",
    )
)

# Parametri del provider: non negoziabili senza capire perché Onyx li usava così.
PROVIDER_NAME = "Ollama Cloud (OpenAI-compatible)"
PROVIDER_KIND = "openai_compatible"
API_BASE = "https://ollama.com/v1"
MODEL_NAME = "glm-5.3-flash"
MODEL_DISPLAY = "GLM 5.3 Flash (via Ollama Cloud, OpenAI-compatible)"
MODEL_MAX_INPUT = 131072  # vedi litellm cost map per glm-5.3-flash su ollama
LEGACY_PROVIDER_ID = 1  # `ollama_chat` creato in fase B0


def leggi_chiave_ollama() -> str:
    """Legge OLLAMA_API_KEY dal .env di Onyx. Mai stampare il valore."""
    if not ENV_FILE.exists():
        raise SystemExit(f"env non trovato: {ENV_FILE}")
    for riga in ENV_FILE.read_text().splitlines():
        if riga.startswith("OLLAMA_API_KEY="):
            return riga.split("=", 1)[1].strip()
    raise SystemExit(f"OLLAMA_API_KEY non presente in {ENV_FILE}")


def trova_provider(cookie: str, nome: str) -> dict | None:
    risposta = richiesta("/admin/llm/provider", cookie)
    providers = risposta.get("providers", []) if isinstance(risposta, dict) else risposta
    for p in providers:
        if p.get("name") == nome:
            return p
    return None


def upsert_provider(cookie: str, chiave: str, dry_run: bool) -> int:
    """Crea o aggiorna il provider openai_compatible. Ritorna l'id."""
    esistente = trova_provider(cookie, PROVIDER_NAME)
    body = {
        "name": PROVIDER_NAME,
        "provider": PROVIDER_KIND,
        "api_key": chiave,
        "api_key_changed": True,
        "api_base": API_BASE,
        "is_public": True,
        "groups": [],
        "personas": [],
        "model_configurations": [
            {
                "name": MODEL_NAME,
                "is_visible": True,
                "display_name": MODEL_DISPLAY,
                "max_input_tokens": MODEL_MAX_INPUT,
            }
        ],
    }
    is_creation = esistente is None
    if esistente:
        body["id"] = esistente["id"]
    if dry_run:
        azione = "aggiornerei" if esistente else "creerei"
        print(f"[dry-run] {azione} provider '{PROVIDER_NAME}' (provider={PROVIDER_KIND}, "
              f"api_base={API_BASE}, modello={MODEL_NAME}, id={body.get('id', '<nuovo>')})")
        return esistente["id"] if esistente else -1

    query = "?is_creation=true" if is_creation else ""
    risposta = richiesta(f"/admin/llm/provider{query}", cookie, metodo="PUT", corpo=body)
    provider_id = esistente["id"] if esistente else risposta.get("id")
    if provider_id is None:
        provider_id = trova_provider(cookie, PROVIDER_NAME)["id"]
    return provider_id


def imposta_default(cookie: str, provider_id: int, dry_run: bool) -> None:
    body = {"provider_id": provider_id, "model_name": MODEL_NAME}
    if dry_run:
        print(f"[dry-run] imposterei default provider_id={provider_id} model={MODEL_NAME}")
        return
    richiesta("/admin/llm/default", cookie, metodo="POST", corpo=body)


def nascondi_provider_legacy(cookie: str, dry_run: bool) -> None:
    """Rende i modelli di `ollama_chat` invisibili, senza cancellare il provider.

    Rollback: da admin UI si ri-attiva la visibilità. La cancellazione perderebbe
    il legame con le chat esistenti (model_display_name nelle chat_message).
    """
    legacy = richiesta("/admin/llm/provider", cookie)
    legacy_list = legacy.get("providers", []) if isinstance(legacy, dict) else legacy
    legacy = next((p for p in legacy_list if p.get("id") == LEGACY_PROVIDER_ID), None)
    if not legacy:
        print(f"provider legacy id={LEGACY_PROVIDER_ID} non trovato, salto")
        return
    if legacy.get("provider") != "ollama_chat":
        print(f"provider id={LEGACY_PROVIDER_ID} non è 'ollama_chat' "
              f"(è '{legacy.get('provider')}'): non lo tocco")
        return

    body = {
        "id": LEGACY_PROVIDER_ID,
        "name": legacy.get("name"),
        "provider": "ollama_chat",
        # api_key e api_base non cambiano: non li inviamo per non esporre la chiave
        "is_public": True,
        "model_configurations": [
            {
                "name": mc["name"],
                "is_visible": False,
                "display_name": mc.get("display_name"),
                "max_input_tokens": mc.get("max_input_tokens"),
                "supports_image_input": mc.get("supports_image_input"),
            }
            for mc in legacy.get("model_configurations", [])
        ],
    }
    if dry_run:
        print(f"[dry-run] renderei invisibili {len(body['model_configurations'])} "
              f"modelli del provider legacy id={LEGACY_PROVIDER_ID}")
        return
    richiesta("/admin/llm/provider", cookie, metodo="PUT", corpo=body)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="mostra cosa farebbe, non applica")
    args = parser.parse_args()

    chiave = leggi_chiave_ollama()
    cookie = sessione()

    provider_id = upsert_provider(cookie, chiave, args.dry_run)
    imposta_default(cookie, provider_id, args.dry_run)
    nascondi_provider_legacy(cookie, args.dry_run)

    if not args.dry_run:
        print(json.dumps({
            "provider_id": provider_id,
            "provider": PROVIDER_KIND,
            "api_base": API_BASE,
            "default_model": MODEL_NAME,
            "legacy_provider_id": LEGACY_PROVIDER_ID,
        }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
