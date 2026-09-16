"""Test delle scritture mediate: `registra_richiesta`, `proponi_modifica`, `approva_proposta` (B3-SHM-05/06).

Due livelli, per due domande diverse.

1. **Contratto HTTP** (senza database): `dependency_overrides` sostituisce la sessione con una finta e si verifica
   tutto ciò che non dipende dal database — 422 per i campi extra, 422 per `inviata_altrove` senza destinazione, 422
   `dato_personale_sospetto` su `motivazione` **e** su `payload`, forma della risposta 201.
2. **RLS vera** (con database, marcati `live`): le decisioni che il contratto delega al database — 403 «da approvare
   in coda» su una proposta di un'altra Casa, 409 su una proposta scaduta o già decisa, e la prova che
   `proponi_modifica` **non** modifica il dominio. Questi test girano come i ruoli veri del seed: una sessione finta
   non proverebbe nulla sulla RLS, che è l'autorità (§11).
"""

from __future__ import annotations

import asyncio
import json
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

import ambiente

URL = "/v1/u/{email}"
CHIAVE = ambiente.CHIAVE_SHIM or "chiave-di-test"


class SessioneFinta:
    """Una sessione con la stessa superficie di `db.Sessione`, senza database.

    Registra le query eseguite: serve a distinguere «la richiesta è stata rifiutata prima di toccare il database» da
    «la richiesta ha scritto qualcosa». Nei test del filtro anti-PII la differenza è il punto.
    """

    def __init__(self, *, casa_id: int | None = 5, ruolo: str = "casa_sanbao", email: str = ambiente.EMAIL_SANBAO):
        self.casa_id = casa_id
        self.ruolo = ruolo
        self.email = email
        self.eseguite: list[tuple[str, tuple[Any, ...]]] = []
        self.riga_proposta: dict[str, Any] | None = None
        self.righe_modificate = 1
        self.viste: list[str] = []

    async def fetch(self, sql: str, *args: Any) -> list[Any]:
        return []

    async def fetchrow(self, sql: str, *args: Any) -> dict[str, Any] | None:
        self.eseguite.append((sql, args))
        if self.riga_proposta is not None and "FROM trasi.proposta" in sql:
            return self.riga_proposta
        if "INSERT INTO trasi.proposta" in sql:
            return {"id": 4242, "approvatore_ruolo": "at", "casa_id": self.casa_id}
        if "v_oggi_casa" in sql:
            self.viste.append(sql)
            return None
        return None

    async def fetchval(self, sql: str, *args: Any) -> Any:
        self.eseguite.append((sql, args))
        if "INSERT INTO trasi.richiesta" in sql:
            return 777
        if "INSERT INTO trasi.evento" in sql:
            return 888
        return None

    async def execute(self, sql: str, *args: Any) -> str:
        self.eseguite.append((sql, args))
        return f"UPDATE {self.righe_modificate}"


@pytest.fixture
def app_cliente(monkeypatch):
    """`TestClient` sull'app reale, con la sessione sostituita da una finta."""
    ambiente.configura_ambiente()

    from app import main as modulo_main
    from app.db import sessione as dipendenza

    def costruisci(sessione_finta: SessioneFinta) -> TestClient:
        applicazione = modulo_main.crea_app()
        applicazione.dependency_overrides[dipendenza] = lambda: sessione_finta
        return TestClient(applicazione, raise_server_exceptions=False)

    def chiama(email: str = ambiente.EMAIL_SANBAO) -> str:
        return f"/v1/u/{email}"

    costruisci.chiama = chiama  # type: ignore[attr-defined]
    return costruisci


def _intestazioni() -> dict[str, str]:
    return {"X-Trasi-Key": CHIAVE}


# --- `registra_richiesta` -------------------------------------------------------------------------------------


