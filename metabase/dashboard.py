#!/usr/bin/env python3
"""Trasi — B5 · le 3 dashboard Metabase (Rete, Casa, Mappa) + gli alert per Casa.

Uno script, non una serie di clic. Le dashboard sono **configurazione**, e una configurazione che
esiste solo dentro il database H2 di Metabase non è riproducibile, non è revisionabile e non si
ricostruisce dopo un ripristino. Questo file è la fonte di verità: rieseguirlo converge allo stesso
stato (idempotente per nome, come `db/apply.sh` lo è per file).

Principi che il codice rispetta — sono i vincoli del blocco, non preferenze:

* **Le query sono nelle viste, non nelle card.** Nessuna card scrive SQL di dominio: interroga
  `trasi.v_*`. È ciò che garantisce che Home, chat e dashboard non possano dire numeri diversi
  (§7.3, requisito 4 del committente). Le card si limitano a filtrare e presentare.
* **k-anonimato 5 (§12).** Il numero grezzo sotto soglia **non esiste** nel database: le viste lo
  restituiscono già come `n IS NULL` + `n_label = '<5'`. Le card non ricalcolano mai `count(*)` su
  un dato di sportello — sarebbe la scorciatoia che aggira la maschera. Le colonne presentate sono
  le `*_label`, e le colonne numeriche non mascherate sono **nascoste** dalla lista bianca
  (`table.columns`), così non compaiono in una cella, in un tooltip né in un ordinamento.
* **V6 — l'umano decide.** Ogni testo che suggerisce mostra i quattro campi (*cosa è stato
  osservato / su quale evidenza / cosa si potrebbe fare / chi decide*) e nessun verbo imperativo.
  `--verifica-v6` lo controlla con una regex.
* **Sola lettura.** La connessione è `metabase_ro`, il ruolo senza `richiesta`, `proposta`, `audit`,
  `identita_onyx` (garantito da `db/007_dash.sql`). Nessuna Model action: questo file non contiene
  un solo `INSERT`/`UPDATE`/`DELETE`.
* **Alert: una sola email per tipo di avviso.** `flussi/alert.py` (B4) manda già le email di
  *proposte in attesa* e *coerenza fonti*. I quattro alert F6 di B5 sono quindi: tre con email
  (scaduti, in scadenza, senza risposta — che nessuno copre) e uno con canale **in-app**, che è il
  modo in cui il gestore vede la coda senza ricevere una seconda email per lo stesso fatto.
  La partizione è concordata con il worker dei flussi.

Uso:
    metabase/dashboard.py                 # costruisce o riconcilia le 3 dashboard
    metabase/dashboard.py --verifica-v6   # controllo V6 sui testi (0 verbi imperativi attesi)
    metabase/dashboard.py --dry-run       # mostra le azioni, non scrive

Credenziali: `metabase/.secrets/creds.env` (mode 600, mai versionato, mai stampato).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import httpx

RADICE = Path(__file__).resolve().parent.parent
CREDS = RADICE / "metabase" / ".secrets" / "creds.env"
BASE = os.environ.get("MB_URL", "http://127.0.0.1:3001")

#: Nome della connessione al dominio. La crea `metabase/provisiona.sh`.
NOME_DB = "Trasi"

#: La coda delle proposte. NocoDB non è avviato in B5 (vincolo di RAM): il link è configurato e non
#: risponde finché non entra in funzione in B6. Dichiarato, non nascosto.
URL_CODA_NOCODB = "https://trasi.lascuolaopensource.org/nocodb"

#: Gli id dei parametri devono restare stabili fra un'esecuzione e l'altra: i `parameter_mappings`
#: delle card li citano, e un id che cambia lascia le card col filtro scollegato.
ID_PERIODO = "5a1b2c3d"
ID_CASA = "6b2c3d4e"

#: Verbi imperativi vietati da V6 (§2.2). Ancorati alla parola intera e con le forme dell'italiano:
#: «aggiorna» è vietato, «aggiornamento» no — è un sostantivo, e serve per parlare di orari.
RE_V6 = re.compile(
    r"(?i)\b(aggiorna|aggiornate|contatta|contattate|chiama|chiamate|invia|inviate|verifica|"
    r"verificate|fai|fate|devi|dovete|bisogna|ricorda|ricordate|provvedi|provvedete|"
    r"assegna|assegnate|sollecita|sollecitate|correggi|correggere|avvisa|avvisate|"
    r"compila|compilate|stampa|stampate|controlla|controllate)\b"
)

#: I quattro campi V6, nell'ordine dell'architettura §2.2. Ogni testo che suggerisce li mostra tutti.
CAMPI_V6 = ("cosa_osservato", "evidenza", "cosa_si_potrebbe_fare", "chi_decide")


# =========================================================================== infrastruttura


class Errore(Exception):
    """Errore di configurazione, con il messaggio già pronto per chi legge il log."""


def credenziali() -> dict[str, str]:
    if not CREDS.exists():
        raise Errore(f"{CREDS} assente — esegui prima metabase/provisiona.sh")
    out: dict[str, str] = {}
    for riga in CREDS.read_text().splitlines():
        riga = riga.strip()
        if not riga or riga.startswith("#"):
            continue
        chiave, _, valore = riga.partition("=")
        out[chiave] = valore
    if "MB_ADMIN_EMAIL" not in out:
        raise Errore(f"{CREDS}: manca MB_ADMIN_EMAIL")
    return out


class Mb:
    """Client Metabase minimale: sessione, e i pochi endpoint che questo script usa."""

    def __init__(self, base: str = BASE) -> None:
        self.c = httpx.Client(base_url=base, timeout=180.0)
        self.dry = False

    def login(self, email: str, password: str) -> None:
        r = self.c.post("/api/session", json={"username": email, "password": password})
        if r.status_code >= 300:
            raise Errore(f"login Metabase fallito ({r.status_code}): {r.text[:200]}")
        self.c.headers["X-Metabase-Session"] = r.json()["id"]

    def get(self, path: str, **kw):
        r = self.c.get(path, **kw)
        if r.status_code >= 300:
            raise Errore(f"GET {path} → {r.status_code}: {r.text[:300]}")
        return r.json()

    def _scrivi(self, metodo: str, path: str, body):
        if self.dry:
            print(f"    [dry-run] {metodo} {path}")
            return None
        r = self.c.request(metodo, path, json=body)
        if r.status_code >= 300:
            raise Errore(f"{metodo} {path} → {r.status_code}: {r.text[:400]}")
        return r.json()

    def post(self, path: str, body):
        return self._scrivi("POST", path, body)

    def put(self, path: str, body):
        return self._scrivi("PUT", path, body)


# =========================================================================== le card


class Card:
    """Una card: nome, SQL sulla vista, resa, e i filtri che accetta.

    `colonne` è la lista **bianca** di ciò che si presenta. Tutto il resto non compare: è il
    meccanismo con cui le colonne numeriche non mascherate (`n`, `richieste_mese`, …) restano fuori
    dalla tabella **e dai tooltip**. Lista bianca e non nera di proposito: se un domani una vista
    guadagnasse una colonna con un numero grezzo, questa scelta la terrà fuori senza che nessuno
    debba ricordarsene.

    `filtri` mappa il nome del `template-tag` all'id del campo su cui filtrare (es. `{"casa": 440}`).
    Un tag dichiarato ma non mappato dalla dashboard **non** filtra: una card non filtra mai da sola.
    """

    def __init__(self, nome: str, sql: str, display: str = "table",
                 colonne: list[str] | None = None, viz: dict | None = None,
                 descrizione: str = "", filtri: dict[str, int] | None = None) -> None:
        self.nome = nome
        self.sql = sql.strip()
        self.display = display
        self.colonne = colonne
        self.viz = viz or {}
        self.descrizione = descrizione
        self.filtri = filtri or {}

    def template_tags(self) -> dict:
        """I `template-tag` della card, uno per filtro dichiarato.

        Sono `dimension` agganciati a un campo reale della vista: è ciò che rende il filtro una
        selezione fra i valori che esistono (le Case vere) invece di una stringa da digitare — e da
        digitare bene, perché «San Bao» e «san-bao» non sono la stessa cosa per un database.
        """
        tags = {}
        for nome, campo_id in self.filtri.items():
            tags[nome] = {
                "name": nome, "display-name": nome.capitalize(), "type": "dimension",
                "dimension": ["field", campo_id, None],
                "widget-type": "date/all-options" if nome == "periodo" else "category",
            }
        return tags


# --------------------------------------------------------------------------- Rete

CARDS_RETE: list[Card] = [
    Card(
        "Rete · richieste per Casa",
        """
        SELECT casa_nome AS "Casa", zona AS "Zona",
               richieste_mese_label AS "Richieste (mese corrente)",
               risolte_mese_label   AS "Risolte",
               destinate_mese_label AS "Inviate altrove"
          FROM trasi.v_confronto_case
         WHERE true [[AND {{periodo}}]]
         ORDER BY casa_nome
        """,
        colonne=["Casa", "Zona", "Richieste (mese corrente)", "Risolte", "Inviate altrove"],
        descrizione="Richieste del mese corrente per Casa. Sotto 5 il conteggio non esiste: si legge «<5».",
        filtri={"periodo": 411},   # v_confronto_case.mese
    ),
    Card(
        "Rete · categorie per Casa",
        """
        SELECT casa_nome AS "Casa", categoria AS "Categoria", esito AS "Esito",
               n_label AS "Richieste"
          FROM trasi.v_report_mensile
         WHERE n_label IS NOT NULL [[AND {{periodo}}]]
         ORDER BY casa_nome, categoria, esito
        """,
        colonne=["Casa", "Categoria", "Esito", "Richieste"],
        descrizione="Richieste per categoria ed esito. Le colonne sono mascherate dalla vista (k-anonimato 5).",
        filtri={"periodo": 562},   # v_report_mensile.mese
    ),
    Card(
        "Rete · proposte aperte per approvatore",
        """
        SELECT casa_nome AS "Casa", approvatore_ruolo AS "Chi decide",
               count(*) AS "Proposte in attesa",
               max(giorni_in_attesa) AS "Attesa massima (giorni)"
          FROM trasi.v_proposte_aperte
         WHERE true [[AND {{periodo}}]]
         GROUP BY casa_nome, approvatore_ruolo
         ORDER BY "Proposte in attesa" DESC, casa_nome
        """,
        colonne=["Casa", "Chi decide", "Proposte in attesa", "Attesa massima (giorni)"],
        descrizione="Proposte in attesa, per chi le deve decidere. Nessun nome di persona: solo il ruolo.",
        filtri={"periodo": 558},   # v_proposte_aperte.proposto_ts
    ),
    Card(
        "Rete · scadute",
        """
        SELECT casa_nome AS "Casa", titolo AS "Opportunità", categoria AS "Categoria",
               scadenza AS "Scaduta il", giorni_da_scadenza AS "Giorni"
          FROM trasi.v_scaduti
         WHERE true [[AND {{periodo}}]]
         ORDER BY giorni_da_scadenza DESC
        """,
        colonne=["Casa", "Opportunità", "Categoria", "Scaduta il", "Giorni"],
        descrizione="Opportunità con scadenza passata: la rete le conserva, ma non sono più attuali.",
        filtri={"periodo": 577},   # v_scaduti.scadenza
    ),
    Card(
        "Rete · in scadenza",
        """
        SELECT casa_nome AS "Casa", voce AS "Tipo", titolo AS "Voce",
               scadenza AS "Scade il", giorni_rimanenti AS "Giorni rimanenti"
          FROM trasi.v_in_scadenza
         WHERE true [[AND {{periodo}}]]
         ORDER BY giorni_rimanenti
        """,
        colonne=["Casa", "Tipo", "Voce", "Scade il", "Giorni rimanenti"],
        descrizione="Ciò che scade entro la finestra di preavviso configurata.",
        filtri={"periodo": 485},   # v_in_scadenza.scadenza
    ),
    Card(
        "Rete · senza risposta",
        """
        SELECT casa_nome AS "Casa", categoria AS "Categoria",
               count(*) AS "Colloqui", max(giorni_da_registrazione) AS "Più vecchio (giorni)"
          FROM trasi.v_senza_risposta
         WHERE true [[AND {{periodo}}]]
         GROUP BY casa_nome, categoria
         ORDER BY "Colloqui" DESC, casa_nome
        """,
        colonne=["Casa", "Categoria", "Colloqui", "Più vecchio (giorni)"],
        descrizione="Colloqui chiusi senza una risposta trovata. Solo categoria e conteggio: mai la persona.",
        filtri={"periodo": 592},   # v_senza_risposta.data
    ),
]

# --------------------------------------------------------------------------- Casa

CARDS_CASA: list[Card] = [
    Card(
        "Casa · oggi",
        """
        SELECT nome AS "Casa", eventi AS "Eventi oggi",
               schede_in_scadenza AS "Schede in scadenza", proposte AS "Proposte"
          FROM trasi.v_oggi_casa
         WHERE true [[AND {{casa}}]]
        """,
        colonne=["Casa", "Eventi oggi", "Schede in scadenza", "Proposte"],
        descrizione="La riga «Oggi» della Home. Una riga per Casa.",
        filtri={"casa": 538},   # v_oggi_casa.slug
    ),
    Card(
        "Casa · proposte in attesa",
        """
        SELECT tipo AS "Tipo", entita AS "Entità", origine AS "Origine",
               giorni_in_attesa AS "In attesa da (giorni)", approvatore_ruolo AS "Chi decide",
               motivazione AS "Motivazione", scade_il AS "Scade il"
          FROM trasi.v_proposte_aperte
         WHERE true [[AND {{casa}}]]
         ORDER BY giorni_in_attesa DESC
        """,
        colonne=["Tipo", "Entità", "Origine", "In attesa da (giorni)", "Chi decide",
                 "Motivazione", "Scade il"],
        descrizione=(
            "La coda delle proposte della propria Casa. La vista non espone chi ha proposto: "
            "il merito è del dato, non della persona (§12)."
        ),
        filtri={"casa": 551},   # v_proposte_aperte.casa_slug
    ),
    Card(
        "Casa · scaduti",
        """
        SELECT titolo AS "Opportunità", categoria AS "Categoria", scadenza AS "Scaduta il",
               giorni_da_scadenza AS "Giorni", fonte_nome AS "Fonte"
          FROM trasi.v_scaduti
         WHERE true [[AND {{casa}}]]
         ORDER BY giorni_da_scadenza DESC
        """,
        colonne=["Opportunità", "Categoria", "Scaduta il", "Giorni", "Fonte"],
        descrizione="Opportunità della Casa con scadenza passata.",
        filtri={"casa": 573},   # v_scaduti.casa_slug
    ),
    Card(
        "Casa · in scadenza",
        """
        SELECT voce AS "Tipo", titolo AS "Voce", scadenza AS "Scade il",
               giorni_rimanenti AS "Giorni rimanenti", fonte_nome AS "Fonte"
          FROM trasi.v_in_scadenza
         WHERE true [[AND {{casa}}]]
         ORDER BY giorni_rimanenti
        """,
        colonne=["Tipo", "Voce", "Scade il", "Giorni rimanenti", "Fonte"],
        descrizione="Ciò che scade a breve per questa Casa.",
        filtri={"casa": 482},   # v_in_scadenza.casa_slug
    ),
    Card(
        "Casa · destinazioni",
        """
        SELECT destinazione AS "Destinazione", destinazione_tipo AS "Tipo",
               n_label AS "Richieste",
               CASE WHEN interna_alla_casa THEN 'sì' ELSE 'no' END AS "Interna alla Casa",
               ultima_ts AS "Ultima volta"
          FROM trasi.v_destinazioni
         WHERE true [[AND {{casa}}]]
         ORDER BY "Richieste" DESC NULLS LAST, destinazione
        """,
        colonne=["Destinazione", "Tipo", "Richieste", "Interna alla Casa", "Ultima volta"],
        descrizione="Dove sono state indirizzate le persone. Sotto 5 il numero non esiste: si legge «<5».",
        filtri={"casa": 440},   # v_destinazioni.casa_slug
    ),
]

# --------------------------------------------------------------------------- Mappa

CARDS_MAPPA: list[Card] = [
    Card(
        "Mappa · Case di Quartiere",
        """
        SELECT nome AS "Casa", slug AS "slug", lat AS "lat", lon AS "lon",
               raggio_m_eff AS "Raggio di vicinanza (m)",
               CASE WHEN da_validare THEN 'dati provvisori' ELSE 'dati confermati' END AS "Stato dati",
               geom_qualita AS "Qualità posizione", orari_testo AS "Orari"
          FROM trasi.v_mappa_case
         ORDER BY nome
        """,
        display="map",
        colonne=["Casa", "slug", "lat", "lon", "Raggio di vicinanza (m)", "Stato dati",
                 "Qualità posizione", "Orari"],
        viz={"map.type": "pin", "map.latitude_column": "lat", "map.longitude_column": "lon",
             "map.pin_title": "Casa", "map.pin_type": "marker", "map.zoom": 11},
        descrizione=(
            "Le 10 Case di Quartiere. Il raggio di vicinanza è nel tooltip: la mappa non disegna "
            "cerchi, e un pin senza raggio farebbe credere che il raggio non esista."
        ),
    ),
    Card(
        "Mappa · luoghi",
        """
        SELECT nome AS "Luogo", tipo AS "Tipo", indirizzo AS "Indirizzo",
               lat AS "lat", lon AS "lon", orari_testo AS "Orari",
               fonte_nome AS "Fonte", affidabilita AS "Affidabilità"
          FROM trasi.v_mappa_luoghi
         ORDER BY nome
        """,
        display="map",
        colonne=["Luogo", "Tipo", "Indirizzo", "lat", "lon", "Orari", "Fonte", "Affidabilità"],
        viz={"map.type": "pin", "map.latitude_column": "lat", "map.longitude_column": "lon",
             "map.pin_title": "Luogo", "map.pin_type": "marker", "map.zoom": 11},
        descrizione="Luoghi e servizi in memoria, con la fonte e l'affidabilità dichiarate.",
    ),
    Card(
        "Mappa · luoghi vicini alla Casa",
        """
        SELECT nome AS "Luogo", tipo AS "Tipo", distanza_m AS "Distanza (m)",
               CASE WHEN entro_50m THEN 'entro 50 m' ELSE 'oltre 50 m' END AS "Vicinanza"
          FROM trasi.v_mappa_luoghi_vicini
         WHERE true [[AND {{casa}}]]
         ORDER BY distanza_m
        """,
        colonne=["Luogo", "Tipo", "Distanza (m)", "Vicinanza"],
        descrizione="Distanza dei luoghi dalla propria Casa, calcolata dal database (PostGIS).",
        filtri={"casa": 533},   # v_mappa_luoghi_vicini.casa_slug
    ),
    Card(
        "Mappa · destinazioni delle richieste",
        """
        SELECT destinazione AS "Destinazione", destinazione_tipo AS "Tipo",
               n_label AS "Richieste",
               CASE WHEN interna_alla_casa THEN 'sì' ELSE 'no' END AS "Interna alla Casa"
          FROM trasi.v_destinazioni
         WHERE true [[AND {{casa}}]]
         ORDER BY "Richieste" DESC NULLS LAST, destinazione
        """,
        colonne=["Destinazione", "Tipo", "Richieste", "Interna alla Casa"],
        descrizione=(
            "Dove sono state indirizzate le persone, per Casa. La colonna «Richieste» mostra la resa "
            "mascherata: sotto soglia è «<5», a zero è «—»."
        ),
        filtri={"casa": 440},   # v_destinazioni.casa_slug
    ),
]


# =========================================================================== i testi V6

TESTO_RETE = """
### Come si legge questa dashboard

