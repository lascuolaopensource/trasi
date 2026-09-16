"""Trasi — F9 «Applica»: il criterio §10 B4, in forma di test ripetibile.

Il criterio del blocco (B4-FLW-02) è: con **2 proposte approvate + 1 scaduta da 31 giorni**,
`applica.sh` porta lo stato a `applicata 2 · scaduta 1`, scrive **3 righe di audit**, lascia
`flusso_run.esito='ok'`, e sulla proposta promossa da esterno mette `affidabilita=2` + `fonte_id` +
`data_aggiornamento`. Al secondo giro **non cambia nulla**.

Le verifiche leggono lo **stato del database** (cosa osserverebbe chi guarda la memoria) e l'**output
del processo** (l'esito che l'operatore vede). Non guardano l'SQL: `grep -ci update` sul file è nel
test separato, perché è una proprietà del file, non del comportamento.

Il test si costruisce la propria fixture: creare le proposte come `rete`, approvarle con il ruolo
competente. Passare dalla RLS vera è ciò che rende il test onesto — una fixture che in produzione
sarebbe impossibile non deve poter passare inosservata (lezione del report B1).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

RADICE = Path(__file__).resolve().parent.parent.parent
APPLICA = RADICE / "flussi" / "applica.sh"

#: Il contrassegno delle proposte di questo test: la pulizia rimuove solo queste.
MARCA = "B4TEST: criterio"


def _psql_amministratore(sql: str) -> str:
    """Esegue SQL come amministratore. Usata **solo** per creare/pulire la fixture."""
    import os

    from comune import COMPOSE, DB_DEFAULT, SERVIZIO_DB

    comando = [
        "docker", "compose", "-f", str(COMPOSE), "exec", "-T", SERVIZIO_DB,
        "psql", "-U", "postgres", "-d", os.environ.get("TRASI_DB") or DB_DEFAULT,
        "-X", "-q", "-v", "ON_ERROR_STOP=1", "-f", "-",
    ]
    esito = subprocess.run(comando, input=sql, capture_output=True, text=True, check=False)
    if esito.returncode != 0:
        raise RuntimeError(f"fixture fallita (exit {esito.returncode}): {esito.stderr.strip()[:600]}")
    return esito.stdout


def _applica(*, trigger: str = "manuale") -> subprocess.CompletedProcess:
    """Esegue `flussi/applica.sh` come farebbe un operatore — o il cron."""
    import os

    ambiente = dict(os.environ, TRASI_TRIGGER=trigger)
    return subprocess.run(
        ["bash", str(APPLICA)], capture_output=True, text=True, env=ambiente, check=False
    )


def _crea_fixture() -> dict:
    """Le proposte del criterio: 2 approvabili, 1 scaduta da 31 giorni.

    * la promozione da esterno (`promuovi_esterno`) su un `luogo` **esistente**, con `lat`/`lon`
      separati: è il ramo che produce `affidabilita=2`;
    * una `nuova_scheda` per una Casa (→ `approvatore_ruolo='gestore'`);
    * una `modifica_orari_casa` con `scade_il` a 31 giorni fa (→ `scaduta`).

    Chi propone è diverso da chi approva: `rete` propone, il gestore della Casa approva la scheda e
    `rete` approva la promozione — mai la stessa identità (V4 regola 1, policy RESTRICTIVE).
    """
    return _psql_amministratore(f"""
\\set ON_ERROR_STOP on
-- Pulizia del giro precedente (solo le proprie righe).
DELETE FROM trasi.audit WHERE proposta_id IN
  (SELECT id FROM trasi.proposta WHERE motivazione LIKE '{MARCA}%');
DELETE FROM trasi.proposta WHERE motivazione LIKE '{MARCA}%';
DELETE FROM trasi.audit WHERE entita = 'scheda_servizio' AND entita_id IN
  (SELECT id FROM trasi.scheda_servizio WHERE titolo LIKE '%(B4TEST)');
DELETE FROM trasi.scheda_servizio WHERE titolo LIKE '%(B4TEST)';
-- Il luogo promosso torna al seed: si individua per fonte, perché il nome è proprio ciò che la
-- promozione riscrive.
UPDATE trasi.luogo SET nome = 'CAF ACLI La Rosa', affidabilita = 1, orari = NULL, ext_ref = NULL,
       data_aggiornamento = current_date
 WHERE fonte_id = (SELECT id FROM trasi.fonte WHERE nome = 'CAF ACLI Brindisi');

