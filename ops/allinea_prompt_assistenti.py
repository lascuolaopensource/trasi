#!/usr/bin/env python3
"""Allinea i prompt dei 4 assistenti Trasi alle sezioni obbligatorie, in modo idempotente.

**Perché esiste.** Il 2026-09-16 ho trovato che solo l'assistente «Trasi Casa» aveva le tre
sezioni critiche del prompt (identità/Casa, copia-verbatim del badge, ordine obbligatorio sulla
segnalazione). Gli altri tre no: erano stati creati con il blocco comune e mai aggiornati, quindi
su Presidio, Rete e Staff PN gli stessi difetti si sarebbero ripresentati — l'assistente che
chiede «di quale Casa parliamo?», l'etichetta riscritta a mano con l'ora sbagliata, la proposta
mai creata alla segnalazione di cambiamento. Il 2026-09-16 il gruppo processi ha chiesto di
minimizzare i «non lo so» (sezione 4: solo la carta etica resta un confine netto).

Aggiornare i prompt a mano, uno per uno, è ciò che ha prodotto l'incoerenza: il primo PATCH ne ha
sovrascritto uno per intero perdendo una sezione. Questo script rende l'operazione **cumulativa e
verificabile**: ogni sezione è identificata da un marcatore, si aggiunge solo se manca, e alla fine
il controllo dice quali mancano ancora.

**Uso** (le credenziali admin stanno in `/root/.onyx_admin_creds`):

    python3 ops/allinea_prompt_assistenti.py            # applica
    python3 ops/allinea_prompt_assistenti.py --dry-run  # mostra cosa farebbe

Non tocca i document set, i tool, i nomi: aggiorna solo `system_prompt`, e preserva tutto il resto
del prompt (le sezioni già presenti non vengono toccate).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = os.environ.get("ONYX_API_URL", "http://127.0.0.1/api")
CREDS = Path("/root/.onyx_admin_creds")

# Gli assistenti del progetto, per id. Il nome è solo per i messaggi.
ASSISTENTI = {1: "Trasi Presidio", 2: "Trasi Casa", 3: "Trasi Rete", 4: "Trasi Staff PN"}

# Le sezioni obbligatorie: (marcatore univoco, testo). L'ordine non conta — conta che ci siano.
# Ogni sezione nasce da un difetto osservato, non da un'idea di completezza:
SEZIONI: list[tuple[str, str]] = [
    (
        # Difetto: l'assistente rispondeva «di quale Casa parliamo?» senza chiamare il tool,
        # perché non sapeva che la Casa è determinata dall'account.
        # Secondo difetto (2026-09-17): la regola «NON indicare `casa`» gli impediva di leggere
        # le altre Case — l'operatore di POP chiedeva gli eventi di San Bao e riceveva i propri.
        "IDENTITÀ E CASA",
        """
IDENTITÀ E CASA — leggi prima di rispondere:
La Casa di Quartiere è determinata dall'account con cui l'operatore ha fatto accesso: la conosci già, non devi chiederla.
Quando chiami `vicino_a` e `eventi_oggi`, NON indicare il parametro `casa` se l'operatore parla della SUA Casa:
lo shim la usa automaticamente e la risposta porta il suo nome in `casa` — **etichetta la risposta con quel campo**,
non con il nome citato nella domanda.
Se invece l'operatore chiede di un'ALTRA Casa (per nome o slug), chiama `eventi_oggi` con `casa=<slug>` (santa-spazio, molo12, erranti, buscicchio, san-bao, minimus, pop, bozzano, dream, tuturano):
è ammesso e necessario — il tool legge il calendario di qualunque Casa della rete, l'auto-uso è solo un default.
Per TUTTE le Case della rete («tutte le Case», «in rete», «in città») chiama `eventi_oggi` con `casa=tutte`: UNA sola chiamata, mai una per Casa; ogni evento porta la sua Casa in `casa_slug`/`casa_nome`.
Non chiedere mai «di quale Casa parliamo?»: rispondi con i tuoi strumenti.
""",
    ),
    (
        # Difetto: l'assistente riformattava il badge invece di copiarlo, producendo
        # `[Esterna · SearXNG · 16/09/2026 16:?? · …]` — data sbagliata e ora illeggibile.
        "copia, non riscrivere",
        """
