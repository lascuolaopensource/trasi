-- ============================================================================
-- Trasi — B1 · tests/test_zero_scritture.sql
-- Worker proprietario: trasi-proposte.
--
-- SCOPO: per OGNI via di scrittura verso la memoria applicativa
-- (luogo, scheda_servizio, evento, opportunita, casa) dimostrare che l'esito e'
-- quello previsto da V4: `42501` (privilegio/RLS) oppure `0 righe` (RLS che
-- filtra). L'unico esito positivo ammesso e' l'upsert iCal su `evento` da una
-- fonte `tipo_accesso='ical'` (§8 F4), piu' il percorso mediato
-- proposta -> approvazione -> `applica_proposte_approvate` + `audit`.
--
-- Convenzione: PASS = NOTICE, FAIL = EXCEPTION (SQLSTATE, e con
-- `ON_ERROR_STOP on` il run si ferma: un FAIL non viene mai assorbito).
--
-- COME GIRA (questo e' il punto delicato del test):
--   * il file si lancia come superuser solo per i fixture e per `SET SESSION
--     AUTHORIZATION`. Ogni verifica gira dentro una sessione autorizzata a un
--     ruolo APPLICATIVO (`SET SESSION AUTHORIZATION <ruolo>`), cioe' in un
--     contesto non-superuser autentico: `session_user` cambia davvero e le
--     protezioni sono esercitate come le incontrerebbe l'applicazione;
--   * `SET LOCAL ROLE` NON basta e NON si usa: girando da superuser il
--     superuser puo' assumere qualunque ruolo (anche `applicatore`), e in piu'
--     un'eccezione catturata ne annulla l'effetto, riportando la sessione ai
--     privilegi di superuser — il test diventerebbe verde per il motivo
--     sbagliato. Verificato: con `SET LOCAL ROLE applicatore` da superuser
--     l'escalation RIUSCIVA (era un falso PASS del test stesso);
--   * i fixture di dominio sono scritti dal ruolo `applicatore`;
--   * tutto gira in UNA transazione che termina con `ROLLBACK`: nessun residuo
--     (proposte, audit, luoghi di prova), quindi il test e' rieseguibile;
--   * `pg_temp.zs_ok` e' creata PRIMA di autorizzare la sessione, cosi' resta
--     richiamabile anche dentro la sessione applicativa.
--
-- Uso:
--   docker compose -f deployment/docker-compose.yml exec -T db_trasi \
--     psql -U postgres -d trasi_db -v ON_ERROR_STOP=1 -f - < db/tests/test_zero_scritture.sql
--
-- [ASSUNZIONE] Nomi di ruolo/tabella/colonna dal contratto congelato
-- (`.specs/B1-dati.md` + `.specs/B1-proposte.md`) e da §7.1 dell'architettura,
-- verificati sul DDL reale applicato in `trasi_db`.
-- ============================================================================
\set ON_ERROR_STOP on

-- Helper di asserzione: PASS = NOTICE, FAIL = EXCEPTION.
-- In `pg_temp`: sparisce con la sessione, non lascia residui nel DB.
CREATE FUNCTION pg_temp.zs_ok(p_ok boolean, p_msg text) RETURNS void
LANGUAGE plpgsql AS $fn$
BEGIN
  IF p_ok THEN
    RAISE NOTICE 'PASS %', p_msg;
  ELSE
    RAISE EXCEPTION 'FAIL %', p_msg;
  END IF;
END
$fn$;

BEGIN;

-- ---------------------------------------------------------------------------
-- §0 — Contesto: presupposti e fixture
-- ---------------------------------------------------------------------------
CREATE TEMP TABLE zs_ctx ON COMMIT DROP AS
SELECT
  (SELECT id FROM trasi.casa WHERE slug = 'san-bao')  AS id_sanbao,
  (SELECT id FROM trasi.casa WHERE slug = 'bozzano')  AS id_bozzano,
  (SELECT id FROM trasi.fonte WHERE tipo_accesso = 'ical' ORDER BY id LIMIT 1)             AS id_fonte_ical,
  (SELECT id FROM trasi.fonte WHERE tipo_accesso <> 'ical' AND attiva ORDER BY id LIMIT 1) AS id_fonte_nonical;

-- Identificativi dei fixture: le asserzioni puntano a QUESTE righe, non a un
-- conteggio per Casa. Il database puo' contenere dati pregressi (esecuzioni
-- precedenti di altri test): un conteggio renderebbe il test dipendente
-- dall'ordine di esecuzione, cioe' rosso o verde per il motivo sbagliato.
CREATE TEMP TABLE zs_fix (slug text primary key, scheda_id int) ON COMMIT DROP;

DO $s0$
DECLARE c zs_ctx;
BEGIN
  RAISE NOTICE '=== §0 Contesto e presupposti ===';
  SELECT * INTO c FROM zs_ctx;

  PERFORM pg_temp.zs_ok((SELECT count(*) FROM trasi.casa) = 10,
    format('seed: 10 Case presenti (trovate %s)', (SELECT count(*) FROM trasi.casa)));
  PERFORM pg_temp.zs_ok(c.id_sanbao IS NOT NULL AND c.id_bozzano IS NOT NULL,
    'seed: le Case San Bao e Bozzano esistono');
  PERFORM pg_temp.zs_ok(c.id_fonte_ical IS NOT NULL,
    'seed: esiste una fonte `ical` (Google Calendar) — senza, l''eccezione iCal non e'' testabile');
  PERFORM pg_temp.zs_ok(c.id_fonte_nonical IS NOT NULL,
    'seed: esiste una fonte non-iCal attiva');
  PERFORM pg_temp.zs_ok((SELECT count(*) FROM trasi.ruolo_casa) >= 10,
    format('seed: ruolo_casa popolato (%s righe) — senza, casa_corrente() sarebbe NULL per tutti',
           (SELECT count(*) FROM trasi.ruolo_casa)));
END
$s0$;

-- Istante di inizio della batteria: e' il `:t0` del criterio B1-PRP-06
-- (`SELECT count(*) FROM v_scritture_senza_audit WHERE ts > :t0`). Serve a
-- isolare cio' che produce questa esecuzione da eventuale pregresso del DB.
CREATE TEMP TABLE zs_run (t0 timestamptz) ON COMMIT DROP;
INSERT INTO zs_run VALUES (clock_timestamp());
CREATE FUNCTION pg_temp.zs_t0() RETURNS timestamptz
LANGUAGE sql STABLE AS $fn$ SELECT t0 FROM zs_run $fn$;

-- Fixture di dominio. Sono dati INIZIALI di prova, non scritture applicative:
-- li crea `trasi_owner`, lo stesso ruolo del seed (e la contabilita' di
-- `v_scritture_senza_audit` tratta le scritture dell'owner come caricamento
-- iniziale, non come mutazioni da tracciare). Servono a rendere NON VACUI i
-- test di RLS: senza righe reali, «0 righe» sarebbe vero per tabella vuota.
INSERT INTO zs_fix (slug, scheda_id)
SELECT c.slug, s.id
  FROM trasi.casa c
  CROSS JOIN LATERAL (
    SELECT id FROM trasi.scheda_servizio
     WHERE casa_id = c.id AND categoria = 'ZS-fixture' LIMIT 1) s
 WHERE c.slug IN ('bozzano', 'san-bao');

DO $fix$
DECLARE v_casa record;
BEGIN
  IF (SELECT count(*) FROM zs_fix) = 0 THEN
    SET SESSION AUTHORIZATION trasi_owner;
    FOR v_casa IN SELECT id, slug FROM trasi.casa WHERE slug IN ('bozzano', 'san-bao') LOOP
      INSERT INTO trasi.scheda_servizio (casa_id, titolo, categoria)
      VALUES (v_casa.id, 'ZS fixture ' || v_casa.slug, 'ZS-fixture');
    END LOOP;
    RESET SESSION AUTHORIZATION;
    INSERT INTO zs_fix (slug, scheda_id)
    SELECT cc.slug, s.id
      FROM trasi.casa cc
      JOIN LATERAL (SELECT id FROM trasi.scheda_servizio
                     WHERE casa_id = cc.id AND categoria = 'ZS-fixture' LIMIT 1) s ON true
     WHERE cc.slug IN ('bozzano', 'san-bao');
  END IF;
