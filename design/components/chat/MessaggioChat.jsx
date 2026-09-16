import React from 'react';
import { EtichettaProvenienza } from '../provenienza/EtichettaProvenienza.jsx';

/* Un turno della chat CHIEDI. Ogni informazione dell'assistente porta la sua
   etichetta di provenienza sotto il testo, mai dentro la frase. */

/** Un messaggio della chat: dell'operatore o dell'assistente. */
export function MessaggioChat({ autore = 'assistente', testo, provenienza, azioni, style, children, ...resto }) {
  const operatore = autore === 'operatore';
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', gap: 'var(--s-2)', maxWidth: '42rem',
      alignSelf: operatore ? 'flex-end' : 'flex-start',
      background: operatore ? 'var(--superficie-incassata)' : 'var(--superficie)',
      border: 'var(--contorno) solid ' + (operatore ? 'var(--bordo-tenue)' : 'var(--bordo-tenue)'),
      borderLeft: operatore ? 'var(--contorno) solid var(--bordo-tenue)' : 'var(--filetto-forte) solid var(--mare)',
      borderRadius: 'var(--raggio)', padding: 'var(--s-4)',
      fontFamily: 'var(--font-corpo)', fontSize: 'var(--t-corpo)', lineHeight: 'var(--interlinea)', ...style,
    }} {...resto}>
      <p style={{ margin: 0, fontSize: 'var(--t-minuto)', color: 'var(--testo-tenue)', fontWeight: 'var(--peso-medio)' }}>
        {operatore ? 'Operatore' : 'Assistente della rete'}
      </p>
      {testo ? <p style={{ margin: 0, whiteSpace: 'pre-line' }}>{testo}</p> : null}
      {children}
      {provenienza ? <EtichettaProvenienza {...provenienza} /> : null}
      {azioni ? <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--s-2)', marginTop: 'var(--s-1)' }}>{azioni}</div> : null}
    </div>
  );
}
