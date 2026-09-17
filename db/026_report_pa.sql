-- Trasi — db/026_report_pa.sql
-- Il report di monitoraggio per la Pubblica Amministrazione (US-4, foglio «4.3 Report Mensili»):
-- il report di rete diventa un oggetto **persistito** con uno stato d'approvazione deciso da un
-- umano, visibile in dashboard PA e notificabile.
--
-- ------------------------------------------------------------------------------------------------
-- COSA AGGIUNGE QUESTO FILE RISPETTO A db/024_report.sql
-- ------------------------------------------------------------------------------------------------
-- La 024 ha reso il report un oggetto di dominio (leggibile e commentabile, mai correggibile).
-- Mancava la parte «per la PA»: chi approva, chi legge l'osservatorio, e come la PA vi accede.
--
--   1. Stato HITL sul report: bozza → approvato → inviato_pa. L'umano che decide è il referente
--      (ruolo `rete`, AT); il flusso notturno invia solo ciò che è approvato (V6, V3: la fonte è
--      dichiarata e la decisione resta umana).
--   2. Un canale di accesso nuovo: il ruolo DB `pa` (NOLOGIN, db/000 — vi si arriva solo via
--      `SET LOCAL ROLE` da `shim_rw` dopo `crea_sessione_servizio`), con credenziali proprie e
--      anti brute-force identico a quello delle Case (db/013).
--   3. Le viste k-anonime che la dashboard e la persona Onyx «Trasi Monitoraggio PA» consumano:
--      fasce orarie, confronto mese-su-mese a livello RETE, log della chat. Nessuna di queste
--      espone un numero grezzo sotto soglia: `pa` legge gli aggregati, mai una riga di dominio.
--   4. Il log delle interazioni con l'assistente (`chat_interazione_log`): dichiara **esito e
--      fonte** della risposta, MAI il testo (V5). È la contabilità di qualità del servizio, ed è
--      l'eccezione a V4 dichiarata qui sotto (§4).
--
-- **Rapporto con V4.** `report`, `chat_interazione_log`, `sessione`, `credenziale_servizio` NON
-- sono tabelle di dominio: sono output di flusso e contabilità (stessa natura di `flusso_run` e di
-- `messaggio`). La regola «il dominio si scrive solo via proposta» resta intatta su
-- luogo/scheda_servizio/evento/opportunita/casa — `pa` non ha alcun privilegio su di esse.
--
-- Idempotente: rieseguibile senza errori.
\set ON_ERROR_STOP on
\set VERBOSITY terse

-- Niente `SET ROLE trasi_owner` qui: `apply.sh` esegue come amministratore del container (che
-- impersona trasi_owner dove serve). L'ALTER FUNCTION ... OWNER TO applicatore richiede che
-- chi esegue possa assumere il ruolo `applicatore` — `trasi_owner` non è membro di `applicatore`
-- (db/000), e le function di transizione devono restare di `applicatore` (come in 006 §11).
SET search_path = trasi, public, pg_temp;

