#!/bin/sh
# Trasi — entrypoint del container `automazioni`.
#
# Fa quattro cose e nessuna di più: mette le credenziali dove i job le trovano, installa il crontab,
# esegue una **prova offline** dei flussi, e passa il controllo a cron in primo piano (PID 1, così
# `docker stop` ferma davvero lo scheduler).
#
# **1. Le credenziali.** In `/run/trasi/env` (mode 600, proprietario `automazioni`), non nel crontab e
# non sulla riga di comando: un segreto in un crontab è un segreto in un file versionato, uno in
# `docker inspect` è un segreto che legge chiunque abbia accesso al demone. `job.sh` le carica da lì.
#
# **3. La prova offline, non una prova vera.** Il primo avvio verifica che i flussi *partano* e che il
# database risponda; **non** esegue i flussi di produzione. Due ragioni, entrambe misurate:
#
#   * un container che si riavvia a metà giornata non deve applicare le proposte di nessuno — quello è
#     il compito delle 05:00. `applica.sh` non si esegue mai qui;
#   * la prova non deve dipendere dalla rete. Prima versione di questo script: la prova chiamava
#     `fonti_http.py --dry-run`, che va su internet, e il container segnalava «errore» a ogni avvio
#     perché `https://www.comune.brindisi.it/urp` risponde **404** da qui. Un healthcheck che fallisce
#     per un sito esterno è un allarme che si impara a ignorare. La prova ora usa `--help` (i moduli
#     importano, gli argomenti si costruiscono) e un `SELECT` di lettura: dice se l'ambiente è sano,
#     non se una fonte esterna è raggiungibile — quello lo dice `fonte_run`, dove va letto.

set -eu

echo "automazioni: avvio $(date '+%Y-%m-%d %H:%M:%S %Z') · ruolo=${PGUSER:-automazioni} · host=${PGHOST:-db_trasi}"

# --- 1. Credenziali per i job --------------------------------------------------------------
# `umask 077` prima di creare la directory: il file non deve esistere leggibile nemmeno per un
# istante. Il contenuto è generato da `printf '%s'` e mai stampato nel log.
mkdir -p /run/trasi
umask 077
{
  printf 'export PGHOST=%s\n'     "${PGHOST:-db_trasi}"
  printf 'export PGPORT=%s\n'     "${PGPORT:-5432}"
  printf 'export PGUSER=%s\n'     "${PGUSER:-automazioni}"
  printf 'export PGDATABASE=%s\n' "${PGDATABASE:-trasi_db}"
  printf 'export PGPASSWORD=%s\n' "${PGPASSWORD:-}"
  printf 'export TRASI_DB_VIA=%s\n' "${TRASI_DB_VIA:-diretta}"
} > /run/trasi/env
# **Il proprietario deve essere `automazioni`, non root.** L'entrypoint gira come root (cron lo
# richiede) e creerebbe il file con il proprio uid: `chmod 600` lo renderebbe leggibile **solo da
# root**, e ogni job — che gira come `automazioni` — fallirebbe su «cannot open /run/trasi/env:
# Permission denied» *prima* di eseguire qualunque cosa. Verificato: è il secondo difetto di questo
# entrypoint, e il sintomo era un job che non faceva nulla senza dire perché.
chown automazioni:automazioni /run/trasi/env
chmod 600 /run/trasi/env
echo "automazioni: credenziali per i job in /run/trasi/env (mode 600, proprietario automazioni, valore non stampato)"

# --- 2. Il database risponde? ---------------------------------------------------------------
atteso=0
finche=0
while [ "$finche" -lt 30 ]; do
  if pg_isready -h "${PGHOST:-db_trasi}" -p "${PGPORT:-5432}" -U "${PGUSER:-automazioni}" -q; then
    atteso=1
    break
  fi
  finche=$((finche + 1))
  sleep 2
done

if [ "$atteso" -eq 0 ]; then
  echo "automazioni: il database non risponde su ${PGHOST:-db_trasi}:${PGPORT:-5432} dopo 60 s" >&2
  echo "automazioni: verifica PGHOST/PGUSER/PGPASSWORD e che db_trasi sia healthy" >&2
  exit 1
fi
echo "automazioni: database raggiungibile"

# --- 3. Autenticazione e registro -----------------------------------------------------------
# La connessione è come `automazioni` **via TCP**: è la stessa via dei job, quindi una password
# sbagliata o un ruolo senza LOGIN si vedono adesso invece che alle 05:00.
if identita="$(psql -X -q -tAc "SELECT session_user || ' / ' || current_user" 2>&1 | tail -1)"; then
  :
fi
case "$identita" in
  automazioni*) echo "automazioni: autenticazione OK ($identita)" ;;
  *)
    echo "automazioni: autenticazione FALLITA → ${identita}" >&2
    echo "automazioni: esegui flussi/provisiona.sh da host per impostare la password del ruolo" >&2
    exit 1
    ;;
esac

if psql -X -q -tAc "SELECT 1 FROM trasi.flusso_run LIMIT 0" >/dev/null 2>&1; then
  echo "automazioni: registro flusso_run accessibile"
else
  echo "automazioni: ATTENZIONE — trasi.flusso_run non è leggibile: applica db/020_flusso.sql" >&2
  exit 1
fi

