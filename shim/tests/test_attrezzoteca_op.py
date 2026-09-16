"""Test dell'area operatore dell'attrezzoteca: `GET /op/movimenti_da_confermare` (US-5.3).

La scheda esiste perché la UI dell'operatore la chiama (`deployment/home/operatore.js`, «Movimenti da confermare»):
senza, il pannello resta vuoto e un prestito in attesa non si vede da nessuna parte.

Cosa difendono questi test, e perché **live**. Tre proprietà non sono verificabili con una sessione finta:

1. il movimento proposto dalla Casa cedente **compare** a entrambe le Case coinvolte (cedente e ricevente);
2. i movimenti di **altre** Case non compaiono. È la proprietà che rende la vista `v_movimenti_da_confermare`
   utilizzabile: essendo `security_invoker=false`, al suo interno la RLS di `movimento` non vede il chiamante, quindi
   l'unico filtro è il `WHERE` della query. Un test con una sessione finta proverebbe che il `WHERE` è *scritto*, non
   che *filtra*;
3. un movimento **confermato** esce dalla lista: la vista seleziona `stato='proposto'`, e la conferma (che spetta
   alla ricevente, `conferma_movimento`) è il confine osservabile dell'elenco.

Il corpo della risposta è quello che la UI legge (`dati.movimenti`) con i campi che usa per la riga
(`oggetto`, `da_casa_slug`, `a_casa_slug`, `dal`, `al`): sono asseriti per nome, così il disallineamento con
`operatore.js` si vede qui e non in produzione.

**La sessione è quella vera.** La fixture fa `POST /login` con le credenziali della Casa e porta il cookie
`trasi_sessione` fino a `/op/…`, esattamente come il browser: nessun `dependency_overrides`. È una scelta
deliberata — sostituire la dipendenza di sessione renderebbe questi test verdi anche se l'autenticazione fosse
rotta, cioè lascerebbe scoperto proprio il tratto da cui dipende tutto l'accesso dell'operatore. La conseguenza è
che questi test dipendono dallo stack vivo (database + `credenziale_casa` seminata), come gli altri test `live`.
"""

from __future__ import annotations

import asyncio
from contextlib import ExitStack
from typing import Any

import pytest
from fastapi.testclient import TestClient

import ambiente

# Le Case usate dalle fixture: San Bao è la Casa della sessione, Bozzano la cedente tipica, Tuturano la terza Casa
# che serve a provare l'esclusione (un movimento fra due Case che non sono la nostra).
SLUG_PRINCIPALE = ambiente.SLUG_SANBAO
SLUG_CEDENTE = ambiente.SLUG_BOZZANO
SLUG_TERZA = "tuturano"

NOME_OGGETTO = "ZZ-oggetto di prova attrezzoteca"


def _intestazioni() -> dict[str, str]:
    return {"X-Trasi-Key": ambiente.CHIAVE_SHIM or "chiave-di-test"}


def _password_di(slug: str) -> str:
    """La password **iniziale** della Casa, quella seminata da db/013: `<slug senza trattini>2026!`.

    I test non inventano credenziali e non ne scrivono di proprie nel database: usano il seme documentato, come gli
    altri test usano le email seminate (`op.san-bao@trasi.local`) e gli id dei luoghi. Se il TI ha ruotato la
    password, il login risponde 401 e `accedi` lo dice con il nome della Casa: è informazione utile, non un
    fallimento da mascherare con un salto.
    """
    return slug.replace("-", "") + "2026!"


# --- fixture sul database (richiedono lo stack acceso) --------------------------------------------------------


async def _crea_oggetto(slug: str, nome: str, *, quantita: int = 1) -> int:
    """Crea l'oggetto di fixture come `trasi_owner`.

    Non è una scorciatoia: `oggetto` nasce **solo** dal flusso proposte (V4) e nessun ruolo Casa ha `INSERT` sulla
    tabella — la fixture usa quindi il ruolo del caricamento iniziale, che `v_scritture_senza_audit` tratta come
    scrittura dichiarata e non come violazione. Provare a inserirlo come Casa fallirebbe, ed è il comportamento
    voluto.
    """
    conn = await ambiente.connessione_amministratore()
    try:
        await conn.execute("SET ROLE trasi_owner")
        return await conn.fetchval(
            """
            INSERT INTO trasi.oggetto (nome, quantita, casa_id, condizione, aggiornato_ts)
            VALUES ($1, $2, (SELECT id FROM trasi.casa WHERE slug = $3), 'integro', now())
            RETURNING id
            """,
            nome,
            quantita,
            slug,
        )
    finally:
        await conn.close()


