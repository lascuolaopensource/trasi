/* Trasi — area operatore. Vanilla JS, nessuna dipendenza.
 *
 * Quattro compiti, tutti dietro la sessione dello shim:
 *   1. accesso (`POST /api/shim/login` → cookie HttpOnly, la pagina non tocca la sessione);
 *   2. «Chiedi»: il collegamento all'assistente in **Onyx**, l'unica superficie di conversazione
 *      (`GET /api/shim/op/config` → `{onyx_url}`, aperto in una nuova scheda: qui non c'è una chat);
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
    /* Con la sessione c'è il guscio: sidebar, Casa in sessione, «Esci». */
    var guscio = document.querySelector(".guscio");
    if (guscio) guscio.classList.remove("guscio--pubblico");
    collegaOnyx();
    caricaInventario("");
    caricaMovimenti();
    caricaMessaggi();
  }

  function fuoriSessione() {
    casaCorrente = null;
    $("operatore-casa").textContent = "accesso richiesto";
    vistaBanco.hidden = true;
    vistaAccesso.hidden = false;
    /* Senza sessione resta la sola scheda di accesso (vista Login del prototipo):
       la sidebar è del lavoro in sessione, non dell'ingresso. */
    var guscio = document.querySelector(".guscio");
    if (guscio) guscio.classList.add("guscio--pubblico");
    scollegaOnyx();
    sincronizzaTimerAttrezzoteca();
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
    chiama("/logout", { method: "POST" }).catch(function () { /* la sessione lato server scade da sé */ });
    mostra($("esito-uscita"), "Sessione chiusa.");
    fuoriSessione();
  });

  /* ------------------------------------------------------------ linguette */

  var linguette = document.querySelectorAll(".linguetta[data-pannello]");
  for (var i = 0; i < linguette.length; i++) {
    linguette[i].addEventListener("click", function () {
      for (var j = 0; j < linguette.length; j++) linguette[j].setAttribute("aria-pressed", "false");
      this.setAttribute("aria-pressed", "true");
      var pannelli = document.querySelectorAll(".pannello");
      for (var k = 0; k < pannelli.length; k++) pannelli[k].hidden = true;
      var pannello = this.getAttribute("data-pannello");
      $("pannello-" + pannello).hidden = false;
      /* L'inventario si rilegge **all'apertura** della linguetta, non solo al login: un oggetto
         aggiunto dalla chat Onyx (`salva_dato` con `entita=oggetto`) deve comparire qui senza
         ricaricare la pagina. Stessa query dello shim per entrambe le porte (`inventario()`). */
      if (pannello === "attrezzoteca" && casaCorrente) {
        aggiornaAttrezzoteca();
      }
      sincronizzaTimerAttrezzoteca();
    });
  }

  function scaduta(errore) {
    if (errore && errore.sessioneScaduta) { fuoriSessione(); return true; }
    return false;
  }

  /* ------------------------------------------------------- «Chiedi» → Onyx
   *
   * L'indirizzo lo dice lo shim, perché la pagina è statica e non lo conosce; si
   * chiede **dopo** l'accesso, perché `/op/config` vuole la sessione. Nuova scheda,
   * dichiarata a chi non la vede (`aria-label`); `rel="noopener"` perché Onyx è
   * un'altra applicazione. Se lo shim non lo dà, il collegamento resta senza `href`
   * e lo dice: mai un `href` vuoto, mai una chat dentro Trasi. */

  var TESTO_ONYX_NON_DISPONIBILE = "Onyx non disponibile";
  var linguettaOnyx = $("linguetta-onyx");

  function collegaOnyx() {
    if (!linguettaOnyx) return;
    chiama("/op/config").then(function (config) {
      if (!config || typeof config.onyx_url !== "string" || !config.onyx_url) throw new Error("onyx_url assente");
      window.TrasiShell.aggiornaChiedi(config.onyx_url);
      linguettaOnyx.textContent = "Chiedi";
      linguettaOnyx.removeAttribute("aria-disabled");
      linguettaOnyx.setAttribute("href", config.onyx_url);
      linguettaOnyx.setAttribute("target", "_blank");
      linguettaOnyx.setAttribute("rel", "noopener");
      linguettaOnyx.setAttribute("aria-label", "Chiedi (si apre in una nuova scheda)");
    }).catch(function (errore) {
      if (scaduta(errore)) return;
      scollegaOnyx();
      window.TrasiShell.aggiornaChiedi(false);
      linguettaOnyx.textContent = TESTO_ONYX_NON_DISPONIBILE;
    });
  }

  function scollegaOnyx() {
    window.TrasiShell.aggiornaChiedi(null);
    if (!linguettaOnyx) return;
    linguettaOnyx.removeAttribute("href");
    linguettaOnyx.removeAttribute("target");
    linguettaOnyx.removeAttribute("rel");
    linguettaOnyx.removeAttribute("aria-label");
    linguettaOnyx.setAttribute("aria-disabled", "true");
    linguettaOnyx.textContent = "Chiedi";
  }

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

  /* --------------------------------------------------------- attrezzoteca
   *
   * Quattro regole, tutte lette dai dati e non ricalcolate qui:
   *   1. su un oggetto **proprio** disponibile si propone un prestito (`a_casa`); su un oggetto di
   *      un'**altra** Casa disponibile si chiede in prestito (`da_casa`, db/033); a disponibilità 0 nessun
   *      pulsante, solo la parola;
   *   2. nei movimenti in attesa i pulsanti («Conferma ricezione»/«Conferma prestito» e «Rifiuta»)
   *      compaiono **solo** a chi deve decidere: `decide_casa_slug` viene dalla vista del database, la UI
   *      lo confronta con la Casa della sessione e basta; chi ha proposto legge «In attesa della
   *      decisione di …»;
   *   3. i moduli sono **in linea** nella tabella (niente `window.prompt`): un `<form>` nella riga sotto,
   *      raggiungibile da tastiera, con Annulla che riporta il focus al pulsante;
   *   4. l'inventario si rilegge da solo mentre la linguetta è visibile — ogni 30 s e al ritorno del
   *      focus/visibilità (l'operatore torna dalla scheda di Onyx) — e a mano con «Aggiorna». La riga
   *      «Inventario aggiornato alle HH:MM» dice quando.
   */

  var ATTREZZOTECA_INTERVALLO_MS = 30000;
  var timerAttrezzoteca = null;
  var moduloAperto = null;   /* la <tr> del modulo in linea aperto, una sola per volta */

  function nodo(tag, classe, testo) {
    var el = document.createElement(tag);
    if (classe) el.className = classe;
    if (testo !== undefined && testo !== null) el.textContent = String(testo);
    return el;
  }

  function oggiIso() { return new Date().toISOString().slice(0, 10); }

  /* Gli slug validi sono quelli che la pagina già elenca nel selettore di accesso: leggerli da lì
     evita una seconda copia della lista delle Case nel JS. */
  function caseDellaRete() {
    var opzioni = document.querySelectorAll("#accesso-casa option");
    var lista = [];
    for (var i = 0; i < opzioni.length; i++) lista.push({ slug: opzioni[i].value, nome: opzioni[i].textContent });
    return lista;
  }

  function chiudiModulo() {
    if (!moduloAperto) return;
    var apertoDa = moduloAperto.apertoDa;
    if (moduloAperto.parentNode) moduloAperto.parentNode.removeChild(moduloAperto);
    moduloAperto = null;
    if (apertoDa && apertoDa.isConnected) apertoDa.focus();
  }

  /* Un modulo in linea sotto la riga dell'oggetto. `campi` è una lista di {nome, etichetta, tipo, opzioni?}. */
  function apriModulo(rigaOggetto, bottone, titolo, campi, invia) {
    chiudiModulo();
    var riga = nodo("tr", "op-riga-modulo");
    riga.apertoDa = bottone;
    var cella = nodo("td");
    cella.colSpan = 6;
    var modulo = nodo("form", "op-modulo");
    modulo.setAttribute("aria-label", titolo);
    modulo.appendChild(nodo("p", "op-modulo-titolo", titolo));
    var primo = null;
    campi.forEach(function (campo, i) {
      var id = "op-campo-" + rigaOggetto.dataset.oggetto + "-" + campo.nome;
      var blocco = nodo("div", "op-campo");
      var etichetta = nodo("label", "etichetta", campo.etichetta);
      etichetta.setAttribute("for", id);
      var controllo;
      if (campo.tipo === "select") {
        controllo = nodo("select");
        campo.opzioni.forEach(function (op) {
          var o = nodo("option", null, op.nome);
          o.value = op.slug;
          controllo.appendChild(o);
        });
      } else {
        controllo = nodo("input");
        controllo.type = campo.tipo;
        if (campo.valore) controllo.value = campo.valore;
        if (campo.min) controllo.min = campo.min;
      }
      controllo.id = id;
      controllo.name = campo.nome;
      controllo.required = true;
      blocco.appendChild(etichetta);
      blocco.appendChild(controllo);
      modulo.appendChild(blocco);
      if (i === 0) primo = controllo;
    });
    var azioni = nodo("div", "op-modulo-azioni");
    var conferma = nodo("button", "riquadro-azione", "Invia");
    conferma.type = "submit";
    var annulla = nodo("button", "riquadro-azione riquadro-azione--quieto", "Annulla");
    annulla.type = "button";
    annulla.addEventListener("click", chiudiModulo);
    azioni.appendChild(conferma);
    azioni.appendChild(annulla);
    modulo.appendChild(azioni);
    modulo.addEventListener("keydown", function (ev) { if (ev.key === "Escape") { ev.preventDefault(); chiudiModulo(); } });
    modulo.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var valori = {};
      campi.forEach(function (campo) { valori[campo.nome] = modulo.elements[campo.nome].value; });
      invia(valori);
    });
    cella.appendChild(modulo);
    riga.appendChild(cella);
    rigaOggetto.parentNode.insertBefore(riga, rigaOggetto.nextSibling);
    moduloAperto = riga;
    if (primo) primo.focus();
  }

  function esitoAttrezzoteca(ok, testo) {
    if (ok) { mostra($("attrezzoteca-ok"), testo); nascondi($("attrezzoteca-errore")); }
    else { mostra($("attrezzoteca-errore"), testo); nascondi($("attrezzoteca-ok")); }
  }

  function registraMovimento(corpo, testoOk) {
    chiama("/op/movimento", { method: "POST", body: corpo }).then(function () {
      chiudiModulo();
      esitoAttrezzoteca(true, testoOk);
      aggiornaAttrezzoteca();
    }).catch(function (errore) {
      if (scaduta(errore)) return;
      esitoAttrezzoteca(false, "Movimento non registrato: " + errore.message);
    });
  }

  function rigaInventario(o) {
    var riga = nodo("tr");
    riga.dataset.oggetto = o.oggetto_id;
    var disponibili = o.quantita_disponibile != null ? o.quantita_disponibile : o.quantita;
    riga.appendChild(nodo("td", null, o.nome + (o.descrizione ? " — " + o.descrizione : "")));
    riga.appendChild(nodo("td", null, o.casa_slug || o.casa));
    riga.appendChild(nodo("td", null, disponibili == null ? "—" : disponibili));
    riga.appendChild(nodo("td", null, o.condizione == null ? "—" : o.condizione));
    riga.appendChild(nodo("td", null, o.fonte || ""));
    var azione = nodo("td");
    var slugOggetto = String(o.casa_slug || o.casa || "");
    var propria = slugOggetto === String(casaCorrente || "");
    if (!(disponibili > 0)) {
      azione.textContent = "Non disponibile ora";
    } else if (propria) {
      /* Prestito: la cedente sceglie la destinataria fra le altre Case (`movimento_case_distinte`:
         la propria non è nell'elenco, così il vincolo non può scattare) e la data di rientro. */
      var presta = nodo("button", "riquadro-azione", "Proponi prestito a\u2026");
      presta.type = "button";
      presta.setAttribute("aria-label", "Proponi in prestito " + o.nome + " a un'altra Casa");
      presta.addEventListener("click", function () {
        var altre = caseDellaRete().filter(function (c) { return c.slug !== casaCorrente; });
        apriModulo(riga, presta, "Prestito di «" + o.nome + "»", [
          { nome: "a_casa", etichetta: "A quale Casa", tipo: "select", opzioni: altre },
          { nome: "al", etichetta: "Fino a quando (rientro previsto)", tipo: "date", valore: oggiIso(), min: oggiIso() }
        ], function (v) {
          registraMovimento({ oggetto_id: o.oggetto_id, a_casa: v.a_casa, dal: oggiIso(), al: v.al },
            "Prestito proposto a " + v.a_casa + ": conta dalla sua conferma.");
        });
      });
      azione.appendChild(presta);
    } else {
      /* Richiesta: la ricevente chiede l'oggetto di un'altra Casa (db/033); decide la cedente. */
      var chiedi = nodo("button", "riquadro-azione", "Chiedi in prestito");
      chiedi.type = "button";
      chiedi.setAttribute("aria-label", "Chiedi in prestito " + o.nome + " a " + slugOggetto);
      chiedi.addEventListener("click", function () {
        apriModulo(riga, chiedi, "Richiesta di «" + o.nome + "» a " + slugOggetto, [
          { nome: "al", etichetta: "Fino a quando (rientro previsto)", tipo: "date", valore: oggiIso(), min: oggiIso() }
        ], function (v) {
          registraMovimento({ oggetto_id: o.oggetto_id, da_casa: slugOggetto, dal: oggiIso(), al: v.al },
            "Richiesta inviata a " + slugOggetto + ": conta dalla sua conferma.");
        });
      });
      azione.appendChild(chiedi);
    }
    riga.appendChild(azione);
    return riga;
  }

  function oraLocale() {
    var d = new Date();
    return (d.getHours() < 10 ? "0" : "") + d.getHours() + ":" + (d.getMinutes() < 10 ? "0" : "") + d.getMinutes();
  }

  function caricaInventario(q) {
    var corpo = $("corpo-inventario");
    var stato = $("attrezzoteca-aggiornato");
    chiudiModulo();
    corpo.innerHTML = "";
    var attesa = nodo("tr");
    attesa.appendChild(nodo("td", null, "Caricamento\u2026")).colSpan = 6;
    corpo.appendChild(attesa);
    return chiama("/op/attrezzoteca" + (q ? "?q=" + encodeURIComponent(q) : "")).then(function (dati) {
      corpo.innerHTML = "";
      var elenco = dati && dati.items;
      if (!Array.isArray(elenco) || elenco.length === 0) {
        var r = nodo("tr");
        r.appendChild(nodo("td", null, "Nessun oggetto trovato.")).colSpan = 6;
        corpo.appendChild(r);
      } else {
        for (var i = 0; i < elenco.length; i++) corpo.appendChild(rigaInventario(elenco[i]));
      }
      if (stato) stato.textContent = "Inventario aggiornato alle " + oraLocale();
    }).catch(function (errore) {
      if (scaduta(errore)) return;
      corpo.innerHTML = "";
      var r = nodo("tr");
      r.appendChild(nodo("td", null, "Inventario non disponibile: " + errore.message)).colSpan = 6;
      corpo.appendChild(r);
    });
  }

  function decidiMovimento(m, azione, testoOk) {
    chiama("/op/movimento/" + encodeURIComponent(m.id) + "/conferma", { method: "POST", body: { azione: azione } })
      .then(function (dati) {
        esitoAttrezzoteca(true, testoOk + " (stato: " + (dati && dati.stato) + ").");
        aggiornaAttrezzoteca();
      }).catch(function (errore) {
        if (scaduta(errore)) return;
        esitoAttrezzoteca(false, "Decisione non registrata: " + errore.message);
      });
  }

  function caricaMovimenti() {
    var lista = $("movimenti-da-confermare");
    lista.innerHTML = "";
    return chiama("/op/movimenti_da_confermare").then(function (dati) {
      var elenco = dati && dati.movimenti;
      if (!Array.isArray(elenco) || elenco.length === 0) {
        lista.appendChild(nodo("li", null, "Nessun movimento in attesa di conferma."));
        return;
      }
      elenco.forEach(function (m) {
        var voce = nodo("li", "op-movimento");
        var testo = (m.oggetto || ("oggetto #" + m.oggetto_id)) + " \u00b7 da " + m.da_casa_slug + " a " + m.a_casa_slug +
          " \u00b7 " + m.dal + " \u2192 " + (m.al || "\u2014") + " \u00b7 proposto da " + m.proposto_da_casa_slug;
        voce.appendChild(nodo("span", "op-movimento-testo", testo));
        if (m.decide_casa_slug === casaCorrente) {
          /* Decide questa Casa: come ricevente conferma la ricezione (prestito proposto dalla cedente), come
             cedente conferma il prestito (richiesta della ricevente). In entrambi i casi può rifiutare. */
          var etichetta = m.ruolo_mio === "ricevente" ? "Conferma ricezione" : "Conferma prestito";
          var conferma = nodo("button", "riquadro-azione", etichetta);
          conferma.type = "button";
          conferma.setAttribute("aria-label", etichetta + ": " + (m.oggetto || "oggetto") + " da " + m.da_casa_slug + " a " + m.a_casa_slug);
          conferma.addEventListener("click", function () {
            decidiMovimento(m, "conferma", m.ruolo_mio === "ricevente"
              ? "Ricezione confermata: l\u2019oggetto ora risulta alla tua Casa"
              : "Prestito confermato: l\u2019oggetto ora risulta a " + m.a_casa_slug);
          });
          var rifiuta = nodo("button", "riquadro-azione riquadro-azione--quieto", "Rifiuta");
          rifiuta.type = "button";
          rifiuta.setAttribute("aria-label", "Rifiuta: " + (m.oggetto || "oggetto") + " da " + m.da_casa_slug + " a " + m.a_casa_slug);
          rifiuta.addEventListener("click", function () {
            decidiMovimento(m, "rifiuta", "Movimento rifiutato: l\u2019oggetto resta dov\u2019\u00e8");
          });
          voce.appendChild(conferma);
          voce.appendChild(rifiuta);
        } else {
          voce.appendChild(nodo("span", "op-movimento-attesa", "In attesa della decisione di " + m.decide_casa_slug));
        }
        lista.appendChild(voce);
      });
    }).catch(function (errore) {
      if (scaduta(errore)) return;
      lista.innerHTML = "";
      lista.appendChild(nodo("li", null, "Movimenti non disponibili: " + errore.message));
    });
  }

  /* Rilettura completa con il termine di ricerca corrente. */
  function aggiornaAttrezzoteca() {
    if (!casaCorrente) return;
    caricaInventario($("cerca-oggetto").value.trim());
    caricaMovimenti();
  }

  function attrezzotecaVisibile() {
    return Boolean(casaCorrente) && !$("pannello-attrezzoteca").hidden && document.visibilityState === "visible";
  }

  /* Il timer vive solo con la linguetta visibile e la finestra in primo piano: una pagina in secondo piano
     non interroga lo shim ogni 30 s per nessuno. */
  function sincronizzaTimerAttrezzoteca() {
    if (attrezzotecaVisibile()) {
      if (!timerAttrezzoteca) timerAttrezzoteca = window.setInterval(aggiornaAttrezzoteca, ATTREZZOTECA_INTERVALLO_MS);
    } else if (timerAttrezzoteca) {
      window.clearInterval(timerAttrezzoteca);
      timerAttrezzoteca = null;
    }
  }

  /* Al ritorno (dalla scheda di Onyx, da un'altra finestra) si rilegge subito: è il momento in cui
     l'operatore si aspetta di vedere ciò che ha appena scritto in chat. */
  function alRitorno() {
    if (attrezzotecaVisibile()) aggiornaAttrezzoteca();
    sincronizzaTimerAttrezzoteca();
  }
  document.addEventListener("visibilitychange", alRitorno);
  window.addEventListener("focus", alRitorno);

  $("modulo-cerca-oggetto").addEventListener("submit", function (evento) {
    evento.preventDefault();
    caricaInventario($("cerca-oggetto").value.trim());
  });
  $("aggiorna-attrezzoteca").addEventListener("click", aggiornaAttrezzoteca);

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
