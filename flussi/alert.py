#!/usr/bin/env python3
"""Trasi — F6 «Alert» (B4-FLW-09) · chi decide, non chi deve fare.

Tre avvisi:

1. **Proposte in attesa** — oltre `[P] gg_attesa_alert` giorni (default 7), al **destinatario
   competente**: il *gestore* della Casa se la proposta è sua (`approvatore_ruolo='gestore'`), altrimenti
   l'*AT*. Include le proposte scadute nelle ultime 24 h, perché una proposta scaduta è una decisione
   che non è stata presa — ed è l'informazione più utile che la coda possa dare.
2. **Coerenza delle fonti** — fonte silente, in errore, con delta anomalo, o dato provvisorio non
   confermato entro la finestra. Va all'AT (è chi governa le fonti, §11).
3. **Eventi con dati mancanti o datati** — da `trasi.v_eventi_dati_mancanti` (evento futuro con campi
   nulli, oppure dato non aggiornato da oltre 2 mesi, motivo `incompleto`|`datato`). Va al **gestore
   della Casa** dell'evento (recapito da `trasi.v_flusso_recapiti`): la scheda è sua e la decisione
   di aggiornarla è sua. **Sola segnalazione**: nessuna scrittura sul dominio, mai — il flusso legge
   la vista e compone l'avviso, punto.
4. **Report osservatorio approvati, non ancora notificati alla PA** — da `trasi.v_report_da_notificare`
   (US-4): il report resta una **bozza** dal ciclo del giorno 3 finché l'operatore referente non lo
   approva dalla dashboard (`trasi.approva_report`, sicurezza definita all'interno del DB); questo
   step avverte il recapito `[P] email_report_pa` che il report approvato **è disponibile nella
   dashboard PA** e marca l'invio con `trasi.marca_report_inviato(id)`. Se il parametro è vuoto, il
   messaggio va su file e la scelta è dichiarata (stessa filosofia degli invii senza SMTP). La vista
   filtra `inviato_pa_ts IS NULL`: un report notificato non viene rinotificato, e l'idempotenza di
   questo avviso è nel **marcatore di stato**, non nel confronto di contenuto.

**V6 — i messaggi dicono chi decide, non impartiscono compiti.** I quattro campi sono *cosa è stato
osservato · su quale evidenza · cosa si potrebbe fare · chi decide*, e nessun verbo imperativo entra
nel testo. Non è una raccomandazione: `verifica_v6()` (in `comune.py`) è un controllo lessicale che i
template di questo file attraversano a ogni invio, e `flussi/tests/test_v6_template.py` lo applica a
tutti i template. Se un template contenesse un verbo imperativo, l'alert **non parte** e il run
finisce in errore: meglio nessun avviso che un avviso che ordina.

**Invio.** SMTP se configurato (`TRASI_SMTP_HOST`), altrimenti **file** in `flussi/evidenze/alert/`:
la scelta è dichiarata nell'output e nel `flusso_run`, mai silenziosa. Il file non è un ripiego
dimenticato: è il modo in cui questa batteria prova il contenuto dei messaggi senza un server di posta.

**V5/§12.** Nessun dato personale nelle email: destinatari di servizio (`…@trasi.local`,
`casa.email_digest`), e i messaggi portano id di proposta, entità e conteggi — mai il testo di una
richiesta, mai un nome.

Uso:
    flussi/alert.py                    # invia (SMTP se configurato, altrimenti su file)
    flussi/alert.py --dry-run          # mostra i messaggi, non invia
    flussi/alert.py --json             # i messaggi come JSON (per i test)
"""

from __future__ import annotations

import argparse
import json
import os
import smtplib
import ssl
import sys
from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage
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
CARTELLA_ALERT = RADICE / "flussi" / "evidenze" / "alert"

#: Giorni oltre i quali una proposta in attesa genera un avviso (§8 F6: «oltre 7 gg»).
GG_ATTESA_DEFAULT = 7


class AlertErrore(FlussoErrore):
    """Errore del flusso di alert."""


# --------------------------------------------------------------------------- modelli


