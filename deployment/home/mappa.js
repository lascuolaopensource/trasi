/* mappa.js — la mappa delle dieci Case della rete, centrata sulla Casa scelta. Vanilla JS + Leaflet vendorizzato.
 *
 * Preso dalla mappa dell'Osservatorio (ramo old-next) **solo** ciò che serve alle Case: apertura della
 * tela, tile, pin come testo, selezione nei due sensi, stati in parole. Niente POI esterni, niente
 * guscio, niente scheda. Il caricamento è riscritto per il canale pubblico della Home.
 *
 * Tre decisioni conservate da lì, e la ragione di ciascuna.
 *
 * 1. **I pin sono testo, non immagini.** `L.divIcon` disegna un carattere (`■`), la stessa forma della
 *    legenda in parole: nessuna richiesta di rete per disegnarli, e il segno non dipende dal colore. I
 *    pin sono `aria-hidden` e `keyboard: false`: la mappa non è navigabile da tastiera per costruzione,
 *    e il suo equivalente accessibile è l'elenco sotto, non il pin.
 * 2. **I tile OSM sono diretti dal browser**: nessun proxy. L'attribuzione è nel documento, in parole,
 *    non nel controllo di Leaflet (che a 24 rem la taglia). Se i tile non arrivano lo si dichiara: le
 *    Case e l'elenco restano leggibili.
 * 3. **Niente cerchio del raggio**: `raggio_m_eff` arriva dallo shim ma non si disegna (miglioria non
 *    approvata).
 *
 * L'UNICO dominio esterno contattato da questa pagina è `tile.openstreetmap.org` (sfondo della mappa).
 * Nessun CDN, nessun font remoto, nessuna geocodifica. I dati vengono dallo shim via `/api/shim/…`
 * (Caddy aggiunge la chiave lato server), con l'identità pubblica `rete@trasi.local` come la riga «Oggi».
 */
