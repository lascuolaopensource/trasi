const { Intestazione, SelettoreCasa, Bottone, Scheda, Tabella, Etichetta, EtichettaProvenienza } = window.TrasiDesignSystem_18d101;

/* Le 10 Case con le coordinate reali non sono in questo progetto: la mappa vera è
   la dashboard Metabase «Mappa» (id 4) che disegna i pin da v_mappa_case. Qui non
   si inventa una cartografia: si mostra la cornice Trasi e l'elenco dei luoghi con
   la loro provenienza, che è la parte che il design system possiede. */

function Mappa() {
  return (
    <div style={{ minHeight: '100vh', fontFamily: 'var(--font-corpo)', color: 'var(--testo)' }}>
      <Intestazione logo="../../assets/logo-case-di-quartiere-bianco.png"
        casa={<SelettoreCasa valore="san-bao" onChange={() => {}} />}
        azioni={<><Bottone variante="suScuro" dimensione="compatta" href="../trasi-home/index.html">Torna a Trasi</Bottone><Bottone variante="suScuro" dimensione="compatta">Esci</Bottone></>} />

      <div style={{ maxWidth: 'var(--misura-lettura)', margin: '0 auto', padding: 'var(--padding-pagina)', display: 'flex', flexDirection: 'column', gap: 'var(--s-5)' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 'var(--t-titolo-m)', fontWeight: 'var(--peso-medio)' }}>MAPPA — intorno a San Bao</h1>
          <p style={{ margin: '4px 0 0', color: 'var(--testo-tenue)' }}>I luoghi entro 1,5 km, da guardare insieme alla persona.</p>
        </div>

        <Scheda padding="var(--s-6)" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s-2)', alignItems: 'center', textAlign: 'center', background: 'var(--superficie-incassata)' }}>
          <p style={{ margin: 0, fontWeight: 'var(--peso-medio)' }}>Qui sta la mappa</p>
          <p style={{ margin: 0, maxWidth: '36rem', color: 'var(--testo-tenue)' }}>
            La mappa è la dashboard Metabase «Mappa»: disegna i pin delle Case e dei luoghi dalle viste
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--t-minuto)' }}> v_mappa_case</span> e
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--t-minuto)' }}> v_mappa_luoghi</span>.
            Il raggio di vicinanza non è un cerchio disegnato: è una nota nel dettaglio del pin.
          </p>
          <Etichetta tono="neutra">contenuto reso da Metabase — non ridisegnato qui</Etichetta>
        </Scheda>

        <section style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s-3)' }}>
          <h2 style={{ margin: 0, fontSize: 'var(--t-titolo-s)', fontWeight: 'var(--peso-forte)', color: 'var(--azione)', letterSpacing: 'var(--spaziatura-destinazione)' }}>LUOGHI VICINI</h2>
          <Tabella colonne={['Luogo', 'Distanza', 'Orari', 'Provenienza']}
            righe={[
              ['Lavanderia sociale Molo 12', '850 m', 'lun-ven 9:00-13:00', <EtichettaProvenienza testo="[KB · Rete delle Case di Quartiere · agg. 15/09/2026 · affidabilità 2]" glossa={false} />],
              ['Sportello CAF, via Nazario Sauro', '1,2 km', 'mar e gio 9:00-12:00', <EtichettaProvenienza tipo="kb" fonte="Comune di Brindisi" data="09/09/2026" affidabilita={3} glossa={false} />],
              ['Lavanderia a gettoni, via Bastioni Carlo V', '1,4 km', 'orari non disponibili', <EtichettaProvenienza tipo="esterna" fonte="OpenStreetMap contributors (ODbL)" ora="11:42" glossa={false} />],
            ]} />
          <p style={{ margin: 0, fontSize: 'var(--t-minuto)', color: 'var(--testo-tenue)' }}>
            «Orari non disponibili» non è un errore: a Brindisi solo una piccola parte dei luoghi esterni
            dichiara gli orari, e un luogo senza orari resta utile.
          </p>
        </section>

        <section style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s-3)' }}>
          <h2 style={{ margin: 0, fontSize: 'var(--t-titolo-s)', fontWeight: 'var(--peso-forte)', color: 'var(--azione)', letterSpacing: 'var(--spaziatura-destinazione)' }}>CASE VICINE</h2>
          <Tabella densita="compatta" colonne={['Casa', 'Distanza', 'Nota']}
            righe={[
              ['Molo 12', '850 m', ''],
              ['Minimus', '1,9 km', ''],
              ['Tuturano', '12 km', <Etichetta tono="neutra">dati provvisori</Etichetta>],
            ]} />
        </section>
      </div>
    </div>
  );
}
Object.assign(window, { Mappa });
