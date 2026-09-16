"""`cerca_luogo` ed `eventi_oggi` (B3-SHM-02): la lettura della memoria della rete.

I test con database girano contro il database reale (`live`), perché questi due endpoint sono **query**: provarli su
un doppio verificherebbe il doppio, non la query. Lo `stub` di `q` troppo corta e il 404 della Casa inesistente sono
invece indipendenti dal database e girano sempre.
"""

import asyncio
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from attese import EMAIL_OP_SANBAO, EMAIL_RETE
from conftest import _valore_da_env_file

URL = "/v1/u/{email}"

FUSO_LOCALE = ZoneInfo("Europe/Rome")


def _dsn_admin() -> str:
    """Il DSN amministrativo per creare e rimuovere la fixture del test.

    La password viene da `deployment/.env` (`POSTGRES_PASSWORD`), la stessa sorgente del compose: nessun segreto nel
    codice. Serve solo ai test `live` che devono **cambiare** lo stato per osservare la reazione dello shim; il
    database viene riportato allo stato iniziale alla fine di ogni test.
    """
    return (
        f"postgresql://postgres:{_valore_da_env_file('POSTGRES_PASSWORD')}@127.0.0.1:5432/"
        f"{_valore_da_env_file('TRASI_DB') or 'trasi_db'}"
    )


def _cerca(client, query: str, email: str = EMAIL_OP_SANBAO):
    return client.get(f"{URL.format(email=email)}/cerca_luogo?{query}")


def test_cerca_luogo_con_q_di_un_carattere_risponde_422(client, sessione_finta):
    """Una ricerca di un carattere non è una ricerca: 422, con il motivo dichiarato al chiamante."""
    sessione_finta()
    risposta = _cerca(client, "q=I")

    assert risposta.status_code == 422
    assert "q" in risposta.json()["detail"]


def test_cerca_luogo_senza_q_risponde_422(client, sessione_finta):
    """`q` è obbligatorio nel contratto: la sua assenza è un parametro non ammesso, non una ricerca vuota."""
    sessione_finta()
    risposta = _cerca(client, "tipo=caf")

    assert risposta.status_code == 422


@pytest.mark.live
def test_cerca_luogo_trova_i_caf_della_rete(client, db_vivo):
    """«CAF» trova i patronati della memoria: è la domanda di US-01 («dove si fa l'ISEE?»)."""
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    risposta = _cerca(client, "q=CAF")

    assert risposta.status_code == 200
    nomi = [item["nome"] for item in risposta.json()["items"]]
    assert any("CAF" in nome for nome in nomi), f"attesi i CAF in memoria, trovati: {nomi}"


@pytest.mark.live
def test_cerca_luogo_ogni_item_porta_provenienza_badge_e_fiducia(client, db_vivo):
    """V3: nessun item senza etichetta di provenienza, e il badge è già composto dallo shim.

    Il test verifica la **forma** del badge, non una stringa esatta: se il LLM dovesse ricomporlo, due risposte alla
    stessa domanda mostrerebbero etichette diverse.
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    items = _cerca(client, "q=CAF").json()["items"]

    assert items, "attesi i CAF in memoria"
    for item in items:
        assert item["provenienza"] == "kb"
        assert item["badge"].startswith("[KB · ")
        assert item["badge"].endswith(f"affidabilità {item['fiducia']}]")
        assert "agg." in item["badge"]


@pytest.mark.live
def test_cerca_luogo_senza_risultati_risponde_200_con_lista_vuota(client, db_vivo):
    """US-02: nessun risultato è una risposta valida (`items: []`), non un 404.

    Un 404 direbbe che l'endpoint non esiste; `items: []` dice all'assistente che la memoria non ha nulla, che è
    l'informazione su cui si fonda l'astensione dichiarata.
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    risposta = _cerca(client, "q=zzzznonesistemai")

    assert risposta.status_code == 200
    assert risposta.json() == {"items": []}


@pytest.mark.live
def test_cerca_luogo_filtra_per_tipo(client, db_vivo):
    """`tipo` restringe davvero la ricerca ai luoghi di quel tipo."""
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    items = _cerca(client, "q=CAF&tipo=caf").json()["items"]

    assert items, "la ricerca per tipo deve restituire i CAF"
    assert {item["tipo"] for item in items} == {"caf"}


