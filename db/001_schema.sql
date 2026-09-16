-- Trasi — db/001_schema.sql
-- Strato dati, schema `trasi` (owner trasi_owner).
--   Parte A  dominio + configurazione + identità
--   Parte B  proposta/audit + approvatore_default() + casa_corrente() + trigger proposta_00_default_tg
--
-- Fonti: docs/trasi-architecture-v1.2.md §7 (ER) e §7.1 (DDL verbatim per proposta/audit/funzioni).
-- [ASSUNZIONE] Il DDL v1.1 non esiste nel repo: le colonne non elencate in §7/§7.1 sono ricostruite
-- dall'ER §7 e dai contratti dei consumatori (shim/openapi.yaml, plan.md B1-DAT-02/03/10/12). Le scelte
-- non ovvie sono commentate qui e dichiarate nel report B1.
--
-- V4: il dominio (casa, luogo, scheda_servizio, evento, opportunita) non è scrivibile dalle identità
--     applicative salvo l'eccezione iCal su evento (§8 F4) e i casi ammessi dal plan (principio 3).
-- V5/§12: nessun campo per dati personali; `motivazione` ≤ 80 caratteri.
-- Idempotente: rieseguibile senza errori.
\set ON_ERROR_STOP on
\set VERBOSITY terse

SET ROLE trasi_owner;
SET search_path = trasi, public, pg_temp;

-- ===========================================================================
-- A. Tabelle
-- ===========================================================================

-- Le 10 Case di Quartiere -----------------------------------------------------
CREATE TABLE IF NOT EXISTS trasi.casa (
  id                serial PRIMARY KEY,
  slug              text NOT NULL UNIQUE,
  nome              text NOT NULL,
  zona              text,
  ente_gestore      text,
  orari             jsonb,                       -- {lun..dom: ["HH:MM","HH:MM",…]} ; [] = chiuso
  orari_eccezioni   jsonb,                       -- [{tipo: stagionale|evento|chiusura, dal, al, orari, nota}]
  orari_provvisori  boolean NOT NULL DEFAULT false,
  raggio_m          integer CHECK (raggio_m IS NULL OR raggio_m > 0),
  geom              geography(Point,4326),
  geom_qualita      text NOT NULL DEFAULT 'stimata' CHECK (geom_qualita IN ('verificata','stimata')),
  email_digest      text,
  da_validare       boolean NOT NULL DEFAULT false,
  persone_target    text[],
  competenze        text[],
  note              text,
  creato_ts         timestamptz NOT NULL DEFAULT now()
);
COMMENT ON COLUMN trasi.casa.raggio_m IS 'Raggio di vicinanza della Casa in metri; NULL = usa il parametro [P] raggio_vicinanza_m.';
COMMENT ON COLUMN trasi.casa.geom_qualita IS 'verificata = coordinata con riscontro civico; stimata = punto ricostruito (obbligatorio per Tuturano, plan §7).';
COMMENT ON COLUMN trasi.casa.orari_eccezioni IS 'Precedenza: chiusura > evento > stagionale > orari regolari (plan B1, specifiche di riferimento).';

-- Allow-list delle fonti ------------------------------------------------------
CREATE TABLE IF NOT EXISTS trasi.fonte (
  id                serial PRIMARY KEY,
  nome              text NOT NULL UNIQUE,
  url               text,
  tipo_accesso      text NOT NULL CHECK (tipo_accesso IN ('kb','drive','ical','http','osm_overpass','web','api')),
  autorita          text,
  livello_fiducia   smallint NOT NULL CHECK (livello_fiducia BETWEEN 1 AND 3),
  attiva            boolean NOT NULL DEFAULT true,
  ultima_variazione timestamptz,
  creato_ts         timestamptz NOT NULL DEFAULT now()
);

-- Esiti dei run di ingestione (F4) -------------------------------------------
CREATE TABLE IF NOT EXISTS trasi.fonte_run (
  id          bigserial PRIMARY KEY,
  fonte_id    integer NOT NULL REFERENCES trasi.fonte(id),
  ts          timestamptz NOT NULL DEFAULT now(),
  esito       text NOT NULL CHECK (esito IN ('ok','anomalo','errore')),
  righe       integer,
  hash        text,
  dettaglio   jsonb,
  eseguito_da text
);

