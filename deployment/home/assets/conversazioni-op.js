/* conversazioni-op.js — il comportamento della sezione «Conversazioni» dell'Account.
 *
 * CARICATO DA `account.html`; `account.js` chiama `window.TrasiAccount.avvii["conversazioni"](vista)`
 * dopo aver inserito il frammento (contratto §5.4). Il frammento è solo markup.
 *
 * ---------------------------------------------------------------------------
 * La lista è per data, e la data è quella del primo turno
 * ---------------------------------------------------------------------------
 * `GET /op/conversazioni` (di BotHome) restituisce `{conversazioni: [{id, titolo, primo_ts,
 * ultimo_ts, turni}]}` ordinate dalla più recente. Il raggruppamento per giorno si fa **qui**, dal
 * dato che c'è (`primo_ts`), e non si chiede al server una seconda forma della stessa lista: la
 * pagina è l'unico posto in cui la data serve raggruppata.
 *
 * I gruppi sono in parole come nel pannello dello storico della Home (`OGGI` · `IERI` · …) e non in
 * date assolute: è la forma che il contratto §3.2 dichiara per lo storico, e le due liste mostrano
 * la stessa cosa. La data esatta resta scritta sotto ogni voce — un gruppo in parole che sostituisse
 * la data la nasconderebbe, e «ieri» da solo non dice quando.
 *
 * ---------------------------------------------------------------------------
 * L'apertura porta alla Home: `home.html?c=<id>`
 * ---------------------------------------------------------------------------
 * Non c'è una vista conversazione dentro l'Account, ed è deliberato: `home.html?c=<id>` esiste già,
 * è la forma condivisibile di una conversazione (§4.1.1, stato S5), e duplicarla qui significherebbe
 * due posti in cui correggere la chat.
 *
 * ---------------------------------------------------------------------------
 * Se l'endpoint non risponde, si dichiara — non si finge una lista vuota
 * ---------------------------------------------------------------------------
 * `GET /op/conversazioni` è di BotHome e può non essere ancora montato (allora risponde `404`).
 * Una lista vuota direbbe «nessuna conversazione negli ultimi 30 giorni», che è un'affermazione sul
 * mondo; il `404` non permette di affermarla. Quindi: stato «dati non disponibili» con il testo del
 * design system, e nessuna lista. Vale identicamente per un `503`.
 */
