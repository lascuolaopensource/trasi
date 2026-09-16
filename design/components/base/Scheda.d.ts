import type { ReactNode, CSSProperties } from 'react';

/** Superficie di contenuto. Separa con un bordo, non con un'ombra. */
export interface SchedaProps {
  /** Colore del filetto a sinistra, es. 'var(--coda-filetto)'. Assente = nessun filetto. */
  filetto?: string;
  /** Tag da rendere (default 'div'): 'section', 'li', 'article'. */
  elemento?: string;
  padding?: string;
  style?: CSSProperties;
  children?: ReactNode;
}
export function Scheda(props: SchedaProps): JSX.Element;
