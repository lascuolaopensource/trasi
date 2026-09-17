#!/usr/bin/env python3
"""Crea la persona «Trasi Monitoraggio PA» in Onyx con il prompt del file docs/prompt-assistente-5-trasipa.txt.

**Perché esiste.** La persona deve esistere prima che il tool custom (openapi_monitoraggio.yaml)
sia pronto, così l'approfondimento conversazionale della dashboard PA non blocca lo sviluppo parallelo.
Il binding del tool è un passo separato e dichiarato nel risultato.

**Idempotente.** Se la persona esiste già (stesso name), aggiorna il system_prompt dal file
senza toccare tool né docset. Se non esiste, la crea con replace_base_system_prompt=true,
is_public=true, tool_ids vuoto (da riempire dopo la registrazione del tool).

**Uso** (credenziali in /root/.onyx_admin_creds):
    python3 ops/provisiona_persona_pa.py           # applica
    python3 ops/provisiona_persona_pa.py --dry-run  # mostra cosa farebbe
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = os.environ.get("ONYX_API_URL", "http://127.0.0.1/api")
CREDS = Path("/root/.onyx_admin_creds")
PROMPT_FILE = Path("docs/prompt-assistente-5-trasipa.txt")
NOME = "Trasi Monitoraggio PA"
DESCRIZIONE = (
    "Approfondimento conversazionale del report di monitoraggio della rete Trasi per la PA: "
    "solo dati dagli strumenti del monitoraggio, k-anonimato dichiarato, mai imperativi."
)


def _leggi_credenziali() -> tuple[str, str]:
    email = password = None
    for riga in CREDS.read_text().splitlines():
        if riga.startswith("ONYX_ADMIN_EMAIL="):
            email = riga.split("=", 1)[1].strip()
        elif riga.startswith("ONYX_ADMIN_PASSWORD="):
            password = riga.split("=", 1)[1].strip()
    if not email or not password:
        raise SystemExit(f"credenziali non trovate in {CREDS}")
    return email, password


def _login(email: str, password: str) -> str:
    corpo = urllib.parse.urlencode({"username": email, "password": password}).encode()
    richiesta = urllib.request.Request(
        f"{BASE}/auth/login",
        data=corpo,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(richiesta, timeout=30) as risposta:
        for h in risposta.headers.get_all("Set-Cookie") or []:
            if h.startswith(("fastapiusersauth", "access_token")):
                return h.split(";", 1)[0]
    raise SystemExit("login riuscito ma nessun cookie")


def _req(percorso: str, cookie: str, *, metodo: str = "GET", corpo: dict | None = None) -> dict:
    dati = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(
        f"{BASE}{percorso}",
        data=dati,
        method=metodo,
        headers={"Cookie": cookie, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            grezzo = r.read().decode()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{metodo} {percorso} → HTTP {e.code}: {e.read().decode(errors='replace')[:400]}") from e
    return json.loads(grezzo) if grezzo.strip() else {}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    prompt = PROMPT_FILE.read_text().strip()
    if not prompt:
        raise SystemExit(f"file prompt vuoto o mancante: {PROMPT_FILE}")

    email, password = _leggi_credenziali()
    cookie = _login(email, password)

    # Cerca persona per nome
    dati = _req("/persona", cookie)
    lista = dati if isinstance(dati, list) else dati.get("personas", [])
    trovata = next((p for p in lista if p.get("name") == NOME), None)

    corpo = {
        "name": NOME,
        "description": DESCRIZIONE,
        "system_prompt": prompt,
        "task_prompt": "",
        "datetime_aware": True,
        "replace_base_system_prompt": True,
        "is_public": True,
        "tool_ids": [],
        "document_set_ids": [],
        "starter_messages": [],
        "label_ids": [],
    }

    if args.dry_run:
        if trovata:
            print(f"persona già esistente id={trovata['id']}: aggiornerebbe system_prompt ({len(prompt)} caratteri)")
        else:
            print(f"persona da creare: name={NOME}, prompt={len(prompt)} caratteri, tool_ids=[]")
        return 0

    if trovata:
        persona_id = trovata["id"]
        # Patch completo: preserva tool e docset, sostituisce il prompt
        patch_corpo = {
            "name": trovata["name"],
            "description": trovata.get("description") or "",
            "system_prompt": prompt,
            "task_prompt": trovata.get("task_prompt") or "",
            "datetime_aware": trovata.get("datetime_aware", True),
            "replace_base_system_prompt": True,
            "is_public": trovata.get("is_public", True),
            "tool_ids": [t["id"] for t in trovata.get("tools", [])],
            "document_set_ids": [d["id"] for d in trovata.get("document_sets", [])],
            "starter_messages": trovata.get("starter_messages") or [],
            "label_ids": [],
        }
        _req(f"/persona/{persona_id}", cookie, metodo="PATCH", corpo=patch_corpo)
        print(f"persona {persona_id} «{NOME}»: system_prompt aggiornato ({len(prompt)} caratteri)")
    else:
        # In Onyx v4.7.2 la creazione è su /api/persona (basic_router, non /admin/persona).
        creato = _req("/persona", cookie, metodo="POST", corpo=corpo)
        persona_id = creato.get("id")
        print(f"persona {persona_id} «{NOME}»: creata (tool_ids=[] — binding pendente)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
