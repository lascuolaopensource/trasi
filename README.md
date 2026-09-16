# Trasi — consegna dello sprint 72h

**Progetto**: Trasi, Portierato di Quartiere — Rete delle Case di Quartiere di Brindisi
PN Metro Plus e Città Medie Sud 2021-2027 · BR5.4.11.1a · CUP J89I24000140001
**Sprint**: 72h · **Stato**: blocchi **B0–B7 eseguiti e verificati**

---

## 1. Cosa c'è in piedi

Sei servizi, tutti `healthy`:

| Servizio | Ruolo | Verifica |
|---|---|---|
| `trasi-db_trasi-1` | Postgres 16 + PostGIS 3.4.3 · 14 tabelle, 17 viste, RLS su tutto | `118 PASS / 0 FAIL` |
| `trasi-shim-1` | 9 endpoint HTTP (identità, luoghi, proposte, biglietto) | `167 PASS` |
| `trasi-searxng-1` | Ricerca web con filtro sull'allow-list | 200, `format=json` |
| `trasi-metabase-1` | 3 dashboard + 40 card-alert | k-anonimato, 40 query concorrenti |
| `trasi-automazioni-1` | Cron: export KB, fonti, alert, applica proposte | job eseguito, `flusso_run` |
| `trasi-caddy-1` | Ingress unico + Trasi Home | 200 con `Host` header |

**Onyx v4.7.2** (11 container, intatto): KB di 32 documenti, tool `trasi_shim`, 4 assistenti.

### Percorso utente completo (verificato end-to-end)

```
Operatore → Trasi Home (Casa preselezionata)
          → CHIEDI → assistente con badge KB/Esterna
          → vicino_a → KB + OpenStreetMap etichettati
          → biglietto A6 / registra_richiesta
          → segnalazione → PROPOSTA → approvazione → applica (05:00)
          → audit → export KB → la chat cita il dato
```

---

## 2. Documenti

