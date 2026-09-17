/* Trasi — monitoraggio PA. Vanilla JS, nessuna dipendenza.
 *
 * Quattro compiti, tutti dietro la sessione dello shim (stesso cookie HttpOnly
 * dell'area operatore, emesso da `POST /api/shim/servizio/login`):
 *   1. accesso del soggetto (Pubblica Amministrazione o Rete AT);
 *   2. report mensili della rete: storico, dettaglio, export stampabile, e per
 *      la Rete AT l'approvazione delle bozze (V6: l'umano decide);
 *   3. confronto tra mesi e lacune, solo conteggi k-anonimi;
 *   4. approfondimento conversazionale **dentro Trasi** (`POST /api/shim/pa/chat`).
 *
 * Perché tutte le chiamate passano da `/api/shim/…`: è lo stesso percorso delle
 * altre pagine — Caddy aggiunge lato server ciò che serve, il browser non vede
 * mai segreti. L'export apre `/api/shim/pa/report/{id}/export` in una scheda
 * nuova: il documento stampabile resta una pagina indipendente, come la scheda
 * evento dello sportello.
 *
 * V5 ovunque: i numeri arrivano già mascherati (`n`/`n_label`, sotto soglia
 * «<5») e la pagina li mostra così come sono, senza ricalcolarli.
 */