@pytest.mark.live
def test_cerca_luogo_con_tipo_fuori_vocabolario_non_restringe(client, db_vivo):
    """Il contratto dice che «un valore fuori vocabolario non restringe la ricerca»: non è un 422.

    Distinguerlo da `vicino_a` (dove il tipo fuori elenco è 422) non è un'incoerenza: là il tipo diventa una query
    OpenStreetMap e un valore ignoto non è traducibile; qui è un filtro su una colonna, e ignorarlo è il
    comportamento dichiarato.
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    con_tipo = _cerca(client, "q=CAF&tipo=non_esiste_questo_tipo")

    assert con_tipo.status_code == 200
    assert con_tipo.json()["items"], "un tipo sconosciuto non deve svuotare la ricerca"


@pytest.mark.live
def test_eventi_oggi_di_una_casa_senza_eventi_risponde_200_con_lista_vuota(client, db_vivo):
    """Una Casa esistente senza eventi oggi è 200 con `eventi: []`: la Casa c'è, la giornata è vuota."""
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    risposta = client.get(f"{URL.format(email=EMAIL_OP_SANBAO)}/eventi_oggi?casa=san-bao")

    assert risposta.status_code == 200
    corpo = risposta.json()
    assert corpo["casa"] == "san-bao"
    assert corpo["eventi"] == []
    assert corpo["data"] == date.today().isoformat()


def test_eventi_oggi_con_casa_inesistente_risponde_404(client, sessione_finta):
    """Una Casa che non esiste è una richiesta sbagliata: 404, non una lista vuota.

    Se rispondesse `eventi: []`, l'assistente direbbe «oggi non c'è nulla» per una Casa che non esiste — cioè
    inventerebbe un'informazione falsa a partire da un errore di chi chiama.

    Il doppio di sessione restituisce zero eventi e nessuna Casa: è lo stato esatto in cui la distinzione 200/404 si
    decide, e non serve il database per costruirlo.
    """
    sessione_finta(righe=[], valore=None)
    risposta = client.get(f"{URL.format(email=EMAIL_OP_SANBAO)}/eventi_oggi?casa=casa-che-non-esiste")

    assert risposta.status_code == 404
    assert "casa non trovata" in risposta.json()["detail"]


def test_eventi_oggi_con_data_non_iso_risponde_422(client, sessione_finta):
    """Una data malformata è un parametro non ammesso, e lo shim lo dichiara (non un 500 dell'indicizzatore)."""
    sessione_finta()
    risposta = client.get(f"{URL.format(email=EMAIL_OP_SANBAO)}/eventi_oggi?casa=san-bao&data=ieri")

    assert risposta.status_code == 422


@pytest.mark.live
def test_eventi_oggi_restituisce_gli_eventi_della_data_richiesta(client, db_vivo, dsn):
    """Un evento inserito per una data compare in quel giorno, con orari e badge KB (V3).

    L'evento di prova è creato con una connessione amministrativa e rimosso alla fine: non si tocca `db/**` e il
    database resta com'era. La data è scelta nel futuro per non dipendere da altri eventi già presenti.
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    giorno = date.today() + timedelta(days=30)
    titolo = "Evento di prova B3 (rimosso dal test)"

    async def inserisci() -> int:
        import asyncpg

        conn = await asyncpg.connect(_dsn_admin())
        try:
            return await conn.fetchval(
                """
                INSERT INTO trasi.evento (casa_id, titolo, inizio, luogo_testo, affidabilita)
                SELECT c.id, $1, $2, 'Sala di prova', 3 FROM trasi.casa c WHERE c.slug = 'san-bao'
                RETURNING id
                """,
                titolo,
                datetime.combine(giorno, time(18, 30), tzinfo=FUSO_LOCALE),
            )
        finally:
            await conn.close()

    async def rimuovi(identificativo: int) -> None:
        import asyncpg

        conn = await asyncpg.connect(_dsn_admin())
        try:
            await conn.execute("DELETE FROM trasi.evento WHERE id = $1", identificativo)
        finally:
            await conn.close()

    identificativo = asyncio.run(inserisci())
    try:
        risposta = client.get(
            f"{URL.format(email=EMAIL_OP_SANBAO)}/eventi_oggi?casa=san-bao&data={giorno.isoformat()}"
        )
    finally:
        asyncio.run(rimuovi(identificativo))

    assert risposta.status_code == 200
    corpo = risposta.json()
    assert [evento["titolo"] for evento in corpo["eventi"]] == [titolo]
    evento = corpo["eventi"][0]
    assert evento["ora_inizio"] == "18:30"
    assert evento["provenienza"] == "kb"
    assert evento["badge"].startswith("[KB · ")
    assert evento["dove"] == "Sala di prova"


@pytest.mark.live
def test_l_operatore_della_rete_vede_gli_eventi_di_ogni_casa(client, db_vivo):
    """Il ruolo `rete` (AT/AQ) non è legato a una Casa e vede il calendario di tutte: è il principio 3."""
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    risposta = client.get(f"{URL.format(email=EMAIL_RETE)}/eventi_oggi?casa=bozzano")

    assert risposta.status_code == 200
    assert risposta.json()["casa"] == "bozzano"
