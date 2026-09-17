"""Scritture dello shim: `registra_richiesta`, `crea_evento`, `proponi_modifica`, `approva_proposta` (B3-SHM-05/06, S2).

**La RLS è l'autorità** (§1 principio 3, §11). Questo modulo non decide mai i permessi: prova l'operazione e mappa
l'esito — un `UPDATE` che non tocca righe è «0 righe», cioè un rifiuto della RLS, non un errore interno. Per questo
non esiste alcun pre-controllo del tipo «questa proposta è tua?»: quel controllo sarebbe una seconda copia della
policy, e divergerebbe.

Le scritture ammesse dal progetto sono tre, e sono qui dentro:

- `richiesta` — registro operativo del colloquio (`registra_richiesta`), **senza campi del cittadino**: il modello
  dati non ne ha, e `additionalProperties: false` respinge `casa_id` o qualunque altro campo non previsto;
- `evento` — **scrittura diretta** (`crea_evento`): l'operatore della Casa è anche il gestore (decisione S2,
  «opzione A»), quindi la cerimonia proposta/approvazione non ha un secondo umano a cui passare. Il dominio resta
  protetto dalla policy `evento_ins_casa` (`casa_id = casa_corrente()`) e la tracciabilità dai trigger di dominio;
- `proposta` — il ciclo mediato (`proponi_modifica` → `approva_proposta`) resta per le entità **fuori dalla Casa**
  (luoghi, territorio, rete), dove un secondo decisore esiste davvero. L'applicazione al dominio è del flusso F9
  (`applica_proposte`), non dello shim.

**Cosa il database calcola da sé, e che quindi non si passa.** `approvatore_ruolo`, `stato`, `proposto_da`,
`scade_il` e `diff` sono impostati dai trigger `proposta_00_default_tg` / `proposta_03_diff_tg`. Passarli sarebbe
una seconda decisione in conflitto con quella del database (e un errore di privilegio: i GRANT sono colonnari, e lo
shim possiede solo le colonne che gli servono davvero).

**Nota di correttezza emersa dalla verifica sul database reale (riportata, non aggirata).** La policy RESTRICTIVE
`no_self_approve` confronta `proposto_da` con `current_user`: poiché operatore e gestore della stessa Casa
condividono lo stesso ruolo DB (§11, «un ruolo per Casa»), una proposta creata da `casa_sanbao` produce
`proposto_da = 'casa_sanbao'` e **nessun** `UPDATE` dello stesso ruolo la tocca — 0 righe, quindi 403 «da approvare
in coda», anche quando riguarda la propria Casa. È la regola V4 («auto-approvazione vietata, non negoziabile») che
funziona come previsto; la conseguenza operativa è che l'approvazione *in chat* prevista da §9.2 richiede una
seconda identità (es. `rete@trasi.local` per le proposte `at`, il gestore con un ruolo DB separato in S2). Il campo
`in_chat` dichiara quindi la **competenza** della proposta (riguarda la Casa dell'operatore), non la possibilità
materiale di decidere una proposta che quell'identità ha appena creato: il contratto lo definisce «riguarda la Casa
dell'operatore», ed è esattamente quello che viene calcolato.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from asyncpg.exceptions import (
    CheckViolationError,
    ForeignKeyViolationError,
    InsufficientPrivilegeError,
    RaiseError,
)
from fastapi import APIRouter, Depends, FastAPI
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import pii
from .badge import badge_kb
from .contratto import prefisso_path
from .db import Sessione, sessione
from .errori import DETAIL_DA_APPROVARE_IN_CODA, errore
from .operazioni import dichiarazione

router = APIRouter()


def monta(applicazione: FastAPI) -> None:
    """Monta le route delle scritture sotto il prefisso del contratto (`/v1/u/{email}`)."""
    applicazione.include_router(router, prefix=prefisso_path())


def _argomenti(operation_id: str) -> dict[str, Any]:
    """Gli argomenti del decoratore, letti dal contratto congelato (`summary`, `tags`, descrizioni degli errori)."""
    dati = dichiarazione(operation_id)
    return {
        "path": dati["path"],
        "operation_id": dati["operation_id"],
        "summary": dati["summary"],
        "tags": dati["tags"],
        "responses": dati["responses"],
    }


# Dettaglio dei rifiuti che il contratto non nomina, perché non è un esempio ma un caso distinto.
DETAIL_RUOLO_NON_CONSENTITO = "operazione non consentita al ruolo dell'operatore"
DETAIL_RIGA_NON_DELLA_CASA = "riga non appartiene alla Casa dell'operatore"
#: Il rifiuto di una proposta su un dato **proprio**, con la via alternativa. Il messaggio dice dove andare,
#: non solo che non si passa di qui: `{entita}` è una delle ENTITA_DIRETTE.
DETAIL_USA_SCRITTURA_DIRETTA = (
    "i dati della propria Casa si scrivono direttamente (salva_dato per scheda/opportunità, crea_evento per "
    "gli eventi, salva_orari per gli orari): una proposta su «{entita}» della propria Casa non è decidibile da "
    "nessuno, perché operatore e gestore condividono un solo accesso per Casa"
)
DETAIL_DESTINAZIONE_INESISTENTE = "destinazione_id non corrisponde a un luogo della memoria della rete"
DETAIL_CASA_INESISTENTE = "casa_id non corrisponde a una Casa della rete"
DETAIL_ENTITA_NON_AMMESSA = (
    "entità non ammessa — valori: casa, evento, luogo, opportunita, scheda_servizio"
)

# Vocabolari chiusi del modello dati. Sono dichiarati anche qui, oltre che nel database, per una ragione
# osservabile: un valore fuori elenco diventa un **422 con l'elenco ammesso** (contratto §ParametriNonAmmessi) invece
# di un 500 da violazione di CHECK — e il LLM può correggersi.
CATEGORIE = (
    "orientamento",
    "servizi_sociali",
    "fiscale_isee",
    "lavoro",
    "abitare",
    "salute",
    "interculturale",
    "ascolto_solitudine",
    "eventi_attivita",
    "altro",
)
ESITI = ("risolta", "inviata_altrove", "non_trovata", "rinviata")
# Le fasce del foglio 4.4 (gruppo Processi, decisione 2026-09-17): **le stesse** di `evento.fascia_eta`
# (`db/025`), senza `tutte` — una persona ha un'età, un evento può essere «per tutti» — e con
# `non_dichiarat*`, che è una risposta e non un buco. Elenco chiuso anche qui: un testo libero
# («72 anni») sarebbe un valore esatto, cioè ciò che le fasce esistono per non raccogliere.
FASCE_ETA = ("0-13", "14-17", "18-29", "30-44", "45-59", "60-74", "75+", "non_dichiarata")
GENERI = ("donna", "uomo", "altro", "non_dichiarato")
PROVENIENZE = ("italia", "ue", "extra_ue", "non_dichiarata")
TIPI_PROPOSTA = (
    "nuovo_luogo",
    "modifica_luogo",
    "chiudi_luogo",
    "modifica_scheda",
    "nuova_scheda",
    "modifica_evento",
    "nuova_opportunita",
    "promuovi_esterno",
    "modifica_orari_casa",
)
ENTITA_DOMINIO = ("luogo", "scheda_servizio", "evento", "opportunita", "casa")
GIORNI = ("lun", "mar", "mer", "gio", "ven", "sab", "dom")


# --- Corpi di richiesta ---------------------------------------------------------------------------------------
# `extra="forbid"` è il presidio strutturale contro i dati personali (§12): un campo non previsto — `casa_id`,
# `nome_cittadino`, `telefono` — è un 422, non una colonna in più scritta per distrazione.

class RichiestaIn(BaseModel):
    """Il corpo di `registra_richiesta`: i campi del registro e le fasce del foglio 4.4.

    `extra="forbid"` resta il presidio strutturale contro i dati personali (§12): un campo non previsto —
    `casa_id`, `nome_cittadino`, `telefono` — è un 422, non una colonna in più scritta per distrazione.
    """

    model_config = ConfigDict(extra="forbid")

    categoria: Literal[CATEGORIE]  # type: ignore[valid-type]
    esito: Literal[ESITI]  # type: ignore[valid-type]
    destinazione_id: int | None = Field(default=None, ge=1)
    destinazione_nota: str | None = Field(default=None, min_length=1)
    # Le tre fasce del foglio 4.4 (db/026): **facoltative** e a vocabolario chiuso. L'assenza è
    # legittima («non ho chiesto») e i valori ammessi sono gli stessi del CHECK del database, così un
    # valore fuori elenco è un 422 parlante e non un 500 da CHECK. Non sono dati identificativi: sono
    # classi, e i loro conteggi escono solo mascherati da `v_fasce_cittadino`.
    fascia_eta: Literal[FASCE_ETA] | None = None  # type: ignore[valid-type]
    genere: Literal[GENERI] | None = None  # type: ignore[valid-type]
    provenienza: Literal[PROVENIENZE] | None = None  # type: ignore[valid-type]

    @model_validator(mode="after")
    def _destinazione_obbligatoria(self) -> "RichiestaIn":
        """`inviata_altrove` senza destinazione è una registrazione inutilizzabile: il CHECK del database la
        rifiuterebbe con un 500, il contratto la dichiara 422."""
        if self.esito == "inviata_altrove" and self.destinazione_id is None and not self.destinazione_nota:
            raise ValueError(
                "destinazione_id o destinazione_nota obbligatori quando esito è «inviata_altrove»"
            )
        return self


class OrariProposti(BaseModel):
    """Orari settimanali proposti: fasce `HH:MM` a coppie, elenco vuoto = chiuso quel giorno."""

    model_config = ConfigDict(extra="forbid")

    lun: list[str] | None = None
    mar: list[str] | None = None
    mer: list[str] | None = None
    gio: list[str] | None = None
    ven: list[str] | None = None
    sab: list[str] | None = None
    dom: list[str] | None = None


class PayloadProposta(BaseModel):
    """I valori proposti, scelti dall'elenco chiuso di colonne del modello dati (`§7.1`, contratto `PayloadProposta`).

    Nessun campo libero: è il motivo per cui una proposta non può contenere dati personali *per costruzione*. Il
    filtro sui valori (`pii`) è la seconda barriera, per i campi testuali che restano ammessi (indirizzo, nome,
    descrizione).
    """

    model_config = ConfigDict(extra="forbid")

    nome: str | None = None
    tipo: str | None = None
    indirizzo: str | None = None
    # `categoria` esiste su `scheda_servizio` e `opportunita` (db/001) e mancava qui: senza, una
    # proposta di nuova scheda non poteva dichiarare la categoria e `applica_proposte_approvate` la
    # scriveva NULL. Aggiunta con la scrittura diretta (`salva_dato`), che la usa per entrambe.
    categoria: str | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    orari: OrariProposti | None = None
    orari_provvisori: bool | None = None
    zona: str | None = None
    raggio_m: int | None = Field(default=None, ge=1)
    descrizione: str | None = None
    scadenza: date | None = None
    chiuso_il: date | None = None
    ext_ref: str | None = None
    affidabilita: int | None = Field(default=None, ge=1, le=3)
    data_aggiornamento: date | None = None
    casa_id: int | None = Field(default=None, ge=1)
    anomalo: bool | None = None

    # I campi di `evento` e `scheda_servizio`. Mancavano, e non era una svista senza conseguenze:
    # `trasi.applica_proposte_approvate` accetta `inizio`, `fine` e `luogo_testo` per `modifica_evento`
    # e `titolo` per `nuova_scheda`/`modifica_scheda`, ma `extra="forbid"` respingeva ogni payload che
    # li portasse con un 422. La conseguenza era che **l'orario di un evento non si poteva correggere
    # dal percorso utente**: l'assistente chiamava `proponi_modifica` e riceveva
    # «payload.inizio: Extra inputs are not permitted», quindi la segnalazione dell'operatore non
    # diventava una proposta. L'elenco qui sotto è la chiusura di quel divario: gli stessi nomi che
    # le whitelist di `db/006_fn_proposte.sql` leggono dai rami C (evento) e B (scheda).
    #
    # `inizio`/`fine` sono `datetime` e non `date`: un evento ha un'ora, e un `date` la perderebbe
    # silenziosamente a mezzanotte. `luogo_testo` è testo libero (il luogo di un evento può non essere
    # ancora in memoria) e resta coperto dal filtro anti-PII.
    titolo: str | None = None
    inizio: datetime | None = None
    fine: datetime | None = None
    luogo_testo: str | None = None
    url: str | None = None
    annullato: bool | None = None
    referente_ruolo: str | None = None
    validata_il: date | None = None


class ProponiModificaIn(BaseModel):
    """Il corpo di `proponi_modifica`."""

    model_config = ConfigDict(extra="forbid")

    tipo: Literal[TIPI_PROPOSTA]  # type: ignore[valid-type]
    entita: str = Field(min_length=1)
    entita_id: int | None = Field(default=None, ge=1)
    payload: PayloadProposta
    motivazione: str = Field(min_length=1, max_length=80)


class ApprovaPropostaIn(BaseModel):
    """Il corpo di `approva_proposta`."""

    model_config = ConfigDict(extra="forbid")

    proposta_id: int = Field(ge=1)
    decisione: Literal["approva", "rifiuta"]
    nota: str | None = Field(default=None, max_length=80)


# --- Mappatura degli errori del database ----------------------------------------------------------------------


def _rifiuta_violazione(exc: Exception) -> None:
    """Traduce una violazione del database in una risposta **dichiarata dal contratto**, poi rilancia.

    Questa funzione esiste per non lasciare mai uscire un 500 da un vincolo del database: una violazione di CHECK è
    un 422 (parametro non ammesso), una chiave esterna inesistente è un 422 (destinazione che non esiste), un
    privilegio negato è un 403 (la RLS ha deciso). Chi chiama la invoca nel proprio `except` e non ritorna.
    """
    if isinstance(exc, InsufficientPrivilegeError):
        raise errore(403, DETAIL_RUOLO_NON_CONSENTITO) from exc
    if isinstance(exc, ForeignKeyViolationError):
        raise errore(422, DETAIL_CASA_INESISTENTE) from exc
    if isinstance(exc, CheckViolationError):
        raise errore(422, "valore non ammesso dal modello dati") from exc
    if isinstance(exc, RaiseError):
        # Un trigger che solleva è una regola del database violata (proposta immutabile, transizione non ammessa):
        # è una richiesta non ammessa, non un guasto dello shim. Il testo del trigger è in italiano e non contiene
        # valori della richiesta.
        raise errore(422, str(exc).strip()) from exc
    raise


# --- `registra_richiesta` -------------------------------------------------------------------------------------


@router.post(
    **_argomenti("registra_richiesta"),
    status_code=201,
)
async def registra_richiesta(
    corpo: RichiestaIn, sess: Sessione = Depends(sessione)
) -> dict[str, int]:
    """Registra la richiesta di orientamento: il registro operativo e le fasce del foglio 4.4.

    `casa_id` viene **dall'identità** (`identita_onyx` → `SET LOCAL ROLE` → `trasi.casa_corrente()`), mai dal corpo:
    un operatore non può registrare una richiesta a nome di un'altra Casa. La policy `rich_ins_casa` del database
    verifica comunque che la riga appartenga alla Casa corrente — la seconda barriera, non la prima.

    **Le fasce (`fascia_eta`, `genere`, `provenienza`) non sono dati identificativi**: sono classi a
    vocabolario chiuso (db/026) e i loro conteggi escono solo mascherati da `trasi.v_fasce_cittadino` —
    sotto la soglia `[P] k_anonimato` il numero non esiste. Resteranno fuori da ogni superficie che
    esponga righe di sportello: nessuna vista le porta riga per riga. Chiedi le fasce **solo se l'operatore
    le ha chieste alla persona**: un campo vuoto è una risposta legittima, un dato indovinato no.
    """
    pii.rifiuta_se_presente(corpo.model_dump(exclude_unset=True, mode="json"))

    try:
        richiesta_id = await sess.fetchval(
            """
            INSERT INTO trasi.richiesta (casa_id, categoria, esito, destinazione_id, destinazione_nota,
                                         fascia_eta, genere, provenienza)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id
            """,
            sess.casa_id,
            corpo.categoria,
            corpo.esito,
            corpo.destinazione_id,
            corpo.destinazione_nota,
            corpo.fascia_eta,
            corpo.genere,
            corpo.provenienza,
        )
    except ForeignKeyViolationError as exc:
        raise errore(422, DETAIL_DESTINAZIONE_INESISTENTE) from exc
    except Exception as exc:  # noqa: BLE001 — la traduzione è il compito di `_rifiuta_violazione`
        _rifiuta_violazione(exc)

    return {"richiesta_id": richiesta_id}


# --- `crea_evento` --------------------------------------------------------------------------------------------


class CreaEventoIn(BaseModel):
    """Il corpo di `crea_evento`: solo campi di `trasi.evento`, mai `casa_id` né dati personali (V5/§12).

    `casa_id` viene **dall'identità** (come in `registra_richiesta`): la policy `evento_ins_casa` del database
    verifica comunque `casa_id = casa_corrente()` — la seconda barriera, non la prima.
    """

    model_config = ConfigDict(extra="forbid")

    titolo: str = Field(min_length=1, max_length=200)
    descrizione: str | None = None
    inizio: datetime
    fine: datetime | None = None
    luogo_testo: str | None = None
    url: str | None = None

    @model_validator(mode="after")
    def _fine_dopo_inizio(self) -> "CreaEventoIn":
        """Il CHECK `evento_fine_dopo_inizio` lo rifiuterebbe con un 500; il contratto lo dichiara 422."""
        if self.fine is not None and self.fine < self.inizio:
            raise ValueError("fine deve essere uguale o successiva a inizio")
        return self


@router.post(
    **_argomenti("crea_evento"),
    status_code=201,
)
async def crea_evento(
    corpo: CreaEventoIn, sess: Sessione = Depends(sessione)
) -> dict[str, Any]:
    """Crea un evento della Casa dell'operatore, scrittura **diretta** (opzione A, decisione del progetto).

    Non è una proposta: il gestore è anche l'operatore, la separazione V4 non si applica. La tracciabilità resta
    garantita dai trigger di dominio (`scrittura_00_ts` su `aggiornato_ts`/`aggiornato_da`); il trigger
    `evento_ical_01_audit` **non** registra la scrittura come `ical_upsert` perché `session_user` non è
    `automazioni` — l'audit non attribuisce a una fonte automatica una scrittura umana.
    """
    if sess.casa_id is None:
        raise errore(403, DETAIL_RUOLO_NON_CONSENTITO)

    pii.rifiuta_se_presente(corpo.model_dump(exclude_unset=True, mode="json"))

    try:
        evento_id = await sess.fetchval(
            """
            INSERT INTO trasi.evento (casa_id, titolo, descrizione, inizio, fine, luogo_testo, url, affidabilita)
            VALUES ($1, $2, $3, $4, $5, $6, $7, 3)
            RETURNING id
            """,
            sess.casa_id,
            corpo.titolo,
            corpo.descrizione,
            corpo.inizio,
            corpo.fine,
            corpo.luogo_testo,
            corpo.url,
        )
    except Exception as exc:  # noqa: BLE001 — la traduzione è il compito di `_rifiuta_violazione`
        _rifiuta_violazione(exc)

    badge = badge_kb("inserito dall'operatore", date.today(), 3)
    return {"evento_id": evento_id, "badge": badge}


# --- `salva_dato` — la scrittura diretta della propria Casa -----------------------------------------------

#: Le entità che una Casa scrive **direttamente** — sono le sue.
#:
#: La specifica del gruppo Processi (2026-09-17) è esplicita: «ogni casa/ente può modificare i propri dati,
#: della propria casa». Operatore e gestore condividono un solo accesso per Casa, quindi la cerimonia
#: proposta → approvazione **non ha un secondo umano a cui passare**: chiedere a qualcuno di approvare ciò che
#: ha appena scritto l'unica identità della Casa è la definizione del vicolo cieco, ed è esattamente BUG-02.
#:
ENTITA_DIRETTE = ("scheda_servizio", "opportunita", "casa", "persona")

#: Le colonne che `salva_dato` accetta di scrivere, per entità. Elenco chiuso: `casa_id` non c'è perché viene
#: dall'identità (la policy lo impone comunque), e le colonne di servizio (`fonte_id`, `affidabilita`,
#: `aggiornato_ts`) non c'è perché un dato scritto a mano da una persona ha affidabilità 3 e impronta
#: automatica — un operatore non si dichiara «affidabile 1» né si firma.
#:
#: Per `casa` l'elenco è **esattamente** il privilegio che il database concede al ruolo della Casa
#: (`db/002`: `UPDATE (orari, orari_eccezioni, orari_provvisori, email_digest)`). Non è una coincidenza da
#: mantenere a mano: è lo stesso criterio di least-privilege visto dai due lati, e un campo in più qui
#: produrrebbe un `42501` — cioè un rifiuto del database, non una scrittura.
#:
#: Per `persona` (db/027): il **nome è l'unico dato personale che questa operazione accetta**, ed è il
#: punto della decisione del gruppo Processi (2026-09-17, forma C): le persone della Casa entrano nella
#: knowledge base — e quindi in chat — **solo con il consenso dell'interessata**. Per questo
#: `consenso` è **obbligatorio e deve essere `true` alla creazione**: un'operazione che creasse una
#: persona senza dichiarare il consenso sarebbe una scrittura di un nome in attesa di una promessa.
#: La revoca non passa da qui: è `DELETE` della persona (la RLS la concede alla propria Casa), e il
#: flusso export cancella il documento da Onyx. Vedi `db/027_persone_casa.sql`.
COLONNE_DIRETTE: dict[str, tuple[str, ...]] = {
    "scheda_servizio": ("titolo", "descrizione", "categoria", "orari", "referente_ruolo", "scadenza", "url"),
    "opportunita": ("titolo", "descrizione", "categoria", "scadenza", "url"),
    # Le colonne della Casa: gli orari, i recapiti, e i tre campi del foglio 1.1 di Processi
    # (`indirizzo`, `edificio`, `telefono`). È **esattamente** il privilegio che il database concede al ruolo
    # della Casa: `db/002` per orari/email_digest, `db/025` per i tre nuovi.
    "casa": ("orari", "orari_provvisori", "email_digest", "indirizzo", "edificio"),
    "persona": ("nome", "ruolo", "competenze", "informativa"),
}


class SalvaDatoIn(BaseModel):
    """Il corpo di `salva_dato`: i campi della propria scheda/opportunità/orari, nessun `casa_id`.

    Come per `crea_evento`, `casa_id` **non** è nel corpo: la Casa è quella dell'identità, e la policy
    `scheda_ins_casa`/`opp_ins_casa` (`casa_id = casa_corrente()`) la impone anche a livello di database.
    `extra="forbid"` è il presidio strutturale contro i dati personali (V5/§12): un campo non previsto — un
    nome, un telefono — è un 422, non una colonna scritta per distrazione.
    """

    model_config = ConfigDict(extra="forbid")

    entita: Literal["scheda_servizio", "opportunita", "casa", "persona"]  # type: ignore[valid-type]
    # None = nuova entità; un id = modifica di quella esistente (che la RLS riserva alla propria Casa).
    # Per `entita="casa"` è **sempre** None: la Casa è una sola, quella dell'identità, e non si sceglie.
    id: int | None = Field(default=None, ge=1)
    # I campi di `scheda_servizio`/`opportunita`. Per `casa` non si usano: si usano quelli sotto.
    titolo: str | None = Field(default=None, min_length=1, max_length=200)
    descrizione: str | None = None
    categoria: str | None = None
    orari: OrariProposti | None = None
    referente_ruolo: str | None = None
    scadenza: date | None = None
    url: str | None = None
    # I campi della Casa (solo `entita="casa"`): gli orari di apertura e i recapiti del digest.
    orari_provvisori: bool | None = None
    email_digest: str | None = None
    # I campi del foglio 1.1 (gruppo Processi): indirizzo civico della sede e denominazione dell'immobile.
    # **`telefono` NON c'è, deliberatamente**: il filtro `pii.TELEFONO` riconosce qualunque numero fisso o
    # cellulare italiano e non può distinguere un centralino di sportello da un cellulare personale — la
    # differenza non è nella forma del numero. Una colonna che accetta numeri in una tabella esportata in KB
    # (e quindi citabile in chat) riaprirebbe per la porta di servizio ciò che V5 tiene fuori. Vedi `db/025`.
    indirizzo: str | None = None
    edificio: str | None = None
    # I campi del foglio 1.1 «Persone» (solo `entita="persona"`), db/027. `nome` è l'unico dato
    # personale ammesso da questa operazione, ed è condizionato: vedi `COLONNE_DIRETTE["persona"]`.
    nome: str | None = Field(default=None, min_length=3, max_length=120)
    ruolo: str | None = Field(default=None, min_length=2, max_length=80)
    competenze: list[str] | None = None
    informativa: str | None = Field(default=None, max_length=200)
    # Il consenso: **obbligatorio a `true` alla creazione** di una persona. Non è un campo tra gli
    # altri, è la condizione che rende legittimo scrivere il nome — per questo il validatore lo
    # impone e la risposta della API lo riporta.
    consenso: bool | None = None

    @model_validator(mode="after")
    def _coerenza(self) -> "SalvaDatoIn":
        """Cosa si può dichiarare per ciascuna entità: un campo fuori posto è un 422, non un campo ignorato.

        Senza questo, `entita="scheda_servizio"` con `orari_provvisori` verrebbe accettato e il valore
        sparirebbe in silenzio — il tipo di scrittura che sembra riuscita e non ha fatto nulla.
        """
        if self.entita == "opportunita" and self.orari is not None:
            raise ValueError("orari non si applica a «opportunita»: è una colonna di scheda_servizio")
        if (
            self.entita not in ("casa", "persona")
            and self.id is None
            and (self.titolo is None or not self.titolo.strip())
        ):
            # `titolo` è obbligatorio **alla creazione** di scheda/opportunità: è `NOT NULL` nello schema, e
            # senza questo controllo l'assenza diventerebbe un `NotNullViolation` tradotto in un 500, invece
            # del 422 parlante che il contratto dichiara. Con `id` è un aggiornamento parziale: chi corregge la
            # sola `descrizione` non deve riscrivere il titolo (misurato: lo pretendeva, e ogni UPDATE senza
            # titolo era un 422 — la via «correggi la scheda» era in pratica «riscrivi la scheda»).
            raise ValueError(f"titolo è obbligatorio per creare «{self.entita}»")
        if self.entita == "persona":
            # `consenso` non è un campo tra gli altri: è la condizione che rende legittimo scrivere il
            # nome di una persona. Alla creazione deve essere `true` esplicito — l'assenza non è
            # interpretabile come consenso — e la colonna `consenso_il` del database timbra quando.
            if self.id is None and self.consenso is not True:
                raise ValueError(
                    "creare una persona richiede consenso=true: il nome entra nella knowledge base "
                    "(quindi in chat) solo con il consenso dell'interessata (db/027)"
                )
            if any(v is not None for v in (self.titolo, self.descrizione, self.categoria,
                                           self.orari, self.referente_ruolo, self.scadenza, self.url,
                                           self.orari_provvisori, self.email_digest,
                                           self.indirizzo, self.edificio)):
                raise ValueError(
                    "«persona» accetta solo nome, ruolo, competenze, informativa e consenso"
                )
            return self
        if self.entita == "casa":
            if self.id is not None:
                raise ValueError("«casa» non vuole id: la Casa è quella dell'identità, un ruolo una Casa")
            if any(v is not None for v in (self.titolo, self.descrizione, self.categoria,
                                           self.referente_ruolo, self.scadenza, self.url)):
                raise ValueError(
                    "«casa» accetta solo orari, orari_provvisori, email_digest, indirizzo ed edificio"
                )
        else:
            if any(v is not None for v in (self.orari_provvisori, self.email_digest,
                                           self.indirizzo, self.edificio)):
                raise ValueError(
                    "orari_provvisori/email_digest/indirizzo/edificio si applicano solo a «casa»"
                )
        return self


@router.post(
    **_argomenti("salva_dato"),
    status_code=201,
)
async def salva_dato(corpo: SalvaDatoIn, sess: Sessione = Depends(sessione)) -> dict[str, Any]:
    """Crea o aggiorna un dato **della propria Casa**, scrittura diretta (specifica del gruppo Processi).

    Non è una proposta, e non è una scorciatoia: è la regola. «Ogni casa/ente può modificare i propri dati,
    della propria casa» — e un accesso solo per Casa significa che non esiste una seconda identità a cui
    chiedere l'approvazione. Il ciclo mediato resta per ciò che **non** è della Casa (`luogo`, promozioni
    dall'esterno), dove il secondo decisore c'è.

    Quattro entità, due forme:

    * `scheda_servizio` / `opportunita` — `id` assente = INSERT, `id` presente = UPDATE della propria riga;
    * `casa` — **sempre** UPDATE della riga dell'identità (`casa_corrente()`), mai INSERT: una Casa non si
      crea dallo sportello, e `id` non è ammesso perché la Casa è quella di chi scrive, non una da scegliere.
      Si scrivono solo gli orari e i recapiti — cioè esattamente le colonne che `db/002` concede al ruolo
      della Casa (`UPDATE (orari, orari_eccezioni, orari_provvisori, email_digest)`).
    * `persona` (db/027) — INSERT o UPDATE come una scheda, **con il consenso richiesto dal validatore**:
      il nome entra nella KB, e la revoca è la cancellazione della riga.

    **Chi garantisce cosa.** La RLS: `scheda_ins_casa`/`scheda_upd_casa` (e le omologhe su `opportunita`,
    `casa` e `persona`) impongono `casa_id = casa_corrente()`. La scrittura su un dato di un'altra Casa non
    è un errore da validare qui — è una riga che Postgres non rende possibile: un `UPDATE` che non tocca
    righe è un rifiuto (403), non un 500. La tracciabilità è dei trigger di dominio (`scrittura_00_ts` timbra
    `aggiornato_ts` e `aggiornato_da`), quindi la scrittura è contabilizzata da `v_scritture_senza_audit`
    come ogni altra.
    """
    if sess.casa_id is None:
        raise errore(403, DETAIL_RUOLO_NON_CONSENTITO)

    # Il filtro anti-PII sui **valori** (V5/§12). Per `persona` il campo `nome` è l'unica eccezione
    # dichiarata in tutto lo shim: è ciò che la decisione C del gruppo Processi ha chiesto di registrare,
    # ed è condizionato dal consenso (validatore sopra). Un nome non è comunque un'email, un telefono o
    # un codice fiscale — il filtro non lo riconosce, ma l'eccezione è esplicita perché visibile: nessun
    # altro campo di nessun'altra operazione la riceve. Gli altri campi testuali di `persona`
    # (`ruolo`, `competenze`, `informativa`) restano **dentro** il filtro: un telefono incollato lì
    # sarebbe un dato personale pubblicato in KB.
    campi_pii = corpo.model_dump(exclude_unset=True, mode="json")
    if corpo.entita == "persona":
        campi_pii.pop("nome", None)
    pii.rifiuta_se_presente(campi_pii)

    tabella = corpo.entita
    orari = corpo.orari.model_dump(exclude_unset=True, mode="json") if corpo.orari else None
    # I campi inviati davvero (`exclude_unset`): una PATCH parziale non deve azzerare ciò che non nomina.
    inviati = corpo.model_dump(exclude_unset=True)

    def valore_di(nome: str) -> Any:
        """Il valore del campo, con `orari` già convertito in dizionario (il codec `jsonb` serializza)."""
        return orari if nome == "orari" else getattr(corpo, nome, None)

    try:
        # --- `casa`: UPDATE della propria riga, mai INSERT --------------------------------
        if tabella == "casa":
            assegnazioni, valori = [], []
            for nome in COLONNE_DIRETTE["casa"]:
                if nome in inviati:
                    valori.append(valore_di(nome))
                    assegnazioni.append(f"{nome} = ${len(valori)}")
            if not assegnazioni:
                raise errore(422, "parametri non ammessi — nessun campo da aggiornare per «casa»")
            esito = await sess.execute(
                f"UPDATE trasi.casa SET {', '.join(assegnazioni)} "
                f"WHERE id = trasi.casa_corrente()",
                *valori,
            )

        # --- `scheda_servizio` / `opportunita` / `persona`: INSERT o UPDATE ------------------
        elif corpo.id is None:
            # Il nome dell'entità nel corpo non è sempre il nome della tabella: `persona` (il dato del
            # foglio 1.1) vive in `persona_casa` (db/027). La mappa è qui, non nel chiamante.
            if tabella == "persona":
                tabella = "persona_casa"
            # `casa_id` dall'identità; `aggiornato_ts`/`aggiornato_da` li timbra il trigger. Le colonne
            # scritte sono l'elenco chiuso di COLONNE_DIRETTE: nessun nome di colonna dal chiamante.
            colonne = ["casa_id"]
            valori = [sess.casa_id]
            for nome in COLONNE_DIRETTE[tabella]:
                valore = valore_di(nome)
                if valore is not None:
                    colonne.append(nome)
                    valori.append(valore)
            # `consenso_il` è la colonna che `v_kb_export` filtra: vale la data locale alla creazione e
            # non è nel corpo, perché è un fatto del database — chi crea una persona ha già dichiarato
            # il consenso (il validatore lo impone). Vedi `db/027_persone_casa.sql`.
            if tabella == "persona_casa":
                colonne.append("consenso_il")
                valori.append(_oggi())
            segnaposti = ", ".join(f"${i}" for i in range(1, len(valori) + 1))
            nuovo_id = await sess.fetchval(
                f"INSERT INTO trasi.{tabella} ({', '.join(colonne)}) VALUES ({segnaposti}) RETURNING id",
                *valori,
            )
            if tabella == "persona_casa":
                return {"id": nuovo_id, "entita": "persona", "creato": True, "consenso": True}
            return {"id": nuovo_id, "entita": tabella, "creato": True}

        else:
            if tabella == "persona":
                tabella = "persona_casa"
            assegnazioni, valori = [], []
            for nome in COLONNE_DIRETTE[tabella]:
                if nome in inviati:
                    valori.append(valore_di(nome))
                    assegnazioni.append(f"{nome} = ${len(valori)}")
            if not assegnazioni:
                raise errore(422, "parametri non ammessi — nessun campo da aggiornare oltre a entita e id")
            valori.append(corpo.id)
            esito = await sess.execute(
                f"UPDATE trasi.{tabella} SET {', '.join(assegnazioni)} WHERE id = ${len(valori)}",
                *valori,
            )

    except Exception as exc:  # noqa: BLE001 — la traduzione è il compito di `_rifiuta_violazione`
        _rifiuta_violazione(exc)

    if _righe(esito) == 0:
        # La RLS non ha reso la riga visibile al ruolo: non è della Casa dell'operatore. Stesso criterio di
        # `approva_proposta` — «0 righe» è un rifiuto, non un errore interno.
        raise errore(403, DETAIL_RIGA_NON_DELLA_CASA)

    # `corpo.entita`, non `tabella`: il contratto dichiara «l'entità come dichiarata nella richiesta», e per
    # `persona` la tabella (`persona_casa`) non è nell'enum di `RispostaSalvaDato`.
    return {"id": corpo.id, "entita": corpo.entita, "creato": False}


# --- `proponi_modifica` ---------------------------------------------------------------------------------------


def _casa_della_proposta(corpo: ProponiModificaIn, sess: Sessione) -> int | None:
    """La Casa a cui la proposta appartiene: quella del `payload` se dichiarata, altrimenti quella dell'operatore.

    `payload.casa_id` è una colonna dell'elenco chiuso proprio perché alcune proposte riguardano una Casa diversa da
    quella dell'operatore (es. un AT che propone la scheda di un'altra Casa). Quando il campo manca, la Casa è quella
    dell'identità: un operatore che propone una modifica senza dire *di chi* intende la propria, non una a caso.
    """
    if corpo.payload.casa_id is not None:
        return corpo.payload.casa_id
    return sess.casa_id


def _in_chat(approvatore_ruolo: str, casa_proposta: int | None, sess: Sessione) -> bool:
    """Vero se la proposta riguarda la Casa dell'operatore ed è di competenza del suo gestore (contratto, §9.2).

    Vedi la nota in testa al modulo: la RESTRICTIVE `no_self_approve` impedisce che la **stessa** identità che ha
    creato la proposta la decida, quindi questo campo dichiara la competenza, non la decidibilità immediata.
    """
    return (
        approvatore_ruolo == "gestore"
        and casa_proposta is not None
        and casa_proposta == sess.casa_id
    )


@router.post(
    **_argomenti("proponi_modifica"),
    status_code=201,
)
async def proponi_modifica(
    corpo: ProponiModificaIn, sess: Sessione = Depends(sessione)
) -> dict[str, Any]:
    """Crea una proposta: **nulla** del dominio viene modificato, l'approvazione è umana (F8).

    L'INSERT è colonnare e non passa `approvatore_ruolo`, `stato`, `proposto_da`, `scade_il` né `diff`: li calcola il
    database (`proposta_00_default_tg`, `proposta_03_diff_tg`, `approvatore_default()`), che è l'unico posto in cui la
    regola «chi approva cosa» deve stare.
    """
    if corpo.entita not in ENTITA_DOMINIO:
        raise errore(422, DETAIL_ENTITA_NON_AMMESSA)

    # Filtro anti-PII su `motivazione` **e** `payload` (V5/§12): è il presidio sui *valori*, complementare al
    # presidio sui *campi* (`extra="forbid"`).
    #
    # **Prima** del controllo di routing qui sotto, e l'ordine è deliberato: il filtro anti-PII è un presidio di
    # sicurezza, e un presidio di sicurezza non sta dietro a una decisione di instradamento. Se stesse dopo, un
    # payload con un codice fiscale riceverebbe come risposta «usa `salva_dato`» — cioè il sistema
    # **consiglierebbe** di scrivere altrove un dato personale, invece di rifiutarlo. Misurato: era l'ordine
    # sbagliato nella prima versione, e i test `test_proponi_modifica_dato_personale_*` sono diventati rossi
    # perché si aspettavano `dato_personale_sospetto` e ricevevano il messaggio di routing.
    pii.rifiuta_se_presente(corpo.model_dump(exclude_unset=True, mode="json"))

    # --- BUG-02: i dati della PROPRIA Casa non passano di qui -------------------------------------------
    # La specifica del gruppo Processi è che «ogni casa/ente può modificare i propri dati, della propria
    # casa». Con un accesso solo per Casa non esiste una seconda identità a cui chiedere l'approvazione,
    # quindi una proposta su un dato proprio nasce in un vicolo cieco: `proposto_da` è il ruolo DB (comune
    # a operatore e gestore), la policy `no_self_approve` impedisce a quel ruolo di approvarla, e nessun
    # altro ruolo è ammesso da `upd_client`. Misurato: **5 tipi su 12** restavano per sempre in coda.
    #
    # La correzione non è allentare V4 — è togliere la ragione per cui la proposta esiste: se il dato è
    # della Casa, la Casa lo scrive **direttamente** (`salva_dato` per scheda/opportunità/orari,
    # `crea_evento` per gli eventi). Il ciclo mediato resta per ciò che non è della Casa — `luogo`,
    # `promuovi_esterno`, la scheda/opportunità di un'**altra** Casa — dove un secondo decisore c'è.
    #
    # Il rifiuto è un **422 con la via alternativa**, non un errore muto: chi chiama (l'assistente, o un
    # operatore) deve sapere *dove* andare. Un 403 direbbe «non puoi», che è falso: puoi, per un'altra via.
    #
    # **`entita_id IS NULL` è il caso «nuovo dato»**: non esiste ancora una riga, quindi non c'è una Casa
    # da confrontare e la proposta resta legittima — l'assistente segnala che *serve* una scheda nuova, e
    # qualcuno (l'AT, o la Casa stessa via `salva_dato`) la crea. Rifiutare anche quel caso toglierebbe
    # all'assistente la capacità di segnalare il bisogno, che è il suo compito principale (V3/V6).
    if (
        corpo.entita in ENTITA_DIRETTE
        and corpo.entita_id is not None
        and _casa_della_proposta(corpo, sess) == sess.casa_id
    ):
        raise errore(422, DETAIL_USA_SCRITTURA_DIRETTA.format(entita=corpo.entita))

    casa_proposta = _casa_della_proposta(corpo, sess)
    # `payload` così com'è stato dichiarato: solo i campi inviati (`exclude_unset`), perché un `null` esplicito
    # significherebbe «azzera questo valore», che è una proposta diversa da quella formulata.
    #
    # **Si passa il dizionario, non `json.dumps(...)`.** Il codec `jsonb` del pool (`db.py`,
    # `_prepara_connessione`, `encoder=json.dumps`) serializza già: serializzare qui *e* lasciar serializzare
    # il codec produce una **doppia codifica**, cioè una stringa JSON dentro un `jsonb`. Misurato sul database:
    #   * `json.dumps({...})` → `jsonb_typeof` = `'string'`
    #   * `{...}`             → `jsonb_typeof` = `'object'`
    #
    # Il sintomo non era un errore al momento della scrittura — l'INSERT riusciva — ma al momento
    # dell'**applicazione**, ore dopo e in un altro processo: `applica_proposte_approvate` chiama
    # `trasi.payload_ammesso`/`payload_richiede`, che usano `jsonb_each`, e su una stringa cadono con
    # `cannot call jsonb_each on a non-object`. La proposta restava approvata e non applicabile, con l'errore
    # in `audit` come `errore_applicazione` e l'esito `parziale` in `flusso_run`: il consenso umano raccolto e
    # mai applicato, che è il modo peggiore in cui V4 può rompersi.
    #
    # Il difetto era largo: 44 delle 46 proposte in database avevano `jsonb_typeof(payload) = 'string'`, quindi
    # *nessuna* modifica proposta dal percorso utente poteva essere applicata. Nessun test lo copriva perché le
    # fixture scrivono il payload direttamente in SQL (dove `$5::jsonb` su una stringa è la cosa giusta).
    payload = corpo.payload.model_dump(exclude_unset=True, mode="json")

    try:
        riga = await sess.fetchrow(
            """
            INSERT INTO trasi.proposta (origine, tipo, entita, entita_id, casa_id, payload, motivazione)
            VALUES ('chat', $1, $2, $3, $4, $5::jsonb, $6)
            RETURNING id, approvatore_ruolo, casa_id
            """,
            corpo.tipo,
            corpo.entita,
            corpo.entita_id,
            casa_proposta,
            payload,
            corpo.motivazione,
        )
    except Exception as exc:  # noqa: BLE001 — vedi `_rifiuta_violazione`
        _rifiuta_violazione(exc)

    return {
        "proposta_id": riga["id"],
        "approvatore_ruolo": riga["approvatore_ruolo"],
        "in_chat": _in_chat(riga["approvatore_ruolo"], riga["casa_id"], sess),
    }


# --- `approva_proposta` ---------------------------------------------------------------------------------------

ESITO_DECISIONE = {"approva": "approvata", "rifiuta": "rifiutata"}


@router.post(**_argomenti("approva_proposta"))
async def approva_proposta(
    corpo: ApprovaPropostaIn, sess: Sessione = Depends(sessione)
) -> dict[str, Any]:
    """Decide una proposta **solo se la RLS lo consente** al ruolo dell'operatore (F8, §11).

    L'esito è la riga contata dall'`UPDATE`: zero righe significa che la policy `upd_client` non ha reso la riga
    visibile al ruolo — non è un errore del database e non è un 500. Il 403 «da approvare in coda» è il messaggio che
    il contratto (§9.1) e il prompt degli assistenti (§9.2) chiedono in quel caso.

    Le due condizioni che il contratto distingue dal 403 sono accertate **prima** dell'`UPDATE`, in sola lettura:
    proposta già decisa e proposta oltre `scade_il` sono 409 (il contratto: «scaduta → non più decidibile»). Non è un
    pre-controllo di permesso — quello resta l'`UPDATE` — è la classificazione di uno stato che il 403
    confonderebbe con una coda.
    """
    if corpo.nota:
        pii.rifiuta_se_presente({"nota": corpo.nota})

    riga = await sess.fetchrow(
        "SELECT stato, scade_il, casa_id, approvatore_ruolo FROM trasi.proposta WHERE id = $1",
        corpo.proposta_id,
    )
    if riga is None:
        raise errore(403, DETAIL_DA_APPROVARE_IN_CODA)
    if riga["stato"] != "proposta":
        raise errore(409, f"proposta già {riga['stato']}: non è più decidibile")
    if riga["scade_il"] is not None and riga["scade_il"] < _oggi():
        raise errore(409, "proposta scaduta: non è più decidibile")

    stato = await sess.execute(
        """
        UPDATE trasi.proposta
           SET stato = $1, nota_decisione = $2
         WHERE id = $3
           AND stato = 'proposta'
           AND (scade_il IS NULL OR scade_il >= current_date)
        """,
        ESITO_DECISIONE[corpo.decisione],
        corpo.nota,
        corpo.proposta_id,
    )
    if _righe(stato) == 0:
        # La RLS ha deciso: la proposta non è nella coda di questo ruolo. Nessun dato della proposta viene rivelato
        # oltre a quanto l'operatore ha già in mano (l'identificativo che ha chiesto di decidere).
        raise errore(403, DETAIL_DA_APPROVARE_IN_CODA)

    return {"proposta_id": corpo.proposta_id, "stato": ESITO_DECISIONE[corpo.decisione]}


def _righe(statuscommand: str) -> int:
    """Le righe toccate dallo statuscommand di PostgreSQL (`"UPDATE 0"` → 0)."""
    try:
        return int(statuscommand.rsplit(" ", 1)[-1])
    except (ValueError, IndexError):  # pragma: no cover — un comando diverso da UPDATE non arriva qui
        return 0


def _oggi() -> date:
    """La data locale della decisione: «scaduta» è una domanda sul calendario italiano, non su UTC."""
    from .vicinanza import oggi_locale

    return oggi_locale()
