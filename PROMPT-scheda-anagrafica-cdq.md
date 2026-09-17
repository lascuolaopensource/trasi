# PROMPT — Costruire la «Scheda Anagrafica della Casa di Quartiere» (1.1)

Prompt di costruzione per l'implementazione della scheda dati **1.1 Scheda Anagrafica CdQ**
dentro l'interfaccia Trasi. Da eseguire **dopo** aver letto il design system della rete
(vedi «Materiali»). Il deliverable è **codice funzionante** nel repo, verificato nel browser
reale, non un mockup: niente «v1», niente TODO, niente segnaposto lasciati a schermo.

Copia tutto ciò che segue (da «## Contesto» in poi) nell'agente che costruisce la UI,
allegando i file elencati in «Materiali».

---

## Contesto

**Trasi** è lo strumento digitale del *Portierato di Quartiere* della **Rete delle Case di
Quartiere di Brindisi** (PN Metro Plus, Città Medie Sud 2021-2027). Serve **operatori
sociali**, non tecnici, spesso su tablet, con poco tempo e alto turnover: ogni schermata
deve spiegarsi da sola.

La **Scheda Anagrafica della Casa** è l'**anagrafica della Casa di Quartiere**: i dati di
identità e di contatto del luogo. La compila e la aggiorna l'**operatore della Casa**
(`operatorə CdQ`), sempre riferita alla **propria** Casa (il profilo da cui scrive è quello
della Casa stessa, quindi l'appartenenza è un fatto della sessione, non un campo da chiedere).

**Dove vive.** Dentro l'area operatore, funzione **REGISTRA / AGGIORNA → Casa** (la sezione
«Account della Casa», sola lettura + modifica-come-proposta). È una delle schede dati del
sistema; le sue vicine sono 1.2 Anagrafica Personale, 2.1 Eventi, 3.1 Inventario. Riusa la
**app shell alla Onyx** già definita per l'area operatore (testata sticky, navigazione
laterale ≥ 1180 px che diventa linguette sotto, contenuto in contenitore `md`/`lg`).

## Materiali da allegare / leggere prima

