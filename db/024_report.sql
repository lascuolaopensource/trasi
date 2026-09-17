-- Trasi — db/024_report.sql
-- I REPORT MENSILI come oggetto di dominio: il report dell'operatore si **legge**, non si modifica;
-- su di esso si **commenta**. Più la chat interna diventa commentabile verso un report (foglio 4.3).
--
-- ------------------------------------------------------------------------------------------------
-- DA DOVE VIENE QUESTO FILE (una specifica, non un'invenzione)
-- ------------------------------------------------------------------------------------------------
-- Il gruppo Processi ha dettato la regola:
--
--   «per i report che il sistema genera mensilmente gli operatori delle case o enti possono solo
--    commentare i report, non correggerlo o modificarli»
--
-- e il foglio «4.3 Report Mensili» del documento di architettura dei campi (gruppo Processi,
-- 2026-09-17) ne dà i contenuti. Questo file traduce quella regola in vincoli del database.
--
-- **Perché serve una tabella e non basta il CSV.** Oggi il report è un allegato `.csv` scritto in
-- `flussi/evidenze/ciclo_mensile/` e spedito per email: un artefatto, non un oggetto. Un allegato
-- non ha identità (non si può dire «il report di settembre di San Bao» in modo stabile), quindi non
-- si può **commentare** — e senza un oggetto commentabile la regola di Processi non è realizzabile.
-- Il commento deve agganciarsi a qualcosa che resta.
--
-- **Perché il report non è modificabile, e come lo si garantisce.** Non con una convenzione né con un
-- controllo applicativo — quelli si aggirano con una query diretta. Con i GRANT: ai ruoli Casa e a
-- `rete`/`ti` si concede **SELECT** sul report e **nient'altro**. Un `UPDATE` non trova il privilegio
-- e fallisce con `42501 permission denied`, che è la stessa forma con cui V4 protegge il dominio
-- (db/005 revoca le scritture e la RLS è l'autorità). Una regola che vive nell'interfaccia è una
-- regola che il primo `psql` smentisce.
--
-- **Chi scrive il report**: `automazioni`, che genera il ciclo mensile. Non `applicatore`: il report
-- non è una modifica al dominio mediata da proposta, è un **output di flusso** — la stessa natura di
-- `flusso_run`/`fonte_run` (db/020), che infatti hanno INSERT ad `automazioni`. Metterlo nel flusso
-- proposte significherebbe chiedere a un umano di approvare il proprio rendiconto.
--
-- **V5 e k-anonimato.** Il report **per Casa** è il rendiconto della Casa a sé stessa: contiene
-- numeri **non mascherati** dei propri sportelli (è il foglio 4.3-B: «registrazione degli accessi …
-- presso lo sportello di front desk»). Il report **aggregato dell'osservatorio** (4.3-C) attraversa
-- le Case e quindi passa da `trasi.k_anon` come ogni conteggio di persone: le celle sotto soglia
-- restano `<5`/`—`. La distinzione è nel campo `ambito` ed è vincolata da un CHECK, perché è la
-- differenza fra un rendiconto e una violazione di §12.
--
-- Nessun campo per dati personali: i contenuti sono conteggi e categorie, e `commento.testo` è testo
-- libero **filtrato dal presidio anti-PII dello shim** come `motivazione` delle proposte (V5).
--
-- Idempotente: rieseguibile senza errori.
\set ON_ERROR_STOP on
\set VERBOSITY terse

SET ROLE trasi_owner;
SET search_path = trasi, public, pg_temp;

-- ---------------------------------------------------------------------------
-- 0. Precondizioni
-- ---------------------------------------------------------------------------
DO $pre$
DECLARE v_missing text;
BEGIN
  -- Solo ciò che questo file **presuppone**: le tabelle che crea non si autocontrollano.
  SELECT string_agg(x, ', ') INTO v_missing
    FROM unnest(ARRAY['trasi.casa','trasi.fonte','trasi.flusso_run']) x
   WHERE to_regclass(x) IS NULL;
  -- `k_anon` e `casa_corrente` sono funzioni: `to_regclass` le trova `NULL`, quindi si controllano a
  -- parte. Mescolare le due verifiche in un solo predicato darebbe un falso «manca tutto».
  IF to_regprocedure('trasi.k_anon(bigint)') IS NULL OR to_regprocedure('trasi.casa_corrente()') IS NULL THEN
    RAISE EXCEPTION '024_report: mancano k_anon()/casa_corrente() — applica prima db/000–020';
  END IF;
  IF v_missing IS NOT NULL THEN
    RAISE EXCEPTION '024_report: mancano % — applica prima db/000–020', v_missing;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'automazioni') THEN
    RAISE EXCEPTION '024_report: ruolo automazioni assente — applica prima db/000_roles.sql';
  END IF;
END
$pre$;

-- ---------------------------------------------------------------------------
-- 1. `report` — il report mensile come oggetto, con identità stabile
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trasi.report (
  id            bigserial PRIMARY KEY,
  -- Un report per (Casa, mese): la chiave naturale. Il mese è il primo giorno, come in `v_report_mensile`.
  casa_id       integer NOT NULL REFERENCES trasi.casa(id),
  mese          date    NOT NULL CHECK (mese = date_trunc('month', mese)::date),
  -- `casa` = rendiconto della Casa a sé stessa (numeri propri, non mascherati).
  -- `osservatorio` = aggregato di rete, che attraversa le Case e quindi **deve** passare da k_anon.
  ambito        text    NOT NULL CHECK (ambito IN ('casa','osservatorio')),
  -- I contenuti del foglio 4.3, in JSON: `{"richieste": n, "senza_risposta": n, "categorie": {...},
  -- "reindirizzamenti": {...}, "suggerimenti": "..."}`. JSON e non colonne fisse perché il foglio
  -- elenca le **voci** del report, e le voci cambiano con le domande del gruppo Processi; colonne
  -- fisse significherebbero una migrazione a ogni voce nuova.
  contenuti     jsonb   NOT NULL DEFAULT '{}'::jsonb,
  -- Il CSV del report, quando esiste: il testo che è stato spedito, conservato perché il report
  -- **è** quel documento. Nessun percorso su disco: un file in `flussi/evidenze/` si cancella con la
  -- rotazione, e il report di settembre deve restare leggibile a novembre.
  csv           text,
  generato_ts   timestamptz NOT NULL DEFAULT now(),
  generato_da   text    NOT NULL DEFAULT 'automazioni',
  -- La riga di `flusso_run` che l'ha prodotto: il report è ricostruibile dall'esecuzione che l'ha
  -- generato (stessa contabilità dei flussi, §8).
  flusso_run_id bigint,
  UNIQUE (casa_id, mese, ambito)
);

COMMENT ON TABLE trasi.report IS
  'Report mensile persistito (foglio 4.3). L''operatore lo LEGGE e lo COMMENTA; non lo modifica: i '
  'ruoli Casa/rete/ti hanno solo SELECT, garantito dai GRANT, non da una convenzione.';

-- ---------------------------------------------------------------------------
-- 2. `commento` — la sola scrittura ammessa su un report
-- ---------------------------------------------------------------------------
-- Un commento è testo **su** un oggetto di dominio, come `nota_decisione` lo è su una proposta: non
-- modifica il report, vi si aggiunge accanto. Per questo vive in una tabella propria e non in una
-- colonna di `report`: due persone possono commentare lo stesso report, e una colonna terrebbe solo
-- l'ultimo — perdendo esattamente ciò che la specifica chiede di conservare.
CREATE TABLE IF NOT EXISTS trasi.commento (
  id         bigserial PRIMARY KEY,
  -- L'oggetto commentato. `report` è il caso della specifica; `evento` è quello che il foglio 4.2
  -- descrive («commenti rispetto a eventi»). Il CHECK tiene il vocabolario chiuso: un commento su
  -- un'entità non prevista è un errore di chi chiama, non una riga in più.
  entita     text NOT NULL CHECK (entita IN ('report','evento')),
  entita_id  bigint NOT NULL,
  -- Chi commenta: la Casa dell'identità. NULL per `rete`/`ti`, che commentano come osservatorio.
  casa_id    integer REFERENCES trasi.casa(id),
  -- ≤ 2000 caratteri come `messaggio.testo` (db/015): stesso limite, stessa ragione — un commento
  -- operativo si legge in una schermata, e un testo senza limite è un canale, non un commento.
  testo      text NOT NULL CHECK (char_length(testo) BETWEEN 1 AND 2000),
  ts         timestamptz NOT NULL DEFAULT now(),
  -- Impronta di scrittura, come sul dominio (db/005 `scrittura_00_ts`): la stessa contabilità di
  -- `v_scritture_senza_audit`, così un commento non è una scrittura invisibile.
  aggiornato_da text
);

CREATE INDEX IF NOT EXISTS commento_entita_idx ON trasi.commento (entita, entita_id, ts);

COMMENT ON TABLE trasi.commento IS
  'Commento su un report o un evento (foglio 4.2/4.3). È l''unica scrittura che un operatore può '
  'fare su un report: il report resta di sola lettura per costruzione (GRANT).';

-- ---------------------------------------------------------------------------
-- 3. Impronta di scrittura sui commenti
-- ---------------------------------------------------------------------------
-- Lo stesso trigger del dominio (`scrittura_00_ts`, db/005) applicato a `commento`: `aggiornato_da` è
-- il ruolo che ha scritto, e senza di esso `v_scritture_senza_audit` non potrebbe distinguere una
-- scrittura dichiarata da una sospetta.
CREATE OR REPLACE FUNCTION trasi.commento_00_ts() RETURNS trigger
LANGUAGE plpgsql AS $fn$
BEGIN
  NEW.aggiornato_da := current_user;
  RETURN NEW;
END;
$fn$;

DROP TRIGGER IF EXISTS commento_00_ts ON trasi.commento;
CREATE TRIGGER commento_00_ts BEFORE INSERT ON trasi.commento
  FOR EACH ROW EXECUTE FUNCTION trasi.commento_00_ts();

-- ---------------------------------------------------------------------------
-- 4. RLS: si legge tutto, si scrive solo il commento, e solo nella propria Casa
-- ---------------------------------------------------------------------------
ALTER TABLE trasi.report   ENABLE ROW LEVEL SECURITY;
ALTER TABLE trasi.report   FORCE  ROW LEVEL SECURITY;
ALTER TABLE trasi.commento ENABLE ROW LEVEL SECURITY;
ALTER TABLE trasi.commento FORCE  ROW LEVEL SECURITY;

DROP POLICY IF EXISTS rep_sel ON trasi.report;
DROP POLICY IF EXISTS rep_ins_flusso ON trasi.report;
DROP POLICY IF EXISTS com_sel ON trasi.commento;
DROP POLICY IF EXISTS com_ins_casa ON trasi.commento;
DROP POLICY IF EXISTS com_ins_rete ON trasi.commento;

-- Lettura: **il report di una Casa lo legge quella Casa**. L'AT/TI li leggono tutti (sono l'osservatorio);
-- `metabase_ro` no.
--
-- **Perché non `USING (true)`, che è la prima cosa che avevo scritto e che era sbagliata.** Il report per
-- Casa contiene i numeri **pieni** dei propri sportelli (è il rendiconto, foglio 4.3-B: «registrazione degli
-- accessi … raccolti tramite i form»), mentre le viste di confronto fra Case li espongono **mascherati** da
-- `k_anon` (`bozzano → '<5'`). Con `USING (true)` ogni Casa avrebbe letto i numeri non mascherati delle
-- altre, e il k-anonimato di §12 sarebbe stato aggirabile **leggendo un'altra superficie**: la protezione
-- esiste solo se tutte le vie la rispettano, e una via laterale la annulla.
--
-- La conseguenza per l'osservatorio è dichiarata: l'aggregato di rete è il report con
-- `ambito='osservatorio'`, che passa da `k_anon` come `v_confronto_case`. Chi vuole il quadro d'insieme usa
-- quello, non la somma dei rendiconti altrui.
DROP POLICY IF EXISTS rep_sel ON trasi.report;
CREATE POLICY rep_sel ON trasi.report
  FOR SELECT
  USING (
    casa_id = trasi.casa_corrente()
    OR current_user IN ('rete', 'ti')
  );

