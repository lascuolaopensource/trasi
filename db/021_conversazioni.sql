-- Trasi — db/021_conversazioni.sql
-- Storico delle conversazioni della chat (D5, §5.1 del piano): `conversazione` + `turno`.
--
-- Perché le tabelle stanno qui e non su Onyx (G-04, opzione A — decisione).
-- Oggi ogni messaggio apre una nuova sessione Onyx e Trasi non persiste nulla: la retention
-- nativa di Onyx esiste ma è **chiusa dal tier** (PATCH /api/admin/settings con
-- maximum_chat_retention_days → 402 FEATURE_NOT_AVAILABLE, «requires the Enterprise plan») e il
-- task `check-ttl-management` gira ogni ora senza cancellare niente perché la soglia è `None`.
-- Una UI che promette «le conversazioni restano 30 giorni» su una retention che non esiste è una
-- dichiarazione falsa. Qui la retention è una `DELETE` transazionale, governata da un parametro
-- `[P]`, e la visibilità è la stessa regola che il progetto usa ovunque: la RLS per Casa.
--
-- Perché NON è dominio (V4). `conversazione`/`turno` non passano dal flusso
-- proposta → approvazione → applicazione, come `messaggio` (db/015) e a differenza di
-- `luogo`/`scheda_servizio`/`evento`/`opportunita`/`casa`: non sono memoria della rete, sono lo
-- storico di un colloquio. Un turno non si «propone» e non si «approva»: si scrive e si legge.
-- Conseguenza dichiarata: queste due tabelle **non** entrano in `v_scritture_senza_audit` (che
-- contabilizza le mutazioni del dominio) e non hanno `aggiornato_ts`/`aggiornato_da`.
--
-- Vincoli applicati: RLS ENABLE+FORCE su entrambe; ogni policy con USING **e** WITH CHECK;
-- nessun UPDATE e nessun DELETE ai ruoli client (la conversazione si crea e si legge, e a
-- cancellarla è solo la retention); `titolo`, `ultimo_ts`, `scade_ts`, `ts` **fuori dai GRANT**
-- colonnari — li calcola il database, nessuno se li sceglie.
--
-- Idempotente: rieseguibile senza errori.
--
-- Due fasi, e la ragione è misurata. `ALTER FUNCTION … OWNER TO applicatore` richiede di poter
-- fare `SET ROLE applicatore`, e **`trasi_owner` non ne è membro** (`pg_has_role('trasi_owner',
-- 'applicatore','MEMBER')` = false): la prima stesura di questo file apriva con `SET ROLE
-- trasi_owner` come db/013–015 e falliva con `must be able to SET ROLE "applicatore"`. È la stessa
-- ragione per cui db/006 — l'unico altro file con funzioni di `applicatore` — **non** fa `SET ROLE`
-- e gira come amministratore. Qui servono entrambe le cose, quindi il file le fa in due fasi:
-- le funzioni prima (fase A, come db/006), le tabelle e le policy dopo (fase B, come db/015).
\set ON_ERROR_STOP on
\set VERBOSITY terse

