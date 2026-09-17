-- Trasi — db/golden_seed.sql (P1/P2 del golden set, NON una migrazione di dominio)
--
-- Contenuti di prova per il golden set. Tre regole:
-- 1. La memoria (evento/scheda_servizio/persona) si scrive SOLO col flusso V4:
--    casa_* propone → rete approva → applicatore applica (+audit). Il ruoli sono
--    impersonati con SET LOCAL ROLE, come fa db/apply.sh, mai superuser.
-- 2. I due mock (richiesta non_trovata, opportunita scaduta) sono eccezioni
--    dichiarate di registrazione, con audit, e ripulibili (vedi `pulisci`).
-- 3. Marcatore unico: motivazione = 'golden set: …' (ricercabile, idempotente).
--
-- Uso (da host):
--   docker exec -i trasi-db_trasi-1 psql -U postgres -d trasi_db < db/golden_seed.sql          # applica
--   docker exec -i trasi-db_trasi-1 psql -U postgres -d trasi_db -v PULISCI=1 < db/golden_seed.sql  # pulisci
--
-- Dopo P1: `docker exec trasi-automazioni-1 /app/flussi/job.sh /app/flussi/export_kb.py` (re-ingest).
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
DELETE FROM trasi.opportunita WHERE titolo LIKE '%(golden)';
SELECT 'golden set ripulito' AS esito;
\else

-- ===========================================================================
-- 1 · P1a — 3 eventi con accesso completo: propone casa_sanbao / casa_buscicchio
-- ===========================================================================
BEGIN;

SET LOCAL ROLE casa_sanbao;
INSERT INTO proposta (origine, tipo, entita, entita_id, casa_id, payload, motivazione)
SELECT 'manuale', 'modifica_evento', 'evento', v.eid, e.casa_id, v.payload,
       'golden set: accesso completo evento'
FROM (VALUES
  (1427::bigint, jsonb_build_object('costo', 0, 'prenotazione', true,
        'prenotazione_nota', 'prenotazione al telefono della Casa', 'fascia_eta', 'famiglie')),
  (2438::bigint, jsonb_build_object('costo', 5, 'prenotazione', false, 'fascia_eta', 'adulti'))
) AS v(eid, payload)
JOIN trasi.evento e ON e.id = v.eid
WHERE NOT EXISTS (
  SELECT 1 FROM trasi.proposta p
  WHERE p.tipo = 'modifica_evento' AND p.entita_id = v.eid
    AND p.motivazione = 'golden set: accesso completo evento'
    AND p.stato IN ('proposta','approvata','applicata'));

SET LOCAL ROLE casa_buscicchio;
INSERT INTO proposta (origine, tipo, entita, entita_id, casa_id, payload, motivazione)
SELECT 'manuale', 'modifica_evento', 'evento', v.eid, e.casa_id, v.payload,
       'golden set: accesso completo evento'
FROM (VALUES
  (3357::bigint, jsonb_build_object('costo', 0, 'prenotazione', true,
        'prenotazione_nota', 'gratuito, prenotazione consigliata', 'fascia_eta', 'caregiver'))
) AS v(eid, payload)
JOIN trasi.evento e ON e.id = v.eid
WHERE NOT EXISTS (
  SELECT 1 FROM trasi.proposta p
  WHERE p.tipo = 'modifica_evento' AND p.entita_id = v.eid
    AND p.motivazione = 'golden set: accesso completo evento'
    AND p.stato IN ('proposta','approvata','applicata'));

COMMIT;

-- ===========================================================================
-- 2 · P1b — approvazione (rete = AT), poi applicazione (applicatore) + audit
-- ===========================================================================
BEGIN;
SET LOCAL ROLE rete;
UPDATE trasi.proposta SET stato = 'approvata'
 WHERE motivazione LIKE 'golden set: accesso completo evento' AND stato = 'proposta'
   AND approvatore_ruolo = 'gestore';   -- 6903-era: le proposte di gestore passano per la coda?
COMMIT;

BEGIN;
SET LOCAL ROLE applicatore;
SELECT trasi.applica_proposte_approvate(50);
COMMIT;

-- ===========================================================================
-- 3 · P1c — 3 schede servizio reali (ISEE, anagrafe, legge 103) via V4
-- ===========================================================================
BEGIN;

