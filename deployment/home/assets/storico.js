/* storico.js — il pannello della sidebar in Home: le conversazioni della Casa, per data (§3.2, §4.1.2).
 *
 * Perché è un file suo e non una funzione di `chat.js`. `CONTRATTO-shell.md` §4 gli dà un proprietario
 * distinto (`storico.js`), e il confine ha un senso preciso: **questo modulo legge e chiede di aprire,
 * non disegna la conversazione.** Riempie `#shell-pannello`, dice a `chat.js` «apri questa» o «nuova»,
 * e non tocca mai i turni. Così l'Osservatorio potrà montare un pannello diverso senza che la chat
 * cambi, e questa è l'unica ragione per cui due file valgono la pena.
 *
 * Il raggruppamento è per **giorni locali** (`OGGI` · `IERI` · `ULTIMI 7 GIORNI` · `ULTIMI 30 GIORNI`),
 * e i confini si calcolano sulla mezzanotte locale, non su `24 * 3600 * 1000`. La differenza si vede
 * due volte l'anno, all'ora legale, quando un giorno dura 23 o 25 ore: sottrarre millisecondi
 * metterebbe un turno delle 00:30 di ieri nel gruppo di oggi — ed è il caso che il piano dice di
 * provare («alle 00:30 locali o con date a cavallo», T-UX-08).
 *
 * Il titolo della voce è quello salvato nella conversazione: lo shim lo compone dalla prima domanda
 * troncata a 40 caratteri (`db/021`, trigger). Qui non si tronca di nuovo — troncare una stringa già
 * troncata è come riformattare un'etichetta di provenienza: la seconda copia della regola è quella
 * che un giorno diverge dalla prima.
 */
