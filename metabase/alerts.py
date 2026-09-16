#!/usr/bin/env python3
"""Trasi — B5 · gli alert per Casa (F6) su Metabase.

Quattro tipi di avviso (§8 F6), uno per Casa: **scaduti**, **in scadenza**, **senza risposta**,
**proposte in attesa**. La configurazione è generata dall'API, non cliccata: `[S2]`/piano lo
prescrive perché le subscription con filtri personalizzati sono una funzione a pagamento, mentre una
*question per Casa* generata via API fa la stessa cosa con la licenza libera.

## Una sola email per tipo di avviso

`flussi/alert.py` (blocco B4) manda già due email: *proposte in attesa oltre 7 giorni* e *coerenza
delle fonti*. Quei due avvisi **restano suoi**. I quattro di B5 non devono sommarsi a lui, altrimenti
il gestore di una Casa riceve due email per lo stesso fatto — il modo più efficace per fargli
ignorare entrambe.

La partizione, concordata con il worker dei flussi, è quindi:

| Avviso | Chi manda l'email | Stato in Metabase |
|---|---|---|
| scaduti | **Metabase** | attivo |
| in scadenza | **Metabase** | attivo |
| senza risposta | **Metabase** | attivo |
| proposte in attesa | `flussi/alert.py` | **configurato, non attivo** |
| coerenza fonti | `flussi/alert.py` | non presente qui |

Le 10 notification «proposte in attesa» esistono, hanno il destinatario giusto e il testo giusto, e
sono **spente**: accenderle è un `--accendi-proposte`, cioè l'interruttore con cui si sposta la
proprietà di quell'email da `alert.py` a Metabase, in un verso o nell'altro, senza riscrivere niente.
Un avviso configurato e spento è una decisione leggibile; un avviso assente sembrerebbe una
dimenticanza, e due email identiche sarebbero un difetto.

## k-anonimato e V6

I quattro avvisi contano opportunità, schede e proposte — **non** dati di sportello — quindi non
attraversano la soglia di k-anonimato: le card che li alimentano non hanno una colonna `n_label` da
usare. Restano comunque dentro il perimetro: le card sono `WHERE casa_slug = …` su viste già
filtrate, e l'avviso non porta mai il contenuto di una richiesta né un nome di persona.

Ogni testo mostra i quattro campi V6 (*osservato / evidenza / cosa si potrebbe fare / chi decide*) e
nessun verbo imperativo. `flussi/comune.py::verifica_v6` è la stessa funzione che il blocco B4 usa
sui propri template: è importata, non reimplementata, perché una regola di linguaggio con due
implementazioni è una regola che prima o poi diverge.

## Idempotenza

Rieseguire non duplica: ogni notification è riconosciuta dalla card che serve (`payload.card_id`),
e la card dal suo nome. È la stessa idempotenza «per nome» di `db/apply.sh` e di `metabase/dashboard.py`.

Uso:
    metabase/alerts.py                    # crea o riconcilia le 40 notification
    metabase/alerts.py --verifica         # controlla lo stato, non scrive
    metabase/alerts.py --accendi-proposte # sposta a Metabase l'email «proposte in attesa»
    metabase/alerts.py --spegni-proposte  # la riporta a flussi/alert.py (default)
    metabase/alerts.py --invia <id>       # invia una notification adesso (per provare il recapito)

Credenziali: `metabase/.secrets/creds.env` (mode 600, mai versionato, mai stampato).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RADICE / "flussi"))

from comune import verifica_v6  # noqa: E402  — la stessa verifica V6 del blocco B4
from dashboard import Errore, Mb, credenziali, trova_per_nome  # noqa: E402

#: Le Case sono dati, non una lista nel codice: si leggono dalla vista che le espone.
VISTA_CASE = "trasi.v_mappa_case"
#: Il recapito per Casa. La catena (`email_digest` → identità gestore → AT) vive dentro la vista,
#: scritta una volta dal blocco B4: qui non si replica la convenzione `gestore.<slug>@`.
VISTA_RECAPITI = "trasi.v_flusso_recapiti"

#: Ora dell'invio. 07:30 come in §8 (il job notturno finisce alle 06:00).
#: Formato Quartz: `secondi minuti ore giorno-mese mese giorno-settimana`.
CRON = "0 30 7 * * ?"


class Tipo:
    """Un tipo di avviso F6: nome, card che lo serve, oggetto e testo dell'email."""

    def __init__(self, chiave: str, titolo: str, sql: str, oggetto: str,
                 campi: dict[str, str], attivo: bool) -> None:
        self.chiave = chiave
        self.titolo = titolo
        self.sql = sql.strip()
        self.oggetto = oggetto
        self.campi = campi
        self.attivo = attivo

    @property
    def nome_card(self) -> str:
        """Il nome della card-avviso, con il segnaposto della Casa."""
        return f"Alert · {{casa}} · {self.titolo}"


