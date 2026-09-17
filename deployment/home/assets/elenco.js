/* elenco.js — l'elenco equivalente da tastiera: le stesse voci della mappa, nello stesso ordine.
 *
 * **Perché esiste, e perché non è un'aggiunta di accessibilità.** La mappa Leaflet è un canvas con
 * dei segni sopra: da tastiera non è navigabile, e un lettore di schermo non ha nulla da leggere.
 * L'elenco è l'**equivalente funzionale** — stessa informazione, stesso ordine (distanza), stessa
 * azione (aprire la scheda) — e il criterio di done non è «l'elenco esiste», è «*tutte* le
 * informazioni della mappa sono raggiungibili e usabili da tastiera attraverso l'elenco»
 * (WCAG 2.1 AA 2.1.1, 1.1.1).
 *
 * **La selezione è sincronizzata nei due sensi** (§4.2.1), ed è la parte che si dimentica:
 *
 *   elenco → mappa: `Invio` (o click) su una voce. La voce prende `aria-expanded="true"`, il pin
 *                   corrispondente riceve la classe di evidenza e la mappa ci si sposta sopra.
 *   mappa → elenco: click sul pin. La voce corrispondente riceve `aria-expanded="true"` e il
 *                   **focus** (`document.activeElement` è la voce, come chiede il criterio).
 *
 * Le voci sono `<button>`, non `<a>` né `<li>` cliccabili: aprono un pannello nella stessa pagina,
 * non portano altrove, e un bottone è ciò che un lettore di schermo annuncia come azionabile.
 */
