-- Trasi — db/028_fasce_cittadino.sql
-- Foglio 4.4 «Anagrafica cittadino» del gruppo Processi: fascia d'età, genere, area di provenienza
-- del colloquio di sportello, nella forma compatibile con V5.
--
-- ---------------------------------------------------------------------------
-- La decisione, e chi l'ha presa
-- ---------------------------------------------------------------------------
-- Il foglio 4.4 chiede di raccogliere «età, genere, provenienza» di chi si rivolge allo sportello.
-- Presi singolarmente sono dati banali; presi insieme, legati a una Casa e a un giorno, identificano
-- una persona: «una donna extra-UE di 72 anni, passata da San Bao martedì mattina» a San Bao è
-- probabilmente una sola persona. Non serve il nome perché sia lei.
--
-- Per questo `db/025` li aveva lasciati fuori («la forma compatibile esiste — fasce + conteggi
-- mascherati — ma è una decisione di Processi e DPO»). **Quella decisione è arrivata** e sono
-- scelte le fasce con la soglia di k-anonimato. Le tre scelte che la compongono, implementate una
-- per una e nessuna delle quali è un'opinione:
--
--   1. **fasce, mai il valore esatto** — l'età è una classe (`60-74`), non un numero: due persone
--      di 71 e 74 anni sono indistinguibili nel dato, che è esattamente lo scopo;
--   2. **vocabolario chiuso** — le fasce sono quelle già dichiarate da `evento.fascia_eta`
--      (`db/025`): la stessa scala serve l'evento (a chi è rivolto) e il colloquio (chi è venuto),
--      e una seconda scala renderebbe impossibile confrontarli;
--   3. **conteggio mascherato da `k_anon`** — sotto la soglia `[P] k_anonimato` (5) il numero non
--      esce: `n` è NULL e resta `n_label` (`<5`). Non è un nascondiglio applicativo: è la stessa
--      funzione di `v_report_mensile` e `v_confronto_case`, e la vista qui sotto non ha una colonna
--      grezza da cui rileggerlo.
--
-- ---------------------------------------------------------------------------
-- Cosa NON cambia, ed è la parte importante
-- ---------------------------------------------------------------------------
-- **`richiesta` resta senza identificativi.** Le tre colonne nuove sono attributi del colloquio, non
-- della persona: niente id, niente nome, niente collegamento a una chat, niente data di nascita da
-- cui l'età si ricalcola. Chi legge una riga sa che quel giorno c'è stato un colloquio con una
-- persona in una fascia d'età — non *quale* persona.
--
-- Il presidio di `t_seed.sql` O05 («richiesta ha colonne extra») viene **aggiornato di conseguenza e
-- non allentato**: l'elenco ammette le tre colonne nuove e continua a rifiutare qualunque altra.
-- La differenza fra «il contratto è cambiato per decisione» e «qualcuno ha aggiunto un campo» deve
-- restare visibile: l'elenco è esplicito e commentato, non un `NOT LIKE '%nome%'`.
--
-- **Il k-anonimato protegge i conteggi, non la riga.** Una Casa che legge il proprio registro vede
-- le proprie righe (è il suo rendiconto, foglio 4.3-B, come per `report` ambito `casa`): la soglia
-- interviene dove i numeri si aggregano e attraversano le Case. È la stessa distinzione già presa in
-- `db/024`; applicarla diversamente qui produrrebbe due dottrine in due migrazioni.
--
-- Idempotente: rieseguibile senza errori.
\set ON_ERROR_STOP on
\set VERBOSITY terse

SET ROLE trasi_owner;
SET search_path = trasi, public, pg_temp;

-- ---------------------------------------------------------------------------
-- Precondizioni
-- ---------------------------------------------------------------------------
-- `k_anon` è la funzione che applica la soglia: se manca, questa migrazione installerebbe colonne che
-- nessuno maschera — un dato sensibile raccolto e mai protetto, che è la cosa peggiore.
DO $pre$
BEGIN
  IF to_regprocedure('trasi.k_anon(bigint)') IS NULL THEN
    RAISE EXCEPTION '028_fasce_cittadino: manca trasi.k_anon() — applica prima db/004_views.sql';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'evento_fascia_eta_check') THEN
    RAISE EXCEPTION '028_fasce_cittadino: manca il CHECK di evento.fascia_eta (db/025): la scala delle '
                    'fasce deve essere UNA sola, altrimenti evento e richiesta non si confrontano';
  END IF;
END
$pre$;

-- ---------------------------------------------------------------------------
-- 1. `richiesta` — le tre colonne del foglio 4.4
-- ---------------------------------------------------------------------------
-- `NULL` è un valore legittimo e previsto, non un dato mancante da correggere: la persona può non
-- dichiarare età, genere o provenienza. Per questo `genere` e `provenienza` hanno `non_dichiarato*`
-- nel vocabolario invece di essere NOT NULL: un campo obbligatorio spingerebbe l'operatore a
-- indovinare, che è il modo in cui un dato inventato entra in un report e da lì in una decisione.
ALTER TABLE trasi.richiesta ADD COLUMN IF NOT EXISTS fascia_eta   text;
ALTER TABLE trasi.richiesta ADD COLUMN IF NOT EXISTS genere       text;
ALTER TABLE trasi.richiesta ADD COLUMN IF NOT EXISTS provenienza  text;