-- Memoria dei luoghi ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS trasi.luogo (
  id                  serial PRIMARY KEY,
  nome                text NOT NULL,
  tipo                text NOT NULL CHECK (tipo IN ('bar','farmacia','caf','fermata','poste','asl','comune','inps',
                                                    'questura','sportello','presidio_ascolto','servizio_professionale',
                                                    'casa_quartiere','associazione','altro')),
  descrizione         text,
  indirizzo           text,
  geom                geography(Point,4326),
  orari               jsonb,
  note_accesso        text,
  chiuso_il           date,
  ext_ref             text UNIQUE,
  url                 text,
  casa_id             integer REFERENCES trasi.casa(id),
  fonte_id            integer NOT NULL REFERENCES trasi.fonte(id),
  affidabilita        smallint NOT NULL CHECK (affidabilita BETWEEN 1 AND 3),
  data_aggiornamento  date,
  creato_ts           timestamptz NOT NULL DEFAULT now()
);
COMMENT ON COLUMN trasi.luogo.ext_ref IS 'Riferimento esterno stabile (es. osm:node/123); UNIQUE quando presente, NULL per i luoghi della rete.';
COMMENT ON COLUMN trasi.luogo.chiuso_il IS 'Soft-close: un luogo chiuso resta in tabella ed esce dalle viste valide (mai DELETE).';

-- Schede di servizio ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS trasi.scheda_servizio (
  id            serial PRIMARY KEY,
  casa_id       integer NOT NULL REFERENCES trasi.casa(id),
  titolo        text NOT NULL,
  descrizione   text,
  categoria     text,
  orari         jsonb,
  referente_ruolo text,
  scadenza      date,
  validata_il   date,
  url           text,
  fonte_id      integer REFERENCES trasi.fonte(id),
  affidabilita  smallint CHECK (affidabilita BETWEEN 1 AND 3),
  creato_ts     timestamptz NOT NULL DEFAULT now()
);

-- Eventi ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trasi.evento (
  id           serial PRIMARY KEY,
  casa_id      integer NOT NULL REFERENCES trasi.casa(id),
  titolo       text NOT NULL,
  descrizione  text,
  inizio       timestamptz NOT NULL,
  fine         timestamptz,
  luogo_testo  text,
  uid_ical     text,
  url          text,
  annullato    boolean NOT NULL DEFAULT false,
  fonte_id     integer REFERENCES trasi.fonte(id),
  affidabilita smallint CHECK (affidabilita BETWEEN 1 AND 3),
  creato_ts    timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT evento_casa_uid_ical_uq UNIQUE (casa_id, uid_ical),
  CONSTRAINT evento_fine_dopo_inizio CHECK (fine IS NULL OR fine >= inizio)
);
COMMENT ON COLUMN trasi.evento.uid_ical IS 'Chiave del feed iCal: UNIQUE(casa_id, uid_ical) rende l''upsert F4 idempotente. NULL per gli eventi inseriti a mano.';
COMMENT ON COLUMN trasi.evento.annullato IS 'Annullamento soft: il flusso iCal non fa mai DELETE (§8 F4).';

-- Opportunità (bandi, iniziative con scadenza) --------------------------------
CREATE TABLE IF NOT EXISTS trasi.opportunita (
  id           serial PRIMARY KEY,
  casa_id      integer NOT NULL REFERENCES trasi.casa(id),
  titolo       text NOT NULL,
  descrizione  text,
  categoria    text,
  scadenza     date,
  url          text,
  fonte_id     integer REFERENCES trasi.fonte(id),
  affidabilita smallint CHECK (affidabilita BETWEEN 1 AND 3),
  creato_ts    timestamptz NOT NULL DEFAULT now()
);

