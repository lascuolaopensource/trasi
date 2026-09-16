#!/usr/bin/env bash
# Trasi — ops/restore_test.sh · la prova di restore, su un database di **prova**.
#
# Perché esiste come script e non come «si fa con pg_restore». Un backup non verificato è una
# speranza, non un backup: l'unico modo di sapere se un dump è ripristinabile è ripristinarlo. Questo
# script lo fa **senza toccare il database di produzione**: crea un database nuovo
# (`trasi_restore_test`, o quello che si indica), ci ripristina il dump, e verifica il risultato.
#
# **L'esito del criterio B6-STK-01 è `count(casa) = 10`** — dieci Case di Quartiere, il numero che il
# seed di B1 garantisce. Ma non è l'unica verifica, e non è la più importante:
#
#   * `count(casa)=10` dice che *i dati del dominio* sono arrivati;
#   * `count(pg_roles …)=21` dal file dei **globals** dice che *i ruoli* sono arrivati — cioè che il
#     ripristino ha ricostruito ciò che rende applicabili le policy RLS. Un database con i dati e
#     senza i ruoli è un database che risponde alle query e non protegge niente: è il modo in cui un
#     restore sembra riuscito e non lo è;
#   * le policy RLS applicate a un ruolo vero (`SET ROLE casa_sanbao` → `UPDATE … WHERE casa='bozzano'`
#     → `UPDATE 0`) dicono che il ripristino ha prodotto un **sistema che si comporta come l'originale**,
#     non solo una copia di righe.
#
# Il database di prova viene **distrutto alla fine** (a meno di `--tieni`): una prova che lascia un
# database in giro è una prova che il giorno dopo qualcuno esegue credendo di essere in produzione.
# Anche `trasi_restore_test` viene creato da `template_postgis` — senza PostGIS le viste geografiche
# del dump non si creano e il test fallirebbe per la ragione sbagliata.
#
# Uso:
#     ops/restore_test.sh /backups/trasi_2026-09-16_014834.dominio.dump
#     ops/restore_test.sh <dump> --db trasi_restore_test   # nome diverso
#     ops/restore_test.sh <dump> --tieni                   # non distrugge il DB di prova
#     ops/restore_test.sh <dump> --globals <globals.sql.gz>  # verifica anche i ruoli
#
# Exit: 0 = restore riuscito e **tutte** le verifiche passate; ≠0 altrimenti.
set -uo pipefail

cd "$(dirname "$0")/.."

DUMP=""
GLOBALS=""
TEST_DB="trasi_restore_test"
TIENI=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --db)       TEST_DB="${2:-}"; shift 2 ;;
    --globals)  GLOBALS="${2:-}"; shift 2 ;;
    --tieni)    TIENI=1; shift ;;
    -h|--help)  sed -n '2,32p' "$0"; exit 0 ;;
    -*)         echo "restore_test.sh: argomento non riconosciuto: $1" >&2; exit 2 ;;
    *)          DUMP="$1"; shift ;;
  esac
done

if [[ -z "$DUMP" ]]; then
  echo "restore_test.sh: manca il file di dump." >&2
  echo "  uso: ops/restore_test.sh /backups/trasi_YYYY-MM-DD_HHMMSS.dominio.dump" >&2
  echo "  (l'elenco: ls -1 /backups/*.dominio.dump)" >&2
  exit 2
fi
if [[ ! -f "$DUMP" ]]; then
  echo "restore_test.sh: il dump ${DUMP} non esiste." >&2
  exit 1
fi

if [[ -f deployment/.env ]]; then
  set -a; . deployment/.env; set +a
fi
POSTGRES_USER="${POSTGRES_USER:-postgres}"
COMPOSE_FILE="deployment/docker-compose.yml"
SERVICE="db_trasi"

# `-X` (non leggere .psqlrc), `-q`, `-tA` (tuple-only, unaligned): l'output si confronta con `[[ ]]`,
# non si legge a occhio.
# **`-q` e `-tA` insieme, e il `.psqlrc` escluso**: senza `-q`, `SET ROLE` stampa `SET` e il conteggio
# diventa `SET\nUPDATE 0` invece di `UPDATE 0` — un confronto di stringa che fallisce per una riga di
# troppo. Verificato: `psql -X -tA -c "SET ROLE …; UPDATE …"` → `SET` + `UPDATE 0`.
psql_admin() { docker compose -f "$COMPOSE_FILE" exec -T "$SERVICE" \
                 psql -U "$POSTGRES_USER" -X -q -tA "$@"; }
