# TASK SPEC — B4 Flussi: il ciclo notturno di Trasi (`trasi-flussi`)

## Target

Implementa la **catena notturna** di Trasi in `flussi/` (script eseguibili dal container `automazioni`), più il servizio `automazioni` nel compose e i suoi test.

Questo blocco chiude il ciclo di **V4**: una proposta approvata diventa dato reale, **con riga di audit**, e il giorno dopo la chat la cita. È il criterio §10 B4.

## Contesto verificato (non ri-verificare)

**Servizi attivi:** `trasi-db_trasi-1` (Postgres+PostGIS, hostname `db_trasi`), `trasi-searxng-1`, `trasi-shim-1` — tutti healthy.

**Già fatto (B1/B2/B3), usalo:**
- `trasi.applica_proposte_approvate(p_limit)` — **esiste**, idempotente, un savepoint per proposta, scrive `audit` con `prima`/`dopo`. Owner `applicatore`; `EXECUTE` a `automazioni` e `ti` (verificato: `has_function_privilege('automazioni', …, 'EXECUTE')` = **t**).
- `trasi.scadi_proposte()` — esiste.
- `trasi.fonte_run` — **esiste** (append-only).
- `trasi.flusso_run` — **NON esiste**: creala tu.
- `trasi.v_kb_export` — 32 righe (10 Case, 22 luoghi), colonne: `doc_id, entita, id, titolo, testo, fonte_nome, url, data_aggiornamento, affidabilita, casa_nome`.
- `trasi.fonte` — allow-list; la fonte iCal è `Google Calendar-ical-2` (`tipo_accesso='ical'`, `livello_fiducia=2`).
- Ruoli: `automazioni` (esegue i flussi, **non** può scrivere `luogo`/`scheda`/`opportunita`/`casa`), `ti`, `trasi_owner`.
- **`flussi/export_kb.py` esiste già** (fatto in B2, idempotente: verificato — run2 = 0 nuovi). Leggilo e riusalo, non riscriverlo.
- Container `automazioni` **non esiste**: va aggiunto al compose `deployment/docker-compose.yml`. ⚠️ **Quel file è di `trasi-stack`**: coordina via `hub` **prima** di modificarlo, oppure aggiungi un servizio in un file compose separato e concordane l'inclusione.

**Modello di esecuzione (dal piano §8):** logica DB in funzioni SQL; I/O esterno in Python; **cron** come punto d'ingresso primario. Non c'è Activepieces: **non avviarlo** (RAM) — se serve la visibilità no-code è `[S2]`.

## Change

### 1. `db/020_flussi.sql` (tua proprietà)
- tabella **`flusso_run`** (`id, nome, trigger, inizio_ts, fine_ts, esito, n_righe, dettaglio jsonb`) — una riga per esecuzione, `esito ∈ ok|parziale|errore`
- GRANT a `automazioni` (INSERT/SELECT) e `ti`/`metabase_ro` (SELECT)
- eventuali viste di supporto agli alert (§4)

### 2. `flussi/applica.sh` (F9 — `B4-FLW-02`)
```
psql -c "SELECT * FROM trasi.applica_proposte_approvate(200)" → "SELECT trasi.scadi_proposte()" → INSERT flusso_run
```
- una sola transazione; **nessuna** `UPDATE` diretta su `luogo/scheda/evento/opportunita/casa` nel file (`grep -ci update flussi/applica.sh` → 0)
- l'esito va in `flusso_run` (`n_righe`, `esito`, dettaglio con gli eventuali `errore:`)

### 3. `flussi/export_kb.py` (F3 — `B4-FLW-04`) — **esiste già**
Verifica che sia idempotente e che `doc_updated_at` venga aggiornato; aggiungi la scrittura in `flusso_run`. Se serve modificarlo, fallo — è nel tuo scope da qui in avanti.

### 4. `flussi/fonti_ical.py` (F4 — `B4-FLW-06`) — **l'unica scrittura diretta ammessa**
- fetch del feed (timeout 10 s, UA identificativo), parse ICS, finestra −1/+90 giorni
- scrive su `evento` **solo** se la fonte è `tipo_accesso='ical'`; **mai** `DELETE` (usa `annullato=true`)
- **una riga `audit` per variazione** (`azione='ical_upsert'`, `eseguito_da='automazioni'`, `prima`/`dopo`)
- **controllo delta anomalo**: se `|nuovi+rimossi| / max(esistenti,1) > soglia_delta_anomalo_pct` → **nessun upsert**, crea una `proposta` (`origine='coerenza'`) e `fonte_run.esito='anomalo'`
- importa **solo** campi non personali: `SUMMARY`, `DTSTART/DTEND`, `LOCATION`, `URL`. **Mai** `ATTENDEE`/`ORGANIZER`/`DESCRIPTION` (V5)
- se non hai un feed reale, usa una fixture in `flussi/fixtures/casa.ics` e dichiaralo

