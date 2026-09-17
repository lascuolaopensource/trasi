"""Fixture condivise dei test dei flussi (B4).

Tre scelte dichiarate, perché non sono ovvie.

**I test girano sul database vero, marcati `live`.** I flussi *sono* la cosa che si vuole provare, e la
cosa che provano è un effetto sul database: una riga di `audit` in più, un `orari` immutato, un
`flusso_run.esito`. Un doppio del database proverebbe che il codice chiama le query che il test si
aspetta — cioè proverebbe la propria assunzione, non il comportamento (§ «mai asserire
l'implementazione»). Chi non ha lo stack acceso li salta, con un motivo.

**I test si puliscono da soli.** `db/apply.sh` è rieseguibile e la fixture `pulizia` rimuove solo le
righe che i test stessi hanno marcato (`B4TEST:`, `(fixture B4TEST)`), più le righe di registro dei
flussi. Lezione di B3: le prove su un DB condiviso vanno fatte in transazione **o pulite subito**; e i
test girano in parallelo alla rete reale, che non si azzera.

**Il test dell'identità è separato e non si salta.** `test_identita.py` non ha bisogno del database:
prova che il comando che i flussi costruiscono si connette **come** `automazioni`. È il presidio di una
perdita silenziosa già misurata (5 eventi scritti, 0 righe di audit), e un presidio che si salta non è
un presidio.
"""

from __future__ import annotations

import os
import subprocess
import re
import socket
import sys
from pathlib import Path

import pytest

RADICE = Path(__file__).resolve().parent.parent.parent
if str(RADICE / "flussi") not in sys.path:
    sys.path.insert(0, str(RADICE / "flussi"))

FIXTURES = RADICE / "flussi" / "fixtures"


def _db_raggiungibile() -> bool:
    """Il database risponde su TCP? Verifica di rete, non di credenziali."""
    try:
        with socket.create_connection(("127.0.0.1", int(os.environ.get("HOST_PORT_DB", "5432"))),
                                      timeout=1.5):
            return True
    except OSError:
        return False


DB_VIVO = _db_raggiungibile()


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "live: richiede il database Trasi (saltato se assente)"
    )


@pytest.fixture(scope="session")
def db_vivo() -> bool:
    return DB_VIVO


@pytest.fixture(scope="session")
def psql():
    """Un lettore dal database, come `automazioni` — la stessa identità dei flussi.

    Ritorna una funzione `psql(sql) -> list[dict]`. Non è un ORM e non serve: i test leggono conteggi
    e righe, e la via CSV di `comune.leggi()` è già quella che i flussi usano — quindi una query del
    test e una query del flusso passano dallo stesso trasporto.
    """
    from comune import leggi

    def leggi_con(sql: str) -> list[dict]:
        return leggi(sql)

    return leggi_con


@pytest.fixture(scope="session")
def sql_amministratore():
    """Una funzione `sql(query) -> list[dict]` nel ruolo amministratore.

    Serve **solo** alle operazioni che nessun ruolo applicativo può fare, ed è dichiarato nel punto
    d'uso: cancellare le righe di fixture (nessun ruolo applicativo ha `DELETE` su `proposta`/`audit`,
    ed è una protezione voluta — V4) e simulare il tempo che passa (`proposto_ts`, non grantato in
    INSERT). Mai per verificare: le verifiche passano da `psql`, cioè dal ruolo dei flussi.
    """
    import subprocess

    from comune import COMPOSE, DB_DEFAULT, SERVIZIO_DB

    def esegui(query: str) -> list[dict]:
        comando = [
            "docker", "compose", "-f", str(COMPOSE), "exec", "-T", SERVIZIO_DB,
            "psql", "-U", "postgres", "-d", os.environ.get("TRASI_DB") or DB_DEFAULT,
            "-X", "-q", "-t", "-A", "-F", "\t", "-c", query,
        ]
        esito = subprocess.run(comando, capture_output=True, text=True, check=False)
        if esito.returncode != 0:
            raise RuntimeError(f"psql amministratore fallito: {esito.stderr.strip()[:500]}")
        return [dict(zip(("valore",), riga.split("\t"))) for riga in esito.stdout.splitlines() if riga]

    return esegui


