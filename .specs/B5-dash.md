# TASK SPEC — B5 Metabase: dashboard, k-anonimato, alert (`trasi-dash`)

## Target

Avvia Metabase e costruisci le **3 dashboard** (Rete, Casa, Mappa) + gli **alert per Casa**, usando le viste già esistenti.

## Contesto verificato (non ri-verificare)

**Servizi attivi:** `trasi-db_trasi-1`, `trasi-searxng-1`, `trasi-shim-1`, `automazioni`. **RAM: ~6,3 GB liberi.**

**Metabase è definito nel compose ma NON avviato** (scelta di RAM in B0). Va avviato ora, con i limiti già previsti: `mem_limit 1.5g`, `JAVA_OPTS=-Xmx1g`. Comando: `docker compose -f deployment/docker-compose.yml up -d metabase` (aggiungi il file `deployment/docker-compose.automazioni.yml` se serve, ma **non modificare** `docker-compose.yml`: è di `trasi-stack` — coordina via `hub` se ti serve un cambiamento).

Se Metabase usa un **app-DB** (Postgres), verifica che sia definito; il default H2 non va bene per la persistenza.

**Il ruolo `metabase_ro` è pronto e verificato:**
- `has_table_privilege('metabase_ro','trasi.casa','SELECT')` = **t**
- `has_table_privilege('metabase_ro','trasi.richiesta','SELECT')` = **f** (least-privilege voluto)
- `SET ROLE metabase_ro; SELECT count(*) FROM trasi.v_oggi_casa` → **10** (le viste funzionano)

**15 viste già esistenti** in `trasi`, tra cui quelle che ti servono:
`v_mappa_case`, `v_mappa_luoghi`, `v_mappa_luoghi_vicini`, `v_destinazioni`, `v_oggi_casa`, `v_proposte_aperte`, `v_scaduti`, `v_in_scadenza`, `v_senza_risposta`, `v_report_mensile`, `v_confronto_case`, `v_kb_export`, `v_scritture_senza_audit`, `v_flusso_alert_proposte`, `v_flusso_coerenza_fonti`.

**Leggi `db/004_views.sql` e `db/020_flusso.sql`**: sono la fonte di verità sulle colonne. Non indovinare i nomi.

**Alert già implementati in B4** (`flussi/alert.py`, con `v_flusso_*`): proposte in attesa >7gg e coerenza fonti, con destinatari per ruolo. **Il tuo compito sugli alert è la parte Metabase** (i 4 alert F6 del piano: scaduti, in scadenza, senza risposta, proposte in attesa), **non duplicare** quelli di B4: coordina via `hub` con `trasi-flussi` se c'è sovrapposizione, e **una sola sorgente di email per alert**.

## Change

### 1. Avvio Metabase + connessione
- container healthy, app-DB persistente, amministratore creato (credenziali in un file protetto, **non stamparle**)
- connessione «Trasi» con `metabase_ro`

### 2. Dashboard «Trasi · Rete» (`B5-DSH-04`)
- filtro periodo (default ultimi 30 giorni)
- richieste per Casa, esiti per Casa, categorie per Casa, proposte aperte per approvatore, scadute/in scadenza, senza risposta
- **k-anonimato**: da `v_confronto_case`/`v_report_mensile`, dove `n` è già NULL sotto soglia con `n_label='<5'`
- text card di testata con i **4 campi V6**

### 3. Dashboard «Trasi · Casa» (`B5-DSH-05`)
- filtro **Casa** (obbligatorio) + periodo
- riga «Oggi» da `v_oggi_casa` (3 numeri: eventi, schede in scadenza, proposte)
- tabella `v_proposte_aperte` (tipo, entità, origine, giorni di attesa, approvatore, motivazione) + link alla coda NocoDB
- scaduti / in scadenza; destinazioni della Casa

### 4. Dashboard «Trasi · Mappa» (`B5-DSH-06`)
- pin map delle 10 Case da `v_mappa_case` (lat/lon)
- pin dei luoghi da `v_mappa_luoghi`; con filtro Casa, `v_mappa_luoghi_vicini`
- destinazioni delle richieste da `v_destinazioni` (tooltip con `n_label`, **mai** il numero sotto soglia)
- ⚠️ Metabase **non disegna cerchi di raggio**: il raggio va nel tooltip come testo

### 5. Alert per Casa (`B5-DSH-07/08`)
- i 4 alert F6 (scaduti, in scadenza, senza risposta, proposte in attesa >7gg), ognuno recapitatato **alla Casa giusta**
- **V6**: revisione dei testi, con verifica automatica (regex sui verbi imperativi → 0 occorrenze)
- idempotenza: rieseguire la creazione non duplica gli alert

## Constraints

- **RAM**: Metabase con `mem_limit 1.5g` e `-Xmx1g`. Verifica con `docker stats` che non saturi; se l'host va in sofferenza, **segnalalo** invece di alzare il limite.
- **V5/k-anonimato**: sotto soglia il numero grezzo non appare **da nessuna parte** (celle, tooltip, ordinamenti).
- **V6**: nessun verbo imperativo; i 4 campi dove si suggerisce.
- **Sola lettura**: `metabase_ro`; nessuna Model action abilitata.
- Non modificare `db/000–020` (B1/B4), `shim/**` (B3), `flussi/**` (B4). Se ti serve una vista nuova, **chiedila** via `hub`.
- Non avviare NocoDB/Activepieces (RAM).

## Ownership

Configurazione Metabase (via UI/API), `metabase/**` se crei script. Il compose è di `trasi-stack`.

## Observable acceptance (prove reali)

1. Metabase **healthy**; `docker stats` mostra l'uso entro il limite.
2. Connessione «Trasi» attiva con `metabase_ro`; in Admin › Table Metadata **non** compaiono `richiesta`, `proposta`, `audit`, `identita_onyx`.
3. **k-anonimato**: con 4 richieste di una Casa in una categoria la cella mostra **`<5`**; con 5 mostra `5`; con 0 mostra `—`. Provalo davvero (fixture + ROLLBACK o clone).
4. Mappa: `count(*) FROM v_mappa_case` = **10** pin; Tuturano visibile con `raggio_m_eff=2000`; con filtro Bozzano la card dei luoghi contiene il bar interno.
5. **Performance**: la dashboard si apre in < 3 s (misura o `running_time` delle card).
6. Alert: con una scheda scaduta **solo** a San Bao, l'alert arriva a San Bao e **non** a Bozzano. Verifica il destinatario reale.
7. **V6**: regex sui testi (celle, tooltip, alert) per verbi imperativi → **0** occorrenze.
8. Screenshot delle 3 dashboard (le dashboard vanno **guardate**, non solo salvate).

Riporta comandi e output reali. Se un criterio è rosso, dillo.

## Nota
Il piano è in `plan.md` (§4 B5, i criteri §10 B5), l'architettura in `docs/trasi-architecture-v1.2.md` (§4.3 Home→MAPPA/OSSERVATORIO, §7.3 viste, §6 Metabase, §12 k-anonimato). In conflitto **vince l'architettura**. **Leggi `docs/verifiche.md`**: contiene scoperte già fatte che non devi riscoprire.
