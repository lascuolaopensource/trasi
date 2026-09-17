"""Endpoint di lettura della memoria della rete: `cerca_luogo` ed `eventi_oggi` (B3-SHM-02).

Entrambi leggono solo `trasi.luogo` / `trasi.casa` / `trasi.evento` come ruolo della Casa dell'operatore: la RLS fa
il resto, e una Casa non vede nulla di più di quanto il suo ruolo concede.

Due scelte che vale la pena dichiarare:

- **`cerca_luogo` risponde 200 con `items: []`**, mai 404. «Nessun luogo in memoria» è un'informazione vera e utile
  (è lo scenario US-02: l'assistente dichiara l'astensione invece di inventare), mentre un 404 direbbe che
  l'*endpoint* non esiste. Il 422 di `q` troppo corta è invece un errore di chi chiama: una ricerca di un carattere
  restituirebbe mezzo database.
- **`eventi_oggi` risponde 404 se lo slug non esiste**: la Casa è un vocabolario chiuso, e una Casa inesistente è una
  richiesta sbagliata, non una risposta vuota. Se la Casa esiste ma non ha eventi, la risposta è 200 con `eventi: []`.
"""

from __future__ import annotations

import re
from datetime import date

from fastapi import APIRouter, Depends, Query

from .badge import badge_esterna, badge_kb, nome_fonte
from .contratto import meta
from .db import Sessione, dipendenza_sessione, parametri, risolvi_slug_casa, slug_casa_da_identita
from .errori import errore
from .schemi import (
    ItemEvento,
    ItemLuogo,
    ItemStatisticheAmbito,
    RispostaCercaLuogo,
    RispostaEventiOggi,
    RispostaStatistiche,
    WhoAmI,
)
from .settings import get_settings
from .vicinanza import CHIAVI_PARAMETRI, FUSO, oggi_locale

router = APIRouter()

# Sotto questa lunghezza la ricerca non è una ricerca: `q` di un carattere restituirebbe l'intero vocabolario dei
# luoghi, che non aiuta l'operatore e spreca il tetto di contesto del LLM.
MIN_LUNGHEZZA_RICERCA = 2

# La ricerca è sulla memoria della rete, che è piccola (22 luoghi nel seed): un tetto dichiarato evita che una
# richiesta generica restituisca tutto e tenga fuori il resto della risposta del LLM.
TETTO_CERCA_LUOGO = 20

# Ricerca su nome, descrizione e indirizzo. `ILIKE` e non full-text: la memoria della rete ha 22 luoghi nel seed
# (ordine di grandezza di una manciata di migliaia a regime), e un indice GIN non guadagnerebbe nulla su questa
# cardinalità mentre aggiungerebbe un indice da mantenere.
#
# Il filtro `tipo` è condizionato alla presenza del tipo **in memoria**: il contratto dice che «un valore fuori
# vocabolario non restringe la ricerca», e la memoria è l'unica autorità sul proprio vocabolario (il shim non lo
# duplica). Conseguenza dichiarata: un tipo che è nel vocabolario del database ma non ha righe in memoria (oggi
# `fermata`) non restringe nemmeno lui. È il verso giusto dell'errore: il contratto preferisce restituire troppo
# poco filtrato che rispondere `items: []` a un tipo scritto male dall'assistente.
SQL_CERCA_LUOGO = """
SELECT l.id, l.nome, l.tipo, COALESCE(l.indirizzo, '') AS indirizzo, l.descrizione,
       l.orari,
       round(st_y(l.geom::geometry)::numeric, 5) AS lat,
       round(st_x(l.geom::geometry)::numeric, 5) AS lon,
       trasi.orari_testo(l.orari) AS orari_testo,
       COALESCE(l.url, f.url) AS url, l.data_aggiornamento, l.affidabilita,
       f.nome AS fonte_nome, f.autorita AS fonte_autorita,
       c.slug AS casa_slug, c.zona AS casa_zona
FROM trasi.luogo l
LEFT JOIN trasi.fonte f ON f.id = l.fonte_id
LEFT JOIN trasi.casa c ON c.id = l.casa_id
WHERE l.chiuso_il IS NULL
  AND (l.nome ILIKE $1 OR COALESCE(l.descrizione, '') ILIKE $1 OR COALESCE(l.indirizzo, '') ILIKE $1)
  AND ($2::text IS NULL OR l.tipo = $2
       OR NOT EXISTS (SELECT 1 FROM trasi.luogo v WHERE v.tipo = $2))
  AND ($3::text IS NULL OR COALESCE(c.zona, '') ILIKE $3 OR COALESCE(l.indirizzo, '') ILIKE $3)
ORDER BY l.affidabilita DESC, l.nome
LIMIT $4
"""

