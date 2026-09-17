-- Trasi — db/011_seed_fonti.sql
-- Allow-list delle fonti (§3): 9 fonti attive + 10 siti degli ETS della rete disattivati.
--
-- `fonte` è configurazione, non memoria applicativa: si scrive con una riga e la amplia il TI senza deploy
-- (§3, §11). A runtime la scrive solo `ti`; qui è caricamento iniziale come trasi_owner.
-- Invariante verificata da tests/run.sh: ogni fonte ATTIVA ha livello_fiducia >= p_int('fiducia_min_esterna'),
-- altrimenti la fonte sarebbe in allow-list e insieme scartata a ogni risposta (§7.2, F1).
--
-- [ASSUNZIONE] Gli URL dei siti istituzionali sono quelli ufficiali noti; i feed iCal delle Case non
-- esistono ancora (li configura il TI) → `url` NULL per la fonte Calendar. I 10 siti ETS restano
-- `attiva=false` finché il TI non li verifica (§3: «Il TI amplia»).
\set ON_ERROR_STOP on
\set VERBOSITY terse

SET ROLE trasi_owner;
SET search_path = trasi, public, pg_temp;

INSERT INTO trasi.fonte (nome, url, tipo_accesso, autorita, livello_fiducia, attiva) VALUES
  -- Memoria della rete: la fonte di tutto ciò che è già verificato (badge KB)
  ('Rete-kb-3', NULL, 'kb', 'Rete delle Case di Quartiere di Brindisi', 3, true),
  -- Documenti della rete su Drive: FUORI dal MVP (decisione 17/09/2026). Il consent Google resta in
  -- «Testing» e il canale non ha consumatori: la riga resta nel seed come configurazione dichiarata ma
  -- **inattiva**, così un deploy pulito non accende un canale che nessuno usa. Nessun invariante la
  -- presuppone (O07 verifica le fonti attive, non il totale).
  ('Google Drive-3', 'https://drive.google.com', 'drive', 'Rete delle Case di Quartiere di Brindisi', 3, false),
  -- Calendari delle Case: unica scrittura automatica diretta ammessa su `evento` (§8 F4)
  ('Google Calendar-ical-2', NULL, 'ical', 'Calendari ufficiali delle Case', 2, true),
  -- POI e orari esterni (§3; endpoint verificato in B0: overpass.openstreetmap.fr risponde con UA identificativo)
  ('OpenStreetMap/Overpass-2', 'https://overpass.openstreetmap.fr/api/interpreter', 'osm_overpass',
   'OpenStreetMap contributors (ODbL)', 2, true),
  ('Comune di Brindisi-3', 'https://www.comune.brindisi.it', 'web', 'Comune di Brindisi', 3, true),
  ('ASL Brindisi-3', 'https://www.asl.brindisi.it', 'web', 'ASL della Provincia di Brindisi', 3, true),
  ('INPS-3', 'https://www.inps.it', 'web', 'INPS', 3, true),
  ('Regione Puglia-3', 'https://www.regione.puglia.it', 'web', 'Regione Puglia', 3, true),
  ('Questura di Brindisi-3', 'https://questure.poliziadistato.it/Brindisi', 'web',
   'Ministero dell''Interno — Polizia di Stato', 3, true)
ON CONFLICT (nome) DO UPDATE
  SET url = EXCLUDED.url, tipo_accesso = EXCLUDED.tipo_accesso, autorita = EXCLUDED.autorita,
      livello_fiducia = EXCLUDED.livello_fiducia, attiva = EXCLUDED.attiva;

-- 10 siti degli ETS della rete: candidati, non ancora in allow-list → attiva = false, fiducia 1.
INSERT INTO trasi.fonte (nome, url, tipo_accesso, autorita, livello_fiducia, attiva)
SELECT 'ETS: ' || c.nome, NULL, 'web', COALESCE(c.ente_gestore, 'ETS della rete'), 1, false
FROM trasi.casa c
ORDER BY c.slug
ON CONFLICT (nome) DO UPDATE
  SET autorita = EXCLUDED.autorita, tipo_accesso = EXCLUDED.tipo_accesso,
      livello_fiducia = EXCLUDED.livello_fiducia, attiva = EXCLUDED.attiva;

