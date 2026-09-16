# Confronto sistema attuale ↔ schede `!NEW` + prompt esecutivo

Data: 2026-09-16. Fonte funzionalità: Scheda Prodotti (Google Doc) → `docs/user-stories-new.md`.
Convenzione: CdQ = Casa di Quartiere.

---

## 1. Matrice di copertura

Legenda: ✅ esiste e funziona · 🟡 esiste in parte / adattabile · ❌ manca · ⚠️ esiste ma in conflitto con un vincolo

| # | Scheda !NEW | Cosa chiede | Sistema attuale | Copertura | Gap |
|---|---|---|---|---|---|
| 1 | **Eventi** (palinsesto) | Palinsesto condiviso, filtri, scheda stampabile, segnalazione incompletezza/dating | Tabella `trasi.evento` ✅ · import iCal `fonti_ical.py` ✅ · vista `v_oggi_casa` ✅ · biglietto A6 per **luoghi** ✅ · shim chat read-only ✅ | 🟡 | Manca: scheda evento stampabile (oggi solo luogo); segnalazione eventi datati (>2 mesi); validazione "campi utili mancanti" prima della pubblicazione |
| 2 | **Servizi** (orientamento) | Risposta servizio → destinatari → dove → quando → contatti → fonte; output multicanale; mappa servizi | `scheda_servizio` ✅ · `cerca_web` con allow-list ✅ · vista `v_destinazioni` ✅ · dashboard Metabase "Mappa" ✅ · biglietto A6 stampabile ✅ | 🟡 | Manca: output multicanale oltre la stampa (bozza email, documento); la risposta strutturata "cosa offre → destinatari → …" dipende dai prompt dell'assistente Onyx, non dal sistema |
| 3 | **Monitoraggio op.** | Registrazione richiesta anonima allo sportello; verifica "oggi" | Tabella `trasi.richiesta` (categoria, esito, destinazione, **zero dati personali**, V5 by design) ✅ · `v_oggi_casa` ✅ · registrazione via proposte? NO: ❌ — oggi non c'è endpoint di scrittura richiesta nel flusso operatore | 🟡 | Manca: percorso operatore per registrare la richiesta (form NocoDB? endpoint shim? via proposta?); eventuali campi età/genere **in conflitto con V5** → solo aggregati, decisione DPO |
| 4 | **Monitoraggio PA** | Report mensile aggregato per il Comune | `v_report_mensile` con k-anonimato ✅ · `flussi/ciclo_mensile.py` ✅ · dashboard "Osservatorio" ✅ · vista `v_confronto_case` ✅ | ✅/🟡 | Manca: canale di consegna del report alla PA (export PDF/dashboard pubblica?); journey PA↔AI non definita nella scheda |
| 5 | **Attrezzoteca** | Inventario oggetti condivisi, disponibilità, prenotazioni con conflitti, spostamenti con conferma, condizioni, statistiche d'uso | — | ❌ | Interamente da costruire: entità nuova (`oggetto`, `prestito`/`movimento`), non coperta dalle 5 entità di dominio esistenti. Deve passare dal flusso proposte (V4) o essere dichiarata eccezione come iCal |
| 6 | **Login** | Accesso per ruolo; credenziali per CdQ; subentri e rotazione | Ruoli DB per CdQ ✅ (`ruolo_casa`, `identita_onyx`) · ma l'autenticazione oggi è quella di Onyx sul sottodominio, con redirect dalla Home | 🟡 | Da rifare secondo decisioni accumulate: login singolo per CdQ, niente login cittadini 12 mesi, nessun redirect → chat integrata via API server-to-server; gestione subentro ente gestore (rotazione credenziali) da progettare |
| 7 | **Chat interna** | Canale CdQ ↔ CdQ ↔ PA, **senza AI** | — (Onyx è una chat **con** AI; non è questo) | ❌ | Da costruire: bacheca/messaggi nel DB Trasi con audit, oppure integrazione strumento esterno. Ai sensi di V4 non è dominio → non serve flusso proposte, ma serve policy retention (privacy) |

## 2. Conflitti da risolvere PRIMA dello sviluppo