#: I quattro tipi F6. I testi dei campi V6 sono **per tipo**, non per Casa: il destinatario cambia,
#: il significato no. La Casa entra nell'oggetto e nel riferimento all'evidenza.
TIPI: list[Tipo] = [
    Tipo(
        "scaduti", "scaduti",
        """
        SELECT titolo AS "Opportunità", categoria AS "Categoria",
               scadenza AS "Scaduta il", giorni_da_scadenza AS "Giorni trascorsi"
          FROM trasi.v_scaduti
         WHERE casa_slug = '{casa}'
         ORDER BY giorni_da_scadenza DESC
        """,
        "Trasi · {casa_nome}: opportunità scadute",
        {
            "cosa_osservato": (
                "Nelle opportunità di {casa_nome} ci sono voci con una data di scadenza passata: "
                "restano visibili nella rete con la loro età."
            ),
            "evidenza": (
                "Vista trasi.v_scaduti, filtrata su casa_slug='{casa}'. La stessa vista alimenta la "
                "dashboard «Trasi · Casa» e il report della rete."
            ),
            "cosa_si_potrebbe_fare": (
                "Un'opportunità scaduta si può lasciare dov'è (resta leggibile come memoria di cosa "
                "è stato proposto) oppure sostituirla con la nuova edizione, se esiste. La "
                "dashboard «Trasi · Casa» mostra la stessa lista, con la fonte accanto."
            ),
            "chi_decide": (
                "Le opportunità della Casa e la loro scadenza sono in mano al gestore della Casa; "
                "quelle sul territorio all'AT."
            ),
        },
        True,
    ),
    Tipo(
        "in_scadenza", "in scadenza",
        """
        SELECT voce AS "Tipo", titolo AS "Voce", scadenza AS "Scade il",
               giorni_rimanenti AS "Giorni rimanenti", fonte_nome AS "Fonte"
          FROM trasi.v_in_scadenza
         WHERE casa_slug = '{casa}'
         ORDER BY giorni_rimanenti
        """,
        "Trasi · {casa_nome}: voci in scadenza",
        {
            "cosa_osservato": (
                "Voci di {casa_nome} con una scadenza vicina, entro la finestra di preavviso "
                "configurata nella rete."
            ),
            "evidenza": (
                "Vista trasi.v_in_scadenza, filtrata su casa_slug='{casa}': opportunità e schede "
                "che scadono entro il preavviso."
            ),
            "cosa_si_potrebbe_fare": (
                "Una voce in scadenza si può rinnovare aggiornando la data, oppure lasciarla "
                "scadere: in entrambi i casi il numero dei giorni rimanenti è nel messaggio, così la "
                "decisione non dipende dal ricordarsi la data."
            ),
            "chi_decide": (
                "Le scadenze della Casa le governa il gestore; quelle di territorio e Comune l'AT, "
                "che è anche chi conferma i dati provvisori."
            ),
        },
        True,
    ),
    Tipo(
        "senza_risposta", "senza risposta",
        """
        SELECT categoria AS "Categoria", count(*) AS "Colloqui",
               max(giorni_da_registrazione) AS "Più vecchio (giorni)"
          FROM trasi.v_senza_risposta
         WHERE casa_slug = '{casa}'
         GROUP BY categoria
         ORDER BY "Colloqui" DESC
        """,
        "Trasi · {casa_nome}: colloqui senza risposta",
        {
            "cosa_osservato": (
                "A {casa_nome} ci sono colloqui chiusi senza che una risposta sia stata trovata, "
                "raggruppati per categoria. Il numero è per categoria, mai per persona."
            ),
            "evidenza": (
                "Vista trasi.v_senza_risposta, filtrata su casa_slug='{casa}': solo categoria, data "
                "e Casa — la vista non espone alcun campo del cittadino."
            ),
            "cosa_si_potrebbe_fare": (
                "Una categoria che resta senza risposta segnala un servizio che manca o che non è "
                "in memoria: si può cercarlo e proporne l'inserimento, oppure annotarlo nel "
                "confronto con l'AT."
            ),
            "chi_decide": (
                "Le lacune dell'offerta di una Casa sono materia del gestore e dell'AT insieme; "
                "l'inserimento di un nuovo servizio in memoria lo approva l'AT."
            ),
        },
        True,
    ),
    Tipo(
        "proposte_attesa", "proposte in attesa",
        """
        SELECT tipo AS "Tipo", entita AS "Entità", origine AS "Origine",
               giorni_in_attesa AS "In attesa da (giorni)", approvatore_ruolo AS "Chi decide",
               motivazione AS "Motivazione"
          FROM trasi.v_proposte_aperte
         WHERE casa_slug = '{casa}'
         ORDER BY giorni_in_attesa DESC
        """,
        "Trasi · {casa_nome}: proposte in attesa",
        {
            "cosa_osservato": (
                "La coda di {casa_nome} ha proposte in attesa di una decisione. Il tempo di attesa "
                "di ciascuna è nell'elenco."
            ),
            "evidenza": (
                "Vista trasi.v_proposte_aperte, filtrata su casa_slug='{casa}': la stessa coda della "
                "vista «Da approvare», senza il nome di chi ha proposto."
            ),
            "cosa_si_potrebbe_fare": (
                "Una proposta si può approvare o rifiutare dalla coda, leggendo il diff di ciò che "
                "cambia. Una proposta che scade non si perde: resta leggibile, e una proposta nuova "
                "la sostituisce."
            ),
            "chi_decide": (
                "Le proposte della Casa le decide il gestore; quelle su territorio e Comune l'AT. "
                "Chi ha proposto non può approvare la propria proposta."
            ),
        },
        # Spenta: l'email di questo avviso la manda `flussi/alert.py` (B4). Vedi il modulo.
        False,
    ),
]


