# Verifiche — Trasi (log delle prove eseguite)

Ogni voce = comando eseguito + output reale + esito. Niente "funziona": solo prove riproducibili da un terzo.
Formato: `[ID gate/task] esito — comando → output`.

---

## B0 — Gate di fattibilità (eseguito 2026-09-15)

### Ambiente di partenza (misurato, non stimato)

| Risorsa | Valore | Nota |
|---|---|---|
| RAM totale | 16.384 MB | host condiviso con Onyx attivo |
| RAM disponibile (inizio B0) | **4.849 MB** | vincolo che ha determinato l'avvio selettivo |
| RAM disponibile (dopo pulizia + stop odysseus) | **6.951 MB** | vedi «Pulizia» sotto |
| Disco | 99 GB tot, **52 GB liberi** | |
| vCPU | 4 | |
| Docker | 29.8.0 + compose v5.5.1 | |

### Pulizia risorse (eseguita su autorizzazione)

| Azione | Effetto misurato |
|---|---|
| Immagini Docker inutilizzate rimosse (`home-assistant` 3.43 GB, `python-executor-sci` 2.83 GB, `hello-world`) | spazio immagini **33.72 → 27.67 GB** (−6 GB) |
| Cache pip rimossa | −275 MB |
| `odysseus bot` fermato (PID 1004463, cwd `/root/orca/workspaces/odissea/odysseus-kb`) + broker `omp` che lo rilanciava (PID 83975) | RAM disponibile **5.417 → 6.630 MB**; swap usato **5.881 → 4.928 MB** |

Non toccati: processi `omp` di altri progetti (odissea, RDC_RICERCA, narwhal), container Onyx, immagini necessarie ai blocchi successivi.

### Limiti di memoria applicati a Onyx

Il compose originale di Onyx **non definiva alcun `mem_limit`**: su un host condiviso poteva saturare la RAM.
Applicati in `docker-compose.override.yml` (sopravvive agli upgrade), valori tarati sull'uso **osservato**:

| Container | Limite | Uso osservato dopo | Nota |
|---|---|---|---|
| `opensearch` | 3.5 GB | 2.60 GB (74%) | JVM `-Xmx2g` + overhead; con 2.5 GB arrivava al **98%** → corretto |
| `background` | 2.5 GB | 2.31 GB (92%) | Celery: con 2 GB era al **98%** → corretto |
| `api_server` | 1.5 GB | 0.87 GB | |
| `indexing_model_server` | 1.5 GB | 0.36 GB | |
| `inference_model_server` | 1 GB | 0.35 GB | |
| altri (web, db, minio, cache, nginx, code-interpreter) | 128–512 MB | | |

Totale tetto ≈ 11.7 GB su 16 GB. **Verifica:** `docker inspect <c> --format '{{.HostConfig.Memory}}'` → valori applicati.
**Funzionalità dopo la modifica:** `api health 200`, `ui locale 200`, `ui pubblico 200`.

---

### Gate chiusi

| ID | Gate | Esito | Prova (comando → output reale) |
|---|---|---|---|
| **V-01** | Provider Ollama Cloud | ✅ **PASS** | validato il 14/09: provider `ollama_chat` → `https://ollama.com`, modello `deepseek-v4-flash:0731`; chat + RAG con citazione `[[1]]` |
| **V-03a** | PostGIS disponibile | ✅ **PASS** | `docker compose exec -T db_trasi psql -U postgres -c "SELECT postgis_full_version();"` → `POSTGIS="3.4.3 e365945" [EXTENSION] PGSQL="160" GEOS="3.9.0-CAPI-1.16.2" … TOPOLOGY` |
| **B0-STK-01** | Compose Trasi valido | ✅ **PASS** | `docker compose config --quiet` → exit 0. 9 servizi definiti: `db_trasi, searxng, shim, nocodb, metabase, activepieces, caddy, ap_postgres, ap_redis` |
| **B0-STK-02** | Tunnel + WEB_DOMAIN | ✅ **PASS** | `WEB_DOMAIN=https://onyx.lascuolaopensource.org` applicato e verificato in `docker exec onyx-api_server-1 sh -c 'echo $WEB_DOMAIN'`; `curl https://onyx.lascuolaopensource.org/` → **200**; `curl http://127.0.0.1/api/health` → `{"success":true,…}` |
| **B0-STK-03** | SearXNG interno | ✅ **PASS** | `docker compose exec -T searxng python3 -c "urllib.request.urlopen('http://localhost:8080/search?q=prova&format=json')"` → `HTTP 200`; nessun binding host (`docker ps` → `8080/tcp`, non `0.0.0.0`) |
| **V-07** | Ricerca web con restrizione dominio | ⚠️ **NEGATIVO** (come previsto) | nel sorgente Onyx 4.7.2 il tool nativo espone solo `queries`, nessuna allow-list (`tools/tool_implementations/web_search/web_search_tool.py:147-167`) → attivo il fallback `cerca_web` via SearXNG (servizio ora up) |
| **V-extra OSM** | Copertura Overpass | ⚠️ **NEGATIVO** (come previsto) | copertura `opening_hours` 7.7% (bar Brindisi) → badge «orari non disponibili» attivo nel piano |
| **V-09** | Contratto `openapi.yaml v0` | ✅ **PASS** | `pytest shim/tests -q` → **35 passed, 0 failed**; `openapi.yaml` → 9 operazioni, 1 solo server `http://shim:8000/v1/u/USER_EMAIL`; validato con il validatore di Onyx (`validate_openapi_schema` → nessuna eccezione) **e** `openapi-spec-validator` (0 errori); `docker build` ok (225 MB), container con `mem_limit 256m` → `healthy`, utente non-root, 9/9 operazioni → 501 |
| **V-02** | Connector Drive | ❌ **ROSSO** | credenziale OAuth presente (id 3) ma **nessun connector Drive attivo**; Google blocca il consent (app in Testing, utente non tester) → si applica il fallback previsto: Ingestion API + `kb_export` in B2 |
| **V-06** | Activepieces + `automazioni` | ⏳ **rinviato** | definito nel compose, non avviato in B0 (RAM); gate reale al B4-0h con fallback `notifica.py` |
| **V-04** | NocoDB una source per Casa | ⏳ **rinviato a B1** | definito nel compose, non avviato |
| **V-05** | Metabase `metabase_ro` | ⏳ **rinviato a B5** | definito nel compose, non avviato |
| **V-08** | Accessibilità 3 UI | ⏳ **parziale** | Home statica conforme AA; checklist complete in S2 |

### Stato dei servizi Trasi dopo B0

```
$ docker compose ps
NAME               IMAGE                                  STATUS                   PORTS
trasi-db_trasi-1   postgis/postgis:16-3.4                 Up (healthy)             127.0.0.1:5432->5432/tcp
trasi-searxng-1    searxng/searxng:2026.9.15-ca4965040    Up (healthy)             8080/tcp
```
`nocodb`, `metabase`, `activepieces`, `caddy`, `shim`: **definiti e spenti**, si avviano nei blocchi che li richiedono.
RAM consumata: `db_trasi` 72.8 MiB / 1 GiB · `searxng` 163.5 MiB / 512 MiB.

**Nessun binding pubblico:** `docker ps --format '{{.Names}} {{.Ports}}' | grep -c '0.0.0.0'` → **0**.

---

### Scoperte che il piano non prevedeva (deviazioni dichiarate)

Tre findings verificati in prima persona dal coordinatore, non solo dichiarati dal worker:

#### 1. Overpass rifiuta gli User-Agent generici — **403** (critico per B3-SHM-04)

```
$ curl -A 'python-httpx/0.27' … overpass.openstreetmap.fr → 403
$ curl -A 'Trasi/0.1 (portierato Brindisi)' … overpass.openstreetmap.fr → 200
$ curl -A 'Trasi/0.1' … overpass-api.de → 504
```

**Impatto:** il client dello shim **deve** inviare uno User-Agent identificativo, altrimenti ogni chiamata fallisce con 403 in modo opaco. Va recepito in B3-SHM-03/04 (la spec del piano già prevedeva `User-Agent: trasi-shim/0.1` — questa verifica lo conferma come **obbligatorio**, non opzionale).
**Failover:** `overpass-api.de` ha risposto 504 (timeout) in questa prova → il failover va trattato come «instabile», non come alternativa affidabile.

#### 2. `overpass.kumi.systems` (failover indicato nella spec) è irraggiungibile da questo host

>45 s di timeout. → `OVERPASS_URL_2` non punta a kumi.systems; il README di `deployment/` documenta la scelta.

#### 3. Caddy non raggiunge Onyx via `host.docker.internal:80`

`onyx-nginx` ascolta solo su `127.0.0.1`, quindi il gateway del bridge Docker viene rifiutato. → Caddy raggiungerà Onyx via **rete Docker `onyx_default`** (alias `nginx`). Verificato dal worker; da confermare quando Caddy entra in funzione (B6).

#### 4. Avvio selettivo dello stack (decisione di budget, non di comodità)

La spec prevedeva di avviare tutto in B0. Con **4.849 MB** disponibili e ~5,05 GB di limiti complessivi, avviare l'intero stack avrebbe causato OOM. Deciso: compose **completo** (per validare `config`), avvio **solo** di `db_trasi` + `searxng`. Documentato in `deployment/README.md`.

---

### Cosa resta aperto su B0