SQL_CASA_ESISTE = "SELECT id FROM trasi.casa WHERE slug = $1"

# Il giorno si ritaglia nel fuso del database (`TimeZone` = Europe/Rome dal compose), non in UTC: l'evento delle
# 21:30 di oggi appartiene a oggi, e confrontare un `timestamptz` con una data in UTC lo sposterebbe a domani.
SQL_EVENTI = """
SELECT e.id, e.titolo, o.inizio, o.fine, e.luogo_testo, e.ricorrenza, o.n_occorrenza,
       COALESCE(e.url, f.url) AS url,
       COALESCE(e.affidabilita, 2) AS affidabilita,
       f.nome AS fonte_nome, f.autorita AS fonte_autorita, f.tipo_accesso AS fonte_tipo,
       (e.uid_ical IS NULL AND e.fonte_id IS NULL) AS inserito_a_mano,
       c.nome AS casa_nome, c.slug AS casa_slug
FROM trasi.evento e
JOIN trasi.casa c ON c.id = e.casa_id
LEFT JOIN trasi.fonte f ON f.id = e.fonte_id
CROSS JOIN LATERAL trasi.evento_occorgenze(e, $2, $3) o
WHERE c.slug = $1
  AND e.annullato = false
  AND o.inizio::date >= $2
  AND o.inizio::date <= $3
ORDER BY o.inizio, e.id
"""


@router.get(
    "/_whoami",
    summary="Identità dell'operatore risolta dallo shim (solo con SHIM_DEBUG=1).",
    include_in_schema=False,
    response_model=WhoAmI,
)
async def whoami(sess: Sessione = Depends(dipendenza_sessione)) -> WhoAmI:
    """Diagnostica: l'identità risolta e i parametri [P] in vigore.

    Fuori dal contratto congelato e spenta per default: esiste perché i test e la diagnosi dentro il container
    possano verificare **quale** ruolo è stato assunto senza leggere i log del database. Con il debug spento la route
    risponde 404 — non 403 — perché non deve nemmeno rivelare di esistere.
    """
    if get_settings().shim_debug != "1":
        raise errore(404, "non trovato")
    return WhoAmI(
        email=sess.email,
        ruolo=sess.ruolo,
        casa_id=sess.casa_id,
        parametri=await parametri(sess, CHIAVI_PARAMETRI),
    )


@router.get("/cerca_luogo", response_model=RispostaCercaLuogo, **meta("cerca_luogo"))
async def cerca_luogo(
    q: str = Query(description="Testo libero della ricerca, in italiano (obbligatorio)."),
    tipo: str | None = Query(default=None, description="Tipo di luogo, facoltativo (vocabolario `luogo.tipo`)."),
    quartiere: str | None = Query(default=None, description="Quartiere o zona, facoltativo."),
    sess: Sessione = Depends(dipendenza_sessione),
) -> RispostaCercaLuogo:
    """Cerca nella memoria della rete per nome, descrizione e indirizzo.

    `tipo` fuori vocabolario **non** è un errore qui: il contratto dice che «un valore fuori vocabolario non
    restringe la ricerca». Il 422 dei tipi chiusi è di `vicino_a`, dove il tipo determina i tag OpenStreetMap da
    interrogare e un valore ignoto non sarebbe traducibile in una query.
    """
    testo = (q or "").strip()
    if len(testo) < MIN_LUNGHEZZA_RICERCA:
        raise errore(
            422, f"parametri non ammessi — q: servono almeno {MIN_LUNGHEZZA_RICERCA} caratteri per cercare"
        )

    righe = await sess.fetch(
        SQL_CERCA_LUOGO,
        f"%{testo}%",
        (tipo or "").strip() or None,
        f"%{quartiere.strip()}%" if quartiere and quartiere.strip() else None,
        TETTO_CERCA_LUOGO,
    )

    return RispostaCercaLuogo(items=[_item_luogo(riga) for riga in righe])

