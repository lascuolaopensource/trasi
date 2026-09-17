"""Sessione amministrativa verso l'API di Onyx, condivisa dagli script di `ops/`.

Tre script (`allinea_prompt_assistenti.py`, `registra_tool_shim.py`, `provisiona_connettore_documenti.py`)
fanno la stessa cosa prima di lavorare: leggono le credenziali admin da `/root/.onyx_admin_creds`, fanno
login e ottengono il cookie di sessione. Averlo in tre copie significava tre posti in cui un cambio del nome
del cookie o del percorso di login si sarebbe rotto in momenti diversi. Qui ce n'è uno.

Regole:
* la password non viene mai stampata né passata in argv: viaggia solo nel corpo della POST di login;
* gli errori HTTP diventano `SystemExit` con il corpo troncato a 200 caratteri — quanto basta per capire
  cosa dice l'API, non abbastanza per copiare un segreto in un log.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BASE = os.environ.get("ONYX_API_URL", "http://127.0.0.1/api")
CREDS = Path("/root/.onyx_admin_creds")


def leggi_credenziali() -> tuple[str, str]:
    email = password = None
    for riga in CREDS.read_text().splitlines():
        if riga.startswith("ONYX_ADMIN_EMAIL="):
            email = riga.split("=", 1)[1].strip()
        elif riga.startswith("ONYX_ADMIN_PASSWORD="):
            password = riga.split("=", 1)[1].strip()
    if not email or not password:
        raise SystemExit(f"credenziali non trovate in {CREDS}")
    return email, password


def login(email: str, password: str) -> str:
    """Il cookie di sessione, senza mai stampare la password."""
    corpo = urllib.parse.urlencode({"username": email, "password": password}).encode()
    richiesta = urllib.request.Request(
        f"{BASE}/auth/login",
        data=corpo,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(richiesta, timeout=30) as risposta:
        for intestazione in risposta.headers.get_all("Set-Cookie") or []:
            if intestazione.startswith(("fastapiusersauth", "access_token")):
                return intestazione.split(";", 1)[0]
    raise SystemExit("login riuscito ma nessun cookie di sessione nella risposta")


def sessione() -> str:
    """Login con le credenziali del file: il cookie da passare a `richiesta`."""
    return login(*leggi_credenziali())


def richiesta(percorso: str, cookie: str, *, metodo: str = "GET", corpo: dict | list | None = None) -> dict | list:
    dati = json.dumps(corpo).encode() if corpo is not None else None
    richiesta_http = urllib.request.Request(
        f"{BASE}{percorso}",
        data=dati,
        method=metodo,
        headers={"Cookie": cookie, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(richiesta_http, timeout=60) as risposta:
            grezzo = risposta.read().decode()
    except urllib.error.HTTPError as errore:
        raise SystemExit(f"{metodo} {percorso} → HTTP {errore.code}: "
                         f"{errore.read().decode(errors='replace')[:200]}") from errore
    return json.loads(grezzo) if grezzo.strip() else {}