(function () {
  "use strict";

  var LIMITE_ELENCO = 50;

  /* Le intestazioni dei gruppi, nell'ordine in cui compaiono. I nomi sono **verbatim** da §4.1.2. */
  var OGGI = "OGGI";
  var IERI = "IERI";
  var SETTE = "ULTIMI 7 GIORNI";
  var TRENTA = "ULTIMI 30 GIORNI";

  var PIEDE = "le conversazioni restano 30 giorni";
  var TESTO_VUOTO = "Nessuna conversazione negli ultimi 30 giorni.";
  var TESTO_ERRORE = "Dati non disponibili: la memoria della rete non risponde in questo momento";

  var lista = null;
  var corrente = null;

  function elemento(tag, classe, testo) {
    var el = document.createElement(tag);
    if (classe) el.className = classe;
    if (testo !== undefined && testo !== null) el.textContent = testo;
    return el;
  }

  /* L'inizio del giorno locale di una data, in millisecondi. `new Date(y, m, d)` costruisce la
     mezzanotte **locale**: sottrarre giorni con `setDate` attraversa l'ora legale in modo corretto,
     perché è il calendario a muoversi e non l'aritmetica dei millisecondi. */
  function mezzanotte(data) {
    return new Date(data.getFullYear(), data.getMonth(), data.getDate());
  }

  function giorniFa(quanti) {
    var d = new Date();
    d.setDate(d.getDate() - quanti);
    return mezzanotte(d);
  }

  /* Il gruppo di una conversazione, dalla data dell'**ultimo** turno: è l'ora che la voce mostra
     accanto al titolo, quindi è quella che deve decidere dove la voce compare. Raggruppare per il
     primo turno (che la Home mostra in testa quando si riapre) metterebbe una conversazione di
     lunedì nel gruppo di lunedì anche se l'ultima risposta è di stamattina — e l'elenco
     sembrerebbe sbagliato proprio a chi l'ha usato. */
  function gruppo(iso) {
    var quando = new Date(iso);
    if (isNaN(quando.getTime())) return TRENTA;
    var giorno = mezzanotte(quando);
    if (giorno.getTime() >= mezzanotte(new Date()).getTime()) return OGGI;
    if (giorno.getTime() >= giorniFa(1).getTime()) return IERI;
    if (giorno.getTime() >= giorniFa(7).getTime()) return SETTE;
    return TRENTA;
  }

  /* L'ora dell'ultimo turno, `HH:MM` nell'orologio del browser: è l'ora che l'operatore ha davanti,
     non quella del server. `it-IT` dà le 24 ore. */
  function ora(iso) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    return d.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
  }

  /* ---------------------------------------------------------------- il pannello */

  function monta() {
    /* Il pannello si monta **dall'interno**: `Trasi.montaPannello` scrive l'HTML del contenitore e
       `storico.js` lo riempie. È il contratto §4 — la pagina decide cosa c'è nel pannello, la shell
       solo dove. */
    if (!window.Trasi || !window.Trasi.montaPannello) return;
    window.Trasi.montaPannello(
      '<div class="pannello-testa">' +
        '<button class="bottone storico-nuova" type="button" id="storico-nuova">Nuova conversazione</button>' +
      '</div>' +
      '<div class="pannello-corpo">' +
        '<div id="storico-lista" class="storico-elenco" aria-label="Conversazioni"></div>' +
        '<p class="storico-piede">' + PIEDE + '</p>' +
      '</div>'
    );

    var bottone = document.getElementById("storico-nuova");
    if (bottone) {
      bottone.addEventListener("click", function () {
        /* «Nuova conversazione» non chiama lo shim: azzera lo stato della pagina. La conversazione
           nasce al primo invio — crearne una vuota qui lascerebbe in database una riga senza turni
           per ogni click, e riempirebbe la retention di conversazioni che non sono mai avvenute
           (§4.1.3: la conversazione esiste quando ha almeno una risposta). */
        corrente = null;
        if (window.TrasiChat) window.TrasiChat.nuova();
        segnaCorrente(null);
      });
    }

    lista = document.getElementById("storico-lista");
    ricarica();
  }

  function segnaCorrente(id) {
    corrente = id;
    if (!lista) return;
    var voci = lista.querySelectorAll(".storico-voce");
    for (var i = 0; i < voci.length; i++) {
      var suo = voci[i].getAttribute("data-conversazione");
      if (id !== null && String(id) === suo) voci[i].setAttribute("aria-current", "true");
      else voci[i].removeAttribute("aria-current");
    }
  }

  function voce(conversazione) {
    var bottone = elemento("button", "storico-voce");
    bottone.type = "button";
    bottone.setAttribute("data-conversazione", conversazione.id);
    /* Il titolo è quello dello shim, già troncato a 40 caratteri. Vuoto (una conversazione creata e
       mai usata) → una frase che dice il fatto, non una riga vuota su cui si può cliccare. */
    bottone.appendChild(elemento("span", "storico-titolo", conversazione.titolo || "Conversazione senza domanda"));
    bottone.appendChild(elemento("span", "storico-ora", ora(conversazione.ultimo_ts)));
    bottone.addEventListener("click", function () {
      segnaCorrente(conversazione.id);
      if (window.TrasiChat) window.TrasiChat.apri(conversazione.id);
      var url = new URL(window.location.href);
      url.searchParams.set("c", conversazione.id);
      window.history.replaceState(null, "", url.toString());
    });
    return bottone;
  }

  function disegna(conversazioni) {
    if (!lista) return;
    lista.textContent = "";

    if (!conversazioni.length) {
      lista.appendChild(elemento("p", "storico-vuoto", TESTO_VUOTO));
      return;
    }

    /* I quattro gruppi, **in ordine**: `OGGI` per primo, poi a scendere. Un gruppo senza voci non
       compare — un'intestazione sola con sotto il nulla dice che qualcosa è andato perso. */
    var ordine = [OGGI, IERI, SETTE, TRENTA];
    var per = {};
    conversazioni.forEach(function (c) {
      var nome = gruppo(c.ultimo_ts);
      (per[nome] = per[nome] || []).push(c);
    });

    ordine.forEach(function (nome) {
      if (!per[nome] || !per[nome].length) return;
      var gruppo_el = elemento("div", "storico-gruppo");
      gruppo_el.appendChild(elemento("p", "storico-gruppo-testa", nome));
      var ul = elemento("ul", "storico-voci");
      per[nome].forEach(function (c) {
        var li = elemento("li");
        li.appendChild(voce(c));
        ul.appendChild(li);
      });
      gruppo_el.appendChild(ul);
      lista.appendChild(gruppo_el);
    });

    segnaCorrente(corrente);
  }

  function ricarica() {
    if (!lista || !window.Trasi || !window.Trasi.api) return;
    return window.Trasi.api("/op/conversazioni?limite=" + LIMITE_ELENCO)
      .then(function (dati) { disegna(dati.conversazioni || []); })
      .catch(function (errore) {
        if (errore && errore.sessioneScaduta) return null;
        /* Un guasto dello storico non deve toccare la chat: la lista lo dichiara con il testo
           esistente (§7 del contratto), e il compositore resta usabile. */
        if (lista) {
          lista.textContent = "";
          lista.appendChild(elemento("p", "storico-vuoto", TESTO_ERRORE));
        }
        return null;
      });
  }

  window.TrasiStorico = { ricarica: ricarica, segnaCorrente: segnaCorrente, monta: monta };

  /* Il pannello si monta quando la sessione è risolta: `Trasi.pronto` si chiude quando `GET /me` è
     arrivato. Montarlo prima significherebbe una richiesta a `/op/conversazioni` senza sessione —
     cioè un 401 che `shell.js` leggerebbe come «torna all'accesso» appena entrati. */
  function avvia() {
    if (!window.Trasi || !window.Trasi.pronto) return;
    window.Trasi.pronto.then(function (esito) {
      if (!esito) return;   // nessuna sessione: `shell.js` sta già riportando all'accesso
      monta();
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", avvia);
  else avvia();
})();
