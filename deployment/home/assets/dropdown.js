/* dropdown.js — il dropdown custom del prototipo, sopra i `<select>` che ci sono già.
 *
 * Perché così: `casa.js` legge `selettore.value`, `operatore.js` legge il testo delle
 * `<option>` di `#accesso-casa`, `home.js` e `mappa.js` ascoltano il `change` del
 * selettore. Sostituire i select con un widget a parte romperebbe tutti e tre; arricchirli
 * no: il `<select>` resta nel documento (`display: none`), il pannello lo rispecchia e
 * scrive in lui, e il `change` parte dal select come prima.
 *
 * Uso: aggiungere `data-tendina` al `<select>`. Senza JS il select resta visibile e
 * funziona; con JS diventa trigger + pannello con la spunta sulla voce scelta
 * (`assets/icone.svg#icon-check`), chiusura su click fuori o `Esc`, una tendina aperta
 * alla volta. Tastiera: `Invio`/`Spazio` aprono, `↓ ↑` e `Home`/`Fine` si muovono,
 * `Invio` sceglie, `Esc` chiude e riporta il focus al grilletto.
 *
 * Le classi sono `tendina-` (prefisso di questo modulo, CONTRATTO-shell.md §3); le misure
 * e i colori vengono dai token di `style.css`, mai scritti a mano.
 */
