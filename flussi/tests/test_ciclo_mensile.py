"""Trasi — F5 ciclo mensile: 10 digest + 1 report PN, con le celle k-anonime nel CSV.

Il criterio B6-FLW-02: un run manuale produce **10 digest** (uno per Casa, incluso Tuturano che cade
sul fallback AT) e **1 report PN** con il CSV `trasi_rete_YYYY-MM.csv`; le celle sotto la soglia di
k-anonimato sono `«<5»`; il run schedulato gira **prima delle 09:00**.

Il test verifica anche le due proprietà che rendono il ciclo sostenibile: **idempotenza** (un secondo
run non raddoppia i digest) e **V6** (nessun messaggio assegna compiti). Un ciclo che rimanda dieci
email ogni volta che lo si esegue per provare è un ciclo che si smette di eseguire.
"""

from __future__ import annotations

import csv
import io
import re
import subprocess
import sys
from pathlib import Path

import pytest

RADICE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RADICE / "flussi"))

import ciclo_mensile  # noqa: E402
from comune import v6_ok  # noqa: E402

CSV_DIR = RADICE / "flussi" / "evidenze" / "ciclo_mensile"
LUOGHI = 10


def _esegui(*argomenti: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(RADICE / "flussi" / "ciclo_mensile.py"), *argomenti],
        capture_output=True, text=True, check=False,
    )


@pytest.fixture
def ciclo_pulito(pulizia, db_vivo):
    if not db_vivo:
        pytest.skip("database non raggiungibile: il ciclo legge le viste di B1")
    pulizia(registro=True, proposte=False)
    yield
    pulizia(registro=True, proposte=False)


@pytest.mark.live
def test_dieci_digest_e_un_report_pn(db_vivo, psql, ciclo_pulito):
    """10 digest (uno per Casa) + 1 report PN: è il criterio B6-FLW-02."""
    esito = _esegui("--dry-run")
    assert esito.returncode == 0, f"il ciclo è fallito:\n{esito.stderr}"

    # Le righe dei messaggi hanno il prefisso `[HH:MM:SS]` di `log()` e la forma
    # `  → destinatario: oggetto`. Si filtra su quella forma: la riga di riepilogo contiene anch'essa
    # una freccia («… → /percorso/csv») e contarla darebbe 12 invece di 11.
    righe = [r for r in esito.stdout.splitlines()
             if r.split("]", 1)[-1].lstrip().startswith("→")]
    assert len(righe) == LUOGHI + 1, (
        f"attesi {LUOGHI} digest + 1 report PN = {LUOGHI + 1} messaggi, trovati {len(righe)}:\n"
        + "\n".join(righe)
    )

    # Un digest per Casa, tutti diversi: nessuna Casa senza recapito e nessun duplicato.
    destinatari = [r.split("→")[1].split(":")[0].strip() for r in righe]
    assert len(set(destinatari)) == LUOGHI + 1, f"destinatari duplicati: {destinatari}"

    # Il report PN c'è ed è distinto dai digest.
    pn = [r for r in righe if "report di rete" in r]
    assert len(pn) == 1, f"atteso 1 report PN, trovati {len(pn)}: {pn}"

    # Tuturano è incluso (ha `email_digest` NULL e cade sull'identità gestore).
    assert any("tuturano" in r.lower() for r in righe), (
        "Tuturano manca dal ciclo: è la Casa con i dati provvisori e il fallback AT"
    )


@pytest.mark.live
def test_csv_con_celle_k_anonime(db_vivo, psql, ciclo_pulito):
    """Il CSV esiste, è leggibile, e le celle sotto soglia sono «<5» — non il numero grezzo."""
    esito = _esegui("--dry-run")
    assert esito.returncode == 0

    mese = ciclo_mensile._mese_corrente(None)
    percorso = CSV_DIR / f"trasi_rete_{mese.strftime('%Y-%m')}.csv"
    assert percorso.exists(), f"il CSV non è stato scritto: {percorso}"

    testo = percorso.read_text(encoding="utf-8")
    righe = list(csv.reader(io.StringIO(testo)))
    assert righe[0] == ["casa", "categoria", "esito", "n"], f"intestazione inattesa: {righe[0]}"

    # Ogni cella `n` è o un intero ≥ soglia, o una maschera: mai un numero sotto soglia.
    soglia = int(psql("SELECT trasi.p_int('k_anonimato') AS v")[0]["v"] or 5)
    for riga in righe[1:]:
        cella = riga[3]
        if cella.isdigit():
            assert int(cella) >= soglia, (
                f"cella sotto soglia nel CSV: {riga} — il numero grezzo non deve uscire (§12)"
            )
        else:
            assert cella in ("<5", f"<{soglia}", "—"), f"maschera inattesa: {cella!r} in {riga}"


