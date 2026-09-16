# TASK SPEC — B1 Dati: schema, RLS, parametri, seed (`trasi-dati`)

## Target

Crea lo strato dati di Trasi in `/root/orca/projects/onice/db/`, eseguibile contro il Postgres+PostGIS **già attivo**:

```
docker compose -f deployment/docker-compose.yml exec -T db_trasi psql -U postgres -d trasi_db …
```

Il container è `trasi-db_trasi-1` (healthy, PostGIS 3.4.3, `127.0.0.1:5432`). Credenziali in `deployment/.env` (mode 600) — **non stamparle**.

**File di tua proprietà** (non crearne altri con questi scopi):
`db/apply.sh` · `db/000_roles.sql` · `db/001_schema.sql` · `db/002_rls.sql` · `db/003_parametri.sql` · `db/004_views.sql` · `db/010_seed_case.sql` · `db/011_seed_fonti.sql` · `db/012_seed_luoghi.sql` · `db/tests/`

**NON toccare** (altro worker, `trasi-proposte`): `db/005_rls_proposta.sql`, `db/006_fn_proposte.sql`, `db/tests/test_zero_scritture.sql`.

## Change

Ordine di esecuzione: `000 → 001 → 002 → 003 → 004 → 010 → 011 → 012`. `apply.sh` deve essere **idempotente** (eseguito due volte → exit 0 entrambe).

### `db/000_roles.sql` — 17 ruoli
`casa_santaspazio, casa_molo12, casa_erranti, casa_buscicchio, casa_sanbao, casa_minimus, casa_pop, casa_bozzano, casa_dream, casa_tuturano, rete, ti, metabase_ro, automazioni, shim_rw, applicatore, trasi_owner`
- nessuno con `BYPASSRLS` né `SUPERUSER`
- `shim_rw`: `NOINHERIT`, `LOGIN`, **nessun privilegio proprio** su `proposta`/`richiesta`; member delle 10 Case + `rete` (**non** `ti`)
- `trasi_owner`, `applicatore`: `NOLOGIN`
- **schema dedicato** `trasi` (owner `trasi_owner`) — importante: su PG15 `CREATE TABLE` in `public` come owner non-superuser dà `permission denied for schema public`

### `db/001_schema.sql` — schema (parte A: tabelle; parte B: proposta/audit)

Tabelle in schema `trasi`: `casa, fonte, fonte_run, luogo, scheda_servizio, evento, opportunita, richiesta, parametro, ruolo_casa, identita_onyx` + `proposta, audit`.

Colonne chiave (ricostruite dall'ER §7 e §7.1 dell'architettura; il DDL v1.1 non esiste nel repo — è una `[ASSUNZIONE]` da dichiarare):

- `casa`: `slug UNIQUE`, `nome`, `zona`, `ente_gestore`, `orari jsonb`, `orari_eccezioni jsonb`, `orari_provvisori bool DEFAULT false`, `raggio_m int NULL` (NULL = usa `[P] raggio_vicinanza_m`), `geom geography(Point,4326)`, `geom_qualita CHECK IN ('verificata','stimata')`, `email_digest text NULL`, `da_validare bool DEFAULT false`
- `luogo`: `tipo` con CHECK a **vocabolario chiuso** (`bar, farmacia, caf, fermata, poste, asl, comune, inps, questura, sportello, presidio_ascolto, servizio_professionale, casa_quartiere, associazione, altro`), `geom geography`, `orari jsonb`, `chiuso_il date NULL`, `ext_ref text UNIQUE NULL` (es. `osm:node/123`), `casa_id int NULL`, `fonte_id`, `affidabilita smallint CHECK 1-3`, `data_aggiornamento date`, `indirizzo`, `note_accesso`
- `evento`: `uid_ical text NULL`, UNIQUE `(casa_id, uid_ical)`, `annullato bool DEFAULT false`, `fonte_id`
- `richiesta`: CHECK `esito IN ('risolta','inviata_altrove','non_trovata','rinviata')` e CHECK `(esito <> 'inviata_altrove' OR destinazione_id IS NOT NULL OR destinazione_nota IS NOT NULL)`. **Nessun campo per dati personali** (V5)
- `proposta` + `audit` + `approvatore_default(tipo, casa_id)` + `casa_corrente()` + trigger `proposta_00_default_tg` (calcola `approvatore_ruolo` e `scade_il`)
- indici: `richiesta(casa_id, ts)`, `proposta(stato, casa_id)`, `evento(casa_id, inizio)`, `opportunita(scadenza)`, GIST su `casa.geom` e `luogo.geom`

