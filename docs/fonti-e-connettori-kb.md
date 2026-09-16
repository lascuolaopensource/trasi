# Trasi — Fonti e connettori per la knowledge base

**A cosa serve.** Espandere la banca dati e i connettori dietro i servizi erogati della «Scheda dei servizi»
(gruppo Processi, aggiornata al 16/09/2026): OLD *Front office e accoglienza · Presidio contro la solitudine ·
Facilitazione interculturale · Osservatorio sociale di quartiere* e NEW 1–7.

**Come sono state prodotte le tabelle.** Ogni link è stato **misurato**, non ipotizzato:
`curl -s -m 15 -o /dev/null -w '%{http_code}' -A 'Mozilla/5.0 (X11; Linux x86_64)' -L <url>`, il 16/09/2026,
dallo stesso host che ospita lo stack. Il codice HTTP è fra parentesi accanto al link. I link non raggiungibili
**non** sono in tabella: sono elencati in fondo, con l'alternativa che li copre. Dove un `200` è **ingannevole**
— un corpo di blocco servito al posto della pagina, o una pagina costruita in JavaScript che senza browser resta
vuota — la riga lo dichiara invece di far finta che il link sia a posto. I tipi di connettore della
colonna 4 sono quelli che lo stack **sa già fare** — Onyx v4.7.2 (59 valori di `DocumentSource`, 55 mappati nel
registry lazy dei connettori), `trasi.fonte` (7 valori di `tipo_accesso`), i due flussi notturni e lo shim.
Nessun connettore inventato.

**Regola che governa la scelta del connettore (§3 V3 + §8 F4).** Un contenuto esterno entra in memoria per
**tre strade diverse**, e la strada decide l'etichetta che l'operatore vede in chat:

