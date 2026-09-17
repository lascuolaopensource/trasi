-- Trasi — db/029_persone_casa.sql
-- Foglio 1.1 «Persone» del gruppo Processi: chi lavora e frequenta la Casa — nome, ruolo, competenze.
--
-- ---------------------------------------------------------------------------
-- La decisione, e chi l'ha presa
-- ---------------------------------------------------------------------------
-- `db/025` aveva lasciato fuori le persone: «sono dati personali che finirebbero in `v_kb_export` e
-- quindi citabili in chat; serve decidere consenso, retention e visibilità». **La decisione è
-- arrivata** ed è la forma C: **i nomi entrano nella knowledge base**, perché è quello che la rende
-- utile («chi è il referente di San Bao?» ha una risposta), e la condizione che la rende legittima
-- è il **consenso**.
--
-- Quindi il consenso non è un commento: è **una colonna e una condizione della vista**. Una persona
-- compare in `v_kb_export` — cioè diventa citabile dall'assistente — se e solo se
-- `consenso_il IS NOT NULL`. Niente consenso, niente nome in chat: il dato può stare nella scheda
-- della Casa, resta inaccessibile alla KB, e nessun filtro può farglielo pubblicare.
--
-- ---------------------------------------------------------------------------
-- I tre punti che la decisione chiede, e come sono presidiati
-- ---------------------------------------------------------------------------
--   * **Consenso**: `consenso_il` (data, non booleano) — una data è un'asserzione verificabile,
--     un booleano è un interruttore che nessuno sa perché sia acceso. `revoca_il` la revoca.
--   **Retenzione**: la revoca NON cancella la riga (serve a tenere la storia di quando era
--   consensata) ma la **toglie dalla KB**; la cancellazione fisica è un `DELETE` della Casa, che la
--   RLS le concede — e che il flusso di export rimuove da Onyx (B4-FLW-04: «DELETE dei trasi:*
--   non più in vista»).
--   **Visibilità**: la tabella si legge nella rete (come `scheda_servizio`, T09 «tutti leggono
--   tutto») ma **non** da `metabase_ro`: i nomi non sono un numero di dashboard. La superficie
--   verso il cittadino è solo la KB, e quella è sotto consenso.
--
-- ---------------------------------------------------------------------------
-- Cosa non c'è, ed è deliberato
-- ---------------------------------------------------------------------------
-- **Nessun contatto.** Né email né telefono: `pii.TELEFONO` e `pii.EMAIL` rifiuterebbero il valore
-- alla scrittura (lezione di `db/025` con `casa.telefono`), e per un dato personale di un operatore
-- non c'è «limite dichiarato» che regga — un recapito personale scritto in una tabella esportata in
-- KB è un dato personale pubblicato. Il contatto resta `casa.email_digest` (di servizio) e i luoghi.
-- Per lo stesso motivo il campo è **uno solo, `nome`**: il foglio 1.1 chiede «Nome Cognome» come
-- voce unica, e spezzarlo in `nome`+`cognome` introdurrebbe un nome di colonna che il presidio
-- V5 del contratto vieta (`cognome` è nella lista dei campi non ammessi). «Maria Rossi» è un dato.
--
-- **«Chi lo abita» non c'è.** È una colonna diversa del foglio, riguarda dove vivono le persone e
-- va trattata come il foglio 4.4, non come una scheda di servizio.
--
-- Perché NON c'è `persona_casa` in `v_scritture_senza_audit` (db/006): quella vista rileva le
-- mutazioni del dominio **fuori** dai percorsi dichiarati, e le sue eccezioni sono il seed
-- (`trasi_owner`) e la gestione diretta della propria Casa (`casa_<slug>`). La scrittura di una
-- persona è esattamente quest'ultima: `salva_dato` con `entita="persona"` scrive come ruolo Casa,
-- quindi già dichiarata. Estendere la vista significherebbe duplicarne la definizione qui, in un
-- file che gira DOPO `db/006` e che ne coprirebbe silenziosamente i futuri cambiamenti — un
-- secondo luogo in cui la stessa regola vive, che è il difetto che questo schema evita. Se un
-- flusso mediato per le persone arriverà (tipi `nuova_persona`/`modifica_persona`), la vista va
-- estesa lì, in `db/006`.
--
-- Idempotente: rieseguibile senza errori.
\set ON_ERROR_STOP on
\set VERBOSITY terse

SET ROLE trasi_owner;
SET search_path = trasi, public, pg_temp;

