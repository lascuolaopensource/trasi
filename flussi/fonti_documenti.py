#!/usr/bin/env python3
"""Trasi — F4 «Fonti documenti»: file istituzionali (ZIP, CSV, PDF) → KB di Onyx.

Perché esiste. Fra i link che la rete ha indicato come utili (`.orca/drops/link_scartati.json`) quattro
**non sono pagine**: lo zip ISTAT della popolazione residente (POSAS), due CSV di Open Data Puglia
(punti di facilitazione digitale, registri delle strutture socio-assistenziali) e il PDF della Procura
con i contatti dei centri antiviolenza. Il connettore `web` di Onyx li scarta — non c'è HTML da
parsare — e senza questo flusso la chat non li cita mai. Qui si scarica il file, si riduce a testo
leggibile (per Brindisi soltanto, dove il file è regionale o provinciale) e si pubblica con la stessa
**Ingestion API** di `flussi/export_kb.py` (`POST /onyx-api/ingestion`), su un connector dedicato.

**Non è una scrittura sul dominio.** Nessuna riga di `luogo`, `scheda_servizio`, `evento`, `opportunita`
viene toccata: si scrive solo la KB, che è una proiezione. Per questo il flusso non passa da `proposta`
(V4 riguarda la memoria della rete, non l'indice) e non produce `audit`. La governance è di V3: ogni
documento porta `fonte`, `data_aggiornamento` e **`affidabilita = 1`** — è di una fonte istituzionale,
ma nessuno di Trasi l'ha verificato — e la fonte deve essere una riga **attiva** di `trasi.fonte`
(allow-list §3): fonte assente o inattiva → la voce va in errore e non si pubblica.

**L'id è `documento:<slug>`, e non deve mai iniziare con `trasi`.** `export_kb.py` cancella dalla KB ogni
documento ingestion il cui id inizia con `trasi` e non è nella vista (orfani di luoghi chiusi, eventi
annullati). Un documento di questo flusso con un id `trasi:…` verrebbe cancellato ogni notte alle 01:00
e ripubblicato la domenica: un dato che c'è sei giorni su sette. Il prefisso diverso è il contratto fra
i due flussi, e il test `test_id_documento_non_inizia_con_trasi` lo difende.

**Idempotenza.** Lo stesso slug → lo stesso `document.id` → upsert (`already_existed=true`). Il flusso
è settimanale (crontab, domenica 01:30): l'ISTAT pubblica una volta l'anno, i registri regionali
idem, il PDF è stabile. Rieseguirlo non crea nulla di nuovo.

**V5.** Le colonne che portano una persona (cognome/nome del legale rappresentante, codice fiscale) si
escludono sempre (`CAMPI_PERSONALI`): la KB descrive strutture e servizi, non chi li rappresenta.

Uso:
    flussi/fonti_documenti.py                                   # tutte le voci del registro
    flussi/fonti_documenti.py --dry-run                         # scarica ed estrae, non pubblica
    flussi/fonti_documenti.py --solo istat-posas-brindisi-2026 --file /tmp/posas.zip --dry-run
    flussi/fonti_documenti.py --config flussi/fixtures/fonti_documenti.json

`--dry-run` non tocca né Onyx né il database: non serve la PAT, e stampa per ogni voce titolo, numero
di sezioni e un'anteprima del testo. È il modo di vedere «cosa entrerebbe in KB» prima di farlo entrare.

Configurazione (come export_kb; nessun segreto qui né in output):
    ONYX_API_URL                default `http://127.0.0.1/api`
    ONYX_TRASI_KB_API_KEY       PAT Onyx (in `deployment/.env`, mode 600)
    ONYX_DOCUMENTI_CC_PAIR_ID   cc_pair del connector dei documenti; se assente, letto da
                                `shim/.onyx-kb.json["documenti_cc_pair_id"]`
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass, field
from datetime import date
from email.utils import parsedate_to_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from comune import (  # noqa: E402
    FlussoErrore,
    apri_run,
    leggi,
    log,
    registra_fonte_run,
    registra_run,
)
from export_kb import ONYX_KB_JSON, ExportErrore, _da_env_file, pubblica  # noqa: E402
from fonti_http import UA  # noqa: E402

RADICE = Path(__file__).resolve().parent.parent
REGISTRO = RADICE / "flussi" / "fixtures" / "fonti_documenti.json"

#: I file sono grandi (il CSV dei registri è 1,7 MB) e i portali lenti: 60 s, non i 10 delle pagine.
TIMEOUT_S = 60

#: Righe di CSV per sezione. Onyx spezza il testo in chunk: una sezione per riga sarebbe rumorosa
#: (95 sezioni da tre righe), una sola sezione per 95 righe troppo lunga per un chunk utile.
RIGHE_PER_SEZIONE = 10

#: Colonne che identificano una **persona** e non una struttura (V5). Il confronto è sul nome della
#: colonna, senza maiuscole; `nome` da solo non c'è perché `nomeDelloSpazio` è il nome di un luogo.
CAMPI_PERSONALI = re.compile(r"cognome|nome_legale|codice_fiscale|cod_?fisc", re.IGNORECASE)

TIPI = ("csv", "istat_posas", "pdf")

#: Fasce d'età del riepilogo POSAS: quelle che l'Osservatorio sociale usa (minori, attivi, anziani,
#: grandi anziani). `None` = senza limite superiore.
FASCE = (("0-14", 0, 14), ("15-64", 15, 64), ("65+", 65, None), ("80+", 80, None))


class DocumentoErrore(FlussoErrore):
    """Errore di una voce: file illeggibile, filtro su una colonna assente, nessun estrattore."""


# --------------------------------------------------------------------------- registro


@dataclass
class Voce:
    """Un documento da pubblicare: dove si scarica, come si legge, con quale fonte si dichiara."""

    slug: str
    titolo: str
    fonte: str
    url: str
    tipo: str
    affidabilita: int = 1
    servizi: list[str] = field(default_factory=list)
    filtro: dict | None = None
    delimitatore: str | None = None
    attivo: bool = True
    file: str | None = None   # file locale al posto del download (test, diagnosi con `--solo`)

    @classmethod
    def da_json(cls, voce: dict) -> "Voce":
        for campo in ("slug", "titolo", "fonte", "url", "tipo"):
            if not voce.get(campo):
                raise DocumentoErrore(f"voce incompleta: manca `{campo}` in {voce!r}")
        if voce["tipo"] not in TIPI:
            raise DocumentoErrore(
                f"tipo {voce['tipo']!r} non supportato per {voce['slug']!r}: i tipi sono {', '.join(TIPI)}"
            )
        filtro = voce.get("filtro")
        if filtro is not None and not (isinstance(filtro, dict) and filtro.get("campo") and "valore" in filtro):
            raise DocumentoErrore(f"filtro di {voce['slug']!r} non valido: atteso {{campo, valore}}")
        if voce.get("delimitatore") not in (None, ",", ";"):
            raise DocumentoErrore(f"delimitatore di {voce['slug']!r} non valido: `,` o `;`")
        return cls(
            slug=voce["slug"], titolo=voce["titolo"], fonte=voce["fonte"], url=voce["url"],
            tipo=voce["tipo"], affidabilita=int(voce.get("affidabilita", 1)),
            servizi=[str(s) for s in voce.get("servizi") or []], filtro=filtro,
            delimitatore=voce.get("delimitatore"), attivo=bool(voce.get("attivo", True)),
            file=voce.get("file"),
        )


def carica_registro(percorso: Path) -> list[Voce]:
    """Il registro dei documenti: una lista o `{"documenti": […]}` (la forma con le note a lato)."""
    try:
        contenuto = json.loads(percorso.read_text(encoding="utf-8"))
    except (OSError, ValueError) as errore:
        raise DocumentoErrore(f"registro {percorso} illeggibile: {errore}") from errore
    voci = contenuto.get("documenti") if isinstance(contenuto, dict) else contenuto
    if not isinstance(voci, list) or not voci:
        raise DocumentoErrore(f"registro {percorso}: attesa una lista di documenti (o `{{\"documenti\": […]}}`)")
    return [Voce.da_json(v) for v in voci]


# --------------------------------------------------------------------------- configurazione


def _config() -> tuple[str, str, int]:
    """`(base_url, api_key, cc_pair)` — la stessa forma di export_kb, con il cc_pair dei documenti."""
    base_url = os.environ.get("ONYX_API_URL") or "http://127.0.0.1/api"
    api_key = os.environ.get("ONYX_TRASI_KB_API_KEY") or _da_env_file("ONYX_TRASI_KB_API_KEY") or ""
    if not api_key:
        raise DocumentoErrore(
            "PAT Onyx assente: valorizza ONYX_TRASI_KB_API_KEY (in deployment/.env, mode 600)"
        )
    cc_pair = os.environ.get("ONYX_DOCUMENTI_CC_PAIR_ID")
    if not cc_pair:
        try:
            with ONYX_KB_JSON.open(encoding="utf-8") as f:
                cc_pair = str(json.load(f)["documenti_cc_pair_id"])
        except (OSError, KeyError, ValueError) as exc:
            raise DocumentoErrore(
                "cc_pair dei documenti non determinabile: manca ONYX_DOCUMENTI_CC_PAIR_ID e "
                f"{ONYX_KB_JSON} non contiene `documenti_cc_pair_id` (il connector dei documenti va "
                "creato in Onyx e il suo id annotato lì, come per `cc_pair_id`)"
            ) from exc
    return base_url.rstrip("/"), api_key, int(cc_pair)


# --------------------------------------------------------------------------- origine del file


def scarica(url: str) -> tuple[bytes, str | None]:
    """`(contenuto, data)`: il file e la sua `Last-Modified` come `YYYY-MM-DD` (o `None` se assente)."""
    richiesta = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(richiesta, timeout=TIMEOUT_S) as risposta:
            contenuto = risposta.read()
            ultima_modifica = risposta.headers.get("Last-Modified")
    except urllib.error.HTTPError as errore:
        raise DocumentoErrore(f"{url} → HTTP {errore.code}") from errore
    except (urllib.error.URLError, TimeoutError, OSError) as errore:
        raise DocumentoErrore(f"{url} irraggiungibile: {errore}") from errore
    return contenuto, _data_http(ultima_modifica)


def _data_http(valore: str | None) -> str | None:
    """`Last-Modified` (RFC 7231) → `YYYY-MM-DD`; un'intestazione malformata vale come assente."""
    if not valore:
        return None
    try:
        return parsedate_to_datetime(valore).date().isoformat()
    except (TypeError, ValueError):
        return None


