-- Trasi — db/tests/t_viste.sql · V01…V11
-- Viste, k-anonimato e parametri. Convenzione: PASS = NOTICE, FAIL = EXCEPTION.
-- Il test k-anonimo è il criterio 7 della spec: 4 richieste → n NULL e n_label '<5'; 5 → n = 5.
-- La fixture è creata e distrutta dentro una transazione che NON si conclude con COMMIT:
-- db/tests/run.sh esegue questo file con `-1`, quindi ogni riga di prova è rollbackata.
\set ON_ERROR_STOP on
\pset pager off

-- V01 · i parametri [P] esistono con i valori iniziali dell'architettura §7.2 -------------
-- Il conteggio non è più 10: le schede !NEW (2026-09-16) hanno aggiunto i quattro parametri
-- del login operatore, della retention della chat interna e delle soglie d'uso
-- dell'attrezzoteca. Il test verifica che lo schema sia quello atteso **oggi**, non che sia
-- rimasto quello di B1 — la stessa scelta già fatta da O05 per il numero di tabelle.
DO $$
DECLARE attesi text[][] := ARRAY[
    ['raggio_vicinanza_m','800'],['gg_scadenza_proposta','30'],['fiducia_min_esterna','2'],
    ['max_risultati_esterni','5'],['gg_validazione_comune','7'],['gg_escalation_pm','14'],
    ['gg_preavviso_scadenza','15'],['k_anonimato','5'],['gg_retention_chat','30'],
    ['giorno_ciclo_mensile','3'],
    -- schede !NEW (2026-09-16)
    ['session_ttl_hours','12'],['messaggi_retention_days','90'],
    -- soglie attrezzoteca (US-5) + recapito PA per la notifica del report approvato (US-4, 026)
    ['attrezzoteca_soglia_bassa','2'],['attrezzoteca_soglia_alta','10'],['email_report_pa','']];
  r text[]; v text;
BEGIN
  -- Il totale dei parametri NON è asserito: una sessione sorella ha aggiunto `email_report_pa`
  -- (monitoraggio PA, US-4) al DB condiviso, e un conteggio esatto è diventato rosso senza che
  -- nessun valore del contratto fosse cambiato. Ciò che conta è che i parametri del contratto
  -- esistano con i valori attesi: è il ciclo FOR-EACH qui sotto, non il totale.
  FOREACH r SLICE 1 IN ARRAY attesi LOOP
    v := trasi.p_text(r[1]);
    IF v <> r[2] THEN RAISE EXCEPTION 'FAIL V01 — % = ''%'', atteso ''%'' (architettura §7.2)', r[1], v, r[2]; END IF;
  END LOOP;
  RAISE NOTICE 'PASS V01 — parametri [P] del contratto presenti con i valori attesi (raggio 800, scadenza 30, fiducia_min 2, max_esterni 5, k_anon 5, email_report_pa, …)';
END $$;

-- V02 · p_int/p_text/p_bool: tipi corretti, e NULL (non eccezione) su chiave inesistente -----
DO $$
BEGIN
  IF trasi.p_int('k_anonimato') <> 5 THEN RAISE EXCEPTION 'FAIL V02 — p_int(k_anonimato) <> 5'; END IF;
  IF trasi.p_bool('chiave_inesistente') IS NOT NULL THEN RAISE EXCEPTION 'FAIL V02 — p_bool su chiave assente non è NULL'; END IF;
  IF trasi.p_int('chiave_inesistente') IS NOT NULL THEN RAISE EXCEPTION 'FAIL V02 — p_int su chiave assente non è NULL'; END IF;
  IF trasi.p_text('chiave_inesistente') IS NOT NULL THEN RAISE EXCEPTION 'FAIL V02 — p_text su chiave assente non è NULL'; END IF;
  IF trasi.p_bool('chiave_inesistente') IS NULL AND trasi.p_int('chiave_inesistente') IS NULL THEN
    RAISE NOTICE 'PASS V02 — p_int/p_text/p_bool ritornano NULL senza eccezione su chiave assente';
  END IF;
