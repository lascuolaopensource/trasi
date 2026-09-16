/* @ds-bundle: {"format":4,"namespace":"TrasiDesignSystem_18d101","components":[{"name":"Bottone","sourcePath":"components/base/Bottone.jsx"},{"name":"CampoTesto","sourcePath":"components/base/CampoTesto.jsx"},{"name":"Etichetta","sourcePath":"components/base/Etichetta.jsx"},{"name":"Scheda","sourcePath":"components/base/Scheda.jsx"},{"name":"MessaggioChat","sourcePath":"components/chat/MessaggioChat.jsx"},{"name":"Tabella","sourcePath":"components/dati/Tabella.jsx"},{"name":"Destinazione","sourcePath":"components/destinazioni/Destinazione.jsx"},{"name":"Intestazione","sourcePath":"components/navigazione/Intestazione.jsx"},{"name":"SaltaContenuto","sourcePath":"components/navigazione/SaltaContenuto.jsx"},{"name":"CASE","sourcePath":"components/navigazione/SelettoreCasa.jsx"},{"name":"SelettoreCasa","sourcePath":"components/navigazione/SelettoreCasa.jsx"},{"name":"EtichettaProvenienza","sourcePath":"components/provenienza/EtichettaProvenienza.jsx"},{"name":"AvvisoCoda","sourcePath":"components/stato/AvvisoCoda.jsx"},{"name":"RigaOggi","sourcePath":"components/stato/RigaOggi.jsx"}],"sourceHashes":{"components/base/Bottone.jsx":"71d9667d2004","components/base/CampoTesto.jsx":"3afbcd70a67a","components/base/Etichetta.jsx":"54f798ff68f8","components/base/Scheda.jsx":"8e0d80b145ab","components/chat/MessaggioChat.jsx":"a707f84dcea6","components/dati/Tabella.jsx":"e10258bb2e1e","components/destinazioni/Destinazione.jsx":"33058cdebea3","components/navigazione/Intestazione.jsx":"2c22301a56c5","components/navigazione/SaltaContenuto.jsx":"9ad0c49cb1d7","components/navigazione/SelettoreCasa.jsx":"2fa580128f49","components/provenienza/EtichettaProvenienza.jsx":"81b1915de9c6","components/stato/AvvisoCoda.jsx":"eef49c73a12c","components/stato/RigaOggi.jsx":"98c30cb825bc","ui_kits/trasi-chiedi/Chiedi.jsx":"5ae331e8572b","ui_kits/trasi-home/Home.jsx":"d0ad5490021a","ui_kits/trasi-home/SezioneAiuto.jsx":"3ac904fbf05c","ui_kits/trasi-mappa/Mappa.jsx":"d3f240d33a84","ui_kits/trasi-osservatorio/Osservatorio.jsx":"d138124125a5","ui_kits/trasi-registra/Registra.jsx":"265322d88344"},"inlinedExternals":[],"unexposedExports":[]} */

(() => {

const __ds_ns = (window.TrasiDesignSystem_18d101 = window.TrasiDesignSystem_18d101 || {});

const __ds_scope = {};

(__ds_ns.__errors = __ds_ns.__errors || []);

// components/base/Bottone.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
const base = {
  fontFamily: 'var(--font-corpo)',
  fontSize: 'var(--t-corpo)',
  fontWeight: 'var(--peso-medio)',
  lineHeight: 'var(--interlinea-stretta)',
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  gap: 'var(--s-2)',
  borderRadius: 'var(--raggio)',
  borderStyle: 'solid',
  borderWidth: 'var(--contorno)',
  cursor: 'pointer',
  textDecoration: 'none',
  transition: 'var(--transizione-stato)',
  boxSizing: 'border-box'
};
const dimensioni = {
  normale: {
    minHeight: 'var(--bersaglio-min)',
    padding: '10px 18px'
  },
  compatta: {
    minHeight: '36px',
    padding: '6px 12px',
    fontSize: 'var(--t-minuto)'
  }
};
const varianti = {
  principale: {
    background: 'var(--testata)',
    color: 'var(--testo-su-scuro)',
    borderColor: 'var(--testata)'
  },
  secondaria: {
    background: 'var(--superficie)',
    color: 'var(--azione)',
    borderColor: 'var(--bordo-forte)'
  },
  quieta: {
    background: 'transparent',
    color: 'var(--azione)',
    borderColor: 'transparent',
    textDecoration: 'underline',
    textUnderlineOffset: '3px'
  },
  suScuro: {
    background: 'transparent',
    color: 'var(--testo-su-scuro)',
    borderColor: 'var(--testo-su-scuro)',
    textDecoration: 'underline',
    textUnderlineOffset: '3px'
  }
};

/** Un'azione. Sobria: cambia solo colore, non si muove e non si ingrandisce. */
function Bottone({
  variante = 'secondaria',
  dimensione = 'normale',
  href,
  disabilitato = false,
  onClick,
  style,
  children,
  ...resto
}) {
  const stile = {
    ...base,
    ...dimensioni[dimensione],
    ...varianti[variante],
    ...(disabilitato ? {
      opacity: 0.55,
      cursor: 'not-allowed'
    } : null),
    ...style
  };
  if (href && !disabilitato) return /*#__PURE__*/React.createElement("a", _extends({
    href: href,
    style: stile
  }, resto), children);
  return /*#__PURE__*/React.createElement("button", _extends({
    type: "button",
    style: stile,
    disabled: disabilitato,
    onClick: onClick
  }, resto), children);
}
Object.assign(__ds_scope, { Bottone });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/base/Bottone.jsx", error: String((e && e.message) || e) }); }

// components/base/CampoTesto.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/** Campo di testo con etichetta sempre visibile e testo di aiuto opzionale. */
function CampoTesto({
  id,
  etichetta,
  aiuto,
  valore,
  onChange,
  righe,
  segnaposto,
  larghezza = '100%',
  ...resto
}) {
  const Controllo = righe ? 'textarea' : 'input';
  const stileControllo = {
    font: 'inherit',
    fontSize: 'var(--t-corpo)',
    color: 'var(--testo)',
    background: 'var(--superficie)',
    border: 'var(--contorno) solid var(--bordo)',
    borderRadius: 'var(--raggio)',
    padding: '10px 12px',
    minHeight: righe ? undefined : 'var(--bersaglio-min)',
    width: '100%',
    boxSizing: 'border-box'
  };
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--s-1)',
      width: larghezza,
      fontFamily: 'var(--font-corpo)'
    }
  }, /*#__PURE__*/React.createElement("label", {
    htmlFor: id,
    style: {
      fontSize: 'var(--t-corpo)',
      fontWeight: 'var(--peso-medio)',
      color: 'var(--testo)'
    }
  }, etichetta), /*#__PURE__*/React.createElement(Controllo, _extends({
    id: id,
    value: valore,
    onChange: onChange,
    rows: righe,
    placeholder: segnaposto,
    style: stileControllo
  }, resto)), aiuto ? /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      fontSize: 'var(--t-corpo)',
      color: 'var(--testo-tenue)'
    }
  }, aiuto) : null);
}
Object.assign(__ds_scope, { CampoTesto });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/base/CampoTesto.jsx", error: String((e && e.message) || e) }); }

// components/base/Etichetta.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
const toni = {
  attenzione: {
    background: 'var(--attenzione-sfondo)',
    color: 'var(--attenzione-testo)',
    borderColor: 'var(--attenzione-testo)'
  },
  neutra: {
    background: 'var(--superficie-incassata)',
    color: 'var(--testo-tenue)',
    borderColor: 'var(--bordo)'
  },
  informativa: {
    background: 'var(--kb-sfondo)',
    color: 'var(--kb-testo)',
    borderColor: 'var(--kb-bordo)'
  }
};

/** Etichetta di stato: poche parole, sempre leggibili anche senza colore. */
function Etichetta({
  tono = 'neutra',
  bordo = false,
  style,
  children,
  ...resto
}) {
  return /*#__PURE__*/React.createElement("span", _extends({
    style: {
      display: 'inline-block',
      padding: '2px 8px',
      borderRadius: 'var(--raggio-piccolo)',
      fontFamily: 'var(--font-corpo)',
      fontSize: 'var(--t-minuto)',
      fontWeight: 'var(--peso-medio)',
      lineHeight: '1.45',
      borderStyle: 'solid',
      borderWidth: bordo ? '1px' : '0',
      ...toni[tono],
      ...style
    }
  }, resto), children);
}
Object.assign(__ds_scope, { Etichetta });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/base/Etichetta.jsx", error: String((e && e.message) || e) }); }

// components/base/Scheda.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/** Superficie di contenuto: bianca, bordo di 2 px, nessuna ombra. */
function Scheda({
  filetto,
  elemento = 'div',
  padding = 'var(--padding-scheda)',
  style,
  children,
  ...resto
}) {
  const Elemento = elemento;
  return /*#__PURE__*/React.createElement(Elemento, _extends({
    style: {
      background: 'var(--superficie-scheda)',
      color: 'var(--testo)',
      border: 'var(--contorno) solid var(--bordo-tenue)',
      borderRadius: 'var(--raggio)',
      padding,
      boxShadow: 'var(--ombra-nessuna)',
      ...(filetto ? {
        borderLeft: 'var(--filetto-forte) solid ' + filetto
      } : null),
      ...style
    }
  }, resto), children);
}
Object.assign(__ds_scope, { Scheda });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/base/Scheda.jsx", error: String((e && e.message) || e) }); }