def leggi_origine(voce: Voce) -> tuple[bytes, str]:
    """Il file della voce e la sua `data_aggiornamento`.

    Da rete si conserva `Last-Modified` quando il server la dichiara — è la data del **dato**, non della
    lettura, ed è quella che il badge V3 deve mostrare. Senza intestazione, o da file locale, vale la
    data odierna: è comunque la data in cui Trasi ha consultato la fonte.
    """
    if voce.file:
        percorso = Path(voce.file)
        if not percorso.is_absolute():
            percorso = RADICE / percorso
        return percorso.read_bytes(), date.today().isoformat()
    contenuto, data = scarica(voce.url)
    return contenuto, data or date.today().isoformat()


# --------------------------------------------------------------------------- estrattori


def _uguale(a: str, b: str) -> bool:
    return (a or "").strip().casefold() == (b or "").strip().casefold()


def _righe_csv(testo: str, delimitatore: str | None) -> list[dict[str, str]]:
    """Le righe di un CSV come dizionari. Il delimitatore dichiarato vince; altrimenti lo si riconosce."""
    if not delimitatore:
        try:
            delimitatore = csv.Sniffer().sniff(testo[:4096], delimiters=",;").delimiter
        except csv.Error:
            delimitatore = ","
    return list(csv.DictReader(io.StringIO(testo), delimiter=delimitatore))


