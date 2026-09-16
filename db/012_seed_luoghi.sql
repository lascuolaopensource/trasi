-- Trasi — db/012_seed_luoghi.sql
-- Luoghi della memoria della rete: 22 righe, tutte con geom, fonte_id e affidabilita (mai NULL).
--   10 casa_quartiere        (una per Casa, stessa geometria della Casa)         affidabilità 3
--    3 presidio_ascolto      (Buscicchio, San Bao, Bozzano)                      affidabilità 3
--    1 servizio_professionale(psicologa di comunità, Parco Buscicchio)           affidabilità 3
--    1 bar con casa_id=Bozzano (entro 50 m dalla Casa, ST_DWithin verificato)    affidabilità 2
--    5 istituzionali         (Comune, ASL, INPS, Regione, Questura)              affidabilità 1
--    2 caf                   (La Rosa e Perrino, per US-01)                      affidabilità 1
--   → count(affidabilita=3) = 14 (solo dati della rete), count(affidabilita=1) = 7 (da verificare),
--     count(affidabilita=2) = 1 (il bar interno, dato della rete ma gestione operativa).
--
-- Perché le istituzionali hanno affidabilità 1: §11 tratta i dati del Comune come provvisori fino alla
-- validazione ([P] gg_validazione_comune); la chat li mostra con badge KB «affidabilità 1» e propone la
-- verifica. La stessa marca è sui 2 CAF (plan App. C: «2 righe caf affidabilità 1 … la chat le mostra
-- badge KB affidabilità 1 e propone modifica_luogo a verifica operatore»).
--
-- [ASSUNZIONE] Indirizzi: NULL (nessuna verifica civica disponibile in B1) — il campo `indirizzo` dello
-- shim è COALESCE(a '' , …) e il biglietto di US-01 richiederà l'indirizzo reale, che l'AT inserisce con
-- una proposta. Orari: noti solo dove il foglio [F] li documenta (bar interno = orari della Casa);
-- assenti per i CAF («orari NULL», plan App. C) e per le sedi istituzionali.
-- `ext_ref` resta NULL: gli identificativi stabili delle fonti esterne (osm:node/…) si assegnano
-- all'ingestione (F4), non si inventano nel seed.
--
-- Idempotenza senza chiave artificiale: INSERT … WHERE NOT EXISTS sul nome (i nomi del seed sono distinti,
-- e un UNIQUE(nome) sarebbe sbagliato: due Case possono avere un luogo omonimo).
\set ON_ERROR_STOP on
\set VERBOSITY terse

SET ROLE trasi_owner;
SET search_path = trasi, public, pg_temp;

INSERT INTO trasi.luogo
  (nome, tipo, descrizione, indirizzo, geom, orari, note_accesso, chiuso_il, ext_ref, url,
   casa_id, fonte_id, affidabilita, data_aggiornamento)
SELECT v.nome, v.tipo, v.descrizione, NULL,
       ST_SetSRID(ST_MakePoint(v.lon, v.lat), 4326)::geography,
       v.orari::jsonb, v.note_accesso, NULL, NULL, v.url,
       c.id, f.id, v.affidabilita, current_date
