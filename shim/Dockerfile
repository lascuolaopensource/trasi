# Shim Trasi — immagine di produzione dello stub (contratto v0, gate V-09).
#
# Multi-stage: il builder compila e installa le dipendenze in un venv, lo stage finale porta solo il venv e il codice.
# Il container gira con utente non root e usa i tempi dichiarati dal contratto (§9.1): 3 s shim, 5 s Overpass.

# --- Stage 1: dipendenze ---------------------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

# Il venv è autoconsistente: si copia nello stage finale senza dipendere dal layout di sistema.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
COPY requirements.txt ./
RUN pip install --no-compile -r requirements.txt

# --- Stage 2: runtime -----------------------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    # Tempi dichiarati dal contratto e fuso di riferimento per «oggi» e gli orari.
    SHIM_TIMEOUT_S=3 \
    OVERPASS_TIMEOUT_S=5 \
    TZ=Europe/Rome \
    # Nessun access log: le richieste contengono l'email dell'operatore e i corpi contengono testo dell'operatore.
    # Il log applicativo di B3 registrerà solo ts, method, operationId, status, ms, ruolo.
    UVICORN_ACCESS_LOG=0

COPY --from=builder /opt/venv /opt/venv

# Utente non root, senza shell di login: l'immagine non deve poter scrivere nel proprio codice.
RUN groupadd --system --gid 10001 shim \
    && useradd --system --uid 10001 --gid shim --no-create-home --shell /usr/sbin/nologin shim

WORKDIR /app
COPY --chown=shim:shim app ./app
COPY --chown=shim:shim openapi.yaml ./

USER shim

EXPOSE 8000

# Liveness reale: interroga `/healthz`, l'unica risposta non 501 dello stub.
HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3).status == 200 else 1)"]

# Un solo worker: lo stub è senza stato e il limite di memoria del compose è 256m; nessun access log (dati personali).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--workers", "1"]
