-- Trasi — db/golden_seed.sql (P1/P2 del golden set, NON una migrazione di dominio)
--
-- Contenuti di prova per il golden set. Tre regole, e la ragione per cui sono così:
-- 1. La memoria (scheda/evento/opportunita) si scrive via **gestione diretta D1**
--    (ruolo casa_*, limitata a casa_id = casa_corrente()): è la via ammessa dal
--    piano (§7 riga 390, «scrittura diretta gestore su proprie schede/eventi/
--    opportunita: ammessa») e da db/005 D1 con SWITCH-CASA-STRICT spento.
--    Perché non via proposta: per i tipi casa→gestore la policy no_self_approve
--    forma un vicolo cieco noto (B7 US-07, BUG-05 nel report: proposto_da =
--    current_user a causa del ruolo DB condiviso) — approva NESSUNO.
-- 2. I due mock (richiesta non_trovata, opportunita scaduta) sono registrazioni
--    di esercizio: la richiesta passa da registra_richiesta_operatore (INSERT+audit
--    atomica, eccezione V4 documentata); l'opportunita è D1 diretto del gestore.
-- 3. Marcatore unico: motivazione/titolo con '(golden)' (ricercabile, idempotente).
--
-- Uso (da host):
--   docker exec -i trasi-db_trasi-1 psql -U postgres -d trasi_db < db/golden_seed.sql               # applica
--   docker exec -i trasi-db_trasi-1 psql -U postgres -d trasi_db -v PULISCI=1 < db/golden_seed.sql  # pulisci
--
-- Dopo il seed: re-ingest con `docker exec trasi-automazioni-1 /app/flussi/job.sh /app/flussi/export_kb.py`
-- (cron 01:00, riparato il 17/09: prima il mount puntava a un worktree cancellato).
\set ON_ERROR_STOP on
\set VERBOSITY terse

SET search_path = trasi, public, pg_temp;

-- ===========================================================================
-- 0 · PULISCI — rimuove i contenuti golden (prima audit/proposta per FK)
-- ===========================================================================
\if :{?PULISCI}
DELETE FROM trasi.audit WHERE proposta_id IN (SELECT id FROM trasi.proposta WHERE motivazione LIKE 'golden set:%');
DELETE FROM trasi.proposta WHERE motivazione LIKE 'golden set:%';
DELETE FROM trasi.richiesta WHERE destinazione_nota = 'golden set: richieste senza risposta';
DELETE FROM trasi.movimento WHERE motivazione = 'golden set: prestito in corso';
DELETE FROM trasi.persona_casa WHERE nome LIKE '%(golden)';
DELETE FROM trasi.scheda_servizio WHERE titolo LIKE '%(golden)';
DELETE FROM trasi.opportunita WHERE titolo LIKE '%(golden)';
SELECT 'golden set ripulito' AS esito;
\else

-- ===========================================================================
-- 1 · P1a — 3 eventi con accesso completo (costo/prenotazione/fascia), D1
--     Il ruolo è `casa_sanbao` per gli eventi di San Bao (1427, 2438) e
--     `casa_erranti` per l'evento di Erranti (3357): la gestione diretta vale
--     sulla PROPRIA Casa.
-- ===========================================================================
BEGIN;
SET LOCAL ROLE casa_sanbao;
UPDATE trasi.evento SET costo = 0, prenotazione = true,
       prenotazione_nota = 'prenotazione al telefono della Casa', fascia_eta = 'tutte'
 WHERE id = 1427 AND casa_id = trasi.casa_corrente()::int;
UPDATE trasi.evento SET costo = 5, prenotazione = false, fascia_eta = '18-29'
 WHERE id = 2438 AND casa_id = trasi.casa_corrente()::int;
COMMIT;

BEGIN;
SET LOCAL ROLE casa_erranti;
UPDATE trasi.evento SET costo = 0, prenotazione = true,
       prenotazione_nota = 'gratuito, prenotazione consigliata', fascia_eta = '30-44'
 WHERE id = 3357 AND casa_id = trasi.casa_corrente()::int;
COMMIT;

