# Trasi Home — architettura dell'informazione e veste UX/UI

Documento di progetto, non di implementazione. Risponde ai sei punti chiesti dal lead engineer.
Il codice attuale letto come sorgente: `deployment/home/{index.html,style.css,home.js}`,
`shim/app/badge.py`, `shim/app/testi.py`, `.specs/B5-dash.md`, `.specs/B6-home-ops.md`
(repository `lascuolaopensource/trasi`, ramo `main`).

---

## 1. Architettura dell'informazione: cosa cambierei

**La struttura è giusta; la gerarchia no.** Le quattro destinazioni sono le quattro giuste, e la Home
fa bene a essere una porta e non un cruscotto. Il problema è che quattro riquadri uguali in griglia
2×2 dicono una cosa falsa: che le quattro attività hanno la stessa frequenza. Il lavoro reale è
diverso, e l'ordine che propongo è quello del lavoro:

| | Frequenza reale | Peso visivo proposto |
|---|---|---|
| CHIEDI | decine di volte al giorno, con una persona davanti | destinazione principale, tutta la larghezza, titolo a 36 px |
| OSSERVATORIO | ogni giorno o ogni settimana, ma **per le proposte** | secondaria, con il conteggio della coda sul riquadro |
| MAPPA | qualche volta al giorno, dentro un colloquio | secondaria |
| REGISTRA / AGGIORNA | quando capita, e oggi **non è attivo** | terzo livello, riquadro basso, stato dichiarato |

Tre argomenti, non una preferenza estetica:

1. **Una porta con quattro maniglie identiche costringe a leggere ogni volta.** Con turnover alto e
   alfabetizzazione variabile, l'operatore nuovo legge quattro titoli e quattro descrizioni prima di
   capire dov'è la cosa che gli serve nel 90% dei casi. Una destinazione grande sola si riconosce
   dalla forma, non dal testo: al secondo giorno la mano va da sola.
2. **REGISTRA/AGGIORNA oggi non funziona.** Un riquadro non attivo che occupa un quarto della pagina
   principale insegna che il sistema promette cose che non fa. Scenda di livello, con l'etichetta
   «Servizio non ancora attivo» e la frase che dice cosa fare intanto (le proposte in chat).
3. **OSSERVATORIO è due cose in una.** «Guardare i numeri» è un'attività settimanale da scrivania;
   «decidere sulle proposte» è un'attività quotidiana, breve, che qualcuno aspetta. Tenerle nello
   stesso riquadro fa sì che la seconda si veda solo se si entra. Vedi il punto 4.

**Cosa NON cambierei nella struttura**: il numero delle destinazioni (quattro, non cinque: la coda
delle proposte non è un servizio diverso, è una vista di OSSERVATORIO), la scelta di aprire i servizi
esterni con la Casa già impostata, e il fatto che la Home non abbia un login proprio.

---

## 2. Il layout

```
┌──────────────────────────────────────────────────────────────────────┐
│ ▮logo  TRASI                        Casa di riferimento              │ testata
│        Rete delle Case di Quartiere  [ San Bao            ▾ ]        │ blu notte
│                                       [Aiuto] [Esci]                 │ #06405A
├──────────────────────────────────────────────────────────────────────┤
│ ▌OGGI  Oggi a San Bao: 2 eventi · 1 scheda in scadenza · 3 proposte │ fascia
│ ▌3 proposte aspettano una decisione a San Bao · la più vecchia da 4  │ di stato
│   giorni                              Apri la coda delle proposte    │
│                                                                      │
│ La porta della rete delle Case di Quartiere                          │
│ ┌──────────────────────────────────────────────────────────────────┐ │
│ │ CHIEDI                                                           │ │ 36 px
│ │ L'assistente della rete: risponde alla persona che hai davanti — │ │
│ │ dove andare, con quali orari — e dichiara da dove viene ogni     │ │
│ │ informazione.                                                    │ │
│ │ si apre con San Bao già impostata                                │ │
│ └──────────────────────────────────────────────────────────────────┘ │
│ ┌───────────────────────────────┐ ┌──────────────────────────────────┐│
│ │ MAPPA                         │ │ OSSERVATORIO   3 proposte in att.││ 20 px
│ │ Dove sono i luoghi e le Case  │ │ I numeri della Casa e le         ││
│ │ vicine.                       │ │ proposte che aspettano.          ││
│ └───────────────────────────────┘ └──────────────────────────────────┘│
│ ┌──────────────────────────────────────────────────────────────────┐ │
│ │ REGISTRA / AGGIORNA        [Servizio non ancora attivo]          │ │ grigio
│ └──────────────────────────────────────────────────────────────────┘ │
│                                                                      │
│ ▸ Aiuto (cinque minuti di lettura)                                   │
│ Trasi · non conserva dati personali: la Casa scelta resta nel browser│
└──────────────────────────────────────────────────────────────────────┘
```