@dataclass
class Messaggio:
    """Un avviso: destinatario, oggetto, e i **quattro campi V6**.

    I campi sono un dizionario e non testo libero perché il controllo V6 deve poterli attraversare
    tutti: un template che nascondesse il verbo imperativo dentro `evidenza` non passerebbe comunque.
    """

    #: La spec chiede «template ≤ 15 righe». Il tetto non è estetico: un avviso che si legge in una
    #: schermata di telefono viene letto, uno che ne occupa tre viene archiviato.
    MAX_RIGHE = 15

    a: str
    oggetto: str
    campi: dict[str, str] = field(default_factory=dict)
    righe: list[str] = field(default_factory=list)
    #: L'id del report, per i messaggi del passo «report osservatorio approvato → PA» (US-4): è
    #: ciò che `marca_report_inviato` riceve dopo l'invio riuscito. Resta `None` per gli altri
    #: avvisi, perché nessun altro messaggio marca una transizione di stato.
    report_id: int | None = None

    def righe_elenco(self) -> list[str]:
        """L'elenco, troncato al numero di righe che lascia il messaggio entro `MAX_RIGHE`.

        Le righe fisse sono: titolo, riga vuota, i 4 campi V6, riga vuota, riga vuota, firma = 10.
        Il resto è spazio per l'elenco; se le voci sono di più, si dichiara quante ne restano —
        un elenco che si interrompe senza dirlo fa credere di averle viste tutte.
        """
        spazio = max(1, self.MAX_RIGHE - 10 - 1)   # -1 per l'eventuale riga «e altre N»
        if len(self.righe) <= spazio:
            return list(self.righe)
        resto = len(self.righe) - spazio
        return [*self.righe[:spazio], f"  · e altre {resto} voci: l'elenco completo è nella coda"]

    def corpo(self) -> str:
        """Il testo del messaggio: quattro campi marcati, poi le righe di dettaglio (≤ 15 righe).

        La forma è quella dell'architettura §2.2 — *osservato / evidenza / possibile azione / chi
        decide* — perché è la struttura che il destinatario legge per decidere, non un elenco.
        """
        righe = [
            "Trasi — avviso automatico della rete delle Case di Quartiere",
            "",
            f"Cosa è stato osservato: {self.campi['cosa_osservato']}",
            f"Su quale evidenza: {self.campi['evidenza']}",
            f"Cosa si potrebbe fare: {self.campi['cosa_si_potrebbe_fare']}",
            f"Chi decide: {self.campi['chi_decide']}",
            "",
            *self.righe_elenco(),
            "",
            "— Messaggio generato dal flusso notturno. Non rispondere a questo indirizzo.",
        ]
        return "\n".join(righe).rstrip() + "\n"

    def verifica(self) -> list[str]:
        """I verbi imperativi presenti nel messaggio (V6). Lista vuota = conforme."""
        return verifica_v6(self.oggetto + "\n" + self.corpo())


# --------------------------------------------------------------------------- composizione


def _proposte_in_attesa(gg: int) -> list[dict]:
    """Le proposte aperte e quelle scadute da poco, con il destinatario già risolto dalla vista."""
    return leggi(
        "SELECT voce, proposta_id, origine, tipo, entita, entita_id, casa_slug, casa_nome, "
        "       approvatore_ruolo, motivazione, giorni, destinatario, destinatario_ruolo "
        "  FROM trasi.v_flusso_alert_proposte "
        f" WHERE (voce = 'in_attesa' AND giorni > {gg}) OR voce = 'scaduta' "
        " ORDER BY destinatario, voce, giorni DESC"
    )


def _coerenza_fonti() -> list[dict]:
    return leggi(
        "SELECT voce, fonte_id, fonte_nome, riferimento, dettaglio, giorni "
        "  FROM trasi.v_flusso_coerenza_fonti ORDER BY voce, fonte_nome"
    )


def _destinatario_at() -> str:
    """L'indirizzo dell'AT (ruolo `rete`), o stringa vuota.

    Si legge da `v_flusso_destinatari` e non da `v_flusso_alert_proposte`: il recapito dell'AT serve
    anche quando la coda è vuota (l'alert di coerenza delle fonti), e legarlo alla coda significava
    che con zero proposte **nessun** avviso partiva. È il difetto emerso alla prima esecuzione.
    """
    righe = leggi(
        "SELECT destinatario FROM trasi.v_flusso_destinatari "
        " WHERE destinatario_ruolo = 'at' AND destinatario IS NOT NULL LIMIT 1"
    )
    return righe[0]["destinatario"] if righe else ""