@router.get("/eventi_oggi", response_model=RispostaEventiOggi, **meta("eventi_oggi"))
async def eventi_oggi(
    casa: str | None = Query(
        default=None,
        description="Slug della Casa di Quartiere. Se omesso si usa la Casa dell'operatore autenticato.",
    ),
    data: date | None = Query(default=None, description="Data ISO `AAAA-MM-GG`; se omessa, oggi."),
    data_fine: date | None = Query(
        default=None,
        description="Ultima data dell'intervallo, inclusa (ISO `AAAA-MM-GG`). Se omessa, la ricerca vale "
        "per il solo giorno di `data`: «questa settimana» è `data` di lunedì e `data_fine` di domenica.",
    ),
    sess: Sessione = Depends(dipendenza_sessione),
) -> RispostaEventiOggi:
    """Gli eventi di una Casa in una data (oggi se non indicata) o in un intervallo di date.

    «Oggi» è calcolato nel fuso italiano: alle 00:30 di Roma gli eventi della sera prima non sono più «oggi», ed è
    il comportamento che l'operatore allo sportello si aspetta.

    `data_fine` (17/09/2026, US-1.2): senza, l'endpoint vale **un giorno** come sempre — il contratto con chi
    lo chiama non cambia. Con `data_fine`, la finestra è inclusiva su entrambi gli estremi (`data` … `data_fine`),
    e «questa settimana» o «questo mese» diventano **una** chiamata invece di sette. `data_fine` prima di `data`
    è un `422`, non un intervallo invertito.

    La Casa, se non indicata, è quella dell'operatore: l'assistente non deve conoscerla (v. `slug_casa_da_identita`).
    """
    slug = (casa or "").strip() or await slug_casa_da_identita(sess)
    if not slug:
        raise errore(422, "parametri non ammessi — casa: obbligatoria per un ruolo senza Casa (es. rete)")
    # Il modello scrive il nome («San Bao») più spesso dello slug: si prova a riconoscerlo. Solo se non è una
    # Casa riconoscibile si ripiega su quella dell'operatore (v. `routes_geo`), com'era prima.
    if await sess.fetchval(SQL_CASA_ESISTE, slug) is None:
        slug = await risolvi_slug_casa(sess, slug) or await slug_casa_da_identita(sess) or slug

    riferimento = data or oggi_locale()
    fine = data_fine or riferimento
    if fine < riferimento:
        raise errore(422, "parametri non ammessi — data_fine: la data di fine precede quella di inizio")
    # I parametri sono `date`, non stringhe ISO: `$2::date` fa dedurre ad asyncpg il tipo del parametro, e una
    # stringa lì è un `DataError` a runtime (verificato: `'str' object has no attribute 'toordinal'`).
    righe = await sess.fetch(SQL_EVENTI, slug, riferimento, fine)

    if not righe and await sess.fetchval(SQL_CASA_ESISTE, slug) is None:
        raise errore(404, f"casa non trovata: nessuna Casa di Quartiere con slug «{slug}»")

    return RispostaEventiOggi(
        casa=slug, data=riferimento, eventi=[_item_evento(riga) for riga in righe], data_fine=fine
    )


def _item_luogo(riga) -> ItemLuogo:
    """Una riga di `trasi.luogo` → `ItemLuogo` del contratto, con il badge già composto (V3) e l'`id` per il biglietto."""
    fonte = nome_fonte(riga["fonte_autorita"], riga["fonte_nome"])
    return ItemLuogo(
        id=riga["id"],
        provenienza="kb",
        nome=riga["nome"],
        tipo=riga["tipo"],
        indirizzo=riga["indirizzo"],
        lat=float(riga["lat"]) if riga["lat"] is not None else None,
        lon=float(riga["lon"]) if riga["lon"] is not None else None,
        orari_testo=riga["orari_testo"],
        fonte=fonte,
        url=riga["url"],
        data_aggiornamento=riga["data_aggiornamento"],
        fiducia=riga["affidabilita"],
        badge=badge_kb(fonte, riga["data_aggiornamento"], riga["affidabilita"]),
    )


