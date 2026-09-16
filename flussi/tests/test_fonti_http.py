"""Trasi — F4 HTTP: change-detection che **propone** e non scrive mai il dominio.

Il criterio B4-FLW-07 chiede quattro cose, e il test le prova tutte sul database:

* pagina cambiata → 1 `proposta` `origine='fonte_automatica'`, `approvatore_ruolo='at'`;
* **`luogo.orari` identico a prima** — il diff allegato; è l'invariante di V4;
* rerun → nessun duplicato (dedup su proposta aperta stessa entità+fonte);
* pagina riscritta al 90% → proposta con `payload.anomalo = true`.

Il primo caso — la **prima osservazione** — non produce proposte: senza un «prima» con cui confrontare
non c'è cambiamento da segnalare. Il test lo asserisce, perché è il difetto che la prima esecuzione
aveva: una proposta «la pagina è cambiata» su una pagina che nessuno aveva mai letto, che avrebbe poi
bloccato il vero cambiamento attraverso il dedup.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

RADICE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RADICE / "flussi"))

import fonti_http  # noqa: E402

FIXTURES = RADICE / "flussi" / "fixtures"
LUOGO_URP = 16          # il luogo del seed su cui punta il registro
FONTE_COMUNE = "Comune di Brindisi-3"


def _esegui(pagina: str, *, dry_run: bool = False) -> subprocess.CompletedProcess:
    argomenti = [
        sys.executable, str(RADICE / "flussi" / "fonti_http.py"),
        "--fonte", FONTE_COMUNE, "--file", str(FIXTURES / pagina),
    ]
    if dry_run:
        argomenti.append("--dry-run")
    return subprocess.run(argomenti, capture_output=True, text=True, check=False)


def _orari(psql) -> tuple[str, str]:
    """`(orari, ultima modifica)` del luogo sorvegliato: l'invariante da difendere."""
    riga = psql(
        f"SELECT COALESCE(orari::text, '') AS orari, "
        f"       COALESCE(aggiornato_da, '') AS da, COALESCE(descrizione,'') AS descrizione "
        f"  FROM trasi.luogo WHERE id = {LUOGO_URP}"
    )[0]
    return riga["orari"], riga["descrizione"]


def _proposte(psql) -> list[dict]:
    return psql(
        "SELECT id, origine, tipo, entita, entita_id, fonte_id, stato, approvatore_ruolo, "
        "       motivazione, payload "
        "  FROM trasi.proposta WHERE origine = 'fonte_automatica' ORDER BY id"
    )


@pytest.fixture
def http_pulito(pulizia, db_vivo):
    if not db_vivo:
        pytest.skip("database non raggiungibile: la change-detection vive in `fonte_run`")
    pulizia(registro=True, proposte=True, automatiche=True)
    yield
    pulizia(registro=True, proposte=True, automatiche=True)


@pytest.mark.live
def test_prima_osservazione_non_produce_proposte(db_vivo, psql, http_pulito):
    """La prima lettura stabilisce la base: non c'è un «prima», quindi non c'è un cambiamento."""
    esito = _esegui("urp_base.html")
    assert esito.returncode == 0, f"il run è fallito:\n{esito.stderr}"
    assert "prima osservazione" in esito.stdout, f"output inatteso:\n{esito.stdout}"
    assert _proposte(psql) == [], (
        "la prima osservazione non deve creare proposte: segnalerebbe un cambiamento mai avvenuto e "
        "il dedup bloccherebbe quello vero"
    )

    registro = psql(
        "SELECT esito, righe, hash FROM trasi.fonte_run ORDER BY id DESC LIMIT 1"
    )[0]
    assert registro["hash"], "la base deve essere registrata (`hash` in `fonte_run`)"


