# Trasi — design system

**Trasi** è lo strumento digitale del *Portierato di Quartiere* della **Rete delle Case di Quartiere
di Brindisi** (PN Metro Plus e Città Medie Sud 2021-2027, BR5.4.11.1a). Lo usano **operatori
sociali**, non tecnici: l'operatore sta allo sportello con una persona davanti, poco tempo, e deve
capire dove mandarla, con quale informazione, e stampare un promemoria.

Il prodotto è una **shell autenticata** con tre pagine pubblicate. La Casa dell'operatore è già impostata
all'accesso.

| Pagina pubblicata | Cosa apre | Cosa ci fa l'operatore |
|---|---|---|
| **Home** | la conversazione con l'assistente | cerca una risposta per la persona allo sportello |
| **Osservatorio** | la mappa e l'elenco dei luoghi | legge ciò che la rete conosce e ciò che è stato trovato fuori |
| **Account** | le otto sezioni della Casa | legge i dati, registra una proposta e segue la coda |

## I due principi che danno forma a tutto

1. **Mai senza fonte.** Ogni informazione porta un'etichetta di provenienza, di due tipi:
   `[KB · Rete delle Case di Quartiere · agg. 15/09/2026 · affidabilità 2]` (la rete lo sa) oppure
   `[Esterna · OpenStreetMap contributors (ODbL) · consultata 02:21 · non verificata dalla rete]`
   (trovato fuori). Le stringhe sono composte dal servizio (`shim/app/badge.py`) e si citano verbatim.
2. **L'umano decide.** Il sistema non modifica la memoria della rete da solo: nasce una **proposta**
   che una persona approva. Nessun testo dell'interfaccia dà ordini a nessuno.

## Vincoli non negoziabili (valgono anche per il design)

- **WCAG 2.1 AA**: contrasto testo ≥ 4,5:1, focus sempre visibile, tutto da tastiera, base ≥ 16 px.
- **Zero dipendenze esterne**: nessun CDN, nessun font remoto e nessun carattere aggiuntivo da scaricare; il testo usa lo stack di sistema.
- **Peso**: la pagina reale resta leggera nel codice e non scarica un font dedicato.
- **Nessun dato personale**: l'unica cosa conservata è lo slug della Casa nel browser.
- **Italiano semplice**, nessun imperativo verso le persone.

## Fonti di questo design system

- **Repository**: `lascuolaopensource/trasi`, ramo `main` — vedi `github.md` per la mappa
  schermata → file. File letti: `deployment/home/{index.html,style.css,home.js}`, `shim/app/badge.py`,
  `shim/app/testi.py`, `.specs/B1-proposte.md`, `.specs/B5-dash.md`, `.specs/B6-home-ops.md`,
  `docs/PROMPT-claude-design-home.md`, `docs/prompt-assistente-2-trasicasa.txt`, `README.md`.
- **Manuale di identità visiva**: `uploads/CASE-DI-QUARTIERE_LINEE-GUIDA_VISUAL-1.pdf` («Case di
  Quartiere Brindisi — identità visiva», 14 pagine). Da qui vengono loghi e colori di marca, estratti
  dal file: non sono ricostruiti a mano.
- **Contatti di progetto indicati nel manuale**: Serena Mingolla (contenuti), William Vesnaver (web).

---

# CONTENT FUNDAMENTALS

La lingua di Trasi è **italiano semplice**, e non è una preferenza di stile: chi legge ha una persona
davanti e trenta secondi.

**Persona e tono.** Si parla in terza persona delle cose («la pagina non conserva dati personali»),
mai «tu» e mai «noi». Non c'è un io di prodotto. Il sistema **descrive**, non ordina: è una regola
verificata in automatico nel repository (regex sui verbi imperativi → 0 occorrenze).

| Non si scrive | Si scrive |
|---|---|
| «Approva le proposte in attesa» | «3 proposte aspettano una decisione a San Bao» |
| «Attenzione: errore di connessione» | «Dati non disponibili: la memoria della rete non risponde in questo momento» |
| «Servizio disabilitato» | «Servizio non ancora attivo» |
| «Compila i campi obbligatori» | «Da dove viene l'informazione» (etichetta del campo) |

**Un guasto è un'informazione.** Il vocabolario degli stati non ha la parola «errore». Se lo shim non
risponde entro 3 secondi, la riga dice «dati non disponibili» e — nella veste proposta — aggiunge
«è un'informazione, non un guasto».

