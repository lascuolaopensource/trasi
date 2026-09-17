-- Trasi — db/020_flusso.sql  (blocco B4, worker trasi-flussi)
--
-- Registro delle esecuzioni dei flussi notturni + le viste di supporto agli alert.
-- Idempotente: rieseguibile senza errori.
--
-- Perché un file separato da db/000–012: quei file sono di B1 e il loro ordinamento è congelato;
-- `flusso_run` nasce con B4 (`plan.md` §4 B4-FLW-02) e deve poter essere applicato senza toccarli.
-- L'ordine di apply.sh lo esegue dopo 012 (prefisso 020 > 012) — vedi `flussi/apply_flussi.sh`, che
-- lo applica da solo quando si vuole il solo delta B4.
--
-- Cosa NON c'è qui: nessuna scrittura sul dominio. `flusso_run` è un registro (append-only come
-- `audit` e `fonte_run`), le viste sono di sola lettura. Le uniche scritture di dominio di B4 le fa
-- `trasi.applica_proposte_approvate` (proposta → approvazione → audit) e l'upsert iCal su `evento`
-- (§8 F4). V4 resta invariato.
--
-- Un'unica eccezione a un GRANT di B1, dichiarata: `automazioni` riceve INSERT su `fonte_run`.
-- Senza, nessun flusso potrebbe lasciare traccia dell'esito di una fonte (la tabella era scrivibile
-- solo da `ti`/owner) e il criterio F4 `fonte_run.esito='anomalo'` sarebbe irraggiungibile.
-- INSERT soltanto: `fonte_run` resta append-only (nessun UPDATE/DELETE a nessun ruolo applicativo).
--
-- [ASSUNZIONE] I parametri nuovi letti dai flussi (`gg_attesa_alert`, `giorni_fonte_silente`,
-- `soglia_delta_anomalo_pct`, `soglia_riscrittura_pct`) NON vengono seminati qui: la batteria B1
-- (`db/tests/t_viste.sql` V01) fissa `count(parametro) = 10` e `db/003` è di un altro worker.
-- Le viste e gli script li leggono con `COALESCE(trasi.p_int('…'), <default>)`: la riga si può
-- aggiungere in qualsiasi momento come configurazione (solo `ti` scrive `parametro`) e il flusso
-- la rispetta, senza che il valore di default sia duplicato nel codice SQL di ogni consumatore.
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
    FROM unnest(ARRAY['trasi.fonte_run','trasi.proposta','trasi.audit','trasi.casa',
                      'trasi.identita_onyx','trasi.fonte','trasi.luogo',
                      'trasi.p_int(text)']) x
   WHERE to_regclass(x) IS NULL AND to_regprocedure(x) IS NULL;
  IF v_missing IS NOT NULL THEN
    RAISE EXCEPTION 'B4-flussi/020: mancano % — applica prima db/000–012', v_missing;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'automazioni') THEN
    RAISE EXCEPTION 'B4-flussi/020: ruolo automazioni assente — applica prima db/000_roles.sql';
  END IF;
END
$pre$;

-- ---------------------------------------------------------------------------
-- 1. `flusso_run` — una riga per esecuzione (plan.md §4 B4-FLW-02)
--    Colonne della spec: id, nome, trigger, inizio_ts, fine_ts, esito, n_righe, dettaglio
--    più `eseguito_da` (session_user), come `fonte_run`: senza, non si distingue un run
--    notturno da uno manuale di diagnosi.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trasi.flusso_run (
  id          bigserial PRIMARY KEY,
  nome        text NOT NULL,
  trigger     text NOT NULL CHECK (trigger IN ('cron','manuale')),
  inizio_ts   timestamptz NOT NULL DEFAULT now(),
  fine_ts     timestamptz,
  esito       text NOT NULL CHECK (esito IN ('ok','parziale','errore')),
  n_righe     integer,
  dettaglio   jsonb,
  eseguito_da text
);
COMMENT ON TABLE  trasi.flusso_run IS
  'Una riga per esecuzione di un flusso notturno (F3/F4/F6/F9). Append-only: è il registro con cui si prova che la notte è passata e con che esito.';
COMMENT ON COLUMN trasi.flusso_run.nome IS
  'Nome del flusso: applica | export_kb | fonti_ical | fonti_http | alert.';
