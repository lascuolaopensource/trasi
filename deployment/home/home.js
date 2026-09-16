/* Trasi Home — comportamento della pagina. Vanilla JS, nessuna dipendenza.
 * Fa quattro cose: la Casa scelta (in `localStorage` c'è **solo** lo slug), le
 * destinazioni con le frasi che la nominano, la riga «Oggi» (scadenza 3 s) e
 * quella della coda, dalla stessa lettura.
 *
 * Si passa da `/api/shim/…` e non dallo shim diretto perché la chiave
 * `X-Trasi-Key` è un segreto di servizio e questa pagina è pubblica: la mette
 * Caddy. L'identità è `rete@trasi.local` perché la Home non ha un login proprio:
 * un ruolo `casa_*` risponderebbe 404 su altre Case, `rete` non ne ha una
 * (`casa_corrente()` è NULL). Lo shim filtra comunque lato database.
 */
(function () {
  "use strict";

  /* Valori pubblici (slug delle Case), non dati personali: in `localStorage`
     non entra nient'altro (V5). */
  var CHIAVE_CASA = "trasi.casa_id";
  var CASA_PREDEFINITA = "san-bao";
  var IDENTITA = "rete@trasi.local";
  var ATTESA_MS = 3000;
  var TESTO_ATTESA = "Lettura dei dati di oggi in corso\u2026";
  var TESTO_ASSENTE = "Dati non disponibili: la memoria della rete non risponde in questo momento.";
  /* Senza questa riga, su uno schermo condiviso con un cittadino, l'operatore
     legge un guasto dove c'è solo un dato che manca. */
  var NOTA_ASSENTE = "\u00c8 un'informazione, non un guasto: le destinazioni qui sotto funzionano.";

  var selettore = document.getElementById("selettore-casa");
  var rigaOggi = document.getElementById("oggi");
  var casaNota = document.getElementById("casa-nota");
  var riquadroCoda = document.getElementById("coda");
  var testoCoda = document.getElementById("coda-testo");
  var contatore = document.getElementById("osservatorio-contatore");
  var notaChiedi = document.getElementById("chiedi-nota");
  var hrefInCorso = null;

  /* Lo slug è valido solo se è una delle opzioni del selettore: un residuo in
     `localStorage` non deve poter costruire un indirizzo arbitrario. */
  function opzione(slug) {
    if (typeof slug !== "string" || slug === "") return null;
    for (var i = 0; i < selettore.options.length; i++) {
      if (selettore.options[i].value === slug) return selettore.options[i];
    }
    return null;
  }

  function casaValida(slug) {
    return opzione(slug) ? slug : null;
  }

  function casaScelta() {
    return casaValida(selettore.value) || CASA_PREDEFINITA;
  }

  /* Il nome della Casa senza la nota: nell'opzione di Tuturano il testo porta
     anche «dati provvisori», che in una frase come «...a Tuturano» sarebbe di
     troppo. Il nome è quello che precede il trattino lungo. */
  function nomeCasa(slug) {
    var scelta = opzione(slug);
    if (!scelta) return slug;
    return scelta.textContent.split(" \u2014 ")[0].trim();
  }

  function memorizza(slug) {
    try {
      window.localStorage.setItem(CHIAVE_CASA, slug);
    } catch (e) {
      /* Navigazione privata o storage disabilitato: la pagina funziona lo stesso,
         semplicemente non ricorda la scelta. Non è un errore da mostrare. */
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

  /* Gli indirizzi stanno una volta sola, in `data-modello`. `URL`/`searchParams`
     riscriverebbe in relativo gli indirizzi dei sottodomini (CHIEDI sta su un
     altro host) o aggiungerebbe una barra finale alla rotta di Metabase. */
  function aggiornaDestinazioni(slug) {
    var anelli = document.querySelectorAll("[data-modello]");
    var codificato = encodeURIComponent(slug);
    for (var i = 0; i < anelli.length; i++) {
      anelli[i].setAttribute("href", anelli[i].getAttribute("data-modello").replace("{casa}", codificato));
    }
  }

  /* La nota di CHIEDI e quella dei dati provvisori: un nome sbagliato in una
     nota è un'informazione sbagliata. */
  function aggiornaNomi(slug) {
    var nome = nomeCasa(slug);
    if (notaChiedi) notaChiedi.textContent = "si apre con " + nome + " gi\u00e0 impostata";
    if (casaNota) {
      var scelta = opzione(slug);
      var provvisori = scelta && scelta.textContent.indexOf("dati provvisori") !== -1;
      casaNota.hidden = !provvisori;
      if (provvisori) {
        casaNota.textContent = nome + ": dati provvisori \u2014 alcune schede non sono ancora complete.";
      }
    }
  }

  /* ---------------------------------------------------------------- «Oggi» */

  function mostraTesto(testo, stato, nota) {
    rigaOggi.textContent = testo;
    rigaOggi.setAttribute("aria-busy", "false");
    if (stato) {
      rigaOggi.setAttribute("data-stato", stato);
    } else {
      rigaOggi.removeAttribute("data-stato");
    }
    var vecchia = rigaOggi.querySelector(".oggi-nota");
    if (vecchia) vecchia.remove();
    if (nota) {
      var p = document.createElement("span");
      p.className = "oggi-nota";
      p.textContent = nota;
      rigaOggi.appendChild(p);
    }
  }

  /* La coda: presenza, non allarme. Nessuna scadenza, nessun imperativo. Il dato
     che dice se è ferma non è il numero ma l'età della più vecchia: distingue
     «tre arrivate oggi» da «tre ferme da un mese». */
  function mostraCoda(slug, numero, giorni) {
    if (!riquadroCoda || !testoCoda) return;
    var nome = nomeCasa(slug);
    var vuota = !numero;

    riquadroCoda.hidden = false;
    riquadroCoda.setAttribute("data-vuota", vuota ? "si" : "no");

    while (testoCoda.firstChild) testoCoda.removeChild(testoCoda.firstChild);

    if (vuota) {
      testoCoda.appendChild(document.createTextNode("Nessuna proposta in attesa a " + nome + "."));
    } else {
      var forte = document.createElement("strong");
      forte.className = "coda-numero";
      forte.textContent = String(numero);
      testoCoda.appendChild(forte);
      testoCoda.appendChild(document.createTextNode(
        " " + (numero === 1 ? "proposta aspetta" : "proposte aspettano") + " una decisione a " + nome
      ));
      if (giorni) {
        var quando = document.createElement("span");
        quando.className = "coda-quando";
        quando.textContent = " \u00b7 la pi\u00f9 vecchia da " + giorni + (giorni === 1 ? " giorno" : " giorni");
        testoCoda.appendChild(quando);
      }
    }

    /* Anche sul riquadro OSSERVATORIO: è là che si decide. */
    if (contatore) {
      contatore.hidden = vuota;
      if (!vuota) contatore.textContent = numero + (numero === 1 ? " proposta in attesa" : " proposte in attesa");
    }
  }

  /* Lettura fallita: la coda sparisce. Non sappiamo quante proposte aspettano, e
     «nessuna in attesa» sarebbe falso — l'operatore non controllerebbe una coda
     che ha davvero proposte ferme. */
  function nascondiCoda() {
    if (riquadroCoda) riquadroCoda.hidden = true;
    if (contatore) contatore.hidden = true;
  }

  /* Una lettura per volta: se il selettore cambia due volte di fila, la risposta
     della Casa precedente non deve sovrascrivere quella nuova. */
  function leggiOggi(slug) {
    if (hrefInCorso && typeof hrefInCorso.abort === "function") hrefInCorso.abort();
    var controllo = typeof AbortController === "function" ? new AbortController() : null;
    hrefInCorso = controllo;

    mostraTesto(TESTO_ATTESA, "attesa", null);
    rigaOggi.setAttribute("aria-busy", "true");
    /* Nascosta durante la lettura: un numero della Casa precedente sarebbe
       sbagliato, ed è peggio di nessun numero. */
    if (riquadroCoda) riquadroCoda.hidden = true;

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
      mostraTesto(TESTO_ASSENTE, "non-disponibile", NOTA_ASSENTE);
      nascondiCoda();
      return;
    }

    richiesta
      .then(function (risposta) {
        if (!risposta.ok) throw new Error("risposta " + risposta.status);
        return risposta.json();
      })
      .then(function (dati) {
        finisci();
        /* Si mostra **solo** il `testo` della vista: ricomporre la frase qui
           sarebbe una seconda formattazione da tenere allineata, e la Home
           direbbe numeri diversi dalla chat. */
        if (dati && typeof dati.testo === "string" && dati.testo.trim() !== "") {
          mostraTesto(dati.testo, null, null);
          mostraCoda(dati.casa || slug, Number(dati.proposte) || 0, Number(dati.giorni_piu_vecchia) || 0);
        } else {
          mostraTesto(TESTO_ASSENTE, "non-disponibile", NOTA_ASSENTE);
          nascondiCoda();
        }
      })
      .catch(function () {
        /* Timeout, rete assente, shim fermo, risposta non JSON: stessa frase per
           l'operatore. Nessun errore grezzo a schermo. */
        finisci();
        mostraTesto(TESTO_ASSENTE, "non-disponibile", NOTA_ASSENTE);
        nascondiCoda();
      });
  }

  /* ------------------------------------------------------------- avvio */

  /* Il selettore è l'unica fonte della Casa scelta: gli `href` nell'HTML sono la
     destinazione predefinita senza JS. */
  selettore.value = ricorda(selettore.value) || selettore.value || CASA_PREDEFINITA;

  function applica(slug) {
    aggiornaDestinazioni(slug);
    aggiornaNomi(slug);
    leggiOggi(slug);
  }

  applica(casaScelta());

  selettore.addEventListener("change", function () {
    var slug = casaScelta();
    memorizza(slug);
    applica(slug);
  });

  /* Cambio di Casa da un'altra scheda dello stesso browser: la pagina segue. */
  window.addEventListener("storage", function (evento) {
    if (evento.key !== CHIAVE_CASA) return;
    var slug = casaValida(evento.newValue);
    if (!slug || slug === selettore.value) return;
    selettore.value = slug;
    applica(slug);
  });

  /* Uscita: chiude la sessione **dello shim** con lo stesso percorso del resto
     della pagina (Caddy aggiunge la chiave lato server). Il POST è gestito qui e
     non da un modulo HTML, perché l'`action` puntava a un altro dominio: il logout
     di Onyx. La sessione dell'operatore è del cookie `trasi_sessione`, e la revoca
     avviene sul database dello shim, quindi il pulsante non deve uscire da Trasi
     per funzionare. L'esito si dichiara in ogni caso — anche se la richiesta
     fallisce, chi ha premuto sa che non è uscito. */
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
})();