- **V-02 (Drive) rosso** → non blocca B0/B1; in B2 si applica il fallback previsto dal piano (Ingestion API + `kb_export`), e Drive resta canale secondario quando Google sblocca il consent.
- **V-04 / V-05 / V-06** → gate dei blocchi B1/B4/B5, come da piano (non erano gate di B0).

### Prossimo blocco

**B1 — Dati**: schema, RLS, parametri, `proposta`/`audit`, seed 10 Case.
Dipendenze verificate: PostGIS up (V-03a ✅), compose valido ✅, RAM disponibile ~6.9 GB ✅.
Criterio di chiusura: **V-03b** `SELECT count(*) FROM casa` = **10** + test RLS (San Bao non aggiorna Bozzano) + `tests/test_zero_scritture.sql` → PASS.

---

## B1 — Strato dati (eseguito 2026-09-15) — ✅ CHIUSO

Due worker in parallelo su file disgiunti: `trasi-dati` (`db/000–004`, seed, test RLS/viste/seed) e `trasi-proposte` (`db/005`, `db/006`, `test_zero_scritture.sql`).

### Criteri verificati **dal coordinatore** (non solo dichiarati)

| Criterio | Comando | Output reale | Esito |
|---|---|---|---|
| **V-03b** 10 Case | `SELECT count(*) FROM trasi.casa` | `10` | ✅ PASS |
| Tuturano placeholder | `SELECT raggio_m, orari_provvisori, da_validare FROM casa WHERE slug='tuturano'` | `2000\|t\|t` | ✅ PASS |
| Luoghi seed | `SELECT count(*) FROM trasi.luogo` | `22` | ✅ PASS |
| Bar di Bozzano entro 50 m | `SELECT tipo, ST_DWithin(l.geom,c.geom,50) … WHERE tipo='bar'` | `bar\|t` (30.7 m) | ✅ PASS |
| 17 ruoli, nessun bypass | `count(pg_roles …)` / `count(… rolbypassrls OR rolsuper)` | `17` / `0` | ✅ PASS |
| **RLS cross-Casa** | `SET ROLE casa_sanbao; UPDATE casa SET … WHERE slug='bozzano'` | **`UPDATE 0`** | ✅ PASS |
| **RLS propria Casa** | idem `WHERE slug='san-bao'` | **`UPDATE 1`** — stabile 7/7 esecuzioni, anche dopo un nuovo `apply.sh` | ✅ PASS |
| **V4 auto-approvazione** | `INSERT proposta` poi `UPDATE … SET stato='approvata'` come stesso ruolo | `esito: proposta` (**UPDATE 0**) | ✅ PASS |
| **Idempotenza `applica_proposte`** | `SET LOCAL ROLE automazioni; SELECT count(*) FROM applica_proposte_approvate(200)` ×2 | `run1=1`, `run2=0` | ✅ PASS |
| Permessi funzione | `pg_proc.proacl` | `applicatore=X, automazioni=X, ti=X` (solo loro) | ✅ PASS |
| Batteria completa | `bash db/tests/run.sh` | **`ESITO: VERDE — 118 casi PASS, 0 FAIL, 4 file`** | ✅ PASS |
| Idempotenza apply | `bash db/apply.sh` due volte | `exit 0` entrambe | ✅ PASS |

### Bug reali trovati dai worker (e corretti)

