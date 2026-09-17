#!/usr/bin/env python3
"""Dà all'assistente **predefinito** di Onyx (persona 0, «Assistant») lo strumento `trasi_shim` e le
istruzioni minime di Trasi, in modo idempotente.

**Perché esiste.** Il 2026-09-17 un operatore di San Bao ha scritto «aggiungi evento oggi» nella chat
di Onyx e l'assistente ha risposto «non ho accesso a un calendario», poi ha inventato un evento, poi
ha «memorizzato l'appuntamento nelle note». Nessuna scrittura è arrivata a Trasi. Non aveva sbagliato
nulla di visibile: aveva aperto una chat nuova, e una chat nuova in Onyx parte con l'assistente
predefinito — che non aveva `trasi_shim`. Gli assistenti Trasi (1-4) c'erano, ma erano una scelta in
un selettore, e un selettore è un posto dove si sbaglia.

L'assistente predefinito non si può nascondere né sostituire: è quello di ogni chat nuova. Si può
però renderlo **capace**: con `trasi_shim` e una sezione di istruzioni, «aggiungi l'aperitivo alle 20»
chiama `crea_evento` invece di inventare.

**Attenzione a un dettaglio non ovvio.** Il `system_prompt` della persona 0 è il **prompt di base di
tutti** gli assistenti (`get_default_base_system_prompt`): se è `None` Onyx usa il suo testo
predefinito, se è impostato lo sostituisce **per intero**, anche per Trasi Casa & co. Per questo lo
script non scrive mai solo la sezione Trasi: scrive «testo predefinito di Onyx + sezione Trasi», e la
sezione è riconoscibile da un marcatore, così una seconda esecuzione non la duplica.

**Uso** (chiave API admin in `deployment/.env` → `ONYX_TRASI_KB_API_KEY`):

    python3 ops/allinea_assistente_predefinito.py            # applica
    python3 ops/allinea_assistente_predefinito.py --dry-run  # mostra cosa farebbe

Non tocca gli altri strumenti già attivi sull'assistente predefinito, né gli assistenti 1-4
(per quelli c'è `ops/allinea_prompt_assistenti.py`).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.environ.get("ONYX_API_URL", "http://127.0.0.1:3000/api")
ENV = Path(__file__).resolve().parent.parent / "deployment" / ".env"

STRUMENTO = "trasi_shim"

# Il marcatore è la prima riga: se c'è, la sezione c'è.
MARCATORE = "TRASI — strumenti della rete delle Case di Quartiere"
SEZIONE = f"""
{MARCATORE}:
Sei dentro Trasi, la piattaforma della rete delle Case di Quartiere di Brindisi. Chi ti scrive è un operatore di una Casa; la sua Casa è determinata dall'account, non chiederla.
Per eventi, luoghi, orari, servizi e proposte della rete usa SEMPRE gli strumenti `trasi_shim`: `eventi_oggi`, `vicino_a`, `cerca_luogo`, `oggi`, `crea_evento`, `proponi_modifica`, `approva_proposta`, `biglietto`.
Se l'operatore ti chiede di aggiungere un evento della sua Casa (titolo, giorno, ora), chiama SUBITO `crea_evento`: non chiedere conferma prima, non «memorizzarlo nelle note», non inventare eventi. L'evento esiste solo se lo strumento risponde con un `evento_id`.
Se ti dice che qualcosa è cambiato (chiusura, orario, servizio nuovo), chiama `proponi_modifica`.
Il campo `badge` che ricevi dagli strumenti va riportato verbatim in una riga a parte, es. [KB · inserito dall'operatore · 17/09/2026 · affidabilità 3].
Non chiedere né trascrivere dati personali della persona allo sportello.
"""


def _chiave() -> str:
    chiave = os.environ.get("ONYX_TRASI_KB_API_KEY")
    if not chiave and ENV.exists():
        for riga in ENV.read_text().splitlines():
            if riga.startswith("ONYX_TRASI_KB_API_KEY="):
                chiave = riga.split("=", 1)[1].strip().strip('"').strip("'")
    if not chiave:
        raise SystemExit(f"ONYX_TRASI_KB_API_KEY assente (ambiente o {ENV})")
    return chiave


def _richiesta(percorso: str, chiave: str, *, metodo: str = "GET", corpo: dict | None = None) -> dict:
    dati = json.dumps(corpo).encode() if corpo is not None else None
    richiesta = urllib.request.Request(
        f"{BASE}{percorso}",
        data=dati,
        method=metodo,
        headers={"Authorization": f"Bearer {chiave}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(richiesta, timeout=30) as risposta:
            grezzo = risposta.read().decode()
    except urllib.error.HTTPError as errore:
        raise SystemExit(f"{metodo} {percorso} → {errore.code}: {errore.read().decode()[:300]}") from None
    return json.loads(grezzo) if grezzo.strip() else {}


def main(argv: list[str] | None = None) -> int:
    argomenti = argparse.ArgumentParser(description="Allinea l'assistente predefinito di Onyx a Trasi")
    argomenti.add_argument("--dry-run", action="store_true", help="mostra cosa farebbe, senza scrivere")
    opzioni = argomenti.parse_args(argv)

    chiave = _chiave()

    strumenti = {s["name"]: s["id"] for s in _richiesta("/tool", chiave)}
    if STRUMENTO not in strumenti:
        raise SystemExit(f"strumento «{STRUMENTO}» non presente in Onyx: {sorted(strumenti)}")
    id_shim = strumenti[STRUMENTO]

    config = _richiesta("/admin/default-assistant/configuration", chiave)
    tool_ids: list[int] = list(config["tool_ids"])
    prompt_attuale: str | None = config.get("system_prompt")
    base = prompt_attuale if prompt_attuale is not None else config["default_system_prompt"]

    manca_strumento = id_shim not in tool_ids
    manca_sezione = MARCATORE not in base
    print(f"strumento {STRUMENTO} (id {id_shim}): {'MANCA' if manca_strumento else 'presente'}")
    print(f"sezione «{MARCATORE}»: {'MANCA' if manca_sezione else 'presente'}")

    if not (manca_strumento or manca_sezione):
        print("già allineato.")
        return 0
    if opzioni.dry_run:
        print("dry-run: nessuna scrittura.")
        return 0

    corpo: dict = {}
    if manca_strumento:
        corpo["tool_ids"] = tool_ids + [id_shim]
    if manca_sezione:
        corpo["system_prompt"] = base.rstrip() + "\n" + SEZIONE
    _richiesta("/admin/default-assistant", chiave, metodo="PATCH", corpo=corpo)

    # Verifica riletta dal server: un PATCH accettato ma non persistito è il difetto da escludere.
    dopo = _richiesta("/admin/default-assistant/configuration", chiave)
    ok_strumento = id_shim in dopo["tool_ids"]
    ok_sezione = MARCATORE in (dopo.get("system_prompt") or "")
    print(f"verifica: strumento {'OK' if ok_strumento else 'ASSENTE'} · sezione {'OK' if ok_sezione else 'ASSENTE'}")
    if not (ok_strumento and ok_sezione):
        return 1
    print("assistente predefinito allineato.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
