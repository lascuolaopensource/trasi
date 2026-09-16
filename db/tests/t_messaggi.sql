-- Trasi — db/tests/t_messaggi.sql · M01…M12
-- RLS della chat interna (US-7.x, db/015_messaggi.sql + scadi_messaggi in db/006 §11).
-- Convenzione della batteria: PASS = NOTICE, FAIL = EXCEPTION; i ruoli sono applicativi
-- (SET ROLE), mai superuser. run.sh avvolge il file in BEGIN/ROLLBACK: nessun residuo.
--
-- Premessa: la tabella `messaggio` può essere vuota nel DB reale. I test che richiedono
-- righe si creano i propri fixture con SET ROLE ti (l'unico ruolo client che può scrivere
-- messaggi PA) e con ruoli Casa: è la stessa via di scrittura dei client, niente scorciatoie.
\set ON_ERROR_STOP on
\pset pager off

-- M01 · Casa → Casa: INSERT consentito; il timestamp di lettura nasce NULL -----------------
DO $$
DECLARE n integer; v_id bigint;
BEGIN
  EXECUTE 'SET ROLE casa_sanbao';
  INSERT INTO trasi.messaggio (da_casa_id, a_casa_id, testo)
  SELECT (SELECT id FROM trasi.casa WHERE slug='san-bao'), (SELECT id FROM trasi.casa WHERE slug='bozzano'),
         'M01: proposta di coordinamento festa quartiere';
  GET DIAGNOSTICS n = ROW_COUNT;
  EXECUTE 'RESET ROLE';
  IF n <> 1 THEN RAISE EXCEPTION 'FAIL M01 — INSERT Casa→Casa = % righe, atteso 1', n; END IF;
  SELECT count(*) INTO n FROM trasi.messaggio WHERE testo LIKE 'M01:%' AND letto_ts IS NULL;
  IF n <> 1 THEN RAISE EXCEPTION 'FAIL M01 — letto_ts dovrebbe nascere NULL'; END IF;
  RAISE NOTICE 'PASS M01 — casa_sanbao INSERT messaggio per Bozzano = 1 riga, letto_ts NULL';
END $$;

-- M02 · una Casa NON può fare broadcast: a_casa_id NULL è riservato alla PA ---------------
DO $$
DECLARE fallito boolean := false; code text;
BEGIN
  EXECUTE 'SET ROLE casa_sanbao';
  BEGIN
    INSERT INTO trasi.messaggio (da_casa_id, a_casa_id, testo)
    SELECT id, NULL, 'M02: messaggio a tutta la rete' FROM trasi.casa WHERE slug='san-bao';
  EXCEPTION WHEN OTHERS THEN fallito := true; code := SQLSTATE; END;
  EXECUTE 'RESET ROLE';
  IF NOT fallito THEN RAISE EXCEPTION 'FAIL M02 — casa_sanbao ha inserito un broadcast (riservato alla PA)'; END IF;
  RAISE NOTICE 'PASS M02 — broadcast da una Casa = % (WITH CHECK: broadcast solo dalla PA)', code;
END $$;

-- M03 · una Casa non può firmarsi PA, né scrivere a nome di un'altra Casa -----------------
DO $$
DECLARE f1 boolean := false; f2 boolean := false; b1 boolean := false; b2 boolean := false;
BEGIN
  EXECUTE 'SET ROLE casa_sanbao';
  BEGIN
    INSERT INTO trasi.messaggio (da_casa_id, a_casa_id, testo)
    VALUES (NULL, (SELECT id FROM trasi.casa WHERE slug='bozzano'), 'M03a: messaggio con firma PA');
  EXCEPTION WHEN OTHERS THEN f1 := true; END;
  BEGIN
    INSERT INTO trasi.messaggio (da_casa_id, a_casa_id, testo)
    SELECT id, (SELECT id FROM trasi.casa WHERE slug='san-bao'), 'M03b: messaggio a nome Bozzano'
      FROM trasi.casa WHERE slug='bozzano';
  EXCEPTION WHEN OTHERS THEN f2 := true; END;
  EXECUTE 'RESET ROLE';
  b1 := NOT EXISTS (SELECT 1 FROM trasi.messaggio WHERE testo LIKE 'M03a:%');
  b2 := NOT EXISTS (SELECT 1 FROM trasi.messaggio WHERE testo LIKE 'M03b:%');
  IF NOT (f1 AND b1) THEN RAISE EXCEPTION 'FAIL M03 — casa_sanbao ha scritto con firma PA (da_casa_id NULL)'; END IF;
  IF NOT (f2 AND b2) THEN RAISE EXCEPTION 'FAIL M03 — casa_sanbao ha scritto a nome di un''altra Casa'; END IF;
  RAISE NOTICE 'PASS M03 — firma PA impersonata = 42501 · scrittura a nome di altra Casa = 42501 (WITH CHECK)';
