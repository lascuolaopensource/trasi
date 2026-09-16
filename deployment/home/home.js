/* Trasi Home — comportamento della pagina. Vanilla JS, nessuna dipendenza.
 *
 * Tre compiti, e nient'altro:
 *   1. la Casa scelta nel selettore (in `localStorage` c'è **solo** lo slug);
 *   2. le quattro destinazioni, che seguono la Casa scelta;
 *   3. la riga «Oggi», una lettura della memoria della rete con scadenza a 3 s.
 *
 * Perché la riga «Oggi» passa da `/api/shim/…` e non parla direttamente con lo
 * shim: la chiave `X-Trasi-Key` è un segreto di servizio e questa pagina è
 * statica e pubblica. La chiave la mette Caddy nel proxy, lato server
 * (`deployment/caddy/Caddyfile`, blocco `handle_path /api/shim/*`). Il browser
 * non vede mai il segreto.
 *
 * Perché l'identità è `rete@trasi.local` e non quella dell'operatore: la Home
 * non ha un login proprio e il selettore può indicare una Casa diversa da
 * quella dell'operatore. Un ruolo `casa_*` può leggere solo la propria Casa e
 * risponderebbe 404 sulle altre; `rete` non ha una Casa (`casa_corrente()` è
 * NULL) ed è quindi l'unico ruolo che può leggere lo slug indicato. Lo shim
 * filtra comunque lato database: non è un controllo che vive qui.
 */
