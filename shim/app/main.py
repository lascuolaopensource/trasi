"""Applicazione FastAPI dello shim Trasi (B3): le nove operazioni del contratto congelato in B0 (gate V-09).

Lo stub di B0 è sostituito dall'implementazione reale. Il contratto `shim/openapi.yaml` **non cambia**: le
`operationId`, gli schemi e l'unico `servers[].url` sono quelli che Onyx ha già registrato come tool custom, e questo
modulo si limita a servire quegli indirizzi derivando il prefisso dal documento (§`contratto.prefisso_path`).

Tre cose vivono qui e in nessun altro posto:

- **il montaggio dei router**, così il prefisso è calcolato una volta sola dal contratto congelato;
- **il log delle richieste senza corpo** (V5/§12): `ts, method, operationId, status, ms, ruolo` e nient'altro. Non
  l'email, non i query parameter, non `motivazione`, non `payload`, non le coordinate. È l'invariante che il piano
  verifica cercando `@trasi.local` o `motivazione` nel log e attendendosi zero occorrenze;
- **la vita del pool di connessioni**, aperto all'avvio e chiuso allo spegnimento.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request

from . import routes_geo, routes_lettura
from .contratto import meta, operazioni, prefisso_path, url_server
from .db import apri_pool, chiudi_pool
from .errori import installa_handler
from .settings import get_settings
from .vicinanza import FUSO

logger = logging.getLogger("trasi.shim")

# Le operazioni del contratto congelato. La tupla è la dichiarazione **indipendente** delle `operationId`:
# i test la confrontano con `openapi.yaml` e con i router, e l'import fallisce se una diverge.
FIRMA_OPERAZIONI: tuple[tuple[str, str], ...] = (
    ("cerca_luogo", "GET"),
    ("eventi_oggi", "GET"),
    ("vicino_a", "GET"),
    ("registra_richiesta", "POST"),
    ("crea_evento", "POST"),
    # `salva_dato` è la scrittura **diretta** della propria Casa (scheda, opportunità, orari): la
    # specifica del gruppo Processi — «ogni casa/ente può modificare i propri dati, della propria
    # casa» — con un accesso solo per Casa, che rende impossibile la proposta→approvazione su un dato
    # proprio (BUG-02). Sostituisce i cinque tipi di proposta che finivano in un vicolo cieco.
    ("salva_dato", "POST"),
    ("proponi_modifica", "POST"),
    ("approva_proposta", "POST"),
    ("biglietto", "GET"),
    ("oggi", "GET"),
    ("statistiche", "GET"),
    ("cerca_web", "GET"),
)


def _operation_id_del_contratto() -> dict[str, dict]:
    """Le operazioni del contratto indicizzate per `operationId`."""
    return {operazione["operationId"]: operazione for operazione in operazioni()}


@asynccontextmanager
async def _vita(applicazione: FastAPI):
    """Apre il pool all'avvio e lo chiude allo spegnimento.

    Se il database non è raggiungibile all'avvio, l'applicazione **parte comunque**: il fallimento di una dipendenza
    non deve impedire a `healthz` di rispondere, altrimenti un healthcheck darebbe «unhealthy» su un servizio che è
    vivo e che risponde 503 con un motivo leggibile alle richieste che il database lo richiedono davvero.
    """
    try:
        await apri_pool(applicazione.state.settings)
    except Exception:
        logger.warning("pool di connessioni non aperto all'avvio: il database non è raggiungibile")
    try:
        yield
    finally:
        await chiudi_pool()


def _registra_richiesta(request: Request, status: int, durata_ms: int, ruolo: str) -> None:
    """Una riga di log per richiesta, **senza corpo**: `ts, method, operationId, status, ms, ruolo`.

    L'`operationId` viene dalla route risolta da Starlette, non dall'URL: l'URL contiene l'email dell'operatore e
    registrarlo vanificherebbe l'intero presidio. Il ruolo si legge dallo stato messo dalla dipendenza di sessione:
    è l'informazione che serve a capire «chi ha fatto cosa» senza sapere *chi*.
    """
    route = request.scope.get("route")
    operation_id = getattr(route, "operation_id", None) or getattr(route, "name", "-")
    logger.info(
        "ts=%s method=%s operationId=%s status=%s ms=%s ruolo=%s",
        datetime.now(FUSO).isoformat(timespec="seconds"),
        request.method,
        operation_id,
        status,
        durata_ms,
        ruolo or "-",
    )


def _configura_log() -> None:
    """Accende il log applicativo e **zittisce** quello delle librerie HTTP.

    Due problemi distinti, entrambi verificati nel container:

    1. Sotto uvicorn il livello del logger `trasi.shim` è `NOTSET` con zero handler: `logger.info(...)` finirebbe nel
       nulla e il presidio «log senza corpo» sarebbe verificabile solo come assenza. Con `basicConfig` le righe
       esistono e si possono leggere.
    2. `httpx` — non uvicorn — registra a INFO l'URL di ogni richiesta uscente, e l'URL dello shim contiene l'email
       dell'operatore. `UVICORN_ACCESS_LOG=0` non lo copre, perché quella riga la emette la libreria: senza questo
       silenziamento, ogni chiamata a Overpass o SearXNG scriverebbe l'email nel log (osservato nel container).
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    # `httpx`/`httpcore` a WARNING: le loro righe INFO portano l'URL completo, che qui significa l'email.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def crea_app() -> FastAPI:
    """Costruisce l'applicazione."""
    _configura_log()
    firma = _operation_id_del_contratto()

    mancanti = sorted({operation_id for operation_id, _ in FIRMA_OPERAZIONI} - firma.keys())
    if mancanti:
        raise RuntimeError(f"operationId assenti dal contratto congelato: {mancanti}")

    applicazione = FastAPI(
        title="Trasi — shim",
        version="0.1.0",
        description=(
            "Shim d'integrazione fra Onyx e la memoria della rete delle Case di Quartiere di Brindisi. "
            "Serve le operazioni del contratto congelato in B0, all'indirizzo "
            f"{url_server()}; la RLS del database è l'unica autorità sui permessi."
        ),
        servers=[{"url": url_server()}],
        lifespan=_vita,
    )

    applicazione.state.settings = get_settings()

    installa_handler(applicazione)

    prefisso = prefisso_path()
    applicazione.include_router(routes_lettura.router, prefix=prefisso)
    applicazione.include_router(routes_geo.router, prefix=prefisso)

    # I router delle scritture e degli output sono dell'altro worker (B3ShimB) e vivono in file separati: si
    # montano **dopo** i miei e ognuno monta il proprio `router`, così nessuno riscrive il file dell'altro. Il
    # prefisso lo applica il loro `monta()`, derivandolo dal contratto congelato.
    from . import scritture, testi

    scritture.monta(applicazione)
    testi.monta(applicazione)

    # --- area operatore (schede !NEW 3/5/6/7): le funzioni del browser, non di Onyx --------------
    #
    # Questi router stanno **fuori** dal prefisso `/v1/u/{email}` del contratto congelato, e la
    # distinzione non è formale: quel prefisso è la via di Onyx (identità nell'URL, autenticata con
    # `X-Trasi-Key`), questa è la via del **browser dell'operatore**, autenticata con il cookie di
    # sessione. Tenerle separate significa che una richiesta non può accidentalmente essere valida
    # per entrambe, ed è la ragione per cui l'email dell'operatore non compare in nessuno di questi
    # indirizzi (V5: nessun identificatore nel percorso, quindi nei log dei proxy).
    #
    # Due prefissi e non uno, deliberatamente:
    #   * `auth` a radice, perché la pagina di accesso esiste **prima** della sessione: `/login` non
    #     può stare dietro un prefisso che presuppone di essere già entrati, e `/logout` e `/me`
    #     stanno con lui perché sono la stessa conversazione (chi sono / esci);
    #   * il resto sotto `/op`, così «tutto ciò che richiede una sessione operatore» è un prefisso
    #     solo, verificabile con un `grep`, e non un elenco di path da tenere a mente.
    #
    # `include_in_schema=False` su tutto il blocco, e non è un dettaglio. Lo schema OpenAPI che
    # FastAPI genera da questa applicazione **è il contratto con Onyx**, e il gate V-09 lo verifica
    # per uguaglianza: le `operationId` esposte devono essere esattamente le nove congelate in
    # `shim/openapi.yaml`. Gli endpoint dell'area operatore non sono strumenti del LLM — li chiama
    # il browser — quindi non appartengono a quel documento: dichiararli qui li tiene fuori dal
    # contratto **senza** indebolire il gate (che resta `esposte == attese`, non un suo sottoinsieme).
    from . import attrezzoteca, auth, messaggi

    applicazione.include_router(auth.router, include_in_schema=False)

    # La chat (proxy server-to-server verso Onyx) è montata con lo stesso criterio degli altri;
    # se il modulo non è ancora presente, il resto dell'area operatore continua a funzionare.
    try:
        from . import chat

        chat.monta(applicazione)
    except ImportError:  # pragma: no cover — il modulo nasce con la scheda !NEW 6
        logger.warning("chat non montata: shim/app/chat.py assente")

    applicazione.include_router(attrezzoteca.router, prefix="/op", include_in_schema=False)
    applicazione.include_router(messaggi.router, prefix="/op", include_in_schema=False)

    # `GET /op/config`: la configurazione a runtime per la Home (indirizzo di Onyx). Router nudo,
    # stessa forma di `attrezzoteca` e `messaggi`.
    from . import config_op

    applicazione.include_router(config_op.router, prefix="/op", include_in_schema=False)

    @applicazione.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        """Liveness del container: non tocca il database, così «healthy» significa «il processo risponde»."""
        return {"status": "ok"}

    @applicazione.middleware("http")
    async def _log_senza_corpo(request: Request, call_next):
        """Misura la durata e registra la richiesta senza corpo (V5/§12).

        Il middleware non legge `request.body()`: leggere il corpo per registrarlo sarebbe la violazione che questa
        funzione esiste per impedire.
        """
        inizio = time.perf_counter()
        ruolo = ""
        try:
            risposta = await call_next(request)
        except Exception:
            _registra_richiesta(request, 500, int((time.perf_counter() - inizio) * 1000), ruolo)
            raise
        ruolo = getattr(request.state, "ruolo", "") or ""
        _registra_richiesta(request, risposta.status_code, int((time.perf_counter() - inizio) * 1000), ruolo)
        return risposta

    return applicazione


# `Depends` è riesportato per i test che contraffanno la sessione.
__all__ = ["FIRMA_OPERAZIONI", "crea_app", "meta", "operazioni"]

app = crea_app()
