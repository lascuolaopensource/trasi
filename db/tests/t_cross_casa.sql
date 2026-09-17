-- Trasi — db/tests/t_cross_casa.sql · lettura cross-Casa e scrittura solo-propri (US-1/O3)
--
-- La regola di principio 3 («tutti leggono tutto, ognuno scrive il proprio») applicata agli EVENTI:
--   · la LETTURA degli eventi di qualunque Casa è libera (RLS `evento_sel` = USING(true) per tutti
--     i ruoli Casa + rete): è il palinsesto di rete (US-1), e `eventi_oggi?casa=<slug>` si affida a
--     questo comportamento del DB;
--   · la SCRITTURA resta della Casa: nessun ruolo Casa inserisce/aggiorna/cancella righe altrui.
--
-- Perché un file dedicato: `t_rls.sql` copre le matrici generiche di B1, ma il caso «lettura
-- cross-Casa ammessa, scrittura cross-Casa negata» sugli EVENTI non era provato da nessuna parte —
-- e una policy `evento_ins_casa` senza WITH CHECK visibile in `pg_policy` è esattamente il posto
-- dove una regressione silenziosa si nasconderebbe (misurato 2026-09-17: Postgres blocca l'INSERT
-- altrui per mancanza di WITH CHECK compatibile — questo file lo rende un contratto).
--
-- Convenzione della batteria: PASS = NOTICE, FAIL = EXCEPTION; ruoli applicativi (SET ROLE),
-- mai superuser. `run.sh` avvolge in BEGIN/ROLLBACK: nessun residuo.
\set ON_ERROR_STOP on
\pset pager off

-- Fixture: un evento per San Bao e uno per Bozzano (il titolo è il marcatore; in transazione non
-- resta nulla comunque). Inseriti nel ruolo della CASA PROPRIA, come fa lo shim (`crea_evento`).
SET LOCAL ROLE casa_sanbao;
INSERT INTO trasi.evento (casa_id, titolo, inizio, luogo_testo)
SELECT c.id, 'TEST-CROSS: evento san-bao', now() + interval '3 days', 'San Bao'
  FROM trasi.casa c WHERE c.slug = 'san-bao';
RESET ROLE;

SET LOCAL ROLE casa_bozzano;
INSERT INTO trasi.evento (casa_id, titolo, inizio, luogo_testo)
SELECT c.id, 'TEST-CROSS: evento bozzano', now() + interval '3 days', 'Bozzano'
  FROM trasi.casa c WHERE c.slug = 'bozzano';
RESET ROLE;

-- C01 · LETTURA cross-Casa: bozzano legge gli eventi di San Bao (il palinsesto è di rete) ------
DO $$
DECLARE n integer;
BEGIN
  EXECUTE 'SET LOCAL ROLE casa_bozzano';
  SELECT count(*) INTO n
    FROM trasi.evento e JOIN trasi.casa c ON c.id = e.casa_id
   WHERE c.slug = 'san-bao' AND e.titolo LIKE 'TEST-CROSS%';
  EXECUTE 'RESET ROLE';
  IF n < 1 THEN RAISE EXCEPTION 'FAIL C01 — bozzano non legge gli eventi di san-bao: la lettura cross-Casa è rotta (n=%)', n; END IF;
  RAISE NOTICE 'PASS C01 — bozzano legge gli eventi di san-bao (lettura cross-Casa libera)';
END $$;

-- C02 · SCRITTURA cross-Casa: bozzano NON inserisce un evento per San Bao ----------------------
DO $$
DECLARE bloccato boolean := false;
BEGIN
  EXECUTE 'SET LOCAL ROLE casa_bozzano';
  BEGIN
    INSERT INTO trasi.evento (casa_id, titolo, inizio)
    VALUES ((SELECT id FROM trasi.casa WHERE slug='san-bao'), 'TEST-CROSS: violazione', now() + interval '3 days');
    bloccato := false;
  EXCEPTION WHEN insufficient_privilege THEN bloccato := true;
  END;
  EXECUTE 'RESET ROLE';
  IF NOT bloccato THEN RAISE EXCEPTION 'FAIL C02 — bozzano ha INSERITO un evento per san-bao (la RLS non blocca le scritture altrui)'; END IF;
  RAISE NOTICE 'PASS C02 — la RLS blocca l''INSERT cross-Casa (violazione policy per table "evento")';
