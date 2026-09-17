# TASK SPEC — B6 Trasi Home + Ops (`trasi-ux` e `trasi-stack`)

## Target

### Parte A — `trasi-ux`: Trasi Home
La pagina d'ingresso **unica** del progetto (§4.3): una pagina statica che apre le 4 destinazioni con la **Casa dell'operatore preselezionata**. Oggi è un segnaposto.

### Parte B — `trasi-stack`: ops
Cron, backup/restore con prova reale, retention, runbook.

## Contesto verificato

**Endpoint già funzionante** (usalo per la riga «Oggi»):
```
GET /v1/u/{email}/oggi   → {"casa":"bozzano","eventi":1,"schede_in_scadenza":0,"proposte":0,
                            "testo":"Oggi a Centro di Aggregazione Bozzano: 1 evento · 0 schede in scadenza · 0 proposte"}
```
Header richiesto: `X-Trasi-Key` (in `deployment/.env`). Se `casa` è omessa, la deduce dall'identità.

**Pagine pubblicate:**
- **Home** → conversazione con l'assistente, già nella sessione della Casa
- **Osservatorio** → mappa, elenco equivalente e scheda dei luoghi
- **Account** → dati della Casa, proposte e funzioni operative

La mappa vive nell'Osservatorio e la sezione «Registra» vive nell'Account. La coda delle proposte è visibile
nella riga dell'Account e nella sezione «Proposte».

**Servizi attivi:** `db_trasi`, `searxng`, `shim`, `automazioni`, `metabase` — tutti healthy. Caddy è definito e **non avviato** (serve per servire la Home + i sottodomini).

## Change — Parte A (Trasi Home)

- `index.html` è l'accesso; `home.html`, `osservatorio.html` e `account.html` sono le pagine della shell; CSS/JS **vanilla**, zero CDN
- `lang="it"`, font base **≥ 16 px**, contrasto **≥ 4,5:1**, focus visibile, navigabile da tastiera tra Home, Osservatorio e Account
- **Casa della sessione** letta dal cookie HttpOnly; nel browser non entra alcun dato personale
- **Riga della coda** che dichiara il numero di proposte quando la lettura risponde; se lo shim non risponde → «dati non disponibili»
- Le pagine e le otto sezioni dell'Account sono collegamenti o controlli nativi

### 2. Caddy
- serve `home/` su `/` dell'hostname `trasi.lascuolaopensource.org`
- **attenzione**: Onyx **non ha basePath** → sta su sottodominio separato (`onyx.lascuolaopensource.org`), raggiunto via rete Docker `onyx_default` (alias `nginx`), **non** via `host.docker.internal` (verificato: non raggiungibile)
- ⚠️ Il Caddyfile è di `trasi-stack` (B0): **coordina via `hub`** prima di modificarlo

### 3. Accessibilità (V-08)
- checklist WCAG 2.1 AA con misura reale su contrasto, tastiera, focus
- le checklist su Onyx/Metabase/NocoDB sono `[S2]` per il piano: **dichiara che sono rinviate**, non spacciarle per fatte

## Change — Parte B (ops, `trasi-stack`)

### 4. Cron + backup
- `ops/crontab` con i job del piano: **01:00** export KB · **02:00** backup · **03:00** retention chat · **05:00** applica_proposte · **06:00** coerenza fonti · giorno `[P]` **3** ciclo mensile
- ⚠️ I flussi **esistono già** (`flussi/crontab`, `flussi/job.sh`, `automazioni`): **non duplicarli**. Coordina via `hub` con `trasi-flussi`: al massimo aggiungi ciò che manca (es. backup, retention).
- `ops/backup.sh`: `pg_dump` + **`pg_dumpall --globals-only`** (i ruoli non stanno nel dump del DB) + rotazione
- **Prova di restore reale**: non solo lo script — esegui un restore su un DB di prova e mostra `count(casa)=10`.

### 5. Retention chat
- Onyx ha la sua retention (`[P] gg_retention_chat=30`, parametro in Trasi). Verifica **dove** Onyx conserva i messaggi e se ha una retention nativa: se sì usala, se no scrivi lo script e **documenta il gap**.

### 6. Runbook (`docs/runbook.md` o in `deployment/README.md`)
start/stop, backup, restore, retention, rollback, rotazione segreti. Comandi reali, non descrizioni.

## Constraints

- **V6**: nessun testo imperativo verso persone o Case nella Home (è una porta, non un cruscotto che ordina).
- **V5**: in `localStorage` solo lo slug della Casa; nessun dato personale.
- **RAM**: ~3,9 GB liberi (Metabase è al 98% del suo limite: **segnalalo** se peggiora, non alzarlo).
- Non modificare `db/**`, `shim/**`, `flussi/**`. `deployment/docker-compose.yml` e `caddy/Caddyfile` sono di `trasi-stack`: per A, coordina via `hub`.
- NocoDB non è avviato: **predisponi** il link e dichiara che è inattivo, non avviarlo (RAM).

## Observable acceptance

**Parte A:**
1. Home servita da Caddy; peso ≤ 30 KB; `grep` per URL esterni → **0**.
2. Selettore Casa: scelgo Bozzano → ricarico → resta Bozzano e i 4 `href` la contengono (screenshot o dump degli `href`).
3. Riga «Oggi»: mostra il `testo` dello shim; con shim fermo → «dati non disponibili» entro 3 s (provalo davvero, fermando il container o simulando il timeout).
4. `curl https://onyx.lascuolaopensource.org/app?agentId=2` → 200 con l'assistente preselezionato.
5. Checklist WCAG compilata con le misure reali (contrasto, tastiera, focus); le 3 app esterne **dichiarate rinviate a S2**.

**Parte B:**
6. `ops/backup.sh` eseguito → file prodotto con timestamp; **restore su DB di prova → `count(casa)=10`**.
7. `crontab -l` → i job presenti.
8. Runbook con comandi eseguiti e output.

Riporta comandi e output reali. Se un criterio è rosso, dillo.

## Nota
Piano: `plan.md` (§4 B6, §10 B6/B7, §8 runbook). Architettura: §4.3 (Home), §4.6 (accessibilità), §6 (cron), App. B. In conflitto **vince l'architettura**. **Leggi `docs/verifiche.md`**: contiene scoperte già fatte (i flussi esistono, `automazioni` ha un healthcheck corretto con `pidof`, Onyx usa id URL-encoded) che non devi riscoprire.
