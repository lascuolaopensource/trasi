/* shell.js — il guscio: sessione, sidebar, pannello, uscita.
 *
 * È il SOLO contratto di codice fra i bot (`CONTRATTO-shell.md` §4). Chi ha bisogno di una
 * funzione la chiede qui invece di scriverne una seconda copia.
 *
 * Cosa fa, e nient'altro:
 *   1. chiede `GET /api/shim/me`: se risponde, la pagina è "dentro"; se dà 401, si torna all'accesso;
 *   2. riempie la testata della sidebar (Casa e zona) e segna la voce corrente con `aria-current`;
 *   3. governa la sidebar sotto 62 rem (bottone «Menu», `Esc`, click fuori);
 *   4. espone `window.Trasi` con `api()`, `montaPannello()`, `casa`, `onyx`;
 *   5. gestisce «Esci»;
 *   6. chiede `GET /op/config` e trasforma la voce «Chiedi» in un collegamento a Onyx, che si apre
 *      in una nuova scheda: Onyx è l'unica superficie di conversazione con l'assistente.
 *
 * NON contiene: la mappa, l'account. Quelli sono dei rispettivi moduli. Non contiene nemmeno una
 * chat: la conversazione con l'assistente vive in Onyx, non in queste pagine.
 *
 * Perché tutte le chiamate passano da `/api/shim/…`: Caddy aggiunge la `X-Trasi-Key` lato server
 * (`deployment/caddy/Caddyfile`), il browser non vede mai un segreto.
 */