(function () {
  "use strict";

  var Casa = window.TrasiCasa;
  var IDENTITA = "rete@trasi.local";
  var ATTESA_MS = 3000;
  /* Il centro di ripiego quando non c'è una Casa: Brindisi. Non è una Casa — senza un centro la mappa
     non si disegna, e una mappa vuota direbbe «non c'è nulla» invece di «non c'è un punto di partenza». */
  var CENTRO_RIPIEGO = [40.6383, 17.9464];
  var ZOOM = 13;
  /* Testi in parole, verbatim (§7 del contratto / WCAG.md): mai un codice, mai «errore». */
  var DATI_NON_DISPONIBILI = "Dati non disponibili: la memoria della rete non risponde in questo momento. È un'informazione, non un guasto.";
  var SFONDO_NON_DISPONIBILE = "Sfondo della mappa non disponibile: le Case e l'elenco restano leggibili.";
  var ORARI_ASSENTI = "orari non disponibili";

  var contenitore = document.getElementById("mappa");
  var rigaStato = document.getElementById("mappa-stato");
  var tela = document.getElementById("mappa-tela");
  var elenco = document.getElementById("mappa-elenco");
  var selettore = Casa.selettore;

  var stato = { case: [], perSlug: {}, scelta: null };
  var mappa = null;
  var livello = null;
  var pin = {};
  var letturaInCorso = null;

  /* ------------------------------------------------------------------ la mappa */

  function apriMappa(centro) {
    if (mappa) return mappa;
    if (!window.L || !tela) {
      dichiaraSfondo(SFONDO_NON_DISPONIBILE);
      return null;
    }
    mappa = L.map("mappa-tela", {
      center: centro,
      zoom: ZOOM,
      /* I due bottoni di zoom restano (sono raggiungibili da tastiera e hanno un nome): in italiano. */
      zoomControl: false,
      attributionControl: false,
      /* Il `keyboard` di Leaflet è spento: i marcatori non sono focalizzabili, e un finto supporto
         da tastiera che non porta a nessuna voce è peggio dell'assenza. La via da tastiera è l'elenco. */
      keyboard: false
    });
    var sfondo = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "© OpenStreetMap contributors (ODbL)"
    });
    /* Nessun gestore `load` che nasconda la riga: Leaflet emette `load` anche quando i tile hanno
       fallito, e la dichiarazione sparirebbe un istante dopo essere comparsa (misurato con i tile bloccati). */
    sfondo.on("tileerror", function () { dichiaraSfondo(SFONDO_NON_DISPONIBILE); });
    sfondo.addTo(mappa);
    livello = L.layerGroup().addTo(mappa);
    L.control.zoom({ zoomInTitle: "Avvicina la mappa", zoomOutTitle: "Allontana la mappa" }).addTo(mappa);
    /* La sidebar cambia la tela senza un resize della finestra; vale anche per la testata che
       va a capo e per l'altezza dinamica del browser mobile. Il centro scelto non si sposta. */
    var dimensioni = new ResizeObserver(function (voci) {
      if (voci[0].contentRect.width && voci[0].contentRect.height) {
        mappa.invalidateSize({ pan: true, debounceMoveend: true });
      }
    });
    dimensioni.observe(tela);
    return mappa;
  }

  function dichiaraSfondo(testo) {
    var riga = document.getElementById("mappa-sfondo");
    if (!riga) return;
    if (!testo) { riga.hidden = true; riga.textContent = ""; return; }
    riga.textContent = testo;
    riga.hidden = false;
  }

  /* ------------------------------------------------------------------ i pin */

  function icona(scelta) {
    /* Il pin del prototipo: cerchio pieno con il segno del luogo. Resta testo nel DOM
       (divIcon), aria-hidden: l'elenco è l'equivalente accessibile. */
    return L.divIcon({
      className: "mappa-pin mappa-pin--casa" + (scelta ? " mappa-pin--scelto" : ""),
      html: '<svg class="icona" aria-hidden="true"><use href="assets/icone.svg#icon-map-pin"/></svg>',
      iconSize: [34, 34],
      iconAnchor: [17, 17]
    });
  }

  function disegna() {
    if (!mappa) return;
    livello.clearLayers();
    pin = {};
    stato.case.forEach(function (casa) {
      var marcatore = L.marker([casa.lat, casa.lon], {
        icon: icona(casa.slug === stato.scelta),
        title: casa.nome,
        alt: casa.nome,
        keyboard: false
      });
      /* Click sul pin → la voce dell'elenco si evidenzia e si porta in vista, senza rubare il focus. */
      marcatore.on("click", function () { seleziona(casa.slug, false); });
      marcatore.addTo(livello);
      pin[casa.slug] = marcatore;
    });
  }

  /* ------------------------------------------------------------------ selezione */

  function seleziona(slug, centra) {
    stato.scelta = slug;
    Object.keys(pin).forEach(function (altro) {
      var elemento = pin[altro].getElement();
      if (elemento) elemento.classList.toggle("mappa-pin--scelto", altro === slug);
    });
    if (tela) tela.classList.toggle("mappa-tela--scelta", Boolean(slug));
    var casa = stato.perSlug[slug];
    if (casa && centra && mappa) mappa.panTo([casa.lat, casa.lon]);
    /* L'elenco si ridisegna (l'ordine dipende dalla Casa scelta). Se il focus era su un bottone
       dell'elenco, torna sul bottone della stessa Casa: chi usa la tastiera non deve ritrovarsi
       all'inizio della pagina. Dal pin o dal selettore il focus non si tocca. */
    var focusNellElenco = elenco && elenco.contains(document.activeElement);
    disegnaElenco();
    if (elenco) {
      var voce = elenco.querySelector('[data-slug="' + slug + '"]');
      if (voce && focusNellElenco) {
        var bottone = voce.querySelector("button");
        if (bottone) bottone.focus({ preventScroll: true });
      }
      if (voce && !centra) voce.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }

  /* ------------------------------------------------------------------ l'elenco */

  /* Distanza sul cerchio massimo (haversine), in metri: serve solo all'ordine dell'elenco. */
  function distanza(a, b) {
    var R = 6371000, rad = Math.PI / 180;
    var dLat = (b.lat - a.lat) * rad, dLon = (b.lon - a.lon) * rad;
    var h = Math.sin(dLat / 2) * Math.sin(dLat / 2)
      + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
    return 2 * R * Math.asin(Math.sqrt(h));
  }

  /* Prima la Casa scelta, poi le altre per distanza da essa; senza Casa scelta, alfabetiche. */
  function ordinate() {
    var scelta = stato.perSlug[stato.scelta];
    var altre = stato.case.filter(function (c) { return c.slug !== stato.scelta; });
    if (!scelta) {
      return altre.slice().sort(function (a, b) { return a.nome.localeCompare(b.nome, "it"); });
    }
    altre.sort(function (a, b) { return distanza(scelta, a) - distanza(scelta, b); });
    return [scelta].concat(altre);
  }

  function nodo(tag, classe, testo) {
    var el = document.createElement(tag);
    if (classe) el.className = classe;
    if (testo !== undefined) el.textContent = testo;
    return el;
  }

  /* Il segno del pin, in elenco come sulla mappa: stesso cerchio, stesso simbolo. */
  function segno() {
    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "icona");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    var uso = document.createElementNS("http://www.w3.org/2000/svg", "use");
    uso.setAttribute("href", "assets/icone.svg#icon-map-pin");
    svg.appendChild(uso);
    return svg;
  }

  function disegnaElenco() {
    if (!elenco) return;
    while (elenco.firstChild) elenco.removeChild(elenco.firstChild);
    var scelta = stato.perSlug[stato.scelta];
    ordinate().forEach(function (casa) {
      var eScelta = casa.slug === stato.scelta;
      var voce = nodo("li", "mappa-voce" + (eScelta ? " mappa-voce--scelta" : ""));
      voce.setAttribute("data-slug", casa.slug);
      if (eScelta) voce.setAttribute("aria-current", "true");

      var testa = nodo("div", "mappa-voce-testa");
      var marca = nodo("span", "mappa-voce-segno");
      marca.setAttribute("aria-hidden", "true");
      marca.appendChild(segno());
      testa.appendChild(marca);
      testa.appendChild(nodo("span", "mappa-voce-nome", casa.nome));
      if (eScelta) testa.appendChild(nodo("span", "mappa-voce-etichetta", "la Casa scelta"));
      else if (scelta) testa.appendChild(nodo("span", "mappa-voce-distanza", Math.round(distanza(scelta, casa) / 100) / 10 + " km dalla Casa scelta"));
      voce.appendChild(testa);

      var riga = nodo("div", "mappa-voce-riga");
      if (casa.zona) riga.appendChild(nodo("span", null, casa.zona));
      if (casa.ente_gestore) riga.appendChild(nodo("span", null, casa.ente_gestore));
      voce.appendChild(riga);

      var orari = nodo("div", "mappa-voce-riga");
      orari.appendChild(nodo("span", null, casa.orari_testo || ORARI_ASSENTI));
      if (casa.orari_provvisori) orari.appendChild(nodo("span", "mappa-voce-nota", "orari provvisori"));
      if (casa.geom_qualita === "stimata") orari.appendChild(nodo("span", "mappa-voce-nota", "coordinate stimate"));
      if (casa.da_validare) orari.appendChild(nodo("span", "mappa-voce-nota", "dati provvisori"));
      voce.appendChild(orari);

      /* Il badge di provenienza (V3), verbatim, in monospazio: è una stringa da citare com'è. */
      voce.appendChild(nodo("p", "mappa-voce-fonte", casa.badge));

      var bottone = nodo("button", "mappa-voce-bottone", "Mostra sulla mappa");
      bottone.type = "button";
      bottone.setAttribute("aria-label", "Mostra " + casa.nome + " sulla mappa");
      bottone.addEventListener("click", function () { seleziona(casa.slug, true); });
      voce.appendChild(bottone);

      elenco.appendChild(voce);
    });
  }

  /* ------------------------------------------------------------------ stato e caricamento */

  function dichiaraStato(testo, attenzione) {
    if (!rigaStato) return;
    rigaStato.textContent = testo;
    rigaStato.classList.toggle("mappa-stato--attenzione", Boolean(attenzione));
  }

  function nascondiTutto() {
    if (tela) tela.hidden = true;
    var attr = document.getElementById("mappa-attribuzione");
    if (attr) attr.hidden = true;
    if (elenco) while (elenco.firstChild) elenco.removeChild(elenco.firstChild);
  }

  function mostraTutto() {
    if (tela) tela.hidden = false;
    var attr = document.getElementById("mappa-attribuzione");
    if (attr) attr.hidden = false;
  }

  function applica(dati, slug) {
    stato.case = (dati.case || []).filter(function (c) {
      return typeof c.lat === "number" && typeof c.lon === "number";
    });
    stato.perSlug = {};
    stato.case.forEach(function (c) { stato.perSlug[c.slug] = c; });
    stato.scelta = dati.casa_evidenziata || (stato.perSlug[slug] ? slug : null);

    var scelta = stato.perSlug[stato.scelta];
    var centro = scelta ? [scelta.lat, scelta.lon] : CENTRO_RIPIEGO;
    mostraTutto();
    if (apriMappa(centro)) {
      mappa.setView(centro, ZOOM);
      disegna();
    }
    disegnaElenco();
    var conteggio = stato.case.length + (stato.case.length === 1 ? " Casa" : " Case");
    dichiaraStato(conteggio + (scelta ? " · centrata su " + scelta.nome : " · la rete delle Case di Quartiere"), false);
    if (contenitore) contenitore.setAttribute("aria-busy", "false");
  }

  /* Una lettura per volta, con la stessa scadenza di 3 s della riga «Oggi»: se il selettore cambia due
     volte di fila, la risposta della Casa precedente non deve sovrascrivere quella nuova. */
  function leggi(slug) {
    if (letturaInCorso && typeof letturaInCorso.abort === "function") letturaInCorso.abort();
    var controllo = typeof AbortController === "function" ? new AbortController() : null;
    letturaInCorso = controllo;
    if (contenitore) contenitore.setAttribute("aria-busy", "true");
    dichiaraStato("Lettura in corso\u2026", false);

    var scadenza = window.setTimeout(function () { if (controllo) controllo.abort(); }, ATTESA_MS);
    var url = "/api/shim/v1/u/" + encodeURIComponent(IDENTITA) + "/mappa_case?casa=" + encodeURIComponent(slug);
    var richiesta;
    try {
      richiesta = fetch(url, { signal: controllo ? controllo.signal : undefined, headers: { Accept: "application/json" } });
    } catch (e) {
      window.clearTimeout(scadenza);
      letturaInCorso = null;
      fallita();
      return;
    }
    richiesta
      .then(function (risposta) {
        if (!risposta.ok) throw new Error("risposta " + risposta.status);
        return risposta.json();
      })
      .then(function (dati) {
        window.clearTimeout(scadenza);
        letturaInCorso = null;
        applica(dati, slug);
      })
      .catch(function () {
        /* Timeout, rete assente, shim fermo, risposta non JSON: stessa frase per l'operatore. */
        window.clearTimeout(scadenza);
        letturaInCorso = null;
        fallita();
      });
  }

  function fallita() {
    nascondiTutto();
    dichiaraStato(DATI_NON_DISPONIBILI, true);
    if (contenitore) contenitore.setAttribute("aria-busy", "false");
  }

  /* ------------------------------------------------------------------ avvio */

  /* `?casa=` dalla Home vince, poi la Casa ricordata, poi la predefinita: un valore non valido è
     ignorato in silenzio. La scelta si ricorda con la stessa chiave della Home. */
  var iniziale = Casa.daUrl() || Casa.ricorda() || Casa.casaScelta();
  if (selettore) selettore.value = iniziale;
  /* dropdown.js ha già montato il grilletto sopra il select: scritto il valore da qui,
     nessun evento parte — si riallinea l'etichetta a mano. */
  if (window.TrasiTendina) window.TrasiTendina.aggiorna(selettore);
  Casa.memorizza(iniziale);
  leggi(iniziale);

  if (selettore) {
    selettore.addEventListener("change", function () {
      var slug = Casa.casaScelta();
      Casa.memorizza(slug);
      /* La Casa è già in memoria: si ricentra ed evidenzia senza una seconda lettura. La lettura
         serve solo se i dati non ci sono (prima lettura fallita). */
      if (stato.perSlug[slug]) {
        seleziona(slug, true);
        dichiaraStato(stato.case.length + " Case · centrata su " + stato.perSlug[slug].nome, false);
      } else {
        leggi(slug);
      }
    });
  }

  /* Cambio di Casa da un'altra scheda dello stesso browser: la pagina segue. */
  window.addEventListener("storage", function (evento) {
    if (evento.key !== Casa.CHIAVE_CASA) return;
    var slug = Casa.casaValida(evento.newValue);
    if (!slug || !selettore || slug === selettore.value) return;
    selettore.value = slug;
    if (window.TrasiTendina) window.TrasiTendina.aggiorna(selettore);
    if (stato.perSlug[slug]) seleziona(slug, true); else leggi(slug);
  });

  /* ------------------------------------------------------------- il cassetto
     Aperto al caricamento; chiuso, resta il bottone per riaprirlo (prototipo, vista Mappa). */
  var cassetto = document.getElementById("mappa-cassetto");
  var chiudiCassetto = document.getElementById("mappa-cassetto-chiudi");
  var riapriCassetto = document.getElementById("mappa-riapri");
  if (cassetto && chiudiCassetto && riapriCassetto) {
    chiudiCassetto.addEventListener("click", function () {
      cassetto.hidden = true;
      riapriCassetto.hidden = false;
      riapriCassetto.focus();
    });
    riapriCassetto.addEventListener("click", function () {
      riapriCassetto.hidden = true;
      cassetto.hidden = false;
      var prima = cassetto.querySelector("button, a");
      if (prima) prima.focus();
    });
  }
})();
