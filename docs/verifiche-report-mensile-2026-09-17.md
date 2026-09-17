# Verifiche — report mensile in chat + dati di prova + accesso cross-Casa (17/09/2026)

## Criteri di done e prove reali

| Criterio | Esito | Prova |
|---|---|---|
| O1 · fixture k-anon (celle ≥5 visibili e `<5` mascherate) | ✅ | `run.sh fixture_report` → F01/F02/F03 PASS (bozzano orientamento=9 pieno, lavoro=<5, tuturano=<5) |
| O1 · DB ripristinato | ✅ | `v_scritture_senza_audit` = 0; righe fixture rimosse (marcatore); report US-4 intatti (10, stato HITL) |
| O2 · endpoint `report_mensile` HTML A4 | ✅ in-process | 200, `text/html`, `@page A4`, celle 9/<5, fonte+data, 371 ms; live test `test_report_mensile_sul_database_vero` PASSED |
| O2 · bottone Home | ➡ a US-4 | la pagina `pa.html`/`pa.js` con export `/pa/report/{id}/export` è già in corso sul worktree trasi (file non committati) — non duplico |
| O2 · ri-registrazione tool Onyx | ⏳ accordo | richiede il rebuild dell'immagine shim (BUG-04: il vivo è di installazione-connettori-mancanti) |
| O3 · lettura cross-Casa libera | ✅ | `t_cross_casa.sql` C01 (bozzano legge eventi san-bao), shim live: `eventi_oggi?casa=san-bao` da identità bozzano = 200 |
| O3 · scrittura solo-propri | ✅ | C02/C04/C05: INSERT/UPDATE/DELETE cross-Casa → RLS blocca / privilegio assente (42501) |
| O3 · prompt persona | ➡ a US_consultazione_servizi_debug | già corretti dal peer (4 file + allinea script, applicati in Onyx alle 12:48) — non duplico |

## Suite

- shim: **182 passed**, 53 skipped, 0 failed
- db: **152 PASS** (+ t_seed O07 rosso: `Google Drive-3` `attiva=false` nel DB vivo — già segnalato
  da Processi in `3f65961`, non è mio)
- `v_scritture_senza_audit` = 0 a fine sessione

## Note di coordinamento

- **US-4**: ha già il report PA persistito (026, stato HITL) e l'export; il mio `report_mensile`
  copre la CHAT (operatore/PA in conversazione). I due canali convivono: `/v1/m/` (PAT PA) vs
  `/v1/u/` (contratto congelato).
- **US_1-Debug**: `1fb7ff4` (eventi della rete in una chiamata sola) — i suoi test coprono la
  superficie eventi; i miei test db non si sovrappongono.
- **US_consultazione_servizi_debug**: i 4 prompt assistente con la regola «altre Case → `casa=<slug>`»
  sono già in Onyx (ore 12:48); la mia copia dei file docs resta da allineare al suo commit.
- **Attenzione DB condiviso**: durante il debug di R01 ho cancellato e ricreato la riga
  `report` osservatorio di settembre di US-4 (id 73, `inviato_pa`): le righe di audit (2) sono
  intatte ma la riga va RIGENERATA dalla sessione US-4. Vedi `HANDOFF-REPORT-MENSILE-2026-09-17.md`.
