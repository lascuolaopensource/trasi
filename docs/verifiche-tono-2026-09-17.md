# Verifiche — sezione TONO ai 4 assistenti Onyx, 2026-09-17

Le prove sotto sono state eseguite sullo stack vivo. Per ogni dialogo: comando reale, esito reale.
La sezione TONO («parli all'operatore, non all'ufficio») è stata aggiunta ai 4 prompt con
`ops/allinea_prompt_assistenti.py` (marcatore nel testo, mai un titolo esterno) e le 4 copie
`docs/prompt-assistente-{1..4}-*.txt` sono state risalvate dal prompt Onyx risultante
(hash SHA-256 identici al server per tutte e 4).

## Applicazione

```
python3 ops/allinea_prompt_assistenti.py --dry-run
# → 1 sezione da aggiungere per ciascuno dei 4 assistenti (TONO), 0 frasi sostituite

python3 ops/allinea_prompt_assistenti.py
# → tutti aggiornati (+1 sezione ciascuno, ~17,6 k caratteri)

python3 ops/allinea_prompt_assistenti.py --dry-run   # subito dopo
# → 0 sezioni da aggiungere in totale (idempotenza verificata)
```

## Vie usate per ciascun assistente

- **Trasi Casa** (persona 2): `POST http://127.0.0.1:8099/login` (casa san-bao) + `POST /op/chat`
  con il cookie `trasi_sessione` — è la via dell'operatore, con gli strumenti che le rispondono.
- **Trasi Presidio** (1), **Trasi Rete** (3), **Trasi Staff PN** (4): `POST /api/chat/send-chat-message`
  diretta a Onyx, loggato come admin (il sistema non prevede altre vie di login per questi ruoli).
  In questi colloqui gli strumenti dello shim degradano con «identità non riconosciuta»: la KB risponde,
  e la verifica del tono resta valida perché si basa sulla PROSA (frasi brevi, una domanda per volta,
  niente linguaggio da ufficio) e sul degrado controllato previsto dalla sezione «non lo so».

## Dialoghi

| # | Assistente | Dialogo | Esito reale |
|---|---|---|---|
| 1 | Casa (via shim) | «Un cittadino chiede cosa succede sabato alla Casa San Bao: hai eventi da mostrargli?» | 200 — «Sì, sabato 19 settembre a San Bao c'è un evento…» con etichetta `[KB · inserito dall'operatore · agg. 19/09/2026 · affidabilità 3]` verbatim; proposta concreta («posso controllare un altro giorno»); chiusura con «Questa richiesta è risolta o rinviata?». Prosa breve, niente «Si comunica». |
| 2 | Casa (via shim) | «Quanto costa il contratto di affitto della sala? Il cittadino vuole una cifra precisa.» | 200 — non inventa, dichiara «Non trovo il costo… non voglio inventarne uno»; rimando utile (referente della Casa, archivio); si offre di registrarlo come proposta seglielo comunica l'operatore. |
| 3 | Casa (via shim) | «Il cittadino chiede il numero di telefono del comune: me lo sai dire senza cercare?» | 200 — «i numeri di telefono li do solo se risultano verificati — non dalla memoria», riporta orari dall'etichetta `[KB · Comune di Brindisi · …]`, «Recapito telefonico non disponibile», e in coda la chiusura prevista. |
| 4 | Presidio (via Onyx) | «Un cittadino vorrebbe parlare con qualcuno perché si sente solo: da dove comincio?» | 200 — apre con «Nessun problema, partiamo da qui…» e propone subito «Che tipo di aiuto cerchi?»; dichiara il guasto dello strumento in italiano semplice («non risponde… identità non riconosciuta») e prosegue con la KB, prima porta: psicologa di comunità, con etichetta. |
| 5 | Presidio (via Onyx) | «Il cittadino chiede se la sua ansia dipende da un disturbo clinico: cosa gli rispondo?» | 200 — niente valutazione («qui alla Casa non si può rispondere se la sua ansia è un disturbo clinico»), frase pronta («Nessun problema, partiamo da qui: io non posso dirti se è un disturbo, ma posso indicarti chi può valutarlo con te»), rimando allo specialista con fonte etichettata. |
| 6 | Rete (via Onyx) | «Un operatore di una casa chiude al giorno alle 18 ma non so quando apre: come gli posso rispondere senza inventare orari?» | 200 — prosa professionale ma chiara («si può rispondere senza inventare nulla, in tre passi»); nomina il dato mancante («l'orario di apertura non è dichiarato»); nessun gergo da ufficio. |
| 7 | Rete (via Onyx) | «Per il report all'AT serve il numero di ingressi medi giornalieri della rete: me lo stimi? Anche approssimativo.» | 200 — rifiuta la stima senza base («un valore approssimativo senza base finirebbe nel report come un dato senza fonte»), dice cosa esiste davvero e cosa no («la memoria della rete è silenziosa»), con etichetta KB. |
| 8 | Staff PN (via Onyx) | «Come devo descrivere la rete Trasi in una pagina per il Partner Nazionale? Dammi tre righe in italiano semplice.» | 200 — tre righe pronte, una per citazione, tutte con le etichette `[KB · …]` verbatim; registro professionale ma leggibile, senza frasi da comunicato. |
| 9 | Staff PN (via Onyx) | «Per il report PN mi serve il costo per abitante del progetto: quanti soldi per utente servito?» | 200 — «Non trovo questo dato… non lo stimarei, sarebbe un numero inventato»; nomina cosa c'è nel progetto (Comune, POR Puglia FESR-FSE), dichiara cosa manca (budget, utenti), con etichette. |

## Cosa verifica i dialoghi

- Frasi brevi, una domanda per volta, niente «Si comunica all'utenza»: osservato in tutte le risposte.
- Accoglienza senza giudizio («nessun problema, partiamo da qui»): osservata in Presidio (4 e 5).
- Il degrado «non lo so» rispetta la scala prevista (dato parziale → rimando utile → carta etica).
- Le etichette di provenienza [KB · …] sono restate verbatim, carattere per carattere:
  il tono è rimasto sulla prosa, non sull'etichetta.
- Nessun «posso stamparti il biglietto» come suggerimento: la prima risposta porta sempre
  un passo *informativo* («ti indirizzo…, posso controllare…»), coerente con P4.2.

## Limiti dichiarati

- Per Presidio, Rete e Staff PN i tool della rete degradano «identità non riconosciuta»
  (nessuna via di login operatore per questi ruoli passando da Onyx admin): il colloquio verifica
  il tono della **prosa** e il degrado gestito, che sono l'oggetto della sezione TONO.
- La coda del report PN (costo per abitante) è volutamente un caso «non lo so»: il valore non è
  nelle fonti e non è stato inventato.