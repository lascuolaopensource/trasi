# TASK SPEC — B2 Onyx: connettore KB, tool custom, assistenti (`trasi-onyx`)

## Target

Configura l'istanza Onyx v4.7.2 **già attiva e healthy** (`/opt/onyx/deployment/docker_compose`, 11 container) per il progetto Trasi.

Non reinstallare nulla. Non modificare `/opt/onyx/deployment/docker_compose/docker-compose.yml` (l'`override.yml` è già a posto, non serve toccarlo).

Accesso amministrativo: credenziali in `/root/.onyx_admin_creds` (**non stamparle**). Sessione:
```
. /root/.onyx_admin_creds
curl -sS -c /tmp/oc2 -X POST http://127.0.0.1/api/auth/login \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d "username=$ONYX_ADMIN_EMAIL&password=$ONYX_ADMIN_PASSWORD" -w '%{http_code}\n'
```

## Contesto verificato (non ri-verificare da capo)

- Provider LLM: `ollama_chat` → `https://ollama.com`, modello `deepseek-v4-flash:0731`, **già validato** (chat + RAG con citazione `[[1]]`).
- **V-02 (Drive) = ROSSO**: Google blocca il consent (app in Testing, nessun tester approvato). **Non perdere tempo su Drive**: si applica il fallback previsto dal piano.
- **V-09 = PASS**: `shim/openapi.yaml` esiste (40 KB, 9 operazioni, `servers[].url = http://shim:8000/v1/u/USER_EMAIL`, `additionalProperties:false` ovunque, validato **con il validatore di Onyx** `validate_openapi_schema` e con `openapi-spec-validator`).
- Lo **stub** dello shim risponde 501: gli endpoint reali arrivano col blocco B3. Di conseguenza il tool `trasi_shim` si registra ora ma **fallirà 501** finché B3 non è chiuso.
- I dati di Trasi sono in Postgres: container `trasi-db_trasi-1`, DB `trasi_db`, schema `trasi` (13 tabelle, viste tra cui `v_kb_export`). Comando:
  `docker compose -f deployment/docker-compose.yml exec -T db_trasi psql -U postgres -d trasi_db -c "…"`

## Change

### 1. `B2-ONX-07` — connettore KB (fallback Drive)

Crea un connettore dedicato per la knowledge base Trasi, alimentato via **Ingestion API**:
```
POST /api/manage/admin/connector
{"name": "Trasi KB (export)", "source": "INGESTION_API", "input_type": "LOAD_STATE", "connector_specific_config": {}}
```
(Nota: il router dei connector è montato con prefisso `/manage` → il path reale è `/api/manage/admin/connector`. Verifica nel sorgente se diverso.)
Salva il `cc_pair_id` risultante in un file `shim/.onyx-kb.json` (o dove indicato) perché servirà al flusso F3.

**Prova:** il connettore compare in `GET /api/manage/admin/connector`; un `POST /api/onyx-api/ingestion` di prova con un documento sentinella viene accettato.

### 2. Popola la KB con i dati reali di Trasi (necessario per la batteria)

La KB di Onyx non vede il Postgres: va alimentata. Scrivi uno script `flussi/export_kb.py` (o `.sh`) che:
- esegue `SELECT * FROM trasi.v_kb_export` (colonne `doc_id, entita, id, titolo, testo, fonte_nome, url, data_aggiornamento, affidabilita, casa_nome`)
- per ogni riga invia `POST /api/onyx-api/ingestion` con `document.id = doc_id` (**id naturale → upsert idempotente**), `semantic_identifier = titolo`, `sections=[{text, link}]`, `metadata={fonte, data_aggiornamento, affidabilita, casa, entita}`
- è **rieseguibile**: seconda esecuzione → `already_existed=true`, nessun duplicato

**Prova:** `GET /api/onyx-api/ingestion` mostra i documenti con id `trasi:*`; i `metadata` sono visibili in amministrazione.

> Serve una API key Onyx con permesso `MANAGE_CONNECTORS`: creala dall'interfaccia o via API (personal access token), salvala **fuori dal versionamento** (es. `deployment/.env`, mode 600) e **non stamparla**.

### 3. `B2-ONX-04` — tool custom dal contratto congelato

Registra `shim/openapi.yaml` come tool custom:
```
POST /api/admin/tool/custom
{"name": "trasi_shim", "description": "…", "definition": <contenuto di shim/openapi.yaml>, "custom_headers": [{"key":"X-Trasi-Key","value":"<segreto>"}], "passthrough_auth": false}
```
Il placeholder `USER_EMAIL` nel `servers[].url` viene sostituito **lato server** da Onyx con l'email dell'utente autenticato: **non** toccare quell'URL.

**Prova:** `GET /api/admin/tool` elenca `trasi_shim` con le 9 operazioni; il registro funziona anche se poi le chiamate danno 501 (è lo stub).

### 4. `B2-ONX-05` — 4 assistenti

Crea gli assistenti con `POST /api/admin/persona`. Per ognuno:
- `replace_base_system_prompt: true` — **obbligatorio**: la guida base di Onyx spinge a rispondere da conoscenza pregressa, che viola V3 (`chat/llm_loop.py:908-916`)
- `tool_ids` = [id di `trasi_shim`]
- `document_set_ids` = [connettore «Trasi KB (export)»]
- `is_public: true`

**Blocco comune del system prompt** (18 righe) + una delta per ciascuno. Testo (usalo, adattandolo solo se necessario):

```
Rispondi SOLO con informazioni dalla knowledge base (KB) o dagli strumenti.
MAI da memoria del modello.
Etichetta OGNI informazione:
[KB · fonte · data · affidabilità 1-3] oppure [Esterna · fonte · ora · non verificata dalla rete]
Se lo strumento non risponde: dichiaralo esplicitamente.
Se nessuna fonte risponde: dichiara «non trovo informazioni su questo».
L'operatore segnala un cambiamento? NON modificare nulla: usa proponi_modifica.
Se riguarda la sua Casa, chiedi: «Vuoi che aggiorni ora? Sì / No».
Non chiedere né trascrivere dati personali della persona davanti a te.
A fine colloquio: categoria, esito, destinazione, biglietto (usa biglietto se serve).
Se una Casa ha un servizio professionale interno (es. psicologa di comunità), proponilo PRIMA di servizi esterni.
Mai imperativi rivolti a persone o Case: il sistema osserva, l'umano decide.
Oggi in Casa: usa eventi_oggi. Per luoghi/orari vicini: vicino_a.
Ricerca web esterna su fonti autorevoli: cerca_web.
Proponi correzione: proponi_modifica. Approva/rifiuta un dato della propria Casa: approva_proposta.
Stampa per il cittadino: biglietto(luogo_id).
Sezione «Oggi» della Home: oggi(casa).
```

Delta dei 4:
- **Trasi Presidio** (ascolto/solitudine): prima domanda «Che tipo di aiuto cerchi?»; se solitudine → prima il servizio professionale interno alla rete (psicologa di comunità Parco Buscicchio), poi attività over 60 (Bozzano), poi altre Case; **no compagnia personale, no valutazioni cliniche**; destinazione obbligatoria se si invia altrove.
- **Trasi Casa** (operatore di sportello): accogli, ascolta, indirizza; tre azioni — chiedi, leggi le fonti, stampa/registra; se la domanda riguarda la propria Casa usa `eventi_oggi`+`vicino_a`; se riguarda altre Case → proposta (approvatore AT).
- **Trasi Rete** (AT/rete): vede tutta la rete; confronta le Case se utile; approva proposte di territorio/comune; mai ordinare alle Case («si potrebbe considerare…»).
- **Trasi Staff PN**: aggregato e anonimo, k-anonimato 5; se una cella ha < 5 casi **non mostrarla**; non inventare numeri.

**Prova:** i 4 assistenti esistono; `curl -sS -b /tmp/oc2 'http://127.0.0.1/api/admin/persona'` li elenca; `https://onyx.lascuolaopensource.org/app?agentId=<id>` apre la chat con l'assistente preselezionato (verifica almeno che l'URL esista e restituisca 200).