def _item_evento(riga) -> ItemEvento:
    """Una riga di `trasi.evento` → `ItemEvento` del contratto.

    Le ore si convertono **esplicitamente** nel fuso italiano: `asyncpg` restituisce i `timestamptz` in UTC, e un
    `strftime('%H:%M')` diretto mostrerebbe l'evento delle 18:30 come «16:30» (verificato). Il badge porta la data
    locale dell'evento, che è il giorno in cui l'operatore lo vede in calendario.
    """
    # La provenienza (V3, P0.2): un evento arrivato da un **calendario esterno** (`ical`) non è memoria
    # verificata della rete e va detto — `op_eventi` lo faceva già, `eventi_oggi` no, e la chat mostrava
    # `[KB · …]` su eventi che nessuno della rete aveva confermato. Stesso criterio di `eventi_op.voce_evento`.
    inizio = riga["inizio"].astimezone(FUSO)
    fine = riga["fine"].astimezone(FUSO) if riga["fine"] else None
    if riga["fonte_tipo"] == "ical":
        provenienza = "esterna"
        fonte = nome_fonte(riga["fonte_autorita"], riga["fonte_nome"] or "calendario della Casa")
        badge = badge_esterna(fonte, inizio)
    else:
        provenienza = "kb"
        fonte = (
            "inserito dall'operatore"
            if riga["inserito_a_mano"]
            else nome_fonte(riga["fonte_autorita"], riga["fonte_nome"])
        )
        badge = badge_kb(fonte, inizio.date(), riga["affidabilita"])
    return ItemEvento(
        provenienza=provenienza,
        titolo=riga["titolo"],
        dove=riga["luogo_testo"] or riga["casa_nome"],
        data=inizio.date(),
        ora_inizio=inizio.strftime("%H:%M"),
        ora_fine=fine.strftime("%H:%M") if fine else None,
        orari_nota=None,
        fonte=fonte,
        url=riga["url"],
        fiducia=riga["affidabilita"],
        badge=badge,
        ricorrenza=riga["ricorrenza"],
        occorrenza=riga["n_occorrenza"],
    )

SQL_STATISTICHE = """
SELECT casa_slug, mese, categoria, esito, n, n_label
  FROM trasi.v_report_mensile
 WHERE casa_slug = $1
   AND mese = $2
   AND (trasi.casa_corrente() IS NULL OR casa_id = trasi.casa_corrente())
 ORDER BY categoria, esito
"""


SQL_NOME_CASA = "SELECT nome FROM trasi.casa WHERE slug = $1"

# Le etichette leggibili degli esiti, per il `testo`: la vista dà il vocabolario del database
# (`risolta`, `inviata_altrove`), l'operatore parla italiano.
ETICHETTA_ESITO = {
    "risolta": "richieste risolte",
    "inviata_altrove": "inviate ad altro servizio",
    "non_trovata": "senza destinazione trovata",
    "rinviata": "rinviate",
}


