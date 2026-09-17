#!/usr/bin/env python3
"""Trasi — F5 «Ciclo mensile» (B6-FLW-02, §8 F5) · digest alle Case e report allo staff PN.

Giorno `[P] giorno_ciclo_mensile` (default 3), alle 08:00. Produce:

* **un digest per Casa** (10), con il riepilogo del mese — richieste, esiti, destinazioni,
  proposte in attesa — al recapito della Casa (`v_flusso_recapiti`: `email_digest` → identità
  gestore → AT);
* **un report per lo staff PN** con il **CSV** `trasi_rete_YYYY-MM.csv` allegato, con le celle
  k-anonime (`<5`, `—`) già mascherate da `trasi.k_anon` — il report non ricalcola i numeri, li legge;
* **i report persistiti** (US-4): una riga `trasi.report` per Casa (`ambito='casa'`) e una unica
  `ambito='osservatorio'` con il CSV in colonna, in stato `bozza`: l'approvazione è umana
  (operatore referente, ruolo `rete`), la notifica alla PA è del flusso `alert` (07:30) che legge
  `trasi.v_report_da_notificare`. La persistenza è **prima dell'invio**: il report è il documento
  che il digest riassume, e deve esistere anche se un'email rimbalza.

**Perché i messaggi sono miei.** Il contenuto di un messaggio di Trasi ha tre vincoli che vivono in
questo blocco: i **quattro campi V6** (chi decide, non chi deve fare), la catena di recapito per
competenza (§8 F6) e il presidio `verifica_v6()`. Reimplementarli in un altro linguaggio significherebbe
duplicare tutti e tre, e la duplicazione di una regola di governance è ciò che §11 vieta. La
**schedulazione** invece è di `ops/`: il cron è un orologio, non una decisione di dominio.

**Idempotenza — la scelta dichiarata.** Un secondo run nello stesso mese **non raddoppia** i digest:
riconosce di aver già girato (`flusso_run.dettaglio` del ciclo del mese corrente) e, senza `--forza`,
esce senza inviare nulla. Rimandare un digest è una decisione umana: si fa con `--forza`, che lo
dichiara in `flusso_run.dettaglio.forzato`. Un ciclo che rimandasse da solo, ogni volta che lo si
esegue, sarebbe un ciclo che riempie le caselle il giorno in cui qualcuno lo esegue due volte per
provare. `--forza` rimanda i **messaggi** ma **non riscrive i report**: un report esistente non si
aggiorna (V4: UPDATE non grantato per costruzione, db/024 — il report si legge e si commenta, non si
corregge) e un duplicato è impedito dalla SELECT di esistenza per (casa, mese, ambito); il fatto resta
registrato in `flusso_run.dettaglio.report.gia_esistenti`.

**Vincoli rispettati.** Nessuna scrittura su NocoDB né su REGIS (§9): i messaggi escono via SMTP o su
file. Nessun dato personale (§12): i digest portano conteggi k-anonimi e id di proposta, mai il testo
di una richiesta o un nome. `richiesta` non ha campi per il cittadino — il k-anonimato è l'ultima
difesa, non l'unica.

Uso:
    flussi/ciclo_mensile.py                 # invia (SMTP se configurato, altrimenti file)
    flussi/ciclo_mensile.py --dry-run       # mostra cosa invierebbe
    flussi/ciclo_mensile.py --forza         # riesegue anche se il mese è già stato fatto
    flussi/ciclo_mensile.py --mese 2026-09  # un mese specifico (per la verifica a mano)
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from comune import (  # noqa: E402
    CAMPI_V6,
    FlussoErrore,
    apri_run,
    esegui_sql,
    leggi,
    log,
    parametro_int,
    registra_run,
    verifica_v6,
)

RADICE = Path(__file__).resolve().parent.parent
CARTELLA_CSV = RADICE / "flussi" / "evidenze" / "ciclo_mensile"

#: Giorno del mese del ciclo. `[P] giorno_ciclo_mensile`, valore iniziale 3 (db/003).
GIORNO_DEFAULT = 3


class CicloErrore(FlussoErrore):
    """Errore del ciclo mensile."""


# --------------------------------------------------------------------------- dati


def _mese_corrente(mese: str | None) -> date:
    """Il primo giorno del mese da rendicontare. `--mese 2026-09` o il mese corrente."""
    if not mese:
        oggi = date.today()
        return oggi.replace(day=1)
    try:
        return datetime.strptime(mese, "%Y-%m").date().replace(day=1)
    except ValueError as errore:
        raise CicloErrore(f"--mese {mese!r} non è nel formato YYYY-MM") from errore


def _digest_per_casa(mese: date) -> list[dict]:
    """Il riepilogo del mese, una riga per Casa.

    Legge le **viste** di B1 e non le tabelle: i conteggi che possono re-identificare una persona
    passano da `trasi.k_anon` (soglia `[P] k_anonimato`, 5) e arrivano qui già mascherati (`n` NULL,
    `n_label` `<5`/`—`). Ricalcolarli in Python significherebbe reimplementare la regola di §12 e,
    prima o poi, dimenticarla in un ramo.
    """
    righe = leggi(
        "WITH mesi AS ("
        "  SELECT casa_id, casa_slug, casa_nome, categoria, esito, n, n_label "
        "    FROM trasi.v_report_mensile WHERE mese = DATE " + f"'{mese.isoformat()}'"
        "), per_casa AS ("
        "  SELECT casa_slug, casa_nome,"
        "         count(*) FILTER (WHERE n_label NOT IN ('—')) AS voci,"
        "         COALESCE(sum(n), 0) AS richieste,"
        "         count(*) FILTER (WHERE esito = 'non_trovata' AND n_label NOT IN ('—')) AS senza_risposta"
        "    FROM mesi GROUP BY 1, 2"
        ")"
        "SELECT c.slug AS casa_slug, c.nome AS casa_nome,"
        "       COALESCE(p.richieste, 0) AS richieste,"
        "       COALESCE(p.senza_risposta, 0) AS senza_risposta,"
        "       (SELECT count(*) FROM trasi.proposta pr"
        "         WHERE pr.casa_id = c.id AND pr.stato = 'proposta') AS proposte_aperte,"
        "       (SELECT count(*) FROM trasi.proposta pr"
        "         WHERE pr.casa_id = c.id AND pr.stato = 'applicata'"
        f"           AND pr.proposto_ts >= DATE '{mese.isoformat()}') AS applicate,"
        "       (SELECT count(*) FROM trasi.scheda_servizio s"
        "         WHERE s.casa_id = c.id AND s.scadenza IS NOT NULL"
        "           AND s.scadenza <= current_date + 15) AS in_scadenza"
        "  FROM trasi.casa c LEFT JOIN per_casa p ON p.casa_slug = c.slug"
        " ORDER BY c.slug"
    )
    return righe


def _recapito(casa_slug: str) -> str:
    """Il recapito della Casa, dalla vista ridotta. Nessuna convenzione replicata qui."""
    righe = leggi(
        "SELECT destinatario FROM trasi.v_flusso_recapiti "
        f" WHERE casa_slug = '{casa_slug}' AND destinatario IS NOT NULL"
    )
    return righe[0]["destinatario"] if righe else ""


def _recapito_pn() -> str:
    """Il recapito dello staff PN. Oggi è l'AT: le identità in `identita_onyx` sono 22 e nessuna è
    marcata «PN». Si legge dal ruolo, come per gli alert, invece di inventare un indirizzo."""
    righe = leggi(
        "SELECT destinatario FROM trasi.v_flusso_destinatari "
        " WHERE ruolo = 'rete' AND destinatario IS NOT NULL LIMIT 1"
    )
    return righe[0]["destinatario"] if righe else ""


def _csv_rete(mese: date) -> tuple[str, int]:
    """Il CSV del report PN, dalle viste k-anonime. Ritorna `(contenuto, righe)`.

    Le celle `<5` e `—` arrivano dalla vista: il CSV le **trascrive**, non le calcola. È il criterio
    «celle `<5` nel CSV» di B6-FLW-02, e metterlo in Python invece che nella vista lo renderebbe una
    seconda verità sulla stessa regola.
    """
    righe = leggi(
        "SELECT casa_slug, casa_nome, categoria, esito, n_label "
        "  FROM trasi.v_report_mensile "
        f" WHERE mese = DATE '{mese.isoformat()}' ORDER BY casa_slug, categoria, esito"
    )
    buffer = io.StringIO()
    scrittore = csv.writer(buffer, lineterminator="\n")
    scrittore.writerow(["casa", "categoria", "esito", "n"])
    for riga in righe:
        scrittore.writerow([riga["casa_slug"], riga["categoria"], riga["esito"], riga["n_label"]])
    return buffer.getvalue(), len(righe)


# --------------------------------------------------------------------------- messaggi


@dataclass
class Messaggio:
    """Un messaggio del ciclo: destinatario, oggetto, quattro campi V6, righe di dettaglio."""

    a: str
    oggetto: str
    campi: dict[str, str]
    righe: list[str]
    allegato: tuple[str, str] | None = None   # (nome file, contenuto)

    def corpo(self) -> str:
        return "\n".join([
            "Trasi — ciclo mensile della rete delle Case di Quartiere",
            "",
            f"Cosa è stato osservato: {self.campi['cosa_osservato']}",
            f"Su quale evidenza: {self.campi['evidenza']}",
            f"Cosa si potrebbe fare: {self.campi['cosa_si_potrebbe_fare']}",
            f"Chi decide: {self.campi['chi_decide']}",
            "",
            *self.righe,
            "",
            "— Messaggio generato dal ciclo mensile. Non rispondere a questo indirizzo.",
        ]).rstrip() + "\n"

    def verifica(self) -> list[str]:
        return verifica_v6(self.oggetto + "\n" + self.corpo())


def messaggi(mese: date) -> tuple[list[Messaggio], str, int]:
    """I 10 digest + il report PN, e il CSV. Ritorna `(messaggi, csv, righe_csv)`."""
    digest = _digest_per_casa(mese)
    if not digest:
        raise CicloErrore("nessuna Casa nel database: il ciclo non ha destinatari")

    messaggi_: list[Messaggio] = []

    for riga in digest:
        recapito = _recapito(riga["casa_slug"])
        if not recapito:
            raise CicloErrore(
                f"la Casa {riga['casa_slug']} non ha recapito: né `email_digest` né identità "
                "gestore (v_flusso_recapiti). Senza destinatario il digest non si invia."
            )
        aperte = int(riga["proposte_aperte"])
        messaggi_.append(
            Messaggio(
                a=recapito,
                oggetto=f"Trasi · digest di {mese.strftime('%m/%Y')} — {riga['casa_nome']}",
                campi={
                    "cosa_osservato": (
                        f"Nel mese: {riga['richieste']} richieste registrate"
                        + (f", {riga['senza_risposta']} con esito «non trovata»"
                           if int(riga["senza_risposta"]) else "")
                        + f". In coda: {aperte} proposte in attesa."
                    ),
                    "evidenza": (
                        "viste trasi.v_report_mensile (k-anonimo: celle sotto soglia mostrate come "
                        "«<5», zero come «—») e trasi.v_proposte_aperte"
                    ),
                    "cosa_si_potrebbe_fare": (
                        "Il digest si legge per Casa: le voci con «non trovata» indicano dove la rete "
                        "non ha ancora una risposta, e le proposte in attesa si possono approvare "
                        "o rifiutare dalla coda della propria Casa."
                    ),
                    "chi_decide": (
                        "I dati della Casa li decide il gestore; i luoghi e i servizi del territorio "
                        "li decide l’AT. La promozione di un dato esterno in memoria resta in mano "
                        "all’AT."
                    ),
                },
                righe=[
                    f"  · richieste registrate: {riga['richieste']}",
                    f"  · proposte in attesa: {aperte}",
                    f"  · proposte applicate nel mese: {riga['applicate']}",
                    f"  · schede in scadenza (15 gg): {riga['in_scadenza']}",
                ],
            )
        )

    csv_testo, righe_csv = _csv_rete(mese)
    pn = _recapito_pn()
    if not pn:
        raise CicloErrore("nessun recapito per lo staff PN (identità del ruolo `rete` assente)")

    totale_richieste = sum(int(r["richieste"]) for r in digest)
    totale_aperte = sum(int(r["proposte_aperte"]) for r in digest)
    messaggi_.append(
        Messaggio(
            a=pn,
            oggetto=f"Trasi · report di rete {mese.strftime('%m/%Y')} ({len(digest)} Case)",
            campi={
                "cosa_osservato": (
                    f"Nel mese: {totale_richieste} richieste su {len(digest)} Case, "
                    f"{totale_aperte} proposte in attesa in tutta la rete. "
                    f"CSV allegato: {righe_csv} righe."
                ),
                "evidenza": (
                    "viste trasi.v_report_mensile (k-anonima) e trasi.v_proposte_aperte; "
                    f"allegato {f'trasi_rete_{mese.strftime("%Y-%m")}.csv'}"
                ),
                "cosa_si_potrebbe_fare": (
                    "Il CSV si apre in un foglio di calcolo per il confronto fra Case; le celle "
                    "«<5» indicano i conteggi sotto la soglia di k-anonimato e «—» i conteggi a zero."
                ),
                "chi_decide": (
                    "La lettura di rete è dello staff PN; la validazione dei dati di una Casa resta "
                    "del suo gestore, quella dei dati del territorio dell’AT."
                ),
            },
            righe=[
                f"  · Case nel report: {len(digest)}",
                f"  · richieste totali (dove sopra soglia): {totale_richieste}",
                f"  · proposte in attesa: {totale_aperte}",
                "  · allegato CSV con le celle k-anonime già mascherate",
            ],
            allegato=(f"trasi_rete_{mese.strftime('%Y-%m')}.csv", csv_testo),
        )
    )
    return messaggi_, csv_testo, righe_csv


# ----------------------------------------------------------------- persistenza dei report (US-4)


def _run_id_sql(run: Run | None) -> int | None:
    """L'id del run corrente se è già nel registro, altrimenti di un run passato non fallito dello
    stesso mese, altrimenti None. `flusso_run_id` è nullable per costruzione (db/024): le metà
    esistenti — report scritti da cicli precedenti a questa persistenza — non hanno il legame,
    e la risoluzione via `flusso_run` li lega all'esecuzione che li ha prodotti senza inventarlo.
    """
    if run is None:
        return None
    if getattr(run, "id", None) is not None:
        return int(run.id)
    mese = run.dettaglio.get("mese")
    if not mese:
        return None
    righe = leggi(
        "SELECT id FROM trasi.flusso_run "
        " WHERE nome = 'ciclo_mensile' AND esito != 'errore' "
        f"   AND dettaglio->>'mese' = '{mese}' "
        " ORDER BY id DESC LIMIT 1"
    )
    return int(righe[0]["id"]) if righe else None


def _run_id_letterale(run: Run | None) -> str:
    """Il letterale SQL per `flusso_run_id`: numero o `NULL`. Mai una stringa vuota castata a bigint."""
    risolto = _run_id_sql(run)
    return str(risolto) if risolto is not None else "NULL"


def persisti_report(primo: date, digest: list[dict], csv_testo: str, run: Run | None) -> dict:
    """Persiste i report del mese in `trasi.report`, una riga per Casa più l'osservatorio.

    Ritorna `{"inseriti": int, "gia_esistenti": int}`: i due conteggi sono il modo in cui
    l'idempotenza si **legge** — un secondo run dà `inseriti = 0`, e il fatto è dichiarato in
    `flusso_run.dettaglio.report`, non silenzioso.

    **Nessun `ON CONFLICT`, nè `DO NOTHING` né `DO UPDATE`.** `DO UPDATE` richiede il privilegio
    UPDATE che db/024 non concede **per costruzione** (il report si legge e si commenta, non si
    corregge: è la regola di Processi). `DO NOTHING` risolverebbe la selezione nel database, ma
    renderebbe invisibile al flusso *quale* report esisteva già: la SELECT preventiva per
    (casa, mese, ambito) è il modo in cui il run sa dichiararlo. Le due chiavi UNIQUE parziali di
    db/026 restano la guardia dal lato del database — un INSERT in corsa con un parallelo fallisce
    invece di duplicare.

    **Contenuti dell'ambito `casa`.** Le viste di B1 rilasciano solo celle k-anonime: qui si
    trascrivono `n_label` (`«<5»`, `«—»`), mai il numero grezzo. L'ambito `casa` non maschera *di
    regola* (foglio 4.3-B: è il rendiconto della Casa a sé stessa), ma questo flusso **non ha**
    accesso ai numeri pieni e non deve inventarseli: trascrivere la cella mascherata è il vincolo
    di §12 fatto struttura, non un limite aggirabile leggendo la tabella di base.
    """
    mese = primo.isoformat()
    if digest:
        slugs = ",".join(sorted(r["casa_slug"] for r in digest))
        esistenti = {
            r["casa_slug"]
            for r in leggi(
                "SELECT c.slug AS casa_slug FROM trasi.report r "
                " JOIN trasi.casa c ON c.id = r.casa_id "
                f" WHERE r.mese = DATE '{mese}' AND r.ambito = 'casa' "
                f"   AND c.slug IN ('{slugs.replace(',', "','")}')"
            )
        }
    else:
        esistenti = set()

    inseriti = 0
    gia = 0
    for riga in digest:
        slug = riga["casa_slug"]
        if slug in esistenti:
            gia += 1
            log(f"  report {slug} {primo.strftime('%m/%Y')} già presente: non riscritto")
            continue
        dettaglio = leggi(
            "SELECT categoria, esito, n_label FROM trasi.v_report_mensile "
            f" WHERE mese = DATE '{mese}' AND casa_slug = '{slug}' "
            "   AND n_label NOT IN ('—') ORDER BY categoria, esito"
        )
        contenuti = json.dumps(
            {
                "richieste": int(riga["richieste"]),
                "senza_risposta": int(riga["senza_risposta"]),
                "per_categoria_esito": [
                    {"categoria": r["categoria"], "esito": r["esito"], "n": r["n_label"]}
                    for r in dettaglio
                ],
                "proposte_in_attesa": int(riga["proposte_aperte"]),
                "proposte_applicate": int(riga["applicate"]),
                "schede_in_scadenza": int(riga["in_scadenza"]),
            },
            ensure_ascii=False,
        )
        esegui_sql(
            "INSERT INTO trasi.report (casa_id, mese, ambito, contenuti, flusso_run_id)\n"
            f"SELECT c.id, :'mese'::date, 'casa', :'contenuti'::jsonb, {_run_id_letterale(run)}\n"
            "  FROM trasi.casa c WHERE c.slug = :'slug'\n",
            variabili={"mese": mese, "contenuti": contenuti, "slug": slug},
        )
        inseriti += 1

    esito_oss = _persisti_osservatorio(primo, csv_testo, run)
    inseriti += esito_oss["inseriti"]
    gia += esito_oss["gia_esistenti"]
    return {"inseriti": inseriti, "gia_esistenti": gia}


def _persisti_osservatorio(primo: date, csv_testo: str, run: "Run | None") -> dict:
    """La riga unica `ambito='osservatorio'` del mese, con l'aggregato di rete e il CSV in colonna.

    `casa_id` è NULL per vincolo (db/026: `(ambito='osservatorio') = (casa_id IS NULL)`): la
    precondizione va cercata per ambito e mese, non per casa.
    """
    mese = primo.isoformat()
    esiste = leggi(
        "SELECT id FROM trasi.report "
        f" WHERE mese = DATE '{mese}' AND ambito = 'osservatorio' LIMIT 1"
    )
    if esiste:
        log(f"  report osservatorio {primo.strftime('%m/%Y')} già presente: non riscritto")
        return {"inseriti": 0, "gia_esistenti": 1}

    aggregato = leggi(
        "SELECT categoria, esito, n, n_label FROM trasi.v_report_confronto "
        f" WHERE mese = DATE '{mese}' ORDER BY categoria, esito"
    )
    sotto_soglia = leggi(
        "SELECT count(*) AS n FROM trasi.v_report_confronto "
        f" WHERE mese = DATE '{mese}' AND n IS NULL"
    )[0]["n"]
    proposte = leggi(
        "SELECT count(*) AS n FROM trasi.proposta WHERE stato = 'proposta'"
    )[0]["n"]
    totale_richieste = sum(
        int(r["n"]) for r in aggregato if r.get("n", "").lstrip("-").isdigit()
    )
    contenuti = json.dumps(
        {
            "totale_richieste_supra_soglia": totale_richieste,
            "celle_sotto_soglia": int(sotto_soglia),
            "per_categoria_esito": [
                {
                    "categoria": r["categoria"],
                    "esito": r["esito"],
                    "n": r["n_label"],
                    "n_mese_precedente": r.get("n_prec_label", ""),
                    "delta_pct": r.get("delta_pct", ""),
                }
                for r in aggregato
            ],
            "proposte_in_attesa": int(proposte),
        },
        ensure_ascii=False,
    )
    esegui_sql(
        "INSERT INTO trasi.report (casa_id, mese, ambito, contenuti, csv, flusso_run_id)\n"
        f"VALUES (NULL, :'mese'::date, 'osservatorio', :'contenuti'::jsonb, :'csv', "
        f"{_run_id_letterale(run)})\n",
        variabili={"mese": mese, "contenuti": contenuti, "csv": csv_testo},
    )
    return {"inseriti": 1, "gia_esistenti": 0}


# --------------------------------------------------------------------------- invio


def _config_smtp() -> tuple[str, int, str, str] | None:
    host = os.environ.get("TRASI_SMTP_HOST", "").strip()
    if not host:
        return None
    return (host, int(os.environ.get("TRASI_SMTP_PORT", "25") or 25),
            os.environ.get("TRASI_SMTP_USER", "").strip(),
            os.environ.get("TRASI_SMTP_PASSWORD", "").strip())


def _invia(messaggio: Messaggio, mittente: str) -> tuple[str, str | None]:
    """Invia un messaggio: SMTP se configurato, altrimenti file. Ritorna `(modo, percorso)`.

    Riusa `alert.invia_smtp` e `alert.invia_file` — non li reimplementa: due copie dello stesso invio
    divergono, e la divergenza si scoprirebbe il giorno in cui una casella cambia.
    """
    from alert import CARTELLA_ALERT, invia_file, invia_smtp

    config = _config_smtp()
    if config:
        invia_smtp(messaggio, mittente, config)
        return "smtp", None

    # Su file si conserva anche l'allegato: `.csv` accanto al `.eml`, con lo stesso prefisso.
    percorso = invia_file(messaggio, datetime.now())
    if messaggio.allegato:
        nome, contenuto = messaggio.allegato
        (percorso.parent / f"{percorso.stem}__{nome}").write_text(contenuto, encoding="utf-8")
    return "file", str(percorso)


def _gia_fatto(mese: date) -> bool:
    """Il ciclo di questo mese è già stato eseguito con successo?

    Si legge da `flusso_run`, che è append-only: la storia *è* la memoria di ciò che è stato fatto. Un
    file di stato separato sarebbe una seconda verità da tenere allineata.
    """
    righe = leggi(
        "SELECT id FROM trasi.flusso_run "
        " WHERE nome = 'ciclo_mensile' AND esito IN ('ok','parziale') "
        f"   AND dettaglio->>'mese' = '{mese.isoformat()}' LIMIT 1"
    )
    return bool(righe)


# --------------------------------------------------------------------------- main


def esegui(*, mese: str | None, dry_run: bool, forza: bool) -> int:
    primo = _mese_corrente(mese)
    run = apri_run("ciclo_mensile", mese=primo.isoformat())

    if not dry_run and not forza and _gia_fatto(primo):
        # Idempotenza, e la scelta è dichiarata: `--forza` per rimandare, con `forzato: true` nel
        # registro. Un ciclo che rimandasse da solo riempirebbe le caselle di dieci Case ogni volta
        # che qualcuno lo esegue per provare.
        log(f"ciclo di {primo.strftime('%m/%Y')} già eseguito: nessun invio "
            "(usa --forza per rimandarlo)")
        run.chiudi("ok", 0, gia_eseguito=True, forzato=False)
        registra_run(run)
        return 0

    try:
        messaggi_, csv_testo, righe_csv = messaggi(primo)
        # Il digest è la stessa lettura che `persisti_report` trascrive in `trasi.report` (ambito
        # casa): due query sulle stesse viste darebbero due versioni dello stesso mese da tenere
        # allineate — il documento persistito e il suo riassunto devono essere la stessa osservazione.
        digest = _digest_per_casa(primo)
    except FlussoErrore as errore:
        print(f"ciclo_mensile: {errore}", file=sys.stderr)
        run.chiudi("errore", 0, errore=str(errore))
        registra_run(run)
        return 1

    # --- presidio V6, prima di qualunque invio ----------------------------------------------
    # Stesso presidio di `alert.py`: un messaggio che impartisce compiti viola V6, e V6 è un
    # invariante. Se un template lo viola, il ciclo **non invia** e dichiara l'errore.
    violazioni = [f"{m.oggetto}: {', '.join(m.verifica())}" for m in messaggi_ if m.verifica()]
    if violazioni:
        for violazione in violazioni:
            print(f"V6 violato — {violazione}", file=sys.stderr)
        run.chiudi("errore", 0, v6_violato=violazioni)
        registra_run(run)
        return 1

    # Il CSV si salva **sempre**, anche nel dry-run: è il deliverable del report, e un dry-run che non
    # lo produce non permetterebbe di controllarlo prima di inviare.
    CARTELLA_CSV.mkdir(parents=True, exist_ok=True)
    percorso_csv = CARTELLA_CSV / f"trasi_rete_{primo.strftime('%Y-%m')}.csv"
    percorso_csv.write_text(csv_testo, encoding="utf-8")

    if dry_run:
        # Il dry-run **non** persiste i report: è una prova di «cosa invierebbe», e una bozza scritta
        # da un dry-run farebbe nascere un report che nessuno ha deciso di produrre. Stesso criterio
        # dei messaggi: si mostra, non si fa.
        log(f"dry-run: {len(messaggi_)} messaggi pronti · CSV {righe_csv} righe → {percorso_csv}")
        for messaggio in messaggi_:
            log(f"  → {messaggio.a}: {messaggio.oggetto}")
        run.chiudi("ok", 0, dry_run=True, messaggi=len(messaggi_), csv=str(percorso_csv))
        registra_run(run)
        return 0

    # --- persistenza dei report, prima dell'invio (US-4) -------------------------------------
    # Il report persistito è il **documento** di cui il digest è il riassunto: deve esistere prima
    # che parta qualunque email, così un invio rimbalzato non lascia un mese senza rendiconto e il
    # `run` che lo ha prodotto è lo stesso che dichiara `report: {inseriti, gia_esistenti}`.
    # Un fallimento qui ferma il ciclo — i digest di oggi riassumono un report che deve esistere.
    try:
        report_esito = persisti_report(primo, digest, csv_testo, run)
    except FlussoErrore as errore:
        print(f"ciclo_mensile: persistenza report fallita: {errore}", file=sys.stderr)
        run.chiudi("errore", 0, errore=f"persistenza report: {errore}",
                   mese=primo.isoformat())
        registra_run(run)
        return 1
    log(f"report persistiti: {report_esito['inseriti']} inseriti · "
        f"{report_esito['gia_esistenti']} già esistenti (non riscritti)")

    mittente = os.environ.get("TRASI_SMTP_FROM", "trasi@trasi.local")
    recapiti: list[dict] = []
    for messaggio in messaggi_:
        try:
            modo, percorso = _invia(messaggio, mittente)
            recapiti.append({"a": messaggio.a, "modo": modo, "oggetto": messaggio.oggetto,
                             **({"file": percorso} if percorso else {})})
        except FlussoErrore as errore:
            log(f"  {messaggio.a}: invio fallito ({errore})")
            recapiti.append({"a": messaggio.a, "errore": str(errore)})

    esito = "parziale" if any("errore" in r for r in recapiti) else "ok"
    modo = recapiti[0]["modo"] if recapiti and "modo" in recapiti[0] else "?"
    log(f"ciclo mensile {primo.strftime('%m/%Y')}: {len(recapiti)} messaggi via {modo} · "
        f"CSV {righe_csv} righe · esito={esito}")

    run.chiudi(esito, len(recapiti), messaggi=len(recapiti), modo=modo, mese=primo.isoformat(),
               forzato=bool(forza), csv=str(percorso_csv), righe_csv=righe_csv,
               report=report_esito, recapiti=recapiti, campi_v6=list(CAMPI_V6))
    registra_run(run)
    return 0 if esito == "ok" else 1


def main(argv: list[str] | None = None) -> int:
    argomenti = argparse.ArgumentParser(description="F5 · ciclo mensile: digest alle Case e report PN")
    argomenti.add_argument("--mese", help="mese da rendicontare, formato YYYY-MM (default: corrente)")
    argomenti.add_argument("--dry-run", action="store_true", help="mostra cosa invierebbe, non invia")
    argomenti.add_argument("--forza", action="store_true",
                           help="riesegue anche se il ciclo del mese è già stato inviato")
    opzioni = argomenti.parse_args(argv)

    try:
        return esegui(mese=opzioni.mese, dry_run=opzioni.dry_run, forza=opzioni.forza)
    except FlussoErrore as errore:
        print(f"ciclo_mensile: {errore}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
