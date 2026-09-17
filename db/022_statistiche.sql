-- Trasi — db/022_statistiche.sql  (scheda !NEW: i «Numeri» dell'Account, §4.3.1 e §5.3 del piano)
--
-- Una sola funzione: `trasi.fn_statistiche_casa(p_casa, p_dal, p_al)`. Serve la sezione «Numeri»
-- della pagina Account e nient'altro.
--
-- ---------------------------------------------------------------------------
-- Perché una funzione e non una vista (misurato, non dedotto)
-- ---------------------------------------------------------------------------
-- Le viste di reporting esistenti aggregano per **mese** o su tutta la storia:
--   * `v_report_mensile` → `date_trunc('month', ts)`: una finestra arbitraria come «ultimi 30 giorni»
--     non è esprimibile da lì, perché il mese corrente è un mese di calendario, non trenta giorni;
--   * `v_destinazioni`   → nessun filtro di data: aggrega `esito='inviata_altrove'` su tutto lo storico.
-- Filtrare quelle viste a valle darebbe numeri sbagliati in silenzio (i conteggi sarebbero già chiusi
-- per mese). Quindi l'aggregazione si rifà qui, sugli stessi predicati delle viste, con il filtro di
-- finestra al posto del mese. `v_uso_oggetti` fa eccezione ed è citata sotto.
--
-- ---------------------------------------------------------------------------
-- k-anonimato per cella: il numero sotto soglia non lascia il database
-- ---------------------------------------------------------------------------
-- `trasi.k_anon()` (db/004_views.sql) restituisce `n = NULL` e `n_label = '<5'` sotto
-- `[P] k_anonimato`, e `n = NULL`, `n_label = '—'` a zero. Qui si applica **per cella**, mai a valle:
-- la colonna grezza `cnt` è interna al CTE e non compare in nessuna colonna di uscita, quindi
-- `SELECT * FROM trasi.fn_statistiche_casa(...)` non può restituire il numero che la soglia vieta —
-- l'operatore dello shim, il LLM o Metabase leggono `n`/`n_label` e non hanno un secondo canale.
--
-- **Quali celle si mascherano, e perché non tutte.** Si mascherano i conteggi derivati da
-- `trasi.richiesta` — richieste per categoria, esito e destinazioni — perché sono l'unica tabella
-- del dominio che registra colloqui con persone: un conteggio di 1 in una categoria è, in una Casa
-- piccola, la traccia di un incontro. Non si mascherano eventi, schede e movimenti di attrezzoteca:
-- sono fatti pubblici della rete, e le stesse quantità escono **non mascherate** da `v_oggi_casa`
-- (riga «Oggi») e da `v_inventario`, che la Home e le dashboard già mostrano. Mascherarle qui
-- produrrebbe la cosa peggiore: due pagine che dicono numeri diversi sullo stesso fatto
-- («4 eventi» in Home, «<5» in Account). La regola è quindi «maschera ciò che conta le persone»,
-- e la colonna `sotto_soglia` dichiara riga per riga **dove** la soglia è scattata, così la UI può
-- spiegarla in parole invece di lasciare un simbolo senza contesto.
--
-- ---------------------------------------------------------------------------
-- La forma dell'uscita: una riga per cella, il blocco è un attributo
-- ---------------------------------------------------------------------------
-- `blocco`/`titolo`/`ordine` identificano il grafico, `tipo_riga` dice **cosa** è la riga:
--   * `conteggio` → `n`/`n_label` portano il numero (o il suo mascheramento) — è ciò che si disegna;
--   * `voce`      → la riga è un elemento nominato (un prossimo evento): `n` è NULL, il testo sta in
--                   `etichetta` e gli dettagli in `nota_riga`; non c'è nulla da contare;
--   * `vuoto`     → il blocco non ha dati, e il **vuoto si dichiara**: la frase sta in `etichetta`.
--                   «Il vuoto è un'informazione» è una regola del design system, e ha un precedente
--                   in questo schema: `v_eventi_dati_mancanti` dichiara le mancanze come dato.
-- Un blocco che non può che avere righe (esito, scadenze) non ha mai una riga `vuoto`;
-- quelli che possono restare senza dati (destinazioni, attrezzoteca) la ricevono quando serve.
-- `vuoto_testo` accompagna **ogni** riga del blocco con la frase con cui il blocco dichiara di non avere
-- dati: serve al caso distinto «il blocco ha righe, ma sono tutte a zero» — attrezzoteca con oggetti attivi
-- e nessun movimento — dove la pagina deve sapere **cosa** dire senza che la frase sia scritta due volte.
--
-- `aggiornato_il` è la data dell'ultimo dato che alimenta la riga, non la data di oggi: è ciò che
-- il badge di provenienza (V3) mostra come «agg.». Se manca, manca il dato, e il badge lo dichiara
-- invece di stampare una data plausibile.
--
-- Idempotente: `CREATE OR REPLACE FUNCTION` a ogni esecuzione.
\set ON_ERROR_STOP on
\set VERBOSITY terse

SET ROLE trasi_owner;
SET search_path = trasi, public, pg_temp;

-- ===========================================================================
-- fn_statistiche_casa — le sei serie dei «Numeri», su finestra arbitraria
-- ===========================================================================
-- Il `DROP` prima del `CREATE`: `CREATE OR REPLACE` non può cambiare il tipo di ritorno, e la firma di
-- uscita di questa funzione è destinata a crescere (una colonna dichiarata è un contratto con lo shim).
-- Un `CREATE OR REPLACE` che fallisse qui lascerebbe in piedi la versione vecchia, e l'errore arriverebbe
-- al primo `SELECT` dello shim invece che a chi applica. `IF EXISTS` la rende idempotente.
DROP FUNCTION IF EXISTS trasi.fn_statistiche_casa(integer, date, date);
CREATE OR REPLACE FUNCTION trasi.fn_statistiche_casa(p_casa integer, p_dal date, p_al date)
RETURNS TABLE (
  blocco        text,
  titolo        text,
  ordine        integer,
  ordine_riga   integer,
  tipo_riga     text,
  etichetta     text,
  nota_riga     text,
  n             integer,
  n_label       text,
  sotto_soglia  boolean,
  aggiornato_il date,
  fonte_nome    text,
  fonte_fiducia smallint,
  vuoto_testo   text
)
LANGUAGE sql STABLE SET search_path = '' AS $$
WITH
-- La fonte della memoria: la riga `kb` a fiducia più alta, con il nome **umano** (`autorita`,
-- «Rete delle Case di Quartiere di Brindisi») e non quello tecnico del seed («Rete-kb-3»).
-- È la stessa scelta di `shim/app/badge.py:nome_fonte`, ripetuta qui perché il badge lo compone lo
-- shim e il database gli deve dare la stessa coppia (nome, fiducia), non una seconda verità.
kb AS (
  SELECT COALESCE(NULLIF(btrim(f.autorita), ''), f.nome) AS nome, f.livello_fiducia
    FROM trasi.fonte f
   WHERE f.tipo_accesso = 'kb'
   ORDER BY f.livello_fiducia DESC, f.id
   LIMIT 1
),

-- La finestra: le richieste della Casa richiesta, ritagliate sul giorno locale. Il confronto è su
-- `ts::date` e non su `ts` perché `dal`/`al` sono giorni di calendario: un colloquio delle 21:30 di
-- `al` appartiene a `al`.
ric AS (
  SELECT r.categoria, r.esito, r.destinazione_id, r.destinazione_nota, r.ts
    FROM trasi.richiesta r
   WHERE r.casa_id = p_casa
     AND r.ts::date BETWEEN p_dal AND p_al
),

-- I blocchi: id, titolo in italiano (terza persona, nessun imperativo) e la frase con cui il blocco
-- dichiara di essere vuoto. Titoli e frasi stanno qui e non nella pagina, perché due consumatori
-- (la pagina Account e qualunque report futuro) devono leggere la stessa parola.
blocchi (id, titolo, ordine, vuoto_testo) AS (
  VALUES ('richieste_categoria'::text, 'Richieste registrate'::text, 1,
          'Nessuna richiesta registrata nel periodo.'::text),
         ('esito', 'Esito dei colloqui', 2,
          'Nessun esito registrato nel periodo.'),
         ('destinazioni', 'Dove sono state indirizzate le persone', 3,
          'Nessuna persona indirizzata altrove nel periodo.'),
         ('eventi', 'Eventi in programma', 4,
          'Nessun evento in programma.'),
         ('scadenze_proposte', 'Schede in scadenza e proposte', 5,
          'Nessuna scheda in scadenza e nessuna proposta in attesa.'),
         ('attrezzoteca', 'Uso dell''attrezzoteca', 6,
          'Nessun oggetto in attrezzoteca per questa Casa.')
),

-- --- 1 · richieste per categoria, con il totale in testa -------------------
-- Il totale è una cella come le altre e passa dalla stessa soglia: per una Casa con una sola
-- richiesta nel periodo, «totale» vale `<5` — che è il criterio di accettazione del piano.
b1 AS (
  SELECT 'richieste_categoria'::text AS blocco, 0 AS ordine_riga, 'conteggio'::text AS tipo_riga,
         'totale'::text AS etichetta, NULL::text AS nota_riga,
         count(*)::bigint AS cnt, max(ric.ts)::date AS aggiornato_il,
         (SELECT nome FROM kb) AS fonte_nome, (SELECT livello_fiducia FROM kb)::smallint AS fonte_fiducia
    FROM ric
  UNION ALL
  SELECT 'richieste_categoria', 10 + row_number() OVER (ORDER BY count(*) DESC, ric.categoria),
         'conteggio', ric.categoria, NULL,
         count(*)::bigint, max(ric.ts)::date,
         (SELECT nome FROM kb), (SELECT livello_fiducia FROM kb)::smallint
    FROM ric
   GROUP BY ric.categoria
),

-- --- 2 · esito dei colloqui ------------------------------------------------
-- Il vocabolario è chiuso (`richiesta_esito_check`) e si enumera tutto: un esito senza casi è uno
-- **zero**, e zero si mostra come `—`, non si omette. Omettere direbbe «non previsto», mostrare
-- «—» dice «nessun caso», che è un fatto diverso.
b2 AS (
  SELECT 'esito'::text, v.ordine_riga, 'conteggio'::text, v.etichetta::text, NULL::text,
         count(ric.esito)::bigint, max(ric.ts)::date,
         (SELECT nome FROM kb), (SELECT livello_fiducia FROM kb)::smallint
    FROM (VALUES (0, 'risolte', 'risolta'),
                 (1, 'inviate altrove', 'inviata_altrove'),
                 (2, 'non trovate', 'non_trovata'),
                 (3, 'rinviate', 'rinviata')) AS v(ordine_riga, etichetta, codice)
    LEFT JOIN ric ON ric.esito = v.codice
   GROUP BY v.ordine_riga, v.etichetta
),

-- --- 3 · dove sono state indirizzate le persone ----------------------------
-- Stessi predicati di `v_destinazioni` (solo `inviata_altrove`, nome del luogo o nota libera), ma
-- con la finestra: la vista non filtra per data e non è riusabile qui. La provenienza di riga è
-- quella del **luogo** di destinazione (fonte e affidabilità della sua riga in memoria), perché è
-- l'informazione che l'operatore deve poter verificare prima di mandarci qualcuno.
b3 AS (
  SELECT 'destinazioni'::text, row_number() OVER (ORDER BY count(*) DESC, COALESCE(l.nome, d.destinazione_nota)),
         'conteggio'::text,
         COALESCE(l.nome, d.destinazione_nota, 'destinazione non indicata')::text,
         CASE WHEN COALESCE(l.casa_id = p_casa, false) THEN 'interna alla Casa'
              ELSE 'esterna alla rete' END::text,
         count(*)::bigint, max(d.ts)::date,
         COALESCE(NULLIF(btrim(f.autorita), ''), f.nome), l.affidabilita::smallint
    FROM ric d
    LEFT JOIN trasi.luogo l ON l.id = d.destinazione_id
    LEFT JOIN trasi.fonte f ON f.id = l.fonte_id
   WHERE d.esito = 'inviata_altrove'
   GROUP BY l.nome, d.destinazione_nota, l.casa_id, f.autorita, f.nome, l.affidabilita
),

-- --- 4 · eventi in programma: il conteggio e i prossimi tre ----------------
-- «In programma» è `inizio >= now()`: un evento di stamattina non è in programma, e il confine è
-- l'istante, non il giorno (come in `v_kb_export`, che usa `COALESCE(fine, inizio) >= now()`).
b4 AS (
  (SELECT 'eventi'::text, 0, 'conteggio'::text, 'in programma'::text, NULL::text,
          count(*)::bigint, max(e.aggiornato_ts)::date,
          (SELECT nome FROM kb), (SELECT livello_fiducia FROM kb)::smallint
     FROM trasi.evento e
    WHERE e.casa_id = p_casa AND e.annullato = false AND e.inizio >= now())
  UNION ALL
  (SELECT 'eventi', 100 + row_number() OVER (ORDER BY e.inizio), 'voce', e.titolo,
          to_char(e.inizio AT TIME ZONE 'Europe/Rome', 'DD/MM/YYYY HH24:MI')
            || COALESCE(' · ' || NULLIF(btrim(e.luogo_testo), ''), ''),
          0::bigint, e.aggiornato_ts::date,
          (SELECT nome FROM kb), (SELECT livello_fiducia FROM kb)::smallint
     FROM trasi.evento e
    WHERE e.casa_id = p_casa AND e.annullato = false AND e.inizio >= now()
    ORDER BY e.inizio
    LIMIT 3)
),

-- --- 5 · schede in scadenza e proposte in attesa ---------------------------
-- Le due quantità che la riga «Oggi» mostra già (`v_oggi_casa`): la soglia di preavviso è la stessa
-- `[P] gg_preavviso_scadenza`, letta qui a ogni chiamata — il TI la cambia senza deploy e senza
-- toccare questa funzione.
b5 AS (
  (SELECT 'scadenze_proposte'::text, 0, 'conteggio'::text, 'schede in scadenza'::text, NULL::text,
          count(*)::bigint, max(COALESCE(s.validata_il, s.creato_ts::date)),
          (SELECT nome FROM kb), (SELECT livello_fiducia FROM kb)::smallint
     FROM trasi.scheda_servizio s
    WHERE s.casa_id = p_casa
      AND s.scadenza IS NOT NULL
      AND s.scadenza BETWEEN current_date
                         AND current_date + COALESCE(trasi.p_int('gg_preavviso_scadenza'), 15))
  UNION ALL
  (SELECT 'scadenze_proposte', 1, 'conteggio', 'proposte in attesa', NULL,
          count(*)::bigint, max(p.proposto_ts)::date,
          (SELECT nome FROM kb), (SELECT livello_fiducia FROM kb)::smallint
     FROM trasi.proposta p
    WHERE p.casa_id = p_casa AND p.stato = 'proposta')
),

-- --- 6 · uso dell'attrezzoteca, per oggetto -------------------------------
-- Gli **oggetti della Casa** (non quelli della rete: `v_uso_oggetti` non è filtrata per ruolo),
-- ciascuno con i movimenti andati a buon fine **dentro la finestra richiesta**. `v_uso_oggetti`
-- conta su 12 mesi fissi, e usarla qui significherebbe che il filtro periodo della pagina non ha
-- effetto su questo grafico: un filtro che finge di filtrare è peggio di un filtro assente. La
-- fascia d'uso (`basso`/`medio`/`alto`) riusa le stesse soglie `[P]` della vista.
b6 AS (
  SELECT 'attrezzoteca'::text, 10 + row_number() OVER (ORDER BY uso.n_movimenti DESC, o.nome),
         'conteggio'::text, o.nome,
         ('uso ' || CASE WHEN uso.n_movimenti < COALESCE(trasi.p_int('attrezzoteca_soglia_bassa'), 2) THEN 'basso'
                         WHEN uso.n_movimenti >= COALESCE(trasi.p_int('attrezzoteca_soglia_alta'), 10) THEN 'alto'
                         ELSE 'medio' END)::text,
         uso.n_movimenti::bigint, uso.ultimo_ts::date,
         (SELECT nome FROM kb), (SELECT livello_fiducia FROM kb)::smallint
    FROM trasi.oggetto o
    CROSS JOIN LATERAL (
      SELECT count(*) AS n_movimenti, max(m.ts) AS ultimo_ts
        FROM trasi.movimento m
       WHERE m.oggetto_id = o.id
         AND m.stato IN ('confermato', 'rientrato')
         AND m.ts::date BETWEEN p_dal AND p_al
    ) uso
   WHERE o.casa_id = p_casa AND o.attivo
),

-- Le celle di tutti i blocchi, nella forma comune. `maschera` è **derivata dal blocco**, in un punto
-- solo: i sei CTE non la portano, così non esiste un ramo che possa dimenticarla o contraddirla.
righe AS (
  SELECT blocco, ordine_riga, tipo_riga, etichetta, nota_riga, cnt,
         blocco IN ('richieste_categoria', 'esito', 'destinazioni') AS maschera,
         aggiornato_il, fonte_nome, fonte_fiducia
    FROM b1
  UNION ALL
  SELECT blocco, ordine_riga, tipo_riga, etichetta, nota_riga, cnt,
         blocco IN ('richieste_categoria', 'esito', 'destinazioni'),
         aggiornato_il, fonte_nome, fonte_fiducia
    FROM (
      SELECT * FROM b2
      UNION ALL SELECT * FROM b3
      UNION ALL SELECT * FROM b4
      UNION ALL SELECT * FROM b5
      UNION ALL SELECT * FROM b6
    ) AS resto(blocco, ordine_riga, tipo_riga, etichetta, nota_riga, cnt,
               aggiornato_il, fonte_nome, fonte_fiducia)
),

-- Il vuoto dichiarato: un blocco che non ha prodotto nessuna riga ne riceve una che lo dice.
dichiarati AS (
  SELECT b.id, 0, 'vuoto'::text, b.vuoto_testo, NULL::text, NULL::bigint, false,
         NULL::date, NULL::text, NULL::smallint
    FROM blocchi b
   WHERE NOT EXISTS (SELECT 1 FROM righe r WHERE r.blocco = b.id)
)

SELECT b.id AS blocco,
       b.titolo,
       b.ordine,
       r.ordine_riga,
       r.tipo_riga,
       r.etichetta,
       r.nota_riga,
       -- Il numero grezzo non esce: sotto soglia la sola via è `n_label`, e per le righe che non
       -- sono un conteggio (`voce`, `vuoto`) non c'è nulla da mostrare.
       CASE WHEN r.tipo_riga <> 'conteggio' THEN NULL
            WHEN r.maschera THEN a.n
            ELSE r.cnt::integer END AS n,
       CASE WHEN r.tipo_riga <> 'conteggio' THEN NULL
            WHEN r.maschera THEN a.n_label
            WHEN r.cnt = 0 THEN '—'
            ELSE r.cnt::text END AS n_label,
       (r.maschera AND a.n IS NULL AND r.cnt > 0) AS sotto_soglia,
       r.aggiornato_il,
       r.fonte_nome,
       r.fonte_fiducia,
       -- La frase con cui il blocco dichiara di non avere dati: accompagna **ogni** riga del blocco,
       -- così il consumatore non deve dedurla e la pagina non la riscrive (due copie della stessa frase
       -- divergono alla prima revisione dei testi).
       b.vuoto_testo
  FROM (SELECT * FROM righe UNION ALL SELECT * FROM dichiarati) r
  JOIN blocchi b ON b.id = r.blocco
  -- `k_anon` su **ogni** cella, anche su quelle che non si mascherano: così la regola della soglia
  -- vive in un posto solo, e il giorno in cui una cella cambia regime basta cambiare `maschera`.
  CROSS JOIN LATERAL trasi.k_anon(r.cnt) a
 ORDER BY b.ordine, r.ordine_riga
$$;

-- ===========================================================================
-- Permessi: la funzione la esegue il ruolo della Casa, non solo lo shim
-- ===========================================================================
-- `EXECUTE` si controlla su `current_user`, e lo shim esegue **dopo** `SET LOCAL ROLE casa_*`
-- (`shim/app/auth.py`): concederla al solo `shim_rw` la renderebbe ineseguibile da ogni endpoint.
-- Quindi i dieci ruoli Casa, più `rete`/`ti` (che leggono la rete e i cruscotti) e `applicatore`
-- (le funzioni di dominio girano col suo ruolo).
--
-- `REVOKE … FROM PUBLIC` prima del `GRANT`: senza, PostgreSQL lascerebbe a `PUBLIC` il permesso
-- che concede a ogni funzione nuova, e il `GRANT` esplicito non toglierebbe nulla — un elenco di
-- autorizzati che non autorizza, cioè un presidio che non si può verificare.
REVOKE ALL ON FUNCTION trasi.fn_statistiche_casa(integer, date, date) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION trasi.fn_statistiche_casa(integer, date, date)
  TO casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao, casa_minimus, casa_pop,
     casa_bozzano, casa_dream, casa_tuturano, rete, ti, shim_rw, applicatore;

-- ===========================================================================
-- Verifica di installazione — l'effetto, non l'intenzione
-- ===========================================================================
DO $verify$
DECLARE
  v_senza_permesso text;
  v_esito          record;
BEGIN
  SELECT string_agg(r.rolname, ', ' ORDER BY r.rolname) INTO v_senza_permesso
    FROM pg_roles r
   WHERE r.rolname IN ('casa_santaspazio', 'casa_molo12', 'casa_erranti', 'casa_buscicchio',
                       'casa_sanbao', 'casa_minimus', 'casa_pop', 'casa_bozzano', 'casa_dream',
                       'casa_tuturano', 'rete', 'ti', 'shim_rw')
     AND NOT has_function_privilege(r.rolname,
           'trasi.fn_statistiche_casa(integer, date, date)', 'EXECUTE');
  IF v_senza_permesso IS NOT NULL THEN
    RAISE EXCEPTION '022: fn_statistiche_casa non eseguibile da: %', v_senza_permesso;
  END IF;

  -- La firma deve restare quella dichiarata: un `RETURN TABLE` cambiato in silenzio rompe lo shim
  -- a runtime, e il consumatore vedrebbe un errore di colonna mancante invece di un guasto vero.
  IF (SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
       WHERE n.nspname = 'trasi' AND p.proname = 'fn_statistiche_casa'
         AND pg_get_function_result(p.oid) LIKE '%sotto_soglia%') <> 1 THEN
    RAISE EXCEPTION '022: firma di fn_statistiche_casa inattesa';
  END IF;

  -- Prova in transazione: la funzione deve girare **come un ruolo Casa**, non come owner. Se la
  -- RLS o un GRANT colonnare la bloccassero, l'errore arriverebbe qui e non al primo click.
  SET LOCAL ROLE casa_bozzano;
  SELECT * INTO v_esito FROM trasi.fn_statistiche_casa(8, current_date - 30, current_date) LIMIT 1;
  IF v_esito.blocco IS NULL THEN
    RAISE EXCEPTION '022: fn_statistiche_casa non ha restituito righe per la Casa 8';
  END IF;
  IF v_esito.tipo_riga NOT IN ('conteggio', 'voce', 'vuoto') THEN
    RAISE EXCEPTION '022: tipo_riga inatteso: %', v_esito.tipo_riga;
  END IF;

  RAISE NOTICE '022_statistiche applicato: fn_statistiche_casa su finestra arbitraria, k-anon per cella, GRANT a 10 Case + rete/ti/shim_rw';
END
$verify$;

RESET ROLE;