async def _pulisci(oggetti: list[int], movimenti: list[int]) -> None:
    """Rimuove le righe di prova con la connessione amministrativa.

    Nessun ruolo applicativo ha `DELETE` su `movimento` né su `oggetto` (V4 regola 7: si ritira, non si cancella),
    quindi la pulizia passa da qui — mai per «far passare» un comportamento, solo per togliere ciò che il test ha
    creato. Si rimuovono anche le righe `audit` collegate ai movimenti di prova: l'`audit` è append-only e non ha
    chiave esterna su `movimento`, quindi senza questa riga le tracce dei test resterebbero a contare per sempre.
    """
    conn = await ambiente.connessione_amministratore()
    try:
        if movimenti:
            await conn.execute(
                "DELETE FROM trasi.audit WHERE entita = 'movimento' AND entita_id = ANY($1::int[])", movimenti
            )
        if oggetti:
            await conn.execute(
                "DELETE FROM trasi.audit WHERE entita = 'oggetto' AND entita_id = ANY($1::int[])", oggetti
            )
        if movimenti:
            await conn.execute("DELETE FROM trasi.movimento WHERE id = ANY($1::int[])", movimenti)
        if oggetti:
            await conn.execute("DELETE FROM trasi.oggetto WHERE id = ANY($1::int[])", oggetti)
    finally:
        await conn.close()


async def _stato_movimento(movimento_id: int) -> str | None:
    conn = await ambiente.connessione(ruolo="rete")
    try:
        return await conn.fetchval("SELECT stato::text FROM trasi.movimento WHERE id = $1", movimento_id)
    finally:
        await conn.close()


# --- client con la sessione di una Casa -----------------------------------------------------------------------


@pytest.fixture
def accedi():
    """Un `TestClient` autenticato, che cambia Casa rifacendo il login — come farebbe un operatore.

    `POST /login` con le credenziali seminate da db/013, poi il cookie `trasi_sessione` viaggia su ogni richiesta
    successiva: è lo stesso percorso del browser (`/api/shim/login`, poi `/api/shim/op/…`), **senza alcun override
    delle dipendenze**. Un 401 qui significa che l'accesso dell'operatore è rotto, e va visto invece che aggirato.

    Un solo `TestClient` per test, e non uno per Casa: il pool di connessioni dello shim è globale al processo e vive
    nel ciclo di eventi del client che l'ha aperto, quindi due client contemporanei — due cicli — condividerebbero un
    pool che appartiene all'altro (misurato: 500 «connection was closed in the middle of operation»). Il cambio di
    Casa è quindi un nuovo login sullo stesso client, che è anche ciò che accade davvero quando l'operatore cambia
    postazione.
    """
    if not ambiente.dsn_disponibile():
        pytest.skip(f"database non raggiungibile ({ambiente.dsn_test()})")
    ambiente.configura_ambiente()

    from app.main import crea_app

    with ExitStack() as pila:
        client = pila.enter_context(TestClient(crea_app(), raise_server_exceptions=False))
        pila.callback(lambda: client.post("/logout", headers=_intestazioni()))

        def accedi_come(slug: str) -> TestClient:
            risposta = client.post("/login", json={"casa": slug, "password": _password_di(slug)})
            assert risposta.status_code == 200, (
                f"login della Casa {slug} non riuscito ({risposta.status_code}): {risposta.text}"
            )
            return client

        yield accedi_come


