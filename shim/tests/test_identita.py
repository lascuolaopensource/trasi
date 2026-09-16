"""Identità, chiave e sessione di database (B3-SHM-01).

Cinque comportamenti, ognuno con un esito osservabile:

1. **401** con `X-Trasi-Key` assente o errata, **prima** di toccare il database.
2. **403** con `{"detail": "identità non riconosciuta"}` per un'email non in `identita_onyx`, e **nessuna query
   applicativa eseguita**.
3. Ogni richiesta autenticata esegue `SET LOCAL ROLE <ruolo_db>`: la RLS vede il ruolo della Casa, non `shim_rw`.
4. Il log non contiene il corpo: mai l'email, mai `motivazione`, mai i parametri. Solo
   `ts, method, operationId, status, ms, ruolo`.
5. `_whoami` risponde solo con `SHIM_DEBUG=1`.

La prova del punto 2 è deliberatamente la più forte disponibile: si azzera il pool di connessioni
(`app.db._pool = None`), così **qualunque** query diventerebbe un 503. Se un'email sconosciuta risponde comunque 403
e non 503, allora nessuna query è stata tentata — che è esattamente l'invariante.
"""

import asyncio
import logging
from io import StringIO

import pytest

from attese import (
    DETAIL_CHIAVE_NON_VALIDA,
    DETAIL_IDENTITA_NON_RICONOSCIUTA,
    DETAIL_RUOLO_SENZA_ACCESSO,
    EMAIL_OP_SANBAO,
    EMAIL_SCONOSCIUTA,
    EMAIL_TI,
)

URL = "/v1/u/{email}"
RAGGIO_DI_PROVA = "vicino_a?casa=san-bao&tipo=bar"


def _apri(client, email: str, path: str = RAGGIO_DI_PROVA):
    """Chiama un'operazione all'indirizzo che Onyx compone davvero (`servers[0].url` + path)."""
    return client.get(f"{URL.format(email=email)}/{path}")


def test_chiave_assente_risponde_401(client_anonimo):
    """Senza `X-Trasi-Key` nessuna operazione è accessibile, nemmeno con un'email valida."""
    risposta = _apri(client_anonimo, EMAIL_OP_SANBAO)

    assert risposta.status_code == 401
    assert risposta.json() == {"detail": DETAIL_CHIAVE_NON_VALIDA}


def test_chiave_errata_risponde_401(client):
    """Con una chiave sbagliata la risposta è 401, non 403: l'identità non viene nemmeno cercata."""
    risposta = client.get(
        f"{URL.format(email=EMAIL_OP_SANBAO)}/{RAGGIO_DI_PROVA}", headers={"X-Trasi-Key": "sbagliata"}
    )

    assert risposta.status_code == 401
    assert risposta.json() == {"detail": DETAIL_CHIAVE_NON_VALIDA}


class _Spia:
    """Un finto pool che registra ogni query: serve a provare **cosa** il database ha visto.

    La prova più diretta dell'invariante «nessuna query eseguita» non è un codice di stato ma l'elenco delle query:
    con questo doppio si legge esattamente quali istruzioni sono arrivate.
    """

    def __init__(self, riga=None):
        self.query: list[str] = []
        self.riga = riga

    async def fetchrow(self, sql, *args):
        self.query.append(sql)
        return self.riga

    async def fetch(self, sql, *args):
        self.query.append(sql)
        return []

    async def fetchval(self, sql, *args):
        self.query.append(sql)
        return None

    async def execute(self, sql, *args):
        self.query.append(sql)
        return "OK"


class _PoolSpia:
    """Un pool che cede sempre la stessa connessione spia e conta gli `acquire`."""

    def __init__(self, connessione: _Spia):
        self.connessione = connessione
        self.acquisizioni = 0

    def acquire(self):
        self.acquisizioni += 1
        return _ContestoAcquisizione(self.connessione)


class _ContestoAcquisizione:
    """Il context manager di `pool.acquire()` (asyncpg lo espone così)."""

    def __init__(self, connessione: _Spia):
        self.connessione = connessione

    async def __aenter__(self):
        return self.connessione

    async def __aexit__(self, *_):
        return False


