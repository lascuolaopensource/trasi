-- Trasi — db/tests/t_report.sql · R01…R08
-- La regola di Processi sui report mensili: **gli operatori delle Case possono solo commentare i
-- report, non correggerli o modificarli** (specifica del gruppo Processi; foglio «4.3 Report
-- Mensili» del documento di architettura dei campi).
--
-- Convenzione della batteria: PASS = NOTICE, FAIL = EXCEPTION; i ruoli sono applicativi (SET ROLE),
-- mai superuser. `run.sh` avvolge il file in BEGIN/ROLLBACK: nessun residuo.
--
-- **Perché questi test esistono.** La regola non è una convenzione documentata: è un privilegio
-- **assente** (`GRANT`). Un privilegio assente è invisibile leggendo il codice applicativo — si
-- scopre solo provando a scrivere. Questi test sono il modo in cui la regola resta vera quando
-- qualcuno, fra sei mesi, aggiunge un `GRANT UPDATE` per far passare una funzione.
\set ON_ERROR_STOP on
\pset pager off

-- Fixture: un report per San Bao, generato come lo genera il flusso (`automazioni`). In transazione:
-- `run.sh` chiude in ROLLBACK, quindi non resta nulla nel database reale.
--
-- **Niente `ON CONFLICT DO NOTHING`.** Quel ramo richiede di poter **leggere** la riga in conflitto, e
-- `automazioni` non è fra i ruoli della policy `rep_sel` (legge il report chi è della Casa, più `rete`/`ti`):
-- misurato, `ON CONFLICT` → `new row violates row-level security policy`, un errore che sembra un problema
-- di INSERT ed è un problema di lettura. Il flusso, in esercizio, deve quindi **sapere** se il report esiste
-- (`SELECT` prima, o il mese già rendicontato nei `flusso_run`) invece di affidarsi al conflitto — ed è la
-- stessa conclusione scritta in `db/024` a proposito di `DO UPDATE`.
DO $$
DECLARE v_id bigint; n integer;
BEGIN
  -- La pulizia preventiva gira **prima** di indossare il ruolo: `automazioni` non ha DELETE su `report`
  -- (e non deve averlo — è la regola di Processi). Serve a rendere il file rieseguibile anche fuori dalla
  -- batteria, dove la transazione di `run.sh` non c'è.
  --
  -- Il mese della fixture è il **mese appena chiuso**, non il corrente: il ciclo mensile (`P2.1`)
  -- rendiconta il mese chiuso, e la batteria deve provare ciò che il flusso scrive davvero. Il
  -- report reale del mese chiuso (scritto dal ciclo, non da qui) si sposta via in una transazione
  -- che `run.sh` riepilogherà in ROLLBACK.
  DELETE FROM trasi.report
   WHERE casa_id = (SELECT id FROM trasi.casa WHERE slug='san-bao')
     AND mese = date_trunc('month', current_date - interval '1 month')::date;

  EXECUTE 'SET LOCAL ROLE automazioni';
  INSERT INTO trasi.report (casa_id, mese, ambito, contenuti, csv)
  SELECT (SELECT id FROM trasi.casa WHERE slug='san-bao'), date_trunc('month', current_date - interval '1 month')::date,
         'casa', jsonb_build_object('richieste', 12, 'senza_risposta', 2), 'casa,categoria,esito,n';
  EXECUTE 'RESET ROLE';
  SELECT count(*) INTO n FROM trasi.report
   WHERE casa_id = (SELECT id FROM trasi.casa WHERE slug='san-bao')
     AND mese = date_trunc('month', current_date - interval '1 month')::date;

  IF n <> 1 THEN RAISE EXCEPTION 'FAIL R00 — fixture: atteso 1 report, trovati %', n; END IF;
END $$;

-- R01 · il flusso GENERA il report (INSERT): è la sua funzione -------------------------------
DO $$
DECLARE n integer;
BEGIN
  DELETE FROM trasi.report WHERE ambito='osservatorio' AND mese = date_trunc('month', current_date)::date;
  EXECUTE 'SET LOCAL ROLE automazioni';
  INSERT INTO trasi.report (casa_id, mese, ambito, contenuti)
  VALUES (NULL, date_trunc('month', current_date)::date,
          'osservatorio', jsonb_build_object('aggregato', true));
  EXECUTE 'RESET ROLE';
  SELECT count(*) INTO n FROM trasi.report
   WHERE ambito='osservatorio' AND mese = date_trunc('month', current_date)::date;
  IF n <> 1 THEN RAISE EXCEPTION 'FAIL R01 — il flusso non ha potuto generare il report (trovati %)', n; END IF;
  RAISE NOTICE 'PASS R01 — automazioni genera un report (INSERT permesso, INSERT è il suo compito)';
END $$;

