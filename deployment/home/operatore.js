/* Trasi — area operatore. Vanilla JS, nessuna dipendenza.
 *
 * Quattro compiti, tutti dietro la sessione dello shim:
 *   1. accesso (`POST /api/shim/login` → cookie HttpOnly, la pagina non tocca la sessione);
 *   2. chat con l'assistente **dentro Trasi** (`POST /api/shim/op/chat`, nessun salto di dominio);
 *   3. registrazione della richiesta del colloquio (V5: niente dati della persona);
 *   4. attrezzoteca e messaggi interni (V6: la conferma decide, la piattaforma registra).
 *
 * Perché tutte le chiamate passano da `/api/shim/…`: è lo stesso percorso della
 * riga «Oggi» della Home — Caddy aggiunge lato server ciò che serve, il browser
 * non vede mai segreti. La stampa della scheda evento apre `/api/shim/op/scheda_evento`
 * in una scheda nuova: il documento stampabile resta una pagina indipendente.
 */
(function () {
  "use strict";

  var BASE = "/api/shim";
  var COOKIE_SESSIONE = "trasi_sessione";

  function $(id) { return document.getElementById(id); }

  function mostra(el, testo) {
    el.textContent = testo;
    el.hidden = false;
  }
  function nascondi(el) { el.hidden = true; }

  /* Una risposta non OK diventa un errore leggibile; mai il corpo grezzo. */
  function chiama(percorso, opzioni) {
    var init = opzioni || {};
    init.headers = Object.assign({ Accept: "application/json" }, init.headers || {});
    if (init.body && typeof init.body === "object") {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(init.body);
    }
    init.credentials = "same-origin";
    return fetch(BASE + percorso, init).then(function (risposta) {
      if (risposta.status === 401) {
        var e = new Error("sessione assente o scaduta");
        e.sessioneScaduta = true;
        throw e;
      }
      if (!risposta.ok) {
        return risposta.json().catch(function () { return null; }).then(function (corpo) {
          var dettaglio = corpo && (corpo.dettaglio || corpo.detail);
          throw new Error(typeof dettaglio === "string" ? dettaglio : "errore " + risposta.status);
        });
      }
      var tipo = risposta.headers.get("content-type") || "";
      return tipo.indexOf("json") >= 0 ? risposta.json() : risposta.text();
    });
  }

  /* ------------------------------------------------------------- sessione */

  var vistaAccesso = $("accesso");
  var vistaBanco = $("banco");
  var casaCorrente = null;

  function inSessione(casa) {
    casaCorrente = casa;
    $("operatore-casa").textContent = casa;
    nascondi(vistaAccesso);
    vistaBanco.hidden = false;
    caricaInventario("");
    caricaMovimenti();
    caricaMessaggi();
  }

  function fuoriSessione() {
    casaCorrente = null;
    $("operatore-casa").textContent = "accesso richiesto";
    vistaBanco.hidden = true;
    vistaAccesso.hidden = false;
  }

  $("modulo-accesso").addEventListener("submit", function (evento) {
    evento.preventDefault();
    nascondi($("accesso-errore"));
    chiama("/login", {
      method: "POST",
      body: { casa: $("accesso-casa").value, password: $("accesso-password").value }
    }).then(function (dati) {
      $("accesso-password").value = "";
      inSessione(dati && dati.casa ? dati.casa : $("accesso-casa").value);
    }).catch(function (errore) {
      mostra($("accesso-errore"), errore.sessioneScaduta
        ? "Accesso non riuscito: Casa o parola d’ordine non riconosciute."
        : "Accesso non riuscito: " + errore.message);
    });
  });

  $("pulsante-esci").addEventListener("click", function () {
    /* Lo stesso difetto corretto in `shell.js`: navigare o nascondere la vista prima che lo
       shim risponda cancella la richiesta in volo, e il cookie resta valido. */
    chiama("/logout", { method: "POST" })
      .catch(function () { /* la sessione lato server scade da sé */ })
      .then(function () {
        mostra($("esito-uscita"), "Sessione chiusa.");
        fuoriSessione();
      });
  });

  /* ------------------------------------------------------------ linguette */

  var linguette = document.querySelectorAll(".linguetta");
  for (var i = 0; i < linguette.length; i++) {
    linguette[i].addEventListener("click", function () {
      for (var j = 0; j < linguette.length; j++) linguette[j].setAttribute("aria-pressed", "false");
      this.setAttribute("aria-pressed", "true");
      var pannelli = document.querySelectorAll(".pannello");
      for (var k = 0; k < pannelli.length; k++) pannelli[k].hidden = true;
      $("pannello-" + this.getAttribute("data-pannello")).hidden = false;
    });
  }

  function scaduta(errore) {
    if (errore && errore.sessioneScaduta) { fuoriSessione(); return true; }
    return false;
  }

  /* ---------------------------------------------------------------- chat */

  var registro = $("chat-registro");

  function battuta(chi, testo) {
    var voce = document.createElement("li");
    voce.className = "chat-battuta chat-" + chi;
    var chiEl = document.createElement("span");
    chiEl.className = "chat-chi";
    chiEl.textContent = chi === "operatore" ? "Tu" : "Assistente";
    var testoEl = document.createElement("p");
    testoEl.className = "chat-testo";
    testoEl.textContent = testo;
    voce.appendChild(chiEl);
    voce.appendChild(testoEl);
    registro.appendChild(voce);
    voce.scrollIntoView({ block: "end" });
    return testoEl;
  }

  $("chat-modulo").addEventListener("submit", function (evento) {
    evento.preventDefault();
    var testo = $("chat-testo").value.trim();
    if (!testo || !casaCorrente) return;
    battuta("operatore", testo);
    $("chat-testo").value = "";
    var attesa = battuta("assistente", "…");
    chiama("/op/chat", { method: "POST", body: { messaggio: testo } }).then(function (dati) {
      var risposta = dati && (dati.risposta || dati.testo || dati.answer);
      attesa.textContent = typeof risposta === "string" && risposta.trim() ? risposta : JSON.stringify(dati);
    }).catch(function (errore) {
      if (scaduta(errore)) return;
      attesa.textContent = "L’assistente non risponde in questo momento (" + errore.message + ").";
    });
  });

  /* ------------------------------------------------------------ richiesta */

  $("richiesta-esito").addEventListener("change", function () {
    $("riga-destinazione").hidden = this.value !== "inviata_altrove";
  });

  $("modulo-richiesta").addEventListener("submit", function (evento) {
    evento.preventDefault();
    nascondi($("richiesta-errore"));
    nascondi($("richiesta-esito-ok"));
    var corpo = {
      categoria: $("richiesta-categoria").value,
      esito: $("richiesta-esito").value
    };
    var nota = $("richiesta-destinazione-nota").value.trim();
    if (corpo.esito === "inviata_altrove" && nota) corpo.destinazione_nota = nota;
    chiama("/op/registra_richiesta", { method: "POST", body: corpo }).then(function () {
      mostra($("richiesta-esito-ok"), "Richiesta registrata. Il conteggio entra nel report del mese.");
      $("richiesta-destinazione-nota").value = "";
    }).catch(function (errore) {
      if (scaduta(errore)) return;
      mostra($("richiesta-errore"), "Registrazione non riuscita: " + errore.message);
    });
  });

  /* --------------------------------------------------------- attrezzoteca */

  function rigaInventario(o) {
    var riga = document.createElement("tr");
    function cella(testo) {
      var td = document.createElement("td");
      td.textContent = testo == null ? "—" : String(testo);
      return td;
    }
    riga.appendChild(cella(o.nome + (o.descrizione ? " — " + o.descrizione : "")));
    riga.appendChild(cella(o.casa_slug || o.casa));
    riga.appendChild(cella(o.quantita_disponibile != null ? o.quantita_disponibile : o.quantita));
    riga.appendChild(cella(o.condizione));
    riga.appendChild(cella(o.fonte || ""));
    var azione = document.createElement("td");
    /* Il pulsante c'è **solo sulla riga dell'oggetto della propria Casa**, e non è una rifinitura.
       `mov_ins_casa` (db/014) pretende `oggetto.casa_id = casa_corrente()`: prestando un oggetto
       altrui la RLS respinge l'INSERT. Mostrando il pulsante su ogni riga, l'operatore che vuole il
       microfono di Bozzano — cioè il caso d'uso normale, «5 microfoni per domani, dove?» (US-5.1) —
       preme l'unico pulsante disponibile e riceve un rifiuto: l'inventario della rete serve proprio
       a **chiedere in prestito**, e la richiesta non ha un pulsante suo. Meglio dichiararlo qui che
       far scoprire il confine con un errore. Il confronto è con `casa` della sessione (lo stesso
       valore che `/me` restituisce e che l'intestazione mostra). */
    var propria = String(o.casa_slug || o.casa || "") === String(casaCorrente || "");
    if (propria) {
      var bottone = document.createElement("button");
      bottone.type = "button";
      bottone.className = "riquadro-azione";
      bottone.textContent = "Proponi prestito";
      bottone.addEventListener("click", function () { proponiMovimento(o); });
      azione.appendChild(bottone);
    } else {
      azione.textContent = "Di un'altra Casa: si chiede a loro";
    }
    riga.appendChild(azione);
    return riga;
  }

  function caricaInventario(q) {
    var corpo = $("corpo-inventario");
    corpo.innerHTML = "";
    var vuoto = document.createElement("tr");
    vuoto.innerHTML = "<td colspan=\"6\">Caricamento…</td>";
    corpo.appendChild(vuoto);
    chiama("/op/attrezzoteca" + (q ? "?q=" + encodeURIComponent(q) : "")).then(function (dati) {
      corpo.innerHTML = "";
      /* Il campo è `items`: è quello che `GET /op/attrezzoteca` restituisce
         (`{"items": [...]}`), e leggerne un altro significava mostrare «Nessun
         oggetto trovato» a inventario **pieno** — non un caso limite, ma il
         comportamento di ogni ricerca, perché `dati.oggetti` e `dati.risultati`
         restano `undefined` e `dati` è un oggetto, quindi `Array.isArray(dati)`
         è falso. */
      var elenco = dati && (dati.items || dati.oggetti || dati.risultati);
      if (!Array.isArray(elenco) || elenco.length === 0) {
        var r = document.createElement("tr");
        r.innerHTML = "<td colspan=\"6\">Nessun oggetto trovato.</td>";
        corpo.appendChild(r);
        return;
      }
      for (var i = 0; i < elenco.length; i++) corpo.appendChild(rigaInventario(elenco[i]));
    }).catch(function (errore) {
      if (scaduta(errore)) return;
      corpo.innerHTML = "<tr><td colspan=\"6\">Inventario non disponibile: " + errore.message + "</td></tr>";
    });
  }

  /* Gli slug validi sono quelli che la pagina già elenca nel selettore di accesso: leggerli da lì
     evita una seconda copia della lista delle Case nel JS, che sarebbe un secondo elenco da tenere
     allineato al seed. */
  function caseDellaRete() {
    var opzioni = document.querySelectorAll("#accesso-casa option");
    var slug = [];
    for (var i = 0; i < opzioni.length; i++) slug.push(opzioni[i].value);
    return slug;
  }

  function proponiMovimento(o) {
    var oggi = new Date().toISOString().slice(0, 10);
    /* La destinataria si chiede finché non è una Casa **diversa dalla propria**, e non è pignoleria:
       `movimento_case_distinte` (db/014) è un CHECK, e il default precedente era `casaCorrente` —
       cioè il valore che il vincolo rifiuta *sempre*. Chi premeva «Proponi prestito» e accettava il
       valore proposto otteneva un 422 su una data o su una Casa, a seconda di quale prompt
       correggeva: un modulo che propone come default l'unico valore non ammesso. Il confronto è con
       la Casa della sessione, la stessa che l'intestazione mostra. */
    var aCasa = null;
    while (true) {
      var risposta = window.prompt(
        "A quale Casa va «" + o.nome + "»? (slug, es. bozzano)",
        o.casa_slug && o.casa_slug !== casaCorrente ? o.casa_slug : ""
      );
      if (risposta === null) return;
      aCasa = risposta.trim();
      if (!aCasa) return;
      if (aCasa === casaCorrente) {
        mostra($("attrezzoteca-errore"), "La Casa destinataria deve essere diversa dalla tua: un prestito va a un'altra Casa.");
        nascondi($("attrezzoteca-ok"));
        continue;
      }
      if (caseDellaRete().indexOf(aCasa) < 0) {
        mostra($("attrezzoteca-errore"), "Casa «" + aCasa + "» non riconosciuta: usa lo slug di una Casa della rete (es. bozzano).");
        nascondi($("attrezzoteca-ok"));
        continue;
      }
      break;
    }
    var al = window.prompt("Fino a quando? (AAAA-MM-GG)", oggi);
    if (!al) return;
    nascondi($("attrezzoteca-errore"));
    /* I nomi dei campi sono quelli dell'endpoint, e sono **tre** correzioni in un
       punto solo — ognuna faceva fallire il pulsante:
         * `oggetto_id`: l'inventario espone `oggetto_id`, non `id`;
         * `a_casa`: l'endpoint vuole lo slug del destinatario in `a_casa`, non in
           `a_casa_slug` (che è un campo in più, quindi 422 `extra` non ammesso);
         * `dal`/`al` sono date ISO: l'endpoint le valida come `date`, quindi una
           stringa malformata è 422 — nessun `Date` va serializzato a mano qui. */
    chiama("/op/movimento", {
      method: "POST",
      body: { oggetto_id: o.oggetto_id, a_casa: aCasa, dal: oggi, al: al }
    }).then(function () {
      mostra($("attrezzoteca-ok"), "Prestito proposto. Conta dalla conferma della Casa che riceve.");
      caricaInventario("");
      caricaMovimenti();
    }).catch(function (errore) {
      if (scaduta(errore)) return;
      mostra($("attrezzoteca-errore"), "Proposta non registrata: " + errore.message);
    });
  }

  function caricaMovimenti() {
    var lista = $("movimenti-da-confermare");
    lista.innerHTML = "";
    chiama("/op/movimenti_da_confermare").then(function (dati) {
      var elenco = dati && (dati.movimenti || dati.items || dati);
      if (!Array.isArray(elenco) || elenco.length === 0) {
        lista.innerHTML = "<li>Nessun movimento in attesa di conferma.</li>";
        return;
      }
      for (var i = 0; i < elenco.length; i++) {
        (function (m) {
          var voce = document.createElement("li");
          var testo = document.createElement("span");
          testo.textContent = (m.oggetto || ("oggetto #" + m.oggetto_id)) + " da " + (m.da_casa_slug || m.da_casa_id) +
            " a " + (m.a_casa_slug || m.a_casa_id) + " (" + m.dal + " → " + m.al + ") ";
          var bottone = document.createElement("button");
          bottone.type = "button";
          bottone.className = "riquadro-azione";
          bottone.textContent = "Conferma ricezione";
          bottone.addEventListener("click", function () {
            chiama("/op/movimento/" + encodeURIComponent(m.id) + "/conferma", { method: "POST" }).then(function () {
              mostra($("attrezzoteca-ok"), "Ricezione confermata: l’oggetto ora risulta alla tua Casa.");
              caricaMovimenti();
              caricaInventario("");
            }).catch(function (errore) {
              if (scaduta(errore)) return;
              mostra($("attrezzoteca-errore"), "Conferma non riuscita: " + errore.message);
            });
          });
          voce.appendChild(testo);
          voce.appendChild(bottone);
          lista.appendChild(voce);
        })(elenco[i]);
      }
    }).catch(function (errore) {
      if (scaduta(errore)) return;
      lista.innerHTML = "<li>Movimenti non disponibili: " + errore.message + "</li>";
    });
  }

  $("modulo-cerca-oggetto").addEventListener("submit", function (evento) {
    evento.preventDefault();
    caricaInventario($("cerca-oggetto").value.trim());
  });

  /* ------------------------------------------------------------- messaggi */

  function caricaMessaggi() {
    var lista = $("elenco-messaggi");
    lista.innerHTML = "";
    chiama("/op/messaggi").then(function (dati) {
      /* Il campo è `items`, come per l'inventario: `GET /op/messaggi` restituisce
         `{"items": [...]}`. Leggere `dati.messaggi` dava `undefined`, e `dati` è un
         oggetto — quindi `Array.isArray(dati)` falso — con l'effetto che la bacheca
         mostrava «Nessun messaggio» **anche appena dopo un invio riuscito**: il
         messaggio era salvato, ma la lista non lo mostrava mai. */
      var elenco = dati && (dati.items || dati.messaggi || dati.risultati);
      if (!Array.isArray(elenco) || elenco.length === 0) {
        lista.innerHTML = "<li>Nessun messaggio.</li>";
        return;
      }
      for (var i = 0; i < elenco.length; i++) {
        var m = elenco[i];
        var voce = document.createElement("li");
        /* I campi sono `da_casa`/`a_casa`: l'endpoint li restituisce già risolti in
           slug, e usa `'pa'` per la PA e `'broadcast'` per il messaggio a tutta la
           rete (`a_casa_id IS NULL`). Leggere `da_casa_slug`/`a_casa_slug` — che non
           esistono nella risposta — faceva comparire «Comune → Comune» su **ogni**
           messaggio, qualunque fosse il mittente reale. */
        voce.textContent = "[" + (m.ts || "").slice(0, 16).replace("T", " ") + "] " +
          (m.da_casa || "Comune") + " → " + (m.a_casa || "Comune") + ": " + m.testo;
        if (!m.letto) voce.className = "messaggio-non-letto";
        lista.appendChild(voce);
      }
    }).catch(function (errore) {
      if (scaduta(errore)) return;
      lista.innerHTML = "<li>Messaggi non disponibili: " + errore.message + "</li>";
    });
  }

  $("modulo-messaggio").addEventListener("submit", function (evento) {
    evento.preventDefault();
    nascondi($("messaggio-errore"));
    nascondi($("messaggio-ok"));
    var corpo = { testo: $("messaggio-testo").value.trim() };
    var destinatario = $("messaggio-destinatario").value;
    /* `a_casa` è il nome del campo nell'endpoint (`MessaggioIn`), ed è lo **slug**
       della Casa destinataria; `a_casa_slug` sarebbe un campo in più, quindi 422
       `extra` non ammesso. Vale la stessa convenzione di `/op/movimento`. */
    if (destinatario) corpo.a_casa = destinatario;
    chiama("/op/messaggi", { method: "POST", body: corpo }).then(function () {
      mostra($("messaggio-ok"), "Messaggio inviato.");
      $("messaggio-testo").value = "";
      caricaMessaggi();
    }).catch(function (errore) {
      if (scaduta(errore)) return;
      mostra($("messaggio-errore"), "Invio non riuscito: " + errore.message);
    });
  });

  /* ---------------------------------------------------------------- avvio */

  /* Già dentro? `GET /me` è la verifica: il cookie è HttpOnly, la pagina non
     può leggerlo e non prova a indovinarlo. */
  chiama("/me").then(function (dati) {
    if (dati && dati.casa) inSessione(dati.casa);
    else fuoriSessione();
  }).catch(function () { fuoriSessione(); });
})();
