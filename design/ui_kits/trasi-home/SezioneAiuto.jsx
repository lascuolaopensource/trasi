const { Scheda, EtichettaProvenienza } = window.TrasiDesignSystem_18d101;

function Voce({ titolo, children }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
      <h3 style={{ margin: 0, fontSize: 'var(--t-guida)', fontWeight: 'var(--peso-forte)', color: 'var(--azione)' }}>{titolo}</h3>
      <p style={{ margin: 0, maxWidth: 'var(--misura-testo)' }}>{children}</p>
    </div>
  );
}

/** La sezione Aiuto: si legge in cinque minuti, in italiano semplice. */
function SezioneAiuto({ aperto = false, onToggle }) {
  return (
    <Scheda elemento="section" id="aiuto" padding="var(--padding-scheda-grande)" style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s-4)' }}>
      <button type="button" onClick={onToggle} aria-expanded={aperto} style={{
        font: 'inherit', fontSize: 'var(--t-titolo-m)', fontWeight: 'var(--peso-medio)', color: 'var(--azione)',
        background: 'transparent', border: 0, padding: 0, textAlign: 'left', cursor: 'pointer',
        display: 'flex', alignItems: 'center', gap: 'var(--s-2)', minHeight: 'var(--bersaglio-min)',
      }}>
        Aiuto
        <span style={{ fontSize: 'var(--t-minuto)', color: 'var(--testo-tenue)', fontWeight: 'var(--peso-normale)' }}>
          {aperto ? '(chiudi)' : '(cinque minuti di lettura)'}
        </span>
      </button>

      {aperto ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s-4)', lineHeight: 'var(--interlinea-larga)' }}>
          <p style={{ margin: 0, maxWidth: 'var(--misura-testo)' }}>
            Trasi è la porta della rete delle Case di Quartiere. Da qui si aprono quattro destinazioni, e
            ognuna si apre già sulla Casa scelta in alto.
          </p>

          <Voce titolo="CHIEDI">
            La chat con l'assistente della rete. Si scrive la domanda della persona e l'assistente risponde
            con luogo, orari e fonte. Da lì si può stampare un promemoria in formato A6, senza dati personali.
          </Voce>
          <Voce titolo="MAPPA">
            I luoghi e le Case della rete su una mappa, da guardare insieme alla persona.
          </Voce>
          <Voce titolo="REGISTRA / AGGIORNA">
            Il registro delle schede, degli eventi e delle opportunità della Casa. Non è ancora attivo:
            fino all'attivazione le correzioni passano dalle proposte fatte in chat.
          </Voce>
          <Voce titolo="OSSERVATORIO">
            I numeri della Casa e la coda delle proposte che aspettano una decisione. I conteggi troppo
            piccoli si leggono come «&lt;5»: è una tutela della riservatezza delle persone.
          </Voce>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s-3)' }}>
            <h3 style={{ margin: 0, fontSize: 'var(--t-guida)', fontWeight: 'var(--peso-forte)', color: 'var(--azione)' }}>Da dove viene l'informazione</h3>
            <p style={{ margin: 0, maxWidth: 'var(--misura-testo)' }}>
              Ogni informazione porta un'etichetta. Ce ne sono due, e dicono cose diverse.
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--s-2)' }}>
              <EtichettaProvenienza testo="[KB · Rete delle Case di Quartiere · agg. 15/09/2026 · affidabilità 2]" />
              <p style={{ margin: '0 0 var(--s-2)', maxWidth: 'var(--misura-testo)' }}>
                La rete lo sa: qualcuno della rete ha verificato questo dato. La data dice quando, il numero
                da 1 a 3 dice quanto è solida la fonte.
              </p>
              <EtichettaProvenienza tipo="esterna" fonte="OpenStreetMap contributors (ODbL)" ora="02:21" />
              <p style={{ margin: 0, maxWidth: 'var(--misura-testo)' }}>
                Trovato fuori: viene da una fonte esterna e nessuno della rete l'ha controllato. Si può usare,
                dicendo alla persona che non è verificato — meglio una telefonata prima di mandarla lì.
              </p>
            </div>
          </div>

          <Voce titolo="Le proposte">
            Trasi non cambia la memoria della rete da sola. Se in chat si segnala che un bar ha chiuso o che
            un orario è cambiato, nasce una proposta: resta in attesa finché una persona la approva. La riga
            in alto dice quante ne aspettano una decisione e da quanto tempo. Non c'è una scadenza da rispettare.
          </Voce>
          <Voce titolo="La riga «Oggi»">
            È una lettura della memoria della rete per la Casa scelta: eventi, schede in scadenza, proposte.
            Se il servizio dati non risponde entro tre secondi, la riga dice «dati non disponibili»: è
            un'informazione, non un guasto, e le quattro destinazioni funzionano comunque.
          </Voce>
          <Voce titolo="La Casa in alto">
            Il selettore ricorda la Casa nel browser: al prossimo accesso è già quella. L'unica cosa
            conservata è il nome breve della Casa, nessun dato personale. Tuturano porta la nota «dati
            provvisori»: alcune sue schede non sono ancora complete.
          </Voce>
          <Voce titolo="Tastiera">
            Si può usare tutto da tastiera: il tasto Tab passa dal salto alle destinazioni, al selettore
            della Casa, ad Aiuto ed Esci, poi a CHIEDI, MAPPA, OSSERVATORIO e alla coda delle proposte.
            Il riquadro giallo indica sempre dove sei.
          </Voce>
        </div>
      ) : null}
    </Scheda>
  );
}

Object.assign(window, { SezioneAiuto });
