import React from 'react';

/* La coda delle proposte: una presenza, non un allarme. Niente rosso, niente
   punto esclamativo, nessun imperativo (V6: il sistema osserva, l'umano decide). */

/** Quante proposte aspettano un umano, e da quanto. */
export function AvvisoCoda({ numero = 0, giorniPiuVecchia, casa, href, azione = 'Apri la coda delle proposte', style, ...resto }) {
  const vuota = !numero;
  return (
    <div style={{
      display: 'flex', flexWrap: 'wrap', alignItems: 'baseline', gap: 'var(--s-2) var(--s-4)',
      background: 'var(--coda-sfondo)', border: 'var(--contorno) solid var(--bordo-tenue)',
      borderLeft: 'var(--filetto-forte) solid ' + (vuota ? 'var(--bordo-tenue)' : 'var(--coda-filetto)'),
      borderRadius: 'var(--raggio)', padding: 'var(--s-3) var(--s-4)',
      fontFamily: 'var(--font-corpo)', fontSize: 'var(--t-corpo)', lineHeight: 'var(--interlinea)',
      ...style,
    }} {...resto}>
      <span style={{ color: vuota ? 'var(--testo-tenue)' : 'var(--testo)' }}>
        {vuota ? (
          <>Nessuna proposta in attesa{casa ? ' a ' + casa : ''}.</>
        ) : (
          <>
            <strong style={{ fontWeight: 'var(--peso-forte)', color: 'var(--coda-testo)' }}>{numero}</strong>
            {' '}{numero === 1 ? 'proposta aspetta' : 'proposte aspettano'} una decisione{casa ? ' a ' + casa : ''}
            {giorniPiuVecchia ? <span style={{ color: 'var(--testo-tenue)' }}>{' · la più vecchia da ' + giorniPiuVecchia + (giorniPiuVecchia === 1 ? ' giorno' : ' giorni')}</span> : null}
          </>
        )}
      </span>
      {href ? <a href={href} style={{ color: 'var(--azione)', fontWeight: 'var(--peso-medio)', textUnderlineOffset: '3px' }}>{azione}</a> : null}
    </div>
  );
}
