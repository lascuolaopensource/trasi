#!/usr/bin/env bash
# Trasi — B5 · provisioning di Metabase: amministratore, connessione «Trasi», ruolo di sola lettura.
#
# Idempotente: rieseguibile. Ciò che non è idempotente per natura (la creazione dell'utente admin da
# parte del wizard di Metabase) viene saltato se l'istanza è già configurata.
#
# Perché uno script e non dei clic: la connessione a un database, il ruolo con cui si connette e il
# possesso delle credenziali sono configurazione. Una configurazione che esiste solo dentro il
# database di un'applicazione non è riproducibile, e dopo un ripristino non si sa più com'era.
#
#   ./metabase/provisiona.sh
#
# Credenziali: generate qui la prima volta in `metabase/.secrets/creds.env` (mode 600, MAI versionato,
# MAI stampato). Lo script non le ripete mai in output.
set -euo pipefail

cd "$(dirname "$0")/.."

MB_URL="${MB_URL:-http://127.0.0.1:3001}"
SEGRETI="metabase/.secrets/creds.env"
PSQL=(docker compose -f deployment/docker-compose.yml exec -T db_trasi
      psql -U postgres -d trasi_db -X -q -v ON_ERROR_STOP=1 -f -)

# --- 1. Segreti (solo se mancano: rigenerarli scollegherebbe l'istanza già configurata) -----------
if [[ ! -f "$SEGRETI" ]]; then
  mkdir -p metabase/.secrets
  # `openssl rand -base64`: niente `python3 -c` con i segreti sulla riga di comando, che finirebbe
  # in `ps` e nella history.
  {
    echo "# Trasi B5 — credenziali Metabase (SEGRETI). Mode 600, MAI versionato, MAI stampato."
    echo "# Creato da metabase/provisiona.sh"
    echo "MB_ADMIN_EMAIL=admin@trasi.local"
    echo "MB_ADMIN_PASSWORD=$(openssl rand -base64 32 | tr -d '/+=' | head -c 28)"
    echo "MB_ADMIN_FIRST_NAME=Gestore"
    echo "MB_ADMIN_LAST_NAME=Rete"
    echo "MB_RO_PASSWORD=$(openssl rand -base64 32 | tr -d '/+=' | head -c 28)"
  } > "$SEGRETI"
  chmod 600 "$SEGRETI"
  echo "  creato $SEGRETI (mode 600)"
else
  echo "  $SEGRETI esiste già — non lo rigenero"
fi

set -a; . "$SEGRETI"; set +a

# --- 2. Attesa che Metabase risponda -------------------------------------------------------------
echo "  attendo Metabase su $MB_URL ..."
for _ in $(seq 1 60); do
  if curl -fsS -m 3 "$MB_URL/api/health" >/dev/null 2>&1; then break; fi
  sleep 2
done
curl -fsS -m 3 "$MB_URL/api/health" >/dev/null || {
  echo "provisiona.sh: Metabase non risponde su $MB_URL" >&2; exit 1; }

# --- 3. Admin (setup guidato dall'API) o login ---------------------------------------------------
# Il token di setup si legge dalle proprietà di sessione: è il modo con cui il wizard pubblica il
# proprio stato prima che esista un utente.
TOKEN=$(curl -fsS "$MB_URL/api/session/properties" |
        python3 -c 'import json,sys; print(json.load(sys.stdin).get("setup-token") or "")')
if [[ -n "$TOKEN" ]]; then
  # `--data-binary @-` con l'heredoc: la password arriva su stdin, non come argomento.
  python3 - "$MB_URL" "$TOKEN" <<'PY'
import json, sys, urllib.request, os
url, token = sys.argv[1], sys.argv[2]
body = json.dumps({
    "token": token,
    "user": {"email": os.environ["MB_ADMIN_EMAIL"], "password": os.environ["MB_ADMIN_PASSWORD"],
             "first_name": os.environ["MB_ADMIN_FIRST_NAME"], "last_name": os.environ["MB_ADMIN_LAST_NAME"]},
    "prefs": {"site_name": "Trasi — Osservatorio", "site_locale": "it"},
}).encode()
req = urllib.request.Request(url + "/api/setup", data=body,
                            headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=60) as r:
    print(f"  setup: HTTP {r.status}")
PY
else
  echo "  istanza già configurata — salto il setup"
fi

# --- 4. Password del ruolo di sola lettura -------------------------------------------------------
# La matrice di B1 dice testualmente: «gli altri ruoli LOGIN ricevono la password al provisioning di
# NocoDB/Metabase». È questo il posto. `\set` + `:'pw'`: psql quota il valore, quindi la password non
# entra in una stringa SQL costruita a mano.
printf "\\set pw '%s'\nALTER ROLE metabase_ro WITH LOGIN PASSWORD :'pw';\n" "$MB_RO_PASSWORD" |
  "${PSQL[@]}" >/dev/null
echo "  metabase_ro: password impostata (non stampata)"

# --- 5. Connessione «Trasi» + sincronizzazione ---------------------------------------------------
python3 - "$MB_URL" <<'PY'
import json, os, sys, urllib.request

url = sys.argv[1]

def call(path, body=None, method=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url + path, data=data, method=method,
                                 headers={"Content-Type": "application/json",
                                          "X-Metabase-Session": SESSION})
    with urllib.request.urlopen(req, timeout=120) as r:
        testo = r.read()
        return json.loads(testo) if testo else {}

# Sessione (la password viaggia nel corpo della richiesta, non nella URL).
body = json.dumps({"username": os.environ["MB_ADMIN_EMAIL"],
                   "password": os.environ["MB_ADMIN_PASSWORD"]}).encode()
with urllib.request.urlopen(urllib.request.Request(
        url + "/api/session", data=body,
        headers={"Content-Type": "application/json"}), timeout=30) as r:
    SESSION = json.load(r)["id"]

conn = {
    "engine": "postgres", "name": "Trasi",
    "details": {"host": "db_trasi", "port": 5432, "dbname": "trasi_db",
                "user": "metabase_ro", "password": os.environ["MB_RO_PASSWORD"],
                "ssl": False, "schema-filters-type": "inclusion",
                "schema-filters-patterns": "trasi"},
    "is_full_sync": True, "is_on_demand": False, "auto_run_queries": True, "cache_ttl": None,
}
esistenti = {d["name"]: d for d in call("/api/database")["data"]}
if "Trasi" in esistenti:
    call(f"/api/database/{esistenti['Trasi']['id']}", conn, "PUT")
    print("  connessione «Trasi» aggiornata")
else:
    creata = call("/api/database", conn, "POST")
    print(f"  connessione «Trasi» creata (id {creata['id']})")

# La connessione di esempio di Metabase non serve e non deve restare: il cruscotto legge il dominio.
for nome, d in esistenti.items():
    if nome != "Trasi":
        call(f"/api/database/{d['id']}", None, "DELETE")
        print(f"  rimossa la connessione di esempio «{nome}»")
PY

echo "provisiona.sh: fatto. Le credenziali sono in $SEGRETI (non stampate)."
