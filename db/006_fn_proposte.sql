-- ============================================================================
-- Trasi — B1 · 006_fn_proposte.sql
-- Worker proprietario: trasi-proposte.  Ordine: dopo 005, prima di 010–012.
--
-- Contenuto:
--   1. helper: whitelist del payload, snapshot di entita', diff leggibile
--   2. macchina a stati `proposta_01_transition_tg` (P0001 su transizioni illegali)
--   3. audit automatico delle transizioni `proposta_02_audit_tg`
--   4. diff automatico `proposta_03_diff_tg` + `diff_leggibile()`
--   5. percorsi automatici ammessi da V4:
--        * `evento_ical_*` — unica eccezione: upsert iCal su `evento` (§8 F4)
--        * `applica_proposte_approvate()` — l'unico che scrive il dominio
--        * `scadi_proposte()`
--   6. viste `v_da_approvare` (coda) e `v_scritture_senza_audit` (B1-PRP-06)
--
-- Idempotente: rieseguibile senza errori.
--
-- [ASSUNZIONE] Il DDL v1.1 non esiste nel repo: i nomi di colonna vengono
-- dalla ricostruzione del worker trasi-dati (001/002, contratto verificato via
-- hub il 15/09) e da §7.1 dell'architettura. Le colonne aggiunte da questo
-- blocco sono elencate in 005 (§2, D3).
-- ============================================================================
\set ON_ERROR_STOP on

-- ---------------------------------------------------------------------------
-- 1. Helper
-- ---------------------------------------------------------------------------

-- `payload_ammesso`: presidio strutturale di V5. Il payload di una proposta
-- puo' toccare solo un elenco chiuso di colonne: nessun campo libero, quindi
-- nessun posto dove far entrare un dato personale.
CREATE OR REPLACE FUNCTION trasi.payload_ammesso(p_payload jsonb, p_chiavi text[])
RETURNS jsonb
LANGUAGE sql IMMUTABLE
AS $fn$
  SELECT COALESCE(jsonb_object_agg(e.k, e.v), '{}'::jsonb)
    FROM jsonb_each(COALESCE(p_payload, '{}'::jsonb)) AS e(k, v)
   WHERE e.k = ANY (p_chiavi);
$fn$;

-- `payload_richiede`: errore parlante (finisce in `esito` e in `audit`) se il
-- payload non porta i valori obbligatori per il ramo di applicazione.
CREATE OR REPLACE FUNCTION trasi.payload_richiede(p_payload jsonb, p_chiavi text[])
RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE
AS $fn$
DECLARE
  v_mananti text;
BEGIN
  SELECT string_agg(k, ', ') INTO v_mananti
    FROM unnest(p_chiavi) AS k
   WHERE NOT COALESCE(p_payload, '{}'::jsonb) ? k;
  IF v_mananti IS NOT NULL THEN
    RAISE EXCEPTION 'payload incompleto: mancano %', v_mananti;
  END IF;
  RETURN COALESCE(p_payload, '{}'::jsonb);
END;
$fn$;

