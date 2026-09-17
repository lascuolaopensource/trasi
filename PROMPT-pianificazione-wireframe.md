# PROMPT — Generazione di `plan-wireframe.md` per Trasi (Home · Osservatorio · Account)

## Ruolo

Sei il lead engineer / architect di **Trasi** (Portierato di Quartiere, Rete delle Case di Quartiere di Brindisi). Lo stack B0–B7 è in piedi e verificato (`README.md` §1): Postgres+PostGIS con RLS, shim FastAPI, Onyx v4.7.2 con 4 assistenti, Metabase, Caddy come ingresso unico. Esiste una Trasi Home statica (`deployment/home/`) e un design system (`design/`). Ora il prodotto cambia forma: da «porta con quattro riquadri che aprono servizi esterni» a **un sito a tre pagine con sidebar condivisa**, disegnato in abbozzi Figma da trasformare in wireframe.

## Obiettivo

Produci **`plan-wireframe.md`**: il piano esecutivo, assegnabile, con criteri di done verificabili da terzi, per realizzare il **wireframe funzionante** del sito — tre pagine navigabili, collegate a shim/Onyx/Postgres reali, con veste da wireframe (struttura, testi reali, stati) e **nessuna decisione di design visivo**: il design lo farà **X** dopo, sopra questa struttura.

Non è un riassunto degli abbozzi: è il piano che permette a 2+ persone (o sub-agenti) di lavorare in parallelo senza calpestarsi, che chiude i buchi fra ciò che la UI mostra e ciò che il backend oggi espone, e che consegna a X un pacchetto su cui disegnare senza rifare la struttura.

**Ultrathink.** Prima di scrivere ragiona su: (a) la **macchina a stati della chat** (vuoto → primo invio → modalità chat → conversazione riaperta dallo storico → stessa conversazione vista dalla sidebar di Osservatorio/Account) e dove vive lo stato fra le pagine; (b) il **grafo delle dipendenze reale** (persistenza storico chat → endpoint shim → UI; sessione Onyx multi-turno → chat; Overpass per area/tipi → mappa; `v_da_approvare` esposta al browser → coda proposte in Account); (c) dove i **documenti non definiscono nulla** (pagina Account, storico chat lato Trasi, sidebar, mappa OSM propria, calendario e servizi per luogo) e come il piano lo chiude con decisioni esplicite invece di inventare in silenzio; (d) quali informazioni del wireframe sono **dati reali** (viste RLS, k-anonimato) e quali possono essere **finte dichiarate** (etichettate come tali nel prototipo); (e) i punti di fallimento più probabili (accesso Figma, policy dei tile OSM, `no_self_approve` con un solo account per Casa, rate limit Overpass, peso della pagina con Leaflet) e dove collocare le loro verifiche **early**; (f) cosa **non** va deciso qui: palette, tipografia di marca, iconografia — sono di X; (g) il draft Figma è **un punto di partenza, non un tetto**: il committente lo vuole migliorato molto, e la sezione «Lettura del draft» dice dove e perché — il piano deve rendere misurabile quel salto. Scrivi il piano come lo scriverebbe chi la settimana prossima deve mettere il prototipo davanti a due operatori con un cittadino accanto.

---

## Decisioni già prese (non riaprirle: pianificale)

