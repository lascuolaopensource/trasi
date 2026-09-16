# TASK SPEC — B3 Shim: implementazione reale (`trasi-shim`)

## Target

Trasforma lo **stub** in `shim/` (oggi 9 route che rispondono 501) nell'**implementazione reale** dei 9 endpoint, mantenendo il contratto `shim/openapi.yaml` **congelato** (gate V-09 superato: non cambiarne `operationId`, schemi, `servers[].url`).

Blocco **critico** (§13): è ciò da cui dipende la batteria completa e l'E2E di B7.

## Contesto verificato (non ri-verificare)

**Servizi attivi:**
- `trasi-db_trasi-1` — Postgres 16 + PostGIS 3.4.3, DB `trasi_db`, schema `trasi`. Raggiungibile nella rete `trasi_net` come hostname **`db_trasi`**.
- `trasi-searxng-1` — SearXNG interno, rete `trasi_net`, hostname **`searxng`**, porta **8080**, **`format=json` già abilitato** (verificato: 40 risultati).
- Shim: servizio nel compose `deployment/docker-compose.yml` (build `../shim`, `mem_limit 256m`, rete `trasi_net`, healthcheck `/healthz`). Env già presenti: `DATABASE_URL` (`postgresql://shim_rw:<pw>@db_trasi:5432/trasi_db`), `TRASI_SHIM_KEY`, `OVERPASS_URL`, `OVERPASS_URL_2`, `OVERPASS_TIMEOUT_S=5`.

**Contratto DB reale** (leggi i file in `db/` — sono la fonte di verità, non questo riassunto):
- `trasi.identita_onyx(email text, ruolo_db text, casa_id int, attiva bool)` — **la colonna è `ruolo_db`**, non `ruolo`
- `trasi.casa_corrente()` → `casa_id` dal `current_user` via `ruolo_casa`
- `trasi.p_int(chiave)` / `p_text` / `p_bool` — parametri `[P]`
- `trasi.aperto_a(orari jsonb, eccezioni jsonb, ts timestamptz) → bool`
- `trasi.proposta` — INSERT **colonnare** (non passare `approvatore_ruolo`/`stato`: li calcola il trigger `proposta_00_default_tg`)
- `trasi.applica_proposte_approvate(p_limit)` — non serve allo shim
- viste: `v_oggi_casa(casa_id, slug, nome, data, eventi, schede_in_scadenza, proposte, testo)`, `v_kb_export`, `v_da_approvare` (coda filtrata per `casa_corrente()`)
- `trasi.fonte(tipo_accesso, livello_fiducia, attiva, nome, url)` — allow-list
- **Non esistono** funzioni `proponi_modifica`/`approva_proposta`: lo shim fa INSERT/UPDATE diretto su `proposta` (§9.1)

**Modello di identità (verificato funzionante):**
`shim_rw` ha **SELECT** su `proposta` ma **nessun privilegio di tabella** per INSERT/UPDATE — i GRANT sono **colonnari** e appartengono ai ruoli `casa_<slug>`. Quindi lo shim **deve** fare:
```
BEGIN; SET LOCAL ROLE <ruolo_db da identita_onyx>; <query>; COMMIT
```
Verificato: con `SET LOCAL ROLE casa_sanbao` l'INSERT su `proposta` riesce e il trigger imposta `approvatore_ruolo='gestore'`. **È il design, non un bug.**

**Overpass — vincolo scoperto e verificato dal coordinatore:**
```
UA 'python-httpx/0.27' → 403
UA 'Trasi/0.1 (portierato Brindisi)' → 200
```
Il client **deve** inviare uno User-Agent identificativo, altrimenti ogni chiamata fallisce con 403 opaco. `overpass-api.de` ha dato 504 in prova: trattalo come failover instabile, non come alternativa affidabile.

## Change

