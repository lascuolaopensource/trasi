-- ============================================================================
-- Trasi — B1 · 005_rls_proposta.sql
-- Worker proprietario: trasi-proposte.  Ordine: dopo 000–004, prima di 010–012.
--
-- Scopo (V4): rendere IMPOSSIBILE, a livello di database, scrivere la memoria
-- applicativa (luogo, scheda_servizio, evento, opportunita, casa) fuori dal
-- flusso proposta -> approvazione umana -> applica_proposte + audit.
--
-- Questo file e' idempotente: rieseguibile senza errori.
--
-- Rafforzamenti decisi dal piano rispetto al DDL §7.1 dell'architettura
-- (plan.md §Conflitti 2, non negoziabile):
--   * `ins_any WITH CHECK (true)` -> `ins_client WITH CHECK (stato='proposta'
--     AND approvato_ts IS NULL AND approvato_da IS NULL)`: il DDL letterale
--     permetterebbe a un client di inserire una proposta GIA' approvata
--     (auto-approvazione = violazione diretta di V4).
--   * policy `no_self_approve`: chi ha creato la proposta non puo' approvarla
--     (`proposto_da <> current_user`). E' **RESTRICTIVE**: cosi' l'UPDATE
--     sulla propria proposta tocca **0 righe** (non solleva 42501), che e' il
--     criterio osservabile del piano (B1-PRP-04).
--   * `ti` perde le scritture di dominio (V4: il dominio lo scrive solo
--     `applicatore`); conserva `fonte`, `parametro`, `ruolo_casa`,
--     `identita_onyx`.
--
-- Divergenze dichiarate (riportate nel report, non silenziose):
--   D1. `casa_*` conserva INSERT/UPDATE/DELETE su scheda_servizio/evento/
--       opportunita/richiesta limitato a `casa_id = casa_corrente()`
--       (matrice congelata di `.specs/B1-dati.md` §002 + plan.md §7 riga 390:
--       «Scrittura diretta gestore su proprie schede/eventi/opportunita via
--       NocoDB: ammessa»). Non revocato qui: l'interruttore e' il blocco
--       `-- [SWITCH-CASA-STRICT]` piu' sotto.
--   D2. `ev_ical_ins/upd` + GRANT INSERT/UPDATE su `evento` ad `automazioni`:
--       unica eccezione ammessa a V4 (upsert iCal, §8 F4).
--   D3. Colonne aggiunte da questo file (assunzione dichiarata):
--       `proposta.nota_decisione`, `audit.entita`, `audit.entita_id`,
--       `<dominio>.aggiornato_ts`. Nessuna esiste nel DDL §7.1; servono a
--       §9.1 (`nota` di `approva_proposta`) e a B1-PRP-06
--       (`v_scritture_senza_audit`, contabilita' delle scritture via audit).
--   D4. `applicatore` riceve una policy permissiva `appl_all` sulle 5 tabelle
--       di dominio: con `FORCE ROW LEVEL SECURITY` il proprietario
--       `applicatore` (usato dalle funzioni SECURITY DEFINER) non passerebbe
--       senza policy. E' la sola via di scrittura del dominio.
--   D5. DELETE revocato anche ai ruoli Casa, che la matrice congelata
--       ammetterebbe. Prevale V4 regola 7 («mai DELETE su entita' di dominio:
--       si marca chiuso/annullato») e §8 F4 («mai DELETE, annullato=true»).
--
-- [ASSUNZIONE] Il DDL v1.1 non esiste nel repo: nomi di tabella/colonna presi
-- da §7.1 dell'architettura + `.specs/B1-dati.md` (ricostruzione del worker
-- trasi-dati, verificata via hub il 15/09).
-- ============================================================================
\set ON_ERROR_STOP on