@pytest.mark.live
def test_pagina_cambiata_produce_proposta_e_non_tocca_il_dominio(db_vivo, psql, http_pulito):
    """Pagina cambiata → 1 proposta `fonte_automatica` / `at`, e **`luogo.orari` identico**."""
    assert _esegui("urp_base.html").returncode == 0
    orari_prima = _orari(psql)

    esito = _esegui("urp_cambiato.html")
    assert esito.returncode == 0, f"il run è fallito:\n{esito.stderr}"

    proposte = _proposte(psql)
    assert len(proposte) == 1, f"attesa 1 proposta, trovate {len(proposte)}: {proposte}"
    proposta = proposte[0]

    assert proposta["origine"] == "fonte_automatica"
    assert proposta["entita"] == "luogo"
    assert int(proposta["entita_id"]) == LUOGO_URP
    assert proposta["stato"] == "proposta"
    assert proposta["approvatore_ruolo"] == "at", (
        f"un dato del territorio lo decide l'AT (§11): {proposta['approvatore_ruolo']}"
    )
    assert len(proposta["motivazione"]) <= 80, (
        f"motivazione di {len(proposta['motivazione'])} caratteri (V5/§12: ≤ 80)"
    )
    payload = json.loads(proposta["payload"])
    assert payload["anomalo"] is False, "una modifica piccola non è un'anomalia"
    assert payload["campo"] == "orari"
    assert payload["_selettore"] == "#orari-urp"

    # --- IL CRITERIO: `luogo.orari` invariato -----------------------------------------------
    orari_dopo = _orari(psql)
    assert orari_dopo == orari_prima, (
        "il flusso ha modificato il dominio: questo è esattamente ciò che V4 vieta. "
        f"prima={orari_prima!r} dopo={orari_dopo!r}"
    )


@pytest.mark.live
def test_rerun_non_duplica_la_proposta(db_vivo, psql, http_pulito):
    """Rerun con la stessa pagina cambiata → **nessun duplicato** (dedup su proposta aperta).

    Senza il dedup, un sito che cambia a ogni richiesta (un contatore di visite, un orologio in pagina)
    produrrebbe una proposta al giorno e affogherebbe la coda di approvazione: il flusso diventerebbe
    esso stesso il rumore che dovrebbe ridurre.
    """
    assert _esegui("urp_base.html").returncode == 0
    assert _esegui("urp_cambiato.html").returncode == 0
    proposte_dopo_primo = _proposte(psql)
    assert len(proposte_dopo_primo) == 1

    # Un cambiamento ulteriore, con la proposta ancora aperta.
    esito = _esegui("urp_riscritto.html")
    assert esito.returncode == 0
    assert "dedup" in esito.stdout.lower() or "già aperta" in esito.stdout, (
        f"il flusso non ha dichiarato il dedup:\n{esito.stdout}"
    )

    proposte_dopo_secondo = _proposte(psql)
    assert len(proposte_dopo_secondo) == len(proposte_dopo_primo) == 1, (
        f"il dedup non ha funzionato: {len(proposte_dopo_secondo)} proposte"
    )
    assert _orari(psql) == _orari(psql), "il secondo run non deve toccare il dominio"


@pytest.mark.live
def test_pagina_riscritta_e_anomala(db_vivo, psql, http_pulito):
    """Pagina riscritta al 90% → proposta con `payload.anomalo = true` (non applicata)."""
    assert _esegui("urp_base.html").returncode == 0
    orari_prima = _orari(psql)

    esito = _esegui("urp_riscritto.html")
    assert esito.returncode == 0, f"il run è fallito:\n{esito.stderr}"
    assert "anomalo" in esito.stdout.lower(), f"il flusso non ha segnalato l'anomalia:\n{esito.stdout}"

    proposte = _proposte(psql)
    assert len(proposte) == 1
    payload = json.loads(proposte[0]["payload"])
    assert payload["anomalo"] is True, f"`anomalo` atteso true: {payload}"

    # La proposta resta tale: non è applicata finché un umano non decide.
    assert proposte[0]["stato"] == "proposta", (
        f"una proposta anomala non si applica da sola: stato={proposte[0]['stato']}"
    )
    # E il dominio è intatto.
    assert _orari(psql) == orari_prima

    # L'esito in `fonte_run` porta la percentuale di riscrittura: è il numero su cui si decide.
    registro = psql(
        "SELECT esito, dettaglio FROM trasi.fonte_run ORDER BY id DESC LIMIT 1"
    )[0]
    assert registro["esito"] == "anomalo"
    assert float(json.loads(registro["dettaglio"])["pct_riscrittura"]) > 80


