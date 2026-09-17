/* registra.js — il comportamento della sezione «Registra» dell'Account.
 *
 * CARICATO DA `account.html`; `account.js` chiama `window.TrasiAccount.avvii["registra"](vista)` dopo
 * aver inserito il frammento (contratto §5.4). Il frammento è solo markup.
 *
 * ---------------------------------------------------------------------------
 * Tre moduli, tre regimi di scrittura — e il modulo non ne confonde due
 * ---------------------------------------------------------------------------
 * 1. **richiesta allo sportello** → `POST /op/registra_richiesta`. Registro del colloquio: quattro
 *    chiavi, nessuna della persona. Il corpo si compone **solo** dai campi valorizzati, così
 *    `destinazione_nota` non parte come stringa vuota quando l'esito è «risolta» (il database la
 *    rifiuterebbe con `richiesta_destinazione_obbl`… che è il verso opposto: la pretende quando
 *    l'esito è `inviata_altrove`, e una nota vuota su un esito diverso non serve a nulla).
 * 2. **evento della Casa** → `POST /op/eventi`. Scrittura diretta (opzione A). Le date arrivano da
 *    `<input type="datetime-local">` nella forma `AAAA-MM-GGTHH:MM` — che è già ISO e viene mandata
 *    così com'è: costruire un `Date` e riserializzarlo sarebbe un passaggio in più e una conversione
 *    di fuso in più, e il fuso di un evento è quello della Casa, non quello del browser.
 * 3. **servizi e orari** → `POST /op/proponi_modifica`. **Nulla del dominio viene scritto**: si crea
 *    una proposta. Il pulsante lo dice («invia come proposta») e il messaggio di esito pure.
 *
 * ---------------------------------------------------------------------------
 * Perché gli orari si compongono qui e non si mandano come testo
 * ---------------------------------------------------------------------------
 * `payload.orari` è un oggetto `{lun: [...], …, dom: [...]}`, con le fasce come coppie `HH:MM`
 * (`db/022`, `OrariProposti` di `scritture.py`). Il campo della pagina è una textarea di righe
 * «lun 09:00-13:00», perché scrivere un orario è più naturale in quella forma che in un modulo a
 * coppie di campi. La conversione avviene **qui**, e una riga che non si sa leggere **ferma l'invio**
 * con un messaggio che dice quale riga: mandare un orario interpretato male significherebbe una
 * proposta scritta in memoria con degli orari sbagliati, e nessuno se ne accorgerebbe fino
 * all'apertura della Casa.
 *
 * Nessun uso di `localStorage` (V5): lo stato vive in memoria di modulo e muore con la pagina.
 */