| # | Decisione | Conseguenza per il piano |
|---|---|---|
| D1 | **Formato**: prototipo funzionante con veste da wireframe | ogni elemento della UI ha una fonte dati reale (endpoint/vista) **oppure** è marcato «dato finto» nel prototipo e nel piano |
| D2 | **Abbozzi**: file Figma con accesso via link + token | §1 del piano legge i frame reali; niente ricostruzioni da descrizione |
| D3 | **Nomi**: **Home** · **Osservatorio** (la mappa) · **Account** | OSSERVATORIO cambia significato rispetto a oggi (numeri + coda → mappa): task espliciti di aggiornamento di Aiuto, `README.md`, `design/readme.md`, `design/github.md`, `.specs/B6-home-ops.md` |
| D4 | **Accesso**: login dell'operatore con le credenziali della Casa (un account per Casa, US-6.1); superato il login si accede a tutte le pagine; **la sessione non scade durante l'uso** | schermata di accesso unica; Casa derivata dalla sessione (`GET /me`), niente selettore Casa; `session_ttl_hours` (`db/003_parametri.sql:46`, oggi 12 h) e `trasi.sessione.scade_ts` da rivedere (TTL lungo o rinnovo scorrevole); «Esci» sempre visibile; rischio schermo condiviso → domanda aperta DPO |
| D5 | **Storico chat**: per Casa, **lato server**, 30 giorni (`gg_retention_chat`) | oggi Trasi **non** persiste le conversazioni e ogni messaggio apre una nuova `chat_session` Onyx (`shim/app/chat.py`, `_conversa`): il piano include persistenza + endpoint + retention + RLS, come dipendenza del wireframe |
| D6 | **Sidebar**: Home → navigazione + storico chat; Osservatorio → navigazione + chat con l'assistente; Account → navigazione + chat con l'assistente | un solo componente sidebar con due pannelli contestuali; un solo modello di stato della conversazione |
| D7 | **Account** include: coda proposte (approva/rifiuta), registra (richieste, eventi, servizi, orari della Casa), attrezzoteca, messaggi interni Casa↔Casa↔PA, impostazioni (Casa, Aiuto, Esci, stampa biglietto/scheda) | `/operatore.html` viene **assorbito**: cutover pulito, nessuna doppia area operatore |
| D8 | **Mappa**: deroga dichiarata al vincolo «zero dipendenze esterne»: **Leaflet self-hosted + tile OpenStreetMap** | Leaflet servito da Caddy (`/srv/home/vendor/…`), nessun CDN; tile: policy OSM (User-Agent/Referer, attribuzione ODbL, niente bulk) e scelta fra tile diretti o proxy/cache Caddy (nasconde l'IP dell'operatore — `Caddyfile:28` già evita log con IP) |
| D9 | **Design visivo**: lo fa X, dopo | il wireframe è in scala di grigi con i soli token strutturali del design system (spaziature, scala tipografica, bersagli 44 px, focus a due anelli, filetto di stato); CSS separato in **struttura** (layout, agganci) e **veste** (sostituibile da X senza toccare l'HTML) |

**Migliorie di funzionalità o UX oltre a quanto specificato qui e negli abbozzi: mai nel percorso critico senza approvazione.** Il piano le raccoglie in §10 come proposte con beneficio, costo e default «non inclusa». Il committente decide.

---

## Materiali in ingresso

### 1. Abbozzi Figma (fonte primaria della struttura)

- File: `https://www.figma.com/design/NyuZ9c757w8WwVACK9H1ME/Untitled` (chiave `NyuZ9c757w8WwVACK9H1ME`). Il file è **pubblico in lettura**: si apre in un browser senza account (verificato il 16/09/2026). Sei frame, tutti della stessa pagina:

| Sigla | Frame Figma | node-id | Cosa rappresenta | Render salvato |
|---|---|---|---|---|
| W1 | Wireframe - 1 | `4-2` | Home, stato vuoto, sidebar aperta | `design/uploads/wireframe/W1-home-sidebar-aperta_4-2.webp` |
| W2 | Wireframe - 2 | `4-37` | Home, stato vuoto, sidebar ridotta a icone | `…/W2-home-sidebar-chiusa_4-37.webp` |
| W3 | Wireframe - 3 | `4-56` | Home in modalità chat | `…/W3-chat_4-56.webp` |
| W4 | Wireframe - 4 | `4-70` | Osservatorio: mappa a tutto schermo | `…/W4-osservatorio-mappa_4-70.webp` |
| W5 | Wireframe - 5 | `4-88` | Osservatorio: scheda del luogo con calendario | `…/W5-scheda-luogo_4-88.webp` |
| W6 | Wireframe - 6 | `16-131` | Account della Casa | `…/W6-account_16-131.webp` |

- Rilettura: `https://www.figma.com/design/NyuZ9c757w8WwVACK9H1ME/Untitled?node-id=<id>` in un browser headless (il nodo nell'URL è selezionato all'apertura; `Shift+2` lo inquadra) → screenshot. Con `FIGMA_TOKEN` in ambiente (mai nel piano né nei log) si possono leggere anche testi e misure: `GET https://api.figma.com/v1/files/{key}/nodes?ids=4-2,4-37,4-56,4-70,4-88,16-131` e `GET https://api.figma.com/v1/images/{key}?ids=…&format=png&scale=2`, header `X-Figma-Token`. Se è configurato un server MCP Figma, preferiscilo.
- Il file può cambiare: il piano rilegge i sei nodi all'avvio e segnala in §1 ogni differenza rispetto alla lettura qui sotto. Se il file non è più raggiungibile: **gate G-01 negativo** → il piano lo dichiara e lavora sui render salvati.

### 2. Repository (leggere prima di pianificare)

| File | Perché |
|---|---|
| `docs/trasi-architecture-v1.2.md` §2 (Case, V1–V7), §4 (UX: persone, risposta chat, coda), §9 (contratto shim, assistenti), §11 (chi approva cosa), §12 (privacy), §14 (US-01..08) | fonte di verità; ogni task cita una sezione |
| `design/readme.md`, `design/guidelines/analisi-architettura-informazione.md`, `design/tokens/*.css`, `design/components/**`, `design/ui_kits/*/README.md` | regole di contenuto (italiano semplice, terza persona, nessun imperativo, «dati non disponibili» è un'informazione), niente icone/emoji/rosso, i 13 componenti da riusare (`EtichettaProvenienza`, `MessaggioChat`, `Tabella`, `RigaOggi`, `AvvisoCoda`, `Scheda`, `CampoTesto`, `Bottone`…) |
| `deployment/home/{index.html,style.css,home.js,operatore.html,operatore.js,WCAG.md}` | ciò che si sostituisce: login, chat proxy, registra richiesta, attrezzoteca, messaggi; metodo WCAG già usato (axe 0, Lighthouse 100) |
| `deployment/caddy/Caddyfile`, `deployment/docker-compose.yml`, `deployment/README.md` | come si servono `/srv/home`, `/api/shim/*`, `/metabase/*`; dove aggiungere Leaflet e l'eventuale proxy tile |
| `shim/openapi.yaml` (contratto congelato lato LLM), `shim/app/{auth,chat,testi,attrezzoteca,messaggi,badge}.py` (endpoint `/op/*` con cookie, fuori OpenAPI) | cosa il browser può già chiamare, con quali input/output ed errori (401, 422 PII, 503) |
| `db/001_schema.sql`, `db/003_parametri.sql`, `db/004_views.sql`, `db/006_fn_proposte.sql` (`v_da_approvare`, `no_self_approve`, `crea_sessione`), `db/013_credenziali.sql`, `db/014_attrezzoteca.sql`, `db/015_messaggi.sql`, `db/016_viste_new.sql` | entità e viste (k-anonimato in `k_anon()`), RLS per Casa, sessioni, retention |
| `docs/user-stories-new.md` (!NEW 1–7), `docs/B7-report.md`, `docs/confronto-sistema-nuove-funzionalita.md` | domande esempio, decisioni Fase 0 (auth shim, chat proxy, export HTML A6/A5), cosa non toccare |
| `docs/prompt-assistente-*.txt`, `shim/app/badge.py` | formato **verbatim** delle etichette `[KB · … ]` / `[Esterna · … ]`, astensione «non trovo informazioni su questo» |
| `metabase/dashboard.py`, `.specs/B5-dash.md` | le metriche già definite per «Casa» e «Rete»: sono la base dei grafici dell'Account |
| `docs/runbook.md` §5, `ops/retention_chat.*` | retention chat 30 gg lato Onyx (`chat_session`/`chat_message`) |
| `docs/fonti-e-connettori-kb.md`, `flussi/export_kb.py` | la **knowledge base**: fonti, documenti esportati (32), dati reali delle 10 Case e dei 22 luoghi da usare nel prototipo |
| `plan.md` §6 (S2), §7 (domande aperte), §9 (icebox) | cosa era già rimandato o escluso; non ripianificare l'escluso senza dirlo |

### 3. Riferimento di funzionamento: la chat di Onyx

Il comportamento da replicare (non l'aspetto) è quello dell'interfaccia chat di Onyx v4.7:

1. **Stato vuoto**: titolo/saluto al centro, **barra** (compositore) grande centrata, **suggerimenti** cliccabili (starter messages) sotto la barra; un clic riempie e invia.
2. **Primo invio**: la barra scende e si **aggancia in basso**; titolo e suggerimenti scompaiono; i turni si accodano sopra, in una colonna scorrevole; il turno dell'assistente mostra uno stato di attesa, poi la risposta con le fonti sotto.
3. **Sidebar sinistra**: «Nuova conversazione», storico raggruppato per data (Oggi · Ieri · Ultimi 7 giorni · Ultimi 30 giorni), titolo della conversazione = prima domanda troncata; clic → riapre la conversazione nella stessa pagina; la conversazione corrente compare in cima appena inviato il primo messaggio; sidebar richiudibile.
4. **Cosa non si replica** (salvo approvazione in §10): selettore di assistente, allegati, pollici su/giù, rigenera, streaming token-per-token (lo shim oggi risponde con il testo intero: lo stato di attesa basta).

In Trasi le «fonti» sono le etichette di provenienza dello shim, su riga propria, alla lettera (`design/components/provenienza/`).

---

## Lettura del draft (W1–W6) e direzione di miglioramento

Il draft è **l'intenzione** dell'autore, e l'intenzione è giusta: tre pagine, una sidebar, la chat che scende al primo invio, la mappa che riempie la pagina, una scheda per il luogo, un account della Casa. Va tenuta l'intenzione e cambiata quasi tutta la resa: il committente chiede un wireframe **molto migliore** del draft. Il piano lo dimostra in §1 con una tabella *draft → wireframe* (per frame: cosa resta, cosa cambia, perché — vincolo, dato reale o miglioria approvata). Un wireframe che ricopia il draft non è accettabile.

### Cosa mostra il draft e cosa non regge

| Frame | Cosa mostra | Cosa non regge — e la regola che lo dice |
|---|---|---|
| W1 | «TRASI» in alto nella sidebar; voci «Nuova Chat», «Osservatorio», «About»; «Recenti» con «Pizzeria Sabato Sera», «Voglio andare a scuola»; in fondo «Santa Chiara»; al centro il logotipo «TRASI» a ~120 px, una barra con una «×», quattro domande come righe di testo centrate | la navigazione mescola un'azione (Nuova chat) con le destinazioni e ne perde una: Account sta in fondo con il nome di una via — la Casa si chiama **Santa Spazio Culturale** (`db/010_seed_case.sql:28`); «About» non è nel prodotto; il logotipo gigante è da landing page, non da strumento di sportello («sobrio, di servizio, di carta», `design/readme.md` § Visual Foundations); le domande non sembrano cliccabili, una è doppia e sono scritte in prima persona del cittadino; niente Casa, niente Esci, niente Aiuto, niente riga privacy; la barra ha un'icona, nessuna etichetta e nessun bottone |
| W2 | la sidebar ridotta a tre icone, più una in fondo | Trasi non ha icone (`design/readme.md` § Iconography): una colonna di sole icone non si legge e non passa WCAG senza etichetta; il ridotto si fa con parole o nascondendo la barra |
| W3 | domanda in alto a destra, risposta a sinistra, compositore in basso alto circa un terzo dello schermo | manca **l'etichetta di provenienza sotto la risposta** — V3, il cuore del prodotto; mancano stato di attesa, astensione, azioni sulla risposta, etichette di turno; le bolle destra/sinistra sono messaggistica, non la colonna unica di `MessaggioChat`; il compositore è sproporzionato; la domanda di esempio ne contiene quattro |
| W4 | fotografia satellitare di Brindisi a tutto schermo, sei punti rossi, testo «OpenStreetMap prototype (this image is a placeholder)» | satellitare ≠ OpenStreetMap (D8: tile OSM standard); il rosso è vietato e qui direbbe «allarme»; nessuna legenda, nessuna provenienza dei livelli, Case/luoghi/POI indistinguibili, nessun filtro per tipo, nessun elenco equivalente da tastiera (WCAG), non si vede dov'è la Casa; la sidebar non mostra la chat (D6) |
| W5 | mappa ridotta a una striscia a sinistra; «Casa SANTA», «Via Santa Chiara, 57», «Other info», «Services»; «Calendar with written events (Clickable)»; «Image event»; «Event Details» | sparisce la mappa e con lei la domanda dell'operatore («dov'è rispetto a qui?»); la griglia mensile è vuota per definizione (pochi eventi → celle vuote = rumore) e poco accessibile: serve l'**elenco per data**; «Image event» non ha dato (`evento` non ha immagini; l'interfaccia non ne ha) → al suo posto la scheda evento stampabile (US-1.3, `GET /op/scheda_evento`); niente provenienza, distanza, orari, azioni |
| W6 | un'immagine, i dati della Casa ripetuti in due colonne, tre bottoni grigi senza nome, «Archive of Demands» come lista di righe | mancano grafici, coda proposte, registra, attrezzoteca, messaggi, impostazioni (D7); immagine decorativa vietata; colonne duplicate; «Archive of Demands» è ambiguo (richieste registrate? conversazioni?); niente k-anonimato, niente Esci/Aiuto |
| tutti | — | nessuna schermata di accesso (D4); nessuno stato (attesa, dati non disponibili, vuoto, 422, 503); nessun comportamento sotto 62/40 rem; testi in inglese o in prima persona; grigio su grigio sotto 4,5:1 |

### La direzione: le schermate ridisegnate

Schizzi di riferimento, non layout definitivi: il piano li porta a wireframe con misure, stati e fonte dati. I testi fra virgolette basse sono quelli **già esistenti** nel design system e nella Home e non si riscrivono. Le voci marcate `(Mn)` sono migliorie della tabella §«Migliorie candidate»: entrano solo se approvate.

**L0 — Accesso** (una sola schermata, prima di tutto)

```
TRASI · Rete delle Case di Quartiere

Accesso della Casa
Casa di riferimento          [ Santa Spazio Culturale                ▾ ]   ← 10 voci; «Tuturano — dati provvisori» nel testo
Parola d'ordine della Casa   [ ••••••••••••• ] [Mostra]
[ Entra ]

▌Parola d'ordine non riconosciuta per Santa Spazio Culturale.            ← stato in parole; dopo 4 tentativi: «Accesso bloccato per qualche minuto»
La sessione resta aperta su questo computer finché non si esce. Non conserva dati personali.
```

**Shell + H1 — Home, stato vuoto** (sidebar 18 rem; sotto 62 rem la barra si nasconde e in testa al contenuto compare il bottone «Menu» — parola, non icona; nessuno stato «solo icone»)

```
┌ sidebar ──────────────┬ contenuto ─────────────────────────────────────────────────────┐
│ TRASI                 │ Oggi a Santa Spazio Culturale: 2 eventi · 1 scheda in scadenza │ (M1)
│ Santa Spazio Culturale│ · 3 proposte                                                   │
│ Centro Storico        │                                                                │
│───────────────────────│            La domanda della persona allo sportello             │
│ Home               ●  │   ┌────────────────────────────────────────────────────────┐   │
│ Osservatorio          │   │ es. dove può fare la tessera sanitaria?                │   │
│ Account               │   │                                                        │   │
│───────────────────────│   └───────────────────────────────────────────[ Chiedi ]──┘   │
│ [ Nuova conversazione ]│   «Senza nomi e senza dati personali: servono solo il bisogno  │
│                       │   e la zona.» Ogni risposta porta la sua etichetta di provenienza│
│ OGGI                  │                                                                │
│ · Dove si fa l'ISEE…  │   Domande frequenti allo sportello                             │
│   11:42               │   [ Dove si fa l'ISEE vicino alla Casa? ]                       │
│ · Bar aperti adesso…  │   [ Bar aperti adesso vicino alla Casa ]                        │
│ IERI                  │   [ Una persona sola cerca qualcuno con cui parlare ]           │
│ · Farmacia di turno…  │   [ Farmacia di turno stasera ]                                 │
│ ULTIMI 30 GIORNI      │   [ Eventi di oggi nella rete ]   [ Come si fa lo SPID? ]       │
│ · …                   │                                                                │
│ le conversazioni      │                                                                │
│ restano 30 giorni     │                                                                │
│───────────────────────│                                                                │
│ Aiuto · Esci          │                                                                │
│ «Non conserva dati    │                                                                │
│ personali»            │                                                                │
└───────────────────────┴────────────────────────────────────────────────────────────────┘
```

Cambia rispetto a W1/W2: navigazione = le tre pagine e basta; «Nuova conversazione» è un'azione dentro il pannello dello storico; la Casa (nome vero, zona) sta in testa alla sidebar; il logotipo torna alla sua misura; i suggerimenti sono **bottoni**, scritti come li batterebbe l'operatore, personalizzati con la Casa, presi dalle user stories; il compositore ha etichetta visibile, testo d'aiuto, bottone «Chiedi»; Aiuto, Esci e riga privacy esistono.

**H2 — Home, modalità chat** (colonna unica, turni etichettati, provenienza sotto ogni informazione; il compositore si aggancia in basso con 2–4 righe, non un terzo dello schermo)

```
│ [ Nuova conversazione ]│ Conversazione di oggi, 11:42 · Santa Spazio Culturale                              │
│ OGGI                  │                                                                                    │
│ ● Dove si fa l'ISEE…  │ OPERATORE                                                                          │
│ · Bar aperti adesso…  │ Dove si fa l'ISEE vicino a La Rosa?                                                │
│ IERI                  │                                                                                    │
│ · …                   │ ASSISTENTE                                                                         │
│                       │ Due CAF vicini al quartiere La Rosa:                                               │
│                       │ 1. CAF ACLI Brindisi — via …, 12 · lun–ven 9:00–13:00 · 840 m                      │
│                       │    ▌KB · Comune di Brindisi · agg. 10/09/2026 · affidabilità 3                     │
│                       │ 2. CAF CISL — via …, 4 · orari non disponibili · 1,2 km                            │
│                       │    ╎Esterna · OpenStreetMap contributors (ODbL) · consultata 11:42 · non verificata dalla rete╎
│                       │ [Stampa il biglietto: CAF ACLI] [Registra richiesta] [Segnala un cambiamento]  (M2)│
│                       │                                                                                    │
│                       │ OPERATORE                                                                          │
│                       │ Il secondo è aperto anche il sabato?                                               │
│                       │ ASSISTENTE · in attesa                                                             │
│                       │ ▌Ricerca nella memoria della rete in corso…                                        │
│                       │────────────────────────────────────────────────────────────────────────────────────│
│                       │ La domanda della persona                                                           │
│                       │ ┌──────────────────────────────────────────────────────────────────────────────┐   │
│                       │ │                                                                              │   │
│                       │ └──────────────────────────────────────────────────────────────[ Chiedi ]─────┘   │
│                       │ «La chat non conserva dati personali.» · 0/2000                                    │
```

Altri stati della stessa schermata, tutti disegnati: astensione («Non trovo informazioni su questo nella memoria della rete.» — nessuna etichetta perché nessuna fonte); `422` («Il testo sembra contenere un dato personale — telefono, email, codice fiscale — e non è stato inviato. Si può riscrivere senza quel dato.»); `503` («L'assistente non risponde in questo momento. La domanda resta scritta qui sotto.»); conversazione riaperta dallo storico (stesso layout, data del primo turno in testa).

**O1 — Osservatorio, mappa** (mappa ed elenco fianco a fianco: l'elenco è l'equivalente da tastiera, con la selezione sincronizzata; sotto 62 rem l'elenco passa sotto la mappa)

```
│ Home                  │ Osservatorio · intorno a Santa Spazio Culturale (Centro Storico) · raggio 800 m         │
│ Osservatorio       ●  │ Sulla mappa: [x] Case della rete (10)  [x] Luoghi della rete (22)  [ ] Bar  [ ] Farmacie  │
│ Account               │ [ ] Scuole  [ ] Fermate  [ ] CAF  [ ] Poste  [ ] altro ▾      [ ] solo aperti adesso (M5) │
│───────────────────────│ ■ Casa della rete — «la rete lo sa» · ● luogo della rete — «la rete lo sa» ·            │
│ CHAT CON L'ASSISTENTE │ ○ trovato su OpenStreetMap — «trovato fuori, non verificato dalla rete»                   │
│ ASSISTENTE            │ ┌───────────────────────────────────────────┬───────────────────────────────────────────┐ │
│ Il CAF più vicino… ▌KB│ │                                           │ ELENCO · 14 voci, per distanza            │ │
│ ┌───────────────────┐ │ │        ■ Santa Spazio Culturale           │ ■ Santa Spazio Culturale · 0 m · aperta   │ │
│ │ La domanda della  │ │ │      (cerchio del raggio 800 m: M3)       │   fino alle 19:00                         │ │
│ │ persona           │ │ │   ● Sportello del Comune   ○ Bar Centrale │   ▌KB · Rete CdQ · agg. 15/09/2026 · aff. 3│ │
│ └─────────[ Chiedi ]┘ │ │         ○ Farmacia Duomo                  │ ● Sportello del Comune · 240 m · lun–ven  │ │
│ Apri nella Home       │ │                                           │   9:00–12:00 · ▌KB · Comune di Brindisi…  │ │
│───────────────────────│ │                                           │ ○ Bar Centrale · 310 m · aperto adesso    │ │
│ Aiuto · Esci          │ │  © OpenStreetMap contributors (ODbL)      │   ╎Esterna · OSM · consultata 11:42╎       │ │
│                       │ └───────────────────────────────────────────┴───────────────────────────────────────────┘ │
│                       │ Fonti esterne: OpenStreetMap ha risposto in 1,2 s   ← oppure «non ha risposto: l'elenco     │
│                       │ mostra solo la memoria della rete»                                                        │
```

Pin distinti per **forma e parola**, mai per il solo colore e mai rossi; tile OSM standard con attribuzione; la Casa della sessione è sempre visibile e centrata all'apertura.

**O2 — Osservatorio, scheda del luogo** (pannello che prende il posto dell'elenco; la mappa **resta** con il pin evidenziato e gli altri attenuati; «Torna all'elenco» in testa; chiusura anche con Esc)

```
│ ┌────────────────────────────────────┬────────────────────────────────────────────────────────┐ │
│ │ mappa: ■ evidenziato, cerchio      │ ← Torna all'elenco                                     │ │
│ │ della Casa, altri pin attenuati    │ Santa Spazio Culturale                                 │ │
│ │                                    │ Casa di Quartiere · Centro Storico · 0 m dalla Casa    │ │
│ │                                    │ via …, Brindisi                                        │ │
│ │                                    │ Orari: lun–ven 9:30–13:00 e 16:00–19:00 · sab 10:00–   │ │
│ │                                    │ 13:00 · oggi aperta fino alle 19:00                    │ │
│ │                                    │ ▌KB · Rete delle Case di Quartiere · agg. 15/09/2026 · affidabilità 3 │
│ │                                    │ [Stampa il biglietto] [Segnala un cambiamento]         │ │
│ │                                    │ [Chiedi all'assistente di questo luogo] (M4)           │ │
│ │                                    │────────────────────────────────────────────────────────│ │
│ │                                    │ SERVIZI DELLA CASA (3)                                 │ │
│ │                                    │ Sportello di ascolto — martedì 16:00–18:00 — per adulti│ │
│ │                                    │ — accesso libero — referente: operatrice dello sportello│ │
│ │                                    │ ▌KB · Rete CdQ · validata 01/09/2026                   │ │
│ │                                    │ …                                                      │ │
│ │                                    │────────────────────────────────────────────────────────│ │
│ │                                    │ PROSSIMI EVENTI · settimana | mese                     │ │
│ │                                    │ gio 18/09 · 17:00–19:00 · Laboratorio per bambini      │ │
│ │                                    │   [Stampa la scheda evento] (M7)                       │ │
│ │                                    │ sab 20/09 · 10:00 · Mercatino del riuso                │ │
│ │                                    │ Nessun altro evento fino al 30/09.                     │ │
│ └────────────────────────────────────┴────────────────────────────────────────────────────────┘ │
```

Per un POI di OpenStreetMap le sezioni dicono la verità del dato: «Servizi: non nella memoria della rete», «Eventi: nessun evento collegato a questo luogo», orari da OSM o «orari non disponibili», etichetta Esterna tratteggiata.

**A1 — Account** (sotto-navigazione in parole; il piano decide fra pagina unica con indice e una pagina per sezione nella stessa shell — default: una per sezione)

```
│ Home                  │ Account · Santa Spazio Culturale                                          [Esci]      │
│ Osservatorio          │ La Casa · Numeri · Proposte (3) · Registra · Attrezzoteca · Messaggi (2 nuovi) ·        │
│ Account            ●  │ Conversazioni · Impostazioni                                                            │
│───────────────────────│──────────────────────────────────────────────────────────────────────────────────────────│
│ CHAT CON L'ASSISTENTE │ ▌3 proposte aspettano una decisione a Santa Spazio Culturale · la più vecchia da 4 giorni │
│ …                     │ ▌                                                                Apri le proposte        │
│                       │                                                                                          │
│                       │ LA CASA                                   │ NUMERI · ultimi 30 giorni    [periodo ▾]     │
│                       │ Santa Spazio Culturale · Centro Storico   │ Richieste registrate                    27   │
│                       │ Ente gestore: YEAHJASì aps                │ per categoria   casa    ████████████     9   │
│                       │ Orari: lun–ven 9:30–13:00 e 16:00–19:00 · │                 lavoro  █████           <5   │
│                       │ sab 10:00–13:00 · chiusa la domenica      │                 salute  ████            <5   │
│                       │ Raggio di riferimento: 800 m              │ per esito  risolte 18 · inviate altrove 6 ·  │
│                       │ ▌KB · Rete CdQ · agg. 15/09/2026          │            non trovate <5                    │
│                       │ [Proponi una correzione]                  │ Eventi in programma 4 · Schede in scadenza 1 │
│                       │                                           │ · Prestiti da confermare 2                   │
│                       │                                           │ Sotto 5 il numero non si mostra (riservatezza)│
│                       │──────────────────────────────────────────────────────────────────────────────────────────│
│                       │ PROPOSTE (3)                                                                             │
│                       │ tipo · entità · da 4 giorni · chi decide: gestore della Casa · motivazione (≤ 80 caratteri)│
│                       │ prima → dopo (diff leggibile)                                    [Approva] [Rifiuta]     │
│                       │ … REGISTRA: richiesta allo sportello | evento della Casa | servizi e orari «invia come     │
│                       │   proposta» · ATTREZZOTECA · MESSAGGI · CONVERSAZIONI (30 gg → apre la Home) · IMPOSTAZIONI│
```

Grafici come barre orizzontali con parola e numero (SVG inline, nessuna libreria da CDN), ordinati, con `<5` al posto del numero sotto soglia e la frase che lo spiega; nessuna torta, nessun colore a portare significato.

### Le regole che escono dal confronto (criteri di accettazione del wireframe)

1. Nessuna icona in nessuno stato; la sidebar ha due stati: aperta (parole) e nascosta (bottone «Menu»).
2. Ogni informazione — in chat, nell'elenco, nella scheda, nell'Account — porta l'etichetta di provenienza dello shim, alla lettera, su riga propria; tratteggio per Esterna.
3. La mappa ha sempre l'elenco equivalente da tastiera con selezione sincronizzata, una legenda in parole, tile OpenStreetMap con attribuzione, la Casa visibile; nessun rosso.
4. La scheda sta **accanto** alla mappa, mai al suo posto; si chiude con «Torna all'elenco» ed Esc.
5. Gli eventi sono un elenco per data (settimana | mese), mai una griglia di celle vuote; niente immagini: al loro posto la scheda evento stampabile.
6. L'Account ha le sezioni di D7 con sotto-navigazione in parole e la riga di presenza della coda in testa.
7. Ogni schermata ha disegnati gli stati: attesa, dati non disponibili, vuoto, 422, 503, e (per la mappa) fonte esterna che non risponde.
8. Tutti i testi in italiano semplice, terza persona, senza imperativi né punti esclamativi; i testi già esistenti si riusano tali e quali.
9. I suggerimenti della Home sono bottoni, presi dalle user stories, personalizzati con la Casa, al massimo sei.
10. Il compositore ha etichetta visibile, riga d'aiuto, bottone «Chiedi», contatore, 2–4 righe; una volta agganciato in basso non copre mai l'ultimo turno.

---

## Il sito, pagina per pagina (specifica da rispettare)

Il draft W1–W6 dà l'intenzione; la «direzione di miglioramento» qui sopra e questa specifica prevalgono su struttura, comportamento, dati e vincoli. Ogni scelta che si scosta dal draft o dalla direzione va in §1 del piano nella tabella *draft → wireframe*, con il perché.

### Struttura comune

- **Accesso** (prima pagina): Casa (le 10, Tuturano con «dati provvisori» nel testo dell'opzione) + «Parola d'ordine della Casa» → `POST /api/shim/login`. Errori in parole, mai grezzi (credenziali non valide; blocco dopo tentativi, `db/013_credenziali.sql:109`). Dopo il login → Home. `401` su qualunque chiamata → si torna all'accesso, senza perdere il testo digitato nel compositore.
- **Shell**: sidebar a sinistra + area contenuto. Su desktop la sidebar è fissa; sotto 62 rem si richiude a comando; sotto 40 rem è a scomparsa e l'area contenuto prende tutta la larghezza. Bersagli ≥ 44 px. Ordine di tabulazione dichiarato: salta al contenuto → sidebar → contenuto.
- **Sidebar**: testata (marchio TRASI, Casa della sessione da `GET /me`, «dati provvisori» se Tuturano); navigazione a tre voci (Home · Osservatorio · Account) con la voce corrente dichiarata (`aria-current`); **pannello contestuale** (D6): in Home lo storico (D5), in Osservatorio e Account la chat compatta con l'assistente (stessa conversazione corrente della Home, stesso storico, con «Apri nella Home»); piede: Aiuto · Esci · riga privacy («non conserva dati personali»).
- **Stati trasversali** (testi da `design/readme.md` § Content Fundamentals): attesa ≤ 3 s (`aria-busy`, «Lettura in corso…»); «Dati non disponibili: la memoria della rete non risponde in questo momento» (informazione, non guasto, filetto giallo, mai rosso); vuoto («Nessuna proposta in attesa a San Bao.»); `422 dato_personale_sospetto` → il testo non è stato inviato e la frase dice perché; `503` Onyx → «L'assistente non risponde in questo momento»; tile OSM non raggiungibili → mappa senza sfondo con pin ed elenco comunque leggibili, e una riga che lo dice.

### Home — la chat

- **Stato vuoto**: titolo (una frase in italiano semplice, terza persona, senza «tu»: la scrive il piano seguendo le regole di contenuto), barra/compositore centrata (textarea ≤ 2000 caratteri, invio con bottone e con tastiera), **4–6 suggerimenti** presi dalle user stories, nell'ordine della frequenza reale allo sportello: US-01 «Dove si fa l'ISEE vicino a La Rosa?», US-08 «Bar vicino a Bozzano aperti adesso?», US-04 «Una persona sola che vuole parlare con qualcuno: dove?», §9.3 «Farmacia di turno vicino a Tuturano», «Eventi oggi a Bozzano», !NEW US-1.2 «Laboratori per bambini questa settimana?», !NEW US-5.1 «Cinque microfoni per domani: dove sono?». I suggerimenti si personalizzano con la Casa della sessione.
- **Transizione**: al primo invio la barra scende in basso e resta fissa (l'unico elemento fisso ammesso, `design/readme.md` § Layout); la conversazione entra nello storico della sidebar.
- **Modalità chat**: turni Operatore / Assistente (`MessaggioChat`), risposta con le etichette di provenienza **verbatim** su riga propria (`EtichettaProvenienza`), astensione dichiarata quando non c'è fonte, stato di attesa fra invio e risposta. **Multi-turno**: la conversazione mantiene il contesto (oggi no: vedi «Cosa manca»).
- **Azioni sulla risposta** (`docs/trasi-architecture-v1.2.md` §4.4): `[Stampa biglietto]` `[Registra richiesta]` `[Proponi correzione]`. Oggi il proxy restituisce solo `{risposta, fonte}`: il biglietto ha bisogno di `luogo_id` — buco da chiudere (tabella sotto).
- **Storico** (sidebar): lista per data, riapribile, 30 gg, per Casa (account condiviso: nessun nome di operatore, nessun dato personale — il filtro anti-PII a monte già rifiuta con 422). «Nuova conversazione» in testa.

### Osservatorio — la mappa

- **Mappa Leaflet** nell'area contenuto, centrata sulla Casa della sessione (`v_mappa_case`: lat/lon, `raggio_m_eff`), zoom di quartiere.
- **Tre livelli**, ciascuno con la sua provenienza dichiarata in una legenda in parole (mai il solo colore; niente icone: parole + forma del pin): **Case della rete** (10, `v_mappa_case`) in evidenza; **luoghi della rete** (22, `v_mappa_luoghi`, KB, tipo/casa/fonte/affidabilità); **POI di quartiere** (bar, scuole, farmacie…) da OpenStreetMap via Overpass, **Esterna**, in secondo piano, filtrabili per tipo. Nota: `vicino_a` accetta un solo `tipo` per chiamata, con enum di 12 valori (`shim/openapi.yaml:143`) **senza `scuola`**: la mappa per area richiede un endpoint o un'estensione (tabella sotto).
- **Clic su un pin → scheda** (pannello nell'area contenuto, non modale; chiudibile; raggiungibile da tastiera anche dall'elenco): nome, tipo, indirizzo, distanza dalla Casa, orari o «orari non disponibili» (il luogo non si scarta), note di accesso, etichetta di provenienza; **calendario degli eventi** (per le Case: `evento` per `casa_id`, vista settimana/mese; per gli altri luoghi: `evento` non è legato a `luogo.id` — si dichiara «nessun evento collegato» finché il dato non esiste); **servizi offerti** (per le Case: `scheda_servizio` per `casa_id` con titolo, destinatari, quando, come accedere, referente come ruolo; per gli altri luoghi: descrizione e `note_accesso`); azioni: `[Stampa biglietto]` (`GET /biglietto?luogo_id`), `[Proponi correzione]` (→ proposta, V4).
- **Elenco equivalente** accanto/sotto la mappa: le stesse voci ordinate per distanza, con provenienza per riga (`Tabella` del design system, come `ui_kits/trasi-mappa`). È l'alternativa accessibile alla mappa, non un'aggiunta.
- **Sidebar**: chat compatta con l'assistente (D6).

### Account — la Casa

- **Testata della Casa**: nome, zona, ente gestore, orari settimanali ed eccezioni, raggio, «dati provvisori» se del caso, fonte e data di aggiornamento (tabella `casa`, sola lettura: le modifiche passano da proposta).
- **Grafici sul funzionamento della Casa**: le metriche già definite in Metabase «Casa» e «Rete» (`metabase/dashboard.py`): richieste per categoria ed esito nel periodo (`v_report_mensile`, `v_destinazioni`), eventi in programma, schede in scadenza, proposte aperte per approvatore, uso dell'attrezzoteca (`v_uso_oggetti`); filtro periodo (default 30 gg); **k-anonimato 5** in ogni cella, tooltip e ordinamento (`<5`, mai il numero). Resa dei grafici senza CDN (SVG inline o libreria self-hosted: lo decide il piano); dati via endpoint `/op/*` su viste `k_anon` (o embed Metabase: il piano confronta e sceglie).
- **Storico chat**: lista completa per data (30 gg), apertura → Home in modalità chat sulla conversazione scelta.
- **Coda delle proposte**: `v_da_approvare` filtrata sul ruolo; per proposta: tipo, entità, origine, età, chi decide, motivazione, **diff leggibile**; `Approva` / `Rifiuta` sulla singola proposta, solo dove la Casa decide davvero (altrimenti «da approvare in coda» di chi compete). Riga di presenza «N proposte aspettano una decisione · la più vecchia da X giorni», nessuna scadenza, nessun contatore a pallino (`AvvisoCoda`).
- **Registra**: richiesta allo sportello (categorie/esiti di `richiesta`, nessun campo per il cittadino), evento della Casa (`POST /eventi`, scrittura diretta — opzione A, `README.md` § Decisione S2), servizi e orari della Casa (→ `proponi_modifica`, «invia come proposta»), stato delle proprie proposte.
- **Attrezzoteca** e **Messaggi interni**: le funzioni di `operatore.html` (inventario, prestiti da confermare, movimenti; lista e invio messaggi a Casa/PA), riportate nella nuova shell.
- **Impostazioni**: Casa (sola lettura), Aiuto (riscritto per le tre pagine, cinque minuti di lettura), Esci, stampa (biglietto A6, scheda evento `GET /op/scheda_evento`).
- **Sidebar**: chat compatta con l'assistente (D6).

---

## Cosa esiste e cosa manca (il piano chiude ogni riga)

| Bisogno della UI | Oggi | Buco | Direzione attesa nel piano |
|---|---|---|---|
| Chat multi-turno | `POST /op/chat` apre una nuova `chat_session` per ogni messaggio | nessun contesto fra i turni | riuso della `chat_session` Onyx per conversazione (`parent_message_id` reale) — SA-Onyx + SA-Shim |
| Storico chat per Casa, 30 gg | Trasi non persiste; solo Onyx (retention via `ops/retention_chat.*`) | nessuna tabella, nessun endpoint di lista/lettura, nessuna RLS | decisione: tabella `trasi.conversazione`/`turno` con RLS per Casa e `scadi_*` a 30 gg **oppure** mappa Casa↔`chat_session_id` Onyx + lettura via API Onyx; endpoint `GET /op/conversazioni`, `GET /op/conversazioni/{id}`, `POST /op/conversazioni/{id}/messaggi` — SA-Dati + SA-Shim |
| Azioni sulla risposta | il proxy restituisce `{risposta, fonte}` | manca `luogo_id`/entità citate per biglietto e proposta | arricchire la risposta con i riferimenti dei `top_documents` (`trasi:luogo:N`, attenzione all'URL-encoding: `README.md` §7.2) — SA-Shim |
| POI di quartiere sulla mappa | `vicino_a` un tipo per chiamata, 12 tipi, raggio dalla Casa | niente `scuola`, niente bbox, N chiamate per N tipi, rate limit Overpass | endpoint `/op/poi?bbox&tipi[]` con cache breve e User-Agent identificativo (`README.md` §7.1), estensione dell'enum — SA-Shim (+ gate) |
| Case e luoghi per la mappa | `v_mappa_case`, `v_mappa_luoghi` lette solo da Metabase | nessun endpoint browser | `GET /op/mappa` (Case + luoghi, con badge per riga) — SA-Shim |
| Eventi per la scheda | `eventi_oggi` un giorno per Casa; `evento.luogo_testo` libero | nessun range/mese, nessun legame `evento`↔`luogo.id` | `GET /op/eventi?casa&dal&al`; per i luoghi non-Casa si dichiara l'assenza; il legame è domanda aperta | 
| Servizi per la scheda | `scheda_servizio` per Casa | nessun endpoint browser, nessuna relazione luogo↔servizio | `GET /op/servizi?casa`; per i luoghi non-Casa: descrizione/note_accesso | 
| Coda proposte in UI | `approva_proposta` solo nel contratto LLM (`/v1/u/{email}/…`); NocoDB non attivo | nessun `/op/proposte`; **`no_self_approve` distingue per email, ma il login è uno per Casa** (`docs/B7-report.md:56-61`) | `GET /op/proposte`, `POST /op/proposte/{id}/decisione`; **gate** su chi può approvare cosa con un solo account per Casa → se irrisolto, domanda aperta Processi, e in UI la decisione resta visibile ma dichiarata «non disponibile da questo accesso» |
| Grafici dell'Account | dashboard Metabase 3 e 2 | nessun endpoint dati per il browser; embed Metabase richiede login proprio | `GET /op/casa/statistiche?dal&al` su viste `k_anon` **oppure** embed firmato: confronto nel piano |
| Sessione che non scade | `session_ttl_hours` = 12, `scade_ts` fissa | contraddizione con D4 | TTL lungo o rinnovo scorrevole a ogni chiamata; `Esci` esplicito; nota DPO — SA-Dati + SA-Shim |
| Leaflet e tile senza CDN | vincolo zero dipendenze, `Caddyfile` serve `/srv/home` | nessun vendor, nessuna policy tile | Leaflet in `deployment/home/vendor/`, attribuzione ODbL, tile diretti vs proxy Caddy (`/tile/*`) con cache — SA-Stack (+ gate) |
| Modifica servizi/orari della Casa | `proponi_modifica` solo nel contratto LLM | nessun `/op/proponi_modifica` | variante con cookie che riusa la stessa funzione DB — SA-Shim |

Nessuna di queste righe si risolve con una scrittura diretta fuori dal flusso proposta→approvazione→applicazione, salvo le eccezioni già decise (iCal, `registra_richiesta`, movimento attrezzoteca, eventi della propria Casa — opzione A). Se un buco spinge verso una scrittura diretta nuova, il piano lo segnala come conflitto, non lo pianifica.

---

## Vincoli non negoziabili

- **V3 mai senza fonte**: ogni informazione mostrata porta l'etichetta dello shim alla lettera; POI OSM sempre «Esterna … non verificata dalla rete»; «orari non disponibili» non scarta il luogo; stato delle fonti esterne dichiarato (`fonti_esterne[].stato`).
- **V4 l'umano decide**: nessuna scrittura del dominio fuori da proposta→approvazione→applicazione (eccezioni sopra); Approva/Rifiuta solo sulla singola proposta, dove la decisione avviene.
- **V5 privacy**: nessun dato personale in UI, storico, log, `localStorage`/`sessionStorage`; il cittadino non compare mai in un campo; k-anonimato 5 su ogni conteggio; retention chat 30 gg; IP degli operatori non loggati (vale anche per i tile).
- **V6 nessun imperativo** verso persone o Case: la verifica regex «zero imperativi» esistente (`metabase/alerts.py`, `README.md` §5) si estende a tutti i testi del wireframe.
- **Accessibilità WCAG 2.1 AA**: contrasto ≥ 4,5:1 anche in scala di grigi, focus visibile a due anelli, tutto da tastiera (la mappa ha sempre l'elenco equivalente), `lang="it"`, base ≥ 16 px, axe 0 violazioni e Lighthouse Accessibilità 100 come in `deployment/home/WCAG.md`.
- **Italiano semplice**, terza persona, niente «tu»/«noi», niente emoji, niente icone (parole, filetto, separatore `·`, tratteggio per Esterna), niente rosso, nessun punto esclamativo (`design/readme.md`).
- **Dipendenze**: zero CDN, zero font remoti, zero domini terzi **tranne** i tile OSM (D8). Nessun passo di build: HTML + CSS + JS in moduli ES, come `deployment/home/` oggi. Un framework o un bundler entra solo come domanda aperta motivata, non come default. Budget di peso **per pagina** fissato dal piano (la Home del 2026 stava in 21 KB; Leaflet da solo ne pesa ~150).
- **Veste da wireframe** (D9): scala di grigi + token strutturali; nessuna scelta di palette, tipografia di marca, iconografia. L'HTML è semantico e stabile: X cambia la veste senza toccare la struttura.
- **Cutover pulito**: la nuova shell sostituisce `index.html` (porta) e `operatore.html`; niente doppie Home, alias o pagine «vecchie» lasciate lì. Le dashboard Metabase restano per `rete`/`ti`, non per la Casa (o il piano motiva altrimenti).
- **Dati reali dove esistono**: 10 Case, 22 luoghi, schede, eventi, proposte dal DB (via RLS della Casa loggata). I dati finti, se servono, sono pochi e **dichiarati** («dato di esempio») nel prototipo.
- **Tuturano**: «dati provvisori» dentro il testo, mai solo in un colore.

---

## Migliorie candidate — da approvare prima (non pianificarle come incluse)

Il piano le presenta in §10 con beneficio, costo in ore, dipendenze e default «non inclusa». Chi legge decide con un sì/no per riga.

| # | Miglioria | Perché potrebbe valere |
|---|---|---|
| M1 | Riga «Oggi» + presenza della coda in testa alla Home (esiste oggi: `v_oggi_casa`, `RigaOggi`, `AvvisoCoda`) | è l'unica cosa che cambia da sola; gli abbozzi non la prevedono |
| M2 | Azioni sulla risposta della chat `[Stampa biglietto] [Registra richiesta] [Proponi correzione]` | previste dall'architettura §4.4, mai realizzate; chiudono il ciclo allo sportello |
| M3 | Cerchio del raggio della Casa sulla mappa (`raggio_m_eff`, che Metabase non disegna) | dato già in DB; Leaflet lo rende gratis |
| M4 | «Chiedi all'assistente di questo luogo» dalla scheda: precompila la chat in sidebar con il contesto del luogo | collega Osservatorio e chat senza copiare a mano |
| M5 | Filtro «aperto adesso» sui POI (già in `vicino_a`) e nell'elenco | risposta alla domanda più frequente («adesso dove?») |
| M6 | Ricerca testuale nello storico chat (lato client, 30 gg) | ritrovare «quella risposta di martedì» senza scorrere |
| M7 | Stampa della scheda luogo/evento direttamente dalla scheda (esiste `GET /op/scheda_evento`) | un passo in meno fra scheda e stampante |
| M8 | Streaming della risposta (SSE shim → Onyx) al posto dello stato di attesa | percezione di velocità; costo lato shim non banale |

Se dagli abbozzi emergono altre migliorie, si aggiungono a questa tabella, mai al percorso critico.

---

## Formato di `plan-wireframe.md` (obbligatorio)

```
# Trasi — Piano di realizzazione del wireframe funzionante (Home · Osservatorio · Account)

## 0. Come leggere questo piano
## 1. Lettura del draft e tabella draft → wireframe ← per frame W1–W6: cosa mostra, cosa resta, cosa cambia e perché (vincolo · dato reale · miglioria approvata); differenze rispetto alla lettura del prompt se il file Figma è cambiato
## 2. Gate di fattibilità (0–4h)         ← G-01 accesso Figma · G-02 Leaflet self-hosted + policy tile + peso · G-03 Onyx multi-turno via API · G-04 persistenza storico chat (schema/RLS/retention) · G-05 no_self_approve con un account per Casa · G-06 Overpass per bbox/tipi (scuole) e rate limit · G-07 sessione senza scadenza · G-08 dati per i grafici (endpoint vs embed) — criterio pass/fail e azione-se-negativo
## 3. Architettura dell'informazione e shell ← sidebar (matrice pagina × pannello), navigazione, accesso, stati trasversali, comportamento sotto 62/40 rem, modello di stato della conversazione fra le pagine
## 4. Specifica per pagina               ← Home, Osservatorio, Account: elementi, stati (vuoto/attesa/non disponibili), macchina a stati della chat, interazioni della mappa e della scheda, sezioni dell'Account; ogni elemento → fonte dati o «dato finto dichiarato»
## 5. Mappa dati e contratto API         ← elemento UI → endpoint esistente | nuovo endpoint (path, input, output, ruolo DB, RLS, errori) | vista; ogni riga di «Cosa manca» chiusa
## 6. Task dettagliati                   ← ID, owner/SA, stima (h), input, output, criterio di done osservabile, dipendenze, rischio; nessun task > 4h senza scomposizione
## 7. Lavoro parallelo e percorso critico ← mermaid + tabella owner × fase; tre tagli: minimo dimostrabile / completo / con migliorie approvate
## 8. Verifiche                          ← percorsi E2E (US-01, US-04, US-08; mappa → scheda → biglietto; Account → proposta approvata → applicata alle 05:00; storico riaperto dopo 24 h); axe/Lighthouse; regex imperativi; PII 422; k-anonimato <5; RLS cross-Casa 0 righe; retention 30 gg; peso per pagina; sessione dopo 13 h
## 9. Consegna a X (design)              ← inventario componenti e stati, schermate annotate (render), agganci (token CSS, classi, file veste), cosa X può cambiare senza toccare l'HTML, cosa no
## 10. Migliorie proposte — da approvare ← tabella: miglioria, beneficio, costo, dipendenze, default (non inclusa)
## 11. Domande aperte                    ← domanda, owner (PM / TI / Processi / DPO / X), deadline, fallback se non arriva risposta
## 12. Cosa NON si fa                    ← design visivo, funzioni per il cittadino, accesso PA/rete al sito, SSO, PWA, app nativa, notifiche, traduzione, framework/bundler… con motivazione
```

Regole di formato: ogni criterio di done è **osservabile** («`GET /op/conversazioni` come `casa_bozzano` → 0 righe di San Bao», «axe: 0 violazioni su tre pagine + accesso», «`curl` tile senza User-Agent → il proxy risponde comunque 200», «pin cliccato da tastiera → scheda con `aria-expanded=true`»), non «funziona»; ogni task cita la sezione dell'architettura o il file/frame di origine; stime in ore; nessun task > 4h; i task UI non partono prima dei gate da cui dipendono; ogni endpoint nuovo ha ruolo DB, RLS e casi 401/422/503 nella definizione, non «da vedere».

---

## Orchestrazione (sub-agenti del piano)

Il piano si produce orchestrando sub-agenti dove serve profondità; in `plan-wireframe.md` ogni fase indica chi la produce e chi la verifica.

| Sub-agente | Scope | Fasi |
|---|---|---|
| **SA-UX** (`task`) | lettura Figma, shell + sidebar, Home/chat, Osservatorio (Leaflet, scheda, elenco), Account (sezioni, grafici), veste wireframe, pacchetto per X, WCAG | §1, §3, §4, §9 |
| **trasi-shim** | endpoint `/op/*` nuovi (conversazioni, mappa, poi, eventi, servizi, proposte, statistiche, proponi_modifica), risposta chat arricchita, test pytest | §5, §6 |
| **trasi-dati** | schema storico chat, RLS per Casa, retention 30 gg, `session_ttl_hours`/rinnovo, viste `k_anon` per le statistiche, test SQL | §5, §6, G-04, G-07 |
| **trasi-onyx** | sessione multi-turno via API, PAT, persona, budget, `top_documents` con riferimenti | G-03, §5 |
| **trasi-proposte** | coda proposte in UI, `no_self_approve` con login unico, test «zero scritture dirette» sulle novità | G-05, §5, §8 |
| **trasi-stack** | Leaflet in `/srv/home/vendor`, proxy/cache tile, Caddyfile, compose, budget di peso | G-02, §6 |
| **trasi-dash** | quali metriche entrano nei grafici dell'Account e da quali viste; confronto endpoint vs embed | G-08, §4 Account |
| **trasi-review** (sola lettura) | revisione del piano: V3–V6, criteri osservabili, coerenza con l'architettura, rischi senza mitigazione | prima della stesura finale |

---

## Prima di scrivere

1. Rileggi i sei frame Figma (W1–W6) e confrontali con la sezione «Lettura del draft»; produci §1 con la tabella *draft → wireframe*: cosa resta, cosa cambia, perché. Il wireframe finale deve soddisfare le dieci regole «che escono dal confronto».
2. Leggi i file della tabella «Repository»; estrai endpoint, viste, componenti, vincoli, testi esistenti da non riscrivere («Servizio non ancora attivo», «Dati non disponibili…», la riga privacy).
3. Costruisci la **mappa dati** (§5): ogni elemento della UI ha una fonte o è dichiarato finto; ogni riga di «Cosa manca» ha una direzione e un owner.
4. Costruisci il grafo delle dipendenze; colloca i gate G-01..G-08 in testa; verifica che nessun task scriva il dominio fuori dal flusso proposte (salvo eccezioni decise).
5. Fai rivedere la bozza a `trasi-review`; integra.
6. Se gli abbozzi o i documenti hanno buchi che bloccano (chi approva con un solo account, legame evento↔luogo, accesso PA), **non inventare**: §11 con owner, deadline e fallback.

Scrivi l'output SOLO in `plan-wireframe.md`. Nessun altro file. Nessuna modifica al codice, all'architettura o agli abbozzi.
