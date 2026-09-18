"""`GET /op/config`: l'indirizzo di Onyx per il tasto «Chiedi» della Home.

Tre fatti, nello stile di `test_conversazioni_op.py` (sessione contraffatta, ambiente di prova): l'URL composto da
`ONYX_DOMAIN` e dalla persona della chat; il `503` dichiarato quando il dominio manca; il `401` senza sessione.
"""

from __future__ import annotations

import pytest

import ambiente

DETAIL_ONYX_NON_CONFIGURATO = "Onyx non configurato: manca ONYX_DOMAIN"
DOMINIO_DI_PROVA = "onyx.di-prova.example"


class SessioneFinta:
    """La sessione della Casa: all'endpoint basta che esista."""

    ruolo = "casa_sanbao"
    casa_slug = "san-bao"
    casa_id = 5
    email = ""


@pytest.fixture
def app_cliente(monkeypatch, tmp_path):
    """`TestClient` sull'app reale con la sessione sostituita; `ONYX_DOMAIN` e `ONYX_PERSONA_ID` dall'ambiente di prova."""
    monkeypatch.setattr("app.chat.PERCORSO_ENV", tmp_path / "env-inesistente")
    monkeypatch.delenv("ONYX_PERSONA_ID", raising=False)

    from fastapi.testclient import TestClient

    from app import auth, main as modulo_main
    from app.settings import get_settings

    def costruisci(dominio: str | None = DOMINIO_DI_PROVA, persona_id: str | None = None):
        if dominio is None:
            monkeypatch.delenv("ONYX_DOMAIN", raising=False)
        else:
            monkeypatch.setenv("ONYX_DOMAIN", dominio)
        if persona_id is not None:
            monkeypatch.setenv("ONYX_PERSONA_ID", persona_id)
        ambiente.configura_ambiente()
        get_settings.cache_clear()
        applicazione = modulo_main.crea_app()
        applicazione.dependency_overrides[auth.sessione_corrente] = lambda: SessioneFinta()
        return TestClient(applicazione, raise_server_exceptions=False)

    yield costruisci
    get_settings.cache_clear()


def test_senza_sessione_risponde_401(client_anonimo):
    """Senza cookie l'endpoint risponde 401: stessa guardia degli altri `/op/…`."""
    risposta = client_anonimo.get("/op/config")
    assert risposta.status_code == 401
    assert risposta.json() == {"detail": "sessione assente o scaduta"}


def test_con_dominio_risponde_l_url_dell_assistente(app_cliente):
    """`ONYX_DOMAIN` configurato → `https://<dominio>/chat?agentId=2`: la persona è quella di `chat.py`, nient'altro nell'URL (V5)."""
    risposta = app_cliente().get("/op/config")
    assert risposta.status_code == 200
    assert risposta.json() == {"onyx_url": f"https://{DOMINIO_DI_PROVA}/chat?agentId=2"}


def test_la_persona_segue_onyx_persona_id(app_cliente):
    """`ONYX_PERSONA_ID` cambia l'assistente anche qui: una sola sorgente per la chat e per il collegamento."""
    risposta = app_cliente(persona_id="9").get("/op/config")
    assert risposta.status_code == 200
    assert risposta.json()["onyx_url"].endswith("/chat?agentId=9")


def test_senza_dominio_risponde_503_dichiarato(app_cliente):
    """`ONYX_DOMAIN` vuoto o assente → 503 con il motivo in italiano, mai un 500 né un URL inventato."""
    for dominio in (None, "", "   "):
        risposta = app_cliente(dominio=dominio).get("/op/config")
        assert risposta.status_code == 503, dominio
        assert risposta.json() == {"detail": DETAIL_ONYX_NON_CONFIGURATO}


def test_fuori_dal_contratto_con_onyx(app_cliente):
    """`/op/config` non compare nel documento OpenAPI generato: non è uno strumento del LLM (gate V-09)."""
    client = app_cliente()
    assert "/op/config" not in client.get("/openapi.json").json()["paths"]
