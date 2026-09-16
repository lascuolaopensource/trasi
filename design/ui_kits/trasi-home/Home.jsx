const { SezioneAiuto } = window;
const { Intestazione, SelettoreCasa, CASE, Bottone, Destinazione, RigaOggi, AvvisoCoda, Etichetta, SaltaContenuto } = window.TrasiDesignSystem_18d101;

/* Dati finti ma realistici: la riga «Oggi» arriva dalla vista v_oggi_casa,
   la coda da v_proposte_aperte. */
const OGGI = {
  'san-bao': { testo: 'Oggi a San Bao: 2 eventi · 1 scheda in scadenza · 3 proposte', coda: 3, giorni: 4 },
  bozzano: { testo: 'Oggi a Centro di Aggregazione Bozzano: 1 evento · 0 schede in scadenza · 1 proposta', coda: 1, giorni: 2 },
  tuturano: { testo: 'Oggi a Tuturano: 0 eventi · 0 schede in scadenza · 0 proposte', coda: 0, giorni: 0 },
};
const predefinito = { testo: null, coda: 2, giorni: 3 };

function nomeCasa(slug) { const c = CASE.find((x) => x.slug === slug); return c ? c.nome : slug; }

function datiOggi(slug) {
  const d = OGGI[slug];
  if (d) return d;
  return { ...predefinito, testo: 'Oggi a ' + nomeCasa(slug) + ': 1 evento · 2 schede in scadenza · 2 proposte' };
}

function Colonna({ children, style }) {
  return <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s-5)', ...style }}>{children}</div>;
}

function Home({ statoDati = 'ok' }) {
  const [casa, setCasa] = React.useState('san-bao');
  const [aiutoAperto, setAiutoAperto] = React.useState(false);
  const dati = datiOggi(casa);
  const nome = nomeCasa(casa);
  const url = (base) => base.replace('{casa}', casa);

  return (
    <div style={{ minHeight: '100%', background: 'var(--sfondo)', fontFamily: 'var(--font-corpo)', color: 'var(--testo)' }}>
      <SaltaContenuto href="#destinazioni" />
      <Intestazione
        logo="../../assets/logo-case-di-quartiere-bianco.png"
        casa={<SelettoreCasa valore={casa} onChange={(e) => setCasa(e.target.value)} />}
        azioni={<>
          <Bottone variante="suScuro" dimensione="compatta" onClick={() => setAiutoAperto(!aiutoAperto)} aria-expanded={aiutoAperto} aria-controls="aiuto">Aiuto</Bottone>
          <Bottone variante="suScuro" dimensione="compatta">Esci</Bottone>
        </>}
      />

      <div style={{ maxWidth: 'var(--misura-lettura)', margin: '0 auto', padding: 'var(--padding-pagina)', display: 'flex', flexDirection: 'column', gap: 'var(--s-6)' }}>
        {/* Fascia di stato: le due sole cose che cambiano da sole. Sta in testa
            perché si legge prima di scegliere, non dopo. */}
        <Colonna style={{ gap: 'var(--s-3)' }}>
          {statoDati === 'ok'
            ? <RigaOggi testo={dati.testo} />
            : statoDati === 'attesa'
              ? <RigaOggi stato="attesa" testo="Lettura dei dati di oggi in corso…" />
              : <RigaOggi stato="non-disponibile" testo="Dati non disponibili: la memoria della rete non risponde in questo momento." nota="È un'informazione, non un guasto: le destinazioni qui sotto funzionano." />}
          <AvvisoCoda numero={statoDati === 'ok' ? dati.coda : 0} giorniPiuVecchia={dati.giorni} casa={nome} href={url('/nocodb/?casa={casa}&view=da-approvare')} />
        </Colonna>

        <div id="destinazioni" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s-5)' }}>
          <h1 style={{ margin: 0, fontSize: 'var(--t-titolo-m)', fontWeight: 'var(--peso-medio)', color: 'var(--testo-tenue)' }}>
            La porta della rete delle Case di Quartiere
          </h1>

          <Destinazione
            variante="principale"
            titolo="CHIEDI"
            href={url('//onyx.lascuolaopensource.org/app?agentId=2&casa={casa}')}
            testo="L'assistente della rete: risponde alla persona che hai davanti — dove andare, con quali orari — e dichiara da dove viene ogni informazione."
            nota={'si apre con ' + nome + ' già impostata'}
          />

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 'var(--s-5)' }}>
            <Destinazione
              titolo="MAPPA"
              href={url('/metabase/dashboard/4?casa={casa}')}
              testo="Dove sono i luoghi e le Case vicine, da guardare insieme alla persona."
            />
            <Destinazione
              titolo="OSSERVATORIO"
              href={url('/metabase/dashboard/3?casa={casa}')}
              contatore={dati.coda ? dati.coda + (dati.coda === 1 ? ' proposta in attesa' : ' proposte in attesa') : null}
              testo="I numeri della Casa e le proposte che aspettano una decisione."
            />
          </div>

          <Destinazione
            titolo="REGISTRA / AGGIORNA"
            attivo={false}
            testo="Schede, eventi e opportunità della Casa."
            nota="Fino all'attivazione, le correzioni passano dalle proposte in chat."
          >
            <span style={{ marginTop: 'var(--s-2)' }}><Etichetta tono="attenzione">Servizio non ancora attivo</Etichetta></span>
          </Destinazione>
        </div>

        <SezioneAiuto aperto={aiutoAperto} onToggle={() => setAiutoAperto(!aiutoAperto)} />

        <footer style={{ padding: 'var(--s-4) 0 var(--s-8)', color: 'var(--testo-tenue)', fontSize: 'var(--t-corpo)' }}>
          <p style={{ margin: 0 }}>Trasi · rete delle Case di Quartiere di Brindisi. Questa pagina non conserva dati personali: la Casa scelta resta nel browser.</p>
        </footer>
      </div>
    </div>
  );
}

Object.assign(window, { Home });
