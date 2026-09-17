"""Trasi — V6 sui template: i messaggi dicono **chi decide**, non assegnano compiti.

Il controllo è lessicale e automatico, come chiede la spec («check lessicale su tutti i template →
0 verbi imperativi»). Non è una revisione a occhio: una revisione a occhio non gira in CI e non
sopravvive a chi riscrive un template fra sei mesi.

I messaggi provengono dalle funzioni che li compongono **davvero** (`alert.messaggi_*`), non da copie
nei test: un test che verificasse una copia del template proverebbe la copia.
"""

from __future__ import annotations

import pytest

from comune import CAMPI_V6, MOTIVAZIONE_MAX, verifica_v6, v6_ok

import alert

#: Il vocabolario vietato, quello della spec B4 più `plan.md` §4 B4-FLW-09. Ridichiarato qui perché un
#: test che importasse l'elenco dal codice che verifica non proverebbe nulla: se l'elenco sparisse, il
#: test resterebbe verde. Questo è il contratto, non un dettaglio implementativo.
VIETATI = ("devi", "dovete", "fai", "fate", "assegna", "assegnate", "contatta", "contattate",
           "bisogna", "occorre")


def test_il_presidio_riconosce_i_verbi_vietati():
    """La controprova: senza, i test sui template sarebbero verdi anche con un presidio rotto."""
    for verbo in VIETATI:
        assert verifica_v6(f"Per favore {verbo} aggiornare la scheda") == [verbo.lower()], (
            f"il presidio deve riconoscere {verbo!r}"
        )

    # Un verbo dentro una parola più lunga non è un imperativo: «contattare» in una citazione non
    # deve far scattare «contatta» (né «fate» dentro «sfate»).
    assert v6_ok("Il modulo si può contattare via PEC"), "«contattare» non è l'imperativo «contatta»"
    assert v6_ok("Le attività si svolgono al piano terra")
    assert v6_ok("La proposta è in attesa di una decisione")


@pytest.mark.live
def test_messaggi_proposte_rispettano_v6(db_vivo, proposta_vecchia):
    """I template delle proposte: nessun imperativo, e i quattro campi V6 presenti.

    La premessa (una proposta aperta **da 8 giorni**, oltre la soglia di §8 F6) la costruisce la
    fixture `proposta_vecchia`, e non è un dettaglio: `messaggi_proposte(7)` filtra `giorni > 7`, quindi
    senza quella riga la funzione restituisce zero messaggi e il test non verificherebbe **nessun**
    template. Prima della fixture asseriva `assert messaggi` appoggiandosi a una proposta vecchia
    rimasta nel database condiviso: verde per ragioni ambientali, e rosso — senza indicare alcun difetto
    del codice — il giorno in cui quella riga non c'è più stata (misurato il 2026-09-17, coda con una
    sola proposta di 1 giorno).
    """
    messaggi = alert.messaggi_proposte(7)
    assert messaggi, (
        "la fixture ha creato una proposta oltre la soglia: atteso almeno un messaggio"
    )

    for messaggio in messaggi:
        corpo = messaggio.corpo()
        assert v6_ok(corpo), f"V6 violato in {messaggio.oggetto}: {verifica_v6(corpo)}"
        assert v6_ok(messaggio.oggetto), f"V6 violato nell'oggetto: {messaggio.oggetto}"
        for campo in CAMPI_V6:
            assert campo in messaggio.campi and messaggio.campi[campo], (
                f"campo V6 mancante o vuoto: {campo}"
            )
            assert campo.replace("_", " ") in corpo.lower() or campo in ("cosa_osservato",
                                                                        "cosa_si_potrebbe_fare")
        # «template ≤ 15 righe»: un avviso che si legge in una schermata viene letto.
        assert len(corpo.splitlines()) <= alert.Messaggio.MAX_RIGHE, (
            f"messaggio di {len(corpo.splitlines())} righe: il tetto è "
            f"{alert.Messaggio.MAX_RIGHE}"
        )


@pytest.mark.live
def test_messaggi_coerenza_rispettano_v6(db_vivo, pulizia):
    """Il template della coerenza fonti: nessun imperativo, quattro campi, ≤ 15 righe."""
    if not db_vivo:
        pytest.skip("database non raggiungibile: la coerenza si compone su dati reali")

    messaggi = alert.messaggi_coerenza()
    if not messaggi:
        pytest.skip("nessuna incoerenza di fonte nel database corrente")

    for messaggio in messaggi:
        corpo = messaggio.corpo()
        assert v6_ok(corpo), f"V6 violato: {verifica_v6(corpo)}"
        for campo in CAMPI_V6:
            assert messaggio.campi.get(campo), f"campo V6 mancante: {campo}"
        assert len(corpo.splitlines()) <= alert.Messaggio.MAX_RIGHE


def test_ogni_messaggio_dichiara_chi_decide():
    """`chi_decide` non è un campo decorativo: dice il ruolo, non assegna un compito.

    Il test costruisce un messaggio a mano: la proprietà da difendere è del *template*, e va provata
    anche quando il database non ha proposte da recapitare.
    """
    messaggio = alert.Messaggio(
        a="gestore.san-bao@trasi.local",
        oggetto="Trasi · 1 in attesa",
        campi={
            "cosa_osservato": "Coda delle proposte: 1 in attesa da oltre 7 giorni",
            "evidenza": "vista trasi.v_flusso_alert_proposte",
            "cosa_si_potrebbe_fare": "Le proposte si possono approvare o rifiutare dalla coda",
            "chi_decide": "Il ruolo che decide queste proposte è il gestore della Casa.",
        },
        righe=["  · proposta 1 — scheda_servizio · San Bao · 8 giorni"],
    )
    corpo = messaggio.corpo()
    assert "Chi decide:" in corpo
    assert "gestore della Casa" in corpo
    assert v6_ok(corpo)
    assert len(corpo.splitlines()) <= alert.Messaggio.MAX_RIGHE


def test_motivazione_rispetta_il_limite_di_80_caratteri():
    """V5/§12: `motivazione ≤ 80`. Il limite è applicato da `comune.motivazione`, non sperato."""
    from comune import motivazione

    lunga = ("Calendario bozzano: 0 nuovi e 4 rimossi su 5 (80.0% > 50%): "
             "possibile feed rotto o riorganizzazione — e altro testo che va oltre")
    risultato = motivazione(lunga)
    assert len(risultato) <= MOTIVAZIONE_MAX, f"{len(risultato)} caratteri: il limite è {MOTIVAZIONE_MAX}"
    assert risultato.endswith("…"), "il troncamento deve essere visibile, non silenzioso"
    assert not risultato.endswith(" …"), "non deve restare uno spazio prima del taglio"
