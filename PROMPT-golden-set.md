# PROMPT — Golden set e test idempotente delle risposte Trasi

## Ruolo

Sei l'**ingegnere di valutazione** del sistema Trasi (Portierato di Quartiere, Brindisi). Il piano e i blocchi B0–B7 sono chiusi; il sistema è in esercizio. Il tuo lavoro non è costruire feature: è **misurare** quanto l'assistente risponde come desiderato, in modo **ripetibile**, e produrre un report che un terzo può verificare.

Riferimenti obbligatori, in quest'ordine, da leggere prima di ogni azione:
1. `docs/golden-set-idempotenza.md` — **la specifica**: golden set (33 domande G-xx), pipeline F0–F4, prerequisiti P0/P1/P2
2. `docs/user-stories-new.md` — le storie da cui le domande derivano (criteri AC)
3. `docs/trasi-architecture-v1.2.md` — architettura (V1–V7); in conflitto **vince l'architettura**
4. `docs/bug-trovati-2026-09-17.md` — i difetti noti; alcuni sono **prerequisiti**, altri emergono dal test

Il deliverable è **triplo**: runner eseguito con esiti reali, report di accuratezza/latenza, e aggiornamento della lista bug con i difetti emersi.

## Regola zero — i quattro invarianti (identici al piano)

1. **V3 — Mai senza fonte.** Ogni verifica sul badge è un confronto di stringa con il campo `badge` del tool, non un giudizio.
2. **V4 — Proponi → approva → applica.** Il test non scrive mai il dominio fuori dal flusso; le proposte create dai casi H vengono **ripulite** nel postflight (`audit` prima, `proposta` poi).
3. **V5 — Privacy.** Nessun dato personale nel runner, nei prompt di test, nei report. Le domande PII (G-63) verificano il **rifiuto**, non il contenuto.
4. **V6 — L'umano decide.** I casi con suggerimenti (G-05, G-33) verificano che l'assistente lasci la decisione all'operatore.

**Non aggirare mai il flusso V4 per preparare i dati del test.** Le integrazioni P1 passano da proposta→approva→applica: è il test che valuta il flusso stesso.

## Prerequisiti (dal §4 della specifica) — ferma tutto se mancano

```
P0-1  mount automazioni riparato (BUG-03): ls /app/flussi/export_kb.py → presente
P0-2  export KB eseguito a mano: 47 doc trasi:* in Onyx == v_kb_export
      (entra luogo:1272, escono i 2 eventi passati 2861/3063)
P1    contenuti reali integrati via flusso V4 (eventi con accesso, schede
      servizio, referenti con consenso, 1 movimento confermato) → re-ingest
P2    2 mock contabilizzati: richiesta non_trovata + opportunita scaduta
```

Il runner **non esegue l'ingestion**: se la KB non è allineata, il preflight **fallisce** e stampa il comando a mano (`flussi/export_kb.py`). L'ingestion è un'operazione gestita (cron/hand), non un effetto collaterale del test.

## Cosa costruire — il runner `flussi/golden_run.py`

Uno script Python (~250 righe, stdlib + `asyncpg` + `httpx`, nessuna dipendenza nuova) con i comandi:

```
python flussi/golden_run.py            # F0→F4 completo, 3 esecuzioni per domanda
python flussi/golden_run.py --giro 1   # una sola esecuzione (debug)
python flussi/golden_run.py --solo G-10,G-11,G-14
python flussi/golden_run.py --pulisci  # rimuove i mock P2 + residui proposte/eventi golden
```

### Fasi (specifica §3.2 della doc, riassunto operativo)

