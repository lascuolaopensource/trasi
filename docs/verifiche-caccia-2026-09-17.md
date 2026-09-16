# Caccia ai bug (2026-09-16/17) — 5 difetti trovati, 1 riparato, 4 dichiarati

Protocollo: `PROMPT-caccia-bug.md`, eseguito integralmente su questo host.
`HEAD` all'inizio: `587f615`. Tutti i comandi e gli output citati sono reali.

---

## Metodo

Tredici tecniche (T1–T13 del prompt), dodici identità, dieci superfici. Il valore della sessione sta
tanto nei difetti trovati quanto in **cosa ha tenuto**: le tecniche che non hanno prodotto nulla sono
elencate come tali, perché «non ho trovato niente» è un risultato solo se si dichiara *dove* si è
guardato.

Due scelte di metodo che hanno cambiato l'esito:

1. **Il contenuto, non lo status code.** `oggi?casa=bozzano` risponde 200 a chiunque — sembrava un
   leak cross-Casa. Misurando il **corpo** si è visto che `op.san-bao` riceve i dati di *san-bao*: la
   Casa viene dall'identità, non dal parametro. Lo status uguale non era la prova.
2. **Il superuser bypassa la RLS.** Un primo test di approvazione girato come `postgres` dava «UPDATE
   eseguito» su una riga che la RLS avrebbe dovuto proteggere. Il test era **metodologicamente
   invalido**: rifatto come `shim_rw` (`usesuper = f`), il verdetto è cambiato. Un test che gira come
   superuser non prova la RLS, prova il superuser.

### Tentativi falliti (il sistema ha tenuto)

| Tecnica | Cosa ho provato | Esito |
|---|---|---|
| T2 | SQL injection `'; DROP TABLE trasi.casa;--` in `q` | **200, 10 Case intatte** (query parametrizzate) |
| T2 | JSON malformato, payload non-oggetto, tipo/entità inesistenti, id non numerico, decisione invalida, campo PII extra, `fine < inizio`, titolo vuoto, motivazione 81 char | **11 casi, tutti 422 parlanti, 0 × 500** |
| T1 | Righe con dati degeneri (evento `fine<inizio`, titolo vuoto, luogo senza fonte, motivazione >80, proposte scadute ancora aperte, eventi annullati futuri, Case senza geometria) | **0 righe per ognuna**: il DB non le ammette |
| T10 | Soglia k-anonimato (4/5/6) e `v_confronto_case`, `v_report_mensile`, `v_destinazioni` | **`4 → NULL + «<5»`, `5 → 5` visibile**, nessun numero grezzo sotto soglia |
| T10 | 3 viste con `count(*)` senza `k_anon` (`v_oggi_casa`, `v_inventario`, `v_uso_oggetti`) | contano **eventi/schede/oggetti**, non persone: k-anonimato non si applica |
| T4 | Orfani KB: documenti `trasi:*` in Onyx non più in `v_kb_export` | **0 orfani** (il BUG 2 storico è riparato; 32 in KB, 36 in vista, 0 orfani) |
| T4 | Stessa riga «Oggi» da **quattro** fonti (vista, shim, Caddy, testo SQL) | **coincidono su entrambe le Case provate**, incluso il testo composto |
| T7 | `v_scritture_senza_audit` e proposte `applicata` orfane di audit | **0 e 0** — nessuna scrittura non contabilizzata |
| T5 | `db/apply.sh` due volte di fila | **12/12 ok entrambe**: idempotente |
| T9 | Shim fermato → Caddy | Home **200** (sito statico regge), catena oggi **502** (come documentato) |
| T11 | V6 sulle dashboard (`--verifica-v6`) | **0 verbi imperativi su 3 testi** |
| T3 | Auto-approvazione da 5 identità diverse | **tutte 403**: V4 regola 1 tiene |
| T12 | Contratto HEAD ↔ Onyx ↔ istanza viva | le 10 operazioni di `main` sono **tutte** in Onyx; 0 mancanti |

