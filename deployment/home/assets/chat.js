/* chat.js — la macchina a stati della Home (§4.1.1 del piano) e la chat compatta per le altre pagine.
 *
 * CINQUE STATI, e il DOM li dichiara: `#chat[data-stato="…"]`. Uno solo è attivo per volta, e le
 * transizioni sono quelle della tabella di §4.1.1 — nessuna in più:
 *
 *   S0 vuota     la Home si apre senza `?c=`: titolo e compositore centrati, suggerimenti visibili
 *   S1 attesa    invio: il compositore scende in basso e si aggancia; il turno OPERATORE è subito
 *                in colonna e sotto compare il turno ASSISTENTE con «Ricerca nella memoria della
 *                rete in corso…» e `aria-busy="true"`
 *   S2 chat      arriva la risposta: il turno mostra il testo e l'etichetta di provenienza **verbatim**
 *   S3 errore    `422` dal filtro anti-PII: la frase dice il perché, il testo **resta** nel compositore
 *   S4 guasto    `503`: «L'assistente non risponde in questo momento.» e il testo resta
 *   S5 riaperta  `?c=<id>` o click nello storico: come S2, con la data del primo turno in testa
 *
 * TRE COSE CHE QUESTO FILE NON FA, e sono scelte, non omissioni.
 *
 * 1. **Non usa `localStorage`.** V5: nel browser resta solo lo slug della Casa (che la pagina di
 *    accesso manda nell'URL). La conversazione corrente vive in una variabile di modulo e, quando è un
 *    fatto condivisibile, nell'URL (`?c=<id>`) — che è il posto giusto: si può incollare, e
 *    ricaricando la pagina si riapre la stessa conversazione.
 * 2. **Non conserva la domanda quando fallisce.** Un `422` è un testo rifiutato, un `503` è un
 *    guasto: nessuno dei due scrive un turno (§4.1.3). Il testo resta **nel campo**, così
 *    l'operatore lo rilegge e lo corregge, ma non entra nella conversazione.
 * 3. **Non riformatta l'etichetta di provenienza.** `fonte` è già composta dallo shim, verbatim:
 *    qui si copia nella riga e basta. Riformattare date e ore lato pagina renderebbe il badge
 *    della chat diverso da quello del biglietto, ed è il difetto che V3 esiste per impedire.
 *
 * L'astensione («Non trovo informazioni su questo nella memoria della rete.») arriva con `fonte:
 * null`: nessuna etichetta, perché non c'è fonte. La regola sta nel dato, non in un confronto di
 * stringhe qui: se la frase del modello cambia, questo file non se ne accorge e non deve.
 */