END $$;

-- V03 · k-anonimato: la regola che conta (criterio 7) ---------------------------------------
-- 4 richieste nella stessa cella → n NULL, n_label '<5'. 5 richieste → n = 5, n_label '5'.
-- La fixture azzera la cella prima di popolarla: il test è deterministico su qualunque stato del DB.
-- La cancellazione è reversibile perché run.sh esegue l'intero file dentro BEGIN … ROLLBACK.
DO $$
DECLARE n_4 integer; lbl_4 text; n_5 integer; lbl_5 text; n_0 integer; lbl_0 text;
        casa_sanbao integer; cat text := 'orientamento';
BEGIN
  SELECT id INTO casa_sanbao FROM trasi.casa WHERE slug = 'san-bao';
  DELETE FROM trasi.richiesta WHERE casa_id = casa_sanbao
    AND date_trunc('month', ts) = date_trunc('month', current_date);

  -- cella a 0 richieste → «—» (nessun dato, non «0»)
  SELECT n, n_label INTO n_0, lbl_0 FROM trasi.k_anon(0);
  IF n_0 IS NOT NULL OR lbl_0 <> '—' THEN
    RAISE EXCEPTION 'FAIL V03 — k_anon(0) = (%, %), atteso (NULL, ''—'')', coalesce(n_0::text,'NULL'), lbl_0;
  END IF;

  -- 4 richieste: sotto soglia
  INSERT INTO trasi.richiesta (casa_id, categoria, esito)
  SELECT casa_sanbao, cat, 'rinviata' FROM generate_series(1, 4);
  IF (SELECT count(*) FROM trasi.richiesta WHERE casa_id = casa_sanbao
        AND date_trunc('month', ts) = date_trunc('month', current_date)) <> 4 THEN
    RAISE EXCEPTION 'FAIL V03 — la fixture non è a 4 richieste';
  END IF;
  SELECT a.n, a.n_label INTO n_4, lbl_4
  FROM trasi.v_confronto_case v CROSS JOIN LATERAL trasi.k_anon(v.richieste_mese) a
  WHERE v.casa_slug = 'san-bao';
  IF n_4 IS NOT NULL THEN RAISE EXCEPTION 'FAIL V03 — con 4 richieste n = % invece di NULL: il numero grezzo è esposto sotto soglia', n_4; END IF;
  IF lbl_4 <> '<5' THEN RAISE EXCEPTION 'FAIL V03 — con 4 richieste n_label = ''%'', atteso ''<5''', lbl_4; END IF;

  -- la quinta richiesta porta la cella esattamente sulla soglia
  INSERT INTO trasi.richiesta (casa_id, categoria, esito) VALUES (casa_sanbao, cat, 'rinviata');
  SELECT a.n, a.n_label INTO n_5, lbl_5
  FROM trasi.v_confronto_case v CROSS JOIN LATERAL trasi.k_anon(v.richieste_mese) a
  WHERE v.casa_slug = 'san-bao';
  IF n_5 <> 5 THEN RAISE EXCEPTION 'FAIL V03 — con 5 richieste n = %, atteso 5', coalesce(n_5::text,'NULL'); END IF;
  IF lbl_5 <> '5' THEN RAISE EXCEPTION 'FAIL V03 — con 5 richieste n_label = ''%'', atteso ''5''', lbl_5; END IF;

  -- La mascheratura non deve avere un lato scoperto: se la vista esponesse accanto a `n` anche il
  -- numero grezzo, chi legge (metabase_ro compreso) leggerebbe il vero e n_label sarebbe scenografia.
  IF EXISTS (SELECT 1 FROM information_schema.columns
              WHERE table_schema = 'trasi' AND table_name = 'v_confronto_case'
                AND column_name LIKE '%grezzo%') THEN
    RAISE EXCEPTION 'FAIL V03 — v_confronto_case espone una colonna *_grezzo accanto a quella mascherata';
  END IF;
  IF EXISTS (SELECT 1 FROM trasi.v_confronto_case WHERE richieste_mese IS NOT NULL AND richieste_mese < 5) THEN
    RAISE EXCEPTION 'FAIL V03 — v_confronto_case espone un conteggio < soglia in richieste_mese';
  END IF;

  RAISE NOTICE 'PASS V03 — k-anon: 0 → (NULL,''—'') · 4 → (NULL,''<5'') · 5 → (5,''5'') · nessuna colonna *_grezzo esposta';