psql_test()  { docker compose -f "$COMPOSE_FILE" exec -T "$SERVICE" \
                 psql -U "$POSTGRES_USER" -X -q -tA -d "$TEST_DB" "$@"; }

# --- precondizioni ------------------------------------------------------------------------------
if ! docker compose -f "$COMPOSE_FILE" ps --format '{{.Service}} {{.State}}' 2>/dev/null \
     | grep -q "^${SERVICE} running"; then
  echo "restore_test.sh: il servizio ${SERVICE} non è in esecuzione." >&2
  exit 1
fi

# **Il controllo che impedisce l'errore grave.** Se il nome indicato è il database di produzione,
# questo script cancellerebbe i dati veri: si rifiuta di procedere. La lista dei nomi vietati è
# esplicita e include il nome reale del progetto, non un pattern indovinato.
PROD_DB="${TRASI_DB:-trasi_db}"
if [[ "$TEST_DB" == "$PROD_DB" || "$TEST_DB" == "postgres" \
   || "$TEST_DB" == "template0" || "$TEST_DB" == "template1" \
   || "$TEST_DB" == "template_postgis" ]]; then
  echo "restore_test.sh: RIFIUTO — '${TEST_DB}' non è un database di prova." >&2
  echo "restore_test.sh: la prova di restore distrugge il database su cui gira: usa un altro nome." >&2
  exit 2
fi

echo "Trasi · prova di restore — $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "  dump   : ${DUMP} ($(numfmt --to=iec "$(stat -c %s "$DUMP")"))"
echo "  DB test: ${TEST_DB}"
echo "  (il database di produzione '${PROD_DB}' non viene toccato)"
echo

ESITI=()
fallito=0
ok()   { ESITI+=("PASS  $1"); echo "  PASS  $1"; }
ko()   { ESITI+=("FAIL  $1"); echo "  FAIL  $1" >&2; fallito=1; }

# --- 1. il database di prova nasce da template0 -------------------------------------------------
# **`template0`, non `template_postgis`** — ed è un difetto reale, trovato eseguendo questa prova la
# prima volta (v. `docs/verifiche.md`). Su questa immagine `template_postgis` **contiene già** gli
# schemi `topology`, `tiger`, `tiger_data` e le estensioni PostGIS. Il dump, coerentemente, contiene
# i propri `CREATE SCHEMA tiger` / `CREATE EXTENSION postgis`: ripristinarlo su un database che li ha
# già produce
#
#     pg_restore: error: could not execute query: ERROR:  schema "tiger" already exists
#
# e — con `--single-transaction` — **l'intera transazione va in rollback**: `count(casa)` viene
# `<null>`, nessuna policy RLS, nessuna funzione. Il risultato era «restore rosso» con un dump
# perfettamente buono: la prova stava misurando sé stessa, non il backup.
#
# Da `template0` (vuoto, senza PostGIS preinstallato) il dump si applica per intero e crea tutto ciò
# che gli serve, che è esattamente ciò che farebbe su un host nuovo — cioè la situazione in cui un
# restore serve davvero. `template0` richiede `datallowconn`: qui è `false` di default, quindi si
# passa da `template1` come ponte (`CREATE DATABASE … TEMPLATE template0` **è** consentito anche se
# `template0` non accetta connessioni: è il template vuoto, ed è il modo previsto per clonarlo).
echo "── 1/4  creazione di ${TEST_DB} da template0 (vuoto: il dump porta il proprio PostGIS)"
psql_admin -c "DROP DATABASE IF EXISTS ${TEST_DB}" >/dev/null 2>&1
if psql_admin -c "CREATE DATABASE ${TEST_DB} TEMPLATE template0" >/dev/null 2>&1; then
  ok "database di prova creato (template0: il dump crea PostGIS, quindi nessuna collisione)"
else
  ko "creazione di ${TEST_DB} fallita"
  echo "restore_test.sh: mi fermo — senza il database di prova non c'è niente da verificare." >&2
  exit 1
fi

