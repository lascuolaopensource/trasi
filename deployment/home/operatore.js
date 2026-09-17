/* Trasi — area operatore. Vanilla JS, ES module, nessuna dipendenza.
 * Contratti invariati: POST /api/shim/login, /me, /op/chat, /op/registra_richiesta,
 * /op/attrezzoteca, /op/movimento, /op/movimento/{id}/conferma, /op/messaggi,
 * /logout. Cookie HttpOnly `trasi_sessione`; la pagina non tocca la sessione.
 * Novità UI: pannello attivo nell'URL (?pannello=…), fonte citata sotto le
 * risposte, dialog per il prestito al posto di window.prompt, skeleton in attesa. */

const BASE = "/api/shim";

const $ = id => document.getElementById(id);
function mostra(el, testo) { el.textContent = testo; el.hidden = false; }
function nascondi(el) { el.hidden = true; }

/* Una risposta non OK diventa un errore leggibile; mai il corpo grezzo. */
function chiama(percorso, opzioni = {}) {
  const init = { ...opzioni };
  init.headers = { Accept: "application/json", ...(init.headers || {}) };
  if (init.body && typeof init.body === "object") {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(init.body);
  }
  init.credentials = "same-origin";
  return fetch(BASE + percorso, init).then(risposta => {
    if (risposta.status === 401) {
      const e = new Error("sessione assente o scaduta");
      e.sessioneScaduta = true;
      throw e;
    }
    if (!risposta.ok) {
      return risposta.json().catch(() => null).then(corpo => {
        const dettaglio = corpo && (corpo.dettaglio || corpo.detail);
        throw new Error(typeof dettaglio === "string" ? dettaglio : "errore " + risposta.status);
      });
    }
    const tipo = risposta.headers.get("content-type") || "";
    return tipo.includes("json") ? risposta.json() : risposta.text();
  });
}

/* ------------------------------------------------------------ sessione */

const registro = $("chat-registro");
const vistaAccesso = $("accesso");
const vistaBanco = $("banco");
let casaCorrente = null;
let pannelloCorrente = "chat";

const caricati = new Set();
function caricaPannello(nome) {
  if (!casaCorrente || caricati.has(nome)) return;
  caricati.add(nome);
  if (nome === "attrezzoteca") { caricaInventario(""); caricaMovimenti(); }
  if (nome === "messaggi") caricaMessaggi();
}

function inSessione(casa) {
  sessioneAperta = true;
  casaCorrente = casa;
  $("operatore-casa").textContent = "Casa: " + casa;
  nascondi(vistaAccesso);
  vistaBanco.hidden = false;
  caricati.clear();
  caricaPannello(pannelloCorrente);
}

let sessioneAperta = false;
function fuoriSessione() {
  const eraAperta = sessioneAperta;
  sessioneAperta = false;
  casaCorrente = null;
  $("operatore-casa").textContent = "accesso richiesto";
  vistaBanco.hidden = true;
  vistaAccesso.hidden = false;
  /* Postazione condivisa: nulla della conversazione resta nel documento. */
  const vuota = $("chat-vuota");
  registro.replaceChildren();
  if (vuota) registro.appendChild(vuota);
  if (eraAperta) mostra($("accesso-errore"), "La sessione è terminata: per continuare serve un nuovo accesso.");
  $("accesso-password").focus();
}

$("modulo-accesso").addEventListener("submit", evento => {
  evento.preventDefault();
  nascondi($("accesso-errore"));
  chiama("/login", { method: "POST", body: { casa: $("accesso-casa").value, password: $("accesso-password").value } })
    .then(dati => {
      $("accesso-password").value = "";
      inSessione(dati && dati.casa ? dati.casa : $("accesso-casa").value);
    })
    .catch(errore => {
      mostra($("accesso-errore"), errore.sessioneScaduta
        ? "Accesso non riuscito: Casa o parola d’ordine non riconosciute."
        : "Accesso non riuscito: " + errore.message);
    });
});

$("pulsante-esci").addEventListener("click", () => {
  chiama("/logout", { method: "POST" }).catch(() => { /* la sessione lato server scade da sé */ });
  mostra($("esito-uscita"), "Sessione chiusa.");
  fuoriSessione();
});

function scaduta(errore) {
  if (errore && errore.sessioneScaduta) { fuoriSessione(); return true; }
  return false;
}

/* ------------------------------------------------------------ pannelli + URL */