class _TransazioneVuota:
    """La transazione del doppio: non fa nulla, perché qui si conta quali query arrivano, non il loro effetto."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False


def test_email_non_riconosciuta_risponde_403_e_non_esegue_nessuna_query(client, monkeypatch):
    """Un'email fuori da `identita_onyx` dà 403 e il database vede **una sola** query: la risoluzione dell'identità.

    È l'invariante del §9.1: la risoluzione è l'unica lettura ammessa prima di assumere un ruolo, e da lì in poi
    nessuna query applicativa parte. L'elenco delle query lo prova direttamente, invece di dedurlo da un codice.
    """
    from app import db

    spia = _Spia(riga=None)
    pool = _PoolSpia(spia)
    monkeypatch.setattr(db, "_pool", pool)
    monkeypatch.setattr(db, "_pool_corrente", lambda: pool)
    db.svuota_cache_identita()

    risposta = _apri(client, EMAIL_SCONOSCIUTA)

    assert risposta.status_code == 403
    assert risposta.json() == {"detail": DETAIL_IDENTITA_NON_RICONOSCIUTA}
    assert len(spia.query) == 1, f"attesa la sola risoluzione dell'identità, trovate: {spia.query}"
    assert "identita_onyx" in spia.query[0]
    assert pool.acquisizioni == 1, "nessuna connessione oltre a quella dell'identità"


def test_identita_riconosciuta_e_cache_breve_evitano_query_ripetute(client, monkeypatch):
    """La risoluzione dell'identità è in cache: la seconda richiesta non rilegge `identita_onyx`.

    La cache è breve (60 s) di proposito, ma esiste: senza, ogni chiamata dello shim pagherebbe una query in più su
    una tabella che cambia una volta al mese.
    """
    from app import db

    riga = {"ruolo_db": "casa_sanbao", "casa_id": 5}
    spia = _Spia(riga=riga)
    pool = _PoolSpia(spia)
    monkeypatch.setattr(db, "_pool", pool)
    monkeypatch.setattr(db, "_pool_corrente", lambda: pool)
    db.svuota_cache_identita()

    asyncio.run(db.risolvi_identita(EMAIL_OP_SANBAO))
    asyncio.run(db.risolvi_identita(EMAIL_OP_SANBAO))

    assert len(spia.query) == 1, "la seconda risoluzione deve arrivare dalla cache"


@pytest.mark.live
def test_il_ruolo_assunto_non_sopravvive_alla_richiesta(db_vivo, dsn):
    """`SET LOCAL` e non `SET`: una connessione riusata dal pool non porta il ruolo della richiesta precedente.

    Il test usa un pool **suo**, di una sola connessione, e la stessa connessione due volte: è esattamente lo
    scenario che rende pericoloso un `SET` persistente — la richiesta di una Casa che lascia i propri permessi alla
    richiesta successiva. Un pool dell'applicazione non si può usare qui perché vive nel ciclo di eventi del
    `TestClient`; la proprietà verificata, però, è la stessa che la dipendenza sfrutta.
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    async def scenario() -> tuple[str, str]:
        import asyncpg

        pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=1)
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute("SET LOCAL ROLE casa_sanbao")
                    dentro = await conn.fetchval("SELECT current_user")
            async with pool.acquire() as conn:
                fuori = await conn.fetchval("SELECT current_user")
            return dentro, fuori
        finally:
            await pool.close()

    dentro, fuori = asyncio.run(scenario())

    assert dentro == "casa_sanbao", "dentro la transazione il ruolo deve essere quello della Casa"
    assert fuori == "shim_rw", "dopo il COMMIT la stessa connessione non deve conservare il ruolo"



@pytest.mark.live
def test_ogni_richiesta_autenticata_assume_il_ruolo_della_casa(client, db_vivo, monkeypatch):
    """La richiesta HTTP arriva al database **dentro** il ruolo della Casa, non come `shim_rw`.

    È il comportamento da cui dipende tutto il modello di permessi: l'autorità è la RLS, e la RLS decide su
    `current_user`. `_whoami` (acceso solo qui, per il test) riporta il ruolo che la dipendenza ha assunto per
    questa richiesta; il valore atteso è quello scritto in `identita_onyx` per l'operatore di San Bao.
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    from app import db
    from app.settings import get_settings

    db.svuota_cache_identita()
    monkeypatch.setattr(get_settings(), "shim_debug", "1")

    risposta = client.get(f"{URL.format(email=EMAIL_OP_SANBAO)}/_whoami")

    assert risposta.status_code == 200
    corpo = risposta.json()
    assert corpo["ruolo"] == "casa_sanbao", "la richiesta deve girare come ruolo della Casa"
    assert corpo["casa_id"] == 5, "la Casa dell'operatore (San Bao)"


@pytest.mark.live
def test_operatore_di_una_casa_non_legge_i_dati_di_un_altra(client, db_vivo):
    """La RLS è l'autorità: la risposta non contiene dati riservati a un'altra Casa.

    Il test cerca un luogo che appartiene a un'altra Casa e verifica che ciò che torna sia comunque leggibile: la
    RLS di `luogo` è di lettura per tutti (principio 3 «tutti leggono tutto»), quindi la verifica utile è che la
    **scrittura** sia invece negata — coperta dai test delle proposte. Qui si prova che la lettura non è filtrata
    per errore dallo shim, che è il modo in cui una Casa perderebbe informazione senza che nessuno se ne accorga.
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    risposta = client.get(f"{URL.format(email=EMAIL_OP_SANBAO)}/cerca_luogo?q=CAF")

    assert risposta.status_code == 200
    nomi = [item["nome"] for item in risposta.json()["items"]]
    assert any("CAF" in nome for nome in nomi), f"i luoghi delle altre Case devono essere leggibili: {nomi}"


def test_whoami_e_spento_senza_shim_debug(client, sessione_finta):
    """`_whoami` è diagnostica, non contratto: senza `SHIM_DEBUG=1` non esiste (404, non 403)."""
    sessione_finta()
    risposta = client.get(f"{URL.format(email=EMAIL_OP_SANBAO)}/_whoami")

    assert risposta.status_code == 404


