-- Trasi — db/tests/t_rls.sql · T01…T16
-- La RLS è l'autorità: questi test girano SEMPRE come ruolo applicativo (SET ROLE), mai come
-- superuser, altrimenti darebbero falsi positivi. Convenzione: PASS = NOTICE, FAIL = EXCEPTION
-- (interrompe il run). Eseguito con `-1`: ogni INSERT di prova è rollbackato a fine file.
--
-- Cosa NON è qui: l'eccezione iCal positiva e le scritture di `applicatore` stanno in
-- db/tests/test_zero_scritture.sql (worker trasi-proposte). Qui c'è il perimetro dei miei file.
\set ON_ERROR_STOP on
\pset pager off

-- T01 · principio 3: una Casa non scrive la Casa di un'altra --------------------------------
DO $$
DECLARE n integer;
BEGIN
  EXECUTE 'SET ROLE casa_sanbao';
  UPDATE trasi.casa SET orari_provvisori = orari_provvisori WHERE slug = 'bozzano';
  GET DIAGNOSTICS n = ROW_COUNT;
  EXECUTE 'RESET ROLE';
  IF n <> 0 THEN RAISE EXCEPTION 'FAIL T01 — San Bao ha aggiornato Bozzano (% righe), atteso 0', n; END IF;
  RAISE NOTICE 'PASS T01 — casa_sanbao UPDATE casa(bozzano) = 0 righe';
END $$;

-- T02 · la propria Casa sì ---------------------------------------------------------------
DO $$
DECLARE n integer;
BEGIN
  EXECUTE 'SET ROLE casa_sanbao';
  UPDATE trasi.casa SET orari_provvisori = orari_provvisori WHERE slug = 'san-bao';
  GET DIAGNOSTICS n = ROW_COUNT;
  EXECUTE 'RESET ROLE';
  IF n <> 1 THEN RAISE EXCEPTION 'FAIL T02 — San Bao ha aggiornato la propria Casa con % righe, atteso 1', n; END IF;
  RAISE NOTICE 'PASS T02 — casa_sanbao UPDATE casa(san-bao) = 1 riga';
END $$;

-- T03 · WITH CHECK: INSERT di una richiesta per un'altra Casa → 42501 --------------------
DO $$
DECLARE fallito boolean := false; altri integer;
BEGIN
  EXECUTE 'SET ROLE casa_sanbao';
  BEGIN
    INSERT INTO trasi.richiesta (casa_id, categoria, esito)
    SELECT id, 'orientamento', 'risolta' FROM trasi.casa WHERE slug = 'bozzano';
    fallito := true;
  EXCEPTION
    WHEN insufficient_privilege THEN NULL;
    WHEN check_violation THEN altri := 1;
  END;
  EXECUTE 'RESET ROLE';
  IF altri = 1 THEN RAISE EXCEPTION 'FAIL T03 — respinta da CHECK (23514) e non dalla RLS (42501): la policy non è l''autorità'; END IF;
  IF fallito THEN RAISE EXCEPTION 'FAIL T03 — San Bao ha inserito una richiesta per Bozzano (atteso 42501)'; END IF;
  RAISE NOTICE 'PASS T03 — casa_sanbao INSERT richiesta(bozzano) = 42501 (WITH CHECK)';
END $$;

-- T04 · INSERT per la propria Casa: consentito -------------------------------------------
DO $$
DECLARE n integer;
BEGIN
  EXECUTE 'SET ROLE casa_sanbao';
  INSERT INTO trasi.richiesta (casa_id, categoria, esito)
  SELECT id, 'orientamento', 'risolta' FROM trasi.casa WHERE slug = 'san-bao';
  GET DIAGNOSTICS n = ROW_COUNT;
  EXECUTE 'RESET ROLE';
  IF n <> 1 THEN RAISE EXCEPTION 'FAIL T04 — INSERT richiesta propria Casa = % righe, atteso 1', n; END IF;
  RAISE NOTICE 'PASS T04 — casa_sanbao INSERT richiesta(san-bao) = 1 riga';
END $$;

-- T05 · V4: il dominio non si scrive dai ruoli applicativi (luogo) ------------------------
DO $$
DECLARE fallito boolean := false; altri integer;
BEGIN
  EXECUTE 'SET ROLE casa_sanbao';
  BEGIN
    INSERT INTO trasi.luogo (nome, tipo, fonte_id, affidabilita)
    SELECT 'Luogo di prova T05', 'bar', id, 2 FROM trasi.fonte WHERE nome = 'Rete-kb-3';
    fallito := true;
  EXCEPTION
    WHEN insufficient_privilege THEN NULL;
    WHEN OTHERS THEN altri := 1;
  END;
  EXECUTE 'RESET ROLE';
  IF altri = 1 THEN RAISE EXCEPTION 'FAIL T05 — errore diverso da 42501'; END IF;
  IF fallito THEN RAISE EXCEPTION 'FAIL T05 — casa_sanbao ha inserito in luogo (V4 violata)'; END IF;
  RAISE NOTICE 'PASS T05 — casa_sanbao INSERT luogo = 42501';
