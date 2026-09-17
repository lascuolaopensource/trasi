"""I «Numeri» della Casa (piano §4.3.1 e §5.3): le sei serie della sezione Account.

Un solo endpoint, `GET /op/casa/statistiche?dal&al`, e una sola fonte: `trasi.fn_statistiche_casa`
(`db/022_statistiche.sql`). Questo modulo **non conta nulla e non maschera nulla** — è deliberato, ed è
la parte che conta:

- **il conteggio** sta nella funzione SQL, sul filtro di finestra, con gli stessi predicati delle viste di
  reporting (`v_report_mensile`, `v_destinazioni`) ma su un intervallo arbitrario;
- **il k-anonimato** sta nella funzione, che applica `trasi.k_anon()` **per cella**: sotto
  `[P] k_anonimato` la colonna `n` è `NULL` e `n_label` è `'<5'`, e il numero grezzo non è mai una colonna
  di uscita. Se lo shim ricalcolasse la soglia in Python, il numero sotto soglia avrebbe già attraversato
  la rete e il presidio sarebbe solo una convenzione di resa. Qui la soglia si **legge** (`p_int`) e si
  dichiara al chiamante, non si applica.

**Perché il filtro per Casa è nel parametro della funzione e non in un `WHERE` esterno.** La funzione è
`SECURITY INVOKER` e riceve `p_casa`: il ruolo della sessione la esegue con i propri privilegi, quindi le
policy di `richiesta`/`proposta`/`scheda_servizio` restano in vigore. La Casa viene da `sess.casa_id` —
dalla sessione, mai da un parametro: un endpoint che accettasse `?casa=` sarebbe la prima via con cui un
operatore legge i numeri di un'altra Casa (Principio 3).

**Perché il periodo massimo è 366 giorni.** La funzione aggrega su `richiesta`, che cresce di ~300 righe al
mese su questa rete: 366 giorni è il tetto oltre il quale il cruscotto smette di essere un cruscotto di
sportello e diventa un export. Il rifiuto è dichiarato (`422`), non troncato in silenzio: una finestra
tagliata a metà mostrerebbe numeri giusti per un periodo che l'operatore non ha chiesto.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query

from .auth import SessioneOperatore, sessione_corrente
from .badge import badge_kb
from .errori import DETAIL_RUOLO_SENZA_ACCESSO, errore
from .vicinanza import oggi_locale

router = APIRouter()

# Finestra predefinita: «ultimi 30 giorni», come dice §5.3. Il calcolo è `al - 30`, non `al - 29`, ed è
# quello dell'esempio del piano (`dal: 2026-08-17`, `al: 2026-09-16`): è una finestra di trenta giorni
# **indietro**, non trenta giorni di calendario contati a rovescio.
GIORNI_DEFAULT = 30

# Tetto dichiarato (§5.3): oltre, `422`. Vedi la nota in testa al modulo.
GIORNI_MASSIMI = 366

# Ripiego della soglia se `[P] k_anonimato` non è leggibile: è il default del seed `db/003_parametri.sql`.
# Serve perché una soglia assente non deve trasformare il cruscotto in un 500, e perché il numero che
# finisce nella frase di riservatezza sia quello vero: la mascheratura avviene comunque **nel database**,
# questo valore lo shim lo usa solo per spiegarla.
SOGLIA_FALLBACK = 5


async def _soglia_riservatezza(sess: SessioneOperatore) -> int:
    """`[P] k_anonimato`, letto a ogni chiamata: il TI lo cambia senza deploy (e senza riavviare lo shim)."""
    valore = await sess.fetchval("SELECT trasi.p_int('k_anonimato')")
    return int(valore) if valore else SOGLIA_FALLBACK


def _periodo(dal: date | None, al: date | None) -> tuple[date, date]:
    """La finestra richiesta, validata: `(dal, al)` in ordine, non più lunga di `GIORNI_MASSIMI`.

    Il controllo sta qui e non in un validatore pydantic perché le due date non sono indipendenti —
    una finestra è una coppia — e il messaggio deve dire all'operatore **quale** delle due regole ha
    violato, invece di un errore per campo.
    """
    fine = al or oggi_locale()
    inizio = dal or (fine - timedelta(days=GIORNI_DEFAULT))

    if inizio > fine:
        raise errore(422, f"periodo invertito: dal ({inizio.isoformat()}) è successivo ad al ({fine.isoformat()})")
    if (fine - inizio).days > GIORNI_MASSIMI:
        raise errore(
            422,
            f"periodo troppo lungo: {GIORNI_MASSIMI} giorni al massimo, richiesti {(fine - inizio).days}",
        )
    return inizio, fine


def _blocchi(righe: list[Any]) -> list[dict[str, Any]]:
    """Le righe piatte della funzione, raggruppate nei sei blocchi con la loro provenienza.

    Il raggruppamento è in Python perché la funzione restituisce **una riga per cella**: è la forma che tiene
    il k-anonimato per cella e l'ordinamento dichiarato, senza che il database debba comporre json.

    La provenienza (V3) arriva dal database — `fonte_nome` e `fonte_fiducia` sono quelle della memoria della
    rete (`fonte.tipo_accesso = 'kb'`, `autorita` come nome umano) — e il **badge** lo compone `badge.badge_kb`,
    lo stesso di ogni altro endpoint: la stessa informazione porta la stessa etichetta in chat, nel biglietto e
    qui, e se il badge cambiasse forma cambierebbe in un posto solo. Un `aggiornato_il` assente resta `None`, e
    il badge scrive `agg. —` invece di inventare una data (`badge._data_italiana`).

    **Il vuoto si dichiara in due modi distinti, e non sono lo stesso fatto:**

    - `vuoto: true`, `righe: []` — il blocco non ha prodotto nessuna cella: non c'è nulla da disegnare, e non
      c'è nemmeno un grafico a zero da mostrare;
    - `vuoto: true`, `righe: [...]` — il blocco ha celle ma **tutte a zero** (destinazioni senza indirizzamenti,
      attrezzoteca con oggetti e nessun movimento): le righe ci sono e vanno elencate, ognuna con il proprio `—`.

    In entrambi i casi la frase da mostrare è `nota_vuoto`, e la scrive il **database** (`vuoto_testo`): la
    pagina non riscrive «Nessun evento in programma» nel JavaScript, altrimenti la revisione dei testi
    dovrebbe passare da due file.
    """
    blocchi: list[dict[str, Any]] = []
    corrente: dict[str, Any] | None = None

    def chiudi(blocco: dict[str, Any]) -> None:
        """Fissa i valori che si conoscono solo alla fine del blocco: soglia scattata e blocco a zero."""
        blocco["sotto_soglia"] = any(riga["sotto_soglia"] for riga in blocco["righe"])
        blocco["vuoto"] = not blocco["righe"] or all(
            riga["tipo_riga"] == "conteggio" and riga["valore_label"] == "—" for riga in blocco["righe"]
        )

    for riga in righe:
        if corrente is None or corrente["id"] != riga["blocco"]:
            if corrente is not None:
                chiudi(corrente)
            fonte = riga["fonte_nome"]
            aggiornato = riga["aggiornato_il"]
            fiducia = riga["fonte_fiducia"]
            corrente = {
                "id": riga["blocco"],
                "titolo": riga["titolo"],
                "ordine": riga["ordine"],
                "nota_vuoto": riga["vuoto_testo"],
                "fonte": fonte,
                "fiducia": fiducia,
                "aggiornato_il": aggiornato.isoformat() if aggiornato else None,
                "badge": badge_kb(fonte, aggiornato, fiducia) if fonte else None,
                "sotto_soglia": False,
                "vuoto": True,
                "righe": [],
            }
            blocchi.append(corrente)

        # La riga `vuoto` è la dichiarazione del blocco senza celle, non una cella: la frase è già in
        # `nota_vuoto`, e metterla anche in `righe` la farebbe disegnare come se fosse un dato.
        if riga["tipo_riga"] == "vuoto":
            continue

        corrente["righe"].append(
            {
                "etichetta": riga["etichetta"],
                "nota_riga": riga["nota_riga"],
                # `tipo_riga` distingue una cella da contare da una voce nominata (i prossimi eventi):
                # la pagina disegna una barra solo per la prima, e la seconda è testo.
                "tipo_riga": riga["tipo_riga"],
                # `valore` e `valore_label` escono entrambi, e la UI legge **solo** `valore_label`. `valore`
                # è `None` esattamente quando la soglia scatta, quindi non c'è nulla da nascondere a valle:
                # il numero grezzo sotto soglia non è mai stato calcolato fuori dal database. Averli tutti e
                # due permette di verificare la corrispondenza (valore nullo ⇔ etichetta non numerica)
                # senza dedurla dal testo.
                "valore": riga["n"],
                "valore_label": riga["n_label"],
                "sotto_soglia": bool(riga["sotto_soglia"]),
            }
        )

    if corrente is not None:
        chiudi(corrente)
    return blocchi


@router.get(
    "/casa/statistiche",
    operation_id="op_casa_statistiche",
    summary="I numeri del funzionamento della Casa nel periodo scelto: richieste per categoria ed esito, "
    "destinazioni, eventi in programma, schede in scadenza e proposte, uso dell'attrezzoteca. Sotto la "
    "soglia di riservatezza il numero non è mostrato: si legge l'etichetta «<5».",
    tags=["op"],
)
async def op_casa_statistiche(
    dal: date | None = Query(default=None, description="Inizio periodo (ISO AAAA-MM-GG); se omesso, 30 giorni prima di al."),
    al: date | None = Query(default=None, description="Fine periodo (ISO AAAA-MM-GG); se omessa, oggi."),
    sess: SessioneOperatore = Depends(sessione_corrente),
) -> dict[str, Any]:
    """GET /op/casa/statistiche?dal=&al= — le sei serie della sezione «Numeri», della **propria** Casa.

    L'uscita è per blocchi, e ogni riga porta `valore_label` — la **sola** cosa che la pagina disegna.
    `valore` esiste per il controllo di coerenza e per un consumatore che voglia fare aritmetica sulle
    celle non mascherate, ed è `None` dove la soglia scatta: non c'è un numero da leggere, non c'è un
    numero da proteggere a valle.

    `soglia_riservatezza` è la soglia **in vigore** (da `[P] k_anonimato`): serve alla pagina per spiegare
    in parole il simbolo «<5» che trova nelle etichette, e per non doverlo scrivere a mano nel JavaScript —
    un numero di policy duplicato nella pagina sarebbe la prima cosa a divergere.
    """
    if sess.casa_id is None:
        # Difesa in profondità: una sessione `/op` nasce da `trasi.sessione.casa_id` (FK su `casa`), quindi
        # una Casa c'è sempre. Se mancasse, i numeri non avrebbero un soggetto e «tutte le Case» sarebbe la
        # risposta peggiore possibile.
        raise errore(403, DETAIL_RUOLO_SENZA_ACCESSO)

    inizio, fine = _periodo(dal, al)
    soglia = await _soglia_riservatezza(sess)

    righe = await sess.fetch(
        """
        SELECT blocco, titolo, ordine, ordine_riga, tipo_riga, etichetta, nota_riga,
               n, n_label, sotto_soglia, aggiornato_il, fonte_nome, fonte_fiducia, vuoto_testo
          FROM trasi.fn_statistiche_casa($1, $2, $3)
        """,
        sess.casa_id,
        inizio,
        fine,
    )

    return {
        "casa": sess.casa_slug,
        "periodo": {"dal": inizio.isoformat(), "al": fine.isoformat()},
        "soglia_riservatezza": soglia,
        "blocchi": _blocchi(righe),
    }


__all__ = ["GIORNI_DEFAULT", "GIORNI_MASSIMI", "op_casa_statistiche", "router"]