FROM (VALUES
  -- --- 10 casa_quartiere: la Casa è anche un luogo della mappa -------------------------------
  ('Santa Spazio Culturale', 'casa_quartiere', 'Casa di Quartiere — Centro Storico', 40.64036, 17.94518,
   'santa-spazio', 'Rete-kb-3', 3,
   '{"lun":["09:30","13:00","16:00","19:00"],"mar":["09:30","13:00","16:00","19:00"],"mer":["09:30","13:00","16:00","19:00"],"gio":["09:30","13:00","16:00","19:00"],"ven":["09:30","13:00","16:00","19:00"],"sab":["10:00","13:00"],"dom":[]}',
   NULL, NULL),
  ('Molo 12', 'casa_quartiere', 'Casa di Quartiere — coworking e impresa', 40.64370, 17.94610,
   'molo12', 'Rete-kb-3', 3,
   '{"lun":["09:00","18:00"],"mar":["09:00","18:00"],"mer":["09:00","18:00"],"gio":["09:00","18:00"],"ven":["09:00","18:00"],"sab":[],"dom":[]}',
   NULL, NULL),
  ('Accademia degli Erranti', 'casa_quartiere', 'Casa di Quartiere — turismo lento e pellegrini', 40.63960, 17.94450,
   'erranti', 'Rete-kb-3', 3,
   '{"mar":["10:00","12:00","17:20","20:00"],"mer":["10:00","12:00","17:20","20:00"],"gio":["10:00","12:00","17:20","20:00"],"ven":["10:00","12:00","17:20","20:00"],"sab":["10:00","12:00","17:20","20:00"]}',
   'Orari stagionali: vedere le eccezioni della Casa', NULL),
  ('Parco Buscicchio', 'casa_quartiere', 'Casa di Quartiere — educativa e famiglie', 40.61847, 17.92216,
   'buscicchio', 'Rete-kb-3', 3,
   '{"lun":["15:00","19:00"],"mar":["15:00","19:00"],"mer":["15:00","19:00"],"gio":["15:00","19:00"],"ven":["15:00","19:00"],"sab":["10:00","13:00"],"dom":[]}',
   NULL, NULL),
  ('San Bao', 'casa_quartiere', 'Casa di Quartiere — anziani e benessere', 40.60609, 17.95196,
   'san-bao', 'Rete-kb-3', 3,
   '{"lun":["09:00","13:00"],"mar":["09:00","13:00"],"mer":["09:00","13:00"],"gio":["09:00","13:00"],"ven":["09:00","13:00"],"sab":[],"dom":[]}',
   'Aperture del weekend solo per eventi', NULL),
  ('Minimus', 'casa_quartiere', 'Casa di Quartiere — ambiente, 13-19', 40.63890, 17.94400,
   'minimus', 'Rete-kb-3', 3,
   '{"mar":["13:00","19:00"],"mer":["13:00","19:00"],"gio":["13:00","19:00"],"ven":["13:00","19:00"],"sab":["13:00","19:00"]}',
   NULL, NULL),
  ('POP — Piccolo Opificio Popolare', 'casa_quartiere', 'Casa di Quartiere — laboratori e formazione', 40.63148, 17.95341,
   'pop', 'Rete-kb-3', 3,
   NULL, 'Orari in via di definizione', NULL),
  ('Centro di Aggregazione Bozzano', 'casa_quartiere', 'Casa di Quartiere — over 60, con bar interna', 40.62350, 17.94270,
   'bozzano', 'Rete-kb-3', 3,
   '{"lun":["09:00","12:30","15:30","18:30"],"mar":["09:00","12:30","15:30","18:30"],"mer":["09:00","12:30","15:30","18:30"],"gio":["09:00","12:30","15:30","18:30"],"ven":["09:00","12:30","15:30","18:30"],"sab":["09:00","12:30"],"dom":[]}',
   NULL, NULL),
  ('Dream: Laboratorio Creativo', 'casa_quartiere', 'Casa di Quartiere — autismo e disabilità', 40.64958, 17.91837,
   'dream', 'Rete-kb-3', 3,
   '{"lun":["09:00","13:00"],"mar":["09:00","13:00"],"mer":["09:00","13:00"],"gio":["09:00","13:00"],"ven":["09:00","13:00"],"sab":["09:00","13:00"]}',
   'Sportello informativo', NULL),
  ('Tuturano', 'casa_quartiere', 'Casa di Quartiere — frazione di Tuturano (dati provvisori)', 40.54525, 17.94691,
   'tuturano', 'Rete-kb-3', 3,
   NULL, 'Orari e dati in via di definizione (dati provvisori)', NULL),

  -- --- 3 presidi di ascolto («pre» nel Presidio, US-04) --------------------------------------
  ('Presidio di ascolto — Parco Buscicchio', 'presidio_ascolto',
   'Accoglienza e ascolto, primo accesso senza appuntamento', 40.61860, 17.92260,
   'buscicchio', 'Rete-kb-3', 3,
   '{"lun":["15:00","19:00"],"mar":["15:00","19:00"],"mer":["15:00","19:00"],"gio":["15:00","19:00"],"ven":["15:00","19:00"]}',
   'Accesso libero nella fascia di apertura', NULL),
  ('Presidio di ascolto — San Bao', 'presidio_ascolto',
   'Accoglienza e ascolto per persone anziane e famiglie', 40.60630, 17.95170,
   'san-bao', 'Rete-kb-3', 3,
   '{"lun":["09:00","13:00"],"mar":["09:00","13:00"],"mer":["09:00","13:00"],"gio":["09:00","13:00"],"ven":["09:00","13:00"]}',
   'Accesso libero nella fascia di apertura', NULL),
  ('Presidio di ascolto — Bozzano', 'presidio_ascolto',
   'Accoglienza e ascolto per over 60', 40.62370, 17.94220,
   'bozzano', 'Rete-kb-3', 3,
   '{"lun":["09:00","12:30"],"mar":["09:00","12:30"],"mer":["09:00","12:30"],"gio":["09:00","12:30"],"ven":["09:00","12:30"]}',
   'Accesso libero nella fascia di apertura', NULL),

  -- --- 1 servizio professionale interno (psicologa di comunità, §2.1) ------------------------
  ('Psicologa di comunità — Parco Buscicchio', 'servizio_professionale',
   'Servizio professionale interno alla Casa (psicologa di comunità)', 40.61830, 17.92180,
   'buscicchio', 'Rete-kb-3', 3,
   NULL, 'Su appuntamento tramite la portineria di comunità', NULL),

  -- --- 1 bar con gestione interna a Bozzano (criterio: entro 50 m dalla Casa) ----------------
  ('Bar interno — Centro di Aggregazione Bozzano', 'bar',
   'Bar a gestione interna della Casa di Quartiere', 40.62370, 17.94295,
   'bozzano', 'Rete-kb-3', 2,
   '{"lun":["08:00","18:30"],"mar":["08:00","18:30"],"mer":["08:00","18:30"],"gio":["08:00","18:30"],"ven":["08:00","18:30"],"sab":["09:00","12:30"],"dom":[]}',
   'Ingresso dalla Casa', NULL),

  -- --- 5 sedi istituzionali (dato del Comune/enti: provvisorio fino a validazione) ------------
  ('Comune di Brindisi — URP', 'comune', 'Ufficio relazioni con il pubblico', 40.64036, 17.94518,
   NULL, 'Comune di Brindisi-3', 1,
   '{"lun":["08:30","12:30"],"mar":["08:30","12:30"],"mer":["08:30","12:30"],"gio":["08:30","12:30","15:00","17:00"],"ven":["08:30","12:30"]}',
   NULL, 'https://www.comune.brindisi.it'),
  ('ASL Brindisi — Distretto socio-sanitario', 'asl', 'Distretto socio-sanitario', 40.63580, 17.94390,
   NULL, 'ASL Brindisi-3', 1,
   '{"lun":["08:30","13:00"],"mar":["08:30","13:00"],"mer":["08:30","13:00"],"gio":["08:30","13:00"],"ven":["08:30","13:00"]}',
   NULL, 'https://www.asl.brindisi.it'),
  ('INPS — Agenzia di Brindisi', 'inps', 'Sede INPS provinciale', 40.63890, 17.94720,
   NULL, 'INPS-3', 1,
   '{"lun":["08:30","13:00"],"mar":["08:30","13:00"],"mer":["08:30","13:00"],"gio":["08:30","13:00"],"ven":["08:30","13:00"]}',
   'Accesso su prenotazione per la maggior parte dei servizi', 'https://www.inps.it'),
  ('Regione Puglia — sportello territoriale', 'sportello', 'Sportello territoriale regionale', 40.63920, 17.94210,
   NULL, 'Regione Puglia-3', 1,
   NULL, NULL, 'https://www.regione.puglia.it'),
  ('Questura di Brindisi', 'questura', 'Ufficio immigrazione e permessi di soggiorno', 40.64500, 17.93900,
   NULL, 'Questura di Brindisi-3', 1,
   '{"lun":["08:30","12:30"],"mar":["08:30","12:30"],"mer":["08:30","12:30"],"gio":["08:30","12:30"],"ven":["08:30","12:30"]}',
   'Accesso su appuntamento', 'https://questure.poliziadistato.it/Brindisi'),

  -- --- 2 CAF di riferimento US-01 (La Rosa e Perrino; orari NULL, da verificare) ---------------
  ('CAF ACLI La Rosa', 'caf', 'Patronato ACLI — assistenza fiscale e ISEE', 40.60650, 17.95050,
   NULL, 'CAF ACLI Brindisi', 1,
   NULL, 'Orari e indirizzo da verificare', NULL),
  ('CAF CISL Perrino', 'caf', 'Patronato CISL — assistenza fiscale e ISEE', 40.63150, 17.95250,
   NULL, 'CAF CISL Brindisi', 1,
   NULL, 'Orari e indirizzo da verificare', NULL)
) AS v(nome, tipo, descrizione, lat, lon, casa_slug, fonte_nome, affidabilita, orari, note_accesso, url)
LEFT JOIN trasi.casa c  ON c.slug = v.casa_slug
JOIN      trasi.fonte f ON f.nome = v.fonte_nome
WHERE NOT EXISTS (SELECT 1 FROM trasi.luogo l WHERE l.nome = v.nome);

RESET ROLE;
