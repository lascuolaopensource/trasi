# Accessibilità — Trasi Home e area operatore

Misure del 2026-09-17 dopo la revisione UX/UI. Ambiente: Chrome 150, anteprima locale
con le stesse rotte dell'esercizio. Metodo: axe-core (wcag2a, wcag2aa, wcag21a, wcag21aa,
best-practice), scansione automatica del contrasto su tutti i testi visibili, percorso
tastiera registrato elemento per elemento, prove manuali a zoom 200 % e larghezza 320 px.

## Risultati

| Controllo | Home | Area operatore | Home (shim fermo) |
|---|---|---|---|
| Lighthouse accessibility | 100 | 100 | 100 |
| axe: violazioni | 0 | 0 | 0 |
| Contrasto minimo testo | ≥ 4,5:1 (scansione: 0 sotto soglia) | ≥ 4,5:1 | ≥ 4,5:1 |
| Reflow a 320 px | nessun overflow orizzontale | nessun overflow | nessun overflow |
| Zoom 200 % | contenuto utilizzabile | contenuto utilizzabile | — |
| `prefers-reduced-motion` | shimmer/rotazioni ferme, transizioni annullate | idem | idem |

## Contrasti misurati (token su fondo reale)

| Combinazione | Rapporto | Minimo richiesto |
|---|---|---|
| testo principale (#000000e5) su bianco | 17,6:1 | 4,5:1 |
| testo principale su tint-02 (hover) | 18,4:1 | 4,5:1 |
| testo secondario (#000000bf) su bianco | 10,4:1 | 4,5:1 |
| link (#07577B) su bianco | 7,9:1 | 4,5:1 |
| testo invertito (bianco) su testata #06405A | 11,1:1 | 4,5:1 |
| bianco su bottone pieno hover #1D5B76 | 7,5:1 | 4,5:1 |
| testo successo #00761F su success-00 | 5,6:1 | 4,5:1 |
| testo attenzione #B44105 su warning-00 | 5,4:1 | 4,5:1 |
| testo errore #B02B27 su error-00 | 6,2:1 | 4,5:1 |
| testo info #1D5ECF su info-00 | 5,7:1 | 4,5:1 |

La scansione automatica a 1440px (tutti i nodi con testo proprio, alpha composta sul
fondo effettivo) non ha trovato coppie sotto 4,5:1 (3:1 per testo grande).

## Tastiera

Ordine di tabulazione Home (registrato):
salta-al-contenuto → selettore Casa → Area operatore → Aiuto → Esci →
apri la coda delle proposte → CHIEDI → MAPPA → OSSERVATORIO → Aiuto (details).

Ordine area operatore (in sessione):
salta → Home → Aiuto → Esci → 4 funzioni (linguette) → campo chat → invia.

- Focus visibile: `outline 2px` anello esterno su ogni elemento focalizzabile
  (`:focus-visible`), colore anello `border-04` (#808080) visibile su chiaro; nei campi
  l'anello resta sul bordo del campo con `outline-offset: 0`.
- Al cambio di pannello nell'area operatore il focus va al titolo del pannello
  (`tabindex="-1"`), così chi usa lo screen reader sente dove si trova; verificato:
  `document.activeElement` = titolo del pannello dopo il cambio.
- «Esci» chiude la sessione dello shim; l'esito è annunciato con `role="status"`.
- La riga «Oggi» è una regione `role="status" aria-live="polite"` con `aria-busy`
  durante la lettura: i cambi di stato sono annunciati.

## Linguaggio

Nessun imperativo rivolto a persone o Case (V6). Stati dichiarati a parole oltre che con
il colore: «Servizio non ancora attivo», «dati provvisori», «dati non disponibili:
la memoria della rete non risponde in questo momento. È un'informazione, non un
guasto…». Conteggi sotto soglia di riservatezza scritti «<5».

## Limiti dichiarati

- La verifica riguarda le due pagine Trasi. Le applicazioni esterne (Onyx, Metabase,
  NocoDB) sono rinviate alla settimana 2 del piano (S2), come già dichiarato nell'Aiuto.
- L'audit `errors-in-console` di Lighthouse sull'area operatore registra il 401 atteso
  di `GET /api/shim/me` per una visita senza sessione: comportamento contrattuale
  (sessione assente → 401 → schermata di accesso), non un difetto di accessibilità.
- Il CLS misurato da Lighthouse è 0,03–0,06 (soglia «good» ≤ 0,1; in riproduzione
  manuale throttled: 0). Causa e mitigazioni documentate nel report di revisione.