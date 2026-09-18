"""Configurazione dello shim Trasi.

Le variabili sono **contratto congelato** con il worker `trasi-stack` (`.specs/B0-stack.md` §2): i nomi e i valori
di default qui sotto devono restare allineati al compose.

Nessun segreto è memorizzato in questo file: `TRASI_SHIM_KEY` arriva dall'ambiente (compose / `.env` mode 600).
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Variabili d'ambiente attese dallo shim."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    # Connessione al database Trasi. In B0 lo stub non si connette affatto: nessuna query (§4 V4).
    database_url: str = "postgresql://shim_rw@db_trasi:5432/db_trasi"

    # Chiave che lo shim pretende nell'header X-Trasi-Key. Vuota per default: nessun segreto nel codice,
    # il valore reale è iniettato dal compose. In B3 una chiave vuota o errata deve rispondere 401.
    trasi_shim_key: str = ""

    # Interprete Overpass per i POI esterni (`vicino_a`). L'endpoint produttivo del piano è quello francese:
    # `overpass-api.de` è bloccato da questo host (plan.md §0.3, B0-STK-04).
    overpass_url: str = "https://overpass.openstreetmap.fr/api/interpreter"
    # Failover. `overpass-api.de` ha risposto 504 in B0 (docs/verifiche.md): è trattato come instabile, non come
    # alternativa affidabile. Si interroga solo se lo shim è configurato per farlo (`OVERPASS_FAILOVER=1`).
    overpass_url_2: str = ""

    # User-Agent identificativo **obbligatorio** (verificato in B0: un UA generico risponde 403, questo risponde 200).
    # Non è una cortesia verso Overpass: senza di esso ogni chiamata fallisce in modo opaco.
    overpass_user_agent: str = "Trasi/0.1 (portierato Brindisi)"
    # Geocodificatore per `vicino_a?indirizzo=…`. Stesso User-Agent identificativo di Overpass (la policy di
    # Nominatim lo rende **obbligatorio**: senza, risponde 403) e stesso budget di tempo `overpass_timeout_s`. La
    # ricerca è confinata alla viewbox di Brindisi (`vicinanza.geocodifica`): «via Appia 120» esiste in decine di
    # comuni, e un indirizzo fuori provincia sarebbe un dato inventato da una risposta che sembra giusta.
    nominatim_url: str = "https://nominatim.openstreetmap.org"

    # Motore di ricerca interno per `cerca_web` (V-07 negativo: la ricerca web nativa di Onyx non è limitabile
    # per dominio, quindi passa dallo shim su allow-list). La porta è quella del servizio nella rete `trasi_net`.
    searxng_url: str = "http://searxng:8080"

    # Tempi dichiarati (regola §9.1: 3 s shim, 5 s Overpass) — mai eccezione al chiamante, si legge
    # `fonti_esterne[].stato`.
    overpass_timeout_s: int = 5
    shim_timeout_s: int = 3

    # Fuso orario di riferimento per «oggi», orari e `eventi_oggi`.
    tz: str = "Europe/Rome"

    # `_whoami` esiste solo con `SHIM_DEBUG=1`: è diagnostica, non contratto. Spenta per default, perché un endpoint
    # che dichiara il ruolo del chiamante è informazione che nessuno deve poter leggere per caso.
    shim_debug: str = "0"

    # Dominio pubblico di Onyx (`ONYX_DOMAIN`, lo stesso del Caddyfile): serve a `GET /op/config` per comporre
    # il collegamento «Chiedi» della Home verso l'assistente. Vuoto per default: senza, l'endpoint risponde 503
    # dichiarato e il resto dell'area operatore continua a funzionare.
    onyx_domain: str = ""


@lru_cache
def get_settings() -> Settings:
    """Istanza unica delle impostazioni (letta una volta per processo)."""
    return Settings()