# --------------------------------------------------------------------------- query di lettura


def leggi(mb: Mb, db_id: int, sql: str) -> list[list]:
    """Esegue una lettura sulla connessione «Trasi» (ruolo `metabase_ro`, sola lettura)."""
    r = mb.post("/api/dataset", {"database": db_id, "type": "native",
                                 "native": {"query": sql, "template-tags": {}}})
    if not r or r.get("status") != "completed":
        raise Errore(f"query fallita: {json.dumps(r)[:300] if r else 'nessuna risposta'}")
    return r["data"]["rows"]


def corpo_email(tipo: Tipo, casa_nome: str, casa_slug: str) -> str:
    """Il testo dell'email: i quattro campi V6, poi il riferimento alla card.

    Il messaggio **non contiene i dati**: contiene l'osservazione, l'evidenza, la possibilità e chi
    decide, e rimanda alla card per l'elenco. È la forma che l'architettura §2.2 prescrive, e per una
    buona ragione: un'email con un elenco di righe viene inoltrata e poi citata fuori contesto, mentre
    un'email che dice *dove guardare* resta vera anche quando i dati cambiano.
    """
    c = tipo.campi
    return "\n".join([
        "Trasi — avviso automatico della rete delle Case di Quartiere",
        "",
        f"Cosa è stato osservato: {c['cosa_osservato'].format(casa_nome=casa_nome, casa=casa_slug)}",
        f"Su quale evidenza: {c['evidenza'].format(casa_nome=casa_nome, casa=casa_slug)}",
        "Cosa si potrebbe fare: "
        f"{c['cosa_si_potrebbe_fare'].format(casa_nome=casa_nome, casa=casa_slug)}",
        f"Chi decide: {c['chi_decide'].format(casa_nome=casa_nome, casa=casa_slug)}",
        "",
        "L'elenco completo è nella card collegata e nella dashboard «Trasi · Casa».",
        "",
        "— Messaggio generato dal flusso notturno. Non rispondere a questo indirizzo.",
    ])


