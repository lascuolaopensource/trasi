"""Le nove operazioni del contratto congelato rispondono **per davvero** (B3 sostituisce lo stub 501).

Il file che c'era prima (`test_stub_501.py`) verificava che ogni operazione rispondesse 501: era il criterio del gate
V-09, quando lo shim era uno stub e Onyx doveva poter registrare il contratto prima che gli endpoint esistessero. In
B3 quel comportamento è **superato**: le operazioni sono implementate, e un test che si aspettasse ancora 501
proverebbe il contrario di ciò che serve.

Questi test difendono le proprietà che restano vere qualunque cosa facciano gli endpoint:

1. le nove `operationId` esistono agli indirizzi che Onyx compone davvero (`/v1/u/<email>/…`), e **nessuna** risponde
   501 o 405;
2. nessuna esiste fuori dal prefisso con l'email: senza email l'indirizzo non è una route;
3. i corpi d'errore usano l'involucro `{"detail": <stringa>}` del contratto, mai la struttura di pydantic;
4. `GET /healthz` resta fuori dal contratto e non tocca il database.
"""

import pytest

from attese import OPERAZIONI_ATTESE

EMAIL_OPERATORE = "op.san-bao@trasi.local"

# Marcatore delle proposte che questa batteria crea davvero (il corpo di `proponi_modifica` è
# completo, quindi con il database acceso l'INSERT va a buon fine). Serve a **rimuoverle**: vedi la
# fixture `senza_residui` in coda. Il motivo per cui non si può omettere: `proposta` è la coda «Da
# approvare» che l'operatore apre ogni giorno, e ogni esecuzione della suite ne lasciava due —
# misurate **40 righe** di motivazione «prova» dopo una giornata di lavoro, indistinguibili da una
# segnalazione vera per chi guarda la coda. È il difetto che il piano chiama «coda ignorata», ed è
# esattamente il modo in cui si produce: rumore che sembra lavoro.
MARCA = "B3TEST: prova di contratto"

# Parametri minimi perché la richiesta arrivi alla logica dell'endpoint invece di fermarsi alla validazione: serve a
# distinguere «l'operazione esiste e risponde» da «l'operazione esiste e rifiuta i parametri».
PARAMETRI: dict[str, str] = {
    "cerca_luogo": "q=CAF",
    "eventi_oggi": "casa=san-bao",
    "vicino_a": "casa=san-bao&tipo=bar",
    "biglietto": "luogo_id=1",
    "oggi": "casa=san-bao",
    "statistiche": "casa=san-bao",
    "cerca_web": "q=isee",
}
CORPI: dict[str, dict] = {
    "registra_richiesta": {"categoria": "orientamento", "esito": "risolta"},
    "proponi_modifica": {
        "tipo": "chiudi_luogo",
        "entita": "luogo",
        "payload": {},
        "motivazione": MARCA,
    },
    "approva_proposta": {"proposta_id": 1, "decisione": "approva"},
}


def url_operazione(path: str) -> str:
    """L'URL reale dell'operazione, come lo compone Onyx a partire da `servers[0].url`."""
    return f"/v1/u/{EMAIL_OPERATORE}{path}"


def chiama(client, metodo: str, path: str):
    """Chiama un'operazione con i parametri minimi, se l'operazione li richiede."""
    operation_id = path.lstrip("/")
    url = url_operazione(path)
    if metodo == "post":
        return client.post(url, json=CORPI.get(operation_id, {}))
    query = PARAMETRI.get(operation_id, "")
    return client.get(f"{url}?{query}" if query else url)


@pytest.mark.parametrize(
    ("operation_id", "metodo", "path"),
    OPERAZIONI_ATTESE,
    ids=[operation_id for operation_id, _, _ in OPERAZIONI_ATTESE],
)
def test_ogni_operazione_del_contratto_esiste_e_non_risponde_piu_501(client, operation_id, metodo, path):
    """Le nove operazioni esistono e sono implementate: nessuna risponde 501 né 405.

    Il test **non** asserisce un codice preciso, e la scelta è deliberata: senza database alcune operazioni rispondono
    503, con database rispondono 200/201, e con un payload incompleto 422. Asserire un codice renderebbe il test
    dipendente dallo stack acceso; asserire che l'operazione esiste e ha una logica è l'invariante che conta — 501 e
    405 sono i due modi in cui l'operazione **non** esisterebbe.
    """
    risposta = chiama(client, metodo, path)

    assert risposta.status_code not in (501, 405), (
        f"{operation_id} deve essere implementata, risposta: {risposta.status_code}"
    )