**Stati.**
- *Attesa* (fino a 3 s): «Lettura dei dati di oggi in corso…», filetto grigio, `aria-busy="true"`.
- *Dati non disponibili*: filetto giallo sole (non rosso), il testo attuale + una seconda riga piccola:
  «È un'informazione, non un guasto: le destinazioni qui sotto funzionano.» Le destinazioni restano
  tutte attive: non dipendono da quella lettura.
- *Coda vuota*: la riga resta, il filetto si spegne, il testo diventa grigio: «Nessuna proposta in
  attesa a San Bao.» Una coda vuota è un'informazione, non uno spazio da riempire.
- *Casa con dati provvisori* (Tuturano): nota sotto il selettore, in parole.

**Tablet e telefono.** Sotto 62 rem il corpo prende tutta la larghezza con 24 px di margine; sotto
40 rem MAPPA e OSSERVATORIO passano in colonna singola e la fascia di stato resta in testa. Bersagli
non inferiori a 44 px, selettore Casa incluso. Sotto 30 rem (telefono in verticale) la testata
manda il selettore a capo sotto il marchio: resta leggibile e non si stringe il `<select>`.

---

## 3. I token

Tutti i valori stanno in `tokens/` con i contrasti misurati in commento. In sintesi:

| Ruolo | Valore | Contrasto |
|---|---|---|
| sfondo pagina | `--carta` #F5F3EE | — |
| testo | `--inchiostro` #1C1C1A | 15,39:1 su carta |
| testo tenue | `--inchiostro-tenue` #4A4A46 | 8,03:1 |
| testata | `--mare-notte` #06405A | bianco 11,12:1 |
| collegamenti e titoli | `--mare-profondo` #07577B | 7,12 / 7,90:1 |
| provenienza KB | #07577B su #EAF2F7 | 7,3:1 |
| provenienza Esterna | `--terra-scuro` #7A3D20 su #FBF0EA | 7,9:1 |
| attenzione | `--sole-scuro` #6B4A00 su `--sole-tenue` #FFE9A8 | 6,71:1 |
| focus | `--sole` #F6AF37 + anello #043044 | visibile su chiaro e su scuro |

Il minimo misurato è **6,71:1**, sopra il 7,99:1 dichiarato oggi solo nella coppia dell'attenzione —
che resta largamente oltre il 4,5:1 richiesto. Nessuna coppia scende sotto.

I tre colori di marca (#0B90CB mare, #CC7E5B terra, #F6AF37 sole, campionati dal logo Case di
Quartiere) **non portano mai testo**: stanno fra 1,9:1 e 3,6:1. Vivono nei filetti, nel marchio e
nei fondi. Il testo usa le varianti profonde.

**Tipografia**: Commissioner locale con fallback di sistema, base 16 px, scala 15 · 16 · 17 · 18 · 20 · 22 · 28 · 36 px. Il 15 px è ammesso solo per etichette e note, mai per testo corrente. Le etichette di provenienza restano in monospaziato di sistema, perché sono stringhe da citare, non prosa.

**Spaziature**: passo di 4 px, da 4 a 64. Padding di scheda 20 px, griglia 20 px, pagina 24 px.

---

## 4. Le due informazioni difficili

### Provenienza KB / Esterna

Tre canali ridondanti, nessuno dei quali è il colore da solo:

1. **la parola**, in grassetto e separata: `KB` oppure `Esterna`;
2. **il tratto del bordo**: continuo per KB, tratteggiato per Esterna — un tratteggio si legge anche
   in bianco e nero e anche da chi non distingue blu e marrone;
3. **la glossa in italiano semplice**, accanto all'etichetta: «la rete lo sa» / «trovato fuori, non
   verificato dalla rete».

Il testo dentro l'etichetta resta **quello composto dallo shim**, carattere per carattere:

    ▌KB  Rete delle Case di Quartiere · agg. 15/09/2026 · affidabilità 2     la rete lo sa
    ┌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌┐
    ╎Esterna  OpenStreetMap contributors (ODbL) · consultata 02:21 ·        ╎  trovato fuori,
    ╎         non verificata dalla rete                                     ╎  non verificato
    └╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌┘

**Perché non diventa rumore**: l'etichetta sta **sotto** la risposta, su una riga propria, in 15 px
monospaziato. Dentro la frase sarebbe rumore; sotto è una firma. Quando in una lista ogni riga ha la
sua provenienza (tabelle di MAPPA e OSSERVATORIO) la glossa si spegne (`glossa={false}`): la
colonna intera dice già di cosa si parla.

