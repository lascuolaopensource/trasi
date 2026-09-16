Azione dell'interfaccia — bottone o collegamento, stessa veste.

\`\`\`jsx
<Bottone variante="principale" href="/chiedi">Apri CHIEDI</Bottone>
<Bottone variante="secondaria" onClick={salva}>Salva</Bottone>
<Bottone variante="suScuro" dimensione="compatta">Esci</Bottone>
\`\`\`

Varianti: \`principale\` (piena, blu notte — una sola per schermata), \`secondaria\` (bordo 2 px),
\`quieta\` (solo testo sottolineato), \`suScuro\` (per la testata blu).
Dimensioni: \`normale\` (44 px minimi) e \`compatta\` (36 px, solo azioni di servizio).
Niente ombre, niente scala al passaggio del mouse: cambia solo il colore.
