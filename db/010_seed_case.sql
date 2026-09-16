-- Trasi — db/010_seed_case.sql
-- Caricamento iniziale: 10 Case (§2.1), mappa ruolo→Casa (12 righe), identità Onyx (22 righe).
--
-- Eseguito come `trasi_owner`: è il caricamento iniziale, non una scrittura a runtime. Da qui in poi
-- ogni modifica a una Casa passa da proposta → approvazione → applica_proposte (§11).
-- Idempotente per NON riscrittura: ON CONFLICT DO NOTHING sulle Case (così una modifica già approvata
-- a valle non viene riportata indietro da una riesecuzione), DO UPDATE sulla configurazione
-- (ruolo_casa, identita_onyx), che è dato di governance e non memoria applicativa.
--
-- [ASSUNZIONE] Coordinate: il piano fornisce 7 punti verificati (Nominatim). Le 3 Case senza riscontro
-- civico — Tuturano (obbligatorio, §7) e i due punti del centro storico non coperti dai 7 — sono
-- marcate geom_qualita='stimata'. Orari: dedotti dal foglio [F] dove noto (§2.1), altrimenti
-- [ASSUNZIONE] su orari plausibili; Tuturano senza orari (orari_provvisori=true, da_validare=true).
\set ON_ERROR_STOP on
\set VERBOSITY terse

SET ROLE trasi_owner;
SET search_path = trasi, public, pg_temp;

-- ===========================================================================
-- 1. Le 10 Case di Quartiere (§2.1)
-- ===========================================================================
INSERT INTO trasi.casa
  (slug, nome, zona, ente_gestore, orari, orari_eccezioni, orari_provvisori, raggio_m, geom, geom_qualita,
   email_digest, da_validare, persone_target, competenze, note)
