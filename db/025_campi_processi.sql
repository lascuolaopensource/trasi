-- Trasi — db/025_campi_processi.sql
-- I campi che il gruppo Processi chiede e che i nostri schemi non avevano.
--
-- ------------------------------------------------------------------------------------------------
-- DA DOVE VIENE QUESTO FILE
-- ------------------------------------------------------------------------------------------------
-- Il gruppo Processi ha fornito l'architettura delle variabili informative degli oggetti del sistema
-- (foglio Google `12UTF0ot7w5KFiDxkyCxSdcviAyUthVRszGtCurZYmeQ`, 8 fogli). Il confronto campo per campo
-- è in `docs/confronto-schemi-processi.md`; questo file implementa **solo** la parte che è:
--
--   (a) additiva — nessuna colonna rimossa, nessun tipo cambiato, nessun chiamante rotto;
--   (b) priva di tensione con V4/V5 — nessun campo del cittadino, nessuna scrittura fuori dal flusso
--       (i dati della propria Casa passano da `salva_dato`, gli altri da proposta).
--
-- **Cosa NON è qui, e perché.** Tre voci del foglio richiedono una decisione che non spetta a un agente:
--
--   * **4.4 età/genere/provenienza del cittadino** — va contro V5 (§12: «nessun campo per il cittadino»,
--     presidiato da `t_seed.sql` O05 e dal k-anonimato 5). La forma compatibile esiste — fasce + conteggi
--     mascherati — ma è una decisione di Processi e DPO. In `docs/confronto-schemi-processi.md` §4.
--   * **Persone della Casa** (nome, ruolo, competenze) — sono dati personali che finirebbero in
--     `v_kb_export` e quindi citabili in chat. Serve una decisione su consenso, retention e visibilità (§5).
--   * **4.5 stakeholders** — non è un campo mancante, è un oggetto che non esiste: anagrafica nuova o
--     `luogo` con un ruolo? La differenza è sostanziale (§3.6).
--
-- Aggiungere quei campi «per completezza» sarebbe la cosa più facile e la più sbagliata: sono esattamente
-- i casi in cui il progetto ha già scelto, e riaprirli silenziosamente vanificherebbe la scelta.
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
  SELECT string_agg(x, ', ') INTO v_missing
    FROM unnest(ARRAY['trasi.casa','trasi.evento','trasi.oggetto','trasi.commento','trasi.report']) x
   WHERE to_regclass(x) IS NULL;
  IF v_missing IS NOT NULL THEN
    RAISE EXCEPTION '025_campi_processi: mancano % — applica prima db/000–024', v_missing;
  END IF;
END
$pre$;

