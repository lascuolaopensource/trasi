"""Trasi — F4 «Fonti documenti»: file istituzionali (ZIP/CSV/PDF) → KB di Onyx, senza toccare il dominio.

Tutto offline: nessuna rete, nessun database, nessun POST. Le tre dipendenze esterne del flusso —
`leggi` (allow-list), `registra_run`/`registra_fonte_run` (registro) e `pubblica` (Ingestion API) — sono
sostituite da doppi che **registrano le chiamate**, e i test asseriscono su quelle: cosa sarebbe
finito in Onyx, e cosa nel registro. Il file da leggere è una fixture ridotta (CSV) o è costruito nel
test (zip POSAS, PDF): così il caso «solo Brindisi» è esplicito e non dipende da un file da 1,7 MB.

I contratti difesi:

* il filtro tiene le sole righe del comune e le raggruppa in sezioni da `RIGHE_PER_SEZIONE`;
* il riepilogo POSAS somma il solo comune 074001 (non la provincia) e dichiara la stima;
* l'id del documento **non inizia con `trasi`**: export_kb cancella gli orfani `trasi*` ogni notte;
* fonte inattiva → nessuna pubblicazione, voce in errore;
* `--dry-run` non chiama l'Ingestion API né il registro;
* PDF senza estrattore → la voce va in errore e il run prosegue (`parziale`), non cade.
"""

from __future__ import annotations

import io
import json
import shutil
import sys
import zipfile
from pathlib import Path

import pytest

RADICE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RADICE / "flussi"))

import fonti_documenti as fd  # noqa: E402

FIXTURES = RADICE / "flussi" / "fixtures"

FONTE_ATTIVA = {"id": 41, "nome": "Regione Puglia — Open Data", "attiva": True}
FONTE_INATTIVA = {"id": 42, "nome": "Procura della Repubblica di Brindisi", "attiva": False}


# --------------------------------------------------------------------------- doppi


class Doppi:
    """Le chiamate che il flusso farebbe verso l'esterno, registrate per essere lette dai test."""

    def __init__(self) -> None:
        self.pubblicati: list[dict] = []
        self.run: list = []
        self.fonte_run: list[tuple] = []


@pytest.fixture
def doppi(monkeypatch) -> Doppi:
    d = Doppi()
    monkeypatch.setattr(fd, "_config", lambda: ("http://onyx.test/api", "pat-di-prova", 7))
    monkeypatch.setattr(fd, "registra_run", lambda run: d.run.append(run))
    monkeypatch.setattr(
        fd, "registra_fonte_run",
        lambda fid, esito, righe, **kw: d.fonte_run.append((fid, esito, righe, kw.get("dettaglio"))),
    )

    def finta_pubblica(base_url, api_key, cc_pair, documento):
        d.pubblicati.append({"cc_pair": cc_pair, "documento": documento})
        return False  # «nuovo»

    monkeypatch.setattr(fd, "pubblica", finta_pubblica)
    # Nessun download: ogni voce dei test ha `file`; se una voce lo dimentica, si cade qui e non in rete.
    monkeypatch.setattr(fd, "scarica", lambda url: (_ for _ in ()).throw(AssertionError(f"rete usata: {url}")))
    return d


def _allowlist(monkeypatch, fonti: dict[str, dict | None]) -> None:
    monkeypatch.setattr(fd, "fonte_allowlist", lambda nome: fonti.get(nome))


def _voce(**campi) -> fd.Voce:
    base = dict(
        slug="prova", titolo="Documento di prova", fonte="Open Data Puglia-3", url="https://esempio.test/x.csv",
        tipo="csv", servizi=["OLD Front office"], attivo=True,
    )
    return fd.Voce(**{**base, **campi})


def _voce_registri(**campi) -> fd.Voce:
    base = dict(
        slug="puglia-registri", tipo="csv", file=str(FIXTURES / "registri_ridotto.csv"),
        filtro={"campo": "COMUNE_SEDE_OP", "valore": "Brindisi"},
    )
    return _voce(**{**base, **campi})


def _voce_facilitazione(**campi) -> fd.Voce:
    base = dict(
        slug="puglia-facilitazione", tipo="csv", file=str(FIXTURES / "facilitazione_ridotto.csv"),
        filtro={"campo": "comune", "valore": "brindisi"},   # minuscolo: il confronto non guarda il caso
    )
    return _voce(**{**base, **campi})


