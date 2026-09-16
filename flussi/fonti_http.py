#!/usr/bin/env python3
"""Trasi — F4 «Fonti HTTP» (B4-FLW-07) · change-detection **senza mai scrivere il dominio**.

Una pagina del Comune che cambia non è un dato verificato: è un indizio. Il flusso calcola l'hash del
testo estratto dal selettore e, se è cambiato, **crea una proposta** (`origine='fonte_automatica'`,
decide l'AT, §11). Non esiste in questo file una scrittura su `luogo` o `scheda_servizio`: il dominio
lo tocca solo `applica_proposte_approvate`, dopo che un umano ha approvato. Criterio osservabile:
`SELECT orari FROM luogo WHERE id = X` è **identico** prima e dopo il run (il test lo asserisce).

Tre presidi, tutti richiesti dalla spec §8 F4 e dalla regola 4 di V4 («delta anomalo → proposta, non
scrittura»):

* **hash come chiave di cambiamento** — `sha256` del testo estratto. Un cambio di hash è la condizione
  necessaria perché nasca una proposta; senza cambio non succede nulla.
* **dedup** — `NOT EXISTS (proposta aperta stessa entità+fonte)`: un sito instabile (un orologio in
  pagina, un contatore di visite) produrrebbe una proposta al giorno e affogherebbe la coda di
  approvazione. La proposta si crea una volta e resta lì finché qualcuno decide.
* **riscrittura anomala** — se la pagina è riscritta oltre soglia il payload porta `anomalo=true`:
  è un segnale per chi approva («guarda bene, è cambiato quasi tutto»), non un blocco tecnico. Il
  testo resta una proposta: la decisione è umana.

Uso:
    flussi/fonti_http.py                                  # tutte le fonti del registro
    flussi/fonti_http.py --config flussi/fixtures/fonti_http.json
    flussi/fonti_http.py --fonte "Comune di Brindisi-3" --file fixtures/urp_cambiato.html
    flussi/fonti_http.py --dry-run

Il registro (`--config`) dichiara *cosa* si sorveglia: fonte, URL, selettore, entità di riferimento e
campo. È configurazione, non codice: aggiungere una pagina non richiede di toccare questo file.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
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
REGISTRO = RADICE / "flussi" / "fixtures" / "fonti_http.json"

UA = "Trasi/0.1 (portierato di quartiere Brindisi; +https://trasi.lascuolaopensource.org)"
TIMEOUT_S = 10


class HttpErrore(FlussoErrore):
    """Errore del flusso HTTP."""


# --------------------------------------------------------------------------- estrazione del testo


class _Estrattore(HTMLParser):
    """Estrae il testo di un elemento individuato da un selettore CSS essenziale (`#id`, `.classe`, `tag`).

    Perché non BeautifulSoup: la regola del blocco è «I/O esterno in Python **minimale**» e la
    dipendenza non è nel `requirements-dev.txt`. Serve un selettore, non un motore CSS: `#id`,
    `.classe`, `tag`, `tag.classe` coprono i casi d'uso reali (un blocco orari, un box avvisi) e
    `html.parser` è stdlib.

    Il parser è tollerante per costruzione — una pagina malformata non fa cadere la notte: si estrae
    quel che si riesce, e se il testo è vuoto il flusso lo dichiara invece di creare una proposta su
    «niente» (che sarebbe un falso positivo: la pagina non è cambiata, è solo illeggibile).
    """

    def __init__(self, selettore: str) -> None:
        super().__init__(convert_charrefs=True)
        self.tag, self.id_, self.classe = self._parse_selettore(selettore)
        self.profondita = 0          # quanti tag aperti dentro l'elemento trovato
        self.attivo = False
        self.pezzi: list[str] = []

    @staticmethod
    def _parse_selettore(selettore: str) -> tuple[str | None, str | None, str | None]:
        selettore = (selettore or "").strip()
        tag = id_ = classe = None
        riscontro = re.match(r"^([a-zA-Z][\w-]*)?(?:#([\w-]+))?(?:\.([\w-]+))?$", selettore)
        if not riscontro:
            raise HttpErrore(f"selettore non supportato: {selettore!r} (usi `#id`, `.classe`, `tag`)")
        tag, id_, classe = riscontro.group(1), riscontro.group(2), riscontro.group(3)
        if not (tag or id_ or classe):
            raise HttpErrore(f"selettore vuoto o non valido: {selettore!r}")
        return (tag.lower() if tag else None), id_, classe

    def _corrisponde(self, tag: str, attrs: dict) -> bool:
        if self.tag and tag.lower() != self.tag:
            return False
        if self.id_ and attrs.get("id") != self.id_:
            return False
        if self.classe and self.classe not in (attrs.get("class") or "").split():
            return False
        return True

    def handle_starttag(self, tag: str, attrs_el: list) -> None:
        attrs = dict(attrs_el)
        if self.attivo:
            self.profondita += 1
            return
        if self._corrisponde(tag, attrs):
            self.attivo = True
            self.profondita = 0

    def handle_endtag(self, tag: str) -> None:
        if not self.attivo:
            return
        if self.profondita > 0:
            self.profondita -= 1
        else:
            self.attivo = False

    def handle_data(self, dati: str) -> None:
        if self.attivo:
            self.pezzi.append(dati)

    def testo(self) -> str:
        """Il testo normalizzato: spazi collassati, righe vuote rimosse.

        La normalizzazione è necessaria perché il confronto non deve dipendere dall'indentazione
        dell'HTML: una pagina riscritta dal CMS con gli stessi contenuti e spazi diversi non è cambiata.
        """
        grezzo = " ".join(self.pezzi)
        righe = [" ".join(r.split()) for r in re.split(r"[\r\n]+", grezzo)]
        return "\n".join(r for r in righe if r)


def estrai_testo(html: str, selettore: str) -> str:
    """Il testo dell'elemento individuato dal selettore (stringa vuota se non c'è)."""
    parser = _Estrattore(selettore)
    parser.feed(html)
    parser.close()
    return parser.testo()


# --------------------------------------------------------------------------- registro


@dataclass
class Bersaglio:
    """Una pagina sorvegliata: cosa guardare, dove, e a quale entità della memoria si riferisce."""

    fonte: str
    url: str
    selettore: str
    entita: str          # 'luogo' | 'scheda_servizio'
    entita_id: int | None
    campo: str           # il campo che la proposta toccherebbe ('orari', 'descrizione', …)
    casa: str | None = None
    file: str | None = None   # fixture locale: se presente si legge da lì, non dalla rete
    #: `False` finché il TI non ha verificato che URL e selettore esistono davvero. Un bersaglio non
    #: verificato che resta attivo produce un `fonte_run.esito='errore'` a ogni notte, e l'alert di
    #: coerenza segnala all'AT una fonte rotta che non è rotta: non è ancora configurata. Il bersaglio
    #: resta nel registro, inattivo e con la nota di cosa manca — la stessa forma di
    #: `fonte.attiva = false` nel seed (§3). Il default è `False`: un bersaglio nuovo non è attivo
    #: finché qualcuno non lo dichiara verificato.
    attivo: bool = False

    def chiave(self) -> str:
        """L'identità della sorveglianza: due bersagli diversi sulla stessa fonte non si confondono."""
        return f"{self.fonte}|{self.url}|{self.entita}:{self.entita_id}|{self.selettore}"

    @classmethod
    def da_json(cls, voce: dict) -> "Bersaglio":
        for campo in ("fonte", "url", "selettore", "entita", "campo"):
            if not voce.get(campo):
                raise HttpErrore(f"bersaglio incompleto: manca `{campo}` in {voce!r}")
        if voce["entita"] not in ("luogo", "scheda_servizio"):
            raise HttpErrore(
                f"entita {voce['entita']!r} non ammessa: questo flusso propone modifiche a "
                "`luogo` e `scheda_servizio` (le altre entità hanno altre fonti)"
            )
        return cls(
            fonte=voce["fonte"], url=voce["url"], selettore=voce["selettore"],
            entita=voce["entita"], entita_id=voce.get("entita_id"), campo=voce["campo"],
            casa=voce.get("casa"), file=voce.get("file"),
            # Un bersaglio dichiarato dalle fixture di test si considera attivo: il test costruisce
            # la pagina, quindi URL e selettore *sono* verificati per costruzione.
            attivo=bool(voce.get("attivo", voce.get("file") is not None)),
        )