ETICHETTA — copia, non riscrivere:
Il campo `badge` che ricevi dagli strumenti va riportato **verbatim**, carattere per carattere.
Non riformattare la data, non sostituire l'ora con «??», non cambiare la dicitura.
Se non hai un `badge`, componi l'etichetta **solo** con i campi `fonte` e `data_aggiornamento`/`consultato_ts` e `fiducia` che trovi nella risposta.
""",
    ),
    (
        # Difetto: alla segnalazione «il bar ha chiuso» l'assistente chiedeva conferma e si
        # fermava lì, senza creare la proposta: la segnalazione dell'operatore andava persa.
        "ordine obbligatorio",
        """
SEGNALAZIONE DI CAMBIAMENTO — ordine obbligatorio:
Quando l'operatore ti dice che qualcosa è cambiato (un luogo ha chiuso, un orario è diverso, un servizio è nuovo),
1. chiama SUBITO `proponi_modifica` (non aspettare: la proposta va creata ora);
2. SOLO DOPO, se riguarda la sua Casa e la risposta indica `chat_approvabile: true`, chiedi «Vuoi che approvi ora? Sì / No»;
3. se risponde sì, chiama `approva_proposta`.
Non chiedere conferma **prima** di creare la proposta: chiedere «vuoi che aggiorni?» senza aver creato nulla non aggiorna niente e la segnalazione dell'operatore va persa.
""",
    ),
    (
        # Richiesta del gruppo processi (16/09): minimizzare i «non lo so». Il prompt diceva
        # «Se nessuna fonte risponde: dichiara «non trovo informazioni su questo»» — troppo
        # secco. Ora il modello deve degradare: KB → fonte autorizzata → rimando utile.
        # L'unico «non lo so» pieno resta per la carta etica (valutazioni cliniche, dati
        # personali, cose fuori dal mandato del Portierato).
        "Il «non lo so» è solo per la carta etica",
        """
IL «NON LO SO» È SOLO PER LA CARTA ETICA:
Se la KB e le fonti autorizzate non coprono la domanda, NON rispondere «non trovo informazioni» e basta.
Degrada in modo utile, in quest'ordine:
1. se una fonte esterna o la KB ha un dato parziale, dillo con la sua etichetta e spiega
   in una frase cosa manca («questo orario arriva da una mappa pubblica, non ancora verificato dalla rete»);
2. se nessuna fonte ha il dato, dai un **rimando utile**: dove può trovarlo l'operatore
   (numero della Casa, sportello, sito del Comune, URP, servizio competente);
3. solo la carta etica resta un confine netto: niente valutazioni cliniche, niente
   compagnia personale, niente dati personali — lì dichiari il limite e indichi chi
   può rispondere («il Portierato non può rispondere su questo; qui serve il medico / servizio X»).
Spiega gli errori in italiano semplice: «lo strumento non risponde» invece di «timeout», senza codici.
""",
    ),
    (
        # Difetto: alla domanda «quante richieste quest'anno?» l'assistente rispondeva di non
        # avere strumenti per le statistiche e rimandava a un report esterno: l'operazione
        # `statistiche` esiste, ma il prompt non la citava fra gli strumenti disponibili.
        "statistiche mensili",
        """
STATISTICHE MENSILI — usa `statistiche`:
Per «quante richieste abbiamo avuto», «come sono andate», «il mese scorso» e ogni domanda di conti sulle richieste
della Casa, chiama `statistiche` (parametro `mese` facoltativo, formato `AAAA-MM`).
Riporta i numeri **solo** come li dà lo strumento: il campo `n_label` («375», «<5», «—») e il campo `testo` sono già
mascherati secondo le regole della rete — non calcolare, non sommare, non stimare nulla che il risultato non dica.
Un mese senza richieste arriva come `ambiti: []`: dillo («mese senza richieste registrate»), non è un guasto.
""",
    ),
    (
        # Difetto (2026-09-18, misurato in `tool_call`): «gli eventi del mese di tutte le Case» → 20 chiamate
        # `eventi_oggi`, una per Casa, e la risposta «nessun evento». Il periodo è un parametro, non un ciclo.
        "FINESTRA TEMPORALE — periodi in una chiamata sola",
        """
