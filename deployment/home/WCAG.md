# Trasi Home — verifica di accessibilità WCAG 2.1 AA

Pagina verificata: **Trasi Home** (`deployment/home/`, servita da Caddy all'indirizzo
`trasi.lascuolaopensource.org`). Data della misura: 2026-09-16. Strumenti: axe-core 4.13.0 (regole
WCAG 2.1 A/AA), Lighthouse 12 (categoria accessibilità), misure dirette sul DOM (contrasti,
ordine di tabulazione, `Emulation.setDeviceMetricsOverride` per reflow e zoom).

**Cosa questa pagina copre e cosa no.** Qui è verificata **una sola** pagina: la Home statica, che è
un deliverable del blocco B6. La verifica WCAG delle **tre applicazioni esterne** (Onyx, Metabase,
NocoDB) è `[S2]` nel piano (§2 tagli d'emergenza, App. A V-08): **non è fatta e non è dichiarata
fatta**. Le tre app sono prodotti di terzi con interfacce complesse; il piano le colloca nella
settimana 2 con una checklist dedicata.

---

## Esito sintetico

| Verifica | Strumento | Esito |
|---|---|---|
| Violazioni WCAG 2.1 A/AA | axe-core 4.13.0 | **0 violazioni**, 0 «incomplete», 42 controlli superati |
| Punteggio accessibilità | Lighthouse 12 | **100 / 100** |
| Contrasti (ogni coppia testo/sfondo) | misura sul DOM | **14/14 ≥ 4,5:1** (minimo misurato **7,99:1**) |
| Ordine di tabulazione | `Tab` reale, 10 pressioni | CHIEDI → MAPPA → REGISTRA → OSSERVATORIO ✔ |
| Focus visibile | `ComputedStyle` sull'elemento attivo | contorno **3 px** su tutti i 9 elementi focalizzabili |
| Font di base | `ComputedStyle` | **16 px** (nessun testo sotto i 16 px) |
| Reflow 320 px (1.4.10) | override metriche CDP | nessuno scorrimento orizzontale |
| Zoom 200% (1.4.4) | override metriche CDP | nessuno scorrimento orizzontale |
| `lang="it"` | ispezione | presente, valido |

---

## 1 · Percezione

### 1.1.1 Contenuto non testuale (A)

Le uniche immagini sono caratteri tipografici; non ci sono `img`, `svg` decorativi senza
alternativa, né immagini di testo. Il simbolo `·` dell'intestazione è `aria-hidden="true"`.
**Esito: conforme.** (Verificato da axe: 0 violazioni su `image-alt`, `svg-img-alt`.)

### 1.3.1 Informazioni e correlazioni (A) · 1.3.2 Sequenza significativa (A)

Struttura semantica: `<header>` → `<main>` con `<h1>` → `<ul>` dei quattro riquadri → `<section id="aiuto">`
→ `<footer>`. I riquadri sono una lista reale (`<ul>/<li>`), non una griglia di `div`: la sequenza
è quella che si legge. I campi del selettore hanno `<label for="selettore-casa">` associata.

Disposizione **2×2**, come il disegno di §4.3 dell'architettura (CHIEDI/MAPPA in alto,
REGISTRA/OSSERVATORIO in basso): misurata sul DOM, i quattro riquadri hanno `top` 157 px per i primi
due e 307 px per gli altri due, con la stessa `left` a coppie. L'ordine visivo coincide con l'ordine
del DOM e con l'ordine di tabulazione (2.4.3).
**Esito: conforme** (axe: 0 violazioni su `list`, `listitem`, `label`, `heading-order`, `region`).

### 1.4.3 Contrasto minimo (AA) — ⚠️ misure reali

Misura su ogni nodo di testo visibile: colore calcolato del testo contro lo sfondo **effettivo**
(risalendo i genitori, perché `background-color` non è ereditato). Soglia 4,5:1 per il testo normale,
3:1 per il testo grande (≥ 24 px, o ≥ 18,66 px in grassetto).