COMMENT ON COLUMN trasi.richiesta.fascia_eta IS
  'Fascia d''età di chi si è rivolto allo sportello (foglio 4.4). Classi, mai la data di nascita: la '
  'stessa scala di evento.fascia_eta, così «a chi è rivolto l''evento» e «chi è venuto» si confrontano. '
  'NULL = non dichiarata.';
COMMENT ON COLUMN trasi.richiesta.genere IS
  'Genere dichiarato dalla persona (foglio 4.4), vocabolario chiuso. «non_dichiarato» è un valore '
  'legittimo e non un buco: un campo obbligatorio farebbe indovinare l''operatore.';
COMMENT ON COLUMN trasi.richiesta.provenienza IS
  'Area di provenienza (foglio 4.4): Italia, UE, extra-UE. **Non** il Paese e **non** la nazionalità: '
  'l''area è ciò che serve a decidere se stanziare un mediatore culturale, il Paese è un dato '
  'identificativo in più che non serve a quella decisione.';

-- ---------------------------------------------------------------------------
-- 2. I vocabolari, chiusi
-- ---------------------------------------------------------------------------
-- Le fasce sono **letteralmente** quelle di `evento.fascia_eta` (`db/025`), più `non_dichiarata`:
-- l'evento usa `tutte` per «rivolto a tutti», che su un colloquio non ha senso (una persona ha
-- un'età), mentre «non dichiarata» è l'assenza della risposta. Due cose diverse, due valori diversi.
ALTER TABLE trasi.richiesta DROP CONSTRAINT IF EXISTS richiesta_fascia_eta_check;
ALTER TABLE trasi.richiesta ADD CONSTRAINT richiesta_fascia_eta_check
  CHECK (fascia_eta IS NULL OR fascia_eta IN
         ('0-13','14-17','18-29','30-44','45-59','60-74','75+','non_dichiarata'));

-- `genere`: `altro` e `non_dichiarato` sono due cose diverse — «mi riconosco in un'altra categoria» e
-- «non rispondo» — e fonderle perderebbe l'unica differenza che la persona ha voluto dichiarare.
ALTER TABLE trasi.richiesta DROP CONSTRAINT IF EXISTS richiesta_genere_check;
ALTER TABLE trasi.richiesta ADD CONSTRAINT richiesta_genere_check
  CHECK (genere IS NULL OR genere IN ('donna','uomo','altro','non_dichiarato'));

-- `provenienza`: l'**area**, non il Paese. Il Paese, incrociato con il quartiere, è identificativo;
-- la decisione che il report deve sostenere è «serve un mediatore culturale?» — a cui l'area risponde.
ALTER TABLE trasi.richiesta DROP CONSTRAINT IF EXISTS richiesta_provenienza_check;
ALTER TABLE trasi.richiesta ADD CONSTRAINT richiesta_provenienza_check
  CHECK (provenienza IS NULL OR provenienza IN ('italia','ue','extra_ue','non_dichiarata'));