END
$fix$;

DO $s0b$
BEGIN
  PERFORM pg_temp.zs_ok((SELECT count(*) FROM zs_fix) = 2,
    format('fixture: 2 schede di prova pronte (Bozzano + San Bao) (%s)', (SELECT count(*) FROM zs_fix)));
  PERFORM pg_temp.zs_ok(
    NOT EXISTS (SELECT 1 FROM pg_roles
                 WHERE (rolname IN ('applicatore','automazioni','shim_rw','rete','ti','metabase_ro')
                        OR rolname LIKE 'casa\_%')
                   AND rolbypassrls),
    'V4: nessun ruolo applicativo ha BYPASSRLS (la RLS e'' l''autorita'')');
END
$s0b$;

-- ---------------------------------------------------------------------------
-- §1 — shim_rw: nessuna scrittura di dominio
-- ---------------------------------------------------------------------------
DO $s1$
DECLARE c zs_ctx; v_code text;
BEGIN
  RAISE NOTICE '=== §1 shim_rw: nessuna scrittura di dominio ===';
  SELECT * INTO c FROM zs_ctx;

  v_code := NULL;
  BEGIN
    SET SESSION AUTHORIZATION shim_rw;
    INSERT INTO trasi.luogo (nome, tipo, fonte_id, affidabilita) VALUES ('ZS shim luogo', 'bar', c.id_fonte_nonical, 2);
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code = '42501',
    format('shim_rw INSERT luogo → 42501 (ottenuto: %s)', COALESCE(v_code, 'NESSUN ERRORE: scrittura riuscita')));

  v_code := NULL;
  BEGIN
    SET SESSION AUTHORIZATION shim_rw;
    UPDATE trasi.scheda_servizio SET titolo = 'ZS shim' WHERE casa_id = c.id_sanbao;
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code = '42501',
    format('shim_rw UPDATE scheda_servizio → 42501 (ottenuto: %s)', COALESCE(v_code, 'NESSUN ERRORE: scrittura riuscita')));

  v_code := NULL;
  BEGIN
    SET SESSION AUTHORIZATION shim_rw;
    DELETE FROM trasi.evento WHERE casa_id = c.id_sanbao;
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code = '42501',
    format('shim_rw DELETE evento → 42501 (ottenuto: %s)', COALESCE(v_code, 'NESSUN ERRORE: cancellazione riuscita')));

  v_code := NULL;
  BEGIN
    SET SESSION AUTHORIZATION shim_rw;
    UPDATE trasi.casa SET orari_provvisori = true WHERE id = c.id_sanbao;
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code = '42501',
    format('shim_rw UPDATE casa → 42501 (ottenuto: %s)', COALESCE(v_code, 'NESSUN ERRORE: scrittura riuscita')));

  v_code := NULL;
  BEGIN
    SET SESSION AUTHORIZATION shim_rw;
    INSERT INTO trasi.opportunita (casa_id, titolo) VALUES (c.id_sanbao, 'ZS shim opportunita');
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code = '42501',
    format('shim_rw INSERT opportunita → 42501 (ottenuto: %s)', COALESCE(v_code, 'NESSUN ERRORE: scrittura riuscita')));
END
$s1$;

-- ---------------------------------------------------------------------------
-- §2 — Ruolo Casa: 0 righe fuori dalla propria Casa, 42501 dove manca il
--      privilegio; controprova positiva sulla propria Casa
-- ---------------------------------------------------------------------------
DO $s2$
DECLARE
  c zs_ctx;
  v_code text;
  v_n bigint;
  -- Gli identificativi dei fixture si leggono PRIMA di autorizzare la
  -- sessione: la temp table e' del superuser e i ruoli applicativi non hanno
  -- (ne' devono avere) alcun privilegio su di essa.
  v_scheda_bozzano int := (SELECT scheda_id FROM zs_fix WHERE slug = 'bozzano');
  v_scheda_sanbao  int := (SELECT scheda_id FROM zs_fix WHERE slug = 'san-bao');
BEGIN
  RAISE NOTICE '=== §2 ruolo Casa (casa_sanbao) ===';
  SELECT * INTO c FROM zs_ctx;

  -- RLS: la riga di un'altra Casa non e' visibile all'UPDATE → 0 righe.
  -- Il bersaglio e' la scheda fixture di BOZZANO: una riga che esiste davvero,
  -- quindi lo «0 righe» e' merito della RLS, non dell'assenza di dati.
  v_code := NULL; v_n := NULL;
  BEGIN
    SET SESSION AUTHORIZATION casa_sanbao;
    UPDATE trasi.scheda_servizio SET titolo = 'ZS cross' WHERE id = v_scheda_bozzano;
    GET DIAGNOSTICS v_n = ROW_COUNT;
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code IS NULL AND v_n = 0,
    format('casa_sanbao UPDATE scheda_servizio di BOZZANO → 0 righe (errore=%s, righe=%s)',
           COALESCE(v_code, 'no'), COALESCE(v_n::text, 'n/a')));

  -- Controprova: sulla PROPRIA Casa la stessa UPDATE tocca 1 riga. Senza questa,
  -- i «0 righe» sopra sarebbero verdi anche se nessuno potesse scrivere nulla.
  v_code := NULL; v_n := NULL;
  BEGIN
    SET SESSION AUTHORIZATION casa_sanbao;
    UPDATE trasi.scheda_servizio SET titolo = 'ZS fixture san-bao' WHERE id = v_scheda_sanbao;
    GET DIAGNOSTICS v_n = ROW_COUNT;
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code IS NULL AND v_n = 1,
    format('casa_sanbao UPDATE scheda_servizio della PROPRIA Casa → 1 riga (errore=%s, righe=%s)',
           COALESCE(v_code, 'no'), COALESCE(v_n::text, 'n/a')));

  v_code := NULL;
  BEGIN
    SET SESSION AUTHORIZATION casa_sanbao;
    INSERT INTO trasi.luogo (nome, tipo, fonte_id, affidabilita) VALUES ('ZS casa luogo', 'bar', c.id_fonte_nonical, 2);
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code = '42501',
    format('casa_sanbao INSERT luogo → 42501 (ottenuto: %s)', COALESCE(v_code, 'NESSUN ERRORE: scrittura riuscita')));

  -- La matrice congelata ammette il gestore a scrivere eventi DELLA PROPRIA
  -- Casa (D1): `evento` e' quindi l'entita' dove il confine cross-Casa va
  -- provato esplicitamente, perche' il privilegio esiste davvero e un errore di
  -- policy qui scriverebbe nel calendario di un'altra Casa.
  v_code := NULL;
  BEGIN
    SET SESSION AUTHORIZATION casa_sanbao;
    INSERT INTO trasi.evento (casa_id, titolo, inizio)
    VALUES (c.id_bozzano, 'ZS evento di Bozzano', now() + interval '3 day');
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code = '42501',
    format('casa_sanbao INSERT evento per BOZZANO → 42501 (RLS cross-Casa) (ottenuto: %s)',
           COALESCE(v_code, 'NESSUN ERRORE: evento scritto in un''altra Casa')));

  -- Controprova: per la PROPRIA Casa l'INSERT e' legittimo (1 riga).
  v_code := NULL; v_n := NULL;
  BEGIN
    SET SESSION AUTHORIZATION casa_sanbao;
    INSERT INTO trasi.evento (casa_id, titolo, inizio)
    VALUES (c.id_sanbao, 'ZS evento di San Bao', now() + interval '3 day');
    GET DIAGNOSTICS v_n = ROW_COUNT;
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code IS NULL AND v_n = 1,
    format('casa_sanbao INSERT evento della PROPRIA Casa → 1 riga (errore=%s, righe=%s)',
           COALESCE(v_code, 'no'), COALESCE(v_n::text, 'n/a')));

  -- La matrice ammette il gestore a scrivere un evento della propria Casa
  -- (D1): il punto di V4 non e' vietarlo, ma impedire che quella scrittura
  -- umana venga registrata come `ical_upsert`, cioe' che si mascheri da
  -- eccezione automatica. L'audit deve dire la verita' sulla provenienza.
  PERFORM pg_temp.zs_ok(
    NOT EXISTS (SELECT 1 FROM trasi.audit a
                 JOIN trasi.evento e ON e.id = a.entita_id
                WHERE a.azione = 'ical_upsert' AND a.entita = 'evento'
                  AND e.casa_id = c.id_sanbao AND e.uid_ical IS NULL),
    'una scrittura umana di evento NON viene registrata come `ical_upsert` (provenienza non falsificata)');

  -- `casa`: la colonna non concessa (`nome`) deve dare 42501 — non basta la RLS.
  v_code := NULL;
  BEGIN
    SET SESSION AUTHORIZATION casa_sanbao;
    UPDATE trasi.casa SET nome = nome WHERE id = c.id_sanbao;
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code = '42501',
    format('casa_sanbao UPDATE casa(nome) — colonna non concessa → 42501 (ottenuto: %s)',
           COALESCE(v_code, 'NESSUN ERRORE: scrittura riuscita')));

  -- Sulla colonna concessa la RLS fa il suo mestiere: 0 fuori Casa, 1 in Casa.
  v_code := NULL; v_n := NULL;
  BEGIN
    SET SESSION AUTHORIZATION casa_sanbao;
    UPDATE trasi.casa SET orari_provvisori = orari_provvisori WHERE id = c.id_bozzano;
    GET DIAGNOSTICS v_n = ROW_COUNT;
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code IS NULL AND v_n = 0,
    format('casa_sanbao UPDATE casa(orari_provvisori) di BOZZANO → 0 righe (errore=%s, righe=%s)',
           COALESCE(v_code, 'no'), COALESCE(v_n::text, 'n/a')));

  v_code := NULL; v_n := NULL;
  BEGIN
    SET SESSION AUTHORIZATION casa_sanbao;
    UPDATE trasi.casa SET orari_provvisori = orari_provvisori WHERE id = c.id_sanbao;
    GET DIAGNOSTICS v_n = ROW_COUNT;
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code IS NULL AND v_n = 1,
    format('casa_sanbao UPDATE casa(orari_provvisori) della PROPRIA Casa → 1 riga (errore=%s, righe=%s)',
           COALESCE(v_code, 'no'), COALESCE(v_n::text, 'n/a')));