(function () {
  "use strict";

  var GIORNI = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"];

  /* ---------------------------------------------------------------- utilità */

  function $(id) {
    return document.getElementById(id);
  }

  function mostra(nodo, testo) {
    if (!nodo) return;
    nodo.textContent = testo;
    nodo.hidden = !testo;
  }

  /* Una risposta non OK diventa un errore leggibile; mai il corpo grezzo (V6: niente gergo). */
  function chiama(percorso, opzioni) {
    var init = opzioni || {};
    init.headers = Object.assign({ Accept: "application/json" }, init.headers || {});
    if (init.body && typeof init.body === "object") {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(init.body);
    }
    init.credentials = "same-origin";
    return fetch("/api/shim" + percorso, init).then(function (risposta) {
      if (risposta.status === 401) {
        var scaduta = new Error("sessione assente o scaduta");
        scaduta.sessioneScaduta = true;
        throw scaduta;
      }
      if (!risposta.ok) {
        return risposta.json().catch(function () { return null; }).then(function (corpo) {
          var dettaglio = corpo && (corpo.dettaglio || corpo.detail);
          var e = new Error(typeof dettaglio === "string" ? dettaglio : "errore " + risposta.status);
          e.stato = risposta.status;
          throw e;
        });
      }
      var tipo = risposta.headers.get("content-type") || "";
      return tipo.indexOf("json") >= 0 ? risposta.json() : risposta.text();
    });
  }

  /* La frase per l'operatore la compone `shell.js` (`Trasi.spiega`): un solo traduttore per tutto il
     sito, mai il `detail` tecnico dello shim (`dato_personale_sospetto — campi: …`, «errore 422»).
     Il ripiego locale vale solo se la shell non c'è. */
  function messaggioErrore(e) {
    if (window.Trasi && window.Trasi.spiega) return window.Trasi.spiega(e);
    return e && e.sessioneScaduta ? "Sessione non più valida: la pagina di accesso è a un passo." : "Invio non riuscito.";
  }

  /* ---------------------------------------------------------------- richiesta */

  function collegaRichiesta() {
    var esito = $("acc-registra-esito");
    var rigaDestinazione = $("acc-registra-riga-destinazione");

    if (esito) {
      esito.addEventListener("change", function () {
        if (rigaDestinazione) rigaDestinazione.hidden = esito.value !== "inviata_altrove";
      });
    }

    var modulo = $("acc-registra-modulo-richiesta");
    if (!modulo) return;

    modulo.addEventListener("submit", function (evento) {
      evento.preventDefault();
      mostra($("acc-registra-esito-richiesta"), "");

      var corpo = {
        categoria: $("acc-registra-categoria").value,
        esito: esito.value
      };
      /* La destinazione si allega **solo** quando l'esito la richiede e c'è: il database pretende
         una delle due quando l'esito è `inviata_altrove` (`richiesta_destinazione_obbl`), e una nota
         vuota su un altro esito sarebbe un campo in più senza contenuto. */
      if (corpo.esito === "inviata_altrove") {
        var nota = ($("acc-registra-destinazione-nota").value || "").trim();
        if (nota) corpo.destinazione_nota = nota;
      }

      chiama("/op/registra_richiesta", { method: "POST", body: corpo }).then(function () {
        mostra($("acc-registra-esito-richiesta"), "Richiesta registrata nel registro della Casa.");
        if (rigaDestinazione) rigaDestinazione.hidden = true;
        $("acc-registra-destinazione-nota").value = "";
      }).catch(function (e) {
        mostra($("acc-registra-esito-richiesta"), messaggioErrore(e));
      });
    });
  }

  /* ---------------------------------------------------------------- evento */

  function collegaEvento() {
    var modulo = $("acc-registra-modulo-evento");
    if (!modulo) return;

    modulo.addEventListener("submit", function (evento) {
      evento.preventDefault();
      mostra($("acc-registra-esito-evento"), "");

      /* Le date del campo `datetime-local` sono già ISO locali (`2026-09-20T18:00`): si mandano
         così. Il valore del campo non ha secondi, e lo shim lo accetta — è un `datetime` valido. */
      var corpo = {
        titolo: $("acc-registra-evento-titolo").value.trim(),
        inizio: $("acc-registra-evento-inizio").value
      };
      var fine = $("acc-registra-evento-fine").value;
      var luogo = $("acc-registra-evento-luogo").value.trim();
      var descrizione = $("acc-registra-evento-descrizione").value.trim();
      var ricorrenzaEl = $("acc-registra-evento-ricorrenza");
      var ricorrenza = ricorrenzaEl ? ricorrenzaEl.value : "";
      if (fine) corpo.fine = fine;
      if (luogo) corpo.luogo_testo = luogo;
      if (descrizione) corpo.descrizione = descrizione;
      /* Vuoto = evento singolo: il campo non si manda, lo shim lo legge come `null`. */
      if (ricorrenza) corpo.ricorrenza = ricorrenza;

      /* L'esito in parole: il numero interno dell'evento non dice niente a chi sta allo sportello;
         la ripetizione sì — è ciò che l'operatore ha appena dichiarato e vuole vedersi confermare. */
      var RIPETIZIONE = {
        settimanale: "ogni settimana", bisettimanale: "ogni due settimane",
        mensile: "ogni mese", annuale: "ogni anno"
      };
      chiama("/op/eventi", { method: "POST", body: corpo }).then(function () {
        mostra(
          $("acc-registra-esito-evento"),
          "Evento aggiunto al calendario della Casa" +
            (ricorrenza && RIPETIZIONE[ricorrenza] ? ", si ripete " + RIPETIZIONE[ricorrenza] : "") + "."
        );
        modulo.reset();
      }).catch(function (e) {
        mostra($("acc-registra-esito-evento"), messaggioErrore(e));
      });
    });
  }

  /* ---------------------------------------------------------------- proposta */

  /* «lun 09:00-13:00 15:00-18:00» → `{lun: ["09:00","13:00","15:00","18:00"]}`.
     Restituisce `null` se una riga non si sa leggere, e il chiamante **non invia**: un orario
     interpretato male diventerebbe una proposta scritta in memoria con gli orari sbagliati. */
  function leggiOrari(testo) {
    var orari = {};
    var righe = String(testo || "").split("\n");
    for (var i = 0; i < righe.length; i++) {
      var riga = righe[i].trim();
      if (!riga) continue;

      var parti = riga.split(/\s+/);
      var giorno = parti.shift().toLowerCase().replace(/:$/, "");
      if (GIORNI.indexOf(giorno) < 0) return { errore: "giorno non riconosciuto: «" + riga + "»" };
      if (parti.length === 1 && parti[0].toLowerCase() === "chiuso") {
        orari[giorno] = [];
        continue;
      }

      var fasce = [];
      for (var j = 0; j < parti.length; j++) {
        var pezzi = parti[j].split("-");
        if (pezzi.length !== 2 || !/^\d{1,2}:\d{2}$/.test(pezzi[0]) || !/^\d{1,2}:\d{2}$/.test(pezzi[1])) {
          return { errore: "fascia non riconosciuta: «" + parti[j] + "» — la forma è 09:00-13:00" };
        }
        /* `HH:MM` con due cifre: `orari_testo` del database le mostra così, e una «9:00» renderebbe
           la lettura della memoria diversa a seconda di chi ha scritto la proposta. */
        fasce.push(completa(pezzi[0]), completa(pezzi[1]));
      }
      if (!fasce.length) return { errore: "nessuna fascia nella riga «" + riga + "»" };
      orari[giorno] = fasce;
    }
    return Object.keys(orari).length ? { orari: orari } : { errore: "nessun orario scritto" };
  }

  function completa(ora) {
    var pezzi = ora.split(":");
    return (pezzi[0].length === 1 ? "0" + pezzi[0] : pezzi[0]) + ":" + pezzi[1];
  }

  /* Il tipo di proposta determina la forma del payload: la scelta si fa **qui** e non nell'HTML,
     perché `payload` non è un modulo con tutti i campi possibili — è la descrizione di ciò che si
     propone di cambiare, e ogni tipo ha il suo elenco chiuso (le whitelist di `db/006_fn_proposte.sql`).
     Mandare i campi di tutti i tipi insieme produrrebbe un `422` di payload fuori vocabolario.

     `richiede` elenca i campi **obbligatori** perché l'applicazione della proposta non fallisca dopo
     l'approvazione: `nuova_scheda` senza `titolo` e `nuovo_luogo` senza nome e tipo sono respinti da
     `payload_richiede` **al momento dell'applicazione**, cioè la notte dopo, in un altro processo, con
     la proposta già approvata e mai applicata. È il modo peggiore in cui V4 può rompersi: il consenso
     umano raccolto e inutilizzabile. La pagina chiede quei campi prima di inviare, così il controllo
     arriva dove l'operatore può ancora correggerlo. */
  var PROPOSTE = {
    modifica_orari_casa: { entita: "casa", entita_id: false, titolo: false, orari: true, descrizione: false },
    modifica_scheda: { entita: "scheda_servizio", entita_id: true, titolo: false, orari: true, descrizione: true },
    nuova_scheda: { entita: "scheda_servizio", entita_id: false, titolo: true, orari: true, descrizione: true },
    modifica_luogo: { entita: "luogo", entita_id: true, titolo: false, orari: true, descrizione: true },
    chiudi_luogo: { entita: "luogo", entita_id: true, titolo: false, orari: false, descrizione: true }
  };

  function collegaProposta() {
    var scelta = $("acc-registra-proposta-cosa");
    var rigaEntita = $("acc-registra-riga-entita");
    var rigaTitolo = $("acc-registra-riga-titolo");
    var rigaOrari = $("acc-registra-riga-orari");
    var rigaDescrizione = $("acc-registra-riga-descrizione");
    var campoOrari = $("acc-registra-proposta-orari");

    /* L'identificativo dell'elemento serve solo quando la modifica riguarda un elemento che già
       esiste; il titolo solo quando se ne crea uno. Nascondere i campi che non servono evita che
       vengano compilati «per sicurezza» con un valore inventato, che finirebbe in memoria. */
    if (scelta) {
      var aggiorna = function () {
        var voce = PROPOSTE[scelta.value] || {};
        if (rigaEntita) rigaEntita.hidden = !voce.entita_id;
        if (rigaTitolo) rigaTitolo.hidden = !voce.titolo;
        if (rigaOrari) rigaOrari.hidden = !voce.orari;
        if (rigaDescrizione) rigaDescrizione.hidden = !voce.descrizione;
      };
      scelta.addEventListener("change", aggiorna);
      aggiorna();
    }

    var modulo = $("acc-registra-modulo-proposta");
    if (!modulo) return;

    modulo.addEventListener("submit", function (evento) {
      evento.preventDefault();
      mostra($("acc-registra-esito-proposta"), "");

      var tipo = scelta.value;
      var voce = PROPOSTE[tipo] || {};
      var payload = {};

      if (voce.titolo) {
        var titolo = $("acc-registra-proposta-titolo").value.trim();
        if (!titolo) {
          mostra($("acc-registra-esito-proposta"), "Un servizio nuovo ha bisogno di un titolo: senza, la proposta non si può applicare.");
          return;
        }
        payload.titolo = titolo;
      }

      if (voce.orari && campoOrari && campoOrari.value.trim()) {
        var letto = leggiOrari(campoOrari.value);
        if (letto.errore) {
          mostra($("acc-registra-esito-proposta"), "Orari non inviati — " + letto.errore + ".");
          return;
        }
        payload.orari = letto.orari;
      }

      if (voce.descrizione) {
        var descrizione = $("acc-registra-proposta-descrizione").value.trim();
        if (descrizione) payload.descrizione = descrizione;
      }

      if (voce.entita_id) {
        var entitaId = $("acc-registra-proposta-entita-id").value;
        if (!entitaId) {
          mostra(
            $("acc-registra-esito-proposta"),
            "Per questa proposta serve l'identificativo dell'elemento che si vuole cambiare."
          );
          return;
        }
      }

      /* `payload` non può essere vuoto: una proposta senza valori proposti non descrive un
         cambiamento, e l'applicazione sarebbe un `UPDATE` che non tocca nulla. `chiudi_luogo` fa
         eccezione ed è ammessa vuota — la chiusura è il cambiamento, e `chiuso_il` lo mette
         l'applicazione con la data del giorno. */
      if (!Object.keys(payload).length && tipo !== "chiudi_luogo") {
        mostra(
          $("acc-registra-esito-proposta"),
          "La proposta non contiene nulla da cambiare: mancano gli orari, il titolo o la descrizione."
        );
        return;
      }

      var corpo = {
        tipo: tipo,
        entita: voce.entita,
        payload: payload,
        motivazione: $("acc-registra-proposta-motivazione").value.trim()
      };
      if (voce.entita_id) corpo.entita_id = parseInt($("acc-registra-proposta-entita-id").value, 10);

      chiama("/op/proponi_modifica", { method: "POST", body: corpo }).then(function (dati) {
        var chi = dati && dati.approvatore_ruolo === "at" ? "AT" : (dati && dati.approvatore_ruolo) || "chi compete";
        mostra(
          $("acc-registra-esito-proposta"),
          "Proposta inviata (numero " + (dati && dati.proposta_id ? dati.proposta_id : "—") + "). " +
            "La decisione è di " + chi + "; la memoria della rete non è cambiata: si applica dopo l'approvazione."
        );
        caricaProposte();
      }).catch(function (e) {
        mostra($("acc-registra-esito-proposta"), messaggioErrore(e));
      });
    });
  }

  /* ---------------------------------------------------------------- proposte */

  /* Lo stato delle proprie proposte: `GET /op/proposte` è di BotAccountCoda. Il campo `decidibile`
     distingue due fatti che non si possono confondere — la proposta che questa Casa decide e quella
     che la riguarda ma la cui decisione è di altri (gate G-05): la lista li nomina entrambi, perché
     omettere i secondi farebbe sembrare vuota una coda che ha dentro una decisione in attesa. */
  function caricaProposte() {
    var stato = $("acc-registra-stato-proposte");
    var elenco = $("acc-registra-elenco-proposte");
    if (!elenco) return;

    elenco.textContent = "";
    mostra(stato, "Lettura in corso…");

    chiama("/op/proposte").then(function (dati) {
      var proposte = (dati && dati.proposte) || [];
      mostra(stato, "");
      if (!proposte.length) {
        /* Il testo è quello del design system, alla lettera, composto col nome della Casa. */
        mostra(stato, "Nessuna proposta in attesa a " + (window.Trasi && window.Trasi.nomeCasa ? window.Trasi.nomeCasa() : "questa Casa") + ".");
        return;
      }
      proposte.forEach(function (p) {
        var voce = document.createElement("li");
        voce.className = "filetto " + (p.decidibile ? "filetto--coda" : "filetto--attenzione");

        var titolo = document.createElement("p");
        titolo.textContent = (p.diff_leggibile || p.tipo || "proposta") +
          (p.eta_giorni != null ? " · in attesa da " + p.eta_giorni + (p.eta_giorni === 1 ? " giorno" : " giorni") : "");
        voce.appendChild(titolo);

        var chi = document.createElement("p");
        chi.className = "acc-registra-nota";
        chi.textContent = p.decidibile
          ? "La decisione è di questa Casa: si decide nella sezione Proposte."
          : "La decisione è di " + (p.chi_decide === "at" ? "AT" : (p.chi_decide || "chi compete")) + ": la proposta è in coda da chi decide.";
        voce.appendChild(chi);

        elenco.appendChild(voce);
      });
    }).catch(function (e) {
      /* Se la lettura fallisce non si dice «nessuna proposta»: non sapendo quante ne aspettano,
         affermare che non ce ne sono sarebbe un'informazione falsa. */
      mostra(stato, messaggioErrore(e));
    });
  }

  /* ---------------------------------------------------------------- API */

  window.TrasiAccount = window.TrasiAccount || { avvii: {} };
  window.TrasiAccount.avvii = window.TrasiAccount.avvii || {};
  window.TrasiAccount.avvii["registra"] = function () {
    collegaRichiesta();
    collegaEvento();
    collegaProposta();
    caricaProposte();
  };
})();