def _filtra(righe: list[dict[str, str]], filtro: dict | None, colonne: list[str]) -> list[dict[str, str]]:
    """Le righe che soddisfano `filtro`. Un filtro su una colonna assente è un errore di configurazione:
    zero righe «perché la colonna non c'è» passerebbero per «a Brindisi non ce n'è»."""
    if not filtro:
        return righe
    campo = filtro["campo"]
    if campo not in colonne:
        raise DocumentoErrore(f"filtro sulla colonna {campo!r} che il file non ha (colonne: {colonne[:8]}…)")
    return [r for r in righe if _uguale(r.get(campo) or "", str(filtro["valore"]))]


def _blocco(riga: dict[str, str]) -> str:
    """Una riga come blocco «CAMPO: valore», solo campi non vuoti e mai quelli personali (V5)."""
    return "\n".join(
        f"{campo}: {' '.join(valore.split())}"
        for campo, valore in riga.items()
        if campo and valore and valore.strip() and not CAMPI_PERSONALI.search(campo)
    )


def _estrai_csv(contenuto: bytes, voce: Voce) -> tuple[str, list[str]]:
    testo = contenuto.decode("utf-8-sig")
    righe = _righe_csv(testo, voce.delimitatore)
    colonne = list(righe[0].keys()) if righe else []
    scelte = _filtra(righe, voce.filtro, colonne)
    blocchi = [b for b in (_blocco(r) for r in scelte) if b]
    sezioni = [
        "\n\n".join(blocchi[i:i + RIGHE_PER_SEZIONE]) for i in range(0, len(blocchi), RIGHE_PER_SEZIONE)
    ]
    info = f"Righe selezionate: {len(scelte)} su {len(righe)}"
    if voce.filtro:
        info += f" ({voce.filtro['campo']} = {voce.filtro['valore']})"
    return info, sezioni