-- ---------------------------------------------------------------------------
-- Precondizioni
-- ---------------------------------------------------------------------------
DO $pre$
BEGIN
  IF to_regprocedure('trasi.casa_corrente()') IS NULL THEN
    RAISE EXCEPTION '029_persone_casa: manca trasi.casa_corrente() — applica prima db/002_rls.sql';
  END IF;
  IF to_regclass('trasi.v_kb_export') IS NULL THEN
    RAISE EXCEPTION '029_persone_casa: manca trasi.v_kb_export — applica prima db/004_views.sql';
  END IF;
END
$pre$;

-- ---------------------------------------------------------------------------
-- 1. La tabella
-- ---------------------------------------------------------------------------
-- Una riga per persona della Casa. `nome` è il nome come la persona vuole che sia citato («Maria
-- Rossi»), non un campo anagrafico separato: la KB lo riproduce così com'è.
CREATE TABLE IF NOT EXISTS trasi.persona_casa (
  id            serial PRIMARY KEY,
  casa_id       integer NOT NULL REFERENCES trasi.casa(id),
  nome          text NOT NULL CHECK (btrim(nome) <> '' AND char_length(btrim(nome)) <= 120),
  ruolo         text NOT NULL CHECK (btrim(ruolo) <> '' AND char_length(btrim(ruolo)) <= 80),
  competenze    text[] CHECK (competenze IS NULL OR cardinality(competenze) <= 10),
  -- Il consenso, come dati e non come interruttore. `consenso_il` NULL è lo stato normale di una
  -- persona appena inserita: **non** è in KB finché non arriva il consenso. `revoca_il` lo toglie.
  consenso_il   date,
  revoca_il     date,
  -- L'informativa: la decisione C la richiede («su dove il nome può comparire»). Il campo è il
  -- riferimento dichiarato dall'operatore (es. 'informativa v1 · 2026-09-17'), non il testo: quel
  -- documento è della Casa, non dello schema.
  informativa   text,
  attiva        boolean NOT NULL DEFAULT true,
  creato_ts     timestamptz NOT NULL DEFAULT now(),
  aggiornato_ts timestamptz,
  aggiornato_da text,

  -- Non si può revocare un consenso che non c'è mai stato, né revocare prima di concedere.
  CONSTRAINT persona_revoca_dopo_consenso
    CHECK (revoca_il IS NULL OR consenso_il IS NOT NULL),
  -- La revoca non può precedere il consenso che revoca: è un errore di battitura, non una scelta.
  CONSTRAINT persona_revoca_dopo_il_consenso
    CHECK (revoca_il IS NULL OR consenso_il IS NULL OR revoca_il >= consenso_il)
);

COMMENT ON TABLE trasi.persona_casa IS
  'Persone che lavorano e frequentano la Casa (foglio 1.1, gruppo Processi): nome, ruolo, competenze. '
  '**Il nome entra nella KB solo con consenso** (`consenso_il IS NOT NULL AND revoca_il IS NULL`): è '
  'la condizione della decisione del 2026-09-17, e `v_kb_export` la applica, non la dichiara. Nessun '
  'recapito: il filtro anti-PII rifiuta email e telefoni e non può distinguere uno di servizio da '
  'uno personale (lezione di db/025).';
COMMENT ON COLUMN trasi.persona_casa.nome IS
  'Nome come la persona vuole che sia citato in chat («Maria Rossi»), dal foglio 1.1 «Nome Cognome». '
  'Campo unico, deliberatamente: «cognome» è un nome di colonna che il presidio V5 del contratto vieta.';
COMMENT ON COLUMN trasi.persona_casa.consenso_il IS
  'Data in cui la persona ha acconsentito a comparire nella KB (e quindi in chat). NULL = nessun '
  'consenso: la persona resta nella scheda della Casa, e fuori dalla KB.';
COMMENT ON COLUMN trasi.persona_casa.revoca_il IS
  'Data della revoca. La persona esce da `v_kb_export` subito, e il flusso export la cancella da Onyx '
  '(B4-FLW-04). Il consenso revocabile in ogni momento è ciò che rende legittima la pubblicazione.';

CREATE INDEX IF NOT EXISTS persona_casa_casa_idx ON trasi.persona_casa (casa_id);
-- L'unico uso di questa tabella è «chi è in KB»: l'indice parziale serve a quella lettura.
CREATE INDEX IF NOT EXISTS persona_casa_in_kb_idx
  ON trasi.persona_casa (casa_id)
  WHERE consenso_il IS NOT NULL AND revoca_il IS NULL AND attiva;

-- ---------------------------------------------------------------------------
-- 2. RLS: chi legge, chi scrive
-- ---------------------------------------------------------------------------
ALTER TABLE trasi.persona_casa ENABLE ROW LEVEL SECURITY;
ALTER TABLE trasi.persona_casa FORCE  ROW LEVEL SECURITY;

