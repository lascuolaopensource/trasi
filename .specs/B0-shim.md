# TASK SPEC — Worker `trasi-shim` (blocco B0, contratto V-09)

## Target

Crea da zero lo scheletro dello shim Trasi in `/root/orca/projects/onice/shim/`:
- `openapi.yaml` — **contratto v0 congelato**, 9 operazioni
- `app/` — stub FastAPI che risponde **501** a ogni operazione (tranne `/healthz`)
- `Dockerfile`
- `tests/` — test minimi

Questo è il gate **V-09**: serve a rompere un ciclo di dipendenza. Il worker `trasi-onyx` registrerà questo contratto come tool custom in Onyx **prima** che gli endpoint siano implementati; l'implementazione reale è il blocco B3.

## Change

### 1. `shim/openapi.yaml` — contratto congelato (la parte critica)

**Vincoli tecnici obbligatori** (verificati nel sorgente di Onyx v4.7.2 in `/opt/onyx/backend`):
- `servers:` deve avere **esattamente un** elemento, con `url: http://shim:8000/v1/u/USER_EMAIL`
  (`USER_EMAIL` è un placeholder che Onyx sostituisce lato server con l'email dell'utente autenticato — `tools/tool_constructor.py:436-447`, `tool_implementations/custom/custom_tool.py:307-308`)
- ogni `operationId` è univoco e stabile; `summary` in **italiano**, orientato al LLM (quando usare il tool)
- `additionalProperties: false` su **ogni** schema di tipo objeto (ricorsivamente)
- content type: solo `application/json`

**Le 9 operazioni** (nomi esatti = contratto con gli altri worker, non cambiarli):

| operationId | Method | Path | Parametri principali |
|---|---|---|---|
| `cerca_luogo` | GET | `/cerca_luogo` | `q`, `tipo?`, `quartiere?` |
| `eventi_oggi` | GET | `/eventi_oggi` | `casa`, `data?` |
| `vicino_a` | GET | `/vicino_a` | `casa`, `tipo`, `aperto_adesso?`, `raggio_m?` |
| `registra_richiesta` | POST | `/registra_richiesta` | `categoria`, `esito`, `destinazione_id?`, `destinazione_nota?` |
| `proponi_modifica` | POST | `/proponi_modifica` | `tipo`, `entita`, `entita_id?`, `payload`, `motivazione` |
| `approva_proposta` | POST | `/approva_proposta` | `proposta_id`, `decisione`, `nota?` |
| `biglietto` | GET | `/biglietto` | `luogo_id`, `casa?` |
| `oggi` | GET | `/oggi` | `casa` |
| `cerca_web` | GET | `/cerca_web` | `q`, `max?` |

Lo schema di risposta di `vicino_a` deve prevedere, per ogni item: `provenienza` (`kb`|`esterna`), `nome`, `tipo`, `indirizzo`, `lat`, `lon`, `distanza_m`, `aperto_adesso` (nullable), `orari_testo` (nullable), `orari_nota` (nullable), `fonte`, `url` (nullable), `data_aggiornamento` (nullable), `fiducia` (1-3), `consultato_ts`, `badge`.
Prevedi anche `fonti_esterne[]` con `fonte`, `stato` (`ok`|`timeout`|`errore`|`scartata_fiducia`), `ms`.

`registra_richiesta` e `proponi_modifica` devono avere `additionalProperties: false` (**nessun campo libero per dati personali**: se arriva `nome_cittadino` → 422).

### 2. `shim/app/` — stub FastAPI
- `main.py`: app FastAPI con tutte e 9 le route che rispondono **501 Not Implemented** con body `{"detail": "non implementato (contratto v0)"}`, più `GET /healthz` → `{"status": "ok"}` 200.
- `settings.py`: pydantic-settings con le variabili attese (`DATABASE_URL`, `TRASI_SHIM_KEY`, `OVERPASS_URL`, `OVERPASS_TIMEOUT_S=5`, `SHIM_TIMEOUT_S=3`, `TZ=Europe/Rome`). Valori di default sensati, nessun segreto hardcoded.
- L'OpenAPI esposto da FastAPI (`app.openapi()`) deve essere **coerente** con `openapi.yaml` (stessi operationId). Aggiungi un test che lo verifica.

### 3. `shim/Dockerfile`
- base `python:3.12-slim`, utente non root, `uvicorn --no-access-log --workers 1`, `EXPOSE 8000`, `HEALTHCHECK` su `/healthz`.
- Usa la skill `multi-stage-dockerfile` se serve un build stage.

### 4. `shim/tests/` (pytest)
- `test_health.py`: `/healthz` → 200.
- `test_stub_501.py`: ognuna delle 9 operazioni → 501.
- `test_openapi_contract.py`: (a) `openapi.yaml` si carica e ha 9 operationId attesi; (b) `servers` ha esattamente 1 elemento e l'URL è quello atteso; (c) walk ricorsivo: ogni `type: object` ha `additionalProperties: false`; (d) gli operationId di `openapi.yaml` coincidono con quelli di `app.openapi()`.

## Constraints

- **V4**: nessuna scrittura alla memoria. In B0 sei uno stub: nessuna connessione al DB, nessuna query.
- **V5/§12**: nessun campo per dati personali negli schemi; nessun log di corpo richiesta.
- **Non inventare** endpoint, parametri o modelli non presenti in questa spec (la fonte è `docs/trasi-architecture-v1.2.md` §9.1).
- Non avviare container: l'infrastruttura la gestisce il worker `trasi-stack`.
- Non usare servizi esterni (l'Overpass reale è del blocco B3).

## Ownership

Puoi creare/modificare: `shim/**`. Non toccare: `deployment/**` (altro worker), `plan.md`, `docs/trasi-architecture-v1.2.md`.

## Observable acceptance (prove reali)

1. `pytest shim/tests -q` → **0 failed**, con il conteggio dei test passati.
2. `python -c "import yaml; d=yaml.safe_load(open('shim/openapi.yaml')); print(len(d['paths']), d['servers'])"` → 9 operazioni e un solo server con l'URL atteso.
3. Il test di coerenza openapi↔FastAPI verde (dimostra che app.openapi() combacia).
4. `docker build -t trasi-shim:test shim/` → build riuscita (se Docker è disponibile; altrimenti dichiara che non l'hai potuto verificare).

Riporta i comandi eseguiti e gli output reali.

## Nota su skill e contesto
Hai attive `fastapi-templates` e `pytest-coverage`: usale. Il contratto completo degli endpoint è in `docs/trasi-architecture-v1.2.md` §9.1; il piano in `plan.md` (V-09, blocco B0, B3-SHM-09). In caso di conflitto **vince l'architettura**, e il conflitto va segnalato.
