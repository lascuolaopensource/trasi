-- Trasi — flussi/fixtures/alert.sql
--
-- Fixture del criterio B4-FLW-09 (§8 F6): **1 proposta di San Bao in attesa da 8 giorni + 1 scaduta**
-- → `alert.py` → **1 email al gestore di San Bao** («1 in attesa · 1 scaduta») e **0 email a Bozzano**.
--
-- Il caso da 8 giorni richiede di invecchiare `proposto_ts`. Il campo non è grantato in INSERT a
-- nessun ruolo client (lo scrive il `DEFAULT now()`): nessuna fixture può far invecchiare una proposta
-- attraverso il percorso di produzione, perché **il tempo che passa non ha un percorso applicativo**.
-- L'invecchiamento è quindi un passo come `trasi_owner` su righe marcate `B4FLW09:`, ed è una
-- simulazione del tempo, non una scrittura di dominio.
--
-- La proposta di San Bao è `modifica_scheda` → `approvatore_ruolo='gestore'` (regola §11) → decide il
-- gestore di San Bao. La scaduta è di Bozzano: la sua presenza prova che l'alert *non* va a chi non
-- deve deciderla — il criterio «0 email Bozzano» è quello che distingue un recapito corretto da un
-- broadcast a tutte le Case.
--
-- Idempotente: cancella prima le proprie righe (contrassegno `B4FLW09:`).
--
-- Uso:  psql … -f flussi/fixtures/alert.sql
\set ON_ERROR_STOP on
\set VERBOSITY terse

-- ---------------------------------------------------------------------------
-- 0. Pulizia delle esecuzioni precedenti
-- ---------------------------------------------------------------------------
SET ROLE trasi_owner;
SET search_path = trasi, public, pg_temp;
DELETE FROM trasi.audit WHERE proposta_id IN
  (SELECT id FROM trasi.proposta WHERE motivazione LIKE 'B4FLW09:%');
DELETE FROM trasi.proposta WHERE motivazione LIKE 'B4FLW09:%';
RESET ROLE;

-- ---------------------------------------------------------------------------
-- 1. La proposta di San Bao (gestore, 8 giorni di attesa) e quella di Bozzano (scaduta)
--    Proposte da `rete`: chi decide (i due gestori) non è chi propone, quindi sono decidibili.
-- ---------------------------------------------------------------------------
SET ROLE rete;
SET search_path = trasi, public, pg_temp;

INSERT INTO trasi.proposta (origine, tipo, entita, casa_id, payload, motivazione)
SELECT 'manuale', 'modifica_scheda', 'scheda_servizio', c.id,
       jsonb_build_object('descrizione', 'Sportello aggiornato (fixture B4FLW09)'),
       'B4FLW09: proposta di San Bao in attesa'
  FROM trasi.casa c WHERE c.slug = 'san-bao';

INSERT INTO trasi.proposta (origine, tipo, entita, casa_id, payload, motivazione, scade_il)
SELECT 'manuale', 'modifica_scheda', 'scheda_servizio', c.id,
       jsonb_build_object('descrizione', 'Sportello aggiornato (fixture B4FLW09)'),
       'B4FLW09: proposta di Bozzano scaduta',
       current_date - 1
  FROM trasi.casa c WHERE c.slug = 'bozzano';

RESET ROLE;

-- ---------------------------------------------------------------------------
-- 2. Invecchiamento: 8 giorni di attesa per la proposta di San Bao (simulazione del tempo).
--    La scaduta di Bozzano resta con `scade_il` di ieri, così `scadi_proposte()` (05:00) l'ha
--    marcata `scaduta` e l'alert la vede nella finestra delle 24 h.
-- ---------------------------------------------------------------------------
SET ROLE trasi_owner;
SET search_path = trasi, public, pg_temp;
UPDATE trasi.proposta SET proposto_ts = now() - interval '8 days'
 WHERE motivazione = 'B4FLW09: proposta di San Bao in attesa';
RESET ROLE;

-- La scaduta si marca con la stessa via della produzione: la funzione del flusso F9.
SET SESSION AUTHORIZATION automazioni;
SELECT trasi.scadi_proposte() AS marcate_scadute;
RESET SESSION AUTHORIZATION;

-- ---------------------------------------------------------------------------
-- 3. Lo stato della fixture, per chi la esegue
-- ---------------------------------------------------------------------------
SET ROLE trasi_owner;
SET search_path = trasi, public, pg_temp;

SELECT p.voce, p.casa_slug, p.proposta_id, p.giorni, p.approvatore_ruolo,
       p.destinatario, p.destinatario_ruolo
  FROM trasi.v_flusso_alert_proposte p
 WHERE p.proposta_id IN (SELECT id FROM trasi.proposta WHERE motivazione LIKE 'B4FLW09:%')
 ORDER BY p.voce, p.casa_slug;
RESET ROLE;
