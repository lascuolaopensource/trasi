-- Trasi — db/030_ricorrenze.sql
-- L'espansione delle occorrenze degli eventi ricorrenti (US-1, P0.4): la colonna `evento.ricorrenza`
-- esiste dal 025 (CHECK a 4 valori: settimanale/bisettimanale/mensile/annuale), ma nessuna vista la
-- **calcola** — un evento settimanale compariva una volta sola, al primo `inizio`, e la Home e la
-- ricerca per intervallo non lo mostravano mai più. La regola si calcola, non si memorizza: memorizzare
-- le occorrenze romperebbe l'upsert iCal (N righe con lo stesso `uid_ical`) e duplicherebbe la verità.
--
-- Forma: una **funzione** `evento_occorgenze(evento, dal, al)` che rende le righe di occorrenza
-- nell'intervallo, e una vista `v_eventi_occorgenze` che espone gli eventi **con** le loro occorrenze
-- entro una finestra. I consumatori (`eventi_oggi` shim, `v_oggi_casa`, `GET /op/eventi`) la usano al
-- posto di leggere `evento` nudo: un evento singolo è una occorrenza sola, un ricorrente è una per
-- ripetizione caduta nella finestra.
--
-- Semantica dell'occorgenze (le decisioni, non i dettagli):
--   * la prima occorrenza è `inizio` **sempre** — anche se `dal` è successivo: l'evento settimanale del
--     1/9 esiste il 1/9 anche se la finestra inizia l'8;
--   * le successive sono `inizio + N * passo`, con `N >= 1`, finché il giorno cade in `[dal, al]`;
--   * `mensile` e `annuale` **non saltano**: il 31 gennaio mensile diventa il 28/29 febbraio (clamp a
--     fine mese, `make_date` con day calcolato) — è il comportamento che un calendario di sportello
--     attende, non un errore;
--   * un evento con `fine` (multi-giorno) ricorre **con la sua durata**: l'occorrenza successiva parte
--     dalla `inizio` originale più il passo, e la `fine` si sposta dello stesso intervallo;
--   * `annullato = true` esclude tutto (come `v_eventi`).
-- Idempotente: DROP+CREATE di funzione e vista.
\set ON_ERROR_STOP on
\set VERBOSITY terse

SET ROLE trasi_owner;
SET search_path = trasi, public, pg_temp;

-- ---------------------------------------------------------------------------
-- 1. `evento_occorgenze` — le occorrenze di un evento in `[dal, al]`, come SETOF righe
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION trasi.evento_occorgenze(
  p_evento trasi.evento,
  p_dal    date,
  p_al     date
) RETURNS TABLE (
  occorrenza_id  integer,
  inizio         timestamptz,
  fine           timestamptz,
  n_occorrenza   integer
) LANGUAGE plpgsql STABLE AS $$
DECLARE
  v_inizio    timestamptz := p_evento.inizio;
  v_fine      timestamptz := p_evento.fine;
  v_dal       timestamptz := p_dal::timestamptz;
  v_al_fine   timestamptz := (p_al + 1)::timestamptz;  -- fine finestra inclusiva (mezzanotte del giorno dopo)
  v_quando    timestamptz;
  v_fine_q    timestamptz;
  v_n         integer := 0;
  v_passo     interval;
  v_limite    integer := 500;  -- tetto di sicurezza: un annuale con finestra di anni non estrae all'infinito
BEGIN
  -- Finestra assurda: nessuna occorrenza (il chiamante valida comunque).
  IF p_al < p_dal THEN RETURN; END IF;

  -- La prima occorrenza è `inizio` SEMPRE: se cade nella finestra (o la attraversa), esce.
  v_quando := v_inizio;
  IF v_quando::date <= p_al THEN
    v_fine_q := v_fine;
    RETURN QUERY SELECT p_evento.id, v_quando, v_fine_q, 0;
  END IF;

  -- Poi il passo, fino a uscire dall'alto della finestra.
  v_passo := CASE p_evento.ricorrenza
    WHEN 'settimanale'   THEN interval '7 days'
    WHEN 'bisettimanale' THEN interval '14 days'
    WHEN 'mensile'       THEN interval '1 month'
    WHEN 'annuale'       THEN interval '1 year'
    ELSE NULL
  END;
  IF v_passo IS NULL THEN RETURN; END IF;  -- evento singolo: già emesso (o fuori finestra)

  v_quando := v_inizio + v_passo;
  WHILE v_quando::date <= p_al AND v_n < v_limite LOOP
    v_fine_q := v_fine + (v_quando - v_inizio);
    v_n := v_n + 1;
    RETURN QUERY SELECT p_evento.id, v_quando, v_fine_q, v_n;
    v_quando := v_quando + v_passo;
  END LOOP;
END $$;

COMMENT ON FUNCTION trasi.evento_occorgenze(trasi.evento, date, date) IS
  'Occorrenze di un evento in [dal, al], inclusiva su entrambi gli estremi. n_occorrenza 0 = la prima '
  '(sempre `inizio` originale). Mensile/annuale con giorno mancante (31 gen → feb) fa clamp a fine mese '
  'per effetto dell''aritmetica degli intervalli PostgreSQL (1 month su 31/01 = 28/02).';