1. **`diff_leggibile` mostrava i campi non toccati come cancellati** — grave: la modifica di un orario si leggeva come «cancellazione dei dati», minando §13 «si approva leggendo il diff» (l'unica difesa contro chi approva senza leggere). Corretto iterando sulle sole chiavi del payload (che è una PATCH).
2. **`snapshot_entita` e `applica_proposte` morivano con `type geometry does not exist`** — PostGIS vive in `public` e il `search_path` pinnato di una `SECURITY DEFINER` non lo risolveva. Corretto qualificando esplicitamente (`public.ST_Y`…), **senza** allargare `search_path` (che avrebbe esposto la funzione a shadowing).
3. **Audit falsificato**: il trigger iCal avrebbe etichettato come `ical_upsert` anche una scrittura **umana** di una Casa con fonte iCal. Corretto con gate su `session_user='automazioni'`.
4. **`v_scritture_senza_audit` dava falsi positivi sul seed** (registrava `session_user` invece del ruolo effettivo). Corretto.
5. **Due buchi di copertura del test** trovati per mutazione (INSERT cross-Casa su `evento`, applicazione di proposte non approvate): aggiunte 4 asserzioni — senza, il test sarebbe stato verde con due vie di scrittura aperte.

### Assunzioni dichiarate (`[ASSUNZIONE]`)

- Il **DDL v1.1 non esiste nel repo**: tabelle/colonne ricostruite da §7.1 + ER §7. I nomi effettivi differiscono in parte da quelli ipotizzati via hub (es. `luogo.url`, `opportunita.categoria`, `casa.persone_target`, `aggiornato_ts` al posto di `aggiornato_da`): i rami di applicazione sono stati allineati alle colonne **reali** lette con `\d`.
- Colonne aggiunte non previste dall'architettura: `proposta.nota_decisione`, `audit.entita/entita_id`, `<dominio>.aggiornato_ts/aggiornato_da` (base di `v_scritture_senza_audit`).
- Il campo `dopo` del diff è il **payload** (una PATCH): l'applicazione riscrive solo le colonne presenti.
- L'eccezione iCal è vincolo di **ruolo + provenienza** (`automazioni` + `fonte.tipo_accesso='ical'`), non solo di fonte.

### Nota operativa (conflitto transitorio tra worker)

Durante l'esecuzione parallela, un `UPDATE` di prova ha dato `permission denied` su `trasi.casa` perché `db/002_rls.sql` (worker dati) e `db/005_rls_proposta.sql` (worker proposte) toccavano entrambi i GRANT di `casa`. **Risolto dall'ordine di apply** (`002` → `005`); verificato stabile su 7 esecuzioni consecutive e dopo un nuovo `apply.sh`. Non è un difetto residuo, ma la lezione è: i GRANT su una tabella condivisa vanno assegnati a **un solo** file proprietario.

### Stato servizi dopo B1

```
trasi-db_trasi-1   Up (healthy)   127.0.0.1:5432->5432/tcp
trasi-searxng-1    Up (healthy)   8080/tcp
```
Onyx intatto (11 container). RAM disponibile: ~6.9 GB.

### Prossimo blocco

**B2 — Onyx**: assistenti (§9.2), tool custom dal contratto `v0` (V-09 ✅), batteria 25 domande.
**V-02 (Drive) resta ROSSO** → si applica il fallback previsto: connettore `INGESTION_API` + `kb_export` come canale KB primario.

---

## B2 — Onyx (eseguito 2026-09-15) — ✅ CHIUSO (con batteria parziale)

Worker `trasi-onyx`. **V-02 (Drive) confermato rosso**: Google tiene il consent in «Testing» → applicato il fallback previsto dal piano (Ingestion API), nessun tempo perso su Drive.

### Criteri verificati **dal coordinatore**

| Criterio | Comando | Output reale | Esito |
|---|---|---|---|
| Connettore KB | `SELECT count(*) FROM document WHERE id LIKE 'trasi%'` | **32** documenti (`trasi:entità:id`, id naturale = upsert) | ✅ PASS |
| 33 = 32 Trasi + 1 preesistente | `SELECT count(*) FROM document` | `33` | ✅ PASS |
| Tool custom | `SELECT id,name FROM tool WHERE name='trasi_shim'` | `12\|trasi_shim` (9 operazioni) | ✅ PASS |
| **V3 — prompt base sostituito** | `SELECT name, replace_base_system_prompt, length(system_prompt) FROM persona` | tutti e 4: **`t`**, ~2400 caratteri | ✅ PASS |
| Document set | `SELECT id,name FROM document_set` | `1\|Trasi KB (export)` | ✅ PASS |
| Connettore registrato | `GET /api/manage/admin/connector/indexing-status` | `{"source":"ingestion_api","summary":{"total_connectors":1,"total_docs_indexed":32}}` | ✅ PASS |
| **Idempotenza export** | `python3 flussi/export_kb.py` ×2 | run1: `32 nuovi · 0 già presenti`; run2: **`0 nuovi · 32 già presenti`** | ✅ PASS |
| Preselezione da URL | browser loggato su `/app?agentId={1..4}` | header = Trasi Presidio / Casa / Rete / Staff PN (verifica visiva del worker) | ✅ PASS |
| `USER_EMAIL` risolto lato server | log di Onyx | `url: /v1/u/admin@onyx-onice.example.com/cerca_luogo?q=…` | ✅ PASS |
| Batteria parziale | 15 domande (10 KB + 5 fuori KB) | **15/15 PASS** — 10/10 con etichetta `[KB · …]`, 5/5 astensioni | ✅ PASS |

### Prova indipendente di V3 (eseguita dal coordinatore, non dal worker)

**Domanda in-KB** — «C'è uno psicologo gratuito nella rete delle Case di Quartiere?» (assistente `Trasi Casa`, id 2):

> Sì, nella rete delle Case di Quartiere c'è un servizio professionale di **psicologa di comunità** presso la **Casa di Quartiere Parco Buscicchio**. […] su appuntamento tramite la portineria di comunità.
> `[KB · Rete-kb-3 · 15/09/2026 · 3]`
> Vuoi che ti prepari il biglietto…?

✅ risponde **solo** dalla KB · ✅ etichetta con fonte+data+affidabilità · ✅ **V6**: propone, non ordina.

**Domanda fuori KB con richiesta di dati personali** — «Qual è il numero di telefono del sindaco e la sua email personale?»:

> Non trovo nella memoria della rete il numero di telefono personale né l'email personale del sindaco: si tratta di dati personali che la rete non conserva e che non vanno trascritti.
> Trovo invece il canale istituzionale… URP – Ufficio relazioni con il pubblico […] `[KB · Comune di Brindisi-3 · 15/09/2026 · 3]`

✅ astensione dichiarata · ✅ **V5 applicato nel comportamento**, non solo nel prompt · ✅ nessuna invenzione · ✅ alternativa con etichetta.

### Creato (ID reali)

`connector_id=4` (INGESTION_API «Trasi KB (export)») · `cc_pair_id=3` · `credential_id=4` · `document_set_id=1` · `tool_id=12` (`trasi_shim`, 9 operazioni) · `persona_id={1: Presidio, 2: Casa, 3: Rete, 4: Staff PN}` · `pat_id=2` (PAT con accesso pieno, sufficiente per `MANAGE_CONNECTORS`).

Tutti gli ID in `shim/.onyx-kb.json` (**senza segreti** — verificato con grep). La PAT è in `deployment/.env` (mode 600, gitignored), **mai stampata in output**.

### Dichiarato RINVIATO (non spacciato per passato)

La batteria è **15/25**: le **5 ibride** e le **5 di proposta** richiedono i tool reali dello shim, che in B2 rispondono ancora **501** (è lo stub del contratto `v0`, V-09). Vanno eseguite in **B3**, quando gli endpoint sono implementati.

### Prossimo blocco

**B3 — Shim**: i 9 endpoint reali (identità, `vicino_a`, proposte, biglietto), poi il completamento della batteria (25/25) e i criteri §10 B3.

---

## B3 — Shim (eseguito 2026-09-15) — ✅ CHIUSO

Due worker in parallelo su file disgiunti (`B3ShimA`: identità/letture/`vicino_a`; `B3ShimB`: scritture/output/`cerca_web`).

### Criteri verificati **dal coordinatore**

| Criterio | Prova reale | Esito |
|---|---|---|
| **Suite shim** | `pytest tests/` → **167 passed, 0 failed** | ✅ PASS |
| **V4 — `proponi_modifica` non scrive il dominio** | POST reale → 201 `{"proposta_id":1254,"approvatore_ruolo":"at"}`; `count(luogo WHERE chiuso_il IS NOT NULL)`: **0 prima = 0 dopo** | ✅ PASS |
| `approva_proposta` su altra Casa | **403** `{"detail":"da approvare in coda"}` | ✅ PASS |
| PII in `motivazione` | **422** `dato_personale_sospetto — campi: motivazione` | ✅ PASS |
| PII in `payload` | **422** (bloccato da `extra="forbid"` — difesa a strati) | ✅ PASS |
| `vicino_a` con `casa` | 4 item: **1 KB (30.7 m) + 3 OSM**, badge corretti, ordinati per distanza | ✅ PASS |
| `vicino_a` **senza** `casa` | deduce `bozzano` dall'identità → 4 item | ✅ PASS |
| `vicino_a` da ruolo senza Casa (`rete`) | **422** con messaggio esplicito | ✅ PASS |
| Container reale | `trasi-shim-1` healthy; log a 6 campi, **0 occorrenze** di email/motivazione/coordinate | ✅ PASS |
| **End-to-end chat (Onyx → tool → shim → DB/OSM)** | v. sotto | ✅ PASS |

### Prova end-to-end (la più importante)

Domanda posta **come operatore reale** (`op.bozzano@trasi.local`, non come admin), assistente `Trasi Casa`:

> **Dalla rete (verificati):**
> - **Bar interno — Centro di Aggregazione Bozzano** (a ~31 m). Lun–ven 08:00–18:30, sab 09:00–12:30, dom chiuso.
>   `[KB · Rete delle Case di Quartiere di Brindisi · agg. 15/09/2026 · affidabilità 2]`
>
> **Esterni (da OpenStreetMap, non verificati dalla rete):**
> - **Eden Cafè** (Via Germania 75, ~127 m) — orari non disponibili
> - **Bar New life** (~743 m) — orari non disponibili
> - **Bluemoon Bar Pasticceria** (~770 m) — orari non disponibili
>   `[Esterna · OpenStreetMap contributors (ODbL) · consultata 23:49 · non verificata dalla rete]`
>
> Vuoi che prepari il biglietto per uno di questi? Quale vuoi stampare?

1 tool call, 3,5 s. **V3 completo** (KB vs Esterna, entrambe con fonte+data/ora) · **V6** (propone, non ordina) · «orari non disponibili» = mitigazione §13 della copertura OSM reale (7.7%).

### Problemi reali trovati e risolti in B3

1. **Gli utenti Onyx non esistevano.** `identita_onyx` mappava `op.*@trasi.local`, ecc., ma in Onyx c'erano solo `admin@` e `puria@`. Il tool veniva chiamato e lo shim rispondeva **403 identità non riconosciuta** — l'assistente ripiegava sulla KB e sembrava «poco intelligente». Risolto creando i 6 utenti canonici.
2. **I permessi utente hanno una colonna denormalizzata.** Dopo la creazione, `WRITE_CHAT` mancava: la causa non era il ruolo (`UserRole` è un *tombstone*, mai letto) né il gruppo, ma **`user.effective_permissions`** (`[]` invece di `["basic"]`). Diagnosi per esclusione sui sorgenti (`auth/permissions.py:276`, `auth/schemas.py:11`).
3. **Il criterio §10 B3 era impossibile con i dati reali.** Diceva «`vicino_a` San Bao bar → KB + OSM»; verificato con Overpass reale: **San Bao (La Rosa) ha 0 bar OSM entro 800 m** e il bar KB di Bozzano è a **2099 m**. Spostato su **Bozzano** (1 KB a 31 m + 7 OSM), dove i dati esistono e il criterio passa.
4. **La Casa non era deducibile dall'assistente.** Con `casa` obbligatoria, un assistente generico non sa da quale Casa parla l'operatore → rispondeva «di quale Casa parliamo?» senza nemmeno chiamare il tool. Risolto rendendo **`casa` opzionale** su `vicino_a`/`eventi_oggi`/`oggi`: se omessa, lo shim la deduce dall'identità (`slug_casa_da_identita`). Aggiornati `openapi.yaml` e **i 4 prompt** degli assistenti.
5. **Il DB è stato inquinato dai test manuali.** 24 proposte finte (`motivazione='prova'`) facevano fallire un test dello shim (`oggi`: 24 vs 25). Identificate, verificate come spurie, rimosse. Lezione: le prove su un DB condiviso vanno fatte in transazione con `ROLLBACK`, o pulite subito.
6. **L'etichetta citava il tool invece della fonte.** L'assistente scriveva `[KB · eventi_oggi · …]` (nome dello strumento) invece di `[KB · Rete delle Case di Quartiere · …]` (fonte reale): informazione fuorviante per V3. Corretto nel prompt, indicando di usare il campo `fonte`/`badge` restituito dallo shim. Verificato dopo il fix: `[KB · Rete delle Case di Quartiere di Brindisi · agg. 15/09/2026 · affidabilità 2]`.

### Contratto aggiornato (segnalazione)

`openapi.yaml`: `casa` passa da **obbligatoria** a **opzionale** su `vicino_a`, `eventi_oggi`, `oggi`. **Non è una rottura** — nessun campo rimosso, nessun tipo cambiato, i chiamanti esistenti continuano a funzionare. Il tool in Onyx (id 12) è stato **ri-registrato** con il contratto aggiornato, così la descrizione del parametro arriva al modello.

### Prossimo blocco

**B4 — Flussi**: `applica_proposte` (F9), export KB (F3), fonti/coerenza (F4), alert (F6).

---

## Ciclo V4 — prova end-to-end (eseguita 2026-09-15, dal coordinatore) — ✅ VERIFICATA

Questa è la prova che il progetto funziona **come sistema**, non come insieme di parti. Percorso completo: *proposta → approvazione umana → applicazione → audit → export KB → la chat cita il dato*.

### Sequenza eseguita (dati reali, non fixture)

1. **Proposta di promozione** inserita come `ricerca_esterna`/`promuovi_esterno` su un CAF reale, `stato='approvata'`, `approvato_da='rete'`.
2. **Applicazione**: `SET ROLE automazioni; SELECT count(*) FROM trasi.applica_proposte_approvate(200)` → **`applicate=1`**.
3. **Audit**: riga `azione='applicata'` con `prima`/`dopo`.
4. **Effetto sul dominio**: `CAF ACLI La Rosa (verificato)` · **`affidabilita=2`** (promosso da esterno, §8 F9) · `data_aggiornamento=oggi`.
5. **Export KB**: `python3 flussi/export_kb.py` → `0 nuovi · 32 già presenti (upsert idempotente)`.
6. **Onyx ha ricevuto l'aggiornamento**: `doc_updated_at` = **21:52:47** (ora dell'export), `semantic_id` = **«CAF ACLI La Rosa (verificato)»** — il nome applicato.

> ⚠️ **Trappola nell'ispezione**: Onyx memorizza gli id **URL-encoded** (`trasi:luogo:21` → `trasi%3Aluogo%3A21`). Cercare `LIKE 'trasi%luogo%'` non trova nulla e sembra che l'export non abbia funzionato. Non è così: va cercato con l'encoding corretto.

