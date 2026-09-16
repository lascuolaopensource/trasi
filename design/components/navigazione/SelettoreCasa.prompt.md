Il selettore della Casa di riferimento. Resta un \`<select>\`: si cambia poche volte l'anno.

\`\`\`jsx
<SelettoreCasa valore="san-bao" onChange={(e) => setCasa(e.target.value)} />
\`\`\`

L'etichetta «Casa di riferimento» è visibile (non nascosta agli screen reader come oggi);
Tuturano porta «— dati provvisori» dentro il testo dell'opzione e ripete la nota sotto il
controllo quando è selezionata, così l'informazione non dipende dal colore.
La costante \`CASE\` esporta le 10 Case con i loro slug reali.
