"""Attrezzoteca dalla chat Onyx: `salva_dato` con `entita="oggetto"` e `cerca_oggetto` (decisione 2026-09-18).

Due gruppi, come `test_scritture.py`:

1. **Validazione senza database**: il corpo di `salva_dato` per un oggetto — cosa è obbligatorio alla creazione,
   cosa è ammesso solo con `id`, quali campi delle altre entità sono un 422 e non un campo ignorato, il filtro
   anti-PII sulla descrizione.
2. **RLS vera** (`live`): San Bao crea un oggetto → `cerca_oggetto` lo trova (dalla stessa Casa, da un'altra Casa,
   dalla rete) e `/op/attrezzoteca` (cookie) lo mostra; un'altra Casa **non** lo modifica (403 deciso dal database:
   `ogg_upd_casa` rende l'UPDATE «0 righe»); il ritiro (`attivo=false`) lo toglie dall'inventario; `rete` non
   scrive; la scrittura diretta della propria Casa non compare in `v_scritture_senza_audit`.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient

import ambiente
from test_scritture import SessioneFinta, _db, _intestazioni, _post, app_cliente, client_reale  # noqa: F401

EMAIL_POP = "op.pop@trasi.local"


def _salva(client: TestClient, corpo: dict[str, Any], email: str = ambiente.EMAIL_SANBAO):
    return _post(client, email, "salva_dato", corpo)


def _cerca(client: TestClient, query: str, email: str = ambiente.EMAIL_SANBAO):
    return client.get(f"/v1/u/{email}/cerca_oggetto?{query}", headers=_intestazioni())


# --- validazione: 422 parlanti, nessuna scrittura ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("corpo", "frammento"),
    [
        pytest.param({"entita": "oggetto", "quantita": 5}, "nome è obbligatorio", id="senza_nome"),
        pytest.param({"entita": "oggetto", "nome": "sedie pieghevoli"}, "quantita è obbligatoria", id="senza_quantita"),
        pytest.param({"entita": "oggetto", "nome": "sedie pieghevoli", "quantita": 0}, "quantita", id="quantita_zero"),
        pytest.param({"entita": "oggetto", "nome": "sedie pieghevoli", "quantita": 5, "attivo": False},
                     "attivo si usa con id", id="ritiro_senza_id"),
        pytest.param({"entita": "oggetto", "nome": "sedie pieghevoli", "quantita": 5, "titolo": "Sedie"},
                     "accetta solo nome", id="titolo_di_scheda"),
        pytest.param({"entita": "oggetto", "nome": "sedie pieghevoli", "quantita": 5, "consenso": True},
                     "accetta solo nome", id="consenso_di_persona"),
        pytest.param({"entita": "oggetto", "nome": "sedie pieghevoli", "quantita": 5, "condizione": "rotto"},
                     "condizione", id="condizione_fuori_vocabolario"),
        pytest.param({"entita": "scheda_servizio", "titolo": "Scheda", "quantita": 3},
                     "si applicano solo a «oggetto»", id="quantita_su_scheda"),
    ],
)
def test_salva_dato_oggetto_corpo_non_ammesso_422(app_cliente, corpo, frammento):
    """Un corpo sbagliato è un 422 che dice cosa manca o cosa non c'entra — mai un 500 né un campo ignorato."""
    sessione_finta = SessioneFinta()
    client = app_cliente(sessione_finta)

    risposta = _salva(client, corpo)

    assert risposta.status_code == 422, risposta.text
    assert frammento in risposta.json()["detail"]
    assert not [c for c in sessione_finta.eseguite if "INSERT" in c[0] or "UPDATE" in c[0]]


def test_salva_dato_oggetto_dato_personale_nella_descrizione_422(app_cliente):
    """Il filtro anti-PII (V5) vale anche sull'inventario: un telefono nella descrizione è 422, prima del database."""
    sessione_finta = SessioneFinta()
    client = app_cliente(sessione_finta)

    risposta = _salva(client, {"entita": "oggetto", "nome": "proiettore", "quantita": 1,
                               "descrizione": "chiedere a Mario, 333 1234567"})

    assert risposta.status_code == 422
    assert risposta.json()["detail"].startswith("dato_personale_sospetto")
    assert not [c for c in sessione_finta.eseguite if "INSERT" in c[0]]


