# PROMPT — Generazione di plan.md per Trasi (Portierato di Quartiere)

## Ruolo

Sei il lead engineer / architect dello sprint di 72h del progetto **Trasi** (Portierato di Quartiere, Rete delle Case di Quartiere di Brindisi). Il documento di architettura v1.2 è in `docs/trasi-architecture-v1.2.md` — leggilo per intero **prima** di pianificare: ogni task del piano deve essere riconducibile a una sezione specifica (§2.1 seed Case, §7.1 DDL, §8 flussi F1–F9, §9 contratto shim / assistenti, §10 blocchi B0–B7, §14 user stories).

## Obiettivo

Produci **`plan.md`**: un piano di implementazione esecutivo, operativo, assegnabile, per l'intero sprint 72h + settimana 2 `[S2]`. Non è un riassunto dell'architettura: è il piano che permette a 2+ persone di lavorare **in parallelo senza calpestarsi**, con criteri di done verificabili da terzi, e con i gate `[V-xx]` chiusi **prima** del lavoro che dipende da essi.

**Ultrathink.** Prima di scrivere: ragiona su (a) il grafo delle dipendenze reale (DB schema → shim → flussi → dashboard; V-07 → decisione ricerca web → prompt assistenti; RLS → test «zero scritture dirette»); (b) i rischi di §13 trasformati in task di mitigazione espliciti con owner; (c) i punti di fallimento più probabili nello sprint (Drive OAuth, copertura OSM a Tuturano, coda proposte ignorata) e dove collocare le loro verifiche **early**; (d) quali cose NON vanno automatizzate (decisioni di governance `[DA VALIDARE – Processi]` richiedono il gruppo Processi, non un flusso). Scrivi il piano come lo scriverebbe un team lead che domani deve stare in piedi davanti a 10 Case con qualcosa che funziona.

## Vincoli del piano

- **72h** hard: B0→B7 come in §10; `[S2]` va in una sezione separata «Settimana 2», mai mescolata nel percorso critico.
- **Principi non negoziabili** (V3/V4/V6): nessuna risposta senza fonte etichettata; nessuna scrittura senza proposta→approvazione→applicazione+audit; nessuna azione/compito assegnato dal sistema a persone o Case. Ogni task di scrittura nel piano DEVE transitare da `proposta`. Se ti accorgi che un flusso aggira il meccanismo, segnala il conflitto invece di pianificarlo.
- **Privacy (V5, §12):** niente dati personali verso Ollama Cloud o nelle proposte; `motivazione` ≤ 80 caratteri; retention chat 30gg; k-anonimato 5 su Metabase. Task di compliance espliciti, non impliciti.
- **Tutte le assunzioni `[ASSUNZIONE]` e `[DA VALIDARE]`** dell'architettura vanno raccolti in una sezione «Domande aperte» del piano con owner (PM / TI / Processi / DPO) e deadline entro cui devono chiudersi — nessuno resta orfano.
- Stack esistente e deployato: Onyx v4.7.2 su Docker (provider Ollama Cloud già configurato e validato, connector file testato con RAG citato); da deployare nell'ambiente Trasi: Postgres+PostGIS, NocoDB, Metabase, Activepieces, Caddy (§6, App. B). Il piano deve trattare «stack su» come B0, non come precondizione magica.
- Italiano per i deliverable utente-facing (assistenti, biglietto, Home); il piano stesso in italiano tecnico.

## Formato di plan.md (obbligatorio)

```
# Trasi — Piano di implementazione (sprint 72h)

## 0. Come leggere questo piano
## 1. Blocco 0 — Gate di fattibilità (0–4h)     ← V-01..V-08 come task con criterio pass/fail e azione-se-negativo
## 2. Matrice di lavoro parallelo               ← chi può lavorare a cosa contemporaneamente, dopo quale gate
## 3. Percorso critico e dipendenze             ← grafo/mermaid + tabella owner×blocco
## 4. Task dettagliati per blocco B1..B7        ← per ogni task: ID, owner, stima, input, output, criterio di done (testabile), dipendenze, rischio collegato (§13)
## 5. Batteria di test (B2 + B7)               ← le 15+5+5 KB e le 8 user stories come tabelle eseguibili con esito atteso
## 6. Settimana 2 [S2]
## 7. Domande aperte (DA VALIDARE / ASSUNZIONE) ← tabella: domanda, owner, deadline, fallback se non arriva risposta
## 8. Runbook operativo                          ← cron (01:00 export KB … giorno 3 ciclo), backup/restore, retention, rollback
## 9. Cosa NON si fa in questo sprint           ← icebox esplicito + motivazione
```

Regole di formato: ogni criterio di done è **osservabile** («count(casa)=10», «RLS: ruolo San Bao non aggiorna Bozzano — test SQL allegato», «biglietto HTML stampato in sessione»), non «funziona»; ogni task cita la sezione dell'architettura; stime realistiche a grana di ore, non di giornate; nessun task > 4h senza scomposizione; i task di B7 E2E includono la checklist materiali (stampante, account, 2 operatori + 1 gestore + 1 AT).

## Orchestrazione (sub-agenti del piano)

Il piano stesso va prodotto orchestrando sub-agenti dove serve profondità; in plan.md ogni blocco indica quale SA lo produce/verifica. Sub-agenti previsti:

| Sub-agente | Scope | Task che copre |
|---|---|---|
| **SA-Stack** | Deploy compose, Postgres+PostGIS, Caddy, NocoDB/Metabase/Activepieces, backup/restore, cron | B0, B1 infra, B6 ops |
| **SA-Onyx** | Provider Ollama Cloud, connector Drive, assistenti (§9.2), batteria B2 | B0 V-01/V-02, B2 |
| **SA-Shim** | FastAPI §9.1, Overpass `vicino_a`, biglietto, OpenAPI `shim/openapi.yaml` | B3 |
| **SA-Dati** | DDL §7.1, RLS, parametri §7.2, seed 10 Case, viste, test SQL | B1 |
| **SA-Flussi** | Activepieces F3–F9, applica_proposte, coerenza, ciclo mensile, alert | B4, B6 |
| **SA-Dash** | Metabase Rete/Casa/Mappa, k-anonimato, 4 alert | B5 |
| **SA-Onyx chiude anche V-07** (ricerca web con restrizione per dominio) e **SA-Stack verifica Overpass** (rate limit, opening_hours) e la copertura OSM su Brindisi/Tuturano con 5 query campione. | V-07 + V-extra OSM | B0 |
| **SA-Proposte** | specifica proposta/audit, funzione approvatore, RLS, flusso applica_proposte, test «zero scritture dirette» | B1/B4 cross |
| **SA-UX** | Trasi Home (HTML/CSS), template biglietto A6, checklist WCAG, script della sessione B7 con operatori | B6/B7 |

## Prima di scrivere

1. Leggi `docs/trasi-architecture-v1.2.md` per intero.
2. Estrai: tutte le tabelle con criteri di accettazione (§10, §14), tutti i `[V-xx]`, `[DA VALIDARE]`, `[P]`, i 4 principi, i rischi §13.
3. Costruisci il grafo delle dipendenze; verifica che ogni blocco §10 sia coperto e che nessun task preveda scrittura diretta fuori dal flusso proposta→approvazione→applicazione.
4. Se l'architettura ha buchi che bloccano il piano (es. ambiguità su chi approva cosa), NON inventare: scrivili in «Domande aperte» con fallback proposto.

Scrivi l'output SOLO in `plan.md`. Nessun altro file. Nessuna modifica all'architettura.