**Cosa è stato osservato.** Ogni riquadro conta ciò che la rete ha registrato: richieste ed esiti per
Casa, categorie, proposte in attesa con il ruolo che le deve decidere, opportunità scadute o in
scadenza, colloqui chiusi senza che una risposta sia stata trovata.

**Su quale evidenza.** I numeri vengono dalle viste `trasi.v_confronto_case`, `v_report_mensile`,
`v_proposte_aperte`, `v_scaduti`, `v_in_scadenza`, `v_senza_risposta`: sono le stesse che alimentano
la chat e la riga «Oggi» della Home, quindi non possono raccontare una storia diversa.

**Cosa si potrebbe fare.** Questi numeri si possono leggere come una fotografia della rete: dove le
richieste si concentrano, quali categorie restano senza risposta, da quanto tempo una proposta
aspetta. Il confronto fra Case è possibile solo dove il conteggio supera la soglia di riservatezza.

**Chi decide.** Le priorità della rete sono in mano all'AT e ai gestori delle Case. Questa dashboard
non distribuisce compiti e non dà ordini: mostra lo stato, e la decisione si prende altrove.

*Sotto la soglia di riservatezza il conteggio non è nascosto: non esiste. Si legge «<5». A zero si
legge «—». Non c'è modo di risalire al numero vero da questa pagina, perché il numero vero non
arriva a Metabase.*
"""

TESTO_CASA = """
### Come si legge la dashboard della propria Casa

