/* grafici.js — i sei grafici della sezione «Numeri» dell'Account (§4.3.1 del piano).
 *
 * CARICATO DA `account.js` quando la sezione `#numeri` entra in `#acc-vista`: il frammento è solo
 * markup (`innerHTML` non esegue `<script>`), quindi il comportamento vive qui. L'API è una sola:
 * `window.TrasiAccount.monta(radice)` al montaggio, `window.TrasiAccount.smonta()` all'uscita.
 *
 * ---------------------------------------------------------------------------
 * Le tre regole di resa che questo modulo esiste per rispettare
 * ---------------------------------------------------------------------------
 * 1. **La barra è decorativa, il numero sta nel testo.** Ogni grafico è una `<table>` del design
 *    system: l'etichetta in `<th scope="row">`, la barra in una cella, il valore in un'altra. La
 *    tabella è **visibile**, non una copia nascosta per i lettori di schermo: una tabella `sr-only`
 *    accanto a un disegno è la stessa informazione scritta due volte, e la seconda copia prima o poi
 *    diverge dalla prima. L'SVG porta `aria-hidden="true"` e `focusable="false"`, non contiene
 *    **nessun** `<text>`, e quindi non contiene nessun numero: il criterio «il numero sotto soglia
 *    non deve mai comparire nel sorgente dell'SVG» (`T-UX-13`) è rispettato per costruzione, non
 *    perché qualcuno si ricordi di mascherarlo.
 *
 * 2. **Il numero da disegnare è `valore_label`, e nient'altro.** Questo modulo non legge **mai**
 *    `valore`: quella colonna è `null` esattamente quando la soglia di riservatezza scatta, quindi
 *    usarla significherebbe leggere `null` dove serve «<5» e — se un giorno la soglia cambiasse —
 *    disegnare un numero che il database ha deciso di non far uscire. Il confronto con la soglia non
 *    avviene qui: avviene in `trasi.k_anon()` (`db/004_views.sql`), dentro il database, e questo
 *    modulo riceve il risultato già mascherato.
 *
 * 3. **Dove non ci sono dati si legge il vuoto, non un grafico a zero.** Su questo database
 *    l'attrezzoteca ha zero oggetti e le schede di servizio zero righe: un grafico a zero direbbe
 *    «misurato, ed è zero», il vuoto dichiarato dice «non c'è niente da misurare». Sono due fatti
 *    diversi, e la frase che li distingue la scrive il database (`vuoto_testo`), non questa pagina.
 *
 * ---------------------------------------------------------------------------
 * Perché la scala delle barre si calcola dai soli valori noti
 * ---------------------------------------------------------------------------
 * La larghezza di una barra è `valore / massimo`. Il massimo si prende **solo** fra i valori noti:
 * quando una riga è sotto soglia il suo numero non esiste nel browser, quindi non può entrare in un
 * massimo, e una riga mascherata riceve una barra a tratteggio di lunghezza minima — che dice «piccola,
 * e non mostrata» senza affermare una quantità. Se **tutte** le righe sono mascherate non c'è scala:
 * le barre restano a lunghezza minima e la tabella, che è la forma vera del grafico, resta leggibile.
 *
 * Nessuna libreria, nessun CDN, nessun colore che porti significato: la barra eredita il colore del
 * testo (`currentColor`) e la veste la ridipinge senza toccare questo file (D9).
 */