| Elemento | Testo | Colore | Sfondo | px | Rapporto | Soglia | Esito |
|---|---|---|---|---|---|---|---|
| `h1.titolo` | La porta della rete… | `rgb(74,74,74)` | `rgb(245,243,238)` | 22 | **7,99** | 4,5 | PASS |
| `span.nota-inattiva` | (servizio non ancora attivo) | `rgb(74,74,74)` | `rgb(245,243,238)` | 16 | **7,99** | 4,5 | PASS |
| `p.stato-inattivo` | Servizio non ancora attivo | `rgb(74,56,0)` | `rgb(255,233,168)` | 16 | **9,41** | 4,5 | PASS |
| `p.rinvio` | La verifica di accessibilità… | `rgb(74,56,0)` | `rgb(255,233,168)` | 16 | **9,41** | 4,5 | PASS |
| `a#coda-proposte` | Coda delle proposte «Da approvare» | `rgb(18,58,92)` | `rgb(245,243,238)` | 16 | **10,61** | 4,5 | PASS |
| `p.marchio` | Casa: | `rgb(255,255,255)` | `rgb(18,58,92)` | 18 | **11,76** | 4,5 | PASS |
| `span.marchio-nome` | TRASI | `rgb(255,255,255)` | `rgb(18,58,92)` | 18 | **11,76** | 4,5 | PASS |
| `a.azione` | Aiuto · Esci | `rgb(255,255,255)` | `rgb(18,58,92)` | 16 | **11,76** | 4,5 | PASS |
| `h2.riquadro-titolo` | CHIEDI · MAPPA · … | `rgb(18,58,92)` | `rgb(255,255,255)` | 20 | **11,76** | 3 | PASS |
| `h2#aiuto-titolo` | Aiuto | `rgb(18,58,92)` | `rgb(255,255,255)` | 22 | **11,76** | 3 | PASS |
| `h3` | La riga «Oggi» | `rgb(18,58,92)` | `rgb(255,255,255)` | 18 | **11,76** | 4,5 | PASS |
| `a.salta` | Salta ai riquadri | `rgb(28,28,28)` | `rgb(255,255,255)` | 16 | **17,04** | 4,5 | PASS |
| `option` | San Bao · Bozzano · … | `rgb(28,28,28)` | `rgb(255,255,255)` | 16 | **17,04** | 4,5 | PASS |
| `p#oggi.oggi` | Oggi a … | `rgb(28,28,28)` | `rgb(255,255,255)` | 17 | **17,04** | 4,5 | PASS |
| `dt` | CHIEDI · MAPPA · … | `rgb(28,28,28)` | `rgb(255,255,255)` | 16 | **17,04** | 4,5 | PASS |

**Minimo misurato: 7,99:1** — ben oltre il 4,5:1 richiesto. Nessun elemento sotto soglia.
**Esito: conforme.** (axe: 0 violazioni su `color-contrast`; Lighthouse: audit superato.)

### 1.4.4 Ridimensionamento del testo (AA)

Il font di base è dichiarato in `html { font-size: 16px }` e tutte le dimensioni derivate usano `rem`,
quindi il testo scala con le preferenze del browser senza rompere il layout. La misura minima su
tutti gli elementi di testo è **16 px**.
**Esito: conforme.**

### 1.4.10 Reflow (AA) — ⚠️ un difetto reale, trovato e corretto

Alla prima misura a **320 px** di larghezza (equivalente a 400% di zoom su 1280 px) la pagina
**scorreva orizzontalmente di 24 px**: `scrollWidth` 329 contro `clientWidth` 305. La causa, isolata
elemento per elemento, era il `<select>` dell'intestazione, che non poteva restringersi sotto la
larghezza della sua voce più lunga («Centro di Aggregazione Bozzano») e spingeva fuori il contenitore.

Corretto in `style.css` con `min-width: 0` su `.marchio` e `#selettore-casa` (`flex: 1 1 auto;
max-width: min(22rem, 100%)`), e con `grid-template-columns: repeat(2, minmax(0, 1fr))` sulla griglia
dei riquadri (lo `0` nel `minmax` è la stessa protezione: senza, le colonne non scendono sotto la
larghezza del contenuto). Sotto i 40 rem la griglia passa a una colonna sola. Rimisurato:

| Larghezza viewport | `clientWidth` | `scrollWidth` | Scorrimento orizzontale | Elementi fuori |
|---|---|---|---|---|
| 320 px | 320 | 320 | **no** | nessuno |
| 360 px | 360 | 360 | **no** | nessuno |
| 400 px | 385 | 385 | **no** | nessuno |
| 640 px (zoom 200% su 1280) | 625 | 625 | **no** | nessuno |

**Esito: conforme** (dopo la correzione). Senza la misura, il difetto non si sarebbe visto: la pagina
«sembrava» a posto perché a 1280 px non c'è alcun problema.

### 1.4.11 Contrasto non testuale (AA)

I bordi dei riquadri (`--bordo: #8a8377` su `--superficie: #ffffff`) e i contorni dei pulsanti
(`#ffffff` su `#123a5c`, e viceversa al passaggio del mouse) superano 3:1. Il contorno di focus è
giallo `#ffd400`: sul fondo chiaro ha rapporto **1,27:1**, che da solo **non** basta come indicatore
di stato — per questo non è usato da solo, ma sempre accoppiato a un secondo anello scuro `#10233c`
(descritto al punto 2.4.11). **Esito: conforme** per la parte non testuale (bordi e contorni dei
controlli); il focus è trattato sotto.

