-- Trasi — db/000_roles.sql
-- Ruoli applicativi, schema dedicato `trasi`, membership. Idempotente e convergente:
-- rieseguirlo riporta ruoli e schema allo stato dichiarato anche se qualcuno li ha alterati.
--
-- Invarianti (plan.md B1-DAT-01, architettura §11):
--   * nessun ruolo con SUPERUSER / BYPASSRLS (la RLS è l'autorità);
--   * `shim_rw` NOINHERIT e LOGIN: i privilegi si prendono solo con SET LOCAL ROLE (una richiesta = un ruolo Casa);
--   * `trasi_owner` e `applicatore` NOLOGIN: non sono identità applicative;
--   * schema dedicato `trasi` (PG16 nega CREATE su `public` a un owner non-superuser).
--
-- Eseguito come utente amministratore del container (postgres): CREATE ROLE e GRANT <ruolo> TO <ruolo>
-- richiedono CREATEROLE/ADMIN e non possono girare come trasi_owner.
-- La password di shim_rw arriva da deployment/.env via apply.sh (-v shim_pw=…): non è mai stampata.
\set ON_ERROR_STOP on
\set VERBOSITY terse

-- 1) Ruoli -------------------------------------------------------------------
DO $$
DECLARE
  -- nome, LOGIN, INHERIT
  spec text[][] := ARRAY[
    ['trasi_owner',      'false', 'true' ],
    ['applicatore',      'false', 'true' ],
    ['shim_rw',          'true',  'false'],
    ['rete',             'true',  'true' ],
    ['ti',               'true',  'true' ],
    ['metabase_ro',      'true',  'true' ],
    ['automazioni',      'true',  'true' ],
    ['casa_santaspazio', 'true',  'true' ],
    ['casa_molo12',      'true',  'true' ],
    ['casa_erranti',     'true',  'true' ],
    ['casa_buscicchio',  'true',  'true' ],
    ['casa_sanbao',      'true',  'true' ],
    ['casa_minimus',     'true',  'true' ],
    ['casa_pop',         'true',  'true' ],
    ['casa_bozzano',     'true',  'true' ],
    ['casa_dream',       'true',  'true' ],
    ['casa_tuturano',    'true',  'true' ]
  ];
  r text[];
  attrs text;
BEGIN
  FOREACH r SLICE 1 IN ARRAY spec LOOP
    attrs := format('%s %s NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS',
                    CASE r[2] WHEN 'true' THEN 'LOGIN' ELSE 'NOLOGIN' END,
                    CASE r[3] WHEN 'true' THEN 'INHERIT' ELSE 'NOINHERIT' END);
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r[1]) THEN
      EXECUTE format('CREATE ROLE %I %s', r[1], attrs);
    ELSE
      -- convergenza: gli attributi sono riaffermati a ogni esecuzione
      EXECUTE format('ALTER ROLE %I %s', r[1], attrs);
    END IF;
  END LOOP;
END $$;

-- 2) Schema dedicato ---------------------------------------------------------
-- Dopo i ruoli: `trasi_owner` deve esistere per esserne il proprietario.
CREATE SCHEMA IF NOT EXISTS trasi AUTHORIZATION trasi_owner;
ALTER SCHEMA trasi OWNER TO trasi_owner;
REVOKE ALL ON SCHEMA trasi FROM PUBLIC;

-- 3) shim_rw: membro delle 10 Case e di `rete`, NON di `ti` -------------------
-- Le membership non danno privilegi (NOINHERIT): servono solo a poter fare SET LOCAL ROLE.
GRANT casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
      casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano,
      rete
  TO shim_rw;
REVOKE ti FROM shim_rw;

-- 3b) `automazioni`: membro di `rete` (NOINHERIT non serve a nulla qui: INHERIT=true — la membership
-- serve allo stesso fine di `shim_rw`, cioè il `SET LOCAL ROLE` per **leggere** i report che ha scritto:
-- la policy `rep_sel` di db/024 ammette `rete`, non `automazioni`; misurato il 17/09/2026: il ciclo
-- mensile contava zero righe anche a INSERT riusciti).
GRANT rete TO automazioni;

-- 4) Privilegi di schema -----------------------------------------------------
-- USAGE: tutti i ruoli client devono poter nominare gli oggetti dello schema.
GRANT USAGE ON SCHEMA trasi TO
  casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
  casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano,
  rete, ti, metabase_ro, automazioni, shim_rw, applicatore;
-- CREATE: `applicatore` è owner delle funzioni SECURITY DEFINER di db/005+db/006 (F9): PostgreSQL
-- richiede il CREATE sullo schema al nuovo owner di un oggetto.
GRANT CREATE ON SCHEMA trasi TO applicatore;

-- 5) Password di shim_rw -----------------------------------------------------
-- Unico ruolo applicativo che si connette col DATABASE_URL dello shim (rete Docker → scram-sha-256):
-- senza password il B3 non autentica. Gli altri ruoli LOGIN ricevono la password al provisioning
-- di NocoDB/Metabase (fuori perimetro B1, vedi report).
\if :{?shim_pw}
ALTER ROLE shim_rw WITH LOGIN PASSWORD :'shim_pw';
\else
\echo '000_roles: shim_pw non fornito — shim_rw resta senza password (apply.sh la passa da deployment/.env)'
\endif