def carica_registro(percorso: Path) -> list[Bersaglio]:
    """Il registro dei bersagli. Accetta sia una lista sia `{"bersagli": […] }`.

    La seconda forma è quella del file in `flussi/fixtures/`: permette di documentare i campi accanto
    ai valori, e un registro che si spiega da solo è un registro che qualcuno aggiornerà davvero.
    """
    try:
        contenuto = json.loads(percorso.read_text(encoding="utf-8"))
    except (OSError, ValueError) as errore:
        raise HttpErrore(f"registro {percorso} illeggibile: {errore}") from errore

    voci = contenuto.get("bersagli") if isinstance(contenuto, dict) else contenuto
    if not isinstance(voci, list) or not voci:
        raise HttpErrore(f"registro {percorso}: attesa una lista di bersagli (o `{{\"bersagli\": […]}}`)")
    return [Bersaglio.da_json(v) for v in voci]


# --------------------------------------------------------------------------- scarico e hash


def scarica(url: str) -> str:
    richiesta = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
    try:
        with urllib.request.urlopen(richiesta, timeout=TIMEOUT_S) as risposta:
            return risposta.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as errore:
        raise HttpErrore(f"{url} → HTTP {errore.code}") from errore
    except (urllib.error.URLError, TimeoutError) as errore:
        raise HttpErrore(f"{url} irraggiungibile: {errore}") from errore