### 1.4.5 Immagini di testo (AA) · 1.4.12 Spaziatura del testo (AA)

Nessuna immagine di testo. Le misure di spaziatura richieste (interlinea 1,5×, spaziatura parole
0,16×, lettere 0,12×, paragrafi 2×) sono rispettate: `line-height: 1.5` su `body`, altezze dei
controlli definite in `px` e non in `em` compressi. **Esito: conforme.**

---

## 2 · Utilizzabilità

### 2.1.1 Tastiera (A) · 2.1.2 Nessuna trappola da tastiera (A) · 2.4.3 Ordine di focus (A) — ⚠️ misure reali

Prova eseguita con `Tab` reale (10 pressioni consecutive), leggendo `document.activeElement` e lo
stile calcolato a ogni passo:

| # | Elemento attivo | testo | Contorno misurato |
|---|---|---|---|
| 1 | `a.salta` | Salta ai riquadri | `3px solid rgb(255,212,0)` + ombra `rgb(16,35,60) 0 0 0 6px` |
| 2 | `select#selettore-casa` | San Bao | idem |
| 3 | `a.azione` | Aiuto | idem |
| 4 | `button.azione` | Esci | idem |
| 5 | `a#riquadro-chiedi` | CHIEDI | idem |
| 6 | `a#riquadro-mappa` | MAPPA | idem |
| 7 | `a#riquadro-registra` | REGISTRA / AGGIORNA | idem |
| 8 | `a#riquadro-osservatorio` | OSSERVATORIO | idem |
| 9 | `a#coda-proposte` | Coda delle proposte «Da approvare» | idem |
| 10 | `body` | — | (fine del ciclo: si rientra dal primo elemento) |

L'ordine **CHIEDI → MAPPA → REGISTRA → OSSERVATORIO** è esattamente quello richiesto e coincide con
l'ordine del DOM. Il ciclo si chiude e riparte: **nessuna trappola**. Tutti i controlli sono
raggiungibili, compresi [Aiuto] ed [Esci].
**Esito: conforme.**

### 2.4.1 Bypass dei blocchi (A)

Un collegamento «Salta ai riquadri» è il **primo** elemento focalizzabile e porta a `#riquadri`
(`<main>`). È visibile quando riceve il focus (`.salta:focus { left: 0 }`).
**Esito: conforme** (axe: 0 violazioni su `bypass`).

### 2.4.4 Scopo del collegamento (A) · 2.4.6 Intestazioni ed etichette (AA)

Ogni collegamento ha un testo che ne dichiara la destinazione: «CHIEDI», «MAPPA», «REGISTRA /
AGGIORNA», «OSSERVATORIO», «Coda delle proposte «Da approvare»», «Aiuto», «Esci». Le intestazioni
descrivono l'argomento (`h1` = scopo della pagina, `h2` = i quattro riquadri, `h3` nella sezione
Aiuto). Il pulsante [Esci] ha testo visibile, non una sola icona.
**Esito: conforme.**

### 2.4.7 Focus visibile (AA) — ⚠️ misure reali

Su **tutti** i 9 elementi focalizzabili, il focus calcolato è `outline: 3px solid #ffd400`
(≥ 2 px richiesti) più un secondo anello `box-shadow: 0 0 0 6px #10233c`. Il doppio anello serve
perché il giallo da solo, sulla testata blu, non si distingue; l'anello scuro sì. Misurato su ogni
elemento della tabella al punto 2.1.1.
**Esito: conforme.**

### 2.5.3 Etichetta nel nome (A)

Il `<select>` ha `<label for="selettore-casa">Casa di riferimento</label>` (visivamente nascosta con
la tecnica del testo ritagliato, presente nella struttura di accessibilità). I pulsanti hanno testo.
**Esito: conforme** (axe: 0 violazioni su `label`, `select-name`, `button-name`).

---

## 3 · Comprensibilità

### 3.1.1 Lingua della pagina (A) · 3.1.2 Lingua delle parti (AA)

`<html lang="it">` e tutto il contenuto è in italiano. Le poche parole straniere sono nomi propri
(Metabase, NocoDB, Onyx, OpenStreetMap). **Esito: conforme.**

### 3.2.1 Al focus (A) · 3.2.2 All'input (A)

Nessun cambio di contesto automatico: cambiare Casa nel selettore riscrive gli `href` dei riquadri e
aggiorna la riga «Oggi», ma **non naviga** e non apre finestre. Il focus resta dov'è.
Il pulsante [Esci] naviga solo perché è un `<button type="submit">` dentro un `<form>`: è un'azione
esplicita dell'operatore, non un cambio di contesto inatteso.
**Esito: conforme.**