DROP POLICY IF EXISTS owner_all ON trasi.persona_casa;
CREATE POLICY owner_all ON trasi.persona_casa FOR ALL TO trasi_owner USING (true) WITH CHECK (true);

-- `ti` amministra (matrice: ALL sul dominio). `applicatore` non scrive qui: non c'è flusso mediato.
DROP POLICY IF EXISTS pers_all_ti ON trasi.persona_casa;
CREATE POLICY pers_all_ti ON trasi.persona_casa FOR ALL TO ti USING (true) WITH CHECK (true);

-- La rete legge (T09: tutti leggono tutto, sono colleghi), ognuno scrive la propria.
DROP POLICY IF EXISTS pers_sel ON trasi.persona_casa;
CREATE POLICY pers_sel ON trasi.persona_casa FOR SELECT
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano, rete
  USING (true);

DROP POLICY IF EXISTS pers_ins_casa ON trasi.persona_casa;
CREATE POLICY pers_ins_casa ON trasi.persona_casa FOR INSERT
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano
  WITH CHECK (casa_id = casa_corrente());

DROP POLICY IF EXISTS pers_upd_casa ON trasi.persona_casa;
CREATE POLICY pers_upd_casa ON trasi.persona_casa FOR UPDATE
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano
  USING (casa_id = casa_corrente()) WITH CHECK (casa_id = casa_corrente());

-- Il DELETE è della Casa che la persona ha lasciato (diritto alla cancellazione, art. 17): una
-- scrittura della propria Casa come le altre. Una persona di un'altra Casa non si cancella.
DROP POLICY IF EXISTS pers_del_casa ON trasi.persona_casa;
CREATE POLICY pers_del_casa ON trasi.persona_casa FOR DELETE
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano
  USING (casa_id = casa_corrente());

-- `metabase_ro` non c'è, per la stessa ragione di `richiesta` (db/002): i nomi non sono un dato di
-- dashboard. La KB è il canale di pubblicazione, non il cruscotto. Né `automazioni` né `applicatore`:
-- l'export KB legge dalla vista (owner), e la persona non passa dal ciclo delle proposte.

-- ---------------------------------------------------------------------------
-- 3. GRANT
-- ---------------------------------------------------------------------------
GRANT SELECT ON trasi.persona_casa TO
  casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
  casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano, rete, ti,
  shim_rw;
GRANT INSERT, UPDATE, DELETE ON trasi.persona_casa TO
  casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
  casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano, ti;
GRANT USAGE ON SEQUENCE trasi.persona_casa_id_seq TO
  casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
  casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano, ti, shim_rw;
-- **La REVOKE è necessaria, non ridondante**: `db/002` ha `ALTER DEFAULT PRIVILEGES … GRANT SELECT ON
-- TABLES` per i ruoli di lettura, quindi una tabella nuova nasce leggibile da `metabase_ro`,
-- `automazioni` e `applicatore` **prima** che questo file dica la sua. Misurato sul DB condiviso dopo
-- la prima applicazione: `has_table_privilege('metabase_ro','trasi.persona_casa','SELECT') = true`
-- mentre il commento qui sopra diceva il contrario. La RLS (nessuna policy per quei ruoli → nessuna
-- riga) li teneva comunque fuori, ma un privilegio che il file nega e il catalogo concede è un
-- presidio di carta: si revoca e si verifica sotto.
REVOKE ALL ON trasi.persona_casa FROM metabase_ro, automazioni, applicatore;
REVOKE ALL ON SEQUENCE trasi.persona_casa_id_seq FROM metabase_ro, automazioni, applicatore;

-- ---------------------------------------------------------------------------
-- 3b. L'impronta di scrittura (stessa di luogo/scheda/casa)
-- ---------------------------------------------------------------------------
DROP TRIGGER IF EXISTS scrittura_00_ts ON trasi.persona_casa;
CREATE TRIGGER scrittura_00_ts BEFORE INSERT OR UPDATE ON trasi.persona_casa
  FOR EACH ROW EXECUTE FUNCTION trasi.scrittura_00_ts();