END
$s2$;

-- ---------------------------------------------------------------------------
-- §3 — automazioni: divieti di dominio + UNICA eccezione (upsert iCal su evento)
-- ---------------------------------------------------------------------------
DO $s3$
DECLARE c zs_ctx; v_code text; v_n bigint; v_id int;
BEGIN
  RAISE NOTICE '=== §3 automazioni: divieti + eccezione iCal ===';
  SELECT * INTO c FROM zs_ctx;

  v_code := NULL;
  BEGIN
    SET SESSION AUTHORIZATION automazioni;
    INSERT INTO trasi.luogo (nome, tipo, fonte_id, affidabilita) VALUES ('ZS autom luogo', 'bar', c.id_fonte_nonical, 2);
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code = '42501',
    format('automazioni INSERT luogo → 42501 (ottenuto: %s)', COALESCE(v_code, 'NESSUN ERRORE: scrittura riuscita')));

  v_code := NULL;
  BEGIN
    SET SESSION AUTHORIZATION automazioni;
    INSERT INTO trasi.opportunita (casa_id, titolo) VALUES (c.id_sanbao, 'ZS autom opportunita');
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code = '42501',
    format('automazioni INSERT opportunita → 42501 (ottenuto: %s)', COALESCE(v_code, 'NESSUN ERRORE: scrittura riuscita')));

  v_code := NULL;
  BEGIN
    SET SESSION AUTHORIZATION automazioni;
    UPDATE trasi.scheda_servizio SET titolo = 'ZS autom' WHERE casa_id = c.id_sanbao;
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code = '42501',
    format('automazioni UPDATE scheda_servizio → 42501 (ottenuto: %s)', COALESCE(v_code, 'NESSUN ERRORE: scrittura riuscita')));

  v_code := NULL;
  BEGIN
    SET SESSION AUTHORIZATION automazioni;
    UPDATE trasi.casa SET orari_provvisori = orari_provvisori WHERE id = c.id_sanbao;
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code = '42501',
    format('automazioni UPDATE casa → 42501 (ottenuto: %s)', COALESCE(v_code, 'NESSUN ERRORE: scrittura riuscita')));

  -- Eccezione a V4 (§8 F4): upsert iCal su `evento` da fonte ical → 1 riga.
  v_code := NULL; v_n := NULL; v_id := NULL;
  BEGIN
    SET SESSION AUTHORIZATION automazioni;
    INSERT INTO trasi.evento (casa_id, titolo, inizio, uid_ical, fonte_id)
    VALUES (c.id_sanbao, 'ZS evento iCal', now() + interval '1 day', 'zs-test-ical-1', c.id_fonte_ical)
    RETURNING id INTO v_id;
    GET DIAGNOSTICS v_n = ROW_COUNT;
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code IS NULL AND v_n = 1,
    format('automazioni INSERT evento da fonte iCal → 1 riga (ECCEZIONE ATTESA, positiva) (errore=%s, righe=%s)',
           COALESCE(v_code, 'no'), COALESCE(v_n::text, 'n/a')));

  -- L'eccezione e' vincolata alla fonte iCal: con una fonte non-iCal → 42501.
  v_code := NULL;
  BEGIN
    SET SESSION AUTHORIZATION automazioni;
    INSERT INTO trasi.evento (casa_id, titolo, inizio, uid_ical, fonte_id)
    VALUES (c.id_sanbao, 'ZS evento non-iCal', now() + interval '2 day', 'zs-test-ical-2', c.id_fonte_nonical);
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code = '42501',
    format('automazioni INSERT evento da fonte NON iCal → 42501 (ottenuto: %s)',
           COALESCE(v_code, 'NESSUN ERRORE: scrittura riuscita')));

  -- L'upsert aggiorna (stessa chiave iCal) e resta confinato alla fonte iCal.
  v_code := NULL; v_n := NULL;
  BEGIN
    SET SESSION AUTHORIZATION automazioni;
    UPDATE trasi.evento SET titolo = 'ZS evento iCal aggiornato' WHERE uid_ical = 'zs-test-ical-1';
    GET DIAGNOSTICS v_n = ROW_COUNT;
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code IS NULL AND v_n = 1,
    format('automazioni UPDATE evento iCal → 1 riga (errore=%s, righe=%s)',
           COALESCE(v_code, 'no'), COALESCE(v_n::text, 'n/a')));

  -- Nessun DELETE: la rimozione e' `annullato = true`.
  v_code := NULL;
  BEGIN
    SET SESSION AUTHORIZATION automazioni;
    DELETE FROM trasi.evento WHERE uid_ical = 'zs-test-ical-1';
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code = '42501',
    format('automazioni DELETE evento → 42501 (ottenuto: %s)', COALESCE(v_code, 'NESSUN ERRORE: cancellazione riuscita')));

  -- L'audit iCal c'e' (§8 F4: una riga per variazione) — contabilita', non
  -- euristica (B1-PRP-06).
  PERFORM pg_temp.zs_ok(
    (SELECT count(*) FROM trasi.audit WHERE azione = 'ical_upsert' AND entita = 'evento' AND entita_id = v_id) = 2,
    format('audit: 2 righe `ical_upsert` per l''evento di prova (INSERT + UPDATE) (trovate %s)',
           (SELECT count(*) FROM trasi.audit WHERE azione = 'ical_upsert' AND entita = 'evento' AND entita_id = v_id)));

  -- L'eccezione iCal non e' un varco generico: `automazioni` non puo' assumere
  -- `applicatore` (sessione applicativa reale, non superuser).
  v_code := NULL;
  BEGIN
    SET SESSION AUTHORIZATION automazioni;
    SET ROLE applicatore;
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code = '42501',
    format('automazioni non puo'' assumere il ruolo applicatore → 42501 (ottenuto: %s)',
           COALESCE(v_code, 'NESSUN ERRORE: ruolo assunto')));

  -- Stessa cosa per `trasi_owner`, che e' il proprietario dello schema e ha la
  -- policy permissiva `owner_all` su tutte le tabelle di dominio: se un ruolo
  -- applicativo ne fosse membro, scriverebbe la memoria senza proposta,
  -- aggirando V4 per intero. Il controllo e' sull'appartenenza, non sul ruolo.
  PERFORM pg_temp.zs_ok(
    NOT EXISTS (SELECT 1 FROM pg_auth_members m
                 JOIN pg_roles r ON r.oid = m.member
                 JOIN pg_roles g ON g.oid = m.roleid
                WHERE g.rolname = 'trasi_owner'
                  AND (r.rolname IN ('applicatore','automazioni','shim_rw','rete','ti','metabase_ro')
                       OR r.rolname LIKE 'casa\_%')),
    'nessun ruolo applicativo e'' membro di trasi_owner (policy owner_all non raggiungibile)');

  v_code := NULL;
  BEGIN
    SET SESSION AUTHORIZATION automazioni;
    SET ROLE trasi_owner;
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code = '42501',
    format('automazioni non puo'' assumere trasi_owner → 42501 (ottenuto: %s)',
           COALESCE(v_code, 'NESSUN ERRORE: ruolo assunto')));

  -- `v_scritture_senza_audit` non segnala la scrittura iCal (ha il suo audit).
  PERFORM pg_temp.zs_ok(
    (SELECT count(*) FROM trasi.v_scritture_senza_audit WHERE entita = 'evento' AND entita_id = v_id) = 0,
    'v_scritture_senza_audit: l''upsert iCal e'' contabilizzato (0 righe di scostamento)');
