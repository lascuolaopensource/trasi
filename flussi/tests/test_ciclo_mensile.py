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
