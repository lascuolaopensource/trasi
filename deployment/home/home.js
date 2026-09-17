/* Trasi Home — comportamento della pagina. Vanilla JS, ES module, nessuna dipendenza.
 * Contratti invariati: slug della Casa in localStorage (chiave `trasi.casa_id`),
 * GET /api/shim/v1/u/rete@trasi.local/{oggi,eventi_oggi} con scadenza 3 s,
 * POST /api/shim/logout. Caddy aggiunge X-Trasi-Key: il browser non vede segreti. */

const CHIAVE_CASA = "trasi.casa_id";
const CASA_PREDEFINITA = "san-bao";
const IDENTITA = "rete@trasi.local";
const ATTESA_MS = 3000;
const TESTO_ATTESA = "Lettura dei dati di oggi in corso…";
const TESTO_ASSENTE = "Dati non disponibili: la memoria della rete non risponde in questo momento.";
const NOTA_ASSENTE = "È un’informazione, non un guasto: le destinazioni qui sotto funzionano.";

const selettore = document.getElementById("selettore-casa");
const oggiScheda = document.getElementById("oggi-scheda");
const oggiTesto = document.getElementById("oggi-testo");
const listaEventi = document.getElementById("oggi-eventi");
const casaNota = document.getElementById("casa-nota");
const riquadroCoda = document.getElementById("coda");
const testoCoda = document.getElementById("coda-testo");
const contatore = document.getElementById("osservatorio-contatore");
const notaChiedi = document.getElementById("chiedi-nota");

function opzione(slug) {
  if (typeof slug !== "string" || slug === "") return null;
  for (const opt of selettore.options) if (opt.value === slug) return opt;
  return null;
}
const casaValida = slug => (opzione(slug) ? slug : null);
function casaScelta() { return casaValida(selettore.value) || CASA_PREDEFINITA; }
function nomeCasa(slug) {
  const scelta = opzione(slug);
  return scelta ? scelta.textContent.split(" — ")[0].trim() : slug;
}
function memorizza(slug) { try { localStorage.setItem(CHIAVE_CASA, slug); } catch { /* navigazione privata: la pagina funziona lo stesso */ } }
function ricorda() { try { return casaValida(localStorage.getItem(CHIAVE_CASA)); } catch { return null; } }

/* destinazioni */
function aggiornaDestinazioni(slug) {
  const codificato = encodeURIComponent(slug);
  for (const anello of document.querySelectorAll("[data-modello]")) {
    anello.setAttribute("href", anello.getAttribute("data-modello").replace("{casa}", codificato));
  }
}
function aggiornaNomi(slug) {
  const nome = nomeCasa(slug);
  const frase = "si apre con " + nome + " già impostata";
  if (notaChiedi) notaChiedi.textContent = frase;
  for (const nota of document.querySelectorAll(".nota-casa-dest")) nota.textContent = frase;
  if (casaNota) {
    const scelta = opzione(slug);
    const provvisori = scelta && scelta.textContent.includes("dati provvisori");
    casaNota.hidden = !provvisori;
    if (provvisori) casaNota.textContent = nome + ": dati provvisori — alcune schede non sono ancora complete.";
  }
}

/* «Oggi» */
function impostaStatoOggi(stato) {
  oggiScheda.style.borderLeftColor = {
    "attesa": "var(--border-03)",
    "dati": "var(--status-info-05)",
    "non-disponibile": "var(--status-warning-05)",
  }[stato] || "var(--border-03)";
}

function mostraTesto(testo, stato, nota) {
  oggiTesto.classList.remove("skeleton");
  oggiTesto.textContent = testo;
  document.getElementById("oggi").setAttribute("aria-busy", "false");
  impostaStatoOggi(stato);
  const vecchia = oggiTesto.parentElement.querySelector(".oggi-nota");
  if (vecchia) vecchia.remove();
  if (nota) {
    const n = document.createElement("span");
    n.className = "oggi-nota";
    n.style.cssText = "flex-basis:100%;font-size:0.875rem;color:var(--text-03)";
    n.textContent = nota;
    oggiTesto.parentElement.appendChild(n);
  }
}

function mostraCoda(slug, numero, giorni) {
  const nome = nomeCasa(slug);
  const vuota = !numero;
  riquadroCoda.hidden = false;
  testoCoda.replaceChildren();
  if (vuota) {
    testoCoda.append("Nessuna proposta in attesa a " + nome + ".");
  } else {
    const forte = document.createElement("strong");
    forte.textContent = String(numero);
    testoCoda.append(forte, " " + (numero === 1 ? "proposta aspetta" : "proposte aspettano") + " una decisione a " + nome);
    if (giorni) {
      const quando = document.createElement("span");
      quando.style.color = "var(--text-03)";
      quando.textContent = " · la più vecchia da " + giorni + (giorni === 1 ? " giorno" : " giorni");
      testoCoda.appendChild(quando);
    }
  }
  if (contatore) {
    contatore.hidden = vuota;
    if (!vuota) contatore.textContent = numero + (numero === 1 ? " proposta in attesa" : " proposte in attesa");
  }
}