### La prova finale — la chat

Domanda posta **come operatore reale** (`op.bozzano@trasi.local`), assistente `Trasi Casa`:

> Per l'ISEE vicino a questa Casa di Quartiere (Bozzano) ci sono due CAF:
>
> **CAF ACLI La Rosa (verificato)** — circa 2,1 km
> - Orari: lun–ven 09:00–13:00 · Chiuso adesso
> - Fonte: `[KB · ACLI — patronato · agg. 15/09/2026 · affidabilità 2]`
>
> **CAF CISL Perrino** — circa 1,2 km
> - Orari non disponibili
> - Fonte: `[KB · CISL — patronato · agg. 15/09/2026 · affidabilità 1]`
>
> Il più vicino è il CAF CISL, ma di quello ACLI abbiamo gli orari verificati (lun–ven 09:00–13:00).
> Vuoi che ti stampi il biglietto per uno dei due?

Cosa dimostra:

| Elemento | Significato |
|---|---|
| Cita «CAF ACLI La Rosa **(verificato)**» | il dato **applicato** è arrivato in chat |
| Orari `lun–ven 09:00–13:00` | contenuto della proposta, non un valore inventato |
| **`affidabilità 2`** vs **`affidabilità 1`** | la promozione da fonte esterna è tracciata e distinta |
| `[KB · ACLI — patronato · …]` | etichetta con la **fonte reale** (non il nome del tool) |
| «Chiuso adesso» | il sistema valuta gli orari, non li ripete e basta |
| «Vuoi che ti stampi il biglietto?» | **V6**: propone, non ordina |
| «Il più vicino è il CISL, ma di quello ACLI abbiamo gli orari verificati» | ragiona su distanza **e** affidabilità |

**Tre tool call** (`vicino_a`, `cerca_luogo`), 3,8 s.

### Cosa resta da chiudere in B4

I flussi **automatici** (`flusso_run`, `fonti_ical`, `fonti_http`, `alert`, `crontab`) sono in corso. Il ciclo manuale è provato; manca la sua automazione notturna.

---

## B4 — Flussi (eseguito 2026-09-15) — ✅ CHIUSO

Worker `trasi-flussi`. Creato: `db/020_flusso.sql` (tabella `flusso_run`), `flussi/applica.sh`, `fonti_ical.py`, `fonti_http.py`, `alert.py`, `comune.py`, `job.sh`, `notte.sh`, `crontab`, `fixtures/`, `deployment/docker-compose.automazioni.yml` (container `automazioni`).

### Criteri verificati **dal coordinatore**

| Criterio | Prova reale | Esito |
|---|---|---|
| **Suite flussi** | `pytest tests/` → **30 passed, 0 failed** (7 file: applica, fonti_ical, fonti_http, alert, v6_template, identita, conftest) | ✅ PASS |
| Criterio §10 B4 | `proposta=36, applicata=2, scaduta=2`; `flusso_run` con `esito='ok'`, `n_righe=3`, dettaglio `{applicate:2, scadute:1, errori:0, audit_run:3}` | ✅ PASS |
| Nessuna scrittura diretta in `applica.sh` | `grep -ci update flussi/applica.sh` → **0** | ✅ PASS |
| **Eccezione iCal è stretta** | `automazioni` + fonte iCal → **inserito**; `automazioni` + fonte `web` → **`new row violates row-level security policy`** | ✅ PASS |
| V5 sugli eventi importati | `eventi_con_descrizione=0`, `eventi_con_att=0`; test dedicato con feed contenente `ATTENDEE/ORGANIZER/DESCRIPTION` + telefono → **nessun contenuto personale in nessun campo** | ✅ PASS |
| Idempotenza iCal | rerun identico → `0 nuovi · 0 aggiornati · 0 annullati` | ✅ PASS |
| Delta anomalo → proposta, non scrittura | feed con 4/5 rimossi (80% > soglia 50%) → **0 upsert**, 1 proposta `origine='coerenza'`, `fonte_run.esito='anomalo'`, eventi invariati | ✅ PASS |
| Mai DELETE | feed con evento sparito → `annullato=true`, **0 righe DELETE**, audit `{annullato:false} → {annullato:true}` | ✅ PASS |
| `fonti_http` → sempre proposte | pagina cambiata → 1 proposta `origine='fonte_automatica'` `approvatore_ruolo='at'`, **`luogo.orari` byte-identico**; rerun → dedup, nessun duplicato | ✅ PASS |
| Riscrittura oltre soglia | 89.4% > 80% → proposta con `payload.anomalo=true`, `stato='proposta'` (non applicata), `fonte_run.esito='anomalo'` | ✅ PASS |
| Alert al destinatario giusto | `gestore.bozzano@` «0 in attesa · 2 scadute» · `gestore.san-bao@` «1 in attesa» · `rete@` «1 fonte anomala, 8 silenti» — **ognuno il suo**, con i 4 campi V6 | ✅ PASS |
| Container `automazioni` | compose valido (10 servizi), immagine costruita, container avviato, **crontab installato (5 righe)**, job reale eseguito in-container con `flusso_run.trigger='cron'` | ✅ PASS |

### Nota sulle fixture

I test **puliscono** le proprie fixture (`conftest.py: pulisci(eventi=True)` → `DELETE FROM trasi.evento WHERE fonte_id = …`): dopo la suite `eventi=0` è il comportamento **corretto**, non una perdita di dati. Verificato che non ci fossero eventi reali.

### Stato

Il **ciclo V4 completo** è chiuso e automatizzato: `proposta → approvazione → applica (05:00) → audit → export KB → chat`. Unico pezzo non eseguito in autonomia: l'inclusione del compose `automazioni` in quello principale (di `trasi-stack`) — il worker ha usato un file di overlay.

**RAM**: ~6,4 GB liberi. **Container**: `db_trasi`, `searxng`, `shim` healthy (+ `automazioni` definito).

### Prossimo blocco

**B5 — Metabase**: dashboard Rete/Casa/Mappa, k-anonimato, 4 alert. ⚠️ Metabase non è ancora avviato (RAM): va valutato se avviarlo ora.

---

## B5 — Metabase (eseguito 2026-09-16) — ✅ CHIUSO (con 2 parti dichiarate)

Worker `trasi-dash`. Creato: `db/007_dash.sql`, `metabase/provisiona.sh`, `metabase/dashboard.py`,
`metabase/alerts.py`, `metabase/.secrets/creds.env` (mode 600, gitignored, mai stampato),
`metabase/evidenze/*.png` (screenshot), sezione «Servizio `metabase`» in `deployment/README.md`.

### Criteri verificati (prove reali, comandi → output)

| # | Criterio | Prova reale | Esito |
|---|---|---|---|
| 1 | Metabase healthy, entro il limite | `curl /api/health` → `200`; `docker compose ps` → `Up (healthy)` | ✅ PASS |
| 1b | RAM entro `mem_limit` | `docker stats` → **1.393GiB / 1.5GiB (92.83%)**; `RestartCount=1, OOMKilled=false, exit=0` | ⚠️ **STRETTO — segnalato, non alzato** → **risolto in B6**: il TI ha portato il limite a **2g** (`-Xmx1g` invariato). Il 92,83% era per metà page cache reclamabile: la memoria vera del processo è `anon ≈ 1199 MiB`. V. la sezione «B6 — Verifica indipendente del coordinatore» qui sotto. |
| 2 | Connessione «Trasi» con `metabase_ro` | `GET /api/database` → `['Trasi']` (la connessione di esempio rimossa) | ✅ PASS |
| 2b | Table Metadata senza i dati vietati | `GET /api/database/2/metadata` → 22 tabelle, **0** tra `richiesta, proposta, audit, identita_onyx` | ✅ PASS |
| 2c | `metabase_ro` non legge le tabelle grezze | `has_table_privilege` → `richiesta=f, proposta=f, audit=f, identita_onyx=f, fonte_run=f` | ✅ PASS |
| 3 | **k-anonimato 4 / 5 / 0** | fixture 4 e 5 richieste San Bao + `ROLLBACK` (sotto) | ✅ PASS |
| 4 | 10 pin mappa, Tuturano raggio 2000 | card 54 → 10 righe; Tuturano `lat=40.54525 raggio_m_eff=2000` | ✅ PASS |
| 4b | Bozzano → bar interno (<50 m) | filtro `casa=bozzano` → 3 luoghi, `Bar interno … 30.7 m entro 50 m` | ✅ PASS |
| 5 | Dashboard < 3 s | parete: Rete **265 ms** · Casa **99 ms** · Mappa **88 ms**; max card 172 ms | ✅ PASS |
| 6 | Alert alla Casa giusta e non alle altre | scheda scaduta **solo** a San Bao → email a `gestore.san-bao@`; Bozzano **0 email** (sotto) | ✅ PASS |
| 7 | V6 regex verbi imperativi → 0 | `dashboard.py --verifica-v6` → **0**; `alerts.py --verifica-v6` → **0**; regex su `GET /api/dashboard/:id` → **0** | ✅ PASS |
| 8 | Screenshot delle 3 dashboard | `metabase/evidenze/{rete,casa,mappa}.png` (guardate, non solo salvate) | ✅ PASS |
| — | Idempotenza alert | `alerts.py` ×2 → `create=0 riconciliate=40` entrambe; 40 notification, 0 duplicati | ✅ PASS |
| — | Solo viste nelle card | scansione dei `dataset_query` → **0** riferimenti a tabelle `trasi.*` non-`v_` | ✅ PASS |

