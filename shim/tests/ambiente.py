"""Ambiente dei test delle scritture e degli output (metà B3 del worker B3ShimB).

Questo modulo risolve **una** domanda: i test di questa metà devono poter girare in due contesti diversi senza
cambiare una riga.

- **Fuori dalla rete Docker** (host di sviluppo): il database è pubblicato su `127.0.0.1`, mentre `deployment/.env`
  indica l'hostname interno `db_trasi`. Qui l'hostname viene sostituito con l'indirizzo pubblicato, e le credenziali
  restano quelle vere — lette dal file, non ricopiate nel codice.
- **Dentro la rete `trasi_net`** (container, CI): `db_trasi` risolve e viene usato così com'è.

Se `deployment/.env` non c'è, `dsn_disponibile()` è falso e i test che richiedono il database si **saltano**
(`pytest.skip`), non falliscono: un test che fallisce perché manca un prerequisito insegna poco.

Le fixture di questo modulo creano righe in `trasi.proposta` agendo **come `rete`** sulla connessione di `shim_rw`
(che ne è membro), non come amministratore: così anche la creazione delle fixture passa per la stessa RLS che
protegge la produzione, e una fixture impossibile in produzione non passa inosservata nei test.
"""

from __future__ import annotations

import os
import re
import socket
from datetime import date
from pathlib import Path
from typing import Any

import asyncpg

RADICE_PROGETTO = Path(__file__).resolve().parents[2]
PERCORSO_ENV = RADICE_PROGETTO / "deployment" / ".env"

_RIGA_ENV = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def _variabili_env() -> dict[str, str]:
    """Le variabili di `deployment/.env`, senza interpretazione delle sostituzioni (`${…}`)."""
    if not PERCORSO_ENV.exists():
        return {}
    valori: dict[str, str] = {}
    for riga in PERCORSO_ENV.read_text(encoding="utf-8").splitlines():
        trovato = _RIGA_ENV.match(riga.strip())
        if trovato:
            valori[trovato.group(1)] = trovato.group(2).strip().strip('"').strip("'")
    return valori


def _host_raggiungibile(nome: str) -> bool:
    """Vero se l'hostname risolve da questo processo (fuori dalla rete Docker, `db_trasi` non risolve)."""
    try:
        socket.getaddrinfo(nome, None)
    except OSError:
        return False
    return True


def _dsn_raggiungibile(dsn: str, variabili: dict[str, str]) -> str:
    """L'URL del database con l'host sostituito se l'hostname interno non è raggiungibile."""
    from urllib.parse import urlsplit, urlunsplit

    parti = urlsplit(dsn)
    if not parti.hostname or _host_raggiungibile(parti.hostname):
        return dsn
    porta = variabili.get("HOST_PORT_DB", "5432")
    netloc = parti.netloc.replace(f"{parti.hostname}:{parti.port}", f"127.0.0.1:{porta}")
    return urlunsplit((parti.scheme, netloc, parti.path, parti.query, parti.fragment))


VARIABILI = _variabili_env()

# Lo stesso URL che il compose inietta nello shim, con l'host reso raggiungibile da qui. La variabile d'ambiente
# **vince** sul file: è così che si simula «database irraggiungibile» (una porta morta) per verificare che i test
# `live` si saltino invece di fallire — il criterio del piano chiede una suite verde anche offline.
DATABASE_URL = os.environ.get("DATABASE_URL") or _dsn_raggiungibile(VARIABILI.get("DATABASE_URL", ""), VARIABILI)

# La chiave dello shim: quella vera del compose, così i test provano anche il percorso 401/201 completo.
CHIAVE_SHIM = VARIABILI.get("TRASI_SHIM_KEY", "")

# Email reali di `trasi.identita_onyx` (db/010_seed_case.sql): i test non inventano identità, usano quelle seminate.
EMAIL_SANBAO = "op.san-bao@trasi.local"
EMAIL_BOZZANO = "op.bozzano@trasi.local"
EMAIL_RETE = "rete@trasi.local"

# Case del seed: `casa_corrente()` di `op.san-bao` è San Bao (id 5 nel seed attuale: si legge, non si assume).
SLUG_SANBAO = "san-bao"
SLUG_BOZZANO = "bozzano"


def dsn_disponibile() -> bool:
    """Vero se il database **risponde** davvero, non solo se l'URL esiste.

    La differenza conta: il criterio del piano chiede che offline la suite sia verde con i test dipendenti dal
    database **saltati**. Un controllo sulla stringa non distinguerebbe «URL configurato» da «database raggiungibile»,
    e i test fallirebbero con un errore di connessione invece di saltarsi. La sonda è una connessione TCP con timeout
    breve: costa pochi millisecondi e viene eseguita una volta per processo.
    """
    global _dsn_esito
    if _dsn_esito is None:
        _dsn_esito = _prova_connessione()
    return _dsn_esito


def _prova_connessione() -> bool:
    """Una connessione TCP all'host e alla porta del database, senza credenziali."""
    if not DATABASE_URL:
        return False
    from urllib.parse import urlsplit

    parti = urlsplit(DATABASE_URL)
    if not parti.hostname:
        return False
    try:
        with socket.create_connection((parti.hostname, parti.port or 5432), timeout=1.5):
            return True
    except OSError:
        return False


_dsn_esito: bool | None = None


def configura_ambiente() -> None:
    """Esporta `DATABASE_URL` e `TRASI_SHIM_KEY` per l'applicazione e azzera le impostazioni memorizzate.

    Va chiamata **prima** che l'applicazione venga costruita: `Settings` è memorizzato (`lru_cache`) e creato una
    volta per processo, quindi senza questo azzeramento i test userebbero i default del codice invece dei valori
    reali dello stack.
    """
    if DATABASE_URL:
        os.environ["DATABASE_URL"] = DATABASE_URL
    if CHIAVE_SHIM:
        os.environ["TRASI_SHIM_KEY"] = CHIAVE_SHIM

    from app.settings import get_settings

    get_settings.cache_clear()


