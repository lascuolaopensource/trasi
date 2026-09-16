"""Badge di provenienza pre-formattati (V3, architettura §2.2 e §4.4).

Il badge è **già composto dallo shim** e il LLM deve riportarlo così com'è: se lo componesse lui, due risposte alla
stessa domanda mostrerebbero due etichette diverse e la provenienza — che è il primo principio del progetto — non
sarebbe verificabile a colpo d'occhio. Per lo stesso motivo la formattazione sta in un solo modulo: `vicino_a`,
`cerca_luogo`, `eventi_oggi`, `cerca_web` e il biglietto usano le stesse tre funzioni.

Perché `autorita` e non `nome`: le fonti del seed si chiamano «Comune di Brindisi-3», «Rete-kb-3» — il suffisso è il
livello di fiducia, non parte del nome. `fonte.autorita` contiene il nome umano («Comune di Brindisi»,
«OpenStreetMap contributors (ODbL)»), che è ciò che l'architettura mostra nel badge.
"""

from datetime import date, datetime

FUSO_ITALIANO = "Europe/Rome"
NOTA_ORARI_ASSENTI = "orari non disponibili"

MESI = (
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
)


def nome_fonte(autorita: str | None, nome: str | None) -> str:
    """Il nome leggibile di una fonte: `autorita` se dichiarata, altrimenti il `nome` tecnico."""
    for candidato in (autorita, nome):
        if candidato and candidato.strip():
            return candidato.strip()
    return "fonte non dichiarata"


def _data_italiana(valore: date | datetime | None) -> str:
    """`10/09/2026`; em dash quando la data non è nota — il badge non inventa una data."""
    if valore is None:
        return "—"
    return f"{valore.day:02d}/{valore.month:02d}/{valore.year:04d}"


def _ora_italiana(valore: datetime | None) -> str:
    """`11:42`; em dash quando l'istante non è noto."""
    if valore is None:
        return "—"
    return f"{valore.hour:02d}:{valore.minute:02d}"


def badge_kb(fonte: str, data_aggiornamento: date | datetime | None, fiducia: int | None) -> str:
    """`[KB · Comune di Brindisi · agg. 10/09/2026 · affidabilità 3]` (architettura §4.4)."""
    return f"[KB · {fonte} · agg. {_data_italiana(data_aggiornamento)} · affidabilità {fiducia if fiducia else '—'}]"


def badge_esterna(fonte: str, consultato_ts: datetime | None) -> str:
    """`[Esterna · OpenStreetMap contributors (ODbL) · consultata 11:42 · non verificata dalla rete]`."""
    return f"[Esterna · {fonte} · consultata {_ora_italiana(consultato_ts)} · non verificata dalla rete]"