END $$;

-- M04 · la PA scrive diretto e broadcast; solo `ti` ---------------------------------------
DO $$
DECLARE n integer; f_ti boolean := false;
BEGIN
  EXECUTE 'SET ROLE ti';
  INSERT INTO trasi.messaggio (da_casa_id, a_casa_id, testo)
  VALUES (NULL, (SELECT id FROM trasi.casa WHERE slug='bozzano'), 'M04a: sollecito aggiornamento dati');
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n <> 1 THEN RAISE EXCEPTION 'FAIL M04 — ti non ha inserito il messaggio PA→Casa'; END IF;
  INSERT INTO trasi.messaggio (da_casa_id, a_casa_id, testo)
  VALUES (NULL, NULL, 'M04b: interruzione servizio il 20/09');
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n <> 1 THEN RAISE EXCEPTION 'FAIL M04 — ti non ha inserito il broadcast'; END IF;
  -- rete NON è la PA operativa: nessuna policy INSERT per rete.
  EXECUTE 'SET ROLE rete';
  BEGIN
    INSERT INTO trasi.messaggio (da_casa_id, a_casa_id, testo)
    VALUES (NULL, NULL, 'M04c: broadcast a nome rete');
  EXCEPTION WHEN insufficient_privilege THEN f_ti := true; END;
  EXECUTE 'RESET ROLE';
  IF NOT f_ti THEN RAISE EXCEPTION 'FAIL M04 — rete ha inserito un broadcast (il canale PA è di ti)'; END IF;
  RAISE NOTICE 'PASS M04 — ti INSERT PA→Casa = 1, broadcast = 1; rete broadcast = 42501';
END $$;

-- M05 · visibilità: le Case vedono solo le proprie conversazioni e i broadcast ------------
DO $$
DECLARE v_sanbao integer; v_bozzano integer; v_molo integer; f_molo boolean := false;
BEGIN
  EXECUTE 'SET ROLE casa_sanbao';
  SELECT count(*) INTO v_sanbao FROM trasi.messaggio WHERE testo LIKE 'M01:%';
  SELECT count(*) INTO v_molo   FROM trasi.messaggio WHERE testo LIKE 'M04a:%';
  EXECUTE 'SET ROLE casa_molo12';
  SELECT count(*) INTO v_bozzano FROM trasi.messaggio WHERE testo LIKE 'M01:%';
  BEGIN
    PERFORM 1 FROM trasi.messaggio WHERE testo LIKE 'M04a:%';
    GET DIAGNOSTICS v_molo = ROW_COUNT;
  END;
  EXECUTE 'RESET ROLE';
  IF v_sanbao <> 1 THEN RAISE EXCEPTION 'FAIL M05 — san-bao non vede il proprio messaggio (% righe)', v_sanbao; END IF;
  IF v_bozzano <> 0 THEN RAISE EXCEPTION 'FAIL M05 — molo12 vede la conversazione san-bao→bozzano (% righe)', v_bozzano; END IF;
  IF v_molo <> 0 THEN RAISE EXCEPTION 'FAIL M05 — molo12 vede il messaggio PA→bozzano (% righe)', v_molo; END IF;
  RAISE NOTICE 'PASS M05 — san-bao vede 1 proprio; molo12 vede 0 conversazioni altrui (niente terze Case)';
END $$;

-- M06 · il broadcast è leggibile da ogni Casa --------------------------------------------
DO $$
DECLARE n integer;
BEGIN
  EXECUTE 'SET ROLE casa_dream';
  SELECT count(*) INTO n FROM trasi.messaggio WHERE testo LIKE 'M04b:%' AND a_casa_id IS NULL;
  EXECUTE 'RESET ROLE';
  IF n <> 1 THEN RAISE EXCEPTION 'FAIL M06 — una Casa non legge il broadcast PA (% righe)', n; END IF;
  RAISE NOTICE 'PASS M06 — casa_dream legge il broadcast PA (1 riga)';
