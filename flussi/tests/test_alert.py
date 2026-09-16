"""Trasi — F6 Alert: il destinatario giusto, con i quattro campi V6, e nessun compito assegnato.

Il criterio B4-FLW-09: una proposta di **San Bao vecchia di 8 giorni** → **1 email a San Bao** con i
quattro campi, e **0 email a Bozzano**. La seconda metà è quella che distingue un recapito corretto da
un broadcast: un alert che va a tutte le Case è un alert che nessuno legge.

Con SMTP non configurato il flusso scrive su **file** (`flussi/evidenze/alert/`) e lo dichiara: è il
modo in cui questo test legge il contenuto reale dei messaggi senza un server di posta. Il test
verifica che la scelta sia dichiarata nel `flusso_run`, perché un cambio silenzioso di canale
(da SMTP a file) sarebbe la differenza fra un avviso consegnato e un avviso in una cartella.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

RADICE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RADICE / "flussi"))

import alert  # noqa: E402

CARTELLA = RADICE / "flussi" / "evidenze" / "alert"
EMAIL_SANBAO = "gestore.san-bao@trasi.local"
EMAIL_BOZZANO = "gestore.bozzano@trasi.local"
MARCA = "B4TEST: alert"


def _esegui(*, giorni: int | None = None) -> subprocess.CompletedProcess:
    argomenti = [sys.executable, str(RADICE / "flussi" / "alert.py")]
    if giorni is not None:
        argomenti += ["--giorni", str(giorni)]
    return subprocess.run(argomenti, capture_output=True, text=True, check=False)


def _crea_fixture() -> dict:
    """1 proposta di San Bao invecchiata a 8 giorni + 1 di Bozzano scaduta.

    L'invecchiamento di `proposto_ts` passa dall'amministratore, come in `flussi/fixtures/alert.sql`:
    il campo non è grantato in INSERT a nessun ruolo client — il tempo che passa non ha un percorso
    applicativo — quindi simulare il tempo richiede quel passo. È dichiarato, non nascosto.
    """
    import os
    from comune import COMPOSE, DB_DEFAULT, SERVIZIO_DB

    sql = f"""
\\set ON_ERROR_STOP on
DELETE FROM trasi.audit WHERE proposta_id IN
  (SELECT id FROM trasi.proposta WHERE motivazione LIKE '{MARCA}%');
DELETE FROM trasi.proposta WHERE motivazione LIKE '{MARCA}%';

SET ROLE rete;
SET search_path = trasi, public, pg_temp;
INSERT INTO trasi.proposta (origine, tipo, entita, casa_id, payload, motivazione)
SELECT 'manuale', 'modifica_scheda', 'scheda_servizio', c.id,
       jsonb_build_object('descrizione', 'aggiornata'), '{MARCA}: San Bao in attesa'
  FROM trasi.casa c WHERE c.slug = 'san-bao';
INSERT INTO trasi.proposta (origine, tipo, entita, casa_id, payload, motivazione, scade_il)
SELECT 'manuale', 'modifica_scheda', 'scheda_servizio', c.id,
       jsonb_build_object('descrizione', 'aggiornata'), '{MARCA}: Bozzano scaduta',
       current_date - 1
  FROM trasi.casa c WHERE c.slug = 'bozzano';
RESET ROLE;

-- Simulazione del tempo: 8 giorni di attesa per la proposta di San Bao.
SET ROLE trasi_owner;
UPDATE trasi.proposta SET proposto_ts = now() - interval '8 days'
 WHERE motivazione = '{MARCA}: San Bao in attesa';
RESET ROLE;

-- La scaduta si marca con la via della produzione (F9).
SET SESSION AUTHORIZATION automazioni;
SELECT trasi.scadi_proposte();
RESET SESSION AUTHORIZATION;

DO $$
DECLARE n int;
BEGIN
  SELECT count(*) INTO n FROM trasi.v_flusso_alert_proposte
   WHERE proposta_id IN (SELECT id FROM trasi.proposta WHERE motivazione LIKE '{MARCA}%');
  IF n < 2 THEN RAISE EXCEPTION 'fixture: attese >=2 proposte in alert, trovate %', n; END IF;