// components/dati/Tabella.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/** Tabella di dati: righe alte, intestazioni fisse nel senso della lettura, zebratura tenue. */
function Tabella({
  colonne = [],
  righe = [],
  didascalia,
  densita = 'comoda',
  style,
  ...resto
}) {
  const pad = densita === 'compatta' ? '8px 12px' : '12px 14px';
  return /*#__PURE__*/React.createElement("div", _extends({
    style: {
      overflowX: 'auto',
      border: 'var(--contorno) solid var(--bordo-tenue)',
      borderRadius: 'var(--raggio)',
      background: 'var(--superficie)',
      ...style
    }
  }, resto), /*#__PURE__*/React.createElement("table", {
    style: {
      borderCollapse: 'collapse',
      width: '100%',
      fontFamily: 'var(--font-corpo)',
      fontSize: 'var(--t-corpo)'
    }
  }, didascalia ? /*#__PURE__*/React.createElement("caption", {
    style: {
      textAlign: 'left',
      padding: pad,
      color: 'var(--testo-tenue)',
      fontSize: 'var(--t-minuto)'
    }
  }, didascalia) : null, /*#__PURE__*/React.createElement("thead", null, /*#__PURE__*/React.createElement("tr", null, colonne.map((c, i) => /*#__PURE__*/React.createElement("th", {
    key: i,
    scope: "col",
    style: {
      textAlign: 'left',
      padding: pad,
      borderBottom: 'var(--contorno) solid var(--bordo)',
      fontWeight: 'var(--peso-forte)',
      color: 'var(--testo)',
      whiteSpace: 'nowrap'
    }
  }, typeof c === 'string' ? c : c.titolo)))), /*#__PURE__*/React.createElement("tbody", null, righe.map((r, i) => /*#__PURE__*/React.createElement("tr", {
    key: i,
    style: {
      background: i % 2 ? 'var(--carta)' : 'var(--superficie)'
    }
  }, r.map((cella, j) => /*#__PURE__*/React.createElement("td", {
    key: j,
    style: {
      padding: pad,
      borderBottom: '1px solid var(--bordo-tenue)',
      color: 'var(--testo)',
      verticalAlign: 'top'
    }
  }, cella)))))));
}
Object.assign(__ds_scope, { Tabella });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/dati/Tabella.jsx", error: String((e && e.message) || e) }); }

// components/destinazioni/Destinazione.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/* Le quattro destinazioni non hanno la stessa frequenza d'uso: CHIEDI decine di
   volte al giorno, OSSERVATORIO una volta a settimana. La variante «principale»
   esiste per questo — la gerarchia visiva dice quanto una cosa si usa. */

const varianti = {
  principale: {
    titolo: 'var(--t-titolo-xl)',
    padding: 'var(--s-8)',
    bordo: 'var(--bordo-forte)',
    testo: 'var(--t-guida)'
  },
  secondaria: {
    titolo: 'var(--t-titolo-s)',
    padding: 'var(--s-5)',
    bordo: 'var(--bordo)',
    testo: 'var(--t-corpo)'
  }
};

/** Una destinazione della Home: apre un servizio con la Casa già impostata. */
function Destinazione({
  titolo,
  testo,
  href,
  variante = 'secondaria',
  attivo = true,
  nota,
  contatore,
  style,
  children,
  ...resto
}) {
  const v = varianti[variante] || varianti.secondaria;
  return /*#__PURE__*/React.createElement("a", _extends({
    href: attivo ? href : undefined,
    "aria-disabled": attivo ? undefined : 'true',
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--s-2)',
      height: '100%',
      padding: v.padding,
      background: 'var(--superficie)',
      color: 'var(--testo)',
      border: 'var(--contorno) solid ' + v.bordo,
      borderRadius: 'var(--raggio)',
      textDecoration: 'none',
      transition: 'var(--transizione-stato)',
      boxSizing: 'border-box',
      ...(attivo ? null : {
        background: 'var(--superficie-incassata)'
      }),
      ...style
    }
  }, resto), /*#__PURE__*/React.createElement("span", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      alignItems: 'baseline',
      justifyContent: 'space-between',
      gap: 'var(--s-2)'
    }
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: v.titolo,
      fontWeight: 'var(--peso-forte)',
      letterSpacing: 'var(--spaziatura-destinazione)',
      lineHeight: 'var(--interlinea-stretta)',
      color: 'var(--azione)'
    }
  }, titolo), contatore ? /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 'var(--t-corpo)',
      color: 'var(--coda-testo)',
      fontWeight: 'var(--peso-medio)'
    }
  }, contatore) : null), testo ? /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: v.testo,
      lineHeight: 'var(--interlinea)',
      color: 'var(--testo)',
      maxWidth: 'var(--misura-testo)'
    }
  }, testo) : null, nota ? /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 'var(--t-minuto)',
      color: 'var(--testo-tenue)'
    }
  }, nota) : null, children);
}
Object.assign(__ds_scope, { Destinazione });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/destinazioni/Destinazione.jsx", error: String((e && e.message) || e) }); }

// components/navigazione/Intestazione.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/** La testata: chi sono, per quale Casa, e le due azioni di servizio. */
function Intestazione({
  logo = 'assets/logo-case-di-quartiere-bianco.png',
  sottotitolo = 'Rete delle Case di Quartiere di Brindisi',
  casa,
  azioni,
  style,
  ...resto
}) {
  return /*#__PURE__*/React.createElement("header", _extends({
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      alignItems: 'flex-end',
      justifyContent: 'space-between',
      gap: 'var(--s-4) var(--s-6)',
      padding: 'var(--s-4) var(--padding-pagina)',
      background: 'var(--testata)',
      color: 'var(--testo-su-scuro)',
      borderBottom: 'var(--filetto-testata) solid var(--testata-bordo)',
      fontFamily: 'var(--font-corpo)',
      ...style
    }
  }, resto), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      alignItems: 'center',
      gap: 'var(--s-4)',
      minWidth: 0
    }
  }, logo ? /*#__PURE__*/React.createElement("img", {
    src: logo,
    alt: "Case di Quartiere Brindisi",
    style: {
      height: '44px',
      width: 'auto'
    }
  }) : null, /*#__PURE__*/React.createElement("div", {
    style: {
      minWidth: 0
    }
  }, /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      fontSize: 'var(--t-titolo-m)',
      fontWeight: 'var(--peso-forte)',
      letterSpacing: 'var(--spaziatura-marchio)'
    }
  }, "TRASI"), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      fontSize: 'var(--t-minuto)',
      color: 'rgba(255,255,255,0.86)'
    }
  }, sottotitolo))), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      alignItems: 'flex-end',
      gap: 'var(--s-4)',
      minWidth: 0
    }
  }, casa, azioni ? /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 'var(--s-2)',
      alignItems: 'center'
    }
  }, azioni) : null));
}
Object.assign(__ds_scope, { Intestazione });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/navigazione/Intestazione.jsx", error: String((e && e.message) || e) }); }

