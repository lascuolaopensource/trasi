/* shell.js — il guscio: sessione, sidebar, pannello, uscita.
 *
 * È il SOLO contratto di codice fra i bot (`CONTRATTO-shell.md` §4). Chi ha bisogno di una
 * funzione la chiede qui invece di scriverne una seconda copia.
 *
 * Cosa fa, e nient'altro:
 *   1. chiede `GET /api/shim/me`: se risponde, la pagina è "dentro"; se dà 401, si torna all'accesso;
 *   2. riempie la testata della sidebar (Casa e zona) e segna la voce corrente con `aria-current`;
 *   3. governa la sidebar sotto 62 rem (bottone «Menu», `Esc`, click fuori);
 *   4. espone `window.Trasi` con `api()`, `montaPannello()`, `casa`;
 *   5. gestisce «Esci».
 *
 * NON contiene: la chat, lo storico, la mappa, l'account. Quelli sono dei rispettivi moduli.
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

  /* ---------------------------------------------------------------- spiega */

  /* Il `detail` dello shim è una diagnosi per chi legge il log («dato_personale_sospetto — campi con
     dati personali: descrizione», «parametri non ammessi — al: …», «errore 503»): tecnico per
     costruzione. Chi sta allo sportello legge invece una frase. La traduzione è **una** — qui, e i
     moduli la chiamano — perché otto copie in otto file (misurate il 17/09) divergono alla prima
     modifica, e il giorno in cui una dice «errore 422» e l'altra «testo non ammesso» l'operatore
     non sa più a chi credere.

     Le famiglie sono quelle dei `DETAIL_*` dello shim e dei suoi 4xx/5xx; tutto ciò che non si
     riconosce diventa la frase generica — mai il codice, mai il testo grezzo. */
  var TESTO_SESSIONE = "Sessione non più valida: la pagina di accesso è a un passo.";
  var TESTO_NON_DISPONIBILE = "Dati non disponibili: la memoria della rete non risponde in questo momento";
  var TESTO_GENERICO = "Operazione non riuscita. Si può riprovare fra qualche istante.";

  function spiega(errore) {
    if (!errore) return TESTO_GENERICO;
    if (errore.sessioneScaduta) return TESTO_SESSIONE;
    var d = String(errore.message || "");
    var stato = errore.stato || 0;

    if (d.indexOf("dato_personale_sospetto") >= 0) {
      return "Il testo sembra contenere un dato personale — telefono, email, codice fiscale — e non è " +
             "stato inviato. Si può riscrivere senza quel dato.";
    }
    if (d.indexOf("da approvare in coda") >= 0) {
      return "Questa decisione spetta a chi approva in coda: la proposta è registrata e aspetta lì.";
    }
    if (d.indexOf("Casa destinataria sconosciuta") >= 0) {
      return "La Casa indicata non è fra quelle della rete. Il nome va scritto come nell'elenco (es. bozzano, san-bao).";
    }
    if (d.indexOf("non appartiene alla Casa") >= 0 || d.indexOf("non consentita al ruolo") >= 0 ||
        d.indexOf("senza accesso operativo") >= 0) {
      return "Questa operazione non è fra quelle della Casa di questa sessione.";
    }
    if (d.indexOf("precede quella di inizio") >= 0 || d.indexOf("periodo invertito") >= 0) {
      return "La data di fine viene prima di quella di inizio: le due date vanno invertite.";
    }
    if (d.indexOf("non presente nella memoria") >= 0 || d.indexOf("non trovat") >= 0) {
      return "Non c'è nulla con questo riferimento nella memoria della rete.";
    }
    if (d.indexOf("non raggiungibile") >= 0 || d.indexOf("non ha risposto") >= 0 || stato === 503 || stato === 504) {
      return TESTO_NON_DISPONIBILE;
    }
    if (stato === 409) {
      return "C'è già qualcosa che si sovrappone: la memoria della rete non ha accettato la scrittura.";
    }
    if (stato === 422) {
      return "Uno dei campi non è nella forma attesa: si può controllare e reinviare.";
    }
    if (stato >= 500) return TESTO_NON_DISPONIBILE;
    return TESTO_GENERICO;
  }

  /* ---------------------------------------------------------------- accesso */

  var VOCI = { "index.html": null, "home.html": null, "osservatorio.html": null, "account.html": null, "aiuto.html": null };

  function paginaCorrente() {
    var p = location.pathname.split("/").pop() || "index.html";
    return p === "" ? "index.html" : p;
  }

  function segnaVoce() {
    var p = paginaCorrente();
    // Home e accesso vivono nello stesso file: `index.html` è la voce Home.
    var voce = (p === "index.html" || p === "home.html") ? "index.html" : p;
    var voci = document.querySelectorAll(".nav-voce");
    for (var i = 0; i < voci.length; i++) {
      if (voci[i].getAttribute("href") === voce) {
        voci[i].setAttribute("aria-current", "page");
      }
    }
  }

  function testata(casa) {
    var nome = document.getElementById("shell-casa");
    if (nome) nome.textContent = casa.nome || casa.casa;
    var zona = document.getElementById("shell-zona");
    if (zona) {
      /* «dati provvisori» sta nel TESTO, mai in un colore (vincolo del progetto). «Zona» dichiarata
         in parole: il nome del quartiere da solo («La Rosa») non dice cosa è. */
      zona.textContent = (casa.zona ? "Zona " + casa.zona : "") + (casa.dati_provvisori ? " · dati provvisori" : "");
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
      /* Il logout DEVE partire prima di navigare: `location.href` subito dopo avrebbe
         cancellato la richiesta in volo (il cookie non revocato, la sessione viva).
         Si naviga quando lo shim risponde; se la richiesta fallisce, si naviga comunque —
         la sessione lato server scade da sé, e restare su una pagina che crede di essere
         uscita sarebbe peggio. */
      api("/logout", { method: "POST" })
        .catch(function () { /* la sessione lato server scade da sé */ })
        .then(function () { location.href = "index.html"; });
    });
  }

  /* ---------------------------------------------------------------- avvio */

  var Trasi = {
    casa: null,
    api: api,
    spiega: spiega,
    montaPannello: montaPannello,
    voceCorrente: paginaCorrente(),
    /* La Casa come la mostra la testata: serve a chi scrive i testi («Oggi a …», «… a San Bao»). */
    nomeCasa: function () { return Trasi.casa ? (Trasi.casa.nome || Trasi.casa.casa) : ""; }
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
})();
