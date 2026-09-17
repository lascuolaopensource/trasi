-- Trasi — db/023_sessione.sql
-- Sessione (G-07, §5.5): il privilegio che rende possibile il rinnovo scorrevole.
--
-- ===========================================================================
-- 1. La decisione sul TTL — 12 ore, in attesa del DPO (Q-02)
-- ===========================================================================
-- Il piano §5.5 propone `[P] session_ttl_hours` → **720** (30 giorni) con rinnovo scorrevole.
-- Il committente **non ha risposto** alla domanda Q-02: «lo sportello ha un PC condiviso: una
-- sessione di 30 giorni su un computer che nessuno chiude è un accesso aperto». Cambiare il
-- parametro adesso deciderebbe al posto suo una questione di privacy.
--
-- Resta quindi **12 ore** — il valore vero nel database — e il requisito D4 («la sessione non
-- scade durante l'uso») si soddisfa con il **rinnovo scorrevole**: chi usa il sito non scade mai
-- durante l'uso, chi lo lascia aperto scade dopo 12 ore di inattività. È il comportamento più
-- prudente e reversibile **con un `UPDATE`** quando il DPO risponde:
--
--   UPDATE trasi.parametro SET valore='720', modificato_da=current_user, modificato_ts=now()
--    WHERE chiave='session_ttl_hours';          -- ruolo `ti`, nessun deploy
--
-- Perché è una chiave `[P]` e non una costante nel codice. La durata della sessione è una scelta
-- di **governance**, non una scelta tecnica: la decide il DPO, e deve poter cambiare senza
-- ricompilare lo shim né riavviare un container. `session_ttl_hours` è già `[P]` in
-- db/003_parametri.sql e la legge `crea_sessione()` (`db/006_fn_proposte.sql:965`); il rinnovo
-- deve leggere **la stessa chiave**, o le due scadenze divergono — un login da 12 h e un rinnovo
-- da 30 giorni sarebbero due contratti diversi sulla stessa sessione.
--
-- ===========================================================================
-- 2. Il rinnovo scorrevole non era possibile: `permission denied for table sessione`
-- ===========================================================================
-- Il rinnovo `UPDATE trasi.sessione SET scade_ts = now() + TTL` gira nella dipendenza di sessione
-- (`shim/app/auth.py:dipendenza_sessione_corrente`), cioè come **`shim_rw`**: è quel ruolo che
-- valida il token a ogni richiesta, **prima** di `SET LOCAL ROLE <ruolo della Casa>`. Il ruolo
-- Casa non è ancora determinato quando la riga di sessione va rinnovata, quindi il privilegio
-- serve a `shim_rw` e a nessun altro.
--
-- Misurato su questo database, **prima** di questa modifica (transazione di prova, `ROLLBACK`):
--   SET LOCAL ROLE shim_rw;
--   SELECT count(*) FROM trasi.sessione WHERE token = :t;     -- 1 riga (la legge: sess_sel_shim)
--   UPDATE trasi.sessione SET scade_ts = now() + interval '12 hours' WHERE token = :t;
--   → ERROR:  permission denied for table sessione
-- Con `has_table_privilege('shim_rw','trasi.sessione','UPDATE')` = **false** e nessuna policy
-- UPDATE per lui. db/013 lo dichiara esplicitamente: «Nessun `UPDATE`: un token non si modifica,
-- si revoca» — quella riga valeva per il logout, e il rinnovo la contraddice. La contraddizione
-- si risolve qui invece di scoprirla in produzione con un 500 sul primo click dopo 5 minuti.
--
-- Il perimetro resta stretto, ed è la stessa forma del `DELETE` del logout (db/013:184).
--  * **Colonnare**: si concede `UPDATE (scade_ts)` e **non** `UPDATE` di tabella. `token` e
--    `casa_id` non sono aggiornabili: un token non si riscrive e una sessione non si sposta di
--    Casa — sarebbe un modo per dirottare una sessione esistente su un'altra Casa, che è
--    esattamente ciò che la RLS esiste per impedire.
--  * **Policy dedicata** a `shim_rw` con `USING` **e** `WITH CHECK`: il ruolo può spostare la
--    scadenza solo di righe che continua a vedere, e la riga che scrive deve restare visibile
--    (`sess_sel_shim` la copre). Senza `WITH CHECK` la policy sarebbe un permesso a metà.
--  * **Nessun ruolo Casa**: nessuno dei dieci `casa_*` riceve questo privilegio, e la policy non
--    li nomina. Un operatore non allunga la propria sessione dal browser: la allunga lo shim
--    quando la sessione è **valida**, ed è il punto che tiene il presidio anti-abuso intatto
--    (il blocco dopo >4 tentativi in 10 minuti, db/006, non è toccato).
--
-- Cosa questa modifica **non** aggiunge: nessuna funzione, nessuna colonna, nessuna tabella.
-- Il rinnovo resta codice dello shim (`T-SHIM-12`), che qui trova soltanto il privilegio che gli
-- manca. `scade_ts` è già `NOT NULL DEFAULT now() + interval '12 hours'` (db/013:100) e resta il
-- ripiego per gli inserimenti fuori da `crea_sessione()`.
--
-- Idempotente: rieseguibile senza errori.
\set ON_ERROR_STOP on
\set VERBOSITY terse

SET ROLE trasi_owner;
SET search_path = trasi, public, pg_temp;

-- ---------------------------------------------------------------------------
-- 1. Privilegio colonnare: solo `scade_ts`, solo `shim_rw`
-- ---------------------------------------------------------------------------
GRANT UPDATE (scade_ts) ON trasi.sessione TO shim_rw;

-- ---------------------------------------------------------------------------
-- 2. Policy UPDATE dedicata — USING **e** WITH CHECK
--    `sess_sel_shim` (db/013:170) dà a shim_rw la lettura di tutte le sessioni: la condizione qui
--    è la stessa, così il rinnovo non può spostare la scadenza di una riga che non vede.
-- ---------------------------------------------------------------------------
DROP POLICY IF EXISTS sess_upd_shim ON trasi.sessione;
CREATE POLICY sess_upd_shim ON trasi.sessione FOR UPDATE TO shim_rw
  USING (true) WITH CHECK (true);
-- Nota sulla condizione: `USING (true)` **non** è un allargamento rispetto a oggi, ed è
-- deliberato. La RLS di `sessione` non è il presidio di segregazione fra Case (fra chi legge le
-- sessioni non c'è nulla da segregare: sono token opachi, e `sess_sel_shim` è già `USING (true)`):
-- il presidio è **chi** può scrivere, cioè il perimetro dei ruoli e il GRANT colonnare qui sopra.
-- Una condizione per-Casa qui sarebbe una **tautologia mascherata**: l'operatore non presenta una
-- Casa, presenta un token opaco, e il ruolo della Casa non è ancora determinato in quel punto del
-- codice (è la ragione per cui il privilegio sta su shim_rw e non su un ruolo `casa_*`). Meglio
-- una policy che dice il vero — «shim_rw può spostare la scadenza, e solo quella colonna» — che
-- una condizione che sembra proteggere e non protegge.

-- ---------------------------------------------------------------------------
-- 3. Verifica di installazione
-- ---------------------------------------------------------------------------
DO $verify$
BEGIN
  -- Si controlla il privilegio **colonnare**, non quello di tabella: `has_table_privilege(…,
  -- 'UPDATE')` risponde `false` anche con il GRANT colonnare attivo (misurato su questo database),
  -- quindi asserirlo darebbe un falso rosso su una configurazione corretta. Ciò che conta è che la
  -- colonna sia aggiornabile — ed è quello che `has_column_privilege` dice.
  IF NOT has_column_privilege('shim_rw', 'trasi.sessione', 'scade_ts', 'UPDATE') THEN
    RAISE EXCEPTION '023: shim_rw senza UPDATE su sessione.scade_ts — il rinnovo scorrevole resta impossibile';
  END IF;
  -- Il perimetro stretto: ciò che NON deve essere aggiornabile.
  IF has_column_privilege('shim_rw', 'trasi.sessione', 'token', 'UPDATE') THEN
    RAISE EXCEPTION '023: shim_rw può riscrivere sessione.token (un token si revoca, non si modifica)';
  END IF;
  IF has_column_privilege('shim_rw', 'trasi.sessione', 'casa_id', 'UPDATE') THEN
    RAISE EXCEPTION '023: shim_rw può spostare una sessione di Casa (dirottamento)';
  END IF;
  -- Nessun ruolo Casa: la sessione si allunga dallo shim, non dal browser. Il controllo è
  -- colonnare, perché è sul GRANT colonnare che il divieto deve reggere.
  IF EXISTS (SELECT 1 FROM unnest(ARRAY['casa_santaspazio','casa_molo12','casa_erranti','casa_buscicchio',
                                         'casa_sanbao','casa_minimus','casa_pop','casa_bozzano',
                                         'casa_dream','casa_tuturano']) r
              WHERE has_column_privilege(r, 'trasi.sessione', 'scade_ts', 'UPDATE')) THEN
    RAISE EXCEPTION '023: un ruolo Casa può spostare la scadenza di una sessione';
  END IF;
  -- La policy esiste ed è completa (USING + WITH CHECK).
  IF NOT EXISTS (SELECT 1 FROM pg_policies
                  WHERE schemaname = 'trasi' AND tablename = 'sessione'
                    AND policyname = 'sess_upd_shim' AND cmd = 'UPDATE'
                    AND qual IS NOT NULL AND with_check IS NOT NULL) THEN
    RAISE EXCEPTION '023: policy sess_upd_shim mancante o senza USING/WITH CHECK';
  END IF;
  -- Il TTL resta 12: la decisione su Q-02 è del committente, non di questo file.
  IF trasi.p_int('session_ttl_hours') <> 12 THEN
    RAISE EXCEPTION '023: session_ttl_hours = %, atteso 12 (Q-02 aperta: il valore si cambia con un UPDATE, non qui)',
      trasi.p_int('session_ttl_hours');
  END IF;
  RAISE NOTICE '023_sessione applicato: shim_rw UPDATE colonnare (solo scade_ts) + policy sess_upd_shim USING/WITH CHECK; TTL 12 h invariato (Q-02 aperta), rinnovo scorrevole ora possibile';
END
$verify$;

RESET ROLE;
