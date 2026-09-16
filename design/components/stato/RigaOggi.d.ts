import type { CSSProperties } from 'react';

/**
 * La riga «Oggi»: la lettura di `v_oggi_casa` per la Casa scelta.
 * @startingPoint section="Stato" subtitle="Riga Oggi: attesa, dati, dati non disponibili" viewport="700x150"
 */
export interface RigaOggiProps {
  stato?: 'attesa' | 'ok' | 'non-disponibile';
  /** Il campo `testo` composto dalla vista: «Oggi a San Bao: 2 eventi · 1 scheda in scadenza · 3 proposte». */
  testo: string;
  /** Seconda riga piccola, per spiegare lo stato senza allarmare. */
  nota?: string;
  style?: CSSProperties;
}
export function RigaOggi(props: RigaOggiProps): JSX.Element;