function nascondiCoda() {
  riquadroCoda.hidden = true;
  if (contatore) contatore.hidden = true;
}

function mostraEventi(eventi) {
  const contenitore = document.getElementById("oggi-eventi-contenitore");
  const sommario = document.getElementById("oggi-eventi-sommario");
  listaEventi.replaceChildren();
  if (!eventi.length) { nascondiEventi(); return; }
  for (const e of eventi) {
    const voce = document.createElement("li");
    voce.className = "oggi-evento";
    const quando = e.ora_inizio ? e.ora_inizio + (e.ora_fine ? "–" + e.ora_fine : "") : (e.orari_nota || "");
    if (quando) {
      const ora = document.createElement("span");
      ora.className = "oggi-ora";
      ora.textContent = quando;
      voce.appendChild(ora);
    }
    const titolo = document.createElement("strong");
    titolo.textContent = e.titolo;
    voce.appendChild(titolo);
    if (e.dove) {
      const dove = document.createElement("span");
      dove.className = "dove";
      dove.textContent = e.dove;
      voce.appendChild(dove);
    }
    listaEventi.appendChild(voce);
  }
  if (contenitore) {
    sommario.textContent = eventi.length + (eventi.length === 1 ? " evento di oggi" : " eventi di oggi");
    contenitore.hidden = false;
    /* Allo sportello gli eventi sono il contenuto: aperti quando lo spazio c'è. */
    contenitore.open = window.matchMedia("(min-width: 40rem)").matches;
  }
}
function nascondiEventi() {
  listaEventi.replaceChildren();
  const contenitore = document.getElementById("oggi-eventi-contenitore");
  if (contenitore) contenitore.hidden = true;
}

let inCorso = null;
function leggiOggi(slug) {
  if (inCorso) inCorso.abort();
  const controllo = new AbortController();
  inCorso = controllo;

  mostraTesto("Lettura dei dati di oggi in corso…", "attesa", null);
  document.getElementById("oggi").setAttribute("aria-busy", "true");
  oggiTesto.classList.add("skeleton");
  riquadroCoda.hidden = true;
  nascondiEventi();

  const scadenza = setTimeout(() => controllo.abort(), ATTESA_MS);
  let inAttesa = 2;
  const finisci = () => { if (--inAttesa === 0) { clearTimeout(scadenza); inCorso = null; } };

  const base = "/api/shim/v1/u/" + encodeURIComponent(IDENTITA) + "/";
  const opzioni = { signal: controllo.signal, headers: { Accept: "application/json" } };

  fetch(base + "eventi_oggi?casa=" + encodeURIComponent(slug), opzioni)
    .then(r => { if (!r.ok) throw new Error("risposta " + r.status); return r.json(); })
    .then(dati => { finisci(); mostraEventi(dati && Array.isArray(dati.eventi) ? dati.eventi : []); })
    .catch(() => { finisci(); nascondiEventi(); });

  fetch(base + "oggi?casa=" + encodeURIComponent(slug), opzioni)
    .then(r => { if (!r.ok) throw new Error("risposta " + r.status); return r.json(); })
    .then(dati => {
      finisci();
      /* Solo il `testo` della vista: la Home non ricompone frasi che la chat
         comporrebbe diversamente. */
      if (dati && typeof dati.testo === "string" && dati.testo.trim() !== "") {
        mostraTesto(dati.testo, "dati", null);
        mostraCoda(dati.casa || slug, Number(dati.proposte) || 0, Number(dati.giorni_piu_vecchia) || 0);
      } else {
        mostraTesto(TESTO_ASSENTE, "non-disponibile", NOTA_ASSENTE);
        nascondiCoda();
      }
    })
    .catch(() => {
      finisci();
      mostraTesto(TESTO_ASSENTE, "non-disponibile", NOTA_ASSENTE);
      nascondiCoda();
    });
}

/* avvio */
selettore.value = ricorda() || selettore.value || CASA_PREDEFINITA;

function applica(slug) { aggiornaDestinazioni(slug); aggiornaNomi(slug); leggiOggi(slug); }
applica(casaScelta());

selettore.addEventListener("change", () => { const slug = casaScelta(); memorizza(slug); applica(slug); });

window.addEventListener("storage", evento => {
  if (evento.key !== CHIAVE_CASA) return;
  const slug = casaValida(evento.newValue);
  if (!slug || slug === selettore.value) return;
  selettore.value = slug;
  applica(slug);
});

/* uscita: chiude la sessione dello shim (cookie trasi_sessione), non Onyx */
const pulsanteEsci = document.getElementById("pulsante-esci");
const esitoUscita = document.getElementById("esito-uscita");
pulsanteEsci.addEventListener("click", () => {
  fetch("/api/shim/logout", { method: "POST", credentials: "same-origin" })
    .then(risposta => {
      esitoUscita.textContent = risposta.ok ? "Sessione chiusa." : "Uscita non riuscita (risposta " + risposta.status + ").";
      esitoUscita.hidden = false;
    })
    .catch(() => {
      esitoUscita.textContent = "Uscita non riuscita: servizio non raggiungibile.";
      esitoUscita.hidden = false;
    });
});