### 3.3.1 Identificazione dell'errore (A) · 3.3.2 Etichette o istruzioni (A)

L'unico «errore» possibile è la riga «Oggi» che non riceve risposta: è comunicato in testo semplice
(«Dati non disponibili: la memoria della rete non risponde in questo momento.»), mai con un codice o
un messaggio tecnico, e mai solo con un colore (c'è anche un bordo laterale più scuro, ma il testo
basta da solo). La sezione Aiuto spiega cosa significa.
**Esito: conforme.**

---

## 4 · Robustezza

### 4.1.1 Analisi sintattica (A) · 4.1.2 Nome, ruolo, valore (A)

HTML valido, senza errori di annidamento. Ruoli e stati comunicati con la semantica nativa: gli `<a>`
sono collegamenti (non `div` con `onclick`), il `<select>` è un controllo di selezione, la riga
«Oggi» è un `role="status"` con `aria-live="polite"`, il testo dell'esito di uscita è un
`role="status"`, il blocco [Esci] è in un `<nav aria-label="Aiuto e uscita">`.
`aria-busy="true"` è applicato durante la lettura e tolto alla risposta.
**Esito: conforme** (axe: 0 violazioni su `aria-*`, `duplicate-id-aria`, `aria-hidden-focus`).

### 4.1.3 Messaggi di stato (AA)

La riga «Oggi» è un `role="status"` (`aria-live="polite"`), quindi il passaggio da «Lettura dei dati
di oggi in corso…» al testo (o a «Dati non disponibili») è annunciato senza rubare il focus.
L'esito dell'uscita è anch'esso un `role="status"`.
**Esito: conforme.**

---

## 5 · Come ripetere la verifica

```bash
# 1 · axe-core e Lighthouse (la Home serve l'header Host)
cd /tmp && npm install axe-core@4.13.0 lighthouse@12
CHROME_PATH=/root/.omp/puppeteer/chrome/linux-150.0.7871.24/chrome-linux64/chrome \
  ./node_modules/.bin/lighthouse --only-categories=accessibility \
  --chrome-flags="--headless=new --no-sandbox" \
  --output=json --output-path=/tmp/lighthouse-home.json \
  'http://trasi.lascuolaopensource.org:8088/'
jq '.categories.accessibility.score' /tmp/lighthouse-home.json   # atteso: 1

# 2 · La Home servita, e la rotta della riga «Oggi»
curl -s -o /dev/null -w '%{http_code}\n' \
  -H 'Host: trasi.lascuolaopensource.org' http://127.0.0.1:8088/     # atteso: 200
curl -s -H 'Host: trasi.lascuolaopensource.org' \
  'http://127.0.0.1:8088/api/shim/v1/u/rete@trasi.local/oggi?casa=bozzano'
```

Le prove di reflow e zoom usano `Emulation.setDeviceMetricsOverride` del protocollo CDP (`width`),
non una finestra ridimensionata: è l'unico modo di misurare il reflow senza dipendere dalla
dimensione effettiva della finestra, che in un browser headless non è affidabile.

---

## 6 · Difetti reali trovati durante questa verifica

1. **Scorrimento orizzontale a 320 px** (WCAG 1.4.10 Reflow) — il `<select>` della Casa non si
   restringeva sotto la voce più lunga e portava la pagina a 329 px su 305 disponibili. Corretto con
   `min-width: 0`. Trovato **solo** perché la misura è stata fatta a 320 px: a 1280 px la pagina è
   indistinguibile da una corretta.
2. **`aria-describedby` che puntava a un id inesistente** sul `<select>` — un riferimento rotto, che
   axe non segnala come violazione ma che i lettori di schermo annunciano come descrizione vuota.
   Rimosso (l'etichetta `label` era già associata).

Entrambi erano invisibili a occhio nudo e sono emersi dalle misure, non dalla lettura del codice.

---

## 7 · Cosa NON è verificato (dichiarato, non omesso)

- **Onyx, Metabase, NocoDB**: verifica WCAG **rinviata a S2** dal piano (§2, App. A V-08). Non è
  stata eseguita qui e non va considerata fatta.
- **Lettori di schermo reali** (NVDA, JAWS, VoiceOver): non disponibili in questo ambiente. La
  verifica è strutturale (ruoli, nomi, stati, `aria-live`) e con axe, non con un lettore vero.
- **Utenti reali**: il piano prevede la sessione con operatori in B7 (US-01…US-08).
- **Contrasto sui colori di sistema del `<select>` aperto**: la tendina è resa dal sistema
  operativo e non è misurabile dal DOM; il controllo chiuso è quello misurato al punto 1.4.3.