-- Ruoli applicativi (usati piu' volte).
\set casa_roles 'casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao, casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano'

-- ---------------------------------------------------------------------------
-- 0. Precondizioni
-- ---------------------------------------------------------------------------
DO $pre$
DECLARE
  v_tab_missing text;
  v_roles_missing text;
BEGIN
  SELECT string_agg(x, ', ') INTO v_tab_missing
    FROM unnest(ARRAY['trasi.proposta','trasi.audit','trasi.casa','trasi.luogo',
                      'trasi.scheda_servizio','trasi.evento','trasi.opportunita',
                      'trasi.fonte','trasi.ruolo_casa']) x
   WHERE to_regclass(x) IS NULL;
  IF v_tab_missing IS NOT NULL THEN
    RAISE EXCEPTION 'B1-proposte/005: mancano % — applica prima db/001_schema.sql e db/002_rls.sql', v_tab_missing;
  END IF;

  SELECT string_agg(r, ', ') INTO v_roles_missing
    FROM unnest(ARRAY['applicatore','automazioni','shim_rw','rete','ti','metabase_ro',
                      'casa_santaspazio','casa_molo12','casa_erranti','casa_buscicchio',
                      'casa_sanbao','casa_minimus','casa_pop','casa_bozzano','casa_dream',
                      'casa_tuturano']) r
   WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r);
  IF v_roles_missing IS NOT NULL THEN
    RAISE EXCEPTION 'B1-proposte/005: mancano i ruoli % — applica prima db/000_roles.sql', v_roles_missing;
  END IF;

  -- Funzioni del contratto congelato (db/001, worker trasi-dati): le policy le
  -- referenziano, quindi devono esistere prima di questo file.
  IF to_regprocedure('trasi.casa_corrente()') IS NULL
     OR to_regprocedure('trasi.approvatore_default(text,integer)') IS NULL THEN
    RAISE EXCEPTION 'B1-proposte/005: mancano trasi.casa_corrente()/trasi.approvatore_default(text,int) — applica prima db/001_schema.sql';
  END IF;

  -- V4: nessun ruolo applicativo puo' scavalcare la RLS.
  IF EXISTS (SELECT 1 FROM pg_roles
              WHERE (rolname IN ('applicatore','automazioni','shim_rw','rete','ti','metabase_ro')
                     OR rolname LIKE 'casa\_%')
                AND rolbypassrls) THEN
    RAISE EXCEPTION 'B1-proposte/005: un ruolo applicativo ha BYPASSRLS — la RLS non sarebbe autorita''';
  END IF;
END
$pre$;

-- ---------------------------------------------------------------------------
-- 1. Colonne di V4 (D3) — ADD COLUMN IF NOT EXISTS, idempotente
-- ---------------------------------------------------------------------------
ALTER TABLE trasi.proposta ADD COLUMN IF NOT EXISTS nota_decisione text;

ALTER TABLE trasi.audit    ADD COLUMN IF NOT EXISTS entita    text;
ALTER TABLE trasi.audit    ADD COLUMN IF NOT EXISTS entita_id integer;

-- `aggiornato_ts`: impronta di scrittura sulle entita' di dominio. Base di
-- `v_scritture_senza_audit` (B1-PRP-06): ogni mutazione del dominio deve avere
-- una riga `audit` corrispondente (azione 'applicata' / 'ical_upsert').
ALTER TABLE trasi.luogo           ADD COLUMN IF NOT EXISTS aggiornato_ts timestamptz;
ALTER TABLE trasi.scheda_servizio ADD COLUMN IF NOT EXISTS aggiornato_ts timestamptz;
ALTER TABLE trasi.evento          ADD COLUMN IF NOT EXISTS aggiornato_ts timestamptz;
ALTER TABLE trasi.opportunita     ADD COLUMN IF NOT EXISTS aggiornato_ts timestamptz;
ALTER TABLE trasi.casa            ADD COLUMN IF NOT EXISTS aggiornato_ts timestamptz;

-- Chi ha scritto: e' l'informazione che rende `v_scritture_senza_audit` una
-- contabilita' e non un'euristica. Senza, una scrittura diretta legittima
-- (gestore sulla propria Casa, D1) e una scrittura illecita sarebbero
-- indistinguibili.
ALTER TABLE trasi.luogo           ADD COLUMN IF NOT EXISTS aggiornato_da text;
ALTER TABLE trasi.scheda_servizio ADD COLUMN IF NOT EXISTS aggiornato_da text;
ALTER TABLE trasi.evento          ADD COLUMN IF NOT EXISTS aggiornato_da text;
ALTER TABLE trasi.opportunita     ADD COLUMN IF NOT EXISTS aggiornato_da text;
ALTER TABLE trasi.casa            ADD COLUMN IF NOT EXISTS aggiornato_da text;