// components/navigazione/SaltaContenuto.jsx
try { (() => {
/** Il salto al contenuto: invisibile fino al primo Tab, poi ben visibile. */
function SaltaContenuto({
  href = '#contenuto',
  children = 'Salta alle destinazioni'
}) {
  return /*#__PURE__*/React.createElement("a", {
    href: href,
    className: "trasi-salta",
    style: {
      position: 'absolute',
      left: '-9999px',
      top: 0,
      zIndex: 10,
      padding: '12px 16px',
      background: 'var(--superficie)',
      color: 'var(--testo)',
      border: 'var(--contorno) solid var(--testo)',
      borderRadius: '0 0 var(--raggio) 0',
      fontFamily: 'var(--font-corpo)',
      fontWeight: 'var(--peso-medio)'
    }
  }, children);
}
Object.assign(__ds_scope, { SaltaContenuto });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/navigazione/SaltaContenuto.jsx", error: String((e && e.message) || e) }); }

// components/navigazione/SelettoreCasa.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/* Le 10 Case della rete, con lo slug usato da localStorage («trasi.casa_id»)
   e dagli href delle destinazioni. Tuturano porta «dati provvisori» nel testo
   dell'opzione: l'informazione non dipende dal colore né da un'icona. */
const CASE = [{
  slug: 'santa-spazio',
  nome: 'Santa Spazio Culturale'
}, {
  slug: 'molo12',
  nome: 'Molo 12'
}, {
  slug: 'erranti',
  nome: 'Accademia degli Erranti'
}, {
  slug: 'buscicchio',
  nome: 'Parco Buscicchio'
}, {
  slug: 'san-bao',
  nome: 'San Bao'
}, {
  slug: 'minimus',
  nome: 'Minimus'
}, {
  slug: 'pop',
  nome: 'POP — Piccolo Opificio Popolare'
}, {
  slug: 'bozzano',
  nome: 'Centro di Aggregazione Bozzano'
}, {
  slug: 'dream',
  nome: 'Dream: Laboratorio Creativo'
}, {
  slug: 'tuturano',
  nome: 'Tuturano',
  nota: 'dati provvisori'
}];

/** La Casa di riferimento: si cambia raramente, quindi si legge sempre e si apre solo se serve. */
function SelettoreCasa({
  id = 'selettore-casa',
  valore = 'san-bao',
  case: elenco = CASE,
  onChange,
  suScuro = true,
  style,
  ...resto
}) {
  const scelta = elenco.find(c => c.slug === valore);
  const coloreEtichetta = suScuro ? 'rgba(255,255,255,0.86)' : 'var(--testo-tenue)';
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--s-1)',
      minWidth: 0,
      fontFamily: 'var(--font-corpo)',
      ...style
    }
  }, /*#__PURE__*/React.createElement("label", {
    htmlFor: id,
    style: {
      fontSize: 'var(--t-minuto)',
      fontWeight: 'var(--peso-medio)',
      color: coloreEtichetta,
      letterSpacing: '0.02em'
    }
  }, "Casa di riferimento"), /*#__PURE__*/React.createElement("select", _extends({
    id: id,
    value: valore,
    onChange: onChange,
    style: {
      font: 'inherit',
      fontSize: 'var(--t-corpo)',
      fontWeight: 'var(--peso-medio)',
      color: 'var(--testo)',
      background: 'var(--superficie)',
      border: 'var(--contorno) solid ' + (suScuro ? 'var(--testata-bordo)' : 'var(--bordo)'),
      borderRadius: 'var(--raggio)',
      padding: '8px 10px',
      minHeight: 'var(--bersaglio-min)',
      maxWidth: 'min(24rem, 100%)',
      minWidth: 0
    }
  }, resto), elenco.map(c => /*#__PURE__*/React.createElement("option", {
    key: c.slug,
    value: c.slug
  }, c.nota ? c.nome + ' — ' + c.nota : c.nome))), scelta && scelta.nota ? /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      fontSize: 'var(--t-minuto)',
      color: suScuro ? 'rgba(255,255,255,0.92)' : 'var(--attenzione-testo)'
    }
  }, scelta.nome, ": ", scelta.nota, " \u2014 alcune schede non sono ancora complete.") : null);
}
Object.assign(__ds_scope, { CASE, SelettoreCasa });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/navigazione/SelettoreCasa.jsx", error: String((e && e.message) || e) }); }

// components/provenienza/EtichettaProvenienza.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/* Le due forme sono quelle composte dallo shim (shim/app/badge.py) e vanno
   riportate verbatim:
     [KB · Comune di Brindisi · agg. 10/09/2026 · affidabilità 3]
     [Esterna · OpenStreetMap contributors (ODbL) · consultata 11:42 · non verificata dalla rete]
   Qui cambia solo la veste. La distinzione KB/Esterna non dipende dal colore:
   la porta la parola («KB» / «Esterna»), il tratto del bordo (continuo /
   tratteggiato) e la glossa in italiano semplice. */

const toni = {
  kb: {
    colore: 'var(--kb-testo)',
    bordo: 'var(--kb-bordo)',
    sfondo: 'var(--kb-sfondo)',
    tratto: 'solid',
    parola: 'KB',
    glossa: 'la rete lo sa'
  },
  esterna: {
    colore: 'var(--esterna-testo)',
    bordo: 'var(--esterna-bordo)',
    sfondo: 'var(--esterna-sfondo)',
    tratto: 'dashed',
    parola: 'Esterna',
    glossa: 'trovato fuori, non verificato dalla rete'
  }
};
function testoPredefinito(tipo, {
  fonte,
  data,
  affidabilita,
  ora
}) {
  if (tipo === 'kb') return '[KB · ' + (fonte || 'fonte non dichiarata') + ' · agg. ' + (data || '—') + ' · affidabilità ' + (affidabilita || '—') + ']';
  return '[Esterna · ' + (fonte || 'fonte non dichiarata') + ' · consultata ' + (ora || '—') + ' · non verificata dalla rete]';
}

/** L'etichetta di provenienza di un'informazione: da dove viene, e se la rete l'ha verificata. */
function EtichettaProvenienza({
  tipo = 'kb',
  fonte,
  data,
  affidabilita,
  ora,
  testo,
  glossa = true,
  style,
  ...resto
}) {
  const tono = toni[tipo] || toni.kb;
  const riga = testo || testoPredefinito(tipo, {
    fonte,
    data,
    affidabilita,
    ora
  });
  return /*#__PURE__*/React.createElement("span", _extends({
    style: {
      display: 'inline-flex',
      flexWrap: 'wrap',
      alignItems: 'baseline',
      gap: 'var(--s-2)',
      fontFamily: 'var(--font-corpo)',
      ...style
    }
  }, resto), /*#__PURE__*/React.createElement("span", {
    style: {
      display: 'inline-flex',
      alignItems: 'baseline',
      gap: 'var(--s-2)',
      fontFamily: 'var(--font-etichette)',
      fontSize: 'var(--t-minuto)',
      lineHeight: '1.5',
      color: tono.colore,
      background: tono.sfondo,
      border: '1px ' + tono.tratto + ' ' + tono.bordo,
      borderLeft: 'var(--contorno) solid ' + tono.bordo,
      borderRadius: 'var(--raggio-piccolo)',
      padding: '3px 8px'
    }
  }, /*#__PURE__*/React.createElement("strong", {
    style: {
      fontWeight: 'var(--peso-forte)',
      letterSpacing: '0.04em'
    }
  }, tono.parola), /*#__PURE__*/React.createElement("span", null, riga.replace(/^\[(KB|Esterna) · /, '').replace(/\]$/, ''))), glossa ? /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 'var(--t-minuto)',
      color: 'var(--testo-tenue)'
    }
  }, tono.glossa) : null);
}
Object.assign(__ds_scope, { EtichettaProvenienza });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/provenienza/EtichettaProvenienza.jsx", error: String((e && e.message) || e) }); }

// components/chat/MessaggioChat.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/* Un turno della chat CHIEDI. Ogni informazione dell'assistente porta la sua
   etichetta di provenienza sotto il testo, mai dentro la frase. */

/** Un messaggio della chat: dell'operatore o dell'assistente. */
function MessaggioChat({
  autore = 'assistente',
  testo,
  provenienza,
  azioni,
  style,
  children,
  ...resto
}) {
  const operatore = autore === 'operatore';
  return /*#__PURE__*/React.createElement("div", _extends({
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--s-2)',
      maxWidth: '42rem',
      alignSelf: operatore ? 'flex-end' : 'flex-start',
      background: operatore ? 'var(--superficie-incassata)' : 'var(--superficie)',
      border: 'var(--contorno) solid ' + (operatore ? 'var(--bordo-tenue)' : 'var(--bordo-tenue)'),
      borderLeft: operatore ? 'var(--contorno) solid var(--bordo-tenue)' : 'var(--filetto-forte) solid var(--mare)',
      borderRadius: 'var(--raggio)',
      padding: 'var(--s-4)',
      fontFamily: 'var(--font-corpo)',
      fontSize: 'var(--t-corpo)',
      lineHeight: 'var(--interlinea)',
      ...style
    }
  }, resto), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      fontSize: 'var(--t-minuto)',
      color: 'var(--testo-tenue)',
      fontWeight: 'var(--peso-medio)'
    }
  }, operatore ? 'Operatore' : 'Assistente della rete'), testo ? /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      whiteSpace: 'pre-line'
    }
  }, testo) : null, children, provenienza ? /*#__PURE__*/React.createElement(__ds_scope.EtichettaProvenienza, provenienza) : null, azioni ? /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 'var(--s-2)',
      marginTop: 'var(--s-1)'
    }
  }, azioni) : null);
}
Object.assign(__ds_scope, { MessaggioChat });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/chat/MessaggioChat.jsx", error: String((e && e.message) || e) }); }

