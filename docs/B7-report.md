# B7 — E2E: report della sessione con le user stories

**Data:** 2026-09-16 · **Ambiente:** stack Trasi completo (6 servizi healthy) + Onyx v4.7.2
**Modalità:** esecuzione via API/DB con **identità reali** (account `op.*`, `gestore.*`, `rete`), non come amministratore
**Criterio del piano:** ≥ 7/8 user stories passate · risposta chat < 2 min · biglietto stampato · backlog al TI

---

## Esito sintetico: **6/8 PASS + 2 parziali** su quanto verificabile senza operatori umani

| ID | User story | Esito | Prova |
|---|---|---|---|
| **US-01** | Orientamento con biglietto | ✅ **PASS** | `CAF ACLI La Rosa` **a 506 m** con `[KB · ACLI — patronato · affidabilità 1]`; 2 tool call; **3,9 s**; offre il biglietto |
| **US-02** | Informazione mancante → astensione | ✅ **PASS** | «Non trovo informazioni sul Consolato del Bangladesh…» + **nessuna invenzione** + alternativa reale dal KB con etichette |
| **US-03** | Interculturale con destinazione obbligatoria | ✅ **PASS** | `registra_richiesta` con `esito='inviata_altrove'` senza destinazione → **422**; nessuna traduzione dall'AI |
| **US-04** | Presidio (solitudine) | ✅ **PASS** | Ordine rispettato: **1) psicologa di comunità Parco Buscicchio** (servizio interno) → 2) presidio d'ascolto → 3) aggregazione over 60. Nessuna offerta di compagnia |
| **US-05** | Ciclo mensile | ⚠️ **PARZIALE** | `ops/ciclo_mensile.sh --forza` → **11 messaggi + CSV**, `flusso_run: trigger=cron esito=ok`. **Non consegnati**: SMTP non configurato (dichiarato). k-anonimato verificato separatamente |
| **US-06** | Bando scaduto | ✅ **PASS** | Opportunità scaduta: **0** in `v_kb_export` (non citabile), **1** in `v_scaduti` (alert) |
| **US-07** | Scrittura solo propria Casa | ⚠️ **PARZIALE** | Bozzano su proposta di San Bao → **`UPDATE 0`** ✅; **auto-approvazione vietata** ✅ (`no_self_approve`); ⚠️ **l'approvazione da `gestore.san-bao` NON si riproduce**: 403 `da approvare in coda` (v. «Rettifica US-07» sotto) |
| **US-08** | Domanda ibrida + proposta | ✅ **PASS** | Segnalazione «il bar ha chiuso» → **`proponi_modifica`** → proposta `chiudi_luogo` `approvatore='at'`; **`luogo` invariato** (V4) |

**6 PASS + 2 parziali su 8.** Un parziale non è un difetto dello stack: è l'**SMTP non configurato**, azione del TI. L'altro è la rettifica di US-07 (sotto), che è un **difetto reale** e non una questione di ambiente.

> ⚠️ **Rettifica del 2026-09-17.** La riga US-07 di questa tabella dichiarava un `PASS` che **non si
> riproduce**. Vedi «Rettifica US-07» in fondo: la prova è stata rieseguita e il comportamento è
> diverso da come era stato verbalizzato.

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

## Verifica di merito su `no_self_approve` (RETTIFICATA il 2026-09-17)

Il piano (`§7`) aveva come domanda aperta: *«operatore e gestore della stessa Casa condividono il ruolo DB → l'operatore approva in chat le proprie proposte?»*.

**Questa sezione affermava il falso.** Diceva che la policy distingue per **persona (email)** e che
`gestore.san-bao` **può approvare** la proposta di `op.san-bao` (`UPDATE 1`). Rieseguita identica il
2026-09-17, la prova dà l'esito opposto:

```
1) op.san-bao propone   -> 201 id=3980
   proposto_da registrato dal trigger: casa_sanbao    <- è il RUOLO DB, non l'email
2) gestore.san-bao approva -> 403 {"detail":"da approvare in coda"}
   stato: proposta
```

**Causa.** `proposta_00_default_tg` forza `proposto_da := current_user`, e per entrambe le identità di
una Casa `current_user` è **lo stesso ruolo DB** (`casa_sanbao`): lo shim autentica per email ma entra
nel ruolo con `SET LOCAL ROLE`, e il database vede solo quello. La policy `no_self_approve` confronta
`proposto_da` con `current_user` — quindi confronta `casa_sanbao` con `casa_sanbao` e **blocca anche il
gestore**. La frase «l'identità che conta è l'email» era un'inferenza, non una misura: il database non
vede mai l'email.

**Conseguenza misurata.** La coda è un vicolo cieco per **5 tipi di proposta su 12** — quelli con
`approvatore_ruolo = 'gestore'`: `modifica_scheda`, `nuova_scheda`, `modifica_evento`,
`nuova_opportunita`, `modifica_orari_casa`. Provata l'approvazione da 5 identità diverse
(`gestore.san-bao`, `op.san-bao`, `gestore.bozzano`, `op.bozzano`, `rete`): **tutte 403**. Le proposte
`at` (gli altri 7 tipi) funzionano, perché le decide `rete`/`ti` — una Casa diversa.

**Prova storica.** Nessuna riga di `trasi.proposta` ha mai avuto `proposto_da = approvato_da`: le
proposte `gestore` sono state approvate **solo** quando proposte da `rete`.

**Cosa resta vero di questa sezione:**
- `op.san-bao` **non può** approvare la propria proposta → **auto-approvazione vietata** ✅ (protezione
  efficace, ed è il motivo per cui la policy esiste);
- un trigger impedisce di modificare `proposto_da` a posteriori → **l'audit trail non è falsificabile** ✅.

**Cosa NON è vero:** che la condivisione del ruolo DB sia innocua. **È la causa del vicolo cieco.**

**Stato: non riparata in questa sede.** Cambiare `proposto_da` da ruolo DB a email — o ammettere
l'auto-approvazione entro la stessa Casa — modifica la regola di governance di `plan.md` §394: è una
decisione per il gruppo Processi, tracciata in `docs/verifiche-caccia-2026-09-17.md` (BUG-02). La riga
US-07 della tabella in testa è stata corretta da `PASS` a `PARZIALE` di conseguenza.

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

Ambiente pronto: Trasi Home su `trasi.lascuolaopensource.org` (serve l'**ingress Cloudflare**, azione TI), **22 account** — tutte le identità di `trasi.identita_onyx` (op e gestore per 10 Case, più `rete` e `ti`) —, KB popolata (32 documenti), stampante da collegare.

> **Aggiornato il 2026-09-17.** Qui erano elencati **6** account (`op.`/`gestore.` per San Bao e
> Bozzano, più `rete` e `ti`): le altre **16** identità esistevano nel database ma **non avevano
> accesso a Onyx**, quindi 8 Case su 10 erano di fatto inaccessibili. Create con
> `ops/provisiona_utenti_onyx.sh` (idempotente, `--dry-run` disponibile; v. `docs/runbook.md` §11.2).
> La password è in `deployment/.env` → `TRASI_UTENTI_PASSWORD` (mode 600, gitignored): prima quella
> riga di `README.md` era **falsa**, le password non erano in nessun file del progetto.

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
