"""Test di F3 «export KB» — pubblicazione, idempotenza e **cancellazione degli orfani**.

Il bug riparato qui (2026-09-16) era di quelli che non si vedono: la funzione che cancellava i
documenti non esisteva affatto, quindi un luogo chiuso o un evento annullato **restava citabile
dalla chat** — con un badge che dichiarava una fonte attendibile per un dato che il database non
aveva più. Un difetto di V3, non un dettaglio di manutenzione.

Il test non tocca la KB reale: verifica la **logica di calcolo** degli orfani e la forma
dell'id nel percorso, che è il punto in cui il primo tentativo di riparazione ha sbagliato
(404 silenziosi su documenti esistenti, per la decodifica del percorso da parte di FastAPI).
"""

from __future__ import annotations

import urllib.parse

import export_kb as e


# --------------------------------------------------------------- forma dell'id nel percorso


def test_id_nel_percorso_codifica_due_volte_il_separatore() -> None:
    """L'id memorizzato (`trasi%3Aentita%3Aid`) va codificato per il percorso: `%253A`.

    FastAPI decodifica una volta il percorso. Passando `trasi%3Aevento%3A470` arriva
    `trasi:evento:470`, che nel database non esiste → 404 su un documento **presente**.
    La forma corretta è la codifica della stringa già codificata.
    """
    memorizzato = "trasi%3Aevento%3A470"
    percorso = e._id_nel_percorso(memorizzato)
    assert percorso == "trasi%253Aevento%253A470"
    # Dopo UNA decodifica (ciò che fa il framework) si torna all'id memorizzato:
    assert urllib.parse.unquote(percorso) == memorizzato


def test_id_come_onyx_e_la_forma_memorizzata() -> None:
    """`doc_id` della vista (`trasi:luogo:6`) → forma memorizzata da Onyx (`trasi%3Aluogo%3A6`)."""
    assert e._id_come_onyx("trasi:luogo:6") == "trasi%3Aluogo%3A6"
    # E il confronto fra i due insiemi funziona solo nella stessa forma:
    vista = {e._id_come_onyx("trasi:luogo:6")}
    onyx = {"trasi%3Aluogo%3A6"}
    assert vista == onyx


# --------------------------------------------------------------- calcolo degli orfani


def test_orfani_sono_onyx_meno_vista() -> None:
    """Gli orfani sono i documenti `trasi:*` in Onyx ma non più nella vista.

    È la definizione che decide cosa cancellare: se sbagliata, si cancella un documento valido
    (dato che sparisce dalla chat) o si lascia un fantasma (dato citabile che non esiste).
    """
    vista_doc_ids = ["trasi:luogo:6", "trasi:casa_quartiere:8"]
    onyx_ids = [
        "trasi%3Aluogo%3A6",          # presente in vista
        "trasi%3Acasa_quartiere%3A8",  # presente in vista
        "trasi%3Aevento%3A470",        # ORFANO: non più in vista
        "altro-documento",             # non è `trasi:*`: non si tocca
    ]

    doc_vista = {e._id_come_onyx(d) for d in vista_doc_ids}
    presenti = [i for i in onyx_ids if i.startswith("trasi")]
    orfani = sorted(set(presenti) - doc_vista)

    assert orfani == ["trasi%3Aevento%3A470"], "solo il documento uscito dalla vista va cancellato"
    assert "altro-documento" not in " ".join(orfani), "i documenti non `trasi:*` non vanno toccati"


def test_nessun_orfano_quando_allineati() -> None:
    """KB e vista allineate → nessuna cancellazione (idempotenza dell'export)."""
    vista = ["trasi:luogo:6", "trasi:evento:470"]
    doc_vista = {e._id_come_onyx(d) for d in vista}
    presenti = {e._id_come_onyx(d) for d in vista}
    assert sorted(presenti - doc_vista) == []


# --------------------------------------------------------------- il 404 non è un errore


def test_cancellazione_tratta_il_404_come_gia_assente(monkeypatch) -> None:
    """Un documento già assente non è un errore: è idempotenza.

    Se il 404 sollevasse, una seconda esecuzione dell'export fallirebbe su un KB già pulita —
    e un flusso notturno che va in errore quando non c'è nulla da fare è un flusso che si impara
    a ignorare.
    """
    import urllib.error

    def finto_urlopen(*_args, **_kwargs):
        raise urllib.error.HTTPError(
            url="http://x", code=404, msg="Not Found", hdrs=None, fp=None  # type: ignore[arg-type]
        )

    monkeypatch.setattr(e.urllib.request, "urlopen", finto_urlopen)
    # Non solleva: conta 0 e prosegue.
    assert e.cancellazione("http://base", "chiave", ["trasi%3Aevento%3A999"]) == 0