def verifica_testi() -> list[tuple[str, str]]:
    """I verbi imperativi presenti nei testi degli alert (V6). Lista vuota = conforme."""
    trovate: list[tuple[str, str]] = []
    for t in TIPI:
        testo = t.oggetto + "\n" + "\n".join(
            f"{k}: {v}" for k, v in t.campi.items())
        for verbo in verifica_v6(testo):
            trovate.append((t.chiave, verbo))
    return trovate


# --------------------------------------------------------------------------- costruzione


def case(mb: Mb, db_id: int) -> list[dict]:
    """Le Case, dalla vista: `slug` per il filtro, `nome` per il testo."""
    righe = leggi(mb, db_id, f"SELECT slug, nome FROM {VISTA_CASE} ORDER BY slug")
    return [{"slug": r[0], "nome": r[1]} for r in righe]


def recapiti(mb: Mb, db_id: int) -> dict[str, str]:
    """`slug` → indirizzo di recapito, dalla vista di B4 (la regola vive là, non qui)."""
    righe = leggi(mb, db_id, f"SELECT casa_slug, destinatario FROM {VISTA_RECAPITI} "
                             "WHERE destinatario IS NOT NULL ORDER BY casa_slug")
    return {r[0]: r[1] for r in righe}


def assicura_collezione(mb: Mb, nome: str) -> int:
    trovata = trova_per_nome(mb.get("/api/collection"), nome)
    if trovata:
        return trovata["id"]
    creata = mb.post("/api/collection", {
        "name": nome, "description": "Card degli alert per Casa (blocco B5)."})
    return creata["id"] if creata else 0


def assicura_card_alert(mb: Mb, db_id: int, tipo: Tipo, casa: dict, collezione: int) -> dict:
    """La card-avviso di una Casa, riconciliata per nome.

    Il filtro sulla Casa è **nella query** (`WHERE casa_slug = …`), non un parametro: un avviso che
    dipendesse da un parametro impostato a mano manderebbe l'email sbagliata il giorno in cui
    qualcuno cambia il filtro. La query continua a leggere **solo la vista** del dominio.
    """
    nome = tipo.nome_card.format(casa=casa["slug"])
    esistente = trova_per_nome(mb.get("/api/card"), nome)
    corpo = {
        "name": nome,
        "description": f"Avviso F6 «{tipo.titolo}» per {casa['nome']}. Filtro sulla Casa nella query.",
        "display": "table",
        "visualization_settings": {},
        "collection_id": collezione,
        "dataset_query": {"database": db_id, "type": "native",
                          "native": {"query": tipo.sql.format(casa=casa["slug"]),
                                     "template-tags": {}}},
    }
    if esistente:
        return mb.put(f"/api/card/{esistente['id']}", corpo) or esistente
    return mb.post("/api/card", corpo) or {"id": -1, "name": nome}


def tutte_le_notification(mb: Mb) -> list[dict]:
    """Tutte le notification, **comprese quelle spente**.

    `GET /api/notification` restituisce solo le attive: usarlo per l'idempotenza significa non
    vedere le spente e ricrearle a ogni esecuzione. È successo davvero, alla prima stesura di questo
    script, e ha prodotto dieci alert «proposte in attesa» duplicati — invisibili proprio perché
    spenti, quindi il difetto non si sarebbe visto fino al giorno in cui qualcuno li accendeva.
    L'elenco completo lo dà l'endpoint di amministrazione.
    """
    out: list[dict] = []
    offset = 0
    while True:
        pagina = mb.get(f"/api/notification/admin?limit=200&offset={offset}")
        out.extend(pagina["data"])
        offset += 200
        if offset >= pagina["total"]:
            return out


