#!/usr/bin/env bash
# Trasi — ops/backup.sh · il backup del progetto (blocco B6, §8 del piano).
#
# Cosa salva, e perché ognuna di queste cose è qui:
#
#   1. `pg_dump -Fc trasi_db` — il dominio: schema, dati, funzioni, policy RLS, seed.
#      Formato custom (`-Fc`): compresso e **ripristinabile selettivamente** (`pg_restore -t`), cosa che
#      un dump SQL puro non consente. Un backup da cui non si può estrarre una sola tabella è un
#      backup che si usa solo quando è troppo tardi.
#
#   2. `pg_dumpall --globals-only` — **i ruoli**. Non stanno in `pg_dump`: `pg_dump` salva il
#      contenuto di *un database*, e i ruoli vivono nel **cluster**. Su questo progetto i ruoli sono
#      la cosa meno ricostruibile a mano: 17 ruoli (`casa_*`, `metabase_ro`, `shim_rw`, `automazioni`,
#      `trasi_owner`, …) con i loro GRANT e le loro proprietà. Un ripristino senza i ruoli produce un
#      database le cui policy RLS non si applicano a nessuno — cioè un database che sembra ripristinato
#      e non protegge nulla. La password dei ruoli **non** sta qui (è hashata in pg_authid? no:
#      `pg_dumpall` scrive `PASSWORD 'md5…'` solo se il ruolo ne ha una in chiaro *impostata in questa
#      sessione*; per i ruoli provisionati da `flussi/provisiona.sh` l'hash SCRAM **sì**, è incluso).
#      Quindi il file dei globals va trattato come **materiale sensibile**: mode 600 e directory 700.
#
#   3. `pg_dump -Fc` del database di Onyx — le chat. La retention è di Onyx (v. `ops/retention_chat.sh`
#      e il runbook): questo backup è ciò che rende una cancellazione **reversibile** entro la finestra
#      di rotazione. Senza, la retention a 30 giorni sarebbe irreversibile per costruzione.
#
#   4. I volumi che nessun dump copre: l'App-DB di Metabase (H2 su file), i file di Caddy, e i
#      binding di configurazione (`deployment/`). Metabase è al 93% del suo limite di RAM e un riavvio
#      non è gratis: ricostruire 3 dashboard + 40 alert a mano sarebbe ore di lavoro che qui sono
#      un `tar`.
#
# Non salva: i segreti di `deployment/.env` (sono già in `deployment/.env.example` come struttura, e
# il file reale è di chi lo possiede — un backup che si porta dietro le password è un backup che non
# si può lasciare dove sta) — ma **sì** i file di configurazione, che è la parte che si sbaglia a
# ricostruire. Il Caddyfile, il compose e i settings di SearXNG vanno nel tarball.
#
# Idempotenza: ogni esecuzione produce un file **nuovo** con timestamp (un backup non è idempotente per
# natura: due backup dello stesso istante devono esistere entrambi). Ciò che è idempotente è la
# **rotazione**, e il fatto che una seconda esecuzione nello stesso secondo non sovrascrive la prima:
# il nome include i secondi, e la collisione è gestita con `-1`, `-2`… invece che con una sovrascrittura
# silenziosa.
#
# Uso:
#     ops/backup.sh                       # backup completo + rotazione
#     ops/backup.sh --dry-run             # mostra cosa farebbe, non scrive
#     ops/backup.sh --senza-onyx          # salta il dump delle chat (per un test veloce)
#     ops/backup.sh --dir /tmp/prova      # cambia la destinazione
#
# Variabili (dai default sensati, sovrascrivibili):
#     TRASI_BACKUP_DIR   default /backups
#     TRASI_BACKUP_KEEP  default 7   (giorni di backup **completi** da conservare)
#     TRASI_DB           default trasi_db
#     TRASI_MB_VOLUME    default trasi_metabase_data
#
# Exit: 0 = backup scritto e verificato; 1 = almeno un passo è fallito (e il messaggio dice quale).
set -uo pipefail

cd "$(dirname "$0")/.."

# --- parametri ---------------------------------------------------------------------------------
BACKUP_DIR="${TRASI_BACKUP_DIR:-/backups}"
KEEP="${TRASI_BACKUP_KEEP:-7}"
DRY_RUN=0
SENZA_ONYX=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)     DRY_RUN=1; shift ;;
    --senza-onyx)  SENZA_ONYX=1; shift ;;
    --dir)         BACKUP_DIR="${2:-}"; shift 2 ;;
    -h|--help)     sed -n '2,45p' "$0"; exit 0 ;;
    *) echo "backup.sh: argomento non riconosciuto: $1" >&2; exit 2 ;;
  esac
