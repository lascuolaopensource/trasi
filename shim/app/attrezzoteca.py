"""Attrezzoteca della rete (scheda !NEW 5): inventario, prestito, conferma.

Entità **nuova** che la decisione §2 dichiara in due metà diverse, e il codice le tiene separate:

- **Nascita e modifica di `oggetto`** passano dal flusso proposte (V4): da qui **nessuna** scrittura su `oggetto`,
  nemmeno indiretta. Chi vuole un attrezzo in memoria lo propone, come per ogni altro dominio.
- **Il movimento** (prestito/spostamento) è invece **evento operativo** con scrittura immediata, come la registrazione
  della richiesta: il ritiro delle sedie non può aspettare una coda serale. La scrittura è comunque **mediata**:
  l'INSERT crea solo `stato='proposto'` e il passaggio a `confermato`/`rientrato` avviene solo per
  `trasi.conferma_movimento` (SECURITY DEFINER dell'owner `applicatore`), che verifica la casa del chiamante — la
  regola «conferma solo la destinataria, rientro solo la cedente/rete» vive **là dentro**, non qui. Lo shim
  traduce l'esito (righe toccate o errore parlante), non decide i permessi.

«Errori DB → 403/422 parlanti, mai 500»: le violazioni di CHECK (`quantita`, `condizione`, transizione vietata
dalla funzione) devono arrivare al LLM in italiano leggibile, perché possa correggersi invece di dichiarare guasti.
Un rifiuto della RLS è un **403** (la decisione è del database, non un guasto); l'unico 500 ammesso è il handler
generico di `errori.py` su un bug vero, non su un input cattivo.

Disponibilità: `v_inventario` è l'unica fonte — il conteggio «quanti pezzi sono fuori adesso» è calcolato dalla
vista (al netto dei movimenti confermati in corso), mai sommato qui, così la UI, la chat e la dashboard Metabase
dicono lo stesso numero.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Literal

from asyncpg.exceptions import (
    CheckViolationError,
    ForeignKeyViolationError,
    InsufficientPrivilegeError,
    RaiseError,
)
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import pii
from .auth import SessioneOperatore, sessione_corrente
from .badge import badge_kb, nome_fonte
from .errori import errore

router = APIRouter()

# --- `registra_richiesta` (scheda !NEW 3, decisione §2) -------------------------------------------------------
# Eccezione dichiarata a V4: INSERT diretto + audit, come iCal. Qui però NON si fa l'INSERT: la regola
# `richiesta` senza campi cittadino e l'audit atomica stanno in `trasi.registra_richiesta_operatore` (db/006), che
# è l'unico punto in cui «registro + audit» non possono divergere. Lo shim chiama quella funzione.

CATEGORIE_RICHIESTA = (
    "orientamento", "servizi_sociali", "fiscale_isee", "lavoro", "abitare",
    "salute", "interculturale", "ascolto_solitudine", "eventi_attivita", "altro",
)
ESITI_RICHIESTA = ("risolta", "inviata_altrove", "non_trovata", "rinviata")


class RegistraRichiestaIn(BaseModel):
    """Il corpo di `POST /op/registra_richiesta`: **quattro** chiavi, e nient'altro (V5).

    `extra="forbid"` è il presidio strutturale: una chiave in più (`nome`, `telefono_cittadino`, `casa_id`) è un
    422 prima di toccare il DB. `casa_id` non esiste proprio: la Casa è quella della sessione, e un operatore non
    registra a nome di un'altra Casa.
    """

    model_config = ConfigDict(extra="forbid")

    categoria: Literal[CATEGORIE_RICHIESTA]  # type: ignore[valid-type]
    esito: Literal[ESITI_RICHIESTA]  # type: ignore[valid-type]
    destinazione_id: int | None = Field(default=None, ge=1)
    destinazione_nota: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def _destinazione_se_inviata(self) -> "RegistraRichiestaIn":
        """`inviata_altrove` senza destinazione non serve al registro: il DB la rifiuterebbe (CHECK), qui il 422
        è dichiarato e in italiano, così il chiamante sa correggere."""
        if self.esito == "inviata_altrove" and self.destinazione_id is None and not self.destinazione_nota:
            raise ValueError("destinazione_id o destinazione_nota obbligatori quando esito è «inviata_altrove»")
        return self


def _traduci_db(exc: Exception) -> None:
    """Traduce una violazione del DB in una risposta parlante (403/422), poi rilancia.

    Le funzioni di db/006 sollevano `RaiseError` con messaggi italiani propri («destinazione inesistente»,
    «conferma solo la casa destinataria»): quel testo è già il messaggio del dominio e si propaga così com'è.
    Le violazioni di vincolo nude (CHECK, FK) non hanno un testo pensato per il LLM e vengono invece mappate.
    """
    if isinstance(exc, RaiseError):
        testo = str(exc).strip()
        # Il testo delle fn di dominio è parlante e non contiene valori della richiesta.
        raise errore(422, testo) from exc
    if isinstance(exc, CheckViolationError):
        raise errore(422, "valore non ammesso dal modello dati dell'attrezzoteca o della richiesta") from exc
    if isinstance(exc, ForeignKeyViolationError):
        raise errore(422, "un riferimento non esiste in memoria (oggetto, casa o destinazione)") from exc
    # La RLS ha deciso: il ruolo dell'operatore non può fare questa scrittura. **Non è un guasto** ed è il
    # caso più probabile di tutto il modulo, perché ogni INSERT qui è filtrato da una policy: cedere un
    # oggetto che è di un'altra Casa (`mov_ins_casa` chiede `oggetto.casa_id = casa_corrente()`) finisce
    # qui. Senza questo ramo l'eccezione di asyncpg attraversa il modulo e diventa un **500 «errore
    # interno dello shim»**, cioè l'operatore legge un guasto al posto di «non puoi prestare un oggetto che
    # non è tuo» — e chi diagnostica cerca un bug che non c'è. Misurato: `POST /op/movimento` su un oggetto
    # di un'altra Casa → `InsufficientPrivilegeError: new row violates row-level security policy for table
    # "movimento"` → 500. Lo stesso in `scritture.py` è già 403: due traduttori, un criterio solo.
    if isinstance(exc, InsufficientPrivilegeError):
        raise errore(403, "operazione non consentita al ruolo dell'operatore") from exc
    raise


@router.post(
    "/registra_richiesta",
    operation_id="op_registra_richiesta",
    status_code=201,
    summary="Registra la richiesta del cittadino allo sportello in forma anonima: solo categoria, esito e "
    "destinazione. Nessun dato personale, mai (V5). Chi registra: l'operatore della propria Casa.",
    tags=["op"],
)
async def op_registra_richiesta(
    corpo: RegistraRichiestaIn, sess: SessioneOperatore = Depends(sessione_corrente)
) -> dict[str, Any]:
    """POST /op/registra_richiesta — la scrittura arriva a `trasi.registra_richiesta_operatore`, mai INSERT diretto.

    Filtro anti-PII **sui valori** (`destinazione_nota` è testo libero e potrebbe portare un telefono dettato a
    voce): è la seconda barriera dopo `extra="forbid"`, perché V5 protegge sia le chiavi sia ciò che contengono.
    """
    pii.rifiuta_se_presente(corpo.model_dump(exclude_unset=True, mode="json"))
    try:
        richiesta_id = await sess.fetchval(
            "SELECT trasi.registra_richiesta_operatore($1, $2, $3, $4, $5)",
            sess.casa_slug, corpo.categoria, corpo.esito, corpo.destinazione_id, corpo.destinazione_nota,
        )
    except Exception as exc:  # noqa: BLE001 — la traduzione è compito di `_traduci_db`
        _traduci_db(exc)
    return {"richiesta_id": richiesta_id, "casa": sess.casa_slug}


# --- Inventario (`GET /op/attrezzoteca`) ----------------------------------------------------------------------


@router.get(
    "/attrezzoteca",
    operation_id="op_attrezzoteca",
    summary="Cerca nell'inventario degli oggetti condivisi della rete: dove si trova un oggetto, in che quantità "
    "e condizioni. Disponibilità al netto dei movimenti confermati; fonte dichiarata (V3).",
    tags=["op"],
)
async def op_attrezzoteca(
    q: str | None = Query(default=None, min_length=1, description="Nome o descrizione dell'oggetto."),
    sess: SessioneOperatore = Depends(sessione_corrente),
) -> dict[str, Any]:
    """GET /op/attrezzoteca?q= — inventario di rete, leggibile da ogni Casa (US-5.1).

    Quantità «disponibile» = quella della vista `v_inventario`, già al netto dei confermati in corso; qui non si
    somma nulla, così il numero che legge l'operatore è lo stesso che vede la Casa prestatrice. Il badge della fonte
    (V3) arriva dalla vista ed è restituito com'è, non ricomposto.
    """
    testo = (q or "").strip() or None
    righe = await sess.fetch(
        """
        SELECT oggetto_id, nome, descrizione, casa_id, casa_slug, quantita, quantita_fuori, quantita_disponibile,
               condizione, fonte_nome, badge_fonte
          FROM trasi.v_inventario
         WHERE ($1::text IS NULL OR nome ILIKE '%' || $1 || '%' OR COALESCE(descrizione, '') ILIKE '%' || $1 || '%'
                OR casa_slug ILIKE '%' || $1 || '%')
         ORDER BY casa_slug, nome
        """,
        testo,
    )
    items = [
        {
            "oggetto_id": r["oggetto_id"],
            "nome": r["nome"],
            "descrizione": r["descrizione"],
            "casa": r["casa_slug"],
            "quantita": r["quantita"],
            "quantita_fuori": r["quantita_fuori"],
            "quantita_disponibile": r["quantita_disponibile"],
            "condizione": r["condizione"],
            "fonte": r["fonte_nome"],
            "badge": r["badge_fonte"],
        }
        for r in righe
    ]
    return {"items": items}


# --- Movimenti da confermare (`GET /op/movimenti_da_confermare`) ----------------------------------------------


@router.get(
    "/movimenti_da_confermare",
    operation_id="op_movimenti_da_confermare",
    summary="Elenca i prestiti in attesa di conferma che riguardano la propria Casa, come cedente o come "
    "ricevente, dal più vecchio: sono quelli che aspettano una decisione umana da più tempo.",
    tags=["op"],
)
async def op_movimenti_da_confermare(sess: SessioneOperatore = Depends(sessione_corrente)) -> dict[str, Any]:
    """GET /op/movimenti_da_confermare — i movimenti in stato `proposto` della vista `v_movimenti_da_confermare`.

    Il filtro per la Casa della sessione sta **nella query**, e non è ridondante con la RLS: la vista è
    `security_invoker=false` (db/016), quindi al suo interno la lettura gira con i privilegi del proprietario e la
    policy di `movimento` non vede il chiamante. Senza il `WHERE`, un operatore leggerebbe i prestiti in attesa di
    tutte e dieci le Case — l'informazione non è riservata, ma la lista decisionale sì: è la sua.

    `dal`/`al` escono come date ISO e `ts` come data-ora ISO, così la UI non deve interpretare formati; il
    `giorni_attesa` è quello calcolato dalla vista (un solo posto per la regola del conteggio, come per la
    disponibilità di `v_inventario`).
    """
    righe = await sess.fetch(
        """
        SELECT id, oggetto_id, oggetto_nome, oggetto_quantita, da_casa_id, da_casa_slug,
               a_casa_id, a_casa_slug, dal, al, motivazione, ts, giorni_attesa
          FROM trasi.v_movimenti_da_confermare
         WHERE da_casa_id = $1 OR a_casa_id = $1
         ORDER BY ts, id
        """,
        sess.casa_id,
    )
    movimenti = [
        {
            "id": r["id"],
            "oggetto_id": r["oggetto_id"],
            "oggetto": r["oggetto_nome"],
            "oggetto_quantita": r["oggetto_quantita"],
            "da_casa_id": r["da_casa_id"],
            "da_casa_slug": r["da_casa_slug"],
            "a_casa_id": r["a_casa_id"],
            "a_casa_slug": r["a_casa_slug"],
            "dal": r["dal"].isoformat(),
            "al": r["al"].isoformat() if r["al"] is not None else None,
            "motivazione": r["motivazione"],
            "ts": r["ts"].isoformat(),
            "giorni_attesa": r["giorni_attesa"],
        }
        for r in righe
    ]
    return {"movimenti": movimenti}


# --- Movimenti (`POST /op/movimento`, `POST /op/movimento/{id}/conferma`) -------------------------------------

CONDIZIONI = ("integro", "danneggiato", "mancante_di_parti")


class MovimentoIn(BaseModel):
    """Il corpo di `POST /op/movimento`: il prestito di un oggetto della propria Casa verso un'altra.

    `da_casa` non è una chiave: chi sposta è la Casa della sessione (la cedente), e nessuna Casa registra un
    prestito «a nome di» un'altra. L'oggetto è per `id` (il nome non è univoco). Niente date precompilate dal
    chiamante per il passato: se manca, `dal` è oggi.

    `dal`/`al` sono `date`, non stringhe ISO: è la convenzione del resto dello shim (`eventi_oggi`) e non una
    preferenza di stile — asyncpg deduce il tipo del parametro dal cast `$4::date` della query, e legarci una stringa
    è un `DataError` a runtime (`'str' object has no attribute 'toordinal'`), cioè un 500 al posto di un 201. Con
    `date`, una data scritta male è un 422 di pydantic in italiano, prima di toccare il database.
    """

    model_config = ConfigDict(extra="forbid")

    oggetto_id: int = Field(ge=1)
    a_casa: str = Field(min_length=1, description="Slug della Casa destinataria (es. bozzano).")
    dal: date | None = Field(default=None, description="Data inizio prestito ISO AAAA-MM-GG; se omessa, oggi.")
    al: date | None = Field(default=None, description="Data rientro prevista ISO AAAA-MM-GG.")


@router.post(
    "/movimento",
    operation_id="op_movimento",
    status_code=201,
    summary="Registra lo spostamento (prestito) di un oggetto dalla propria Casa a un'altra: nasce 'proposto' e "
    "diventa effettivo solo dopo conferma della Casa ricevente (V6: decide la destinataria).",
    tags=["op"],
)
async def op_movimento(
    corpo: MovimentoIn, sess: SessioneOperatore = Depends(sessione_corrente)
) -> dict[str, Any]:
    """POST /op/movimento — INSERT diretto con `stato='proposto'` (evento operativo, eccezione documentata V4).

    La `a_casa` è risolta in `casa_id` **nel DB** (`slug → id`), perché un `id` nel corpo lascerebbe al chiamante la
    scelta di una Casa arbitraria; lo slug è il vocabolario che l'operatore vede. La condizione di partenza non è
    richiesta: è rilevata al rientro (`conferma`), quando chi riceve la vede.
    """
    pii.rifiuta_se_presente(corpo.model_dump(exclude_unset=True, mode="json"))
    try:
        riga = await sess.fetchrow(
            """
            INSERT INTO trasi.movimento (oggetto_id, da_casa_id, a_casa_id, dal, al, stato)
            VALUES (
                $1,
                $2,
                (SELECT c.id FROM trasi.casa c WHERE c.slug = $3),
                COALESCE($4::date, current_date),
                $5::date,
                'proposto'
            )
            RETURNING id, stato
            """,
            corpo.oggetto_id,
            sess.casa_id,
            corpo.a_casa,
            corpo.dal,
            corpo.al,
        )
    except Exception as exc:  # noqa: BLE001
        _traduci_db(exc)
    if riga is None:
        # La sotto-select non ha trovato lo slug della destinataria (a_casa_id NULL violerebbe il vincolo, quindi
        # la FK avrebbe già parlato); se arriviamo qui è solo perché la Casa non esiste.
        raise errore(422, f"Casa destinataria sconosciuta: «{corpo.a_casa}»")
    return {"movimento_id": riga["id"], "stato": riga["stato"]}


@router.post(
    "/movimento/{movimento_id}/conferma",
    operation_id="op_movimento_conferma",
    summary="Conferma, rifiuta o marca il rientro di uno spostamento. Decide chi riceve (destinataria) sul "
    "proposto; chi presta (cedente) o la rete sul rientro. La regola è nel DB, non qui.",
    tags=["op"],
)
async def op_movimento_conferma(
    movimento_id: int,
    corpo: dict[str, Any] | None = None,
    sess: SessioneOperatore = Depends(sessione_corrente),
) -> dict[str, Any]:
    """POST /op/movimento/{id}/conferma — delega a `trasi.conferma_movimento` (SECURITY DEFINER).

    Lo shim **non** fa UPDATE su `movimento`: non ne ha il permesso (per design, UPDATE solo di `applicatore`), e
    non deve avercelo — così la transizione con la verifica della casa («solo la destinataria conferma», «solo la
    cedente marca il rientro») sta in un punto solo del database. Il `ruolo` passato è quello della sessione.
    """
    azione = "conferma"
    condizione: str | None = None
    if corpo:
        chiavi_extra = set(corpo) - {"azione", "condizione_rientro"}
        if chiavi_extra:
            raise errore(422, "parametri non ammessi — chiavi non previste: " + ", ".join(sorted(chiavi_extra)))
        azione = corpo.get("azione", "conferma")
        condizione = corpo.get("condizione_rientro")
        if condizione is not None and condizione not in CONDIZIONI:
            raise errore(422, "condizione_rientro non ammessa — valori: " + ", ".join(CONDIZIONI))
        if "condizione_rientro" in corpo:
            pii.rifiuta_se_presente({"condizione_rientro": condizione or ""})

    try:
        await sess.execute(
            "SELECT trasi.conferma_movimento($1, $2)", movimento_id, sess.ruolo
        )
    except RaiseError as exc:
        testo = str(exc).strip()
        # La funzione distingue «non spetta a te» (P0001 con «ruolo»/«destinatario») da «transizione impossibile».
        # Il testo va al chiamante così com'è (parlante, senza valori del payload).
        raise errore(409, testo) from exc
    except Exception as exc:  # noqa: BLE001
        _traduci_db(exc)
    return {"movimento_id": movimento_id, "stato": azione if azione in ("conferma", "rifiuta", "rientro") else "aggiornato"}


# --- Prenotazione anticipata (`POST /op/prenota`) — US-5.2, dialogo «proiettore il 30 settembre» ---

class PrenotaIn(BaseModel):
    """Il corpo di `POST /op/prenota`: l'oggetto, la Casa che lo riceve, e le due date.

    Qui «prenotare» non è un dominio nuovo: è un `movimento` con `dal` nel futuro — la stessa riga,
    lo stesso flusso di conferma (V6: la Casa ricevente decide), con la differenza che il conflitto di
    periodo non è un NOTICE invisibile ma **una lista nel ritorno**: l'assistente deve poter dire
    «c'è già chi lo vuole in quelle date», altrimenti promette ciò che non è.
    """

    model_config = ConfigDict(extra="forbid")

    oggetto_id: int = Field(ge=1)
    a_casa: str = Field(min_length=1, description="Slug della Casa che riceverà l'oggetto (es. bozzano).")
    dal: date = Field(description="Data inizio prenotazione ISO AAAA-MM-GG (anche futura).")
    al: date = Field(description="Data fine prenotazione ISO AAAA-MM-GG, uguale o successiva a dal.")
    motivazione: str | None = Field(default=None, max_length=80, description="Uso dichiarato, facoltativo.")


@router.post(
    "/prenota",
    operation_id="op_prenota",
    status_code=201,
    summary="Prenota un oggetto per un periodo futuro: nasce 'proposto' e va confermato dalla Casa che "
    "lo riceve. Se nel periodo l'oggetto è già prenotato o in prestito, la risposta lo dice (campo "
    "conflitti): la prenotazione si registra, la decisione resta alle Case (V6).",
    tags=["op"],
)
async def op_prenota(corpo: PrenotaIn, sess: SessioneOperatore = Depends(sessione_corrente)) -> dict[str, Any]:
    """POST /op/prenota — delega a `trasi.prenota_oggetto` (SECURITY DEFINER, db/026).

    `dal`/`al` sono `date` e non stringhe per la stessa ragione di `op_movimento`: asyncpg le lega al
    cast `$4::date` della funzione, e una stringa è un DataError a runtime invece di un 422 pydantic.
    La risposta riporta **tutto** ciò che l'assistente deve leggere a voce alta: oggetto, Case, periodo,
    stato, e i conflitti già formattati (movimento, Case, date) — così la frase in chat è veritiera
    senza che il modello debita interrogare di nuovo.
    """
    pii.rifiuta_se_presente(corpo.model_dump(exclude_unset=True, mode="json"))
    try:
        riga = await sess.fetchval(
            "SELECT trasi.prenota_oggetto($1, $2, $3::date, $4::date, $5)",
            corpo.oggetto_id,
            corpo.a_casa,
            corpo.dal,
            corpo.al,
            sess.ruolo,
        )
    except RaiseError as exc:
        raise errore(409, str(exc).strip()) from exc
    except Exception as exc:  # noqa: BLE001 — la traduzione è compito di `_traduci_db`
        _traduci_db(exc)
    esito = json.loads(riga) if isinstance(riga, str) else riga
    return esito


# --- Rifiuto del prestito (`POST /op/movimento/{id}/rifiuta`) — US-5.3 -------------------------
@router.post(
    "/movimento/{movimento_id}/rifiuta",
    operation_id="op_movimento_rifiuta",
    summary="Rifiuta un prestito proposto. Decide chi riceve (destinataria): è la stessa regola della "
    "conferma, e il rifiuto è terminale — un prestito rifiutato non torna proponibile.",
    tags=["op"],
)
async def op_movimento_rifiuta(
    movimento_id: int,
    sess: SessioneOperatore = Depends(sessione_corrente),
) -> dict[str, Any]:
    """POST /op/movimento/{id}/rifiuta — delega a `trasi.rifiuta_movimento` (SECURITY DEFINER, db/026).

    Il «no» della Casa ricevente: la transizione `proposto → rifiutato` esisteva nel dominio
    (CHECK e trigger) ma nessuna funzione la raggiungeva — `conferma_movimento` non fa rifiuti, e il
    rifiuto implicito («non confermo») lasciava il prestito per sempre in `proposto`, cioè nella lista
    «da confermare» di due operatori. Un rifiuto è una decisione: va registrata come tale.
    """
    try:
        await sess.execute("SELECT trasi.rifiuta_movimento($1, $2)", movimento_id, sess.ruolo)
    except RaiseError as exc:
        raise errore(409, str(exc).strip()) from exc
    except Exception as exc:  # noqa: BLE001
        _traduci_db(exc)
    return {"movimento_id": movimento_id, "stato": "rifiutato"}


# --- Rientro con condizione (`POST /op/movimento/{id}/rientro`) — US-5.3, dialogo «trapano TR04» ---


class RientroIn(BaseModel):
    """Il corpo di `POST /op/movimento/{id}/rientro`: come torna l'oggetto, e se si sospende.

    `sospendi=true` toglie l'oggetto dall'inventario (attivo=false): è la risposta al dialogo
    «il caricabatterie non funziona più» — l'oggetto danneggiato non resta prenotabile finché una
    Casa non lo ripristina con una proposta `modifica_oggetto` (attivo=true), che è una modifica
    decisa, non un effetto collaterale del rientro.
    """

    model_config = ConfigDict(extra="forbid")

    condizione: Literal["integro", "danneggiato", "mancante_di_parti"]  # type: ignore[valid-type]
    sospendi: bool = False


@router.post(
    "/movimento/{movimento_id}/rientro",
    operation_id="op_movimento_rientro",
    summary="Marca il rientro di un prestito confermato, con la condizione dell'oggetto al passaggio "
    "(integro | danneggiato | mancante_di_parti). Con sospendi=true l'oggetto esce dall'inventario "
    "finché una Casa non lo ripristina: è la sospensione del dialogo «il caricabatterie non funziona più».",
    tags=["op"],
)
async def op_movimento_rientro(
    movimento_id: int,
    corpo: RientroIn,
    sess: SessioneOperatore = Depends(sessione_corrente),
) -> dict[str, Any]:
    """POST /op/movimento/{id}/rientro — delega a `trasi.riporta_oggetto` (SECURITY DEFINER, db/026).

    La condizione **si scrive sull'oggetto**, non solo sul movimento: è il suo stato d'ora in poi, e
    `v_inventario` la mostra a tutta la rete al prossimo `GET /op/attrezzoteca`. Decidere il rientro
    spetta alla Casa cedente (o alla rete), come per `conferma_movimento` — la regola sta nella
    funzione, non qui.
    """
    pii.rifiuta_se_presente(corpo.model_dump(exclude_unset=True, mode="json"))
    try:
        riga = await sess.fetchval(
            "SELECT trasi.riporta_oggetto($1, $2, $3, $4)",
            movimento_id,
            sess.ruolo,
            corpo.condizione,
            corpo.sospendi,
        )
    except RaiseError as exc:
        raise errore(409, str(exc).strip()) from exc
    except Exception as exc:  # noqa: BLE001
        _traduci_db(exc)
    esito = json.loads(riga) if isinstance(riga, str) else riga
    return esito


# --- Uso degli oggetti (`GET /op/uso_oggetti`) — US-5.4 ----------------------------------------


@router.get(
    "/uso_oggetti",
    operation_id="op_uso_oggetti",
    summary="Statistiche d'uso degli oggetti negli ultimi 12 mesi: fascia basso/medio/alto con le soglie "
    "della rete. Gli oggetti poco usati sono candidati a cessione; quelli molto richiesti a un secondo "
    "esemplare. Segnala anche i rientri in ritardo.",
    tags=["op"],
)
async def op_uso_oggetti(sess: SessioneOperatore = Depends(sessione_corrente)) -> dict[str, Any]:
    """GET /op/uso_oggetti — `v_uso_oggetti` (db/016) + i rientri in ritardo.

    La fascia di uso (`basso`/`medio`/`alto`) è calcolata dalla vista con le soglie dei parametri
    `[P] attrezzoteca_soglia_bassa/alta`: un solo posto per la regola, come per la disponibilità.
    Il ritardo è qui e non in una vista: «non rientra nei tempi previsti» è un movimento `confermato`
    con `al` passata — una query, non un'aggregazione (e la lista è brevissima quando va bene: vuota).
    """
    righe = await sess.fetch(
        """
        SELECT oggetto_id, nome, casa_slug, condizione, n_movimenti_12m, ultimo_movimento_ts, fascia_uso
          FROM trasi.v_uso_oggetti
         ORDER BY fascia_uso DESC, n_movimenti_12m DESC, nome
        """
    )
    ritardi = await sess.fetch(
        """
        SELECT m.id AS movimento_id, m.oggetto_id, o.nome AS oggetto,
               cda.slug AS da_casa, ca.slug AS a_casa, m.dal, m.al,
               (current_date - m.al) AS giorni_ritardo
          FROM trasi.movimento m
          JOIN trasi.oggetto o ON o.id = m.oggetto_id
          JOIN trasi.casa cda ON cda.id = m.da_casa_id
          JOIN trasi.casa ca  ON ca.id  = m.a_casa_id
         WHERE m.stato = 'confermato'
           AND m.al IS NOT NULL
           AND m.al < current_date
         ORDER BY giorni_ritardo DESC, m.id
        """
    )
    return {
        "uso": [
            {
                "oggetto_id": r["oggetto_id"],
                "nome": r["nome"],
                "casa": r["casa_slug"],
                "condizione": r["condizione"],
                "n_movimenti_12m": r["n_movimenti_12m"],
                "ultimo_movimento": r["ultimo_movimento_ts"].isoformat() if r["ultimo_movimento_ts"] else None,
                "fascia_uso": r["fascia_uso"],
            }
            for r in righe
        ],
        "in_ritardo": [
            {
                "movimento_id": r["movimento_id"],
                "oggetto_id": r["oggetto_id"],
                "oggetto": r["oggetto"],
                "da_casa": r["da_casa"],
                "a_casa": r["a_casa"],
                "dal": r["dal"].isoformat(),
                "al": r["al"].isoformat(),
                "giorni_ritardo": r["giorni_ritardo"],
            }
            for r in ritardi
        ],
    }


__all__ = [
    "MovimentoIn",
    "PrenotaIn",
    "RegistraRichiestaIn",
    "RientroIn",
    "op_attrezzoteca",
    "op_movimenti_da_confermare",
    "op_movimento",
    "op_movimento_conferma",
    "op_movimento_rifiuta",
    "op_movimento_rientro",
    "op_prenota",
    "op_registra_richiesta",
    "op_uso_oggetti",
    "router",
]