@pytest.mark.live
def test_k_anonimato_maschera_sotto_soglia(db_vivo, psql, ciclo_pulito):
    """3 richieste su una Casa → la vista dà `n` NULL e `n_label` = «<5», e il CSV trascrive «<5».

    La fixture gira in transazione con `ROLLBACK`: le prove su un DB condiviso non devono lasciare
    righe (lezione di B3).
    """
    from comune import COMPOSE, DB_DEFAULT, SERVIZIO_DB
    import os

    sql = """
BEGIN;
INSERT INTO trasi.richiesta (casa_id, categoria, esito, ts)
SELECT c.id, 'fiscale_isee', 'risolta', now() FROM trasi.casa c WHERE c.slug = 'bozzano';
INSERT INTO trasi.richiesta (casa_id, categoria, esito, ts)
SELECT c.id, 'fiscale_isee', 'risolta', now() FROM trasi.casa c WHERE c.slug = 'bozzano';
INSERT INTO trasi.richiesta (casa_id, categoria, esito, ts)
SELECT c.id, 'fiscale_isee', 'risolta', now() FROM trasi.casa c WHERE c.slug = 'bozzano';
SELECT n::text, n_label FROM trasi.v_report_mensile
 WHERE casa_slug = 'bozzano' AND categoria = 'fiscale_isee'
   AND mese = date_trunc('month', current_date);
ROLLBACK;
"""
    comando = [
        "docker", "compose", "-f", str(COMPOSE), "exec", "-T", SERVIZIO_DB,
        "psql", "-U", "postgres", "-d", os.environ.get("TRASI_DB") or DB_DEFAULT,
        "-X", "-q", "-t", "-A", "-F", "|", "-f", "-",
    ]
    esito = subprocess.run(comando, input=sql, capture_output=True, text=True, check=False)
    assert esito.returncode == 0, f"fixture k-anon fallita: {esito.stderr[:400]}"

    riga = [r for r in esito.stdout.splitlines() if "|" in r]
    assert riga, f"la vista non ha restituito la riga attesa: {esito.stdout!r}"
    n_grezzo, n_label = riga[-1].split("|")
    assert n_grezzo == "", f"il numero grezzo è uscito: {n_grezzo!r} (atteso NULL sotto soglia)"
    assert n_label == "<5", f"l'etichetta attesa è «<5», ottenuta {n_label!r}"


@pytest.mark.live
def test_dry_run_non_persiste_i_report(db_vivo, psql, ciclo_pulito):
    """Il dry-run produce il CSV ma **non** scrive in `trasi.report` (US-4).

    Una bozza scritta da un dry-run farebbe nascere un report che nessuno ha deciso di produrre:
    il criterio del dry-run è «si mostra, non si fa», e vale per la persistenza come per l'invio.
    """
    mese = ciclo_mensile._mese_corrente(None)

    prima = psql(
        "SELECT count(*) AS n FROM trasi.report "
        f" WHERE mese = DATE '{mese.isoformat()}'"
    )
    esito = _esegui("--dry-run")
    assert esito.returncode == 0, f"il dry-run è fallito: {esito.stderr}"
    dopo = psql(
        "SELECT count(*) AS n FROM trasi.report "
        f" WHERE mese = DATE '{mese.isoformat()}'"
    )
    assert dopo[0]["n"] == prima[0]["n"], (
        f"il dry-run ha scritto in trasi.report: prima {prima[0]['n']}, dopo {dopo[0]['n']}"
    )

    # Il CSV invece c'è: è il deliverable da controllare prima di inviare.
    percorso = CSV_DIR / f"trasi_rete_{mese.strftime('%Y-%m')}.csv"
    assert percorso.exists(), f"il dry-run non ha prodotto il CSV: {percorso}"