def _estrai_posas(contenuto: bytes, voce: Voce) -> tuple[str, list[str]]:
    """Il CSV POSAS dentro lo zip → riepilogo per fasce d'età e tabella per età, per il solo comune."""
    try:
        with zipfile.ZipFile(io.BytesIO(contenuto)) as archivio:
            nomi = [n for n in archivio.namelist() if n.lower().endswith(".csv")]
            if not nomi:
                raise DocumentoErrore("lo zip non contiene un CSV")
            testo = archivio.read(nomi[0]).decode("utf-8-sig")
    except zipfile.BadZipFile as errore:
        raise DocumentoErrore(f"zip illeggibile: {errore}") from errore

    # La prima riga è il titolo del prospetto («Popolazione residente per età e sesso al 1° gennaio
    # 2026 (stima)»), non l'intestazione: si tiene come dicitura e si salta per il parser.
    righe_testo = testo.splitlines()
    dicitura = righe_testo[0].strip().strip('"') if righe_testo and ";" not in righe_testo[0] else ""
    corpo = "\n".join(righe_testo[1:] if dicitura else righe_testo)
    righe = list(csv.DictReader(io.StringIO(corpo), delimiter=";"))
    colonne = list(righe[0].keys()) if righe else []
    scelte = _filtra(righe, voce.filtro, colonne)

    # Età 999 è il totale già calcolato dall'ISTAT; si ricalcola dalle età così riepilogo e tabella
    # sono coerenti fra loro per costruzione. Le righe che non sono età (la nota in coda) si saltano.
    per_eta: dict[int, tuple[int, int, int]] = {}
    comune = ""
    for r in scelte:
        eta = (r.get("Età") or "").strip()
        if not eta.isdigit() or int(eta) == 999:
            continue
        comune = comune or (r.get("Comune") or "").strip()
        per_eta[int(eta)] = (
            int(r.get("Totale maschi") or 0), int(r.get("Totale femmine") or 0), int(r.get("Totale") or 0)
        )
    if not per_eta:
        raise DocumentoErrore("nessuna riga per età dopo il filtro: codice comune sbagliato o file cambiato")

    maschi = sum(v[0] for v in per_eta.values())
    femmine = sum(v[1] for v in per_eta.values())
    totale = sum(v[2] for v in per_eta.values())

    def fascia(da: int, a: int | None) -> int:
        return sum(v[2] for eta, v in per_eta.items() if eta >= da and (a is None or eta <= a))

    def pct(n: int) -> str:
        return f"{100 * n / totale:.1f}%" if totale else "n/d"

    righe_riepilogo = [
        f"{dicitura or 'Popolazione residente per età e sesso al 1° gennaio 2026 (stima)'} — Comune di {comune or 'Brindisi'}.",
        "Nota: stima al 1° gennaio 2026 (dato ISTAT POSAS, non censimento).",
        f"Totale residenti: {_n(totale)}",
        f"Maschi: {_n(maschi)} ({pct(maschi)})",
        f"Femmine: {_n(femmine)} ({pct(femmine)})",
        "",
        "Fasce d'età:",
    ]
    for nome, da, a in FASCE:
        n = fascia(da, a)
        righe_riepilogo.append(f"  {nome} anni: {_n(n)} ({pct(n)})")
    riepilogo = "\n".join(righe_riepilogo)

    tabella = "\n".join(
        [f"Residenti per età (età: maschi/femmine/totale; 100 = 100 e più) — {comune or 'Brindisi'}:"]
        + [f"{eta}: {m}/{f}/{t}" for eta, (m, f, t) in sorted(per_eta.items())]
    )
    info = f"Comune {comune or 'selezionato'}: {len(per_eta)} età, {_n(totale)} residenti (stima al 1° gennaio)"
    return info, [riepilogo, tabella]