END $$;
"""
    comando = [
        "docker", "compose", "-f", str(COMPOSE), "exec", "-T", SERVIZIO_DB,
        "psql", "-U", "postgres", "-d", os.environ.get("TRASI_DB") or DB_DEFAULT,
        "-X", "-q", "-v", "ON_ERROR_STOP=1", "-f", "-",
    ]
    esito = subprocess.run(comando, input=sql, capture_output=True, text=True, check=False)
    if esito.returncode != 0:
        raise RuntimeError(f"fixture fallita: {esito.stderr.strip()[:600]}")
    return {"out": esito.stdout}


@pytest.fixture
def alert_pulito(pulizia, db_vivo):
    if not db_vivo:
        pytest.skip("database non raggiungibile: l'alert si compone su dati reali")
    pulizia(registro=True, proposte=True)
    if CARTELLA.exists():
        for percorso in CARTELLA.glob("*.eml"):
            percorso.unlink()
    yield
    pulizia(registro=True, proposte=True)


@pytest.mark.live
def test_proposta_vecchia_va_al_destinatario_giusto(db_vivo, psql, alert_pulito):
    """8 giorni a San Bao → 1 messaggio al **gestore di San Bao**; Bozzano non riceve nulla di San Bao."""
    _crea_fixture()

    esito = _esegui(giorni=7)
    assert esito.returncode == 0, f"alert.py è fallito:\n{esito.stdout}\n{esito.stderr}"

    messaggi = alert.messaggi_proposte(7)
    destinatari = {m.a for m in messaggi}
    assert EMAIL_SANBAO in destinatari, (
        f"il gestore di San Bao non riceve l'avviso: destinatari = {destinatari}"
    )

    # Il messaggio di San Bao riguarda **solo** le proprie proposte.
    san_bao = next(m for m in messaggi if m.a == EMAIL_SANBAO)
    corpo = san_bao.corpo()
    assert "San Bao" in corpo, f"il messaggio di San Bao non nomina la sua Casa:\n{corpo}"
    assert "Bozzano" not in corpo, (
        f"il messaggio di San Bao nomina Bozzano: il recapito non è per competenza\n{corpo}"
    )

    # La scaduta di Bozzano va a chi decide per Bozzano, non a San Bao.
    if EMAIL_BOZZANO in destinatari:
        bozzano = next(m for m in messaggi if m.a == EMAIL_BOZZANO)
        assert "San Bao" not in bozzano.corpo(), (
            "il gestore di Bozzano riceve notizie di San Bao: il recapito per competenza è rotto"
        )

    # I quattro campi V6 e il limite di righe.
    for messaggio in messaggi:
        for campo in ("cosa_osservato", "evidenza", "cosa_si_potrebbe_fare", "chi_decide"):
            assert messaggio.campi.get(campo), f"{campo} mancante in {messaggio.oggetto}"
        assert len(messaggio.corpo().splitlines()) <= alert.Messaggio.MAX_RIGHE
        assert not messaggio.verifica(), f"V6 violato: {messaggio.verifica()}"


@pytest.mark.live
def test_invio_su_file_dichiarato(db_vivo, psql, alert_pulito):
    """Senza SMTP l'invio va su file, e la scelta è **dichiarata** nel registro — non silenziosa."""
    _crea_fixture()
    esito = _esegui(giorni=7)
    assert esito.returncode == 0, f"alert.py è fallito:\n{esito.stderr}"

    registro = psql(
        "SELECT esito, n_righe, dettaglio FROM trasi.flusso_run "
        " WHERE nome = 'alert' ORDER BY id DESC LIMIT 1"
    )
    assert registro, "`alert.py` non ha scritto in `flusso_run`"
    dettaglio = json.loads(registro[0]["dettaglio"])
    assert dettaglio["modo"] in ("file", "smtp"), f"canale non dichiarato: {dettaglio}"
    assert dettaglio["giorni_attesa"] == 7

    if dettaglio["modo"] == "file":
        # I file esistono e il destinatario è nel nome: l'evidenza è ispezionabile a mano.
        file_scritti = sorted(CARTELLA.glob("*.eml"))
        assert file_scritti, "modo `file` dichiarato ma nessun file scritto"
        contenuto = " ".join(p.read_text(encoding="utf-8") for p in file_scritti)
        assert EMAIL_SANBAO in contenuto, "il messaggio al gestore di San Bao non è stato scritto"
        # V5: nessun dato personale nei messaggi.
        for vietato in ("@example.org", "340 99 88 776", "Anna", "Bianchi"):
            assert vietato not in contenuto, f"{vietato!r} compare in un messaggio di alert"


@pytest.mark.live
def test_nessun_avviso_per_proposte_recenti(db_vivo, psql, alert_pulito):
    """La soglia conta: con `--giorni 30` una proposta di 8 giorni **non** genera avviso.

    Senza questo caso, il test precedente sarebbe verde anche se il flusso mandasse tutto a tutti.
    """
    _crea_fixture()
    assert alert.messaggi_proposte(30) == [] or all(
        "in attesa da oltre 30" not in m.corpo() for m in alert.messaggi_proposte(30)
    ), "con soglia 30 giorni la proposta di 8 non deve entrare nell'avviso di attesa"