def _proponi(client: TestClient, oggetto_id: int, a_casa: str, **date: str) -> int:
    """Propone un prestito con `POST /op/movimento` e ritorna l'id: la fixture usa il percorso vero dell'endpoint.

    Creare il movimento con un `INSERT` di prova proverebbe la query di `movimenti_da_confermare` su una riga che
    l'endpoint di scrittura non è in grado di produrre; passando da `POST /op/movimento` la riga nasce come nasce in
    produzione (RLS della cedente inclusa), e una rottura dell'uno si vede nell'altro.
    """
    risposta = client.post(
        "/op/movimento",
        headers=_intestazioni(),
        json={"oggetto_id": oggetto_id, "a_casa": a_casa, **date},
    )
    assert risposta.status_code == 201, risposta.text
    return risposta.json()["movimento_id"]


def _movimenti(client: TestClient) -> list[dict[str, Any]]:
    risposta = client.get("/op/movimenti_da_confermare", headers=_intestazioni())
    assert risposta.status_code == 200, risposta.text
    corpo = risposta.json()
    assert set(corpo) == {"movimenti"}, f"la UI legge `dati.movimenti`: trovato {set(corpo)}"
    return corpo["movimenti"]


def _trova(movimenti: list[dict[str, Any]], movimento_id: int) -> dict[str, Any] | None:
    return next((m for m in movimenti if m["id"] == movimento_id), None)


# --- il movimento compare a entrambe le Case coinvolte --------------------------------------------------------


@pytest.mark.live
def test_movimenti_da_confermare_mostra_il_prestito_atteso_dalla_casa_ricevente(accedi):
    """Un prestito in attesa verso la nostra Casa compare, con i campi che la UI usa per la riga.

    È il caso normale della scheda: l'operatore di San Bao vede il movimento proposto da Bozzano e lo conferma. I
    campi asseriti sono quelli letti da `operatore.js` (`oggetto`, `da_casa_slug`, `a_casa_slug`, `dal`, `al`): un
    rinomino nell'endpoint deve far fallire questo test, non svuotare il pannello.
    """
    oggetto = asyncio.run(_crea_oggetto(SLUG_CEDENTE, NOME_OGGETTO, quantita=3))
    movimenti: list[int] = []
    try:
        cedente = accedi(SLUG_CEDENTE)
        movimenti.append(_proponi(cedente, oggetto, SLUG_PRINCIPALE, al="2026-12-31"))

        elenco = _movimenti(accedi(SLUG_PRINCIPALE))

        voce = _trova(elenco, movimenti[0])
        assert voce is not None, f"il prestito atteso dalla nostra Casa deve comparire: {elenco}"
        assert voce["oggetto"] == NOME_OGGETTO
        assert voce["oggetto_id"] == oggetto
        assert voce["da_casa_slug"] == SLUG_CEDENTE
        assert voce["a_casa_slug"] == SLUG_PRINCIPALE
        assert voce["al"] == "2026-12-31"
        assert voce["dal"] <= "2026-12-31", f"`dal` è una data ISO: {voce['dal']}"
        assert voce["giorni_attesa"] == 0
        assert asyncio.run(_stato_movimento(movimenti[0])) == "proposto"
    finally:
        asyncio.run(_pulisci([oggetto], movimenti))


@pytest.mark.live
def test_movimenti_da_confermare_mostra_il_prestito_alla_casa_cedente(accedi):
    """Anche la Casa **cedente** vede il movimento proposto: le ha prestato l'oggetto e attende la conferma.

    Senza questo ramo del filtro l'operatore che ha proposto il prestito non avrebbe modo di sapere che è ancora in
    attesa — è la differenza fra «il mio prestito è partito» e «il mio prestito è ancora una proposta».
    """
    oggetto = asyncio.run(_crea_oggetto(SLUG_PRINCIPALE, NOME_OGGETTO))
    movimenti: list[int] = []
    try:
        client = accedi(SLUG_PRINCIPALE)
        movimenti.append(_proponi(client, oggetto, SLUG_CEDENTE))

        elenco = _movimenti(client)

        voce = _trova(elenco, movimenti[0])
        assert voce is not None, f"la cedente deve vedere il proprio prestito in attesa: {elenco}"
        assert voce["da_casa_slug"] == SLUG_PRINCIPALE
        assert voce["a_casa_slug"] == SLUG_CEDENTE
    finally:
        asyncio.run(_pulisci([oggetto], movimenti))