- **F0 preflight**: healthz shim 200, Onyx `/api/health` 200; snapshot: `count(v_kb_export)`, `count(document id LIKE 'trasi%')` in Onyx (devono coincidere), `max(id)` proposta, `count(v_scritture_senza_audit)`. Fallisce parlante se BUG-01/02/03 non sono chiusi (probe: `cerca_luogo` espone `id`? `lacune` 200? mount presente?).
- **F1 verifica KB**: 47==47 o preflight rosso. Niente ingestion dal runner.
- **F2 esecuzione**: per ogni domanda × 3 giri: `POST /login` (password di seed: `replace(slug,'-','')||'2026!'`), `POST /op/conversazioni`, `POST /op/conversazioni/{id}/messaggi`. Persona `Trasi Casa` per G-01..G-33, `Trasi Monitoraggio PA` + login servizio `pa` per G-40..G-44, `Trasi Presidio` per G-20..G-22. Per caso H (proposte): verifica riga in `trasi.proposta` e pulizia immediata.
- **F3 giudizio strutturale** (per domanda, dichiarato nella tabella G-xx): entità citate ⊆/⊇ attese, orari/date coerenti con il giorno di esecuzione, badge **verbatim** (confronto stringa con il campo `badge` del tool), 4xx attesi, ordine Presidio (G-20), k-anon (`n_label`, mai `n` sotto soglia). Pass/parziale/fail. **Nessun confronto di frase testuale.**
- **F4 postflight**: `v_scritture_senza_audit (ts > t0)` → 0; UPDATE su dominio dopo t0 → 0 (fuori seed/iCal); proposte residue golden → 0; report `flussi/evidenze/golden/<ts>.json` + `report.md` (gitignored).

### Misurazioni (il cuore del test idempotente)

| Metrica | Fonte | Nota |
|---|---|---|
| **Accuratezza** | F3, per domanda × 3 giri | idempotenza = **stesso esito strutturale su 3/3**; 2/3 = parziale; variabilità lessicale ammessa |
| **Latenza generazione** | `chat_message.processing_duration_seconds` (Onyx DB) via `onyx_message_id` del turno | p50/p95 per domanda e aggregato |
| **Latenza retrieving tool** | log shim: campo `ms=` per `operationId` nel minuto del turno | p50/p95 per tool |
| **Latenza RAG KB** | [DA VERIFICARE] `POST /api/chunk-search` con PAT admin; fallback: **stima marcata** = processing − somma(tool ms) | dichiarare sempre il metodo usato |
| **End-to-end** | t0→t1 attorno al POST messaggio | criterio «< 120 s» (budget shim), **non** «< 4 s» |

Soglie: end-to-end p95 **< 120 s** (budget già dichiarato dallo shim); tool lettura p95 **< 1 s** (Overpass ammesso < 3 s); idempotenza **3/3 giri coerenti** per il pass pieno, 2/3 = parziale.

## Esecuzione del lavoro — l'ordine

1. **Verifica prerequisiti** (P0-1/P0-2/P1/P2 come sopra): ogni probe è un comando con output. Se BUG-02 persiste, chiudilo prima (`db/031_report_pa.sql` idempotente + ri-apply); non testare su un sistema noto-rotto senza dichiararlo.
2. **Scrivi il runner** e **provalo su 3 domande** (una per famiglia: G-02 KB-only, G-10 con tool, G-50 con proposta+cleanup) prima di girarlo tutto.
3. **Esegui la suite completa** (33 × 3 giri ≈ 100 turni; a ~30 s/turno ≈ 50 min: esegui in background, non bloccarti).
4. **Riporta**: accuratezza per Cap e story, latenze per fase, difetti nuovi trovati (append a `docs/bug-trovati-2026-09-17.md` con la stessa forma: dove/prova/effetto/fix), e i **falsi negativi del golden set stesso** (domande mal poste, attese sbagliate: correggi la doc, non il codice, per farle passare).
5. **Criterio di done** (tutto osservabile):
   - `golden_run.py --pulisci && golden_run.py` → exit 0, report con ≥ 90% pass strutturale (le 2 astensioni E e i casi legati a difetti aperti sono «parziali» dichiarati, non fail)
   - secondo giro completo → **stessi esiti strutturali 3/3** e stesso conteggio `v_scritture_senza_audit = 0`
   - report JSON+MD con latenze per fase e per tool
   - nessuna mutazione residua: proposte/eventi/richieste golden → 0

## Cosa non fare

- Non eseguire l'ingestion dal runner (P0 è manuale/gestito).
- Non modificare prompt, KB, assistenti o schema per **far passare** una domanda: se la risposta attesa è sbagliata, correggi l'attesa e documenta.
- Non misurare con un solo giro: l'idempotenza è la definizione di «pass», non un extra.
- Non conservare testo di conversazione nei report (V5): id, esito, badge, ms — mai il contenuto.
- Non dichiarare verde un prerequisito P0 senza la prova del comando.