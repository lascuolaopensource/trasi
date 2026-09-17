"""`GET /op/report`, `/op/report/{id}`, `/op/report/{id}/export` — il report mensile nell'area operatore (P2.2, P2.3).

**Live per necessità.** Il report è una riga di `trasi.report` scritta dal ciclo mensile e letta sotto la RLS della
Casa (`rep_sel`, db/024): provare l'endpoint su un doppio verificherebbe il doppio, non la regola «una Casa legge il
proprio report, non quello di un'altra». La fixture scrive un report di prova per un mese lontano (2019-12), come
farebbe il flusso (`generato_da='automazioni'`), e lo rimuove alla fine.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient

import ambiente

MESE_PROVA = "2019-12-01"
CONTENUTI_PROVA = {
    "richieste": 12,
    "senza_risposta": 1,
    "per_categoria_esito": [
        {"categoria": "fiscale_isee", "esito": "risolta", "n": "7"},
        {"categoria": "abitare", "esito": "inviata_altrove", "n": "<5"},
    ],
    "proposte_in_attesa": 2,
    "proposte_applicate": 1,
    "schede_in_scadenza": 0,
}


def _intestazioni() -> dict[str, str]:
    return {"X-Trasi-Key": ambiente.CHIAVE_SHIM or "chiave-di-test"}


def _password_di(slug: str) -> str:
    return slug.replace("-", "") + "2026!"


async def _crea_report(slug: str) -> int:
    conn = await ambiente.connessione_amministratore()
    try:
        return await conn.fetchval(
            """
            INSERT INTO trasi.report (casa_id, mese, ambito, contenuti, csv)
            SELECT c.id, $1::date, 'casa', $2::jsonb, 'casa,categoria,esito,n\n' FROM trasi.casa c WHERE c.slug = $3
            RETURNING id
            """,
            __import__("datetime").date.fromisoformat(MESE_PROVA),
            json.dumps(CONTENUTI_PROVA),
            slug,
        )
    finally:
        await conn.close()


async def _rimuovi_report(ids: list[int]) -> None:
    conn = await ambiente.connessione_amministratore()
    try:
        await conn.execute("DELETE FROM trasi.report WHERE id = ANY($1::bigint[])", ids)
    finally:
        await conn.close()


@pytest.fixture
def accedi():
    if not ambiente.dsn_disponibile():
        pytest.skip(f"database non raggiungibile ({ambiente.dsn_test()})")
    ambiente.configura_ambiente()

    from app.main import crea_app

    with ExitStack() as pila:
        client = pila.enter_context(TestClient(crea_app(), raise_server_exceptions=False))
        pila.callback(lambda: client.post("/logout", headers=_intestazioni()))

        def accedi_come(slug: str) -> TestClient:
            client.post("/logout", headers=_intestazioni())
            risposta = client.post("/login", json={"casa": slug, "password": _password_di(slug)})
            assert risposta.status_code == 200, f"login {slug}: {risposta.status_code} {risposta.text}"
            return client

        yield accedi_come


@pytest.fixture
def report_di_prova():
    """Un report per San Bao e uno per Bozzano nel mese di prova; rimossi alla fine."""
    if not ambiente.dsn_disponibile():
        pytest.skip("database non raggiungibile")
    ids = {"san-bao": asyncio.run(_crea_report("san-bao")), "bozzano": asyncio.run(_crea_report("bozzano"))}
    try:
        yield ids
    finally:
        asyncio.run(_rimuovi_report(list(ids.values())))


@pytest.mark.live
def test_la_casa_legge_il_proprio_report_e_non_quello_altrui(accedi, report_di_prova):
    """T14 — l'elenco di San Bao porta il **suo** report del mese di prova e non quello di Bozzano; il dettaglio del
    report altrui è 404 (la RLS non lo rende leggibile: «non esiste» e «non è tuo» sono la stessa risposta)."""
    client = accedi("san-bao")
    elenco = client.get("/op/report")
    assert elenco.status_code == 200, elenco.text
    del_mese = [r for r in elenco.json()["report"] if r["mese"] == MESE_PROVA]
    assert [r["casa_slug"] for r in del_mese] == ["san-bao"]
    voce = del_mese[0]
    assert voce["mese_testo"] == "dicembre 2019"
    assert voce["richieste"] == 12 and voce["senza_risposta"] == 1
    assert voce["export_url"] == f"/op/report/{report_di_prova['san-bao']}/export"

    dettaglio = client.get(f"/op/report/{report_di_prova['san-bao']}")
    assert dettaglio.status_code == 200
    celle = dettaglio.json()["per_categoria_esito"]
    assert celle[0] == {"categoria": "fiscale_isee", "categoria_testo": "Fiscale e ISEE", "esito": "risolta",
                        "esito_testo": "risolte", "n": "7"}
    assert celle[1]["n"] == "<5", "la cella mascherata resta mascherata"

    altrui = client.get(f"/op/report/{report_di_prova['bozzano']}")
    assert altrui.status_code == 404
    assert client.get(f"/op/report/{report_di_prova['bozzano']}/export").status_code == 404


@pytest.mark.live
def test_export_e_un_file_html_scaricabile_autonomo_e_senza_moduli(accedi, report_di_prova):
    """T15 — l'export è `.html` in download (MIME `text/html`, `Content-Disposition: attachment` con nome
    `report_<slug>_<AAAA-MM>.html`), contiene i numeri del report con le parole del dominio e nessun `<form>`."""
    client = accedi("san-bao")
    risposta = client.get(f"/op/report/{report_di_prova['san-bao']}/export")

    assert risposta.status_code == 200
    assert risposta.headers["content-type"].startswith("text/html")
    assert risposta.headers["content-disposition"] == 'attachment; filename="report_san-bao_2019-12.html"'
    testo = risposta.text
    assert testo.startswith("<!DOCTYPE html>")
    assert "Report mensile — San Bao — dicembre 2019" in testo
    assert "Fiscale e ISEE" in testo and "&lt;5" in testo and ">12<" in testo
    assert "<form" not in testo and "<input" not in testo and "<script" not in testo
    assert "http://" not in testo and "https://" not in testo, "documento autonomo: nessun asset esterno"


@pytest.mark.live
def test_senza_sessione_il_report_non_si_legge(accedi):
    """Il canale è quello dell'operatore: senza cookie di sessione l'elenco è 401, non una lista vuota."""
    client = accedi("san-bao")
    client.post("/logout", headers=_intestazioni())
    assert client.get("/op/report").status_code == 401