(function () {
  "use strict";

  var BASE = "/api/shim";

  /* ---------------------------------------------------------------- api */

  /* Una risposta non OK diventa un errore leggibile; mai il corpo grezzo (V6: niente gergo). */
  function api(percorso, opzioni) {
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
          var d = corpo && (corpo.dettaglio || corpo.detail);
          var err = new Error(typeof d === "string" ? d : "errore " + risposta.status);
          err.stato = risposta.status;
          throw err;
        });
      }
      var tipo = risposta.headers.get("content-type") || "";
      return tipo.indexOf("json") >= 0 ? risposta.json() : risposta.text();
    });
  }

  /* ---------------------------------------------------------------- accesso */

  var VOCI = { "home.html": null, "osservatorio.html": null, "account.html": null, "aiuto.html": null };

  function paginaCorrente() {
    var p = location.pathname.split("/").pop() || "index.html";
    return p === "" ? "index.html" : p;
  }

  function segnaVoce() {
    var p = paginaCorrente();
    var voci = document.querySelectorAll(".nav-voce");
    for (var i = 0; i < voci.length; i++) {
      if (voci[i].getAttribute("href") === p) {
        voci[i].setAttribute("aria-current", "page");
      }
    }
  }

  /* ---------------------------------------------------------------- onyx */

  /* Le voci «Chiedi» (`href="home.html"` nel guscio) puntano a Onyx: l'indirizzo lo dice lo shim
   * (`GET /op/config` → `{onyx_url}`), perché la Home è statica e non lo conosce. Nuova scheda, e
   * lo si dice a chi non la vede (`aria-label`); `rel="noopener"` perché Onyx è un'altra
   * applicazione. Se lo shim non risponde, la voce resta **senza** `href` e lo dichiara: mai un
   * collegamento vuoto, mai un ripiego a una chat che qui non c'è più. */
  var TESTO_ONYX_NON_DISPONIBILE = "Onyx non disponibile";

  function vociChiedi() {
    return document.querySelectorAll('.nav-voce[href="home.html"]');
  }

  function collegaOnyx(url) {
    var voci = vociChiedi();
    for (var i = 0; i < voci.length; i++) {
      var a = voci[i];
      a.setAttribute("href", url);
      a.setAttribute("target", "_blank");
      a.setAttribute("rel", "noopener");
      a.setAttribute("aria-label", a.textContent.trim() + " (si apre in una nuova scheda)");
      a.removeAttribute("aria-current");
    }
  }

  function scollegaOnyx() {
    var voci = vociChiedi();
    for (var i = 0; i < voci.length; i++) {
      var a = voci[i];
      a.removeAttribute("href");
      a.removeAttribute("aria-current");
      a.setAttribute("aria-disabled", "true");
      a.textContent = TESTO_ONYX_NON_DISPONIBILE;
    }
  }

  function testata(casa) {
    var nome = document.getElementById("shell-casa");
    if (nome) nome.textContent = casa.nome || casa.casa;
    var zona = document.getElementById("shell-zona");
    if (zona) {
      // «dati provvisori» sta nel TESTO, mai in un colore (vincolo del progetto).
      zona.textContent = (casa.zona || "") + (casa.dati_provvisori ? " · dati provvisori" : "");
    }
  }

  /* ---------------------------------------------------------------- sidebar */

  function governaSidebar() {
    var sidebar = document.getElementById("sidebar");
    var bottone = document.getElementById("shell-menu");
    if (!sidebar || !bottone) return;

    var stretto = function () { return window.matchMedia("(max-width: 62rem)").matches; };

    function chiudi() {
      if (!stretto()) return;
      sidebar.hidden = true;
      bottone.setAttribute("aria-expanded", "false");
    }
    function apri() {
      sidebar.hidden = false;
      bottone.setAttribute("aria-expanded", "true");
    }
    function sincronizza() { if (stretto()) chiudi(); else sidebar.hidden = false; }

    bottone.addEventListener("click", function () {
      if (sidebar.hidden) { apri(); var p = sidebar.querySelector("a, button"); if (p) p.focus(); }
      else chiudi();
    });

    // Esc chiude e riporta il focus al bottone: chi naviga da tastiera non resta intrappolato.
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && stretto() && !sidebar.hidden) { chiudi(); bottone.focus(); }
    });
    // Click fuori dal pannello: chiude (solo quando è a scomparsa).
    document.addEventListener("click", function (ev) {
      if (!stretto() || sidebar.hidden) return;
      if (!sidebar.contains(ev.target) && ev.target !== bottone) chiudi();
    });

    window.addEventListener("resize", sincronizza);
    sincronizza();
  }

  /* ---------------------------------------------------------------- pannello */

  function montaPannello(html) {
    var p = document.getElementById("shell-pannello");
    if (p) p.innerHTML = html;
  }

  /* ---------------------------------------------------------------- esci */

  function governaEsci() {
    var b = document.getElementById("shell-esci");
    if (!b) return;
    b.addEventListener("click", function () {
      api("/logout", { method: "POST" }).catch(function () { /* la sessione lato server scade da sé */ });
      location.href = "index.html";
    });
  }

  /* ---------------------------------------------------------------- avvio */

  var Trasi = {
    casa: null,
    api: api,
    montaPannello: montaPannello,
    voceCorrente: paginaCorrente(),
    /* La Casa come la mostra la testata: serve a chi scrive i testi («Oggi a …», «… a San Bao»). */
    nomeCasa: function () { return Trasi.casa ? (Trasi.casa.nome || Trasi.casa.casa) : ""; },
    /* Promessa dell'indirizzo di Onyx (`GET /op/config`): si chiude con l'URL, o si rifiuta se lo
     * shim non lo dà. `home.html` la usa per rimandare a Onyx chi la apre da un vecchio segnalibro. */
    onyx: null
  };
  window.Trasi = Trasi;

  segnaVoce();
  governaSidebar();
  governaEsci();

  /* `GET /me` dice chi è entrato: `{casa, casa_id, ruolo}`. La zona e i «dati provvisori»
   * arrivano da `GET /op/casa`, che è della pagina Account: se non c'è, la testata mostra
   * solo il nome — senza inventare niente. */
  Trasi.pronto = api("/me").then(function (me) {
    Trasi.casa = me;
    testata(me);
    return api("/op/casa").then(function (dettaglio) {
      Trasi.casa = Object.assign({}, me, dettaglio);
      testata(Trasi.casa);
      return Trasi.casa;
    }).catch(function () { return Trasi.casa; });
  }).catch(function (e) {
    if (e && e.sessioneScaduta && paginaCorrente() !== "index.html") {
      location.href = "index.html";
      return null;
    }
    return null;
  });

  /* Solo con una sessione: senza, `/op/config` darebbe 401 e la pagina sta già tornando all'accesso. */
  Trasi.onyx = Trasi.pronto.then(function (casa) {
    if (!casa) throw new Error(TESTO_ONYX_NON_DISPONIBILE);
    return api("/op/config");
  }).then(function (config) {
    if (!config || typeof config.onyx_url !== "string" || !config.onyx_url) {
      throw new Error(TESTO_ONYX_NON_DISPONIBILE);
    }
    collegaOnyx(config.onyx_url);
    return config.onyx_url;
  });
  Trasi.onyx.catch(function () { scollegaOnyx(); });
})();
