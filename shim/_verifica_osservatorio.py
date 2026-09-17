"""Verifica usa-e-getta dei router dell'Osservatorio, senza toccare `shim/app/main.py` (di Main).

Costruisce l'applicazione vera (`crea_app()`) e vi monta i cinque router nuovi sotto `/op`, esattamente come farà
Main. Poi esercita i percorsi reali: login con le credenziali seminate, poi `GET /op/mappa`, `/op/servizi`,
`/op/eventi`, `/op/biglietto`. Overpass non si interroga: `respx` intercetta e si contano le richieste.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import respx
from fastapi.testclient import TestClient

RADICE = Path(__file__).resolve().parent
sys.path.insert(0, str(RADICE))

ENV = (RADICE.parent / "deployment" / ".env").read_text(encoding="utf-8")
VARIABILI = {
    chiave: valore
    for riga in ENV.splitlines()
    if (trovato := re.match(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", riga.strip()))
    for chiave, valore in [trovato.groups()]
}

dsn = VARIABILI["DATABASE_URL"].replace("db_trasi", "127.0.0.1")
os.environ["DATABASE_URL"] = dsn
os.environ["TRASI_SHIM_KEY"] = VARIABILI["TRASI_SHIM_KEY"]
os.environ["OVERPASS_TIMEOUT_S"] = "5"

from app.main import crea_app  # noqa: E402
from app import biglietto_op, eventi_op, mappa_op, poi_op, servizi_op  # noqa: E402

app = crea_app()
for modulo in (mappa_op, poi_op, eventi_op, servizi_op, biglietto_op):
    modulo.monta(app)

CHIAVE = {"X-Trasi-Key": VARIABILI["TRASI_SHIM_KEY"]}

ENDPOINT_OVERPASS = "https://overpass.openstreetmap.fr/api/interpreter"

CORPO_OVERPASS = {
    "elements": [
        {
            "type": "node",
            "id": 111,
            "lat": 40.6330,
            "lon": 17.9420,
            "tags": {"amenity": "bar", "name": "Bar di prova", "opening_hours": "Mo-Fr 07:00-20:00"},
        },
        {
            "type": "way",
            "id": 222,
            "center": {"lat": 40.6350, "lon": 17.9460},
            "tags": {"amenity": "pharmacy", "name": "Farmacia di prova"},
        },
        {
            "type": "node",
            "id": 333,
            "lat": 40.6370,
            "lon": 17.9480,
            "tags": {"amenity": "school", "name": "Scuola di prova"},
        },
    ]
}


def _esito(etichetta: str, risposta) -> None:
    print(f"--- {etichetta}: HTTP {risposta.status_code}")
    corpo = risposta.text
    print(corpo[:600] + ("…" if len(corpo) > 600 else ""))
    print()


def main() -> int:
    errori: list[str] = []
    with TestClient(app, raise_server_exceptions=False) as client:
        login = client.post("/login", json={"casa": "bozzano", "password": "bozzano2026!"})
        print("login:", login.status_code, login.text)
        if login.status_code != 200:
            return 1

        # --- /op/mappa ---------------------------------------------------------------------------------------
        mappa = client.get("/op/mappa", headers=CHIAVE)
        _esito("GET /op/mappa", mappa)
        if mappa.status_code == 200:
            dati = mappa.json()
            print("case:", len(dati["case"]), "luoghi:", len(dati["luoghi"]))
            print("casa_sessione:", dati["casa_sessione"]["nome"], "raggio:", dati["raggio_m"])
            print("badge casa[0]:", dati["case"][0]["badge"])
            print("badge luogo[0]:", dati["luoghi"][0]["badge"])
            print("mia:", [c["nome"] for c in dati["case"] if c["mia"]])
            print("distanza luogo più vicino:", dati["luoghi"][0]["nome"], dati["luoghi"][0]["distanza_m"])
            if len(dati["case"]) != 10:
                errori.append(f"case attese 10, trovate {len(dati['case'])}")
            if len(dati["luoghi"]) != 22:
                errori.append(f"luoghi attesi 22, trovati {len(dati['luoghi'])}")
            if not all(c["badge"] for c in dati["case"]):
                errori.append("badge mancante su una Casa")
            if len([c for c in dati["case"] if c["mia"]]) != 1:
                errori.append("la Casa della sessione non è unica")
        else:
            errori.append(f"/op/mappa: {mappa.status_code} {mappa.text}")

        # --- /op/poi -----------------------------------------------------------------------------------------
        poi_op.svuota_cache()
        bbox = "17.9300,40.6200,17.9600,40.6400"
        with respx.mock(assert_all_called=False) as mock:
            route = mock.post(ENDPOINT_OVERPASS).mock(
                return_value=respx.MockResponse(200, json=CORPO_OVERPASS)
            )
            primo = client.get("/op/poi", headers=CHIAVE, params={"bbox": bbox, "tipi": ["bar", "farmacia", "scuola"]})
            _esito("GET /op/poi (1)", primo)
            print("richieste Overpass dopo la prima:", route.call_count)
            if primo.status_code == 200:
                dati = primo.json()
                print("dalla_cache:", dati["dalla_cache"], "poi:", len(dati["poi"]))
                print("tipi risolti:", sorted({p["tipo"] for p in dati["poi"]}))
                print("badge:", dati["poi"][0]["badge"] if dati["poi"] else "-")
                print("fonti_esterne:", dati["fonti_esterne"])
                print("query inviata:")
                print(route.calls.last.request.content.decode())
                print("user-agent:", route.calls.last.request.headers.get("user-agent"))
                if route.call_count != 1:
                    errori.append(f"3 tipi devono fare UNA richiesta, fatte {route.call_count}")
                if sorted({p["tipo"] for p in dati["poi"]}) != ["bar", "farmacia", "scuola"]:
                    errori.append("i tipi risolti non sono quelli richiesti")
            else:
                errori.append(f"/op/poi: {primo.status_code} {primo.text}")

            # seconda chiamata identica: cache, zero richieste
            secondo = client.get("/op/poi", headers=CHIAVE, params={"bbox": bbox, "tipi": ["bar", "farmacia", "scuola"]})
            print("richieste Overpass dopo la seconda (atteso 1):", route.call_count)
            print("dalla_cache:", secondo.json().get("dalla_cache"))
            if route.call_count != 1:
                errori.append(f"la seconda chiamata identica ha interrogato Overpass: {route.call_count} richieste")
            if not secondo.json().get("dalla_cache"):
                errori.append("la seconda chiamata non dichiara la cache")

        # --- /op/poi: validazioni ----------------------------------------------------------------------------
        for etichetta, parametri in (
            ("bbox malformata", {"bbox": "1,2,3"}),
            ("tipo fuori vocabolario", {"bbox": bbox, "tipi": ["zzz"]}),
            ("bbox troppo grande", {"bbox": "10,30,25,45", "tipi": ["bar"]}),
            ("senza tipi", {"bbox": bbox}),
        ):
            risposta = client.get("/op/poi", headers=CHIAVE, params=parametri)
            print(f"422 atteso — {etichetta}: {risposta.status_code} {risposta.json().get('detail', '')[:160]}")
            if risposta.status_code != 422:
                errori.append(f"{etichetta}: atteso 422, ottenuto {risposta.status_code}")

        # --- /op/poi: Overpass in timeout → 200 con stato dichiarato -----------------------------------------
        poi_op.svuota_cache()
        with respx.mock(assert_all_called=False) as mock:
            mock.post(ENDPOINT_OVERPASS).mock(side_effect=respx.MockResponse(502, text="ko"))
            mock.post("https://overpass-api.de/api/interpreter").mock(side_effect=respx.MockResponse(502, text="ko"))
            guasto = client.get("/op/poi", headers=CHIAVE, params={"bbox": bbox, "tipi": ["bar"]})
            print("Overpass giù:", guasto.status_code, guasto.json().get("fonti_esterne"))
            if guasto.status_code != 200:
                errori.append(f"Overpass giù: atteso 200, ottenuto {guasto.status_code}")
            if guasto.json()["fonti_esterne"][0]["stato"] != "errore":
                errori.append("stato della fonte non dichiarato")
            if guasto.json()["poi"] != []:
                errori.append("lista POI non vuota con la fonte giù")

        # --- /op/eventi --------------------------------------------------------------------------------------
        eventi = client.get("/op/eventi", headers=CHIAVE, params={"dal": "2026-09-15", "al": "2026-09-30"})
        _esito("GET /op/eventi", eventi)
        if eventi.status_code == 200:
            dati = eventi.json()
            print("periodo:", dati["periodo"], "eventi:", len(dati["eventi"]))
            for e in dati["eventi"]:
                print(" ", e["giorno"], e["ora_inizio"], e["titolo"], "|", e["casa_nome"], "|", e["badge"])
        else:
            errori.append(f"/op/eventi: {eventi.status_code} {eventi.text}")

        invertita = client.get("/op/eventi", headers=CHIAVE, params={"dal": "2026-09-30", "al": "2026-09-15"})
        print("finestra invertita:", invertita.status_code, invertita.json().get("detail"))
        if invertita.status_code != 422:
            errori.append(f"finestra invertita: atteso 422, ottenuto {invertita.status_code}")

        lunga = client.get("/op/eventi", headers=CHIAVE, params={"dal": "2026-01-01", "al": "2026-12-31"})
        print("finestra troppo ampia:", lunga.status_code, lunga.json().get("detail"))
        if lunga.status_code != 422:
            errori.append(f"finestra ampia: atteso 422, ottenuto {lunga.status_code}")

        # --- /op/servizi -------------------------------------------------------------------------------------
        servizi = client.get("/op/servizi", headers=CHIAVE)
        _esito("GET /op/servizi", servizi)
        if servizi.status_code == 200:
            print("casa:", servizi.json()["casa"], "servizi:", len(servizi.json()["servizi"]))
        else:
            errori.append(f"/op/servizi: {servizi.status_code} {servizi.text}")

        inesistente = client.get("/op/servizi", headers=CHIAVE, params={"casa_id": 999999})
        print("Casa inesistente:", inesistente.status_code, inesistente.json().get("detail"))
        if inesistente.status_code != 404:
            errori.append(f"Casa inesistente: atteso 404, ottenuto {inesistente.status_code}")

        # --- /op/biglietto -----------------------------------------------------------------------------------
        biglietto = client.get("/op/biglietto", headers=CHIAVE, params={"luogo_id": 21})
        _esito("GET /op/biglietto?luogo_id=21", biglietto)
        if biglietto.status_code == 200:
            testo = biglietto.text
            print("content-type:", biglietto.headers.get("content-type"))
            for divieto in ("<input", "<form", "cittadino"):
                if divieto in testo:
                    errori.append(f"il biglietto contiene «{divieto}»")
        else:
            errori.append(f"/op/biglietto: {biglietto.status_code} {biglietto.text}")

        assente = client.get("/op/biglietto", headers=CHIAVE, params={"luogo_id": 999999})
        print("luogo inesistente:", assente.status_code, assente.json().get("detail"))
        if assente.status_code != 404:
            errori.append(f"luogo inesistente: atteso 404, ottenuto {assente.status_code}")

        with respx.mock(assert_all_called=False) as mock:
            mock.post(ENDPOINT_OVERPASS).mock(
                return_value=respx.MockResponse(
                    200,
                    json={"elements": [{"type": "node", "id": 111, "lat": 40.633, "lon": 17.942,
                                        "tags": {"amenity": "bar", "name": "Bar di prova"}}]},
                )
            )
            esterno = client.get("/op/biglietto", headers=CHIAVE, params={"luogo_id": "osm:node:111"})
            print("biglietto POI esterno:", esterno.status_code, "badge Esterna:",
                  "[Esterna" in esterno.text)
            if esterno.status_code != 200:
                errori.append(f"biglietto POI: {esterno.status_code} {esterno.text}")

        # --- autenticazione ----------------------------------------------------------------------------------
        senza_cookie = TestClient(app, raise_server_exceptions=False)
        for percorso in ("/op/mappa", "/op/poi", "/op/eventi", "/op/servizi", "/op/biglietto"):
            risposta = senza_cookie.get(percorso, headers=CHIAVE)
            print(f"senza cookie {percorso}: {risposta.status_code} {risposta.json().get('detail')}")
            if risposta.status_code != 401:
                errori.append(f"{percorso} senza cookie: atteso 401, ottenuto {risposta.status_code}")
        senza_cookie.close()

        # --- contratto: nessuna traccia nell'OpenAPI ---------------------------------------------------------
        percorsi = set(app.openapi()["paths"])
        print("\npercorsi OpenAPI:", sorted(percorsi))
        if any("/op/" in percorso for percorso in percorsi):
            errori.append("un endpoint /op è finito nell'OpenAPI")

    print()
    if errori:
        print("PROBLEMI:")
        for errore in errori:
            print(" -", errore)
        return 1
    print("TUTTO OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