VALUES
  -- Centro Storico — coordinate verificate (Piazza Duomo, 40.64036/17.94518)
  ('santa-spazio', 'Santa Spazio Culturale', 'Centro Storico', 'YEAHJASì aps',
   '{"lun":["09:30","13:00","16:00","19:00"],"mar":["09:30","13:00","16:00","19:00"],
     "mer":["09:30","13:00","16:00","19:00"],"gio":["09:30","13:00","16:00","19:00"],
     "ven":["09:30","13:00","16:00","19:00"],"sab":["10:00","13:00"],"dom":[]}'::jsonb,
   NULL, false, NULL, ST_SetSRID(ST_MakePoint(17.94518, 40.64036), 4326)::geography, 'verificata',
   NULL, false, ARRAY['giovani','NEET'], ARRAY['biblioteca','musica','aggregazione'],
   'Vocazione: biblioteca, musica, giovani, NEET (foglio [F]).'),

  -- Centro Storico — punto portuale non coperto dai 7 verificati → stimata
  ('molo12', 'Molo 12', 'Centro Storico', 'ATS The Qube',
   '{"lun":["09:00","18:00"],"mar":["09:00","18:00"],"mer":["09:00","18:00"],
     "gio":["09:00","18:00"],"ven":["09:00","18:00"],"sab":[],"dom":[]}'::jsonb,
   NULL, false, NULL, ST_SetSRID(ST_MakePoint(17.94610, 40.64370), 4326)::geography, 'stimata',
   NULL, false, ARRAY['imprese','professionisti'], ARRAY['coworking','impresa'],
   'lun–ven 9-18 (foglio [F]). Coordinate [ASSUNZIONE]: stimata.'),

  -- Centro Storico — orari stagionali in orari_eccezioni (§2.1)
  ('erranti', 'Accademia degli Erranti', 'Centro Storico', 'Brindisi e le Antiche Strade',
   '{"lun":[],"mar":["10:00","12:00","17:20","20:00"],"mer":["10:00","12:00","17:20","20:00"],
     "gio":["10:00","12:00","17:20","20:00"],"ven":["10:00","12:00","17:20","20:00"],
     "sab":["10:00","12:00","17:20","20:00"],"dom":[]}'::jsonb,
   '[{"tipo":"stagionale","dal":"2026-06-01","al":"2026-09-30",
      "orari":{"mar":["10:00","12:00","17:20","20:00"],"mer":["10:00","12:00","17:20","20:00"],
               "gio":["10:00","12:00","17:20","20:00"],"ven":["10:00","12:00","17:20","20:00"],
               "sab":["10:00","12:00","17:20","20:00"]},
      "nota":"orari stagionali estate 10-12 / 17:20-20 (foglio [F])"}]'::jsonb,
   false, NULL, ST_SetSRID(ST_MakePoint(17.94450, 40.63960), 4326)::geography, 'stimata',
   NULL, false, ARRAY['turisti','pellegrini'], ARRAY['turismo lento','accoglienza'],
   'Orari stagionali: precedenza chiusura > evento > stagionale > regolare. Coordinate [ASSUNZIONE]: stimata.'),

  -- Sant'Elia — verificata (40.61847/17.92216)
  ('buscicchio', 'Parco Buscicchio', 'Sant''Elia', 'Legami di Comunità',
   '{"lun":["15:00","19:00"],"mar":["15:00","19:00"],"mer":["15:00","19:00"],
     "gio":["15:00","19:00"],"ven":["15:00","19:00"],"sab":["10:00","13:00"],"dom":[]}'::jsonb,
   NULL, false, NULL, ST_SetSRID(ST_MakePoint(17.92216, 40.61847), 4326)::geography, 'verificata',
   NULL, false, ARRAY['famiglie','caregiver','bambini'], ARRAY['educativa','portineria di comunità','ascolto'],
   'In squadra: psicologa di comunità e «portineria di comunità» (foglio [F]). Fascia educativa 6-19.'),

  -- La Rosa — verificata (40.60609/17.95196)
  ('san-bao', 'San Bao', 'La Rosa', 'Coop. NauKleros',
   '{"lun":["09:00","13:00"],"mar":["09:00","13:00"],"mer":["09:00","13:00"],
     "gio":["09:00","13:00"],"ven":["09:00","13:00"],"sab":[],"dom":[]}'::jsonb,
   '[{"tipo":"evento","nota":"aperture del weekend solo per eventi (foglio [F])",
      "orari":{"sab":["10:00","12:30"]}}]'::jsonb,
   false, NULL, ST_SetSRID(ST_MakePoint(17.95196, 40.60609), 4326)::geography, 'verificata',
   NULL, false, ARRAY['anziani'], ARRAY['benessere','portierato'],
   'Portierato attivo; weekend «per eventi» in orari_eccezioni.'),

  -- Centro Storico — stimata
  ('minimus', 'Minimus', 'Centro Storico', 'WWF Brindisi odv',
   '{"lun":[],"mar":["13:00","19:00"],"mer":["13:00","19:00"],"gio":["13:00","19:00"],
     "ven":["13:00","19:00"],"sab":["13:00","19:00"],"dom":[]}'::jsonb,
   NULL, false, NULL, ST_SetSRID(ST_MakePoint(17.94400, 40.63890), 4326)::geography, 'stimata',
   NULL, false, ARRAY['bambini','ragazzi'], ARRAY['ambiente','educazione'],
   'Fascia 13-19 (foglio [F]). Coordinate [ASSUNZIONE]: stimata.'),

  -- Perrino — verificata (40.63148/17.95341)
  ('pop', 'POP — Piccolo Opificio Popolare', 'Perrino', 'CE.F.A.S.',
   NULL, NULL, true, NULL, ST_SetSRID(ST_MakePoint(17.95341, 40.63148), 4326)::geography, 'verificata',
   NULL, false, ARRAY['bambini'], ARRAY['laboratori','formazione'],
   'Orari in fase di definizione (foglio [F]) → orari_provvisori=true, orari NULL.'),

  -- Bozzano — verificata (40.62350/17.94270)
  ('bozzano', 'Centro di Aggregazione Bozzano', 'Bozzano', 'L''Officina Sociale aps',
   '{"lun":["09:00","12:30","15:30","18:30"],"mar":["09:00","12:30","15:30","18:30"],
     "mer":["09:00","12:30","15:30","18:30"],"gio":["09:00","12:30","15:30","18:30"],
     "ven":["09:00","12:30","15:30","18:30"],"sab":["09:00","12:30"],"dom":[]}'::jsonb,
   NULL, false, NULL, ST_SetSRID(ST_MakePoint(17.94270, 40.62350), 4326)::geography, 'verificata',
   NULL, false, ARRAY['over 60'], ARRAY['aggregazione','bar interno'],
   'Gestione bar interna (foglio [F]); il bar è nel seed luoghi con casa_id = Bozzano.'),

  -- Paradiso — verificata (40.64958/17.91837)
  ('dream', 'Dream: Laboratorio Creativo', 'Paradiso', 'ANGSA + Il Bene Che Ti Voglio',
   '{"lun":["09:00","13:00"],"mar":["09:00","13:00"],"mer":["09:00","13:00"],
     "gio":["09:00","13:00"],"ven":["09:00","13:00"],"sab":["09:00","13:00"],"dom":[]}'::jsonb,
   NULL, false, NULL, ST_SetSRID(ST_MakePoint(17.91837, 40.64958), 4326)::geography, 'verificata',
   NULL, false, ARRAY['autismo','disabilità','caregiver'], ARRAY['laboratorio creativo','sportello informativo'],
   'Sportello informativo (foglio [F]).'),

  -- Tuturano — fuori dal centro urbano: raggio ampio, dati provvisori (§7, [DA VALIDARE])
  ('tuturano', 'Tuturano', 'Tuturano (frazione)', NULL,
   NULL, NULL, true, 2000, ST_SetSRID(ST_MakePoint(17.94691, 40.54525), 4326)::geography, 'stimata',
   NULL, true, NULL, NULL,
   'Dati provvisori (dati provvisori) — ente gestore e target [DA VALIDARE], completamento in S2. '
   'Fuori dal centro urbano: la vicinanza è distanza reale, non zona (raggio_m=2000).')
