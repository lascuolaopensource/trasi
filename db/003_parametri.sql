-- Trasi — db/003_parametri.sql
-- I 10 parametri [P] (architettura §7.2) e gli accessori p_int/p_text/p_bool.
--
-- Regola: le funzioni ritornano NULL se la chiave non esiste — nessuna eccezione. Un parametro mancante
-- non deve far cadere una query (Metabase, shim, flussi); chi legge decide il default.
-- Chi modifica: solo `ti` (matrice 002); qui si riafferma il valore iniziale solo se la riga non esiste,
-- così un valore cambiato da `ti` sopravvive alla riesecuzione (idempotenza che non cancella il lavoro umano).
\set ON_ERROR_STOP on
\set VERBOSITY terse

SET ROLE trasi_owner;
SET search_path = trasi, public, pg_temp;

CREATE OR REPLACE FUNCTION trasi.p_int(p_chiave text) RETURNS integer
LANGUAGE sql STABLE SET search_path = '' AS $$
  SELECT CASE WHEN p.valore ~ '^-?[0-9]+$' THEN p.valore::integer END
  FROM trasi.parametro p WHERE p.chiave = p_chiave
$$;

CREATE OR REPLACE FUNCTION trasi.p_text(p_chiave text) RETURNS text
LANGUAGE sql STABLE SET search_path = '' AS $$
  SELECT p.valore FROM trasi.parametro p WHERE p.chiave = p_chiave
$$;

CREATE OR REPLACE FUNCTION trasi.p_bool(p_chiave text) RETURNS boolean
LANGUAGE sql STABLE SET search_path = '' AS $$
  SELECT CASE lower(p.valore) WHEN 'true' THEN true WHEN 'false' THEN false
                              WHEN 't' THEN true WHEN 'f' THEN false
                              WHEN 'on' THEN true WHEN 'off' THEN false
                              WHEN '1' THEN true WHEN '0' THEN false END
  FROM trasi.parametro p WHERE p.chiave = p_chiave
$$;

INSERT INTO trasi.parametro (chiave, valore, tipo, descrizione) VALUES
  ('raggio_vicinanza_m',      '800',  'int',  'Raggio di vicinanza in metri quando casa.raggio_m è NULL (Tuturano: 2000 in seed).'),
  ('gg_scadenza_proposta',    '30',   'int',  'Giorni di validità di una proposta: oltre → scaduta + alert.'),
  ('fiducia_min_esterna',     '2',    'int',  'Sotto questa soglia la fonte esterna non viene usata (badge scartata_fiducia).'),
  ('max_risultati_esterni',   '5',    'int',  'Tetto di risultati esterni per risposta.'),
  ('gg_validazione_comune',   '7',    'int',  'Giorni di validità provvisoria di un dato del Comune senza referente.'),
  ('gg_escalation_pm',        '14',   'int',  'Giorni oltre i quali la proposta non trattata sale al PM.'),
  ('gg_preavviso_scadenza',   '15',   'int',  'Preavviso, in giorni, per le scadenze (bandi, opportunità).'),
  ('k_anonimato',             '5',    'int',  'Soglia di k-anonimato: sotto questa soglia n è NULL e n_label = ''<5''.'),
  ('gg_retention_chat',       '30',   'int',  'Retention delle chat Onyx: solo la proposta persiste oltre.'),
  ('giorno_ciclo_mensile',    '3',    'int',  'Giorno del mese del ciclo mensile (digest, report PN, CSV).')
ON CONFLICT (chiave) DO NOTHING;

RESET ROLE;