async def connessione(ruolo: str | None = None) -> asyncpg.Connection:
    """Una connessione come `shim_rw`, eventualmente dentro `SET ROLE <ruolo>`.

    Non è una scorciatoia per i test: è lo **stesso** percorso dello shim (connessione applicativa + ruolo assunto
    per la transazione), quindi una fixture che passa qui passa anche in produzione.
    """
    conn = await asyncpg.connect(dsn=DATABASE_URL)
    if ruolo:
        await conn.execute(f'SET ROLE "{ruolo}"')
    return conn


async def connessione_amministratore() -> asyncpg.Connection:
    """Una connessione come utente amministrativo del container, **solo** per la pulizia delle fixture.

    Serve perché nessun ruolo applicativo può cancellare una proposta: `proposta` ha `DELETE` solo per `trasi_owner`,
    e `audit` (che la riferisce) nemmeno — è la stessa segregazione in scrittura che protegge la produzione (§11,
    «nessun ruolo applicativo cancella la memoria»). Assumere un ruolo che non ha quel privilegio per «far passare»
    la pulizia significherebbe testare una configurazione che non esiste. La connessione amministrativa **non** è mai
    usata per verificare un comportamento: solo per rimuovere le righe di prova create dai test.
    """
    utente = VARIABILI.get("POSTGRES_USER", "postgres")
    password = VARIABILI.get("POSTGRES_PASSWORD", "")
    database = VARIABILI.get("TRASI_DB", "trasi_db")
    if not password:
        raise RuntimeError("POSTGRES_PASSWORD assente da deployment/.env: impossibile pulire le fixture")
    from urllib.parse import urlsplit, urlunsplit

    parti = urlsplit(DATABASE_URL)
    netloc = f"{utente}:{password}@{parti.hostname}:{parti.port}"
    return await asyncpg.connect(dsn=urlunsplit((parti.scheme, netloc, f"/{database}", "", "")))


def dsn_test() -> str:
    """L'URL usato dai test, per i messaggi di diagnosi (senza credenziali)."""
    from urllib.parse import urlsplit

    parti = urlsplit(DATABASE_URL)
    return f"{parti.scheme}://{parti.hostname}:{parti.port}{parti.path}" if parti.hostname else DATABASE_URL


async def pulisci(*ids_proposta: int) -> None:
    """Rimuove le proposte di prova e le righe `audit` che i trigger vi hanno collegato.

    Passa dalla connessione amministrativa: nessun ruolo applicativo ha `DELETE` su `proposta` né su `audit`, ed è una
    protezione voluta (V4: la memoria non si cancella dall'applicazione). L'audit va per primo, perché la chiave
    esterna `audit.proposta_id` impedirebbe altrimenti la cancellazione.

    Le righe `richiesta` di prova non si cancellano qui: il registro è un dato operativo che nessuno cancella (§12), e
    i test che lo usano rimuovono la propria riga esplicitamente.
    """
    if not ids_proposta:
        return
    conn = await connessione_amministratore()
    try:
        await conn.execute("DELETE FROM trasi.audit WHERE proposta_id = ANY($1::bigint[])", list(ids_proposta))
        await conn.execute("DELETE FROM trasi.proposta WHERE id = ANY($1::bigint[])", list(ids_proposta))
    finally:
        await conn.close()


async def crea_proposta(
    conn: asyncpg.Connection,
    *,
    casa_slug: str,
    tipo: str = "modifica_orari_casa",
    entita: str = "casa",
    entita_id: int | None = None,
    payload: dict[str, Any] | None = None,
    scade_il: date | None = None,
) -> int:
    """Crea una proposta **come un ruolo della rete**, come farebbe una fonte automatica o un'altra Casa.

    Serve a costruire gli stati che `proponi_modifica` non può produrre da solo: una proposta di un'**altra** Casa,
    una proposta già scaduta, una proposta la cui approvazione spetta alla rete (`at`). `approvatore_ruolo`,
    `proposto_da` e `diff` li calcolano i trigger: passarli a mano sarebbe una seconda verità sulla proposta.

    La connessione deve essere già nel ruolo che crea la proposta (`SET ROLE rete`, tipicamente): è la stessa RLS
    della produzione, quindi una fixture che non sarebbe possibile in produzione non passa inosservata.
    """
    casa_id = await conn.fetchval("SELECT id FROM trasi.casa WHERE slug = $1", casa_slug)
    if casa_id is None:  # pragma: no cover — il seed garantisce le dieci Case
        raise RuntimeError(f"Casa {casa_slug} assente dal seed")
    destinazione = entita_id if entita_id is not None else casa_id
    import json as _json

    corpo = payload if payload is not None else {"orari": {}}
    return await conn.fetchval(
        """
        INSERT INTO trasi.proposta (origine, tipo, entita, entita_id, casa_id, payload, motivazione, scade_il)
        VALUES ('fonte_automatica', $1, $2, $3, $4, $5::jsonb, 'fixture di test', COALESCE($6::date, current_date + 30))
        RETURNING id
        """,
        tipo,
        entita,
        destinazione,
        casa_id,
        _json.dumps(corpo),
        scade_il,
    )


async def id_casa(slug: str) -> int | None:
    """L'id della Casa, letto dal database: i test non assumono i numeri del seed."""
    conn = await connessione()
    try:
        return await conn.fetchval("SELECT id FROM trasi.casa WHERE slug = $1", slug)
    finally:
        await conn.close()