@pytest.fixture
def pulizia():
    """Rimuove le righe marcate dai test (`B4TEST:`) e il registro dei flussi.

    Non tocca la memoria della rete: solo proposte/audit con il contrassegno dei test e le righe di
    `flusso_run`/`fonte_run` (che sono registro, non dominio). Un test che non può essere ripetuto due
    volte di fila non prova l'idempotenza, che è il criterio principale del blocco.
    """
    import subprocess

    from comune import COMPOSE, DB_DEFAULT, SERVIZIO_DB

    def esegui(query: str) -> None:
        comando = [
            "docker", "compose", "-f", str(COMPOSE), "exec", "-T", SERVIZIO_DB,
            "psql", "-U", "postgres", "-d", os.environ.get("TRASI_DB") or DB_DEFAULT,
            "-X", "-q", "-v", "ON_ERROR_STOP=1", "-c", query,
        ]
        esito = subprocess.run(comando, capture_output=True, text=True, check=False)
        if esito.returncode != 0:
            raise RuntimeError(f"pulizia fallita: {esito.stderr.strip()[:500]}")

    def pulisci(*, registro: bool = True, eventi: bool = False, proposte: bool = True,
                automatiche: bool = False) -> None:
        """`automatiche=True` rimuove anche le proposte prodotte da `fonti_http` (origine
        `fonte_automatica`): sono un ingresso di cambiamento per i test del flusso HTTP, e una
        proposta rimasta da una prova manuale farebbe fallire il caso «prima osservazione» in modo
        incomprensibile. Restano fuori dal perimetro di default: un test che non tocca quel flusso non
        deve poter cancellare le sue proposte.
        """
        if proposte:
            # **Le entità create dalle fixture vanno rimosse insieme alle proposte e al loro audit.**
            # Cancellare solo le proposte e le righe di `audit` lasciava in piedi ciò che il percorso
            # applicativo aveva scritto — una `scheda_servizio`, un `luogo` promosso — con
            # `aggiornato_da='applicatore'` e **senza più la riga di audit che lo giustificava**.
            # Effetto misurato: `v_scritture_senza_audit` segnalava due «scritture senza audit» che
            # erano, in realtà, scritture perfettamente contabilizzate a cui il test aveva tolto la
            # contabilità. Una falsa violazione di V4 prodotta dalla pulizia dei test è il tipo di
            # rumore che fa ignorare la vista quando segnala una violazione vera.
            # L'ordine è obbligato: prima l'audit (la FK `audit.proposta_id`), poi le entità, poi le
            # proposte. Si rimuovono **solo** le righe contrassegnate dalle fixture.
            esegui(
                "DELETE FROM trasi.audit WHERE entita = 'scheda_servizio' AND entita_id IN "
                "(SELECT id FROM trasi.scheda_servizio WHERE titolo LIKE '%(B4TEST)')"
            )
            esegui("DELETE FROM trasi.scheda_servizio WHERE titolo LIKE '%(B4TEST)'")
            esegui(
                "DELETE FROM trasi.audit WHERE proposta_id IN "
                "(SELECT id FROM trasi.proposta WHERE motivazione LIKE 'B4TEST:%')"
            )
            esegui("DELETE FROM trasi.proposta WHERE motivazione LIKE 'B4TEST:%'")
            # Il luogo promosso dalle fixture torna al valore del seed: si individua per fonte, perché
            # è il nome che la promozione riscrive. `aggiornato_da` torna a NULL — è l'impronta della
            # scrittura, e dopo il ripristino non c'è più una scrittura da imputare.
            #
            # **Il trigger va disabilitato per questo UPDATE, e senza di esso il ripristino non
            # avviene affatto.** `scrittura_00_ts` (db/005) è un trigger `BEFORE INSERT OR UPDATE`
            # che *scrive* `NEW.aggiornato_ts := now()` e `NEW.aggiornato_da := current_user`: un
            # `SET aggiornato_da = NULL` viene sovrascritto dal trigger prima che la riga sia scritta.
            # Misurato: `UPDATE … SET aggiornato_da = NULL, aggiornato_ts = NULL` lascia
            # `aggiornato_da = 'postgres'` e `aggiornato_ts` non nullo. La pulizia sembrava riuscire
            # (exit 0, nessun errore) e lasciava intatto ciò che doveva rimuovere: il risultato era
            # esattamente la violazione di V4 che questo blocco esiste per non produrre.
            # `ALTER TABLE … DISABLE TRIGGER` nella stessa transazione è l'unico modo di scrivere
            # quei due campi, ed è confinato alla pulizia (il trigger resta attivo per tutto il resto).
            esegui(
                "BEGIN; "
                "ALTER TABLE trasi.luogo DISABLE TRIGGER scrittura_00_ts; "
                "UPDATE trasi.luogo SET nome = 'CAF ACLI La Rosa', affidabilita = 1, orari = NULL, "
                "       ext_ref = NULL, aggiornato_da = NULL, aggiornato_ts = NULL, "
                "       data_aggiornamento = current_date "
                " WHERE fonte_id = (SELECT id FROM trasi.fonte WHERE nome = 'CAF ACLI Brindisi'); "
                "ALTER TABLE trasi.luogo ENABLE TRIGGER scrittura_00_ts; "
                "COMMIT;"
            )
        if automatiche:
            esegui("DELETE FROM trasi.audit WHERE proposta_id IN "
                   "(SELECT id FROM trasi.proposta WHERE origine = 'fonte_automatica')")
            esegui("DELETE FROM trasi.proposta WHERE origine = 'fonte_automatica'")
        if eventi:
            # Si rimuovono **tutti** gli eventi della fonte iCal, non solo quelli marcati `b4test-`.
            # Il flusso calcola il delta contro *tutto* ciò che è in memoria per quella fonte: un
            # evento rimasto da una prova manuale verrebbe contato come «rimosso» e farebbe scattare
            # l'anomalia, facendo passare il caso «feed cambiato» per il motivo sbagliato. Queste
            # righe sono tutte prodotte dal flusso e si ricreano importando la fixture — non è memoria
            # della rete scritta a mano, ed è il solo modo di rendere il delta deterministico.
            #
            # **L'audit si rimuove per `uid_ical`, non per `entita_id`.** La forma precedente
            # cancellava l'audit degli eventi *ancora esistenti* e poi gli eventi: bastava una
            # esecuzione interrotta fra le due istruzioni — o una riga di audit che puntava a un
            # evento già rimosso da un run precedente — perché restassero righe **orfane**, che
            # nessuna esecuzione successiva poteva più associare a un evento. Misurato: 6 righe
            # `ical_upsert` orfane dopo una serata di esecuzioni, e i test che contano
            # `dopo->>'uid_ical' LIKE 'b4test-%'` le sommavano ai propri, fallendo in modo diverso a
            # ogni run («attese 5 + 1, trovate 7»). Il marcatore `b4test-` è nel payload dell'audit
            # stesso, quindi si può usare direttamente e non dipende dall'esistenza dell'evento.
            esegui(
                "DELETE FROM trasi.audit WHERE azione = 'ical_upsert' "
                "  AND dopo->>'uid_ical' LIKE 'b4test-%'"
            )
            # Rete di sicurezza per gli orfani già accumulati dalle esecuzioni precedenti: righe di
            # audit su eventi che non esistono più. Non tocca l'audit degli eventi vivi.
            esegui(
                "DELETE FROM trasi.audit WHERE entita = 'evento' "
                "  AND NOT EXISTS (SELECT 1 FROM trasi.evento e WHERE e.id = trasi.audit.entita_id)"
            )
            esegui(
                "DELETE FROM trasi.evento WHERE fonte_id = "
                "(SELECT id FROM trasi.fonte WHERE nome = 'Google Calendar-ical-2')"
            )
            # Le proposte di coerenza create dai casi di anomalia.
            #
            # L'`audit` si cancella per `proposta_id` **e** per `entita_id`, e non è ridondanza:
            # `proposta_02_audit_tg` scrive più righe per la stessa proposta (`proposta_creata`,
            # `transizione`), tutte con la stessa `proposta_id` — quindi il solo `proposta_id`
            # basterebbe. Il caso che rompeva è un altro: una proposta può essere cancellata **prima**
            # che questo blocco la raggiunga (un caso della batteria che ripulisce la propria), e la
            # sua riga di audit resta agganciata all'entità. Con la FK `audit.proposta_id →
            # proposta.id` questo produce `update or delete on table "proposta" violates foreign key
            # constraint "audit_proposta_id_fkey"`: la pulizia fallisce, le righe restano, e il test
            # successivo eredita lo stato — il modo in cui un guasto di pulizia diventa un guasto
            # apparente di logica, tre file più in là.
            esegui(
                "DELETE FROM trasi.audit WHERE proposta_id IN "
                "(SELECT id FROM trasi.proposta WHERE origine = 'coerenza')"
            )
            esegui(
                "DELETE FROM trasi.audit WHERE entita = 'evento' AND entita_id IN "
                "(SELECT proposta.entita_id FROM trasi.proposta proposta "
                " WHERE proposta.origine = 'coerenza' AND proposta.entita_id IS NOT NULL)"
            )
            esegui("DELETE FROM trasi.proposta WHERE origine = 'coerenza'")
        if registro:
            esegui("DELETE FROM trasi.flusso_run")
            esegui("DELETE FROM trasi.fonte_run")
            # I report scritti dai run di prova restano orfani del run che li ha generati: si tolgono
            # solo quelli legati a un `flusso_run` inesistente (i report veri, generati da cicli
            # passati, sono legati a run che esistono — e non si toccano).
            esegui(
                "DELETE FROM trasi.report WHERE flusso_run_id IS NOT NULL "
                " AND NOT EXISTS (SELECT 1 FROM trasi.flusso_run f WHERE f.id = flusso_run_id)"
            )

    return pulisci


