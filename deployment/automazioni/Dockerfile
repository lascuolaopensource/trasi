# Trasi — immagine del servizio `automazioni` (B4: flussi notturni).
#
# Perché un'immagine dedicata e non `db_trasi` con `docker compose exec`: i flussi devono girare
# **da soli**, con la propria identità (`automazioni`, non `postgres`) e con cron. Eseguirli dentro il
# container del database significherebbe dare all'esecutore la stessa identità del database, che è
# esattamente ciò che il modello di sicurezza di V4 esiste per impedire: `automazioni` scrive la
# memoria **solo** attraverso `applica_proposte_approvate` e l'upsert iCal su `evento`, e un
# `docker compose exec` come `postgres` userebbe il superuser per fare qualsiasi cosa.
#
# Base `python:3.12-slim` con `postgresql-client` e `cron`. Nessuna dipendenza Python: i flussi usano
# la sola stdlib e parlano al database via `psql` — la stessa scelta di `flussi/export_kb.py` e di
# `db/apply.sh`. Meno dipendenze = meno superficie di aggiornamento su un'immagine che gira da sola.
#
# `python:3.12-slim` e non `alpine`: `postgresql-client` su alpine esiste, ma musl + cron (busybox) ha
# differenze sottili nel comportamento dei job, e questa immagine esegue la contabilità della notte —
# non è il posto per scoprirle. Lo slim ha lo stesso ordine di grandezza di dimensione.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Europe/Rome \
    PATH="/app/flussi:/usr/local/bin:$PATH"

# `postgresql-client`: `psql`, l'unico trasporto verso il database (nessun driver Python).
# `cron`: lo scheduler — il punto d'ingresso primario dei flussi (§6, §8).
# `tzdata`: il fuso `Europe/Rome` deve esistere davvero, altrimenti cron gira in UTC e «05:00» non
#          significa più ciò che l'architettura intende.
RUN apt-get update \
 && apt-get install --no-install-recommends --yes \
      postgresql-client \
      cron \
      tzdata \
      ca-certificates \
      util-linux \
 && rm -rf /var/lib/apt/lists/*

# Utente non root, senza shell di login. L'uid è fisso: i file di registro nel volume devono avere un
# proprietario noto, e un uid che cambia a ogni rebuild renderebbe il volume illeggibile al container
# successivo. Lo stesso schema dello shim (uid 10001) per coerenza.
# `/var/run/crond.pid`: il cron di Debian crea il proprio pid file lì e **come utente non root non
# può** — verificato: «cron: can't open or create /var/run/crond.pid: Permission denied» e lo
# scheduler non parte affatto. Il servizio esisterebbe e non eseguirebbe nulla, in silenzio. Il file
# si crea qui con il proprietario giusto: è una concessione minima e necessaria, non un permesso
# generale su `/var/run`.
RUN groupadd --system --gid 10002 automazioni \
 && useradd --system --uid 10002 --gid automazioni --no-create-home \
      --shell /usr/sbin/nologin automazioni \
 && mkdir -p /var/log/trasi /var/spool/cron/crontabs /var/run \
 && touch /var/run/crond.pid \
 && chown automazioni:automazioni /var/log/trasi /var/spool/cron/crontabs /var/run/crond.pid

# I flussi sono montati **read-only** dal compose (`../flussi:/app/flussi:ro`): il codice non si
# riscrive in esercizio. La copia qui è un default per chi avvia l'immagine senza il mount, e rende
# l'immagine verificabile da sola (`docker run --rm trasi-automazioni:local --help`).
COPY --chown=automazioni:automazioni flussi /app/flussi
RUN chmod +x /app/flussi/*.py /app/flussi/*.sh /app/flussi/job.sh

# Il crontab del container: i quattro orari dell'architettura §6. `crontab` di Debian vuole il file
# in `/etc/cron.d/` **senza** l'utente duplicato quando gira come non-root: si installa con `crontab -u`
# dentro l'entrypoint, dove l'utente è già `automazioni`.
COPY --chown=automazioni:automazioni flussi/crontab /app/flussi/crontab

COPY --chown=automazioni:automazioni deployment/automazioni/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# **Nessun `USER automazioni`.** Il container parte come root perché `cron` ne ha bisogno per
# `seteuid`: come utente non privilegiato esce subito con «seteuid: Operation not permitted» e
# **nessuno dei quattro job parte** — verificato, e l'unico sintomo è una riga in `docker logs`.
# I permessi non si allargano: l'entrypoint scrive le credenziali con `umask 077` e installa il
# crontab con `runuser -u automazioni`; ogni job gira come `automazioni` (il crontab lo dichiara).
# Il container non pubblica porte e monta il codice in sola lettura, quindi l'utente di PID 1 non ha
# una superficie di attacco: `cron` di Debian è progettato per girare così.

# Nessuna porta: l'esecutore non espone servizi. `EXPOSE` assente di proposito.
# Healthcheck: cron vivo **e** database raggiungibile — un container che gira senza poter parlare col
# database è un container che fallisce ogni notte senza che nessuno se ne accorga.
#
# `pidof` e non `pgrep`: `procps` **non è installato** in questa immagine, quindi `pgrep` esce 127
# («/bin/sh: 1: pgrep: not found») e l'healthcheck dichiara il container **unhealthy** mentre cron è
# vivo e i job partono regolarmente — un allarme falso permanente, cioè un allarme che si impara a
# ignorare. `pidof` è in `sysvinit-utils`, già presente come dipendenza di `cron`: zero pacchetti in
# più e la stessa informazione. (Segnalato e riprodotto da `trasi-stack` con `docker inspect`.)
HEALTHCHECK --interval=60s --timeout=10s --start-period=20s --retries=3 \
    CMD pg_isready -h "${PGHOST:-db_trasi}" -p "${PGPORT:-5432}" -U "${PGUSER:-automazioni}" -q \
        && pidof cron > /dev/null

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
