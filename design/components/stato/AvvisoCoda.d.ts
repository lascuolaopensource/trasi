import type { CSSProperties } from 'react';

/**
 * La coda delle proposte da approvare: visibile senza essere un allarme.
 * @startingPoint section="Stato" subtitle="Coda proposte: con attese e vuota" viewport="700x150"
 */
export interface AvvisoCodaProps {
  /** Quante proposte sono in stato «proposta». 0 rende lo stato vuoto, in grigio. */
  numero?: number;
  /** Giorni di attesa della più vecchia: è il dato che dice se la coda è ferma. */
  giorniPiuVecchia?: number;
  /** Nome della Casa, se la coda è di una Casa sola. */
  casa?: string;
  href?: string;
  azione?: string;
  style?: CSSProperties;
}
export function AvvisoCoda(props: AvvisoCodaProps): JSX.Element;