// components/stato/AvvisoCoda.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/* La coda delle proposte: una presenza, non un allarme. Niente rosso, niente
   punto esclamativo, nessun imperativo (V6: il sistema osserva, l'umano decide). */

/** Quante proposte aspettano un umano, e da quanto. */
function AvvisoCoda({
  numero = 0,
  giorniPiuVecchia,
  casa,
  href,
  azione = 'Apri la coda delle proposte',
  style,
  ...resto
}) {
  const vuota = !numero;
  return /*#__PURE__*/React.createElement("div", _extends({
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      alignItems: 'baseline',
      gap: 'var(--s-2) var(--s-4)',
      background: 'var(--coda-sfondo)',
      border: 'var(--contorno) solid var(--bordo-tenue)',
      borderLeft: 'var(--filetto-forte) solid ' + (vuota ? 'var(--bordo-tenue)' : 'var(--coda-filetto)'),
      borderRadius: 'var(--raggio)',
      padding: 'var(--s-3) var(--s-4)',
      fontFamily: 'var(--font-corpo)',
      fontSize: 'var(--t-corpo)',
      lineHeight: 'var(--interlinea)',
      ...style
    }
  }, resto), /*#__PURE__*/React.createElement("span", {
    style: {
      color: vuota ? 'var(--testo-tenue)' : 'var(--testo)'
    }
  }, vuota ? /*#__PURE__*/React.createElement(React.Fragment, null, "Nessuna proposta in attesa", casa ? ' a ' + casa : '', ".") : /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement("strong", {
    style: {
      fontWeight: 'var(--peso-forte)',
      color: 'var(--coda-testo)'
    }
  }, numero), ' ', numero === 1 ? 'proposta aspetta' : 'proposte aspettano', " una decisione", casa ? ' a ' + casa : '', giorniPiuVecchia ? /*#__PURE__*/React.createElement("span", {
    style: {
      color: 'var(--testo-tenue)'
    }
  }, ' · la più vecchia da ' + giorniPiuVecchia + (giorniPiuVecchia === 1 ? ' giorno' : ' giorni')) : null)), href ? /*#__PURE__*/React.createElement("a", {
    href: href,
    style: {
      color: 'var(--azione)',
      fontWeight: 'var(--peso-medio)',
      textUnderlineOffset: '3px'
    }
  }, azione) : null);
}
Object.assign(__ds_scope, { AvvisoCoda });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/stato/AvvisoCoda.jsx", error: String((e && e.message) || e) }); }

// components/stato/RigaOggi.jsx
try { (() => {
function _extends() { return _extends = Object.assign ? Object.assign.bind() : function (n) { for (var e = 1; e < arguments.length; e++) { var t = arguments[e]; for (var r in t) ({}).hasOwnProperty.call(t, r) && (n[r] = t[r]); } return n; }, _extends.apply(null, arguments); }
/* La riga «Oggi» è l'unica cosa della Home che cambia da sola. Tre stati:
   attesa (lettura in corso), ok (il testo della vista v_oggi_casa),
   non-disponibile (lo shim non ha risposto entro 3 s — un'informazione, non un guasto). */

const stili = {
  attesa: {
    filetto: 'var(--bordo)',
    colore: 'var(--testo-tenue)'
  },
  ok: {
    filetto: 'var(--mare)',
    colore: 'var(--testo)'
  },
  'non-disponibile': {
    filetto: 'var(--attenzione-testo)',
    colore: 'var(--testo)'
  }
};

/** La riga «Oggi»: cosa bolle in pentola nella Casa scelta. */
function RigaOggi({
  stato = 'ok',
  testo,
  nota,
  style,
  ...resto
}) {
  const s = stili[stato] || stili.ok;
  return /*#__PURE__*/React.createElement("p", _extends({
    role: "status",
    "aria-live": "polite",
    "aria-busy": stato === 'attesa',
    style: {
      margin: 0,
      padding: 'var(--s-3) var(--s-4)',
      background: 'var(--superficie)',
      border: 'var(--contorno) solid var(--bordo-tenue)',
      borderLeft: 'var(--filetto-forte) solid ' + s.filetto,
      borderRadius: 'var(--raggio)',
      fontFamily: 'var(--font-corpo)',
      fontSize: 'var(--t-corpo-grande)',
      lineHeight: 'var(--interlinea)',
      color: s.colore,
      ...style
    }
  }, resto), /*#__PURE__*/React.createElement("span", {
    style: {
      fontWeight: 'var(--peso-forte)',
      letterSpacing: 'var(--spaziatura-destinazione)',
      textTransform: 'uppercase',
      fontSize: 'var(--t-minuto)',
      color: 'var(--testo-tenue)',
      marginRight: 'var(--s-2)'
    }
  }, "Oggi"), testo, nota ? /*#__PURE__*/React.createElement("span", {
    style: {
      display: 'block',
      marginTop: 'var(--s-1)',
      fontSize: 'var(--t-minuto)',
      color: 'var(--testo-tenue)'
    }
  }, nota) : null);
}
Object.assign(__ds_scope, { RigaOggi });
})(); } catch (e) { __ds_ns.__errors.push({ path: "components/stato/RigaOggi.jsx", error: String((e && e.message) || e) }); }

