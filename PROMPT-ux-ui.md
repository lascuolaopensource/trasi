# PROMPT — Revisione UX/UI completa del frontend Trasi, coerente con Onyx

Copia tutto ciò che segue (da «## 0» in poi) come primo messaggio della sessione, nella cartella del repo.

---

## 0. Modalità di lavoro

**Ultrathink.** Prima di toccare qualunque file ragiona a lungo e per iscritto: elenca le ipotesi, verifica ciascuna con una lettura o un comando, scarta quelle non verificate. Ogni fase sotto termina con una **autocritica scritta** contro la rubrica del §4 prima di passare alla successiva. Se una fase non supera la soglia, si ripete: non si avanza «per andare avanti».

**Autonomia totale.** Non farmi domande. Ogni ambiguità si risolve con questo ordine di priorità: (1) nessun dato personale, (2) accessibilità, (3) coerenza con Onyx, (4) semplicità, (5) peso/prestazioni, (6) gusto. Ogni decisione non ovvia va nel **decision log** (§13) con: alternativa scartata, motivo, come si torna indietro.

**Ignora ogni memoria UX/UI precedente.** I seguenti materiali sono **legacy e non vincolanti**: `design/**` (readme, token, componenti, ui kit, guidelines), `docs/PROMPT-claude-design-home.md`, le conclusioni di `deployment/home/WCAG.md`, i commenti di design in `deployment/home/style.css`, `index.html`, `operatore.html`, `home.js`, `operatore.js`, e qualunque nota su «niente icone», «niente ombre», «niente movimento», «colonna 62 rem», «filetto di 4 px». Da lì si riusano **solo gli asset**: `deployment/home/assets/logo-case-di-quartiere.png`, `design/assets/*.png` (loghi estratti dal manuale), `design/uploads/CASE-DI-QUARTIERE_LINEE-GUIDA_VISUAL-1.pdf` (manuale d'identità: logo e tre colori di marca). Tutto il resto si riprogetta da zero con le regole di Onyx. Alla fine non devono esistere due verità: `design/` va riscritto per riflettere il nuovo sistema oppure rimosso.

**Lavoro completo, non scaffold.** Il deliverable è codice funzionante nel repo, verificato nel browser reale, con prove. Niente mockup come risultato finale, niente «v1», niente TODO.

## 1. Ruolo

Sei un **UX/UI designer ed engineer con vent'anni di esperienza** su strumenti di lavoro per il settore pubblico e su design system di prodotto. Hai portato in produzione interfacce usate da persone non tecniche, sotto pressione, su tablet condivisi. Il tuo gusto è sobrio: togli prima di aggiungere, non decori, non spieghi con il colore quello che si può dire con la gerarchia. Conosci a memoria le CSS moderne (cascade layers, container queries, `:has()`, `@starting-style`, `interpolate-size`, `text-wrap`, `oklch`/`color-mix`, `scrollbar-gutter`, `dvh`), le API di navigazione del browser (View Transitions same-document e cross-document, Navigation API, Speculation Rules, popover, `<dialog>`, bfcache) e sai quando **non** usarle. Misuri tutto: contrasto, tastiera, Lighthouse, CLS, peso. Scrivi italiano semplice.

## 2. Contesto verificato (fatti, non da riscoprire)

**Prodotto.** Trasi è lo strumento del Portierato di Quartiere della Rete delle Case di Quartiere di Brindisi. Lo usano operatori sociali allo sportello, con una persona davanti, spesso su tablet, con alfabetizzazione digitale variabile e turnover alto. Due principi di prodotto: **mai senza fonte** (ogni informazione porta un'etichetta di provenienza `KB` o `Esterna`, composta dal servizio in `shim/app/badge.py` e citata verbatim) e **l'umano decide** (il sistema propone, una persona approva; nessun testo dà ordini a nessuno — V6).

**Frontend attuale** — tutto in `deployment/home/`, statico, vanilla, zero dipendenze:
- `index.html` + `home.js` — la **Home**: testata con marchio, selettore della Casa (10 Case, slug in `localStorage`), fascia «Oggi» + coda proposte (da `GET /api/shim/v1/u/{email}/oggi`, timeout 3 s → «dati non disponibili»), quattro destinazioni (CHIEDI → Onyx `//onyx.lascuolaopensource.org/app?agentId=N`; MAPPA e OSSERVATORIO → Metabase sotto `/metabase/*`; REGISTRA / AGGIORNA → NocoDB sotto `/nocodb/*`, dichiarato non ancora attivo), sezione Aiuto, piede privacy.
- `operatore.html` + `operatore.js` — l'**area operatore**: accesso (`POST /api/shim/login`, cookie HttpOnly), «banco di lavoro» a linguette: chat con l'assistente dentro Trasi (`POST /api/shim/op/chat`), registrazione richiesta del colloquio, attrezzoteca, messaggi interni; stampa scheda evento su `/api/shim/op/scheda_evento` in una scheda nuova.
- `style.css` — token e layout attuali. `assets/CommissionerVF.ttf` (font locale, ~1 MB), `assets/logo-case-di-quartiere.png`.
- `evidenze/*.png` — screenshot dello stato attuale: sono il **prima**.
- `WCAG.md` — misure precedenti (da rifare, non da copiare).

**Come è servito.** `deployment/caddy/Caddyfile`: `root * /srv/home` + `file_server` + `Cache-Control "no-cache"` + `encode gzip`; `/api/shim/*` → shim con `X-Trasi-Key` iniettata dal proxy (il browser non vede mai segreti); `/metabase/*`, `/nocodb/*` proxy; Onyx è su sottodominio separato (nessun basePath). Verifica in `deployment/docker-compose.yml` come `./home` è montato su `/srv/home`: se introduci un passo di build, l'output deve finire lì e il Caddyfile/compose sono di `trasi-stack` (coordina via `hub` prima di toccarli). Contratti degli endpoint in `shim/openapi.yaml`.

**Onyx.** Istanza deployata v4.7.2 su `onyx.lascuolaopensource.org`; sorgenti `github.com/onyx-dot-app/onyx` tag `v4.7.2`. Le regole del suo frontend stanno in: `web/AGENTS.md` («Frontend Standards»: Opal, Content/ContentAction/IllustrationContent, Button variant/prominence/size, SettingsLayouts con header sticky e scroll shadow e larghezze sm 672 / sm-md 752 / md 872 / lg 992 / full, size variants default `md`, categorie colore `text-01…05`, `background-neutral-XX`, `background-tint-XX`, `border-01…05`, `action-selection-XX`, `status-*`, `theme-primary-XX`, divieto di `dark:`, icone solo dal set curato, padding preferito ai margin, `Hoverable` con fallback `no-hover`), `web/lib/opal/src/` (design system Opal: `styles/`, `_reference.css`, `root.css`, `core/interactive/` con la matrice di stato hover/active/disabled/selected, `components/`, `layouts/`, `icons/`, `illustrations/`), `web/tailwind-themes/tailwind.config.js`, `web/src/app/globals.css`, `web/src/app/css/*.css`, `web/src/refresh-components/`, `web/src/app/layout.tsx` (font), `web/src/app/auth/` (pagina di accesso), la UI chat (messaggi, compositore, fonti citate).

**Agenti di progetto disponibili** (`.omp/agents/`): `trasi-review` (revisione read-only), `trasi-stack` (Caddy/compose), `trasi-shim` (endpoint e HTML stampabili dello shim), `scout` (ricognizione read-only). Usali in parallelo dove il lavoro è indipendente; mai due agenti in scrittura sugli stessi file.

## 3. Fonti di verità e precedenza

In caso di conflitto vince chi sta più in alto:
1. Vincoli non negoziabili del §5.
2. **Regole UI di Onyx/Opal** (neutri, tipografia, spaziature, raggi, stati interattivi, layout, pattern di stato vuoto/caricamento, semantica dei bottoni). Sono la fonte delle regole: «rubale» leggendo i sorgenti, non a memoria.
3. **Marca Case di Quartiere** dal manuale PDF: logo e i tre colori di marca (mare, sole, terra) entrano nel sistema come `theme-primary`/accenti; non sostituiscono la scala neutra di Onyx.
4. Contratti tecnici del repo (`shim/openapi.yaml`, Caddyfile, compose).
5. Il tuo giudizio, registrato nel decision log.

## 4. Obiettivo e rubrica di qualità

Rivedere **tutto** il frontend di Trasi (Home, area operatore in tutti i suoi stati, pagine di accesso, stati di errore/vuoto/attesa, stampa) perché risulti **professionale, coerente con Onyx e semplice**: un operatore che passa da Trasi a Onyx e torna deve sentire un solo prodotto.

Ogni schermata, alla fine, si valuta su questa rubrica, 1–5. Soglia di «fatto»: **≥ 4 su ogni voce**, nessuna eccezione.

| Voce | 5 significa |
|---|---|
| Gerarchia | Si capisce in 3 secondi cosa si fa più spesso (CHIEDI) e cosa una volta a settimana; la dimensione e la posizione lo dicono, non il colore |
| Coerenza Onyx | Neutri, raggi, ritmo tipografico, stati hover/active/focus/disabled, header sticky, stati vuoti riconoscibili come Onyx; tabella token→token compilata |
| Uso dello spazio | A 1440 px nessuna colonna sprecata, a 820 px nulla di compresso; griglie fluide, misure di lettura sensate, contenuto che riempie senza affollare |
| Semplicità | Meno elementi di prima o uguali con più chiarezza; ogni controllo ha un solo scopo; nulla di decorativo |
| Stati | Attesa (skeleton), vuoto, non disponibile, errore di sessione, coda vuota, Casa provvisoria: tutti progettati, tutti testuali oltre che visivi |
| Accessibilità | WCAG 2.1 AA misurata: contrasto ≥ 4,5:1, focus a due anelli visibile su chiaro e scuro, ordine di tabulazione, reflow a 320 px, zoom 200 %, `prefers-reduced-motion` |
| Prestazioni | Lighthouse prestazioni ≥ 95, accessibilità 100, best practices 100; CLS 0; interattiva < 1 s su tablet medio; zero richieste a domini terzi |
| Movimento | Transizioni che orientano (dove sono andato, da dove vengo), ≤ 250 ms, mai su un bersaglio che si sta per premere; zero con reduced motion |
| Copy | Italiano semplice, terza persona, nessun imperativo verso persone, nessun gergo, nessuna emoji, nessun punto esclamativo; conteggi < 5 scritti `<5` |
| Manutenibilità | Un solo sistema di token, componenti riusati fra Home e area operatore, nessun numero magico, nessun `!important`, nessuno stile inline |

## 5. Vincoli non negoziabili

- **Nessun dato personale** nel browser: solo lo slug della Casa in `localStorage`; nessun log, nessun analytics, nessuna telemetria (V5).
- **Nessun imperativo verso persone o Case** in alcun testo dell'interfaccia (V6). Sono ammessi i nomi delle azioni sui controlli («Apri», «Invia come proposta») perché descrivono il controllo, non ordinano alla persona.
- **WCAG 2.1 AA** su tutte le pagine, misurata, non dichiarata. Testo base ≥ 16 px.
- **Zero richieste a terzi a runtime**: niente CDN, niente font remoti, niente icone da CDN, niente `https://` in `src`/`href` verso domini esterni salvo le destinazioni dichiarate (Onyx). Dipendenze di **build** sono ammesse; tutto ciò che arriva al browser è servito da Caddy dallo stesso origin.
- **Italiano semplice**, `lang="it"`.
- **Peso**: primo caricamento ≤ 100 KB compressi (HTML+CSS+JS) esclusi font e loghi; ogni font locale con `font-display: swap` e fallback con `size-adjust` per azzerare il CLS.
- **Nessun rosso come allarme** verso la persona: gli stati usano il vocabolario `status-*` di Onyx solo dove Onyx lo userebbe (errore di sessione, campo non valido), mai per «dati non disponibili».
- **Non toccare** `db/**`, `shim/**` (salvo coordinamento via `hub` con `trasi-shim` per l'HTML stampabile), `flussi/**`. Caddyfile e compose: solo via `trasi-stack`.

## 6. Stack: decisione guidata, non imposta

Scegli tu, ma applica questo procedimento e scrivilo nel decision log in ≤ 10 righe:
- Sono due pagine statiche con logica leggera dietro un proxy. La **base** è HTML semantico + CSS moderno con cascade layers e token in custom properties + JavaScript ES modules. Questo è il default; ogni cosa in più deve pagarsi in peso e complessità.
- **Ammesso e consigliato**: un passo di build minimale (Vite o equivalente) per bundling, minificazione, hashing degli asset, `postcss`/Lightning CSS per i fallback, output in `deployment/home/` o in una cartella `dist/` che Caddy serve. Ammesso Tailwind v4 **solo** se ti serve per replicare fedelmente il sistema di utilità di Onyx e resti nel budget; altrimenti token + classi semantiche.
- **Vietato**: React/Next/Vue per due pagine; librerie di icone esterne; librerie CSS complete; qualunque runtime > 15 KB compressi che non sostituisca codice che avresti scritto comunque.
- Icone: SVG inline sprite, prese o ridisegnate secondo lo stile del set curato di Onyx (`web/lib/opal/src/icons/`, tratto e griglia identici), sempre accanto alla parola.
- Font: verifica quale usa Onyx (`web/src/app/layout.tsx`, `globals.css`); se la licenza lo permette, vendorizzalo localmente e usalo; altrimenti scegli il fallback più vicino e motiva. Commissioner resta solo se dimostri che è più coerente, non per inerzia.
- Progressive enhancement obbligatorio: ogni API del §10 dietro `@supports` / feature detection; senza supporto la pagina funziona identica, solo senza transizione.

## 7. Processo in fasi, con gate

Ogni fase produce gli output indicati e chiude con autocritica scritta contro la rubrica §4. Le fasi 0 e 1 corrono in parallelo con subagenti read-only; dalla 2 in avanti sei tu.

**Fase 0 — Baseline (scout + tu).**
Leggi `deployment/home/**`, Caddyfile, compose, `shim/openapi.yaml` (solo gli endpoint usati dalle due pagine). Servi le pagine in locale (server statico, shim vero se raggiungibile o stub con le stesse risposte del contratto) e apri il **browser reale**: screenshot a 390×844, 820×1180, 1180×820, 1440×900, 1920×1080, più zoom 200 % e larghezza 320 px. Registra Lighthouse, axe, contrasto, ordine di tabulazione, peso, CLS. Output: `docs/ux-ui-revisione-<data>.md` §«Prima» con tabella schermata × problema (IA, gerarchia, spazio, stati, a11y, prestazioni), ognuno con screenshot ritagliato.

**Fase 1 — Estrazione delle regole Onyx (scout + tu).**
Clona `onyx-dot-app/onyx` a `v4.7.2` con sparse checkout di `web/AGENTS.md`, `web/lib/opal/`, `web/tailwind-themes/`, `web/src/app/globals.css`, `web/src/app/css/`, `web/src/refresh-components/`, `web/src/app/layout.tsx`, `web/src/app/auth/`, la cartella della chat. Apri anche l'istanza deployata nel browser e leggi i valori **computati** (font, dimensioni, raggi, colori, spaziature di sidebar/header/bottoni/messaggi). Output: `docs/onyx-regole-ui.md` con: scala neutra e semantica (`text-01…05`, `background-neutral/tint`, `border-01…05`, `action-selection`, `status-*`) con valori; preset tipografici (`heading-*`, `main-ui-*`, `secondary-*`) con size/line-height/weight; size variants (2xs…lg) di padding, rounding, altezza; matrice degli stati interattivi; larghezze contenitore; pattern header sticky + scroll shadow; pattern stato vuoto (illustrazione + titolo + descrizione); regole dei bottoni (variant × prominence); pattern chat (messaggio, compositore, fonti). Per ogni regola: file e riga di origine.

**Fase 2 — Sistema Trasi su regole Onyx.**
Un solo file di token (custom properties), struttura e nomi **paralleli** a Onyx (stessi livelli 01…05, stesse categorie), valori neutri ripresi da Onyx, `theme-primary` e accenti dai tre colori di marca. Tabella **token Onyx → token Trasi → valore → contrasto misurato** (script, non a occhio). Componenti: bottone (variant × prominence × size), campo, selettore, scheda, etichetta di stato, etichetta di provenienza, messaggio chat, compositore, tabella, stato vuoto, skeleton, testata, navigazione a linguette/sidebar, dialog/popover. Ognuno con tutti gli stati. Documentali in una pagina `deployment/home/sistema.html` (o equivalente in `dist/`) che è al tempo stesso guida di stile e banco di prova visivo.

**Fase 3 — Architettura dell'informazione e layout.**
Per ogni schermata: inventario dei contenuti, frequenza d'uso, gerarchia, regioni. Requisiti: CHIEDI dominante nella Home; «Oggi» e coda come stato in testa, mai come allarme; area operatore come **app shell** alla Onyx (navigazione laterale su ≥ 1180 px che diventa linguette in alto sotto, header sticky con ombra allo scroll, contenuto in contenitore `md`/`lg`); griglie `repeat(auto-fit, minmax(…, 1fr))` e container queries, tipografia fluida con `clamp()`, misure di lettura 60–75 caratteri, nessuna area vuota > 30 % a 1440 px, nessun controllo < 44 px. Facoltativo: se ritieni utile installa e usa Claude Design o Open Design per esplorare 2–3 varianti di layout **in questa fase soltanto**; se richiedono credenziali o rete non disponibili, procedi senza e annota. Output: wireframe in HTML (non immagini) per 3 breakpoint, scelta motivata.

**Fase 4 — Implementazione.**
Riscrivi HTML/CSS/JS delle due pagine sui componenti della Fase 2 e i layout della Fase 3. Mantieni **identici** i contratti con lo shim, la persistenza dello slug, il timeout di 3 s, il cookie di sessione, i link alle destinazioni. Applica il §10 (navigazione) e il §11 (copy). Stampa: foglio di stile `print` per la scheda evento e per tutto ciò che si stampa allo sportello. Nessun numero magico fuori dai token.

**Fase 5 — Verifica (stesso protocollo della Fase 0).**
Stessi viewport, stesse misure, stesse condizioni (shim su / shim giù / sessione scaduta / coda vuota / Casa provvisoria Tuturano). Requisiti: Lighthouse prestazioni ≥ 95, a11y 100, best practices 100; axe 0 violazioni; contrasto minimo ≥ 4,5:1 documentato; percorso tastiera completo registrato (elenco degli elementi nell'ordine di focus); CLS 0; log di rete dal browser con **zero** host esterni; bfcache idoneo (nessun `unload`, nessun `Cache-Control: no-store`); `prefers-reduced-motion` verificato; anteprima di stampa. Screenshot «dopo» in `deployment/home/evidenze/` al posto dei vecchi.

**Fase 6 — Critica a tre voci e iterazione.**
Scrivi tre revisioni indipendenti della versione implementata: (a) un'operatrice allo sportello con una persona davanti e trenta secondi, (b) un revisore di accessibilità, (c) un ingegnere delle prestazioni su tablet del 2019. Ogni voce elenca i 5 problemi più gravi. Correggi tutto ciò che sta sotto 4 nella rubrica e ripeti la Fase 5 sulle schermate toccate. Poi lancia `trasi-review` (read-only) sul risultato e incorpora o confuta punto per punto.

**Fase 7 — Consegna e pulizia.**
Vedi §13. Rimuovi script di prova, wireframe superati, `design/` legacy (o riscrivilo), commenti che descrivono il vecchio sistema. Aggiorna `deployment/README.md` se esiste un passo di build (comando esatto, dove finisce l'output, come Caddy lo serve). Riscrivi `deployment/home/WCAG.md` con le nuove misure.

## 8. Cosa «rubare» a Onyx, precisamente

- La **scala neutra** e la sua semantica a cinque livelli per testo, sfondo, bordo; come Onyx separa `background-neutral` da `background-tint`.
- I **preset tipografici** e il loro uso: cosa è `heading-h2`, cosa `main-ui-body`, cosa `secondary-body`; il rapporto fra dimensione, interlinea e peso.
- La **matrice degli stati interattivi** di `core/interactive/`: colori di hover, active, selected, disabled (`opacity-50`, `cursor-not-allowed`), e la regola che il disabilitato non sparisce.
- I **bottoni**: `variant` (default/action/danger/none) × `prominence` (primary/secondary/tertiary/internal) × `size`. Traduci in classi o attributi `data-*`; Trasi usa la stessa semantica.
- Il **layout di pagina**: contenitore centrato con larghezze fisse nominate, header sticky con ombra che appare allo scroll, corpo con spaziatura verticale costante; padding preferito ai margin.
- Lo **stato vuoto** come illustrazione + titolo + descrizione, centrato, misurato.
- Il **pattern chat**: allineamento dei messaggi, compositore ancorato, come Onyx mostra le fonti citate → l'etichetta di provenienza di Trasi vive lì, nello stesso posto e con lo stesso ritmo.
- L'**hover che rivela** con fallback `no-hover` per il tocco: su tablet le azioni sono sempre visibili.
- Le **icone**: stesso tratto, stessa griglia, stesso rapporto con il testo. Nessuna libreria esterna.
- Il **divieto** di colori Tailwind grezzi e di `dark:` puntuali: i colori passano solo dai token semantici. Trasi resta in tema chiaro, ma i token sono strutturati in modo da poter avere un tema scuro senza toccare i componenti.

Ciò che **non** si copia: la densità da strumento per sviluppatori dove l'operatore ha bisogno di respiro; le funzioni che Trasi non ha (sidebar di cronologia, pannelli admin); la lingua inglese.

## 9. Spazio e layout fluidi — requisiti concreti

- Griglia principale: `grid-template-columns: repeat(auto-fit, minmax(min(100%, <misura>), 1fr))`; container queries sui componenti (`@container`), non solo media query sulla pagina.
- Tipografia e spaziature fluide con `clamp()` fra i due estremi (390 px e 1440 px), passo di scala coerente con Onyx.
- `scrollbar-gutter: stable` sui contenitori scrollabili; `min-height: 100dvh` sull'app shell; `text-wrap: balance` sui titoli, `text-wrap: pretty` sui paragrafi.
- Larghezze contenitore nominate come Onyx (sm/sm-md/md/lg/full) e usate: Home in `md`, banco di lavoro in `lg` o `full` con colonne interne.
- Liste lunghe (messaggi, attrezzoteca): `content-visibility: auto` con `contain-intrinsic-size` misurato.
- Nessuna dimensione dipendente dal contenuto che possa spostare il layout dopo il caricamento: `width`/`height` sulle immagini, altezze minime sugli skeleton, `size-adjust` sul font di fallback.

## 10. Navigazione morbida — API native del browser, con fallback

- **View Transitions cross-document** fra `index.html` e `operatore.html`: `@view-transition { navigation: auto; }`, `view-transition-name` sulla testata e sul marchio così restano fermi mentre il contenuto cambia. Dietro `@supports (view-transition-name: a)`.
- **View Transitions same-document** per il cambio di linguetta/pannello nel banco di lavoro e per l'apertura degli stati (attesa → dati). Con `prefers-reduced-motion: reduce` la durata è 0 e la transizione non si registra.
- **Stato nell'URL**: la linguetta attiva vive nell'URL (`?pannello=chat` o hash); usa la **Navigation API** (`navigation.addEventListener("navigate", …)` con `intercept`) dove disponibile, altrimenti `history.pushState` + `popstate`. Indietro/avanti funzionano; il refresh riporta allo stesso pannello.
- **Speculation Rules** (`<script type="speculationrules">`) per `prefetch` di `operatore.html` dalla Home, conservativo: solo su hover/focus del link (`eagerness: moderate`).
- **bfcache** idoneo: nessun `unload`, nessuna connessione aperta al momento di lasciare la pagina, `pageshow` gestito per riaggiornare la riga «Oggi».
- **`<dialog>` e Popover API** per l'Aiuto, per conferme e per il selettore della Casa se diventa un menu: focus trap nativo, `Esc` nativo, `light-dismiss`. Nessun modal fatto a mano.
- **`@starting-style` + `interpolate-size: allow-keywords`** per far entrare pannelli e dettagli (`<details>`) senza JavaScript.
- **Scroll**: `scroll-behavior: smooth` solo dove c'è un salto interno, `scroll-margin-top` pari all'altezza dell'header sticky sugli anchor.
- **Focus dopo la navigazione**: al cambio pannello il focus va al titolo del pannello (`tabindex="-1"` + `focus()`), annunciato agli screen reader; mai lasciare il focus su un elemento sparito.
- **Tempi**: transizioni 150–250 ms, curva `ease-out` o quella che Onyx usa; nulla si muove sotto un dito che sta per premere.

## 11. Copy e lingua

Terza persona, descrittiva. Il sistema descrive, non ordina. Esempi vincolanti:

| Non si scrive | Si scrive |
|---|---|
| «Approva le proposte in attesa» | «3 proposte aspettano una decisione a San Bao» |
| «Errore: connessione fallita» | «Dati non disponibili: la memoria della rete non risponde in questo momento» |
| «Servizio disabilitato» | «Servizio non ancora attivo» |
| «Compila i campi obbligatori» | «Da dove viene l'informazione» (etichetta del campo) |
| «Seleziona la tua Casa» | «Casa di riferimento» |

Nomi delle quattro destinazioni in maiuscolo; «Casa», «Case di Quartiere» con la maiuscola; date `15/09/2026`, ore `11:42`, separatore `·`; conteggi sotto soglia scritti `<5`; niente emoji, niente punti esclamativi, niente metafore («cruscotto», «hub»). Una riga per gli stati; due-tre frasi per la descrizione di una destinazione. Verifica finale con una regex sui verbi imperativi rivolti a persone: 0 occorrenze nel codice servito.

## 12. Prove richieste (comandi e output reali nel report)

- Lighthouse (mobile e desktop) per ogni pagina, prima e dopo.
- axe: 0 violazioni, output allegato.
- Script di contrasto sui token effettivamente combinati (testo × sfondo): tabella con i rapporti.
- Ordine di focus: elenco degli elementi per pagina e pannello.
- Log di rete dal browser: elenco degli host contattati (solo l'origin e le destinazioni dichiarate).
- Peso: dimensioni compresse di HTML/CSS/JS per pagina.
- Scenari: shim fermo (→ «dati non disponibili» entro 3 s), sessione scaduta nell'area operatore, coda vuota, Casa «Tuturano» con dati provvisori, `prefers-reduced-motion`, zoom 200 %, larghezza 320 px, stampa.
- Screenshot «dopo» ai cinque viewport, stesso nome file dei «prima» con suffisso.

Ogni prova si esegue nel browser reale o con il comando indicato; niente «verificato» senza output.

## 13. Consegna

1. Codice in `deployment/home/` (o `dist/` servito da Caddy, con il passo di build documentato) — due pagine complete, componenti condivisi, token unici, `sistema.html`.
2. `docs/ux-ui-revisione-<data>.md`: «Prima» (Fase 0), «Regole prese da Onyx» (rimando a `docs/onyx-regole-ui.md`), «Sistema» (tabella token con contrasti), «Architettura dell'informazione» (cosa è cambiato e perché, cosa è rimasto e perché), «Navigazione» (quali API, con quali fallback, misurate), «Prove» (§12), «Rubrica» compilata per ogni schermata, **«Decision log»** (una riga per decisione: scelta · alternativa scartata · motivo · come si torna indietro), «Cosa non ho fatto e perché».
3. `deployment/home/WCAG.md` riscritto con le misure nuove.
4. `design/` riscritto sul nuovo sistema oppure rimosso; nessuna doppia verità.
5. Repository pulito: niente script di prova, wireframe superati, commenti sul vecchio sistema.

## 14. Anti-pattern (fermarsi se compaiono)

Sezione hero o copy da landing page · gradienti, vetro, blur, ombre decorative · colore come unico canale di stato · disabilitato grigio senza parola · emoji o icone da libreria esterna · layout in pixel fissi · animazioni > 250 ms o che spostano un bersaglio · navigazione solo JavaScript senza URL · modali fatti a mano · `!important`, stili inline, numeri magici · framework di applicazione per due pagine · richieste a terzi a runtime · testi che ordinano alle persone · rosso per «dati non disponibili» · «MVP», «v1», «TODO», «da completare» nel codice o nel report · decidere per inerzia (tenere una cosa perché c'era).

## 15. Definizione di fatto

Il lavoro è finito quando: ogni schermata è ≥ 4 su tutte le voci della rubrica con prova allegata; le prove del §12 sono nel report con output reali; la coerenza con Onyx è dimostrata dalla tabella token→token e da uno screenshot affiancato Trasi/Onyx per testata, bottoni, campo, messaggio chat, stato vuoto; il decision log è completo; il repository non contiene più il vecchio sistema né materiali di lavoro. Se un criterio è rosso, lo dici nel report con il motivo: non si dichiara fatto ciò che non lo è.
