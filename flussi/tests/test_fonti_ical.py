"""Trasi — F4 iCal: **l'unica scrittura diretta al dominio**, e i suoi tre casi.

I tre casi del criterio B4-FLW-06, ciascuno con la prova che conta:

1. **feed cambiato** → 1 `UPDATE` su `evento` + **1 riga `audit` `ical_upsert` con `prima`≠`dopo`**;
2. **rerun identico** → 0 scritture, e — decisivo — **0 righe di audit nuove**: è la differenza fra
   «l'upsert non fa danno» e «l'upsert non ha fatto nulla»;
3. **80% degli eventi rimosso** → **0 upsert**, 1 `proposta` `origine='coerenza'`,
   `fonte_run.esito='anomalo'`, e `annullato` non tocca nulla.

Più il presidio V5: un feed che porta `ATTENDEE`, `ORGANIZER` e `DESCRIPTION` non fa entrare quei
contenuti in memoria. Il test guarda la riga **nel database** — non il codice — perché è ciò che
conta: se un domani qualcuno aggiungesse `descrizione` all'INSERT, la riga lo direbbe.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

RADICE = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RADICE / "flussi"))

import fonti_ical  # noqa: E402

FIXTURE_ICS = RADICE / "flussi" / "fixtures" / "casa.ics"


def _esegui(percorso_ics: Path, *, casa: str = "bozzano") -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(RADICE / "flussi" / "fonti_ical.py"),
         "--ics", str(percorso_ics), "--casa", casa],
        capture_output=True, text=True, check=False,
    )


def _eventi(psql) -> dict[str, dict]:
    """Gli eventi iCal di Bozzano, per uid. Solo quelli della fonte iCal (fonte_id=3)."""
    righe = psql(
        "SELECT id, uid_ical, titolo, "
        "       to_char(inizio, 'YYYY-MM-DD\"T\"HH24:MI:SS') AS inizio, "
        "       annullato, descrizione "
        "  FROM trasi.evento "
        " WHERE fonte_id = (SELECT id FROM trasi.fonte WHERE nome = 'Google Calendar-ical-2') "
        "   AND uid_ical LIKE 'b4test-%'"
    )
    return {
        r["uid_ical"]: {
            "id": int(r["id"]), "titolo": r["titolo"], "inizio": r["inizio"],
            "annullato": r["annullato"] == "t", "descrizione": r["descrizione"],
        }
        for r in righe
    }


def _audit_ical(psql) -> list[dict]:
    return psql(
        "SELECT a.id, a.azione, a.eseguito_da, a.entita, a.entita_id, a.prima, a.dopo "
        "  FROM trasi.audit a "
        " WHERE a.azione = 'ical_upsert' "
        "   AND a.dopo->>'uid_ical' LIKE 'b4test-%' ORDER BY a.id"
    )


@pytest.fixture
def ical_pulito(pulizia, db_vivo):
    if not db_vivo:
        pytest.skip("database non raggiungibile: l'upsert iCal vive nel database")
    pulizia(registro=True, eventi=True, proposte=True)
    yield
    pulizia(registro=True, eventi=True, proposte=True)


@pytest.mark.live
def test_case_1_feed_cambiato_una_variazione_un_audit(db_vivo, psql, fixture_ics, ical_pulito):
    """Un orario cambiato → 1 `UPDATE` su `evento` e 1 riga `audit` con `prima`≠`dopo`."""
    base = fixture_ics(titolo_evento="Evento", orario="100000", n_eventi=5)
    assert _esegui(base).returncode == 0, "il primo import è fallito"

    eventi = _eventi(psql)
    assert len(eventi) == 5, f"attesi 5 eventi dal feed, trovati {len(eventi)}"
    assert len(_audit_ical(psql)) == 5, "ogni nuovo evento deve avere la sua riga `ical_upsert`"

    # L'orario cambia: lo stesso feed, un evento con `DTSTART` diverso.
    cambiato = fixture_ics(titolo_evento="Evento", orario="150000", n_eventi=5)
    esito = _esegui(cambiato)
    assert esito.returncode == 0, f"il secondo run è fallito:\n{esito.stderr}"

    dopo = _eventi(psql)
    assert len(dopo) == 5, "il cambio di orario non deve creare righe nuove"

    assert dopo["b4test-evento-0@trasi.test"]["inizio"].endswith("15:00:00"), (
        f"l'orario non è stato aggiornato: {dopo['b4test-evento-0@trasi.test']['inizio']}"
    )

    audit = _audit_ical(psql)
    assert len(audit) == 6, f"attese 5 + 1 righe di audit, trovate {len(audit)}"
    ultima = audit[-1]
    assert ultima["azione"] == "ical_upsert"
    assert ultima["eseguito_da"] == "automazioni", (
        f"la riga deve portare `automazioni`, non {ultima['eseguito_da']}: è il segno che la "
        "connessione è nel ruolo giusto (con `SET ROLE` `session_user` resterebbe l'amministratore "
        "e questa riga non esisterebbe)"
    )
    assert ultima["prima"] and ultima["dopo"], "`prima`/`dopo` sono il contenuto dell'audit"
    assert ultima["prima"] != ultima["dopo"], (
        "una riga `ical_upsert` con `prima` = `dopo` registrerebbe una non-variazione"
    )
    assert "10:00" in ultima["prima"] and "15:00" in ultima["dopo"], (
        f"il diff non racconta il cambio di orario: prima={ultima['prima'][:120]}"
    )


@pytest.mark.live
def test_case_2_rerun_identico_zero_scritture(db_vivo, psql, fixture_ics, ical_pulito):
    """Rerun identico → 0 scritture e **0 righe di audit nuove**. È l'idempotenza vera."""
    feed = fixture_ics(titolo_evento="Evento", orario="100000", n_eventi=5)
    assert _esegui(feed).returncode == 0

    eventi_prima = _eventi(psql)
    audit_prima = _audit_ical(psql)

    esito = _esegui(feed)
    assert esito.returncode == 0, f"il rerun è fallito:\n{esito.stderr}"

    assert _eventi(psql) == eventi_prima, "il rerun ha modificato gli eventi"
    assert _audit_ical(psql) == audit_prima, (
        "il rerun ha scritto righe di audit: un evento già identico non deve essere riscritto "
        "(l'upsert usa `DO UPDATE … WHERE <cambiato>` proprio per questo)"
    )

    registro = psql(
        "SELECT esito, n_righe FROM trasi.flusso_run WHERE nome = 'fonti_ical' ORDER BY id DESC LIMIT 1"
    )[0]
    assert registro["esito"] == "ok"
    assert int(registro["n_righe"]) == 0, f"il rerun dichiara {registro['n_righe']} righe"


