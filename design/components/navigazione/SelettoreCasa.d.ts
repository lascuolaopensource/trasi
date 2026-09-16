import type { ChangeEvent, CSSProperties } from 'react';

export interface Casa {
  /** Lo slug salvato in localStorage e usato negli href («san-bao»). */
  slug: string;
  nome: string;
  /** Nota che entra nel testo dell'opzione, es. «dati provvisori» (Tuturano). */
  nota?: string;
}

/**
 * Il selettore della Casa di riferimento: etichetta sempre visibile, nota in parole.
 * @startingPoint section="Navigazione" subtitle="Selettore Casa, con la nota «dati provvisori»" viewport="700x180"
 */
export interface SelettoreCasaProps {
  id?: string;
  /** Slug della Casa scelta. */
  valore?: string;
  case?: Casa[];
  onChange?: (evento: ChangeEvent<HTMLSelectElement>) => void;
  /** true quando il selettore vive nella testata blu (default). */
  suScuro?: boolean;
  style?: CSSProperties;
}
export function SelettoreCasa(props: SelettoreCasaProps): JSX.Element;
export const CASE: Casa[];
