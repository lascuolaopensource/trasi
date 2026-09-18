# Trasi — `deployment/` (infrastruttura, blocco B0)

Stack Trasi in Compose. **Convive con Onyx**, che resta nel suo compose separato
(`/opt/onyx/deployment/docker_compose`): questo stack non tocca `/opt/onyx/**`.

| File | Ruolo |
|---|---|
| `docker-compose.yml` | Stack completo (7 servizi Trasi + Postgres/Redis di Activepieces) |
| `.env.example` | Variabili documentate, **senza segreti** — è il modello versionato |
| `.env` | Valori reali, **mode 600**, escluso da git (v. `deployment/.gitignore`) |
| `searxng/settings.yml` | Config SearXNG interna (abilita `format=json` per lo shim) |
| `caddy/Caddyfile` | Reverse proxy: Trasi Home/NocoDB/Metabase + Onyx |
| `home/` | Radice del sito statico servita da Caddy (segnaposto B0; contenuto reale = blocco B6) |

## Avvio selettivo (decisione motivata)

**In B0 si avviano solo i due servizi che servono ai gate:**

```bash
docker compose up -d db_trasi searxng
```

`nocodb`, `metabase`, `activepieces`, `ap_postgres`, `ap_redis`, `caddy` e `shim`
restano **definiti ma spenti**: li avviano i blocchi che li richiedono (B1/B3/B4/B5/B6).

**Perché.** L'host ha **~4,85 GB liberi** con Onyx attivo (~6 GB). La somma dei
`mem_limit` dei 7 servizi Trasi è **5,08 GiB** (≈ quanto indicato nella spec), a cui
si aggiungono **320 MiB** per il Postgres/Redis propri di Activepieces:
**5,39 GiB in totale** su ~4,85 GB disponibili ⇒ avviare tutto significherebbe
**over-commit** su una macchina che ospita anche Onyx. Con l'avvio selettivo la
misura reale è:

```
trasi-searxng-1   163.5MiB / 512MiB   (31.9%)
trasi-db_trasi-1   72.8MiB / 1GiB     (7.1%)
```

Limiti per servizio (nessun over-commit): `db_trasi` 1g (`shared_buffers=256MB`),
`searxng` 512m, `shim` 256m, `nocodb` 512m, `metabase` **2g** dal 2026-09-16
(era 1.5g; `JAVA_OPTS=-Xmx1g` invariato — v. «Servizio metabase»),
`activepieces` 1.2g, `caddy` 128m, `ap_postgres` 256m, `ap_redis` 64m,
`automazioni` 256m.

## Binding: solo loopback

Nessun servizio pubblica su `0.0.0.0`. La pubblicazione esterna passa dal
**tunnel Cloudflare** già presente sull'host.

- `db_trasi` → `127.0.0.1:5432`
- `searxng` → **nessun binding**: si raggiunge solo dalla rete Docker `trasi_net`
  (`http://searxng:8080`), coerente con B0-STK-03 «nessuna porta pubblica»
- Gli altri servizi usano porte host dedicate (`8001` shim, `8081` nocodb,
  `3001` metabase, `8082` activepieces, `8088/8443` caddy), sempre su `127.0.0.1`.

Le porte `80`/`3000` dell'host sono **già occupate da onyx-nginx**: Caddy usa
quindi `8088`/`8443`.

## Overpass: endpoint e fallback

```env
OVERPASS_URL=https://overpass.openstreetmap.fr/api/interpreter
OVERPASS_URL_2=https://overpass-api.de/api/interpreter
```

**Misure reali del 15/09 su questo host** (l'endpoint `.de` non è utilizzabile
come primario):

| Endpoint | Esito |
|---|---|
| `overpass-api.de` | **406** con user-agent curl/python e su ogni path (GET e POST); 200 solo con certi UA non-python, poi **429** sotto richieste ravvicinate. Inaffidabile. |
| `overpass.openstreetmap.fr` | **200 + JSON valido** (20 bar in un bbox di Brindisi), stabile su 3 esecuzioni |
| `overpass.osm.ch` | 200 ma dati **stantii** (`timestamp_osm_base` = `117035`, valore non valido) → scartato come fallback |
| `overpass.kumi.systems` | **timeout** (>45 s, 0 byte) → **non utilizzabile** |