COMMENT ON COLUMN trasi.flusso_run.trigger IS
  'cron = eseguito dallo scheduler; manuale = eseguito da una persona (make notte, ./applica.sh).';
COMMENT ON COLUMN trasi.flusso_run.esito IS
  'ok = tutto applicato · parziale = almeno una proposta in errore (le altre sì) · errore = il flusso non ha concluso.';
COMMENT ON COLUMN trasi.flusso_run.n_righe IS
  'Righe cambiate dal flusso (per `applica`: proposte applicate + proposte scadute).';
COMMENT ON COLUMN trasi.flusso_run.dettaglio IS
  'Contesto dell''esito: conteggi, elenco degli `errore:` e, per `applica`, quante righe di `audit` ha scritto.';
COMMENT ON COLUMN trasi.flusso_run.eseguito_da IS
  'session_user: il ruolo di connessione che ha eseguito il flusso (atteso `automazioni`).';

-- Il consumatore è «cos'è passato stanotte»: ultimo run per nome, e storico per nome.
CREATE INDEX IF NOT EXISTS flusso_run_nome_ts_idx ON trasi.flusso_run (nome, inizio_ts DESC);

-- RLS con FORCE, come le altre tabelle di registro: la RLS è l'autorità anche per il proprietario.
ALTER TABLE trasi.flusso_run ENABLE ROW LEVEL SECURITY;
ALTER TABLE trasi.flusso_run FORCE  ROW LEVEL SECURITY;

DROP POLICY IF EXISTS owner_all           ON trasi.flusso_run;
DROP POLICY IF EXISTS flusso_run_ins_flusso ON trasi.flusso_run;
DROP POLICY IF EXISTS flusso_run_sel      ON trasi.flusso_run;

CREATE POLICY owner_all ON trasi.flusso_run
  FOR ALL TO trasi_owner USING (true) WITH CHECK (true);

-- `automazioni` scrive il proprio run e rilegge la storia. Nessuna policy di scrittura
-- oltre a INSERT: un flusso non riscrive il registro di un altro (§ append-only).
CREATE POLICY flusso_run_ins_flusso ON trasi.flusso_run
  FOR INSERT TO automazioni WITH CHECK (true);

CREATE POLICY flusso_run_sel ON trasi.flusso_run
  FOR SELECT TO
    automazioni, ti, rete,
    casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
    casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano
  USING (true);

REVOKE ALL ON trasi.flusso_run FROM PUBLIC;

-- GRANT: `automazioni` INSERT/SELECT (esegue e registra); `ti`, `rete` e le Case SELECT.
-- Alle Case e a `rete` si concede la lettura: «cos'è passato stanotte» riguarda anche loro
-- (la coda di approvazione si popola di notte).
-- **`REVOKE` prima del `GRANT`, e non è ridondanza.** `GRANT` aggiunge un privilegio ma non toglie
-- quelli già presenti: senza il `REVOKE`, rieseguire questo file su un database in cui un ruolo avesse
-- ricevuto la concessione sbagliata la lascerebbe in piedi — il file «converge» solo sui database
-- nuovi. La verifica in fondo lo controlla, e al primo tentativo ha fallito proprio così: dopo aver
-- tolto `metabase_ro` dai `GRANT`, i privilegi della versione precedente erano ancora attivi.
-- `db/apply.sh` è dichiarato idempotente e convergente: questa è la condizione perché lo sia davvero.
REVOKE ALL ON trasi.flusso_run FROM PUBLIC, metabase_ro;
-- Le viste sono create più avanti in questo file (163, 254, 324): su un database NUOVO il
-- REVOKE qui sopra le incontrerebbe inesistenti e abortirebbe il file (misurato su fresco
-- install: «relation trasi.v_flusso_alert_proposte does not exist»). La revoca va condizionata
-- all'esistenza: l'effetto è identico sui database che già le hanno, e su quelli nuovi la
-- `CREATE OR REPLACE VIEW` di sotto le crea senza privilegi extra da revocare.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'trasi' AND c.relname IN ('v_flusso_alert_proposte',
                     'v_flusso_destinatari', 'v_flusso_coerenza_fonti')) THEN
    REVOKE ALL ON trasi.v_flusso_alert_proposte, trasi.v_flusso_destinatari,
                  trasi.v_flusso_coerenza_fonti FROM PUBLIC, metabase_ro;
  END IF;
