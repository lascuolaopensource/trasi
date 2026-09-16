-- Trasi — db/004_views.sql
-- Viste di lettura per Metabase (P2), per la Home (riga «Oggi») e per l'export KB (F3).
--
-- Perché security_invoker = false (owner `trasi_owner`): `metabase_ro` per matrice NON ha SELECT su
-- `richiesta` e `proposta`; le viste di reporting devono poterle aggregare senza concedergliele in chiaro.
-- Il rischio «la vista bypassa l'intento» è neutralizzato così:
--   * le viste espongono SOLO dati già pubblici nella rete (case, luoghi, eventi, opportunità, schede)
--     oppure aggregati/ mascherati — mai righe di `richiesta`, mai identità;
--   * ogni conteggio che possa re-identificare una persona passa da trasi.k_anon(): sotto
--     p_int('k_anonimato') il numero grezzo è NULL e resta solo n_label («<5», «—» a zero);
--   * `v_proposte_aperte` esclude `proposto_da`/`approvato_da` (minimizzazione, §12);
--   * le viste di sola rete sono filtrate a elementi validi (chiusi/scaduti esclusi).
-- Verifica dell'intento (report B1): nessuna vista nomina `richiesta.id`, `richiesta.ts` accoppiato a
-- destinazione, né alcuna colonna di identità.
--
-- [ASSUNZIONE] Il DDL v1.1 delle viste non esiste nel repo: le colonne sono ricostruite dai consumatori
-- dichiarati (plan.md B4-FLW-04, B5-DSH-04/06, shim/openapi.yaml `RispostaOggi`).
\set ON_ERROR_STOP on
\set VERBOSITY terse

SET ROLE trasi_owner;
SET search_path = trasi, public, pg_temp;

-- ===========================================================================
-- Helper: mascheratura k-anonimo e resa degli orari
-- ===========================================================================
-- Un'unica funzione per la regola «mai esporre il numero grezzo sotto soglia»: se la regola vivesse
-- duplicata in ogni vista, prima o poi una la dimenticherebbe.
CREATE OR REPLACE FUNCTION trasi.k_anon(p_n bigint) RETURNS TABLE (n integer, n_label text)
LANGUAGE sql STABLE SET search_path = '' AS $$
  SELECT CASE WHEN p_n >= COALESCE(trasi.p_int('k_anonimato'), 5) THEN p_n::integer END,
         CASE WHEN p_n = 0 THEN '—'
              WHEN p_n < COALESCE(trasi.p_int('k_anonimato'), 5) THEN '<' || COALESCE(trasi.p_int('k_anonimato'), 5)
              ELSE p_n::text END
$$;

-- Orari jsonb → testo leggibile («lun 09:00-13:00 · sab 10:00-12:00», «dom chiuso»).
-- Chiavi `lun`…`dom`; elenco vuoto = chiuso; fasce in coppie apertura/chiusura.
CREATE OR REPLACE FUNCTION trasi.orari_testo(p_orari jsonb) RETURNS text
LANGUAGE plpgsql IMMUTABLE SET search_path = '' AS $$
DECLARE
  giorni text[] := ARRAY['lun','mar','mer','gio','ven','sab','dom'];
  g text; fasce jsonb; pezzi text[]; i int; parti text[] := '{}';
BEGIN
  IF p_orari IS NULL THEN RETURN NULL; END IF;
  FOREACH g IN ARRAY giorni LOOP
    IF NOT (p_orari ? g) THEN CONTINUE; END IF;
    fasce := p_orari -> g;
    IF jsonb_typeof(fasce) <> 'array' OR jsonb_array_length(fasce) = 0 THEN
      parti := parti || (g || ' chiuso');
      CONTINUE;
    END IF;
    pezzi := '{}'; i := 0;
    WHILE i < jsonb_array_length(fasce) LOOP
      pezzi := pezzi || (fasce->>i || '-' || COALESCE(fasce->>(i+1), '?'));
      i := i + 2;
    END LOOP;
    parti := parti || (g || ' ' || array_to_string(pezzi, ' '));
  END LOOP;
  RETURN NULLIF(array_to_string(parti, ' · '), '');
END $$;

