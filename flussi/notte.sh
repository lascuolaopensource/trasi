#!/usr/bin/env bash
# Trasi — flussi/notte.sh · la catena notturna completa, eseguibile a mano.
#
# Perché esiste, se c'è il crontab. Perché un flusso che si può far girare **solo** alle 5 del mattino
# è un flusso che nessuno prova e che nessuno ripara: questo wrapper esegue i quattro passi in ordine,
# con lo stesso esito che avrebbero da cron, e serve a chi deve verificare («è passata la notte?»),
# a chi deve diagnosticare («perché la chat non cita il dato nuovo?») e alla verifica manuale del
# criterio §10 B4.
#
# Differenza con il crontab, dichiarata: il crontab esegue i quattro passi **indipendenti** (un
# fallimento non ferma gli altri: l'export della KB non deve dipendere dall'alert). Questo wrapper
# propaga invece l'exit code — chi lo esegue a mano vuole sapere se *qualcosa* è andato storto.
#
# Uso:
#     flussi/notte.sh                  # tutti e quattro i passi
#     flussi/notte.sh --solo applica   # un solo passo
#     TRASI_TRIGGER=cron flussi/notte.sh   # dichiara il trigger nel registro
#     flussi/notte.sh --dry-run        # mostra cosa eseguirebbe
set -uo pipefail

cd "$(dirname "$0")/.."

# I quattro passi, nell'ordine dell'architettura §6. Il nome è quello che compare in `flusso_run`.
PASSI=(export_kb applica fonti_ical fonti_http alert)
DICHIARAZIONE=(
  "F3  export KB → KB di Onyx (upsert per doc_id, mai duplicati)"
  "F9  applica + scadi → il dominio, con riga di audit per variazione"
  "F4  iCal → upsert diretto su evento (unica eccezione a V4)"
  "F4  HTTP → change-detection: crea proposte, non scrive"
  "F6  alert → proposte in attesa e coerenza fonti, a chi decide"
)

SOLO=""
DRY_RUN=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --solo)    SOLO="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
    *) echo "notte.sh: argomento non riconosciuto: $1" >&2; exit 2 ;;
  esac
done

if [[ -n "$SOLO" ]]; then
  trovato=0
  for passo in "${PASSI[@]}"; do [[ "$passo" == "$SOLO" ]] && trovato=1; done
  if [[ $trovato -eq 0 ]]; then
    echo "notte.sh: passo sconosciuto: ${SOLO} (ammessi: ${PASSI[*]})" >&2
    exit 2
  fi
fi

# L'ordine è significativo: `applica` (05:00) precede `fonti` (06:00) precede `alert` (07:30), così
# l'avviso delle 07:30 contiene anche ciò che la notte ha trovato.
esegui_passo() {
  local passo="$1"
  case "$passo" in
    applica)    comando=(bash flussi/applica.sh) ;;
    export_kb)  comando=(python3 flussi/export_kb.py) ;;
    fonti_ical) comando=(python3 flussi/fonti_ical.py) ;;
    fonti_http) comando=(python3 flussi/fonti_http.py) ;;
    alert)      comando=(python3 flussi/alert.py) ;;
    *) echo "notte.sh: passo non implementato: $passo" >&2; return 2 ;;
  esac

  # `--dry-run` si propaga ai flussi che lo prevedono. `applica.sh` non lo ha: l'unica cosa che sa
  # fare è applicare, e un `--dry-run` che si limitasse a *non* eseguirlo sarebbe indistinguibile da
  # un passo saltato. Nel dry-run di `applica` si dichiara che non viene eseguito.
  if [[ $DRY_RUN -eq 1 ]]; then
    if [[ "$passo" == "applica" ]]; then
      echo "  (dry-run) NON eseguito: ${comando[*]} — applicherebbe le proposte approvate"
      return 0
    fi
    comando+=(--dry-run)
    echo "  (dry-run) ${comando[*]}"
    return 0
  fi
  "${comando[@]}"
}

echo "Trasi · catena notturna — $(date '+%Y-%m-%d %H:%M:%S %Z') · trigger=${TRASI_TRIGGER:-manuale}"
rc=0
eseguiti=0

for indice in "${!PASSI[@]}"; do
  passo="${PASSI[$indice]}"
  [[ -n "$SOLO" && "$passo" != "$SOLO" ]] && continue
  echo
  echo "── ${DICHIARAZIONE[$indice]}"
  if esegui_passo "$passo"; then
    echo "   → ${passo}: ok"
  else
    echo "   → ${passo}: FALLITO (exit $?)" >&2
    rc=1
  fi
  eseguiti=$((eseguiti + 1))
done

echo
if [[ $rc -eq 0 ]]; then
  echo "notte.sh: ${eseguiti} passi conclusi — «è passata la notte?» si verifica con:"
  echo "  psql -c \"SELECT nome, trigger, esito, n_righe, fine_ts FROM trasi.flusso_run ORDER BY id DESC LIMIT 10\""
else
  echo "notte.sh: almeno un passo è fallito; il registro dice quale:" >&2
  echo "  psql -c \"SELECT nome, esito, dettaglio FROM trasi.flusso_run WHERE esito <> 'ok' ORDER BY id DESC LIMIT 10\"" >&2
fi
exit "$rc"