(function () {
  "use strict";

  var BASE = "/api/shim";

  /* Larghezza del disegno: un `viewBox` di 100 unità con `preserveAspectRatio="none"`, così la barra
     si adatta alla cella e la proporzione resta quella del dato. Il tratteggio non si deforma grazie a
     `vector-effect="non-scaling-stroke"`. */
  var LARGHEZZA = 100;
  var ALTEZZA_BARRA = 10;

  /* Lunghezza minima di una barra **mascherata**: dice «c'è una riga, la quantità non si mostra».
     È l'unico valore disegnato senza un dato dietro, e vale solo per le righe sotto soglia — dove il
     lettore sa già, dall'etichetta `<5`, che la quantità è piccola. */
  var LARGHEZZA_MINIMA = 3;

  /* Tetto alla scala: con un massimo molto più grande degli altri, le barre piccole diventano
     invisibili. Si tengono visibili con una soglia di leggibilità del 2% della larghezza. */
  var LARGHEZZA_LEGGIBILE = 2;

  var URL_SVG = "http://www.w3.org/2000/svg";

  /* ---------------------------------------------------------------- utilità */

  function elemento(tag, classe) {
    var nodo = document.createElement(tag);
    if (classe) nodo.className = classe;
    return nodo;
  }

  function testo(nodo, valore) {
    nodo.textContent = valore == null || valore === "" ? "—" : String(valore);
    return nodo;
  }

  /* Il numero di una riga, nella sua forma **mostrabile**: `valore_label` dal database. La funzione
     non ha un ramo che legga `valore` — è deliberato: quello che non si legge non può sfuggire. */
  function etichettaQuantita(riga) {
    return riga.valore_label == null ? "—" : String(riga.valore_label);
  }

  /* ---------------------------------------------------------------- barra */

  /* La barra: un `<rect>` dentro un SVG senza testo. Riceve `aria-hidden` perché il suo contenuto
     informativo sta nella cella accanto, che un lettore di schermo legge davvero. */
  function barra(riga, massimo) {
    var svg = document.createElementNS(URL_SVG, "svg");
    svg.setAttribute("class", "acc-numeri-barra");
    svg.setAttribute("viewBox", "0 0 " + LARGHEZZA + " " + ALTEZZA_BARRA);
    svg.setAttribute("preserveAspectRatio", "none");
    svg.setAttribute("aria-hidden", "true");
    svg.setAttribute("focusable", "false");
    svg.setAttribute("height", String(ALTEZZA_BARRA));

    var valore = riga.valore;
    var mascherata = riga.valore_label != null && String(riga.valore_label).indexOf("<") === 0;

    /* Zero: nessun rettangolo. Una barra di lunghezza zero e una barra assente sono la stessa cosa
       per chi legge, e omettere l'elemento toglie un nodo dal DOM per ogni categoria vuota. */
    if (valore === 0) return svg;

    var larghezza;
    if (mascherata || valore == null || !massimo) {
      larghezza = LARGHEZZA_MINIMA;
    } else {
      larghezza = Math.max((valore / massimo) * LARGHEZZA, LARGHEZZA_LEGGIBILE);
    }

    var rect = document.createElementNS(URL_SVG, "rect");
    rect.setAttribute("x", "0");
    rect.setAttribute("y", "0");
    rect.setAttribute("width", String(larghezza));
    rect.setAttribute("height", String(ALTEZZA_BARRA));
    rect.setAttribute("fill", "currentColor");
    if (mascherata) {
      /* Secondo canale, oltre alla lunghezza: il tratteggio dice «non mostrata» anche a chi non
         distingue le lunghezze. Stesso espediente dell'etichetta esterna, che è tratteggiata. */
      rect.setAttribute("fill", "none");
      rect.setAttribute("stroke", "currentColor");
      rect.setAttribute("stroke-dasharray", "3 2");
      rect.setAttribute("vector-effect", "non-scaling-stroke");
    }
    svg.appendChild(rect);
    return svg;
  }

  /* ---------------------------------------------------------------- tabella */

  function tabella(blocco, id) {
    var t = elemento("table", "tabella acc-numeri-tabella");
    t.id = id;

    /* Il `<caption>` dichiara **cosa** si sta guardando, e per le serie ordinate anche l'ordine:
       «ordinamento dichiarato» è una regola del piano, e una tabella senza caption lo lascerebbe
       dedurre dalla sequenza delle righe. */
    var caption = elemento("caption");
    caption.textContent = blocco.titolo + " — " + (ORDINI[blocco.id] || "");
    t.appendChild(caption);

    var testa = elemento("thead");
    var rigaTesta = elemento("tr");
    ["Voce", "Barra", "Valore"].forEach(function (voce, indice) {
      var th = elemento("th");
      th.setAttribute("scope", "col");
      th.textContent = voce;
      /* L'intestazione della colonna della barra è utile a chi vede la tabella, ma la colonna è
         decorativa: si toglie dal calcolo del nome accessibile della cella, non dal documento. */
      if (indice === 1) th.setAttribute("aria-hidden", "true");
      rigaTesta.appendChild(th);
    });
    testa.appendChild(rigaTesta);
    t.appendChild(testa);

    var corpo = elemento("tbody");
    blocco.righe.forEach(function (riga) {
      corpo.appendChild(rigaTabella(riga, blocco));
    });
    t.appendChild(corpo);
    return t;
  }

  function rigaTabella(riga, blocco) {
    var tr = elemento("tr");

    /* L'etichetta è l'intestazione **di riga**: un lettore di schermo annuncia «orientamento: …»
       invece di leggere due celle sciolte. */
    var th = elemento("th");
    th.setAttribute("scope", "row");
    th.textContent = riga.etichetta;
    tr.appendChild(th);

    if (riga.tipo_riga === "voce") {
      /* Una voce nominata (un prossimo evento) non è una quantità: non ha barra e non ha valore.
         Il dettaglio — data e luogo — sta nella cella del valore, che per le voci è testo. */
      var vuota = elemento("td");
      vuota.setAttribute("aria-hidden", "true");
      tr.appendChild(vuota);
      tr.appendChild(testo(elemento("td", "acc-numeri-nota-riga"), riga.nota_riga));
      return tr;
    }

    var cellaBarra = elemento("td", "acc-numeri-cella-barra");
    cellaBarra.appendChild(barra(riga, massimoDelBlocco(blocco)));
    tr.appendChild(cellaBarra);

    var cellaValore = elemento("td", "acc-numeri-cella-valore");
    cellaValore.textContent = etichettaQuantita(riga);
    if (riga.sotto_soglia) {
      /* La classe è un aggancio per la veste (che può dare al `<5` un peso diverso), mai un colore
         che porti da solo il significato: la parola «<5» è già nel testo. */
      cellaValore.className += " acc-numeri-sotto-soglia";
    }
    tr.appendChild(cellaValore);
    return tr;
  }

  /* Il massimo **dei valori noti** del blocco: vedi la nota in testa al modulo. `0` quando nessuno è
     noto, e in quel caso ogni barra resta alla lunghezza minima. */
  function massimoDelBlocco(blocco) {
    var massimo = 0;
    blocco.righe.forEach(function (riga) {
      if (riga.tipo_riga === "conteggio" && typeof riga.valore === "number" && riga.valore > massimo) {
        massimo = riga.valore;
      }
    });
    return massimo;
  }

  /* ---------------------------------------------------------------- ordini */

  /* L'ordine di ogni serie, in parole. Sta qui e non nel `<caption>` del frammento per una ragione
     sola: il titolo del blocco arriva dal database (`fn_statistiche_casa`), e tenere titolo e ordine
     nello stesso posto evita che il primo cambi e il secondo resti indietro. */
  var ORDINI = {
    richieste_categoria: "in ordine dalla categoria più frequente; il totale in testa",
    esito: "nell'ordine degli esiti previsti dal registro, anche quando non ce ne sono",
    destinazioni: "in ordine dalla destinazione più frequente",
    eventi: "il conteggio, poi i tre eventi più vicini nel tempo",
    scadenze_proposte: "prima le schede in scadenza, poi le proposte in attesa",
    attrezzoteca: "in ordine dall'oggetto più usato"
  };

  /* ---------------------------------------------------------------- disegno */

  function disegna(blocco, contenitore) {
    contenitore.textContent = "";

    /* Il badge di provenienza (V3) e la data di aggiornamento: la stessa etichetta verbatim di ogni
       altra informazione della shell, sotto il grafico a cui si riferisce. */
    if (blocco.badge) {
      var provenienza = elemento("p", "etichetta etichetta--kb");
      provenienza.textContent = blocco.badge;
      contenitore.appendChild(provenienza);
    }

    if (blocco.vuoto && blocco.righe.length === 0) {
      /* Vuoto **senza righe**: non si disegna nulla, si dichiara. La frase è del database. */
      var vuoto = elemento("p", "vuoto");
      vuoto.textContent = blocco.nota_vuoto || "Nessun dato nel periodo scelto.";
      contenitore.appendChild(vuoto);
      return;
    }

    contenitore.appendChild(tabella(blocco, "acc-numeri-tabella-" + blocco.id));

    if (blocco.vuoto) {
      /* Vuoto **con righe tutte a zero** (destinazioni senza indirizzamenti, attrezzoteca con oggetti
         e nessun movimento): le righe si mostrano — ognuna con il suo `—` — e accanto si dichiara che
         non c'è nulla da contare. Nascondere le righe a zero direbbe «categoria non prevista». */
      var notaZero = elemento("p", "vuoto");
      notaZero.textContent = blocco.nota_vuoto || "Nessun dato nel periodo scelto.";
      contenitore.appendChild(notaZero);
    }
  }

  /* ---------------------------------------------------------------- sezione */

  var caricaInCorso = 0;

  function slugDaId(id) {
    /* Gli id del frammento sono prefissati `acc-numeri-…` (contratto §5.3), e il suffisso è l'id del
       blocco che la funzione SQL restituisce: due bot diversi non possono generare lo stesso id. */
    return "acc-numeri-" + id;
  }

  function dataISO(d) {
    var mese = String(d.getMonth() + 1).padStart(2, "0");
    var giorno = String(d.getDate()).padStart(2, "0");
    return d.getFullYear() + "-" + mese + "-" + giorno;
  }

  function dataItaliana(iso) {
    var parti = String(iso).split("-");
    return parti.length === 3 ? parti[2] + "/" + parti[1] + "/" + parti[0] : iso;
  }

  function stato(testo, occupato) {
    var nodo = document.getElementById("acc-numeri-stato");
    if (!nodo) return;
    nodo.hidden = !testo;
    nodo.textContent = testo || "";
    nodo.setAttribute("aria-busy", occupato ? "true" : "false");
  }

  function errore(testo) {
    var nodo = document.getElementById("acc-numeri-errore");
    if (!nodo) return;
    nodo.hidden = !testo;
    nodo.textContent = testo || "";
  }

  function impostaPeriodo(dal, al) {
    var campoDal = document.getElementById("acc-numeri-dal");
    var campoAl = document.getElementById("acc-numeri-al");
    if (campoDal) campoDal.value = dal;
    if (campoAl) campoAl.value = al;
  }

  function segnaPeriodoScelto(giorni) {
    [[30, "acc-numeri-30"], [90, "acc-numeri-90"], [365, "acc-numeri-365"]].forEach(function (voce) {
      var bottone = document.getElementById(voce[1]);
      if (bottone) bottone.setAttribute("aria-pressed", voce[0] === giorni ? "true" : "false");
    });
  }

  /* Una risposta non OK diventa un errore leggibile; mai il corpo grezzo (V6: niente gergo). */
  function leggi(percorso) {
    return fetch(BASE + percorso, {
      headers: { Accept: "application/json" },
      credentials: "same-origin"
    }).then(function (risposta) {
      if (risposta.status === 401) {
        var scaduta = new Error("sessione assente o scaduta");
        scaduta.sessioneScaduta = true;
        throw scaduta;
      }
      if (!risposta.ok) {
        return risposta.json().catch(function () { return null; }).then(function (corpo) {
          var dettaglio = corpo && (corpo.dettaglio || corpo.detail);
          throw new Error(typeof dettaglio === "string" ? dettaglio : "errore " + risposta.status);
        });
      }
      return risposta.json();
    });
  }

  function carica(dal, al) {
    var attesa = ++caricaInCorso;
    errore("");
    stato("Lettura in corso…", true);

    return leggi("/op/casa/statistiche?dal=" + encodeURIComponent(dal) + "&al=" + encodeURIComponent(al))
      .then(function (dati) {
        /* Una risposta arrivata dopo una richiesta più recente si scarta: senza questo, cambiare
           periodo due volte in fretta lascerebbe i grafici del periodo precedente. */
        if (attesa !== caricaInCorso) return;
        stato("", false);
        mostraPeriodo(dati);
        mostraSoglia(dati.soglia_riservatezza);
        disegnaBlocchi(dati.blocchi || []);
      })
      .catch(function (e) {
        if (attesa !== caricaInCorso) return;
        stato("", false);
        if (e && e.sessioneScaduta) {
          /* Il 401 lo gestisce `shell.js` (torna all'accesso): qui si dichiara e basta, senza
             duplicare la navigazione. */
          errore("Sessione non più valida: la pagina di accesso è a un passo.");
          return;
        }
        /* Un 422 è una richiesta sbagliata e il `detail` dello shim lo dice in italiano; un 503 o una
           rete assente si dichiarano con il testo del contratto §3.4. */
        errore(
          e && e.message && e.message.indexOf("periodo") >= 0
            ? e.message
            : "Dati non disponibili: la memoria della rete non risponde in questo momento"
        );
      });
  }

  function mostraPeriodo(dati) {
    var nodo = document.getElementById("acc-numeri-periodo");
    if (!nodo || !dati.periodo) return;
    nodo.textContent =
      "Periodo letto: dal " + dataItaliana(dati.periodo.dal) + " al " + dataItaliana(dati.periodo.al) + ".";
  }

  /* La frase che spiega il simbolo, con la soglia **in vigore**: il numero viene da
     `[P] k_anonimato` letto dal database, quindi la frase segue la policy invece di duplicarla. */
  function mostraSoglia(soglia) {
    var nodo = document.getElementById("acc-numeri-nota-riservatezza");
    if (!nodo) return;
    nodo.textContent = soglia
      ? "Sotto " + soglia + " il numero non si mostra (riservatezza)."
      : "I conteggi molto bassi non si mostrano (riservatezza).";
  }

  function disegnaBlocchi(blocchi) {
    blocchi.forEach(function (blocco) {
      var contenitore = document.querySelector("#" + slugDaId(blocco.id) + " [data-grafico]");
      if (!contenitore) return;
      /* Il titolo del blocco arriva dal database: se divergesse da quello scritto nel frammento, la
         pagina mostrerebbe due nomi per la stessa cosa. Si tiene quello del database — è la fonte —
         e il frammento resta la struttura. */
      var intestazione = document.querySelector("#" + slugDaId(blocco.id) + " h3");
      if (intestazione && blocco.titolo) intestazione.textContent = blocco.titolo;
      disegna(blocco, contenitore);
    });
  }

  /* ---------------------------------------------------------------- filtro */

  function collegaFiltro() {
    function scegli(giorni) {
      var al = new Date();
      var dal = new Date(al.getTime());
      dal.setDate(dal.getDate() - giorni);
      segnaPeriodoScelto(giorni);
      impostaPeriodo(dataISO(dal), dataISO(al));
      carica(dataISO(dal), dataISO(al));
    }

    var scorciatoie = [[30, "acc-numeri-30"], [90, "acc-numeri-90"], [365, "acc-numeri-365"]];
    scorciatoie.forEach(function (voce) {
      var bottone = document.getElementById(voce[1]);
      if (bottone) {
        bottone.addEventListener("click", function () { scegli(voce[0]); });
      }
    });

    var modulo = document.getElementById("acc-numeri-filtro");
    if (modulo) {
      modulo.addEventListener("submit", function (evento) {
        evento.preventDefault();
        var dal = document.getElementById("acc-numeri-dal").value;
        var al = document.getElementById("acc-numeri-al").value;
        segnaPeriodoScelto(null);
        carica(dal, al);
      });
    }

    scegli(30);
  }

  /* ---------------------------------------------------------------- API */

  /* L'aggancio di `account.js` (contratto §5.4): la pagina chiama `avvii["numeri"](vista)` **dopo**
     aver inserito il frammento in `#acc-vista`. Questo modulo non registra ascoltatori su `document`
     o `window`: la sezione vive in un frammento che viene sostituito al cambio di sezione, e un
     ascoltatore globale resterebbe appeso a un nodo che non c'è più.
     `window.TrasiAccount` esiste già (lo crea `account.js`, che è caricato prima di questo file):
     `|| {}` è una difesa per il caso in cui il modulo venga caricato da solo in una pagina di prova. */
  window.TrasiAccount = window.TrasiAccount || { avvii: {} };
  window.TrasiAccount.avvii = window.TrasiAccount.avvii || {};
  window.TrasiAccount.avvii["numeri"] = function (vista) {
    if (!(vista || document.getElementById("acc-vista"))) return;
    collegaFiltro();
  };
})();