(function () {
  "use strict";

  /* La chiave e i valori sono dati pubblici della rete (slug delle Case), non
     dati personali: in `localStorage` non entra nient'altro (V5). */
  var CHIAVE_CASA = "trasi.casa_id";
  var CASA_PREDEFINITA = "san-bao";
  var IDENTITA = "rete@trasi.local";
  var ATTESA_MS = 3000;
  var TESTO_ATTESA = "Lettura dei dati di oggi in corso\u2026";
  var TESTO_ASSENTE = "Dati non disponibili: la memoria della rete non risponde in questo momento.";

  var selettore = document.getElementById("selettore-casa");
  var rigaOggi = document.getElementById("oggi");
  var hrefInCorso = null;

  /* Lo slug è valido solo se è una delle opzioni del selettore: un valore
     rimasto in `localStorage` da una versione precedente non deve poter
     costruire un indirizzo arbitrario. */
  function casaValida(slug) {
    if (typeof slug !== "string" || slug === "") return null;
    for (var i = 0; i < selettore.options.length; i++) {
      if (selettore.options[i].value === slug) return slug;
    }
    return null;
  }

  function casaScelta() {
    return casaValida(selettore.value) || CASA_PREDEFINITA;
  }

  function memorizza(slug) {
    try {
      window.localStorage.setItem(CHIAVE_CASA, slug);
    } catch (e) {
      /* Navigazione privata o storage disabilitato: la pagina funziona lo
         stesso, semplicemente non ricorda la scelta. Non è un errore da
         mostrare all'operatore. */
    }
  }

  function ricorda(slug) {
    try {
      return casaValida(window.localStorage.getItem(CHIAVE_CASA));
    } catch (e) {
      return null;
    }
  }

  /* ---------------------------------------------------------- destinazioni */

  /* Gli indirizzi sono scritti una volta sola, nel `data-modello` accanto a
     ciascun collegamento, e portano `{casa}` al posto dello slug. Compenetrare
     `URL`/`searchParams` qui riscriverebbe in relativo gli indirizzi dei
     sottodomini (CHIEDI sta su un altro host) o aggiungerebbe una barra
     finale alla rotta di Metabase: un modello esplicito non ha questi modi di
     sbagliare, e resta leggibile in `view-source`. */
  function aggiornaDestinazioni(slug) {
    var anelli = document.querySelectorAll("[data-modello]");
    for (var i = 0; i < anelli.length; i++) {
      var modello = anelli[i].getAttribute("data-modello");
      anelli[i].setAttribute("href", modello.replace("{casa}", encodeURIComponent(slug)));
    }
  }

  /* ---------------------------------------------------------------- «Oggi» */

  function mostraTesto(testo, stato) {
    rigaOggi.textContent = testo;
    rigaOggi.setAttribute("aria-busy", "false");
    if (stato) {
      rigaOggi.setAttribute("data-stato", stato);
    } else {
      rigaOggi.removeAttribute("data-stato");
    }
  }

  /* Una sola lettura per volta: se il selettore cambia due volte di fila, la
     risposta della Casa precedente non deve sovrascrivere quella nuova. */
  function leggiOggi(slug) {
    if (hrefInCorso && typeof hrefInCorso.abort === "function") hrefInCorso.abort();
    var controllo = typeof AbortController === "function" ? new AbortController() : null;
    hrefInCorso = controllo;

    mostraTesto(TESTO_ATTESA, "attesa");
    rigaOggi.setAttribute("aria-busy", "true");

    var scadenza = window.setTimeout(function () {
      if (controllo) controllo.abort();
    }, ATTESA_MS);

    function finisci() {
      window.clearTimeout(scadenza);
      hrefInCorso = null;
    }

    var richiesta;
    try {
      richiesta = fetch(
        "/api/shim/v1/u/" + encodeURIComponent(IDENTITA) + "/oggi?casa=" + encodeURIComponent(slug),
        { signal: controllo ? controllo.signal : undefined, headers: { Accept: "application/json" } }
      );
    } catch (e) {
      finisci();
      mostraTesto(TESTO_ASSENTE, "non-disponibile");
      return;
    }

    richiesta
      .then(function (risposta) {
        if (!risposta.ok) throw new Error("risposta " + risposta.status);
        return risposta.json();
      })
      .then(function (dati) {
        finisci();
        /* Si mostra **solo** il campo `testo` composto dalla vista del
           database: ricomporre la frase qui significherebbe due formattazioni
           da tenere allineate, e la Home direbbe numeri diversi dalla chat. */
        if (dati && typeof dati.testo === "string" && dati.testo.trim() !== "") {
          mostraTesto(dati.testo, null);
        } else {
          mostraTesto(TESTO_ASSENTE, "non-disponibile");
        }
      })
      .catch(function () {
        /* Timeout (3 s), rete assente, shim fermo, risposta non JSON: per
           l'operatore è la stessa cosa e si dice la stessa frase. Nessun
           errore grezzo arriva a schermo. */
        finisci();
        mostraTesto(TESTO_ASSENTE, "non-disponibile");
      });
  }

  /* ------------------------------------------------------------- avvio */

  /* Il selettore è l'unica fonte della Casa scelta: gli `href` scritti
     nell'HTML sono la destinazione predefinita della pagina, e da qui in poi
     seguono il selettore. */
  selettore.value = ricorda(selettore.value) || selettore.value || CASA_PREDEFINITA;
  aggiornaDestinazioni(casaScelta());

  selettore.addEventListener("change", function () {
    var slug = casaScelta();
    memorizza(slug);
    aggiornaDestinazioni(slug);
    leggiOggi(slug);
  });

  /* Cambio di Casa da un'altra scheda dello stesso browser: la pagina segue. */
  window.addEventListener("storage", function (evento) {
    if (evento.key !== CHIAVE_CASA) return;
    var slug = casaValida(evento.newValue);
    if (!slug || slug === selettore.value) return;
    selettore.value = slug;
    aggiornaDestinazioni(slug);
    leggiOggi(slug);
  });

  leggiOggi(casaScelta());

  /* Uscita: chiude la sessione **dello shim** con lo stesso percorso del resto
     della pagina (Caddy aggiunge la chiave lato server). Il POST è gestito qui e
     non da un modulo HTML, perché `action` puntava a un altro dominio: il logout
     di Onyx. La sessione dell'operatore è del cookie `trasi_sessione`, e la revoca
     avviene sul database dello shim (`DELETE FROM trasi.sessione`), quindi il
     pulsante non deve uscire da Trasi per funzionare. L'esito si dichiara in ogni
     caso — anche se la richiesta fallisce, l'utente sa che non è uscito. */
  var pulsanteEsci = document.getElementById("pulsante-esci");
  var esitoUscita = document.getElementById("esito-uscita");
  if (pulsanteEsci && esitoUscita) {
    pulsanteEsci.addEventListener("click", function () {
      fetch("/api/shim/logout", { method: "POST", credentials: "same-origin" })
        .then(function (risposta) {
          esitoUscita.textContent = risposta.ok
            ? "Sessione chiusa."
            : "Uscita non riuscita (risposta " + risposta.status + ").";
          esitoUscita.hidden = false;
        })
        .catch(function () {
          esitoUscita.textContent = "Uscita non riuscita: servizio non raggiungibile.";
          esitoUscita.hidden = false;
        });
    });
  }

  /* ====================== INIZIO BLOCCO TEST ======================
     Pannello di collaudo (?test=1). Va rimosso al rilascio insieme al
     blocco omonimo in index.html e style.css. Attivo solo se la query
     string lo chiede: senza `?test=1` non succede nulla. */
  (function pannelloTest() {
    if (!/[?&]test=1\b/.test(window.location.search)) return;
    var pannello = document.getElementById("pannello-test");
    if (!pannello) return;
    pannello.hidden = false;

    function esito(id, testo) {
      var el = document.getElementById(id);
      if (el) el.textContent = testo;
    }

    document.getElementById("test-healthz").addEventListener("click", function () {
      fetch("/api/shim/healthz").then(function (r) {
        esito("test-healthz-esito", "OK (" + r.status + ")");
      }).catch(function () {
        esito("test-healthz-esito", "non raggiungibile");
      });
    });

    document.getElementById("test-me").addEventListener("click", function () {
      fetch("/api/shim/me", { credentials: "same-origin" }).then(function (r) {
        return r.json().then(function (corpo) {
          esito("test-me-esito", r.status === 200 ? "in sessione: " + (corpo.casa || "?") : "nessuna sessione (" + r.status + ")");
        });
      }).catch(function () {
        esito("test-me-esito", "non raggiungibile");
      });
    });

    document.getElementById("test-scheda-evento").addEventListener("click", function () {
      var id = document.getElementById("test-evento-id").value;
      if (!id) return;
      window.open("/api/shim/op/scheda_evento?evento_id=" + encodeURIComponent(id), "_blank", "noopener");
    });

    document.getElementById("test-metabase").addEventListener("click", function () {
      var frame = document.getElementById("test-metabase-frame");
      frame.hidden = false;
      frame.src = "/metabase/dashboard/3";
      frame.addEventListener("load", function () {
        esito("test-metabase-esito", "caricato");
      });
      window.setTimeout(function () {
        if (esito) esito("test-metabase-esito", "timeout 5 s");
      }, 5000);
    });

    /* Riepilogo dell'ultima lettura della riga «Oggi»: la pagina la fa
       comunque, qui ci limitiamo a osservare il risultato. */
    var osservatore = new MutationObserver(function () {
      esito("test-oggi-esito", (rigaOggi.getAttribute("data-stato") || "letta") + " — «" +
        (rigaOggi.textContent || "").slice(0, 80) + "…»");
    });
    osservatore.observe(rigaOggi, { childList: true, attributes: true });
  })();
  /* ======================= FINE BLOCCO TEST ======================== */
})();