-- ---------------------------------------------------------------------------
-- A. Le funzioni — owner `applicatore` (fase dell'amministratore, come db/006)
--    Prima delle tabelle perché la fase B non può creare oggetti di `applicatore`; i corpi
--    plpgsql non risolvono gli oggetti alla creazione, quindi l'ordine è lecito.
-- ---------------------------------------------------------------------------
-- A1. Il trigger che calcola ciò che nessuno si sceglie.
--     Perché un trigger e non due statement del chiamante: il piano vieta l'UPDATE al browser
--     («una conversazione non si modifica, si crea e si legge»), quindi i ruoli Casa **non hanno**
--     il GRANT UPDATE su `conversazione` — e un `UPDATE` dal loro codice darebbe 42501. L'unico
--     modo di tenere `titolo`/`ultimo_ts`/`scade_ts` veri è calcolarli qui, dove il ruolo è
--     `applicatore` (SECURITY DEFINER, owner applicatore, search_path fissato).
CREATE OR REPLACE FUNCTION trasi.turno_00_conversazione_tg() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = trasi, public, pg_catalog
AS $fn$
BEGIN
  UPDATE trasi.conversazione c
     SET ultimo_ts = NEW.ts,
         -- Il rinnovo è sull'ULTIMO turno, non sulla creazione: una conversazione viva non scade
         -- mentre l'operatore la usa, e il piede dello storico («le conversazioni restano 30
         -- giorni») resta vero anche per una conversazione cominciata 29 giorni fa.
         scade_ts  = NEW.ts + make_interval(days => COALESCE(trasi.p_int('gg_retention_chat'), 30)),
         -- Il titolo è la **prima domanda** troncata a 40 caratteri (§5.1), e per questo lo scrive
         -- solo il turno dell'operatore: un titolo preso dalla prima risposta generata sarebbe
         -- un'etichetta che non dice cosa si è chiesto. La condizione guarda `titolo = ''` e non
         -- l'ordine, così l'intitolazione avviene alla prima domanda **ovunque essa cada** — nel
         -- percorso reale è sempre il primo turno (S1: il turno OPERATORE entra subito, la
         -- risposta arriva dopo), ma la regola non dipende da quell'ordine.
         titolo    = CASE WHEN c.titolo = '' AND NEW.ruolo = 'operatore'
                          THEN left(NEW.testo, 40) ELSE c.titolo END
   WHERE c.id = NEW.conversazione_id;
  RETURN NULL;   -- AFTER trigger: il valore di ritorno non si usa
END;
$fn$;
ALTER FUNCTION trasi.turno_00_conversazione_tg() OWNER TO applicatore;