-- ---------------------------------------------------------------------------
-- 1b. Impronta di scrittura generica (B1-PRP-06).
--     `aggiornato_ts` va timbrato da OGNI scrittura, non solo da quelle
--     mediate: altrimenti `v_scritture_senza_audit` non potrebbe accorgersi di
--     una scrittura diretta (che e' esattamente cio' che deve contabilizzare).
--     La funzione e' SECURITY INVOKER e non tocca privilegi: scrive solo il
--     campo `NEW`.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION trasi.scrittura_00_ts()
RETURNS trigger
LANGUAGE plpgsql
AS $fn$
BEGIN
  NEW.aggiornato_ts := now();
  -- Ruolo EFFETTIVO (current_user): e' il ruolo i cui privilegi e le cui policy
  -- hanno autorizzato la scrittura. Il seed gira come `trasi_owner` via
  -- `SET ROLE`, il percorso mediato come `applicatore`, l'upsert iCal come
  -- `automazioni`, il gestore sulla propria Casa come `casa_<slug>`: e' questa
  -- l'informazione che rende la contabilita' di `v_scritture_senza_audit`
  -- capace di distinguere una scrittura dichiarata da una violazione di V4.
  -- (`session_user`, il ruolo di login, resta in `audit.eseguito_da`, dove
  -- serve a ricostruire chi si e' autenticato.)
  NEW.aggiornato_da := current_user;
  RETURN NEW;
END;
$fn$;

DROP TRIGGER IF EXISTS scrittura_00_ts ON trasi.luogo;
CREATE TRIGGER scrittura_00_ts BEFORE INSERT OR UPDATE ON trasi.luogo
  FOR EACH ROW EXECUTE FUNCTION trasi.scrittura_00_ts();
DROP TRIGGER IF EXISTS scrittura_00_ts ON trasi.scheda_servizio;
CREATE TRIGGER scrittura_00_ts BEFORE INSERT OR UPDATE ON trasi.scheda_servizio
  FOR EACH ROW EXECUTE FUNCTION trasi.scrittura_00_ts();
DROP TRIGGER IF EXISTS scrittura_00_ts ON trasi.evento;
CREATE TRIGGER scrittura_00_ts BEFORE INSERT OR UPDATE ON trasi.evento
  FOR EACH ROW EXECUTE FUNCTION trasi.scrittura_00_ts();
DROP TRIGGER IF EXISTS scrittura_00_ts ON trasi.opportunita;
CREATE TRIGGER scrittura_00_ts BEFORE INSERT OR UPDATE ON trasi.opportunita
  FOR EACH ROW EXECUTE FUNCTION trasi.scrittura_00_ts();
DROP TRIGGER IF EXISTS scrittura_00_ts ON trasi.casa;
CREATE TRIGGER scrittura_00_ts BEFORE INSERT OR UPDATE ON trasi.casa
  FOR EACH ROW EXECUTE FUNCTION trasi.scrittura_00_ts();

-- ---------------------------------------------------------------------------
-- 2. Vincoli di V4 (V5/§12): si approva solo leggendo
-- ---------------------------------------------------------------------------
-- `diff` obbligatorio. Il valore lo genera il trigger `proposta_03_diff_tg`
-- (db/006): qui si vincola solo la presenza. NOT VALID per non far fallire
-- l'installazione su un pregresso incoerente; il vincolo e' comunque attivo su
-- ogni INSERT/UPDATE nuovo, e viene validato se il pregresso e' pulito.
DO $chk$
BEGIN
  ALTER TABLE trasi.proposta
    ADD CONSTRAINT proposta_diff_nn CHECK (diff IS NOT NULL) NOT VALID;
EXCEPTION WHEN duplicate_object THEN NULL;
END
$chk$;

DO $val$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM trasi.proposta WHERE diff IS NULL) THEN
    ALTER TABLE trasi.proposta VALIDATE CONSTRAINT proposta_diff_nn;
  END IF;
END
$val$;

-- Nota di decisione (campo `nota` di `approva_proposta`, §9.1): come
-- `motivazione`, testo libero ma ≤ 80 caratteri (V5/§12).
ALTER TABLE trasi.proposta DROP CONSTRAINT IF EXISTS proposta_nota_decisione_len;
ALTER TABLE trasi.proposta
  ADD CONSTRAINT proposta_nota_decisione_len
  CHECK (nota_decisione IS NULL OR char_length(nota_decisione) <= 80);

