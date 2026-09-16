import React from 'react';

const base = {
  fontFamily: 'var(--font-corpo)', fontSize: 'var(--t-corpo)', fontWeight: 'var(--peso-medio)',
  lineHeight: 'var(--interlinea-stretta)', display: 'inline-flex', alignItems: 'center',
  justifyContent: 'center', gap: 'var(--s-2)', borderRadius: 'var(--raggio)',
  borderStyle: 'solid', borderWidth: 'var(--contorno)', cursor: 'pointer',
  textDecoration: 'none', transition: 'var(--transizione-stato)', boxSizing: 'border-box',
};

const dimensioni = {
  normale: { minHeight: 'var(--bersaglio-min)', padding: '10px 18px' },
  compatta: { minHeight: '36px', padding: '6px 12px', fontSize: 'var(--t-minuto)' },
};

const varianti = {
  principale: { background: 'var(--testata)', color: 'var(--testo-su-scuro)', borderColor: 'var(--testata)' },
  secondaria: { background: 'var(--superficie)', color: 'var(--azione)', borderColor: 'var(--bordo-forte)' },
  quieta: { background: 'transparent', color: 'var(--azione)', borderColor: 'transparent', textDecoration: 'underline', textUnderlineOffset: '3px' },
  suScuro: { background: 'transparent', color: 'var(--testo-su-scuro)', borderColor: 'var(--testo-su-scuro)', textDecoration: 'underline', textUnderlineOffset: '3px' },
};

/** Un'azione. Sobria: cambia solo colore, non si muove e non si ingrandisce. */
export function Bottone({ variante = 'secondaria', dimensione = 'normale', href, disabilitato = false, onClick, style, children, ...resto }) {
  const stile = { ...base, ...dimensioni[dimensione], ...varianti[variante], ...(disabilitato ? { opacity: 0.55, cursor: 'not-allowed' } : null), ...style };
  if (href && !disabilitato) return <a href={href} style={stile} {...resto}>{children}</a>;
  return <button type="button" style={stile} disabled={disabilitato} onClick={onClick} {...resto}>{children}</button>;
}