(function () {
  "use strict";

  var BASE = "/api/shim";

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
  var ruoloCorrente = null;

  var ETICHETTE_RUOLO = { pa: "Pubblica Amministrazione", rete: "Rete AT" };

  function inSessione(ruolo) {
    ruoloCorrente = ruolo;
    $("pa-ruolo").textContent = ETICHETTE_RUOLO[ruolo] || ruolo;
    nascondi(vistaAccesso);
    vistaBanco.hidden = false;
    caricaReport();
    caricaConfronto();
    caricaLacune();
  }

  function fuoriSessione() {
    ruoloCorrente = null;
    $("pa-ruolo").textContent = "accesso richiesto";
    vistaBanco.hidden = true;
    vistaAccesso.hidden = false;
  }

  $("modulo-accesso").addEventListener("submit", function (evento) {
    evento.preventDefault();
    nascondi($("accesso-errore"));
    chiama("/servizio/login", {
      method: "POST",
      body: { ruolo: $("accesso-ruolo").value, password: $("accesso-password").value }
    }).then(function (dati) {
      $("accesso-password").value = "";
      var ruolo = dati && dati.ruolo ? dati.ruolo : $("accesso-ruolo").value;
      inSessione(ruolo);
    }).catch(function (errore) {
      mostra($("accesso-errore"), errore.sessioneScaduta
        ? "Accesso non riuscito: soggetto o parola d’ordine non riconosciuti."
        : "Accesso non riuscito: " + errore.message);
    });
  });

  $("pulsante-esci").addEventListener("click", function () {
    chiama("/logout", { method: "POST" }).catch(function () { /* la sessione lato server scade da sé */ });
    mostra($("esito-uscita"), "Sessione chiusa.");
    fuoriSessione();
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

  /* --------------------------------------------------------------- report */

  var reportAperto = null;

  var ETICHETTE_STATO = {
    bozza: "bozza (in attesa di approvazione)",
    approvato: "approvato",
    inviato_pa: "inviato alla PA"
  };

  function caricaReport() {
    var lista = $("elenco-report");
    lista.innerHTML = "<li>Caricamento…</li>";
    chiama("/pa/report").then(function (dati) {
      /* Il campo atteso è `items`, come gli altri elenchi dello shim; le
         alternative coprono il caso in cui l'endpoint restituisca l'array
         direttamente o un'altra chiave — la lista non deve mostrare «Nessun
         report» a rete con un mese di report già prodotti. */
      var elenco = dati && (dati.items || dati.report || dati.risultati);
      if (!elenco && Array.isArray(dati)) elenco = dati;
      if (!Array.isArray(elenco) || elenco.length === 0) {
        lista.innerHTML = "<li>Nessun report disponibile. Il report del mese nasce dal ciclo notturno del primo giorno del mese successivo.</li>";
        return;
      }
      lista.innerHTML = "";
      for (var i = 0; i < elenco.length; i++) {
        (function (r) {
          var voce = document.createElement("li");
          var nCommenti = r.n_commenti != null ? r.n_commenti
            : (Array.isArray(r.commenti) ? r.commenti.length : (r.commenti_count != null ? r.commenti_count : null));
          var testo = document.createElement("span");
          testo.textContent = "Mese " + r.mese +
            (r.ambito && r.ambito !== "osservatorio" ? " — " + (r.casa_slug || r.ambito) : "") +
            " — " + (ETICHETTE_STATO[r.stato] || r.stato || "bozza") +
            (nCommenti != null ? " — " + nCommenti + (nCommenti === 1 ? " commento" : " commenti") : "") + " ";
          var bottone = document.createElement("button");
          bottone.type = "button";
          bottone.className = "riquadro-azione";
          bottone.textContent = "Apri il report";
          bottone.addEventListener("click", function () { apriReport(r.id); });
          voce.appendChild(testo);
          voce.appendChild(bottone);
          lista.appendChild(voce);
        })(elenco[i]);
      }
    }).catch(function (errore) {
      if (scaduta(errore)) return;
      lista.innerHTML = "<li>Report non disponibili: " + errore.message + "</li>";
    });
  }

  /* Una voce di conteggio: mostra n_label se arriva, altrimenti n; sotto soglia
     resta comunque «<5» perché è il server che maschera, la pagina non ricalcola. */
  function etichettaConteggio(riga) {
    if (riga.n_label != null && riga.n_label !== "") return String(riga.n_label);
    if (riga.n != null) return String(riga.n);
    return "—";
  }

  /* I contenuti del report sono jsonb del ciclo mensile: la forma precisa la
     decide il flusso, qui ogni sezione tabellare (array di oggetti) diventa una
     tabella con le colonne che arrivano. Una chiave a valore scalare diventa un
     elenco definizioni: nessuna conoscenza duplicata della struttura. */
  function renderContenuti(contenuti) {
    var scatola = $("dettaglio-contenuti");
    scatola.innerHTML = "";
    if (!contenuti || typeof contenuti !== "object") {
      scatola.textContent = "Contenuti non ancora disponibili.";
      return;
    }
    var chiavi = Object.keys(contenuti);
    var qualcosa = false;
    for (var i = 0; i < chiavi.length; i++) {
      var chiave = chiavi[i];
      var valore = contenuti[chiave];
      var titolo = document.createElement("h4");
      titolo.textContent = chiave.replace(/_/g, " ");
      if (Array.isArray(valore) && valore.length > 0 && typeof valore[0] === "object" && valore[0] !== null) {
        var colonne = [];
        for (var k = 0; k < valore.length; k++) {
          var ck = Object.keys(valore[k]);
          for (var c = 0; c < ck.length; c++) if (colonne.indexOf(ck[c]) < 0) colonne.push(ck[c]);
        }
        var tabella = document.createElement("table");
        tabella.className = "tabella";
        var thead = document.createElement("thead");
        var rigaTesta = document.createElement("tr");
        for (var t = 0; t < colonne.length; t++) {
          var th = document.createElement("th");
          th.scope = "col";
          th.textContent = colonne[t].replace(/_/g, " ");
          rigaTesta.appendChild(th);
        }
        thead.appendChild(rigaTesta);
        tabella.appendChild(thead);
        var tbody = document.createElement("tbody");
        for (var r = 0; r < valore.length; r++) {
          var riga = document.createElement("tr");
          for (var d = 0; d < colonne.length; d++) {
            var td = document.createElement("td");
            var v = valore[r][colonne[d]];
            td.textContent = v == null ? "—" : (typeof v === "object" ? JSON.stringify(v) : String(v));
            riga.appendChild(td);
          }
          tbody.appendChild(riga);
        }
        tabella.appendChild(tbody);
        scatola.appendChild(titolo);
        scatola.appendChild(tabella);
        qualcosa = true;
      } else if (valore != null && typeof valore !== "object") {
        var voce = document.createElement("p");
        voce.textContent = chiave.replace(/_/g, " ") + ": " + String(valore);
        scatola.appendChild(voce);
        qualcosa = true;
      } else if (Array.isArray(valore) && valore.length === 0) {
        /* sezione vuota: niente tabella, ma la voce si dichiara */
        var vuota = document.createElement("p");
        vuota.textContent = chiave.replace(/_/g, " ") + ": nessun dato nel mese.";
        scatola.appendChild(vuota);
        qualcosa = true;
      }
    }
    if (!qualcosa) scatola.textContent = "Contenuti non ancora disponibili.";
  }

  function apriReport(id) {
    nascondi($("report-errore"));
    nascondi($("report-ok"));
    chiama("/pa/report/" + encodeURIComponent(id)).then(function (r) {
      reportAperto = r;
      $("dettaglio-titolo").textContent = "Report " + (r.mese || "") +
        " — " + (ETICHETTE_STATO[r.stato] || r.stato || "bozza");
      renderContenuti(r.contenuti);
      var lista = $("dettaglio-commenti");
      var commenti = r.commenti;
      lista.innerHTML = "";
      if (Array.isArray(commenti) && commenti.length > 0) {
        for (var i = 0; i < commenti.length; i++) {
          var c = commenti[i];
          var voce = document.createElement("li");
          voce.textContent = (c.autore || c.da_casa || "rete") +
            (c.ts ? " (" + String(c.ts).slice(0, 16).replace("T", " ") + ")" : "") +
            ": " + (c.testo || "");
          lista.appendChild(voce);
        }
      } else {
        lista.innerHTML = "<li>Nessun commento.</li>";
      }
      /* L'approvazione è solo della Rete AT e solo sulle bozze: il pulsante non
         compare altrimenti, perché la policy del database lo respingerebbe
         comunque (SECURITY DEFINER con EXECUTE a rete). */
      $("pulsante-approva").hidden = !(ruoloCorrente === "rete" && r.stato === "bozza");
      $("dettaglio-report").hidden = false;
      $("dettaglio-report").scrollIntoView({ block: "start" });
    }).catch(function (errore) {
      if (scaduta(errore)) return;
      mostra($("report-errore"), "Dettaglio non disponibile: " + errore.message);
    });
  }

  $("pulsante-export").addEventListener("click", function () {
    if (!reportAperto || reportAperto.id == null) return;
    /* Scheda nuova, come la scheda evento dello sportello: il documento
       stampabile è una pagina indipendente servita dallo shim. */
    window.open(location.origin + BASE + "/pa/report/" + encodeURIComponent(reportAperto.id) + "/export", "_blank");
  });

  $("pulsante-approva").addEventListener("click", function () {
    if (!reportAperto || reportAperto.id == null) return;
    nascondi($("report-errore"));
    chiama("/pa/report/" + encodeURIComponent(reportAperto.id) + "/approva", { method: "POST" }).then(function () {
      mostra($("report-ok"), "Approvato. La notifica alla PA parte al flusso delle 07:30.");
      $("pulsante-approva").hidden = true;
      caricaReport();
      apriReport(reportAperto.id);
    }).catch(function (errore) {
      if (scaduta(errore)) return;
      mostra($("report-errore"), "Approvazione non riuscita: " + errore.message);
    });
  });

  /* ------------------------------------------------------------- confronto */

  function caricaConfronto() {
    var corpo = $("corpo-confronto");
    corpo.innerHTML = "<tr><td colspan=\"5\">Caricamento…</td></tr>";
    chiama("/pa/report/confronto?mesi=2").then(function (dati) {
      var elenco = dati && (dati.items || dati.confronto || dati.righe || dati.risultati);
      if (!elenco && Array.isArray(dati)) elenco = dati;
      if (!Array.isArray(elenco) || elenco.length === 0) {
        corpo.innerHTML = "<tr><td colspan=\"5\">Confronto non disponibile: servono due mesi di report.</td></tr>";
        nascondi($("confronto-nota"));
        return;
      }
      corpo.innerHTML = "";
      var sottoSoglia = false;
      function cella(testo) {
        var td = document.createElement("td");
        td.textContent = testo == null ? "—" : String(testo);
        return td;
      }
      for (var i = 0; i < elenco.length; i++) {
        var r = elenco[i];
        var riga = document.createElement("tr");
        riga.appendChild(cella(r.categoria));
        riga.appendChild(cella(r.esito));
        riga.appendChild(cella(r.n_label != null && r.n_label !== "" ? r.n_label : r.n));
        riga.appendChild(cella(r.n_prec_label != null && r.n_prec_label !== "" ? r.n_prec_label : r.n_prec));
        /* delta_pct NULL = uno dei due mesi sotto soglia: «—» in tabella e la
           nota sotto spiega perché, invece di un confronto inventato. */
        if (r.delta_pct == null) {
          sottoSoglia = true;
          riga.appendChild(cella("—"));
        } else {
          riga.appendChild(cella(r.delta_pct));
        }
        corpo.appendChild(riga);
      }
      if (sottoSoglia) mostra($("confronto-nota"), "Alcune righe riportano «—»: il confronto non è disponibile sotto soglia k-anonimato.");
      else nascondi($("confronto-nota"));
    }).catch(function (errore) {
      if (scaduta(errore)) return;
      corpo.innerHTML = "<tr><td colspan=\"5\">Confronto non disponibile: " + errore.message + "</td></tr>";
    });
  }

  /* --------------------------------------------------------------- lacune */

  function caricaLacune() {
    var corpo = $("corpo-lacune");
    corpo.innerHTML = "<tr><td colspan=\"4\">Caricamento…</td></tr>";
    chiama("/pa/lacune").then(function (dati) {
      /* Lacune da due fonti: le richieste «non trovata» delle Case e gli esiti
         della chat (errore o nessuna risposta). Entrambi i conteggi arrivano
         già mascherati; la forma esatta la decide l'endpoint, qui ogni riga
         diventa una voce della tabella. */
      var elenco = dati && (dati.items || dati.lacune || dati.righe || dati.risultati);
      if (!elenco && Array.isArray(dati)) elenco = dati;
      if (!Array.isArray(elenco) || elenco.length === 0) {
        corpo.innerHTML = "<tr><td colspan=\"4\">Nessuna lacuna segnalata nel mese.</td></tr>";
        return;
      }
      corpo.innerHTML = "";
      function cella(testo) {
        var td = document.createElement("td");
        td.textContent = testo == null ? "—" : String(testo);
        return td;
      }
      for (var i = 0; i < elenco.length; i++) {
        var l = elenco[i];
        var riga = document.createElement("tr");
        riga.appendChild(cella(l.origine || l.fonte_origine || (l.canale ? "chat" : "sportello")));
        riga.appendChild(cella(l.categoria || l.canale || l.casa_slug));
        riga.appendChild(cella(l.dettaglio || l.esito || (l.casa_slug ? "Casa " + l.casa_slug : null)));
        riga.appendChild(cella(l.n_label != null && l.n_label !== "" ? l.n_label : l.n));
        corpo.appendChild(riga);
      }
    }).catch(function (errore) {
      if (scaduta(errore)) return;
      corpo.innerHTML = "<tr><td colspan=\"4\">Lacune non disponibili: " + errore.message + "</td></tr>";
    });
  }

  /* --------------------------------------------------- approfondimenti (chat) */

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
    if (!testo || !ruoloCorrente) return;
    battuta("operatore", testo);
    $("chat-testo").value = "";
    var attesa = battuta("assistente", "…");
    /* L'LLM risponde in decine di secondi: timeout client di due minuti con
       AbortController, scaduto il quale la chat dichiara il mancato arrivo
       invece di restare appesa su «…». */
    var controllo = new AbortController();
    var scadenza = setTimeout(function () { controllo.abort(); }, 120000);
    chiama("/pa/chat", { method: "POST", body: { messaggio: testo }, signal: controllo.signal }).then(function (dati) {
      clearTimeout(scadenza);
      var risposta = dati && (dati.risposta || dati.testo || dati.answer);
      attesa.textContent = typeof risposta === "string" && risposta.trim() ? risposta : JSON.stringify(dati);
    }).catch(function (errore) {
      clearTimeout(scadenza);
      if (errore && errore.sessioneScaduta) { scaduta(errore); return; }
      attesa.textContent = errore && errore.name === "AbortError"
        ? "L’assistente non risponde entro due minuti. La domanda può essere riproposta più tardi."
        : "L’assistente non risponde in questo momento (" + errore.message + ").";
    });
  });

  /* ---------------------------------------------------------------- avvio */

  /* Già dentro? `GET /pa/me` è la verifica: il cookie è HttpOnly, la pagina
     non può leggerlo e non prova a indovinarlo. Vale per entrambi i ruoli
     servizio (pa e rete): la scelta del modulo non cambia la sessione. */
  chiama("/pa/me").then(function (dati) {
    if (dati && dati.ruolo) inSessione(dati.ruolo);
    else fuoriSessione();
  }).catch(function () { fuoriSessione(); });
})();
