"""Schemi di risposta che rispecchiano `shim/openapi.yaml` (congelato, gate V-09).

Perché duplicare il contratto in pydantic invece di restituire dizionari: con `response_model` FastAPI **valida la
forma della risposta** a ogni chiamata. Un campo dimenticato, un `None` dove il contratto vuole una stringa o un
campo in più diventano un errore visibile subito, invece di un JSON che il LLM interpreta male in chat. Il
`test_schemi_rispecchiano_il_contratto` confronta questi modelli con il file congelato, così le due dichiarazioni non
possono divergere in silenzio.

`extra="forbid"` e `additionalProperties: false` non sono un dettaglio di stile: sono il presidio strutturale contro
i dati personali (§12, V5) — lo shim non può restituire un campo che il contratto non prevede.
"""

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TIPO_STRETTO = ConfigDict(extra="forbid", str_strip_whitespace=False)


class Errore(BaseModel):
    """`components.schemas.Errore`: l'involucro unico degli errori."""

    model_config = TIPO_STRETTO

    detail: str = Field(description="Spiegazione dell'errore, in italiano.")


class ItemLuogo(BaseModel):
    """`cerca_luogo`: un luogo della memoria della rete, con la sua etichetta di provenienza.

    `id` è il `luogo.id` della memoria: è ciò che il LLM passa a `biglietto(luogo_id=…)` per comporre il
    foglio. Senza questo campo il modello doveva indovinare l'identificativo — e chiamava il biglietto
    con il **nome** del luogo (422) o con l'id di un nodo OSM (il bug del 17/09: 500).
    """

    model_config = TIPO_STRETTO

    id: int = Field(ge=1, description="Identificativo del luogo: è il `luogo_id` da passare a `biglietto`.")
    provenienza: Literal["kb"]
    nome: str
    tipo: str
    indirizzo: str
    # `None` = il luogo non ha una posizione in memoria (P1.2): il campo c'è sempre, il valore può mancare.
    lat: float | None = Field(ge=-90, le=90)
    lon: float | None = Field(ge=-180, le=180)
    orari_testo: str | None
    fonte: str
    url: str | None
    # Recapito telefonico (P1.3): il campo c'è sempre, il valore è `None` finché la memoria della rete non ha un
    # recapito **di servizio** verificato (db/025: oggi nessuna colonna lo porta, per decisione). Il LLM legge
    # `null` e dice «Recapito telefonico non disponibile»: un campo assente lo lascerebbe libero di inventarlo.
    telefono: str | None
    data_aggiornamento: date | None
    fiducia: int = Field(ge=1, le=3)
    badge: str


class RispostaCercaLuogo(BaseModel):
    """Esito della ricerca nella memoria della rete: `items: []` è una risposta valida, mai un 404."""

    model_config = TIPO_STRETTO

    items: list[ItemLuogo]


class ItemEvento(BaseModel):
    """`eventi_oggi`: un'occorrenza di un evento in programma in una Casa di Quartiere.

    Un evento ricorrente arriva come **una riga per occorrenza** (17/09/2026, db/030): `ricorrenza`
    porta la regola («settimanale»…), `occorrenza` il numero progressivo (0 = la prima, che è
    l'`inizio` originale). Un evento singolo ha `ricorrenza=None` e `occorrenza=0`: il consumatore
    non deve saperne di più per non mostrare niente di più.
    """

    model_config = TIPO_STRETTO

    provenienza: Literal["kb", "esterna"]
    titolo: str
    dove: str
    data: date
    ora_inizio: str | None
    ora_fine: str | None
    orari_nota: str | None
    fonte: str
    url: str | None
    fiducia: int = Field(ge=1, le=3)
    badge: str
    ricorrenza: Literal["settimanale", "bisettimanale", "mensile", "annuale"] | None = None
    occorrenza: int | None = Field(default=None, ge=0)


class RispostaEventiOggi(BaseModel):
    """Eventi di una Casa in una data o in un intervallo di date.

    `data_fine` è **sempre** presente in risposta (17/09/2026, US-1.2): senza la query string
    coincide con `data` (un giorno), e il consumatore legge l'intervallo effettivo in un campo solo
    invece di doverlo dedurre dall'assenza del campo.
    """

    model_config = TIPO_STRETTO

    casa: str
    data: date
    data_fine: date
    eventi: list[ItemEvento]


class FonteEsterna(BaseModel):
    """Esito di una fonte esterna interrogata: uno stato dichiarato, mai un'eccezione al chiamante."""

    model_config = TIPO_STRETTO

    fonte: str
    stato: Literal["ok", "timeout", "errore", "scartata_fiducia"]
    ms: int = Field(ge=0)


class ItemVicinanza(BaseModel):
    """`vicino_a`: un luogo vicino alla Casa, dalla memoria della rete o da una fonte esterna.

    I campi facoltativi sono `null`, non omessi, così il LLM vede sempre la stessa forma.
    """

    model_config = TIPO_STRETTO

    provenienza: Literal["kb", "esterna"]
    nome: str
    tipo: str
    indirizzo: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    distanza_m: float = Field(ge=0)
    aperto_adesso: bool | None
    orari_testo: str | None
    orari_nota: str | None
    fonte: str
    url: str | None
    # Il recapito della **fonte** (tag OSM `phone`/`contact:phone`, verbatim) per `esterna`; `None` per `kb`
    # (db/025) e per i POI senza tag. Mai composto, mai normalizzato dallo shim.
    telefono: str | None
    data_aggiornamento: date | None
    fiducia: int = Field(ge=1, le=3)
    consultato_ts: datetime
    badge: str


class RispostaVicinoA(BaseModel):
    """Luoghi vicini alla Casa, ordinati per gruppo (prima `kb`, poi `esterna`), apertura e distanza."""

    model_config = TIPO_STRETTO

    casa: str
    tipo: str
    raggio_m: int = Field(ge=1)
    items: list[ItemVicinanza]
    fonti_esterne: list[FonteEsterna]


class ItemStatisticheAmbito(BaseModel):
    """`statistiche`: una riga del report mensile — categoria, esito, conteggio già mascherato.

    `n` è `None` (mai omesso) sotto la soglia di k-anonimato: la vista non espone il numero grezzo, e questo
    modello lo dichiara nullable perché la risposta non venga rifiutata a runtime proprio nei casi in cui la
    mascheratura lavora.
    """

    model_config = TIPO_STRETTO

    categoria: str
    esito: str
    n: int | None = Field(ge=1)
    n_label: str


class RispostaStatistiche(BaseModel):
    """Statistiche mensili delle richieste della Casa: `ambiti: []` è un mese senza attività, non un 404."""

    model_config = TIPO_STRETTO

    casa: str
    mese: str
    ambiti: list[ItemStatisticheAmbito]
    testo: str


class WhoAmI(BaseModel):
    """Risposta del `_whoami` di debug (fuori dal contratto: esiste solo con `SHIM_DEBUG=1`)."""

    model_config = TIPO_STRETTO

    email: str
    ruolo: str
    casa_id: int | None
    parametri: dict[str, Any] = Field(default_factory=dict)