-- R02 · LA REGOLA: una Casa NON può correggere il report -------------------------------------
-- È il test centrale del file. Deve fallire con `insufficient_privilege` (42501): il privilegio
-- `UPDATE` **non esiste** per i ruoli Casa. Se questo test passa, la specifica di Processi è violata.
DO $$
DECLARE bloccato boolean := false;
BEGIN
  EXECUTE 'SET LOCAL ROLE casa_sanbao';
  BEGIN
    UPDATE trasi.report SET contenuti = '{"manomesso":true}'::jsonb
     WHERE casa_id = (SELECT id FROM trasi.casa WHERE slug='san-bao');
    bloccato := false;
  EXCEPTION WHEN insufficient_privilege THEN bloccato := true;
  END;
  EXECUTE 'RESET ROLE';
  IF NOT bloccato THEN
    RAISE EXCEPTION 'FAIL R02 — una Casa ha potuto CORREGGERE un report: la specifica di Processi vieta di modificarlo';
  END IF;
  RAISE NOTICE 'PASS R02 — una Casa non può correggere il report (42501: il privilegio non esiste)';
END $$;

-- R03 · nessuna Casa può nemmeno cancellarlo -------------------------------------------------
DO $$
DECLARE bloccato boolean := false;
BEGIN
  EXECUTE 'SET LOCAL ROLE casa_sanbao';
  BEGIN
    DELETE FROM trasi.report WHERE casa_id = (SELECT id FROM trasi.casa WHERE slug='san-bao');
    bloccato := false;
  EXCEPTION WHEN insufficient_privilege THEN bloccato := true;
  END;
  EXECUTE 'RESET ROLE';
  IF NOT bloccato THEN RAISE EXCEPTION 'FAIL R03 — una Casa ha potuto CANCELLARE un report'; END IF;
  RAISE NOTICE 'PASS R03 — una Casa non può cancellare il report (42501)';
END $$;

-- R04 · il flusso NON può correggere il report che ha generato -------------------------------
-- Vale anche per chi lo scrive: `automazioni` ha INSERT e **non** UPDATE. La regola non è «gli
-- operatori non correggono» ma «il report, una volta generato, non si corregge» — altrimenti il
-- rendiconto di una Casa sarebbe riscrivibile dal flusso che lo produce.
DO $$
DECLARE bloccato boolean := false;
BEGIN
  EXECUTE 'SET LOCAL ROLE automazioni';
  BEGIN
    UPDATE trasi.report SET contenuti = '{"riscritto":true}'::jsonb
     WHERE casa_id = (SELECT id FROM trasi.casa WHERE slug='san-bao');
    bloccato := false;
  EXCEPTION WHEN insufficient_privilege THEN bloccato := true;
  END;
  EXECUTE 'RESET ROLE';
  IF NOT bloccato THEN RAISE EXCEPTION 'FAIL R04 — il flusso ha potuto RISCRIVERE il report che ha generato'; END IF;
  RAISE NOTICE 'PASS R04 — nemmeno il flusso corregge un report esistente (solo INSERT: UPDATE negato dal GRANT)';
END $$;

-- R05 · la Casa LEGGE il proprio report, numeri non mascherati -------------------------------
-- Il report per Casa è il rendiconto della Casa a sé stessa (foglio 4.3-B): i propri sportelli sono
-- suoi, e i numeri sono pieni. Il k-anonimato protegge i conteggi **sulle persone** visti da altri.
DO $$
DECLARE v_richieste text;
BEGIN
  EXECUTE 'SET LOCAL ROLE casa_sanbao';
  SELECT contenuti->>'richieste' INTO v_richieste FROM trasi.report
   WHERE casa_id = (SELECT id FROM trasi.casa WHERE slug='san-bao') AND ambito='casa';
  EXECUTE 'RESET ROLE';
  IF v_richieste IS NULL THEN RAISE EXCEPTION 'FAIL R05 — la Casa non legge il proprio report'; END IF;
  RAISE NOTICE 'PASS R05 — la Casa legge il proprio report (richieste=%)', v_richieste;
END $$;

-- R06 · la Casa COMMENTA il report: è l'unica scrittura che le è concessa --------------------
DO $$
DECLARE n integer;
BEGIN
  EXECUTE 'SET LOCAL ROLE casa_sanbao';
  INSERT INTO trasi.commento (entita, entita_id, casa_id, testo)
  SELECT 'report', id, trasi.casa_corrente(), 'R06: i numeri tornano con il registro di sportello'
    FROM trasi.report
   WHERE casa_id = (SELECT id FROM trasi.casa WHERE slug='san-bao') AND ambito='casa'
     AND mese = date_trunc('month', current_date - interval '1 month')::date;
  GET DIAGNOSTICS n = ROW_COUNT;
  EXECUTE 'RESET ROLE';
  IF n <> 1 THEN RAISE EXCEPTION 'FAIL R06 — commento = % righe, attesa 1', n; END IF;
  RAISE NOTICE 'PASS R06 — la Casa commenta il report (1 riga): commentare è concesso, correggere no';