END $$;

-- T06 · V4: nemmeno l'UPDATE di un luogo ------------------------------------------------
DO $$
DECLARE fallito boolean := false; altri integer;
BEGIN
  EXECUTE 'SET ROLE casa_sanbao';
  BEGIN
    UPDATE trasi.luogo SET nome = nome WHERE nome LIKE 'CAF %';
    fallito := true;
  EXCEPTION
    WHEN insufficient_privilege THEN NULL;
    WHEN OTHERS THEN altri := 1;
  END;
  EXECUTE 'RESET ROLE';
  IF altri = 1 THEN RAISE EXCEPTION 'FAIL T06 — errore diverso da 42501'; END IF;
  IF fallito THEN RAISE EXCEPTION 'FAIL T06 — casa_sanbao ha aggiornato luogo (V4 violata)'; END IF;
  RAISE NOTICE 'PASS T06 — casa_sanbao UPDATE luogo = 42501';
END $$;

-- T07 · shim_rw NOINHERIT: i privilegi si prendono solo con SET LOCAL ROLE ----------------
DO $$
DECLARE fallito boolean := false; n integer;
BEGIN
  EXECUTE 'SET ROLE shim_rw';
  BEGIN
    INSERT INTO trasi.richiesta (casa_id, categoria, esito)
    SELECT id, 'orientamento', 'risolta' FROM trasi.casa WHERE slug = 'san-bao';
    fallito := true;
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  EXECUTE 'SET LOCAL ROLE casa_sanbao';
  INSERT INTO trasi.richiesta (casa_id, categoria, esito)
  SELECT id, 'salute', 'risolta' FROM trasi.casa WHERE slug = 'san-bao';
  GET DIAGNOSTICS n = ROW_COUNT;
  EXECUTE 'RESET ROLE';
  IF fallito THEN RAISE EXCEPTION 'FAIL T07 — shim_rw ha scritto senza SET ROLE: NOINHERIT non è rispettato'; END IF;
  IF n <> 1 THEN RAISE EXCEPTION 'FAIL T07 — con SET LOCAL ROLE l''INSERT ha scritto % righe, atteso 1', n; END IF;
  RAISE NOTICE 'PASS T07 — shim_rw senza SET ROLE = 42501 · con SET LOCAL ROLE casa_sanbao = 1 riga';
END $$;

-- T08 · metabase_ro: legge solo le viste, non i dati grezzi (§12) ------------------------
DO $$
DECLARE fallito_sel boolean := false; fallito_ins boolean := false; n integer;
BEGIN
  EXECUTE 'SET ROLE metabase_ro';
  BEGIN
    PERFORM count(*) FROM trasi.richiesta;
    fallito_sel := true;
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  BEGIN
    INSERT INTO trasi.luogo (nome, tipo, fonte_id, affidabilita)
    SELECT 'Luogo di prova T08', 'bar', id, 2 FROM trasi.fonte WHERE nome = 'Rete-kb-3';
    fallito_ins := true;
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  SELECT count(*) INTO n FROM trasi.v_confronto_case;
  EXECUTE 'RESET ROLE';
  IF fallito_sel THEN RAISE EXCEPTION 'FAIL T08 — metabase_ro legge richiesta in chiaro (matrice: NON deve)'; END IF;
  IF fallito_ins THEN RAISE EXCEPTION 'FAIL T08 — metabase_ro ha scritto in luogo'; END IF;
  IF n <> 10 THEN RAISE EXCEPTION 'FAIL T08 — metabase_ro legge v_confronto_case con % righe, attese 10', n; END IF;
  RAISE NOTICE 'PASS T08 — metabase_ro: SELECT richiesta = 42501 · INSERT luogo = 42501 · v_confronto_case = 10 righe';
END $$;