def messaggi_proposte(gg: int) -> list[Messaggio]:
    """Un messaggio **per destinatario** con le sue proposte: chi decide riceve un solo avviso.

    Raggruppare per destinatario non è un'ottimizzazione: dodici email identiche al giorno sono un
    modo efficace per far ignorare tutte e dodici. Un solo messaggio con l'elenco è un messaggio che
    si legge.
    """
    per_destinatario: dict[str, list[dict]] = {}
    for riga in _proposte_in_attesa(gg):
        destinatario = riga["destinatario"] or _destinatario_at()
        if not destinatario:
            # Senza destinatario la proposta resterebbe invisibile: è un difetto di configurazione
            # (nessuna identità `rete` e nessun `email_digest`) e va dichiarato, non nascosto.
            raise AlertErrore(
                f"proposta {riga['proposta_id']}: nessun destinatario risolvibile "
                "(né gestore con email_digest né identità AT)"
            )
        per_destinatario.setdefault(destinatario, []).append(riga)

    messaggi: list[Messaggio] = []
    for destinatario, righe in sorted(per_destinatario.items()):
        in_attesa = [r for r in righe if r["voce"] == "in_attesa"]
        scadute = [r for r in righe if r["voce"] == "scaduta"]
        ruolo = righe[0]["destinatario_ruolo"]
        case_coinvolte = sorted({r["casa_nome"] for r in righe if r["casa_nome"]})
        pezzi = []
        if in_attesa:
            massimo = max(int(r["giorni"]) for r in in_attesa)
            pezzi.append(f"{len(in_attesa)} in attesa da oltre {gg} giorni (la più vecchia {massimo})")
        if scadute:
            pezzi.append(f"{len(scadute)} scadute nelle ultime 24 ore")
        osservato = "Coda delle proposte: " + " · ".join(pezzi)

        elenco = [
            f"  · proposta {r['proposta_id']} — {r['entita']} "
            f"{r['entita_id'] if r['entita_id'] else ''}".rstrip()
            + f" · {r['casa_nome'] or 'territorio'} · {r['giorni']} giorni"
            + (" · scaduta" if r["voce"] == "scaduta" else "")
            + (f" · {r['motivazione']}" if r["motivazione"] else "")
            for r in sorted(righe, key=lambda x: (-int(x["giorni"]), x["proposta_id"]))
        ]

        messaggi.append(
            Messaggio(
                a=destinatario,
                oggetto=(
                    f"Trasi · {len(in_attesa)} in attesa"
                    + (f" · {len(scadute)} scadute" if scadute else "")
                ),
                campi={
                    "cosa_osservato": osservato,
                    # L'evidenza è la vista da cui i numeri vengono: chi legge può ricontrollarli.
                    "evidenza": (
                        f"vista trasi.v_flusso_alert_proposte · "
                        f"{len(righe)} proposte di {', '.join(case_coinvolte) or 'territorio'}"
                    ),
                    "cosa_si_potrebbe_fare": (
                        "Le proposte si possono approvare o rifiutare dalla coda della propria Casa; "
                        "quelle scadute restano leggibili e una proposta nuova le sostituisce."
                    ),
                    "chi_decide": (
                        f"Il ruolo che decide queste proposte è "
                        f"{('il gestore della Casa' if ruolo.startswith('gestore') else 'l\u2019AT')}."
                        + (
                            " Le proposte già scadute sono quelle non decise entro la finestra di "
                            "validità."
                            if scadute else ""
                        )
                    ),
                },
                righe=elenco,
            )
        )
    return messaggi


def messaggi_coerenza() -> list[Messaggio]:
    """Un solo messaggio all'AT con i quattro esiti di coerenza (§8 F4)."""
    righe = _coerenza_fonti()
    if not righe:
        return []

    destinatario = _destinatario_at()
    if not destinatario:
        raise AlertErrore("coerenza fonti: nessuna identità AT per il recapito")

    per_voce: dict[str, list[dict]] = {}
    for riga in righe:
        per_voce.setdefault(riga["voce"], []).append(riga)

    pezzi = [
        f"{len(v)} {k.replace('_', ' ')}" for k, v in sorted(per_voce.items())
    ]
    elenco = [
        f"  · {r['voce'].replace('_', ' ')} — {r['fonte_nome']}"
        + (f" · {r['riferimento']}" if r["riferimento"] else "")
        + (f" ({r['giorni']} giorni)" if r["giorni"] and r["giorni"] != "0" else "")
        for r in sorted(righe, key=lambda x: (x["voce"], x["fonte_nome"]))[:10]
    ]

    return [
        Messaggio(
            a=destinatario,
            oggetto=f"Trasi · coerenza delle fonti: {', '.join(pezzi)}",
            campi={
                "cosa_osservato": "Stato delle fonti esterne: " + " · ".join(pezzi),
                "evidenza": (
                    "vista trasi.v_flusso_coerenza_fonti, alimentata da trasi.fonte_run "
                    "(una riga per lettura di fonte)"
                ),
                "cosa_si_potrebbe_fare": (
                    "Una fonte silente o in errore si può verificare dall'allow-list; un delta "
                    "anomalo ha già una proposta in coda con il contesto del cambiamento."
                ),
                "chi_decide": (
                    "L'allow-list delle fonti e la loro fiducia sono in mano al TI; le proposte "
                    "di coerenza le decide l’AT."
                ),
            },
            righe=elenco,
        )
    ]


