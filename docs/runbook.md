# Trasi — Runbook operativo (blocco B6, §8 del piano)

Comandi **eseguiti**, non descritti. Dove l'output è riportato, è quello reale di questo host
(`sergio`, 2026-09-16). Dove un comando non è stato eseguito, è dichiarato come tale.

> **Radice del progetto:** `/root/orca/projects/onice`. Tutti i percorsi qui sotto sono relativi a
> quella directory se non è indicato altrimenti; gli script fanno `cd "$(dirname "$0")/.."` da soli,
> quindi funzionano da qualunque directory.

## 0 · Mappa dei servizi, e chi possiede cosa

| Servizio | Container | Proprietà | Porta host (loopback) |
|---|---|---|---|
| Database dominio | `trasi-db_trasi-1` | Trasi | `127.0.0.1:5432` |
| Ricerca web | `trasi-searxng-1` | Trasi | **nessuna** (solo rete Docker) |
| Shim (contratto V-09) | `trasi-shim-1` | Trasi | `127.0.0.1:8001` |
| Flussi notturni | `trasi-automazioni-1` | Trasi | **nessuna** |
| Dashboard | `trasi-metabase-1` | Trasi | `127.0.0.1:3001` |
| Ingresso unico | `trasi-caddy-1` | Trasi | `127.0.0.1:8088` (HTTP), `127.0.0.1:8443` (diagnostica) |
| CRM / coda | `nocodb` | Trasi | `127.0.0.1:8081` — **non avviato** (RAM) |
| Activepieces | `activepieces` + `ap_postgres` + `ap_redis` | Trasi | `127.0.0.1:8082` — **non avviato** (RAM) |
| **Onyx** (11 container) | `onyx-*` | **installazione separata** | `127.0.0.1:80`, `:3000` |

**Il confine:** questo runbook non avvia, ferma o riconfigura Onyx. Onyx ha il suo compose
(`/opt/onyx/deployment/`) e la sua vita. Le uniche operazioni di questo runbook che **leggono** Onyx
sono il backup delle chat e la retention — ed entrambe sono dichiarate come tali nel loro punto.

---

## 1 · Start / Stop

### Avvio selettivo (la scelta di B0, motivata dalla RAM)

L'host ha 16 GB condivisi con Onyx (~6 GB). La somma dei `mem_limit` dei servizi Trasi è **5,08 GiB**
più **320 MiB** per il Postgres/Redis di Activepieces. **Avviare tutto è over-commit.** L'avvio
selettivo è la regola, non un'eccezione:

```bash
cd /root/orca/projects/onice
docker compose -f deployment/docker-compose.yml up -d db_trasi searxng shim automazioni metabase caddy
```

Misurato dopo questo avvio (2026-09-16):

```
$ docker compose -f deployment/docker-compose.yml ps --format '{{.Service}}\t{{.Status}}'
automazioni   Up (healthy)
caddy         Up (healthy)
db_trasi      Up (healthy)
metabase      Up (healthy)
searxng       Up (healthy)
shim          Up (healthy)

$ docker stats --no-stream --format '{{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}' | grep trasi
trasi-automazioni-1   7.586MiB / 256MiB    2.96%
trasi-caddy-1         33.09MiB / 128MiB    25.85%
trasi-metabase-1      1.367GiB / 1.5GiB    91.13%    ← stretto, v. §1.3
trasi-shim-1          62.12MiB / 256MiB    24.27%
trasi-searxng-1       152.1MiB / 512MiB    29.70%
trasi-db_trasi-1      262.5MiB / 1GiB      25.64%
```

**`nocodb` e `activepieces` restano spenti** e non sono necessari al funzionamento: NocoDB è una
destinazione della Home (link predisposto, dichiarato inattivo), Activepieces è stato sostituito da
`automazioni` (§6, decisione di B4).

### 1.1 · Verifica che i servizi *funzionino*, non solo che siano `Up`

Un container `healthy` dice che l'healthcheck passa, non che il servizio risponde. Le tre prove che
contano:

```bash
# shim — il contratto V-09
$ curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8001/healthz
200

# Caddy — la Home servita (richiede l'header Host: il sito è per hostname)
$ curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: trasi.lascuolaopensource.org' http://127.0.0.1:8088/
200

# Caddy → shim → database: la catena della riga «Oggi», end-to-end
$ curl -s -H 'Host: trasi.lascuolaopensource.org' \
    'http://127.0.0.1:8088/api/shim/v1/u/rete@trasi.local/oggi?casa=bozzano'
{"casa":"bozzano","eventi":0,"schede_in_scadenza":0,"proposte":0,
 "testo":"Oggi a Centro di Aggregazione Bozzano: 0 eventi · 0 schede in scadenza · 0 proposte"}

# Onyx, dalla rete interna (non è di questo stack)
$ curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:80/api/health
200
```

### 1.2 · Caddy: due difetti reali trovati avviandolo

Il Caddyfile di B0 **non funzionava** su questo host. Entrambi i difetti sono stati trovati avviando
il servizio e provando l'endpoint, non leggendo la configurazione — ed entrambi sono corretti ora:

1. **`auto_https` di default** → Caddy tentava Let's Encrypt (impossibile: la validazione ACME passa
   dal dominio pubblico, non da questo host) e rispondeva `308 → https://` su ogni richiesta HTTP.
   Il tunnel Cloudflare inoltra **in HTTP**, quindi riceveva un redirect verso un host che non ha un
   certificato → **525**. Corretto con `auto_https off`.
2. **I blocchi sito ascoltavano solo su `:443`** — `{$TRASI_DOMAIN}` è un nome con hostname, e Caddy
   per esso sceglie il server HTTPS. Su `:80` la connessione veniva **azzerata**:
   `Recv failure: Connection reset by peer`. Corretto con `http://{$TRASI_DOMAIN}` e
   `http://{$ONYX_DOMAIN}`: TLS è del tunnel, il server che serve è quello HTTP.

### 1.3 · Metabase: il limite è 2g (era 1.5g), e l'uso reale è più basso di quanto sembri

> **Aggiornato 2026-09-16 (decisione del TI, blocco B7).** Il `mem_limit` di Metabase è passato da
> **1.5g a 2g** con `JAVA_OPTS=-Xmx1g` **invariato**: l'heap resta governato da `-Xmx`, e il tetto
> più alto lascia spazio all'overhead fuori dall'heap (metaspace, stack dei thread, GC, mmap). La
> scelta è del TI ed è documentata nel README di `deployment/`.

**Il numero da guardare non è la percentuale di `docker stats`.** `docker stats` (e
`cgroup.memory.current`) includono la **page cache** del container, che è memoria *file-backed* e
**reclamabile**: non è memoria che il processo sta usando, ed è il motivo per cui «92%» faceva
sembrare Metabase sull'orlo dell'OOM mentre non lo era. Il numero che conta è **`anon`**
(heap + dati del processo, non reclamabile). Misura reale dopo il carico (§ sotto):

```
$ CID=$(docker inspect trasi-metabase-1 --format '{{.Id}}')
$ cat /sys/fs/cgroup/system.slice/docker-$CID.scope/memory.stat
anon    = 1199 MiB   ← memoria vera del processo (heap 1 GB + metaspace/thread/GC)
file    =  645 MiB   ← page cache, RECLAMABILE sotto pressione
current = 1873 MiB   su max 2048 MiB
peak    = 1980 MiB
memory.events → oom_kill 0
```

**Carico provato** — quello che B7 genererà (4 operatori che girano le dashboard), 40 query di card
in parallelo su 4 sessioni:

```
$ for op in 1 2 3 4; do ( for c in 54 55 56 57 58 59 60 61 62 63; do
    curl -s -X POST "http://127.0.0.1:3001/api/card/$c/query" -H "X-Metabase-Session: $TOKEN" -o /dev/null
  done ) & done; wait
40 query concorrenti concluse → anon 1199 MiB · peak 1980 MiB · oom_kill 0
```