-- ===========================================================================
-- V1 · v_scaduti — opportunità con scadenza passata (alert «scaduti», US-06)
-- ===========================================================================
DROP VIEW IF EXISTS trasi.v_scaduti;
CREATE VIEW trasi.v_scaduti AS
SELECT o.id, o.casa_id, c.slug AS casa_slug, c.nome AS casa_nome,
       o.titolo, o.categoria, o.scadenza,
       (current_date - o.scadenza) AS giorni_da_scadenza,
       f.nome AS fonte_nome, o.url, o.affidabilita
FROM trasi.opportunita o
JOIN trasi.casa c ON c.id = o.casa_id
LEFT JOIN trasi.fonte f ON f.id = o.fonte_id
WHERE o.scadenza IS NOT NULL AND o.scadenza < current_date;

-- ===========================================================================
-- V2 · v_in_scadenza — opportunità e schede che scadono entro [P] gg_preavviso_scadenza
-- ===========================================================================
DROP VIEW IF EXISTS trasi.v_in_scadenza;
CREATE VIEW trasi.v_in_scadenza AS
SELECT 'opportunita'::text AS voce, o.id, o.casa_id, c.slug AS casa_slug, c.nome AS casa_nome,
       o.titolo, o.scadenza, (o.scadenza - current_date) AS giorni_rimanenti,
       f.nome AS fonte_nome, o.url
FROM trasi.opportunita o
JOIN trasi.casa c ON c.id = o.casa_id
LEFT JOIN trasi.fonte f ON f.id = o.fonte_id
WHERE o.scadenza IS NOT NULL
  AND o.scadenza >= current_date
  AND o.scadenza <= current_date + COALESCE(trasi.p_int('gg_preavviso_scadenza'), 15)
UNION ALL
SELECT 'scheda'::text AS voce, s.id, s.casa_id, c.slug AS casa_slug, c.nome AS casa_nome,
       s.titolo, s.scadenza, (s.scadenza - current_date) AS giorni_rimanenti,
       f.nome AS fonte_nome, s.url
FROM trasi.scheda_servizio s
JOIN trasi.casa c ON c.id = s.casa_id
LEFT JOIN trasi.fonte f ON f.id = s.fonte_id
WHERE s.scadenza IS NOT NULL
  AND s.scadenza >= current_date
  AND s.scadenza <= current_date + COALESCE(trasi.p_int('gg_preavviso_scadenza'), 15);

-- ===========================================================================
-- V3 · v_senza_risposta — colloqui chiusi con esito «non_trovata» (US-02, alert)
-- Nessun campo del cittadino esiste in `richiesta` (V5): qui escono solo categoria, data e Casa.
-- ===========================================================================
DROP VIEW IF EXISTS trasi.v_senza_risposta;
CREATE VIEW trasi.v_senza_risposta AS
SELECT r.id, r.casa_id, c.slug AS casa_slug, c.nome AS casa_nome,
       r.ts, r.ts::date AS data, r.categoria,
       (current_date - r.ts::date) AS giorni_da_registrazione
FROM trasi.richiesta r
JOIN trasi.casa c ON c.id = r.casa_id
WHERE r.esito = 'non_trovata';

-- ===========================================================================
-- V4 · v_kb_export — alimenta l'export KB (F3/B4-FLW-04) e la cartella kb_export/
-- doc_id = 'trasi:<entita>:<id>' rende l'upsert sull'Ingestion API idempotente.
-- Solo elementi validi: luoghi chiusi, eventi annullati o passati, schede e opportunità scadute esclusi.
-- ===========================================================================
DROP VIEW IF EXISTS trasi.v_kb_export;
CREATE VIEW trasi.v_kb_export AS
SELECT 'trasi:luogo:' || l.id AS doc_id, 'luogo'::text AS entita, l.id,
       l.nome AS titolo,
       NULLIF(concat_ws(E'\n', l.nome || ' (' || l.tipo || ')', l.indirizzo,
                        trasi.orari_testo(l.orari), l.descrizione, l.note_accesso), '') AS testo,
       COALESCE(f.nome, 'rete') AS fonte_nome, COALESCE(l.url, f.url) AS url,
       l.data_aggiornamento, l.affidabilita, c.nome AS casa_nome
