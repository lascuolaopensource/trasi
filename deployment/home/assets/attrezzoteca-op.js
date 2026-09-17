/* attrezzoteca-op.js — il comportamento della sezione «Attrezzoteca» dell'Account.
 *
 * CARICATO DA `account.html`; `account.js` chiama `window.TrasiAccount.avvii["attrezzoteca"](vista)`
 * dopo aver inserito il frammento (contratto §5.4). Il frammento è solo markup.
 *
 * ---------------------------------------------------------------------------
 * Gli endpoint esistono già, e questo modulo non ne riscrive la logica
 * ---------------------------------------------------------------------------
 * `GET /op/attrezzoteca`, `GET /op/movimenti_da_confermare`, `POST /op/movimento`,
 * `POST /op/movimento/{id}/conferma` sono in `shim/app/attrezzoteca.py` e non cambiano: la regola
 * «conferma solo la destinataria, rientro solo la cedente/rete» vive in `trasi.conferma_movimento`
 * (SECURITY DEFINER, db/014), e ripeterla qui sarebbe una seconda decisione che diverge dalla prima.
 *
 * ---------------------------------------------------------------------------
 * Cosa questo modulo NON fa, e perché è la cosa importante
 * ---------------------------------------------------------------------------
 * Non offre di **creare** un oggetto. L'inventario si popola con una proposta (`nuovo_oggetto`, il
 * flusso V4 di `proponi_modifica`), non con un INSERT: `oggetto` è dominio, e da questa pagina il
 * dominio non si scrive. Su questo database l'inventario è vuoto (0 oggetti), quindi il vuoto è la
 * schermata normale e va dichiarato con la sua frase, non nascosto dietro una tabella senza righe.
 *
 * ---------------------------------------------------------------------------
 * Perché il pulsante «Proponi prestito» non sta su ogni riga
 * ---------------------------------------------------------------------------
 * `mov_ins_casa` (db/014) pretende `oggetto.casa_id = casa_corrente()`: prestando un oggetto altrui la
 * RLS respinge l'INSERT. Nel portare qui le funzioni di `operatore.js` la lezione era già scritta nel
 * suo commento, ed è rimasta. Il caso d'uso normale — «cinque microfoni per domani, dove sono?»
 * (US-5.1) — è **chiedere** in prestito, e la richiesta si fa parlando con la Casa che li ha: qui si
 * dichiara chi è, invece di mostrare un pulsante che risponde「non puoi」.
 *
 * «Tu» di `operatore.js` diventa «OPERATORE»: la prima persona non è ammessa nei testi, e il nome del
 * ruolo è già quello che il turno della chat usa (`design/components/chat/MessaggioChat`).
 */