Ogni card risponde in **30–70 ms** (una, a freddo, 410 ms), e 10 query in serie muovono l'`anon` di
**~3 MiB**: il carico di lettura non alloca in modo significativo, perché le card leggono viste già
aggregate.

**Storia del difetto:** con il tetto a 1.5g il container stava al **92-93% di `memory.current`**, cioè
con ~100 MiB di margine *apparente* — e nessun margine reale se si guarda l'`anon`. Il riavvio
registrato in B5 (`RestartCount=1`) era una **ricreazione** (`docker compose up`), non un crash:
verificato, `FinishedAt` del container vecchio e `StartedAt` del nuovo distano **0,28 s**, con
`ExitCode=0` e `OOMKilled=false`. Le 4 occorrenze di «out of memory» nei log di Metabase sono
**falsi positivi**: sono nomi di autore di changeset Liquibase (`heypoom`, `phoomparin`), non errori
di memoria — `grep -i oom` su quel log non è una prova di OOM.

### 1.4 · Stop

```bash
docker compose -f deployment/docker-compose.yml down
```

I dati stanno nei named volume (`db_trasi_data`, `metabase_data`, `caddy_data`, …) e
sopravvivono. **Onyx non viene toccato**: verificato, `down` rimuove solo i container `trasi-*` e
lascia `onyx_default` in vita finché un container Onyx vi è attestato (`Resource is still in use`).

### 1.5 · Prova di stop/start su un servizio singolo (eseguita)

```bash
$ docker compose -f deployment/docker-compose.yml stop shim
 Container trasi-shim-1 Stopped
$ curl -s -o /dev/null -w '%{http_code}\n' --max-time 4 http://127.0.0.1:8001/healthz
000                                    # nessuna risposta: il servizio è fermo

# e la catena della Home, con lo shim fermo:
$ curl -s -o /dev/null -w '%{http_code}\n' --max-time 6 -H 'Host: trasi.lascuolaopensource.org' \
    'http://127.0.0.1:8088/api/shim/v1/u/rete@trasi.local/oggi?casa=bozzano'
502                                    # Caddy risponde, lo shim no: è il caso che la Home deve gestire

$ docker compose -f deployment/docker-compose.yml start shim
$ curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8001/healthz
200
```

**Perché questa prova conta:** la Home deve funzionare **con lo shim fermo** (timeout 3 s →
«dati non disponibili», mai un errore grezzo). Il `502` qui sopra è ciò che la Home vede in quel
caso, e il tempo di risposta è immediato: il frontend deve mettere un `AbortController` a 3 s per
non lasciare la riga appesa.

---

## 2 · Cron

**Due crontab, due proprietari, nessuna sovrapposizione.** Otto righe di schedulazione per i sei job
del piano §6:

| Ora | Job | Dove | Owner |
|---|---|---|---|
| **01:00** | export KB (F3) | `flussi/crontab` → container `automazioni` | B4 |
| **02:00** | **backup** | `ops/crontab` → host | **B6** |
| **03:00** | **retention chat** | `ops/crontab` → host | **B6** |
| **05:00** | `applica_proposte` (F9) | `flussi/crontab` → container `automazioni` | B4 |
| **06:00** | coerenza fonti iCal (F4) | `flussi/crontab` → container `automazioni` | B4 |
| **06:15** | coerenza fonti HTTP (F4) | `flussi/crontab` → container `automazioni` | B4 |
| **07:30** | alert (F6) | `flussi/crontab` → container `automazioni` | B4 |
| **giorno 3, 08:00** | **ciclo mensile** (F5) | `ops/crontab` → host, codice di `flussi/` | **B6** schedula / B4 esegue |

### 2.1 · Perché due file e non uno

`flussi/crontab` schedula i **flussi di dominio**: girano come ruolo `automazioni`, scrivono in
`flusso_run`, passano da `proposta` → approvazione. I job di `ops/crontab` sono di **esercizio**: non
toccano la memoria, non hanno un ruolo applicativo, non producono righe in `flusso_run`. E soprattutto
toccano cose che il container `automazioni` **non ha e non deve avere** (il socket Docker, i volumi,
il database di Onyx): dar glielo significherebbe dare a un esecutore del dominio il controllo
dell'host. La separazione è stata concordata via `hub` con `trasi-flussi`.

### 2.2 · Il difetto che questo formato previene

Un crontab installato nel **formato sbagliato** non fallisce: **tace**. Se un file `/etc/cron.d` (con
il campo utente) viene installato come crontab utente, `cron` legge l'utente come primo token del
comando:

```
$ cat /tmp/log_cron
/bin/sh: 1: root: not found
```

Tutti i job morti, `crontab -l` che mostra le righe, e nessun altro sintomo.
`ops/install_cron.sh` **rifiuta** una riga così invece di installarla:

```
$ ops/install_cron.sh --file <crontab-col-campo-utente> --dry-run
  FAIL  il 6° campo non è un percorso assoluto: «0 2 * * *   root  /root/.../backup.sh»
        (se il 6° campo è un nome utente, la riga è in formato /etc/cron.d)
install_cron.sh: 1 righe malformate — NON installo.
EXIT=1
```

### 2.3 · Installazione (eseguita)

```bash
$ ops/install_cron.sh
── validazione della forma
  PASS  backup.sh          ← 0 2 * * *
  PASS  retention_chat.sh  ← 0 3 * * *
  PASS  ciclo_mensile.sh   ← 0 8 3 * *
── esistenza dei comandi
  PASS  /root/orca/projects/onice/ops/backup.sh
  PASS  /root/orca/projects/onice/ops/ciclo_mensile.sh
  PASS  /root/orca/projects/onice/ops/retention_chat.sh
install_cron.sh: installato e verificato
```

```bash
$ crontab -l
0 2 * * *   /root/orca/projects/onice/ops/backup.sh >> /var/log/trasi/backup.log 2>&1
0 3 * * *   /root/orca/projects/onice/ops/retention_chat.sh >> /var/log/trasi/retention.log 2>&1
0 8 3 * *   /root/orca/projects/onice/ops/ciclo_mensile.sh >> /var/log/trasi/ciclo_mensile.log 2>&1

$ docker exec trasi-automazioni-1 crontab -l -u automazioni | grep -cE '^[0-9*]'
5
```

### 2.4 · Prova che `cron` esegue davvero (eseguita)

Un crontab installato non prova che i job partano. La prova: installato temporaneamente un job con
`* * * * *` puntato a `ops/backup.sh --dry-run`, atteso il minuto, e **letto il log**:

```
$ cat /var/log/trasi/backup.log
Trasi · backup — 2026-09-16 01:56:01 CEST
  destinazione : /backups
  database     : trasi_db (ruolo postgres)
  rotazione    : 7 backup completi
  (dry-run) scriverebbe:
    /backups/trasi_2026-09-16_015601.dominio.dump          # pg_dump -Fc trasi_db
    …
```

Il job è partito, ha trovato l'ambiente giusto (`deployment/.env`, i container), e ha scritto nella
directory dei log. **Il crontab reale è stato poi ripristinato** e il log di prova rimosso.

### 2.5 · Esecuzione manuale (per diagnosi)

```bash
ops/backup.sh                  # backup completo
ops/backup.sh --dry-run        # cosa farebbe
ops/backup.sh --senza-onyx     # salta il dump delle chat (prova veloce)
ops/retention_chat.sh          # soglia da trasi.parametro
ops/retention_chat.sh --dry-run
ops/retention_chat.sh --giorni 1 --dry-run    # prova reale: c'è qualcosa oltre 1 giorno
ops/ciclo_mensile.sh --forza   # esegue il ciclo anche se non è il giorno 3
ops/install_cron.sh --dry-run  # valida il crontab senza installarlo
```

