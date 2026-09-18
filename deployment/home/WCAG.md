# Trasi Home — verifica di accessibilità WCAG 2.1 AA

Pagina verificata: **Trasi Home** (`deployment/home/`, servita da Caddy all'indirizzo
`trasi.lascuolaopensource.org`). Data della misura: 2026-09-16. Strumenti: axe-core 4.13.0 (regole
WCAG 2.1 A/AA), misure dirette sul DOM in Chrome 150 (contrasti, dimensioni di carattere, ordine di
tabulazione, bersagli, reflow).

**Questa scheda è stata rifatta** dopo la revisione della veste (design system, `design/`): la
gerarchia delle destinazioni è cambiata, la riga «Oggi» e la coda delle proposte sono salite in una
fascia di stato in testa, ed è entrato il primo elemento non testuale della pagina — il logo della
rete. Le misure qui sotto sono quelle della pagina **attuale**, non della precedente.

**Cosa questa pagina copre e cosa no.** Qui è verificata **una sola** pagina: la Home statica, che è
un deliverable del blocco B6. La verifica WCAG delle **tre applicazioni esterne** (Onyx, Metabase,
NocoDB) è `[S2]` nel piano (§2 tagli d'emergenza, App. A V-08): **non è fatta e non è dichiarata
fatta**. Le tre app sono prodotti di terzi con interfacce complesse; il piano le colloca nella
settimana 2 con una checklist dedicata.

---

## Esito sintetico

| Verifica | Strumento | Esito |
|---|---|---|
| Violazioni WCAG 2.1 A/AA | axe-core 4.13.0 | **0 violazioni**, 0 «incomplete», 22 controlli superati |
| Contrasti (ogni coppia testo/sfondo) | misura sul DOM | **12/12 ≥ 4,5:1** (minimo misurato **6,71:1**) |
| Ordine di tabulazione | `Tab` reale, 9 pressioni | salta → Casa → Aiuto → Esci → coda → CHIEDI → MAPPA → OSSERVATORIO ✔ |
| Focus visibile | `ComputedStyle` sull'elemento attivo | **3 px + anello 6 px** su tutti gli elementi focalizzabili |
| Font di base | `ComputedStyle` su ogni nodo di testo | **16 px**; 15 px ammesso solo su etichette e note |
| Bersagli | `getBoundingClientRect` | tutti ≥ 24×24 (WCAG 2.2 · 2.5.8) |
| Reflow 320 px (1.4.10) | viewport 320 px | `scrollWidth` = 320: **nessuno scorrimento** |
| `lang="it"` | ispezione | presente, valido |

La verifica è stata ripetuta su **tutti e quattro gli stati** della pagina (dati letti, coda vuota,
coda con proposte ferme, shim che non risponde): 0 violazioni in ognuno.

---

## 1 · Percezione

### 1.1.1 Contenuto non testuale (A)

La pagina ha **un'immagine**: il logo «Case di Quartiere Brindisi» nella testata
(`assets/logo-case-di-quartiere.png`, 203×88 px nella risorsa, resa a 44 px di altezza). Ha
`alt=""`: è **decorativa**, perché accanto c'è il testo «TRASI · Rete delle Case di Quartiere di
Brindisi», che dice la stessa cosa. Ripetere il nome nell'`alt` farebbe annunciare due volte la
stessa informazione a un lettore di schermo, ed è il motivo per cui `alt=""` è la scelta corretta
qui e non una dimenticanza.

Il logo ha `width`/`height` espliciti nell'HTML: lo spazio è riservato prima del caricamento e la
testata non si muove (è anche la ragione per cui non c'è disallineamento al primo paint).

Non ci sono altre immagini, né icone, né immagini di testo: le destinazioni sono parole.
**Esito: conforme.** (Verificato da axe: 0 violazioni su `image-alt`, `svg-img-alt`.)

### 1.3.1 Informazioni e correlazioni (A) · 1.3.2 Sequenza significativa (A)

Struttura semantica: `<header>` → `<main>` con la fascia di stato (`role="status"` per «Oggi», una
`div` per la coda) → `<h1>` → le destinazioni → `<section id="aiuto">` → `<footer>`. Il selettore ha
`<label for="selettore-casa">` associata, ora **visibile** (prima era solo per i lettori di schermo:
anche chi vede ha bisogno di sapere cos'è quel menu).

**Il calendario del mese** (sotto la riga «Oggi», 2026-09-18) è una `<table class="oggi-tabella">` vera,
non una lista stilizzata: `<caption>` («Eventi di settembre 2026 a San Bao», riscritta al cambio di
Casa), `<th scope="col">` per Giorno · Ora · Evento · Dove, `<th scope="row">` sul giorno di ogni
riga. Le righe di oggi portano `aria-current="date"` **e** la parola «oggi» nella cella Giorno
(`<span class="oggi-evento-oggi">`), oltre allo sfondo incassato e al filetto: l'informazione non è
mai affidata al solo colore (1.4.1). Un mese senza eventi non nasconde la tabella ma la sostituisce
con un paragrafo esplicito («Nessun evento in programma a febbraio 2027 per …»). Sotto i 640 px la
tabella scorre in orizzontale **dentro** la sua scatola (`overflow-x: auto`), e la pagina resta a
320 px senza scorrimento (`scrollWidth === 320`, misurato).

**La disposizione non è più 2×2.** La gerarchia segue la frequenza d'uso reale: CHIEDI occupa tutta
la larghezza (titolo 36 px), MAPPA e OSSERVATORIO stanno affiancati, REGISTRA/AGGIORNA — che è
predisposto e non attivo — scende al terzo livello a tutta larghezza. Misurato sul DOM a 1280 px:

| Destinazione | Larghezza | Titolo | Nota |
|---|---|---|---|
| CHIEDI | 944 px | 36 px | destinazione principale |
| MAPPA | 462 px | 20 px | affiancata a OSSERVATORIO |
| OSSERVATORIO | 462 px | 20 px | idem |
| REGISTRA / AGGIORNA | 944 px | 20 px | spenta, dichiarata in parole |

L'ordine del DOM, quello visivo e quello di tabulazione **coincidono** (2.4.3): CHIEDI, MAPPA,
OSSERVATORIO, poi REGISTRA. La gerarchia è affidata alla **dimensione**, non al colore, quindi resta
leggibile in scala di grigi e da chi non distingue i colori.

REGISTRA/AGGIORNA non è un `<a>` (non porta da nessuna parte): è una `div` con l'etichetta «Servizio
non ancora attivo». Non è `disabled` — che lo renderebbe illeggibile e non spiegherebbe nulla.
**Esito: conforme** (axe: 0 violazioni su `list`, `label`, `heading-order`, `region`).

### 1.4.3 Contrasto minimo (AA) — ⚠️ misure reali

Misura su ogni nodo di testo visibile: colore calcolato del testo contro lo sfondo **effettivo**
(risalendo i genitori, perché `background-color` non è ereditato). Soglia 4,5:1 per il testo normale,
3:1 per il testo grande.

| Elemento | Testo | Rapporto | Soglia | Esito |
|---|---|---|---|---|
| `body` | testo corrente su carta | **15,39** | 4,5 | PASS |
| `p#oggi` | Oggi a … | **17,07** | 4,5 | PASS |
| `p.coda-testo` | 7 proposte aspettano una decisione… | **8,90** | 4,5 | PASS |
| `a.coda-azione` | Apri la coda delle proposte | **7,90** | 4,5 | PASS |
| `span.principale-titolo` | CHIEDI (36 px) | **7,90** | 3 | PASS |
| `span.destinazione-testo` | L'assistente della rete… | **17,07** | 4,5 | PASS |
| `span.marchio-nome` | TRASI su testata blu | **11,12** | 4,5 | PASS |
| `select#selettore-casa` | San Bao | **17,07** | 4,5 | PASS |
| `span.etichetta-attenzione` | Servizio non ancora attivo | **6,71** | 4,5 | PASS |
| `span.destinazione-titolo` (spenta) | REGISTRA / AGGIORNA | **7,60** | 4,5 | PASS |
| `span.destinazione-nota` | si apre con San Bao già impostata | **8,90** | 4,5 | PASS |
| `p.piede` | Trasi · rete delle Case… | **8,03** | 4,5 | PASS |
| `th.oggi-evento-giorno` | ven 18 (calendario del mese) | **17,07** | 4,5 | PASS |
| `td.oggi-evento-ora`, `td.oggi-evento-dove`, `thead th`, `caption` | 15:00 · San Bao · Giorno · Eventi di… | **8,90** | 4,5 | PASS |
| `td` della riga di oggi | testo tenue su sfondo incassato `#efede6` | **7,60** | 4,5 | PASS |
| `span.oggi-evento-oggi` | OGGI (carta su `--testata`) | **10,03** | 4,5 | PASS |

**Minimo misurato: 6,71:1** — sopra il 4,5:1 richiesto. La coppia più bassa è l'etichetta «Servizio
non ancora attivo» (testo `--sole-scuro` su `--attenzione-sfondo`): è la stessa del design system, che
la dichiara a 6,71:1.

**I tre colori di marca non portano mai testo.** Mare `#0b90cb`, terra `#cc7e5b` e sole `#f6af37`
stanno fra 1,9:1 e 3,6:1 su bianco: vivono nei filetti e negli sfondi, mentre per il testo ci sono le
varianti profonde. Non è una preferenza: un titolo in mare di marca sarebbe illeggibile.

**Nessun rosso, da nessuna parte.** In Trasi nulla è un allarme rivolto a una persona: l'attenzione è
giallo sole, e accanto c'è sempre la parola.
**Esito: conforme.** (axe: 0 violazioni su `color-contrast`.)

### 1.4.4 Ridimensionamento del testo (AA)

Il font di base è dichiarato in `html { font-size: 16px }` e tutte le dimensioni derivate usano `rem`,
quindi il testo scala con le preferenze del browser senza rompere il layout.

Misurato su **ogni** nodo di testo della pagina, il minimo è **15 px**, su nove elementi che sono
tutti etichette o note e mai testo corrente:

| Elemento | px | Cos'è |
|---|---|---|
| `label.casa-etichetta` | 15 | etichetta del selettore |
| `span.marchio-sotto` | 15 | sottotitolo della testata |
| `p.casa-nota` | 15 | nota «dati provvisori» |
| `a.azione`, `button.azione` | 15 | Aiuto ed Esci |
| `span.destinazione-nota` | 15 | nota di una destinazione |
| `span.etichetta-attenzione` | 15 | «Servizio non ancora attivo» |
| `span.esempio-glossa` | 15 | glossa dell'etichetta di provenienza |

Il testo corrente è a **16 px** (corpo, destinazioni, coda) o **17 px** (riga «Oggi»), e nessun
paragrafo scende sotto i 16. La WCAG 2.1 non fissa una dimensione minima di carattere — chiede che il
testo possa essere ingrandito al 200% senza perdita (1.4.4) e che il contrasto regga (1.4.3): qui
entrambe le cose sono verificate, e il 15 px resta su testo breve che non è fatto per essere letto di
seguito.
**Esito: conforme.**

### 1.4.10 Reflow (AA)

A 320 px di larghezza (equivalente a 400% di zoom su 1280 px) la pagina **non scorre
orizzontalmente**: `scrollWidth` 320 contro `innerWidth` 320. Misurato con viewport reale a 320 px,
leggendo `document.documentElement.scrollWidth`.

Sotto i 40 rem (640 px) MAPPA e OSSERVATORIO passano in colonna singola — affiancarli taglierebbe il
testo — e il selettore della Casa prende la larghezza disponibile (272 px su 320) senza spingere
fuori il contenitore, grazie a `min-width: 0` e `max-width: min(22rem, 100%)`. La griglia usa
`minmax(0, 1fr)` e non `1fr`: senza lo zero minimo le colonne non scendono sotto la larghezza del
contenuto, ed è esattamente il difetto trovato nella versione precedente di questa pagina (§6).
**Esito: conforme.**### 1.4.11 Contrasto non testuale (AA)

I bordi delle destinazioni (`--bordo: #8a8377` su `--superficie: #ffffff`) e i contorni dei pulsanti
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

Prova eseguita con `Tab` reale, leggendo `document.activeElement` e lo stile calcolato a ogni passo:

| # | Elemento attivo | Testo |
|---|---|---|
| 1 | `a.salta` | Salta alle destinazioni |
| 2 | `select#selettore-casa` | San Bao |
| 3 | `a.azione` | Aiuto |
| 4 | `button.azione` | Esci |
| 5 | `a#coda-azione` | Apri la coda delle proposte |
| 6 | `a#riquadro-chiedi` | CHIEDI |
| 7 | `a#riquadro-mappa` | MAPPA |
| 8 | `a#riquadro-osservatorio` | OSSERVATORIO |
| 9 | `body` | (fine del ciclo: si rientra dal primo elemento) |

REGISTRA / AGGIORNA **non è nell'ordine di tabulazione**, ed è corretto: non è un collegamento, non
porta da nessuna parte, e un elemento non attivo che si prende un `Tab` obbliga a un passaggio in più
per arrivare a quello che serve. Il suo stato è dichiarato in parole, che è raggiungibile dalla
lettura normale della pagina.

La coda delle proposte viene **prima** delle destinazioni: è l'unica cosa che può richiedere
un'attenzione, e sta in testa alla fascia di stato.

Il ciclo si chiude e riparte: **nessuna trappola**. Tutti i controlli sono raggiungibili, compresi
[Aiuto] ed [Esci]. Se la coda è vuota o lo shim non risponde, il collegamento non c'è e l'ordine
scorre direttamente alle destinazioni: non resta un elemento focalizzabile che non porta a nulla.
**Esito: conforme.**### 2.4.1 Bypass dei blocchi (A)

Un collegamento «Salta alle destinazioni» è il **primo** elemento focalizzabile e porta a
`#destinazioni`, che contiene le quattro destinazioni: salta la testata e la fascia di stato, cioè
tutto ciò che si ripete a ogni apertura. È visibile quando riceve il focus (`.salta:focus { left: 0 }`).
**Esito: conforme** (axe: 0 violazioni su `bypass`).

### 2.4.4 Scopo del collegamento (A) · 2.4.6 Intestazioni ed etichette (AA)

Ogni collegamento ha un testo che ne dichiara la destinazione: «CHIEDI», «MAPPA»,
«OSSERVATORIO», «Apri la coda delle proposte», «Aiuto», «Esci». Le intestazioni
descrivono l'argomento (`h1` = scopo della pagina, `h2` e `h3` delle destinazioni e della sezione
Aiuto). Il pulsante [Esci] ha testo visibile, non una sola icona.
**Esito: conforme.**

### 2.4.7 Focus visibile (AA) — ⚠️ misure reali

Su tutti gli elementi focalizzabili il focus calcolato è
`outline: 3px solid rgb(246, 175, 55)` (≥ 2 px richiesti) più un secondo anello
`box-shadow: rgb(4, 48, 68) 0 0 0 6px`. Il doppio anello serve perché il giallo da solo, sulla testata
blu notte, non si distingue dallo sfondo; l'anello scuro sì. Il giallo è quello del marchio
(`#f6af37`), non un giallo generico: la pagina precedente usava `#ffd400`.
**Esito: conforme.**### 2.5.3 Etichetta nel nome (A)

Il `<select>` ha `<label for="selettore-casa">Casa di riferimento</label>`, **visibile**: prima era
nascosta con la tecnica del testo ritagliato e riservata ai lettori di schermo, ma anche chi vede ha
bisogno di sapere cos'è quel menu. Le destinazioni hanno il nome come testo del collegamento («CHIEDI»,
«MAPPA», «OSSERVATORIO»), il `select` e i pulsanti hanno testo visibile.
**Esito: conforme** (axe: 0 violazioni su `label`, `select-name`, `button-name`).

---

## 3 · Comprensibilità

### 3.1.1 Lingua della pagina (A) · 3.1.2 Lingua delle parti (AA)

`<html lang="it">` e tutto il contenuto è in italiano. Le poche parole straniere sono nomi propri
(Metabase, NocoDB, Onyx, OpenStreetMap). **Esito: conforme.**

### 3.2.1 Al focus (A) · 3.2.2 All'input (A)

Nessun cambio di contesto automatico: cambiare Casa nel selettore riscrive gli `href` delle destinazioni e
aggiorna la riga «Oggi», ma **non naviga** e non apre finestre. Il focus resta dov'è.
Il pulsante [Esci] naviga solo perché è un `<button type="submit">` dentro un `<form>`: è un'azione
esplicita dell'operatore, non un cambio di contesto inatteso.
**Esito: conforme.**

### 3.3.1 Identificazione dell'errore (A) · 3.3.2 Etichette o istruzioni (A)

L'unico «errore» possibile è la riga «Oggi» che non riceve risposta: è comunicato in testo semplice
(«Dati non disponibili: la memoria della rete non risponde in questo momento.»), seguito da
«È un'informazione, non un guasto: le destinazioni qui sotto funzionano.» Mai un codice o un
messaggio tecnico, e mai solo un colore (c'è anche il filetto laterale, ma il testo basta da solo).
La sezione Aiuto spiega cosa significa.

**Quando la lettura fallisce, anche la coda sparisce.** Non sapendo quante proposte aspettano, la
pagina **non** dice «Nessuna proposta in attesa»: sarebbe un'informazione falsa, e l'operatore
potrebbe non controllare una coda che ha davvero proposte ferme. Sparire è più onesto che dire una
cosa non vera — ed è la stessa scelta già fatta per il numero durante la lettura, quando il
contenitore è nascosto per non mostrare il conteggio della Casa precedente.
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
di oggi in corso…» al testo (o a «Dati non disponibili») è annunciato senza rubare il focus. L'esito
dell'uscita è anch'esso un `role="status"`.

La coda delle proposte e il calendario del mese **non** sono regioni live: cambiano insieme alla riga
che è già annunciata, e due annunci simultanei per un solo cambiamento di Casa sarebbero rumore. Il
calendario si nasconde durante la lettura e quando la lettura fallisce (la riga «Oggi» dice già «Dati
non disponibili»). Il conteggio sul riquadro OSSERVATORIO è testo normale, letto quando ci si arriva.
**Esito: conforme.**

---

## 5 · Come ripetere la verifica

```bash
# 1 · La Home e la rotta della riga «Oggi» (Caddy sceglie il sito dall'header Host)
curl -s -o /dev/null -w '%{http_code}\n' \
  -H 'Host: trasi.lascuolaopensource.org' http://127.0.0.1:8088/            # atteso: 200
curl -s -H 'Host: trasi.lascuolaopensource.org' \
  'http://127.0.0.1:8088/api/shim/v1/u/rete@trasi.local/oggi?casa=bozzano'  # atteso: JSON
```

```bash
# 2 · axe-core, contrasti, caratteri, tabulazione, bersagli — sulla pagina servita
cd /tmp && npm install axe-core@4
# in un browser headless (Chrome 150 in questo ambiente):
#   pagina  = http://127.0.0.1:8088/  con l'header Host (v. sotto)
#   script  = /tmp/axebanco/node_modules/axe-core/axe.min.js
#   axe.run(document, { runOnly: { type: "tag",
#              values: ["wcag2a","wcag2aa","wcag21a","wcag21aa"] } })
```

**Come si guarda la pagina su questa macchina.** Due vincoli, entrambi verificati, e vale la pena
conoscerli perché fanno perdere tempo:

1. Caddy sceglie il sito dall'header `Host`: su un host che non conosce risponde **200 con corpo
   vuoto**, non 404. Quindi `http://127.0.0.1:8088/` da un browser non mostra la pagina, e sembra
   rotta quando invece non lo è.
2. Il dominio pubblico, da qui, risolve **solo in IPv6** e questa macchina non ha connettività IPv6
   verso Cloudflare: il browser non lo raggiunge affatto.

Per la verifica visiva serve quindi un banco che serva i file veri e inoltri `/api/shim/*` al Caddy
vero portandogli l'header `Host`: è lo stesso percorso della riga «Oggi», con la chiave iniettata dal
proxy. `curl` con `-H 'Host: …'` è invece sufficiente per tutte le misure che non richiedono un
browser.

## 5b · La pagina «Mappa delle Case» (`mappa.html`, aggiunta il 2026-09-18)

Seconda pagina pubblica, stessa testata e stesso `style.css` della Home (+ `mappa.css`, Leaflet vendorizzato
BSD-2 in `vendor/leaflet/`). Misure sul banco locale (file veri, `/api/shim/*` verso lo shim del ramo), Chrome
headless, axe-core 4.10.2 regole WCAG 2.1 A/AA: **0 violazioni** (26 regole passate) su `mappa.html`; la Home
dopo l'estrazione di `casa.js` resta a 0 violazioni.

**Struttura semantica** (1.3.1): `<header>` (stesso selettore `#selettore-casa` con `<label>`) → `<main>` →
`<h1>` «Le dieci Case della rete» → riga di stato `role="status" aria-live="polite"` («Lettura in corso…» →
«10 Case · centrata su San Bao») → la tela `<div id="mappa-tela" tabindex="0" role="region" aria-label…
aria-describedby="mappa-attribuzione">` → attribuzione OSM **in parole** (`<p>`, nel flusso, mai dietro il
controllo di Leaflet) → riga «Sfondo della mappa non disponibile…» (`role="status"`, `hidden` finché non serve)
→ legenda `<ul aria-label="Legenda">` in parole → `<section aria-labelledby>` «Elenco delle Case» con un `<ol>`
(stesse Case, stesso ordine della mappa: prima la Casa scelta, poi per distanza) → `<footer>`.

**Tastiera** (2.1.1, 2.4.3, 2.4.7): ordine misurato con Tab dal selettore → «Home» → «Area operatore» → la
tela (annunciata: «Mappa delle dieci Case della rete. L'elenco sotto è la stessa informazione…») → i due
bottoni di zoom di Leaflet («Avvicina la mappa», «Allontana la mappa») → i dieci bottoni «Mostra <Casa> sulla
mappa» → piede. **I pin non sono mai nel percorso** (`keyboard: false`, 0 marcatori con `tabindex ≥ 0`
misurati): l'equivalente è l'elenco. Enter su un bottone seleziona la Casa, l'elenco si riordina e il focus
resta sul bottone della stessa Casa (misurato). Focus visibile su tela e bottoni (`outline 3px --focus`).

**Non solo colore** (1.4.1): la Casa scelta ha l'anello sul pin **e** la parola «la Casa scelta» + `aria-current`
nella voce; «orari provvisori», «coordinate stimate», «dati provvisori» sono parole; il badge di provenienza è
testo monospazio verbatim.

**Contrasti** (1.4.3), colori calcolati: nome della voce `#1c1c1a` su bianco **17,07**; testo tenue `#4a4a46`
**8,90**; chip «LA CASA SCELTA» carta su `--testata` **10,03**; badge `--kb-testo` `#07577b` su bianco
**7,90** (6,98 sulla voce scelta, sfondo `--azione-sfondo-hover`); note `--attenzione-testo` su `--attenzione-sfondo` **6,71** (già misurato in §1.4.3); pin `--testata`
su tile chiari: il pin non porta testo informativo (il nome è nell'elenco), il carattere è 22 px.

**Stati dichiarati**: shim fermo → riga «Dati non disponibili: la memoria della rete non risponde in questo
momento. È un'informazione, non un guasto.», tela e attribuzione nascoste, pagina navigabile; tile bloccati →
«Sfondo della mappa non disponibile: le Case e l'elenco restano leggibili.», 10 pin e 10 voci intatti (misurato
bloccando `tile.openstreetmap.org` con cache disattivata: con la cache attiva i tile già scaricati non
producono errore, ed è corretto); `?casa=` non valido → Casa predefinita, nessun testo tecnico a schermo.

**Reflow** (1.4.10): a 360 px `scrollWidth === 360`, 10 pin; la tela scende a 20 rem. Screenshot in
`evidenze/mappa-{1280,768,360,tile-bloccati,shim-fermo,da-home-molo12}.png`.

**Domini contattati**: `127.0.0.1` (la pagina e `/api/shim/*`) e **`tile.openstreetmap.org`** (lo sfondo).
Nessun CDN, nessun font remoto — misurato registrando ogni richiesta della pagina.
## 5c · La copertina della Home (aggiunta il 2026-09-18)

In testa a `<main>` una `<section class="copertina" aria-labelledby>`: occhiello «Trasi», `<h1>` «Il portierato
pubblico di Brindisi» e tre paragrafi di presentazione del servizio (testo del progetto, verbatim; terza persona,
nessun imperativo). Sola tipografia (Commissioner locale): titolo `clamp(2rem, 4.2vw, 3.5rem)` — 53,8 px a 1280,
32 px a 360 —, testo `clamp(1.125rem, 1.5vw, 1.375rem)` (19,2 px / 18 px), interlinea 1,55, misura di lettura
36 rem. Il vecchio `<h1>` «La porta della rete…» è ora `<h2>`: una sola `<h1>` per pagina (1.3.1). Contrasti:
titolo `--testata` su carta **11,12**; testo `--testo` **15,39**; chiusa `--testo-tenue` **8,90** (già misurati
in §1.4.3). Reflow: a 360 px `scrollWidth === 360`. axe-core 4.10.2 WCAG 2.1 A/AA sulla Home → **0 violazioni**.
Screenshot: `evidenze/home-copertina-{1280,360}.png`.

## 5d · L'area operatore: la sezione Attrezzoteca (aggiornata il 2026-09-18)

Quattro difetti corretti in `operatore.html`/`operatore.js` (vedi PR movimenti bidirezionali), con verifica a
scontrino (stato, focus, contrasti calcolati):

- **Movimenti in attesa**: i pulsanti («Conferma ricezione» per chi riceve, «Conferma prestito» per chi presta,
  «Rifiuta» per entrambi) compaiono **solo** sulla voce che questa Casa deve decidere — `decide_casa_slug` arriva
  dalla vista del database e la UI lo confronta con la Casa della sessione. Chi ha proposto legge «In attesa della
  decisione di <casa>» come testo normale. Prima il pulsante «Conferma ricezione» compariva a entrambe, e la
  cedente riceveva un rifiuto del database **dopo** aver premuto.
- **Moduli in linea** (2.1.1): niente più `window.prompt` (finestra modale del browser, non annunciata). Il
  «Proponi prestito a…» e il «Chiedi in prestito» aprono un `<form>` in linea **nella riga** (`<tr>` con
  `background` incassato): `<select>` delle Case (per il prestito, senza la propria — il CHECK di db/014 non può
  scattare) e `<input type="date">` con `min` = oggi; `Annulla` ed `Esc` chiudono e riportano il **focus** al
  pulsante che ha aperto; un solo modulo aperto per volta. Etichette associate con `for`.
- **Aggiornamento automatico** (4.1.3): la riga `role="status" aria-live="polite"` «Inventario aggiornato alle
  HH:MM» dice quando è avvenuta l'ultima lettura; il timer di 30 s vive **solo** con la linguetta «Attrezzoteca»
  visibile e `document.visibilityState === "visible"`, e si spegne altrimenti (nessuna interrogazione a pagina
  chiusa o in secondo piano); al ritorno del focus/visibilità (l'operatore torna dalla scheda di Onyx) rilettura
  immediata; bottone «Aggiorna» esplicito accanto alla ricerca. Il termine di ricerca corrente è mantenuto nelle
  riletture.
- **Chiedi in prestito** (db/033): sugli oggetti di altre Case con disponibilità > 0 il pulsante «Chiedi in
  prestito» apre lo stesso modulo in linea; a disponibilità 0 solo il testo «Non disponibile ora», senza
  pulsante. Contrasti: etichette `--testo-tenue` su `--superficie-incassata` **7,60** (§1.4.3), riga di stato
  tenue su bianco **8,90**, riga di attenzione `--attenzione-*` **6,71**.

## 6 · Difetti reali trovati durante questa verifica

**Della versione precedente (riportati perché sono lezioni, non storia):**

1. **Scorrimento orizzontale a 320 px** (WCAG 1.4.10 Reflow) — il `<select>` della Casa non si
   restringeva sotto la voce più lunga e portava la pagina a 329 px su 305 disponibili. Corretto con
   `min-width: 0`. Trovato **solo** perché la misura è stata fatta a 320 px: a 1280 px la pagina è
   indistinguibile da una corretta. La protezione è rimasta (`minmax(0, 1fr)`, `min-width: 0`).
2. **`aria-describedby` che puntava a un id inesistente** sul `<select>` — un riferimento rotto, che
   axe non segnala come violazione ma che i lettori di schermo annunciano come descrizione vuota.

**Della revisione della veste (design system):**

3. **La coda diceva «Nessuna proposta in attesa» quando la lettura falliva.** Con lo shim che non
   risponde, la pagina affermava che la coda era vuota: un'informazione **falsa**, e della specie
   peggiore — quella che induce a non controllare. Ora, se la lettura fallisce, la coda sparisce.
   Trovato provando lo stato «shim fermo», non leggendo il codice.
4. **La riga «Oggi» e la coda potevano nominare Case diverse.** Il `testo` della riga arriva dalla
   vista e nomina la Casa della **risposta**; la coda la ricavava dal selettore. Se lo shim risponde
   su una Casa diversa da quella richiesta (accade quando lo slug non è riconosciuto e lo shim ricade
   sull'identità), le due righe si contraddicevano. Ora entrambe usano `dati.casa`, una sola fonte.
5. **Un carattere cirillico in una classe CSS.** `esempio-glossа` conteneva una `а` di U+0430: la
   regola non si applicava e la glossa restava senza stile. Invisibile a occhio, trovato
   confrontando i codepoint dei file.
6. **La pagina superava il tetto di 30 KB** (35.275 B) e il logo da solo ne pesava 67 KB contro un
   limite di 30. Il logo è servito a 88 px di altezza — il doppio dei 44 px resi, per gli schermi
   retina — invece che a 361 px: **8,8 KB invece di 67**, l'87% in meno. La pagina è rientrata a
   30.698 B, e i commenti sono stati ridotti **senza** perdere le motivazioni: quelle che stavano già
   in un documento (il design system, l'analisi IA) ora lo citano invece di ripeterlo.

---

## 7 · Cosa NON è verificato (dichiarato, non omesso)

- **Onyx, Metabase, NocoDB**: verifica WCAG **rinviata a S2** dal piano (§2, App. A V-08). Non è
  stata eseguita qui e non va considerata fatta.
- **Lettori di schermo reali** (NVDA, JAWS, VoiceOver): non disponibili in questo ambiente. La
  verifica è strutturale (ruoli, nomi, stati, `aria-live`) e con axe, non con un lettore vero.
- **Utenti reali**: il piano prevede la sessione con operatori in B7 (US-01…US-08).
- **Contrasto sui colori di sistema del `<select>` aperto**: la tendina è resa dal sistema
  operativo e non è misurabile dal DOM; il controllo chiuso è quello misurato al punto 1.4.3.
- **Il logo come immagine di marca**: il manuale di identità visiva lo distribuisce come PNG e in
  Janna LT Bold, un font che non è disponibile come webfont libero. Il logo resta quindi un'immagine
  raster servita a 88 px per gli schermi retina; se arriva il file vettoriale, va sostituito.
- **Zoom 200%**: verificato indirettamente dal reflow a 320 px (che è la stessa condizione in termini
  di layout) e dal fatto che tutte le misure sono in `rem` con base 16 px dichiarata. La misura
  esplicita a zoom 200% è stata fatta nella versione precedente della pagina con
  `Emulation.setDeviceMetricsOverride`; con la nuova veste non è stata ripetuta con lo stesso
  strumento, e non è dichiarata come rieseguita.

## 8 · Correzioni Home e font (18 settembre 2026)

- Home con sidebar condivisa, menu comprimibile, Casa, Aiuto ed Esci. Copertina e paragrafi allineati alla larghezza delle altre sezioni; tolto il filetto accentuato di «Oggi».
- Commissioner: corretto il range `wght` a 30–220 e tutti i pesi nelle tre pagine; corpo Regular 82, titoli Bold 148. I pesi 82/106/126/148/185/220 producono ora sei larghezze distinte nel browser, anziché convergere su Black.
- Verifica visiva sull'istanza a 1440×900 e 360×800: copertina e destinazioni larghe rispettivamente 944 e 328 px, senza overflow orizzontale. Sidebar 240→72 px e `aria-expanded` aggiornato; dropdown Casa aperto correttamente sopra il selettore desktop.
- Queste verifiche non costituiscono una nuova certificazione WCAG completa; i limiti delle sezioni precedenti restano dichiarati.