ON CONFLICT (slug) DO NOTHING;

-- ===========================================================================
-- 2. Mappa ruolo → Casa (12 righe: 10 Case + rete + ti)
-- ===========================================================================
INSERT INTO trasi.ruolo_casa (ruolo, casa_id, descrizione)
VALUES
  ('casa_santaspazio', (SELECT id FROM trasi.casa WHERE slug = 'santa-spazio'), 'Casa: Santa Spazio Culturale'),
  ('casa_molo12',      (SELECT id FROM trasi.casa WHERE slug = 'molo12'),       'Casa: Molo 12'),
  ('casa_erranti',     (SELECT id FROM trasi.casa WHERE slug = 'erranti'),      'Casa: Accademia degli Erranti'),
  ('casa_buscicchio',  (SELECT id FROM trasi.casa WHERE slug = 'buscicchio'),   'Casa: Parco Buscicchio'),
  ('casa_sanbao',      (SELECT id FROM trasi.casa WHERE slug = 'san-bao'),      'Casa: San Bao'),
  ('casa_minimus',     (SELECT id FROM trasi.casa WHERE slug = 'minimus'),      'Casa: Minimus'),
  ('casa_pop',         (SELECT id FROM trasi.casa WHERE slug = 'pop'),          'Casa: POP — Piccolo Opificio Popolare'),
  ('casa_bozzano',     (SELECT id FROM trasi.casa WHERE slug = 'bozzano'),      'Casa: Centro di Aggregazione Bozzano'),
  ('casa_dream',       (SELECT id FROM trasi.casa WHERE slug = 'dream'),        'Casa: Dream: Laboratorio Creativo'),
  ('casa_tuturano',    (SELECT id FROM trasi.casa WHERE slug = 'tuturano'),     'Casa: Tuturano'),
  ('rete',             NULL, 'Rete / AT-AQ: territorio, promozione dati esterni'),
  ('ti',               NULL, 'TI: allow-list fonti, parametri, identità')
ON CONFLICT (ruolo) DO UPDATE SET casa_id = EXCLUDED.casa_id, descrizione = EXCLUDED.descrizione;

-- ===========================================================================
-- 3. Identità Onyx (22 righe: op.<slug> e gestore.<slug> per 10 Case + rete + ti)
-- L'operatore e il gestore della stessa Casa condividono il ruolo DB (plan §394, governance).
-- ===========================================================================
INSERT INTO trasi.identita_onyx (email, ruolo_db, casa_id)
SELECT v.email, v.ruolo_db, rc.casa_id
FROM (VALUES
  ('op.santa-spazio@trasi.local',      'casa_santaspazio'),
  ('gestore.santa-spazio@trasi.local', 'casa_santaspazio'),
  ('op.molo12@trasi.local',            'casa_molo12'),
  ('gestore.molo12@trasi.local',       'casa_molo12'),
  ('op.erranti@trasi.local',           'casa_erranti'),
  ('gestore.erranti@trasi.local',      'casa_erranti'),
  ('op.buscicchio@trasi.local',        'casa_buscicchio'),
  ('gestore.buscicchio@trasi.local',   'casa_buscicchio'),
  ('op.san-bao@trasi.local',           'casa_sanbao'),
  ('gestore.san-bao@trasi.local',      'casa_sanbao'),
  ('op.minimus@trasi.local',           'casa_minimus'),
  ('gestore.minimus@trasi.local',      'casa_minimus'),
  ('op.pop@trasi.local',               'casa_pop'),
  ('gestore.pop@trasi.local',          'casa_pop'),
  ('op.bozzano@trasi.local',           'casa_bozzano'),
  ('gestore.bozzano@trasi.local',      'casa_bozzano'),
  ('op.dream@trasi.local',             'casa_dream'),
  ('gestore.dream@trasi.local',        'casa_dream'),
  ('op.tuturano@trasi.local',          'casa_tuturano'),
  ('gestore.tuturano@trasi.local',     'casa_tuturano'),
  ('rete@trasi.local',                 'rete'),
  ('ti@trasi.local',                   'ti')
) AS v(email, ruolo_db)
JOIN trasi.ruolo_casa rc ON rc.ruolo = v.ruolo_db
ON CONFLICT (email) DO UPDATE SET ruolo_db = EXCLUDED.ruolo_db, casa_id = EXCLUDED.casa_id, attiva = true;

RESET ROLE;