END $$;

-- R07 · una Casa NON commenta a nome di un'altra ---------------------------------------------
-- Il `casa_id` del commento viene dall'identità, mai dal corpo della richiesta (principio 3): la
-- WITH CHECK della policy `com_ins_casa` confronta con `casa_corrente()` e respinge.
DO $$
DECLARE bloccato boolean := false;
BEGIN
  EXECUTE 'SET LOCAL ROLE casa_bozzano';
  BEGIN
    INSERT INTO trasi.commento (entita, entita_id, casa_id, testo)
    VALUES ('report', 1, (SELECT id FROM trasi.casa WHERE slug='san-bao'), 'R07: commento a nome altrui');
    bloccato := false;
  EXCEPTION WHEN insufficient_privilege THEN bloccato := true;
  END;
  EXECUTE 'RESET ROLE';
  IF NOT bloccato THEN RAISE EXCEPTION 'FAIL R07 — una Casa ha commentato a nome di un''altra'; END IF;
  RAISE NOTICE 'PASS R07 — commento a nome di un''altra Casa respinto (WITH CHECK su casa_corrente())';
END $$;

-- R08 · l'impronta di scrittura sul commento è il ruolo, non un valore scelto ----------------
-- Senza `commento_00_ts` la tabella non direbbe chi ha scritto, e la contabilità di V4
-- (`v_scritture_senza_audit`) non potrebbe distinguere una scrittura dichiarata da una sospetta.
DO $$
DECLARE v_da text;
BEGIN
  EXECUTE 'SET LOCAL ROLE casa_sanbao';
  INSERT INTO trasi.commento (entita, entita_id, casa_id, testo)
  SELECT 'report', id, trasi.casa_corrente(), 'R08: impronta di scrittura'
    FROM trasi.report WHERE casa_id=(SELECT id FROM trasi.casa WHERE slug='san-bao');
  SELECT aggiornato_da INTO v_da FROM trasi.commento WHERE testo LIKE 'R08:%';
  EXECUTE 'RESET ROLE';
  IF v_da <> 'casa_sanbao' THEN
    RAISE EXCEPTION 'FAIL R08 — aggiornato_da = %, atteso casa_sanbao (il trigger non ha timbrato)', coalesce(v_da,'NULL');
  END IF;
  RAISE NOTICE 'PASS R08 — il commento porta l''impronta del ruolo che l''ha scritto (%)', v_da;
END $$;

-- R09 · ISOLAMENTO: una Casa NON legge il report di un'altra --------------------------------
-- La correzione del 2026-09-17. La prima versione di `rep_sel` era `USING (true)`: il report per Casa
-- contiene i numeri **pieni** dei propri sportelli, mentre `v_confronto_case` li espone **mascherati**
-- (`bozzano → '<5'`). Con la lettura ampia, ogni Casa avrebbe letto i numeri non mascherati delle altre e
-- il k-anonimato di §12 sarebbe stato aggirabile per via laterale. La protezione esiste solo se **tutte**
-- le vie la rispettano.
DO $$
DECLARE v_casa integer; v_altra integer; v_visti integer; v_bozzano integer;
BEGIN
  SELECT id INTO v_casa   FROM trasi.casa WHERE slug='san-bao';
  SELECT id INTO v_altra  FROM trasi.casa WHERE slug='bozzano';

  -- Riga di report per l'ALTRA Casa, inserita come flusso.
  DELETE FROM trasi.report WHERE casa_id = v_altra AND mese = date_trunc('month', current_date)::date;
  EXECUTE 'SET LOCAL ROLE automazioni';
  INSERT INTO trasi.report (casa_id, mese, ambito, contenuti)
  VALUES (v_altra, date_trunc('month', current_date)::date, 'casa', jsonb_build_object('richieste', 3));
  EXECUTE 'RESET ROLE';

  EXECUTE 'SET LOCAL ROLE casa_sanbao';
  SELECT count(*) INTO v_visti FROM trasi.report WHERE casa_id = v_altra;
  SELECT count(*) INTO v_bozzano FROM trasi.v_report WHERE casa_slug = 'bozzano';
  EXECUTE 'RESET ROLE';

  IF v_visti <> 0 OR v_bozzano <> 0 THEN
    RAISE EXCEPTION 'FAIL R09 — san-bao vede % righe del report di bozzano (via vista: %): il k-anonimato è aggirabile',
      v_visti, v_bozzano;
  END IF;
  RAISE NOTICE 'PASS R09 — una Casa non vede il report di un''altra (0 righe, anche via v_report)';
END $$;
