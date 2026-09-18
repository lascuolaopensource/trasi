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


def test_eventi_oggi_al_prima_di_data_risponde_422(client, sessione_finta):
    """`al` precedente a `data` è un intervallo vuoto scritto male: 422, non una lista vuota silenziosa."""
    sessione_finta()
    risposta = client.get(f"{URL.format(email=EMAIL_OP_SANBAO)}/eventi_oggi?data=2026-09-20&al=2026-09-19")

    assert risposta.status_code == 422
    assert "al" in risposta.json()["detail"]


def test_eventi_oggi_intervallo_troppo_ampio_risponde_422(client, sessione_finta):
    """Un intervallo oltre il tetto non è una consultazione di calendario ma un dump: 422 dichiarato."""
    sessione_finta()
    risposta = client.get(f"{URL.format(email=EMAIL_OP_SANBAO)}/eventi_oggi?data=2026-01-01&al=2026-12-31")

    assert risposta.status_code == 422
    assert "intervallo" in risposta.json()["detail"]


def test_eventi_oggi_q_troppo_corta_risponde_422(client, sessione_finta):
    """Una parola chiave di un carattere non filtra nulla di utile: 422, come per `cerca_luogo`."""
    sessione_finta()
    risposta = client.get(f"{URL.format(email=EMAIL_OP_SANBAO)}/eventi_oggi?q=a")

    assert risposta.status_code == 422
    assert "q" in risposta.json()["detail"]


def _inserisci_eventi(righe: list[tuple]) -> list[int]:
    """Crea eventi come `postgres` e restituisce gli id, per i test che devono osservare la lettura di rete.

    Ogni riga è `(slug, titolo, inizio, fine)`; `fine` può essere `None`. Lo stato è ripristinato dal chiamante.
    """
    import asyncpg

    async def _fai() -> list[int]:
        conn = await asyncpg.connect(_dsn_admin())
        try:
            ids: list[int] = []
            for slug, titolo, inizio, fine in righe:
                ids.append(
                    await conn.fetchval(
                        """
                        INSERT INTO trasi.evento (casa_id, titolo, inizio, fine, luogo_testo, affidabilita)
                        SELECT c.id, $1, $2, $3, 'Sala test', 3 FROM trasi.casa c WHERE c.slug = $4
                        RETURNING id
                        """,
                        titolo,
                        inizio,
                        fine,
                        slug,
                    )
                )
            return ids
        finally:
            await conn.close()

    return asyncio.run(_fai())


def _rimuovi_eventi(ids: list[int]) -> None:
    import asyncpg

    async def _fai() -> None:
        conn = await asyncpg.connect(_dsn_admin())
        try:
            await conn.execute("DELETE FROM trasi.evento WHERE id = ANY($1::int[])", ids)
        finally:
            await conn.close()

    asyncio.run(_fai())