END $$;

GRANT INSERT, SELECT ON trasi.flusso_run TO automazioni;
-- `metabase_ro` **fuori** di proposito: `dettaglio` porta i recapiti degli alert (indirizzi di
-- servizio, e domani `casa.email_digest`) e i messaggi d'errore interni. Non serve a nessun dashboard,
-- e §12 dice «nessun dato personale» — un indirizzo che oggi è `@trasi.local` domani può essere reale.
-- Lettura per gli operatori e per il monitoraggio notturno, non per l'analitica.
GRANT SELECT ON trasi.flusso_run TO ti, rete,
  casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
  casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano;
-- La PK è `bigserial`: senza USAGE sulla sequenza l'INSERT fallirebbe con «permission denied
-- for sequence», cioè il registro resterebbe vuoto proprio mentre i flussi girano.
GRANT USAGE, SELECT ON SEQUENCE trasi.flusso_run_id_seq TO automazioni;

-- ---------------------------------------------------------------------------
-- 2. `fonte_run` — eccezione dichiarata: INSERT ad `automazioni`
--    (unica modifica a un GRANT di B1; nessun UPDATE/DELETE, resta append-only)
-- ---------------------------------------------------------------------------
DROP POLICY IF EXISTS fonte_run_ins_flusso ON trasi.fonte_run;
CREATE POLICY fonte_run_ins_flusso ON trasi.fonte_run
  FOR INSERT TO automazioni WITH CHECK (true);

GRANT INSERT ON trasi.fonte_run TO automazioni;
GRANT USAGE, SELECT ON SEQUENCE trasi.fonte_run_id_seq TO automazioni;

-- ---------------------------------------------------------------------------
-- 3. Vista di supporto F6 · proposte in attesa e appena scadute, con il destinatario
--    risolto (§8 F6: «proposte in attesa oltre 7 gg» → gestore della Casa se
--    `approvatore_ruolo='gestore'`, altrimenti AT).
--
--    Perché una vista e non una query in `alert.py`: il destinatario è una regola di
--    governance (§11) e va scritta una volta sola; `automazioni` non ha SELECT su
--    `identita_onyx` (giusto: sono indirizzi di servizio, non suoi) e la vista, di
--    proprietà `trasi_owner`, risolve la mappa senza allargare i suoi privilegi.
--
--    Nessun campo personale: escono id di proposta, entità, motivazione e un indirizzo
--    di servizio (`@trasi.local` o `casa.email_digest`), mai chi ha proposto (§12).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW trasi.v_flusso_alert_proposte AS
WITH at AS (
  SELECT i.email FROM trasi.identita_onyx i
   WHERE i.ruolo_db = 'rete' AND i.attiva ORDER BY i.id LIMIT 1
),
gestore AS (
  -- Stessa catena di `v_flusso_destinatari`: `email_digest` della Casa, poi l'identità `gestore.*`
  -- (convenzione del seed), poi l'AT. Una sola regola di recapito, scritta una volta.
  SELECT DISTINCT ON (i.casa_id) i.casa_id, i.email
    FROM trasi.identita_onyx i
   WHERE i.attiva AND i.casa_id IS NOT NULL AND i.ruolo_db LIKE 'casa\_%'
   ORDER BY i.casa_id, (i.email LIKE 'gestore.%') DESC, i.id
)
SELECT 'in_attesa'::text AS voce,
       p.id              AS proposta_id,
       p.origine, p.tipo, p.entita, p.entita_id,
       p.casa_id, c.slug AS casa_slug, c.nome AS casa_nome,
       p.approvatore_ruolo,
       p.motivazione,
       p.proposto_ts,
       p.scade_il,
       (current_date - p.proposto_ts::date) AS giorni,
       -- Il destinatario dipende da **chi decide**: se la proposta è del gestore va al gestore della
       -- Casa (via `email_digest` o identità), se è dell'AT va all'AT (§8 F6, §11).
       CASE WHEN p.approvatore_ruolo = 'gestore'
            THEN COALESCE(c.email_digest, g.email, (SELECT email FROM at))
            ELSE (SELECT email FROM at) END AS destinatario,
       CASE WHEN p.approvatore_ruolo = 'gestore' AND c.email_digest IS NOT NULL THEN 'gestore_email_digest'
            WHEN p.approvatore_ruolo = 'gestore' AND g.email IS NOT NULL   THEN 'gestore_identita'
            WHEN (SELECT email FROM at) IS NOT NULL THEN 'at' END AS destinatario_ruolo
  FROM trasi.proposta p
  LEFT JOIN trasi.casa c ON c.id = p.casa_id
  LEFT JOIN gestore g ON g.casa_id = p.casa_id
 WHERE p.stato = 'proposta'
