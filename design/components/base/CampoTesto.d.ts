import type { ChangeEvent } from 'react';

/** Campo di testo: l'etichetta è sempre visibile, mai solo un segnaposto. */
export interface CampoTestoProps {
  id: string;
  etichetta: string;
  /** Una riga di aiuto sotto il campo, in italiano semplice. */
  aiuto?: string;
  valore?: string;
  onChange?: (evento: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => void;
  /** Se presente, il campo diventa un'area di testo di N righe. */
  righe?: number;
  segnaposto?: string;
  larghezza?: string;
}
export function CampoTesto(props: CampoTestoProps): JSX.Element;