# ------------------------------------------------------------------ eventi: dati mancanti o datati


def _eventi_dati_mancanti() -> list[dict]:
    """Gli eventi futuri con scheda incompleta o non aggiornata, dalla vista di dominio.

    Colonne della vista (db/004_views.sql, confermate da DBA): `evento_id, casa_id, casa_slug,
    titolo, inizio, mancanze text[], motivo`. Il motivo ha **tre** valori: `incompleto`, `datato`,
    `incompleto_e_datato` — il terzo è la congiunzione dei due e va comunicato come entrambi.
    `mancanze` arriva dal CSV come array Postgres testuale (`{descrizione,luogo_testo}`) e si legge
    come elenco di nomi di campo — mai come testo da mostrare così com'è.
    """
    return leggi(
        "SELECT evento_id, casa_slug, titolo, inizio, mancanze, motivo "
        "  FROM trasi.v_eventi_dati_mancanti ORDER BY casa_slug, motivo, titolo"
    )


def _mancanze_elenco(mancanze: str) -> str:
    """`{descrizione,luogo,contatto}` → «descrizione, luogo, contatto»: i nomi dei campi mancanti.

    L'array testuale di Postgres si smonta qui e non in SQL perché il messaggio è una scelta di
    comunicazione del flusso, non della vista: la vista dichiara *quali* campi mancano, il flusso
    decide come dirlo. Nessun campo personale può entrare da qui: sono nomi di colonna dello schema.
    """
    valori = [v.strip().strip('"') for v in mancanze.strip("{}").split(",") if v.strip()]
    return ", ".join(valori) if valori else "informazioni"


def _riga_evento(riga: dict) -> str:
    """La riga V6 del dettaglio: dice lo stato e **chi decide**, mai un compito.

    «Decide la CdQ <slug> se…» è la forma dell'architettura §2.2 — il soggetto della frase è chi
    decide, il verbo è al presente indicativo (dichiara), non all'imperativo (ordina): il presidio
    lessicale `verifica_v6` la lascia passare, e `flussi/tests/test_v6_template.py` lo garantisce a
    ogni giro. Un «aggiorna la scheda» bloccherebbe l'intero alert, com'è giusto che sia.
    """
    if riga["motivo"] == "datato":
        return (
            f"  · La scheda di {riga['titolo']} risulta aggiornata più di 2 mesi fa. "
            f"Decide la CdQ {riga['casa_slug']} se verificarla."
        )
    testo = (
        f"  · La scheda di {riga['titolo']} è incompleta: manca "
        f"{_mancanze_elenco(riga['mancanze'])}."
    )
    if riga["motivo"] == "incompleto_e_datato":
        # La congiunzione dei due motivi: si dicono entrambe le cose, in una riga sola.
        testo = testo.rstrip(".") + ", e risulta aggiornata più di 2 mesi fa."
    return testo + f" Decide la CdQ {riga['casa_slug']} se e quando aggiornarla."


def _conteggi_motivo(eventi: list[dict]) -> tuple[list[dict], list[dict]]:
    """Eventi con campi mancanti e datati, con `incompleto_e_datato` contato in entrambi gli insiemi."""
    incompleti = [e for e in eventi if "incompleto" in e["motivo"]]
    datati = [e for e in eventi if "datato" in e["motivo"]]
    return incompleti, datati