@pytest.mark.live
def test_eventi_oggi_casa_tutte_copre_la_rete_e_senza_casa_resta_la_propria(client, db_vivo):
    """`casa=tutte` legge il calendario di TUTTA la rete su un intervallo, in una chiamata; senza `casa` la propria.

    Difetto del 2026-09-17/18: l'assistente rispondeva «nessun evento nel mese» perché doveva fare una chiamata per
    Casa e per giorno. Qui si inseriscono eventi in **altre** Case (Buscicchio, Bozzano) e li si legge come
    operatore di San Bao: con `casa=tutte` compaiono tutti con la loro Casa in `casa_slug` e `casa` di risposta
    `null`; senza `casa` la risposta è di San Bao (i prompt in esercizio dicono «per la tua Casa ometti `casa`») e
    quegli eventi non ci sono. `finestra_gg=2` equivale ad `al=domenica`; `q` filtra per parola.
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    sabato = date.today() + timedelta(days=200 + (5 - date.today().weekday()) % 7)  # un sabato futuro
    domenica = sabato + timedelta(days=1)
    righe = [
        ("buscicchio", "Laboratorio per bambini TEST rete", datetime.combine(sabato, time(10, 0), tzinfo=FUSO_LOCALE), None),
        ("bozzano", "Serata anziani TEST rete", datetime.combine(domenica, time(18, 0), tzinfo=FUSO_LOCALE), None),
    ]
    ids = _inserisci_eventi(righe)
    base = f"{URL.format(email=EMAIL_OP_SANBAO)}/eventi_oggi?data={sabato.isoformat()}"
    try:
        rete = client.get(f"{base}&al={domenica.isoformat()}&casa=tutte")
        finestra = client.get(f"{base}&finestra_gg=2&casa=tutte")
        propria = client.get(f"{base}&al={domenica.isoformat()}")
        filtro = client.get(f"{base}&al={domenica.isoformat()}&casa=tutte&q=bambini")
    finally:
        _rimuovi_eventi(ids)

    assert rete.status_code == 200
    corpo = rete.json()
    assert corpo["casa"] is None, "con `casa=tutte` la risposta è della rete: `casa` deve essere null"
    assert corpo["al"] == domenica.isoformat()
    titoli = {e["titolo"] for e in corpo["eventi"]}
    assert {"Laboratorio per bambini TEST rete", "Serata anziani TEST rete"} <= titoli, (
        f"gli eventi delle altre Case devono comparire, trovati: {titoli}"
    )
    per_titolo = {e["titolo"]: e for e in corpo["eventi"]}
    assert per_titolo["Laboratorio per bambini TEST rete"]["casa_slug"] == "buscicchio"
    assert per_titolo["Serata anziani TEST rete"]["casa_slug"] == "bozzano"

    assert finestra.status_code == 200
    assert finestra.json()["al"] == domenica.isoformat(), "`finestra_gg=2` da sabato finisce domenica"
    assert {e["titolo"] for e in finestra.json()["eventi"]} == titoli

    assert propria.status_code == 200
    assert propria.json()["casa"] == "san-bao", "senza `casa` la risposta è della Casa dell'operatore"
    assert not ({"Laboratorio per bambini TEST rete", "Serata anziani TEST rete"} & {e["titolo"] for e in propria.json()["eventi"]})

    assert filtro.status_code == 200
    titoli_filtro = {e["titolo"] for e in filtro.json()["eventi"]}
    assert "Laboratorio per bambini TEST rete" in titoli_filtro
    assert "Serata anziani TEST rete" not in titoli_filtro, "`q=bambini` non deve restituire la serata anziani"


def test_eventi_oggi_al_e_finestra_gg_discordanti_risponde_422(client, sessione_finta):
    """Due fini diverse per lo stesso intervallo sono un errore dichiarato, non una scelta silenziosa."""
    risposta = client.get(f"{URL.format(email=EMAIL_OP_SANBAO)}/eventi_oggi?data=2026-09-01&al=2026-09-30&finestra_gg=7")
    assert risposta.status_code == 422
    assert "finestra_gg" in risposta.json()["detail"]


@pytest.mark.parametrize(
    ("percorso", "sconosciuto"),
    [
        ("eventi_oggi?data=2026-09-01&giorni=30", "giorni"),
        ("cerca_luogo?q=isee&zona=centro", "zona"),
        ("statistiche?anno=2026", "anno"),
    ],
)
def test_parametro_di_query_sconosciuto_risponde_422_e_lo_nomina(client, sessione_finta, percorso, sconosciuto):
    """Un parametro che il contratto non dichiara è un 422 che lo nomina ed elenca quelli ammessi.

    È il difetto del 2026-09-18: `finestra_gg=30` passato a uno shim che non lo conosceva veniva ignorato in
    silenzio, la risposta copriva un giorno solo e l'assistente concludeva «nessun evento nel mese» con status 200.
    """
    risposta = client.get(f"{URL.format(email=EMAIL_OP_SANBAO)}/{percorso}")
    assert risposta.status_code == 422
    dettaglio = risposta.json()["detail"]
    assert sconosciuto in dettaglio and "ammessi:" in dettaglio


@pytest.mark.live
def test_eventi_oggi_intervallo_include_evento_di_piu_giorni(client, db_vivo):
    """Un evento di più giorni compare in ogni giornata che attraversa (overlap), non solo in quella d'inizio.

    È la «durata nel tempo» degli eventi: una festa che va da sabato a lunedì deve risultare anche chiedendo la
    sola domenica. Il filtro è `inizio <= al AND COALESCE(fine, inizio) >= dal`, non `inizio = giorno`.
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    sabato = date.today() + timedelta(days=210 + (5 - date.today().weekday()) % 7)
    domenica = sabato + timedelta(days=1)
    lunedi = sabato + timedelta(days=2)
    ids = _inserisci_eventi(
        [
            (
                "san-bao",
                "Festa lunga TEST multigiorno",
                datetime.combine(sabato, time(20, 0), tzinfo=FUSO_LOCALE),
                datetime.combine(lunedi, time(2, 0), tzinfo=FUSO_LOCALE),
            )
        ]
    )
    try:
        solo_domenica = client.get(
            f"{URL.format(email=EMAIL_OP_SANBAO)}/eventi_oggi"
            f"?casa=san-bao&data={domenica.isoformat()}&al={domenica.isoformat()}"
        )
    finally:
        _rimuovi_eventi(ids)

    assert solo_domenica.status_code == 200
    titoli = {e["titolo"] for e in solo_domenica.json()["eventi"]}
    assert "Festa lunga TEST multigiorno" in titoli, (
        "un evento sab→lun deve comparire anche chiedendo la sola domenica (overlap)"
    )