def _n(numero: int) -> str:
    """Migliaia con il punto, come si legge in italiano (81.181, non 81,181)."""
    return f"{numero:,}".replace(",", ".")


def _pagine_pdf(contenuto: bytes) -> list[str]:
    """Il testo di ogni pagina. `pdftotext` (poppler, nel container) o `pypdf` (sull'host); nessuno dei
    due → errore parlante: la voce va in errore e il run prosegue."""
    if shutil.which("pdftotext"):
        with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
            tmp.write(contenuto)
            tmp.flush()
            esito = subprocess.run(
                ["pdftotext", "-layout", tmp.name, "-"], capture_output=True, text=True, check=False
            )
        if esito.returncode != 0:
            raise DocumentoErrore(f"pdftotext ha fallito (exit {esito.returncode}): {esito.stderr.strip()[:200]}")
        return esito.stdout.split("\f")
    try:
        import pypdf  # noqa: PLC0415 - opzionale: c'è sull'host, non nell'immagine
    except ImportError as errore:
        raise DocumentoErrore("nessun estrattore PDF (pdftotext/pypdf)") from errore
    try:
        lettore = pypdf.PdfReader(io.BytesIO(contenuto))
        return [pagina.extract_text() or "" for pagina in lettore.pages]
    except Exception as errore:  # pypdf solleva eccezioni proprie, non una gerarchia stabile
        raise DocumentoErrore(f"PDF illeggibile: {errore}") from errore


def _normalizza(testo: str) -> str:
    """Spazi finali via, righe vuote multiple compresse a una: il layout del PDF non è contenuto."""
    righe = [r.rstrip() for r in testo.splitlines()]
    uscita: list[str] = []
    for r in righe:
        if r or (uscita and uscita[-1]):
            uscita.append(r)
    return "\n".join(uscita).strip()


