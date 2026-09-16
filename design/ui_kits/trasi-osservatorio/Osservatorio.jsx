const { Intestazione, SelettoreCasa, Bottone, Scheda, Tabella, AvvisoCoda, Etichetta, EtichettaProvenienza, RigaOggi } = window.TrasiDesignSystem_18d101;

function Numero({ etichetta, valore, nota }) {
  return (
    <Scheda style={{ flex: '1 1 160px' }}>
      <p style={{ margin: 0, fontSize: 'var(--t-minuto)', color: 'var(--testo-tenue)' }}>{etichetta}</p>
      <p style={{ margin: '2px 0 0', fontSize: 'var(--t-titolo-l)', fontWeight: 'var(--peso-forte)', color: 'var(--azione)', lineHeight: 'var(--interlinea-stretta)' }}>{valore}</p>
      {nota ? <p style={{ margin: '2px 0 0', fontSize: 'var(--t-minuto)', color: 'var(--testo-tenue)' }}>{nota}</p> : null}
    </Scheda>
  );
}

function Osservatorio() {
  const [decise, setDecise] = React.useState({});
  const proposte = [
    { id: 1, tipo: 'modifica_luogo', voce: 'Bar interno · orari', giorni: 4, chi: 'Gestore della Casa', motivo: 'orario serale cambiato da settembre' },
    { id: 2, tipo: 'chiudi_luogo', voce: 'Lavanderia a gettoni, via Bastioni Carlo V 12', giorni: 2, chi: 'Gestore della Casa', motivo: 'segnalata come chiusa allo sportello' },
    { id: 3, tipo: 'promuovi_esterno', voce: 'Sportello CAF, via Nazario Sauro 8', giorni: 1, chi: 'AT di rete', motivo: 'trovata su OpenStreetMap, da verificare' },
  ];
  const aperte = proposte.filter((p) => !decise[p.id]);

  return (
    <div style={{ minHeight: '100vh', fontFamily: 'var(--font-corpo)', color: 'var(--testo)' }}>
      <Intestazione logo="../../assets/logo-case-di-quartiere-bianco.png"
        casa={<SelettoreCasa valore="san-bao" onChange={() => {}} />}
        azioni={<><Bottone variante="suScuro" dimensione="compatta" href="../trasi-home/index.html">Torna a Trasi</Bottone><Bottone variante="suScuro" dimensione="compatta">Esci</Bottone></>} />

      <div style={{ maxWidth: 'var(--misura-lettura)', margin: '0 auto', padding: 'var(--padding-pagina)', display: 'flex', flexDirection: 'column', gap: 'var(--s-6)' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 'var(--t-titolo-m)', fontWeight: 'var(--peso-medio)' }}>OSSERVATORIO — San Bao</h1>
          <p style={{ margin: '4px 0 0', color: 'var(--testo-tenue)' }}>Come sta andando la Casa, e cosa aspetta una decisione. Ultimi 30 giorni.</p>
        </div>

        <RigaOggi testo="Oggi a San Bao: 2 eventi · 1 scheda in scadenza · 3 proposte" />

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--s-4)' }}>
          <Numero etichetta="Richieste registrate" valore="18" nota="ultimi 30 giorni" />
          <Numero etichetta="Schede in scadenza" valore="1" nota="entro 30 giorni" />
          <Numero etichetta="Schede scadute" valore="0" />
          <Numero etichetta="Richieste senza risposta" valore="<5" nota="sotto la soglia di riservatezza" />
        </div>

        <section style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s-3)' }}>
          <h2 style={{ margin: 0, fontSize: 'var(--t-titolo-s)', fontWeight: 'var(--peso-forte)', color: 'var(--azione)', letterSpacing: 'var(--spaziatura-destinazione)' }}>PROPOSTE IN ATTESA</h2>
          <AvvisoCoda numero={aperte.length} giorniPiuVecchia={aperte.length ? Math.max(...aperte.map((p) => p.giorni)) : undefined} casa="San Bao" />
          {aperte.map((p) => (
            <Scheda key={p.id} filetto="var(--coda-filetto)" style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--s-3)', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div style={{ minWidth: 0, flex: '1 1 320px' }}>
                <p style={{ margin: 0, fontSize: 'var(--t-minuto)', color: 'var(--testo-tenue)', fontFamily: 'var(--font-mono)' }}>{p.tipo}</p>
                <p style={{ margin: '2px 0 0', fontWeight: 'var(--peso-medio)' }}>{p.voce}</p>
                <p style={{ margin: '2px 0 0', color: 'var(--testo-tenue)' }}>{p.motivo}</p>
                <p style={{ margin: '6px 0 0', fontSize: 'var(--t-minuto)', color: 'var(--testo-tenue)' }}>in attesa da {p.giorni} {p.giorni === 1 ? 'giorno' : 'giorni'} · chi decide: {p.chi} · nessuna scadenza</p>
              </div>
              <div style={{ display: 'flex', gap: 'var(--s-2)', flexWrap: 'wrap' }}>
                <Bottone variante="secondaria" dimensione="compatta" onClick={() => setDecise({ ...decise, [p.id]: 'approvata' })}>Approva</Bottone>
                <Bottone variante="quieta" dimensione="compatta" onClick={() => setDecise({ ...decise, [p.id]: 'rifiutata' })}>Rifiuta</Bottone>
              </div>
            </Scheda>
          ))}
          {Object.keys(decise).length ? (
            <p style={{ margin: 0, fontSize: 'var(--t-minuto)', color: 'var(--testo-tenue)' }}>
              Le proposte decise vengono applicate dal flusso notturno alle 05:00, con una riga di audit.
            </p>
          ) : null}
        </section>

        <section style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s-3)' }}>
          <h2 style={{ margin: 0, fontSize: 'var(--t-titolo-s)', fontWeight: 'var(--peso-forte)', color: 'var(--azione)', letterSpacing: 'var(--spaziatura-destinazione)' }}>SCHEDE DELLA CASA</h2>
          <Tabella colonne={['Scheda', 'Aggiornata', 'Provenienza', 'Stato']}
            righe={[
              ['Sportello di ascolto', '15/09/2026', <EtichettaProvenienza testo="[KB · Rete delle Case di Quartiere · agg. 15/09/2026 · affidabilità 2]" glossa={false} />, 'in corso'],
              ['Doposcuola', '02/08/2026', <EtichettaProvenienza tipo="kb" fonte="Casa San Bao" data="02/08/2026" affidabilita={2} glossa={false} />, <Etichetta tono="attenzione">in scadenza</Etichetta>],
              ['Lavanderia sociale', '15/09/2026', <EtichettaProvenienza tipo="kb" fonte="Rete-kb-3" data="15/09/2026" affidabilita={3} glossa={false} />, 'in corso'],
            ]} />
          <p style={{ margin: 0, fontSize: 'var(--t-minuto)', color: 'var(--testo-tenue)' }}>I conteggi sotto la soglia di riservatezza si leggono «&lt;5»: mai il numero grezzo.</p>
        </section>
      </div>
    </div>
  );
}
Object.assign(window, { Osservatorio });
