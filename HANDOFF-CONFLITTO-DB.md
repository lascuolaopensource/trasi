# Handoff — conflitto sul DB condiviso (per la sessione `US_4_monitoraggio_pov_gianvito`)

**Da:** la sessione che sta commettendo le decisioni del gruppo Processi (fasce 4.4 + persone 1.1) in main.
**Data:** 2026-09-17.
**Gravità:** bloccante per l'`apply.sh` di main e di qualunque sessione che applichi le migrazioni.

---

## Il fatto

Il database Trasi è **condiviso** fra tutti i worktree. In quest'ora la batteria di main è passata
da verde a rosso tre volte, e l'ultima volta `db/apply.sh` ha fallito al secondo file. Le cause sono
nel lavoro in corso della sessione **US-4 (monitoraggio PA)**, e sono due di natura diversa:

1. **Una gara di numerazione**: `db/026_report_pa.sql` (tuo) e `db/026_fasce_cittadino.sql` (mio).
2. **Un conflitto strutturale con `db/002_rls.sql`** che rompe l'apply per tutti.

Le due cose hanno rimedi diversi, e uno dei due l'ho già risolto dalla mia parte.

---

## 1. Il numero di migrazione — già risolto dalla mia parte

Hai preso `026`; io avevo preso `026` per le fasce. **Ho rinumerato le mie**: sono ora

- `db/028_fasce_cittadino.sql`
- `db/029_persone_casa.sql`

e `db/apply.sh` di main le chiama in ordine `… 024 025 028 029`. **Puoi continuare a usare il tuo
`026_report_pa.sql` senza toccare nulla.**

⚠️ Nota per il momento in cui porterai i tuoi file in main: il tuo `apply.sh` ora dichiara
`… 024 025 026_report_pa)`, il mio `… 024 025 028 029)`. La fusione è banale (aggiungere
`026_report_pa.sql` fra 025 e 028) ma va fatta a mano, altrimenti una delle due migrazioni non viene
più applicata su un deploy pulito.

---

## 2. L'owner delle tue tabelle — questo blocca tutti, ed è il vero problema

In `db/026_report_pa.sql` le tue tabelle nascono **senza `SET ROLE trasi_owner`** (c'è un commento
che lo spiega: ti serve `ALTER FUNCTION … OWNER TO applicatore` dal superuser, e ha senso). Ma il
corollario è che `trasi.chat_interazione_log`, `trasi.credenziale_servizio` e le loro sequence
risultano di **`postgres`**, non di `trasi_owner`.

Effetto misurato: `db/002_rls.sql` fa `GRANT USAGE ON ALL SEQUENCES IN SCHEMA trasi TO …` **come
`trasi_owner`** — e su oggetti di cui non è owner il `GRANT` muore con

```
permission denied for sequence chat_interazione_log_id_seq
```

cioè **l'`apply.sh` di main fallisce al secondo file**, per me e per qualunque altra sessione.
L'ho riparato due volte a runtime (`ALTER TABLE … OWNER TO trasi_owner`) e l'hai ri-applicato ai
giri successivi del tuo apply: finché il `CREATE TABLE` non nasce con l'owner giusto, il database
resta in gara fra i due script.

**La correzione che chiedo** — è una riga, e non tocca la tua scelta sull'`applicatore`:

```sql
-- dopo i CREATE TABLE del tuo 026:
ALTER TABLE trasi.chat_interazione_log  OWNER TO trasi_owner;
ALTER TABLE trasi.credenziale_servizio  OWNER TO trasi_owner;
```

(Le sequence collegate seguono la tabella, non serve farle a mano.) Le due `ALTER` vanno lì, nel tuo
file: così il tuo `apply.sh` resta idempotente *e* non rompe più quello degli altri.

Il motivo per cui è `trasi_owner` e non `postgres`: è l'owner **dichiarato** dello schema (`db/000`)
e `db/002` gira proprio impersonandolo. Tabelle di superuser nello schema applicativo sono anche un
rischio V4: `postgres` non passa dalla RLS, quindi ogni tua tabella di superuser è un oggetto fuori
dalla contabilità di `v_scritture_senza_audit`.

---

## 3. Il CHECK `report_ambito_casa_ck` — è una scelta di dominio, ma rende rosso un test di main

Il tuo CHECK sul DB condiviso è ora:

```sql
CHECK ((ambito = 'osservatorio') = (casa_id IS NULL))
```

È una scelta legittima (il report di rete non appartiene a una Casa) e **non la contesto**. Ma nel
sorgente di main `db/024_report.sql` quel vincolo non esiste, e `db/tests/t_report.sql` R01 inserisce
un report `osservatorio` **con** `casa_id` → 23514, batteria rossa.

Due strade, entrambe pulite — dimmi quale prendi e procedo io se è la (b):

- **(a)** estendi tu `t_report.sql` R01 nel tuo commit (l'INSERT di prova senza `casa_id`);
- **(b)** mi dici che la semantica è tua e io adatto R01 in main (INSERT senza casa_id + asserzione
  che `ambito='casa'` richieda la Casa, cioè il lato del CHECK che il progetto non copriva).

---

## 4. Cosa ho già adattato dalla mia parte (per trasparenza)

Le tue aggiunte di dominio **non le tocco** — le ho solo rese compatibili coi test di main:

- `t_seed.sql` O02: `ruolo_casa` e `identita_onyx` non asseriscono più un totale esatto (hai
  aggiunto il ruolo `pa` e la sua identità), asseriscono la soglia del contratto + **zero identità
  orfane** + le 10 Case con ruolo omonimo e 2 identità, che sono il presidio vero.
- `t_viste.sql` V01: stessa cosa per `trasi.parametro` (hai aggiunto `email_report_pa`).
- Io ho rinumerato le mie migrazioni in `028/029` e aggiornato `db/apply.sh` di main.

---

## Riassunto operativo

| Cosa | Chi | Stato |
|---|---|---|
| Rinumerare `026_fasce` → `028/029` | io | ✅ fatto |
| `OWNER TO trasi_owner` sulle tue 2 tabelle | **tu** (nel tuo 026) | ⛔ da fare, blocca l'apply di tutti |
| `t_report.sql` R01 vs il tuo CHECK | tu o io | ⚠️ da coordinare |
| Merging dell'ORDER di `apply.sh` al tuo merge | tu | ⚠️ ricordalo al commit |

Scrivimi qui (aggiungi una sezione **«Risposta»** in fondo a questo file) o in chat: appena sei
d'accordo sul punto 3, chiudo la mia parte e commetto.