### `db/002_rls.sql` — RLS completa (matrice sotto)
`ENABLE` + `FORCE ROW LEVEL SECURITY` su tutte le tabelle multi-Casa. Policy con `USING` **e** `WITH CHECK`.

| Tabella | casa_* | rete | ti | automazioni | metabase_ro | shim_rw |
|---|---|---|---|---|---|---|
| `casa` | SELECT; UPDATE `(orari, orari_eccezioni, orari_provvisori, email_digest)` solo `id = casa_corrente()` | SELECT | ALL | SELECT | SELECT | SELECT |
| `scheda_servizio, evento, opportunita, richiesta` | SELECT; INSERT/UPDATE/DELETE solo `casa_id = casa_corrente()` | SELECT | ALL | SELECT; **`evento` INSERT/UPDATE solo WITH CHECK `fonte.tipo_accesso='ical'`** | SELECT (**non** `richiesta`) | — |
| `luogo` | SELECT | SELECT | ALL | SELECT | SELECT | — |
| `fonte` | SELECT | SELECT | ALL | — | SELECT | — |
| `parametro` | SELECT | SELECT | UPDATE | SELECT | SELECT | SELECT |
| `ruolo_casa`, `identita_onyx` | — | — | ALL | — | — | SELECT |

**`casa_corrente()`** = `SELECT casa_id FROM ruolo_casa WHERE ruolo = current_user`. Basata su `current_user`, **non** su GUC (`current_setting` è spoofabile e NocoDB si connette col ruolo diretto).

### `db/003_parametri.sql` — 10 parametri `[P]`
`raggio_vicinanza_m=800, gg_scadenza_proposta=30, fiducia_min_esterna=2, max_risultati_esterni=5, gg_validazione_comune=7, gg_escalation_pm=14, gg_preavviso_scadenza=15, k_anonimato=5, gg_retention_chat=30, giorno_ciclo_mensile=3`
+ funzioni `p_int/p_text/p_bool` (ritornano NULL se la chiave non esiste, **nessuna eccezione**). Solo `ti` può modificare.

### `db/004_views.sql` — viste
`v_scaduti, v_in_scadenza, v_senza_risposta, v_kb_export, v_destinazioni, v_oggi_casa, v_mappa_case, v_mappa_luoghi, v_proposte_aperte, v_report_mensile, v_confronto_case`
- **k-anonimato**: in `v_confronto_case`/`v_report_mensile` il conteggio grezzo `n` è **NULL** sotto `p_int('k_anonimato')`, con `n_label = '<5'`. Mai esporre il numero grezzo sotto soglia.
- `v_kb_export(doc_id, entita, id, titolo, testo, fonte_nome, url, data_aggiornamento, affidabilita, casa_nome)` — solo elementi validi (scaduti e chiusi esclusi)
- `v_proposte_aperte(...)` **senza** `proposto_da`/`approvato_da` (minimizzazione)

