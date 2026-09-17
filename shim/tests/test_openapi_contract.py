"""Il contratto `shim/openapi.yaml` è quello che Onyx può registrare, e l'app lo espone con le stesse `operationId`.

Questi test difendono il gate V-09: se il contratto si rompe, B2-ONX-04 non può registrare il tool custom e il blocco
B2 resta bloccato. Le verifiche corrispondono ai criteri di done di B3-SHM-09 (plan.md) e alla regola §9.1.
"""

import sys
from typing import Any

import pytest

from attese import OPERAZIONI_ATTESE, RADICE_ONYX, URL_SERVER_ATTESO

METODI_HTTP = ("get", "post", "put", "delete", "patch")


def _schemi_oggetto(nodo: Any, percorso: str = "#"):
    """Ogni schema dichiarato `type: object`, con il percorso per un messaggio d'errore utile."""
    if isinstance(nodo, dict):
        if nodo.get("type") == "object":
            yield percorso, nodo
        for chiave, valore in nodo.items():
            yield from _schemi_oggetto(valore, f"{percorso}/{chiave}")
    elif isinstance(nodo, list):
        for indice, valore in enumerate(nodo):
            yield from _schemi_oggetto(valore, f"{percorso}/{indice}")


def _operazioni(contratto: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Le operazioni del contratto indicizzate per `operationId`."""
    return {
        operazione["operationId"]: operazione
        for elemento in contratto["paths"].values()
        for chiave, operazione in elemento.items()
        if chiave in METODI_HTTP
    }


def test_contratto_espone_le_quattordici_operazioni_attese(contratto):
    """Il contratto contiene esattamente le quattordici operazioni attese, ai percorsi e metodi attesi."""
    trovate = {
        operazione["operationId"]: (metodo, path)
        for path, elemento in contratto["paths"].items()
        for metodo, operazione in elemento.items()
        if metodo in METODI_HTTP
    }

    assert trovate == {
        operation_id: (metodo, path) for operation_id, metodo, path in OPERAZIONI_ATTESE
    }


def test_ogni_operazione_ha_un_summary(contratto):
    """Onyx rifiuta un'operazione priva di `summary`/`description`: è il testo che il LLM legge per scegliere il tool."""
    for operation_id, operazione in _operazioni(contratto).items():
        summary = operazione.get("summary", "")
        assert summary.strip(), f"{operation_id} senza summary"
        # Il summary è una frase italiana: se fosse rimasto un segnaposto, il tool sarebbe inutilizzabile.
        assert "TODO" not in summary and "TBD" not in summary


def test_servers_ha_un_solo_url_atteso(contratto):
    """`servers` ha un solo elemento ed è l'URL con il segnaposto `USER_EMAIL` risolto da Onyx."""
    servers = contratto["servers"]

    assert [s["url"] for s in servers] == [URL_SERVER_ATTESO]


def test_ogni_schema_oggetto_dichiara_additional_properties_false(contratto):
    """Nessuno schema ammette campi liberi: è il presidio strutturale contro i dati personali (§12, V5)."""
    non_conformi = [
        percorso
        for percorso, schema in _schemi_oggetto(contratto)
        if schema.get("additionalProperties") is not False
    ]

    assert non_conformi == []


def test_nessuno_schema_prevede_campi_per_dati_personali(contratto):
    """Le proprietà ammesse non includono nomi di campo anagrafici del **cittadino**: il 422 su
    `nome_cittadino` deve restare possibile.

    L'eccezione dichiarata è `nome`/`ruolo` per `salva_dato` (db/027): le **persone della Casa** entrano
    nella KB con il consenso dell'interessata (decisione del gruppo Processi, 2026-09-17, forma C). Il
    test non allenta il presidio — lo precisa: quel solo schema può portare un nome, e **deve** esigere
    `consenso`, perché è la condizione che rende legittima la pubblicazione. `cognome`, `telefono` e
    `codice_fiscale` restano vietati ovunque, anche lì (il foglio 1.1 chiede «Nome Cognome» e lo shim lo
    raccoglie come un unico campo `nome`).
    """
    vietati = ("nome_cittadino", "cognome", "telefono", "codice_fiscale", "email_cittadino", "nome_persona")

    ammesse = {
        proprieta
        for _, schema in _schemi_oggetto(contratto)
        for proprieta in schema.get("properties", {})
    }

    assert ammesse.isdisjoint(vietati)


def test_le_persone_esistono_solo_nello_schema_che_esige_consenso(contratto):
    """La persona (nome + ruolo + consenso) è ammessa in un solo schema, e il consenso è parte del corpo.

    La decisione C (gruppo Processi) apre una porta: il nome di un **operatore** può finire in chat. La
    sorveglianza giusta non è sul generico `nome` — che è il nome di un *luogo* in `ItemVicinanza`,
    `ItemLuogo` e `PayloadProposta` — è sulla **coppia** che identifica una persona: `ruolo` + `consenso`.
    Se quella coppia compare in un altro schema, o se lo schema delle persone smette di esigere
    `consenso`, la decisione è stata aggirata — ed è *qui* che si accorge, non dopo che l'assistente ha
    già citato un nome in chat.
    """
    schemi_persona = [
        percorso for percorso, schema in _schemi_oggetto(contratto)
        if "consenso" in schema.get("properties", {}) or "informativa" in schema.get("properties", {})
    ]
    assert len(schemi_persona) == 1, (
        f"l'anagrafica delle persone compare in {len(schemi_persona)} schemi ({schemi_persona}): "
        "deve stare in uno solo, quello di `salva_dato`, dove il consenso è parte del corpo"
    )

    schema_persone = contratto["paths"]["/salva_dato"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    proprieta = schema_persone["properties"]
    assert "consenso" in proprieta and "informativa" in proprieta, (
        "lo schema che ammette il nome di una persona deve anche esigere consenso e informativa"
    )
    assert "consenso" in schema_persone.get("required", []), (
        "`consenso` facoltativo equivale a scrivere il nome senza una promessa"
    )


def test_i_corpi_di_richiesta_ammettono_solo_application_json(contratto):
    """Solo `application/json` per i corpi di richiesta: nessun `multipart` o `form-urlencoded` da interpretare."""
    for operation_id, operazione in _operazioni(contratto).items():
        content = operazione.get("requestBody", {}).get("content", {})
        if content:
            assert list(content) == ["application/json"], f"{operation_id}: {list(content)}"


def test_operationid_del_contratto_coincidono_con_lo_schema_di_fastapi(client):
    """Lo stub espone le stesse `operationId` del contratto: il tool registrato da B2 trova gli endpoint di B3."""
    from app.main import app

    attese = {operation_id for operation_id, _, _ in OPERAZIONI_ATTESE}

    esposte = {
        operazione["operationId"]
        for elemento in app.openapi()["paths"].values()
        for metodo, operazione in elemento.items()
        if metodo in METODI_HTTP
    }

    assert esposte == attese


def test_vicino_a_dichiara_provenienza_badge_e_stato_delle_fonti(contratto):
    """`vicino_a` è l'endpoint ibrido: ogni item dichiara provenienza, badge e fiducia, e le fonti esterne il loro stato."""
    schema = contratto["components"]["schemas"]["RispostaVicinoA"]
    item = contratto["components"]["schemas"]["ItemVicinanza"]

    assert set(schema["properties"]) >= {"items", "fonti_esterne"}
    assert set(item["properties"]) >= {
        "provenienza",
        "nome",
        "tipo",
        "indirizzo",
        "lat",
        "lon",
        "distanza_m",
        "aperto_adesso",
        "orari_testo",
        "orari_nota",
        "fonte",
        "url",
        "data_aggiornamento",
        "fiducia",
        "consultato_ts",
        "badge",
    }
    # `aperto_adesso` è nullable: i POI senza orari non si scartano, restano con `null` (azione-se-negativo OSM).
    assert item["properties"]["aperto_adesso"]["nullable"] is True
    assert item["properties"]["orari_nota"]["nullable"] is True
    assert set(contratto["components"]["schemas"]["FonteEsterna"]["properties"]["stato"]["enum"]) == {
        "ok",
        "timeout",
        "errore",
        "scartata_fiducia",
    }


def test_opendata_dichiara_provenienza_badge_risorse_e_stato_dei_portali(contratto):
    """`cerca_opendata` e `leggi_dataset` sono strumenti esterni: ogni item etichettato (V3), ogni portale con uno stato.

    `interrogabile` su ogni risorsa e `portale` su ogni dataset sono i due dati che rendono possibile la seconda
    chiamata: senza, il LLM non saprebbe **quale** risorsa può leggere né **dove**.
    """
    schemi = contratto["components"]["schemas"]

    assert set(schemi["RispostaOpenData"]["properties"]) == {"items", "fonti_esterne"}
    assert set(schemi["ItemOpenData"]["required"]) >= {"provenienza", "portale", "risorse", "fonte", "fiducia", "badge"}
    assert schemi["ItemOpenData"]["properties"]["provenienza"]["enum"] == ["esterna"]
    assert set(schemi["RisorsaOpenData"]["required"]) == {"id", "nome", "formato", "url", "interrogabile"}

    assert set(schemi["RispostaDataset"]["required"]) == {"items", "totale", "fonti_esterne"}
    assert schemi["RispostaDataset"]["properties"]["totale"]["nullable"] is True
    assert set(schemi["RecordDataset"]["required"]) == {
        "provenienza", "titolo", "testo", "fonte", "consultato_ts", "fiducia", "badge",
    }

    operazioni = _operazioni(contratto)
    parametri_lettura = {p["name"]: p for p in operazioni["leggi_dataset"]["parameters"]}
    assert parametri_lettura["risorsa_id"]["required"] is True
    assert parametri_lettura["max"]["schema"]["maximum"] == 50
    assert {p["name"] for p in operazioni["vicino_a"]["parameters"]} >= {"indirizzo"}
    assert schemi["RispostaVicinoA"]["properties"]["centro"]["nullable"] is True
    assert "centro" not in schemi["RispostaVicinoA"]["required"]


def test_contratto_valido_per_un_validatore_openapi_rigoroso(contratto):
    """Il documento è OpenAPI 3.0 valido e ogni `$ref` si risolve.

    Il validatore di Onyx (usato sopra) è volutamente permissivo: non risolve i riferimenti e non guarda la struttura.
    Un `$ref` rotto o una risposta con codice non valido passerebbero la registrazione del tool e fallirebbero poi in
    chat, quando il LLM prova a chiamare l'operazione. Qui il contratto è verificato anche contro lo standard.
    """
    validatore = pytest.importorskip(
        "openapi_spec_validator", reason="openapi-spec-validator non installato"
    )

    validatore.validate(contratto)


def test_validate_openapi_schema_di_onyx_accetta_il_contratto(contratto):
    """Il contratto passa il validatore con cui Onyx lo registra: se fallisse, B2-ONX-04 non potrebbe partire."""
    if RADICE_ONYX not in sys.path:
        sys.path.insert(0, RADICE_ONYX)
    onyx = pytest.importorskip(
        "onyx.tools.tool_implementations.custom.openapi_parsing",
        reason="sorgente di Onyx non disponibile su questa macchina",
    )

    onyx.validate_openapi_schema(contratto)

    assert onyx.openapi_to_url(contratto) == URL_SERVER_ATTESO
    assert {spec.raw_name for spec in onyx.openapi_to_method_specs(contratto)} == {
        operation_id for operation_id, _, _ in OPERAZIONI_ATTESE
    }
