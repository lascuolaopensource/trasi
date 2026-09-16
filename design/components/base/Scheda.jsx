import React from 'react';

/** Superficie di contenuto: bianca, bordo di 2 px, nessuna ombra. */
export function Scheda({ filetto, elemento = 'div', padding = 'var(--padding-scheda)', style, children, ...resto }) {
  const Elemento = elemento;
  return (
    <Elemento style={{
      background: 'var(--superficie-scheda)', color: 'var(--testo)',
      border: 'var(--contorno) solid var(--bordo-tenue)', borderRadius: 'var(--raggio)',
      padding, boxShadow: 'var(--ombra-nessuna)',
      ...(filetto ? { borderLeft: 'var(--filetto-forte) solid ' + filetto } : null),
      ...style,
    }} {...resto}>{children}</Elemento>
  );
}
