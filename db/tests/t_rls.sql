-- Trasi — db/tests/t_rls.sql · T01…T12
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
