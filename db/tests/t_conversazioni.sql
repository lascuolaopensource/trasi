-- Trasi — db/tests/t_conversazioni.sql · C01…C09
-- Storico della chat (D5, §5.1; db/021_conversazioni.sql): RLS per Casa, colonne calcolate dal
-- trigger, retention con cascade.
--
-- Convenzione della batteria: PASS = NOTICE, FAIL = EXCEPTION (interrompe il run). I test girano
-- come ruolo **applicativo** (SET ROLE), mai come superuser — un test che girasse da superuser
-- darebbe un falso positivo su ogni controllo di RLS. run.sh avvolge il file in BEGIN/ROLLBACK:
-- nessuna fixture resta nel database.
--
-- Cosa si asserisce, e cosa no. Si asseriscono la **struttura** e l'**isolamento** (0 righe,
-- 42501, cascade presente), non i conteggi delle tabelle di esercizio: un test che asserisce un
-- numero esatto si rompe quando un operatore usa la chat, che è il funzionamento normale del
-- sistema (README §7.6). Le uniche righe contate sono le **proprie fixture**, create qui dentro.
\set ON_ERROR_STOP on
\pset pager off

-- ---------------------------------------------------------------------------
-- C01 · struttura: ENABLE+FORCE RLS su entrambe, cascade presente, policy complete
-- ---------------------------------------------------------------------------
DO $c01$
DECLARE
  v_senza_force text;
  v_cascade     boolean;
  v_n           int;
  v_incomplete  text;
BEGIN
  SELECT string_agg(c.relname, ', ') INTO v_senza_force
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE n.nspname = 'trasi' AND c.relname IN ('conversazione','turno')
     AND NOT (c.relrowsecurity AND c.relforcerowsecurity);
  IF v_senza_force IS NOT NULL THEN
    RAISE EXCEPTION 'FAIL C01 — tabelle senza ENABLE+FORCE RLS: %', v_senza_force;
  END IF;

  -- `FORCE` è la parte che conta: senza, il proprietario non è soggetto alla RLS e il controllo
  -- «0 righe» di C03/C04 passerebbe per la ragione sbagliata.
  SELECT EXISTS (SELECT 1 FROM pg_constraint con
                  WHERE con.conrelid = 'trasi.turno'::regclass
                    AND con.confrelid = 'trasi.conversazione'::regclass
                    AND con.contype = 'f' AND con.confdeltype = 'c') INTO v_cascade;
  IF NOT v_cascade THEN
    RAISE EXCEPTION 'FAIL C01 — manca la FK turno → conversazione con ON DELETE CASCADE: la retention lascerebbe turni orfani';
  END IF;

  -- Ogni policy che decide una scrittura deve avere WITH CHECK: con il solo USING la RLS
  -- filtra la lettura e non la scrittura, e una Casa scriverebbe la Casa di un'altra.
  SELECT string_agg(tablename || '.' || policyname, ', ') INTO v_incomplete
    FROM pg_policies
   WHERE schemaname = 'trasi' AND tablename IN ('conversazione','turno')
     AND cmd IN ('ALL','INSERT','UPDATE') AND with_check IS NULL;
  IF v_incomplete IS NOT NULL THEN
    RAISE EXCEPTION 'FAIL C01 — policy senza WITH CHECK (USING da solo non è un permesso di scrittura): %', v_incomplete;
  END IF;

  SELECT count(*) INTO v_n FROM pg_policies
   WHERE schemaname = 'trasi' AND tablename = 'conversazione'
     AND policyname IN ('conv_sel_casa','conv_sel_rete','conv_ins_casa');
  IF v_n <> 3 THEN RAISE EXCEPTION 'FAIL C01 — policy client su conversazione: %, attese 3', v_n; END IF;
  SELECT count(*) INTO v_n FROM pg_policies
   WHERE schemaname = 'trasi' AND tablename = 'turno'
     AND policyname IN ('turno_sel_casa','turno_sel_rete','turno_ins_casa');
  IF v_n <> 3 THEN RAISE EXCEPTION 'FAIL C01 — policy client su turno: %, attese 3', v_n; END IF;

  RAISE NOTICE 'PASS C01 — conversazione e turno: ENABLE+FORCE RLS, FK ON DELETE CASCADE, 6 policy client tutte con USING+WITH CHECK';
