import React from 'react';

/* Le quattro destinazioni non hanno la stessa frequenza d'uso: CHIEDI decine di
   volte al giorno, OSSERVATORIO una volta a settimana. La variante «principale»
   esiste per questo — la gerarchia visiva dice quanto una cosa si usa. */

const varianti = {
  principale: { titolo: 'var(--t-titolo-xl)', padding: 'var(--s-8)', bordo: 'var(--bordo-forte)', testo: 'var(--t-guida)' },
  secondaria: { titolo: 'var(--t-titolo-s)', padding: 'var(--s-5)', bordo: 'var(--bordo)', testo: 'var(--t-corpo)' },
};

/** Una destinazione della Home: apre un servizio con la Casa già impostata. */
export function Destinazione({ titolo, testo, href, variante = 'secondaria', attivo = true, nota, contatore, style, children, ...resto }) {
  const v = varianti[variante] || varianti.secondaria;
  return (
    <a href={attivo ? href : undefined} aria-disabled={attivo ? undefined : 'true'} style={{
      display: 'flex', flexDirection: 'column', gap: 'var(--s-2)', height: '100%',
      padding: v.padding, background: 'var(--superficie)', color: 'var(--testo)',
      border: 'var(--contorno) solid ' + v.bordo, borderRadius: 'var(--raggio)',
      textDecoration: 'none', transition: 'var(--transizione-stato)', boxSizing: 'border-box',
      ...(attivo ? null : { background: 'var(--superficie-incassata)' }),
      ...style,
    }} {...resto}>
      <span style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'baseline', justifyContent: 'space-between', gap: 'var(--s-2)' }}>
        <span style={{
          fontSize: v.titolo, fontWeight: 'var(--peso-forte)', letterSpacing: 'var(--spaziatura-destinazione)',
          lineHeight: 'var(--interlinea-stretta)', color: 'var(--azione)',
        }}>{titolo}</span>
        {contatore ? <span style={{ fontSize: 'var(--t-corpo)', color: 'var(--coda-testo)', fontWeight: 'var(--peso-medio)' }}>{contatore}</span> : null}
      </span>
      {testo ? <span style={{ fontSize: v.testo, lineHeight: 'var(--interlinea)', color: 'var(--testo)', maxWidth: 'var(--misura-testo)' }}>{testo}</span> : null}
      {nota ? <span style={{ fontSize: 'var(--t-minuto)', color: 'var(--testo-tenue)' }}>{nota}</span> : null}
      {children}
    </a>
  );
}
