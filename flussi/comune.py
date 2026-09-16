"""Trasi — flussi: trasporto verso il database, registro dei run e presidio V6.

Perché un modulo e non tre righe copiate in ogni script: la scelta del trasporto (host ↔ container),
la scrittura in `flusso_run` e il **check lessicale V6** sono le tre cose che devono valere *uguali*
per tutti i flussi. Duplicarle significherebbe che un flusso, un giorno, le dimentica — ed è esattamente
il tipo di deriva che V6 e «ogni flusso lascia traccia» esistono per impedire.

**Trasporto.** Due modi di raggiungere il database, scelti da `TRASI_DB_VIA`:

  * `docker` (default quando `docker` è nel PATH) — `docker compose exec -T db_trasi psql …`, la stessa
    via di `db/apply.sh` e di `flussi/export_kb.py`. È il modo con cui i flussi girano **a mano** da host.
  * `diretta` — `psql` locale verso `PGHOST`/`PGUSER`/`PGDATABASE`. È il modo con cui girano **dentro**
    il container `automazioni`, dove `docker` non esiste.

Nessuna dipendenza Python oltre la stdlib e nessun driver Postgres: il traffico dati passa dalla
`COPY … TO STDOUT WITH CSV HEADER` di `psql`, che è anche il modo in cui i valori restano
inequivocabili (niente separatori inventati, niente quoting a mano).

**Sicurezza dei valori.** Le stringhe che finiscono in SQL non vengono mai concatenate a mano: o
viaggiano come **variabile psql** (`:'nome'`, quotata da psql) o come **JSON** passato a
`jsonb_to_recordset`. L'unica interpolazione testuale ammessa è su valori che il codice stesso ha
costruito (identificatori interni, numeri), mai su testo proveniente da una pagina web o da un feed.

**V6.** `verifica_v6()` è il presidio automatico: cerca i verbi che assegnano un compito. Un messaggio
di Trasi dice *cosa è stato osservato*, *su quale evidenza*, *cosa si potrebbe fare* e *chi decide* — non
ordina. La funzione è usata sia dai template sia dai test, così il presidio non è una convenzione.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

RADICE = Path(__file__).resolve().parent.parent
COMPOSE = RADICE / "deployment" / "docker-compose.yml"
ENV_DEPLOY = RADICE / "deployment" / ".env"

SERVIZIO_DB = "db_trasi"
DB_DEFAULT = "trasi_db"
UTENTE_DOCKER = "postgres"

#: Ruolo applicativo dei flussi. `automazioni` scrive la memoria **solo** attraverso le funzioni SQL
#: (§8 F9) e l'upsert iCal su `evento` (§8 F4); tutto il resto lo propone.
RUOLO_FLUSSI = "automazioni"

#: §12: la motivazione di una proposta è testo libero ma breve — è il campo che sopravvive alla chat
#: (`gg_retention_chat`), quindi ogni carattere in più è un carattere in più di memoria permanente.
MOTIVAZIONE_MAX = 80

#: Verbi che **assegnano un compito** a una persona o a una Casa (V6). Il confronto è per parola
#: intera e case-insensitive: «fate» non deve far scattare «sfate».
#:
#: L'elenco contiene forme imperative (2ª persona) e modali di obbligo, **non gli infiniti**.
#: La distinzione non è pedanteria: «si può contattare via PEC» descrive, «contatta il CAF» ordina — e
#: V6 vieta il secondo. Includere `contattare`/`assegnare` farebbe scattare il presidio su una frase
#: legittima, e un presidio che blocca messaggi buoni è un presidio che qualcuno disattiva. Il campo
#: `cosa_si_potrebbe_fare` dell'architettura §2.2 è per costruzione una *proposta*, e in italiano la
#: forma naturale di una proposta è l'infinito.
#:
#: La verifica lessicale non sostituisce la lettura: è il minimo che deve valere in CI. Un messaggio
#: può assegnare un compito senza usare nessuna di queste parole — ma non può **evitare** di dire chi
#: decide, perché `chi_decide` è un campo obbligatorio del template (`CAMPI_V6`).
VERBI_IMPERATIVI = (
    "devi", "dovete", "deve", "devono",
    "fai", "fate",
    "assegna", "assegnate",
    "contatta", "contattate",
    "bisogna", "occorre",
    "provvedi", "provvedete",
)
_RE_V6 = re.compile(r"\b(" + "|".join(VERBI_IMPERATIVI) + r")\b", re.IGNORECASE)

#: Campi V6 obbligatori in ogni messaggio. Il nome è quello dell'architettura §2.2.
CAMPI_V6 = ("cosa_osservato", "evidenza", "cosa_si_potrebbe_fare", "chi_decide")

#: Esiti ammessi in `flusso_run.esito` (CHECK di `db/020_flusso.sql`). Il registro è il posto dove si
#: legge «com'è andata stanotte», quindi il vocabolario è chiuso: `ok` = tutto applicato,
#: `parziale` = qualcosa è stato segnalato o è caduto senza fermare il flusso, `errore` = non ha
#: concluso. Un esito più specifico («anomalo») vive in `fonte_run`, che ha il suo vocabolario.
ESITI_FLUSSO = ("ok", "parziale", "errore")


class FlussoErrore(RuntimeError):
    """Errore non recuperabile di un flusso: la causa va in `flusso_run.dettaglio` e in stderr."""


# --------------------------------------------------------------------------- configurazione


def _da_env_file(nome: str) -> str:
    """Un valore da `deployment/.env`, la stessa sorgente del compose. Mai stampato."""
    try:
        with ENV_DEPLOY.open(encoding="utf-8") as f:
            for riga in f:
                riga = riga.strip()
                if riga.startswith(f"{nome}="):
                    return riga.split("=", 1)[1].strip()
    except OSError:
        return ""
    return ""


def via_trasporto() -> str:
    """`docker` o `diretta`. Esplicito con `TRASI_DB_VIA`, altrimenti dedotto dalla disponibilità di `docker`."""
    dichiarata = os.environ.get("TRASI_DB_VIA", "").strip().lower()
    if dichiarata in ("docker", "diretta"):
        return dichiarata
    return "docker" if shutil.which("docker") else "diretta"


def _comando_psql() -> list[str]:
    """Il comando `psql`, sempre nel ruolo `automazioni`.

    **L'identità è la connessione, non un `SET ROLE`.** `automazioni` è un ruolo LOGIN: i flussi si
    connettono *come* `automazioni`, e `session_user` resta `automazioni` per tutta la sessione.

    Perché è decisivo e non una preferenza di stile. Il trigger `evento_ical_01_audit` (db/006)
    attribuisce la riga `ical_upsert` guardando `session_user`, e `v_scritture_senza_audit` distingue
    una scrittura dichiarata da una violazione di V4 sempre da lì. Con `SET ROLE automazioni` su una
    connessione amministrativa, `current_user` diventa `automazioni` ma `session_user` resta
    `postgres`: le scritture passano (il superuser scavalca la RLS), **l'audit iCal non parte**, e
    nulla nell'exit code lo segnala. Misurato durante lo sviluppo di questo blocco: 5 eventi scritti,
    0 righe di audit. È la definizione di perdita silenziosa di tracciabilità, ed è il motivo per cui
    esiste `flussi/tests/test_identita.py`.
    """
    if via_trasporto() == "diretta":
        return ["psql", "-X", "-q", "--no-psqlrc"]
    return [
        "docker", "compose", "-f", str(COMPOSE), "exec", "-T", SERVIZIO_DB,
        "psql", "-U", RUOLO_FLUSSI, "-d", os.environ.get("TRASI_DB") or DB_DEFAULT,
        "-X", "-q", "--no-psqlrc",
    ]


def _ambiente() -> dict[str, str]:
    """Ambiente del sottoprocesso: solo per il trasporto diretto, e senza mai esporre la password in argv."""
    ambiente = dict(os.environ)
    if via_trasporto() == "diretta":
        ambiente.setdefault("PGUSER", RUOLO_FLUSSI)
        ambiente.setdefault("PGDATABASE", os.environ.get("TRASI_DB") or DB_DEFAULT)
        if not ambiente.get("PGPASSWORD"):
            ambiente["PGPASSWORD"] = (
                os.environ.get("AUTOMAZIONI_DB_PASSWORD") or _da_env_file("AUTOMAZIONI_DB_PASSWORD")
            )
    return ambiente


def trigger_corrente() -> str:
    """Chi ha avviato questo run: `cron` o `manuale` (default `manuale`: chi esegue a mano lo dichiara)."""
    valore = os.environ.get("TRASI_TRIGGER", "manuale").strip().lower()
    return valore if valore in ("cron", "manuale") else "manuale"


# --------------------------------------------------------------------------- esecuzione SQL


def esegui_sql(sql: str, *, variabili: dict[str, str] | None = None, stdin_extra: str = "") -> str:
    """Esegue SQL passato via stdin (nessun quoting di shell) e ritorna stdout.

    `variabili` diventa `-v nome=valore`: nel SQL si usa `:'nome'` per un letterale stringa, che è
    psql a quotare. È il modo con cui un valore esterno entra in una query senza essere concatenato.

    **`ON_ERROR_STOP=1` è obbligatorio, non una preferenza.** Senza, `psql` esegue l'istruzione,
    stampa l'errore su stderr e **esce 0**: un errore SQL diventa un risultato vuoto, e il chiamante
    riceve una lista vuota invece di un'eccezione. Misurato durante lo sviluppo: una query con una
    colonna inesistente (`n_righe` invece di `righe`) è tornata `''` con exit 0, e il difetto si è
    presentato come un `IndexError` tre livelli più in basso — in un test, non in esercizio, e solo
    perché il codice leggeva `[0]`. In un flusso notturno lo stesso errore avrebbe prodotto un
    conteggio a zero presentato come «nessuna variazione».
    """
    comando = _comando_psql() + ["-v", "ON_ERROR_STOP=1"]
    for nome, valore in (variabili or {}).items():
        comando += ["-v", f"{nome}={valore}"]
    comando += ["-f", "-"]
    esito = subprocess.run(
        comando, input=sql + stdin_extra, capture_output=True, text=True, env=_ambiente(), check=False
    )
    if esito.returncode != 0:
        raise FlussoErrore(
            f"psql ha fallito (exit {esito.returncode}): {esito.stderr.strip()[:800]}"
        )
    return esito.stdout


def leggi(query: str) -> list[dict[str, str]]:
    """Righe di una query come dizionari.

    `COPY … TO STDOUT WITH CSV HEADER` e non `-c`: è la stessa via di `flussi/export_kb.py`, e il CSV
    rende il testo (newline, virgole, jsonb) leggibile senza inventare separatori.
    """
    query = query.strip().rstrip(";")
    if not query.lstrip().lower().startswith(("select", "with")):
        raise FlussoErrore("leggi() accetta solo SELECT/WITH: per le scritture usa esegui_sql()")
    uscita = esegui_sql(f"COPY ({query}) TO STDOUT WITH CSV HEADER\n")
    righe = list(csv.DictReader(io.StringIO(uscita)))
    return [{k: (v if v is not None else "") for k, v in riga.items()} for riga in righe]


def uno(query: str, colonna: str, default: str = "") -> str:
    """Il primo valore di `colonna`, o `default`: per i conteggi e le letture di un solo valore."""
    righe = leggi(query)
    return righe[0][colonna] if righe else default


def parametro_int(chiave: str, default: int) -> int:
    """Un parametro `[P]`, con il default dichiarato dal chiamante.

    La funzione SQL ritorna NULL se la chiave non esiste (scelta di `db/003`): qui il default è del
    *flusso*, non del database, così una soglia nuova si può introdurre senza un file di seed di B1.
    Un valore non numerico (configurazione sbagliata) non deve far cadere la notte: si usa il default.
    """
    try:
        valore = uno(f"SELECT trasi.p_int('{chiave}') AS v", "v")
    except FlussoErrore:
        return default
    try:
        return int(valore)
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- flusso_run


@dataclass
class Run:
    """Un'esecuzione di flusso: la riga di `flusso_run` (plan.md §4 B4-FLW-02)."""

    nome: str
    inizio: datetime
    trigger: str
    dettaglio: dict
    esito: str = "ok"
    n_righe: int = 0

    def con(self, **campi) -> "Run":
        for chiave, valore in campi.items():
            setattr(self, chiave, valore)
        return self

    def nota(self, **campi) -> "Run":
        self.dettaglio.update(campi)
        return self

    def chiudi(self, esito: str, n_righe: int, **dettaglio) -> "Run":
        """Chiude il run. `esito` deve essere uno dei valori che `flusso_run` accetta.

        Il controllo è qui e non solo nel CHECK del database perché il messaggio di un CHECK arriva
        come «violates check constraint» dal fondo di una transazione, mentre un errore scritto qui
        dice quale flusso e quale valore. Il CHECK resta la garanzia (i vincoli sono l'autorità);
        questo è la diagnosi.
        """
        if esito not in ESITI_FLUSSO:
            raise FlussoErrore(
                f"esito {esito!r} non ammesso in `flusso_run` per il flusso {self.nome!r}: "
                f"i valori sono {', '.join(sorted(ESITI_FLUSSO))}"
            )
        self.esito = esito
        self.n_righe = n_righe
        self.dettaglio.update(dettaglio)
        return self


