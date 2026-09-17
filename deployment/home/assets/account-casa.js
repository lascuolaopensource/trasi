/* account-casa.js — il comportamento della sezione «La Casa».
 *
 * Perché un file separato e non uno `<script>` nel frammento: `innerHTML` **non esegue** gli script
 * (`CONTRATTO-shell.md` §5, regola 4), quindi il comportamento di una sezione vive in un modulo che
 * `account.js` carica grazie all'attributo `data-modulo` sull'elemento radice del frammento. Questo
 * file registra il proprio avvio nel registro `window.TrasiAccount.avvii`, con la chiave che è il nome
 * della sezione: `la-casa`.
 *
 * Cosa fa, e nient'altro: chiede `GET /op/casa` e riempie il markup. Nessuna scrittura — la testata
 * della Casa è in sola lettura per scelta di progetto (le modifiche passano da proposta →
 * approvazione → applicazione, V4), e una POST da qui sarebbe la seconda via di scrittura che V4
 * vieta.
 *
 * Due regole di contenuto che valgono solo qui:
 *
 *   * **i dati provvisori stanno nel TESTO**, mai in un colore (Tuturano ha `da_validare = true` e
 *     `orari_provvisori = true`: la pagina lo dice a parole, in due punti distinti, perché sono due
 *     fatti distinti — l'anagrafica da confermare e gli orari in via di definizione);
 *   * **l'etichetta di provenienza è quella dello shim, verbatim** (V3): il `badge` che arriva da
 *     `GET /op/casa` si scrive così com'è e non si ricompone, altrimenti due schermate della stessa
 *     Casa mostrerebbero due etichette diverse.
 */