(function () {
  "use strict";

  var elenco = null;
  var vuoto = null;
  var conteggio = null;
  var tipiCostruiti = false;

  /* ------------------------------------------------------------------ i tipi dei POI
   *
   * Il vocabolario dei tipi è **dello shim** (`poi_op.TIPI_MAPPA`): la pagina ne costruisce le
   * caselle da lì invece di tenere una seconda lista che divergerebbe alla prima aggiunta. Le
   * etichette sono in parole, al singolare e al plurale, perché sono caselle da leggere.
   */
  var ETICHETTE_TIPI = {
    bar: "Bar",
    farmacia: "Farmacie",
    scuola: "Scuole",
    fermata: "Fermate",
    caf: "CAF",
    poste: "Poste",
    medico: "Medici",
    ospedale: "Ospedali",
    supermercato: "Supermercati",
    biblioteca: "Biblioteche",
    parco: "Parchi",
    banca: "Banche",
    comune: "Comuni"
  };

  /* I tipi che la pagina offre: sono i più utili allo sportello (US-01, US-08, §9.3), non tutti e
   * tredici — e ogni casella accesa è una interrogazione a OpenStreetMap, quindi l'elenco corto è
   * anche la scelta che tiene basso il numero di chiamate. */
  var TIPI_OFFERTI = ["bar", "farmacia", "scuola", "fermata", "caf"];

  function costruisciTipi(stato) {
    if (tipiCostruiti) { return; }
    var contenitore = document.getElementById("mappa-tipi-esterni");
    if (!contenitore) { return; }
    TIPI_OFFERTI.forEach(function (tipo) {
      /* Spente all'avvio: l'operatore accende ciò che cerca, e la prima interrogazione a Overpass
       * parte solo quando ha senso. */
      stato.filtri.tipi[tipo] = false;
      var etichetta = document.createElement("label");
      etichetta.setAttribute("for", "tipo-" + tipo);
      etichetta.textContent = ETICHETTE_TIPI[tipo] || tipo;
      var casella = document.createElement("input");
      casella.type = "checkbox";
      casella.id = "tipo-" + tipo;
      casella.checked = false;
      casella.addEventListener("change", function () {
        stato.filtri.tipi[tipo] = casella.checked;
        /* Accendere un tipo accende il livello esterno: sono la stessa decisione, e chiedere due
         * click per una cosa sola è una trappola. */
        if (casella.checked) {
          var esterni = document.getElementById("filtro-esterni");
          if (esterni && !esterni.checked) { esterni.checked = true; }
          stato.filtri.esterna = true;
        }
        window.TrasiMappa.caricaEsterni();
      });
      var guscio = document.createElement("span");
      guscio.className = "mappa-filtro";
      guscio.appendChild(casella);
      guscio.appendChild(etichetta);
      contenitore.appendChild(guscio);
    });
    tipiCostruiti = true;
  }

  /* ------------------------------------------------------------------ la voce */

  /* Il segno di ciascun livello, lo **stesso** della mappa e della legenda: la voce è la forma in
   * parole del pin, e chi legge l'elenco deve poter ritrovare il segno sulla mappa. */
  var SEGNI = { casa: "■", luogo: "●", esterna: "○" };

  function metri(valore) {
    if (valore === null || valore === undefined) { return ""; }
    if (valore < 1000) { return Math.round(valore) + " m"; }
    return (valore / 1000).toFixed(1).replace(".", ",") + " km";
  }

  /* «aperto adesso» in parole, con il terzo stato dichiarato: `null` significa «non lo sappiamo»,
   * e dirlo è diverso dal dire «chiuso» — la copertura degli orari è parziale, e trattare il
   * silenzio come una chiusura nasconderebbe la maggioranza dei POI reali. */
  function statoApertura(voce) {
    if (voce.aperto_adesso === true) { return "aperto adesso"; }
    if (voce.aperto_adesso === false) { return "chiuso adesso"; }
    return voce.orari_nota || "orari non disponibili";
  }

  function etichettaTipo(voce) {
    if (voce.livello === "casa") { return "Casa della rete"; }
    if (voce.livello === "esterna") { return "trovato su OpenStreetMap"; }
    return "luogo della rete";
  }

  function creaVoce(voce) {
    var bottone = document.createElement("button");
    bottone.type = "button";
    bottone.className = "mappa-voce";
    bottone.setAttribute("aria-expanded", "false");
    bottone.dataset.chiave = voce.chiave;
    /* Il nome del luogo è nel testo del bottone: un `aria-label` che lo ripetesse sarebbe una
     * seconda copia da tenere allineata, e il testo è già la descrizione giusta. */
    bottone.appendChild(rigaVoce(voce));
    return bottone;
  }

  function rigaVoce(voce) {
    var contenitore = document.createElement("span");

    var testa = document.createElement("span");
    testa.className = "mappa-voce-testa";
    var segno = document.createElement("span");
    segno.className = "mappa-voce-segno mappa-pin--" + voce.livello;
    /* Il segno è decorativo: la parola accanto («Casa della rete») è ciò che porta il significato. */
    segno.setAttribute("aria-hidden", "true");
    segno.textContent = SEGNI[voce.livello];
    var nome = document.createElement("span");
    nome.className = "mappa-voce-nome";
    nome.textContent = voce.nome;
    testa.appendChild(segno);
    testa.appendChild(nome);

    /* Un luogo senza coordinate non ha un pin sulla mappa (P1.2): l'elenco lo dice a parole, al posto
     * della distanza che non si può calcolare. È l'equivalente funzionale che promette la pagina. */
    var senzaPosizione = voce.lat === null || voce.lat === undefined || voce.lon === null || voce.lon === undefined;
    var riga = document.createElement("span");
    riga.className = "mappa-voce-riga";
    [etichettaTipo(voce), voce.zona, voce.indirizzo,
     senzaPosizione ? "posizione non disponibile" : metri(voce.distanza_m), statoApertura(voce)]
      .filter(function (pezzo) { return pezzo; })
      .forEach(function (pezzo) {
        var pezzo_el = document.createElement("span");
        pezzo_el.textContent = pezzo;
        riga.appendChild(pezzo_el);
      });

    var fonte = document.createElement("span");
    fonte.className = "mappa-voce-fonte etichetta " + (voce.livello === "esterna" ? "etichetta--esterna" : "etichetta--kb");
    /* Badge **verbatim** dallo shim (V3): si scrive com'è, non si ricompone né si riformatta. */
    fonte.textContent = voce.badge;

    contenitore.appendChild(testa);
    contenitore.appendChild(riga);
    contenitore.appendChild(fonte);
    return contenitore;
  }

  /* ------------------------------------------------------------------ il disegno */

  function disegna(voci, stato) {
    if (!elenco) { return; }
    elenco.textContent = "";
    voci.forEach(function (voce) {
      var bottone = creaVoce(voce);
      bottone.addEventListener("click", function () { scegli(voce.chiave); });
      elenco.appendChild(bottone);
    });
    /* La voce scelta è ancora in elenco? Se sì si riporta `aria-expanded`, perché il disegno l'ha
     * appena ricostruita: senza, una selezione sopravvissuta a un filtro perderebbe il suo segno. */
    if (stato && stato.scelta) {
      var scelta = elenco.querySelector('[data-chiave="' + CSS.escape(stato.scelta) + '"]');
      if (scelta) { scelta.setAttribute("aria-expanded", "true"); }
    }
    if (vuoto) { vuoto.hidden = voci.length > 0; }
    if (conteggio) {
      conteggio.textContent = voci.length === 0
        ? "Nessun luogo con i filtri attivi."
        : (voci.length === 1 ? "1 voce, dalla più vicina." : voci.length + " voci, dalla più vicina.");
    }
  }

  /* ------------------------------------------------------------------ selezione */

  function scegli(chiave, centra) {
    window.TrasiMappa.seleziona(chiave, centra !== false);
    segnaScelta(chiave);
    window.TrasiScheda.apri(chiave);
  }

  function segnaScelta(chiave) {
    if (!elenco) { return; }
    var voci = elenco.querySelectorAll(".mappa-voce");
    for (var i = 0; i < voci.length; i++) {
      voci[i].setAttribute("aria-expanded", voci[i].dataset.chiave === chiave ? "true" : "false");
    }
  }

  /* Il verso **mappa → elenco**: il click sul pin chiama questa dal modulo della mappa. Il focus
   * va sulla voce, come chiede il criterio osservabile di §4.2.1 — così chi usa la tastiera
   * ritrova il punto da cui continuare, e chi usa il mouse vede la voce evidenziata. */
  function scegliDaMappa(chiave) {
    var voce = elenco ? elenco.querySelector('[data-chiave="' + CSS.escape(chiave) + '"]') : null;
    if (voce) { voce.focus(); }
    scegli(chiave, false);
  }

  /* Il focus torna a una voce dell'elenco: lo chiama la scheda quando si chiude (Esc o «Torna
   * all'elenco»). `chiave` può essere `null` se la voce non esiste più — allora il focus va alla
   * prima voce, che è il punto di ripresa naturale. */
  function tornaAllaVoce(chiave) {
    if (!elenco) { return; }
    var voce = chiave ? elenco.querySelector('[data-chiave="' + CSS.escape(chiave) + '"]') : null;
    if (!voce) { voce = elenco.querySelector(".mappa-voce"); }
    if (voce) { voce.focus(); }
  }

  function deseleziona() {
    segnaScelta(null);
  }

  /* ------------------------------------------------------------------ avvio */

  window.TrasiElenco = {
    disegna: disegna,
    scegliDaMappa: scegliDaMappa,
    tornaAllaVoce: tornaAllaVoce,
    deseleziona: deseleziona
  };

  function avvia() {
    elenco = document.getElementById("mappa-elenco");
    vuoto = document.getElementById("mappa-vuoto");
    conteggio = document.getElementById("mappa-elenco-conteggio");
    costruisciTipi(window.TrasiMappa.stato);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", avvia);
  } else {
    avvia();
  }
})();
