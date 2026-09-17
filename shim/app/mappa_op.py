"""`GET /op/mappa`: le Case e i luoghi della rete, per la mappa dell'Osservatorio (§5.2, `T-SHIM-04`).

Un endpoint del **browser** (cookie di sessione, sotto `/op`, fuori dal contratto congelato con Onyx), che serve le
due viste `v_mappa_case` (10 righe) e `v_mappa_luoghi` (22 righe). L'endpoint non inventa nulla: le righe sono quelle
delle viste, e ciò che aggiunge sono tre cose che la vista non può sapere — il **badge di provenienza** composto dallo
shim (V3), lo **stato di apertura** calcolato nel fuso italiano, e la **distanza** dalla Casa della sessione.

**Perché il filtro per Casa non restringe l'elenco, benché le viste siano `security_invoker=false`.**
`v_mappa_case` e `v_mappa_luoghi` girano con i privilegi del proprietario (`db/004_views.sql:369-370`), quindi al
loro interno la RLS **non vede il chiamante** e non limita nulla: è il caso in cui la regola di `testi.py` (`WHERE
slug = $1 AND (casa_corrente() IS NULL OR casa_id = casa_corrente())`) serve a impedire che un operatore legga la riga
«Oggi» di un'altra Casa. Qui la domanda è diversa e il piano la dichiara (§5.2, «Nota»): «le Case e i luoghi sono
**pubblici per natura** (indirizzi di servizi), ma la RLS resta applicata: la vista non è una scusa per saltarla». La
mappa dell'Osservatorio esiste per mostrare **la rete**, non la propria Casa: le altre nove Case *sono* l'informazione,
e applicare il filtro per Casa darebbe 1 pin invece di 10 — la mappa smetterebbe di dire ciò per cui è stata costruita.

`casa_corrente()` è comunque **nella query**, e fa il lavoro che le compete: distingue la Casa della sessione (che la
mappa centra ed evidenzia, §4.2.1 «Apertura») da tutte le altre, senza che lo shim confronti un id che ha già in
mano. Per `rete`/`ti` la funzione vale `NULL`: nessuna Casa è «mia», tutte restano visibili (§11).

**Il badge di una Casa viene dal suo luogo `casa_quartiere`.** `v_mappa_case` non porta `fonte_id`, `affidabilita`
né `data_aggiornamento`: la provenienza della Casa è quella della sua riga di memoria, che è il luogo di tipo
`casa_quartiere` della Casa (le 10 Case ne hanno tutte una, `Rete-kb-3`). È lo stesso legame che usa `SQL_EVENTO` in
`testi.py` per le note di accesso: un `LEFT JOIN LATERAL` con l'ordinamento per affidabilità. Se una Casa non avesse
quel luogo, il badge dichiara le em dash di `badge_kb` («fonte non dichiarata · agg. — · affidabilità —») invece di
attribuire alla rete una fonte che nessuno ha dichiarato.

**Nessuna scrittura.** Il modulo è di sola lettura, come tutti gli output: se l'operatore vuole correggere un luogo,
quella è una proposta (V4), non una scrittura da qui.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, FastAPI

from .auth import SessioneOperatore, sessione_corrente
from .badge import NOTA_ORARI_ASSENTI, badge_kb, nome_fonte
from .db import parametri, parametro_int
from .vicinanza import adesso_locale, orari_da_jsonb

router = APIRouter()

RAGGIO_DEFAULT_M = 800

# Parametro [P] del raggio di riferimento, la stessa chiave di `vicino_a`: se una Casa non dichiara `raggio_m`, il
# raggio effettivo è quello della rete, non un numero scelto qui.
CHIAVI_PARAMETRI = ("raggio_vicinanza_m",)

# Il legame Casa → riga di memoria, usato per il badge. Lo stesso ordinamento di `testi.py` (SQL_EVENTO): la riga più
# affidabile, e a parità la più vecchia per id — così la scelta è deterministica e non cambia fra due richieste.
SQL_CASE = """
SELECT vc.id, vc.slug, vc.nome, vc.zona, vc.ente_gestore, vc.lat, vc.lon,
       vc.raggio_m_eff, vc.geom_qualita, vc.da_validare, vc.orari_provvisori, vc.orari_testo,
       c.orari,
       f.nome AS fonte_nome, f.autorita AS fonte_autorita,
       l.affidabilita, l.data_aggiornamento,
       (vc.id = trasi.casa_corrente()) AS mia,
       CASE WHEN cs.geom IS NULL THEN NULL
            ELSE round(st_distance(c.geom, cs.geom)::numeric, 1) END AS distanza_m
  FROM trasi.v_mappa_case vc
  JOIN trasi.casa c ON c.id = vc.id
  LEFT JOIN LATERAL (
      SELECT l2.fonte_id, l2.affidabilita, l2.data_aggiornamento
        FROM trasi.luogo l2
       WHERE l2.casa_id = vc.id AND l2.tipo = 'casa_quartiere' AND l2.chiuso_il IS NULL
       ORDER BY l2.affidabilita DESC NULLS LAST, l2.id
       LIMIT 1
  ) l ON true
  LEFT JOIN trasi.fonte f ON f.id = l.fonte_id
  LEFT JOIN trasi.casa cs ON cs.id = trasi.casa_corrente()
 ORDER BY vc.nome
