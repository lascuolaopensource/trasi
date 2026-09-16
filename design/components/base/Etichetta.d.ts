import type { ReactNode, CSSProperties } from 'react';

/** Etichetta di stato in parole («Servizio non ancora attivo», «dati provvisori»). */
export interface EtichettaProps {
  /** attenzione = giallo sole; neutra = grigio carta; informativa = azzurro KB. */
  tono?: 'attenzione' | 'neutra' | 'informativa';
  /** Aggiunge un contorno di 1 px: serve quando l'etichetta sta su una superficie colorata. */
  bordo?: boolean;
  style?: CSSProperties;
  children?: ReactNode;
}
export function Etichetta(props: EtichettaProps): JSX.Element;
