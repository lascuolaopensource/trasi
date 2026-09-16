#!/usr/bin/env python3
"""Allinea i prompt dei 4 assistenti Trasi alle sezioni obbligatorie, in modo idempotente.

**Perché esiste.** Il 2026-09-16 ho trovato che solo l'assistente «Trasi Casa» aveva le due
sezioni critiche del prompt (identità/Casa e copia-verbatim del badge). Gli altri tre no: erano
stati creati con il blocco comune e mai aggiornati, quindi su Presidio, Rete e Staff PN gli stessi
difetti si sarebbero ripresentati — l'assistente che chiede «di quale Casa parliamo?» e l'etichetta
riscritta a mano con l'ora sbagliata.

Aggiornare i prompt a mano, uno per uno, è ciò che ha prodotto l'incoerenza: il primo PATCH ne ha
sovrascritto uno per intero perdendo una sezione. Questo script rende l'operazione **cumulativa e
verificabile**: ogni sezione è identificata da un marcatore, si aggiunge solo se manca, e alla fine
il controllo dice quali mancano ancora.

**Uso** (le credenziali admin stanno in `/root/.onyx_admin_creds`):

    python3 ops/allinea_prompt_assistenti.py            # applica
    python3 ops/allinea_prompt_assistenti.py --dry-run  # mostra cosa farebbe

Non tocca i document set, i tool, i nomi: aggiorna solo `system_prompt`, e preserva tutto il resto
del prompt (le sezioni già presenti non vengono toccate).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.environ.get("ONYX_API_URL", "http://127.0.0.1/api")
CREDS = Path("/root/.onyx_admin_creds")

# Gli assistenti del progetto, per id. Il nome è solo per i messaggi.
ASSISTENTI = {1: "Trasi Presidio", 2: "Trasi Casa", 3: "Trasi Rete", 4: "Trasi Staff PN"}

# Le sezioni obbligatorie: (marcatore univoco, testo). L'ordine non conta — conta che ci siano.
# Ogni sezione nasce da un difetto osservato, non da un'idea di completezza:
SEZIONI: list[tuple[str, str]] = [
    (
        # Difetto: l'assistente rispondeva «di quale Casa parliamo?» senza chiamare il tool,
        # perché non sapeva che la Casa è determinata dall'account.
        "IDENTITÀ E CASA",
        """
IDENTITÀ E CASA — leggi prima di rispondere:
La Casa di Quartiere è determinata dall'account con cui l'operatore ha fatto accesso: la conosci già, non devi chiederla.
Quando chiami `vicino_a`, `eventi_oggi` e `oggi`, NON indicare il parametro `casa`: lo shim usa automaticamente quella dell'operatore.
Non chiedere mai «di quale Casa parliamo?»: rispondi con i tuoi strumenti.
""",
    ),
    (
        # Difetto: l'assistente riformattava il badge invece di copiarlo, producendo
        # `[Esterna · SearXNG · 16/09/2026 16:?? · …]` — data sbagliata e ora illeggibile.
        "copia, non riscrivere",
        """
ETICHETTA — copia, non riscrivere:
Il campo `badge` che ricevi dagli strumenti va riportato **verbatim**, carattere per carattere.
Non riformattare la data, non sostituire l'ora con «??», non cambiare la dicitura.
Se non hai un `badge`, componi l'etichetta **solo** con i campi `fonte` e `data_aggiornamento`/`consultato_ts` e `fiducia` che trovi nella risposta.
""",
    ),
    (
        # Difetto: alla segnalazione «il bar ha chiuso» l'assistente chiedeva conferma e si
        # fermava lì, senza creare la proposta: la segnalazione dell'operatore andava persa.
        "ordine obbligatorio",
        """