def test_salva_dato_oggetto_inserisce_nella_casa_dell_identita(app_cliente):
    """L'INSERT scrive `casa_id` dell'identità e le sole colonne di `COLONNE_DIRETTE["oggetto"]`; la risposta dichiara l'entità."""
    sessione_finta = SessioneFinta(casa_id=5)

    async def fetchval(sql: str, *args: Any) -> Any:
        sessione_finta.eseguite.append((sql, args))
        return 4321 if "INSERT INTO trasi.oggetto" in sql else None

    sessione_finta.fetchval = fetchval  # type: ignore[method-assign]
    client = app_cliente(sessione_finta)

    risposta = _salva(client, {"entita": "oggetto", "nome": "sedie pieghevoli", "quantita": 5, "condizione": "integro"})

    assert risposta.status_code == 201, risposta.text
    assert risposta.json() == {"id": 4321, "entita": "oggetto", "creato": True}
    insert = [c for c in sessione_finta.eseguite if "INSERT INTO trasi.oggetto" in c[0]]
    assert len(insert) == 1
    sql, argomenti = insert[0]
    assert "casa_id" in sql and argomenti[0] == 5, "la Casa viene dall'identità"
    assert "fonte_id" not in sql and "affidabilita" not in sql


def test_cerca_oggetto_casa_inesistente_404(app_cliente):
    """Una Casa che non esiste è 404 (vocabolario chiuso), non un inventario vuoto spacciato per «niente da vedere»."""
    client = app_cliente(SessioneFinta())

    risposta = _cerca(client, "casa=casa-che-non-esiste")

    assert risposta.status_code == 404
    assert "casa non trovata" in risposta.json()["detail"]


def test_cerca_oggetto_senza_corrispondenze_200_lista_vuota(app_cliente):
    """Nessun oggetto è una risposta valida (`items: []`), come per `cerca_luogo`."""
    client = app_cliente(SessioneFinta())

    risposta = _cerca(client, "q=zzz")

    assert risposta.status_code == 200
    assert risposta.json() == {"items": []}


# --- RLS vera: il ciclo completo dalla creazione al ritiro -------------------------------------------------------


