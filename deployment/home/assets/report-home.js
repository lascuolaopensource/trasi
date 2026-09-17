/* report-home.js — «Report mensile» nella Home: l'ultimo rendiconto leggibile da questa sessione.
 *
 * Legge `GET /op/report` (shim, `report_op.py`): la RLS decide cosa arriva — la propria Casa per un
 * operatore, tutte le Case per la rete. La pagina disegna il report **più recente** per ogni Casa che
 * arriva, con i numeri di sintesi già mascherati («<5», «—») e il collegamento all'export `.html`.
 *
 * Il report si legge e si commenta, non si modifica: qui non c'è nessun modulo, nessun pulsante che
 * scriva. Stati: lettura in corso, vuoto (nessun ciclo ha ancora generato un report), errore in parole
 * (`Trasi.spiega`), dati.
 */
(function () {
  "use strict";

  function $(id) { return document.getElementById(id); }

  function el(tag, classe, testo) {
    var e = document.createElement(tag);
    if (classe) e.className = classe;
    if (testo) e.textContent = testo;
    return e;
  }

  function numero(etichetta, valore) {
    var dt = el("dt", null, etichetta);
    var dd = el("dd", null, String(valore));
    return [dt, dd];
  }

  function voce(report) {
    var art = el("article", "report-voce");
    var testa = el("div", "report-voce-testa");
    testa.appendChild(el("h3", "report-titolo", report.casa_nome || "Rete delle Case"));
    testa.appendChild(el("p", "report-mese", report.mese_testo));
    art.appendChild(testa);

    var dl = el("dl", "report-numeri");
    [
      numero("Richieste registrate", report.richieste),
      numero("Senza destinazione trovata", report.senza_risposta),
      numero("Proposte in attesa", report.proposte_in_attesa),
      numero("Proposte applicate", report.proposte_applicate),
      numero("Schede in scadenza", report.schede_in_scadenza)
    ].forEach(function (coppia) { dl.appendChild(coppia[0]); dl.appendChild(coppia[1]); });
    art.appendChild(dl);

    var celle = report.per_categoria_esito || [];
    if (celle.length) {
      var ul = el("ul", "report-celle");
      celle.forEach(function (c) {
        var li = el("li", "report-cella");
        li.appendChild(el("span", "report-cella-testo", c.categoria_testo + " · " + c.esito_testo));
        li.appendChild(el("span", "report-cella-n", c.n));
        ul.appendChild(li);
      });
      art.appendChild(ul);
    } else {
      art.appendChild(el("p", "report-nota", "Nessuna richiesta registrata nel mese."));
    }

    var azioni = el("p", "report-azioni");
    var scarica = el("a", "azione", "Scarica il report (.html)");
    /* Il download passa dallo stesso canale delle API (`/api/shim/...`): Caddy aggiunge la chiave, il
       cookie di sessione decide cosa si può leggere. `download` chiede al browser di salvare, e il nome
       del file lo dà lo shim (`Content-Disposition`). */
    scarica.href = "/api/shim" + report.export_url;
    scarica.setAttribute("download", "");
    azioni.appendChild(scarica);
    art.appendChild(azioni);
    return art;
  }

  /* Il più recente per Casa: l'elenco arriva dal più recente, quindi il primo che si incontra vince. */
  function ultimiPerCasa(report) {
    var visti = {};
    return report.filter(function (r) {
      var chiave = r.ambito === "casa" ? "casa:" + r.casa_id : "rete";
      if (visti[chiave]) return false;
      visti[chiave] = true;
      return true;
    });
  }

  function disegna(dati) {
    var lista = $("report-lista");
    var stato = $("report-stato");
    if (!lista) return;
    lista.textContent = "";
    var report = ultimiPerCasa(dati.report || []);
    if (!report.length) {
      stato.textContent = "Nessun report ancora generato: il ciclo mensile lo produce il giorno 3 di ogni mese, sul mese appena chiuso.";
      stato.hidden = false;
      return;
    }
    stato.hidden = true;
    report.forEach(function (r) { lista.appendChild(voce(r)); });
  }

  function carica() {
    var stato = $("report-stato");
    if (!stato || !window.Trasi || !window.Trasi.api) return;
    stato.textContent = "Lettura del report in corso…";
    stato.hidden = false;
    window.Trasi.api("/op/report")
      .then(disegna)
      .catch(function (e) {
        if (e && e.sessioneScaduta) return;
        stato.textContent = window.Trasi.spiega ? window.Trasi.spiega(e) : "Dati non disponibili: la memoria della rete non risponde in questo momento";
        stato.hidden = false;
      });
  }

  function avvia() {
    if (!window.Trasi || !window.Trasi.pronto) return;
    window.Trasi.pronto.then(function (sessione) { if (sessione) carica(); });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", avvia);
  else avvia();
})();