### 1. Identità e sessione DB (`B3-SHM-01`)
- middleware che risolve `X-Onyx-User-Email` → `identita_onyx` → `ruolo_db` (cache breve, es. 60 s)
- per **ogni** richiesta autenticata: `BEGIN; SET LOCAL ROLE <ruolo_db>; …; COMMIT` (transazione, mai `SET` persistente)
- errori: **401** se `X-Trasi-Key` errata; **403** `{"detail":"identità non riconosciuta"}` se l'email non è in `identita_onyx` o è `anonymous` — e in quel caso **nessuna query eseguita**
- **log senza corpo**: mai email, `motivazione`, `payload`, coordinate. Solo `ts, method, operationId, status, ms, ruolo`
- `GET /{email}/_whoami` attivo solo se `SHIM_DEBUG=1` (per i test)

### 2. Lettura (`B3-SHM-02`)
- `cerca_luogo(q, tipo?, quartiere?)` — KB; `q` < 2 char → 422; nessun risultato → **200 con `items: []`** (mai 404)
- `eventi_oggi(casa, data?)` — KB; slug inesistente → 404

### 3. `vicino_a` (`B3-SHM-03/04`) — il pezzo più delicato
- unisce **KB** (`ST_DWithin(l.geom, c.geom, raggio)`) e **Overpass** (POI entro `casa.raggio_m`, default `p_int('raggio_vicinanza_m')`)
- **User-Agent identificativo obbligatorio**; timeout 5 s; su timeout/errore → **200** con `fonti_esterne[].stato ∈ {ok,timeout,errore,scartata_fiducia}`, mai eccezione
- ordinamento: `kb` prima di `esterna`; dentro il gruppo, aperti noti → `null` → chiusi; poi distanza
- **copertura OSM reale bassa (7.7% bar Brindisi)**: con `aperto_adesso=true` i POI **senza** `opening_hours` restano elencati **dopo** gli aperti noti, con `aperto_adesso: null` e `orari_nota="orari non disponibili"` — **mai scartati**
- scarto delle fonti sotto `p_int('fiducia_min_esterna')` → `stato="scartata_fiducia"`
- max `p_int('max_risultati_esterni')` per gli esterni
- ogni item porta `badge` **pre-formattato** (`[KB · fonte · data · affidabilità]` / `[Esterna · fonte · ora · non verificata dalla rete]`) così il LLM non deve comporlo
- tipo fuori dal vocabolario → 422 con l'elenco ammesso

### 4. Scritture mediate (`B3-SHM-05/06`)
- `registra_richiesta`: `casa_id` **dall'identità**, mai dal body; `esito='inviata_altrove'` senza destinazione → 422; campo extra → 422 (`extra="forbid"`); è l'unica scrittura non-proposta (registro operativo)
- `proponi_modifica`: INSERT su `proposta` **senza** `approvatore_ruolo`/`stato` (li calcola il trigger); **filtro anti-PII** su `motivazione` **e** `payload` (email, telefono IT, codice fiscale) → 422 `dato_personale_sospetto`; risposta 201 con `proposta_id`, `approvatore_ruolo`, e `chat_approvabile: bool`
- `approva_proposta`: `UPDATE proposta SET stato=… WHERE id=$1` come ruolo dell'operatore; **0 righe → 403** `{"detail":"da approvare in coda"}` (la RLS è l'autorità, nessun pre-check fidato); proposta scaduta → **409**; già chiusa → 409

### 5. Biglietto e riga Oggi (`B3-SHM-07/08`)
- `biglietto(luogo_id, casa?)` → HTML **A6** (`@page { size: A6; margin: 8mm }`): nome, indirizzo, orari, come arrivare, fonte+data+badge. **Nessun campo del cittadino**, nessun `<form>`/`<input>`. Accetta anche `osm:node:<id>` (ricarica da Overpass, badge `[Esterna …]`)
- `oggi(casa)` → dalla vista `v_oggi_casa`, con il campo `testo` già pronto

### 6. `cerca_web` (`B3-SHM-12`) — obbligatorio (V-07 negativo)
- chiama SearXNG (`http://searxng:8080/search?q=…&format=json`)
- **filtra i risultati sull'allow-list**: scarta ogni URL il cui host non sia tra i domini di `fonte WHERE tipo_accesso='web' AND attiva` (ricaricata ogni ~60 s)
- ogni item con `provenienza:"esterna"`, `fonte`, `url`, `consultato_ts`, `fiducia`; scarto sotto `fiducia_min_esterna`; max `max_risultati_esterni`
- nessuna fonte risponde → 200 `{"items":[], "nota": "nessuna fonte ha risposto"}`

