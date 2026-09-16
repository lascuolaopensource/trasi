-- Trasi — db/016_viste_new.sql
-- Viste delle schede !NEW: eventi (US-1.4) e attrezzoteca (US-5.1/5.3/5.4).
--
-- Perché un file separato da db/004_views.sql. Le viste qui dentro dipendono da oggetti
-- che nascono DOPO la 004 nell'ordine di apply.sh:
--   * v_eventi_dati_mancanti → `evento.aggiornato_ts`  (db/005_rls_proposta.sql)
--   * v_inventario, v_movimenti_da_confermare, v_uso_oggetti → `oggetto`/`movimento` (db/014)
-- Tenerle nella 004 significava un apply.sh che **fallisce** su una relazione inesistente
-- (misurato: `ERROR: relation "trasi.oggetto" does not exist` alla riga 439), perché la 004
-- gira prima della 005 e della 014. Qui girano dopo entrambe (prefisso 016), e la 004 resta
-- il file delle viste di B1, che non dipendono da nulla di nuovo.
--
-- Idempotente: DROP VIEW + CREATE VIEW ad ogni esecuzione.

-- ===========================================================================
-- Viste eventi (US-1.4) e attrezzoteca (US-5.1/5.3/5.4)
-- ===========================================================================
SET ROLE trasi_owner;
SET search_path = trasi, public, pg_temp;

-- ---------------------------------------------------------------------------
-- V12 · v_eventi_dati_mancanti (US-1.4) — eventi FUTURI con campi utili assenti
--       oppure aggiornati oltre 2 mesi fa. `evento` reale: inizio/fine (timestamptz),
--       descrizione, luogo_testo, url, aggiornato_ts (aggiunta da db/005).
--       mancanze: badge V3 + freschezza; motivo: incompleto | datato | incompleto_e_datato.
-- ---------------------------------------------------------------------------
DROP VIEW IF EXISTS trasi.v_eventi_dati_mancanti;
CREATE VIEW trasi.v_eventi_dati_mancanti AS
WITH base AS (
  SELECT e.id AS evento_id, e.casa_id, c.slug AS casa_slug, e.titolo, e.inizio,
         e.aggiornato_ts,
         ARRAY_REMOVE(ARRAY[
           CASE WHEN NULLIF(btrim(COALESCE(e.descrizione,'')), '') IS NULL THEN 'descrizione' END,
           CASE WHEN NULLIF(btrim(COALESCE(e.luogo_testo,'')), '') IS NULL THEN 'luogo_testo' END,
           CASE WHEN NULLIF(btrim(COALESCE(e.url,'')), '') IS NULL THEN 'url' END,
           CASE WHEN e.fonte_id IS NULL THEN 'fonte' END,
           CASE WHEN e.affidabilita IS NULL THEN 'affidabilita' END
         ], NULL) AS mancanze
  FROM trasi.evento e
  JOIN trasi.casa c ON c.id = e.casa_id
  WHERE e.annullato = false
    AND e.inizio >= now()                       -- solo il palinsesto futuro
)
SELECT evento_id, casa_id, casa_slug, titolo, inizio, mancanze,
       CASE WHEN cardinality(mancanze) > 0
                 AND (aggiornato_ts IS NULL OR aggiornato_ts < now() - interval '2 months')
            THEN 'incompleto_e_datato'
            WHEN cardinality(mancanze) > 0 THEN 'incompleto'
            ELSE 'datato' END AS motivo
FROM base
WHERE cardinality(mancanze) > 0
   OR aggiornato_ts IS NULL
   OR aggiornato_ts < now() - interval '2 months';

-- ---------------------------------------------------------------------------
-- V13 · v_inventario (US-5.1) — disponibilità per oggetto: quantità al netto dei
--       movimenti confermati in corso (fine sconosciuta → in corso finché non rientra;
--       fine nota → in corso fino alla data `al` inclusa). Badge fonte (V3).
-- ---------------------------------------------------------------------------
DROP VIEW IF EXISTS trasi.v_inventario;
CREATE VIEW trasi.v_inventario AS
SELECT o.id AS oggetto_id, o.nome, o.descrizione, o.casa_id, c.slug AS casa_slug,
       o.quantita, o.condizione,
       COALESCE(fuori.n, 0)::integer                          AS quantita_fuori,
       GREATEST(o.quantita - COALESCE(fuori.n, 0), 0)::integer AS quantita_disponibile,
       f.nome AS fonte_nome,
       COALESCE(f.tipo_accesso, 'rete')                       AS badge_fonte,
       o.attivo