// ui_kits/trasi-chiedi/Chiedi.jsx
try { (() => {
const {
  Intestazione,
  SelettoreCasa,
  Bottone,
  MessaggioChat,
  CampoTesto,
  Scheda,
  Etichetta,
  EtichettaProvenienza
} = window.TrasiDesignSystem_18d101;
const CONVERSAZIONE = [{
  autore: 'operatore',
  testo: 'Dove può lavare i panni qui vicino?'
}, {
  testo: "Lavanderia sociale di Molo 12 — via Provinciale per San Vito 2.\nAperta lunedì-venerdì, 9:00-13:00. A circa 850 m dalla Casa San Bao.",
  provenienza: {
    testo: '[KB · Rete delle Case di Quartiere · agg. 15/09/2026 · affidabilità 2]'
  },
  azioni: 'biglietto'
}, {
  testo: "C'è anche una lavanderia a gettoni in via Bastioni Carlo V 12. Gli orari non sono disponibili.",
  provenienza: {
    tipo: 'esterna',
    fonte: 'OpenStreetMap contributors (ODbL)',
    ora: '11:42'
  }
}, {
  autore: 'operatore',
  testo: 'La lavanderia di via Bastioni ha chiuso, me l\'hanno detto ieri.'
}, {
  testo: "Ho creato una proposta di chiusura per quel luogo. Resta in attesa: la decisione è di una persona, non del sistema.",
  proposta: true
}];
function Turni({
  onProponi
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--s-4)'
    }
  }, CONVERSAZIONE.map((m, i) => /*#__PURE__*/React.createElement(MessaggioChat, {
    key: i,
    autore: m.autore,
    testo: m.testo,
    provenienza: m.provenienza,
    azioni: m.azioni === 'biglietto' ? /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(Bottone, {
      variante: "secondaria",
      dimensione: "compatta"
    }, "Stampa il biglietto"), /*#__PURE__*/React.createElement(Bottone, {
      variante: "quieta",
      dimensione: "compatta",
      onClick: onProponi
    }, "Segnala un cambiamento")) : null
  }, m.proposta ? /*#__PURE__*/React.createElement(Scheda, {
    filetto: "var(--coda-filetto)",
    padding: "var(--s-3)",
    style: {
      marginTop: 'var(--s-1)'
    }
  }, /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      fontSize: 'var(--t-minuto)',
      color: 'var(--testo-tenue)',
      fontFamily: 'var(--font-mono)'
    }
  }, "proposta \xB7 chiudi_luogo"), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: '4px 0 0'
    }
  }, "Lavanderia a gettoni, via Bastioni Carlo V 12 \u2014 segnalata come chiusa."), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: '4px 0 0',
      fontSize: 'var(--t-minuto)',
      color: 'var(--testo-tenue)'
    }
  }, "In attesa \xB7 chi decide: gestore della Casa \xB7 nessuna scadenza")) : null)));
}
function Chiedi() {
  const [testo, setTesto] = React.useState('');
  return /*#__PURE__*/React.createElement("div", {
    style: {
      minHeight: '100vh',
      display: 'flex',
      flexDirection: 'column',
      fontFamily: 'var(--font-corpo)',
      color: 'var(--testo)'
    }
  }, /*#__PURE__*/React.createElement(Intestazione, {
    logo: "../../assets/logo-case-di-quartiere-bianco.png",
    casa: /*#__PURE__*/React.createElement(SelettoreCasa, {
      valore: "san-bao",
      onChange: () => {}
    }),
    azioni: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(Bottone, {
      variante: "suScuro",
      dimensione: "compatta",
      href: "../trasi-home/index.html"
    }, "Torna a Trasi"), /*#__PURE__*/React.createElement(Bottone, {
      variante: "suScuro",
      dimensione: "compatta"
    }, "Esci"))
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      flex: 1,
      maxWidth: 'var(--misura-lettura)',
      width: '100%',
      margin: '0 auto',
      padding: 'var(--padding-pagina)',
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--s-5)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      alignItems: 'baseline',
      gap: 'var(--s-3)'
    }
  }, /*#__PURE__*/React.createElement("h1", {
    style: {
      margin: 0,
      fontSize: 'var(--t-titolo-m)',
      fontWeight: 'var(--peso-medio)'
    }
  }, "CHIEDI \u2014 assistente della rete"), /*#__PURE__*/React.createElement(Etichetta, {
    tono: "informativa"
  }, "San Bao"), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      fontSize: 'var(--t-minuto)',
      color: 'var(--testo-tenue)'
    }
  }, "Ogni risposta porta la sua etichetta di provenienza.")), /*#__PURE__*/React.createElement(Turni, {
    onProponi: () => {}
  }), /*#__PURE__*/React.createElement(Scheda, {
    padding: "var(--s-4)",
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--s-3)',
      position: 'sticky',
      bottom: 'var(--s-4)'
    }
  }, /*#__PURE__*/React.createElement(CampoTesto, {
    id: "domanda",
    etichetta: "La domanda della persona",
    righe: 2,
    segnaposto: "es. dove pu\xF2 fare la tessera sanitaria?",
    aiuto: "Senza nomi e senza dati personali: servono solo il bisogno e la zona.",
    valore: testo,
    onChange: e => setTesto(e.target.value)
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 'var(--s-2)',
      alignItems: 'center'
    }
  }, /*#__PURE__*/React.createElement(Bottone, {
    variante: "principale"
  }, "Chiedi"), /*#__PURE__*/React.createElement(Bottone, {
    variante: "quieta"
  }, "Segnala un cambiamento"), /*#__PURE__*/React.createElement("span", {
    style: {
      marginLeft: 'auto',
      fontSize: 'var(--t-minuto)',
      color: 'var(--testo-tenue)'
    }
  }, "La chat non conserva dati personali.")))));
}
Object.assign(window, {
  Chiedi
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/trasi-chiedi/Chiedi.jsx", error: String((e && e.message) || e) }); }

// ui_kits/trasi-home/Home.jsx
try { (() => {
const {
  SezioneAiuto
} = window;
const {
  Intestazione,
  SelettoreCasa,
  CASE,
  Bottone,
  Destinazione,
  RigaOggi,
  AvvisoCoda,
  Etichetta,
  SaltaContenuto
} = window.TrasiDesignSystem_18d101;

/* Dati finti ma realistici: la riga «Oggi» arriva dalla vista v_oggi_casa,
   la coda da v_proposte_aperte. */
const OGGI = {
  'san-bao': {
    testo: 'Oggi a San Bao: 2 eventi · 1 scheda in scadenza · 3 proposte',
    coda: 3,
    giorni: 4
  },
  bozzano: {
    testo: 'Oggi a Centro di Aggregazione Bozzano: 1 evento · 0 schede in scadenza · 1 proposta',
    coda: 1,
    giorni: 2
  },
  tuturano: {
    testo: 'Oggi a Tuturano: 0 eventi · 0 schede in scadenza · 0 proposte',
    coda: 0,
    giorni: 0
  }
};
const predefinito = {
  testo: null,
  coda: 2,
  giorni: 3
};
function nomeCasa(slug) {
  const c = CASE.find(x => x.slug === slug);
  return c ? c.nome : slug;
}
function datiOggi(slug) {
  const d = OGGI[slug];
  if (d) return d;
  return {
    ...predefinito,
    testo: 'Oggi a ' + nomeCasa(slug) + ': 1 evento · 2 schede in scadenza · 2 proposte'
  };
}
function Colonna({
  children,
  style
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--s-5)',
      ...style
    }
  }, children);
}
function Home({
  statoDati = 'ok'
}) {
  const [casa, setCasa] = React.useState('san-bao');
  const [aiutoAperto, setAiutoAperto] = React.useState(false);
  const dati = datiOggi(casa);
  const nome = nomeCasa(casa);
  const url = base => base.replace('{casa}', casa);
  return /*#__PURE__*/React.createElement("div", {
    style: {
      minHeight: '100%',
      background: 'var(--sfondo)',
      fontFamily: 'var(--font-corpo)',
      color: 'var(--testo)'
    }
  }, /*#__PURE__*/React.createElement(SaltaContenuto, {
    href: "#destinazioni"
  }), /*#__PURE__*/React.createElement(Intestazione, {
    logo: "../../assets/logo-case-di-quartiere-bianco.png",
    casa: /*#__PURE__*/React.createElement(SelettoreCasa, {
      valore: casa,
      onChange: e => setCasa(e.target.value)
    }),
    azioni: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(Bottone, {
      variante: "suScuro",
      dimensione: "compatta",
      onClick: () => setAiutoAperto(!aiutoAperto),
      "aria-expanded": aiutoAperto,
      "aria-controls": "aiuto"
    }, "Aiuto"), /*#__PURE__*/React.createElement(Bottone, {
      variante: "suScuro",
      dimensione: "compatta"
    }, "Esci"))
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: 'var(--misura-lettura)',
      margin: '0 auto',
      padding: 'var(--padding-pagina)',
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--s-6)'
    }
  }, /*#__PURE__*/React.createElement(Colonna, {
    style: {
      gap: 'var(--s-3)'
    }
  }, statoDati === 'ok' ? /*#__PURE__*/React.createElement(RigaOggi, {
    testo: dati.testo
  }) : statoDati === 'attesa' ? /*#__PURE__*/React.createElement(RigaOggi, {
    stato: "attesa",
    testo: "Lettura dei dati di oggi in corso\u2026"
  }) : /*#__PURE__*/React.createElement(RigaOggi, {
    stato: "non-disponibile",
    testo: "Dati non disponibili: la memoria della rete non risponde in questo momento.",
    nota: "\xC8 un'informazione, non un guasto: le destinazioni qui sotto funzionano."
  }), /*#__PURE__*/React.createElement(AvvisoCoda, {
    numero: statoDati === 'ok' ? dati.coda : 0,
    giorniPiuVecchia: dati.giorni,
    casa: nome,
    href: url('/nocodb/?casa={casa}&view=da-approvare')
  })), /*#__PURE__*/React.createElement("div", {
    id: "destinazioni",
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--s-5)'
    }
  }, /*#__PURE__*/React.createElement("h1", {
    style: {
      margin: 0,
      fontSize: 'var(--t-titolo-m)',
      fontWeight: 'var(--peso-medio)',
      color: 'var(--testo-tenue)'
    }
  }, "La porta della rete delle Case di Quartiere"), /*#__PURE__*/React.createElement(Destinazione, {
    variante: "principale",
    titolo: "CHIEDI",
    href: url('//onyx.lascuolaopensource.org/app?agentId=2&casa={casa}'),
    testo: "L'assistente della rete: risponde alla persona che hai davanti \u2014 dove andare, con quali orari \u2014 e dichiara da dove viene ogni informazione.",
    nota: 'si apre con ' + nome + ' già impostata'
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
      gap: 'var(--s-5)'
    }
  }, /*#__PURE__*/React.createElement(Destinazione, {
    titolo: "MAPPA",
    href: url('/metabase/dashboard/4?casa={casa}'),
    testo: "Dove sono i luoghi e le Case vicine, da guardare insieme alla persona."
  }), /*#__PURE__*/React.createElement(Destinazione, {
    titolo: "OSSERVATORIO",
    href: url('/metabase/dashboard/3?casa={casa}'),
    contatore: dati.coda ? dati.coda + (dati.coda === 1 ? ' proposta in attesa' : ' proposte in attesa') : null,
    testo: "I numeri della Casa e le proposte che aspettano una decisione."
  })), /*#__PURE__*/React.createElement(Destinazione, {
    titolo: "REGISTRA / AGGIORNA",
    attivo: false,
    testo: "Schede, eventi e opportunit\xE0 della Casa.",
    nota: "Fino all'attivazione, le correzioni passano dalle proposte in chat."
  }, /*#__PURE__*/React.createElement("span", {
    style: {
      marginTop: 'var(--s-2)'
    }
  }, /*#__PURE__*/React.createElement(Etichetta, {
    tono: "attenzione"
  }, "Servizio non ancora attivo")))), /*#__PURE__*/React.createElement(SezioneAiuto, {
    aperto: aiutoAperto,
    onToggle: () => setAiutoAperto(!aiutoAperto)
  }), /*#__PURE__*/React.createElement("footer", {
    style: {
      padding: 'var(--s-4) 0 var(--s-8)',
      color: 'var(--testo-tenue)',
      fontSize: 'var(--t-corpo)'
    }
  }, /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0
    }
  }, "Trasi \xB7 rete delle Case di Quartiere di Brindisi. Questa pagina non conserva dati personali: la Casa scelta resta nel browser."))));
}
Object.assign(window, {
  Home
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/trasi-home/Home.jsx", error: String((e && e.message) || e) }); }

// ui_kits/trasi-home/SezioneAiuto.jsx
try { (() => {
const {
  Scheda,
  EtichettaProvenienza
} = window.TrasiDesignSystem_18d101;
function Voce({
  titolo,
  children
}) {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: '2px'
    }
  }, /*#__PURE__*/React.createElement("h3", {
    style: {
      margin: 0,
      fontSize: 'var(--t-guida)',
      fontWeight: 'var(--peso-forte)',
      color: 'var(--azione)'
    }
  }, titolo), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      maxWidth: 'var(--misura-testo)'
    }
  }, children));
}