**Cosa è stato osservato.** La riga «Oggi» riassume la giornata: eventi in programma, schede in
scadenza, proposte in attesa di una decisione. Sotto, la coda delle proposte con da quanto tempo
aspettano e chi le deve decidere, ciò che è scaduto o sta per scadere, e dove sono state indirizzate
le persone.

**Su quale evidenza.** I dati vengono da `trasi.v_oggi_casa`, `v_proposte_aperte`, `v_scaduti`,
`v_in_scadenza`, `v_destinazioni`. La coda è la stessa della vista «Da approvare» in NocoDB: una
proposta decisa lì sparisce da qui.

**Cosa si potrebbe fare.** La coda mostra ogni proposta con la sua motivazione e il tempo di attesa:
si può approvare o rifiutare dalla coda, leggendo il diff di ciò che cambia. Una proposta che scade
non si perde: resta leggibile, e una proposta nuova la sostituisce.

**Chi decide.** Le proposte della Casa le decide il gestore; quelle sul territorio e sul Comune le
decide l'AT. La dashboard dichiara per ciascuna riga chi è competente, e non decide al posto di
nessuno.

*La Casa è obbligatoria: senza sceglierla, i riquadri mostrano i dati di San Bao, che è il valore
iniziale. Il filtro è in alto, e la Home lo imposta da sé con `?casa=<slug>`.*