def test_registra_richiesta_salva_la_casa_dell_identita_non_del_corpo(app_cliente):
    """`casa_id` viene dall'identità: il corpo non può indicarne un'altra, perché un campo extra è un 422.

    La prova è nel valore passato alla INSERT: se il corpo riuscisse a imporre una Casa, il primo parametro sarebbe
    quello del corpo.
    """
    sessione_finta = SessioneFinta(casa_id=5)
    client = app_cliente(sessione_finta)

    risposta = client.post(
        f"/v1/u/{ambiente.EMAIL_SANBAO}/registra_richiesta",
        headers=_intestazioni(),
        json={"categoria": "fiscale_isee", "esito": "risolta"},
    )

    assert risposta.status_code == 201
    assert risposta.json() == {"richiesta_id": 777}
    insert = [chiamata for chiamata in sessione_finta.eseguite if "INSERT INTO trasi.richiesta" in chiamata[0]]
    assert insert, "nessuna INSERT eseguita"
    assert insert[0][1][0] == 5, "la Casa deve venire dall'identità (5), non dal corpo"


def test_registra_richiesta_inviata_altrove_senza_destinazione_422(app_cliente):
    """`esito='inviata_altrove'` senza destinazione è una registrazione inutilizzabile: 422, non una riga a metà."""
    sessione_finta = SessioneFinta()
    client = app_cliente(sessione_finta)

    risposta = client.post(
        f"/v1/u/{ambiente.EMAIL_SANBAO}/registra_richiesta",
        headers=_intestazioni(),
        json={"categoria": "fiscale_isee", "esito": "inviata_altrove"},
    )

    assert risposta.status_code == 422
    assert "destinazione" in risposta.json()["detail"]
    assert not [c for c in sessione_finta.eseguite if "INSERT" in c[0]]


def test_registra_richiesta_inviata_altrove_con_nota_201(app_cliente):
    """La destinazione in testo libero è ammessa: `destinazione_nota` esiste per i servizi non censiti."""
    client = app_cliente(SessioneFinta())

    risposta = client.post(
        f"/v1/u/{ambiente.EMAIL_SANBAO}/registra_richiesta",
        headers=_intestazioni(),
        json={
            "categoria": "fiscale_isee",
            "esito": "inviata_altrove",
            "destinazione_nota": "CAF in via Roma, non censito",
        },
    )

    assert risposta.status_code == 201


@pytest.mark.parametrize(
    "campo",
    ["casa_id", "nome_cittadino", "telefono", "cognome", "codice_fiscale", "nome_persona"],
)
def test_registra_richiesta_campo_extra_422(app_cliente, campo):
    """Nessun campo del cittadino è ammesso: `extra="forbid"` risponde 422 e non lo scarta in silenzio."""
    client = app_cliente(SessioneFinta())

    risposta = client.post(
        f"/v1/u/{ambiente.EMAIL_SANBAO}/registra_richiesta",
        headers=_intestazioni(),
        json={"categoria": "orientamento", "esito": "risolta", campo: "x"},
    )

    assert risposta.status_code == 422


def test_registra_richiesta_categoria_fuori_vocabolario_422(app_cliente):
    """La categoria è un vocabolario chiuso del modello dati: un valore fuori elenco è 422, non un errore del DB."""
    client = app_cliente(SessioneFinta())

    risposta = client.post(
        f"/v1/u/{ambiente.EMAIL_SANBAO}/registra_richiesta",
        headers=_intestazioni(),
        json={"categoria": "categoria_inventata", "esito": "risolta"},
    )

    assert risposta.status_code == 422


# --- `proponi_modifica` ---------------------------------------------------------------------------------------


def _proposta(**extra: Any) -> dict[str, Any]:
    """Un corpo valido di `proponi_modifica`, con i campi da variare nel test."""
    corpo = {
        "tipo": "modifica_orari_casa",
        "entita": "casa",
        "entita_id": 5,
        "payload": {"orari": {"lun": ["09:00", "13:00"]}},
        "motivazione": "orario aggiornato dalla segnalazione",
    }
    corpo.update(extra)
    return corpo