-- ---------------------------------------------------------------------------
-- 3. RLS di `proposta`: si chiude il buco del DDL §7.1
-- ---------------------------------------------------------------------------
ALTER TABLE trasi.proposta ENABLE ROW LEVEL SECURITY;
ALTER TABLE trasi.proposta FORCE  ROW LEVEL SECURITY;

-- Il DDL dell'architettura crea `ins_any WITH CHECK (true)` e `upd_own`
-- (senza WITH CHECK): entrambe sostituite. `ins_any` consentirebbe l'INSERT di
-- una proposta gia' approvata; `upd_own` non vincola i valori NUOVI della riga.
DROP POLICY IF EXISTS ins_any          ON trasi.proposta;
DROP POLICY IF EXISTS upd_own          ON trasi.proposta;
DROP POLICY IF EXISTS sel_all          ON trasi.proposta;
DROP POLICY IF EXISTS ins_client       ON trasi.proposta;
DROP POLICY IF EXISTS upd_client       ON trasi.proposta;
DROP POLICY IF EXISTS no_self_approve  ON trasi.proposta;
DROP POLICY IF EXISTS upd_appl         ON trasi.proposta;
DROP POLICY IF EXISTS upd_scade        ON trasi.proposta;

-- Lettura: tutti leggono le proposte (principio 3, «tutti leggono tutto»).
-- La minimizzazione (`proposto_da`/`approvato_da` fuori dalle viste) e' in 004/006.
CREATE POLICY sel_all ON trasi.proposta
  FOR SELECT
  USING (true);

-- Inserimento: si propone **solo** nello stato iniziale. Un client non puo'
-- depositare una riga gia' decisa (auto-approvazione).
CREATE POLICY ins_client ON trasi.proposta
  FOR INSERT
  WITH CHECK (stato = 'proposta'
              AND approvato_ts IS NULL
              AND approvato_da IS NULL);

-- Decisione umana: o l'approvatore e' il gestore e la proposta e' della SUA
-- Casa (`casa_corrente()` = `ruolo_casa` su `current_user`), oppure
-- l'approvatore e' `at`/`ti` ed e' in mano a `rete`/`ti`.
-- USING sceglie le righe decidibili; WITH CHECK vincola i valori NUOVI: una
-- decisione lascia la proposta in `approvata`/`rifiutata`, mai `applicata`.
CREATE POLICY upd_client ON trasi.proposta
  FOR UPDATE
  USING ((approvatore_ruolo = 'gestore' AND casa_id = trasi.casa_corrente())
      OR (approvatore_ruolo IN ('at','ti') AND current_user IN ('rete','ti')))
  WITH CHECK (stato IN ('approvata','rifiutata')
              AND approvato_da IS NOT NULL
              AND approvato_ts IS NOT NULL
              AND approvato_da <> proposto_da);

-- V4, regola 1 — auto-approvazione vietata. RESTRICTIVE (AND con le policy
-- permissive): la riga proposta da chi la sta decidendo non e' nemmeno
-- visibile all'UPDATE -> **0 righe**, senza errore. Vale su old e new row.
CREATE POLICY no_self_approve ON trasi.proposta
  AS RESTRICTIVE
  FOR UPDATE
  USING (proposto_da IS DISTINCT FROM current_user)
  WITH CHECK (proposto_da IS DISTINCT FROM current_user);

-- Percorso di applicazione (db/006 `applica_proposte_approvate`, SECURITY
-- DEFINER owner `applicatore`). Con FORCE RLS anche il proprietario ha bisogno
-- di una policy: questa e' la sola via che porta una proposta ad `applicata`.
CREATE POLICY upd_appl ON trasi.proposta
  FOR UPDATE TO applicatore
  USING (stato = 'approvata')
  WITH CHECK (stato = 'applicata');

-- Percorso di scadenza (`scadi_proposte`): solo le proposte scadute e mai
-- trattate possono passare a `scaduta`.
CREATE POLICY upd_scade ON trasi.proposta
  FOR UPDATE TO applicatore
  USING (stato = 'proposta' AND scade_il IS NOT NULL AND scade_il < current_date)
  WITH CHECK (stato = 'scaduta');