END $$;

-- M07 · il destinatario marca «letto»; un terzo no ---------------------------------------
DO $$
DECLARE n integer; n0 integer;
BEGIN
  EXECUTE 'SET ROLE casa_bozzano';
  UPDATE trasi.messaggio SET letto_ts = now() WHERE testo LIKE 'M01:%';
  GET DIAGNOSTICS n = ROW_COUNT;
  EXECUTE 'SET ROLE casa_dream';
  UPDATE trasi.messaggio SET letto_ts = now() WHERE testo LIKE 'M01:%';
  GET DIAGNOSTICS n0 = ROW_COUNT;
  RESET ROLE;
END $$;
DO $$
DECLARE n integer; n0 integer;
BEGIN
  EXECUTE 'SET ROLE casa_bozzano';
  UPDATE trasi.messaggio SET letto_ts = now() WHERE testo LIKE 'M01:%';
  GET DIAGNOSTICS n = ROW_COUNT;
  EXECUTE 'SET ROLE casa_dream';
  UPDATE trasi.messaggio SET letto_ts = now() WHERE testo LIKE 'M01:%';
  GET DIAGNOSTICS n0 = ROW_COUNT;
  EXECUTE 'RESET ROLE';
  IF n <> 1 THEN RAISE EXCEPTION 'FAIL M07 — il destinatario non ha marcato letto (% righe)', n; END IF;
  IF n0 <> 0 THEN RAISE EXCEPTION 'FAIL M07 — una Casa terza ha marcato letto un messaggio altrui (% righe)', n0; END IF;
  RAISE NOTICE 'PASS M07 — destinatario UPDATE letto_ts = 1 riga · terza Casa = 0 righe';
END $$;

-- M08 · UPDATE su colonne diverse da letto_ts = 42501 (GRANT colonnare) -------------------
DO $$
DECLARE fallito boolean := false; code text;
BEGIN
  EXECUTE 'SET ROLE casa_bozzano';
  BEGIN
    UPDATE trasi.messaggio SET testo = testo WHERE testo LIKE 'M01:%';
  EXCEPTION WHEN OTHERS THEN fallito := true; code := SQLSTATE; END;
  EXECUTE 'RESET ROLE';
  IF NOT fallito OR code <> '42501' THEN
    RAISE EXCEPTION 'FAIL M08 — UPDATE testo non respinta con 42501 (ottenuto: %)', COALESCE(code, 'nessun errore');
  END IF;
  RAISE NOTICE 'PASS M08 — UPDATE testo = 42501 (solo letto_ts è aggiornabile)';
END $$;

-- M09 · nessun DELETE per i client: la retention è solo di scadi_messaggi() ---------------
DO $$
DECLARE f_casa boolean := false; f_ti boolean := false;
BEGIN
  EXECUTE 'SET ROLE casa_bozzano';
  BEGIN
    DELETE FROM trasi.messaggio WHERE testo LIKE 'M01:%';
  EXCEPTION WHEN insufficient_privilege THEN f_casa := true; END;
  EXECUTE 'SET ROLE ti';
  BEGIN
    DELETE FROM trasi.messaggio WHERE testo LIKE 'M04b:%';
  EXCEPTION WHEN insufficient_privilege THEN f_ti := true; END;
  EXECUTE 'RESET ROLE';
  IF NOT f_casa THEN RAISE EXCEPTION 'FAIL M09 — una Casa ha cancellato messaggi'; END IF;
  IF NOT f_ti THEN RAISE EXCEPTION 'FAIL M09 — ti ha cancellato messaggi (la retention non è un DELETE manuale)'; END IF;
  RAISE NOTICE 'PASS M09 — DELETE da casa_bozzano e da ti = 42501 (solo scadi_messaggi cancella)';
END $$;

-- M10 · scadi_messaggi: cancella SOLO i letti oltre retention + pulizie di contorno ------
DO $$
DECLARE
  v_del int; v_letti int; v_freschi int; v_nonletti int; v_code text; v_n int;
