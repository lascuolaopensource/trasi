-- Trasi — db/013_credenziali.sql
-- Login unico delle Case di Quartiere (US-6.x, decisione Fase 0 §2 «Meccanismo auth»):
-- sessione propria dello shim, cookie HttpOnly emesso da auth.py, hash bcrypt in pgcrypto.
-- Niente account Onyx nativi, niente redirect: Onyx non vede il browser e viceversa.
--
-- Contenuto: estensione pgcrypto + tabelle credenziale_casa / sessione / tentativo_login
--            + RLS, policy e GRANT. Le FUNZIONI (crea_sessione) sono in db/006_fn_proposte.sql
--            (owner `applicatore`, stesso perimetro di sicurezza delle altre SECURITY DEFINER).
--
-- Vincoli applicati:
--   * RLS ENABLE+FORCE con USING **e** WITH CHECK (la RLS è l'autorità, non lo shim);
--   * hash SOLO nel DB: crypt()/gen_salt() di pgcrypto — niente hash lato shim (niente passlib);
--   * aggiornato_da/aggiornato_ts li scrive il trigger (current_user), non chi chiama:
--     il GRANT UPDATE a `ti` è sulla sola colonna pass_hash;
--   * scritture di sessioni/tentativi SOLO via funzioni owner `applicatore`
--     (crea_sessione in 006, scadi_messaggi per la retention): nessun GRANT di scrittura ai client.
--
-- Idempotente: rieseguibile senza errori.
\set ON_ERROR_STOP on
\set VERBOSITY terse

-- ---------------------------------------------------------------------------
-- 0. Estensione pgcrypto (bcrypt via gen_salt('bf'))
-- ---------------------------------------------------------------------------
-- Questa istruzione gira **prima** del `SET ROLE` qui sotto, e non è un dettaglio
-- di stile: `CREATE EXTENSION` richiede privilegi di amministratore, e `apply.sh`
-- esegue gli script come utente amministratore del container che poi *impersona*
-- `trasi_owner` con un `SET ROLE`. Con l'estensione creata dopo il `SET ROLE`,
-- l'apply falliva con `permission denied to create extension "pgcrypto"` — cioè
-- prima ancora che la prima riga di schema esistesse. Stesso modello di PostGIS
-- (precondizione verificata da `apply.sh`): l'estensione è una risorsa del
-- cluster, non un oggetto dello schema.
--
-- Va nel search_path `public`: le funzioni crypt/gen_salt restano risolvibili
-- anche per le SECURITY DEFINER di db/006 (che fissano search_path = 'public').
-- Se l'estensione esistesse altrove, la si riporta in `public` (idempotente).
DO $$
DECLARE v_schema text;
BEGIN
  SELECT n.nspname INTO v_schema
    FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace
   WHERE e.extname = 'pgcrypto';
  IF v_schema IS NULL THEN
    CREATE EXTENSION pgcrypto WITH SCHEMA public;
  ELSIF v_schema <> 'public' THEN
    ALTER EXTENSION pgcrypto SET SCHEMA public;
  END IF;
END $$;

-- Da qui in poi si lavora come owner dello schema, come gli altri file di apply.sh.
SET ROLE trasi_owner;
SET search_path = trasi, public, pg_temp;

-- ---------------------------------------------------------------------------
-- 1. credenziale_casa — una credenziale per Casa (US-6.1: un solo account per CdQ)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trasi.credenziale_casa (
  casa_id       integer PRIMARY KEY REFERENCES trasi.casa(id),
  pass_hash     text NOT NULL,
  aggiornato_ts timestamptz NOT NULL DEFAULT now(),
  aggiornato_da text NOT NULL DEFAULT 'seed'
);
COMMENT ON TABLE trasi.credenziale_casa IS
  'Credenziale della Casa (login unico, US-6.1): bcrypt in pass_hash. La rotazione/subentro è UPDATE pass_hash da `ti` (runbook deployment/README.md); aggiornato_ts/aggiornato_da li scrive il trigger, mai il client.';
COMMENT ON COLUMN trasi.credenziale_casa.aggiornato_da IS
  'Ruolo DB effettivo (current_user) che ha cambiato l''hash: la prova della rotazione (US-6.1) senza nominare la persona.';

-- Trigger: il timbro della rotazione lo calcola il DB — chi aggiorna non se lo sceglie
-- (stessa regola di proposta.approvatore_ruolo: colonne calcolate fuori dai GRANT).
CREATE OR REPLACE FUNCTION trasi.credenziale_00_ts() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
BEGIN
  NEW.aggiornato_ts := now();
  NEW.aggiornato_da := current_user::text;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS credenziale_00_ts ON trasi.credenziale_casa;
CREATE TRIGGER credenziale_00_ts BEFORE UPDATE ON trasi.credenziale_casa
  FOR EACH ROW EXECUTE FUNCTION trasi.credenziale_00_ts();

-- Password iniziale documentata (runbook: `slug della casa` + «2026!», da cambiare subito).
-- Solo righe mancanti (INSERT SELECT ... WHERE NOT EXISTS): una password già ruotata da `ti`
-- NON viene riportata al valore iniziale da una riesecuzione.
INSERT INTO trasi.credenziale_casa (casa_id, pass_hash)
SELECT c.id, public.crypt(replace(c.slug, '-', '') || '2026!', public.gen_salt('bf'))
  FROM trasi.casa c
 WHERE NOT EXISTS (SELECT 1 FROM trasi.credenziale_casa cc WHERE cc.casa_id = c.id);

-- ---------------------------------------------------------------------------
-- 2. sessione — token opaco del cookie trasi_sessione
-- ---------------------------------------------------------------------------
-- Il token è generato dal DB (gen_random_uuid di pgcrypto): niente entropy dal chiamante.
-- La scadenza è decisa da crea_sessione() leggendo il parametro session_ttl_hours
-- (il DEFAULT qui sotto è il ripiego per inserimenti fuori dalla funzione: non ce ne sono,
--  perché INSERT è solo di `applicatore` e la funzione la imposta sempre).
CREATE TABLE IF NOT EXISTS trasi.sessione (
  token     uuid PRIMARY KEY DEFAULT public.gen_random_uuid(),
  casa_id   integer NOT NULL REFERENCES trasi.casa(id),
  scade_ts  timestamptz NOT NULL DEFAULT now() + interval '12 hours'
);
COMMENT ON TABLE trasi.sessione IS
  'Sessioni del cookie trasi_sessione (HttpOnly, SameSite=Lax): token opaco + scadenza. Scritta solo da crea_sessione() (owner applicatore); pulita dal passo notturno scadi_messaggi().';
CREATE INDEX IF NOT EXISTS sessione_scade_idx ON trasi.sessione (scade_ts);

-- ---------------------------------------------------------------------------
-- 3. tentativo_login — contatore anti brute-force per Casa
-- ---------------------------------------------------------------------------
-- Regola (contract): più di 4 fallimenti in 10 minuti per la stessa Casa → crea_sessione
-- ritorna NULL e scrive audit 'login_bloccato'; al successo i tentativi della Casa sono
-- azzerati. Tabella separata da `sessione`: i fallimenti non devono sopravvivere al login.
CREATE TABLE IF NOT EXISTS trasi.tentativo_login (
  casa_id integer NOT NULL REFERENCES trasi.casa(id),
  ts      timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE trasi.tentativo_login IS
  'Fallimenti di login per Casa (anti brute-force): >4 in 10 minuti → blocco. Azzerati al login riuscito; gli oltre-10-minuti sono rimossi dal passo notturno (scadi_messaggi in db/006).';
CREATE INDEX IF NOT EXISTS tentativo_login_casa_ts_idx ON trasi.tentativo_login (casa_id, ts);

-- ---------------------------------------------------------------------------
-- 4. RLS — ENABLE + FORCE (la RLS è l'autorità; `audit` resta l'unica eccezione per GRANT)
-- ---------------------------------------------------------------------------
ALTER TABLE trasi.credenziale_casa ENABLE ROW LEVEL SECURITY;
ALTER TABLE trasi.credenziale_casa FORCE  ROW LEVEL SECURITY;
ALTER TABLE trasi.sessione         ENABLE ROW LEVEL SECURITY;
ALTER TABLE trasi.sessione         FORCE  ROW LEVEL SECURITY;
ALTER TABLE trasi.tentativo_login  ENABLE ROW LEVEL SECURITY;
ALTER TABLE trasi.tentativo_login  FORCE  ROW LEVEL SECURITY;

-- owner: con FORCE RLS nemmeno trasi_owner legge senza policy (stessa regola di db/002).
DROP POLICY IF EXISTS owner_all ON trasi.credenziale_casa;
CREATE POLICY owner_all ON trasi.credenziale_casa FOR ALL TO trasi_owner USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS owner_all ON trasi.sessione;
CREATE POLICY owner_all ON trasi.sessione FOR ALL TO trasi_owner USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS owner_all ON trasi.tentativo_login;
CREATE POLICY owner_all ON trasi.tentativo_login FOR ALL TO trasi_owner USING (true) WITH CHECK (true);

-- applicatore: le SECURITY DEFINER di db/006 girano come `applicatore` e con FORCE RLS
-- hanno bisogno della policy esplicita (stesso disegno di `appl_all` sul dominio, db/005).
DROP POLICY IF EXISTS appl_all ON trasi.credenziale_casa;
CREATE POLICY appl_all ON trasi.credenziale_casa FOR ALL TO applicatore USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS appl_all ON trasi.sessione;
CREATE POLICY appl_all ON trasi.sessione FOR ALL TO applicatore USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS appl_all ON trasi.tentativo_login;
CREATE POLICY appl_all ON trasi.tentativo_login FOR ALL TO applicatore USING (true) WITH CHECK (true);

-- ti: rotazione e subentro (runbook). USING+WITH CHECK su entrambe le policy di scrittura.
DROP POLICY IF EXISTS cred_sel_ti ON trasi.credenziale_casa;
CREATE POLICY cred_sel_ti ON trasi.credenziale_casa FOR SELECT TO ti USING (true);
DROP POLICY IF EXISTS cred_upd_ti ON trasi.credenziale_casa;
CREATE POLICY cred_upd_ti ON trasi.credenziale_casa FOR UPDATE TO ti USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS sess_sel_ti ON trasi.sessione;
CREATE POLICY sess_sel_ti ON trasi.sessione FOR SELECT TO ti USING (true);

-- shim_rw: la validazione della sessione a ogni richiesta (`auth.dipendenza_sessione_corrente`).
--
-- Perché una policy dedicata e non il solo GRANT. `trasi.sessione` è ENABLE+FORCE RLS e le policy
-- esistenti sono `owner_all` (trasi_owner), `appl_all` (applicatore) e `sess_sel_ti` (ti): con
-- FORCE, **shim_rw non rientra in nessuna**, quindi la sua SELECT vede 0 righe. È il ruolo con cui
-- lo shim fa la ricerca del token — prima di assumere il ruolo della Casa, perché la Casa non è
-- ancora nota — e senza questa policy il login non poteva funzionare: `/login` rispondeva 200 e
-- creava la riga, ma ogni chiamata successiva su `/op/…` rispondeva
-- **401 «sessione assente o scaduta»**. Misurato: `SET ROLE shim_rw; SELECT count(*) FROM
-- trasi.sessione` → 0 mentre la riga esisteva (vista da `postgres`).
--
-- Il perimetro è `SELECT` soltanto: lo shim **legge** il token per validarlo. Non scrive sessioni
-- (le crea `crea_sessione`, owner `applicatore`) e non ne cancella — la revoca del logout è un
-- DELETE che passa dalla stessa funzione/policy dell'owner, non da qui.
DROP POLICY IF EXISTS sess_sel_shim ON trasi.sessione;
CREATE POLICY sess_sel_shim ON trasi.sessione FOR SELECT TO shim_rw USING (true);

-- La **revoca** al logout: `DELETE` della sola riga di sessione, con la sua policy.
--
-- `POST /logout` esegue `DELETE FROM trasi.sessione WHERE token = $1` (`auth.logout`), e senza
-- questo privilegio rispondeva **500** — non 401, non 204: l'operatore premeva «Esci» e riceveva
-- «errore interno». Misurato: `has_table_privilege('shim_rw','trasi.sessione','DELETE')` = false e
-- nessuna policy DELETE per lui. Il logout è l'unico modo che ha un operatore di chiudere la
-- sessione **adesso** invece di aspettare la scadenza delle 12 ore, ed è anche il presidio che il
-- runbook invoca nel subentro («DELETE delle sessioni»).
--
-- Il perimetro è stretto e resta tale: `DELETE` su `sessione` non tocca né il dominio né la
-- memoria — la tabella contiene token opachi e scadenze, e una riga cancellata è una sessione
-- chiusa, non un dato perduto. Nessun `UPDATE`: un token non si modifica, si revoca.
GRANT DELETE ON trasi.sessione TO shim_rw;
DROP POLICY IF EXISTS sess_del_shim ON trasi.sessione;
CREATE POLICY sess_del_shim ON trasi.sessione FOR DELETE TO shim_rw USING (true);

-- shim_rw su `ruolo_casa`: la dipendenza risolve il ruolo della Casa della sessione con
--   `JOIN trasi.ruolo_casa rc ON rc.casa_id = c.id`
-- per poi eseguire `SET LOCAL ROLE <ruolo>`. Anche questa lettura passa da shim_rw (il ruolo della
-- Casa si sta ancora determinando), e `rc_sel_self` di db/002 non basta: ha
-- `USING (ruolo = current_user)`, che per shim_rw significa `ruolo = 'shim_rw'` → 0 righe. La
-- colonna `ruolo` è l'unica informazione che serve, e la tabella è già leggibile in forma
-- colonnare da shim_rw per contratto (db/002, GRANT sui tre campi): la policy allinea la RLS al
-- GRANT che esiste già.
DROP POLICY IF EXISTS rc_sel_shim ON trasi.ruolo_casa;
CREATE POLICY rc_sel_shim ON trasi.ruolo_casa FOR SELECT TO shim_rw USING (true);

-- `applicatore` su `ruolo_casa`: serve a `conferma_movimento` per risolvere ruolo → casa.
--
-- La funzione è SECURITY DEFINER owner `applicatore` e comincia con
--   SELECT rc.casa_id INTO v_casa_id FROM trasi.ruolo_casa rc WHERE rc.ruolo = p_ruolo;
-- con `p_ruolo` = `casa_sanbao` (il ruolo della sessione). `ruolo_casa` è ENABLE+FORCE RLS e
-- `rc_sel_self` ha `USING (ruolo = current_user)`: per `applicatore` quel predicato diventa
-- `ruolo = 'applicatore'`, che nella tabella non esiste → **0 righe**, `v_casa_id` NULL, e la
-- funzione solleva «ruolo casa_sanbao non riconosciuto». Effetto misurato: nessuna conferma di
-- prestito era possibile, da nessun ruolo — il pulsante «Conferma ricezione» della UI rispondeva
-- 409, e la conferma della Casa ricevente è la tutela che in questa eccezione a V4 sostituisce
-- l'approvazione umana. Senza, il prestito non diventava mai effettivo.
--
-- `USING (true)` non allarga nulla: `applicatore` è il ruolo di **macchina** delle SECURITY DEFINER
-- (NOLOGIN, db/000) e ha già `appl_all` su tutte le tabelle di dominio; la mappa ruolo → casa è
-- l'informazione che gli serve per far funzionare le proprie funzioni. La verifica di *chi* può
-- confermare resta dentro `conferma_movimento`, che confronta le Case del movimento.
DROP POLICY IF EXISTS rc_sel_appl ON trasi.ruolo_casa;
CREATE POLICY rc_sel_appl ON trasi.ruolo_casa FOR SELECT TO applicatore USING (true);

-- `richiesta`: la policy e il GRANT che rendono eseguibile `registra_richiesta_operatore`.
--
-- `richiesta` è l'unica tabella di dominio che db/005 **non** copre — il suo `appl_all` è dichiarato
-- per luogo/scheda_servizio/evento/opportunita/casa, perché sono quelle che `applica_proposte_approvate`
-- scrive. Ma `registra_richiesta_operatore` è una SECURITY DEFINER **owner `applicatore`** che scrive
-- proprio `richiesta`, e la tabella è ENABLE+**FORCE** RLS: senza una policy per `applicatore` la RLS
-- blocca la funzione stessa, con l'effetto che l'eccezione a V4 dichiarata nel runbook non era
-- utilizzabile. Misurato: `POST /op/registra_richiesta` con sessione valida →
-- `permission denied for table richiesta`, `has_table_privilege('applicatore','trasi.richiesta','INSERT')`
-- = false, zero policy per `applicatore` sulla tabella.
--
-- `USING (true)` è coerente con il disegno: `applicatore` è il ruolo delle funzioni di dominio, non
-- un'identità applicativa — non ha LOGIN (db/000) e nessuno vi si connette. Il controllo su *quale*
-- Casa registra resta dove deve stare, e resta doppio: la funzione verifica lo slug, la policy
-- `rich_ins_casa` impone `casa_id = casa_corrente()` quando a scrivere è un ruolo Casa.
DROP POLICY IF EXISTS appl_all ON trasi.richiesta;
CREATE POLICY appl_all ON trasi.richiesta FOR ALL TO applicatore USING (true) WITH CHECK (true);

-- Il GRANT di tabella, senza il quale la policy non basta: la RLS filtra le righe, il GRANT concede
-- l'operazione. Servono entrambi (stessa regola delle altre tabelle di dominio).
GRANT SELECT, INSERT, UPDATE ON trasi.richiesta TO applicatore;
GRANT USAGE, SELECT ON SEQUENCE trasi.richiesta_id_seq TO applicatore;

-- ---------------------------------------------------------------------------
-- 5. GRANT — least privilege: i client non toccano sessioni né tentativi
-- ---------------------------------------------------------------------------
-- nessun INSERT/DELETE: le credenziali nascono col seed della Casa (qui sopra) e vivono
-- con lei; il subentro è l'UPDATE pass_hash di `ti`, non una nuova riga.
GRANT SELECT ON trasi.credenziale_casa, trasi.sessione TO ti;
GRANT UPDATE (pass_hash) ON trasi.credenziale_casa TO ti;
GRANT SELECT, INSERT, UPDATE, DELETE ON trasi.credenziale_casa, trasi.sessione, trasi.tentativo_login
  TO trasi_owner;
GRANT SELECT, INSERT, UPDATE, DELETE ON trasi.sessione TO applicatore;
GRANT SELECT, INSERT, DELETE ON trasi.tentativo_login TO applicatore;   -- niente UPDATE: un tentativo non si corregge
GRANT SELECT ON trasi.credenziale_casa TO applicatore;                  -- crea_sessione legge pass_hash, non lo scrive mai

-- ---------------------------------------------------------------------------
-- 6. Verifica di installazione
-- ---------------------------------------------------------------------------
DO $verify$
DECLARE
  v_n    int;
  v_hash text;
BEGIN
  SELECT count(*) INTO v_n FROM trasi.credenziale_casa;
  IF v_n <> 10 THEN
    RAISE EXCEPTION '013: attese 10 credenziali (una per Casa), trovate %', v_n;
  END IF;
  SELECT pass_hash INTO v_hash FROM trasi.credenziale_casa cc
    JOIN trasi.casa c ON c.id = cc.casa_id WHERE c.slug = 'san-bao';
  IF v_hash IS NULL OR public.crypt('sanbao2026!', v_hash) <> v_hash THEN
    RAISE EXCEPTION '013: la password iniziale di san-bao non verifica con crypt()';
  END IF;
  IF public.crypt('password-sbagliata', v_hash) = v_hash THEN
    RAISE EXCEPTION '013: crypt() accetta una password sbagliata (impossibile)';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'trasi' AND c.relkind = 'r'
       AND c.relname IN ('credenziale_casa','sessione','tentativo_login')
       AND NOT (c.relrowsecurity AND c.relforcerowsecurity)
  ) THEN
    RAISE EXCEPTION '013: una tabella credenziali è senza ENABLE+FORCE RLS';
  END IF;

  -- Le due policy che rendono **possibile** la validazione della sessione. Non è un controllo di
  -- forma: senza di esse la ricerca del token legge 0 righe e ogni `/op/…` risponde 401, con il
  -- login che nel frattempo risponde 200 — il difetto più difficile da attribuire perché i due
  -- sintomi sembrano contraddirsi. Il controllo verifica l'**effetto** (le policy esistono), non
  -- l'intenzione di averle scritte.
  IF NOT EXISTS (SELECT 1 FROM pg_policies
                  WHERE schemaname='trasi' AND tablename='sessione' AND policyname='sess_sel_shim') THEN
    RAISE EXCEPTION '013: manca sess_sel_shim — shim_rw non potrebbe validare la sessione (401 su ogni /op/…)';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies
                  WHERE schemaname='trasi' AND tablename='ruolo_casa' AND policyname='rc_sel_shim') THEN
    RAISE EXCEPTION '013: manca rc_sel_shim — la risoluzione del ruolo della Casa leggerebbe 0 righe';
  END IF;

  RAISE NOTICE '013_credenziali applicato: pgcrypto, credenziale_casa (10 righe, bcrypt verificato), sessione, tentativo_login — RLS ENABLE+FORCE, sess_sel_shim/rc_sel_shim per la validazione, grant least-privilege';
END
$verify$;

RESET ROLE;
