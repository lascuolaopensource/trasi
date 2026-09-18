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
  var listaEventi = document.getElementById("oggi-eventi");
  var righeEventi = document.getElementById("oggi-eventi-righe");
  var titoloEventi = document.getElementById("oggi-eventi-titolo");
  var vuotoEventi = document.getElementById("oggi-eventi-vuoto");
  var contatore = document.getElementById("osservatorio-contatore");
  var notaChiedi = document.getElementById("chiedi-nota");
  var riquadroChiedi = document.getElementById("riquadro-chiedi");
  var hrefInCorso = null;
  /* Vero quando CHIEDI punta a Onyx: da lì in poi la Casa scelta non c'entra più
     con l'indirizzo né con la nota del riquadro. */
  var chiediSuOnyx = false;

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
    if (notaChiedi && !chiediSuOnyx) {
      notaChiedi.textContent = "entra nell'area operatore con " + nome + ": da l\u00ec \u00abChiedi\u00bb apre Onyx";
    }
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

  /* Il calendario del mese, sotto il conteggio: una riga per evento, Giorno · Ora ·
     Evento · Dove, nell'ordine in cui lo shim li dà (`eventi_mese`, per inizio).
     L'unica formattazione fatta qui è il giorno («gio 18») da `e.data`: ora, titolo
     e luogo sono quelli dello shim, come li vede la chat. «Oggi» lo dice lo shim
     (`dati.oggi`, nel fuso della rete), non l'orologio del browser: così le righe
     evidenziate coincidono con la riga «Oggi» sopra. L'evidenza è la parola «oggi»
     nella cella Giorno e `aria-current="date"`, prima che un colore.
     Un mese vuoto si dichiara in parole: con il mese intero, l'assenza di righe non
     è più spiegata dal conteggio della riga sopra, che parla solo di oggi. La
     tabella si nasconde solo quando la lettura fallisce. */
  var FORMATO_GIORNO = (typeof Intl === "object" && Intl.DateTimeFormat)
    ? new Intl.DateTimeFormat("it-IT", { weekday: "short", day: "numeric" })
    : null;
  var FORMATO_MESE = (typeof Intl === "object" && Intl.DateTimeFormat)
    ? new Intl.DateTimeFormat("it-IT", { month: "long", year: "numeric" })
    : null;

  /* `AAAA-MM-GG` → Date locale (mezzogiorno, così nessun fuso la sposta di giorno). */
  function dataLocale(iso) {
    var parti = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
    return parti ? new Date(Number(parti[1]), Number(parti[2]) - 1, Number(parti[3]), 12) : null;
  }

  function testoGiorno(iso) {
    var d = dataLocale(iso);
    if (!d) return iso || "";
    return FORMATO_GIORNO ? FORMATO_GIORNO.format(d) : String(d.getDate());
  }

  function testoMese(iso) {
    var d = dataLocale(iso);
    if (!d) return "";
    return FORMATO_MESE ? FORMATO_MESE.format(d) : (d.getMonth() + 1) + "/" + d.getFullYear();
  }

  function cella(tag, classe, testo) {
    var el = document.createElement(tag);
    if (classe) el.className = classe;
    el.textContent = testo;
    return el;
  }

  function mostraEventi(dati, slug) {
    if (!listaEventi || !righeEventi) return;
    while (righeEventi.firstChild) righeEventi.removeChild(righeEventi.firstChild);
    var eventi = dati && Array.isArray(dati.eventi) ? dati.eventi : [];
    var mese = testoMese(dati && dati.dal);
    var nome = nomeCasa((dati && dati.casa) || slug);
    if (titoloEventi) titoloEventi.textContent = "Eventi di " + mese + " a " + nome;

    if (!eventi.length) {
      if (vuotoEventi) {
        vuotoEventi.textContent = "Nessun evento in programma a " + mese + " per " + nome + ".";
        vuotoEventi.hidden = false;
      }
      righeEventi.parentNode.hidden = true;
    } else {
      if (vuotoEventi) vuotoEventi.hidden = true;
      righeEventi.parentNode.hidden = false;
      for (var i = 0; i < eventi.length; i++) {
        var e = eventi[i];
        var riga = document.createElement("tr");
        riga.className = "oggi-evento";
        var oggi = !!(dati.oggi && e.data === dati.oggi);
        if (oggi) {
          riga.classList.add("oggi-evento--oggi");
          riga.setAttribute("aria-current", "date");
        }

        var giorno = cella("th", "oggi-evento-giorno", testoGiorno(e.data));
        giorno.setAttribute("scope", "row");
        if (oggi) {
          giorno.appendChild(document.createTextNode(" "));
          giorno.appendChild(cella("span", "oggi-evento-oggi", "oggi"));
        }
        riga.appendChild(giorno);

        var quando = e.ora_inizio ? e.ora_inizio + (e.ora_fine ? "\u2013" + e.ora_fine : "") : (e.orari_nota || "");
        riga.appendChild(cella("td", "oggi-evento-ora", quando));
        riga.appendChild(cella("td", "oggi-evento-titolo", e.titolo));
        riga.appendChild(cella("td", "oggi-evento-dove", e.dove || ""));
        righeEventi.appendChild(riga);
      }
    }
    listaEventi.hidden = false;
    rigaOggi.setAttribute("data-eventi", "si");
  }

  function nascondiEventi() {
    if (listaEventi) listaEventi.hidden = true;
    rigaOggi.removeAttribute("data-eventi");
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
    nascondiEventi();

    var scadenza = window.setTimeout(function () {
      if (controllo) controllo.abort();
    }, ATTESA_MS);

    /* Due letture sotto la stessa scadenza: il timer si spegne quando è arrivata
       anche la seconda, altrimenti la lista resterebbe senza limite di attesa. */
    var inAttesa = 2;
    function finisci() {
      if (--inAttesa > 0) return;
      window.clearTimeout(scadenza);
      hrefInCorso = null;
    }

    var base = "/api/shim/v1/u/" + encodeURIComponent(IDENTITA) + "/";
    var opzioni = { signal: controllo ? controllo.signal : undefined, headers: { Accept: "application/json" } };
    var richiesta;
    var richiestaEventi;
    try {
      richiesta = fetch(base + "oggi?casa=" + encodeURIComponent(slug), opzioni);
      /* Stessa scadenza e stesso `abort` della riga: un calendario della Casa
         precedente non deve comparire sotto il conteggio di quella nuova. */
      richiestaEventi = fetch(base + "eventi_mese?casa=" + encodeURIComponent(slug), opzioni);
    } catch (e) {
      window.clearTimeout(scadenza);
      hrefInCorso = null;
      mostraTesto(TESTO_ASSENTE, "non-disponibile", NOTA_ASSENTE);
      nascondiCoda();
      return;
    }

    richiestaEventi
      .then(function (risposta) {
        if (!risposta.ok) throw new Error("risposta " + risposta.status);
        return risposta.json();
      })
      .then(function (dati) {
        finisci();
        mostraEventi(dati, slug);
      })
      .catch(function () {
        finisci();
        nascondiEventi();
      });

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

  /* ------------------------------------------------------------- CHIEDI → Onyx
   *
   * Onyx è l'unica superficie di conversazione con l'assistente. L'indirizzo lo
   * dice lo shim (`GET /op/config` → `{onyx_url}`), perché questa pagina è statica
   * e non lo conosce; l'endpoint vuole la sessione operatore, quindi:
   *   200 → il riquadro apre Onyx in una nuova scheda (e lo dichiara a chi non la vede);
   *   401 → nessuna sessione: il riquadro resta la porta dell'area operatore, dove si
   *         entra e da dove «Chiedi» apre Onyx (l'`href` dell'HTML, già corretto);
   *   altro → il riquadro si spegne e dice «Onyx non disponibile». Mai un `href`
   *         vuoto, mai una chat dentro Trasi. */
  if (riquadroChiedi) {
    fetch("/api/shim/op/config", { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (risposta) {
        if (risposta.status === 401) return null;
        if (!risposta.ok) throw new Error("risposta " + risposta.status);
        return risposta.json();
      })
      .then(function (config) {
        if (config === null) return;
        if (!config || typeof config.onyx_url !== "string" || !config.onyx_url) throw new Error("onyx_url assente");
        chiediSuOnyx = true;
        riquadroChiedi.removeAttribute("data-modello");
        riquadroChiedi.setAttribute("href", config.onyx_url);
        riquadroChiedi.setAttribute("target", "_blank");
        riquadroChiedi.setAttribute("rel", "noopener");
        riquadroChiedi.setAttribute("aria-label", "CHIEDI (si apre in una nuova scheda)");
        if (notaChiedi) notaChiedi.textContent = "si apre in Onyx, in una nuova scheda";
      })
      .catch(function () {
        chiediSuOnyx = true;
        riquadroChiedi.removeAttribute("data-modello");
        riquadroChiedi.removeAttribute("href");
        riquadroChiedi.setAttribute("aria-disabled", "true");
        riquadroChiedi.classList.add("spenta");
        if (notaChiedi) notaChiedi.textContent = "Onyx non disponibile";
      });
  }

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
