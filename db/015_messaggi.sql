-- Trasi — db/015_messaggi.sql
-- Chat interna CdQ ↔ CdQ ↔ PA (US-7.x, Fase 0 §2): canale operativo senza AI
-- («Cosa ci aspettiamo che faccia l'AI: Niente» — la scheda lo dichiara).
--
-- Il messaggio NON è dominio (Fase 0): non passa dal flusso proposte; la retention è
-- policy privacy (scadi_messaggi in db/006, parametro messaggi_retention_days) e ogni
-- messaggio lascia riga di audit 'messaggio' (accountability interna senza AI).
--
-- Modello: da_casa_id NULL = messaggio della PA (ruolo `ti`); a_casa_id NULL = broadcast
-- (PA → tutta la rete; una Casa non può fare broadcast). Nessun campo per dati personali.
--
-- Vincoli applicati: RLS ENABLE+FORCE; USING **e** WITH CHECK; UPDATE limitato a letto_ts
-- dal solo destinatario; DELETE solo di `applicatore` (retention) — nessun altro.
--
-- Idempotente: rieseguibile senza errori.
\set ON_ERROR_STOP on
\set VERBOSITY terse

SET ROLE trasi_owner;
SET search_path = trasi, public, pg_temp;

-- ---------------------------------------------------------------------------
-- 1. Tabella
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trasi.messaggio (
  id          bigserial PRIMARY KEY,
  da_casa_id  integer REFERENCES trasi.casa(id),          -- NULL = dalla PA
  a_casa_id   integer REFERENCES trasi.casa(id),          -- NULL = broadcast della PA
  testo       text NOT NULL CHECK (char_length(testo) BETWEEN 1 AND 2000),
  ts          timestamptz NOT NULL DEFAULT now(),
  letto_ts    timestamptz
  -- Nessun CHECK sulla direzione, e la scelta è deliberata.
  --
  -- La prima versione aveva `CHECK (da_casa_id IS NOT NULL OR a_casa_id IS NOT NULL)` per
  -- escludere «un messaggio senza mittente e senza destinatario». Quel vincolo si contraddiceva con
  -- il modello che il file stesso dichiara: il **broadcast della PA** è `da_casa_id IS NULL` (il
  -- mittente è la PA) *e* `a_casa_id IS NULL` (i destinatari sono tutta la rete) — cioè esattamente
  -- la riga che il CHECK rifiutava. Misurato: come `ti`, `INSERT … (NULL, NULL, …)` →
  -- `violates check constraint "messaggio_direzione_ck"`, con la policy `msg_ins_ti` che invece lo
  -- autorizza. La conseguenza era che la funzione dichiarata in US-7.1 («PA → enti: aggiornamenti,
  -- interruzioni, solleciti») non era usabile, e il test M04 di `t_messaggi.sql` la pretendeva.
  --
  -- Le quattro combinazioni possibili sono quindi tutte legittime, e a distinguerle è la **policy**,
  -- che sa chi sta scrivendo:
  --   (Casa, Casa)  → Casa → Casa            [msg_ins_casa]
  --   (NULL, Casa)  → PA → Casa              [msg_ins_ti]
  --   (NULL, NULL)  → PA → tutta la rete      [msg_ins_ti]
  --   (Casa, NULL)  → vietata: nessuna policy INSERT la ammette, perché il broadcast è della PA
  -- Un CHECK di tabella non può esprimere questa regola — non conosce il ruolo — e riscriverla come
  -- `A OR B OR (NOT A AND NOT B)` sarebbe una **tautologia** (sempre vera), cioè un vincolo che
  -- sembra proteggere e non protegge. Meglio nessun CHECK che un CHECK che mente.
);
COMMENT ON TABLE trasi.messaggio IS
  'Chat interna della rete (US-7.1, senza AI): da_casa_id NULL = dalla PA (ruolo ti); a_casa_id NULL = broadcast PA → rete. UPDATE solo letto_ts del destinatario; DELETE solo per retention (scadi_messaggi).';
COMMENT ON COLUMN trasi.messaggio.testo IS
  'Testo operativo ≤ 2000 caratteri; nessun dato personale (V5).';

CREATE INDEX IF NOT EXISTS messaggio_da_idx      ON trasi.messaggio (da_casa_id, ts);
CREATE INDEX IF NOT EXISTS messaggio_a_idx       ON trasi.messaggio (a_casa_id, ts);
CREATE INDEX IF NOT EXISTS messaggio_broadcast_idx ON trasi.messaggio (ts) WHERE a_casa_id IS NULL;
CREATE INDEX IF NOT EXISTS messaggio_letto_idx   ON trasi.messaggio (letto_ts) WHERE letto_ts IS NOT NULL;

-- ---------------------------------------------------------------------------
-- 1b. Vincolo rimosso da un database già applicato.
--     `CREATE TABLE IF NOT EXISTS` **non** tocca una tabella che esiste: il CHECK
--     `messaggio_direzione_ck` continuerebbe a rifiutare il broadcast della PA su ogni database
--     dove la tabella era già stata creata, e il file sembrerebbe corretto perché la definizione
--     qui sopra non lo contiene più. Questo `DROP … IF EXISTS` è la differenza fra «il sorgente è
--     giusto» e «il database è giusto», ed è la seconda che conta.
-- ---------------------------------------------------------------------------
ALTER TABLE trasi.messaggio DROP CONSTRAINT IF EXISTS messaggio_direzione_ck;

-- ---------------------------------------------------------------------------
-- 2. RLS — ENABLE + FORCE
-- ---------------------------------------------------------------------------
ALTER TABLE trasi.messaggio ENABLE ROW LEVEL SECURITY;
ALTER TABLE trasi.messaggio FORCE  ROW LEVEL SECURITY;

DROP POLICY IF EXISTS owner_all ON trasi.messaggio;
CREATE POLICY owner_all ON trasi.messaggio FOR ALL TO trasi_owner USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS appl_all ON trasi.messaggio;
CREATE POLICY appl_all ON trasi.messaggio FOR ALL TO applicatore USING (true) WITH CHECK (true);

-- Lettura: solo le proprie conversazioni (dirette o broadcast), più rete/ti/automazioni.
-- Nota: questa policy è anche il presidio DB del «PA ↔ Case» — la visibilità è rigorosa.
DROP POLICY IF EXISTS msg_sel ON trasi.messaggio;
CREATE POLICY msg_sel ON trasi.messaggio FOR SELECT
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano,
     rete, ti, automazioni, shim_rw
  USING (da_casa_id = (SELECT trasi.casa_corrente())
      OR a_casa_id = (SELECT trasi.casa_corrente())
      OR a_casa_id IS NULL
      OR current_user IN ('rete','ti','automazioni'));

-- Inserimento Casa → Casa o Casa → PA: mai broadcast (a_casa_id NULL solo dalla PA).
DROP POLICY IF EXISTS msg_ins_casa ON trasi.messaggio;
CREATE POLICY msg_ins_casa ON trasi.messaggio FOR INSERT
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano
  WITH CHECK (da_casa_id = (SELECT trasi.casa_corrente())
              AND a_casa_id IS NOT NULL);

-- Inserimento PA (`ti`): verso una Casa oppure broadcast all rete; firma PA (da_casa_id NULL).
DROP POLICY IF EXISTS msg_ins_ti ON trasi.messaggio;
CREATE POLICY msg_ins_ti ON trasi.messaggio FOR INSERT TO ti
  WITH CHECK (da_casa_id IS NULL);

-- Lettura «letto»: solo il destinatario (Casa o PA) marca letto_ts; il broadcast lo marca
-- ogni Casa per sé. USING+WITH CHECK su entrambi i lati.
DROP POLICY IF EXISTS msg_upd_letto ON trasi.messaggio;
CREATE POLICY msg_upd_letto ON trasi.messaggio FOR UPDATE
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano
  USING (a_casa_id = (SELECT trasi.casa_corrente()) OR a_casa_id IS NULL)
  WITH CHECK (a_casa_id = (SELECT trasi.casa_corrente()) OR a_casa_id IS NULL);
DROP POLICY IF EXISTS msg_upd_letto_ti ON trasi.messaggio;
CREATE POLICY msg_upd_letto_ti ON trasi.messaggio FOR UPDATE TO ti
  USING (da_casa_id IS NOT NULL AND a_casa_id IS NULL)
  WITH CHECK (da_casa_id IS NOT NULL AND a_casa_id IS NULL);

-- Nessuna policy DELETE per i client: la retention è scadi_messaggi() (owner applicatore).

-- ---------------------------------------------------------------------------
-- 3. Colonne aggiornabili: solo letto_ts
-- ---------------------------------------------------------------------------
-- GRANT colonnare: il destinatario aggiorna la sola colonna `letto_ts` (testo e attori
-- non si riscrivono: la chat è un registro, non una lavagna).
REVOKE ALL ON trasi.messaggio FROM PUBLIC;

GRANT SELECT ON trasi.messaggio
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano,
     rete, ti, automazioni, shim_rw, applicatore;
GRANT INSERT (da_casa_id, a_casa_id, testo) ON trasi.messaggio
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano, ti;
GRANT UPDATE (letto_ts) ON trasi.messaggio
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano, ti;
GRANT SELECT, INSERT, UPDATE, DELETE ON trasi.messaggio TO trasi_owner;
GRANT SELECT, INSERT, UPDATE, DELETE ON trasi.messaggio TO applicatore;
GRANT USAGE ON SEQUENCE trasi.messaggio_id_seq
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano, ti, applicatore;

-- ---------------------------------------------------------------------------
-- 4. Verifica di installazione
-- ---------------------------------------------------------------------------
DO $verify$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                  WHERE n.nspname = 'trasi' AND c.relname = 'messaggio'
                    AND c.relrowsecurity AND c.relforcerowsecurity) THEN
    RAISE EXCEPTION '015: trasi.messaggio senza ENABLE+FORCE RLS';
  END IF;
  IF (SELECT count(*) FROM pg_policies
       WHERE schemaname = 'trasi' AND tablename = 'messaggio'
         AND policyname IN ('msg_sel','msg_ins_casa','msg_ins_ti','msg_upd_letto','msg_upd_letto_ti')) <> 5 THEN
    RAISE EXCEPTION '015: attese 5 policy client su messaggio, trovate %',
      (SELECT count(*) FROM pg_policies
        WHERE schemaname = 'trasi' AND tablename = 'messaggio'
          AND policyname IN ('msg_sel','msg_ins_casa','msg_ins_ti','msg_upd_letto','msg_upd_letto_ti'));
  END IF;
  RAISE NOTICE '015_messaggi applicato: chat interna (senza AI), RLS ENABLE+FORCE, UPDATE solo letto_ts del destinatario, broadcast solo da ti, DELETE solo retention';
END
$verify$;

RESET ROLE;
