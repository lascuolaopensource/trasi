#!/usr/bin/env python3
"""Trasi — F4 «Fonti iCal» (B4-FLW-06) · **l'unica scrittura diretta al dominio ammessa**.

Perché è un'eccezione e non una violazione di V4. Un calendario è dato *già pubblicato* dalla Casa:
rifarlo passare da una coda di approvazione significherebbe che un evento di domani non è visibile in
chat finché qualcuno non apre la coda. L'architettura §8 F4 ammette quindi l'upsert diretto **a tre
condizioni**, tutte implementate qui e tutte verificate dai test:

1. la fonte deve avere `tipo_accesso='ical'` — lo impone la policy `ev_ical_*` di `db/005`, non la
   buona volontà di questo script;
2. **mai `DELETE`**: un evento rimosso a monte diventa `annullato=true` (§8 F4). La riga resta;
3. **una riga `audit` per variazione** (`azione='ical_upsert'`, `prima`/`dopo`), scritta dal trigger
   `evento_ical_01_audit`. Il trigger riconosce il percorso da `session_user='automazioni'`: per questo
   il flusso si **connette** come `automazioni` e non fa `SET ROLE` (che lascerebbe `session_user`
   all'utente di login e sopprimerebbe l'audit in silenzio).

**Delta anomalo (§8 F4, regola 4).** Se il feed cambia oltre soglia il flusso **non applica**:
segnala. Un calendario che perde l'80% degli eventi non è «il calendario aggiornato», è un feed rotto
o svuotato: applicarlo cancellerebbe la memoria della rete su un errore di rete. In quel caso il
flusso crea una `proposta` (`origine='coerenza'`, decide l'AT) e registra `fonte_run.esito='anomalo'`.

**V5/§12.** Si importano `SUMMARY`, `DTSTART`/`DTEND`, `LOCATION`, `URL`. **Mai** `ATTENDEE`,
`ORGANIZER`, `DESCRIPTION`: i primi due sono dati personali di persone terze, il terzo è testo libero
in cui possono finire nomi e contatti (l'invito di un incontro li contiene quasi sempre). Il parser
**non li legge affatto** — non è un filtro applicato a valle, è un'assenza: un campo che non viene
letto non può finire in memoria. `test_v5_nessun_campo_personale` lo verifica sul testo del file.

Uso:
    flussi/fonti_ical.py                       # feed da `--ics` o dalla fixture
    flussi/fonti_ical.py --ics feed.ics --casa bozzano --fonte "Google Calendar-ical-2"
    flussi/fonti_ical.py --dry-run             # calcola il delta e stampa, non scrive
    flussi/fonti_ical.py --reset               # rimarca nulla: azzera la fixture (solo per i test)

Configurazione (nessun segreto in questo file):
    TRASI_ICAL_FIXTURE   percorso della fixture ICS (default `flussi/fixtures/casa.ics`)
    TRASI_ICAL_CASA      slug della Casa (default `bozzano`)
    TRASI_ICAL_FONTE     nome della fonte nella allow-list (default `Google Calendar-ical-2`)
    TRASI_ICAL_URL       URL del feed reale; se assente si usa la fixture e lo si dichiara
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from comune import (  # noqa: E402
    MOTIVAZIONE_MAX,
    FlussoErrore,
    apri_run,
    esegui_sql,
    leggi,
    log,
    motivazione,
    parametro_int,
    registra_fonte_run,
    registra_run,
)

RADICE = Path(__file__).resolve().parent.parent
FIXTURE = RADICE / "flussi" / "fixtures" / "casa.ics"

#: User-Agent identificativo. Le fonti `.it` e gli endpoint pubblici rispondono 403 a un UA generico
#: (lezione di B0 su Overpass, `docs/verifiche.md`): non è cortesia, è la differenza fra 200 e 403.
UA = "Trasi/0.1 (portierato di quartiere Brindisi; +https://trasi.lascuolaopensource.org)"

TIMEOUT_S = 10
#: Finestra di importazione (§8 F4): un giorno indietro (gli eventi in corso), 90 avanti.
GIORNI_INDIETRO, GIORNI_AVANTI = 1, 90


class IcalErrore(FlussoErrore):
    """Errore del flusso iCal."""


# --------------------------------------------------------------------------- letura del feed


def _srotola(testo: str) -> str:
    """Rimuove il *folding* di RFC 5545: le righe continuate iniziano con spazio o tabulazione."""
    return re.sub(r"\r?\n[ \t]", "", testo)


def _parse_dt(valore: str) -> datetime | None:
    """`DTSTART`/`DTEND` → datetime con fuso, da un feed ICS **o** dal database.

    Tre forme ricorrono nei feed reali: `20260920T180000Z` (UTC), `20260920T180000` (**ora locale**,
    che senza `VTIMEZONE` non è interpretabile e si assume Europe/Rome), e `20260920` (tutto il
    giorno). L'ora locale è una scelta dichiarata: leggere `20260920T180000` come UTC sposterebbe ogni
    evento di due ore, e un orario sbagliato in chat è peggio di un orario assente.

    Le ultime due forme arrivano dal database, dove `to_char(…, 'OF')` produce un offset **senza
    due punti** (`+02`, `+02:30`): `%z` di Python vuole `+0200`/`+02:00`. La normalizzazione è qui e
    non nel SQL perché è una differenza fra due convenzioni, non una scelta di formato.
    """
    valore = valore.strip()
    if not valore:
        return None
    for formato, con_fuso in (("%Y%m%dT%H%M%SZ", True), ("%Y%m%dT%H%M%S", False), ("%Y%m%d", False)):
        try:
            momento = datetime.strptime(valore, formato)
        except ValueError:
            continue
        return momento.replace(tzinfo=timezone.utc if con_fuso else ZONA)

    # Forme ISO con offset (dal database). `fromisoformat` in 3.11+ gestisce `+02:00`; per `+02`
    # si normalizza prima, perché è esattamente il caso che PostgreSQL produce con `OF`.
    for candidato in (valore, re.sub(r"([+-]\d{2})$", r"\1:00", valore)):
        try:
            momento = datetime.fromisoformat(candidato)
        except ValueError:
            continue
        return momento if momento.tzinfo else momento.replace(tzinfo=ZONA)
    return None


#: Fuso della rete. `zoneinfo` è stdlib e il database dell'host ha Europe/Rome.
try:
    from zoneinfo import ZoneInfo

    ZONA = ZoneInfo("Europe/Rome")
except Exception:  # pragma: no cover - solo su host senza tzdata
    ZONA = timezone(timedelta(hours=2))


@dataclass
class Evento:
    """Un evento del feed, **ridotto ai soli campi non personali** (V5/§12).

    I campi sono quattro perché quattro sono quelli ammessi: `ATTENDEE`, `ORGANIZER` e `DESCRIPTION`
    non hanno una variabile che li raccolga. Questa assenza è la difesa, non un filtro successivo.
    """

    uid: str
    titolo: str
    inizio: datetime
    fine: datetime | None = None
    luogo_testo: str = ""
    url: str = ""

    def chiave(self) -> tuple:
        """La forma che rende l'upsert idempotente: `(uid, titolo, inizio, fine, luogo, url)`."""
        return (self.uid, self.titolo, self.inizio, self.fine, self.luogo_testo, self.url)