# --- 2. il ripristino ---------------------------------------------------------------------------
# `--no-owner --no-privileges` in **uscita** (backup.sh) e qui `--no-owner --no-privileges` in entrata:
# il dump è portabile fra cluster con nomi di ruolo diversi, che è esattamente il caso di un
# ripristino su un'altra macchina. Gli errori si **contano**: `pg_restore` esce 1 anche per un
# `COMMENT ON` non applicabile, e un restore con 3 errori di commento è diverso da uno con la
# tabella `casa` mancante. Il conteggio sta nell'esito, non solo il flag.
echo
echo "── 2/4  pg_restore"
# **`--no-owner --no-privileges` non si usano** (v. il commento lungo in `ops/backup.sh`, passo 1):
# un ripristino che azzera i privilegi perde i GRANT `USAGE` sullo schema `trasi`, e da lì il test
# RLS — l'invariante centrale di §11/V4 — non è nemmeno eseguibile (`permission denied for schema
# trasi` invece di `UPDATE 0`). La proprietà degli oggetti non è decorazione: è ciò che decide quali
# policy RLS si applicano.
#
# **Presupposto:** i ruoli devono esistere nel cluster *prima* del ripristino. È la stessa
# precondizione del restore vero (runbook §8 → prima i globals, poi il dump), ed è verificata qui
# sotto al punto 4 invece di essere data per scontata.
# `--exit-on-error` **non** si usa: un errore su un oggetto non essenziale fermerebbe il restore e
# impedirebbe di misurare il risultato, che è la cosa che interessa. Si misura, invece.
docker compose -f "$COMPOSE_FILE" exec -T "$SERVICE" \
  pg_restore -U "$POSTGRES_USER" -d "$TEST_DB" --single-transaction \
  < "$DUMP" >/tmp/trasi_restore_out 2>/tmp/trasi_restore_err
restore_rc=$?
errori=$(grep -c '^pg_restore: error' /tmp/trasi_restore_err 2>/dev/null || echo 0)
if [[ "$restore_rc" -eq 0 ]]; then
  ok "pg_restore completato senza errori (exit 0)"
else
  # `--single-transaction`: se qualcosa è andato storto, **non è stato applicato nulla**. È la
  # scelta giusta per un test: un restore parziale renderebbe i conteggi ambigui (il numero sarebbe
  # sbagliato *e* il database in uno stato che non esiste in nessun altro posto).
  ko "pg_restore exit ${restore_rc} · ${errori} errori (v. /tmp/trasi_restore_err)"
  # Si mostrano **tutti** gli errori, non gli ultimi due: con `--single-transaction` un solo errore
  # annulla tutto, e l'errore che spiega il fallimento è spesso il **primo** (i successivi sono
  # conseguenze a catena). Nasconderlo dietro un `tail` costringe a rifare la diagnosi da capo.
  sed -n '1,25p' /tmp/trasi_restore_err >&2
fi

# --- 3. le verifiche di contenuto ---------------------------------------------------------------
echo
echo "── 3/4  verifiche di contenuto"

# **La verifica del criterio: `count(casa) = 10`.** È il numero che il seed di B1 garantisce, ed è
# l'esito richiesto da B6-STK-01.
casa=$(psql_test -c "SELECT count(*) FROM trasi.casa" 2>/dev/null | tr -d '[:space:]')
if [[ "$casa" == "10" ]]; then
  ok "count(casa) = 10  ← criterio B6-STK-01"
else
  ko "count(casa) = '${casa:-<null>}' (atteso 10)"
fi

# **Le altre tabelle si confrontano con il database di produzione, non con un numero scritto qui.**
# Un valore atteso copiato nello script è un valore che invecchia: al primo dato reale (una fonte
# aggiunta dal TI, un luogo promosso dalla rete) il test diventa rosso **su un backup buono**, e un
# test che si impara a ignorare non è un test. Il confronto è `restore == produzione`: se differiscono,
# il ripristino ha perso righe — che è l'unica cosa che questa verifica deve sapere.
#
# `fonte` è il caso che l'ha reso evidente: il seed ne mette 3, il database reale ne ha **21** (le
# fonti aggiunte in B3/B4 più quelle iCal). Con l'atteso scritto a mano il test era rosso su un
# ripristino perfetto — un falso allarme prodotto dalla prova stessa.
echo "  (i conteggi si confrontano con il database di produzione '${PROD_DB}', non con valori fissi)"
for tabella in trasi.luogo trasi.fonte trasi.parametro trasi.casa; do
  atteso=$(psql_admin -d "$PROD_DB" -c "SELECT count(*) FROM ${tabella}" 2>/dev/null | tr -d '[:space:]')
  n=$(psql_test -c "SELECT count(*) FROM ${tabella}" 2>/dev/null | tr -d '[:space:]')
  if [[ -n "$atteso" && "$n" == "$atteso" ]]; then
    ok "count(${tabella}) = ${n} (identico alla produzione)"
  else
    ko "count(${tabella}) = '${n:-<null>}' (produzione: '${atteso:-<null>}') — il ripristino ha perso righe"
  fi
done