@pytest.mark.live
def test_attrezzoteca_in_chat_ciclo_completo(client_reale):
    """San Bao crea → tutti leggono (chat e portale) → Pop non modifica (403 del DB) → San Bao ritira → sparisce.

    La prova della RLS è il 403 di `op.pop` su un oggetto che **esiste** ed è visibile: `ogg_upd_casa` (USING
    `casa_id = casa_corrente()`) rende l'UPDATE «0 righe», che lo shim traduce nel 403 «riga non appartiene alla
    Casa dell'operatore» — la decisione è del database, lo shim la riporta. `rete` non ha il privilegio: 403.
    """
    if not client_reale:
        pytest.skip("database non raggiungibile")

    nome = "Sedie pieghevoli (prova attrezzoteca chat, rimosse dal test)"
    creazione = _salva(client_reale, {"entita": "oggetto", "nome": nome, "quantita": 5,
                                      "condizione": "integro", "tipo": "arredo"})
    assert creazione.status_code == 201, creazione.text
    assert creazione.json()["entita"] == "oggetto" and creazione.json()["creato"] is True
    oggetto_id = creazione.json()["id"]
    try:
        # La chat della stessa Casa lo trova, con Casa e disponibilità.
        propria = _cerca(client_reale, f"q=pieghevoli&casa={ambiente.SLUG_SANBAO}")
        assert propria.status_code == 200, propria.text
        trovati = [i for i in propria.json()["items"] if i["oggetto_id"] == oggetto_id]
        assert len(trovati) == 1
        assert trovati[0]["casa"] == ambiente.SLUG_SANBAO and trovati[0]["casa_nome"]
        assert trovati[0]["quantita"] == 5 and trovati[0]["quantita_disponibile"] == 5
        assert trovati[0]["tipo"] == "arredo" and trovati[0]["condizione"] == "integro"
        assert trovati[0]["badge"]

        # Un'altra Casa e la rete lo trovano (l'inventario è della rete): per slug, per nome, senza filtro.
        for email, query in ((EMAIL_POP, "q=pieghevoli"), (ambiente.EMAIL_RETE, "q=pieghevoli&casa=San%20Bao")):
            altrui = _cerca(client_reale, query, email=email)
            assert altrui.status_code == 200, altrui.text
            assert oggetto_id in [i["oggetto_id"] for i in altrui.json()["items"]], (email, query)

        # Il portale (cookie della stessa Casa) legge la stessa query.
        accesso = client_reale.post("/login", json={"casa": ambiente.SLUG_SANBAO,
                                                    "password": ambiente.SLUG_SANBAO.replace("-", "") + "2026!"})
        assert accesso.status_code == 200, accesso.text
        portale = client_reale.get("/op/attrezzoteca?q=pieghevoli")
        assert portale.status_code == 200, portale.text
        assert oggetto_id in [i["oggetto_id"] for i in portale.json()["items"]]
        client_reale.post("/logout")

        # Pop non modifica l'oggetto di San Bao: la RLS lo nasconde all'UPDATE → 403 parlante.
        altrui_scrive = _salva(client_reale, {"entita": "oggetto", "id": oggetto_id, "quantita": 3}, email=EMAIL_POP)
        assert altrui_scrive.status_code == 403, altrui_scrive.text
        assert "non appartiene alla Casa" in altrui_scrive.json()["detail"]

        # La rete non scrive l'inventario (nessun privilegio: 403).
        rete_scrive = _salva(client_reale, {"entita": "oggetto", "nome": "Oggetto via rete", "quantita": 1},
                             email=ambiente.EMAIL_RETE)
        assert rete_scrive.status_code == 403, rete_scrive.text

        # San Bao corregge la quantità, poi ritira: l'oggetto esce dall'inventario (la vista filtra `attivo`).
        correzione = _salva(client_reale, {"entita": "oggetto", "id": oggetto_id, "quantita": 4})
        assert correzione.status_code == 201, correzione.text
        assert correzione.json() == {"id": oggetto_id, "entita": "oggetto", "creato": False}
        dopo = _cerca(client_reale, f"q=pieghevoli&casa={ambiente.SLUG_SANBAO}")
        assert [i["quantita"] for i in dopo.json()["items"] if i["oggetto_id"] == oggetto_id] == [4]

        ritiro = _salva(client_reale, {"entita": "oggetto", "id": oggetto_id, "attivo": False})
        assert ritiro.status_code == 201, ritiro.text
        sparito = _cerca(client_reale, "q=pieghevoli", email=EMAIL_POP)
        assert oggetto_id not in [i["oggetto_id"] for i in sparito.json()["items"]]

        # La scrittura diretta della propria Casa non è una violazione di V4.
        async def violazioni() -> int:
            conn = await ambiente.connessione_amministratore()
            try:
                riga = await conn.fetchrow(
                    "SELECT count(*) AS n, bool_and(attivo = false) AS ritirato FROM trasi.v_scritture_senza_audit v "
                    "JOIN trasi.oggetto o ON o.id = v.entita_id WHERE v.entita = 'oggetto' AND o.id = $1",
                    oggetto_id,
                )
                ritirato = await conn.fetchval("SELECT attivo FROM trasi.oggetto WHERE id = $1", oggetto_id)
                assert ritirato is False, "il ritiro è attivo=false, la riga resta (mai DELETE)"
                return riga["n"]
            finally:
                await conn.close()

        assert asyncio.run(violazioni()) == 0
    finally:

        async def ripulisci() -> None:
            conn = await ambiente.connessione_amministratore()
            try:
                await conn.execute("DELETE FROM trasi.oggetto WHERE id = $1", oggetto_id)
            finally:
                await conn.close()

        asyncio.run(ripulisci())
