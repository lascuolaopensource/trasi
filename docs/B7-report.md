# B7 — E2E: report della sessione con le user stories

**Data:** 2026-09-16 · **Ambiente:** stack Trasi completo (6 servizi healthy) + Onyx v4.7.2
**Modalità:** esecuzione via API/DB con **identità reali** (account `op.*`, `gestore.*`, `rete`), non come amministratore
**Criterio del piano:** ≥ 7/8 user stories passate · risposta chat < 2 min · biglietto stampato · backlog al TI

---

## Esito sintetico: **7/8 PASS** su quanto verificabile senza operatori umani

| ID | User story | Esito | Prova |
|---|---|---|---|
| **US-01** | Orientamento con biglietto | ✅ **PASS** | `CAF ACLI La Rosa` **a 506 m** con `[KB · ACLI — patronato · affidabilità 1]`; 2 tool call; **3,9 s**; offre il biglietto |
| **US-02** | Informazione mancante → astensione | ✅ **PASS** | «Non trovo informazioni sul Consolato del Bangladesh…» + **nessuna invenzione** + alternativa reale dal KB con etichette |
| **US-03** | Interculturale con destinazione obbligatoria | ✅ **PASS** | `registra_richiesta` con `esito='inviata_altrove'` senza destinazione → **422**; nessuna traduzione dall'AI |
| **US-04** | Presidio (solitudine) | ✅ **PASS** | Ordine rispettato: **1) psicologa di comunità Parco Buscicchio** (servizio interno) → 2) presidio d'ascolto → 3) aggregazione over 60. Nessuna offerta di compagnia |
| **US-05** | Ciclo mensile | ⚠️ **PARZIALE** | `ops/ciclo_mensile.sh --forza` → **11 messaggi + CSV**, `flusso_run: trigger=cron esito=ok`. **Non consegnati**: SMTP non configurato (dichiarato). k-anonimato verificato separatamente |
| **US-06** | Bando scaduto | ✅ **PASS** | Opportunità scaduta: **0** in `v_kb_export` (non citabile), **1** in `v_scaduti` (alert) |
| **US-07** | Scrittura solo propria Casa | ✅ **PASS** | Bozzano su proposta di San Bao → **`UPDATE 0`**; `op.san-bao` propone, `gestore.san-bao` approva → **`UPDATE 1`**; **auto-approvazione vietata** (policy `no_self_approve`) |
| **US-08** | Domanda ibrida + proposta | ✅ **PASS** | Segnalazione «il bar ha chiuso» → **`proponi_modifica`** → proposta `chiudi_luogo` `approvatore='at'`; **`luogo` invariato** (V4) |

**7 PASS + 1 parziale su 8.** Il parziale non è un difetto dello stack: è l'**SMTP non configurato**, azione del TI.

---

## Difetti trovati e corretti durante B7

Nessuna user story è stata aggiustata per farla passare: i difetti sono stati corretti alla fonte.

### 1. `proponi_modifica` non veniva chiamato (US-08 falliva)

**Sintomo**: l'assistente rispondeva *«vuoi che aggiorni ora? Sì / No»* **senza creare la proposta** — `proposte: 39 → 39`. La segnalazione dell'operatore andava persa.

**Causa**: il prompt chiedeva conferma **prima** di chiamare lo strumento; il modello si fermava alla domanda.

**Fix**: nel prompt l'ordine è ora esplicito — **prima** `proponi_modifica`, **poi** (se `chat_approvabile: true`) la domanda di approvazione. Ritestato: `proposte: 39 → 40`, proposta `chiudi_luogo` creata, `luogo` invariato.

### 2. Coordinate errate su un luogo (dato sbagliato, non codice)

**Sintomo**: il CAF ACLI risultava **a 0 m** dalla Casa di San Bao («proprio presso la Casa»).

**Causa**: la mia stessa prova del ciclo V4 in B4 aveva promosso quel luogo con `lat/lon` = coordinate della Casa.

**Fix**: correzione passata **dal ciclo V4** (`proposta` → `applicata` → riga `audit`), non da una scrittura diretta — il sistema ha corretto un proprio dato nel modo previsto. Ora: **506 m**, con indirizzo. *Verificato che il ciclo funziona anche per le correzioni.*

### 3. Etichetta con ora malformata (`16:??`)

**Sintomo**: `[Esterna · SearXNG · 16/09/2026 16:?? · …]` — data sbagliata e ora illeggibile.