(function () {
  "use strict";

  var LIMITE = 2000;

  /* Testi. Quelli degli stati sono **verbatim** da §3.4 del piano: si riusano, non si riscrivono. */
  var TESTO_ATTESA = "Ricerca nella memoria della rete in corso…";
  var TESTO_422 = "Il testo sembra contenere un dato personale — telefono, email, codice fiscale — e non è stato inviato. Si può riscrivere senza quel dato.";
  var TESTO_503 = "L'assistente non risponde in questo momento. La domanda resta scritta qui sotto.";
  var TESTO_SESSIONE = "La sessione è scaduta. Si torna all'accesso: la domanda resta scritta qui sotto.";
  var TESTO_STORICO_VUOTO = "Nessuna conversazione negli ultimi 30 giorni.";
  var TESTO_TRONCATO = "La risposta è più lunga di quanto la memoria della rete conserva.";
  var TESTO_COMPATTA_VUOTA = "Nessuno scambio nella conversazione corrente.";
  /* Quanto testo entra nella chat compatta della sidebar: è una misura di **spazio**, e il taglio è
     dichiarato dalla riga `TESTO_TRONCATO` — mai da soli puntini, che lasciano il dubbio se la
     risposta sia finita così. */
  var LIMITE_COMPATTA = 220;

  /* ---------------------------------------------------------------- riferimenti al DOM */

  function $(id) { return document.getElementById(id); }

  var chat = null;
  var turni = null;
  var campo = null;
  var avviso = null;
  var testaAperta = null;
  var contatore = null;
  var suggerimenti = null;
  var modulo = null;

  /* Stato in memoria, uno solo per pagina (§3.2: la conversazione corrente è una sola).
     `conversazioneViva` distingue una conversazione che ha **almeno una risposta** da una riga nata
     e mai usata: la prima è un fatto e si conserva, la seconda si dimentica — nello storico non
     compare comunque (§4.1.3), e un `?c=` verso una conversazione invisibile è un rimando che non
     porta da nessuna parte. */
  var conversazione = null;   // id della conversazione corrente, o null
  var conversazioneViva = false;
  var invioInCorso = false;   // evita il doppio invio: due click su «Chiedi» sono due domande distinte

  /* ---------------------------------------------------------------- utilità */

  /* La Casa come la mostra la testata. `Trasi.pronto` è la Promise di `GET /me`: i suggerimenti la
     aspettano, perché il nome della Casa nei testi non si inventa. */
  function nomeCasa() {
    try { return (window.Trasi && window.Trasi.nomeCasa && window.Trasi.nomeCasa()) || ""; }
    catch (e) { return ""; }
  }

  function mostra(el, testo) {
    if (!el) return;
    el.textContent = testo;
    el.hidden = false;
  }

  function nascondi(el) {
    if (el) el.hidden = true;
  }

  /* Un elemento con del testo dentro. `textContent` e mai `innerHTML`: la risposta dell'assistente
     è testo di un modello, e interpretarla come HTML significherebbe eseguire ciò che il modello
     ha scritto. Il prezzo è che il markdown resta visibile — è un prezzo accettabile, e comunque
     la UI non promette markdown reso (§12: nessuna funzione di resa). */
  function elemento(tag, classe, testo) {
    var el = document.createElement(tag);
    if (classe) el.className = classe;
    if (testo !== undefined && testo !== null) el.textContent = testo;
    return el;
  }

  /* L'ora dell'ultimo turno, per lo storico. `toLocaleTimeString` con `it-IT` e il fuso del
     browser: è l'orologio che l'operatore ha davanti — non quello del server. */
  function oraBreve(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    return d.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
  }

  function dataEstesa(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    var data = d.toLocaleDateString("it-IT", { day: "2-digit", month: "2-digit", year: "numeric" });
    return data + ", " + d.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
  }

  /* ---------------------------------------------------------------- i turni nel DOM */

  /* Un turno. `autore` è `operatore` o `assistente`; la classe lo dichiara e il testo dell'etichetta
     di turno è in **maiuscolo** come chiede il contratto (`OPERATORE`/`ASSISTENTE`). */
  function disegnaTurno(autore, testo, fonte, inAttesa) {
    var operatore = autore === "operatore";
    var turno = elemento("div", "turno " + (operatore ? "turno--operatore" : "turno--assistente"));
    if (inAttesa) turno.classList.add("turno--attesa");
    if (inAttesa) turno.setAttribute("aria-busy", "true");

    turno.appendChild(elemento("p", "turno-chi", operatore ? "OPERATORE" : "ASSISTENTE"));
    turno.appendChild(elemento("p", "turno-testo", testo || ""));

    /* L'etichetta di provenienza **sotto** la risposta, su riga propria, e solo se c'è: `null` è
       l'astensione, e l'astensione non ha fonte. Il testo si copia senza toccarlo. */
    if (!operatore && typeof fonte === "string" && fonte) {
      var etichetta = elemento("p", "etichetta chat-provenienza", fonte);
      if (fonte.indexOf("[Esterna") === 0) etichetta.classList.add("etichetta--esterna");
      turno.appendChild(etichetta);
    }
    turni.appendChild(turno);
    turno.scrollIntoView({ block: "nearest" });
    return turno;
  }

  /* Porta la pagina in uno dei cinque stati. Tutto ciò che cambia fra gli stati passa da qui. */
  function stato(nuovo) {
    if (chat) chat.setAttribute("data-stato", nuovo);
  }

  function svuotaTurni() {
    if (turni) turni.textContent = "";
  }

  /* ---------------------------------------------------------------- il compositore */

  function aggiornaContatore() {
    if (contatore && campo) contatore.textContent = campo.value.length + "/" + LIMITE;
  }

  function svuotaCampo() {
    if (!campo) return;
    campo.value = "";
    aggiornaContatore();
  }

  function mostraAvviso(testo, guasto) {
    if (!avviso) return;
    avviso.textContent = testo;
    avviso.hidden = false;
    /* `--guasto` cambia il segno di stato (bordo tenue invece di giallo sole) e **niente altro**:
       la parola c'è in entrambi i casi, il colore non è mai l'unico canale. */
    avviso.classList.toggle("chat-avviso--guasto", !!guasto);
  }

  /* ---------------------------------------------------------------- invio */

  /* Apre la conversazione se non c'è: `POST /op/conversazioni`, che lega la sessione Onyx alla
     riga. Una sola volta per conversazione — è il difetto che `chat.js` non deve reintrodurre
     lato pagina (una `create-chat-session` per messaggio) dopo che lo shim l'ha corretto. */
  function apriConversazione() {
    if (conversazione !== null) return Promise.resolve(conversazione);
    return window.Trasi.api("/op/conversazioni", { method: "POST", body: {} }).then(function (dati) {
      conversazione = dati.conversazione_id;
      /* L'URL porta la conversazione: `?c=<id>` è il fatto condivisibile (§4.1.1), e ricaricando la
         pagina si riapre la stessa. `replaceState` e non `pushState`: aprire una conversazione non
         è una navigazione da annullare col tasto indietro — l'ha aperta l'invio, non un click. */
      var url = new URL(window.location.href);
      url.searchParams.set("c", conversazione);
      window.history.replaceState(null, "", url.toString());
      if (window.TrasiStorico) window.TrasiStorico.ricarica();
      return conversazione;
    });
  }

  function invia(testo) {
    if (invioInCorso) return;
    var messaggio = (testo !== undefined ? testo : (campo ? campo.value : "")).trim();
    if (!messaggio) return;

    invioInCorso = true;
    nascondi(avviso);

    /* S1 — ATTESA. Il turno dell'operatore è **subito** in colonna, e sotto compare il turno
       dell'assistente con la frase di attesa: è l'attesa a dire all'operatore che la domanda è
       partita. Il compositore scende in basso perché lo stato cambia, e lo governa il CSS. */
    stato("attesa");
    disegnaTurno("operatore", messaggio);
    var inAttesa = disegnaTurno("assistente", TESTO_ATTESA, null, true);

    var bottone = $("chat-chiedi");
    if (bottone) bottone.disabled = true;

    apriConversazione()
      .then(function (id) {
        return window.Trasi.api("/op/conversazioni/" + id + "/messaggi", {
          method: "POST",
          body: { messaggio: messaggio }
        });
      })
      .then(function (dati) {
        /* S2 — CHAT. L'attesa sparisce e al suo posto c'è la risposta, con la sua etichetta
           verbatim. `fonte: null` è l'astensione: nessuna etichetta. */
        inAttesa.remove();
        disegnaTurno("assistente", dati.risposta, dati.fonte);
        conversazioneViva = true;
        stato("chat");
        svuotaCampo();
        if (window.TrasiStorico) window.TrasiStorico.ricarica();
      })
      .catch(function (errore) {
        inAttesa.remove();
        gestisciErrore(errore, messaggio);
      })
      .then(
        function () {
          invioInCorso = false;
          if (bottone) bottone.disabled = false;
          if (campo) campo.focus();
        },
        function () {
          invioInCorso = false;
          if (bottone) bottone.disabled = false;
        }
      );
  }

  /* Torna allo stato vuoto **con una frase al posto dei turni**. S3 e S4 finiscono qui, e non è una
     semplificazione: il diagramma di §4.1.1 li disegna come un ritorno a VUOTO («errore 422/503 — la
     domanda resta scritta»), la tabella dice «nessun turno aggiunto», e la frase del 503 — «La domanda
     resta scritta qui sotto» — indica il compositore, che è sotto. Quindi: i turni disegnati durante
     l'attesa escono dal DOM, il testo resta nel campo, e l'avviso dice cosa è successo.

     `data-stato` distingue comunque `errore` da `guasto` da `vuota`: il CSS li rende uguali nel
     layout e diversi nel segno di stato, e un test può leggerli. Uno stato che non si distingue non
     serve a niente. */
  function tornaAlVuotoConAvviso(nuovoStato, testo, guasto) {
    if (turni) turni.textContent = "";
    mostraAvviso(testo, guasto);
    stato(nuovoStato);
  }

  /* La conversazione corrente ha almeno una risposta? Se no, è una riga nata e mai usata (l'invio
     è fallito): la si dimentica e si pulisce l'URL, perché nello storico non compare comunque
     (§4.1.3) e un `?c=` che porta a una conversazione invisibile è un rimando che non porta da
     nessuna parte. Se invece una risposta c'è già, la conversazione è un fatto e si tiene. */
  function dimenticaSeVuota() {
    if (conversazioneViva) return;
    conversazione = null;
    var url = new URL(window.location.href);
    url.searchParams.delete("c");
    window.history.replaceState(null, "", url.toString());
  }

  function gestisciErrore(errore, messaggio) {
    var stato_http = errore && errore.stato;

    /* Il testo resta **nel compositore** in tutti e tre i casi: è un testo che l'operatore deve poter
       correggere, e riscriverlo da capo dopo aver letto il motivo sarebbe una punizione. */
    campo.value = messaggio;
    aggiornaContatore();

    if (stato_http === 422) {
      tornaAlVuotoConAvviso("errore", TESTO_422);
      dimenticaSeVuota();
      return;
    }

    if (stato_http === 503) {
      tornaAlVuotoConAvviso("guasto", TESTO_503, true);
      dimenticaSeVuota();
      return;
    }

    if (errore && errore.sessioneScaduta) {
      /* 401: `shell.js` riporta all'accesso, e il testo resta nel campo (§3.3). La conversazione non
         si dimentica: la sessione può tornare, e con essa la conversazione se ha già una risposta. */
      tornaAlVuotoConAvviso("guasto", TESTO_SESSIONE, true);
      return;
    }

    /* Altro (404 su una conversazione sparita, 500): la conversazione non è più quella corrente, quindi
       si dimentica — il prossimo invio ne apre una nuova invece di insistere su un id morto. */
    conversazione = null;
    conversazioneViva = false;
    tornaAlVuotoConAvviso("guasto", TESTO_503, true);
    dimenticaSeVuota();
  }

  /* ---------------------------------------------------------------- S5 — riaprire una conversazione */

  /* Riapre una conversazione dal suo id: i turni salvati, con le etichette **come sono state
     scritte** — è ciò che rende il ricaricamento della pagina la stessa cosa della chat dal vivo
     (la fonte è la stringa salvata, non una ricomposta). La data del **primo** turno va in testa. */
  function apri(id) {
    conversazione = id;
    svuotaTurni();
    nascondi(avviso);
    stato("riaperta");

    return window.Trasi.api("/op/conversazioni/" + id).then(function (dati) {
      var turniSalvati = dati.turni || [];
      conversazioneViva = turniSalvati.length > 0;
      if (testaAperta) {
        var primo = turniSalvati.length ? turniSalvati[0].ts : dati.creato_ts;
        var casa = nomeCasa();
        mostra(testaAperta, "Conversazione del " + dataEstesa(primo) + (casa ? " · " + casa : ""));
      }
      turniSalvati.forEach(function (turno) {
        disegnaTurno(turno.ruolo, turno.testo, turno.fonte);
      });
      /* Una conversazione senza turni (riaperta prima che il primo invio risponda) torna allo
         stato vuoto invece di mostrare una pagina vuota con un compositore agganciato. */
      if (!turniSalvati.length) stato("vuota");
      if (window.TrasiStorico) window.TrasiStorico.segnaCorrente(id);
      return dati;
    }).catch(function (errore) {
      /* 404: la conversazione non esiste o non è di questa Casa (lo shim risponde uguale, e la
         pagina non deve distinguere). Si torna allo stato vuoto e lo si dice in parole. */
      conversazione = null;
      conversazioneViva = false;
      stato("vuota");
      if (testaAperta) nascondi(testaAperta);
      if (errore && errore.sessioneScaduta) return null;
      mostraAvviso("Questa conversazione non è più disponibile.", true);
      return null;
    });
  }

  function nuovaConversazione() {
    conversazione = null;
    conversazioneViva = false;
    svuotaTurni();
    svuotaCampo();
    nascondi(avviso);
    if (testaAperta) nascondi(testaAperta);
    stato("vuota");
    var url = new URL(window.location.href);
    url.searchParams.delete("c");
    window.history.replaceState(null, "", url.toString());
    if (window.TrasiStorico) window.TrasiStorico.segnaCorrente(null);
    if (campo) campo.focus();
  }

  /* ---------------------------------------------------------------- chat compatta (Osservatorio, Account) */

  /* L'ultimo scambio della conversazione corrente, in miniatura, con il compositore compatto.
     La disegna questa pagina perché la conversazione è sua (§4.2.1: «la conversazione corrente è
     una sola per sessione»): Osservatorio e Account mostrano quella, non ne aprono una loro.

     La risposta è **troncata** — la compatta è un promemoria, non il posto in cui si legge — e il
     taglio è dichiarato da una frase, non da puntini sospesi: chi legge sa che c'è dell'altro e il
     collegamento «Apri nella Home» porta al resto. */
  function renderCompatta(contenitore) {
    if (!contenitore) return;
    contenitore.textContent = "";

    var scatola = elemento("div", "chat-compatta");
    var corpo = elemento("div", "chat-compatta-turni");
    var campoCompatto = elemento("textarea", "chat-campo");
    campoCompatto.rows = 2;
    campoCompatto.maxLength = LIMITE;
    campoCompatto.id = "chat-compatta-campo";
    campoCompatto.setAttribute("aria-label", "La domanda della persona");

    var bottone = elemento("button", "bottone bottone--principale", "Chiedi");
    bottone.type = "button";

    var moduloCompatto = elemento("div", "compositore");
    var etichetta = elemento("label", "chat-etichetta", "La domanda della persona");
    etichetta.setAttribute("for", "chat-compatta-campo");
    moduloCompatto.appendChild(etichetta);
    moduloCompatto.appendChild(campoCompatto);
    moduloCompatto.appendChild(bottone);

    scatola.appendChild(corpo);
    scatola.appendChild(moduloCompatto);
    contenitore.appendChild(scatola);

    function avviso(testo, guasto) {
      var esistente = scatola.querySelector(".chat-avviso");
      if (esistente) esistente.remove();
      scatola.insertBefore(
        elemento("p", "chat-avviso" + (guasto ? " chat-avviso--guasto" : ""), testo),
        corpo
      );
    }

    function nullaDaMostrare() {
      corpo.textContent = "";
      corpo.appendChild(elemento("p", "chat-compatta-scelta", TESTO_COMPATTA_VUOTA));
    }

    /* L'id della conversazione corrente. In Home è la variabile di modulo; in Osservatorio e in
       Account la Home non è aperta, quindi la sola fonte è l'URL (`?c=<id>`), che è dove §4.1.1
       dice che il fatto condivisibile vive. Senza id: nessuno scambio da mostrare, e il
       compositore ne apre uno al primo invio. */
    function idCorrente() {
      return conversazione !== null ? conversazione : leggiIdDaUrl();
    }

    function disegna() {
      var id = idCorrente();
      if (id === null) {
        nullaDaMostrare();
        return;
      }
      window.Trasi.api("/op/conversazioni/" + id).then(function (dati) {
        var elenco = (dati.turni || []).slice(-2);
        if (!elenco.length) {
          nullaDaMostrare();
          return;
        }
        corpo.textContent = "";
        elenco.forEach(function (turno) {
          var operatore = turno.ruolo === "operatore";
          var riga = elemento("div", "turno " + (operatore ? "turno--operatore" : "turno--assistente"));
          riga.appendChild(elemento("p", "turno-chi", operatore ? "OPERATORE" : "ASSISTENTE"));
          var testo = turno.testo || "";
          var tagliato = testo.length > LIMITE_COMPATTA;
          riga.appendChild(elemento("p", "turno-testo", tagliato ? testo.slice(0, LIMITE_COMPATTA) + "…" : testo));
          if (tagliato) riga.appendChild(elemento("p", "chat-aiuto", TESTO_TRONCATO));
          /* L'etichetta si copia **verbatim** anche qui: è la stessa stringa salvata nel turno, non
             una ricomposta per la colonna stretta. Troncarla sarebbe riscrivere la provenienza. */
          if (!operatore && turno.fonte) {
            riga.appendChild(elemento("p", "etichetta chat-provenienza", turno.fonte));
          }
          corpo.appendChild(riga);
        });
      }).catch(function (errore) {
        /* La conversazione non è più leggibile (404) o la rete non risponde: in entrambi i casi la
           compatta mostra il vuoto dichiarato e il compositore resta usabile per aprirne una nuova. */
        if (errore && errore.stato === 404) conversazione = null;
        nullaDaMostrare();
      });
    }

    function inviaCompatto() {
      var testo = campoCompatto.value.trim();
      if (!testo) return;
      bottone.disabled = true;
      var id = idCorrente();
      var apertura = id !== null
        ? Promise.resolve(id)
        : window.Trasi.api("/op/conversazioni", { method: "POST", body: {} })
            .then(function (dati) { return dati.conversazione_id; });

      apertura
        .then(function (nuovoId) {
          return window.Trasi.api("/op/conversazioni/" + nuovoId + "/messaggi", {
            method: "POST",
            body: { messaggio: testo }
          }).then(function () {
            conversazione = nuovoId;
            campoCompatto.value = "";
            bottone.disabled = false;
            disegna();
          });
        })
        .catch(function (errore) {
          /* Gli stessi due casi della Home e lo stesso trattamento: la frase dichiarata e **il testo
             che resta nel campo**, perché è l'unica cosa che si può correggere da qui. */
          bottone.disabled = false;
          if (errore && errore.stato === 422) avviso(TESTO_422);
          else if (errore && errore.sessioneScaduta) avviso(TESTO_SESSIONE, true);
          else avviso(TESTO_503, true);
        });
    }

    bottone.addEventListener("click", inviaCompatto);
    disegna();
  }

  function leggiIdDaUrl() {
    var valore = new URL(window.location.href).searchParams.get("c");
    if (!valore) return null;
    var numero = parseInt(valore, 10);
    return isNaN(numero) ? null : numero;
  }

  /* ---------------------------------------------------------------- avvio (solo in Home) */

  function avvia() {
    chat = $("chat");
    turni = $("chat-turni");
    campo = $("chat-testo");
    avviso = $("chat-avviso");
    testaAperta = $("chat-aperta");
    contatore = $("chat-contatore");
    suggerimenti = $("chat-suggerimenti");
    modulo = $("chat-compositore");
    if (!chat || !campo || !modulo) return;

    aggiornaContatore();

    modulo.addEventListener("submit", function (evento) {
      evento.preventDefault();
      invia();
    });

    /* `Invio` invia, `Maiusc+Invio` va a capo: in uno sportello si scrive una domanda, non un
       paragrafo — e chi vuole il capo lo ottiene senza toccare il mouse. */
    campo.addEventListener("keydown", function (evento) {
      if (evento.key === "Enter" && !evento.shiftKey) {
        evento.preventDefault();
        invia();
      }
    });
    campo.addEventListener("input", aggiornaContatore);

    /* I suggerimenti: un click riempie il campo e **invia** (S0 → S1, §4.1.1). Il testo del
       suggerimento è nel `data-domanda`, già con il nome della Casa al posto di `{casa}`. */
    if (suggerimenti) {
      var bottoni = suggerimenti.querySelectorAll(".suggerimento");
      for (var i = 0; i < bottoni.length; i++) {
        bottoni[i].addEventListener("click", function (evento) {
          var domanda = evento.currentTarget.getAttribute("data-domanda") || "";
          campo.value = domanda;
          aggiornaContatore();
          invia(domanda);
        });
      }
    }

    /* Il nome della Casa nei due suggerimenti che lo portano. `Trasi.pronto` si risolve con
       `GET /me` (o `null` con 401): senza Casa il segnaposto resta e la frase resta leggibile
       — meglio di un testo con una graffa dentro, che è il caso da evitare. */
    if (window.Trasi && window.Trasi.pronto) {
      window.Trasi.pronto.then(function () {
        var casa = nomeCasa();
        if (!casa || !suggerimenti) return;
        var conCasa = suggerimenti.querySelectorAll(".suggerimento");
        for (var k = 0; k < conCasa.length; k++) {
          var grezzo = conCasa[k].getAttribute("data-domanda") || "";
          if (grezzo.indexOf("{casa}") < 0) continue;
          var riscritto = grezzo.split("{casa}").join(casa);
          conCasa[k].setAttribute("data-domanda", riscritto);
          conCasa[k].textContent = riscritto;
        }
      });
    }

    /* S5 all'avvio: `?c=<id>` riapre quella conversazione. `?c=` senza numero si ignora — l'URL
       non è un input affidabile, e un id non numerico non esiste. */
    var daUrl = leggiIdDaUrl();
    if (daUrl !== null) apri(daUrl);
  }

  /* L'aggancio per le altre pagine. `renderCompatta` è l'unica cosa che esce da questo file:
     Osservatorio e Account non devono sapere come è fatta la chat, e non devono poterla riscrivere. */
  window.TrasiChat = { renderCompatta: renderCompatta, apri: apri, nuova: nuovaConversazione };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", avvia);
  else avvia();
})();