def assicura_notification(mb: Mb, tipo: Tipo, casa: dict, card_id: int,
                          destinatario: str) -> dict:
    """La notification di una Casa, riconosciuta dalla card che serve (idempotenza).

    `send_condition: has_result` — l'avviso parte **solo se la card ha righe**. Una Casa senza
    scadenze non riceve un'email che dice «0 scadenze»: il silenzio è l'informazione giusta, e un
    messaggio periodico che non dice niente è il modo più rapido per far filtrare nella posta
    indesiderata anche quelli che dicono qualcosa.
    """
    for n in tutte_le_notification(mb):
        if (n.get("payload") or {}).get("card_id") == card_id:
            return n

    return mb.post("/api/notification", {
        "payload_type": "notification/card",
        "payload": {"card_id": card_id, "send_condition": "has_result"},
        "handlers": [{
            "channel_type": "channel/email",
            "recipients": [{"type": "notification-recipient/raw-value",
                            "details": {"value": destinatario}}],
            "template": {
                "channel_type": "channel/email",
                "name": f"Trasi · {tipo.titolo} · {casa['slug']}",
                "details": {
                    "type": "email/handlebars-text",
                    "subject": tipo.oggetto.format(casa_nome=casa["nome"], casa=casa["slug"]),
                    "body": corpo_email(tipo, casa["nome"], casa["slug"]),
                },
            },
        }],
        "subscriptions": [{"type": "notification-subscription/cron", "cron_schedule": CRON}],
        "active": tipo.attivo,
    }) or {}


def costruisci(mb: Mb, accendi_proposte: bool) -> dict:
    db_id = trova_per_nome(mb.get("/api/database")["data"], "Trasi")["id"]
    collezione = assicura_collezione(mb, "Trasi · Alert")
    le_case = case(mb, db_id)
    recap = recapiti(mb, db_id)

    mancanti = [c["slug"] for c in le_case if c["slug"] not in recap]
    if mancanti:
        raise Errore(f"nessun recapito per: {', '.join(mancanti)} — "
                     "la catena è in trasi.v_flusso_recapiti (B4)")

    prima = {n["payload"]["card_id"]: n for n in tutte_le_notification(mb)
             if n.get("payload") and n["payload"].get("card_id")}
    create, riconciliate, attive = 0, 0, 0

    for tipo in TIPI:
        attivo = tipo.attivo or (tipo.chiave == "proposte_attesa" and accendi_proposte)
        for casa in le_case:
            card = assicura_card_alert(mb, db_id, tipo, casa, collezione)
            esistente = prima.get(card["id"])
            assicura_notification(mb, tipo, casa, card["id"], recap[casa["slug"]])
            if esistente:
                riconciliate += 1
            else:
                create += 1
            # Lo stato attivo/spento è una proprietà del **tipo**, non della singola notification:
            # si riallinea a ogni esecuzione, così `--accendi-proposte` e il default convergono
            # sempre, anche su una configurazione creata da una versione precedente dello script.
            for n in tutte_le_notification(mb):
                if (n.get("payload") or {}).get("card_id") == card["id"] and n["active"] != attivo:
                    mb.put(f"/api/notification/{n['id']}", {
                        "payload_type": "notification/card",
                        "payload": {"card_id": card["id"], "send_condition": "has_result"},
                        "active": attivo})
            attive += 1 if attivo else 0

    return {"case": len(le_case), "tipi": len(TIPI), "notification": len(le_case) * len(TIPI),
            "create": create, "riconciliate": riconciliate, "attive": attive}