def test_proponi_modifica_non_scrive_il_dominio_e_non_sceglie_l_approvatore(app_cliente):
    """La INSERT non passa `approvatore_ruolo`, `stato`, `proposto_da`, `scade_il` né `diff`: li calcola il database.

    È l'invariante di V4 («nessuno si sceglie l'approvatore») e anche l'unica forma che i GRANT colonnari di
    `proposta` permettono: le colonne che lo shim non possiede non possono comparire nella query.
    """
    sessione_finta = SessioneFinta(casa_id=5)
    client = app_cliente(sessione_finta)

    risposta = client.post(
        f"/v1/u/{ambiente.EMAIL_SANBAO}/proponi_modifica", headers=_intestazioni(), json=_proposta()
    )

    assert risposta.status_code == 201
    corpo = risposta.json()
    assert corpo["proposta_id"] == 4242
    assert corpo["approvatore_ruolo"] in ("gestore", "at", "ti")
    assert isinstance(corpo["in_chat"], bool)

    insert = [c for c in sessione_finta.eseguite if "INSERT INTO trasi.proposta" in c[0]]
    assert len(insert) == 1
    sql = insert[0][0]
    # Le colonne vietate sono quelle dell'elenco di INSERT: `approvatore_ruolo` compare solo nel `RETURNING`, che è
    # la lettura del valore calcolato dal database — il contrario di sceglierlo.
    elenco_colonne = sql.split("INSERT INTO trasi.proposta", 1)[1].split(")", 1)[0]
    for vietata in ("approvatore_ruolo", "stato", "proposto_da", "scade_il", "diff"):
        assert vietata not in elenco_colonne, f"la INSERT non deve nominare {vietata}"
    assert "RETURNING id, approvatore_ruolo" in sql
    assert not [c for c in sessione_finta.eseguite if any(
        parola in c[0].upper() for parola in ("INSERT INTO TRASI.LUOGO", "UPDATE TRASI.LUOGO", "INSERT INTO TRASI.SCHEDA", "UPDATE TRASI.SCHEDA")
    )], "lo shim non scrive il dominio"
    corpo_payload = json.loads(insert[0][1][4])
    assert corpo_payload == {"orari": {"lun": ["09:00", "13:00"]}}


def test_proponi_modifica_motivazione_81_char_422(app_cliente):
    """La `motivazione` è limitata a 80 caratteri dal contratto e dal CHECK del database: 81 è 422."""
    client = app_cliente(SessioneFinta())

    risposta = client.post(
        f"/v1/u/{ambiente.EMAIL_SANBAO}/proponi_modifica",
        headers=_intestazioni(),
        json=_proposta(motivazione="a" * 81),
    )

    assert risposta.status_code == 422
    assert risposta.json().get("detail")


def test_proponi_modifica_motivazione_80_char_201(app_cliente):
    """Il confine ammesso: 80 caratteri passano, perché è il limite dichiarato."""
    client = app_cliente(SessioneFinta())

    risposta = client.post(
        f"/v1/u/{ambiente.EMAIL_SANBAO}/proponi_modifica",
        headers=_intestazioni(),
        json=_proposta(motivazione="a" * 80),
    )

    assert risposta.status_code == 201


@pytest.mark.parametrize(
    ("motivazione", "atteso"),
    [
        ("il CAF ha chiuso, scrivere a mario.rossi@example.it", "dato_personale_sospetto"),
        ("richiamare la signora al 333 1234567", "dato_personale_sospetto"),
        ("telefono 0831 123456 per informazioni", "dato_personale_sospetto"),
        ("il codice fiscale RSSMRA80A01H501U non è valido", "dato_personale_sospetto"),
    ],
)
def test_proponi_modifica_dato_personale_sospetto_422(app_cliente, motivazione, atteso):
    """Il filtro anti-PII respinge email, telefoni italiani e codici fiscali nella `motivazione` (V5/§12)."""
    sessione_finta = SessioneFinta()
    client = app_cliente(sessione_finta)

    risposta = client.post(
        f"/v1/u/{ambiente.EMAIL_SANBAO}/proponi_modifica",
        headers=_intestazioni(),
        json=_proposta(motivazione=motivazione),
    )

    assert risposta.status_code == 422
    assert risposta.json()["detail"].startswith(atteso)
    assert not [c for c in sessione_finta.eseguite if "INSERT" in c[0]], "nessuna riga deve essere scritta"