# --- ricorrenza: il calcolo delle occorrenze (db/025 `ricorrenza`, db/030 `ricorrenza_fine`) -----------------


def _occorrenze_giorni(base: str, regola: str, dal: str, al: str, fine_ric: str | None = None):
    """I giorni prodotti da `_giorni_occorrenza` per date ISO, senza toccare il database."""
    from app.routes_lettura import _giorni_occorrenza

    return _giorni_occorrenza(
        date.fromisoformat(base),
        regola,
        date.fromisoformat(dal),
        date.fromisoformat(al),
        date.fromisoformat(fine_ric) if fine_ric else None,
    )


def test_ricorrenza_settimanale_produce_una_occorrenza_ogni_sette_giorni():
    """«Ogni lunedì» è una occorrenza a settimana, anche chiedendo un mese intero: è la periodicità di base."""
    giorni = _occorrenze_giorni("2026-01-05", "settimanale", "2026-01-01", "2026-01-31")

    assert giorni == [date(2026, 1, 5), date(2026, 1, 12), date(2026, 1, 19), date(2026, 1, 26)]


def test_ricorrenza_bisettimanale_salta_una_settimana():
    """«Ogni due settimane» non è «ogni settimana»: il passo è di 14 giorni, non 7."""
    giorni = _occorrenze_giorni("2026-01-05", "bisettimanale", "2026-01-01", "2026-02-15")

    assert giorni == [date(2026, 1, 5), date(2026, 1, 19), date(2026, 2, 2)]


def test_ricorrenza_mensile_avanza_sul_calendario_non_di_trenta_giorni():
    """Il 31 diventa il 28 a febbraio e torna il 31 a marzo: un passo di 30 giorni slitterebbe e mentirebbe.

    È il caso limite del calendario: chi fissa «il 31 di ogni mese» non vuole che l'evento
    diventi quello del 2 marzo per effetto di uno scivolamento.
    """
    giorni = _occorrenze_giorni("2026-01-31", "mensile", "2026-01-01", "2026-04-30")

    assert giorni == [
        date(2026, 1, 31),
        date(2026, 2, 28),
        date(2026, 3, 31),
        date(2026, 4, 30),
    ]


def test_ricorrenza_annuale_ripete_nello_stesso_giorno_dell_anno():
    """«Ogni anno» avanza di dodici mesi, non di 365 giorni: il 29 febbraio non deve scivolare al 1 marzo."""
    giorni = _occorrenze_giorni("2028-02-29", "annuale", "2028-01-01", "2030-12-31")

    assert giorni == [date(2028, 2, 29), date(2029, 2, 28), date(2030, 2, 28)]


