import React from 'react';

/* Le 10 Case della rete, con lo slug usato da localStorage («trasi.casa_id»)
   e dagli href delle destinazioni. Tuturano porta «dati provvisori» nel testo
   dell'opzione: l'informazione non dipende dal colore né da un'icona. */
export const CASE = [
  { slug: 'santa-spazio', nome: 'Santa Spazio Culturale' },
  { slug: 'molo12', nome: 'Molo 12' },
  { slug: 'erranti', nome: 'Accademia degli Erranti' },
  { slug: 'buscicchio', nome: 'Parco Buscicchio' },
  { slug: 'san-bao', nome: 'San Bao' },
  { slug: 'minimus', nome: 'Minimus' },
  { slug: 'pop', nome: 'POP — Piccolo Opificio Popolare' },
  { slug: 'bozzano', nome: 'Centro di Aggregazione Bozzano' },
  { slug: 'dream', nome: 'Dream: Laboratorio Creativo' },
  { slug: 'tuturano', nome: 'Tuturano', nota: 'dati provvisori' },
];

/** La Casa di riferimento: si cambia raramente, quindi si legge sempre e si apre solo se serve. */
export function SelettoreCasa({ id = 'selettore-casa', valore = 'san-bao', case: elenco = CASE, onChange, suScuro = true, style, ...resto }) {
  const scelta = elenco.find((c) => c.slug === valore);
  const coloreEtichetta = suScuro ? 'rgba(255,255,255,0.86)' : 'var(--testo-tenue)';
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s-1)', minWidth: 0, fontFamily: 'var(--font-corpo)', ...style }}>
      <label htmlFor={id} style={{ fontSize: 'var(--t-minuto)', fontWeight: 'var(--peso-medio)', color: coloreEtichetta, letterSpacing: '0.02em' }}>
        Casa di riferimento
      </label>
      <select id={id} value={valore} onChange={onChange} style={{
        font: 'inherit', fontSize: 'var(--t-corpo)', fontWeight: 'var(--peso-medio)', color: 'var(--testo)',
        background: 'var(--superficie)', border: 'var(--contorno) solid ' + (suScuro ? 'var(--testata-bordo)' : 'var(--bordo)'),
        borderRadius: 'var(--raggio)', padding: '8px 10px', minHeight: 'var(--bersaglio-min)',
        maxWidth: 'min(24rem, 100%)', minWidth: 0,
      }} {...resto}>
        {elenco.map((c) => (
          <option key={c.slug} value={c.slug}>{c.nota ? c.nome + ' — ' + c.nota : c.nome}</option>
        ))}
      </select>
      {scelta && scelta.nota ? (
        <p style={{ margin: 0, fontSize: 'var(--t-minuto)', color: suScuro ? 'rgba(255,255,255,0.92)' : 'var(--attenzione-testo)' }}>
          {scelta.nome}: {scelta.nota} — alcune schede non sono ancora complete.
        </p>
      ) : null}
    </div>
  );
}