| Strada | Etichetta in chat | Mediazione umana | Chi la usa |
|---|---|---|---|
| Ricerca a runtime (`cerca_web` → SearXNG, filtrata sull'allow-list di `trasi.fonte`) | **`[Esterna · ente · ora · non verificata dalla rete]`** | nessuna: si legge e si cita | fonti autorevoli ma mutevoli (Comune, ASL, INPS) |
| Sorveglianza (`fonti_http.py`: hash del testo → **proposta**) | `[KB · …]` **solo dopo** che un umano approva | **obbligatoria** (V4) | pagine i cui orari cambiano e devono diventare dato della rete |
| Indicizzazione diretta (connettore Onyx `web`/`drive`/`file`, o `export_kb`) | `[KB · …]` subito | nessuna | ciò che la rete **possiede** (schede Casa, calendari, Drive) |

La terza strada **salta** il cancello della proposta: indicizzare con il connettore `web` di Onyx un sito
istituzionale esterno lo fa citare come memoria della rete, senza la dicitura «non verificata». È una scelta
legittima, ma è una decisione di governance, non un dettaglio tecnico: nel dubbio la strada giusta è la prima
(allow-list), e il passaggio in memoria avviene dopo, con una proposta.

---

## Tabella A — Link utili, servizio collegato, perché, connettore

### A.1 Ricerca a runtime su fonti esterne — `cerca_web` (SearXNG + allow-list `trasi.fonte`)

| Link utile (HTTP al 16/09/2026) | Servizio | Dettaglio del perché | Tipo di connettore |
|---|---|---|---|
| `https://www.comune.brindisi.it/servizi/` (200) | NEW 2 Servizi POV operatore | Pagina-madre di **tutte** le schede servizio del Comune: è l'indice da cui si risponde a «cosa devo fare per…» | `cerca_web` — una riga `fonte` (`tipo_accesso='web'`) autorizza il dominio `comune.brindisi.it` e tutti i suoi sottodomini |
| `https://www.comune.brindisi.it/servizi-categoria/salute-benessere-e-assistenza/` (200) | NEW 2 · OLD Presidio contro la solitudine | Categoria «Salute, benessere e assistenza»: è la sezione sociale e sanitaria del Comune | `cerca_web` (stesso dominio) |
| `https://www.comune.brindisi.it/amministrazione/unita_organizzativa/servizi-alla-persona/` (200) | NEW 2 · OLD Facilitazione interculturale | Unità «Servizio Sociale Professionale»: sede via Grazia Balsamo 4, tel 0831 229820, PEC | `cerca_web` (stesso dominio) |
| `https://www.comune.brindisi.it/vivere-il-comune/luoghi/servizi-sociali/` (200) | NEW 2 · OLD Presidio contro la solitudine | Scheda-luogo con indirizzo e orari dello sportello sociale: è il dato che si legge al cittadino | `cerca_web` (stesso dominio) |
| `https://www.comune.brindisi.it/amministrazione/uffici/` (200) | NEW 2 Servizi POV operatore | Elenco uffici con orari: la domanda n. 4 del set di prova («a che ora chiude lo sportello?») si risponde qui | `cerca_web` (stesso dominio) |
| `https://www.comune.brindisi.it/amministrazione/unita_organizzativa/ufficio-anagrafe/` (200) | NEW 2 · OLD Front office | Ufficio Anagrafe con orari, contatti e servizi erogati (CIE inclusa) | `cerca_web` (stesso dominio) |
| `https://www.comune.brindisi.it/servizio/certificati-anagrafici/` (200) | NEW 2 · OLD Front office | Scheda servizio più richiesta allo sportello: cosa chiedere, come, costi | `cerca_web` (stesso dominio) |
| `https://www.comune.brindisi.it/documento_pubblico/attestazione-estraneita-affettiva-ed-economica-ai-fini-isee/` (200) | NEW 2 Servizi POV operatore | Lato comunale della pratica ISEE: l'attestazione che il Comune deve rilasciare | `cerca_web` (stesso dominio) |
| `https://www.comune.brindisi.it/servizio/presentare-domanda-per-un-contributo/` (200) | NEW 2 · OLD Osservatorio sociale | Procedura dei contributi e sussidi: voce «contributi e sussidi» del livello Comune | `cerca_web` (stesso dominio) |
| `https://www.comune.brindisi.it/documento_pubblico/tari/` (200) | NEW 2 Servizi POV operatore | TARI: la scheda `/servizio/tari/` **non esiste** (404 misurato), questa è la pagina reale | `cerca_web` (stesso dominio) |
| `https://www.comune.brindisi.it/servizio/sportello-unico-telematico-per-ledilizia-sue/` (200) | NEW 2 Servizi POV operatore | SUE: come si presenta un'istanza edilizia, con la modulistica | `cerca_web` (stesso dominio) |
| `https://www.comune.brindisi.it/web/suap/` (200) | NEW 2 Servizi POV operatore | SUAP: l'unica superficie SUAP raggiungibile (`suap.comune.brindisi.it` non risolve) | `cerca_web` (stesso dominio) |
| `https://www.comune.brindisi.it/vivere-il-comune/eventi/` (200) | NEW 1 Eventi POV operatore | Calendario eventi comunali in HTML: unica pagina-eventi pubblica del Comune | `cerca_web` + sorveglianza (`http`) per il palinsesto |
| `https://www.comune.brindisi.it/argomento/istruzione/` (200) | NEW 2 Servizi POV operatore | Scuole, mensa e servizi scolastici: copre la voce «scuole» del livello Comune | `cerca_web` (stesso dominio) |
| `https://www.comune.brindisi.it/argomento/turismo/` (200) | NEW 1 Eventi POV operatore | Aggregatore di eventi, luoghi e tempo libero della città | `cerca_web` (stesso dominio) |
| `https://servizi.comune.brindisi.it/` (200) | NEW 2 · OLD Front office | Portale servizi online del Comune (appuntamenti, trasparenza, pagamenti) | `cerca_web` — **già coperto** dalla riga `Comune di Brindisi-3`: l'allow-list confronta per etichetta di dominio, e un dominio autorizza i propri sottodomini (`_in_allowlist` in `shim/app/testi.py`: `comune.brindisi.it` → `servizi.comune.brindisi.it` ✅, `falso-comune.brindisi.it.example` ❌) |
| `https://servizi.comune.brindisi.it/openweb/appuntamenti/scegli.php` (200) | OLD Front office e accoglienza | Prenotazione appuntamenti agli uffici: è il deep link operativo da dare al cittadino | `cerca_web` (sottodominio già autorizzato) |
| `https://servizi.comune.brindisi.it/openweb/trasparenza/` (200) | NEW 4 Monitoraggio POV PA | Atti e trasparenza: sostituisce l'albo pretorio, che **non** ha un URL raggiungibile (404/403 misurati) | `cerca_web` (sottodominio già autorizzato) |
| `https://www.sanita.puglia.it/web/asl-brindisi` (200) | NEW 2 Servizi POV operatore | Pagina-madre dell'ASL Brindisi con i numeri unici (CUP 800888388, URP, PS 112) | `cerca_web` — **il dominio storico `asl.brindisi.it` non risponde (000)**: l'autorità è su `sanita.puglia.it` |
| `https://www.sanita.puglia.it/web/asl-brindisi/cup` (200) | NEW 2 Servizi POV operatore | CUP: canali di prenotazione, disdetta entro 48 h, validità ricetta | `cerca_web` (host `sanita.puglia.it`) |
| `https://www.sanita.puglia.it/servizi-di-prenotazione` (200) | NEW 2 Servizi POV operatore | Il servizio di prenotazione online vero e proprio, non la pagina che lo descrive | `cerca_web` (stesso host) |
| `https://www.sanita.puglia.it/en/web/asl-brindisi/consultori` (200) | NEW 2 · OLD Presidio contro la solitudine | Consultori: 16 sedi, accesso libero e gratuito anche per persone straniere | `cerca_web` (stesso host) |
| `https://www.sanita.puglia.it/web/asl-brindisi/-/consultorio-familiare-n-1-brindisi-centro` (200) | NEW 2 Servizi POV operatore | Orari e contatti reali di un consultorio cittadino (via Egnazia 1, 0831 510041) | `cerca_web` (stesso host) |
| `https://www.sanita.puglia.it/web/asl-brindisi/-/c-s-m-distretto-sociosanitario-n-1-brindisi` (200) | NEW 2 · OLD Presidio contro la solitudine | CSM: piazza A. di Summa 1, lun–sab 8–14, accesso libero con urgenze | `cerca_web` (stesso host) |
| `https://www.sanita.puglia.it/en/web/asl-brindisi/-/dipendenze-patologiche` (200) | NEW 2 Servizi POV operatore | SerD: struttura-madre con l'elenco di tutti i SERT della provincia | `cerca_web` (stesso host) |
| `https://www.sanita.puglia.it/web/asl-brindisi/-/ser-t-brindisi?ids=548992` (200) | NEW 2 Servizi POV operatore | Orari reali del SerT di Brindisi (via S. Teresa 7, lun–ven 8–12.45) | `cerca_web` (stesso host) |
| `https://www.sanita.puglia.it/en/web/asl-brindisi/-/rinnovo-esenzione-ticket-per-reddito` (200) | NEW 2 Servizi POV operatore | Esenzioni ticket per reddito: autocertificazione con SPID e uffici di distretto | `cerca_web` (stesso host) |
| `https://www.sanita.puglia.it/en/web/asl-brindisi/assistenza-psicologica-ai-caregiver` (200) | OLD Presidio contro la solitudine · NEW 2 | «Consapevolmente Caregiver»: supporto psicologico gratuito con le finestre di chiamata per distretto | `cerca_web` (stesso host) |
| `https://www.sanita.puglia.it/en/web/asl-brindisi/distretti-socio-sanitari` (200) | NEW 2 Servizi POV operatore | Pagina-madre dei 4 distretti: da qui si individua l'ufficio di competenza | `cerca_web` (stesso host) |
| `https://www.sanita.puglia.it/en/web/asl-brindisi/pnes-contrasto-alla-poverta-sanitaria` (200) | OLD Osservatorio sociale di quartiere | Contrasto alla povertà sanitaria: riferimento regionale per la lettura dei bisogni | `cerca_web` (stesso host) |
| `https://www.inps.it/it/it/dettaglio-scheda.it.schede-servizio-strumento.schede-servizi.Portale-unico-ISEE.html` (200) | NEW 2 · OLD Front office | Scheda ufficiale ISEE: tipologie, DSU, tempi dell'attestazione | `cerca_web` (host `inps.it`) |
| `https://servizi2.inps.it/servizi/ISEEPrecompilato/WfSimHome.aspx` (200) | NEW 2 Servizi POV operatore | Il servizio dove la DSU si presenta davvero: è il link da mostrare in sportello | `cerca_web` — host `servizi2.inps.it`, autorizzato dal dominio `inps.it` |
| `https://servizi2.inps.it/servizi/iseeriforma/home.aspx` (200) | NEW 2 Servizi POV operatore | Canale alternativo per chi ha già una DSU e deve ritirare l'attestazione | `cerca_web` (stesso host) |
| `https://www.agenziaentrate.gov.it/portale/cittadini` (200) | NEW 2 Servizi POV operatore | Codice fiscale, dichiarazioni, rimborsi, calcolatori: le pratiche fiscali quotidiane | `cerca_web` (host `agenziaentrate.gov.it`) |
| `https://www.agenziaentrate.gov.it/portale/cittadini/pagamenti-e-rimborsi` (200) | NEW 2 Servizi POV operatore | Deep link mirato su pagamenti e rimborsi (F24) | `cerca_web` (stesso host) |
| `https://www.agenziaentrateriscossione.gov.it/it/cittadini/` (200) | NEW 2 Servizi POV operatore | Cartelle e rottamazione: domanda frequente allo sportello, fonte diversa dall'Agenzia | `cerca_web` — riga `fonte` per `agenziaentrateriscossione.gov.it` |
| `https://www.regione.puglia.it/web/welfare-diritti-e-cittadinanza/elenco-bandi` (200) | NEW 2 · OLD Osservatorio sociale | Elenco bandi welfare: è il dato «Bandi e opportunità» del livello Staff | `cerca_web` (host `regione.puglia.it`) |
| `https://www.regione.puglia.it/web/welfare-diritti-e-cittadinanza/servizi-e-modulistica` (200) | OLD Front office · NEW 2 | Modulistica ufficiale dei servizi socio-assistenziali regionali | `cerca_web` (stesso host) |
| `https://www.regione.puglia.it/web/welfare-diritti-e-cittadinanza` (200) | OLD Osservatorio · NEW 4 Monitoraggio PA | Piano regionale, piani di zona, rete dei servizi: cornice per leggere i bisogni | `cerca_web` (stesso host) |
| `https://servizisocialipuglia.it/` (200) | OLD Osservatorio · NEW 2 | Registro regionale delle strutture socio-assistenziali autorizzate, per comune e tipologia | `cerca_web` — **attenzione: solo senza `www`** (con `www` = 000) |
| `https://www.consorziosocialebr1.it/` (200) | OLD Facilitazione interculturale · NEW 2 | Ambito Territoriale Sociale BR1: avvisi e servizi (integrazione scolastica, autismo) | `cerca_web` (host `consorziosocialebr1.it`) |
| `https://www.csvbrindisilecce.it/` (200) | OLD Osservatorio · NEW 2 | Centro Servizi al Volontariato: la rete ETS di Brindisi e Lecce in un unico canale | `cerca_web` (host `csvbrindisilecce.it`) |
| `https://www.csvbrindisilecce.it/contatti/` (200) | OLD Front office · NEW 2 | Sportello CSV **dentro** il Centro Anziani Bozzano (via Spagna 16), con orari | `cerca_web` (stesso host) |
| `https://www.diocesibrindisiostuni.it/arcidiocesi/parrocchie/` (200) | OLD Presidio contro la solitudine · NEW 2 | 60 parrocchie con contatti: i punti di ascolto più capillari del territorio | `cerca_web` (host `diocesibrindisiostuni.it`) |
| `https://www.diocesibrindisiostuni.it/mensa-della-carita-delle-parrocchie-di-brindisi-servizio-ai-poveri/` (200) | OLD Presidio contro la solitudine | Mensa della Carità: ingresso via Peschiera, ~190 pasti/giorno, 16 parrocchie solidali | `cerca_web` (stesso host) — **gli orari non sono pubblicati**: da inserire a mano |
| `https://www.bancoalimentare.it/sedi-locali/puglia` (200) | OLD Presidio contro la solitudine · NEW 2 | Rete dei punti di distribuzione alimentare della Puglia con indirizzi | `cerca_web` — riga `fonte` per `bancoalimentare.it` |
| `https://gaia.cri.it/informazioni/sedi/puglia-brindisi/` (200) | OLD Presidio contro la solitudine | Anagrafica ufficiale del Comitato CRI di Brindisi (il comitato non ha sito proprio) | `cerca_web` — riga `fonte` per `gaia.cri.it` |
| `https://questure.poliziadistato.it/it/Brindisi` (200 **ma corpo «Accesso negato»**) | NEW 2 · OLD Facilitazione interculturale | Portale della Questura: passaporti, immigrazione, denunce. **Attenzione**: l'host risponde 200 servendo una pagina di blocco — il testo utile non è leggibile da qui, e `www.questure.poliziadistato.it` non risolve affatto (DNS). Il blocco è identico con tre user-agent diversi e anche dal container dello shim: non è un filtro sul client. Da riprovare con il connettore `web` di Onyx, che guida un browser vero (Playwright, con attesa per le challenge e gestione cookie) | `cerca_web` — riga `fonte` per `questure.poliziadistato.it`, **da verificare prima di attivare**; se non passa, `web` (Onyx) o niente |
| `https://www.interno.gov.it/it/temi/immigrazione-e-asilo/permesso-di-soggiorno` (200, contenuto leggibile) | OLD Facilitazione interculturale | Permesso di soggiorno: la pagina informativa del Ministero, che **non** è dietro il blocco della Questura | `cerca_web` — riga `fonte` per `interno.gov.it` (autorizza anche `prefettura.interno.gov.it`) |
| `https://prefettura.interno.gov.it/it/prefetture/brindisi/uffici/aree-e-servizi` (200) | NEW 2 Servizi POV operatore | Aree e servizi della Prefettura: orienta la richiesta all'ufficio giusto | `cerca_web` — riga `fonte` per `prefettura.interno.gov.it` |
| `https://identitadigitale.gov.it/` (200) | OLD Front office · NEW 2 | Richiedere SPID o CIE, confronto gestori, app CieID: primo passo per i servizi digitali | `cerca_web` — riga `fonte` per `identitadigitale.gov.it` |
| `https://www.cartaidentita.interno.gov.it/` (200) | OLD Front office · NEW 2 | Guida ufficiale CIE e prenotazione (`prenotazionicie.interno.gov.it` = 000 da questo host) | `cerca_web` — riga `fonte` per `cartaidentita.interno.gov.it` |
| `https://arpal.regione.puglia.it/cpi-provincia-brindisi` (200) | NEW 2 Servizi POV operatore | Tutti i Centri per l'Impiego della provincia, con link alle schede | `cerca_web` — riga `fonte` per `arpal.regione.puglia.it` |
| `https://arpal.regione.puglia.it/cpi-provincia-brindisi/cpi-brindisi` (200) | NEW 2 · OLD Front office | Scheda del CPI di Brindisi: indirizzo, orari, contatti, servizi (IDO, DID) | `cerca_web` (stesso host) |
| `https://sintesi.regione.puglia.it/web/sintesi-brindisi/centro-per-l-impiego-di-brindisi` (200) | NEW 2 Servizi POV operatore | Scheda alternativa del CPI, con orari sportelli e PEC | `cerca_web` — **host senza `www`** (con `www` = 000) |
| `https://www.cpiabrindisi.edu.it/` (200) | NEW 2 · OLD Facilitazione interculturale | CPIA «Anna Lorenzetto»: istruzione degli adulti e alfabetizzazione in italiano | `cerca_web` — riga `fonte` per `cpiabrindisi.edu.it` |
| `https://www.mim.gov.it/en/istruzione-per-gli-adulti-centri-provinciali-per-l-istruzione-degli-adulti` (200) | NEW 2 · OLD Facilitazione interculturale | Quadro nazionale dei percorsi per adulti: chi può iscriversi e con quali percorsi | `cerca_web` — riga `fonte` per `mim.gov.it` |
| `https://www.unisalento.it/ufficio-orientamento` (200) | NEW 2 Servizi POV operatore | Sportello universitario di riferimento (non c'è una sede UNISALENTO a Brindisi) | `cerca_web` — riga `fonte` per `unisalento.it` |
| `https://itsaerospaziopuglia.tuttogare.it/` (200) | NEW 2 Servizi POV operatore | ITS Aerospazio a Brindisi: corsi post-diploma gratuiti per i giovani della rete | `cerca_web` — riga `fonte` per `tuttogare.it` |
| `https://www.poste.it/uffici-postali/index.html` (200) | NEW 2 Servizi POV operatore | Ricerca uffici postali con orari: molti servizi (CIE, pratiche) passano da qui | `cerca_web` — riga `fonte` per `poste.it` |
| `https://www.poste.it/servizi-online.html` (200) | NEW 2 Servizi POV operatore | Panoramica dei servizi online (PosteID, spedizioni, pratiche) | `cerca_web` (stesso host) |
| `https://www.casediquartiere.it/` (200) | OLD Front office · NEW 2 | Pagina-madre della rete: le 10 Case con ente gestore, indirizzo, orari, contatti | `cerca_web` — riga `fonte` per `casediquartiere.it` (sito del progetto, gestito dal Comune) |
| `https://www.casediquartiere.it/eventi/` (200) | NEW 1 Eventi POV operatore | Unica pagina-eventi aggregata della rete: candidata naturale al palinsesto condiviso | `cerca_web` + sorveglianza (`http`) |
| `https://www.casediquartiere.it/our-team/` (200) | NEW 2 Servizi POV operatore | Schede degli enti gestori, con i contatti delle persone di riferimento | `cerca_web` (stesso host) |
| `https://www.casediquartiere.it/san-bao/` (200) | OLD Front office · NEW 2 | Scheda Casa con orari e contatti (idem `/parco-buscicchio/`, `/minimus/`, `/scuole-pie/`, `/palazzoguerrieri/`, `/casa-della-musica/`, `/ferrante-aporti/`, `/cag/`, tutte 200) | `cerca_web` (stesso host) |
| `https://www.naukleros.com/` (200 **ma pagina resa da JavaScript**: 7,7 kB di HTML senza testo visibile) e `http://www.naukleros.com/san-bao-casa-di-quartiere-la-rosa` (200, title corretto) | OLD Front office · NEW 2 | Ente gestore di San Bao, con una sottopagina dedicata alla Casa. **Attenzione**: è un «supersite» Aruba che costruisce la pagina in JavaScript — un connettore `web` che non esegue JS non ne ricaverebbe nulla (il WebConnector di Onyx usa Playwright e ce la fa, `scroll_before_scraping` se serve) | `cerca_web` (host `naukleros.com`) — per la ricerca il contenuto lo ha già reso il motore; per l'`http` change-detection serve il connettore `web` con scroll |
| `https://www.legamidicomunita-br.it/` (200) | OLD Front office · NEW 2 | Gestore del Parco Buscicchio: contatti e attività della Casa | `cerca_web` (host `legamidicomunita-br.it`) |
| `https://www.ilbenechetivoglio.it/` (200) | NEW 2 Servizi POV operatore | Uno dei due gestori di Dream: contatti e missione dell'associazione | `cerca_web` (host `ilbenechetivoglio.it`) |
| `https://www.angsa.it/` (200) | NEW 2 Servizi POV operatore | ANGSA nazionale (contatti locali Brindisi: brindisi@angsa.it, 338 6456396) | `cerca_web` (host `angsa.it`) |
| `https://molo12brindisi.com/coworking/` (200) | NEW 2 Servizi POV operatore | Descrizione dei servizi del Molo 12 (coworking, fablab) — **la home è instabile (500 misurato)** | `cerca_web` (host `molo12brindisi.com`), deep link invece della home |
| `https://molo12brindisi.com/contattaci/` (200) | OLD Front office | Contatti operativi del Molo 12 (via Guerrieri 7, 0831 361932) | `cerca_web` (stesso host) |
| `https://theqube.it/` (200) | NEW 2 Servizi POV operatore | L'incubatore gestore del Molo 12: notizie e servizi | `cerca_web` (host `theqube.it`) |
| `https://sites.google.com/view/accademiadeglierranti/home` (200) | OLD Front office · NEW 2 | Unica pagina-web dedicata all'Accademia degli Erranti (sede, contatti, orari su prenotazione) | `cerca_web` — riga `fonte` per `sites.google.com`, o connettore Onyx `google_sites` (che però vuole uno zip del sito: più fragile) |
| `https://percorsiconibambini.it/congliocchideiquartieri/` (200) | NEW 2 Servizi POV operatore | Unica descrizione strutturata dei laboratori del POP Perrino (che non ha sito) | `cerca_web` (host `percorsiconibambini.it`) |
| `https://www.cooperidano.it/service/centro-diurno-eridano-di-giorno/` (200) | NEW 2 Servizi POV operatore | Centro diurno disabilità: modalità di accesso (UVM/PAI/PUA) e retta documentate | `cerca_web` (host `cooperidano.it`) |
| `https://www.patronato.acli.it/` (200) | OLD Front office | Patronato ACLI: ricerca sedi; lo sportello di Brindisi è in Corso Umberto I 122 | `cerca_web` (host `patronato.acli.it`) |
| `https://www.inca.it/` (200) | OLD Front office | INCA-CGIL: sportello di Brindisi in via P. Togliatti 44, orari lun–ven 8.30–13 e 16–19 | `cerca_web` (host `inca.it`) |
| `https://www.cafcisl.it/it-ricerca_sedi` (200) | OLD Front office | CAF CISL: ricerca sedi (Brindisi, via P. Togliatti 88) | `cerca_web` (host `cafcisl.it`) |
| `https://caf.coldiretti.it/dove-siamo/puglia/` (200) | OLD Front office | CAF Coldiretti: elenco sedi regionali (Brindisi, via Appia 226) | `cerca_web` (host `caf.coldiretti.it`) |
| `https://www.csvbrindisilecce.it/category/brindisi/` (200) | NEW 1 · NEW 2 | Notizie e avvisi degli ETS della provincia, aggiornati al 16/09/2026: fonte viva | `cerca_web` (stesso host) |

### A.2 Sorveglianza del cambiamento — `http` (`flussi/fonti_http.py` → **proposta**, mai scrittura)

Questi sono i link in cui **il valore sta nella variazione**: se cambiano, nasce una proposta che un umano
approva. Richiedono un bersaglio in `flussi/fixtures/fonti_http.json` (`fonte`, `url`, `selettore`, `entita`,
`campo`) — e il selettore **va individuato sulla pagina vera**: finché non è verificato, il bersaglio resta
`attivo: false`, altrimenti il flusso registra un errore ogni notte e l'alert insegna a ignorarlo.

| Link utile (HTTP al 16/09/2026) | Servizio | Dettaglio del perché | Tipo di connettore |
|---|---|---|---|
| `https://www.comune.brindisi.it/notizie/avvisi/` (200) | NEW 2 · NEW 4 Monitoraggio PA | Gli avvisi del Comune cambiano di continuo: un cambio è un'opportunità da valutare, non un dato da scrivere | `http` — bersaglio di sorveglianza, `entita='scheda_servizio'` (o `opportunita`) |
| `https://www.comune.brindisi.it/vivere-il-comune/eventi/` (200) | NEW 1 Eventi POV operatore | Il palinsesto comunale cambia: la sorveglianza propone l'evento, l'operatore decide | `http` — bersaglio di sorveglianza su `entita='evento'` |
| `https://www.sanita.puglia.it/web/asl-brindisi/cup` (200) | NEW 2 Servizi POV operatore | Orari e canali CUP cambiano senza preavviso: è il caso d'uso della change-detection | `http` — bersaglio di sorveglianza su `entita='luogo'`, `campo='orari'` |
| `https://www.sanita.puglia.it/en/web/asl-brindisi/consultori` (200) | NEW 2 · OLD Presidio contro la solitudine | L'elenco dei consultori e le loro sedi si aggiornano: serve la proposta, non l'ingestione cieca | `http` — bersaglio di sorveglianza su `entita='luogo'` |
| `https://www.casediquartiere.it/` (200) | OLD Front office · NEW 2 | Gli orari delle Case pubblicati qui sono la fonte con cui confrontare la memoria locale | `http` — un bersaglio per Casa (`selettore` sulla scheda della singola Casa) |
| `https://www.comune.brindisi.it/amministrazione/unita_organizzativa/ufficio-anagrafe/` (200) | NEW 2 · OLD Front office | Gli orari degli sportelli anagrafe cambiano per stagione o per aperture straordinarie | `http` — bersaglio su `entita='luogo'`, `campo='orari'` |
| `https://servizi.comune.brindisi.it/openweb/appuntamenti/scegli.php` (200) | OLD Front office | Se cambiano i servizi prenotabili, cambia il modo in cui si indirizza il cittadino | `http` — bersaglio su `entita='luogo'` |
| `https://www.comune.brindisi.it/documento_pubblico/tari/` (200) | NEW 2 Servizi POV operatore | Scadenze e regolamenti TARI cambiano ogni anno | `http` — bersaglio su `entita='scheda_servizio'` |

**Da correggere subito.** Il bersaglio oggi in `flussi/fixtures/fonti_http.json` punta a
`https://www.comune.brindisi.it/urp` con selettore `#orari-urp`: **quella pagina risponde 404** (misurato), e
nessuna pagina URP dedicata esiste nel sitemap del Comune. Il bersaglio è già `attivo: false`, quindi non
produce rumore — va rimpiazzato con uno degli URL qui sopra quando il TI verifica il selettore.

### A.3 Scrittura diretta ammessa — `ical` (`flussi/fonti_ical.py`: upsert su `evento`, con audit)

| Link utile | Servizio | Dettaglio del perché | Tipo di connettore |
|---|---|---|---|
| *nessun link pubblico trovato* | NEW 1 Eventi POV operatore | **Misurato: nessuna delle 10 Case, né la rete, né il Comune pubblica un feed iCal.** `casediquartiere.it/schedule/` è un calendario WordPress, non un feed; i Google Calendar delle Case non risultano pubblici | `ical` — il connettore **c'è ed è testato**, ma è senza sorgente: va creato il feed (una riga di `fonte` con `tipo_accesso='ical'` e `url` valorizzato). Nel frattempo gli eventi entrano da `fonti_http` (proposta) o da `crea_evento` in chat |

### A.4 Geografia — `osm_overpass` (shim `vicino_a`)

| Link utile (HTTP al 16/09/2026) | Servizio | Dettaglio del perché | Tipo di connettore |
|---|---|---|---|
| `https://overpass.openstreetmap.fr/api/interpreter` (403 senza user-agent, **200 con UA `Trasi/1.0`**) | NEW 2 · OLD Presidio contro la solitudine | POI e `opening_hours` entro il raggio della Casa: risponde a «il bar più vicino è aperto adesso?» | `osm_overpass` — già configurato (`OVERPASS_URL`, `OVERPASS_URL_2`) e con timeout 5 s |
| `https://overpass-api.de/api/interpreter` (406) | — | **Non usare**: bloccato da questo host, come già annotato nel piano | — |
| `https://nominatim.openstreetmap.org/` (200) | NEW 2 Servizi POV operatore | Geocodifica di un indirizzo scritto dall'operatore → coordinate per `vicino_a` | `api` — dichiarato in `fonte.tipo_accesso`, **nessun flusso lo implementa oggi**: richiede lavoro nello shim, non è una riga di configurazione |

### A.5 Memoria della rete e dati strutturati — `ingestion_api`, `file`, `drive`, `user_file`

| Link / sorgente | Servizio | Dettaglio del perché | Tipo di connettore |
|---|---|---|---|
| vista `trasi.v_kb_export` (nessun URL: è il database) | tutti | È il canale con cui luoghi, Case, schede, eventi e opportunità **verificati** diventano KB citabile | `ingestion_api` — `flussi/export_kb.py` su cc_pair «Trasi KB (export)», upsert idempotente per `doc_id` |
| cartella Drive «Trasi KB» (documenti della rete: linee guida, verbali, modulistica) | OLD Front office · NEW 2 | I documenti che la rete già produce su Drive: oggi **non** entrano in KB (V-02 rosso, consent Google bloccato) | `drive` — connettore OAuth disponibile e credenziale presente; sbloccato il consent, una riga di configurazione |
| file caricati in chat (locandine, PDF, XLS: «non trovo quello che cerco, carico il file») | NEW 1 · NEW 2 | Il documento dice esplicitamente che l'operatore deve poter caricare una locandina e chiedere «abbiamo info su questa cosa?» | `user_file` — sorgente presente e senza configurazione (si abilita allegando i file alla persona, `persona.user_files`); **il documento resta del caricatore o della persona**: non entra nella KB condivisa |
| `kb_export/` su disco | — | Cartella ispezionabile di appoggio, non un canale di ingestione: il connettore `file` di Onyx 4.7.2 legge solo UUID del filestore interno | `file` — disponibile ma **non** usabile puntando a una directory dell'host (verificato sul sorgente) |
| casella di posta di servizio (comunicazioni del Comune alle Case, PEC) | NEW 7 Chat interna segnalazioni | Le comunicazioni ufficiali oggi passano per email: indicizzarle renderebbe citabili gli aggiornamenti | `imap` — connettore disponibile in Onyx, **non configurato**: richiede una casella dedicata e un presidio privacy |

### A.6 Open data — `api` (dichiarato, non implementato)

| Link utile (HTTP al 16/09/2026) | Servizio | Dettaglio del perché | Tipo di connettore |
|---|---|---|---|
| `https://dati.puglia.it/` (200) | OLD Osservatorio sociale · NEW 4 Monitoraggio PA | Oltre 800 dataset regionali: è la materia prima dei report aggregati al Comune | `api` — `tipo_accesso='api'` esiste nel vocabolario di `fonte`, **nessun flusso lo legge**: serve uno script nuovo se si vuole il dato fresco |
| `https://esploradati.istat.it/` (200) | OLD Osservatorio sociale · NEW 4 | Query su popolazione, famiglie, lavoro a livello comunale (Brindisi = 074001) | `api` — come sopra |
| `https://www.istat.it/it/cittadini` (200) | OLD Osservatorio · NEW 4 | Indicatori e comunicati: contesto territoriale per la lettura dei bisogni | `cerca_web` — riga `fonte` per `istat.it` (è consultazione, non serie storica) |
| `https://www.comune.brindisi.it/amministrazione/documenti-e-dati/dataset/` (200) | NEW 4 Monitoraggio POV PA | Open data comunali: **poveri** (dataset 2014–2016), ma è l'unico canale dati del Comune | `cerca_web` (stesso dominio) |

---

## Tabella B — Tipi di connettore: quali link coprono, quali servizi erogano

| Tipo di connettore (stato reale al 16/09/2026) | Link che copre | Servizi che permette di erogare |
|---|---|---|
| **`cerca_web`** — ricerca a runtime su SearXNG interno, filtrata per dominio da `trasi.fonte WHERE tipo_accesso='web' AND attiva` (attivo) | Tutte le 80 righe di §A.1 (81 URL) — Comune, `servizi.comune.brindisi.it`, ASL/PugliaSalute, INPS, Agenzia Entrate, ADER, Regione Puglia, ARPAL, SINTESI, CPIA, MIM, UNISALENTO, ITS, Poste, identità digitale, CIE, Ministero dell'Interno, Prefettura, Consorzio BR1, CSV, Diocesi, Banco Alimentare, CRI, cooperative sociali, CAF/patronati, `casediquartiere.it` e i siti dei gestori | **NEW 2 Servizi POV operatore** (risposta con badge `[Esterna]`), **OLD Front office e accoglienza**, **OLD Facilitazione interculturale**, **OLD Presidio contro la solitudine**, **NEW 1 Eventi** (limitatamente a eventi pubblicati sul web). Ogni risposta porta ente, URL, ora della consultazione e la dicitura «non verificata dalla rete»: è V3 che si compie |
| **`http`** — change-detection su hash di un selettore; produce **una proposta**, non una scrittura (attivo, 1 bersaglio configurato e inattivo) | Gli 8 link di §A.2 | **NEW 1 Eventi**, **NEW 2 Servizi POV**, **OLD Front office**, **NEW 4 Monitoraggio PA** — nella forma «la fonte è cambiata, decidi tu»: è V4 che si compie |
| **`ical`** — upsert diretto su `evento` da fonte `tipo_accesso='ical'`, con una riga di `audit` per variazione (attivo, **nessuna sorgente**) | Nessuno (da creare: feed delle 10 Case e della rete) | **NEW 1 Eventi POV operatore** — è l'unico percorso che rende un evento di domani visibile in chat senza passare dalla coda di approvazione |
| **`osm_overpass`** — query Overpass entro `casa.raggio_m` (attivo, verificato dal container) | `overpass.openstreetmap.fr/api/interpreter` (con user-agent identificativo) | **NEW 2 Servizi POV operatore** e **OLD Presidio contro la solitudine**: luoghi e orari vicini alla Casa, con badge OSM; alimenta anche il biglietto («come arrivare») |
| **`ingestion_api`** — `POST /onyx-api/ingestion` sul cc_pair «Trasi KB (export)» (attivo, 32 documenti, idempotente) | La vista `trasi.v_kb_export` (luoghi, Case, schede, eventi, opportunità validi) | **Tutti i servizi**: è la memoria della rete che l'assistente cita con badge `[KB · fonte · data · affidabilità]`. Nessun servizio esiste senza questa |
| **`web` (Onyx WebConnector: `sitemap` / `single` / `recursive`)** — indicizza pagine nel KB di Onyx (disponibile, nessun connettore configurato) | ⚠️ **Non `sitemap` sul sito del Comune.** `robots.txt` dichiara `https://www.comune.brindisi.it/wp-sitemap.xml`, che è un **`<sitemapindex>`**: il connettore legge i `<loc>` di primo livello e **non ricorre** negli indici figli (`extract_urls_from_sitemap` in `connectors/web/connector.py:289` prende tutti i `<loc>` e si ferma — nessuna discesa, perché la ricorsione è solo in `list_pages_for_site`, che scatta quando *non* trova un urlset). Risultato: un connettore `sitemap` sul Comune indicizzerebbe **21 file XML**, non 900+ pagine. Il che, per inciso, è innocuo — meglio così che un crawl accidentale di 900 pagine su 4 vCPU. Per indicizzare davvero: `sitemap` su ciascun sotto-sitemap (`.../wp-sitemap-posts-servizio-1.xml` per le 12 schede, `.../documento_pubblico-1.xml` per i 107 documenti, `.../punto_contatto-1.xml` per i 93 punti di contatto, `.../unita_organizzativa-1.xml` per i 28 uffici), oppure `single` sulle pagine scelte. Le 864 **notizie** e i 40 **luoghi** conviene tenerli fuori: sono volume, non risposta. Stessa trappola su `https://www.casediquartiere.it/wp-sitemap.xml` (**`<sitemapindex>`, 15 `<loc>`**): anche qui si punta ai sotto-sitemap, non all'indice — quelli che contano sono `.../casediquartiere.it/wp-sitemap-posts-page-1.xml` (**51 pagine**, fra cui le schede delle Case) e `.../wp-sitemap-posts-mp-event-1.xml` (**13 eventi**) | **NEW 2 Servizi POV operatore**, **OLD Front office**, **NEW 4 Monitoraggio PA**. **Attenzione**: ciò che entra da qui è citato come KB, **senza** la dicitura «non verificata» e **senza** proposta: da usare solo per contenuti che la rete possiede o che il Comune pubblica come propri. Il crawler guida un browser vero (Playwright, con attesa per le challenge e `scroll_before_scraping` per i siti che rendono in JavaScript come `naukleros.com`): il costo va misurato, non acceso e dimenticato |
| **`drive` (Onyx Google Drive, OAuth)** — indicizza documenti Drive (disponibile, credenziale presente, **connector assente: V-02 rosso**) | Cartella Drive «Trasi KB» e «KB export» della rete | **Tutti i servizi** (documenti, linee guida, verbali, modulistica). Resta il fallback manuale finché Google non sblocca il consent: `publish` dell'app o aggiunta dei tester |
| **`file` (Onyx FileConnector)** — carica dal **filestore interno** di Onyx, non da una directory dell'host (disponibile, non configurato) | Nessun percorso host: solo UUID già caricati nell'interfaccia | **NEW 2 Servizi POV operatore**, **OLD Front office** — utile per un documento caricato a mano dall'amministratore, non per una cartella sorvegliata |
| **`user_file` (Uploaded Files)** — sorgente `user_file` presente in Onyx, esposta dal persona se la persona ha file allegati (`persona.user_files`, verificato sul sorgente), **nessuna configurazione** | File che l'operatore allega durante il colloquio (locandina, PDF, XLS) | **NEW 2 Servizi POV operatore**, **OLD Front office**: risponde al requisito del documento «non trovo quello che cerco, carico il file — abbiamo info su questa cosa?». Il file resta del caricatore (o allegato alla persona) e **non** entra nella KB condivisa |
| **`imap` (Onyx Email)** — mappato nel registry (`DocumentSource.IMAP`), **non configurato** | Casella di servizio/PEC delle comunicazioni ufficiali alle Case | **NEW 7 Chat interna segnalazioni POV operatore** (in sola lettura indicizzata), **NEW 2 Servizi POV operatore**. Richiede una casella dedicata e un vaglio privacy prima di accendersi |
| **`api`** — valore dichiarato in `trasi.fonte.tipo_accesso`, **nessun flusso lo legge** (non implementato) | `https://dati.puglia.it/`, `https://esploradati.istat.it/`, `https://nominatim.openstreetmap.org/` | **OLD Osservatorio sociale di quartiere**, **NEW 4 Monitoraggio POV PA**, **NEW 2 Servizi POV operatore** (geocodifica). Oggi il dato va preso a mano o via `cerca_web`: per una serie storica serve uno script nuovo |
| **`kb` / `Rete-kb-3`** — non è un connettore: è la fonte con cui si etichetta la memoria della rete (attivo) | — | **Tutti i servizi**: è il badge `[KB · Rete delle Case di Quartiere]` che accompagna le risposte senza fonte esterna |
| **social — nessun connettore** (Onyx non ha connettori Instagram/Facebook/WhatsApp; nessuno scraping, per privacy) | 15 profili censiti: `facebook.com/CaseDiQuartiereBrindisi`, `facebook.com/Yeahjasi`, `instagram.com/yeahjasi_santa`, `facebook.com/molo12coworkingspacebrindisi`, `instagram.com/molo12coworking_brindisi`, `facebook.com/brleantichestrade`, `facebook.com/legamidicomunita`, `facebook.com/sanbaocasadiquartiere`, `facebook.com/BrindisiWWF`, `instagram.com/wwf_brindisi`, `instagram.com/pop_perrino_brindisi`, `facebook.com/p/Il-Bene-Che-Ti-Voglio-100064852443797`, `facebook.com/associazioneilcurro`, `instagram.com/desteenazionebrindisi`, `facebook.com/desteenazionebrindisi` | **NEW 1 Eventi POV operatore**, **OLD Presidio contro la solitudine**: sono i canali più vivi e gli unici per le Case senza sito (Tuturano/Gala House, POP Perrino, Bozzano). Il documento chiede «aggiornamento da canali già in uso invece del doppio inserimento»: **non è realizzabile con i connettori di Onyx**. La via praticabile è il modulo di inserimento semplificato + il link al post nella scheda evento |

---

## Quello che non c'è (e cosa significa)

Non sono in tabella perché **non sono raggiungibili** da questo host: l'elenco è un risultato, non una
omissione — ognuno di questi è stato provato e ha un'alternativa che lo copre.

| Provato | Esito | Alternativa che lo copre |
|---|---|---|
| `www.asl.brindisi.it` (dominio storico ASL) | 000, timeout (DNS risolve) | `sanita.puglia.it/web/asl-brindisi` (200) |
| `www.comune.brindisi.it/urp` | **404** — è il bersaglio oggi in `fixtures/fonti_http.json` | `notizie/avvisi/` per gli avvisi; nessuna pagina URP dedicata esiste |
| `sportellotelematico.comune.brindisi.it`, `servizionline.comune.brindisi.it` | 000 (DNS) | `servizi.comune.brindisi.it/openweb/appuntamenti/` (200) |
| Albo pretorio del Comune (`albo-pretorio.php`, `/openweb/albo/`) | 404 / 403 | `servizi.comune.brindisi.it/openweb/trasparenza/` (200) |
| `prenotazionicie.interno.gov.it` | 000 | `cartaidentita.interno.gov.it` (200) |
| `www.arpa.puglia.it` (portale e pagina aria) | 000 | dataset ARPA su `dati.puglia.it` (200) |
| `www.caritasbrindisi.it` (DNS non risolve) | 000 | `diocesibrindisiostuni.it` — pagina Mensa della Carità (200); la Caritas diocesana non ha sito |
| `wwfbrindisi.altervista.org` (sito Minimus) | 403 (anti-bot) | `wwf.it/chi-siamo/.../wwf-brindisi/` (200) |
| `cisltarantobrindisi.it`, `aporti.it` | 403 / 000 (WAF) | `cafcisl.it` ricerca sedi (200); `cafpatronati.com` per la scheda sportello |
| `molo12brindisi.com` **home** | **500** (server error) | le pagine interne rispondono 200 (`/contattaci/`, `/coworking/`): si indicizza il deep link, non la home |
| Feed iCal di Case, rete e Comune | **nessuno esiste** (nessun `.ics` in sitemap, robots o home) | `fonti_http` (proposta) e `crea_evento` in chat: la via iCal è pronta ma senza sorgente |
| Feed RSS del Comune (`/feed/`) | 200 ma **canale vuoto** (nessun `<item>`) | non usabile come fonte eventi |
| Pagine dedicate per POP Perrino, Bozzano, Tuturano su `casediquartiere.it` | 404 (`/pop/`, `/bozzano/`, `/tuturano/`) | scheda nella home di `casediquartiere.it`; per Bozzano **nessun canale pubblico esiste** |
| `www.questure.poliziadistato.it` (qualsiasi pagina) | **DNS non risolve**; l'host senza `www` risponde 200 ma con un corpo `Accesso negato` (misurato con tre user-agent diversi e anche dal container dello shim: non è un filtro sul client) | `interno.gov.it` — pagina permesso di soggiorno (200, contenuto leggibile); la Questura resta da riprovare con il connettore `web` |
| Instagram, Facebook, WhatsApp, YouTube | 200 via curl ma **contenuto dietro login**: nessun connettore Onyx li legge | modulo di inserimento semplificato + link al post nella scheda (vedi Tabella B) |

**Tre buchi che restano aperti e riguardano il contenuto, non i link:**

1. **Bozzano non ha voce.** Il Centro di Aggregazione Bozzano — una delle 10 Case, con la gestione bar e il
   punto di facilitazione digitale — non ha sito, non ha social, non ha pagina sul Comune. Gli unici dati
   pubblici sono gli orari del punto di facilitazione sul sito del Consorzio BR1. Finché è così, la memoria
   di Bozzano si regge **solo** su inserimento manuale.
2. **Gli orari dei servizi sociali quasi mai sono pubblicati.** Mensa Caritas, Emporio, centri diurni
   comunali: le pagine descrivono il servizio ma non gli orari. La sorveglianza automatica non può coprirli:
   servono inserimento manuale e la data di aggiornamento in vista (affidabilità 1–2).
3. **Nessuna fonte pubblica per l'affluenza e per l'Attrezzoteca (NEW 3 e NEW 5).** Sono dati che esistono solo
   dentro la rete: nessun link li porta. Restano da costruire come dati interni (registrazione ingressi,
   inventario oggetti), e questo conferma che la distinzione del documento fra «dati automatizzabili» e «dati
   che richiedono lettura umana» non è teorica — è la forma del sistema.

---

## Appendice — Come queste due tabelle diventano righe nel database

Niente di questa appendice è stato applicato: è il **lavoro pronto**, da eseguire quando il TI verifica i
domini. Ogni riga è la traduzione diretta di una riga della Tabella A.

### A. Righe per `trasi.fonte` (allow-list di `cerca_web`)

Vincoli da rispettare, tutti già nel codice: `tipo_accesso` ∈ {`kb`,`drive`,`ical`,`http`,`osm_overpass`,`web`,`api`};
`livello_fiducia` ≥ 2 perché una fonte attiva sotto soglia sarebbe «in allow-list e scartata a ogni risposta»
(la verifica è in `db/tests/t_seed.sql`, O07); `attiva=true` **solo** dopo aver visto la pagina.

| `nome` | `url` (dominio che autorizza) | `tipo_accesso` | `autorita` | `livello_fiducia` | `attiva` | Nota |
|---|---|---|---|---|---|---|
| `Comune di Brindisi-3` | *(già presente)* `https://www.comune.brindisi.it` | `web` | Comune di Brindisi | 3 | true | autorizza l'intero albero: `/servizi/`, `/notizie/avvisi/`, uffici, luoghi, eventi **e il sottodominio** `servizi.comune.brindisi.it` (verificato eseguendo `_in_allowlist` dello shim). Non serve una seconda riga per il portale servizi |
| `ASL Brindisi-3` | **`https://www.sanita.puglia.it`** *(oggi: `https://www.asl.brindisi.it`)* | `web` | ASL della Provincia di Brindisi | 3 | true | ⚠️ **l'URL nel seed è morto** (000): la riga esiste in allow-list e non autorizza nulla. Le pagine ASL — CUP, consultori, CSM, SerD, esenzioni, distretti — vivono tutte su `sanita.puglia.it`: 18 delle righe di §A.1 dipendono da questa correzione |
| `Regione Puglia — welfare-3` | `https://www.regione.puglia.it` | `web` | Regione Puglia | 3 | true | *(riga già presente: copre già bandi e welfare)* |
| `INPS-3` | `https://www.inps.it` | `web` | INPS | 3 | true | autorizza per sottodominio `servizi2.inps.it` (allow-list per etichetta di dominio) |
| `Agenzia delle Entrate-3` | `https://www.agenziaentrate.gov.it` | `web` | Agenzia delle Entrate | 3 | true | |
| `Agenzia Entrate-Riscossione-3` | `https://www.agenziaentrateriscossione.gov.it` | `web` | Agenzia delle Entrate-Riscossione | 3 | true | |
| `Questura di Brindisi-3` | `https://questure.poliziadistato.it` | `web` | Ministero dell'Interno — Polizia di Stato | 3 | true | ⚠️ l'host risponde 200 con un corpo «Accesso negato»: **verificare** che SearXNG ne indicizzi il contenuto |
| `Ministero dell'Interno-3` | `https://www.interno.gov.it` | `web` | Ministero dell'Interno | 3 | true | copre immigrazione e asilo; autorizza anche `prefettura.interno.gov.it` |
| `Arpal Puglia-3` | `https://arpal.regione.puglia.it` | `web` | ARPAL — Regione Puglia | 3 | true | Centri per l'Impiego |
| `Casa di Quartiere — rete-3` | `https://www.casediquartiere.it` | `web` | Rete delle Case di Quartiere di Brindisi | 3 | true | sito di progetto gestito dal Comune: è la fonte con orari e contatti di tutte le Case |
| *(una riga per gestore)*: `Naukleros`, `Legami di Comunità`, `Il Bene Che Ti Voglio`, `The Qube`, `Molo 12` | `https://www.naukleros.com`, `https://www.legamidicomunita-br.it`, `https://www.ilbenechetivoglio.it`, `https://theqube.it`, `https://molo12brindisi.com` | `web` | l'ente gestore | 2 | false → true dopo verifica | sono gli ETS della rete: oggi nel seed sono le 10 righe `ETS: <Casa>` con `url` **NULL**, quindi non contribuiscono alcun dominio alla allow-list |
| `Consorzio Sociale ATS BR1-3` | `https://www.consorziosocialebr1.it` | `web` | Consorzio Sociale ATS BR1 | 3 | true | Ambito sociale e sportello immigrazione |
| `CSV Brindisi Lecce-2` | `https://www.csvbrindisilecce.it` | `web` | CSV Brindisi Lecce ETS | 2 | true | rete ETS e notizie del volontariato |
| `Diocesi Brindisi-Ostuni-2` | `https://www.diocesibrindisiostuni.it` | `web` | Arcidiocesi di Brindisi-Ostuni | 2 | true | parrocchie e Mensa della Carità (gli **orari** non sono pubblicati) |
| `Banco Alimentare Puglia-2` | `https://www.bancoalimentare.it` | `web` | Banco Alimentare della Puglia ETS | 2 | true | punti di distribuzione |
| `Croce Rossa Brindisi-2` | `https://gaia.cri.it` | `web` | Croce Rossa Italiana | 2 | true | anagrafica del Comitato di Brindisi |
| `CPIA Brindisi-2` | `https://www.cpiabrindisi.edu.it` | `web` | CPIA «Anna Lorenzetto» | 2 | true | istruzione adulti, alfabetizzazione |
| `CAF e patronati-2` | `https://www.acli.it`, `https://www.inca.it`, `https://www.cafcisl.it`, `https://caf.coldiretti.it` | `web` | patronati e CAF | 2 | false → true dopo verifica | le 2 righe `CAF ACLI/CISL Brindisi` già nel seed puntano alle home nazionali: **non contengono gli sportelli di Brindisi**, vanno sostituite o affiancate da queste |
| `Università e formazione-2` | `https://www.unisalento.it`, `https://www.mim.gov.it`, `https://itsaerospaziopuglia.tuttogare.it` | `web` | università, MIM, ITS | 2 | true | orientamento scolastico e universitario |
| `Poste Italiane-2` | `https://www.poste.it` | `web` | Poste Italiane | 2 | true | uffici postali e servizi online |
| `Identità digitale-3` | `https://identitadigitale.gov.it` | `web` | Dipartimento per la Trasformazione Digitale | 3 | true | SPID e CIE: è il primo passo dei servizi digitali |
| `CIE — Ministero dell'Interno-3` | `https://www.cartaidentita.interno.gov.it` | `web` | Ministero dell'Interno | 3 | true | richiesta e prenotazione CIE |
| `Siti dei gestori-2` | `https://sites.google.com` (Accademia degli Erranti), `https://percorsiconibambini.it` (POP Perrino), `https://www.angsa.it` (Dream), `https://www.cooperidano.it` | `web` | enti gestori e progetti | 2 | false → true dopo verifica | ⚠️ `sites.google.com` è un dominio **di piattaforma**: autorizzarlo apre a qualunque Google Site pubblico. Se il TI lo concede, va fatto sapendo cosa significa |
| `Servizi sociali Puglia-3` | `https://servizisocialipuglia.it` | `web` | Regione Puglia | 3 | true | registro regionale delle strutture socio-assistenziali. **Solo senza `www`**: con `www` il dominio non risponde |
| `OpenStreetMap/Overpass-2` | *(già presente)* `https://overpass.openstreetmap.fr/api/interpreter` | `osm_overpass` | OpenStreetMap contributors (ODbL) | 2 | true | verificato dal container dello shim |
| `Nominatim-2` | `https://nominatim.openstreetmap.org` | `api` | OpenStreetMap contributors (ODbL) | 2 | false | **dichiarato ma non implementato**: richiede lavoro nello shim, non è una riga di sola configurazione |
| `Open Data Puglia-2` | `https://dati.puglia.it` | `api` | Regione Puglia | 2 | false | idem: nessun flusso legge oggi `tipo_accesso='api'` |

### B. Bersagli per `flussi/fixtures/fonti_http.json` (sorveglianza → proposta)

Ogni bersaglio va aggiunto **con `attivo: false`** e acceso solo dopo che il selettore è stato individuato
sulla pagina vera: è la regola che il file stesso dichiara, ed è la ragione per cui non si accende «per
provare». Struttura pronta per i bersagli di §A.2:

```json
{
  "fonte": "Comune di Brindisi-3",
  "url": "https://www.comune.brindisi.it/amministrazione/unita_organizzativa/ufficio-anagrafe/",
  "selettore": "#orari",
  "entita": "luogo",
  "entita_id": 0,
  "campo": "orari",
  "casa": null,
  "attivo": false,
  "_nota": "Pagina verificata 200 il 16/09/2026. Da fare: individuare il blocco degli orari e sostituire '#orari' e l'id reale del luogo in memoria."
}
```

I tre bersagli che valgono l'accensione, in ordine di ritorno:

1. `https://www.sanita.puglia.it/web/asl-brindisi/cup` → `entita='luogo'`, `campo='orari'`: è l'orario che più
   spesso cambia e che più spesso il cittadino chiede.
2. `https://www.comune.brindisi.it/notizie/avvisi/` → `entita='scheda_servizio'`: gli avvisi sono la fonte
   naturale delle «opportunità» (contributi, avvisi pubblici con scadenza).
3. `https://www.casediquartiere.it/` → **un bersaglio per Casa**, con il selettore sulla scheda della singola
   Casa: è l'unico posto in cui gli orari di tutte e dieci sono pubblicati insieme, ed è il confronto diretto
   con la memoria locale.

### C. Ciò che va corretto comunque (indipendente dalle due tabelle)

| Dove | Cosa | Perché |
|---|---|---|
| `db/011_seed_fonti.sql` | `('ASL Brindisi-3', 'https://www.asl.brindisi.it', …)` | il dominio è morto (000): la fonte è in allow-list e non risolve nulla. Sostituire con `https://www.sanita.puglia.it` |
| `flussi/fixtures/fonti_http.json` | bersaglio su `https://www.comune.brindisi.it/urp` | **404 misurato**: il bersaglio è già `attivo:false`, ma un URL morto in un registro è una nota che mente. Sostituire con gli URL di §A.2 |
| `db/011_seed_fonti.sql` | righe `ETS: <Casa>` con `url` NULL | senza `url` non contribuiscono domini alla allow-list: i siti dei gestori restano invisibili a `cerca_web` finché non si valorizza l'URL (Tabella A.1, righe dei gestori) |
| `trasi.fonte` ↔ `fonte.tipo_accesso` | `api` e `http` sono nel vocabolario ma **nessun flusso li legge** | `http` è usato solo come sorveglianza (`fonti_http.py`); `api` non è implementato da nessuno. Se il TI inserisce una riga `api` aspettandosi che funzioni, non funzionerà: è una scelta da dichiarare, non un bug da scoprire |