@pytest.mark.live
def test_coerenza_fonti_arriva_all_at(db_vivo, psql, alert_pulito):
    """L'alert di coerenza fonti va all'AT (`rete`), ed è composto dai quattro campi V6."""

    from comune import leggi

    righe = leggi(
        "SELECT voce, fonte_nome FROM trasi.v_flusso_coerenza_fonti LIMIT 1"
    )
    if not righe:
        pytest.skip("nessuna incoerenza di fonte nel database corrente")

    messaggi = alert.messaggi_coerenza()
    assert messaggi, "ci sono incoerenze ma nessun messaggio"
    for messaggio in messaggi:
        assert messaggio.a == "rete@trasi.local", (
            f"la coerenza delle fonti la governa il TI/AT: destinatario {messaggio.a}"
        )
        for campo in ("cosa_osservato", "evidenza", "cosa_si_potrebbe_fare", "chi_decide"):
            assert messaggio.campi.get(campo)
        assert not messaggio.verifica()
        assert len(messaggio.corpo().splitlines()) <= alert.Messaggio.MAX_RIGHE


def test_dry_run_non_invia_e_non_scrive_file(tmp_path, monkeypatch, db_vivo, alert_pulito):
    """`--dry-run` non invia: serve a vedere cosa partirebbe senza farlo partire."""
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    prima = set(CARTELLA.glob("*.eml")) if CARTELLA.exists() else set()
    esito = _esegui(giorni=7)
    # Il run vero scrive; il dry-run no. Si confronta il numero di file prima/dopo del dry-run.
    prima_dry = set(CARTELLA.glob("*.eml")) if CARTELLA.exists() else set()
    dry = subprocess.run(
        [sys.executable, str(RADICE / "flussi" / "alert.py"), "--dry-run", "--giorni", "7"],
        capture_output=True, text=True, check=False,
    )
    assert dry.returncode == 0, f"il dry-run è fallito:\n{dry.stderr}"
    dopo_dry = set(CARTELLA.glob("*.eml")) if CARTELLA.exists() else set()
    assert dopo_dry == prima_dry, "il dry-run ha scritto file: non deve inviare nulla"


# ------------------------------------------------------------------ deduplicazione (bug 2026-09-16)


def test_impronta_stabile_a_parita_di_contenuto() -> None:
    """Stessa situazione → stessa impronta: è la condizione che sopprime le ripetizioni.

    Un alert identico ogni mattina per la stessa proposta insegna a ignorare gli alert — e la coda
    resta ignorata, che è il rischio §13 più probabile di questo sistema.
    """
    import alert as a

    m1 = a.Messaggio(a="gestore.x@trasi.local", oggetto="Trasi · 1 in attesa",
                     righe=["proposta 12 · modifica_scheda · 8 giorni"])
    m2 = a.Messaggio(a="gestore.x@trasi.local", oggetto="Trasi · 1 in attesa",
                     righe=["proposta 12 · modifica_scheda · 8 giorni"])
    assert a._impronta(m1) == a._impronta(m2)


def test_impronta_cambia_se_cambia_la_situazione() -> None:
    """Una voce in più (o in meno) → impronta diversa → l'avviso riparte.

    È il caso che conta: la soppressione NON deve nascondere un cambiamento reale, altrimenti
    un avviso importante si perderebbe per non ripetersi.
    """
    import alert as a

    base = dict(a="gestore.x@trasi.local", oggetto="Trasi · 1 in attesa",
                righe=["proposta 12 · modifica_scheda · 8 giorni"])
    m1 = a.Messaggio(**base)
    m2 = a.Messaggio(a="gestore.x@trasi.local", oggetto="Trasi · 2 in attesa",
                     righe=["proposta 12 · modifica_scheda · 8 giorni",
                            "proposta 15 · nuova_scheda · 10 giorni"])
    assert a._impronta(m1) != a._impronta(m2)


def test_impronta_distingue_i_destinatari() -> None:
    """La stessa osservazione a due destinatari diversi sono due avvisi distinti."""
    import alert as a

    righe = ["proposta 12 · modifica_scheda · 8 giorni"]
    m1 = a.Messaggio(a="gestore.a@trasi.local", oggetto="Trasi · 1 in attesa", righe=righe)
    m2 = a.Messaggio(a="gestore.b@trasi.local", oggetto="Trasi · 1 in attesa", righe=righe)
    assert a._impronta(m1) != a._impronta(m2)


