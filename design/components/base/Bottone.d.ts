import type { ReactNode, CSSProperties } from 'react';

/**
 * Azione dell'interfaccia: bottone o collegamento con la stessa veste.
 * @startingPoint section="Base" subtitle="Bottoni: principale, secondaria, quieta, su scuro" viewport="700x150"
 */
export interface BottoneProps {
  /** principale = una sola per schermata; suScuro vive nella testata blu. */
  variante?: 'principale' | 'secondaria' | 'quieta' | 'suScuro';
  /** normale = 44 px di altezza minima (bersaglio tattile). */
  dimensione?: 'normale' | 'compatta';
  /** Se presente, il componente rende un <a>. */
  href?: string;
  disabilitato?: boolean;
  onClick?: () => void;
  style?: CSSProperties;
  children?: ReactNode;
}
export function Bottone(props: BottoneProps): JSX.Element;