-- Nota: `fiducia_min_esterna` NON si applica qui. Quella soglia riguarda le fonti esterne interrogate
-- a runtime (§7.2); i luoghi in memoria restano esportati anche con affidabilità 1 (es. i 2 CAF da
-- verificare: la chat li mostra con badge «affidabilità 1», US-01).
FROM trasi.luogo l
LEFT JOIN trasi.fonte f ON f.id = l.fonte_id
LEFT JOIN trasi.casa c ON c.id = l.casa_id
WHERE l.chiuso_il IS NULL
UNION ALL
SELECT 'trasi:casa_quartiere:' || c.id, 'casa_quartiere', c.id, c.nome,
       NULLIF(concat_ws(E'\n', c.nome || ' — Casa di Quartiere', c.zona, c.ente_gestore,
                        trasi.orari_testo(c.orari),
                        CASE WHEN c.orari_provvisori THEN 'orari in via di definizione' END), ''),
       COALESCE((SELECT f.nome FROM trasi.fonte f WHERE f.tipo_accesso = 'kb'
                 ORDER BY f.livello_fiducia DESC, f.id LIMIT 1), 'rete'),
       NULL, c.creato_ts::date, 3, c.nome
FROM trasi.casa c
UNION ALL
SELECT 'trasi:scheda_servizio:' || s.id, 'scheda_servizio', s.id, s.titolo,
       NULLIF(concat_ws(E'\n', s.titolo, s.descrizione, trasi.orari_testo(s.orari)), ''),
       COALESCE(f.nome, 'rete'), s.url, COALESCE(s.validata_il, s.creato_ts::date),
       COALESCE(s.affidabilita, 3), c.nome
FROM trasi.scheda_servizio s
JOIN trasi.casa c ON c.id = s.casa_id
LEFT JOIN trasi.fonte f ON f.id = s.fonte_id
WHERE s.scadenza IS NULL OR s.scadenza >= current_date
UNION ALL
SELECT 'trasi:evento:' || e.id, 'evento', e.id, e.titolo,
       NULLIF(concat_ws(E'\n', e.titolo,
                        to_char(e.inizio, 'DD/MM/YYYY HH24:MI')
                          || CASE WHEN e.fine IS NOT NULL THEN '–' || to_char(e.fine, 'HH24:MI') ELSE '' END,
                        e.luogo_testo, e.descrizione), ''),
       COALESCE(f.nome, 'calendario della Casa'), COALESCE(e.url, f.url),
       e.inizio::date, COALESCE(e.affidabilita, 2), c.nome
FROM trasi.evento e
JOIN trasi.casa c ON c.id = e.casa_id
LEFT JOIN trasi.fonte f ON f.id = e.fonte_id
WHERE e.annullato = false AND COALESCE(e.fine, e.inizio) >= now()
UNION ALL
SELECT 'trasi:opportunita:' || o.id, 'opportunita', o.id, o.titolo,
       NULLIF(concat_ws(E'\n', o.titolo,
                        CASE WHEN o.scadenza IS NOT NULL THEN 'scadenza ' || to_char(o.scadenza, 'DD/MM/YYYY') END,
                        o.descrizione), ''),
       COALESCE(f.nome, 'rete'), o.url, o.creato_ts::date, COALESCE(o.affidabilita, 3), c.nome
FROM trasi.opportunita o
JOIN trasi.casa c ON c.id = o.casa_id
LEFT JOIN trasi.fonte f ON f.id = o.fonte_id
WHERE o.scadenza IS NULL OR o.scadenza >= current_date;

-- ===========================================================================
-- V5 · v_destinazioni — dove sono state indirizzate le persone, per Casa e destinazione.
-- k-anonimato: n NULL e n_label «<5» sotto soglia (tooltip mappa, B5-DSH-06); 0 → «—».
-- ===========================================================================
DROP VIEW IF EXISTS trasi.v_destinazioni;
CREATE VIEW trasi.v_destinazioni AS
SELECT r.casa_id, c.slug AS casa_slug, c.nome AS casa_nome,
       r.destinazione_id, COALESCE(l.nome, r.destinazione_nota) AS destinazione,
       l.tipo AS destinazione_tipo, COALESCE(l.casa_id = r.casa_id, false) AS interna_alla_casa,
       a.n, a.n_label, r.ultima_ts