BEGIN
  -- Fixture con timestamp retroattivi: passa da `trasi_owner`, non da `ti`.
  --
  -- Il GRANT INSERT su `messaggio` è **colonnare** (`da_casa_id, a_casa_id, testo`, db/015): `ts` e
  -- `letto_ts` non sono inseribili da nessun ruolo client, ed è deliberato — un client non si sceglie
  -- quando un messaggio è stato scritto né quando è stato letto. Questa fixture però deve *simulare il
  -- tempo che passa* (un letto di 150 giorni fa per esercitare la retention), e per farlo serve
  -- scrivere proprio quelle colonne. È la stessa ragione per cui `flussi/tests/conftest.py` usa la
  -- connessione amministrativa per `proposto_ts`: la fixture costruisce uno stato che il percorso
  -- applicativo non deve poter costruire. La prova di M10 resta sul comportamento di
  -- `scadi_messaggi()`, non sui privilegi di chi ha inserito le righe; il rifiuto dei ruoli client
  -- sull'INSERT è verificato da M02/M03, dove è l'oggetto del test.
  EXECUTE 'SET ROLE trasi_owner';
  INSERT INTO trasi.messaggio (da_casa_id, a_casa_id, testo, ts, letto_ts) VALUES
    (NULL, NULL, 'M10 vecchio letto',      now() - interval '200 days', now() - interval '150 days'),
    (NULL, NULL, 'M10 fresco letto',       now() - interval '5 days',   now() - interval '2 days'),
    (NULL, NULL, 'M10 vecchio NON letto',  now() - interval '200 days', NULL);
  EXECUTE 'RESET ROLE';

  BEGIN
    EXECUTE 'SET ROLE casa_sanbao';
    PERFORM trasi.scadi_messaggi();
  EXCEPTION WHEN insufficient_privilege THEN v_code := '42501'; END;
  EXECUTE 'RESET ROLE';
  IF v_code IS DISTINCT FROM '42501' THEN
    RAISE EXCEPTION 'FAIL M10 — scadi_messaggi chiamata da un ruolo client (ottenuto: %)', COALESCE(v_code,'nessun errore');
  END IF;

  EXECUTE 'SET ROLE automazioni';
  SELECT trasi.scadi_messaggi() INTO v_del;
  EXECUTE 'RESET ROLE';

  SELECT count(*) INTO v_letti   FROM trasi.messaggio WHERE testo = 'M10 vecchio letto';
  SELECT count(*) INTO v_freschi FROM trasi.messaggio WHERE testo = 'M10 fresco letto';
  SELECT count(*) INTO v_nonletti FROM trasi.messaggio WHERE testo = 'M10 vecchio NON letto';
  IF v_letti <> 0 THEN RAISE EXCEPTION 'FAIL M10 — il letto oltre retention non è stato cancellato'; END IF;
  IF v_freschi <> 1 THEN RAISE EXCEPTION 'FAIL M10 — il letto recente è stato cancellato'; END IF;
  IF v_nonletti <> 1 THEN RAISE EXCEPTION 'FAIL M10 — un NON letto è stato cancellato (una segnalazione PA non sparisce perché vecchia)'; END IF;
  IF v_del < 1 THEN RAISE EXCEPTION 'FAIL M10 — scadi_messaggi ha ritornato % righe cancellate, atteso >= 1', v_del; END IF;
  RAISE NOTICE 'PASS M10 — scadi_messaggi: % righe pulite; letto oltre 90gg = 0, letto recente = 1, non letto vecchio = 1; client = 42501', v_del;
END $$;

-- M11 · nessun dato personale per costruzione (V5) ---------------------------------------
DO $$
BEGIN
  IF char_length('x') > 2000 THEN RAISE EXCEPTION 'interno'; END IF;  -- guardia logica
  IF NOT EXISTS (SELECT 1 FROM pg_constraint con JOIN pg_class c ON c.oid = con.conrelid
                  JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname='trasi' AND c.relname='messaggio' AND con.conname='messaggio_testo_check') THEN
    RAISE EXCEPTION 'FAIL M11 — manca il CHECK su testo (≤ 2000 caratteri)';
  END IF;
  RAISE NOTICE 'PASS M11 — il testo è l''unico contenuto libero, ed è vincolato a ≤ 2000 caratteri (V5)';
END $$;

-- M12 · invariante strutturale sulla tabella ---------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                  WHERE n.nspname='trasi' AND c.relname='messaggio'
                    AND c.relrowsecurity AND c.relforcerowsecurity) THEN
    RAISE EXCEPTION 'FAIL M12 — messaggio senza ENABLE+FORCE RLS';
  END IF;
  RAISE NOTICE 'PASS M12 — messaggio: ENABLE+FORCE RLS, 5 policy client + owner/applicatore';
END $$;