@pytest.mark.parametrize(
    ("campo", "valore"),
    [
        ("indirizzo", "via Roma 1, chiedere di Anna al 340 9988776"),
        ("descrizione", "servizio della sig.ra Rossi (anna.rossi@example.it)"),
        ("nome", "CAF RSSMRA80A01H501U"),
    ],
)
def test_proponi_modifica_dato_personale_nel_payload_422(app_cliente, campo, valore):
    """Il filtro vale anche sul `payload`, non solo sulla `motivazione`: è il presidio esteso di V5.

    Senza questo test, un indirizzo come «via Roma 1, chiedere di Anna al 340 99 88 776» entrerebbe in memoria e
    resterebbe lì: la proposta è ciò che sopravvive alla chat (retention 30 gg, §12).
    """
    sessione_finta = SessioneFinta()
    client = app_cliente(sessione_finta)

    risposta = client.post(
        f"/v1/u/{ambiente.EMAIL_SANBAO}/proponi_modifica",
        headers=_intestazioni(),
        json=_proposta(payload={"nome": "CAF", campo: valore}),
    )

    assert risposta.status_code == 422
    assert risposta.json()["detail"].startswith("dato_personale_sospetto")
    assert not [c for c in sessione_finta.eseguite if "INSERT" in c[0]]


def test_proponi_modifica_payload_con_campo_fuori_elenco_422(app_cliente):
    """Il `payload` è un elenco chiuso di colonne: nessun campo libero, quindi nessun posto per dati personali."""
    client = app_cliente(SessioneFinta())

    risposta = client.post(
        f"/v1/u/{ambiente.EMAIL_SANBAO}/proponi_modifica",
        headers=_intestazioni(),
        json=_proposta(payload={"nome": "CAF", "note_libere": "qualunque testo"}),
    )

    assert risposta.status_code == 422


def test_proponi_modifica_entita_fuori_dominio_422(app_cliente):
    """L'entità è una tabella del dominio: un valore fuori elenco è 422 con l'elenco ammesso nel messaggio."""
    client = app_cliente(SessioneFinta())

    risposta = client.post(
        f"/v1/u/{ambiente.EMAIL_SANBAO}/proponi_modifica",
        headers=_intestazioni(),
        json=_proposta(entita="clienti"),
    )

    assert risposta.status_code == 422
    assert "casa" in risposta.json()["detail"] and "luogo" in risposta.json()["detail"]


def test_proponi_modifica_in_chat_dipende_dalla_casa_della_proposta(app_cliente):
    """`in_chat` è vero solo quando la proposta riguarda la Casa dell'operatore ed è di competenza del gestore.

    Il contratto definisce `in_chat` come «riguarda la Casa dell'operatore»: una proposta per un'altra Casa va in
    coda, anche se l'operatore l'ha formulata.
    """
    from app import scritture

    sessione = SessioneFinta(casa_id=5)
    assert scritture._in_chat("gestore", 5, sessione) is True
    assert scritture._in_chat("gestore", 8, sessione) is False
    assert scritture._in_chat("at", 5, sessione) is False
    assert scritture._in_chat("ti", 5, sessione) is False
    assert scritture._in_chat("gestore", None, sessione) is False


# --- Test con la RLS vera -------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _db() -> bool:
    """Vero se il database è raggiungibile: i test `live` si saltano, non falliscono."""
    return ambiente.dsn_disponibile()


@pytest.fixture
def client_reale(_db):
    """`TestClient` sull'app reale **con il database vero**: nessun override della sessione."""
    if not _db:
        pytest.skip(f"database non raggiungibile ({ambiente.dsn_test()})")
    ambiente.configura_ambiente()
    from app.main import crea_app

    with TestClient(crea_app(), raise_server_exceptions=False) as c:
        yield c


def _post(client: TestClient, email: str, operation: str, corpo: dict[str, Any]) -> Any:
    return client.post(f"/v1/u/{email}/{operation}", headers=_intestazioni(), json=corpo)


