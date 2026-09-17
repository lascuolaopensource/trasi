#!/usr/bin/env python3
"""Crea in Onyx il connettore «Trasi KB (documenti esterni)» e lo aggiunge al document set degli assistenti.

**Perché un secondo connettore Ingestion API e non il cc_pair «Trasi KB (export)».** `flussi/export_kb.py`
tiene la KB uguale alla vista `v_kb_export`: pubblica le righe e **cancella** ogni documento ingestion
con id `trasi:*` che non è più nella vista. I documenti esterni (ZIP ISTAT, CSV Open Data Puglia, PDF
della Procura — `flussi/fonti_documenti.py`) non vengono dalla vista: hanno id `documento:*` e un
connettore proprio, così in amministrazione si vede quanti sono e da dove vengono, e un `prune` o una
cancellazione del connettore export non li tocca (e viceversa).

Il document set resta **uno** («Trasi KB (export)», id 1): i quattro assistenti lo hanno già collegato,
e aggiungere il cc_pair a quel set li fa vedere i documenti nuovi senza toccare le persona.

Idempotente: se un cc_pair con questo nome esiste già, non ne crea un secondo; se è già nel document set,
non lo riaggiunge. Scrive `documenti_cc_pair_id` in `shim/.onyx-kb.json` (nessun segreto: solo id), che
è dove `fonti_documenti.py` lo legge.

Uso (credenziali admin in `/root/.onyx_admin_creds`):

    python3 ops/provisiona_connettore_documenti.py
    python3 ops/provisiona_connettore_documenti.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from onyx_admin import richiesta, sessione  # noqa: E402

RADICE = Path(__file__).resolve().parent.parent
ONYX_KB_JSON = RADICE / "shim" / ".onyx-kb.json"

NOME_CONNETTORE = "Trasi KB (documenti esterni)"


def _cc_pair_per_nome(cookie: str, nome: str) -> dict | None:
    """Il cc_pair con questo nome, dallo stato di indicizzazione (l'unico elenco completo dell'API admin).

    In Onyx 4.7.2 è una `POST` paginata per sorgente: si filtra per `source` e `name_filter` e si legge
    `indexing_statuses[]` (`cc_pair_id`, `name`), che è tutto ciò che serve qui.
    """
    esito = richiesta(
        "/manage/admin/connector/indexing-status",
        cookie,
        metodo="POST",
        corpo={"source": "ingestion_api", "name_filter": nome, "get_all_connectors": True},
    )
    for blocco in esito:
        for voce in blocco.get("indexing_statuses", []):
            if voce.get("name") == nome:
                return voce
    return None


def main(argv: list[str] | None = None) -> int:
    argomenti = argparse.ArgumentParser(description="Provisiona il connettore Ingestion API dei documenti esterni")
    argomenti.add_argument("--dry-run", action="store_true", help="mostra cosa farebbe, senza scrivere")
    opzioni = argomenti.parse_args(argv)

    identificativi = json.loads(ONYX_KB_JSON.read_text(encoding="utf-8"))
    document_set_id = int(identificativi["document_set_id"])
    cookie = sessione()

    esistente = _cc_pair_per_nome(cookie, NOME_CONNETTORE)
    if esistente:
        cc_pair_id = int(esistente["cc_pair_id"])
        print(f"connettore «{NOME_CONNETTORE}» già presente: cc_pair_id={cc_pair_id}")
    elif opzioni.dry_run:
        print(f"dry-run: creerebbe il connettore «{NOME_CONNETTORE}» (ingestion_api, load_state, pubblico)")
        cc_pair_id = None
    else:
        richiesta(
            "/manage/admin/connector-with-mock-credential",
            cookie,
            metodo="POST",
            corpo={
                "name": NOME_CONNETTORE,
                "source": "ingestion_api",
                "input_type": "load_state",
                "connector_specific_config": {},
                "refresh_freq": None,
                "prune_freq": None,
                "indexing_start": None,
                "access_type": "public",
                "groups": [],
            },
        )
        creato = _cc_pair_per_nome(cookie, NOME_CONNETTORE)
        if not creato:
            print("il connettore è stato creato ma non compare nello stato di indicizzazione", file=sys.stderr)
            return 1
        cc_pair_id = int(creato["cc_pair_id"])
        print(f"connettore creato: cc_pair_id={cc_pair_id}")

    insieme = richiesta(f"/manage/admin/document-set/{document_set_id}", cookie)
    presenti = [int(d["id"]) for d in insieme.get("cc_pair_summaries", [])]
    if cc_pair_id is not None and cc_pair_id in presenti:
        print(f"document set {document_set_id} «{insieme['name']}»: cc_pair {cc_pair_id} già incluso")
    elif opzioni.dry_run:
        print(f"dry-run: aggiungerebbe il cc_pair al document set {document_set_id} «{insieme['name']}» (oggi: {presenti})")
    else:
        richiesta(
            "/manage/admin/document-set",
            cookie,
            metodo="PATCH",
            corpo={
                "id": document_set_id,
                "name": insieme["name"],
                "description": insieme.get("description") or "",
                "cc_pair_ids": presenti + [cc_pair_id],
                "is_public": insieme.get("is_public", True),
                "users": insieme.get("users") or [],
                "groups": insieme.get("groups") or [],
            },
        )
        riletto = richiesta(f"/manage/admin/document-set/{document_set_id}", cookie)
        nuovi = [int(d["id"]) for d in riletto.get("cc_pair_summaries", [])]
        if cc_pair_id not in nuovi:
            print(f"ATTENZIONE: il document set rilegge {nuovi}, senza {cc_pair_id}", file=sys.stderr)
            return 1
        print(f"document set {document_set_id}: cc_pair {nuovi}")

    if cc_pair_id is not None and identificativi.get("documenti_cc_pair_id") != cc_pair_id and not opzioni.dry_run:
        identificativi["documenti_cc_pair_id"] = cc_pair_id
        identificativi["documenti_connector_name"] = NOME_CONNETTORE
        ONYX_KB_JSON.write_text(json.dumps(identificativi, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{ONYX_KB_JSON.relative_to(RADICE)}: documenti_cc_pair_id={cc_pair_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