---

## Difetti trovati

```
BUG-01 | S2 | shim | ti@trasi.local | 500 su ogni endpoint | ... | 403 parlante | REPARATO
BUG-02 | S1 | proposta/RLS | gestore di Casa | 5 tipi su 12 non approvabili da nessuno | ... | NON REPARATO (governance)
BUG-03 | S2 | shim | ti@trasi.local | 16 ruoli su 22 senza accesso Onyx | ... | NON REPARATO (governance)
BUG-04 | S3 | contratto | istanza viva | l'istanza viva non è main, senza dichiarazione | ... | NON REPARATO (operativo)
BUG-05 | S4 | docs | B7-report | US-07 dichiarata PASS, oggi non riproducibile | ... | NON REPARATO (documentazione)
```

### BUG-01 — `ti@trasi.local` riceveva 500 su ogni endpoint (REPARATO)

**Come l'ho trovato.** T3 (confusione di identità): il giro su tutte e 22 le identità ha dato 21 × 200
e **1 × 500**.

```
### T3 — blast radius su 22 identità attive (endpoint /oggi) ###
distribuzione status: {200: 21, 500: 1}
identità che NON ottengono 200:
   500  ti@trasi.local
```

**Causa.** `ti` è un'identità **attiva** in `trasi.identita_onyx` con un utente Onyx, quindi dalla chat
la si raggiunge come ogni altro operatore. Ma `db/000_roles.sql:68` revoca `ti` da `shim_rw` (deliberato:
il TI non passa dalla chat). Lo shim esegue `SET LOCAL ROLE ti` in `shim/app/db.py`, che solleva
`InsufficientPrivilegeError`; senza traduzione l'handler generico di `errori.py` lo rende un **500
«errore interno dello shim»**.

L'effetto vero non è il 500: è che **la causa a monte diventa invisibile**. Un guasto dichiarato al
posto di un ruolo non abilitato manda chi diagnostica a cercare un bug nello shim.

**Fix** (`shim/app/db.py`, `shim/app/errori.py`): tradotta l'eccezione nel 403 del contratto, seguendo
la convenzione che il repo usa già per lo stesso caso in `scritture.py:78` e `attrezzoteca.py:104`
(«due traduttori, un criterio solo», già scritto in quel commento). **Il ruolo non viene concesso**: la
lacuna si dichiara, non si allarga.

**Verifica.**
```
ti@trasi.local             -> 403  {'detail': 'identità senza accesso operativo: ruolo non abilitato allo shim'}
op.san-bao@trasi.local     -> 200  {'casa': 'san-bao', 'eventi': 0, ...}
```
**Mutation test** (obbligatorio): rimosso il `try/except`, il nuovo test torna **rosso** con
`asyncpg.exceptions.InsufficientPrivilegeError: permission denied to set role "ti"`; ripristinato, verde.

**Test di regressione** (2, in `shim/tests/test_identita.py`): il 403 parlante, e — più importante — la
**premessa dove sta la decisione** (`REVOKE ti FROM shim_rw` in `db/000_roles.sql`). Se un giorno
qualcuno concedesse `ti` a `shim_rw`, la suite diventa rossa: l'allargamento di privilegio passa da una
revisione, non da una riga silenziosa.

**Limite dichiarato.** Il codice dello shim sta **nell'immagine** (`build: ../shim`, nessun volume), e
l'istanza viva è il build di un altro worktree. Il fix è quindi verificato **in-process con database
reale**, non sull'istanza viva: applicarlo richiede un rebuild dello stack condiviso, che è una decisione
dell'utente (BUG-04).

---

### BUG-02 — Una proposta `gestore` della propria Casa non è decidibile da nessuno (NON riparato)

**Gravità S1.** Tocca la funzione centrale del progetto: senza approvazione l'ordine del ciclo
proposta→applicazione→visibilità vale `NULL`.