FROM (
  SELECT casa_id, destinazione_id, min(destinazione_nota) AS destinazione_nota,
         count(*) AS cnt, max(ts) AS ultima_ts
  FROM trasi.richiesta
  WHERE esito = 'inviata_altrove'
  GROUP BY casa_id, destinazione_id
) r
JOIN trasi.casa c ON c.id = r.casa_id
LEFT JOIN trasi.luogo l ON l.id = r.destinazione_id
CROSS JOIN LATERAL trasi.k_anon(r.cnt) a;

-- ===========================================================================
-- V6 · v_oggi_casa — riga «Oggi» della Home e risposta dell'endpoint `oggi`.
-- Una riga per Casa: la vista non è filtrata per ruolo (owner-rights); il consumatore filtra su slug/id.
-- ===========================================================================
DROP VIEW IF EXISTS trasi.v_oggi_casa;
CREATE VIEW trasi.v_oggi_casa AS
SELECT c.id AS casa_id, c.slug, c.nome, current_date AS data,
       COALESCE(ev.n, 0)::integer AS eventi,
       COALESCE(sc.n, 0)::integer AS schede_in_scadenza,
       COALESCE(pr.n, 0)::integer AS proposte,
       format('Oggi a %s: %s %s · %s %s · %s %s',
              c.nome,
              COALESCE(ev.n,0), CASE WHEN COALESCE(ev.n,0) = 1 THEN 'evento' ELSE 'eventi' END,
              COALESCE(sc.n,0), CASE WHEN COALESCE(sc.n,0) = 1 THEN 'scheda in scadenza' ELSE 'schede in scadenza' END,
              COALESCE(pr.n,0), CASE WHEN COALESCE(pr.n,0) = 1 THEN 'proposta' ELSE 'proposte' END) AS testo
FROM trasi.casa c
LEFT JOIN LATERAL (
  SELECT count(*) AS n FROM trasi.evento e
  WHERE e.casa_id = c.id AND e.annullato = false AND e.inizio::date = current_date
) ev ON true
LEFT JOIN LATERAL (
  SELECT count(*) AS n FROM trasi.scheda_servizio s
  WHERE s.casa_id = c.id AND s.scadenza IS NOT NULL
    AND s.scadenza <= current_date + COALESCE(trasi.p_int('gg_preavviso_scadenza'), 15)
) sc ON true
LEFT JOIN LATERAL (
  SELECT count(*) AS n FROM trasi.proposta p
  WHERE p.casa_id = c.id AND p.stato = 'proposta'
) pr ON true;

-- ===========================================================================
-- V7 · v_mappa_case — pin delle 10 Case; lat/lon numerici (Metabase non usa geography) + raggio in tooltip.
-- ===========================================================================
DROP VIEW IF EXISTS trasi.v_mappa_case;
CREATE VIEW trasi.v_mappa_case AS
SELECT c.id, c.slug, c.nome, c.zona, c.ente_gestore,
       round(st_y(c.geom::geometry)::numeric, 5) AS lat,
       round(st_x(c.geom::geometry)::numeric, 5) AS lon,
       c.raggio_m,
       COALESCE(c.raggio_m, trasi.p_int('raggio_vicinanza_m')) AS raggio_m_eff,
       c.geom_qualita, c.da_validare, c.orari_provvisori,
       trasi.orari_testo(c.orari) AS orari_testo,
       c.email_digest IS NOT NULL AS ha_email_digest
FROM trasi.casa c;

-- ===========================================================================
-- V8 · v_mappa_luoghi — luoghi validi con Casa, fonte e affidabilità.
-- ===========================================================================
DROP VIEW IF EXISTS trasi.v_mappa_luoghi;
CREATE VIEW trasi.v_mappa_luoghi AS
SELECT l.id, l.nome, l.tipo, l.indirizzo,
       round(st_y(l.geom::geometry)::numeric, 5) AS lat,
       round(st_x(l.geom::geometry)::numeric, 5) AS lon,
       l.casa_id, c.slug AS casa_slug,
       l.ext_ref, l.chiuso_il, trasi.orari_testo(l.orari) AS orari_testo,
       f.nome AS fonte_nome, f.tipo_accesso, l.affidabilita, l.data_aggiornamento, l.url