### La coda delle proposte

Il rischio è il contrario di quello che sembra: non che non si veda, ma che sembri un allarme. Non
c'è nessuna scadenza, nessuno è in ritardo, e V6 vieta gli imperativi. La soluzione è **una riga di
presenza**, in testa alla pagina, con tre informazioni e nessun verbo all'imperativo:

    ▌3 proposte aspettano una decisione a San Bao · la più vecchia da 4 giorni   Apri la coda
    ▌Nessuna proposta in attesa a San Bao.

Filetto **terracotta** a sinistra, mai rosso; nessun punto esclamativo, nessuna icona, nessun
contatore a pallino. Il dato che dice se la coda è ferma non è il numero, è **da quanto aspetta la
più vecchia**: è la sola informazione che distingue «tre arrivate oggi» da «tre ferme da un mese».
In più, il conteggio compare come riga secondaria sul riquadro OSSERVATORIO, perché è là che si
decide: `OSSERVATORIO — 3 proposte in attesa`.

---

## 5. La riga «Oggi»: sì, sta in testa

È l'unica cosa della pagina che cambia da sola, e dice se c'è qualcosa che vale un'occhiata prima di
entrare in un servizio. In fondo alla pagina viene letta **dopo** aver scelto, cioè mai. In testa —
sopra le destinazioni, sotto la testata — ha il posto che corrisponde a quello che è: uno stato.

Resta discreta per come è fatta, non per dove sta: una riga sola, 17 px, fondo bianco, filetto
sottile, la parola «OGGI» in 15 px maiuscoletto grigio. Non è un titolo, non è un banner, non è un
numero grande. E siccome «Oggi» e la coda delle proposte rispondono alla stessa domanda — *cosa bolle
in pentola* — stanno nella stessa fascia, una sopra l'altra.

---

## 6. Cosa NON cambiare

1. **I testi che esistono.** «Dati non disponibili: la memoria della rete non risponde in questo
   momento», «Servizio non ancora attivo», la riga della privacy in fondo, la frase composta dalla
   vista `v_oggi_casa`. Sono già in italiano semplice e già senza imperativi. Ho aggiunto testo,
   non riscritto quello che c'era.
2. **Il `<select>` per la Casa.** Con dieci voci, un cambio raro e la necessità di funzionare da
   tastiera e da screen reader senza codice, il controllo nativo è la scelta giusta. Un elenco di
   dieci bottoni-Casa occuperebbe la pagina per un'azione che si fa una volta. Due sole modifiche:
   l'etichetta «Casa di riferimento» diventa **visibile** (oggi è nascosta agli occhi e riservata
   agli screen reader: anche chi vede ha bisogno di sapere cos'è quel menu) e Tuturano porta
   «— dati provvisori» **dentro il testo dell'opzione**, non in un colore.
3. **Il comportamento della pagina.** Un solo `localStorage` con lo slug; gli `href` riscritti da
   `data-modello`; la scadenza a 3 secondi; il ritorno a «dati non disponibili» per qualunque
   guasto. Non tocco niente di questo: è già la cosa giusta e la veste non lo richiede.
4. **Dipendenze locali e peso.** Commissioner è incluso nel repository e non richiede rete esterna; il font aggiunge circa 1 MB al primo caricamento. Nessuna icona da libreria e nessuna immagine decorativa: l'unica immagine è il logo della rete (~20 KB in PNG).
5. **Il focus a due anelli.** Giallo + anello scuro è la soluzione che rende il focus visibile sia
   sulla carta sia sulla testata blu. L'ho ripresa identica, cambiando solo il giallo (#FFD400 →
   #F6AF37, il giallo del marchio).
6. **La griglia a due colonne dove serve.** MAPPA e OSSERVATORIO restano affiancate: sono due cose
   dello stesso peso e la coppia si legge in un colpo d'occhio. È la 2×2 a quattro elementi uguali
   che va sciolta, non l'idea di affiancare.

---

## Assunzioni che non condivido

- «Spesso usa un tablet, a volte un PC di Casa»: nel form mi è stato risposto **PC desktop** come
  dispositivo principale, con l'uso da telefono come possibilità. Il layout resta fluido e funziona
  da 320 px in su, ma la colonna di lettura è pensata su desktop, non su tablet in verticale.
- «REGISTRA / AGGIORNA: quando capita» — se il registro si attiva e diventa il modo normale di
  correggere i dati, la gerarchia va rivista: passerebbe a fianco di MAPPA e OSSERVATORIO. La
  gerarchia proposta descrive il lavoro **di oggi**, non un ordine permanente.
