-- Trasi — db/026_attrezzoteca_chat.sql
-- L'attrezzoteca in chat (scheda !NEW 5, dialoghi della specifica servizio): tre lacune del dominio
-- che la UI non sentiva ma la chat sì, perché l'assistente risponde con i numeri, non con le schermate.
--
--   1. il CONFLITTO di prenotazione era un `RAISE NOTICE` — invisibile a chi chiama (shim, chat, UI):
--      l'operatore chiede "è libero?" e riceve una risposta che non sa di non essere tutta la verità.
--      Qui il conflitto diventa una colonna della funzione `prenota_oggetto`: segnalato, non rifiutato (V6);
--   2. il RIFIUTO di un prestito era nello stato (`rifiutato` del CHECK e del trigger) ma nessuna funzione
--       lo raggiungeva: l'unica via era `conferma_movimento`, che non fa rifiuti. La Casa ricevente non poteva
--       dire no se non facendosi restituire un 409 senza effetto — cioè non poteva dirlo;
--   3. la CONDIZIONE al rientro la scriveva `conferma_movimento` copiando quella **corrente** dell'oggetto:
--       «il caricabatterie non funziona più» non poteva essere registrato, e un oggetto danneggiato restava
--       «integro» e disponibile.
--
-- Aggiunge anche `prenota_oggetto` (prenotazione anticipata, US-5.2: `dal` futuro, non solo oggi) e
-- `riporta_oggetto` (rientro con condizione + sospensione opzionale dell'oggetto, dialogo «trapano TR04»).
--
-- Ogni scrittura è SECURITY DEFINER di `applicatore` con la verifica del ruolo dentro la funzione (come
-- `conferma_movimento`), e con riga di audit: il dominio resta contabilizzato da `v_scritture_senza_audit`.
-- Idempotente: DROP+CREATE delle funzioni, owner impostato solo se serve.
\set ON_ERROR_STOP on
\set VERBOSITY terse

-- search_path esplicito nei corpi: ogni funzione ha il suo `SET search_path`.
-- Niente SET ROLE: le CREATE girano con il chiamante (superuser via apply.sh) e
-- l'owner si impone col DO in coda.

-- ---------------------------------------------------------------------------
-- 1. `prenota_oggetto(p_oggetto, p_da, p_al, p_ruolo, p_a_casa)` — prenotazione
-- ---------------------------------------------------------------------------
-- La Casa della sessione prenota un oggetto per un periodo FUTURO. Il movimento nasce 'proposto' come il
-- prestito immediato (il confermare resta della Casa che riceve, V6): qui la differenza è che `dal` può
-- essere nel futuro, e il ritorno dichiara i conflitti di periodo — con oggetto, Case e date — invece di
-- sussurrarli a un NOTICE.
CREATE OR REPLACE FUNCTION trasi.prenota_oggetto(
  p_oggetto integer,
  p_a_casa  text,
  p_dal     date,
  p_al      date,
  p_ruolo   text
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = trasi, public, pg_catalog
AS $fn$
DECLARE
  v_casa_id   int;
  v_a_casa_id int;
  v_mov_id    int;
  v_mov       trasi.movimento%ROWTYPE;
  v_oggetto   trasi.oggetto%ROWTYPE;
  v_conflitti jsonb;
BEGIN
  IF p_dal IS NULL THEN
    RAISE EXCEPTION 'prenotazione senza data di inizio: indicare «dal» (AAAA-MM-GG)' USING ERRCODE = 'P0001';
  END IF;
  IF p_al IS NULL THEN
    RAISE EXCEPTION 'prenotazione senza fine: per prenotare in anticipo serve «al» (AAAA-MM-GG)' USING ERRCODE = 'P0001';
  END IF;
  IF p_al < p_dal THEN
    RAISE EXCEPTION '«al» (%) è prima di «dal» (%): una prenotazione non dura un tempo negativo', p_al, p_dal USING ERRCODE = 'P0001';
  END IF;

  SELECT rc.casa_id INTO v_casa_id FROM trasi.ruolo_casa rc WHERE rc.ruolo = p_ruolo;
  IF v_casa_id IS NULL THEN
    RAISE EXCEPTION 'la prenotazione spetta a una Casa: % non è una Casa', p_ruolo USING ERRCODE = 'P0001';
  END IF;

  SELECT c.id INTO v_a_casa_id FROM trasi.casa c WHERE c.slug = p_a_casa;
  IF v_a_casa_id IS NULL THEN
    RAISE EXCEPTION 'Casa destinataria «%» inesistente', p_a_casa USING ERRCODE = 'P0001';
  END IF;

  SELECT * INTO v_oggetto FROM trasi.oggetto o WHERE o.id = p_oggetto AND o.attivo;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'oggetto % inesistente o ritirato dall''inventario', p_oggetto USING ERRCODE = 'P0001';
  END IF;

  -- La prenotazione è una RICHIESTA all'oggetto, e l'oggetto sta da qualche parte: la Casa che lo tiene
  -- (o che lo terrà al momento) è la cedente. Se il richiedente È la Casa che lo tiene, il movimento è un
  -- spostamento a sé: vietato dal CHECK `movimento_case_distinte`, qui col messaggio giusto.
  IF v_a_casa_id = v_oggetto.casa_id THEN
    RAISE EXCEPTION 'l''oggetto è già presso «%»: la prenotazione riguarda una Casa diversa',
      (SELECT c.slug FROM trasi.casa c WHERE c.id = v_oggetto.casa_id) USING ERRCODE = 'P0001';
  END IF;

  -- INSERT diretto con stato 'proposto': stessa eccezione V4 documentata di `POST /op/movimento`.
  -- Il conflitto di periodo non si rifiuta (V6): si registra e si dichiara in ritorno.
  INSERT INTO trasi.movimento (oggetto_id, da_casa_id, a_casa_id, dal, al, stato, motivazione)
  VALUES (p_oggetto, v_oggetto.casa_id, v_a_casa_id, p_dal, p_al, 'proposto', 'prenotazione anticipata')
  RETURNING id INTO v_mov_id;

  -- I conflitti si leggono DOPO l'insert: qualsiasi movimento attivo che si sovrappone al periodo —
  -- incluso quello appena scritto — è un conflitto da dichiarare (V6: segnalato, la decisione resta umana).
  SELECT COALESCE(jsonb_agg(jsonb_build_object(
           'movimento_id', m.id,
           'stato', m.stato,
           'da_casa', (SELECT c.slug FROM trasi.casa c WHERE c.id = m.da_casa_id),
           'a_casa',  (SELECT c.slug FROM trasi.casa c WHERE c.id = m.a_casa_id),
           'dal', m.dal, 'al', m.al)), '[]'::jsonb)
    INTO v_conflitti
    FROM trasi.movimento m
   WHERE m.oggetto_id = p_oggetto
     AND m.id <> v_mov_id
     AND m.stato IN ('proposto','confermato')
     AND daterange(m.dal, COALESCE(m.al, m.dal), '[]') && daterange(p_dal, p_al, '[]');

  SELECT * INTO v_mov FROM trasi.movimento WHERE id = v_mov_id;

  INSERT INTO trasi.audit (azione, eseguito_da, entita, entita_id, dopo)
  VALUES ('prenota_oggetto', session_user, 'movimento', v_mov_id,
          to_jsonb(v_mov));

  RETURN jsonb_build_object(
    'movimento_id', v_mov_id,
    'oggetto_id', v_oggetto.id,
    'oggetto', v_oggetto.nome,
    'da_casa', (SELECT c.slug FROM trasi.casa c WHERE c.id = v_oggetto.casa_id),
    'a_casa', p_a_casa,
    'dal', p_dal,
    'al', p_al,
    'stato', 'proposto',
    'conflitti', v_conflitti
  );
END;
$fn$;

-- ---------------------------------------------------------------------------
-- 2. `rifiuta_movimento(p_movimento, p_ruolo)` — il «no» della Casa ricevente
-- ---------------------------------------------------------------------------
-- La transizione proposto→rifiutato esisteva nel CHECK del trigger ma nessuna funzione la raggiungeva:
-- la Casa ricevente non poteva dire no se non facendosi rispondere 409. La regola è la stessa di
-- `conferma_movimento` (decide la destinataria; rete/ti per l'archivio), e il rifiuto è terminale.
CREATE OR REPLACE FUNCTION trasi.rifiuta_movimento(p_movimento integer, p_ruolo text)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = trasi, public, pg_catalog
AS $fn$
DECLARE
  v_mov trasi.movimento%ROWTYPE;
  v_casa_id int;
BEGIN
  SELECT rc.casa_id INTO v_casa_id FROM trasi.ruolo_casa rc WHERE rc.ruolo = p_ruolo;
  SELECT m.* INTO v_mov FROM trasi.movimento m WHERE m.id = p_movimento;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'movimento % inesistente', p_movimento USING ERRCODE = 'P0001';
  END IF;
  IF v_mov.stato <> 'proposto' THEN
    RAISE EXCEPTION 'il movimento % è in stato ''%'': si rifiuta solo un prestito proposto',
      p_movimento, v_mov.stato USING ERRCODE = 'P0001';
  END IF;
  IF p_ruolo NOT IN ('rete','ti') AND v_casa_id IS DISTINCT FROM v_mov.a_casa_id THEN
    RAISE EXCEPTION 'il rifiuto del movimento % spetta alla Casa ricevente (%), non a %',
      p_movimento,
      (SELECT c.slug FROM trasi.casa c WHERE c.id = v_mov.a_casa_id),
      p_ruolo USING ERRCODE = 'P0001';
  END IF;

  UPDATE trasi.movimento m SET stato = 'rifiutato' WHERE m.id = p_movimento;

  INSERT INTO trasi.audit (azione, eseguito_da, entita, entita_id, prima, dopo)
  SELECT 'rifiuta_movimento', session_user, 'movimento', m.id,
         to_jsonb(v_mov), to_jsonb(m)
    FROM trasi.movimento m WHERE m.id = p_movimento;
END;
$fn$;

-- ---------------------------------------------------------------------------
-- 3. `riporta_oggetto(p_movimento, p_ruolo, p_condizione)` — rientro con condizione
-- ---------------------------------------------------------------------------
-- Il rientro chiude il prestito. `conferma_movimento` copiava la condizione **corrente** dell'oggetto:
-- «il caricabatterie non funziona più» restava «integro» e l'oggetto tornava disponibile. Qui la
-- condizione arriva dal chiamante (la Casa che restituisce, o la rete), viene scritta SULL'OGGETTO
-- (è il suo stato d'ora in poi) e sul movimento (condizione_rientro). Con `p_sospendi`, l'oggetto
-- passa attivo=false: fuori dall'inventario finché una Casa non lo ripristina con una proposta
-- `modifica_oggetto` (attivo=true) — la sospensione è memoria, la riparazione è una modifica decisa.
CREATE OR REPLACE FUNCTION trasi.riporta_oggetto(
  p_movimento  integer,
  p_ruolo      text,
  p_condizione text,
  p_sospendi   boolean DEFAULT false
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = trasi, public, pg_catalog
AS $fn$
DECLARE
  v_mov     trasi.movimento%ROWTYPE;
  v_casa_id int;
  v_ogg_prima jsonb;
  v_oggetto_id int;
BEGIN
  IF p_condizione IS NULL OR p_condizione NOT IN ('integro','danneggiato','mancante_di_parti') THEN
    RAISE EXCEPTION 'condizione al rientro obbligatoria: integro | danneggiato | mancante_di_parti'
      USING ERRCODE = 'P0001';
  END IF;

  SELECT rc.casa_id INTO v_casa_id FROM trasi.ruolo_casa rc WHERE rc.ruolo = p_ruolo;
  SELECT m.* INTO v_mov FROM trasi.movimento m WHERE m.id = p_movimento;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'movimento % inesistente', p_movimento USING ERRCODE = 'P0001';
  END IF;
  IF v_mov.stato <> 'confermato' THEN
    RAISE EXCEPTION 'il movimento % è in stato ''%'': il rientro si marca solo su un prestito confermato',
      p_movimento, v_mov.stato USING ERRCODE = 'P0001';
  END IF;
  IF p_ruolo NOT IN ('rete','ti') AND v_casa_id IS DISTINCT FROM v_mov.da_casa_id THEN
    RAISE EXCEPTION 'il rientro del movimento % lo marca la Casa cedente (%), non %',
      p_movimento,
      (SELECT c.slug FROM trasi.casa c WHERE c.id = v_mov.da_casa_id),
      p_ruolo USING ERRCODE = 'P0001';
  END IF;

  SELECT to_jsonb(o) INTO v_ogg_prima FROM trasi.oggetto o WHERE o.id = v_mov.oggetto_id;
  v_oggetto_id := v_mov.oggetto_id;

  UPDATE trasi.movimento m
     SET stato = 'rientrato', condizione_rientro = p_condizione
   WHERE m.id = p_movimento;

  UPDATE trasi.oggetto o
     SET condizione = p_condizione,
         attivo = CASE WHEN p_sospendi THEN false ELSE o.attivo END,
         aggiornato_ts = now()
   WHERE o.id = v_oggetto_id;

  INSERT INTO trasi.audit (azione, eseguito_da, entita, entita_id, prima, dopo)
  SELECT 'riporta_oggetto', session_user, 'oggetto', o.id, v_ogg_prima, to_jsonb(o)
    FROM trasi.oggetto o WHERE o.id = v_oggetto_id;

  RETURN jsonb_build_object(
    'movimento_id', p_movimento,
    'oggetto_id', v_oggetto_id,
    'condizione', p_condizione,
    'sospeso', COALESCE(p_sospendi, false)
  );
END;
$fn$;

-- ---------------------------------------------------------------------------
-- 4. Proprietà e privilegi — la lezione dell'apply fallito (misurato):
--    * le CREATE sopra girano con il chiamante (superuser via apply.sh: il file non
--      fa SET ROLE — al secondo apply il CREATE OR REPLACE di `trasi_owner` sarebbe
--      morto con «must be owner of function», l'ALTER OWNER con lo stesso errore);
--    * l'owner si impone col DO qui sotto, che tocca solo le funzioni non ancora di
--      `applicatore`: il secondo apply non trova nulla da fare e non fallisce.
-- ---------------------------------------------------------------------------
DO $owner$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT p.oid::regprocedure::text AS firma
      FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
     WHERE n.nspname = 'trasi'
       AND p.proname IN ('prenota_oggetto','rifiuta_movimento','riporta_oggetto')
       AND pg_get_userbyid(p.proowner) <> 'applicatore'
  LOOP
    EXECUTE format('ALTER FUNCTION %s OWNER TO applicatore', r.firma);
  END LOOP;
END
$owner$;

GRANT EXECUTE ON FUNCTION trasi.prenota_oggetto(integer, text, date, date, text)
  TO shim_rw, applicatore, automazioni,
     casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano;
GRANT EXECUTE ON FUNCTION trasi.rifiuta_movimento(integer, text)
  TO shim_rw, applicatore, automazioni,
     casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano;
GRANT EXECUTE ON FUNCTION trasi.riporta_oggetto(integer, text, text, boolean)
  TO shim_rw, applicatore, automazioni,
     casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano;

REVOKE ALL ON FUNCTION trasi.prenota_oggetto(integer, text, date, date, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION trasi.rifiuta_movimento(integer, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION trasi.riporta_oggetto(integer, text, text, boolean) FROM PUBLIC;

-- ---------------------------------------------------------------------------
-- 5. Verifica di installazione
-- ---------------------------------------------------------------------------
DO $verify$
BEGIN
  IF (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
       WHERE n.nspname = 'trasi' AND p.proname IN ('prenota_oggetto','rifiuta_movimento','riporta_oggetto')) <> 3 THEN
    RAISE EXCEPTION '026: manca una delle tre funzioni dell''attrezzoteca';
  END IF;
  RAISE NOTICE '026_attrezzoteca_chat applicato: prenota_oggetto (conflitti in ritorno), rifiuta_movimento, riporta_oggetto (condizione + sospensione)';
END
$verify$;
