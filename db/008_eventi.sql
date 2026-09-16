-- Trasi — db/008_eventi.sql  (delta «eventi visibili», dopo B5)
--
-- Una cosa sola: la vista `trasi.v_eventi`, gli eventi **in programma** di una Casa, perché un
-- evento scritto in chat da `crea_evento` (opzione A) sia visibile sul sito e non solo nella
-- risposta dell'assistente.
--
-- Perché serve una vista e non basta `trasi.evento`. Due ragioni, entrambe già pagate altrove:
--
--   1. **Le card leggono viste, non tabelle.** È il principio con cui B5 ha costruito le dashboard
--      (`metabase/dashboard.py`): Home, chat e cruscotto non possono raccontare storie diverse se
--      leggono lo stesso strato. Una card che interrogasse `trasi.evento` direttamente sarebbe la
--      prima eccezione, e la seconda arriverebbe subito dopo.
--   2. **La riga è già pronta da mostrare.** La vista compone `quando` (l'intervallo in italiano) e
--      `giorni_all_inizio`: ricomporli in SQL dentro una card significherebbe due formattazioni da
--      tenere allineate, che è esattamente il difetto che `v_oggi_casa` esiste per evitare.
--
-- Perché un file separato da db/000–020: quei file appartengono a B1/B4/B5 e il loro ordinamento è
-- congelato; questo è un delta successivo. `db/apply.sh` lo prevede nella propria ORDER (008),
-- subito dopo `007_dash.sql`, perché i GRANT qui sotto presuppongono che `metabase_ro` esista e che
-- i REVOKE di 007 siano già passati.
--
-- Nessuna scrittura: è una vista di sola lettura. V4 resta invariato — gli eventi li scrive
-- `crea_evento` (diretta, per la propria Casa) o l'upsert iCal di `automazioni`, mai questa vista.
--
-- k-anonimato: **non si applica**, e vale la pena dirlo invece di lasciarlo implicito. La soglia
-- (§12) protegge i conteggi *sulle persone* (richieste di orientamento, destinazioni): un evento è
-- un fatto pubblico della rete, già esportato riga per riga in `v_kb_export` e già leggibile da ogni
-- ruolo Casa. Nascondere il titolo di un evento sotto una soglia numerica non proteggerebbe nessuno
-- e toglierebbe all'operatore l'unica schermata dove l'evento appena inserito si vede.

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
    FROM unnest(ARRAY['trasi.evento','trasi.casa','trasi.fonte']) x
   WHERE to_regclass(x) IS NULL;
  IF v_missing IS NOT NULL THEN
    RAISE EXCEPTION '008_eventi: mancano % — applica prima db/000–012', v_missing;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'metabase_ro') THEN
    RAISE EXCEPTION '008_eventi: ruolo metabase_ro assente — applica prima db/000_roles.sql';
  END IF;
END
$pre$;