@pytest.mark.live
def test_idempotenza_secondo_run_non_rinvia(db_vivo, psql, ciclo_pulito):
    """Un secondo run nello stesso mese **non** raddoppia i digest: esce senza inviare, e lo dichiara."""
    primo = _esegui()
    assert primo.returncode == 0, f"il primo run è fallito:\n{primo.stderr}"

    registro = psql(
        "SELECT esito, n_righe, dettaglio FROM trasi.flusso_run "
        " WHERE nome = 'ciclo_mensile' ORDER BY id DESC LIMIT 1"
    )
    assert registro, "il ciclo non ha scritto in `flusso_run`"
    assert registro[0]["esito"] == "ok"
    assert int(registro[0]["n_righe"]) == LUOGHI + 1, (
        f"attesi {LUOGHI + 1} messaggi, dichiarati {registro[0]['n_righe']}"
    )

    secondo = _esegui()
    assert secondo.returncode == 0, f"il secondo run è fallito:\n{secondo.stderr}"
    assert "già eseguito" in secondo.stdout, (
        f"il secondo run non ha dichiarato di essere un doppio:\n{secondo.stdout}"
    )

    ultimo = psql(
        "SELECT esito, n_righe, dettaglio FROM trasi.flusso_run "
        " WHERE nome = 'ciclo_mensile' ORDER BY id DESC LIMIT 1"
    )[0]
    assert int(ultimo["n_righe"]) == 0, "il secondo run ha reinviato i digest"
    assert "true" in ultimo["dettaglio"], f"il registro non dichiara il doppio: {ultimo['dettaglio']}"

    # `--forza` è la via dichiarata per rimandare.
    forzato = _esegui("--forza")
    assert forzato.returncode == 0
    ultimo_forzato = psql(
        "SELECT n_righe, dettaglio FROM trasi.flusso_run "
        " WHERE nome = 'ciclo_mensile' ORDER BY id DESC LIMIT 1"
    )[0]
    assert int(ultimo_forzato["n_righe"]) == LUOGHI + 1, "--forza non ha reinviato"
    assert '"forzato": true' in ultimo_forzato["dettaglio"], (
        f"il registro non dichiara l'invio forzato: {ultimo_forzato['dettaglio']}"
    )


@pytest.mark.live
def test_messaggi_rispettano_v6(db_vivo, ciclo_pulito):
    """Nessun messaggio assegna compiti, e i quattro campi V6 ci sono sempre."""
    mese = ciclo_mensile._mese_corrente(None)
    messaggi_, _, _ = ciclo_mensile.messaggi(mese)

    assert len(messaggi_) == LUOGHI + 1
    for messaggio in messaggi_:
        corpo = messaggio.corpo()
        assert v6_ok(corpo), f"V6 violato in «{messaggio.oggetto}»: {messaggio.verifica()}"
        assert v6_ok(messaggio.oggetto)
        for campo in ("cosa_osservato", "evidenza", "cosa_si_potrebbe_fare", "chi_decide"):
            assert messaggio.campi.get(campo), f"{campo} mancante in «{messaggio.oggetto}»"
        # §12: nessun dato personale nei digest.
        for vietato in ("@example.org", "cittadino", "telefono", "codice fiscale"):
            assert vietato.lower() not in corpo.lower(), f"{vietato!r} nel digest"


def test_mese_malformato_errore_parlante():
    """`--mese` sbagliato dà un errore leggibile, non uno stack."""
    esito = _esegui("--mese", "settembre")
    assert esito.returncode != 0
    assert "YYYY-MM" in esito.stderr, f"errore poco parlante: {esito.stderr!r}"


