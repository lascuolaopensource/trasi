# User stories — schede `!NEW` della Scheda Prodotti

Fonte: Scheda Prodotti (Google Doc), tab il cui nome inizia con `!NEW`.
Data estrazione: 2026-09-16.
Convenzione: **CdQ** = Casa di Quartiere; **O** = operatore; **AI** = assistente Onyx/Trasi.

Vincoli trasversali del progetto (da rispettare in OGNI acceptance criteria):
- **V3**: ogni risposta AI dichiara la fonte (`[KB · …]` / `[Esterna · …]`).
- **V4**: nessuna scrittura diretta al dominio fuori da proposta → approvazione → applicazione (unica eccezione: upsert iCal su `evento`).
- **V5**: nessun dato personale del cittadino in DB, biglietti, export, log.
- **V6**: i messaggi dicono *chi decide*, non assegnano compiti a persone.
- **k-anonimato**: conteggi sotto soglia mostrati come `<5`.

Legenda stato AC: ✅ derivato dal testo della scheda · 🟡 deduzione ragionata, da confermare · ❓ dato mancante nella scheda, da definire.

---

## !NEW 1 — Eventi (POV operatore)

**Titolo:** Palinsesto generale eventi e attività delle CdQ
**Servizio:** raccolta degli eventi proposti da ciascuna CdQ in un palinsesto condiviso, visibile a tutta la rete.

### US-1.1 — Inserimento evento
Come operatore CdQ, voglio inserire un evento/attività/laboratorio della mia CdQ con le sue caratteristiche, perché entri nel palinsesto condiviso della rete.

AC:
- ✅ L'inserimento passa dal flusso proposta → approvazione → applicazione (V4), mai scrittura diretta.
- ✅ L'AI segnala i dati mancanti utili al cittadino (es. prenotazione, costo, accessibilità) prima della pubblicazione.
- 🟡 Campi minimi: titolo, data/ora, luogo, CdQ proponente, categoria/target, caratteristiche di accesso (gratuito/prenotazione), fonte dell'informazione.
- ✅ Tipi di dato ammessi: testo, audio-video, immagine, link esterni con preview.
- ✅ La risposta AI conferma l'inserimento dichiarando chi approva/decide (V6).

### US-1.2 — Consultazione palinsesto filtrato
Come operatore, voglio chiedere all'AI gli eventi filtrati per zona/quartiere, data, categoria target o parola chiave, per rispondere al cittadino con informazioni aggiornate.

AC (dai Q&A della scheda):
- ✅ «Quali eventi questo weekend vicino a me?» → filtro per zona + fascia data.
- ✅ «Laboratorio per bambini questa settimana?» → filtro per categoria target (famiglie/minori) + fascia data.
- ✅ «Prossimo evento su disabilità/caregiver?» → filtro per tema + data; la risposta include luogo, durata, gratuità, garanzie di accesso.
- ✅ Ogni risposta dichiara la fonte (V3) e la data di aggiornamento dell'informazione.
- ✅ Informazione mancante → l'AI lo dichiara e indica contatto pubblico (telefono/email istituzionale), non inventa.

### US-1.3 — Scheda evento unificata stampabile
Come operatore, voglio generare l'export stampabile dell'evento selezionato (locandina + caratteristiche di accesso e svolgimento), da stampare direttamente dalla UI.

AC:
- ✅ «Dammi la locandina dell'evento X da stampare» → l'AI produce l'export; formato PDF scaricabile E/O pagina HTML stampabile da browser (❓ scelta formato).
- ✅ L'export contiene: titolo, data/ora, luogo, caratteristiche di accesso, contatto pubblico, fonte + data aggiornamento, badge `[KB …]`/`[Esterna …]`.
- ✅ Nessun dato personale del cittadino, nessun campo compilabile a mano (come il biglietto A6 esistente).
- 🟡 Stessa pipeline del biglietto A6 esistente (`/biglietto`), estesa o affiancata da endpoint evento.
- ✅ Eventi importati da Gancio (solo lettura, ICS/API) appaiono nel palinsesto con badge fonte esterna e sono stampabili allo stesso modo.

### US-1.4 — Controllo completezza e freschezza
Come operatore, voglio sapere quali schede evento sono incomplete o datate, per sollecitare l'aggiornamento.

AC:
- ✅ «Quali eventi mancano di informazioni complete?» → elenco con i dati mancanti; l'AI suggerisce, la decisione resta all'operatore (V6).
- ✅ Il sistema segnala eventi pubblicati con data antecedente di 2 mesi per verifica aggiornamento.

---

## !NEW 2 — Servizi (POV operatore)

**Titolo:** Consultazione servizi della rete CdQ e della cittadinanza
**Servizio:** supporto all'operatore per rispondere al cittadino su opportunità e servizi, con materiali esportabili.