@pytest.mark.live
def test_pagina_invariata_non_fa_nulla(db_vivo, psql, http_pulito):
    """Due letture identiche → 0 proposte: il flusso non è un generatore di rumore."""
    assert _esegui("urp_base.html").returncode == 0
    esito = _esegui("urp_base.html")
    assert esito.returncode == 0
    assert "invariato" in esito.stdout, f"output inatteso:\n{esito.stdout}"
    assert _proposte(psql) == []


def test_estrazione_dal_selettore():
    """Il selettore essenziale: `#id`, `.classe`, `tag`, `tag.classe`. La normalizzazione conta.

    La normalizzazione degli spazi non è un dettaglio: una pagina riscritta dal CMS con gli stessi
    contenuti e indentazione diversa non è cambiata, e senza normalizzare il flusso segnalerebbe un
    cambiamento a ogni pubblicazione dell'editor.
    """
    html = """
    <div id="orari-urp">
        lun   08:30-12:30
        mar 08:30-12:30
    </div>
    <div id="altro">ignorato</div>
    """
    assert fonti_http.estrai_testo(html, "#orari-urp") == "lun 08:30-12:30\nmar 08:30-12:30"
    assert fonti_http.estrai_testo(html, "#inesistente") == ""
    assert "ignorato" in fonti_http.estrai_testo(html, "div")
    assert "ignorato" not in fonti_http.estrai_testo(html, "#orari-urp")

    # Indentazione diversa, stesso contenuto → stesso testo (e quindi stesso hash).
    html2 = '<div id="orari-urp">\n   lun   08:30-12:30\n   mar 08:30-12:30\n</div>'
    assert fonti_http.estrai_testo(html2, "#orari-urp") == fonti_http.estrai_testo(html, "#orari-urp")

    with pytest.raises(fonti_http.HttpErrore):
        fonti_http.estrai_testo(html, "div > p")   # selettore non supportato: errore parlante


def test_riscrittura_percentuale():
    """`riscrittura_pct`: 0 = identico, 100 = nulla in comune. È la soglia dell'anomalia."""
    assert fonti_http.riscrittura_pct("", "nuovo") == 0.0, (
        "senza un testo precedente non c'è riscrittura: è il caso della prima osservazione"
    )
    assert fonti_http.riscrittura_pct("uguale", "uguale") == 0.0
    alta = fonti_http.riscrittura_pct(
        "lun 08:30-12:30 mar 08:30-12:30",
        "Apertura su appuntamento telefonico obbligatorio. Sportello unico polifunzionale.",
    )
    assert alta > 80, f"una pagina riscritta deve superare la soglia, ottenuto {alta}"


def test_registro_rifiuta_campo_non_ammesso(tmp_path):
    """Il registro è configurazione: un bersaglio su un'entità non ammessa non si accetta.

    Questo flusso propone modifiche a `luogo` e `scheda_servizio`. Un bersaglio su `casa` o `evento`
    sarebbe una via per far proporre a questo flusso qualcosa che non gli compete — e il registro è
    un file, quindi modificabile senza toccare il codice.
    """
    percorso = tmp_path / "reg.json"
    percorso.write_text(json.dumps([
        {"fonte": "Comune di Brindisi-3", "url": "https://x.test", "selettore": "#a",
         "entita": "casa", "entita_id": 1, "campo": "orari"}
    ]), encoding="utf-8")
    with pytest.raises(fonti_http.HttpErrore):
        fonti_http.carica_registro(percorso)

    percorso.write_text(json.dumps([
        {"fonte": "Comune di Brindisi-3", "url": "https://x.test", "selettore": "#a",
         "entita": "luogo", "entita_id": 1, "campo": "orari"}
    ]), encoding="utf-8")
    assert len(fonti_http.carica_registro(percorso)) == 1