def test_orario_del_ciclo_prima_delle_0900():
    """La schedulazione del ciclo è **prima delle 09:00** (criterio B6-FLW-02).

    Si legge da `flussi/crontab` se c'è, altrimenti si dichiara che la schedulazione è di `ops/` —
    il test non inventa un orario che non è nel mio file.
    """
    crontab = (RADICE / "flussi" / "crontab").read_text(encoding="utf-8")
    righe = [r for r in crontab.splitlines()
             if re.match(r"^[0-9*]", r) and "ciclo_mensile" in r]
    if not righe:
        pytest.skip("il ciclo mensile è schedulato da ops/ (accordo con B6Ops), non da flussi/crontab")

    ora = int(righe[0].split()[1])
    assert ora < 9, f"il ciclo è schedulato alle {ora}:00 (deve essere < 09:00)"


# ----------------------------------------------------- persistenza report (US-4), finti trasporti

# La persistenza si prova **senza database**: finto il trasporto (`leggi`/`esegui_sql`), quello che
# resta da verificare è la *politica* — esiste già? non riscriverlo; non esiste? INSERT con stato
# implicito `bozza`; il run corrente con id usato; il run senza id ripiegato all'ultimo run del mese.
# Sono le regole che distinguono un ciclo che duplica da un ciclo che dichiara.
from datetime import date  # noqa: E402
from types import SimpleNamespace  # noqa: E402
import json as _json  # noqa: E402


def _digest_finto() -> list[dict]:
    return [
        {
            "casa_slug": "san-bao", "casa_nome": "San Bao", "richieste": "12",
            "senza_risposta": "2", "proposte_aperte": "3", "applicate": "1", "in_scadenza": "0",
        },
        {
            "casa_slug": "bozzano", "casa_nome": "Bozzano", "richieste": "0",
            "senza_risposta": "0", "proposte_aperte": "0", "applicate": "0", "in_scadenza": "1",
        },
    ]


class _TrasportoFinto:
    """Il trasporto contraffatto: risponde alle SELECT che `persisti_report` fa, registra gli INSERT."""

    def __init__(self, *, casa_esistenti: set[str] | None = None,
                 osservatorio_esistente: bool = False, run_precedenti: list[int] | None = None):
        self.casa_esistenti = casa_esistenti or set()
        self.osservatorio_esistente = osservatorio_esistente
        self.run_precedenti = run_precedenti or []
        self.sql_eseguiti: list[tuple[str, dict]] = []

    def leggi(self, query: str) -> list[dict]:
        if "FROM trasi.report r" in query:  # precondizione per-casa
            return [{"casa_slug": s} for s in sorted(self.casa_esistenti)]
        if "ambito = 'osservatorio' LIMIT 1" in query:  # precondizione osservatorio
            return [{"id": "41"}] if self.osservatorio_esistente else []
        if "FROM trasi.v_report_mensile" in query:
            return [{"categoria": "fiscale_isee", "esito": "risolta", "n_label": "<5"}]
        if "FROM trasi.v_report_confronto" in query and "n IS NULL" in query:
            return [{"n": "4"}]
        if "FROM trasi.v_report_confronto" in query:
            return [
                {"categoria": "fiscale_isee", "esito": "risolta", "n": "9", "n_label": "9",
                 "n_prec_label": "<5", "delta_pct": None},
            ]
        if "FROM trasi.proposta" in query:
            return [{"n": "3"}]
        if "FROM trasi.flusso_run" in query:
            return [{"id": str(i)} for i in self.run_precedenti]
        raise AssertionError(f"query inattesa nel finto trasporto: {query}")

    def esegui_sql(self, sql: str, *, variabili=None, stdin_extra: str = "") -> str:
        self.sql_eseguiti.append((sql, variabili or {}))
        return ""


def _installa_finto(monkeypatch: pytest.MonkeyPatch, finto: _TrasportoFinto) -> None:
    monkeypatch.setattr(ciclo_mensile, "leggi", finto.leggi)
    monkeypatch.setattr(ciclo_mensile, "esegui_sql", finto.esegui_sql)