-- `snapshot_entita`: fotografia jsonb di una riga di dominio, per `diff` e per
-- `audit.prima/dopo`. Sulla geografia non si emette l'EWKB: si emettono lat/lon
-- (leggibilita' del diff, §9.1 «si approva leggendo»). Whitelist chiusa: un
-- `entita` fuori elenco non produce snapshot.
-- PostGIS e' installato nello schema `public` (extnamespace = public): i tipi e
-- le funzioni geografiche sono qualificati esplicitamente, cosi' non serve
-- allargare il `search_path` di una funzione SECURITY DEFINER a uno schema in
-- cui un altro ruolo potrebbe creare oggetti.
CREATE OR REPLACE FUNCTION trasi.snapshot_entita(p_entita text, p_id int)
RETURNS jsonb
LANGUAGE plpgsql STABLE
SET search_path = trasi, pg_catalog
AS $fn$
BEGIN
  IF p_id IS NULL THEN
    RETURN NULL;
  END IF;
  RETURN CASE p_entita
    WHEN 'luogo' THEN (
      SELECT to_jsonb(t) - 'geom'
             || jsonb_build_object('lat', public.ST_Y(t.geom::public.geometry),
                                   'lon', public.ST_X(t.geom::public.geometry))
        FROM trasi.luogo t WHERE t.id = p_id)
    WHEN 'casa' THEN (
      SELECT to_jsonb(t) - 'geom'
             || jsonb_build_object('lat', public.ST_Y(t.geom::public.geometry),
                                   'lon', public.ST_X(t.geom::public.geometry))
        FROM trasi.casa t WHERE t.id = p_id)
    WHEN 'scheda_servizio' THEN (
      SELECT to_jsonb(t) FROM trasi.scheda_servizio t WHERE t.id = p_id)
    WHEN 'evento' THEN (
      SELECT to_jsonb(t) FROM trasi.evento t WHERE t.id = p_id)
    WHEN 'opportunita' THEN (
      SELECT to_jsonb(t) FROM trasi.opportunita t WHERE t.id = p_id)
    WHEN 'oggetto' THEN (
      SELECT to_jsonb(t) FROM trasi.oggetto t WHERE t.id = p_id)
    ELSE NULL
  END;
END;
$fn$;

-- `diff_leggibile`: rende `diff` una riga per campo proposto — «campo: prima →
-- dopo». E' il testo su cui l'umano decide in coda (§4.5, §9.1).
--
-- `dopo` e' il PAYLOAD, cioe' una PATCH: contiene solo i campi proposti. I campi
-- dell'entita' assenti dal payload NON vengono toccati dall'applicazione, quindi
-- non devono comparire; iterare sull'unione `prima ∪ dopo` li mostrerebbe come
-- «valore → ∅», facendo leggere una modifica di orario come una cancellazione
-- dei dati. Si itera quindi sulle chiavi del payload, che sono esattamente le
-- colonne che l'applicazione riscrivera'.
CREATE OR REPLACE FUNCTION trasi.diff_leggibile(p_diff jsonb)
RETURNS text
LANGUAGE sql IMMUTABLE
AS $fn$
  SELECT CASE
           WHEN p_diff IS NULL THEN '(diff assente)'
           ELSE COALESCE(NULLIF((
             SELECT string_agg(format('%s: %s → %s', ks.k,
                                      CASE WHEN (p_diff->'prima') ? ks.k
                                           THEN COALESCE((p_diff->'prima')->>ks.k, '(nessun valore)')
                                           ELSE '(assente da valorizzare)' END,
                                      COALESCE((p_diff->'dopo')->>ks.k, '(nessun valore)')),
                               E'\n' ORDER BY ks.k)
               FROM (SELECT jsonb_object_keys(COALESCE(p_diff->'dopo', '{}'::jsonb)) AS k) AS ks
           ), ''), '(nessun campo proposto)')
         END
    || CASE WHEN (p_diff->>'anomalo') = 'true'
            THEN E'\n[delta anomalo: non applicare senza verifica]' ELSE '' END;
$fn$;

-- ---------------------------------------------------------------------------
-- 2. Macchina a stati: proposta -> approvata|rifiutata|scaduta,
--    approvata -> applicata|rifiutata. Ogni altra transizione = P0001.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION trasi.proposta_01_transition_tg()
RETURNS trigger
LANGUAGE plpgsql
AS $fn$
DECLARE
  v_ok boolean;
BEGIN
  IF TG_OP = 'UPDATE' THEN
    -- Integrita' della proposta: chi la crea e chi la deve approvare non si
    -- cambiano strada facendo (V4 regola 2: nessuno si sceglie l'approvatore).
    IF NEW.proposto_da IS DISTINCT FROM OLD.proposto_da
       OR NEW.approvatore_ruolo IS DISTINCT FROM OLD.approvatore_ruolo
       OR NEW.tipo IS DISTINCT FROM OLD.tipo
       OR NEW.casa_id IS DISTINCT FROM OLD.casa_id
       OR NEW.entita IS DISTINCT FROM OLD.entita
       OR NEW.entita_id IS DISTINCT FROM OLD.entita_id
       OR NEW.payload IS DISTINCT FROM OLD.payload THEN
      RAISE EXCEPTION 'campi di proposta immutabili (proposto_da, approvatore_ruolo, tipo, casa_id, entita, entita_id, payload)'
        USING ERRCODE = 'P0001';
    END IF;

    IF NEW.stato IS DISTINCT FROM OLD.stato THEN
      v_ok := CASE OLD.stato::text
                WHEN 'proposta'  THEN NEW.stato IN ('approvata', 'rifiutata', 'scaduta')
                WHEN 'approvata' THEN NEW.stato IN ('applicata', 'rifiutata')
                ELSE false   -- rifiutata | applicata | scaduta: stati terminali
              END;
      IF NOT v_ok THEN
        RAISE EXCEPTION 'transizione di stato non ammessa: % -> % (proposta %)',
          OLD.stato, NEW.stato, NEW.id USING ERRCODE = 'P0001';
      END IF;

      -- Si approva solo dentro la finestra di validita' della proposta.
      IF NEW.stato = 'approvata' AND NEW.scade_il IS NOT NULL AND NEW.scade_il < current_date THEN
        RAISE EXCEPTION 'proposta % scaduta il %: non approvabile (usare scadi_proposte)',
          NEW.id, NEW.scade_il USING ERRCODE = 'P0001';
      END IF;

      -- V4 regola 1 — auto-approvazione vietata, anche a livello di macchina a
      -- stati (oltre alla policy RESTRICTIVE `no_self_approve` di 005).
      IF NEW.stato IN ('approvata', 'rifiutata') AND NEW.proposto_da = current_user THEN
        RAISE EXCEPTION 'auto-approvazione vietata: % ha proposto la proposta % e non puo'' deciderla',
          current_user, NEW.id USING ERRCODE = 'P0001';
      END IF;

      -- Chi decide non si firma da solo.
      IF NEW.stato IN ('approvata', 'rifiutata') THEN
        NEW.approvato_da := current_user;
        NEW.approvato_ts := now();
      END IF;

      -- Solo il ruolo di macchina porta una proposta ad `applicata`.
      IF NEW.stato = 'applicata' AND current_user <> 'applicatore' THEN
        RAISE EXCEPTION 'solo applicatore puo'' portare una proposta ad applicata (current_user=%)',
          current_user USING ERRCODE = 'P0001';
      END IF;
    END IF;
  END IF;

  RETURN NEW;
END;
$fn$;

DROP TRIGGER IF EXISTS proposta_01_transition_tg ON trasi.proposta;
CREATE TRIGGER proposta_01_transition_tg
  BEFORE INSERT OR UPDATE ON trasi.proposta
  FOR EACH ROW EXECUTE FUNCTION trasi.proposta_01_transition_tg();

-- ---------------------------------------------------------------------------
-- 3. Audit delle transizioni di proposta. `applicata` esclusa: la registra il
--    percorso di applicazione con prima/dopo dell'ENTITA' (non della proposta).
--    SECURITY DEFINER owner `applicatore`: e' l'unico con INSERT su `audit`.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION trasi.proposta_02_audit_tg()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = trasi, pg_catalog
AS $fn$
BEGIN
  IF TG_OP = 'INSERT' THEN
    INSERT INTO trasi.audit (proposta_id, azione, eseguito_da, entita, entita_id, prima, dopo)
    VALUES (NEW.id, 'proposta_creata', session_user, NEW.entita, NEW.entita_id,
            NULL, jsonb_build_object('stato', NEW.stato, 'tipo', NEW.tipo,
                                     'diff', NEW.diff, 'payload', NEW.payload));
    RETURN NEW;
  END IF;

  IF NEW.stato IS DISTINCT FROM OLD.stato AND NEW.stato <> 'applicata' THEN
    INSERT INTO trasi.audit (proposta_id, azione, eseguito_da, entita, entita_id, prima, dopo)
    VALUES (NEW.id, 'transizione', session_user, NEW.entita, NEW.entita_id,
            jsonb_build_object('stato', OLD.stato, 'approvato_da', OLD.approvato_da,
                               'nota_decisione', OLD.nota_decisione, 'scade_il', OLD.scade_il),
            jsonb_build_object('stato', NEW.stato, 'approvato_da', NEW.approvato_da,
                               'nota_decisione', NEW.nota_decisione, 'scade_il', NEW.scade_il));
  END IF;
  RETURN NEW;
END;
$fn$;
ALTER FUNCTION trasi.proposta_02_audit_tg() OWNER TO applicatore;

DROP TRIGGER IF EXISTS proposta_02_audit_tg ON trasi.proposta;
CREATE TRIGGER proposta_02_audit_tg
  AFTER INSERT OR UPDATE ON trasi.proposta
  FOR EACH ROW EXECUTE FUNCTION trasi.proposta_02_audit_tg();

-- ---------------------------------------------------------------------------
-- 4. `diff` automatico: si approva solo leggendo (regola 3)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION trasi.proposta_03_diff_tg()
RETURNS trigger
LANGUAGE plpgsql
AS $fn$
BEGIN
  IF NEW.diff IS NULL THEN
    NEW.diff := jsonb_build_object(
                  'prima', trasi.snapshot_entita(NEW.entita, NEW.entita_id),
                  'dopo',  COALESCE(NEW.payload, '{}'::jsonb));
  END IF;
  RETURN NEW;
END;
$fn$;

DROP TRIGGER IF EXISTS proposta_03_diff_tg ON trasi.proposta;
CREATE TRIGGER proposta_03_diff_tg
  BEFORE INSERT OR UPDATE OF diff, payload, entita, entita_id ON trasi.proposta
  FOR EACH ROW EXECUTE FUNCTION trasi.proposta_03_diff_tg();

-- ---------------------------------------------------------------------------
-- 5a. Unica eccezione a V4: upsert iCal su `evento`.
--     Il percorso resta confinato dalla policy `ev_ical_ins/upd` di 005 (la
--     fonte deve avere `tipo_accesso='ical'`). Qui: impronta di scrittura e una
--     riga di audit per variazione (F4, F9).
-- ---------------------------------------------------------------------------
-- L'impronta di scrittura (`aggiornato_ts`, `aggiornato_da`) su `evento` e'
-- gia' coperta dal trigger generico `scrittura_00_ts` di 005: qui resta solo
-- l'audit, per non avere due trigger che timbrano lo stesso campo.

CREATE OR REPLACE FUNCTION trasi.evento_ical_01_audit()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = trasi, pg_catalog
AS $fn$
BEGIN
  -- Il percorso mediato (`applica_proposte_approvate`) marca la propria
  -- transazione: le sue scritture hanno gia' la riga `applicata` con prima/dopo
  -- dell'entita' e non devono generare una seconda contabilita'. Il marcatore e'
  -- una GUC di transazione, quindi falsificabile: se qualcuno lo usasse per
  -- sopprimere l'audit iCal, la scrittura resterebbe **senza** riga di audit e
  -- `v_scritture_senza_audit` la contabilizzerebbe come violazione di V4.
  IF COALESCE(current_setting('trasi.applicazione', true), 'off') = 'on' THEN
    RETURN NULL;
  END IF;

  -- L'eccezione di V4 e' «upsert iCal da `automazioni`», non «ogni scrittura
  -- con fonte iCal»: un ruolo Casa che scrive un evento della propria Casa
  -- (consentito dalla matrice, D1) non deve essere registrato come `ical_upsert`,
  -- altrimenti l'audit attribuirebbe a una fonte automatica una scrittura umana.
  -- `session_user` (il ruolo di CONNESSIONE) e non `current_user`: questa
  -- funzione e' SECURITY DEFINER, quindi al suo interno `current_user` e' il
  -- proprietario `applicatore` e non il chiamante.
  IF session_user <> 'automazioni' THEN
    RETURN NULL;
  END IF;

  -- Coerenza con la policy `ev_ical_ins/upd` di 005: la fonte deve essere iCal.
  IF NOT EXISTS (SELECT 1 FROM trasi.fonte f
                  WHERE f.id = NEW.fonte_id AND f.tipo_accesso = 'ical') THEN
    RETURN NULL;
  END IF;

  -- Nessun DELETE e' ammesso sul dominio: un evento iCal rimosso a monte e'
  -- `annullato = true` (F4), quindi qui si registrano INSERT e UPDATE.
  INSERT INTO trasi.audit (azione, eseguito_da, entita, entita_id, prima, dopo)
  VALUES ('ical_upsert', session_user, 'evento', NEW.id,
          CASE WHEN TG_OP = 'UPDATE' THEN to_jsonb(OLD) END,
          to_jsonb(NEW));
  RETURN NULL;
END;
$fn$;
ALTER FUNCTION trasi.evento_ical_01_audit() OWNER TO applicatore;

DROP TRIGGER IF EXISTS evento_ical_01_audit ON trasi.evento;
CREATE TRIGGER evento_ical_01_audit
  AFTER INSERT OR UPDATE ON trasi.evento
  FOR EACH ROW EXECUTE FUNCTION trasi.evento_ical_01_audit();

-- ---------------------------------------------------------------------------
-- 6. `applica_proposte_approvate(p_limit)`
--    SECURITY DEFINER owner `applicatore`: e' l'unico percorso che scrive la
--    memoria applicativa. Idempotente (2a run = 0 righe), un savepoint per
--    proposta (un errore non abbatte il batch), FOR UPDATE SKIP LOCKED, audit
--    con prima/dopo dell'ENTITA'.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION trasi.applica_proposte_approvate(p_limit int DEFAULT 100)
RETURNS TABLE (proposta_id bigint, tipo text, entita text, entita_id int, esito text)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = trasi, pg_catalog
AS $fn$
DECLARE
  v_limit      int := COALESCE(NULLIF(p_limit, 0), 100);
  v_rec        record;
  v_p          jsonb;
  v_eid        int;
  v_prima      jsonb;
  v_dopo       jsonb;
  v_esito      text;
  v_fonte_kb   int;
  v_msg        text;
BEGIN
  -- Fonte di ripiego per le proposte di creazione senza `fonte_id` proprio.
  SELECT f.id INTO v_fonte_kb FROM trasi.fonte f
   WHERE f.tipo_accesso = 'kb' ORDER BY f.livello_fiducia NULLS LAST, f.id LIMIT 1;

  -- Marca la transazione: da qui in poi le scritture di dominio sono mediate da
  -- proposta e hanno la loro riga `applicata` (vedi `evento_ical_01_audit`).
  PERFORM set_config('trasi.applicazione', 'on', true);

  FOR v_rec IN
    SELECT p.id, p.tipo, p.entita, p.entita_id, p.payload, p.casa_id, p.fonte_id
      FROM trasi.proposta p
     -- Una proposta `approvata` ma con scadenza passata NON va applicata: il consenso
     -- umano è più vecchio della validità del dato. Il trigger di transizione impedisce
     -- di *approvare* dopo la scadenza, ma non copre il caso in cui la scadenza arrivi
     -- **dopo** l'approvazione: `applica` gira alle 05:00 e `scadi` subito dopo, quindi
     -- tra mezzanotte e le 05:00 una proposta scaduta resta `approvata` e verrebbe
     -- applicata. `scadi_proposte()` la marca `scaduta` e la riga esce da questo filtro.
     WHERE p.stato = 'approvata'
       AND (p.scade_il IS NULL OR p.scade_il >= current_date)
     ORDER BY p.id
     LIMIT v_limit
       FOR UPDATE SKIP LOCKED
  LOOP
    v_esito := 'ok';
    v_eid   := NULL;
    v_prima := trasi.snapshot_entita(v_rec.entita, v_rec.entita_id);

    BEGIN   -- savepoint implicito: una proposta rotta non abbatte il batch
      CASE v_rec.tipo

        -- -------- A. luogo -------------------------------------------------
        WHEN 'nuovo_luogo' THEN
          v_p := trasi.payload_richiede(
                   trasi.payload_ammesso(v_rec.payload,
                     ARRAY['nome','tipo','lat','lon','orari','descrizione','indirizzo',
                           'note_accesso','ext_ref','casa_id','fonte_id','affidabilita',
                           'data_aggiornamento']),
                   ARRAY['nome','tipo']);
          INSERT INTO trasi.luogo (nome, tipo, geom, orari, descrizione, indirizzo,
                                   note_accesso, ext_ref, casa_id, fonte_id,
                                   affidabilita, data_aggiornamento, aggiornato_ts)
          VALUES (
            v_p->>'nome',
            v_p->>'tipo',
            CASE WHEN v_p ? 'lat' AND v_p ? 'lon'
                 THEN public.ST_SetSRID(public.ST_MakePoint((v_p->>'lon')::float8,
                                              (v_p->>'lat')::float8), 4326)::public.geography
            END,
            CASE WHEN v_p ? 'orari' THEN v_p->'orari' END,
            v_p->>'descrizione', v_p->>'indirizzo', v_p->>'note_accesso', v_p->>'ext_ref',
            COALESCE((v_p->>'casa_id')::int, v_rec.casa_id),
            COALESCE((v_p->>'fonte_id')::int, v_rec.fonte_id, v_fonte_kb),
            COALESCE((v_p->>'affidabilita')::smallint,
                     CASE WHEN COALESCE((v_p->>'fonte_id')::int, v_rec.fonte_id) IS NOT DISTINCT FROM v_fonte_kb
                          THEN 3 ELSE 2 END),
            COALESCE((v_p->>'data_aggiornamento')::date, current_date),
            now())
          RETURNING id INTO v_eid;

        WHEN 'modifica_luogo' THEN
          v_eid := v_rec.entita_id;
          v_p := trasi.payload_ammesso(v_rec.payload,
                   ARRAY['nome','tipo','lat','lon','orari','descrizione','indirizzo',
                         'note_accesso','chiuso_il','ext_ref','casa_id','fonte_id',
                         'affidabilita','data_aggiornamento']);
          UPDATE trasi.luogo t SET
            nome         = CASE WHEN v_p ? 'nome'         THEN v_p->>'nome'         ELSE t.nome END,
            tipo         = CASE WHEN v_p ? 'tipo'         THEN v_p->>'tipo'         ELSE t.tipo END,
            geom         = CASE WHEN v_p ? 'lat' AND v_p ? 'lon'
                                THEN public.ST_SetSRID(public.ST_MakePoint((v_p->>'lon')::float8,
                                                             (v_p->>'lat')::float8), 4326)::public.geography
                                ELSE t.geom END,
            orari        = CASE WHEN v_p ? 'orari'        THEN v_p->'orari'         ELSE t.orari END,
            descrizione  = CASE WHEN v_p ? 'descrizione'  THEN v_p->>'descrizione'  ELSE t.descrizione END,
            indirizzo    = CASE WHEN v_p ? 'indirizzo'    THEN v_p->>'indirizzo'    ELSE t.indirizzo END,
            note_accesso = CASE WHEN v_p ? 'note_accesso' THEN v_p->>'note_accesso' ELSE t.note_accesso END,
            chiuso_il    = CASE WHEN v_p ? 'chiuso_il'    THEN (v_p->>'chiuso_il')::date ELSE t.chiuso_il END,
            ext_ref      = CASE WHEN v_p ? 'ext_ref'      THEN v_p->>'ext_ref'      ELSE t.ext_ref END,
            casa_id      = CASE WHEN v_p ? 'casa_id'      THEN (v_p->>'casa_id')::int ELSE t.casa_id END,
            fonte_id     = CASE WHEN v_p ? 'fonte_id'     THEN (v_p->>'fonte_id')::int ELSE t.fonte_id END,
            affidabilita = CASE WHEN v_p ? 'affidabilita' THEN (v_p->>'affidabilita')::smallint ELSE t.affidabilita END,
            data_aggiornamento = CASE WHEN v_p ? 'data_aggiornamento'
                                      THEN (v_p->>'data_aggiornamento')::date ELSE t.data_aggiornamento END,
            aggiornato_ts = now()
           WHERE t.id = v_eid;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'luogo % inesistente: modifica non applicabile', v_eid;
          END IF;

        -- Soft-close: la memoria si chiude, non si cancella (V4 regola 7).
        WHEN 'chiudi_luogo' THEN
          v_eid := v_rec.entita_id;
          v_p := trasi.payload_ammesso(v_rec.payload, ARRAY['chiuso_il','descrizione']);
          UPDATE trasi.luogo t SET
            chiuso_il    = COALESCE((v_p->>'chiuso_il')::date, current_date),
            descrizione  = CASE WHEN v_p ? 'descrizione' THEN v_p->>'descrizione' ELSE t.descrizione END,
            data_aggiornamento = current_date,
            aggiornato_ts = now()
           WHERE t.id = v_eid;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'luogo % inesistente: chiusura non applicabile', v_eid;
          END IF;

        -- Promozione di un dato esterno in memoria (§11): affidabilita 2.
        WHEN 'promuovi_esterno' THEN
          v_eid := v_rec.entita_id;
          v_p := trasi.payload_ammesso(v_rec.payload,
                   ARRAY['nome','tipo','lat','lon','orari','descrizione','indirizzo',
                         'note_accesso','ext_ref','casa_id','fonte_id']);
          UPDATE trasi.luogo t SET
            nome         = CASE WHEN v_p ? 'nome'         THEN v_p->>'nome'         ELSE t.nome END,
            tipo         = CASE WHEN v_p ? 'tipo'         THEN v_p->>'tipo'         ELSE t.tipo END,
            geom         = CASE WHEN v_p ? 'lat' AND v_p ? 'lon'
                                THEN public.ST_SetSRID(public.ST_MakePoint((v_p->>'lon')::float8,
                                                             (v_p->>'lat')::float8), 4326)::public.geography
                                ELSE t.geom END,
            orari        = CASE WHEN v_p ? 'orari'        THEN v_p->'orari'         ELSE t.orari END,
            descrizione  = CASE WHEN v_p ? 'descrizione'  THEN v_p->>'descrizione'  ELSE t.descrizione END,
            indirizzo    = CASE WHEN v_p ? 'indirizzo'    THEN v_p->>'indirizzo'    ELSE t.indirizzo END,
            note_accesso = CASE WHEN v_p ? 'note_accesso' THEN v_p->>'note_accesso' ELSE t.note_accesso END,
            ext_ref      = CASE WHEN v_p ? 'ext_ref'      THEN v_p->>'ext_ref'      ELSE t.ext_ref END,
            casa_id      = CASE WHEN v_p ? 'casa_id'      THEN (v_p->>'casa_id')::int ELSE t.casa_id END,
            fonte_id     = COALESCE((v_p->>'fonte_id')::int, t.fonte_id, v_rec.fonte_id),
            affidabilita = 2,                     -- promosso da esterno
            data_aggiornamento = current_date,
            aggiornato_ts = now()
           WHERE t.id = v_eid;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'luogo % inesistente: promozione non applicabile', v_eid;
          END IF;

        -- -------- B. scheda_servizio --------------------------------------
        WHEN 'nuova_scheda' THEN
          v_p := trasi.payload_richiede(
                   trasi.payload_ammesso(v_rec.payload,
                     ARRAY['titolo','descrizione','categoria','orari','referente_ruolo',
                           'scadenza','fonte_id','affidabilita','casa_id']),
                   ARRAY['titolo']);
          INSERT INTO trasi.scheda_servizio (casa_id, titolo, descrizione, categoria, orari,
                                             referente_ruolo, scadenza, validata_il,
                                             fonte_id, affidabilita, aggiornato_ts)
          VALUES (
            COALESCE((v_p->>'casa_id')::int, v_rec.casa_id),
            v_p->>'titolo', v_p->>'descrizione', v_p->>'categoria',
            CASE WHEN v_p ? 'orari' THEN v_p->'orari' END,
            v_p->>'referente_ruolo', (v_p->>'scadenza')::date,
            current_date,                          -- approvata = validata
            COALESCE((v_p->>'fonte_id')::int, v_rec.fonte_id, v_fonte_kb),
            COALESCE((v_p->>'affidabilita')::smallint, 2),
            now())
          RETURNING id INTO v_eid;

        WHEN 'modifica_scheda' THEN
          v_eid := v_rec.entita_id;
          v_p := trasi.payload_ammesso(v_rec.payload,
                   ARRAY['titolo','descrizione','categoria','orari','referente_ruolo',
                         'scadenza','validata_il','fonte_id','affidabilita','casa_id']);
          UPDATE trasi.scheda_servizio t SET
            titolo          = CASE WHEN v_p ? 'titolo'          THEN v_p->>'titolo'          ELSE t.titolo END,
            descrizione     = CASE WHEN v_p ? 'descrizione'     THEN v_p->>'descrizione'     ELSE t.descrizione END,
            categoria       = CASE WHEN v_p ? 'categoria'       THEN v_p->>'categoria'       ELSE t.categoria END,
            orari           = CASE WHEN v_p ? 'orari'           THEN v_p->'orari'           ELSE t.orari END,
            referente_ruolo = CASE WHEN v_p ? 'referente_ruolo' THEN v_p->>'referente_ruolo' ELSE t.referente_ruolo END,
            scadenza        = CASE WHEN v_p ? 'scadenza'        THEN (v_p->>'scadenza')::date ELSE t.scadenza END,
            validata_il     = CASE WHEN v_p ? 'validata_il'     THEN (v_p->>'validata_il')::date ELSE t.validata_il END,
            fonte_id        = CASE WHEN v_p ? 'fonte_id'        THEN (v_p->>'fonte_id')::int ELSE t.fonte_id END,
            affidabilita    = CASE WHEN v_p ? 'affidabilita'    THEN (v_p->>'affidabilita')::smallint ELSE t.affidabilita END,
            aggiornato_ts   = now()
           WHERE t.id = v_eid;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'scheda_servizio % inesistente: modifica non applicabile', v_eid;
          END IF;

        -- -------- C. evento ------------------------------------------------
        WHEN 'modifica_evento' THEN
          v_eid := v_rec.entita_id;
          v_p := trasi.payload_ammesso(v_rec.payload,
                   ARRAY['titolo','descrizione','inizio','fine','luogo_testo','url',
                         'annullato','fonte_id','affidabilita']);
          UPDATE trasi.evento t SET
            titolo       = CASE WHEN v_p ? 'titolo'       THEN v_p->>'titolo'       ELSE t.titolo END,
            descrizione  = CASE WHEN v_p ? 'descrizione'  THEN v_p->>'descrizione'  ELSE t.descrizione END,
            inizio       = CASE WHEN v_p ? 'inizio'       THEN (v_p->>'inizio')::timestamptz ELSE t.inizio END,
            fine         = CASE WHEN v_p ? 'fine'         THEN (v_p->>'fine')::timestamptz   ELSE t.fine END,
            luogo_testo  = CASE WHEN v_p ? 'luogo_testo'  THEN v_p->>'luogo_testo'  ELSE t.luogo_testo END,
            url          = CASE WHEN v_p ? 'url'          THEN v_p->>'url'          ELSE t.url END,
            annullato    = CASE WHEN v_p ? 'annullato'    THEN (v_p->>'annullato')::boolean ELSE t.annullato END,
            fonte_id     = CASE WHEN v_p ? 'fonte_id'     THEN (v_p->>'fonte_id')::int ELSE t.fonte_id END,
            affidabilita = CASE WHEN v_p ? 'affidabilita' THEN (v_p->>'affidabilita')::smallint ELSE t.affidabilita END,
            aggiornato_ts = now()
           WHERE t.id = v_eid;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'evento % inesistente: modifica non applicabile', v_eid;
          END IF;

        -- -------- D. opportunita -------------------------------------------
        WHEN 'nuova_opportunita' THEN
          v_p := trasi.payload_richiede(
                   trasi.payload_ammesso(v_rec.payload,
                     ARRAY['titolo','descrizione','categoria','scadenza','url',
                           'fonte_id','affidabilita','casa_id']),
                   ARRAY['titolo']);
          INSERT INTO trasi.opportunita (casa_id, titolo, descrizione, categoria, scadenza,
                                         url, fonte_id, affidabilita, aggiornato_ts)
          VALUES (
            COALESCE((v_p->>'casa_id')::int, v_rec.casa_id),
            v_p->>'titolo', v_p->>'descrizione', v_p->>'categoria',
            (v_p->>'scadenza')::date, v_p->>'url',
            COALESCE((v_p->>'fonte_id')::int, v_rec.fonte_id, v_fonte_kb),
            COALESCE((v_p->>'affidabilita')::smallint, 2),
            now())
          RETURNING id INTO v_eid;

        -- -------- E. casa (solo orari) -------------------------------------
        WHEN 'modifica_orari_casa' THEN
          v_eid := COALESCE(v_rec.entita_id, (v_rec.payload->>'casa_id')::int, v_rec.casa_id);
          IF v_eid IS NULL THEN
            RAISE EXCEPTION 'modifica_orari_casa senza casa_id';
          END IF;
          v_p := trasi.payload_ammesso(v_rec.payload,
                   ARRAY['orari','orari_eccezioni','orari_provvisori','casa_id']);
          UPDATE trasi.casa t SET
            orari            = CASE WHEN v_p ? 'orari'            THEN v_p->'orari'            ELSE t.orari END,
            orari_eccezioni  = CASE WHEN v_p ? 'orari_eccezioni'  THEN v_p->'orari_eccezioni'  ELSE t.orari_eccezioni END,
            orari_provvisori = CASE WHEN v_p ? 'orari_provvisori' THEN (v_p->>'orari_provvisori')::boolean ELSE t.orari_provvisori END,
            aggiornato_ts    = now()
           WHERE t.id = v_eid;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'casa % inesistente: orari non applicabili', v_eid;
          END IF;

        -- -------- F. oggetto (attrezzoteca, US-5.x; tabella db/014) ---------
        WHEN 'nuovo_oggetto' THEN
          v_p := trasi.payload_richiede(
                   trasi.payload_ammesso(v_rec.payload,
                     ARRAY['nome','descrizione','quantita','condizione','casa_id','fonte_id']),
                   ARRAY['nome','quantita']);
          INSERT INTO trasi.oggetto (nome, descrizione, quantita, casa_id, condizione, fonte_id, aggiornato_ts)
          VALUES (
            v_p->>'nome', v_p->>'descrizione',
            (v_p->>'quantita')::int,
            COALESCE((v_p->>'casa_id')::int, v_rec.casa_id),
            COALESCE(v_p->>'condizione', 'integro'),
            COALESCE((v_p->>'fonte_id')::int, v_rec.fonte_id, v_fonte_kb),
            now())
          RETURNING id INTO v_eid;

        WHEN 'modifica_oggetto' THEN
          v_eid := v_rec.entita_id;
          v_p := trasi.payload_ammesso(v_rec.payload,
                   ARRAY['nome','descrizione','quantita','condizione','casa_id','fonte_id','attivo']);
          UPDATE trasi.oggetto t SET
            nome        = CASE WHEN v_p ? 'nome'       THEN v_p->>'nome'              ELSE t.nome END,
            descrizione = CASE WHEN v_p ? 'descrizione' THEN v_p->>'descrizione'      ELSE t.descrizione END,
            quantita    = CASE WHEN v_p ? 'quantita'   THEN (v_p->>'quantita')::int   ELSE t.quantita END,
            condizione  = CASE WHEN v_p ? 'condizione' THEN v_p->>'condizione'        ELSE t.condizione END,
            casa_id     = CASE WHEN v_p ? 'casa_id'    THEN (v_p->>'casa_id')::int    ELSE t.casa_id END,
            fonte_id    = CASE WHEN v_p ? 'fonte_id'   THEN (v_p->>'fonte_id')::int   ELSE t.fonte_id END,
            attivo      = CASE WHEN v_p ? 'attivo'     THEN (v_p->>'attivo')::boolean ELSE t.attivo END,
            aggiornato_ts = now()
           WHERE t.id = v_eid;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'oggetto % inesistente: modifica non applicabile', v_eid;
          END IF;

        -- Ritiro dall'attrezzoteca: attivo=false (mai DELETE, V4 regola 7).
        WHEN 'ritira_oggetto' THEN
          v_eid := v_rec.entita_id;
          v_p := trasi.payload_ammesso(v_rec.payload, ARRAY['condizione']);
          UPDATE trasi.oggetto t SET
            attivo        = false,
            condizione    = COALESCE(v_p->>'condizione', t.condizione),
            aggiornato_ts = now()
           WHERE t.id = v_eid;
          IF NOT FOUND THEN
            RAISE EXCEPTION 'oggetto % inesistente: ritiro non applicabile', v_eid;
          END IF;

        ELSE
          RAISE EXCEPTION 'tipo di proposta non applicabile: %', v_rec.tipo;
      END CASE;

      -- Stato finale: solo ora la proposta diventa `applicata`.
      UPDATE trasi.proposta SET stato = 'applicata' WHERE id = v_rec.id;

      -- Prima/dopo dell'ENTITA' (non della proposta), letti dal database.
      v_dopo := trasi.snapshot_entita(v_rec.entita, v_eid);

      INSERT INTO trasi.audit (proposta_id, azione, eseguito_da, entita, entita_id, prima, dopo)
      VALUES (v_rec.id, 'applicata', session_user, v_rec.entita, v_eid, v_prima, v_dopo);

    EXCEPTION WHEN OTHERS THEN
      -- Savepoint: la mutazione del dominio e' gia' stata annullata. Lo stato
      -- resta `approvata` (ritentabile) e resta traccia dell'errore.
      GET STACKED DIAGNOSTICS v_msg = MESSAGE_TEXT;
      v_esito := 'errore: ' || v_msg;
      INSERT INTO trasi.audit (proposta_id, azione, eseguito_da, entita, entita_id, prima, dopo)
      VALUES (v_rec.id, 'errore_applicazione', session_user, v_rec.entita, v_rec.entita_id,
              NULL, jsonb_build_object('errore', v_msg, 'tipo', v_rec.tipo));
    END;

    proposta_id := v_rec.id;
    tipo        := v_rec.tipo;
    entita      := v_rec.entita;
    entita_id   := v_eid;
    esito       := v_esito;
    RETURN NEXT;
  END LOOP;
END;
$fn$;

ALTER FUNCTION trasi.applica_proposte_approvate(int) OWNER TO applicatore;
REVOKE ALL ON FUNCTION trasi.applica_proposte_approvate(int) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION trasi.applica_proposte_approvate(int) TO automazioni, ti;

-- ---------------------------------------------------------------------------
-- 7. `scadi_proposte()`: le proposte non trattate diventano `scaduta`.
--    Solo da `proposta` (macchina a stati), con audit via
--    `proposta_02_audit_tg`, idempotente per costruzione.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION trasi.scadi_proposte()
RETURNS int
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = trasi, pg_catalog
AS $fn$
DECLARE
  v_n int := 0;
  r   record;
BEGIN
  FOR r IN
    SELECT p.id FROM trasi.proposta p
     WHERE p.stato = 'proposta'
       AND p.scade_il IS NOT NULL
       AND p.scade_il < current_date
     ORDER BY p.id
       FOR UPDATE SKIP LOCKED
  LOOP
    UPDATE trasi.proposta SET stato = 'scaduta' WHERE id = r.id;
    v_n := v_n + 1;
  END LOOP;
  RETURN v_n;
END;
$fn$;

ALTER FUNCTION trasi.scadi_proposte() OWNER TO applicatore;
REVOKE ALL ON FUNCTION trasi.scadi_proposte() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION trasi.scadi_proposte() TO automazioni, ti;

-- ---------------------------------------------------------------------------
-- 8. `v_da_approvare` — la coda (§4.5). `security_invoker`: il filtro usa il
--    ruolo del CHIAMANTE (dentro una vista definer `current_user` sarebbe il
--    proprietario e il filtro guarderebbe il ruolo sbagliato).
--    Minimizzazione: `proposto_da` non esce (V5/§12).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW trasi.v_da_approvare
WITH (security_invoker = true)
AS
SELECT p.id,
       p.origine,
       p.tipo,
       p.entita,
       p.entita_id,
       p.casa_id,
       c.slug                        AS casa_slug,
       p.fonte_id,
       p.payload,
       p.diff,
       trasi.diff_leggibile(p.diff)  AS diff_leggibile,
       p.motivazione,
       p.stato,
       p.approvatore_ruolo,
       p.proposto_ts,
       p.scade_il,
       (p.scade_il - current_date)   AS giorni_attesa
  FROM trasi.proposta p
  LEFT JOIN trasi.casa c ON c.id = p.casa_id
 WHERE p.stato = 'proposta'
   AND (p.scade_il IS NULL OR p.scade_il >= current_date)
   -- V4 regola 1: la coda mostra solo cio' che il chiamante puo' davvero
   -- decidere. Una proposta propria non e' decidibile (`no_self_approve`).
   AND p.proposto_da IS DISTINCT FROM current_user
   AND ((p.approvatore_ruolo = 'gestore' AND p.casa_id = trasi.casa_corrente())
     OR (p.approvatore_ruolo IN ('at', 'ti') AND current_user IN ('rete', 'ti')));

COMMENT ON VIEW trasi.v_da_approvare IS
  'Coda delle proposte da approvare, filtrata sul ruolo del chiamante (casa_corrente()/rete/ti). Senza proposto_da (V5).';

-- La coda serve a chi decide: i ruoli Casa e la rete. `security_invoker` fa il
-- resto (il filtro e' sul ruolo del chiamante).
GRANT SELECT ON trasi.v_da_approvare TO casa_santaspazio, casa_molo12, casa_erranti,
  casa_buscicchio, casa_sanbao, casa_minimus, casa_pop, casa_bozzano, casa_dream,
  casa_tuturano, rete, ti, shim_rw, metabase_ro, automazioni, applicatore;

-- ---------------------------------------------------------------------------
-- 9. `v_scritture_senza_audit` — contabilita' invece di euristica (B1-PRP-06).
--    Elenca ogni mutazione del dominio che NON ha una riga `audit`
--    corrispondente (`applicata` dal percorso di proposta, `ical_upsert`
--    dall'eccezione iCal). Uso:
--      SELECT count(*) FROM trasi.v_scritture_senza_audit WHERE ts > :t0;
--
--    `aggiornato_da` distingue le scritture: quelle di `trasi_owner` (seed,
--    caricamento iniziale) e dei ruoli che la matrice congelata ammette a
--    scrivere la propria Casa (D1) sono dichiarate, non sospette; una scrittura
--    di dominio da un ruolo qualunque altro senza audit e' una violazione di V4
--    e compare qui. Atteso: 0 righe dopo la batteria B2 e dopo ogni notte.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW trasi.v_scritture_senza_audit
WITH (security_invoker = true)
AS
WITH mut AS (
  SELECT 'luogo'::text AS entita, id, casa_id, aggiornato_ts AS ts, aggiornato_da AS da FROM trasi.luogo
   WHERE aggiornato_ts IS NOT NULL
  UNION ALL
  SELECT 'scheda_servizio', id, casa_id, aggiornato_ts, aggiornato_da FROM trasi.scheda_servizio
   WHERE aggiornato_ts IS NOT NULL
  UNION ALL
  SELECT 'evento', id, casa_id, aggiornato_ts, aggiornato_da FROM trasi.evento
   WHERE aggiornato_ts IS NOT NULL
  UNION ALL
  SELECT 'opportunita', id, casa_id, aggiornato_ts, aggiornato_da FROM trasi.opportunita
   WHERE aggiornato_ts IS NOT NULL
  UNION ALL
  SELECT 'casa', id, id, aggiornato_ts, aggiornato_da FROM trasi.casa
   WHERE aggiornato_ts IS NOT NULL
  -- Attrezzoteca (db/014): `oggetto` è memoria della rete a tutti gli effetti —
  -- nasce e si modifica SOLO via proposta (tipi nuovo_oggetto/modifica_oggetto/
  -- ritira_oggetto), quindi una sua mutazione senza `applicata` è una violazione
  -- di V4 esattamente come per un luogo. `movimento` NON è qui: è l'evento
  -- operativo la cui eccezione è documentata, e la sua contabilità è l'audit
  -- 'conferma_movimento' scritto da `conferma_movimento()` a ogni passaggio di
  -- stato — confrontarlo con `applicata` segnalerebbe ogni prestito legittimo.
  UNION ALL
  SELECT 'oggetto', id, casa_id, aggiornato_ts, aggiornato_da FROM trasi.oggetto
   WHERE aggiornato_ts IS NOT NULL
)
SELECT m.entita, m.id AS entita_id, m.ts, m.da AS scritto_da, m.casa_id
  FROM mut m
 WHERE NOT EXISTS (
         SELECT 1 FROM trasi.audit a
          WHERE a.entita = m.entita
            AND a.entita_id = m.id
            AND a.azione IN (
              -- I tre percorsi che mutano la memoria con una riga di audit
              -- corrispondente: proposta applicata, eccezione iCal, e lo
              -- spostamento di un oggetto fra Case (`conferma_movimento`, che
              -- muta `oggetto.casa_id` e scrive la propria riga — v. §11c).
              'applicata', 'ical_upsert', 'conferma_movimento'))
   -- Scritture dichiarate fuori dal flusso mediato: il seed iniziale (owner) e
   -- la gestione diretta della propria Casa (matrice congelata, D1/§7 riga 390).
   -- Tutto il resto senza audit e' una violazione di V4 e compare qui.
   AND m.da IS DISTINCT FROM 'trasi_owner'
   AND NOT EXISTS (
         SELECT 1 FROM trasi.casa c
          WHERE c.id = m.casa_id
            AND m.da = 'casa_' || replace(c.slug, '-', ''));

COMMENT ON VIEW trasi.v_scritture_senza_audit IS
  'Mutazioni del dominio senza riga di audit corrispondente (B1-PRP-06). Atteso: 0 righe dopo la batteria B2 e dopo ogni notte. Scritture dichiarate fuori flusso: seed (trasi_owner) e gestione diretta della propria Casa (D1).';

-- Contabilita' ispezionabile dagli operatori e dal monitoraggio notturno.
GRANT SELECT ON trasi.v_scritture_senza_audit TO casa_santaspazio, casa_molo12,
  casa_erranti, casa_buscicchio, casa_sanbao, casa_minimus, casa_pop, casa_bozzano,
  casa_dream, casa_tuturano, rete, ti, shim_rw, metabase_ro, automazioni, applicatore;

-- ---------------------------------------------------------------------------
-- 10. Verifica di installazione
-- ---------------------------------------------------------------------------
DO $verify$
DECLARE
  v_n int;
  v_owner text;
BEGIN
  SELECT count(*) INTO v_n FROM pg_trigger
   WHERE tgrelid = 'trasi.proposta'::regclass AND NOT tgisinternal
     AND tgname IN ('proposta_01_transition_tg','proposta_02_audit_tg','proposta_03_diff_tg');
  IF v_n <> 3 THEN
    RAISE EXCEPTION 'B1-proposte/006: attesi 3 trigger su proposta (transizione, audit, diff), trovati %', v_n;
  END IF;

  SELECT count(*) INTO v_n FROM pg_trigger
   WHERE tgrelid = 'trasi.evento'::regclass AND NOT tgisinternal
     AND tgname IN ('scrittura_00_ts','evento_ical_01_audit');
  IF v_n <> 2 THEN
    RAISE EXCEPTION 'B1-proposte/006: attesi 2 trigger su evento (impronta, audit iCal), trovati %', v_n;
  END IF;

  SELECT pg_get_userbyid(proowner) INTO v_owner FROM pg_proc
   WHERE oid = 'trasi.applica_proposte_approvate(int)'::regprocedure;
  IF v_owner <> 'applicatore' THEN
    RAISE EXCEPTION 'B1-proposte/006: applica_proposte_approvate ha owner % invece di applicatore', v_owner;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE oid = 'trasi.scadi_proposte()'::regprocedure
                   AND pg_get_userbyid(proowner) = 'applicatore') THEN
    RAISE EXCEPTION 'B1-proposte/006: scadi_proposte ha owner diverso da applicatore';
  END IF;

  RAISE NOTICE 'B1-proposte/006 applicato: macchina a stati, diff automatico, audit, applica_proposte_approvate (owner applicatore), scadi_proposte, v_da_approvare, v_scritture_senza_audit';
END
$verify$;

-- ============================================================================
-- 11. Schede !NEW — funzioni operative (Fase 0 §2: eccezioni V4 documentate in
--     deployment/README.md, lista chiusa).
--     Dipendono dalle tabelle di db/013_credenziali.sql, db/014_attrezzoteca.sql,
--     db/015_messaggi.sql (apply.sh le applica prima di rieseguire 006).
--
--     Convenzioni uguali al resto del file: SECURITY DEFINER owner `applicatore`,
--     search_path fissato, EXECUTE revocato a PUBLIC e concesso per nome ai soli
--     ruoli che le usano. `session_user` va in audit.eseguito_da (chi si è
--     autenticato); `current_user` dentro è `applicatore` per costruzione.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 10b. Vocabolario dei tipi di proposta: i tre dell'attrezzoteca (US-5.x).
--
-- Perché qui e non in db/001. Il CHECK di `proposta.tipo` è nato con le nove
-- tipologie del dominio di territorio (§7.1 di db/001_schema.sql); i tre tipi
-- dell'attrezzoteca nascono con questo file, che è l'unico che li implementa
-- (§F dello `applica_proposte_approvate`). Senza questo ALTER il vocabolario e
-- l'implementazione divergono in modo silenzioso per chi legge il codice: la
-- `nuovo_oggetto` è un ramo `WHEN` perfettamente scritto che **nessun INSERT
-- può raggiungere**, perché il CHECK rifiuta la riga prima.
-- (Misurato: `INSERT … tipo='nuovo_oggetto'` → `violates check constraint
-- "proposta_tipo_check"`, con il ramo di applicazione già presente.)
--
-- Il vincolo si sostituisce per intero, non si aggiunge: due CHECK sullo stesso
-- campo sarebbero due vocabolari da tenere allineati — la seconda verità che
-- questo progetto rifiuta altrove. Idempotente: DROP + ADD.
-- ---------------------------------------------------------------------------
ALTER TABLE trasi.proposta DROP CONSTRAINT IF EXISTS proposta_tipo_check;
ALTER TABLE trasi.proposta
  ADD CONSTRAINT proposta_tipo_check CHECK (tipo IN (
    -- nove tipi del dominio di territorio (db/001 §7.1, invariati)
    'nuovo_luogo','modifica_luogo','chiudi_luogo','modifica_scheda','nuova_scheda',
    'modifica_evento','nuova_opportunita','promuovi_esterno','modifica_orari_casa',
    -- tre tipi dell'attrezzoteca: nascita/modifica/ritiro di `oggetto`. Il
    -- MOVIMENTO non è qui: è un evento operativo con INSERT diretto e conferma
    -- della Casa ricevente (eccezione V4 documentata in deployment/README.md),
    -- non una proposta.
    'nuovo_oggetto','modifica_oggetto','ritira_oggetto'));

-- `approvatore_default` (db/001) decide chi approva in base al tipo: i tre tipi
-- dell'attrezzoteca non sono nel suo CASE e ricadono su `at` (la rete). Non si
-- ridefinisce — la scelta è già quella giusta e una seconda copia della funzione
-- sarebbe una seconda verità da tenere allineata. La si dichiara qui perché è
-- deliberata: l'oggetto nasce nella Casa ma entra nell'inventario **condiviso**
-- della rete, e chi lo prende in prestito è un'altra Casa. Approva la rete, e
-- resta salva la separazione proponente/approvatore di V4 (una Casa propone,
-- `at` approva).

-- Precondizioni (falliscono con errore parlante se l'ordine di apply non è rispettato).
DO $pre_new$
DECLARE v_missing text;
BEGIN
  SELECT string_agg(x, ', ') INTO v_missing
    FROM unnest(ARRAY['trasi.credenziale_casa','trasi.sessione','trasi.tentativo_login',
                      'trasi.oggetto','trasi.movimento','trasi.messaggio']) x
   WHERE to_regclass(x) IS NULL;
  IF v_missing IS NOT NULL THEN
    RAISE EXCEPTION '006 §11: mancano % — applica prima db/013, db/014, db/015 via apply.sh', v_missing;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pgcrypto') THEN
    RAISE EXCEPTION '006 §11: manca pgcrypto — applica prima db/013_credenziali.sql';
  END IF;
END
$pre_new$;

-- ---------------------------------------------------------------------------
-- 11a. `crea_sessione(p_casa_slug, p_pass)` → uuid | NULL
--      Login unico per CdQ (US-6.1): verifica bcrypt lato DB (niente passlib),
--      anti brute-force (>4 fallimenti/10 min per Casa → NULL + audit login_bloccato),
--      successo → sessione con scadenza dal parametro [P] session_ttl_hours
--      (ripiego 12 h) + audit 'login' + azzeramento dei tentativi della Casa.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION trasi.crea_sessione(p_casa_slug text, p_pass text)
RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = trasi, public, pg_catalog
AS $fn$
DECLARE
  v_casa_id    int;
  v_hash       text;
  v_fallimenti int;
  v_token      uuid;
  v_ttl        interval;
BEGIN
  IF p_casa_slug IS NULL OR p_pass IS NULL THEN
    RETURN NULL;
  END IF;

  SELECT c.id, cc.pass_hash INTO v_casa_id, v_hash
    FROM trasi.casa c
    LEFT JOIN trasi.credenziale_casa cc ON cc.casa_id = c.id
   WHERE c.slug = p_casa_slug;

  -- Casa sconosciuta o senza credenziale: stesso NULL della password errata
  -- (l'endpoint non rivela se lo slug esiste).
  IF v_casa_id IS NULL OR v_hash IS NULL THEN
    RETURN NULL;
  END IF;

  SELECT count(*) INTO v_fallimenti
    FROM trasi.tentativo_login t
   WHERE t.casa_id = v_casa_id
     AND t.ts > now() - interval '10 minutes';

  IF v_fallimenti > 4 THEN
    INSERT INTO trasi.audit (azione, eseguito_da, entita, entita_id, dopo)
    VALUES ('login_bloccato', session_user, 'casa', v_casa_id,
            jsonb_build_object('casa_slug', p_casa_slug, 'fallimenti_10min', v_fallimenti));
    RETURN NULL;
  END IF;

  IF crypt(p_pass, v_hash) <> v_hash THEN
    INSERT INTO trasi.tentativo_login (casa_id) VALUES (v_casa_id);
    INSERT INTO trasi.audit (azione, eseguito_da, entita, entita_id, dopo)
    VALUES ('login_fallito', session_user, 'casa', v_casa_id,
            jsonb_build_object('casa_slug', p_casa_slug));
    RETURN NULL;
  END IF;

  v_ttl := make_interval(hours => COALESCE(trasi.p_int('session_ttl_hours'), 12));
  DELETE FROM trasi.tentativo_login t WHERE t.casa_id = v_casa_id;
  INSERT INTO trasi.sessione (casa_id, scade_ts)
  VALUES (v_casa_id, now() + v_ttl)
  RETURNING token INTO v_token;

  INSERT INTO trasi.audit (azione, eseguito_da, entita, entita_id, dopo)
  VALUES ('login', session_user, 'casa', v_casa_id,
          jsonb_build_object('casa_slug', p_casa_slug, 'scade_ts', now() + v_ttl));
  RETURN v_token;
END;
$fn$;

ALTER FUNCTION trasi.crea_sessione(text, text) OWNER TO applicatore;
REVOKE ALL ON FUNCTION trasi.crea_sessione(text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION trasi.crea_sessione(text, text) TO shim_rw, applicatore, automazioni;

-- ---------------------------------------------------------------------------
-- 11b. `registra_richiesta_operatore(...)` → bigint
--      Eccezione V4 documentata (Fase 0 §2): la registrazione avviene DURANTE il
--      colloquio e non può attendere la coda di approvazione. Insert + audit in
--      una transazione; errori parlanti P0001 su vocabolario e destinazione
--      (lo shim li mappa in 422; i CHECK di tabella restano la seconda barriera).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION trasi.registra_richiesta_operatore(
  p_casa_slug         text,
  p_categoria         text,
  p_esito             text,
  p_destinazione_id   integer DEFAULT NULL,
  p_destinazione_nota text    DEFAULT NULL
) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = trasi, public, pg_catalog
AS $fn$
DECLARE
  v_casa_id int;
  v_id      bigint;
BEGIN
  SELECT c.id INTO v_casa_id FROM trasi.casa c WHERE c.slug = p_casa_slug;
  IF v_casa_id IS NULL THEN
    RAISE EXCEPTION 'casa % sconosciuta: la richiesta non si registra (controllare lo slug)', p_casa_slug
      USING ERRCODE = 'P0001';
  END IF;
  IF p_categoria IS NULL OR p_categoria NOT IN ('orientamento','servizi_sociali','fiscale_isee','lavoro','abitare',
                                                'salute','interculturale','ascolto_solitudine','eventi_attivita','altro') THEN
    RAISE EXCEPTION 'categoria % non ammessa: vocabolario chiuso (orientamento, servizi_sociali, fiscale_isee, lavoro, abitare, salute, interculturale, ascolto_solitudine, eventi_attivita, altro)', COALESCE(p_categoria, '(vuota)')
      USING ERRCODE = 'P0001';
  END IF;
  IF p_esito IS NULL OR p_esito NOT IN ('risolta','inviata_altrove','non_trovata','rinviata') THEN
    RAISE EXCEPTION 'esito % non ammesso (risolta, inviata_altrove, non_trovata, rinviata)', COALESCE(p_esito, '(vuoto)')
      USING ERRCODE = 'P0001';
  END IF;
  IF p_esito = 'inviata_altrove' AND p_destinazione_id IS NULL AND NULLIF(btrim(COALESCE(p_destinazione_nota,'')), '') IS NULL THEN
    RAISE EXCEPTION 'esito «inviata_altrove» senza destinazione: indicare destinazione_id oppure destinazione_nota, altrimenti la registrazione non dice dove è stata indirizzata la persona'
      USING ERRCODE = 'P0001';
  END IF;
  IF p_destinazione_id IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM trasi.luogo l WHERE l.id = p_destinazione_id AND l.chiuso_il IS NULL) THEN
    RAISE EXCEPTION 'destinazione_id % non corrisponde a un luogo della memoria della rete', p_destinazione_id
      USING ERRCODE = 'P0001';
  END IF;

  INSERT INTO trasi.richiesta (casa_id, categoria, esito, destinazione_id, destinazione_nota)
  VALUES (v_casa_id, p_categoria, p_esito, p_destinazione_id, NULLIF(btrim(COALESCE(p_destinazione_nota,'')), ''))
  RETURNING id INTO v_id;

  INSERT INTO trasi.audit (azione, eseguito_da, entita, entita_id, dopo)
  SELECT 'registra_richiesta', session_user, 'richiesta', r.id, to_jsonb(r)
    FROM trasi.richiesta r WHERE r.id = v_id;

  RETURN v_id;
END;
$fn$;

ALTER FUNCTION trasi.registra_richiesta_operatore(text, text, text, integer, text) OWNER TO applicatore;
REVOKE ALL ON FUNCTION trasi.registra_richiesta_operatore(text, text, text, integer, text) FROM PUBLIC;
-- I ruoli **Casa** devono poterla eseguire, non solo `shim_rw`, ed è il punto che rende la funzione
-- raggiungibile dall'area operatore. La sessione dello shim esegue `SET LOCAL ROLE casa_<slug>`
-- (`auth.dipendenza_sessione_corrente`) per far decidere la RLS come in ogni altra via: da quel
-- momento i privilegi effettivi sono quelli del **ruolo Casa**, e `EXECUTE` concesso al solo
-- `shim_rw` non basta. Misurato: `POST /op/registra_richiesta` con sessione valida →
-- `permission denied for function registra_richiesta_operatore`; `has_function_privilege` dava
-- `casa_sanbao: false` e `shim_rw: true`. Concederlo ai dieci ruoli Casa non allarga il perimetro:
-- la funzione è SECURITY DEFINER e prende lo slug della Casa come parametro, ma l'INSERT che esegue
-- va su `trasi.richiesta`, dove la RLS impone `casa_id = casa_corrente()` — cioè un operatore non
-- può registrare a nome di un'altra Casa, indipendentemente dal privilegio sulla funzione.
GRANT EXECUTE ON FUNCTION trasi.registra_richiesta_operatore(text, text, text, integer, text)
  TO shim_rw, applicatore, automazioni,
     casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano;

-- ---------------------------------------------------------------------------
-- 11c. `conferma_movimento(p_movimento, p_ruolo)` → void
--      L'unica via di UPDATE di `movimento` (tabella senza policy UPDATE per i
--      client): decide la Casa RICEVENTE sul prestito proposto, e la Casa
--      CEDENTE (o rete/ti) sul rientro con condizione. Errori P0001 parlanti V6.
--      `p_ruolo` è il ruolo DB ricavato dalla sessione (mai dal body libero).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION trasi.conferma_movimento(p_movimento integer, p_ruolo text)
RETURNS void
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = trasi, public, pg_catalog
AS $fn$
DECLARE
  v_mov     trasi.movimento%ROWTYPE;
  v_casa_id int;
  v_prima   jsonb;
  v_ogg_prima jsonb;
BEGIN
  SELECT rc.casa_id INTO v_casa_id FROM trasi.ruolo_casa rc WHERE rc.ruolo = p_ruolo;
  IF p_ruolo IS NULL OR (v_casa_id IS NULL AND p_ruolo NOT IN ('rete','ti','applicatore')) THEN
    RAISE EXCEPTION 'ruolo % non riconosciuto: la conferma spetta alla Casa ricevente', COALESCE(p_ruolo, '(vuoto)')
      USING ERRCODE = 'P0001';
  END IF;

  SELECT m.* INTO v_mov FROM trasi.movimento m WHERE m.id = p_movimento;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'movimento % inesistente', p_movimento
      USING ERRCODE = 'P0001';
  END IF;
  v_prima := to_jsonb(v_mov);
  -- Fotografia dell'oggetto PRIMA dello spostamento: serve all'audit che si scrive
  -- in coda. `snapshot_entita` non si usa qui perché è STABLE e leggerebbe lo stato
  -- già mutato; qui la lettura è esplicita e avviene prima delle UPDATE.
  SELECT to_jsonb(o) INTO v_ogg_prima FROM trasi.oggetto o WHERE o.id = v_mov.oggetto_id;

  CASE v_mov.stato
    WHEN 'proposto' THEN
      IF p_ruolo NOT IN ('rete','ti') AND v_casa_id IS DISTINCT FROM v_mov.a_casa_id THEN
        RAISE EXCEPTION 'la conferma del movimento % spetta alla Casa ricevente (%), non a %: la decisione resta umana (V6)',
          p_movimento,
          (SELECT c.slug FROM trasi.casa c WHERE c.id = v_mov.a_casa_id),
          p_ruolo
          USING ERRCODE = 'P0001';
      END IF;
      UPDATE trasi.movimento m
         SET stato = 'confermato'
       WHERE m.id = p_movimento;
      UPDATE trasi.oggetto o SET casa_id = v_mov.a_casa_id WHERE o.id = v_mov.oggetto_id;
    WHEN 'confermato' THEN
      -- Il rientro chiude il prestito: lo marca la Casa cedente (o rete/ti),
      -- riportando l'oggetto alla Casa d'origine e registrando la condizione.
      IF p_ruolo NOT IN ('rete','ti') AND v_casa_id IS DISTINCT FROM v_mov.da_casa_id THEN
        RAISE EXCEPTION 'il rientro del movimento % lo marca la Casa cedente (%), non %',
          p_movimento,
          (SELECT c.slug FROM trasi.casa c WHERE c.id = v_mov.da_casa_id),
          p_ruolo
          USING ERRCODE = 'P0001';
      END IF;
      UPDATE trasi.movimento m
         SET stato = 'rientrato',
             condizione_rientro = (SELECT o.condizione FROM trasi.oggetto o WHERE o.id = v_mov.oggetto_id)
       WHERE m.id = p_movimento;
      UPDATE trasi.oggetto o SET casa_id = v_mov.da_casa_id WHERE o.id = v_mov.oggetto_id;
    ELSE
      RAISE EXCEPTION 'il movimento % è in stato ''%'': nessuna conferma possibile (conferma solo da ''proposto'', rientro solo da ''confermato'')',
        p_movimento, v_mov.stato
        USING ERRCODE = 'P0001';
  END CASE;

  INSERT INTO trasi.audit (azione, eseguito_da, entita, entita_id, prima, dopo)
  SELECT 'conferma_movimento', session_user, 'movimento', m.id, v_prima, to_jsonb(m)
    FROM trasi.movimento m WHERE m.id = p_movimento;

  -- L'oggetto cambia Casa insieme al movimento (le due UPDATE sopra): anche lui
  -- ha la sua riga. Senza, `v_scritture_senza_audit` — che contabilizza `oggetto`
  -- come il resto della memoria — segnalerebbe **ogni prestito legittimo** come
  -- violazione di V4: il falso positivo che rende inutile la vista quando poi
  -- segnala una violazione vera. Una sola riga per movimento, scritta dopo il
  -- CASE: entrambi i rami che arrivano qui hanno spostato l'oggetto (i rifiuti
  -- sollevano eccezione prima).
  INSERT INTO trasi.audit (azione, eseguito_da, entita, entita_id, prima, dopo)
  SELECT 'conferma_movimento', session_user, 'oggetto', o.id, v_ogg_prima, to_jsonb(o)
    FROM trasi.oggetto o WHERE o.id = v_mov.oggetto_id;
END;
$fn$;

ALTER FUNCTION trasi.conferma_movimento(integer, text) OWNER TO applicatore;
REVOKE ALL ON FUNCTION trasi.conferma_movimento(integer, text) FROM PUBLIC;
-- Come `registra_richiesta_operatore`: la sessione opera come ruolo **Casa** (`SET LOCAL ROLE`), quindi
-- il privilegio va concesso ai dieci ruoli, non al solo `shim_rw`. Senza, il pulsante «Conferma
-- ricezione» della UI (`POST /op/movimento/{id}/conferma`) rispondeva «permission denied for function
-- conferma_movimento», e la transitività del prestito — cioè la tutela che sostituisce V4 in questa
-- eccezione — non poteva avvenire. La verifica di chi può confermare **non** è qui: è dentro la
-- funzione (`p_ruolo`, e la casa del movimento), che è il posto in cui la regola vive.
GRANT EXECUTE ON FUNCTION trasi.conferma_movimento(integer, text)
  TO shim_rw, applicatore, automazioni,
     casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano;

-- ---------------------------------------------------------------------------
-- 11d. `scadi_messaggi()` → int — retention chat interna (US-7, privacy):
--      cancella i messaggi LETTI oltre messaggi_retention_days (ripiego 90).
--      I non-letti non si toccano: una segnalazione PA non sparisce perché vecchia.
--      Qui dentro anche le pulizie di contorno del login: sessioni scadute e
--      tentativi oltre la finestra di 10 minuti (stesso passo notturno, notte.sh).
--      Ritorna quante righe sono state cancellate in totale.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION trasi.scadi_messaggi()
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = trasi, public, pg_catalog
AS $fn$
DECLARE
  v_retention interval := make_interval(days => COALESCE(trasi.p_int('messaggi_retention_days'), 90));
  v_n_msg  int;
  v_n_sess int;
  v_n_tent int;
BEGIN
  DELETE FROM trasi.messaggio m
   WHERE m.letto_ts IS NOT NULL
     AND m.letto_ts < now() - v_retention;
  GET DIAGNOSTICS v_n_msg = ROW_COUNT;

  DELETE FROM trasi.sessione s WHERE s.scade_ts < now();
  GET DIAGNOSTICS v_n_sess = ROW_COUNT;

  DELETE FROM trasi.tentativo_login t WHERE t.ts < now() - interval '10 minutes';
  GET DIAGNOSTICS v_n_tent = ROW_COUNT;

  RETURN v_n_msg + v_n_sess + v_n_tent;
END;
$fn$;

ALTER FUNCTION trasi.scadi_messaggi() OWNER TO applicatore;
REVOKE ALL ON FUNCTION trasi.scadi_messaggi() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION trasi.scadi_messaggi() TO automazioni, ti;

-- ---------------------------------------------------------------------------
-- 11e. Verifica di installazione delle funzioni !NEW
-- ---------------------------------------------------------------------------
DO $verify_new$
DECLARE v_mancanti text;
BEGIN
  SELECT string_agg(f, ', ') INTO v_mancanti
    FROM unnest(ARRAY['trasi.crea_sessione(text,text)',
                      'trasi.registra_richiesta_operatore(text,text,text,integer,text)',
                      'trasi.conferma_movimento(integer,text)',
                      'trasi.scadi_messaggi()']) f
   WHERE to_regprocedure(f) IS NULL;
  IF v_mancanti IS NOT NULL THEN
    RAISE EXCEPTION '006 §11: funzioni mancanti dopo l''installazione: %', v_mancanti;
  END IF;
  IF EXISTS (SELECT 1 FROM pg_proc p JOIN pg_roles r ON r.oid = p.proowner
              WHERE p.oid IN ('trasi.crea_sessione(text,text)'::regprocedure,
                              'trasi.registra_richiesta_operatore(text,text,text,integer,text)'::regprocedure,
                              'trasi.conferma_movimento(integer,text)'::regprocedure,
                              'trasi.scadi_messaggi()'::regprocedure)
                AND r.rolname <> 'applicatore') THEN
    RAISE EXCEPTION '006 §11: una funzione operativa non ha owner applicatore';
  END IF;
  IF trasi.snapshot_entita('oggetto', NULL) IS NOT NULL THEN
    RAISE EXCEPTION '006 §11: snapshot_entita(oggetto, NULL) deve essere NULL';
  END IF;
  RAISE NOTICE '006 §11 applicato: entita ''oggetto'' in snapshot/whitelist, tipi nuovo_oggetto|modifica_oggetto|ritira_oggetto, crea_sessione, registra_richiesta_operatore, conferma_movimento, scadi_messaggi (owner applicatore)';
END
$verify_new$;