END
$s3$;

-- ---------------------------------------------------------------------------
-- §4 — metabase_ro, ti, rete: nessuna scrittura di dominio
-- ---------------------------------------------------------------------------
DO $s4$
DECLARE c zs_ctx; v_code text;
BEGIN
  RAISE NOTICE '=== §4 metabase_ro / ti / rete ===';
  SELECT * INTO c FROM zs_ctx;

  v_code := NULL;
  BEGIN
    SET SESSION AUTHORIZATION metabase_ro;
    INSERT INTO trasi.luogo (nome, tipo, fonte_id, affidabilita) VALUES ('ZS mb luogo', 'bar', c.id_fonte_nonical, 2);
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code = '42501',
    format('metabase_ro INSERT luogo → 42501 (ottenuto: %s)', COALESCE(v_code, 'NESSUN ERRORE: scrittura riuscita')));

  v_code := NULL;
  BEGIN
    SET SESSION AUTHORIZATION metabase_ro;
    UPDATE trasi.evento SET titolo = 'ZS mb' WHERE casa_id = c.id_sanbao;
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code = '42501',
    format('metabase_ro UPDATE evento → 42501 (ottenuto: %s)', COALESCE(v_code, 'NESSUN ERRORE: scrittura riuscita')));

  -- V4 rafforzato (divergenza dichiarata D-ti): anche `ti` non scrive il
  -- dominio, che appartiene al solo `applicatore`.
  v_code := NULL;
  BEGIN
    SET SESSION AUTHORIZATION ti;
    INSERT INTO trasi.luogo (nome, tipo, fonte_id, affidabilita) VALUES ('ZS ti luogo', 'bar', c.id_fonte_nonical, 2);
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code = '42501',
    format('ti INSERT luogo → 42501 (V4 rafforzato) (ottenuto: %s)', COALESCE(v_code, 'NESSUN ERRORE: scrittura riuscita')));

  v_code := NULL;
  BEGIN
    SET SESSION AUTHORIZATION rete;
    INSERT INTO trasi.luogo (nome, tipo, fonte_id, affidabilita) VALUES ('ZS rete luogo', 'bar', c.id_fonte_nonical, 2);
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code = '42501',
    format('rete INSERT luogo → 42501 (ottenuto: %s)', COALESCE(v_code, 'NESSUN ERRORE: scrittura riuscita')));
END
$s4$;

