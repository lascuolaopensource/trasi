"""`GET /op/eventi?dal&al&casa_id?`: gli eventi di un **intervallo** di date, non di un giorno solo (§5.2, `T-SHIM-06`).

**Perché serve, avendo già `eventi_oggi`.** Il contratto congelato copre **un giorno** e **una Casa**
(`shim/app/routes_lettura.py:144`): basta alla riga «Oggi» della Home, non basta alla scheda del luogo, che chiede un
intervallo `settimana | mese` (§4.2.2). Due strade erano possibili — estendere `eventi_oggi` (che è nel contratto
**congelato con Onyx**, quindi non si tocca) o aggiungere un endpoint del browser. Si è scelta la seconda: canale
diverso, contratto diverso, nessun rischio su ciò che Onyx ha già registrato.

**`dal` e `al` sono date locali, non istanti.** Il fuso del database è `Europe/Rome` (verificato: `SHOW TimeZone`), e
il confronto è su `inizio::date`, cioè sul **giorno italiano**: l'evento delle 21:30 di oggi appartiene a oggi. La
conversione a UTC lo sposterebbe a domani per chi guarda la sera — è il difetto già misurato su `eventi_oggi`, e la
ragione per cui qui il taglio è esplicito.

**Il fuso di uscita è quello italiano.** `asyncpg` restituisce i `timestamptz` in UTC e un `isoformat()` diretto
mostrerebbe le 18:30 come «16:30»: gli istanti si convertono con `astimezone(FUSO)` prima di uscire, così la pagina
non deve sapere in che fuso è il database.

**Lo stato `annullato` è escluso dalla vista.** `v_eventi` filtra `annullato = false` e `COALESCE(fine, inizio) >=
now()`: un evento ritirato non è in programma, e un evento di più giorni resta visibile finché non è finito. Leggere
la **vista** invece di `trasi.evento` è ciò che tiene allineati chat, cruscotto e questa pagina sulla stessa domanda
(«cosa è in programma»), con una sola definizione.

**Nessuna scrittura.** `POST /op/eventi` (l'evento della propria Casa, opzione A) è di un altro modulo: qui si legge.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, FastAPI, Query

from .auth import SessioneOperatore, sessione_corrente
from .badge import badge_esterna, badge_kb, nome_fonte
from .errori import errore

router = APIRouter()

# Il fuso italiano: gli istanti escono convertiti, il `badge` porta la data **locale** dell'evento.
FUSO = ZoneInfo("Europe/Rome")

# Finestra massima dichiarata: la scheda chiede una settimana o un mese, e un intervallo di un anno non è una
# domanda della pagina — è un'estrazione. Il limite è il fratello del tetto di area di `poi_op`: entrambi traducono
# «questo endpoint serve una vista, non un export».
GIORNI_MAX_FINESTRA = 92

# Il discriminante del badge (V3): un evento con fonte `ical` l'ha scritto un calendario esterno ed è **non
# verificato dalla rete**; senza `fonte_id`, o con una fonte della rete, è memoria della rete.
TIPO_ACCESSO_ICAL = "ical"
NOME_FONTE_MANO = "inserito a mano"
NOME_FONTE_CALENDARIO = "calendario della Casa"

# Ordinamento dichiarato: per inizio, e a parità per id — così due richieste identiche danno lo stesso ordine, e la
# pagina non ha un secondo ordinamento da tenere allineato.
SQL_EVENTI = """
SELECT e.id, e.titolo, e.descrizione, e.inizio, e.fine, e.luogo_testo, e.url,
       e.casa_id, e.casa_slug, e.casa_nome,
       e.fonte_nome, e.affidabilita, e.giorni_all_inizio,
       f.autorita AS fonte_autorita, f.tipo_accesso AS fonte_tipo,
       (e.inizio::date - $1::date) AS giorni_dal
  FROM trasi.v_eventi e
  LEFT JOIN trasi.fonte f ON f.nome = e.fonte_nome
 WHERE e.inizio::date >= $1::date
   AND e.inizio::date <= $2::date
   AND ($3::integer IS NULL OR e.casa_id = $3)
 ORDER BY e.inizio, e.id