-- ---------------------------------------------------------------------------
-- 4. Grant delle proposte: la colonna `approvatore_ruolo` NON e' grantata
--    ai client (regola 2): la calcola il trigger dalla funzione
--    `approvatore_default(tipo, casa_id)`. Lo stesso vale per `stato` in
--    INSERT e per `approvato_da/approvato_ts`.
-- ---------------------------------------------------------------------------
GRANT USAGE ON SCHEMA trasi TO shim_rw, automazioni, applicatore, rete, ti, metabase_ro,
  casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
  casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano;

-- Si azzera ogni grant di tabella su `proposta` e si ricostruisce per colonna:
-- cosi' nessuno riceve (per inerzia da 002) il diritto di scrivere `stato` in
-- INSERT o `approvatore_ruolo`.
REVOKE ALL ON trasi.proposta FROM PUBLIC;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON trasi.proposta
  FROM shim_rw, automazioni, metabase_ro, rete, ti,
       casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
       casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano, applicatore;

-- INSERT colonnare: il client sceglie solo i valori della proposta.
-- Niente `approvatore_ruolo`, niente `stato`, niente `approvato_da/ts`.
GRANT INSERT (origine, tipo, entita, entita_id, casa_id, fonte_id,
              payload, diff, motivazione, proposto_da, scade_il)
  ON trasi.proposta
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano,
     rete, ti, automazioni;

-- UPDATE colonnare: la decisione (`stato`) e la nota (`nota_decisione`).
-- `approvatore_ruolo` resta fuori anche qui; `approvato_da/approvato_ts` li
-- scrive il trigger di transizione (`current_user`, `now()`).
GRANT UPDATE (stato, nota_decisione)
  ON trasi.proposta
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano,
     rete, ti;

-- `automazioni` propone (fonte_automatica / coerenza) e applica, non approva:
-- nessun UPDATE su `proposta`. `shim_rw` non propone direttamente: lo shim
-- esegue `SET LOCAL ROLE casa_<slug>` per richiesta (§9.1).

GRANT SELECT ON trasi.proposta TO shim_rw, automazioni, applicatore, rete, ti, metabase_ro,
  casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
  casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano;

-- `applicatore` e' il ruolo applicativo (NOLOGIN) delle funzioni SECURITY
-- DEFINER di db/006: e' l'unico a poter portare una proposta ad `applicata`
-- (la policy `upd_appl` gli consente esattamente quella transizione).
GRANT SELECT, UPDATE ON trasi.proposta TO applicatore;

-- ---------------------------------------------------------------------------
-- 5. Dominio: REVOKE delle scritture.  La matrice di 002 concede le scritture
--    applicative; questo file (gira dopo) le revoca — la RLS e' l'autorita'.
-- ---------------------------------------------------------------------------
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
  ON trasi.luogo, trasi.scheda_servizio, trasi.evento, trasi.opportunita, trasi.casa
  FROM shim_rw, automazioni, ti, metabase_ro, PUBLIC;

-- V4 regola 7 — mai DELETE sul dominio: la memoria si chiude (`chiuso_il`) o si
-- annulla (`annullato=true`), non si cancella. Vale anche per i ruoli Casa, che
-- conservano INSERT/UPDATE entro la propria Casa (matrice congelata, D1) ma non
-- il DELETE. §8 F4 lo dice esplicitamente per gli eventi iCal.
REVOKE DELETE ON trasi.luogo, trasi.scheda_servizio, trasi.evento, trasi.opportunita, trasi.casa
  FROM casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
       casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano;

-- [SWITCH-CASA-STRICT] Se Processi decide che il gestore scrive solo via
-- proposta (plan.md §7, riga 390), decommentare il REVOKE seguente: e' l'unico
-- interruttore necessario, il resto di V4 resta invariato.
-- REVOKE INSERT, UPDATE, DELETE ON trasi.scheda_servizio, trasi.evento,
--   trasi.opportunita FROM casa_santaspazio, casa_molo12, casa_erranti,
--   casa_buscicchio, casa_sanbao, casa_minimus, casa_pop, casa_bozzano,
--   casa_dream, casa_tuturano;