-- Richieste di orientamento (V5: nessun campo per il cittadino) ---------------
CREATE TABLE IF NOT EXISTS trasi.richiesta (
  id                bigserial PRIMARY KEY,
  casa_id           integer NOT NULL REFERENCES trasi.casa(id),
  ts                timestamptz NOT NULL DEFAULT now(),
  categoria         text NOT NULL CHECK (categoria IN ('orientamento','servizi_sociali','fiscale_isee','lavoro','abitare',
                                                       'salute','interculturale','ascolto_solitudine','eventi_attivita','altro')),
  esito             text NOT NULL CHECK (esito IN ('risolta','inviata_altrove','non_trovata','rinviata')),
  destinazione_id   integer REFERENCES trasi.luogo(id),
  destinazione_nota text,
  CONSTRAINT richiesta_destinazione_obbl CHECK (esito <> 'inviata_altrove'
                                               OR destinazione_id IS NOT NULL
                                               OR destinazione_nota IS NOT NULL)
);
COMMENT ON TABLE trasi.richiesta IS 'Categoria, esito e destinazione del colloquio. Nessun campo per dati personali (plan §12): niente nome, contatti, testo libero del cittadino.';

-- Parametri [P] ---------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trasi.parametro (
  chiave        text PRIMARY KEY,
  valore        text NOT NULL,
  tipo          text NOT NULL CHECK (tipo IN ('int','text','bool')),
  descrizione   text,
  modificato_da text,
  modificato_ts timestamptz,
  creato_ts     timestamptz NOT NULL DEFAULT now()
);

-- Mappa ruolo DB → Casa (§11: un ruolo per Casa) ------------------------------
CREATE TABLE IF NOT EXISTS trasi.ruolo_casa (
  ruolo       text PRIMARY KEY,
  casa_id     integer REFERENCES trasi.casa(id),   -- NULL per rete (AT/AQ) e ti
  descrizione text
);

