-- Trasi — flussi/fixtures/criterio_b4.sql
--
-- Fixture del criterio §10 B4 (B4-FLW-02): **2 proposte approvate + 1 scaduta da 31 giorni**
-- → `applica.sh` → `applicata 2 · scaduta 1`, 3 righe di audit, `flusso_run.esito='ok'`,
-- e sulla proposta promossa da esterno `affidabilita=2` + `fonte_id` + `data_aggiornamento`.
--
-- Come è costruita, e perché così.
--
-- * Le proposte le crea **`rete`**, non l'amministratore: è il ruolo che in produzione propone i dati
--   del territorio (AT/AQ, §11). Le fixture passano dalla stessa RLS della produzione, quindi una
--   fixture impossibile non passa inosservata (lezione del report B1).
-- * `stato='approvata'` non si scrive nell'INSERT: `db/005` respinge con 42501 un INSERT che tenti di
--   nascere deciso (auto-approvazione, V4 regola 1) e `db/006` vieta la transizione
--   `proposta → applicata` a un client. Si approva quindi con un **`UPDATE` del ruolo competente**,
--   che è esattamente ciò che fa l'umano in coda: due passi, non un trucco.
-- * La promozione da esterno usa `promuovi_esterno` su un `luogo` **esistente** con `lat`/`lon`
--   separati nel payload: è il ramo che produce `affidabilita=2`, `fonte_id` e `data_aggiornamento`
--   (ramo verificato dal coordinatore; evitate la trappola dell'`entita_id` NULL e quella del `geom` WKT).
--
-- **L'unica scrittura fuori dai ruoli applicativi, dichiarata.** `proposta.proposto_ts` non è
-- grantata in INSERT a nessun ruolo client (il `DEFAULT now()` la scrive il database): è corretto, ma
-- significa che **nessuna fixture può invecchiare una proposta** attraverso il percorso di produzione —
-- il tempo che passa non ha un percorso applicativo. La scaduta da 31 giorni richiede quindi un passo
-- come `trasi_owner` che sposta `proposto_ts` indietro: è una **simulazione del tempo**, non una
-- scrittura di dominio, e resta confinata a righe marcate `B4FLW02:`.
--
-- Idempotente: la fixture cancella prima le proprie proposte (per `motivazione`, il suo contrassegno) e
-- riporta il luogo promosso al valore del seed, così due esecuzioni di fila danno lo stesso stato.
-- Le proposte non si cancellano mai per mano applicativa: qui la pulizia riguarda solo righe marcate
-- come fixture, mai memoria applicativa.
--
-- Uso:  psql … -f flussi/fixtures/criterio_b4.sql
\set ON_ERROR_STOP on
\set VERBOSITY terse

-- I due nomi del luogo promosso: il seed e quello scritto dal ramo `promuovi_esterno`.
\set nome_seed 'CAF ACLI La Rosa'
\set nome_promosso 'CAF Promosso B4FLW02'

-- ---------------------------------------------------------------------------
-- 0. Pulizia delle esecuzioni precedenti di questa fixture
-- ---------------------------------------------------------------------------
SET ROLE trasi_owner;
SET search_path = trasi, public, pg_temp;

DELETE FROM trasi.audit WHERE proposta_id IN
  (SELECT id FROM trasi.proposta WHERE motivazione LIKE 'B4FLW02:%'
                                    OR motivazione = 'verificato da operatore');
DELETE FROM trasi.proposta WHERE motivazione LIKE 'B4FLW02:%'
                             OR motivazione = 'verificato da operatore';

-- Le entità che la fixture *crea* (non modifica) vanno rimosse, altrimenti ogni riesecuzione ne
-- lascerebbe una in più e il confronto prima/dopo non sarebbe più lo stesso confronto.
-- `scheda_servizio` non ha un campo `chiuso`/`annullato` con cui fare soft-close (a differenza di
-- `luogo.chiuso_il` e `evento.annullato`): è una tabella di *entità correnti*, non di storia.
-- La rimozione avviene qui come `trasi_owner` e riguarda **solo** le righe che portano il
-- contrassegno della fixture — mai memoria della rete.
DELETE FROM trasi.audit WHERE entita = 'scheda_servizio' AND entita_id IN
  (SELECT id FROM trasi.scheda_servizio WHERE titolo LIKE '%(fixture B4FLW02)');
DELETE FROM trasi.scheda_servizio WHERE titolo LIKE '%(fixture B4FLW02)';

-- Il luogo promosso torna al valore del **seed**. Si individua per fonte (`CAF ACLI Brindisi`) e non
-- per nome: il nome è proprio ciò che il ramo `promuovi_esterno` riscrive, quindi cercarlo per nome
-- renderebbe la fixture non idempotente già alla seconda esecuzione. Il ripristino copre anche il
-- nome, l'affidabilità, gli orari, la descrizione e la data — cioè tutto ciò che la promozione tocca.
-- Effetto collaterale voluto: ripara la deriva lasciata dalle prove manuali su un DB condiviso
-- (lezione B3: «le prove su un DB condiviso vanno fatte in transazione o pulite subito»).
UPDATE trasi.luogo l
   SET nome = :'nome_seed', affidabilita = 1, orari = NULL, ext_ref = NULL,
       descrizione = 'Patronato ACLI — assistenza fiscale e ISEE',
       note_accesso = 'Orari e indirizzo da verificare',
       data_aggiornamento = current_date
 WHERE l.fonte_id = (SELECT f.id FROM trasi.fonte f WHERE f.nome = 'CAF ACLI Brindisi');

RESET ROLE;

-- ---------------------------------------------------------------------------
-- 1. Le tre proposte.
--
--    **Chi propone non decide** (V4 regola 1, policy RESTRICTIVE `no_self_approve` di db/005): se una
--    riga la creasse `rete`, `rete` non potrebbe approvarla e l'UPDATE toccherebbe 0 righe — senza
--    errore, perché la RLS filtra invece di sollevare. Quindi le due proposte da approvare nascono da
--    identità diverse da chi le approva, come in produzione:
--      1a  proposta dall'operatore di San Bao (il CAF ACLI è nella zona di La Rosa, US-01) → decide AT
--      1b  proposta dalla rete (dato del territorio)                                  → decide il gestore
-- ---------------------------------------------------------------------------

-- 1a. PROMOZIONE da fonte esterna su un luogo ESISTENTE. È questa che deve uscire dal run con
--     `affidabilita=2`, `fonte_id` di OSM e `data_aggiornamento` = oggi.
SET ROLE casa_sanbao;
SET search_path = trasi, public, pg_temp;

INSERT INTO trasi.proposta (origine, tipo, entita, entita_id, casa_id, fonte_id, payload, motivazione)
SELECT 'ricerca_esterna', 'promuovi_esterno', 'luogo', l.id, l.casa_id, f.id,
       jsonb_build_object(
         'nome', :'nome_promosso',
         'lat', 40.60609, 'lon', 17.95196,
         'orari', jsonb_build_object(
            'lun', jsonb_build_array('09:00','13:00'),
            'mar', jsonb_build_array('09:00','13:00'),
            'mer', jsonb_build_array('09:00','13:00'),
            'gio', jsonb_build_array('09:00','13:00'),
            'ven', jsonb_build_array('09:00','13:00')),
         'descrizione', 'Dato esterno promosso in memoria (fixture B4-FLW-02)'),
       'B4FLW02: promozione da fonte esterna'
  FROM trasi.luogo l, trasi.fonte f
 WHERE l.fonte_id = (SELECT f2.id FROM trasi.fonte f2 WHERE f2.nome = 'CAF ACLI Brindisi')
   AND f.nome = 'OpenStreetMap/Overpass-2';
RESET ROLE;

-- 1b. NUOVA SCHEDA di servizio della Casa di Bozzano: `approvatore_ruolo='gestore'` (regola §11).
SET ROLE rete;
SET search_path = trasi, public, pg_temp;

INSERT INTO trasi.proposta (origine, tipo, entita, casa_id, payload, motivazione)
SELECT 'manuale', 'nuova_scheda', 'scheda_servizio', c.id,
       jsonb_build_object('titolo', 'Sportello ISEE (fixture B4FLW02)',
                          'descrizione', 'Sportello di assistenza ISEE',
                          'categoria', 'fiscale_isee',
                          'referente_ruolo', 'gestore'),
       'B4FLW02: nuova scheda della Casa'
  FROM trasi.casa c WHERE c.slug = 'bozzano';

-- 1c. SCADUTA: `scade_il` è 31 giorni fa. La finestra si dichiara (`proposta_00_default_tg` rispetta
--     lo `scade_il` fornito), quindi `scadi_proposte()` la marcherà `scaduta`.
INSERT INTO trasi.proposta (origine, tipo, entita, casa_id, payload, motivazione, scade_il)
SELECT 'manuale', 'modifica_orari_casa', 'casa', c.id,
       jsonb_build_object('orari_provvisori', true),
       'B4FLW02: proposta scaduta da 31 giorni',
       current_date - 31
  FROM trasi.casa c WHERE c.slug = 'bozzano';

RESET ROLE;

-- ---------------------------------------------------------------------------
-- 2. Invecchiamento della sola 1c: simulazione del tempo che passa (vedi nota in testa).
--    Solo per la riga marcata, prima dell'approvazione, così nessun trigger la vede «nuova».
-- ---------------------------------------------------------------------------
SET ROLE trasi_owner;
SET search_path = trasi, public, pg_temp;
UPDATE trasi.proposta SET proposto_ts = now() - interval '31 days'
 WHERE motivazione = 'B4FLW02: proposta scaduta da 31 giorni';
RESET ROLE;

-- ---------------------------------------------------------------------------
-- 3. Approvazione umana (1a e 1b): due `UPDATE`, uno per ruolo competente.
--    1a è `promuovi_esterno` → `approvatore_ruolo='at'`     → decide `rete` (AT/AQ, §11).
--    1b è `nuova_scheda`   → `approvatore_ruolo='gestore'` → decide il gestore di Bozzano.
--    Mai dalla stessa identità che ha proposto: la policy RESTRICTIVE `no_self_approve` (db/005)
--    farebbe toccare 0 righe, e il criterio «applicata 2» non si raggiungerebbe.
-- ---------------------------------------------------------------------------
SET ROLE rete;
SET search_path = trasi, public, pg_temp;
UPDATE trasi.proposta SET stato = 'approvata', nota_decisione = 'approvata in coda (AT)'
 WHERE motivazione = 'B4FLW02: promozione da fonte esterna' AND stato = 'proposta';
RESET ROLE;

SET ROLE casa_bozzano;
SET search_path = trasi, public, pg_temp;
UPDATE trasi.proposta SET stato = 'approvata', nota_decisione = 'approvata dal gestore'
 WHERE motivazione = 'B4FLW02: nuova scheda della Casa' AND stato = 'proposta';
RESET ROLE;

-- ---------------------------------------------------------------------------
-- 4. Lo stato della fixture, per chi la esegue (prima del run)
-- ---------------------------------------------------------------------------
SET ROLE trasi_owner;
SET search_path = trasi, public, pg_temp;

SELECT p.stato, count(*) AS n
  FROM trasi.proposta p WHERE p.motivazione LIKE 'B4FLW02:%'
 GROUP BY 1 ORDER BY 1;

SELECT id, tipo, entita, entita_id, stato, scade_il, approvatore_ruolo, approvato_da
  FROM trasi.proposta WHERE motivazione LIKE 'B4FLW02:%' ORDER BY id;
RESET ROLE;