def apri_run(nome: str, **dettaglio) -> Run:
    return Run(nome=nome, inizio=datetime.now(timezone.utc), trigger=trigger_corrente(),
               dettaglio=dict(dettaglio))


def _jsonb(valore: object) -> str:
    """Un valore Python come letterale jsonb, per la variabile psql `:'dettaglio'`."""
    return json.dumps(valore, ensure_ascii=False, default=str)


def registra_run(run: Run) -> None:
    """Scrive la riga di `flusso_run`. È l'unica scrittura che ogni flusso fa sempre, anche in errore.

    Passa da `:'dettaglio'::jsonb`: il JSON contiene testo di fonti esterne, quindi non deve mai
    essere concatenato nella query.
    """
    sql = (
        "INSERT INTO trasi.flusso_run (nome, trigger, inizio_ts, fine_ts, esito, n_righe, dettaglio)\n"
        "VALUES (:'nome', :'trigger', :'inizio'::timestamptz, now(), :'esito', :'n_righe'::int,\n"
        "        :'dettaglio'::jsonb)\n"
    )
    esegui_sql(
        sql,
        variabili={
            "nome": run.nome,
            "trigger": run.trigger,
            "inizio": run.inizio.isoformat(),
            "esito": run.esito,
            "n_righe": str(run.n_righe),
            "dettaglio": _jsonb(run.dettaglio),
        },
    )