-- T09 · tutti leggono tutto, ognuno scrive il proprio (scheda_servizio) ------------------
DO $$
DECLARE n integer; visibili integer;
BEGIN
  INSERT INTO trasi.scheda_servizio (casa_id, titolo)
  SELECT id, 'Scheda di prova T09 (bozzano)' FROM trasi.casa WHERE slug = 'bozzano';
  INSERT INTO trasi.scheda_servizio (casa_id, titolo)
  SELECT id, 'Scheda di prova T09 (san-bao)' FROM trasi.casa WHERE slug = 'san-bao';
  EXECUTE 'SET ROLE casa_sanbao';
  SELECT count(*) INTO visibili FROM trasi.scheda_servizio WHERE titolo LIKE 'Scheda di prova T09%';
  UPDATE trasi.scheda_servizio SET titolo = titolo WHERE titolo LIKE '%(bozzano)';
  GET DIAGNOSTICS n = ROW_COUNT;
  EXECUTE 'RESET ROLE';
  IF visibili <> 2 THEN RAISE EXCEPTION 'FAIL T09 — San Bao vede % schede di prova, attese 2 (tutti leggono tutto)', visibili; END IF;
  IF n <> 0 THEN RAISE EXCEPTION 'FAIL T09 — San Bao ha aggiornato % schede di Bozzano, atteso 0', n; END IF;
  RAISE NOTICE 'PASS T09 — San Bao legge 2 schede (anche di Bozzano) e ne aggiorna 0';
END $$;

-- T10 · automazioni: nessuna scrittura di dominio; INSERT evento senza fonte iCal → 42501 -
DO $$
DECLARE f_upd boolean := false; f_ins boolean := false; n integer;
BEGIN
  EXECUTE 'SET ROLE automazioni';
  BEGIN
    UPDATE trasi.luogo SET nome = nome WHERE nome LIKE 'CAF %';
    f_upd := true;
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  BEGIN
    INSERT INTO trasi.evento (casa_id, titolo, inizio)
    SELECT id, 'Evento di prova T10', now() FROM trasi.casa WHERE slug = 'san-bao';
    f_ins := true;
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  SELECT count(*) INTO n FROM trasi.evento;
  EXECUTE 'RESET ROLE';
  IF f_upd THEN RAISE EXCEPTION 'FAIL T10 — automazioni ha aggiornato luogo'; END IF;
  IF f_ins THEN RAISE EXCEPTION 'FAIL T10 — automazioni ha inserito un evento senza fonte iCal (V4)'; END IF;
  IF n < 0 THEN RAISE EXCEPTION 'FAIL T10 — irraggiungibile'; END IF;
  RAISE NOTICE 'PASS T10 — automazioni: UPDATE luogo = 42501 · INSERT evento senza fonte iCal = 42501';
END $$;

-- T11 · parametro [P]: leggono tutti, scrive solo `ti` ----------------------------------
DO $$
DECLARE n integer; fallito boolean := false;
BEGIN
  EXECUTE 'SET ROLE casa_sanbao';
  BEGIN
    UPDATE trasi.parametro SET valore = valore WHERE chiave = 'k_anonimato';
    fallito := true;
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  EXECUTE 'SET ROLE ti';
  UPDATE trasi.parametro SET valore = valore, modificato_da = current_user, modificato_ts = now()
   WHERE chiave = 'k_anonimato';
  GET DIAGNOSTICS n = ROW_COUNT;
  EXECUTE 'RESET ROLE';
  IF fallito THEN RAISE EXCEPTION 'FAIL T11 — una Casa ha modificato un parametro [P]'; END IF;
  IF n <> 1 THEN RAISE EXCEPTION 'FAIL T11 — ti ha modificato % righe di parametro, atteso 1', n; END IF;
  RAISE NOTICE 'PASS T11 — casa_sanbao UPDATE parametro = 42501 · ti UPDATE parametro = 1 riga';
END $$;

-- T12 · l'invariante strutturale: FORCE RLS ovunque, nessun bypass ----------------------
-- I ruoli ispezionati sono i 17 di 000_roles.sql, non l'intero cluster: `postgres` è l'amministratore
-- del container (serve a CREATE ROLE e ai GRANT ruolo→ruolo) e non è un'identità applicativa.
DO $$
DECLARE
  ruoli text[] := ARRAY['casa_santaspazio','casa_molo12','casa_erranti','casa_buscicchio','casa_sanbao',
                        'casa_minimus','casa_pop','casa_bozzano','casa_dream','casa_tuturano',
                        'rete','ti','metabase_ro','automazioni','shim_rw','applicatore','trasi_owner'];
  senza_force text; bypass text; n integer; creati integer;