@pytest.mark.live
def test_case_3_ottanta_percento_rimosso_e_anomalo(db_vivo, psql, fixture_ics, ical_pulito):
    """80% degli eventi rimosso → **0 upsert**, 1 proposta `coerenza`, `fonte_run.esito='anomalo'`."""
    feed = fixture_ics(titolo_evento="Evento", orario="100000", n_eventi=5)
    assert _esegui(feed).returncode == 0

    eventi_prima = _eventi(psql)
    audit_prima = len(_audit_ical(psql))

    # Un feed con 1 evento su 5: l'80% rimosso.
    ridotto = fixture_ics(titolo_evento="Evento", orario="100000", n_eventi=1)
    esito = _esegui(ridotto)
    assert esito.returncode == 0, f"il run anomalo è fallito:\n{esito.stderr}"
    assert "ANOMALO" in esito.stdout, f"il flusso non ha segnalato l'anomalia:\n{esito.stdout}"

    # 0 upsert: nulla è stato scritto e nulla è stato annullato.
    assert _eventi(psql) == eventi_prima, "un delta anomalo non deve toccare gli eventi"
    assert len(_audit_ical(psql)) == audit_prima, "un delta anomalo non deve scrivere audit iCal"
    annullati = psql(
        "SELECT count(*) AS n FROM trasi.evento WHERE uid_ical LIKE 'b4test-%' AND annullato"
    )[0]["n"]
    assert int(annullati) == 0, "il delta anomalo non deve marcare `annullato`: non ha applicato nulla"

    # 1 proposta di coerenza, con il contesto nel payload.
    proposte = psql(
        "SELECT id, origine, entita, casa_id, fonte_id, motivazione, payload, approvatore_ruolo "
        "  FROM trasi.proposta WHERE origine = 'coerenza' ORDER BY id DESC LIMIT 1"
    )
    assert proposte, "il delta anomalo deve produrre una proposta, non una scrittura"
    proposta = proposte[0]
    assert proposta["approvatore_ruolo"] == "gestore", (
        f"la proposta di coerenza su una Casa la decide il gestore: {proposta['approvatore_ruolo']}"
    )
    assert '"anomalo": true' in proposta["payload"], f"payload senza `anomalo`: {proposta['payload']}"
    assert len(proposta["motivazione"]) <= 80, (
        f"motivazione di {len(proposta['motivazione'])} caratteri (V5/§12: ≤ 80)"
    )

    # `fonte_run.esito='anomalo'`: la traccia che il flusso ha *deciso* di non applicare.
    fonte_run = psql(
        "SELECT esito, righe, hash, dettaglio FROM trasi.fonte_run "
        " WHERE fonte_id = (SELECT id FROM trasi.fonte WHERE nome = 'Google Calendar-ical-2') "
        " ORDER BY id DESC LIMIT 1"
    )
    assert fonte_run, "il flusso non ha scritto in `fonte_run`"
    assert fonte_run[0]["esito"] == "anomalo", (
        f"`fonte_run.esito` atteso 'anomalo', ottenuto {fonte_run[0]['esito']}"
    )


