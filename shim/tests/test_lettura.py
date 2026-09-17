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
def test_luogo_senza_coordinate_e_dichiarato_non_geolocalizzato_e_non_rompe_la_ricerca(client, db_vivo):
    """T09/T10 — un luogo **con** coordinate esce con `lat`/`lon` numerici (T09); uno **senza** `geom` esce con
    `lat`/`lon` `null` (T10) e non fa saltare la risposta con un 500. La coordinata non si inventa: la posizione
    manca e lo si dice. Stessa regola su `GET /op/mappa` (mappa dell'Osservatorio).
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    nome = "Sportello di prova T10 senza posizione (rimosso dal test)"

    async def inserisci() -> int:
        import asyncpg

        conn = await asyncpg.connect(_dsn_admin())
        try:
            return await conn.fetchval(
                """
                INSERT INTO trasi.luogo (nome, tipo, descrizione, geom, fonte_id, affidabilita, casa_id)
                SELECT $1, 'caf', 'Fixture di test: nessuna posizione in memoria', NULL, f.id, 3, c.id
                  FROM trasi.fonte f, trasi.casa c WHERE f.nome = 'Rete-kb-3' AND c.slug = 'san-bao'
                RETURNING id
                """,
                nome,
            )
        finally:
            await conn.close()

    async def rimuovi(identificativo: int) -> None:
        import asyncpg

        conn = await asyncpg.connect(_dsn_admin())
        try:
            await conn.execute("DELETE FROM trasi.luogo WHERE id = $1", identificativo)
        finally:
            await conn.close()

    identificativo = asyncio.run(inserisci())
    try:
        senza = _cerca(client, "q=prova%20T10")
        con = _cerca(client, "q=CAF")
    finally:
        asyncio.run(rimuovi(identificativo))

    assert senza.status_code == 200, senza.text
    voci = [i for i in senza.json()["items"] if i["nome"] == nome]
    assert len(voci) == 1
    assert voci[0]["lat"] is None and voci[0]["lon"] is None

    # T09: i CAF del seed hanno coordinate vere, e restano numeri.
    assert con.status_code == 200
    con_posizione = [i for i in con.json()["items"] if i["lat"] is not None]
    assert con_posizione, "nessun CAF geolocalizzato nel seed"
    assert all(-90 <= i["lat"] <= 90 and -180 <= i["lon"] <= 180 for i in con_posizione)


@pytest.mark.live
def test_cerca_luogo_non_lascia_che_il_servizio_con_piu_righe_monopolizzi_la_risposta(client, db_vivo):
    """T08 — una domanda che tocca più servizi riceve **tutti** i servizi pertinenti, non il più numeroso.

    Fixture (8 righe, marcate come dati di prova): sei CAF, una farmacia e un'associazione, tutti con lo stesso
    testo nel nome. L'ordine per «affidabilità, nome» metteva i sei CAF davanti (alfabetico) e con un tetto basso
    la farmacia non entrava. Con l'ordine bilanciato per tipo, **le prime tre voci sono tre tipi diversi** e le
    successive riprendono il giro: il servizio con più righe non è più rilevante per il solo fatto di averne di più.
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    marcatore = "Prova T08 multi-servizio (rimosso dal test)"
    fixture = [(f"CAF {chr(65 + n)} {marcatore}", "caf") for n in range(6)] + [
        (f"Farmacia {marcatore}", "farmacia"),
        (f"Associazione {marcatore}", "associazione"),
    ]

    async def inserisci() -> list[int]:
        import asyncpg

        conn = await asyncpg.connect(_dsn_admin())
        try:
            ids = []
            for nome, tipo in fixture:
                ids.append(
                    await conn.fetchval(
                        """
                        INSERT INTO trasi.luogo (nome, tipo, descrizione, geom, fonte_id, affidabilita, casa_id)
                        SELECT $1, $2, 'Fixture di test T08', NULL, f.id, 3, c.id
                          FROM trasi.fonte f, trasi.casa c WHERE f.nome = 'Rete-kb-3' AND c.slug = 'san-bao'
                        RETURNING id
                        """,
                        nome,
                        tipo,
                    )
                )
            return ids
        finally:
            await conn.close()

    async def rimuovi(ids: list[int]) -> None:
        import asyncpg

        conn = await asyncpg.connect(_dsn_admin())
        try:
            await conn.execute("DELETE FROM trasi.luogo WHERE id = ANY($1::int[])", ids)
        finally:
            await conn.close()

    ids = asyncio.run(inserisci())
    try:
        risposta = _cerca(client, "q=Prova%20T08")
    finally:
        asyncio.run(rimuovi(ids))

    assert risposta.status_code == 200, risposta.text
    tipi = [i["tipo"] for i in risposta.json()["items"]]
    assert len(tipi) == len(fixture)
    # Primo giro: un rappresentante per ogni servizio, prima di qualunque secondo CAF.
    assert set(tipi[:3]) == {"caf", "farmacia", "associazione"}
    # Il resto è la coda del servizio numeroso: nessun servizio è sparito, nessuno è raddoppiato in testa.
    assert tipi[3:] == ["caf"] * 5

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