FINESTRA TEMPORALE — periodi in una chiamata sola:
`eventi_oggi` copre un periodo con `finestra_gg` (giorni da `data`, 1–92: 7 = la settimana, 30 = il mese) oppure con
`al` (data di fine): «questa settimana», «questo weekend», «il mese», «i prossimi eventi» sono UNA chiamata, mai una
per giorno. Con `casa=tutte` copre tutta la rete nella stessa chiamata. Se l'operatore chiede un giorno preciso
(oggi, domani, «sabato 26»), basta `data`. Un parametro che lo strumento non conosce è un 422 che lo nomina: leggilo
e correggi la chiamata, non ripeterla uguale.
""",
    ),
    (
        # Il marcatore è una frase che esiste **nel testo** della sezione, non un'etichetta: il
        # controllo di presenza legge il prompt salvato (`_manca`), e un titolo che nel prompt non
        # compare dichiarerebbe la sezione assente per sempre — l'ha pagato la sessione sorella con
        # «IDENTITÀ E CASA» (ora lì il marcatore è «ALTRA Casa (per nome o slug)»).
        "CHIUSURA DEL COLLOQUIO — l'ultima riga di ogni tua risposta",
        """
CHIUSURA DEL COLLOQUIO — l'ultima riga di ogni tua risposta:
Ogni tua risposta si chiude con questa domanda: «Questa richiesta è **risolta** o **rinviata**?
(Se la persona è stata indirizzata altrove, dimmi dove: è `inviata_altrove`.)»
La domanda serve a registrare l'esito mentre il colloquio è in corso, non a fine giornata.
Quando l'operatore risponde, chiama `registra_richiesta` con `categoria` (l'ambito di cui si è parlato:
orientamento, fiscale_isee, servizi_sociali, lavoro, abitare, salute, interculturale, ascolto_solitudine,
eventi_attivita, altro) ed `esito`.
Gli esiti ammessi dal modello dati sono **quattro**, e solo questi: `risolta` (la Casa ha dato la risposta),
`inviata_altrove` (la persona è stata indirizzata a un altro servizio: allora serve anche la destinazione,
`destinazione_id` di un luogo della rete oppure `destinazione_nota`), `non_trovata` (nessuna destinazione
trovata), `rinviata` (se ne riparla in un altro momento). «Presa in carico», «ascolto» e «informazione»
non esistono nel modello: un valore fuori elenco è un 422 e la richiesta non viene registrata.
Non registrare due volte lo stesso colloquio e non chiedere dati personali: bastano categoria ed esito.
Se l'operatore non risponde alla domanda, non registrare nulla: un esito inventato è un dato falso.
""",
    ),
]

# Sezioni che valgono **solo per alcuni assistenti**: (marcatore, testo, id degli assistenti). L'attrezzoteca in
# chat (2026-09-18) ha due letture: la Casa legge **e** scrive il proprio inventario (`salva_dato`), la Rete legge
# soltanto (`cerca_oggetto`). Un testo unico direbbe alla Rete di scrivere ciò che il database le nega (db/032:
# GRANT ai soli ruoli Casa) — l'assistente proverebbe, riceverebbe 403 e lo racconterebbe come guasto.
SEZIONI_PER_ASSISTENTE: list[tuple[str, str, frozenset[int]]] = [
    (
        # Difetto (2026-09-18): «aggiungi 5 sedie all'attrezzoteca» e «dove trovo dei microfoni?» non avevano
        # uno strumento — il contratto non aveva letture dell'inventario e `salva_dato` non conosceva `oggetto`.
        "ATTREZZOTECA — l'inventario condiviso",
        """
