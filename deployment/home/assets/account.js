/* account.js — la pagina singola dell'Account: sotto-navigazione, caricamento delle sezioni, coda.
 *
 * Contratto (CONTRATTO-shell.md §5):
 *   1. la sezione attiva viene da `location.hash`; senza hash è `#la-casa`;
 *   2. si carica **una** sezione alla volta con `fetch('account/<nome>.html')` dentro `#acc-vista`:
 *      le altre non sono nel DOM, così gli id non collidono e la pagina resta leggera;
 *   3. i frammenti sono **solo markup** — `<script>` dentro `innerHTML` non viene eseguito, quindi
 *      il comportamento sta qui;
 *   4. se il `fetch` fallisce, la vista mostra lo stato «dati non disponibili», mai un errore grezzo.
 *
 * La riga di presenza della coda sta invece in testa alla pagina e non dipende dalla sezione aperta:
 * è l'unica cosa che cambia da sola, e vale la pena leggerla prima di scegliere dove andare.
 */
(function () {
  "use strict";

  var SEZIONI = ["la-casa", "numeri", "proposte", "registra", "attrezzoteca",
                 "messaggi", "conversazioni", "impostazioni"];
  var PREDEFINITA = "la-casa";

  var vista = document.getElementById("acc-vista");
  var nav = document.querySelector(".acc-sottonav");

  /* ---------------------------------------------------------------- stato della vista */

  function sezioneRichiesta() {
    var nome = (location.hash || "").replace(/^#/, "");
    return SEZIONI.indexOf(nome) >= 0 ? nome : PREDEFINITA;
  }

  function segnaVoce(nome) {
    var voci = nav.querySelectorAll("a");
    for (var i = 0; i < voci.length; i++) {
      var suo = (voci[i].getAttribute("href") || "").replace(/^#/, "");
      if (suo === nome) voci[i].setAttribute("aria-current", "true");
      else voci[i].removeAttribute("aria-current");
    }
  }

  /* Lo stato «dati non disponibili» è un'informazione, non un guasto: il testo è quello del
   * design system, riusato alla lettera, e il filetto è giallo sole, mai rosso. */
  function mostraGuasto(che) {
    vista.innerHTML =
      '<div class="blocco filetto filetto--attenzione">' +
      '<p><strong>Dati non disponibili</strong>: la memoria della rete non risponde in questo momento.</p>' +
      '<p>È un\'informazione, non un guasto. La sezione «' + che + '» è raggiungibile fra qualche istante.</p>' +
      '</div>';
  }

  var caricata = null;
  var moduli = {};   // src → Promise: un modulo si carica una volta sola per pagina

  /* Carica il modulo JS di una sezione, una volta sola.
   *
   * Perché serve: i frammenti sono **solo markup** (`<script>` dentro `innerHTML` non viene
   * eseguito), quindi una sezione che ha bisogno di comportamento lo dichiara come DATO — con
   * `data-modulo="assets/account-proposte.js"` sull'elemento radice — e questa funzione lo carica
   * prima di chiamare l'avvio. Così chi scrive una sezione non tocca `account.html` (che è di uno
   * solo) per aggiungere il proprio `<script>`: il meccanismo è lo stesso per tutte le sezioni, e
   * regge anche con sei sezioni scritte da due persone diverse in parallelo.
   *
   * `moduli[src]` conserva la Promise: una sezione aperta due volte non riscarica il modulo.
   * Il fallimento è tollerato (`catch`) perché un modulo mancante non deve impedire la lettura
   * della sezione: il markup resta visibile, e il comportamento che manca si dichiara nel rapporto.
   */
  function caricaModulo(src) {
    if (moduli[src]) return moduli[src];
    moduli[src] = new Promise(function (ok, ko) {
      var s = document.createElement("script");
      s.src = src;
      s.onload = ok;
      s.onerror = ko;
      document.head.appendChild(s);
    });
    return moduli[src];
  }

  function carica(nome, forza) {
    if (caricata === nome && !forza) return;   // niente ricariche inutili sullo stesso hash
    segnaVoce(nome);
    vista.innerHTML = '<p class="acc-attesa">Lettura in corso…</p>';

    /* `cache: "no-cache"` di proposito: un frammento modificato durante il cantiere deve comparire
     * subito. In esercizio la differenza è trascurabile (un file locale, poche centinaia di byte) e
     * il vantaggio — non dover combattere con la cache mentre si lavora — è concreto. */
    fetch("account/" + nome + ".html", { credentials: "same-origin", cache: "no-cache" })
      .then(function (r) {
        if (!r.ok) throw new Error("sezione non disponibile: " + r.status);
        return r.text();
      })
      .then(function (html) {
        vista.innerHTML = html;
        caricata = nome;
        /* Dopo l'inserimento, il comportamento della sezione. Due strade, e la prima è quella
         * normale: il frammento dichiara il proprio modulo con `data-modulo` e lo si carica qui —
         * i `<script>` dentro `innerHTML` non vengono eseguiti, quindi la sezione non può caricarsi
         * da sola. La seconda (`AVVII`, registro diretto) resta per i moduli già caricati da
         * `account.html`, come `grafici.js`. */
        var radice = vista.querySelector("[data-modulo]");
        var pronto = radice
          ? caricaModulo(radice.getAttribute("data-modulo")).catch(function () { /* modulo assente: la sezione resta leggibile */ })
          : Promise.resolve();
        pronto.then(function () {
          var avvio = AVVII[nome];
          if (typeof avvio === "function") {
            try { avvio(vista); } catch (e) { /* un errore di una sezione non abbatte la pagina */ }
          }
        });
      })
      .catch(function () {
        caricata = null;
        mostraGuasto(nome);
      });
  }

  /* Registro degli avvii di sezione. Le sezioni che hanno bisogno di comportamento lo aggiungono
   * qui dal proprio modulo (es. `grafici.js` per «numeri»), invece di mettere `<script>` nel
   * frammento — che non verrebbe eseguito. */
  var AVVII = {};
  window.TrasiAccount = { avvii: AVVII, ricarica: function () { carica(sezioneRichiesta(), true); } };

  /* ---------------------------------------------------------------- riga di presenza della coda */

  /* Due fatti distinti, e la differenza è il punto del gate G-05:
   *   - `decidibile > 0`  → «N proposte aspettano una decisione a <Casa>»  → pulsanti attivi in #proposte
   *   - `nonDecidibile>0` → «N proposte riguardano la Casa e la decisione è di <chi>»
   * Con TUTTE le proposte non decidibili NON si dice «nessuna proposta in attesa»: sarebbe falso, ed
   * è il difetto che questo blocco esiste per evitare (una coda che sembra vuota mentre c'è dentro
   * una decisione che aspetta qualcun altro). */
  function rigaCoda(proposte, nomeCasa) {
    var contenitore = document.getElementById("acc-coda");
    if (!contenitore) return;
    if (!proposte || !proposte.length) {
      contenitore.className = "acc-coda filetto filetto--spento";
      contenitore.textContent = "Nessuna proposta in attesa a " + nomeCasa + ".";
      contenitore.hidden = false;
      return;
    }
    var decidibili = proposte.filter(function (p) { return p.decidibile; });
    var altrui = proposte.filter(function (p) { return !p.decidibile; });
    var piuVecchia = proposte.reduce(function (a, p) {
      return (a === null || (p.eta_giorni || 0) > (a.eta_giorni || 0)) ? p : a;
    }, null);

    var testo;
    if (decidibili.length) {
      testo = decidibili.length + (decidibili.length === 1 ? " proposta aspetta" : " proposte aspettano") +
              " una decisione a " + nomeCasa;
      if (piuVecchia && piuVecchia.eta_giorni > 0) {
        testo += " · la più vecchia da " + piuVecchia.eta_giorni +
                 (piuVecchia.eta_giorni === 1 ? " giorno" : " giorni");
      }
    } else {
      // La decisione è di altri: si dichiara chi, senza chiedere niente a chi legge.
      var chi = altrui[0].chi_decide === "at" ? "AT" : altrui[0].chi_decide;
      testo = altrui.length + (altrui.length === 1 ? " proposta riguarda" : " proposte riguardano") +
              " la Casa e la decisione è di " + chi;
    }

    contenitore.className = "acc-coda filetto " + (decidibili.length ? "filetto--coda" : "filetto--attenzione");
    contenitore.textContent = testo;
    contenitore.hidden = false;
  }

  /* ---------------------------------------------------------------- avvio */

  function caricaCoda(nomeCasa) {
    if (!window.Trasi) return;
    window.Trasi.api("/op/proposte").then(function (dati) {
      rigaCoda((dati && dati.proposte) || [], nomeCasa);
    }).catch(function () {
      /* Se la lettura fallisce, la riga **sparisce** invece di dire «nessuna proposta»: non sapendo
       * quante ne aspettano, affermare che non ce ne sono sarebbe un'informazione falsa — ed è la
       * stessa scelta già fatta dalla Home attuale (`deployment/home/WCAG.md` § 3.3.1). */
      var c = document.getElementById("acc-coda");
      if (c) c.hidden = true;
    });
  }

  nav.addEventListener("click", function (ev) {
    var a = ev.target.closest("a");
    if (!a) return;
    /* Il collegamento è un `<a href="#…">`: si lascia fare al browser (così l'indirizzo è
     * condivisibile), e si ricarica la vista sull'hash nuovo. */
    var nome = (a.getAttribute("href") || "").replace(/^#/, "");
    if (SEZIONI.indexOf(nome) >= 0) carica(nome);
  });
  window.addEventListener("hashchange", function () { carica(sezioneRichiesta()); });

  carica(sezioneRichiesta());

  if (window.Trasi && window.Trasi.pronto) {
    window.Trasi.pronto.then(function (casa) {
      if (!casa) return;
      var nome = window.Trasi.nomeCasa();
      var etichetta = document.getElementById("acc-casa");
      if (etichetta) etichetta.textContent = nome;
      caricaCoda(nome);
    });
  }
})();