(function () {
  "use strict";

  var GIORNI = {
    lun: "lunedì", mar: "martedì", mer: "mercoledì", gio: "giovedì",
    ven: "venerdì", sab: "sabato", dom: "domenica"
  };

  var MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
              "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"];

  /* `2026-09-15` → `15/09/2026`. La data arriva ISO dallo shim e si mostra all'italiana: è la forma
   * che l'operatore legge in ogni altro punto del prodotto (badge compresi), e l'ISO nella scheda
   * sarebbe l'unico posto con una forma diversa. */
  function dataItaliana(iso) {
    if (!iso || iso.length < 10) return "non dichiarata";
    var p = iso.slice(0, 10).split("-");
    return p[2] + "/" + p[1] + "/" + p[0];
  }

  /* Il raggio: `raggio_m` è quello dichiarato dalla Casa (può essere assente), `raggio_m_eff` è quello
   * che il sistema usa davvero, con il default `[P] raggio_vicinanza_m` al posto del valore mancante.
   * Si mostrano **entrambi** quando differiscono, e si spiega perché: un campo vuoto nella scheda si
   * legge «non si sa», mentre «non dichiarato: si usa il valore della rete, 800 m» è la verità. */
  function testoRaggio(dati) {
    var dichiarato = dati.raggio_m;
    var effettivo = dati.raggio_m_eff;
    if (dichiarato !== null && dichiarato !== undefined) {
      return dichiarato + " metri";
    }
    if (effettivo !== null && effettivo !== undefined) {
      return "non dichiarato dalla Casa: si usa il valore della rete, " + effettivo + " metri";
    }
    return "non dichiarato";
  }

  /* Il punto sulla mappa: `geom_qualita` dice se le coordinate sono state verificate o stimate
   * (`verificata` | `stimata`, CHECK di `trasi.casa`). «stimata» è un'informazione che l'operatore
   * deve avere: significa che il pin della mappa può cadere a qualche decina di metri dal portone. */
  function testoGeom(qualita) {
    if (qualita === "verificata") return "coordinate verificate";
    if (qualita === "stimata") return "coordinate stimate, da confermare sul posto";
    return "qualità della posizione non dichiarata";
  }

  function testoFiducia(livello) {
    if (livello === null || livello === undefined) return "non dichiarato";
    return livello + " su 3";
  }

  function scrivi(id, testo) {
    var nodo = document.getElementById(id);
    if (nodo) nodo.textContent = testo;
  }

  /* ---------------------------------------------------------------- orari */

  function riempiOrari(orari, provvisori) {
    var corpo = document.getElementById("acc-casa-orari-corpo");
    var tabella = document.getElementById("acc-casa-orari-tabella");
    var vuoto = document.getElementById("acc-casa-orari-vuoto");
    var nota = document.getElementById("acc-casa-orari-nota");
    if (!corpo) return;

    corpo.textContent = "";
    var righe = orari || [];

    if (!righe.length) {
      /* Nessun orario dichiarato: si dichiara il vuoto con la parola del contratto — «orari non
       * disponibili» — invece di mostrare sette righe con un trattino, che sembrerebbero sette
       * giorni chiusi. È il caso di Tuturano (`orari IS NULL`). */
      if (tabella) tabella.hidden = true;
      if (vuoto) vuoto.hidden = false;
      if (nota) nota.textContent = "";
      return;
    }

    if (tabella) tabella.hidden = false;
    if (vuoto) vuoto.hidden = true;

    for (var i = 0; i < righe.length; i++) {
      var tr = document.createElement("tr");
      var th = document.createElement("th");
      th.setAttribute("scope", "row");
      th.textContent = GIORNI[righe[i].giorno] || righe[i].giorno;
      var td = document.createElement("td");
      td.textContent = righe[i].fasce;
      tr.appendChild(th);
      tr.appendChild(td);
      corpo.appendChild(tr);
    }

    /* «orari in via di definizione» è la formula del seed e della vista KB (`db/004_views.sql`) per
     * una Casa con `orari_provvisori = true`: si riusa alla lettera, e sta nel testo. */
    if (nota) {
      nota.textContent = provvisori ? "orari in via di definizione" : "";
      nota.hidden = !provvisori;
    }
  }

  function riempiEccezioni(eccezioni) {
    var blocco = document.getElementById("acc-casa-eccezioni-blocco");
    var elenco = document.getElementById("acc-casa-eccezioni");
    if (!blocco || !elenco) return;

    elenco.textContent = "";
    if (!eccezioni || !eccezioni.length) {
      blocco.hidden = true;
      return;
    }

    for (var i = 0; i < eccezioni.length; i++) {
      var e = eccezioni[i];
      var li = document.createElement("li");
      var quando = "";
      if (e.dal && e.al) quando = " dal " + dataItaliana(e.dal) + " al " + dataItaliana(e.al);
      else if (e.dal) quando = " dal " + dataItaliana(e.dal);
      /* La nota è il testo scritto dal seed («orari stagionali estate 10-12 / 17:20-20»): è già in
       * italiano e si riporta così com'è. Il tipo (`stagionale`) è il vocabolario del database e
       * resta tale perché non ha una traduzione dichiarata. */
      li.textContent = e.tipo + quando + (e.nota ? " — " + e.nota : "");
      elenco.appendChild(li);
    }
    blocco.hidden = false;
  }

  /* ---------------------------------------------------------------- provvisorietà */

  /* Due fatti distinti, due frasi distinte, entrambe nel TESTTO e mai in un colore. Si mostrano
   * insieme quando entrambi valgono — è il caso di Tuturano — perché dicono cose diverse: l'anagrafica
   * della Casa non è ancora stata confermata, e gli orari non sono ancora definitivi. */
  function testoProvvisorio(dati) {
    var pezzi = [];
    if (dati.da_validare) {
      pezzi.push("I dati di questa Casa sono provvisori: l'anagrafica non è ancora stata confermata.");
    }
    if (dati.orari_provvisori) {
      pezzi.push("Gli orari sono provvisori e possono cambiare.");
    }
    return pezzi.join(" ");
  }

  /* ---------------------------------------------------------------- montaggio */

  function mostra(dati) {
    scrivi("acc-casa-nome", dati.nome || "Casa senza nome");
    scrivi("acc-casa-zona", dati.zona ? "Zona " + dati.zona : "Zona non dichiarata");
    scrivi("acc-casa-zona-valore", dati.zona || "non dichiarata");
    scrivi("acc-casa-ente", dati.ente_gestore || "non dichiarato");
    scrivi("acc-casa-raggio", testoRaggio(dati));
    scrivi("acc-casa-geom", testoGeom(dati.geom_qualita));

    var provvisorio = document.getElementById("acc-casa-provvisorio");
    if (provvisorio) {
      var testo = testoProvvisorio(dati);
      provvisorio.textContent = testo;
      provvisorio.hidden = !testo;
    }

    riempiOrari(dati.orari_settimanali, dati.orari_provvisori);
    riempiEccezioni(dati.orari_eccezioni);

    var prov = dati.provenienza || {};
    /* L'etichetta V3 si scrive **verbatim**: è la stringa composta dallo shim (`badge.py`), e
     * ricomporla qui renderebbe due schermate della stessa Casa non confrontabili. */
    scrivi("acc-casa-badge", prov.badge || "provenienza non dichiarata");
    scrivi("acc-casa-fonte", prov.fonte || "non dichiarata");
    scrivi("acc-casa-fiducia", testoFiducia(prov.fiducia));
    scrivi("acc-casa-aggiornato", dataItaliana(prov.data_aggiornamento));
  }

  function guasto() {
    /* Se la lettura fallisce, i campi restano al loro «—» e si accende lo stato dichiarato: «Dati non
     * disponibili…», il testo del contratto §7. Non si svuota la scheda — un titolo senza dati si
     * legge «questa Casa non ha dati», che è un'affermazione falsa. */
    var nodo = document.getElementById("acc-casa-guasto");
    if (nodo) nodo.hidden = false;
  }

  function monta(vista) {
    var guastoNodo = document.getElementById("acc-casa-guasto");
    if (guastoNodo) guastoNodo.hidden = true;

    if (!window.Trasi || !window.Trasi.api) {
      guasto();
      return;
    }

    window.Trasi.api("/op/casa").then(mostra).catch(guasto);
  }

  /* Registro degli avvii: la chiave è il nome della sezione, cioè `data-sezione` del frammento. */
  window.TrasiAccount = window.TrasiAccount || { avvii: {} };
  window.TrasiAccount.avvii["la-casa"] = monta;
})();