"""

# Il filtro «leggibile da questa Casa» quando il chiamante indica una Casa diversa dalla propria. `scheda_sel` e
# `evento_sel` concedono la lettura a tutta la rete (`db/002_rls.sql:165,188`), quindi un `casa_id` di un'altra Casa
# **non** è un 403: è una domanda legittima («gli eventi di Bozzano») che la policy già permette. Si rifiuta invece
# una Casa che non esiste: quello è un parametro fuori vocabolario, non una lista vuota.
SQL_CASA_ESISTE = "SELECT id, slug, nome, zona FROM trasi.casa WHERE id = $1"


def finestra_valida(dal: date, al: date) -> None:
    """`422` se l'intervallo è invertito o troppo ampio. Sta in una funzione perché è una regola, non un `if`.

    Il piano dichiara **422** per «finestra invertita» (`T-SHIM-06`), e il caso reale non è teorico: la pagina compone
    le date, e un errore di segno produce una lista vuota che si legge come «non c'è nulla» — cioè un'assenza di
    eventi che nessuno ha verificato.
    """
    if al < dal:
        raise errore(422, "parametri non ammessi — al: la data di fine precede quella di inizio")
    if (al - dal).days > GIORNI_MAX_FINESTRA:
        raise errore(
            422,
            f"parametri non ammessi — finestra troppo ampia: al massimo {GIORNI_MAX_FINESTRA} giorni "
            "(la scheda del luogo chiede una settimana o un mese)",
        )


def voce_evento(riga: Any) -> dict[str, Any]:
    """Una riga di `v_eventi` → l'elemento che l'elenco per data disegna.

    `giorni_all_inizio` è quello della **vista** e non un conto rifatto qui: è il numero che la chat e il cruscotto
    mostrano («fra 3 giorni»), e due formule per lo stesso fatto finirebbero per divergere di un giorno a cavallo
    della mezzanotte. `giorni_dal` è invece relativo all'inizio della finestra chiesta (`dal`): serve all'elenco per
    data, che raggruppa per giorno **dentro** la finestra, non rispetto a oggi.
    """
    inizio = riga["inizio"].astimezone(FUSO)
    fine = riga["fine"].astimezone(FUSO) if riga["fine"] is not None else None

    # La fonte: `v_eventi` dà `fonte_nome` = «inserito dall'operatore» per gli eventi senza `fonte_id`. Il badge
    # distingue i due casi come fa `op_scheda_evento`: `ical` → esterna, tutto il resto → KB. Un evento **senza**
    # fonte non è «provenienza ignota»: l'ha scritto una persona della rete, e lo si dichiara.
    if riga["fonte_tipo"] == TIPO_ACCESSO_ICAL:
        nome = nome_fonte(riga["fonte_autorita"], riga["fonte_nome"] or NOME_FONTE_CALENDARIO)
        badge = badge_esterna(nome, inizio)
    else:
        nome = nome_fonte(riga["fonte_autorita"], riga["fonte_nome"] or NOME_FONTE_MANO)
        badge = badge_kb(nome, inizio.date(), riga["affidabilita"])

    return {
        "id": riga["id"],
        "titolo": riga["titolo"],
        "descrizione": riga["descrizione"],
        "inizio": inizio.isoformat(),
        "fine": fine.isoformat() if fine is not None else None,
        "giorno": inizio.date().isoformat(),
        "ora_inizio": inizio.strftime("%H:%M"),
        "ora_fine": fine.strftime("%H:%M") if fine is not None else None,
        "luogo_testo": riga["luogo_testo"],
        "casa_id": riga["casa_id"],
        "casa_slug": riga["casa_slug"],
        "casa_nome": riga["casa_nome"],
        "giorni_all_inizio": riga["giorni_all_inizio"],
        "giorni_dal": riga["giorni_dal"],
        "url": riga["url"],
        "fonte": nome,
        "fiducia": riga["affidabilita"],
        "badge": badge,
    }


@router.get(
    "/eventi",
    operation_id="op_eventi",
    summary="Eventi in programma di un intervallo di date (per la scheda del luogo: settimana o mese), di tutte le "
    "Case o di una sola. Ogni evento porta il badge di provenienza; l'ora è quella italiana.",
    tags=["op"],
)
async def op_eventi(
    dal: date = Query(description="Primo giorno dell'intervallo (ISO AAAA-MM-GG), incluso."),
    al: date = Query(description="Ultimo giorno dell'intervallo (ISO AAAA-MM-GG), incluso."),
    casa_id: int | None = Query(
        default=None, ge=1, description="Identificativo della Casa; se omesso, gli eventi di tutte le Case."
    ),
    sess: SessioneOperatore = Depends(sessione_corrente),
) -> dict[str, Any]:
    """GET /op/eventi?dal&al&casa_id → `{periodo, casa, eventi}`.

    La finestra è **inclusiva su entrambi gli estremi**: chi chiede «dal 15 al 21» si aspetta l'evento del 21, e un
    `BETWEEN` con il secondo estremo escluso è il modo classico di far sparire l'ultimo giorno del mese.

    Per un **POI non-Casa** la scheda dichiara «Eventi: nessun evento collegato a questo luogo» (§4.2.2): il legame
    `evento ↔ luogo.id` non esiste (`evento.luogo_testo` è testo libero) ed è la domanda aperta §11 Q-04. La pagina
    non passa per questo endpoint in quel caso, e qui non si inventa un legame: si risponde su `casa_id`, che è
    l'unico raggruppamento che il modello dati possiede.
    """
    finestra_valida(dal, al)

    casa: dict[str, Any] | None = None
    if casa_id is not None:
        riga_casa = await sess.fetchrow(SQL_CASA_ESISTE, casa_id)
        if riga_casa is None:
            raise errore(404, "Casa non presente nella memoria della rete")
        casa = {"id": riga_casa["id"], "slug": riga_casa["slug"], "nome": riga_casa["nome"], "zona": riga_casa["zona"]}

    righe = await sess.fetch(SQL_EVENTI, dal, al, casa_id)
    return {
        "periodo": {"dal": dal.isoformat(), "al": al.isoformat(), "giorni": (al - dal).days + 1},
        "casa": casa,
        "eventi": [voce_evento(riga) for riga in righe],
    }


def monta(applicazione: FastAPI) -> None:
    """Monta il router sotto `/op`, **fuori** dal documento OpenAPI (stessa regola di `mappa_op.monta`)."""
    applicazione.include_router(router, prefix="/op", include_in_schema=False)


__all__ = ["GIORNI_MAX_FINESTRA", "finestra_valida", "monta", "op_eventi", "router", "voce_evento"]