def messaggi_eventi_dati_mancanti() -> list[Messaggio]:
    """Un messaggio **per Casa** con i suoi eventi incompleti o datati: la scheda è sua, decide lei.

    Il recapito si risolve da `trasi.v_flusso_recapiti` — la stessa regola di governance degli altri
    avvisi (email_digest, poi identità gestore, poi AT) scritta una volta sola nel database. Una casa
    senza recapito manda l'avviso all'AT: un evento senza destinatario non deve sparire.
    """
    righe = _eventi_dati_mancanti()
    if not righe:
        return []

    recapiti = {
        r["casa_slug"]: r["destinatario"]
        for r in leggi("SELECT casa_slug, destinatario FROM trasi.v_flusso_recapiti")
        if r["destinatario"]
    }
    at = _destinatario_at()

    per_casa: dict[str, list[dict]] = {}
    for riga in righe:
        per_casa.setdefault(riga["casa_slug"], []).append(riga)

    messaggi: list[Messaggio] = []
    for slug, eventi in sorted(per_casa.items()):
        destinatario = recapiti.get(slug) or at
        if not destinatario:
            raise AlertErrore(
                f"eventi dati mancanti: nessun recapito per la CdQ {slug} e nessuna identità AT"
            )
        incomplete = [e for e in eventi if e["motivo"] == "incompleto"]
        datate = [e for e in eventi if e["motivo"] != "incompleto"]
        pezzi = []
        if incomplete:
            pezzi.append(f"{len(incomplete)} con campi mancanti")
        if datate:
            pezzi.append(f"{len(datate)} non aggiornate da oltre 2 mesi")

        messaggi.append(
            Messaggio(
                a=destinatario,
                oggetto=f"Trasi · schede evento di {slug}: " + " · ".join(pezzi),
                campi={
                    "cosa_osservato": (
                        f"Schede di eventi futuri della CdQ {slug}: " + " · ".join(pezzi)
                    ),
                    "evidenza": (
                        "vista trasi.v_eventi_dati_mancanti: eventi futuri con campi nulli "
                        "oppure dato non aggiornato da oltre 2 mesi"
                    ),
                    "cosa_si_potrebbe_fare": (
                        "Le schede si possono aggiornare dalla coda delle proposte della propria "
                        "Casa; una scheda che resta datata continua a comparire in questo avviso "
                        "fino a quando il dato torna aggiornato."
                    ),
                    "chi_decide": (
                        f"Le schede degli eventi della CdQ {slug} le decide la CdQ {slug}: "
                        "il sistema segnala lo stato e la scelta resta alla Casa."
                    ),
                },
                righe=[_riga_evento(e) for e in eventi],
            )
        )
    return messaggi


# --------------------------------------------------------- report osservatorio approvati → PA (US-4)


def _report_da_notificare() -> list[dict]:
    """I report osservatorio approvati non ancora segnalati alla PA (vista del contract db/031)."""
    return leggi(
        "SELECT id, mese, approvato_ts FROM trasi.v_report_da_notificare ORDER BY mese"
    )


def _recapito_pa() -> str:
    """Il recapito del parametro `[P] email_report_pa`; vuoto = modalità file dichiarata.

    Chiave assente → la funzione SQL del parametro risponde NULL (db/003: nessuna eccezione), e il
    flusso non deve inventare un indirizzo: il file è il modo in cui il messaggio resta leggibile.
    """
    from comune import uno

    return uno("SELECT trasi.p_text('email_report_pa') AS v", "v").strip()


def messaggi_report_pa() -> list[Messaggio]:
    """Un messaggio per report approvato: «è disponibile nella dashboard PA». Chi decide ha deciso.

    Il destinatario è il recapito del parametro dedicato — non `v_flusso_destinatari`: altrimenti
    l'avviso arriverebbe all'AT, che è **chi ha approvato** e non chi deve sapere. Con parametro
    vuoto il messaggio è comunque composto e va su **file**: il run dichiara il modo, non lo nasconde,
    e `marca_report_inviato` scatta lo stesso — un report che non compare più in vista perché
    marcato non deve rinotificarsi ogni mattina in attesa di un recapito.
    """
    da_notificare = _report_da_notificare()
    if not da_notificare:
        return []
    destinatario = _recapito_pa()  # vuoto → il ramo d'invio scrive su file e lo dichiara

    messaggi: list[Messaggio] = []
    for riga in da_notificare:
        mese = str(riga["mese"])[:7]  # '2026-09-01' → '2026-09'
        messaggi.append(
            Messaggio(
                a=destinatario,
                report_id=int(riga["id"]),
                oggetto=f"Trasi · report osservatorio {mese} approvato — disponibile in dashboard PA",
                campi={
                    "cosa_osservato": (
                        f"Il report mensile dell'osservatorio di rete del mese {mese} risulta "
                        "approvato dall'operatore referente ed è consultabile nella dashboard PA."
                    ),
                    "evidenza": (
                        "vista trasi.v_report_da_notificare: report di ambito osservatorio con "
                        f"stato «approvato» (approvato il {str(riga['approvato_ts'])[:10]})"
                    ),
                    "cosa_si_potrebbe_fare": (
                        "Il report è leggibile nella dashboard PA e da lì si può esportare in un "
                        "documento stampabile; la lettura di approfondimento resta disponibile "
                        "dalla stessa pagina."
                    ),
                    "chi_decide": (
                        "L'approvazione del report è dell'operatore referente della rete; la "
                        "pubblicazione e l'uso del dato restano alla PA."
                    ),
                },
                righe=[(f"  · report osservatorio {mese}: leggibile nella dashboard PA, "
                        "con i conteggi già k-anonimi")],
            )
        )
    return messaggi


