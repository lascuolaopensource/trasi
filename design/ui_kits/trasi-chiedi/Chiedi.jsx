const { Intestazione, SelettoreCasa, Bottone, MessaggioChat, CampoTesto, Scheda, Etichetta, EtichettaProvenienza } = window.TrasiDesignSystem_18d101;

const CONVERSAZIONE = [
  { autore: 'operatore', testo: 'Dove può lavare i panni qui vicino?' },
  {
    testo: "Lavanderia sociale di Molo 12 — via Provinciale per San Vito 2.\nAperta lunedì-venerdì, 9:00-13:00. A circa 850 m dalla Casa San Bao.",
    provenienza: { testo: '[KB · Rete delle Case di Quartiere · agg. 15/09/2026 · affidabilità 2]' },
    azioni: 'biglietto',
  },
  {
    testo: "C'è anche una lavanderia a gettoni in via Bastioni Carlo V 12. Gli orari non sono disponibili.",
    provenienza: { tipo: 'esterna', fonte: 'OpenStreetMap contributors (ODbL)', ora: '11:42' },
  },
  { autore: 'operatore', testo: 'La lavanderia di via Bastioni ha chiuso, me l\'hanno detto ieri.' },
  {
    testo: "Ho creato una proposta di chiusura per quel luogo. Resta in attesa: la decisione è di una persona, non del sistema.",
    proposta: true,
  },
];

function Turni({ onProponi }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s-4)' }}>
      {CONVERSAZIONE.map((m, i) => (
        <MessaggioChat key={i} autore={m.autore} testo={m.testo} provenienza={m.provenienza}
          azioni={m.azioni === 'biglietto' ? (
            <>
              <Bottone variante="secondaria" dimensione="compatta">Stampa il biglietto</Bottone>
              <Bottone variante="quieta" dimensione="compatta" onClick={onProponi}>Segnala un cambiamento</Bottone>
            </>
          ) : null}>
          {m.proposta ? (
            <Scheda filetto="var(--coda-filetto)" padding="var(--s-3)" style={{ marginTop: 'var(--s-1)' }}>
              <p style={{ margin: 0, fontSize: 'var(--t-minuto)', color: 'var(--testo-tenue)', fontFamily: 'var(--font-mono)' }}>proposta · chiudi_luogo</p>
              <p style={{ margin: '4px 0 0' }}>Lavanderia a gettoni, via Bastioni Carlo V 12 — segnalata come chiusa.</p>
              <p style={{ margin: '4px 0 0', fontSize: 'var(--t-minuto)', color: 'var(--testo-tenue)' }}>In attesa · chi decide: gestore della Casa · nessuna scadenza</p>
            </Scheda>
          ) : null}
        </MessaggioChat>
      ))}
    </div>
  );
}

function Chiedi() {
  const [testo, setTesto] = React.useState('');
  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', fontFamily: 'var(--font-corpo)', color: 'var(--testo)' }}>
      <Intestazione logo="../../assets/logo-case-di-quartiere-bianco.png"
        casa={<SelettoreCasa valore="san-bao" onChange={() => {}} />}
        azioni={<><Bottone variante="suScuro" dimensione="compatta" href="../trasi-home/index.html">Torna a Trasi</Bottone><Bottone variante="suScuro" dimensione="compatta">Esci</Bottone></>} />

      <div style={{ flex: 1, maxWidth: 'var(--misura-lettura)', width: '100%', margin: '0 auto', padding: 'var(--padding-pagina)', display: 'flex', flexDirection: 'column', gap: 'var(--s-5)' }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'baseline', gap: 'var(--s-3)' }}>
          <h1 style={{ margin: 0, fontSize: 'var(--t-titolo-m)', fontWeight: 'var(--peso-medio)' }}>CHIEDI — assistente della rete</h1>
          <Etichetta tono="informativa">San Bao</Etichetta>
          <p style={{ margin: 0, fontSize: 'var(--t-minuto)', color: 'var(--testo-tenue)' }}>Ogni risposta porta la sua etichetta di provenienza.</p>
        </div>

        <Turni onProponi={() => {}} />

        <Scheda padding="var(--s-4)" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s-3)', position: 'sticky', bottom: 'var(--s-4)' }}>
          <CampoTesto id="domanda" etichetta="La domanda della persona" righe={2}
            segnaposto="es. dove può fare la tessera sanitaria?"
            aiuto="Senza nomi e senza dati personali: servono solo il bisogno e la zona."
            valore={testo} onChange={(e) => setTesto(e.target.value)} />
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--s-2)', alignItems: 'center' }}>
            <Bottone variante="principale">Chiedi</Bottone>
            <Bottone variante="quieta">Segnala un cambiamento</Bottone>
            <span style={{ marginLeft: 'auto', fontSize: 'var(--t-minuto)', color: 'var(--testo-tenue)' }}>La chat non conserva dati personali.</span>
          </div>
        </Scheda>
      </div>
    </div>
  );
}
Object.assign(window, { Chiedi });