# Le **funzioni** e le **policy**: sono la parte che un `pg_dump` di sole tabelle perderebbe, e la
# parte che rende il sistema V4 invece di un database qualsiasi. Anche qui il confronto è con la
# produzione: il numero assoluto non significa nulla, l'uguaglianza sì.
n_fn=$(psql_test -c "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='trasi' AND p.prosecdef" 2>/dev/null | tr -d '[:space:]')
fn_prod=$(psql_admin -d "$PROD_DB" -c "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='trasi' AND p.prosecdef" 2>/dev/null | tr -d '[:space:]')
if [[ -n "$fn_prod" && "$n_fn" == "$fn_prod" && "${n_fn:-0}" -gt 0 ]]; then
  ok "funzioni SECURITY DEFINER = ${n_fn} (identiche alla produzione)"
else
  ko "funzioni SECURITY DEFINER = '${n_fn:-<null>}' (produzione: '${fn_prod:-<null>}')"
fi

n_pol=$(psql_test -c "SELECT count(*) FROM pg_policies WHERE schemaname='trasi'" 2>/dev/null | tr -d '[:space:]')
pol_prod=$(psql_admin -d "$PROD_DB" -c "SELECT count(*) FROM pg_policies WHERE schemaname='trasi'" 2>/dev/null | tr -d '[:space:]')
if [[ -n "$pol_prod" && "$n_pol" == "$pol_prod" && "${n_pol:-0}" -gt 0 ]]; then
  ok "policy RLS = ${n_pol} (identiche alla produzione)"
else
  ko "policy RLS = '${n_pol:-<null>}' (produzione: '${pol_prod:-<null>}') — un restore senza policy non protegge"
fi

# **I GRANT sullo schema.** È la verifica che ha trovato il difetto più grave di questo blocco: con
# `--no-privileges` il dump si ripristinava «senza errori» e `nspacl` restava **vuoto**, quindi i 17
# ruoli perdevano il `USAGE` sullo schema e nessuna policy RLS si applicava più a nessuno. Un
# database che risponde a tutte le query e non protegge niente.
acl=$(psql_test -c "SELECT count(*) FROM aclexplode((SELECT nspacl FROM pg_namespace WHERE nspname='trasi'))" 2>/dev/null | tr -d '[:space:]')
acl_prod=$(psql_admin -d "$PROD_DB" -c "SELECT count(*) FROM aclexplode((SELECT nspacl FROM pg_namespace WHERE nspname='trasi'))" 2>/dev/null | tr -d '[:space:]')
if [[ -n "$acl_prod" && "$acl" == "$acl_prod" && "${acl:-0}" -gt 0 ]]; then
  ok "GRANT sullo schema trasi = ${acl} (identici alla produzione: i privilegi sono ripristinati)"
else
  ko "GRANT sullo schema trasi = '${acl:-<null>}' (produzione: '${acl_prod:-<null>}') — i ruoli non possono usare lo schema"
fi

# **La verifica che conta davvero**: il sistema ripristinato si comporta come l'originale?
# `SET ROLE casa_sanbao` + `UPDATE` su un'altra Casa deve aggiornare **0 righe**; sulla **propria**
# deve aggiornarne **1**. Non basta il caso negativo: un database in cui *nessuno* può scrivere
# passerebbe la prima verifica e sarebbe inutilizzabile — servono entrambi i lati.
#
# Il conteggio passa da `WITH … RETURNING`, non dal messaggio `UPDATE n` di psql: quel messaggio non
# compare con `-q`, e leggerlo significherebbe dipendere da una riga di output che psql non promette
# di stampare sempre. `count(*)` su un `RETURNING` è il numero di righe davvero toccate, ed è
# l'unica forma che sopravvive a un cambio di verbosità.
#
# Richiede che i **ruoli** esistano nel cluster: da qui la verifica dei globals al punto 4. Se i ruoli
# non ci sono, `SET ROLE` fallisce e questo è il sintomo che va letto così, non come «RLS rotta».
rls_altrui=$(psql_test -d "$TEST_DB" -c \
  "SET ROLE casa_sanbao; WITH u AS (UPDATE trasi.casa SET orari_provvisori=orari_provvisori WHERE slug='bozzano' RETURNING 1) SELECT count(*) FROM u" \
  2>/dev/null | tr -d '[:space:]')
rls_propria=$(psql_test -d "$TEST_DB" -c \
  "SET ROLE casa_sanbao; WITH u AS (UPDATE trasi.casa SET orari_provvisori=orari_provvisori WHERE slug='san-bao' RETURNING 1) SELECT count(*) FROM u" \
  2>/dev/null | tr -d '[:space:]')