@router.get("/statistiche", response_model=RispostaStatistiche, **meta("statistiche"))
async def statistiche(
    casa: str | None = Query(
        default=None,
        description="Slug della Casa di Quartiere. Se omesso si usa la Casa dell'operatore autenticato.",
    ),
    mese: str | None = Query(default=None, description="Mese `AAAA-MM`; se omesso, quello corrente."),
    sess: Sessione = Depends(dipendenza_sessione),
) -> RispostaStatistiche:
    """Le statistiche mensili delle richieste della Casa, dalla vista `v_report_mensile`.

    I conteggi arrivano **già mascherati** dalla vista (`k_anon`): lo shim non vede mai il numero grezzo, quindi non
    può rivelarlo nemmeno per errore — la stessa proprietà che protegge Metabase protegge la chat. `n` è `null` sotto
    la soglia di k-anonimato e `n_label` è la forma da mostrare («<5», «—» a zero): la chat riporta `n_label`, e il
    `testo` composto qui usa solo quello.

    La vista è `security_invoker=false`: il filtro «solo la propria Casa» sta nella query con `trasi.casa_corrente()`,
    come per `oggi` — la decisione resta del database.
    """
    slug = (casa or "").strip() or await slug_casa_da_identita(sess)
    if not slug:
        raise errore(422, "parametri non ammessi — casa: obbligatoria per un ruolo senza Casa (es. rete)")

    # Un mese fuori forma non arriva al database: la vista accetterebbe anche `'2026-13-01'::date`, e un errore di
    # battitura («2026-02-») diventerebbe un 500 invece di un 422 di chi chiama. La validazione qui è la dichiarazione
    # del formato del contratto, non una seconda regola.
    if mese is not None and not re.fullmatch(r"\d{4}-\d{2}", mese.strip()):
        raise errore(422, "parametri non ammessi — mese: attendesi il formato AAAA-MM")

    riferimento = (mese or "").strip() or None
    if riferimento is None:
        # Il mese corrente si calcola nel fuso italiano, come `oggi_locale` fa per il giorno: un mese chiesto alle
        # 00:30 di Roma il primo del mese non deve rispondere con il mese di UTC.
        riferimento = oggi_locale().strftime("%Y-%m")

    # Uno slug inesistente non è un errore se l'operatore ha una Casa propria (v. `eventi_oggi`): il modello tende a
    # riempire `casa` con il nome invece dello slug, e il 404 dichiarerebbe un guasto che non esiste.
    if await sess.fetchval(SQL_CASA_ESISTE, slug) is None:
        slug_identita = await slug_casa_da_identita(sess)
        if slug_identita:
            slug = slug_identita

    # Prima di interrogare il report si verifica che il mese richiesto sia una data: `AAAA-13` passerebbe il pattern,
    # e `'2026-13-01'::date` è un `DataError` a runtime. La conversione fallita è un 422, non un 500.
    try:
        primo_mese = date.fromisoformat(riferimento + "-01")
    except ValueError:
        raise errore(422, "parametri non ammessi — mese: non è un mese valido (es. 2026-09)") from None

    righe = await sess.fetch(SQL_STATISTICHE, slug, primo_mese)

    # Il 404 copre solo la Casa inesistente (vocabolario chiuso, come `eventi_oggi`): un mese senza richieste è 200
    # con `ambiti: []`, che all'assistente dice «mese senza attività» e non «endpoint sbagliato».
    if not righe and await sess.fetchval(SQL_CASA_ESISTE, slug) is None:
        raise errore(404, f"casa non trovata: nessuna Casa di Quartiere con slug «{slug}»")

    # Il `testo` è composto qui e una volta sola: le righe arrivano già mascherate, quindi anche il riepilogo può
    # dire solo ciò che la rete dichiara — nessun numero ricostruito in Python.
    nome = await sess.fetchval(SQL_NOME_CASA, slug)
    nome = nome or slug
    if not righe:
        testo = f"{nome} · {riferimento}: nessuna richiesta registrata"
    else:
        pezzi = [
            f"{r['n_label']} {ETICHETTA_ESITO.get(r['esito'], r['esito'])}"
            + (f" in {r['categoria'].replace('_', ' ')}" if len(righe) > 1 else "")
            for r in righe
        ]
        testo = f"{nome} · {riferimento}: " + ", ".join(pezzi)

    return RispostaStatistiche(
        casa=slug,
        mese=riferimento,
        ambiti=[
            ItemStatisticheAmbito(
                categoria=r["categoria"], esito=r["esito"], n=r["n"], n_label=r["n_label"]
            )
            for r in righe
        ],
        testo=testo,
    )


__all__ = [
    "MIN_LUNGHEZZA_RICERCA",
    "SQL_CERCA_LUOGO",
    "SQL_EVENTI",
    "router",
]
