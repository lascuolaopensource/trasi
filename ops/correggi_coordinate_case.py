#!/usr/bin/env python3
"""Corregge solo le sedi verificate, passando da proposta, rete e applicatore.

Da root del repository, dopo `bash db/apply.sh 006`:
  python3 ops/correggi_coordinate_case.py ops/coordinate_case_verificate.json
  python3 ops/correggi_coordinate_case.py ops/coordinate_case_verificate.json --apply

La prima esecuzione mostra diff/fonti e fa ROLLBACK (nessun dato persistente,
ma le sequence possono avanzare). --apply attesta la revisione umana dei diff
ed effettua COMMIT solo se entrambe le geometrie e tutti gli audit coincidono.
Trasporto amministrativo come db/apply.sh: docker compose/psql; il superuser
serve SOLO a impersonare identità distinte via SET SESSION AUTHORIZATION.
Le scritture al dominio appartengono esclusivamente alla funzione applicatore.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from flussi.comune import _da_env_file  # noqa: E402


SQL = r"""
BEGIN;
SET LOCAL lock_timeout = '10s';
SELECT pg_advisory_xact_lock(620260918);
CREATE TEMP TABLE coordinate_input ON COMMIT DROP AS
SELECT * FROM jsonb_to_recordset(:'fixture'::jsonb)
  AS f(slug text, lat double precision, lon double precision,
       indirizzo text, fonte_url text, maps_url text);
CREATE TEMP TABLE coordinate_target (
  slug text PRIMARY KEY, casa_id integer NOT NULL, luogo_id integer NOT NULL,
  fonte_id integer NOT NULL, payload jsonb NOT NULL,
  casa_prima jsonb NOT NULL, luogo_prima jsonb NOT NULL
) ON COMMIT DROP;
CREATE TEMP TABLE coordinate_proposte (
  id bigint PRIMARY KEY, entita text NOT NULL, entita_id integer NOT NULL,
  prima jsonb NOT NULL
) ON COMMIT DROP;
CREATE TEMP TABLE coordinate_esiti (
  proposta_id bigint, tipo text, entita text, entita_id integer, esito text
) ON COMMIT DROP;
GRANT SELECT ON coordinate_input, coordinate_target, coordinate_proposte TO automazioni, rete;
GRANT INSERT ON coordinate_proposte, coordinate_esiti TO automazioni;
GRANT SELECT ON coordinate_esiti TO automazioni;

-- Blocchi in ordine stabile: snapshot e patch della coppia appartengono alla
-- stessa transazione. Nessun UPDATE amministrativo delle entità.
DO $prepare$
DECLARE f record; c trasi.casa%ROWTYPE; l trasi.luogo%ROWTYPE;
BEGIN
  FOR f IN SELECT * FROM coordinate_input ORDER BY slug LOOP
    SELECT * INTO STRICT c FROM trasi.casa WHERE slug = f.slug FOR UPDATE;
    SELECT * INTO STRICT l FROM trasi.luogo
      WHERE casa_id = c.id AND tipo = 'casa_quartiere' AND chiuso_il IS NULL
      FOR UPDATE;
    INSERT INTO coordinate_target VALUES (
      f.slug, c.id, l.id, l.fonte_id,
      jsonb_build_object('lat', f.lat, 'lon', f.lon, 'indirizzo', f.indirizzo,
                         'fonte_url', f.fonte_url, 'maps_url', f.maps_url),
      trasi.snapshot_entita('casa', c.id), trasi.snapshot_entita('luogo', l.id));
  END LOOP;
END
$prepare$;

-- Solo segnalazione: questi luoghi NON sono corretti automaticamente.
SELECT 'luogo dipendente da verificare' AS avviso, t.slug, l.id, l.nome, l.tipo,
       public.ST_Y(l.geom::public.geometry) AS lat,
       public.ST_X(l.geom::public.geometry) AS lon
FROM coordinate_target t
JOIN trasi.casa c ON c.id = t.casa_id
JOIN trasi.luogo l ON l.casa_id = t.casa_id
  OR public.ST_Equals(l.geom::public.geometry, c.geom::public.geometry)
WHERE l.id <> t.luogo_id
ORDER BY t.slug, l.id;

