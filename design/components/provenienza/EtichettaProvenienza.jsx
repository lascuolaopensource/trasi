import React from 'react';

/* Le due forme sono quelle composte dallo shim (shim/app/badge.py) e vanno
   riportate verbatim:
     [KB · Comune di Brindisi · agg. 10/09/2026 · affidabilità 3]
     [Esterna · OpenStreetMap contributors (ODbL) · consultata 11:42 · non verificata dalla rete]
   Qui cambia solo la veste. La distinzione KB/Esterna non dipende dal colore:
   la porta la parola («KB» / «Esterna»), il tratto del bordo (continuo /
   tratteggiato) e la glossa in italiano semplice. */

const toni = {
  kb: { colore: 'var(--kb-testo)', bordo: 'var(--kb-bordo)', sfondo: 'var(--kb-sfondo)', tratto: 'solid', parola: 'KB', glossa: 'la rete lo sa' },
  esterna: { colore: 'var(--esterna-testo)', bordo: 'var(--esterna-bordo)', sfondo: 'var(--esterna-sfondo)', tratto: 'dashed', parola: 'Esterna', glossa: 'trovato fuori, non verificato dalla rete' },
};

function testoPredefinito(tipo, { fonte, data, affidabilita, ora }) {
  if (tipo === 'kb') return '[KB · ' + (fonte || 'fonte non dichiarata') + ' · agg. ' + (data || '—') + ' · affidabilità ' + (affidabilita || '—') + ']';
  return '[Esterna · ' + (fonte || 'fonte non dichiarata') + ' · consultata ' + (ora || '—') + ' · non verificata dalla rete]';
}

/** L'etichetta di provenienza di un'informazione: da dove viene, e se la rete l'ha verificata. */
export function EtichettaProvenienza({ tipo = 'kb', fonte, data, affidabilita, ora, testo, glossa = true, style, ...resto }) {
  const tono = toni[tipo] || toni.kb;
  const riga = testo || testoPredefinito(tipo, { fonte, data, affidabilita, ora });
  return (
    <span style={{ display: 'inline-flex', flexWrap: 'wrap', alignItems: 'baseline', gap: 'var(--s-2)', fontFamily: 'var(--font-corpo)', ...style }} {...resto}>
      <span style={{
        display: 'inline-flex', alignItems: 'baseline', gap: 'var(--s-2)',
        fontFamily: 'var(--font-etichette)', fontSize: 'var(--t-minuto)', lineHeight: '1.5',
        color: tono.colore, background: tono.sfondo,
        border: '1px ' + tono.tratto + ' ' + tono.bordo, borderLeft: 'var(--contorno) solid ' + tono.bordo,
        borderRadius: 'var(--raggio-piccolo)', padding: '3px 8px',
      }}>
        <strong style={{ fontWeight: 'var(--peso-forte)', letterSpacing: '0.04em' }}>{tono.parola}</strong>
        <span>{riga.replace(/^\[(KB|Esterna) · /, '').replace(/\]$/, '')}</span>
      </span>
      {glossa ? <span style={{ fontSize: 'var(--t-minuto)', color: 'var(--testo-tenue)' }}>{tono.glossa}</span> : null}
    </span>
  );
}
