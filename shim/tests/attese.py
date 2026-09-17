"""Attese indipendenti sul contratto congelato (gate V-09) e sulle costanti condivise dai test.

Queste costanti sono **duplicate di proposito** rispetto a `shim/openapi.yaml` e al codice: i test confrontano il
documento con un'attesa scritta a mano, invece di rileggere la stessa fonte e confermare sé stessi. Se il contratto
cambia senza una decisione, questi test falliscono.
"""

# Le operazioni congelate: `operationId`, metodo HTTP, percorso. Decisa l'aggiunta di `crea_evento` (scrittura
# diretta dell'evento da parte dell'operatore-gestore, opzione A approvata dal progetto).
OPERAZIONI_ATTESE: tuple[tuple[str, str, str], ...] = (
    ("cerca_luogo", "get", "/cerca_luogo"),
    ("eventi_oggi", "get", "/eventi_oggi"),
    ("vicino_a", "get", "/vicino_a"),
    ("registra_richiesta", "post", "/registra_richiesta"),
    ("crea_evento", "post", "/eventi"),
    # La scrittura diretta della propria Casa (scheda, opportunità, orari): sostituisce i cinque tipi
    # di proposta che restavano in un vicolo cieco (operatore e gestore condividono un solo accesso per
    # Casa, quindi nessuno poteva approvarli). Specifica del gruppo Processi, 2026-09-17.
    ("salva_dato", "post", "/salva_dato"),
    ("proponi_modifica", "post", "/proponi_modifica"),
    ("approva_proposta", "post", "/approva_proposta"),
    ("biglietto", "get", "/biglietto"),
    ("oggi", "get", "/oggi"),
    # Le statistiche mensili delle richieste (v_report_mensile, k-anonimato): la lettura aggregata
    # che la chat non aveva — l'assistente non poteva rispondere a «quante richieste quest'anno?».
    ("statistiche", "get", "/statistiche"),
    ("cerca_web", "get", "/cerca_web"),
    # La scheda !NEW 5 (attrezzoteca) entra nel contratto: ricerca inventario, prenotazione anticipata
    # (con conflitti dichiarati in ritorno, V6), spostamento con conferma della ricevente, statistiche
    # d'uso. La scheda !NEW 5 dei dialoghi di servizio, 2026-09-17.
    ("attrezzoteca", "get", "/attrezzoteca"),
    ("prenota_oggetto", "post", "/prenota"),
    ("registra_movimento", "post", "/movimento"),
    ("conferma_movimento", "post", "/movimento/{movimento_id}/conferma"),
    ("uso_oggetti", "get", "/uso_oggetti"),
)

# L'unico URL ammesso in `servers`, con il segnaposto che Onyx sostituisce lato server.
URL_SERVER_ATTESO = "http://shim:8000/v1/u/USER_EMAIL"

# Prefisso di montaggio delle operazioni nell'applicazione (derivato dall'URL sopra, col segnaposto come parametro).
PREFISSO_PATH_ATTESO = "/v1/u/{email}"

# Percorso del sorgente Onyx che definisce il validatore usato per registrare il tool custom (B2-ONX-04).
RADICE_ONYX = "/opt/onyx/backend"

# Le tre identità di prova del seed `db/010_seed_case.sql`. L'operatore di San Bao è il caso usato da US-01 e da
# ogni criterio di done di B3; `rete` è il ruolo AT/AQ, senza Casa; la terza serve al 403.
EMAIL_OP_SANBAO = "op.san-bao@trasi.local"
EMAIL_OP_BOZZANO = "op.bozzano@trasi.local"
EMAIL_RETE = "rete@trasi.local"
EMAIL_SCONOSCIUTA = "nessuno@trasi.local"
# Il TI: identità **attiva** con un utente Onyx, il cui ruolo DB `ti` non è però assumibile da `shim_rw`
# (`db/000_roles.sql` concede le 10 Case più `rete`, e revoca `ti` di proposito). Il caso serviva a un test:
# senza, il difetto si presentava come 500 su ogni endpoint per quell'unica identità.
EMAIL_TI = "ti@trasi.local"

# Dettagli d'errore del contratto (§9.1), ripetuti qui per non leggerli dal codice che li produce.
DETAIL_IDENTITA_NON_RICONOSCIUTA = "identità non riconosciuta"
DETAIL_CHIAVE_NON_VALIDA = "chiave shim non valida"
DETAIL_DA_APPROVARE_IN_CODA = "da approvare in coda"
DETAIL_DATO_PERSONALE_SOSPETTO = "dato_personale_sospetto"
DETAIL_RUOLO_SENZA_ACCESSO = "identità senza accesso operativo: ruolo non abilitato allo shim"

# I tipi ammessi da `vicino_a` (enum del contratto congelato, `parameters[tipo].schema.enum`), ripetuti a mano.
TIPI_VICINO_A = (
    "bar", "farmacia", "caf", "fermata", "poste", "medico",
    "ospedale", "supermercato", "biblioteca", "parco", "banca", "comune",
)
