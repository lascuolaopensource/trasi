"""Endpoint di lettura della memoria della rete: `cerca_luogo` ed `eventi_oggi` (B3-SHM-02).

Entrambi leggono solo `trasi.luogo` / `trasi.casa` / `trasi.evento` come ruolo della Casa dell'operatore: la RLS fa
il resto, e una Casa non vede nulla di più di quanto il suo ruolo concede.

Tre scelte che vale la pena dichiarare:

- **`cerca_luogo` risponde 200 con `items: []`**, mai 404. «Nessun luogo in memoria» è un'informazione vera e utile
  (è lo scenario US-02: l'assistente dichiara l'astensione invece di inventare), mentre un 404 direbbe che
  l'*endpoint* non esiste. Il 422 di `q` troppo corta è invece un errore di chi chiama: una ricerca di un carattere
  restituirebbe mezzo database.
- **`eventi_oggi` senza `casa` copre TUTTE le Case della rete** (il calendario è condiviso e la RLS concede a
  ogni ruolo Casa la lettura dell'intera memoria degli eventi). Con `casa` esplicito è solo quella Casa; il
  modello ne scrive di solito il **nome** («San Bao») e non lo slug, quindi un valore che non è uno slug si prova
  a risolvere in Casa, e solo un testo che non è riconoscibile è 404. Una Casa esistente senza eventi è 200 con
  `eventi: []`. Ogni item porta `casa_slug`/`casa_nome`, così la provenienza viaggia con l'evento.
- **`data` è un giorno o l'inizio di un intervallo**: con `al` la risposta copre `data..al` (inclusi), così
  «questo weekend» o «questa settimana» sono una sola chiamata e non una per giorno. Un evento di più giorni
  compare in ogni giornata che attraversa (overlap), non solo nel giorno d'inizio.
"""

from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Query

from .badge import badge_kb, nome_fonte
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

