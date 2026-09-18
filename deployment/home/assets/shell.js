/* shell.js — sidebar comprimibile e Aiuto su richiesta.
 * Il bottone comprime la propria sidebar tramite closest().
 * Lo stato non si conserva: al ricaricamento la sidebar torna espansa (niente dati
 * personali, neppure una preferenza — regola V5 del progetto).
 *
 * Le classi le dà `style.css` (`.guscio--stretto`); qui c'è solo il comportamento e
 * `aria-expanded`, perché il segno di stato è anche una parola per chi usa lo schermo.
 */
(function () {
  "use strict";

  function pronte() {
    var bottoni = document.querySelectorAll("[data-sidebar-comprimi]");
    for (var i = 0; i < bottoni.length; i++) {
      bottoni[i].addEventListener("click", function () {
        var guscio = this.closest(".guscio");
        if (!guscio) return;
        var stretto = guscio.classList.toggle("guscio--stretto");
        this.setAttribute("aria-expanded", stretto ? "false" : "true");
        /* L'etichetta segue lo stato: quando è compresso il bottone «espande». */
        this.setAttribute("aria-label", stretto ? "Espandi il menu" : "Comprimi il menu");
      });
    }
    var aiuti = document.querySelectorAll("[data-aiuto-apri]");
    for (var j = 0; j < aiuti.length; j++) {
      aiuti[j].addEventListener("click", function () {
        var dialogo = document.getElementById(this.getAttribute("aria-controls"));
        if (dialogo && !dialogo.open) dialogo.showModal();
      });
    }
  }

  /* Home e operatore riusano la loro lettura di /op/config; solo la Mappa la avvia qui.
     null = accesso richiesto, false = servizio non disponibile, stringa = URL Onyx. */
  function aggiornaChiedi(url) {
    var link = document.getElementById("sidebar-chiedi");
    if (!link) return;
    link.removeAttribute("target");
    link.removeAttribute("rel");
    link.removeAttribute("aria-disabled");
    link.setAttribute("aria-label", "Chiedi");
    if (url === false) {
      link.removeAttribute("href");
      link.setAttribute("aria-disabled", "true");
      link.setAttribute("aria-label", "Chiedi — Onyx non disponibile");
    } else {
      link.setAttribute("href", url || "/operatore.html");
      if (url) {
        link.setAttribute("target", "_blank");
        link.setAttribute("rel", "noopener");
        link.setAttribute("aria-label", "Chiedi (si apre in una nuova scheda)");
      }
    }
  }

  if (document.querySelector("#sidebar-chiedi[data-carica-onyx]")) {
    fetch("/api/shim/op/config", { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (risposta) {
        if (risposta.status === 401) return null;
        if (!risposta.ok) throw new Error("risposta " + risposta.status);
        return risposta.json();
      })
      .then(function (config) {
        if (config === null) return aggiornaChiedi(null);
        if (!config || typeof config.onyx_url !== "string" || !config.onyx_url) throw new Error("onyx_url assente");
        aggiornaChiedi(config.onyx_url);
      })
      .catch(function () { aggiornaChiedi(false); });
  }

  window.TrasiShell = { pronte: pronte, aggiornaChiedi: aggiornaChiedi };

  /* Le pagine caricano questo file a fine `<body>`: il guscio c'è già. */
  pronte();
})();
