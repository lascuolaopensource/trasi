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
    """Il corpo di `registra_richiesta`: solo campi del registro, nessun campo del cittadino."""

    model_config = ConfigDict(extra="forbid")

    categoria: Literal[CATEGORIE]  # type: ignore[valid-type]
    esito: Literal[ESITI]  # type: ignore[valid-type]
    destinazione_id: int | None = Field(default=None, ge=1)
    destinazione_nota: str | None = Field(default=None, min_length=1)

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
    """Registra la richiesta di orientamento: solo il registro operativo, nessun dato del cittadino.

    `casa_id` viene **dall'identità** (`identita_onyx` → `SET LOCAL ROLE` → `trasi.casa_corrente()`), mai dal corpo:
    un operatore non può registrare una richiesta a nome di un'altra Casa. La policy `rich_ins_casa` del database
    verifica comunque che la riga appartenga alla Casa corrente — la seconda barriera, non la prima.
    """
    pii.rifiuta_se_presente(corpo.model_dump(exclude_unset=True, mode="json"))

    try:
        richiesta_id = await sess.fetchval(
            """
            INSERT INTO trasi.richiesta (casa_id, categoria, esito, destinazione_id, destinazione_nota)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            sess.casa_id,
            corpo.categoria,
            corpo.esito,
            corpo.destinazione_id,
            corpo.destinazione_nota,
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
    pii.rifiuta_se_presente(corpo.model_dump(exclude_unset=True, mode="json"))

    casa_proposta = _casa_della_proposta(corpo, sess)
    # `payload` così com'è stato dichiarato: solo i campi inviati (`exclude_unset`), perché un `null` esplicito
    # significherebbe «azzera questo valore», che è una proposta diversa da quella formulata.
    #
    # **Dizionario, non stringa.** Il codec `jsonb` del pool (`db.py`, `_prepara_connessione`) codifica già con
    # `json.dumps`: passare qui una stringa la faceva incapsulare come *stringa JSON* dentro il `jsonb`, e il
    # database conservava `"{\"inizio\": …}"` invece di `{"inizio": …}`. Il sintomo non era un errore al momento
    # della scrittura — l'INSERT riusciva — ma al momento dell'**applicazione**, ore dopo e in un altro processo:
    # `applica_proposte_approvate` chiama `trasi.payload_ammesso(v_rec.payload)`, che fa `jsonb_each` su una
    # stringa e cade con `cannot call jsonb_each on a non-object`. La proposta risultava approvata e non
    # applicabile, con l'errore registrato in `audit` come `errore_applicazione`.
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
