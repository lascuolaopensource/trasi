const { Intestazione, SelettoreCasa, Bottone, Scheda, Tabella, Etichetta, CampoTesto, EtichettaProvenienza } = window.TrasiDesignSystem_18d101;

function Registra() {
  const [modulo, setModulo] = React.useState(false);
  return (
    <div style={{ minHeight: '100vh', fontFamily: 'var(--font-corpo)', color: 'var(--testo)' }}>
      <Intestazione logo="../../assets/logo-case-di-quartiere-bianco.png"
        casa={<SelettoreCasa valore="san-bao" onChange={() => {}} />}
        azioni={<><Bottone variante="suScuro" dimensione="compatta" href="../trasi-home/index.html">Torna a Trasi</Bottone><Bottone variante="suScuro" dimensione="compatta">Esci</Bottone></>} />

      <div style={{ maxWidth: 'var(--misura-lettura)', margin: '0 auto', padding: 'var(--padding-pagina)', display: 'flex', flexDirection: 'column', gap: 'var(--s-5)' }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--s-3)', alignItems: 'baseline' }}>
          <h1 style={{ margin: 0, fontSize: 'var(--t-titolo-m)', fontWeight: 'var(--peso-medio)' }}>REGISTRA / AGGIORNA — San Bao</h1>
          <Etichetta tono="attenzione">Servizio non ancora attivo</Etichetta>
        </div>

        <Scheda filetto="var(--attenzione-testo)">
          <p style={{ margin: 0 }}>
            Il registro è predisposto: il collegamento porta già alla vista della Casa. Fino all'attivazione,
            le correzioni passano dalle proposte fatte in chat e dalla coda in OSSERVATORIO.
          </p>
        </Scheda>

        <section style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s-3)' }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--s-2)', justifyContent: 'space-between', alignItems: 'center' }}>
            <h2 style={{ margin: 0, fontSize: 'var(--t-titolo-s)', fontWeight: 'var(--peso-forte)', color: 'var(--azione)', letterSpacing: 'var(--spaziatura-destinazione)' }}>SCHEDE E EVENTI</h2>
            <Bottone variante="secondaria" dimensione="compatta" onClick={() => setModulo(!modulo)}>{modulo ? 'Chiudi il modulo' : 'Aggiungi una voce'}</Bottone>
          </div>

          {modulo ? (
            <Scheda padding="var(--padding-scheda-grande)" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s-4)' }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 'var(--s-4)' }}>
                <CampoTesto id="voce" etichetta="Nome della voce" segnaposto="es. Doposcuola" />
                <CampoTesto id="quando" etichetta="Quando" segnaposto="es. lunedì e mercoledì, 15:00-18:00" />
                <CampoTesto id="dove" etichetta="Dove" segnaposto="via Nazario Sauro 8" />
                <CampoTesto id="fonte" etichetta="Da dove viene l'informazione" aiuto="Chi l'ha detto o quale documento lo dice." />
              </div>
              <CampoTesto id="nota" etichetta="Nota per chi decide" righe={2} aiuto="Massimo 80 caratteri, senza dati personali." />
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--s-2)', alignItems: 'center' }}>
                <Bottone variante="principale">Invia come proposta</Bottone>
                <Bottone variante="quieta" onClick={() => setModulo(false)}>Annulla</Bottone>
                <span style={{ marginLeft: 'auto', fontSize: 'var(--t-minuto)', color: 'var(--testo-tenue)' }}>Niente viene scritto subito: la voce resta in attesa di una decisione.</span>
              </div>
            </Scheda>
          ) : null}

          <Tabella colonne={['Voce', 'Tipo', 'Quando', 'Aggiornata', 'Provenienza']}
            righe={[
              ['Sportello di ascolto', 'scheda', 'martedì, 10:00-13:00', '15/09/2026', <EtichettaProvenienza tipo="kb" fonte="Casa San Bao" data="15/09/2026" affidabilita={2} glossa={false} />],
              ['Doposcuola', 'scheda', 'lunedì e mercoledì, 15:00-18:00', '02/08/2026', <EtichettaProvenienza tipo="kb" fonte="Casa San Bao" data="02/08/2026" affidabilita={2} glossa={false} />],
              ['Laboratorio di cucito', 'evento', '24/09/2026, 17:00', '14/09/2026', <EtichettaProvenienza tipo="kb" fonte="Calendario della Casa (iCal)" data="14/09/2026" affidabilita={2} glossa={false} />],
              ['Borsa lavoro giovani', 'opportunità', 'domande entro il 30/09/2026', '09/09/2026', <EtichettaProvenienza tipo="kb" fonte="Comune di Brindisi" data="09/09/2026" affidabilita={3} glossa={false} />],
            ]} />
        </section>
      </div>
    </div>
  );
}
Object.assign(window, { Registra });