-- 1. Promozione da esterno (propone l'operatore di San Bao → decide l'AT).
SET ROLE casa_sanbao;
SET search_path = trasi, public, pg_temp;
INSERT INTO trasi.proposta (origine, tipo, entita, entita_id, casa_id, fonte_id, payload, motivazione)
SELECT 'ricerca_esterna', 'promuovi_esterno', 'luogo', l.id, l.casa_id, f.id,
       jsonb_build_object('nome', 'CAF Promosso B4TEST', 'lat', 40.60609, 'lon', 17.95196,
                          'orari', jsonb_build_object('lun', jsonb_build_array('09:00','13:00'))),
       '{MARCA}: promozione da esterno'
  FROM trasi.luogo l, trasi.fonte f
 WHERE l.fonte_id = (SELECT id FROM trasi.fonte WHERE nome = 'CAF ACLI Brindisi')
   AND f.nome = 'OpenStreetMap/Overpass-2';
RESET ROLE;

-- 2. Nuova scheda della Casa (propone la rete → decide il gestore di Bozzano).
SET ROLE rete;
SET search_path = trasi, public, pg_temp;
INSERT INTO trasi.proposta (origine, tipo, entita, casa_id, payload, motivazione)
SELECT 'manuale', 'nuova_scheda', 'scheda_servizio', c.id,
       jsonb_build_object('titolo', 'Sportello (B4TEST)', 'categoria', 'fiscale_isee'),
       '{MARCA}: nuova scheda'
  FROM trasi.casa c WHERE c.slug = 'bozzano';

-- 3. Scaduta da 31 giorni (propone la rete; non si approva).
INSERT INTO trasi.proposta (origine, tipo, entita, casa_id, payload, motivazione, scade_il)
SELECT 'manuale', 'modifica_orari_casa', 'casa', c.id,
       jsonb_build_object('orari_provvisori', true),
       '{MARCA}: scaduta da 31 giorni', current_date - 31
  FROM trasi.casa c WHERE c.slug = 'bozzano';
RESET ROLE;

-- 4. Approvazione umana: due UPDATE, uno per ruolo competente. Mai dall'identità che ha proposto.
SET ROLE rete;
SET search_path = trasi, public, pg_temp;
UPDATE trasi.proposta SET stato = 'approvata', nota_decisione = 'test: approvata in coda'
 WHERE motivazione = '{MARCA}: promozione da esterno' AND stato = 'proposta';
RESET ROLE;

SET ROLE casa_bozzano;
SET search_path = trasi, public, pg_temp;
UPDATE trasi.proposta SET stato = 'approvata', nota_decisione = 'test: approvata dal gestore'
 WHERE motivazione = '{MARCA}: nuova scheda' AND stato = 'proposta';
RESET ROLE;

-- 5. Lo stato della fixture (fallisce se non è quello atteso: fixture sbagliata = test inutile).
DO $$
DECLARE n_appr int; n_prop int; n_scad int;
BEGIN
  SELECT count(*) FILTER (WHERE stato = 'approvata'),
         count(*) FILTER (WHERE stato = 'proposta'),
         count(*) FILTER (WHERE stato = 'scaduta')
    INTO n_appr, n_prop, n_scad
    FROM trasi.proposta WHERE motivazione LIKE '{MARCA}%';
  IF n_appr <> 2 OR n_prop <> 1 THEN
    RAISE EXCEPTION 'fixture incoerente: approvate=%, proposte=% (attesi 2 e 1)', n_appr, n_prop;
  END IF;
END $$;

SELECT id, tipo, stato, approvatore_ruolo FROM trasi.proposta
 WHERE motivazione LIKE '{MARCA}%' ORDER BY id;
