#!/usr/bin/env python3
"""Trasi — F3 «Export KB» (blocco B2, B2-ONX-07): Postgres → KB di Onyx.

Legge la vista `trasi.v_kb_export` e la pubblica nella knowledge base di Onyx via **Ingestion API**
(`POST /onyx-api/ingestion`), sul connector dedicato «Trasi KB (export)».

Perché l'Ingestion API e non il File connector: in Onyx 4.7.2 il File connector legge unicamente UUID del
file store interno, non directory dell'host (`connectors/file/connector.py:287-302`). La decisione è in
`docs/trasi-architecture-v1.2.md` §5 App. B; il fallback Drive (V-02, rosso) resta manuale.

**Idempotenza.** `document.id` è l'id naturale della vista (`trasi:<entita>:<id>`): ripubblicare la stessa
riga sovrascrive il documento invece di duplicarlo, e la risposta riporta `already_existed=true`
(`server/onyx_api/ingestion.py` → `IndexingResult`). La seconda esecuzione non crea nulla.

**Fuori perimetro qui (B4-FLW-04).** Questo script pubblica e aggiorna; **non** cancella. La `DELETE` dei
`trasi:*` presenti in Onyx ma assenti dalla vista — cioè di un luogo chiuso o di un'opportunità scaduta —
è il passo di B4-FLW-04 (`plan.md` §4), che riusa questo stesso file. Aggiungerla qui la lascerebbe
scoperta in una batteria in cui la KB deve restare confrontabile con la vista.

Uso:
    flussi/export_kb.py                 # pubblica tutte le righe della vista
    flussi/export_kb.py --dry-run       # legge la vista e stampa cosa pubblicherebbe, senza POST

Configurazione (nessun segreto in questo file, né in output):
    ONYX_API_URL            default `http://127.0.0.1/api` — base dell'API Onyx vista da qui.
    ONYX_TRASI_KB_API_KEY   PAT Onyx con permesso `MANAGE_CONNECTORS` (in `deployment/.env`, mode 600).
    ONYX_KB_CC_PAIR_ID      cc_pair di destinazione; se assente, letto da `shim/.onyx-kb.json`.

Trasporto dati: `docker compose exec db_trasi psql` con `COPY … TO STDOUT WITH CSV HEADER` — nessuna
dipendenza Python oltre la stdlib, stessa via usata da `db/apply.sh`. Se lo script verrà eseguito *dentro*
un container (cron di B4) quel trasporto andrà riconciliato con la rete `trasi_net`.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
COMPOSE = RADICE / "deployment" / "docker-compose.yml"
ENV_DEPLOY = RADICE / "deployment" / ".env"
ONYX_KB_JSON = RADICE / "shim" / ".onyx-kb.json"

VISTA = "trasi.v_kb_export"
# Colonne della vista, nell'ordine dichiarato da `db/004_views.sql` (V4 · v_kb_export).
COLONNE = (
    "doc_id",
    "entita",
    "id",
    "titolo",
    "testo",
    "fonte_nome",
    "url",
    "data_aggiornamento",
    "affidabilita",
    "casa_nome",
)


class ExportErrore(RuntimeError):
    """Errore non recuperabile dell'export: la vista o l'API Onyx non rispondono come atteso."""


# --------------------------------------------------------------------------- configurazione


def _da_env_file(nome: str) -> str | None:
    """Legge una variabile da `deployment/.env` senza mai stamparne il valore."""
    try:
        with ENV_DEPLOY.open(encoding="utf-8") as f:
            for riga in f:
                riga = riga.strip()
                if not riga or riga.startswith("#") or "=" not in riga:
                    continue
                chiave, valore = riga.split("=", 1)
                if chiave == nome:
                    return valore
    except OSError:
        return None
    return None


def _config() -> tuple[str, str, int]:
    base_url = os.environ.get("ONYX_API_URL") or "http://127.0.0.1/api"
    api_key = os.environ.get("ONYX_TRASI_KB_API_KEY") or _da_env_file("ONYX_TRASI_KB_API_KEY") or ""
    if not api_key:
        raise ExportErrore(
            "PAT Onyx assente: valorizza ONYX_TRASI_KB_API_KEY (in deployment/.env, mode 600)"
        )

    cc_pair = os.environ.get("ONYX_KB_CC_PAIR_ID")
    if not cc_pair:
        try:
            with ONYX_KB_JSON.open(encoding="utf-8") as f:
                cc_pair = str(json.load(f)["cc_pair_id"])
        except (OSError, KeyError, ValueError) as exc:
            raise ExportErrore(
                f"cc_pair_id non determinabile: manca ONYX_KB_CC_PAIR_ID e {ONYX_KB_JSON} "
                "non è leggibile o non contiene `cc_pair_id`"
            ) from exc
    return base_url.rstrip("/"), api_key, int(cc_pair)


# --------------------------------------------------------------------------- lettura della vista


def leggi_vista() -> list[dict[str, str]]:
    """Righe di `v_kb_export` come lista di dizionari (tutti valori stringa o vuoti)."""
    sql = (
        f"COPY (SELECT {', '.join(COLONNE)} FROM {VISTA} ORDER BY doc_id) "
        "TO STDOUT WITH CSV HEADER"
    )
    cmd = [
        "docker", "compose", "-f", str(COMPOSE), "exec", "-T", "db_trasi",
        "psql", "-U", "postgres", "-d", "trasi_db", "-X", "-q", "-c", sql,
    ]
    try:
        esito = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise ExportErrore(f"`docker` non disponibile: {exc}") from exc
    if esito.returncode != 0:
        raise ExportErrore(
            f"lettura di {VISTA} fallita (exit {esito.returncode}): {esito.stderr.strip()}"
        )

    righe = list(csv.DictReader(io.StringIO(esito.stdout)))
    attese = set(COLONNE)
    mancanti = attese - set(righe[0].keys() if righe else attese)
    if mancanti:
        raise ExportErrore(f"{VISTA}: colonne attese assenti: {sorted(mancanti)}")
    return [{k: (v or "") for k, v in riga.items()} for riga in righe]


# --------------------------------------------------------------------------- pubblicazione


def _documento(riga: dict[str, str]) -> dict:
    """`document` per l'Ingestion API: id naturale, testo, e i metadati mostrati in amministrazione."""
    testo = riga["testo"] or riga["titolo"]
    return {
        # Id naturale `trasi:<entita>:<id>`: l'upsert è idempotente per costruzione.
        "id": riga["doc_id"],
        "semantic_identifier": riga["titolo"],
        "title": riga["titolo"],
        "sections": [{"text": testo, "link": riga["url"] or None}],
        "metadata": {
            "fonte": riga["fonte_nome"],
            "data_aggiornamento": riga["data_aggiornamento"],
            "affidabilita": riga["affidabilita"],
            "casa": riga["casa_nome"],
            "entita": riga["entita"],
        },
    }