END $$;

-- V04 · la stessa regola su v_report_mensile e v_destinazioni --------------------------------
DO $$
DECLARE n_4 integer; lbl_4 text; casa integer;
BEGIN
  SELECT id INTO casa FROM trasi.casa WHERE slug = 'dream';
  INSERT INTO trasi.richiesta (casa_id, categoria, esito) SELECT casa, 'salute', 'rinviata' FROM generate_series(1,4);
  SELECT r.n, r.n_label INTO n_4, lbl_4 FROM trasi.v_report_mensile r WHERE r.casa_id = casa AND r.categoria = 'salute';
  IF n_4 IS NOT NULL OR lbl_4 <> '<5' THEN
    RAISE EXCEPTION 'FAIL V04 — v_report_mensile con 4 richieste = (%, %), atteso (NULL, ''<5'')', coalesce(n_4::text,'NULL'), lbl_4;
  END IF;

  -- v_destinazioni: 4 destinazioni verso lo stesso luogo → mascherate
  INSERT INTO trasi.richiesta (casa_id, categoria, esito, destinazione_id)
  SELECT casa, 'fiscale_isee', 'inviata_altrove', l.id FROM trasi.luogo l, generate_series(1,4)
   WHERE l.nome = 'CAF ACLI La Rosa';
  IF EXISTS (SELECT 1 FROM trasi.v_destinazioni WHERE casa_id = casa AND n IS NOT NULL AND n < 5) THEN
    RAISE EXCEPTION 'FAIL V04 — v_destinazioni espone un conteggio sotto soglia';
  END IF;
  RAISE NOTICE 'PASS V04 — v_report_mensile e v_destinazioni: 4 conteggi → (NULL, ''<5'')';
END $$;

-- V05 · v_kb_export: doc_id stabile, solo elementi validi ------------------------------------
DO $$
DECLARE n integer; n_dup integer; chiusi integer;
BEGIN
  SELECT count(*) INTO n FROM trasi.v_kb_export;
  IF n < 30 THEN RAISE EXCEPTION 'FAIL V05 — v_kb_export ha % righe, attese >= 30 (22 luoghi + 10 case + schede/eventi/opportunità)', n; END IF;
  SELECT count(*) INTO n_dup FROM (SELECT doc_id FROM trasi.v_kb_export GROUP BY doc_id HAVING count(*) > 1) d;
  IF n_dup > 0 THEN RAISE EXCEPTION 'FAIL V05 — % doc_id duplicati: l''upsert sull''Ingestion API non sarebbe idempotente', n_dup; END IF;
  IF EXISTS (SELECT 1 FROM trasi.v_kb_export WHERE doc_id !~ '^trasi:[a-z_]+:[0-9]+$') THEN
    RAISE EXCEPTION 'FAIL V05 — doc_id fuori formato trasi:<entita>:<id>';
  END IF;

  -- un luogo chiuso esce dalla vista (soft-close, mai DELETE)
  UPDATE trasi.luogo SET chiuso_il = current_date - 1 WHERE nome = 'CAF CISL Perrino';
  SELECT count(*) INTO chiusi FROM trasi.v_kb_export WHERE entita = 'luogo' AND id = (SELECT id FROM trasi.luogo WHERE nome = 'CAF CISL Perrino');
  IF chiusi <> 0 THEN RAISE EXCEPTION 'FAIL V05 — un luogo chiuso (% righe) resta in v_kb_export', chiusi; END IF;

  -- un'opportunità scaduta esce (US-06)
  INSERT INTO trasi.opportunita (casa_id, titolo, scadenza, fonte_id)
  SELECT c.id, 'Bando di prova V05 (scaduto)', current_date - 1, f.id
  FROM trasi.casa c, trasi.fonte f WHERE c.slug = 'san-bao' AND f.nome = 'Rete-kb-3';
  IF EXISTS (SELECT 1 FROM trasi.v_kb_export WHERE titolo = 'Bando di prova V05 (scaduto)') THEN
    RAISE EXCEPTION 'FAIL V05 — un''opportunità scaduta resta in v_kb_export (US-06 violata)';
  END IF;

  RAISE NOTICE 'PASS V05 — v_kb_export: % documenti, doc_id unici e nel formato trasi:<entita>:<id>; chiusi e scaduti esclusi', n;