def _estrai_pdf(contenuto: bytes, voce: Voce) -> tuple[str, list[str]]:
    pagine = [_normalizza(p) for p in _pagine_pdf(contenuto)]
    sezioni = [f"Pagina {n}\n\n{p}" for n, p in enumerate(pagine, start=1) if p]
    if not sezioni:
        raise DocumentoErrore("il PDF non ha testo estraibile (scansione senza OCR?)")
    return f"Pagine con testo: {len(sezioni)} su {len(pagine)}", sezioni


ESTRATTORI = {"csv": _estrai_csv, "istat_posas": _estrai_posas, "pdf": _estrai_pdf}


def estrai(voce: Voce, contenuto: bytes, *, nome_fonte: str, data: str) -> list[str]:
    """Le sezioni del documento: la prima è l'intestazione (titolo, fonte, url, data, cosa contiene)."""
    try:
        info, sezioni = ESTRATTORI[voce.tipo](contenuto, voce)
    except UnicodeDecodeError as errore:
        raise DocumentoErrore(f"il file non è UTF-8: {errore}") from errore
    if not sezioni:
        raise DocumentoErrore("nessun contenuto dopo il filtro: il documento non si pubblica vuoto")
    intestazione = "\n".join([
        voce.titolo,
        f"Fonte: {nome_fonte}",
        f"URL: {voce.url}",
        f"Data di aggiornamento: {data}",
        info,
    ])
    return [intestazione] + sezioni


# --------------------------------------------------------------------------- pubblicazione


def documento(voce: Voce, sezioni: list[str], *, nome_fonte: str, data: str) -> dict:
    """`document` per l'Ingestion API. I metadati di Onyx sono stringhe (o liste di stringhe)."""
    return {
        # `documento:<slug>` e non `trasi:…`: export_kb cancella gli orfani `trasi*` (vedi docstring).
        "id": f"documento:{voce.slug}",
        "semantic_identifier": voce.titolo,
        "title": voce.titolo,
        "sections": [{"text": s, "link": voce.url} for s in sezioni],
        "metadata": {
            "fonte": nome_fonte,
            "data_aggiornamento": data,
            "affidabilita": str(voce.affidabilita),
            "entita": "documento",
            "url": voce.url,
            "servizi": ", ".join(voce.servizi),
        },
    }


def _lit(testo: str) -> str:
    return "'" + str(testo).replace("'", "''") + "'"


def fonte_allowlist(nome: str) -> dict | None:
    """`{id, nome, attiva}` della riga di `trasi.fonte`, o `None`. Il nome umano è l'autorità
    (`COALESCE(NULLIF(autorita,''), nome)`): è quello del badge V3, come nello shim."""
    righe = leggi(
        "SELECT id, COALESCE(NULLIF(autorita, ''), nome) AS nome_umano, attiva "
        f"  FROM trasi.fonte WHERE nome = {_lit(nome)}"
    )
    if not righe:
        return None
    r = righe[0]
    return {"id": int(r["id"]), "nome": r["nome_umano"], "attiva": r["attiva"].strip().lower() in ("t", "true")}


# --------------------------------------------------------------------------- main