@pytest.mark.live
def test_proponi_modifica_crea_proposta_con_approvatore_calcolato_dal_db(client_reale):
    """Con il database vero, l'`approvatore_ruolo` lo decide `approvatore_default()`, e la risposta lo riporta.

    `chiudi_luogo` non è nel gruppo «della Casa»: la funzione del database assegna `at`, cioè la rete. La risposta
    201 deve dichiararlo — è l'informazione che l'assistente usa per dire all'operatore chi approverà.
    """
    if not client_reale:
        pytest.skip("database non raggiungibile")

    risposta = _post(
        client_reale,
        ambiente.EMAIL_SANBAO,
        "proponi_modifica",
        {
            "tipo": "chiudi_luogo",
            "entita": "luogo",
            "entita_id": 6,
            "payload": {"chiuso_il": "2026-09-15"},
            "motivazione": "chiuso secondo la segnalazione",
        },
    )

    assert risposta.status_code == 201, risposta.text
    corpo = risposta.json()
    assert corpo["approvatore_ruolo"] == "at"
    assert corpo["in_chat"] is False  # la rete approva, non il gestore della Casa

    async def verifica() -> None:
        conn = await ambiente.connessione()
        try:
            riga = await conn.fetchrow(
                "SELECT stato, proposto_da, casa_id, diff FROM trasi.proposta WHERE id = $1",
                corpo["proposta_id"],
            )
            assert riga["stato"] == "proposta"
            assert riga["proposto_da"] == "casa_sanbao"
            assert riga["diff"] is not None
            # La proposta NON ha toccato il dominio: il luogo è ancora aperto.
            chiuso = await conn.fetchval("SELECT chiuso_il FROM trasi.luogo WHERE id = 6")
            assert chiuso is None, "lo shim non deve modificare il dominio"
            await ambiente.pulisci(corpo["proposta_id"])
        finally:
            await conn.close()

    asyncio.run(verifica())


@pytest.mark.live
def test_approva_proposta_altra_casa_403_da_approvare_in_coda(client_reale):
    """Una proposta di un'altra Casa non è nella coda di questo ruolo: la RLS fa 0 righe → 403 «da approvare in coda».

    Le fixture della proposta sono create **come `rete`**, cioè da un'identità diversa da quella che poi decide:
    altrimenti la RESTRICTIVE `no_self_approve` renderebbe il test vero per la ragione sbagliata.
    """
    if not client_reale:
        pytest.skip("database non raggiungibile")

    async def prepara() -> tuple[int, int]:
        conn = await ambiente.connessione(ruolo="rete")
        try:
            altra = await ambiente.crea_proposta(
                conn, casa_slug=ambiente.SLUG_BOZZANO, tipo="modifica_orari_casa"
            )
            propria = await ambiente.crea_proposta(
                conn, casa_slug=ambiente.SLUG_SANBAO, tipo="modifica_orari_casa"
            )
            return altra, propria
        finally:
            await conn.close()

    altra, propria = asyncio.run(prepara())
    try:
        risposta = _post(
            client_reale,
            ambiente.EMAIL_SANBAO,
            "approva_proposta",
            {"proposta_id": altra, "decisione": "approva"},
        )
        assert risposta.status_code == 403
        assert risposta.json() == {"detail": "da approvare in coda"}

        # La stessa richiesta sulla propria Casa riesce: il 403 di sopra è la RLS, non un guasto.
        risposta = _post(
            client_reale,
            ambiente.EMAIL_SANBAO,
            "approva_proposta",
            {"proposta_id": propria, "decisione": "approva", "nota": "verificato in chat"},
        )
        assert risposta.status_code == 200, risposta.text
        assert risposta.json() == {"proposta_id": propria, "stato": "approvata"}

        async def stati() -> tuple[str, str]:
            conn = await ambiente.connessione()
            try:
                return (
                    await conn.fetchval("SELECT stato::text FROM trasi.proposta WHERE id = $1", altra),
                    await conn.fetchval("SELECT stato::text FROM trasi.proposta WHERE id = $1", propria),
                )
            finally:
                await conn.close()

        stato_altra, stato_propria = asyncio.run(stati())
        assert stato_altra == "proposta", "la proposta di un'altra Casa resta in coda, intatta"
        assert stato_propria == "approvata"
    finally:
        asyncio.run(_ripulisci(altra, propria))