def _zip_posas(tmp_path: Path, *, con_totale: bool = True, con_nota: bool = True) -> Path:
    """Uno zip POSAS sintetico: due comuni × poche età, con la riga-titolo, il totale 999 e la nota."""
    righe = [
        '"Popolazione residente per età e sesso al 1° gennaio 2026 (stima)"',
        '"Codice comune";"Comune";"Età";"Totale maschi";"Totale femmine";"Totale"',
        '"074001";"Brindisi";0;10;20;30',
        '"074001";"Brindisi";14;10;10;20',
        '"074001";"Brindisi";15;20;30;50',
        '"074001";"Brindisi";64;10;10;20',
        '"074001";"Brindisi";65;5;5;10',
        '"074001";"Brindisi";80;2;3;5',
        '"074001";"Brindisi";100;0;1;1',
        '"074020";"Villa Castelli";0;100;100;200',
        '"074020";"Villa Castelli";65;100;100;200',
    ]
    if con_totale:
        righe += ['"074001";"Brindisi";999;57;79;136', '"074020";"Villa Castelli";999;200;200;400']
    if con_nota:
        righe.append('"Nota: lo stato civile è in corso di validazione."')
    percorso = tmp_path / "posas.zip"
    with zipfile.ZipFile(percorso, "w") as z:
        z.writestr("POSAS_2026_it_074_Brindisi.csv", "\ufeff" + "\r\n".join(righe) + "\r\n")
    return percorso