FROM trasi.luogo l
LEFT JOIN trasi.casa c ON c.id = l.casa_id
LEFT JOIN trasi.fonte f ON f.id = l.fonte_id
WHERE l.chiuso_il IS NULL;

-- ===========================================================================
-- V8b · v_mappa_luoghi_vicini — luoghi validi con la distanza dalla propria Casa (bar interno di Bozzano).
-- ===========================================================================
DROP VIEW IF EXISTS trasi.v_mappa_luoghi_vicini;
CREATE VIEW trasi.v_mappa_luoghi_vicini AS
SELECT l.id, l.nome, l.tipo, l.casa_id, c.slug AS casa_slug, c.nome AS casa_nome,
       round(st_distance(l.geom, c.geom)::numeric, 1) AS distanza_m,
       (st_distance(l.geom, c.geom) <= 50) AS entro_50m
FROM trasi.luogo l
JOIN trasi.casa c ON c.id = l.casa_id
WHERE l.chiuso_il IS NULL AND l.geom IS NOT NULL AND c.geom IS NOT NULL;

-- ===========================================================================
-- V9 · v_proposte_aperte — coda delle proposte in attesa, per Casa.
-- Minimizzazione (§12): `proposto_da` e `approvato_da` NON sono esposti.
-- ===========================================================================
DROP VIEW IF EXISTS trasi.v_proposte_aperte;
CREATE VIEW trasi.v_proposte_aperte AS
SELECT p.id, p.origine, p.tipo, p.entita, p.entita_id,
       p.casa_id, c.slug AS casa_slug, c.nome AS casa_nome,
       p.fonte_id, f.nome AS fonte_nome,
       p.motivazione, p.stato, p.approvatore_ruolo,
       p.proposto_ts, p.scade_il,
       (current_date - p.proposto_ts::date) AS giorni_in_attesa,
       LEFT(p.payload::text, 200) AS payload_sintesi
FROM trasi.proposta p
LEFT JOIN trasi.casa c ON c.id = p.casa_id
LEFT JOIN trasi.fonte f ON f.id = p.fonte_id
WHERE p.stato = 'proposta';

-- ===========================================================================
-- V10 · v_report_mensile — richieste per Casa, mese, categoria ed esito, con k-anonimato.
-- `n` è NULL sotto soglia (mai il numero grezzo); `n_label` è «—» a zero, «<5» sotto soglia.
-- ===========================================================================
DROP VIEW IF EXISTS trasi.v_report_mensile;
CREATE VIEW trasi.v_report_mensile AS
SELECT r.mese,
       r.casa_id, c.slug AS casa_slug, c.nome AS casa_nome,
       r.categoria, r.esito, r.esito = 'inviata_altrove' AS con_destinazione,
       a.n, a.n_label
FROM (
  SELECT casa_id, categoria, esito, date_trunc('month', ts) AS mese, count(*) AS cnt
  FROM trasi.richiesta
  GROUP BY casa_id, categoria, esito, date_trunc('month', ts)
) r
JOIN trasi.casa c ON c.id = r.casa_id
CROSS JOIN LATERAL trasi.k_anon(r.cnt) a;

-- ===========================================================================
-- V11 · v_confronto_case — un indicatore per Casa, con k-anonimato sui conteggi di richieste.
-- I conteggi di RICHIESTE escono SOLO mascherati: `*_grezzo` non esiste perché una vista è
-- leggibile da metabase_ro e da ogni ruolo (GRANT SELECT sotto). Esporre il grezzo accanto al
-- mascherato renderebbe la mascheratura inutile: chi legge il numero vero non ha bisogno di n_label.
-- Chi serve il dato non mascherato lo legge da `trasi.richiesta` (solo `ti` per matrice).
-- ===========================================================================
DROP VIEW IF EXISTS trasi.v_confronto_case;
CREATE VIEW trasi.v_confronto_case AS
SELECT c.id AS casa_id, c.slug AS casa_slug, c.nome AS casa_nome, c.zona,
       mm.mese,
       kr.n AS richieste_mese, kr.n_label AS richieste_mese_label,
       res.n AS risolte_mese, res.n_label AS risolte_mese_label,
       des.n AS destinate_mese, des.n_label AS destinate_mese_label,
       COALESCE(lp.n, 0)::integer AS luoghi,
       COALESCE(ev.n, 0)::integer AS eventi_futuri,
       COALESCE(pr.n, 0)::integer AS proposte_aperte,
       COALESCE(op.n, 0)::integer AS opportunita_aperte
