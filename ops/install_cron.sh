#!/usr/bin/env bash
# Trasi — ops/install_cron.sh · installa il crontab di esercizio, **con un controllo che ne vale la
# pena** (blocco B6).
#
# Un `crontab ops/crontab` a mano è una riga. Questo script esiste per la verifica che sta prima e
# quella che sta dopo, entrambe nate da un difetto **misurato** (non ipotizzato) sul file del worker
# `trasi-flussi`:
#
#     $ cat /tmp/log_cron
#     /bin/sh: 1: automazioni: not found
#
# Cinque job, tutti morti, `crontab -l` che mostra le righe, container `healthy`, nessun altro
# sintomo. La causa: il file era in formato `/etc/cron.d` (con il campo utente fra il giorno della
# settimana e il comando) installato come crontab **utente**, dove quel campo non esiste — quindi
# `cron` leggeva `automazioni` come programma da eseguire.
#
# La lezione non è «stare attenti»: è che **un crontab sbagliato non fallisce, tace**. Quindi qui:
#
#   * **prima**: ogni riga di job deve avere esattamente 5 campi di schedulazione e un comando che
#     inizia con `/`. Una riga con un sesto campo prima di un percorso assoluto è il campo utente di
#     troppo, ed è un errore fatale, non un avviso;
#   * **dopo**: ogni comando deve esistere ed essere eseguibile. Un percorso sbagliato è lo stesso
#     difetto in un'altra forma: il job parte e fallisce con «not found», in un log;
#   * **dopo**: si legge `crontab -l` e si **ricontano** le righe, perché quello che è installato è
#     ciò che conta, non ciò che si è scritto nel file;
#   * **prima di installare**: si salva il crontab precedente in un file con timestamp, così un
#     errore si annulla con un `crontab <file>` invece che a memoria.
#
# Uso:
#     ops/install_cron.sh --dry-run    # valida il file e mostra cosa installerebbe
#     ops/install_cron.sh              # salva il precedente, installa, verifica
#     ops/install_cron.sh --ripristina /var/backups/trasi/crontab.2026-09-16_020000
#
# Exit: 0 = installato e verificato; ≠0 = non installato (il crontab precedente resta intatto).
set -uo pipefail

cd "$(dirname "$0")/.."

CRONTAB_FILE="ops/crontab"
BACKUP_DIR="${TRASI_BACKUP_DIR:-/backups}/crontab"
DRY_RUN=0
RIPRISTINA=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)    DRY_RUN=1; shift ;;
    --file)       CRONTAB_FILE="${2:-}"; shift 2 ;;
    --ripristina) RIPRISTINA="${2:-}"; shift 2 ;;
    -h|--help)    sed -n '2,32p' "$0"; exit 0 ;;
    *) echo "install_cron.sh: argomento non riconosciuto: $1" >&2; exit 2 ;;
  esac
done

# --- il ripristino, perché è la via d'uscita e va provata come le altre ---------------------------
if [[ -n "$RIPRISTINA" ]]; then
  if [[ ! -f "$RIPRISTINA" ]]; then
    echo "install_cron.sh: il file da ripristinare non esiste: ${RIPRISTINA}" >&2
    exit 1
  fi
  echo "install_cron.sh: ripristino da ${RIPRISTINA}"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "  (dry-run) eseguirebbe: crontab ${RIPRISTINA}"
    exit 0
  fi
  crontab "$RIPRISTINA" && { echo "  → installato"; crontab -l; exit 0; }
  echo "install_cron.sh: ripristino fallito" >&2
  exit 1
fi

if [[ ! -f "$CRONTAB_FILE" ]]; then
  echo "install_cron.sh: crontab non trovato: ${CRONTAB_FILE}" >&2
  exit 1
fi

echo "Trasi · installazione del crontab — $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "  file: ${CRONTAB_FILE}"

