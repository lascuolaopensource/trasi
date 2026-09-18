-- Trasi — db/014_attrezzoteca.sql
-- Attrezzoteca (US-5.x, Fase 0 §2): inventario condiviso delle Case + movimenti (prestiti).
--
-- Perimetro V4 (decisione Fase 0, lista chiusa in deployment/README.md; **aggiornato da db/032**):
--   * `oggetto` — nascita e modifica DIRETTE della propria Casa (D1: policy `ogg_ins_casa`/`ogg_upd_casa`
--     qui sotto + GRANT in db/032); via proposta (tipi nuovo_oggetto / modifica_oggetto /
--     ritira_oggetto in db/006, decide l'AT) per gli oggetti delle altre Case. Inventario = memoria della rete;
--   * `movimento` — evento operativo tra due Case: INSERT diretto della Casa cedente
--     (stato 'proposto'), conferma SOLO della ricevente via conferma_movimento() (db/006,
--     audit su ogni passaggio). Mai DELETE (coerente con V4 regola 7).
--
-- Vincoli applicati: RLS ENABLE+FORCE; policy con USING **e** WITH CHECK; nessun ruolo
-- con BYPASSRLS; impronta di scrittura (aggiornato_ts/aggiornato_da) via trigger generico.
--
-- Adattamento ai nomi reali (dichiarazione del contract): la colonna «chi è la Casa» è
-- `casa.slug` (text, es. 'san-bao'): i CHECK di coerenza conferma usano slug normalizzato
-- (slug ⇔ ruolo si converte sostituendo '-' con ''). Nessuna altra divergenza: `richiesta`
-- ha esattamente le colonne del contract (categoria, esito, destinazione_id, destinazione_nota).
--
-- Idempotente: rieseguibile senza errori.
\set ON_ERROR_STOP on
\set VERBOSITY terse

SET ROLE trasi_owner;
SET search_path = trasi, public, pg_temp;

-- ---------------------------------------------------------------------------
-- 1. oggetto — inventario condiviso
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trasi.oggetto (
  id            serial PRIMARY KEY,
  nome          text NOT NULL,
  descrizione   text,
  quantita      integer NOT NULL CHECK (quantita > 0),
  casa_id       integer NOT NULL REFERENCES trasi.casa(id),
  condizione    text NOT NULL DEFAULT 'integro'
                CHECK (condizione IN ('integro','danneggiato','mancante_di_parti')),
  attivo        boolean NOT NULL DEFAULT true,
  fonte_id      integer REFERENCES trasi.fonte(id),
  creato_ts     timestamptz NOT NULL DEFAULT now(),
  aggiornato_ts timestamptz,
  aggiornato_da text
);
COMMENT ON TABLE trasi.oggetto IS
  'Attrezzoteca: inventario condiviso (US-5.1). Nascita/modifica via proposta (V4, eccezioni nessuna); SELECT a tutta la rete. attivo=false = ritirato (mai DELETE).';
COMMENT ON COLUMN trasi.oggetto.quantita IS
  'Esemplari presso la Casa attuale; la disponibilità effettiva è in v_inventario (al netto dei movimenti confermati in corso).';

CREATE INDEX IF NOT EXISTS oggetto_casa_idx    ON trasi.oggetto (casa_id);
CREATE INDEX IF NOT EXISTS oggetto_attivo_idx  ON trasi.oggetto (attivo) WHERE attivo;

-- ---------------------------------------------------------------------------
-- 2. movimento — prestito da Casa a Casa, con conferma della ricevente
-- ---------------------------------------------------------------------------
-- Stati: proposto → confermato | rifiutato; confermato → rientrato.
-- La macchina a stati è nel trigger movimento_00_stato_tg: UPDATE diretto SOLO da
-- `applicatore` (conferma_movimento), che il trigger autorizza; qualunque altro UPDATE
-- è respinto con P0001 parlante (anche se un GRANT futuro lo consentisse per errore).
CREATE TABLE IF NOT EXISTS trasi.movimento (
  id                serial PRIMARY KEY,
  oggetto_id        integer NOT NULL REFERENCES trasi.oggetto(id),
  da_casa_id        integer NOT NULL REFERENCES trasi.casa(id),
  a_casa_id         integer NOT NULL REFERENCES trasi.casa(id),
  dal               date NOT NULL DEFAULT current_date,
  al                date,
  stato             text NOT NULL DEFAULT 'proposto'
                    CHECK (stato IN ('proposto','confermato','rientrato','rifiutato')),
  condizione_rientro text CHECK (condizione_rientro IS NULL OR condizione_rientro IN
                                 ('integro','danneggiato','mancante_di_parti')),
  motivazione       text CHECK (motivazione IS NULL OR char_length(motivazione) <= 80),
  ts                timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT movimento_case_distinte  CHECK (da_casa_id <> a_casa_id),
  CONSTRAINT movimento_al_dopo_dal    CHECK (al IS NULL OR al >= dal),
  CONSTRAINT movimento_rientro_chiuso CHECK (stato <> 'rientrato' OR condizione_rientro IS NOT NULL)
);
COMMENT ON TABLE trasi.movimento IS
  'Prestito tra Case (US-5.2/5.3): INSERT diretto della cedente (stato proposto, eccezione V4 documentata), conferma della ricevente via conferma_movimento(). Mai DELETE.';
COMMENT ON COLUMN trasi.movimento.condizione_rientro IS
  'Condizione registrata al rientro (US-5.3): obbligatoria quando stato=rientrato.';

CREATE INDEX IF NOT EXISTS movimento_oggetto_idx  ON trasi.movimento (oggetto_id);
CREATE INDEX IF NOT EXISTS movimento_da_casa_idx  ON trasi.movimento (da_casa_id);
CREATE INDEX IF NOT EXISTS movimento_a_casa_idx   ON trasi.movimento (a_casa_id);
CREATE INDEX IF NOT EXISTS movimento_stato_idx    ON trasi.movimento (stato);

-- Trigger macchina a stati + nota informativa (US-5.2: conflitto segnalato, mai
-- rifiutato dal sistema — la decisione resta alle due Case, V6).
CREATE OR REPLACE FUNCTION trasi.movimento_00_stato_tg() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  v_attivo  boolean;
  v_titolo  text;
BEGIN
  IF TG_OP = 'INSERT' THEN
    -- Lo stato iniziale è 'proposto' e basta: nessuno deposita un prestito già confermato.
    IF NEW.stato IS DISTINCT FROM 'proposto' THEN
      RAISE EXCEPTION 'un movimento nasce in stato ''proposto'', non ''%'': la conferma è della Casa ricevente (conferma_movimento)', NEW.stato
        USING ERRCODE = 'P0001';
    END IF;
    SELECT o.attivo INTO v_attivo FROM trasi.oggetto o WHERE o.id = NEW.oggetto_id;
    IF v_attivo IS DISTINCT FROM true THEN
      RAISE EXCEPTION 'oggetto % ritirato o inesistente: movimento non registrabile', NEW.oggetto_id
        USING ERRCODE = 'P0001';
    END IF;
    -- Conflitto doppio prenotato: si segnala (NOTICE informativo) e si accetta; decidono le Case.
    IF EXISTS (SELECT 1 FROM trasi.movimento m
                WHERE m.oggetto_id = NEW.oggetto_id
                  AND m.stato IN ('proposto','confermato')
                  AND daterange(m.dal, COALESCE(m.al, m.dal), '[]')
                      && daterange(NEW.dal, COALESCE(NEW.al, NEW.dal), '[]')) THEN
      RAISE NOTICE 'conflitto di periodo sull''oggetto %: la decisione resta alle due Case (V6)', NEW.oggetto_id;
    END IF;
    RETURN NEW;
  END IF;

  -- UPDATE: il solo ruolo autorizzato è `applicatore` via conferma_movimento().
  -- Un UPDATE diretto (GRANT futuro, errore di configurazione) muore qui con P0001.
  IF current_user <> 'applicatore' THEN
    RAISE EXCEPTION 'i movimenti si cambiano solo con conferma_movimento(): la conferma spetta alla Casa ricevente (V6), current_user=%', current_user
      USING ERRCODE = 'P0001';
  END IF;
  IF (NEW.oggetto_id, NEW.da_casa_id, NEW.a_casa_id, NEW.dal, NEW.ts)
     IS DISTINCT FROM (OLD.oggetto_id, OLD.da_casa_id, OLD.a_casa_id, OLD.dal, OLD.ts) THEN
    RAISE EXCEPTION 'campi di movimento immutabili (oggetto, Case, data inizio, ts)'
      USING ERRCODE = 'P0001';
  END IF;
  IF NEW.stato IS DISTINCT FROM OLD.stato THEN
    IF NOT ((OLD.stato = 'proposto'    AND NEW.stato IN ('confermato','rifiutato'))
         OR (OLD.stato = 'confermato'  AND NEW.stato = 'rientrato')) THEN
      RAISE EXCEPTION 'transizione di movimento non ammessa: % → % (movimento %, oggetto %): decide la Casa ricevente',
        OLD.stato, NEW.stato, NEW.id, NEW.oggetto_id USING ERRCODE = 'P0001';
    END IF;
  END IF;
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS movimento_00_stato_tg ON trasi.movimento;
CREATE TRIGGER movimento_00_stato_tg BEFORE INSERT OR UPDATE ON trasi.movimento
  FOR EACH ROW EXECUTE FUNCTION trasi.movimento_00_stato_tg();

-- Impronta di scrittura: solo su `oggetto`.
--
-- `movimento` **non** porta `scrittura_00_ts`, e la ragione è che non ha le colonne che quel
-- trigger scrive (`aggiornato_ts`, `aggiornato_da`): attaccarlo comunque rendeva la tabella
-- **inscrivibile**. `trasi.scrittura_00_ts()` fa `NEW.aggiornato_ts := now()`, e su `movimento` —
-- che quelle colonne non le ha — ogni INSERT moriva con
-- `record "new" has no field "aggiornato_ts"`. Misurato: `POST /op/movimento` (il pulsante
-- «Proponi prestito» della UI) rispondeva 500, e nessun prestito poteva nascere.
--
-- Non si aggiungono le colonne per uniformità: `movimento` non è in `v_scritture_senza_audit` —
-- la sua contabilità è l'audit `conferma_movimento` scritto a **ogni** transizione di stato, e
-- `movimento_00_stato_tg` respinge con P0001 qualunque UPDATE che non venga da `conferma_movimento`.
-- Una seconda impronta che nessuno legge sarebbe peso morto, non sicurezza.
DROP TRIGGER IF EXISTS scrittura_00_ts ON trasi.oggetto;
CREATE TRIGGER scrittura_00_ts BEFORE INSERT OR UPDATE ON trasi.oggetto
  FOR EACH ROW EXECUTE FUNCTION trasi.scrittura_00_ts();

-- Il trigger va rimosso anche da un database già applicato: `DROP TRIGGER IF EXISTS` su una tabella
-- che non lo ha è un no-op, quindi questa riga è sicura sia sul DB esistente sia su uno nuovo.
DROP TRIGGER IF EXISTS scrittura_00_ts ON trasi.movimento;

-- ---------------------------------------------------------------------------
-- 3. RLS — ENABLE + FORCE; USING **e** WITH CHECK su ogni policy di scrittura
-- ---------------------------------------------------------------------------
ALTER TABLE trasi.oggetto   ENABLE ROW LEVEL SECURITY;
ALTER TABLE trasi.oggetto   FORCE  ROW LEVEL SECURITY;
ALTER TABLE trasi.movimento ENABLE ROW LEVEL SECURITY;
ALTER TABLE trasi.movimento FORCE  ROW LEVEL SECURITY;

-- owner e applicatore (viste security_invoker=false di db/004; SECURITY DEFINER di db/006).
DROP POLICY IF EXISTS owner_all ON trasi.oggetto;
CREATE POLICY owner_all ON trasi.oggetto FOR ALL TO trasi_owner USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS owner_all ON trasi.movimento;
CREATE POLICY owner_all ON trasi.movimento FOR ALL TO trasi_owner USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS appl_all ON trasi.oggetto;
CREATE POLICY appl_all ON trasi.oggetto FOR ALL TO applicatore USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS appl_all ON trasi.movimento;
CREATE POLICY appl_all ON trasi.movimento FOR ALL TO applicatore USING (true) WITH CHECK (true);

-- oggetto: SELECT a tutta la rete (inventario consultabile, US-5.1).
DROP POLICY IF EXISTS ogg_sel ON trasi.oggetto;
CREATE POLICY ogg_sel ON trasi.oggetto FOR SELECT
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano,
     rete, ti, metabase_ro, automazioni, shim_rw
  USING (true);

-- oggetto: INSERT/UPDATE solo della propria Casa. Le policy sono l'autorità (USING **e** WITH CHECK);
-- il GRANT ai ruoli Casa non è qui ma in db/032 (nato con la decisione di scrittura diretta D1):
-- db/000–029 sono congelati. `v_scritture_senza_audit` esclude già le scritture della propria Casa.
DROP POLICY IF EXISTS ogg_ins_casa ON trasi.oggetto;
CREATE POLICY ogg_ins_casa ON trasi.oggetto FOR INSERT
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano
  WITH CHECK (casa_id = (SELECT trasi.casa_corrente()));
DROP POLICY IF EXISTS ogg_upd_casa ON trasi.oggetto;
CREATE POLICY ogg_upd_casa ON trasi.oggetto FOR UPDATE
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano
  USING (casa_id = (SELECT trasi.casa_corrente()))
  WITH CHECK (casa_id = (SELECT trasi.casa_corrente()));

-- movimento: lettura per le Case coinvolte, rete, ti e automazioni (alert «da confermare»).
DROP POLICY IF EXISTS mov_sel ON trasi.movimento;
CREATE POLICY mov_sel ON trasi.movimento FOR SELECT
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano,
     rete, ti, automazioni, shim_rw
  USING (da_casa_id = (SELECT trasi.casa_corrente())
      OR a_casa_id = (SELECT trasi.casa_corrente())
      OR current_user IN ('rete','ti','automazioni','shim_rw'));

-- movimento: INSERT solo della Casa CEDENTE e verso l'inventario della propria Casa.
DROP POLICY IF EXISTS mov_ins_casa ON trasi.movimento;
CREATE POLICY mov_ins_casa ON trasi.movimento FOR INSERT
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano
  WITH CHECK (da_casa_id = (SELECT trasi.casa_corrente())
              AND EXISTS (SELECT 1 FROM trasi.oggetto o
                           WHERE o.id = oggetto_id
                             AND o.casa_id = (SELECT trasi.casa_corrente())
                             AND o.attivo));

-- Nessuna policy UPDATE per i ruoli Casa: la conferma passa da conferma_movimento()
-- (SECURITY DEFINER owner `applicatore`, con audit). Mai DELETE: nessuna policy DELETE.

-- ---------------------------------------------------------------------------
-- 4. GRANT
-- ---------------------------------------------------------------------------
-- I GRANT di dominio esistenti NON sono toccati da 005 (oggetto/movimento sono nuovi):
-- qui si parte da zero con il minimo indispensabile.
REVOKE ALL ON trasi.oggetto, trasi.movimento FROM PUBLIC;

GRANT SELECT ON trasi.oggetto
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano,
     rete, ti, metabase_ro, automazioni, shim_rw, applicatore;
GRANT SELECT ON trasi.movimento
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano,
     rete, ti, automazioni, shim_rw, applicatore;
-- metabase_ro legge i movimenti solo dalle viste (v_uso_oggetti/v_movimenti_da_confermare).

-- INSERT diretto del movimento: solo ruoli Casa (eccezione V4 documentata, Fase 0 §2).
GRANT INSERT ON trasi.movimento
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano;

-- Applicatore: scrive per il flusso proposte (oggetto) e per conferma_movimento (movimento).
GRANT INSERT, UPDATE ON trasi.oggetto   TO applicatore;
GRANT INSERT, UPDATE ON trasi.movimento TO applicatore;

-- Owner (seed, manutenzione).
GRANT SELECT, INSERT, UPDATE ON trasi.oggetto, trasi.movimento TO trasi_owner;

-- Sequenze: senza USAGE l'INSERT serial fallisce con 42501.
GRANT USAGE ON SEQUENCE trasi.movimento_id_seq
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano, applicatore;
GRANT USAGE ON SEQUENCE trasi.oggetto_id_seq TO applicatore;

-- ---------------------------------------------------------------------------
-- 5. Verifica di installazione
-- ---------------------------------------------------------------------------
DO $verify$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'trasi' AND c.relkind = 'r'
       AND c.relname IN ('oggetto','movimento')
       AND NOT (c.relrowsecurity AND c.relforcerowsecurity)
  ) THEN
    RAISE EXCEPTION '014: oggetto/movimento senza ENABLE+FORCE RLS';
  END IF;
  -- `movimento` ha **un solo** trigger, quello della macchina a stati: `scrittura_00_ts` è stato
  -- rimosso perché scrive `NEW.aggiornato_ts`, colonna che `movimento` non ha — attaccarlo rendeva
  -- ogni INSERT impossibile (`record "new" has no field "aggiornato_ts"`). Il controllo verifica
  -- l'assenza, non la presenza: è il presidio che impedisce di reintrodurlo «per simmetria con
  -- oggetto», che è esattamente come era arrivato.
  IF NOT EXISTS (SELECT 1 FROM pg_trigger
                  WHERE tgrelid = 'trasi.movimento'::regclass AND NOT tgisinternal
                    AND tgname = 'movimento_00_stato_tg') THEN
    RAISE EXCEPTION '014: manca movimento_00_stato_tg (la macchina a stati del prestito)';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_trigger
              WHERE tgrelid = 'trasi.movimento'::regclass AND NOT tgisinternal
                AND tgname = 'scrittura_00_ts') THEN
    RAISE EXCEPTION '014: scrittura_00_ts è su movimento, che non ha aggiornato_ts: ogni INSERT fallirebbe';
  END IF;
  RAISE NOTICE '014_attrezzoteca applicato: oggetto + movimento, RLS ENABLE+FORCE, INSERT movimento solo Casa cedente, UPDATE solo via conferma_movimento (applicatore), mai DELETE';
END
$verify$;

RESET ROLE;
