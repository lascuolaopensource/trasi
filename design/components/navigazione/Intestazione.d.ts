import type { ReactNode, CSSProperties } from 'react';

/**
 * La testata di Trasi: logo della rete, nome TRASI, Casa di riferimento, azioni.
 * @startingPoint section="Navigazione" subtitle="Testata blu notte con selettore e azioni" viewport="1100x140"
 */
export interface IntestazioneProps {
  /** Percorso del logo bianco; passa null per il solo logotipo TRASI. */
  logo?: string | null;
  sottotitolo?: string;
  /** Di norma un <SelettoreCasa />. */
  casa?: ReactNode;
  /** Di norma due <Bottone variante="suScuro" />: Aiuto ed Esci. */
  azioni?: ReactNode;
  style?: CSSProperties;
}
export function Intestazione(props: IntestazioneProps): JSX.Element;