const linguette = [...document.querySelectorAll(".linguetta[data-pannello]")];
const PANNELLI = new Set(linguette.map(l => l.dataset.pannello));

function pannelloDaURL() {
  const q = new URLSearchParams(location.search).get("pannello");
  return PANNELLI.has(q) ? q : "chat";
}

function apriPannello(nome, { storia = true, fuoco = false } = {}) {
  pannelloCorrente = nome;
  for (const l of linguette) {
    const attivo = l.dataset.pannello === nome;
    if (attivo) l.setAttribute("aria-current", "page"); else l.removeAttribute("aria-current");
  }
  for (const p of document.querySelectorAll(".pannello")) p.hidden = p.id !== "pannello-" + nome;
  caricaPannello(nome);
  if (fuoco) {
    const titolo = document.querySelector("#pannello-" + nome + " .titolo-pannello");
    if (titolo) titolo.focus({ preventScroll: true });
  }
  if (storia) {
    const url = new URL(location.href);
    url.searchParams.set("pannello", nome);
    history.pushState({ pannello: nome }, "", url);
  }
}

linguette.forEach(l => l.addEventListener("click", evento => {
  evento.preventDefault();
  const nome = l.dataset.pannello;
  /* view transition same-document, con fallback diretto */
  if (document.startViewTransition && !matchMedia("(prefers-reduced-motion: reduce)").matches) {
    document.startViewTransition(() => apriPannello(nome, { fuoco: true }));
  } else {
    apriPannello(nome, { fuoco: true });
  }
}));

window.addEventListener("popstate", () => apriPannello(pannelloDaURL(), { fuoco: true }));

/* ----------------------------------------------------------------- chat */


function battuta(chi, testo) {
  const vuota = $("chat-vuota");
  if (vuota) vuota.remove();
  const voce = document.createElement("li");
  voce.className = "battuta";
  voce.dataset.chi = chi;
  if (chi === "operatore") voce.classList.add("io");
  const chiEl = document.createElement("span");
  chiEl.className = "chi";
  chiEl.textContent = chi === "operatore" ? "Tu" : "Assistente";
  const bolla = document.createElement("p");
  bolla.className = "bolla";
  bolla.textContent = testo;
  voce.append(chiEl, bolla);
  const inFondo = registro.scrollHeight - registro.scrollTop - registro.clientHeight < 80;
  registro.appendChild(voce);
  if (inFondo) voce.scrollIntoView({ block: "end" });
  return { voce, bolla };
}

$("chat-modulo").addEventListener("submit", evento => {
  evento.preventDefault();
  const testo = $("chat-testo").value.trim();
  if (!testo || !casaCorrente) return;
  battuta("operatore", testo);
  $("chat-testo").value = "";

  const attesa = battuta("assistente", "");
  const riga = document.createElement("span");
  riga.className = "shimmer";
  riga.textContent = "L’assistente sta rispondendo…";
  attesa.bolla.appendChild(riga);
  attesa.bolla.classList.add("shimmer-testo");

  /* L'assistente può impiegare fino a 120 s: niente timeout lato pagina,
     il compositore resta usabile. */
  chiama("/op/chat", { method: "POST", body: { messaggio: testo } })
    .then(dati => {
      const risposta = dati && (dati.risposta || dati.testo || dati.answer);
      attesa.bolla.classList.remove("shimmer-testo");
      attesa.bolla.textContent = typeof risposta === "string" && risposta.trim() ? risposta : "Risposta non leggibile dalla chat.";
      /* la fonte arriva separata: la mostriamo come etichetta, verbatim */
      if (dati && typeof dati.fonte === "string" && dati.fonte.trim()) {
        const fonte = document.createElement("span");
        fonte.className = "fonte fonte-risposta";
        fonte.textContent = dati.fonte;
        if (dati.fonte.startsWith("[Esterna")) fonte.dataset.origine = "esterna";
        else if (!dati.fonte.startsWith("[KB")) fonte.dataset.origine = "assente";
        attesa.voce.appendChild(fonte);
      }
    })
    .catch(errore => {
      if (scaduta(errore)) return;
      attesa.voce.classList.add("chat-errore");
      attesa.bolla.classList.remove("shimmer-testo", "bolla");
      attesa.bolla.className = "messaggio";
      attesa.bolla.dataset.tipo = "attenzione";
      attesa.bolla.replaceChildren();
      attesa.bolla.append("L’assistente non risponde in questo momento. La domanda si può inviare di nuovo; nel frattempo la MAPPA della Home mostra i luoghi della Casa. ");
      const riprova = document.createElement("button");
      riprova.type = "button";
      riprova.className = "bottone";
      riprova.dataset.prominenza = "bordo";
      riprova.dataset.size = "sm";
      riprova.textContent = "Invia di nuovo";
      riprova.addEventListener("click", () => { attesa.voce.remove(); $("chat-testo").value = testo; $("chat-modulo").requestSubmit(); });
      attesa.bolla.appendChild(riprova);
    });
});