-- ---------------------------------------------------------------------------
-- 3. L'indice per l'aggregazione
-- ---------------------------------------------------------------------------
-- Le tre colonne si leggono **sempre** aggregate (per Casa, mese, fascia), mai una riga per volta: è
-- il loro unico uso legittimo. L'indice è su (casa_id, fascia_eta) e la finestra mensile si calcola
-- in lettura: un indice su `date_trunc('month', ts)` non sarebbe ammesso (espressione non-immutable
-- in un predicato d'indice) e i dati di un mese sono comunque pochi.
CREATE INDEX IF NOT EXISTS richiesta_fasce_idx ON trasi.richiesta (casa_id, fascia_eta);

-- ---------------------------------------------------------------------------
-- 4. La vista: le distribuzioni, con il numero mascherato
-- ---------------------------------------------------------------------------
-- Una riga per (Casa, mese, dimensione, valore) — la forma «lunga», che permette di aggiungere una
-- dimensione senza cambiare lo schema della vista.
--
-- **`n` è NULL sotto soglia.** La colonna grezza `cnt` vive dentro il CTE e **non compare fra le
-- colonne di uscita**: chi interroga la vista non ha un secondo canale da cui rileggere il numero che
-- la soglia vieta. È la stessa proprietà di `fn_statistiche_casa` (db/022) e la ragione è che una
-- mascheratura aggirabile con un `SELECT *` non è una mascheratura.
--
-- Le righe `non_dichiarat*` NON sono un buco da nascondere: è il conteggio di chi non ha risposto, e
-- il report deve poterlo mostrare («il 40% non dichiara l'età») perché una raccolta che non funziona
-- va vista, non nascosta.
DROP VIEW IF EXISTS trasi.v_fasce_cittadino;
CREATE VIEW trasi.v_fasce_cittadino AS
WITH celle AS (
  SELECT r.casa_id,
         date_trunc('month', r.ts)::date AS mese,
         d.dimensione,
         CASE d.dimensione
           WHEN 'fascia_eta'  THEN COALESCE(r.fascia_eta, 'non_dichiarata')
           WHEN 'genere'      THEN COALESCE(r.genere, 'non_dichiarato')
           WHEN 'provenienza' THEN COALESCE(r.provenienza, 'non_dichiarata')
         END AS valore,
         count(*) AS cnt
  FROM trasi.richiesta r
  CROSS JOIN (VALUES ('fascia_eta'), ('genere'), ('provenienza')) AS d(dimensione)
  GROUP BY 1, 2, 3, 4
)
SELECT c.casa_id,
       cs.slug AS casa_slug,
       cs.nome AS casa_nome,
       c.mese,
       c.dimensione,
       c.valore,
       a.n,
       a.n_label
FROM celle c
JOIN trasi.casa cs ON cs.id = c.casa_id
CROSS JOIN LATERAL trasi.k_anon(c.cnt) a;

COMMENT ON VIEW trasi.v_fasce_cittadino IS
  'Distribuzioni del foglio 4.4 (fascia d''età, genere, area di provenienza) per Casa e mese. `n` è '
  'NULL sotto la soglia [P] k_anonimato e resta `n_label` (<5, —): il numero grezzo non esce dal '
  'database. Il valore `non_dichiarat*` conta chi non ha risposto, ed è un''informazione, non un buco.';

-- `security_invoker = false` come le altre viste di reporting (db/004): è ciò che permette a
-- `metabase_ro`, che non ha SELECT su `richiesta`, di leggere **solo** le celle mascherate.
ALTER VIEW trasi.v_fasce_cittadino SET (security_invoker = false);

-- ---------------------------------------------------------------------------
-- 5. I permessi
-- ---------------------------------------------------------------------------
-- `metabase_ro` **è** incluso, ed è la differenza con `richiesta` (da cui è escluso): la vista non
-- porta righe di sportello, porta celle mascherate. È esattamente il motivo per cui la vista esiste —
-- dare al cruscotto la distribuzione senza dargli il registro.
GRANT SELECT ON trasi.v_fasce_cittadino TO
  casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
  casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano,
  rete, ti, metabase_ro, automazioni, shim_rw, applicatore;

-- ---------------------------------------------------------------------------
-- 6. Verifica di installazione
-- ---------------------------------------------------------------------------
DO $verify$
DECLARE v_missing text; v_buchi int;
BEGIN
  SELECT string_agg(v.c, ', ') INTO v_missing FROM (VALUES
    ('fascia_eta'),('genere'),('provenienza')
  ) AS v(c)
  WHERE NOT EXISTS (SELECT 1 FROM information_schema.columns ic
                     WHERE ic.table_schema = 'trasi' AND ic.table_name = 'richiesta'
                       AND ic.column_name = v.c);
  IF v_missing IS NOT NULL THEN
    RAISE EXCEPTION '028_fasce_cittadino: colonne non aggiunte a richiesta: %', v_missing;
  END IF;

  SELECT string_agg(c.conname, ', ') INTO v_missing FROM (VALUES
    ('richiesta_fascia_eta_check'),('richiesta_genere_check'),('richiesta_provenienza_check')
  ) AS c(conname)
  WHERE NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = c.conname);
  IF v_missing IS NOT NULL THEN
    RAISE EXCEPTION '028_fasce_cittadino: CHECK mancanti: %', v_missing;
  END IF;

  -- La proprietà che conta: la vista NON espone una colonna con il conteggio grezzo. Se un domani
  -- qualcuno aggiungesse `cnt` alle colonne di uscita, il k-anonimato sarebbe aggirabile con un
  -- `SELECT *` e questo test è il posto in cui accorgersene.
  SELECT count(*) INTO v_buchi FROM information_schema.columns
   WHERE table_schema = 'trasi' AND table_name = 'v_fasce_cittadino'
     AND column_name IN ('cnt', 'conteggio', 'n_grezzo', 'totale');
  IF v_buchi > 0 THEN
    RAISE EXCEPTION '028_fasce_cittadino: v_fasce_cittadino espone una colonna di conteggio grezzo (%): '
                    'il k-anonimato sarebbe aggirabile con un SELECT *', v_buchi;
  END IF;

  IF to_regclass('trasi.v_fasce_cittadino') IS NULL THEN
    RAISE EXCEPTION '028_fasce_cittadino: v_fasce_cittadino non creata';
  END IF;

  RAISE NOTICE '028_fasce_cittadino applicato: richiesta (fascia_eta, genere, provenienza) a vocabolario '
               'chiuso · indice richiesta_fasce_idx · v_fasce_cittadino (k-anonima, nessuna colonna grezza)';
END
$verify$;