def marca_report_inviato(id_report: int) -> None:
    """Segna la notifica avvenuta: `trasi.marca_report_inviato` (SECURITY DEFINER, con audit).

    Mai `UPDATE` diretto su `trasi.report`: UPDATE non è grantato per costruzione (db/024, il report
    non si corregge) e la transizione di stato è un atto tracciato, non un campo che un flusso
    riscrive. È lo stesso criterio per cui lo stato `approvato` lo scrive `trasi.approva_report`.
    """
    esegui_sql(f"SELECT trasi.marca_report_inviato({int(id_report)})\n")


# --------------------------------------------------------------------------- invio


def _config_smtp() -> tuple[str, int, str, str] | None:
    """`(host, porta, utente, password)` se SMTP è configurato, altrimenti `None`.

    La password si legge da `deployment/.env` o dall'ambiente, mai da un argomento della riga di
    comando (che finirebbe nella history e in `ps`).
    """
    host = os.environ.get("TRASI_SMTP_HOST", "").strip()
    if not host:
        return None
    porta = int(os.environ.get("TRASI_SMTP_PORT", "25") or 25)
    utente = os.environ.get("TRASI_SMTP_USER", "").strip()
    password = os.environ.get("TRASI_SMTP_PASSWORD", "").strip()
    return host, porta, utente, password


def invia_smtp(messaggio: Messaggio, mittente: str, config: tuple[str, int, str, str]) -> None:
    host, porta, utente, password = config
    email = EmailMessage()
    email["From"] = mittente
    email["To"] = messaggio.a
    email["Subject"] = messaggio.oggetto
    email.set_content(messaggio.corpo().encode("utf-8"), charset="utf-8", cte="base64")

    try:
        if porta == 465:
            with smtplib.SMTP_SSL(host, porta, timeout=10, context=ssl.create_default_context()) as s:
                if utente:
                    s.login(utente, password)
                s.send_message(email)
        else:
            with smtplib.SMTP(host, porta, timeout=10) as s:
                if utente:
                    s.starttls(context=ssl.create_default_context())
                    s.login(utente, password)
                s.send_message(email)
    except (smtplib.SMTPException, OSError) as errore:
        raise AlertErrore(f"invio SMTP a {messaggio.a} fallito: {errore}") from errore


def invia_file(messaggio: Messaggio, quando: datetime) -> Path:
    """Scrive il messaggio su file: la modalità dei test e dei run senza SMTP, dichiarata in output."""
    CARTELLA_ALERT.mkdir(parents=True, exist_ok=True)
    # Un file per messaggio e per run: due run non si sovrascrivono, e l'evidenza di ieri resta.
    nome = f"{quando.strftime('%Y%m%dT%H%M%S')}__{messaggio.a.replace('@', '_at_')}.eml"
    percorso = CARTELLA_ALERT / nome
    percorso.write_text(
        f"To: {messaggio.a}\nSubject: {messaggio.oggetto}\n\n{messaggio.corpo()}", encoding="utf-8"
    )
    return percorso


# --------------------------------------------------------------------------- main


def _impronta(messaggio: Messaggio) -> str:
    """L'impronta del **contenuto** di un avviso: destinatario, oggetto e dettaglio.

    Non è un hash dell'ora né del testo completo (che contiene la data di oggi e cambierebbe ogni
    giorno): è l'insieme di ciò che dice *cosa è cambiato*. Due esecuzioni con la stessa situazione
    producono la stessa impronta, e l'avviso si sopprime; se la situazione cambia di una sola voce,
    l'impronta cambia e l'avviso riparte.
    """
    import hashlib

    materiale = json.dumps(
        {"a": messaggio.a, "oggetto": messaggio.oggetto, "righe": messaggio.righe},
        ensure_ascii=False, sort_keys=True,
    )
    return hashlib.sha256(materiale.encode("utf-8")).hexdigest()[:16]


