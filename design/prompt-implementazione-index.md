# Prompt — implementazione index.html (Trasi)

Costruisci un prototipo web completo per "Trasi", la piattaforma delle Case di Quartiere del Comune di Brindisi,

## Vincoli tecnici
- Un solo file index.html: `<style>` con tutto il CSS inline, `<script>` con tutto il JS inline, sprite SVG delle icone inline nel `<body>` (nessun file .svg esterno).
- Font: Commissioner (Google Fonts), pesi 400/500/600/700/900.
- Icone: stile Lucide (coerente con l'iconset di shadcn/ui) — stroke 2px, viewBox 24x24, linecap/linejoin round — incorporate come sprite `<svg style="display:none"><symbol id="icon-...">` e richiamate con `<use href="#icon-...">`. NON usare riferimenti a file esterni per le icone (rompono su file://).
- È una SPA a "viste multiple" nello stesso file: ogni pagina è una `<section class="view" id="view-nome" hidden>`; una funzione JS `showView(nome)` nasconde tutte le view e mostra quella richiesta (usa l'attributo nativo `hidden`, senza bisogno di CSS aggiuntivo). La navigazione (sidebar, header, form login) usa `data-nav="nome"` intercettato da un listener delegato su `document`, con `preventDefault()`.
- Mappa: Leaflet + tile CARTO "light_all" (gratuiti, no API key), inizializzata SOLO al primo accesso alla vista mappa (lazy init), con `invalidateSize()` richiamato ad ogni successivo accesso alla vista (il container è dentro una sezione nascosta all'avvio, quindi Leaflet non può misurarla prima).

## Design system
Palette (CSS custom properties):
- `--color-background: #DFEFF5` (celeste chiaro, sfondo pagina)
- `--color-primary: #0D5063` (teal scuro, sidebar/testo enfasi) / hover `#0A3F4E`
- `--color-secondary: #F0821D` (arancio, CTA/accenti) / hover `#D66F0E`
- `--color-card: #FFFFFF`
- `--color-muted: #EAF3F6`, `--color-muted-foreground: #6B6B69`
- `--color-accent: #DFEFF5` su foreground `#0D5063`
- `--color-border: #CFE1E7`
- `--color-focus-bg: #CDE7EE` (usato SOLO per il focus degli input, vedi sotto)

Spacing: scala rigorosamente a multipli di 8, definita come token riutilizzati ovunque (niente valori arbitrari come 6/10/12/18/20px sparsi nel CSS):
`--space-1:8px --space-2:16px --space-3:24px --space-4:32px --space-5:40px --space-6:48px --space-7:56px --space-8:64px`

Radius: sm 8px, md 12px, lg 16px, full 999px.
Ombre: tinte di teal (non nero puro), es. `0 1px 3px rgba(13,80,99,.08)` per le card, più marcate per i drawer.

Stile generale: evitare l'estetica "da IA generica" — bordi netti + ombre morbide invece di flat design piatto, badge con maiuscolo/letter-spacing, indicatore di stato attivo nella sidebar come barra laterale (non blocco pieno), tipografia con tracking leggermente negativo sui titoli.

## Componenti chiave
- **Bottoni**: varianti primary (arancio/bianco), secondary (teal/bianco), outline, ghost. Mai sottolineati.
- **Input/select**: bordo 1.5px, altezza 48px. Stato focus: NIENTE cambio di bordo, solo `background: var(--color-focus-bg)`.
- **Dropdown custom** (per selettore case di quartiere e select nell'area operatore): trigger + pannello flottante con ombra, voci con hover e check icon sulla selezione, apertura/chiusura via `data-dropdown`/`data-dropdown-trigger`/`data-dropdown-panel`/`data-dropdown-item`, chiusura su click esterno o Esc.
- **Sidebar app** (240px espansa / 72px compressa): identica in spaziatura e struttura in tutte le pagine autenticate, con pulsante toggle funzionante (comprime/espande), logo testuale "Trasi" da espansa e SOLO il marchio/icona (logo SVG fornito, non testo "T") da compressa.
- **Card evento**: sfondo bianco distinto dallo sfondo pagina (mai trasparente/uguale al background), bordo + ombra leggera, data in formato "14.10" grande senza riquadro colorato attorno, titolo evento grande (18px+), hover con leggero sollevamento e freccia che si sposta per segnalare che è cliccabile.
- **Drawer evento** (da destra, overlay scuro dietro): blocco immagine mostrato SOLO se l'evento ha un'immagine (altrimenti niente placeholder), titolo grande (30px), meta data/luogo con icone, descrizione, CTA esterna opzionale.
- **Drawer mappa**: due pannelli sovrapposti esattamente nella stessa posizione/dimensione (in alto a destra, larghezza = 1.5x quella della sidebar espansa) — uno con la lista delle case di quartiere (aperto di default al caricamento), uno con il dettaglio della casa selezionata (orari, servizi, operatori, prossimi eventi), con pulsante per tornare alla lista.

## Viste da implementare (in quest'ordine nel documento)
1. **Loading** (prima vista visibile, le altre `hidden`): logo grande su sfondo teal, dopo ~1s fade-out e passaggio automatico a Calendario.
2. **Calendario (pre-login, pubblica)**: header con logo SVG completo (icona+wordmark) a sinistra e bottone "Accedi" a destra (sfondo arancio, testo bianco, nessuna sottolineatura); sotto, un dropdown per scegliere la casa di quartiere; lista eventi (card come sopra); click su un evento apre il drawer evento.
3. **Login**: card centrata con email, password, "password dimenticata", bottone Accedi (invio del form passa alla vista Home senza reload).
4. **Home** (autenticata): sidebar + lista eventi della casa di quartiere dell'utente + bottone "Proponi evento"; stesso drawer evento condiviso con Calendario (un'unica istanza nel DOM, non duplicata).
5. **Utente** ("La tua casa"): sidebar + card info (indirizzo, telefono, operatori) + report mensile con stat tile.
6. **Area Operatore**: sidebar + tab (Registra richiesta / Attrezzoteca / Messaggi interni), ognuna con form che usa i dropdown custom sopra descritti.
7. **Mappa**: sidebar + mappa OpenStreetMap reale (Leaflet, tile CARTO) centrata su Brindisi (40.632, 17.937), tile ricolorati via filtro CSS (`sepia + hue-rotate + saturate`) per avvicinarli alla palette del brand; marker circolari teal (arancio se selezionati) su 5-6 case di quartiere con coordinate plausibili nei quartieri di Brindisi (Bozzano, Sant'Elia, Casale, Paradiso, San Bao, Centro); click su marker o su una riga della lista fa lo zoom sulla sede e mostra il drawer di dettaglio.

## Attenzione a bug noti da evitare
- Le icone via `<use href="file.svg#id">` NON funzionano se il file viene aperto come file:// (blocco cross-document del browser): usare SEMPRE sprite inline nello stesso documento.
- I pannelli interni di Leaflet hanno z-index fino a 700+: dare al contenitore della mappa un proprio `z-index` esplicito (es. `z-index:0`) per creare uno stacking context che li contenga, altrimenti la mappa copre i drawer sovrapposti.
- Il pulsante di toggle della sidebar deve agire sulla sidebar più vicina (`closest()`), non su una query globale, perché nel documento coesistono più sidebar (una per vista).
- L'unica istanza di drawer evento + overlay va condivisa a livello di documento (fuori dalle singole `<section class="view">`), non duplicata per ogni vista che mostra eventi.

