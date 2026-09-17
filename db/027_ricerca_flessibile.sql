-- Trasi — db/027_ricerca_flessibile.sql
-- La ricerca dell'attrezzoteca deve disambiguare: l'operatore scrive «seggiole» e l'oggetto si chiama
-- «sedie impilabili» — l'ILIKE secco non basta. Tre pezzi:
--   1. `sinonimo_ricerca` — tabella-configurazione (come `fonte`): il TI la estende senza deploy.
--      Ogni riga: termine → elenco di varianti da cercare. No RLS: è configurazione, non memoria.
--   2. `termine_espanso(p_q)` — normalizza il termine (lower + unaccent), lo cerca nella tabella
--      (come termine o dentro un gruppo di varianti), altrimenti prova la prima parola, e in ultima
--      istanza restituisce il termine così com'è. Tutti i riferimenti qualificati (`public.unaccent`,
--      `trasi.sinonimo_ricerca`): la sessione dello shim gira con search_path ridotto (SET LOCAL ROLE
--      e search_path di default vuoto), e un nome non qualificato non si risolve (misurato).
--   3. estensioni `pg_trgm` e `unaccent` (CREATE EXTENSION: girano da superuser via apply.sh).
-- La query di ricerca (shim, scritture.attrezzoteca e attrezzoteca.op_attrezzoteca) fa
-- `CROSS JOIN LATERAL unnest(trasi.termine_espanso($1))` e cerca ogni variante su nome,
-- descrizione e Casa.
\set ON_ERROR_STOP on
\set VERBOSITY terse

-- Le estensioni vogliono il superuser: apply.sh esegue come amministratore (vedi apply.sh §psql_owner).
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS unaccent;

SET ROLE trasi_owner;
SET search_path = trasi, public, pg_temp;

CREATE TABLE IF NOT EXISTS trasi.sinonimo_ricerca (
  termine text PRIMARY KEY,
  espandi_a text[] NOT NULL,
  aggiornato_ts timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE trasi.sinonimo_ricerca IS
  'Sinonimi della ricerca attrezzoteca (US-5.1): termine → varianti da cercare. Configurazione, non memoria: il TI la estende con una riga, senza deploy (come `fonte`).';

INSERT INTO trasi.sinonimo_ricerca (termine, espandi_a) VALUES
  ('sedia', ARRAY['sedia','sedie','segg','seggiola','seggiole','seduta','sedute']),
  ('seggiola', ARRAY['sedia','sedie','segg','seggiola','seggiole']),
  ('tavolo', ARRAY['tavolo','tavoli','tavolino','tavolini','banco','banchi']),
  ('proiettore', ARRAY['proiettore','proiettori','videoproiettore','videoproiettori','beamer']),
  ('microfono', ARRAY['microfono','microfoni','mic','mics','radio mic']),
  ('gazebo', ARRAY['gazebo','padiglione','padiglioni','tensostruttura','chiosco']),
  ('tenda', ARRAY['tenda','tende','tenda pieghevole','tende pieghevoli','tettoia']),
  ('cassa', ARRAY['cassa','casse','casse audio','diffusore','diffusori','impianto audio','cassa amplificata']),
  ('estensione', ARRAY['estensione','estensioni','ciabatta','ciabatte','multipresa','presa elettrica','prolunga'])
ON CONFLICT (termine) DO UPDATE SET espandi_a = EXCLUDED.espandi_a, aggiornato_ts = now();

GRANT SELECT ON trasi.sinonimo_ricerca TO shim_rw, applicatore, automazioni,
  casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
  casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano;

CREATE OR REPLACE FUNCTION trasi.termine_espanso(p_q text)
RETURNS text[] LANGUAGE plpgsql STABLE SET search_path = pg_catalog, trasi, public, pg_temp AS $fn$
DECLARE
  v_norm   text := lower(btrim(public.unaccent(COALESCE(p_q,''))));
  v_parola text;
  v_esp    text[] := ARRAY[]::text[];
BEGIN
  IF v_norm = '' THEN RETURN ARRAY[]::text[]; END IF;
  -- il termine intero può essere un sinonimo registrato (es. «seggiole»)
  SELECT COALESCE(s.espandi_a, ARRAY[v_norm]) INTO v_esp
    FROM trasi.sinonimo_ricerca s
   WHERE s.termine = v_norm OR v_norm = ANY (s.espandi_a)
   LIMIT 1;
  IF v_esp IS NULL OR array_length(v_esp, 1) IS NULL THEN
    -- niente sinonimo: prova la prima parola (l'operatore scrive «sedie impilabili da 40»)
    v_parola := btrim(split_part(v_norm, ' ', 1));
    SELECT COALESCE(s.espandi_a, ARRAY[v_parola]) INTO v_esp
      FROM trasi.sinonimo_ricerca s
     WHERE s.termine = v_parola OR v_parola = ANY (s.espandi_a)
     LIMIT 1;
  END IF;
  IF v_esp IS NULL OR array_length(v_esp, 1) IS NULL THEN
    v_esp := ARRAY[v_norm];
  END IF;
  RETURN v_esp;
END;
$fn$;
-- L'owner si impone solo se serve: il secondo apply non deve fallire (vedi 026 §4).
-- Il DO gira da superuser (RESET ROLE): trasi_owner non può cedere la proprietà (misurato in 026).
RESET ROLE;
DO $owner$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT p.oid::regprocedure::text AS firma
      FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
     WHERE n.nspname = 'trasi'
       AND p.proname = 'termine_espanso'
       AND pg_get_userbyid(p.proowner) <> 'applicatore'
  LOOP
    EXECUTE format('ALTER FUNCTION %s OWNER TO applicatore', r.firma);
  END LOOP;
END
$owner$;
GRANT EXECUTE ON FUNCTION trasi.termine_espanso(text) TO PUBLIC;

DO $verify$
BEGIN
  IF (SELECT count(*) FROM trasi.sinonimo_ricerca) < 5 THEN
    RAISE EXCEPTION '027: sinonimi di ricerca mancanti';
  END IF;
  RAISE NOTICE '027_ricerca_flessibile applicato: sinonimo_ricerca + termine_espanso (unaccent + sinonimi, estendibile dal TI)';
END
$verify$;
