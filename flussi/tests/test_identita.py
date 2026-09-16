"""Trasi — flussi: l'identità con cui girano i flussi.

Questo file prova **una cosa sola**, e non richiede il database: il comando che i flussi costruiscono
si connette **come** `automazioni`, e non come amministratore con un `SET ROLE`.

Perché merita un file. Durante lo sviluppo del blocco è stato misurato questo: con
`psql -U postgres` + `SET LOCAL ROLE automazioni`, `session_user` resta `postgres`. Le scritture
passano (il superuser scavalca la RLS), il codice esce 0, il flusso scrive 5 eventi — e **zero righe
di audit**, perché il trigger `evento_ical_01_audit` (db/006) attribuisce la riga `ical_upsert`
guardando `session_user`. È la perdita di tracciabilità più insidiosa possibile: nessun errore, nessun
sintomo, e la contabilità di V4 (`v_scritture_senza_audit`) che accusa una violazione inesistente.

Il test non guarda il codice: guarda la riga di comando. Se qualcuno cambia il trasporto, il test lo
vede prima che il difetto arrivi in produzione.
"""

from __future__ import annotations

import os

import pytest

from comune import RUOLO_FLUSSI, _comando_psql, via_trasporto


def test_trasporto_docker_si_connette_come_automazioni(monkeypatch):
    """`docker compose exec … psql -U automazioni`: il ruolo è nella connessione, non in un `SET ROLE`."""
    monkeypatch.setenv("TRASI_DB_VIA", "docker")
    comando = _comando_psql()

    assert "-U" in comando, f"il comando deve dichiarare l'utente: {comando}"
    utente = comando[comando.index("-U") + 1]
    assert utente == RUOLO_FLUSSI == "automazioni", (
        f"i flussi devono connettersi come {RUOLO_FLUSSI!r}, non {utente!r}: con `SET ROLE` "
        "`session_user` resterebbe l'utente di login e l'audit iCal non verrebbe scritto"
    )
    assert "postgres" not in comando, (
        "nessuna parte del comando deve usare l'amministratore: i flussi girano con i privilegi "
        "reali del ruolo applicativo, altrimenti il test non proverebbe che quei privilegi bastano"
    )


def test_trasporto_diretto_non_impone_set_role(monkeypatch):
    """Nel container il ruolo arriva da `PGUSER`: anche lì l'identità è la connessione."""
    monkeypatch.setenv("TRASI_DB_VIA", "diretta")
    monkeypatch.delenv("PGUSER", raising=False)

    comando = _comando_psql()
    assert comando[0] == "psql"
    assert "-U" not in comando or comando[comando.index("-U") + 1] == RUOLO_FLUSSI

    from comune import _ambiente

    ambiente = _ambiente()
    assert ambiente["PGUSER"] == RUOLO_FLUSSI

    # La password non compare **mai** nella riga di comando: finirebbe in `ps` e nella history.
    assert not any("password" in pezzo.lower() or "PGPASSWORD=" in pezzo for pezzo in comando)


def test_via_trasporto_dedotta_dal_contesto(monkeypatch):
    """Senza `TRASI_DB_VIA` la scelta è dedotta: `docker` da host, `diretta` nel container."""
    monkeypatch.delenv("TRASI_DB_VIA", raising=False)
    monkeypatch.setenv("PATH", "/nonexistent")   # simula il container: niente `docker`
    assert via_trasporto() == "diretta"

    monkeypatch.setenv("TRASI_DB_VIA", "DOCKER")
    assert via_trasporto() == "docker", "il valore dichiarato vince sulla deduzione, normalizzato"


@pytest.mark.live
def test_la_batteria_non_lascia_violazioni_di_v4(db_vivo, psql):
    """Dopo la batteria, `v_scritture_senza_audit` non deve accusare scritture di `automazioni`.

    È la contabilità di V4 (B1-PRP-06) e insieme il controllo che le **fixture dei test non inquinino
    la contabilità**: la pulizia cancella l'audit scritto dal percorso applicativo, quindi se lasciasse
    in piedi l'entità che quell'audit giustificava, la vista segnalerebbe una violazione di V4 che non
    esiste. Misurato: due «scritture senza audit» di `applicatore` prodotte dalla sola pulizia dei
    test. Un falso positivo qui è il difetto peggiore possibile per questa vista — è il rumore che fa
    ignorare la vista quando segnala una violazione vera.

    Le scritture di `trasi_owner` (seed) e dei ruoli Casa (matrice di B1, dichiarate fuori flusso) sono
    escluse dalla vista stessa: quello che resta da sorvegliare sono proprio `automazioni` e
    `applicatore`, cioè i due percorsi di scrittura di B4.
    """
    orfane = psql(
        "SELECT entita, entita_id, scritto_da FROM trasi.v_scritture_senza_audit "
        " WHERE scritto_da IN ('automazioni', 'applicatore')"
    )
    assert orfane == [], (
        "la batteria ha lasciato scritture mediate senza la loro riga di audit: "
        f"{orfane}"
    )


def test_ruolo_flussi_e_il_contratto():
    """Il ruolo è un contratto: `EXECUTE` su `applica_proposte_approvate` è concesso a lui e a `ti`."""
    assert RUOLO_FLUSSI == "automazioni"
    assert os.environ.get("TRASI_DB_ROLE", "automazioni") == "automazioni"