### 5. `flussi/fonti_http.py` (F4 — `B4-FLW-07`)
- fetch pagina, estrazione del testo dal selettore, hash `sha256`
- se l'hash cambia: **crea proposte** (`origine='fonte_automatica'`), **mai** UPDATE diretto su `luogo`/`scheda`
- dedup: `WHERE NOT EXISTS (proposta aperta stessa entità+fonte)`
- se la pagina è riscritta oltre la soglia → proposta con `payload.anomalo=true`

### 6. `flussi/alert.py` (F6 — `B4-FLW-09`)
- **proposte in attesa da oltre 7 giorni** → email al ruolo competente (`gestore` della Casa se `approvatore_ruolo='gestore'`, altrimenti AT)
- **coerenza fonti**: silente / errore / delta anomalo / validazione scaduta
- invio **SMTP**; per i test usa una casella locale (Mailpit) o **scrivi su file** se SMTP non è configurato — dichiara quale
- template in italiano ≤ 15 righe con i **4 campi V6**: *cosa è stato osservato / su quale evidenza / cosa si potrebbe fare / chi decide*. **Nessun imperativo** verso persone o Case

### 7. `flussi/crontab` + wrapper
- `01:00` export KB · `05:00` applica+scadi · `06:00` fonti+coerenza · `07:30` alert
- ogni script eseguibile a mano e ripetibile (idempotente)

## Constraints

- **V4** — l'unica scrittura diretta al dominio ammessa è **`evento` da fonte iCal**. Tutto il resto passa da `proposta`. Se ti accorgi che un flusso aggira il meccanismo, **fermati e segnala**: non implementarlo.
- **V5/§12** — mai campi personali negli eventi importati; `motivazione` ≤ 80; nessun dato personale nelle email.
- **V6** — i messaggi dicono **chi decide**, non assegnano compiti. Verifica con un check lessicale automatico sui template (nessun `devi|dovete|fai|fate|assegna|contatta`).
- **Idempotenza**: ogni flusso rieseguito senza duplicati (2ª esecuzione = stesso esito, 0 righe nuove). È il tuo criterio principale.
- Non toccare `db/000–012` (B1), `shim/**` (B3), `flussi/export_kb.py` nella parte già verificata.
- RAM: ~6 GB liberi. Non avviare container pesanti (niente Activepieces, niente Metabase).

## Ownership

`flussi/**`, `db/020_flussi.sql`. Il compose è di `trasi-stack`: coordina via `hub`.

## Observable acceptance (prove reali)

1. `db/020_flussi.sql` applicato; `flusso_run` esiste con i GRANT corretti.
2. **Il criterio §10 B4**: fixture con 2 proposte `approvata` + 1 scaduta da 31 giorni → `applica.sh` → `applica=2, scaduta=1`; **3 righe `audit`**; `flusso_run` esito `ok`; `affidabilita=2` + `fonte_id` + `data_aggiornamento` sulla promossa da esterno.
3. **Idempotenza**: `applica.sh` due volte → 2ª non cambia nulla (`applica=0`, `audit` invariato).
4. **`grep -ci update flussi/applica.sh` → 0** (nessuna scrittura diretta nel file).
5. iCal: feed con 1 orario cambiato → 1 `UPDATE` su `evento` + **1 riga `audit` `ical_upsert` con `prima`≠`dopo`**; rerun identico → 0 nuove scritture; feed con 80% di eventi rimossi → **0 upsert**, 1 `proposta` `origine='coerenza'`, `fonte_run.esito='anomalo'`.
6. `fonti_http.py`: fixture cambiata → 1 `proposta` `origine='fonte_automatica'`, `approvatore_ruolo='at'`; **`luogo.orari` invariato** (diff allegato); rerun → nessun duplicato.
7. Alert: proposta vecchia di 8 giorni → email/messaggio al **destinatario giusto**, con i 4 campi V6; check lessicale su tutti i template → 0 verbi imperativi.
8. `export_kb.py` dopo `applica.sh` → il documento toccato ha `doc_updated_at` aggiornato e la chat lo cita il giorno dopo.

Riporta comandi e output reali. Se un criterio è rosso, dillo.

## Nota
Il piano è in `plan.md` (§4 B4, §8 flussi F3/F4/F6/F9), l'architettura in `docs/trasi-architecture-v1.2.md` (§8, §6 cron, §12). In conflitto **vince l'architettura**. Il log delle verifiche precedenti è in `docs/verifiche.md`: leggilo per non rifare scoperte già fatte (es. Overpass richiede UA identificativo).