-- ===========================================================================
-- 2 · P1b — 3 schede servizio reali (ISEE, anagrafe, legge 103), D1 per gestore
-- ===========================================================================
BEGIN;
SET LOCAL ROLE casa_sanbao;
INSERT INTO scheda_servizio (casa_id, titolo, descrizione, orari, url, affidabilita)
SELECT 5, 'ISEE — patronato in Casa (golden)',
       'Redazione DSU e assistenza ISEE; documento e codice fiscale',
       jsonb_build_object('lun', jsonb_build_array('09:00','13:00'),
                          'mer', jsonb_build_array('09:00','13:00')),
       'https://www.inps.it', 3
WHERE NOT EXISTS (SELECT 1 FROM trasi.scheda_servizio WHERE titolo LIKE 'ISEE — patronato in Casa (golden)%');
SET LOCAL ROLE casa_bozzano;
INSERT INTO scheda_servizio (casa_id, titolo, descrizione, orari, url, affidabilita)
SELECT 8, 'Certificati anagrafici (golden)',
       'Richiesta certificati anagrafici con SPID o allo sportello',
       jsonb_build_object('lun', jsonb_build_array('09:00','12:00'),
                          'ven', jsonb_build_array('09:00','12:00')),
       'https://www.comune.brindisi.it/servizio/certificati-anagrafici/', 3
WHERE NOT EXISTS (SELECT 1 FROM trasi.scheda_servizio WHERE titolo LIKE 'Certificati anagrafici (golden)%');
SET LOCAL ROLE casa_buscicchio;
INSERT INTO scheda_servizio (casa_id, titolo, descrizione, orari, url, affidabilita)
SELECT 4, 'Assistenza legge 103 (golden)',
       'Diritti per persone con disabilita: esenzioni e accompagnamento',
       jsonb_build_object('mar', jsonb_build_array('15:00','18:00')),
       'https://www.inps.it', 3
WHERE NOT EXISTS (SELECT 1 FROM trasi.scheda_servizio WHERE titolo LIKE 'Assistenza legge 103 (golden)%');
COMMIT;

-- ===========================================================================
-- 3 · P1c — 1 movimento confermato in corso (proposto da San Bao, conferma Bozzano)
--     Il movimento è evento operativo (INSERT diretto ammesso alla cedente),
--     la conferma passa per conferma_movimento con audit (V6: decisione umana).
-- ===========================================================================
BEGIN;
SET LOCAL ROLE casa_sanbao;
INSERT INTO movimento (oggetto_id, da_casa_id, a_casa_id, dal, al, motivazione)
SELECT 474, 5, 8, current_date + 14, current_date + 17, 'golden set: prestito in corso'
WHERE NOT EXISTS (SELECT 1 FROM trasi.movimento m
  WHERE m.oggetto_id = 474 AND m.motivazione = 'golden set: prestito in corso'
    AND m.stato IN ('proposto','confermato'));
COMMIT;

BEGIN;
SET LOCAL ROLE casa_bozzano;
DO $conf$
DECLARE
  v_mov int;
BEGIN
  SELECT max(id) INTO v_mov FROM trasi.movimento
   WHERE motivazione = 'golden set: prestito in corso' AND stato = 'proposto';
  IF v_mov IS NOT NULL THEN
    PERFORM trasi.conferma_movimento(v_mov, 'casa_bozzano');
  END IF;
END
$conf$;
COMMIT;

-- ===========================================================================
-- 4 · P1d — 3 referenti con consenso (INSERT diretto ammesso a casa_*; la
--     condizione `consenso_il IS NOT NULL` è ciò che li rende citabili: db/029)
-- ===========================================================================
BEGIN;
SET LOCAL ROLE casa_sanbao;
INSERT INTO persona_casa (casa_id, nome, ruolo, competenze, consenso_il)
SELECT 5, 'Referente golden San Bao (golden)', 'referente sportello',
       ARRAY['orientamento','ISEE']::text[], current_date
WHERE NOT EXISTS (SELECT 1 FROM trasi.persona_casa WHERE nome = 'Referente golden San Bao (golden)');
SET LOCAL ROLE casa_bozzano;
INSERT INTO persona_casa (casa_id, nome, ruolo, competenze, consenso_il)
SELECT 8, 'Referente golden Bozzano (golden)', 'referente laboratori',
       ARRAY['intercultura']::text[], current_date