def verifica(mb: Mb) -> dict:
    """Stato reale: quante notification, con quale destinatario, quante attive."""
    le_case = case(mb, trova_per_nome(mb.get("/api/database")["data"], "Trasi")["id"])
    nomi_card = {t.nome_card.format(casa=c["slug"]) for t in TIPI for c in le_case}
    cards = {c["name"]: c["id"] for c in mb.get("/api/card") if c["name"] in nomi_card}

    per_card: dict[int, list[dict]] = {}
    for n in tutte_le_notification(mb):
        cid = (n.get("payload") or {}).get("card_id")
        if cid in set(cards.values()):
            per_card.setdefault(cid, []).append(n)

    senza_destinatario, duplicati, dettaglio = [], [], []
    for nome, cid in sorted(cards.items()):
        ns = per_card.get(cid, [])
        dest = [(r.get("details") or {}).get("value")
                for n in ns for h in n.get("handlers", []) for r in h.get("recipients", [])]
        if not ns or not [d for d in dest if d]:
            senza_destinatario.append(nome)
        if len(ns) > 1:
            duplicati.append(nome)
        dettaglio.append({"card": nome, "card_id": cid,
                          "notification_id": ns[0]["id"] if ns else None,
                          "quante": len(ns),
                          "attiva": any(n["active"] for n in ns),
                          "destinatari": dest})
    return {"attese": len(nomi_card), "trovate": len(per_card), "duplicati": duplicati,
            "senza_destinatario": senza_destinatario, "dettaglio": dettaglio}


# --------------------------------------------------------------------------- CLI


def main() -> int:
    ap = argparse.ArgumentParser(description="Alert F6 per Casa su Metabase (B5).")
    ap.add_argument("--verifica", action="store_true", help="mostra lo stato, non scrive")
    ap.add_argument("--verifica-v6", action="store_true", help="solo il controllo V6 sui testi")
    ap.add_argument("--accendi-proposte", action="store_true",
                    help="sposta a Metabase l'email «proposte in attesa» (default: resta a flussi/alert.py)")
    ap.add_argument("--spegni-proposte", action="store_true",
                    help="riporta a flussi/alert.py l'email «proposte in attesa» (default)")
    ap.add_argument("--invia", type=int, metavar="ID", help="invia subito la notification ID")
    args = ap.parse_args()

    if args.verifica_v6:
        violazioni = verifica_testi()
        for chiave, verbo in violazioni:
            print(f"VIOLAZIONE V6 · alert {chiave}: «{verbo}»")
        print(f"V6: {len(violazioni)} verbi imperativi nei testi degli alert (atteso 0)")
        return 1 if violazioni else 0

    c = credenziali()
    mb = Mb()
    mb.login(c["MB_ADMIN_EMAIL"], c["MB_ADMIN_PASSWORD"])

    if args.invia:
        r = mb.post(f"/api/notification/{args.invia}/send", {})
        print(f"invio notification {args.invia}: {json.dumps(r)[:200] if r is not None else 'ok'}")
        return 0

    if args.verifica:
        v = verifica(mb)
        print(f"attese {v['attese']} · trovate {v['trovate']} · senza destinatario "
              f"{len(v['senza_destinatario'])} · duplicati {len(v['duplicati'])}")
        for d in v["dettaglio"]:
            stato = "attiva" if d["attiva"] else "spenta"
            notif = f"{d['notification_id']:>4}" if d["notification_id"] is not None else "   -"
            rip = f" (x{d['quante']})" if d["quante"] > 1 else ""
            print(f"  {d['card']:46s} notif={notif}{rip:6s} {stato:7s} "
                  f"→ {', '.join(x or '—' for x in d['destinatari']) or '—'}")
        return 1 if (v["senza_destinatario"] or v["duplicati"]) else 0

    # Il default è **spenta**: l'email di «proposte in attesa» la manda `flussi/alert.py`. Accenderla
    # è `--accendi-proposte`, cioè spostare la proprietà di quell'email a Metabase. Il verso del
    # default conta: un doppio invio è peggio di nessun invio, perché insegna a ignorare entrambe.
    attivo = bool(args.accendi_proposte)
    print("alert:", json.dumps(costruisci(mb, accendi_proposte=attivo)))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Errore as e:
        print(f"ERRORE: {e}", file=sys.stderr)
        sys.exit(2)
