"""Attrezzoteca della rete (scheda !NEW 5): inventario, prestito, conferma.

Entità **nuova** che la decisione §2 dichiara in due metà diverse, e il codice le tiene separate:

- **Nascita e modifica di `oggetto`** (db/014 + db/032, decisione 2026-09-18): la **propria** Casa li scrive
  direttamente con `salva_dato` (`entita="oggetto"`, `scritture.py`), come la scheda; per gli oggetti delle altre
  Case resta il flusso proposte (tipi `*_oggetto`, decide l'AT). Da questo modulo **nessuna** scrittura su `oggetto`.
- **La lettura dell'inventario** è una sola query (`inventario()`, su `v_inventario`) servita da due porte: il
  browser dell'operatore (`GET /op/attrezzoteca`, cookie) e Onyx (`cerca_oggetto`, contratto congelato, chiave).
  Portale e chat non possono dire numeri diversi perché leggono la stessa funzione.
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
from .contratto import meta
from .db import Sessione, dipendenza_sessione, risolvi_slug_casa
from .errori import errore
from .schemi import ItemOggetto, RispostaCercaOggetto

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


# --- Inventario: una query, due porte (`GET /op/attrezzoteca` e `cerca_oggetto`) ------------------------------

SQL_CASA_ESISTE = "SELECT id FROM trasi.casa WHERE slug = $1"

# `v_inventario` è l'unica fonte: `quantita_disponibile` è già al netto dei movimenti confermati in corso e il badge
# della fonte (V3) arriva dalla vista. Il filtro `q` cerca su nome, descrizione, tipo e badge; `casa_slug` opzionale
# restringe a una Casa. Nessuna somma qui: portale, chat e dashboard dicono lo stesso numero.
SQL_INVENTARIO = """
SELECT v.oggetto_id, v.nome, o.tipo, v.casa_id, v.casa_slug, c.nome AS casa_nome,
       v.quantita, v.quantita_fuori, v.quantita_disponibile,
       v.condizione, v.fonte_nome, v.badge_fonte
  FROM trasi.v_inventario v
  JOIN trasi.oggetto o ON o.id = v.oggetto_id
  JOIN trasi.casa c ON c.id = v.casa_id
 WHERE ($1::text IS NULL
        OR v.nome ILIKE '%' || $1 || '%'
        OR COALESCE(v.descrizione, '') ILIKE '%' || $1 || '%'
        OR COALESCE(o.tipo, '') ILIKE '%' || $1 || '%'
        OR COALESCE(v.badge_fonte, '') ILIKE '%' || $1 || '%')
   AND ($2::text IS NULL OR v.casa_slug = $2)
 ORDER BY v.casa_slug, v.nome
"""


async def inventario(sess: Any, q: str | None, casa_slug: str | None) -> list[dict[str, Any]]:
    """L'inventario della rete come lo vedono **entrambe** le porte: `[{oggetto_id, nome, tipo, casa, …, badge}]`.

    `sess` è la sessione del browser (`SessioneOperatore`) o quella di Onyx (`Sessione`): entrambe espongono
    `fetch`, e la RLS (`ogg_sel`: SELECT a tutta la rete) decide cosa si vede.
    """
    righe = await sess.fetch(SQL_INVENTARIO, (q or "").strip() or None, casa_slug)
    return [
        {
            "oggetto_id": r["oggetto_id"],
            "nome": r["nome"],
            "tipo": r["tipo"],
            "casa": r["casa_slug"],
            "casa_nome": r["casa_nome"],
            "quantita": r["quantita"],
            "quantita_fuori": r["quantita_fuori"],
            "quantita_disponibile": r["quantita_disponibile"],
            "condizione": r["condizione"],
            "fonte": r["fonte_nome"],
            "badge": r["badge_fonte"],
        }
        for r in righe
    ]


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
    """GET /op/attrezzoteca?q= — inventario di rete, leggibile da ogni Casa (US-5.1). Stessa query di `cerca_oggetto`."""
    return {"items": await inventario(sess, q, None)}


# Il router del contratto congelato (prefisso `/v1/u/{email}`, chiave + identità): lo monta `main.py` accanto a
# `routes_lettura`. Separato da `router` (che va sotto `/op` con il cookie) perché le due porte hanno due
# autenticazioni diverse e non devono poter essere confuse.
router_contratto = APIRouter()


@router_contratto.get("/cerca_oggetto", response_model=RispostaCercaOggetto, **meta("cerca_oggetto"))
async def cerca_oggetto(
    q: str | None = Query(
        default=None, min_length=1, max_length=120,
        description="Cosa si cerca (nome, descrizione o tipo dell'oggetto). Vuoto = tutto l'inventario.",
    ),
    casa: str | None = Query(
        default=None, description="Slug o nome della Casa di Quartiere; se omesso, tutte le Case."
    ),
    sess: Sessione = Depends(dipendenza_sessione),
) -> RispostaCercaOggetto:
    """Cerca nell'attrezzoteca della rete (US-5.1): dove si trova un oggetto, quanti pezzi sono disponibili.

    Aperta a tutte le Case e a `rete` (la RLS `ogg_sel` dà SELECT a tutta la rete): l'inventario è memoria della
    rete, non della singola Casa. `casa` si risolve come in `eventi_oggi` (`risolvi_slug_casa`: il modello scrive
    il nome più spesso dello slug); una Casa inesistente è **404** (vocabolario chiuso), un inventario vuoto è
    `items: []` con 200.
    """
    casa_slug: str | None = None
    if casa and casa.strip():
        richiesta = casa.strip()
        if await sess.fetchval(SQL_CASA_ESISTE, richiesta) is not None:
            casa_slug = richiesta
        else:
            casa_slug = await risolvi_slug_casa(sess, richiesta)
            if casa_slug is None:
                raise errore(404, f"casa non trovata: nessuna Casa di Quartiere con slug «{richiesta}»")
    items = await inventario(sess, q, casa_slug)
    return RispostaCercaOggetto(items=[ItemOggetto(**item) for item in items])


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


__all__ = [
    "MovimentoIn",
    "RegistraRichiestaIn",
    "cerca_oggetto",
    "inventario",
    "op_attrezzoteca",
    "op_movimenti_da_confermare",
    "op_movimento",
    "op_movimento_conferma",
    "op_registra_richiesta",
    "router",
    "router_contratto",
]