**Come l'ho trovato.** T13 → T6: creata una proposta `modifica_evento` come `gestore.san-bao` via shim e
provata l'approvazione da **ogni** identità.

```
creata: 201 {"proposta_id":3912,"approvatore_ruolo":"gestore","in_chat":true}
proposto_da: casa_sanbao | approvatore: gestore casa=5
   approva gestore.san-bao@trasi.local  403 {"detail":"da approvare in coda"}
   approva op.san-bao@trasi.local       403
   approva gestore.bozzano@trasi.local  403
   approva op.bozzano@trasi.local       403
   approva rete@trasi.local             403
stato finale: proposta  approvato_da=-
```

**Causa.** Due regole del database che, combinate, non lasciano uscita:

1. `proposta_00_default_tg` forza `proposto_da := current_user` — il **ruolo DB**, non l'email.
   Operatore e gestore della stessa Casa **condividono** `casa_sanbao` (governance, `plan.md` §394).
2. La policy RESTRICTIVE `no_self_approve` (`db/005_rls_proposta.sql:249`) vieta `proposto_da =
   current_user`, e `upd_client` ammette su una proposta `gestore` solo `(approvatore_ruolo='gestore'
   AND casa_id=casa_corrente())` — cioè `casa_sanbao`, che è **la stessa identità** che ha proposto.

Nessuna riga storica ha mai avuto `proposto_da = approvato_da`: le proposte `gestore` sono state
approvate **solo** quando proposte da `rete` (4 casi). Prova strutturale:

```
 approvatore_ruolo | proposto_da  | approvato_da |   stato   | count
-------------------+--------------+--------------+-----------+-------
 gestore           | casa_sanbao  | postgres     | rifiutata |     1
 gestore           | rete         | casa_sanbao  | rifiutata |     1
 gestore           | rete         | casa_sanbao  | applicata |     2
 gestore           | rete         |              | scaduta   |     1
```

**Scope: 5 tipi di proposta su 12** finiscono nel vicolo cieco — `modifica_scheda`, `nuova_scheda`,
`modifica_evento`, `nuova_opportunita`, `modifica_orari_casa`. Gli altri 7 hanno approvatore `at` e si
decidono da `rete`.

**Perché NON l'ho riparato.** Il commit `5ac36ab` lo dichiara già come comportamento voluto: «è V4 che
funziona come previsto, e si decide da un'identità diversa — **non l'ho indebolito**». Ripararlo
significa cambiare `proposto_da` da ruolo DB a email (o ammettere l'auto-approvazione entro la stessa
Casa): entrambe **modificano la regola di governance** `plan.md` §394. Il prompt §3.1-3.2 vieta di
indebolire un invariante per far passare un test, e §0 assegna le decisioni di governance al gruppo
Processi. È una decisione, non un fix.