def impronta(testo: str) -> str:
    """Lo sha256 del testo estratto: la chiave del cambiamento."""
    return hashlib.sha256(testo.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- stato e proposte


def _lit(testo: str) -> str:
    return "'" + str(testo).replace("'", "''") + "'"


def fonte_id(nome: str) -> int | None:
    """L'id della fonte in allow-list, o `None`. Una fonte fuori allow-list non si sorveglia (§3)."""
    righe = leggi(
        "SELECT f.id, f.tipo_accesso, f.attiva FROM trasi.fonte f "
        f" WHERE f.nome = {_lit(nome)} AND f.attiva"
    )
    return int(righe[0]["id"]) if righe else None


def stato_precedente(fid: int, chiave: str) -> tuple[str, str]:
    """`(hash, testo)` dell'ultima sorveglianza riuscita di questo bersaglio, o `('', '')`.

    Si legge da `fonte_run`, che è append-only: la storia delle letture *è* il meccanismo di
    change-detection. Un file di stato separato sarebbe una seconda verità da tenere allineata.
    """
    righe = leggi(
        "SELECT hash, dettaglio->>'testo' AS testo FROM trasi.fonte_run "
        f" WHERE fonte_id = {fid} AND esito IN ('ok','anomalo') "
        f"   AND dettaglio->>'chiave' = {_lit(chiave)} "
        "  ORDER BY ts DESC, id DESC LIMIT 1"
    )
    if not righe:
        return "", ""
    return righe[0]["hash"] or "", righe[0]["testo"] or ""


def proposta_aperta(fid: int, entita: str, entita_id: int | None) -> bool:
    """Esiste già una proposta aperta per questa entità e questa fonte?

    È il **dedup** richiesto dalla spec (`WHERE NOT EXISTS (proposta aperta stessa entità+fonte)`).
    Si guarda lo stato `proposta` e non anche `approvata`: una proposta già approvata e non ancora
    applicata è comunque in coda, e crearne una seconda sarebbe lo stesso rumore.
    """
    condizione_id = "IS NULL" if entita_id is None else f"= {int(entita_id)}"
    righe = leggi(
        "SELECT 1 AS esiste FROM trasi.proposta p "
        f" WHERE p.fonte_id = {fid} AND p.entita = {_lit(entita)} "
        f"   AND p.entita_id {condizione_id} AND p.stato IN ('proposta','approvata') LIMIT 1"
    )
    return bool(righe)


def crea_proposta(fid: int, bersaglio: Bersaglio, testo: str, *, anomalo: bool,
                  campo: str, valore: str | None = None) -> int | None:
    """Crea la proposta `origine='fonte_automatica'`. **Nessuna scrittura sul dominio.**

    `approvatore_ruolo` non si scrive: lo calcola il trigger `proposta_00_default_tg` dalla regola §11
    (`luogo`/`scheda_servizio` del territorio → AT). Il test verifica proprio quel valore: se il
    codice lo scegliesse, la regola di governance sarebbe duplicata in un flusso.
    """
    frammento = testo.strip().splitlines()[0] if testo.strip() else "(testo non disponibile)"
    testo_motivazione = motivazione(
        f"{bersaglio.fonte}: testo del selettore {bersaglio.selettore} cambiato su "
        f"{bersaglio.entita} {bersaglio.entita_id} — da verificare prima di aggiornare `{campo}`"
    )

    payload = {
        "anomalo": anomalo,
        "campo": campo,
        "_estratto": frammento[:300],
        "_fonte_url": bersaglio.url,
        "_selettore": bersaglio.selettore,
    }
    if valore is not None:
        payload[campo] = valore

    uscita = esegui_sql(
        "INSERT INTO trasi.proposta (origine, tipo, entita, entita_id, casa_id, fonte_id, "
        "                             payload, motivazione) "
        "VALUES ('fonte_automatica', 'modifica_luogo', "
        f"        {_lit(bersaglio.entita)}, "
        f"        {bersaglio.entita_id if bersaglio.entita_id is not None else 'NULL'}, "
        f"        (SELECT c.id FROM trasi.casa c WHERE c.slug = {_lit(bersaglio.casa or '')}), "
        f"        {fid}, "
        f"        {_lit(json.dumps(payload, ensure_ascii=False))}::jsonb, "
        f"        {_lit(testo_motivazione)}) "
        "RETURNING id\n"
    )
    righe = [r.strip() for r in uscita.splitlines() if r.strip().isdigit()]
    return int(righe[0]) if righe else None


def riscrittura_pct(vecchio: str, nuovo: str) -> float:
    """Quanto è cambiato il testo, in percentuale (0 = identico, 100 = nulla in comune).

    `SequenceMatcher.ratio()` è `2·M/T` (M = caratteri comuni): la percentuale di riscrittura è il
    complemento. Una pagina riscritta al 90% non è «un orario aggiornato», è un'altra pagina — e la
    proposta lo dichiara con `anomalo=true`, come chiede `plan.md` B4-FLW-07.
    """
    if not vecchio:
        return 0.0
    rapporto = difflib.SequenceMatcher(None, vecchio, nuovo, autojunk=False).ratio()
    return round(100.0 * (1.0 - rapporto), 1)


# --------------------------------------------------------------------------- main


def _soglia_riscrittura() -> int:
    return max(1, min(100, parametro_int("soglia_riscrittura_pct", 80)))


def esegui(bersagli: list[Bersaglio], *, dry_run: bool) -> int:
    run = apri_run("fonti_http", bersagli=len(bersagli))

    proposte, cambiati, invariati, errori, anomali = [], [], [], [], []
    inattivi: list[str] = []
    soglia = _soglia_riscrittura()

    for bersaglio in bersagli:
        chiave = bersaglio.chiave()

        # I bersagli non verificati si **dichiarano**, non si saltano in silenzio: il registro deve
        # dire «c'è una pagina che nessuno sorveglia», altrimenti la configurazione diventa l'unico
        # posto in cui vive quell'informazione (e nessuno la legge).
        if not bersaglio.attivo:
            inattivi.append(chiave)
            log(f"  {bersaglio.fonte}: bersaglio inattivo (da verificare) → non sorvegliato")
            continue

        fid = fonte_id(bersaglio.fonte)
        if fid is None:
            errori.append(f"{bersaglio.fonte}: non in allow-list o inattiva → non si sorveglia (§3)")
            log(f"  {bersaglio.fonte}: fuori allow-list, saltata")
            continue

        # --- lettura della pagina (fixture locale se dichiarata) -------------------------------
        try:
            if bersaglio.file:
                percorso = Path(bersaglio.file)
                if not percorso.is_absolute():
                    percorso = RADICE / percorso
                html = percorso.read_text(encoding="utf-8")
                origine = str(percorso)
            else:
                html = scarica(bersaglio.url)
                origine = bersaglio.url
        except (FlussoErrore, OSError) as errore:
            errori.append(f"{bersaglio.url}: {errore}")
            log(f"  {bersaglio.url}: errore ({errore})")
            registra_fonte_run(fid, "errore", 0, dettaglio={"chiave": chiave, "errore": str(errore)})
            continue

        testo = estrai_testo(html, bersaglio.selettore)
        if not testo:
            # Niente testo = il selettore non trova nulla. Non è «la pagina è cambiata»: è «non
            # sappiamo leggerla». Si dichiara l'esito e **non** si crea una proposta — un falso
            # positivo in coda costa a un umano una decisione su nulla.
            errori.append(f"{bersaglio.url}: selettore {bersaglio.selettore!r} senza testo")
            log(f"  {bersaglio.url}: selettore {bersaglio.selettore!r} non trova testo → nessuna proposta")
            registra_fonte_run(fid, "errore", 0, dettaglio={"chiave": chiave, "errore": "selettore vuoto"})
            continue

        nuovo_hash = impronta(testo)
        hash_prec, testo_prec = stato_precedente(fid, chiave)

        # **Prima osservazione**: non c'è un «prima» con cui confrontare, quindi non c'è un
        # cambiamento da segnalare. Si registra la base e si esce. Senza questo caso, il primo run su
        # una pagina mai sorvegliata produrrebbe una proposta «la pagina è cambiata» su una pagina che
        # nessuno ha mai letto — un falso positivo, e per giunta uno che poi *blocca* il vero
        # cambiamento (la proposta aperta farebbe scattare il dedup al run successivo).
        # La change-detection ha senso da due osservazioni in poi: la prima stabilisce il riferimento.
        if not hash_prec:
            log(f"  {bersaglio.fonte}: prima osservazione → base registrata ({nuovo_hash[:12]}), "
                "nessuna proposta (non c'è un «prima» con cui confrontare)")
            invariati.append(chiave)
            registra_fonte_run(fid, "ok", 0, hash_=nuovo_hash,
                               dettaglio={"chiave": chiave, "testo": testo, "cambiato": False,
                                          "prima_osservazione": True})
            continue

        if nuovo_hash == hash_prec:
            invariati.append(chiave)
            log(f"  {bersaglio.fonte}: invariato ({nuovo_hash[:12]})")
            registra_fonte_run(fid, "ok", 0, hash_=nuovo_hash,
                               dettaglio={"chiave": chiave, "testo": testo, "cambiato": False})
            continue

        # --- cambiato: proposta, mai scrittura -------------------------------------------------
        pct = riscrittura_pct(testo_prec, testo)
        anomalo = bool(testo_prec) and pct > soglia
        log(f"  {bersaglio.fonte}: CAMBIATO ({hash_prec[:8] or '∅'} → {nuovo_hash[:8]}, "
            f"riscrittura {pct}%{' > soglia ' + str(soglia) + '% → anomalo' if anomalo else ''})")

        if proposta_aperta(fid, bersaglio.entita, bersaglio.entita_id):
            invariati.append(chiave)
            log(f"  {bersaglio.fonte}: proposta già aperta per {bersaglio.entita} "
                f"{bersaglio.entita_id} → dedup, nessun duplicato")
            registra_fonte_run(fid, "ok", 0, hash_=nuovo_hash,
                               dettaglio={"chiave": chiave, "testo": testo, "cambiato": True,
                                          "dedup": True})
            continue

        if dry_run:
            log(f"  {bersaglio.fonte}: (dry-run) avrei creato 1 proposta "
                f"{'ANOMALA' if anomalo else 'normale'}")
            cambiati.append(chiave)
            continue

        pid = crea_proposta(fid, bersaglio, testo, anomalo=anomalo, campo=bersaglio.campo)
        proposte.append(pid)
        cambiati.append(chiave)
        if anomalo:
            anomali.append(chiave)
        log(f"  {bersaglio.fonte}: creata proposta {pid} "
            f"(origine='fonte_automatica', decide l'AT{' , anomalo' if anomalo else ''})")
        registra_fonte_run(fid, "anomalo" if anomalo else "ok", 1, hash_=nuovo_hash,
                           dettaglio={"chiave": chiave, "testo": testo, "cambiato": True,
                                      "pct_riscrittura": pct, "proposta_id": pid,
                                      "anomalo": anomalo})

    # L'esito non dipende dagli inattivi: un bersaglio non verificato è una decisione di
    # configurazione, non un guasto del flusso. Se l'unico contenuto del registro sono bersagli
    # inattivi, il run è `ok` con 0 proposte — ed è la verità.
    esito = "errore" if errori and not (proposte or invariati) else ("parziale" if errori else "ok")
    run.chiudi(esito, len(proposte), proposte=proposte, cambiati=cambiati,
               invariati=len(invariati), anomalie=anomali, errori=errori,
               inattivi=inattivi, soglia_riscrittura=soglia)
    registra_run(run)

    log(f"fonti_http: {len(proposte)} proposte create · {len(cambiati)} bersagli cambiati · "
        f"{len(invariati)} invariati/dedup · {len(inattivi)} inattivi · {len(errori)} errori · "
        f"esito={esito}")
    return 0 if esito != "errore" else 1


def main(argv: list[str] | None = None) -> int:
    argomenti = argparse.ArgumentParser(description="F4 · change-detection delle fonti HTTP")
    argomenti.add_argument("--config", default=str(REGISTRO), help="registro dei bersagli (JSON)")
    argomenti.add_argument("--fonte", help="limita a una fonte della allow-list")
    argomenti.add_argument("--file", help="usa questa fixture locale invece della rete")
    argomenti.add_argument("--dry-run", action="store_true")
    opzioni = argomenti.parse_args(argv)

    try:
        bersagli = carica_registro(Path(opzioni.config))
    except FlussoErrore as errore:
        print(f"errore: {errore}", file=sys.stderr)
        return 1

    if opzioni.fonte:
        bersagli = [b for b in bersagli if b.fonte == opzioni.fonte]
        if not bersagli:
            print(f"errore: nessun bersaglio per la fonte {opzioni.fonte!r}", file=sys.stderr)
            return 1
    if opzioni.file:
        # Una fixture sola per tutti i bersagli selezionati: è il modo in cui i test cambiano «la
        # pagina» senza dipendere dalla rete. E `attivo=True` è obbligatorio qui: se il test costruisce
        # la pagina, allora URL e selettore **sono** verificati per costruzione — è esattamente la
        # condizione che `attivo` dichiara. Senza, `--file` verrebbe ignorato in silenzio e il test
        # sarebbe verde per il motivo sbagliato (nessuna proposta perché nessuno ha guardato).
        bersagli = [Bersaglio(**{**b.__dict__, "file": opzioni.file, "attivo": True}) for b in bersagli]

    try:
        return esegui(bersagli, dry_run=opzioni.dry_run)
    except FlussoErrore as errore:
        print(f"errore: {errore}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
