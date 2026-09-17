/* scheda.js — la scheda del luogo: pannello **accanto** alla mappa, mai al suo posto.
 *
 * Tre cose che il piano chiede e che si vedono solo qui.
 *
 * 1. **La mappa resta.** La scheda prende il posto dell'elenco nella colonna destra; la mappa è
 *    nella colonna sinistra e non si tocca. Il pin resta evidenziato, gli altri attenuati. Il
 *    criterio: a 1280 px scheda **e** mappa visibili insieme (§4.2.2).
 * 2. **Si chiude con «← Torna all'elenco» e con `Esc`**, e in entrambi i casi il focus torna alla
 *    voce dell'elenco da cui si era partiti — non al `<body>`, che perderebbe il posto di lettura.
 * 3. **Le sezioni dichiarano ciò che manca.** Per un POI esterno: «Servizi: non nella memoria
 *    della rete» e «Eventi: nessun evento collegato a questo luogo». Non è un ripiego: il legame
 *    `evento ↔ luogo.id` non esiste (`evento.luogo_testo` è testo libero, §11 Q-04), e inventarlo
 *    sarebbe peggio che dichiararlo.
 *
 * **Eventi come elenco per data, mai una griglia di celle vuote.** In memoria ci sono 7 eventi,
 * di cui 4 futuri, tutti di una Casa: una griglia mensile mostrerebbe 27 celle vuote su 30. Il
 * selettore `settimana | mese` cambia l'intervallo, non la forma. Per gli eventi di una Casa si
 * chiede l'intervallo vero (`GET /op/eventi?dal&al`), raggruppato per giorno.
 *
 * **Nessuna azione che non sappia dove andare.** `[Stampa il biglietto]` è un collegamento a
 * `GET /op/biglietto`, che esiste. `[Segnala un cambiamento]` porta alla sezione Registra
 * dell'Account: la via che **scrive** — `POST /op/proponi_modifica` — non è di questa scheda, e un
 * bottone che chiama un endpoint inesistente è peggio di un collegamento che porta dove la cosa si
 * fa davvero.
 */