# --- validazione 1: la forma di ogni riga di job -------------------------------------------------
# Si guardano le sole righe che iniziano con un carattere di schedulazione (cifra o `*`): le variabili
# (`SHELL=…`), i commenti e le righe vuote non sono job.
#
# **Il test decisivo**: con lo schema corretto (crontab utente) il **sesto** campo è l'inizio del
# comando, e deve iniziare con `/`. Se il sesto campo è una parola (un nome utente) e il settimo è il
# percorso, la riga ha il campo utente di troppo.
echo
echo "── validazione della forma"
malformate=0
while IFS= read -r riga; do
  [[ -z "${riga// /}" ]] && continue
  # **`read -ra`, non `campi=($riga)`.** Con un'assegnazione non quotata bash fa anche la
  # *pathname expansion*: i campi `*` dello schema cron si espandono nell'elenco dei file della
  # directory corrente, e `campi[5]` non è più il comando. Verificato: la prima versione di questo
  # script rifiutava **tre righe valide** con «il 6° campo non è un percorso assoluto», e il campo
  # mostrato era un percorso di file che non c'entrava nulla. `read -ra` divide senza glob.
  read -ra campi <<< "$riga"
  cmd="${campi[5]:-}"
  if [[ "${#campi[@]}" -lt 6 ]]; then
    echo "  FAIL  riga con meno di 6 campi: «${riga}»" >&2
    malformate=$((malformate + 1))
  elif [[ "$cmd" != /* ]]; then
    echo "  FAIL  il 6° campo non è un percorso assoluto: «${riga}»" >&2
    echo "        (se il 6° campo è un nome utente, la riga è in formato /etc/cron.d:" >&2
    echo "         in un crontab UTENTE il campo utente non esiste — v. testa di ${CRONTAB_FILE})" >&2
    malformate=$((malformate + 1))
  else
    echo "  PASS  $(printf '%-12s' "$(echo "$cmd" | xargs -n1 basename 2>/dev/null)") ← ${campi[0]} ${campi[1]} ${campi[2]} ${campi[3]} ${campi[4]}"
  fi
done < <(grep -E '^[0-9*]' "$CRONTAB_FILE")

if [[ "$malformate" -gt 0 ]]; then
  echo "install_cron.sh: ${malformate} righe malformate — NON installo." >&2
  echo "install_cron.sh: un crontab malformato non fallisce, tace: i job restano in elenco e muoiono." >&2
  exit 1
fi

# --- validazione 2: i comandi esistono ----------------------------------------------------------
# Un percorso sbagliato è lo stesso difetto in un'altra forma: il job parte e fallisce con «not
# found», in un log che nessuno legge. Il controllo è qui e non dopo l'installazione, perché dopo
# sarebbe un job già sbagliato.
echo
echo "── esistenza dei comandi"
mancanti=0
while IFS= read -r cmd; do
  if [[ -x "$cmd" ]]; then
    echo "  PASS  ${cmd}"
  else
    echo "  FAIL  ${cmd} — non esiste o non è eseguibile" >&2
    mancanti=$((mancanti + 1))
  fi
done < <(grep -E '^[0-9*]' "$CRONTAB_FILE" | awk '{print $6}' | sort -u)

if [[ "$mancanti" -gt 0 ]]; then
  echo "install_cron.sh: ${mancanti} comandi mancanti — NON installo." >&2
  exit 1
fi

# La directory dei log: cron **non** la crea, e un `>> /var/log/trasi/…` verso una directory
# inesistente fa fallire ogni job con «cannot create». È il terzo modo in cui un crontab tace.
if [[ ! -d /var/log/trasi ]]; then
  echo
  echo "── /var/log/trasi"
  if [[ "$DRY_RUN" -eq 1 ]]; then
    echo "  (dry-run) creerebbe /var/log/trasi (senza, ogni job fallisce su '>>')"
  else
    mkdir -p /var/log/trasi && echo "  creato /var/log/trasi"
  fi
fi

# --- installazione ------------------------------------------------------------------------------
if [[ "$DRY_RUN" -eq 1 ]]; then
  echo
  echo "  (dry-run) le $(grep -cE '^[0-9*]' "$CRONTAB_FILE") righe di schedulazione sono valide."
  echo "  (dry-run) eseguirebbe: crontab ${CRONTAB_FILE}"
  exit 0
fi

# Si salva il crontab **precedente** prima di toccarlo. Se `crontab -l` non ha niente (nessun
# crontab installato), non si salva niente: un file vuoto di backup farebbe credere che ci fosse
# qualcosa da ripristinare.
mkdir -p "$BACKUP_DIR"
precedente=$(crontab -l 2>/dev/null || true)
if [[ -n "$precedente" ]]; then
  f="${BACKUP_DIR}/crontab.$(date +%Y-%m-%d_%H%M%S)"
  printf '%s\n' "$precedente" > "$f"
  chmod 600 "$f"
  echo
  echo "  crontab precedente salvato: ${f} ($(printf '%s\n' "$precedente" | grep -cE '^[0-9*]') righe di job)"
fi

if crontab "$CRONTAB_FILE"; then
  echo "  → installato"
else
  echo "install_cron.sh: l'installazione è fallita; il crontab precedente è intatto." >&2
  exit 1
fi

# --- verifica: quello che è **installato**, non quello che si è scritto --------------------------
# `crontab -l` rilegge dal file che cron userà davvero. Contare le righe qui è l'unico controllo che
# il percorso file → cron sia andato a buon fine.
echo
echo "── verifica (crontab -l)"
installate=$(crontab -l 2>/dev/null | grep -cE '^[0-9*]')
attese=$(grep -cE '^[0-9*]' "$CRONTAB_FILE")
echo "  righe di schedulazione installate: ${installate} (attese: ${attese})"
if [[ "$installate" != "$attese" ]]; then
  echo "install_cron.sh: il conteggio non torna — verifica con 'crontab -l'" >&2
  exit 1
fi

echo
crontab -l
echo
echo "install_cron.sh: installato e verificato — $(date '+%Y-%m-%d %H:%M:%S')"
echo "  I job partiranno alle loro ore. Per eseguirne uno subito, a mano:"
echo "    ops/backup.sh · ops/retention_chat.sh · ops/ciclo_mensile.sh --forza"
