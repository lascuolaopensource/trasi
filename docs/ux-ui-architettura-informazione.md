# Architettura dell'informazione — Trasi (revisione 2026-09-17)

Per ogni schermata: chi la usa, con quale frequenza, quali contenuti, quale gerarchia.
Le decisioni qui sono vincolanti per l'implementazione.

## Home (`index.html`) — la porta

**Chi**: l'operatore allo sportello, con la persona davanti, su tablet o PC di Casa.
Decine di accessi al giorno; ogni accesso dura pochi secondi.

**Contenuti**: marchio e nome della rete; selettore della Casa (persistente); la riga
«Oggi» con eventi e coda delle proposte; quattro destinazioni; Aiuto; nota di privacy.

**Gerarchia** (dalla frequenza d'uso reale, non dalla simmetria):

1. **Testata**: marchio + Casa di riferimento + Aiuto/Esci. La Casa è un *fatto*
   dell'operazione, va sempre visibile.
2. **Stato di oggi** (prima delle destinazioni): la riga «Oggi» (con la lista degli
   eventi del giorno) e la coda delle proposte. Sono le uniche cose che cambiano da
   sole e si legano alla Casa scelta. Non sono allarmi: il filetto di sinistra dice
   lo stato, la parola dice il resto.
3. **Destinazioni**: CHIEDI grande e prima (azione primaria, si usa decine di volte
   al giorno); MAPPA e OSSERVATORIO in coppia sotto (uso quotidiano ma breve);
   REGISTRA / AGGIORNA sotto, spento e dichiarato (uso raro, servizio inattivo).
   La gerarchia si legge dalla dimensione e dalla posizione, non dal colore.
4. **Aiuto** in fondo, ripiegabile in una `<details>`; resta raggiungibile anche con
   `#aiuto` e dalla testata.
5. **Piede**: la nota sulla privacy.

**Frequenza → forma**: CHIEDI occupa una riga intera su desktop e sta in cima;
MAPPA/OSSERVATORIO due colonne di larghezza media; REGISTRA una riga bassa. Su
schermi stretti (≤ 40rem) tutto diventa una colonna nell'ordine d'uso.

**Stati progettati** per «Oggi»: attesa (skeleton della riga), dati (testo dello shim +
lista eventi), non disponibili (frase + nota «è un'informazione, non un guasto»), coda
vuota (parola, non numero), Casa provvisoria (nota sotto il selettore).

## Area operatore (`operatore.html`) — app shell alla Onyx

**Chi**: l'operatore in sessione; accesso una volta, poi lavoro continuato.
Chat decine di volte al giorno; richiesta una o due volte per colloquio; attrezzoteca
e messaggi quando capita.

**Struttura** (pattern `SettingsLayouts` di Onyx adattato):

- **Testata sticky** con marchio, Casa della sessione, Home/Aiuto/Esci. Ombra di
  scroll quando il contenuto scorre (gradiente `mask-02`, come l'header di Onyx).
- **Navigazione funzioni**: sidebar a sinistra ≥ 1180px (larghezza `15rem`, come la
  sidebar di Onyx); sotto, linguette orizzontali. Le quattro funzioni: Chiedi,
  Registra richiesta, Attrezzoteca, Messaggi interni.
- **Contenuto** in contenitore `lg` (62rem) — è un banco di lavoro, non una pagina di
  lettura; la chat occupa l'altezza disponibile, il compositore sta in fondo come in
  Onyx.
- **Pannello attivo nell'URL** (`?pannello=chat`): indietro/avanti e refresh
  restano sulla funzione giusta; il focus va al titolo del pannello.

**Stati progettati**: accesso (errore leggibile, mai dettagli tecnici), sessione
scaduta (ritorno all'accesso con messaggio), chat in attesa (riga shimmer
«l'assistente sta rispondendo» — la risposta può tardare fino a 120s, il
compositore resta usabile), fonte citata sotto ogni risposta (`risposta` + `fonte`
di `POST /op/chat`), inventario in caricamento (skeleton righe), ricerca senza
esiti (stato vuoto), prestito da proporre (dialog, non `prompt()`), messaggio
inviato (conferma inline).

## Cosa non cambia

- I contratti con lo shim: stessi endpoint, stessi campi, stesso timeout di 3s,
  cookie di sessione, slug della Casa unico dato in `localStorage`.
- L'ordine di tabulazione essenziale: salto → testata → stato → destinazioni.
- Le parole: mai imperativi verso le persone; i quattro nomi in maiuscolo.

## Wireframe (HTML, tre breakpoint)

`/tmp/wireframe/wireframe.html` — Home e area operatore a 1440, 820, 390px,
con gli stati principali. Non resta nel repository: il risultato verificato è
l'implementazione.