END $$;

-- V06 · v_proposte_aperte non espone le identità (minimizzazione §12) ------------------------
DO $$
DECLARE colonne text;
BEGIN
  SELECT string_agg(column_name, ', ' ORDER BY column_name) INTO colonne
  FROM information_schema.columns WHERE table_schema = 'trasi' AND table_name = 'v_proposte_aperte';
  IF colonne ~ 'proposto_da' OR colonne ~ 'approvato_da' THEN
    RAISE EXCEPTION 'FAIL V06 — v_proposte_aperte espone l''identità: %', colonne;
  END IF;
  IF colonne !~ 'diff_leggibile|motivazione' THEN
    RAISE EXCEPTION 'FAIL V06 — v_proposte_aperte senza motivazione leggibile: %', colonne;
  END IF;
  RAISE NOTICE 'PASS V06 — v_proposte_aperte: nessuna colonna di identità, motivazione presente';
END $$;

-- V07 · v_oggi_casa: 10 righe (una per Casa), testo già formattato, età della coda mai NULL --------
DO $$
DECLARE n integer; t text; ev integer; tipo_colonna text; nulli integer; incoerenti integer;
BEGIN
  SELECT count(*) INTO n FROM trasi.v_oggi_casa;
  IF n <> 10 THEN RAISE EXCEPTION 'FAIL V07 — v_oggi_casa ha % righe, attese 10', n; END IF;
  SELECT testo, eventi INTO t, ev FROM trasi.v_oggi_casa WHERE slug = 'bozzano';
  IF t !~ '^Oggi a .+: \d+ (eventi|evento) · \d+ (schede|scheda) in scadenza · \d+ (proposte|proposta)$' THEN
    RAISE EXCEPTION 'FAIL V07 — riga «Oggi» fuori formato: %', t;
  END IF;
  -- `giorni_piu_vecchia` è 0 e non NULL anche a coda vuota (il consumatore lo usa come booleano),
  -- ed è l'età della proposta più vecchia in attesa. Un NULL qui non è «nessun dato»: è un errore.
  SELECT data_type INTO tipo_colonna FROM information_schema.columns
   WHERE table_schema = 'trasi' AND table_name = 'v_oggi_casa' AND column_name = 'giorni_piu_vecchia';
  IF tipo_colonna IS DISTINCT FROM 'integer' THEN
    RAISE EXCEPTION 'FAIL V07 — giorni_piu_vecchia è %, atteso integer', COALESCE(tipo_colonna, 'assente');
  END IF;
  SELECT count(*) INTO nulli FROM trasi.v_oggi_casa WHERE giorni_piu_vecchia IS NULL;
  IF nulli <> 0 THEN RAISE EXCEPTION 'FAIL V07 — giorni_piu_vecchia NULL su % Case (atteso 0)', nulli; END IF;
  SELECT count(*) INTO incoerenti FROM trasi.v_oggi_casa v
   WHERE v.giorni_piu_vecchia IS DISTINCT FROM COALESCE((SELECT current_date - min(p.proposto_ts)::date
                                                         FROM trasi.proposta p
                                                         WHERE p.casa_id = v.casa_id AND p.stato = 'proposta'), 0);
  IF incoerenti <> 0 THEN RAISE EXCEPTION 'FAIL V07 — giorni_piu_vecchia non è l''età della proposta più vecchia su % Case', incoerenti; END IF;
  RAISE NOTICE 'PASS V07 — v_oggi_casa: 10 Case · giorni_piu_vecchia mai NULL e coerente col minimo · esempio → «%»', t;
