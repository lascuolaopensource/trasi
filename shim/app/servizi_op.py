"""`GET /op/servizi?casa_id`: le schede di servizio di una Casa di Quartiere, per la scheda del luogo (§5.2, `T-SHIM-07`).

**Perché serve.** `scheda_servizio` non aveva nessun endpoint del browser: la tabella esiste dalla B1 ma la si leggeva
solo da Metabase. La scheda del luogo (§4.2.2) mostra i servizi di una Casa — titolo, destinatari, quando, come
accedere, referente **come ruolo** — e senza questo endpoint la sezione resterebbe vuota per un guasto invece che per
il vuoto dichiarato.

**Il vuoto si dichiara, non si riempie.** Su questo database `scheda_servizio` ha **0 righe** (misurato): l'endpoint
risponde `{"servizi": []}` e la pagina scrive «Servizi: non nella memoria della rete». È la regola del design system
(«il vuoto è un'informazione»), e la ragione per cui non si seminano dati di esempio per far bella la demo.

**Per un luogo non-Casa l'endpoint non c'entra.** Un POI di OpenStreetMap non ha una Casa, quindi non ha schede di
servizio: la pagina **non** lo chiama e dichiara «Servizi: non nella memoria della rete» (§4.2.2). Se lo chiamasse con
un `casa_id` inventato, l'endpoint risponderebbe `404`, che è corretto e che la pagina non deve trasformare in un
errore visibile.

**Il referente esce come ruolo, mai come persona.** `referente_ruolo` è una colonna `text` con il ruolo
(«operatore», «psicologa», …): non esiste un campo per un nome, e questa è una scelta del modello dati (V5). Lo shim
lo restituisce così com'è, senza dedurre nomi.

**Nessuna scrittura.** Aggiungere o correggere un servizio passa da `proponi_modifica`: `scheda_servizio` è dominio, e
lo shim non lo scrive (V4).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, FastAPI, Query

from .auth import SessioneOperatore, sessione_corrente
from .badge import badge_kb, nome_fonte
from .errori import errore

router = APIRouter()

# Le schede di servizio della Casa, con fonte e orari leggibili. `trasi.orari_testo` è l'unica autorità sulla
# conversione `orari` jsonb → testo («lun 09:00-13:00 · sab chiuso»), la stessa che usano `v_mappa_case` e
# `v_mappa_luoghi`: riscriverla in Python produrrebbe due formati diversi per lo stesso dato.
#
# `scadenza` non si filtra: una scheda scaduta è un'informazione che l'operatore deve vedere (la pagina la marca con
# il filetto d'attenzione e la parola). Filtrare qui significherebbe che una scheda scaduta sparisce in silenzio
# dalla scheda del luogo, che è il modo in cui un servizio finisce per non essere più offerto perché nessuno se ne
# ricorda.
SQL_SERVIZI = """
SELECT s.id, s.titolo, s.descrizione, s.categoria, s.referente_ruolo, s.scadenza,
       s.validata_il, s.url, s.affidabilita,
       (s.scadenza IS NOT NULL AND s.scadenza < current_date) AS scaduta,
       trasi.orari_testo(s.orari) AS orari_testo,
       f.nome AS fonte_nome, f.autorita AS fonte_autorita,
       c.slug AS casa_slug, c.nome AS casa_nome
  FROM trasi.scheda_servizio s
  JOIN trasi.casa c ON c.id = s.casa_id
  LEFT JOIN trasi.fonte f ON f.id = s.fonte_id
 WHERE s.casa_id = $1
 ORDER BY s.categoria NULLS LAST, s.titolo
"""

SQL_CASA = "SELECT id, slug, nome, zona FROM trasi.casa WHERE id = $1"


def voce_servizio(riga: Any) -> dict[str, Any]:
    """Una riga di `scheda_servizio` → l'elemento che la lista dei servizi disegna.

    Il badge è `badge_kb`: una scheda di servizio è memoria della rete — l'ha scritta la Casa, ed è la Casa a
    risponderne. `validata_il` è la data che il badge porta al posto di `data_aggiornamento` (la tabella non ne ha
    una): è la data in cui qualcuno della rete ha verosimilmente guardato la scheda, ed è l'unica data che il
    modello dati offre senza inventarne una.
    """
    fonte = nome_fonte(riga["fonte_autorita"], riga["fonte_nome"])
    return {
        "id": riga["id"],
        "titolo": riga["titolo"],
        "descrizione": riga["descrizione"],
        "categoria": riga["categoria"],
        "orari_testo": riga["orari_testo"],
        "referente_ruolo": riga["referente_ruolo"],
        "scadenza": riga["scadenza"].isoformat() if riga["scadenza"] is not None else None,
        # `scaduta` è deciso nel database (`scadenza < current_date`), dove «oggi» è il giorno di `Europe/Rome`:
        # confrontarlo con la data del processo introdurrebbe una seconda nozione di «oggi», che a mezzanotte diverge.
        "scaduta": bool(riga["scaduta"]),
        "validata_il": riga["validata_il"].isoformat() if riga["validata_il"] is not None else None,
        "url": riga["url"],
        "casa_slug": riga["casa_slug"],
        "casa_nome": riga["casa_nome"],
        "fonte": fonte,
        "fiducia": riga["affidabilita"],
        "badge": badge_kb(fonte, riga["validata_il"], riga["affidabilita"]),
    }


@router.get(
    "/servizi",
    operation_id="op_servizi",
    summary="Schede di servizio di una Casa di Quartiere: titolo, destinatari e descrizione, quando, come si accede "
    "e referente **come ruolo**, con il badge di provenienza. Per un luogo fuori dalla rete l'elenco è vuoto: la "
    "scheda lo dichiara, non lo nasconde.",
    tags=["op"],
)
async def op_servizi(
    casa_id: int | None = Query(
        default=None, ge=1, description="Identificativo della Casa; se omesso, la Casa della sessione."
    ),
    sess: SessioneOperatore = Depends(sessione_corrente),
) -> dict[str, Any]:
    """GET /op/servizi?casa_id → `{casa, servizi}`.

    Senza `casa_id` si usa la **Casa della sessione**, che è quella che l'operatore sta guardando: per un ruolo senza
    Casa (`rete`, `ti`) il parametro è obbligatorio, e l'assenza è un 422 dichiarato — la stessa regola di `oggi`.

    `404` per una Casa inesistente: `{"servizi": []}` è la risposta di una Casa **che esiste** e non ha schede, e
    confondere i due casi direbbe all'operatore «questa Casa non ha servizi» quando invece ha sbagliato l'id.
    """
    riferimento = casa_id if casa_id is not None else sess.casa_id
    if riferimento is None:
        raise errore(422, "parametri non ammessi — casa_id: obbligatorio per un ruolo senza Casa (es. rete)")

    riga_casa = await sess.fetchrow(SQL_CASA, riferimento)
    if riga_casa is None:
        raise errore(404, "Casa non presente nella memoria della rete")

    righe = await sess.fetch(SQL_SERVIZI, riferimento)
    return {
        "casa": {
            "id": riga_casa["id"],
            "slug": riga_casa["slug"],
            "nome": riga_casa["nome"],
            "zona": riga_casa["zona"],
        },
        "servizi": [voce_servizio(riga) for riga in righe],
    }


def monta(applicazione: FastAPI) -> None:
    """Monta il router sotto `/op`, **fuori** dal documento OpenAPI (stessa regola di `mappa_op.monta`)."""
    applicazione.include_router(router, prefix="/op", include_in_schema=False)


__all__ = ["monta", "op_servizi", "router", "voce_servizio"]