done

# --- credenziali: solo da deployment/.env (mode 600), mai sulla riga di comando -----------------
# Stessa scelta di `db/apply.sh`: il file è la sola fonte, e i valori non vengono mai stampati.
if [[ -f deployment/.env ]]; then
  set -a; . deployment/.env; set +a
fi
TRASI_DB="${TRASI_DB:-trasi_db}"
POSTGRES_USER="${POSTGRES_USER:-postgres}"
# Il container del database: si usa `docker compose exec` e non `docker exec` perché è la stessa
# invocazione del resto del progetto (apply.sh, tests/run.sh), e fallisce con un messaggio chiaro
# se il servizio non è su.
COMPOSE_FILE="deployment/docker-compose.yml"
DB_SERVICE="db_trasi"
ONYX_DB_CONTAINER="${ONYX_DB_CONTAINER:-onyx-relational_db-1}"
ONYX_DB="${ONYX_DB:-postgres}"

PSQL="docker compose -f ${COMPOSE_FILE} exec -T ${DB_SERVICE} psql -U ${POSTGRES_USER} -X -q -tA"

# --- precondizioni ------------------------------------------------------------------------------
# Un backup che parte con il database fermo produce un file **vuoto o parziale** e ritorna 0:
# è il modo classico in cui un backup "verde" non contiene niente. Quindi si controlla prima.
if ! docker compose -f "$COMPOSE_FILE" ps --format '{{.Service}} {{.State}}' 2>/dev/null \
     | grep -q "^${DB_SERVICE} running"; then
  echo "backup.sh: il servizio ${DB_SERVICE} non è in esecuzione." >&2
  echo "backup.sh: avvialo con: docker compose -f ${COMPOSE_FILE} up -d ${DB_SERVICE}" >&2
  exit 1
fi

if ! ${PSQL} -c "SELECT 1" >/dev/null 2>&1; then
  echo "backup.sh: il database ${TRASI_DB} non risponde come ${POSTGRES_USER}." >&2
  exit 1
fi

# --- il timestamp, e la collisione --------------------------------------------------------------
# `date +%Y-%m-%d_%H%M%S` con i secondi: due backup nello stesso secondo sono possibili solo in una
# prova a mano. In quel caso **non si sovrascrive**: si aggiunge un suffisso. Un backup che sparisce
# perché il secondo era lo stesso è un backup di cui ci si accorge di non avere quando serve.
STAMP="$(date +%Y-%m-%d_%H%M%S)"
BASE="${BACKUP_DIR}/trasi_${STAMP}"
n=1
while [[ -e "${BASE}.manifest" ]]; do
  BASE="${BACKUP_DIR}/trasi_${STAMP}-${n}"; n=$((n + 1))
done

echo "Trasi · backup — $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "  destinazione : ${BACKUP_DIR}"
echo "  database     : ${TRASI_DB} (ruolo ${POSTGRES_USER})"
echo "  rotazione    : ${KEEP} backup completi"

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo
  echo "  (dry-run) scriverebbe:"
  echo "    ${BASE}.dominio.dump          # pg_dump -Fc ${TRASI_DB}"
  echo "    ${BASE}.globals.sql.gz        # pg_dumpall --globals-only"
  [[ "$SENZA_ONYX" -eq 0 ]] && echo "    ${BASE}.onyx.dump             # pg_dump -Fc ${ONYX_DB} (chat)"
  echo "    ${BASE}.config.tar.gz         # Caddyfile, compose, searxng, home/, metabase/*.py"
  echo "    ${BASE}.metabase.tgz          # volume ${TRASI_MB_VOLUME:-trasi_metabase_data} (App-DB H2)"
  echo "    ${BASE}.manifest              # impronta di ogni file + conteggi di verifica"
  echo "  (dry-run) rotazione: rimuoverebbe i backup più vecchi di ${KEEP}, non i più recenti"
  exit 0
fi

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR" 2>/dev/null || true

rc=0
MANIFEST="${BASE}.manifest"
# Il manifest è il cuore della verifica: senza gli `sha256` e i **conteggi di riga**, un backup
# troncato a metà (disco pieno, container morto a metà dump) è indistinguibile da uno buono fino al
# giorno del restore. Il formato è `sha256  file` — lo stesso di `sha256sum -c`, così si verifica
# con lo strumento standard e non con questo script.
{
  echo "# Trasi — manifest del backup"
  echo "# creato: $(date -Is)"
  echo "# host: $(hostname) · kernel: $(uname -r)"
  echo "# database: ${TRASI_DB} · onyx: ${ONYX_DB}"
  echo "#"
  echo "# I conteggi qui sotto sono il **contratto di integrità**: il restore di prova"
  echo "# (ops/restore_test.sh) li confronta con il database ripristinato. Se differiscono,"
  echo "# il backup è incompleto anche se pg_restore non ha protestato."
  echo "#"
} > "$MANIFEST"

