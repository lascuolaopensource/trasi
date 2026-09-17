# Confronto schemi Trasi ↔ architettura dei campi (gruppo Processi)

**Fonte**: foglio Google `12UTF0ot7w5KFiDxkyCxSdcviAyUthVRszGtCurZYmeQ` (8 fogli), scaricato il 2026-09-17
via `export?format=xlsx`. Copia locale: `docs/foglio.xlsx`; estrazione testuale: §Appendice A.
**Oggetto**: confronto campo per campo fra l'architettura di Processi e gli schemi di `db/`.
**Esito**: 5 oggetti su 8 già coperti; **gap reali** su 4; **una tensione con V5** da decidere (§4.4).

---

## 1 · Metodo

Il foglio è trattato come **elenco dei campi possibili** (parole di chi ce l'ha dato): «l'elenco di tutti i
possibili potenziali campi che compongono quegli oggetti». Quindi un campo assente dai nostri schemi **non è
automaticamente un difetto**: è una **capacità non ancora costruita**, e va decisa — non implementata
d'ufficio.

Per ogni campo ho verificato **quattro** cose, non una:

1. se il campo esiste con **lo stesso nome**;
2. se esiste con un **altro nome** (il caso più frequente: `Nome casa quartiere` → `casa.nome`);
3. se il concetto è **derivabile** da ciò che c'è (es. «luogo in cui è attualmente» ← ultimo `movimento`);
4. se il campo **non deve esistere** per un vincolo del progetto (V5). Quest'ultimo è il caso più
   importante e non è un gap: è una decisione presa.

La verifica è sui cataloghi reali (`information_schema.columns`), non sulla lettura dei file `db/*.sql`:
una colonna può essere aggiunta da un file che non si è letto.

---

## 2 · Esito sintetico, per foglio

| Foglio Processi | Nostro oggetto | Esito | Gap |
|---|---|---|---|
| 1.1 Anagrafica CdQ | `casa` | ⚠️ **parziale** | indirizzo, edificio, recapiti telefonici, **persone** |
| 2.1 Eventi | `evento` | ⚠️ **parziale** | ricorrenza, costo, fascia d'età, tag |
| 3.1 Inventario | `oggetto` + `movimento` | ⚠️ **parziale** | tipo materiale, ubicazione attuale |
| 4.1 Cronologia conversazioni | `turno` (UX-UI) + Onyx | ✅ **coperto altrove** | — |
| 4.2 Segnalazioni | `commento` (db/024) | ⚠️ **parziale** | manca il tipo «mancanza in piattaforma» |
| 4.3 Report Mensili | `report` + `v_report_mensile` | ✅ **coperto** | 2 voci non calcolate (chat interna, suggerimenti) |
| 4.4 Anagrafica cittadino | — | 🔴 **NON implementabile** | viola V5 (§4.4 sotto) |
| 4.5 Anagrafica stakeholders | — | 🔴 **assente** | nessun oggetto: da decidere |

**Il foglio «Home» elenca 9 schede ma ne documenta 8**: la **4.5 (stakeholders)** è in elenco e non ha un
foglio proprio. Non è deducibile: va chiesta al gruppo Processi.

---

## 3 · Confronto campo per campo

### 3.1 · `1.1 Anagrafica CdQ` → `casa`

| Campo Processi | Da noi | Nota |
|---|---|---|
| Nome casa quartiere | `casa.nome` ✅ | |
| Indirizzo | ⚠️ **assente su `casa`** | `luogo.indirizzo` esiste, ma è un'altra cosa: l'indirizzo della **sede**, non dei luoghi sul territorio. Abbiamo `geom` (coordinate) e non l'indirizzo civico: per un biglietto stampabile serve anche la via |
| Edificio | ❌ **assente** | nessun campo. Probabile «nome/denominazione dell'immobile» (es. «Ex scuola De Amicis»): utile all'orientamento |
| Zona (quartiere) | `casa.zona` ✅ | |
| Recapiti telefonici | ❌ **assente** | abbiamo solo `email_digest`. Un telefono di **servizio** della Casa (non di persona) è compatibile con V5 |
| Mail | `casa.email_digest` ⚠️ | il nome dice «digest»: è il recapito del riepilogo mensile. Semanticamente più stretto di «mail della Casa» — da chiarire se basta |
| Orari di apertura | `casa.orari` + `orari_eccezioni` + `orari_provvisori` ✅ | più ricco del foglio: gestiamo anche le eccezioni |
| **Persone** (Nome Cognome, Ruolo, Competenze) | 🔴 **assente come struttura** | abbiamo `casa.competenze` e `casa.persone_target` come **testo libero**, non un elenco di persone. Vedi §5: è la decisione più delicata del confronto |
| Servizi e attività ricorrenti | `scheda_servizio` ✅ | oggetto separato, con orari propri |
| Chi lo abita | ❌ **assente** | e ha lo stesso problema di «Persone» |

### 3.2 · `2.1 Eventi` → `evento`

| Campo Processi | Da noi | Nota |
|---|---|---|
| Nome casa («autocompilato dal profilo») | `evento.casa_id` ✅ | e **dall'identità**, come chiede il foglio: la Casa non si sceglie nel corpo della richiesta |
| Titolo evento | `evento.titolo` ✅ | |
| Descrizione evento | `evento.descrizione` ✅ | |
| Quando: evento specifico | `inizio`/`fine` ✅ | |
| Quando: **più giorni** | ✅ **derivabile** | `inizio` e `fine` su giorni diversi coprono il caso |
| Quando: **ricorrente** (settimana/2 settimane/mese/anno) | ❌ **assente** | nessun campo di ricorrenza. Oggi l'unico modo è creare N eventi: moltiplica le righe e **rompe l'upsert iCal** (che identifica un evento per `uid_ical`) |
| Ora: da che ora / a che ora | `inizio`/`fine` ✅ | |
| **Costo** («0 è gratuito») | ❌ **assente** | campo assente. `0` come «gratuito» è una convenzione, non un valore: meglio `costo` NULL = non noto, `0` = gratuito |
| **Fascia d'età consigliata** (slider) | ❌ **assente** | |
| **Tag** («in base ai tipi di evento») | ❌ **assente** | |
| Link all'evento | `evento.url` ✅ | |

### 3.3 · `3.1 Inventario` → `oggetto` + `movimento`

| Campo Processi | Da noi | Nota |
|---|---|---|
| Tipo di materiale | ⚠️ **assente come campo** | `oggetto.nome` e `descrizione` sono testo libero: non si può **filtrare per tipo** («mostrami tutti gli attrezzi») |
| Descrizione materiale | `oggetto.descrizione` ✅ | |
| Proprietario (lista Case) | `oggetto.casa_id` ✅ | |
| Luogo in cui è **attualmente** (lista Case) | ⚠️ **derivabile** | si ricava dall'ultimo `movimento` confermato. Calcolarlo invece di memorizzarlo evita la **seconda verità** (un campo «dove è ora» e un movimento che dice altro sono due fonti che divergono) |
| Date: prestito / ritorno previsto | `movimento.dal`/`al` ✅ | e in più `stato`, `condizione_rientro` |

### 3.4 · `4.2 Segnalazioni` → `commento` (appena creato, db/024)

Il foglio descrive **tre** cose diverse, e noi ne copriamo due:

| Cosa | Da noi |
|---|---|
| «commenti rispetto a eventi» | ✅ `commento.entita='evento'` |
| «feedback dell'operatore riguardo a ciò che accade nella casa» | ✅ `commento.entita='report'` (il rendiconto) |
| «segnalazioni di **mancanze in piattaforma**» | ❌ **manca il tipo**: serve `entita='piattaforma'` — una mancanza dello strumento, non del dato |

### 3.5 · `4.3 Report Mensili` → `report` + viste

Le voci di contenuto, una per una:

| Voce Processi | Da noi |
|---|---|
| registrazione degli accessi allo sportello | ✅ `richiesta` |
| ambiti tematici più/meno richiesti | ✅ `v_report_mensile.categoria` |
| ambiti a cui il sistema non sa rispondere | ✅ `esito='non_trovata'` |
| informazioni mancanti nel database interno | ⚠️ parziale: si vede `non_trovata`, non **cosa** manca |
| numero di domande e risposte | ✅ |
| servizi terzi verso cui si è reindirizzato | ✅ `v_destinazioni` |
| servizi erogati dalla rete proposti | ✅ |
| **analisi automatica della cronologia chat interna** (segnalazioni in sospeso) | ❌ **assente**: richiede di leggere `messaggio` (db/015) e di un'analisi che oggi non esiste |
| **indicazioni e suggerimenti operativi/strategici** | ❌ **assente**: nessun campo per il commento strategico dell'osservatorio |
| report aggregato per osservatorio | ✅ `report.ambito='osservatorio'` |

### 3.6 · `4.5 Anagrafica stakeholders` — 🔴 assente

Il foglio Home la descrive: *«Organizzazioni o persone che erogano o vorrebbero erogare eventi dentro le
CdQ»*. **Non esiste** un oggetto per questo. Ciò che gli assomiglia:

- `fonte` — sono le fonti **dati** (KB, iCal, web), non gli erogatori di eventi;
- `casa.ente_gestore` — è una stringa, non un'anagrafica;
- `luogo.tipo='associazione'` — un **luogo**, non un'organizzazione con un rapporto.

Serve una decisione: è un'anagrafica nuova (`stakeholder`) o è un `luogo` con un ruolo? La differenza è
sostanziale: un luogo ha una posizione geografica e un orario, un possibile stakeholder no.

---

## 4 · 🔴 La tensione con V5 — `4.4 Anagrafica cittadino`

Il foglio chiede: *«Ogni casa di quartiere ha una scheda che raccoglie **età, genere, provenienza**»*.

**Questo va contro V5.** Il progetto ha un presidio esplicito e verificato: la tabella `richiesta` **non ha
nessun campo del cittadino**, e `t_seed.sql` (O05) **fallisce** se qualcuno ne aggiunge uno:

```
IF colonne IS NOT NULL THEN RAISE EXCEPTION 'FAIL O05 (V5) — richiesta ha colonne extra: %', colonne;
```

Non è una svista: è §12 del piano («nessun campo per il cittadino») e la ragione per cui esiste il
**k-anonimato 5** — i conteggi sotto soglia non esistono, non sono nascosti. Salvare età/genere/provenienza
di una persona che va allo sportello significa costruire un registro di persone vulnerabili, con i dati
che la legge classifica come particolari (origine etnica, convinzioni) — e con un solo operatore che digita,
la re-identificazione è immediata. `age` + `genere` + `provenienza` + `data` + `casa` identifica una persona
in un quartiere piccolo.

**Ma il bisogno dietro il foglio è legittimo**, ed è il foglio 4.3: i report devono dire *«gli ambiti più
richiesti»*, e per farlo servono **distribuzioni**, non persone. La forma compatibile con V5 esiste già ed è
quella che il progetto usa altrove (`v_report_mensile`, `v_confronto_case`): **fasce**, non valori, e
**conteggi mascherati** da `k_anon`.

La traduzione corretta del foglio 4.4 è quindi:

| Foglio | Forma compatibile con V5 |
|---|---|
| età | **fascia** (`14-17`, `18-29`, `30-44`, `45-59`, `60-74`, `75+`), mai la data di nascita |
| genere | categoria a **vocabolario chiuso**, e «non dichiarato» come valore legittimo |
| provenienza | **area** (Italia / UE / extra-UE), non il Paese né la nazionalità |

…e i campi stanno **sul registro del colloquio** (`richiesta`), dove già vivono categoria ed esito, con il
conteggio che esce solo mascherato. Nessun identificativo di persona, nessun collegamento a una chat, e la
retention delle chat (30 gg) resta l'unico posto dove esiste un testo.

**Questa è una decisione da prendere con Processi e il DPO, non da implementare.** Non l'ho implementata:
introdurre `casa_id + età + genere + provenienza` su una tabella che il progetto ha costruito per non
averli è il tipo di modifica che va discussa, non consegnata.

---

## 5 · La sotto-decisione di `1.1 Persone` (nome, ruolo, competenze)

Il foglio chiede una scheda per le persone che lavorano e frequentano la Casa: nome, cognome, ruolo,
competenze. È **diverso** da 4.4 e va distinto con chiarezza:

- sono **operatori della rete**, non cittadini — quindi non riguarda i dati dei fruitori del servizio;
- ma «nome e cognome» **sono** dati personali, e finirebbero in una tabella del dominio, esportabile in KB
  (`v_kb_export`) e quindi **citabile dall'assistente in chat**.

Il rischio concreto: chiedere all'assistente «chi è il referente di San Bao?» e ricevere un nome proprio.
Oggi il progetto lo ha risolto **alla radice**: la scheda ha `referente_ruolo` (il *ruolo*, non la persona) —
una scelta che il foglio non prevede ma che è coerente con V5.

Anche questa è una decisione: un'anagrafica delle **persone** richiede di decidere (a) se entra in
`v_kb_export`, (b) con quale retention, (c) se il nome può uscire in chat. Se il gruppo Processi la vuole,
va fatta con consenso e informativa — non è una colonna in più.

---

## 6 · Adeguamento proposto

### 6.1 · Da fare ora (campi additivi, nessuna tensione con V4/V5)

Sono i campi che il foglio chiede e che **non toccano** privacy né il flusso proposte. Li ho implementati in
`db/025_campi_processi.sql`:

| Oggetto | Campo | Perché è sicuro |
|---|---|---|
| `casa` | `indirizzo`, `edificio` | indirizzo civico della sede e denominazione dell'immobile: informazioni **pubbliche** di un edificio. Il biglietto A6 ha già l'indirizzo del luogo di destinazione; quello della sede lo completa |
| `evento` | `costo`, `fascia_eta`, `tag[]` | informazioni **dell'evento**, pubbliche per definizione (una locandina le ha) |
| `evento` | `ricorrenza` | evita di creare N righe per un evento settimanale, che romperebbe l'upsert iCal |
| `oggetto` | `tipo` | rende l'inventario **filtrabile** («tutti gli attrezzi»), che oggi non è |
| `commento` | tipo `piattaforma` | completa il foglio 4.2 |
| `report` | `suggerimenti` | la voce «indicazioni e suggerimenti» del 4.3 |

Tutti i nuovi campi testuali passano dal **filtro anti-PII** dello shim, come gli esistenti.

### 6.1.1 · Il campo che ho aggiunto e poi **rimosso**: `casa.telefono`

Il foglio 1.1 chiede i «Recapiti telefonici» della Casa. Li avevo implementati come colonna. Poi ho provato a
scriverli:

```
$ salva_dato {entita: casa, telefono: "0831 000000"}
422 {"detail":"dato_personale_sospetto — campi con dati personali: telefono"}
```

**Il filtro anti-PII ha rifiutato il mio stesso dato, e aveva ragione.** `pii.TELEFONO` riconosce qualunque
numero fisso o cellulare italiano e **non può distinguere** un centralino di sportello da un cellulare
personale: la differenza non è nella forma del numero.

Da qui la conclusione, che non è «aggiungo il campo e sto attento»: **il sistema non può verificare** la
promessa «è un numero di servizio». Una colonna che accetta numeri in una tabella esportata in
`v_kb_export` — quindi **citabile dall'assistente in chat** — riapre per la porta di servizio ciò che V5/§12
tiene fuori dalla porta principale. Ho rimosso il campo: un campo che non si può popolare senza rifiutare il
valore è un campo che confonde chi lo trova vuoto.

**Dove il recapito può stare**: `casa.email_digest` (già esistente, indirizzo di servizio) e i **luoghi**
(`luogo.indirizzo`). Se Processi vuole un telefono di Casa, la via è decidere *come* garantire che non sia
personale — non una colonna in più (§6.2, voce 1-bis).

### 6.2 · Da decidere (non implementati)

| # | Voce | Chi decide |
|---|---|---|
| 1 | **4.4 età/genere/provenienza** in forma aggregata (fasce + k-anon) | Processi + DPO |
| 1-bis | **Recapito telefonico della Casa**: con quale garanzia che non sia personale? (il filtro PII lo rifiuta, e non può fare altrimenti) | Processi + DPO |
| 2 | **Persone** della Casa (nome, ruolo, competenze): se e come | Processi + DPO |
| 3 | **4.5 stakeholders**: anagrafica nuova o `luogo` con un ruolo | Processi |
| 4 | «analisi automatica della chat interna» nel report mensile | Processi + TI (richiede un'analisi che non esiste) |
| 5 | `casa.email_digest` basta come «Mail» della Casa? | Processi |
| 6 | «informazioni mancanti nel database»: basta `non_trovata`, o serve registrare **cosa** manca? | Processi |
| 7 | **`oggetto.tipo`**: vocabolario aperto finché Processi non fornisce l'elenco dei tipi di materiale | Processi |

### 6.3 · Non da fare (e perché)

- **`oggetto.ubicazione_attuale`**: derivabile dall'ultimo `movimento` confermato. Memorizzarlo creerebbe una
  **seconda verità** che può divergere dal registro dei movimenti — lo stesso difetto che
  `v_report_mensile` esiste per evitare.
- **«più giorni»** su `evento`: già coperto da `inizio`/`fine` su giorni diversi.

---

## Appendice A · Il foglio come è arrivato

Estratto fedele (nome foglio, righe, contenuto per colonna). Le celle vuote sono vuote nel foglio.

```
FOGLIO: Home (9 righe)
  Database | Scheda | Descrizione
  1. INFO CDQ | 1.1 Scheda Anagrafica CdQ | l'anagrafica della casa con i dati delle persone che ci lavorano e la frequentano
  2. EVENTI | 2.1 Scheda Eventi | eventi/formazioni/workshop che avvengono nelle case di quartiere
  3. INVENTARIO | 3.1 Scehda Inventario | dati che servono per scambiarsi materiali
  4. REPOSITORY INTERAZIONI | 4.1 Cronologia conversazioni chatbot | cronologie delle interazioni Operatore-AI
    | 4.2 Segnalazioni | segnalazioni di mancanze in piattaforma o commenti rispetto a eventi o feedback dell'operatore
    | 4.3 Report Mensili | si raccolgono tutti i report mensili
    | 4.4 Anagrafica Cittadino | ogni casa ha una scheda che raccoglie età, genere, provenienza
    | 4.5 Anagrafica di possibili stakeholders | organizzazioni o persone che erogano o vorrebbero erogare eventi dentro le CdQ

FOGLIO: 1.1 Anagrafica (13 righe)
  Nome casa quartiere · Indirizzo · Edificio · Zona (quartiere) · Recapiti telefonici · Mail · Orari di apertura
  Persone: Nome Cognome / Ruolo / Competenze
  Servizi e attività ricorrenti · Chi lo abita

FOGLIO: 2.1 Eventi (16 righe)
  Nome casa di questiere (autocompilato dal profilo) · Titolo evento · Descrizione evento
  Quando: Evento specifico / Più giorni / Ricorrente (Ogni settimana, Ogni 2 settimane, Ogni mese, Ogni anno)
  Ora: Da che ora / A che ora
  Costo (casella testo, 0 è gratuito) · Fascia d'età consigliata (Slider) · Tag (in base ai tipi di evento) · Link all'evento

FOGLIO: 3.1 Inventario (6 righe)
  Tipo di materiale · Descrizione materiale · Proprietario (lista con le case)
  Luogo in cui è attualmente (lista con le case) · Date: Data di prestito / Data di ritorno previsto

FOGLIO: 4.1 Cronologia conversazioni chatbot (1 riga)
  «Qui ci sono tutte le cronologie rispetto alle interazioni di utilizzo Operatore-AI»
  (nessun campo: solo la descrizione)

FOGLIO: 4.2 Segnalazioni (1 riga)
  «Qui a livello testuale l'operatore può inserire eventuali segnalazioni di mancanze in piattaforma o anche
   commenti rispetto a eventi o feedback dell'operatore riguardo a ciò che accade nella casa»
  (nessun campo: solo la descrizione)

FOGLIO: 4.3 Report Mensili (10 righe)
  titolo output: «report mensile case di quartiere» | «report mensile aggregato per osservatorio»
  Contenuti (per il report della Casa):
    - registrazione degli accessi al servizio presso lo sportello di front desk (form di registrazione)
    - gli ambiti tematici più ricorrenti e i meno richiesti tra le domande di assistenza
    - ambiti di domanda a cui il sistema non riesce a dare risposta
    - presenza di informazioni e dati necessari a dare risposte che non sono presenti nel database interno
    - numero di domande poste e di risposte fornite
    - numero totale e frequenza di servizi terzi (pubblici istituzionali, ETS locali) verso cui sono stati reindirizzati gli utenti
    - numero totale e frequenza di servizi erogati dalla rete delle case di quartiere proposti nelle risposte
    - analisi automatica della cronologia della chat interna tra case e admin (segnalazioni in sospeso, criticità, opportunità)
  Contenuti (per il report dell'osservatorio):
    - analisi e report aggregato di tutti i report dei singoli sportelli, con grafici, elementi ricorrenti e criticità
    - indicazioni e suggerimenti operativi rispetto ad aggiornamenti e integrazione dei dati
    - indicazioni e suggerimenti strategici e di gestione per l'intero ecosistema del servizio

FOGLIO: 4.4 Anagrafica cittadino (3 righe)
  Genere · Età · Provenienza

FOGLIO: 4.5 — ASSENTE come foglio (presente solo nell'elenco della Home)
```