(function () {
  "use strict";

  var GIORNI = ["domenica", "lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato"];
  var MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
              "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"];

  function $(id) {
    return document.getElementById(id);
  }

  function mostra(nodo, testo) {
    if (!nodo) return;
    nodo.textContent = testo || "";
    nodo.hidden = !testo;
  }

  function chiama(percorso) {
    return fetch("/api/shim" + percorso, {
      headers: { Accept: "application/json" },
      credentials: "same-origin"
    }).then(function (risposta) {
      if (risposta.status === 401) {
        var scaduta = new Error("sessione assente o scaduta");
        scaduta.sessioneScaduta = true;
        throw scaduta;
      }
      if (!risposta.ok) {
        var e = new Error("errore " + risposta.status);
        e.stato = risposta.status;
        throw e;
      }
      return risposta.json();
    });
  }

  /* `primo_ts` è un istante ISO con il fuso (`2026-09-17T11:42:00+02:00`). Si legge la parte di data
     così com'è, senza passare da `Date`: la conversione a UTC sposterebbe le conversazioni della sera
     al giorno prima, e il gruppo «OGGI» mostrerebbe ieri. Il confronto è fra stringhe di data
     **locali**, che è il fuso in cui il turno è stato scritto. */
  function soloGiorno(iso) {
    return String(iso || "").slice(0, 10);
  }

  function giornoDi(iso) {
    var g = soloGiorno(iso).split("-");
    return g.length === 3 ? new Date(Number(g[0]), Number(g[1]) - 1, Number(g[2])) : null;
  }

  function oggiLocale() {
    var adesso = new Date();
    return new Date(adesso.getFullYear(), adesso.getMonth(), adesso.getDate());
  }

  function differenzaInGiorni(iso) {
    var giorno = giornoDi(iso);
    if (!giorno) return null;
    return Math.round((oggiLocale().getTime() - giorno.getTime()) / 86400000);
  }

  /* L'etichetta del gruppo: in parole per i giorni vicini, con la data per il resto. `IERI` e `OGGI`
     sono i due casi in cui la parola è più utile della data. */
  function etichettaGruppo(iso) {
    var giorni = differenzaInGiorni(iso);
    if (giorni === 0) return "OGGI";
    if (giorni === 1) return "IERI";
    if (giorni !== null && giorni > 1 && giorni < 7) return "ULTIMI 7 GIORNI";
    if (giorni !== null && giorni >= 7 && giorni < 30) return "ULTIMI 30 GIORNI";
    var giorno = giornoDi(iso);
    if (!giorno) return "DATA NON DISPONIBILE";
    return giorno.getDate() + " " + MESI[giorno.getMonth()] + " " + giorno.getFullYear();
  }

  /* La data estesa di una voce: `giovedì 17 settembre 2026, 11:42`. Il fuso si dichiara con l'ora
     locale del browser, che è quella della Casa. */
  function dataEstesa(iso) {
    var giorno = giornoDi(iso);
    if (!giorno) return "data non disponibile";
    var ora = String(iso).slice(11, 16);
    return GIORNI[giorno.getDay()] + " " + giorno.getDate() + " " + MESI[giorno.getMonth()] + " " +
           giorno.getFullYear() + (ora ? ", " + ora : "");
  }

  /* La retention è un parametro `[P]`, e la pagina non lo legge: non è esposto da nessun endpoint e
     inventarlo qui sarebbe peggio che tacerlo. La riga dichiara il fatto senza il numero, e il
     numero sta nella documentazione della Casa. */
  var NOTA_RETENTION = "Le conversazioni restano in memoria per un periodo limitato, poi sono cancellate.";

  function carica() {
    var elenco = $("acc-conversazioni-elenco");
    var stato = $("acc-conversazioni-stato");
    if (!elenco) return;

    elenco.textContent = "";
    mostra(stato, "Lettura in corso…");

    chiama("/op/conversazioni").then(function (dati) {
      var conversazioni = (dati && dati.conversazioni) || [];
      mostra(stato, "");
      if (!conversazioni.length) {
        /* Vuoto dichiarato, con il testo nuovo composto secondo le regole di contenuto (§3.4). */
        mostra(stato, "Nessuna conversazione negli ultimi 30 giorni.");
        return;
      }
      disegna(elenco, conversazioni);
    }).catch(function (e) {
      /* Un `404` significa che l'endpoint non è ancora montato; un `503` che la memoria non risponde.
         In entrambi i casi non si sa se ci sono conversazioni, e «nessuna» sarebbe falso. */
      mostra(
        stato,
        "Dati non disponibili: la memoria della rete non risponde in questo momento. " +
          "È un'informazione, non un guasto."
      );
    });
  }

  function disegna(elenco, conversazioni) {
    var gruppoCorrente = null;
    conversazioni.forEach(function (c) {
      var gruppo = etichettaGruppo(c.primo_ts);
      if (gruppo !== gruppoCorrente) {
        gruppoCorrente = gruppo;
        var intestazione = document.createElement("li");
        intestazione.className = "acc-conversazioni-giorno";
        intestazione.textContent = gruppo;
        /* L'intestazione di gruppo è un'etichetta, non una voce: `role="presentation"` la toglie
           dall'elenco annunciato, che resta una lista di conversazioni. */
        intestazione.setAttribute("role", "presentation");
        elenco.appendChild(intestazione);
      }
      elenco.appendChild(voce(c));
    });

    var nota = document.createElement("li");
    nota.className = "acc-conversazioni-nota";
    nota.setAttribute("role", "presentation");
    nota.textContent = NOTA_RETENTION;
    elenco.appendChild(nota);
  }

  function voce(c) {
    var li = document.createElement("li");
    li.className = "acc-conversazioni-voce filetto filetto--spento";

    /* L'apertura è un **collegamento**, non un bottone: `home.html?c=<id>` è un indirizzo, e un
       indirizzo si può aprire in una scheda nuova e condividere (§4.1.1, S5). */
    var apertura = document.createElement("a");
    apertura.className = "acc-conversazioni-apertura";
    apertura.href = "home.html?c=" + encodeURIComponent(c.id);
    apertura.textContent = c.titolo || "Conversazione senza titolo";
    li.appendChild(apertura);

    var quando = document.createElement("p");
    quando.className = "acc-conversazioni-quando";
    quando.textContent = dataEstesa(c.primo_ts) +
      (c.turni ? " · " + c.turni + (c.turni === 1 ? " turno" : " turni") : "");
    li.appendChild(quando);

    return li;
  }

  window.TrasiAccount = window.TrasiAccount || { avvii: {} };
  window.TrasiAccount.avvii = window.TrasiAccount.avvii || {};
  window.TrasiAccount.avvii["conversazioni"] = function () {
    carica();
  };
})();
