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


# ------------------------------------------- notifica report osservatorio alla PA (US-4), offline

# Il passo si prova **senza database**: finte le letture (`v_report_da_notificare`, parametro) e la
# marcatura, resta da verificare la *politica* — nessun report in vista → nessun messaggio; un report
# → un messaggio V6 con l'id che la marcatura richiede; la marcatura scatta **una sola volta** per
# report e **solo** a invio riuscito. Sono le regole per cui un report non viene rinotificato ogni
# mattina, e quelle per cui un invio fallito non perde la notifica.


class _TrasportoAlertFinto:
    """Trasporto contraffatto per il passo «report PA»: SELECT di vista/parametro e marcatura."""

    def __init__(self, *, da_notificare: list[dict], recapito: str = "pa@ente.example"):
        self.da_notificare = da_notificare
        self.recapito = recapito
        self.marcate: list[str] = []

    def leggi(self, query: str) -> list[dict]:
        if "FROM trasi.v_report_da_notificare" in query:
            return list(self.da_notificare)
        if "p_text('email_report_pa')" in query:
            return [{"v": self.recapito}] if self.recapito else []
        if "p_int(" in query:
            return []  # parametro assente → il default dichiarato dal flusso (db/003: NULL)
        raise AssertionError(f"query inattesa nel finto trasporto: {query}")

    def esegui_sql(self, sql: str, *, variabili=None, stdin_extra: str = "") -> str:
        if "marca_report_inviato" in sql:
            self.marcate.append(sql)
            return ""
        raise AssertionError(f"SQL inatteso nel finto trasporto: {sql}")


def _installa_finto_alert(monkeypatch: pytest.MonkeyPatch, finto: _TrasportoAlertFinto) -> None:
    monkeypatch.setattr(alert, "leggi", finto.leggi)
    monkeypatch.setattr(alert, "esegui_sql", finto.esegui_sql)
    # `_recapito_pa` importa `uno` in ritardo dal modulo: si finta anche quello.
    import comune as _comune

    monkeypatch.setattr(_comune, "leggi", finto.leggi)


def test_report_pa_vista_vuota_nessun_messaggio(monkeypatch):
    """`v_report_da_notificare` vuota → zero messaggi: un avviso che non c'è non si inventa.

    Ed è il caso in cui la marcatura **non deve** avvenire affatto: niente da segnalare, niente da
    segnare.
    """
    finto = _TrasportoAlertFinto(da_notificare=[])
    _installa_finto_alert(monkeypatch, finto)

    assert alert.messaggi_report_pa() == []
    assert finto.marcate == []


def test_report_pa_vista_piena_messaggio_v6_con_id(monkeypatch):
    """Un report approvato in vista → un messaggio con i 4 campi V6, l'id per la marcatura e il mese."""
    finto = _TrasportoAlertFinto(
        da_notificare=[{"id": "41", "mese": "2026-09-01", "approvato_ts": "2026-09-04 09:12:00+00"}]
    )
    _installa_finto_alert(monkeypatch, finto)

    messaggi = alert.messaggi_report_pa()
    assert len(messaggi) == 1
    messaggio = messaggi[0]
    assert messaggio.report_id == 41, "l'id del report serve a marca_report_inviato"
    assert messaggio.a == "pa@ente.example"
    assert "2026-09" in messaggio.oggetto
    assert "dashboard PA" in messaggio.oggetto
    corpo = messaggio.corpo()
    for campo in ("cosa_osservato", "evidenza", "cosa_si_potrebbe_fare", "chi_decide"):
        assert messaggio.campi.get(campo), f"campo V6 mancante: {campo}"
    assert not alert.verifica_v6(messaggio.oggetto + "\n" + corpo), (
        f"la notifica PA viola V6: {alert.verifica_v6(messaggio.oggetto + corpo)}"
    )
    # V5: nessun testo di chat né dato cittadino — il messaggio porta mese e stato, nient'altro.
    for vietato in ("richiesta", "cittadino", "ATTENDEE"):
        assert vietato not in corpo, f"{vietato!r} nella notifica PA"