def _ultime_impronte() -> dict[str, dict]:
    """L'impronta dell'ultimo invio **riuscito** per destinatario, dal registro `flusso_run`.

    Si legge dal registro dei flussi e non da una tabella nuova: l'informazione «cosa ho già
    mandato» è già lì, e una tabella in più sarebbe un secondo posto da tenere allineato.
    Se il registro non è raggiungibile si ritorna vuoto: in quel caso si invia (un avviso in più
    è meglio di un avviso perso).
    """
    from comune import esegui_sql

    try:
        grezzo = esegui_sql(
            """
            SELECT coalesce(dettaglio -> 'recapiti', 'null'::jsonb)::text
              FROM trasi.flusso_run
             WHERE nome = 'alert' AND esito = 'ok' AND dettaglio ? 'recapiti'
             ORDER BY id DESC LIMIT 1
            """
        )
    except Exception:
        return {}

    # `psql -t -A` stampa una riga per riga: si prende la prima non vuota.
    for riga in grezzo.splitlines():
        riga = riga.strip()
        if not riga or riga == "null":
            continue
        try:
            recapiti = json.loads(riga)
        except json.JSONDecodeError:
            continue
        if not isinstance(recapiti, list):
            continue
        ultime: dict[str, dict] = {}
        for r in recapiti:
            if isinstance(r, dict) and r.get("a") and r.get("impronta"):
                ultime[r["a"]] = r
        return ultime
    return {}