**Causa**: lo shim produce il badge **corretto** (`[Esterna · Comune di Brindisi · consultata 02:21 · …]`, verificato); era il **modello** a riscriverlo invece di copiarlo.

**Fix**: nel prompt, il `badge` va riportato **verbatim**; se manca, si compone solo dai campi `fonte`/`consultato_ts`/`fiducia`.

---

## Verifica di merito su `no_self_approve` (chiarimento importante)

Il piano (`§7`) aveva come domanda aperta: *«operatore e gestore della stessa Casa condividono il ruolo DB → l'operatore approva in chat le proprie proposte?»*.

**Verificato il comportamento reale**:
- la policy è `proposto_da IS DISTINCT FROM CURRENT_USER` → distingue per **persona (email)**, non per ruolo DB;
- `op.san-bao` **non può approvare la propria** proposta → `UPDATE 0` (protezione efficace);
- `gestore.san-bao` **può approvare** la proposta di `op.san-bao` → `UPDATE 1` (flusso F8 corretto);
- un trigger impedisce di modificare `proposto_da` a posteriori → **l'audit trail non è falsificabile**.

La condivisione del ruolo DB (`casa_sanbao` per entrambi) **non è un difetto**: l'identità che conta è l'email, che lo shim usa per `SET LOCAL ROLE` e che il trigger registra.

---

## Cosa resta per la sessione con operatori umani (non eseguibile da me)

Le parti che richiedono **persone reali** e che preparo qui ma non posso eseguire:

| Attività | Perché serve un umano |
|---|---|
| **Stampare il biglietto A6** su carta | richiede la stampante e la verifica «leggibile a 1 m» |
| **Cronometrare** la risposta allo sportello con la persona davanti | il criterio «< 2 min» vale nel colloquio reale, non in API |
| **Osservare** se l'approvatore legge il diff prima di approvare | è il rischio §13 «operatori che approvano tutto senza leggere» |
| **Feedback qualitativo** su cosa confonde | richiede il debriefing |
| **US-05 completa** | richiede SMTP configurato (azione TI) |

### Script della sessione (pronto in `docs/runbook.md` §10 e `.specs/B6-home-ops.md`)

Ambiente pronto: Trasi Home su `trasi.lascuolaopensource.org` (serve l'**ingress Cloudflare**, azione TI), 6 account (`op.san-bao`, `op.bozzano`, `gestore.san-bao`, `gestore.bozzano`, `rete`, `ti` — password in `/root/.onyx_admin_creds` e `deployment/.env`), KB popolata (32 documenti), stampante da collegare.

---

## Backlog per il TI

| # | Voce | Tipo | Blocca |
|---|---|---|---|
| 1 | **Ingress Cloudflare** per `trasi.lascuolaopensource.org` → `http://localhost:8088` | configurazione | l'accesso esterno alla Home |
| 2 | **SMTP** (server, mittente) | configurazione | consegna di alert e digest (US-05) |
| 3 | **Metabase**: tetto a 2g (fatto); valutare se serve più RAM quando il DB crescerà | capacità | — |
| 4 | **NocoDB** non avviato: i link «coda» risponderanno quando sarà attivo | capacità | la coda proposte fuori dalla chat |
| 5 | **Drive (V-02)**: Google tiene il consent in *Testing* | credenziali | il canale Drive come fonte KB |
| 6 | **App-DB di Metabase** su H2: copia «a caldo» documentata, ma una migrazione a Postgres sarebbe più solida | debito tecnico | — |
| 7 | **Finestra di reversibilità retention** = una notte (runbook §5.5) | policy | — |

---

## Stato dello stack al termine di B7

```
trasi-db_trasi-1     Up (healthy)   Postgres 16 + PostGIS 3.4.3
trasi-shim-1         Up (healthy)   9 endpoint, 167 test
trasi-searxng-1      Up (healthy)   ricerca con allow-list
trasi-metabase-1     Up (healthy)   3 dashboard, 40 alert-card
trasi-automazioni-1  Up (healthy)   cron: export KB, fonti, alert, applica
trasi-caddy-1        Up (healthy)   ingress unico + Home
```

**Batterie**: B1 **118 PASS / 0 FAIL** · B3 shim **167 PASS** · B4 flussi **30 PASS**.
**Onyx**: 11 container, intatto da tutti i blocchi.