> Lo spec indicava `kumi.systems` come esempio di `OVERPASS_URL_2`: è stato
> sostituito con `.de` perché `kumi.systems` non risponde da questo host
> (deviazione tracciata nel report B0).

### ⚠️ User-Agent obbligatorio (misurato, riguarda B3)

Le istanze Overpass filtrano per **User-Agent**. L'endpoint primario `.fr`
risponde **403 «This service is only available to white-listed usages»** se lo UA
è quello dei client Python:

| User-Agent | `.fr` |
|---|---|
| `python-httpx/0.27.0`, `python-requests/2.32.3`, `Mozilla/5.0` | **403** |
| `Trasi/1.0 (+https://trasi.lascuolaopensource.org)`, `PostmanRuntime` | **200 + JSON** |

Il client Overpass dello shim (**B3-SHM-04**) **deve** inviare uno User-Agent esplicito
e non-python, altrimenti la via live resta rotta indipendentemente dall'endpoint.
Non è stato introdotto un env dedicato perché il contratto shim è congelato:
la nota è qui e nel `.env.example`.

**Contesto dati (V-extra OSM, già negativo):** la copertura `opening_hours` a
Brindisi è molto scarsa (bar 7,7%). In B3 i POI OSM senza orari **non** vanno
scartati: restano elencati **dopo** gli aperti noti con `aperto_adesso:null` e
`orari_nota="orari non disponibili"`.

## Contratto congelato con lo shim (V-09)

Invariato, come da spec:

- build dir `../shim` (il `Dockerfile` lo fornisce il worker `trasi-shim`), nome servizio `shim`, porta interna `8000`
- healthcheck `GET /healthz` → 200
- env: `DATABASE_URL`, `TRASI_SHIM_KEY`, `OVERPASS_URL`, `OVERPASS_TIMEOUT_S=5`, `SHIM_TIMEOUT_S=3`, `TZ=Europe/Rome`
- `OVERPASS_URL_2` è **additivo** (concordato con il worker shim: la sua `Settings` ignora le variabili extra)

Il compose **valida anche con `../shim` assente** (verificato: `Dockerfile` mancante non blocca `docker compose config`).

### Contratto verificato end-to-end (Dockerfile consegnato dal worker shim)

Una volta che il worker ha consegnato `shim/Dockerfile`, il servizio è stato
buildato e provato per davvero, poi **fermato** (in B0 restano attivi solo
`db_trasi` e `searxng`):

```
$ docker compose build shim   → Image trasi-shim:local Built
$ docker compose up -d shim   → Up (healthy)
$ curl -i http://127.0.0.1:8001/healthz
HTTP/1.1 200 OK
server: uvicorn
{"status":"ok"}
$ curl -o /dev/null -w '%{http_code}' \
    'http://127.0.0.1:8001/v1/u/op.san-bao@trasi.local/oggi?casa=san-bao'
501                      # stub del contratto v0: come atteso
```

Binding: `127.0.0.1:8001->8000/tcp` (loopback only).

## Onyx: rete condivisa invece di `host.docker.internal`

La spec chiedeva, per Caddy, `onyx.lascuolaopensource.org → host.docker.internal:80`.
**Quella rotta non funziona su questo host** (misurato):

```
$ docker run --rm --add-host=host.docker.internal:host-gateway alpine \
    sh -c 'wget -T 5 -O /dev/null http://host.docker.internal:80/'
wget: can't connect to remote host (172.17.0.1): Connection refused
```

`onyx-nginx` pubblica la porta 80 **solo su `127.0.0.1`**: dal gateway del bridge
Docker (`172.17.0.1`) non è raggiungibile. La soluzione adottata è **raggiungere
Onyx per nome servizio** sulla sua rete Docker:

```yaml
# caddy
networks: [trasi_net, onyx_net]
# ...
onyx_net:
  name: onyx_default
  external: true
```

verificato funzionante: `docker run --network onyx_default alpine` →
`http://nginx:80/` risponde. Il Caddyfile proxya a `nginx:80`.

## Segreti

- `.env` è **mode 600** ed è escluso da git tramite `deployment/.gitignore`
- `.env.example` non contiene valori reali (solo `CHANGE_ME` documentati)
- Nessun segreto compare nei log: verificato `docker logs` dei container attivi e
  `docker compose logs` → 0 occorrenze delle password