-- ---------------------------------------------------------------------------
-- §5 — Auto-approvazione vietata (V4 regola 1)
--      `proposto_da <> current_user`: la riga non e' decidibile da chi l'ha
--      proposta → **0 righe** (la RLS filtra, non solleva).
-- ---------------------------------------------------------------------------
DO $s5$
DECLARE c zs_ctx; v_code text; v_n bigint; v_id bigint; v_appr text;
BEGIN
  RAISE NOTICE '=== §5 auto-approvazione vietata ===';
  SELECT * INTO c FROM zs_ctx;

  -- 5.1 Una Casa propone una modifica orari DELLA PROPRIA Casa: nasce con
  --     approvatore_ruolo='gestore' (calcolato dal trigger, non scelto).
  SET SESSION AUTHORIZATION casa_sanbao;
  INSERT INTO trasi.proposta (origine, tipo, entita, entita_id, casa_id, payload, motivazione)
  VALUES ('chat', 'modifica_orari_casa', 'casa', c.id_sanbao, c.id_sanbao,
          jsonb_build_object('orari_provvisori', true), 'ZS test auto-approvazione')
  RETURNING id, approvatore_ruolo INTO v_id, v_appr;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_appr = 'gestore' AND v_id IS NOT NULL,
    format('trigger: proposta di Casa con tipo gestore → approvatore_ruolo=%s (atteso gestore)', v_appr));

  -- 5.2 La stessa Casa prova ad approvarla: 0 righe.
  v_code := NULL; v_n := NULL;
  BEGIN
    SET SESSION AUTHORIZATION casa_sanbao;
    UPDATE trasi.proposta SET stato = 'approvata' WHERE id = v_id;
    GET DIAGNOSTICS v_n = ROW_COUNT;
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code IS NULL AND v_n = 0,
    format('AUTO-APPROVAZIONE (propria proposta): UPDATE stato=''approvata'' → 0 righe (errore=%s, righe=%s)',
           COALESCE(v_code, 'no'), COALESCE(v_n::text, 'n/a')));

  -- 5.3 Proposta di un'ALTRA Casa → 0 righe (RLS).
  SET SESSION AUTHORIZATION casa_bozzano;
  INSERT INTO trasi.proposta (origine, tipo, entita, entita_id, casa_id, payload, motivazione)
  VALUES ('chat', 'modifica_orari_casa', 'casa', c.id_bozzano, c.id_bozzano,
          jsonb_build_object('orari_provvisori', true), 'ZS test altra Casa')
  RETURNING id INTO v_id;
  RESET SESSION AUTHORIZATION;

  v_code := NULL; v_n := NULL;
  BEGIN
    SET SESSION AUTHORIZATION casa_sanbao;
    UPDATE trasi.proposta SET stato = 'approvata' WHERE id = v_id;
    GET DIAGNOSTICS v_n = ROW_COUNT;
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code IS NULL AND v_n = 0,
    format('proposta di BOZZANO decisa da SAN BAO → 0 righe (errore=%s, righe=%s)',
           COALESCE(v_code, 'no'), COALESCE(v_n::text, 'n/a')));

  -- 5.4 Proposta della PROPRIA Casa ma di tipo non-gestore (`chiudi_luogo` →
  --     approvatore 'at'): il gestore non decide → 0 righe.
  SET SESSION AUTHORIZATION casa_sanbao;
  INSERT INTO trasi.proposta (origine, tipo, entita, entita_id, casa_id, payload, motivazione)
  VALUES ('chat', 'chiudi_luogo', 'luogo', NULL, c.id_sanbao,
          jsonb_build_object('chiuso_il', current_date::text), 'ZS test tipo at')
  RETURNING id, approvatore_ruolo INTO v_id, v_appr;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_appr = 'at',
    format('trigger: proposta `chiudi_luogo` → approvatore_ruolo=%s (atteso at)', v_appr));

  v_code := NULL; v_n := NULL;
  BEGIN
    SET SESSION AUTHORIZATION casa_sanbao;
    UPDATE trasi.proposta SET stato = 'approvata' WHERE id = v_id;
    GET DIAGNOSTICS v_n = ROW_COUNT;
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code IS NULL AND v_n = 0,
    format('gestore su proposta di TIPO at → 0 righe (errore=%s, righe=%s)',
           COALESCE(v_code, 'no'), COALESCE(v_n::text, 'n/a')));

  -- 5.5 Controprova positiva: proposta `gestore` per San Bao creata da `rete` e
  --     approvata dal gestore di San Bao → 1 riga. Senza questa, i «0 righe»
  --     sopra potrebbero dipendere da un divieto generale invece che dalla
  --     regola di non-auto-approvazione.
  SET SESSION AUTHORIZATION rete;
  INSERT INTO trasi.proposta (origine, tipo, entita, entita_id, casa_id, payload, motivazione)
  VALUES ('manuale', 'modifica_orari_casa', 'casa', c.id_sanbao, c.id_sanbao,
          jsonb_build_object('orari_provvisori', false), 'ZS test approvazione legittima')
  RETURNING id INTO v_id;
  RESET SESSION AUTHORIZATION;

  v_code := NULL; v_n := NULL;
  BEGIN
    SET SESSION AUTHORIZATION casa_sanbao;
    UPDATE trasi.proposta SET stato = 'approvata', nota_decisione = 'ok dal gestore' WHERE id = v_id;
    GET DIAGNOSTICS v_n = ROW_COUNT;
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code IS NULL AND v_n = 1,
    format('gestore di San Bao approva una proposta NON sua della propria Casa → 1 riga (errore=%s, righe=%s)',
           COALESCE(v_code, 'no'), COALESCE(v_n::text, 'n/a')));

  -- 5.6 Il client non si sceglie l'approvatore: colonna non grantata in INSERT.
  v_code := NULL;
  BEGIN
    SET SESSION AUTHORIZATION casa_sanbao;
    INSERT INTO trasi.proposta (origine, tipo, entita, casa_id, payload, motivazione, approvatore_ruolo)
    VALUES ('chat', 'modifica_orari_casa', 'casa', c.id_sanbao, '{}'::jsonb, 'ZS approvatore scelto', 'ti');
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code = '42501',
    format('client che si sceglie `approvatore_ruolo` in INSERT → 42501 (ottenuto: %s)',
           COALESCE(v_code, 'NESSUN ERRORE: approvatore forzato')));

  -- 5.7 E non puo' inserire una proposta gia' decisa: il buco `ins_any WITH
  --     CHECK (true)` del DDL §7.1, chiuso da `ins_client`.
  v_code := NULL;
  BEGIN
    SET SESSION AUTHORIZATION casa_sanbao;
    INSERT INTO trasi.proposta (origine, tipo, entita, casa_id, payload, motivazione,
                                stato, approvato_da, approvato_ts)
    VALUES ('chat', 'modifica_orari_casa', 'casa', c.id_sanbao, '{}'::jsonb, 'ZS proposta pre-approvata',
            'approvata', 'casa_sanbao', now());
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code = '42501',
    format('INSERT di proposta GIA'' approvata → 42501 (buco ins_any chiuso) (ottenuto: %s)',
           COALESCE(v_code, 'NESSUN ERRORE: proposta pre-approvata inserita')));

  -- 5.8 La `diff` e' obbligatoria e auto-generata: si approva leggendo
  --     (regola 3). La proposta di 5.5 ne ha una, generata dal trigger.
  PERFORM pg_temp.zs_ok(
    (SELECT diff IS NOT NULL AND diff ? 'prima' AND diff ? 'dopo' FROM trasi.proposta WHERE id = v_id),
    'diff: generato dal trigger con `prima`/`dopo` (si approva leggendo)');

  PERFORM pg_temp.zs_ok(
    (SELECT trasi.diff_leggibile(diff) LIKE '%orari_provvisori:%' FROM trasi.proposta WHERE id = v_id),
    format('diff_leggibile: rende il diff leggibile (%s)',
           (SELECT replace(trasi.diff_leggibile(diff), E'\n', ' / ') FROM trasi.proposta WHERE id = v_id)));

  -- 5.9 `motivazione` > 80 caratteri: respinta dal CHECK (V5).
  v_code := NULL;
  BEGIN
    SET SESSION AUTHORIZATION casa_sanbao;
    INSERT INTO trasi.proposta (origine, tipo, entita, casa_id, payload, motivazione)
    VALUES ('chat', 'modifica_orari_casa', 'casa', c.id_sanbao, '{}'::jsonb, repeat('x', 81));
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code = '23514',
    format('motivazione di 81 caratteri → 23514 (V5) (ottenuto: %s)', COALESCE(v_code, 'NESSUN ERRORE: accettata')));
END
$s5$;

-- ---------------------------------------------------------------------------
-- §6 — Percorso mediato: proposta → approvazione → applicazione, con audit
--      prima/dopo dell'ENTITA', idempotenza e savepoint per proposta
-- ---------------------------------------------------------------------------
DO $s6$
DECLARE
  c zs_ctx; v_n int; v_ok int; v_id1 bigint; v_id2 bigint;
  v_luogo1 int; v_luogo2 int; v_audit int; v_dopo text;