-- ---------------------------------------------------------------------------
-- 1. `casa` — indirizzo ed edificio (foglio 1.1)
-- ---------------------------------------------------------------------------
-- Due campi su tre: **`telefono` è stato rimosso**, e la ragione è una prova, non un'opinione.
--
-- Il foglio 1.1 chiede i «Recapiti telefonici» della Casa. Li avevo aggiunti come colonna, poi ho provato a
-- scriverli: `salva_dato` → **422 `dato_personale_sospetto — campi con dati personali: telefono`**. Il
-- filtro `pii.TELEFONO` dello shim riconosce *qualunque* numero fisso o cellulare italiano, e **non può
-- distinguere** un centralino di sportello da un cellulare personale: la differenza non è nella forma del
-- numero.
--
-- Quindi la scelta non è «aggiungo il campo e sto attento»: è che **il sistema non può verificare** la
-- promessa «è un numero di servizio». Una colonna che accetta numeri di telefono in una tabella del dominio
-- — esportata in `v_kb_export` e quindi **citabile dall'assistente in chat** — reintroduce per la porta di
-- servizio ciò che V5/§12 tiene fuori dalla porta principale. Il filtro PII ha funzionato come presidio: ha
-- rifiutato il mio stesso dato di prova, che era un numero vero.
--
-- **Dove il recapito può stare**: `casa.email_digest` (già esistente, ed è un indirizzo di servizio), e i
-- **luoghi** (`luogo.indirizzo`, e il biglietto A6 che oggi porta l'indirizzo di destinazione). Se Processi
-- vuole un telefono di Casa, la via è una decisione su *come* garantire che non sia personale — non una
-- colonna in più. Tracciato in `docs/confronto-schemi-processi.md` §6.2.
--
-- **`indirizzo` non è ridondante con `luogo.indirizzo`.** Il secondo è l'indirizzo di un *luogo sul
-- territorio* (un CAF, una farmacia); questo è l'indirizzo della **sede della Casa**. Il biglietto A6 ha
-- già l'indirizzo del luogo di destinazione: senza questo campo, «come arrivo alla Casa» resta senza
-- risposta, e la Home manda a una mappa con un pin e senza un civico.
--
-- **`edificio`** è la denominazione dell'immobile («Ex scuola De Amicis»): serve all'orientamento, perché
-- l'indirizzo da solo non basta a chi non conosce il quartiere.
ALTER TABLE trasi.casa ADD COLUMN IF NOT EXISTS indirizzo text;
ALTER TABLE trasi.casa ADD COLUMN IF NOT EXISTS edificio  text;

COMMENT ON COLUMN trasi.casa.indirizzo IS
  'Indirizzo civico della sede della Casa (foglio 1.1). Diverso da luogo.indirizzo, che è quello di un '
  'luogo sul territorio.';

-- **Il GRANT, senza il quale i campi sarebbero inutilizzabili.** La specifica del gruppo Processi è che
-- «ogni casa/ente può modificare i propri dati, della propria casa»: i due campi nuovi sono dati della Casa,
-- quindi vanno nel privilegio che la Casa già ha sulle proprie colonne (`db/002`:
-- `UPDATE (orari, orari_eccezioni, orari_provvisori, email_digest)`).
--
-- Misurato: senza questo GRANT, `salva_dato` con `entita=casa` e `indirizzo` risponde **422** (il campo non
-- è nell'elenco chiuso dello shim) e, aggiunto all'elenco, sarebbe **42501** dal database. Il sintomo
-- avrebbe detto «parametro non ammesso» e la causa era un privilegio assente — la stessa lezione di
-- `effective_permissions` in B3: la colonna c'è, la scrittura no, e il messaggio non lo spiega.
--
-- `affidabilita`/`fonte_id` NON si concedono: un operatore non si dichiara «affidabile 1» né si firma.
GRANT UPDATE (indirizzo, edificio) ON trasi.casa TO
  casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
  casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano;

-- Se una versione precedente di questo file aveva creato `telefono`, la si rimuove: un campo che il sistema
-- non può popolare senza rifiutare il valore è un campo che confonde chi lo trova vuoto.
ALTER TABLE trasi.casa DROP COLUMN IF EXISTS telefono;

-- ---------------------------------------------------------------------------
-- 2. `evento` — costo, fascia d'età, tag, ricorrenza (foglio 2.1)
-- ---------------------------------------------------------------------------
ALTER TABLE trasi.evento ADD COLUMN IF NOT EXISTS costo numeric(8,2);
ALTER TABLE trasi.evento ADD COLUMN IF NOT EXISTS fascia_eta text;
ALTER TABLE trasi.evento ADD COLUMN IF NOT EXISTS tag text[] NOT NULL DEFAULT '{}'::text[];
ALTER TABLE trasi.evento ADD COLUMN IF NOT EXISTS ricorrenza text;

-- **`costo = 0` significa «gratuito», `NULL` «non noto»**: è la distinzione che il foglio rende esplicita
-- («0 è gratuito») e che un solo valore sentinella confonderebbe. Il CHECK vieta i negativi, che non hanno
-- significato per un evento pubblico.
ALTER TABLE trasi.evento DROP CONSTRAINT IF EXISTS evento_costo_non_negativo;
ALTER TABLE trasi.evento ADD CONSTRAINT evento_costo_non_negativo CHECK (costo IS NULL OR costo >= 0);

-- **`fascia_eta` a vocabolario chiuso**, e le fasce sono dichiarate qui perché la stessa scala servirà ai
-- report (foglio 4.3: «gli ambiti più richiesti»). Un testo libero («per tutti», «adulti», «18+») non è
-- aggregabile, e senza aggregazione il campo non serve a nulla.
ALTER TABLE trasi.evento DROP CONSTRAINT IF EXISTS evento_fascia_eta_check;
ALTER TABLE trasi.evento ADD CONSTRAINT evento_fascia_eta_check
  CHECK (fascia_eta IS NULL OR fascia_eta IN ('0-13','14-17','18-29','30-44','45-59','60-74','75+','tutte'));

-- **`ricorrenza`**: il foglio chiede «ogni settimana / ogni 2 settimane / ogni mese / ogni anno». Senza
-- questo campo, un evento settimanale esiste solo come N righe — e le righe multiple **rompono l'upsert
-- iCal** (`uid_ical` identifica un evento: N copie dello stesso `uid` violerebbero l'unicità). Quindi il
-- campo non è un abbellimento: è la condizione perché un evento ricorrente possa esistere.
--
-- Il valore è la **regola**, non le occorrenze: le occorrenze si calcolano (`inizio` + intervallo). Il
-- foglio dice «ricorrente» come proprietà dell'evento, ed è quello che si registra.
ALTER TABLE trasi.evento DROP CONSTRAINT IF EXISTS evento_ricorrenza_check;
ALTER TABLE trasi.evento ADD CONSTRAINT evento_ricorrenza_check
  CHECK (ricorrenza IS NULL OR ricorrenza IN ('settimanale','bisettimanale','mensile','annuale'));

COMMENT ON COLUMN trasi.evento.costo IS
  'Costo in euro (foglio 2.1). 0 = gratuito, NULL = non noto: due cose diverse, e il foglio le distingue.';
COMMENT ON COLUMN trasi.evento.ricorrenza IS
  'Regola di ricorrenza (settimanale/bisettimanale/mensile/annuale); NULL = evento singolo. Le occorrenze '
  'si calcolano da inizio, non si memorizzano: eviterebbe N righe con lo stesso uid_ical.';
COMMENT ON COLUMN trasi.evento.tag IS
  'Etichette dell''evento (foglio 2.1: «in base ai tipi di evento»). Array e non tabella: sono attributi '
  'dell''evento, non entità con una vita propria.';

-- L'indice sui tag: `GIN` perché si cerca «gli eventi con questo tag», che su un array è una query di
-- contenimento (`tag @> ARRAY['musica']`). Senza, ogni ricerca per tag è una scansione sequenziale.
CREATE INDEX IF NOT EXISTS evento_tag_idx ON trasi.evento USING gin (tag);

-- ---------------------------------------------------------------------------
-- 3. `oggetto` — tipo di materiale (foglio 3.1)
-- ---------------------------------------------------------------------------
-- Il foglio chiede «Tipo di materiale». Oggi l'inventario ha `nome` e `descrizione` come testo libero,
-- quindi **non si può filtrare** («mostrami tutti gli attrezzi disponibili»): si può solo cercare per
-- sottostringa del nome, che dipende da come l'operatore ha scritto la riga.
--
-- Vocabolario **aperto** (text senza CHECK) e non chiuso: il foglio non elenca i tipi, e indovinarli
-- significherebbe rifiutare con un 422 una categoria legittima che Processi userà. La coerenza si ottiene
-- a valle — la vista `v_uso_oggetti` raggruppa per tipo — non con un vincolo che nessuno ha ancora
-- specificato. Quando Processi darà l'elenco, il CHECK si aggiunge con un file nuovo (l'ordinamento di
-- db/000–025 è congelato).
ALTER TABLE trasi.oggetto ADD COLUMN IF NOT EXISTS tipo text;

COMMENT ON COLUMN trasi.oggetto.tipo IS
  'Tipo di materiale (foglio 3.1), per filtrare l''inventario. Vocabolario aperto finché Processi non '
  'fornisce l''elenco.';

-- ---------------------------------------------------------------------------
-- 4. `commento` — la segnalazione su «mancanze in piattaforma» (foglio 4.2)
-- ---------------------------------------------------------------------------
-- Il foglio 4.2 descrive **tre** cose: commenti sugli eventi, feedback sulla Casa, e «segnalazioni di
-- mancanze in piattaforma». Le prime due sono già coperte da `commento.entita` ('evento', 'report'); la
-- terza no, ed è distinta: è una mancanza dello **strumento** (una funzione che serve e non c'è, un dato
-- che il sistema non chiede), non del dato o dell'evento.
--
-- Estendere il CHECK è l'unico modo di rappresentarla senza una seconda tabella che sarebbe identica
-- (`testo`, `casa_id`, `ts`): la differenza è *su cosa* si commenta, che è già il discriminante di `entita`.
ALTER TABLE trasi.commento DROP CONSTRAINT IF EXISTS commento_entita_check;
ALTER TABLE trasi.commento ADD CONSTRAINT commento_entita_check
  CHECK (entita IN ('report','evento','piattaforma'));

-- ---------------------------------------------------------------------------
-- 5. `report` — i suggerimenti dell'osservatorio (foglio 4.3)
-- ---------------------------------------------------------------------------
-- Il foglio 4.3 chiede, per il report **aggregato**, «indicazioni e suggerimenti operativi» e «strategici
-- e di gestione per l'intero ecosistema». Sono il valore aggiunto dell'osservatorio — e non hanno un posto
-- dove vivere: `contenuti` è JSONB e potrebbe ospitarli, ma un testo lungo dentro un JSONB non è
-- interrogabile né mostrabile da una dashboard senza estrarlo.
--
-- Una colonna propria, invece: si legge, si cerca, si mostra. Vuota per i report di Casa (`ambito='casa'`),
-- dove il foglio non la prevede.
ALTER TABLE trasi.report ADD COLUMN IF NOT EXISTS suggerimenti text;

COMMENT ON COLUMN trasi.report.suggerimenti IS
  'Indicazioni e suggerimenti dell''osservatorio (foglio 4.3), per i report con ambito=''osservatorio''. '
  'Non è il commento di una Casa: quello è in `commento`, e la regola di Processi lo tiene distinto.';

-- ---------------------------------------------------------------------------
-- 6. Le viste espongono i campi nuovi
-- ---------------------------------------------------------------------------
-- `v_eventi` (db/008) è la superficie della Home e della dashboard: senza i campi nuovi, l'evento
-- ricorrente e il costo non arrivano all'operatore. Si ricrea con le colonne in più, **in coda**:
-- le colonne esistenti restano dove sono (un consumatore che legge per posizione non si rompe).
DROP VIEW IF EXISTS trasi.v_eventi;
CREATE VIEW trasi.v_eventi AS
SELECT e.id, e.casa_id, c.slug AS casa_slug, c.nome AS casa_nome,
       e.titolo, e.descrizione, e.inizio, e.fine, e.luogo_testo, e.url,
       COALESCE(f.nome, 'inserito dall''operatore') AS fonte_nome,
       COALESCE(e.affidabilita, 2) AS affidabilita,
       e.aggiornato_ts, e.creato_ts,
       (e.inizio::date - current_date) AS giorni_all_inizio,
       -- L'intervallo in italiano, già composto: ricomporlo in ogni card significherebbe due formattazioni
       -- da tenere allineate (stessa ragione di `v_oggi_casa`).
       CASE
         WHEN e.fine IS NULL THEN to_char(e.inizio, 'DD/MM/YYYY – HH24:MI')
         WHEN e.inizio::date = e.fine::date THEN
           to_char(e.inizio, 'DD/MM/YYYY – HH24:MI') || '–' || to_char(e.fine, 'HH24:MI')
         ELSE to_char(e.inizio, 'DD/MM/YYYY') || ' – ' || to_char(e.fine, 'DD/MM/YYYY')
       END AS quando,
       -- I campi del foglio 2.1. `gratuito` è un booleano **derivato** e non memorizzato: `costo = 0` e
       -- `costo IS NULL` sono due cose diverse, e una colonna in più le confonderebbe al primo `UPDATE`.
       e.costo,
       (e.costo = 0) AS gratuito,
       e.fascia_eta,
       e.tag,
       e.ricorrenza,
       -- La ricorrenza in parole, per la stessa ragione di `quando`.
       CASE e.ricorrenza
         WHEN 'settimanale'   THEN 'ogni settimana'
         WHEN 'bisettimanale' THEN 'ogni 2 settimane'
         WHEN 'mensile'       THEN 'ogni mese'
         WHEN 'annuale'       THEN 'ogni anno'
         ELSE NULL
       END AS ricorrenza_testo
FROM trasi.evento e
LEFT JOIN trasi.casa c ON c.id = e.casa_id
LEFT JOIN trasi.fonte f ON f.id = e.fonte_id
WHERE e.annullato = false;

-- `security_invoker = false` come le altre viste di lettura pubblica (db/008): la vista espone dati già
-- pubblici nella rete (eventi con il loro badge di provenienza), ed è la forma che `t_viste.sql` V09 chiede
-- per le viste aggregate. Qui non ci sono numeri di persone: il k-anonimato non si applica.
ALTER VIEW trasi.v_eventi SET (security_invoker = false);

GRANT SELECT ON trasi.v_eventi TO
  casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao,
  casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano,
  rete, ti, metabase_ro, automazioni, shim_rw, applicatore;

-- ---------------------------------------------------------------------------
-- 7. Verifica di installazione
-- ---------------------------------------------------------------------------
DO $verify$
DECLARE v_missing text;
BEGIN
  SELECT string_agg(v.t || '.' || v.c, ', ') INTO v_missing FROM (VALUES
    ('casa','indirizzo'),('casa','edificio'),
    ('evento','costo'),('evento','fascia_eta'),('evento','tag'),('evento','ricorrenza'),
    ('oggetto','tipo'),
    ('report','suggerimenti')
  ) AS v(t, c)
  WHERE NOT EXISTS (SELECT 1 FROM information_schema.columns ic
                     WHERE ic.table_schema='trasi' AND ic.table_name=v.t AND ic.column_name=v.c);
  IF v_missing IS NOT NULL THEN
    RAISE EXCEPTION '025_campi_processi: colonne non aggiunte: %', v_missing;
  END IF;

  -- I vocabolari chiusi devono rifiutare un valore fuori elenco: se il CHECK non c'è, il campo è di fatto
  -- testo libero e l'aggregazione nei report (fascia d'età) non è possibile.
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='evento_fascia_eta_check') THEN
    RAISE EXCEPTION '025_campi_processi: CHECK su evento.fascia_eta assente';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='evento_ricorrenza_check') THEN
    RAISE EXCEPTION '025_campi_processi: CHECK su evento.ricorrenza assente';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='commento_entita_check'
                   AND pg_get_constraintdef(oid) LIKE '%piattaforma%') THEN
    RAISE EXCEPTION '025_campi_processi: commento.entita non ammette «piattaforma» (foglio 4.2)';
  END IF;

  RAISE NOTICE '025_campi_processi applicato: casa (indirizzo, edificio) · evento (costo, fascia_eta, tag, ricorrenza) · oggetto.tipo · commento piattaforma · report.suggerimenti · v_eventi aggiornata';
END
$verify$;

RESET ROLE;
