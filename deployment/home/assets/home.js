/* home.js — la Home della Casa: oggi, cosa aspetta una decisione, le destinazioni.
 *
 * Tre letture, tutte in sola lettura e tutte indipendenti: se una non risponde, le altre restano.
 *   1. `GET /op/eventi?dal=oggi&al=oggi&casa_id` → gli eventi del giorno alla Casa della sessione;
 *   2. `GET /op/proposte` → la riga della coda, composta da `shell.js` (`Trasi.rigaCoda`), perché è
 *      la stessa riga dell'Account e due copie del testo divergerebbero;
 *   3. `GET /op/movimenti_da_confermare` → i prestiti che aspettano una conferma della Casa.
 *
 * Nessuna scrittura da qui: la Home dice, l'Account fa. Il badge di provenienza degli eventi si copia
 * **verbatim** dallo shim (V3). Le date si costruiscono in locale: `toISOString()` le sposterebbe di
 * un giorno per il fuso e la Home chiederebbe gli eventi di ieri.
 */
(function () {
  "use strict";

  var DATI_NON_DISPONIBILI = "Dati non disponibili: la memoria della rete non risponde in questo momento. È un'informazione, non un guasto.";
  var GIORNI = ["domenica", "lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato"];
  var MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
              "settembre", "ottobre", "novembre", "dicembre"];

  function $(id) { return document.getElementById(id); }

  function elemento(tag, classe, contenuto) {
    var e = document.createElement(tag);
    if (classe) e.className = classe;
    if (contenuto !== undefined && contenuto !== null) e.textContent = contenuto;
    return e;
  }

  function isoLocale(d) {
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" +
      String(d.getDate()).padStart(2, "0");
  }

  function dataEstesa(d) {
    return GIORNI[d.getDay()] + " " + d.getDate() + " " + MESI[d.getMonth()] + " " + d.getFullYear();
  }

  /* ---------------------------------------------------------------- oggi */

  function disegnaEventi(eventi) {
    var contenitore = $("home-eventi");
    var sezione = $("home-oggi");
    contenitore.textContent = "";
    if (sezione) sezione.setAttribute("aria-busy", "false");

    if (!eventi.length) {
      contenitore.appendChild(elemento("p", "vuoto", "Nessun evento oggi a " + window.Trasi.nomeCasa() + "."));
      return;
    }
    var lista = elemento("ul", "elenco home-eventi");
    eventi.forEach(function (evento) {
      var riga = elemento("li", "home-evento");
      var testa = elemento("div", "riga home-evento-testa");
      testa.appendChild(elemento("span", "home-evento-ora",
        evento.ora_inizio + (evento.ora_fine ? "–" + evento.ora_fine : "")));
      testa.appendChild(elemento("span", "home-evento-titolo", evento.titolo));
      riga.appendChild(testa);
      if (evento.luogo_testo) riga.appendChild(elemento("p", "vuoto", evento.luogo_testo));
      /* Il badge verbatim dello shim, su riga propria sotto l'informazione (§1.3 regola 2). */
      if (evento.badge) riga.appendChild(elemento("p", "etichetta etichetta--kb", evento.badge));
      lista.appendChild(riga);
    });
    contenitore.appendChild(lista);
  }

  function caricaOggi(casa) {
    var oggi = isoLocale(new Date());
    var url = "/op/eventi?dal=" + oggi + "&al=" + oggi + "&casa_id=" + encodeURIComponent(casa.casa_id);
    return window.Trasi.api(url).then(function (dati) {
      disegnaEventi((dati && dati.eventi) || []);
    }).catch(function () {
      var contenitore = $("home-eventi");
      contenitore.textContent = "";
      contenitore.appendChild(elemento("p", "vuoto", DATI_NON_DISPONIBILI));
      var sezione = $("home-oggi");
      if (sezione) sezione.setAttribute("aria-busy", "false");
    });
  }

  /* ---------------------------------------------------------------- in attesa di una decisione */

  function caricaCoda() {
    return window.Trasi.rigaCoda($("home-coda")).then(function (proposte) {
      var rimando = $("home-coda-rimando");
      /* Il collegamento compare solo se c'è qualcosa da vedere: con la coda vuota la riga basta. */
      if (rimando) rimando.hidden = !(proposte && proposte.length);
    });
  }

  function caricaPrestiti() {
    var riga = $("home-prestiti");
    var rimando = $("home-prestiti-rimando");
    return window.Trasi.api("/op/movimenti_da_confermare").then(function (dati) {
      var movimenti = (dati && dati.movimenti) || [];
      if (!movimenti.length) {
        riga.hidden = true;
        if (rimando) rimando.hidden = true;
        return;
      }
      var piuVecchio = movimenti.reduce(function (a, m) {
        return (a === null || (m.giorni_attesa || 0) > (a.giorni_attesa || 0)) ? m : a;
      }, null);
      var testo = movimenti.length + (movimenti.length === 1 ? " prestito aspetta" : " prestiti aspettano") +
                  " una conferma";
      if (piuVecchio && piuVecchio.giorni_attesa > 0) {
        testo += " · il più vecchio da " + piuVecchio.giorni_attesa +
                 (piuVecchio.giorni_attesa === 1 ? " giorno" : " giorni");
      }
      riga.className = "home-riga filetto filetto--coda";
      riga.textContent = testo;
      riga.hidden = false;
      if (rimando) rimando.hidden = false;
    }).catch(function () {
      /* Senza risposta la riga sparisce: dire «nessun prestito» senza saperlo sarebbe falso. */
      riga.hidden = true;
      if (rimando) rimando.hidden = true;
    });
  }

  /* ---------------------------------------------------------------- avvio */

  var data = $("home-data");
  if (data) data.textContent = dataEstesa(new Date());

  if (!window.Trasi || !window.Trasi.pronto) return;
  window.Trasi.pronto.then(function (casa) {
    if (!casa) return;
    var nome = $("home-casa");
    if (nome) nome.textContent = window.Trasi.nomeCasa();
    caricaOggi(casa);
    caricaCoda();
    caricaPrestiti();
  });
})();