UNION ALL
-- Le scadute delle ultime 24 h: la transizione `proposta → scaduta` è tracciata in `audit`,
-- quindi la finestra temporale si legge da lì (le proposte non hanno un `scaduto_ts`).
SELECT 'scaduta', p.id, p.origine, p.tipo, p.entita, p.entita_id,
       p.casa_id, c.slug, c.nome, p.approvatore_ruolo, p.motivazione,
       p.proposto_ts, p.scade_il,
       (current_date - p.scade_il) AS giorni,
       CASE WHEN p.approvatore_ruolo = 'gestore'
            THEN COALESCE(c.email_digest, g.email, (SELECT email FROM at))
            ELSE (SELECT email FROM at) END,
       CASE WHEN p.approvatore_ruolo = 'gestore' AND c.email_digest IS NOT NULL THEN 'gestore_email_digest'
            WHEN p.approvatore_ruolo = 'gestore' AND g.email IS NOT NULL   THEN 'gestore_identita'
            WHEN (SELECT email FROM at) IS NOT NULL THEN 'at' END
  FROM trasi.audit a
  JOIN trasi.proposta p ON p.id = a.proposta_id
  LEFT JOIN trasi.casa c ON c.id = p.casa_id
  LEFT JOIN gestore g ON g.casa_id = p.casa_id
 WHERE a.azione = 'transizione'
   AND a.dopo->>'stato' = 'scaduta'
   AND a.ts > now() - interval '24 hours';

COMMENT ON VIEW trasi.v_flusso_alert_proposte IS
  'F6: proposte aperte (voce=in_attesa) e scadute nelle ultime 24 h (voce=scaduta), con destinatario risolto secondo chi decide (gestore della Casa se la proposta è sua, altrimenti AT). Nessun dato personale.';

-- **Nessuna delle viste di questo file è concessa a `metabase_ro`, e la ragione è strutturale.**
-- Queste viste sono di proprietà `trasi_owner` e quindi girano con i SUOI privilegi
-- (`security_invoker` assente di default): una vista così concede a chi la legge i dati che le
-- servono, anche se la tabella sottostante gli è negata. `v_flusso_alert_proposte` porta
-- `motivazione` e `origine` di `proposta`; `v_flusso_destinatari` porta gli indirizzi di recapito.
-- Concederle a `metabase_ro` **aggirerebbe** la revoca di `SELECT` su `proposta`/`audit`
-- (`db/007_dash.sql`, criterio B5-DSH-01), cioè proprio la segregazione che §11/§12 chiede — ed è la
-- stessa trappola che `db/004_views.sql` documenta in testa. Le viste di B4 servono ai flussi e agli
-- operatori; l'analitica ha le proprie (B1, `v_proposte_aperte`, `v_oggi_casa`, …).
GRANT SELECT ON trasi.v_flusso_alert_proposte TO automazioni, ti, rete,
  casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
  casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano;