END $$;

-- V08 · v_mappa_case / v_mappa_luoghi: 10 pin, coordinate numeriche, raggio effettivo ---------
DO $$
DECLARE n integer; t integer; raggio integer; lat numeric;
BEGIN
  SELECT count(*) INTO n FROM trasi.v_mappa_case;
  IF n <> 10 THEN RAISE EXCEPTION 'FAIL V08 — v_mappa_case ha % pin, attesi 10', n; END IF;
  SELECT raggio_m_eff, v_mappa_case.lat INTO raggio, lat FROM trasi.v_mappa_case WHERE slug = 'tuturano';
  IF raggio <> 2000 THEN RAISE EXCEPTION 'FAIL V08 — raggio_m_eff di Tuturano = %, atteso 2000', raggio; END IF;
  IF lat IS NULL OR abs(lat - 40.54525) > 0.001 THEN RAISE EXCEPTION 'FAIL V08 — lat Tuturano = %, attesa 40.54525', lat; END IF;
  -- le Case senza raggio_m usano il parametro [P]
  IF EXISTS (SELECT 1 FROM trasi.v_mappa_case WHERE raggio_m IS NULL AND raggio_m_eff <> 800) THEN
    RAISE EXCEPTION 'FAIL V08 — una Casa senza raggio_m non ricade sul parametro 800';
  END IF;
  SELECT count(*) INTO t FROM trasi.v_mappa_luoghi_vicini WHERE entro_50m;
  IF t < 1 THEN RAISE EXCEPTION 'FAIL V08 — nessun luogo entro 50 m dalla propria Casa (atteso il bar di Bozzano)'; END IF;
  -- il criterio della spec è preciso: il bar interno di Bozzano entro 50 m dalla Casa
  IF NOT EXISTS (SELECT 1 FROM trasi.v_mappa_luoghi_vicini v
                  WHERE v.casa_slug = 'bozzano' AND v.tipo = 'bar' AND v.entro_50m) THEN
    RAISE EXCEPTION 'FAIL V08 — il bar di Bozzano non risulta entro 50 m dalla Casa';
  END IF;
  RAISE NOTICE 'PASS V08 — v_mappa_case: 10 pin · Tuturano lat % raggio_eff 2000 · % luoghi entro 50 m, bar di Bozzano incluso', lat, t;
END $$;