(function () {
  "use strict";

  var pannello = null;
  var corpo = null;
  var pezzoElenco = null;
  var chiaveDaCuiSiEPartiti = null;
  var periodo = "settimana";
  var voceCorrente = null;

  var GIORNI = ["domenica", "lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato"];
  var MESI = ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"];

  /* ------------------------------------------------------------------ utilità */

  function testo(tag, classe, contenuto) {
    var el = document.createElement(tag);
    if (classe) { el.className = classe; }
    if (contenuto !== undefined && contenuto !== null) { el.textContent = contenuto; }
    return el;
  }

  function rigaDato(etichetta, valore) {
    var riga = document.createElement("div");
    riga.appendChild(testo("dt", null, etichetta));
    riga.appendChild(testo("dd", null, valore));
    return riga;
  }

  function dataItaliana(iso) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) { return ""; }
    return d.getDate() + "/" + String(d.getMonth() + 1).padStart(2, "0") + "/" + d.getFullYear();
  }

  function giornoEsteso(iso) {
    var d = new Date(iso + "T12:00:00");
    if (isNaN(d.getTime())) { return iso; }
    return GIORNI[d.getDay()] + " " + d.getDate() + " " + MESI[d.getMonth()];
  }

  /* Le date della finestra (`dal`, `al`) come stringhe ISO locali: costruirle con `toISOString()`
   * le sposterebbe di un giorno per il fuso, e la scheda chiederebbe gli eventi di ieri. */
  function isoLocale(d) {
    return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" +
      String(d.getDate()).padStart(2, "0");
  }

  function finestra() {
    var oggi = new Date();
    var giorni = periodo === "mese" ? 30 : 7;
    var al = new Date(oggi.getTime() + giorni * 86400000);
    return { dal: isoLocale(oggi), al: isoLocale(al) };
  }

  /* ------------------------------------------------------------------ la testata */

  function testata(voce) {
    var testa = testo("div", "mappa-scheda-testa");
    var titolo = testo("h2", null, voce.nome);
    titolo.id = "mappa-scheda-titolo";
    testa.appendChild(titolo);

    var tipo = testo("p", "mappa-conteggio",
      voce.livello === "casa" ? "Casa della rete" :
        voce.livello === "luogo" ? "Luogo della rete" : "Trovato su OpenStreetMap, non verificato dalla rete");
    testa.appendChild(tipo);

    /* Il badge **verbatim** dallo shim, su riga propria (V3): è l'etichetta di provenienza, e
     * ricomporla qui — anche solo cambiando un separatore — romperebbe il confronto carattere per
     * carattere che il piano pretende. */
    var badge = testo("p", "etichetta " + (voce.livello === "esterna" ? "etichetta--esterna" : "etichetta--kb"), voce.badge);
    testa.appendChild(badge);
    return testa;
  }

  function dati(voce) {
    var lista = testo("dl", "mappa-scheda-dati");
    lista.appendChild(rigaDato("Tipo", voce.tipo || "non dichiarato"));
    if (voce.livello === "casa" && voce.ente_gestore) {
      lista.appendChild(rigaDato("Ente gestore", voce.ente_gestore));
    }
    if (voce.zona) { lista.appendChild(rigaDato("Zona", voce.zona)); }
    if (voce.casaNome && voce.livello !== "casa") {
      lista.appendChild(rigaDato("Casa di riferimento", voce.casaNome));
    }
    /* L'indirizzo dichiara l'assenza invece di stampare una riga vuota: nel seed nessuna Casa ha
     * un indirizzo, e «—» è l'informazione vera («non lo sappiamo»), non un difetto di resa. */
    lista.appendChild(rigaDato("Indirizzo", voce.indirizzo || "non dichiarato nella memoria"));
    /* Due assenze diverse, due frasi: il luogo senza coordinate (P1.2) non ha una posizione in memoria —
     * non è la Casa a mancare; la Casa manca solo per i ruoli senza Casa (`rete`, `ti`). */
    var senzaPosizione = voce.lat === null || voce.lat === undefined || voce.lon === null || voce.lon === undefined;
    lista.appendChild(rigaDato("Distanza dalla Casa", senzaPosizione
      ? "posizione del luogo non disponibile in memoria"
      : (voce.distanza_m === null || voce.distanza_m === undefined
        ? "non calcolabile senza una Casa di riferimento"
        : metri(voce.distanza_m) + " in linea d'aria")));
    /* «orari non disponibili» è testo **verbatim** del contratto (§7): si scrive così, non si
     * parafrasa, e il luogo **non si scarta** per questo. */
    lista.appendChild(rigaDato("Orari", voce.orari_testo || "orari non disponibili"));
    if (voce.livello === "casa") {
      if (voce.da_validare) {
        lista.appendChild(rigaDato("Dati", "in attesa di validazione dalla rete"));
      }
      if (voce.orari_provvisori) {
        lista.appendChild(rigaDato("Orari", "provvisori"));
      }
    }
    if (voce.url) { lista.appendChild(rigaDato("Riferimento", voce.url)); }
    return lista;
  }

  function metri(valore) {
    if (valore < 1000) { return Math.round(valore) + " m"; }
    return (valore / 1000).toFixed(1).replace(".", ",") + " km";
  }

  /* ------------------------------------------------------------------ azioni */

  function azioni(voce) {
    var riga = testo("div", "mappa-scheda-azioni");

    /* Il biglietto: si apre in una **scheda nuova** (criterio di done di T-UX-11), perché è un
     * foglio da stampare e la pagina dietro resta quella su cui si stava lavorando. Il riferimento
     * è l'id del luogo in memoria, o `osm:<tipo>:<id>` per un POI — la forma che l'endpoint accetta
     * per un punto che non è in memoria. */
    var riferimento = voce.livello === "esterna" ? voce.riferimento : String(voce.id);
    if (riferimento) {
      var stampa = testo("a", "bottone", "[Stampa il biglietto]");
      stampa.href = "/api/shim/op/biglietto?luogo_id=" + encodeURIComponent(riferimento);
      stampa.target = "_blank";
      stampa.rel = "noopener";
      riga.appendChild(stampa);
    }

    /* «Segnala un cambiamento»: la via che **scrive** è `POST /op/proponi_modifica`, e la sezione
     * che la offre è «Registra» dell'Account (§4.3, riga 4). Puntare a un endpoint che questa
     * scheda non possiede sarebbe un bottone che non sa dove andare. */
    var segnala = testo("a", "bottone", "[Segnala un cambiamento]");
    segnala.href = "account.html#registra";
    riga.appendChild(segnala);
    return riga;
  }

  /* ------------------------------------------------------------------ servizi */

  /* Per una **Casa**: le schede di servizio, da `GET /op/servizi?casa_id`. Per un **POI**: la
   * dichiarazione dell'assenza. L'endpoint non si chiama per un POI — non ha una Casa, e un
   * `404` trasformato in un messaggio d'errore direbbe una cosa falsa («servizi non disponibili»
   * invece di «non è una Casa»). */
  function servizi(voce, sezione) {
    if (voce.livello === "esterna") {
      sezione.appendChild(testo("p", "mappa-vuoto", "Servizi: non nella memoria della rete"));
      return;
    }
    if (voce.livello === "luogo" && !voce.casaId) {
      /* Un luogo di servizio che non appartiene a nessuna Casa (URP, ASL, INPS): non ha schede di
       * servizio, perché non c'è una Casa che le dichiari. */
      sezione.appendChild(testo("p", "mappa-vuoto", "Servizi: non nella memoria della rete"));
      return;
    }
    var casaId = voce.livello === "casa" ? voce.id : voce.casaId;
    sezione.appendChild(testo("p", "mappa-vuoto", "Lettura in corso…"));
    window.Trasi.api("/op/servizi?casa_id=" + encodeURIComponent(casaId)).then(function (dati) {
      sezione.textContent = "";
      if (!dati.servizi || !dati.servizi.length) {
        /* Il vuoto è un'informazione: su questo database `scheda_servizio` ha 0 righe, e la
         * sezione lo **dichiara** invece di restare muta (§4.2.2). */
        sezione.appendChild(testo("p", "mappa-vuoto", "Nessun servizio in memoria per questa Casa."));
        return;
      }
      var lista = testo("ul", "elenco");
      dati.servizi.forEach(function (servizio) {
        var voce_el = testo("li", "mappa-scheda-sezione");
        voce_el.appendChild(testo("p", "mappa-evento-giorno", servizio.titolo));
        if (servizio.descrizione) { voce_el.appendChild(testo("p", null, servizio.descrizione)); }
        var dettagli = testo("dl", "mappa-scheda-dati");
        if (servizio.categoria) { dettagli.appendChild(rigaDato("Categoria", servizio.categoria)); }
        if (servizio.orari_testo) { dettagli.appendChild(rigaDato("Quando", servizio.orari_testo)); }
        if (servizio.referente_ruolo) {
          /* Il referente è un **ruolo**, mai una persona (V5): «operatore», non «Maria». */
          dettagli.appendChild(rigaDato("Referente", servizio.referente_ruolo));
        }
        if (servizio.scadenza) { dettagli.appendChild(rigaDato("Scadenza", dataItaliana(servizio.scadenza))); }
        voce_el.appendChild(dettagli);
        voce_el.appendChild(testo("p", "etichetta etichetta--kb", servizio.badge));
        lista.appendChild(voce_el);
      });
      sezione.appendChild(lista);
    }).catch(function () {
      sezione.textContent = "";
      sezione.appendChild(testo("p", "mappa-vuoto", "Servizi: la memoria della rete non ha risposto."));
    });
  }

  /* ------------------------------------------------------------------ eventi */

  /* Elenco **per data**, con il selettore `settimana | mese`. Mai una griglia di celle vuote: in
   * memoria ci sono 4 eventi futuri, una griglia mensile mostrerebbe 27 celle vuote su 30.
   *
   * Per un POI esterno il selettore **non** si disegna: la sezione dichiara che non c'è nessun
   * evento collegato, e un selettore sopra una frase che dice «nessuno» prometterebbe una scelta
   * che non cambia nulla. */
  function eventi(voce, sezione) {
    /* Il legame `evento ↔ luogo.id` non esiste nel modello dati (`evento.luogo_testo` è testo
     * libero, §11 Q-04): mostrare gli eventi della Casa più vicina sarebbe un'inferenza, non un
     * dato. Si dichiara, e non si chiama nemmeno l'endpoint. */
    var senzaEventi = voce.livello === "esterna" || (voce.livello === "luogo" && !voce.casaId);
    if (senzaEventi) {
      sezione.appendChild(testo("p", "mappa-vuoto", "Eventi: nessun evento collegato a questo luogo"));
      return;
    }

    var casaId = voce.livello === "casa" ? voce.id : voce.casaId;
    var elencoEventi = testo("div", null);

    var testa = testo("div", "blocco-testa");
    var selettore = testo("div", "mappa-periodo");
    selettore.setAttribute("role", "group");
    selettore.setAttribute("aria-label", "Intervallo degli eventi");
    ["settimana", "mese"].forEach(function (nome) {
      var b = testo("button", "azione", nome);
      b.type = "button";
      b.setAttribute("aria-pressed", String(periodo === nome));
      b.addEventListener("click", function () {
        periodo = nome;
        var bottoni = selettore.querySelectorAll("button");
        for (var i = 0; i < bottoni.length; i++) {
          bottoni[i].setAttribute("aria-pressed", String(bottoni[i].textContent === nome));
        }
        disegnaEventi(casaId, elencoEventi);
      });
      selettore.appendChild(b);
    });
    testa.appendChild(selettore);
    sezione.appendChild(testa);
    sezione.appendChild(elencoEventi);

    disegnaEventi(casaId, elencoEventi);
  }

  function disegnaEventi(casaId, contenitore) {
    contenitore.textContent = "";
    contenitore.appendChild(testo("p", "mappa-vuoto", "Lettura in corso…"));
    var finestraCorrente = finestra();
    window.Trasi.api("/op/eventi?dal=" + finestraCorrente.dal + "&al=" + finestraCorrente.al +
      "&casa_id=" + encodeURIComponent(casaId)).then(function (dati) {
      contenitore.textContent = "";
      if (!dati.eventi || !dati.eventi.length) {
        contenitore.appendChild(testo("p", "mappa-vuoto",
          periodo === "mese" ? "Nessun evento nei prossimi 30 giorni." : "Nessun evento nei prossimi 7 giorni."));
        return;
      }
      /* Raggruppati per giorno: l'elenco per data, non una griglia. L'ordine è quello dello shim
       * (per inizio), quindi i gruppi escono già in ordine e dentro il gruppo gli orari pure. */
      var perGiorno = [];
      dati.eventi.forEach(function (evento) {
        var ultimo = perGiorno[perGiorno.length - 1];
        if (!ultimo || ultimo.giorno !== evento.giorno) {
          ultimo = { giorno: evento.giorno, eventi: [] };
          perGiorno.push(ultimo);
        }
        ultimo.eventi.push(evento);
      });

      var lista = testo("ul", "mappa-eventi");
      perGiorno.forEach(function (gruppo) {
        var voce_giorno = testo("li", null);
        voce_giorno.appendChild(testo("p", "mappa-evento-giorno", giornoEsteso(gruppo.giorno)));
        var sotto = testo("ul", "mappa-eventi");
        gruppo.eventi.forEach(function (evento) {
          var riga = testo("li", "mappa-evento");
          var testa = testo("div", "mappa-evento-testa");
          testa.appendChild(testo("span", "mappa-evento-ora",
            evento.ora_inizio + (evento.ora_fine ? "–" + evento.ora_fine : "")));
          testa.appendChild(testo("span", null, evento.titolo));
          riga.appendChild(testa);
          if (evento.luogo_testo) { riga.appendChild(testo("p", "mappa-vuoto", evento.luogo_testo)); }
          /* Il badge **verbatim** dello shim anche sull'evento: la provenienza sta sotto
           * l'informazione, su riga propria (§1.3 regola 2). */
          riga.appendChild(testo("p", "etichetta etichetta--kb", evento.badge));
          sotto.appendChild(riga);
        });
        voce_giorno.appendChild(sotto);
        lista.appendChild(voce_giorno);
      });
      contenitore.appendChild(lista);

      /* La riga di chiusura dice **fino a quando** si è guardato: senza, «non c'è altro» e «la
       * finestra finisce qui» sono la stessa cosa per chi legge. */
      contenitore.appendChild(testo("p", "mappa-conteggio",
        "Elenco fino al " + dataItaliana(finestraCorrente.al) + "."));
    }).catch(function () {
      contenitore.textContent = "";
      contenitore.appendChild(testo("p", "mappa-vuoto", "Eventi: la memoria della rete non ha risposto."));
    });
  }

  /* ------------------------------------------------------------------ apri / chiudi */

  /* `Esc` chiude **solo** se la scheda è aperta: la stessa chiave è usata da `shell.js` per la
   * sidebar a scomparsa, e disattivarla qui lascerebbe un `Esc` che non fa nulla su una pagina in
   * cui la sidebar non è aperta. */
  function alTasto(evento) {
    if (evento.key !== "Escape") { return; }
    if (!pannello || pannello.hidden) { return; }
    /* Se il focus è dentro la scheda — o non è in nessun punto preciso — `Esc` chiude la scheda.
     * Se invece è nella sidebar, `shell.js` ha già fatto il suo lavoro e non si interferisce. */
    var dentro = pannello.contains(document.activeElement);
    var fuori = !document.activeElement || document.activeElement === document.body;
    if (dentro || fuori) {
      evento.preventDefault();
      chiudi(true);
    }
  }

  function apri(chiave) {
    var voce = window.TrasiMappa.stato.perChiave[chiave];
    if (!voce) { return; }
    /* Il punto di partenza si ricorda **alla prima apertura**: se si passa da una voce all'altra
     * senza chiudere, il focus deve tornare a dove si era entrati, non all'ultima toccata. */
    if (!voceCorrente) { chiaveDaCuiSiEPartiti = chiave; }
    voceCorrente = chiave;

    corpo.textContent = "";
    corpo.appendChild(testata(voce));
    var sezioneDati = testo("div", "mappa-scheda-sezione");
    sezioneDati.appendChild(dati(voce));
    corpo.appendChild(sezioneDati);

    var sezioneServizi = testo("div", "mappa-scheda-sezione");
    sezioneServizi.appendChild(testo("h3", null, "Servizi"));
    corpo.appendChild(sezioneServizi);
    servizi(voce, sezioneServizi);

    var sezioneEventi = testo("div", "mappa-scheda-sezione");
    sezioneEventi.appendChild(testo("h3", null, "Prossimi eventi"));
    corpo.appendChild(sezioneEventi);
    eventi(voce, sezioneEventi);

    corpo.appendChild(azioni(voce));

    pannello.hidden = false;
    pezzoElenco.hidden = true;
    document.addEventListener("keydown", alTasto);
  }

  function chiudi(conFocus) {
    if (!pannello || pannello.hidden) { return; }
    pannello.hidden = true;
    pezzoElenco.hidden = false;
    var chiave = chiaveDaCuiSiEPartiti || voceCorrente;
    voceCorrente = null;
    chiaveDaCuiSiEPartiti = null;
    document.removeEventListener("keydown", alTasto);
    if (conFocus) {
      /* Fuori dai filtri, se la voce è sparita: l'elenco è stato ridisegnato e il nodo non c'è
       * più — `tornaAllaVoce` ripiega sulla prima voce, che è il punto di ripresa naturale. */
      window.TrasiElenco.tornaAllaVoce(chiave);
    } else {
      window.TrasiElenco.deseleziona();
    }
  }

  /* ------------------------------------------------------------------ avvio */

  window.TrasiScheda = { apri: apri, chiudi: chiudi };

  function avvia() {
    pannello = document.getElementById("mappa-scheda");
    corpo = document.getElementById("mappa-scheda-corpo");
    pezzoElenco = document.getElementById("mappa-elenco-pezzo");
    var chiudiBtn = document.getElementById("mappa-scheda-chiudi");
    if (chiudiBtn) { chiudiBtn.addEventListener("click", function () { chiudi(true); }); }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", avvia);
  } else {
    avvia();
  }
})();
