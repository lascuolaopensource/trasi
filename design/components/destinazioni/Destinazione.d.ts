import type { ReactNode, CSSProperties } from 'react';

/**
 * Una destinazione della Home (CHIEDI, MAPPA, REGISTRA/AGGIORNA, OSSERVATORIO).
 * @startingPoint section="Destinazioni" subtitle="Destinazione principale e secondarie" viewport="700x300"
 */
export interface DestinazioneProps {
  titolo: string;
  testo?: string;
  href?: string;
  /** principale = CHIEDI, la cosa che si usa decine di volte al giorno. */
  variante?: 'principale' | 'secondaria';
  /** false = servizio predisposto ma non ancora attivo: il riquadro resta leggibile e non cliccabile. */
  attivo?: boolean;
  /** Riga piccola in fondo: «Servizio non ancora attivo», «si apre con la Casa già impostata». */
  nota?: string;
  /** Conteggio a destra del titolo, es. «3 proposte in attesa». */
  contatore?: string;
  style?: CSSProperties;
  children?: ReactNode;
}
export function Destinazione(props: DestinazioneProps): JSX.Element;
