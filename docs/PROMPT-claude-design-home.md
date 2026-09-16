# PROMPT PER CLAUDE DESIGN — Trasi Home: architettura dell'informazione e UX/UI

Copia tutto ciò che segue (da «## Contesto» in poi) in Claude Design, allegando i due file indicati in «Materiali».

---

## Contesto

Sono il lead engineer del progetto **Trasi**: lo strumento digitale del *Portierato di Quartiere* della **Rete delle Case di Quartiere di Brindisi** (PN Metro Plus, Città Medie Sud 2021-2027).

Trasi serve **operatori sociali**, non tecnici. L'operatore sta allo sportello con **una persona davanti** e poco tempo: deve capire dove mandarla, con quale informazione, e stampare un promemoria. Spesso usa un **tablet**, a volte un PC di Casa. L'alfabetizzazione digitale è variabile e il turnover è alto: la pagina deve spiegarsi da sola.

**Cosa c'è oggi**: una pagina statica (`index.html` + `style.css` + `home.js`, ~21 KB, zero dipendenze esterne) che funziona, è accessibile (Lighthouse 100/100, axe 0 violazioni) ma è **visivamente grezza**: quattro riquadri in griglia 2×2, un selettore in testa, una riga di riepilogo in fondo. Il tuo compito è **progettare l'architettura dell'informazione e la veste UX/UI** — non riscriverla tecnica per tecnica.

## Materiali da allegare

1. `index.html` — la pagina attuale (contenuto reale, testi compresi)
2. `style.css` — i token e il layout attuali (contrasti già misurati)
3. (facoltativo) uno screenshot della pagina attuale

## Cosa fa la pagina, in concreto

**Header**: il nome **TRASI**, un **selettore della Casa** (10 Case: Santa Spazio Culturale, Molo 12, Accademia degli Erranti, Parco Buscicchio, San Bao, Minimus, POP, Centro di Aggregazione Bozzano, Dream, Tuturano), due azioni: **Aiuto** e **Esci**.

**Quattro riquadri**, ognuno apre un servizio diverso con la Casa già impostata:

| Riquadro | Cosa apre | Cosa ci fa l'operatore |
|---|---|---|
| **CHIEDI** | la chat con l'assistente | risponde alla persona davanti: dove andare, con quali orari, con la fonte citata |
| **MAPPA** | una mappa | guarda insieme alla persona dove sono i luoghi e le Case vicine |
| **REGISTRA / AGGIORNA** | un modulo tabellare | inserisce o corregge schede, eventi, opportunità della sua Casa |
| **OSSERVATORIO** | un cruscotto | legge i numeri della sua Casa e **approva le proposte** in attesa |

**Riga «Oggi»** (in fondo): una lettura dal database, tipo *«Oggi a Centro di Aggregazione Bozzano: 1 evento · 0 schede in scadenza · 1 proposta»*. Se il servizio non risponde entro 3 secondi, mostra *«dati non disponibili»* — **è un'informazione, non un guasto**.

**Sezione Aiuto**: spiega in linguaggio semplice cosa sono i quattro riquadri, come si legge un'etichetta di provenienza, cosa sono le proposte.

**Footer**: una riga sulla privacy (nessun dato personale conservato).

## Il vincolo che dà forma a tutto: «da dove viene l'informazione»

Il progetto ha un principio non negoziabile: **mai senza fonte**. Ogni informazione che l'assistente dà porta un'**etichetta di provenienza**, di due tipi:

- `[KB · Rete delle Case di Quartiere · 15/09/2026 · affidabilità 2]` → **la rete lo sa**, verificato da noi
- `[Esterna · OpenStreetMap · consultata 02:21 · non verificata dalla rete]` → **trovato fuori**, non verificato

Questa distinzione è **il cuore del prodotto**, non un dettaglio tecnico: un operatore che manda una persona in un posto sbagliato fa un danno. La domanda di design è: **come si rende questa distinzione leggibile a colpo d'occhio, senza che diventi rumore?**

E c'è un secondo meccanismo che ti riguarda: il sistema **non modifica mai la memoria da solo**. Se l'operatore segnala *«quel bar ha chiuso»*, nasce una **proposta** che un umano deve approvare. La coda delle proposte è oggi dentro OSSERVATORIO, ma è un'attività **quotidiana o settimanale** — vale la pena chiedersi se meriti più visibilità.

## Il tuo compito

1. **Architettura dell'informazione.** La struttura attuale è giusta? Quattro riquadri uguali comunicano che le quattro cose hanno la stessa frequenza d'uso — probabilmente **non è vero**: CHIEDI si usa decine di volte al giorno, OSSERVATORIO una volta a settimana, REGISTRA quando capita. Progetta una gerarchia che rispecchi **il lavoro reale**, non la simmetria. Dimmi cosa cambieresti e perché.

2. **Veste UX/UI.** Palette, tipografia, spaziature, stati (hover, focus, attivo), comportamento su tablet. Puoi partire dai token CSS esistenti o proporne di nuovi. **Deve restare sobria**: è uno strumento di servizio sociale, non una landing page. Niente illustrazioni decorative, niente animazioni che distraggono, niente gergo.

3. **Le due informazioni difficili.** Come mostri l'**etichetta di provenienza** (KB vs Esterna) e come rendi visibile che c'è **una coda di proposte da approvare**, senza che l'operatore le confonda con un avviso urgente? Sono i due punti su cui il progetto si gioca la credibilità.

4. **Il selettore della Casa.** Oggi è un menu a tendina con 10 voci. Va bene? Considera che: l'operatore lavora quasi sempre per **una sola Casa** (la sua), quindi il cambio è raro; Tuturano va marcata *«dati provvisori»* perché i suoi dati non sono ancora completi; l'informazione non deve dipendere dal colore.

5. **La riga «Oggi».** Oggi è una frase in fondo. Deve restare discreta, ma è l'unica cosa della pagina che **cambia da sola** e dice cosa bolle in pentola. Vale come «stato» in testa? Dimmi la tua lettura.

## Vincoli non negoziabili

- **Accessibilità WCAG 2.1 AA**: contrasto testo ≥ 4,5:1, focus sempre visibile, navigazione completa da tastiera, testo base ≥ 16 px. Oggi è rispettata (contrasto minimo misurato 7,99:1) e **non va peggiorata**.
- **Zero dipendenze esterne**: niente CDN, niente font remoti, nessuna richiesta a domini terzi. La pagina deve funzionare anche se la rete esterna è irraggiungibile. Quindi: font di sistema, icone in SVG inline o caratteri, nessuna libreria.
- **Peso contenuto**: ≤ 30 KB totali (oggi 21 KB). È una pagina di servizio che deve aprirsi subito su un tablet vecchio.
- **Nessun dato personale**: l'unica informazione conservata è lo slug della Casa nel browser.
- **Nessun imperativo verso le persone**: il sistema osserva e suggerisce, non impartisce compiti. Vale anche per i testi dell'interfaccia.
- **Lingua: italiano semplice.** Chi la usa non è tecnico e ha una persona davanti.

## Cosa voglio ricevere

1. **Un'analisi dell'architettura dell'informazione**: cosa cambieresti nella gerarchia e perché (con l'argomento, non solo la conclusione).
2. **Un layout** della Home — wireframe ad alta fedeltà o descrizione precisa: header, corpo, stati vuoti, stato «dati non disponibili», tablet.
3. **I token di design**: palette con i valori esadecimali e i contrasti calcolati, scala tipografica, spaziature.
4. **Le due soluzioni difficili**: provenienza KB/Esterna e visibilità della coda proposte — con esempi testuali, non solo descrizioni.
5. **La sezione Aiuto riscritta**: in italiano semplice, per chi ha 5 minuti.
6. **Cosa NON cambiare**, e perché.

## Nota di metodo

Non serve che produca codice pronto: produrrò io l'implementazione partendo dal tuo progetto. Quello che mi serve è **il ragionamento**, non il file finito. Se pensi che una delle mie assunzioni sia sbagliata, dillo: il punto 1 esiste proprio per questo.
