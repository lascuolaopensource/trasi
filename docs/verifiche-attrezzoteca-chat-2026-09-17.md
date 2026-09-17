# Verifiche — Attrezzoteca via chat (scheda !NEW 5), 2026-09-17

Le prove sotto sono state eseguite sullo stack vivo. Per ogni dialogo: comando reale, output reale.
Strumenti del contratto aggiornati su Onyx (tool `trasi_shim` id 12, `PUT /api/admin/tool/custom/12`,
validatore interno Onyx `POST /api/admin/tool/custom/validate` → 200 con 16 metodi).

## Setup usato dalle prove

```
curl -X POST http://127.0.0.1:8099/login -H 'Content-Type: application/json' \
  -d '{"casa":"san-bao","password":"sanbao2026!"}'          # 200, cookie trasi_sessione
```

Le 5 operazioni del contratto rispondono via `http://shim:8000/v1/u/{email}` (verificato anche
da `onyx-api_server-1`, che è il punto da cui Onyx chiama i tool custom):

```
GET  /v1/u/op.san-bao@trasi.local/attrezzoteca?q=proiettore   → 200 {"items":[{…, casa: buscicchio, badge: kb}]}
GET  /v1/u/op.san-bao@trasi.local/uso_oggetti                 → 200 {"uso":[…],"in_ritardo":[]}
POST /v1/u/op.san-bao@trasi.local/prenota                     → 201 (conflitti nel ritorno)
POST /v1/u/op.san-bao@trasi.local/movimento                   → 201 (stato: proposto)
POST /v1/u/op.san-bao@trasi.local/movimento/{id}/conferma     → 200/409 (decide il dominio)
```

## Batteria dialoghi (assistente «Trasi Casa», via `POST /op/chat`)

| # | Dialogo (scheda servizio) | Esito reale |
|---|---|---|
| 1 | «Ho bisogno di 5 microfoni per un evento domani, dove posso trovarli?» | 200 — l'assistente dichiara che **non ci sono microfoni** in inventario e non inventa; segnala l'unico materiale audio/video censito (proiettore). |
| 2 | «Dove posso trovare un proiettore? Quanti ce ne sono e in che condizioni?» | 200 — «un solo proiettore … Casa Buscicchio, quantità 1, disponibile, condizione: integro» + badge `[KB · Rete-kb-3 · kb]`. |
| 3 | «Prenota il proiettore (oggetto 336) per la Casa bozzano dal 2026-09-30 al 2026-10-02» | 200 — «Prenotazione registrata, in attesa di conferma … la conferma spetta a Bozzano. Conflitti: nessuno» (201 su `prenota_oggetto`). |
| 4 | Conferma dalla Casa ricevente (bozzano), via `POST /v1/u/op.bozzano@trasi.local/movimento/467/conferma` | 200 `{movimento_id:467, stato:confermato}`; DB: `stato=confermato`. |
| 5 | Rientro con danno + sospensione, dalla cedente buscicchio, `POST /op/movimento/467/rientro {"condizione":"danneggiato","sospendi":true}` | 200 `{sospeso:true, condizione:danneggiato}`; l'oggetto esce da `v_inventario` (`GET /op/attrezzoteca?q=proiettore` → `{"items":[]}`). |
| 6 | Conflitto di periodo: seconda prenotazione sullo stesso oggetto in date sovrapposte | 201 con `conflitti:[{movimento_id:468, da_casa:bozzano, a_casa:molo12, dal:2026-10-01, al:2026-10-03, stato:proposto}]` — il conflitto è **dichiarato**, non rifiutato (V6). |

Note dei dialoghi: un tentativo con slug inesistente (`trasi-casa`) è stato respinto dal dominio
con 409 parlante («Casa destinataria inesistente»); l'assistente ha corretto usando uno slug reale.
Il rientro con `sospendi=true` è eseguibile anche via chat con `azione=rientro` + `condizione_rientro`
(contratto), mentre la sospensione esplicita resta all'endpoint `/op` perché è una modifica di
inventario → proposta `modifica_oggetto` (attivo=false).

## Riparazione durante la verifica

**Immagine `trasi-shim:local` con codice stantio.** Sintomo: l'assistente riceveva «Not Found»
dallo strumento anche dopo l'aggiornamento del contratto. Causa misurata: `docker compose build`
riusava layer in cache con file vecchi (dentro l'immagine: `scritture.py` 45.068 B senza
`prenota_oggetto`, `openapi.yaml` 52.888 B a 10 operazioni; sul disco: 34.631 B / 70.119 B a 16).
Riparato con `docker build --no-cache` dal context `US5_attrezzoteca_marco/shim` e
`up -d --force-recreate shim`; verifica: `grep -c prenota_oggetto /app/app/scritture.py` nel
container → 5, e chiamata da `onyx-api_server-1` → 200.

## Stato del database dopo la batteria

| Oggetto | Stato |
|---|---|
| 336 proiettore (buscicchio → bozzano, movimento 467) | `rientrato`, `condizione_rientro=danneggiato`, oggetto `attivo=false` |
| 337 proiettore (san-bao) | ripristinato via proposta 5497 (`modifica_oggetto`, attivo=true, integro) |
| Prenotazioni 468/469 su 337 (1–3/10) | `proposto`, con conflitto dichiarato nel ritorno |

Le righe di prova dei test SQL (026) sono state rimosse al termine della sessione di test.