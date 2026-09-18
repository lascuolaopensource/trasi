-- Trasi — db/032_attrezzoteca_diretta.sql
-- L'oggetto dell'attrezzoteca entra nel perimetro della **scrittura diretta della propria Casa** (D1).
--
-- Decisione (2026-09-18, coerente con S2 «opzione A» e con la specifica del gruppo Processi
-- 2026-09-17 «ogni casa/ente può modificare i propri dati»): con un solo accesso per Casa la
-- cerimonia proposta → approvazione **non ha un secondo umano** — è lo stesso argomento di
-- `salva_dato` per scheda/opportunità/casa/persona (shim, `DETAIL_USA_SCRITTURA_DIRETTA`). Fino a qui
-- `oggetto` aveva le policy `ogg_ins_casa`/`ogg_upd_casa` (db/014 §3) **senza** il GRANT: la porta era
-- disegnata e murata. Questo file toglie il muro e lascia la porta com'è: la RLS resta l'autorità
-- (`casa_id = casa_corrente()` in USING **e** WITH CHECK).
--
-- Cosa cambia e cosa no:
--   * GRANT INSERT, UPDATE su `trasi.oggetto` ai dieci ruoli Casa (+ USAGE sulla sequenza);
--   * **nessun DELETE** (V4 regola 7): il ritiro è `attivo = false`;
--   * i tipi di proposta `nuovo_oggetto`/`modifica_oggetto`/`ritira_oggetto` (db/006) **restano**, per il
--     caso cross-Casa deciso dall'AT — non si rimuovono;
--   * `v_scritture_senza_audit` (db/006 §9) già esclude le scritture dirette del ruolo della propria Casa
--     (`m.da = 'casa_' || replace(slug,'-','')`): non si tocca, e dopo questo file una scrittura di
--     `casa_sanbao` su un oggetto di San Bao **non** compare come violazione;
--   * il trigger `scrittura_00_ts` è già su `oggetto` (db/014 §2): l'impronta c'è.
--
-- Idempotente; SET ROLE trasi_owner; db/000–029 sono congelati, per questo il file è nuovo.
\set ON_ERROR_STOP on
\set VERBOSITY terse

SET ROLE trasi_owner;
SET search_path = trasi, public, pg_temp;

-- Precondizioni (errore parlante se l'ordine di apply non è rispettato).
DO $pre$
BEGIN
  IF to_regclass('trasi.oggetto') IS NULL THEN
    RAISE EXCEPTION '032_attrezzoteca_diretta: manca trasi.oggetto — applica prima db/014_attrezzoteca.sql';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE schemaname = 'trasi' AND tablename = 'oggetto'
                    AND policyname IN ('ogg_ins_casa', 'ogg_upd_casa')) THEN
    RAISE EXCEPTION '032_attrezzoteca_diretta: mancano le policy ogg_ins_casa/ogg_upd_casa (db/014 §3): il GRANT senza policy aprirebbe la tabella';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid = 'trasi.oggetto'::regclass
                    AND NOT tgisinternal AND tgname = 'scrittura_00_ts') THEN
    RAISE EXCEPTION '032_attrezzoteca_diretta: manca scrittura_00_ts su oggetto (db/014 §2): una scrittura senza impronta non è contabilizzabile';
  END IF;
END
$pre$;

-- ---------------------------------------------------------------------------
-- 1. GRANT: la porta che db/014 aveva disegnato (policy) ma murato (nessun privilegio)
-- ---------------------------------------------------------------------------
GRANT INSERT, UPDATE ON trasi.oggetto
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano;

-- Senza USAGE sulla sequenza l'INSERT serial fallisce con 42501 (stesso motivo di db/014 §4).
GRANT USAGE ON SEQUENCE trasi.oggetto_id_seq
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano;

-- Nessun DELETE, deliberatamente: un oggetto si ritira (attivo=false), non si cancella.
REVOKE DELETE ON trasi.oggetto
  FROM casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
       casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano, rete, shim_rw;

-- ---------------------------------------------------------------------------
-- 2. Il perimetro dichiarato dove lo si legge: il commento della tabella
-- ---------------------------------------------------------------------------
COMMENT ON TABLE trasi.oggetto IS
  'Attrezzoteca: inventario condiviso (US-5.1). Nascita e modifica DIRETTE della propria Casa (D1, db/032: RLS casa_id = casa_corrente()); via proposta (nuovo_oggetto/modifica_oggetto/ritira_oggetto, decide l''AT) per gli oggetti delle altre Case. SELECT a tutta la rete. attivo=false = ritirato (mai DELETE, V4 regola 7).';

-- ---------------------------------------------------------------------------
-- 3. Verifica di installazione
-- ---------------------------------------------------------------------------
DO $verify$
DECLARE
  v_ruolo text;
  v_manca text;
BEGIN
  FOREACH v_ruolo IN ARRAY ARRAY['casa_santaspazio','casa_molo12','casa_erranti','casa_buscicchio','casa_sanbao',
                                 'casa_minimus','casa_pop','casa_bozzano','casa_dream','casa_tuturano'] LOOP
    IF NOT has_table_privilege(v_ruolo, 'trasi.oggetto', 'INSERT')
       OR NOT has_table_privilege(v_ruolo, 'trasi.oggetto', 'UPDATE') THEN
      v_manca := concat_ws(', ', v_manca, v_ruolo);
    END IF;
    IF has_table_privilege(v_ruolo, 'trasi.oggetto', 'DELETE') THEN
      RAISE EXCEPTION '032_attrezzoteca_diretta: % ha DELETE su oggetto — il ritiro è attivo=false (V4 regola 7)', v_ruolo;
    END IF;
  END LOOP;
  IF v_manca IS NOT NULL THEN
    RAISE EXCEPTION '032_attrezzoteca_diretta: GRANT INSERT/UPDATE mancante per %', v_manca;
  END IF;
  IF has_table_privilege('rete', 'trasi.oggetto', 'INSERT') OR has_table_privilege('shim_rw', 'trasi.oggetto', 'INSERT') THEN
    RAISE EXCEPTION '032_attrezzoteca_diretta: rete/shim_rw non devono scrivere oggetto (solo i ruoli Casa, per la propria)';
  END IF;
  RAISE NOTICE '032_attrezzoteca_diretta applicato: INSERT/UPDATE su oggetto ai dieci ruoli Casa (RLS casa_id = casa_corrente()), nessun DELETE, proposte *_oggetto conservate per il cross-Casa';
END
$verify$;

RESET ROLE;