def registra_fonte_run(fonte_id: int, esito: str, righe: int, *, hash_: str = "",
                      dettaglio: dict | None = None) -> None:
    """Una riga in `fonte_run` (append-only): l'esito di *questa* fonte in *questo* run."""
    sql = (
        "INSERT INTO trasi.fonte_run (fonte_id, esito, righe, hash, dettaglio, eseguito_da)\n"
        "VALUES (:'fonte_id'::int, :'esito', :'righe'::int, NULLIF(:'hash', ''), :'dettaglio'::jsonb,\n"
        "        session_user)\n"
    )
    esegui_sql(
        sql,
        variabili={
            "fonte_id": str(fonte_id),
            "esito": esito,
            "righe": str(righe),
            "hash": hash_ or "",
            "dettaglio": _jsonb(dettaglio or {}),
        },
    )


# --------------------------------------------------------------------------- testo e V6


def verifica_v6(testo: str) -> list[str]:
    """Verbi imperativi trovati nel testo (V6: un messaggio dice *chi decide*, non assegna compiti).

    Ritorna l'elenco dei riscontri: lista vuota = conforme. Il confronto è case-insensitive e su
    parola intera — `fate` non fa scattare `sfate`, e l'accento non conta.
    """
    return sorted({m.group(0).lower() for m in _RE_V6.finditer(testo)})


def v6_ok(testo: str) -> bool:
    return not verifica_v6(testo)


def tronca(testo: str, limite: int) -> str:
    """Tronca senza spezzare l'ultima parola e senza finire con punteggiatura sospesa."""
    testo = " ".join((testo or "").split())
    if len(testo) <= limite:
        return testo
    tagliato = testo[: limite - 1].rsplit(" ", 1)[0]
    return (tagliato or testo[: limite - 1]) + "…"


def motivazione(testo: str) -> str:
    """`motivazione` di una proposta: ≤ 80 caratteri (§12). Il limite è applicato qui, non sperato."""
    return tronca(testo, MOTIVAZIONE_MAX)


def log(messaggio: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {messaggio}", flush=True)


def esci_con_errore(messaggio: str) -> int:
    print(f"errore: {messaggio}", file=sys.stderr, flush=True)
    return 1