BEGIN
  RAISE NOTICE '=== §6 percorso mediato: applica_proposte_approvate ===';
  SELECT * INTO c FROM zs_ctx;

  SET SESSION AUTHORIZATION casa_sanbao;
  INSERT INTO trasi.proposta (origine, tipo, entita, casa_id, payload, motivazione)
  VALUES ('chat', 'nuovo_luogo', 'luogo', c.id_sanbao,
          jsonb_build_object('nome', 'ZS luogo applicato 1', 'tipo', 'caf'), 'ZS test applicazione 1')
  RETURNING id INTO v_id1;
  INSERT INTO trasi.proposta (origine, tipo, entita, casa_id, payload, motivazione)
  VALUES ('chat', 'nuovo_luogo', 'luogo', c.id_sanbao,
          jsonb_build_object('nome', 'ZS luogo applicato 2', 'tipo', 'bar'), 'ZS test applicazione 2')
  RETURNING id INTO v_id2;
  RESET SESSION AUTHORIZATION;

  SET SESSION AUTHORIZATION rete;
  UPDATE trasi.proposta SET stato = 'approvata' WHERE id IN (v_id1, v_id2);
  GET DIAGNOSTICS v_n = ROW_COUNT;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_n = 2, format('AT (rete) approva le 2 proposte → %s righe (atteso 2)', v_n));

  PERFORM pg_temp.zs_ok(
    (SELECT count(*) FROM trasi.luogo WHERE nome LIKE 'ZS luogo applicato%') = 0,
    'approvare non scrive il dominio: 0 luoghi ZS prima dell''applicazione');

  -- 1ª esecuzione. L'asserzione e' ristretta alle DUE proposte di questo
  -- paragrafo: il batch puo' contenerne altre approvate dai paragrafi
  -- precedenti (es. la controprova di §5.5), e includerle renderebbe il
  -- controllo dipendente dall'ordine di esecuzione dei paragrafi.
  SET SESSION AUTHORIZATION automazioni;
  SELECT count(*) FILTER (WHERE esito = 'ok') INTO v_ok
    FROM trasi.applica_proposte_approvate(10) WHERE proposta_id IN (v_id1, v_id2);
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_ok = 2,
    format('applica_proposte_approvate (1ª run) → %s righe esito=''ok'' per le 2 proposte (atteso 2)', v_ok));

  SELECT id INTO v_luogo1 FROM trasi.luogo WHERE nome = 'ZS luogo applicato 1';
  SELECT id INTO v_luogo2 FROM trasi.luogo WHERE nome = 'ZS luogo applicato 2';
  PERFORM pg_temp.zs_ok(v_luogo1 IS NOT NULL AND v_luogo2 IS NOT NULL,
    format('dominio scritto dal percorso mediato: luoghi %s e %s presenti',
           COALESCE(v_luogo1::text, '∅'), COALESCE(v_luogo2::text, '∅')));

  SELECT count(*) INTO v_audit FROM trasi.audit
   WHERE azione = 'applicata' AND entita = 'luogo' AND proposta_id IN (v_id1, v_id2);
  PERFORM pg_temp.zs_ok(v_audit = 2,
    format('audit: %s righe `applicata` per le 2 proposte (atteso 2)', v_audit));

  SELECT dopo->>'nome' INTO v_dopo FROM trasi.audit WHERE azione = 'applicata' AND proposta_id = v_id1;
  PERFORM pg_temp.zs_ok(v_dopo = 'ZS luogo applicato 1',
    format('audit.dopo e'' lo snapshot dell''ENTITA'' (luogo.nome=%s)', COALESCE(v_dopo, '∅')));

  PERFORM pg_temp.zs_ok((SELECT stato = 'applicata' FROM trasi.proposta WHERE id = v_id1),
    'proposta applicata: stato = applicata');

  -- Solo le proposte APPROVATE sono applicabili: una proposta ancora in stato
  -- `proposta` non deve essere toccata dal batch (ne' scritta nel dominio).
  -- Senza questo controllo, una `upd_appl` permissiva applicherebbe anche cio'
  -- che nessun umano ha approvato — il cuore di V4.
  DECLARE v_pending bigint; v_esiti text; v_nome text;
  BEGIN
    SET SESSION AUTHORIZATION casa_sanbao;
    INSERT INTO trasi.proposta (origine, tipo, entita, casa_id, payload, motivazione)
    VALUES ('chat', 'nuovo_luogo', 'luogo', c.id_sanbao,
            jsonb_build_object('nome', 'ZS luogo NON approvato', 'tipo', 'bar'),
            'ZS proposta non approvata')
    RETURNING id INTO v_pending;
    RESET SESSION AUTHORIZATION;

    SET SESSION AUTHORIZATION automazioni;
    SELECT string_agg(esito, ' | ') INTO v_esiti FROM trasi.applica_proposte_approvate(10);
    RESET SESSION AUTHORIZATION;

    SELECT nome INTO v_nome FROM trasi.luogo WHERE nome = 'ZS luogo NON approvato';
    PERFORM pg_temp.zs_ok(v_nome IS NULL,
      format('una proposta non approvata NON e'' applicata (luogo assente=%s)',
             COALESCE(v_nome, 'assente ✓')));

    PERFORM pg_temp.zs_ok((SELECT stato = 'proposta' FROM trasi.proposta WHERE id = v_pending),
      'la proposta non approvata resta in stato `proposta` (nessuno l''ha decisa)');

    -- E nemmeno il ruolo di macchina puo' portarla ad `applicata` per conto
    -- proprio: la policy `upd_appl` espone solo le proposte `approvata`. Il
    -- filtro della funzione non basta: `applicatore` e' un ruolo reale e la RLS
    -- deve reggere anche se qualcuno lo usa fuori dalla funzione.
    DECLARE v_app_code text; v_app_n bigint;
    BEGIN
      v_app_code := NULL; v_app_n := NULL;
      BEGIN
        SET SESSION AUTHORIZATION applicatore;
        UPDATE trasi.proposta SET stato = 'applicata' WHERE id = v_pending;
        GET DIAGNOSTICS v_app_n = ROW_COUNT;
      EXCEPTION WHEN OTHERS THEN v_app_code := SQLSTATE; END;
      RESET SESSION AUTHORIZATION;
      PERFORM pg_temp.zs_ok((v_app_code IS NULL AND v_app_n = 0) OR v_app_code = 'P0001',
        format('applicatore non applica una proposta non approvata (errore=%s, righe=%s)',
               COALESCE(v_app_code, 'no'), COALESCE(v_app_n::text, 'n/a')));
    END;
  END;

  -- 2ª esecuzione: 0 righe (idempotenza).
  SET SESSION AUTHORIZATION automazioni;
  SELECT count(*) INTO v_n FROM trasi.applica_proposte_approvate(10);
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_n = 0,
    format('applica_proposte_approvate (2ª run) → %s righe (atteso 0: idempotente)', v_n));

  PERFORM pg_temp.zs_ok(
    (SELECT count(*) FROM trasi.luogo WHERE nome LIKE 'ZS luogo applicato%') = 2,
    'idempotenza: nessun luogo duplicato dopo la 2ª run');

  PERFORM pg_temp.zs_ok(
    (SELECT count(*) FROM trasi.v_scritture_senza_audit
      WHERE entita = 'luogo' AND entita_id IN (v_luogo1, v_luogo2)) = 0,
    'v_scritture_senza_audit: 0 mutazioni non contabilizzate per i luoghi applicati');

  -- Savepoint per proposta: una proposta rotta non abbatte il batch.
  DECLARE v_bad bigint; v_good bigint; v_stato_bad text; v_audit_err int; v_res text;
  BEGIN
    SET SESSION AUTHORIZATION casa_sanbao;
    INSERT INTO trasi.proposta (origine, tipo, entita, entita_id, casa_id, payload, motivazione)
    VALUES ('chat', 'modifica_luogo', 'luogo', 2147483000, c.id_sanbao,
            jsonb_build_object('nome', 'ZS inesistente'), 'ZS test errore applicazione')
    RETURNING id INTO v_bad;
    INSERT INTO trasi.proposta (origine, tipo, entita, casa_id, payload, motivazione)
    VALUES ('chat', 'nuovo_luogo', 'luogo', c.id_sanbao,
            jsonb_build_object('nome', 'ZS luogo applicato 3', 'tipo', 'bar'), 'ZS test applicazione 3')
    RETURNING id INTO v_good;
    RESET SESSION AUTHORIZATION;

    SET SESSION AUTHORIZATION rete;
    UPDATE trasi.proposta SET stato = 'approvata' WHERE id IN (v_bad, v_good);
    RESET SESSION AUTHORIZATION;

    -- UNA sola esecuzione con la rotta e la buona nello stesso batch.
    SET SESSION AUTHORIZATION automazioni;
    SELECT string_agg(esito, ' | ' ORDER BY proposta_id) INTO v_res FROM trasi.applica_proposte_approvate(10);
    RESET SESSION AUTHORIZATION;

    PERFORM pg_temp.zs_ok(v_res LIKE '%errore:%inesistente%' AND v_res LIKE '%ok%',
      format('savepoint: il batch attraversa la proposta rotta E quella buona (esiti: %s)', COALESCE(v_res, '∅')));

    SELECT stato INTO v_stato_bad FROM trasi.proposta WHERE id = v_bad;
    PERFORM pg_temp.zs_ok(v_stato_bad = 'approvata',
      format('la proposta rotta resta `approvata` (ritentabile), stato=%s', COALESCE(v_stato_bad, '∅')));

    PERFORM pg_temp.zs_ok(EXISTS (SELECT 1 FROM trasi.luogo WHERE nome = 'ZS luogo applicato 3'),
      'la proposta buona dello stesso batch e'' stata applicata (il batch non e'' abortito)');

    SELECT count(*) INTO v_audit_err FROM trasi.audit
     WHERE azione = 'errore_applicazione' AND entita = 'luogo' AND proposta_id = v_bad;
    PERFORM pg_temp.zs_ok(v_audit_err = 1,
      format('errore applicazione tracciato in audit: %s riga (atteso 1)', v_audit_err));
  END;
END
$s6$;