BEGIN
  SELECT string_agg(c.relname, ', ' ORDER BY c.relname) INTO senza_force
  FROM pg_class c JOIN pg_namespace nsp ON nsp.oid = c.relnamespace
  WHERE nsp.nspname = 'trasi' AND c.relkind = 'r' AND c.relname <> 'audit'
    AND NOT (c.relrowsecurity AND c.relforcerowsecurity);
  IF senza_force IS NOT NULL THEN
    RAISE EXCEPTION 'FAIL T12 — tabelle senza ENABLE+FORCE RLS: %', senza_force;
  END IF;
  SELECT string_agg(rolname, ', ') INTO bypass FROM pg_roles
   WHERE rolname = ANY (ruoli) AND (rolsuper OR rolbypassrls);
  IF bypass IS NOT NULL THEN RAISE EXCEPTION 'FAIL T12 — ruoli di progetto con SUPERUSER/BYPASSRLS: %', bypass; END IF;
  SELECT count(*) INTO creati FROM pg_roles WHERE rolname = ANY (ruoli);
  IF creati <> 17 THEN RAISE EXCEPTION 'FAIL T12 — ruoli di progetto presenti: %, attesi 17', creati; END IF;
  SELECT count(*) INTO n FROM pg_class c JOIN pg_namespace nsp ON nsp.oid = c.relnamespace
   WHERE nsp.nspname = 'trasi' AND c.relkind = 'r' AND c.relrowsecurity AND c.relforcerowsecurity;
  RAISE NOTICE 'PASS T12 — % tabelle con ENABLE+FORCE RLS, 17 ruoli di progetto, 0 con SUPERUSER/BYPASSRLS (audit fuori: controllo per GRANT, §7.1)', n;
END $$;

-- T13 · casa_corrente() deriva da current_user via ruolo_casa, non da una GUC -------------
-- La prova negativa che conta: una GUC di comodo non sposta la Casa corrente.
DO $$
DECLARE senza_guc int; con_guc int; senza_ruolo int;
BEGIN
  EXECUTE 'SET ROLE casa_sanbao';
  senza_guc := trasi.casa_corrente();
  EXECUTE 'SET LOCAL trasi.casa_id = ''8''';      -- tentativo di spoof
  con_guc := trasi.casa_corrente();
  EXECUTE 'RESET ROLE';
  EXECUTE 'SET ROLE shim_rw';                      -- nessuna riga in ruolo_casa per shim_rw
  senza_ruolo := trasi.casa_corrente();
  EXECUTE 'RESET ROLE';
  IF senza_guc <> 5 THEN RAISE EXCEPTION 'FAIL T13 — casa_corrente() come casa_sanbao = %, atteso 5', senza_guc; END IF;
  IF con_guc <> senza_guc THEN RAISE EXCEPTION 'FAIL T13 — una GUC ha spostato la Casa corrente (% → %)', senza_guc, con_guc; END IF;
  IF senza_ruolo IS NOT NULL THEN RAISE EXCEPTION 'FAIL T13 — shim_rw ha una Casa corrente (%) pur senza riga in ruolo_casa', senza_ruolo; END IF;
  RAISE NOTICE 'PASS T13 — casa_corrente() = 5 da ruolo_casa, invariata con GUC spoofata, NULL per shim_rw';
END $$;

