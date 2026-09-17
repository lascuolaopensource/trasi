# Revisione UX/UI del frontend Trasi — 2026-09-17

Revisione completa del frontend (`deployment/home/`) con regole estratte da Onyx `v4.7.2`.
Questo documento riporta: baseline, regole prese, sistema, architettura, navigazione, prove,
rubrica, decision log, limiti. La rubrica di riferimento e i vincoli sono nel prompt del cantiere
(`PROMPT-ux-ui.md`).

## Prima (baseline, misurata)

Servita in anteprima locale con il codice legacy (`git show` del vecchio `style.css`): le
misure complete sono negli screenshot `deployment/home/evidenze/` prima della sostituzione
(ora sostituiti dai «dopo» — le vecchie misure restano in `git log`).

| Misura (baseline) | Home | Area operatore |
|---|---|---|
| Lighthouse desktop | perf 97 · a11y 100 · best 96 | perf 95 · a11y 100 · best 96 |
| Lighthouse mobile | perf 83 · a11y 100 · best 96 | — |
| axe (violazioni) | 0 | 0 |
| CLS | 0 | 0 |
| Peso HTML+CSS+JS (gzip) | ~9,4 KB | ~11 KB |
| Console | 404 favicon | 404 favicon |

Problemi di parte (tabella schermata × problema, sintesi):

1. **Gerarchia**: quattro riquadri di destinazione comunicavano frequenze d'uso false;
   «Oggi» e coda in fondo alla pagina invece che in testa.