*Sotto la soglia di riservatezza il conteggio non è nascosto: non esiste. Si legge «<5». A zero si
legge «—».*
"""

TESTO_MAPPA = """
### Come si legge la mappa

**Cosa è stato osservato.** Ogni pin è un luogo della rete o una Casa di Quartiere, con la posizione
che il database conserva. Il passaggio del mouse su un pin mostra la provenienza, l'affidabilità e il
raggio di vicinanza di quel dato.

**Su quale evidenza.** I pin vengono da `trasi.v_mappa_case` e `v_mappa_luoghi`; le distanze dalla
propria Casa da `v_mappa_luoghi_vicini` (calcolate in PostGIS, non stimate a occhio); le destinazioni
delle richieste da `v_destinazioni`.

**Cosa si potrebbe fare.** Si possono guardare i luoghi intorno a una Casa, vedere quali sono interni
e quali nel quartiere, e leggere quanta parte delle richieste si è indirizzata fuori. I luoghi con
affidabilità bassa o con dati provvisori sono dichiarati come tali accanto al nome.

**Chi decide.** La promozione di un dato esterno in memoria e la conferma di un dato provvisorio
sono in mano all'AT. La mappa mostra la posizione, non la convalida.

*Il raggio di vicinanza di ogni Casa è scritto accanto al pin, non disegnato: la mappa non traccia
cerchi, e un cerchio assente si leggerebbe come «raggio zero». Per le destinazioni vale la stessa
regola dei conteggi: sotto soglia si legge «<5», mai il numero.*
"""


def testi_dashboard() -> dict[str, str]:
    return {"Rete": TESTO_RETE, "Casa": TESTO_CASA, "Mappa": TESTO_MAPPA}


def verifica_v6(testi: dict[str, str]) -> list[tuple[str, str]]:
    """Le violazioni V6: `(dove, verbo)` per ogni verbo imperativo trovato. Vuota = conforme.

    Il controllo non è un'euristica di stile: è la parte meccanica di un vincolo (§2.2) sul modo in
    cui il sistema parla alle persone. Un testo che ordina sbaglia a prescindere da quanto sia utile,
    e questo è il modo di accorgersene senza doverlo rileggere ogni volta.
    """
    trovate: list[tuple[str, str]] = []
    for dove, testo in testi.items():
        for m in RE_V6.finditer(testo):
            trovate.append((dove, m.group(0)))
    return trovate


# =========================================================================== parametri


def parametro_periodo() -> dict:
    """Filtro «periodo»: un solo parametro per «ultimi 30 giorni», «questo mese» o intervallo.

    È la forma che l'architettura §4.3 chiede (un filtro, non tre), e il default `past30days` è
    quello della spec B5-DSH-04.
    """
    return {"name": "Periodo", "slug": "periodo", "id": ID_PERIODO,
            "type": "date/all-options", "sectionId": "date", "default": "past30days"}


def parametro_casa(obbligatorio: bool) -> dict:
    """Filtro «Casa», sul valore dello slug.

    Lo slug è la chiave che il deep link della Home usa (`?casa=<slug>`, §4.3): rende il filtro
    impostabile da un URL, senza passare dall'interfaccia.

    Metabase non sa rendere un parametro *obbligatorio*: il vincolo sta nel testo della dashboard,
    che è dove l'operatore lo legge. Il default è San Bao, la Casa dell'esempio dell'architettura
    §4.3, e la Home lo sovrascrive. Un default è la differenza fra «la pagina si apre su una Casa» e
    «la pagina si apre su tutte le Case», che per un gestore è un dato che non gli appartiene.
    """
    return {"name": "Casa", "slug": "casa", "id": ID_CASA, "type": "category",
            "sectionId": "string", "default": "san-bao" if obbligatorio else None}


def mappatura(card_id: int, filtri: dict[str, int], parametri: dict[str, dict]) -> list[dict]:
    """Collega alla card i filtri che essa dichiara, e solo quelli.

    Il collegamento è per card, una per una: una card a cui il filtro «Casa» non è mappato non può
    mostrare i dati di un'altra Casa, perché non riceve affatto il valore.

    Il `target` è `["dimension", ["template-tag", …]]`, non `"variable"`: il template-tag è un
    `dimension` agganciato a un campo, e con `variable` Metabase accetta la mappatura senza
    applicarla — la card gira, il filtro sembra a posto, e i numeri restano quelli di tutte le Case.
    È il difetto che questa riga esiste per non ripetere (verificato: con `variable` il filtro «Casa»
    su Bozzano restituiva 10 righe, con `dimension` 1).
    """
    fuori = []
    for nome in filtri:
        if nome in parametri:
            fuori.append({"parameter_id": parametri[nome]["id"], "card_id": card_id,
                          "target": ["dimension", ["template-tag", nome]]})
    return fuori


# =========================================================================== costruzione


def trova_per_nome(oggetti: list[dict], nome: str) -> dict | None:
    return next((o for o in oggetti if o["name"] == nome), None)


def assicura_collezione(mb: Mb, nome: str) -> int:
    """Una collezione dedicata: le dashboard di progetto non stanno in «Le nostre analisi» mescolate."""
    trovata = trova_per_nome(mb.get("/api/collection"), nome)
    if trovata:
        return trovata["id"]
    creata = mb.post("/api/collection", {
        "name": nome, "description": "Dashboard e alert del progetto Trasi (blocco B5)."})
    return creata["id"] if creata else 0


def assicura_card(mb: Mb, db_id: int, card: Card, collezione: int) -> dict:
    """Crea o riconcilia la card **per nome**: rieseguire non duplica (come `db/apply.sh`)."""
    esistente = trova_per_nome(mb.get("/api/card"), card.nome)
    corpo = {
        "name": card.nome,
        "description": card.descrizione,
        "display": card.display,
        "visualization_settings": viz_della_card(card),
        "collection_id": collezione,
        "dataset_query": {"database": db_id, "type": "native",
                          "native": {"query": card.sql, "template-tags": card.template_tags()}},
    }
    if esistente:
        return mb.put(f"/api/card/{esistente['id']}", corpo) or esistente
    return mb.post("/api/card", corpo) or {"id": -1, "name": card.nome}


def viz_della_card(card: Card) -> dict:
    """Resa della card, con la **lista bianca** delle colonne presentate.

    `table.columns` con le sole colonne elencate è ciò che tiene fuori dalla pagina le colonne
    numeriche non mascherate. Su una card mappa le stesse impostazioni valgono per il tooltip:
    la lista bianca è una sola, quindi non esiste un percorso in cui un numero grezzo arrivi
    all'occhio passando dal tooltip invece che dalla tabella.
    """
    viz = dict(card.viz)
    if card.colonne:
        viz["table.columns"] = [{"name": c, "enabled": True} for c in card.colonne]
    return viz


def assicura_dashboard(mb: Mb, nome: str, descrizione: str, collezione: int,
                       parametri: list[dict]) -> dict:
    esistente = trova_per_nome(mb.get("/api/dashboard"), nome)
    corpo = {"name": nome, "description": descrizione, "collection_id": collezione,
             "parameters": parametri, "width": "full"}
    if esistente:
        return mb.put(f"/api/dashboard/{esistente['id']}", corpo) or esistente
    return mb.post("/api/dashboard", corpo) or {"id": -1, "name": nome}


def _riquadro_card(card_id: int, id_dc: int, riga: int, colonna: int, dim_x: int, dim_y: int,
                   mappature: list[dict]) -> dict:
    return {"id": id_dc, "card_id": card_id, "row": riga, "col": colonna,
            "size_x": dim_x, "size_y": dim_y,
            "parameter_mappings": mappature, "visualization_settings": {}}


def _riquadro_testo(testo: str, id_dc: int, riga: int, colonna: int,
                    dim_x: int, dim_y: int) -> dict:
    return {"id": id_dc, "card_id": None, "row": riga, "col": colonna,
            "size_x": dim_x, "size_y": dim_y, "parameter_mappings": [],
            "visualization_settings": {"text": testo, "virtual_card": {
                "name": None, "display": "text", "visualization_settings": {},
                "dataset_query": {}, "archived": False}}}


def disponi(mb: Mb, dash: dict, riquadri: list[dict]) -> None:
    """Scrive l'**insieme** dei riquadri della dashboard in una sola chiamata.

    L'endpoint sostituisce il contenuto, non lo integra: per questo la costruzione è dichiarativa.
    Si passa la lista completa di ciò che la dashboard deve contenere, e il risultato converge —
    rieseguire non raddoppia niente, e un riquadro tolto dal codice sparisce anche dalla dashboard,
    senza che nessuno debba ricordarsi di cancellarlo a mano.

    Gli id dei riquadri già presenti si riusano; ai nuovi si dà un id negativo, che è la convenzione
    con cui l'API segnala «da creare». Senza il riuso, ogni esecuzione creerebbe riquadri nuovi e la
    dashboard cambierebbe identità a ogni riconciliazione.
    """
    esistenti = mb.get(f"/api/dashboard/{dash['id']}").get("dashcards", [])
    per_card = {dc["card_id"]: dc["id"] for dc in esistenti if dc.get("card_id") is not None}
    per_testo = {dc.get("visualization_settings", {}).get("text"): dc["id"]
                 for dc in esistenti if dc.get("card_id") is None}

    corpo = []
    for i, r in enumerate(riquadri):
        # L'id negativo identifica il riquadro da creare; è unico per posizione, così due riquadri
        # nuovi nello stesso giro non collidono.
        id_dc = -(i + 1)
        if r["testo"] is not None:
            corpo.append(_riquadro_testo(r["testo"], per_testo.get(r["testo"], id_dc),
                                         r["row"], r["col"], r["size_x"], r["size_y"]))
        else:
            corpo.append(_riquadro_card(r["card_id"], per_card.get(r["card_id"], id_dc),
                                        r["row"], r["col"], r["size_x"], r["size_y"], r["mappature"]))
    mb.put(f"/api/dashboard/{dash['id']}/cards", {"cards": corpo})


def _griglia(cards: list[Card], card_risolte: list[dict], parametri: dict[str, dict],
             riga_inizio: int, alto: int, largo: int = 12, per_riga: int = 2) -> list[dict]:
    riquadri = []
    for i, (c, card) in enumerate(zip(cards, card_risolte)):
        riquadri.append({
            "testo": None, "card_id": card["id"],
            "row": riga_inizio + (i // per_riga) * alto, "col": (i % per_riga) * largo,
            "size_x": largo, "size_y": alto,
            "mappature": mappatura(card["id"], c.filtri, parametri),
        })
    return riquadri


def costruisci(mb: Mb) -> dict:
    db_id = trova_per_nome(mb.get("/api/database")["data"], NOME_DB)["id"]
    collezione = assicura_collezione(mb, "Trasi · Osservatorio")

    par_casa_casa = parametro_casa(True)
    par_casa_mappa = parametro_casa(False)
    par_periodo = parametro_periodo()

    dash_rete = assicura_dashboard(
        mb, "Trasi · Rete",
        "Come sta andando la rete delle Case di Quartiere: richieste, esiti, categorie, proposte in "
        "attesa, scadenze e colloqui senza risposta. Il numero sotto la soglia di riservatezza non "
        "esiste: si legge «<5».",
        collezione, [par_periodo])
    dash_casa = assicura_dashboard(
        mb, "Trasi · Casa",
        "Come sta andando questa Casa di Quartiere: oggi, proposte in attesa con chi le deve "
        "decidere, scadenze e destinazioni. La Casa è obbligatoria — il filtro è in alto.",
        collezione, [par_casa_casa, par_periodo])
    dash_mappa = assicura_dashboard(
        mb, "Trasi · Mappa",
        "Dove sono le Case di Quartiere e i luoghi della rete, con provenienza e affidabilità di "
        "ogni dato. Il raggio di vicinanza è accanto al pin: la mappa non disegna cerchi.",
        collezione, [par_casa_mappa])

    # --- Rete: il testo che spiega come si legge, poi i numeri ---------------------------
    risolte = [assicura_card(mb, db_id, c, collezione) for c in CARDS_RETE]
    disponi(mb, dash_rete, [{"testo": TESTO_RETE, "card_id": None, "row": 0, "col": 0,
                             "size_x": 24, "size_y": 10, "mappature": []}]
            + _griglia(CARDS_RETE, risolte, {"periodo": par_periodo}, riga_inizio=10, alto=6))

    # --- Casa: il filtro obbligatorio è un default, e il testo lo dichiara ---------------
    risolte = [assicura_card(mb, db_id, c, collezione) for c in CARDS_CASA]
    disponi(mb, dash_casa, [{"testo": TESTO_CASA, "card_id": None, "row": 0, "col": 0,
                             "size_x": 24, "size_y": 10, "mappature": []}]
            + _griglia(CARDS_CASA, risolte, {"casa": par_casa_casa}, riga_inizio=10, alto=6))

    # --- Mappa: la geografia prima, i conteggi mascherati dopo ---------------------------
    risolte = [assicura_card(mb, db_id, c, collezione) for c in CARDS_MAPPA]
    disponi(mb, dash_mappa, [{"testo": TESTO_MAPPA, "card_id": None, "row": 0, "col": 0,
                              "size_x": 24, "size_y": 10, "mappature": []}]
            + _griglia(CARDS_MAPPA, risolte, {"casa": par_casa_mappa}, riga_inizio=10, alto=7))

    return {"Rete": dash_rete["id"], "Casa": dash_casa["id"], "Mappa": dash_mappa["id"],
            "collezione": collezione}


# =========================================================================== CLI


def main() -> int:
    ap = argparse.ArgumentParser(description="Costruisce le dashboard Trasi su Metabase.")
    ap.add_argument("--dry-run", action="store_true", help="mostra le azioni, non scrive")
    ap.add_argument("--verifica-v6", action="store_true", help="solo il controllo V6 sui testi")
    args = ap.parse_args()

    if args.verifica_v6:
        violazioni = verifica_v6(testi_dashboard())
        for dove, verbo in violazioni:
            print(f"VIOLAZIONE V6 · {dove}: «{verbo}»")
        print(f"V6: {len(violazioni)} verbi imperativi nei testi delle dashboard "
              f"(atteso 0 su {len(testi_dashboard())} testi)")
        return 1 if violazioni else 0

    c = credenziali()
    mb = Mb()
    mb.dry = args.dry_run
    mb.login(c["MB_ADMIN_EMAIL"], c["MB_ADMIN_PASSWORD"])
    print("dashboard:", json.dumps(costruisci(mb)))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Errore as e:
        print(f"ERRORE: {e}", file=sys.stderr)
        sys.exit(2)