SEGNALAZIONE DI CAMBIAMENTO — ordine obbligatorio:
Quando l'operatore ti dice che qualcosa è cambiato (un luogo ha chiuso, un orario è diverso, un servizio è nuovo),
1. chiama SUBITO `proponi_modifica` (non aspettare: la proposta va creata ora);
2. SOLO DOPO, se riguarda la sua Casa e la risposta indica `chat_approvabile: true`, chiedi «Vuoi che approvi ora? Sì / No»;
3. se risponde sì, chiama `approva_proposta`.
Non chiedere conferma **prima** di creare la proposta: chiedere «vuoi che aggiorni?» senza aver creato nulla non aggiorna niente e la segnalazione dell'operatore va persa.
""",
    ),
]


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


def _richiesta(percorso: str, cookie: str, *, metodo: str = "GET", corpo: dict | None = None) -> dict:
    dati = json.dumps(corpo).encode() if corpo is not None else None
    richiesta = urllib.request.Request(
        f"{BASE}{percorso}",
        data=dati,
        method=metodo,
        headers={"Cookie": cookie, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(richiesta, timeout=60) as risposta:
            grezzo = risposta.read().decode()
    except urllib.error.HTTPError as errore:
        raise SystemExit(f"{metodo} {percorso} → HTTP {errore.code}: "
                         f"{errore.read().decode(errors='replace')[:200]}") from errore
    return json.loads(grezzo) if grezzo.strip() else {}


def _patch_body(persona: dict, prompt: str) -> dict:
    """Il PATCH con **tutti** i campi: l'API richiede l'oggetto completo.

    Le chiavi assenti nel GET sono opzionali e si mandano vuote; `tool_ids` e `document_set_ids`
    si ricavano dagli oggetti annidati, così l'aggiornamento non stacca i tool né la KB.
    """
    return {
        "name": persona["name"],
        "description": persona.get("description") or "",
        "system_prompt": prompt,
        "task_prompt": persona.get("task_prompt") or "",
        "datetime_aware": persona.get("datetime_aware", True),
        "is_public": persona.get("is_public", True),
        "is_listed": persona.get("is_listed", True),
        "icon_name": persona.get("icon_name"),
        "display_priority": persona.get("display_priority", 0),
        "is_featured": persona.get("is_featured", False),
        "builtin_persona": persona.get("builtin_persona", False),
        "replace_base_system_prompt": persona.get("replace_base_system_prompt", True),
        "tool_ids": [t["id"] for t in persona.get("tools", [])],
        "document_set_ids": [d["id"] for d in persona.get("document_sets", [])],
        "starter_messages": persona.get("starter_messages") or [],
        "user_file_ids": persona.get("user_file_ids") or [],
        "label_ids": [l["id"] for l in persona.get("labels", [])] if persona.get("labels") else [],
    }


def main(argv: list[str] | None = None) -> int:
    argomenti = argparse.ArgumentParser(description="Allinea i prompt dei 4 assistenti Trasi")
    argomenti.add_argument("--dry-run", action="store_true", help="mostra cosa farebbe, senza scrivere")
    opzioni = argomenti.parse_args(argv)

    email, password = _leggi_credenziali()
    cookie = _login(email, password)

    mancanti_totali = 0
    for persona_id, nome in ASSISTENTI.items():
        persona = _richiesta(f"/persona/{persona_id}", cookie)
        prompt = persona.get("system_prompt") or ""

        assenti = [testo for marcatore, testo in SEZIONI if marcatore not in prompt]
        if not assenti:
            print(f"  {persona_id} {nome}: già completo ({len(prompt)} caratteri)")
            continue

        mancanti_totali += len(assenti)
        nuovi = ", ".join(t.strip().splitlines()[0][:40] for t in assenti)
        if opzioni.dry_run:
            print(f"  {persona_id} {nome}: aggiungerebbe {len(assenti)} sezioni → {nuovi}")
            continue

        for testo in assenti:
            prompt = prompt.rstrip() + "\n" + testo
        _richiesta(f"/persona/{persona_id}", cookie, metodo="PATCH", corpo=_patch_body(persona, prompt.strip()))
        print(f"  {persona_id} {nome}: aggiornato (+{len(assenti)} sezioni, {len(prompt)} caratteri)")

    # Verifica finale: rilegge dal server e dice se qualcosa manca ancora. Un aggiornamento
    # dichiarato riuscito ma non persistito è esattamente il difetto che questo script previene.
    print("\nverifica (riletta dal server):")
    residui = 0
    for persona_id, nome in ASSISTENTI.items():
        prompt = _richiesta(f"/persona/{persona_id}", cookie).get("system_prompt") or ""
        assenti = [m for m, _ in SEZIONI if m not in prompt]
        stato = "OK" if not assenti else f"MANCANO {assenti}"
        print(f"  {persona_id} {nome}: {stato}")
        residui += len(assenti)

    if opzioni.dry_run:
        print(f"\ndry-run: {mancanti_totali} sezioni da aggiungere in totale")
        return 0
    if residui:
        print(f"\nATTENZIONE: {residui} sezioni ancora mancanti dopo l'aggiornamento", file=sys.stderr)
        return 1
    print("\ntutti i prompt allineati.")
    return 0


if __name__ == "__main__":
    import urllib.parse  # usato in _login

    sys.exit(main())