@pytest.fixture
def proposta_vecchia(pulizia, db_vivo):
    """Una proposta **aperta da 8 giorni**, così i messaggi di alert si possono comporre.

    Perché serve, e perché è una fixture condivisa e non un pezzo di un solo test.

    `alert.messaggi_proposte(7)` seleziona le proposte con `giorni > 7` (è la soglia di §8 F6), quindi
    **con una coda fresca restituisce zero messaggi**. Il test `test_messaggi_proposte_rispettano_v6`
    asseriva `assert messaggi` senza creare nulla: era verde finché nel database condiviso restava una
    proposta aperta più vecchia di otto giorni — cioè per ragioni **ambientali**, non per merito del
    codice che doveva verificare.

    Misurato il 2026-09-17: la coda aveva una sola proposta aperta di **1 giorno**, il test è diventato
    rosso (`assert []`) e il rosso non segnalava alcun difetto del codice: segnalava che era finito
    l'invecchiamento di una riga altrui. Un test che dipende da quanto a lungo una proposta è rimasta
    in coda è un test che si rompe da solo, e la sua rottura non dice niente su ciò che verifica.

    L'invecchiamento di `proposto_ts` passa dall'amministratore: il campo **non è grantato in INSERT** a
    nessun ruolo client — il tempo che passa non ha un percorso applicativo — quindi simulare il tempo
    richiede quel passo. È dichiarato, non nascosto (stessa scelta di `flussi/fixtures/alert.sql` e di
    `test_alert.py`).

    La fixture vale per **tutti** i test che compongono messaggi: `test_alert.py` e `test_v6_template.py`
    chiedono la stessa premessa, e averla in due copie significherebbe due posti da aggiornare quando
    cambia la soglia.
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile: i messaggi si compongono su dati reali")

    import subprocess

    from comune import COMPOSE, DB_DEFAULT, SERVIZIO_DB

    marca = "B4TEST: proposta vecchia"
    sql = f"""