def test_log_non_contiene_corpo_ne_email_ne_motivazione(client, caplog):
    """Il log porta solo `method, operationId, status, ms, ruolo`: mai l'email, mai il corpo (V5/§12).

    È l'invariante che il piano verifica con `grep -c '@trasi.local\\|motivazione' shim.log` → 0; qui è verificata
    catturando davvero le righe di log prodotte da una richiesta.
    """
    registratore = logging.getLogger("trasi.shim")
    registratore.addHandler(caplog.handler)
    livello = registratore.level
    registratore.setLevel(logging.INFO)
    try:
        with caplog.at_level(logging.INFO, logger="trasi.shim"):
            _apri(client, EMAIL_OP_SANBAO, "eventi_oggi?casa=san-bao")
    finally:
        registratore.setLevel(livello)
        registratore.removeHandler(caplog.handler)

    testo = "\n".join(voce.getMessage() for voce in caplog.records if voce.name == "trasi.shim")

    assert "eventi_oggi" in testo, "il log deve nominare l'operationId, non l'URL"
    assert EMAIL_OP_SANBAO not in testo, "l'email dell'operatore non deve comparire nel log"
    assert "@trasi.local" not in testo
    assert "motivazione" not in testo
    assert "san-bao" not in testo, "i parametri di query non devono finire nel log"


def test_log_di_una_scrittura_non_contiene_il_payload(client, caplog):
    """`POST registra_richiesta` è la richiesta più esposta: il log non deve contenerne il corpo.

    Il test manda un corpo riconoscibile e verifica che nessuna riga di log lo ripeta. Il corpo è volutamente una
    categoria valida, così la richiesta arriva fino alla registrazione (o al 503 senza database): in entrambi i casi
    il log deve restare muto sul contenuto.
    """
    corpo = {"categoria": "orientamento", "esito": "risolta"}
    registratore = logging.getLogger("trasi.shim")
    registratore.addHandler(caplog.handler)
    livello = registratore.level
    registratore.setLevel(logging.INFO)
    try:
        with caplog.at_level(logging.INFO, logger="trasi.shim"):
            client.post(f"{URL.format(email=EMAIL_OP_SANBAO)}/registra_richiesta", json=corpo)
    finally:
        registratore.setLevel(livello)
        registratore.removeHandler(caplog.handler)

    testo = StringIO()
    for voce in caplog.records:
        testo.write(voce.getMessage() + "\n")

    assert "orientamento" not in testo.getvalue()
    assert EMAIL_OP_SANBAO not in testo.getvalue()


def test_ruolo_non_assumibile_risponde_403_non_500(client, db_vivo):
    """Un'identità **attiva** il cui ruolo non è concesso a `shim_rw` dà 403 parlante, non un 500.

    Il caso è reale: `ti@trasi.local` esiste in `identita_onyx` con `attiva = true` e ha un utente Onyx, quindi dalla
    chat lo si raggiunge come ogni altro operatore. Ma `db/000_roles.sql` concede a `shim_rw` le dieci Case più
    `rete`, e **revoca `ti`**: il `SET LOCAL ROLE ti` della dipendenza di sessione solleva
    `InsufficientPrivilegeError`, che senza traduzione diventa un **500 «errore interno dello shim»** — cioè un
    guasto dichiarato al posto di un ruolo non abilitato, e chi diagnostica cerca un bug che non c'è.

    Misurato prima del fix: 21 identità su 22 rispondevano 200 su `oggi`, `ti` rispondeva 500 su ogni endpoint.

    Il test asserisce **entrambe** le metà dell'invariante: che il rifiuto sia dichiarato (403 col dettaglio del
    contratto) **e** che il ruolo non venga concesso — se un giorno `ti` fosse aggiunto a `shim_rw`, questo test
    diventa rosso e la decisione di least-privilege passa da una revisione, non da una riga silenziosa.
    """
    if not db_vivo:
        pytest.skip("serve il database: la risoluzione dell'identità legge `identita_onyx`")

    risposta = _apri(client, EMAIL_TI)

    assert risposta.status_code == 403, (
        f"atteso 403 (ruolo non abilitato), ottenuto {risposta.status_code}: {risposta.text[:200]}"
    )
    assert risposta.json() == {"detail": DETAIL_RUOLO_SENZA_ACCESSO}


def test_il_ti_non_e_membro_di_shim_rw():
    """La premessa del test precedente, verificata dove sta la decisione: `db/000_roles.sql`.

    Se questo test diventa rosso, la riga `REVOKE ti FROM shim_rw` è sparita e l'identità TI ha accesso operativo:
    è una decisione di least-privilege, e va presa deliberatamente.
    """
    from pathlib import Path

    sorgente = Path(__file__).resolve().parents[2] / "db" / "000_roles.sql"
    testo = sorgente.read_text(encoding="utf-8")

    assert "REVOKE ti FROM shim_rw" in testo, (
        "db/000_roles.sql non revoca più `ti` da `shim_rw`: il TI avrebbe accesso allo shim"
    )
