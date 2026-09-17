"""Autenticazione degli operatori delle Case di Quartiere (scheda !NEW 6, decisione §2).

Percorso proprio, **fuori** dal prefisso `/v1/u/{email}` che è riservato alle chiamate server-to-server di Onyx:
il browser dell'operatore si autentica qui con le credenziali della Casa (non un account personale — un solo account
per CdQ, decisione 2026-09-16) e riceve un cookie di sessione. Da quel momento gli endpoint `/op/…` — e solo quelli —
funzionano col cookie, senza redirect verso il sottodominio Onyx (correzione #3).

Tre decisioni non negoziabili, e dove vivono:

- **Nessun segreto nel codice e nessun hash in Python.** La password è verificata da `trasi.crea_sessione` (bcrypt di
  pgcrypto, dentro il database): lo shim passa slug e password *sulla connessione applicativa già autenticata* e
  riceve un token oppure `NULL`. `passlib` non è nemmeno nelle dipendenze: se l'hash vivesse qui, chi legge il
  container potrebbe provare password offline, fuori dalla RLS.
- **Il blocco anti brute-force è del database** (`>4 fallimenti/10 min` → `NULL` + audit `login_bloccato`): se fosse
  dello shim, riavviare il container lo azzererebbe. Al chiamante arriva **un solo 401 indistinto** per «casa
  sconosciuta» e «password errata» — altrimenti gli slug delle dieci Case sarebbero enumerabili — e un 401 dedicato
  solo per il blocco (il runbook §«Login operatore CdQ» lo chiede, e il blocco non è enumerabile: è proprio).
- **Cookie `HttpOnly` + `SameSite=Lax` + TTL dal parametro `[P] session_ttl_hours`**, letto a ogni login così il TI
  lo cambia senza riavvio. Il valore è un UUID opaco, non un JWT firmato: revocarlo è un `DELETE`, e lo shim non
  custodisce una chiave di firma in più.

Log senza corpo (V5/§12): da qui non si registra mai né slug né password né token; il middleware scrive il `ruolo`
della sessione e basta.

**Sessioni di servizio (`rete`/`pa`, US-4).** La stessa conversazione — login, cookie, logout — vale anche per i due
ruoli senza Casa: l'operatore referente (`rete`, approva i report) e la Pubblica Amministrazione (`pa`, li legge).
Le differenze sono nel database, non in un secondo meccanismo: la credenziale vive in `trasi.credenziale_servizio`,
la sessione porta `ruolo_db` invece di `casa_id` (CHECK mutuamente esclusivo, db/026), e la creazione è
`trasi.crea_sessione_servizio` con lo stesso anti-brute-force. Il cookie è lo **stesso** (`trasi_sessione`): due
cookie significherebbero due logout e una sessione che resta accesa quando l'altra è stata chiusa.

**Dipendenza `sessione_corrente`** (in coda al modulo): è la guardia di tutti gli endpoint `/op/…`. Valida il cookie
sul DB a ogni richiesta (scadenza e revoca sono immediate, non attendono il TTL), risolve la Casa e apre la
transazione `BEGIN; SET LOCAL ROLE <ruolo_db>` — lo stesso modello della dipendenza Onyx, così la RLS decide come
per ogni altra via. Senza cookie valido: **401 JSON**, mai redirect (la Home è statica e gestisce lei la pagina di
accesso).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any, Literal

import asyncpg
from asyncpg.exceptions import RaiseError
from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from .db import Sessione, _pool_corrente
from .errori import errore

router = APIRouter()

# Nome del cookie di sessione, dichiarato una volta sola: `logout` deve scadere lo stesso cookie che `login` scrive.
# Prefisso `__Host-` non usato finché lo stack serve anche in HTTP loopback (HOST_PORT_CADDY_HTTP), perché quel
# prefisso pretende `Secure` e il browser lo scarterebbe in chiaro.
COOKIE_SESSIONE = "trasi_sessione"

# Dettagli esposti al chiamante. Casa inesistente e password errata condividono lo **stesso** dettaglio: risposte
# diverse renderebbero gli slug enumerabili.
DETAIL_CREDENZIALI_NON_VALIDE = "casa o password non valide"
DETAIL_TROPPI_TENTATIVI = "troppi tentativi: accesso bloccato, riprovare più tardi"
DETAIL_SESSIONE_NON_VALIDA = "sessione assente o scaduta"
DETAIL_RUOLO_SBAGLIATO = "questa area richiede un altro ruolo: sessione non valida per il ruolo richiesto"

# La forma ammessa per il `ruolo_db` di una sessione di servizio: lettere minuscole e `_`, nient'altro. È la barriera
# davanti al `SET LOCAL ROLE …`: il valore viene dal DB (non dall'input), ma un nome di identificatore non ammette
# parametri, quindi la forma si verifica e basta — anche chi applica una migrazione malata non può trasformare una
# riga di `sessione` in SQL arbitrario.
_RUOLO_PERMESSO = re.compile(r"^[a-z][a-z_]*$")

# Fallback documentato del TTL (12 ore) se il parametro `[P]` manca o non è un intero: è il default scritto nel
# seed di db/003, ripetuto qui perché il login non deve fallire per un parametro assente.
TTL_FALLBACK_SECONDI = 12 * 3600


class Credenziali(BaseModel):
    """Il corpo di `POST /login`: le **sole** due chiavi ammesse (`extra="forbid"`, V5).

    `casa` è lo **slug** della Casa (`san-bao`, `bozzano`, …), non il nome: un account per CdQ, niente persona. La
    password viaggia nel corpo JSON, mai nella query string: un query parameter finirebbe nei log dei proxy.
    """

    model_config = ConfigDict(extra="forbid")

    casa: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


class CredenzialiServizio(BaseModel):
    """Il corpo di `POST /servizio/login`: **le sole** due chiavi ammesse (`extra="forbid"`, V5).

    `ruolo` è il nome del ruolo di servizio (`pa` per la Pubblica Amministrazione, `rete` per il referente AT), non
    un identificatore personale: un solo accesso per ruolo, come per le Case. La password viaggia nel corpo JSON,
    mai nella query string.
    """

    model_config = ConfigDict(extra="forbid")

    ruolo: Literal["pa", "rete"]
    password: str = Field(min_length=1, max_length=200)


class SessioneOperatore:
    """La sessione del browser dell'operatore, validata sul DB a ogni richiesta.

    Eredita i cinque metodi di query da `Sessione` e aggiunge lo `slug` della Casa: gli endpoint `/op/…` ragionano
    quasi sempre per slug (è ciò che la UI e il runbook mostrano), e ricavarlo qui una volta sola toglie una
    query ridondante a ogni endpoint. Niente email, mai: questo canale non conosce l'identità Onyx dell'operatore.
    """

    def __init__(self, base: Sessione, casa_slug: str, token: uuid.UUID) -> None:
        self._base = base
        self.ruolo = base.ruolo
        self.casa_id = base.casa_id
        self.casa_slug = casa_slug
        self.token = token

    async def fetch(self, sql: str, *args: Any):
        return await self._base.fetch(sql, *args)

    async def fetchrow(self, sql: str, *args: Any):
        return await self._base.fetchrow(sql, *args)

    async def fetchval(self, sql: str, *args: Any):
        return await self._base.fetchval(sql, *args)

    async def execute(self, sql: str, *args: Any):
        return await self._base.execute(sql, *args)


class SessioneServizio:
    """La sessione del browser della PA o del referente di rete, validata sul DB a ogni richiesta.

    Stessa forma di `SessioneOperatore`, senza Casa: il canale conosce il **ruolo** (`pa` o `rete`) e basta. Non è
    una sessione speciale: è la stessa tabella `trasi.sessione` con `ruolo_db` valorizzato al posto di `casa_id`,
    guardata dal CHECK mutuamente esclusivo di db/026.
    """

    def __init__(self, base: Sessione, ruolo: str, token: uuid.UUID) -> None:
        self._base = base
        self.ruolo = ruolo
        self.token = token

    async def fetch(self, sql: str, *args: Any):
        return await self._base.fetch(sql, *args)

    async def fetchrow(self, sql: str, *args: Any):
        return await self._base.fetchrow(sql, *args)

    async def fetchval(self, sql: str, *args: Any):
        return await self._base.fetchval(sql, *args)

    async def execute(self, sql: str, *args: Any):
        return await self._base.execute(sql, *args)


def _token_dal_cookie(request: Request) -> uuid.UUID | None:
    """Il token della sessione, solo dal cookie HttpOnly; mai da query string né dal corpo (V5 / log senza corpo)."""
    grezzo = request.cookies.get(COOKIE_SESSIONE)
    if not grezzo:
        return None
    try:
        return uuid.UUID(grezzo)
    except ValueError:
        return None


async def _ttl_secondi() -> int:
    """`[P] session_ttl_hours` in secondi, letto a ogni login: il TI lo cambia senza riavviare lo shim."""
    async with _pool_corrente().acquire() as conn:
        valore = await conn.fetchval(
            "SELECT valore FROM trasi.parametro WHERE chiave = 'session_ttl_hours'"
        )
    try:
        ore = int(str(valore)) if valore is not None else 0
    except (TypeError, ValueError):
        ore = 0
    return ore * 3600 if ore > 0 else TTL_FALLBACK_SECONDI


async def dipendenza_sessione_corrente(request: Request) -> AsyncIterator[SessioneOperatore]:
    """La dipendenza dei `/op/…`: cookie valido → transazione con il ruolo della Casa; altrimenti 401 JSON.

    Il token è cercato in `trasi.sessione` **a ogni richiesta** (la tabella porta la scadenza e la revoca): un
    cookie scaduto o cancellato da `/logout` smette subito di aprire, indipendentemente dal `max_age` del browser.

    Se il token esiste ma punta a una Casa senza ruolo dichiarato (`ruolo_casa`), la sessione è rifiutata: lo shim
    non improvvisa un ruolo, perché la RLS è l'autorità e un ruolo mancante è una configurazione da correggere nel
    DB, non da aggirare qui.
    """
    token = _token_dal_cookie(request)
    if token is None:
        raise errore(401, DETAIL_SESSIONE_NON_VALIDA)

    pool = _pool_corrente()
    async with pool.acquire() as conn:
        riga = await conn.fetchrow(
            """
            SELECT s.casa_id, c.slug, rc.ruolo
              FROM trasi.sessione s
              JOIN trasi.casa c ON c.id = s.casa_id
              JOIN trasi.ruolo_casa rc ON rc.casa_id = c.id
             WHERE s.token = $1 AND s.scade_ts > now()
            """,
            token,
        )
        if riga is None:
            raise errore(401, DETAIL_SESSIONE_NON_VALIDA)

        ruolo = riga["ruolo"]
        # Interpolazione difesa due volte: il valore arriva da `ruolo_casa` (dato del DB, non input), e qui si
        # verifica la forma prima dell'unico punto dello shim in cui un identificatore non può essere un parametro.
        if not ruolo or not ruolo.replace("_", "").isalnum():
            raise errore(401, DETAIL_SESSIONE_NON_VALIDA)

        async with conn.transaction():
            await conn.execute(f"SET LOCAL ROLE {ruolo}")
            # Solo il ruolo esce verso il log (middleware): né slug né token (V5/§12).
            request.state.ruolo = ruolo
            yield SessioneOperatore(Sessione(conn, "", ruolo, riga["casa_id"]), riga["slug"], token)


# Alias con il nome del contratto: gli endpoint scrivono `Depends(sessione_corrente)`.
sessione_corrente = dipendenza_sessione_corrente


async def _dipendenza_sessione_servizio(
    request: Request, ruolo_atteso: str, morbido: bool = False
) -> AsyncIterator[SessioneServizio]:
    """Cookie valido con `ruolo_db = ruolo_atteso` → transazione con quel ruolo; altrimenti 401.

    La risoluzione del token **non** presuppone il ruolo: il cookie è quello di una sessione, e il confronto con il
    ruolo atteso è una decisione applicativa — così chi tiene un cookie di servizio può verificare da solo con
    `GET /pa/me` se è rimasto dentro la sessione scaduta (401) senza che lo shim sveli quale ruolo il token porta.

    La query legge **solo** `sessione`: `ruolo_db` su una sessione di Casa è `NULL` per il CHECK di db/026, quindi
    il confronto stringa basta a escluderle — non serve un JOIN che distingua i due casi, perché la distinzione è
    già un vincolo del database. Il formato del ruolo è verificato prima dell'`SET LOCAL ROLE`: identificatori non
    parametrici si possono solo interpolare, e la forma è la barriera giusta per una stringa che il DB vincola ma
    che non è un parametro.

    `morbido=True` è il modo in cui la factory multi-ruolo (`sessione_servizio_tra`) *chiede* la prova di un
    ruolo senza chiudere: il mismatch non solleva, semplicemente non produce niente — e la factory prova il
    ruolo successivo. Gli 401 dei casi davvero fuori accesso (cookie assente, scaduto, ruolo malformato) restano
    intatti: il "morbido" riguarda solo il **confronto del ruolo**.
    """
    token = _token_dal_cookie(request)
    if token is None:
        raise errore(401, DETAIL_SESSIONE_NON_VALIDA)

    pool = _pool_corrente()
    async with pool.acquire() as conn:
        ruolo = await conn.fetchval(
            "SELECT ruolo_db FROM trasi.sessione WHERE token = $1 AND scade_ts > now()", token
        )
        if ruolo is None or not _RUOLO_PERMESSO.match(str(ruolo)):
            raise errore(401, DETAIL_SESSIONE_NON_VALIDA)
        if ruolo != ruolo_atteso:
            if morbido:
                return
            raise errore(401, DETAIL_RUOLO_SBAGLIATO)

        async with conn.transaction():
            await conn.execute(f"SET LOCAL ROLE {ruolo}")
            request.state.ruolo = ruolo
            yield SessioneServizio(Sessione(conn, "", ruolo, None), ruolo, token)


def sessione_servizio_corrente(ruolo_atteso: str) -> Callable[[Request], AsyncIterator[SessioneServizio]]:
    """La guardia degli endpoint del servizio (`/pa/…`, la dashboard del monitoraggio US-4).

    `ruolo_atteso` è il nome del ruolo di servizio (`pa` o `rete`): i due canali condividono lo stesso cookie e la
    stessa dipendenza, e il confronto decide se questo browser è autorizzato a *questa* area. Una sessione di Casa
    passa qualsiasi `/op/…` e qui trova il 401 dedicato, perché il contratto delle due aree è diverso.
    """

    async def guardia(request: Request) -> AsyncIterator[SessioneServizio]:
        async for sessione in _dipendenza_sessione_servizio(request, ruolo_atteso):
            yield sessione

    return guardia


def sessione_servizio_tra(ruoli: tuple[str, ...]) -> Callable[[Request], AsyncIterator[SessioneServizio]]:
    """Una sessione di servizio valida per **uno qualsiasi** dei ruoli elencati (dashboard condivisa US-4).

    La dashboard del monitoraggio è letta sia da `pa` (Pubblica Amministrazione) sia da `rete` (referente AT, che
    approva): la stessa superficie, due identità. `sessione_servizio_corrente` tiene UN solo ruolo atteso; per
    la dashboard condivisa si usa questa factory, che prova i ruoli nell'ordine dato e 401 solo se nessuno
    corrisponde. `@router.get("/me")` resta multi-ruolo perché è il modo in cui il browser sa chi è entrato.
    """

    async def guardia(request: Request) -> AsyncIterator[SessioneServizio]:
        for ruolo in ruoli:
            async for sessione in _dipendenza_sessione_servizio(request, ruolo, morbido=True):
                yield sessione
                return
        raise errore(401, DETAIL_SESSIONE_NON_VALIDA)

    return guardia


@router.post(
    "/login",
    operation_id="login_operatore",
    summary="Accede con le credenziali della Casa di Quartiere (una per CdQ) e apre la sessione: "
    "risponde solo con lo slug, e mette il token in un cookie HttpOnly.",
    tags=["op"],
)
async def login(corpo: Credenziali, risposta: Response) -> dict[str, Any]:
    """POST /login `{casa, password}` → 200 `{casa, sessione}` + cookie `trasi_sessione`; 401 se credenziali errate.

    Il confronto della password è delegato a `trasi.crea_sessione` (bcrypt/pgcrypto): qui si conosce l'esito, non il
    segreto. `NULL` e un `RaiseError` di blocco hanno messaggi distinti *perché il blocco è una stato proprio*,
    mentre «casa sconosciuta» e «password errata» restano indistinguibili.
    """
    slug = corpo.casa.strip().lower()
    try:
        async with _pool_corrente().acquire() as conn:
            token = await conn.fetchval(
                "SELECT trasi.crea_sessione($1, $2)", slug, corpo.password
            )
    except RaiseError as exc:
        # La funzione solleva soltanto per il blocco anti-forza; il suo testo non è propagato (potrebbe cambiare e
        # non deve diventare contratto), il messaggio al chiamante è quello dichiarato qui.
        raise errore(401, DETAIL_TROPPI_TENTATIVI) from exc

    if token is None:
        raise errore(401, DETAIL_CREDENZIALI_NON_VALIDE)

    ttl = await _ttl_secondi()
    risposta.set_cookie(
        COOKIE_SESSIONE,
        value=str(token),
        max_age=ttl,
        httponly=True,
        samesite="lax",
        # `secure` spento finché lo stack serve anche in HTTP loopback; davanti al tunnel HTTPS si accende a
        # configurazione, senza cambiare codice (fuori perimetro di questa scheda).
        secure=False,
        path="/",
    )
    # Il token non è mai nel corpo JSON: solo lo slug, che la Home mostra come «operatore di …».
    return {"casa": slug, "sessione": "aperta"}


@router.post(
    "/servizio/login",
    operation_id="login_servizio",
    summary="Accede come PA o referente di rete: cookie di sessione sulle credenziali di `credenziale_servizio`.",
    tags=["servizio"],
)
async def login_servizio(corpo: CredenzialiServizio, risposta: Response) -> dict[str, Any]:
    """POST /servizio/login `{ruolo, password}` → 200 `{ruolo, sessione}` + cookie; 401 su fallimento e sul blocco.

    Il confronto della password è delegato a `trasi.crea_sessione_servizio` (bcrypt/pgcrypto): qui si conosce l'esito,
    non il segreto. `NULL` significa «credenziali non valide» (il blocco anti-brute-force è sollevato dalla funzione
    come `RaiseError` con `login_bloccato` nel testo, e qui diventa il proprio 401: è uno stato dedicato, non una
    variazione di «chi sei»). Ruolo sconosciuto e password errata restano indistinguibili: risposte diverse
    renderebbero i ruoli enumerabili.
    """
    try:
        async with _pool_corrente().acquire() as conn:
            token = await conn.fetchval(
                "SELECT trasi.crea_sessione_servizio($1, $2)", corpo.ruolo, corpo.password
            )
    except RaiseError as exc:
        # La funzione solleva per il blocco anti-forza; il suo testo non è propagato: il messaggio al chiamante è
        # quello dichiarato qui.
        raise errore(401, DETAIL_TROPPI_TENTATIVI) from exc

    if token is None:
        raise errore(401, DETAIL_CREDENZIALI_NON_VALIDE)

    ttl = await _ttl_secondi()
    risposta.set_cookie(
        COOKIE_SESSIONE,
        value=str(token),
        max_age=ttl,
        httponly=True,
        samesite="lax",
        # `secure` spento finché lo stack serve anche in HTTP loopback; davanti al tunnel HTTPS si accende a
        # configurazione, senza cambiare codice.
        secure=False,
        path="/",
    )
    return {"ruolo": corpo.ruolo, "sessione": "aperta"}


@router.post(
    "/logout",
    operation_id="logout_operatore",
    summary="Chiude la sessione: revoca il token sul DB e scade subito il cookie. Idempotente: "
    "funziona identico anche senza sessione aperta.",
    tags=["op"],
)
async def logout(request: Request) -> Response:
    """POST /logout → 204 con cookie scaduto. Sempre 204, con o senza cookie valido.

    «Sempre lo stesso esito» è la regola: un 401 su cookie assente direbbe a chi osserva che la sessione **non**
    esisteva, e non serve. La revoca è un `DELETE` (la sessione è credenziale, non memoria); se il token non c'è
    più il comando tocca zero righe, che è già lo stato desiderato.
    """
    token = _token_dal_cookie(request)
    if token is not None:
        async with _pool_corrente().acquire() as conn:
            await conn.execute("DELETE FROM trasi.sessione WHERE token = $1", token)

    risposta = Response(status_code=204)
    risposta.delete_cookie(COOKIE_SESSIONE, path="/")
    return risposta


@router.get(
    "/me",
    operation_id="identita_operatore",
    summary="Chi è questa sessione: slug e id della Casa, nessun dato personale. 401 se il cookie è "
    "assente o scaduto.",
    tags=["op"],
)
async def me(sess: SessioneOperatore = Depends(sessione_corrente)) -> dict[str, Any]:
    """GET /me → `{casa, casa_id, ruolo}`: ciò che la Home mostra per confermare «sei entrato come …».

    Il `ruolo` è esposto perché è il vocabolario del runbook (`casa_sanbao`, …) e non un segreto: chiunque abbia la
    sessione lo possiede già di fatto. L'email dell'operatore **non** esiste in questo canale e non esce.
    """
    return {"casa": sess.casa_slug, "casa_id": sess.casa_id, "ruolo": sess.ruolo}


__all__ = [
    "COOKIE_SESSIONE",
    "DETAIL_CREDENZIALI_NON_VALIDE",
    "DETAIL_RUOLO_SBAGLIATO",
    "Credenziali",
    "CredenzialiServizio",
    "SessioneOperatore",
    "SessioneServizio",
    "login",
    "login_servizio",
    "logout",
    "me",
    "router",
    "sessione_corrente",
    "sessione_servizio_corrente",
]
