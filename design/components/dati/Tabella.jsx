import React from 'react';

/** Tabella di dati: righe alte, intestazioni fisse nel senso della lettura, zebratura tenue. */
export function Tabella({ colonne = [], righe = [], didascalia, densita = 'comoda', style, ...resto }) {
  const pad = densita === 'compatta' ? '8px 12px' : '12px 14px';
  return (
    <div style={{ overflowX: 'auto', border: 'var(--contorno) solid var(--bordo-tenue)', borderRadius: 'var(--raggio)', background: 'var(--superficie)', ...style }} {...resto}>
      <table style={{ borderCollapse: 'collapse', width: '100%', fontFamily: 'var(--font-corpo)', fontSize: 'var(--t-corpo)' }}>
        {didascalia ? <caption style={{ textAlign: 'left', padding: pad, color: 'var(--testo-tenue)', fontSize: 'var(--t-minuto)' }}>{didascalia}</caption> : null}
        <thead>
          <tr>
            {colonne.map((c, i) => (
              <th key={i} scope="col" style={{
                textAlign: 'left', padding: pad, borderBottom: 'var(--contorno) solid var(--bordo)',
                fontWeight: 'var(--peso-forte)', color: 'var(--testo)', whiteSpace: 'nowrap',
              }}>{typeof c === 'string' ? c : c.titolo}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {righe.map((r, i) => (
            <tr key={i} style={{ background: i % 2 ? 'var(--carta)' : 'var(--superficie)' }}>
              {r.map((cella, j) => (
                <td key={j} style={{ padding: pad, borderBottom: '1px solid var(--bordo-tenue)', color: 'var(--testo)', verticalAlign: 'top' }}>{cella}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
