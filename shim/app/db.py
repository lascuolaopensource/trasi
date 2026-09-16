"""Identità e sessione di database dello shim (B3-SHM-01).

Il modello di sicurezza del progetto (§1 principio 3, §11) dice che **la RLS è l'autorità**: `shim_rw` si connette
senza privilegi sul dominio e per ogni richiesta indossa il ruolo della Casa dell'operatore con

    BEGIN; SET LOCAL ROLE <ruolo_db>; …; COMMIT

`SET LOCAL` e non `SET`: il ruolo vive nella transazione e non sopravvive alla richiesta, così una connessione
riusata dal pool non porta addosso i permessi della richiesta precedente. Questa è la ragione per cui la dipendenza
è un *async generator*: il `COMMIT` e il `ROLLBACK` sono la chiusura della transazione, non un dettaglio del
chiamante.

Le due decisioni d'errore sono deliberate e non negoziabili:
- **401** se `X-Trasi-Key` è assente o errata — prima di toccare il database;
- **403** se l'email non è in `identita_onyx` (o l'identità è dismessa) — e in quel caso **nessuna query applicativa
  viene eseguita**. La risoluzione dell'identità è l'unica lettura, fatta come `shim_rw`, non come Casa.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any

import asyncpg
from asyncpg.exceptions import InsufficientPrivilegeError
from fastapi import Request

from .errori import (
    DETAIL_CHIAVE_NON_VALIDA,
    DETAIL_DATABASE_NON_RAGGIUNGIBILE,
    DETAIL_IDENTITA_NON_RICONOSCIUTA,
    DETAIL_RUOLO_SENZA_ACCESSO,
    errore,
)
from .settings import Settings, get_settings

logger = logging.getLogger("trasi.shim")

# Quanto vive in cache la risoluzione email → ruolo. Breve di proposito: il TI può cambiare `identita_onyx` e
# l'effetto deve essere visibile entro un minuto, non al riavvio del container.
TTL_IDENTITA_S = 60.0

HEADER_EMAIL = "X-Onyx-User-Email"
HEADER_CHIAVE = "X-Trasi-Key"

_pool: asyncpg.Pool | None = None
_cache_identita: dict[str, tuple[float, "Identita | None"]] = {}

# Il lucchetto del pool, tenuto insieme al ciclo di eventi che l'ha creato: un `asyncio.Lock` legato a un ciclo
# non è riusabile in un altro, e i test aprono un ciclo nuovo per ogni client.
_lucchetto_pool: tuple[asyncio.AbstractEventLoop, asyncio.Lock] | None = None


def _lucchetto() -> asyncio.Lock:
    """Il lucchetto del ciclo di eventi corrente."""
    global _lucchetto_pool
    ciclo = asyncio.get_running_loop()
    if _lucchetto_pool is None or _lucchetto_pool[0] is not ciclo:
        _lucchetto_pool = (ciclo, asyncio.Lock())
    return _lucchetto_pool[1]


@dataclass(frozen=True)
class Identita:
    """L'identità risolta: chi è l'operatore, per il database."""

    email: str
    ruolo_db: str
    casa_id: int | None


async def _prepara_connessione(conn: asyncpg.Connection) -> None:
    """Decodifica `jsonb` in Python invece che in stringa JSON.

    Senza questo, `asyncpg` restituisce `jsonb` come **stringa**: `orari` arriverebbe a `orari_da_jsonb` come testo
    e la funzione, che cerca un dizionario, risponderebbe sempre «stato non determinabile» — cioè ogni luogo della
    memoria risulterebbe senza orari noti, e con `aperto_adesso=true` verrebbero tutti trattati come «orari non
    disponibili». È un difetto silenzioso (la risposta resta valida e plausibile), quindi va chiuso qui, dove vale
    per ogni connessione del pool, e non nel punto in cui il sintomo si vede.
    """
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def apri_pool(settings: Settings | None = None) -> asyncpg.Pool:
    """Apre il pool di connessioni (una volta per processo).

    `min_size=1` e `max_size=4`: lo shim ha un solo worker e un tetto di 256 MB (`mem_limit` del compose); un pool
    più grande aprirebbe connessioni che il database paga senza che lo shim le usi.

    Il lucchetto serve al riavvio a caldo (`pool_pronto`): due richieste che scoprono insieme il pool assente
    aprirebbero due pool, e il secondo resterebbe orfano con le sue connessioni.
    """
    global _pool
    async with _lucchetto():
        if _pool is None:
            impostazioni = settings or get_settings()
            _pool = await asyncpg.create_pool(
                dsn=impostazioni.database_url,
                min_size=1,
                max_size=4,
                # Senza questo, `create_pool` aspetta il default di asyncpg (60 s) e una richiesta con il database
                # giù resterebbe appesa invece di rispondere 503 entro il tempo dichiarato (§9.1: 3 s).
                timeout=impostazioni.shim_timeout_s,
                command_timeout=impostazioni.shim_timeout_s,
                server_settings={"application_name": "trasi-shim"},
                init=_prepara_connessione,
            )
    return _pool


async def pool_pronto() -> asyncpg.Pool:
    """Il pool, **aprendolo adesso** se l'avvio non c'è riuscito.

    L'apertura all'avvio non è una garanzia: lo shim e `db_trasi` partono insieme e Postgres impiega qualche
    secondo ad accettare connessioni. Un `_pool = None` permanente trasformerebbe quel ritardo in un guasto
    definitivo — ogni endpoint tranne `healthz` risponderebbe 503 «database non raggiungibile» fino al riavvio a
    mano del container, con il database invece vivo (osservato: `operationId=oggi status=503 ms=0` per ore).

    Quindi il pool si apre alla **prima richiesta** che ne ha bisogno, non solo all'avvio: il fallimento
    all'avvio è un avviso, non uno stato.
    """
    if _pool is not None:
        return _pool
    try:
        return await apri_pool()
    except Exception as errore_connessione:
        # Il chiamante vede il motivo del contratto, non lo stacktrace del driver (§9.1).
        logger.warning("pool non apribile: %s", type(errore_connessione).__name__)
        raise errore(503, DETAIL_DATABASE_NON_RAGGIUNGIBILE) from errore_connessione


async def chiudi_pool() -> None:
    """Chiude il pool (allo spegnimento dell'applicazione)."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def _pool_corrente() -> asyncpg.Pool:
    """Il pool **già aperto**; se l'applicazione non l'ha aperto, è un errore di configurazione, non di rete."""
    if _pool is None:
        raise errore(503, DETAIL_DATABASE_NON_RAGGIUNGIBILE)
    return _pool


def chiave_valida(chiave: str | None, settings: Settings | None = None) -> bool:
    """La `X-Trasi-Key` è quella configurata?

    Una chiave configurata vuota **non** autentica nessuno: senza `TRASI_SHIM_KEY` lo shim non parte servendo
    richieste, altrimenti chiunque nella rete `trasi_net` impersonerebbe una Casa.
    """
    impostazioni = settings or get_settings()
    attesa = impostazioni.trasi_shim_key
    return bool(attesa) and chiave == attesa


async def risolvi_identita(email: str, *, conn: asyncpg.Connection | None = None) -> Identita | None:
    """`identita_onyx`: email → (ruolo_db, casa_id), con cache breve.

    `None` significa «non riconosciuta»: email assente dalla tabella oppure `attiva = false`. Chi chiama decide lo
    status; qui non si solleva nulla, perché la stessa funzione serve sia alla dipendenza sia ai test.
    """
    adesso = time.monotonic()
    in_cache = _cache_identita.get(email)
    if in_cache is not None and adesso - in_cache[0] < TTL_IDENTITA_S:
        return in_cache[1]

    riga = None
    if conn is not None:
        riga = await conn.fetchrow(
            "SELECT ruolo_db, casa_id FROM trasi.identita_onyx WHERE email = $1 AND attiva", email
        )
    else:
        pool = await pool_pronto()
        async with pool.acquire() as connessione:
            riga = await connessione.fetchrow(
                "SELECT ruolo_db, casa_id FROM trasi.identita_onyx WHERE email = $1 AND attiva", email
            )

    identita = Identita(email=email, ruolo_db=riga["ruolo_db"], casa_id=riga["casa_id"]) if riga else None
    _cache_identita[email] = (adesso, identita)
    return identita


def svuota_cache_identita() -> None:
    """Azzera la cache dell'identità (usata dai test: un'identità appena creata deve essere visibile subito)."""
    _cache_identita.clear()


class Sessione:
    """Una richiesta autenticata, dentro la transazione con il ruolo della Casa.

    Le query del chiamante girano **già** dentro `BEGIN; SET LOCAL ROLE <ruolo_db>; …; COMMIT`: nessun endpoint
    ripete la sequenza, e nessuno può dimenticarla.
    """

    def __init__(self, conn: asyncpg.Connection, email: str, ruolo: str, casa_id: int | None) -> None:
        self.conn = conn
        self.email = email
        self.ruolo = ruolo
        self.casa_id = casa_id

    async def fetch(self, sql: str, *args: Any) -> list[asyncpg.Record]:
        """Le righe della query, nella transazione della richiesta."""
        return await self.conn.fetch(sql, *args)

    async def fetchrow(self, sql: str, *args: Any) -> asyncpg.Record | None:
        """La prima riga, o `None`."""
        return await self.conn.fetchrow(sql, *args)

    async def fetchval(self, sql: str, *args: Any) -> Any:
        """Il primo valore della prima riga, o `None`."""
        return await self.conn.fetchval(sql, *args)

    async def execute(self, sql: str, *args: Any) -> str:
        """Esegue e ritorna lo statuscommand (es. `"UPDATE 0"`): la RLS che nega si legge da qui."""
        return await self.conn.execute(sql, *args)


def _email_dal_path(request: Request) -> str:
    """L'email dal percorso `/v1/u/{email}/…`, che è anche l'email sostituita da Onyx in `servers[0].url`."""
    return request.path_params.get("email", "")


def _chiave_dalla_richiesta(request: Request) -> str | None:
    """La chiave dello shim, dall'header. Mai dai query parameter: finirebbe nei log di ogni proxy."""
    return request.headers.get(HEADER_CHIAVE)


async def dipendenza_sessione(request: Request) -> AsyncIterator[Sessione]:
    """La dipendenza FastAPI: autentica, risolve l'identità, apre la transazione con il ruolo della Casa.

    Ordine deliberato: la chiave si verifica **prima** di qualunque cosa tocchi il database (401 senza connessione),
    e l'identità si risolve **come `shim_rw`** (l'unica lettura ammessa senza ruolo Casa). Solo dopo si entra nel
    ruolo, che è ciò che la RLS usa per decidere.

    L'email si legge da `request.path_params` e non da un parametro dichiarato: dichiararla la farebbe interpretare
    da FastAPI come parametro di query in ogni route che la usa, e una `email` nella query string è esattamente la
    cosa che non deve esistere (finirebbe nei log dei proxy).
    """
    settings = get_settings()

    if not chiave_valida(_chiave_dalla_richiesta(request), settings):
        raise errore(401, DETAIL_CHIAVE_NON_VALIDA)

    email_operatore = _email_dal_path(request)
    if not email_operatore:
        raise errore(403, DETAIL_IDENTITA_NON_RICONOSCIUTA)

    identita = await risolvi_identita(email_operatore)
    if identita is None:
        # Nessuna query applicativa è stata eseguita: l'unica lettura è stata la risoluzione dell'identità.
        raise errore(403, DETAIL_IDENTITA_NON_RICONOSCIUTA)

    pool = await pool_pronto()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # `SET LOCAL ROLE` non ammette parametri: si interpola con `format` dopo aver verificato che il ruolo
            # esista in `identita_onyx` ed è quindi un valore del database, non un input del chiamante. Il controllo
            # di forma (solo lettere, cifre e underscore) è la seconda barriera, non la prima.
            if not identita.ruolo_db.replace("_", "").isalnum():
                raise errore(403, DETAIL_IDENTITA_NON_RICONOSCIUTA)
            try:
                await conn.execute(f"SET LOCAL ROLE {identita.ruolo_db}")
            except InsufficientPrivilegeError as exc:
                # L'identità ESISTE in `identita_onyx` ed è attiva, ma `shim_rw` non è membro del suo ruolo e non
                # può assumerlo (`db/000_roles.sql`: tutte le Case più `rete`, e **non** `ti` — revoca deliberata,
                # perché il TI non passa dalla chat). Il caso è reale e non teorico: `ti@trasi.local` è un'identità
                # attiva con un utente Onyx, quindi la si raggiunge dalla chat come le altre.
                #
                # Senza questo ramo l'eccezione attraversa la dipendenza, l'handler generico la rende un **500
                # «errore interno dello shim»** e l'operatore legge un guasto al posto di «il tuo ruolo non è
                # abilitato» — con il difetto a monte (una riga di `000_roles.sql`) che diventa invisibile a chi
                # diagnostica. Misurato: 21 identità su 22 rispondevano 200, `ti` rispondeva 500 su ogni endpoint.
                # Il ruolo NON viene concesso qui: la lacuna si dichiara, non si allarga (V4, least-privilege).
                logger.warning("ruolo %s non assumibile da shim_rw", identita.ruolo_db)
                raise errore(403, DETAIL_RUOLO_SENZA_ACCESSO) from exc
            # Solo il ruolo esce dalla richiesta verso il log: l'email no (log senza corpo, V5/§12).
            request.state.ruolo = identita.ruolo_db
            yield Sessione(conn, identita.email, identita.ruolo_db, identita.casa_id)


# Alias con il nome usato dai router: `Depends(sessione)`.
sessione = dipendenza_sessione


async def parametri(sess: Sessione, chiavi: Sequence[str]) -> dict[str, Any]:
    """I parametri `[P]` richiesti, in una sola query, con `NULL` per le chiavi assenti.

    Una sola andata e ritorno invece di una per chiave: i parametri si leggono a ogni chiamata di `vicino_a`, e
    pagare quattro round-trip per una risposta da 3 secondi non è giustificato. `p_int`/`p_text` del database
    ritornano `NULL` se la chiave manca — qui si fa lo stesso, e chi legge decide il default.
    """
    righe = await sess.fetch(
        "SELECT chiave, valore, tipo FROM trasi.parametro WHERE chiave = ANY($1::text[])", list(chiavi)
    )
    valori: dict[str, Any] = {chiave: None for chiave in chiavi}
    for riga in righe:
        valore = riga["valore"]
        if riga["tipo"] == "int":
            try:
                valore = int(str(valore))
            except ValueError:
                valore = None
        elif riga["tipo"] == "bool":
            valore = str(valore).lower() in ("true", "t", "on", "1")
        valori[riga["chiave"]] = valore
    return valori


def parametro_int(valori: dict[str, Any], chiave: str, default: int) -> int:
    """Il parametro intero, o il default quando manca (il database non garantisce che tutte le chiavi esistano)."""
    valore = valori.get(chiave)
    return valore if isinstance(valore, int) else default


__all__ = [
    "HEADER_CHIAVE",
    "HEADER_EMAIL",
    "Identita",
    "Sessione",
    "apri_pool",
    "chiave_valida",
    "chiudi_pool",
    "dipendenza_sessione",
    "parametri",
    "parametro_int",
    "risolvi_identita",
    "sessione",
    "svuota_cache_identita",
]


async def slug_casa_da_identita(sess: "Sessione") -> str:
    """Lo slug della Casa dell'operatore autenticato, dalla sua identità.

    Esiste per togliere al LLM un dato che non può conoscere: un assistente generico non sa da
    quale Casa sta parlando l'operatore, e chiederglielo produce risposte evasive («di quale Casa
    parliamo?») o, peggio, uno slug inventato. L'identità invece lo determina in modo esatto.

    Ritorna "" per un ruolo senza Casa (es. `rete`), così il chiamante decide: gli endpoint che
    richiedono una Casa rispondono 422 con un messaggio esplicito.
    """
    if sess.casa_id is None:
        return ""
    slug = await sess.fetchval("SELECT slug FROM trasi.casa WHERE id = $1", sess.casa_id)
    return slug or ""