-- 2 fonti per i CAF di riferimento US-01 (ACLI/CISL): i luoghi del seed (db/012) le citano, ma
-- restano `attiva=false` finché il TI non le verifica — è lo scenario «badge KB affidabilità 1 e
-- proposta di verifica all'operatore» previsto dal piano (App. C, CAF La Rosa/Perrino).
INSERT INTO trasi.fonte (nome, url, tipo_accesso, autorita, livello_fiducia, attiva) VALUES
  ('CAF ACLI Brindisi', 'https://www.acli.it', 'web', 'ACLI — patronato', 1, false),
  ('CAF CISL Brindisi', 'https://www.cisl.it', 'web', 'CISL — patronato', 1, false)
ON CONFLICT (nome) DO UPDATE
  SET url = EXCLUDED.url, tipo_accesso = EXCLUDED.tipo_accesso, autorita = EXCLUDED.autorita,
      livello_fiducia = EXCLUDED.livello_fiducia, attiva = EXCLUDED.attiva;

-- Fonti per i link che il connettore `web` di Onyx non può indicizzare (`.orca/drops/link_scartati.json`,
-- 16/09/2026): API JSON e file, non pagine HTML. Due strade, due `tipo_accesso`:
--   * `api`  — interrogate **on-demand** dallo shim: i tre portali CKAN da `cerca_opendata`/`leggi_dataset`
--              (la base API è `url` + `/api/3/action/...`), Nominatim dalla geocodifica di `vicino_a`
--              (parametro `indirizzo`). La riga è l'allow-list: spenta la riga, lo shim non la interroga.
--              Lo shim riconosce Nominatim per host (= `NOMINATIM_URL`); ogni altra riga `api` è un portale CKAN.
--   * `http` — file scaricati e indicizzati dal flusso settimanale `flussi/fonti_documenti.py` (ZIP ISTAT,
--              CSV di Open Data Puglia, PDF della Procura). Il flusso lascia una riga in `fonte_run`, così la
--              coerenza F6 vede se la fonte tace.
-- La fiducia segue la convenzione del suffisso: 3 per gli enti pubblici titolari del dato, 2 per IPRES e
-- per OpenStreetMap (come la riga Overpass). Tutte >= fiducia_min_esterna (invariante O07).
INSERT INTO trasi.fonte (nome, url, tipo_accesso, autorita, livello_fiducia, attiva) VALUES
  ('Open Data Puglia-3', 'https://dati.puglia.it/ckan', 'api', 'Regione Puglia — Open Data', 3, true),
  ('dati.gov.it-3', 'https://www.dati.gov.it/opendata', 'api',
   'dati.gov.it — Catalogo nazionale dei dati aperti (AgID)', 3, true),
  ('IPRES Open Data-2', 'http://www.opendataipres.it', 'api',
   'IPRES — Istituto Pugliese di Ricerche Economiche e Sociali', 2, true),
  ('Nominatim-2', 'https://nominatim.openstreetmap.org', 'api',
   'OpenStreetMap contributors (ODbL) — Nominatim', 2, true),
  ('ISTAT-3', 'https://demo.istat.it', 'http', 'ISTAT', 3, true),
  ('Procura di Brindisi-3', 'https://procura-brindisi.giustizia.it', 'http',
   'Procura della Repubblica di Brindisi', 3, true)
ON CONFLICT (nome) DO UPDATE
  SET url = EXCLUDED.url, tipo_accesso = EXCLUDED.tipo_accesso, autorita = EXCLUDED.autorita,
      livello_fiducia = EXCLUDED.livello_fiducia, attiva = EXCLUDED.attiva;

RESET ROLE;