-- Scrittura: solo il flusso che genera il ciclo. Nessuna policy di UPDATE: `automazioni` non ha
-- nemmeno il GRANT (sotto), quindi un report, una volta generato, **non si corregge** — che è la
-- regola di Processi resa struttura.
--
-- **Conseguenza sul flusso, misurata.** Chi genera il report non può usare
-- `INSERT … ON CONFLICT DO UPDATE`: quel ramo richiede il privilegio `UPDATE` e Postgres lo nega
-- (`42501`). Verificato: `DO UPDATE` → respinto, `DO NOTHING` → accettato. È il comportamento voluto,
-- non un ostacolo: se il report di un mese esiste già, il ciclo **non lo riscrive** — registra che
-- esiste e prosegue (`ON CONFLICT DO NOTHING` + lettura dell'id esistente). Un report rigenerato
-- identico è una riscrittura silenziosa del rendiconto di una Casa, e la regola di Processi esiste
-- proprio per impedirla. Se un report fosse davvero sbagliato, si corregge con un atto esplicito
-- (una nuova riga con `ambito` dedicato, o l'intervento del TI), non con un `UPDATE` di un flusso.
CREATE POLICY rep_ins_flusso ON trasi.report FOR INSERT TO automazioni WITH CHECK (true);

CREATE POLICY com_sel ON trasi.commento FOR SELECT USING (true);

-- Un ruolo Casa commenta **come la propria Casa**: il `casa_id` viene dall'identità, mai dal corpo
-- della richiesta (principio 3, come ovunque nello shim). Commentare a nome di un'altra Casa non è
-- un errore da validare: è una riga che la policy non rende possibile.
CREATE POLICY com_ins_casa ON trasi.commento
  FOR INSERT TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
                casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano
  WITH CHECK (casa_id = trasi.casa_corrente());

-- `rete` e `ti` commentano come osservatorio (`casa_id IS NULL`): l'AT e il TI non appartengono a una
-- Casa, e attribuire loro quella sbagliata sarebbe peggio di non attribuirne nessuna.
CREATE POLICY com_ins_rete ON trasi.commento
  FOR INSERT TO rete, ti
  WITH CHECK (casa_id IS NULL);

-- ---------------------------------------------------------------------------
-- 5. GRANT — è QUI che vive la regola «non correggere il report»
-- ---------------------------------------------------------------------------
-- La specifica di Processi non si implementa con una convenzione ma con un privilegio **assente**.
-- Un ruolo Casa ha SELECT su `report` e nient'altro: un `UPDATE` fallisce con 42501, con lo stesso
-- errore con cui V4 protegge il dominio. Non c'è una via applicativa da chiudere, perché non c'è
-- una via applicativa che esista.
REVOKE ALL ON trasi.report, trasi.commento FROM PUBLIC;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON trasi.report
  FROM shim_rw, automazioni, metabase_ro, rete, ti,
       casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
       casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano, applicatore;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON trasi.commento
  FROM shim_rw, automazioni, metabase_ro, rete, ti,
       casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
       casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano, applicatore;

-- Il report si LEGGE: operatori, AT, TI, dashboard e — in sola lettura — anche `automazioni`, che
-- deve poter riconoscere un report già generato per non duplicarlo.
GRANT SELECT ON trasi.report TO
  casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
  casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano,
  rete, ti, metabase_ro, automazioni, shim_rw, applicatore;

-- Il flusso GENERA il report: INSERT, e nient'altro. **Nessun UPDATE**: è la regola di Processi.
GRANT INSERT, SELECT ON trasi.report TO automazioni;
GRANT USAGE, SELECT ON SEQUENCE trasi.report_id_seq TO automazioni;

-- I commenti: si leggono tutti, si scrivono nella propria Casa (la RLS decide quale).
GRANT SELECT ON trasi.commento TO
  casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
  casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano,
  rete, ti, metabase_ro, automazioni, shim_rw, applicatore;
GRANT INSERT (entita, entita_id, casa_id, testo) ON trasi.commento TO
  casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
  casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano, rete, ti;
GRANT USAGE, SELECT ON SEQUENCE trasi.commento_id_seq TO
  casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
  casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano, rete, ti;

-- Lo shim scrive i commenti **impersonando** il ruolo della Casa (`SET LOCAL ROLE`), quindi non ha
-- bisogno di INSERT proprio: come per `proposta`, `shim_rw` legge e basta.

-- ---------------------------------------------------------------------------
-- 6. Le viste di lettura per le superfici (Home, Metabase, chat)
-- ---------------------------------------------------------------------------
DROP VIEW IF EXISTS trasi.v_report;
CREATE VIEW trasi.v_report AS
SELECT r.id, r.casa_id, c.slug AS casa_slug, c.nome AS casa_nome,
       r.mese, r.ambito, r.contenuti, r.generato_ts, r.generato_da,
       (r.csv IS NOT NULL) AS ha_csv,
       (SELECT count(*) FROM trasi.commento cm
         WHERE cm.entita = 'report' AND cm.entita_id = r.id) AS commenti,
       (SELECT max(cm.ts) FROM trasi.commento cm
         WHERE cm.entita = 'report' AND cm.entita_id = r.id) AS ultimo_commento_ts
FROM trasi.report r
JOIN trasi.casa c ON c.id = r.casa_id;

-- `security_invoker = true`, ed è una scelta obbligata (non una preferenza).
--
-- La vista espone `contenuti`, che per l'ambito `casa` porta i numeri **non mascherati** della Casa. La RLS
-- di `report` decide quali righe il chiamante può vedere: con `security_invoker = true` quella decisione si
-- applica **al chiamante**; con `false` la vista girerebbe come owner (`trasi_owner`, che ha tutto) e
-- mostrerebbe a chiunque i report di chiunque — cioè il contrario di ciò che il k-anonimato protegge.
--
-- **Correzione di una motivazione sbagliata.** La prima versione di questo commento diceva che con `false`
-- «metabase_ro vedrebbe tutto». Misurato: `metabase_ro` vede tutto **lo stesso** con `true`, perché la mia
-- policy `rep_sel` non lo esclude — l'errore non era `security_invoker`, era la policy (corretta sopra).
-- Le due cose erano state confuse, ed è la ragione per cui questo test (`t_viste.sql` V09) ha chiesto
-- `security_invoker=false` per tutte le viste: è una regola pensata per le viste **aggregate** (`v_confronto_case`
-- e simili, che devono leggere oltre la RLS per produrre l'aggregato k-anonimo). `v_report` appartiene alla
-- categoria opposta — **non** aggrega, espone righe di dominio — e per quelle la regola corretta è `true`.
ALTER VIEW trasi.v_report SET (security_invoker = true);

DROP VIEW IF EXISTS trasi.v_commento;
CREATE VIEW trasi.v_commento AS
SELECT cm.id, cm.entita, cm.entita_id, cm.casa_id,
       c.slug AS casa_slug, c.nome AS casa_nome,
       cm.testo, cm.ts
FROM trasi.commento cm
LEFT JOIN trasi.casa c ON c.id = cm.casa_id;

ALTER VIEW trasi.v_commento SET (security_invoker = true);

GRANT SELECT ON trasi.v_report, trasi.v_commento TO
  casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
  casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano,
  rete, ti, metabase_ro, automazioni, shim_rw, applicatore;

-- ---------------------------------------------------------------------------
-- 7. Verifica di installazione — la regola di Processi, provata qui
-- ---------------------------------------------------------------------------
DO $verify$
DECLARE
  v_priv text;
  v_pol  int;
BEGIN
  -- **Il controllo che conta**: nessun ruolo operativo ha UPDATE su `report`. Se questa asserzione
  -- fallisce, la specifica di Processi («non correggerlo o modificarli») non è rispettata e il file
  -- non si installa — invece di installarsi e lasciare che qualcuno lo scopra usando il sistema.
  SELECT string_agg(DISTINCT grantee || ':' || privilege_type, ', ') INTO v_priv
    FROM information_schema.role_table_grants
   WHERE table_schema = 'trasi' AND table_name = 'report'
     AND privilege_type IN ('UPDATE', 'DELETE')
     AND grantee IN ('casa_santaspazio','casa_molo12','casa_erranti','casa_buscicchio','casa_sanbao',
                     'casa_minimus','casa_pop','casa_bozzano','casa_dream','casa_tuturano',
                     'rete','ti','shim_rw','automazioni');
  IF v_priv IS NOT NULL THEN
    RAISE EXCEPTION '024_report: ruoli con UPDATE/DELETE su report: % — la specifica vieta di modificare i report', v_priv;
  END IF;

  SELECT count(*) INTO v_pol FROM pg_policies
   WHERE schemaname='trasi' AND tablename='commento' AND policyname IN ('com_sel','com_ins_casa','com_ins_rete');
  IF v_pol <> 3 THEN
    RAISE EXCEPTION '024_report: attese 3 policy su commento, trovate %', v_pol;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname='commento_00_ts' AND NOT tgisinternal) THEN
    RAISE EXCEPTION '024_report: trigger commento_00_ts assente';
  END IF;

  RAISE NOTICE '024_report applicato: report (sola lettura per gli operatori, INSERT al solo flusso) + commento (RLS per Casa) + v_report/v_commento';
END
$verify$;

RESET ROLE;