SET SESSION AUTHORIZATION automazioni;
WITH nuove AS (
  INSERT INTO trasi.proposta
    (origine, tipo, entita, entita_id, casa_id, fonte_id, payload, motivazione)
  SELECT 'manuale', 'modifica_coordinate_casa', 'casa', t.casa_id,
         t.casa_id, t.fonte_id, t.payload || '{"geom_qualita":"verificata"}'::jsonb,
         'Coordinate sede verificate: fonte e destinazione Maps nel payload'
  FROM coordinate_target t
  WHERE (t.casa_prima->'lat') IS DISTINCT FROM (t.payload->'lat')
     OR (t.casa_prima->'lon') IS DISTINCT FROM (t.payload->'lon')
     OR t.casa_prima->>'geom_qualita' IS DISTINCT FROM 'verificata'
  RETURNING id, entita, entita_id
)
INSERT INTO coordinate_proposte
SELECT n.id, n.entita, n.entita_id, t.casa_prima
FROM nuove n JOIN coordinate_target t ON t.casa_id = n.entita_id;
WITH nuove AS (
  INSERT INTO trasi.proposta
    (origine, tipo, entita, entita_id, casa_id, fonte_id, payload, motivazione)
  SELECT 'manuale', 'modifica_luogo', 'luogo', t.luogo_id,
         t.casa_id, t.fonte_id, t.payload,
         'Allineamento sede Casa: fonte e destinazione Maps nel payload'
  FROM coordinate_target t
  WHERE (t.luogo_prima->'lat') IS DISTINCT FROM (t.payload->'lat')
     OR (t.luogo_prima->'lon') IS DISTINCT FROM (t.payload->'lon')
     OR (t.luogo_prima->'indirizzo') IS DISTINCT FROM (t.payload->'indirizzo')
  RETURNING id, entita, entita_id
)
INSERT INTO coordinate_proposte
SELECT n.id, n.entita, n.entita_id, t.luogo_prima
FROM nuove n JOIN coordinate_target t ON t.luogo_id = n.entita_id;

SELECT p.id, p.tipo, p.entita_id, p.approvatore_ruolo, p.proposto_da,
       trasi.diff_leggibile(p.diff) AS diff, p.payload
FROM trasi.proposta p JOIN coordinate_proposte t ON t.id = p.id ORDER BY p.id;
RESET SESSION AUTHORIZATION;
\if :applica
SET SESSION AUTHORIZATION rete;
UPDATE trasi.proposta p SET stato = 'approvata',
  nota_decisione = 'Verifica umana coordinate sede e fonti; correzione puntuale'
FROM coordinate_proposte t WHERE p.id = t.id AND p.stato = 'proposta';
DO $approval$
BEGIN
  IF EXISTS (
    SELECT 1 FROM coordinate_proposte t JOIN trasi.proposta p ON p.id = t.id
    WHERE p.stato <> 'approvata' OR p.proposto_da <> 'automazioni'
       OR p.approvato_da IS DISTINCT FROM 'rete'
       OR p.approvatore_ruolo <> 'at' OR p.diff IS NULL
  ) THEN
    RAISE EXCEPTION 'Approvazione separata o diff mancanti: rollback';
  END IF;
END
$approval$;
RESET SESSION AUTHORIZATION;
SET SESSION AUTHORIZATION automazioni;
INSERT INTO coordinate_esiti
SELECT * FROM trasi.applica_proposte_approvate(
  (SELECT count(*)::integer FROM coordinate_proposte),
  ARRAY(SELECT id FROM coordinate_proposte ORDER BY id));
SELECT * FROM coordinate_esiti ORDER BY proposta_id;
DO $applied$
BEGIN
  IF (SELECT count(*) FROM coordinate_esiti) <> (SELECT count(*) FROM coordinate_proposte)
     OR EXISTS (SELECT 1 FROM coordinate_esiti WHERE esito <> 'ok') THEN
    RAISE EXCEPTION 'Applicazione incompleta: rollback dell''intera correzione';
  END IF;
  IF EXISTS (SELECT 1 FROM trasi.applica_proposte_approvate(
      100, ARRAY(SELECT id FROM coordinate_proposte ORDER BY id))) THEN
    RAISE EXCEPTION 'Applicazione non idempotente: rollback';
  END IF;