# --- 1. il dominio ------------------------------------------------------------------------------
echo
echo "── 1/5  dominio → ${BASE}.dominio.dump"
# **`--no-owner --no-privileges` NON si usa**, ed è un difetto reale trovato eseguendo la prova di
# restore la prima volta (v. `docs/verifiche.md`). Toglierli sembra «più portabile», e in questo
# progetto è **distruttivo**: gli `ACL` dello schema `trasi` (`nspacl`) sono il GRANT `USAGE` ai 17
# ruoli applicativi, e le propriet* degli oggetti (`trasi_owner`, `applicatore`) determinano quali
# policy RLS si applicano. Un dump senza privilegi ripristina **le tabelle e non il sistema**:
#
#     nspacl su trasi_db          → {trasi_owner=UC/trasi_owner, casa_sanbao=U/…, rete=U/…, …}
#     nspacl sul DB ripristinato  → (vuoto)
#     has_schema_privilege('casa_sanbao','trasi','USAGE') → f
#     SET ROLE casa_sanbao; UPDATE trasi.casa … WHERE slug='bozzano'
#       → ERROR: permission denied for schema trasi
#
# cioè il test RLS cross-Casa — l'invariante centrale del progetto (§11, V4) — **non era nemmeno
# eseguibile** su un database «ripristinato con successo». Il dump deve riportare la proprietà e i
# privilegi, e il ripristino deve presupporre i **ruoli** presenti: è esattamente il motivo per cui
# il file dei globals è parte di questo backup (passo 2) e per cui il runbook li applica **prima**
# del dump. La portabilità fra cluster diversi resta possibile, ma è una scelta dichiarata nel
# runbook, non un default silenzioso che azzera la sicurezza.
if docker compose -f "$COMPOSE_FILE" exec -T "$DB_SERVICE" \
     pg_dump -U "$POSTGRES_USER" -Fc "$TRASI_DB" \
     > "${BASE}.dominio.dump" 2>/tmp/trasi_backup_err; then
  size=$(stat -c %s "${BASE}.dominio.dump" 2>/dev/null || echo 0)
  if [[ "$size" -lt 1024 ]]; then
    echo "   → FALLITO: il dump è di ${size} byte (sospetto: un dump vuoto pesa più di così)" >&2
    rc=1
  else
    echo "   → $(numfmt --to=iec "$size") · sha256 $(sha256sum "${BASE}.dominio.dump" | cut -c1-16)…"
  fi
else
  echo "   → FALLITO: $(cat /tmp/trasi_backup_err 2>/dev/null | tail -2)" >&2
  rc=1
fi

# --- 2. i ruoli (globals) -----------------------------------------------------------------------
# `--globals-only`: **solo** `CREATE ROLE`/`ALTER ROLE`/`GRANT` di cluster, nessun dato.
# L'opzione `-r` fa lo stesso; si usa la forma lunga perché è quella che si legge nel runbook.
echo
echo "── 2/5  ruoli → ${BASE}.globals.sql.gz"
if docker compose -f "$COMPOSE_FILE" exec -T "$DB_SERVICE" \
     pg_dumpall -U "$POSTGRES_USER" --globals-only \
     | gzip -9 > "${BASE}.globals.sql.gz" 2>/tmp/trasi_backup_err; then
  # **Il controllo che conta**: un `pg_dumpall --globals-only` di un cluster sano contiene i
  # `CREATE ROLE`. Se ne contiene zero (permessi, versione, un errore silenzioso su stderr mentre
  # stdout è vuoto ma l'exit è 0) il file esiste, è compresso, e non serve a niente.
  ruoli=$(zcat "${BASE}.globals.sql.gz" | grep -c '^CREATE ROLE')
  attesi=$(docker compose -f "$COMPOSE_FILE" exec -T "$DB_SERVICE" \
             psql -U "$POSTGRES_USER" -X -q -tA -c \
             "SELECT count(*) FROM pg_roles WHERE rolname NOT LIKE 'pg\_%'" 2>/dev/null | tr -d '[:space:]')
  echo "   → $(numfmt --to=iec "$(stat -c %s "${BASE}.globals.sql.gz")") · ${ruoli} CREATE ROLE (cluster: ${attesi} ruoli non-pg)"
  if [[ "${ruoli:-0}" -lt 1 ]]; then
    echo "   → FALLITO: nessun CREATE ROLE nel file dei globals" >&2
    rc=1
  fi
  {
    echo "ruoli_cluster = ${attesi}"
    echo "ruoli_create_role_nel_backup = ${ruoli}"
  } >> "$MANIFEST"