def pubblica(base_url: str, api_key: str, cc_pair: int, documento: dict) -> bool:
    """POST di un documento. Ritorna `already_existed` (True ⇒ nessun duplicato creato)."""
    corpo = json.dumps({"cc_pair_id": cc_pair, "document": documento}).encode("utf-8")
    richiesta = urllib.request.Request(
        f"{base_url}/onyx-api/ingestion",
        data=corpo,
        method="POST",
        headers={
            # La chiave viaggia solo nell'header: mai in URL, mai nei log.
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(richiesta, timeout=120) as risposta:
            esito = json.loads(risposta.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        dettaglio = exc.read().decode("utf-8", errors="replace")[:300]
        raise ExportErrore(f"POST ingestion {documento['id']} → HTTP {exc.code}: {dettaglio}") from exc
    except urllib.error.URLError as exc:
        raise ExportErrore(f"POST ingestion {documento['id']} → API irraggiungibile: {exc.reason}") from exc
    return bool(esito.get("already_existed"))


# --------------------------------------------------------------------------- main


def cancellazione(base_url: str, api_key: str, da_cancellare: list[str]) -> int:
    """DELETE dei documenti `trasi:*` non più presenti nella vista.

    Serve a rispettare V3: se un luogo viene chiuso, un'opportunità scade o un evento è annullato,
    quel documento **non deve restare citabile** dalla chat. Senza questa cancellazione la KB
    conserva elementi che il database non ha più — e l'assistente li cita come se esistessero,
    con un badge che dichiara una fonte attendibile.

    L'`id` viaggia **URL-encoded** nel percorso (`trasi:luogo:6` → `trasi%3Aluogo%3A6`): è la stessa
    forma con cui Onyx lo memorizza, quindi si codifica qui e non si tenta di indovinarla.
    """
    cancellati = 0
    for doc_id in da_cancellare:
        # `doc_id` arriva nella forma memorizzata da Onyx (`trasi%3Aentita%3Aid`): per il
        # percorso della richiesta serve la codifica di quella stringa (v. `_id_nel_percorso`),
        # altrimenti FastAPI decodifica e l'id cercato non esiste → 404 su un documento presente.
        percorso = _id_nel_percorso(doc_id)
        richiesta = urllib.request.Request(
            f"{base_url}/onyx-api/ingestion/{percorso}",
            method="DELETE",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        try:
            with urllib.request.urlopen(richiesta, timeout=60):
                cancellati += 1
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                # Già assente: non è un errore, è idempotenza.
                continue
            dettaglio = exc.read().decode("utf-8", errors="replace")[:200]
            raise ExportErrore(f"DELETE ingestion {doc_id} → HTTP {exc.code}: {dettaglio}") from exc
        except urllib.error.URLError as exc:
            raise ExportErrore(f"DELETE ingestion {doc_id} → API irraggiungibile: {exc.reason}") from exc
    return cancellati


def leggi_onyx(base_url: str, api_key: str) -> list[str]:
    """Gli `id` dei documenti `trasi:*` presenti nella KB di Onyx, **nella forma memorizzata**.

    Onyx conserva l'id **URL-encoded** (`trasi:luogo:6` → `trasi%3Aluogo%3A6`) e lo restituisce
    così com'è: va usato in quella forma sia per confrontarlo con altri id di Onyx, sia per il
    `DELETE` (che cerca per id memorizzato). Decodificarlo produce un id che non esiste e ogni
    cancellazione diventa un 404 silenzioso — l'errore che questa funzione ha già commesso.
    """
    richiesta = urllib.request.Request(
        f"{base_url}/onyx-api/ingestion",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    with urllib.request.urlopen(richiesta, timeout=60) as risposta:
        documenti = json.loads(risposta.read().decode("utf-8"))
    return [
        d.get("document_id", "")
        for d in documenti
        if d.get("document_id", "").startswith("trasi")
    ]


def _id_come_onyx(doc_id: str) -> str:
    """L'id della vista (`trasi:entita:id`) nella forma memorizzata da Onyx (`trasi%3Aentita%3Aid`)."""
    return urllib.parse.quote(doc_id, safe="")


def _id_nel_percorso(doc_id_memorizzato: str) -> str:
    """L'id di Onyx codificato per il **percorso** della DELETE: doppia codifica.

    Onyx memorizza l'id come `trasi%3Aentita%3Aid` e la ricerca lo confronta con l'id nel
    percorso della richiesta (`get_document` → `WHERE id = :document_id`). FastAPI **decodifica
    una volta** il percorso: passando `trasi%3Aevento%3A470` arriva `trasi:evento:470`, che nel
    database non esiste → **404 silenzioso** su un documento che c'è.

    La forma che arriva corretta è quindi la codifica **della stringa già codificata**
    (`%253A`), che dopo la decodifica del framework diventa il `%3A` memorizzato. Verificato:
    `%%253A` → HTTP 200 e il documento sparisce; `%3A` → 404 e resta.
    """
    return urllib.parse.quote(doc_id_memorizzato, safe="")


def main(argv: list[str] | None = None) -> int:
    argomenti = argparse.ArgumentParser(description="Export di v_kb_export nella KB di Onyx")
    argomenti.add_argument("--dry-run", action="store_true", help="mostra cosa pubblicherebbe, senza POST")
    opzioni = argomenti.parse_args(argv)

    base_url, api_key, cc_pair = _config()
    righe = leggi_vista()
    print(f"v_kb_export: {len(righe)} righe · cc_pair={cc_pair} · destinazione={base_url}")

    if opzioni.dry_run:
        for riga in righe:
            print(f"  {riga['doc_id']:34s} {riga['titolo']}")
        return 0

    # Il registro del flusso (B4-FLW-04). `flusso_run` e `comune` sono importati **qui** e non in
    # testa: il file era già verificato in B2 e una sua dipendenza nuova in cima lo renderebbe
    # inutilizzabile dove `flussi/` non è nel `sys.path` (l'import locale isola il rischio al percorso
    # che ne ha bisogno). Se il registro non è disponibile l'export **continua**: la KB aggiornata è
    # il lavoro, la riga di registro è la sua traccia — e un guasto del registro non deve impedire
    # che la chat citi il dato nuovo il giorno dopo.
    run = None
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from comune import apri_run, registra_run

        run = apri_run("export_kb", cc_pair=cc_pair, righe_vista=len(righe))
    except Exception as errore:  # pragma: no cover - dipende dall'ambiente
        print(f"export_kb: registro non disponibile ({errore}) — l'export prosegue", file=sys.stderr)

    nuove, esistenti, cancellati = 0, 0, 0
    errore_ = None
    try:
        # Prima l'aggiornamento, poi la cancellazione: se la pubblicazione fallisce a metà,
        # meglio avere documenti aggiornati in più che averne cancellati di validi.
        for riga in righe:
            if pubblica(base_url, api_key, cc_pair, _documento(riga)):
                esistenti += 1
            else:
                nuove += 1

        # Cancellazione degli orfani: `trasi:*` in Onyx ma non più nella vista (luogo chiuso,
        # opportunità scaduta, evento annullato). Senza questo passo la chat citerebbe elementi
        # che il database non ha più — un difetto di V3, perché il badge dichiarerebbe una fonte
        # attendibile per un dato inesistente.
        try:
            presenti_onyx = leggi_onyx(base_url, api_key)
            # Entrambi gli insiemi nella forma memorizzata da Onyx: la vista usa i due punti,
            # Onyx il `%3A`. Si normalizza la vista, non Onyx, perché l'id di Onyx è quello
            # che serve al DELETE.
            doc_vista = {_id_come_onyx(r["doc_id"]) for r in righe}
            da_cancellare = sorted(set(presenti_onyx) - doc_vista)
            if da_cancellare:
                cancellati = cancellazione(base_url, api_key, da_cancellare)
        except ExportErrore:
            raise
        except Exception as errore:  # la cancellazione non deve impedire l'export riuscito
            print(f"export_kb: cancellazione non eseguita ({errore})", file=sys.stderr)
    except ExportErrore as errore:
        errore_ = errore
        raise
    finally:
        print(f"pubblicati: {nuove} nuovi · {esistenti} già presenti (upsert idempotente) · "
              f"totale vista {len(righe)}"
              + (f" · cancellati {cancellati} orfani" if cancellati else ""))
        if run is not None:
            # `n_righe` è il numero di documenti **nuovi** (non di righe della vista): è la sola
            # grandezza che dice se l'export ha fatto lavoro. Al secondo giro è 0 — e un 0 che si
            # legge nel registro è la prova dell'idempotenza, mentre `totale vista` sarebbe sempre 32.
            try:
                run.chiudi(
                    "errore" if errore_ else "ok",
                    nuove,
                    nuove=nuove, esistenti=esistenti, cancellati=cancellati, righe_vista=len(righe),
                    **({"errore": str(errore_)} if errore_ else {}),
                )
                registra_run(run)
            except Exception as errore:  # pragma: no cover - dipende dall'ambiente
                print(f"export_kb: registrazione del run fallita ({errore})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ExportErrore as errore:
        print(f"export_kb: {errore}", file=sys.stderr)
        sys.exit(1)
