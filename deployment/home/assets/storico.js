/* storico.js — il pannello della sidebar in Home: le conversazioni della Casa, per data.
 *
 * La chat **è Onyx** (`home.html`): questo pannello non replica né disegna conversazioni —
 * è il registro di quelle che sono passate da Trasi (`trasi.conversazione`, retention 30
 * giorni), e ogni voce apre Onyx nella scheda nuova. Il pannello dichiara due azioni:
 *
 *   «Nuova conversazione» → apre Onyx con l'assistente «Trasi Casa» (`agentId=2`);
 *   una voce dell'elenco   → idem: Onyx è l'unico posto in cui una conversazione vive.
 *
 * Il raggruppamento è per **giorni locali** (`OGGI` · `IERI` · `ULTIMI 7 GIORNI` · `ULTIMI 30
 * GIORNI`), e i confini si calcolano sulla mezzanotte locale, non su `24 * 3600 * 1000`: la
 * differenza si vede due volte l'anno, all'ora legale, quando un giorno dura 23 o 25 ore.
 *
 * Il titolo della voce è quello salvato nella conversazione: lo shim lo compone dalla prima
 * domanda troncata a 40 caratteri (`db/021`, trigger). Qui non si tronca di nuovo.
 */
(function () {
  "use strict";

  var LIMITE_ELENCO = 50;

  /* L'assistente «Trasi Casa»: la stessa destinazione del pannello centrale di `home.html`.
     Un solo posto dichiara l'URL, per non avere due copie che divergono alla prima modifica. */
  var URL_ONYX = "https://onyx.lascuolaopensource.org/app?agentId=2";

  /* Le intestazioni dei gruppi, nell'ordine in cui compaiono. */
  var OGGI = "OGGI";
  var IERI = "IERI";
  var SETTE = "ULTIMI 7 GIORNI";
  var TRENTA = "ULTIMI 30 GIORNI";

  var PIEDE = "le conversazioni passate da Trasi restano 30 giorni";
  var TESTO_VUOTO = "Nessuna conversazione negli ultimi 30 giorni.";
  var TESTO_ERRORE = "Dati non disponibili: la memoria della rete non risponde in questo momento";

  var lista = null;

  function elemento(tag, classe, testo) {
    var el = document.createElement(tag);
    if (classe) el.className = classe;
    if (testo) el.textContent = testo;
    return el;
  }

  /* L'inizio del giorno locale di una data, in millisecondi. `new Date(y, m, d)` costruisce la
     mezzanotte **locale**: sottrarre giorni con `setDate` attraversa l'ora legale in modo corretto. */
  function mezzanotte(data) {
    return new Date(data.getFullYear(), data.getMonth(), data.getDate());
  }

  function giorniFa(quanti) {
    var data = new Date();
    data.setDate(data.getDate() - quanti);
    return mezzanotte(data);
  }

  /* Il gruppo di una conversazione, dalla data dell'**ultimo** turno: è l'ora che la voce mostra
     accanto al titolo, quindi è quella che deve decidere dove la voce compare. */
  function gruppo(iso) {
    if (!iso) return TRENTA;
    var quando = new Date(iso);
    if (isNaN(quando.getTime())) return TRENTA;
    var istante = quando.getTime();
    if (istante >= mezzanotte(new Date()).getTime()) return OGGI;
    if (istante >= giorniFa(1).getTime()) return IERI;
    if (istante >= giorniFa(7).getTime()) return SETTE;
    return TRENTA;
  }

  /* L'ora dell'ultimo turno, `HH:MM` nell'orologio del browser: è l'ora che l'operatore ha davanti,
     non quella del server. `it-IT` dà le 24 ore. */
  function ora(iso) {
    if (!iso) return "";
    var quando = new Date(iso);
    if (isNaN(quando.getTime())) return "";
    return quando.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
  }

  function apriOnyx() {
    /* `_blank` + `noopener`: scheda nuova, senza `window.opener`. */
    window.open(URL_ONYX, "_blank", "noopener");
  }

  /* ---------------------------------------------------------------- il pannello */

  function monta() {
    if (!window.Trasi || !window.Trasi.montaPannello) return;
    window.Trasi.montaPannello(
      '<div class="pannello-testa">' +
        '<button class="bottone storico-nuova" type="button" id="storico-nuova">Nuova conversazione</button>' +
        '<form id="storico-nuova-form" class="storico-nuova-form" hidden>' +
          '<label class="storico-nuova-etichetta" for="storico-nuova-testo">La domanda della persona</label>' +
          '<input id="storico-nuova-testo" maxlength="2000" autocomplete="off" ' +
                 'placeholder="Es. dove si fa l\'ISEE vicino a qui?">' +
          '<button class="bottone" type="submit">Apri la conversazione</button>' +
        '</form>' +
      '</div>' +
      '<div class="pannello-corpo">' +
        '<div id="storico-lista" class="storico-elenco" aria-label="Conversazioni"></div>' +
        '<p class="storico-piede">' + PIEDE + '</p>' +
      '</div>'
    );

    var bottone = document.getElementById("storico-nuova");
    var modulo = document.getElementById("storico-nuova-form");
    if (bottone && modulo) {
      /* Il bottone apre il modulo della domanda: l'apertura **salva** la domanda (P4.1) e poi porta
         a Onyx. «Nuova conversazione» senza domanda resta la via diretta. */
      bottone.addEventListener("click", function () {
        modulo.hidden = !modulo.hidden;
        if (!modulo.hidden) {
          var testo = document.getElementById("storico-nuova-testo");
          if (testo) testo.focus();
        }
      });
      modulo.addEventListener("submit", function (evento) {
        evento.preventDefault();
        var testo = document.getElementById("storico-nuova-testo");
        var domanda = testo ? testo.value.trim() : "";
        if (!domanda) { apriOnyx(); return; }
        window.Trasi.api("/op/conversazioni", { method: "POST", body: { messaggio: domanda } })
          .then(function () { apriOnyx(); })
          .catch(function (e) {
            /* L'apertura senza salvataggio non deve bloccare il dialogo: Onyx resta il luogo della
               conversazione, e il difetto della richiesta non salvata è dello shim, non dello sportello. */
            apriOnyx();
          });
      });
    } else if (bottone) {
      bottone.addEventListener("click", apriOnyx);
    }

    lista = document.getElementById("storico-lista");
    ricarica();
  }

  /* La voce è un `<a>` e non un `<button>`: porta a Onyx, non esegue un'azione locale. */
  function voce(conversazione) {
    var collegamento = elemento("a", "storico-voce");
    collegamento.href = URL_ONYX;
    collegamento.target = "_blank";
    collegamento.rel = "noopener";
    /* Il titolo è quello dello shim, già troncato a 40 caratteri. Vuoto (una conversazione creata
       e mai usata) → una frase che dice il fatto, non una riga vuota su cui si può cliccare. */
    collegamento.appendChild(elemento("span", "storico-titolo", conversazione.titolo || "Conversazione senza domanda"));
    collegamento.appendChild(elemento("span", "storico-ora", ora(conversazione.ultimo_ts)));
    return collegamento;
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
  }

  function ricarica() {
    if (!lista || !window.Trasi || !window.Trasi.api) return;
    return window.Trasi.api("/op/conversazioni?limite=" + LIMITE_ELENCO)
      .then(function (dati) { disegna(dati.conversazioni || []); })
      .catch(function (errore) {
        if (errore && errore.sessioneScaduta) return null;
        if (lista) {
          lista.textContent = "";
          lista.appendChild(elemento("p", "storico-vuoto", TESTO_ERRORE));
        }
        return null;
      });
  }

  window.TrasiStorico = { ricarica: ricarica, monta: monta };

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