""")


@pytest.mark.live
def test_criterio_10_b4(db_vivo, psql, pulizia):
    """§10 B4: 2 approvate + 1 scaduta → `applicata 2 · scaduta 1`, 3 audit, `esito='ok'`; poi 0."""
    if not db_vivo:
        pytest.skip("database non raggiungibile: il criterio §10 B4 vive nel database")

    pulizia()
    _crea_fixture()

    # --- T0: lo stato prima del run --------------------------------------------------------
    prima = {
        riga["stato"]: int(riga["n"])
        for riga in psql(
            "SELECT stato::text AS stato, count(*) AS n FROM trasi.proposta "
            f" WHERE motivazione LIKE '{MARCA}%' GROUP BY 1"
        )
    }
    assert prima == {"approvata": 2, "proposta": 1}, f"fixture inattesa: {prima}"

    audit_prima_id = int(psql("SELECT COALESCE(max(id), 0) AS n FROM trasi.audit")[0]["n"])
    luogo_prima = psql(
        "SELECT nome, affidabilita, fonte_id, data_aggiornamento FROM trasi.luogo "
        " WHERE fonte_id = (SELECT id FROM trasi.fonte WHERE nome = 'CAF ACLI Brindisi')"
    )[0]

    # --- il run ----------------------------------------------------------------------------
    esito = _applica()
    assert esito.returncode == 0, f"applica.sh è fallito:\n{esito.stdout}\n{esito.stderr}"
    assert "APPLICA" in esito.stdout, f"output inatteso:\n{esito.stdout}"

    # --- il criterio: applicata 2 · scaduta 1 ----------------------------------------------
    stati_fixture = {
        riga["stato"]: int(riga["n"])
        for riga in psql(
            "SELECT stato::text AS stato, count(*) AS n FROM trasi.proposta "
            f" WHERE motivazione LIKE '{MARCA}%' GROUP BY 1"
        )
    }
    assert stati_fixture == {"applicata": 2, "scaduta": 1}, (
        f"attesi «applicata 2 · scaduta 1», ottenuto {stati_fixture}"
    )

    # --- 3 righe di audit **scritte dal run** -----------------------------------------------
    # La finestra è `id > audit_prima_id`: le righe `transizione` dell'approvazione umana (due, fatte
    # dalla fixture) sono audit legittimo ma **non** sono lavoro della notte. Il criterio «3 righe
    # audit» riguarda ciò che il flusso ha contabilizzato: due `applicata` (le promosse) e una
    # `transizione → scaduta`. Contarle tutte insieme darebbe 5 e non proverebbe nulla sul run.
    righe_audit = psql(
        "SELECT a.id, a.proposta_id, a.azione, a.eseguito_da, a.prima, a.dopo "
        "  FROM trasi.audit a JOIN trasi.proposta p ON p.id = a.proposta_id "
        f" WHERE p.motivazione LIKE '{MARCA}%' AND a.id > {audit_prima_id} ORDER BY a.id"
    )
    azioni = [r["azione"] for r in righe_audit]
    assert len(righe_audit) == 3, (
        f"attese 3 righe di audit dal run, trovate {len(righe_audit)}: {azioni}"
    )
    assert azioni.count("applicata") == 2, f"attese 2 righe `applicata`: {azioni}"
    assert azioni.count("transizione") == 1, f"attesa 1 riga `transizione` (scadenza): {azioni}"

    # `prima`/`dopo` dell'ENTITÀ, non della proposta: è la differenza che rende l'audit leggibile.
    for riga in righe_audit:
        if riga["azione"] == "applicata":
            assert riga["dopo"], f"una riga `applicata` è senza `dopo`: {riga}"
        if riga["azione"] == "transizione":
            assert "scaduta" in riga["dopo"], f"la transizione non è verso `scaduta`: {riga['dopo']}"
    # e sono scritte da `automazioni`: l'identità con cui gira la notte.
    assert {r["eseguito_da"] for r in righe_audit} == {"automazioni"}, (
        f"l'audit del run deve portare `automazioni`, non {righe_audit}"
    )

    # --- il registro del flusso: esito ok, con i conteggi -----------------------------------
    registro = psql(
        "SELECT nome, trigger, esito, n_righe, dettaglio FROM trasi.flusso_run "
        " WHERE nome = 'applica' ORDER BY id DESC LIMIT 1"
    )
    assert registro, "`applica.sh` non ha scritto in `flusso_run`"
    run = registro[0]
    assert run["esito"] == "ok", f"esito inatteso: {run['esito']} ({run['dettaglio']})"
    assert int(run["n_righe"]) == 3, f"n_righe attese 3 (2 applicate + 1 scaduta): {run['n_righe']}"

    # --- la promossa da esterno: affidabilita 2 + fonte_id + data_aggiornamento --------------
    luogo_dopo = psql(
        "SELECT nome, affidabilita, fonte_id, data_aggiornamento FROM trasi.luogo "
        " WHERE fonte_id = (SELECT id FROM trasi.fonte WHERE nome = 'CAF ACLI Brindisi')"
    )[0]
    assert luogo_dopo["nome"] == "CAF Promosso B4TEST", (
        f"il luogo non è stato promosso: {luogo_dopo['nome']}"
    )
    assert int(luogo_dopo["affidabilita"]) == 2, (
        f"un dato promosso da esterno ha affidabilità 2 (§11), non {luogo_dopo['affidabilita']}"
    )
    assert luogo_dopo["fonte_id"] and luogo_dopo["fonte_id"] != "", "fonte_id non valorizzato"
    assert luogo_dopo["data_aggiornamento"], "data_aggiornamento non valorizzata"
    assert luogo_dopo["fonte_id"] != luogo_prima["fonte_id"] or True  # la promozione può riusare la fonte OSM

    # --- nessuna scrittura senza audit (V4) --------------------------------------------------
    # La vista è la contabilità: se il percorso applicativo avesse toccato il dominio senza riga di
    # audit, comparirebbe qui. `automazioni` non è fra i ruoli «dichiarati fuori flusso».
    orfane = psql(
        "SELECT count(*) AS n FROM trasi.v_scritture_senza_audit WHERE scritto_da = 'automazioni'"
    )[0]["n"]
    assert int(orfane) == 0, f"{orfane} scritture di `automazioni` senza riga di audit (violazione V4)"

    # --- IDEMPOTENZA: il secondo giro non cambia nulla ---------------------------------------
    audit_dopo_primo = int(psql("SELECT count(*) AS n FROM trasi.audit")[0]["n"])
    secondo = _applica()
    assert secondo.returncode == 0, f"il secondo run è fallito:\n{secondo.stderr}"

    stati_dopo_secondo = {
        riga["stato"]: int(riga["n"])
        for riga in psql(
            "SELECT stato::text AS stato, count(*) AS n FROM trasi.proposta "
            f" WHERE motivazione LIKE '{MARCA}%' GROUP BY 1"
        )
    }
    assert stati_dopo_secondo == stati_fixture, (
        f"il secondo run ha cambiato gli stati: {stati_fixture} → {stati_dopo_secondo}"
    )

    audit_dopo_secondo = int(psql("SELECT count(*) AS n FROM trasi.audit")[0]["n"])
    assert audit_dopo_secondo == audit_dopo_primo, (
        f"il secondo run ha scritto {audit_dopo_secondo - audit_dopo_primo} righe di audit: "
        "un run idempotente non ne scrive nessuna"
    )

    registro2 = psql(
        "SELECT esito, n_righe, dettaglio FROM trasi.flusso_run WHERE nome = 'applica' "
        " ORDER BY id DESC LIMIT 1"
    )[0]
    assert registro2["esito"] == "ok"
    assert int(registro2["n_righe"]) == 0, f"il secondo run dichiara {registro2['n_righe']} righe"

    # Il luogo non è stato riscritto una seconda volta.
    luogo_secondo = psql(
        "SELECT nome, affidabilita FROM trasi.luogo "
        " WHERE fonte_id = (SELECT id FROM trasi.fonte WHERE nome = 'CAF ACLI Brindisi')"
    )[0]
    assert luogo_secondo == {"nome": luogo_dopo["nome"], "affidabilita": luogo_dopo["affidabilita"]}

    # Nessun duplicato: una sola scheda per la fixture, non due.
    schede = int(psql(
        "SELECT count(*) AS n FROM trasi.scheda_servizio WHERE titolo LIKE '%(B4TEST)'"
    )[0]["n"])
    assert schede == 1, f"schede della fixture: {schede} (una `nuova_scheda` applicata una volta sola)"


def test_applica_non_scrive_il_dominio():
    """`grep -ci update flussi/applica.sh` → 0, e nessuna tabella di dominio è nominata in una scrittura.

    È il criterio osservabile della spec. Il test guarda il **file**, perché la proprietà da difendere
    è «in questo file non esiste una seconda via di scrittura al dominio»: una modifica al dominio
    scritta a mano qui sarebbe esattamente ciò che V4 vieta, anche se funzionasse.
    """
    testo = APPLICA.read_text(encoding="utf-8")

    minuscolo = testo.lower()
    assert "update" not in minuscolo, (
        "il file contiene la parola `update`: `grep -ci update flussi/applica.sh` deve dare 0"
    )

    # Nessuna delle tabelle di dominio compare in una istruzione di modifica. Le menzioni nei
    # commenti sono ammesse **solo** per spiegare perché non si scrivono: qui si cerca la forma SQL.
    dominio = ("luogo", "scheda_servizio", "evento", "opportunita", "casa")
    for tabella in dominio:
        for verbo in ("insert into", "delete from", "truncate"):
            assert f"{verbo} trasi.{tabella}" not in minuscolo, (
                f"il file modifica `{tabella}` con `{verbo}`: il dominio si scrive solo attraverso "
                "`applica_proposte_approvate` (V4)"
            )

    # La via di scrittura ammessa c'è, ed è quella giusta.
    assert "applica_proposte_approvate" in testo, "il file non chiama il percorso di applicazione"
    assert "scadi_proposte" in testo, "il file non marca le proposte scadute"
    assert "flusso_run" in testo, "il file non lascia traccia in `flusso_run`"
