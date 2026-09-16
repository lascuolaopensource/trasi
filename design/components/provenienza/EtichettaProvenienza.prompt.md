L'etichetta che dice da dove viene un'informazione: si usa **ogni volta** che la pagina mostra un dato.

\`\`\`jsx
<EtichettaProvenienza testo="[KB · Rete delle Case di Quartiere · agg. 15/09/2026 · affidabilità 2]" />
<EtichettaProvenienza tipo="esterna" fonte="OpenStreetMap contributors (ODbL)" ora="02:21" />
\`\`\`

Tre canali ridondanti, nessuno dei quali è il colore da solo: la parola («KB» / «Esterna»),
il bordo (continuo / tratteggiato) e la glossa («la rete lo sa» / «trovato fuori, non verificato dalla rete»).
Se hai il campo \`badge\` dello shim, passalo in \`testo\` verbatim: non riformattare date e ore.
