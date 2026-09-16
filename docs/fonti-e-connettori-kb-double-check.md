# Trasi — Fonti e connettori: secondo controllo

**Cosa è questo documento.** Un controllo indipendente su `docs/fonti-e-connettori-kb.md` (il censimento dei
131 link, commit `73cecce`, mergiato su `main` in `7d162e9`). Il primo censimento rispondeva alla domanda
«quale link serve a quale servizio»; questo risponde a tre domande diverse:

1. **I link reggono?** Ri-misurati tutti e 131, uno per uno, con metadati (title, canonical, redirect, corpo).
2. **Sono troppo specifici?** Sì, in parte: 22 link su 126 sono fragili o sottili. Per ogni ente esiste una
   **pagina-madre** che il primo documento non aveva — questa è la sezione che cambia il modo di usare la lista.
3. **Cosa manca del tutto?** Otto fonti intere che il primo censimento non aveva, e sei servizi di base per cui
   **nessuno pubblica nulla**.

**Metodo.** `curl -s -m 20 -o /dev/null -w '%{http_code} %{url_effective} %{content_type}' -A 'Mozilla/5.0 (X11; Linux x86_64)' -L <url>`,
più un secondo fetch per il conteggio del **testo visibile** e degli elementi elencati. Misure del 16/09/2026.
Quattro ricognizioni indipendenti hanno lavorato in parallelo; **ogni loro affermazione è stata ri-verificata**, e
dove la verifica le smentiva ho tenuto la misura, non il report (sezione «Errori trovati»).

**La regola di misura che il primo documento non aveva.** Un `200` non dice che la pagina contenga qualcosa:

| Segnale | Cosa significa | Quante volte |
|---|---|---|
| `200` con **corpo di blocco** | la richiesta è stata respinta, servita come pagina | 1 (`questure.poliziadistato.it`) |
| `200` con **articolo vuoto** | la pagina esiste nell'albero ma non ha contenuto: è un buco, non una fonte | 1 (`strutture-private-convenzionate`) |
| `200` con **solo guscio JavaScript** | senza browser la pagina è vuota | 2 (`RUNTS`, EsploraDati ISTAT) |
| `200` con **redirect a sé stesso** | il link «funziona» ma porta altrove | 6 (vedi §2) |
| `200` **senza `-L`** = link morto | il 200 arriva solo dal redirect | 1 (`ambitomesagne.it`, **errore grave**: §4) |
| `404` **camuffato** | le 404 di Liferay hanno lo stesso peso delle pagine vere (4,5 kB di testo, 90 `<li>`) | molte, ASL |

**Sul testo visibile: la trappola del menu.** Le pagine `sanita.puglia.it` portano lo **stesso** menu-mega e
banner-cookie su ogni pagina. Su `/consultori` il testo di pagina è 8.074 caratteri ma il **corpo dell'articolo è
1.837**. Misurare solo il totale sovrastima di **4–6 volte** e non distingue una pagina piena da una vuota: è
esattamente il modo in cui `strutture-private-convenzionate` sembra una fonte e non lo è. In questo documento do
sempre `pagina/corpo`.

---

## 1. La lista è troppo specifica: le pagine-madre che mancavano