END
$applied$;
RESET SESSION AUTHORIZATION;
DO $verified$
BEGIN
  IF EXISTS (
    SELECT 1 FROM coordinate_target t
    JOIN trasi.casa c ON c.id = t.casa_id
    JOIN trasi.luogo l ON l.id = t.luogo_id
    WHERE public.ST_Y(c.geom::public.geometry) IS DISTINCT FROM (t.payload->>'lat')::float8
       OR public.ST_X(c.geom::public.geometry) IS DISTINCT FROM (t.payload->>'lon')::float8
       OR public.ST_Equals(c.geom::public.geometry, l.geom::public.geometry) IS DISTINCT FROM true
       OR c.geom_qualita <> 'verificata'
       OR l.indirizzo IS DISTINCT FROM t.payload->>'indirizzo'
  ) THEN
    RAISE EXCEPTION 'Casa/luogo non coerenti con la fonte: rollback';
  END IF;
  IF EXISTS (
    SELECT 1 FROM coordinate_proposte t
    WHERE NOT EXISTS (
      SELECT 1 FROM trasi.audit a
      WHERE a.proposta_id = t.id AND a.azione = 'applicata'
        AND a.entita = t.entita AND a.entita_id = t.entita_id
        AND a.eseguito_da = 'automazioni' AND a.prima = t.prima
        AND a.dopo = trasi.snapshot_entita(t.entita, t.entita_id)
        AND a.prima IS DISTINCT FROM a.dopo
    )
  ) THEN
    RAISE EXCEPTION 'Audit prima/dopo incompleto: rollback';
  END IF;
END
$verified$;
SELECT count(*) AS proposte_applicate FROM coordinate_esiti;
COMMIT;
\else
ROLLBACK;
\echo Anteprima annullata: leggere diff/fonti, poi usare --apply per approvare e applicare.
\endif
"""


def load_fixture(path: Path) -> list[dict]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows:
        raise ValueError("La fixture deve essere un array non vuoto")
    slugs = set()
    fields = {"slug", "lat", "lon", "indirizzo", "fonte_url", "maps_url"}
    for row in rows:
        if not isinstance(row, dict) or set(row) != fields:
            raise ValueError(f"Ogni sede richiede esattamente {sorted(fields)}")
        slug = row["slug"]
        if not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9-]+", slug) or slug in slugs:
            raise ValueError("Slug assente, non valido o duplicato")
        slugs.add(slug)
        for key, bound in (("lat", 90), ("lon", 180)):
            value = row[key]
            if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > bound:
                raise ValueError(f"{slug}: {key} non valida")
        if not isinstance(row["indirizzo"], str) or not row["indirizzo"].strip():
            raise ValueError(f"{slug}: indirizzo mancante")
        for key in ("fonte_url", "maps_url"):
            value = row[key]
            if not isinstance(value, str) or any(c.isspace() for c in value):
                raise ValueError(f"{slug}: {key} non valida")
            parsed = urlparse(value)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError(f"{slug}: {key} deve essere una URL HTTPS pubblica")
        # La vista @lat,lon è il centro della mappa, NON la destinazione.
        destinations = re.findall(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)", unquote(row["maps_url"]))
        if len(destinations) != 1 or tuple(map(float, destinations[0])) != (row["lat"], row["lon"]):
            raise ValueError(f"{slug}: coordinate diverse dalla destinazione !3d/!4d della fonte Maps")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--apply", action="store_true", help="Attesta la revisione umana dei diff e applica")
    args = parser.parse_args()
    rows = load_fixture(args.fixture)
    admin = os.environ.get("POSTGRES_USER") or _da_env_file("POSTGRES_USER") or "postgres"
    database = os.environ.get("TRASI_DB") or _da_env_file("TRASI_DB") or "trasi_db"
    command = [
        "docker", "compose", "-f", str(ROOT / "deployment/docker-compose.yml"),
        "exec", "-T", "db_trasi", "psql", "-U", admin, "-d", database,
        "-X", "-v", "ON_ERROR_STOP=1", "-v", "fixture=" + json.dumps(rows, allow_nan=False),
        "-v", "applica=" + ("true" if args.apply else "false"), "-f", "-",
    ]
    return subprocess.run(command, input=SQL, text=True, cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"correggi_coordinate_case: {exc}", file=sys.stderr)
        raise SystemExit(1)