**Parole della casa.** Si dice *memoria della rete* (non «database», non «KB» nel testo corrente),
*Casa di riferimento* (non «sede»), *proposta* (non «richiesta di modifica»), *biglietto* (il foglio
A6 stampabile), *la persona* o *il cittadino* nei documenti di progetto — mai nei campi: non si
chiedono né si trascrivono dati personali.

**Maiuscole.** I nomi delle pagine pubblicate sono *Home*, *Osservatorio* e *Account*. Le sezioni
dell'Account hanno nomi propri in maiuscolo iniziale: *La Casa*, *Numeri*, *Proposte*, *Registra*,
*Attrezzoteca*, *Messaggi*, *Conversazioni* e *Impostazioni*. Tutto il resto è in minuscolo normale, con
la maiuscola su *Casa* e *Case di Quartiere* (è un'istituzione, non un edificio).

**Numeri e date.** Date in `15/09/2026`, ore in `11:42`, distanze come si leggono ad alta voce
(`840 m`, `2,1 km`), separatore `·` fra le voci di una riga. I conteggi sotto la soglia di
riservatezza si scrivono `<5`: mai il numero grezzo (k-anonimato 5).

**Niente emoji, niente gergo, nessun punto esclamativo.** Nessuna metafora («cruscotto», «hub») nei
testi rivolti all'operatore: il manuale di progetto può usarle, l'interfaccia no.

**Lunghezze.** Una riga per gli stati; due-tre frasi per la descrizione di una destinazione; i
paragrafi dell'Aiuto stanno entro 36 rem di misura e si leggono in cinque minuti tutti insieme.

---

# VISUAL FOUNDATIONS

**Il carattere generale**: sobrio, di servizio, di carta. È uno strumento pubblico, non una landing
page. La pagina si apre già ferma: nessuna animazione d'ingresso, nessuna illustrazione decorativa.

**Colore.** Tre colori di marca, campionati dal logo Case di Quartiere e ispirati — dice il manuale —
alle risorse archetipiche della città: **il mare** (#0B90CB), **il sole** (#F6AF37), **la terra**
(#CC7E5B). Sono colori *di marca*, non colori *di testo*: su bianco stanno fra 1,9:1 e 3,6:1, quindi
vivono in filetti, fondi e marchio. Il testo usa le varianti profonde (`--mare-profondo` #07577B,
`--terra-scuro` #7A3D20, `--sole-scuro` #6B4A00), tutte oltre 6,6:1. Lo sfondo è carta calda
(#F5F3EE, ereditato dalla pagina attuale), le superfici sono bianche, la testata è blu notte
(#06405A). **Un solo colore di sfondo** per la pagina e uno per la testata: non ce ne sono altri.
Nessun rosso, da nessuna parte: in Trasi nulla è un allarme rivolto a una persona.

**Tipografia.** Il carattere dell'interfaccia usa lo **stack di sistema**. Base 16 px, scala breve (15 · 16 · 17 · 18 · 20 · 22 · 28 · 36). Pesi 400 / 600 / 700, niente leggeri. Il monospaziato di sistema è riservato alle **etichette di provenienza**, perché sono stringhe da citare e si devono poter confrontare carattere per carattere. Il marchio «TRASI» è tipografico, con 0,12 em di spaziatura; il logo della rete resta un'immagine.

**Sfondi.** Nessuna immagine di sfondo, nessun gradiente, nessuna texture, nessun pattern. La carta
calda e il bianco fanno tutto il lavoro. L'unica immagine della pagina è il logo della rete.

**Bordi, angoli, ombre.** Contorni di **2 px** sui controlli e sulle schede (1 px solo per i filetti
interni delle tabelle), raggio **10 px** per schede e controlli, 4 px per le etichette piccole.
Le ombre **non si usano** per separare: separano i bordi. Esiste un solo token d'ombra
(`--ombra-livello`, `0 2px 6px rgba(4,48,68,.12)`) per un livello che galleggia davvero. Nessuna
capsula sfumata, nessun gradiente di protezione, nessuna trasparenza, nessun blur — servirebbero a
far convivere testo e immagini, e qui non ci sono immagini.

**Il filetto a sinistra** è il solo segno di stato del sistema: 4 px sul bordo sinistro di una
scheda. Blu mare per la riga «Oggi», terracotta per la coda delle proposte, giallo sole per
l'attenzione, grigio quando lo stato è spento. Non è mai l'unico canale: accanto c'è sempre la parola.

**Stati.** Riposo: bordo `--bordo` #8A8377. Mouse sopra: sfondo #EAF2F7 e bordo blu notte. Premuto:
sfondo un passo più scuro, **nessuno spostamento e nessuna scala** (una scheda che si muove sotto il
dito, su un tablet allo sportello, è un bersaglio che scappa). Focus: outline 3 px giallo sole +
anello 6 px blu inchiostro, così resta visibile sulla carta e sulla testata blu; è la soluzione della
pagina attuale, ripresa con il giallo del marchio. Disabilitato non esiste: un servizio non attivo si
dichiara in parole («Servizio non ancora attivo») e resta leggibile.

**Movimento.** 120 ms `ease-out` su colore, bordo e sfondo. Nient'altro si muove. Con
`prefers-reduced-motion` la durata va a zero.

**Layout.** Colonna di lettura di 62 rem centrata, margine di pagina 24 px, griglia a due colonne
`minmax(0, 1fr)` che diventa una sotto 40 rem. Bersagli tattili minimi 44 px. Nessun elemento fisso
in sovrimpressione, tranne il compositore della chat in Home. La gerarchia si legge dalla
**dimensione del riquadro**, non dal colore: è l'unica cosa che cambia fra Home e le altre pagine.

**Immagini e illustrazioni.** Il manuale contiene un'illustrazione (un calendario, tratto a mano,
`assets/illustrazione-calendario.png`) usata nella comunicazione interna del progetto: **non entra in
Trasi**. L'interfaccia non ha immagini, e la palette delle immagini di progetto (fotografie di
comunità, calde, luminose) resta fuori dallo strumento di lavoro.

---

# ICONOGRAPHY

**Trasi non ha iconografia, e la scelta è deliberata.** Nel codice attuale non esiste nessuna icona:
né un font di icone, né uno sprite, né un SVG. Il vincolo di zero dipendenze esterne esclude le
librerie (Lucide, Heroicons, Material) e ogni set da CDN; disegnarne uno a mano darebbe un
vocabolario nuovo da imparare a chi ha trenta secondi e turnover alto.

Al posto delle icone il sistema usa:

- **parole**: `Home`, `Osservatorio`, `Account`, `Servizio non ancora attivo`, `Apri la coda delle proposte`;
- **il filetto di 4 px** a sinistra di una scheda come segno di stato;
- **il separatore `·`** fra le voci di una riga (è la convenzione già usata dal servizio nelle
  stringhe di provenienza e nella riga «Oggi»);
- **il tratteggio del bordo** per distinguere l'origine esterna da quella verificata.

Nessuna emoji, mai: non sono nel manuale di marca e su uno schermo condiviso con un cittadino
cambierebbero il registro. Se in futuro servissero icone, la regola è: SVG inline, tratto 2 px come i
bordi, mai da sole — sempre accanto alla parola che già c'è.

**Loghi disponibili** (estratti dal PDF di identità visiva, non ricostruiti):

| File | Uso |
|---|---|
| `assets/logo-case-di-quartiere-colore.png` | versione principale, su fondo bianco |
| `assets/logo-case-di-quartiere-bianco.png` | su testata blu notte e fondi scuri |
| `assets/logo-case-di-quartiere-blu.png` | monocromatico blu |
| `assets/logo-case-di-quartiere-giallo.png` | monocromatico giallo, su fondo scuro |
| `assets/logo-mark-q.png`, `assets/logo-mark-q-bianco.png` | il solo marchio Q (11 sanpietrini) |
| `assets/loghi-istituzionali-por-puglia.png` | obblighi informativi POR Puglia FESR-FSE — solo materiali di progetto, non l'interfaccia |
| `assets/illustrazione-calendario.png` | illustrazione del manuale, comunicazione interna |

Regole del manuale da rispettare: riduzione minima 32 mm, nessuna deformazione, nessuna modifica dei
colori, non ridimensionare una sola parte del logo. Nella comunicazione ufficiale di progetto il logo
Case di Quartiere va sempre accanto al logo del Comune di Brindisi e di Palazzo Guerrieri.

---

# Indice dei file

| File | Contenuto |
|---|---|
| `styles.css` | ingresso unico: solo `@import` |
| `tokens/colori.css` | colori di marca, scale, alias semantici, contrasti misurati |
| `tokens/tipografia.css` | stack di sistema, scala, pesi, misure di lettura |
| `tokens/spaziature.css` | passo di 4 px, padding, bersaglio minimo |
| `tokens/bordi-ombre.css` | raggi, contorni, filetti, l'unica ombra |
| `tokens/focus.css` | la regola `:focus-visible` a due anelli |
| `tokens/movimento.css` | durate e curva, `prefers-reduced-motion` |
| `guidelines/analisi-architettura-informazione.md` | **l'analisi IA e UX della Home**: gerarchia, layout, stati, le due informazioni difficili, cosa non cambiare |
| `guidelines/*.card.html` | le card di fondazione (colori, tipo, spazi, focus, marchio) |
| `assets/` | loghi e illustrazione estratti dal manuale di identità visiva |
| `github.md` | associazione al repository e mappa schermata → file |
| `SKILL.md` | descrittore per l'uso come Agent Skill |

## Componenti

| Componente | Cartella | A cosa serve |
|---|---|---|
| `Bottone` | `components/base/` | azioni: principale, secondaria, quieta, su scuro |
| `Etichetta` | `components/base/` | stato in parole: «Servizio non ancora attivo», «dati provvisori» |
| `Scheda` | `components/base/` | superficie di contenuto, con filetto di stato opzionale |
| `CampoTesto` | `components/base/` | campo con etichetta visibile e riga di aiuto |
| `EtichettaProvenienza` | `components/provenienza/` | l'etichetta KB / Esterna — il componente più importante del sistema |
| `RigaOggi` | `components/stato/` | la riga «Oggi»: attesa, dati, dati non disponibili |
| `AvvisoCoda` | `components/stato/` | quante proposte aspettano una decisione, e da quanto |
| `Intestazione` | `components/navigazione/` | la testata blu notte con logo, Casa e azioni |
| `SelettoreCasa` | `components/navigazione/` | la Casa di riferimento (più la costante `CASE` con le 10 Case) |
| `SaltaContenuto` | `components/navigazione/` | il salto al contenuto, primo elemento focalizzabile |
| `Destinazione` | `components/destinazioni/` | i contenuti delle pagine pubblicate, mantenendo il nome tecnico del componente |
| `Tabella` | `components/dati/` | tabelle di dati con provenienza per riga |
| `MessaggioChat` | `components/chat/` | un turno della chat in Home, con la provenienza sotto |

**Aggiunte intenzionali.** Il codice attuale non ha una libreria di componenti: è una pagina statica
con CSS. I tredici componenti qui sopra sono l'estrazione di ciò che quella pagina già fa
(riquadri, selettore, riga di stato, etichette) più i tre pezzi che le altre superfici richiedono e
che nel repository esistono come dati, non come UI: `EtichettaProvenienza` (da `shim/app/badge.py`),
`MessaggioChat` (da `docs/prompt-assistente-2-trasicasa.txt`) e `Tabella` (dalle viste
`v_proposte_aperte`, `v_mappa_luoghi`). Non ho aggiunto primitive che il prodotto non usa: nessun
Toast, nessun Avatar, nessun Tab, nessun Dialog.

## UI kit

| Kit | Schermate |
|---|---|
| `ui_kits/trasi-home/` | `index.html` (vista tipica), `stati.html` (attesa / dati / non disponibili / coda vuota) |
| `ui_kits/trasi-chiedi/` | la chat con le etichette di provenienza, il biglietto, la proposta |
| `ui_kits/trasi-osservatorio/` | numeri della Casa, coda delle proposte, schede |
| `ui_kits/trasi-registra/` | registro della Casa e modulo che «invia come proposta» |
| `ui_kits/trasi-mappa/` | cornice Trasi attorno alla dashboard Metabase, elenco dei luoghi vicini |

## Template

`templates/schermata-trasi/` — il punto di partenza per una nuova schermata di Trasi: testata,
colonna di lettura, fascia di stato, piede sulla privacy.

---

## Caveat

- **Font del marchio.** «Case di Quartiere» è composto in **Janna LT Bold**, che il manuale distribuisce come file da installare e che non è disponibile come webfont libero. Il logo resta quindi un'immagine PNG estratta dal manuale. Il testo dell'interfaccia usa lo stack di sistema; Janna resta confinato al logo immagine.
- **Loghi come PNG, non SVG.** Nel PDF i loghi sono immagini raster: l'estrazione conserva la
  massima risoluzione disponibile (795×331 per la versione a colori). Se esiste il file vettoriale
  originale, è meglio.
- **Nessuna cartografia.** Le coordinate delle Case e dei luoghi stanno nel database del progetto e
  la mappa è resa dal modulo dell'Osservatorio: il kit tecnico mantiene il proprio nome di cartella
  per compatibilità, mentre la pagina pubblicata si chiama Osservatorio.
