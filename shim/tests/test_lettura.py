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
    """Una Casa esistente senza eventi in una data è 200 con `eventi: []`: la Casa c'è, la giornata è vuota.

    Il giorno si chiede **lontano** invece che «oggi», e non è un dettaglio di comodo. Scritto su oggi, questo test
    affermava una proprietà del database e non dell'endpoint: «San Bao non ha eventi oggi» è vero finché nessuno ne
    inserisce uno — e l'area operatore ha **`crea_evento`** (`POST /v1/u/…/crea_evento`, scheda !NEW 1) proprio per
    farlo. Misurato in questa sessione: una sessione sorella ha creato un evento per oggi alle 19:43 e questo test è
    diventato rosso senza che nulla dell'endpoint fosse cambiato — il difetto peggiore, perché insegna a ignorare
    l'unico test che dichiara «lista vuota = 200».

    La data lontana è la stessa convenzione dell'altro test di questo file (`+30 giorni`), che crea il proprio evento
    nel futuro per non dipendere da quelli già presenti. Ciò che si prova è il **contratto**: una Casa che esiste e
    non ha eventi in quella data riceve 200 con la lista vuota, `casa` e `data` riecheggiati.
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    giorno = (date.today() + timedelta(days=365)).isoformat()
    risposta = client.get(f"{URL.format(email=EMAIL_OP_SANBAO)}/eventi_oggi?casa=san-bao&data={giorno}")

    assert risposta.status_code == 200
    corpo = risposta.json()
    assert corpo["casa"] == "san-bao"
    assert corpo["eventi"] == [], f"nessun evento atteso il {giorno}: {corpo['eventi']}"
    assert corpo["data"] == giorno


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


# --- eventi_mese (fuori contratto: il calendario della Home) ---------------------------------------------------


def _dsn_admin_connessione():
    import asyncpg

    return asyncpg.connect(_dsn_admin())


@pytest.mark.live
def test_eventi_mese_restituisce_gli_eventi_del_mese_in_ordine_e_non_quelli_del_mese_dopo(client, db_vivo, dsn):
    """Due eventi in giorni diversi del mese richiesto compaiono in ordine di inizio; uno del mese successivo no.

    Il mese è scelto **lontano** (fra 14 mesi) per non dipendere dagli eventi già in calendario: si prova il
    contratto dell'intervallo (`dal` = 1, `al` = ultimo giorno, tutti e soli gli eventi in mezzo), non lo stato del
    database. Gli eventi di prova sono creati con la connessione amministrativa e rimossi alla fine.
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    import calendar

    oggi = date.today()
    anno, mese = (oggi.year + 1, oggi.month + 2) if oggi.month <= 10 else (oggi.year + 2, oggi.month - 10)
    primo = date(anno, mese, 1)
    ultimo = date(anno, mese, calendar.monthrange(anno, mese)[1])
    mese_dopo = date(anno + (mese == 12), mese % 12 + 1, 3)
    # Inseriti in ordine **inverso** rispetto a quello atteso: l'ordine della risposta deve venire da `inizio`.
    prove = [
        ("Evento di prova mese — 20 (rimosso dal test)", datetime.combine(date(anno, mese, 20), time(10, 0), tzinfo=FUSO_LOCALE)),
        ("Evento di prova mese — 5 (rimosso dal test)", datetime.combine(date(anno, mese, 5), time(18, 30), tzinfo=FUSO_LOCALE)),
        ("Evento di prova mese dopo (rimosso dal test)", datetime.combine(mese_dopo, time(9, 0), tzinfo=FUSO_LOCALE)),
    ]

    async def inserisci() -> list[int]:
        conn = await _dsn_admin_connessione()
        try:
            return [
                await conn.fetchval(
                    """
                    INSERT INTO trasi.evento (casa_id, titolo, inizio, luogo_testo, affidabilita)
                    SELECT c.id, $1, $2, 'Sala di prova', 3 FROM trasi.casa c WHERE c.slug = 'san-bao'
                    RETURNING id
                    """,
                    titolo,
                    inizio,
                )
                for titolo, inizio in prove
            ]
        finally:
            await conn.close()

    async def rimuovi(identificativi: list[int]) -> None:
        conn = await _dsn_admin_connessione()
        try:
            await conn.execute("DELETE FROM trasi.evento WHERE id = ANY($1::bigint[])", identificativi)
        finally:
            await conn.close()

    identificativi = asyncio.run(inserisci())
    try:
        risposta = client.get(
            f"{URL.format(email=EMAIL_RETE)}/eventi_mese?casa=san-bao&mese={primo.strftime('%Y-%m')}"
        )
    finally:
        asyncio.run(rimuovi(identificativi))

    assert risposta.status_code == 200
    corpo = risposta.json()
    assert corpo["casa"] == "san-bao"
    assert corpo["dal"] == primo.isoformat()
    assert corpo["al"] == ultimo.isoformat()
    assert corpo["oggi"] == oggi.isoformat(), "«oggi» lo dice lo shim, nel fuso della rete"
    assert [e["titolo"] for e in corpo["eventi"]] == [prove[1][0], prove[0][0]]
    assert [e["data"] for e in corpo["eventi"]] == [date(anno, mese, 5).isoformat(), date(anno, mese, 20).isoformat()]
    assert corpo["eventi"][0]["ora_inizio"] == "18:30"


