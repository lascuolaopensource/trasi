"""Fixture condivise dei test dello shim.

Quattro scelte che vale la pena dichiarare, perché non sono ovvie:

**Il contratto è letto dal file reale** `shim/openapi.yaml` (fonte di verità del gate V-09), non da una copia: un test
che girasse su una copia non proverebbe nulla sul contratto che Onyx registra.

**Le variabili d'ambiente si impostano prima di importare `app`**: l'applicazione costruisce l'istanza delle
impostazioni all'import (`crea_app()`), quindi l'ordine non è un dettaglio di stile. `DATABASE_URL` viene riscritta
verso `127.0.0.1` perché dall'host il nome di rete `db_trasi` non risolve (il container lo risolve: è la stessa
password, la porta è pubblicata su loopback).

**Niente fixture asincrone.** La suite usa `TestClient` (sincrono) e, dove serve il database, un `asyncio.run(...)`
dentro il test: è la stessa forma usata dall'altro worker, e non introduce una dipendenza da `pytest-asyncio` che il
`requirements-dev.txt` non dichiara.

**I test che richiedono il database si saltano, non falliscono**, quando il database non risponde: la suite deve
girare anche su una macchina senza lo stack acceso, e un test saltato con un motivo è più onesto di un fallimento che
dice «il database non c'è». I test che provano il **contratto** (401, 422, badge, ordinamento) girano sempre.
"""

import os
import socket
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

RADICE_SHIM = Path(__file__).resolve().parent.parent
if str(RADICE_SHIM) not in sys.path:
    sys.path.insert(0, str(RADICE_SHIM))

PERCORSO_CONTRATTO = RADICE_SHIM / "openapi.yaml"


def _valore_da_env_file(nome: str) -> str:
    """Un valore da `deployment/.env`, la stessa sorgente del compose.

    Serve perché la suite gira **da host** (dove `db_trasi` non risolve e la chiave non è esportata) e **in
    container** (dove le variabili ci sono già): leggere il file rende i due casi lo stesso caso.
    """
    percorso = RADICE_SHIM.parent / "deployment" / ".env"
    if not percorso.exists():
        return ""
    for riga in percorso.read_text(encoding="utf-8").splitlines():
        if riga.startswith(f"{nome}="):
            return riga.split("=", 1)[1].strip()
    return ""


def _dsn_di_prova() -> str:
    """`DATABASE_URL` utilizzabile da questo processo: host di rete nel container, `127.0.0.1` da host.

    La password non è nel codice: viene da `deployment/.env`, come per il compose. Senza quel file si resta senza
    DSN, e saranno i test che richiedono il database a saltare — non il test a mentire.
    """
    dsn = os.environ.get("DATABASE_URL") or _valore_da_env_file("DATABASE_URL")
    if "db_trasi" not in dsn:
        return dsn
    return dsn.replace("db_trasi", "127.0.0.1")


def _db_raggiungibile(dsn: str) -> bool:
    """Il database risponde su TCP? Verifica di rete, non di credenziali (quelle le prova chi apre la connessione)."""
    if "@" not in dsn:
        return False
    indirizzo = dsn.rsplit("@", 1)[1].split("/")[0]
    host, _, porta = indirizzo.partition(":")
    try:
        with socket.create_connection((host or "127.0.0.1", int(porta or 5432)), timeout=1.5):
            return True
    except OSError:
        return False


# La configurazione di prova va impostata **prima** che `app` venga importato: `crea_app()` legge le impostazioni
# all'import, e un `DATABASE_URL` sbagliato lì non si corregge più senza riavviare il processo.
DSN_PROVA = _dsn_di_prova()
if DSN_PROVA:
    os.environ["DATABASE_URL"] = DSN_PROVA