(function () {
  "use strict";

  function $(id) {
    return document.getElementById(id);
  }

  function mostra(nodo, testo) {
    if (!nodo) return;
    nodo.textContent = testo || "";
    nodo.hidden = !testo;
  }

  /* Una risposta non OK diventa un errore leggibile; mai il corpo grezzo (V6: niente gergo). */
  function chiama(percorso, opzioni) {
    var init = opzioni || {};
    init.headers = Object.assign({ Accept: "application/json" }, init.headers || {});
    if (init.body && typeof init.body === "object") {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(init.body);
    }
    init.credentials = "same-origin";
    return fetch("/api/shim" + percorso, init).then(function (risposta) {
      if (risposta.status === 401) {
        var scaduta = new Error("sessione assente o scaduta");
        scaduta.sessioneScaduta = true;
        throw scaduta;
      }
      if (!risposta.ok) {
        return risposta.json().catch(function () { return null; }).then(function (corpo) {
          var dettaglio = corpo && (corpo.dettaglio || corpo.detail);
          var e = new Error(typeof dettaglio === "string" ? dettaglio : "errore " + risposta.status);
          e.stato = risposta.status;
          throw e;
        });
      }
      var tipo = risposta.headers.get("content-type") || "";
      return tipo.indexOf("json") >= 0 ? risposta.json() : risposta.text();
    });
  }

  /* La frase per l'operatore la compone `shell.js` (`Trasi.spiega`): un solo traduttore per tutto il
     sito, mai il `detail` tecnico dello shim. Il ripiego locale vale solo se la shell non c'è. */
  function messaggioErrore(e) {
    if (window.Trasi && window.Trasi.spiega) return window.Trasi.spiega(e);
    return e && e.sessioneScaduta ? "Sessione non più valida: la pagina di accesso è a un passo." : "Operazione non riuscita.";
  }

  function casaCorrente() {
    return window.Trasi && window.Trasi.casa ? window.Trasi.casa.casa : null;
  }

  /* ---------------------------------------------------------------- inventario */

  function cella(testo) {
    var td = document.createElement("td");
    td.textContent = testo == null || testo === "" ? "—" : String(testo);
    return td;
  }

  function rigaInventario(oggetto) {
    var tr = document.createElement("tr");
    tr.appendChild(cella(oggetto.nome));
    tr.appendChild(cella(oggetto.casa));

    /* La disponibilità è quella della vista `v_inventario`, già al netto dei confermati in corso:
       non si somma e non si sottrae nulla qui, così il numero che legge la Casa prestatrice e quello
       che legge la Casa richiedente sono lo stesso numero. */
    var disponibili = cella(oggetto.quantita_disponibile);
    if (oggetto.quantita_fuori > 0) {
      disponibili.textContent = oggetto.quantita_disponibile + " (fuori " + oggetto.quantita_fuori + ")";
    }
    tr.appendChild(disponibili);

    tr.appendChild(cella(oggetto.condizione));

    /* Provenienza (V3): il badge della fonte arriva dalla vista e si rende **verbatim**, mai
       ricomposto — è la regola dell'etichetta, e vale anche in una cella di tabella. */
    var provenienza = document.createElement("td");
    var etichetta = document.createElement("span");
    etichetta.className = "etichetta etichetta--kb";
    etichetta.textContent = oggetto.badge || oggetto.fonte || "fonte non dichiarata";
    provenienza.appendChild(etichetta);
    tr.appendChild(provenienza);

    var azione = document.createElement("td");
    if (String(oggetto.casa || "") === String(casaCorrente() || "")) {
      var bottone = document.createElement("button");
      bottone.type = "button";
      bottone.className = "azione";
      bottone.textContent = "Proponi prestito";
      bottone.addEventListener("click", function () { proponiPrestito(oggetto); });
      azione.appendChild(bottone);
    } else {
      /* Un oggetto di un'altra Casa si **chiede** alla Casa che lo tiene: la piattaforma non offre
         una via per prenderlo, e dirlo è più utile che mostrare un pulsante che verrebbe respinto. */
      azione.className = "acc-attrezzoteca-stato-proprio";
      azione.textContent = "Di un'altra Casa: la richiesta si rivolge alla Casa che lo tiene.";
    }
    tr.appendChild(azione);
    return tr;
  }

  function caricaInventario(q) {
    var corpo = $("acc-attrezzoteca-corpo-inventario");
    var stato = $("acc-attrezzoteca-stato-inventario");
    var vuoto = $("acc-attrezzoteca-vuoto-inventario");
    if (!corpo) return;

    corpo.textContent = "";
    mostra(vuoto, "");
    mostra(stato, "Lettura in corso…");

    /* Il filtro `q` è un `ILIKE` sul nome e sulla descrizione: la ricerca della rete non distingue
       maiuscole. Il termine si codifica nell'URL, mai interpolato a mano. */
    chiama("/op/attrezzoteca" + (q ? "?q=" + encodeURIComponent(q) : "")).then(function (dati) {
      /* Il campo è `items`: è quello che `GET /op/attrezzoteca` restituisce (`{"items": […]}`). */
      var elenco = dati && dati.items;
      mostra(stato, "");
      if (!Array.isArray(elenco) || !elenco.length) {
        /* Vuoto dichiarato: su questo database l'inventario **è** vuoto (0 oggetti), e una tabella
           con solo l'intestazione non direbbe perché. La frase dice anche da dove si popola — una
           proposta — invece di lasciare intendere che la funzione sia spenta. */
        mostra(
          vuoto,
          q
            ? "Nessun oggetto in memoria corrisponde a questa ricerca."
            : "Nessun oggetto in attrezzoteca per la rete: l'inventario si popola con una proposta accolta."
        );
        return;
      }
      elenco.forEach(function (oggetto) { corpo.appendChild(rigaInventario(oggetto)); });
    }).catch(function (e) {
      mostra(stato, e && e.sessioneScaduta ? messaggioErrore(e) : "Inventario non disponibile: " + messaggioErrore(e));
    });
  }

  /* ---------------------------------------------------------------- prestito */

  /* Le Case della rete, per scegliere la destinataria: si leggono dalle opzioni del selettore della
     pagina di accesso, che è l'unico elenco in pagina. Se non c'è (la sezione aperta da sola), si
     chiede lo slug e lo si manda: lo shim risponde «Casa destinataria sconosciuta» se non esiste, e
     quel messaggio è più utile di un elenco inventato qui. */
  function caseDellaRete() {
    var opzioni = document.querySelectorAll("#accesso-casa option");
    var slug = [];
    for (var i = 0; i < opzioni.length; i++) slug.push(opzioni[i].value);
    return slug;
  }

  function proponiPrestito(oggetto) {
    var errore = $("acc-attrezzoteca-errore");
    var esito = $("acc-attrezzoteca-esito");
    mostra(errore, "");
    mostra(esito, "");

    var oggi = new Date().toISOString().slice(0, 10);
    var destinataria = window.prompt(
      "A quale Casa va «" + oggetto.nome + "»? (slug, es. bozzano)",
      ""
    );
    if (destinataria === null) return;
    destinataria = destinataria.trim();
    if (!destinataria) return;

    /* La destinataria deve essere una Casa **diversa** dalla propria: `movimento_case_distinte`
       (db/014) è un CHECK, e proporre come default l'unico valore non ammesso sarebbe un modulo che
       sbaglia da solo. */
    if (destinataria === casaCorrente()) {
      mostra(errore, "La Casa destinataria è diversa dalla propria: un prestito va a un'altra Casa.");
      return;
    }
    var note = caseDellaRete();
    if (note.length && note.indexOf(destinataria) < 0) {
      mostra(errore, "Casa «" + destinataria + "» non riconosciuta: serve lo slug di una Casa della rete (es. bozzano).");
      return;
    }

    var al = window.prompt("Fino a quando? (AAAA-MM-GG)", oggi);
    if (!al) return;

    /* I nomi dei campi sono quelli dell'endpoint: `oggetto_id`, `a_casa` (slug), `dal`, `al` come date
       ISO. `a_casa_slug` sarebbe un campo in più, quindi un 422. */
    chiama("/op/movimento", {
      method: "POST",
      body: { oggetto_id: oggetto.oggetto_id, a_casa: destinataria, dal: oggi, al: al }
    }).then(function () {
      mostra(esito, "Prestito proposto. Diventa effettivo quando la Casa che riceve conferma.");
      caricaInventario("");
      caricaMovimenti();
    }).catch(function (e) {
      mostra(errore, "Proposta non registrata: " + messaggioErrore(e));
    });
  }

  /* ---------------------------------------------------------------- movimenti */

  function caricaMovimenti() {
    var elenco = $("acc-attrezzoteca-elenco-movimenti");
    var stato = $("acc-attrezzoteca-stato-movimenti");
    if (!elenco) return;

    elenco.textContent = "";
    mostra(stato, "Lettura in corso…");

    chiama("/op/movimenti_da_confermare").then(function (dati) {
      var movimenti = (dati && dati.movimenti) || [];
      mostra(stato, "");
      if (!movimenti.length) {
        mostra(stato, "Nessun prestito in attesa di conferma.");
        return;
      }
      movimenti.forEach(function (m) { elenco.appendChild(rigaMovimento(m)); });
    }).catch(function (e) {
      mostra(stato, "Movimenti non disponibili: " + messaggioErrore(e));
    });
  }

  function rigaMovimento(m) {
    var voce = document.createElement("li");
    voce.className = "filetto filetto--coda";

    var testo = document.createElement("p");
    testo.textContent =
      (m.oggetto || "oggetto " + m.oggetto_id) +
      " per " + (m.oggetto_quantita != null ? m.oggetto_quantita : "—") +
      " da " + (m.da_casa_slug || "—") + " a " + (m.a_casa_slug || "—") +
      " · dal " + (m.dal || "—") + (m.al ? " al " + m.al : "") +
      (m.giorni_attesa ? " · in attesa da " + m.giorni_attesa + (m.giorni_attesa === 1 ? " giorno" : " giorni") : "");
    voce.appendChild(testo);

    var azioni = document.createElement("p");
    azioni.className = "acc-attrezzoteca-azioni";

    /* Le azioni ammesse si mostrano in base al verso del movimento, e non è una seconda copia della
       regola: è la dichiarazione di **cosa** si può chiedere. Chi decide resta `conferma_movimento`,
       che rifiuta con un messaggio parlante se la richiesta non spetta a questa Casa. */
    var mia = casaCorrente();
    if (String(m.a_casa_slug || "") === String(mia || "")) {
      azioni.appendChild(pulsanteMovimento(m, "conferma", "Conferma la ricezione"));
      azioni.appendChild(pulsanteMovimento(m, "rifiuta", "Rifiuta"));
    }
    if (String(m.da_casa_slug || "") === String(mia || "")) {
      azioni.appendChild(pulsanteMovimento(m, "rientro", "Segna il rientro"));
    }
    voce.appendChild(azioni);
    return voce;
  }

  function pulsanteMovimento(m, azione, etichetta) {
    var bottone = document.createElement("button");
    bottone.type = "button";
    bottone.className = "azione";
    bottone.textContent = etichetta;
    bottone.addEventListener("click", function () {
      var errore = $("acc-attrezzoteca-errore");
      var esito = $("acc-attrezzoteca-esito");
      mostra(errore, "");
      mostra(esito, "");
      chiama("/op/movimento/" + encodeURIComponent(m.id) + "/conferma", {
        method: "POST",
        body: { azione: azione }
      }).then(function () {
        mostra(esito, "Movimento aggiornato: " + (azione === "conferma" ? "ricezione confermata" : azione === "rifiuta" ? "prestito rifiutato" : "rientro registrato") + ".");
        caricaMovimenti();
        caricaInventario("");
      }).catch(function (e) {
        mostra(errore, "Movimento non aggiornato: " + messaggioErrore(e));
      });
    });
    return bottone;
  }

  /* ---------------------------------------------------------------- API */

  window.TrasiAccount = window.TrasiAccount || { avvii: {} };
  window.TrasiAccount.avvii = window.TrasiAccount.avvii || {};
  window.TrasiAccount.avvii["attrezzoteca"] = function () {
    var modulo = $("acc-attrezzoteca-modulo-cerca");
    if (modulo) {
      modulo.addEventListener("submit", function (evento) {
        evento.preventDefault();
        caricaInventario(($("acc-attrezzoteca-cerca").value || "").trim());
      });
    }
    caricaInventario("");
    caricaMovimenti();
  };
})();