-- ---------------------------------------------------------------------------
-- 4. `v_kb_export` — le persone **con consenso** entrano nella KB
-- ---------------------------------------------------------------------------
-- La definizione è quella di `db/004_views.sql` con un ramo in più, **in coda**: le colonne esistenti
-- restano dove sono (l'export KB le legge per nome, ma un consumatore che legge per posizione non si
-- rompe). `CREATE OR REPLACE` e non DROP+CREATE: così i GRANT e `security_invoker = false` non
-- passano da una finestra in cui la vista non esiste (il flusso export notturno non trova la vista
-- e resta fermo senza che un log lo dica).
--
-- Il ramo è **gated sul consenso**, ed è questo il presidio, non un commento: una persona senza
-- `consenso_il` non produce riga in `v_kb_export`, quindi non raggiunge Onyx, quindi l'assistente
-- non può citarla — qualunque cosa dica un prompt. `attiva` e `revoca_il` sono la stessa clausola
-- nella pratica: «la persona è ancora qui e non ha ritirato il consenso».
CREATE OR REPLACE VIEW trasi.v_kb_export AS
SELECT 'trasi:luogo:' || l.id AS doc_id, 'luogo'::text AS entita, l.id,
       l.nome AS titolo,
       NULLIF(concat_ws(E'\n', l.nome || ' (' || l.tipo || ')', l.indirizzo,
                        trasi.orari_testo(l.orari), l.descrizione, l.note_accesso), '') AS testo,
       COALESCE(f.nome, 'rete') AS fonte_nome, COALESCE(l.url, f.url) AS url,
       l.data_aggiornamento, l.affidabilita, c.nome AS casa_nome
FROM trasi.luogo l
LEFT JOIN trasi.fonte f ON f.id = l.fonte_id
LEFT JOIN trasi.casa c ON c.id = l.casa_id
WHERE l.chiuso_il IS NULL
UNION ALL
SELECT 'trasi:casa_quartiere:' || c.id, 'casa_quartiere', c.id, c.nome,
       NULLIF(concat_ws(E'\n', c.nome || ' — Casa di Quartiere', c.zona, c.ente_gestore,
                        trasi.orari_testo(c.orari),
                        CASE WHEN c.orari_provvisori THEN 'orari in via di definizione' END), ''),
       COALESCE((SELECT f.nome FROM trasi.fonte f WHERE f.tipo_accesso = 'kb'
                 ORDER BY f.livello_fiducia DESC, f.id LIMIT 1), 'rete'),
       NULL, c.creato_ts::date, 3, c.nome
FROM trasi.casa c
UNION ALL
SELECT 'trasi:scheda_servizio:' || s.id, 'scheda_servizio', s.id, s.titolo,
       NULLIF(concat_ws(E'\n', s.titolo, s.descrizione, trasi.orari_testo(s.orari)), ''),
       COALESCE(f.nome, 'rete'), s.url, COALESCE(s.validata_il, s.creato_ts::date),
       COALESCE(s.affidabilita, 3), c.nome
FROM trasi.scheda_servizio s
JOIN trasi.casa c ON c.id = s.casa_id
LEFT JOIN trasi.fonte f ON f.id = s.fonte_id
WHERE s.scadenza IS NULL OR s.scadenza >= current_date
UNION ALL
SELECT 'trasi:evento:' || e.id, 'evento', e.id, e.titolo,
       NULLIF(concat_ws(E'\n', e.titolo,
                        to_char(e.inizio, 'DD/MM/YYYY HH24:MI')
                          || CASE WHEN e.fine IS NOT NULL THEN '–' || to_char(e.fine, 'HH24:MI') ELSE '' END,
                        e.luogo_testo, e.descrizione), ''),
       COALESCE(f.nome, 'calendario della Casa'), COALESCE(e.url, f.url),
       e.inizio::date, COALESCE(e.affidabilita, 2), c.nome
FROM trasi.evento e
JOIN trasi.casa c ON c.id = e.casa_id
LEFT JOIN trasi.fonte f ON f.id = e.fonte_id
WHERE e.annullato = false AND COALESCE(e.fine, e.inizio) >= now()
UNION ALL
SELECT 'trasi:opportunita:' || o.id, 'opportunita', o.id, o.titolo,
       NULLIF(concat_ws(E'\n', o.titolo,
                        CASE WHEN o.scadenza IS NOT NULL THEN 'scadenza ' || to_char(o.scadenza, 'DD/MM/YYYY') END,
                        o.descrizione), ''),
       COALESCE(f.nome, 'rete'), o.url, o.creato_ts::date, COALESCE(o.affidabilita, 3), c.nome