# La chiave reale quando c'è (così le verifiche con `curl` fatte a mano corrispondono a quelle dei test), altrimenti
# una chiave di prova: lo shim non autentica nessuno con una chiave vuota, quindi non si può omettere.
os.environ.setdefault("TRASI_SHIM_KEY", _valore_da_env_file("TRASI_SHIM_KEY") or "chiave-di-prova")
os.environ.setdefault("OVERPASS_TIMEOUT_S", "5")
os.environ.setdefault("TZ", "Europe/Rome")

DB_VIVO = _db_raggiungibile(DSN_PROVA)


def pytest_configure(config: pytest.Config) -> None:
    """Registra i marcatori usati dalla suite (senza, pytest avvisa a ogni esecuzione)."""
    config.addinivalue_line(
        "markers", "live: richiede il database o una fonte esterna reale (saltato se assente)"
    )


@pytest.fixture(scope="session")
def contratto() -> dict[str, Any]:
    """Il contratto congelato, interpretato."""
    with PERCORSO_CONTRATTO.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="session")
def db_vivo() -> bool:
    """Il database è raggiungibile da questo processo?"""
    return DB_VIVO


@pytest.fixture(scope="session")
def dsn() -> str:
    """Il DSN utilizzabile da questo processo (o `""` se il database non è configurato)."""
    return DSN_PROVA


@pytest.fixture
def chiave() -> str:
    """La `X-Trasi-Key` valida in questa sessione di test."""
    from app.settings import get_settings

    return get_settings().trasi_shim_key


@pytest.fixture
def client(chiave: str):
    """Client ASGI sull'applicazione, con la chiave dello shim già impostata.

    La chiave è nell'header di default: senza, ogni richiesta sarebbe un 401 e i test non proverebbero l'endpoint.
    L'email dell'operatore resta nel percorso, che è come Onyx la passa (`servers[0].url` con `USER_EMAIL` risolto).
    """
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app, headers={"X-Trasi-Key": chiave}) as c:
        yield c


@pytest.fixture
def client_anonimo():
    """Client ASGI **senza** chiave: serve a provare il 401."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


class SessioneFinta:
    """Una sessione con risposte preconfezionate, per i test che non hanno bisogno del database.

    Serve a una ragione precisa: FastAPI risolve le dipendenze **prima** di validare i parametri dell'operazione,
    quindi una richiesta con parametri malformati arriva al database prima di essere rifiutata con 422. Sostituendo
    la dipendenza di sessione si prova la stessa logica (il rifiuto dei parametri, il 404 di una Casa inesistente)
    senza dipendere dal database: il test resta deterministico e dice esattamente cosa verifica.

    Il doppio è minimale di proposito: registra le query ricevute e restituisce le righe che il test ha preparato.
    I nomi dei metodi sono quelli che i router usano (`fetch`, `fetchrow`, `fetchval`, `execute`).
    """

    def __init__(self, righe: list | None = None, riga=None, valore=None):
        self.righe = righe or []
        self.riga = riga
        self.valore = valore
        self.query: list[str] = []
        self.email = "op.di.prova@trasi.local"
        self.ruolo = "casa_sanbao"
        self.casa_id = 5

    async def fetch(self, sql: str, *args):
        self.query.append(sql)
        return self.righe

    async def fetchrow(self, sql: str, *args):
        self.query.append(sql)
        return self.riga

    async def fetchval(self, sql: str, *args):
        self.query.append(sql)
        return self.valore

    async def execute(self, sql: str, *args):
        self.query.append(sql)
        return "OK"


@pytest.fixture
def sessione_finta():
    """Installa un doppio della dipendenza di sessione per il test corrente, e lo rimuove alla fine.

    L'override è su `app.db.sessione`: è il nome che i router importano e che FastAPI usa come chiave di
    risoluzione, quindi la sostituzione è completa senza toccare il codice di produzione.
    """
    from app import db
    from app.main import app

    def installa(**kwargs) -> SessioneFinta:
        doppio = SessioneFinta(**kwargs)
        app.dependency_overrides[db.sessione] = lambda: doppio
        return doppio

    yield installa
    app.dependency_overrides.pop(db.sessione, None)