\\set ON_ERROR_STOP on
DELETE FROM trasi.audit WHERE proposta_id IN
  (SELECT id FROM trasi.proposta WHERE motivazione = '{marca}');
DELETE FROM trasi.proposta WHERE motivazione = '{marca}';

SET ROLE rete;
SET search_path = trasi, public, pg_temp;
INSERT INTO trasi.proposta (origine, tipo, entita, casa_id, payload, motivazione)
SELECT 'manuale', 'modifica_scheda', 'scheda_servizio', c.id,
       jsonb_build_object('descrizione', 'aggiornata'), '{marca}'
  FROM trasi.casa c WHERE c.slug = 'san-bao';
RESET ROLE;

-- Simulazione del tempo: 8 giorni di attesa. Come in `test_alert.py`, dall'amministratore.
SET ROLE trasi_owner;
UPDATE trasi.proposta SET proposto_ts = now() - interval '8 days' WHERE motivazione = '{marca}';
RESET ROLE;

DO $$
DECLARE n int;
BEGIN
  SELECT count(*) INTO n FROM trasi.v_flusso_alert_proposte
   WHERE proposta_id IN (SELECT id FROM trasi.proposta WHERE motivazione = '{marca}')
     AND giorni > 7;
  IF n < 1 THEN RAISE EXCEPTION 'fixture: la proposta vecchia non compare negli alert (giorni > 7)'; END IF;