SET LOCAL ROLE casa_sanbao;
INSERT INTO proposta (origine, tipo, entita, entita_id, casa_id, payload, motivazione)
SELECT 'manuale', 'nuova_scheda', 'scheda_servizio', NULL, 5,
       jsonb_build_object('titolo', 'ISEE — patronato in Casa (golden)',
         'descrizione', 'Redazione DSU e assistenza ISEE; documento e codice fiscale',
         'orari', jsonb_build_object('lun', jsonb_build_array('09:00','13:00'),
                                     'mer', jsonb_build_array('09:00','13:00')),
         'url', 'https://www.inps.it'),
       'golden set: scheda servizio ISEE'
WHERE NOT EXISTS (SELECT 1 FROM trasi.proposta
  WHERE tipo='nuova_scheda' AND motivazione='golden set: scheda servizio ISEE'
    AND stato IN ('proposta','approvata','applicata'));

SET LOCAL ROLE casa_bozzano;
INSERT INTO proposta (origine, tipo, entita, entita_id, casa_id, payload, motivazione)
SELECT 'manuale', 'nuova_scheda', 'scheda_servizio', NULL, 8,
       jsonb_build_object('titolo', 'Certificati anagrafici (golden)',
         'descrizione', 'Richiesta certificati anagrafici con SPID o allo sportello',
         'orari', jsonb_build_object('lun', jsonb_build_array('09:00','12:00'),
                                     'ven', jsonb_build_array('09:00','12:00')),
         'url', 'https://www.comune.brindisi.it/servizio/certificati-anagrafici/'),
       'golden set: scheda anagrafe'
WHERE NOT EXISTS (SELECT 1 FROM trasi.proposta
  WHERE tipo='nuova_scheda' AND motivazione='golden set: scheda anagrafe'
    AND stato IN ('proposta','approvata','applicata'));

SET LOCAL ROLE casa_buscicchio;
INSERT INTO proposta (origine, tipo, entita, entita_id, casa_id, payload, motivazione)
SELECT 'manuale', 'nuova_scheda', 'scheda_servizio', NULL, 4,
       jsonb_build_object('titolo', 'Assistenza legge 103 (golden)',
         'descrizione', 'Diritti per persone con disabilita: esenzioni e accompagnamento',
         'orari', jsonb_build_object('mar', jsonb_build_array('15:00','18:00')),
         'url', 'https://www.inps.it'),
       'golden set: scheda legge 103'
WHERE NOT EXISTS (SELECT 1 FROM trasi.proposta
  WHERE tipo='nuova_scheda' AND motivazione='golden set: scheda legge 103'
    AND stato IN ('proposta','approvata','applicata'));

COMMIT;

-- ===========================================================================
-- 4 · P1d — 1 movimento confermato in corso (proposto da San Bao, conferma Bozzano)
-- ===========================================================================
BEGIN;
SET LOCAL ROLE casa_sanbao;
INSERT INTO movimento (oggetto_id, da_casa_id, a_casa_id, dal, al, motivazione)
SELECT 474, 5, 8, current_date + 14, current_date + 17, 'golden set: prestito in corso'
WHERE NOT EXISTS (SELECT 1 FROM trasi.movimento m
  WHERE m.oggetto_id = 474 AND m.motivazione = 'golden set: prestito in corso'
    AND m.stato IN ('proposto','confermato'))
RETURNING id AS movimento_golden;
COMMIT;

\set MOV_ID `(SELECT max(id) FROM trasi.movimento WHERE motivazione = 'golden set: prestito in corso' AND stato='proposto' ORDER BY id DESC LIMIT 1)`
BEGIN;
SET LOCAL ROLE casa_bozzano;
SELECT trasi.conferma_movimento(:MOV_ID, 'casa_bozzano');
COMMIT;

-- ===========================================================================
-- 5 · P1e — 3 referenti con consenso (via salva_dato = INSERT diretto ammesso a casa_*)
--     `persona_casa` con consenso_il è la condizione di v_kb_export (db/029)
-- ===========================================================================
BEGIN;
SET LOCAL ROLE casa_sanbao;
INSERT INTO persona_casa (casa_id, nome, ruolo, competenze, consenso_il)
SELECT 5, 'Referente golden San Bao (golden)', 'referente sportello',
       'orientamento, ISEE', current_date
WHERE NOT EXISTS (SELECT 1 FROM trasi.persona_casa WHERE nome = 'Referente golden San Bao (golden)');
SET LOCAL ROLE casa_bozzano;
INSERT INTO persona_casa (casa_id, nome, ruolo, competenze, consenso_il)
SELECT 8, 'Referente golden Bozzano (golden)', 'referente laboratori',
       'intercultura', current_date