-- T14 · persona_casa (db/029): una Casa non scrive le persone di un'altra ----------------------------
-- I nomi sono l'unico dato personale che lo shim scrive del dominio (decisione del gruppo Processi,
-- forma C): l'isolamento cross-Casa non è un dettaglio, è ciò che impedisce a una Casa di pubblicare
-- in KB il nome di chi lavora altrove. Policy `pers_ins_casa`/`pers_upd_casa`, qui verificate.
DO $$
DECLARE bozzano int; n int;
BEGIN
  SELECT id INTO bozzano FROM trasi.casa WHERE slug = 'bozzano';

  EXECUTE 'SET ROLE casa_sanbao';
  BEGIN
    INSERT INTO trasi.persona_casa (casa_id, nome, ruolo, consenso_il)
    VALUES (bozzano, 'Persona di Bozzano via San Bao', 'volontario', current_date);
    n := 1;
  EXCEPTION WHEN insufficient_privilege THEN n := 0;   -- atteso: la policy `pers_ins_casa` rifiuta
  END;
  EXECUTE 'RESET ROLE';
  IF n <> 0 THEN RAISE EXCEPTION 'FAIL T14 — san-bao ha inserito una persona di bozzano: la RLS non isola persona_casa'; END IF;

  -- Una persona di Bozzano c'è davvero (scritta da Bozzano): senza fixture UPDATE e DELETE cross-Casa
  -- toccherebbero 0 righe per assenza di righe, non per la RLS, e il test passerebbe a vuoto.
  EXECUTE 'SET ROLE casa_bozzano';
  INSERT INTO trasi.persona_casa (casa_id, nome, ruolo, consenso_il)
  VALUES (bozzano, 'Persona di Bozzano (fixture T14)', 'volontario', current_date);
  EXECUTE 'RESET ROLE';

  -- E nemmeno si aggira con un UPDATE delle righe di un'altra Casa.
  EXECUTE 'SET ROLE casa_sanbao';
  BEGIN
    UPDATE trasi.persona_casa SET ruolo = 'riscritto da san-bao' WHERE casa_id = bozzano;
    GET DIAGNOSTICS n = ROW_COUNT;
  EXCEPTION WHEN insufficient_privilege THEN n := 0;
  END;
  EXECUTE 'RESET ROLE';
  IF n <> 0 THEN RAISE EXCEPTION 'FAIL T14 — san-bao ha aggiornato % persone di Bozzano', n; END IF;

  -- Né con un DELETE (`pers_del_casa`): cancellare il nome di chi lavora altrove è una scrittura come
  -- le altre — la revoca la fa la Casa che ha raccolto il consenso.
  EXECUTE 'SET ROLE casa_sanbao';
  BEGIN
    DELETE FROM trasi.persona_casa WHERE casa_id = bozzano;
    GET DIAGNOSTICS n = ROW_COUNT;
  EXCEPTION WHEN insufficient_privilege THEN n := 0;
  END;
  EXECUTE 'RESET ROLE';
  IF n <> 0 THEN RAISE EXCEPTION 'FAIL T14 — san-bao ha cancellato % persone di Bozzano', n; END IF;

  -- La fixture la toglie chi la può toccare: la sua Casa.
  EXECUTE 'SET ROLE casa_bozzano';
  DELETE FROM trasi.persona_casa WHERE nome = 'Persona di Bozzano (fixture T14)';
  GET DIAGNOSTICS n = ROW_COUNT;
  EXECUTE 'RESET ROLE';
  IF n <> 1 THEN RAISE EXCEPTION 'FAIL T14 — Bozzano non ha potuto cancellare la propria persona (% righe)', n; END IF;

  RAISE NOTICE 'PASS T14 — persona_casa: INSERT, UPDATE e DELETE cross-Casa → 0 righe/42501; la propria Casa cancella (la RLS isola anche i nomi)';
END $$;