### `db/010/011/012` — seed
- **10 Case** (§2.1): slug `santa-spazio, molo12, erranti, buscicchio, san-bao, minimus, pop, bozzano, dream, tuturano`. Tuturano: `raggio_m=2000`, `orari_provvisori=true`, `da_validare=true`, `ente_gestore NULL`. Erranti: orari stagionali in `orari_eccezioni`. San Bao: eccezione weekend-per-eventi. POP: `orari_provvisori=true`.
- `ruolo_casa` (12 righe: 10 Case + `rete`, `ti`), `identita_onyx` (22 righe: `op.<slug>@trasi.local`, `gestore.<slug>@trasi.local`, `rete@trasi.local`, `ti@trasi.local`)
- **fonte** (allow-list §3): Rete-kb-3, Google Drive-3, Google Calendar-ical-2, **OpenStreetMap/Overpass `osm_overpass`-2**, Comune-3, ASL-3, INPS-3, Regione-3, Questura-3 + 10 righe ETS `attiva=false`
- **luogo ≥ 22**: 10 `casa_quartiere` (una per Casa), 3 `presidio_ascolto`, 1 `servizio_professionale` (psicologa di comunità, Buscicchio), **1 `bar` con `casa_id`=Bozzano** (entro 50 m dalla Casa), 5 istituzionali, 2 `caf` in zona La Rosa/Perrino

## Constraints

- **V4**: il dominio (`luogo, scheda_servizio, evento, opportunita, casa`) **non** è scrivibile dai ruoli applicativi. Tu **non** concedi INSERT/UPDATE su quelle tabelle a `casa_*`/`shim_rw`/`automazioni`, **tranne** l'eccezione iCal su `evento`. Il worker `trasi-proposte` completa il REVOKE/GRANT per `applicatore`: coordina via `hub` se serve, non sovrapporti.
- **V5/§12**: nessun campo per dati personali; `motivazione` ≤ 80 char (CHECK); `richiesta` senza campi liberi per il cittadino.
- **Seed = caricamento iniziale** eseguito come `trasi_owner`, non scrittura a runtime: dopo B1 ogni modifica a `luogo` passa da `proposta`.
- Non inventare tipi/colonne: se l'ER è ambiguo, **dichiara l'assunzione** nel risultato.
- Non avviare altri container (RAM: ~6.9 GB liberi, ma `nocodb`/`metabase` servono dopo).

## Ownership

`db/**` tranne `db/005_*`, `db/006_*`, `db/tests/test_zero_scritture.sql` (altro worker).

## Observable acceptance (prove reali, non dichiarazioni)

1. **V-03b**: `SELECT count(*) FROM trasi.casa` = **10**; Tuturano `(raggio_m=2000, orari_provvisori=t, da_validare=t)`.
2. `SELECT count(*) FROM trasi.luogo` ≥ **22**, di cui `tipo='bar'` con `casa_id`=Bozzano presente.
3. Ruoli: 17 ruoli creati, nessuno `BYPASSRLS`/`SUPERUSER`, `shim_rw` NOINHERIT con 11 membership.
4. **RLS (il test che conta)**: `SET ROLE casa_sanbao; UPDATE trasi.casa SET orari_provvisori=orari_provvisori WHERE slug='bozzano'` → **0 righe**; stesso su `slug='san-bao'` → **1 riga**.
5. `tests/run.sh` → exit 0 con `PASS` per ogni caso (T01…T12, V01…V08, O01…O07).
6. `apply.sh` eseguito **due volte** → exit 0 entrambe (idempotenza).
7. k-anonimato: con 4 richieste → `n IS NULL, n_label='<5'`; con 5 → `n=5`.

Riporta comandi e output reali. Se un criterio è rosso, dillo — non aggiustarlo con una scorciatoia.

## Nota su coordinate
Per `geom` delle Case usa le coordinate già verificate (Nominatim, evidenze del piano): Bozzano 40.62350/17.94270 · Tuturano 40.54525/17.94691 · La Rosa 40.60609/17.95196 · Perrino 40.63148/17.95341 · Paradiso 40.64958/17.91837 · Sant'Elia 40.61847/17.92216 · Centro/Piazza Duomo 40.64036/17.94518. Marchia `geom_qualita='stimata'` dove non hai verifica civica (obbligatorio per Tuturano). `[DA VALIDARE]`.