**Cosa servirebbe.** Una scelta fra: (a) `proposto_da` = email dell'identità, con `no_self_approve` che
confronta le email (il gestore della Casa decide la proposta dell'operatore, sé stesso no); (b) i tipi
`gestore` passano a `at` come gli altri. La (a) è più fedele a V4. **Domanda per Processi**, non per un
agente.

---

### BUG-03 — 16 ruoli su 22 senza accesso Onyx (NON riparato)

**Gravità S2.** Misurato in FASE 0 incrociando le due fonti:

```
=== identità DB SENZA utente Onyx (gap) ===
gestore.buscicchio / gestore.dream / gestore.erranti / gestore.minimus / gestore.molo12
gestore.pop / gestore.santa-spazio / gestore.tuturano (+ i rispettivi op.<slug>)
```

Sono **16 identità su 22**: `trasi.identita_onyx` ha 22 righe, gli utenti Onyx con `@trasi.local` sono
**6** (`op.san-bao`, `gestore.san-bao`, `op.bozzano`, `gestore.bozzano`, `rete`, `ti`). Le altre 8 Case
esistono nel seed con operatori e gestori, ma **nessuno di loro può entrare in chat**.

Non è un difetto del codice: è provisioning. Lo registro perché la documentazione
(`docs/B7-report.md`) riferisce verifiche fatte su «10 Case», e la differenza fra 10 Case *nel database*
e 2 Case *usabili in chat* cambia ciò che le sessioni B7 con operatori reali possono provare.

---

### BUG-04 — Lo stack vivo era il build di un altro worktree, senza dichiarazione (NON riparato)

**Gravità S3 (operativo).** Trovato eseguendo il check di coerenza che il prompt stesso prescrive:

```
trasi-shim-1             /root/orca/workspaces/onice/installazione-connettori-mancanti/deployment
istanza viva: 12 operazioni | HEAD: 10 operazioni
moduli nell'immagine ASSENTI in HEAD: ['opendata.py']
```

Il compose è `name: trasi`, **unico e condiviso da tutti i 15 worktree**. Chiunque ricostruisca
l'immagine impone il proprio branch a tutti. Al momento della misura lo shim vivo serviva
`/cerca_opendata` e `/leggi_dataset`, assenti da `main`, e un modulo `shim/app/opendata.py` che in
`HEAD` non esiste.

**Perché conta.** Una verifica che non distingue «la codebase» da «l'istanza viva» misura il codice di
qualcun altro e attribuisce i difetti alla persona sbagliata. Non l'ho «riparato» ricostruendo
l'immagine: avrebbe sovrascritto il lavoro di un peer con modifiche non committate. L'ho dichiarato e ho
verificato il contratto su `HEAD` (le 10 operazioni di `main` sono tutte in Onyx).

**Proposta operativa**, non implementata: al deploy, scrivere in un file di stato quale worktree ha
costruito l'immagine e con quale `HEAD`, così `docker inspect` smette di essere l'unica fonte.

---

### BUG-05 — `US-07` dichiarata PASS, oggi non riproducibile (NON riparato)

**Gravità S4 (documentazione), ma è la lezione della sessione.**

`docs/B7-report.md:19` dichiara: *«`op.san-bao` propone, `gestore.san-bao` approva → **`UPDATE 1`**»*.
Riprodotta esattamente:

```
1) op.san-bao propone          -> 201 id=3915
   proposto_da = casa_sanbao
2) gestore.san-bao approva     -> 403 {"detail":"da approvare in coda"}   <<< il report dice UPDATE 1
   stato: proposta
```

La riga del report descrive una prova fatta **dal ruolo `postgres`** (o prima di una modifica), non la
via dello shim. Il comportamento attuale è quello di BUG-02.

**Perché lo registro come difetto e non come nota.** Un report che dichiara PASS su una funzione
centrale **e non è riproducibile** è più dannoso di un report incompleto: orienta le sessioni
successive a fidarsi. La lezione del prompt §5.3 — «il fatto che fossero PASS non le rende vere oggi» —
si è verificata sul campo.

---

## Stato dopo le riparazioni

| Suite | Prima | Dopo | Delta |
|---|---|---|---|
| `shim` | 218 passed | **220 passed** | **+2** (i miei test), 0 rossi nuovi |
| `db/tests/run.sh` | 132 PASS / 0 FAIL | **132 PASS / 0 FAIL** | invariato |
| `flussi` (a `HEAD`) | 49 passed / 1 skipped | **49 passed / 1 skipped** | invariato |

| Superficie | Esito |
|---|---|
| S1 shim `/healthz` | 200 |
| S2 Home via Caddy | 200 |
| S2 catena `oggi` end-to-end | 200 |
| S3 Metabase | 200 |
| S4 NocoDB | 302 |
| S5 Onyx | 200 |
| S6 automazioni (cron) | healthy |
| S7 backup | 2 dump presenti |
| S8 database | 43 tabelle in `trasi` |
| T7 `v_scritture_senza_audit` | **0** |

**Giro completo su ogni identità** (22 × `/oggi`): `{200: 21, 500: 1}`. Il 500 è BUG-01, riparato nel
codice ma non ancora nell'istanza viva (BUG-04).

---

## Limiti dichiarati

Cosa **non** ho potuto verificare, e perché:

1. **La verifica visiva nel browser non è stata possibile.** Il browser headless di questa macchina non
   raggiunge le porte locali (`net::ERR_INVALID_ARGUMENT` su `127.0.0.1:8088`, `:8001`, `:3001`,
   `:8081`), e il tentativo via relay è andato in timeout. Le superfici S2/S3/S4 sono quindi verificate
   **via API e hash dei byte serviti** (la Home servita ha md5 identico al file su disco), che è una
   prova più debole di uno screenshot: non copre il rendering, il selettore Casa, gli `href` generati.
2. **US-05 (ciclo mensile) resta parziale**: SMTP non configurato, la consegna non è verificabile.
   Azione del TI, dichiarata da prima di questa sessione.
3. **Il tunnel Cloudflare** non ha un ingress per `trasi.lascuolaopensource.org`: la Home non è
   raggiungibile dall'esterno. Non l'ho toccato.
4. **I 4 flussi notturni non sono stati eseguiti via cron**: ho verificato che il crontab è installato
   (5/5 righe) e che i job partono, ma le 01:00/05:00/06:00/07:30 non sono passate durante la sessione.
   `applica.sh` è stato eseguito a mano.
5. **BUG-01 non è attivo sull'istanza viva**: il codice è riparato e testato, l'immagine no (BUG-04).
   Verificato in-process con DB reale, non sull'istanza condivisa.
6. **`flussi` nel working tree resta rosso (5 failed)** per il fixture `flussi/fixtures/fonti_http.json`
   modificato da una sessione parallela. A `HEAD` è verde (49 passed). Non l'ho toccato: è lavoro di un
   peer.

---

## Dati di test: ripristino

Tutte le prove sono state condotte su fixture rimosse subito, con lo stato di dominio verificato a fine
sessione:

- **8 proposte** di prova create e cancellate insieme al loro audit (3 `T3 auto-approvazione`,
  2 `T6 concorrenza`, 1 `T13 percorso felice`, 1 `US-07 riprova`, 1 `BUG02`); **0 audit orfani**;
- **`trasi.luogo` 16** riportato allo stato esatto (`descrizione`, e `aggiornato_ts`/`aggiornato_da`
  a `NULL` con il trigger disabilitato **dentro una transazione** — un `UPDATE` normale avrebbe lasciato
  un timbro che `v_scritture_senza_audit` contabilizza come violazione di V4, come il prompt §8 avverte);
- **`v_scritture_senza_audit` = 0** a fine sessione;
- **15 worktree** (nessuno temporaneo residuo), nessun file temporaneo.

**Non toccato, di proprietà di altri**: `flussi/fixtures/fonti_http.json` e
`flussi/evidenze/ciclo_mensile/trasi_rete_2026-09.csv` (sessione parallela), l'evento `2366` «PROVA —
evento di oggi» (creato alle 19:36 da un percorso applicativo, non da me), lo stack condiviso (nessun
rebuild), il branch `puria/*` di ogni worktree.

---

## Nota di metodo

I cinque difetti hanno una cosa in comune con i tre storici: **nessuno si vedeva dalle suite**, che
erano tutte verdi (218, 132, 49). Sono usciti da:

- **un giro esaustivo invece che a campione** (BUG-01: la 22ª identità, non la prima);
- **un confronto fra due fonti di verità** (BUG-03: il DB ha 22 identità, Onyx 6);
- **un check di coerenza che il prompt prescriveva** (BUG-04: l'istanza viva non è `main`);
- **la ri-esecuzione di una user story dichiarata PASS** (BUG-02 e BUG-05).

Nessuna di queste è una tecnica raffinata. Sono tutte variazioni di «prova dove non hai ancora
provato», che è l'unica cosa che le suite — per costruzione — non fanno.