-- ---------------------------------------------------------------------------
-- 3b. Vista di supporto F6 · i destinatari degli avvisi
--     Il recapito dell'AT serve **anche quando non ci sono proposte** (per l'alert di coerenza
--     delle fonti): risolverlo da `v_flusso_alert_proposte` lo legherebbe a una coda non vuota, ed è
--     il difetto trovato eseguendo il flusso per la prima volta. `automazioni` non ha SELECT su
--     `identita_onyx` (sono indirizzi di servizio, e la regola è «il minimo privilegio»): la vista,
--     di proprietà `trasi_owner`, risolve la mappa senza allargare i suoi privilegi.
--
--     La catena di recapito è a tre gradini, dal più specifico al meno:
--       1. `casa.email_digest` — il campo che l'architettura §7.1 prevede per il recapito di una Casa
--          (oggi NULL nel seed: lo popola il TI/Metabase in B5-DSH-07a);
--       2. l'identità **gestore** della Casa — la convenzione del seed (`gestore.<slug>@trasi.local`,
--          `db/010_seed_case.sql`). Fra le identità dello stesso ruolo Casa si preferisce quella il
--          cui indirizzo inizia per `gestore.`: la scelta è deterministica e documentata, e un
--          `email_digest` valorizzato la scavalca senza modifiche;
--       3. l'AT (`rete`) — chi decide quando la proposta non è di una Casa.
--     Senza il gradino 2 un alert per il gestore di San Bao non avrebbe recapito (tutte le Case hanno
--     `email_digest` NULL) e il criterio B4-FLW-09 «1 email a San Bao, 0 a Bozzano» sarebbe
--     irraggiungibile con i dati reali.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW trasi.v_flusso_destinatari AS
WITH at AS (
  SELECT i.email FROM trasi.identita_onyx i
   WHERE i.ruolo_db = 'rete' AND i.attiva ORDER BY i.id LIMIT 1
),
gestore AS (
  -- Un solo indirizzo per Casa: quello del gestore, con `email_digest` come prima scelta.
  SELECT DISTINCT ON (i.casa_id) i.casa_id, i.email
    FROM trasi.identita_onyx i
   WHERE i.attiva AND i.casa_id IS NOT NULL AND i.ruolo_db LIKE 'casa\_%'
   ORDER BY i.casa_id, (i.email LIKE 'gestore.%') DESC, i.id
)
SELECT rc.ruolo, rc.casa_id, c.slug AS casa_slug, c.nome AS casa_nome,
       COALESCE(c.email_digest, g.email, (SELECT email FROM at)) AS destinatario,
       CASE WHEN c.email_digest IS NOT NULL THEN 'gestore_email_digest'
            WHEN g.email IS NOT NULL   THEN 'gestore_identita'
            WHEN (SELECT email FROM at) IS NOT NULL THEN 'at' END AS destinatario_ruolo,
       (SELECT email FROM at) AS at_email
  FROM trasi.ruolo_casa rc
  LEFT JOIN trasi.casa c ON c.id = rc.casa_id
  LEFT JOIN gestore g ON g.casa_id = rc.casa_id;

COMMENT ON VIEW trasi.v_flusso_destinatari IS
  'F6: destinatario degli avvisi per ruolo/Casa — email_digest della Casa, altrimenti l''identità gestore della Casa, altrimenti l''AT. Nessun dato personale: solo indirizzi di servizio.';

GRANT SELECT ON trasi.v_flusso_destinatari TO automazioni, ti, rete,
  casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
  casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano;

-- ---------------------------------------------------------------------------
-- 3c. Vista **ridotta** dei recapiti, per l'analitica (B5-DSH-07a).
--
-- Perché esiste, se c'è già `v_flusso_destinatari`. Quella vista è completa: porta `at_email`,
-- `casa_nome`, il ruolo e la catena di risoluzione. `metabase_ro` **non** può leggerla, e la ragione è
-- strutturale, non di comodo: le viste di questo file girano con i privilegi del proprietario
-- (`trasi_owner`), e `v_flusso_destinatari` legge `identita_onyx` — che §11/§12 negano a
-- `metabase_ro` insieme a `richiesta`/`proposta`/`audit` (`db/007_dash.sql`, criterio B5-DSH-01).
-- Concederla in blocco aggirerebbe quella segregazione.
--
-- Il problema pratico è però reale: `plan.md` B5-DSH-07a chiede a Metabase 40 notification «10 Case ×
-- 4 tipi», ognuna con almeno un destinatario. Senza una vista, il destinatario si risolverebbe
-- replicando `gestore.<slug>@trasi.local` nella configurazione di Metabase — cioè duplicando una
-- regola di governance (§11), che è esattamente ciò che questo file evita scrivendola una volta sola.
--
-- La risposta è **proiettare il minimo**: slug della Casa, destinatario risolto, ruolo. Nessun
-- `at_email`, nessun `casa_nome`, nessuna riga di `identita_onyx`. È la stessa regola di recapito,
-- esposta per quanto serve a spedire un avviso e non un carattere di più.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW trasi.v_flusso_recapiti AS
SELECT casa_slug, destinatario, destinatario_ruolo
  FROM trasi.v_flusso_destinatari
 WHERE casa_slug IS NOT NULL;