**Limite dichiarato (non nascosto).** I segreti passano ai container come **variabili
d'ambiente**, quindi sono leggibili da `docker inspect` da chiunque abbia accesso al
demone Docker (equivalente a root sull'host). È il compromesso standard di Compose e
il piano non richiede Docker secrets; su questo host il demone è già accessibile solo
da root. Se in S2 l'hardening lo vorrà, la via è `deploy.secrets`/`*_FILE` senza
cambiare l'invocazione. `automazioni` attenua già il punto per sé: l'entrypoint copia
le credenziali in `/run/trasi/env` **mode 600, owner `automazioni`** e i job le leggono
da lì invece di averle in chiaro nel crontab.

## Servizio `automazioni` (B4) — incluso nel compose

I flussi notturni (cron: 01:00 export KB · 05:00 applica · 06:00 fonti · 07:30 alert)
vivono in `docker-compose.automazioni.yml` (owner B4) e sono **inclusi** dal compose
principale con una riga `include:` in fondo a `docker-compose.yml`, così l'invocazione
del runbook §8 (`docker compose up -d`) li vede senza un secondo `-f`.

`include` **non avvia nulla da solo**: l'avvio selettivo di B0 resta
`docker compose up -d db_trasi searxng`, e `automazioni` si accende quando serve.

**Due difetti trovati in verifica (entrambi riprodotti e corretti):**

1. **Healthcheck `unhealthy` con cron vivo.** Il container usava `pgrep`, che **non è
   installato** nella sua immagine (`python:3.12-slim` senza `procps`): usciva 127
   (`/bin/sh: 1: pgrep: not found`) e il container risultava *unhealthy* mentre cron
   girava. Corretto con `pidof cron` (`sysvinit-utils`, già presente come dipendenza di
   `cron`: zero pacchetti in più). Verificato dopo il rebuild: `Up (healthy)`.
2. **`external: true` su `trasi_net`** avrebbe impedito la prima installazione: nel
   config aggregato `trasi_net` diventava esterna, e su un host pulito
   `docker compose up -d` falliva con «network trasi_net declared as external, but
   could not be found» — *exit 0 con 0 container avviati*, cioè fallimento silenzioso.
   Corretto dichiarando `trasi_net` con `name:` + `driver: bridge`, senza `external`.
   (Su questo host il difetto non si vedeva, perché la rete esiste da B0.)

**Integrazione con Onyx (corretta in verifica):** l'export KB (F3) chiama
`http://nginx/api/onyx-api/ingestion`, e `nginx` risolve **solo** su `onyx_default`.
Da `trasi_net` il nome non risolveva (NXDOMAIN): l'export da container sarebbe fallito.
`automazioni` ora sta su **entrambe** le reti (`[trasi_net, onyx_net]`). Verificato:

```
$ docker exec trasi-automazioni-1 python3 -c "...urlopen('http://nginx/api/health')..."
http://nginx/api/health -> OK
$ docker exec trasi-automazioni-1 sh -c '. /run/trasi/env; psql -Atc "SELECT current_user"'
automazioni
```

`onyx_net` resta `external: true` **qui è corretto**: è la rete di Onyx, non nostra
(mentre `trasi_net` è nostra e dobbiamo crearla). Verificato che `docker compose down`
del progetto Trasi non tocca Onyx: rimuove solo i container `trasi-*` e lascia
`trasi_net` in vita finché un container Onyx vi è attestato («Resource is still in use»).

## Servizio `metabase` (B5) — dashboard, k-anonimato, alert

Avviato in B5 (era definito e spento dalla scelta di RAM di B0). Configurazione
delle dashboard **non** cliccata a mano: `metabase/dashboard.py` e `metabase/alerts.py`
sono la fonte di verità e sono idempotenti per nome, come `db/apply.sh` lo è per file.

```bash
docker compose up -d metabase          # il servizio, con mem_limit 2g e -Xmx1g
metabase/provisiona.sh                 # admin + connessione «Trasi» (credenziali in .secrets/)
python3 metabase/dashboard.py          # 3 dashboard: Rete, Casa, Mappa
python3 metabase/alerts.py             # 40 alert (10 Case x 4 tipi F6)
```

**App-DB: H2 su volume**, non Postgres — scelta di budget di B0 (`METABASE_DB_TYPE=h2`,
`metabase_data`). Il warning di Metabase è reale e va ripetuto: H2 non è raccomandato
per la produzione e va incluso nel backup (B6, `ops/backup.sh`). La **source** verso
il dominio è invece Postgres, con il ruolo `metabase_ro` in sola lettura.

**Least-privilege (`db/007_dash.sql`).** Alla verifica di B5 `metabase_ro` leggeva
`proposta` (40 righe) e `audit` (50 righe) in chiaro: due `GRANT` di db/005 lo
elencavano insieme ai ruoli che quel dato devono averlo. La matrice §11/§12 dice
l'opposto e il criterio B5-DSH-01 lo verifica, quindi `007_dash.sql` revoca
`proposta`, `audit`, `fonte_run` (e `richiesta`/`identita_onyx`, già negate) e
controlla **l'effetto**, non l'intenzione. Gli indirizzi di recapito per gli alert
non passano da `identita_onyx` ma da `trasi.v_flusso_recapiti` (proiezione minima
di B4: `casa_slug`, `destinatario`, `destinatario_ruolo`).

**RAM: il limite era 1.5g, dal 2026-09-16 è 2g (decisione del TI).** Metabase usa `-Xmx1g`
**invariato**: l'heap resta governato da `-Xmx`, e il tetto più alto serve all'overhead fuori
dall'heap (metaspace, stack dei thread, GC, mmap). Stato a fine B5, con il tetto vecchio:

```
$ docker stats --no-stream --format '{{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}' trasi-metabase-1
trasi-metabase-1   1.393GiB / 1.5GiB   92.83%
$ docker inspect trasi-metabase-1 --format 'restart={{.RestartCount}} oom={{.State.OOMKilled}} exit={{.State.ExitCode}}'
restart=1 oom=false exit=0
```

**Due letture di quei numeri che erano sbagliate, e che vale la pena correggere:**

1. **Il riavvio non era un crash.** `FinishedAt` del container vecchio e `StartedAt` del nuovo
   distano **0,28 s**, con `ExitCode=0` e `OOMKilled=false`: è una **ricreazione**
   (`docker compose up`), non il kernel che uccide il processo.
2. **Il «92%» non era memoria del processo.** `docker stats` e `memory.current` includono la
   **page cache** del container, che è *file-backed* e **reclamabile** sotto pressione. Il numero
   che conta è **`anon`**. Misurato sotto il carico di B7 (4 operatori × 10 card in parallelo, 40
   query concorrenti):

```
$ cat /sys/fs/cgroup/system.slice/docker-$CID.scope/memory.stat
anon    1199 MiB   ← memoria vera del processo (heap 1 GB + metaspace/thread/GC)
file     645 MiB   ← page cache, reclamabile
current 1873 MiB su max 2048 MiB · peak 1980 MiB · memory.events → oom_kill 0
```

Ogni card risponde in **30–70 ms** (una a freddo: 410 ms) e 10 query in serie muovono l'`anon` di
**~3 MiB**: il carico di lettura non alloca in modo significativo, perché le card leggono viste già
aggregate. Le 4 occorrenze di «out of memory» nei log di Metabase sono **falsi positivi** — sono nomi
di autore di changeset Liquibase (`heypoom`, `phoomparin`).

Con il tetto a 2g il margine reale è `2048 − 1199 = 849 MiB` di memoria non reclamabile, contro i
~100 MiB apparenti di prima. La decisione (e la sua motivazione) è del TI; i numeri sono questi.

**NocoDB non è avviato** in B5 (RAM): i link «coda» delle dashboard puntano al path
pubblico e rispondono quando NocoDB entra in funzione in B6.

**SMTP non configurato.** Metabase invia email solo con un server configurato
(`Admin › Settings › Email`); i 40 alert sono configurati e restano attivi, ma finché
SMTP non c'è non consegnano. La prova di recapito di B5 è stata fatta con un sink
SMTP usa-e-getta in `/tmp`, poi rimosso: l'esito è in `docs/verifiche.md`, e la
configurazione SMTP è stata **ripristinata a vuoto** dopo la misura.

**Una sola email per tipo di avviso.** `flussi/alert.py` (B4) manda già *proposte in
attesa* e *coerenza fonti*. I 4 alert F6 di B5 sono: 3 con email (scaduti, in
scadenza, senza risposta) e 1 **configurato e spento** (proposte in attesa), che si
accende con `alerts.py --accendi-proposte` se la proprietà di quell'email si sposta a
Metabase. Le 10 notification spente sono la scelta scritta, non una dimenticanza.

## Cron e ops (blocco B6) — consegnati

6 job del piano §6, distribuiti su **due crontab con due proprietari** (8 righe di schedulazione),
nessuna sovrapposizione. Il runbook completo è `docs/runbook.md`.

| Ora | Job | Dove | Owner |
|---|---|---|---|
| 01:00 | export KB (F3) | `flussi/crontab` → container `automazioni` | B4 |
| **02:00** | **backup** | `ops/crontab` → host | **B6** |
| **03:00** | **retention chat** | `ops/crontab` → host | **B6** |
| 05:00 | `applica_proposte` (F9) | `flussi/crontab` → container `automazioni` | B4 |
| 06:00 / 06:15 | coerenza fonti iCal / HTTP (F4) | `flussi/crontab` → container | B4 |
| 07:30 | alert (F6) | `flussi/crontab` → container | B4 |
| **giorno 3, 08:00** | **ciclo mensile** (F5) | `ops/crontab` → host; **codice di `flussi/`** | **B6** schedula / B4 esegue |

**Perché l'host per i tre job di esercizio.** Il container `automazioni` non ha — e non deve avere —
il socket Docker, i volumi, o l'accesso al database di Onyx: il backup li usa tutti e tre, la
retention esegue codice dentro il container di Onyx. Dare al container quelle capacità significherebbe
dare a un esecutore del dominio il controllo dell'host.

### `ops/` — gli script (tutti eseguibili a mano e ripetibili)

| File | Cosa fa |
|---|---|
| `backup.sh` | dominio (`pg_dump -Fc`) + **ruoli** (`pg_dumpall --globals-only`) + chat di Onyx + configurazione + App-DB di Metabase, con manifest `sha256` e rotazione (7) |
| `restore_test.sh` | **prova di restore reale** su un DB di prova (`trasi_restore_test`, da `template0`) con `count(casa)=10` e le verifiche di RLS/GRANT |
| `retention_chat.py` / `.sh` | retention delle chat di Onyx, con le funzioni di Onyx (non una `DELETE`: i file stanno su MinIO) |
| `ciclo_mensile.sh` | **schedula** il ciclo F5 (codice di `flussi/ciclo_mensile.py`, owner B4) verificando che il giorno coincida con `trasi.paremetro.giorno_ciclo_mensile` |
| `install_cron.sh` | installa `ops/crontab` validando che ogni riga sia in **formato crontab utente** e che i comandi esistano |
| `crontab` | le 3 righe di schedulazione |

**Esiti reali (prove eseguite, non dichiarate):**

```
$ ops/backup.sh
── 1/5 dominio  233K · ── 2/5 ruoli 1.0K (21 CREATE ROLE) · ── 3/5 onyx 946K (54 chat)
── 4/5 config 336K · ── 5/5 metabase 6.6M  → rotazione: 7 conservati

$ ops/restore_test.sh <dump>
ESITO VERDE — 13 PASS, 0 FAIL · count(casa)=10

$ ops/retention_chat.sh --giorni 365        # fixture sintetica a 400 gg
retention_chat: cancellate 1 sessioni (0 errori) · chat_session 55→54 · chat_message 210→210

$ crontab -l                                 # 3 righe host
0 2 * * *   …/ops/backup.sh >> /var/log/trasi/backup.log 2>&1
0 3 * * *   …/ops/retention_chat.sh >> /var/log/trasi/retention.log 2>&1
0 8 3 * *   …/ops/ciclo_mensile.sh >> /var/log/trasi/ciclo_mensile.log 2>&1
```

**I ruoli sono nel backup, e non è un dettaglio.** `pg_dump` salva *un database*, i ruoli vivono nel
**cluster**: senza `pg_dumpall --globals-only` un ripristino produce un database le cui policy RLS non
si applicano a nessuno. Misurato: il manifest registra `ruoli_cluster = 21`,
`ruoli_create_role_nel_backup = 21`.

**Due difetti trovati eseguendo (non leggendo):**

1. **`--no-owner --no-privileges` rendeva il ripristino inutile.** `nspacl` dello schema `trasi`
   restava **vuoto** → i 17 ruoli perdevano il `USAGE` → il test RLS cross-Casa non era nemmeno
   eseguibile (`permission denied for schema trasi` invece di `UPDATE 0`). Rimosso dal dump del
   dominio; l'effetto è ora verificato (`GRANT = 19`, identici alla produzione).
2. **`template_postgis` faceva fallire ogni restore con un dump buono**: contiene già `topology`,
   `tiger`, `tiger_data`, quindi il `CREATE SCHEMA tiger` del dump collideva e
   `--single-transaction` mandava in rollback **tutto**. Corretto creando il DB di prova da
   `template0`.

### Retention chat: **il gap è dichiarato**, non aggirato

Onyx **ha** una retention nativa (task Celery `check_ttl_management_task`, beat ogni ora — verificato
nei log: `Sending due task check-ttl-management-public`), ma è chiusa dal tier:

```
$ curl -X PATCH http://127.0.0.1:80/api/admin/settings -d '{"maximum_chat_retention_days": 30}'
{"error_code":"FEATURE_NOT_AVAILABLE","detail":"Chat history retention requires the Enterprise plan."}
HTTP 402
```

Installazione **Community** (nessuna licenza, `license` → 0 righe). Il task gira, legge una soglia
`None`, e non cancella: **container sano, beat vivo, retention ferma**. Non esiste una variabile
d'ambiente alternativa. Le strade sono la **licenza Enterprise** (nativa) o **`ops/retention_chat.sh`**
(il fallback previsto dal piano, consegnato). **Non** si aggira il gate scrivendo in
`key_value_store`: sarebbe l'aggiramento di un controllo di licenza e un deployment la cui UI rifiuta
la configurazione che il DB contiene. Dettagli in `docs/runbook.md` §5.2.

## Servizio `caddy` (B6) — avviato, con due difetti corretti

Avviato in B6. **Due difetti reali, trovati provando l'endpoint (non leggendo il Caddyfile):**

1. **`auto_https` attivo** → Caddy tentava Let's Encrypt (impossibile da questo host: la validazione
   ACME passa dal dominio pubblico) e rispondeva `308 → https://` su ogni richiesta HTTP. Il tunnel
   inoltra **in HTTP** → riceveva un redirect verso un host senza certificato → **525** dall'edge.
   Corretto con `auto_https off`.