Ogni script è rieseguibile: il backup produce un file nuovo con timestamp (e non sovrascrive una
collisione: aggiunge `-1`, `-2`…), la retention è idempotente (le sessioni già cancellate non sono
più selezionate), il ciclo mensile è idempotente **per scelta dichiarata** nel suo codice
(`gia_eseguito: true`, 0 invii; `--forza` per rimandare).

---

## 3 · Backup

```bash
$ ops/backup.sh
── 1/5  dominio → /backups/trasi_2026-09-16_015647.dominio.dump
   → 233K · sha256 7b8cf6f20caf7532…
── 2/5  ruoli → /backups/trasi_2026-09-16_015647.globals.sql.gz
   → 1.0K · 21 CREATE ROLE (cluster: 21 ruoli non-pg)
── 3/5  chat di Onyx → /backups/trasi_2026-09-16_015647.onyx.dump
   → 946K · sha256 83aea181536c5cd6…
   → chat_session nel database: 54
── 4/5  configurazione → /backups/trasi_2026-09-16_015647.config.tar.gz
   → 336K
── 5/5  App-DB di Metabase → /backups/trasi_2026-09-16_015647.metabase.tgz
   → 6.6M
backup.sh: completato — /backups/trasi_2026-09-16_015647.manifest
── rotazione (mantengo 7)
   → 1 backup presenti, nessuno da rimuovere
```

### 3.1 · Cosa contiene, e perché ogni pezzo c'è

| File | Cosa | Perché |
|---|---|---|
| `.dominio.dump` | `pg_dump -Fc` di `trasi_db` | schema, dati, funzioni, **policy RLS e GRANT** |
| `.globals.sql.gz` | `pg_dumpall --globals-only` | **i ruoli non stanno nel dump del DB**: senza, le policy RLS non si applicano a nessuno |
| `.onyx.dump` | `pg_dump -Fc` del DB di Onyx | le chat. Rende la retention **reversibile** nella finestra di rotazione |
| `.config.tar.gz` | `deployment/`, `ops/`, `flussi/`, `db/`, `shim/`, `metabase/`, `docs/` | la configurazione si sbaglia a ricostruire; **escluso `deployment/.env`** (segreti) |
| `.metabase.tgz` | volume `trasi_metabase_data` (App-DB H2) | nessun dump lo copre: 3 dashboard + 40 alert sono ore di lavoro |
| `.manifest` | `sha256` + conteggi di verifica | un backup troncato è altrimenti indistinguibile da uno buono |

### 3.2 · I ruoli: perché `pg_dumpall --globals-only` non è opzionale

Su questo progetto i ruoli **sono** la sicurezza: 21 ruoli di cluster, i `GRANT` di `USAGE` sullo
schema `trasi` (19 voci di ACL), le proprietà degli oggetti (`trasi_owner`, `applicatore`) che
decidono quali policy RLS si applicano. Un ripristino senza i ruoli produce un database che risponde
a tutte le query e non protegge niente. La verifica del backup controlla che il file ne contenga:

```
ruoli_cluster = 21
ruoli_create_role_nel_backup = 21
```

### 3.3 · ⚠️ Due difetti reali trovati nel backup, entrambi corretti

**1. `--no-owner --no-privileges` rendeva il ripristino inutile.** Sembra «più portabile»; su questo
progetto è **distruttivo**. Misurato:

```
nspacl su trasi_db           → {trasi_owner=UC/trasi_owner, casa_sanbao=U/…, rete=U/…, …}  (19 voci)
nspacl sul DB ripristinato   → (vuoto)
has_schema_privilege('casa_sanbao','trasi','USAGE')  → f
SET ROLE casa_sanbao; UPDATE trasi.casa … WHERE slug='bozzano'
  → ERROR: permission denied for schema trasi
```

Il test RLS cross-Casa — l'invariante centrale di §11/V4 — **non era nemmeno eseguibile** su un
database «ripristinato con successo». I flag sono stati rimossi dal dump del dominio. (Restano nel
dump di Onyx, che ha un solo proprietario e nessun modello di ruoli: lì non portano informazione.)

**2. Il `manifest` eseguiva comandi.** Una riga di commento conteneva `` `pg_restore` `` fra doppi
apici: bash ha eseguito `pg_restore` come command substitution, stampando `pg_restore: command not
found` durante il backup. Sintomo rumoroso, conseguenza nulla (il commento restava sbagliato) — ma è
il tipo di errore che in un'altra posizione silenziosa cancellerebbe un file.

### 3.4 · Verifica dell'integrità

```bash
$ cd /backups && sha256sum -c trasi_2026-09-16_015647.manifest
trasi_2026-09-16_015647.dominio.dump: OK
trasi_2026-09-16_015647.globals.sql.gz: OK
trasi_2026-09-16_015647.onyx.dump: OK
trasi_2026-09-16_015647.config.tar.gz: OK
trasi_2026-09-16_015647.metabase.tgz: OK
```

### 3.5 · Rotazione

Conserva gli ultimi **7** backup completi (`TRASI_BACKUP_KEEP`, default 7), ordinati **per nome**
(che è cronologico). Provata con 9 backup sintetici:

```
$ TRASI_BACKUP_KEEP=7 ops/backup.sh --senza-onyx
── rotazione (mantengo 7)
   rimuovo trasi_2026-08-1_020000.*
   rimuovo trasi_2026-08-2_020000.*
   rimuovo trasi_2026-08-3_020000.*
   rimuovo trasi_2026-08-4_020000.*
   → rimossi 4; restano 7 backup completi
```

### 3.6 · Limite dichiarato: la copia di Metabase è «a caldo»

Il volume `trasi_metabase_data` contiene un'App-DB **H2 su file**, e viene copiato con Metabase
**in esecuzione**. Non esiste un dump per H2 (a differenza del dominio, che ha `pg_dump`), e fermare
Metabase a ogni backup costa: il riavvio è lento (Metabase impiega ~40 s a essere `healthy`) e il
servizio è in uso durante la giornata. La copia è quindi
coerente *per il file*, non necessariamente *per l'insieme*.

**Se serve un backup coerente di Metabase**, fermarlo prima:

```bash
docker compose -f deployment/docker-compose.yml stop metabase
ops/backup.sh
docker compose -f deployment/docker-compose.yml start metabase
```

È un compromesso **dichiarato**, non un difetto nascosto. La configurazione delle dashboard è
comunque ricostruibile: `metabase/dashboard.py` e `metabase/alerts.py` sono idempotenti per nome e
sono inclusi nel `.config.tar.gz`.

---

## 4 · Restore

### 4.1 · La prova di restore — eseguita, esito VERDE

```bash
$ ops/restore_test.sh /backups/trasi_2026-09-16_015647.dominio.dump
Trasi · prova di restore — 2026-09-16 01:56:xx CEST
  dump   : /backups/trasi_2026-09-16_015647.dominio.dump (233K)
  DB test: trasi_restore_test
  (il database di produzione 'trasi_db' non viene toccato)

── 1/4  creazione di trasi_restore_test da template0 (vuoto: il dump porta il proprio PostGIS)
  PASS  database di prova creato (template0: il dump crea PostGIS, quindi nessuna collisione)
── 2/4  pg_restore
  PASS  pg_restore completato senza errori (exit 0)
── 3/4  verifiche di contenuto
  PASS  count(casa) = 10  ← criterio B6-STK-01
  PASS  count(trasi.luogo) = 22 (identico alla produzione)
  PASS  count(trasi.fonte) = 21 (identico alla produzione)
  PASS  count(trasi.parametro) = 10 (identico alla produzione)
  PASS  count(trasi.casa) = 10 (identico alla produzione)
  PASS  funzioni SECURITY DEFINER = 4 (identiche alla produzione)
  PASS  policy RLS = 65 (identiche alla produzione)
  PASS  GRANT sullo schema trasi = 19 (identici alla produzione: i privilegi sono ripristinati)
  PASS  RLS ripristinata: casa_sanbao scrive la propria Casa (1) e non quella altrui (0)
── 4/4  globals (ruoli)
  PASS  il file dei globals contiene 21 ruoli (i ruoli NON stanno nel dump del DB)
  PASS  tutti i ruoli del contratto B1 sono nel file dei globals

restore_test.sh: trasi_restore_test rimosso (il cluster torna com'era)

restore_test.sh: ESITO VERDE — 13 PASS, 0 FAIL · count(casa)=10
```