def _valore(blocco: str, campo: str) -> str:
    """Il valore di un campo ICS, con i parametri (`DTSTART;TZID=…:`) rimossi dal nome."""
    riscontro = re.search(rf"^{re.escape(campo)}[^:\r\n]*:(.*)$", blocco, re.MULTILINE)
    return riscontro.group(1).strip() if riscontro else ""


def _desescapa(testo: str) -> str:
    """Sequenze di escape di RFC 5545 (`\\,` `\\;` `\\n`)."""
    return (testo.replace("\\n", " ").replace("\\N", " ")
                 .replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")).strip()


def leggi_ics(testo: str) -> list[Evento]:
    """Gli eventi di un feed ICS, già ridotti ai campi ammessi e filtrati alla finestra.

    Si legge per blocchi `BEGIN:VEVENT … END:VEVENT` e si estraggono **solo** i quattro campi ammessi.
    Un feed che porti `ATTENDEE` non lo fa entrare: non c'è codice che lo legga.
    """
    testo = _srotola(testo)
    adesso = datetime.now(ZONA)
    dal = adesso - timedelta(days=GIORNI_INDIETRO)
    al = adesso + timedelta(days=GIORNI_AVANTI)

    eventi: list[Evento] = []
    for blocco in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", testo, re.DOTALL):
        uid = _valore(blocco, "UID")
        inizio = _parse_dt(_valore(blocco, "DTSTART"))
        if not uid or inizio is None:
            # Un evento senza chiave o senza inizio non è importabile: senza `uid` l'upsert non è
            # idempotente, senza `inizio` la riga non ha senso. Si scarta e si conta (vedi `scartati`).
            continue
        if not (dal <= inizio <= al):
            continue
        eventi.append(
            Evento(
                uid=uid,
                titolo=_desescapa(_valore(blocco, "SUMMARY")) or "(senza titolo)",
                inizio=inizio,
                fine=_parse_dt(_valore(blocco, "DTEND")),
                luogo_testo=_desescapa(_valore(blocco, "LOCATION")),
                url=_valore(blocco, "URL"),
            )
        )
    return eventi


def scarica(url: str) -> tuple[str, str]:
    """Il testo del feed e il suo sha256. Mai un errore silenzioso: senza feed si esce con esito `errore`."""
    richiesta = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/calendar,*/*"})
    try:
        with urllib.request.urlopen(richiesta, timeout=TIMEOUT_S) as risposta:
            testo = risposta.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as errore:
        raise IcalErrore(f"feed iCal {url} → HTTP {errore.code}") from errore
    except (urllib.error.URLError, TimeoutError) as errore:
        raise IcalErrore(f"feed iCal {url} irraggiungibile: {errore}") from errore
    return testo, hashlib.sha256(testo.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- stato del database


@dataclass
class Contesto:
    """Fonte e Casa risolte, più lo stato attuale degli eventi iCal di quella Casa."""

    fonte_id: int
    casa_id: int
    casa_slug: str
    fonte_nome: str
    esistenti: dict[str, tuple] = field(default_factory=dict)

    @classmethod
    def risolvi(cls, casa_slug: str, fonte_nome: str) -> "Contesto":
        righe = leggi(
            "SELECT f.id AS fonte_id, c.id AS casa_id, c.slug AS casa_slug, f.nome AS fonte_nome, "
            "       f.tipo_accesso "
            "  FROM trasi.fonte f, trasi.casa c "
            f" WHERE f.nome = {_lit(fonte_nome)} AND c.slug = {_lit(casa_slug)}"
        )
        if not righe:
            raise IcalErrore(
                f"fonte {fonte_nome!r} o Casa {casa_slug!r} non in allow-list: "
                "una fonte fuori allow-list non si importa (§3)"
            )
        riga = righe[0]
        # L'eccezione iCal vale per `tipo_accesso='ical'`. Il controllo è anche nella policy
        # `ev_ical_ins/upd`; qui si anticipa, per dare un errore leggibile invece di un 42501.
        if riga["tipo_accesso"] != "ical":
            raise IcalErrore(
                f"la fonte {fonte_nome!r} ha tipo_accesso={riga['tipo_accesso']!r}: solo le fonti "
                "`ical` possono scrivere `evento` direttamente (§8 F4). Le altre passano da `proposta`."
            )
        contesto = cls(
            fonte_id=int(riga["fonte_id"]),
            casa_id=int(riga["casa_id"]),
            casa_slug=riga["casa_slug"],
            fonte_nome=riga["fonte_nome"],
        )
        contesto.esistenti = contesto.eventi_ical()
        return contesto

    def eventi_ical(self) -> dict[str, tuple]:
        """Gli eventi **della fonte iCal** di questa Casa, per `uid`: `uid → (id, chiave, annullato)`.

        Si filtra per `uid_ical IS NOT NULL`: gli eventi inseriti a mano (o da altre fonti) non sono
        di questo flusso e non devono né essere confrontati né essere marcati rimossi.

        Le date escono in **ISO 8601 esplicito** (`YYYY-MM-DDTHH:MI:SS+TZ`): è lo stesso formato che
        produce `datetime.isoformat()` dal feed, quindi il confronto fra il valore in memoria e quello
        del feed è un confronto fra stringhe equivalenti e non dipende dal `DateStyle` della sessione.
        Senza `to_char`, un `DataStyle` diverso produrrebbe un `prima`/`dopo` che «sembra cambiato»
        a ogni notte e l'upsert riscriverebbe tutto — cioè l'idempotenza cadrebbe per un dettaglio di
        formattazione.
        """
        iso = "YYYY-MM-DD\"T\"HH24:MI:SSOF"
        righe = leggi(
            "SELECT id, uid_ical, titolo, "
            f"       to_char(inizio, '{iso}') AS inizio, "
            f"       to_char(fine,   '{iso}') AS fine, "
            "       COALESCE(luogo_testo, '') AS luogo_testo, COALESCE(url, '') AS url, annullato "
            "  FROM trasi.evento "
            f" WHERE casa_id = {self.casa_id} AND uid_ical IS NOT NULL "
            f"   AND fonte_id = {self.fonte_id}"
        )
        risultato: dict[str, tuple] = {}
        for riga in righe:
            momento = _parse_dt(riga["inizio"])
            if momento is None:
                continue
            risultato[riga["uid_ical"]] = (
                int(riga["id"]),
                (riga["uid_ical"], riga["titolo"], momento, _parse_dt(riga["fine"]),
                 riga["luogo_testo"], riga["url"]),
                riga["annullato"] == "t",
            )
        return risultato


def _lit(testo: str) -> str:
    """Un letterale SQL. Usato **solo** per valori di configurazione (nome fonte, slug Casa) che
    arrivano da variabili d'ambiente o da argomenti della riga di comando — mai da una pagina web o
    da un feed. Gli apostrofi si raddoppiano."""
    return "'" + str(testo).replace("'", "''") + "'"


# --------------------------------------------------------------------------- scritture


def upsert_evento(contesto: Contesto, evento: Evento) -> str:
    """Scrive un evento: `'nuovo'`, `'aggiornato'`, o `''` se il feed non è cambiato.

    `INSERT … ON CONFLICT (casa_id, uid_ical) DO UPDATE … WHERE <cambiato>` è una sola istruzione:
    due richieste concorrenti non possono inserire due righe per lo stesso `uid` (l'UNIQUE
    `evento_casa_uid_ical_uq` è la garanzia, non il codice), e — decisivo per l'idempotenza — un
    evento già identico **non viene riscritto affatto**.

    La clausola `WHERE` sul `DO UPDATE` è ciò che distingue «l'upsert non fa danno» da «l'upsert non
    ha fatto nulla»: senza, ogni notte riscriverebbe tutti gli eventi e il trigger
    `evento_ical_01_audit` produrrebbe una riga `ical_upsert` per ognuno, rendendo impossibile
    distinguere «il calendario è cambiato» da «è passata la notte». Il criterio del blocco chiede la
    seconda: rerun identico → 0 righe di audit nuove.
    """
    nuovo = _sql_valori(evento, contesto)
    sql = (
        "INSERT INTO trasi.evento "
        "(casa_id, titolo, inizio, fine, luogo_testo, uid_ical, url, annullato, fonte_id, affidabilita) "
        f"VALUES {nuovo} "
        "ON CONFLICT (casa_id, uid_ical) DO UPDATE SET "
        "  titolo = EXCLUDED.titolo, inizio = EXCLUDED.inizio, fine = EXCLUDED.fine, "
        "  luogo_testo = EXCLUDED.luogo_testo, url = EXCLUDED.url, annullato = false, "
        "  fonte_id = EXCLUDED.fonte_id, affidabilita = EXCLUDED.affidabilita "
        "WHERE (trasi.evento.titolo, trasi.evento.inizio, trasi.evento.fine, "
        "       trasi.evento.luogo_testo, trasi.evento.url, trasi.evento.annullato) "
        "   IS DISTINCT FROM "
        "      (EXCLUDED.titolo, EXCLUDED.inizio, EXCLUDED.fine, EXCLUDED.luogo_testo, "
        "       EXCLUDED.url, false) "
        "RETURNING (xmax = 0) AS inserito\n"
    )
    uscita = esegui_sql(sql)
    righe = [r.strip() for r in uscita.splitlines() if r.strip() in ("t", "f")]
    if not righe:
        # Nessuna riga: il `DO UPDATE … WHERE` non è scattato → l'evento è già identico in memoria.
        return ""
    return "nuovo" if righe[0] == "t" else "aggiornato"


def _sql_valori(evento: Evento, contesto: Contesto) -> str:
    """I valori dell'`INSERT`, con i datetime come letterali `timestamptz` espliciti.

    `format('%s')` del datetime userebbe il formato del database; `isoformat()` con l'offset è
    esplicito e non dipende da un `DateStyle` che qualcun altro potrebbe cambiare.
    """
    fine = f"'{evento.fine.isoformat()}'::timestamptz" if evento.fine else "NULL"
    return (
        f"({contesto.casa_id}, {_lit(evento.titolo)}, '{evento.inizio.isoformat()}'::timestamptz, "
        f"{fine}, {_lit(evento.luogo_testo)}, {_lit(evento.uid)}, {_lit(evento.url)}, false, "
        f"{contesto.fonte_id}, 2)"
    )


def annulla_eventi(contesto: Contesto, uid: list[str]) -> int:
    """Marca `annullato=true` gli eventi spariti dal feed. **Mai `DELETE`** (§8 F4, V4 regola 7).

    L'evento resta in memoria: «la Casa aveva in programma X e non c'è più» è informazione, e una
    riga cancellata non la porta. `annullato=true` esce dalle viste (`v_kb_export` filtra
    `annullato = false`) senza perdere la storia.
    """
    if not uid:
        return 0
    elenco = ", ".join(_lit(u) for u in uid)
    uscita = esegui_sql(
        "UPDATE trasi.evento SET annullato = true "
        f" WHERE casa_id = {contesto.casa_id} AND fonte_id = {contesto.fonte_id} "
        f"   AND annullato = false AND uid_ical IN ({elenco})\n"
    )
    riscontro = re.search(r"UPDATE (\d+)", uscita)
    return int(riscontro.group(1)) if riscontro else 0


def crea_proposta_anomalia(contesto: Contesto, dettaglio: dict) -> int | None:
    """La segnalazione di delta anomalo: una `proposta` `origine='coerenza'`, non una scrittura.

    Il flusso **non applica** il delta e chiede all'AT di decidere: «il calendario della Casa è
    cambiato oltre soglia» non è una modifica da approvare, è una domanda («è una riorganizzazione o
    un feed rotto?»). Il testo sta in `motivazione` (≤ 80 char, §12) e il contesto in `payload`.
    """
    testo = motivazione(
        f"Calendario {contesto.casa_slug}: {dettaglio['nuovi']} nuovi e {dettaglio['rimossi']} "
        f"rimossi su {dettaglio['esistenti']} ({dettaglio['pct']}% > {dettaglio['soglia']}%): "
        "possibile feed rotto o riorganizzazione"
    )[:MOTIVAZIONE_MAX]

    uscita = esegui_sql(
        "INSERT INTO trasi.proposta "
        "(origine, tipo, entita, casa_id, fonte_id, payload, motivazione) "
        "VALUES ('coerenza', 'modifica_evento', 'evento', "
        f"        {contesto.casa_id}, {contesto.fonte_id}, "
        f"        jsonb_build_object('anomalo', true, "
        f"                          'nuovi', {dettaglio['nuovi']}, "
        f"                          'rimossi', {dettaglio['rimossi']}, "
        f"                          'esistenti', {dettaglio['esistenti']}, "
        f"                          'pct_variazione', {dettaglio['pct']}, "
        f"                          'soglia_pct', {dettaglio['soglia']}, "
        f"                          'feed', {_lit(dettaglio['feed'])}), "
        f"        {_lit(testo)}) "
        "RETURNING id\n"
    )
    # `-tA` non è disponibile nella forma usata: si legge l'id dalle righe di output di psql.
    righe = [r.strip() for r in uscita.splitlines() if r.strip().isdigit()]
    return int(righe[0]) if righe else None


# --------------------------------------------------------------------------- main


def _soglia(contesto: Contesto) -> int:
    """Soglia di delta anomalo, in percentuale. `[P]` se configurata, altrimenti 50.

    Il 50% non è arbitrario: un calendario che cambia metà dei propri eventi in un giorno è più
    probabilmente un feed riscritto che un mese di attività raddoppiato. Il parametro è nuovo e la
    batteria B1 fissa il numero dei parametri a 10: la riga si aggiunge quando `ti` vuole
    (solo `ti` scrive `parametro`) e questo codice la rispetta senza modifiche.
    """
    return max(1, min(100, parametro_int("soglia_delta_anomalo_pct", 50)))


def esegui(fonte_nome: str, casa_slug: str, *, ics: str | None, url: str | None,
           dry_run: bool) -> int:
    run = apri_run("fonti_ical", casa=casa_slug, fonte=fonte_nome)

    try:
        contesto = Contesto.risolvi(casa_slug, fonte_nome)
    except FlussoErrore as errore:
        run.chiudi("errore", 0, errore=str(errore))
        registra_run(run)
        return 1

    # --- il feed ---------------------------------------------------------------------------
    da_fixture = url is None
    try:
        if url:
            testo, impronta = scarica(url)
            origine_feed = url
        else:
            percorso = Path(ics) if ics else FIXTURE
            testo = percorso.read_text(encoding="utf-8")
            impronta = hashlib.sha256(testo.encode("utf-8")).hexdigest()
            origine_feed = str(percorso)
            if not percorso.exists():
                raise IcalErrore(f"fixture ICS non trovata: {percorso}")
    except (FlussoErrore, OSError) as errore:
        run.chiudi("errore", 0, errore=str(errore), feed=str(url or ics or FIXTURE))
        registra_run(run)
        registra_fonte_run(contesto.fonte_id, "errore", 0, dettaglio={"errore": str(errore)})
        return 1

    eventi = leggi_ics(testo)
    dal_feed = {e.uid: e for e in eventi}

    # --- il delta --------------------------------------------------------------------------
    esistenti = contesto.esistenti
    uid_feed, uid_db = set(dal_feed), set(esistenti)

    # Un evento esiste già *identico*? `chiave()` a confronto: è ciò che decide se l'upsert scriverà.
    invariati = [u for u in uid_feed & uid_db
                 if esistenti[u][1] == dal_feed[u].chiave() and not esistenti[u][2]]
    cambiati = sorted(u for u in uid_feed & uid_db
                      if esistenti[u][1] != dal_feed[u].chiave() and not esistenti[u][2])
    riattivati = sorted(u for u in uid_feed & uid_db if esistenti[u][2])
    nuovi = sorted(uid_feed - uid_db)
    rimossi = sorted(uid_db - uid_feed)

    n_esistenti = len(uid_db)
    n_variazioni = len(nuovi) + len(riattivati) + len(cambiati) + len(rimossi)
    soglia = _soglia(contesto)
    # Il denominatore è `max(esistenti, 1)`: evita la divisione per zero.
    pct = round(100.0 * n_variazioni / max(n_esistenti, 1), 1)
    # **Il primo popolamento non è un'anomalia.** La formula letterale della spec
    # (`|nuovi+rimossi| / max(esistenti,1) > soglia`) con `esistenti = 0` darebbe 500% per un feed di
    # 5 eventi e classificherebbe come «delta anomalo» ogni primo import — in contraddizione con il
    # criterio di done dello stesso task B4-FLW-06, che chiede `feed 5 eventi → count(evento)=5` e
    # 5 righe `ical_upsert`. La soglia è un presidio contro il *cambiamento* di una memoria che
    # esiste; dove non c'è memoria da tradire non c'è nulla da segnalare. La condizione è quindi
    # `esistenti > 0 AND pct > soglia`: nessun'altra parte della formula cambia.
    # (L'alternativa — seminare 5 eventi a mano prima del primo import — sposterebbe la fixture
    # dentro il database della rete e non proverebbe che l'import iniziale funziona.)
    anomalo = n_esistenti > 0 and pct > soglia

    run.nota(nuovi=len(nuovi), cambiati=len(cambiati), rimossi=len(rimossi),
             invariati=len(invariati), riattivati=len(riattivati),
             esistenti=n_esistenti, variazioni=n_variazioni, pct=pct, soglia=soglia,
             hash=impronta[:12], feed=origine_feed, fixture=da_fixture, eventi_feed=len(eventi))

    log(f"feed {origine_feed}{' (fixture)' if da_fixture else ''}: {len(eventi)} eventi in finestra "
        f"{-GIORNI_INDIETRO}/+{GIORNI_AVANTI} gg · DB: {n_esistenti} eventi iCal della Casa")
    log(f"delta: {len(nuovi)} nuovi · {len(cambiati)} cambiati · {len(riattivati)} riattivati · "
        f"{len(rimossi)} rimossi · {len(invariati)} invariati → {pct}% (soglia {soglia}%)")

    # --- il controllo: oltre soglia si segnala, non si applica ------------------------------
    if anomalo:
        dettaglio = {"nuovi": len(nuovi), "rimossi": len(rimossi), "esistenti": n_esistenti,
                     "pct": pct, "soglia": soglia, "feed": origine_feed}
        if dry_run:
            log("ANOMALO (dry-run): nessuna scrittura, avrei creato 1 proposta di coerenza")
            run.chiudi("parziale", 0, proposta=None, dry_run=True, anomalo=True)
            registra_run(run)
            return 0
        proposta_id = crea_proposta_anomalia(contesto, dettaglio)
        log(f"ANOMALO: nessun upsert, 0 rami applicati · creata proposta {proposta_id} "
            f"(origine='coerenza', decide l'AT)")
        # `flusso_run.esito='parziale'`, non `'anomalo'`: l'enum del registro dei flussi è
        # `ok|parziale|errore` e «anomalo» è un esito di *fonte* (`fonte_run`, dove l'enum lo prevede).
        # Il flusso ha concluso il proprio lavoro — ha letto, ha misurato e ha segnalato — ma non ha
        # applicato nulla: «parziale» è la parola esatta, e il dettaglio porta `anomalo=true` per chi
        # legge il registro. Usare `'anomalo'` qui violerebbe il CHECK e il run non verrebbe scritto.
        run.chiudi("parziale", 1, proposta=proposta_id, anomalo=True, **dettaglio)
        registra_run(run)
        registra_fonte_run(contesto.fonte_id, "anomalo", 0,
                           hash_=impronta, dettaglio={**dettaglio, "proposta_id": proposta_id})
        return 0

    if dry_run:
        log("dry-run: nessuna scrittura")
        run.chiudi("ok", 0, dry_run=True, scritti={"nuovi": len(nuovi), "cambiati": len(cambiati),
                                                   "rimossi": len(rimossi)})
        registra_run(run)
        return 0

    # --- l'upsert --------------------------------------------------------------------------
    scritti = {"nuovi": 0, "aggiornati": 0, "riattivati": 0, "annullati": 0}
    for uid in nuovi + cambiati + riattivati:
        esito = upsert_evento(contesto, dal_feed[uid])
        if esito == "nuovo":
            scritti["nuovi"] += 1
        elif esito == "aggiornato":
            scritti["aggiornati"] += 1

    scritti["annullati"] = annulla_eventi(contesto, rimossi)

    n_righe = scritti["nuovi"] + scritti["aggiornati"] + scritti["annullati"]
    log(f"scritto: {scritti['nuovi']} nuovi · {scritti['aggiornati']} aggiornati · "
        f"{scritti['annullati']} annullati (mai DELETE)")

    run.chiudi("ok", n_righe, **scritti)
    registra_run(run)
    registra_fonte_run(contesto.fonte_id, "ok", n_righe, hash_=impronta,
                       dettaglio={"nuovi": scritti["nuovi"], "aggiornati": scritti["aggiornati"],
                                  "annullati": scritti["annullati"], "invariati": len(invariati),
                                  "feed": origine_feed})
    return 0


def main(argv: list[str] | None = None) -> int:
    import os

    argomenti = argparse.ArgumentParser(description="F4 · importazione del feed iCal di una Casa")
    argomenti.add_argument("--ics", help="percorso della fixture/feed ICS locale")
    argomenti.add_argument("--url", help="URL del feed reale (se assente si usa la fixture)")
    argomenti.add_argument("--casa", default=os.environ.get("TRASI_ICAL_CASA", "bozzano"))
    argomenti.add_argument("--fonte", default=os.environ.get("TRASI_ICAL_FONTE",
                                                             "Google Calendar-ical-2"))
    argomenti.add_argument("--dry-run", action="store_true", help="calcola il delta senza scrivere")
    opzioni = argomenti.parse_args(argv)

    try:
        return esegui(opzioni.fonte, opzioni.casa, ics=opzioni.ics,
                      url=opzioni.url or os.environ.get("TRASI_ICAL_URL") or None,
                      dry_run=opzioni.dry_run)
    except FlussoErrore as errore:
        print(f"errore: {errore}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