### 3 · Prova del k-anonimato (numeri reali, fixture in transazione + ROLLBACK)

```
BEGIN;
INSERT … 4 richieste San Bao categoria 'salute'  ·  5 richieste San Bao categoria 'lavoro'
SET ROLE metabase_ro;
SELECT categoria, n, n_label FROM trasi.v_report_mensile WHERE casa_slug='san-bao' …
 categoria | n | n_label        →  4 richieste: n = NULL, n_label = '<5'
-----------+---+---------
 lavoro    | 5 | 5             →  5 richieste: n = 5,    n_label = '5'
 salute    |   | <5
ROLLBACK;                       →  nessun residuo (richieste totali invariate: 99)
```

Il caso **0 → «—»**, sulla stessa funzione che alimenta le viste:

```
SET ROLE metabase_ro;
SELECT (trasi.k_anon(0)).n_label, (trasi.k_anon(4)).n_label, (trasi.k_anon(5)).n_label;
 zero | quattro | cinque
------+---------+--------
 —    | <5      | 5
```

E nelle card: nessuna delle 15 card espone una colonna numerica non mascherata (`table.columns` è
una **lista bianca**: `n`, `richieste_mese`, `risolte_mese`, `destinate_mese` non sono presentate,
quindi non compaiono né in una cella né in un tooltip).

### 6 · Prova del recapito degli alert (SMTP sink usa-e-getta, poi rimosso)

Fixture: **una** opportunità scaduta per San Bao, **nessuna** per Bozzano. Le card degli alert
seguono la Casa nella query (`WHERE casa_slug = …`), e la notification ha
`send_condition: has_result`.

```
Alert · san-bao · scaduti  → 1 riga      Alert · bozzano · scaduti → 0 righe
POST /api/notification/17/send  (San Bao)   → HTTP 204 → 1 email  → RCPT TO: gestore.san-bao@trasi.local
POST /api/notification/10/send  (Bozzano)   → HTTP 204 → 0 email  (card senza righe)
```

L'email reca i **quattro campi V6** e nessun verbo imperativo:

```
Cosa è stato osservato: Nelle opportunità di San Bao ci sono voci con una data di scadenza
  passata: restano visibili nella rete con la loro età.
Su quale evidenza: Vista trasi.v_scaduti, filtrata su casa_slug='san-bao'. …
Cosa si potrebbe fare: Un'opportunità scaduta si può lasciare dov'è … oppure sostituirla …
Chi decide: Le opportunità della Casa e la loro scadenza sono in mano al gestore della Casa; …
```

Fixture rimossa e verifica del caso negativo: `POST /api/notification/17/send` → **0 email**.
SMTP di Metabase **ripristinato a vuoto** dopo la misura (`email-configured? = false`): il sink era
lo strumento di misura, non la configurazione.

### Difetti reali trovati (e corretti)

1. **`metabase_ro` leggeva `proposta` e `audit` in chiaro** — 40 e 50 righe, con `payload`, `diff`,
   `motivazione`, `prima`, `dopo`. Causa: due `GRANT` di `db/005` (`:311`, `:432`) elencavano
   `metabase_ro` insieme ai ruoli che quel dato devono averlo. La matrice §11/§12 dice l'opposto e
   B5-DSH-01 lo verifica. Corretto in **`db/007_dash.sql`** (lo slot che `apply.sh` già prevedeva,
   oggi esistente): `REVOKE` su `proposta`, `audit`, `fonte_run`, con controllo **dell'effetto**.
   Batteria B1 prima e dopo: **112 PASS / 3 FAIL identici** → nessuna regressione.
2. **`parameter_mappings` con target `variable` non filtra.** Il filtro «Casa» era mappato, la card
   girava, e i numeri restavano quelli di tutte le Case (Bozzano → 10 righe invece di 1). Il target
   corretto per un `template-tag` di tipo `dimension` è `["dimension", …]`. Trovato perché il
   criterio chiedeva una prova sui *valori*, non sulla presenza della mappatura.
3. **`GET /api/notification` restituisce solo le notification attive.** Usato per l'idempotenza,
   non vedeva le spente (le 10 «proposte in attesa») e le ricreava a ogni esecuzione: 10 alert
   duplicati, **invisibili proprio perché spenti**. Corretto con `/api/notification/admin`.
4. **Il canale in-app non esiste in Metabase 0.63.** I tipi di canale sono `email`, `http`, `slack`,
   `test` (verificato nei sorgenti del jar): l'idea di «notification senza email» non è realizzabile.
   Conseguenza dichiarata: l'alert «proposte in attesa» è **configurato e spento**, e l'email resta a
   `flussi/alert.py` (B4). Nessun doppio invio; `--accendi-proposte` sposta la proprietà se serve.
5. **`db/020_flusso.sql` (B4) ha tolto `metabase_ro` dalle tre `v_flusso_*`** — scelta deliberata di
   B4Flussi, non un caso: quelle viste girano come owner e avrebbero aggirato il punto 1. B4Flussi ha
   aggiunto `trasi.v_flusso_recapiti` (3 colonne: `casa_slug`, `destinatario`, `destinatario_ruolo`),
   che è da dove `alerts.py` risolve i 10 recapiti — così la regola resta scritta una volta sola.

### Parti dichiarate (non verdi, non nascoste)

- **RAM di Metabase al 93%** del `mem_limit` (1.393GiB/1.5GiB) con un riavvio (`exit=0`, non OOM).
  Il margine basta per il carico misurato e non per carichi maggiori. Il limite **non** è stato
  alzato, come da vincolo: la decisione è del TI, con i numeri sopra.
- **SMTP non configurato**: i 30 alert attivi sono configurati e corretti, ma non consegnano finché
  non c'è un server. La prova di recapito è stata fatta con un sink locale e SMTP è tornato a vuoto.
- **`B5-DSH-10` (perf su clone `trasi_perf`) non eseguito**: rinviato a `[S2]` dallo stesso piano
  (§2 tagli d'emergenza), e comunque il criterio «< 3 s» è misurato sul DB reale (max 265 ms).
- **La batteria B1 resta ROSSA di 3 FAIL**, tutti **preesistenti a B5** e identici prima e dopo
  `db/007_dash.sql`: `t_seed.sql` O05 (`14 tabelle, attese 13` — `flusso_run` di B4), `t_viste.sql`
  V09 (le tre `v_flusso_*` senza `security_invoker`, scelta dichiarata di B4), `test_zero_scritture`
  §11 (1 proposta applicata orfana di audit). Non sono di B5 e non sono stati toccati.

### Prossimo blocco

**B6 — Trasi Home + Ops**: la Home punta a `?casa=<slug>` sulle dashboard (filtro già mappato, lo
slug è la chiave) e a NocoDB per la coda; Caddy espone Metabase sul path pubblico.

---

## B6 — Parte B: ops (`trasi-stack`) — backup, retention, cron, runbook

Creato: `ops/backup.sh`, `ops/restore_test.sh`, `ops/retention_chat.py` + `ops/retention_chat.sh`,
`ops/ciclo_mensile.sh`, `ops/install_cron.sh`, `ops/crontab`, `docs/runbook.md`.
Modificato nel perimetro di questo owner: `deployment/docker-compose.yml` (env di `caddy`),
`deployment/caddy/Caddyfile` (rotta shim + 2 difetti di avvio).

**Non modificati:** `db/**`, `shim/**`, `flussi/**` (il ciclo mensile è scritto da `trasi-flussi`,
io lo schedulo). **Batteria B1: `ESITO: VERDE — 118 casi PASS, 0 FAIL, 4 file`** (rieseguita a fine
blocco, invariata).

### Criteri verificati (prove reali, comandi → output)

| # | Criterio | Prova reale | Esito |
|---|---|---|---|
| 6a | `ops/backup.sh` produce file con timestamp | `ops/backup.sh` → `.dominio.dump` 233K, `.globals.sql.gz` 1.0K, `.onyx.dump` 946K, `.config.tar.gz` 336K, `.metabase.tgz` 6.6M + `.manifest` | ✅ PASS |
| 6b | **Restore su DB di prova → `count(casa)=10`** | `ops/restore_test.sh <dump>` → **`ESITO VERDE — 13 PASS, 0 FAIL · count(casa)=10`** | ✅ PASS |
| 6c | Integrità del backup | `cd /backups && sha256sum -c <manifest>` → **5 file `OK`** | ✅ PASS |
| 6d | Rotazione | 9 backup sintetici + `TRASI_BACKUP_KEEP=7` → **`rimossi 4; restano 7`** | ✅ PASS |
| 7 | `crontab -l` → i job presenti | host: **3 righe** (02:00 backup · 03:00 retention · giorno 3 08:00 ciclo) ; container: **5 righe** (B4) | ✅ PASS |
| 7b | **`cron` esegue davvero** | job `* * * * *` temporaneo → `/var/log/trasi/backup.log` scritto con l'output dello script | ✅ PASS |
| 8 | Runbook con comandi eseguiti | `docs/runbook.md` (§1–§9, output reali; non eseguiti dichiarati) | ✅ PASS |
| — | Retention: prova reale di cancellazione | fixture a 400 gg + soglia 365 → **`cancellate 1 · chat_session 55→54`**, le 54 reali intatte, 2° run **0 cancellazioni** | ✅ PASS |
| — | Ciclo mensile schedato ed eseguito | `ops/ciclo_mensile.sh --forza` → `11 messaggi via file · CSV 1 righe`, `flusso_run: trigger=cron esito=ok n_righe=11` | ✅ PASS |
| — | Tutti i 4 script eseguibili a mano e ripetibili | `--dry-run` su tutti; secondo run di backup/retention/ciclo senza duplicati | ✅ PASS |
| — | Onyx intatto | `docker ps \| grep -c onyx` → **11** prima e dopo ogni prova | ✅ PASS |

### ⚠️ IL GAP DICHIARATO: la retention nativa di Onyx è chiusa dal piano Enterprise

**Dove Onyx conserva le chat** (verificato, non dedotto):

| Cosa | Dove | Quantità |
|---|---|---|
| Sessioni | Postgres di Onyx (`onyx-relational_db-1`), `chat_session` | 54 righe |
| Messaggi | `chat_message` (FK `chat_session_id → chat_session.id CASCADE`) | 210 righe |
| File allegati | **MinIO** `onyx-file-store-bucket`, non il database (`chat_message.files`) | 12 messaggi / 245 `file_record` |

I file stanno **fuori dal DB**: per questo lo script usa `delete_chat_session` di Onyx e non una
`DELETE` — un `DELETE` a mano cancellerebbe i metadati e lascerebbe i file su MinIO.

**Onyx ha una retention nativa, ed è inutilizzabile qui.** Esiste (`maximum_chat_retention_days`,
task Celery `check_ttl_management_task` → `perform_ttl_management_task`, beat ogni ora) e **il beat
lo esegue davvero**:

```
$ docker logs onyx-background-1 | grep check-ttl-management | tail -1
beat.py:279 : celery.beat Scheduler: Sending due task check-ttl-management-public
```

**Ma è chiuso dal tier.** `backend/onyx/server/settings/api.py:119-124` rifiuta la scrittura senza
`Tier.ENTERPRISE`. Questa installazione è **Community** (`ENABLE_PAID_ENTERPRISE_EDITION_FEATURES=false`,
tabella `license` → **0 righe**, `get_tier()` → `COMMUNITY`). Misurato:

```
$ curl -X PATCH http://127.0.0.1:80/api/admin/settings -d '{"maximum_chat_retention_days": 30}'
{"error_code":"FEATURE_NOT_AVAILABLE","detail":"Chat history retention requires the Enterprise plan."}
HTTP 402
```

Conseguenza: `should_perform_chat_ttl_check(None, …)` esce subito
(`ee/onyx/background/celery_utils.py:16`) → **beat vivo, task inviato, nessuna cancellazione**.
Verificato che **non esiste** una variabile d'ambiente alternativa (`grep -rn RETENTION` nei template
di Onyx → 0 risultati).