-- ---------------------------------------------------------------------------
-- 0. Precondizioni
-- ---------------------------------------------------------------------------
DO $pre$
DECLARE v_missing text;
BEGIN
  SELECT string_agg(x, ', ') INTO v_missing
    FROM unnest(ARRAY['trasi.casa','trasi.richiesta','trasi.report','trasi.sessione',
                      'trasi.tentativo_login','trasi.audit','trasi.parametro']) x
   WHERE to_regclass(x) IS NULL;
  IF v_missing IS NOT NULL THEN
    RAISE EXCEPTION '026_report_pa: mancano % — applica prima db/000–025', v_missing;
  END IF;
  IF to_regprocedure('trasi.k_anon(bigint)') IS NULL OR to_regprocedure('trasi.casa_corrente()') IS NULL THEN
    RAISE EXCEPTION '026_report_pa: mancano k_anon()/casa_corrente() — applica prima db/000–020';
  END IF;
  -- crypt()/gen_salt() arrivano da pgcrypto (db/013), nel search_path public.
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pgcrypto') THEN
    RAISE EXCEPTION '026_report_pa: manca pgcrypto — applica prima db/013_credenziali.sql';
  END IF;
  -- Il ruolo `pa` è creato da db/000 (i ruoli stanno là, e il canale PA non è un'eccezione).
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pa') THEN
    RAISE EXCEPTION '026_report_pa: ruolo pa assente — applica prima db/000_roles.sql';
  END IF;
  -- audit.entita/entita_id sono colonne aggiunte da db/005: le funzioni di transizione (§2)
  -- registrano l'oggetto della decisione, e senza queste colonne non potrebbero.
END
$pre$;

-- ---------------------------------------------------------------------------
-- 1. `report`: stato HITL e aggregato di rete senza Casa
-- ---------------------------------------------------------------------------
-- **Perché `casa_id` diventa nullable.** Nella 024 il report osservatorio era appeso a una Casa
-- arbitraria (`UNIQUE (casa_id, mese, ambito)` lo imponeva) — un'incrostazione del modello che
-- confondeva il rendiconto di una Casa con l'aggregato di rete. L'osservatorio non è di nessuna
-- Casa: `ambito='osservatorio' ⟺ casa_id IS NULL`, vincolato da un CHECK e non da una convenzione.
ALTER TABLE trasi.report ALTER COLUMN casa_id DROP NOT NULL;

ALTER TABLE trasi.report ADD COLUMN IF NOT EXISTS stato         text NOT NULL DEFAULT 'bozza';
ALTER TABLE trasi.report ADD COLUMN IF NOT EXISTS approvato_da  text;
ALTER TABLE trasi.report ADD COLUMN IF NOT EXISTS approvato_ts  timestamptz;
ALTER TABLE trasi.report ADD COLUMN IF NOT EXISTS inviato_pa_ts timestamptz;

-- Il vocabolario di stato è chiuso ed è la macchina delle decisioni: 'bozza' lo legge solo chi
-- deve decidere (rete/ti), 'approvato' apre la lettura a `pa`, 'inviato_pa' chiude il ciclo.
ALTER TABLE trasi.report DROP CONSTRAINT IF EXISTS report_stato_check;
ALTER TABLE trasi.report ADD CONSTRAINT report_stato_check
  CHECK (stato IN ('bozza','approvato','inviato_pa'));

-- coerenza di ambito: rendiconto di Casa ⟺ casa assegnata; osservatorio ⟺ nessuna Casa.
ALTER TABLE trasi.report DROP CONSTRAINT IF EXISTS report_ambito_casa_ck;
ALTER TABLE trasi.report ADD CONSTRAINT report_ambito_casa_ck
  CHECK ((ambito = 'osservatorio') = (casa_id IS NULL));

-- Unicità: la vecchia chiave (casa_id, mese, ambito) non funziona più con casa_id NULL
-- (NULL non confligge). Due indici parziali dichiarano la chiave naturale nei due mondi.
ALTER TABLE trasi.report DROP CONSTRAINT IF EXISTS report_casa_id_mese_ambito_key;
CREATE UNIQUE INDEX IF NOT EXISTS report_casa_mese_ambito_uq
  ON trasi.report (casa_id, mese, ambito) WHERE casa_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS report_osservatorio_mese_uq
  ON trasi.report (mese, ambito) WHERE ambito = 'osservatorio';

COMMENT ON COLUMN trasi.report.stato IS
  'Stato HITL (US-4): bozza → approvato (rete/ti, funzione approva_report) → inviato_pa '
  '(la notifica, funzione marca_report_inviato). Mai UPDATE diretto: il privilegio non esiste.';
COMMENT ON COLUMN trasi.report.approvato_da IS
  'Ruolo che ha approvato (lo scrive approva_report = current_user): nessuno si firma da solo.';

-- ---------------------------------------------------------------------------
-- 2. Le funzioni di transizione — chi decide e chi notifica
-- ---------------------------------------------------------------------------
-- Owner `applicatore`, SECURITY DEFINER, come tutte le scritture mediate (db/006): l'UPDATE su
-- `report` non è concesso a NESSUN ruolo (la regola di Processi della 024 — «non si corregge»),
-- quindi l'unico modo per far vivere la macchina a stati è una funzione con l'audit a bordo.
-- **Non è una violazione della regola**: è la sua espressione per lo stato — la funzione non
-- riscrive i contenuti (che restano intoccabili), cambia solo `stato`, e solo nella direzione
-- ammessa. Chi la chiama deve avere EXECUTE (rete/ti per approvare; automazioni/ti per marcare
-- l'invio): `pa` non è nell'elenco, e non potrà mai auto-approvare ciò che legge.

CREATE OR REPLACE FUNCTION trasi.approva_report(p_id bigint) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = trasi, pg_catalog
AS $fn$
DECLARE
  v_report trasi.report%ROWTYPE;
BEGIN
  SELECT * INTO v_report FROM trasi.report r WHERE r.id = p_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'report % inesistente', p_id USING ERRCODE = 'P0001';
  END IF;
  -- Solo dalla bozza: approvare un report già deciso è una riscrittura della decisione.
  IF v_report.stato <> 'bozza' THEN
    RAISE EXCEPTION 'report % in stato %: si approva solo da bozza', p_id, v_report.stato
      USING ERRCODE = 'P0001';
  END IF;
  UPDATE trasi.report
     SET stato = 'approvato', approvato_da = current_user::text, approvato_ts = now()
   WHERE id = p_id;
  INSERT INTO trasi.audit (azione, eseguito_da, entita, entita_id, prima, dopo)
  VALUES ('report_approvato', session_user, 'report', p_id,
          jsonb_build_object('stato', 'bozza'),
          jsonb_build_object('stato', 'approvato', 'approvato_da', current_user::text,
                             'mese', v_report.mese, 'ambito', v_report.ambito));
  RETURN true;
END;
$fn$;

CREATE OR REPLACE FUNCTION trasi.marca_report_inviato(p_id bigint) RETURNS boolean
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = trasi, pg_catalog
AS $fn$
DECLARE
  v_report trasi.report%ROWTYPE;
BEGIN
  SELECT * INTO v_report FROM trasi.report r WHERE r.id = p_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'report % inesistente', p_id USING ERRCODE = 'P0001';
  END IF;
  -- Solo da approvato: il flusso notturno non notifica una bozza (V6: l'umano decide prima).
  IF v_report.stato <> 'approvato' THEN
    RAISE EXCEPTION 'report % in stato %: si marca inviato solo da approvato', p_id, v_report.stato
      USING ERRCODE = 'P0001';
  END IF;
  UPDATE trasi.report SET stato = 'inviato_pa', inviato_pa_ts = now() WHERE id = p_id;
  INSERT INTO trasi.audit (azione, eseguito_da, entita, entita_id, prima, dopo)
  VALUES ('report_inviato_pa', session_user, 'report', p_id,
          jsonb_build_object('stato', 'approvato'),
          jsonb_build_object('stato', 'inviato_pa', 'inviato_pa_ts', now(),
                             'mese', v_report.mese, 'ambito', v_report.ambito));
  RETURN true;
END;
$fn$;

-- Le funzioni sono SECURITY DEFINER owner `applicatore`, e `applicatore` è l'unico ruolo con
-- UPDATE su `report`: **non ai ruoli applicativi** (la regola di Processi resta intatta — il
-- report non si corregge a mano), ma al ruolo di macchina che incarna le transizioni dichiarate.
-- È la stessa architettura di `applica_proposte_approvate` / `conferma_movimento` (db/005-006):
-- la scrittura non avviene per GRANT diretto all'applicazione, ma per delega a una funzione che
-- ha l' audit a bordo e controlla la transizione.
GRANT UPDATE ON trasi.report TO applicatore;
-- `report` è FORCE RLS e la policy `rep_sel` non include applicatore: con una SECURITY DEFINER
-- la funzione gira come applicatore e non vedrebbe la riga (FOR UPDATE → 0 righe → 'inesistente').
-- `appl_all` è la policy che la 005 riserva al ruolo di macchina sul dominio; qui serve uguale.
DROP POLICY IF EXISTS appl_all ON trasi.report;
CREATE POLICY appl_all ON trasi.report FOR ALL TO applicatore USING (true) WITH CHECK (true);
ALTER FUNCTION trasi.approva_report(bigint)          OWNER TO applicatore;
ALTER FUNCTION trasi.marca_report_inviato(bigint)    OWNER TO applicatore;
REVOKE ALL ON FUNCTION trasi.approva_report(bigint)       FROM PUBLIC;
REVOKE ALL ON FUNCTION trasi.marca_report_inviato(bigint) FROM PUBLIC;
-- EXECUTE esplicito, e solo dove serve: `pa` (e shim_rw) non lo ricevono.
GRANT EXECUTE ON FUNCTION trasi.approva_report(bigint)       TO rete, ti, applicatore;
GRANT EXECUTE ON FUNCTION trasi.marca_report_inviato(bigint) TO automazioni, ti, applicatore;
REVOKE EXECUTE ON FUNCTION trasi.approva_report(bigint)
  FROM shim_rw, pa, metabase_ro, automazioni,
       casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
       casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano;
REVOKE EXECUTE ON FUNCTION trasi.marca_report_inviato(bigint)
  FROM shim_rw, pa, metabase_ro, rete,
       casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
       casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano;

-- ---------------------------------------------------------------------------
-- 3. Il canale PA: credenziali, sessioni di servizio, login
-- ---------------------------------------------------------------------------
-- **Perché una tabella a parte e non `credenziale_casa`.** `credenziale_casa` ha `casa_id` come
-- PK e la PA non è una Casa: allargarla a un tipo generico avrebbe allentato il vincolo più
-- utile («una credenziale ⟺ una Casa»). Qui il vocabolario è chiuso sui due ruoli di servizio
-- ('rete', 'pa'): il referente che approva usa lo stesso login (ruolo 'rete') da pa.html.
CREATE TABLE IF NOT EXISTS trasi.credenziale_servizio (
  ruolo         text PRIMARY KEY CHECK (ruolo IN ('rete','pa')),
  pass_hash     text NOT NULL,
  aggiornato_ts timestamptz NOT NULL DEFAULT now(),
  aggiornato_da text NOT NULL DEFAULT 'seed'
);
COMMENT ON TABLE trasi.credenziale_servizio IS
  'Credenziali dei canali di servizio (US-4: rete e pa per la dashboard di monitoraggio). '
  'bcrypt in pass_hash; la rotazione è UPDATE pass_hash da ti, come credenziale_casa.';

-- Le tabelle create da questo file DEVONO essere di `trasi_owner`, così `db/002_rls.sql` (che fa
-- `GRANT … ON ALL SEQUENCES IN SCHEMA trasi` come `trasi_owner`) non fallisce su un oggetto che
-- non possiede. Senza questa riga l'owner è chi esegue lo script (postgres), e ogni apply.sh
-- successivo di qualunque sessione muore con `permission denied for sequence …`.
ALTER TABLE trasi.credenziale_servizio OWNER TO trasi_owner;

-- SECURITY DEFINER: anche da questa tabella applicatore deve poter leggere (RLS FORCE, come su
-- `credenziale_casa` in db/013) per la verifica bcrypt. SELECT soltanto: la rotazione è di `ti`.
ALTER TABLE trasi.credenziale_servizio ENABLE ROW LEVEL SECURITY;
ALTER TABLE trasi.credenziale_servizio FORCE  ROW LEVEL SECURITY;
DROP POLICY IF EXISTS owner_all ON trasi.credenziale_servizio;
CREATE POLICY owner_all ON trasi.credenziale_servizio FOR ALL TO trasi_owner USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS appl_all ON trasi.credenziale_servizio;
CREATE POLICY appl_all ON trasi.credenziale_servizio FOR ALL TO applicatore USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS credserv_sel_ti ON trasi.credenziale_servizio;
CREATE POLICY credserv_sel_ti ON trasi.credenziale_servizio FOR SELECT TO ti USING (true);
DROP POLICY IF EXISTS credserv_upd_ti ON trasi.credenziale_servizio;
CREATE POLICY credserv_upd_ti ON trasi.credenziale_servizio FOR UPDATE TO ti USING (true) WITH CHECK (true);

REVOKE ALL ON trasi.credenziale_servizio FROM PUBLIC;
GRANT SELECT ON trasi.credenziale_servizio TO ti, applicatore;
GRANT UPDATE (pass_hash) ON trasi.credenziale_servizio TO ti;

-- Password iniziali DOCUMENTATE (da cambiare subito, runbook): rete2026! / pa2026!.
-- Solo righe mancanti: una password già ruotata non torna mai al valore iniziale (stessa regola
-- della 013 — l'idempotenza non cancella il lavoro umano).
INSERT INTO trasi.credenziale_servizio (ruolo, pass_hash)
SELECT v.ruolo, public.crypt(v.pass, public.gen_salt('bf'))
  FROM (VALUES ('rete','rete2026!'), ('pa','pa2026!')) AS v(ruolo, pass)
 WHERE NOT EXISTS (SELECT 1 FROM trasi.credenziale_servizio cs WHERE cs.ruolo = v.ruolo);

-- `sessione`: ospita anche le sessioni di servizio. La regola XOR è il cuore del disegno:
-- una riga è una sessione di Casa (casa_id, ruolo_db NULL) **oppure** di servizio (ruolo_db,
-- casa_id NULL), mai le due cose né nessuna. Così la validazione non può confondere i canali.
ALTER TABLE trasi.sessione ALTER COLUMN casa_id DROP NOT NULL;
ALTER TABLE trasi.sessione ADD COLUMN IF NOT EXISTS ruolo_db text;

ALTER TABLE trasi.sessione DROP CONSTRAINT IF EXISTS sessione_casa_ruolo_ck;
ALTER TABLE trasi.sessione ADD CONSTRAINT sessione_casa_ruolo_ck
  CHECK ((casa_id IS NULL) = (ruolo_db IS NOT NULL));

COMMENT ON COLUMN trasi.sessione.ruolo_db IS
  'Ruolo di servizio (''rete''/''pa'') per le sessioni della dashboard PA; NULL nelle sessioni Casa. '
  'XOR con casa_id: i due canali non si mescolano.';

-- `crea_sessione_servizio(p_ruolo, p_pass)` → uuid | NULL
-- Speculare a `crea_sessione` (db/006 §11a): stessa verifica bcrypt lato DB, stesso anti
-- brute-force (>4 fallimenti/10 min → NULL + audit 'login_bloccato'), stesso 401 indistinto
-- (ruolo sconosciuto e password errata danno lo stesso NULL). I tentativi vivono nella tabella
-- esistente `tentativo_login` con `casa_id = NULL` per i ruoli di servizio (la colonna era NOT
-- NULL FK su casa: qui diventa nullable — NULL è «nessuna Casa», che è esattamente il servizio).
ALTER TABLE trasi.tentativo_login ALTER COLUMN casa_id DROP NOT NULL;

CREATE OR REPLACE FUNCTION trasi.crea_sessione_servizio(p_ruolo text, p_pass text)
RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = trasi, public, pg_catalog
AS $fn$
DECLARE
  v_hash       text;
  v_fallimenti int;
  v_token      uuid;
  v_ttl        interval;
BEGIN
  -- Ruolo fuori vocabolario: stesso NULL della password errata (401 indistinto all'endpoint).
  IF p_ruolo IS NULL OR p_ruolo NOT IN ('rete','pa') OR p_pass IS NULL THEN
    RETURN NULL;
  END IF;

  SELECT cs.pass_hash INTO v_hash FROM trasi.credenziale_servizio cs WHERE cs.ruolo = p_ruolo;
  IF v_hash IS NULL THEN
    RETURN NULL;
  END IF;

  SELECT count(*) INTO v_fallimenti
    FROM trasi.tentativo_login t
   WHERE t.casa_id IS NULL AND t.ruolo_db = p_ruolo
     AND t.ts > now() - interval '10 minutes';

  IF v_fallimenti > 4 THEN
    INSERT INTO trasi.audit (azione, eseguito_da, entita, dopo)
    VALUES ('login_bloccato', session_user, 'sessione',
            jsonb_build_object('ruolo_db', p_ruolo, 'fallimenti_10min', v_fallimenti));
    RETURN NULL;
  END IF;

  IF crypt(p_pass, v_hash) <> v_hash THEN
    INSERT INTO trasi.tentativo_login (casa_id, ruolo_db) VALUES (NULL, p_ruolo);
    INSERT INTO trasi.audit (azione, eseguito_da, entita, dopo)
    VALUES ('login_fallito', session_user, 'sessione',
            jsonb_build_object('ruolo_db', p_ruolo));
    RETURN NULL;
  END IF;

  v_ttl := make_interval(hours => COALESCE(trasi.p_int('session_ttl_hours'), 12));
  DELETE FROM trasi.tentativo_login t WHERE t.casa_id IS NULL AND t.ruolo_db = p_ruolo;
  INSERT INTO trasi.sessione (casa_id, ruolo_db, scade_ts)
  VALUES (NULL, p_ruolo, now() + v_ttl)
  RETURNING token INTO v_token;

  INSERT INTO trasi.audit (azione, eseguito_da, entita, dopo)
  VALUES ('login', session_user, 'sessione',
          jsonb_build_object('ruolo_db', p_ruolo, 'scade_ts', now() + v_ttl));
  RETURN v_token;
END;
$fn$;

ALTER FUNCTION trasi.crea_sessione_servizio(text, text) OWNER TO applicatore;
REVOKE ALL ON FUNCTION trasi.crea_sessione_servizio(text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION trasi.crea_sessione_servizio(text, text) TO shim_rw, applicatore, automazioni;

-- tentativo_login.ruolo_db: la colonna che distingue il canale nei fallimenti.
ALTER TABLE trasi.tentativo_login ADD COLUMN IF NOT EXISTS ruolo_db text;

-- ---------------------------------------------------------------------------
-- 4. `chat_interazione_log` — contabilità della chat, senza il testo (V5)
-- ---------------------------------------------------------------------------
-- **Eccezione dichiarata a V4, della stessa famiglia di `messaggio` (db/015)** e della
-- registrazione di `richiesta` (db/006 §11b): questa tabella è un **log**, non dominio — la
-- contabilità di quante volte l'assistente ha risposto, da dove ha preso la risposta (KB o
-- fonte esterna) e se è andata bene. NON c'è testo: V5 vieta di persistere le chat, e un log
-- che conservasse i messaggi sarebbe una chat con un altro nome. Ciò che serve alla qualità del
-- servizio è la **distribuzione** («quante domande senza risposta KB»), non il contenuto.
--
-- `casa_id` NULL = canale PA: la PA non ha Casa, e la RLS tiene i due canali distinguibili senza
-- mescolarli. La policy INSERT per `pa` ammette solo `casa_id IS NULL`; per i ruoli Casa solo la
-- propria Casa — come `msg_ins_casa` e `rich_ins_casa`, la scrittura è sempre dalla propria
-- identità, mai dal corpo della richiesta (principio 3).
CREATE TABLE IF NOT EXISTS trasi.chat_interazione_log (
  id       bigserial PRIMARY KEY,
  casa_id  integer REFERENCES trasi.casa(id),
  canale   text NOT NULL CHECK (canale IN ('sportello','pa')),
  esito    text NOT NULL CHECK (esito IN ('risposta','errore')),
  fonte    text          CHECK (fonte IN ('kb','esterna','nessuna')),
  ts       timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE trasi.chat_interazione_log IS
  'Contabilità delle interazioni con l''assistente (US-4, V5): esito e fonte, MAI il testo. '
  'canale=sportello per la chat dello sportello (casa_id), canale=pa per la dashboard PA (casa_id NULL). '
  'Eccezione dichiarata a V4: log, non dominio (stessa famiglia di messaggio e richiesta).';
COMMENT ON COLUMN trasi.chat_interazione_log.fonte IS
  'kb = risposta dalla knowledge base di rete; esterna = fonte esterna interrogata a runtime; '
  'nessuna = nessuna fonte (esito=errore o risposta di mancato reperimento).';

CREATE INDEX IF NOT EXISTS chat_log_casa_ts_idx ON trasi.chat_interazione_log (casa_id, ts);
-- Le tabelle create da questo file DEVONO essere di `trasi_owner`, così `db/002_rls.sql` non muore
-- su `permission denied for sequence` (vedi sopra, stessa regola per credenziale_servizio).
ALTER TABLE trasi.chat_interazione_log OWNER TO trasi_owner;
-- Le letture della dashboard filtrano per mese/canale: `date_trunc` su timestamptz è STABLE e
-- non IMMUTABLE (dipende dalla timezone), quindi non può stare in un indice. La vista si
-- appoggia al filtro su `ts`, che l'indice copre già.

ALTER TABLE trasi.chat_interazione_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE trasi.chat_interazione_log FORCE  ROW LEVEL SECURITY;

DROP POLICY IF EXISTS chatlog_sel ON trasi.chat_interazione_log;
DROP POLICY IF EXISTS chatlog_ins_casa ON trasi.chat_interazione_log;
DROP POLICY IF EXISTS chatlog_ins_pa ON trasi.chat_interazione_log;
DROP POLICY IF EXISTS chatlog_sel_readers ON trasi.chat_interazione_log;

-- Lettura: ogni Casa vede il proprio canale sportello; rete/ti/pa vedono tutto (l'aggregato è
-- già k-anonimo nelle viste, ma qui le righe sono singole — la distinzione canale='pa' è ciò che
-- serve; la mascheratura sta nelle VISTE, non nella tabella).
CREATE POLICY chatlog_sel_readers ON trasi.chat_interazione_log
  FOR SELECT
  USING (casa_id = trasi.casa_corrente() OR current_user IN ('rete','ti','pa'));

-- INSERT: i ruoli Casa solo sul proprio sportello; `pa` solo sul proprio canale (casa_id NULL).
-- Nessun UPDATE, nessun DELETE per i ruoli di scrittura: il log si accoda, non si corregge.
CREATE POLICY chatlog_ins_casa ON trasi.chat_interazione_log
  FOR INSERT TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
                casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano
  WITH CHECK (casa_id = trasi.casa_corrente() AND canale = 'sportello');

CREATE POLICY chatlog_ins_pa ON trasi.chat_interazione_log
  FOR INSERT TO pa
  WITH CHECK (casa_id IS NULL AND canale = 'pa');

-- Automazioni e applicatore: il log lo scrive anche il flusso (per la chat dello sportello via
-- shim, `shim_rw` impersona la Casa — come ogni altra via). `applicatore` serve per il passo di
-- retention futuro e per le SECURITY DEFINER.
DROP POLICY IF EXISTS appl_all ON trasi.chat_interazione_log;
CREATE POLICY appl_all ON trasi.chat_interazione_log
  FOR ALL TO applicatore USING (true) WITH CHECK (true);

REVOKE ALL ON trasi.chat_interazione_log FROM PUBLIC;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON trasi.chat_interazione_log
  FROM shim_rw, automazioni, metabase_ro, rete, ti,
       casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
       casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano;
GRANT SELECT ON trasi.chat_interazione_log TO
  casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
  casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano,
  rete, ti, pa, metabase_ro, automazioni, shim_rw, applicatore;
GRANT INSERT (casa_id, canale, esito, fonte) ON trasi.chat_interazione_log TO
  casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
  casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano, pa, shim_rw, applicatore;
GRANT USAGE, SELECT ON SEQUENCE trasi.chat_interazione_log_id_seq TO
  casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
  casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano, pa, shim_rw, applicatore;
-- `shim_rw` serve perché lo shim scrive il log dello sportello DURANTE la chiamata Onyx
-- (`chat/op` → proxy → INSERT log best-effort), con il ruolo della Casa già assunto; la policy
-- RLS fa il resto. `pa` scrive il proprio canale via `POST /pa/chat`.

-- ---------------------------------------------------------------------------
-- 5. Le viste k-anonime del report PA (security_invoker = false)
-- ---------------------------------------------------------------------------
-- Come le viste di reporting di db/004 (`v_report_mensile`, `v_confronto_case`): girano come
-- owner (`trasi_owner`) perché `pa`/`metabase_ro` NON hanno SELECT su `richiesta` né su
-- `chat_interazione_log`, e l'aggregato deve poterli leggere senza concederglieli in chiaro.
-- L'intento non è aggirato, come nella 004: tutto ciò che esce è k-anonimo (`k_anon()`), e il
-- numero grezzo sotto soglia non esiste nella vista — c'è solo l'etichetta (`'<5'`, `'—'`).

-- v_report_fasce — richieste del mese per fascia oraria, per Casa.
-- Le fasce sono dichiarate: mattina 6-13, pomeriggio 13-19, sera 19-24, notte 0-6
-- (mezzanotte esatta finisce in «sera»: extract('hour') la colloca a 0, e la fascia «notte»
-- copre 0-6 — la domanda «quando le persone cercano Trasi» non ha bisogno di un caso limite).
DROP VIEW IF EXISTS trasi.v_report_fasce;
CREATE VIEW trasi.v_report_fasce AS
SELECT mm.mese,
       c.slug AS casa_slug, fx.fascia_oraria,
       a.n, a.n_label
FROM (
  SELECT date_trunc('month', r.ts)::date AS mese,
         r.casa_id,
         CASE WHEN extract(hour FROM r.ts) BETWEEN 6  AND 12 THEN 'mattina'
              WHEN extract(hour FROM r.ts) BETWEEN 13 AND 18 THEN 'pomeriggio'
              WHEN extract(hour FROM r.ts) BETWEEN 19 AND 23 THEN 'sera'
              ELSE 'notte' END AS fascia_oraria,
         count(*) AS cnt
  FROM trasi.richiesta r
  GROUP BY date_trunc('month', r.ts)::date, r.casa_id, fascia_oraria
) fx
JOIN LATERAL (SELECT DISTINCT date_trunc('month', ts)::date AS mese, casa_id
              FROM trasi.richiesta) mm ON mm.mese = fx.mese AND mm.casa_id = fx.casa_id
JOIN trasi.casa c ON c.id = fx.casa_id
CROSS JOIN LATERAL trasi.k_anon(fx.cnt) a;

-- v_report_confronto — mese corrente vs mese precedente, a livello RETE (somma delle Case).
-- **Perché a livello rete**: il confronto della PA riguarda l'andamento complessivo del
-- servizio, non la Casa singola — e aggregare PRIMA del k-anonimato è la regola corretta
-- (sommare i conteggi e poi mascherare dà un numero che rappresenta davvero la rete, a
-- differenza della somma di molti `<5`). delta_pct è NULL sotto soglia: una variazione su dati
-- mascherati non si mostra, perché non si sa.
DROP VIEW IF EXISTS trasi.v_report_confronto;
CREATE VIEW trasi.v_report_confronto AS
WITH mesi AS (
  SELECT DISTINCT date_trunc('month', ts)::date AS mese FROM trasi.richiesta
), agg AS (
  SELECT date_trunc('month', r.ts)::date AS mese,
         r.categoria, r.esito,
         count(*) AS cnt
  FROM trasi.richiesta r
  GROUP BY 1, 2, 3
)
SELECT m.mese,
       a.categoria, a.esito,
       ka.n, ka.n_label,
       kp.n AS n_prec, kp.n_label AS n_prec_label,
       CASE WHEN a.cnt >= COALESCE(trasi.p_int('k_anonimato'), 5)
                 AND p.cnt >= COALESCE(trasi.p_int('k_anonimato'), 5)
            THEN round(((a.cnt - p.cnt)::numeric / p.cnt) * 100, 1)
       END AS delta_pct
FROM mesi m
JOIN agg a ON a.mese = m.mese
LEFT JOIN agg p ON p.mese = (m.mese - interval '1 month')::date
               AND p.categoria = a.categoria AND p.esito = a.esito
CROSS JOIN LATERAL trasi.k_anon(a.cnt) ka
CROSS JOIN LATERAL trasi.k_anon(COALESCE(p.cnt, 0)) kp;

-- v_chat_mensile — conteggi del log delle chat per mese, Casa, canale, esito, fonte.
-- Il log non ha testo (§4): qui esce solo il conteggio, k-anonimo come ogni conteggio di
-- persone. È la base della sezione «lacune» della dashboard: «nessuna» come fonte = la KB non
-- ha risposto → il dato da migliorare.
DROP VIEW IF EXISTS trasi.v_chat_mensile;
CREATE VIEW trasi.v_chat_mensile AS
SELECT g.mese,
       c.slug AS casa_slug,
       g.canale, g.esito, g.fonte,
       a.n, a.n_label
FROM (
  SELECT date_trunc('month', l.ts)::date AS mese,
         l.casa_id, l.canale, l.esito, COALESCE(l.fonte, 'nessuna') AS fonte,
         count(*) AS cnt
  FROM trasi.chat_interazione_log l
  GROUP BY 1, 2, 3, 4, 5
) g
LEFT JOIN trasi.casa c ON c.id = g.casa_id
CROSS JOIN LATERAL trasi.k_anon(g.cnt) a;

-- v_report_da_notificare — i report di osservatorio approvati non ancora inviati alla PA.
-- È la coda del flusso notturno (`flussi/alert.py`): da qui il passo sa che c'è un report
-- approvato da comunicare. `ambito='osservatorio'` perché sono i report **di rete** quelli che
-- la PA riceve; le bozze di Casa restano alla Casa.
DROP VIEW IF EXISTS trasi.v_report_da_notificare;
CREATE VIEW trasi.v_report_da_notificare AS
SELECT r.id, r.mese, r.approvato_ts
FROM trasi.report r
WHERE r.ambito = 'osservatorio' AND r.stato = 'approvato' AND r.inviato_pa_ts IS NULL;

-- v_report: estesa alle colonne di stato di questa migrazione — la dashboard PA le mostra
-- (stato, chi ha approvato e quando), e `v_report` è la superficie unica di lettura delle righe.
DROP VIEW IF EXISTS trasi.v_report;
CREATE VIEW trasi.v_report AS
SELECT r.id, r.casa_id, c.slug AS casa_slug, c.nome AS casa_nome,
       r.mese, r.ambito, r.contenuti, r.generato_ts, r.generato_da,
       r.stato, r.approvato_da, r.approvato_ts, r.inviato_pa_ts, r.csv,
       (r.csv IS NOT NULL) AS ha_csv,
       (SELECT count(*) FROM trasi.commento cm
         WHERE cm.entita = 'report' AND cm.entita_id = r.id) AS commenti,
       (SELECT max(cm.ts) FROM trasi.commento cm
         WHERE cm.entita = 'report' AND cm.entita_id = r.id) AS ultimo_commento_ts
FROM trasi.report r
-- LEFT JOIN: il report osservatorio non ha una Casa (CHECK osservatorio ⟺ casa_id IS NULL), e con un
-- JOIN interno scomparirebbe dalla dashboard PA — che è la sua superficie. Casa = NULL, e il nome/slug
-- sono quelli dichiarati NULL di una riga «rete».
LEFT JOIN trasi.casa c ON c.id = r.casa_id;
ALTER VIEW trasi.v_report SET (security_invoker = true);
GRANT SELECT ON trasi.v_report TO
  casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
  casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano,
  rete, ti, pa, metabase_ro, automazioni, shim_rw, applicatore;

ALTER VIEW trasi.v_report_fasce          SET (security_invoker = false);
ALTER VIEW trasi.v_report_confronto      SET (security_invoker = false);
ALTER VIEW trasi.v_chat_mensile          SET (security_invoker = false);
ALTER VIEW trasi.v_report_da_notificare  SET (security_invoker = false);

GRANT SELECT ON trasi.v_report_fasce, trasi.v_report_confronto,
                trasi.v_chat_mensile, trasi.v_report_da_notificare
  TO pa, rete, ti, metabase_ro, automazioni, shim_rw, applicatore;

-- ---------------------------------------------------------------------------
-- 6. Policy `rep_sel`: `pa` legge solo ciò che è pronto per la PA
-- ---------------------------------------------------------------------------
-- La 024 dichiarava «il report di una Casa lo legge quella Casa; rete/ti tutto». Il canale PA
-- apre una terza via, e la regola si precisa: **`pa` legge solo i report di osservatorio in
-- stato 'approvato' o 'inviato_pa'** — mai una bozza (la bozza è dell'umano che decide, V6),
-- mai il rendiconto di una Casa (che è della Casa). `automazioni` resta nel gruppo rete/ti: il
-- ciclo mensile deve poter rileggere la bozza che ha generato per non duplicarla (idempotenza:
-- SELECT preventiva, mai ON CONFLICT DO UPDATE), e la SELECT su `report` non tocca i contenuti —
-- li legge chi li aveva già scritti.
-- Prerequisito della policy: `casa_corrente()` legge `ruolo_casa`, quindi `pa` deve poter
-- risolvere la PROPRIA riga (altrimenti ogni policy che la chiama fallirebbe con
-- «permission denied for table ruolo_casa», già misurato in db/002 sui ruoli Casa). La policy
-- è selettiva e idempotente: non allarga `rc_sel_self` della 002 né tocca gli altri ruoli.
DROP POLICY IF EXISTS rc_sel_pa ON trasi.ruolo_casa;
CREATE POLICY rc_sel_pa ON trasi.ruolo_casa FOR SELECT TO pa USING (ruolo = 'pa');
GRANT SELECT (ruolo, casa_id, descrizione) ON trasi.ruolo_casa TO pa;
-- `v_report` è security_invoker=true e fa JOIN con `trasa` per nome/slug: senza GRANT su `casa`
-- la vista fallirebbe con «permission denied for table casa» appena `pa` la legge (misurato).
-- Concedo le sole colonne che la vista espone; la RLS di `casa` (non FORCE per la lettura dei
-- dati pubblici della rete) lascia i dati anagrafici accessibili, che è l'intento («tutti leggono
-- tutto»), e il confine privacy sta nei conteggi k-anonimi, non nella sede della Casa.
GRANT SELECT (id, slug, nome) ON trasi.casa TO pa;
-- `v_report` conta i commenti in sub-select: senza GRANT su `commento` la vista fallisce con
-- «permission denied for table commento» per `pa` (misurato). I commenti sono leggibili a tutta la
-- rete (policy com_sel USING(true), db/024): qui si aggiunge solo il privilegio mancante.
GRANT SELECT ON trasi.commento TO pa;
GRANT SELECT ON trasi.v_commento TO pa;
-- Le viste aggregate chiamano k_anon → p_int, che leggono `parametro`: senza questo GRANT ogni
-- vista k-anonima fallirebbe per `pa` con «permission denied for table parametro» (misurato).
GRANT SELECT ON trasi.parametro TO pa;
-- La policy decide le RIGHE, il GRANT concede l'OPERAZIONE: servono entrambi (la 024 concedeva
-- SELECT report alle Case/rete/ti; `pa` è nato dopo e va dichiarato qui, nel suo file).
GRANT SELECT ON trasi.report TO pa;

DROP POLICY IF EXISTS rep_sel ON trasi.report;
CREATE POLICY rep_sel ON trasi.report
  FOR SELECT
  USING (
    casa_id = trasi.casa_corrente()
    -- `automazioni` legge come rete/ti: il ciclo mensile deve riconoscere la propria bozza prima
    -- di re-inserirla (idempotenza dichiarata in db/024, non ON CONFLICT DO UPDATE).
    OR current_user IN ('rete', 'ti', 'automazioni')
    -- `pa`: solo ciò che è pronto per la PA. La bozza resta di chi decide (V6); il rendiconto di
    -- Casa resta della Casa.
    OR (current_user = 'pa' AND ambito = 'osservatorio' AND stato IN ('approvato','inviato_pa'))
  );

-- ---------------------------------------------------------------------------
-- 7. Verifica di installazione — le regole del canale PA, provate qui
-- ---------------------------------------------------------------------------
DO $verify$
DECLARE
  v_priv text;
  v_n    int;
BEGIN
  -- La regola di Processi resta intera: nessuno ha UPDATE su report. Le funzioni di transizione
  -- sono SECURITY DEFINER owner applicatore — il privilegio assente non cambia.
  SELECT string_agg(DISTINCT grantee || ':' || privilege_type, ', ') INTO v_priv
    FROM information_schema.role_table_grants
   WHERE table_schema = 'trasi' AND table_name = 'report'
     AND privilege_type IN ('UPDATE','DELETE')
     AND grantee IN ('casa_santaspazio','casa_molo12','casa_erranti','casa_buscicchio','casa_sanbao',
                     'casa_minimus','casa_pop','casa_bozzano','casa_dream','casa_tuturano',
                     'rete','ti','pa','shim_rw','automazioni');
  IF v_priv IS NOT NULL THEN
    RAISE EXCEPTION '026_report_pa: ruoli con UPDATE/DELETE su report: %', v_priv;
  END IF;

  -- Le due policy di scrittura sull'eccezione chat_interazione_log devono essere le sole.
  SELECT count(*) INTO v_n FROM pg_policies
   WHERE schemaname='trasi' AND tablename='chat_interazione_log' AND cmd='INSERT';
  IF v_n <> 2 THEN
    RAISE EXCEPTION '026_report_pa: attese 2 policy INSERT su chat_interazione_log, trovate %', v_n;
  END IF;

  -- Vocabolario chiuso: `pa` non è membro di metabase_ro e non è nemmeno LOGIN.
  IF EXISTS (SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.roleid
              WHERE r.rolname='metabase_ro'
                AND m.member = (SELECT oid FROM pg_roles WHERE rolname='pa')) THEN
    RAISE EXCEPTION '026_report_pa: pa è membro di metabase_ro (non deve esserlo)';
  END IF;

  -- I report osservatorio senza casa_id devono rispettare il CHECK: la prova è che lo stato
  -- default è 'bozza' e che ambio osservatorio ⟺ casa_id NULL sui seed già presenti.
  IF EXISTS (SELECT 1 FROM trasi.report WHERE (ambito='osservatorio') <> (casa_id IS NULL)) THEN
    RAISE EXCEPTION '026_report_pa: righe report incoerenti con il CHECK ambito/casa_id';
  END IF;

  RAISE NOTICE '026_report_pa applicato: report (stato/approvato_da/ts, inviato_pa_ts, osservatorio senza casa) + credenziale_servizio (rete2026!/pa2026!) + crea_sessione_servizio + chat_interazione_log + 4 viste k-anonime (fasce, confronto, chat_mensile, da_notificare)';
END
$verify$;
