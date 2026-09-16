# TASK SPEC — Worker `trasi-stack` (blocco B0, infrastruttura)

## Target

Crea da zero l'infrastruttura Trasi in `/root/orca/projects/onice/deployment/`:
- `docker-compose.yml` — stack Trasi completo
- `.env.example` — variabili documentate (nessun segreto reale)
- `.env` — valori reali generati, mode 600

NON toccare `/opt/onyx/` (istanza Onyx già attiva su questo host, in uso).

## Change

### 1. Compose completo (tutti i servizi definiti)
Servizi richiesti (nomi **esatti**, sono contratto con gli altri worker):

| Servizio | Immagine | Porta interna | Limite memoria |
|---|---|---|---|
| `db_trasi` | `postgis/postgis:16-3.4` | 5432 | `mem_limit: 1g`, `shared_buffers=256MB` |
| `searxng` | `searxng/searxng` | 8080 | `mem_limit: 512m` |
| `shim` | build `../shim` | 8000 | `mem_limit: 256m` |
| `nocodb` | `nocodb/nocodb` | 8080 | `mem_limit: 512m` |
| `metabase` | `metabase/metabase` | 3000 | `mem_limit: 1.5g`, `JAVA_OPTS=-Xmx1g` |
| `activepieces` | `activepieces/activepieces` | 80 | `mem_limit: 1.2g` |
| `caddy` | `caddy:2-alpine` | 80/443 | `mem_limit: 128m` |

Regole:
- **Port binding SOLO su `127.0.0.1`** (mai `0.0.0.0`). La pubblicazione esterna passa dal tunnel Cloudflare esistente.
- `restart: unless-stopped` su tutti + `healthcheck` reale su ognuno.
- Rete Docker unica `trasi_net`, condivisa col servizio `shim`.
- Volumi nominati per la persistenza (`db_trasi_data`, `metabase_data`, `nocodb_data`, `activepieces_data`, `caddy_data`).
- `logging` json-file con `max-size: 10m`, `max-file: 3` su tutti.
- Caddy: reverse proxy verso i servizi interni (config in `deployment/caddy/Caddyfile`), `trasi.lascuolaopensource.org` → home/nocodb/metabase, `onyx.lascuolaopensource.org` → `host.docker.internal:80` (Onyx è su compose separato).

### 2. CONTRATTO CONGELATO con worker `trasi-shim` (non negoziabile)
Il servizio shim è così, e il worker shim sta già lavorando su questa base in parallelo:
- directory build: `../shim`
- nome servizio: `shim`, hostname interno: `shim`
- porta interna: `8000`
- healthcheck: `GET /healthz` → 200
- variabili d'ambiente attese dallo shim: `DATABASE_URL`, `TRASI_SHIM_KEY`, `OVERPASS_URL`, `OVERPASS_TIMEOUT_S=5`, `SHIM_TIMEOUT_S=3`, `TZ=Europe/Rome`
- **Non** definire un `Dockerfile` per shim: lo fornisce il worker shim.

### 3. Avvio SELETTIVO — decisione motivata
**NON avviare tutto**: sull'host ci sono **4.849 MB liberi** e i limiti sommano ~5,05 GB. Avvia **solo ciò che serve ai gate B0**:
```
docker compose up -d db_trasi searxng
```
`nocodb`, `metabase`, `activepieces`, `caddy`, `shim` restano **definiti ma spenti** — verranno avviati nei blocchi che li richiedono (B1/B4/B5). Documenta questa decisione in una nota nel README di `deployment/`.

### 4. Overpass: endpoint e fallback
`overpass-api.de` è **bloccato da questo host** (connection refused, verificato). Nei file d'ambiente usa:
`OVERPASS_URL=https://overpass.openstreetmap.fr/api/interpreter`
Aggiungi `OVERPASS_URL_2` (es. `https://overpass.kumi.systems/api/interpreter`) come failover documentato.

## Constraints

- **V4**: nessuna scrittura alla memoria applicativa fuori dal flusso proposta→approvazione→applica. Tu tocchi solo infrastruttura: nessuna query che scriva dati di dominio.
- **RAM**: nessun over-commit. Limiti espliciti come da tabella.
- **Segreti**: `.env` mode 600; `.env.example` senza valori reali; mai stampare segreti in output (né in questo report).
- Non modificare l'istanza Onyx né i suoi container.
- Non installare pacchetti di sistema; solo Docker.

## Ownership

Puoi creare/modificare: `deployment/**`. Non toccare: `shim/**` (altro worker), `plan.md`, `docs/trasi-architecture-v1.2.md`.

## Observable acceptance (prove da produrre, con output reale)

1. `docker compose config --quiet` → exit 0 (config valida).
2. `docker compose ps` → `db_trasi` e `searxng` **healthy**.
3. **PostGIS vivo** (gate V-03a): `docker compose exec -T db_trasi psql -U postgres -c "SELECT postgis_full_version();"` → output con la versione PostGIS.
4. **SearXNG vivo** (B0-STK-03): `docker compose exec -T searxng curl -s -o /dev/null -w '%{http_code}' 'http://localhost:8080/search?q=prova'` → 200; e da fuori: nessuna porta esposta su `0.0.0.0` (`docker compose ps` mostra solo binding `127.0.0.1` o nessun binding per searxng).
5. Nessun binding pubblico: `docker compose ps --format '{{.Ports}}'` → nessun `0.0.0.0`.

Riporta nel risultato finale: i comandi eseguiti e i loro output reali (non riassunti).

## Nota su skill e contesto
Hai la skill `multi-stage-dockerfile` attiva: usala per eventuali Dockerfile. Il piano completo è in `plan.md` (blocco B0, §2 per i tagli d'emergenza, §8 runbook); l'architettura di riferimento in `docs/trasi-architecture-v1.2.md` (App. B → compose). In caso di conflitto tra i due **vince l'architettura** e il conflitto va segnalato.