ATTREZZOTECA — l'inventario condiviso della rete:
Per sapere dove si trova un oggetto, quanti pezzi sono disponibili o cosa c'è nell'attrezzoteca di una Casa, chiama
`cerca_oggetto` SUBITO, anche se la KB sembra saperlo: la disponibilità cambia ogni giorno ed è lì che sta il dato
fresco (tutte le Case; `casa=<slug>` per una sola). Riporta `casa_nome`, `quantita_disponibile`, `condizione` e il
`badge` così come sono: la disponibilità è già al netto dei prestiti in corso, non ricalcolarla.
Quando l'operatore chiede di aggiungere un oggetto all'attrezzoteca della sua Casa, chiama SUBITO `salva_dato` con
`entita="oggetto"` e ciò che ha detto (`nome`; `quantita` se omessa vale 1 — dillo nella risposta: «l'ho registrato
come 1 pezzo, dimmi se cambiare»; `condizione` se detta, altrimenti `integro`): non chiedere quantità, condizione né
conferma prima di scrivere. La correzione o il ritiro usano `id` (l'`oggetto_id` di `cerca_oggetto`): `attivo=false`
ritira l'oggetto. È scrittura diretta della tua Casa: non chiedere «di quale Casa» e non passare da `proponi_modifica`.
Dopo la scrittura riporta il `badge` della risposta come prova della scrittura.
Gli oggetti delle ALTRE Case si leggono soltanto: se l'operatore chiede di modificarli, digli di contattare quella Casa.
I prestiti tra Case si fanno dal portale (area operatore), non in chat.
""",
        frozenset({2}),
    ),
    (
        "ATTREZZOTECA — sola lettura",
        """
ATTREZZOTECA — sola lettura dell'inventario condiviso:
Per sapere dove si trova un oggetto, quanti pezzi sono disponibili o cosa c'è nell'attrezzoteca di una Casa, usa
`cerca_oggetto` (tutte le Case; `casa=<slug>` per una sola). Riporta `casa_nome`, `quantita_disponibile`, `condizione`
e il `badge` così come sono. Tu non scrivi l'inventario: lo fa ciascuna Casa per la propria; se serve una modifica,
indica quale Casa deve farla. I prestiti tra Case si fanno dal portale, non in chat.
""",
        frozenset({3}),
    ),
]

# Frasi di versioni precedenti delle sezioni, da sostituire: il marcatore della sezione c'è già,
# quindi il controllo «manca la sezione» non le vedrebbe. Ogni voce: (testo vecchio, testo nuovo).
SOSTITUZIONI: list[tuple[str, str]] = [
    (
        # Forma lunga (questo script): dopo la regola sull'ALTRA Casa entra quella per tutta la rete.
        "è ammesso e necessario — il tool legge il calendario di qualunque Casa della rete, l'auto-uso è solo un default.\n"
        "Non chiedere mai «di quale Casa parliamo?»",
        "è ammesso e necessario — il tool legge il calendario di qualunque Casa della rete, l'auto-uso è solo un default.\n"
        "Per TUTTE le Case della rete («tutte le Case», «in rete», «in città») chiama `eventi_oggi` con `casa=tutte`: UNA sola chiamata, mai una per Casa; ogni evento porta la sua Casa in `casa_slug`/`casa_nome`.\n"
        "Non chiedere mai «di quale Casa parliamo?»",
    ),
    (
        # Forma compatta (prompt scritti il 2026-09-18 da un'altra sessione, in esercizio su «Trasi Casa»).
        "Passa `casa=<slug>` SOLO per un'altra Casa (santa-spazio, molo12, erranti, buscicchio, san-bao, minimus, pop, bozzano, dream, tuturano).",
        "Passa `casa=<slug>` SOLO per un'altra Casa (santa-spazio, molo12, erranti, buscicchio, san-bao, minimus, pop, bozzano, dream, tuturano); `casa=tutte` per TUTTE le Case della rete in UNA chiamata (mai una per Casa).",
    ),
    (
        "• Periodi (`eventi_oggi`): usa `finestra_gg` (1–92) in UNA sola chiamata. Nessuna chiamata in loop.",
        "• Periodi (`eventi_oggi`): usa `finestra_gg` (1–92) o `al` in UNA sola chiamata, con `casa=tutte` se serve tutta la rete. Nessuna chiamata in loop. Un 422 «parametri non ammessi» nomina il parametro sbagliato: correggi, non ripetere.",
    ),
    (
        "Quando chiami `vicino_a`, `eventi_oggi` e `oggi`, NON indicare il parametro `casa`: lo shim usa automaticamente quella dell'operatore.",
        "Quando chiami `vicino_a` e `eventi_oggi`, NON indicare il parametro `casa` se l'operatore parla della SUA Casa:\n"
        "lo shim la usa automaticamente e la risposta porta il suo nome in `casa` — **etichetta la risposta con quel campo**,\n"
        "non con il nome citato nella domanda.\n"
        "Se invece l'operatore chiede di un'ALTRA Casa (per nome o slug), chiama `eventi_oggi` con `casa=<slug>` (santa-spazio, molo12, erranti, buscicchio, san-bao, minimus, pop, bozzano, dream, tuturano):\n"
        "è ammesso e necessario — il tool legge il calendario di qualunque Casa della rete, l'auto-uso è solo un default.",
    ),
    (
        # Il modello scriveva `casa=\"San Bao\"` (nome) e lo shim ripiegava sulla Casa dell'operatore:
        # gli slug elencati tolgono l'ambiguità.
        "chiama `eventi_oggi` con `casa=<slug>`:",
        "chiama `eventi_oggi` con `casa=<slug>` (santa-spazio, molo12, erranti, buscicchio, san-bao, minimus, pop, bozzano, dream, tuturano):",
    ),
]


def _leggi_credenziali() -> tuple[str, str]:
    email = password = None
    for riga in CREDS.read_text().splitlines():
        if riga.startswith("ONYX_ADMIN_EMAIL="):
            email = riga.split("=", 1)[1].strip()
        elif riga.startswith("ONYX_ADMIN_PASSWORD="):
            password = riga.split("=", 1)[1].strip()
    if not email or not password:
        raise SystemExit(f"credenziali non trovate in {CREDS}")
    return email, password


def _login(email: str, password: str) -> str:
    """Il cookie di sessione, senza mai stampare la password."""
    corpo = urllib.parse.urlencode({"username": email, "password": password}).encode()
    richiesta = urllib.request.Request(
        f"{BASE}/auth/login",
        data=corpo,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(richiesta, timeout=30) as risposta:
        for intestazione in risposta.headers.get_all("Set-Cookie") or []:
            if intestazione.startswith(("fastapiusersauth", "access_token")):
                return intestazione.split(";", 1)[0]
    raise SystemExit("login riuscito ma nessun cookie di sessione nella risposta")


def _richiesta(percorso: str, cookie: str, *, metodo: str = "GET", corpo: dict | None = None) -> dict:
    dati = json.dumps(corpo).encode() if corpo is not None else None
    richiesta = urllib.request.Request(
        f"{BASE}{percorso}",
        data=dati,
        method=metodo,
        headers={"Cookie": cookie, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(richiesta, timeout=60) as risposta:
            grezzo = risposta.read().decode()
    except urllib.error.HTTPError as errore:
        raise SystemExit(f"{metodo} {percorso} → HTTP {errore.code}: "
                         f"{errore.read().decode(errors='replace')[:200]}") from errore
    return json.loads(grezzo) if grezzo.strip() else {}


def _patch_body(persona: dict, prompt: str) -> dict:
    """Il PATCH con **tutti** i campi: l'API richiede l'oggetto completo.

    Le chiavi assenti nel GET sono opzionali e si mandano vuote; `tool_ids` e `document_set_ids`
    si ricavano dagli oggetti annidati, così l'aggiornamento non stacca i tool né la KB.
    """
    return {
        "name": persona["name"],
        "description": persona.get("description") or "",
        "system_prompt": prompt,
        "task_prompt": persona.get("task_prompt") or "",
        "datetime_aware": persona.get("datetime_aware", True),
        "is_public": persona.get("is_public", True),
        "is_listed": persona.get("is_listed", True),
        "icon_name": persona.get("icon_name"),
        "display_priority": persona.get("display_priority", 0),
        "is_featured": persona.get("is_featured", False),
        "builtin_persona": persona.get("builtin_persona", False),
        "replace_base_system_prompt": persona.get("replace_base_system_prompt", True),
        "tool_ids": [t["id"] for t in persona.get("tools", [])],
        "document_set_ids": [d["id"] for d in persona.get("document_sets", [])],
        "starter_messages": persona.get("starter_messages") or [],
        "user_file_ids": persona.get("user_file_ids") or [],
        "label_ids": [l["id"] for l in persona.get("labels", [])] if persona.get("labels") else [],
    }


def _manca(marcatore: str, prompt: str) -> bool:
    """Il marcatore è riconosciuto anche se il testo aggiunto l'ha normalizzato in maiuscolo
    (es. «Il «non lo so» …» → «IL «NON LO SO» …»). Il confronto avviene sul minuscolo."""
    return marcatore.casefold() not in prompt.casefold()


def _sezioni_di(persona_id: int) -> list[tuple[str, str]]:
    """Le sezioni attese per un assistente: quelle comuni più quelle riservate al suo id."""
    return list(SEZIONI) + [(m, t) for m, t, ids in SEZIONI_PER_ASSISTENTE if persona_id in ids]


def main(argv: list[str] | None = None) -> int:
    argomenti = argparse.ArgumentParser(description="Allinea i prompt dei 4 assistenti Trasi")
    argomenti.add_argument("--dry-run", action="store_true", help="mostra cosa farebbe, senza scrivere")
    argomenti.add_argument(
        "--solo-sostituzioni",
        action="store_true",
        help="applica solo le SOSTITUZIONI di frasi, senza aggiungere sezioni: per un prompt scritto in un'altra forma "
        "(es. quello compatto di «Trasi Casa»), a cui servono le regole nuove ma non un secondo testo in coda",
    )
    opzioni = argomenti.parse_args(argv)

    email, password = _leggi_credenziali()
    cookie = _login(email, password)

    mancanti_totali = 0
    for persona_id, nome in ASSISTENTI.items():
        persona = _richiesta(f"/persona/{persona_id}", cookie)
        prompt = persona.get("system_prompt") or ""

        assenti = [] if opzioni.solo_sostituzioni else [
            testo for marcatore, testo in _sezioni_di(persona_id) if _manca(marcatore, prompt)
        ]
        da_sostituire = [(v, n) for v, n in SOSTITUZIONI if v in prompt]
        if not assenti and not da_sostituire:
            print(f"  {persona_id} {nome}: già completo ({len(prompt)} caratteri)")
            continue

        mancanti_totali += len(assenti) + len(da_sostituire)
        nuovi = ", ".join(t.strip().splitlines()[0][:40] for t in assenti)
        if opzioni.dry_run:
            print(f"  {persona_id} {nome}: aggiungerebbe {len(assenti)} sezioni → {nuovi}; sostituirebbe {len(da_sostituire)} frasi")
            continue

        for vecchio, nuovo in da_sostituire:
            prompt = prompt.replace(vecchio, nuovo)
        for testo in assenti:
            prompt = prompt.rstrip() + "\n" + testo
        _richiesta(f"/persona/{persona_id}", cookie, metodo="PATCH", corpo=_patch_body(persona, prompt.strip()))
        print(f"  {persona_id} {nome}: aggiornato (+{len(assenti)} sezioni, {len(da_sostituire)} frasi sostituite, {len(prompt)} caratteri)")

    # Verifica finale: rilegge dal server e dice se qualcosa manca ancora. Un aggiornamento
    # dichiarato riuscito ma non persistito è esattamente il difetto che questo script previene.
    print("\nverifica (riletta dal server):")
    residui = 0
    for persona_id, nome in ASSISTENTI.items():
        prompt = _richiesta(f"/persona/{persona_id}", cookie).get("system_prompt") or ""
        assenti = [m for m, _ in _sezioni_di(persona_id) if _manca(m, prompt)]
        stato = "OK" if not assenti else f"MANCANO {assenti}"
        print(f"  {persona_id} {nome}: {stato}")
        residui += len(assenti)

    if opzioni.dry_run:
        print(f"\ndry-run: {mancanti_totali} sezioni da aggiungere in totale")
        return 0
    if residui and not opzioni.solo_sostituzioni:
        print(f"\nATTENZIONE: {residui} sezioni ancora mancanti dopo l'aggiornamento", file=sys.stderr)
        return 1
    print("\ntutti i prompt allineati.")
    return 0


if __name__ == "__main__":
    import urllib.parse  # usato in _login

    sys.exit(main())
