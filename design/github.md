repo: lascuolaopensource/trasi
branch: main

## Last sync

date: 2026-09-16T09:23:17Z

### Updated in this project
- Token CSS derivati dai token della Home attuale (`deployment/home/style.css`) e dai colori del logo Case di Quartiere.
- Componenti: etichetta di provenienza (da `shim/app/badge.py`), riga «Oggi», coda delle proposte.
- UI kit delle cinque superfici: Home, CHIEDI, OSSERVATORIO, REGISTRA/AGGIORNA, MAPPA.
- Analisi dell'architettura dell'informazione della Home in `guidelines/analisi-architettura-informazione.md`.

## Screen map

| Schermata in questo progetto | File del repository |
|---|---|
| `ui_kits/trasi-home/` | `deployment/home/index.html`, `deployment/home/style.css`, `deployment/home/home.js`, `.specs/B6-home-ops.md` |
| `ui_kits/trasi-chiedi/` | `shim/app/badge.py`, `docs/prompt-assistente-2-trasicasa.txt`, `shim/app/testi.py` |
| `ui_kits/trasi-osservatorio/` | `.specs/B5-dash.md`, `.specs/B1-proposte.md`, `db/004_views.sql` (viste `v_oggi_casa`, `v_proposte_aperte`) |
| `ui_kits/trasi-registra/` | `.specs/B1-proposte.md`, `deployment/home/index.html` (stato «non ancora attivo») |
| `ui_kits/trasi-mappa/` | `.specs/B5-dash.md` (dashboard «Mappa», viste `v_mappa_*`) |
| `tokens/`, `guidelines/` | `deployment/home/style.css`, `deployment/home/WCAG.md`, `shim/app/testi.py` (biglietto A6) |
