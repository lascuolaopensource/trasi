-- Trasi — db/033_movimenti_bidirezionali.sql
-- Il movimento dell'attrezzoteca può nascere da **entrambe** le Case, e decide la controparte.
--
-- Fino a qui (db/014) un movimento lo proponeva solo la Casa cedente (`mov_ins_casa`: `da_casa_id =
-- casa_corrente()`) e lo confermava solo la ricevente (`conferma_movimento`): la Casa che **vuole** un oggetto
-- («5 microfoni per domani, dove?», US-5.1/5.2) non aveva un gesto suo — l'inventario di rete serviva a
-- chiedere in prestito, e la richiesta non esisteva nel modello. Inoltre `conferma_movimento(p_movimento,
-- p_ruolo)` non implementava il rifiuto, benché `movimento.stato` ammetta 'rifiutato' e il trigger la
-- transizione proposto→rifiutato: lo shim accettava `azione: "rifiuta"` e **confermava**.
--
-- Cosa cambia:
--   * `movimento.proposto_da_casa_id` — chi ha proposto (cedente **o** ricevente); backfill = cedente per le
--     righe esistenti (finora proponeva sempre lei); CHECK che sia una delle due; immutabile (trigger);
--   * `mov_ins_casa` — chi propone è la Casa della sessione, in uno dei due ruoli; l'oggetto sta presso la
--     cedente ed è attivo;
--   * `conferma_movimento(p_movimento, p_ruolo, p_azione DEFAULT 'conferma', p_condizione_rientro DEFAULT NULL)`
--     — sostituisce la firma a due parametri (DROP: con i default una chiamata a due argomenti sarebbe ambigua).
--     Regola: su 'proposto' decide la **controparte** di chi ha proposto (rete/ti sempre): 'conferma' →
--     confermato + oggetto alla ricevente; 'rifiuta' → rifiutato, oggetto fermo. Su 'confermato' 'rientro' →
--     rientrato con `condizione_rientro = COALESCE(p_condizione_rientro, condizione dell'oggetto)` + oggetto alla
--     cedente, solo cedente o rete/ti. Ogni altra combinazione → P0001 parlante che dice chi può e cosa.
--     Audit `conferma_movimento` a ogni transizione (movimento; oggetto solo quando si sposta), con `azione`
--     nel `dopo`;
--   * `v_movimenti_da_confermare` — in più `proposto_da_casa_id/_slug` e `decide_casa_id/_slug` (la
--     controparte): la UI legge **da qui** chi deve decidere, nessuna copia della regola in JS.
--
-- Idempotente. Tabella, trigger, policy e vista come `trasi_owner` (SET ROLE); la funzione `conferma_movimento`
-- come amministratore, perché il suo owner è `applicatore` e `trasi_owner` non ne è membro — è la stessa forma di
-- db/006, che gira senza SET ROLE proprio per questo. db/000–029 e db/032 sono congelati; per questo il file è nuovo. In apply.sh dopo 032:
-- 014 e 016 (rieseguiti prima) ricreano policy/vista/trigger nella forma vecchia, e questo file li porta alla
-- forma nuova — l'ordine è ciò che rende il risultato deterministico.
\set ON_ERROR_STOP on
\set VERBOSITY terse

SET ROLE trasi_owner;
SET search_path = trasi, public, pg_temp;

DO $pre$
BEGIN
  IF to_regclass('trasi.movimento') IS NULL THEN
    RAISE EXCEPTION '033_movimenti_bidirezionali: manca trasi.movimento — applica prima db/014_attrezzoteca.sql';
  END IF;
  IF to_regclass('trasi.v_movimenti_da_confermare') IS NULL THEN
    RAISE EXCEPTION '033_movimenti_bidirezionali: manca trasi.v_movimenti_da_confermare — applica prima db/016_viste_new.sql';
  END IF;
  IF to_regprocedure('trasi.conferma_movimento(integer,text)') IS NULL
     AND to_regprocedure('trasi.conferma_movimento(integer,text,text,text)') IS NULL THEN
    RAISE EXCEPTION '033_movimenti_bidirezionali: manca trasi.conferma_movimento — applica prima db/006_fn_proposte.sql';
  END IF;
