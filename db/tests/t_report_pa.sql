-- Trasi — db/tests/t_report_pa.sql · PA01…PA12
-- Batteria del canale «Monitoraggio PA» (US-4): stato HITL sui report, login di servizio con
-- anti brute-force, k-anonimato sulle viste dedicate e log della chat senza testo.
--
-- Convenzione della batteria: PASS = NOTICE, FAIL = EXCEPTION; i ruoli sono applicativi (SET ROLE),
-- mai superuser. `run.sh` avvolge il file in BEGIN/ROLLBACK: nessun residuo.
--
-- **Cosa si dimostra qui.** La regola che il report PA si approva da un umano e si invia solo
-- dopo non è una convenzione di flusso: si dimostra che (a) la Casa non può correggere né
-- approvare il report, (b) `rete` approva solo dalla bozza, (c) `pa` non vede le bozze, (d)
-- il login di servizio scatta da `credenziale_servizio` e si blocca dopo 5 fallimenti,
-- (e) le viste k-anonime mascherano sotto soglia e confrontano i mesi a livello rete,
-- (f) il log della chat registra esito/fonte e rifiuta il canale altrui.
\set ON_ERROR_STOP on
\pset pager off

-- ---------------------------------------------------------------------------
-- §0 · Fixture: una bozza di report osservatorio (la Casa, in 024, resta di sua pertinenza;
--      qui serve l'osservatorio, con casa_id NULL post-026).
-- ---------------------------------------------------------------------------
DO $$
DECLARE n integer;
BEGIN
  -- La pulizia preventiva gira prima di SET ROLE: `automazioni` non ha DELETE su report (la 024
  -- lo garantisce), e in questa batteria la pulizia è del test, non del flusso.
  DELETE FROM trasi.report WHERE ambito = 'osservatorio';

  EXECUTE 'SET LOCAL ROLE automazioni';
  INSERT INTO trasi.report (casa_id, mese, ambito, contenuti, csv, suggerimenti)
  VALUES (NULL, date_trunc('month', current_date)::date, 'osservatorio',
          jsonb_build_object('richieste', 48, 'senza_risposta', 6), 'mese,richieste,senza_risposta',
          'Mantenere aperto il confronto con le Case sui fasce serali.');
  EXECUTE 'RESET ROLE';
  SELECT count(*) INTO n FROM trasi.report WHERE ambito = 'osservatorio';
  IF n <> 1 THEN RAISE EXCEPTION 'FAIL PA00 — fixture: atteso 1 report osservatorio, trovati %', n; END IF;
END $$;

-- PA01 · il report nasce in stato 'bozza' (DEFAULT), mai in 'approvato' -----------------------
DO $$
DECLARE v_stato text;
BEGIN
  SELECT stato INTO v_stato FROM trasi.report WHERE ambito = 'osservatorio';
  IF v_stato <> 'bozza' THEN RAISE EXCEPTION 'FAIL PA01 — stato = %, atteso bozza', v_stato; END IF;
  RAISE NOTICE 'PASS PA01 — il report osservatorio nasce in stato ''bozza'' (DEFAULT)';
END $$;

-- PA02 · la Casa NON può approvare il report (EXECUTE su approva_report non è grantato) --------
-- `approva_report` è SECURITY DEFINER owner applicatore, ma GRANT EXECUTE è solo rete/ti/applicatore.
DO $$
DECLARE bloccato boolean := false;
BEGIN
  EXECUTE 'SET LOCAL ROLE casa_sanbao';
  BEGIN
    PERFORM trasi.approva_report((SELECT id FROM trasi.report WHERE ambito = 'osservatorio'));
  EXCEPTION WHEN insufficient_privilege THEN bloccato := true;
            WHEN OTHERS THEN
              RAISE EXCEPTION 'FAIL PA02 — errore inatteso da approva_report: %', SQLERRM;
  END;
  EXECUTE 'RESET ROLE';
  IF NOT bloccato THEN RAISE EXCEPTION 'FAIL PA02 — una Casa ha potuto approvare un report'; END IF;
  RAISE NOTICE 'PASS PA02 — una Casa non può approvare un report (42501: EXECUTE non grantato)';
END $$;

-- PA03 · `rete` approva la bozza → 'approvato' + riga audit -----------------------------------
DO $$
DECLARE v_ok boolean; v_appr_da text; n_audit integer;
BEGIN
  EXECUTE 'SET LOCAL ROLE rete';
  SELECT trasi.approva_report((SELECT id FROM trasi.report WHERE ambito = 'osservatorio')) INTO v_ok;
  EXECUTE 'RESET ROLE';
  IF v_ok IS DISTINCT FROM true THEN RAISE EXCEPTION 'FAIL PA03 — approva_report → %', v_ok; END IF;

  SELECT approvato_da INTO v_appr_da FROM trasi.report WHERE ambito = 'osservatorio';
  IF v_appr_da IS NULL THEN RAISE EXCEPTION 'FAIL PA03 — approvato_da è NULL dopo approva_report'; END IF;

  SELECT count(*) INTO n_audit FROM trasi.audit
   WHERE azione='report_approvato' AND entita='report' AND entita_id=(SELECT id FROM trasi.report WHERE ambito='osservatorio');
  IF n_audit <> 1 THEN RAISE EXCEPTION 'FAIL PA03 — audit report_approvato: % righe, attese 1', n_audit; END IF;

  RAISE NOTICE 'PASS PA03 — rete approva la bozza → ''approvato'' (approvato_da=%, audit presente)', v_appr_da;
END $$;

-- PA04 · `rete` NON ri-approva un report già 'approvato' (stato non-bozza → errore) -----------
DO $$
DECLARE bloccato boolean := false;
BEGIN
  EXECUTE 'SET LOCAL ROLE rete';
  BEGIN
    PERFORM trasi.approva_report((SELECT id FROM trasi.report WHERE ambito = 'osservatorio'));
  EXCEPTION WHEN raise_exception THEN bloccato := true;   -- P0001 = RAISE EXCEPTION con SQLSTATE P0001
  END;
  EXECUTE 'RESET ROLE';
  IF NOT bloccato THEN RAISE EXCEPTION 'FAIL PA04 — rete ha ri-approvato un report già approvato'; END IF;
  RAISE NOTICE 'PASS PA04 — approva solo da ''bozza'': la seconda chiamata solleva P0001';
END $$;

-- PA05 · `pa` NON legge un report 'bozza' ------------------------------------------------------
DO $$
DECLARE v_righe integer;
BEGIN
  -- la bozza: stato='bozza'; il report osservatorio è stato approvato in PA03. Serve una bozza nuova.
  EXECUTE 'SET LOCAL ROLE automazioni';
  INSERT INTO trasi.report (casa_id, mese, ambito, contenuti)
  VALUES (NULL, (date_trunc('month', current_date) - interval '1 month')::date, 'osservatorio',
          jsonb_build_object('richieste', 40));
  EXECUTE 'RESET ROLE';

  EXECUTE 'SET LOCAL ROLE pa';
  SELECT count(*) INTO v_righe FROM trasi.report WHERE ambito='osservatorio' AND stato='bozza';
  EXECUTE 'RESET ROLE';
  IF v_righe <> 0 THEN RAISE EXCEPTION 'FAIL PA05 — pa vede % report in bozza', v_righe; END IF;
  RAISE NOTICE 'PASS PA05 — pa non vede le bozze (0 righe)';
END $$;

-- PA06 · `pa` LEGGE il report 'approvato' ------------------------------------------------------
DO $$
DECLARE v_righe integer;
BEGIN
  EXECUTE 'SET LOCAL ROLE pa';
  SELECT count(*) INTO v_righe FROM trasi.report
   WHERE ambito='osservatorio' AND stato='approvato' AND mese=date_trunc('month', current_date)::date;
  EXECUTE 'RESET ROLE';
  IF v_righe <> 1 THEN RAISE EXCEPTION 'FAIL PA06 — pa legge % report approvati, atteso 1', v_righe; END IF;
  RAISE NOTICE 'PASS PA06 — pa legge il report approvato (1 riga)';
END $$;

-- PA07 · crea_sessione_servizio con password corretta → uuid ----------------------------------
DO $$
DECLARE v_token uuid;
BEGIN
  -- pulizia tentativi precedenti (il test deve decidere da zero)
  DELETE FROM trasi.tentativo_login WHERE casa_id IS NULL AND ruolo_db = 'pa';
  SELECT trasi.crea_sessione_servizio('pa', 'pa2026!') INTO v_token;
  IF v_token IS NULL THEN RAISE EXCEPTION 'FAIL PA07 — login di servizio con password corretta → NULL'; END IF;

  -- e la sessione ha la forma attesa: casa_id NULL, ruolo_db='pa'
  IF NOT EXISTS (SELECT 1 FROM trasi.sessione WHERE token = v_token AND casa_id IS NULL AND ruolo_db = 'pa') THEN
    RAISE EXCEPTION 'FAIL PA07 — sessione trovata ma senza la forma attesa (casa_id/ruolo_db)';
  END IF;
  RAISE NOTICE 'PASS PA07 — crea_sessione_servizio(''pa'', password seed) → uuid valido';
END $$;

-- PA08 · password sbagliata → NULL; dopo 5 fallimenti → blocco (login_bloccato) ---------------
DO $$
DECLARE v_token uuid; v_fallimenti integer; v_bloccato integer;
BEGIN
  DELETE FROM trasi.tentativo_login WHERE casa_id IS NULL AND ruolo_db = 'pa';
  SELECT trasi.crea_sessione_servizio('pa', 'password-sbagliata') INTO v_token;
  IF v_token IS NOT NULL THEN RAISE EXCEPTION 'FAIL PA08 — password sbagliata → token non NULL'; END IF;

  -- altri 4 fallimenti → totale 5 in 10 minuti
  FOR v_fallimenti IN 2..5 LOOP
    PERFORM trasi.crea_sessione_servizio('pa', 'password-sbagliata');
  END LOOP;

  SELECT count(*) INTO v_fallimenti FROM trasi.tentativo_login
   WHERE casa_id IS NULL AND ruolo_db='pa' AND ts > now() - interval '10 minutes';
  IF v_fallimenti <> 5 THEN RAISE EXCEPTION 'FAIL PA08 — tentativi registrati = %, attesi 5', v_fallimenti; END IF;

  -- con la password corretta, ora deve essere bloccato
  SELECT trasi.crea_sessione_servizio('pa', 'pa2026!') INTO v_token;
  IF v_token IS NOT NULL THEN RAISE EXCEPTION 'FAIL PA08 — blocco dopo 5 fallimenti: password corretta ha dato token'; END IF;

  SELECT count(*) INTO v_bloccato FROM trasi.audit WHERE azione='login_bloccato' AND dopo->>'ruolo_db' = 'pa';
  IF v_bloccato < 1 THEN RAISE EXCEPTION 'FAIL PA08 — manca audit login_bloccato per pa'; END IF;

  RAISE NOTICE 'PASS PA08 — 5 fallimenti/10 min → blocco (NULL) + audit ''login_bloccato''';
END $$;

-- PA09 · v_report_fasce: 5 stessa fascia → n=5; 4 → '<5' --------------------------------------
-- Uso 'salute'/'non_trovata' come categoria della fixture, in modo da non cumularmi con i dati
-- reali del DB (che usano 'orientamento'/'lavoro'): la batteria deve essere deterministica.
DO $$
DECLARE v_label_5 text; v_n_5 integer; v_label_4 text; v_n_4 integer;
BEGIN
  EXECUTE 'SET LOCAL ROLE applicatore';
  INSERT INTO trasi.richiesta (casa_id, ts, categoria, esito)
  SELECT (SELECT id FROM trasi.casa WHERE slug='tuturano'),
         date_trunc('month', current_date) + interval '8 hours' + (g * interval '1 minute'),
         'salute', 'non_trovata'
    FROM generate_series(1,5) g;
  INSERT INTO trasi.richiesta (casa_id, ts, categoria, esito)
  SELECT (SELECT id FROM trasi.casa WHERE slug='tuturano'),
         date_trunc('month', current_date) + interval '15 hours' + (g * interval '1 minute'),
         'salute', 'non_trovata'
    FROM generate_series(1,4) g;
  EXECUTE 'RESET ROLE';

  SELECT n, n_label INTO v_n_5, v_label_5
    FROM trasi.v_report_fasce
   WHERE casa_slug='tuturano' AND mese=date_trunc('month', current_date)::date AND fascia_oraria='mattina';
  SELECT n, n_label INTO v_n_4, v_label_4
    FROM trasi.v_report_fasce
   WHERE casa_slug='tuturano' AND mese=date_trunc('month', current_date)::date AND fascia_oraria='pomeriggio';

  IF v_n_5 IS NULL OR v_label_5 <> '5' THEN
    RAISE EXCEPTION 'FAIL PA09 — fascia mattina: n=% n_label=%, attesi 5 e ''5''',
      coalesce(v_n_5::text,'NULL'), coalesce(v_label_5,'NULL');
  END IF;
  IF v_n_4 IS NOT NULL OR v_label_4 <> '<5' THEN
    RAISE EXCEPTION 'FAIL PA09 — fascia pomeriggio: n=% n_label=%, attesi NULL e ''<5''',
      coalesce(v_n_4::text,'NULL'), coalesce(v_label_4,'NULL');
  END IF;
  RAISE NOTICE 'PASS PA09 — v_report_fasce: 5 in ''mattina'' → n=5; 4 in ''pomeriggio'' → ''<5''';
END $$;

-- PA10 · v_report_confronto compara il mese corrente col precedente ---------------------------
DO $$
DECLARE v_delta numeric; v_n integer; v_n_prec integer;
BEGIN
  -- La fixture di PA09 ha lasciato 5+4 richieste 'salute/non_trovata' su tuturano nel mese
  -- corrente (totale 9, sopra soglia). Qui aggiungo le 8 del mese precedente, così il confronto
  -- a livello rete dà corrente=9, precedente=8, delta_pct = +12.5 (rete = somma delle Case).
  EXECUTE 'SET LOCAL ROLE applicatore';
  INSERT INTO trasi.richiesta (casa_id, ts, categoria, esito)
  SELECT (SELECT id FROM trasi.casa WHERE slug='bozzano'),
         date_trunc('month', current_date) - interval '1 month' + interval '9 hours' + (g * interval '1 minute'),
         'salute', 'non_trovata'
    FROM generate_series(1,8) g;
  EXECUTE 'RESET ROLE';

  SELECT n, n_prec, delta_pct INTO v_n, v_n_prec, v_delta
    FROM trasi.v_report_confronto
   WHERE mese = date_trunc('month', current_date)::date AND categoria='salute' AND esito='non_trovata';

  IF v_n IS NULL OR v_n <> 9 THEN
    RAISE EXCEPTION 'FAIL PA10 — v_report_confronto.n = %, atteso 9 (5 mattina + 4 pomeriggio di tuturano)',
      coalesce(v_n::text, 'NULL');
  END IF;
  IF v_n_prec IS NULL OR v_n_prec <> 8 THEN
    RAISE EXCEPTION 'FAIL PA10 — v_report_confronto.n_prec = %, atteso 8', coalesce(v_n_prec::text, 'NULL');
  END IF;
  IF v_delta IS NULL OR v_delta <> 12.5 THEN
    RAISE EXCEPTION 'FAIL PA10 — v_report_confronto.delta_pct = %, atteso 12.5', coalesce(v_delta::text, 'NULL');
  END IF;
  RAISE NOTICE 'PASS PA10 — v_report_confronto: mese corrente (n=9) vs precedente (n_prec=8), delta_pct = +12.5';
END $$;

-- PA11 · chat_interazione_log: una Casa inserisce solo col proprio casa_id --------------------
DO $$
DECLARE bloccato boolean := false; n integer;
BEGIN
  EXECUTE 'SET LOCAL ROLE casa_sanbao';
  -- Inserimento col proprio casa_id: ammesso
  INSERT INTO trasi.chat_interazione_log (casa_id, canale, esito, fonte)
  VALUES (trasi.casa_corrente(), 'sportello', 'risposta', 'kb');
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n <> 1 THEN RAISE EXCEPTION 'FAIL PA11 — insert proprio: % righe, attese 1', n; END IF;

  -- Inserimento con casa_id altrui: la policy WITH CHECK respinge
  BEGIN
    INSERT INTO trasi.chat_interazione_log (casa_id, canale, esito, fonte)
    VALUES ((SELECT id FROM trasi.casa WHERE slug='bozzano'), 'sportello', 'risposta', 'kb');
  EXCEPTION WHEN insufficient_privilege THEN bloccato := true;
  END;
  EXECUTE 'RESET ROLE';
  IF NOT bloccato THEN RAISE EXCEPTION 'FAIL PA11 — una Casa ha inserito il log a nome di un''altra'; END IF;
  RAISE NOTICE 'PASS PA11 — chat_interazione_log: proprio casa_id ammesso, altrui respinto (WITH CHECK)';
END $$;

-- PA12 · il canale 'pa' è separato: pa inserisce solo con casa_id NULL e canale='pa' ----------
DO $$
DECLARE bloccato boolean := false; n integer;
BEGIN
  EXECUTE 'SET LOCAL ROLE pa';
  -- insert col canale PA: ammesso (casa_id NULL, canale 'pa')
  INSERT INTO trasi.chat_interazione_log (casa_id, canale, esito, fonte)
  VALUES (NULL, 'pa', 'risposta', 'kb');
  GET DIAGNOSTICS n = ROW_COUNT;
  IF n <> 1 THEN RAISE EXCEPTION 'FAIL PA12 — insert pa: % righe, attese 1', n; END IF;

  -- pa NON inserisce nel canale sportello: la policy chatlog_ins_pa ha canale='pa' obbligatorio
  BEGIN
    INSERT INTO trasi.chat_interazione_log (casa_id, canale, esito, fonte)
    VALUES (NULL, 'sportello', 'risposta', 'kb');
  EXCEPTION WHEN insufficient_privilege THEN bloccato := true;
  END;
  EXECUTE 'RESET ROLE';
  IF NOT bloccato THEN RAISE EXCEPTION 'FAIL PA12 — pa ha inserito nel canale sportello'; END IF;
  RAISE NOTICE 'PASS PA12 — canale pa separato: pa scrive solo in canale=''pa'' con casa_id NULL';
END $$;
