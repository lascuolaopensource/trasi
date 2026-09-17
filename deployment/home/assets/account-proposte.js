/* account-proposte.js — il comportamento della sezione «Proposte»: la lista, il diff, la decisione.
 *
 * Perché un file separato e non uno `<script>` nel frammento: `innerHTML` **non esegue** gli script
 * (`CONTRATTO-shell.md` §5, regola 4), quindi il comportamento vive in un modulo che `account.js`
 * carica grazie a `data-modulo`. Il modulo registra il proprio avvio in `window.TrasiAccount.avvii`
 * con la chiave `proposte`.
 *
 * ------------------------------------------------------------------ G-05, il punto delicato
 *
 * La policy RESTRICTIVE `no_self_approve` del database confronta `proposto_da` con `current_user` —
 * cioè il **ruolo DB** — non l'email. Poiché un account per Casa significa un ruolo per Casa, la
 * conseguenza è che **una Casa non può approvare le proprie proposte**: `UPDATE 0`, quindi 403.
 * Sul database reale la coda di Bozzano ha 0 righe decidibili e 1 proposta aperta che la riguarda
 * (`chiudi_luogo` id 2106, `chi_decide = 'at'`).
 *
 * Da qui le due forme della riga, e la scelta di come NON mostrarle:
 *
 *   * `decidibile` → `[Approva]` e `[Rifiuta]` presenti e attivi;
 *   * non decidibile → i pulsanti **non ci sono**. Al loro posto una nota che dice chi decide.
 *
 * I pulsanti non si disabilitano, e non è una preferenza estetica: un pulsante spento si legge «non
 * ora, forse dopo» e invita a ritentare — ma la decisione di un altro non è un «non ora», è una
 * competenza diversa. Un pulsante che non sa decidere è peggio di un pulsante assente.
 *
 * **La logica di `decidibile` non è qui.** Il campo arriva dall'endpoint, che lo legge dalla vista
 * `v_da_approvare` — la stessa autorità che governa l'`UPDATE`. Ricostruire il predicato in
 * JavaScript sarebbe una seconda copia della policy, e il giorno in cui Processi cambia la regola nel
 * database la UI mostrerebbe pulsanti su proposte che il server rifiuta.
 *
 * ------------------------------------------------------------------ il diff
 *
 * `diff_leggibile` è composto dal database (`trasi.diff_leggibile`, `db/006_fn_proposte.sql`): una
 * riga per campo, «campo: prima → dopo». È il testo su cui l'umano decide, e si mostra così com'è —
 * ricomporlo qui dai `payload` significherebbe riscrivere in JavaScript la regola che decide quali
 * campi sono cambiati, che vive nel database e che è già stata corretta una volta.
 */