def test_persisti_report_inserisce_case_e_osservatorio(monkeypatch):
    """Nessun report presente: 2 INSERT casa + 1 osservatorio, con i conteggi nel risultato."""
    finto = _TrasportoFinto(run_precedenti=[17])
    _installa_finto(monkeypatch, finto)
    run = SimpleNamespace(id=None, dettaglio={"mese": "2026-09-01"})

    esito = ciclo_mensile.persisti_report(date(2026, 9, 1), _digest_finto(), "casa,csv\n", run)

    assert esito == {"inseriti": 3, "gia_esistenti": 0}
    inserti = [sql for sql, _ in finto.sql_eseguiti if "INSERT INTO trasi.report" in sql]
    assert len(inserti) == 3
    # L'osservatorio porta il CSV in colonna e `casa_id` NULL per costruzione (db/026).
    osservatorio = [s for s in inserti if "'osservatorio'" in s]
    assert len(osservatorio) == 1 and "VALUES (NULL," in osservatorio[0]
    # Il legame col run che lo ha prodotto: risolto all'ultimo run non fallito del mese.
    assert ", 17\n" in osservatorio[0] or osservatorio[0].rstrip().endswith("17)")
    # Il contratto non prevede `stato` nella INSERT: entra col DEFAULT 'bozza'.
    assert all("'bozza'" not in s for s in inserti)


def test_persisti_report_non_riscrive_chi_esiste(monkeypatch):
    """Le righe già presenti (casa + osservatorio) NON vengono riscritte: esito e INSERT lo dicono."""
    finto = _TrasportoFinto(casa_esistenti={"san-bao"}, osservatorio_esistente=True,
                            run_precedenti=[17])
    _installa_finto(monkeypatch, finto)
    run = SimpleNamespace(id=None, dettaglio={"mese": "2026-09-01"})

    esito = ciclo_mensile.persisti_report(date(2026, 9, 1), _digest_finto(), "casa,csv\n", run)

    assert esito == {"inseriti": 1, "gia_esistenti": 2}
    inserti = [(sql, v) for sql, v in finto.sql_eseguiti if "INSERT INTO trasi.report" in sql]
    assert len(inserti) == 1, f"atteso 1 INSERT (solo bozzano), trovati: {inserti}"
    assert inserti[0][1].get("slug") == "bozzano", (
        f"l'unico INSERT deve essere della Casa non ancora persistita: {inserti}"
    )
    # Nessun UPDATE né ON CONFLICT: il report non si corregge (db/024) e il ciclo non lo simula.
    testo = "\n".join(sql for sql, _ in finto.sql_eseguiti)
    assert "UPDATE" not in testo and "ON CONFLICT" not in testo


def test_persisti_report_seconda_esecuzione_zero_inserimenti(monkeypatch):
    """Tutto già presente → 0 INSERT: è l'idempotenza che si legge, non che si spera."""
    finto = _TrasportoFinto(casa_esistenti={"san-bao", "bozzano"}, osservatorio_esistente=True)
    _installa_finto(monkeypatch, finto)

    esito = ciclo_mensile.persisti_report(date(2026, 9, 1), _digest_finto(), "casa,csv\n", None)

    assert esito == {"inseriti": 0, "gia_esistenti": 3}
    assert all("INSERT INTO trasi.report" not in sql for sql, _ in finto.sql_eseguiti)


def test_persisti_report_cella_k_anonima_trascritta_non_ricalcolata(monkeypatch):
    """I contenuti per casa portano `n_label` («<5») così come la vista lo dà: mai il numero grezzo."""
    finto = _TrasportoFinto(run_precedenti=[17])
    _installa_finto(monkeypatch, finto)
    run = SimpleNamespace(id=None, dettaglio={"mese": "2026-09-01"})

    ciclo_mensile.persisti_report(date(2026, 9, 1), _digest_finto(), "casa,csv\n", run)

    variabili_casa = [v for sql, v in finto.sql_eseguiti
                      if "INSERT INTO trasi.report" in sql and "'casa'" in sql]
    assert variabili_casa, "nessun INSERT per-casa registrato"
    for variabili in variabili_casa:
        contenuti = _json.loads(variabili["contenuti"])
        assert contenuti["per_categoria_esito"] == [
            {"categoria": "fiscale_isee", "esito": "risolta", "n": "<5"}
        ], f"la cella k-anonima non è stata trascritta: {contenuti}"