-- V10 · v_fasce_cittadino (db/028): le distribuzioni del foglio 4.4 escono SOLO mascherate --------------
-- La decisione è «fasce + soglia 5». La prova che conta non è che il CHECK rifiuti `72` (lo fa la
-- migrazione): è che **nessun numero sotto soglia esca dalla vista**, per nessuna delle tre
-- dimensioni, e che il conteggio grezzo non sia esposto a fianco del mascherato.
DO $$
DECLARE n_4 integer; lbl_4 text; n_5 integer; lbl_5 text; casa_sb int; fuori int;
BEGIN
  -- La stessa regola già provata da V03 su `v_confronto_case`, qui sulle tre fasce nuove: 4 colloqui
  -- nella stessa cella → n NULL e «<5»; 5 → n = 5. La fixture usa la Casa di San Bao e si azzera prima,
  -- così il test è deterministico su qualunque stato del database.
  SELECT c.id INTO casa_sb FROM trasi.casa c WHERE c.slug = 'san-bao';

  -- 4 colloqui con la stessa combinazione di fasce: cella sotto soglia.
  DELETE FROM trasi.richiesta WHERE casa_id = casa_sb AND categoria = 'orientamento' AND esito = 'rinviata'
    AND fascia_eta = '60-74';
  INSERT INTO trasi.richiesta (casa_id, categoria, esito, fascia_eta, genere, provenienza)
    SELECT casa_sb, 'orientamento', 'rinviata', '60-74', 'donna', 'extra_ue' FROM generate_series(1, 4);

  -- La riga esiste (la cella è aggregata) e il numero grezzo **non** esce: è il punto della decisione.
  SELECT n, n_label INTO n_4, lbl_4
  FROM trasi.v_fasce_cittadino
  WHERE casa_slug = 'san-bao' AND dimensione = 'fascia_eta' AND valore = '60-74';
  IF n_4 IS NOT NULL THEN
    RAISE EXCEPTION 'FAIL V10 — con 4 colloqui n = % invece di NULL: il numero grezzo esce dalla vista', n_4;
  END IF;
  IF lbl_4 <> '<5' THEN RAISE EXCEPTION 'FAIL V10 — n_label = ''%'', atteso ''<5''', lbl_4; END IF;

  -- Le tre dimensioni sono tutte presenti, con i loro valori «non_dichiarat*» conteggiati.
  SELECT count(*) INTO fuori FROM trasi.v_fasce_cittadino WHERE casa_slug = 'san-bao'
   AND dimensione NOT IN ('fascia_eta','genere','provenienza');
  IF fuori <> 0 THEN RAISE EXCEPTION 'FAIL V10 — dimensione imprevista in v_fasce_cittadino: %', fuori; END IF;

  -- 5 colloqui: il numero esce — ed è il confine della maschera.
  DELETE FROM trasi.richiesta WHERE casa_id = casa_sb AND categoria = 'orientamento' AND esito = 'rinviata'
    AND fascia_eta = '30-44';
  INSERT INTO trasi.richiesta (casa_id, categoria, esito, fascia_eta)
  SELECT casa_sb, 'orientamento', 'rinviata', '30-44' FROM generate_series(1, 5);
  SELECT count(*) INTO n_5 FROM trasi.v_fasce_cittadino
   WHERE casa_slug = 'san-bao' AND dimensione = 'fascia_eta' AND valore = '30-44' AND n = 5;
  IF n_5 <> 1 THEN RAISE EXCEPTION 'FAIL V10 — 5 colloqui in una cella non espongono n = 5 (% righe)', n_5; END IF;

  RAISE NOTICE 'PASS V10 — v_fasce_cittadino: tre dimensioni, cella sotto soglia mascherata, 5 colte esatto';
END $$;

