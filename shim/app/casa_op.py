"""Testata della Casa in **sola lettura** — la sezione «La Casa» dell'Account (`T-SHIM-11`).

Il browser dell'operatore chiede `GET /op/casa` e riceve i dati anagrafici della **propria** Casa: nome, zona,
ente gestore, orari settimanali, raggio di riferimento, la provenienza (fonte, livello di fiducia, data) e i due
indicatori di provvisorietà (`da_validare`, `orari_provvisori`) che la UI deve mostrare **nel testo**.

Tre decisioni non negoziabili, e dove vivono:

- **la Casa è quella della sessione, mai un parametro.** Il filtro è `c.id = trasi.casa_corrente()`, calcolato dal
  database sul ruolo assunto con `SET LOCAL ROLE`: un `casa_id` nella query string sarebbe un'identità scelta dal
  browser, che è esattamente ciò che l'architettura vieta (Principio 3, `plan-wireframe.md` §11 Q-05). Non è
  ridondante con la RLS: la policy `casa_sel` è `USING (true)` — ogni ruolo legge ogni Casa — quindi **l'unico
  filtro è quello che si scrive qui**.
- **nessuna scrittura, per nessuna via.** Questa sezione è in sola lettura per scelta di progetto: le modifiche a
  una Casa passano da `proponi_modifica` → approvazione → `applica_proposte_approvate` (V4). Il GRANT di `UPDATE`
  su `trasi.casa` per i ruoli Casa esiste (colonne `orari`, `orari_eccezioni`, `orari_provvisori`, `email_digest`),
  e proprio per questo il presidio non può essere il privilegio: è l'assenza dell'endpoint.
- **niente dati personali.** `email_digest` è l'unica colonna di contatto della tabella e **non esce**: la testata
  dell'Account è una scheda anagrafica pubblica della Casa, non la rubrica di chi la gestisce. `persone_target` e
  `competenze` sono descrizioni della vocazione della Casa e non hanno un consumatore in questa sezione.

La provenienza è composta dal database dove esiste già (`orari_testo`, `p_int`), e dal badge V3 dello shim dove
serve una stringa per l'operatore. La regola è quella di `badge.py`: **l'etichetta si compone una volta sola**, così
la UI la mostra e non la ricostruisce.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, FastAPI

from .auth import SessioneOperatore, sessione_corrente
from .badge import badge_kb, nome_fonte
from .errori import errore

router = APIRouter()

# La fonte di una Casa, quando il seed non ne ha una dedicata: `db/011_seed_fonti.sql` semina una fonte
# `ETS: <nome>` per ciascuna delle dieci Case, e il `LEFT JOIN` sulla convenzione del nome è il legame che esiste
# oggi. Se quella riga manca, si dichiara la fonte della memoria della rete invece di lasciare il campo vuoto: un
# campo vuoto nella UI si legge «non si sa chi lo dice», che è peggio di «lo dice la rete» — che è vero.
NOME_FONTE_MEMORIA = "Rete delle Case di Quartiere di Brindisi"

# Perché il `LEFT JOIN` è sulla convenzione `'ETS: ' || c.nome` e non su una chiave esterna: `casa` non ha
# `fonte_id` (l'anagrafica della Casa è un dato di governance del seed, non un dato raccolto da una fonte), e
# aggiungere una colonna sarebbe una migrazione del modello dati, fuori da questa scheda. La convenzione è già
# quella che usa `db/011_seed_fonti.sql:40` per seminare la riga, quindi i due lati combaciano per costruzione.
SQL_CASA = """
SELECT c.id, c.slug, c.nome, c.zona, c.ente_gestore,
       trasi.orari_testo(c.orari)                     AS orari_testo,
       c.orari_eccezioni,
       c.orari_provvisori,
       c.raggio_m,
       COALESCE(c.raggio_m, trasi.p_int('raggio_vicinanza_m')) AS raggio_m_eff,
       c.geom_qualita,
       c.da_validare,
       c.aggiornato_ts,
       c.creato_ts,
       f.nome        AS fonte_nome,
       f.autorita    AS fonte_autorita,
       f.url         AS fonte_url,
       f.livello_fiducia AS fonte_fiducia
  FROM trasi.casa c
  LEFT JOIN trasi.fonte f ON f.nome = 'ETS: ' || c.nome
 WHERE c.id = trasi.casa_corrente()
