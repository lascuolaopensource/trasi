# TASK SPEC — B1 Proposte: V4 enforcement (`trasi-proposte`)

## Target

Rendi **impossibile a livello di database** scrivere la memoria applicativa fuori dal flusso `proposta` → approvazione → `applica_proposte` + `audit`.

**File di tua proprietà** (non crearne altri con questi scopi):
`db/005_rls_proposta.sql` · `db/006_fn_proposte.sql` · `db/tests/test_zero_scritture.sql`

**NON toccare** (altro worker, `trasi-dati`): `db/000_roles.sql`, `db/001_schema.sql`, `db/002_rls.sql`, `db/003_parametri.sql`, `db/004_views.sql`, seed `010–012`, `db/tests/run.sh`.

Esecuzione contro il Postgres già attivo:
```
docker compose -f deployment/docker-compose.yml exec -T db_trasi psql -U postgres -d trasi_db …
```

## Dipendenza (contratto congelato)

`trasi-dati` sta creando in parallelo, **con questi nomi esatti**:
- ruoli: `applicatore` (NOLOGIN), `automazioni`, `shim_rw` (NOINHERIT), 10 `casa_<slug>`, `rete`, `ti`
- in `db/001_schema.sql`: tabella `proposta` (con `origine, tipo, entita, entita_id, casa_id, fonte_id, payload, diff, motivazione, stato, approvatore_ruolo, proposto_da, proposto_ts, approvato_da, approvato_ts, scade_il`), tipo enum `stato_prop_t`, tabella `audit`, funzione `approvatore_default(tipo, casa_id)`, `casa_corrente()`, trigger `proposta_00_default_tg`
- in `db/002_rls.sql`: RLS di base e GRANT per tabella/colonna

**Se un nome non combacia, fermati e segnalalo via `hub`** — non rinominare le cose per conto tuo.

## Change

### `db/005_rls_proposta.sql`