FROM trasi.oggetto o
JOIN trasi.casa c ON c.id = o.casa_id
LEFT JOIN trasi.fonte f ON f.id = o.fonte_id
LEFT JOIN LATERAL (
  SELECT count(*) AS n
  FROM trasi.movimento m
  WHERE m.oggetto_id = o.id
    AND m.stato = 'confermato'
    AND m.dal <= current_date
    AND (m.al IS NULL OR m.al >= current_date)
) fuori ON true
WHERE o.attivo;

-- ---------------------------------------------------------------------------
-- V14 · v_movimenti_da_confermare (US-5.3) — prestiti in attesa di conferma.
--       security_invoker=false: la UI filtra per a_casa_slug della sessione.
-- ---------------------------------------------------------------------------
DROP VIEW IF EXISTS trasi.v_movimenti_da_confermare;
CREATE VIEW trasi.v_movimenti_da_confermare AS
SELECT m.id, m.oggetto_id, o.nome AS oggetto_nome, o.quantita AS oggetto_quantita,
       m.da_casa_id, cda.slug AS da_casa_slug,
       m.a_casa_id,  ca.slug  AS a_casa_slug,
       m.dal, m.al, m.motivazione, m.ts,
       (current_date - m.ts::date) AS giorni_attesa
FROM trasi.movimento m
JOIN trasi.oggetto o ON o.id = m.oggetto_id
JOIN trasi.casa cda ON cda.id = m.da_casa_id
JOIN trasi.casa ca  ON ca.id  = m.a_casa_id
WHERE m.stato = 'proposto';

-- ---------------------------------------------------------------------------
-- V15 · v_uso_oggetti (US-5.4) — frequenza d'uso negli ultimi 12 mesi, con soglie
--       da parametro [P] attrezzoteca_soglia_bassa / attrezzoteca_soglia_alta
--       (ripiego 2/10 se i parametri non sono ancora stati caricati da db/003).
-- ---------------------------------------------------------------------------
DROP VIEW IF EXISTS trasi.v_uso_oggetti;
CREATE VIEW trasi.v_uso_oggetti AS
SELECT o.id AS oggetto_id, o.nome, o.casa_id, c.slug AS casa_slug, o.condizione,
       COALESCE(uso.n, 0)::integer AS n_movimenti_12m,
       uso.ultimo_ts               AS ultimo_movimento_ts,
       CASE WHEN COALESCE(uso.n, 0) <  COALESCE(trasi.p_int('attrezzoteca_soglia_bassa'), 2) THEN 'basso'
            WHEN COALESCE(uso.n, 0) >= COALESCE(trasi.p_int('attrezzoteca_soglia_alta'), 10) THEN 'alto'
            ELSE 'medio' END AS fascia_uso
FROM trasi.oggetto o
JOIN trasi.casa c ON c.id = o.casa_id
LEFT JOIN LATERAL (
  SELECT count(*) AS n, max(m.ts) AS ultimo_ts
  FROM trasi.movimento m
  WHERE m.oggetto_id = o.id
    AND m.stato IN ('confermato','rientrato')
    AND m.ts >= now() - interval '12 months'
) uso ON true
WHERE o.attivo;

ALTER VIEW trasi.v_eventi_dati_mancanti    SET (security_invoker = false);
ALTER VIEW trasi.v_inventario              SET (security_invoker = false);
ALTER VIEW trasi.v_movimenti_da_confermare SET (security_invoker = false);
ALTER VIEW trasi.v_uso_oggetti             SET (security_invoker = false);

GRANT SELECT ON trasi.v_eventi_dati_mancanti, trasi.v_inventario,
                trasi.v_movimenti_da_confermare, trasi.v_uso_oggetti
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao, casa_minimus, casa_pop,
     casa_bozzano, casa_dream, casa_tuturano, rete, ti, metabase_ro, automazioni, shim_rw, applicatore;

RESET ROLE;