-- ---------------------------------------------------------------------------
-- §7 — Macchina a stati e scadenza
-- ---------------------------------------------------------------------------
DO $s7$
DECLARE c zs_ctx; v_code text; v_id bigint; v_stato text; v_scad int; v_n bigint;
BEGIN
  RAISE NOTICE '=== §7 macchina a stati e scadenza ===';
  SELECT * INTO c FROM zs_ctx;

  -- 7.1 Transizione illegale `proposta` → `applicata`: P0001 dalla macchina a
  --     stati. Si usa una proposta visibile a `rete` (tipo `chiudi_luogo` →
  --     approvatore `at`): per un ruolo che non vede la riga l'esito sarebbe
  --     «0 righe» (RLS), e il vincolo di stato non verrebbe mai esercitato.
  SET SESSION AUTHORIZATION casa_sanbao;
  INSERT INTO trasi.proposta (origine, tipo, entita, casa_id, payload, motivazione)
  VALUES ('chat', 'chiudi_luogo', 'luogo', c.id_sanbao, '{}'::jsonb, 'ZS transizione illegale')
  RETURNING id INTO v_id;
  RESET SESSION AUTHORIZATION;

  v_code := NULL;
  BEGIN
    SET SESSION AUTHORIZATION rete;
    UPDATE trasi.proposta SET stato = 'applicata' WHERE id = v_id;
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code = 'P0001',
    format('transizione proposta→applicata → P0001 (ottenuto: %s)', COALESCE(v_code, 'NESSUN ERRORE: transizione ammessa')));

  -- E per un client la stessa transizione non e' nemmeno raggiungibile: la riga
  -- non e' decidibile da lui → 0 righe (difesa in profondita': RLS + macchina).
  v_code := NULL;
  BEGIN
    SET SESSION AUTHORIZATION casa_sanbao;
    UPDATE trasi.proposta SET stato = 'applicata' WHERE id = v_id;
    GET DIAGNOSTICS v_n = ROW_COUNT;
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code IS NULL AND v_n = 0,
    format('client su proposta→applicata → 0 righe (errore=%s, righe=%s)',
           COALESCE(v_code, 'no'), COALESCE(v_n::text, 'n/a')));

  -- 7.2 Proposta scaduta: approvarla e' vietato.
  SET SESSION AUTHORIZATION casa_sanbao;
  INSERT INTO trasi.proposta (origine, tipo, entita, casa_id, payload, motivazione, scade_il)
  VALUES ('chat', 'chiudi_luogo', 'luogo', c.id_sanbao, '{}'::jsonb, 'ZS scaduta', current_date - 5)
  RETURNING id INTO v_id;
  RESET SESSION AUTHORIZATION;

  v_code := NULL;
  BEGIN
    SET SESSION AUTHORIZATION rete;
    UPDATE trasi.proposta SET stato = 'approvata' WHERE id = v_id;
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code = 'P0001',
    format('approvazione di proposta scaduta → P0001 (ottenuto: %s)', COALESCE(v_code, 'NESSUN ERRORE: approvata')));

  -- 7.3 `scadi_proposte()` la marca `scaduta`, con audit, ed e' idempotente.
  SET SESSION AUTHORIZATION automazioni;
  SELECT trasi.scadi_proposte() INTO v_scad;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_scad >= 1,
    format('scadi_proposte() → %s proposte marcate (atteso >=1)', v_scad));

  SELECT stato INTO v_stato FROM trasi.proposta WHERE id = v_id;
  PERFORM pg_temp.zs_ok(v_stato = 'scaduta',
    format('proposta con scade_il passato → stato=%s (atteso scaduta)', COALESCE(v_stato, '∅')));

  PERFORM pg_temp.zs_ok(
    (SELECT count(*) FROM trasi.audit
      WHERE proposta_id = v_id AND azione = 'transizione' AND dopo->>'stato' = 'scaduta') = 1,
    'audit: la scadenza e'' tracciata (1 riga `transizione` → scaduta)');

  SET SESSION AUTHORIZATION automazioni;
  SELECT trasi.scadi_proposte() INTO v_scad;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_scad = 0,
    format('scadi_proposte() 2ª run → %s (atteso 0: idempotente)', v_scad));
END
$s7$;

-- ---------------------------------------------------------------------------
-- §8 — Coda `v_da_approvare`: filtro per ruolo, V4 regola 1, minimizzazione
-- ---------------------------------------------------------------------------
DO $s8$
DECLARE c zs_ctx; v_n int;
BEGIN
  RAISE NOTICE '=== §8 coda v_da_approvare ===';
  SELECT * INTO c FROM zs_ctx;

  SET SESSION AUTHORIZATION casa_sanbao;
  INSERT INTO trasi.proposta (origine, tipo, entita, entita_id, casa_id, payload, motivazione)
  VALUES ('coerenza', 'modifica_orari_casa', 'casa', c.id_sanbao, c.id_sanbao,
          jsonb_build_object('orari_provvisori', true), 'ZS coda gestore');
  RESET SESSION AUTHORIZATION;

  SET SESSION AUTHORIZATION casa_sanbao;
  SELECT count(*) INTO v_n FROM trasi.v_da_approvare WHERE motivazione LIKE 'ZS coda gestore%';
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_n = 0,
    format('coda: la proposta l''ha creata casa_sanbao stessa e non e'' decidibile (V4 regola 1) → %s righe (atteso 0)', v_n));

  -- La stessa proposta e' invece visibile al gestore di un'ALTRA Casa dello
  -- stesso ruolo? No: il filtro e' la propria Casa. La si crea da `rete`.
  SET SESSION AUTHORIZATION rete;
  INSERT INTO trasi.proposta (origine, tipo, entita, entita_id, casa_id, payload, motivazione)
  VALUES ('manuale', 'modifica_orari_casa', 'casa', c.id_sanbao, c.id_sanbao,
          jsonb_build_object('orari_provvisori', true), 'ZS coda visibile');
  RESET SESSION AUTHORIZATION;

  SET SESSION AUTHORIZATION casa_sanbao;
  SELECT count(*) INTO v_n FROM trasi.v_da_approvare WHERE motivazione LIKE 'ZS coda visibile%';
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_n = 1,
    format('coda per il gestore: vede la proposta `gestore` non propria della propria Casa → %s riga (atteso 1)', v_n));

  -- Minimizzazione (V5/§12): `proposto_da` non esce dalla coda.
  PERFORM pg_temp.zs_ok(
    NOT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_schema = 'trasi' AND table_name = 'v_da_approvare'
                   AND column_name IN ('proposto_da', 'approvato_da')),
    'v_da_approvare non espone proposto_da/approvato_da (V5)');
  PERFORM pg_temp.zs_ok(
    EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema = 'trasi' AND table_name = 'v_da_approvare' AND column_name = 'diff_leggibile'),
    'v_da_approvare espone diff_leggibile (si approva leggendo)');

  -- Una proposta `at` e' visibile a `rete` (coda del territorio), non al gestore.
  SET SESSION AUTHORIZATION casa_bozzano;
  INSERT INTO trasi.proposta (origine, tipo, entita, entita_id, casa_id, payload, motivazione)
  VALUES ('fonte_automatica', 'chiudi_luogo', 'luogo', 2147483000, c.id_bozzano, '{}'::jsonb, 'ZS coda territorio');
  RESET SESSION AUTHORIZATION;

  SET SESSION AUTHORIZATION rete;
  SELECT count(*) INTO v_n FROM trasi.v_da_approvare WHERE motivazione LIKE 'ZS coda territorio%';
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_n = 1,
    format('coda per AT (rete): vede la proposta `at` del territorio → %s riga (atteso 1)', v_n));

  SET SESSION AUTHORIZATION casa_sanbao;
  SELECT count(*) INTO v_n FROM trasi.v_da_approvare WHERE motivazione LIKE 'ZS coda territorio%';
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_n = 0,
    format('coda per il gestore di San Bao: NON vede la proposta `at` di Bozzano → %s righe (atteso 0)', v_n));
END
$s8$;

-- ---------------------------------------------------------------------------
-- §9 — `audit` append-only (regola 5): nessun UPDATE/DELETE a nessuno
-- ---------------------------------------------------------------------------
DO $s9$
DECLARE v_code text;
BEGIN
  RAISE NOTICE '=== §9 audit append-only ===';

  v_code := NULL;
  BEGIN
    SET SESSION AUTHORIZATION applicatore;
    UPDATE trasi.audit SET azione = 'riscritta' WHERE id > 0;
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code = '42501',
    format('audit: UPDATE da `applicatore` → 42501 (ottenuto: %s)', COALESCE(v_code, 'NESSUN ERRORE: audit riscritto')));

  v_code := NULL;
  BEGIN
    SET SESSION AUTHORIZATION applicatore;
    DELETE FROM trasi.audit WHERE id > 0;
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code = '42501',
    format('audit: DELETE da `applicatore` → 42501 (ottenuto: %s)', COALESCE(v_code, 'NESSUN ERRORE: audit cancellato')));

  v_code := NULL;
  BEGIN
    SET SESSION AUTHORIZATION casa_sanbao;
    DELETE FROM trasi.audit WHERE id > 0;
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code = '42501',
    format('audit: DELETE da un ruolo Casa → 42501 (ottenuto: %s)', COALESCE(v_code, 'NESSUN ERRORE: audit cancellato')));

  -- L'audit resta leggibile (trasparenza interna, §12).
  PERFORM pg_temp.zs_ok((SELECT count(*) FROM trasi.audit) > 0,
    format('audit leggibile: %s righe', (SELECT count(*) FROM trasi.audit)));
