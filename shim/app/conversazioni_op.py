"""Conversazioni della Home: multi-turno reale, storico per Casa, riferimenti alle entità citate.

Perché un modulo a parte e non dentro `chat.py`. `chat.py` è il **proxy** verso Onyx: prende una domanda, la manda,
riporta il testo e il badge. Qui c'è un'altra cosa — una conversazione che **esiste nel tempo**, con una sessione
Onyx riusata fra i turni, i turni scritti in `trasi.turno` e uno storico leggibile con la RLS della Casa. Le due
responsabilità hanno due cicli di vita diversi (il proxy non tocca il database, questo modulo ci vive dentro) e
tenerle in un file solo significherebbe che ogni modifica allo storico mette le mani sul percorso che parla col
provider. Il codice condiviso — configurazione, token, identità, estrazione del testo, badge, riferimenti — resta in
`chat.py` e si **importa**: qui non si duplica nulla di quella logica.

Le quattro decisioni che contano, e dove vivono:

- **Il difetto corretto: `parent_message_id`.** Prima di questo modulo, `chat.py` creava una `chat_session` Onyx per
  **ogni** messaggio e mandava sempre `parent_message_id: -1`. Il risultato era che due domande consecutive erano due
  conversazioni diverse: «e domani?» non aveva un «ieri» da cui partire. Ora la conversazione nasce con **una**
  sessione Onyx (`onyx_session_id`, valorizzata all'`INSERT`: sui ruoli Casa non c'è `UPDATE` su `conversazione`),
  ogni turno salva il `message_id` che Onyx gli assegna e il turno successivo lo passa come padre. Verificato dal
  vivo: `message_id` crescente (`746`, `748`) e la risposta al secondo turno che usa il contesto del primo.
- **404 e non 403 su una conversazione di un'altra Casa.** È la stessa risposta di «non esiste», e la differenza non
  è cortesia: un `403` direbbe a chi prova che quella conversazione **esiste** e appartiene a un altro, cioè
  rivelerebbe l'esistenza. La RLS della Casa è comunque l'autorità — il `SELECT` non trova la riga — e questo modulo
  non aggiunge un secondo filtro che potrebbe divergere: traduce l'esito in uno status.
- **Il `409` non c'è, e la ragione è nel dato.** Il piano lo elenca fra gli errori, ma la tabella non ha una colonna
  di stato e la retention è una scadenza, non una chiusura: una conversazione scaduta è **cancellata** da
  `scadi_conversazioni()`, quindi «scaduta» e «non esiste» sono lo stesso stato e prendono entrambi `404`. Inventare
  un `409` su un campo che non esiste significherebbe un ramo irraggiungibile, cioè codice che sembra coprire un
  caso e non copre niente.
- **Nessuna scrittura del dominio, V4 intatta.** `conversazione` e `turno` non sono dominio: sono la memoria della
  chat, come `messaggio` per la bacheca interna (`db/015`, decisione §2). Non passa da qui nessuna modifica a
  `luogo`, `casa`, `evento`, `proposta`: quelle restano dietro proposta → approvazione → applicazione.

**V5, e vale la pena scriverlo perché è l'unico punto in cui il testo dell'operatore finisce su disco.** Il turno
salva la domanda dell'operatore, che è testo libero: passa dal filtro anti-PII **prima** di essere scritto (un
messaggio con un telefono è `422` e non lascia riga), e il troncamento del titolo a 40 caratteri avviene sul testo
**già** filtrato. Nessun altro campo del turno ha testo libero: niente nome, niente IP, niente user-agent.

**Log senza corpo (§12).** Da qui non si registra né il messaggio, né la risposta, né il titolo: il middleware di
`main.py` scrive `operationId`, stato e ruolo, e basta.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, FastAPI, Query
from pydantic import BaseModel, ConfigDict, Field

from .auth import SessioneOperatore, sessione_corrente
from .badge import FUSO_ITALIANO
from .chat import (
    DETAIL_CASA_SENZA_IDENTITA,
    DETAIL_CHAT_NON_CONFIGURATA,
    FONTE_NON_DICHIARATA,
    Guasto,
    _conversa,
    apri_sessione,
    configurazione,
    email_onyx_della_casa,
    prepara_invio,
)
from .errori import errore

router = APIRouter()

# Dettagli d'errore. Il 404 è **uno solo** per «non esiste» e «non è tua»: due messaggi diversi renderebbero le due
# situazioni distinguibili, che è esattamente ciò che il 404 unico esiste per impedire.
DETAIL_CONVERSAZIONE_NON_TROVATA = "conversazione non trovata"

# Il tetto di pagina dello storico. Lo storico è fatto per essere scorso — la retention è 30 giorni e una Casa che
# lavora tutto il giorno ne produce poche al giorno — non per essere esportato in blocco.
TETTO_CONVERSAZIONI = 200

# Le due parti di un turno, come le scrive il CHECK della tabella: sono il vocabolario, non un enum di comodo.
RUOLO_OPERATORE = "operatore"
RUOLO_ASSISTENTE = "assistente"


class ConversazioneIn(BaseModel):
    """Il corpo di `POST /op/conversazioni`: **vuoto**, e `extra="forbid"` lo impone (V5).

    Non c'è un `casa_id` perché la Casa è quella della sessione, non una scelta del chiamante: è lo stesso principio
    per cui `sessione_corrente` fa `SET LOCAL ROLE` prima di ogni query. Un corpo con una chiave in più è un `422` di
    validazione, non un campo ignorato in silenzio.
    """

    model_config = ConfigDict(extra="forbid")


class MessaggioIn(BaseModel):
    """Il corpo di `POST /op/conversazioni/{id}/messaggi`: `{"messaggio"}`, nient'altro (`extra="forbid"`).

    Il tetto di 2000 caratteri è lo stesso di `chat.MessaggioIn` e di `trasi.messaggio.testo`: tiene una domanda di
    sportello con il contesto necessario. `conversazione_id` **non** sta qui: è nel percorso, dove non si può
    confondere con un campo del corpo che verrebbe da un altro posto.
    """

    model_config = ConfigDict(extra="forbid")

    messaggio: str = Field(
        min_length=1,
        max_length=2000,
        description="Domanda dell'operatore per l'assistente (max 2000 caratteri).",
    )


def _ts(valore: Any) -> str:
    """Un istante del database come stringa ISO 8601 **nel fuso della rete** (`Europe/Rome`), o `""`.

    Il fuso è quello che il resto dello shim usa (`badge.FUSO_ITALIANO`, `vicinanza.FUSO`): il database risponde in
    UTC perché è la sua sessione, e lasciarlo così significherebbe che l'ora di un turno e l'ora dentro un badge sono
    in due fusi diversi — la stessa riga di UI mostrerebbe `09:42` nell'etichetta e `07:42` accanto. La conversione è
    sull'**istante** (non sulla stringa): l'ora mostrata è quella che l'operatore ha davanti all'orologio.

    La stringa non si riformatta: nessun `strftime`, nessun testo italiano. Formattare qui sarebbe un secondo posto
    in cui la data si compone, e §3.2 dice che il testo già composto non si ricompone — chi mostra sceglie il formato.
    """
    if isinstance(valore, datetime):
        return valore.astimezone(ZoneInfo(FUSO_ITALIANO)).isoformat()
    return valore if isinstance(valore, str) else ""


def _turno(riga: Any) -> dict[str, Any]:
    """Una riga di `trasi.turno` come la vuole la UI: ruolo, testo, fonte (verbatim), riferimenti, istante.

    `fonte` è `None` sull'astensione — «non c'è fonte» è un'informazione e la UI la usa per **non** disegnare
    l'etichetta. Non si sostituisce con una stringa vuota: `""` sarebbe un'etichetta vuota, che è peggio di nessuna
    etichetta. `riferimenti` è sempre una lista (anche vuota) per la stessa ragione: chi legge non deve distinguere
    «assente» da «nessuno».
    """
    riferimenti = riga["riferimenti"]
    return {
        "id": riga["id"],
        "ruolo": riga["ruolo"],
        "testo": riga["testo"],
        "fonte": riga["fonte"],
        "riferimenti": list(riferimenti) if isinstance(riferimenti, list) else [],
        "ts": _ts(riga["ts"]),
    }


async def _conversazione_della_casa(sess: SessioneOperatore, conversazione_id: int) -> Any:
    """La conversazione **se è della Casa della sessione**, altrimenti `404`.

    La query non porta un `WHERE casa_id = …`: la RLS della Casa è l'autorità sulla visibilità, e riscrivere il
    filtro qui creerebbe una seconda copia della regola — che il giorno in cui la policy cambia resta indietro in
    silenzio. La query chiede la riga; se il ruolo non può vederla, la riga non c'è. È lo stesso disegno di
    `messaggi.py`, dove la visibilità è della policy e il modulo non la ripete.
    """
    riga = await sess.fetchrow(
        """
        SELECT id, titolo, onyx_session_id, creato_ts, ultimo_ts
          FROM trasi.conversazione
         WHERE id = $1
        """,
        conversazione_id,
    )
    if riga is None:
        raise errore(404, DETAIL_CONVERSAZIONE_NON_TROVATA)
    return riga


async def _ultimo_turno_assistente(sess: SessioneOperatore, conversazione_id: int) -> Any:
    """L'ultimo turno **dell'assistente** della conversazione, o `None` se non ce n'è ancora uno.

    Si cerca l'ultimo turno dell'assistente e non l'ultimo turno in assoluto: il padre di una domanda è la risposta
    precedente, e un turno dell'operatore non ha un `message_id` di Onyx da passare. `ORDER BY id DESC` e non
    `ts DESC`: due turni scritti nello stesso istante (è il caso normale: domanda e risposta nella stessa
    transazione logica) hanno lo stesso `ts` al microsecondo solo per caso, mentre `id` è monotono per costruzione.
    """
    return await sess.fetchrow(
        """
        SELECT onyx_message_id
          FROM trasi.turno
         WHERE conversazione_id = $1 AND ruolo = $2
         ORDER BY id DESC
         LIMIT 1
        """,
        conversazione_id,
        RUOLO_ASSISTENTE,
    )


async def _scrivi_turno(
    sess: SessioneOperatore,
    conversazione_id: int,
    ruolo: str,
    testo: str,
    *,
    fonte: str | None = None,
    riferimenti: list[dict[str, Any]] | None = None,
    onyx_message_id: int | None = None,
) -> Any:
    """Scrive un turno e ne restituisce la riga (`id`, `ts`).

    `INSERT` colonnare e diretto, senza funzione: il titolo della conversazione e l'`ultimo_ts` li calcola il
    trigger `BEFORE INSERT` di `db/021`, che è l'unico posto in cui quella regola deve stare — un `UPDATE` da qui
    sarebbe anche rifiutato dai permessi (sui ruoli Casa c'è `UPDATE` solo su `letto_ts` di `messaggio`, non su
    `conversazione`), ed è giusto: una conversazione non si modifica, si crea e si legge.

    `riferimenti` si passa come lista Python e **non** come stringa JSON: il codec `jsonb` del pool serializza già
    (`db.py`, `_prepara_connessione`), e serializzare qui *e* là produrrebbe una stringa JSON dentro un `jsonb` —
    il difetto già misurato su `proposta.payload` (`scritture.py`), che si vede solo molto dopo, quando qualcuno
    prova a leggere il campo.
    """
    return await sess.fetchrow(
        """
        INSERT INTO trasi.turno (conversazione_id, ruolo, testo, fonte, riferimenti, onyx_message_id)
        VALUES ($1, $2, $3, $4, $5::jsonb, $6)
        RETURNING id, ts
        """,
        conversazione_id,
        ruolo,
        testo,
        fonte,
        riferimenti or None,
        onyx_message_id,
    )


@router.post(
    "/conversazioni",
    operation_id="op_conversazioni_crea",
    status_code=201,
    summary="Apre una conversazione con l'assistente della rete per la Casa della sessione, con la sua "
    "sessione Onyx già legata: i turni successivi riusano quella, quindi il contesto resta.",
    tags=["op"],
)
async def op_conversazioni_crea(
    corpo: ConversazioneIn | None = None, sess: SessioneOperatore = Depends(sessione_corrente)
) -> dict[str, Any]:
    """POST /op/conversazioni `{}` → 201 `{conversazione_id, creato_ts}`; 401; 503 (database o Onyx).

    La sessione Onyx si apre **qui** e non al primo messaggio, per due ragioni. La prima è che la riga di
    `conversazione` deve uscire da questa chiamata con `onyx_session_id` già valorizzato: sui ruoli Casa non c'è
    `UPDATE` su `conversazione`, quindi un `onyx_session_id` scritto dopo non sarebbe scrivibile — e la sessione
    andrebbe persa al primo riavvio del container, trasformando la conversazione in una serie di domande scollegate.
    La seconda è che così il primo turno è **una** chiamata a Onyx invece di due, e l'operatore aspetta meno.

    Se la sessione Onyx non si apre, si risponde `503` e **non** si crea nessuna conversazione: una conversazione
    senza la sua sessione sarebbe uno storico di domande senza contesto, cioè il difetto che questo modulo corregge.
    """
    # Il corpo è dichiarato opzionale perché la UI manda `{}` (o niente): l'unico contenuto lecito è «nessuno».
    _ = corpo

    # `prepara_invio` non si può usare qui: il suo primo controllo è il PII su un messaggio che non esiste ancora.
    # Token e identità però si controllano **prima** di parlare con Onyx, come là: un 503 dichiarato prima di una
    # chiamata di rete che non potrebbe riuscire.
    configurazione_chat = configurazione()
    if not configurazione_chat.token:
        raise errore(503, DETAIL_CHAT_NON_CONFIGURATA)

    email = await email_onyx_della_casa(sess.casa_id)
    if not email:
        raise errore(503, DETAIL_CASA_SENZA_IDENTITA)

    sessione_onyx = await apri_sessione(configurazione_chat, email)
    if isinstance(sessione_onyx, Guasto):
        raise errore(503, sessione_onyx.detail)

    riga = await sess.fetchrow(
        """
        INSERT INTO trasi.conversazione (casa_id, onyx_session_id)
        VALUES (trasi.casa_corrente(), $1)
        RETURNING id, creato_ts
        """,
        sessione_onyx,
    )
    return {"conversazione_id": riga["id"], "creato_ts": _ts(riga["creato_ts"])}


@router.post(
    "/conversazioni/{conversazione_id}/messaggi",
    operation_id="op_conversazioni_messaggio",
    summary="Pone una domanda dentro una conversazione e riceve la risposta con la fonte (V3) e i "
    "riferimenti. Il turno precedente fa da contesto: la stessa conversazione è un dialogo, non domande "
    "slegate.",
    tags=["op"],
)
async def op_conversazioni_messaggio(
    corpo: MessaggioIn,
    conversazione_id: int,
    sess: SessioneOperatore = Depends(sessione_corrente),
) -> dict[str, Any]:
    """POST /op/conversazioni/{id}/messaggi `{messaggio}` → 200 `{risposta, fonte, riferimenti, turno_id, onyx_message_id}`.

    Errori: `401` senza sessione · `404` se la conversazione non è della propria Casa (**stessa** risposta di «non
    esiste») · `422` su un dato personale nel messaggio · `503` se Onyx non risponde entro il budget dichiarato.

    L'ordine dei controlli è quello di `prepara_invio` — PII, configurazione, identità — e **prima** di tutti c'è il
    404: una conversazione che non è della propria Casa non deve far partire né una lettura dell'identità né una
    chiamata a Onyx, e soprattutto non deve scrivere un turno. Il 404 è anche il motivo per cui la lettura della
    conversazione viene prima del filtro PII: non ha senso dire a un estraneo che il suo testo contiene un telefono.

    Il turno dell'operatore si scrive **dopo** la risposta di Onyx, insieme a quello dell'assistente, e non prima:
    un `503` non deve lasciare una domanda senza risposta nello storico (§4.1.3), e un `422` non deve lasciare la
    riga di un testo che il filtro ha rifiutato. La conseguenza è che i due turni sono due `INSERT` distinti
    eseguiti a risposta arrivata — se il secondo fallisse, il primo resterebbe: è il caso raro che vale un turno
    dell'operatore senza risposta, e non vale una transazione esplicita che coprirebbe un'intera chiamata a un LLM
    (decine di secondi) tenendo aperta una connessione del pool.

    Il `parent_message_id` che va a Onyx è l'`onyx_message_id` dell'**ultimo turno dell'assistente**, oppure `-1`
    al primo turno: è ciò che rende il dialogo un dialogo.
    """
    conversazione = await _conversazione_della_casa(sess, conversazione_id)

    configurazione_chat, email = await prepara_invio(sess, corpo.messaggio)

    sessione_onyx = conversazione["onyx_session_id"]
    if not sessione_onyx:
        # Non dovrebbe accadere: la conversazione nasce con la sessione legata. Se accadesse (una riga scritta da
        # una migrazione a mano, un `onyx_session_id` azzerato), se ne apre una invece di mandare `-1` su una
        # sessione vuota: il dialogo riparte, e la cosa non si trasforma in un errore per l'operatore.
        nuova = await apri_sessione(configurazione_chat, email)
        if isinstance(nuova, Guasto):
            raise errore(503, nuova.detail)
        sessione_onyx = nuova

    precedente = await _ultimo_turno_assistente(sess, conversazione_id)
    padre = precedente["onyx_message_id"] if precedente and precedente["onyx_message_id"] else None

    esito = await _conversa(
        configurazione_chat,
        corpo.messaggio,
        email,
        sessione_id=sessione_onyx,
        parent_message_id=padre,
    )
    if isinstance(esito, Guasto):
        raise errore(503, esito.detail)

    await _scrivi_turno(sess, conversazione_id, RUOLO_OPERATORE, corpo.messaggio)
    # `fonte` NULL = nessuna fonte citata, cioè l'astensione: la UI non disegna nessuna etichetta e il turno non
    # porta una stringa che sembri una provenienza. Il valore di comodo dello shim («nessuna fonte citata nella
    # risposta») è una **diagnosi per chi legge il log**, non un'etichetta da mostrare: se finisse in `fonte`,
    # l'astensione mostrerebbe un'etichetta che, dal vivo, non mostrava — due aspetti diversi per lo stesso turno,
    # che è il difetto che V3 esiste per impedire. La normalizzazione è **una** e vale per la risposta e per la riga
    # scritta, così ricaricare la pagina non cambia quello che si vede.
    fonte = None if esito.fonte == FONTE_NON_DICHIARATA else esito.fonte
    turno = await _scrivi_turno(
        sess,
        conversazione_id,
        RUOLO_ASSISTENTE,
        esito.testo,
        fonte=fonte,
        riferimenti=esito.riferimenti,
        onyx_message_id=esito.messaggio_id,
    )

    return {
        "risposta": esito.testo,
        "fonte": fonte,
        "riferimenti": esito.riferimenti,
        "turno_id": turno["id"],
        "onyx_message_id": esito.messaggio_id,
    }


@router.get(
    "/conversazioni",
    operation_id="op_conversazioni_elenco",
    summary="Elenca le conversazioni della Casa della sessione, dalla più recente, entro la retention "
    "dichiarata: titolo, primo e ultimo istante, numero di turni. Mai quelle di un'altra Casa.",
    tags=["op"],
)
async def op_conversazioni_elenco(
    limite: int = Query(
        default=50,
        ge=1,
        le=TETTO_CONVERSAZIONI,
        description="Quante conversazioni al massimo (1-200).",
    ),
    sess: SessioneOperatore = Depends(sessione_corrente),
) -> dict[str, Any]:
    """GET /op/conversazioni → `{"conversazioni": [{id, titolo, primo_ts, ultimo_ts, turni}]}`, dalla più recente.

    Il `WHERE` non filtra per Casa: la policy `SELECT` di `db/021` fa vedere solo le proprie, ed è la RLS a
    decidere — la stessa autorità che vale per ogni altra tabella del progetto.

    **Compare solo ciò che è avvenuto**, e la condizione è «almeno un turno dell'assistente» (§4.1.3, punto c). Una
    conversazione creata e poi fallita (`503`) ha zero turni: mostrarla in sidebar sarebbe una voce senza titolo che
    l'operatore non può ripulire, e lo storico smetterebbe di essere una lista di cose accadute. La riga vuota resta
    nel database e scade con la retention — non è visibile e non vale una cancellazione da qui (i ruoli Casa non
    hanno `DELETE` su `conversazione`, per disegno).

    Un `EXISTS` per il filtro e una sotto-query per il conteggio, e non un `JOIN … GROUP BY HAVING`: `turni` conta
    **tutti** i turni (domande e risposte — `4` per due domande), mentre il filtro è «esiste una risposta». Con un
    solo `JOIN` filtrato sul ruolo le due cose collasserebbero e `turni` conterebbe solo le risposte: un campo giusto
    per metà, che è il tipo di difetto che nessuno nota finché non conta i turni a mano.
    """
    righe = await sess.fetch(
        """
        SELECT c.id, c.titolo, c.creato_ts, c.ultimo_ts,
               (SELECT count(*) FROM trasi.turno t WHERE t.conversazione_id = c.id) AS turni
          FROM trasi.conversazione c
         WHERE EXISTS (
                 SELECT 1 FROM trasi.turno r
                  WHERE r.conversazione_id = c.id AND r.ruolo = $2
               )
         ORDER BY c.ultimo_ts DESC, c.id DESC
         LIMIT $1
        """,
        limite,
        RUOLO_ASSISTENTE,
    )
    return {
        "conversazioni": [
            {
                "id": r["id"],
                "titolo": r["titolo"],
                # Il primo istante della conversazione è quello della sua creazione: la UI mostra «Conversazione
                # del …» con questa data, e la conversazione è ciò che l'operatore ha aperto, non il primo turno.
                "primo_ts": _ts(r["creato_ts"]),
                "ultimo_ts": _ts(r["ultimo_ts"]),
                "turni": r["turni"],
            }
            for r in righe
        ]
    }


@router.get(
    "/conversazioni/{conversazione_id}",
    operation_id="op_conversazioni_dettaglio",
    summary="I turni di una conversazione, in ordine: domanda dell'operatore, risposta dell'assistente con "
    "la sua fonte. 404 se non esiste o se è di un'altra Casa.",
    tags=["op"],
)
async def op_conversazioni_dettaglio(
    conversazione_id: int, sess: SessioneOperatore = Depends(sessione_corrente)
) -> dict[str, Any]:
    """GET /op/conversazioni/{id} → `{id, titolo, creato_ts, turni: [{ruolo, testo, fonte, riferimenti, ts}]}`.

    `404` anche per una conversazione di un'altra Casa, con lo **stesso** dettaglio: la RLS non fa vedere la riga e
    questo modulo non aggiunge un `403` che rivelerebbe l'esistenza. Nessuna paginazione: una conversazione della
    chat di sportello è di pochi turni, e un tetto arbitrario nasconderebbe proprio la parte vecchia — quella che
    si sta cercando.
    """
    conversazione = await _conversazione_della_casa(sess, conversazione_id)
    righe = await sess.fetch(
        """
        SELECT id, ruolo, testo, fonte, riferimenti, ts
          FROM trasi.turno
         WHERE conversazione_id = $1
         ORDER BY id
        """,
        conversazione_id,
    )
    return {
        "id": conversazione["id"],
        "titolo": conversazione["titolo"],
        "creato_ts": _ts(conversazione["creato_ts"]),
        "turni": [_turno(r) for r in righe],
    }


def monta(applicazione: FastAPI) -> None:
    """Monta il router sotto `/op`, **fuori** dal documento OpenAPI.

    Stesso criterio di `chat.monta`: il prefisso è quello che la UI chiama (`/api/shim/op/conversazioni`, con Caddy
    che toglie `/api/shim`), e `include_in_schema=False` tiene questi endpoint fuori dal documento che è il
    contratto congelato con Onyx — il gate V-09 lo verifica per **uguaglianza**, quindi un endpoint del browser in
    più lo farebbe fallire. La visibilità non cambia: `include_in_schema` riguarda il documento, non il routing.
    """
    applicazione.include_router(router, prefix="/op", include_in_schema=False)


__all__ = [
    "DETAIL_CONVERSAZIONE_NON_TROVATA",
    "ConversazioneIn",
    "MessaggioIn",
    "RUOLO_ASSISTENTE",
    "RUOLO_OPERATORE",
    "TETTO_CONVERSAZIONI",
    "monta",
    "op_conversazioni_crea",
    "op_conversazioni_dettaglio",
    "op_conversazioni_elenco",
    "op_conversazioni_messaggio",
    "router",
]
