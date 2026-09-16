-- Trasi — db/002_rls.sql
-- RLS e GRANT. La RLS è l'autorità sui permessi, non l'interfaccia (architettura §1 principio 3, §11).
--
-- Regole applicate:
--   * ENABLE + FORCE ROW LEVEL SECURITY su tutte le tabelle multi-Casa (FORCE = valgono anche per l'owner);
--   * ogni policy ha USING **e** WITH CHECK (mai solo USING);
--   * `casa_corrente()` usa current_user → ruolo_casa, mai una GUC (NocoDB si connette col ruolo diretto);
--   * nessuna scrittura di dominio concessa a shim_rw / automazioni / casa_* tranne l'eccezione iCal su `evento`
--     (che vive in db/005_rls_proposta.sql, insieme ai GRANT di `applicatore` e alle policy di `proposta`);
--   * `audit` NON ha RLS: il controllo è per GRANT (architettura §7.1). INSERT sarà solo di `applicatore` (db/005).
--
-- Scostamenti dalla matrice, dichiarati nel report B1:
--   1. per valutare una policy che chiama casa_corrente() il chiamante deve poter leggere `ruolo_casa`:
--      GRANT SELECT (ruolo, casa_id) ai ruoli che valutano policy (altrimenti la query muore con
--      «permission denied for table ruolo_casa», verificato in B1).
--   2. le viste di db/004 sono `security_invoker=false` con owner `trasi_owner`: le tabelle sottostanti
--      ricevono una policy permissiva `TO trasi_owner`, altrimenti con FORCE RLS nemmeno l'owner legge.
--   3. `ti` riceve ALL sul dominio come da matrice; il rafforzamento V4 che glielo toglie è in db/005
--      (worker trasi-proposte, che gira dopo).
\set ON_ERROR_STOP on
\set VERBOSITY terse

SET ROLE trasi_owner;
SET search_path = trasi, public, pg_temp;

-- I ruoli sono quelli di 000_roles.sql; l'elenco è ripetuto per tipo di permesso, non per comodità:
-- leggerlo è l'unico modo di sapere chi può cosa senza aprire pg_policies.
DO $$
DECLARE
  casas   text := 'casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao, casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano';
  readers text := 'casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao, casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano, rete, ti, automazioni';
  sel_all text := 'casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao, casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano, rete, ti, metabase_ro, automazioni, shim_rw, applicatore, trasi_owner';
BEGIN
  -- =========================================================================
  -- 1. GRANT sulle tabelle (senza GRANT la policy non serve a nulla)
  -- =========================================================================
  EXECUTE format('GRANT SELECT ON trasi.casa, trasi.fonte, trasi.luogo, trasi.scheda_servizio, trasi.evento, '
                 'trasi.opportunita, trasi.parametro, trasi.richiesta, trasi.proposta, trasi.fonte_run TO %s', sel_all);

  -- metabase_ro: per matrice NON vede `richiesta` (dato di sportello) né `audit`; vede `ruolo_casa`/`identita_onyx`
  -- solo nei limiti della matrice (nessuna delle due).
  REVOKE SELECT ON trasi.richiesta FROM metabase_ro;
  REVOKE SELECT ON trasi.proposta, trasi.fonte_run FROM shim_rw;

  -- audit: append-only, lettura a tutti (il controllo è per GRANT, §7.1). Nessun INSERT qui: sarà di `applicatore`.
  EXECUTE format('GRANT SELECT ON trasi.audit TO %s', sel_all);

  -- ruolo_casa: `ti` amministra, gli altri leggono solo le colonne che servono a casa_corrente()
  -- (il SELECT per colonna è ciò che rende valutabili le policy di casa_corrente()).
  EXECUTE format('GRANT SELECT (ruolo, casa_id, descrizione) ON trasi.ruolo_casa TO %s', casas);
  GRANT SELECT (ruolo, casa_id, descrizione) ON trasi.ruolo_casa TO rete, shim_rw, applicatore, automazioni, metabase_ro;

  -- identita_onyx: riservata a `ti` (matrice). `shim_rw` risolve l'email → ruolo: SELECT.
  GRANT SELECT ON trasi.identita_onyx TO shim_rw;

  -- scritture ammesse ai client (tutte coperte da WITH CHECK nelle policy sotto)
  EXECUTE format('GRANT INSERT, UPDATE, DELETE ON trasi.scheda_servizio, trasi.evento, trasi.opportunita, trasi.richiesta TO %s', casas);
  EXECUTE format('GRANT UPDATE (orari, orari_eccezioni, orari_provvisori, email_digest) ON trasi.casa TO %s', casas);
  -- `ti`: ALL sul dominio come da matrice (casa, scheda_servizio, evento, opportunita, richiesta, luogo).
  -- Il rafforzamento V4 che glielo toglie è in db/005_rls_proposta.sql (worker trasi-proposte, gira dopo):
  -- qui la matrice è implementata alla lettera, così è verificabile una cella per volta.
  GRANT SELECT, INSERT, UPDATE, DELETE ON trasi.casa, trasi.luogo, trasi.scheda_servizio, trasi.evento,
                                          trasi.opportunita, trasi.richiesta TO ti;
  -- `ti`: amministra allow-list fonti e identità (matrice: ALL su fonte/ruolo_casa/identita_onyx;
  -- UPDATE su parametro). INSERT/DELETE su parametro sono [ASSUNZIONE]: §11 assegna i parametri a
  -- TI/PM e «aggiungerne uno = una riga in parametro», quindi la matrice va letta come gestione piena.
  GRANT INSERT, UPDATE, DELETE ON trasi.fonte, trasi.ruolo_casa, trasi.identita_onyx TO ti;
  GRANT INSERT, DELETE ON trasi.parametro TO ti;
  GRANT UPDATE (valore, modificato_da, modificato_ts) ON trasi.parametro TO ti;

  -- sequenze: senza USAGE l'INSERT serial/bigserial fallisce con 42501
  EXECUTE format('GRANT USAGE ON ALL SEQUENCES IN SCHEMA trasi TO %s', casas || ', rete, ti, automazioni, shim_rw, applicatore');

  -- viste e oggetti futuri creati da trasi_owner (db/004 crea le viste dopo questo file)
  EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA trasi GRANT SELECT ON TABLES TO %s', sel_all);

  -- =========================================================================
  -- 2. ENABLE + FORCE + policy
  -- =========================================================================
  EXECUTE $sql$
    ALTER TABLE trasi.casa             ENABLE ROW LEVEL SECURITY;
    ALTER TABLE trasi.casa             FORCE  ROW LEVEL SECURITY;
    ALTER TABLE trasi.fonte            ENABLE ROW LEVEL SECURITY;
    ALTER TABLE trasi.fonte            FORCE  ROW LEVEL SECURITY;
    ALTER TABLE trasi.fonte_run        ENABLE ROW LEVEL SECURITY;
    ALTER TABLE trasi.fonte_run        FORCE  ROW LEVEL SECURITY;
    ALTER TABLE trasi.luogo            ENABLE ROW LEVEL SECURITY;
    ALTER TABLE trasi.luogo            FORCE  ROW LEVEL SECURITY;
    ALTER TABLE trasi.scheda_servizio  ENABLE ROW LEVEL SECURITY;
    ALTER TABLE trasi.scheda_servizio  FORCE  ROW LEVEL SECURITY;
    ALTER TABLE trasi.evento           ENABLE ROW LEVEL SECURITY;
    ALTER TABLE trasi.evento           FORCE  ROW LEVEL SECURITY;
    ALTER TABLE trasi.opportunita      ENABLE ROW LEVEL SECURITY;
    ALTER TABLE trasi.opportunita      FORCE  ROW LEVEL SECURITY;
    ALTER TABLE trasi.richiesta        ENABLE ROW LEVEL SECURITY;
    ALTER TABLE trasi.richiesta        FORCE  ROW LEVEL SECURITY;
    ALTER TABLE trasi.parametro        ENABLE ROW LEVEL SECURITY;
    ALTER TABLE trasi.parametro        FORCE  ROW LEVEL SECURITY;
    ALTER TABLE trasi.ruolo_casa       ENABLE ROW LEVEL SECURITY;
    ALTER TABLE trasi.ruolo_casa       FORCE  ROW LEVEL SECURITY;
    ALTER TABLE trasi.identita_onyx    ENABLE ROW LEVEL SECURITY;
    ALTER TABLE trasi.identita_onyx    FORCE  ROW LEVEL SECURITY;
    ALTER TABLE trasi.proposta         ENABLE ROW LEVEL SECURITY;
    ALTER TABLE trasi.proposta         FORCE  ROW LEVEL SECURITY;
  $sql$;

  -- --- owner: senza queste policy, FORCE RLS nega la lettura anche a trasi_owner,
  --     e le viste security_invoker=false di db/004 (che girano come owner) non vedrebbero nulla.
  EXECUTE $sql$
    DROP POLICY IF EXISTS owner_all ON trasi.casa;
    CREATE POLICY owner_all ON trasi.casa FOR ALL TO trasi_owner USING (true) WITH CHECK (true);
    DROP POLICY IF EXISTS owner_all ON trasi.fonte;
    CREATE POLICY owner_all ON trasi.fonte FOR ALL TO trasi_owner USING (true) WITH CHECK (true);
    DROP POLICY IF EXISTS owner_all ON trasi.fonte_run;
    CREATE POLICY owner_all ON trasi.fonte_run FOR ALL TO trasi_owner USING (true) WITH CHECK (true);
    DROP POLICY IF EXISTS owner_all ON trasi.luogo;
    CREATE POLICY owner_all ON trasi.luogo FOR ALL TO trasi_owner USING (true) WITH CHECK (true);
    DROP POLICY IF EXISTS owner_all ON trasi.scheda_servizio;
    CREATE POLICY owner_all ON trasi.scheda_servizio FOR ALL TO trasi_owner USING (true) WITH CHECK (true);
    DROP POLICY IF EXISTS owner_all ON trasi.evento;
    CREATE POLICY owner_all ON trasi.evento FOR ALL TO trasi_owner USING (true) WITH CHECK (true);
    DROP POLICY IF EXISTS owner_all ON trasi.opportunita;
    CREATE POLICY owner_all ON trasi.opportunita FOR ALL TO trasi_owner USING (true) WITH CHECK (true);
    DROP POLICY IF EXISTS owner_all ON trasi.richiesta;
    CREATE POLICY owner_all ON trasi.richiesta FOR ALL TO trasi_owner USING (true) WITH CHECK (true);
    DROP POLICY IF EXISTS owner_all ON trasi.parametro;
    CREATE POLICY owner_all ON trasi.parametro FOR ALL TO trasi_owner USING (true) WITH CHECK (true);
    DROP POLICY IF EXISTS owner_all ON trasi.ruolo_casa;
    CREATE POLICY owner_all ON trasi.ruolo_casa FOR ALL TO trasi_owner USING (true) WITH CHECK (true);
    DROP POLICY IF EXISTS owner_all ON trasi.identita_onyx;
    CREATE POLICY owner_all ON trasi.identita_onyx FOR ALL TO trasi_owner USING (true) WITH CHECK (true);
    DROP POLICY IF EXISTS owner_all ON trasi.proposta;
    CREATE POLICY owner_all ON trasi.proposta FOR ALL TO trasi_owner USING (true) WITH CHECK (true);
  $sql$;

  -- --- casa: tutti leggono; la Casa aggiorna solo i propri orari/contatti; `ti` amministra.
  EXECUTE $sql$
    DROP POLICY IF EXISTS casa_sel ON trasi.casa;
    CREATE POLICY casa_sel ON trasi.casa FOR SELECT TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio,
      casa_sanbao, casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano, rete, automazioni, metabase_ro,
      shim_rw USING (true);
    DROP POLICY IF EXISTS casa_upd_casa ON trasi.casa;
    CREATE POLICY casa_upd_casa ON trasi.casa FOR UPDATE
      TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao, casa_minimus, casa_pop,
         casa_bozzano, casa_dream, casa_tuturano
      USING (id = (SELECT trasi.casa_corrente()))
      WITH CHECK (id = (SELECT trasi.casa_corrente()));
    DROP POLICY IF EXISTS casa_all_ti ON trasi.casa;
    CREATE POLICY casa_all_ti ON trasi.casa FOR ALL TO ti USING (true) WITH CHECK (true);
  $sql$;

  -- --- luogo: sola lettura per tutti (V4: i luoghi si cambiano via proposta); `ti` amministra.
  EXECUTE $sql$
    DROP POLICY IF EXISTS luogo_sel ON trasi.luogo;
    CREATE POLICY luogo_sel ON trasi.luogo FOR SELECT TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio,
      casa_sanbao, casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano, rete, automazioni, metabase_ro,
      shim_rw USING (true);
    DROP POLICY IF EXISTS luogo_all_ti ON trasi.luogo;
    CREATE POLICY luogo_all_ti ON trasi.luogo FOR ALL TO ti USING (true) WITH CHECK (true);
  $sql$;

  -- --- scheda_servizio / evento / opportunita: lettura a tutta la rete, scrittura alla propria Casa.
  EXECUTE $sql$
    DROP POLICY IF EXISTS scheda_sel ON trasi.scheda_servizio;
    CREATE POLICY scheda_sel ON trasi.scheda_servizio FOR SELECT TO casa_santaspazio, casa_molo12, casa_erranti,
      casa_buscicchio, casa_sanbao, casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano, rete, automazioni
      USING (true);
    DROP POLICY IF EXISTS scheda_ins_casa ON trasi.scheda_servizio;
    CREATE POLICY scheda_ins_casa ON trasi.scheda_servizio FOR INSERT
      TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao, casa_minimus, casa_pop,
         casa_bozzano, casa_dream, casa_tuturano
      WITH CHECK (casa_id = (SELECT trasi.casa_corrente()));
    DROP POLICY IF EXISTS scheda_upd_casa ON trasi.scheda_servizio;
    CREATE POLICY scheda_upd_casa ON trasi.scheda_servizio FOR UPDATE
      TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao, casa_minimus, casa_pop,
         casa_bozzano, casa_dream, casa_tuturano
      USING (casa_id = (SELECT trasi.casa_corrente()))
      WITH CHECK (casa_id = (SELECT trasi.casa_corrente()));
    DROP POLICY IF EXISTS scheda_del_casa ON trasi.scheda_servizio;
    CREATE POLICY scheda_del_casa ON trasi.scheda_servizio FOR DELETE
      TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao, casa_minimus, casa_pop,
         casa_bozzano, casa_dream, casa_tuturano
      USING (casa_id = (SELECT trasi.casa_corrente()));
    DROP POLICY IF EXISTS scheda_all_ti ON trasi.scheda_servizio;
    CREATE POLICY scheda_all_ti ON trasi.scheda_servizio FOR ALL TO ti USING (true) WITH CHECK (true);

    DROP POLICY IF EXISTS evento_sel ON trasi.evento;
    CREATE POLICY evento_sel ON trasi.evento FOR SELECT TO casa_santaspazio, casa_molo12, casa_erranti,
      casa_buscicchio, casa_sanbao, casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano, rete, automazioni
      USING (true);
    DROP POLICY IF EXISTS evento_ins_casa ON trasi.evento;
    CREATE POLICY evento_ins_casa ON trasi.evento FOR INSERT
      TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao, casa_minimus, casa_pop,
         casa_bozzano, casa_dream, casa_tuturano
      WITH CHECK (casa_id = (SELECT trasi.casa_corrente()));
    DROP POLICY IF EXISTS evento_upd_casa ON trasi.evento;
    CREATE POLICY evento_upd_casa ON trasi.evento FOR UPDATE
      TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao, casa_minimus, casa_pop,
         casa_bozzano, casa_dream, casa_tuturano
      USING (casa_id = (SELECT trasi.casa_corrente()))
      WITH CHECK (casa_id = (SELECT trasi.casa_corrente()));
    DROP POLICY IF EXISTS evento_del_casa ON trasi.evento;
    CREATE POLICY evento_del_casa ON trasi.evento FOR DELETE
      TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao, casa_minimus, casa_pop,
         casa_bozzano, casa_dream, casa_tuturano
      USING (casa_id = (SELECT trasi.casa_corrente()));
    DROP POLICY IF EXISTS evento_all_ti ON trasi.evento;
    CREATE POLICY evento_all_ti ON trasi.evento FOR ALL TO ti USING (true) WITH CHECK (true);

    DROP POLICY IF EXISTS opp_sel ON trasi.opportunita;
    CREATE POLICY opp_sel ON trasi.opportunita FOR SELECT TO casa_santaspazio, casa_molo12, casa_erranti,
      casa_buscicchio, casa_sanbao, casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano, rete, automazioni
      USING (true);
    DROP POLICY IF EXISTS opp_ins_casa ON trasi.opportunita;
    CREATE POLICY opp_ins_casa ON trasi.opportunita FOR INSERT
      TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao, casa_minimus, casa_pop,
         casa_bozzano, casa_dream, casa_tuturano
      WITH CHECK (casa_id = (SELECT trasi.casa_corrente()));
    DROP POLICY IF EXISTS opp_upd_casa ON trasi.opportunita;
    CREATE POLICY opp_upd_casa ON trasi.opportunita FOR UPDATE
      TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao, casa_minimus, casa_pop,
         casa_bozzano, casa_dream, casa_tuturano
      USING (casa_id = (SELECT trasi.casa_corrente()))
      WITH CHECK (casa_id = (SELECT trasi.casa_corrente()));
    DROP POLICY IF EXISTS opp_del_casa ON trasi.opportunita;
    CREATE POLICY opp_del_casa ON trasi.opportunita FOR DELETE
      TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao, casa_minimus, casa_pop,
         casa_bozzano, casa_dream, casa_tuturano
      USING (casa_id = (SELECT trasi.casa_corrente()));
    DROP POLICY IF EXISTS opp_all_ti ON trasi.opportunita;
    CREATE POLICY opp_all_ti ON trasi.opportunita FOR ALL TO ti USING (true) WITH CHECK (true);
  $sql$;

  -- --- richiesta: `metabase_ro` NON la vede (matrice; il dato di sportello esce solo aggregato dalle viste).
  EXECUTE $sql$
    DROP POLICY IF EXISTS rich_sel ON trasi.richiesta;
    CREATE POLICY rich_sel ON trasi.richiesta FOR SELECT TO casa_santaspazio, casa_molo12, casa_erranti,
      casa_buscicchio, casa_sanbao, casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano, rete, automazioni
      USING (true);
    DROP POLICY IF EXISTS rich_ins_casa ON trasi.richiesta;
    CREATE POLICY rich_ins_casa ON trasi.richiesta FOR INSERT
      TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao, casa_minimus, casa_pop,
         casa_bozzano, casa_dream, casa_tuturano
      WITH CHECK (casa_id = (SELECT trasi.casa_corrente()));
    DROP POLICY IF EXISTS rich_upd_casa ON trasi.richiesta;
    CREATE POLICY rich_upd_casa ON trasi.richiesta FOR UPDATE
      TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao, casa_minimus, casa_pop,
         casa_bozzano, casa_dream, casa_tuturano
      USING (casa_id = (SELECT trasi.casa_corrente()))
      WITH CHECK (casa_id = (SELECT trasi.casa_corrente()));
    DROP POLICY IF EXISTS rich_del_casa ON trasi.richiesta;
    CREATE POLICY rich_del_casa ON trasi.richiesta FOR DELETE
      TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao, casa_minimus, casa_pop,
         casa_bozzano, casa_dream, casa_tuturano
      USING (casa_id = (SELECT trasi.casa_corrente()));
    DROP POLICY IF EXISTS rich_all_ti ON trasi.richiesta;
    CREATE POLICY rich_all_ti ON trasi.richiesta FOR ALL TO ti USING (true) WITH CHECK (true);
  $sql$;

  -- --- fonte (allow-list), fonte_run: lettura a tutti, scrittura solo a `ti` (§11: TI approva l'allow-list).
  EXECUTE $sql$
    DROP POLICY IF EXISTS fonte_sel ON trasi.fonte;
    CREATE POLICY fonte_sel ON trasi.fonte FOR SELECT TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio,
      casa_sanbao, casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano, rete, automazioni, metabase_ro,
      shim_rw, applicatore USING (true);
    DROP POLICY IF EXISTS fonte_all_ti ON trasi.fonte;
    CREATE POLICY fonte_all_ti ON trasi.fonte FOR ALL TO ti USING (true) WITH CHECK (true);

    DROP POLICY IF EXISTS fonte_run_sel ON trasi.fonte_run;
    CREATE POLICY fonte_run_sel ON trasi.fonte_run FOR SELECT TO casa_santaspazio, casa_molo12, casa_erranti,
      casa_buscicchio, casa_sanbao, casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano, rete, automazioni
      USING (true);
    DROP POLICY IF EXISTS fonte_run_all_ti ON trasi.fonte_run;
    CREATE POLICY fonte_run_all_ti ON trasi.fonte_run FOR ALL TO ti USING (true) WITH CHECK (true);
  $sql$;

  -- --- parametro [P]: tutti leggono, solo `ti` modifica (§11).
  EXECUTE $sql$
    DROP POLICY IF EXISTS param_sel ON trasi.parametro;
    CREATE POLICY param_sel ON trasi.parametro FOR SELECT TO casa_santaspazio, casa_molo12, casa_erranti,
      casa_buscicchio, casa_sanbao, casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano, rete, automazioni,
      metabase_ro, shim_rw, applicatore USING (true);
    DROP POLICY IF EXISTS param_all_ti ON trasi.parametro;
    CREATE POLICY param_all_ti ON trasi.parametro FOR ALL TO ti USING (true) WITH CHECK (true);
  $sql$;

  -- --- ruolo_casa / identita_onyx: riservate a `ti` (matrice); `shim_rw` risolve l'identità.
  -- La policy `rc_sel_self` è un requisito funzionale, non una concessione: `casa_corrente()` è
  -- SECURITY INVOKER (deve leggere `current_user`, non l'owner) e senza una policy che renda leggibile
  -- la PROPRIA riga la funzione fallisce con «permission denied for table ruolo_casa» e ogni policy che
  -- la chiama nega tutto. Ogni ruolo vede al massimo una riga: la propria.
  EXECUTE $sql$
    DROP POLICY IF EXISTS rc_all_ti ON trasi.ruolo_casa;
    CREATE POLICY rc_all_ti ON trasi.ruolo_casa FOR ALL TO ti USING (true) WITH CHECK (true);
    DROP POLICY IF EXISTS rc_sel_self ON trasi.ruolo_casa;
    CREATE POLICY rc_sel_self ON trasi.ruolo_casa FOR SELECT TO casa_santaspazio, casa_molo12, casa_erranti,
      casa_buscicchio, casa_sanbao, casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano, rete,
      shim_rw, automazioni, applicatore
      USING (ruolo = current_user::text);
    DROP POLICY IF EXISTS io_all_ti ON trasi.identita_onyx;
    CREATE POLICY io_all_ti ON trasi.identita_onyx FOR ALL TO ti USING (true) WITH CHECK (true);
    DROP POLICY IF EXISTS io_sel_shim ON trasi.identita_onyx;
    CREATE POLICY io_sel_shim ON trasi.identita_onyx FOR SELECT TO shim_rw USING (true);
  $sql$;

  -- --- proposta: ENABLE+FORCE qui; le policy di scrittura (ins_client/upd_*) sono di db/005, che sostituisce
  --     anche quelle di §7.1. Qui solo la lettura, e il GRANT SELECT è già sopra.
  EXECUTE $sql$
    DROP POLICY IF EXISTS prova_sel ON trasi.proposta;
    CREATE POLICY prova_sel ON trasi.proposta FOR SELECT TO casa_santaspazio, casa_molo12, casa_erranti,
      casa_buscicchio, casa_sanbao, casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano, rete, ti,
      automazioni, shim_rw, applicatore USING (true);
    -- §7.1 verbatim (db/005 le sostituisce): un client non può inserire una proposta già approvata.
    DROP POLICY IF EXISTS ins_any ON trasi.proposta;
    CREATE POLICY ins_any ON trasi.proposta FOR INSERT TO shim_rw, automazioni, rete
      WITH CHECK (stato = 'proposta' AND approvato_ts IS NULL AND approvato_da IS NULL);
    DROP POLICY IF EXISTS upd_own ON trasi.proposta;
    CREATE POLICY upd_own ON trasi.proposta FOR UPDATE TO shim_rw, automazioni, rete
      USING ((approvatore_ruolo = 'gestore' AND casa_id = (SELECT trasi.casa_corrente()))
             OR (approvatore_ruolo IN ('at','ti') AND current_user IN ('rete','ti')))
      WITH CHECK ((approvatore_ruolo = 'gestore' AND casa_id = (SELECT trasi.casa_corrente()))
             OR (approvatore_ruolo IN ('at','ti') AND current_user IN ('rete','ti')));
  $sql$;
END $$;

RESET ROLE;
