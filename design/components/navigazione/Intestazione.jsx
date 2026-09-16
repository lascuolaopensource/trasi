import React from 'react';

/** La testata: chi sono, per quale Casa, e le due azioni di servizio. */
export function Intestazione({ logo = 'assets/logo-case-di-quartiere-bianco.png', sottotitolo = 'Rete delle Case di Quartiere di Brindisi', casa, azioni, style, ...resto }) {
  return (
    <header style={{
      display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end', justifyContent: 'space-between',
      gap: 'var(--s-4) var(--s-6)', padding: 'var(--s-4) var(--padding-pagina)',
      background: 'var(--testata)', color: 'var(--testo-su-scuro)',
      borderBottom: 'var(--filetto-testata) solid var(--testata-bordo)',
      fontFamily: 'var(--font-corpo)', ...style,
    }} {...resto}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--s-4)', minWidth: 0 }}>
        {logo ? <img src={logo} alt="Case di Quartiere Brindisi" style={{ height: '44px', width: 'auto' }} /> : null}
        <div style={{ minWidth: 0 }}>
          <p style={{ margin: 0, fontSize: 'var(--t-titolo-m)', fontWeight: 'var(--peso-forte)', letterSpacing: 'var(--spaziatura-marchio)' }}>TRASI</p>
          <p style={{ margin: 0, fontSize: 'var(--t-minuto)', color: 'rgba(255,255,255,0.86)' }}>{sottotitolo}</p>
        </div>
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end', gap: 'var(--s-4)', minWidth: 0 }}>
        {casa}
        {azioni ? <div style={{ display: 'flex', gap: 'var(--s-2)', alignItems: 'center' }}>{azioni}</div> : null}
      </div>
    </header>
  );
}
