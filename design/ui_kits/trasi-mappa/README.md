# UI kit — MAPPA

La pagina statica `deployment/home/mappa.html` (con `mappa.js`, `mappa.css`, `casa.js`): la mappa Leaflet
delle **dieci Case della rete** con l'elenco equivalente, centrata sulla Casa scelta. Fino al 2026-09-18 il
riquadro MAPPA della Home apriva la dashboard Metabase «Mappa» (`/metabase/dashboard/4`), che non portava a
una mappa utilizzabile allo sportello.

**Cosa c'è.** Le coordinate stanno nel database del progetto (`trasi.v_mappa_case`, 10 righe) e arrivano dallo
shim (`GET /mappa_case?casa=<slug>`, canale pubblico con chiave, fuori dal contratto con Onyx) con fonte,
affidabilità, data e badge `[KB · …]` composto dal servizio. Lo sfondo è OpenStreetMap (tile diretti dal browser,
attribuzione **in parole** sotto la mappa); i pin sono un carattere (`■`), non immagini; la Casa scelta è
evidenziata per forma (anello) **e** per parola («la Casa scelta» nell'elenco, `aria-current`).

**Cosa non c'è, e perché.** I luoghi della rete (`v_mappa_luoghi`) e i punti di OpenStreetMap non sono su
questa mappa: è la mappa delle Case, non l'Osservatorio. Il cerchio del raggio non si disegna (miglioria non
approvata). I pin non sono raggiungibili da tastiera per costruzione: l'equivalente accessibile è l'elenco,
stesse Case nello stesso ordine (prima la Casa scelta, poi per distanza), con un bottone «Mostra sulla mappa»
per voce. Gli stati sono in parole: «Sfondo della mappa non disponibile: le Case e l'elenco restano leggibili.»
e «Dati non disponibili: la memoria della rete non risponde in questo momento. È un'informazione, non un
guasto.» — mai un codice, mai rosso.

**Provenienza in ogni riga**: il badge è verbatim in monospazio, e le note («orari provvisori», «coordinate
stimate», «dati provvisori») sono parole accanto al dato, non colori.
