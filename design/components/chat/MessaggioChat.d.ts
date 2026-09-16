import type { ReactNode, CSSProperties } from 'react';
import type { EtichettaProvenienzaProps } from '../provenienza/EtichettaProvenienza';

/**
 * Un turno della chat CHIEDI, con l'etichetta di provenienza sotto la risposta.
 * @startingPoint section="Chat" subtitle="Turni operatore e assistente con provenienza" viewport="700x320"
 */
export interface MessaggioChatProps {
  autore?: 'operatore' | 'assistente';
  testo?: string;
  /** Le props dell'<EtichettaProvenienza /> da mostrare sotto la risposta. */
  provenienza?: EtichettaProvenienzaProps;
  /** Azioni offerte dalla risposta: «Stampa il biglietto», «Segnala un cambiamento». */
  azioni?: ReactNode;
  style?: CSSProperties;
  children?: ReactNode;
}
export function MessaggioChat(props: MessaggioChatProps): JSX.Element;