2. **I blocchi sito ascoltavano solo su `:443`**: `{$TRASI_DOMAIN}` è un nome con hostname, e Caddy
   per esso sceglie il server HTTPS. Su `:80` la connessione veniva **azzerata**
   (`Recv failure: Connection reset by peer`). Corretto con `http://{$TRASI_DOMAIN}` e
   `http://{$ONYX_DOMAIN}`.

Verificato dopo la correzione:

```
$ curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: trasi.lascuolaopensource.org' http://127.0.0.1:8088/
200
$ curl -s -H 'Host: trasi.lascuolaopensource.org' \
    'http://127.0.0.1:8088/api/shim/v1/u/rete@trasi.local/oggi?casa=bozzano'
{"casa":"bozzano","eventi":0,…,"testo":"Oggi a Centro di Aggregazione Bozzano: 0 eventi · …"}
$ curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: onyx.lascuolaopensource.org' http://127.0.0.1:8088/
200
$ curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: trasi.lascuolaopensource.org' http://127.0.0.1:8088/metabase/
200
$ curl -s -o /dev/null -w '%{http_code}\n' -H 'Host: trasi.lascuolaopensource.org' http://127.0.0.1:8088/nocodb/
502                      # atteso: NocoDB è spento (RAM)
```

**Rotta `/api/shim/*`** (per la riga «Oggi» della Home): `handle_path` toglie il prefisso e Caddy
**inietta** `X-Trasi-Key` da `{env.TRASI_SHIM_KEY}` (aggiunto all'`environment` del servizio). La
chiave **non** sta nel JS: la Home è un sito statico senza autenticazione, quindi una chiave scritta
lì sarebbe pubblica — una chiave pubblica non è una chiave.

⚠️ **Il tunnel Cloudflare non ha un ingress per `trasi.lascuolaopensource.org`** — verificato con
`curl http://127.0.0.1:20241/config` (ingress presenti: `orca.…`, `onyx.…`, più un 404 di default).
Caddy serve correttamente su `:8088`, ma la pubblicazione esterna richiede una regola di ingress
aggiunta dal TI: su questo host non ci sono le credenziali (`/etc/cloudflared/` contiene solo
`credentials.json` di un tunnel token-based).

## Login operatore CdQ (schede !NEW, US-6.x)

Ogni Casa di Quartiere ha **una sola credenziale condivisa** per gli operatori: utente = **slug della
Casa** (es. `sanbao`, `tuturano`), password per Casa. Niente account per i cittadini (decisione del
2026-09-16: vietati per 12 mesi) e **nessun redirect verso Onyx**: il browser entra solo sul dominio
Trasi, e la chat con l'assistente passa dallo shim server-to-server.

Il login è un endpoint dello shim (`POST /login`, accanto a `POST /logout` e `GET /me`): i client non
toccano mai il database.
Dopo il login il browser riceve un **cookie `trasi_sessione`** (HttpOnly + SameSite=Lax, quindi
non leggibile dal JavaScript della pagina) e tutte le operazioni (scheda evento, registrazione
richiesta, attrezzoteca, chat interna) avvengono con quel cookie.

| Aspetto | Valore |
|---|---|
| Durata sessione | **12 ore** — parametro DB `session_ttl_hours`; passate le 12 h si rifà il login |
| Blocco anti brute-force | **più di 4 tentativi falliti in 10 minuti** → la Casa è bloccata per 10 minuti (non serve sblocco manuale: il blocco scade da solo) |
| Password | hash `crypt`/bcrypt (pgcrypto) sul DB; la password in chiaro non è conservata da nessuna parte |
| Password iniziale | **`<slug>2026!`** (es. per San Bao: `sanbao2026!`) — **da cambiare alla prima consegna** con la procedura sotto |

### Prima attivazione di una Casa

Lo slug è quello della tabella `casa` (v. NocoDB «Casa» o `SELECT slug FROM trasi.casa;`).

```bash
docker exec trasi-db_trasi-1 psql -U postgres -d trasi_db -c "
  SET ROLE ti; SET search_path = trasi, public;
  INSERT INTO credenziale_casa (casa_id, pass_hash)
  SELECT c.id, crypt('<slug>2026!', gen_salt('bf'))
  FROM casa c WHERE c.slug = '<slug>'
  ON CONFLICT (casa_id) DO NOTHING;"
```

### Cambio password (richiesta della Casa, o password iniziale da cambiare)

Può farlo **solo il ruolo `ti`** — non l'operatore della Casa da solo. Comando con la **nuova**
password scelta (evitare spazi e apici):

```bash
docker exec trasi-db_trasi-1 psql -U postgres -d trasi_db -c "
  SET ROLE ti; SET search_path = trasi, public;
  UPDATE credenziale_casa c SET pass_hash = crypt('NUOVA_PASSWORD', gen_salt('bf')),
       aggiornato_ts = now(), aggiornato_da = current_user
  FROM casa s WHERE s.id = c.casa_id AND s.slug = '<slug>';"
```

`UPDATE 1` = cambiata; `UPDATE 0` = credenziale mai creata per quello slug → usare la procedura di
prima attivazione. Dopo il cambio, le sessioni già aperte restano valide fino allo scadere naturale
(≤ 12 h); per tagliarle subito:

```bash
docker exec trasi-db_trasi-1 psql -U postgres -d trasi_db -c "
  SET ROLE ti; SET search_path = trasi, public;
  DELETE FROM sessione s USING casa c WHERE c.id = s.casa_id AND c.slug = '<slug>';"
```

### Subentro dell'ente gestore

**Stessa identica procedura del cambio password**: nuova password con l'`UPDATE` sopra, poi il
`DELETE` delle sessioni. Le vecchie credenziali smettono di funzionare sul colpo; le sessioni già
aperte dai precedenti operatori decadono al più tardi entro 12 ore. Il runbook non prevede altro:
non c'è archivio delle password vecchie e non serve riavviare nessun servizio.

### Note operative

- **Nessun lockout permanente**: il blocco dopo > 4 fallimenti scade da solo in 10 minuti; se una Casa
  segnala «non riusciamo più ad entrare», aspettare 10 minuti e riprovare con calma.
- I tentativi di login sono tracciati in `trasi.tentativo_login` (solo ora e Casa, mai la password):
  utile per capire se un blocco è un errore umano o un rumore esterno.
- La Home pubblica (`trasi.…`) **non** richiede login: resta aperta come prima. Il login riguarda solo
  le funzioni operatore sotto `/op/…`.

## Eccezioni V4 aggiornate (schede !NEW)

V4 resta la regola: **le scritture al dominio avvengono solo via proposta → approvazione →
applicazione con audit**. Le schede `!NEW` aggiungono due eccezioni documentate all'unica preesistente
(import iCal). Decisioni del 2026-09-16 in `docs/confronto-sistema-nuove-funzionalita.md` §2. Tutte e
tre le eccezioni scrivono comunque una riga in `trasi.audit`.

| Eccezione | Perché non può passare dal flusso proposte |
|---|---|
| **Import iCal** (preesistente, `flussi/fonti_ical.py`) | È una sincronizzazione automatica da fonte esterna dichiarata (V3): la fonte è già la garanzia, e ogni evento importato porta badge e fonte. Un passaggio manuale per evento renderebbe l'import inutile. |
| **`registra_richiesta` (`POST /op/registra_richiesta`)** | La registrazione avviene **durante** il colloquio allo sportello: non può attendere la coda di approvazione. La riga `richiesta` non contiene comunque dati del cittadino (V5) — solo categoria, esito, destinazione; l'audit (`azione='registra_richiesta'`) conserva il chi/quando. |
| **Movimento attrezzoteca (prestito tra Case)** | È un evento operativo concordato tra due Case, non una modifica di scheda: la tutela V4 è garantita dalla **conferma della Casa ricevente** (`conferma_movimento`, solo `a_casa` può confermare) e dall'audit su ogni passaggio di stato. |
| **Oggetto dell'attrezzoteca della propria Casa** (`salva_dato` con `entita=oggetto`, `db/032`, 2026-09-18) | Non è un'eccezione nuova: è la **scrittura diretta della propria Casa (D1)** già ammessa per scheda, opportunità, evento e persona — con un solo accesso per Casa la proposta su un oggetto proprio non ha un secondo umano che la decida. La RLS (`ogg_ins_casa`/`ogg_upd_casa`: `casa_id = casa_corrente()`) è l'autorità; nessun DELETE (ritiro = `attivo=false`); `v_scritture_senza_audit` esclude già le scritture della propria Casa. Gli oggetti delle **altre** Case restano nel flusso proposte (`nuovo_oggetto`/`modifica_oggetto`/`ritira_oggetto`, decide l'AT). |

Mantenere la lista **chiusa**: una nuova eccezione richiede una riga qui **prima** del codice, con la
motivazione, come per quelle sopra.

## Domande aperte / punti non risolti in B0

1. **Rate limit Caddy** (plan §12 p. 6, «60 req/min/IP»): **non implementato**.
   L'immagine ufficiale `caddy:2-alpine` **non contiene il modulo `rate_limit`**
   (verificato: `caddy list-modules` → 0 moduli `rate*`); serve un build custom
   (`xcaddy` + `caddy-ratelimit`). È comunque una domanda aperta TI+DPO nel piano.
2. **Metabase e NocoDB dietro path prefix** (`trasi…/metabase`, `trasi…/nocodb`):
   entrambi sono documentati come **non pienamente supportati su subpath**
   (asset e socket.io di NocoDB, redirect/click-behavior di Metabase). Il piano
   prevede in alternativa **sottodomini** (`metabase.`/`nocodb.`) sullo stesso
   tunnel: decisione rimessa al TI (domanda aperta di piano, non risolta in B0).
3. **Nessun `rate_limit` né TLS su Caddy**: TLS è delegato al tunnel Cloudflare;
   le porte `8443` sono predisposte ma non usate finché il tunnel non le punta.
