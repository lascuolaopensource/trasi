import React from 'react';

/** Campo di testo con etichetta sempre visibile e testo di aiuto opzionale. */
export function CampoTesto({ id, etichetta, aiuto, valore, onChange, righe, segnaposto, larghezza = '100%', ...resto }) {
  const Controllo = righe ? 'textarea' : 'input';
  const stileControllo = {
    font: 'inherit', fontSize: 'var(--t-corpo)', color: 'var(--testo)', background: 'var(--superficie)',
    border: 'var(--contorno) solid var(--bordo)', borderRadius: 'var(--raggio)',
    padding: '10px 12px', minHeight: righe ? undefined : 'var(--bersaglio-min)', width: '100%', boxSizing: 'border-box',
  };
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s-1)', width: larghezza, fontFamily: 'var(--font-corpo)' }}>
      <label htmlFor={id} style={{ fontSize: 'var(--t-corpo)', fontWeight: 'var(--peso-medio)', color: 'var(--testo)' }}>{etichetta}</label>
      <Controllo id={id} value={valore} onChange={onChange} rows={righe} placeholder={segnaposto} style={stileControllo} {...resto} />
      {aiuto ? <p style={{ margin: 0, fontSize: 'var(--t-corpo)', color: 'var(--testo-tenue)' }}>{aiuto}</p> : null}
    </div>
  );
}
