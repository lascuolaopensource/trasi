import type { CSSProperties } from 'react';

/**
 * Etichetta di provenienza: il cuore del prodotto («mai senza fonte»).
 * Il testo grezzo è quello composto dallo shim e non va riscritto: passalo in `testo`.
 * @startingPoint section="Provenienza" subtitle="KB verificata vs Esterna non verificata" viewport="700x150"
 */
export interface EtichettaProvenienzaProps {
  /** kb = la memoria della rete, verificata. esterna = trovato fuori, non verificato. */
  tipo?: 'kb' | 'esterna';
  /** Nome umano della fonte («Comune di Brindisi», «OpenStreetMap contributors (ODbL)»). */
  fonte?: string;
  /** Data di aggiornamento della scheda KB, formato 10/09/2026. */
  data?: string;
  /** Livello di affidabilità dichiarato, 1-3 (solo KB). */
  affidabilita?: number | string;
  /** Ora della consultazione, formato 11:42 (solo Esterna). */
  ora?: string;
  /** Il badge già composto dallo shim: se presente vince su tutto il resto. */
  testo?: string;
  /** La glossa in italiano semplice accanto all'etichetta (default true). */
  glossa?: boolean;
  style?: CSSProperties;
}
export function EtichettaProvenienza(props: EtichettaProvenienzaProps): JSX.Element;