else
  echo "   → FALLITO: $(tail -2 /tmp/trasi_backup_err 2>/dev/null)" >&2
  rc=1
fi

# --- 3. le chat di Onyx -------------------------------------------------------------------------
echo
if [[ "$SENZA_ONYX" -eq 1 ]]; then
  echo "── 3/5  chat di Onyx → SALTATO (--senza-onyx)"
else
  echo "── 3/5  chat di Onyx → ${BASE}.onyx.dump"
  # Container di Onyx: non è nel nostro compose (è un'altra installazione), quindi si usa
  # `docker exec` diretto. Se non c'è, **non è un errore fatale**: il backup del dominio è valido lo
  # stesso, e dirlo è più utile che fallire un backup intero per un servizio di un altro progetto.
  # Qui `--no-owner --no-privileges` **resta**, ed è una scelta diversa da quella del dominio (passo 1)
  # per una ragione concreta: Onyx ha un solo proprietario (`postgres`) e nessun modello di ruoli —
  # i suoi ACL non portano informazione di sicurezza, mentre nel dominio Trasi i GRANT **sono** le
  # policy RLS. Uniformare le due invocazioni costringerebbe a una scelta sola per due casi diversi.
  if docker exec "$ONYX_DB_CONTAINER" pg_dump -U postgres -Fc --no-owner --no-privileges "$ONYX_DB" \
       > "${BASE}.onyx.dump" 2>/tmp/trasi_backup_err; then
    echo "   → $(numfmt --to=iec "$(stat -c %s "${BASE}.onyx.dump")") · sha256 $(sha256sum "${BASE}.onyx.dump" | cut -c1-16)…"
    # I conteggi delle chat **nel backup**, non nel database: è il contratto di integrità del pezzo
    # che la retention cancella. Se il dump è troncato, i due numeri non tornano.
    chat_db=$(docker exec "$ONYX_DB_CONTAINER" psql -U postgres -X -q -tA -d "$ONYX_DB" \
                -c "SELECT count(*) FROM chat_session" 2>/dev/null | tr -d '[:space:]')
    echo "chat_session_nel_database = ${chat_db}" >> "$MANIFEST"
    echo "   → chat_session nel database: ${chat_db}"
  else
    echo "   → SALTATO: ${ONYX_DB_CONTAINER} non raggiungibile — $(tail -1 /tmp/trasi_backup_err 2>/dev/null)" >&2
    echo "onyx_dump = assente" >> "$MANIFEST"
  fi
fi

# --- 4. la configurazione -----------------------------------------------------------------------
# Cosa entra: i file che si sbagliano a ricostruire a mano (Caddyfile, compose, settings SearXNG),
# il codice dei flussi e delle dashboard, la Home. Cosa **non** entra: `deployment/.env` (segreti),
# `.venv`, `__pycache__`, `.pytest_cache`, `evidenze/` (immagini di prova: le rifà la misura).
echo
echo "── 4/5  configurazione → ${BASE}.config.tar.gz"
if tar --create --gzip --file "${BASE}.config.tar.gz" \
     --exclude='__pycache__' --exclude='.pytest_cache' --exclude='.venv' \
     --exclude='evidenze' --exclude='.secrets' --exclude='node_modules' \
     --exclude='deployment/.env' \
     deployment ops flussi db shim metabase docs 2>/tmp/trasi_backup_err; then
  echo "   → $(numfmt --to=iec "$(stat -c %s "${BASE}.config.tar.gz")")"
else
  echo "   → FALLITO: $(tail -2 /tmp/trasi_backup_err 2>/dev/null)" >&2
  rc=1
fi

