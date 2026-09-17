/* mappa.js — la mappa Leaflet dell'Osservatorio: centratura, pin a tre livelli, legenda, filtri.
 *
 * È il modulo che **accende** la pagina: carica i dati (`elenco.js`), disegna (`mappa.js`), e
 * governa la selezione nei due sensi (`elenco.js` chiama `seleziona`, i pin chiamano l'elenco).
 *
 * Tre decisioni non ovvie, e la ragione di ciascuna.
 *
 * 1. **I pin sono testo, non immagini.** Un marcatore Leaflet standard è un PNG del vendor: tre
 *    livelli richiederebbero tre immagini, e il colore sarebbe l'unico segnale. Qui `L.divIcon`
 *    disegna un carattere (`■ ● ○`), che è la stessa forma della legenda **in parole** di §4.2.1:
 *    nessuna richiesta di rete per disegnare, e il segno è leggibile a chiunque. I pin portano
 *    `aria-hidden`: la mappa Leaflet non è navigabile da tastiera per costruzione, e il suo
 *    equivalente accessibile è l'elenco, non il pin.
 *
 * 2. **La mappa non è la fonte della verità.** Lo stato (cosa è filtrato, cosa è scelto, quale
 *    vista è aperta) vive qui, in una struttura sola, e l'elenco e la scheda lo leggono. Leaflet
 *    custodisce solo i suoi layer: se una voce è in elenco ma il pin non c'è (per esempio un POI
 *    fuori dal riquadro), la selezione funziona lo stesso — e succede davvero, perché l'elenco è
 *    filtrato per tipo mentre i POI arrivano per bbox.
 *
 * 3. **I tile OSM sono diretti dal browser** (decisione D8): nessun proxy, nessun `no-cache`,
 *    `Referer` intatto. L'attribuzione è nel documento, non nel controllo di Leaflet, perché la
 *    policy impone che sia **visibile** e non nascosta dietro un toggle — e il controllo di
 *    Leaflet, a 24 rem, la taglia.
 *
 * Nessun dominio di terze parti viene contattato: solo `tile.openstreetmap.org` per i tile. La
 * pagina non chiama CDN, font remoti, né servizi di geocodifica.
 */
