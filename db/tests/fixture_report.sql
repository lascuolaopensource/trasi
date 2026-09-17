-- Trasi — db/tests/fixture_report.sql · FIXTURE per provare la generazione del report mensile
--
-- Dati momentanei per il test del report (2026-09-17): il DB vivo ha quasi solo
-- `orientamento`/`risolta` (391 righe al 16/09, poi cresciute), quindi `v_report_mensile`
-- restituisce un report monocolore che non esercita né le celle ≥5 né la mascheratura `<5`.
-- Questo file aggiunge varietà per PROVARE LA GENERAZIONE, non per falsare il dato: ogni
-- riga porta un **marcatore** univoco e si rimuove con una sola DELETE (o col ROLLBACK della
-- batteria), e le righe NON toccano `v_scritture_senza_audit` (vedi sotto).
--
-- Cosa contiene (mese 2026-09 e un po' di 2026-08 per il confronto fra mesi):
--   · `richiesta`  — 6 Case, 8 categorie, 4 esiti: abbastanza che esista una cella (Casa,
--     categoria, esito) con n ≥ 5 (numero NON mascherato) e 2–3 celle con n = 1..4 (mascherate
--     come `<5` da `trasi.k_anon`, soglia `[P] k_anonimato` = 5);
--   · `evento` — 4 eventi futuri (visibili in `v_confronto_case.eventi_futuri`);
--   · `opportunita` — 2 aperte (visibili in `v_confronto_case.opportunita_aperte`).
--
-- Perché NON sporca `v_scritture_senza_audit` (la contabilità di V4):
--   · `richiesta` non è fra le entità di quella vista (l'ha scritta `registra_richiesta`, e la
--     registrazione è l'eccezione dichiarata di V4 — v. $COMMENT della vista in db/006);
--   · `evento`/`opportunita` vi compaiono SOLO se `aggiornato_ts IS NOT NULL`: qui l'INSERT non
--     lo imposta, e la pulizia finale è una DELETE (che non timbra nulla). Nessuna mutazione
--     senza audit resta registrata.
--
-- Come si usa:
--   · nella batteria (run.sh): il file gira dentro BEGIN/ROLLBACK come gli altri — zero residui;
--   · per la prova LIVE dell'endpoint report (commit reale, poi `curl`): applicare con
--       psql -v ON_ERROR_STOP=1 -f db/tests/fixture_report.sql
--     provare il report, poi pulire con la DELETE in fondo a «Pulizia» eseguita come postgres:
--       DELETE FROM trasi.richiesta  WHERE destinazione_nota LIKE 'FIXTURE-REPORT:%';
--       DELETE FROM trasi.evento     WHERE titolo LIKE 'FIXTURE-REPORT:%';
--       DELETE FROM trasi.opportunita WHERE titolo LIKE 'FIXTURE-REPORT:%';
--     e verificare `SELECT count(*) FROM trasi.v_scritture_senza_audit` = 0 (era 0 prima).
--
-- Idempotente: la pulizia preventiva dei marcatori (riga sotto) rende una seconda esecuzione
-- innocua anche senza transazione.
\set ON_ERROR_STOP on
\pset pager off

-- ---------------------------------------------------------------------------
-- 0. Pulizia preventiva (gira come l'utente della connessione: nella batteria è postgres,
--    nella prova live idem). Solo i marcatori di QUESTO file, mai righe reali.
-- ---------------------------------------------------------------------------
DELETE FROM trasi.richiesta   WHERE destinazione_nota LIKE 'FIXTURE-REPORT:%';
DELETE FROM trasi.evento      WHERE titolo LIKE 'FIXTURE-REPORT:%';
DELETE FROM trasi.opportunita WHERE titolo LIKE 'FIXTURE-REPORT:%';

-- ---------------------------------------------------------------------------
-- 1. `richiesta` — distribuzione per Casa/categoria/esito
--    Ogni blocco gira nel ruolo della Casa (mai superuser): è il modo in cui lo shim scrive,
--    e la RLS resta l'autorità. `destinazione_nota` porta il marcatore su TUTTE le righe (non
--    solo su `inviata_altrove`): è un campo libero e la pulizia lo riconosce con certezza.
-- ---------------------------------------------------------------------------

-- bozzano: la cella PROVA «≥5 visibile» (9 richieste orientamento/risolta) più 2 celle piccole
-- (lavoro/inviata_altrove = 3 → `<5`; abitare/non_trovata = 1 → `<5`).
SET LOCAL ROLE casa_bozzano;
INSERT INTO trasi.richiesta (casa_id, ts, categoria, esito, destinazione_id, destinazione_nota, fascia_eta, genere, provenienza)
SELECT c.id,
       (date_trunc('month', current_date)::date + (1 + g))::timestamptz + (g || ' hours')::interval AS ts,
       'orientamento', 'risolta', NULL, 'FIXTURE-REPORT:o1',
       '60-74'::text, 'donna'::text, 'italia'::text
  FROM trasi.casa c, generate_series(0, 8) g WHERE c.slug = 'bozzano';
INSERT INTO trasi.richiesta (casa_id, ts, categoria, esito, destinazione_id, destinazione_nota, fascia_eta, genere, provenienza)
SELECT c.id, date_trunc('month', current_date)::date + 2,
       'lavoro', 'inviata_altrove', l.id, 'FIXTURE-REPORT:o1',
       '30-44'::text, 'uomo'::text, 'extra_ue'::text
  FROM trasi.casa c, trasi.luogo l
 WHERE c.slug = 'bozzano' AND l.id = 21;                                   -- CAF ACLI La Rosa
INSERT INTO trasi.richiesta (casa_id, ts, categoria, esito, destinazione_id, destinazione_nota, fascia_eta, genere, provenienza)
SELECT c.id, date_trunc('month', current_date)::date + 2,
       'lavoro', 'inviata_altrove', l.id, 'FIXTURE-REPORT:o1',
       '30-44'::text, 'uomo'::text, 'extra_ue'::text
  FROM trasi.casa c, trasi.luogo l
 WHERE c.slug = 'bozzano' AND l.id = 22;                                   -- CAF CISL Perrino
INSERT INTO trasi.richiesta (casa_id, ts, categoria, esito, destinazione_id, destinazione_nota, fascia_eta, genere, provenienza)
SELECT c.id, date_trunc('month', current_date)::date + 2,
       'lavoro', 'inviata_altrove', l.id, 'FIXTURE-REPORT:o1',
       '30-44'::text, 'uomo'::text, 'extra_ue'::text
  FROM trasi.casa c, trasi.luogo l
 WHERE c.slug = 'bozzano' AND l.id = 19;                                   -- Regione Puglia
INSERT INTO trasi.richiesta (casa_id, ts, categoria, esito, destinazione_id, destinazione_nota, fascia_eta, genere, provenienza)
SELECT c.id, date_trunc('month', current_date)::date + 5,
       'abitare', 'non_trovata', NULL, 'FIXTURE-REPORT:o1',
       '45-59'::text, 'altro'::text, 'non_dichiarata'::text
  FROM trasi.casa c WHERE c.slug = 'bozzano';
RESET ROLE;

-- san-bao: una cella piccola (salute/risolta = 2 → `<5`) e una riga agosto per il confronto mesi
-- (fiscale_isee/rinviata, mese 2026-08 → non compare nel report di settembre).
SET LOCAL ROLE casa_sanbao;
INSERT INTO trasi.richiesta (casa_id, ts, categoria, esito, destinazione_id, destinazione_nota, fascia_eta, genere, provenienza)
SELECT c.id, date_trunc('month', current_date)::date + 3,
       'salute', 'risolta', NULL, 'FIXTURE-REPORT:o1',
       '75+'::text, 'donna'::text, 'italia'::text
  FROM trasi.casa c WHERE c.slug = 'san-bao';
INSERT INTO trasi.richiesta (casa_id, ts, categoria, esito, destinazione_id, destinazione_nota, fascia_eta, genere, provenienza)
SELECT c.id, date_trunc('month', current_date)::date + 3,
       'salute', 'risolta', NULL, 'FIXTURE-REPORT:o1',
       '60-74'::text, 'donna'::text, 'italia'::text
  FROM trasi.casa c WHERE c.slug = 'san-bao';
INSERT INTO trasi.richiesta (casa_id, ts, categoria, esito, destinazione_id, destinazione_nota, fascia_eta, genere, provenienza)
SELECT c.id,
       date_trunc('month', current_date)::date + 9 - interval '1 month',
       'fiscale_isee', 'rinviata', NULL, 'FIXTURE-REPORT:o1',
       '30-44'::text, 'non_dichiarato'::text, 'ue'::text
  FROM trasi.casa c WHERE c.slug = 'san-bao';
RESET ROLE;

-- altre 4 Case, una cella piccola ciascuna (per la mascheratura `<5` distribuita)
SET LOCAL ROLE casa_buscicchio;
INSERT INTO trasi.richiesta (casa_id, ts, categoria, esito, destinazione_id, destinazione_nota, fascia_eta, genere, provenienza)
SELECT c.id, date_trunc('month', current_date)::date + 4,
       'servizi_sociali', 'inviata_altrove', l.id, 'FIXTURE-REPORT:o1',
       '45-59'::text, 'uomo'::text, 'italia'::text
  FROM trasi.casa c, trasi.luogo l
 WHERE c.slug = 'buscicchio' AND l.id = 17;                                -- ASL distretto
INSERT INTO trasi.richiesta (casa_id, ts, categoria, esito, destinazione_id, destinazione_nota, fascia_eta, genere, provenienza)
SELECT c.id, date_trunc('month', current_date)::date + 4,
       'servizi_sociali', 'inviata_altrove', l.id, 'FIXTURE-REPORT:o1',
       '45-59'::text, 'uomo'::text, 'italia'::text
  FROM trasi.casa c, trasi.luogo l
 WHERE c.slug = 'buscicchio' AND l.id = 18;                                -- INPS
RESET ROLE;

SET LOCAL ROLE casa_tuturano;
INSERT INTO trasi.richiesta (casa_id, ts, categoria, esito, destinazione_id, destinazione_nota, fascia_eta, genere, provenienza)
SELECT c.id, date_trunc('month', current_date)::date + 6,
       'ascolto_solitudine', 'risolta', NULL, 'FIXTURE-REPORT:o1',
       '75+'::text, 'donna'::text, 'italia'::text
  FROM trasi.casa c WHERE c.slug = 'tuturano';
INSERT INTO trasi.richiesta (casa_id, ts, categoria, esito, destinazione_id, destinazione_nota, fascia_eta, genere, provenienza)
SELECT c.id, date_trunc('month', current_date)::date + 6,
       'ascolto_solitudine', 'risolta', NULL, 'FIXTURE-REPORT:o1',
       '60-74'::text, 'donna'::text, 'italia'::text
  FROM trasi.casa c WHERE c.slug = 'tuturano';
RESET ROLE;

SET LOCAL ROLE casa_pop;
INSERT INTO trasi.richiesta (casa_id, ts, categoria, esito, destinazione_id, destinazione_nota, fascia_eta, genere, provenienza)
SELECT c.id, date_trunc('month', current_date)::date + 1,
       'eventi_attivita', 'risolta', NULL, 'FIXTURE-REPORT:o1',
       '18-29'::text, 'altro'::text, 'non_dichiarata'::text
  FROM trasi.casa c WHERE c.slug = 'pop';
RESET ROLE;

SET LOCAL ROLE casa_molo12;
INSERT INTO trasi.richiesta (casa_id, ts, categoria, esito, destinazione_id, destinazione_nota, fascia_eta, genere, provenienza)
SELECT c.id, date_trunc('month', current_date)::date + 12 - interval '1 month',
       'interculturale', 'inviata_altrove', l.id, 'FIXTURE-REPORT:o1',
       '18-29'::text, 'donna'::text, 'extra_ue'::text
  FROM trasi.casa c, trasi.luogo l
 WHERE c.slug = 'molo12' AND l.id = 16;                                    -- URP Comune
RESET ROLE;

-- ---------------------------------------------------------------------------
-- 2. `evento` — 4 eventi futuri (v_confronto_case.eventi_futuri)
-- ---------------------------------------------------------------------------
SET LOCAL ROLE casa_sanbao;
INSERT INTO trasi.evento (casa_id, titolo, descrizione, inizio, fine, luogo_testo, affidabilita, fascia_eta)
SELECT c.id, 'FIXTURE-REPORT: laboratorio di cucina', 'Fixture di prova — evento futuro (report mensile)',
       now() + interval '7 days', now() + interval '7 days' + interval '2 hours', 'San Bao', 2, '18-29'
  FROM trasi.casa c WHERE c.slug = 'san-bao';
INSERT INTO trasi.evento (casa_id, titolo, descrizione, inizio, fine, luogo_testo, affidabilita)
SELECT c.id, 'FIXTURE-REPORT: cineforum', 'Fixture di prova — evento futuro (report mensile)',
       now() + interval '14 days', now() + interval '14 days' + interval '2 hours', 'San Bao', 3
  FROM trasi.casa c WHERE c.slug = 'san-bao';
RESET ROLE;

SET LOCAL ROLE casa_bozzano;
INSERT INTO trasi.evento (casa_id, titolo, descrizione, inizio, fine, luogo_testo, affidabilita)
SELECT c.id, 'FIXTURE-REPORT: tombola di quartiere', 'Fixture di prova — evento futuro (report mensile)',
       now() + interval '10 days', now() + interval '10 days' + interval '3 hours', 'Bozzano', 2
  FROM trasi.casa c WHERE c.slug = 'bozzano';
RESET ROLE;

SET LOCAL ROLE casa_tuturano;
INSERT INTO trasi.evento (casa_id, titolo, descrizione, inizio, fine, luogo_testo, affidabilita)
SELECT c.id, 'FIXTURE-REPORT: mercato contadino', 'Fixture di prova — evento futuro (report mensile)',
       now() + interval '21 days', now() + interval '21 days' + interval '4 hours', 'Tuturano', 2
  FROM trasi.casa c WHERE c.slug = 'tuturano';
RESET ROLE;

-- ---------------------------------------------------------------------------
-- 3. `opportunita` — 2 aperte (v_confronto_case.opportunita_aperte)
-- ---------------------------------------------------------------------------
SET LOCAL ROLE casa_sanbao;
INSERT INTO trasi.opportunita (casa_id, titolo, descrizione, categoria, scadenza, affidabilita)
SELECT c.id, 'FIXTURE-REPORT: bando volontari', 'Fixture di prova — opportunità aperta',
       'lavoro', current_date + 15, 2 FROM trasi.casa c WHERE c.slug = 'san-bao';
RESET ROLE;
SET LOCAL ROLE casa_bozzano;
INSERT INTO trasi.opportunita (casa_id, titolo, descrizione, categoria, scadenza, affidabilita)
SELECT c.id, 'FIXTURE-REPORT: corso di alfabetizzazione digitale', 'Fixture di prova — opportunità aperta',
       'formazione', current_date + 30, 2 FROM trasi.casa c WHERE c.slug = 'bozzano';
RESET ROLE;

-- ---------------------------------------------------------------------------
-- 4. Verifiche osservabili (le stesse celle che il report deve mostrare)
-- ---------------------------------------------------------------------------
DO $$
DECLARE
  n_bozzano_ori    integer;  -- cella ≥5: deve uscire come numero pieno
  n_bozzano_lav    integer;  -- cella 3: deve uscire come `<5`
  n_tuturano_ascol integer;  -- cella 2: deve uscire come `<5`
  v_bozzano_ori    text;
  v_bozzano_lav    text;
  v_tuturano_ascol text;
BEGIN
  SELECT count(*) INTO n_bozzano_ori FROM trasi.v_report_mensile
   WHERE casa_slug='bozzano' AND categoria='orientamento' AND esito='risolta' AND mese=date_trunc('month', current_date)::date;
  SELECT count(*) INTO n_bozzano_lav FROM trasi.v_report_mensile
   WHERE casa_slug='bozzano' AND categoria='lavoro' AND esito='inviata_altrove' AND mese=date_trunc('month', current_date)::date;
  SELECT count(*) INTO n_tuturano_ascol FROM trasi.v_report_mensile
   WHERE casa_slug='tuturano' AND categoria='ascolto_solitudine' AND esito='risolta' AND mese=date_trunc('month', current_date)::date;

  SELECT n_label INTO v_bozzano_ori FROM trasi.v_report_mensile
   WHERE casa_slug='bozzano' AND categoria='orientamento' AND esito='risolta' AND mese=date_trunc('month', current_date)::date;
  SELECT n_label INTO v_bozzano_lav FROM trasi.v_report_mensile
   WHERE casa_slug='bozzano' AND categoria='lavoro' AND esito='inviata_altrove' AND mese=date_trunc('month', current_date)::date;
  SELECT n_label INTO v_tuturano_ascol FROM trasi.v_report_mensile
   WHERE casa_slug='tuturano' AND categoria='ascolto_solitudine' AND esito='risolta' AND mese=date_trunc('month', current_date)::date;

  -- La cella orientamento/risolta di bozzano ha 9 righe del fixture PIÙ le eventuali reali: deve
  -- essere ≥ 5 (numero pieno, mai `<5`). Le due celle piccole devono essere `<5` (n NULL).
  IF v_bozzano_ori = '<5' OR v_bozzano_ori IS NULL OR v_bozzano_ori = '—' THEN
    RAISE EXCEPTION 'FAIL F01 — cella bozzano/orientamento/risolta: atteso numero pieno ≥5, trovato %', v_bozzano_ori;
  END IF;
  IF v_bozzano_lav IS DISTINCT FROM '<5' THEN
    RAISE EXCEPTION 'FAIL F02 — cella bozzano/lavoro/inviata_altrove: atteso <5, trovato %', coalesce(v_bozzano_lav,'NULL');
  END IF;
  IF v_tuturano_ascol IS DISTINCT FROM '<5' THEN
    RAISE EXCEPTION 'FAIL F03 — cella tuturano/ascolto_solitudine/risolta: atteso <5, trovato %', coalesce(v_tuturano_ascol,'NULL');
  END IF;
  RAISE NOTICE 'PASS F01/F02/F03 — fixture: bozzano orientamento=% (pieno), bozzano lavoro=% , tuturano ascolto=% ()',
    v_bozzano_ori, v_bozzano_lav, v_tuturano_ascol;
END $$;

-- Il confronto fra mesi: settembre ha i numeri (righe 2026-09), agosto ha 2 righe sole (fixture).
DO $$
DECLARE v_ago integer;
BEGIN
  SELECT count(*) INTO v_ago FROM trasi.v_report_mensile
   WHERE mese = date_trunc('month', current_date)::date - interval '1 month';
  IF v_ago < 2 THEN RAISE EXCEPTION 'FAIL F04 — agosto: attese ≥2 celle di fixture, trovate %', v_ago; END IF;
  RAISE NOTICE 'PASS F04 — il mese precedente è nel report (celle fixture: %)', v_ago;
END $$;

-- Dopo il fixture, la contabilità di V4 non deve vedere mutazioni senza audit.
-- NOTA: si controllano SOLO `evento`/`opportunita` (le entità che questo file scrive e che la
-- vista traccia): un zero assoluto sarebbe fragile su un DB condiviso, dove un altro worktree
-- può legittimamente scrivere (es. `UPDATE trasi.casa` come postgres durante un restore —
-- misurato il 2026-09-17: una riga `casa|5|postgres` presente prima ancora del fixture).
DO $$
DECLARE v_sospette integer;
BEGIN
  SELECT count(*) INTO v_sospette FROM trasi.v_scritture_senza_audit
   WHERE entita IN ('evento', 'opportunita') AND ts > now() - interval '1 hour';
  IF v_sospette <> 0 THEN
    RAISE EXCEPTION 'FAIL F05 — % scritture senza audit su evento/opportunità dopo il fixture (la contabilità di V4 è sporca)', v_sospette;
  END IF;
  RAISE NOTICE 'PASS F05 — v_scritture_senza_audit: nessuna riga su evento/opportunità dopo il fixture';
END $$;
