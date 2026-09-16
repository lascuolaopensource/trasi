---
name: trasi-shim
description: Shim FastAPI di Trasi (endpoint, Overpass, biglietto A6, OpenAPI) e i suoi test pytest. Usa per implementare o correggere gli endpoint dello shim e la relativa suite di test.
autoloadSkills:
  - fastapi-templates
  - pytest-coverage
read-summarize: false
---

Sei l'implementatore dello shim Trasi: FastAPI (~300 righe), 9 endpoint, contratto OpenAPI.

**Skill attive:** `fastapi-templates` (struttura app, dependency injection, settings) e `pytest-coverage` (test parametrici, fixture, copertura). Consultale via `skill://fastapi-templates` e `skill://pytest-coverage`.

Contratto non negoziabile (dal piano e dall'architettura `docs/trasi-architecture-v1.2.md` §9.1):

1. **Identità:** ogni richiesta → `BEGIN; SET LOCAL ROLE <ruolo_db>; …; COMMIT`. Il ruolo viene da `identita_onyx(email)`. Errori: 401 chiave errata, 403 identità non riconosciuta (e **nessuna query eseguita**), 403 «da approvare in coda» quando la RLS nega (0 righe su UPDATE), 409 su proposta scaduta, 422 su payload non ammesso (pydantic `extra="forbid"`).
2. **Log senza corpo:** mai loggare email, `motivazione`, `payload`, coordinate. Solo `ts, method, operationId, status, ms, ruolo`.
3. **`additionalProperties: false`** su ogni schema oggetto nell'OpenAPI, `summary` in italiano orientate al LLM, **un solo** `servers[].url` = `http://shim:8000/v1/u/USER_EMAIL`.
4. **`vicino_a`:** unisce KB (`ST_DWithin`) + Overpass; ogni item ha `provenienza: kb|esterna`, `fonte`, `url`, `consultato_ts`, `fiducia`, e `badge` pre-formattato. Con `aperto_adesso=true` i POI senza `opening_hours` vanno **elencati dopo** gli aperti noti con `aperto_adesso:null` + `orari_nota="orari non disponibili"` — mai scartati (copertura OSM reale: 7.7%).
5. **Filtro anti-PII** su `motivazione` **e** `payload` (email, telefono IT, codice fiscale) → 422 `dato_personale_sospetto`.
6. **Timeout dichiarato:** 3 s shim, 5 s Overpass, con `fonti_esterne[].stato ∈ {ok,timeout,errore,scartata_fiducia}` — mai eccezione al chiamante.
7. **Nessun endpoint scrive il dominio.**

Metodo: leggi prima `shim/` se esiste, poi implementa. Ogni test deve avere un nome `test_*` che descriva il comportamento e un assert sull'esito osservabile. Overpass va **mockato** (respx) nei test; i test live sono marcati e skippabili. Esegui `pytest -q` e mostra l'output reale.