# -------------------------------------------------------- eventi: dati mancanti o datati (V6)


def test_riga_evento_incompleto_tono_v6() -> None:
    """Il testo del caso `incompleto`: dichiara lo stato e chi decide — mai un imperativo.

    È il contratto del nuovo check, e va provato **senza** database: la proprietà da difendere è del
    template, e un template non deve dipendere dai dati per essere misurato. La frase è quella del
    contract: «La scheda di <titolo> è incompleta: manca <mancanze>. Decide la CdQ <slug> se e quando
    aggiornarla.» — `verifica_v6` deve lasciarla passare (il soggetto è chi decide, il verbo è al
    presente indicativo), e il test fallisce se il template la cambiasse.
    """
    riga = alert._riga_evento({
        "motivo": "incompleto",
        "titolo": "Cineforum d'estate",
        "mancanze": "{descrizione,luogo_testo}",
        "casa_slug": "san-bao",
    })
    assert riga == (
        "  · La scheda di Cineforum d'estate è incompleta: manca descrizione, luogo_testo. "
        "Decide la CdQ san-bao se e quando aggiornarla."
    ), f"il testo del caso incompleto è cambiato:\n{riga}"
    assert not alert.verifica_v6(riga), f"il caso incompleto contiene un imperativo: {alert.verifica_v6(riga)}"


def test_riga_evento_datato_tono_v6() -> None:
    """Il testo del caso `datato`: «…risulta aggiornata più di 2 mesi fa. Decide la CdQ <slug> se
    verificarla.» — niente «verifica», niente «aggiorna»: chi decide è la CdQ, il sistema segnala."""
    riga = alert._riga_evento({
        "motivo": "datato",
        "titolo": "Cineforum d'estate",
        "mancanze": "{}",
        "casa_slug": "bozzano",
    })
    assert riga == (
        "  · La scheda di Cineforum d'estate risulta aggiornata più di 2 mesi fa. "
        "Decide la CdQ bozzano se verificarla."
    ), f"il testo del caso datato è cambiato:\n{riga}"
    assert not alert.verifica_v6(riga), f"il caso datato contiene un imperativo: {alert.verifica_v6(riga)}"


def test_mancanze_elenco_nomi_campi() -> None:
    """Le mancanze arrivano come array Postgres testuale: escono come elenco leggibile di nomi."""
    assert alert._mancanze_elenco("{descrizione,luogo_testo}") == "descrizione, luogo_testo"
    assert alert._mancanze_elenco("{url}") == "url"
    # Un array vuoto (caso limite della vista) non deve rompere la frase.
    assert alert._mancanze_elenco("{}") == "informazioni"


@pytest.mark.live
def test_messaggi_eventi_dati_mancanti_rispettano_v6(db_vivo, pulizia):
    """Il check compone messaggi reali dalla vista: tono V6, quattro campi, destinatario risolto.

    Se la vista `trasi.v_eventi_dati_mancanti` non è ancora stata creata (merge DBA in corso) il test
    si salta dichiarandolo: la vista è l'interfaccia di dominio del check, e senza di essa non c'è
    nulla da misurare — il coordinatore la verifica nell'integrazione.
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile: i messaggi si compongono su dati reali")

    from comune import leggi

    try:
        leggi("SELECT evento_id FROM trasi.v_eventi_dati_mancanti LIMIT 1")
    except Exception:
        pytest.skip("trasi.v_eventi_dati_mancanti non presente: in attesa del merge DBA (db/004)")

    messaggi = alert.messaggi_eventi_dati_mancanti()
    if not messaggi:
        pytest.skip("nessun evento con dati mancanti o datati nel database corrente")

    for messaggio in messaggi:
        corpo = messaggio.corpo()
        assert messaggio.a, "destinatario mancante"
        assert not messaggio.verifica(), f"V6 violato: {messaggio.verifica()}"
        for campo in ("cosa_osservato", "evidenza", "cosa_si_potrebbe_fare", "chi_decide"):
            assert messaggio.campi.get(campo), f"campo V6 mancante: {campo}"
        assert len(corpo.splitlines()) <= alert.Messaggio.MAX_RIGHE
        # «Decide la CdQ …» deve comparire in ogni riga di dettaglio: è la firma del check.
        for riga in messaggio.righe:
            assert "Decide la CdQ" in riga, f"riga senza il soggetto che decide:\n{riga}"