def test_eventi_mese_con_casa_inesistente_risponde_404(client, sessione_finta):
    """Stessa regola di `eventi_oggi`: una Casa che non esiste è 404, non un mese vuoto."""
    sessione_finta(righe=[], valore=None)
    risposta = client.get(f"{URL.format(email=EMAIL_OP_SANBAO)}/eventi_mese?casa=casa-che-non-esiste")

    assert risposta.status_code == 404
    assert "casa non trovata" in risposta.json()["detail"]


@pytest.mark.parametrize("mese", ["2026-13", "2026-00", "settembre", "2026-9", "2026-09-01"])
def test_eventi_mese_con_mese_malformato_risponde_422(client, sessione_finta, mese):
    """`mese` è `AAAA-MM` con mese fra 01 e 12: qualunque altra forma è un parametro non ammesso, dichiarato."""
    sessione_finta()
    risposta = client.get(f"{URL.format(email=EMAIL_OP_SANBAO)}/eventi_mese?casa=san-bao&mese={mese}")

    assert risposta.status_code == 422
    assert risposta.json()["detail"].startswith("parametri non ammessi")


def test_eventi_mese_senza_mese_usa_il_mese_corrente(client, sessione_finta):
    """Senza `mese` l'intervallo è il mese di oggi, dal primo all'ultimo giorno, e `oggi` è dentro."""
    sessione_finta(righe=[], valore=5)  # `valore` è la risposta a `SQL_CASA_ESISTE`: la Casa c'è, il mese è vuoto
    risposta = client.get(f"{URL.format(email=EMAIL_OP_SANBAO)}/eventi_mese?casa=san-bao")

    assert risposta.status_code == 200
    corpo = risposta.json()
    dal, al, oggi = date.fromisoformat(corpo["dal"]), date.fromisoformat(corpo["al"]), date.fromisoformat(corpo["oggi"])
    assert dal.day == 1 and (al + timedelta(days=1)).day == 1
    assert dal <= oggi <= al
    assert corpo["eventi"] == []


def test_eventi_mese_e_fuori_dal_contratto_congelato(client):
    """La rotta non compare nello schema OpenAPI generato: le operazioni esposte restano le nove congelate (V-09)."""
    percorsi = client.get("/openapi.json").json()["paths"]
    assert not any(p.endswith("/eventi_mese") for p in percorsi)

@pytest.mark.live
def test_l_operatore_della_rete_vede_gli_eventi_di_ogni_casa(client, db_vivo):
    """Il ruolo `rete` (AT/AQ) non è legato a una Casa e vede il calendario di tutte: è il principio 3."""
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    risposta = client.get(f"{URL.format(email=EMAIL_RETE)}/eventi_oggi?casa=bozzano")

    assert risposta.status_code == 200
    assert risposta.json()["casa"] == "bozzano"


@pytest.mark.live
@pytest.mark.parametrize("casa", ["Parco Buscicchio", "buscicchio", "BUSCICCHIO", "Centro di Aggregazione Bozzano"])
def test_eventi_oggi_riconosce_la_casa_dal_nome(client, db_vivo, casa):
    """Un operatore di San Bao che chiede «Parco Buscicchio» riceve Buscicchio, non San Bao.

    Il modello riempie `casa` con il **nome** della Casa, non con lo slug. Fino al 2026-09-17 uno slug
    sconosciuto faceva ripiegare in silenzio sulla Casa dell'operatore: POP chiedeva gli eventi di San Bao
    e riceveva i propri, e l'operatore concludeva di non poter leggere le altre Case. Il ripiego resta per
    un testo che non è una Casa (v. `test_vicino_a_casa_inesistente_ricade_sull_identita`).
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    risposta = client.get(f"{URL.format(email=EMAIL_OP_SANBAO)}/eventi_oggi?casa={casa}")

    assert risposta.status_code == 200
    atteso = "bozzano" if "Bozzano" in casa else "buscicchio"
    assert risposta.json()["casa"] == atteso, f"«{casa}» deve risolversi in {atteso}, non nella Casa dell'operatore"