Il problema che hai posto è reale. Il primo censimento aveva scelto il deep link «che risponde a quella domanda»
(utile per l'assistente) e **non** l'indice «da cui si vede tutto» (utile a chi configura e a chi sorveglia). Ecco
gli indici, per ente.

| Ente | Pagina-madre (la visione d'insieme) | Quanti elementi elenca | Perché batte i deep link | HTTP · testo pagina/corpo |
|---|---|---|---|---|
| **ASL Brindisi** | `https://www.sanita.puglia.it/web/asl-brindisi/assistenza-e-cura` | **24 servizi** | È **l'indice che mancava del tutto**: elenca in un colpo Consultori, ADI, Ospedali, Poliambulatori, Hospice, RSA pubblica, Invalidità, Malattie Rare, Ospedali di comunità, Centro Autismo, GAP, Caregiver, Assistenza Protesica. I 18 deep link ASL del primo documento stanno tutti sotto questo | 200 · 5.119/101 |
| **ASL Brindisi** | `https://www.sanita.puglia.it/web/asl-brindisi/mappa-del-sito` | **176 voci, 159 link** | L'indice **esaustivo**: include le voci fuori da «Assistenza e cura» (dipartimenti, distretti, albo, trasparenza). Da qui si enumera tutta l'azienda senza conoscerne la struttura | 200 · 6.927/0\* |
| **ASL — consultori** | `https://www.sanita.puglia.it/web/asl-brindisi/consultori` | **16 sedi su 2 pagine** | Il deep link del primo documento copriva **1** consultorio; questo ne copre 16, con indirizzo e telefono. ⚠️ **Serve la paginazione**: `?page=1` ne dà 12, `?page=2` i 4 mancanti (verificato: 12 + 4 = 16 distinti) | 200 · 8.074/1.837 |
| **ASL — distretti** | `https://www.sanita.puglia.it/web/asl-brindisi/distretti-socio-sanitari` | **4 distretti + allegati** | Collega i 4 DSS (`dss-n-1-brindisi`…): da qui si individua l'ufficio di competenza senza saperne il nome | 200 · 8.299/3.450 |
| **ASL — SerD** | `https://www.sanita.puglia.it/en/web/asl-brindisi/-/dipendenze-patologiche` | **6 SERT della provincia** | Il primo documento puntava al **singolo** SerT di Brindisi; questo elenca tutti e 6 con telefoni ed email. ⚠️ **Il `/en/` è obbligatorio per l'URL senza `/-/`, ma NON è una pagina in inglese** (vedi §3) | 200 · 7.042/2.529 |
| **ASL — poliambulatori** | `https://www.sanita.puglia.it/web/asl-brindisi/poliambulatori` | **12 poliambulatori** | Indice di tutte le sedi ambulatoriali della provincia | 200 · 5.845 |
| **ASL — invalidità** | `https://www.sanita.puglia.it/web/asl-brindisi/invalidita` | **8 commissioni** | Elenca le commissioni invalidi civili per sede: è il percorso del disagio che lo sportello vede più spesso | 200 · 5.258 |
| **ASL — ospedali** | `https://www.sanita.puglia.it/web/asl-brindisi/ospedali` | **3 presidi** | Di Summa-Perrino, Francavilla, Ostuni | 200 · 5.798/6.388 |
| **Regione Puglia — strutture sociali** | `https://www.sistema.puglia.it/portal/pls/portal/welfare.WLF_R_REG_ANZIANI.show` (+ `_MINORI`, `_DISABILI`, `_PROB_PSICO`) | 20 righe/pagina, **4 registri** | **È il registro ufficiale** (L.R. 19/2006), interrogabile **per comune**: dice quali strutture socio-assistenziali sono autorizzate nel brindisino. Il primo documento dava questa funzione a `servizisocialipuglia.it`, che **non è** il registro (vedi §4) | 200 · 3.156–5.566 |
| **Regione Puglia — i registri in un file** | `https://dati.puglia.it/ckan/dataset/bffa2d3d-c0b4-4fc9-a96c-7104a272ed38/resource/7aa651c7-b536-494e-861e-2adbcf798223/download/registri2023od.csv` | **4.923 righe · 43 colonne · 95 a Brindisi** | Lo stesso registro in **CSV scaricabile**, senza browser: 41 minori, 27 disabili, 19 anziani, 7 accesso al welfare, 1 problematiche sociali nel comune di Brindisi. È una fonte che si **ingerisce**, non che si consulta | 200 · CSV |
| **ATS BR4 (Mesagne)** | `https://www.ambitomesagne.it/ambito/` | **30 voci di menu, tutte di servizio** | Il primo documento dichiarava il BR4 irraggiungibile. **È raggiungibile** — serviva solo seguire il meta-refresh. Elenca mediazione linguistico-culturale, SAD, ADI, centro ascolto famiglie, contrasto alla violenza, P.I.P.P.I, Reddito di Dignità, buoni servizio anziani e disabili (vedi §4) | 200 · 7.226 |
| **Comune di Brindisi — luoghi** | `https://www.comune.brindisi.it/vivere-il-comune/luoghi/` | **40 schede** | Ogni scheda ha blocchi `#modalita-accesso`, `#indirizzo`, `#contatti` **e 7 hanno `#orario-pubblico`**: sono i selettori stabili per la sorveglianza, già pronti | 200 · 4.978 |
| **Comune di Brindisi — uffici** | `https://www.comune.brindisi.it/amministrazione/uffici/` | **28 unità** | Ogni unità ha `#sede-principale` e `#contatti` con telefono ed email. ⚠️ **Quasi nessuna ha gli orari**: la pagina URP (200, `#contatti`, tel 0831 229712) **non contiene la parola «orari»** | 200 · 6.423 |
| **Comune — servizi per categoria** | `https://www.comune.brindisi.it/servizi-categoria/salute-benessere-e-assistenza/` | 15 categorie, 72 link | La sezione sociale del Comune in una pagina: è la controparte comunale dell'indice ASL | 200 · 4.828 |
| **Comune — ufficio con orari** | `https://servizi.comune.brindisi.it/openweb/benefici/ufficio.php?tipo=U&id=60` | — | **L'unica pagina del Comune con gli orari dei Servizi Sociali** (lun–ven 8:30–13, gio 15–18, su appuntamento): non è sul sito istituzionale, è sul portale OpenWeb. Fonte trovata dalla ricognizione, verificata | 200 · HTML |
| **Regione — punti di facilitazione digitale** | `https://www.regione.puglia.it/web/trasformazione-digitale/punti-di-facilitazione-digitale/mappa-dei-punti` | **314 punti in Puglia, 7 a Brindisi** con orari | Copre interamente il servizio «facilitazione digitale e SPID», che il primo documento copriva con **zero** link. ⚠️ **La pagina è JS**: i dati veri stanno in un dataset CKAN scaricabile (sotto) | 200 · 2.134 (guscio) |
| **Regione — gli stessi punti in CSV** | `https://dati.puglia.it/ckan/dataset/b98b3c31-d861-4cab-b395-d51b5b917a5d/resource/eb1dba91-7152-4f8c-98d9-abfdb2b6d96b/download/punto-di-facilitazione-digitale.csv` | **310 righe, 100 % con orari** | Verificato riga per riga: 7 punti nel comune di Brindisi (Consorzio via Grazia Balsamo, ASL Di Summa, CPI via Cappuccini, ASL Sala Vaccinazioni, ASL Dalmazia, **Parco Buscicchio**, **Centro aggregazione via Spagna 16 = Bozzano**). Chiude il buco su Bozzano del primo documento | 200 · CSV |
| **AReSS Puglia** | `https://aress.regione.puglia.it/web/guest/aree-tematiche/equita-e-inclusione/osservatorio-regionale-delle-politiche-sociali` | 133 link, 116 voci | **Di AReSS il primo documento non aveva nulla.** L'ORPS monitora offerta e domanda dei servizi sociali regionali: è la fonte con cui si **leggono i bisogni** per il report alla PA | 200 · 5.481 |
| **Albo cooperative sociali** | `https://www.regione.puglia.it/web/albo-cooperative-sociali` | 299 cooperative in provincia di BR | ⚠️ **L'indice è utile, l'export NO**: l'endpoint DataTables dichiarato dalla ricognizione restituisce `text/html`, non JSON (vedi §4). L'export vero passa dal dataset CKAN dei Registri | 200 · HTML |
| **Procura di Brindisi — CAV** | `https://procura-brindisi.giustizia.it/cmsresources/cms/documents/CentriAntiViolenzaContattiUtili.pdf` | 4 CAV + 4 ATS + 16 consultori | **Un solo PDF che elenca i centri antiviolenza del circondario con enti gestori, telefoni, email e PEC**, più i servizi sociali dei 4 ambiti. Il primo documento dava questo servizio per «coperto» da `cerca_web`: non lo era | 200 · PDF |
| **1522 — mappatura nazionale** | `https://www.1522.eu/mappatura-1522/` | **423 centri, di cui a Brindisi** | L'unica pagina-indice con **orari** dei centri antiviolenza, incluse le schede brindisine (es. «Ricomincio da me», via Giulio Cesare 22/t, 800688791 + 3501801953, con orari per giorno) | 200 · 139.309 |
| **CSV — sportello di Brindisi** | `https://www.csvbrindisilecce.it/contatti-brindisi/` | 1 sportello con orari | Via Spagna 16 (dentro il **Centro Anziani Bozzano**), 0831 515800, lun–ven 9–13:30 / 15:30–19:30. È il contatto della rete ETS più vicino alla Casa di Bozzano | 200 · 2.072 |
| **Diocesi — Caritas** | `https://www.diocesibrindisiostuni.it/caritas/` | — | La pagina Caritas diocesana (il primo documento citava solo la Mensa). ⚠️ **Gli orari della mensa restano non pubblicati** | 200 · 3.159 |
| **Regione — terzo settore** | `https://www.regione.puglia.it/web/welfare-diritti-e-cittadinanza/terzo-settore` | — | Pagina regionale sul terzo settore: cornice per il RUNTS | 200 · 3.780 |

\* `mappa-del-sito` non ha un blocco `journal-content-article`: i suoi 176 elementi sono nell'albero di navigazione,
ed è lì che vive l'utilità. Non è un difetto della pagina, è un difetto del selettore.

**Come cambia l'uso della lista.** Con gli indici, il lavoro di configurazione si fa **in due passi**: prima si
indicizza (o si sorveglia) **l'indice**, poi si scende ai deep link solo per i servizi che hanno orari che cambiano.
Sorvegliare 18 pagine ASL una per una è il modo di avere 18 allerte scollegate; sorvegliare `assistenza-e-cura` più
`consultori` (2 pagine) più `dipendenze-patologiche` è il modo di avere tre allerte che dicono «è cambiata l'offerta
ASL» — che è la cosa che l'AT deve sapere.

---

## 2. Fragilità: 22 link su 126 sono «troppo specifici»

Classificazione misurata (criteri: id numerici o `?query` nell'URL, testo visibile < 1.200 caratteri, corpo di
blocco, redirect). **22 voci grezze su 126** — che sono **17 link distinti** (alcune compaiono due volte nella
misura: `nominatim` con e senza barra finale, `angsa` e `theqube` con e senza `www`, `naukleros` come voce di
Tabella A e come URL di allow-list). Ecco i 17:

| Link | Problema misurato | Cosa fare |
|---|---|---|
| `nominatim.openstreetmap.org/` | 14 caratteri di testo: **non è una pagina, è un endpoint** con redirect a `/ui/search.html` | non è una fonte consultabile: è un'API. Se serve la geocodifica, va dietro uno strumento (vedi il primo documento, §A.4) |
| `sites.google.com/view/accademiadeglierranti/home` | il link nudo `sites.google.com` **redirige a login Google**; 1.111 caratteri | linkare **sempre** il path completo. Autorizzare il dominio `sites.google.com` in allow-list è una decisione, non un dettaglio: apre a qualunque Google Site pubblico |
| `naukleros.com` | **23 caratteri** di testo: pagina resa in JavaScript | il deep link `/san-bao-casa-di-quartiere-la-rosa` ha 47 caratteri: **peggio**. Serve il connettore `web` (guida un browser vero), non `cerca_web` |
| `servizi.comune.brindisi.it` e `.../scegli.php` | 117 e 530 caratteri: gusci che chiedono JavaScript («Per la completa fruizione del sito si devono abilitare i JavaScript») | ⚠️ **un connettore `web` testuale non ci cava nulla**. Verificato: il testo utile c'è solo a browser acceso |
| `esploradati.istat.it/` | 106 caratteri, redirect a `/databrowser/`, che è **in errore** («An error occurred while contacting the server»). L'API SDMX è **irraggiungibile** (4 varianti provate, tutte in timeout) | ⚠️ **sostituire** con `demo.istat.it` (vedi §3) |
| `gaia.cri.it/...` | 726 caratteri | pagina snella ma corretta; da tenere come dettaglio, non come indice |
| `posta.it/servizi-online.html` | **redirige alla home** (200 ma inutile) | sostituire con `poste.it/uffici-postali/index.html` (funziona) |
| `istat.it/it/cittadini` | redirige a un **comunicato stampa** su «cittadini e giustizia civile» | ⚠️ **sostituire**: il link non porta dove diceva. Usare `istat.it/dati/banche-dati/` (l'indice delle 12 banche dati) |
| `interno.gov.it` (senza path) | redirige a `/it` | usare il deep link `/it/temi/immigrazione-e-asilo/permesso-di-soggiorno` (200, contenuto leggibile) |
| `agnziaentrate.gov.it` (nudo) | redirige a `/portale/` | usare `/portale/cittadini` |
| `angsa.it` | redirige a `https://angsa.it/` (cade il `www`) | entrambi funzionano; preferire la forma che non redirige |
| `theqube.it` | redirige a `www.theqube.it` | entrambi funzionano |
| `comune.brindisi.it/web/suap/` | redirige a `/documento_pubblico/suap-edilizia-produttiva/` | ⚠️ il primo documento dava il primo URL: **il secondo è la destinazione reale** |
| `sanita.puglia.it/.../ser-t-brindisi?ids=548992` | `?ids=548992` è un id opaco che **sparisce nel redirect** verso `/en/`, e **porta ai 6 SERT, non al SerT di Brindisi** | sostituire con l'indice `/en/web/asl-brindisi/-/dipendenze-patologiche` |
| `comune.brindisi.it/wp-sitemap.xml` | 991 caratteri: è un `<sitemapindex>`, contiene 21 riferimenti a file XML, **non pagine** | non è una fonte: è un elenco di elenchi (vedi §3) |
| `overpass-api.de` | 406 | già dichiarato non usabile: confermato |
| `molo12brindisi.com/contattaci/` | **500 il 16/09 alle 16:55**, era 200 poche ore prima | ⚠️ **il sito è instabile**: non mettere in sorveglianza una pagina che va e viene senza segnalarlo (falso allarme notturno) |

**Il caso che vale da solo.** `molo12brindisi.com` è passato da 200 a **500** in poche ore. È la prova concreta che
la **sorveglianza notturna di un sito dei gestori** produce falsi allarmi: se `fonti_http` avesse in registro quella
pagina, stanotte l'AT riceverebbe «fonte in errore» per un guasto di hosting che non lo riguarda. La conseguenza
operativa è nel primo documento e qui si rafforza: **si sorvegliano le pagine istituzionali stabili, non i siti
degli ETS**.

---

## 3. Cosa manca e va aggiunto (otto fonti intere)

### a. I dati: il percorso automatico esiste, e non era noto

| Fonte nuova | Cosa contiene (misurato) | Perché conta |
|---|---|---|
| **CKAN Puglia** — `https://dati.puglia.it/ckan/api/3/action/package_search?q=brindisi&rows=1` | CKAN 2.9.5, **2.045 dataset** (`package_list` → 2.033 elementi). ⚠️ **la radice `/api/3/action/` è 404: il percorso è sotto `/ckan/`** | Il primo documento marcava `dati.puglia.it` come «`api` — dichiarato, non implementato». **Ora è implementabile con la sola correzione del percorso.** Verificato: `package_search` → 15 dataset su «brindisi»; `datastore_search` con `filters` → **95 record con `COMUNE_SEDE_OP=Brindisi`** |
| **CKAN IPRES** — `http://www.opendataipres.it/api/3/action/package_search?q=&rows=1` | **51 dataset** (13 temi), tutti con dettaglio comunale | **Fonte intera assente dal primo documento.** Copre redditi IRPEF per comune (2014–2024), occupati, disoccupazione, **Indice di Fragilità Comunale** (12 indicatori), stranieri, bilancio demografico. ⚠️ **trappola verificata**: `package_search?q=brindisi` → **count=0**; IPRES non indicizza i nomi dei comuni, che stanno *dentro* i CSV. Chi cerca «Brindisi» conclude che il dato manca: falso |
| **ISTAT Demo** — `https://demo.istat.it/data/posas/POSAS_2026_it_074_Brindisi.zip` | ZIP verificato: `POSAS_2026_it_074_Brindisi.csv`, **2.043 righe** (popolazione per età e sesso al 1/1/2026, provincia di Brindisi). Pattern stabile: `demo.istat.it/data/<indagine>/<INDAGINE>_<anno>_it_074_Brindisi.zip` | ⚠️ **sostituisce** EsploraDati, che è in errore. `strasa` per gli stranieri, `d7b` per il bilancio demografico comunale |
| **Registri socio-assistenziali via API** — `https://dati.puglia.it/ckan/api/3/action/datastore_search?resource_id=7aa651c7-b536-494e-861e-2adbcf798223&filters=%7B%22COMUNE_SEDE_OP%22%3A%22Brindisi%22%7D` | **95 record** dei registri del comune di Brindisi, interrogabili via API (verificato: `total=95`) | Il registro regionale come **servizio interrogabile**: l'Osservatorio filtra per comune e tipologia senza scaricare il CSV |
| **CKAN nazionale (AgID)** — `https://www.dati.gov.it/opendata/api/3/action/package_search?q=brindisi&rows=1` | **22 dataset** con «brindisi», fra cui **OpenCoesione** (dove vanno i fondi di coesione) | ⚠️ **anche qui la radice `/api/` è 404**: il percorso è `/opendata/api/` |
| **ISTAT — indice banche dati** — `https://www.istat.it/dati/banche-dati/` | Indice di **12 banche dati**: IstatData, Serie storiche, Demo, **Disabilità in cifre**, Censimento permanente Non profit, Atlante statistico dei comuni, 8milaCensus | Fonti intere non citate: «Disabilità in cifre» e il censimento non profit sono esattamente i due buchi del primo documento |

**Verificato e confermato non-utilizzabile** (non è una svista, è un esito): API SDMX ISTAT (timeout su 4 varianti);
`datastore_search_sql` su CKAN Puglia (**bloccato dal WAF**, categoria SQL injection → le aggregazioni vanno fatte
lato client); parametro `fl=` su CKAN Puglia (**HTTP 500**); databrowser EsploraDati (guscio in errore); portale
`arpa.puglia.it` (**catena TLS non verificabile**: `curl` senza `-k` → 000, con `-k` → 200; il certificato è
`*.arpa.puglia.it`, `O=ARPA PUGLIA`, emesso da `Actalis Organization Validated TLS Server RSA CA 2025` — il server
non invia la catena intermedia, quindi i dati ARPA si prendono da CKAN, non dal portale).

### b. I registri: il terzo settore in blocco

| Fonte nuova | Cosa contiene | Nota |
|---|---|---|
| **RUNTS — lista enti** `https://servizi.lavoro.gov.it/runts/it-it/Lista-enti` | **7 file scaricabili**, tutti datati 16/09/2026. **Ho scaricato l'export Excel**: `20260916_iscritti_v1.1.xlsx`, **152.626 righe** (12,8 MB), 10 colonne | ⚠️ **i link sono postback ASP.NET, non URL**: servono i campi `__VIEWSTATE/__VIEWSTATEGENERATOR/__EVENTVALIDATION`. Verificato: il POST restituisce il file. **Filtro misurato: 890 enti con sede legale in provincia di BR, di cui 195 nel comune di Brindisi** (APS 72.556 in tutta Italia, ODV 39.176, Imprese sociali 22.012) |
| **Limite del RUNTS, misurato** | Colonne effettive: codice fiscale, repertorio, denominazione, sezione, nome del legale rappresentante, rete, **comune e provincia della sede legale**, 5x1000, data iscrizione | ⚠️ **non contiene indirizzo, telefono né email**. Serve come **censimento** («quanti enti ci sono a Brindisi»), non come fonte di orari e contatti. E la ricerca interattiva è **SPA JS**: non interrogabile senza browser |
| **Registro strutture socio-assistenziali** `https://www.sistema.puglia.it/portal/pls/portal/welfare.WLF_R_REG_ANZIANI.show` | 4 registri (anziani, minori, disabili, problematiche psico-sociali), **interrogabili per comune** | È il registro **ufficiale**, L.R. 19/2006. Sostituisce l'attribuzione data dal primo documento a `servizisocialipuglia.it` |
| **Strutture socio-sanitarie autorizzate** `https://dati.puglia.it/ckan/api/3/action/datastore_search?resource_id=3fdec20c-f92d-459c-b48b-96ec96e65f06&q=Brindisi` | **8 strutture nel comune di Brindisi** con setting, ASL, comune, distretto | Verificato: 2398 B, `total=8`. Copre RSA e centri diurni con dati strutturati |

### c. Le fonti che restano fuori uso, per scelta

`pugliasociale.regione.puglia.it` → **18 caratteri di testo**: il vecchio portale è un guscio, la funzione è
passata all'ORPS di AReSS. `servizisocialipuglia.it` → si **auto-dichiara** «Archivio informativo indipendente ·
Non è un sito ufficiale della Regione Puglia», sitemap di 31 URL, la pagina «Brindisi» elenca 8 voci di cui **4
fuori provincia**. `www.arpa.puglia.it` → certificato non verificabile. Ambiti BR2 e BR3 → **nessun dominio esiste**
(sei host provati, tutti DNS-fail).

---

## 4. Errori trovati (nel primo documento e nelle ricognizioni)

Il secondo controllo serve anche a questo: dichiarare dove si è sbagliato. **Sei correzioni**, di cui **due gravi**
e introdotte dalle ricognizioni, non dal primo documento.

| # | Chi | Cosa era affermato | Cosa dice la misura | Gravità |
|---|---|---|---|---|
| 1 | ricognizione → me | «Le pagine ASL `/en/…` sono **in inglese**» (conteggio lessicale `it/en`: 17/31) | **Falso.** `/en/web/asl-brindisi/-/dipendenze-patologiche` contiene «Il Servizio per le Dipendenze Patologiche svolge le attività…» in **italiano**, identico alla variante `/web/` (2.529 caratteri di corpo entrambi). Il conteggio dello scout misurava il **menu** inglese, non il corpo. **Le 6 righe `/en/` del primo documento sono corrette e non vanno cambiate** | grave (avrebbe fatto riscrivere 6 righe buone) |
| 2 | ricognizione → me | «ATS BR4 (`ambitomesagne.it`) è **irraggiungibile**: 000 / 301-loop» | **Falso.** `https://www.ambitomesagne.it/` risponde **200** con 84 byte di meta-refresh verso `/ambito/`, che risponde **200 con 86.645 byte e 7.226 caratteri di testo**. ⚠️ **L'errore nasce dal metodo**: con `curl -L` il fetch **non segue un meta-refresh** (non è un redirect HTTP) e restituisce i body vuoto da 84 byte. Chi misura solo con `-L` e vede `size_download: 0` conclude «non raggiungibile». Il BR4 pubblica **tutti** i servizi dell'ambito, inclusi mediazione linguistico-culturale e contrasto alla violenza | grave (dichiarava un buco che non esiste: 30 pagine di servizio perse) |
| 3 | ricognizione → me | Albo cooperative sociali: «endpoint JSON, **299 cooperative in provincia di BR**» | **Non riproducibile.** Con parametri DataTables e con header AJAX la risposta resta `text/html` (122 kB). Il `iTotalRecords=299` non è stato ritrovato in nessuna delle 4 combinazioni provate. **Va trattato come dato non verificato**, non come fonte. L'export delle cooperative passa dal dataset CKAN dei Registri | media |
| 4 | ricognizione → me | «`esploradati.istat.it` → sostituire con `demo.istat.it`» | **Confermato** (SDMX in timeout, databrowser in errore) — è la correzione 5 sotto, la tengo | — |
| 5 | **mio, primo documento** | `dati.puglia.it` e `esploradati.istat.it` etichettati entrambi «`api` — dichiarato, non implementato» | **Da scindere.** `dati.puglia.it` **è implementabile oggi** (percorso `/ckan/`, verificato con 95 record). `esploradati.istat.it` **non lo è**: va sostituito da `demo.istat.it` | media |
| 6 | **mio, primo documento** | `servizisocialipuglia.it` citato come «Registro regionale delle strutture e socio-assistenziali autorizzate»; `consorziosocialebr1.it` citato come pagina «servizi» | **Impreciso.** Il primo si auto-dichiara archivio indipendente non ufficiale e la sua pagina «Brindisi» è per metà fuori provincia; il secondo **non ha una pagina servizi** (la voce esiste su `/sample-page/servizi/`, la URL di default di WordPress, mai rinominata — 1.297 caratteri). Il registro vero è su `sistema.puglia.it` | media |

**Una correzione che ho già fatto al primo documento, e che il controllo conferma**: avevo scritto che
`servizi.comune.brindisi.it` richiede una riga `fonte` propria. Falso — l'allow-list confronta per etichetta di
dominio, e `comune.brindisi.it` autorizza già i sottodomini. Verificato eseguendo `_in_allowlist`.

**Un errore di metodo, da non ripetere.** Un `200` con `-L` non prova che un link sia vivo: `ambitomesagne.it`
risponde 200 sia senza sia con `-L` **sulla root**, ma il body sono 84 byte di meta-refresh. La regola giusta è
quella che ho usato qui: **misurare anche il testo visibile**, e se è ~0 guardare il contenuto, non il codice.

---

## 5. I buchi che restano: sei servizi per cui nessuno pubblica nulla

Metodo incrociato: i **95 record con sede operativa nel comune di Brindisi** del registro regionale (per parola
chiave in `TIPOLOGIA`, `DENOMINAZIONE_SEDE_OP`, `DENOMINAZIONE_TITOLARE`) + le pagine-indice ASL + Comune, CSV,
Diocesi, Banco Alimentare + URL diretti provati a mano.

| Servizio di base | Esito | Cosa esiste | Cosa manca |
|---|---|---|---|
| **Distribuzione abbigliamento** | **assente totale** | Nulla: 0 record nel registro (né «vestiario» né «abbigliamento»), nessun emporio con pagina. Il Banco Alimentare è solo alimentare | tutto |
| **Dormitorio / emergenza abitativa** | **assente nel comune** | Il progetto «Stazione di Posta» esiste (4 ATS) ma **senza pagina di servizio**. Il registro copre strutture *autorizzate*: l'accoglienza notturna non vi rientra. In provincia esistono comunità alloggio (Oria, Latiano, Galatina) | un dormitorio maschile a Brindisi: **non compare in nessuna fonte pubblica** |
| **Sportello immigrazione** | **nessuna pagina di servizio** | Solo l'archivio di categoria del blog BR1, con i dati (via Carmine 11, 348 7014331) **dentro i post**. Sul lato sanitario la mediazione FAMI 5.0 esiste ma senza pagina (`/sportello-immigrazione` = 404). ⚠️ **Il BR4 invece ha una pagina vera** per la mediazione linguistico-culturale: il servizio esiste, ma la pagina del BR1 no | una scheda con orari |
| **Salute mentale (CSM)** | **indice inesistente** | `/salute-mentale` = 404, `/dipartimento-di-salute-mentale` = 404. `/dipartimenti` dichiara **«PAGINA IN COSTRUZIONE»** e nomina solo il direttore. Esistono schede di **singoli** CSM (es. DSS1), cioè il dettaglio senza l'indice | l'elenco dei CSM della provincia |
| **Centro diurno anziani e disabili** | **nessun indice cittadino** | Il registro ha **1** centro socio-educativo diurno a Brindisi ed è per **minori**. Per anziani/disabili: solo i buoni servizio BR1, che rimandano a centri esterni senza elencarli. Le 8 strutture socio-sanitarie del comune sono l'aggancio parziale | l'elenco dei centri diurni accessibili |
| **Sportello antiviolenza** | **pagina di servizio assente** | Il registro attesta **2 servizi + 1 casa rifugio** a Brindisi (fra cui «Crisalide» del Comune). Le fonti con orari e contatti sono la **mappa 1522** e il **PDF della Procura** — entrambe di soggetti terzi, non della rete | una pagina della rete o del Comune |

**Due buchi sono di estrazione, non di esistenza — e si chiudono con una riga di configurazione:**

- **Consultori**: 16 sedi su **2 pagine** (`?page=1` → 12, `?page=2` → 4, verificato: 16 distinte). Il selettore di
  sorveglianza deve coprire entrambe.
- **SerD/SERT**: 6 strutture raggiungibili **solo** via `/en/web/…/-/dipendenze-patologiche` — e la pagina è in
  italiano (correzione 1). La variante italiana senza `/-/` è 404.

**Un buco strutturale che non si chiude con web**: gli **ambiti BR2 (Fasano) e BR3 (Francavilla)** non hanno alcun
dominio (sei host provati, tutti DNS-fail), e i loro comuni capofila restituiscono 404 su `/servizi-sociali`. Per
quei due territori **non esiste** una pagina-indice: il Portierato non può sapere cosa eroga l'ambito vicino.

**Conclusione operativa sui buchi.** Per abbigliamento, dormitorio, sportello immigrazione BR1, salute mentale e
centro diurni **non c'è un link da trovare: il dato non è pubblicato da nessuno.** Sono dati che devono entrare
dalla rete (voce dell'operatore, scheda della Casa) o essere chiesti alla PA come richiesta formale. Continuare a
cercarli sul web è il modo di consumare tempo per non trovare nulla: la risposta corretta è la **proposta di
modifica** con cui l'operatore scrive in memoria ciò che sa, e la **segnalazione al Comune** che quel dato manca.

---

## 6. Quadro finale: la lista, riorganizzata per tipo

| Tipo di fonte | Quante | Esempi | Connettore giusto |
|---|---|---|---|
| **Indici / pagine-madre** | 23 (§1) | `assistenza-e-cura`, `mappa-del-sito`, `luoghi/`, `uffici/`, `welfare` | `cerca_web` (consultazione) o `web` (indicizzazione) |
| **Deep link con orari che cambiano** | 8 (§A.2 del primo doc) | `cup`, `notizie/avvisi/`, `ufficio-anagrafe` | `fonti_http` → **proposta**, mai scrittura |
| **Dataset scaricabili** | 7 (§3a) | registri (95 righe a Brindisi), punti facilitazione (310 righe), POSAS/STRASA Brindisi | serve uno **script di ingestione**: `tipo_accesso='api'` esiste ma **nessun flusso lo legge** |
| **Registri consultabili a mano** | 4 (§3b) | RUNTS (152.626 righe, export via postback), registri regionali, albo cooperative | umano + eventuale export periodico |
| **PDF ufficiali** | 3 | Carta dei servizi ASL, contatti CAV della Procura, elenco soci CSV | `file` o scaricamento manuale |
| **Social** | 15 profili | Facebook/Instagram delle Case | **nessun connettore** (nessuno scraping) |
| **Buchi: nulla da linkare** | 6 servizi (§5) | abbigliamento, dormitorio, CSM, centri diurni… | proposta in chat + segnalazione alla PA |

---

## 7. Nota di confine: il lavoro che sta correndo accanto a questo documento

**Cosa è successo.** Mentre questo controllo era in corso, un'altra sessione ha **implementato a valle** di
`docs/fonti-e-connettori-kb.md`: ha creato `db/013_fonti_kb.sql` (10 righe di allow-list), modificato
`db/011_seed_fonti.sql`, `db/apply.sh` e `flussi/fixtures/fonti_http.json`. La divisione è stata decisa dall'utente
(«non verificare tutti i domini, ho avviato un'altra verifica in un'altra sessione»): **io verifico, quella
implementa**. Nessuna duplicazione di obiettivo.

**Due cose da sapere, perché sono già state fatte e non vanno disfatte.**

1. **`ASL Brindisi-3` è stato corretto**: da `https://www.asl.brindisi.it` (morto, 000) a
   `https://sanita.puglia.it`. È esattamente la correzione n. 5 di questo documento, ed è **già applicata** —
   verificato a DB: `SELECT url FROM trasi.fonte WHERE nome='ASL Brindisi-3'` → `https://sanita.puglia.it`.
   Insieme a `Questura di Brindisi-3`, ridotto al dominio nudo (`questure.poliziadistato.it`): in allow-list l'URL
   è **il dominio che autorizza**, non la pagina da leggere, e il deep link avrebbe autorizzato un host solo.
2. **La migrazione non è ancora applicata al database**: `db/013_fonti_kb.sql` esiste come file non tracciato. Il DB
   live ha **18 fonti attive** e i bersagli di sorveglianza attivi **non hanno ancora girato**.

**Due problemi misurati nei bersagli di sorveglianza** (in `flussi/fixtures/fonti_http.json`), da correggere prima
dell'accensione:

| Problema | Misura | Conseguenza |
|---|---|---|
| **`entita_id` non corrisponde alla pagina** | la fixture «Anagrafe» punta a `entita_id=16` con nota «è Comune di Brindisi — URP», ma **il 16 a DB è `Comune di Brindisi — URP`** mentre la pagina sorvegliata è l'**Anagrafe**; il 17 è `ASL Brindisi — Distretto socio-sanitario` (fonte OSM), non il CUP | una variazione della pagina Anagrafe proporrebbe una modifica **all'URP**: la proposta arriverebbe all'AT su un'entità sbagliata, con `diff` credibile — il tipo di errore che nessuno contesta in approvazione perché *sembra* giusto |
| **Il luogo 17 ha ancora la fonte morta** | `luogo.id=17` («ASL Brindisi — Distretto socio-sanitario») ha `url = https://www.asl.brindisi.it` e `fonte_id=6` | il seed ha corretto la **fonte**, non il **luogo**: la scheda che il cittadino legge continua a puntare al dominio morto |

**Un terzo effetto, non un errore ma un costo**: `v_flusso_coerenza_fonti` elenca come **`fonte_silente` tutte e 18
le fonti attive**, perché nessuna ha ancora un `fonte_run` (verificato: `SELECT voce, count(*) … GROUP BY 1` →
`fonte_silente | 18`). L'identità AT **esiste** (`v_flusso_destinatari`: `at → rete@trasi.local`, 2 righe), quindi
`alert.py` **non** fallisce: manda un messaggio che dice *«18 fonti silenti»*. È corretto per il codice — una fonte
attiva che non ha mai girato è, letteralmente, silente — ma **la prima notte dopo l'applicazione l'AT riceverà un
avviso con 18 voci che non segnalano alcun guasto**. Due modi di evitarlo: escludere dalla voce `fonte_silente` le
fonti senza alcun `fonte_run` (mai girate ≠ smesse di girare), oppure accettare il primo avviso come rumore di
accensione sapendo cos'è. La prima è preferibile: un allarme che parte con 18 voci il primo giorno è un allarme che
si impara a ignorare.

**I selettori sono verificati, e li ho ri-misurati io con l'estrattore reale** (`.card-body`, `html.parser` di
`fonti_http.py`, non un mio surrogato):

| Bersaglio | Selettore | Testo estratto | Esito |
|---|---|---|---|
| ASL CUP | `.card-body` | **1.692 caratteri** («Numero Verde Prenotazioni, 800 888 388, Cup Brindisi…») | ✅ corretto |
| Comune Anagrafe | `.card-body` | 893 caratteri (telefoni dei referenti) | ⚠️ **estrae i contatti, non gli orari**: la pagina Anagrafe **non contiene un blocco orari** (`#orario-pubblico` c'è solo su 7 pagine su 52, tutte luoghi culturali). Il bersaglio sorveglia «i contatti cambiano», non «gli orari cambiano» |
| Comune avvisi / eventi | `.journal-content-article` | **0 caratteri** | ⚠️ correttamente `attivo: false` — e la nota lo dichiara |

**La raccomandazione che porto a questa sessione**: i due bersagli `attivo: true` vanno spenti finché `entita_id`
non è allineato all'entità che la pagina descrive davvero, e il terzo (`.journal-content-article` su avvisi/eventi,
0 caratteri) va lasciato com'è: `attivo: false` con la nota è la forma giusta — il difetto non è il selettore
mancante, è il fatto che un selettore non misurato sarebbe passato per misurato.

---

**Tre azioni che valgono più di qualunque altro link**, e che il secondo controllo porta a dire con certezza:

1. **Sostituire `esploradati.istat.it` con `demo.istat.it`** e **correggere il percorso CKAN** in
   `/ckan/api/3/action/`: sono le due righe che accendono la parte «dati» dell'Osservatorio.
2. **Sorvegliare gli indici, non i dettagli**: `assistenza-e-cura` + `consultori?page=1|2` +
   `dipendenze-patologiche` coprono l'offerta ASL; `luoghi/` e `uffici/` (con i selettori `#indirizzo`,
   `#contatti`, `#orario-pubblico` già misurati) coprono il Comune.
3. **Non sorvegliare i siti degli ETS**: `molo12brindisi.com` è passato da 200 a 500 in poche ore. Un allarme
   notturno su un hosting instabile insegna a ignorare gli allarmi.