COMMENT ON VIEW trasi.v_flusso_recapiti IS
  'F6: recapiti per Casa, proiezione ridotta di v_flusso_destinatari (casa_slug, destinatario, destinatario_ruolo) per B5-DSH-07a. Nessun altro campo.';

-- Questa sì a `metabase_ro`: tre colonne, nessuna identità, nessun testo di proposta.
GRANT SELECT ON trasi.v_flusso_recapiti TO metabase_ro, ti, rete, automazioni,
  casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
  casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano;

-- ---------------------------------------------------------------------------
-- 4. Vista di supporto F6 · coerenza delle fonti (§8 F4, quattro esiti)
--      * fonte_silente        — fonte attiva che non risponde da N giorni (default 3)
--      * fonte_errore         — ultimo run in errore
--      * fonte_anomala        — ultimo run con delta anomalo (il flusso NON ha applicato)
--      * validazione_scaduta  — dato provvisorio di fonte esterna non confermato
--                               entro `gg_validazione_comune` (§11: «il dato diventa
--                               provvisorio dopo [P] 7 gg»)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW trasi.v_flusso_coerenza_fonti AS
WITH ultimo AS (
  SELECT f.id AS fonte_id, f.nome AS fonte_nome, f.tipo_accesso, f.attiva,
         r.ts, r.esito, r.righe, r.dettaglio,
         row_number() OVER (PARTITION BY f.id ORDER BY r.ts DESC, r.id DESC) AS rn
    FROM trasi.fonte f
    LEFT JOIN trasi.fonte_run r ON r.fonte_id = f.id
   WHERE f.attiva
)
SELECT 'fonte_silente'::text AS voce,
       u.fonte_id, u.fonte_nome, NULL::text AS riferimento, NULL::text AS dettaglio,
       u.ts AS ultimo_run_ts,
       COALESCE(EXTRACT(day FROM now() - u.ts)::int, 9999) AS giorni
  FROM ultimo u
 WHERE u.rn = 1
   AND (u.ts IS NULL
        OR u.ts < now() - make_interval(days => COALESCE(trasi.p_int('giorni_fonte_silente'), 3)))
UNION ALL
SELECT 'fonte_errore', u.fonte_id, u.fonte_nome, NULL, u.dettaglio::text, u.ts, 0
  FROM ultimo u
 WHERE u.rn = 1 AND u.esito = 'errore'
UNION ALL
SELECT 'fonte_anomala', u.fonte_id, u.fonte_nome, NULL, u.dettaglio::text, u.ts, 0
  FROM ultimo u
 WHERE u.rn = 1 AND u.esito = 'anomalo'
UNION ALL
SELECT 'validazione_scaduta', l.fonte_id, f.nome,
       'luogo:' || l.id, l.nome || ' — dato provvisorio (affidabilità ' || l.affidabilita || ')',
       (l.data_aggiornamento + COALESCE(trasi.p_int('gg_validazione_comune'), 7))::timestamptz,
       current_date - l.data_aggiornamento
  FROM trasi.luogo l
  JOIN trasi.fonte f ON f.id = l.fonte_id
 WHERE l.chiuso_il IS NULL
   AND f.tipo_accesso = 'web'
   AND l.affidabilita < 3
   AND l.data_aggiornamento IS NOT NULL
   AND l.data_aggiornamento < current_date - COALESCE(trasi.p_int('gg_validazione_comune'), 7);

COMMENT ON VIEW trasi.v_flusso_coerenza_fonti IS
  'F6/F4: coerenza delle fonti — silente, errore, delta anomalo (ultimo run), validazione scaduta dei dati provvisori. Alimenta l''alert all''AT.';

GRANT SELECT ON trasi.v_flusso_coerenza_fonti TO automazioni, ti, rete,
  casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
  casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano;

