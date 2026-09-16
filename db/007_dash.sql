-- Trasi — db/007_dash.sql  (blocco B5, worker trasi-dash)
--
-- Ciò che serve al solo Metabase, e nient'altro:
--   1. togliere a `metabase_ro` la lettura in chiaro di `proposta`, `audit` e `fonte_run`
--      (la matrice §11/§12 dice che non deve averla, e il criterio B5-DSH-01 lo verifica);
--   2. registrare l'esposizione delle viste di reporting.
--
-- Perché un file separato da db/000–020: quei file appartengono a B1 e B4 e il loro ordinamento è
-- congelato; questo è il delta di B5. `db/apply.sh` lo prevede già nella propria ORDER (007_dash.sql)
-- e lo salta con NOTICE finché non esiste — da qui in poi esiste.
--
-- Idempotente: rieseguibile senza errori, come gli altri file di apply.sh.
--
-- ---------------------------------------------------------------------------
-- Perché i REVOKE (misurato, non dedotto)
-- ---------------------------------------------------------------------------
-- `metabase_ro` è il ruolo con cui Metabase legge il dominio: è l'unico ruolo, oltre agli
-- applicativi, che parla con uno strumento di BI. La matrice §11 gli nega `richiesta`, `proposta`,
-- `audit` e `identita_onyx`: le viste di reporting esistono apposta per dare gli **aggregati** senza
-- dare le **righe** (è il commento in testa a db/004_views.sql).
--
-- Alla verifica di B5 il divieto valeva solo a metà (misura: `SET ROLE metabase_ro` →
-- `SELECT count(*) FROM trasi.proposta` = 40 righe, `FROM trasi.audit` = 50 righe, con `payload`,
-- `diff`, `motivazione`, `prima`, `dopo`). La causa non è una policy ma due GRANT di db/005
-- (`GRANT SELECT ON trasi.proposta … metabase_ro …`, `GRANT SELECT ON trasi.audit … metabase_ro …`),
-- che elencano `metabase_ro` insieme ai ruoli che quel dato devono averlo.
--
-- Non si tocca db/005 (è di un altro blocco e il suo contenuto è congelato): il REVOKE vive qui,
-- gira dopo, e ottiene lo stesso effetto. `richiesta` e `identita_onyx` non compaiono perché erano
-- già negate — il REVOKE è idempotente per natura e questo file resta leggibile come «ciò che B5
-- toglie», senza ri-verificare l'intera matrice.
--
-- Cosa NON si toglie, deliberatamente:
--   * `casa`, `luogo`, `fonte`, `evento`, `scheda_servizio`, `opportunita`, `parametro` restano
--     leggibili: sono dati pubblici della rete (o configurazione non personale) e le mappe, le
--     tabelle di dettaglio e i filtri delle dashboard ne hanno bisogno per il drill-down;
--   * le `v_*` restano leggibili: sono il canale con cui i numeri aggregati arrivano a Metabase.
--
-- Il REVOKE su `fonte_run` è meno ovvio e va spiegato: `fonte_run` è il registro delle letture di
-- fonte (esito, `dettaglio` con il contesto del delta). Serve ad `automazioni` e all'AT, non a un
-- cruscotto di sola lettura: il consumo di BI su quel registro passa da `v_flusso_coerenza_fonti`,
-- che è già aggregata. Metabase non ha nessuna card su `fonte_run`.
\set ON_ERROR_STOP on
\set VERBOSITY terse

SET ROLE trasi_owner;
SET search_path = trasi, public, pg_temp;

-- ---------------------------------------------------------------------------
-- 0. Precondizioni: da quale contratto dipende questo file
-- ---------------------------------------------------------------------------
DO $pre$
DECLARE v_missing text;
BEGIN
  SELECT string_agg(x, ', ') INTO v_missing
    FROM unnest(ARRAY['trasi.casa','trasi.proposta','trasi.audit','trasi.fonte_run',
                      'trasi.v_mappa_case','trasi.v_confronto_case','trasi.v_proposte_aperte']) x
   WHERE to_regclass(x) IS NULL;
  IF v_missing IS NOT NULL THEN
    RAISE EXCEPTION 'B5-dash/007: mancano % — applica prima db/000–020', v_missing;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'metabase_ro') THEN
    RAISE EXCEPTION 'B5-dash/007: ruolo metabase_ro assente — applica prima db/000_roles.sql';
  END IF;
END
$pre$;

-- ---------------------------------------------------------------------------
-- 1. Least-privilege di `metabase_ro`: fuori i dati di sportello e i registri
-- ---------------------------------------------------------------------------
-- `proposta` porta `payload` e `diff` (il contenuto che si sta proponendo di cambiare) e
-- `motivazione`; `audit` porta `prima`/`dopo` di ogni mutazione e `eseguito_da`. Sono dati di
-- processo, non aggregati: un cruscotto li legge dalle viste (`v_proposte_aperte`,
-- `v_da_approvare`, `v_flusso_alert_proposte`), che espongono ciò che serve e minimizzano il resto.
REVOKE SELECT ON trasi.proposta FROM metabase_ro;
REVOKE SELECT ON trasi.audit    FROM metabase_ro;
REVOKE SELECT ON trasi.fonte_run FROM metabase_ro;

-- Difesa a strati: se un domani un GRANT arrivasse da `PUBLIC`, il REVOKE per ruolo non basterebbe.
-- (Non c'è oggi — `REVOKE ALL ON trasi.audit FROM PUBLIC` è già in db/005 — ma il costo è nullo.)
REVOKE ALL ON trasi.proposta, trasi.audit, trasi.fonte_run FROM PUBLIC;

-- ---------------------------------------------------------------------------
-- 2. Verifica di installazione
--    Un REVOKE che non ha tolto niente (perché il GRANT era altrove) è indistinguibile da un
--    REVOKE riuscito: qui si controlla l'**effetto**, non l'intenzione.
-- ---------------------------------------------------------------------------
DO $verify$
DECLARE v_letti text;
BEGIN
  SELECT string_agg(c.relname, ', ' ORDER BY c.relname) INTO v_letti
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE n.nspname = 'trasi' AND c.relkind IN ('r','v','m','p')
     AND c.relname IN ('richiesta','proposta','audit','identita_onyx','fonte_run')
     AND has_table_privilege('metabase_ro', c.oid, 'SELECT');

  IF v_letti IS NOT NULL THEN
    RAISE EXCEPTION 'B5-dash/007: metabase_ro legge ancora in chiaro: %', v_letti;
  END IF;

  -- E il verso opposto: le viste di reporting devono restare leggibili, altrimenti le dashboard
  -- di B5 si romperebbero in silenzio (Metabase mostrerebbe «permission denied» a runtime).
  IF NOT has_table_privilege('metabase_ro', 'trasi.v_mappa_case', 'SELECT')
     OR NOT has_table_privilege('metabase_ro', 'trasi.v_confronto_case', 'SELECT')
     OR NOT has_table_privilege('metabase_ro', 'trasi.v_proposte_aperte', 'SELECT')
     OR NOT has_table_privilege('metabase_ro', 'trasi.v_oggi_casa', 'SELECT')
     OR NOT has_table_privilege('metabase_ro', 'trasi.v_destinazioni', 'SELECT') THEN
    RAISE EXCEPTION 'B5-dash/007: metabase_ro ha perso la lettura di una vista di reporting';
  END IF;

  RAISE NOTICE 'B5-dash/007 applicato: metabase_ro senza proposta/audit/fonte_run/richiesta/identita_onyx, con le v_* di reporting';
END
$verify$;

RESET ROLE;
