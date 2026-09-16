Un riquadro-destinazione della Home. La variante dice quanto si usa, non quanto è importante.

\`\`\`jsx
<Destinazione variante="principale" titolo="CHIEDI" href="//onyx…/app?agentId=2&casa=san-bao"
  testo="L'assistente della rete: risponde con la fonte di ogni informazione." nota="si apre con San Bao già impostata" />
<Destinazione titolo="OSSERVATORIO" href="/metabase/dashboard/3?casa=san-bao" contatore="3 proposte in attesa"
  testo="I numeri della Casa e le proposte da approvare." />
<Destinazione titolo="REGISTRA / AGGIORNA" attivo={false} nota="Servizio non ancora attivo" testo="Schede, eventi e opportunità della Casa." />
\`\`\`

Una sola \`principale\` per schermata. Al passaggio del mouse cambia il colore del bordo e lo sfondo,
niente movimento.