/** La sezione Aiuto: si legge in cinque minuti, in italiano semplice. */
function SezioneAiuto({
  aperto = false,
  onToggle
}) {
  return /*#__PURE__*/React.createElement(Scheda, {
    elemento: "section",
    id: "aiuto",
    padding: "var(--padding-scheda-grande)",
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--s-4)'
    }
  }, /*#__PURE__*/React.createElement("button", {
    type: "button",
    onClick: onToggle,
    "aria-expanded": aperto,
    style: {
      font: 'inherit',
      fontSize: 'var(--t-titolo-m)',
      fontWeight: 'var(--peso-medio)',
      color: 'var(--azione)',
      background: 'transparent',
      border: 0,
      padding: 0,
      textAlign: 'left',
      cursor: 'pointer',
      display: 'flex',
      alignItems: 'center',
      gap: 'var(--s-2)',
      minHeight: 'var(--bersaglio-min)'
    }
  }, "Aiuto", /*#__PURE__*/React.createElement("span", {
    style: {
      fontSize: 'var(--t-minuto)',
      color: 'var(--testo-tenue)',
      fontWeight: 'var(--peso-normale)'
    }
  }, aperto ? '(chiudi)' : '(cinque minuti di lettura)')), aperto ? /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--s-4)',
      lineHeight: 'var(--interlinea-larga)'
    }
  }, /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      maxWidth: 'var(--misura-testo)'
    }
  }, "Trasi \xE8 la porta della rete delle Case di Quartiere. Da qui si aprono quattro destinazioni, e ognuna si apre gi\xE0 sulla Casa scelta in alto."), /*#__PURE__*/React.createElement(Voce, {
    titolo: "CHIEDI"
  }, "La chat con l'assistente della rete. Si scrive la domanda della persona e l'assistente risponde con luogo, orari e fonte. Da l\xEC si pu\xF2 stampare un promemoria in formato A6, senza dati personali."), /*#__PURE__*/React.createElement(Voce, {
    titolo: "MAPPA"
  }, "I luoghi e le Case della rete su una mappa, da guardare insieme alla persona."), /*#__PURE__*/React.createElement(Voce, {
    titolo: "REGISTRA / AGGIORNA"
  }, "Il registro delle schede, degli eventi e delle opportunit\xE0 della Casa. Non \xE8 ancora attivo: fino all'attivazione le correzioni passano dalle proposte fatte in chat."), /*#__PURE__*/React.createElement(Voce, {
    titolo: "OSSERVATORIO"
  }, "I numeri della Casa e la coda delle proposte che aspettano una decisione. I conteggi troppo piccoli si leggono come \xAB<5\xBB: \xE8 una tutela della riservatezza delle persone."), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--s-3)'
    }
  }, /*#__PURE__*/React.createElement("h3", {
    style: {
      margin: 0,
      fontSize: 'var(--t-guida)',
      fontWeight: 'var(--peso-forte)',
      color: 'var(--azione)'
    }
  }, "Da dove viene l'informazione"), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      maxWidth: 'var(--misura-testo)'
    }
  }, "Ogni informazione porta un'etichetta. Ce ne sono due, e dicono cose diverse."), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--s-2)'
    }
  }, /*#__PURE__*/React.createElement(EtichettaProvenienza, {
    testo: "[KB \xB7 Rete delle Case di Quartiere \xB7 agg. 15/09/2026 \xB7 affidabilit\xE0 2]"
  }), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: '0 0 var(--s-2)',
      maxWidth: 'var(--misura-testo)'
    }
  }, "La rete lo sa: qualcuno della rete ha verificato questo dato. La data dice quando, il numero da 1 a 3 dice quanto \xE8 solida la fonte."), /*#__PURE__*/React.createElement(EtichettaProvenienza, {
    tipo: "esterna",
    fonte: "OpenStreetMap contributors (ODbL)",
    ora: "02:21"
  }), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      maxWidth: 'var(--misura-testo)'
    }
  }, "Trovato fuori: viene da una fonte esterna e nessuno della rete l'ha controllato. Si pu\xF2 usare, dicendo alla persona che non \xE8 verificato \u2014 meglio una telefonata prima di mandarla l\xEC."))), /*#__PURE__*/React.createElement(Voce, {
    titolo: "Le proposte"
  }, "Trasi non cambia la memoria della rete da sola. Se in chat si segnala che un bar ha chiuso o che un orario \xE8 cambiato, nasce una proposta: resta in attesa finch\xE9 una persona la approva. La riga in alto dice quante ne aspettano una decisione e da quanto tempo. Non c'\xE8 una scadenza da rispettare."), /*#__PURE__*/React.createElement(Voce, {
    titolo: "La riga \xABOggi\xBB"
  }, "\xC8 una lettura della memoria della rete per la Casa scelta: eventi, schede in scadenza, proposte. Se il servizio dati non risponde entro tre secondi, la riga dice \xABdati non disponibili\xBB: \xE8 un'informazione, non un guasto, e le quattro destinazioni funzionano comunque."), /*#__PURE__*/React.createElement(Voce, {
    titolo: "La Casa in alto"
  }, "Il selettore ricorda la Casa nel browser: al prossimo accesso \xE8 gi\xE0 quella. L'unica cosa conservata \xE8 il nome breve della Casa, nessun dato personale. Tuturano porta la nota \xABdati provvisori\xBB: alcune sue schede non sono ancora complete."), /*#__PURE__*/React.createElement(Voce, {
    titolo: "Tastiera"
  }, "Si pu\xF2 usare tutto da tastiera: il tasto Tab passa dal salto alle destinazioni, al selettore della Casa, ad Aiuto ed Esci, poi a CHIEDI, MAPPA, OSSERVATORIO e alla coda delle proposte. Il riquadro giallo indica sempre dove sei.")) : null);
}
Object.assign(window, {
  SezioneAiuto
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/trasi-home/SezioneAiuto.jsx", error: String((e && e.message) || e) }); }

// ui_kits/trasi-mappa/Mappa.jsx
try { (() => {
const {
  Intestazione,
  SelettoreCasa,
  Bottone,
  Scheda,
  Tabella,
  Etichetta,
  EtichettaProvenienza
} = window.TrasiDesignSystem_18d101;

/* Le 10 Case con le coordinate reali non sono in questo progetto: la mappa vera è
   la dashboard Metabase «Mappa» (id 4) che disegna i pin da v_mappa_case. Qui non
   si inventa una cartografia: si mostra la cornice Trasi e l'elenco dei luoghi con
   la loro provenienza, che è la parte che il design system possiede. */

function Mappa() {
  return /*#__PURE__*/React.createElement("div", {
    style: {
      minHeight: '100vh',
      fontFamily: 'var(--font-corpo)',
      color: 'var(--testo)'
    }
  }, /*#__PURE__*/React.createElement(Intestazione, {
    logo: "../../assets/logo-case-di-quartiere-bianco.png",
    casa: /*#__PURE__*/React.createElement(SelettoreCasa, {
      valore: "san-bao",
      onChange: () => {}
    }),
    azioni: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(Bottone, {
      variante: "suScuro",
      dimensione: "compatta",
      href: "../trasi-home/index.html"
    }, "Torna a Trasi"), /*#__PURE__*/React.createElement(Bottone, {
      variante: "suScuro",
      dimensione: "compatta"
    }, "Esci"))
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: 'var(--misura-lettura)',
      margin: '0 auto',
      padding: 'var(--padding-pagina)',
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--s-5)'
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h1", {
    style: {
      margin: 0,
      fontSize: 'var(--t-titolo-m)',
      fontWeight: 'var(--peso-medio)'
    }
  }, "MAPPA \u2014 intorno a San Bao"), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: '4px 0 0',
      color: 'var(--testo-tenue)'
    }
  }, "I luoghi entro 1,5 km, da guardare insieme alla persona.")), /*#__PURE__*/React.createElement(Scheda, {
    padding: "var(--s-6)",
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--s-2)',
      alignItems: 'center',
      textAlign: 'center',
      background: 'var(--superficie-incassata)'
    }
  }, /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      fontWeight: 'var(--peso-medio)'
    }
  }, "Qui sta la mappa"), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      maxWidth: '36rem',
      color: 'var(--testo-tenue)'
    }
  }, "La mappa \xE8 la dashboard Metabase \xABMappa\xBB: disegna i pin delle Case e dei luoghi dalle viste", /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-mono)',
      fontSize: 'var(--t-minuto)'
    }
  }, " v_mappa_case"), " e", /*#__PURE__*/React.createElement("span", {
    style: {
      fontFamily: 'var(--font-mono)',
      fontSize: 'var(--t-minuto)'
    }
  }, " v_mappa_luoghi"), ". Il raggio di vicinanza non \xE8 un cerchio disegnato: \xE8 una nota nel dettaglio del pin."), /*#__PURE__*/React.createElement(Etichetta, {
    tono: "neutra"
  }, "contenuto reso da Metabase \u2014 non ridisegnato qui")), /*#__PURE__*/React.createElement("section", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--s-3)'
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      margin: 0,
      fontSize: 'var(--t-titolo-s)',
      fontWeight: 'var(--peso-forte)',
      color: 'var(--azione)',
      letterSpacing: 'var(--spaziatura-destinazione)'
    }
  }, "LUOGHI VICINI"), /*#__PURE__*/React.createElement(Tabella, {
    colonne: ['Luogo', 'Distanza', 'Orari', 'Provenienza'],
    righe: [['Lavanderia sociale Molo 12', '850 m', 'lun-ven 9:00-13:00', /*#__PURE__*/React.createElement(EtichettaProvenienza, {
      testo: "[KB \xB7 Rete delle Case di Quartiere \xB7 agg. 15/09/2026 \xB7 affidabilit\xE0 2]",
      glossa: false
    })], ['Sportello CAF, via Nazario Sauro', '1,2 km', 'mar e gio 9:00-12:00', /*#__PURE__*/React.createElement(EtichettaProvenienza, {
      tipo: "kb",
      fonte: "Comune di Brindisi",
      data: "09/09/2026",
      affidabilita: 3,
      glossa: false
    })], ['Lavanderia a gettoni, via Bastioni Carlo V', '1,4 km', 'orari non disponibili', /*#__PURE__*/React.createElement(EtichettaProvenienza, {
      tipo: "esterna",
      fonte: "OpenStreetMap contributors (ODbL)",
      ora: "11:42",
      glossa: false
    })]]
  }), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      fontSize: 'var(--t-minuto)',
      color: 'var(--testo-tenue)'
    }
  }, "\xABOrari non disponibili\xBB non \xE8 un errore: a Brindisi solo una piccola parte dei luoghi esterni dichiara gli orari, e un luogo senza orari resta utile.")), /*#__PURE__*/React.createElement("section", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--s-3)'
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      margin: 0,
      fontSize: 'var(--t-titolo-s)',
      fontWeight: 'var(--peso-forte)',
      color: 'var(--azione)',
      letterSpacing: 'var(--spaziatura-destinazione)'
    }
  }, "CASE VICINE"), /*#__PURE__*/React.createElement(Tabella, {
    densita: "compatta",
    colonne: ['Casa', 'Distanza', 'Nota'],
    righe: [['Molo 12', '850 m', ''], ['Minimus', '1,9 km', ''], ['Tuturano', '12 km', /*#__PURE__*/React.createElement(Etichetta, {
      tono: "neutra"
    }, "dati provvisori")]]
  }))));
}
Object.assign(window, {
  Mappa
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/trasi-mappa/Mappa.jsx", error: String((e && e.message) || e) }); }

// ui_kits/trasi-osservatorio/Osservatorio.jsx
try { (() => {
const {
  Intestazione,
  SelettoreCasa,
  Bottone,
  Scheda,
  Tabella,
  AvvisoCoda,
  Etichetta,
  EtichettaProvenienza,
  RigaOggi
} = window.TrasiDesignSystem_18d101;
function Numero({
  etichetta,
  valore,
  nota
}) {
  return /*#__PURE__*/React.createElement(Scheda, {
    style: {
      flex: '1 1 160px'
    }
  }, /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      fontSize: 'var(--t-minuto)',
      color: 'var(--testo-tenue)'
    }
  }, etichetta), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: '2px 0 0',
      fontSize: 'var(--t-titolo-l)',
      fontWeight: 'var(--peso-forte)',
      color: 'var(--azione)',
      lineHeight: 'var(--interlinea-stretta)'
    }
  }, valore), nota ? /*#__PURE__*/React.createElement("p", {
    style: {
      margin: '2px 0 0',
      fontSize: 'var(--t-minuto)',
      color: 'var(--testo-tenue)'
    }
  }, nota) : null);
}
function Osservatorio() {
  const [decise, setDecise] = React.useState({});
  const proposte = [{
    id: 1,
    tipo: 'modifica_luogo',
    voce: 'Bar interno · orari',
    giorni: 4,
    chi: 'Gestore della Casa',
    motivo: 'orario serale cambiato da settembre'
  }, {
    id: 2,
    tipo: 'chiudi_luogo',
    voce: 'Lavanderia a gettoni, via Bastioni Carlo V 12',
    giorni: 2,
    chi: 'Gestore della Casa',
    motivo: 'segnalata come chiusa allo sportello'
  }, {
    id: 3,
    tipo: 'promuovi_esterno',
    voce: 'Sportello CAF, via Nazario Sauro 8',
    giorni: 1,
    chi: 'AT di rete',
    motivo: 'trovata su OpenStreetMap, da verificare'
  }];
  const aperte = proposte.filter(p => !decise[p.id]);
  return /*#__PURE__*/React.createElement("div", {
    style: {
      minHeight: '100vh',
      fontFamily: 'var(--font-corpo)',
      color: 'var(--testo)'
    }
  }, /*#__PURE__*/React.createElement(Intestazione, {
    logo: "../../assets/logo-case-di-quartiere-bianco.png",
    casa: /*#__PURE__*/React.createElement(SelettoreCasa, {
      valore: "san-bao",
      onChange: () => {}
    }),
    azioni: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(Bottone, {
      variante: "suScuro",
      dimensione: "compatta",
      href: "../trasi-home/index.html"
    }, "Torna a Trasi"), /*#__PURE__*/React.createElement(Bottone, {
      variante: "suScuro",
      dimensione: "compatta"
    }, "Esci"))
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: 'var(--misura-lettura)',
      margin: '0 auto',
      padding: 'var(--padding-pagina)',
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--s-6)'
    }
  }, /*#__PURE__*/React.createElement("div", null, /*#__PURE__*/React.createElement("h1", {
    style: {
      margin: 0,
      fontSize: 'var(--t-titolo-m)',
      fontWeight: 'var(--peso-medio)'
    }
  }, "OSSERVATORIO \u2014 San Bao"), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: '4px 0 0',
      color: 'var(--testo-tenue)'
    }
  }, "Come sta andando la Casa, e cosa aspetta una decisione. Ultimi 30 giorni.")), /*#__PURE__*/React.createElement(RigaOggi, {
    testo: "Oggi a San Bao: 2 eventi \xB7 1 scheda in scadenza \xB7 3 proposte"
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 'var(--s-4)'
    }
  }, /*#__PURE__*/React.createElement(Numero, {
    etichetta: "Richieste registrate",
    valore: "18",
    nota: "ultimi 30 giorni"
  }), /*#__PURE__*/React.createElement(Numero, {
    etichetta: "Schede in scadenza",
    valore: "1",
    nota: "entro 30 giorni"
  }), /*#__PURE__*/React.createElement(Numero, {
    etichetta: "Schede scadute",
    valore: "0"
  }), /*#__PURE__*/React.createElement(Numero, {
    etichetta: "Richieste senza risposta",
    valore: "<5",
    nota: "sotto la soglia di riservatezza"
  })), /*#__PURE__*/React.createElement("section", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--s-3)'
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      margin: 0,
      fontSize: 'var(--t-titolo-s)',
      fontWeight: 'var(--peso-forte)',
      color: 'var(--azione)',
      letterSpacing: 'var(--spaziatura-destinazione)'
    }
  }, "PROPOSTE IN ATTESA"), /*#__PURE__*/React.createElement(AvvisoCoda, {
    numero: aperte.length,
    giorniPiuVecchia: aperte.length ? Math.max(...aperte.map(p => p.giorni)) : undefined,
    casa: "San Bao"
  }), aperte.map(p => /*#__PURE__*/React.createElement(Scheda, {
    key: p.id,
    filetto: "var(--coda-filetto)",
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 'var(--s-3)',
      justifyContent: 'space-between',
      alignItems: 'flex-start'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      minWidth: 0,
      flex: '1 1 320px'
    }
  }, /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      fontSize: 'var(--t-minuto)',
      color: 'var(--testo-tenue)',
      fontFamily: 'var(--font-mono)'
    }
  }, p.tipo), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: '2px 0 0',
      fontWeight: 'var(--peso-medio)'
    }
  }, p.voce), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: '2px 0 0',
      color: 'var(--testo-tenue)'
    }
  }, p.motivo), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: '6px 0 0',
      fontSize: 'var(--t-minuto)',
      color: 'var(--testo-tenue)'
    }
  }, "in attesa da ", p.giorni, " ", p.giorni === 1 ? 'giorno' : 'giorni', " \xB7 chi decide: ", p.chi, " \xB7 nessuna scadenza")), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      gap: 'var(--s-2)',
      flexWrap: 'wrap'
    }
  }, /*#__PURE__*/React.createElement(Bottone, {
    variante: "secondaria",
    dimensione: "compatta",
    onClick: () => setDecise({
      ...decise,
      [p.id]: 'approvata'
    })
  }, "Approva"), /*#__PURE__*/React.createElement(Bottone, {
    variante: "quieta",
    dimensione: "compatta",
    onClick: () => setDecise({
      ...decise,
      [p.id]: 'rifiutata'
    })
  }, "Rifiuta")))), Object.keys(decise).length ? /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      fontSize: 'var(--t-minuto)',
      color: 'var(--testo-tenue)'
    }
  }, "Le proposte decise vengono applicate dal flusso notturno alle 05:00, con una riga di audit.") : null), /*#__PURE__*/React.createElement("section", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--s-3)'
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      margin: 0,
      fontSize: 'var(--t-titolo-s)',
      fontWeight: 'var(--peso-forte)',
      color: 'var(--azione)',
      letterSpacing: 'var(--spaziatura-destinazione)'
    }
  }, "SCHEDE DELLA CASA"), /*#__PURE__*/React.createElement(Tabella, {
    colonne: ['Scheda', 'Aggiornata', 'Provenienza', 'Stato'],
    righe: [['Sportello di ascolto', '15/09/2026', /*#__PURE__*/React.createElement(EtichettaProvenienza, {
      testo: "[KB \xB7 Rete delle Case di Quartiere \xB7 agg. 15/09/2026 \xB7 affidabilit\xE0 2]",
      glossa: false
    }), 'in corso'], ['Doposcuola', '02/08/2026', /*#__PURE__*/React.createElement(EtichettaProvenienza, {
      tipo: "kb",
      fonte: "Casa San Bao",
      data: "02/08/2026",
      affidabilita: 2,
      glossa: false
    }), /*#__PURE__*/React.createElement(Etichetta, {
      tono: "attenzione"
    }, "in scadenza")], ['Lavanderia sociale', '15/09/2026', /*#__PURE__*/React.createElement(EtichettaProvenienza, {
      tipo: "kb",
      fonte: "Rete-kb-3",
      data: "15/09/2026",
      affidabilita: 3,
      glossa: false
    }), 'in corso']]
  }), /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0,
      fontSize: 'var(--t-minuto)',
      color: 'var(--testo-tenue)'
    }
  }, "I conteggi sotto la soglia di riservatezza si leggono \xAB<5\xBB: mai il numero grezzo."))));
}
Object.assign(window, {
  Osservatorio
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/trasi-osservatorio/Osservatorio.jsx", error: String((e && e.message) || e) }); }

// ui_kits/trasi-registra/Registra.jsx
try { (() => {
const {
  Intestazione,
  SelettoreCasa,
  Bottone,
  Scheda,
  Tabella,
  Etichetta,
  CampoTesto,
  EtichettaProvenienza
} = window.TrasiDesignSystem_18d101;
function Registra() {
  const [modulo, setModulo] = React.useState(false);
  return /*#__PURE__*/React.createElement("div", {
    style: {
      minHeight: '100vh',
      fontFamily: 'var(--font-corpo)',
      color: 'var(--testo)'
    }
  }, /*#__PURE__*/React.createElement(Intestazione, {
    logo: "../../assets/logo-case-di-quartiere-bianco.png",
    casa: /*#__PURE__*/React.createElement(SelettoreCasa, {
      valore: "san-bao",
      onChange: () => {}
    }),
    azioni: /*#__PURE__*/React.createElement(React.Fragment, null, /*#__PURE__*/React.createElement(Bottone, {
      variante: "suScuro",
      dimensione: "compatta",
      href: "../trasi-home/index.html"
    }, "Torna a Trasi"), /*#__PURE__*/React.createElement(Bottone, {
      variante: "suScuro",
      dimensione: "compatta"
    }, "Esci"))
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      maxWidth: 'var(--misura-lettura)',
      margin: '0 auto',
      padding: 'var(--padding-pagina)',
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--s-5)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 'var(--s-3)',
      alignItems: 'baseline'
    }
  }, /*#__PURE__*/React.createElement("h1", {
    style: {
      margin: 0,
      fontSize: 'var(--t-titolo-m)',
      fontWeight: 'var(--peso-medio)'
    }
  }, "REGISTRA / AGGIORNA \u2014 San Bao"), /*#__PURE__*/React.createElement(Etichetta, {
    tono: "attenzione"
  }, "Servizio non ancora attivo")), /*#__PURE__*/React.createElement(Scheda, {
    filetto: "var(--attenzione-testo)"
  }, /*#__PURE__*/React.createElement("p", {
    style: {
      margin: 0
    }
  }, "Il registro \xE8 predisposto: il collegamento porta gi\xE0 alla vista della Casa. Fino all'attivazione, le correzioni passano dalle proposte fatte in chat e dalla coda in OSSERVATORIO.")), /*#__PURE__*/React.createElement("section", {
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--s-3)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 'var(--s-2)',
      justifyContent: 'space-between',
      alignItems: 'center'
    }
  }, /*#__PURE__*/React.createElement("h2", {
    style: {
      margin: 0,
      fontSize: 'var(--t-titolo-s)',
      fontWeight: 'var(--peso-forte)',
      color: 'var(--azione)',
      letterSpacing: 'var(--spaziatura-destinazione)'
    }
  }, "SCHEDE E EVENTI"), /*#__PURE__*/React.createElement(Bottone, {
    variante: "secondaria",
    dimensione: "compatta",
    onClick: () => setModulo(!modulo)
  }, modulo ? 'Chiudi il modulo' : 'Aggiungi una voce')), modulo ? /*#__PURE__*/React.createElement(Scheda, {
    padding: "var(--padding-scheda-grande)",
    style: {
      display: 'flex',
      flexDirection: 'column',
      gap: 'var(--s-4)'
    }
  }, /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'grid',
      gridTemplateColumns: 'repeat(2, minmax(0, 1fr))',
      gap: 'var(--s-4)'
    }
  }, /*#__PURE__*/React.createElement(CampoTesto, {
    id: "voce",
    etichetta: "Nome della voce",
    segnaposto: "es. Doposcuola"
  }), /*#__PURE__*/React.createElement(CampoTesto, {
    id: "quando",
    etichetta: "Quando",
    segnaposto: "es. luned\xEC e mercoled\xEC, 15:00-18:00"
  }), /*#__PURE__*/React.createElement(CampoTesto, {
    id: "dove",
    etichetta: "Dove",
    segnaposto: "via Nazario Sauro 8"
  }), /*#__PURE__*/React.createElement(CampoTesto, {
    id: "fonte",
    etichetta: "Da dove viene l'informazione",
    aiuto: "Chi l'ha detto o quale documento lo dice."
  })), /*#__PURE__*/React.createElement(CampoTesto, {
    id: "nota",
    etichetta: "Nota per chi decide",
    righe: 2,
    aiuto: "Massimo 80 caratteri, senza dati personali."
  }), /*#__PURE__*/React.createElement("div", {
    style: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: 'var(--s-2)',
      alignItems: 'center'
    }
  }, /*#__PURE__*/React.createElement(Bottone, {
    variante: "principale"
  }, "Invia come proposta"), /*#__PURE__*/React.createElement(Bottone, {
    variante: "quieta",
    onClick: () => setModulo(false)
  }, "Annulla"), /*#__PURE__*/React.createElement("span", {
    style: {
      marginLeft: 'auto',
      fontSize: 'var(--t-minuto)',
      color: 'var(--testo-tenue)'
    }
  }, "Niente viene scritto subito: la voce resta in attesa di una decisione."))) : null, /*#__PURE__*/React.createElement(Tabella, {
    colonne: ['Voce', 'Tipo', 'Quando', 'Aggiornata', 'Provenienza'],
    righe: [['Sportello di ascolto', 'scheda', 'martedì, 10:00-13:00', '15/09/2026', /*#__PURE__*/React.createElement(EtichettaProvenienza, {
      tipo: "kb",
      fonte: "Casa San Bao",
      data: "15/09/2026",
      affidabilita: 2,
      glossa: false
    })], ['Doposcuola', 'scheda', 'lunedì e mercoledì, 15:00-18:00', '02/08/2026', /*#__PURE__*/React.createElement(EtichettaProvenienza, {
      tipo: "kb",
      fonte: "Casa San Bao",
      data: "02/08/2026",
      affidabilita: 2,
      glossa: false
    })], ['Laboratorio di cucito', 'evento', '24/09/2026, 17:00', '14/09/2026', /*#__PURE__*/React.createElement(EtichettaProvenienza, {
      tipo: "kb",
      fonte: "Calendario della Casa (iCal)",
      data: "14/09/2026",
      affidabilita: 2,
      glossa: false
    })], ['Borsa lavoro giovani', 'opportunità', 'domande entro il 30/09/2026', '09/09/2026', /*#__PURE__*/React.createElement(EtichettaProvenienza, {
      tipo: "kb",
      fonte: "Comune di Brindisi",
      data: "09/09/2026",
      affidabilita: 3,
      glossa: false
    })]]
  }))));
}
Object.assign(window, {
  Registra
});
})(); } catch (e) { __ds_ns.__errors.push({ path: "ui_kits/trasi-registra/Registra.jsx", error: String((e && e.message) || e) }); }

__ds_ns.Bottone = __ds_scope.Bottone;

__ds_ns.CampoTesto = __ds_scope.CampoTesto;

__ds_ns.Etichetta = __ds_scope.Etichetta;

__ds_ns.Scheda = __ds_scope.Scheda;

__ds_ns.MessaggioChat = __ds_scope.MessaggioChat;

__ds_ns.Tabella = __ds_scope.Tabella;

__ds_ns.Destinazione = __ds_scope.Destinazione;

__ds_ns.Intestazione = __ds_scope.Intestazione;

__ds_ns.SaltaContenuto = __ds_scope.SaltaContenuto;

__ds_ns.CASE = __ds_scope.CASE;

__ds_ns.SelettoreCasa = __ds_scope.SelettoreCasa;

__ds_ns.EtichettaProvenienza = __ds_scope.EtichettaProvenienza;

__ds_ns.AvvisoCoda = __ds_scope.AvvisoCoda;

__ds_ns.RigaOggi = __ds_scope.RigaOggi;

})();