### US-2.1 — Orientamento e indirizzamento
Come operatore, voglio che l'AI trasformi una richiesta generica in un'indicazione operativa di servizio, per orientare il cittadino.

AC:
- ✅ Per ogni servizio individuato la risposta include, quando disponibile: cosa offre → destinatari → dove → quando → come accedere → contatto → fonte dell'informazione.
- ✅ Contatti solo pubblici/istituzionali (V5).
- ✅ Fonte dichiarata su ogni risposta (V3).

### US-2.2 — Ricerca su banca dati interna ed esterna
Come operatore, voglio che l'AI attinga al DB interno della rete (aggiornato dalle CdQ) e a fonti esterne (Comune, CAF, INPS…), per una risposta unica.

AC:
- ✅ Priorità/ordine delle fonti dichiarato nella risposta.
- ✅ Informazione datata → segnalazione «aggiornata il …, si consiglia verifica» (l'AI non aggiorna da sé).
- ✅ Ricerca esterna solo da fonti in allow-list (meccanismo esistente `cerca_web` dello shim).

### US-2.3 — Output multicanale esportabili
Come operatore, voglio trasformare la risposta in formati diversi (testo, email, documento, scheda informativa stampabile), per consegnarla al cittadino.

AC:
- ✅ Stampa diretta da UI; ❓ elenco dei formati effettivamente richiesti (mail come bozza? documento in che formato?).
- ✅ Ogni output rispetta V5 (nessun campo cittadino).
- 🟡 La scheda servizio stampabile riusa la pipeline del biglietto A6.

### US-2.4 — Mappa servizi
Come operatore, voglio una mappa interattiva che geolocalizza schede servizio e CdQ, per mostrare dove sono i servizi.

AC:
- 🟡 Integrazione con dashboard Metabase «Mappa» esistente o nuova vista; ❓ scelta.
- ✅ Coordinate e dati solo pubblici.

---

## !NEW 3 — Monitoraggio (POV operatore)

**Titolo:** Inserimento dati per il monitoraggio del servizio
**Servizio:** raccolta dati dal Servizio di Prossimità (attività, bisogni rilevati, risorse) a fini di ricerca e proposte di welfare.

⚠️ Scheda quasi vuota (solo descrizione parziale e beneficiario: ufficio comunale). Storie minime:

### US-3.1 — Registrazione richiesta allo sportello
Come operatore, voglio registrare una richiesta del cittadino in forma aggregata/anonima, per alimentare il monitoraggio.

AC:
- ✅ Dati registrati: categoria della richiesta, servizio cercato, fascia oraria, esito (risposta data / non possibile).
- ✅ Mai dati personali del cittadino (V5): niente nome, contatti, estremi identificativi.
- ❓ Fascia d'età/genere: richiesti nella scheda OLD-9 e vietati da V5 in forma individuale → solo se aggregati; da confermare con DPO.

### US-3.2 — Vista operatore sul proprio inserimento
Come operatore, voglio vedere cosa ho registrato oggi, per verificare.

AC:
- 🟡 Riga «Oggi» della Home o dashboard dedicata; ❓ da confermare.

---

## !NEW 4 — Monitoraggio (POV PA)

**Titolo:** Report di monitoraggio del servizio per la PA
**Servizio:** report mensili aggregati sull'attività della rete (flussi, bisogni, ambiti di domanda, servizi attivati) per il Comune di Brindisi.

### US-4.1 — Report periodico aggregato
Come funzionario PA, voglio ricevere un report mensile aggregato sull'attività della rete CdQ, per rendicontare le risorse e orientare il welfare.

AC:
- ✅ Contenuti: flussi di accesso, bisogni rilevati, ambiti di domanda, servizi attivati.
- ✅ Frequenza: 1 mese, generazione automatica (flusso schedulato, coerente con `flussi/` esistente).
- ✅ k-anonimato: conteggi `<5` soppressi/mascherati.
- ✅ Solo dati aggregati, nessuna conversazione individuale conservata (V5; la distinzione storico-statistico vs conversazione è esplicita nella scheda Front Office).
- ❓ Formato: dashboard Metabase «Osservatorio» esistente, PDF, o entrambi?

### US-4.2 — Accesso autonomo PA
Come funzionario PA, voglio consultare il monitoraggio quando serve, non solo al report mensile.

AC:
- 🟡 Accesso PA alla dashboard con ruolo dedicato (vedi US-6).
- ❓ Journey realistica PA↔AI indicata nella scheda ma vuota → da definire con il Comune.

---

## !NEW 5 — Attrezzoteca (POV operatore)

**Titolo:** Attrezzoteca
**Servizio:** database di materiali/arredi/utensili condivisi dalle CdQ, con gestione prestiti e spostamenti.

### US-5.1 — Inventario consultabile
Come operatore, voglio sapere dove si trova un oggetto, in che quantità e condizioni, per prenderlo in prestito.

AC (dai Q&A della scheda):
- ✅ «5 microfoni per domani, dove?» → risposta con CdQ, quantità disponibile, contatti.
- ✅ Disponibilità in tempo reale (stato aggiornato a ogni movimento confermato).
- ✅ Fonte del dato dichiarata (V3).

### US-5.2 — Prenotazione anticipata
Come operatore, voglio prenotare un oggetto per un periodo futuro, con segnalazione dei conflitti.

AC:
- ✅ Conflitto stesso oggetto / stesso periodo → segnalato a entrambe le CdQ; la decisione resta umana (V6).
- ❓ Politica di risoluzione conflitti (priorità? mediazione?) non definita nella scheda.

### US-5.3 — Registrazione spostamento con conferma
Come operatore della CdQ cedente, voglio registrare lo spostamento e ottenere conferma dalla CdQ ricevente, per tenere l'inventario affidabile.

AC:
- ✅ Spostamento registrato → notifica alla CdQ ricevente → conferma esplicita → stato aggiornato.
- ✅ Traccia: chi sposta, da dove a dove, quando.
- ✅ Ad ogni passaggio si registra la condizione (integro / danneggiato / mancante di parti).

### US-5.4 — Manutenzione e statistiche d'uso
Come rete, voglio segnalazioni su oggetti da manutenere, in ritardo di rientro, poco o molto utilizzati.

AC:
- ✅ Mancato rientro oltre i tempi previsti → segnalazione (non addebito automatico: V6).
- ✅ Oggetti scarsamente usati → candidati a cessione; molto richiesti → candidati a secondo esemplare.
- ❓ Soglie (giorni di ritardo, frequenza d'uso) da definire.

---

## !NEW 6 — Login (POV operatore)

**Titolo:** Registrazione e accesso alla piattaforma TRASI
**Servizio:** accesso differenziato per ruolo (CdQ, monitoraggio, PA/Osservatorio).

### US-6.1 — Login unico per CdQ
Come operatore, voglio accedere con le credenziali della mia CdQ, per usare le funzioni che mi competono.

AC:
- ✅ Un solo account per CdQ (decisione progettuale 2026-09-16); niente login cittadini nei primi 12 mesi.
- ✅ A seconda del ruolo (operatore CdQ / monitoraggio / PA) si afferisce a funzioni diverse.
- ✅ Le credenziali passano al nuovo ente gestore nei subentri e vengono aggiornate periodicamente (rotazione).
- ❓ Meccanismo: account Onyx nativi vs autenticazione a monte (Caddy/reverse proxy) → legato alla chat unificata (correzione #3).

### US-6.2 — Sessione comoda e senza redirect
Come operatore, voglio restare nella stessa piattaforma senza salti di dominio, per lavorare senza attriti.

AC:
- ✅ Nessun redirect verso domini esterni durante l'uso normale (vincolo architetturale #5).
- 🟡 Chat integrata nella piattaforma via API server-to-server (opzione C discussa).

---

## !NEW 7 — Chat interna segnalazioni (POV operatore)

**Titolo:** Chat di comunicazione interna tra CdQ e PA
**Servizio:** canale rapido tra enti gestori e PA: esigenze, problemi, richieste di supporto, solleciti di aggiornamento dati.

### US-7.1 — Canale di comunicazione operativa
Come operatore CdQ o responsabile comunale, voglio un canale chat interno alla piattaforma, per comunicare senza strumenti esterni.

AC:
- ✅ L'AI **non interviene** in questo canale (dichiarato in scheda: «Cosa ci aspettiamo che faccia l'AI: Niente»).
- ✅ Il canale vive dentro la piattaforma gestionale (stesso login, US-6).
- ✅ Uso bidirezionale: PA → enti (aggiornamenti, interruzioni, solleciti aggiornamento DB) e CdQ ↔ CdQ / CdQ → PA.
- ❓ Tecnologia: semplice bacheca/messaggi nel DB Trasi (con audit) vs strumento esterno integrato. Da decidere.
- 🟡 I messaggi non sono eventi di dominio: non passano dal flusso proposte (V4 si applica al dominio, non alle comunicazioni), ma la cronologia va conservata secondo policy privacy da definire.

---

## Copertura schede e buchi

| Scheda | Stato contenuto | Buci principali |
|---|---|---|
| !NEW 1 Eventi | completa | formato export (PDF vs HTML), campi minimi definitivi |
| !NEW 2 Servizi | quasi completa | formati output multicanale, mappa (Metabase vs nuova) |
| !NEW 3 Mon. operatore | scarna | dati di affluenza (età/genere) vs V5 → decisione DPO |
| !NEW 4 Mon. PA | media | formato report, journey PA↔AI vuota |
| !NEW 5 Attrezzoteca | completa | politica conflitti, soglie ritardi/uso |
| !NEW 6 Login | scarna | meccanismo auth (dipende da chat unificata) |
| !NEW 7 Chat interna | media | tecnologia canale, retention messaggi |