END $$;

-- C03 · UPDATE cross-Casa: bozzano non tocca l'evento di San Bao -------------------------------
DO $$
DECLARE modificati integer;
BEGIN
  EXECUTE 'SET LOCAL ROLE casa_bozzano';
  UPDATE trasi.evento SET titolo = 'TEST-CROSS: manomesso'
   WHERE titolo = 'TEST-CROSS: evento san-bao';
  GET DIAGNOSTICS modificati = ROW_COUNT;
  EXECUTE 'RESET ROLE';
  IF modificati <> 0 THEN RAISE EXCEPTION 'FAIL C03 — bozzano ha MODIFICATO un evento di san-bao (% righe)', modificati; END IF;
  RAISE NOTICE 'PASS C03 — UPDATE cross-Casa: 0 righe (RLS `evento_upd_casa` filtra su casa_corrente)';
END $$;

-- C04 · DELETE cross-Casa: il privilegio stesso non esiste per i ruoli Casa ---------------------
-- Sui ruoli Casa il GRANT su `evento` è `arw` (niente D): la DELETE fallisce per privilegio,
-- prima ancora che la RLS la filtri (stesso criterio di t_report R03). Aspettarsi 0 righe
-- mascherebbe un allargamento di privilegio; questo test lo rende un errore.
DO $$
DECLARE bloccato boolean := false;
BEGIN
  EXECUTE 'SET LOCAL ROLE casa_bozzano';
  BEGIN
    DELETE FROM trasi.evento WHERE titolo = 'TEST-CROSS: evento san-bao';
    bloccato := false;
  EXCEPTION WHEN insufficient_privilege THEN bloccato := true;
  END;
  EXECUTE 'RESET ROLE';
  IF NOT bloccato THEN
    RAISE EXCEPTION 'FAIL C04 — bozzano ha potuto eseguire DELETE su trasi.evento: un GRANT DELETE ai ruoli Casa allargherebbe V4';
  END IF;
  RAISE NOTICE 'PASS C04 — DELETE cross-Casa: 42501, il privilegio DELETE non esiste per i ruoli Casa';
END $$;

-- C05 · RICHIESTA: bozzano NON registra richieste a nome di San Bao ----------------------------
DO $$
DECLARE inserite integer := 0;
BEGIN
  EXECUTE 'SET LOCAL ROLE casa_bozzano';
  BEGIN
    INSERT INTO trasi.richiesta (casa_id, ts, categoria, esito)
    VALUES ((SELECT id FROM trasi.casa WHERE slug='san-bao'), now(), 'orientamento', 'risolta');
    inserite := 1;
  EXCEPTION WHEN insufficient_privilege THEN inserite := 0;
  END;
  EXECUTE 'RESET ROLE';
  IF inserite <> 0 THEN RAISE EXCEPTION 'FAIL C05 — bozzano ha registrato una RICHIESTA a nome di san-bao'; END IF;
  RAISE NOTICE 'PASS C05 — INSERT richiesta cross-Casa bloccato (RLS `rich_ins_casa` con casa_corrente)';
END $$;

-- C06 · i dati di lettura restano leggibili dopo i tentativi di scrittura bloccati --------------
DO $$
DECLARE n integer;
BEGIN
  EXECUTE 'SET LOCAL ROLE casa_bozzano';
  SELECT count(*) INTO n FROM trasi.evento WHERE titolo LIKE 'TEST-CROSS%';
  EXECUTE 'RESET ROLE';
  IF n < 1 THEN RAISE EXCEPTION 'FAIL C06 — i dati di lettura cross-Casa non sono leggibili (n=%)', n; END IF;
  RAISE NOTICE 'PASS C06 — il fixture di lettura resta leggibile dopo i tentativi di scrittura bloccati';
END $$;