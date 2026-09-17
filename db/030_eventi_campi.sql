-- Trasi — db/030_eventi_campi.sql  (delta «i campi che l'operatore deve poter dire di un evento»)
--
-- db/025 ha aggiunto a `trasi.evento` costo, fascia_eta, tag e `ricorrenza`, ma
-- due cose restavano fuori, ed entrambe sono emerse da una domanda reale in chat
-- che l'assistente non sapeva soddisfare («è gratuito? serve prenotare?», «ogni
-- lunedì di maggio»):
--
--   1. `ricorrenza_fine` — FINO A QUANDO si ripete un evento ricorrente.
--      `ricorrenza` dice ogni quanto (settimanale/…); senza un termine, «ogni
--      lunedì di maggio» non è esprimibile e la ripetizione sarebbe infinita.
--
--   2. `prenotazione` (+ `prenotazione_nota`) — se serve prenotare e come.
--      Era una lacuna: l'assistente, richiesto, non aveva il dato e ripiegava su
--      ricerche inutili invece di dire «non lo so». Il dato va chiesto a chi crea
--      l'evento, non indovinato dopo.
--
-- Perché estende i campi esistenti e non introduce una seconda convenzione: la
-- ricorrenza resta l'enum di db/025 (una regola RRULE parallela sarebbe un secondo
-- modo di dire la stessa cosa, cioè un difetto). Qui si aggiunge solo il mancante.
--
-- Le occorrenze NON si materializzano (niente N righe con lo stesso uid_ical): si
-- calcolano da `inizio` + `ricorrenza`, e `ricorrenza_fine` è il limite del calcolo.
--
-- Additivo e idempotente. La scrittura è coperta dal GRANT di tabella già concesso
-- ai ruoli Casa (db/002: `GRANT INSERT, UPDATE, DELETE ON trasi.evento`), come per
-- `costo`/`tag` di db/025: nessun GRANT di colonna in più. Nessun dato personale:
-- `prenotazione_nota` è testo di servizio (il filtro PII dello shim rifiuta numeri).

\set ON_ERROR_STOP on
\set VERBOSITY terse

SET ROLE trasi_owner;
SET search_path = trasi, public, pg_temp;

-- ---------------------------------------------------------------------------
-- 0. Precondizioni: la colonna `ricorrenza` di db/025 deve esistere
-- ---------------------------------------------------------------------------
DO $pre$
BEGIN
  IF to_regclass('trasi.evento') IS NULL THEN
    RAISE EXCEPTION '030_eventi_campi: manca trasi.evento — applica prima db/001_schema.sql';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.columns
                  WHERE table_schema = 'trasi' AND table_name = 'evento' AND column_name = 'ricorrenza') THEN
    RAISE EXCEPTION '030_eventi_campi: manca trasi.evento.ricorrenza — applica prima db/025_campi_processi.sql';
  END IF;
END
$pre$;

-- ---------------------------------------------------------------------------
-- 1. Fine della ricorrenza
-- ---------------------------------------------------------------------------
ALTER TABLE trasi.evento ADD COLUMN IF NOT EXISTS ricorrenza_fine date;

-- Un termine ha senso solo per un evento ricorrente. L'ordine `ricorrenza_fine >= inizio` NON sta qui ma nello
-- shim (422): `inizio::date` è una conversione timestamptz→date dipendente dal fuso (STABLE), e un CHECK ammette
-- solo espressioni immutabili — la stessa ragione per cui `crea_evento`, non il database, verifica `fine >= inizio`.
ALTER TABLE trasi.evento DROP CONSTRAINT IF EXISTS evento_ricorrenza_fine_check;
ALTER TABLE trasi.evento ADD CONSTRAINT evento_ricorrenza_fine_check
  CHECK (ricorrenza_fine IS NULL OR ricorrenza IS NOT NULL);

COMMENT ON COLUMN trasi.evento.ricorrenza_fine IS
  'Ultimo giorno in cui la ricorrenza produce occorrenze (UNTIL); NULL = senza termine dichiarato. Ha senso '
  'solo con ricorrenza non nulla. Le occorrenze si calcolano da inizio, non si memorizzano.';

-- ---------------------------------------------------------------------------
-- 2. Prenotazione
-- ---------------------------------------------------------------------------
-- `prenotazione` è terzo stato apposta: TRUE = serve, FALSE = non serve, NULL = non noto. Un booleano NOT NULL
-- costringerebbe a inventare un default, e «non lo so» diventerebbe «non serve» — cioè un dato indovinato, che è
-- esattamente il difetto da cui nasce questo campo. `prenotazione_nota` dice COME (es. «posti limitati, in
-- biglietteria»): testo di servizio, senza dati personali (il filtro PII dello shim rifiuta telefoni/email).
ALTER TABLE trasi.evento ADD COLUMN IF NOT EXISTS prenotazione      boolean;
ALTER TABLE trasi.evento ADD COLUMN IF NOT EXISTS prenotazione_nota text;

COMMENT ON COLUMN trasi.evento.prenotazione IS
  'Serve prenotare? TRUE = sì, FALSE = no, NULL = non noto. Il terzo stato distingue «non serve» da «non lo so».';
COMMENT ON COLUMN trasi.evento.prenotazione_nota IS
  'Come prenotare (es. «posti limitati, in biglietteria»); testo di servizio, senza dati personali.';

-- ---------------------------------------------------------------------------
-- 3. Verifica
-- ---------------------------------------------------------------------------
DO $post$
DECLARE v_mancanti text;
BEGIN
  SELECT string_agg(x, ', ') INTO v_mancanti
    FROM unnest(ARRAY['ricorrenza_fine','prenotazione','prenotazione_nota']) x
   WHERE NOT EXISTS (SELECT 1 FROM information_schema.columns
                      WHERE table_schema = 'trasi' AND table_name = 'evento' AND column_name = x);
  IF v_mancanti IS NOT NULL THEN
    RAISE EXCEPTION '030_eventi_campi: colonne assenti dopo la ALTER: %', v_mancanti;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'evento_ricorrenza_fine_check') THEN
    RAISE EXCEPTION '030_eventi_campi: vincolo evento_ricorrenza_fine_check assente';
  END IF;
END
$post$;

RESET ROLE;