FROM trasi.casa c
CROSS JOIN LATERAL (SELECT date_trunc('month', current_date)::date AS mese) mm
LEFT JOIN LATERAL (
  SELECT count(*) AS n_req,
         count(*) FILTER (WHERE r.esito = 'risolta') AS n_risolte,
         count(*) FILTER (WHERE r.esito = 'inviata_altrove') AS n_destinate
  FROM trasi.richiesta r
  WHERE r.casa_id = c.id AND date_trunc('month', r.ts) = date_trunc('month', current_date)
) cur ON true
LEFT JOIN LATERAL trasi.k_anon(COALESCE(cur.n_req, 0)) kr ON true
LEFT JOIN LATERAL trasi.k_anon(COALESCE(cur.n_risolte, 0)) res ON true
LEFT JOIN LATERAL trasi.k_anon(COALESCE(cur.n_destinate, 0)) des ON true
LEFT JOIN LATERAL (SELECT count(*) AS n FROM trasi.luogo l WHERE l.casa_id = c.id AND l.chiuso_il IS NULL) lp ON true
LEFT JOIN LATERAL (SELECT count(*) AS n FROM trasi.evento e
                   WHERE e.casa_id = c.id AND e.annullato = false AND e.inizio >= now()) ev ON true
LEFT JOIN LATERAL (SELECT count(*) AS n FROM trasi.proposta p WHERE p.casa_id = c.id AND p.stato = 'proposta') pr ON true
LEFT JOIN LATERAL (SELECT count(*) AS n FROM trasi.opportunita o
                   WHERE o.casa_id = c.id AND (o.scadenza IS NULL OR o.scadenza >= current_date)) op ON true;

-- ===========================================================================
-- Proprietà e permessi delle viste
-- ===========================================================================
-- security_invoker = false: la vista gira come owner (trasi_owner) e vede tutto tramite le policy
-- `owner_all`. È ciò che serve a metabase_ro, che non ha SELECT su `richiesta`/`proposta`.
-- L'intento NON è aggirato perché ogni riga esposta è già pubblica nella rete o mascherata da k_anon().
ALTER VIEW trasi.v_scaduti             SET (security_invoker = false);
ALTER VIEW trasi.v_in_scadenza         SET (security_invoker = false);
ALTER VIEW trasi.v_senza_risposta      SET (security_invoker = false);
ALTER VIEW trasi.v_kb_export           SET (security_invoker = false);
ALTER VIEW trasi.v_destinazioni        SET (security_invoker = false);
ALTER VIEW trasi.v_oggi_casa           SET (security_invoker = false);
ALTER VIEW trasi.v_mappa_case          SET (security_invoker = false);
ALTER VIEW trasi.v_mappa_luoghi        SET (security_invoker = false);
ALTER VIEW trasi.v_mappa_luoghi_vicini SET (security_invoker = false);
ALTER VIEW trasi.v_proposte_aperte     SET (security_invoker = false);
ALTER VIEW trasi.v_report_mensile      SET (security_invoker = false);
ALTER VIEW trasi.v_confronto_case      SET (security_invoker = false);

GRANT SELECT ON trasi.v_scaduti, trasi.v_in_scadenza, trasi.v_senza_risposta, trasi.v_kb_export,
                trasi.v_destinazioni, trasi.v_oggi_casa, trasi.v_mappa_case, trasi.v_mappa_luoghi,
                trasi.v_mappa_luoghi_vicini, trasi.v_proposte_aperte, trasi.v_report_mensile,
                trasi.v_confronto_case
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao, casa_minimus, casa_pop,
     casa_bozzano, casa_dream, casa_tuturano, rete, ti, metabase_ro, automazioni, shim_rw, applicatore;

RESET ROLE;