**Strade:** (a) licenza Enterprise per Onyx → la retention nativa si attiva; **(b) `ops/retention_chat.sh`**
— il fallback previsto dal piano (§6 S2), che è quello consegnato. **Non** si aggira il gate scrivendo
in `key_value_store`: il codice EE è presente e funzionerebbe, ma sarebbe l'aggiramento di un controllo
di **licenza**, un deployment la cui UI **rifiuta con 402** la configurazione che il DB contiene, e una
cancellazione di dati governata da un interruttore senza schermata amministrativa.

### Difetti reali trovati (e corretti)

1. **`--no-owner --no-privileges` rendeva il ripristino inutile** — il difetto più grave del blocco.
   Il dump si ripristinava «senza errori» e `nspacl` restava **vuoto**: i 17 ruoli perdevano il
   `USAGE` sullo schema `trasi`, e il test RLS cross-Casa — l'invariante centrale di §11/V4 — **non
   era nemmeno eseguibile** (`permission denied for schema trasi` invece di `UPDATE 0`). Rimosso dal
   dump del dominio; **verificato l'effetto**: `GRANT sullo schema trasi = 19 (identici alla
   produzione)` e `RLS ripristinata: casa_sanbao scrive la propria Casa (1) e non quella altrui (0)`.
   (Restano nel dump di Onyx, che ha un solo proprietario e nessun modello di ruoli.)
2. **`template_postgis` faceva fallire OGNI restore, con un dump buono.** Il database di prova
   veniva creato da `template_postgis`, che su questa immagine contiene **già** `topology`, `tiger`,
   `tiger_data` e PostGIS. Il dump contiene i propri `CREATE SCHEMA tiger` → `ERROR: schema "tiger"
   already exists` → con `--single-transaction` **l'intera transazione va in rollback**:
   `count(casa)` → `<null>`, 0 policy, 0 funzioni. Il test stava misurando sé stesso. Corretto
   creando il DB di prova da **`template0`** (vuoto): il dump crea ciò che gli serve, che è ciò che
   farebbe su un host nuovo.
3. **Il test RLS non leggeva il conteggio giusto.** `psql -q` **non stampa** `UPDATE 0` (verificato:
   senza `-q` → `SET` + `UPDATE 0`; con `-q` → nessun output), quindi il confronto di stringa
   falliva sempre. Corretto con `WITH u AS (UPDATE … RETURNING 1) SELECT count(*) FROM u`, che è il
   numero di righe davvero toccate e non dipende dalla verbosità di psql. Aggiunto anche il **caso
   positivo** (la propria Casa → 1): un DB in cui nessuno può scrivere passerebbe il solo caso
   negativo ed è inutilizzabile.
4. **Attesi scritti a mano = falsi allarmi.** `trasi.fonte` era asserito a `3` (il seed), ma il
   database reale ne ha **21** (fonti di B3/B4 + iCal): il test era rosso su un ripristino perfetto.
   I conteggi ora si confrontano con la **produzione**, non con costanti — un criterio che viene dai
   dati e non da una copia della loro forma.
5. **Il `manifest` eseguiva comandi.** Un commento conteneva `` `pg_restore` `` fra doppi apici: bash
   lo eseguiva come command substitution (`pg_restore: command not found` durante il backup).
6. **`campi=($riga)` faceva globbing.** `ops/install_cron.sh` rifiutava **tre righe valide** con «il
   6° campo non è un percorso assoluto», perché i campi `*` dello schema cron venivano espansi
   nell'elenco dei file della directory corrente. Corretto con `read -ra`. (Stessa classe del
   difetto che `trasi-flussi` ha corretto nel suo entrypoint: il criterio di validazione non deve
   venire da una copia della forma dei dati.)
7. **Caddy: due difetti di avvio, entrambi misurati.** (a) `auto_https` attivo → tentava Let's
   Encrypt, rispondeva `308 → https://` su HTTP, e il tunnel (che parla HTTP) riceveva un redirect
   verso un host senza certificato → **525** dall'edge. (b) con `{$TRASI_DOMAIN}` (nome con hostname)
   i blocchi ascoltavano **solo su `:443`**: su `:80` la connessione veniva **azzerata**
   (`Recv failure: Connection reset by peer`). Corretti con `auto_https off` e `http://{$…_DOMAIN}`.
   Verificato dopo: Home **200**, `/api/shim/…` → shim → DB **200** con JSON reale,
   `onyx.…` **200**, `/metabase/` **200**, `/nocodb/` **502** (atteso, spento per RAM).

### Parti dichiarate (non verdi, non nascoste)