END
$c01$;

-- ---------------------------------------------------------------------------
-- C02 · il trigger: titolo, ultimo_ts e scade_ts li calcola il database
--       (è l'interfaccia che lo shim consuma: `INSERT (casa_id, onyx_session_id)` + `INSERT turno`)
-- ---------------------------------------------------------------------------
DO $c02$
DECLARE
  v_conv    bigint;
  v_conv_pk int;
  v_turno   bigint;
  v_titolo  text;
  v_ultimo  timestamptz;
  v_scade   timestamptz;
  v_ts      timestamptz;
  v_fonte   text;
  v_rif     jsonb;
  v_long    text := repeat('Domanda di sportello molto lunga ', 5);   -- > 40 caratteri
BEGIN
  EXECUTE 'SET ROLE casa_sanbao';
  v_conv_pk := trasi.casa_corrente();
  INSERT INTO trasi.conversazione (casa_id, onyx_session_id)
  VALUES (v_conv_pk, 'onyx-c02')
  RETURNING id INTO v_conv;

  -- Il titolo nasce vuoto: nessuno glielo sceglie (fuori dai GRANT, C06).
  SELECT titolo INTO v_titolo FROM trasi.conversazione WHERE id = v_conv;
  IF v_titolo <> '' THEN
    RAISE EXCEPTION 'FAIL C02 — titolo alla creazione = ''%'', atteso vuoto (lo scrive il primo turno)', v_titolo;
  END IF;

  INSERT INTO trasi.turno (conversazione_id, ruolo, testo, fonte, riferimenti, onyx_message_id)
  VALUES (v_conv, 'operatore', v_long, NULL, NULL, NULL)
  RETURNING id, ts INTO v_turno, v_ts;

  SELECT titolo, ultimo_ts, scade_ts INTO v_titolo, v_ultimo, v_scade
    FROM trasi.conversazione WHERE id = v_conv;

  -- turno dell'assistente: la fonte è il badge dello shim (V3), i riferimenti i top_documents.
  INSERT INTO trasi.turno (conversazione_id, ruolo, testo, fonte, riferimenti, onyx_message_id)
  VALUES (v_conv, 'assistente', 'Risposta di prova C02', '[KB · Rete-kb-3]',
          '[{"tipo":"luogo","id":21,"nome":"CAF ACLI La Rosa"}]'::jsonb, 729);

  SELECT t.fonte, t.riferimenti INTO v_fonte, v_rif
    FROM trasi.turno t WHERE t.conversazione_id = v_conv AND t.ruolo = 'assistente';
  EXECUTE 'RESET ROLE';

  IF v_titolo <> left(v_long, 40) THEN
    RAISE EXCEPTION 'FAIL C02 — titolo = ''%'', atteso left(testo,40) = ''%''', v_titolo, left(v_long, 40);
  END IF;
  IF char_length(v_titolo) <> 40 THEN
    RAISE EXCEPTION 'FAIL C02 — titolo di % caratteri, attesi 40 (troncamento a 40)', char_length(v_titolo);
  END IF;
  -- Il rinnovo è sull'ULTIMO turno, e `ultimo_ts` è il timestamp del turno, non `now()`.
  IF v_ultimo <> v_ts THEN
    RAISE EXCEPTION 'FAIL C02 — ultimo_ts = %, atteso il ts dell''ultimo turno (%)', v_ultimo, v_ts;
  END IF;
  -- La scadenza viene dal parametro [P]: cambiarlo non richiede un deploy.
  IF v_scade <> v_ts + make_interval(days => COALESCE(trasi.p_int('gg_retention_chat'), 30)) THEN
    RAISE EXCEPTION 'FAIL C02 — scade_ts = %, atteso ts + [P] gg_retention_chat', v_scade;
  END IF;
  -- Il badge si conserva **verbatim**: è il cuore di V3, e un test che lo riformattasse
  -- passerebbe lasciando il difetto in piedi.
  IF v_fonte <> '[KB · Rete-kb-3]' THEN
    RAISE EXCEPTION 'FAIL C02 — fonte = ''%'', atteso il badge verbatim', COALESCE(v_fonte, '(NULL)');
  END IF;
  IF v_rif IS NULL OR v_rif->0->>'tipo' <> 'luogo' OR (v_rif->0->>'id')::int <> 21 THEN
    RAISE EXCEPTION 'FAIL C02 — riferimenti non conservati: %', COALESCE(v_rif::text, '(NULL)');
  END IF;

  RAISE NOTICE 'PASS C02 — trigger: titolo = left(testo,40) (% car.), ultimo_ts = ts del turno, scade_ts = ts + [P] 30gg; badge verbatim e riferimenti jsonb conservati',
    char_length(v_titolo);
END
$c02$;

-- ---------------------------------------------------------------------------
-- C03 · isolamento in lettura: Bozzano NON vede i turni di San Bao
--       (la prova è non vacua: `trasi_owner` vede le stesse righe)
-- ---------------------------------------------------------------------------
DO $c03$
DECLARE
  v_conv  bigint;
  v_owner int;
  v_sanbao int;
  v_bozzano int;
  v_join  int;
BEGIN
  EXECUTE 'SET ROLE casa_sanbao';
  INSERT INTO trasi.conversazione (casa_id, onyx_session_id)
  VALUES (trasi.casa_corrente(), 'onyx-c03')
  RETURNING id INTO v_conv;
  INSERT INTO trasi.turno (conversazione_id, ruolo, testo)
  VALUES (v_conv, 'operatore', 'C03 domanda di San Bao');
  INSERT INTO trasi.turno (conversazione_id, ruolo, testo)
  VALUES (v_conv, 'assistente', 'C03 risposta di San Bao');
  EXECUTE 'RESET ROLE';

  -- Non-vacuità: le righe esistono e sono visibili a chi ha titolo per vederle.
  EXECUTE 'SET ROLE trasi_owner';
  SELECT count(*) INTO v_owner FROM trasi.turno WHERE conversazione_id = v_conv;
  EXECUTE 'RESET ROLE';
  IF v_owner <> 2 THEN
    RAISE EXCEPTION 'FAIL C03 — fixture non creata: trasi_owner vede % turni, attesi 2', v_owner;
  END IF;

  EXECUTE 'SET ROLE casa_sanbao';
  SELECT count(*) INTO v_sanbao FROM trasi.turno WHERE conversazione_id = v_conv;
  EXECUTE 'RESET ROLE';

  EXECUTE 'SET ROLE casa_bozzano';
  SELECT count(*) INTO v_bozzano FROM trasi.turno WHERE conversazione_id = v_conv;
  -- La stessa domanda nella forma del criterio del task (join sulle due tabelle), perché è la
  -- query che uno scriverebbe davvero e deve dare lo stesso esito.
  SELECT count(*) INTO v_join
    FROM trasi.turno t JOIN trasi.conversazione c ON c.id = t.conversazione_id
   WHERE c.casa_id <> trasi.casa_corrente();
  EXECUTE 'RESET ROLE';

  IF v_sanbao <> 2 THEN
    RAISE EXCEPTION 'FAIL C03 — San Bao vede % propri turni, attesi 2', v_sanbao;
  END IF;
  IF v_bozzano <> 0 THEN
    RAISE EXCEPTION 'FAIL C03 — Bozzano vede % turni della conversazione di San Bao, attesi 0', v_bozzano;
  END IF;
  IF v_join <> 0 THEN
    RAISE EXCEPTION 'FAIL C03 — join cross-Casa: % turni di altre Case visibili a Bozzano, attesi 0', v_join;
  END IF;

  RAISE NOTICE 'PASS C03 — casa_sanbao vede 2 propri turni · casa_bozzano: 0 sulla stessa conversazione e 0 nel join cross-Casa (fixture visibile a trasi_owner: non vacua)';
END
$c03$;

-- ---------------------------------------------------------------------------
-- C04 · WITH CHECK: un turno in una conversazione di un'ALTRA Casa → 42501
--       È il caso che il piano mappa su `404` nello shim: la RLS risponde 42501, non 403
--       (403 rivelerebbe l'esistenza della conversazione).
-- ---------------------------------------------------------------------------
DO $c04$
DECLARE
  v_conv   bigint;
  v_code   text;
  v_fallito boolean := false;
BEGIN
  EXECUTE 'SET ROLE casa_sanbao';
  INSERT INTO trasi.conversazione (casa_id, onyx_session_id)
  VALUES (trasi.casa_corrente(), 'onyx-c04')
  RETURNING id INTO v_conv;
  EXECUTE 'RESET ROLE';

  EXECUTE 'SET ROLE casa_bozzano';
  BEGIN
    INSERT INTO trasi.turno (conversazione_id, ruolo, testo)
    VALUES (v_conv, 'operatore', 'C04 scrittura illecita di Bozzano');
    v_fallito := true;
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE;
  END;
  EXECUTE 'RESET ROLE';

  IF v_fallito THEN
    RAISE EXCEPTION 'FAIL C04 — casa_bozzano ha scritto un turno nella conversazione di San Bao';
  END IF;
  IF v_code <> '42501' THEN
    RAISE EXCEPTION 'FAIL C04 — respinta con % invece di 42501: non è la RLS a decidere', COALESCE(v_code, 'nessun errore');
  END IF;
  RAISE NOTICE 'PASS C04 — casa_bozzano INSERT turno nella conversazione di San Bao = 42501 (violazione di RLS, non 23514)';
END
$c04$;

-- ---------------------------------------------------------------------------
-- C05 · il controllo positivo: nella **propria** conversazione si scrive
--       (senza, C04 passerebbe anche con la tabella in sola lettura per tutti)
-- ---------------------------------------------------------------------------
DO $c05$
DECLARE
  v_conv bigint;
  v_n    int;
BEGIN
  EXECUTE 'SET ROLE casa_bozzano';
  INSERT INTO trasi.conversazione (casa_id, onyx_session_id)
  VALUES (trasi.casa_corrente(), 'onyx-c05')
  RETURNING id INTO v_conv;
  INSERT INTO trasi.turno (conversazione_id, ruolo, testo)
  VALUES (v_conv, 'operatore', 'C05 domanda di Bozzano');
  GET DIAGNOSTICS v_n = ROW_COUNT;
  EXECUTE 'RESET ROLE';
  IF v_n <> 1 THEN
    RAISE EXCEPTION 'FAIL C05 — INSERT turno nella propria conversazione = % righe, atteso 1', v_n;
  END IF;
  RAISE NOTICE 'PASS C05 — casa_bozzano INSERT conversazione + turno nella propria Casa = 1 riga';
END
$c05$;

-- ---------------------------------------------------------------------------
-- C06 · il registro non si modifica: nessun UPDATE/DELETE ai client, colonne fuori dai GRANT
-- ---------------------------------------------------------------------------
DO $c06$
DECLARE
  v_conv bigint;
  f_upd boolean := false; c_upd text;
  f_del boolean := false; c_del text;
  f_tit boolean := false; c_tit text;
  f_ts  boolean := false; c_ts  text;
  f_ret boolean := false; c_ret text;
BEGIN
  EXECUTE 'SET ROLE casa_bozzano';
  INSERT INTO trasi.conversazione (casa_id, onyx_session_id)
  VALUES (trasi.casa_corrente(), 'onyx-c06')
  RETURNING id INTO v_conv;

  -- `titolo` non è inseribile: lo calcola il trigger. Nessuno intitola una conversazione con un
  -- testo che non è la sua prima domanda.
  BEGIN
    INSERT INTO trasi.conversazione (casa_id, titolo) VALUES (trasi.casa_corrente(), 'C06 titolo scelto a mano');
    f_tit := true;
  EXCEPTION WHEN OTHERS THEN c_tit := SQLSTATE;
  END;

  BEGIN
    UPDATE trasi.conversazione SET titolo = 'C06 titolo riscritto' WHERE id = v_conv;
    f_upd := true;
  EXCEPTION WHEN OTHERS THEN c_upd := SQLSTATE;
  END;

  BEGIN
    DELETE FROM trasi.conversazione WHERE id = v_conv;
    f_del := true;
  EXCEPTION WHEN OTHERS THEN c_del := SQLSTATE;
  END;

  BEGIN
    INSERT INTO trasi.turno (conversazione_id, ruolo, testo, ts)
    VALUES (v_conv, 'operatore', 'C06 turno con ts scelto dal client', now() - interval '99 days');
    f_ts := true;
  EXCEPTION WHEN OTHERS THEN c_ts := SQLSTATE;
  END;

  -- La retention non è un DELETE manuale: la esegue solo `scadi_conversazioni()`.
  BEGIN
    PERFORM trasi.scadi_conversazioni();
    f_ret := true;
  EXCEPTION WHEN OTHERS THEN c_ret := SQLSTATE;
  END;
  EXECUTE 'RESET ROLE';

  IF f_tit THEN RAISE EXCEPTION 'FAIL C06 — una Casa ha scelto il titolo di una conversazione'; END IF;
  IF c_tit <> '42501' THEN RAISE EXCEPTION 'FAIL C06 — titolo respinto con % invece di 42501', COALESCE(c_tit,'nessun errore'); END IF;
  IF f_upd THEN RAISE EXCEPTION 'FAIL C06 — una Casa ha aggiornato una conversazione (il piano: si crea e si legge)'; END IF;
  IF c_upd <> '42501' THEN RAISE EXCEPTION 'FAIL C06 — UPDATE respinto con % invece di 42501', COALESCE(c_upd,'nessun errore'); END IF;
  IF f_del THEN RAISE EXCEPTION 'FAIL C06 — una Casa ha cancellato una conversazione'; END IF;
  IF c_del <> '42501' THEN RAISE EXCEPTION 'FAIL C06 — DELETE respinto con % invece di 42501', COALESCE(c_del,'nessun errore'); END IF;
  IF f_ts  THEN RAISE EXCEPTION 'FAIL C06 — una Casa si è scelta quando un turno è stato scritto'; END IF;
  IF c_ts <> '42501' THEN RAISE EXCEPTION 'FAIL C06 — INSERT con ts respinto con % invece di 42501', COALESCE(c_ts,'nessun errore'); END IF;
  IF f_ret THEN RAISE EXCEPTION 'FAIL C06 — una Casa ha eseguito la retention (solo automazioni/ti)'; END IF;
  IF c_ret <> '42501' THEN RAISE EXCEPTION 'FAIL C06 — scadi_conversazioni da una Casa respinta con % invece di 42501', COALESCE(c_ret,'nessun errore'); END IF;

  RAISE NOTICE 'PASS C06 — tutti 42501: titolo non inseribile · UPDATE conversazione · DELETE conversazione · INSERT turno con ts · scadi_conversazioni da un ruolo Casa';
END
$c06$;

-- ---------------------------------------------------------------------------
-- C07 · retention: la conversazione scaduta sparisce e i suoi turni con lei (cascade)
--       La fixture scrive `scade_ts` nel passato: è una colonna che nessun ruolo client può
--       scrivere (C06), e simulare il tempo che passa è esattamente ciò che la fixture deve fare.
--       Stessa via di t_messaggi.sql M10: `SET ROLE trasi_owner`, con la stessa motivazione.
-- ---------------------------------------------------------------------------
DO $c07$
DECLARE
  v_scaduta bigint;
  v_turni_prima int;
  v_del int;
  v_conv_dopo int;
  v_turni_dopo int;
BEGIN
  EXECUTE 'SET ROLE casa_sanbao';
  INSERT INTO trasi.conversazione (casa_id, onyx_session_id)
  VALUES (trasi.casa_corrente(), 'onyx-c07')
  RETURNING id INTO v_scaduta;
  INSERT INTO trasi.turno (conversazione_id, ruolo, testo) VALUES (v_scaduta, 'operatore', 'C07 domanda vecchia');
  INSERT INTO trasi.turno (conversazione_id, ruolo, testo) VALUES (v_scaduta, 'assistente', 'C07 risposta vecchia');
  INSERT INTO trasi.turno (conversazione_id, ruolo, testo) VALUES (v_scaduta, 'operatore', 'C07 domanda vecchia 2');
  EXECUTE 'RESET ROLE';

  EXECUTE 'SET ROLE trasi_owner';
  SELECT count(*) INTO v_turni_prima FROM trasi.turno WHERE conversazione_id = v_scaduta;
  UPDATE trasi.conversazione SET scade_ts = now() - interval '1 day' WHERE id = v_scaduta;
  EXECUTE 'RESET ROLE';
  IF v_turni_prima <> 3 THEN
    RAISE EXCEPTION 'FAIL C07 — fixture: % turni sulla conversazione da scadere, attesi 3', v_turni_prima;
  END IF;

  -- La retention gira col ruolo del passo notturno (`flussi/notte.sh` invoca `automazioni`,
  -- lo stesso con cui invoca `scadi_messaggi`).
  EXECUTE 'SET ROLE automazioni';
  v_del := trasi.scadi_conversazioni();
  EXECUTE 'RESET ROLE';

  EXECUTE 'SET ROLE trasi_owner';
  SELECT count(*) INTO v_conv_dopo  FROM trasi.conversazione WHERE id = v_scaduta;
  SELECT count(*) INTO v_turni_dopo FROM trasi.turno WHERE conversazione_id = v_scaduta;
  EXECUTE 'RESET ROLE';

  IF v_del < 1 THEN
    RAISE EXCEPTION 'FAIL C07 — scadi_conversazioni ha cancellato % conversazioni, attese >= 1', v_del;
  END IF;
  IF v_conv_dopo <> 0 THEN
    RAISE EXCEPTION 'FAIL C07 — la conversazione scaduta esiste ancora (% righe)', v_conv_dopo;
  END IF;
  IF v_turni_dopo <> 0 THEN
    RAISE EXCEPTION 'FAIL C07 — % turni orfani: la cancellazione non è andata in cascade', v_turni_dopo;
  END IF;

  RAISE NOTICE 'PASS C07 — scadi_conversazioni() (come automazioni) ha cancellato % conversazioni: la scaduta è sparita e i suoi 3 turni con lei (cascade)',
    v_del;
END
$c07$;

-- ---------------------------------------------------------------------------
-- C08 · una conversazione NON scaduta non viene toccata
-- ---------------------------------------------------------------------------
DO $c08$
DECLARE
  v_fresca bigint;
  v_turni_prima int;
  v_conv_dopo int;
  v_turni_dopo int;
  v_scade timestamptz;
BEGIN
  EXECUTE 'SET ROLE casa_bozzano';
  INSERT INTO trasi.conversazione (casa_id, onyx_session_id)
  VALUES (trasi.casa_corrente(), 'onyx-c08')
  RETURNING id INTO v_fresca;
  INSERT INTO trasi.turno (conversazione_id, ruolo, testo) VALUES (v_fresca, 'operatore', 'C08 domanda di oggi');
  INSERT INTO trasi.turno (conversazione_id, ruolo, testo) VALUES (v_fresca, 'assistente', 'C08 risposta di oggi');
  SELECT scade_ts INTO v_scade FROM trasi.conversazione WHERE id = v_fresca;
  EXECUTE 'RESET ROLE';
  v_turni_prima := 2;

  IF v_scade <= now() THEN
    RAISE EXCEPTION 'FAIL C08 — la conversazione appena creata nasce già scaduta (scade_ts = %)', v_scade;
  END IF;

  EXECUTE 'SET ROLE automazioni';
  PERFORM trasi.scadi_conversazioni();
  EXECUTE 'RESET ROLE';

  EXECUTE 'SET ROLE casa_bozzano';
  SELECT count(*) INTO v_conv_dopo  FROM trasi.conversazione WHERE id = v_fresca;
  SELECT count(*) INTO v_turni_dopo FROM trasi.turno WHERE conversazione_id = v_fresca;
  EXECUTE 'RESET ROLE';

  IF v_conv_dopo <> 1 THEN
    RAISE EXCEPTION 'FAIL C08 — la retention ha cancellato una conversazione non scaduta (% righe)', v_conv_dopo;
  END IF;
  IF v_turni_dopo <> v_turni_prima THEN
    RAISE EXCEPTION 'FAIL C08 — turni della conversazione non scaduta: %, attesi %', v_turni_dopo, v_turni_prima;
  END IF;

  RAISE NOTICE 'PASS C08 — la conversazione non scaduta resta (1 riga, % turni intatti) dopo la retention', v_turni_dopo;
END
$c08$;

-- C10 · il tetto del testo: 2000 sulla domanda, nessuno sulla risposta generata
--       Un CHECK incondizionato qui sarebbe una costante inventata: la risposta di Onyx è
--       generata e non ha tetto a monte, quindi un limite sull'assistente trasformerebbe una
--       risposta lunga in un `23514` — cioè la chat che smette di funzionare.
DO $c10$
DECLARE
  v_conv   bigint;
  v_lunga  text := repeat('Risposta lunga dell''assistente. ', 400);   -- ~12 000 caratteri
  v_n      int;
  v_titolo text;
  f_vuoto  boolean := false; c_vuoto text;
  f_ope    boolean := false; c_ope   text;
BEGIN
  EXECUTE 'SET ROLE casa_sanbao';
  INSERT INTO trasi.conversazione (casa_id, onyx_session_id)
  VALUES (trasi.casa_corrente(), 'onyx-c10')
  RETURNING id INTO v_conv;

  -- La risposta lunga entra: è il caso che il CHECK incondizionato avrebbe respinto.
  INSERT INTO trasi.turno (conversazione_id, ruolo, testo, fonte)
  VALUES (v_conv, 'assistente', v_lunga, '[KB · Rete-kb-3]');
  GET DIAGNOSTICS v_n = ROW_COUNT;
  IF v_n <> 1 THEN
    RAISE EXCEPTION 'FAIL C10 — risposta lunga (% caratteri) rifiutata: la chat si rompe su un testo generato', char_length(v_lunga);
  END IF;

  -- La domanda oltre 2000 caratteri è invece respinta dal DB: secondo presidio, non il primo.
  BEGIN
    INSERT INTO trasi.turno (conversazione_id, ruolo, testo)
    VALUES (v_conv, 'operatore', repeat('x', 2001));
    f_ope := true;
  EXCEPTION WHEN OTHERS THEN c_ope := SQLSTATE;
  END;

  -- Testo vuoto: mai, in nessun ruolo.
  BEGIN
    INSERT INTO trasi.turno (conversazione_id, ruolo, testo)
    VALUES (v_conv, 'assistente', '');
    f_vuoto := true;
  EXCEPTION WHEN OTHERS THEN c_vuoto := SQLSTATE;
  END;

  -- C10 mette un turno dell'assistente **prima** di qualsiasi domanda: qui è il caso in cui un
  -- titolo preso dall'assistente sarebbe sbagliato (direbbe cosa ha risposto, non cosa si è
  -- chiesto). Poi arriva la domanda, che intitola.
  SELECT titolo INTO v_titolo FROM trasi.conversazione WHERE id = v_conv;
  IF v_titolo <> '' THEN
    RAISE EXCEPTION 'FAIL C10 — un turno dell''assistente ha intitolato la conversazione (''%'')', v_titolo;
  END IF;
  INSERT INTO trasi.turno (conversazione_id, ruolo, testo)
  VALUES (v_conv, 'operatore', 'Dove si fa l''ISEE vicino a La Rosa?');
  SELECT titolo INTO v_titolo FROM trasi.conversazione WHERE id = v_conv;
  IF v_titolo <> 'Dove si fa l''ISEE vicino a La Rosa?' THEN
    RAISE EXCEPTION 'FAIL C10 — la domanda non ha intitolato la conversazione (titolo: ''%'')', v_titolo;
  END IF;
  EXECUTE 'RESET ROLE';

  IF f_ope THEN RAISE EXCEPTION 'FAIL C10 — una domanda di 2001 caratteri è stata accettata'; END IF;
  IF c_ope <> '23514' THEN RAISE EXCEPTION 'FAIL C10 — domanda oltre 2000 respinta con % invece di 23514', COALESCE(c_ope,'nessun errore'); END IF;
  IF f_vuoto THEN RAISE EXCEPTION 'FAIL C10 — un turno vuoto è stato accettato'; END IF;
  IF c_vuoto <> '23514' THEN RAISE EXCEPTION 'FAIL C10 — turno vuoto respinto con % invece di 23514', COALESCE(c_vuoto,'nessun errore'); END IF;

  RAISE NOTICE 'PASS C10 — risposta assistente di % caratteri accettata (nessun tetto sul generato) · domanda di 2001 → 23514 · turno vuoto → 23514',
    char_length(v_lunga);
END
$c10$;

-- C11 · il titolo troncato a 40 caratteri: il testo resta intero, si accorcia solo l'etichetta
DO $c11$
DECLARE
  v_conv   bigint;
  v_lunga  text := repeat('Domanda lunga ', 20);      -- 280 caratteri
  v_titolo text;
  v_testo  text;
BEGIN
  EXECUTE 'SET ROLE casa_bozzano';
  INSERT INTO trasi.conversazione (casa_id, onyx_session_id)
  VALUES (trasi.casa_corrente(), 'onyx-c11')
  RETURNING id INTO v_conv;
  INSERT INTO trasi.turno (conversazione_id, ruolo, testo)
  VALUES (v_conv, 'operatore', v_lunga);

  SELECT c.titolo, t.testo INTO v_titolo, v_testo
    FROM trasi.conversazione c JOIN trasi.turno t ON t.conversazione_id = c.id
   WHERE c.id = v_conv;
  EXECUTE 'RESET ROLE';

  IF char_length(v_titolo) <> 40 THEN
    RAISE EXCEPTION 'FAIL C11 — titolo = % caratteri, attesi 40', char_length(v_titolo);
  END IF;
  IF v_titolo <> left(v_lunga, 40) THEN
    RAISE EXCEPTION 'FAIL C11 — il titolo non è il prefisso della prima domanda';
  END IF;
  -- Il turno conserva il testo **intero**: il troncamento è un'etichetta, non una perdita di dato.
  IF v_testo <> v_lunga THEN
    RAISE EXCEPTION 'FAIL C11 — il testo del turno è stato troncato (% caratteri, attesi %)',
      char_length(v_testo), char_length(v_lunga);
  END IF;
  RAISE NOTICE 'PASS C11 — conversazione di % caratteri intitolata con i primi 40; il turno conserva il testo intero', char_length(v_lunga);
END
$c11$;

-- ---------------------------------------------------------------------------
-- C09 · `rete` e `ti` leggono tutto: la chat del territorio non è di una Casa sola
--       (una policy che sembra un permesso e dà 0 righe sarebbe un divieto silenzioso:
--        `casa_corrente()` è NULL per entrambi, quindi non possono passare da `conv_sel_casa`)
-- ---------------------------------------------------------------------------
DO $c09$
DECLARE
  v_conv bigint;
  v_n int;
BEGIN
  EXECUTE 'SET ROLE casa_sanbao';
  INSERT INTO trasi.conversazione (casa_id, onyx_session_id)
  VALUES (trasi.casa_corrente(), 'onyx-c09')
  RETURNING id INTO v_conv;
  INSERT INTO trasi.turno (conversazione_id, ruolo, testo) VALUES (v_conv, 'operatore', 'C09 domanda di San Bao');
  EXECUTE 'RESET ROLE';

  EXECUTE 'SET ROLE rete';
  SELECT count(*) INTO v_n FROM trasi.conversazione WHERE id = v_conv;
  IF v_n <> 1 THEN RAISE EXCEPTION 'FAIL C09 — rete vede % conversazioni di San Bao, attesa 1', v_n; END IF;
  SELECT count(*) INTO v_n FROM trasi.turno WHERE conversazione_id = v_conv;
  IF v_n <> 1 THEN RAISE EXCEPTION 'FAIL C09 — rete vede % turni di San Bao, atteso 1', v_n; END IF;
  EXECUTE 'RESET ROLE';

  EXECUTE 'SET ROLE ti';
  SELECT count(*) INTO v_n FROM trasi.conversazione WHERE id = v_conv;
  IF v_n <> 1 THEN RAISE EXCEPTION 'FAIL C09 — ti vede % conversazioni di San Bao, attesa 1', v_n; END IF;
  EXECUTE 'RESET ROLE';

  RAISE NOTICE 'PASS C09 — rete e ti leggono la conversazione di San Bao (1 riga, 1 turno per rete): la RLS non li tratta come una Casa';
END
$c09$;