/* ------------------------------------------------------------ richiesta */

$("richiesta-esito").addEventListener("change", function () { $("riga-destinazione").hidden = this.value !== "inviata_altrove"; });

$("modulo-richiesta").addEventListener("submit", evento => {
  evento.preventDefault();
  nascondi($("richiesta-errore"));
  nascondi($("richiesta-esito-ok"));
  const corpo = { categoria: $("richiesta-categoria").value, esito: $("richiesta-esito").value };
  const nota = $("richiesta-destinazione-nota").value.trim();
  if (corpo.esito === "inviata_altrove" && nota) corpo.destinazione_nota = nota;
  chiama("/op/registra_richiesta", { method: "POST", body: corpo })
    .then(() => {
      mostra($("richiesta-esito-ok"), "Richiesta registrata. Il conteggio entra nel report del mese.");
      $("richiesta-destinazione-nota").value = "";
    })
    .catch(errore => { if (!scaduta(errore)) mostra($("richiesta-errore"), "Registrazione non riuscita: " + errore.message); });
});

/* --------------------------------------------------------- attrezzoteca */

function skeletonInventario() {
  const corpo = $("corpo-inventario");
  corpo.replaceChildren();
  const riga = document.createElement("tr");
  for (let i = 0; i < 6; i++) {
    const cella = document.createElement("td");
    const barra = document.createElement("span");
    barra.className = "skeleton";
    barra.style.cssText = "display:block;height:1rem;width:" + (50 + i * 8) + "%";
    barra.textContent = "caricamento";
    cella.appendChild(barra);
    riga.appendChild(cella);
  }
  corpo.appendChild(riga);
}

function cella(testo) {
  const td = document.createElement("td");
  td.textContent = testo == null ? "—" : String(testo);
  return td;
}

function rigaInventario(o) {
  const riga = document.createElement("tr");
  riga.appendChild(cella(o.nome + (o.descrizione ? " — " + o.descrizione : "")));
  riga.appendChild(cella(o.casa_slug || o.casa));
  riga.appendChild(cella(o.quantita_disponibile != null ? o.quantita_disponibile : o.quantita));
  riga.appendChild(cella(o.condizione));
  const tdFonte = document.createElement("td");
  tdFonte.textContent = o.fonte ? o.fonte : "—";
  tdFonte.className = "t-ui-ten";
  riga.appendChild(tdFonte);

  const azione = document.createElement("td");
  /* Il pulsante esiste solo sull'oggetto della propria Casa: `mov_ins_casa`
     (db/014) pretende `oggetto.casa_id = casa_corrente()`. Sugli altri: si chiede
     a loro — lo dichiara la riga, non un errore. */
  const propria = String(o.casa_slug || o.casa || "") === String(casaCorrente || "");
  if (propria) {
    const bottone = document.createElement("button");
    bottone.type = "button";
    bottone.className = "bottone";
    bottone.dataset.prominenza = "bordo";
    bottone.dataset.size = "sm";
    bottone.textContent = "Proponi prestito";
    bottone.addEventListener("click", () => apriDialogoPrestito(o));
    azione.appendChild(bottone);
  } else {
    azione.textContent = "Di un’altra Casa: si chiede a loro";
    azione.style.color = "var(--text-03)";
  }
  riga.appendChild(azione);
  return riga;
}

function rigaVuota(testo) {
  const riga = document.createElement("tr");
  riga.className = "stato-vuoto-tabella";
  const cellaVuota = document.createElement("td");
  cellaVuota.colSpan = 6;
  cellaVuota.textContent = testo;
  riga.appendChild(cellaVuota);
  return riga;
}