@pytest.mark.live
def test_approva_proposta_scaduta_409(client_reale):
    """Una proposta oltre `scade_il` è 409, non 403: è «non più decidibile», e il contratto la distingue."""
    if not client_reale:
        pytest.skip("database non raggiungibile")

    async def prepara() -> int:
        conn = await ambiente.connessione(ruolo="rete")
        try:
            return await ambiente.crea_proposta(
                conn,
                casa_slug=ambiente.SLUG_SANBAO,
                tipo="modifica_orari_casa",
                scade_il=date(2020, 1, 1),
            )
        finally:
            await conn.close()

    scaduta = asyncio.run(prepara())
    try:
        risposta = _post(
            client_reale,
            ambiente.EMAIL_SANBAO,
            "approva_proposta",
            {"proposta_id": scaduta, "decisione": "approva"},
        )
        assert risposta.status_code == 409
        assert "scaduta" in risposta.json()["detail"]

        async def stato() -> str:
            conn = await ambiente.connessione()
            try:
                return await conn.fetchval("SELECT stato::text FROM trasi.proposta WHERE id = $1", scaduta)
            finally:
                await conn.close()

        assert asyncio.run(stato()) == "proposta", "una richiesta rifiutata non deve cambiare lo stato"
    finally:
        asyncio.run(_ripulisci(scaduta))


@pytest.mark.live
def test_approva_proposta_gia_decisa_409(client_reale):
    """Decidere due volte la stessa proposta è 409: `proposta_01_transition_tg` non ammette il ritorno indietro."""
    if not client_reale:
        pytest.skip("database non raggiungibile")

    async def prepara() -> int:
        conn = await ambiente.connessione(ruolo="rete")
        try:
            return await ambiente.crea_proposta(
                conn, casa_slug=ambiente.SLUG_SANBAO, tipo="modifica_orari_casa"
            )
        finally:
            await conn.close()

    proposta = asyncio.run(prepara())
    try:
        prima = _post(
            client_reale, ambiente.EMAIL_SANBAO, "approva_proposta", {"proposta_id": proposta, "decisione": "approva"}
        )
        assert prima.status_code == 200, prima.text

        seconda = _post(
            client_reale, ambiente.EMAIL_SANBAO, "approva_proposta", {"proposta_id": proposta, "decisione": "rifiuta"}
        )
        assert seconda.status_code == 409
    finally:
        asyncio.run(_ripulisci(proposta))


@pytest.mark.live
def test_registra_richiesta_scrive_nella_casa_dell_operatore(client_reale):
    """L'INSERT vero finisce nella Casa dell'identità: `rich_ins_casa` accetta solo la riga della Casa corrente."""
    if not client_reale:
        pytest.skip("database non raggiungibile")

    risposta = _post(
        client_reale,
        ambiente.EMAIL_SANBAO,
        "registra_richiesta",
        {"categoria": "orientamento", "esito": "risolta"},
    )
    assert risposta.status_code == 201, risposta.text
    richiesta_id = risposta.json()["richiesta_id"]

    async def verifica() -> None:
        # La lettura avviene **come la Casa**: `richiesta` ha la policy `rich_sel` per i ruoli `casa_*` e `rete`, ma
        # non per `shim_rw` — che, senza `SET ROLE`, non vede alcuna riga. È la segregazione voluta: il registro si
        # legge dal ruolo della Casa, non dalla connessione di servizio.
        conn = await ambiente.connessione(ruolo="casa_sanbao")
        try:
            riga = await conn.fetchrow(
                "SELECT casa_id, categoria, esito, destinazione_id FROM trasi.richiesta WHERE id = $1",
                richiesta_id,
            )
            assert riga is not None, "la richiesta registrata non è visibile al ruolo della Casa"
            assert riga["casa_id"] == await ambiente.id_casa(ambiente.SLUG_SANBAO)
            assert riga["categoria"] == "orientamento"
            assert riga["destinazione_id"] is None
            await conn.execute("DELETE FROM trasi.richiesta WHERE id = $1", richiesta_id)
        finally:
            await conn.close()

    asyncio.run(verifica())