def esegui(*, dry_run: bool, giorni: int | None = None, come_json: bool = False) -> int:
    run = apri_run("alert")
    gg = giorni if giorni is not None else parametro_int("gg_attesa_alert", GG_ATTESA_DEFAULT)
    mittente = os.environ.get("TRASI_SMTP_FROM", "trasi@trasi.local")

    try:
        messaggi_pa = [] if dry_run else messaggi_report_pa()
        messaggi = messaggi_proposte(gg) + messaggi_coerenza() + messaggi_eventi_dati_mancanti()
    except FlussoErrore as errore:
        # L'errore va **anche su stderr**, non solo in `flusso_run`: un run che fallisce senza dire
        # perché è un run che nessuno ripara (successo davvero, alla prima esecuzione di questo file).
        print(f"alert: {errore}", file=sys.stderr)
        run.chiudi("errore", 0, errore=str(errore))
        registra_run(run)
        return 1

    # --- il presidio V6, prima di qualunque invio ------------------------------------------
    # Se un template contenesse un verbo imperativo, l'alert non parte. Un avviso che impartisce
    # viola V6, e V6 è un invariante: meglio nessun avviso (e un run in errore, che qualcuno vedrà)
    # che un avviso che dice a una Casa cosa deve fare. Vale anche per la notifica alla PA: il
    # presidio non conosce eccezioni di destinatario.
    violazioni: list[str] = []
    for messaggio in messaggi + messaggi_pa:
        trovati = messaggio.verifica()
        if trovati:
            violazioni.append(f"{messaggio.oggetto}: {', '.join(trovati)}")

    if violazioni:
        run.chiudi("errore", 0, v6_violato=violazioni)
        registra_run(run)
        for violazione in violazioni:
            print(f"V6 violato — {violazione}", file=sys.stderr)
        return 1

    if come_json:
        print(json.dumps(
            [{"a": m.a, "oggetto": m.oggetto, "campi": m.campi, "corpo": m.corpo(),
              "righe": len(m.corpo().splitlines())} for m in messaggi],
            ensure_ascii=False, indent=2,
        ))

    if dry_run:
        log(f"dry-run: {len(messaggi)} messaggi pronti ({sum(len(m.righe) for m in messaggi)} righe di dettaglio)")
        for messaggio in messaggi:
            log(f"  → {messaggio.a}: {messaggio.oggetto}")
        run.chiudi("ok", 0, dry_run=True, messaggi=len(messaggi))
        registra_run(run)
        return 0

    config = _config_smtp()
    modo = "smtp" if config else "file"
    quando = datetime.now()
    recapiti: list[dict] = []

    # --- notifica dei report osservatorio approvati alla PA (US-4) ---------------------------
    # Il messaggio va al recapito `[P] email_report_pa`; con il parametro vuoto il messaggio va su
    # **file**, perché il messaggio esiste anche senza un indirizzo e il run dichiara il modo. La
    # marcatura (`marca_report_inviato`) segue l'invio riuscito: la vista `v_report_da_notificare`
    # filtra `inviato_pa_ts IS NULL`, quindi un report notificato non torna più in elenco — e
    # l'idempotenza è nel marcatore di stato, non nel confronto del contenuto.
    pa_dettaglio = {"notificati": 0, "report": []}
    if messaggi_pa:
        for messaggio in messaggi_pa:
            recapito = {"a": messaggio.a or "(file: parametro email_report_pa vuoto)",
                        "oggetto": messaggio.oggetto,
                        "impronta": _impronta(messaggio)}
            try:
                if config and messaggio.a:
                    invia_smtp(messaggio, mittente, config)
                    recapito["modo"] = "smtp"
                else:
                    percorso = invia_file(messaggio, quando)
                    recapito["modo"] = "file"
                    recapito["file"] = str(percorso)
            except FlussoErrore as errore:
                log(f"  notifica PA «{messaggio.oggetto}»: invio fallito ({errore})")
                recapito["errore"] = str(errore)
            else:
                pa_dettaglio["notificati"] += 1
                # Invio riuscito: la marcatura chiude il ciclo. Se la funzione SQL mancasse (db/031
                # non ancora applicato) l'errore ferma il run: un report *notificato ma non marcato*
                # ripartirebbe a ogni esecuzione, e questo è un guasto da vedere, non da tacere.
                if messaggio.report_id is not None:
                    marca_report_inviato(messaggio.report_id)
            pa_dettaglio["report"].append(recapito)

    esito_pa_errore = any("errore" in r for r in pa_dettaglio["report"])

    # --- deduplicazione: lo stesso avviso non parte due volte -------------------------------
    # Un gestore che riceve «1 proposta in attesa» ogni mattina per la stessa proposta smette di
    # leggere gli avvisi — e la coda resta ignorata, che è il rischio §13 più probabile di questo
    # sistema. Si sopprime l'invio quando **il contenuto è identico** all'ultimo invio riuscito
    # per lo stesso destinatario: se la situazione cambia (una proposta in più, una in meno, un
    # conteggio diverso), l'impronta cambia e l'avviso riparte.
    #
    # Il confronto è con l'ultimo invio **riuscito** (`esito` non in errore): un invio fallito non
    # deve sopprimere il successivo, altrimenti l'avviso non arriverebbe mai.
    precedenti = _ultime_impronte()
    da_inviare: list[Messaggio] = []
    soppressi: list[dict] = []
    for messaggio in messaggi:
        impronta = _impronta(messaggio)
        precedente = precedenti.get(messaggio.a)
        if precedente and precedente.get("impronta") == impronta:
            soppressi.append({"a": messaggio.a, "oggetto": messaggio.oggetto,
                              "motivo": "contenuto identico all'ultimo invio riuscito"})
            continue
        da_inviare.append(messaggio)

    for messaggio in da_inviare:
        try:
            if config:
                invia_smtp(messaggio, mittente, config)
                recapiti.append({"a": messaggio.a, "modo": "smtp", "oggetto": messaggio.oggetto,
                                 "impronta": _impronta(messaggio)})
            else:
                percorso = invia_file(messaggio, quando)
                recapiti.append({"a": messaggio.a, "modo": "file", "file": str(percorso),
                                 "oggetto": messaggio.oggetto, "impronta": _impronta(messaggio)})
        except FlussoErrore as errore:
            log(f"  {messaggio.a}: invio fallito ({errore})")
            recapiti.append({"a": messaggio.a, "modo": modo, "errore": str(errore)})

    esito = "parziale" if (any("errore" in r for r in recapiti) or esito_pa_errore) else "ok"
    log(f"alert: {len(recapiti)} messaggi via {modo} · {len(soppressi)} soppressi (già inviati) · "
        f"report PA notificati: {pa_dettaglio['notificati']}/{len(messaggi_pa)} · "
        f"giorni_attesa={gg} · esito={esito}")
    for recapito in recapiti:
        log(f"  → {recapito['a']} ({recapito['modo']}): {recapito['oggetto']}")
    for s in soppressi:
        log(f"  · {s['a']}: soppresso ({s['motivo']})")

    run.chiudi(esito, len(recapiti) + pa_dettaglio["notificati"],
               modo=modo, giorni_attesa=gg, recapiti=recapiti,
               report_pa=pa_dettaglio, soppressi=soppressi, campi_v6=list(CAMPI_V6))
    registra_run(run)
    return 0 if esito == "ok" else 1


def main(argv: list[str] | None = None) -> int:
    argomenti = argparse.ArgumentParser(description="F6 · alert delle proposte in attesa e delle fonti")
    argomenti.add_argument("--dry-run", action="store_true", help="mostra i messaggi, non invia")
    argomenti.add_argument("--json", action="store_true", help="stampa i messaggi come JSON")
    argomenti.add_argument("--giorni", type=int, default=None,
                           help=f"soglia di attesa in giorni (default [P] o {GG_ATTESA_DEFAULT})")
    opzioni = argomenti.parse_args(argv)

    try:
        return esegui(dry_run=opzioni.dry_run, giorni=opzioni.giorni, come_json=opzioni.json)
    except FlussoErrore as errore:
        print(f"errore: {errore}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