### 4.2 · Il difetto più importante di questo blocco: `template_postgis` faceva fallire ogni restore

La prima esecuzione era **ROSSA con un dump perfettamente buono**. Il database di prova veniva
creato da `template_postgis`, che su questa immagine contiene **già** gli schemi `topology`, `tiger`,
`tiger_data` e le estensioni PostGIS. Il dump, coerentemente, contiene i propri `CREATE SCHEMA tiger`
e `CREATE EXTENSION postgis`:

```
pg_restore: error: could not execute query: ERROR:  schema "tiger" already exists
```

E con `--single-transaction` **l'intera transazione va in rollback**: `count(casa)` → `<null>`,
nessuna policy, nessuna funzione. Il test stava misurando sé stesso, non il backup. Da `template0`
(vuoto) il dump si applica per intero e crea ciò che gli serve — che è esattamente ciò che farebbe su
un host nuovo.

### 4.3 · Restore vero su un ambiente nuovo (procedura)

Su un host nuovo la sequenza è **ruoli prima, dati dopo**: è la stessa precondizione che
`restore_test.sh` verifica.

```bash
# 1. il cluster e i ruoli (i ruoli NON stanno nel dump del DB)
gunzip -c /backups/trasi_YYYY-MM-DD_HHMMSS.globals.sql.gz \
  | docker compose -f deployment/docker-compose.yml exec -T db_trasi psql -U postgres -d postgres

# 2. il database, da template0 (NON da template_postgis: v. §4.2)
docker compose -f deployment/docker-compose.yml exec -T db_trasi \
  psql -U postgres -c "CREATE DATABASE trasi_db TEMPLATE template0"

# 3. il dominio — SENZA --no-owner/--no-privileges (v. §3.3)
docker compose -f deployment/docker-compose.yml exec -T db_trasi \
  pg_restore -U postgres -d trasi_db --single-transaction \
  < /backups/trasi_YYYY-MM-DD_HHMMSS.dominio.dump

# 4. l'App-DB di Metabase
docker run --rm -v trasi_metabase_data:/dst -v /backups:/src:ro alpine:3 \
  tar --extract --gzip --file /src/trasi_YYYY-MM-DD_HHMMSS.metabase.tgz -C /dst

# 5. la verifica — la stessa della prova
ops/restore_test.sh /backups/trasi_YYYY-MM-DD_HHMMSS.dominio.dump
```

> ⚠️ **I `globals` contengono gli hash SCRAM delle password dei ruoli.** Il file è mode 600 e va
> trattato come materiale sensibile: chi lo legge può tentare un attacco offline sulle password.
> Su un ripristino verso un cluster **diverso**, applicare i globals significa riportare anche le
> password del cluster di origine — se non è voluto, si applicano i soli `CREATE ROLE`/`GRANT`
> (escludendo le righe `PASSWORD`) e si riprovisionano le password con `flussi/provisiona.sh`.

---

## 5 · Retention delle chat

### 5.1 · Dove Onyx conserva le chat (verificato, non dedotto)

| Cosa | Dove |
|---|---|
| Sessioni | PostgreSQL di Onyx (`onyx-relational_db-1`), tabella `chat_session` — **54 righe** |
| Messaggi | tabella `chat_message` — **210 righe**, FK `chat_session_id → chat_session.id ON DELETE CASCADE` |
| File allegati | **fuori dal database**: bucket MinIO `onyx-file-store-bucket` (`onyx-minio-1`), referenziati da `chat_message.files` (12 messaggi) e registrati in `file_record` (245 righe) |

I file stanno **fuori** dal DB: è il motivo per cui lo script usa la funzione di cancellazione di
Onyx invece di un `DELETE`. Un `DELETE` a mano cancellerebbe i metadati e lascerebbe i file su MinIO.

### 5.2 · ⚠️ IL GAP: Onyx ha una retention nativa, ed è chiusa dal piano Enterprise

**Sì, Onyx ha una retention nativa.** `maximum_chat_retention_days` nelle settings, consumata dal
task Celery `check_ttl_management_task` → `perform_ttl_management_task`
(`backend/ee/onyx/background/celery/tasks/ttl_management/tasks.py`), schedulato dal beat ogni ora.
**Il beat lo esegue davvero:**

```
$ docker logs onyx-background-1 | grep check-ttl-management | tail -1
beat.py:279 : celery.beat Scheduler: Sending due task check-ttl-management-public
```

**Ma è chiuso dal tier.** `backend/onyx/server/settings/api.py:119-124`:

```python
if (merged.maximum_chat_retention_days != existing.maximum_chat_retention_days
        and not tier_at_least(current_tier, Tier.ENTERPRISE)):
    raise OnyxError(OnyxErrorCode.FEATURE_NOT_AVAILABLE,
                    "Chat history retention requires the Enterprise plan.")
```

Questa installazione è **Community**: `ENABLE_PAID_ENTERPRISE_EDITION_FEATURES=false`, tabella
`license` → **0 righe**, `get_tier()` → `Tier.COMMUNITY`. Misurato:

```
$ curl -X PATCH http://127.0.0.1:80/api/admin/settings \
    -H "Authorization: Bearer $ONYX_TRASI_KB_API_KEY" -d '{"maximum_chat_retention_days": 30}'
{"error_code":"FEATURE_NOT_AVAILABLE","detail":"Chat history retention requires the Enterprise plan."}
HTTP 402
```

E quindi il task nativo **non fa nulla**: `should_perform_chat_ttl_check(None, …)` esce subito
(`ee/onyx/background/celery_utils.py:16`: `if not retention_limit_days: return False`). La catena è:
il beat invia il task ogni ora → il task legge una soglia che è `None` → nessuna cancellazione.
**Container sano, beat vivo, retention ferma.** Verificato che non esiste una variabile d'ambiente
alternativa (`grep -rn "RETENTION" deployment/` nei template di Onyx → nessun risultato).

**Le due strade, dichiarate senza inventare niente:**

- **(a) licenza Enterprise per Onyx** → la retention nativa si attiva e il task EE fa il lavoro.
- **(b) lo script di questo blocco** → `ops/retention_chat.sh`, che è il fallback previsto dal piano.

**Non si aggira il gate** scrivendo il valore direttamente in `key_value_store`. Il codice EE è
presente in questa immagine (`is_ee_version()` → `True`) e il task gira già, quindi un `UPDATE`
funzionerebbe — ma sarebbe (1) l'aggiramento di un controllo di **licenza**; (2) un deployment la cui
interfaccia **rifiuta con 402** la configurazione che il database contiene; (3) una cancellazione di
dati governata da un interruttore che nessuna schermata amministra. Se il TI vuole la via nativa, la
via è la licenza.

### 5.3 · Lo script: usa il codice di Onyx, non una `DELETE` propria

```bash
$ ops/retention_chat.sh --dry-run
Trasi · retention chat — 2026-09-16 01:53:13 CEST
  soglia: 30 giorni (da trasi.parametro.gg_retention_chat)
retention_chat: soglia 30.0 giorni · retention nativa di Onyx: non impostata (Community — v. testa del file)
retention_chat: chat_session=54 · chat_message=210 · sessioni oltre la soglia: 0
retention_chat: niente da cancellare (idempotente: nessuna sessione oltre la soglia)
retention_chat.sh: exit 0
```

La soglia arriva da **`trasi.parametro.gg_retention_chat`** (30, §7.2), non da una costante: il TI la
cambia con un `UPDATE`, senza un deploy.

