"""Le sessioni di servizio (`pa`/`rete`, US-4): login, cookie, ruolo e logout.

Il database è contraffatto (spia su `asyncpg`) come in `test_identita.py`: la proprietà difesa è «quale SQL arriva,
con quali argomenti, in quale ordine», non l'effetto. Il pool spia è deliberatamente **più vero** di una sessione
finta, perché il punto debole di questo canale è proprio la transazione: un cookie che il codice tratta come un
parametro, e una query che guarda il DB prima di fidarsi del valore.

Cinque comportamenti, ognuno con un esito osservabile:

1. **`POST /servizio/login`** chiama `trasi.crea_sessione_servizio` e restituisce un cookie HttpOnly. L'hash della
   password non è mai in Python: lo shim passa il segreto sulla connessione applicativa, come per le Case.
2. **Blocco anti-brute-force dichiarato**: un `RaiseError` di «login_bloccato» dal DB diventa 401, mai 500.
3. **La guardia della sessione servizio** distingue: cookie assente (401), cookie valido con ruolo giusto (200),
   cookie valido con ruolo sbagliato (401: un operatore `rete` non entra nella dashboard del monitoraggio).
4. **`SET LOCAL ROLE` è quello del DB**, non quello del chiamante: il ruolo atteso non si interpola nella query, la
   query cerca la sessione e **poi** il ruolo viene verificato e assunto.
5. **Il logout scade anche le sessioni servizio**: `DELETE FROM trasi.sessione` per token, indipendente da
   `casa_id`. Un cookie che ha perso la riga di sessione smette di aprire anche se non è ancora scaduto.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

import ambiente

RUOLO_PA = "pa"
RUOLO_RETE = "rete"
PASSWORD_DI_PROVA = "pa2026!"
TOKEN_DI_PROVA = uuid.uuid4()

DETAIL_SESSIONE_NON_VALIDA = "sessione assente o scaduta"
DETAIL_TROPPI_TENTATIVI = "troppi tentativi: accesso bloccato, riprovare più tardi"
DETAIL_CREDENZIALI_NON_VALIDE = "casa o password non valide"
DETAIL_RUOLO_SBAGLIATO = "questa area richiede un altro ruolo: sessione non valida per il ruolo richiesto"

# Le query che lo shim deve fare, alla lettera: sono il contratto osservabile della contraffazione.
SQL_CREA_SERVIZIO = "SELECT trasi.crea_sessione_servizio($1,$2)"
SQL_SESSIONE_SERVIZIO = "SELECT ruolo_db FROM trasi.sessione WHERE token = $1 AND scade_ts > now()"
SQL_TTL = "SELECT valore FROM trasi.parametro WHERE chiave = 'session_ttl_hours'"


class _Spia:
    """Una connessione che risponde per nome della query: login crea il token, la sessione risolve il ruolo.

    Le risposte sono decise dal test: un SQL non riconosciuto risponde con il default (`None`), così un cambio di
    query non passa inosservato.
    """

    def __init__(self, *, token_login=None, ruolo_sessione=None, esegue: dict[str, str] | None = None) -> None:
        self.token_login = token_login
        self.ruolo_sessione = ruolo_sessione
        self.esegue = esegue or {}
        self.query: list[tuple[str, tuple[Any, ...]]] = []

    async def fetchval(self, sql: str, *args: Any) -> Any:
        self.query.append((sql, args))
        normalizzata = " ".join(sql.split())
        if "crea_sessione_servizio" in normalizzata:
            return self.token_login
        if "ruolo_db FROM trasi.sessione" in normalizzata:
            return self.ruolo_sessione
        if "session_ttl_hours" in normalizzata:
            return None
        return None

    async def execute(self, sql: str, *args: Any) -> str:
        self.query.append((sql, args))
        normalizzata = " ".join(sql.split())
        for chiave, risposta in self.esegue.items():
            if chiave in normalizzata:
                return risposta
        return "OK"

    async def fetch(self, sql: str, *args: Any) -> list[Any]:
        self.query.append((sql, args))
        return []

    def transaction(self) -> "_TransazioneVuota":
        """Il context manager di `conn.transaction()` (asyncpg lo espone così)."""
        return _TransazioneVuota()


class _Acquisizione:
    def __init__(self, connessione: _Spia) -> None:
        self.connessione = connessione

    async def __aenter__(self) -> _Spia:
        return self.connessione

    async def __aexit__(self, *_: Any) -> bool:
        return False


class _TransazioneVuota:
    async def __aenter__(self) -> "_TransazioneVuota":
        return self

    async def __aexit__(self, *_: Any) -> bool:
        return False


class _PoolSpia:
    def __init__(self, connessione: _Spia) -> None:
        self.connessione = connessione
        self.acquisizioni = 0

    def acquire(self) -> _Acquisizione:
        self.acquisizioni += 1
        return _Acquisizione(self.connessione)


@pytest.fixture
def client_servizio(monkeypatch, tmp_path):
    """`TestClient` sull'app reale con il pool di auth sostituito da una spia.

    Il punto è che `auth.py` usa `_pool_corrente()` del modulo, non la sessione: qui si sostituisce
    quel factory, così le query del login e della guardia vedono il database contraffatto.
    """
    ambiente.configura_ambiente()
    monkeypatch.setenv("TRASI_SHIM_KEY", ambiente.CHIAVE_SHIM or "chiave-di-test")

    from app import auth as modulo_auth
    from app.main import crea_app

    def costruisci(connessione: _Spia) -> tuple[TestClient, _Spia]:
        monkeypatch.setattr(modulo_auth, "_pool_corrente", lambda: _PoolSpia(connessione))
        aplicazione = crea_app()
        return TestClient(aplicazione, raise_server_exceptions=False), connessione

    return costruisci


# --- login -----------------------------------------------------------------------------------------------------


def test_login_servizio_risponde_200_e_cookie_httponly(client_servizio):
    """`POST /servizio/login` con password giusta chiama la funzione del DB e restituisce il cookie di sessione.

    Il comportamento osservabile è identico a `POST /login` per le Case: stesso cookie, stessa assenza del token nel
    corpo JSON, stesso TTL. La differenza è interna — la funzione chiamata e il payload di risposta — ed è quella che
    qui si aspetta.
    """
    client, spia = client_servizio(_Spia(token_login=TOKEN_DI_PROVA))

    risposta = client.post("/servizio/login", json={"ruolo": RUOLO_PA, "password": PASSWORD_DI_PROVA})

    assert risposta.status_code == 200
    assert risposta.json() == {"ruolo": RUOLO_PA, "sessione": "aperta"}
    assert "trasi_sessione" in risposta.cookies
    assert risposta.cookies.get("trasi_sessione") == str(TOKEN_DI_PROVA)
    # La funzione giusta, con i giusti argomenti: ruolo nel corpo, non nell'URL; password nel corpo.
    login_query = [q for q in spia.query if "crea_sessione_servizio" in " ".join(q[0].split())]
    assert login_query, "la creazione della sessione deve passare per la funzione SECURITY DEFINER del database"
    assert login_query[0][1] == (RUOLO_PA, PASSWORD_DI_PROVA)


def test_login_servizio_sbagliato_risponde_401_indistinto(client_servizio):
    """Password errata e ruolo sconosciuto hanno lo **stesso** 401: i ruoli non devono essere enumerabili."""
    client, _ = client_servizio(_Spia(token_login=None))

    risposta = client.post("/servizio/login", json={"ruolo": RUOLO_PA, "password": "sbagliata"})

    assert risposta.status_code == 401
    assert risposta.json() == {"detail": DETAIL_CREDENZIALI_NON_VALIDE}


def test_blocco_anti_brute_force_risponde_401_dedicato(client_servizio, monkeypatch):
    """Il blocco anti-brute-force del database ha il proprio 401: «troppi tentativi», diverso da «credenziali errate».

    La funzione `crea_sessione_servizio` solleva un `RaiseError` con `login_bloccato` nel testo: qui si verifica che lo
    shim lo riconosca e lo traduca, senza propagarlo né interpretarlo come un guasto interno.
    """
    from asyncpg.exceptions import RaiseError

    def _fetchval_bloccato(sql: str, *args: Any) -> Any:
        if "crea_sessione_servizio" in " ".join(sql.split()):
            raise RaiseError("login_bloccato: troppi tentativi")
        return None

    client, spia = client_servizio(_Spia())
    spia.fetchval = _fetchval_bloccato

    risposta = client.post("/servizio/login", json={"ruolo": RUOLO_RETE, "password": PASSWORD_DI_PROVA})

    assert risposta.status_code == 401
    assert risposta.json() == {"detail": DETAIL_TROPPI_TENTATIVI}


def test_login_servizio_con_chiave_extra_risponde_422(client_servizio):
    """`extra="forbid"`: un `casa` nel corpo è un 422 — il ruolo è quello dichiarato, non una scelta del chiamante."""
    client, _ = client_servizio(_Spia())

    risposta = client.post(
        "/servizio/login", json={"ruolo": RUOLO_PA, "password": PASSWORD_DI_PROVA, "casa": "san-bao"}
    )

    assert risposta.status_code == 422
    assert risposta.json()["detail"].startswith("parametri non ammessi")


# --- guardia della sessione servizio ---------------------------------------------------------------------------


def test_senza_cookie_la_dashboard_pa_risponde_401(client_servizio):
    """`/pa/me` senza cookie risponde 401: la guardia è la stessa di `/op/…`, con la stessa forma di risposta."""
    client, spia = client_servizio(_Spia())

    risposta = client.get("/pa/me")

    assert risposta.status_code == 401
    assert risposta.json() == {"detail": DETAIL_SESSIONE_NON_VALIDA}
    assert spia.query == [], "senza cookie non tocca il database"


def test_sessione_pa_apre_e_set_local_role_pa(client_servizio):
    """Un cookie con `ruolo_db='pa'` apre la transazione e il ruolo è quello del database, non del chiamante.

    La query non porta il ruolo atteso come parametro: cerca la sessione e legge il ruolo, poi lo verifica. Così il
    chiamante non decide chi è — il database decide e lo shim applica. `SET LOCAL` è osservabile nell'elenco delle
    query.
    """
    client, spia = client_servizio(_Spia(ruolo_sessione=RUOLO_PA))
    client.cookies.set("trasi_sessione", str(TOKEN_DI_PROVA))

    risposta = client.get("/pa/me")

    assert risposta.status_code == 200
    assert risposta.json() == {"ruolo": RUOLO_PA}
    sessione_query = [q for q in spia.query if "ruolo_db FROM trasi.sessione" in " ".join(q[0].split())]
    assert sessione_query, "il ruolo si risolve dal DB, mai dal chiamante"
    # Il 200 è arrivato: la transazione con SET LOCAL ROLE pa è stata aperta e chiusa.
    assert any(
        "SET LOCAL ROLE" in " ".join(q[0].split()) and " pa" in " ".join(q[0].split()) for q in spia.query
    ), "SET LOCAL ROLE pa deve comparire nell'elenco delle query"


def test_sessione_con_altro_ruolo_entra_nella_dashboard_condivisa(client_servizio):
    """Il referente `rete` entra nella stessa dashboard di `pa` (lettura): la superficie è condivisa US-4.

    `pa` legge e approfondisce, `rete` legge e in più approva. La separazione non è fra aree diverse ma fra
    **azioni** (`POST …/approva` resta solo `rete`): per questo questo test verifica il 200 multi-ruolo,
    non un 401. Un cookie valido per `rete` apre la stessa sessione di lettura di `pa`, e la transazione è
    aperta con `SET LOCAL ROLE rete`.
    """
    client, spia = client_servizio(_Spia(ruolo_sessione=RUOLO_RETE))
    client.cookies.set("trasi_sessione", str(TOKEN_DI_PROVA))

    risposta = client.get("/pa/me")

    assert risposta.status_code == 200
    assert risposta.json() == {"ruolo": RUOLO_RETE}
    # Il ruolo è stato risolto (query fatta) e la transazione con SET LOCAL ROLE è stata aperta per lui.
    assert any("ruolo_db FROM trasi.sessione" in " ".join(q[0].split()) for q in spia.query)
    assert any(
        "SET LOCAL ROLE" in " ".join(q[0].split()) and " rete" in " ".join(q[0].split()) for q in spia.query
    ), "SET LOCAL ROLE rete deve comparire nelle query"


def test_la_pa_non_puo_approvare_un_report(client_servizio):
    """`POST /pa/report/{id}/approva` è solo di `rete`: con un cookie `pa` l'approvazione risponde 401.

    La lettura è condivisa (test precedente); la **decisione** resta del referente (V6): la funzione
    `trasi.approva_report` ha EXECUTE solo per `rete`/`ti`, e l'endpoint usa la dipendenza riservata.
    """
    client, spia = client_servizio(_Spia(ruolo_sessione=RUOLO_PA))
    client.cookies.set("trasi_sessione", str(TOKEN_DI_PROVA))

    risposta = client.post("/pa/report/1/approva")

    assert risposta.status_code == 401
    assert risposta.json() == {"detail": DETAIL_RUOLO_SBAGLIATO}


def test_cookie_malformato_o_scaduto_risponde_401(client_servizio):
    """Un cookie che non è un UUID valido non arriva al database: 401, prima di qualunque query."""
    client, spia = client_servizio(_Spia())
    client.cookies.set("trasi_sessione", "non-e-un-uuid")

    risposta = client.get("/pa/me")

    assert risposta.status_code == 401
    assert risposta.json() == {"detail": DETAIL_SESSIONE_NON_VALIDA}
    assert spia.query == [], "un cookie malformato si rifiuta prima di toccare il DB"


# --- logout ------------------------------------------------------------------------------------------------------


def test_logout_scade_anche_la_sessione_servizio(client_servizio):
    """`POST /logout` cancella la riga `trasi.sessione` per token: vale anche per le sessioni di `pa`/`rete`.

    L'operazione non distingue fra i due tipi di sessione, perché la tabella è la stessa: un solo meccanismo di
    revoca, e non c'è un cookie che resta valido per uno scopo e revocato per l'altro.
    """
    client, spia = client_servizio(_Spia(ruolo_sessione=RUOLO_PA))
    client.cookies.set("trasi_sessione", str(TOKEN_DI_PROVA))

    risposta = client.post("/logout")

    assert risposta.status_code == 204
    delete_query = [q for q in spia.query if "DELETE FROM trasi.sessione" in " ".join(q[0].split())]
    assert delete_query, "la revoca deve essere la DELETE per token sulla tabella delle sessioni"
    assert delete_query[0][1] == (TOKEN_DI_PROVA,)
    # Il risultato osservabile: il cookie scade nel browser.
    assert risposta.cookies.get("trasi_sessione") in ("", None)


# --- contratto congelato (V-09) ----------------------------------------------------------------------------------


def test_le_nuove_route_non_entrano_nello_schema_openapi(client_servizio):
    """`/servizio/login`, `/pa/…` e `/v1/m/…` non compaiono nello schema: il gate V-09 resta a nove operationId.

    Lo schema è quello che FastAPI genera dall'app **reale** (non da una sua copia): qui la prova è che le route di
    questo canale esistono e rispondono, senza finire nel documento che Onyx registra come tool.
    """
    from app.main import app as applicazione

    percorsi = {p for p in applicazione.openapi()["paths"]}
    assert "/servizio/login" not in percorsi
    assert "/pa/me" not in percorsi
    assert "/pa/report" not in percorsi
    assert "/v1/m/{email}/report" not in percorsi