-- RLS: ENABLE + FORCE su tutte le tabelle di dominio (nessun proprietario
-- privilegiato; l'applicatore passa per la propria policy `appl_all`).
ALTER TABLE trasi.luogo           ENABLE ROW LEVEL SECURITY;
ALTER TABLE trasi.luogo           FORCE  ROW LEVEL SECURITY;
ALTER TABLE trasi.scheda_servizio ENABLE ROW LEVEL SECURITY;
ALTER TABLE trasi.scheda_servizio FORCE  ROW LEVEL SECURITY;
ALTER TABLE trasi.evento          ENABLE ROW LEVEL SECURITY;
ALTER TABLE trasi.evento          FORCE  ROW LEVEL SECURITY;
ALTER TABLE trasi.opportunita     ENABLE ROW LEVEL SECURITY;
ALTER TABLE trasi.opportunita     FORCE  ROW LEVEL SECURITY;
ALTER TABLE trasi.casa            ENABLE ROW LEVEL SECURITY;
ALTER TABLE trasi.casa            FORCE  ROW LEVEL SECURITY;

-- 5a. L'applicatore e' l'unico che scrive il dominio (V4). Policy permissiva
--     dedicata: senza di essa, con FORCE RLS, neppure le funzioni SECURITY
--     DEFINER owner `applicatore` potrebbero scrivere.
DROP POLICY IF EXISTS appl_all ON trasi.luogo;
DROP POLICY IF EXISTS appl_all ON trasi.scheda_servizio;
DROP POLICY IF EXISTS appl_all ON trasi.evento;
DROP POLICY IF EXISTS appl_all ON trasi.opportunita;
DROP POLICY IF EXISTS appl_all ON trasi.casa;

CREATE POLICY appl_all ON trasi.luogo           FOR ALL TO applicatore USING (true) WITH CHECK (true);
CREATE POLICY appl_all ON trasi.scheda_servizio FOR ALL TO applicatore USING (true) WITH CHECK (true);
CREATE POLICY appl_all ON trasi.evento          FOR ALL TO applicatore USING (true) WITH CHECK (true);
CREATE POLICY appl_all ON trasi.opportunita     FOR ALL TO applicatore USING (true) WITH CHECK (true);
CREATE POLICY appl_all ON trasi.casa            FOR ALL TO applicatore USING (true) WITH CHECK (true);

-- 5b. Unica eccezione a V4: upsert iCal su `evento` da `automazioni`,
--     vincolato a `fonte.tipo_accesso = 'ical'` (§8 F4: fiducia 2,
--     reversibile, `annullato=true` invece di DELETE).
DROP POLICY IF EXISTS ev_ical_ins ON trasi.evento;
DROP POLICY IF EXISTS ev_ical_upd ON trasi.evento;

CREATE POLICY ev_ical_ins ON trasi.evento
  FOR INSERT TO automazioni
  WITH CHECK (fonte_id IS NOT NULL
              AND EXISTS (SELECT 1 FROM trasi.fonte f
                           WHERE f.id = fonte_id AND f.tipo_accesso = 'ical'));

CREATE POLICY ev_ical_upd ON trasi.evento
  FOR UPDATE TO automazioni
  USING (fonte_id IS NOT NULL
         AND EXISTS (SELECT 1 FROM trasi.fonte f
                      WHERE f.id = fonte_id AND f.tipo_accesso = 'ical'))
  WITH CHECK (fonte_id IS NOT NULL
              AND EXISTS (SELECT 1 FROM trasi.fonte f
                           WHERE f.id = fonte_id AND f.tipo_accesso = 'ical'));

-- 5c. Letture necessarie a valutare le policy e ai percorsi di scrittura.
GRANT SELECT ON trasi.fonte TO automazioni, shim_rw, metabase_ro, rete, ti,
  casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
  casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano, applicatore;

-- 5d. Scritture dell'applicatore (regola 4). `casa` solo per gli orari:
--     l'applicatore non tocca anagrafica, geografia, raggio, contatti.
--     `aggiornato_ts` e' l'impronta usata da `v_scritture_senza_audit` (D3).
GRANT INSERT, UPDATE ON trasi.luogo, trasi.scheda_servizio, trasi.evento, trasi.opportunita
  TO applicatore;
GRANT UPDATE (orari, orari_eccezioni, orari_provvisori, aggiornato_ts) ON trasi.casa
  TO applicatore;
GRANT SELECT ON trasi.luogo, trasi.scheda_servizio, trasi.evento, trasi.opportunita,
                 trasi.casa, trasi.ruolo_casa, trasi.identita_onyx
  TO applicatore;

-- 5e. Eccezione iCal: `automazioni` ha INSERT/UPDATE su `evento`, ma solo
--     entro la policy `ev_ical_*` (la fonte deve essere iCal). Nessun DELETE.
GRANT INSERT, UPDATE ON trasi.evento TO automazioni;

-- 5f. Le INSERT richiedono USAGE sulla sequenza della PK (`serial`): senza,
--     qualunque scrittura legittima fallirebbe con «permission denied for
--     sequence». Si concede solo a chi scrive (applicatore, automazioni).
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA trasi TO applicatore, automazioni;

-- ---------------------------------------------------------------------------
-- 6. `audit` e' append-only (regola 5): INSERT solo all'applicatore.
--    Nessun GRANT UPDATE/DELETE a nessuno — all'applicatore compreso.
--    Nessuna RLS su audit (§7.1): la protezione e' per GRANT, come da
--    contratto con trasi-dati.
-- ---------------------------------------------------------------------------
ALTER TABLE trasi.audit NO FORCE ROW LEVEL SECURITY;
ALTER TABLE trasi.audit DISABLE  ROW LEVEL SECURITY;

REVOKE ALL ON trasi.audit FROM PUBLIC;
REVOKE ALL ON trasi.audit FROM shim_rw, automazioni, rete, ti, metabase_ro,
  casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
  casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano, applicatore;

GRANT SELECT ON trasi.audit TO shim_rw, automazioni, rete, ti, metabase_ro,
  casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
  casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano, applicatore;

GRANT INSERT ON trasi.audit TO applicatore;

REVOKE UPDATE, DELETE, TRUNCATE ON trasi.audit FROM applicatore, PUBLIC;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA trasi TO applicatore;

-- ---------------------------------------------------------------------------
-- 7. Verifica di installazione (visibile in output: la RLS e' l'autorita')
-- ---------------------------------------------------------------------------
DO $verify$
DECLARE
  v_n int;
  v_owner text;
BEGIN
  SELECT count(*) INTO v_n
    FROM pg_policies WHERE schemaname = 'trasi' AND tablename = 'proposta'
     AND policyname IN ('sel_all','ins_client','upd_client','no_self_approve','upd_appl','upd_scade');
  IF v_n <> 6 THEN
    RAISE EXCEPTION 'B1-proposte/005: attese 6 policy su trasi.proposta, trovate %', v_n;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_policies
                  WHERE schemaname='trasi' AND tablename='proposta'
                    AND policyname='no_self_approve' AND permissive='RESTRICTIVE') THEN
    RAISE EXCEPTION 'B1-proposte/005: no_self_approve deve essere RESTRICTIVE (altrimenti l''auto-approvazione da'' 42501 invece di 0 righe)';
  END IF;

  SELECT count(*) INTO v_n FROM pg_policies
   WHERE schemaname='trasi' AND tablename IN ('luogo','scheda_servizio','evento','opportunita','casa')
     AND (policyname LIKE 'appl\_all' OR policyname LIKE 'ev\_ical\_%');
  IF v_n <> 7 THEN
    RAISE EXCEPTION 'B1-proposte/005: attese 7 policy di dominio (5 appl_all + 2 ical), trovate %', v_n;
  END IF;

  IF EXISTS (SELECT 1 FROM pg_policies
              WHERE schemaname='trasi' AND tablename='proposta'
                AND policyname IN ('ins_any','upd_own')) THEN
    RAISE EXCEPTION 'B1-proposte/005: il buco del DDL §7.1 e'' ancora aperto (ins_any/upd_own presenti)';
  END IF;

  SELECT pg_get_userbyid(c.relowner) INTO v_owner FROM pg_class c
    JOIN pg_namespace n ON n.oid=c.relnamespace
   WHERE n.nspname='trasi' AND c.relname='proposta';
  RAISE NOTICE 'B1-proposte/005 applicato: 6 policy V4 su proposta (no_self_approve RESTRICTIVE), 7 policy di dominio, audit append-only. Owner proposta: %', v_owner;
END
$verify$;