def esegui(voci: list[Voce], *, dry_run: bool) -> int:
    run = apri_run("fonti_documenti", documenti=len(voci))
    pubblicati: list[str] = []
    errori: list[str] = []
    inattivi: list[str] = []
    nuovi = esistenti = 0
    if not dry_run:
        try:
            base_url, api_key, cc_pair = _config()
        except FlussoErrore as errore:
            log(f"fonti_documenti: {errore}")
            run.chiudi("errore", 0, errore=str(errore))
            registra_run(run)
            return 1

    for voce in voci:
        if not voce.attivo:
            inattivi.append(voce.slug)
            log(f"  {voce.slug}: inattivo → non pubblicato")
            continue

        fid: int | None = None
        try:
            if dry_run:
                nome_fonte = voce.fonte
            else:
                fonte = fonte_allowlist(voce.fonte)
                if fonte is None or not fonte["attiva"]:
                    raise DocumentoErrore(
                        f"fonte {voce.fonte!r} non in allow-list o inattiva → non si pubblica (§3)"
                    )
                fid, nome_fonte = fonte["id"], fonte["nome"]

            contenuto, data = leggi_origine(voce)
            sezioni = estrai(voce, contenuto, nome_fonte=nome_fonte, data=data)
            doc = documento(voce, sezioni, nome_fonte=nome_fonte, data=data)

            if dry_run:
                anteprima = " ".join("\n".join(sezioni[1:]).split())[:300]
                log(f"  {voce.slug}: «{voce.titolo}» · {len(sezioni)} sezioni · data {data}")
                log(f"    {anteprima}")
                pubblicati.append(voce.slug)
                continue

            gia = pubblica(base_url, api_key, cc_pair, doc)
            if gia:
                esistenti += 1
            else:
                nuovi += 1
            pubblicati.append(voce.slug)
            log(f"  {voce.slug}: pubblicato ({'aggiornato' if gia else 'nuovo'}, {len(sezioni)} sezioni, data {data})")
            registra_fonte_run(fid, "ok", len(sezioni),
                               dettaglio={"slug": voce.slug, "url": voce.url, "data_aggiornamento": data,
                                          "gia_presente": gia})
        except (FlussoErrore, ExportErrore, OSError) as errore:
            errori.append(f"{voce.slug}: {errore}")
            log(f"  {voce.slug}: errore ({errore})")
            if fid is not None:
                registra_fonte_run(fid, "errore", 0,
                                   dettaglio={"slug": voce.slug, "url": voce.url, "errore": str(errore)})

    esito = "errore" if errori and not pubblicati else ("parziale" if errori else "ok")
    run.chiudi(esito, nuovi, pubblicati=pubblicati, nuovi=nuovi, esistenti=esistenti,
               errori=errori, inattivi=inattivi, dry_run=dry_run)
    if not dry_run:
        registra_run(run)

    conteggio = (f"{len(pubblicati)} estratti (dry-run: nessun POST, nessun registro)" if dry_run
                 else f"{len(pubblicati)} pubblicati ({nuovi} nuovi · {esistenti} aggiornati)")
    log(f"fonti_documenti: {conteggio} · {len(inattivi)} inattivi · {len(errori)} errori · esito={esito}")
    return 0 if esito != "errore" else 1


def main(argv: list[str] | None = None) -> int:
    argomenti = argparse.ArgumentParser(description="F4 · documenti istituzionali (ZIP/CSV/PDF) → KB di Onyx")
    argomenti.add_argument("--config", default=str(REGISTRO), help="registro dei documenti (JSON)")
    argomenti.add_argument("--solo", help="limita a una voce (slug)")
    argomenti.add_argument("--file", help="usa questo file locale invece del download (richiede --solo)")
    argomenti.add_argument("--dry-run", action="store_true", help="scarica ed estrae; nessun POST, nessun registro")
    opzioni = argomenti.parse_args(argv)

    try:
        voci = carica_registro(Path(opzioni.config))
    except FlussoErrore as errore:
        print(f"errore: {errore}", file=sys.stderr)
        return 1

    if opzioni.solo:
        voci = [v for v in voci if v.slug == opzioni.solo]
        if not voci:
            print(f"errore: nessuna voce con slug {opzioni.solo!r}", file=sys.stderr)
            return 1
    if opzioni.file:
        if len(voci) != 1:
            print("errore: --file vale per una voce sola: indica --solo <slug>", file=sys.stderr)
            return 1
        # Un file locale è, per costruzione, una voce che si vuole provare: si attiva anche se il
        # registro la tiene sospesa, altrimenti `--file` verrebbe ignorato in silenzio.
        voci = [Voce(**{**voci[0].__dict__, "file": opzioni.file, "attivo": True})]

    return esegui(voci, dry_run=opzioni.dry_run)


if __name__ == "__main__":
    sys.exit(main())