1. **Chiudi il buco del DDL dell'architettura.** L'architettura ha `CREATE POLICY ins_any … WITH CHECK (true)`: permetterebbe di inserire una proposta **già `stato='approvata'`** (auto-approvazione = violazione di V4). Sostituisci con:
   - `ins_client WITH CHECK (stato='proposta' AND approvato_ts IS NULL AND approvato_da IS NULL)`
   - policy **`no_self_approve`**: chi ha creato la proposta non può approvarla (`proposto_da <> current_user` sull'UPDATE)
2. **GRANT colonnari**: `approvatore_ruolo`, `stato`, `approvato_da/ts` **non** grantati in INSERT ai client (li calcola il trigger). Il client inserisce solo `(origine, tipo, entita, entita_id, casa_id, fonte_id, payload, diff, motivazione, proposto_da, scade_il)`.
3. **REVOKE scritture di dominio** da `shim_rw` e `automazioni` su `luogo, scheda_servizio, evento, opportunita, casa` — **tranne** l'eccezione iCal: `automazioni` può `INSERT/UPDATE` su `evento` solo con `WITH CHECK` sulla fonte iCal.
4. **GRANT dominio ad `applicatore`**: `INSERT/UPDATE` su `luogo, scheda_servizio, evento, opportunita`; `UPDATE` solo `(orari, orari_eccezioni, orari_provvisori)` su `casa`.
5. `audit`: **append-only** — `INSERT` solo ad `applicatore`, `SELECT` agli altri, **nessun** `UPDATE`/`DELETE` a nessuno.
6. `nota_decisione text CHECK (≤80)`, `CHECK (diff IS NOT NULL)`.

### `db/006_fn_proposte.sql`

1. **Macchina a stati** (trigger `proposta_01_transition_tg`): ammesse solo `proposta→approvata|rifiutata|scaduta`, `approvata→applicata|rifiutata`. Ogni altra → eccezione `P0001`. Approvare dopo `scade_il` → eccezione (`P0001`).
2. **`diff` automatico** (trigger `proposta_03_diff_tg`): se assente, genera `{"prima": …, "dopo": payload}` leggendo la riga corrente dell'entità (whitelist tabelle). Più `diff_leggibile(diff) → text`.
3. **Audit automatico** (trigger `proposta_02_audit_tg`) su ogni transizione ≠ `applicata`.
4. **`applica_proposte_approvate(p_limit int)`** — `SECURITY DEFINER` owner `applicatore`, `EXECUTE` solo ad `automazioni`/`ti`. 9 rami `tipo→tabella` (`nuovo_luogo, modifica_luogo, chiudi_luogo, modifica_scheda, nuova_scheda, modifica_evento, nuova_opportunita, promuovi_esterno, modifica_orari_casa`). Requisiti:
   - **idempotente**: 2ª esecuzione = 0 righe
   - **savepoint per proposta**: un errore non abbatte il batch, `esito='errore: …'` in output e `audit.azione='errore_applicazione'`, stato resta `approvata`
   - `FOR UPDATE SKIP LOCKED`
   - scrive `audit` con `prima`/`dopo` **dell'entità** (non della proposta)
   - promozione da esterno → `affidabilita=2`
   - `chiudi_luogo` è **soft-close** (`chiuso_il`), mai `DELETE`
5. **`scadi_proposte()`** — marca `scaduta` quelle con `scade_il < current_date`, con audit.
6. **`v_da_approvare`** — vista della coda, filtrata per `casa_corrente()`/`rete`/`ti`, con `diff_leggibile(diff)` e **senza** `proposto_da`.

### `db/tests/test_zero_scritture.sql`

Per **ogni via di scrittura** dimostra che non può scrivere il dominio. Convenzione: `PASS` = NOTICE, `FAIL` = EXCEPTION (interrompe il run).
- `shim_rw`: INSERT `luogo`, UPDATE `scheda_servizio`, DELETE `evento`, UPDATE `casa`, INSERT `opportunita` → tutti `42501`
- ruolo Casa: UPDATE su `scheda_servizio` di **altra** Casa → **0 righe** (RLS); INSERT `luogo`, UPDATE `casa` → `42501`
- `automazioni`: INSERT `luogo`/`opportunita`, UPDATE `scheda`/`casa` → `42501`; **INSERT `evento` da fonte iCal → 1 riga (eccezione attesa, positiva)**
- `metabase_ro`: INSERT `luogo` → `42501`
- **auto-approvazione**: `UPDATE proposta SET stato='approvata'` sulla **propria** proposta → **0 righe**; su proposta di altra Casa → 0 righe; su propria Casa di altro tipo → coerente con `approvatore_ruolo`
- **idempotenza**: `applica_proposte_approvate` due volte → 2ª = 0 righe

## Constraints

- **V4** è l'invariante: se trovi un'altra via che scrive il dominio, **chiudila** e aggiungila al test.
- **V5**: `motivazione` ≤ 80; audit senza dati personali.
- Non modificare i file di `trasi-dati`; se serve una modifica al suo schema, chiedila via `hub`.
- Il tuo codice deve essere **idempotente** (rieseguibile senza errori).

## Ownership

`db/005_*`, `db/006_*`, `db/tests/test_zero_scritture.sql`.

## Observable acceptance (prove reali)

1. `psql -f db/tests/test_zero_scritture.sql` → NOTICE `PASS` su tutte le sezioni, nessun `FAIL`.
2. **Mutazione**: disabilita temporaneamente una policy (o usa un ruolo senza RLS) → il test **deve diventare rosso**. Se resta verde, il test non vale: dimostralo.
3. `applica_proposte_approvate` su 2 proposte approvate → 2 righe `esito='ok'`, 2 righe `audit` con `prima`/`dopo`; 2ª run → 0 righe.
4. Proposta con `scade_il` passato → `scadi_proposte()` la marca `scaduta` con audit; e approvarla → `P0001`.
5. Auto-approvazione: `UPDATE` sulla propria proposta → **0 righe**.

Riporta comandi e output reali, incluse le eventuali parti rosse.

## Nota
La skill `supabase-postgres-best-practices` è attiva: usala per RLS (`USING` **e** `WITH CHECK`, `FORCE`, nessun bypass). Riferimenti: `docs/trasi-architecture-v1.2.md` §7.1 (DDL), §8 F8/F9 (flussi), §9.1 (`proponi_modifica`/`approva_proposta`), §11 (governance). In conflitto **vince l'architettura**, tranne dove il piano ha già deciso un rafforzamento di V4 (caso `ins_any`) — quello prevale ed è documentato.