"""

# `v_mappa_luoghi` non espone `f.autorita` (solo `f.nome`, il nome tecnico «Rete-kb-3»): il nome umano del badge si
# legge da `fonte` per `nome` — la colonna è UNIQUE, quindi la join non può duplicare righe. Farla qui invece di
# ricomporre il nome in Python è ciò che rende il badge **verbatim** (V3): lo compone `badge_kb`, non questa query.
SQL_LUOGHI = """
SELECT vl.id, vl.nome, vl.tipo, vl.indirizzo, vl.lat, vl.lon,
       vl.casa_id, vl.casa_slug, vl.data_aggiornamento, vl.affidabilita, vl.url,
       vl.orari_testo, l.orari,
       c.nome AS casa_nome, c.zona AS zona,
       f.nome AS fonte_nome, f.autorita AS fonte_autorita,
       (vl.casa_id = trasi.casa_corrente()) AS della_mia_casa,
       CASE WHEN cs.geom IS NULL THEN NULL
            ELSE round(st_distance(l.geom, cs.geom)::numeric, 1) END AS distanza_m
  FROM trasi.v_mappa_luoghi vl
  JOIN trasi.luogo l ON l.id = vl.id
  LEFT JOIN trasi.casa c ON c.id = vl.casa_id
  LEFT JOIN trasi.fonte f ON f.nome = vl.fonte_nome
  LEFT JOIN trasi.casa cs ON cs.id = trasi.casa_corrente()
 ORDER BY distanza_m NULLS LAST, vl.nome
"""


def _distanza(valore: Any) -> float | None:
    """La distanza in metri come numero, o `None` quando non c'è una Casa di riferimento (ruolo `rete`)."""
    return round(float(valore), 1) if valore is not None else None


def voce_casa(riga: Any, *, adesso, raggio_effettivo: int) -> dict[str, Any]:
    """Una riga di `v_mappa_case` → l'elemento che la mappa disegna come **quadrato pieno**.

    `indirizzo` è vuoto e non `null`: la Casa non ha una colonna indirizzo (`v_mappa_case` non la espone e il luogo
    `casa_quartiere` non la porta nel seed) e il contratto degli item usa la stringa vuota per «non dichiarato»,
    come `vicino_a`. La scheda del luogo dichiara l'assenza invece di stampare una riga vuota.

    `aperto_adesso` è `null` quando gli orari non bastano a decidere (chiave del giorno assente, orari assenti): è la
    stessa regola di `vicino_a`, e trattarla come «chiuso» farebbe sparire le Case che non dichiarano la domenica.
    """
    fonte = nome_fonte(riga["fonte_autorita"], riga["fonte_nome"])
    orari_testo = riga["orari_testo"]
    return {
        "provenienza": "kb",
        "id": riga["id"],
        "slug": riga["slug"],
        "nome": riga["nome"],
        "tipo": "casa_quartiere",
        "zona": riga["zona"],
        "ente_gestore": riga["ente_gestore"],
        "lat": float(riga["lat"]),
        "lon": float(riga["lon"]),
        "indirizzo": "",
        "orari_testo": orari_testo,
        "orari_nota": None if orari_testo else NOTA_ORARI_ASSENTI,
        "aperto_adesso": orari_da_jsonb(riga["orari"], adesso),
        "distanza_m": _distanza(riga["distanza_m"]),
        "raggio_m_eff": riga["raggio_m_eff"] or raggio_effettivo,
        "geom_qualita": riga["geom_qualita"],
        "da_validare": riga["da_validare"],
        "orari_provvisori": riga["orari_provvisori"],
        # `mia` è la Casa della sessione: la mappa la centra e la evidenzia, le altre restano sulla mappa.
        "mia": bool(riga["mia"]),
        "casa_id": riga["id"],
        "casa_slug": riga["slug"],
        "casa_nome": riga["nome"],
        "url": None,
        "fonte": fonte,
        "fiducia": riga["affidabilita"],
        "data_aggiornamento": riga["data_aggiornamento"].isoformat() if riga["data_aggiornamento"] else None,
        "badge": badge_kb(fonte, riga["data_aggiornamento"], riga["affidabilita"]),
    }


