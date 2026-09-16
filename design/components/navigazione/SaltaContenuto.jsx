import React from 'react';

/** Il salto al contenuto: invisibile fino al primo Tab, poi ben visibile. */
export function SaltaContenuto({ href = '#contenuto', children = 'Salta alle destinazioni' }) {
  return (
    <a href={href} className="trasi-salta" style={{
      position: 'absolute', left: '-9999px', top: 0, zIndex: 10,
      padding: '12px 16px', background: 'var(--superficie)', color: 'var(--testo)',
      border: 'var(--contorno) solid var(--testo)', borderRadius: '0 0 var(--raggio) 0',
      fontFamily: 'var(--font-corpo)', fontWeight: 'var(--peso-medio)',
    }}>{children}</a>
  );
}