-- T15 · oggetto (db/014 + db/032): la propria Casa scrive l'attrezzoteca, le altre no, nessuno cancella ----
-- La decisione D1 estesa all'inventario: `casa_sanbao` INSERT/UPDATE su `casa_id` proprio; su Bozzano la
-- policy (`ogg_ins_casa` WITH CHECK, `ogg_upd_casa` USING) decide — non lo shim. DELETE negato a tutti i
-- ruoli Casa (V4 regola 7: il ritiro è attivo=false). `rete` e `shim_rw` non hanno il privilegio di
-- scrittura. E la scrittura diretta della propria Casa **non** è una violazione di V4: non compare in
-- `v_scritture_senza_audit`.
DO $$
DECLARE sanbao int; bozzano int; n int; nuovo int; fallito boolean; violazioni int;
BEGIN
  SELECT id INTO sanbao  FROM trasi.casa WHERE slug = 'san-bao';
  SELECT id INTO bozzano FROM trasi.casa WHERE slug = 'bozzano';

  -- INSERT per la propria Casa: consentito, e l'impronta di scrittura è del ruolo.
  EXECUTE 'SET ROLE casa_sanbao';
  INSERT INTO trasi.oggetto (casa_id, nome, quantita, condizione)
  VALUES (sanbao, 'Oggetto di prova T15 (san-bao)', 3, 'integro') RETURNING id INTO nuovo;
  EXECUTE 'RESET ROLE';
  IF nuovo IS NULL THEN RAISE EXCEPTION 'FAIL T15 — san-bao non ha potuto inserire un oggetto proprio'; END IF;
  IF (SELECT aggiornato_da FROM trasi.oggetto WHERE id = nuovo) IS DISTINCT FROM 'casa_sanbao' THEN
    RAISE EXCEPTION 'FAIL T15 — l''impronta di scrittura non è casa_sanbao (scrittura_00_ts assente?)';
  END IF;

  -- INSERT con casa_id di Bozzano: WITH CHECK → 42501, non 23514.
  EXECUTE 'SET ROLE casa_sanbao';
  fallito := false;
  BEGIN
    INSERT INTO trasi.oggetto (casa_id, nome, quantita) VALUES (bozzano, 'Oggetto di Bozzano via San Bao (T15)', 1);
    fallito := true;
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  EXECUTE 'RESET ROLE';
  IF fallito THEN RAISE EXCEPTION 'FAIL T15 — san-bao ha inserito un oggetto di Bozzano (atteso 42501)'; END IF;

  -- Un oggetto di Bozzano c'è davvero (scritto da Bozzano): senza fixture l'UPDATE cross-Casa toccherebbe
  -- 0 righe per assenza di righe, non per la RLS.
  EXECUTE 'SET ROLE casa_bozzano';
  INSERT INTO trasi.oggetto (casa_id, nome, quantita) VALUES (bozzano, 'Oggetto di prova T15 (bozzano)', 2);
  EXECUTE 'RESET ROLE';

  -- UPDATE su un oggetto di Bozzano: la policy USING lo nasconde → 0 righe.
  EXECUTE 'SET ROLE casa_sanbao';
  UPDATE trasi.oggetto SET quantita = 99 WHERE nome = 'Oggetto di prova T15 (bozzano)';
  GET DIAGNOSTICS n = ROW_COUNT;
  EXECUTE 'RESET ROLE';
  IF n <> 0 THEN RAISE EXCEPTION 'FAIL T15 — san-bao ha aggiornato % oggetti di Bozzano', n; END IF;

  -- UPDATE del proprio: 1 riga (il ritiro è così, attivo=false).
  EXECUTE 'SET ROLE casa_sanbao';
  UPDATE trasi.oggetto SET attivo = false WHERE id = nuovo;
  GET DIAGNOSTICS n = ROW_COUNT;
  EXECUTE 'RESET ROLE';
  IF n <> 1 THEN RAISE EXCEPTION 'FAIL T15 — san-bao non ha potuto ritirare il proprio oggetto (% righe)', n; END IF;

  -- DELETE: nessun privilegio, nemmeno sul proprio (V4 regola 7).
  EXECUTE 'SET ROLE casa_sanbao';
  fallito := false;
  BEGIN
    DELETE FROM trasi.oggetto WHERE id = nuovo;
    fallito := true;
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  EXECUTE 'RESET ROLE';
  IF fallito THEN RAISE EXCEPTION 'FAIL T15 — san-bao ha cancellato un oggetto: il ritiro è attivo=false, mai DELETE'; END IF;

  -- rete e shim_rw: nessuna scrittura (la scrittura è della Casa, per la propria).
  EXECUTE 'SET ROLE rete';
  fallito := false;
  BEGIN
    INSERT INTO trasi.oggetto (casa_id, nome, quantita) VALUES (sanbao, 'Oggetto via rete (T15)', 1);
    fallito := true;
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  EXECUTE 'RESET ROLE';
  IF fallito THEN RAISE EXCEPTION 'FAIL T15 — rete ha inserito un oggetto (atteso 42501)'; END IF;
  EXECUTE 'SET ROLE shim_rw';
  fallito := false;
  BEGIN
    INSERT INTO trasi.oggetto (casa_id, nome, quantita) VALUES (sanbao, 'Oggetto via shim_rw (T15)', 1);
    fallito := true;
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  EXECUTE 'RESET ROLE';
  IF fallito THEN RAISE EXCEPTION 'FAIL T15 — shim_rw ha inserito un oggetto (atteso 42501)'; END IF;

  -- La contabilità V4: le due scritture dirette (san-bao e bozzano, ciascuna sulla propria) non sono violazioni.
  SELECT count(*) INTO violazioni FROM trasi.v_scritture_senza_audit
   WHERE entita = 'oggetto' AND entita_id IN (SELECT id FROM trasi.oggetto WHERE nome LIKE 'Oggetto di prova T15%');
  IF violazioni <> 0 THEN
    RAISE EXCEPTION 'FAIL T15 — % scritture dirette della propria Casa contabilizzate come violazioni di V4', violazioni;
  END IF;

  RAISE NOTICE 'PASS T15 — oggetto: INSERT/UPDATE della propria Casa OK e fuori da v_scritture_senza_audit; cross-Casa 42501/0 righe; DELETE 42501; rete e shim_rw 42501';
END $$;

-- T16 · movimento bidirezionale (db/033): propone cedente o ricevente, decide la controparte -------------
-- (a) la ricevente chiede un oggetto altrui (proposto_da = sé) → ok; con proposto_da = cedente → RLS;
-- (b) su quella richiesta la proponente non decide (P0001 «spetta a buscicchio»), la cedente conferma →
--     confermato, oggetto a Molo 12; (c) prestito proposto dalla cedente → decide la ricevente, la cedente
--     riceve P0001; (d) 'rifiuta' → rifiutato, oggetto fermo; (e) 'rientro' dalla ricevente → P0001, dalla
--     cedente → rientrato con condizione; (f) v_movimenti_da_confermare.decide_casa_slug coincide con chi
--     è riuscito a confermare in (b)/(c). Fixture come trasi_owner, rollback a fine file.
DO $$
DECLARE busc int; molo int; ogg1 int; ogg2 int; ogg3 int; m1 int; m2 int; m3 int; n int; fallito boolean;
        decide text; st text; casa_ogg int; cond text; msg text;