-- ---------------------------------------------------------------------------
-- 5. Verifica di installazione (visibile in output: la RLS è l'autorità)
-- ---------------------------------------------------------------------------
DO $verify$
DECLARE
  v_n int;
  v_cattivi text;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                  WHERE n.nspname = 'trasi' AND c.relname = 'flusso_run'
                    AND c.relrowsecurity AND c.relforcerowsecurity) THEN
    RAISE EXCEPTION 'B4-flussi/020: flusso_run senza ENABLE+FORCE ROW LEVEL SECURITY';
  END IF;

  SELECT string_agg(DISTINCT p.priv || ' su ' || p.obj, ', ') INTO v_cattivi FROM (VALUES
    ('INSERT', 'flusso_run'), ('SELECT', 'flusso_run')) AS p(priv, obj)
   WHERE NOT has_table_privilege('automazioni', 'trasi.' || p.obj, p.priv);
  IF v_cattivi IS NOT NULL THEN
    RAISE EXCEPTION 'B4-flussi/020: automazioni senza i GRANT attesi: %', v_cattivi;
  END IF;

  IF NOT has_table_privilege('automazioni', 'trasi.flusso_run', 'INSERT')
     OR NOT has_table_privilege('ti', 'trasi.flusso_run', 'SELECT') THEN
    RAISE EXCEPTION 'B4-flussi/020: GRANT di flusso_run non allineati alla spec';
  END IF;

  -- §11/§12: `metabase_ro` non legge `flusso_run` né le viste di B4. Queste ultime girano con i
  -- privilegi del proprietario, quindi concederle aggirerebbe la revoca di `SELECT` su
  -- `proposta`/`audit` (`db/007_dash.sql`, criterio B5-DSH-01). Il controllo è qui perché una
  -- concessione aggiunta «per far vedere i flusso_run in un dashboard» non deve passare in silenzio.
  IF has_table_privilege('metabase_ro', 'trasi.flusso_run', 'SELECT')
     OR has_table_privilege('metabase_ro', 'trasi.v_flusso_alert_proposte', 'SELECT')
     OR has_table_privilege('metabase_ro', 'trasi.v_flusso_destinatari', 'SELECT')
     OR has_table_privilege('metabase_ro', 'trasi.v_flusso_coerenza_fonti', 'SELECT') THEN
    RAISE EXCEPTION 'B4-flussi/020: metabase_ro legge flusso_run o una vista non ridotta (§12/B5-DSH-01)';
  END IF;

  -- La sola cosa che `metabase_ro` può leggere da B4: i recapiti ridotti (B5-DSH-07a).
  IF NOT has_table_privilege('metabase_ro', 'trasi.v_flusso_recapiti', 'SELECT') THEN
    RAISE EXCEPTION 'B4-flussi/020: metabase_ro senza v_flusso_recapiti (B5-DSH-07a lo richiede)';
  END IF;

  -- Il registro è append-only: nessun ruolo applicativo può riscrivere la storia.
  IF has_table_privilege('automazioni', 'trasi.flusso_run', 'UPDATE')
     OR has_table_privilege('automazioni', 'trasi.flusso_run', 'DELETE')
     OR has_table_privilege('automazioni', 'trasi.fonte_run', 'UPDATE')
     OR has_table_privilege('automazioni', 'trasi.fonte_run', 'DELETE') THEN
    RAISE EXCEPTION 'B4-flussi/020: un registro non è append-only (UPDATE/DELETE concesso ad automazioni)';
  END IF;

  -- V4: questo file non deve aver aperto nessuna via di scrittura sul dominio.
  SELECT string_agg(t || ':' || p, ', ') INTO v_cattivi
    FROM unnest(ARRAY['trasi.luogo','trasi.scheda_servizio','trasi.evento',
                      'trasi.opportunita','trasi.casa']) t
    CROSS JOIN unnest(ARRAY['INSERT','UPDATE','DELETE']) p
   WHERE has_table_privilege('automazioni', t, p)
     AND NOT (t = 'trasi.evento' AND p IN ('INSERT','UPDATE'));   -- sola eccezione: upsert iCal (§8 F4)
  IF v_cattivi IS NOT NULL THEN
    RAISE EXCEPTION 'B4-flussi/020: automazioni ha ricevuto scritture di dominio non ammesse: %', v_cattivi;
  END IF;

  RAISE NOTICE 'B4-flussi/020 applicato: flusso_run (append-only, FORCE RLS, automazioni INSERT/SELECT, ti/rete/Case SELECT, metabase_ro escluso) · fonte_run INSERT ad automazioni · 3 viste di supporto (non concesse a metabase_ro)';
END
$verify$;

RESET ROLE;