-- ---------------------------------------------------------------------------
-- 1. La vista
-- ---------------------------------------------------------------------------
-- «In programma» è `COALESCE(fine, inizio) >= now()`, la stessa condizione di `v_kb_export`: un
-- evento di più giorni resta visibile finché non è finito, e un evento senza `fine` resta visibile
-- finché non è iniziato. Le due viste devono concordare, altrimenti la chat e il cruscotto
-- direbbero cose diverse sullo stesso evento — che è il difetto che questo strato esiste per
-- impedire.
--
-- `annullato = false`: un evento ritirato non è in programma. La riga resta nel database (V4 vieta
-- il DELETE sul dominio) e resta leggibile a chi ha bisogno di ricostruire la storia; qui no.
--
-- `fonte_nome`: gli eventi scritti dall'operatore non hanno `fonte_id` — non vengono da una fonte
-- esterna, li ha inseriti una persona. Il COALESCE lo dichiara invece di lasciare la colonna vuota,
-- che si leggerebbe come «provenienza ignota», che è un'altra cosa e più allarmante. Il testo è lo
-- stesso che `crea_evento` mette nel `badge` (`shim/app/badge.py`): due parole diverse per la stessa
-- provenienza farebbero sembrare due cose diverse la stessa cosa.
DROP VIEW IF EXISTS trasi.v_eventi;
CREATE VIEW trasi.v_eventi AS
SELECT e.id, e.casa_id, c.slug AS casa_slug, c.nome AS casa_nome,
       e.titolo, e.descrizione, e.inizio, e.fine, e.luogo_testo, e.url,
       COALESCE(f.nome, 'inserito dall''operatore') AS fonte_nome,
       COALESCE(e.affidabilita, 2) AS affidabilita,
       e.aggiornato_ts, e.creato_ts,
       (e.inizio::date - current_date) AS giorni_all_inizio,
       concat_ws(' – ',
                 to_char(e.inizio, 'DD/MM/YYYY'),
                 to_char(e.inizio, 'HH24:MI')
                   || CASE WHEN e.fine IS NOT NULL THEN '–' || to_char(e.fine, 'HH24:MI') END
       ) AS quando
FROM trasi.evento e
JOIN trasi.casa c ON c.id = e.casa_id
LEFT JOIN trasi.fonte f ON f.id = e.fonte_id
WHERE e.annullato = false
  AND COALESCE(e.fine, e.inizio) >= now();

-- ---------------------------------------------------------------------------
-- 2. Proprietà e permessi
-- ---------------------------------------------------------------------------
-- security_invoker = false come le altre viste di reporting: la vista espone righe che ogni ruolo
-- Casa ha già diritto di leggere (la matrice §11 gli concede `evento`), ma girare come owner la
-- rende leggibile anche a `metabase_ro`, che è il consumatore per cui questa vista esiste.
ALTER VIEW trasi.v_eventi SET (security_invoker = false);

-- Gli stessi destinatari delle altre viste di reporting (db/004_views.sql): i ruoli Casa per la
-- chat e il cruscotto, `metabase_ro` per le dashboard, `automazioni` e `shim_rw` perché sono i due
-- processi che parlano al database per conto di qualcun altro.
GRANT SELECT ON trasi.v_eventi
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao, casa_minimus, casa_pop,
     casa_bozzano, casa_dream, casa_tuturano, rete, ti, metabase_ro, automazioni, shim_rw, applicatore;

-- ---------------------------------------------------------------------------
-- 3. Verifica di installazione
--    Si controlla l'**effetto**, non l'intenzione: una vista creata ma illeggibile a metà dei suoi
--    consumatori si scoprirebbe solo aprendo la dashboard, con un «permission denied» a runtime.
-- ---------------------------------------------------------------------------
DO $verify$
DECLARE v_n integer;
BEGIN
  IF NOT has_table_privilege('metabase_ro', 'trasi.v_eventi', 'SELECT') THEN
    RAISE EXCEPTION '008_eventi: metabase_ro non legge v_eventi';
  END IF;
  IF NOT has_table_privilege('casa_sanbao', 'trasi.v_eventi', 'SELECT') THEN
    RAISE EXCEPTION '008_eventi: casa_sanbao non legge v_eventi';
  END IF;

  -- Le colonne che le card e la chat citano per nome: se una cambia, il guasto deve arrivare qui e
  -- non dentro una dashboard che mostra una tabella vuota.
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
     WHERE table_schema = 'trasi' AND table_name = 'v_eventi'
       AND column_name = 'giorni_all_inizio'
  ) THEN
    RAISE EXCEPTION '008_eventi: colonna giorni_all_inizio assente';
  END IF;

  SELECT count(*) INTO v_n FROM trasi.v_eventi;
  RAISE NOTICE '008_eventi applicato: v_eventi leggibile da metabase_ro e dai ruoli Casa, % eventi in programma', v_n;
END
$verify$;

RESET ROLE;