@pytest.mark.live
def test_v5_nessun_campo_personale_negli_eventi(db_vivo, psql, ics_personale, ical_pulito):
    """Un feed con `ATTENDEE`/`ORGANIZER`/`DESCRIPTION` non fa entrare quei contenuti (V5/§12).

    Il test guarda la **riga nel database**: se un domani qualcuno aggiungesse `descrizione`
    all'INSERT, la riga porterebbe il testo dell'invito e questo test lo direbbe. Guardare il codice
    non basterebbe — la difesa è che il campo non venga letto, ma la prova è che non finisca in memoria.
    """
    import tempfile

    percorso = Path(tempfile.mkdtemp(prefix="b4pii-")) / "pii.ics"
    percorso.write_text(ics_personale, encoding="utf-8")
    assert _esegui(percorso).returncode == 0

    righe = psql(
        "SELECT id, titolo, descrizione, luogo_testo, url FROM trasi.evento "
        " WHERE uid_ical = 'b4test-pii@trasi.test'"
    )
    assert righe, "l'evento non è stato importato"
    evento = righe[0]

    # `descrizione` non è nemmeno un campo che il flusso scrive: resta NULL.
    assert evento["descrizione"] in (None, ""), (
        f"`descrizione` valorizzata: il feed portava testo libero con un nome e un telefono. "
        f"Valore: {evento['descrizione']!r}"
    )

    # Nessun contenuto personale in nessun campo importato.
    importo = " ".join(
        str(evento[campo] or "") for campo in ("titolo", "luogo_testo", "url")
    )
    for vietato in ("anna.rossi", "mario.bianchi", "340 99 88 776", "Anna", "Bianchi", "@example.org"):
        assert vietato.lower() not in importo.lower(), (
            f"{vietato!r} è finito in un campo importato: {importo!r}"
        )


