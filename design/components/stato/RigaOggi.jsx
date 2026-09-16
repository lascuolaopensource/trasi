import React from 'react';

/* La riga «Oggi» è l'unica cosa della Home che cambia da sola. Tre stati:
   attesa (lettura in corso), ok (il testo della vista v_oggi_casa),
   non-disponibile (lo shim non ha risposto entro 3 s — un'informazione, non un guasto). */

const stili = {
  attesa: { filetto: 'var(--bordo)', colore: 'var(--testo-tenue)' },
  ok: { filetto: 'var(--mare)', colore: 'var(--testo)' },
  'non-disponibile': { filetto: 'var(--attenzione-testo)', colore: 'var(--testo)' },
};

/** La riga «Oggi»: cosa bolle in pentola nella Casa scelta. */
export function RigaOggi({ stato = 'ok', testo, nota, style, ...resto }) {
  const s = stili[stato] || stili.ok;
  return (
    <p role="status" aria-live="polite" aria-busy={stato === 'attesa'} style={{
      margin: 0, padding: 'var(--s-3) var(--s-4)', background: 'var(--superficie)',
      border: 'var(--contorno) solid var(--bordo-tenue)', borderLeft: 'var(--filetto-forte) solid ' + s.filetto,
      borderRadius: 'var(--raggio)', fontFamily: 'var(--font-corpo)', fontSize: 'var(--t-corpo-grande)',
      lineHeight: 'var(--interlinea)', color: s.colore, ...style,
    }} {...resto}>
      <span style={{ fontWeight: 'var(--peso-forte)', letterSpacing: 'var(--spaziatura-destinazione)', textTransform: 'uppercase', fontSize: 'var(--t-minuto)', color: 'var(--testo-tenue)', marginRight: 'var(--s-2)' }}>Oggi</span>
      {testo}
      {nota ? <span style={{ display: 'block', marginTop: 'var(--s-1)', fontSize: 'var(--t-minuto)', color: 'var(--testo-tenue)' }}>{nota}</span> : null}
    </p>
  );
}
