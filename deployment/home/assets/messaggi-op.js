/* messaggi-op.js — il comportamento della sezione «Messaggi» dell'Account.
 *
 * CARICATO DA `account.html`; `account.js` chiama `window.TrasiAccount.avvii["messaggi"](vista)` dopo
 * aver inserito il frammento (contratto §5.4). Il frammento è solo markup.
 *
 * Riporta nella nuova shell le funzioni di `deployment/home/operatore.js` adattate al contratto:
 *   * il campo è `items` (`{"items": [...]}`) — non `messaggi`, non `risultati`: leggere un campo che
 *     non esiste faceva comparire «Nessun messaggio» **anche subito dopo un invio riuscito**;
 *   * il mittente e il destinatario sono già risolti in slug (`da_casa`/`a_casa`), con `'pa'` per la
 *     PA e `'broadcast'` per l'avviso a tutta la rete — leggerne altri dava «Comune → Comune» su ogni
 *     riga;
 *   * il campo del corpo è `a_casa` (lo **slug**), non `a_casa_slug`: quello sarebbe un campo in più,
 *     quindi un `422` `extra` non ammesso.
 *
 * `operatore.js` usava «Tu» come etichetta del turno: la prima persona non è ammessa nei testi, e qui
 * il mittente si nomina con il suo slug — che è già il vocabolario del resto della pagina.
 *
 * Il testo passa dal filtro anti-PII dello shim (`messaggi.py`): un telefono, un'email o un codice
 * fiscale nel messaggio danno `422`, e la pagina lo dice in parole senza mostrare il `detail` tecnico.
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

  function messaggioErrore(e) {
    if (e && e.sessioneScaduta) return "Sessione non più valida: la pagina di accesso è a un passo.";
    if (e && e.stato === 422 && e.message && e.message.indexOf("dato_personale_sospetto") >= 0) {
      return "Il testo sembra contenere un dato personale — telefono, email, codice fiscale — e non è " +
             "stato inviato. Si può riscrivere senza quel dato.";
    }
    if (e && e.stato === 503) return "Dati non disponibili: la memoria della rete non risponde in questo momento";
    return e && e.message ? e.message : "Invio non riuscito.";
  }

  /* Il nome di una controparte: lo slug così com'è, con i due valori che non sono slug tradotti in
     parole. `'pa'` e `'broadcast'` li produce l'endpoint, e sono fatti, non identificatori. */
  function nomeControparte(valore) {
    if (valore === "pa") return "PA";
    if (valore === "broadcast") return "tutta la rete";
    return valore || "—";
  }

  /* La data in forma breve: `2026-09-17T09:30:00+02:00` → `17/09/2026, 09:30`. Il fuso è quello del
     browser dell'operatore, che è quello della Casa: non serve una conversione esplicita. */
  function quando(iso) {
    if (!iso) return "data non disponibile";
    var parti = String(iso).slice(0, 16).split("T");
    if (parti.length !== 2) return String(iso);
    var data = parti[0].split("-");
    return data.length === 3 ? data[2] + "/" + data[1] + "/" + data[0] + ", " + parti[1] : String(iso);
  }

  function carica() {
    var elenco = $("acc-messaggi-elenco");
    var stato = $("acc-messaggi-stato");
    if (!elenco) return;

    elenco.textContent = "";
    mostra(stato, "Lettura in corso…");

    chiama("/op/messaggi").then(function (dati) {
      /* Il campo è `items`: vedi la nota in testa al modulo. */
      var messaggi = (dati && dati.items) || [];
      mostra(stato, "");
      if (!messaggi.length) {
        /* Vuoto dichiarato: la bacheca **è** vuota su questo database, e una lista vuota senza frase
           non distingue «nessun messaggio» da «lettura non riuscita». */
        mostra(stato, "Nessun messaggio nella bacheca della Casa.");
        return;
      }
      messaggi.forEach(function (m) { elenco.appendChild(riga(m)); });
    }).catch(function (e) {
      mostra(stato, "Messaggi non disponibili: " + messaggioErrore(e));
    });
  }

  function riga(m) {
    var voce = document.createElement("li");
    /* Il filetto distingue a colpo d'occhio i messaggi ricevuti da quelli propri, e «non letto»
       aggiunge il **grado** della parola: il colore non porta mai da solo il significato. */
    voce.className = "filetto " + (m.letto ? "filetto--spento" : "filetto--oggi");

    var intestazione = document.createElement("p");
    intestazione.className = "acc-messaggi-intestazione";
    intestazione.textContent =
      quando(m.ts) + " · da " + nomeControparte(m.da_casa) + " a " + nomeControparte(m.a_casa) +
      (m.letto ? "" : " · non letto");
    voce.appendChild(intestazione);

    var testo = document.createElement("p");
    testo.className = "acc-messaggi-testo" + (m.letto ? "" : " acc-messaggi-non-letto");
    testo.textContent = m.testo;
    voce.appendChild(testo);
    return voce;
  }

  window.TrasiAccount = window.TrasiAccount || { avvii: {} };
  window.TrasiAccount.avvii = window.TrasiAccount.avvii || {};
  window.TrasiAccount.avvii["messaggi"] = function () {
    var modulo = $("acc-messaggi-modulo");
    if (modulo) {
      modulo.addEventListener("submit", function (evento) {
        evento.preventDefault();
        mostra($("acc-messaggi-esito"), "");
        mostra($("acc-messaggi-errore"), "");

        var corpo = {
          /* `a_casa` è lo **slug**, ed è obbligatorio: il broadcast è riservato alla PA, quindi il
             modulo non offre «tutta la rete» e senza destinataria non si invia. */
          a_casa: $("acc-messaggi-destinataria").value,
          testo: $("acc-messaggi-testo").value.trim()
        };
        if (!corpo.a_casa || !corpo.testo) {
          mostra($("acc-messaggi-errore"), "Servono la Casa destinataria e il testo del messaggio.");
          return;
        }

        chiama("/op/messaggi", { method: "POST", body: corpo }).then(function () {
          mostra($("acc-messaggi-esito"), "Messaggio inviato.");
          $("acc-messaggi-testo").value = "";
          carica();
        }).catch(function (e) {
          mostra($("acc-messaggi-errore"), messaggioErrore(e));
        });
      });
    }
    carica();
  };
})();