# «Questo weekend», «questa settimana», «questo mese» sono intervalli; oltre ~3 mesi la richiesta non è più una
# consultazione di calendario ma un dump, e riempirebbe il contesto del LLM. Il tetto è sull'ampiezza (al − data),
# non sulla distanza: «gli eventi di dicembre» resta ammesso.
MAX_GIORNI_INTERVALLO = 92

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
#
# `$1` (slug) è facoltativo: NULL = tutte le Case (il calendario è della rete). `$2`/`$3` sono l'intervallo
# `dal..al` (inclusi). `$4` è la parola chiave facoltativa su titolo/descrizione.
#
# Due filtri, perché due cose diverse. Un evento **singolo** entra se la sua giornata cade nell'intervallo
# (`inizio <= al AND COALESCE(fine, inizio) >= dal`: un evento di più giorni compare in ogni giornata che
# attraversa, non solo in quella d'inizio). Un evento **ricorrente** entra se la sua ricorrenza può ancora
# produrre un'occorrenza nell'intervallo (`ricorrenza_fine` NULL = senza termine): le occorrenze si calcolano
# dopo, in `_occorrenze`, perché la regola è un vocabolario di `trasi.evento` (db/025) che il database non
# espande da sé.
SQL_EVENTI = """
SELECT e.id, e.titolo, e.descrizione, e.inizio, e.fine, e.luogo_testo,
       COALESCE(e.url, f.url) AS url,
       COALESCE(e.affidabilita, 2) AS affidabilita,
       f.nome AS fonte_nome, f.autorita AS fonte_autorita,
       (e.uid_ical IS NULL AND e.fonte_id IS NULL) AS inserito_a_mano,
       c.nome AS casa_nome, c.slug AS casa_slug,
       e.costo, e.fascia_eta, e.tag, e.ricorrenza, e.ricorrenza_fine,
       e.prenotazione, e.prenotazione_nota
FROM trasi.evento e
JOIN trasi.casa c ON c.id = e.casa_id
LEFT JOIN trasi.fonte f ON f.id = e.fonte_id
WHERE ($1::text IS NULL OR c.slug = $1)
  AND e.annullato = false
  AND (
        (e.ricorrenza IS NULL
         AND e.inizio::date <= $3
         AND COALESCE(e.fine, e.inizio)::date >= $2)
     OR (e.ricorrenza IS NOT NULL
         AND e.inizio::date <= $3
         AND (e.ricorrenza_fine IS NULL OR e.ricorrenza_fine >= $2))
      )
  AND ($4::text IS NULL
       OR e.titolo ILIKE '%' || $4 || '%'
       OR COALESCE(e.descrizione, '') ILIKE '%' || $4 || '%')
ORDER BY e.inizio
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
        description="Slug o nome della Casa di Quartiere. Se omesso, gli eventi di TUTTE le Case della rete "
        "(il calendario è condiviso); ogni item dichiara la sua Casa in `casa_slug`/`casa_nome`.",
    ),
    data: date | None = Query(
        default=None,
        description="Giorno singolo o inizio dell'intervallo, ISO `AAAA-MM-GG`; se omessa, oggi (Europe/Rome).",
    ),
    al: date | None = Query(
        default=None,
        description="Fine dell'intervallo (inclusa): con `al` la risposta copre `data..al` — «questo weekend» o "
        "«questa settimana» in una sola chiamata. Per un solo giorno, ometterla.",
    ),
    q: str | None = Query(
        default=None,
        description="Parola chiave facoltativa: filtra gli eventi per titolo/descrizione (es. «bambini»).",
    ),
    sess: Sessione = Depends(dipendenza_sessione),
) -> RispostaEventiOggi:
    """Gli eventi del calendario della rete in una data o nell'intervallo `data..al`.

    «Oggi» è calcolato nel fuso italiano: alle 00:30 di Roma gli eventi della sera prima non sono più «oggi».

    Senza `casa` la risposta copre **tutte** le Case della rete (fino al 2026-09-17 prendeva la sola Casa
    dell'operatore, e gli eventi delle altre erano invisibili in chat: una Casa non vedeva il calendario della
    rete). Con `casa` esplicito è quella Casa; il modello ne scrive di solito il **nome** e non lo slug, quindi un
    valore che non è uno slug si prova a risolvere in Casa, e solo un testo che non è riconoscibile è 404. Ogni
    item porta `casa_slug`/`casa_nome`: la provenienza viaggia con l'evento, non si deduce dal campo `casa` (che è
    `null` quando la ricerca è su tutta la rete).
    """
    richiesto = (casa or "").strip() or None
    slug = richiesto
    if slug is not None and await sess.fetchval(SQL_CASA_ESISTE, slug) is None:
        # Il modello riempie `casa` col nome della Casa, non con lo slug (v. `risolvi_slug_casa`): un nome
        # riconoscibile diventa lo slug, un testo che non è una Casa è 404 — mai un ripiego silenzioso su un'altra.
        slug = await risolvi_slug_casa(sess, slug)
        if slug is None:
            raise errore(404, f"casa non trovata: nessuna Casa di Quartiere con «{richiesto}»")

    dal = data or oggi_locale()
    fine_intervallo = al or dal
    if fine_intervallo < dal:
        raise errore(422, "parametri non ammessi — al: deve essere uguale o successiva a data")
    if (fine_intervallo - dal).days > MAX_GIORNI_INTERVALLO:
        raise errore(422, f"parametri non ammessi — intervallo troppo ampio (max {MAX_GIORNI_INTERVALLO} giorni)")

    parola = (q or "").strip() or None
    if parola is not None and len(parola) < MIN_LUNGHEZZA_RICERCA:
        raise errore(422, f"parametri non ammessi — q: almeno {MIN_LUNGHEZZA_RICERCA} caratteri")

    # `data` è un `date`, non una stringa ISO: `$2::date`/`$3::date` fanno dedurre ad asyncpg il tipo del
    # parametro, e una stringa lì è un `DataError` a runtime (verificato: `'str' object has no attribute 'toordinal'`).
    righe = await sess.fetch(SQL_EVENTI, slug, dal, fine_intervallo, parola)

    eventi: list[ItemEvento] = []
    for riga in righe:
        for occ_inizio, occ_fine in _occorrenze(riga, dal, fine_intervallo):
            eventi.append(_item_evento(riga, occ_inizio, occ_fine))
    # Una ripetizione può cadere in un giorno diverso dall'`inizio` memorizzato (che è la prima occorrenza):
    # l'ordine è per data **dell'occorrenza**, non per `inizio`, altrimenti la lista mentirebbe sul calendario.
    eventi.sort(key=lambda e: (e.data, e.ora_inizio or ""))

    return RispostaEventiOggi(casa=slug, data=dal, al=al, eventi=eventi)


def _item_luogo(riga) -> ItemLuogo:
    """Una riga di `trasi.luogo` → `ItemLuogo` del contratto, con il badge già composto (V3)."""
    fonte = nome_fonte(riga["fonte_autorita"], riga["fonte_nome"])
    return ItemLuogo(
        provenienza="kb",
        nome=riga["nome"],
        tipo=riga["tipo"],
        indirizzo=riga["indirizzo"],
        lat=float(riga["lat"]),
        lon=float(riga["lon"]),
        orari_testo=riga["orari_testo"],
        fonte=fonte,
        url=riga["url"],
        data_aggiornamento=riga["data_aggiornamento"],
        fiducia=riga["affidabilita"],
        badge=badge_kb(fonte, riga["data_aggiornamento"], riga["affidabilita"]),
    )


# Il tetto alle occorrenze di un singolo evento ricorrente: l'intervallo è già limitato (`MAX_GIORNI_INTERVALLO`),
# quindi serve solo a fermare un conteggio impazzito, non a limitare l'uso normale.
MAX_OCCORRENZE = 400


def _in_italia(giorno: date, ora: time) -> datetime:
    """`giorno`+`ora` nel fuso italiano. Ricomposta invece di sommata: `+ timedelta(days=7)` su un istante
    consapevole è aritmetica assoluta, e attraverso il cambio d'ora sposterebbe l'evento delle 10:00 alle 11:00."""
    return datetime.combine(giorno, ora, tzinfo=FUSO)


def _giorni_occorrenza(base: date, regola: str, dal: date, al: date, fine_ric: date | None) -> list[date]:
    """I giorni in cui cade la ricorrenza dentro `dal..al`, a partire dal giorno `base` (quello d'inizio).

    Settimanale/bisettimanale avanzano di giorni; mensile/annuale avanzano **sul calendario** (il 31/01 mensile
    resta il 31, o l'ultimo giorno di un mese corto), non di 30/365 giorni, che farebbero scivolare la data.
    """
    giorni: list[date] = []
    if regola in ("settimanale", "bisettimanale"):
        passo = 7 if regola == "settimanale" else 14
        # Si parte da un multiplo vicino a `dal`, non da `base`: un evento settimanale attivo da anni produrrebbe
        # centinaia di passi scartati prima di arrivare all'intervallo.
        n = max(0, (dal - base).days // passo - 1)
        while n < MAX_OCCORRENZE:
            giorno = base + timedelta(days=passo * n)
            if giorno > al or (fine_ric is not None and giorno > fine_ric):
                break
            if giorno >= dal:
                giorni.append(giorno)
            n += 1
        return giorni

    passo_mesi = 1 if regola == "mensile" else 12
    n = max(0, ((dal.year - base.year) * 12 + (dal.month - base.month)) // passo_mesi - 1)
    while n < MAX_OCCORRENZE:
        totale = (base.year * 12 + (base.month - 1)) + passo_mesi * n
        anno, mese = totale // 12, totale % 12 + 1
        giorno = date(anno, mese, min(base.day, monthrange(anno, mese)[1]))
        if giorno > al or (fine_ric is not None and giorno > fine_ric):
            break
        if giorno >= dal:
            giorni.append(giorno)
        n += 1
    return giorni


def _occorrenze(riga, dal: date, al: date) -> list[tuple[datetime, datetime | None]]:
    """Quando cade un evento dentro `dal..al`: l'intervallo memorizzato se è singolo, le occorrenze se ricorre.

    La durata (`fine - inizio`) resta la stessa a ogni ripetizione, così una festa di due giorni resta di due
    giorni anche alla terza occorrenza. Per un evento **non** ricorrente l'intervallo è quello memorizzato: la
    query ha già verificato che cade nei giorni chiesti.
    """
    inizio = riga["inizio"]
    fine = riga["fine"]
    regola = riga["ricorrenza"]
    if not regola:
        return [(inizio, fine)]
    durata = (fine - inizio) if fine else None
    riferimento = inizio.astimezone(FUSO)
    return [
        (
            _in_italia(giorno, riferimento.time()),
            _in_italia(giorno, riferimento.time()) + durata if durata else None,
        )
        for giorno in _giorni_occorrenza(riferimento.date(), regola, dal, al, riga["ricorrenza_fine"])
    ]


def _item_evento(riga, inizio: datetime, fine: datetime | None) -> ItemEvento:
    """Una occorrenza di un evento → `ItemEvento` del contratto, con il badge già composto (V3).

    `inizio`/`fine` sono l'occorrenza (per un ricorrente, quella calcolata). Le ore si convertono
    **esplicitamente** nel fuso italiano: `asyncpg` restituisce i `timestamptz` in UTC, e uno `strftime('%H:%M')`
    diretto mostrerebbe l'evento delle 18:30 come «16:30» (verificato). Il badge porta la data locale
    dell'occorrenza, che è il giorno in cui l'operatore la vede in calendario.

    I campi di db/025 e db/030 (costo, fascia d'età, tag, ricorrenza, prenotazione) viaggiano con l'item: sono le
    risposte a «è gratuito?», «serve prenotare?», «per chi è?», e senza di essi l'assistente le cerca a vuoto
    invece di rispondere.
    """
    fonte = (
        "inserito dall'operatore"
        if riga["inserito_a_mano"]
        else nome_fonte(riga["fonte_autorita"], riga["fonte_nome"])
    )
    locale = inizio.astimezone(FUSO)
    chiusura = fine.astimezone(FUSO) if fine else None
    costo = float(riga["costo"]) if riga["costo"] is not None else None
    return ItemEvento(
        provenienza="kb",
        titolo=riga["titolo"],
        dove=riga["luogo_testo"] or riga["casa_nome"],
        casa_slug=riga["casa_slug"],
        casa_nome=riga["casa_nome"],
        data=locale.date(),
        ora_inizio=locale.strftime("%H:%M"),
        ora_fine=chiusura.strftime("%H:%M") if chiusura else None,
        orari_nota=None,
        descrizione=riga["descrizione"],
        costo=costo,
        gratuito=True if costo == 0 else None,
        fascia_eta=riga["fascia_eta"],
        tag=list(riga["tag"]) if riga["tag"] else None,
        ricorrenza=riga["ricorrenza"],
        prenotazione=riga["prenotazione"],
        prenotazione_nota=riga["prenotazione_nota"],
        fonte=fonte,
        url=riga["url"],
        fiducia=riga["affidabilita"],
        badge=badge_kb(fonte, locale.date(), riga["affidabilita"]),
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


def _item_luogo(riga) -> ItemLuogo:
    """Una riga di `trasi.luogo` → `ItemLuogo` del contratto, con il badge già composto (V3)."""
    fonte = nome_fonte(riga["fonte_autorita"], riga["fonte_nome"])
    return ItemLuogo(
        provenienza="kb",
        nome=riga["nome"],
        tipo=riga["tipo"],
        indirizzo=riga["indirizzo"],
        lat=float(riga["lat"]),
        lon=float(riga["lon"]),
        orari_testo=riga["orari_testo"],
        fonte=fonte,
        url=riga["url"],
        data_aggiornamento=riga["data_aggiornamento"],
        fiducia=riga["affidabilita"],
        badge=badge_kb(fonte, riga["data_aggiornamento"], riga["affidabilita"]),
    )


__all__ = [
    "MIN_LUNGHEZZA_RICERCA",
    "SQL_CERCA_LUOGO",
    "SQL_EVENTI",
    "router",
]