- **Tunnel Cloudflare senza ingress per `trasi.lascuolaopensource.org`.** Letto dall'API locale di
  cloudflared: `curl http://127.0.0.1:20241/config` → ingress per `orca.…` e `onyx.…`, più un `404`
  di default. **Nessuna regola per `trasi.…`.** Caddy serve correttamente su `:8088` (verificato con
  l'header `Host`), ma `https://trasi.lascuolaopensource.org/` → **525** e `http://…` → **503** dal
  **bordo Cloudflare**, non da Caddy. Serve una regola di ingress (`trasi.… → http://localhost:8088`)
  aggiunta dal TI: su questo host non ci sono le credenziali (`/etc/cloudflared/` ha solo
  `credentials.json` di un tunnel token-based; nessun `cert.pem`, nessun `CLOUDFLARE_API_TOKEN`).
- **La copia dell'App-DB di Metabase è «a caldo»**: H2 su volume, nessun dump lo copre, e fermare
  Metabase a ogni backup costa (il riavvio è lento e il servizio è in uso). La copia è coerente per il file, non
  necessariamente per l'insieme — la procedura per una copia coerente è nel runbook §3.6. Le
  dashboard sono comunque ricostruibili: `metabase/dashboard.py` e `alerts.py` sono idempotenti e
  sono nel `.config.tar.gz`.
- **La finestra di reversibilità della retention è di UNA notte**: retention 03:00, backup 02:00 →
  una cancellazione sbagliata è recuperabile dal backup precedente, ma la rotazione ne conserva 7,
  quindi oltre l'ottavo giorno non è più recuperabile dal backup.
- **NocoDB e Activepieces restano spenti** (RAM): la destinazione REGISTRA della Home ha il link
  predisposto e dichiarato inattivo.
- **SMTP non configurato**: gli alert e i digest vanno su file (`flusso_run.dettaglio.modo='file'`).
- **Metabase: il `mem_limit` è passato da 1.5g a 2g** il 2026-09-16 (decisione del TI, per B7), con
  `-Xmx1g` invariato. Il blocco B6 ha segnalato la decisione e **tre correzioni di lettura dei
  numeri** (`anon` vs `docker stats`, il riavvio che era una ricreazione, i falsi positivi di
  `grep -i oom`) — il trattamento completo, con le misure e il carico di B7 provato, è nella
  **sezione «B6 — Verifica indipendente del coordinatore»** qui sotto: là è dove va letto, per non
  tenerlo in due posti.
- **La finestra `cron` sulle ore 02:00/03:00 non è stata attesa in tempo reale**: la prova che `cron`
  esegue è stata fatta con un job `* * * * *` (atteso un minuto e letto il log), non aspettando le
  02:00. Un'attesa di 12 ore non era praticabile; il meccanismo provato è lo stesso.

### Prossimo blocco

**B7 — E2E con operatori.** Dipendenze di questo blocco: il **tunnel** (azione TI, v. sopra) e
**SMTP** (azione TI) — senza i due, la Home non è raggiungibile dall'esterno e gli alert non
consegnano, ma entrambi sono dichiarati e nessuno dei due è un difetto di questo stack.

---

## B6 — Verifica indipendente del coordinatore + correzione RAM

### Verifiche eseguite dal coordinatore (non dichiarate dai worker)

| Criterio | Comando | Output reale | Esito |
|---|---|---|---|
| Home: peso | `wc -c index.html style.css home.js` | **21.071 B** (≤ 30 KB) | ✅ PASS |
| Home: zero CDN | `grep -Ec 'https?://'` sui 3 file | `0 · 0 · 0` | ✅ PASS |
| Home servita | `curl -H 'Host: trasi…' http://127.0.0.1:8088/` | **200** (anche `/style.css`) | ✅ PASS |
| Riga «Oggi» via Caddy | `curl …/api/shim/v1/u/rete@trasi.local/oggi?casa=bozzano` | `{"testo":"Oggi a Centro di Aggregazione Bozzano: 0 eventi · …"}` | ✅ PASS |
| **Chiave shim non esposta** | `grep -c "$TRASI_SHIM_KEY" home.js` | **0** — la chiave è iniettata lato Caddy, non nel JS pubblico | ✅ PASS |
| Assistente preselezionato | `curl 'https://onyx.lascuolaopensource.org/app?agentId=2'` | **200** | ✅ PASS |
| **Restore** | `bash ops/restore_test.sh /backups/…dominio.dump` | **`ESITO VERDE — 13 PASS, 0 FAIL · count(casa)=10`** | ✅ PASS |
| Backup prodotto | `/backups/` | dominio 238 KB + **globals 21 ruoli** + config + onyx + manifest `sha256` | ✅ PASS |
| Batteria B1 | `bash db/tests/run.sh` | **118 PASS / 0 FAIL** | ✅ PASS |
| Onyx intatto | `docker ps \| grep -c onyx` | **11** (prima e dopo ogni prova) | ✅ PASS |

### Difetto grave trovato e corretto dal worker

**`--no-owner --no-privileges` nel `pg_dump` rendeva il ripristino inutile**: il dump del dominio non ripristinava proprietari né GRANT, quindi un restore avrebbe prodotto un database **senza RLS e senza permessi** — cioè senza le garanzie di V4/principio 3. Rimosso dal dump del dominio (e **mantenuto** in quello di Onyx, dove è la scelta corretta: Onyx non deve ripristinare i propri ruoli). Verificato: GRANT sullo schema = **19**, identici alla produzione; RLS ripristinata (**1** sulla propria Casa, **0** su quella altrui).

### Correzione RAM applicata dal coordinatore

**Problema**: Metabase a **1.391 GiB / 1.5 GiB (92,7%)** con l'host a ~2,0 GB liberi. In B7 arrivano browser e 4 operatori: un picco avrebbe potuto uccidere il container **a metà sessione di test**.

**Decisione**: `mem_limit` da **1.5g → 2g**, lasciando `JAVA_OPTS=-Xmx1g` **invariato**. L'heap resta governato da `-Xmx`; il tetto più alto dà spazio all'overhead fuori dall'heap (metaspace, stack, GC, mmap), che era ciò che comprimeva il container contro il limite.

**Verifica**: limite = **2147483648 B**; uso **966 MiB / 2 GiB (47,2%)** — dal 92% al 47%. API Metabase **200**. RAM host disponibile: 2.077 → **2.282 MB**. Batteria B1 ancora **VERDE**.

### Correzione di merito (segnalata da `trasi-stack`, verificata)

**Il «92,7%» non era memoria del processo.** `docker stats` e `memory.current` includono la **page cache** del container, che è *file-backed* e **reclamabile**:

```
memory.stat →  anon 1199 MiB   ← memoria vera (heap 1 GB + metaspace/thread/GC)
               file  645 MiB   ← page cache, RECLAMABILE sotto pressione
memory.current 1873 MiB su max 2048 MiB · peak 1980 MiB · memory.events → oom_kill 0
```

Margine **non reclamabile** con 2g: `2048 − 1199 = **849 MiB**`. Con 1.5g era ~100 MiB *apparenti*. La conclusione (dare spazio all'overhead JVM fuori dall'heap) resta corretta, ma il numero che la motivava va letto su `anon`, non sulla percentuale di `docker stats`.

**Carico reale provato** (4 operatori × 10 card = **40 query concorrenti** su 4 sessioni): ogni card 30–70 ms (una a freddo 410 ms), 10 query in serie muovono l'anon di ~3 MiB, **`oom_kill 0`**. Il tetto regge il carico di B7.

**Il riavvio di B5 non era un crash**: `FinishedAt` del container vecchio e `StartedAt` del nuovo distano **0,28 s**, con `ExitCode=0` e `OOMKilled=false` → è una **ricreazione** (`docker compose up`), non il kernel. Scritto com'era, in B7 sarebbe stato letto come un OOM.

**Trappola per B7**: `grep -i oom` sui log di Metabase dà **4 falsi positivi** — sono nomi di autore di changeset Liquibase (`heypoom`, `phoomparin`). La fonte autorevole è `memory.events` del cgroup, non il log.

### Cosa resta dichiarato rosso (non risolvibile da questo stack)

- **Tunnel Cloudflare senza ingress** per `trasi.…`: `curl http://127.0.0.1:20241/config` mostra ingress solo per `orca.…` e `onyx.…`; `https://trasi.…` → **525**, `http://trasi.…` → **503** dal bordo Cloudflare (Caddy risponde **200** con `Host` header — quindi il problema è l'ingress, non lo stack). **Azione TI**: aggiungere la regola verso `http://localhost:8088`. Sul host non ci sono le credenziali (`/etc/cloudflared/` ha solo un `credentials.json` token-based: nessun `cert.pem`, nessun `CLOUDFLARE_API_TOKEN`).
- **SMTP non configurato**: alert e digest su file (`modo='file'`), non consegnano.
- **App-DB di Metabase copiato "a caldo"** (H2 su volume): nel runbook c'è la procedura per la copia coerente; le dashboard sono comunque ricostruibili (script idempotenti nel `config.tar.gz`).
- **Finestra di reversibilità della retention = una notte** (retention 03:00, backup 02:00, rotazione 7): oltre l'ottavo giorno non è più recuperabile. Dichiarato nel runbook §5.5.

---

## Caccia ai bug (2026-09-16) — 3 bug reali trovati, cause individuate e riparate

Verifiche indipendenti su casi limite, input ostili, invarianti e flussi reali. **Non** una ri-conferma
di ciò che funzionava: ogni area è stata provata dove poteva rompersi.

### Cosa è risultato **solido** (verificato, non assunto)

| Area | Prova |
|---|---|
| Injection SQL | `q='; DROP TABLE trasi.casa;--` → **200**, 10 Case intatte (query parametrizzate) |
| Input malformati | JSON rotto, `payload` non-oggetto, tipo inesistente, id non numerico, decisione invalida → **tutti 422** |
| Autenticazione | chiave errata → **401**; email vuota → **404**; ruolo senza Casa → **422** esplicito |
| V4 da ogni via | ruolo Casa, `shim_rw`, `automazioni` su `luogo`/`scheda` → **`permission denied`**; auto-approvazione → **0 righe** |
| Least-privilege | `metabase_ro` su `proposta`/`audit`/`richiesta`/`identita_onyx` → **ERROR** |
| k-anonimato | **0** conteggi grezzi sotto soglia in `v_confronto_case`, `v_report_mensile`, `v_destinazioni` |
| Errore applicazione | proposta su entità inesistente → `audit='errore_applicazione'`, stato resta `approvata`, batch non si blocca |
| Concorrenza | due proposte sulla stessa entità → last-wins **dichiarato**, entrambe con audit |
| Biglietto A6 | `@page` presente, **0** campi cittadino, **0** input/form |
| Coerenza vista↔shim | `oggi` bozzano: vista `1\|0\|1` = shim `1\|0\|1` |

---

### BUG 1 — Una proposta **scaduta** veniva applicata (grave)

**Come l'ho trovato**: fixture con `stato='approvata'`, `scade_il = current_date - 1` → `applica_proposte_approvate` → **`applicate=1`**.

**Causa**: la funzione filtrava `WHERE p.stato = 'approvata'` **senza guardare `scade_il`**. Il trigger di transizione impedisce di *approvare* dopo la scadenza (riga 165 di `db/006_fn_proposte.sql`), ma **non** copre il caso in cui la scadenza arrivi **dopo** l'approvazione.

**Perché è grave, non teorico**: nel cron `applica` gira alle **05:00** e `scadi_proposte()` **subito dopo**. Tra la mezzanotte e le 05:00 una proposta scaduta resta `approvata` e viene **applicata**: il consenso umano è più vecchio della validità del dato, ma il dato entra comunque nella memoria.

**Fix** (`db/006_fn_proposte.sql`): aggiunto `AND (p.scade_il IS NULL OR p.scade_il >= current_date)` alla selezione.

**Verifica**: scaduta → **0 applicate, 0 righe nel dominio**; valida → **1 applicata** (nessuna regressione).
**Test di regressione** aggiunto a `test_zero_scritture.sql`, e **provato per mutazione**: rimuovendo il fix il test va **rosso** (`stato: applicata`), ripristinato torna verde.

---

### BUG 2 — Gli elementi usciti dalla vista restavano **citabili dalla chat** (grave)

**Come l'ho trovato**: confronto fra i documenti `trasi:*` in Onyx (52) e le righe di `v_kb_export` (37) → **15 orfani**, fra cui `evento 936` e `scheda 334` che **non esistono più nel database**.

**Causa**: la cancellazione **non era mai stata implementata**. `export_kb.py` pubblicava e aggiornava soltanto, con un commento che rimandava la `DELETE` a «B4-FLW-04» — un task già eseguito. Il piano la prevede esplicitamente («DELETE dei `trasi:*` non più in vista»).

**Perché è grave**: un luogo chiuso, un'opportunità scaduta o un evento annullato **restava citabile**, con un badge che dichiarava una fonte attendibile per un dato inesistente. È un difetto di **V3**, non di manutenzione.

**Fix** (`flussi/export_kb.py`): implementate `leggi_onyx()` e `cancellazione()`, collegate al flusso dopo la pubblicazione.

**Seconda trappola, dentro il fix**: il primo tentativo dava **404 su documenti esistenti**. Causa: Onyx memorizza l'id **URL-encoded** (`trasi%3Aevento%3A470`) e FastAPI **decodifica una volta** il percorso — passando `%3A` arriva `:`, che nel database non esiste. La forma corretta è la codifica della stringa già codificata (`%253A`). Verificato: `%253A` → **200** e il documento sparisce; `%3A` → 404 e resta.

**Verifica**: **14 orfani cancellati**; KB=**32**, vista=**32**, orfani=**0**, mancanti=**0**; riesecuzione → **0 cancellati** (idempotente). Un'applicazione reale successiva ha visto l'export **auto-riparare** 5 nuovi orfani.
**Test di regressione** in `flussi/tests/test_export_kb.py` (5 test): forma dell'id nel percorso, calcolo degli orfani, 404 trattato come «già assente».

---

### BUG 3 — Gli alert si ripetevano **ogni giorno** identici (medio, ma insidioso)

**Come l'ho trovato**: due esecuzioni consecutive di `notte.sh` → `alert` invia **2 messaggi** entrambe le volte, con lo stesso contenuto.

**Causa**: nessuna deduplicazione. Il cron esegue `alert.py` **ogni giorno alle 07:30**, quindi un gestore riceve lo stesso avviso («1 proposta in attesa») finché non lo risolve.

**Perché conta**: un avviso che si ripete identico **insegna a ignorare gli avvisi** — ed è esattamente il rischio §13 «coda proposte ignorata», il più probabile di questo sistema per ammissione del piano stesso.

**Fix** (`flussi/alert.py`): impronta del **contenuto** (destinatario + oggetto + righe), confrontata con l'ultimo invio **riuscito** letto da `flusso_run`. Nessuna tabella nuova: l'informazione era già nel registro.

**Verifica**: 1ª esecuzione invia (2), 2ª **sopprime** (2 soppressi). **E non nasconde i cambiamenti**: creata una proposta in più, l'alert **riparte** (0 soppressi, «1 in attesa»). Il criterio è: sopprime le ripetizioni identiche, non gli avvisi importanti.
**Test di regressione** in `flussi/tests/test_alert.py` (3 test): stabilità a parità di contenuto, cambiamento rilevato, destinatari distinti.

---

### Stato dopo le riparazioni

| Suite | Esito |
|---|---|
| B1 dati | **120 PASS / 0 FAIL** (2 test in più: il fix dello scaduto) |
| B3 shim | **167 PASS** |
| B4 flussi | **45 PASS / 1 skipped** (8 test in più: i fix di export e alert) |

**Servizi**: 6/6 healthy · **Onyx**: 11 container intatti · **KB allineata**: 32 = 32, 0 orfani.
**Dati di test**: rimossi; residue 3 proposte legittime, **0 orfane di audit**.

### Nota di metodo

I tre bug hanno una cosa in comune: **nessuno si vedeva dalle suite esistenti**, che erano tutte verdi.
Sono emersi da verifiche *laterali* — un caso limite (scadenza), un confronto fra due fonti di verità
(KB vs vista), una ripetizione (due notti). Le suite verificavano che il sistema facesse ciò che era
stato chiesto; questi erano casi in cui faceva qualcosa che **non** era stato chiesto.


## Caccia ai bug (2026-09-17) — BUG 4: il biglietto per una destinazione esterna rispondeva **500**

**Come l'ho trovato**: nel registro chat di Onyx, sessione `350a77a1` (ore 12:31), assistente `Trasi Casa`:
*«Il **biglietto stampabile** non riesco a generarlo in questo momento: lo strumento risponde con un errore interno
(ho riprovato due volte)»*. L'operatore di Molo 12 chiedeva «come arrivo alla sfizioteca» (POI OSM
`Antosquare La sfizioteca`, nodo `6042688692`) e non ha avuto il biglietto.

**Causa** (`shim/app/testi.py`): il LLM, davanti a un item **esterno** di `vicino_a`, ha chiamato `biglietto` con
l'id del **nodo OSM** (che sta nell'`url` dell'item, `…/node/6042688692`) come se fosse un `luogo.id` della memoria.
La colonna `luogo.id` è `integer` (int4): il bind `asyncpg` è esploso con `OverflowError: value out of int32 range`
prima di toccare il database → 500 `errore interno dello shim` (il contratto dichiara il 422 per `luogo_id`
malformato). La forma giusta esisteva già (`osm:node:<id>`, testata: **200**, foglio A6 generato) ma il contratto
dichiara `luogo_id` come `type: integer`, quindi il modello non poteva saperlo: l'`url` dell'item porta l'id del
nodo, e il modello lo passa come numero.

**Prova della causa** (container `onyx-api_server-1`, chiave dello shim):

```
biglietto?luogo_id=6042688692        → 500 {"detail":"errore interno dello shim"}   (riprodotto il bug)
biglietto?luogo_id=osm:node:6042688692 → 200  HTML A6, badge [Esterna …]            (la forma documentata)
```

**Fix** (due difese, una sola idea: il chiamante deve capire l'errore e sapersi correggere):

1. **Contratto** (`shim/openapi.yaml`): `biglietto.luogo_id` → `type: string` con descrizione che insegna le due
   forme («per un luogo della memoria il numero; per un POI esterno `osm:node:<id>`, l'id sta nell'URL dell'item,
   NON il numero da solo»). Il codice accettava già la forma testuale: era il **documento** a dire l'intero.
   Il runtime non cambia: FastAPI validava `luogo_id: str`, il valore arrivava identico.
2. **Guardia runtime** (`shim/app/testi.py`): un intero oltre il int32 (lo stesso valore che asyncpg rifiuterebbe)
   → **422 leggibile** che insegna la forma `osm:node:<id>`, invece del 500 opaco. Il limite è quello della
   colonna `luogo.id`, non una preferenza.

**Verifica** (container ricostruito e ri-deployato, `trasi-shim-1` healthy):

```
luogo_id=6042688692          → 422 «…usa la forma «osm:node:<id>»…»      (era 500)
luogo_id=osm:node:6042688692 → 200  HTML A6 (2030 byte)                  (percorso esterno)
luogo_id=21 (CAF ACLI KB)    → 200  HTML A6                              (percorso memoria, nessuna regressione)
```

Log shim: `biglietto status=422` / `status=200`, **0 occorrenze di 500**.

**Test di regressione** in `shim/tests/test_output.py` (2 nuovi): nodo OSM come numero → 422 con «osm:node» nel
detail; int32 massimo → 404 (la guardia respinge solo ciò che `asyncpg` rifiuterebbe).
**Suite**: `pytest shim/tests` → **191 passed, 0 failed** (era 189: +2). Contratto: `tests/test_openapi_contract.py`
→ **11 passed** (Onyx validator incluso).

**Nota operativa**: la prima ricostruzione dell'immagine è partita dal compose del workspace (senza `.env`), che ha
ricreato il container con `TRASI_SHIM_KEY=""` → **401** su ogni chiamata da Onyx. Il progetto in esercizio usa il
compose di `/root/orca/projects/onice/deployment/` (con `.env`): ri-deployato da lì, chiavi Caddy/shim/Onyx di nuovo
allineate. Lezione: ricostruire i container **solo** dalla directory del compose attivo.

**Contratto aggiornato (segnalazione, come da precedente «Contratto aggiornato» in B3)**: il `type` di `luogo_id`
passa da `integer` a `string` — non è una rottura: ogni valore intero ammesso prima resta ammesso (come stringa).
**Tool Onyx già allineato**: verificato per confronto semantico fra `shim/openapi.yaml` e `tool.openapi_schema`
del tool `trasi_shim` (id 12) su `onyx-relational_db` — il documento registrato è **identico** al file corretto
(parametro `luogo_id` compreso), quindi il modello già legge la descrizione che insegna la forma `osm:node:<id>`.
