# UI kit — OSSERVATORIO

Il cruscotto della Casa e la coda delle proposte. Oggi il cruscotto è la dashboard Metabase «Casa»
(`/metabase/dashboard/3`) e la coda vive in NocoDB: questo kit mostra **la forma che Trasi darebbe
agli stessi dati**, con i token del sistema.

Fonti dei dati (viste reali del database): `v_oggi_casa`, `v_proposte_aperte`, `v_in_scadenza`,
`v_scaduti`, `v_senza_risposta`.

Due regole che il kit rispetta alla lettera:

- **k-anonimato 5**: sotto soglia la cella dice `<5`, mai il numero.
- **V6**: nessun imperativo. «3 proposte aspettano una decisione», non «approva le proposte».
  Le azioni sui bottoni sono verbi di decisione (Approva / Rifiuta) e stanno sulla singola proposta,
  dove la decisione avviene davvero.