@pytest.mark.live
def test_eventi_oggi_con_data_fine_copre_l_intervallo_e_gli_eventi_futuri(client, db_vivo):
    """T01/T02 — `data_fine` rende l'intervallo **inclusivo**: un evento a +40 giorni compare in una finestra
    che lo contiene e non in una che lo precede. Il tool non forza più «oggi»: chi chiede il mese, ha il mese.
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    giorno = date.today() + timedelta(days=40)
    titolo = "Evento futuro di prova T02 (rimosso dal test)"

    async def inserisci() -> int:
        import asyncpg

        conn = await asyncpg.connect(_dsn_admin())
        try:
            return await conn.fetchval(
                """
                INSERT INTO trasi.evento (casa_id, titolo, inizio, affidabilita)
                SELECT c.id, $1, $2, 3 FROM trasi.casa c WHERE c.slug = 'san-bao' RETURNING id
                """,
                titolo,
                datetime.combine(giorno, time(10, 0), tzinfo=FUSO_LOCALE),
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

    base = URL.format(email=EMAIL_OP_SANBAO)
    identificativo = asyncio.run(inserisci())
    try:
        # La finestra che lo contiene (oggi → +45): l'evento futuro c'è.
        dentro = client.get(
            f"{base}/eventi_oggi?casa=san-bao&data={date.today().isoformat()}"
            f"&data_fine={(date.today() + timedelta(days=45)).isoformat()}"
        )
        # La finestra che lo precede (oggi → +10): non c'è.
        prima = client.get(
            f"{base}/eventi_oggi?casa=san-bao&data={date.today().isoformat()}"
            f"&data_fine={(date.today() + timedelta(days=10)).isoformat()}"
        )
        # Senza `data_fine`: un giorno solo, e la risposta lo dichiara con `data_fine == data`.
        solo_oggi = client.get(f"{base}/eventi_oggi?casa=san-bao&data={giorno.isoformat()}")
        invertita = client.get(
            f"{base}/eventi_oggi?casa=san-bao&data={giorno.isoformat()}"
            f"&data_fine={(giorno - timedelta(days=1)).isoformat()}"
        )
    finally:
        asyncio.run(rimuovi(identificativo))

    assert dentro.status_code == 200
    assert titolo in [e["titolo"] for e in dentro.json()["eventi"]]
    assert dentro.json()["data_fine"] == (date.today() + timedelta(days=45)).isoformat()
    assert titolo not in [e["titolo"] for e in prima.json()["eventi"]]
    assert solo_oggi.json()["data"] == solo_oggi.json()["data_fine"] == giorno.isoformat()
    assert invertita.status_code == 422


@pytest.mark.live
def test_evento_ricorrente_compare_a_ogni_occorrenza_dell_intervallo(client, db_vivo):
    """T05 — un evento `settimanale` è **una** riga in tabella e N occorrenze nella ricerca (db/030):
    quattro settimane di finestra → quattro occorrenze, la prima alla `inizio`, con `occorrenza` 0..3.
    Le settimane successive non ripetono la riga di tabella: `id` è lo stesso su tutte.
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    primo = date.today() + timedelta(days=60)
    titolo = "Laboratorio ricorrente di prova T05 (rimosso dal test)"

    async def inserisci() -> int:
        import asyncpg

        conn = await asyncpg.connect(_dsn_admin())
        try:
            return await conn.fetchval(
                """
                INSERT INTO trasi.evento (casa_id, titolo, inizio, ricorrenza, affidabilita)
                SELECT c.id, $1, $2, 'settimanale', 3 FROM trasi.casa c WHERE c.slug = 'san-bao' RETURNING id
                """,
                titolo,
                datetime.combine(primo, time(17, 0), tzinfo=FUSO_LOCALE),
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

    base = URL.format(email=EMAIL_OP_SANBAO)
    identificativo = asyncio.run(inserisci())
    try:
        risposta = client.get(
            f"{base}/eventi_oggi?casa=san-bao&data={primo.isoformat()}"
            f"&data_fine={(primo + timedelta(days=27)).isoformat()}"
        )
        # Il giorno singolo della terza settimana: la sola occorrenza n. 2, alla stessa ora.
        terza = client.get(f"{base}/eventi_oggi?casa=san-bao&data={(primo + timedelta(days=14)).isoformat()}")
    finally:
        asyncio.run(rimuovi(identificativo))

    assert risposta.status_code == 200
    occorrenze = [e for e in risposta.json()["eventi"] if e["titolo"] == titolo]
    assert [e["data"] for e in occorrenze] == [(primo + timedelta(days=7 * n)).isoformat() for n in range(4)]
    assert [e["occorrenza"] for e in occorrenze] == [0, 1, 2, 3]
    assert {e["ricorrenza"] for e in occorrenze} == {"settimanale"}
    assert {e["ora_inizio"] for e in occorrenze} == {"17:00"}

    nella_terza = [e for e in terza.json()["eventi"] if e["titolo"] == titolo]
    assert len(nella_terza) == 1 and nella_terza[0]["occorrenza"] == 2

@pytest.mark.live
def test_evento_da_calendario_esterno_e_dichiarato_esterna_con_il_suo_badge(client, db_vivo):
    """T03 — un evento arrivato da iCal (fonte `Google Calendar-ical-2`, `tipo_accesso='ical'`) è **distinguibile**
    da quelli della rete: `provenienza="esterna"` e badge `[Esterna · … · non verificata dalla rete]`, mentre
    l'evento inserito a mano lo stesso giorno resta `kb`. Prima, entrambi uscivano `kb`: difetto V3.
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    giorno = date.today() + timedelta(days=50)
    esterno = "Evento da calendario esterno di prova T03 (rimosso dal test)"
    interno = "Evento della rete di prova T03 (rimosso dal test)"

    async def inserisci() -> list[int]:
        import asyncpg

        conn = await asyncpg.connect(_dsn_admin())
        try:
            quando = datetime.combine(giorno, time(11, 0), tzinfo=FUSO_LOCALE)
            a = await conn.fetchval(
                """
                INSERT INTO trasi.evento (casa_id, titolo, inizio, uid_ical, fonte_id, affidabilita)
                SELECT c.id, $1, $2, 'prova-t03@trasi.local', f.id, 2
                  FROM trasi.casa c, trasi.fonte f
                 WHERE c.slug = 'san-bao' AND f.nome = 'Google Calendar-ical-2'
                RETURNING id
                """,
                esterno,
                quando,
            )
            b = await conn.fetchval(
                """
                INSERT INTO trasi.evento (casa_id, titolo, inizio, affidabilita)
                SELECT c.id, $1, $2, 3 FROM trasi.casa c WHERE c.slug = 'san-bao' RETURNING id
                """,
                interno,
                quando,
            )
            return [a, b]
        finally:
            await conn.close()

    async def rimuovi(ids: list[int]) -> None:
        import asyncpg

        conn = await asyncpg.connect(_dsn_admin())
        try:
            await conn.execute("DELETE FROM trasi.evento WHERE id = ANY($1::int[])", ids)
        finally:
            await conn.close()

    ids = asyncio.run(inserisci())
    try:
        risposta = client.get(f"{URL.format(email=EMAIL_OP_SANBAO)}/eventi_oggi?casa=san-bao&data={giorno.isoformat()}")
    finally:
        asyncio.run(rimuovi(ids))

    assert risposta.status_code == 200
    per_titolo = {e["titolo"]: e for e in risposta.json()["eventi"]}
    assert per_titolo[esterno]["provenienza"] == "esterna"
    assert per_titolo[esterno]["badge"].startswith("[Esterna · ")
    assert "non verificata dalla rete" in per_titolo[esterno]["badge"]
    assert per_titolo[interno]["provenienza"] == "kb"
    assert per_titolo[interno]["badge"].startswith("[KB · ")

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