def test_ricorrenza_si_ferma_al_termine_dichiarato():
    """`ricorrenza_fine` è il limite: «ogni lunedì di maggio» non produce il primo lunedì di giugno."""
    giorni = _occorrenze_giorni("2026-05-04", "settimanale", "2026-05-01", "2026-06-30", "2026-05-31")

    assert giorni == [date(2026, 5, 4), date(2026, 5, 11), date(2026, 5, 18), date(2026, 5, 25)]


def test_ricorrenza_in_un_intervallo_stretto_non_perde_occorrenze():
    """Chiedendo un solo giorno di una serie lunga, l'occorrenza di quel giorno c'è: il calcolo non «parte tardi».

    È il difetto che il salto a un multiplo vicino a `dal` potrebbe introdurre: se il punto di partenza sbagliasse
    di uno, un evento settimanale attivo da mesi sparirebbe proprio nella settimana chiesta.
    """
    giorni = _occorrenze_giorni("2020-01-06", "settimanale", "2026-05-11", "2026-05-11")

    assert giorni == [date(2026, 5, 11)]


@pytest.mark.live
def test_evento_ricorrente_compare_in_ogni_occorrenza_e_porta_i_dettagli(client, db_vivo):
    """Un evento creato con ricorrenza+costo+prenotazione si legge in ogni occorrenza, con i dettagli.

    È la user story «c'è un laboratorio per bambini questa settimana?» e la domanda «è gratuito? serve prenotare?»:
    la ricorrenza produce le occorrenze, e costo/fascia d'età/tag/prenotazione viaggiano con l'item — sono il dato
    che l'assistente non aveva e che cercava a vuoto. La Casa è quella dell'operatore; la riga è rimossa alla fine.
    """
    if not db_vivo:
        pytest.skip("database non raggiungibile")

    base = date.today() + timedelta(days=200)
    titolo = "Laboratorio ricorrente TEST (rimosso dal test)"
    ids = _inserisci_eventi(
        [
            (
                "san-bao",
                titolo,
                datetime.combine(base, time(18, 30), tzinfo=FUSO_LOCALE),
                datetime.combine(base, time(20, 0), tzinfo=FUSO_LOCALE),
            )
        ]
    )
    import asyncpg

    async def _arricchisci() -> None:
        conn = await asyncpg.connect(_dsn_admin())
        try:
            await conn.execute(
                """
                UPDATE trasi.evento
                   SET ricorrenza = 'settimanale', ricorrenza_fine = $2,
                       costo = 0, fascia_eta = '0-13', tag = ARRAY['laboratorio'],
                       prenotazione = true, prenotazione_nota = 'posti limitati'
                 WHERE id = ANY($1::int[])
                """,
                ids,
                base + timedelta(days=21),
            )
        finally:
            await conn.close()

    asyncio.run(_arricchisci())
    try:
        risposta = client.get(
            f"{URL.format(email=EMAIL_OP_SANBAO)}/eventi_oggi"
            f"?casa=san-bao&data={base.isoformat()}&al={(base + timedelta(days=21)).isoformat()}&q=Laboratorio ricorrente TEST"
        )
    finally:
        _rimuovi_eventi(ids)

    assert risposta.status_code == 200
    assert [e["data"] for e in risposta.json()["eventi"]] == [
        (base + timedelta(days=7 * k)).isoformat() for k in range(4)
    ], "un evento settimanale con termine deve produrre le 4 occorrenze della serie, non una sola riga"
    for evento in risposta.json()["eventi"]:
        assert evento["ora_inizio"] == "18:30"
        assert evento["ora_fine"] == "20:00", "la durata resta la stessa a ogni occorrenza"
        assert evento["ricorrenza"] == "settimanale"
        assert evento["gratuito"] is True, "costo 0 è «gratuito»: senza il campo l'assistente non può rispondere"
        assert evento["fascia_eta"] == "0-13"
        assert evento["tag"] == ["laboratorio"]
        assert evento["prenotazione"] is True
        assert evento["prenotazione_nota"] == "posti limitati"