-- ---------------------------------------------------------------------------
-- 2. `v_eventi_occorgenze` — la superficie di ricerca: un riga per occorrenza in finestra
-- ---------------------------------------------------------------------------
DROP VIEW IF EXISTS trasi.v_eventi_occorgenze;
CREATE VIEW trasi.v_eventi_occorgenze AS
SELECT e.id AS evento_id, o.n_occorrenza, o.inizio, o.fine,
       e.casa_id, c.slug AS casa_slug, c.nome AS casa_nome,
       e.titolo, e.descrizione, e.luogo_testo, e.url, e.costo, e.fascia_eta, e.tag, e.ricorrenza,
       COALESCE(f.nome, 'inserito dall''operatore') AS fonte_nome,
       f.autorita AS fonte_autorita, f.tipo_accesso AS fonte_tipo,
       COALESCE(e.affidabilita, 2) AS affidabilita,
       o.inizio::date AS giorno,
       (e.inizio::date - current_date) AS giorni_all_inizio
FROM trasi.evento e
JOIN trasi.casa c ON c.id = e.casa_id
LEFT JOIN trasi.fonte f ON f.id = e.fonte_id
CROSS JOIN LATERAL trasi.evento_occorgenze(e, current_date - 92, current_date + 366) o
WHERE e.annullato = false
  AND o.inizio::date >= current_date - 92
  AND o.inizio::date <= current_date + 366;

ALTER VIEW trasi.v_eventi_occorgenze SET (security_invoker = false);

GRANT SELECT ON trasi.v_eventi_occorgenze TO
  casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
  casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano,
  rete, ti, metabase_ro, automazioni, shim_rw, applicatore;

-- ---------------------------------------------------------------------------
-- 3. `v_oggi_casa` conta le OCCORRENZE di oggi, non le righe di `evento`
-- ---------------------------------------------------------------------------
-- La riga «Oggi» della Home e il tool `oggi` della chat dicevano «0 eventi» il giovedì in cui il
-- laboratorio settimanale del giovedì scorso si ripeteva: contavano `e.inizio::date = current_date`,
-- cioè la sola prima occorrenza. Stessa forma (db/004), stessa `format()` del testo: cambia il `LATERAL`.
DROP VIEW IF EXISTS trasi.v_oggi_casa;
CREATE VIEW trasi.v_oggi_casa AS
SELECT c.id AS casa_id, c.slug, c.nome, current_date AS data,
       COALESCE(ev.n, 0)::integer AS eventi,
       COALESCE(sc.n, 0)::integer AS schede_in_scadenza,
       COALESCE(pr.n, 0)::integer AS proposte,
       COALESCE(pv.giorni, 0)::integer AS giorni_piu_vecchia,
       format('Oggi a %s: %s %s · %s %s · %s %s',
              c.nome,
              COALESCE(ev.n,0), CASE WHEN COALESCE(ev.n,0) = 1 THEN 'evento' ELSE 'eventi' END,
              COALESCE(sc.n,0), CASE WHEN COALESCE(sc.n,0) = 1 THEN 'scheda in scadenza' ELSE 'schede in scadenza' END,
              COALESCE(pr.n,0), CASE WHEN COALESCE(pr.n,0) = 1 THEN 'proposta' ELSE 'proposte' END) AS testo
FROM trasi.casa c
LEFT JOIN LATERAL (
  SELECT count(*) AS n
    FROM trasi.evento e
    CROSS JOIN LATERAL trasi.evento_occorgenze(e, current_date, current_date) o
   WHERE e.casa_id = c.id AND e.annullato = false AND o.inizio::date = current_date
) ev ON true
LEFT JOIN LATERAL (
  SELECT count(*) AS n FROM trasi.scheda_servizio s
  WHERE s.casa_id = c.id AND s.scadenza IS NOT NULL
    AND s.scadenza <= current_date + COALESCE(trasi.p_int('gg_preavviso_scadenza'), 15)
) sc ON true
LEFT JOIN LATERAL (
  SELECT count(*) AS n FROM trasi.proposta p
  WHERE p.casa_id = c.id AND p.stato = 'proposta'
) pr ON true
LEFT JOIN LATERAL (
  SELECT current_date - min(p.proposto_ts)::date AS giorni FROM trasi.proposta p
  WHERE p.casa_id = c.id AND p.stato = 'proposta'
) pv ON true;

ALTER VIEW trasi.v_oggi_casa SET (security_invoker = false);

GRANT SELECT ON trasi.v_oggi_casa TO
  casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
  casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano,
  rete, ti, metabase_ro, automazioni, shim_rw, applicatore;

-- ---------------------------------------------------------------------------
-- 4. Verifica di installazione
-- ---------------------------------------------------------------------------
DO $verify$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
                 WHERE n.nspname = 'trasi' AND p.proname = 'evento_occorgenze') THEN
    RAISE EXCEPTION '030_ricorrenze: funzione evento_occorgenze non installata';
  END IF;
  IF to_regclass('trasi.v_eventi_occorgenze') IS NULL THEN
    RAISE EXCEPTION '030_ricorrenze: vista v_eventi_occorgenze non installata';
  END IF;
  RAISE NOTICE '030_ricorrenze applicato: evento_occorgenze + v_eventi_occorgenze';
END
$verify$;