BEGIN
  SELECT id INTO busc FROM trasi.casa WHERE slug = 'buscicchio';
  SELECT id INTO molo FROM trasi.casa WHERE slug = 'molo12';

  EXECUTE 'SET ROLE casa_buscicchio';
  INSERT INTO trasi.oggetto (casa_id, nome, quantita) VALUES (busc, 'Oggetto T16 richiesta', 2) RETURNING id INTO ogg1;
  INSERT INTO trasi.oggetto (casa_id, nome, quantita) VALUES (busc, 'Oggetto T16 prestito', 1) RETURNING id INTO ogg2;
  INSERT INTO trasi.oggetto (casa_id, nome, quantita) VALUES (busc, 'Oggetto T16 rifiuto', 1) RETURNING id INTO ogg3;
  EXECUTE 'RESET ROLE';

  -- (a) Molo 12 chiede in prestito l'oggetto di Buscicchio: propone sé stessa come ricevente.
  EXECUTE 'SET ROLE casa_molo12';
  INSERT INTO trasi.movimento (oggetto_id, da_casa_id, a_casa_id, proposto_da_casa_id)
  VALUES (ogg1, busc, molo, molo) RETURNING id INTO m1;
  -- …ma non può dichiarare che a proporre sia stata Buscicchio.
  fallito := false;
  BEGIN
    INSERT INTO trasi.movimento (oggetto_id, da_casa_id, a_casa_id, proposto_da_casa_id) VALUES (ogg1, busc, molo, busc);
    fallito := true;
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  EXECUTE 'RESET ROLE';
  IF fallito THEN RAISE EXCEPTION 'FAIL T16a — molo12 ha inserito un movimento «proposto da buscicchio» (atteso 42501)'; END IF;

  -- (f) la vista dice chi decide: la controparte di chi ha proposto → buscicchio.
  SELECT decide_casa_slug INTO decide FROM trasi.v_movimenti_da_confermare WHERE id = m1;
  IF decide IS DISTINCT FROM 'buscicchio' THEN RAISE EXCEPTION 'FAIL T16f — decide_casa_slug = % (atteso buscicchio)', decide; END IF;

  -- (b) la proponente non decide; la cedente conferma e l'oggetto passa a Molo 12.
  EXECUTE 'SET ROLE casa_molo12';
  fallito := false;
  BEGIN
    PERFORM trasi.conferma_movimento(m1, 'casa_molo12');
    fallito := true;
  EXCEPTION WHEN raise_exception THEN msg := SQLERRM;
  END;
  EXECUTE 'RESET ROLE';
  IF fallito THEN RAISE EXCEPTION 'FAIL T16b — molo12 ha confermato la richiesta che ha proposto'; END IF;
  IF position('buscicchio' in msg) = 0 THEN RAISE EXCEPTION 'FAIL T16b — il P0001 non dice a chi spetta: %', msg; END IF;
  EXECUTE 'SET ROLE casa_buscicchio';
  PERFORM trasi.conferma_movimento(m1, 'casa_buscicchio', 'conferma');
  EXECUTE 'RESET ROLE';
  SELECT stato INTO st FROM trasi.movimento WHERE id = m1;
  SELECT casa_id INTO casa_ogg FROM trasi.oggetto WHERE id = ogg1;
  IF st <> 'confermato' OR casa_ogg <> molo THEN RAISE EXCEPTION 'FAIL T16b — stato % / oggetto presso % (attesi confermato / molo12)', st, casa_ogg; END IF;

  -- (c) prestito proposto dalla cedente (il caso di prima): decide la ricevente, la cedente riceve P0001.
  EXECUTE 'SET ROLE casa_buscicchio';
  INSERT INTO trasi.movimento (oggetto_id, da_casa_id, a_casa_id, proposto_da_casa_id)
  VALUES (ogg2, busc, molo, busc) RETURNING id INTO m2;
  fallito := false;
  BEGIN
    PERFORM trasi.conferma_movimento(m2, 'casa_buscicchio');
    fallito := true;
  EXCEPTION WHEN raise_exception THEN NULL;
  END;
  EXECUTE 'RESET ROLE';
  IF fallito THEN RAISE EXCEPTION 'FAIL T16c — la cedente ha confermato il proprio prestito'; END IF;
  SELECT decide_casa_slug INTO decide FROM trasi.v_movimenti_da_confermare WHERE id = m2;
  IF decide IS DISTINCT FROM 'molo12' THEN RAISE EXCEPTION 'FAIL T16f — decide_casa_slug = % (atteso molo12)', decide; END IF;

  -- (e) 'rientro' su un proposto → P0001; poi conferma dalla ricevente, rientro dalla ricevente → P0001,
  --     rientro dalla cedente → rientrato con condizione dichiarata e oggetto tornato.
  EXECUTE 'SET ROLE casa_molo12';
  fallito := false;
  BEGIN
    PERFORM trasi.conferma_movimento(m2, 'casa_molo12', 'rientro');
    fallito := true;
  EXCEPTION WHEN raise_exception THEN NULL;
  END;
  IF fallito THEN EXECUTE 'RESET ROLE'; RAISE EXCEPTION 'FAIL T16e — rientro accettato su un movimento proposto'; END IF;
  PERFORM trasi.conferma_movimento(m2, 'casa_molo12', 'conferma');
  fallito := false;
  BEGIN
    PERFORM trasi.conferma_movimento(m2, 'casa_molo12', 'rientro');
    fallito := true;
  EXCEPTION WHEN raise_exception THEN NULL;
  END;
  EXECUTE 'RESET ROLE';
  IF fallito THEN RAISE EXCEPTION 'FAIL T16e — la ricevente ha registrato il rientro'; END IF;
  EXECUTE 'SET ROLE casa_buscicchio';
  PERFORM trasi.conferma_movimento(m2, 'casa_buscicchio', 'rientro', 'danneggiato');
  EXECUTE 'RESET ROLE';
  SELECT stato, condizione_rientro INTO st, cond FROM trasi.movimento WHERE id = m2;
  SELECT casa_id INTO casa_ogg FROM trasi.oggetto WHERE id = ogg2;
  IF st <> 'rientrato' OR cond <> 'danneggiato' OR casa_ogg <> busc THEN
    RAISE EXCEPTION 'FAIL T16e — stato % / condizione % / oggetto presso % (attesi rientrato / danneggiato / buscicchio)', st, cond, casa_ogg;
  END IF;

  -- (d) rifiuto dalla controparte: rifiutato, oggetto fermo, voce fuori dalla vista.
  EXECUTE 'SET ROLE casa_molo12';
  INSERT INTO trasi.movimento (oggetto_id, da_casa_id, a_casa_id, proposto_da_casa_id)
  VALUES (ogg3, busc, molo, molo) RETURNING id INTO m3;
  EXECUTE 'RESET ROLE';
  EXECUTE 'SET ROLE casa_buscicchio';
  PERFORM trasi.conferma_movimento(m3, 'casa_buscicchio', 'rifiuta');
  EXECUTE 'RESET ROLE';
  SELECT stato INTO st FROM trasi.movimento WHERE id = m3;
  SELECT casa_id INTO casa_ogg FROM trasi.oggetto WHERE id = ogg3;
  SELECT count(*) INTO n FROM trasi.v_movimenti_da_confermare WHERE id = m3;
  IF st <> 'rifiutato' OR casa_ogg <> busc OR n <> 0 THEN
    RAISE EXCEPTION 'FAIL T16d — stato % / oggetto presso % / in vista % (attesi rifiutato / buscicchio / 0)', st, casa_ogg, n;
  END IF;
  -- Il rifiuto non sposta l'oggetto: nessuna riga audit «oggetto» per m3, ma una per il movimento.
  SELECT count(*) INTO n FROM trasi.audit WHERE azione = 'conferma_movimento' AND entita = 'movimento' AND entita_id = m3;
  IF n <> 1 THEN RAISE EXCEPTION 'FAIL T16d — audit del rifiuto: % righe (attesa 1)', n; END IF;

  -- La contabilità V4 resta pulita: gli oggetti spostati hanno la loro riga audit.
  SELECT count(*) INTO n FROM trasi.v_scritture_senza_audit WHERE entita = 'oggetto' AND entita_id IN (ogg1, ogg2, ogg3);
  IF n <> 0 THEN RAISE EXCEPTION 'FAIL T16 — % oggetti in v_scritture_senza_audit dopo i movimenti', n; END IF;

  RAISE NOTICE 'PASS T16 — movimento bidirezionale: richiesta della ricevente OK (proposto_da ≠ sé → 42501); decide la controparte (P0001 alla proponente); conferma sposta, rifiuta no, rientro solo dalla cedente con condizione; decide_casa_slug coerente; 0 violazioni V4';
END $$;