(function () {
  "use strict";

  var SPRITE = "assets/icone.svg";

  function icona(nome) {
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "icona icona--piccola");
    svg.setAttribute("aria-hidden", "true");
    var uso = document.createElementNS("http://www.w3.org/2000/svg", "use");
    uso.setAttribute("href", SPRITE + "#" + nome);
    svg.appendChild(uso);
    return svg;
  }

  function nodo(tag, classe, testo) {
    var el = document.createElement(tag);
    if (classe) el.className = classe;
    if (testo !== undefined && testo !== null) el.textContent = testo;
    return el;
  }

  /* Il testo dell'opzione è quello che la pagina mostra altrove (Tuturano porta
     «dati provvisori» nel testo): mai abbreviato qui. */
  function testoVoce(opzione) {
    return opzione.textContent.replace(/\s+/g, " ").trim();
  }

  function monta(select) {
    if (select.getAttribute("data-tendina-pronta")) return;
    select.setAttribute("data-tendina-pronta", "vero");

    var contenitore = nodo("div", "tendina");
    contenitore.setAttribute("data-aperto", "falso");

    var grilletto = nodo("button", "tendina-grilletto");
    grilletto.type = "button";
    grilletto.setAttribute("aria-haspopup", "listbox");
    grilletto.setAttribute("aria-expanded", "false");
    grilletto.appendChild(nodo("span", "tendina-valore"));
    grilletto.appendChild(icona("icon-chevron-down")).classList.add("tendina-chevron");

    var pannello = nodo("div", "tendina-pannello");
    pannello.setAttribute("role", "listbox");
    var etichettaEl = select.id ? document.querySelector('label[for="' + select.id + '"]') : null;
    pannello.setAttribute("aria-label", etichettaEl ? etichettaEl.textContent : "Scelta");
    pannello.hidden = true;

    contenitore.appendChild(grilletto);
    contenitore.appendChild(pannello);
    select.parentNode.insertBefore(contenitore, select);
    /* Il select resta nel documento (casa.js/operatore.js lo leggono) ma esce dalla vista e
       dall'ordine di tabulazione: la voce si sceglie nel pannello, non due volte. */
    select.style.display = "none";

    function voci() {
      return Array.prototype.slice.call(pannello.querySelectorAll(".tendina-voce"));
    }

    function aggiorna() {
      var scelta = select.options[select.selectedIndex];
      contenitore.querySelector(".tendina-valore").textContent = scelta ? testoVoce(scelta) : "";
      voci().forEach(function (voce) {
        voce.setAttribute("aria-selected", voce.getAttribute("data-value") === select.value ? "true" : "false");
      });
    }

    function disegnaVoci() {
      while (pannello.firstChild) pannello.removeChild(pannello.firstChild);
      Array.prototype.forEach.call(select.options, function (opzione) {
        var voce = nodo("button", "tendina-voce");
        voce.type = "button";
        voce.setAttribute("role", "option");
        voce.setAttribute("data-value", opzione.value);
        voce.setAttribute("aria-selected", opzione.value === select.value ? "true" : "false");
        voce.appendChild(nodo("span", "tendina-voce-testo", testoVoce(opzione)));
        voce.appendChild(icona("icon-check"));
        voce.addEventListener("click", function () {
          select.value = opzione.value;
          /* Il `change` parte dal select, come prima di questa veste: gli ascoltatori
             delle pagine non sanno di noi. */
          select.dispatchEvent(new Event("change", { bubbles: true }));
          chiudi(true);
        });
        pannello.appendChild(voce);
      });
    }

    function apri() {
      document.querySelectorAll(".tendina[data-aperto=\"vero\"]").forEach(function (altra) {
        altra.setAttribute("data-aperto", "falso");
        var p = altra.querySelector(".tendina-pannello");
        if (p) p.hidden = true;
        var g = altra.querySelector(".tendina-grilletto");
        if (g) g.setAttribute("aria-expanded", "false");
      });
      disegnaVoci();
      contenitore.setAttribute("data-aperto", "vero");
      grilletto.setAttribute("aria-expanded", "true");
      pannello.hidden = false;
      var scelta = pannello.querySelector("[aria-selected=\"true\"]") || pannello.querySelector(".tendina-voce");
      if (scelta) scelta.focus();
    }

    function chiudi(alGrilletto) {
      contenitore.setAttribute("data-aperto", "falso");
      grilletto.setAttribute("aria-expanded", "false");
      pannello.hidden = true;
      if (alGrilletto) grilletto.focus();
    }

    grilletto.addEventListener("click", function () {
      if (contenitore.getAttribute("data-aperto") === "vero") chiudi(false);
      else apri();
    });

    grilletto.addEventListener("keydown", function (evento) {
      if (evento.key === "ArrowDown" || evento.key === "ArrowUp") {
        evento.preventDefault();
        apri();
      }
    });

    pannello.addEventListener("keydown", function (evento) {
      var elenco = voci();
      var dove = elenco.indexOf(document.activeElement);
      if (evento.key === "Escape") { evento.preventDefault(); chiudi(true); return; }
      if (evento.key === "ArrowDown") { evento.preventDefault(); (elenco[dove + 1] || elenco[0]).focus(); }
      if (evento.key === "ArrowUp") { evento.preventDefault(); (elenco[dove - 1] || elenco[elenco.length - 1]).focus(); }
      if (evento.key === "Home") { evento.preventDefault(); elenco[0].focus(); }
      if (evento.key === "End") { evento.preventDefault(); elenco[elenco.length - 1].focus(); }
      if (evento.key === "Tab") chiudi(false);
    });

    /* Click fuori e `Esc` chiudono: due ascoltatori per tutte le tendine, non uno per ciascuna. */
    document.addEventListener("click", function (evento) {
      if (contenitore.getAttribute("data-aperto") === "vero" && !contenitore.contains(evento.target)) chiudi(false);
    });
    document.addEventListener("keydown", function (evento) {
      if (evento.key === "Escape" && contenitore.getAttribute("data-aperto") === "vero") chiudi(true);
    });

    /* Il valore può cambiare da fuori (il selettore dell'altra pagina, un `?casa=` valido):
       l'etichetta del grilletto segue. */
    select.addEventListener("change", aggiorna);
    /* Le pagine possono scrivere `select.value` da fuori (un `?casa=`, un'altra scheda):
       nessun evento parte, quindi espongono il risincronizzo. */
    select._tendinaAggiorna = aggiorna;
    aggiorna();
  }

  window.TrasiTendina = {
    monta: monta,
    /* Riallinea grilletto e spunte a un `select.value` scritto da fuori. */
    aggiorna: function (select) { if (select && select._tendinaAggiorna) select._tendinaAggiorna(); },
    /* Per le pagine che costruiscono i propri select dopo il caricamento. */
    pronte: function () {
      document.querySelectorAll("select[data-tendina]").forEach(monta);
    }
  };

  /* Le pagine caricano questo file a fine `<body>`: i select statici ci sono già.
     Per select costruiti dopo (moduli dinamici) la pagina richiama `TrasiTendina.pronte()`. */
  TrasiTendina.pronte();
})();
