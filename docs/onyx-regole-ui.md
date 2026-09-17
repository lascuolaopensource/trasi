# Regole UI di Onyx v4.7.2 — estratto per il sistema Trasi

Fonti: sorgenti `github.com/onyx-dot-app/onyx` tag `v4.7.2` (clone in `/tmp/onyx-v4.7.2`,
lettura del 2026-09-17) e istanza deployata `http://127.0.0.1:3000` (valori computati,
accesso con l'account di servizio `op.san-bao@trasi.local`). Ogni valore porta la fonte.
I token di colore, tipografia e dimensione sono definiti in `web/lib/shared/tokens/*.json`
(compilati da style-dictionary) e in `web/lib/opal/tailwind-preset.cjs`; le variabili CSS
corrispondono ai nomi del preset. Le righe citate sono del clone.

## 1. Font

| Token | Valore | Fonte |
|---|---|---|
| Testo | Hanken Grotesk (Google Fonts, OFL), subset latin, `display: swap`, fallback `-apple-system, Segoe UI, Roboto` | `web/src/app/layout.tsx:15,31-34` |
| Monospace | DM Mono 400, fallback `SF Mono, Monaco, Cascadia Code, Roboto Mono, Consolas` | `web/src/app/layout.tsx:15,38-45` |
| Variabile CSS | `--font-hanken-grotesk` composta in `layout.tsx:81` con coda CJK per locale | `web/src/app/layout.tsx:72-81` |
| `public/fonts` | solo KHTeka (Medium/Regular) per casi speciali desktop; non è il font UI | `web/public/fonts/` |

Licenza: Hanken Grotesk è OFL (Google Fonts); vendorizzabile. Il repo Onyx è MIT
(`LICENSE`: "Copyright (c) 2023-present DanswerAI, Inc."; le parti `ee/` sono escluse);
`web/lib/opal/package.json:5` dichiara `"license": "MIT"`.

## 2. Colori — scala neutra e semantica

Definizione: `web/lib/shared/tokens/primitives.json` (scala `grey-00…grey-100`) e
`semantic-light.json` / `semantic-dark.json`; esposizione Tailwind in
`web/lib/opal/tailwind-preset.cjs` (`colors` → `var(--token)`). Risoluzione dei riferimenti
`{grey-XX}` e `{alpha-grey-...}` verificata programmaticamente.

### Scala neutra (primitives.json)

`grey-00 #ffffff · 02 #fafafa · 04 #f5f5f5 · 06 #f0f0f0 · 08 #ebebeb · 10 #e6e6e6 · 20 #cccccc ·
30 #b2b2b2 · 40 #a4a4a4 · 50 #808080 · 60 #555555 · 70 #4d4d4d · 75 #404040 · 80 #333333 ·
85 #262626 · 90 #1a1a1a · 92 #141414 · 94 #0f0f0f · 96 #0a0a0a · 98 #050505 · 100 #000000`

I testi usano **neri alpha** su chiaro: `text-0N` = nero con alpha (vedi sotto), così il colore
adatta al fondo. `alpha-grey-100-90` = `#000000e5` (primitives.json).

### Light (default Trasi)

| Token | Valore | Uso |
|---|---|---|
| `text-01` | `#00000033` | disabilitato/suggerimento leggerissimo |
| `text-02` | `#00000073` | placeholder |
| `text-03` | `#0000008c` | testo secondario |
| `text-04` | `#000000bf` | testo principale attenuato |
| `text-05` | `#000000e5` | testo principale |
| `border-01` | `#e6e6e6` | filetti, divisori |
| `border-02` | `#cccccc` | bordi di default (input, bottoni secondary) |
| `border-03` | `#a4a4a4` | bordi forti, anelli focus |
| `border-04` | `#808080` | focus ring (`outline 2px`) |
| `border-05` | `#000000` | bordo pieno |
| `background-neutral-00` | `#ffffff` | pagina |
| `background-neutral-01` | `#fafafa` | superfici alte |
| `background-neutral-02` | `#f0f0f0` | hover righe |
| `background-neutral-03` | `#e6e6e6` | disabled bg |
| `background-neutral-04` | `#cccccc` | disabled bg pieno |
| `background-tint-00` | `#ffffff` | pressato |
| `background-tint-01` | `#fafafa` | scheda/pagina con header sticky |
| `background-tint-02` | `#f0f0f1` | hover secondary |
| `background-tint-03` | `#e6e6e9` | — |
| `background-tint-04` | `#cccccf` | — |
| `action-selection-01` | `#e7effc` | selezione (bg) |
| `action-selection-02` | `#cddfff` | selezione hover |
| `action-selection-05` | `#286df8` | selezione piena |
| `action-text-link-05` | `#286df8` | link |
| `action-danger-05` | `#dc2626` | pericolo pieno |
| `status-info-00/01/05` | `#f8fafe / #e7effc / #286df8` | info |
| `status-success-00/01/05` | `#f8fbf8 / #e6f2e7 / #00a43f` | successo |
| `status-warning-00/01/05` | `#fef9f7 / #fbeae4 / #ec5b13` | attenzione |
| `status-error-00/01/05` | `#fef7f6 / #fceae7 / #dc2626` | errore |
| `status-text-success-05` | `#008933` | testo successo (≥ 4.5:1) |
| `status-text-warning-05` | `#ce4b05` | testo warning (≥ 4.5:1) |
| `status-text-error-05` | `#dc2626` | testo errore |
| `status-text-info-05` | `#286df8` | testo info |
| `theme-primary-04/05/06` | `#333333 / #1c1c1c / #000000` | tema (Onyx default: nero) |
| `shimmer-base / -highlight` | `#a3a3a3 / #000000` | skeleton testo |
| `mask-02` | `{alpha-grey-100-20}` = nero 20 % | gradiente scroll shadow |

Dark mode (`semantic-dark.json`, tabella completa per un futuro tema): `text-*` = bianco con le
stesse alpha (`#ffffff33…f2`), `border-01 #333333`, `border-02 #555555`, `border-04 #b2b2b2`,
`background-neutral-00 #000000`, `01 #1a1a1a`, `02 #262626`, `03 #333333`, `04 #404040`,
`background-tint-01 #19191e`, `02 #26262b`, `action-selection-05 #286df8` (invariato),
`action-text-link-05 #397bff`, `status-error-05 #dc2626` (invariato), `status-text-danger #f23a36`.

Struttura da copiare: **cinque livelli testuali, cinque di bordo, cinque di sfondo**, semantica
speculare (`inverted`), status a gradini `00/01/02/05`. A Trasi i grigi restano Onyx; i tre colori
di marca (mare/sole/terra) entrano come `theme-primary-*`/accenti senza toccare i neutri.

## 3. Tipografia

Preset in `web/lib/shared/tokens/typography-presets.json` (family Hanken Grotesk):

| Preset | size / line-height | weight | letter-spacing |
|---|---|---|---|
| `heading-h1` | 48px / 64px | 600 | −0.48px |
| `heading-h2` | 24px (1.5rem) / 36px | 600 | −0.24px |
| `heading-h3` | 18px / 28px | 600 | −0.18px |
| `heading-h3-muted` | 18px / 28px | 500 | −0.18px |
| `main-content-body` | 16px / 24px | 450 | 0 |
| `main-content-emphasis` | 16px / 24px | 700 | 0 |
| `main-content-muted` | 16px / 24px | 400 | 0 |
| `main-content-mono` | 16px / 23px | 400 | 0 (DM Mono) |
| `main-ui-body` | 14px / 20px | 500 | 0 |
| `main-ui-muted` | 14px / 20px | 400 | 0 |
| `main-ui-action` | 14px / 20px | 600 | 0 |
| `main-ui-mono` | 14px / 20px | 400 | 0 |
| `secondary-body` | 12px / 16px | 400 | 0 |
| `secondary-action` | 12px / 16px | 600 | 0 |
| `secondary-mono` | 12px / 16px | 400 | 0 |
| `figure-small-label` | 10px / 12px | 700 | 0 |
| `figure-small-value` | 10px / 12px | 400 | 0 |

Regola: contenuto = 16px, UI compatta = 14px, etichette = 12px, mai sotto 12px tranne figure.
I pesi usati: 400 / 450 / 500 / 600 / 700. L'istanza serve Hanken Grotesk come `body` font
(computato, v. §16).

## 4. Dimensioni dei controlli (Interactive.Container)

`web/lib/opal/src/shared.ts:42-77` (`containerSizeVariants`), altezza = preset tipografici:

| size | height | min-width | padding |
|---|---|---|---|
| `fit` | auto | — | 0 |
| `lg` | 36px (`--height-line-h1-headline`) | 36px | 8px (p-2) |
| `md` | 28px (`--height-line-h3-section`) | 28px | 4px (p-1) |
| `sm` | 24px (`--height-line-label`) | 24px | 4px |
| `xs` | 20px (`--height-line-main`) | 20px | 2px |
| `2xs` | 16px (`--height-line-secondary`) | 16px | 2px |

Bottone default `size="lg"` (28px…36px reale con padding 8px), `md` per azioni compatte.
Icone nel bottone (`icon-wrapper.tsx`): lg/md → 16px (1rem), xs/2xs → 12px (0.75rem), gap 4px.
Rounding: `rounding={isLarge ? 3 : size === "2xs" ? 1 : 2}` (components.tsx:100) — step `N` =
`N/4`rem (`roundingToRem` in shared.ts): lg → 12px (`radius-12`), md/sm → 8px (`radius-08`),
2xs → 4px. Scala raggi (`size.json`): `radius-02 2px · 04 4px · 08 8px · 12 12px · 16 16px ·
20 20px · round 62.5rem`.

Timing condiviso (core/interactive/shared.css:23-26): `--interactive-duration: 150ms`,
`--interactive-easing: ease-in-out`.

## 5. Stati interattivi

`web/lib/opal/src/core/interactive/stateless/styles.css` (matrice variant × prominence × stato):

| combinazione | base | hover | active | disabled |
|---|---|---|---|---|
| default/primary | `theme-primary-05` + testo `text-inverted-05` | `theme-primary-04` | `theme-primary-06` | `background-neutral-04` + `text-inverted-04` |
| default/secondary | `background-tint-01` + `text-03`, **bordo** (`data-border`) | `background-tint-02` + `text-04` | `background-tint-00` + `text-05` | `background-neutral-03` + `text-01` |
| default/tertiary | trasparente + `text-03` | bg `background-tint-02` | — | — |
| default/internal | trasparente + `text-04` | — | — | — |
| danger (variant) | `action-danger-*` / `status-error-*` | — | — | — |

Stateful (sidebar, voci, select): `state` = `empty / filled / selected`, colori in
`core/interactive/stateful/styles.css` (selezione via `action-selection-*`).
Disabilitato: `cursor-not-allowed`, sempre leggibile (mai solo opacity sul testo).
Focus: `outline: 2px solid var(--border-04); outline-offset: 2px` con `border-radius 0.25rem`
sul ring (core/animations/styles.css:193-197, usato come pattern focus dell'app).

## 6. Bottoni

`components/buttons/button/components.tsx`: `variant` default/action/danger/none ×
`prominence` primary/secondary/tertiary/internal × `size` (2xs…lg). Etichetta via `Text`:
`main-ui-body` (600 → action) su lg, `secondary-body` altrimenti; icona a sinistra, `rightIcon`
opzionale; gap interno 4px. Secondary ha bordo; primary è pieno scuro (theme-primary).
Trasi traduce: `primary` → pieno, `secondary` → bordo, `tertiary` → quieto, `danger` → rosso solo
dove Onyx lo userebbe.

## 7. Input

`components/inputs/input-type-in/components.tsx` + `components/inputs/shared.css`: campo
basato su Interactive.Container (altezza `--height-line-h3-section` = 28px per md), bordo
`border-02`, raggio 8px, focus con anello; `InputSelect` = stesso contenitore + chevron.
Placeholder `text-02`. (valori nei css dei componenti inputs)

## 8. Layout di pagina

`lib/opal/src/layouts/settings/components.tsx`:

- Root: contenitore centrato, larghezze `sm 42rem · sm-md 47rem · md 54.5rem · lg 62rem · full`
  (`--app-container-*`, styles/sizes.css:14-20; l'AGENTS.md documentava 672/752/872/992 px che
  sono gli equivalenti px arrotondati). Default `md` (872px).
- Scroll container con `id="page-wrapper-scroll-container"`; l'header è `sticky top-0` con
  `bg-background-tint-01` e mostra una **scroll shadow** quando `scrollTop > 0`:
  gradiente `linear-gradient(to bottom, var(--mask-02), transparent)`, alto 8px,
  `rounded-b-08`, opacity animata 300ms (components.tsx:155-163).
- Header: icona + titolo (Content `headline/heading`), azioni a destra (`rightChildren`),
  divider sotto.
- Body: `pt-6 pb-18 px-4 flex flex-col gap-8` (components.tsx:180).
- Sidebar: espansa 15rem (240px), piegata 3.25rem (52px); header alto 3.25rem (52px)
  (`--sidebar-width-*`, `--chrome-header-height`, styles/sizes.css:25-27).
- Breakpoints (tailwind config): `sm 724 · md 912 · lg 1232 · 2xl 1420 · 3xl 1700`.
  Larghezze messaggio: default 740px, max 850px; contenuto max 725px.

## 9. Content / ContentAction / IllustrationContent

- `Content`: icona + titolo + descrizione, routing per `sizePreset`/`variant`
  (headline+heading → icona sopra; section → icona inline; main-ui → compatto).
  Icone 16px (lg) o 20px (hero), gap 12px, titolo `heading-h3` o `main-ui-action`.
- `ContentAction` = Content + slot azioni a destra, `padding` come prop.
- `IllustrationContent`: illustrazione 7.5rem (120px) centrata, gap 12px, padding 20px,
  titolo + descrizione centrati (layouts/illustration-content/components.tsx:9-42).
  È il pattern di **stato vuoto** di Onyx.

## 10. Stati vuoti e caricamento

- Stato vuoto: `IllustrationContent` (illustrazione + titolo + descrizione).
- Skeleton: blocchi `bg-background-tint-02` con `animate-pulse` e raggio 2px
  (`ChatSessionSkeleton.tsx`: cerchio 16px + barra `w-2/3 h-5`).
- Attesa in chat: `shimmer-text` su testo in `main-ui-action text-03`:
  gradiente `linear-gradient(90deg, var(--shimmer-base) 35%, var(--shimmer-highlight) 50%, …)`,
  `background-size: 300% 100%`, animazione `shimmer 1s ease-out infinite`
  (globals.css:256-274). Reduced motion: shimmer fermo (comet.css pattern).
- Loader: `opal-loader` (rotazione 2s) e `craft-comet` (dash 16/84 su 3.6s lineare) —
  entrambi con `@media (prefers-reduced-motion: reduce) { animation: none }`.

## 11. Chat

Sorgenti: `web/src/app/app/message/`, `web/src/sections/chat`, `web/src/sections/input`.

- Larghezza colonna messaggi: `max-w-message-default` = 740px (max 850px).
- Messaggio umano: riga a destra con bolla `bg-background-tint-02`, raggio 16px, padding 12px;
  icona avatar 28px.
- Risposta assistente: senza bolla (fondale pagina), testo `main-content-body`, larghezza
  colonna `content-max 725px`; intestazione con icona agent + nome.
- Compositore: ancorato in basso, contenitore bianco con bordo `border-02`, raggio 16px,
  textarea senza bordo, barra azioni sotto (allegati, tools) e pulsante invio circolare pieno
  (theme-primary-05) disabilitato con input vuoto; altezza riga input ~52px, padding 16px.
- Fonti/citazioni: riga di chip sotto il messaggio (`Sources`), ognuna con numero + nome
  documento, `secondary-body`, bordo `border-01`, raggio 8px, hover `background-tint-01`.
- Streaming: header di riga `shimmer-text` ("sta rispondendo").

## 12. Icone

Cartella `web/lib/opal/src/icons/` (226 icone). Caratteristiche: stroke = `currentColor`,
`fill: none`, `strokeLinecap/join: round`, viewBox **16×16** per le icone piccole
(stroke 1.5), alcune 24×24 (stroke 2), `menu` 32×32. Dimensioni di render: 16px (lg/md/sm),
12px (xs/2xs), 20px (hero). Licenza MIT. Le icone usate da Trasi (appendice A con SVG):
`bubble-text` (chat), `pin` (mappa), `column`/`dashboard` (tabella/registro),
`bar-chart` (osservatorio), `help-circle`, `log-out`, `search`, `plus`, `check`, `check-circle`,
`x`, `x-circle`, `info`, `alert-triangle`, `clock`, `calendar`, `user`, `users`, `home`,
`text-lines`, `external-link`, `chevron-down`.

## 13. Movimento

- Transizioni componenti: `150ms ease-in-out` (interactive shared.css).
- Gradiente header: 300ms opacity.
- `fade-in-up`: `0.5s ease-out` (solo per apparizioni, tailwind.config.js).
- Shimmer: 1s loop. Comet: 3.6s loop.
- `prefers-reduced-motion`: shimmer/rotazioni `animation: none` — sempre.
- Mai transizioni su proprietà che spostano il bersaglio (padding/scale sui pressati).

## 14. Regole di stile da `web/AGENTS.md` (sintesi)

1. Opal prima; niente componenti legacy (`src/components/`).
2. `size` di default `md` per ogni SizeVariant.
3. Vietato `dark:`; i colori passano dai token (`colors.css` gestisce il tema).
4. Icone solo dal set curato (`@opal/icons`), mai librerie esterne.
5. Testo sempre via `Text` con `font`/`color` enum; niente testo "nudo".
6. `RichStr` per prop testuali con markdown opt-in.
7. Mai input HTML grezzi; componenti del design system.
8. Colori solo da categorie token (text/background/border/action/status/theme); mai Tailwind gray.
9. Dati via SWR lato client con skeleton.
10. `cn` per le classi; padding preferito ai margini; absolute import.
11. Componenti: funzioni regolari, props interface nel file, tipi condivisi in `types.ts`.
12. Layout: SettingsLayouts per pagine impostazioni; card per entità; Hoverable con fallback `no-hover` (tocco sempre visibile).
13. i18n via cataloghi; proprietà CSS logiche (`ps-`/`pe-`) per RTL.

## 15. Differenze documentazione ↔ implementazione

- `AGENTS.md` dichiara larghezze Settings 672/752/872/992px; l'implementazione usa
  `--app-container-*`: 42/47/54.5/62rem = **672/752/872/992px** (coerenti, l'AGENTS arrotonda).
- `AGENTS.md` dice size default `md` per i componenti; `Button` di default è `lg`.
- Il focus ring non è definito centralmente: il pattern de facto è `outline: 2px solid
  var(--border-04); outline-offset: 2px` (animations/styles.css), ripreso per-componente.
- `colors.css` citato dall'AGENTS non esiste più: i token vivono in `web/lib/shared/tokens/*.json`
  + `tailwind-preset.cjs`.

## 16. Valori computati dall'istanza deployata

Istanza `http://127.0.0.1:3000` (nginx), login con account di servizio (cookie `fastapiusersauth`):

- Font body: `Hanken Grotesk`, base 16px/24px (computed su `/v1` e `/app`).
- Testo principale ≈ `#000000e5` su `#ffffff`; sidebar bg `#fafafa`, larghezza 240px;
  header chat 52px (`--chrome-header-height`).
- Bottoni: `Sign In` pieno scuro (theme-primary-05 ≈ `#1c1c1c`), raggio 12px, altezza 36px.
- Compositore chat: bordo `#e6e6e6` (border-02), raggio 16px, invio circolare 36px pieno
  scuro, disabilitato su input vuoto.
- Screenshot: `/tmp/onyx-screens/app.png` (nuova sessione, sidebar + compositore),
  `/tmp/onyx-login-attempt.png` (pagina di accesso).
- Chat con messaggi: non aperta (il click su una sessione recente ha appeso il tab; non è
  servita alla definizione dei token — la struttura è letta dai sorgenti, §11).

## 17. Licenza

`LICENSE` (radice): MIT ("Copyright (c) 2023-present DanswerAI, Inc."), con eccezione per le
cartelle `ee/` (Enterprise License) — **non** usate da Trasi. `web/lib/opal/package.json`:
`"license": "MIT"`. Icone e token in `web/lib/opal` e `web/lib/shared` sono quindi
riutilizzabili con attribuzione; Hanken Grotesk è OFL e vendorizzabile.

---

## Appendice A — icone vendorizzate per Trasi

Tutte `fill="none" stroke="currentColor" stroke-linecap="round" stroke-linejoin="round"`.
viewBox 16×16 e stroke 1.5 (salvo indicato). Sorgente: `web/lib/opal/src/icons/<file>.tsx`.

```svg
<!-- bubble-text (chat) 16x16 sw1.5 -->
<svg viewBox="0 0 16 16"><path d="M10.4939 6.5H5.5M8.00607 9.5H5.50607M1.5 13.5H10.5C12.7091 13.5 14.5 11.7091 14.5 9.5V6.5C14.5 4.29086 12.7091 2.5 10.5 2.5H5.5C3.29086 2.5 1.5 4.29086 1.5 6.5V13.5Z"/></svg>
<!-- pin (mappa) 16x16 sw1.5 -->
<svg viewBox="0 0 16 16"><path d="M6.70001 9.29581L2.20001 13.7958M6.70001 9.29581L9.99291 12.5887C10.6229 13.2187 11.7 12.7725 11.7 11.8816V10.5384C11.7 9.7428 12.0161 8.97974 12.5787 8.41713L13.4929 7.50292C13.8834 7.11239 13.8834 6.47923 13.4929 6.0887L9.90712 2.50292C9.51659 2.11239 8.88343 2.11239 8.49291 2.50292L7.57869 3.41713C7.01608 3.97974 6.25302 4.29581 5.45737 4.29581H4.11423C3.22332 4.29581 2.77715 5.37295 3.40712 6.00291L6.70001 9.29581Z"/></svg>
<!-- dashboard (osservatorio) 16x16 sw1.5 -->
<svg viewBox="0 0 16 16"><path d="M14 6V3.33333C14 2.59695 13.403 2 12.6667 2H3.33333C2.59695 2 2 2.59695 2 3.33333V6M14 6V12.6667C14 13.403 13.403 14 12.6667 14H6M14 6H6M2 6V12.6667C2 13.403 2.59695 14 3.33333 14H6"/></svg>
<!-- column (registro/tabella) 16x16 sw1.5 -->
<svg viewBox="0 0 16 16"><path d="M6 14H3.33333C2.59695 14 2 13.403 2 12.6667V3.33333C2 2.59695 2.59695 2 3.33333 2H6M6 14V2M6 14H10M6 2H10M10 2H12.6667C13.403 2 14 2.59695 14 3.33333V12.6667C14 13.403 13.403 14 12.6667 14H10"/></svg>
<!-- bar-chart 16x16 sw1.5 -->
<svg viewBox="0 0 16 16"><path d="M12 13.3333V6.66666M8 13.3333V2.66666M4 13.3333V9.33332"/></svg>
<!-- help-circle 16x16 sw1.5 -->
<svg viewBox="0 0 16 16"><path d="M6.06001 6.00004C6.21675 5.55449 6.52611 5.17878 6.93331 4.93946C7.34051 4.70015 7.81927 4.61267 8.28479 4.69252C8.75031 4.77236 9.17255 5.01439 9.47673 5.37573C9.7809 5.73706 9.94738 6.19439 9.94668 6.66671C9.94668 8.00004 7.94668 8.66671 7.94668 8.66671M8.00001 11.3334H8.00668M14.6667 8.00004C14.6667 11.6819 11.6819 14.6667 8.00001 14.6667C4.31811 14.6667 1.33334 11.6819 1.33334 8.00004C1.33334 4.31814 4.31811 1.33337 8.00001 1.33337C11.6819 1.33337 14.6667 4.31814 14.6667 8.00004Z"/></svg>
<!-- log-out 24x24 sw2 -->
<svg viewBox="0 0 24 24"><path d="M9 21H5C4.46957 21 3.96086 20.7893 3.58579 20.4142C3.21071 20.0391 3 19.5304 3 19V5C3 4.46957 3.21071 3.96086 3.58579 3.58579C3.96086 3.21071 4.46957 3 5 3H9"/><path d="M16 17L21 12L16 7"/><path d="M21 12H9"/></svg>
<!-- search 16x16 sw1.5 -->
<svg viewBox="0 0 16 16"><path d="M14 14L11.1 11.1M12.6667 7.33333C12.6667 10.2789 10.2789 12.6667 7.33333 12.6667C4.38781 12.6667 2 10.2789 2 7.33333C2 4.38781 4.38781 2 7.33333 2C10.2789 2 12.6667 4.38781 12.6667 7.33333Z"/></svg>
<!-- plus 16x16 sw1.5 -->
<svg viewBox="0 0 16 16"><path d="M8 2V14M2 8H14"/></svg>
<!-- check 16x16 sw1.5 -->
<svg viewBox="0 0 16 16"><path d="M13.5 4.5L6 12L2.5 8.5"/></svg>
<!-- x 28x28 sw2.5 -->
<svg viewBox="0 0 28 28"><path d="M21 7L7 21M7 7L21 21" stroke-width="2.5"/></svg>
<!-- chevron-down 16x16 sw1.5 -->
<svg viewBox="0 0 16 16"><path d="M4 6L8 10L12 6"/></svg>
<!-- info 16x16 sw1.5 -->
<svg viewBox="0 0 16 16"><path d="M8.00001 10.6666V7.99998M8.00001 5.33331H8.00668M14.6667 7.99998C14.6667 11.6819 11.6819 14.6666 8.00001 14.6666C4.31811 14.6666 1.33334 11.6819 1.33334 7.99998C1.33334 4.31808 4.31811 1.33331 8.00001 1.33331C11.6819 1.33331 14.6667 4.31808 14.6667 7.99998Z"/></svg>
<!-- alert-triangle 16x16 sw1.5 -->
<svg viewBox="0 0 16 16"><path d="M6.8 1.9C7.4 0.9 8.6 0.9 9.2 1.9L14.6 11.1C15.2 12.1 14.7 13.3 14.1 13.3H1.9C1.3 13.3 0.8 12.1 1.4 11.1L6.8 1.9ZM8 5.3V8.7M8 11H8.007"/></svg>
<!-- clock 16x16 sw1.5 -->
<svg viewBox="0 0 16 16"><path d="M7.99999 3.99999V7.99999L10.6667 9.33333M14.6667 7.99999C14.6667 11.6819 11.6819 14.6667 7.99999 14.6667C4.3181 14.6667 1.33333 11.6819 1.33333 7.99999C1.33333 4.3181 4.3181 1.33333 7.99999 1.33333C11.6819 1.33333 14.6667 4.3181 14.6667 7.99999Z"/></svg>
<!-- calendar 14x15 sw1.5 -->
<svg viewBox="0 0 14 15"><path d="M9.41667 0.75V3.41667M4.08333 0.75V3.41667M0.75 6.08333H12.75M2.08333 2.08333H11.4167C12.153 2.08333 12.75 2.68029 12.75 3.41667V12.75C12.75 13.4864 12.153 14.0833 11.4167 14.0833H2.08333C1.34695 14.0833 0.75 13.4864 0.75 12.75V3.41667C0.75 2.68029 1.34695 2.08333 2.08333 2.08333Z"/></svg>
<!-- user 16x16 sw1.5 -->
<svg viewBox="0 0 16 16"><path d="M13.3333 14V12.6667C13.3333 11.9594 13.0524 11.2811 12.5523 10.781C12.0522 10.281 11.3739 10 10.6667 10H5.33334C4.62609 10 3.94782 10.281 3.44772 10.781C2.94762 11.2811 2.66667 11.9594 2.66667 12.6667V14M10.6667 4.66667C10.6667 6.13943 9.47276 7.33333 8.00001 7.33333C6.52725 7.33333 5.33334 6.13943 5.33334 4.66667C5.33334 3.19391 6.52725 2 8.00001 2C9.47276 2 10.6667 3.19391 10.6667 4.66667Z"/></svg>
<!-- home 16x16 sw1.5 -->
<svg viewBox="0 0 16 16"><path d="M6 14.6667V8H10V14.6667M2 6L8 1.33333L14 6V13.3333C14 13.6869 13.8595 14.0261 13.6095 14.2761C13.3595 14.5262 13.0203 14.6667 12.6667 14.6667H3.33333C2.97971 14.6667 2.64057 14.5262 2.39052 14.2761C2.14048 14.0261 2 13.6869 2 13.3333V6Z"/></svg>
<!-- text-lines 18x18 sw1.5 -->
<svg viewBox="0 0 18 18"><path d="M15.75 7.4925H2.25M15.75 4.5H2.25M9 13.5H2.25M15.75 10.4962H2.25"/></svg>
<!-- external-link 24x24 sw1.5 -->
<svg viewBox="0 0 24 24"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><path d="M15 3h6v6"/><path d="M10 14L21 3"/></svg>
<!-- check-circle 16x16 sw1.5 -->
<svg viewBox="0 0 16 16"><path d="M14.0833 7.41667C14.0833 11.0986 11.0986 14.0833 7.41667 14.0833C3.73477 14.0833 0.75 11.0986 0.75 7.41667C0.75 3.73477 3.73477 0.75 7.41667 0.75C11.0986 0.75 14.0833 3.73477 14.0833 7.41667Z"/><path d="M4.9 7.4L6.8 9.3L10.3 5.8"/></svg>
```

Icone **non presenti** nel set Opal: invio (freccia su) — sostituito da `arrow-up`/`arrow-up-dot`;
usare `arrow-up-dot` o disegnare coerente. `menu` (32×32, sw2) esiste per il burger mobile.