"""Liveness dello stub: è l'unica risposta diversa da 501 e serve agli healthcheck di container e compose."""


def test_healthz_risponde_200_con_stato_ok(client):
    """`GET /healthz` conferma che il processo è vivo."""
    risposta = client.get("/healthz")

    assert risposta.status_code == 200
    assert risposta.json() == {"status": "ok"}