-- Identità Onyx → ruolo DB ----------------------------------------------------
CREATE TABLE IF NOT EXISTS trasi.identita_onyx (
  id         serial PRIMARY KEY,
  email      text NOT NULL UNIQUE,
  ruolo_db   text NOT NULL REFERENCES trasi.ruolo_casa(ruolo),
  casa_id    integer REFERENCES trasi.casa(id),
  attiva     boolean NOT NULL DEFAULT true,
  creato_ts  timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE trasi.identita_onyx IS 'Email di servizio → ruolo DB. La FK su ruolo_casa impedisce identità orfane; l''operatore non è mai nominativo.';

-- ===========================================================================
-- B. Proposta e audit (architettura §7.1, verbatim salvo i commenti)
-- ===========================================================================

DO $$ BEGIN
  CREATE TYPE trasi.stato_prop_t AS ENUM ('proposta','approvata','rifiutata','applicata','scaduta');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS trasi.proposta (
  id                bigserial PRIMARY KEY,
  origine           text NOT NULL CHECK (origine IN ('chat','fonte_automatica','ricerca_esterna','coerenza','manuale')),
  tipo              text NOT NULL CHECK (tipo IN ('nuovo_luogo','modifica_luogo','chiudi_luogo','modifica_scheda','nuova_scheda',
                                                  'modifica_evento','nuova_opportunita','promuovi_esterno','modifica_orari_casa')),
  entita            text NOT NULL,
  entita_id         integer,
  casa_id           integer REFERENCES trasi.casa(id),     -- NULL = territorio / rete
  fonte_id          integer REFERENCES trasi.fonte(id),
  payload           jsonb NOT NULL,
  diff              jsonb,
  motivazione       text CHECK (motivazione IS NULL OR char_length(motivazione) <= 80),   -- V5/§12
  stato             trasi.stato_prop_t NOT NULL DEFAULT 'proposta',
  approvatore_ruolo text NOT NULL CHECK (approvatore_ruolo IN ('gestore','at','ti')),
  proposto_da       text,
  proposto_ts       timestamptz DEFAULT now(),
  approvato_da      text,
  approvato_ts      timestamptz,
  scade_il          date DEFAULT current_date + 30
);

CREATE TABLE IF NOT EXISTS trasi.audit (
  id          bigserial PRIMARY KEY,
  proposta_id bigint REFERENCES trasi.proposta(id),
  ts          timestamptz DEFAULT now(),
  azione      text NOT NULL,
  eseguito_da text NOT NULL,
  prima       jsonb,
  dopo        jsonb
);

-- Regola approvatore (dato, non hardcoded nei flussi) -------------------------
CREATE OR REPLACE FUNCTION trasi.approvatore_default(p_tipo text, p_casa integer) RETURNS text
LANGUAGE sql STABLE SET search_path = '' AS $$
  SELECT CASE WHEN p_casa IS NOT NULL AND p_tipo IN ('modifica_scheda','nuova_scheda','modifica_evento',
                                                    'nuova_opportunita','modifica_orari_casa') THEN 'gestore'
              ELSE 'at' END
$$;

-- Casa dell'identità corrente (RLS) -------------------------------------------
-- Basata su current_user (mai su una GUC: NocoDB si connette col ruolo diretto e una GUC è spoofabile).
-- SECURITY INVOKER di proposito: dentro una SECURITY DEFINER current_user è l'owner, non il chiamante.
CREATE OR REPLACE FUNCTION trasi.casa_corrente() RETURNS integer
LANGUAGE sql STABLE SET search_path = '' AS $$
  SELECT rc.casa_id FROM trasi.ruolo_casa rc WHERE rc.ruolo = current_user::text
$$;

-- Trigger: i campi che nessuno si sceglie ------------------------------------
-- approvatore_ruolo (regola §11), proposto_da (identità reale, non impersonabile) e scade_il.
-- `stato` NON è forzato: resta al DEFAULT 'proposta', così la policy ins_client di db/005 può
-- respingere con 42501 un INSERT che tenti stato='approvata' (auto-approvazione, V4).
CREATE OR REPLACE FUNCTION trasi.proposta_00_default_tg() RETURNS trigger
LANGUAGE plpgsql SECURITY INVOKER SET search_path = '' AS $$
BEGIN
  NEW.approvatore_ruolo := trasi.approvatore_default(NEW.tipo, NEW.casa_id);
  NEW.proposto_da       := current_user::text;
  NEW.scade_il          := COALESCE(NEW.scade_il,
                                    current_date + COALESCE(trasi.p_int('gg_scadenza_proposta'), 30));
  RETURN NEW;
END $$;

DROP TRIGGER IF EXISTS proposta_00_default_tg ON trasi.proposta;
CREATE TRIGGER proposta_00_default_tg BEFORE INSERT ON trasi.proposta
  FOR EACH ROW EXECUTE FUNCTION trasi.proposta_00_default_tg();

-- ===========================================================================
-- C. Indici
-- ===========================================================================
CREATE INDEX IF NOT EXISTS richiesta_casa_ts_idx   ON trasi.richiesta (casa_id, ts);
CREATE INDEX IF NOT EXISTS proposta_stato_casa_idx ON trasi.proposta (stato, casa_id);
CREATE INDEX IF NOT EXISTS evento_casa_inizio_idx  ON trasi.evento (casa_id, inizio);
CREATE INDEX IF NOT EXISTS opportunita_scadenza_idx ON trasi.opportunita (scadenza);
CREATE INDEX IF NOT EXISTS casa_geom_gix           ON trasi.casa USING gist (geom);
CREATE INDEX IF NOT EXISTS luogo_geom_gix          ON trasi.luogo USING gist (geom);
-- indici delle chiavi esterne e dei filtri usati dalle viste/tool (schema-foreign-key-indexes)
CREATE INDEX IF NOT EXISTS luogo_casa_idx          ON trasi.luogo (casa_id);
CREATE INDEX IF NOT EXISTS luogo_fonte_idx         ON trasi.luogo (fonte_id);
CREATE INDEX IF NOT EXISTS luogo_tipo_idx          ON trasi.luogo (tipo);
CREATE INDEX IF NOT EXISTS scheda_servizio_casa_idx ON trasi.scheda_servizio (casa_id);
CREATE INDEX IF NOT EXISTS opportunita_casa_idx    ON trasi.opportunita (casa_id);
CREATE INDEX IF NOT EXISTS evento_fonte_idx        ON trasi.evento (fonte_id);
CREATE INDEX IF NOT EXISTS richiesta_destinazione_idx ON trasi.richiesta (destinazione_id);
CREATE INDEX IF NOT EXISTS identita_onyx_ruolo_idx ON trasi.identita_onyx (ruolo_db);
CREATE INDEX IF NOT EXISTS fonte_run_fonte_ts_idx  ON trasi.fonte_run (fonte_id, ts);