La cancellazione usa le **stesse funzioni del task nativo**:
`get_chat_sessions_older_than()` (identica definizione di «vecchia»: ultima attività, non creazione)
e `delete_chat_session(…, hard_delete=True)` (rimuove anche i file su MinIO e le CASCADE).

### 5.4 · Prova reale di cancellazione (eseguita)

Inserita una sessione sintetica con timestamp di 400 giorni (l'unico esemplare oltre 365), con
soglia **365** per non toccare le 54 sessioni reali (tutte di oggi/ieri):

```bash
# dry-run: elenca esattamente quella
$ ops/retention_chat.sh --giorni 365 --dry-run
retention_chat: chat_session=55 · chat_message=210 · sessioni oltre la soglia: 1
retention_chat: (dry-run) NON cancello. Prime 1 sessioni:
    a6cd99b4-…  ultima attività: 2025-08-11 23:53:25+00:00

# esecuzione reale
$ ops/retention_chat.sh --giorni 365
retention_chat: soglia 365.0 giorni · retention nativa di Onyx: non impostata (Community — v. testa del file)
retention_chat: chat_session=55 · chat_message=210 · sessioni oltre la soglia: 1
retention_chat: cancellate 1 sessioni (0 errori) · chat_session 55→54 · chat_message 210→210
retention_chat.sh: exit 0

# verifica
$ docker exec onyx-relational_db-1 psql -U postgres -d postgres -tAc \
    "SELECT count(*) FROM chat_session WHERE description='TRASI-RETENTION-PROVA'"
0

# idempotenza: secondo run identico
$ ops/retention_chat.sh --giorni 365
retention_chat: chat_session=54 · chat_message=210 · sessioni oltre la soglia: 0
retention_chat: niente da cancellare (idempotente: nessuna sessione oltre la soglia)
retention_chat.sh: exit 0
```

**Cosa dimostra:** la cancellazione funziona (55→54), tocca **solo** ciò che è oltre la soglia (le 54
reali intatte), è idempotente, e la sessione sintetica è stata rimossa.

### 5.5 · Finestra di reversibilità (⚠️ dichiarata)

La retention gira alle **03:00**, il backup alle **02:00**: una cancellazione sbagliata è
recuperabile dal backup della notte precedente. **Ma la finestra è di una notte**, perché la
rotazione conserva 7 backup: una cancellazione non notata per 8 giorni non è più recuperabile dal
backup. È il motivo per cui i due orari hanno quest'ordine, ed è un dettaglio che si nota solo
quando serve.

---

## 6 · Rollback

### 6.1 · Livello A — un servizio smette di funzionare, il codice è quello

Riavviare il servizio. Se è la configurazione, tornare al file precedente:

```bash
# Caddyfile e compose sono nel `.config.tar.gz` dell'ultimo backup, e in git
git -C /root/orca/projects/onice log --oneline -5 -- deployment/caddy/Caddyfile
git -C /root/orca/projects/onice checkout <commit> -- deployment/caddy/Caddyfile
docker compose -f deployment/docker-compose.yml restart caddy
# verifica (non basta che sia "up")
curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: trasi.lascuolaopensource.org' http://127.0.0.1:8088/
```

### 6.2 · Livello B — il database è in uno stato sbagliato

```bash
# 1. fermare chi scrive (i flussi sono i soli scrittori automatici)
docker compose -f deployment/docker-compose.yml stop automazioni

# 2. verificare PRIMA che il backup sia buono, su un DB di prova
ops/restore_test.sh /backups/trasi_YYYY-MM-DD_HHMMSS.dominio.dump

# 3. solo se la prova è VERDE, ripristinare il dominio (procedura §4.3)

# 4. riavviare i flussi e verificare la catena
docker compose -f deployment/docker-compose.yml start automazioni
curl -s -H 'Host: trasi.lascuolaopensource.org' \
  'http://127.0.0.1:8088/api/shim/v1/u/rete@trasi.local/oggi?casa=bozzano'
```

**Regola:** non si ripristina mai in produzione un backup che non ha passato `restore_test.sh`. È il
motivo per cui quello script esiste.

### 6.3 · Livello C — l'immagine o il compose sono cambiati e non funzionano

```bash
docker compose -f deployment/docker-compose.yml down
git -C /root/orca/projects/onice checkout <commit> -- deployment/
docker compose -f deployment/docker-compose.yml up -d db_trasi searxng shim automazioni metabase caddy
docker compose -f deployment/docker-compose.yml ps
```

### 6.4 · Cosa **non** si fa mai

- `docker compose down -v`: cancella i named volume, quindi i dati. Va usato solo su un ambiente di
  prova, mai qui.
- `DELETE` a mano su `chat_session` per "fare spazio": lascia i file su MinIO e non è idempotente.
  Usare `ops/retention_chat.sh`.
- Modificare i test di `db/tests/` per farli passare.
- Alzare il `mem_limit` di Metabase (o di un altro servizio) senza la decisione del TI: l'host è
  condiviso con Onyx e l'over-commit è già stato escluso in B0 con i numeri.

---

## 7 · Rotazione dei segreti

| Segreto | Dove vive | Come si ruota | Effetto |
|---|---|---|---|
| Password Postgres Trasi (`postgres`) | `deployment/.env`, volume `db_trasi_data` | `ALTER USER postgres PASSWORD '<nuova>'`, aggiornare `.env`, `restart db_trasi` | tutti i consumatori rileggono da `.env` |
| Password `shim_rw` | `deployment/.env` (mode 600) + ruolo nel DB | `flussi/provisiona.sh` la rilegge e riprovisiona | nessun file di codice cambia |
| Password `automazioni` | `deployment/.env` → `/run/trasi/env` nel container | `flussi/provisiona.sh`, poi `restart automazioni` | l'entrypoint riscrive `/run/trasi/env` |
| `TRASI_SHIM_KEY` | `deployment/.env` → `shim` **e** `caddy` | aggiornare `.env`, `restart shim caddy` | la Home continua a funzionare: la chiave la inietta Caddy (§1.1) |
| PAT Onyx (`ONYX_TRASI_KB_API_KEY`) | `deployment/.env` | rigenerare dalla console di Onyx (Admin → API Keys), aggiornare `.env`, `restart automazioni` | l'export KB riprende al prossimo giro |
| Segreti Metabase / NocoDB / Activepieces | `deployment/.env` + `.secrets/` (mode 600, gitignored) | rigenerare, aggiornare `.env`, `restart <servizio>` | le dashboard restano configurate (sono nell'App-DB) |
| Ollama Cloud API key | ambiente di Onyx (compose di Onyx) | rigenerare nella console, aggiornare l'env di Onyx, `restart` dei container Onyx | **è di Onyx, non di questo stack** |

**Verifica dopo ogni rotazione** (nessun segreto in output):

```bash
# che i container abbiano il valore nuovo senza stamparlo
docker compose -f deployment/docker-compose.yml exec -T shim python3 -c \
  "import os; print('TRASI_SHIM_KEY presente:', bool(os.environ.get('TRASI_SHIM_KEY')))"

# che non ci siano segreti nei log
docker compose -f deployment/docker-compose.yml logs --no-log-prefix 2>&1 \
  | grep -ciE 'password|secret|api[_-]?key'
```

**Limite dichiarato:** i segreti passano ai container come **variabili d'ambiente**, quindi sono
leggibili con `docker inspect` da chi ha accesso al demone (equivalente a root sull'host). È il
compromesso standard di Compose; l'hardening è in S2 (`deploy.secrets`/`*_FILE`, senza cambiare
l'invocazione).

---

## 8 · Diagnosi rapida

| Sintomo | Dove guardare |
|---|---|
| «la chat non cita il dato nuovo» | `SELECT nome, esito, dettaglio FROM trasi.flusso_run ORDER BY id DESC LIMIT 10` — l'export KB è passato? |
| «è passata la notte?» | `flussi/notte.sh` (esegue la catena a mano) · `flusso_run` |
| «la Home dice *dati non disponibili*» | `curl http://127.0.0.1:8001/healthz` · `docker compose ps shim` · §1.5 |
| «la Home non si apre» | `curl -H 'Host: trasi.…' http://127.0.0.1:8088/` — se è 200, il problema è il **tunnel**, non Caddy (§1.2) |
| «il backup non è partito» | `cat /var/log/trasi/backup.log` · `crontab -l` · `ops/backup.sh --dry-run` |
| «la retention non cancella» | `ops/retention_chat.sh --dry-run` · la soglia in `trasi.parametro` · §5.2 |
| «un flusso non parte dal container» | `docker logs trasi-automazioni-1` · `docker exec trasi-automazioni-1 crontab -l` |
| «Metabase è lento o riavvia» | `docker stats --no-stream trasi-metabase-1` · §1.3 |
| **«sto misurando il codice giusto?»** | `ops/provenienza_stack.sh` — dice **quale worktree** ha costruito l'istanza viva (§11) |
| «un utente non riesce a entrare in Onyx» | `ops/provisiona_utenti_onyx.sh --dry-run` — dice chi manca, senza creare (§11) |
| «ho aggiunto un evento in chat ma non c'è» — l'assistente ha detto «non ho un calendario» o «memorizzato nelle note» | la chat era con l'assistente **predefinito** di Onyx (persona 0), non con Trasi Casa: `SELECT persona_id FROM chat_session ORDER BY time_created DESC LIMIT 5` sul DB di Onyx · `docker logs trasi-shim-1 \| grep crea_evento` (nessuna riga = nessuna scrittura) · `ops/allinea_assistente_predefinito.py` dà a persona 0 lo strumento `trasi_shim` e le istruzioni |

---

## 9 · Cosa non è coperto da questo runbook (dichiarato)

- **Il tunnel Cloudflare.** Non ha un ingress per `trasi.lascuolaopensource.org`: verificato leggendo
  l'API locale di `cloudflared` (`curl http://127.0.0.1:20241/config` → ingress per
  `orca.…`, `onyx.…`, e un `404` di default). Caddy serve correttamente su `:8088` (verificato con
  l'header `Host`), ma la pubblicazione su internet richiede una regola di ingress
  (`trasi.… → http://localhost:8088`) aggiunta dal TI: su questo host non ci sono le credenziali per
  farlo (`/etc/cloudflared/` contiene solo `credentials.json` di un tunnel token-based: nessun
  `cert.pem`, nessun `CLOUDFLARE_API_TOKEN`).
- **SMTP.** Non configurato: gli alert di Metabase e i messaggi di `flussi/` vanno su file finché non
  c'è un server. La prova di recapito di B5 è stata fatta con un sink usa-e-getta, poi rimosso.
- **NocoDB.** Non avviato (RAM). La destinazione REGISTRA della Home ha il link predisposto; si
  attiva quando NocoDB entra in funzione.
- **Hardening** (`deploy.secrets`, rate limit Caddy, MFA): S2.
- **Monitoraggio** (Prometheus/Grafana): S2. Oggi la diagnostica è `docker stats`, `flusso_run` e i
  log in `/var/log/trasi/`.

---

## 10 · Trasi Home (il sito statico)

La Home è la porta unica della rete (`deployment/home/`, tre file: `index.html`, `style.css`,
`home.js`). Non ha un processo proprio: la serve Caddy come sito statico. Per la verifica
dell'endpoint e per i due difetti di avvio di Caddy **v. §1.1** e **§1.2**; qui c'è il contratto
della pagina e le prove che la riguardano.

### 10.1 · Come è servita

| Rotta | Cosa serve | Prova |
|---|---|---|
| `/` | `index.html` da `/srv/home` (`deployment/home/` montata in sola lettura) | `curl -H 'Host: trasi…' http://127.0.0.1:8088/` → 200 |
| `/style.css`, `/home.js` | gli altri due file | 200, `text/css` / `application/javascript` |
| `/api/shim/*` | la riga «Oggi»: proxy verso `shim:8000`, con la chiave iniettata **da Caddy** | vedi §10.3 |
| `/metabase/*` | le dashboard (MAPPA, OSSERVATORIO) | 200 |
| `/nocodb/*` | la destinazione REGISTRA | **502** con servizio spento (§10.5) |

```bash
$ curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: trasi.lascuolaopensource.org' http://127.0.0.1:8088/
200
```

### 10.2 · La chiave dello shim non sta nella pagina

Il problema: la Home è **statica e pubblica**, quindi una `X-Trasi-Key` scritta nel JS sarebbe
leggibile da chiunque — una chiave pubblica non è una chiave. La soluzione: la chiave la aggiunge
Caddy nel proxy (`header_up X-Trasi-Key {env.TRASI_SHIM_KEY}`), e il browser non la vede mai.

La pagina chiama `/api/shim/v1/u/rete@trasi.local/oggi?casa=<slug>`, che Caddy inoltra a
`http://shim:8000/v1/u/rete@trasi.local/oggi?casa=<slug>`.

Verifica che il client **non possa** interferire né leggere il segreto:

```bash
# con una chiave falsa mandata dal client → 200: Caddy la sostituisce, non la aggiunge
$ curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: trasi.lascuolaopensource.org' \
    -H 'X-Trasi-Key: chiave-falsa' \
    'http://127.0.0.1:8088/api/shim/v1/u/rete@trasi.local/oggi?casa=bozzano'
200

# direttamente sullo shim, senza chiave → 401: la protezione esiste, e sta a monte
$ curl -s -o /dev/null -w '%{http_code}\n' 'http://127.0.0.1:8001/v1/u/rete@trasi.local/oggi?casa=bozzano'
401
```

**Perché l'identità è `rete@trasi.local` e non quella dell'operatore.** La Home non ha un login
proprio e il selettore Casa può indicare una Casa diversa da quella dell'operatore. Un ruolo `casa_*`
può leggere solo la propria Casa e risponderebbe `404` sulle altre; `rete` non ha una Casa
(`casa_corrente()` è `NULL`) ed è quindi l'unico ruolo che può leggere lo slug indicato. Il filtro
resta comunque nel database (la query di `oggi` confronta `casa_id` con `trasi.casa_corrente()`): non
è un controllo che vive nel JS.

### 10.3 · Il contratto della riga «Oggi»

La riga non ricompone la frase: mostra il campo `testo` **così come lo restituisce la vista del
database** (`v_oggi_casa`). Ricomporla qui significherebbe due formattazioni da tenere allineate, e la
Home potrebbe dire numeri diversi dalla chat.

```bash
$ curl -s -H 'Host: trasi.lascuolaopensource.org' \
    'http://127.0.0.1:8088/api/shim/v1/u/rete@trasi.local/oggi?casa=bozzano'
{"casa":"bozzano","eventi":0,"schede_in_scadenza":0,"proposte":0,
 "testo":"Oggi a Centro di Aggregazione Bozzano: 0 eventi · 0 schede in scadenza · 0 proposte"}
```

**Timeout di 3 secondi, mai un errore grezzo.** Il `fetch` è governato da un `AbortController` con
scadenza a 3000 ms; qualunque esito diverso da una risposta valida (timeout, shim fermo, rete assente,
risposta non JSON, campo `testo` vuoto) produce la **stessa** frase per l'operatore:

> Dati non disponibili: la memoria della rete non risponde in questo momento.

Il timeout sta nel JS e non in Caddy: Caddy non ha un timeout corto sul proxy, quindi senza
`AbortController` la richiesta resterebbe appesa finché non risponde il proxy.

**Prova del fallback, eseguita con lo shim fermo** (`docker stop trasi-shim-1`):

| Passo | Comando | Esito |
|---|---|---|
| shim fermo | `docker stop trasi-shim-1` | `trasi-shim-1` exited |
| riga via Caddy | `curl -H 'Host: trasi…' 'http://127.0.0.1:8088/api/shim/…/oggi?casa=bozzano'` | **502** (Caddy risponde, lo shim no) |
| riga nella pagina | apertura della Home nel browser | «Dati non disponibili: …» |
| shim riavviato | `docker start trasi-shim-1` | `Up (healthy)` |
| riga nella pagina | ricarica | il testo di `oggi` torna a comparire |

La stessa prova è stata ripetuta con un banco di prova usa-e-getta che **non risponde mai** al posto
dello shim: la riga cambia a 3,1 secondi dalla richiesta (misurato con `performance.now()`), cioè
entro la scadenza prevista. È il caso che discrimina: con lo shim fermo la connessione viene rifiutata
subito e il fallback comparirebbe anche senza timeout, mentre un servizio che non risponde è ciò che
il `AbortController` esiste per gestire.

### 10.4 · Il contratto degli `href` (e la Casa scelta)

Le destinazioni e la coda delle proposte portano lo slug della Casa in `?casa=<slug>`. Gli
indirizzi sono scritti una volta sola, in `data-modello`, con `{casa}` al posto dello slug; cambiarli
significa cambiare quel solo attributo (e l'attributo `href` statico, che è la destinazione
predefinita senza JS).

| Destinazione | Modello dell'`href` | Destinazione reale |
|---|---|---|
| CHIEDI | `//onyx.lascuolaopensource.org/app?agentId=2&casa={casa}` | Onyx, assistente «Trasi Casa» preselezionato (`agentId` 1=Presidio, 2=Casa, 3=Rete, 4=Staff PN) |
| MAPPA | `/metabase/dashboard/4?casa={casa}` | dashboard «Trasi · Mappa» |
| REGISTRA / AGGIORNA | `/nocodb/?casa={casa}` | NocoDB (spento: §10.5) |
| OSSERVATORIO | `/metabase/dashboard/3?casa={casa}` | dashboard «Trasi · Casa» |
| Coda delle proposte | `/nocodb/?casa={casa}&view=da-approvare` | NocoDB, vista «Da approvare» |

La Casa scelta sta in `localStorage` sotto **una sola** chiave, `trasi.casa_id`, con il **solo slug**
(nessun dato personale: V5). Un valore che non corrisponde a una voce del selettore viene ignorato:
un residuo di una versione precedente non può costruire un indirizzo arbitrario. Se lo storage è
disabilitato (navigazione privata) la pagina funziona lo stesso e semplicemente non ricorda la scelta.

```bash
# La persistenza si prova nel browser: scelgo Bozzano, ricarico, e i 4 href lo contengono
$ # (estratto dalla verifica B6: localStorage dopo il cambio)
[["trasi.casa_id","bozzano"]]
$ # href dopo il ricarico, con la Casa Bozzano:
//onyx.lascuolaopensource.org/app?agentId=2&casa=bozzano
/metabase/dashboard/4?casa=bozzano
/nocodb/?casa=bozzano
/metabase/dashboard/3?casa=bozzano
/nocodb/?casa=bozzano&view=da-approvare
```

### 10.5 · Le quattro destinazioni: esito reale, una per una

| # | Destinazione | Esito misurato | Nota |
|---|---|---|---|
| 1 | CHIEDI → Onyx | **200**, assistente «Trasi Casa» preselezionato | richiede la sessione Onyx (la chat chiede il login: la Home non ha un SSO, §10.6) |
| 2 | MAPPA → Metabase `dashboard/4?casa=bozzano` | **200**, filtro «Casa: bozzano» applicato | richiede la sessione Metabase |
| 3 | REGISTRA → NocoDB | **502** | servizio **spento per RAM** (dichiarato inattivo). Il `502` è corretto: la rotta esiste, il servizio dietro no. Un `404` sarebbe un link sbagliato |
| 4 | OSSERVATORIO → Metabase `dashboard/3?casa=bozzano` | **200**, filtro «Casa: bozzano» applicato | idem 2 |

**Nessuna delle quattro destinazioni dà un `404`.** Tre rispondono; la quarta è dichiarata inattiva.

### 10.6 · Cosa la Home **non** fa (limiti dichiarati)

- **Non autentica.** È una pagina pubblica che apre i servizi; i servizi si autenticano da sé. Se
  l'operatore non ha una sessione attiva, CHIEDI/MAPPA/OSSERVATORIO mostrano la schermata di accesso
  del servizio, non un errore. Un SSO unico non è nel perimetro del MVP (§3: shell applicativa in
  S2+).
- **Il pulsante [Esci]** chiude la sessione **della chat** (fa un POST a
  `onyx.lascuolaopensource.org/auth/logout`, in un `<form>`: nessun `fetch`, così funziona anche se
  in futuro il logout richiedesse un token) e **non** chiude la sessione di Metabase, che è un
  prodotto separato. Verificato nel browser: dopo il clic il cookie di sessione di Onyx sparisce e
  `/api/me` passa da `200` a `403`, mentre la pagina resta la Home e mostra «Sessione della chat
  chiusa.». Un logout unico per i tre servizi richiederebbe un SSO: S2.
- **Non è un cruscotto.** Non mostra numeri propri e non dà istruzioni (V6): la riga «Oggi» è una
  lettura della memoria della rete, le destinazioni sono porte.
- **La coda delle proposte è una riga, non un riquadro.** Il conteggio sta in testa (quante ne
  aspettano una decisione, e da quanto aspetta la più vecchia) e anche sul riquadro OSSERVATORIO,
  perché è là che si decide. Se la lettura fallisce, la riga **sparisce**: non sapendo quante
  proposte ci sono, dire «nessuna in attesa» sarebbe falso.
- **REGISTRA / AGGIORNA e la coda sono dichiarati inattivi.** NocoDB è in esecuzione ma non ha
  ancora le basi collegate (`nc_bases_v2` e `nc_users_v2` sono vuote, verificato): il collegamento è
  predisposto e la nota dice che per ora si approva dalla chat. Senza la nota l'operatore atterrerebbe
  su una registrazione e leggerebbe un guasto dove c'è un servizio non ancora configurato.
- **Non conserva dati personali** (V5): in `localStorage` c'è solo lo slug della Casa.

### 10.7 · Verifica di accessibilità

Vedi **`deployment/home/WCAG.md`** (rifatta dopo la revisione della veste): axe-core → **0
violazioni** WCAG 2.1 A/AA **in tutti e quattro gli stati** della pagina, 12 coppie di contrasto
misurate (minimo **6,71:1**), ordine di tabulazione verificato con `Tab` reale (salta → Casa → Aiuto →
Esci → coda → CHIEDI → MAPPA → OSSERVATORIO), reflow a 320 px senza scorrimento, bersagli ≥ 24×24.
La verifica WCAG delle tre applicazioni esterne è **rinviata a S2** (§9 e App. A V-08): non è fatta.

---

## 11 · Provenienza dello stack e utenti di Onyx (due difetti trovati il 2026-09-17)

Due script nati da altrettanti difetti misurati, non da un'esigenza teorica. Entrambi sono
**idempotenti** e hanno una modalità `--dry-run`: si possono eseguire per sapere, senza cambiare.

### 11.1 · `ops/provenienza_stack.sh` — quale codice sta girando

Il progetto compose è `name: trasi`: **uno solo, condiviso da tutti i worktree** (15 al 2026-09-17).
Chiunque ricostruisca un'immagine impone il proprio branch a tutte le sessioni che poi interrogano lo
stack.

**Misurato**: lo shim in esecuzione era stato costruito da
`/root/orca/workspaces/onice/installazione-connettori-mancanti/deployment` e serviva **12 operazioni**
(`+ /cerca_opendata`, `/leggi_dataset`) invece delle **10** di `main`, con un modulo
`shim/app/opendata.py` che in `HEAD` non esiste.

**Perché conta** — non è un dettaglio tecnico, è epistemico: chi verifica lo stack senza saperlo
**misura il codice di qualcun altro** e attribuisce i difetti alla codebase sbagliata.

```bash
$ ops/provenienza_stack.sh
provenienza_stack: quale codice sta girando

  checkout locale     : /root/orca/projects/onice
  branch              : main @ 464ed5b
  container           : trasi-shim-1
  costruito da        : /root/orca/workspaces/onice/installazione-connettori-mancanti/deployment
  operazioni contratto: 12 (istanza viva) vs 10 (checkout)
  moduli non tracciati: 1
      opendata.py

  VERDETTO: l'istanza viva NON è questo checkout.
```

Exit code: **0** se l'istanza è questo checkout, **1** se è di un altro. Con `--riga` produce una riga
sola, da incollare in un report.

**I tre indizi sono indipendenti** e il verdetto è sul congiunto, perché uno solo può ingannare:
il `working_dir` dell'etichetta Compose, i moduli presenti nell'immagine ma assenti da `git ls-files`,
il numero di operazioni del contratto. L'hash dei file **non** si usa: un'immagine ricostruita dallo
stesso codice ha hash diversi, e un hash diverso non dice *di chi* è il codice — che è la domanda.

**Cosa non fare** quando il verdetto è rosso: `docker compose build`/`up`/`restart` per «allineare».
Sovrascriverebbe lavoro non committato di un'altra sessione. Nei report si **dichiara** l'origine
dell'istanza misurata; per verificare il proprio codice si usa un worktree isolato o i test
in-process.

### 11.2 · `ops/provisiona_utenti_onyx.sh` — chi può entrare in chat

`db/010_seed_case.sql` dichiara **22 identità** (op e gestore per 10 Case, più `rete` e `ti`). In Onyx
ne esistevano **6**, create a mano in B3. Le altre **16** — 8 Case con i loro operatori — esistevano
nel database ma **non avevano un accesso**: nessuno di loro poteva entrare in chat. La documentazione
riferiva verifiche su «10 Case»: 10 nel database, 2 usabili.

```bash
$ ops/provisiona_utenti_onyx.sh --dry-run
provisiona_utenti_onyx: confronto identita_onyx (Trasi) con user (Onyx)
  attese da identita_onyx : 22
  già presenti in Onyx    : 6
  da creare               : 16
  gestore.buscicchio@trasi.local
  …
provisiona_utenti_onyx: (dry-run) NON creo nulla
```

**Tre vincoli hanno deciso l'implementazione**, e valgono per chi lo modificherà:

1. **Non si scrive `INSERT` a mano.** Onyx 4.7.2 verifica con **argon2id**; l'hash lo calcola
   `PasswordHelper` **di Onyx**, dentro il container con la stessa versione del codice. La password
   entra nello **stdin**, mai in `argv`.
2. **Non si usa `POST /api/auth/register`.** Quell'endpoint valida l'email con `email_validator`, che
   rifiuta i domini riservati: `@trasi.local` è *special-use* → **422**. È anche il motivo per cui le 6
   utenze esistenti sono state create fuori dall'API. (Che quell'endpoint sia **aperto e raggiungibile
   da internet** è un problema separato e più grave, tracciato in `docs/verifiche-caccia-2026-09-17.md`:
   questo script non lo usa, ma non è lui a chiuderlo.)
3. **`effective_permissions` non si dimentica.** È una colonna **denormalizzata**: il ruolo
   (`UserRole`) è un tombstone mai letto, e con `[]` ogni scrittura risponde **403** con un messaggio
   che non spiega perché. È la trappola già pagata in B3 (`docs/verifiche.md`, lezione 2), e la ragione
   per cui lo script la popola con `["basic"]`.

**Idempotente**: chi esiste non viene toccato (né password né permessi). Rieseguirlo dopo aver
aggiunto una Casa al seed crea **solo** i nuovi.

**La password** è una sola per tutti gli account di servizio della rete (sono account di sportello,
condivisi da chi lavora in quella Casa): una per utente moltiplicherebbe i posti in cui custodire un
segreto senza aumentare la sicurezza. Se non è passata con `--password` viene generata e **stampata
una volta sola**. Il README dichiara che sta in `deployment/.env` — dal 2026-09-17 è vero
(`TRASI_UTENTI_PASSWORD`, mode 600, gitignored): prima quella riga del README era **falsa**.

**Verificato** dopo l'esecuzione: login reale di `op.molo12@trasi.local` → **204** con cookie di
sessione; 22/22 utenti con `effective_permissions = ["basic"]`; `oggi` via shim → `{"casa":"molo12",…}`.

---

## 12 · Notifica report PA (US-4)

Il passaggio del report mensile alla PA **non è un invio diretto**: è una catena in tre stati, in cui
ogni transizione richiede un atto esplicito e resta tracciata.

1. **Giorno 3, 08:00 — il ciclo mensile (F5) persiste le bozze.** Per ogni Casa una riga
   `trasi.report` (`ambito='casa'`, `stato='bozza'`) e **una** riga `ambito='osservatorio'` con il CSV
   in colonna. Se il report del mese esiste già **non viene riscritto** (divieto di UPDATE per
   costruzione, db/024/026): il run lo dichiara in `flusso_run.dettaglio.report.gia_esistenti`.
   `--forza` rimanda i digest ma **non** duplica i report.
2. **L'operatore referente (ruolo rete/AT) approva dalla dashboard PA.** È un atto umano, non del
   flusso: `trasi.approva_report(id)` è SECURITY DEFINER con audit a transizione; da quel momento il
   report compare in `trasi.v_report_da_notificare` (approvato, `inviato_pa_ts IS NULL`).
3. **Giorno successivo, 07:30 — l'alert (F6) notifica.** `flussi/alert.py` legge la vista; per ogni
   report invia «Trasi · report osservatorio `<mese>` approvato — disponibile in dashboard PA» al
   recapito del parametro `[P] email_report_pa` e marca `trasi.marca_report_inviato(id)`. Se il
   parametro è **vuoto** il messaggio va su file (`flussi/evidenze/alert/`) e il modo è dichiarato in
   `flusso_run.dettaglio.report_pa` — la stessa filosofia degli invii senza SMTP: il recapito mancante
   non blocca la marcatura, e non deve far rinotificare il report ogni mattina.

**Perché la marcatura e non la deduplicazione di contenuto.** Gli altri avvisi si deduplicano per
impronta del contenuto (§2/bug 2026-09-16); la notifica PA no: la vista filtra già
`inviato_pa_ts IS NULL`, quindi il marcatore di stato *è* l'idempotenza. Un report notificato ma non
marcato ripartirebbe ogni mattina — per questo un'invo fallito **non** marca (il report torna in
vista al prossimo run) e una marcatura impossibile (funzione SQL assente) ferma il run in errore,
non tace.

**V6 anche qui.** Il messaggio dice *chi decide* (l'approvazione è dell'operatore referente, la
pubblicazione resta alla PA) e attraversa lo stesso presidio lessicale degli altri avvisi: un
template con un imperativo blocca l'intero job delle 07:30, compreso il passo PA.

**Diagnosi rapida:**

```bash
# Cosa aspetta di essere notificato (vista del contract):
docker compose -f deployment/docker-compose.yml exec -T db_trasi \
  psql -U automazioni -d trasi_db -c "SELECT id, mese, approvato_ts FROM trasi.v_report_da_notificare;"

# Com'è andato l'ultimo passo PA dell'alert:
docker compose -f deployment/docker-compose.yml exec -T db_trasi \
  psql -U automazioni -d trasi_db -c \
  "SELECT esito, dettaglio->'report_pa' AS report_pa FROM trasi.flusso_run
   WHERE nome = 'alert' ORDER BY id DESC LIMIT 1;"

# Recapito configurato (vuoto = modalità file):
docker compose -f deployment/docker-compose.yml exec -T db_trasi \
  psql -U automazioni -d trasi_db -c "SELECT trasi.p_text('email_report_pa');"
```
