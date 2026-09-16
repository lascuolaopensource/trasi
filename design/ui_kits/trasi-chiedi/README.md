# UI kit — CHIEDI

La chat dell'assistente della rete, vista dallo sportello. Oggi il servizio è Onyx
(`onyx.lascuolaopensource.org/app?agentId=2`): questo kit non ne replica l'interfaccia, mostra
**come Trasi vorrebbe che si leggessero le risposte** — una etichetta di provenienza per ogni
informazione, su riga propria, sotto il testo.

Le due forme dell'etichetta vengono da `shim/app/badge.py` e si citano verbatim:

    [KB · Comune di Brindisi · agg. 10/09/2026 · affidabilità 3]
    [Esterna · OpenStreetMap contributors (ODbL) · consultata 11:42 · non verificata dalla rete]

Il turno finale mostra il meccanismo delle proposte: l'operatore segnala un cambiamento, nasce una
proposta in attesa, la decisione resta di una persona.