END
$pre$;

-- ---------------------------------------------------------------------------
-- 1. La colonna: chi ha proposto
-- ---------------------------------------------------------------------------
ALTER TABLE trasi.movimento ADD COLUMN IF NOT EXISTS proposto_da_casa_id integer REFERENCES trasi.casa(id);

-- Backfill: finora proponeva sempre la cedente. Il trigger `movimento_00_stato_tg` respinge ogni UPDATE che non
-- venga da `applicatore` (giusto: è il presidio contro le modifiche fuori da `conferma_movimento`); qui si
-- riempie una colonna nuova senza toccare stato né campi immutabili, quindi lo si sospende per la sola istruzione.
ALTER TABLE trasi.movimento DISABLE TRIGGER movimento_00_stato_tg;
UPDATE trasi.movimento SET proposto_da_casa_id = da_casa_id WHERE proposto_da_casa_id IS NULL;
ALTER TABLE trasi.movimento ENABLE TRIGGER movimento_00_stato_tg;

ALTER TABLE trasi.movimento DROP CONSTRAINT IF EXISTS movimento_proposto_da_una_delle_due;
ALTER TABLE trasi.movimento ADD CONSTRAINT movimento_proposto_da_una_delle_due
  CHECK (proposto_da_casa_id IN (da_casa_id, a_casa_id));

COMMENT ON COLUMN trasi.movimento.proposto_da_casa_id IS
  'La Casa che ha proposto il movimento: la cedente (prestito) o la ricevente (richiesta, db/033). Decide la controparte (conferma_movimento). Immutabile.';
COMMENT ON TABLE trasi.movimento IS
  'Prestito tra Case (US-5.2/5.3): INSERT diretto della Casa che propone — cedente (prestito) o ricevente (richiesta, db/033) — in stato proposto (eccezione V4 documentata); decide la controparte via conferma_movimento() (conferma | rifiuta; rientro della cedente). Mai DELETE.';

-- ---------------------------------------------------------------------------
-- 2. Il trigger: la nuova colonna è immutabile come le altre
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION trasi.movimento_00_stato_tg() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
DECLARE
  v_attivo  boolean;
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF NEW.stato IS DISTINCT FROM 'proposto' THEN
      RAISE EXCEPTION 'un movimento nasce in stato ''proposto'', non ''%'': decide la controparte (conferma_movimento)', NEW.stato
        USING ERRCODE = 'P0001';
    END IF;
    SELECT o.attivo INTO v_attivo FROM trasi.oggetto o WHERE o.id = NEW.oggetto_id;
    IF v_attivo IS DISTINCT FROM true THEN
      RAISE EXCEPTION 'oggetto % ritirato o inesistente: movimento non registrabile', NEW.oggetto_id
        USING ERRCODE = 'P0001';
    END IF;
    IF EXISTS (SELECT 1 FROM trasi.movimento m
                WHERE m.oggetto_id = NEW.oggetto_id
                  AND m.stato IN ('proposto','confermato')
                  AND daterange(m.dal, COALESCE(m.al, m.dal), '[]')
                      && daterange(NEW.dal, COALESCE(NEW.al, NEW.dal), '[]')) THEN
      RAISE NOTICE 'conflitto di periodo sull''oggetto %: la decisione resta alle due Case (V6)', NEW.oggetto_id;
    END IF;
    RETURN NEW;
  END IF;

  IF current_user <> 'applicatore' THEN
    RAISE EXCEPTION 'i movimenti si cambiano solo con conferma_movimento(): decide la controparte di chi ha proposto (V6), current_user=%', current_user
      USING ERRCODE = 'P0001';
  END IF;
  IF (NEW.oggetto_id, NEW.da_casa_id, NEW.a_casa_id, NEW.proposto_da_casa_id, NEW.dal, NEW.ts)
     IS DISTINCT FROM (OLD.oggetto_id, OLD.da_casa_id, OLD.a_casa_id, OLD.proposto_da_casa_id, OLD.dal, OLD.ts) THEN
    RAISE EXCEPTION 'campi di movimento immutabili (oggetto, Case, chi ha proposto, data inizio, ts)'
      USING ERRCODE = 'P0001';
  END IF;
  IF NEW.stato IS DISTINCT FROM OLD.stato THEN
    IF NOT ((OLD.stato = 'proposto'    AND NEW.stato IN ('confermato','rifiutato'))
         OR (OLD.stato = 'confermato'  AND NEW.stato = 'rientrato')) THEN
      RAISE EXCEPTION 'transizione di movimento non ammessa: % → % (movimento %, oggetto %)',
        OLD.stato, NEW.stato, NEW.id, NEW.oggetto_id USING ERRCODE = 'P0001';
    END IF;
  END IF;
  RETURN NEW;
