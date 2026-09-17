# Bug trovati durante l'analisi del golden set

**Data:** 2026-09-17 · **Chi:** sessione test-tuning-risposte-idempotenza · **Metodo:** misure live su stack, DB, shim, Onyx (comandi e output verificati, non inferenze)

Escluso dalla lista per decisione di prodotto: il **PDF** come formato di export (sostituito dall'HTML stampabile — decisione confermata; il ramo `86b15fc` che aggiungeva `_pdf_dall_html` non è deployato e non va deployato).

---

## P0 — bloccano il golden set e l'ingestion

### BUG-01 · Il shim deployato è indietro rispetto a main: `cerca_luogo` non espone `id` → il modello non può chiamare `biglietto` correttamente

- **Dove:** container `trasi-shim-1`, costruito da `puria/resoconto-connettori` (`e6c9aab`); main/`86b15fc` aggiunge `id` a `ItemLuogo` proprio per questo.
- **Prova:** `GET /v1/u/…/cerca_luogo?q=INPS` → item **senza** campo `id` (`schemi.py` del container, riga 29: `ItemLuogo` senza `id`; md5 `/app/openapi.yaml` = `3f2687c6…` ≠ HEAD `8f40a9db…`). `biglietto?luogo_id=CAF ACLI La Rosa` (il nome) → **422**.
- **Effetto:** la storia «leggo l'id → stampo» è rotta in chat: il modello riceve istruzioni nel prompt (`docs/prompt-assistente-*.txt` riga 20) che il tool non può soddisfare.
- **Fix:** redeploy dello shim da `main` (include `86b15fc`). Nessuna modifica di codice.

### BUG-02 · Tool PA `lacune` → 500 (colonna e GRANT mancanti: migrazione 031 parzialmente applicata)

- **Dove:** `GET /v1/m/pa@trasi.local/lacune` e `/pa/report` (browser) → **500**; log: `asyncpg.exceptions.InsufficientPrivilegeError: permission denied for view v_report_mensile` e `UndefinedColumnError: column r.stato does not exist`.
- **Prova:** live 17/09 20:4x; `has_table_privilege('pa','trasi.v_report_mensile','SELECT')` → `f`; `v_report` live **non** espone `stato` (definizione di `024`), mentre `report.stato` esiste e `crea_sessione_servizio`/`v_report_fasce`/`v_chat_mensile` (di `031_report_pa.sql`) sì: migrazione applicata **a metà** o `024` rieseguita dopo e ha sovrascritto `v_report` + i GRANT di `031`.
- **Effetto:** l'assistente «Trasi Monitoraggio PA» dichiara guasto su lacune/report; `monitoraggio_report` tool → 500.
- **Fix:** rieseguire `db/031_report_pa.sql` (idempotente: ricrea `v_report` con le colonne di stato e i GRANT a `pa` su `v_report_mensile`, `v_report`, `casa`) e ri-eseguire `apply.sh` con l'ordine del ramo `wip/monitoraggio-pa`.

### BUG-03 · Cron export KB rotto: mount `automazioni` punta a un worktree cancellato

- **Dove:** `trasi-automazioni-1`; mount `bind` `/root/orca/workspaces/onice/resoconto-connettori/flussi` → `/app/flussi`, directory **vuota** (worktree rimosso).
- **Prova:** `/var/log/trasi/export_kb.log` (07:30/01:00) → `export_kb: PAT Onyx assente`; `docker exec trasi-automazioni-1 ls /app/flussi` → 0 file; `docker inspect` → Source su percorso inesistente.
- **Effetto:** la KB di Onyx non si aggiorna dal cron: misurata **stale** — in Onyx ci sono 2 eventi passati (2861, 3063) da rimuovere e manca `luogo:1272` (diff vista vs Onyx verificata, 47 vs 48).
- **Fix:** aggiornare `deployment/docker-compose.yml` (`/root/orca/projects/onice/flussi` → `/app/flussi`) + `docker compose up -d automazioni`; poi rilancio manuale `flussi/export_kb.py`.

## P1 — comportamenti errati / incoerenze

### BUG-04 · Proposte `promuovi_esterno` su entità già in KB e **mai applicate** (restano `approvata` senza `applicata`)

- **Prova:** proposte 6901/6902 (`promuovi_esterno`, `luogo` 21 e 1272, payload «CAF Promosso B4TEST»): stato `approvata`, `approvato_da=rete`, audit `proposta_creata`+`transizione` ma **nessuna** riga `applicata`; `v_scritture_senza_audit` segnala luogo 21/1272 (aggiornati senza riga `applicata`).
- **Nota:** due scritture nella vista sono **mie** (UPDATE diagnostico con ruolo `postgres` durante l'indagine — non è un difetto del sistema); il difetto è che l'**applicazione** di `promuovi_esterno` avvenuta alle 21:01 (misurata via `aggiornato_ts` originari 21:01:25) ha lasciato le proposte in `approvata` senza audit `applicata`, e la vista di contabilità le conta come scritture sospette.
- **Fix da verificare:** `applica_proposte_approvate` (cron 05:00) deve completare la transizione + audit per il tipo `promuovi_esterno`.

### BUG-05 · Duplicato in KB: `CAF ACLI La Rosa` presente 2 volte (id 21 con indirizzo, id 1272 senza) → risposte ambigue in chat

- **Prova:** `SELECT id,nome,indirizzo FROM luogo WHERE nome='CAF ACLI La Rosa'` → 21 (Via provinciale per La Rosa) e 1272 (NULL, creato 20:23 senza audit di nascita); `cerca_luogo?q=CAF` → 2 item omonimi; la chat del 17/09 risponde «seconda scheda in memoria» con distanze contraddittorie.
- **Fix:** decisione dati — `UPDATE trasi.luogo SET chiuso_il=now() WHERE id=1272` (o fusione in 21), poi re-ingest.

### BUG-06 · Le conversazioni Home (`/op/conversazioni/…`) **non scrivono** in `chat_interazione_log`

- **Prova:** 2 turni reali alle 20:43/20:44 (conv. 351) → **0** righe nuove nel log (7 righe totali, ultima 16:45); nel container `conversazioni_op.py` non chiama `_log_chat_mensile` (grep negativo), mentre `/op/chat` (proxy single-turn) sì (`chat.py:734`).
- **Effetto:** il tool PA `chat_stats` e l'alert «chat_errori» contano solo il canale single-turno: la contabilità d'uso è sottostimata sistematicamente.
- **Fix:** aggiungere la traccia best-effort in `op_conversazioni_messaggio` (stesso schema di `chat.py`).

### BUG-07 · `v_report` del DB live non espone le colonne di stato attese dallo shim PA (famiglia BUG-02, lato viste)

- **Prova:** `pg_get_viewdef('trasi.v_report')` senza `stato/approvato_da/inviato_pa_ts`; `monitoraggio.py` (deployato) le seleziona → 500 su `/pa/report` e `/v1/m/.../report`.
- **Nota:** è la stessa radice di BUG-02 (031 applicata parzialmente); separata qui perché la correzione tocca **due** superfici (GRANT `pa` + riscrittura vista) e merita due verifiche distinte: tool Onyx e dashboard browser.

## P2 — minori / osservazioni

### BUG-08 · `eventi_oggi` non filtra gli eventi **in corso** che sono iniziati prima di oggi (coerenza con `v_kb_export`)

- **Prova:** 2 eventi con inizio 17/09 17:00/20:00 appaiono ancora in KB Onyx (scaduti da `v_kb_export`, che filtra `COALESCE(fine,inizio)>=now()`, ma mai cancellati lì) — conseguenza diretta di BUG-03; una volta riparato l'export scompare. Registrato per tracciare che il difetto è solo di freschezza KB, non del tool.

### BUG-09 · `cerca_web` restituisce risultati irrilevanti come «successo» (Consolato Bangladesh → «Referendum 2026»)

- **Prova:** `cerca_web?q=Consolato del Bangladesh Brindisi` → 1 item del **Ministero dell'Interno** sul referendum. L'assistente correttamente astiene (G-14 passa), ma il tool restituisce `items` non pertinenti senza segnale di pertinenza: rischio che un modello meno disciplinato lo citi.
- **Fix (proposta):** nota di pertinenza nel tool (score soglia SearXNG) o istruzione nel prompt: «se il titolo non contiene il termine cercato, trattalo come assenza».

### BUG-10 · Statistiche: due canali, due finestre, due numeri (`/v1/u/statistiche` vs `/op/casa/statistiche`)

- **Prova:** `statistiche` (contratto) → mese corrente da `v_report_mensile` (585 orientamento); `op_casa/statistiche` → finestra 30gg da `fn_statistiche_casa` (587). Nessuno dei due è «sbagliato», ma due superfici diverse rispondono numeri diversi alla stessa domanda: rischio confusione in chat (il modello ha solo `statistiche`) e nelle dashboard.
- **Azione:** dichiarare nei prompt quale superficie usare, o uniformare (decisione design, non hotfix).

## Non-bug (verificati e chiusi)

- `no_self_approve`: le 3 proposte `approvata` odierne hanno `proposto_da <> approvato_da` (casa_sanbao→rete, rete→casa_bozzano): policy funzionante.
- `k_anon`: tutti i conteggi esposti (`n_label`) conformi («<5», «—»); nessun numero grezzo sotto soglia nelle viste PA.
- Filtro PII: `messaggio` con nome+telefono → 422, **zero righe** in `turno` (verificato dopo l'invio).
- V5: `persona_casa` in KB solo con `consenso_il` (Maria Prova V11, consenso presente).
- `vicino_a` senza `tipo` → 422 parlante (comportamento atteso, non difetto).
- `formato=pdf` sul biglietto: ignorato, risposta HTML — **intenzionale** (export HTML-only), non un difetto.