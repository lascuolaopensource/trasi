#!/usr/bin/env python3
"""Aggiorna il tool custom `trasi_shim` di Onyx con il contratto corrente `shim/openapi.yaml`.

**Perché esiste.** Il tool è stato registrato una volta (B2-ONX-04) con il contratto v0 a 9 operazioni,
poi il contratto è cresciuto (`cerca_web`, e il 16/09/2026 `cerca_opendata`, `leggi_dataset`, il
parametro `indirizzo` di `vicino_a`) mentre Onyx continuava a servire agli assistenti la definizione
vecchia: un endpoint dello shim che il LLM **non vede** è un endpoint che non esiste. Registrare a mano
con `curl` è ciò che ha prodotto lo scarto; questo script rende l'operazione ripetibile e verificabile.

Cosa fa: `PUT /api/admin/tool/custom/<tool_id>` con `definition` = `openapi.yaml`. Non tocca
`custom_headers` (la chiave `X-Trasi-Key` resta quella registrata: `update_tool` di Onyx conserva gli
header quando il campo è assente — verificato sul sorgente, `db/tools.py`), né `passthrough_auth`.
Alla fine rilegge il tool e confronta l'insieme delle `operationId` con quello del file: se divergono,
esce 1.

Uso (le credenziali admin stanno in `/root/.onyx_admin_creds`; `tool_id` da `shim/.onyx-kb.json`):

    python3 ops/registra_tool_shim.py            # applica
    python3 ops/registra_tool_shim.py --dry-run  # mostra le operazioni che cambierebbero
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from onyx_admin import richiesta, sessione  # noqa: E402

RADICE = Path(__file__).resolve().parent.parent
CONTRATTO = RADICE / "shim" / "openapi.yaml"
ONYX_KB_JSON = RADICE / "shim" / ".onyx-kb.json"


def _operation_id(definizione: dict) -> set[str]:
    return {
        operazione["operationId"]
        for percorso in (definizione.get("paths") or {}).values()
        for metodo, operazione in percorso.items()
        if isinstance(operazione, dict) and "operationId" in operazione
    }


def main(argv: list[str] | None = None) -> int:
    argomenti = argparse.ArgumentParser(description="Aggiorna il tool custom trasi_shim con shim/openapi.yaml")
    argomenti.add_argument("--dry-run", action="store_true", help="mostra il delta, senza scrivere")
    opzioni = argomenti.parse_args(argv)

    identificativi = json.loads(ONYX_KB_JSON.read_text(encoding="utf-8"))
    tool_id = int(identificativi["tool_id"])
    definizione = yaml.safe_load(CONTRATTO.read_text(encoding="utf-8"))
    attese = _operation_id(definizione)

    cookie = sessione()
    corrente = richiesta(f"/tool/{tool_id}", cookie)
    registrate = _operation_id(corrente.get("definition") or {})
    print(f"tool {tool_id} «{corrente.get('name')}»: registrate {len(registrate)} operazioni, nel file {len(attese)}")
    nuove, rimosse = sorted(attese - registrate), sorted(registrate - attese)
    if nuove:
        print(f"  da aggiungere: {', '.join(nuove)}")
    if rimosse:
        print(f"  non più nel contratto: {', '.join(rimosse)}")
    if corrente.get("definition") == definizione:
        print("  definizione identica al file: niente da fare")
        return 0
    if opzioni.dry_run:
        print("dry-run: la definizione verrebbe sostituita (schemi/descrizioni cambiati" + (", operazioni cambiate" if nuove or rimosse else "") + ")")
        return 0

    richiesta(f"/admin/tool/custom/{tool_id}", cookie, metodo="PUT", corpo={"definition": definizione})

    # Verifica riletta dal server: un PUT accettato ma non persistito è il difetto da escludere.
    riletto = richiesta(f"/tool/{tool_id}", cookie)
    effettive = _operation_id(riletto.get("definition") or {})
    if effettive != attese:
        print(f"ATTENZIONE: dopo il PUT il tool espone {sorted(effettive)} ≠ {sorted(attese)}", file=sys.stderr)
        return 1
    print(f"aggiornato: il tool espone {len(effettive)} operazioni → {', '.join(sorted(effettive))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