function caricaInventario(q) {
  skeletonInventario();
  chiama("/op/attrezzoteca" + (q ? "?q=" + encodeURIComponent(q) : ""))
    .then(dati => {
      /* Il campo è `items` (GET /op/attrezzoteca → {"items": [...]}) */
      const elenco = dati && (dati.items || dati.oggetti || dati.risultati);
      const corpo = $("corpo-inventario");
      corpo.replaceChildren();
      if (!Array.isArray(elenco) || elenco.length === 0) {
        corpo.appendChild(rigaVuota("Nessun oggetto trovato."));
        return;
      }
      for (const o of elenco) corpo.appendChild(rigaInventario(o));
    })
    .catch(errore => {
      if (scaduta(errore)) return;
      $("corpo-inventario").replaceChildren(rigaVuota("Inventario non disponibile: " + errore.message));
    });
}

/* Gli slug validi sono quelli del selettore di accesso: niente seconda lista. */
function caseDellaRete() { return [...document.querySelectorAll("#accesso-casa option")].map(o => o.value); }
function nomeCasaDaSlug(slug) {
  const opt = [...document.querySelectorAll("#accesso-casa option")].find(o => o.value === slug);
  return opt ? opt.textContent : slug;
}

/* dialog prestito */
const dialogo = $("dialogo-prestito");
let oggettoInPrestito = null;

function apriDialogoPrestito(o) {
  oggettoInPrestito = o;
  $("prestito-oggetto").textContent = "«" + o.nome + "» — disponibili: " + (o.quantita_disponibile != null ? o.quantita_disponibile : o.quantita ?? "—");
  const selettoreDest = $("prestito-a-casa");
  selettoreDest.replaceChildren();
  for (const slug of caseDellaRete()) {
    if (slug === casaCorrente) continue;
    const opt = document.createElement("option");
    opt.value = slug;
    opt.textContent = nomeCasaDaSlug(slug);
    selettoreDest.appendChild(opt);
  }
  $("prestito-al").value = new Date().toISOString().slice(0, 10);
  $("prestito-al").min = new Date().toISOString().slice(0, 10);
  nascondi($("prestito-errore"));
  dialogo.showModal();
}
dialogo.querySelector("[data-chiudi]").addEventListener("click", () => dialogo.close());
dialogo.querySelector("[data-annulla]").addEventListener("click", () => dialogo.close());

$("modulo-prestito").addEventListener("submit", evento => {
  evento.preventDefault();
  if (!oggettoInPrestito) return;
  nascondi($("prestito-errore"));
  /* Campi dell'endpoint: oggetto_id, a_casa (slug), dal/al ISO — tre nomi
     verificati sul contratto, ognuno faceva fallire il pulsante. */
  chiama("/op/movimento", {
    method: "POST",
    body: { oggetto_id: oggettoInPrestito.oggetto_id, a_casa: $("prestito-a-casa").value, dal: new Date().toISOString().slice(0, 10), al: $("prestito-al").value },
  })
    .then(() => {
      dialogo.close();
      mostra($("attrezzoteca-ok"), "Prestito proposto. Conta dalla conferma della Casa che riceve.");
      caricaInventario("");
      caricaMovimenti();
    })
    .catch(errore => {
      if (scaduta(errore)) { dialogo.close(); return; }
      mostra($("prestito-errore"), "Proposta non registrata: " + errore.message);
    });
});

