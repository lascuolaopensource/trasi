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
    """`cerca_luogo`: un luogo della memoria della rete, con la sua etichetta di provenienza."""

    model_config = TIPO_STRETTO

    provenienza: Literal["kb"]
    nome: str
    tipo: str
    indirizzo: str
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    orari_testo: str | None
    fonte: str
    url: str | None
    data_aggiornamento: date | None
    fiducia: int = Field(ge=1, le=3)
    badge: str


class RispostaCercaLuogo(BaseModel):
    """Esito della ricerca nella memoria della rete: `items: []` è una risposta valida, mai un 404."""

    model_config = TIPO_STRETTO

    items: list[ItemLuogo]


class ItemEvento(BaseModel):
    """`eventi_oggi`: un'occorrenza di un evento del calendario della rete, con la sua Casa e i suoi dettagli.

    I dettagli (costo, fascia d'età, tag, prenotazione) sono le risposte a «è gratuito?», «serve prenotare?»,
    «per chi è?»: `null` significa «non dichiarato», che è diverso da «no» — ed è la distinzione che permette
    all'assistente di dire «non lo so» invece di inventare.
    """

    model_config = TIPO_STRETTO

    provenienza: Literal["kb"]
    titolo: str
    dove: str
    casa_slug: str
    casa_nome: str
    data: date
    ora_inizio: str | None
    ora_fine: str | None
    orari_nota: str | None
    descrizione: str | None = None
    costo: float | None = None
    gratuito: bool | None = None
    fascia_eta: str | None = None
    tag: list[str] | None = None
    ricorrenza: str | None = None
    prenotazione: bool | None = None
    prenotazione_nota: str | None = None
    fonte: str
    url: str | None
    fiducia: int = Field(ge=1, le=3)
    badge: str


class RispostaEventiOggi(BaseModel):
    """Eventi in una data (o nell'intervallo `data`..`al`); senza `casa`, di tutte le Case della rete."""

    model_config = TIPO_STRETTO

    casa: str | None
    data: date
    al: date | None = None
    eventi: list[ItemEvento]


class ItemOggetto(BaseModel):
    """`cerca_oggetto`: un oggetto dell'attrezzoteca della rete, da `v_inventario` (disponibilità già al netto dei prestiti)."""

    model_config = TIPO_STRETTO

    oggetto_id: int
    nome: str
    tipo: str | None
    casa: str
    casa_nome: str
    quantita: int = Field(ge=1)
    quantita_fuori: int = Field(ge=0)
    quantita_disponibile: int = Field(ge=0)
    condizione: Literal["integro", "danneggiato", "mancante_di_parti"]
    fonte: str | None
    badge: str


class RispostaCercaOggetto(BaseModel):
    """Esito della ricerca nell'attrezzoteca: `items: []` è un inventario senza corrispondenze, mai un 404."""

    model_config = TIPO_STRETTO

    items: list[ItemOggetto]


class RispostaEventiMese(BaseModel):
    """`eventi_mese` (fuori contratto, calendario della Home): gli eventi di una Casa dal primo all'ultimo giorno del mese.

    `oggi` è il giorno nel fuso della rete secondo lo shim: la Home lo usa per evidenziare le righe di oggi, così
    l'evidenza coincide con la riga «Oggi» della stessa pagina e non dipende dall'orologio del browser.
    """

    model_config = TIPO_STRETTO

    casa: str
    dal: date
    al: date
    oggi: date
    eventi: list[ItemEvento]


class VoceMappaCasa(BaseModel):
    """`mappa_case` (fuori contratto, pagina «Mappa» della Home): una Casa della rete come pin e come voce dell'elenco."""

    model_config = TIPO_STRETTO

    slug: str
    nome: str
    zona: str | None
    ente_gestore: str | None
    lat: float
    lon: float
    raggio_m_eff: int | None
    geom_qualita: str | None
    da_validare: bool
    orari_provvisori: bool
    orari_testo: str | None
    fonte: str
    fiducia: int | None = Field(default=None, ge=1, le=3)
    data_aggiornamento: date | None
    badge: str
    evidenziata: bool


class RispostaMappaCase(BaseModel):
    """Le dieci Case per la mappa: `casa_evidenziata` è lo slug richiesto (o `null`), `consultato_ts` l'istante della lettura."""

    model_config = TIPO_STRETTO

    casa_evidenziata: str | None
    consultato_ts: datetime
    case: list[VoceMappaCasa]



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