def test_report_pa_parametro_vuoto_resta_leggibile_file(monkeypatch):
    """Recapito vuoto → il messaggio esiste con destinatario vuoto: il ramo d'invio lo porta su file.

    La scelta della modalità è dichiarata nel `flusso_run` («file: parametro email_report_pa vuoto»),
    non nascosta: un report approvato con recapito non configurato non può restare invisibile.
    """
    finto = _TrasportoAlertFinto(
        da_notificare=[{"id": "7", "mese": "2026-08-01", "approvato_ts": "2026-08-05 10:00:00+00"}],
        recapito="",
    )
    _installa_finto_alert(monkeypatch, finto)

    messaggi = alert.messaggi_report_pa()
    assert len(messaggi) == 1
    assert messaggi[0].a == ""


def test_marca_inviato_una_sola_volta_e_solo_dopo_l_invio(monkeypatch, tmp_path):
    """`marca_report_inviato` scatta **una volta per report** e **solo** a invio riuscito.

    Il marcatore di stato è ciò che fa sparire il report dalla vista: doppio → report già marcato
    rinotificato; nessuno → notifica ripetuta ogni mattina. Il ramo d'invio del flusso lo chiama nel
    ramo `else` del try/except: un invio fallito (SMTP giù) **non** marca, così il report torna in
    vista alla prossima esecuzione.
    """
    from unittest.mock import patch

    finto = _TrasportoAlertFinto(
        da_notificare=[
            {"id": str(i), "mese": "2026-09-01", "approvato_ts": "2026-09-04 09:00:00+00"}
            for i in (11, 12, 13)
        ]
    )
    _installa_finto_alert(monkeypatch, finto)
    monkeypatch.setattr(alert, "CARTELLA_ALERT", tmp_path)

    # Il ciclo completo degli altri avvisi è fuori perimetro qui: si prova **questo** passo.
    monkeypatch.setattr(alert, "messaggi_proposte", lambda gg: [])
    monkeypatch.setattr(alert, "messaggi_coerenza", lambda: [])
    monkeypatch.setattr(alert, "messaggi_eventi_dati_mancanti", lambda: [])
    monkeypatch.setattr(alert, "_ultime_impronte", lambda: {})
    monkeypatch.setattr(alert, "_config_smtp", lambda: None)  # niente SMTP → invio su file
    monkeypatch.setattr(alert, "registra_run", lambda run: None)

    esito = alert.esegui(dry_run=False)
    assert esito == 0
    assert len(finto.marcate) == 3, f"attese 3 marcature (una per report): {finto.marcate}"
    for atteso, chiamata in zip((11, 12, 13), finto.marcate):
        assert f"marca_report_inviato({atteso})" in chiamata

    # Il messaggio è uscito davvero, in modalità file dichiarata. Il nome del file porta
    # timestamp+destinatario: tre notifiche con lo stesso destinatario nel medesimo secondo
    # condividono un solo file (scelta preesistente di `invia_file`), quindi si verifica il
    # contenuto e non il conteggio.
    file_scritti = list(tmp_path.glob("*.eml"))
    assert file_scritti, "la notifica su file non è stata scritta"
    contenuto = " ".join(p.read_text(encoding="utf-8") for p in file_scritti)
    assert "dashboard PA" in contenuto


def test_marca_non_chiamata_se_invio_fallisce(monkeypatch):
    """Invio SMTP che esplode → niente marcatura: il report torna in vista e la notifica riparte."""
    from unittest.mock import patch  # noqa: F401

    finto = _TrasportoAlertFinto(
        da_notificare=[{"id": "21", "mese": "2026-09-01", "approvato_ts": "2026-09-04 09:00:00+00"}]
    )
    _installa_finto_alert(monkeypatch, finto)
    monkeypatch.setattr(alert, "messaggi_proposte", lambda gg: [])
    monkeypatch.setattr(alert, "messaggi_coerenza", lambda: [])
    monkeypatch.setattr(alert, "messaggi_eventi_dati_mancanti", lambda: [])
    monkeypatch.setattr(alert, "_ultime_impronte", lambda: {})
    monkeypatch.setattr(alert, "registra_run", lambda run: None)

    def _smtp_che_fallisce(messaggio, mittente, config):
        raise alert.AlertErrore("connessione rifiutata")

    monkeypatch.setattr(alert, "_config_smtp", lambda: ("smtp.example", 25, "", ""))
    monkeypatch.setattr(alert, "invia_smtp", _smtp_che_fallisce)

    esito = alert.esegui(dry_run=False)
    assert esito == 1, "un invio fallito deve dare esito parziale (exit 1)"
    assert finto.marcate == [], "la marcatura non deve avvenire se l'invio non c'è stato"