"""


def monta(applicazione: FastAPI) -> None:
    """Monta il router sotto `/op`, **fuori** dal contratto congelato.

    `include_in_schema=False` non è un dettaglio: lo schema OpenAPI che FastAPI genera da questa applicazione è il
    contratto con Onyx, e il gate V-09 lo verifica per uguaglianza. Questi endpoint li chiama il **browser** con il
    cookie di sessione, non il LLM con `X-Trasi-Key`, quindi non appartengono a quel documento.
    """
    applicazione.include_router(router, prefix="/op", include_in_schema=False)


def _orari_settimanali(orari_testo: str | None) -> list[dict[str, str]]:
    """Le sette righe della settimana, una per giorno, dalla stringa che il database ha già composto.

    `orari_testo` produce `lun 09:00-12:30 15:30-18:30 · … · dom chiuso` (`db/004_views.sql`,
    funzione `trasi.orari_testo`). Qui si **separa** quel testo su `·` invece di rileggere il `jsonb`: la regola di
    composizione (quali giorni esistono, come si scrive «chiuso», come si accoppiano le fasce) sta in un posto solo
    — la funzione SQL — e riscriverla in Python sarebbe una seconda verità che diverge alla prima modifica.

    Il difetto che questo evita è concreto e misurato: una Casa senza orari (`orari IS NULL`, come Tuturano) ha
    `orari_testo` **NULL**, e un `split` ingenuo su `None` solleverebbe un'eccezione — cioè un 500 al posto di una
    scheda che dichiara «orari non disponibili».
    """
    if not orari_testo:
        return []
    righe = []
    for pezzo in orari_testo.split(" · "):
        pezzo = pezzo.strip()
        if not pezzo:
            continue
        giorno, _, fasce = pezzo.partition(" ")
        righe.append({"giorno": giorno, "fasce": fasce or "—"})
    return righe


def _eccezioni(valore: Any) -> list[dict[str, Any]]:
    """Le eccezioni di orario (stagionali, chiusure) come elenco di dizionari leggibili.

    `orari_eccezioni` è un `jsonb` con array di oggetti `{tipo, dal, al, nota, orari?}`. Il codec del pool
    (`db._prepara_connessione`) lo decodifica già in Python: qui si normalizza soltanto, e una forma inattesa
    diventa un elenco vuoto con la nota, non un errore — la testata è in sola lettura e un dato accessorio malformato
    non deve impedire di leggere nome, zona e orari.
    """
    if not isinstance(valore, list):
        return []
    fuori: list[dict[str, Any]] = []
    for voce in valore:
        if not isinstance(voce, dict):
            continue
        fuori.append(
            {
                "tipo": voce.get("tipo") or "eccezione",
                "dal": voce.get("dal"),
                "al": voce.get("al"),
                "nota": voce.get("nota"),
                "orari_testo": voce.get("nota") or None,
            }
        )
    return fuori


def _provenienza(riga: Any) -> dict[str, Any]:
    """La provenienza V3 della scheda: fonte, fiducia, data e il badge già composto.

    Due date possibili, e la scelta è dichiarata: `aggiornato_ts` è la data dell'ultima **scrittura mediata** (la
    scrive il trigger `scrittura_00_ts`), `creato_ts` è il caricamento iniziale. Sull'anagrafica attuale
    `aggiornato_ts` è NULL per tutte le Case — nessuna ha ancora ricevuto una proposta applicata — e in quel caso la
    data leggibile è quella del seed: mostrare la data del caricamento è vero, mostrare `—` lascerebbe l'operatore
    senza sapere da quando quel dato c'è.
    """
    fonte = nome_fonte(riga["fonte_autorita"], riga["fonte_nome"]) if riga["fonte_nome"] else NOME_FONTE_MEMORIA
    fiducia = riga["fonte_fiducia"]
    data = (riga["aggiornato_ts"].date() if riga["aggiornato_ts"] else None) or (
        riga["creato_ts"].date() if riga["creato_ts"] else None
    )
    return {
        "fonte": fonte,
        "url": riga["fonte_url"],
        "fiducia": fiducia,
        "data_aggiornamento": data.isoformat() if isinstance(data, date) else None,
        "aggiornata_da_mediata": riga["aggiornato_ts"] is not None,
        "badge": badge_kb(fonte, data, fiducia),
    }


@router.get(
    "/casa",
    operation_id="op_casa",
    summary="Legge la testata della Casa della sessione: nome, zona, ente gestore, orari settimanali ed "
    "eccezioni, raggio di riferimento e provenienza del dato. Sola lettura: le modifiche passano da "
    "una proposta. Per Tuturano dichiara i dati provvisori.",
    tags=["op"],
)
async def op_casa(sess: SessioneOperatore = Depends(sessione_corrente)) -> dict[str, Any]:
    """GET /op/casa → la scheda anagrafica della Casa, con la provenienza (V3) e i dati provvisori dichiarati.

    Se la sessione non ha una Casa (`ruolo_casa` senza `casa_id`: il caso di `rete` e `ti`) la risposta è **403**
    e non una scheda vuota: un AT non ha «la propria Casa», e inventarne una — la prima della tabella, o quella
    dell'ultima richiesta — significherebbe mostrare i dati di una Casa scelta dal sistema. Il 403 è già il
    vocabolario di questo canale per «il tuo ruolo non ha questa operazione».
    """
    if sess.casa_id is None:
        raise errore(403, "la sessione non ha una Casa: la testata della Casa riguarda un ruolo di Casa")

    riga = await sess.fetchrow(SQL_CASA)
    if riga is None:
        # Il ruolo esiste in `ruolo_casa` e ha un `casa_id`, ma la Casa non è leggibile: è una configurazione da
        # correggere nel database, non una richiesta sbagliata. Il messaggio lo dice senza esporre l'id.
        raise errore(404, "la Casa della sessione non è presente in memoria")

    return {
        "id": riga["id"],
        "slug": riga["slug"],
        "nome": riga["nome"],
        "zona": riga["zona"],
        "ente_gestore": riga["ente_gestore"],
        "orari_settimanali": _orari_settimanali(riga["orari_testo"]),
        "orari_testo": riga["orari_testo"],
        "orari_eccezioni": _eccezioni(riga["orari_eccezioni"]),
        "orari_provvisori": bool(riga["orari_provvisori"]),
        "raggio_m": riga["raggio_m"],
        "raggio_m_eff": riga["raggio_m_eff"],
        "geom_qualita": riga["geom_qualita"],
        "da_validare": bool(riga["da_validare"]),
        "provenienza": _provenienza(riga),
    }


__all__ = ["SQL_CASA", "monta", "op_casa", "router"]