# --- 4. Prova offline dei flussi ------------------------------------------------------------
# `--help` costruisce tutti gli argomenti e importa tutti i moduli: un `sys.path` sbagliato o una
# dipendenza mancante si vedono qui. Nessuna chiamata di rete, nessuna scrittura.
for flusso in export_kb.py fonti_ical.py fonti_http.py alert.py; do
  if python3 "/app/flussi/$flusso" --help >/dev/null 2>&1; then
    echo "automazioni: $flusso → importabile"
  else
    echo "automazioni: $flusso → ERRORE di import (vedi: python3 /app/flussi/$flusso --help)" >&2
    exit 1
  fi
done

if bash -n /app/flussi/applica.sh && bash -n /app/flussi/notte.sh; then
  echo "automazioni: applica.sh e notte.sh → sintassi ok"
else
  echo "automazioni: applica.sh/notte.sh → ERRORE di sintassi" >&2
  exit 1
fi

# --- 5. Il crontab --------------------------------------------------------------------------
# `TRASI_TRIGGER=cron` è nel crontab, non nell'ambiente: cron non eredita l'ambiente del container,
# e senza quella variabile ogni run si dichiarerebbe «manuale» in `flusso_run` — il registro non
# distinguerebbe più la notte da una diagnosi.
#
# Il crontab si installa come l'utente che lo esegue. Il container parte come **root** (vedi
# `deployment/automazioni/Dockerfile`: `USER` è assente di proposito) e scende a `automazioni` con
# `runuser` solo per installare il crontab e per i job; cron resta root perché gli serve `seteuid` per
# cambiare identità — senza, esce con «seteuid: Operation not permitted» e **nessuno dei job parte**,
# in silenzio. Verificato: con `USER automazioni` il container gira, cron muore subito, e l'unico
# sintomo è una riga in `docker logs`.
installato=$(runuser -u automazioni -- crontab /app/flussi/crontab 2>&1) || {
  echo "automazioni: installazione del crontab fallita: ${installato}" >&2
  exit 1
}
righe=$(runuser -u automazioni -- crontab -l 2>/dev/null | grep -c '^[0-9]' || true)
# **Il numero atteso si deriva dal file, non è una costante.** Un `-lt 5` scritto a mano descrive un
# file che cambia: se domani un flusso si aggiunge o si fonde con un altro, la costante o fallisce a
# torto o — peggio — continua a passare mentre una riga non è stata installata. Il conteggio giusto è
# «tante righe quante ne dichiara `flussi/crontab`», ed è quello che si verifica.
attese=$(grep -cE '^[0-9]' /app/flussi/crontab || true)
echo "automazioni: crontab installato come automazioni (${righe}/${attese} righe di schedulazione)"
if [ "${righe}" -lt "${attese}" ]; then
  echo "automazioni: installate ${righe} righe su ${attese} dichiarate in flussi/crontab" >&2
  exit 1
fi

# **Ogni comando deve iniziare con un percorso assoluto che esiste.** È il controllo che avrebbe
# intercettato il difetto più insidioso di questo blocco: un crontab nel formato `/etc/cron.d` (con il
# campo utente dopo il giorno della settimana) installato come crontab **utente** fa sì che cron legga
# `automazioni` come programma da eseguire. Le cinque righe restano in `crontab -l`, il container è
# `healthy`, e i job falliscono tutti con «/bin/sh: 1: automazioni: not found» in un log che nessuno
# legge. Verificato: `grep -c '^[0-9]'` conta 5 e non se ne accorge — per questo il controllo guarda il
# **primo campo del comando**, non il numero di righe.
malformate=$(runuser -u automazioni -- crontab -l 2>/dev/null | awk '
  /^[0-9*]/ {
    # Le variabili `NAME=valore` non sono righe di job; i job hanno 5 campi di schedulazione.
    cmd = $6
    if (cmd !~ /^\//) { print "riga «" $0 "» → comando «" cmd "» non assoluto" }
  }')
if [ -n "${malformate}" ]; then
  echo "automazioni: crontab con righe malformate (campo utente di troppo?):" >&2
  echo "${malformate}" >&2
  echo "automazioni: un crontab UTENTE non ha il campo utente fra il giorno e il comando" >&2
  exit 1
fi

# I comandi esistono davvero? Un percorso sbagliato è lo stesso difetto in un'altra forma: il job
# partirebbe e fallirebbe con «not found», in un log.
for script in /app/flussi/job.sh /app/flussi/applica.sh; do
  [ -x "${script}" ] || { echo "automazioni: ${script} manca o non è eseguibile" >&2; exit 1; }
done
echo "automazioni: crontab valido (comandi assoluti ed eseguibili)"

# --- 6. cron in primo piano -----------------------------------------------------------------
# `-f` = foreground (PID 1: `docker stop` ferma lo scheduler), `-l 2` = log informativi su stdout,
# così `docker logs` mostra le esecuzioni. Ogni job passa da `job.sh`, che carica le credenziali.
echo "automazioni: cron avviato — 01:00 export KB · 05:00 applica · 06:00 fonti · 07:30 alert"

# `cron -f` in primo piano come PID 1. `-l 2` porta i log dei job su stdout (visibili con
# `docker logs`). Se `cron` esce, **il container esce**: è preferibile un container che si riavvia e
# segnala il problema a un container che resta «Up» senza eseguire nulla — che è il modo in cui questo
# difetto si è presentato la prima volta (cron morto, container verde).
cron -f -l 2 &
CRON_PID=$!

# Resta in attesa del figlio: se cron muore, l'entrypoint esce con il suo codice e `restart:
# unless-stopped` lo fa ripartire.
wait "$CRON_PID"