### 7. Test (`B3-SHM-10`)
Mantieni i **35 test** esistenti verdi (health, 9×501 → ora cambiano: **aggiornali** ai comportamenti reali, non cancellarli) e aggiungi i test nominati nella spec del piano: `test_vicino_a_sanbao_bar_kb_e_osm`, `test_vicino_a_overpass_timeout_fallback_dichiarato`, `test_vicino_a_scarta_fiducia_sotto_soglia`, `test_vicino_a_max_risultati_esterni`, `test_vicino_a_tipo_non_supportato_422`, `test_approva_proposta_altra_casa_403_da_approvare_in_coda`, `test_proponi_modifica_motivazione_81_char_422`, `test_proponi_modifica_dato_personale_sospetto_422`, `test_registra_richiesta_inviata_altrove_senza_destinazione_422`, `test_biglietto_html_a6_senza_campi_cittadino`, `test_oggi_conteggi_coincidono_con_v_oggi_casa`, `test_cerca_web_scarta_dominio_fuori_allowlist`.

**Overpass e SearXNG vanno mockati** (respx) nei test; i test live sono marcati e skippabili.

## Constraints

- **V3**: ogni risposta di `vicino_a`/`cerca_web` porta il `badge` con provenienza e ora — mai un item senza etichetta.
- **V4**: lo shim **non scrive il dominio**. Le uniche scritture sono `richiesta` (registro) e `proposta` (`proponi_modifica`/`approva_proposta`). `luogo`, `scheda_servizio`, `evento`, `opportunita`, `casa` → **mai**.
- **V5/§12**: filtro anti-PII su `motivazione` **e** `payload`; biglietto senza dati del cittadino; log senza corpo.
- **V6**: nessun testo imperativo generato dallo shim.
- Il contratto `openapi.yaml` è **congelato**: se devi cambiarlo, **fermati e segnala** (è il contratto con Onyx, già registrato come tool `trasi_shim` id 12).
- Non modificare `db/**` (lo schema è di B1) né `deployment/docker-compose.yml` (è di B0). Se serve un cambio, chiedilo.
- Timeout dichiarato: shim 3 s, Overpass 5 s, mai eccezione al chiamante.

## Ownership

`shim/**` (incluso `openapi.yaml` solo per lettura).

## Observable acceptance (prove reali)

1. `pytest shim/tests -q` → **0 failed**, con i test nominati sopra presenti e verdi.
2. `vicino_a?casa=san-bao&tipo=bar` → 200 con **≥1 item `kb`** (bar di Bozzano) **e ≥1 item `esterna`** con badge; con `aperto_adesso=true` i POI senza orari restano, dopo gli aperti noti.
3. Timeout Overpass (mock) → 200 con `fonti_esterne[0].stato="timeout"`, soli item KB.
4. `approva_proposta` su proposta di **altra** Casa → **403** «da approvare in coda»; sulla **propria** → 200.
5. `motivazione` 81 char → 422; `motivazione` con un telefono → 422 `dato_personale_sospetto`.
6. `biglietto` → HTML senza `<input>`/`<form>` e senza parole `cittadino|nome_persona|telefono`; `@page { size: A6` presente.
7. `cerca_web` con risposta SearXNG mockata contenente 2 URL fuori allow-list su 5 → **3 item**.
8. **Container reale**: `docker compose up -d shim` → healthy; da `onyx-api_server-1`: `curl http://shim:8000/healthz` → 200; una chiamata reale a `vicino_a` **senza mock** (Overpass reale) → 200 con item esterni e badge.

Riporta comandi e output reali. Se un criterio è rosso, dillo.

## Nota
Hai attive `fastapi-templates` e `pytest-coverage`. Lo stub attuale è in `shim/app/` (leggilo prima di riscrivere: `contratto.py` contiene gli schemi). Il piano completo è in `plan.md` (§4 B3, §9.1 contratto shim); l'architettura in `docs/trasi-architecture-v1.2.md` (§8 F1/F2/F8, §9.1, §12). In conflitto **vince l'architettura**.