FROM trasi.opportunita o
JOIN trasi.casa c ON c.id = o.casa_id
LEFT JOIN trasi.fonte f ON f.id = o.fonte_id
WHERE o.scadenza IS NULL OR o.scadenza >= current_date
UNION ALL
SELECT 'trasi:persona:' || p.id, 'persona', p.id,
       p.nome || ' — ' || p.ruolo,
       NULLIF(concat_ws(E'\n',
                        p.nome || ', ' || p.ruolo || ' presso la Casa di Quartiere ' || c.nome,
                        CASE WHEN p.competenze IS NOT NULL AND cardinality(p.competenze) > 0
                             THEN 'Competenze: ' || array_to_string(p.competenze, ', ') END,
                        'Persona della rete, dato registrato dalla Casa con il consenso dell''interessata'),
              '') AS testo,
       c.nome AS fonte_nome, NULL AS url,
       COALESCE(p.aggiornato_ts, p.creato_ts)::date AS data_aggiornamento,
       3, c.nome
FROM trasi.persona_casa p
JOIN trasi.casa c ON c.id = p.casa_id
WHERE p.consenso_il IS NOT NULL AND p.revoca_il IS NULL AND p.attiva;

-- `security_invoker = false`: come le altre viste dell'export (la riga di `db/004` resta, e qui la
-- riaffermiamo perché il `CREATE OR REPLACE` sopra non tocca le reloptions — ma esplicito è meglio
-- che ereditato).
ALTER VIEW trasi.v_kb_export SET (security_invoker = false);

-- ---------------------------------------------------------------------------
-- 5. Verifica di installazione
-- ---------------------------------------------------------------------------
DO $verify$
DECLARE v_missing text; v_ente text; v_tutti text; v_n int;
BEGIN
  SELECT string_agg(c.conname, ', ') INTO v_missing FROM (VALUES
    ('persona_revoca_dopo_consenso'),('persona_revoca_dopo_il_consenso')
  ) AS c(conname)
  WHERE NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = c.conname);
  IF v_missing IS NOT NULL THEN
    RAISE EXCEPTION '029_persone_casa: CHECK mancanti: %', v_missing;
  END IF;

  -- La condizione che rende legittima la decisione C: il ramo `persona` di `v_kb_export` esiste ed è
  -- **condizionato al consenso**. Se qualcuno lo elimina o toglie il filtro, l'assistente pubblica
  -- nomi senza consenso — e questo test è il posto in cui accorgersene.
  IF position('trasi:persona:' in pg_get_viewdef('trasi.v_kb_export'::regclass, true)) = 0 THEN
    RAISE EXCEPTION '029_persone_casa: v_kb_export non contiene il ramo delle persone';
  END IF;
  IF position('p.consenso_il IS NOT NULL' in pg_get_viewdef('trasi.v_kb_export'::regclass, true)) = 0 THEN
    RAISE EXCEPTION '029_persone_casa: il ramo persona di v_kb_export non è filtrato per consenso';
  END IF;

  -- E tutti i rami ci sono ancora: una ricreazione che perdesse un ramo farà fallire l'export di
  -- quella entità in silenzio. Si asserisce sulla **definizione** e non sulle righe: un'entità può
  -- legittimamente avere 0 elementi validi (le sorelle hanno consumato le seed di prova), e contare
  -- le righe avrebbe dato un falso allarme già al primo giro.
  v_tutti := pg_get_viewdef('trasi.v_kb_export'::regclass, true);
  FOREACH v_ente IN ARRAY ARRAY['luogo','casa_quartiere','scheda_servizio','evento','opportunita','persona'] LOOP
    IF position('trasi:' || v_ente || ':' in v_tutti) = 0 THEN
      RAISE EXCEPTION '029_persone_casa: v_kb_export ha perso l''entita % (definizione incompleta)', v_ente;
    END IF;
  END LOOP;

  -- I ruoli che non devono leggere i nomi non hanno il privilegio — al catalogo, non nel commento.
  -- Il default privilege di db/002 lo riconcede a ogni tabella nuova: senza questa asserzione la
  -- REVOKE sopra potrebbe sparire in una riscrittura e nessun test se ne accorgerebbe (la RLS
  -- maschererebbe il sintomo).
  SELECT string_agg(r, ', ') INTO v_missing
  FROM unnest(ARRAY['metabase_ro','automazioni','applicatore']) AS r
  WHERE has_table_privilege(r, 'trasi.persona_casa', 'SELECT');
  IF v_missing IS NOT NULL THEN
    RAISE EXCEPTION '029_persone_casa: % legge trasi.persona_casa — i nomi non sono un dato di dashboard né di flusso', v_missing;
  END IF;

  SELECT count(*) INTO v_n FROM trasi.persona_casa;
  RAISE NOTICE '029_persone_casa applicato: persona_casa (nome, ruolo, competenze, consenso, revoca) · '
               'RLS FORCE · v_kb_export con le persone SOLO con consenso · % righe presenti', v_n;
END
$verify$;