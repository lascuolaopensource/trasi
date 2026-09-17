/* shell.js — il guscio: sessione, testata, coda delle proposte, uscita.
 *
 * È il SOLO contratto di codice fra le pagine (`CONTRATTO-shell.md` §4). Chi ha bisogno di una
 * funzione la chiede qui invece di scriverne una seconda copia.
 *
 * Cosa fa, e nient'altro:
 *   1. chiede `GET /api/shim/me`: se risponde, la pagina è "dentro"; se dà 401, si torna all'accesso;
 *   2. riempie la testata (Casa e zona) e segna la voce corrente con `aria-current`;
 *   3. espone `window.Trasi` con `api()`, `rigaCoda()`, `casa`, `nomeCasa()`, `pronto`;
 *   4. gestisce «Esci».
 *
 * NON contiene: la mappa, l'account, la Home. Quelli sono dei rispettivi moduli. Non contiene una
 * chat: la conversazione con l'assistente della rete vive su Onyx, non in queste pagine.
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

  function paginaCorrente() {
    var p = location.pathname.split("/").pop() || "index.html";
    return p === "" ? "index.html" : p;
  }

  function segnaVoce() {
    var p = paginaCorrente();
    // L'accesso vive in index.html; la pagina Home della sessione è home.html.
    var voce = p;
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
      // «dati provvisori» sta nel TESTO, mai in un colore (vincolo del progetto).
      zona.textContent = (casa.zona || "") + (casa.dati_provvisori ? " · dati provvisori" : "");
    }
  }

  /* ---------------------------------------------------------------- riga di presenza della coda */

  /* Due fatti distinti, e la differenza è il punto del gate G-05:
   *   - `decidibile > 0`  → «N proposte aspettano una decisione a <Casa>»  → pulsanti attivi in #proposte
   *   - `nonDecidibile>0` → «N proposte riguardano la Casa e la decisione è di <chi>»
   * Con TUTTE le proposte non decidibili NON si dice «nessuna proposta in attesa»: sarebbe falso, ed
   * è il difetto che questo blocco esiste per evitare (una coda che sembra vuota mentre c'è dentro
   * una decisione che aspetta qualcun altro). La riga sta in Home e in Account con lo stesso testo:
   * per questo vive qui e non in una delle due pagine. */
  function testoCoda(proposte, nomeCasa) {
    if (!proposte || !proposte.length) {
      return { testo: "Nessuna proposta in attesa a " + nomeCasa + ".", stato: "filetto--spento" };
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
    return { testo: testo, stato: decidibili.length ? "filetto--coda" : "filetto--attenzione" };
  }

  /* Riempie `contenitore` (che ha già le sue classi di pagina) con la riga della coda: aggiunge
   * `filetto` e lo stato, scrive il testo, lo mostra. Se la lettura fallisce, la riga **sparisce**
   * invece di dire «nessuna proposta»: non sapendo quante ne aspettano, affermare che non ce ne
   * sono sarebbe un'informazione falsa. Restituisce la promessa con le proposte, per chi ne ha
   * bisogno oltre alla riga (la Home mostra anche il collegamento alla sezione). */
  function rigaCoda(contenitore) {
    if (!contenitore) return Promise.resolve(null);
    var base = contenitore.className.split(/\s+/).filter(function (c) {
      return c && c !== "filetto" && c.indexOf("filetto--") !== 0;
    }).join(" ");
    return api("/op/proposte").then(function (dati) {
      var proposte = (dati && dati.proposte) || [];
      var r = testoCoda(proposte, Trasi.nomeCasa());
      contenitore.className = base + " filetto " + r.stato;
      contenitore.textContent = r.testo;
      contenitore.hidden = false;
      return proposte;
    }).catch(function () {
      contenitore.hidden = true;
      return null;
    });
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
    rigaCoda: rigaCoda,
    voceCorrente: paginaCorrente(),
    /* La Casa come la mostra la testata: serve a chi scrive i testi («Oggi a …», «… a San Bao»). */
    nomeCasa: function () { return Trasi.casa ? (Trasi.casa.nome || Trasi.casa.casa) : ""; }
  };
  window.Trasi = Trasi;

  segnaVoce();
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