END
$s9$;

-- ---------------------------------------------------------------------------
-- §10 — Mai DELETE sul dominio (regola 7); `chiudi_luogo` e' soft-close
-- ---------------------------------------------------------------------------
DO $s10$
DECLARE c zs_ctx; v_code text; v_n bigint;
BEGIN
  RAISE NOTICE '=== §10 nessuna DELETE sul dominio ===';
  SELECT * INTO c FROM zs_ctx;

  v_code := NULL;
  BEGIN
    SET SESSION AUTHORIZATION casa_sanbao;
    DELETE FROM trasi.scheda_servizio WHERE casa_id = c.id_sanbao;
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code = '42501',
    format('ruolo Casa DELETE scheda_servizio → 42501 (V4 regola 7) (ottenuto: %s)',
           COALESCE(v_code, 'NESSUN ERRORE: cancellazione riuscita')));

  v_code := NULL;
  BEGIN
    SET SESSION AUTHORIZATION automazioni;
    DELETE FROM trasi.luogo WHERE nome LIKE 'ZS luogo applicato%';
  EXCEPTION WHEN OTHERS THEN v_code := SQLSTATE; END;
  RESET SESSION AUTHORIZATION;
  PERFORM pg_temp.zs_ok(v_code = '42501',
    format('automazioni DELETE luogo → 42501 (ottenuto: %s)', COALESCE(v_code, 'NESSUN ERRORE: luogo cancellato')));

  -- Chiusura mediata: `chiudi_luogo` → soft-close, il luogo resta.
  DECLARE v_id bigint; v_chiudi int; v_chiuso date;
  BEGIN
    SELECT id INTO v_chiudi FROM trasi.luogo WHERE nome = 'ZS luogo applicato 1';
    SET SESSION AUTHORIZATION casa_sanbao;
    INSERT INTO trasi.proposta (origine, tipo, entita, entita_id, casa_id, payload, motivazione)
    VALUES ('chat', 'chiudi_luogo', 'luogo', v_chiudi, c.id_sanbao,
            jsonb_build_object('chiuso_il', current_date::text), 'ZS chiusura mediata')
    RETURNING id INTO v_id;
    RESET SESSION AUTHORIZATION;

    SET SESSION AUTHORIZATION rete;
    UPDATE trasi.proposta SET stato = 'approvata' WHERE id = v_id;
    RESET SESSION AUTHORIZATION;

    SET SESSION AUTHORIZATION automazioni;
    PERFORM count(*) FROM trasi.applica_proposte_approvate(10);
    RESET SESSION AUTHORIZATION;

    SELECT chiuso_il INTO v_chiuso FROM trasi.luogo WHERE id = v_chiudi;
    PERFORM pg_temp.zs_ok(v_chiuso IS NOT NULL AND EXISTS (SELECT 1 FROM trasi.luogo WHERE id = v_chiudi),
      format('chiudi_luogo: soft-close (chiuso_il=%s), la riga esiste ancora', COALESCE(v_chiuso::text, '∅')));
  END;
END
$s10$;

-- ---------------------------------------------------------------------------
-- §11 — Riepilogo e contabilita' finale (B1-PRP-06)
-- ---------------------------------------------------------------------------
DO $s11$
DECLARE v_n int;
BEGIN
  RAISE NOTICE '=== §11 riepilogo ===';

  -- Le mutazioni di dominio introdotte da questo test devono essere tutte
  -- contabilizzate (percorso mediato → `applicata`, eccezione iCal →
  -- `ical_upsert`) o dichiarate (fixture = caricamento iniziale di `trasi_owner`).
  -- Il filtro temporale e' quello del criterio B1-PRP-06
  -- (`SELECT count(*) ... WHERE ts > :t0`): isola cio' che ha prodotto questa
  -- batteria da eventuale pregresso del database.
  SELECT count(*) INTO v_n FROM trasi.v_scritture_senza_audit WHERE ts > pg_temp.zs_t0();
  PERFORM pg_temp.zs_ok(v_n = 0,
    format('v_scritture_senza_audit (ts > inizio batteria): %s righe (atteso 0: ogni scrittura e'' contabilizzata o dichiarata)', v_n));

  SELECT count(*) INTO v_n
    FROM trasi.proposta p
   WHERE p.stato = 'applicata'
     AND NOT EXISTS (SELECT 1 FROM trasi.audit a WHERE a.proposta_id = p.id AND a.azione = 'applicata');
  PERFORM pg_temp.zs_ok(v_n = 0,
    format('ogni proposta `applicata` ha la sua riga di audit (orfane: %s)', v_n));

  -- Regressione: una proposta `approvata` ma SCADUTA non deve essere applicata.
  -- Bug trovato il 2026-09-16: `applica` filtrava solo su `stato='approvata'` senza
  -- guardare `scade_il`. Il trigger impedisce di approvare dopo la scadenza, ma non
  -- copre la scadenza che arriva DOPO l'approvazione — e la finestra è reale, perché
  -- `applica` (05:00) gira prima di `scadi`: tra mezzanotte e le 05:00 una proposta
  -- scaduta restava `approvata` e veniva applicata. Questo test la blocca.
  DECLARE
    v_scaduta_id bigint;
    v_stato      text;
    v_creata     int;
  BEGIN
    INSERT INTO trasi.proposta (origine, tipo, entita, casa_id, payload, motivazione,
                                stato, approvato_da, approvato_ts, scade_il, proposto_da)
    VALUES ('manuale', 'nuova_scheda', 'scheda_servizio', 5, '{"titolo":"__zs_scaduta"}'::jsonb,
            'test regressione scadenza', 'approvata', 'rete', now(), current_date - 1, 'rete@trasi.local')
    RETURNING id INTO v_scaduta_id;

    -- Si esegue l'applicazione e si guarda QUELLA proposta, non il totale delle
    -- applicate: la funzione processa tutte le proposte approvate del database, e
    -- le fixture di questa stessa batteria ne lasciano alcune. Un assert sul totale
    -- misurerebbe le altre, non la scaduta che vogliamo bloccare.
    PERFORM trasi.applica_proposte_approvate(200);

    SELECT p.stato INTO v_stato FROM trasi.proposta p WHERE p.id = v_scaduta_id;
    PERFORM pg_temp.zs_ok(v_stato = 'approvata',
      format('proposta scaduta NON applicata (stato: %s, atteso approvata)', v_stato));

    SELECT count(*) INTO v_creata FROM trasi.scheda_servizio WHERE titolo = '__zs_scaduta';
    PERFORM pg_temp.zs_ok(v_creata = 0,
      format('proposta scaduta: nessuna riga creata nel dominio (%s)', v_creata));

    -- Pulizia: l'`audit` referenzia la proposta (FK), quindi va rimosso prima.
    -- Nota: l'intera batteria gira in una transazione con ROLLBACK finale, quindi
    -- questa riga non persiste comunque; serve a non lasciare il riferimento
    -- pendente qualora il blocco venga eseguito fuori da quella transazione.
    DELETE FROM trasi.audit WHERE proposta_id = v_scaduta_id;
    DELETE FROM trasi.proposta WHERE id = v_scaduta_id;
  END;

  RAISE NOTICE '### TEST ZERO SCRITTURE: TUTTI I CONTROLLI PASS ###';
END
$s11$;

ROLLBACK;
