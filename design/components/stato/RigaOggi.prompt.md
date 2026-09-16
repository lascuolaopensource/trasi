La riga «Oggi» della Home: l'unico contenuto che cambia da solo.

\`\`\`jsx
<RigaOggi testo="Oggi a San Bao: 2 eventi · 1 scheda in scadenza · 3 proposte" />
<RigaOggi stato="non-disponibile" testo="Dati non disponibili: la memoria della rete non risponde in questo momento." nota="È un'informazione, non un guasto: le quattro destinazioni funzionano." />
\`\`\`

Il testo arriva già composto dalla vista \`v_oggi_casa\`: non ricomporlo lato pagina, o la Home
direbbe numeri diversi dalla chat. Lo stato \`non-disponibile\` non è rosso.