| Conflitto | Dove | Decisione richiesta |
|---|---|---|
| Età/genere nelle richieste di monitoraggio | US-3.1 vs V5 | **DECISO (2026-09-16, default conservatore):** nessun campo età/genere su `richiesta`; se il Comune li vorrà, solo aggregati e solo dopo validazione DPO |
| Registrazione richiesta = scrittura al dominio? | US-3.1 vs V4 | **DECISO:** opzione (b) — endpoint shim `POST /registra_richiesta` con inserimento diretto + riga `audit` (`azione='registra_richiesta'`). Eccezione documentata come iCal: la registrazione avviene *durante* il colloquio, non può attendere la coda di approvazione (a differenza di `evento`, che resta su proposte) |
| Attrezzoteca = nuova entità di dominio | US-5.x vs V4 | **DECISO:** `oggetto`/`prenotazione` entrano nel perimetro proposte per nascita/modifica; il **movimento** (prestito) è evento operativo con audit diretto + conferma della CdQ ricevente come transizione di stato sull'evento stesso |
| Formato export evento | US-1.3 | **DECISO:** HTML stampabile @page A6/A5 con `window.print()`, stessa pipeline del biglietto A6. Zero dipendenze PDF |
| Meccanismo auth | US-6.x vs correzione #3 | **DECISO:** sessione propria dello shim (cookie HttpOnly, `credenziale_casa` con hash argon2/bcrypt); chat via proxy server-to-server dello shim verso Onyx con `identita_onyx`. Onyx non vede il browser. Rotazione = update hash da `ti`; subentro = stesso meccanismo (runbook) |
| ~~Gancio~~ | — | **ESCLUSO** dal perimetro (2026-09-16) |

## 3. Cosa NON toccare

- Flusso proposte → approvazione → `applica_proposte` + audit (V4).
- K-anonimato (`k_anon`) nelle viste di reporting.
- `richiesta` senza campi cittadino (V5): niente "tanto per provare" campi nome/telefono nemmeno temporanei.
- Onyx: niente modifiche al suo codice; integrazione solo via API/proxy.

---

## 4. Prompt esecutivo (da dare al/dagli agenti di sviluppo)

