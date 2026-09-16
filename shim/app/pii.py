"""Filtro anti-PII dello shim (V5, §12): i dati personali non entrano nel database.

Il presidio è doppio e volutamente ridondante rispetto al contratto: il contratto congelato vieta i campi liberi
(`additionalProperties: false`), questo modulo rifiuta i **valori** che sembrano dati personali anche dentro i campi
testuali ammessi (`motivazione`, `payload.*`, `nota`). Le tre classi sorvegliate sono quelle dichiarate da §12 e da
`shim/openapi.yaml`:

- **email** — `qualcuno@dominio.it`;
- **telefono italiano** — cellulare (`3xx……`) o fisso (`0xx……`), con separatori e prefisso `+39` facoltativi;
- **codice fiscale** — 16 caratteri, forma `AAAAAA00A00A000A` (o omocodia: le cifre al posto delle lettere).

Il filtro è deliberatamente restrittivo: un falso positivo costa all'operatore una riformulazione della frase, un
falso negativo costa un dato personale scritto nel database delle proposte. Le date e gli orari (`09:00-13:00`,
`2026-09-15`) non sono toccati: le espressioni richiedono la forma completa del dato.

Nessuna funzione di questo modulo solleva eccezioni: restituisce un esito, e chi chiama decide il 422.
"""

import re
from collections.abc import Mapping, Sequence
from typing import Any

from .errori import DETAIL_DATO_PERSONALE_SOSPETTO, errore

# Etichetta unica del rifiuto, allineata a `components.responses.ParametriNonAmmessi` del contratto congelato —
# la costante arriva da `errori.py` (dove stanno tutti i dettagli del contratto) invece di essere ricopiata.
DETAIL_DATO_PERSONALE = DETAIL_DATO_PERSONALE_SOSPETTO

# email: forma `locale@dominio.tld`. Il vincolo sul TLD evita di leggere «@» isolati come indirizzi.
EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")

# Telefono italiano: cellulare (3 + 8/9 cifre) o fisso (0 + 1/3 cifre di prefisso + 5/8 cifre).
# I separatori ammessi sono spazio, punto, trattino, barra; il prefisso internazionale `+39` è facoltativo.
CELLULARE = r"3\d{2}[\s.\-/]?\d{3}[\s.\-/]?\d{3,4}"
FISSO = r"0\d{1,3}[\s.\-/]?\d{5,8}"
TELEFONO = re.compile(
    rf"(?<!\d)(?:\+39[\s.\-/]?)?(?:{CELLULARE}|{FISSO})(?![\s.\-/]?\d)"
)

# Codice fiscale: 6 lettere, 2 cifre, 1 lettera, 2 cifre, 1 lettera, 3 cifre, 1 lettera finale.
# Le posizioni «di controllo» ammettono anche una cifra: è la forma dell'omocodia.
CODICE_FISCALE = re.compile(
    r"(?<![A-Za-z0-9])[A-Za-z]{6}\d{2}[A-Za-z0-9]\d{2}[A-Za-z0-9]\d{3}[A-Za-z0-9](?![A-Za-z0-9])"
)

MOTIVI: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", EMAIL),
    ("telefono", TELEFONO),
    ("codice_fiscale", CODICE_FISCALE),
)


def motivo(testo: str) -> str | None:
    """La prima classe di dato personale riconosciuta nel testo, o `None` se il testo è ammesso."""
    for nome, espressione in MOTIVI:
        if espressione.search(testo):
            return nome
    return None


def contiene_dato_personale(testo: str) -> bool:
    """Vero se il testo contiene un'email, un telefono italiano o un codice fiscale."""
    return motivo(testo) is not None


def campi_sospetti(campi: Mapping[str, Any]) -> list[str]:
    """I percorsi dei campi (anche annidati in oggetti ed elenchi) che contengono dati personali.

    Restituisce percorsi puntati e ordinati — `["motivazione", "payload.indirizzo"]` — così il messaggio d'errore è
    deterministico e il chiamante può nominarli senza mai registrare il valore.
    """
    sospetti: list[str] = []
    for nome, valore in campi.items():
        sospetti.extend(_scansiona_valore(str(nome), valore))
    return sospetti


def _scansiona_valore(percorso: str, valore: Any) -> list[str]:
    if isinstance(valore, str):
        return [percorso] if contiene_dato_personale(valore) else []
    if isinstance(valore, Mapping):
        return [
            trovato
            for chiave, figlio in valore.items()
            for trovato in _scansiona_valore(f"{percorso}.{chiave}", figlio)
        ]
    if isinstance(valore, Sequence) and not isinstance(valore, (str, bytes)):
        return [
            trovato
            for indice, figlio in enumerate(valore)
            for trovato in _scansiona_valore(f"{percorso}[{indice}]", figlio)
        ]
    return []


def rifiuta_se_presente(campi: Mapping[str, Any]) -> None:
    """Solleva il 422 `dato_personale_sospetto` se uno dei campi contiene un dato personale.

    È il punto di ingresso usato dalle route: i **nomi** dei campi sospetti finiscono nel messaggio d'errore (servono
    al LLM per correggersi), i **valori** mai (V5: i dati personali non entrano nemmeno nei log dello shim).
    """
    sospetti = campi_sospetti(campi)
    if sospetti:
        raise errore(
            422,
            f"{DETAIL_DATO_PERSONALE} — campi con dati personali: {', '.join(sorted(sospetti))}",
        )
