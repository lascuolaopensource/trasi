"""Le invarianti del contratto congelato sono verificate anche dall'applicazione.

`servers` con un solo URL non è una preferenza: Onyx rifiuta il contratto con zero o due URL
(`openapi_parsing.openapi_to_url`). E il prefisso delle route è ricavato da quell'URL, quindi un contratto malformato
non deve produrre un'applicazione che risponde a un indirizzo diverso da quello che Onyx chiama: deve fallire subito.

`app.main` è importato **qui sopra**, prima di ogni contraffazione: il modulo costruisce l'applicazione all'import,
quindi va caricato mentre il contratto reale è ancora in vigore.
"""

import pytest

from app import contratto as modulo_contratto
from app.main import crea_app

# I lettori memorizzati (`lru_cache`) del contratto reale, azzerati prima e dopo ogni contraffazione.
LETTORI = (modulo_contratto.contratto, modulo_contratto.url_server, modulo_contratto.prefisso_path)


@pytest.fixture
def contratto_doctored(monkeypatch):
    """Sostituisce il contratto letto da disco con un documento scelto dal test."""

    def applica(documento):
        monkeypatch.setattr(modulo_contratto, "contratto", lambda: documento)
        for lettore in LETTORI:
            lettore.cache_clear()

    yield applica
    monkeypatch.undo()
    for lettore in LETTORI:
        lettore.cache_clear()


@pytest.mark.parametrize(
    "servers",
    [
        pytest.param([], id="nessun_server"),
        pytest.param(
            [{"url": "http://shim:8000/v1/u/USER_EMAIL"}, {"url": "http://altro:8000/v1/u/USER_EMAIL"}],
            id="due_server",
        ),
    ],
)
def test_servers_malformato_impedisce_lo_avvio(contratto_doctored, servers):
    """Un contratto senza un unico server solleva un errore esplicito invece di avviare un'applicazione ambigua."""
    contratto_doctored({"paths": {}, "servers": servers})

    with pytest.raises(modulo_contratto.ContrattoNonValido):
        modulo_contratto.url_server()


def test_url_server_senza_prefisso_impedisce_lo_avvio(contratto_doctored):
    """Se l'URL del server non indicasse un prefisso, le route finirebbero in radice: meglio fallire all'avvio."""
    contratto_doctored({"paths": {}, "servers": [{"url": "http://shim:8000"}]})

    with pytest.raises(modulo_contratto.ContrattoNonValido):
        modulo_contratto.prefisso_path()


def test_prefisso_path_deriva_dall_url_del_contratto(contratto_doctored):
    """Il prefisso delle route è esattamente il percorso di `servers[0].url`, col segnaposto come parametro."""
    contratto_doctored({"paths": {}, "servers": [{"url": "http://shim:8000/v1/u/USER_EMAIL"}]})

    assert modulo_contratto.prefisso_path() == "/v1/u/{email}"


def test_contratto_non_leggibile_o_non_oggetto_impedisce_lo_avvio(monkeypatch, tmp_path):
    """Un contratto assente o che non è un oggetto dà un errore esplicito, non un errore oscuro più avanti."""
    inesistente = tmp_path / "assente.yaml"
    monkeypatch.setattr(modulo_contratto, "PERCORSO_CONTRATTO", inesistente)
    with pytest.raises(modulo_contratto.ContrattoNonValido):
        modulo_contratto._carica()

    non_oggetto = tmp_path / "lista.yaml"
    non_oggetto.write_text("- uno\n- due\n", encoding="utf-8")
    monkeypatch.setattr(modulo_contratto, "PERCORSO_CONTRATTO", non_oggetto)
    with pytest.raises(modulo_contratto.ContrattoNonValido):
        modulo_contratto._carica()


def test_operazione_attesa_assente_dal_contratto_impedisce_lo_avvio(contratto_doctored):
    """Se il contratto perdesse un'operazione, l'app non parte a metà: il tool di B2 punterebbe a un endpoint inesistente."""
    contratto_doctored(
        {
            "servers": [{"url": "http://shim:8000/v1/u/USER_EMAIL"}],
            "paths": {"/cerca_luogo": {"get": {"operationId": "cerca_luogo", "summary": "Cerca."}}},
        }
    )

    with pytest.raises(RuntimeError, match="operationId assenti"):
        crea_app()