WHERE NOT EXISTS (SELECT 1 FROM trasi.persona_casa WHERE nome = 'Referente golden Bozzano (golden)');
SET LOCAL ROLE casa_buscicchio;
INSERT INTO persona_casa (casa_id, nome, ruolo, competenze, consenso_il)
SELECT 4, 'Referente golden Buscicchio (golden)', 'referente educativa',
       'famiglie, caregiver', current_date
WHERE NOT EXISTS (SELECT 1 FROM trasi.persona_casa WHERE nome = 'Referente golden Buscicchio (golden)');
COMMIT;

-- ===========================================================================
-- 6 · P2a — MOCK contabilizzato: 1 richiesta non_trovata (alimenta `lacune` PA)
--     Via canale op = INSERT + audit atomica (trasi.registra_richiesta_operatore)
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
-- 7 · P2b — MOCK contabilizzato: 1 opportunita scaduta da ieri (US-06, v_scaduti)
--     `opportunita` è dominio: la via V4 è `nuova_opportunita` proposta→approva→applica.
--     Scadenza passata ⇒ il flusso iCal-like NON la tocca; l'alert la conta.
-- ===========================================================================
BEGIN;
SET LOCAL ROLE casa_sanbao;
INSERT INTO proposta (origine, tipo, entita, entita_id, casa_id, payload, motivazione)
SELECT 'manuale', 'nuova_opportunita', 'opportunita', NULL, 5,
       jsonb_build_object('titolo', 'Bando scaduto golden (golden)',
         'descrizione', 'Bando di prova per l\u2019alert US-06 del golden set',
         'categoria', 'altro',
         'scadenza', (current_date - 10)::text,
         'url', 'https://www.regione.puglia.it/web/welfare-diritti-e-cittadinanza/elenco-bandi'),
       'golden set: bando scaduto'
WHERE NOT EXISTS (SELECT 1 FROM trasi.proposta
  WHERE tipo='nuova_opportunita' AND motivazione='golden set: bando scaduto'
    AND stato IN ('proposta','approvata','applicata'));
COMMIT;

BEGIN;
SET LOCAL ROLE rete;
UPDATE trasi.proposta SET stato='approvata'
 WHERE motivazione='golden set: bando scaduto' AND stato='proposta';
COMMIT;

BEGIN;
SET LOCAL ROLE applicatore;
SELECT trasi.applica_proposte_approvate(50);
COMMIT;

-- ===========================================================================
-- 8 · Verifica di fine seed (PASS = notice; un conteggio atteso diverso EXCEPTION)
-- ===========================================================================
DO $$
DECLARE
  v_schede int; v_persone int; v_mov int; v_prop int; v_opp int; v_req int;
BEGIN
  SELECT count(*) INTO v_schede FROM trasi.scheda_servizio WHERE titolo LIKE '%(golden)';
  SELECT count(*) INTO v_persone FROM trasi.persona_casa WHERE nome LIKE '%(golden)';
  SELECT count(*) INTO v_mov FROM trasi.movimento WHERE motivazione = 'golden set: prestito in corso' AND stato='confermato';
  SELECT count(*) INTO v_prop FROM trasi.proposta WHERE motivazione LIKE 'golden set:%' AND stato <> 'applicata';
  SELECT count(*) INTO v_opp FROM trasi.opportunita WHERE titolo LIKE '%(golden)';
  SELECT count(*) INTO v_req FROM trasi.richiesta WHERE esito='non_trovata';

  IF v_schede < 3 THEN RAISE EXCEPTION 'golden: attese 3 schede, trovate %', v_schede; END IF;
  IF v_persone < 3 THEN RAISE EXCEPTION 'golden: attese 3 persone, trovate %', v_persone; END IF;
  IF v_mov < 1 THEN RAISE EXCEPTION 'golden: atteso 1 movimento confermato, trovato %', v_mov; END IF;
  IF v_prop <> 0 THEN RAISE EXCEPTION 'golden: proposte residue % (attese 0: tutte applicate)', v_prop; END IF;
  IF v_opp < 1 THEN RAISE EXCEPTION 'golden: attesa 1 opportunita scaduta, trovata %', v_opp; END IF;
  IF v_req < 1 THEN RAISE EXCEPTION 'golden: attesa 1 richiesta non_trovata, trovata %', v_req; END IF;
  RAISE NOTICE 'golden seed OK: % schede, % persone, % movimenti, % opportunita, % richieste nt',
    v_schede, v_persone, v_mov, v_opp, v_req;
END $$;

\endif