1. `.orca/drops/Architettura di informazioni INPUT.xlsx` — la fonte dei campi (foglio Home,
   riga «1.1 Scheda Anagrafica CdQ»; foglio «1.1 Anagrafica Casa» per l'elenco campi).
2. `docs/onyx-regole-ui.md` — le **regole UI di Onyx v4.7.2** estratte per Trasi (token di
   colore/tipografia/dimensioni, componenti, stati, stati vuoti, skeleton, icone). **Vincolante.**
3. `docs/ux-ui-architettura-informazione.md` — architettura dell'informazione dell'area
   operatore (app shell, pannello attivo nell'URL, stati progettati). **Vincolante.**
4. `PROMPT-ux-ui.md` — il contratto di lavoro UX/UI della rete (fasi, budget, vietati).

Se uno di questi manca, **fermati e chiedilo**: non reinventare token, componenti o testi.

## Cosa mostra la scheda — i campi (verbatim dalla fonte)

I nove contenuti della **1.1 Scheda Anagrafica CdQ**, nell'ordine della fonte. Ogni campo è
un'informazione: se non c'è, si mostra il **vuoto dichiarato**, mai un segnaposto.

| # | Campo (etichetta) | Note di contenuto e forma |
|---|---|---|
| 1 | **Nome della Casa di quartiere** | Titolo della scheda. È il nome proprio della Casa (es. «Santa Spazio Culturale», «San Bao», «Centro di Aggregazione Bozzano»). |
| 2 | **Indirizzo** | Via e numero civico. Se la Casa ha una posizione mappabile, l'indirizzo è coerente con la scheda del luogo dell'Osservatorio (non si duplica il dato, si mostra lo stesso). |
| 3 | **Edificio** | Descrizione dell'edificio / collocazione (piano, ala, riferimento). Campo testuale breve. |
| 4 | **Zona (quartiere)** | Il quartiere/zona di Brindisi (es. «Centro Storico», «Sant'Elia»). |
| 5 | **Recapiti telefonici** | Uno o più numeri; ciascuno cliccabile (`tel:`), leggibile anche senza colore. |
| 6 | **Mail** | Indirizzo e-mail di contatto della Casa (`mailto:`). **Non** è un dato personale di persona fisica: è il contatto della Casa. |
| 7 | **Orari di apertura** | Orari settimanali leggibili in parole; gestisci il caso **«orari provvisori»** (Casa con dati non ancora completi, es. Tuturano): nota esplicita «dati provvisori», non un colore. Se assenti: «Orari non nella memoria della rete». |
| 8 | **Servizi e attività ricorrenti** | Elenco dei servizi/attività della Casa (titolo, a chi si rivolge, quando, come accedere, referente **come ruolo** non come persona). Su questo database la tabella dei servizi può essere **vuota**: disegna il vuoto dichiarato («Nessun servizio ancora inserito per questa Casa»), non righe finte. |
| 9 | **Chi lo abita** | Le persone che ci lavorano e la frequentano: rimanda alla **1.2 Anagrafica Personale** (nome, ruolo, competenze, associazione). Mostra un elenco sintetico (nome + ruolo) con collegamento alla scheda personale; se vuoto, dichiaralo. |

Nota metodologica della fonte: per altri esempi di compilazione dei campi vedi il foglio
collegato nella cella «Note metodologiche» della scheda 1.1 (Google Sheet della rete).

## Le due modalità della scheda

1. **Lettura** (default). La scheda mostra i nove campi come **scheda-entità** (card Onyx),
   ciascuno con la propria **etichetta di provenienza** — il principio non negoziabile del
   prodotto è **«mai senza fonte»**:
   - `[KB · Rete delle Case di Quartiere · <data> · affidabilità N]` → verificato dalla rete;
   - `[Esterna · <fonte> · consultata <ora> · non verificata dalla rete]` → trovato fuori.
   L'etichetta va resa leggibile a colpo d'occhio senza diventare rumore (riga propria,
   `secondary-mono`/`DM Mono`, tratteggio per «Esterna»). Segui il pattern etichetta di
   provenienza del design system.

2. **Modifica come proposta** (non scrittura diretta). Il sistema **non modifica mai la
   memoria da solo**: quando l'operatore corregge un campo (es. cambia gli orari o aggiunge un
   recapito) nasce una **proposta** che un umano approva. Quindi la modifica non salva in
   diretta: apre un modulo (campi del design system, mai `input` HTML grezzi, mai `prompt()`),
   e all'invio genera una proposta con conferma inline «La modifica è stata proposta e
   aspetta una decisione». Nessun imperativo, nessuna promessa di modifica immediata.

## Sistema di design — cosa usare (da `docs/onyx-regole-ui.md`)

- **Contenitore**: card entità su `background-tint-01`, bordo `border-01/02`, raggio `radius-12`;
  testata della scheda con titolo `heading-h2`/`heading-h3` (il nome della Casa) e azioni a
  destra (`[Proponi una modifica]`, `[Stampa]`).
- **Righe campo**: etichetta `main-ui-muted` (14px, `text-03`) + valore `main-content-body`
  (16px, `text-05`); sotto, la riga di provenienza. Larghezza di lettura 60–75 caratteri.
- **Bottoni**: `primary` = pieno scuro (`theme-primary-05`), `secondary` = bordo, `tertiary`
  = quieto; `size` `md`/`lg`. Azioni distruttive solo in rosso e solo dove Onyx lo userebbe.
- **Campi/moduli**: componenti input del design system (`InputTypeIn`, `InputSelect`),
  altezza `md`, bordo `border-02`, raggio `radius-08`, placeholder `text-02`, anello di focus.
- **Icone**: solo dal set curato di Onyx (SVG inline, tratto `currentColor`, griglia 16×16),
  sempre accanto alla parola: `home`, `pin`, `clock`, `phone`/`mail` se presenti nel set,
  `users` («chi lo abita»), `text-lines`, `external-link`, `check`, `x`. Mai librerie esterne.
- **Testo** sempre via il componente `Text` con enum `font`/`color`; niente testo «nudo»,
  niente Tailwind gray, niente `dark:`, nessun numero magico fuori dai token.

## Stati progettati (tutti, non solo il caso felice)

Disegna e verifica ogni stato, come per le altre schermate:

- **Attesa**: skeleton delle righe (`bg-background-tint-02`, `animate-pulse`, raggio 2px).
- **Dati non disponibili** (shim non risponde entro il timeout): frase leggibile + nota «è
  un'informazione, non un guasto». Mai un errore tecnico a schermo.
- **Campo vuoto**: «… non nella memoria della rete» / «Nessun servizio ancora inserito».
  Il vuoto è un'informazione, si disegna (pattern `IllustrationContent` per la sezione intera).
- **Casa provvisoria** (es. Tuturano): nota «dati provvisori» sotto il titolo.
- **Errore di validazione (`422`)** nel modulo di proposta: messaggio inline per campo.
- **Servizio non disponibile (`503`)**: stato dichiarato, la scheda resta leggibile.
- **Proposta inviata**: conferma inline; il valore a schermo **non** cambia finché non è approvata.

## Vincoli non negoziabili

- **Accessibilità WCAG 2.1 AA**: contrasto testo ≥ 4,5:1 (misurato, non a occhio), focus
  sempre visibile ≥ 2px, navigazione completa da tastiera, testo base ≥ 16px. Il colore non è
  mai l'unico canale di stato o di provenienza.
- **Zero dipendenze esterne a runtime**: niente CDN, niente font remoti, nessuna richiesta a
  terzi. Font vendorizzato localmente con `display: swap`; icone SVG inline.
- **Nessuna scrittura diretta del dominio**: ogni modifica passa da una **proposta**.
- **Provenienza sempre presente**: nessuna informazione mostrata senza etichetta di fonte.
- **Nessun dato personale non necessario**: «Chi lo abita» mostra ruoli e nomi di chi lavora
  nella Casa (dato di 1.2), non dati sensibili di cittadini.
- **Lingua: italiano semplice, terza persona.** Nessun imperativo verso le persone, nessun
  «tu»/«noi», nessun punto esclamativo. I quattro nomi delle destinazioni restano in maiuscolo.
- **Peso e prestazioni** dentro il budget dell'area operatore già fissato in `PROMPT-ux-ui.md`.

## Stampa

Foglio di stile `print` per la scheda anagrafica (promemoria da sportello): nome, indirizzo,
zona, recapiti, orari, servizi; con l'etichetta di provenienza di ogni dato. Nessun colore
necessario alla comprensione; leggibile in bianco e nero.

## Cosa consegnare (definizione di fatto)

1. La scheda anagrafica in **lettura**, con i nove campi, ciascuno con provenienza, nell'area
   operatore (funzione REGISTRA/AGGIORNA → Casa), integrata nell'app shell esistente.
2. Il **modulo di modifica-come-proposta** funzionante (invio → proposta + conferma inline).
3. Tutti gli **stati** sopra, forzabili e verificati (una pagina `stati` come per le altre UI).
4. Foglio di **stampa**.
5. **Prove**: screenshot ai tre breakpoint (1440/820/390), report a11y (axe 0 violazioni,
   contrasti misurati), percorso tastiera registrato, log di rete con **zero** host esterni.
6. **Cosa NON cambiare** e perché (contratti con lo shim, persistenza della Casa di sessione).

## Coordinamento

Questa scheda vive **dentro** il frontend che la peer `ux-ui-automatica` sta ricostruendo
(area operatore, funzione REGISTRA). Prima di implementare, allinea con lei:
- il **contratto dati** della Casa (endpoint/campi dello shim: anagrafica Casa, servizi,
  personale della Casa, invio proposta di modifica) e l'esatta forma dell'etichetta di
  provenienza (deve combaciare **carattere per carattere** con quella dello shim);
- il punto di innesto nell'app shell (pannello `?pannello=…` della funzione REGISTRA);
- i token/componenti definitivi, così la scheda non introduce una seconda convenzione.