def _pdf_minimo(pagine: list[str]) -> bytes:
    """Un PDF valido con una riga di testo per pagina (font standard, nessuna dipendenza)."""
    oggetti: list[bytes] = []
    n_pag = len(pagine)
    # 1 catalogo, 2 pages, 3 font, poi per ogni pagina: page (4+2i) e contenuto (5+2i)
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(n_pag))
    oggetti.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    oggetti.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pag} >>".encode())
    oggetti.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, testo in enumerate(pagine):
        flusso = f"BT /F1 12 Tf 72 720 Td ({testo}) Tj ET".encode("latin-1")
        oggetti.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> "
            f"/Contents {5 + 2 * i} 0 R >>".encode()
        )
        oggetti.append(b"<< /Length " + str(len(flusso)).encode() + b" >>\nstream\n" + flusso + b"\nendstream")
    uscita = io.BytesIO()
    uscita.write(b"%PDF-1.4\n")
    offset = []
    for n, corpo in enumerate(oggetti, start=1):
        offset.append(uscita.tell())
        uscita.write(f"{n} 0 obj\n".encode() + corpo + b"\nendobj\n")
    xref = uscita.tell()
    uscita.write(f"xref\n0 {len(oggetti) + 1}\n0000000000 65535 f \n".encode())
    for o in offset:
        uscita.write(f"{o:010d} 00000 n \n".encode())
    uscita.write(f"trailer\n<< /Size {len(oggetti) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return uscita.getvalue()


def _estrattore_pdf_disponibile() -> bool:
    if shutil.which("pdftotext"):
        return True
    try:
        import pypdf  # noqa: F401
    except ImportError:
        return False
    return True


# --------------------------------------------------------------------------- CSV


def test_csv_filtro_tiene_solo_brindisi_e_raggruppa_in_sezioni(monkeypatch, doppi) -> None:
    """Dei 4 registri (2 Brindisi) entrano solo i 2 di Brindisi, in una sezione dopo l'intestazione."""
    _allowlist(monkeypatch, {"Open Data Puglia-3": FONTE_ATTIVA})
    monkeypatch.setattr(fd, "RIGHE_PER_SEZIONE", 1)   # una riga per sezione: il raggruppamento si vede

    assert fd.esegui([_voce_registri()], dry_run=False) == 0

    [pubblicazione] = doppi.pubblicati
    doc = pubblicazione["documento"]
    sezioni = [s["text"] for s in doc["sections"]]
    assert len(sezioni) == 1 + 2, "intestazione + una sezione per riga di Brindisi"
    corpo = "\n".join(sezioni[1:])
    assert "Ostuni" not in corpo and "Fasano" not in corpo, "le altre sedi non entrano"
    assert "Via Monte Sabotino 42" in corpo and "Lo Zaino" in corpo
    assert "COMUNE_SEDE_OP: Brindisi" in corpo
    assert "RICETTIVITA" not in sezioni[1], "i campi vuoti non producono righe «CAMPO: »"
    assert "Righe selezionate: 2 su 4" in sezioni[0]
    assert all(s["link"] == "https://esempio.test/x.csv" for s in doc["sections"])
    assert doppi.fonte_run == [(41, "ok", 3, {"slug": "puglia-registri", "url": "https://esempio.test/x.csv",
                                             "data_aggiornamento": doc["metadata"]["data_aggiornamento"],
                                             "gia_presente": False})]
    [run] = doppi.run
    assert (run.esito, run.n_righe, run.dettaglio["pubblicati"]) == ("ok", 1, ["puglia-registri"])


def test_csv_raggruppa_dieci_righe_per_sezione() -> None:
    """Con 12 righe: 10 + 2, non 12 sezioni né una sola (il chunking di Onyx lavora sulle sezioni)."""
    righe = "\n".join(["comune,nome"] + [f"Brindisi,Spazio {i}" for i in range(12)])
    info, sezioni = fd._estrai_csv(righe.encode("utf-8"), _voce(filtro={"campo": "comune", "valore": "Brindisi"}))
    assert len(sezioni) == 2
    assert sezioni[0].count("nome: Spazio") == 10 and sezioni[1].count("nome: Spazio") == 2
    assert info.startswith("Righe selezionate: 12 su 12")


def test_csv_esclude_i_campi_personali_v5() -> None:
    """Cognome e nome del legale rappresentante non entrano in KB, anche se il file li porta (V5)."""
    _, sezioni = fd._estrai_csv(
        (FIXTURES / "registri_ridotto.csv").read_bytes(),
        _voce(filtro={"campo": "COMUNE_SEDE_OP", "valore": "Brindisi"}),
    )
    testo = "\n".join(sezioni)
    assert "Rossi" not in testo and "Mario" not in testo
    assert "COGNOME_LEGALE" not in testo and "NOME_LEGALE" not in testo
    assert "DENOMINAZIONE_TITOLARE" in testo, "il titolare (ente) resta: è una struttura, non una persona"


def test_csv_riconosce_il_delimitatore_e_il_filtro_ignora_il_caso() -> None:
    """Fixture con `,` e BOM, filtro `brindisi` minuscolo → 1 riga su 3."""
    info, sezioni = fd._estrai_csv((FIXTURES / "facilitazione_ridotto.csv").read_bytes(), _voce_facilitazione())
    assert info.startswith("Righe selezionate: 1 su 3")
    assert len(sezioni) == 1 and "via Grazia Balsamo, 4" in sezioni[0]
    # Con delimitatore dichiarato sbagliato la colonna non esiste: errore parlante, non 0 righe.
    with pytest.raises(fd.DocumentoErrore, match="colonna 'comune'"):
        fd._estrai_csv((FIXTURES / "facilitazione_ridotto.csv").read_bytes(), _voce_facilitazione(delimitatore=";"))


def test_csv_senza_righe_dopo_il_filtro_non_si_pubblica(monkeypatch, doppi) -> None:
    """Un documento vuoto non entra in KB: sarebbe un titolo istituzionale senza contenuto."""
    _allowlist(monkeypatch, {"Open Data Puglia-3": FONTE_ATTIVA})
    voce = _voce_registri(filtro={"campo": "COMUNE_SEDE_OP", "valore": "Lecce"})
    assert fd.esegui([voce], dry_run=False) == 1
    assert doppi.pubblicati == []
    assert doppi.fonte_run[0][:2] == (41, "errore")
    assert "vuoto" in doppi.run[0].dettaglio["errori"][0]


def test_sniffer_che_non_riconosce_usa_la_virgola() -> None:
    """Un file di una sola colonna non ha delimitatore riconoscibile: si legge lo stesso."""
    righe = fd._righe_csv("nome\nSpazio A\nSpazio B\n", None)
    assert [r["nome"] for r in righe] == ["Spazio A", "Spazio B"]


# --------------------------------------------------------------------------- POSAS


def test_istat_posas_riepilogo_totali_e_fasce_solo_comune_074001(monkeypatch, doppi, tmp_path) -> None:
    """Il riepilogo somma Brindisi (136), non la provincia (536); fasce e percentuali sono coerenti."""
    _allowlist(monkeypatch, {"ISTAT-3": {"id": 5, "nome": "ISTAT", "attiva": True}})
    voce = _voce(
        slug="istat-posas", fonte="ISTAT-3", tipo="istat_posas", file=str(_zip_posas(tmp_path)),
        filtro={"campo": "Codice comune", "valore": "074001"},
    )
    assert fd.esegui([voce], dry_run=False) == 0

    doc = doppi.pubblicati[0]["documento"]
    intestazione, riepilogo, tabella = (s["text"] for s in doc["sections"])
    assert "Totale residenti: 136" in riepilogo, "solo Brindisi: la riga 999 e Villa Castelli non si sommano"
    assert "Maschi: 57 (41.9%)" in riepilogo and "Femmine: 79 (58.1%)" in riepilogo
    assert "0-14 anni: 50 (36.8%)" in riepilogo
    assert "15-64 anni: 70 (51.5%)" in riepilogo
    assert "65+ anni: 16 (11.8%)" in riepilogo
    assert "80+ anni: 6 (4.4%)" in riepilogo
    assert "stima al 1° gennaio 2026" in riepilogo
    assert "Villa Castelli" not in riepilogo + tabella
    assert "0: 10/20/30" in tabella and "100: 0/1/1" in tabella and "999" not in tabella
    assert "7 età" in intestazione


def test_istat_posas_senza_titolo_e_senza_totale(tmp_path) -> None:
    """Un file senza riga-titolo né riga 999 si legge lo stesso: il parser non li presuppone."""
    righe = [
        '"Codice comune";"Comune";"Età";"Totale maschi";"Totale femmine";"Totale"',
        '"074001";"Brindisi";0;1;1;2',
        '"074001";"Brindisi";70;1;1;2',
    ]
    percorso = tmp_path / "p.zip"
    with zipfile.ZipFile(percorso, "w") as z:
        z.writestr("x.csv", "\n".join(righe))
    info, (riepilogo, _) = fd._estrai_posas(percorso.read_bytes(), _voce(tipo="istat_posas"))
    assert "Totale residenti: 4" in riepilogo and "65+ anni: 2 (50.0%)" in riepilogo
    assert info.startswith("Comune Brindisi: 2 età")


def test_istat_posas_zip_illeggibile_o_senza_csv_o_senza_righe(tmp_path) -> None:
    with pytest.raises(fd.DocumentoErrore, match="zip illeggibile"):
        fd._estrai_posas(b"non sono uno zip", _voce(tipo="istat_posas"))
    senza_csv = tmp_path / "vuoto.zip"
    with zipfile.ZipFile(senza_csv, "w") as z:
        z.writestr("leggimi.txt", "niente")
    with pytest.raises(fd.DocumentoErrore, match="non contiene un CSV"):
        fd._estrai_posas(senza_csv.read_bytes(), _voce(tipo="istat_posas"))
    with pytest.raises(fd.DocumentoErrore, match="nessuna riga per età"):
        fd._estrai_posas(
            _zip_posas(tmp_path).read_bytes(),
            _voce(tipo="istat_posas", filtro={"campo": "Codice comune", "valore": "999999"}),
        )


# --------------------------------------------------------------------------- id e metadati


def test_id_documento_non_inizia_con_trasi() -> None:
    """Contratto con export_kb: la cancellazione degli orfani (`id.startswith('trasi')`) non deve toccarlo."""
    voce = _voce_registri(slug="puglia-registri-strutture-servizi-sociali-2023", affidabilita=1,
                          servizi=["OLD Osservatorio sociale", "NEW 4 Monitoraggio PA"])
    doc = fd.documento(voce, ["intestazione", "corpo"], nome_fonte="Regione Puglia — Open Data", data="2026-09-16")
    assert doc["id"] == "documento:puglia-registri-strutture-servizi-sociali-2023"
    assert not doc["id"].startswith("trasi")
    assert doc["metadata"] == {
        "fonte": "Regione Puglia — Open Data",
        "data_aggiornamento": "2026-09-16",
        "affidabilita": "1",
        "entita": "documento",
        "url": "https://esempio.test/x.csv",
        "servizi": "OLD Osservatorio sociale, NEW 4 Monitoraggio PA",
    }
    assert all(isinstance(v, str) for v in doc["metadata"].values()), "Onyx accetta metadati stringa"
    assert doc["semantic_identifier"] == doc["title"] == voce.titolo
    assert [s["link"] for s in doc["sections"]] == [voce.url, voce.url]


def test_registro_reale_ha_quattro_voci_valide_con_id_non_trasi() -> None:
    """Il registro del repo carica e ogni voce produrrebbe un id fuori dal perimetro di export_kb."""
    voci = fd.carica_registro(fd.REGISTRO)
    assert len(voci) == 4 and all(v.attivo for v in voci)
    assert {v.tipo for v in voci} == {"istat_posas", "csv", "pdf"}
    assert all(not f"documento:{v.slug}".startswith("trasi") for v in voci)
    assert all(v.affidabilita == 1 for v in voci), "affidabilità 1: non verificato dalla rete (l'AT può alzarla)"


# --------------------------------------------------------------------------- allow-list


def test_fonte_inattiva_non_pubblica_e_va_in_errore(monkeypatch, doppi) -> None:
    """Una fonte fuori allow-list (assente o `attiva=false`) non si pubblica: la voce va in errore."""
    _allowlist(monkeypatch, {"Procura di Brindisi-3": FONTE_INATTIVA, "Open Data Puglia-3": FONTE_ATTIVA})
    voci = [
        _voce_registri(slug="inattiva", fonte="Procura di Brindisi-3"),
        _voce_registri(slug="assente", fonte="Fonte che non c'è"),
        _voce_registri(slug="buona"),
    ]
    assert fd.esegui(voci, dry_run=False) == 0

    assert [p["documento"]["id"] for p in doppi.pubblicati] == ["documento:buona"]
    [run] = doppi.run
    assert run.esito == "parziale"
    assert sorted(e.split(":")[0] for e in run.dettaglio["errori"]) == ["assente", "inattiva"]
    assert all("allow-list" in e for e in run.dettaglio["errori"])
    # Una fonte fuori allow-list non ha un `fonte_run`: non è stata consultata.
    assert [fr[0] for fr in doppi.fonte_run] == [41]


def test_voce_inattiva_si_dichiara_e_non_si_pubblica(monkeypatch, doppi) -> None:
    _allowlist(monkeypatch, {"Open Data Puglia-3": FONTE_ATTIVA})
    assert fd.esegui([_voce_registri(attivo=False)], dry_run=False) == 0
    assert doppi.pubblicati == [] and doppi.fonte_run == []
    assert doppi.run[0].dettaglio["inattivi"] == ["puglia-registri"] and doppi.run[0].esito == "ok"


def test_fonte_allowlist_legge_autorita_e_attiva(monkeypatch) -> None:
    """Il nome umano è l'autorità (badge V3); `attiva` arriva da psql come `t`/`f`."""
    monkeypatch.setattr(fd, "leggi", lambda q: [{"id": "9", "nome_umano": "ISTAT", "attiva": "t"}])
    assert fd.fonte_allowlist("ISTAT-3") == {"id": 9, "nome": "ISTAT", "attiva": True}
    monkeypatch.setattr(fd, "leggi", lambda q: [{"id": "9", "nome_umano": "X", "attiva": "f"}])
    assert fd.fonte_allowlist("X-1")["attiva"] is False
    monkeypatch.setattr(fd, "leggi", lambda q: [])
    assert fd.fonte_allowlist("Nessuna") is None


# --------------------------------------------------------------------------- dry-run e configurazione


def test_dry_run_non_chiama_ingestion(monkeypatch, doppi, capsys) -> None:
    """`--dry-run`: né POST, né registro, né allow-list; stampa titolo, sezioni e anteprima."""
    monkeypatch.setattr(fd, "fonte_allowlist", lambda nome: pytest.fail("il dry-run non interroga il database"))
    monkeypatch.setattr(fd, "_config", lambda: pytest.fail("il dry-run non ha bisogno della PAT"))
    assert fd.esegui([_voce_registri()], dry_run=True) == 0
    assert doppi.pubblicati == [] and doppi.run == [] and doppi.fonte_run == []
    uscita = capsys.readouterr().out
    assert "«Documento di prova» · 2 sezioni" in uscita
    assert "REGISTRO: Anziani" in uscita and "Affido Anziani" in uscita, "anteprima del testo estratto"
    assert "nessun POST" in uscita


def test_config_assente_chiude_il_run_in_errore(monkeypatch, doppi) -> None:
    """Senza PAT o cc_pair il flusso non prova nemmeno a scaricare: registra `errore` ed esce 1."""
    monkeypatch.setattr(fd, "_config", lambda: (_ for _ in ()).throw(fd.DocumentoErrore("PAT Onyx assente")))
    assert fd.esegui([_voce_registri()], dry_run=False) == 1
    [run] = doppi.run
    assert run.esito == "errore" and "PAT Onyx assente" in run.dettaglio["errore"]
    assert doppi.pubblicati == []


def test_config_legge_env_e_json(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ONYX_API_URL", "http://onyx.test/api/")
    monkeypatch.setenv("ONYX_TRASI_KB_API_KEY", "pat")
    monkeypatch.setenv("ONYX_DOCUMENTI_CC_PAIR_ID", "12")
    assert fd._config() == ("http://onyx.test/api", "pat", 12)

    monkeypatch.delenv("ONYX_DOCUMENTI_CC_PAIR_ID")
    kb = tmp_path / "kb.json"
    kb.write_text(json.dumps({"cc_pair_id": 3, "documenti_cc_pair_id": 8}), encoding="utf-8")
    monkeypatch.setattr(fd, "ONYX_KB_JSON", kb)
    assert fd._config()[2] == 8

    kb.write_text(json.dumps({"cc_pair_id": 3}), encoding="utf-8")
    with pytest.raises(fd.DocumentoErrore, match="documenti_cc_pair_id"):
        fd._config()

    monkeypatch.delenv("ONYX_TRASI_KB_API_KEY")
    monkeypatch.setattr(fd, "_da_env_file", lambda nome: None)
    with pytest.raises(fd.DocumentoErrore, match="PAT Onyx assente"):
        fd._config()


# --------------------------------------------------------------------------- PDF


def test_pdf_senza_estrattore_va_in_errore_e_run_parziale(monkeypatch, doppi, tmp_path) -> None:
    """Né `pdftotext` né `pypdf`: la voce PDF va in errore con il dettaglio, le altre si pubblicano."""
    _allowlist(monkeypatch, {"Open Data Puglia-3": FONTE_ATTIVA, "Procura di Brindisi-3": {**FONTE_INATTIVA, "attiva": True}})
    monkeypatch.setattr(fd.shutil, "which", lambda nome: None)
    monkeypatch.setitem(sys.modules, "pypdf", None)   # `import pypdf` → ImportError
    pdf = tmp_path / "cav.pdf"
    pdf.write_bytes(b"%PDF-1.4 finto")
    voci = [
        _voce(slug="procura", fonte="Procura di Brindisi-3", tipo="pdf", file=str(pdf)),
        _voce_registri(),
    ]
    assert fd.esegui(voci, dry_run=False) == 0

    assert [p["documento"]["id"] for p in doppi.pubblicati] == ["documento:puglia-registri"]
    [run] = doppi.run
    assert run.esito == "parziale"
    assert run.dettaglio["errori"] == ["procura: nessun estrattore PDF (pdftotext/pypdf)"]
    assert (42, "errore", 0) == doppi.fonte_run[0][:3]
    assert doppi.fonte_run[0][3]["errore"] == "nessun estrattore PDF (pdftotext/pypdf)"


@pytest.mark.skipif(not _estrattore_pdf_disponibile(), reason="né pdftotext né pypdf: l'estrazione PDF non si prova qui")
def test_pdf_una_sezione_per_pagina_con_testo() -> None:
    """Due pagine con testo → intestazione + 2 sezioni «Pagina N»; una pagina vuota non produce sezione."""
    contenuto = _pdf_minimo(["Centro Antiviolenza Brindisi tel 0831", "", "Sportello Mesagne"])
    sezioni = fd.estrai(_voce(tipo="pdf"), contenuto, nome_fonte="Procura", data="2026-09-16")
    assert len(sezioni) == 3
    assert sezioni[1].startswith("Pagina 1") and "Centro Antiviolenza Brindisi" in sezioni[1]
    assert sezioni[2].startswith("Pagina 3") and "Sportello Mesagne" in sezioni[2]
    assert "Pagine con testo: 2 su 3" in sezioni[0]


def test_pdf_via_pdftotext_e_suoi_errori(monkeypatch) -> None:
    """Con `pdftotext` nel PATH si usa quello: una pagina per form feed; exit ≠ 0 → errore parlante."""
    monkeypatch.setattr(fd.shutil, "which", lambda nome: "/usr/bin/pdftotext")

    class Esito:
        def __init__(self, rc, out="", err=""):
            self.returncode, self.stdout, self.stderr = rc, out, err

    monkeypatch.setattr(fd.subprocess, "run", lambda *a, **k: Esito(0, "prima\n\n\n\npagina\fseconda\f"))
    assert fd._pagine_pdf(b"%PDF") == ["prima\n\n\n\npagina", "seconda", ""]
    info, sezioni = fd._estrai_pdf(b"%PDF", _voce(tipo="pdf"))
    assert sezioni == ["Pagina 1\n\nprima\n\npagina", "Pagina 2\n\nseconda"], "righe vuote multiple compresse"
    assert info == "Pagine con testo: 2 su 3"

    monkeypatch.setattr(fd.subprocess, "run", lambda *a, **k: Esito(1, "", "Syntax Error: file corrotto"))
    with pytest.raises(fd.DocumentoErrore, match="pdftotext ha fallito"):
        fd._pagine_pdf(b"%PDF")

    monkeypatch.setattr(fd.subprocess, "run", lambda *a, **k: Esito(0, "\f\f"))
    with pytest.raises(fd.DocumentoErrore, match="non ha testo estraibile"):
        fd._estrai_pdf(b"%PDF", _voce(tipo="pdf"))


def test_pdf_illeggibile_con_pypdf(monkeypatch) -> None:
    pypdf = pytest.importorskip("pypdf")
    monkeypatch.setattr(fd.shutil, "which", lambda nome: None)
    with pytest.raises(fd.DocumentoErrore, match="PDF illeggibile"):
        fd._pagine_pdf(b"questo non e' un PDF")
    assert pypdf  # importato davvero: il ramo pypdf è quello percorso


# --------------------------------------------------------------------------- origine del file


def test_scarica_conserva_last_modified_e_dichiara_gli_errori(monkeypatch) -> None:
    import urllib.error

    class Risposta:
        def __init__(self, corpo, intestazioni):
            self.corpo, self.headers = corpo, intestazioni

        def read(self):
            return self.corpo

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    richieste = []

    def finto_urlopen(richiesta, timeout):
        richieste.append((richiesta.get_header("User-agent"), timeout))
        return Risposta(b"a,b\n1,2\n", {"Last-Modified": "Tue, 15 Sep 2026 10:00:00 GMT"})

    monkeypatch.setattr(fd.urllib.request, "urlopen", finto_urlopen)
    assert fd.scarica("https://esempio.test/x.csv") == (b"a,b\n1,2\n", "2026-09-15")
    assert richieste == [(fd.UA, fd.TIMEOUT_S)], "UA identificativo e timeout dei file, non delle pagine"

    monkeypatch.setattr(fd.urllib.request, "urlopen",
                        lambda r, timeout: Risposta(b"x", {"Last-Modified": "non è una data"}))
    assert fd.scarica("https://esempio.test/x.csv")[1] is None
    monkeypatch.setattr(fd.urllib.request, "urlopen", lambda r, timeout: Risposta(b"x", {}))
    assert fd.scarica("https://esempio.test/x.csv")[1] is None, "senza intestazione: nessuna data (vale oggi)"

    def http_404(r, timeout):
        raise urllib.error.HTTPError(url="u", code=404, msg="Not Found", hdrs=None, fp=None)  # type: ignore[arg-type]

    monkeypatch.setattr(fd.urllib.request, "urlopen", http_404)
    with pytest.raises(fd.DocumentoErrore, match="HTTP 404"):
        fd.scarica("https://esempio.test/x.csv")

    def giu(r, timeout):
        raise urllib.error.URLError("connessione rifiutata")

    monkeypatch.setattr(fd.urllib.request, "urlopen", giu)
    with pytest.raises(fd.DocumentoErrore, match="irraggiungibile"):
        fd.scarica("https://esempio.test/x.csv")


def test_leggi_origine_usa_il_file_locale_o_la_rete(monkeypatch) -> None:
    contenuto, data = fd.leggi_origine(_voce_facilitazione())
    assert contenuto.startswith(b"\xef\xbb\xbfid,avvio") and len(data) == 10
    # Percorso relativo: risolto dalla radice del repo.
    contenuto2, _ = fd.leggi_origine(_voce(file="flussi/fixtures/facilitazione_ridotto.csv"))
    assert contenuto2 == contenuto

    monkeypatch.setattr(fd, "scarica", lambda url: (b"x", None))
    assert fd.leggi_origine(_voce())[1] == fd.date.today().isoformat(), "senza Last-Modified vale oggi"
    monkeypatch.setattr(fd, "scarica", lambda url: (b"x", "2026-01-31"))
    assert fd.leggi_origine(_voce())[1] == "2026-01-31"


def test_file_non_utf8_va_in_errore_parlante() -> None:
    with pytest.raises(fd.DocumentoErrore, match="non è UTF-8"):
        fd.estrai(_voce(), b"comune,nome\n\xff\xfe,x\n", nome_fonte="F", data="2026-09-16")


# --------------------------------------------------------------------------- registro e CLI


def test_registro_rifiuta_voci_incomplete_o_tipi_sconosciuti(tmp_path) -> None:
    base = {"slug": "s", "titolo": "t", "fonte": "f", "url": "u", "tipo": "csv"}
    with pytest.raises(fd.DocumentoErrore, match="manca `titolo`"):
        fd.Voce.da_json({**base, "titolo": ""})
    with pytest.raises(fd.DocumentoErrore, match="tipo 'xlsx' non supportato"):
        fd.Voce.da_json({**base, "tipo": "xlsx"})
    with pytest.raises(fd.DocumentoErrore, match="filtro di 's' non valido"):
        fd.Voce.da_json({**base, "filtro": {"campo": "comune"}})
    with pytest.raises(fd.DocumentoErrore, match="delimitatore"):
        fd.Voce.da_json({**base, "delimitatore": "|"})
    voce = fd.Voce.da_json({**base, "servizi": ["A"], "affidabilita": "2"})
    assert (voce.affidabilita, voce.servizi, voce.attivo, voce.filtro) == (2, ["A"], True, None)

    with pytest.raises(fd.DocumentoErrore, match="illeggibile"):
        fd.carica_registro(tmp_path / "manca.json")
    vuoto = tmp_path / "vuoto.json"
    vuoto.write_text('{"documenti": []}', encoding="utf-8")
    with pytest.raises(fd.DocumentoErrore, match="attesa una lista"):
        fd.carica_registro(vuoto)
    lista = tmp_path / "lista.json"
    lista.write_text(json.dumps([base]), encoding="utf-8")
    assert [v.slug for v in fd.carica_registro(lista)] == ["s"]


def test_main_solo_e_file_selezionano_e_attivano_la_voce(monkeypatch, doppi, tmp_path, capsys) -> None:
    """`--solo` sceglie la voce, `--file` la legge da disco e la attiva anche se il registro la sospende."""
    registro = tmp_path / "reg.json"
    registro.write_text(json.dumps({"documenti": [
        {"slug": "a", "titolo": "A", "fonte": "Open Data Puglia-3", "url": "https://e.test/a.csv", "tipo": "csv",
         "filtro": {"campo": "comune", "valore": "Brindisi"}, "attivo": False},
        {"slug": "b", "titolo": "B", "fonte": "Open Data Puglia-3", "url": "https://e.test/b.csv", "tipo": "csv"},
    ]}), encoding="utf-8")
    argomenti = ["--config", str(registro), "--dry-run"]

    assert fd.main(argomenti + ["--solo", "a", "--file", str(FIXTURES / "facilitazione_ridotto.csv")]) == 0
    assert "«A» · 2 sezioni" in capsys.readouterr().out

    assert fd.main(argomenti + ["--solo", "zz"]) == 1
    assert "nessuna voce con slug 'zz'" in capsys.readouterr().err
    assert fd.main(argomenti + ["--file", "x.csv"]) == 1
    assert "--file vale per una voce sola" in capsys.readouterr().err
    assert fd.main(["--config", str(tmp_path / "manca.json")]) == 1
    assert "illeggibile" in capsys.readouterr().err


def test_eseguibile_da_riga_di_comando(monkeypatch, capsys) -> None:
    """`python3 flussi/fonti_documenti.py --dry-run --solo … --file …` gira come script (shebang + main)."""
    import runpy

    monkeypatch.setattr(sys, "argv", [
        fd.__file__, "--dry-run", "--solo", "puglia-punti-facilitazione-digitale",
        "--file", str(FIXTURES / "facilitazione_ridotto.csv"),
    ])
    with pytest.raises(SystemExit) as uscita:
        runpy.run_path(fd.__file__, run_name="__main__")
    assert uscita.value.code == 0
    assert "Punti di facilitazione digitale — Brindisi" in capsys.readouterr().out


def test_main_senza_file_scarica_e_pubblica(monkeypatch, doppi, tmp_path) -> None:
    """Il percorso di produzione: registro → allow-list → download → estrazione → POST → registro."""
    _allowlist(monkeypatch, {"Open Data Puglia-3": FONTE_ATTIVA})
    monkeypatch.setattr(fd, "scarica", lambda url: ((FIXTURES / "facilitazione_ridotto.csv").read_bytes(), "2026-09-10"))
    registro = tmp_path / "reg.json"
    registro.write_text(json.dumps([
        {"slug": "pfd", "titolo": "Punti", "fonte": "Open Data Puglia-3", "url": "https://e.test/pfd.csv",
         "tipo": "csv", "filtro": {"campo": "comune", "valore": "Brindisi"}},
    ]), encoding="utf-8")
    assert fd.main(["--config", str(registro)]) == 0
    [p] = doppi.pubblicati
    assert p["cc_pair"] == 7 and p["documento"]["metadata"]["data_aggiornamento"] == "2026-09-10"
    assert p["documento"]["metadata"]["fonte"] == "Regione Puglia — Open Data", "l'autorità della riga fonte, non lo slug"
    assert doppi.run[0].esito == "ok"


def test_errore_della_api_va_in_errore_e_nel_registro(monkeypatch, doppi) -> None:
    """Un POST che fallisce non fa cadere il run: la voce va in errore con il dettaglio della API."""
    _allowlist(monkeypatch, {"Open Data Puglia-3": FONTE_ATTIVA})

    def post_ko(*a):
        raise fd.ExportErrore("POST ingestion documento:puglia-registri → HTTP 500: boom")

    monkeypatch.setattr(fd, "pubblica", post_ko)
    assert fd.esegui([_voce_registri()], dry_run=False) == 1
    assert doppi.run[0].esito == "errore" and "HTTP 500" in doppi.run[0].dettaglio["errori"][0]
    assert doppi.fonte_run == [(41, "errore", 0, {"slug": "puglia-registri", "url": "https://esempio.test/x.csv",
                                                 "errore": "POST ingestion documento:puglia-registri → HTTP 500: boom"})]


def test_seconda_pubblicazione_conta_come_aggiornamento(monkeypatch, doppi) -> None:
    """Idempotenza: `already_existed=true` → 0 nuovi, 1 aggiornato, `n_righe = 0` nel registro."""
    _allowlist(monkeypatch, {"Open Data Puglia-3": FONTE_ATTIVA})
    monkeypatch.setattr(fd, "pubblica", lambda *a: True)
    assert fd.esegui([_voce_registri()], dry_run=False) == 0
    [run] = doppi.run
    assert (run.n_righe, run.dettaglio["nuovi"], run.dettaglio["esistenti"]) == (0, 0, 1)
    assert doppi.fonte_run[0][3]["gia_presente"] is True
