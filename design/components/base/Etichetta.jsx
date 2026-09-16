import React from 'react';

const toni = {
  attenzione: { background: 'var(--attenzione-sfondo)', color: 'var(--attenzione-testo)', borderColor: 'var(--attenzione-testo)' },
  neutra: { background: 'var(--superficie-incassata)', color: 'var(--testo-tenue)', borderColor: 'var(--bordo)' },
  informativa: { background: 'var(--kb-sfondo)', color: 'var(--kb-testo)', borderColor: 'var(--kb-bordo)' },
};

/** Etichetta di stato: poche parole, sempre leggibili anche senza colore. */
export function Etichetta({ tono = 'neutra', bordo = false, style, children, ...resto }) {
  return (
    <span style={{
      display: 'inline-block', padding: '2px 8px', borderRadius: 'var(--raggio-piccolo)',
      fontFamily: 'var(--font-corpo)', fontSize: 'var(--t-minuto)', fontWeight: 'var(--peso-medio)',
      lineHeight: '1.45', borderStyle: 'solid', borderWidth: bordo ? '1px' : '0',
      ...toni[tono], ...style,
    }} {...resto}>{children}</span>
  );
}