def test_parser_non_conosce_i_campi_personali():
    """Il parser estrae quattro campi: `ATTENDEE`, `ORGANIZER` e `DESCRIPTION` non hanno una variabile.

    È una proprietà strutturale, non un filtro: un campo che non viene letto non può finire in memoria,
    e nessuna modifica futura può «dimenticare» di filtrarlo. Il test prova che il parser, messo di
    fronte a un feed che li contiene, non ne produce alcuna traccia negli oggetti che costruisce.
    """
    from tests.conftest import DB_VIVO  # noqa: F401  (import per il path, non per il valore)

    testo = (
        "BEGIN:VCALENDAR\nVERSION:2.0\n"
        "BEGIN:VEVENT\nUID:x@test\nDTSTART:20260920T100000\nDTEND:20260920T120000\n"
        "SUMMARY:Cineforum\nLOCATION:Sala\nURL:https://esempio.test/x\n"
        "DESCRIPTION:Chiedere di Anna al 340 99 88 776\n"
        "ATTENDEE;CN=Anna Rossi:mailto:anna.rossi@example.org\n"
        "ORGANIZER;CN=Mario Bianchi:mailto:mario.bianchi@example.org\n"
        "END:VEVENT\nEND:VCALENDAR\n"
    )
    eventi = fonti_ical.leggi_ics(testo)
    assert len(eventi) == 1
    evento = eventi[0]

    # I quattro campi ammessi sono popolati…
    assert evento.titolo == "Cineforum"
    assert evento.luogo_testo == "Sala"
    assert evento.url == "https://esempio.test/x"
    assert evento.inizio is not None

    # …e non esiste un attributo che possa portare i campi personali.
    assert not hasattr(evento, "attendee")
    assert not hasattr(evento, "organizer")
    assert not hasattr(evento, "description")

    importo = " ".join(str(v) for v in evento.chiave())
    for vietato in ("anna.rossi", "mario.bianchi", "340 99 88 776", "@example.org"):
        assert vietato.lower() not in importo.lower(), (
            f"{vietato!r} è finito nella chiave dell'evento: {importo!r}"
        )

    # E la descrizione del feed non compare da nessuna parte nell'oggetto serializzato.
    assert "Chiedere di Anna" not in repr(evento)


@pytest.mark.live
def test_annullamento_non_e_un_delete(db_vivo, psql, fixture_ics, ical_pulito):
    """Un evento sparito dal feed diventa `annullato=true`: la riga **resta** (V4 regola 7, §8 F4).

    Il caso è al di sotto della soglia (1 su 5 = 20% < 50%): qui si vuole provare il *soft-close*, non
    l'anomalia. «La Casa aveva in programma X e non c'è più» è informazione: una riga cancellata non
    la porta.
    """
    feed = fixture_ics(titolo_evento="Evento", orario="100000", n_eventi=5)
    assert _esegui(feed).returncode == 0
    eventi_prima = _eventi(psql)

    # 4 eventi su 5 (20% rimosso: sotto soglia).
    ridotto = fixture_ics(titolo_evento="Evento", orario="100000", n_eventi=4)
    assert _esegui(ridotto).returncode == 0

    dopo = _eventi(psql)
    # Nessuna riga è stata cancellata: gli id sono gli stessi.
    assert {u: e["id"] for u, e in dopo.items()} == {u: e["id"] for u, e in eventi_prima.items()}, (
        "una riga è stata rimossa: il flusso iCal non fa mai DELETE (§8 F4)"
    )
    annullati = [u for u, e in dopo.items() if e["annullato"]]
    assert len(annullati) == 1, f"atteso 1 evento annullato, trovati {len(annullati)}"
    assert annullati[0] == "b4test-evento-4@trasi.test"

    # La riga di audit racconta l'annullamento: `prima` senza `annullato`, `dopo` con.
    ultima = _audit_ical(psql)[-1]
    assert '"annullato": false' in ultima["prima"], f"prima inatteso: {ultima['prima'][:200]}"
    assert '"annullato": true' in ultima["dopo"], f"dopo inatteso: {ultima['dopo'][:200]}"
