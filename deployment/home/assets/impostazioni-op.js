/* impostazioni-op.js — il comportamento della sezione «Impostazioni» dell'Account.
 *
 * CARICATO DA `account.html`; `account.js` chiama `window.TrasiAccount.avvii["impostazioni"](vista)`
 * dopo aver inserito il frammento (contratto §5.4). Il frammento è solo markup.
 *
 * ---------------------------------------------------------------------------
 * La Casa è in sola lettura, e «sola lettura» è una decisione, non una mancanza
 * ---------------------------------------------------------------------------
 * Questo modulo **non offre** un pulsante «salva»: i dati della Casa si leggono e basta. Le
 * modifiche — orari, servizi — passano da `POST /op/proponi_modifica` (sezione «Registra»), che
 * **non scrive il dominio**: crea una proposta, e l'applicazione avviene dopo l'approvazione (V4).
 * Un modulo di modifica qui sarebbe la prima deroga a quella regola, e la più difficile da
 * giustificare: la testata della Casa è il dato che la rete dichiara, non quello che una Casa cambia
 * da sola.
 *
 * Il badge di provenienza (V3) si rende **verbatim** da `GET /op/casa` (di BotAccountCoda), che lo
 * compone già: non si ricompone l'etichetta da `fonte`, `data_aggiornamento` e `fiducia`, perché
 * ricomporla è il modo in cui due schermate finiscono per mostrare due etichette diverse della stessa
 * informazione.
 *
 * ---------------------------------------------------------------------------
 * «Esci» e la stampa
 * ---------------------------------------------------------------------------
 * «Esci» è lo stesso `POST /logout` di `shell.js`, e la voce è ripetuta qui perché è la sezione in cui
 * la si cerca: la mitigazione dichiarata per la sessione lunga (§5.5) è che l'uscita sia **sempre
 * visibile**, e averla in due posti non è ridondanza ma la forma di quella garanzia.
 *
 * I due documenti — biglietto A6 e scheda evento — sono pagine HTML del server (`GET /op/biglietto`,
 * `GET /op/scheda_evento`) e si aprono in una scheda nuova, senza passare dalla `fetch`: un documento
 * stampabile deve restare un documento, con il suo indirizzo. Un `404` diventa la dichiarazione che
 * quell'elemento non è in memoria.
 */