@pytest.mark.live
def test_registra_richiesta_non_scrive_su_altra_casa(client_reale):
    """Il corpo non può imporre `casa_id`: il tentativo è un 422 e nessuna riga viene scritta per un'altra Casa."""
    if not client_reale:
        pytest.skip("database non raggiungibile")

    async def conta() -> int:
        # `rete` è l'unico ruolo che vede le richieste di tutte le Case (`rich_sel`): il conteggio deve guardare
        # Bozzano, e come `casa_sanbao` quelle righe sarebbero invisibili — un test che non vedesse nulla passerebbe
        # per la ragione sbagliata.
        conn = await ambiente.connessione(ruolo="rete")
        try:
            return await conn.fetchval(
                "SELECT count(*) FROM trasi.richiesta WHERE casa_id = $1",
                await ambiente.id_casa(ambiente.SLUG_BOZZANO),
            )
        finally:
            await conn.close()

    prima = asyncio.run(conta())
    risposta = _post(
        client_reale,
        ambiente.EMAIL_SANBAO,
        "registra_richiesta",
        {"categoria": "orientamento", "esito": "risolta", "casa_id": 8},
    )

    assert risposta.status_code == 422
    assert asyncio.run(conta()) == prima


async def _ripulisci(*ids: int) -> None:
    """Rimuove le proposte di prova (via connessione amministrativa: nessun ruolo applicativo ha `DELETE`)."""
    await ambiente.pulisci(*ids)


# --- `crea_evento` --------------------------------------------------------------------------------------------


def _evento(**extra: Any) -> dict[str, Any]:
    """Un corpo valido di `crea_evento`, con i campi da variare nel test."""
    corpo = {
        "titolo": "Prove generali del coro",
        "inizio": "2026-10-20T18:30:00+02:00",
        "fine": "2026-10-20T20:00:00+02:00",
        "luogo_testo": "Sala grande",
    }
    corpo.update(extra)
    return corpo


def test_crea_evento_salva_la_casa_dell_identita(app_cliente):
    """`casa_id` viene dall'identità: la INSERT passa il `casa_id` della sessione, non un valore del corpo."""
    sessione_finta = SessioneFinta(casa_id=5)
    client = app_cliente(sessione_finta)

    risposta = client.post(
        f"/v1/u/{ambiente.EMAIL_SANBAO}/eventi", headers=_intestazioni(), json=_evento()
    )

    assert risposta.status_code == 201
    corpo = risposta.json()
    assert corpo["evento_id"] == 888
    assert corpo["badge"].startswith("[KB · ")
    insert = [c for c in sessione_finta.eseguite if "INSERT INTO trasi.evento" in c[0]]
    assert insert, "nessuna INSERT eseguita"
    assert insert[0][1][0] == 5, "la Casa deve venire dall'identità (5), non dal corpo"


@pytest.mark.parametrize("campo", ["casa_id", "fonte_id", "uid_ical", "annullato", "note_interne"])
def test_crea_evento_campo_extra_422(app_cliente, campo):
    """Nessun campo fuori dal modello è ammesso: `extra="forbid"` respinge anche `casa_id` (mai dal corpo)."""
    client = app_cliente(SessioneFinta())

    risposta = client.post(
        f"/v1/u/{ambiente.EMAIL_SANBAO}/eventi",
        headers=_intestazioni(),
        json=_evento(**{campo: "x"}),
    )

    assert risposta.status_code == 422