function caricaMovimenti() {
  const lista = $("movimenti-da-confermare");
  lista.replaceChildren();
  chiama("/op/movimenti_da_confermare").then(dati => {
    const elenco = dati && (dati.movimenti || dati.items || dati);
    if (!Array.isArray(elenco) || elenco.length === 0) {
      const voce = document.createElement("li");
      voce.textContent = "Nessun movimento in attesa di conferma.";
      lista.appendChild(voce);
      return;
    }
    for (const m of elenco) {
      const voce = document.createElement("li");
      voce.className = "movimento";
      const testo = document.createElement("span");
      testo.textContent = (m.oggetto || ("oggetto #" + m.oggetto_id)) + " · da " + (m.da_casa_slug || m.da_casa_id) + " a " + (m.a_casa_slug || m.a_casa_id) + " (" + m.dal + " → " + m.al + ")";
      const ricevente = String(m.a_casa_slug || m.a_casa_id) === String(casaCorrente);
      if (!ricevente) {
        const attesa = document.createElement("span");
        attesa.className = "t-ui-ten";
        attesa.textContent = "in attesa della Casa che riceve";
        voce.append(testo, attesa);
        lista.appendChild(voce);
        continue;
      }
      const bottone = document.createElement("button");
      bottone.type = "button";
      bottone.className = "bottone";
      bottone.dataset.prominenza = "bordo";
      bottone.dataset.size = "sm";
      bottone.textContent = "Conferma ricezione";
      bottone.addEventListener("click", () => {
        chiama("/op/movimento/" + encodeURIComponent(m.id) + "/conferma", { method: "POST" })
          .then(() => {
            mostra($("attrezzoteca-ok"), "Ricezione confermata: l’oggetto ora risulta alla tua Casa.");
            caricaMovimenti();
            caricaInventario("");
          })
          .catch(errore => { if (!scaduta(errore)) mostra($("attrezzoteca-errore"), "Conferma non riuscita: " + errore.message); });
      });
      voce.append(testo, bottone);
      lista.appendChild(voce);
    }
  }).catch(errore => {
    if (scaduta(errore)) return;
    const voce = document.createElement("li");
    voce.className = "movimento";
    voce.textContent = "Movimenti non disponibili: " + errore.message;
    lista.appendChild(voce);
  });
}

$("modulo-cerca-oggetto").addEventListener("submit", evento => {
  evento.preventDefault();
  caricaInventario($("cerca-oggetto").value.trim());
});

/* ------------------------------------------------------------- messaggi */

function caricaMessaggi() {
  const lista = $("elenco-messaggi");
  lista.replaceChildren();
  chiama("/op/messaggi").then(dati => {
    /* Il campo è `items`, come per l'inventario */
    const elenco = dati && (dati.items || dati.messaggi || dati.risultati);
    if (!Array.isArray(elenco) || elenco.length === 0) {
      const voce = document.createElement("li");
      voce.className = "voce-messaggio";
      voce.textContent = "Nessun messaggio.";
      lista.appendChild(voce);
      return;
    }
    for (const m of elenco) {
      const voce = document.createElement("li");
      voce.className = "voce-messaggio";
      voce.dataset.letto = m.letto ? "si" : "no";
      const quando = document.createElement("span");
      quando.className = "quando";
      quando.textContent = (m.ts || "").slice(0, 16).replace("T", " ");
      const rotta = document.createElement("span");
      rotta.className = "rotta";
      const nomeParte = v => (!v || v === "pa") ? "Comune" : v === "broadcast" ? "tutta la rete" : v;
      rotta.textContent = nomeParte(m.da_casa) + " → " + nomeParte(m.a_casa) + ": ";
      voce.append(quando, rotta, m.testo);
      lista.appendChild(voce);
    }
  }).catch(errore => {
    if (scaduta(errore)) return;
    const voce = document.createElement("li");
    voce.className = "voce-messaggio";
    voce.textContent = "Messaggi non disponibili: " + errore.message;
    lista.appendChild(voce);
  });
}

$("modulo-messaggio").addEventListener("submit", evento => {
  evento.preventDefault();
  nascondi($("messaggio-errore"));
  nascondi($("messaggio-ok"));
  const corpo = { testo: $("messaggio-testo").value.trim() };
  const destinatario = $("messaggio-destinatario").value;
  if (destinatario) corpo.a_casa = destinatario;
  chiama("/op/messaggi", { method: "POST", body: corpo })
    .then(() => {
      mostra($("messaggio-ok"), "Messaggio inviato.");
      $("messaggio-testo").value = "";
      caricaMessaggi();
    })
    .catch(errore => { if (!scaduta(errore)) mostra($("messaggio-errore"), "Invio non riuscito: " + errore.message); });
});

/* ------------------------------------------------------------------ avvio */

/* La Home apre CHIEDI con `?casa=<slug>`: la Casa è preimpostata nel modulo di accesso
   solo se è una delle option (nessun valore arbitrario dall'URL). */
const casaDaURL = new URLSearchParams(location.search).get("casa");
if (casaDaURL && caseDellaRete().includes(casaDaURL)) $("accesso-casa").value = casaDaURL;

apriPannello(pannelloDaURL(), { storia: false });

/* Già dentro? GET /me è la verifica: il cookie è HttpOnly, la pagina non
   può leggerlo e non prova a indovinarlo. */
chiama("/me").then(dati => {
  if (dati && dati.casa) inSessione(dati.casa);
  else fuoriSessione();
}).catch(() => fuoriSessione());