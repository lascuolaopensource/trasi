import type { ReactNode, CSSProperties } from 'react';

/**
 * Tabella di dati (coda proposte, schede della Casa, righe del registro).
 * @startingPoint section="Dati" subtitle="Tabella con intestazioni e zebratura" viewport="700x260"
 */
export interface Colonna { titolo: string }

export interface TabellaProps {
  colonne?: (string | Colonna)[];
  /** Le righe: ogni cella può essere testo o un nodo (es. un'<EtichettaProvenienza />). */
  righe?: ReactNode[][];
  didascalia?: string;
  densita?: 'comoda' | 'compatta';
  style?: CSSProperties;
}
export function Tabella(props: TabellaProps): JSX.Element;