def test_crea_evento_fine_prima_dell_inizio_422(app_cliente):
    """`fine` precedente a `inizio` viola il CHECK `evento_fine_dopo_inizio`: il contratto lo dichiara 422."""
    sessione_finta = SessioneFinta()
    client = app_cliente(sessione_finta)

    risposta = client.post(
        f"/v1/u/{ambiente.EMAIL_SANBAO}/eventi",
        headers=_intestazioni(),
        json=_evento(fine="2026-10-20T17:00:00+02:00"),
    )

    assert risposta.status_code == 422
    assert "fine" in risposta.json()["detail"]
    assert not [c for c in sessione_finta.eseguite if "INSERT" in c[0]]


def test_crea_evento_dato_personale_nella_descrizione_422(app_cliente):
    """Il filtro anti-PII (V5) vale sui campi testuali dell'evento: un telefono nella descrizione è 422."""
    sessione_finta = SessioneFinta()
    client = app_cliente(sessione_finta)

    risposta = client.post(
        f"/v1/u/{ambiente.EMAIL_SANBAO}/eventi",
        headers=_intestazioni(),
        json=_evento(descrizione="info: chiamare il 340 1234567"),
    )

    assert risposta.status_code == 422
    assert risposta.json()["detail"].startswith("dato_personale_sospetto")
    assert not [c for c in sessione_finta.eseguite if "INSERT" in c[0]]


def test_crea_evento_ruolo_senza_casa_403(app_cliente):
    """Chi non è legato a una Casa (`rete`) non può creare un evento: non esiste una Casa a cui assegnarlo."""
    sessione_finta = SessioneFinta(casa_id=None, ruolo="rete")
    client = app_cliente(sessione_finta)

    risposta = client.post(
        f"/v1/u/{ambiente.EMAIL_RETE}/eventi", headers=_intestazioni(), json=_evento()
    )

    assert risposta.status_code == 403
    assert not [c for c in sessione_finta.eseguite if "INSERT" in c[0]]


@pytest.mark.live
def test_crea_evento_scrive_l_evento_e_lo_ritrova_in_eventi_oggi(client_reale):
    """Opzione A: l'evento creato è subito leggibile da `eventi_oggi`, senza passare da proposta/approvazione.

    È il criterio osservabile della user story: «una volta creato, l'operatore può chiedere subito se esiste». La
    data è nel futuro per non dipendere da eventi reali; la riga è rimossa alla fine via connessione amministrativa
    (nessun ruolo applicativo ha DELETE sul dominio, V4 resta intatto sulle cancellazioni).
    """
    if not client_reale:
        pytest.skip("database non raggiungibile")

    inizio = "2026-12-15T18:30:00+01:00"
    titolo = "Evento di prova crea_evento (rimosso dal test)"

    risposta = _post(
        client_reale,
        ambiente.EMAIL_SANBAO,
        "eventi",
        {"titolo": titolo, "inizio": inizio, "luogo_testo": "Sala di prova"},
    )

    assert risposta.status_code == 201
    evento_id = risposta.json()["evento_id"]
    try:
        # La stessa sessione dell'operatore rilegge il proprio calendario: RLS vera, nessun trucco.
        lettura = client_reale.get(
            f"/v1/u/{ambiente.EMAIL_SANBAO}/eventi_oggi?casa=san-bao&data=2026-12-15",
            headers=_intestazioni(),
        )
        assert lettura.status_code == 200
        eventi = lettura.json()["eventi"]
        assert [e["titolo"] for e in eventi] == [titolo]
        assert eventi[0]["provenienza"] == "kb"

        # L'audit non attribuisce la scrittura umana a una fonte automatica: nessuna riga `ical_upsert`.
        async def audit_onesto() -> bool:
            conn = await ambiente.connessione_amministratore()
            try:
                return not await conn.fetchval(
                    """
                    SELECT EXISTS (
                      SELECT 1 FROM trasi.audit
                      WHERE azione = 'ical_upsert' AND entita = 'evento' AND entita_id = $1
                    )
                    """,
                    evento_id,
                )
            finally:
                await conn.close()

        assert asyncio.run(audit_onesto()), "l'evento manuale è registrato come upsert iCal (provenienza falsificata)"
    finally:
        asyncio.run(ambiente.pulisci_eventi(evento_id))
