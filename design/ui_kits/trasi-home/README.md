# UI kit — Trasi Home

La pagina d'ingresso, ridisegnata sulla frequenza d'uso reale invece della simmetria 2×2.

| File | Contenuto |
|---|---|
| `index.html` | la vista tipica: testata, fascia di stato, destinazioni, Aiuto, piede |
| `Home.jsx` | il layout e lo stato della pagina (Casa scelta, Aiuto aperto) |
| `SezioneAiuto.jsx` | la sezione Aiuto riscritta in italiano semplice |
| `stati.html` | gli stati: attesa, dati letti, «dati non disponibili», coda vuota, Casa provvisoria |

## Cosa cambia rispetto alla pagina attuale

1. **Gerarchia per frequenza.** CHIEDI occupa tutta la larghezza con il titolo a 36 px; MAPPA e
   OSSERVATORIO stanno su due colonne; REGISTRA/AGGIORNA scende al terzo livello perché è predisposto
   e non ancora attivo. Quattro riquadri uguali dicevano «quattro cose usate allo stesso modo», e non è vero.
2. **La fascia di stato sale in testa.** La riga «Oggi» e la coda delle proposte sono le due sole cose
   che cambiano da sole: si leggono prima di scegliere dove andare, non dopo.
3. **La coda delle proposte esce da OSSERVATORIO.** Resta anche là (con il conteggio sul riquadro), ma
   ha una riga sua: è un'attività quotidiana o settimanale, non un dato di cruscotto.
4. **L'etichetta della Casa diventa visibile** e Tuturano porta «dati provvisori» nel testo dell'opzione.

## Sorgente

Ricostruito da `deployment/home/index.html`, `style.css`, `home.js` del repository
`lascuolaopensource/trasi` (ramo `main`). I testi reali sono conservati dove esistevano.