(function () {
  "use strict";

  var MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
              "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"];

  function el(tag, classe, testo) {
    var nodo = document.createElement(tag);
    if (classe) nodo.className = classe;
    if (testo !== undefined && testo !== null) nodo.textContent = testo;
    return nodo;
  }

  function dataItaliana(iso) {
    if (!iso || iso.length < 10) return "non dichiarata";
    var p = iso.slice(0, 10).split("-");
    return p[2] + "/" + p[1] + "/" + p[0];
  }

  /* «1 giorno» / «4 giorni»: il singolare è la differenza fra una frase scritta e una generata. */
  function eta(testo) {
    if (testo === null || testo === undefined) return "da data non nota";
    if (testo === 0) return "oggi";
    return "da " + testo + (testo === 1 ? " giorno" : " giorni");
  }

  /* Chi decide, in parole. `chi_decide` arriva dal database come vocabolario (`at`, `gestore`, `ti`) e
   * non come frase: qui si traduce per la lettura, e i tre valori sono quelli che il CHECK
   * `proposta_approvatore_ruolo_check` ammette — non un elenco inventato. */
  function chiDecide(valore) {
    if (valore === "at") return "AT";
    if (valore === "gestore") return "gestore della Casa";
    if (valore === "ti") return "TI";
    return valore || "altro ruolo";
  }

  /* Origine della proposta: da dove è arrivata. Il vocabolario è quello del CHECK
   * `proposta_origine_check` di `trasi.proposta`; i valori non tradotti si mostrano come sono,
   * perché un'etichetta sbagliata è peggio di un termine tecnico. */
  var ORIGINI = {
    chat: "dalla chat",
    fonte_automatica: "da una fonte automatica",
    ricerca_esterna: "da una ricerca esterna",
    coerenza: "dal controllo di coerenza",
    manuale: "inserita a mano"
  };

  /* Il tipo della proposta: `chiudi_luogo`, `modifica_orari_casa`, … È il vocabolario di
   * `proposta_tipo_check` (dodici valori). Si mostra **sotto** una forma leggibile, con il nome
   * tecnico accanto fra parentesi: serve a chi confronta la riga con il database, che è un lavoro
   * reale dell'operatore e del TI. */
  var TIPI = {
    nuovo_luogo: "nuovo luogo",
    modifica_luogo: "modifica di un luogo",
    chiudi_luogo: "chiusura di un luogo",
    modifica_scheda: "modifica di una scheda di servizio",
    nuova_scheda: "nuova scheda di servizio",
    modifica_evento: "modifica di un evento",
    nuova_opportunita: "nuova opportunità",
    promuovi_esterno: "promozione di un risultato esterno in memoria",
    modifica_orari_casa: "modifica degli orari della Casa",
    nuovo_oggetto: "nuovo oggetto dell'attrezzoteca",
    modifica_oggetto: "modifica di un oggetto dell'attrezzoteca",
    ritira_oggetto: "ritiro di un oggetto dell'attrezzoteca"
  };

  /* L'entità toccata: `luogo`, `casa`, `evento`, … con l'id quando c'è. Il soggetto della riga —
   * «chiusura di un luogo (1)» — dice cosa cambia, che è la prima cosa che serve per decidere. */
  function testoEntita(voce) {
    var tipo = TIPI[voce.tipo] || voce.tipo;
    var id = (voce.entita_id === null || voce.entita_id === undefined) ? "" : " (" + voce.entita_id + ")";
    return tipo + (voce.entita ? " · " + voce.entita + id : "") + " · " + voce.tipo;
  }

  /* ---------------------------------------------------------------- la riga */

  function rigaProposta(voce, ricarica, esito) {
    var li = el("li", "acc-proposte-riga blocco filetto " + (voce.decidibile ? "filetto--coda" : "filetto--attenzione"));
    li.setAttribute("data-proposta", String(voce.id));

    var testa = el("div", "blocco-testa");
    testa.appendChild(el("p", "acc-proposte-tipo", testoEntita(voce)));
    /* La motivazione è il testo scritto dalla persona che ha proposto: si riporta così com'è.
     * Se manca — il campo è facoltativo nel modello dati — si dichiara l'assenza invece di lasciare
     * uno spazio bianco che si legge come un difetto di caricamento. */
    testa.appendChild(el("p", "acc-proposte-motivazione",
      voce.motivazione || "motivazione non dichiarata"));
    li.appendChild(testa);

    /* Il diff leggibile: è il testo su cui si decide. `<pre>` non perché sia codice, ma perché gli
     * a capo della composizione SQL sono parte dell'informazione (una riga per campo) e il browser
     * deve conservarli. */
    var diff = el("div", "acc-proposte-diff");
    diff.appendChild(el("h3", "acc-proposte-sottotitolo", "Cosa cambia"));
    diff.appendChild(el("pre", "acc-proposte-diff-testo",
      voce.diff_leggibile || "(nessun campo proposto)"));
    li.appendChild(diff);

    /* Riga dei fatti: età, chi decide, scadenza. L'età si legge per prima perché è ciò che dice da
     * quanto una decisione aspetta. */
    var fatti = el("p", "acc-proposte-fatti");
    var pezzi = [
      "in attesa " + eta(voce.eta_giorni),
      "chi decide: " + chiDecide(voce.chi_decide),
      "origine: " + (ORIGINI[voce.origine] || voce.origine)
    ];
    /* La scadenza si dichiara solo per le proposte ancora decidibili: su una scaduta sarebbe un
     * secondo modo di dire la stessa cosa, e il motivo lo dice già. */
    if (voce.decidibile && voce.scade_il) {
      pezzi.push("decidibile fino al " + dataItaliana(voce.scade_il));
    }
    fatti.textContent = pezzi.join(" · ");
    li.appendChild(fatti);

    if (voce.decidibile) {
      li.appendChild(comandi(voce, ricarica, esito));
    } else {
      /* I pulsanti NON ci sono; c'è la nota che dice chi decide. Il testo del motivo è composto
       * dall'endpoint (sa distinguere «scaduta», «è di AT», «questa Casa non decide una proposta che
       * ha creato») e si riporta verbatim: ricomporlo qui sarebbe una seconda copia di quella
       * classificazione, e le due divergerebbero. */
      li.appendChild(el("p", "acc-proposte-nota",
        voce.motivo_non_decidibile || "la decisione è di un altro ruolo"));
    }

    return li;
  }

  /* ---------------------------------------------------------------- la decisione */

  function comandi(voce, ricarica, esito) {
    var box = el("div", "acc-proposte-comandi");

    var nota = el("input", "acc-proposte-nota-campo");
    nota.type = "text";
    nota.id = "acc-proposte-nota-" + voce.id;
    nota.maxLength = 80;          // il contratto congelato e il CHECK del DB dichiarano 80
    nota.setAttribute("placeholder", "nota per chi legge (facoltativa)");

    var etichetta = el("label", "acc-proposte-nota-etichetta", "Nota sulla decisione");
    etichetta.setAttribute("for", nota.id);
    /* L'aiuto dichiara il limite e il divieto di dati personali: il filtro anti-PII risponde 422, e
     * dirlo prima evita che l'operatore scriva un telefono dettato a voce e perda la decisione. Il
     * testo è quello di `design/ui_kits/trasi-registra/Registra.jsx`. */
    var aiuto = el("p", "acc-proposte-nota-aiuto", "Massimo 80 caratteri, senza dati personali.");

    function decidi(decisione, bottone) {
      var altri = box.querySelectorAll("button");
      for (var i = 0; i < altri.length; i++) altri[i].disabled = true;
      esito.hidden = true;

      window.Trasi.api("/op/proposte/" + voce.id + "/decisione", {
        method: "POST",
        body: { decisione: decisione, nota: nota.value.trim() || null }
      }).then(function (risposta) {
        /* L'applicazione al dominio non è di questa chiamata: la proposta passa ad `approvata` e a
         * scrivere la memoria è il flusso notturno (F9). Il testo lo dice, ed è il testo del piano
         * §5.4 — senza, un operatore cercherebbe sullo schermo un effetto che arriva la notte. */
        esito.textContent = (risposta.stato === "approvata" ? "Approvata." : "Rifiutata.") +
          " Si applica stanotte alle 05:00.";
        esito.hidden = false;
        ricarica();
      }).catch(function (errore) {
        for (var i = 0; i < altri.length; i++) altri[i].disabled = false;
        /* Gli errori si dicono per quello che sono, con il testo del server che è già in italiano e
         * già privo di dati personali:
         *   403 → «da approvare in coda»: la RLS ha negato, e il pulsante non doveva esserci. Succede
         *         solo se la coda è cambiata fra la lettura e la decisione (es. Processi ha corretto
         *         la regola, o un'altra sessione ha già deciso). Si ricarica, così la riga si
         *         ricompone con lo stato vero invece di lasciare pulsanti che non funzionano.
         *   409 → già decisa o scaduta: stessa cosa, si ricarica.
         *   422 → nota con dati personali o troppo lunga: si dichiara, e i pulsanti tornano attivi. */
        esito.textContent = (errore && errore.message) ? errore.message : "decisione non registrata";
        esito.hidden = false;
        if (errore && (errore.stato === 403 || errore.stato === 409)) ricarica();
      });
    }

    var approva = el("button", "bottone bottone--principale", "Approva");
    approva.type = "button";
    approva.addEventListener("click", function () { decidi("approva", approva); });

    var rifiuta = el("button", "bottone", "Rifiuta");
    rifiuta.type = "button";
    rifiuta.addEventListener("click", function () { decidi("rifiuta", rifiuta); });

    box.appendChild(etichetta);
    box.appendChild(nota);
    box.appendChild(aiuto);
    box.appendChild(approva);
    box.appendChild(rifiuta);
    return box;
  }

  /* ---------------------------------------------------------------- montaggio */

  var datiCorrenti = null;

  function disegna(vista) {
    var attesa = document.getElementById("acc-proposte-attesa");
    var vuoto = document.getElementById("acc-proposte-vuoto");
    var guastoNodo = document.getElementById("acc-proposte-guasto");
    var esito = document.getElementById("acc-proposte-esito");
    var elenco = document.getElementById("acc-proposte-elenco");
    if (!elenco) return;

    if (attesa) attesa.hidden = true;
    if (guastoNodo) guastoNodo.hidden = true;

    elenco.textContent = "";
    var proposte = (datiCorrenti && datiCorrenti.proposte) || [];

    if (!proposte.length) {
      /* Coda vuota: il testo è quello di `AvvisoCoda.prompt.md`, riusato alla lettera. Il nome della
       * Casa arriva da `Trasi.nomeCasa()`, che è la stessa fonte della testata della pagina: due
       * nomi diversi nella stessa pagina sarebbero un difetto visibile. */
      if (vuoto) {
        vuoto.textContent = "Nessuna proposta in attesa a " + (window.Trasi.nomeCasa() || "questa Casa") + ".";
        vuoto.hidden = false;
      }
      if (esito) esito.hidden = true;
      return;
    }

    if (vuoto) vuoto.hidden = true;

    function ricarica() { leggi(vista); }
    for (var i = 0; i < proposte.length; i++) {
      elenco.appendChild(rigaProposta(proposte[i], ricarica, esito));
    }
  }

  function leggi(vista) {
    var esito = document.getElementById("acc-proposte-esito");
    /* L'esito resta visibile mentre si ricarica: se sparisse subito dopo una decisione, l'operatore
     * non leggerebbe «Si applica stanotte alle 05:00», che è l'unica cosa che quella frase serve a
     * dire. Si nasconde solo quando la lista si ridisegna da capo per un cambio di sezione. */
    if (window.Trasi && window.Trasi.api) {
      window.Trasi.api("/op/proposte").then(function (dati) {
        datiCorrenti = dati;
        disegna(vista);
      }).catch(function () {
        var attesa = document.getElementById("acc-proposte-attesa");
        var guastoNodo = document.getElementById("acc-proposte-guasto");
        if (attesa) attesa.hidden = true;
        if (guastoNodo) guastoNodo.hidden = false;
        if (esito) esito.hidden = true;
      });
      return;
    }
    var attesa2 = document.getElementById("acc-proposte-attesa");
    var guasto2 = document.getElementById("acc-proposte-guasto");
    if (attesa2) attesa2.hidden = true;
    if (guasto2) guasto2.hidden = false;
  }

  function monta(vista) {
    var attesa = document.getElementById("acc-proposte-attesa");
    var guastoNodo = document.getElementById("acc-proposte-guasto");
    var esito = document.getElementById("acc-proposte-esito");
    if (attesa) attesa.hidden = false;
    if (guastoNodo) guastoNodo.hidden = true;
    if (esito) esito.hidden = true;
    datiCorrenti = null;
    leggi(vista);
  }

  window.TrasiAccount = window.TrasiAccount || { avvii: {} };
  window.TrasiAccount.avvii["proposte"] = monta;
})();
