/* casa.js — la Casa scelta, condivisa fra le pagine pubbliche (Home, Mappa).
 *
 * Una sola copia della regola: lo slug è valido **solo** se è una delle `<option>` del selettore
 * `#selettore-casa` della pagina — un residuo in `localStorage` o un `?casa=` scritto a mano non
 * devono poter costruire un indirizzo arbitrario. In `localStorage` entra solo lo slug (valore
 * pubblico, chiave `trasi.casa_id`), nient'altro (V5).
 *
 * Espone `window.TrasiCasa`; `home.js` e `mappa.js` lo caricano **prima** di sé e non ridefiniscono
 * queste funzioni. Il comportamento della Home è quello di prima: stessi id, stessa chiave, stessa
 * validazione contro le opzioni.
 */
(function () {
  "use strict";

  var CHIAVE_CASA = "trasi.casa_id";
  var CASA_PREDEFINITA = "san-bao";

  var selettore = document.getElementById("selettore-casa");

  function opzione(slug) {
    if (typeof slug !== "string" || slug === "" || !selettore) return null;
    for (var i = 0; i < selettore.options.length; i++) {
      if (selettore.options[i].value === slug) return selettore.options[i];
    }
    return null;
  }

  function casaValida(slug) {
    return opzione(slug) ? slug : null;
  }

  function casaScelta() {
    return casaValida(selettore && selettore.value) || CASA_PREDEFINITA;
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

  function ricorda() {
    try {
      return casaValida(window.localStorage.getItem(CHIAVE_CASA));
    } catch (e) {
      return null;
    }
  }

  /* Lo slug da `?casa=`, se valido: è l'indirizzo che la Home compone per le destinazioni
     (`mappa.html?casa=<slug>`). Un valore non valido è ignorato in silenzio: ripiego alla
     Casa ricordata o predefinita, nessun testo tecnico a schermo. */
  function daUrl() {
    try {
      return casaValida(new URLSearchParams(window.location.search).get("casa"));
    } catch (e) {
      return null;
    }
  }

  window.TrasiCasa = {
    CHIAVE_CASA: CHIAVE_CASA,
    CASA_PREDEFINITA: CASA_PREDEFINITA,
    selettore: selettore,
    opzione: opzione,
    casaValida: casaValida,
    casaScelta: casaScelta,
    nomeCasa: nomeCasa,
    memorizza: memorizza,
    ricorda: ricorda,
    daUrl: daUrl
  };
})();
