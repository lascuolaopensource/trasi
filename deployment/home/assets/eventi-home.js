/* eventi-home.js — «Eventi del mese» nella Home: il palinsesto della rete, per giorno.
 *
 * Legge `GET /op/eventi?dal=<primo del mese>&al=<ultimo del mese>` **senza** `casa_id`: la policy
 * `evento_sel` (db/002) concede a ogni Casa la lettura degli eventi di tutta la rete, e la Home li
 * mostra tutti — con il nome della Casa su ogni riga, così l'operatore sa dove mandare la persona.
 * Le occorrenze degli eventi ricorrenti arrivano già espanse dallo shim (db/030): qui non si calcola
 * nessuna data, si disegna quello che arriva.
 *
 * Gli eventi già passati del mese non si mostrano: il palinsesto serve a rispondere «cosa c'è», e
 * un evento di ieri non è una risposta. La finestra letta è `oggi → ultimo del mese`.
 *
 * Testi in terza persona, nessun imperativo, nessun codice: lo stato di errore usa `Trasi.spiega`.
 */
(function () {
  "use strict";

  var MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
              "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"];
  var GIORNI = ["domenica", "lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato"];
  var RIPETIZIONE = {
    settimanale: "ogni settimana", bisettimanale: "ogni due settimane",
    mensile: "ogni mese", annuale: "ogni anno"
  };

  function $(id) { return document.getElementById(id); }

  function el(tag, classe, testo) {
    var e = document.createElement(tag);
    if (classe) e.className = classe;
    if (testo) e.textContent = testo;
    return e;
  }

  function isoLocale(d) {
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  }

  /* `2026-09-20` → «sabato 20 settembre». La data ISO dello shim è locale (fuso italiano). */
  function giornoInParole(iso) {
    var p = iso.split("-").map(Number);
    var d = new Date(p[0], p[1] - 1, p[2]);
    return GIORNI[d.getDay()] + " " + d.getDate() + " " + MESI[d.getMonth()];
  }

  function voce(evento) {
    var li = el("li", "eventi-voce");
    var ora = el("span", "eventi-ora", evento.ora_inizio + (evento.ora_fine ? "–" + evento.ora_fine : ""));
    var titolo = el("span", "eventi-titolo", evento.titolo);
    var dove = el("span", "eventi-dove", (evento.luogo_testo ? evento.luogo_testo + " · " : "") + evento.casa_nome);
    li.appendChild(ora);
    li.appendChild(titolo);
    li.appendChild(dove);
    if (evento.ricorrenza && RIPETIZIONE[evento.ricorrenza]) {
      li.appendChild(el("span", "eventi-ripete", RIPETIZIONE[evento.ricorrenza]));
    }
    /* Il badge di provenienza **verbatim** (V3): esterna o memoria della rete, come lo compone lo shim. */
    var badge = el("span", "etichetta " + (evento.badge.indexOf("[Esterna") === 0 ? "etichetta--esterna" : "etichetta--kb"), evento.badge);
    li.appendChild(badge);
    return li;
  }

  function disegna(dati, oggi) {
    var lista = $("eventi-lista");
    var stato = $("eventi-stato");
    var titolo = $("eventi-titolo");
    if (!lista) return;
    lista.textContent = "";

    if (titolo) titolo.textContent = "Eventi di " + MESI[oggi.getMonth()] + " nella rete";

    var eventi = dati.eventi || [];
    if (!eventi.length) {
      stato.textContent = "Nessun evento in programma da oggi alla fine del mese, in nessuna Casa della rete.";
      stato.hidden = false;
      return;
    }
    stato.hidden = true;

    var perGiorno = {};
    var ordine = [];
    eventi.forEach(function (e) {
      if (!perGiorno[e.giorno]) { perGiorno[e.giorno] = []; ordine.push(e.giorno); }
      perGiorno[e.giorno].push(e);
    });
    ordine.forEach(function (giorno) {
      var blocco = el("div", "eventi-giorno");
      var testa = el("p", "eventi-giorno-testa", giornoInParole(giorno) + (giorno === isoLocale(oggi) ? " · oggi" : ""));
      var ul = el("ul", "eventi-voci");
      perGiorno[giorno].forEach(function (e) { ul.appendChild(voce(e)); });
      blocco.appendChild(testa);
      blocco.appendChild(ul);
      lista.appendChild(blocco);
    });
  }

  function carica() {
    var stato = $("eventi-stato");
    if (!stato || !window.Trasi || !window.Trasi.api) return;
    var oggi = new Date();
    var ultimo = new Date(oggi.getFullYear(), oggi.getMonth() + 1, 0);
    stato.textContent = "Lettura del palinsesto in corso…";
    stato.hidden = false;
    window.Trasi.api("/op/eventi?dal=" + isoLocale(oggi) + "&al=" + isoLocale(ultimo))
      .then(function (dati) { disegna(dati, oggi); })
      .catch(function (e) {
        if (e && e.sessioneScaduta) return;
        stato.textContent = window.Trasi.spiega ? window.Trasi.spiega(e) : "Dati non disponibili: la memoria della rete non risponde in questo momento";
        stato.hidden = false;
      });
  }

  function avvia() {
    if (!window.Trasi || !window.Trasi.pronto) return;
    window.Trasi.pronto.then(function (sessione) { if (sessione) carica(); });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", avvia);
  else avvia();
})();