@pytest.mark.live
def test_movimenti_da_confermare_non_mostra_i_prestiti_di_altre_case(accedi):
    """Un prestito fra due Case che non sono la nostra **non** compare, benché la vista sia `security_invoker=false`.

    È la proprietà per cui il filtro sta nella query: la vista legge `movimento` con i privilegi del proprietario,
    quindi la RLS non restringerebbe nulla e la lista mostrerebbe i prestiti in attesa di tutta la rete. Il test
    crea un movimento che esiste davvero (Bozzano → Tuturano) e verifica che per San Bao non ci sia: se il `WHERE`
    sparisse, questo test fallirebbe mentre gli altri due resterebbero verdi.
    """
    oggetto = asyncio.run(_crea_oggetto(SLUG_CEDENTE, NOME_OGGETTO))
    movimenti: list[int] = []
    try:
        movimenti.append(_proponi(accedi(SLUG_CEDENTE), oggetto, SLUG_TERZA))
        assert asyncio.run(_stato_movimento(movimenti[0])) == "proposto", "il movimento di prova deve esistere"

        elenco = _movimenti(accedi(SLUG_PRINCIPALE))

        assert _trova(elenco, movimenti[0]) is None, f"i prestiti di altre Case non appartengono a questa lista: {elenco}"
        # Controprova: la ricevente invece lo vede — senza, il test sarebbe verde anche se l'endpoint non
        # restituisse mai nulla.
        assert _trova(_movimenti(accedi(SLUG_TERZA)), movimenti[0]) is not None
    finally:
        asyncio.run(_pulisci([oggetto], movimenti))


@pytest.mark.live
def test_movimenti_da_confermare_esclude_i_movimenti_confermati(accedi):
    """Un movimento confermato **esce** dalla lista: è l'elenco di ciò che attende una decisione, non lo storico.

    La conferma è quella vera (`POST /op/movimento/{id}/conferma`, che delega a `conferma_movimento`): la ricevente
    decide, e da quel momento non c'è più nulla da confermare. Il test verifica entrambi i lati — prima presente,
    dopo assente — perché il solo «dopo assente» sarebbe verde anche se l'endpoint non restituisse mai nulla.
    """
    oggetto = asyncio.run(_crea_oggetto(SLUG_CEDENTE, NOME_OGGETTO))
    movimenti: list[int] = []
    try:
        movimenti.append(_proponi(accedi(SLUG_CEDENTE), oggetto, SLUG_PRINCIPALE))
        ricevente = accedi(SLUG_PRINCIPALE)
        assert _trova(_movimenti(ricevente), movimenti[0]) is not None, "prima della conferma deve comparire"

        conferma = ricevente.post(f"/op/movimento/{movimenti[0]}/conferma", headers=_intestazioni())
        assert conferma.status_code == 200, conferma.text

        assert asyncio.run(_stato_movimento(movimenti[0])) == "confermato"
        assert _trova(_movimenti(ricevente), movimenti[0]) is None, "un movimento confermato non attende più nulla"
    finally:
        asyncio.run(_pulisci([oggetto], movimenti))


# --- il confine di autenticazione, senza sessione -------------------------------------------------------------


def test_movimenti_da_confermare_senza_sessione_risponde_401(chiave):
    """Senza cookie di sessione l'endpoint risponde 401, non un elenco vuoto.

    Un elenco vuoto sarebbe la risposta peggiore possibile: la UI mostrerebbe «Nessun movimento in attesa di
    conferma» a un operatore che non è entrato. Il test non richiede il database — la dipendenza si ferma sul cookie
    assente prima di aprirlo — quindi gira anche a stack spento.
    """
    from app.main import crea_app

    with TestClient(crea_app(), raise_server_exceptions=False) as client:
        risposta = client.get("/op/movimenti_da_confermare", headers={"X-Trasi-Key": chiave})

    assert risposta.status_code == 401
    assert risposta.json()["detail"]