(function () {
  "use strict";

  function $(id) {
    return document.getElementById(id);
  }

  function mostra(nodo, testo) {
    if (!nodo) return;
    nodo.textContent = testo || "";
    nodo.hidden = !testo;
  }

  function chiama(percorso, opzioni) {
    var init = opzioni || {};
    init.headers = Object.assign({ Accept: "application/json" }, init.headers || {});
    init.credentials = "same-origin";
    return fetch("/api/shim" + percorso, init).then(function (risposta) {
      if (risposta.status === 401) {
        var scaduta = new Error("sessione assente o scaduta");
        scaduta.sessioneScaduta = true;
        throw scaduta;
      }
      if (!risposta.ok) throw new Error("errore " + risposta.status);
      return risposta.json();
    });
  }

  /* ---------------------------------------------------------------- la Casa */

  function voce(etichetta, valore) {
    var p = document.createElement("p");
    p.className = "acc-impostazioni-voce";

    var nome = document.createElement("span");
    nome.className = "acc-impostazioni-etichetta";
    nome.textContent = etichetta;
    p.appendChild(nome);

    var testo = document.createElement("span");
    testo.textContent = valore == null || valore === "" ? "—" : String(valore);
    p.appendChild(testo);
    return p;
  }

  function conEtichetta(etichetta, contenuto) {
    var p = voce(etichetta, "");
    var ultimo = p.lastChild;
    ultimo.textContent = "";
    ultimo.appendChild(contenuto);
    return p;
  }

  function caricaCasa() {
    var stato = $("acc-impostazioni-stato");
    var contenitore = $("acc-impostazioni-dati");
    if (!contenitore) return;

    chiama("/op/casa").then(function (casa) {
      mostra(stato, "");
      contenitore.textContent = "";

      contenitore.appendChild(voce("Casa", casa.nome));

      /* «dati provvisori» sta **nel testo** della zona, mai in un colore: è la regola del progetto
         per ogni stato, e la testata della sidebar fa lo stesso. */
      var zona = casa.zona || "—";
      if (casa.orari_provvisori) zona += " · orari in via di definizione";
      if (casa.da_validare) zona += " · dati da validare";
      contenitore.appendChild(voce("Zona", zona));

      contenitore.appendChild(voce("Ente gestore", casa.ente_gestore));
      contenitore.appendChild(voce("Orari settimanali", casa.orari_testo));

      var eccezioni = casa.orari_eccezioni || [];
      if (eccezioni.length) {
        contenitore.appendChild(voce("Orari straordinari", eccezioni.join(" · ")));
      }

      contenitore.appendChild(voce("Raggio di riferimento", casa.raggio_m_eff + " metri"));
      contenitore.appendChild(voce("Qualità della posizione", casa.geom_qualita));

      /* La provenienza (V3): il badge arriva composto da `/op/casa` e si rende **alla lettera**.
         L'etichetta tratteggiata è per le fonti esterne, e la classe la sceglie il tipo della fonte
         — non il badge, che è una stringa. */
      var provenienza = casa.provenienza || {};
      var etichetta = document.createElement("span");
      etichetta.className = "etichetta etichetta--kb";
      etichetta.textContent = provenienza.badge || "fonte non dichiarata";
      contenitore.appendChild(conEtichetta("Provenienza", etichetta));
    }).catch(function () {
      /* La testata della Casa non è disponibile: si dichiara, non si inventa. Il testo è quello del
         design system, alla lettera. */
      mostra(stato, "Dati non disponibili: la memoria della rete non risponde in questo momento");
    });
  }

  /* ---------------------------------------------------------------- stampa */

  /* Un documento stampabile si apre con `window.open`, non con `fetch`: il browser deve scaricarlo
     come pagina, con il suo Content-Type, e la finestra nuova è quella in cui si preme «stampa».
     `noopener` toglie alla pagina aperta ogni riferimento a questa (`window.opener`). */
  function apriDocumento(percorso) {
    var finestra = window.open("/api/shim" + percorso, "_blank", "noopener");
    if (!finestra) {
      /* Un blocco dei popup è una condizione reale dello sportello: si dichiara invece di non fare
         nulla, altrimenti il pulsante sembra rotto. */
      mostra(
        $("acc-impostazioni-errore-stampa"),
        "Il browser non ha aperto la scheda nuova. Il documento si può aprire dal collegamento diretto."
      );
      return;
    }
    mostra($("acc-impostazioni-errore-stampa"), "");
  }

  function collegaStampa() {
    var moduloBiglietto = $("acc-impostazioni-modulo-biglietto");
    if (moduloBiglietto) {
      moduloBiglietto.addEventListener("submit", function (evento) {
        evento.preventDefault();
        var id = $("acc-impostazioni-luogo-id").value;
        if (id) apriDocumento("/op/biglietto?luogo_id=" + encodeURIComponent(id));
      });
    }

    var moduloScheda = $("acc-impostazioni-modulo-scheda");
    if (moduloScheda) {
      moduloScheda.addEventListener("submit", function (evento) {
        evento.preventDefault();
        var id = $("acc-impostazioni-evento-id").value;
        if (id) apriDocumento("/op/scheda_evento?evento_id=" + encodeURIComponent(id));
      });
    }
  }

  /* ---------------------------------------------------------------- uscita */

  /* L'uscita si chiede a `Trasi.api("/logout")` e **non** a una `fetch` scritta qui: la chiamata al
     logout è una sola in tutto il sito (`shell.js`, `governaEsci`) e duplicarla significherebbe due
     copie che divergono alla prima modifica — l'aggiunta di un header, un cambio di percorso, la
     gestione del 401 già scaduto. La voce è ripetuta in questa sezione perché è dove la si cerca
     (la mitigazione dichiarata per la sessione lunga è che l'uscita sia sempre visibile), ma la
     chiamata è una. */
  function collegaUscita() {
    var bottone = $("acc-impostazioni-esci");
    if (!bottone) return;
    bottone.addEventListener("click", function () {
      mostra($("acc-impostazioni-esito-uscita"), "Uscita in corso…");
      var uscita = window.Trasi && window.Trasi.api
        ? window.Trasi.api("/logout", { method: "POST" })
        : Promise.resolve();
      uscita.catch(function () { /* la sessione lato server scade da sé */ })
        .then(function () { location.href = "index.html"; });
    });
  }

  window.TrasiAccount = window.TrasiAccount || { avvii: {} };
  window.TrasiAccount.avvii = window.TrasiAccount.avvii || {};
  window.TrasiAccount.avvii["impostazioni"] = function () {
    caricaCasa();
    collegaStampa();
    collegaUscita();
  };
})();