END $$;

-- ---------------------------------------------------------------------------
-- 3. La policy: propone la Casa della sessione, come cedente o come ricevente
-- ---------------------------------------------------------------------------
DROP POLICY IF EXISTS mov_ins_casa ON trasi.movimento;
CREATE POLICY mov_ins_casa ON trasi.movimento FOR INSERT
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano
  WITH CHECK (proposto_da_casa_id = (SELECT trasi.casa_corrente())
              AND (SELECT trasi.casa_corrente()) IN (da_casa_id, a_casa_id)
              AND EXISTS (SELECT 1 FROM trasi.oggetto o
                           WHERE o.id = oggetto_id
                             AND o.casa_id = da_casa_id
                             AND o.attivo));

-- ---------------------------------------------------------------------------
-- 4. conferma_movimento: decide la controparte; conferma | rifiuta | rientro
--    (come amministratore: l'owner è `applicatore`, v. testa del file)
-- ---------------------------------------------------------------------------
RESET ROLE;
DROP FUNCTION IF EXISTS trasi.conferma_movimento(integer, text);

CREATE OR REPLACE FUNCTION trasi.conferma_movimento(
  p_movimento integer,
  p_ruolo text,
  p_azione text DEFAULT 'conferma',
  p_condizione_rientro text DEFAULT NULL
)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = trasi, public, pg_catalog
AS $fn$
DECLARE
  v_mov        trasi.movimento%ROWTYPE;
  v_casa_id    int;
  v_rete       boolean;
  v_decide_id  int;
  v_decide     text;
  v_cedente    text;
  v_prima      jsonb;
  v_ogg_prima  jsonb;
  v_spostato   boolean := false;
BEGIN
  IF p_azione IS NULL OR p_azione NOT IN ('conferma', 'rifiuta', 'rientro') THEN
    RAISE EXCEPTION 'azione ''%'' non ammessa: le azioni sono conferma, rifiuta, rientro', COALESCE(p_azione, '(vuota)')
      USING ERRCODE = 'P0001';
  END IF;
  IF p_condizione_rientro IS NOT NULL AND p_condizione_rientro NOT IN ('integro','danneggiato','mancante_di_parti') THEN
    RAISE EXCEPTION 'condizione_rientro ''%'' non ammessa: integro, danneggiato, mancante_di_parti', p_condizione_rientro
      USING ERRCODE = 'P0001';
  END IF;

  SELECT rc.casa_id INTO v_casa_id FROM trasi.ruolo_casa rc WHERE rc.ruolo = p_ruolo;
  v_rete := p_ruolo IN ('rete', 'ti');
  IF p_ruolo IS NULL OR (v_casa_id IS NULL AND NOT v_rete) THEN
    RAISE EXCEPTION 'ruolo % non riconosciuto: decide la Casa controparte di chi ha proposto', COALESCE(p_ruolo, '(vuoto)')
      USING ERRCODE = 'P0001';
  END IF;

  SELECT m.* INTO v_mov FROM trasi.movimento m WHERE m.id = p_movimento;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'movimento % inesistente', p_movimento USING ERRCODE = 'P0001';
  END IF;
  v_prima := to_jsonb(v_mov);
  SELECT to_jsonb(o) INTO v_ogg_prima FROM trasi.oggetto o WHERE o.id = v_mov.oggetto_id;

  -- La controparte di chi ha proposto: se ha proposto la cedente decide la ricevente, e viceversa.
  v_decide_id := CASE WHEN v_mov.proposto_da_casa_id = v_mov.da_casa_id THEN v_mov.a_casa_id ELSE v_mov.da_casa_id END;
  SELECT c.slug INTO v_decide  FROM trasi.casa c WHERE c.id = v_decide_id;
  SELECT c.slug INTO v_cedente FROM trasi.casa c WHERE c.id = v_mov.da_casa_id;

  CASE v_mov.stato
    WHEN 'proposto' THEN
      IF p_azione = 'rientro' THEN
        RAISE EXCEPTION 'il movimento % è ancora proposto: il rientro si registra solo su un prestito confermato', p_movimento
          USING ERRCODE = 'P0001';
      END IF;
      IF NOT v_rete AND v_casa_id IS DISTINCT FROM v_decide_id THEN
        RAISE EXCEPTION 'la decisione sul movimento % spetta a % (la controparte di chi ha proposto), non a %: la decisione resta umana (V6)',
          p_movimento, v_decide, p_ruolo USING ERRCODE = 'P0001';
      END IF;
      IF p_azione = 'conferma' THEN
        UPDATE trasi.movimento m SET stato = 'confermato' WHERE m.id = p_movimento;
        UPDATE trasi.oggetto o SET casa_id = v_mov.a_casa_id WHERE o.id = v_mov.oggetto_id;
        v_spostato := true;
      ELSE
        UPDATE trasi.movimento m SET stato = 'rifiutato' WHERE m.id = p_movimento;
      END IF;
    WHEN 'confermato' THEN
      IF p_azione <> 'rientro' THEN
        RAISE EXCEPTION 'il movimento % è già confermato: resta solo il rientro (azione ''rientro''), che registra la Casa cedente (%)',
          p_movimento, v_cedente USING ERRCODE = 'P0001';
      END IF;
      IF NOT v_rete AND v_casa_id IS DISTINCT FROM v_mov.da_casa_id THEN
        RAISE EXCEPTION 'il rientro del movimento % lo registra la Casa cedente (%), non %', p_movimento, v_cedente, p_ruolo
          USING ERRCODE = 'P0001';
      END IF;
      UPDATE trasi.movimento m
         SET stato = 'rientrato',
             condizione_rientro = COALESCE(p_condizione_rientro,
                                           (SELECT o.condizione FROM trasi.oggetto o WHERE o.id = v_mov.oggetto_id))
       WHERE m.id = p_movimento;
      UPDATE trasi.oggetto o SET casa_id = v_mov.da_casa_id WHERE o.id = v_mov.oggetto_id;
      v_spostato := true;
    ELSE
      RAISE EXCEPTION 'il movimento % è in stato ''%'': nessuna azione possibile (conferma/rifiuta solo da ''proposto'', rientro solo da ''confermato'')',
        p_movimento, v_mov.stato USING ERRCODE = 'P0001';
  END CASE;

  INSERT INTO trasi.audit (azione, eseguito_da, entita, entita_id, prima, dopo)
  SELECT 'conferma_movimento', session_user, 'movimento', m.id, v_prima,
         to_jsonb(m) || jsonb_build_object('azione', p_azione, 'ruolo', p_ruolo)
    FROM trasi.movimento m WHERE m.id = p_movimento;

  -- L'oggetto ha la sua riga solo quando si sposta (conferma, rientro): il rifiuto non lo tocca, e una riga
  -- senza mutazione farebbe credere a `v_scritture_senza_audit` una scrittura che non c'è stata.
  IF v_spostato THEN
    INSERT INTO trasi.audit (azione, eseguito_da, entita, entita_id, prima, dopo)
    SELECT 'conferma_movimento', session_user, 'oggetto', o.id, v_ogg_prima, to_jsonb(o)
      FROM trasi.oggetto o WHERE o.id = v_mov.oggetto_id;
  END IF;
END;
$fn$;

ALTER FUNCTION trasi.conferma_movimento(integer, text, text, text) OWNER TO applicatore;
REVOKE ALL ON FUNCTION trasi.conferma_movimento(integer, text, text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION trasi.conferma_movimento(integer, text, text, text)
  TO shim_rw, applicatore, automazioni,
     casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano;

-- ---------------------------------------------------------------------------
-- 5. La vista: chi ha proposto e chi decide, letti dalla UI senza copiare la regola
-- ---------------------------------------------------------------------------
SET ROLE trasi_owner;
DROP VIEW IF EXISTS trasi.v_movimenti_da_confermare;
CREATE VIEW trasi.v_movimenti_da_confermare AS
SELECT m.id, m.oggetto_id, o.nome AS oggetto_nome, o.quantita AS oggetto_quantita,
       m.da_casa_id, cda.slug AS da_casa_slug,
       m.a_casa_id,  ca.slug  AS a_casa_slug,
       m.proposto_da_casa_id, cp.slug AS proposto_da_casa_slug,
       CASE WHEN m.proposto_da_casa_id = m.da_casa_id THEN m.a_casa_id ELSE m.da_casa_id END AS decide_casa_id,
       CASE WHEN m.proposto_da_casa_id = m.da_casa_id THEN ca.slug   ELSE cda.slug     END AS decide_casa_slug,
       m.dal, m.al, m.motivazione, m.ts,
       (current_date - m.ts::date) AS giorni_attesa
FROM trasi.movimento m
JOIN trasi.oggetto o ON o.id = m.oggetto_id
JOIN trasi.casa cda ON cda.id = m.da_casa_id
JOIN trasi.casa ca  ON ca.id  = m.a_casa_id
JOIN trasi.casa cp  ON cp.id  = m.proposto_da_casa_id
WHERE m.stato = 'proposto';
ALTER VIEW trasi.v_movimenti_da_confermare SET (security_invoker = false);
GRANT SELECT ON trasi.v_movimenti_da_confermare
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao, casa_minimus, casa_pop,
     casa_bozzano, casa_dream, casa_tuturano, rete, ti, metabase_ro, automazioni, shim_rw, applicatore;
COMMENT ON VIEW trasi.v_movimenti_da_confermare IS
  'Movimenti in stato proposto (US-5.3): chi ha proposto (proposto_da_casa_*) e chi deve decidere (decide_casa_*: la controparte). La UI legge da qui, non ricalcola.';

-- ---------------------------------------------------------------------------
-- 6. Verifica di installazione
-- ---------------------------------------------------------------------------
DO $verify$
BEGIN
  IF to_regprocedure('trasi.conferma_movimento(integer,text)') IS NOT NULL THEN
    RAISE EXCEPTION '033_movimenti_bidirezionali: la firma a due parametri è ancora presente (ambigua con i default)';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_proc p JOIN pg_roles r ON r.oid = p.proowner
                  WHERE p.oid = 'trasi.conferma_movimento(integer,text,text,text)'::regprocedure AND r.rolname = 'applicatore') THEN
    RAISE EXCEPTION '033_movimenti_bidirezionali: conferma_movimento non ha owner applicatore';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                  WHERE table_schema = 'trasi' AND table_name = 'v_movimenti_da_confermare' AND column_name = 'decide_casa_slug') THEN
    RAISE EXCEPTION '033_movimenti_bidirezionali: v_movimenti_da_confermare senza decide_casa_slug';
  END IF;
  IF EXISTS (SELECT 1 FROM trasi.movimento WHERE proposto_da_casa_id NOT IN (da_casa_id, a_casa_id)) THEN
    RAISE EXCEPTION '033_movimenti_bidirezionali: movimenti con proposto_da fuori dalle due Case';
  END IF;
  RAISE NOTICE '033_movimenti_bidirezionali applicato: proposto_da_casa_id, mov_ins_casa bidirezionale, conferma_movimento(conferma|rifiuta|rientro) decide la controparte, vista con decide_casa_*';
END
$verify$;

RESET ROLE;
