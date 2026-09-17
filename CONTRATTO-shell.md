# CONTRATTO DELLA SHELL — congelato prima che i bot partano

**Perché questo file esiste.** Quattro bot toccano quattro pagine che condividono la stessa testata, la stessa navigazione
e gli stessi token. Senza un contratto congelato, tre bot riscrivono la stessa intestazione in tre modi e
l'integrazione costa più della scrittura. Questo file è **il contratto**: chi costruisce le pagine lo usa e **non
lo modifica**; solo il proprietario della shell può cambiarlo, e in quel momento avvisa gli altri.

**Regola unica e non negoziabile: un file, un proprietario.** Il file è di chi lo crea; gli altri lo **includono**
o lo **caricano**, non lo modificano.

---

## 1. I file e chi li possiede

| File | Proprietario | Cosa contiene |
|---|---|---|
| `_shell.html` | BOT-1 | il guscio: testata con navigazione, main, piede. **Contiene segnaposto**, non contenuti |
| `assets/struttura.css` | BOT-1 | layout, griglia, classi del contratto. **Nessuna scelta di veste** |
| `assets/veste.css` | BOT-1 | ciò che X sostituisce. Importa i token di `design/tokens/` |
| `assets/shell.js` | BOT-1 | sessione (`GET /me`), testata, «Esci», riga della coda (`Trasi.rigaCoda`) |
| `index.html` | BOT-1 | **Accesso** (se non c'è sessione) **e** Home: due viste dello stesso file |
| `home.html` | BOT-2 | la Home: oggi, cosa aspetta una decisione, le destinazioni, il rimando a Onyx |
| `assets/home.js` | BOT-2 | le tre letture della Home (eventi di oggi, coda, prestiti) |
| `osservatorio.html` | BOT-3 | mappa, elenco, scheda (tre viste dello stesso file) |
| `assets/mappa.js` | BOT-3 | Leaflet, pin, legenda, sincronizzazione con l'elenco |
| `account.html` | BOT-4 | la **pagina singola**: carica le 7 sezioni e ne mostra una |
| `assets/account.js` | BOT-4 | sotto-navigazione, caricamento delle sezioni via `fetch` |
| `account/la-casa.html` | BOT-4 | sezione 1 (frammento, **solo markup**) |
| `account/proposte.html` | BOT-4 | sezione 3 |
| `account/numeri.html` | BOT-5 | sezione 2 |
| `account/registra.html` | BOT-5 | sezione 4 |
| `account/attrezzoteca.html` | BOT-5 | sezione 5 |
| `account/messaggi.html` | BOT-5 | sezione 6 |
| `account/impostazioni.html` | BOT-5 | sezione 7 |
| `aiuto.html` | BOT-6 | l'Aiuto riscritto per le tre pagine |
| `stati/*.html` | BOT-6 | le condizioni forzate, per pagina |

## 2. La shell — struttura esatta

`_shell.html` è un **frammento** (non un documento completo): inizia con `<a class="salta">` e finisce con il
piede. Ogni pagina lo include copiandolo **una volta**, alla prima scrittura, e da lì in poi se lo tiene.

È una **testata**, non una sidebar: Casa a sinistra, le tre destinazioni in riga, Aiuto ed Esci a destra. Sotto
40 rem la riga va a capo da sola. Non c'è un «Menu» e non c'è un pannello contestuale: la conversazione con
l'assistente della rete vive su Onyx, non in queste pagine.

```html
<a class="salta" href="#contenuto">Salta al contenuto</a>

<header class="testata">
  <div class="testata-casa">
    <p class="marchio">TRASI</p>
    <p class="casa-nome" id="shell-casa">accesso in corso…</p>
    <p class="casa-zona" id="shell-zona"></p>
  </div>

  <nav class="nav" aria-label="Destinazioni">
    <a class="nav-voce" href="home.html">Home</a>
    <a class="nav-voce" href="osservatorio.html">Osservatorio</a>
    <a class="nav-voce" href="account.html">Account</a>
  </nav>

  <div class="testata-azioni">
    <a class="azione" href="aiuto.html">Aiuto</a>
    <button class="azione" type="button" id="shell-esci">Esci</button>
  </div>
</header>

<main class="contenuto" id="contenuto"><!-- CONTENUTO DELLA PAGINA --></main>

<footer class="piede">
  <p class="privacy">Non conserva dati personali.</p>
</footer>
```

**La voce corrente si dichiara con `aria-current="page"`** — la pagina, al caricamento, la mette sulla propria voce
(una riga in `shell.js` che confronta l'`href` con il nome del file).

## 3. Le classi del contratto (in `struttura.css`)

Queste esistono e **non si inventano altre** per le stesse cose. Ogni bot può aggiungere classi **proprie** con
prefisso della pagina (`home-`, `mappa-`, `acc-`) nel proprio file CSS, se serve: quelle non sono
condivise e non si toccano fra bot.

| Area | Classi | Note |
|---|---|---|
| Guscio | `.testata`, `.contenuto`, `.piede`, `.salta` | colonna unica; `.contenuto` largo al più 62 rem |
| Testata | `.testata-casa`, `.marchio`, `.casa-nome`, `.casa-zona`, `.testata-azioni` | |
| Navigazione | `.nav`, `.nav-voce`, `.nav-voce[aria-current="page"]` | |
| Piede | `.azione`, `.privacy` | |
| Contenuto | `.titolo-pagina`, `.blocco`, `.blocco-testa`, `.riga`, `.elenco`, `.vuoto` | |
| Stati | `.filetto` + `.filetto--oggi` `.filetto--coda` `.filetto--attenzione` `.filetto--spento` | il segno di stato, 4 px |
| Etichette | `.etichetta`, `.etichetta--provenienza`, `.etichetta--esterna` | `--esterna` ha il bordo tratteggiato |
| Bottoni | `.bottone`, `.bottone--principale`, `.bottone--quieto` | bersaglio ≥ 44 px |
| Tabella | `.tabella` | con `<caption>` e `<th scope="col">` |

## 4. Il contratto di codice — `window.Trasi`

`shell.js` espone un solo aggancio, e nient'altro:

```js
// shell.js
window.Trasi = {
  casa: null,          // {casa, casa_id, ruolo, nome, zona, …} da GET /me + GET /op/casa, o null
  api(percorso, opzioni) { … },   // fetch verso /api/shim, gestisce 401 → ritorno all'accesso
  rigaCoda(contenitore) { … },    // la riga «N proposte aspettano una decisione a <Casa>» (Home e Account)
  nomeCasa() { … },               // il nome della Casa come lo mostra la testata
  pronto: Promise,                 // risolta con `casa` quando la sessione è nota
  voceCorrente: "home.html"        // il file della pagina, per aria-current
};
```

**Questo è l'unico contratto di codice fra le pagine.** Chi ha bisogno di una funzione lo chiede a BOT-1 invece di
scrivere una seconda copia: `rigaCoda` è nata così, perché Home e Account mostrano la stessa riga e due copie del
testo sarebbero divergute alla prima correzione.

## 5. `account.html` — pagina singola, sette viste

`account.html` **non contiene** le sezioni: le carica. La struttura è:

```html
<main class="contenuto" id="contenuto">
  <h1 class="titolo-pagina">Account · <span id="acc-casa">…</span></h1>
  <nav class="acc-sottonav" aria-label="Sezioni dell'account">
    <a href="#la-casa">La Casa</a> <a href="#numeri">Numeri</a> <a href="#proposte">Proposte</a>
    <a href="#registra">Registra</a> <a href="#attrezzoteca">Attrezzoteca</a>
    <a href="#messaggi">Messaggi</a> <a href="#impostazioni">Impostazioni</a>
  </nav>
  <div id="acc-vista" aria-live="polite"><!-- qui entra UNA sezione --></div>
</main>
```

**Regole del caricamento** (in `account.js`, BOT-4):
1. La sezione attiva viene da `location.hash`; senza hash è `#la-casa`.
2. `fetch('account/<nome>.html')` → `innerHTML` dentro `#acc-vista`. Una sezione alla volta: le altre **non** sono
   nel DOM (così gli id non collidono e la pagina resta leggera).
3. Gli id di una sezione sono prefissati `acc-<nome>-…` (es. `acc-numeri-tabella`): **due bot diversi non devono
   poter generare lo stesso id**.
4. **I frammenti sono solo markup**: `<script>` dentro un frammento **non** viene eseguito da `innerHTML`. Il
   comportamento sta in `account.js` o in un modulo della sezione, caricato una volta da `account.js` quando
   serve. Chi scrive una sezione lo sa e non mette script nel frammento.
5. Se il `fetch` fallisce, la vista mostra lo stato «Dati non disponibili» — non un errore grezzo.

## 6. Comportamento della testata (un posto solo)

| Larghezza | Comportamento | Proprietà |
|---|---|---|
| ≥ 40 rem | una riga: Casa · destinazioni · azioni | `.testata` (`flex-wrap`) |
| < 40 rem | la riga va a capo: Casa, poi destinazioni, poi azioni | idem, nessun JavaScript |

Criteri di done: a 1280 px la testata sta su una riga e non c'è nessun «Menu»; a 380 px
`document.documentElement.scrollWidth === 380`.

## 7. Testi già esistenti — si riusano **alla lettera**

Non si riscrivono, non si parafrasano: |Testo|Dove| |---|---| |«Dati non disponibili: la memoria della rete non
risponde in questo momento»|stato di ogni pagina| |«È un'informazione, non un guasto»|idem| |«Servizio non ancora
attivo»|ciò che non è pronto| |«Nessuna proposta in attesa a <Casa>.»|coda vuota| |«Non conserva dati
personali.»|piede della pagina| |Le etichette `[KB · …]` e `[Esterna · …]`|**verbatim dallo shim**, mai
ricomposte| |«orari non disponibili»|luogo senza orari|

**Divieti di contenuto** (verificati automaticamente in `T-DASH-03`): nessun imperativo, nessun «tu»/«noi», nessun
punto esclamativo, nessuna icona, nessun rosso, nessuna emoji.

## 8. Come ogni bot prova il proprio lavoro

L'anteprima è già in piedi:

```bash
# la Home dal worktree, con lo shim del worktree (hot reload su shim/app/**)
curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: trasi.lascuolaopensource.org' http://127.0.0.1:8089/
# login reale (password documentata in db/013_credenziali.sql:84)
curl -s -c /tmp/ck.txt -X POST -H 'Host: trasi.lascuolaopensource.org' -H 'Content-Type: application/json' \
  -d '{"casa":"bozzano","password":"bozzano2026!"}' http://127.0.0.1:8089/api/shim/login
```

- **Modifica a `deployment/home/**`** → si vede subito su `:8089` (mount + `no-cache`).
- **Modifica a `shim/app/**`** → `--reload` riavvia in ~1 s, non serve rebuild.
- **Suite**: `bash db/tests/run.sh` (atteso **132 PASS / 0 FAIL**) · `cd shim && python -m pytest` (atteso
  **220 passed**) · `cd flussi && python -m pytest tests -q`.
- Il venv è quello del progetto: `/root/orca/projects/onice/.venv/bin/python`.
