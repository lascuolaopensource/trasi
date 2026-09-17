#!/usr/bin/env bash
# Trasi — db/tests/run.sh
# Esegue la batteria dei test del blocco B1 e ritorna 0 solo se OGNI caso è PASS.
#
#   ./db/tests/run.sh              tutta la batteria
#   ./db/tests/run.sh t_rls        solo i file che iniziano per «t_rls»
#
# Come funziona (e perché così):
#   * ogni file gira in UNA transazione che finisce sempre in ROLLBACK: le fixture dei test non
#     lasciano una riga nel DB (una batteria che sporca il seed falsa la batteria successiva —
#     successo davvero, e il test l'ha rilevato: vedi il report B1);
#   * ON_ERROR_STOP=1: una RAISE EXCEPTION interrompe il file → exit ≠ 0 → FAIL;
#   * convenzione dei test: PASS = NOTICE, FAIL = EXCEPTION;
#   * i test girano come ruolo applicativo (SET ROLE dentro i test), mai come superuser;
#   * i file di un altro worker (test_zero_scritture.sql) vengono eseguiti se presenti: la batteria
#     è una sola anche quando i blocchi arrivano in ordine diverso.
set -uo pipefail

cd "$(dirname "$0")/../.."

COMPOSE_FILE="deployment/docker-compose.yml"
SERVICE="db_trasi"
DB="${TRASI_DB:-trasi_db}"
ADMIN="${POSTGRES_USER:-postgres}"
if [[ -f deployment/.env ]]; then
  set -a; . deployment/.env; set +a
  DB="${TRASI_DB:-trasi_db}"; ADMIN="${POSTGRES_USER:-postgres}"
fi

FILTERS=("$@")
selected() { [[ ${#FILTERS[@]} -eq 0 ]] && return 0; local f; for f in "${FILTERS[@]}"; do [[ "$(basename "$1")" == *"$f"* ]] && return 0; done; return 1; }

# --- precondizioni -----------------------------------------------------------------
if ! docker compose -f "$COMPOSE_FILE" ps --format '{{.Service}} {{.State}}' 2>/dev/null | grep -q "^${SERVICE} running"; then
  echo "run.sh: il servizio ${SERVICE} non è in esecuzione" >&2; exit 1
fi

psql_t() { docker compose -f "$COMPOSE_FILE" exec -T "$SERVICE" psql -U "$ADMIN" -d "$DB" -X -q "$@"; }

if [[ "$(psql_t -tAc "SELECT to_regclass('trasi.casa') IS NOT NULL")" != "t" ]]; then
  echo "run.sh: schema trasi assente — eseguire prima db/apply.sh" >&2; exit 1
fi

FILES=()
for f in db/tests/t_seed.sql db/tests/t_rls.sql db/tests/t_viste.sql db/tests/t_messaggi.sql db/tests/t_report.sql db/tests/test_zero_scritture.sql db/tests/t_cross_casa.sql db/tests/fixture_report.sql; do
  [[ -f "$f" ]] && selected "$f" && FILES+=("$f")
done
if [[ ${#FILES[@]} -eq 0 ]]; then echo "run.sh: nessun file di test selezionato" >&2; exit 1; fi

# --- esecuzione --------------------------------------------------------------------
echo "Trasi · batteria test B1 — db=${DB} (ruoli applicativi, mai superuser)"
tot_pass=0; tot_fail=0; rossi=(); rc=0

for f in "${FILES[@]}"; do
  # Alcuni file (test_zero_scritture.sql) gestiscono da soli la transazione: aprirne una seconda
  # produrrebbe solo «there is already a transaction in progress» e un ROLLBACK a vuoto. Si rileva
  # il controllo di transazione all'inizio di riga e in quel caso il file gira così com'è.
  if grep -qE '^[[:space:]]*(BEGIN|START TRANSACTION)[[:space:]]*;' "$f"; then
    runner() { cat "$f"; }
    modo="auto-transazione"
  else
    runner() { echo "BEGIN;"; cat "$f"; echo "ROLLBACK;"; }
    modo="BEGIN/ROLLBACK"
  fi

  out=$( runner | docker compose -f "$COMPOSE_FILE" exec -T "$SERVICE" \
             psql -U "$ADMIN" -d "$DB" -X -q -v ON_ERROR_STOP=1 -f - 2>&1 )
  st=$?
  p=$(grep -c 'PASS ' <<<"$out"); fl=$(grep -c 'FAIL ' <<<"$out")
  tot_pass=$((tot_pass + p)); tot_fail=$((tot_fail + fl))

  if [[ $st -eq 0 && $fl -eq 0 ]]; then
    printf '%-42s %2d PASS  exit 0  (%s)\n' "$(basename "$f")" "$p" "$modo"
    grep 'PASS ' <<<"$out" | sed 's/^/    /'
  else
    printf '%-42s %2d PASS  %d FAIL  exit %d  (%s)\n' "$(basename "$f")" "$p" "$fl" "$st" "$modo"
    grep -E 'PASS |FAIL |ERROR' <<<"$out" | sed 's/^/    /'
    rossi+=("$f"); rc=1
  fi
done

echo "----------------------------------------------------------------"
if [[ $rc -eq 0 ]]; then
  echo "ESITO: VERDE — ${tot_pass} casi PASS, 0 FAIL, ${#FILES[@]} file"
else
  echo "ESITO: ROSSO — ${tot_pass} PASS, ${tot_fail} FAIL; file rossi: ${rossi[*]}"
fi
exit $rc
