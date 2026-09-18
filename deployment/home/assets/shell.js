/* shell.js — la sidebar comprimibile del guscio (240 px espansa, 72 px compressa).
 *
 * Una cosa sola, nient'altro: il bottone comprime la **propria** sidebar — `closest()`, non una
 * query globale, perché nel documento c'è una sidebar per pagina e non devono parlarsi.
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
  }

  window.TrasiShell = { pronte: pronte };

  /* Le pagine caricano questo file a fine `<body>`: il guscio c'è già. */
  pronte();
})();