> **Contesto.** Progetto Trasi — piattaforma della rete delle Case di Quartiere di Brindisi. Stack: Postgres+PostGIS (`db/`), shim FastAPI (`shim/`), Home statica (`deployment/home/`), flussi notturni Python (`flussi/`), Caddy come ingresso unico (`deployment/caddy/Caddyfile`), Onyx su compose separato. Vincoli inviolabili: V3 (ogni risposta dichiara la fonte), V4 (scritture al dominio solo via proposta→approvazione→applicazione+audit; eccezione iCal), V5 (zero dati personali cittadino), V6 (i messaggi dicono chi decide), k-anonimato `<5`. Decisioni già prese: login singolo per CdQ (no cittadini per 12 mesi); nessun redirect verso il sottodominio Onyx — chat integrata via API server-to-server; elementi di test nella UI devono essere rimovibili prima del rilascio. **Gancio è escluso dal perimetro** di questo lavoro.
>
> **Obiettivo.** Portare nel sistema le 7 funzionalità `!NEW` della Scheda Prodotti (user stories e AC in `docs/user-stories-new.md`), rispettando la matrice di copertura in `docs/confronto-sistema-nuove-funzionalita.md` §1 e risolvendo prima i conflitti di §2.
>
> **Ordine di esecuzione proposto (dipendenze reali):**
>
> **Fase 0 — Decisioni (bloccanti, umane):** formato export evento; meccanismo auth; `richiesta` dentro/fuori flusso proposte; perimetro V4 per attrezzoteca; retention chat interna. Output: risposte scritte in coda a `docs/confronto-sistema-nuove-funzionalita.md` §2. Nessun codice.
>
> **Fase 1 — Eventi (US-1.x), sfrutta l'esistente:**
> 1. Endpoint shim `scheda_evento` (o estensione di `biglietto`) che produce pagina stampabile di un `evento`: titolo, data/ora, luogo, accesso, contatto pubblico, fonte+data aggiornamento, badge V3. Stessa pipeline e stessi divieti del biglietto A6 (`shim/app/testi.py`), @page A6/A5. Test pytest come `test_output.py` (parole vietate, 404, OSM esterno).
> 2. Vista `v_eventi_dati_mancanti` + alert nel flusso notturno (`flussi/alert.py`): eventi con data antecedente di 2 mesi → segnalazione, mai scrittura automatica.
>
> **Fase 2 — Registrazione richiesta (US-3.1):** secondo esito Fase 0: (a) estendere macchina proposte a `richiesta` con auto-approvazione per il ruolo CdQ + audit; oppure (b) endpoint shim `POST /richiesta` con insert diretto e audit, documentando l'eccezione. In entrambi i casi: CHECK di categoria/esito già nello schema; test `db/tests/test_zero_scritture.sql` aggiornato di conseguenza. UI: form minimale in Home (elemento candidato alla rimozione? NO — questa è funzionalità finale, resta).
>
> **Fase 3 — Auth unificata (US-6.x) + chat senza redirect (correzioni #3/#4/#5):**
> 1. Login per CdQ: tabella credenziali/cookie di sessione nello shim (o forward_auth in Caddy), ruoli come da `ruolo_casa`; rotazione e subentro: runbook in `deployment/README.md` + funzione admin di reset.
> 2. Chat UI dentro la Home che chiama lo shim; lo shim inoltra a Onyx server-to-server con l'identità della CdQ (`identita_onyx`). Caddy: nessun nuovo sottodominio. Onyx non vede il browser e viceversa.
> 3. Elementi di test nella Home dietro `?test=1` o pagina separata: stato servizi (/healthz), ultima risposta shim, verifica embed Metabase. Tutti raccolti in UN blocco/componente rimovibile con una sola cancellazione.
>
> **Fase 4 — Monitoraggio PA (US-4.x):** il 90% esiste (`v_report_mensile`, `ciclo_mensile.py`, dashboard). Aggiungere: export/scaricamento del report mensile (HTML stampabile o PDF, stessa filosofia del biglietto) e accesso PA (ruolo di sola lettura sulle viste `metabase_ro`-equivalenti). Journey PA↔AI: solo dopo input dal Comune, non inventare.
>
> **Fase 5 — Attrezzoteca (US-5.x):** nuove tabelle `oggetto` (inventario: descrizione, quantità, casa_id, stato condizioni) e `movimento`/`prenotazione` (da_casa, a_casa, periodo, stato conferma, condizione al passaggio). Tutte le scritture via flusso proposte esteso (V4) con conferma della CdQ ricevente come stato, non come scrittura extra. Viste: inventario consultabile, conflitti di prenotazione, oggetti poco/molto usati, rientri in ritardo (soglie come `trasi.parametro`). Endpoint shim read-only per la chat + UI di gestione (valutare NocoDB, già in stack). Messaggi di conflitto conformi V6.
>
> **Fase 6 — Chat interna (US-7.x):** tabella `messaggio` (mittente ruolo/CdQ, destinatario, testo, ts, letto) o integrazione esterna — secondo esito Fase 0. Nessun AI in questo canale. Retention documentata. RLS: ogni CdQ vede solo le proprie conversazioni; PA vede quelle indirizzate alla PA.
>
> **Vincoli di lavoro per gli agenti:** seguire le convenzioni esistenti (vedi `.omp/agents/trasi-*.md`: dati, proposte, shim, flussi, stack, dash); ogni fase si chiude con test eseguiti e output mostrato (pytest dello shim per F1/F2, `db/tests/*.sql` per F5/F6, script usa-e-getta per smoke UI); niente test di arredamento; niente refactor fuori scope; qualsiasi scoperta incompatibile col piano → fermarsi e segnalare, non aggirare.

---

## 5. Effort grezzo per fase (ordini di grandezza)

| Fase | Dipendenza | Nuovo codice | Rischio principale |
|---|---|---|---|
| 0 | — | nessuno | decisioni rinviate → tutto si blocca |
| 1 | nessuna | piccolo (1 endpoint + 1 vista + config fonti) | formato export non deciso |
| 2 | F0 | piccolo-medio | tocca V4: serve revisione trasi-review |
| 3 | F0 | medio (sessioni + proxy chat) | sessioni: tenere semplice, niente framework auth |
| 4 | F3 (accesso PA) | piccolo | journey PA indefinita: limitarsi a report+accesso |
| 5 | F0 | medio-grande (2-3 tabelle, flusso proposte esteso, viste) | perimetro V4; UI gestione (NocoDB vs custom) |
| 6 | F0, F3 | piccolo-medio | retention/privacy messaggi |