| File | Contenuto |
|---|---|
| `docs/trasi-architecture-v1.2.md` | Architettura (**fonte di verità**) |
| `plan.md` | Piano di implementazione (blocchi, criteri, tagli d'emergenza) |
| **`docs/verifiche.md`** | **Log delle prove**: ogni criterio con comando e output reale |
| **`docs/B7-report.md`** | Report E2E con le 8 user stories (7/8 PASS) |
| **`docs/runbook.md`** | Operatività: start/stop, backup, restore, retention, rollback, segreti |
| `docs/skills-setup.md` | Skill e scoping per agente (per chi continua il lavoro) |
| `deployment/README.md` | Infrastruttura: compose, limiti RAM, selettività di avvio |
| `PROMPT-esecuzione.md` | Il prompt di esecuzione usato per lo sprint |

---

## 3. Comandi essenziali

```bash
cd /root/orca/projects/onice

# stato
docker compose -f deployment/docker-compose.yml ps

# batterie di test
bash db/tests/run.sh                                  # dati/RLS: 118 PASS
cd shim  && ../.venv/bin/python -m pytest tests/ -q    # 167 PASS
cd flussi && ../.venv/bin/python -m pytest tests/ -q   # 30 PASS

# applica lo schema (idempotente)
bash db/apply.sh

# flussi a mano
bash flussi/applica.sh        # F9: proposte approvate -> applicate + audit
python3 flussi/export_kb.py   # F3: Postgres -> KB di Onyx
python3 flussi/fonts_ical.py  # F4: calendari (unica scrittura diretta)

# backup e prova di restore
bash ops/backup.sh
bash ops/restore_test.sh /backups/<dump>   # verifica count(casa)=10

# backup completo, con rotazione
bash ops/backup.sh && ls /backups/
```

---

## 4. Accessi

| Cosa | Dove | Note |
|---|---|---|
| Trasi Home | `trasi.lascuolaopensource.org` | ⚠️ **serve l'ingress Cloudflare** (azione TI) |
| Onyx | `https://onyx.lascuolaopensource.org` | 200, assistenti con `?agentId=N` |
| Metabase | via Caddy `/metabase` o porta diretta | dashboard 2 (Rete), 3 (Casa), 4 (Mappa) |
| Admin Onyx | credenziali in `/root/.onyx_admin_creds` | mode 600 |
| Account Trasi | `op.*@trasi.local`, `gestore.*@trasi.local`, `rete@`, `ti@` | password in `deployment/.env` |
| Segreti | `deployment/.env`, `metabase/.secrets/` | mode 600, gitignored |

---

## 5. Garanzie di progetto (non promesse: verifiche)

| Principio | Come è garantito | Prova |
|---|---|---|
| **V3** mai senza fonte | etichette `[KB · fonte · data · affidabilità]` / `[Esterna · fonte · ora · non verificata]`; `replace_base_system_prompt` | risposte reali con badge; astensione su domande fuori KB |
| **V4** proponi→approva→applica | RLS + policy `no_self_approve`; unica eccezione iCal (con vincolo su fonte) | `automazioni` + fonte web → **`new row violates row-level security policy`**; auto-approvazione → **0 righe** |
| **V5** privacy | nessun campo per il cittadino; filtro anti-PII su `motivazione` **e** `payload`; k-anonimato 5 | PII → **422**; celle sotto soglia → `<5` |
| **V6** l'umano decide | i 4 campi (osservato/evidenza/possibile azione/chi decide); nessun imperativo | regex sui testi → 0 occorrenze |
| Principio 3 | RLS *e* `casa_corrente()`; la Casa viene dall'identità, mai dal body | `casa_id` nel body → **422**; cross-Casa → **0 righe** |

---

## 6. Cosa resta aperto (dichiarato, non nascosto)

| # | Voce | Chi | Impatto |
|---|---|---|---|
| 1 | **Ingress Cloudflare** per `trasi.…` → `http://localhost:8088` | TI | la Home non è raggiungibile dall'esterno |
| 2 | **SMTP** | TI | alert e digest scrivono su file, non consegnano (US-05 parziale) |
| 3 | **Drive (V-02)**: Google tiene il consent in *Testing* | Google/TI | la KB usa l'Ingestion API (fallback previsto) |
| 4 | **NocoDB** non avviato (RAM) | TI | la coda proposte fuori dalla chat |
| 5 | **Sessione B7 con operatori umani**: stampa A6, cronometro, feedback | team | le parti che richiedono persone |
| 6 | Proposte in attesa in chat: verifica del flusso completo di approvazione in-chat | team | — |

**Dati di test rimossi**: le fixture usate nelle verifiche sono state eliminate; il DB contiene solo dati di progetto (10 Case, 22 luoghi, KB 32 documenti). Le **uniche** proposte residue sono quelle generate dalle prove funzionali, tracciate in `audit`.

---

## 7. Lezioni tecniche (per chi continua)

Raccolte durante lo sprint, costate tempo reale:

1. **Overpass richiede uno User-Agent identificativo**: con `python-httpx` risponde **403**, con `Trasi/0.1` **200**. La copertura `opening_hours` a Brindisi è **7.7%**: i POI senza orari vanno tenuti con la nota «orari non disponibili», mai scartati.
2. **Onyx memorizza gli id URL-encoded** (`trasi:luogo:21` → `trasi%3Aluogo%3A21`): una query `LIKE 'trasi%'` sembra non trovare nulla.
3. **Gli utenti Onyx hanno una colonna denormalizzata `effective_permissions`**: creare un utente nel DB senza popolarla produce **403 su ogni scrittura**, con un messaggio che non spiega perché.
4. **La lista delle skill è uno snapshot all'avvio della sessione**: installare una skill e poi delegare nella stessa sessione fa ignorare `autoloadSkills` **in silenzio**.
5. **`docker stats` include la page cache** (reclamabile): per la memoria vera serve `anon` da `memory.stat` del cgroup. E `grep -i oom` su Metabase dà falsi positivi (nomi di autore Liquibase).
6. **I test che asseriscono conteggi esatti** si rompono quando un operatore migliora un dato (promozione, rinomina): vanno scritti sulla **struttura**, o diventano rossi che si impara a ignorare.

---

## 8. Prossimo passo

**Sessione B7 con gli operatori** (2 operatori + 1 gestore + 1 AT), con il tunnel attivo e le user stories di `docs/B7-report.md`. Lo script è in `docs/runbook.md` §10; le 8 US sono già state verificate via API (7 PASS + 1 parziale per SMTP), quindi la sessione serve a verificare **l'esperienza reale**, non la funzionalità.