END $$;
"""
    comando = [
        "docker", "compose", "-f", str(COMPOSE), "exec", "-T", SERVIZIO_DB,
        "psql", "-U", "postgres", "-d", os.environ.get("TRASI_DB") or DB_DEFAULT,
        "-X", "-q", "-v", "ON_ERROR_STOP=1", "-f", "-",
    ]
    esito = subprocess.run(comando, input=sql, capture_output=True, text=True, check=False)
    if esito.returncode != 0:
        raise RuntimeError(f"fixture proposta_vecchia fallita: {esito.stderr.strip()[:600]}")

    # La rimozione delle righe a fine test è affidata alla **stessa `pulizia`** che le altre fixture
    # usano: `pulizia(proposte=True)` cancella `motivazione LIKE 'B4TEST:%'`, e il marcatore di questa
    # fixture comincia per `B4TEST:`. Nessuna `DELETE` propria, quindi: una regola sola per lo sporco
    # dei test, e se un giorno cambia il marcatore cambia in un posto.
    yield {"marca": marca, "out": esito.stdout}
    pulizia(registro=True, proposte=True)


@pytest.fixture(scope="session")
def fixture_ics():
    """La fixture ICS del blocco, scritta per il test in una cartella temporanea.

    Il test **costruisce** il proprio feed invece di leggere quello del repo: così può variare l'orario
    di un evento senza toccare il file che l'esercizio usa a mano, e il caso «1 orario cambiato» è
    esplicito nel test invece di dipendere da un file che qualcuno può aver modificato.
    """
    def scrivi(*, titolo_evento: str = "Evento di prova", orario: str = "100000",
               n_eventi: int = 5) -> Path:
        """Un feed di `n_eventi`, tutti a partire da domani, con l'orario del primo variabile.

        Le date si calcolano con `timedelta` e non con l'aritmetica sulle stringhe: il generatore è la
        base di ogni confronto del test, e un `DTSTART` malformato (`202609110T…`, ottenuto sommando a
        una stringa) verrebbe scartato dal parser senza che il test se ne accorga — gli eventi
        sparirebbero e il caso «80% rimosso» sarebbe verde per il motivo sbagliato.
        """
        import tempfile
        from datetime import datetime, timedelta

        base = datetime.now() + timedelta(days=1)
        blocchi = []
        for indice in range(n_eventi):
            giorno = base + timedelta(days=indice)
            # Solo il primo evento porta l'orario richiesto: è quello su cui il test misura il cambio.
            ora = orario if indice == 0 else f"{9 + indice:02d}0000"
            dtstart = giorno.strftime("%Y%m%d") + "T" + ora
            dtend = giorno.strftime("%Y%m%d") + "T" + f"{int(ora[:2]) + 1:02d}" + ora[2:]
            blocchi.append(
                f"BEGIN:VEVENT\n"
                f"UID:b4test-evento-{indice}@trasi.test\n"
                f"DTSTAMP:20260915T060000Z\n"
                f"DTSTART:{dtstart}\n"
                f"DTEND:{dtend}\n"
                f"SUMMARY:{titolo_evento} {indice}\n"
                f"LOCATION:Sala di prova {indice}\n"
                f"END:VEVENT\n"
            )
        testo = (
            "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Trasi//Test B4//IT\n"
            + "".join(blocchi) + "END:VCALENDAR\n"
        )
        percorso = Path(tempfile.mkdtemp(prefix="b4ics-")) / "casa.ics"
        percorso.write_text(testo, encoding="utf-8")
        return percorso

    return scrivi


@pytest.fixture
def ics_personale() -> str:
    """Un feed con `ATTENDEE`, `ORGANIZER` e `DESCRIPTION`: i campi che **non** devono entrare (V5)."""
    return (
        "BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//Trasi//PII//IT\n"
        "BEGIN:VEVENT\n"
        "UID:b4test-pii@trasi.test\n"
        "DTSTAMP:20260915T060000Z\n"
        "DTSTART:20260920T100000\n"
        "DTEND:20260920T120000\n"
        "SUMMARY:Cineforum\n"
        "LOCATION:Sala grande\n"
        "DESCRIPTION:Chiedere di Anna al 340 99 88 776, anna.rossi@example.org\n"
        "ATTENDEE;CN=Anna Rossi;EMAIL=anna.rossi@example.org:mailto:anna.rossi@example.org\n"
        "ORGANIZER;CN=Mario Bianchi:mailto:mario.bianchi@example.org\n"
        "END:VEVENT\n"
        "END:VCALENDAR\n"
    )


def pulisci_report_consentito(mese: str) -> None:
    """Rimuove le righe `trasi.report` di un mese di fixture (usato dai test del ciclo mensile).

    `report` è oggetto di dominio a sola lettura per i ruoli Casa, ma è **output di flusso** per chi lo
    genera: la pulizia dei test passa da qui, e solo per il mese marcato di fixture, mai sui report veri.
    """
    from comune import COMPOSE, DB_DEFAULT, SERVIZIO_DB
    import os
    import subprocess

    def esegui(query: str) -> None:
        comando = [
            "docker", "compose", "-f", str(COMPOSE), "exec", "-T", SERVIZIO_DB,
            "psql", "-U", "postgres", "-d", os.environ.get("TRASI_DB") or DB_DEFAULT,
            "-X", "-q", "-v", "ON_ERROR_STOP=1", "-c", query,
        ]
        esito = subprocess.run(comando, capture_output=True, text=True, check=False)
        if esito.returncode != 0:
            raise RuntimeError(f"pulizia report fallita: {esito.stderr.strip()[:500]}")

    esegui(f"DELETE FROM trasi.commento WHERE entita = 'report' AND entita_id IN (SELECT id FROM trasi.report WHERE mese = DATE '{mese}')")
    esegui(f"DELETE FROM trasi.report WHERE mese = DATE '{mese}'")


def _esegui_pulizia(*, registro: bool, proposte: bool) -> None:
    """Il `pulisci` del fixture come chiamata diretta (fuori da pytest): i test del ciclo che girano
    `subprocess` hanno bisogno di pulire il registro **dopo** l'esito, e la fixture è una chiusura.

    La logica va replicata qui **per il solo registro**: chiamare la fixture direttamente è vietato da pytest,
    e duplicare le due DELETE è ciò che il fixture stesso chiama «la seconda verità». La via è una: la funzione
    di pulizia vive a livello di modulo e la fixture la riusa, non la duplica."""
    import subprocess

    from comune import COMPOSE, DB_DEFAULT, SERVIZIO_DB

    def esegui(query: str) -> None:
        comando = [
            "docker", "compose", "-f", str(COMPOSE), "exec", "-T", SERVIZIO_DB,
            "psql", "-U", "postgres", "-d", os.environ.get("TRASI_DB") or DB_DEFAULT,
            "-X", "-q", "-v", "ON_ERROR_STOP=1", "-c", query,
        ]
        esito = subprocess.run(comando, capture_output=True, text=True, check=False)
        if esito.returncode != 0:
            raise RuntimeError(f"pulizia fallita: {esito.stderr.strip()[:500]}")

    if registro:
        esegui("DELETE FROM trasi.flusso_run")
        esegui("DELETE FROM trasi.fonte_run")
