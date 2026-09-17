"""Gli schemi di risposta dell'applicazione rispecchiano il contratto congelato.

`app/schemi.py` duplica la forma delle risposte per poterla **validare a runtime** (un campo dimenticato diventa un
errore visibile invece di un JSON che il LLM interpreta male). La duplicazione ha un costo: due dichiarazioni possono
divergere. Questo test è il presidio che la tiene onesta — confronta i modelli pydantic con `shim/openapi.yaml`,
campo per campo, per gli schemi della prima metà dello shim.

È il complemento di `test_openapi_contract.py`: quello verifica il documento, questo verifica che il codice che lo
serve non se ne allontani.
"""

import pytest

from attese import TIPI_VICINO_A

MODELLI = {
    "ItemVicinanza": "app.schemi:ItemVicinanza",
    "FonteEsterna": "app.schemi:FonteEsterna",
    "ItemLuogo": "app.schemi:ItemLuogo",
    "ItemEvento": "app.schemi:ItemEvento",
    "RispostaCercaLuogo": "app.schemi:RispostaCercaLuogo",
    "RispostaEventiOggi": "app.schemi:RispostaEventiOggi",
    "RispostaVicinoA": "app.schemi:RispostaVicinoA",
    "ItemStatisticheAmbito": "app.schemi:ItemStatisticheAmbito",
    "RispostaStatistiche": "app.schemi:RispostaStatistiche",
}


def _modello(percorso: str):
    """Il modello pydantic da `app.schemi:Nome`."""
    import importlib

    modulo, nome = percorso.split(":")
    return getattr(importlib.import_module(modulo), nome)


@pytest.mark.parametrize(("nome", "percorso"), sorted(MODELLI.items()), ids=sorted(MODELLI))
def test_i_campi_del_modello_sono_quelli_del_contratto(contratto, nome, percorso):
    """Il modello dichiara esattamente i campi dello schema congelato: né uno in meno né uno in più.

    «Né uno in più» è importante quanto «né uno in meno»: un campo extra nella risposta è una superficie in cui
    potrebbe finire un dato che il contratto non prevede (§12, V5).
    """
    schema = contratto["components"]["schemas"][nome]
    modello = _modello(percorso)

    assert set(modello.model_fields) == set(schema["properties"]), f"{nome}: campi divergenti"


@pytest.mark.parametrize(("nome", "percorso"), sorted(MODELLI.items()), ids=sorted(MODELLI))
def test_i_campi_obbligatori_del_contratto_sono_obbligatori_nel_modello(contratto, nome, percorso):
    """I campi `required` del contratto sono obbligatori anche nel modello pydantic.

    `aperto_adesso` e `orari_nota` sono `required` **e** nullable: la distinzione conta, perché «assente» e «nullo»
    non sono la stessa cosa per il LLM — i campi facoltativi del contratto sono `null`, non omessi.
    """
    schema = contratto["components"]["schemas"][nome]
    modello = _modello(percorso)

    richiesti = set(schema.get("required", ()))
    obbligatori = {campo for campo, info in modello.model_fields.items() if info.is_required()}

    assert obbligatori == richiesti, f"{nome}: obbligatori divergenti (modello: {obbligatori}, contratto: {richiesti})"


def test_il_modello_non_ammette_campi_extra():
    """`extra="forbid"` sul modello: la risposta non può contenere un campo che il contratto non prevede."""
    for nome, percorso in MODELLI.items():
        assert _modello(percorso).model_config.get("extra") == "forbid", f"{nome} ammette campi extra"


def test_il_modello_di_vicinanza_ammette_i_soli_tipi_del_contratto():
    """Il vocabolario dei tipi è quello dell'`enum` del contratto: una lista diversa renderebbe il 422 bugiardo.

    Il messaggio di errore di `vicino_a` elenca i tipi ammessi: se quell'elenco non fosse quello del contratto,
    l'assistente correggerebbe il proprio errore con un valore che non funziona.
    """
    from app.vicinanza import TIPI_AMMESSI

    assert set(TIPI_AMMESSI) == set(TIPI_VICINO_A)


def test_ogni_tipo_del_vocabolario_ha_almeno_una_query_osm():
    """Ogni tipo ammesso è traducibile in almeno un tag OpenStreetMap.

    È l'invariante che rende il 422 corretto: il tipo è rifiutato perché diventa una query, e un tipo ammesso che non
    avesse una query produrrebbe una ricerca vuota per costruzione.
    """
    from app.vicinanza import TIPI_AMMESSI, TIPI_OSM, costruisci_query

    for tipo in TIPI_AMMESSI:
        assert TIPI_OSM[tipo], f"{tipo} senza tag OSM"
        query = costruisci_query(tipo, 40.6, 17.9, 800)
        assert "around:800" in query
        for chiave, valore in TIPI_OSM[tipo]:
            assert f'["{chiave}"="{valore}"]' in query
