#!/bin/sh
# Trasi — flussi/job.sh · il guscio di ogni esecuzione schedulata.
#
# Serve a una cosa sola, e vale la pena spiegarla: **le credenziali non stanno nel crontab**.
#
# `cron` non eredita l'ambiente del container, quindi `PGPASSWORD` va fornita al job in un modo o
# nell'altro. Le due alternative ovvie sono entrambe sbagliate: scriverla in una riga del crontab
# mette un segreto in un file (e nella sua copia in `/app/flussi/crontab`, che è in sola lettura e
# versionata); passarla con `-e` nell'`ENTRYPOINT` la mette in `docker inspect`, dove chiunque abbia
# accesso al demone la legge.
#
# Qui invece l'entrypoint scrive le variabili in `/run/trasi/env` (mode 600, proprietario
# `automazioni`, dentro il container) e il job le carica solo se il file esiste. Sul **host** il file
# non c'è e il job usa l'ambiente dell'utente — lo stesso `crontab` funziona nei due posti senza
# duplicazioni, ed è il motivo per cui questo file usa `sh` e non `bash`: sul host può essere
# eseguito da un cron minimale.
#
# Uso (dal crontab):  job.sh /app/flussi/export_kb.py
#                     job.sh /app/flussi/applica.sh

set -eu

if [ -r /run/trasi/env ]; then
  # shellcheck disable=SC1091
  . /run/trasi/env
fi

if [ "$#" -eq 0 ]; then
  echo "job.sh: nessun comando da eseguire" >&2
  exit 2
fi

exec "$@"