# --- 5. l'App-DB di Metabase --------------------------------------------------------------------
# H2 su volume nominato: nessun dump lo copre. Il volume va letto **con il container fermo** per una
# copia coerente; fermare Metabase a ogni backup però costa (è al 93% del limite e il riavvio è
# lento). Scelta: si copia **a caldo** e si dichiara il limite — H2 in modalità embedded scrive su
# file, quindi la copia è coerente *per il file*, non per l'insieme. Metabase tiene la sua
# consistenza con il proprio lock, e un `tar` a caldo può contenere uno stato intermedio.
# È un compromesso dichiarato, non un difetto nascosto: per un backup coerente si esegue
# `ops/backup.sh` con Metabase fermo (`docker compose stop metabase`), ed è scritto nel runbook.
echo
echo "── 5/5  App-DB di Metabase → ${BASE}.metabase.tgz"
MB_VOLUME="${TRASI_MB_VOLUME:-trasi_metabase_data}"
if docker volume inspect "$MB_VOLUME" >/dev/null 2>&1; then
  # Si usa un container usa-e-getta che monta il volume **in sola lettura**: non serve il demone
  # Metabase, non serve fermarlo, e non si scrive nel volume dal lato sbagliato.
  if docker run --rm -v "${MB_VOLUME}:/src:ro" -v "${BACKUP_DIR}:/dst" alpine:3 \
       tar --create --gzip --file "/dst/$(basename "${BASE}").metabase.tgz" -C /src . \
       >/dev/null 2>/tmp/trasi_backup_err; then
    echo "   → $(numfmt --to=iec "$(stat -c %s "${BASE}.metabase.tgz")")"
    echo "metabase_volume = ${MB_VOLUME} (copia a caldo — v. commento in ops/backup.sh)" >> "$MANIFEST"
  else
    echo "   → FALLITO: $(tail -2 /tmp/trasi_backup_err 2>/dev/null)" >&2
    rc=1
  fi
else
  echo "   → SALTATO: volume ${MB_VOLUME} assente (Metabase mai avviato su questo host)"
  echo "metabase_volume = assente" >> "$MANIFEST"
fi

# --- impronte e chiusura ------------------------------------------------------------------------
# `sha256sum` di tutto ciò che è stato scritto: è il pezzo che permette a chiunque, senza fidarsi di
# questo script, di verificare che il file sul disco sia quello che è stato creato.
echo >> "$MANIFEST"
echo "# impronte (verifica: cd <dir> && sha256sum -c trasi_*.manifest)" >> "$MANIFEST"
for f in "${BASE}.dominio.dump" "${BASE}.globals.sql.gz" "${BASE}.onyx.dump" \
         "${BASE}.config.tar.gz" "${BASE}.metabase.tgz"; do
  [[ -f "$f" ]] && sha256sum "$f" >> "$MANIFEST"
done

echo
if [[ "$rc" -eq 0 ]]; then
  echo "backup.sh: completato — ${MANIFEST}"
  echo "  verifica rapida:  cd ${BACKUP_DIR} && sha256sum -c $(basename "$MANIFEST")"
  echo "  prova di restore: ops/restore_test.sh ${BASE}.dominio.dump"
else
  echo "backup.sh: completato CON ERRORI — il manifest dice cosa manca: ${MANIFEST}" >&2
fi

# --- rotazione ----------------------------------------------------------------------------------
# Politica: si conservano gli ultimi ${KEEP} backup **completi** (per data), si eliminano i più
# vecchi. Non si tocca l'ultimo backup in assoluto anche se supera il limite, e non si tocca un
# backup la cui `data` non è leggibile: una rotazione che cancella per un errore di parsing è una
# rotazione che cancella il backup buono.
echo
echo "── rotazione (mantengo ${KEEP})"
# `-maxdepth 1 -name 'trasi_*' -type f`: solo i file di questo schema, niente sottodirectory.
# L'ordinamento è **per nome**, che è cronologico perché il nome inizia con la data: nessuna
# dipendenza dai timestamp del filesystem, che si aggiornano con un `cp`.
mappe=$(ls -1 "${BACKUP_DIR}"/trasi_*.manifest 2>/dev/null | sort | sed 's/\.manifest$//')
tot=$(printf '%s\n' "$mappe" | grep -c . || true)
if [[ "${tot:-0}" -gt "$KEEP" ]]; then
  da_togliere=$(printf '%s\n' "$mappe" | head -n $((tot - KEEP)))
  n_tolti=0
  while IFS= read -r base; do
    [[ -z "$base" ]] && continue
    echo "   rimuovo $(basename "$base").*"
    rm -f "${base}".dominio.dump "${base}".globals.sql.gz "${base}".onyx.dump \
          "${base}".config.tar.gz "${base}".metabase.tgz "${base}".manifest
    n_tolti=$((n_tolti + 1))
  done <<< "$da_togliere"
  echo "   → rimossi ${n_tolti}; restano ${KEEP} backup completi"
else
  echo "   → ${tot} backup presenti, nessuno da rimuovere"
fi

exit "$rc"