WHERE NOT EXISTS (SELECT 1 FROM trasi.persona_casa WHERE nome = 'Referente golden Bozzano (golden)');
SET LOCAL ROLE casa_buscicchio;
INSERT INTO persona_casa (casa_id, nome, ruolo, competenze, consenso_il)
SELECT 4, 'Referente golden Buscicchio (golden)', 'referente educativa',
       ARRAY['famiglie','caregiver']::text[], current_date
WHERE NOT EXISTS (SELECT 1 FROM trasi.persona_casa WHERE nome = 'Referente golden Buscicchio (golden)');
COMMIT;

-- ===========================================================================
-- 5 · P2a — MOCK contabilizzato: 1 richiesta non_trovata (alimenta `lacune` PA).
--     Via registra_richiesta_operatore: INSERT + audit in una transazione
--     (eccezione V4 documentata: la registrazione avviene durante il colloquio).
-- ===========================================================================
BEGIN;
SET LOCAL ROLE casa_sanbao;
SELECT trasi.registra_richiesta_operatore(
  'san-bao',                          -- casa (slug)
  'orientamento',                     -- categoria
  'non_trovata'                       -- esito: alimenta `v_senza_risposta` e il tool `lacune`
);
COMMIT;

-- ===========================================================================
-- 6 · P2b — MOCK contabilizzato: 1 opportunita scaduta da 10 giorni (US-06).
--     Scrittura D1 diretta del gestore (piano §7 riga 390: ammessa).
-- ===========================================================================
BEGIN;
SET LOCAL ROLE casa_sanbao;
INSERT INTO opportunita (casa_id, titolo, descrizione, categoria, scadenza, url, affidabilita)
SELECT 5, 'Bando scaduto golden (golden)',
       'Bando di prova per l''alert US-06 del golden set', 'altro',
       current_date - 10, 'https://www.regione.puglia.it/web/welfare-diritti-e-cittadinanza/elenco-bandi', 3
WHERE NOT EXISTS (SELECT 1 FROM trasi.opportunita WHERE titolo = 'Bando scaduto golden (golden)');
COMMIT;

-- ===========================================================================
-- 7 · Verifica di fine seed (PASS = notice; un conteggio atteso diverso EXCEPTION)
-- ===========================================================================
DO $$
DECLARE
  v_schede int; v_persone int; v_mov int; v_opp int; v_req int; v_eventi int;
BEGIN
  SELECT count(*) INTO v_eventi FROM trasi.evento WHERE id IN (1427,2438,3357)
    AND costo IS NOT NULL AND prenotazione IS NOT NULL AND fascia_eta IS NOT NULL;
  SELECT count(*) INTO v_schede FROM trasi.scheda_servizio WHERE titolo LIKE '%(golden)';
  SELECT count(*) INTO v_persone FROM trasi.persona_casa WHERE nome LIKE '%(golden)';
  SELECT count(*) INTO v_mov FROM trasi.movimento WHERE motivazione = 'golden set: prestito in corso' AND stato='confermato';
  SELECT count(*) INTO v_opp FROM trasi.opportunita WHERE titolo = 'Bando scaduto golden (golden)';
  SELECT count(*) INTO v_req FROM trasi.richiesta WHERE esito='non_trovata';

  IF v_eventi < 3 THEN RAISE EXCEPTION 'golden: attesi 3 eventi completi, trovati %', v_eventi; END IF;
  IF v_schede < 3 THEN RAISE EXCEPTION 'golden: attese 3 schede, trovate %', v_schede; END IF;
  IF v_persone < 3 THEN RAISE EXCEPTION 'golden: attese 3 persone, trovate %', v_persone; END IF;
  IF v_mov < 1 THEN RAISE EXCEPTION 'golden: atteso 1 movimento confermato, trovato %', v_mov; END IF;
  IF v_opp < 1 THEN RAISE EXCEPTION 'golden: attesa 1 opportunita scaduta, trovata %', v_opp; END IF;
  IF v_req < 1 THEN RAISE EXCEPTION 'golden: attesa 1 richiesta non_trovata, trovata %', v_req; END IF;
  RAISE NOTICE 'golden seed OK: % eventi completi, % schede, % persone, % movimenti, % opportunita, % richieste nt',
    v_eventi, v_schede, v_persone, v_mov, v_opp, v_req;
END $$;

\endif