@pytest.mark.parametrize(
    "path",
    [path for _, _, path in OPERAZIONI_ATTESE],
    ids=[operation_id for operation_id, _, _ in OPERAZIONI_ATTESE],
)
def test_operazione_assente_dal_prefisso_email_non_esiste(client, path):
    """Le operazioni vivono sotto `/v1/u/<email>/…`: senza email l'indirizzo non esiste (nessuna route parallela)."""
    assert client.get(path).status_code == 404


@pytest.mark.parametrize(
    ("operation_id", "metodo", "path"),
    OPERAZIONI_ATTESE,
    ids=[operation_id for operation_id, _, _ in OPERAZIONI_ATTESE],
)
def test_gli_errori_usano_l_involucro_detail_del_contratto(client, operation_id, metodo, path):
    """Ogni corpo d'errore è `{"detail": <stringa>}`, come dichiara `components.schemas.Errore`.

    È il presidio che rende leggibili gli errori al LLM: la struttura di pydantic (`{"detail": [{...}]}`) non è il
    contratto, e un `detail` che fosse una lista non sarebbe interpretabile dall'assistente.
    """
    risposta = chiama(client, metodo, path)

    if risposta.status_code >= 400:
        corpo = risposta.json()
        assert set(corpo) == {"detail"}, f"{operation_id}: atteso il solo campo detail, trovato {set(corpo)}"
        assert isinstance(corpo["detail"], str), f"{operation_id}: detail deve essere una stringa"


def test_un_campo_non_previsto_nel_corpo_risponde_422_con_detail_stringa(client, sessione_finta):
    """`extra="forbid"` e l'involucro del contratto valgono anche sugli errori di validazione.

    Il campo vietato è quello che il piano cita esplicitamente (`nome_cittadino`): se passasse, lo shim avrebbe
    accettato un dato personale che nessuno schema prevede (V5, §12). Il doppio di sessione isola la validazione dal
    database: un corpo non ammesso è un errore di chi chiama e non deve dipendere dallo stato dello stack.
    """
    sessione_finta()
    risposta = client.post(
        url_operazione("/registra_richiesta"),
        json={"categoria": "orientamento", "esito": "risolta", "nome_cittadino": "Mario Rossi"},
    )

    assert risposta.status_code == 422
    assert isinstance(risposta.json()["detail"], str)


def test_healthz_resta_fuori_dal_contratto_e_non_tocca_il_database(client):
    """`/healthz` è liveness del container: risponde anche se il database è giù, e non compare nell'OpenAPI servito."""
    risposta = client.get("/healthz")

    assert risposta.status_code == 200
    assert risposta.json() == {"status": "ok"}

    from app.main import app

    assert "/healthz" not in app.openapi()["paths"]


@pytest.fixture(autouse=True)
def senza_residui():
    """Rimuove le proposte che questa batteria crea, **prima e dopo** ogni test del file.

    Perché `autouse` e perché anche *prima*: `test_gli_errori_usano_l_involucro_detail_del_contratto`
    e `test_ogni_operazione_del_contratto_esiste_e_non_risponde_piu_501` chiamano `proponi_modifica`
    con un corpo completo, quindi con il database acceso l'INSERT **riesce** — e la proposta resta
    nella coda «Da approvare» della Casa. Il test precedente poteva lasciarne una, e la pulizia a
    fine test non basta a rendere la suite ripetibile: è la stessa ragione per cui `db/tests/run.sh`
    avvolge ogni file in `BEGIN/ROLLBACK`.

    Si cancella con la connessione amministrativa perché nessun ruolo applicativo ha `DELETE` su
    `proposta` e `audit` (V4: la memoria non si cancella dall'applicazione) — è la via che
    `ambiente.pulisci` già usa, e il commento là spiega perché assumere quel ruolo per la pulizia
    non è un aggiramento. Il perimetro è la **marca**, mai «tutte le proposte»: una proposta scritta
    da un altro test o da una prova manuale non va toccata.
    """
    import asyncio

    from ambiente import connessione_amministratore

    async def rimuovi() -> None:
        conn = await connessione_amministratore()
        try:
            # L'ordine è obbligato: prima l'audit (la FK `audit.proposta_id`), poi la proposta.
            await conn.execute(
                "DELETE FROM trasi.audit WHERE proposta_id IN "
                "(SELECT id FROM trasi.proposta WHERE motivazione = $1)",
                MARCA,
            )
            await conn.execute("DELETE FROM trasi.proposta WHERE motivazione = $1", MARCA)
        finally:
            await conn.close()

    try:
        asyncio.run(rimuovi())
    except Exception:  # noqa: BLE001 — senza database la pulizia non ha nulla da fare
        pass

    yield

    try:
        asyncio.run(rimuovi())
    except Exception:  # noqa: BLE001
        pass