def voce_luogo(riga: Any, *, adesso) -> dict[str, Any]:
    """Una riga di `v_mappa_luoghi` → l'elemento che la mappa disegna come **cerchio pieno**.

    Il badge è `badge_kb` anche quando la fonte del luogo è un sito (`tipo_accesso='web'`, i sette luoghi di servizio
    non-Casa): la riga sta nella **memoria della rete** (`trasi.luogo`), ed è la rete a risponderne — è la stessa
    scelta di `routes_lettura._item_luogo` e di `testi.biglietto`. L'etichetta `[Esterna …]` è riservata ai POI che
    la rete **non** ha in memoria, cioè a quelli di Overpass (`poi_op.py`).
    """
    fonte = nome_fonte(riga["fonte_autorita"], riga["fonte_nome"])
    orari_testo = riga["orari_testo"]
    return {
        "provenienza": "kb",
        "id": riga["id"],
        "nome": riga["nome"],
        "tipo": riga["tipo"],
        "zona": riga["zona"],
        "casa_id": riga["casa_id"],
        "casa_slug": riga["casa_slug"],
        "casa_nome": riga["casa_nome"],
        "lat": float(riga["lat"]),
        "lon": float(riga["lon"]),
        "indirizzo": riga["indirizzo"] or "",
        "orari_testo": orari_testo,
        "orari_nota": None if orari_testo else NOTA_ORARI_ASSENTI,
        "aperto_adesso": orari_da_jsonb(riga["orari"], adesso),
        "distanza_m": _distanza(riga["distanza_m"]),
        "della_mia_casa": bool(riga["della_mia_casa"]),
        "url": riga["url"],
        "fonte": fonte,
        "fiducia": riga["affidabilita"],
        "data_aggiornamento": riga["data_aggiornamento"].isoformat() if riga["data_aggiornamento"] else None,
        "badge": badge_kb(fonte, riga["data_aggiornamento"], riga["affidabilita"]),
    }


@router.get(
    "/mappa",
    operation_id="op_mappa",
    summary="Le Case della rete (10) e i luoghi in memoria (22) con coordinate, orari, distanza dalla Casa della "
    "sessione e badge di provenienza per riga: è la sorgente della mappa dell'Osservatorio. Include anche la "
    "Casa della sessione, che è il centro della mappa.",
    tags=["op"],
)
async def op_mappa(sess: SessioneOperatore = Depends(sessione_corrente)) -> dict[str, Any]:
    """GET /op/mappa → `{casa_sessione, raggio_m, case, luoghi}`.

    Tre letture, una sola andata e ritorno per tabella. Il raggio effettivo della Casa della sessione è `raggio_m_eff`
    della vista, che vale `raggio_m` della Casa oppure il parametro `[P] raggio_vicinanza_m` (800): il titolo della
    pagina lo dichiara («raggio 800 m»), quindi il valore che l'operatore legge è quello della vista, non un default
    ripetuto nella pagina.

    Per un ruolo **senza Casa** (`rete`, `ti`) `casa_sessione` è `null` e nessuna riga è `mia`: la pagina non ha un
    centro da cui misurare e lo dichiara, invece di inventare una Casa di riferimento.
    """
    adesso = adesso_locale()
    valori = await parametri(sess, CHIAVI_PARAMETRI)
    raggio_default = parametro_int(valori, "raggio_vicinanza_m", RAGGIO_DEFAULT_M)

    righe_case = await sess.fetch(SQL_CASE)
    righe_luoghi = await sess.fetch(SQL_LUOGHI)

    case = [voce_casa(riga, adesso=adesso, raggio_effettivo=raggio_default) for riga in righe_case]
    luoghi = [voce_luogo(riga, adesso=adesso) for riga in righe_luoghi]

    mia = next((voce for voce in case if voce["mia"]), None)
    consultato = adesso.isoformat()

    return {
        "casa_sessione": mia,
        "raggio_m": mia["raggio_m_eff"] if mia else raggio_default,
        "consultato_ts": consultato,
        "case": case,
        "luoghi": luoghi,
    }


def monta(applicazione: FastAPI) -> None:
    """Monta il router sotto `/op`, **fuori** dal documento OpenAPI (come `testi.py`, `attrezzoteca.py`).

    Il prefisso è quello che il browser chiama (`/api/shim/op/mappa`, con Caddy che toglie `/api/shim`), e
    `include_in_schema=False` non è una formalità: lo schema che FastAPI genera è il contratto congelato con Onyx, e il
    gate V-09 lo verifica per uguaglianza — un endpoint del browser in più nel documento lo farebbe fallire.
    """
    applicazione.include_router(router, prefix="/op", include_in_schema=False)


__all__ = ["RAGGIO_DEFAULT_M", "monta", "op_mappa", "router", "voce_casa", "voce_luogo"]