(function () {
  "use strict";

  var BASE = "/api/shim";

  /* ------------------------------------------------------------------ lo stato */

  var stato = {
    /* Le voci visibili, già filtrate e ordinate; è ciò che l'elenco disegna. */
    voci: [],
    /* Tutte le voci per chiave: case + luoghi della rete + POI esterni. */
    perChiave: {},
    case: [],
    luoghi: [],
    esterni: [],
    casaSessione: null,
    raggio: 800,
    /* I filtri attivi. `esterni` è spento all'avvio: ogni tipo acceso costa una interrogazione a
     * OpenStreetMap, e la mappa non paga ciò che nessuno ha chiesto. */
    filtri: { casa: true, luogo: true, esterna: false, aperto: false, tipi: {} },
    /* La chiave della voce scelta (o `null`): è il legame fra mappa, elenco e scheda. */
    scelta: null,
    /* Il tipo di ciascun elemento OSM: serve a comporre il riferimento `osm:<tipo>:<id>`. */
    osmTipo: {}
  };

  /* ------------------------------------------------------------------ la mappa */

  var mappa = null;
  var livelli = { casa: null, luogo: null, esterna: null, raggio: null };
  var pin = {};   /* chiave → marcatore Leaflet */

  /* Il centro di ripiego quando la sessione non ha una Casa (`rete`, `ti`): Brindisi. Non è una
   * Casa — nessuna riga lo dichiara — ma senza un centro la mappa non si disegna, e una mappa
   * vuota direbbe «non c'è nulla» invece di «non c'è un punto di partenza». */
  var CENTRO_RIPIEGO = [40.6383, 17.9464];
  var ZOOM = 14;

  function apriMappa(centro) {
    if (mappa) { return mappa; }
    if (!window.L) {
      /* Leaflet non caricato: la mappa non esiste, e lo si **dichiara**. L'elenco resta: è la
       * ragione per cui esiste, e da solo è già la pagina. */
      dichiaraSfondo("Sfondo della mappa non disponibile: i luoghi e l'elenco restano leggibili.");
      return null;
    }
    mappa = L.map("mappa-tela", {
      center: centro,
      zoom: ZOOM,
      /* Nessun controllo di scala né di livelli: il primo è rumore, il secondo servirebbe solo se
       * ci fossero più sfondi, e le immagini `layers.png` non sono nel vendor. */
      zoomControl: true,
      attributionControl: false,
      /* Il `keyboard` di Leaflet è spento: i marcatori non sono elementi focalizzabili, e un
       * finto supporto da tastiera che non porta a nessuna voce è peggio dell'assenza. La via da
       * tastiera è l'elenco, e la mappa lo dichiara nel suo `aria-label`. */
      keyboard: false
    });

    var sfondo = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      /* `crossOrigin` non si imposta: i tile non si leggono via canvas, e impostarlo
       * costringerebbe OSMF a rispondere con gli header CORS per nulla. */
      attribution: "© OpenStreetMap contributors (ODbL)"
    });
    sfondo.on("tileerror", function () {
      dichiaraSfondo("Sfondo della mappa non disponibile: i luoghi e l'elenco restano leggibili.");
    });
    sfondo.addTo(mappa);

    livelli.casa = L.layerGroup().addTo(mappa);
    livelli.luogo = L.layerGroup().addTo(mappa);
    livelli.esterna = L.layerGroup().addTo(mappa);

    return mappa;
  }

  function dichiaraSfondo(testo) {
    var riga = document.getElementById("mappa-sfondo");
    if (riga) { riga.textContent = testo; riga.hidden = false; }
  }

  /* ------------------------------------------------------------------ i pin */

  /* Il segno di ciascun livello: la stessa forma della legenda (§4.2.1). La classe porta la
   * **forma** e il carattere la ripete, quindi il segno non dipende dal colore. */
  var SEGNI = { casa: "■", luogo: "●", esterna: "○" };

  function icona(livello) {
    return L.divIcon({
      className: "mappa-pin mappa-pin--" + livello,
      html: '<span aria-hidden="true">' + SEGNI[livello] + "</span>",
      iconSize: [24, 24],
      iconAnchor: [12, 12]
    });
  }

  function disegna(voci) {
    if (!mappa) { return; }
    ["casa", "luogo", "esterna"].forEach(function (livello) { livelli[livello].clearLayers(); });
    pin = {};

    voci.forEach(function (voce) {
      /* Un luogo senza coordinate (P1.2) non ha un pin: `L.marker([null, null])` farebbe saltare l'intero
       * disegno per una voce sola. Resta nell'elenco, con «posizione non disponibile» (elenco.js). */
      if (voce.lat === null || voce.lat === undefined || voce.lon === null || voce.lon === undefined) { return; }
      var marcatore = L.marker([voce.lat, voce.lon], {
        icon: icona(voce.livello),
        title: voce.nome,
        alt: voce.nome,
        /* Il marcatore non prende il focus: la selezione da tastiera passa dall'elenco. */
        keyboard: false
      });
      /* Click sul pin → la voce dell'elenco si evidenzia e si porta in vista (§4.2.1). Il verso
       * opposto (elenco → pin) è `seleziona`, chiamata da `elenco.js`. */
      marcatore.on("click", function () { window.TrasiElenco.scegliDaMappa(voce.chiave); });
      marcatore.addTo(livelli[voce.livello]);
      pin[voce.chiave] = marcatore;
    });
  }

  /* ------------------------------------------------------------------ selezione */

  /* Evidenzia il pin scelto e attenua gli altri. `centra` è vero quando la scelta arriva
   * dall'elenco: l'operatore sta guardando il pin, e portarcelo sopra è la risposta alla sua
   * domanda. Quando la scelta arriva **dal** pin, la mappa è già lì: ricentrare sarebbe un
   * movimento che non ha chiesto nessuno. */
  function seleziona(chiave, centra) {
    stato.scelta = chiave;
    var tela = document.getElementById("mappa-tela");
    if (tela) { tela.classList.toggle("mappa-tela--scelta", Boolean(chiave)); }
    Object.keys(pin).forEach(function (altra) {
      var marcatore = pin[altra];
      var elemento = marcatore.getElement();
      if (!elemento) { return; }
      elemento.classList.toggle("mappa-pin--scelto", altra === chiave);
    });
    var voce = stato.perChiave[chiave];
    if (voce && centra && mappa && voce.lat !== null && voce.lat !== undefined && voce.lon !== null && voce.lon !== undefined) {
      mappa.panTo([voce.lat, voce.lon]);
    }
  }

  /* ------------------------------------------------------------------ i filtri */

  /* Un livello è visibile? `esterna` è un livello a sé: le Case e i luoghi della rete sono la
   * memoria, i POI esterni sono ciò che la rete **non** ha verificato, e la pagina li tiene
   * separati perché l'operatore possa spegnere i secondi e vedere solo ciò di cui la rete
   * risponde (V3). */
  function visibile(voce) {
    if (voce.livello === "casa" && !stato.filtri.casa) { return false; }
    if (voce.livello === "luogo" && !stato.filtri.luogo) { return false; }
    if (voce.livello === "esterna") {
      if (!stato.filtri.esterna) { return false; }
      if (stato.filtri.tipi[voce.tipo] === false) { return false; }
    }
    /* «Solo aperti adesso» esclude i **chiusi noti**: un luogo senza orari resta in elenco con
     * `aperto_adesso: null`. Scartarlo nasconderebbe la maggioranza reale dei POI esterni
     * (copertura `opening_hours` 7,7%) — è la regola dichiarata in §4.2.1 e la mitigazione §13. */
    if (stato.filtri.aperto && voce.aperto_adesso === false) { return false; }
    return true;
  }

  function applica() {
    stato.voci = tutte().filter(visibile);
    disegna(stato.voci);
    window.TrasiElenco.disegna(stato.voci, stato);
    /* Se la voce scelta esce dai filtri, la scheda si chiude: una scheda che descrive un luogo non
     * più in elenco è un pannello senza il suo oggetto, e chiuderla è il comportamento che
     * l'operatore si aspetta dalle caselle che ha appena mosso. */
    if (stato.scelta && !stato.voci.some(function (v) { return v.chiave === stato.scelta; })) {
      window.TrasiScheda.chiudi(false);
    }
    aggiornaConteggio();
  }

  function tutte() {
    return stato.case.concat(stato.luoghi, stato.esterni);
  }

  function aggiornaConteggio() {
    var rete = stato.voci.filter(function (v) { return v.livello !== "esterna"; }).length;
    var fuori = stato.voci.filter(function (v) { return v.livello === "esterna"; }).length;
    var riga = document.getElementById("mappa-conteggio");
    if (!riga) { return; }
    var pezzi = [stato.voci.length + (stato.voci.length === 1 ? " voce in elenco" : " voci in elenco")];
    pezzi.push(rete + " della rete");
    pezzi.push(fuori + " trovate fuori");
    riga.textContent = pezzi.join(" · ") + ".";
  }

  /* ------------------------------------------------------------------ caricamento */

  function errore(testo) {
    var riga = document.getElementById("mappa-errore");
    if (!riga) { return; }
    if (!testo) { riga.hidden = true; riga.textContent = ""; return; }
    riga.textContent = testo;
    riga.hidden = false;
  }

  /* Il testo di §7 del contratto, **verbatim**: non si riscrive, e la seconda riga è già nel
   * design system («È un'informazione, non un guasto»). */
  var DATI_NON_DISPONIBILI = "Dati non disponibili: la memoria della rete non risponde in questo momento. È un'informazione, non un guasto.";

  function titolo(dati) {
    var riga = document.getElementById("mappa-titolo");
    if (!riga) { return; }
    if (!dati.casaSessione) {
      /* Ruolo senza Casa (`rete`, `ti`): nessun «intorno a …», perché non c'è un intorno. La
       * pagina lo dichiara invece di scegliere una Casa per lui. */
      riga.textContent = "Osservatorio · la rete delle Case di Quartiere";
      return;
    }
    var parti = ["Osservatorio · intorno a " + dati.casaSessione.nome];
    if (dati.casaSessione.zona) { parti.push("(" + dati.casaSessione.zona + ")"); }
    if (dati.raggio) { parti.push("· raggio " + dati.raggio + " m"); }
    riga.textContent = parti.join(" ");
  }

  function carica() {
    return window.Trasi.api("/op/mappa").then(function (dati) {
      var centro = CENTRO_RIPIEGO;
      if (dati.casa_sessione) {
        centro = [dati.casa_sessione.lat, dati.casa_sessione.lon];
        stato.casaSessione = dati.casa_sessione;
      }
      stato.raggio = dati.raggio_m || stato.raggio;
      stato.case = (dati.case || []).map(vociDaCasa);
      stato.luoghi = (dati.luoghi || []).map(vociDaLuogo);
      stato.perChiave = {};
      tutte().forEach(function (voce) { stato.perChiave[voce.chiave] = voce; });

      apriMappa(centro);
      /* Il cerchio del raggio **non** si disegna: è la miglioria M3 del piano, e le migliorie non
       * sono nel percorso critico finché non sono approvate (§10). Disegnarlo qui sarebbe
       * introdurre una decisione che non è stata presa. */
      titolo(dati);
      applica();
      aggiornaEtichette();
      montaPannello();
      return dati;
    });
  }

  /* `chiave`: una stringa sola per ogni voce, che sia una Casa, un luogo della rete o un POI. Il
   * prefisso evita che il luogo 3 e la Casa 3 collidano — sono due cose diverse con lo stesso id. */
  function vociDaCasa(casa) {
    return {
      chiave: "casa:" + casa.id,
      livello: "casa",
      provenienza: "kb",
      id: casa.id,
      casaId: casa.id,
      nome: casa.nome,
      tipo: casa.tipo,
      zona: casa.zona,
      indirizzo: casa.indirizzo,
      lat: casa.lat,
      lon: casa.lon,
      distanza_m: casa.distanza_m,
      orari_testo: casa.orari_testo,
      orari_nota: casa.orari_nota,
      aperto_adesso: casa.aperto_adesso,
      fonte: casa.fonte,
      fiducia: casa.fiducia,
      data_aggiornamento: casa.data_aggiornamento,
      url: casa.url,
      badge: casa.badge,
      mia: casa.mia,
      ente_gestore: casa.ente_gestore,
      da_validare: casa.da_validare,
      orari_provvisori: casa.orari_provvisori
    };
  }

  function vociDaLuogo(luogo) {
    return {
      chiave: "luogo:" + luogo.id,
      livello: "luogo",
      provenienza: "kb",
      id: luogo.id,
      casaId: luogo.casa_id,
      casaNome: luogo.casa_nome,
      nome: luogo.nome,
      tipo: luogo.tipo,
      zona: luogo.zona,
      indirizzo: luogo.indirizzo,
      lat: luogo.lat,
      lon: luogo.lon,
      distanza_m: luogo.distanza_m,
      orari_testo: luogo.orari_testo,
      orari_nota: luogo.orari_nota,
      aperto_adesso: luogo.aperto_adesso,
      fonte: luogo.fonte,
      fiducia: luogo.fiducia,
      data_aggiornamento: luogo.data_aggiornamento,
      url: luogo.url,
      badge: luogo.badge,
      mia: Boolean(luogo.della_mia_casa)
    };
  }

  function vociDaPoi(poi) {
    return {
      chiave: "osm:" + poi.osm_tipo + ":" + poi.osm_id,
      livello: "esterna",
      provenienza: "esterna",
      /* L'identificativo del biglietto per un POI: `osm:<tipo>:<id>`, la forma che `/op/biglietto`
       * accetta per un luogo che non è in memoria (V4: la stampa non lo promuove). */
      id: null,
      osmId: poi.osm_id,
      osmTipo: poi.osm_tipo,
      riferimento: "osm:" + poi.osm_tipo + ":" + poi.osm_id,
      casaId: null,
      nome: poi.nome,
      tipo: poi.tipo,
      zona: null,
      indirizzo: poi.indirizzo,
      lat: poi.lat,
      lon: poi.lon,
      distanza_m: poi.distanza_m,
      orari_testo: poi.orari_testo,
      orari_nota: poi.orari_nota,
      aperto_adesso: poi.aperto_adesso,
      fonte: poi.fonte,
      fiducia: poi.fiducia,
      data_aggiornamento: null,
      url: poi.url,
      badge: poi.badge,
      mia: false
    };
  }

  /* ------------------------------------------------------------------ POI esterni */

  /* Una interrogazione per **tutti** i tipi accesi, sul riquadro visibile: è il punto di
   * `T-SHIM-05`, e la ragione per cui questo endpoint esiste invece di N chiamate a `vicino_a`.
   * La bbox è quella che l'operatore vede — non una zona, non la Casa. */
  function caricaEsterni() {
    if (!mappa) { return Promise.resolve(); }
    var tipi = tipiAccesi();
    if (!tipi.length) {
      stato.esterni = [];
      stato.perChiave = {};
      tutte().forEach(function (voce) { stato.perChiave[voce.chiave] = voce; });
      applica();
      return Promise.resolve();
    }
    var limiti = mappa.getBounds();
    var bbox = [limiti.getWest(), limiti.getSouth(), limiti.getEast(), limiti.getNorth()]
      .map(function (valore) { return valore.toFixed(6); }).join(",");
    var parametri = new URLSearchParams();
    parametri.set("bbox", bbox);
    tipi.forEach(function (tipo) { parametri.append("tipi", tipo); });
    if (stato.filtri.aperto) { parametri.set("aperto_adesso", "true"); }

    return window.Trasi.api("/op/poi?" + parametri.toString()).then(function (dati) {
      stato.esterni = (dati.poi || []).map(vociDaPoi);
      stato.perChiave = {};
      tutte().forEach(function (voce) { stato.perChiave[voce.chiave] = voce; });
      dichiaraFonti(dati.fonti_esterne || []);
      applica();
    }).catch(function () {
      /* La fonte esterna che non risponde **non** è un guasto della pagina: l'elenco resta con la
       * memoria della rete, e la riga dichiara lo stato (§4.2.1). */
      stato.esterni = [];
      stato.perChiave = {};
      tutte().forEach(function (voce) { stato.perChiave[voce.chiave] = voce; });
      dichiaraFonti([{ fonte: "OpenStreetMap", stato: "errore", ms: 0 }]);
      applica();
    });
  }

  function tipiAccesi() {
    return Object.keys(stato.filtri.tipi).filter(function (tipo) { return stato.filtri.tipi[tipo]; });
  }

  /* La riga dichiara lo stato della fonte esterna **in parole**, dal dato `fonti_esterne[].stato`:
   * «OpenStreetMap ha risposto in 1,2 s» oppure «non ha risposto: l'elenco mostra solo la memoria
   * della rete». Mai un'eccezione al chiamante, e mai un silenzio. */
  var STATI_FONTE = {
    ok: function (fonte, ms) { return "Fonti esterne: " + fonte + " ha risposto in " + secondi(ms) + " s."; },
    timeout: function (fonte) { return "Fonti esterne: " + fonte + " non ha risposto entro il tempo dichiarato; l'elenco mostra solo la memoria della rete."; },
    errore: function (fonte) { return "Fonti esterne: " + fonte + " ha dato un errore; l'elenco mostra solo la memoria della rete."; },
    scartata_fiducia: function (fonte) { return "Fonti esterne: " + fonte + " non è stata usata (livello di fiducia sotto la soglia della rete); l'elenco mostra solo la memoria della rete."; }
  };

  function secondi(ms) {
    return (ms / 1000).toFixed(1).replace(".", ",");
  }

  function dichiaraFonti(fonti) {
    var riga = document.getElementById("mappa-sfondo");
    if (!riga || !fonti.length) { return; }
    var pezzi = fonti.map(function (fonte) {
      var componi = STATI_FONTE[fonte.stato] || STATI_FONTE.errore;
      return componi(fonte.fonte, fonte.ms);
    });
    riga.textContent = pezzi.join(" ");
    riga.hidden = false;
  }

  /* ------------------------------------------------------------------ etichette dei filtri */

  /* I conteggi delle caselle sono i numeri **veri**, non quelli scritti nell'HTML: le case e i
   * luoghi arrivano dal database, e un «(22)» fisso mentirebbe il giorno in cui un luogo viene
   * chiuso. Il testo delle etichette si riscrive qui, una volta, con i numeri letti. */
  function aggiornaEtichette() {
    var case1 = document.querySelector('label[for="filtro-case"]');
    if (case1) { case1.textContent = "Case della rete (" + stato.case.length + ")"; }
    var luoghi = document.querySelector('label[for="filtro-luoghi"]');
    if (luoghi) { luoghi.textContent = "Luoghi della rete (" + stato.luoghi.length + ")"; }
  }

  /* ------------------------------------------------------------------ il pannello contestuale
   *
   * §4 del contratto: in Osservatorio il pannello dichiara l'assistente. La chat **è Onyx**:
   * il collegamento apre `onyx.lascuolaopensource.org/app?agentId=2` («Trasi Casa») in una
   * scheda nuova — non c'è una chat compatta da replicare, e la conversazione corrente vive
   * dove vive Onyx, non in una copia qui.
   */
  function montaPannello() {
    window.Trasi.montaPannello(
      '<div class="pannello-testa">' +
        '<a class="azione" href="https://onyx.lascuolaopensource.org/app?agentId=2" ' +
        'target="_blank" rel="noopener">Apri l&apos;assistente</a>' +
      '</div>' +
      '<div class="pannello-corpo">' +
        '<p class="pannello-nota">L&apos;assistente Trasi Casa apre in una scheda nuova.</p>' +
      '</div>'
    );
  }

  /* ------------------------------------------------------------------ avvio */

  window.TrasiMappa = {
    stato: stato,
    /* L'elenco (e la scheda) chiedono la selezione qui: un solo posto decide cosa è scelto. */
    seleziona: seleziona,
    applica: applica,
    caricaEsterni: caricaEsterni,
    ricarica: function () { return carica().then(caricaEsterni); }
  };

  function avvia() {
    if (!window.Trasi || !window.Trasi.pronto) {
      errore(DATI_NON_DISPONIBILI);
      return;
    }
    window.Trasi.pronto.then(function (sessione) {
      /* Senza sessione si torna all'accesso: `shell.js` lo fa già, e qui non si disegna una mappa
       * vuota per un operatore che non è entrato. */
      if (!sessione) { return; }
      return carica().then(function () {
        var casella = document.getElementById("filtro-esterni");
        if (casella) {
          casella.addEventListener("change", function () {
            stato.filtri.esterna = casella.checked;
            if (casella.checked) { caricaEsterni(); } else { applica(); }
          });
        }
        var aperto = document.getElementById("filtro-aperto");
        if (aperto) {
          aperto.addEventListener("change", function () {
            stato.filtri.aperto = aperto.checked;
            /* Il filtro «solo aperti adesso» cambia **cosa si chiede** a Overpass, oltre a cosa si
             * mostra: chiedere gli aperti e scartarli poi sarebbe una risposta in più per nulla. */
            if (stato.filtri.esterna) { caricaEsterni(); } else { applica(); }
          });
        }
        ["casa", "luogo"].forEach(function (livello) {
          var el = document.getElementById("filtro-" + livello);
          if (el) {
            el.addEventListener("change", function () {
              stato.filtri[livello] = el.checked;
              applica();
            });
          }
        });
      });
    }).catch(function (e) {
      var riga = document.getElementById("mappa-conteggio");
      if (riga) { riga.textContent = ""; }
      errore(DATI_NON_DISPONIBILI);
      if (e && e.sessioneScaduta) { location.href = "index.html"; }
    }).then(function () {
      var contenitore = document.getElementById("mappa");
      if (contenitore) { contenitore.setAttribute("aria-busy", "false"); }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", avvia);
  } else {
    avvia();
  }
})();