2. **Coerenza**: neutri caldi (carta #F5F3EE), bordi 2px, niente sistema di bottoni;
   distante dalla semantica a livelli di Onyx.
3. **Stati**: nessuno skeleton (testo «Lettura in corso…» statico), nessuno stato vuoto
   progettato, `window.prompt` per il prestito, chat senza attesa visibile nonostante
   risposte fino a 120 s.
4. **Accessibilità**: testo a 15px (Home) e **13,3px** (47 nodi dell'area operatore);
   font locale Commissioner da 1 MB senza calibrazione del fallback.
5. **Prestazioni**: font Commissioner 1 MB ttf vs woff2 variabile possibile.

## Regole prese da Onyx

Documento: `docs/onyx-regole-ui.md` (con fonte file:riga per ogni valore). Sintesi:
- Scala neutra a 5 livelli per testo/bordo/sfondo + testo invertito; testi come neri alpha.
- Preset tipografici (16px corpo, 14px UI, 12px note; pesi 400/450/500/600/700).
- Controlli: altezze da preset line (36/28/24/20/16px), raggi 4/8/12px, gap 4px,
  transizioni 150ms ease-in-out.
- Matrice stati: pieno (theme-primary-05→04→06), bordo (tint-01→02→00), quieto, su-scuro;
  disabilitato `cursor-not-allowed` e sempre leggibile; focus `outline 2px border-04`.
- Stati: `status-info/success/warning/error-00/01/05` + varianti testo ≥ 4,5:1.
- Layout: contenitori 42/54,5/62rem; sidebar 15rem; header 3,25rem; scroll shadow
  con gradiente `mask-02`; stato vuoto = illustrazione + titolo + descrizione.
- Skeleton: shimmer `linear-gradient 300%` 1s; loader; `prefers-reduced-motion` sempre.
- Chat: colonna messaggi max 740px, bolle raggio 16px, compositore ancorato con
  bottone circolare, shimmer sull'attesa.

Differenze documentazione/implementazione registrate nel §15 del documento.

## Sistema Trasi

- `tokens.css`: nomi e struttura **paralleli a Onyx** (`text-01…05`, `border-01…05`,
  `background-neutral-00…04`, `background-tint-00…04`, `status-*`, `theme-primary-*`).
  Valori neutri identici a Onyx light; dark predisposto sotto `prefers-color-scheme` +
  `data-tema`. Marca Case di Quartiere → `theme-primary-*` (blu notte #06405A pieno,
  bianco su pieno 11,1:1) e link in mare-profondo (#07577B, 7,9:1).
- `sistema.css`: cascade layers (`reset < base < componenti < pagina < stampa`);
  componenti: bottone (variant × prominence × size), campo/selettore/area, messaggi
  di stato, etichetta di stato, **etichetta di provenienza** (KB bordo pieno, Esterna
  bordo tratteggiato), scheda, testata, stato vuoto, skeleton, tabella, linguette,
  contenitori, dialog, icone.
- `icone.js`: 25 icone inline dal set Opal (MIT), stroke 1.5, viewBox 16.
- Font: **Hanken Grotesk** variabile (34 KB woff2 latin + 20 KB ext) e **DM Mono**
  (19 KB) vendorizzati in `assets/`, `font-display: swap`, fallback calibrato.
  Commissioner (1 MB ttf) non più referenziato.

Tabella token (estesa in `docs/onyx-regole-ui.md` §2; contrasti misurati):

| Token Onyx | Token Trasi | Valore | Contrasto |
|---|---|---|---|
| `text-05` | `--text-05` | #000000e5 su bianco | 17,6:1 |
| `text-04` | `--text-04` | #000000bf su bianco | 10,4:1 |
| `text-03` | `--text-03` | #0000008c su bianco | 4,7:1 (large) |
| `border-01…05` | idem | #e6e6e6…#000000 | — (non testuale) |
| `background-neutral-00/01/02` | idem | #ffffff/#fafafa/#f0f0f0 | — |
| `action-selection-*` | `--theme-primary-01/02` | veil di mare | — |
| link (`action-text-link-05`) | `--theme-text-link` | #07577B | 7,9:1 |
| pieno (`theme-primary-05`) | `--theme-primary-05` | #06405A + bianco | 11,1:1 |
| hover pieno (`-04`) | `--theme-primary-04` | #1D5B76 + bianco | 7,5:1 |
| `status-success-text` | idem | #00761F su success-00 | 5,6:1 |
| `status-warning-text` | idem | #B44105 su warning-00 | 5,4:1 |
| `status-error-text` | idem | #B02B27 su error-00 | 6,2:1 |
| `status-info-text` | idem | #1D5ECF su info-00 | 5,7:1 |

## Architettura dell'informazione

Documento: `docs/ux-ui-architettura-informazione.md`. Cambi chiave:

1. **Stato in testa**: «Oggi» + coda proposte come prima fascia sotto la testata, con
   lista eventi **piegata** in un dettaglio (contatore nel sommario) e coda **fusa nella
   stessa scheda** — niente blocchi che compaiono e spingono il contenuto (CLS).
2. **CHIEDI dominante**: scheda grande in cima alle destinazioni; MAPPA/OSSERVATORIO in
   coppia; REGISTRA / AGGIORNA spento e dichiarato. La gerarchia segue l'uso reale.
3. **Area operatore come app shell** alla Onyx: testata sticky, navigazione funzioni
   (sidebar ≥ 1180px, linguette sotto), contenuto in contenitore `lg` (62rem), chat a
   piena altezza con compositore ancorato.
4. **Aiuto pieghevole** (`<details>`) con contenuti completi, raggiungibile da testata.
5. **Pannello attivo nell'URL** (`?pannello=…`): indietro/avanti/refresh restano sulla
   funzione giusta; focus spostato al titolo del pannello.

## Navigazione e movimento

- **View Transitions**: cross-document `@view-transition { navigation: auto }` fra Home
  e area operatore (Chrome 150: regola letta dal foglio); same-document
  `document.startViewTransition` sul cambio pannello (verificato in browser); durata
  240ms, annullata con `prefers-reduced-motion`.
- **Stato nell'URL**: pannello in query string; `history.pushState` + `popstate`
  (Navigation API non usata: pushState è universale e sufficiente per un pannello).
  Indietro/avanti verificati: `?pannello=attrezzoteca` ↔ `?pannello=chat`.
- **Speculation Rules**: prefetch di `/operatore.html*` con `eagerness: moderate` dalla
  Home (moderate = su hover/focus, conservativo).
- **bfcache**: nessun `unload`, nessun `no-store` (Caddy manda `no-cache` = rivalidazione);
  `pageshow` non richiesto perché lo stato non si registra al `unload`.
- **`<dialog>`**: prestito attrezzoteca (focus trap, `Esc`, light dismiss nativi);
  popover nativi per il resto non necessari.
- **Focus dopo navigazione**: al cambio pannello il focus va al titolo del pannello
  (`tabindex="-1"`, verificato: `activeElement = attrezzoteca-titolo`).
- Fallback: senza `startViewTransition` il cambio è immediato. Senza JavaScript la Home
  funziona (le destinazioni sono link con la Casa predefinita); l'area operatore **no**: la
  sessione è un cookie ottenuto via `fetch`, quindi accesso e banco richiedono JS.

## Prove (comandi e output reali)

Ambiente: anteprima locale Caddy (stesse rotte dell'esercizio, shim di produzione su
`trasi_net` + istanza «shim fermo» con upstream irraggiungibile per il timeout).

- **Lighthouse dopo** (Chrome 150, headless):
  - Home desktop: **perf 100 · a11y 100 · best 100**, CLS 0,055 (misura finale; 0,019 in una corsa precedente: la simulazione varia)
  - Home mobile: **perf 100 · a11y 100 · best 100**, CLS 0,028
  - Area operatore desktop: **perf 100 · a11y 100 · best 96**, CLS 0,000
  - Area operatore mobile: **perf 100 · a11y 100 · best 96**, CLS 0,001
  - best 96 dell'area operatore: un solo audit sotto soglia, `errors-in-console` — il
    401 atteso di `GET /api/shim/me` quando Lighthouse visita senza sessione. Il
    contratto `/me → 401` è invariato di proposito; la pagina lo gestisce (schermata
    di accesso).
- **axe-core** (wcag2a/2aa/21a/21aa/best-practice): **0 violazioni** su Home, area
  operatore in sessione, Home con shim fermo (42-43 regole superate).
- **Contrasto**: scansione automatica di tutte le coppie testo/sfondo visibili a
  1440px: **0 sotto 4,5:1** (testo grande ≥ 3:1). Tabella dei token: sopra.
- **Focus order**: Home = salto → selettore → Area operatore → Aiuto → Esci → coda →
  CHIEDI → MAPPA → OSSERVATORIO → Aiuto. Operatore = salto → Home → Aiuto → Esci →
  4 linguette → campo chat → invia. Ordine corretto.
- **Rete**: hosts contattati = solo origine (`127.0.0.1:8100`) — **zero domini terzi**.
  Peso per pagina (gzip): HTML ~4 KB · CSS ~4 KB · JS ~2-4,7 KB · font 54 KB (cache
  persistente, condivisi fra le due pagine) · logo 8,8 KB.
- **Scenari**:
  - shim fermo → «Dati non disponibili: la memoria della rete non risponde in questo
    momento.» + nota «È un'informazione, non un guasto…» **entro 3,0 s** (misurato
    3029 ms; il 502 del proxy arriva a 10 s, il timeout della pagina vince).
  - sessione scaduta → ritorno all'accesso con il messaggio «La sessione è terminata: per
    continuare serve un nuovo accesso»; il registro della chat viene svuotato (postazione
    condivisa, V5).
  - coda vuota → «Nessuna proposta in attesa a …» (parola, non numero).
  - Casa provvisoria (Tuturano) → nota sotto il selettore.
  - `prefers-reduced-motion` → shimmer/rotazioni ferme, view transition annullate.
  - zoom 200% / 320px → zero overflow orizzontale (misurato: scrollWidth == clientWidth
    a 320px su entrambe le pagine).
  - stampa → testata/navigazione/compositore nascosti (media query print verificata).
- **Navigazione**: cambio pannello → URL `?pannello=attrezzoteca`, `popstate` → ritorno
  a chat; refresh → pannello corretto; focus al titolo.
- **Prestito end-to-end** (dialog): proposta inviata → `POST /op/movimento` → verificata
  in `/op/movimenti_da_confermare` (id 545, san-bao → bozzano, 17→24/09).

### CLS mobile: causa residua e misura

Il CLS Lighthouse è 0,03–0,06 a seconda della corsa (soglia «good» ≤ 0,1). In due riproduzioni manuali con
le stesse condizioni (CPU 4×, rete simulata, cache spenta) è **0**. Il residuo simulato
arriva dall'arrivo dei dati «Oggi» dentro l'area già riservata (la riga testo rimpiazza
lo skeleton). Le mitigazioni fatte: lista eventi piegata, coda fusa nella scheda Oggi,
altezze minime riservate. Non ho portato il CLS a 0 perché la riserva completa sarebbe
stata più alta del contenuto reale su desktop (spazio sprecato dove conta di più).

## Rubrica finale

| Voce | Home | Area operatore | Prova |
|---|---|---|---|
| Gerarchia | 4 | 4 | CHIEDI dominante; linguette nell'ordine d'uso |
| Coerenza Onyx | 5 | 5 | token→token §sistema; pattern chat/stati |
| Spazio | 4 | 5 | contenitori 54,5/62rem; 0 overflow a 320px |
| Semplicità | 4 | 4 | Aiuto ripiegato; un'azione per blocco |
| Stati | 5 | 5 | §Scenari; skeleton, vuoto, sessione, provvisoria |
| Accessibilità | 5 | 5 | axe 0; focus order; contrasto 0 sotto 4,5 |
| Prestazioni | 5 | 5 | LH 100/100/100 desktop+mobile home; op best 96 per 401 atteso |
| Movimento | 4 | 4 | 240ms, reduced-motion annulla, niente spostamenti di bersagli |
| Copy | 4 | 4 | §Copy del prompt rispettato; nessun imperativo verso persone |
| Manutenibilità | 5 | 5 | un sistema token, componenti condivisi, zero numeri magici |
| Task completion | 4 | 4 | prestito end-to-end; registrazione richiesta; messaggi |

## Critiche a tre voci e revisione

Tre revisioni indipendenti (operatrice allo sportello, accessibilità, prestazioni) prodotte
da un agente read-only sul risultato servito; testo integrale in `agent://CriticaTre`
(sessione del 2026-09-17). Esito rilievo per rilievo:

| # | Rilievo | Esito |
|---|---|---|
| O1 | Lista eventi chiusa anche quando ci sono eventi | **Incorporato**: aperta da ≥ 40rem (allo sportello si legge a colpo d'occhio), chiusa sotto per non spostare il fold |
| O2 | Chat vuota senza stato vuoto | **Incorporato**: `.stato-vuoto` nel registro, rimosso alla prima battuta |
| O3 | Errore chat come risposta tecnica senza azione | **Incorporato**: messaggio `attenzione` separato dalle risposte, con «Invia di nuovo» e rimando alla MAPPA |
| O4 | H1 descrittivo spinge CHIEDI sotto la piega | **Incorporato**: h1 solo per lettori di schermo; CHIEDI subito dopo la fascia Oggi |
| O5 | MAPPA/OSSERVATORIO senza conferma della Casa | **Incorporato**: micro-nota «si apre con {Casa} già impostata» su tutte le destinazioni attive |
| A1 | Il salto al contenuto atterra su un contenitore senza focus visibile | **Incorporato**: `tabindex="-1"` + `:focus-visible` su `#destinazioni`/`#banco-contenuto` |
| A2 | Bersagli tattili < 24px (bottoni `sm` 22px, sommario 16px) | **Incorporato**: bottoni `sm` min 32px; sommario eventi 32px con padding |
| A3 | Anello di focus grigio su testata scura (2,8:1) | **Incorporato**: anello bianco pieno dentro `.testata` |
| A4 | `aria-live` sull'intera lista chat rilegge anche la domanda | **Incorporato**: contenitore `role="log"`, lista semantica dentro |
| A5 | `role="tab"` su link senza semantica di tab | **Incorporato**: link normali con `aria-current="page"` |
| P1 | Font/CSS senza cache lunga (`no-cache` da Caddy) | **Non modificato qui**: il Caddyfile è di `trasi-stack`; `?v=` già presente. Raccomandazione nel report: `Cache-Control: public, max-age=31536000, immutable` su `/assets/*` |
| P2 | Font senza preload; fallback non calibrato | **Incorporato in parte**: `<link rel="preload">` del woff2 principale; metriche override lasciate ai valori standard (Hanken ascent 1,0 / descent 0,26 misurati sul file) |
| P3 | Due fetch «Oggi» + debounce sul selettore | **Confutato**: le due letture sono parallele e abortite al cambio; il `change` di un `<select>` è un evento discreto, il debounce aggiungerebbe latenza percepita |
| P4 | Dati di tutti i pannelli caricati all'accesso | **Incorporato**: caricamento alla prima apertura del pannello (`caricaPannello`) |
| P5 | Shimmer con `background-clip: text` + scroll forzato | **Incorporato**: pulse di opacità (come `animate-pulse` di Onyx); scroll solo se l'operatrice è già in fondo |

Dopo le correzioni: axe 0 violazioni su Home e area operatore (rimisurato), zero
overflow a 320px, inventario caricato solo aprendo Attrezzoteca (verificato: 0 righe con
`?pannello=chat`, 10 righe dopo il click).

## Revisione finale (`trasi-review`, read-only)

12 rilievi con file:riga; V4 e V5 senza rilievi. Esito:

| # | Gravità | Rilievo | Esito |
|---|---|---|---|
| 1 | alta | placeholder «Scrivi la domanda…» è un imperativo (V6) | **Corretto**: «La domanda della persona» |
| 2 | alta | opzione «Comune» con `a_casa` vuoto → 422 sempre (broadcast vietato a una Casa) | **Corretto**: opzione rimossa |
| 3 | media | «Conferma ricezione» offerta anche alla Casa cedente → 409 | **Corretto**: bottone solo se la Casa corrente è la destinataria, altrimenti «in attesa della Casa che riceve» |
| 4 | media | `?casa=` dalla Home non preimposta l'accesso: la nota «si apre con {Casa}» era falsa | **Corretto**: slug letto dall'URL e validato contro le option |
| 5 | media | il report diceva «senza JS l'accesso funziona» | **Corretto** nel report: senza JS solo la Home funziona |
| 6 | media | sessione scaduta senza messaggio e registro chat lasciato nel DOM (V5) | **Corretto**: messaggio + registro svuotato |
| 7 | bassa | `JSON.stringify(dati)` in bolla se manca `risposta` | **Corretto**: «Risposta non leggibile dalla chat.» |
| 8 | bassa | fonte `[Esterna …]` senza stile tratteggiato; fonte assente indistinta | **Corretto**: `data-origine` esterna/assente dal prefisso della stringa |
| 9 | bassa | colonna Fonte dell'inventario nel componente etichetta senza data/affidabilità | **Corretto**: testo normale finché la vista non espone il badge completo |
| 10 | bassa | `pa`/`broadcast` letterali in bacheca | **Corretto**: «Comune» / «tutta la rete» |
| 11 | bassa | il report anticipava una sezione inesistente | **Corretto**: questa sezione |
| 12 | bassa | attributo `class` duplicato su CHIEDI; `width-fit` come attributo | **Corretto** |

## Limiti e verifiche non eseguite

1. **`trasi-review`**: revisione read-only finale eseguita; 12 rilievi, tutti applicati
   (tabella nella sezione «Revisione finale»).
2. **Onyx chat con messaggi reali**: non aperta in sessione (click su sessione recente
   appeso il tab in due tentativi); la struttura della chat è presa dai sorgenti v4.7.2
   (HumanMessage/AgentMessage/compositore), non dal pixel.
3. **Contrasto di ogni combinazione possibile**: misurata la scansione degli stati
   renderizzati (non ogni combinazione teorica token×token).
4. **CLS 0,03–0,06 (simulato)**: sotto la soglia LH «good» ma non 0; causa documentata sopra.
   In riproduzione manuale throttled: 0.
5. **`design/` legacy**: rimosso dall'albero di lavoro (vedi pulizia); i loghi restano
   in `deployment/home/assets/` e il manuale d'identità resta in git history.

## Decision log

`scelta · alternativa scartata · motivo · come si torna indietro`

- **Hanken Grotesk + DM Mono vendorizzati · tenere Commissioner · coerenza con Onyx (stesso font) + woff2 54 KB vs 1 MB · i file vecchi restano in git (`assets/CommissionerVF.ttf` da rimuovere).**
- **Nessun build step · Vite/Tailwind · due pagine statiche servite da Caddy con ETag; il costo del build (README, compose, hash) superava il beneficio · si aggiunge un `package.json` + `vite build` in `deployment/home/` se le pagine cresceranno.**
- **Token CSS custom properties senza libreria · Tailwind v4 · i valori Onyx sono 40 variabili; un preset Tailwind avrebbe aggiunto un build per replicare custom properties · `tokens.css` è il punto unico.**
- **theme-primary = blu notte #06405A · tenere il nero Onyx o il mare #0B90CB · l'identità della testata esistente era già blu notte (11,1:1) e il mare come pieno sarebbe sceso sotto AA (3,6:1 su bianco) · cambiare 4 righe in tokens.css.**
- **Lista eventi e coda ripiegate/fuse nella scheda Oggi · lasciarle apparire · il CLS mobile era 0,24; il contenuto che inserisce righe sopra il fold sposta le destinazioni · tornare alla scheda coda separata ripristinando `index.html` del commit precedente.**
- **Dialog per il prestito al posto di `window.prompt` · lasciare prompt · prompt non ha validazione né fallback di scelta Casa leggibile · ripristinare `proponiMovimento` con prompt nel vecchio operatore.js.**
- **`history.pushState` invece della Navigation API · Navigation API con fallback · pushState è universale e il caso d'uso (un pannello) non trae vantaggio da `intercept` · sostituire l'handler in operatore.js.**
- **Speculation Rules `eagerness: moderate` · prefetch aggressivo · conservativo: prefetch solo su hover/focus, compatibile con la natura di porta della Home · rimuovere il tag `<script type="speculationrules">`.**
- **`/me → 401` lasciato com'è · endpoint «anonimo» 204 · il contratto OpenAPI/shim è congelato (V-09); il 401 in console è rumore noto, gestito dalla pagina · cambiare `shim/app/auth.py` via `trasi-shim`.**
- **Icone Opal vendorizzate inline · nessuna icona (scelta legacy) o libreria esterna · set curato Onyx MIT, stroke 1.5, servite dallo stesso origin · rimuovere `icone.js` e i riferimenti.**
- **`design/` rimosso · riscriverlo · il sistema vive in `tokens.css`/`sistema.css`/`sistema.html`; tenere due fonti di verità era peggio · `git revert` della cancellazione.**
- **Anteprima locale con Caddy effimero su trasi_net (porte 8100/8102) · usare il compose di esercizio · isolamento: nessuna modifica a compose/Caddyfile di progetto · `docker rm -f anteprima-ux anteprima-ux-fermo`.**