### 5. `B2-ONX-06` — batteria (PARZIALE in B2)

Esegui **solo le domande di sola KB** (le 10 con risposta + 5 astensioni). Le 5 ibride e le 5 di proposta richiedono il tool reale (B3) e **non** sono eseguibili ora: registra che sono rinviate e perché.

Per ogni domanda: crea una chat session, invia il messaggio, verifica che la risposta contenga almeno un'etichetta `[KB · …]` e che le domande fuori KB diano **astensione dichiarata** (nessuna invenzione).

**Prove:** tabella con domanda → esito (etichetta presente? astensione?) → esito PASS/FAIL; conteggio etichette = **100%**; astensioni **5/5**.

## Constraints

- **V3**: `replace_base_system_prompt: true` su tutti; l'etichetta di provenienza è obbligatoria in ogni risposta.
- **V4**: gli assistenti **non** scrivono la memoria: solo `proponi_modifica` (crea proposta). Nessuna chiamata diretta a scritture di dominio.
- **V5/§12**: nessun dato personale nei prompt verso Ollama Cloud; nessuna chiave stampata in output.
- Non toccare l'istanza Onyx oltre a quanto richiesto (è in uso da altre utenze: c'è già un connector «Zephyria Docs», lascialo).
- Non riavviare l'intero stack Onyx senza motivo.
- **Non dichiarare verde la batteria completa**: le 10 domande con tool sono rinviate a B3.

## Ownership

`shim/.onyx-kb.json`, `flussi/export_kb.py`, e le configurazioni dentro Onyx (via API). Non toccare `db/**`, `deployment/**`, `plan.md`.

## Observable acceptance (prove reali)

1. `GET /api/manage/admin/connector` → presente «Trasi KB (export)» (`source: ingestion_api`), con il suo id.
2. `GET /api/onyx-api/ingestion` → i documenti `trasi:*` con i `metadata` (fonte/data/affidabilità).
3. `flussi/export_kb.py` eseguito **due volte** → la seconda non crea duplicati (`already_existed=true`).
4. `GET /api/admin/tool` → `trasi_shim` registrato con 9 operazioni.
5. 4 assistenti elencati, ognuno con `trasi_shim` tra i tool e il document set della KB.
6. Batteria parziale: tabella domanda→esito; **etichette 100%** sulle KB; **astensioni 5/5**; le 10 tool-dependent **dichiarate rinviate a B3** (non spacciate per passate).

Riporta comandi e output reali.

## Nota
Hai accesso al sorgente Onyx in `/opt/onyx/backend` — usalo per verificare i path API reali quando un endpoint non risponde come previsto. Se un endpoint dell'architettura/§9 non coincide con quello implementato, **adatta e segnala** (non inventare).