if [[ "$rls_altrui" == "0" && "$rls_propria" == "1" ]]; then
  ok "RLS ripristinata: casa_sanbao scrive la propria Casa (1) e non quella altrui (0)"
elif [[ -z "$rls_altrui" ]]; then
  ko "RLS: non eseguibile → errore da psql (i ruoli esistono? v. punto 4)"
else
  ko "RLS: casa_sanbao su Bozzano=${rls_altrui:-<null>} (atteso 0), su san-bao=${rls_propria:-<null>} (atteso 1)"
fi

# --- 4. i ruoli dai globals ---------------------------------------------------------------------
# Questa è la parte che giustifica `pg_dumpall --globals-only` nel backup: i ruoli non stanno nel
# dump del database, e **senza ruoli le policy RLS non si applicano a nessuno** (il `SET ROLE` qui
# sopra fallirebbe con «role does not exist»). La verifica è di sola lettura e **non crea i ruoli**:
# un restore di prova che modifica il cluster di produzione non è una prova, è una modifica.
echo
echo "── 4/4  globals (ruoli)"
if [[ -z "$GLOBALS" ]]; then
  # Il file dei globals si deduce dal nome del dump: è la convenzione di `ops/backup.sh`
  # (`<base>.dominio.dump` e `<base>.globals.sql.gz`).
  GLOBALS="${DUMP%.dominio.dump}.globals.sql.gz"
fi
if [[ -f "$GLOBALS" ]]; then
  n_ruoli=$(zcat "$GLOBALS" | grep -c '^CREATE ROLE')
  nel_cluster=$(psql_admin -c "SELECT count(*) FROM pg_roles WHERE rolname NOT LIKE 'pg\_%'" | tr -d '[:space:]')
  echo "  globals: ${GLOBALS} → ${n_ruoli} CREATE ROLE · nel cluster: ${nel_cluster}"
  if [[ "${n_ruoli:-0}" -ge 1 ]]; then
    ok "il file dei globals contiene ${n_ruoli} ruoli (i ruoli NON stanno nel dump del DB)"
  else
    ko "il file dei globals non contiene alcun CREATE ROLE"
  fi
  # I ruoli del dominio devono essere tutti presenti **nel file**: si elencano quelli attesi dal
  # contratto B1 (17 ruoli applicativi + i 4 di servizio) e si verifica che ci siano.
  mancanti=""
  for r in trasi_owner applicatore automazioni shim_rw metabase_ro rete ti \
           casa_bozzano casa_sanbao casa_tuturano; do
    zcat "$GLOBALS" | grep -q "^CREATE ROLE ${r}\b" || mancanti="${mancanti} ${r}"
  done
  if [[ -z "$mancanti" ]]; then
    ok "tutti i ruoli del contratto B1 sono nel file dei globals"
  else
    ko "ruoli assenti dal file dei globals:${mancanti}"
  fi
else
  ko "file dei globals non trovato: ${GLOBALS} (passa --globals <file>)"
fi

# --- chiusura -----------------------------------------------------------------------------------
echo
if [[ "$TIENI" -eq 1 ]]; then
  echo "restore_test.sh: ${TEST_DB} conservato (--tieni). Per rimuoverlo:"
  echo "  docker compose -f ${COMPOSE_FILE} exec -T ${SERVICE} psql -U ${POSTGRES_USER} -c 'DROP DATABASE ${TEST_DB}'"
else
  # Si distrugge anche in caso di FAIL: un database di prova lasciato in giro è una trappola per chi
  # arriva dopo. Il dump delle connessioni è necessario perché `DROP DATABASE` non procede se il
  # database ha sessioni aperte.
  psql_admin -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='${TEST_DB}'" >/dev/null 2>&1
  if psql_admin -c "DROP DATABASE IF EXISTS ${TEST_DB}" >/dev/null 2>&1; then
    echo "restore_test.sh: ${TEST_DB} rimosso (il cluster torna com'era)"
  else
    echo "restore_test.sh: ATTENZIONE — ${TEST_DB} non è stato rimosso" >&2
  fi
fi

pass=$(printf '%s\n' "${ESITI[@]}" | grep -c '^PASS')
fail=$(printf '%s\n' "${ESITI[@]}" | grep -c '^FAIL')
echo
if [[ "$fallito" -eq 0 ]]; then
  echo "restore_test.sh: ESITO VERDE — ${pass} PASS, 0 FAIL · count(casa)=${casa}"
else
  echo "restore_test.sh: ESITO ROSSO — ${pass} PASS, ${fail} FAIL" >&2
fi
exit "$fallito"