-- A2. Retention — `scadi_conversazioni()`
--     SECURITY DEFINER owner `applicatore`: la cancellazione è della funzione, non del chiamante.
--     Il passo notturno la invoca come `automazioni`, che è lo stesso ruolo con cui
--     `flussi/notte.sh` invoca già `scadi_messaggi()`.
--
--     Cosa cancella: le conversazioni con `scade_ts < now()`, e con esse i loro turni (cascade).
--     Cosa NON tocca: Onyx. La sessione su Onyx e la sua retention sono due cose diverse, e il
--     piano non le confonde — `ops/retention_chat.py` resta l'unico che parla a Onyx.
--
--     Nota dichiarata: `scade_ts` è la scadenza **scritta**, quindi abbassare `gg_retention_chat`
--     non accorcia retroattivamente le conversazioni già esistenti (mantengono la scadenza che
--     avevano al momento dell'ultimo turno). È il comportamento del DDL prescritto in §5.1, che
--     vuole `scade_ts` come colonna: la scadenza memorizzata è ispezionabile prima di essere
--     applicata, e un cambio di parametro non cancella di colpo uno storico che qualcuno stava
--     leggendo.
CREATE OR REPLACE FUNCTION trasi.scadi_conversazioni()
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = trasi, public, pg_catalog
AS $fn$
DECLARE
  v_n int;
BEGIN
  DELETE FROM trasi.conversazione c WHERE c.scade_ts < now();
  GET DIAGNOSTICS v_n = ROW_COUNT;
  RETURN v_n;
END;
$fn$;

ALTER FUNCTION trasi.scadi_conversazioni() OWNER TO applicatore;
REVOKE ALL ON FUNCTION trasi.scadi_conversazioni() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION trasi.scadi_conversazioni() TO automazioni, ti;

-- ---------------------------------------------------------------------------
-- B. Tabelle, RLS, GRANT (fase dell'owner, come db/015)
-- ---------------------------------------------------------------------------
SET ROLE trasi_owner;
SET search_path = trasi, public, pg_temp;

-- ---------------------------------------------------------------------------
-- 1. conversazione
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trasi.conversazione (
  id              bigserial PRIMARY KEY,
  casa_id         integer NOT NULL REFERENCES trasi.casa(id),
  -- `titolo` = la prima domanda troncata a 40 caratteri. Nasce VUOTO e lo riempie il trigger
  -- `turno_00_conversazione_tg` dal primo turno: il client non ha il GRANT sulla colonna, quindi
  -- nessuno può intitolare una conversazione con un testo che non è la sua prima domanda.
  titolo          text    NOT NULL DEFAULT '' CHECK (char_length(titolo) <= 40),
  onyx_session_id text,                      -- la sessione Onyx riusata per tutta la conversazione
  creato_ts       timestamptz NOT NULL DEFAULT now(),
  ultimo_ts       timestamptz NOT NULL DEFAULT now(),
  -- La scadenza la decide il parametro [P] `gg_retention_chat`, letta a ogni scrittura: cambiarla
  -- non richiede un deploy. È la stessa scadenza che la riga di piede dello storico dichiara
  -- all'operatore («le conversazioni restano 30 giorni»).
  scade_ts        timestamptz NOT NULL DEFAULT now()
                  + make_interval(days => COALESCE(trasi.p_int('gg_retention_chat'), 30))
);
COMMENT ON TABLE trasi.conversazione IS
  'Storico della chat per Casa (D5, §5.1): titolo = prima domanda troncata a 40 caratteri, scade_ts = ultimo turno + [P] gg_retention_chat (30). Non è dominio (V4): si crea e si legge, non si propone. Cancellata solo da scadi_conversazioni().';
COMMENT ON COLUMN trasi.conversazione.casa_id IS
  'Casa della sessione (trasi.casa_corrente()): la Casa non arriva mai dal corpo di una richiesta (Principio 3).';
COMMENT ON COLUMN trasi.conversazione.titolo IS
  'Prima domanda troncata a 40 caratteri, scritta dal trigger dal primo turno. Fuori dai GRANT: nessuno se la sceglie.';
COMMENT ON COLUMN trasi.conversazione.scade_ts IS
  'Scadenza della retention: rinnovata dal trigger a ogni turno (ultimo_ts + [P] gg_retention_chat).';
COMMENT ON COLUMN trasi.conversazione.onyx_session_id IS
  'Sessione Onyx riusata per la conversazione (G-03): è ciò che rende multi-turno la chat. Non modificabile dopo la creazione.';

CREATE INDEX IF NOT EXISTS conversazione_casa_ultimo_idx ON trasi.conversazione (casa_id, ultimo_ts DESC);
CREATE INDEX IF NOT EXISTS conversazione_scade_idx       ON trasi.conversazione (scade_ts);

-- ---------------------------------------------------------------------------
-- 2. turno
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trasi.turno (
  id               bigserial PRIMARY KEY,
  -- ON DELETE CASCADE: cancellare la conversazione cancella i turni. È l'unico DELETE ammesso
  -- sulla chat, e viene dalla retention — non da un client.
  conversazione_id bigint NOT NULL REFERENCES trasi.conversazione(id) ON DELETE CASCADE,
  ruolo            text   NOT NULL CHECK (ruolo IN ('operatore','assistente')),
  -- Il tetto di 2000 caratteri vale **solo per la domanda dell'operatore**, ed è lo stesso di
  -- `MessaggioIn.messaggio` (shim/app/chat.py:136). La risposta dell'assistente è **generata**:
  -- non ha un tetto a monte, e metterglielo qui sarebbe una costante inventata che trasforma una
  -- risposta lunga in un `23514` — cioè la chat che smette di funzionare perché il modello ha
  -- scritto troppo. Il DDL di §5.1 non ha alcun CHECK sul testo: questo lo restringe solo dove il
  -- tetto esiste davvero, e lascia all'assistente il solo vincolo che ha senso (non vuoto).
  testo            text   NOT NULL CONSTRAINT turno_testo_check CHECK (
                     char_length(testo) >= 1
                     AND (ruolo <> 'operatore' OR char_length(testo) <= 2000)),
  fonte            text,                     -- il badge dello shim, verbatim (NULL sull'astensione)
  riferimenti      jsonb,                    -- [{tipo,id,nome}] dai top_documents
  onyx_message_id  bigint,                   -- parent_message_id del turno successivo
  ts               timestamptz NOT NULL DEFAULT now()
);
-- Il vincolo sul testo va riaffermato **esplicitamente**, e non è una ridondanza.
-- `CREATE TABLE IF NOT EXISTS` **non** tocca una tabella che esiste: su ogni database dove `turno`
-- era già stata creata, il CHECK scritto nella definizione qui sopra non verrebbe mai applicato, e
-- la tabella resterebbe senza vincolo mentre il sorgente sembra corretto. Misurato: dopo la prima
-- stesura di questo file (CHECK incondizionato `BETWEEN 1 AND 2000`) un `DROP CONSTRAINT` ha tolto
-- il vecchio vincolo e `CREATE TABLE IF NOT EXISTS` non ha aggiunto il nuovo — `testo` è rimasto
-- **senza alcun CHECK**, e il test C10 lo ha rilevato (una domanda di 2001 caratteri è passata).
-- È la differenza fra «il sorgente è giusto» e «il database è giusto», e conta la seconda.
-- (Stesso presidio di db/015:23 per `messaggio_direzione_ck`, al contrario.)
--
-- Si riafferma solo se la definizione **differisce**: un `DROP`+`ADD` a ogni esecuzione farebbe una
-- scansione di validazione dell'intera tabella a ogni apply, che su una tabella che cresce è un
-- costo che non serve — e l'apply è idempotente per contratto.
DO $ck$
DECLARE
  v_def text;
BEGIN
  SELECT pg_get_constraintdef(oid) INTO v_def FROM pg_constraint
   WHERE conrelid = 'trasi.turno'::regclass AND conname = 'turno_testo_check';
  IF v_def IS NULL
     OR v_def !~ 'ruolo' THEN        -- il vincolo giusto nomina il ruolo; quello vecchio no
    ALTER TABLE trasi.turno DROP CONSTRAINT IF EXISTS turno_testo_check;
    ALTER TABLE trasi.turno ADD CONSTRAINT turno_testo_check CHECK (
      char_length(testo) >= 1
      AND (ruolo <> 'operatore' OR char_length(testo) <= 2000));
  END IF;
END
$ck$;
COMMENT ON TABLE trasi.turno IS
  'Turni della conversazione (operatore | assistente): si scrivono e si leggono, non si modificano né si cancellano dai client. Il turno sparisce solo con la conversazione (cascade).';
COMMENT ON COLUMN trasi.turno.ruolo IS
  'Vocabolario chiuso: operatore (la domanda allo sportello) | assistente (la risposta).';
COMMENT ON COLUMN trasi.turno.testo IS
  'Unico contenuto libero. Domanda dell''operatore ≤ 2000 caratteri (stesso tetto di MessaggioIn); la risposta dell''assistente è generata e non ha tetto. Il testo arriva già filtrato dall''anti-PII a monte (shim/app/pii.py): un 422 non scrive nessun turno (§4.1.3).';
COMMENT ON COLUMN trasi.turno.fonte IS
  'L''etichetta di provenienza dello shim, **verbatim** (V3). NULL sull''astensione: senza fonte non si inventa un''etichetta.';
COMMENT ON COLUMN trasi.turno.riferimenti IS
  'Riferimenti del turno [{tipo,id,nome}] estratti dai top_documents di Onyx; NULL se il turno non ne ha (le azioni sulla risposta non si mostrano).';
COMMENT ON COLUMN trasi.turno.onyx_message_id IS
  'message_id Onyx del turno: è il parent_message_id del turno successivo (G-03).';

CREATE INDEX IF NOT EXISTS turno_conversazione_idx ON trasi.turno (conversazione_id, ts);

-- ---------------------------------------------------------------------------
-- 3. Il trigger sulla tabella (la funzione è definita in fase A)
-- ---------------------------------------------------------------------------
DROP TRIGGER IF EXISTS turno_00_conversazione_tg ON trasi.turno;
CREATE TRIGGER turno_00_conversazione_tg AFTER INSERT ON trasi.turno
  FOR EACH ROW EXECUTE FUNCTION trasi.turno_00_conversazione_tg();

-- ---------------------------------------------------------------------------
-- 4. RLS — ENABLE + FORCE su entrambe
-- ---------------------------------------------------------------------------
ALTER TABLE trasi.conversazione ENABLE ROW LEVEL SECURITY;
ALTER TABLE trasi.conversazione FORCE  ROW LEVEL SECURITY;
ALTER TABLE trasi.turno        ENABLE ROW LEVEL SECURITY;
ALTER TABLE trasi.turno        FORCE  ROW LEVEL SECURITY;

DROP POLICY IF EXISTS owner_all ON trasi.conversazione;
CREATE POLICY owner_all ON trasi.conversazione FOR ALL TO trasi_owner USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS appl_all ON trasi.conversazione;
CREATE POLICY appl_all ON trasi.conversazione FOR ALL TO applicatore USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS owner_all ON trasi.turno;
CREATE POLICY owner_all ON trasi.turno FOR ALL TO trasi_owner USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS appl_all ON trasi.turno;
CREATE POLICY appl_all ON trasi.turno FOR ALL TO applicatore USING (true) WITH CHECK (true);

-- Lettura della propria Casa. `casa_corrente()` deriva da `current_user` via `ruolo_casa`
-- (db/001:248) e **non** da una GUC: NocoDB si connette col ruolo diretto, e una GUC sarebbe
-- spoofabile (T13 di t_rls.sql lo prova).
DROP POLICY IF EXISTS conv_sel_casa ON trasi.conversazione;
CREATE POLICY conv_sel_casa ON trasi.conversazione FOR SELECT
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano, shim_rw
  USING (casa_id = (SELECT trasi.casa_corrente()));

-- `rete` e `ti` leggono tutto: sono il territorio e il TI, non una Casa. Stanno in una policy
-- **separata** e non nella stessa riga, ed è una scelta: `casa_corrente()` è NULL per entrambi
-- (nessuna riga in `ruolo_casa`, verificato), quindi metterli in `conv_sel_casa` avrebbe dato
-- loro zero righe — una policy che sembra un permesso e in realtà è un divieto silenzioso.
-- La lettura larga è coerente con `msg_sel` di db/015, che ammette `rete`/`ti` su tutta la chat.
DROP POLICY IF EXISTS conv_sel_rete ON trasi.conversazione;
CREATE POLICY conv_sel_rete ON trasi.conversazione FOR SELECT TO rete, ti USING (true);

-- Inserimento: con la Casa del **proprio** ruolo. WITH CHECK, non solo USING: senza, un ruolo
-- Casa potrebbe creare una conversazione a nome di un'altra (Principio 3).
DROP POLICY IF EXISTS conv_ins_casa ON trasi.conversazione;
CREATE POLICY conv_ins_casa ON trasi.conversazione FOR INSERT
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano
  WITH CHECK (casa_id = (SELECT trasi.casa_corrente()));

-- Nessuna policy UPDATE: la conversazione non si modifica (il rinnovo lo fa il trigger, che gira
-- come `applicatore`). Nessuna policy DELETE: la retention è `scadi_conversazioni()`.

-- --- turno: la visibilità segue la conversazione -------------------------------------------
DROP POLICY IF EXISTS turno_sel_casa ON trasi.turno;
CREATE POLICY turno_sel_casa ON trasi.turno FOR SELECT
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano, shim_rw
  USING (EXISTS (SELECT 1 FROM trasi.conversazione c
                  WHERE c.id = conversazione_id
                    AND c.casa_id = (SELECT trasi.casa_corrente())));

DROP POLICY IF EXISTS turno_sel_rete ON trasi.turno;
CREATE POLICY turno_sel_rete ON trasi.turno FOR SELECT TO rete, ti USING (true);

-- Il turno si inserisce solo in una conversazione della propria Casa: è qui che un `POST` su una
-- conversazione altrui diventa `42501 new row violates row-level security policy` — lo shim lo
-- mappa su **404** e non su 403, che rivelerebbe l'esistenza della conversazione (§5.1).
DROP POLICY IF EXISTS turno_ins_casa ON trasi.turno;
CREATE POLICY turno_ins_casa ON trasi.turno FOR INSERT
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano
  WITH CHECK (EXISTS (SELECT 1 FROM trasi.conversazione c
                       WHERE c.id = conversazione_id
                         AND c.casa_id = (SELECT trasi.casa_corrente())));

-- Nessuna policy UPDATE/DELETE su `turno`: un turno è un registro, non una lavagna.

-- ---------------------------------------------------------------------------
-- 5. GRANT colonnari — il minimo che serve alla chat
-- ---------------------------------------------------------------------------
REVOKE ALL ON trasi.conversazione FROM PUBLIC;
REVOKE ALL ON trasi.turno        FROM PUBLIC;

GRANT SELECT ON trasi.conversazione
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano,
     rete, ti, shim_rw, applicatore;
-- `titolo`, `scade_ts` e i timestamp NON sono inseribili: li calcola il database (default + trigger).
GRANT INSERT (casa_id, onyx_session_id) ON trasi.conversazione
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano;

GRANT SELECT ON trasi.turno
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano,
     rete, ti, shim_rw, applicatore;
-- `ts` fuori dal GRANT, come in db/015: un client non si sceglie quando un turno è stato scritto.
GRANT INSERT (conversazione_id, ruolo, testo, fonte, riferimenti, onyx_message_id) ON trasi.turno
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano;

GRANT SELECT, INSERT, UPDATE, DELETE ON trasi.conversazione TO trasi_owner;
GRANT SELECT, INSERT, UPDATE, DELETE ON trasi.conversazione TO applicatore;
GRANT SELECT, INSERT, UPDATE, DELETE ON trasi.turno        TO trasi_owner;
GRANT SELECT, INSERT, UPDATE, DELETE ON trasi.turno        TO applicatore;

GRANT USAGE ON SEQUENCE trasi.conversazione_id_seq
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano, applicatore;
GRANT USAGE ON SEQUENCE trasi.turno_id_seq
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
     casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano, applicatore;

-- ---------------------------------------------------------------------------
-- 6. La retention è definita in fase A (`scadi_conversazioni()`, owner `applicatore`)
-- ---------------------------------------------------------------------------

-- ---------------------------------------------------------------------------
-- 7. Verifica di installazione
-- ---------------------------------------------------------------------------
DO $verify$
DECLARE
  v_n int;
  v_owner text;
BEGIN
  IF EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
              WHERE n.nspname = 'trasi' AND c.relname IN ('conversazione','turno')
                AND NOT (c.relrowsecurity AND c.relforcerowsecurity)) THEN
    RAISE EXCEPTION '021: conversazione/turno senza ENABLE+FORCE RLS';
  END IF;

  SELECT count(*) INTO v_n FROM pg_policies
   WHERE schemaname = 'trasi' AND tablename = 'conversazione'
     AND policyname IN ('conv_sel_casa','conv_sel_rete','conv_ins_casa');
  IF v_n <> 3 THEN
    RAISE EXCEPTION '021: attese 3 policy client su conversazione, trovate %', v_n;
  END IF;

  SELECT count(*) INTO v_n FROM pg_policies
   WHERE schemaname = 'trasi' AND tablename = 'turno'
     AND policyname IN ('turno_sel_casa','turno_sel_rete','turno_ins_casa');
  IF v_n <> 3 THEN
    RAISE EXCEPTION '021: attese 3 policy client su turno, trovate %', v_n;
  END IF;

  -- La regola che rende la RLS l'autorità: nessuna policy senza WITH CHECK.
  SELECT string_agg(tablename || '.' || policyname, ', ') INTO v_owner
    FROM pg_policies
   WHERE schemaname = 'trasi' AND tablename IN ('conversazione','turno')
     AND cmd IN ('ALL','INSERT','UPDATE') AND with_check IS NULL;
  IF v_owner IS NOT NULL THEN
    RAISE EXCEPTION '021: policy senza WITH CHECK: %', v_owner;
  END IF;

  -- Cascade: senza, la retention lascerebbe turni orfani (o non cancellerebbe affatto).
  IF NOT EXISTS (SELECT 1 FROM pg_constraint con JOIN pg_class c ON c.oid = con.conrelid
                  WHERE con.conrelid = 'trasi.turno'::regclass AND con.confrelid = 'trasi.conversazione'::regclass
                    AND con.contype = 'f' AND con.confdeltype = 'c') THEN
    RAISE EXCEPTION '021: manca la FK turno → conversazione con ON DELETE CASCADE';
  END IF;

  SELECT pg_get_userbyid(proowner) INTO v_owner FROM pg_proc
   WHERE oid = 'trasi.scadi_conversazioni()'::regprocedure;
  IF v_owner <> 'applicatore' THEN
    RAISE EXCEPTION '021: scadi_conversazioni ha owner % invece di applicatore', v_owner;
  END IF;
  IF NOT (SELECT prosecdef FROM pg_proc WHERE oid = 'trasi.scadi_conversazioni()'::regprocedure) THEN
    RAISE EXCEPTION '021: scadi_conversazioni non è SECURITY DEFINER';
  END IF;

  RAISE NOTICE '021_conversazioni applicato: conversazione + turno, RLS ENABLE+FORCE, 6 policy client con WITH CHECK, nessun UPDATE/DELETE ai client, titolo/ultimo_ts/scade_ts calcolati dal trigger, scadi_conversazioni() (owner applicatore, retention [P] gg_retention_chat)';
END
$verify$;

RESET ROLE;