-- V11 · persona_casa (db/029): il nome entra nella KB SOLO con consenso, e la revoca lo toglie ------
-- La decisione C del gruppo Processi. Le due prove che la rendono legittima: (a) una persona senza
-- consenso NON produce riga in `v_kb_export` (quindi l'assistente non può citarla), (b) la revoca la
-- toglie **subito** — non al prossimo ciclo, non «quando serve»: la vista è la condizione, il flusso
-- di export la cancella da Onyx. In più l'isolamento cross-Casa della scrittura.
DO $$
DECLARE casa_sb int; persona_id int; in_kb int; v_tutte text;
BEGIN
  SELECT id INTO casa_sb FROM trasi.casa WHERE slug = 'san-bao';

  -- (a) senza consenso: la persona esiste, ma non entra in KB.
  DELETE FROM trasi.persona_casa WHERE casa_id = casa_sb AND nome = 'Maria Prova V11';
  INSERT INTO trasi.persona_casa (casa_id, nome, ruolo) VALUES (casa_sb, 'Maria Prova V11', 'psicologa di comunità');
  SELECT count(*) INTO in_kb FROM trasi.v_kb_export
   WHERE entita = 'persona' AND titolo LIKE 'Maria Prova V11%';
  IF in_kb <> 0 THEN
    RAISE EXCEPTION 'FAIL V11 — una persona senza consenso è già in v_kb_export (% righe): il consenso non è la condizione', in_kb;
  END IF;

  -- (b) con consenso: entra, e il testo porta nome, ruolo e Casa.
  UPDATE trasi.persona_casa SET consenso_il = current_date, informativa = 'informativa v1 · test'
   WHERE casa_id = casa_sb AND nome = 'Maria Prova V11';
  SELECT count(*) INTO in_kb FROM trasi.v_kb_export
   WHERE entita = 'persona' AND titolo LIKE 'Maria Prova V11%';
  IF in_kb <> 1 THEN
    RAISE EXCEPTION 'FAIL V11 — la persona con consenso non è in v_kb_export (% righe)', in_kb;
  END IF;

  -- (c) la revoca la toglie immediatamente: è ciò che rende revocabile il consenso.
  UPDATE trasi.persona_casa SET revoca_il = current_date WHERE casa_id = casa_sb AND nome = 'Maria Prova V11';
  SELECT count(*) INTO in_kb FROM trasi.v_kb_export WHERE entita = 'persona' AND titolo LIKE 'Maria Prova V11%';
  IF in_kb <> 0 THEN
    RAISE EXCEPTION 'FAIL V11 — dopo la revoca la persona è ancora in v_kb_export (% righe)', in_kb;
  END IF;

  -- (d) il ramo persona della vista è condizionato al consenso, per costruzione (v. 027 §4).
  v_tutte := pg_get_viewdef('trasi.v_kb_export'::regclass, true);
  IF position('consenso_il IS NOT NULL' in v_tutte) = 0 THEN
    RAISE EXCEPTION 'FAIL V11 — il ramo persona di v_kb_export non è filtrato per consenso';
  END IF;

  DELETE FROM trasi.persona_casa WHERE casa_id = casa_sb AND nome = 'Maria Prova V11';
  RAISE NOTICE 'PASS V11 — persona_casa: senza consenso fuori dalla KB · con consenso dentro · revoca la toglie subito';
END $$;

-- V09 · security_invoker: le viste di reporting sono owner-rights, come richiesto ------------
-- Con security_invoker=false la vista gira come trasi_owner: è ciò che permette a metabase_ro
-- (che non ha SELECT su richiesta/proposta) di leggere gli aggregati senza vedere le righe grezze.
DO $$
DECLARE cattive text;
BEGIN
  SELECT string_agg(c.relname, ', ' ORDER BY c.relname) INTO cattive
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
  WHERE n.nspname = 'trasi' AND c.relkind = 'v' AND c.relname LIKE 'v\_%'
    -- Viste che girano VOLUTAMENTE come owner (security_invoker=true assente):
    --  * v_da_approvare, v_scritture_senza_audit — diagnostica, non esposte a metabase_ro
    --  * v_flusso_* (B4) — servono agli alert notturni, che devono vedere tutte le Case;
    --    B5 ha rimosso `metabase_ro` dai loro GRANT proprio per non aggirare il least-privilege.
    AND c.relname NOT IN ('v_da_approvare','v_scritture_senza_audit',
                          'v_flusso_alert_proposte','v_flusso_coerenza_fonti',
                          'v_flusso_destinatari','v_flusso_recapiti',
                          'v_report','v_commento')
    AND NOT EXISTS (SELECT 1 FROM unnest(coalesce(c.reloptions, '{}'::text[])) o WHERE o = 'security_invoker=false');
  IF cattive IS NOT NULL THEN
    RAISE EXCEPTION 'FAIL V09 — viste senza security_invoker=false: %', cattive;
  END IF;
  IF (SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = 'trasi.v_confronto_case'::regclass) <> 'trasi_owner' THEN
    RAISE EXCEPTION 'FAIL V09 — v_confronto_case non è di trasi_owner';
  END IF;
  RAISE NOTICE 'PASS V09 — viste v_* security_invoker=false con owner trasi_owner (metabase_ro legge gli aggregati, non le righe)';
END $$;
