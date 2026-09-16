# Skill — setup e scoping per agente (progetto Trasi)

## Cosa è installato

4 skill dal marketplace pubblico, scelte per pertinenza al piano (`skills.sh`, criterio: install count + reputazione della fonte + audit di sicurezza):

| Skill | Fonte | Installs | Usata da | Perché questa |
|---|---|---|---|---|
| `supabase-postgres-best-practices` | `supabase/agent-skills` | 402K | `trasi-dati` | Postgres "ovunque": RLS, indici, schema design, migrazioni, diagnosi query lente. Copre il blocco B1. |
| `multi-stage-dockerfile` | `github/awesome-copilot` | 24.9K | `trasi-stack` | Dockerfile multi-stage: shim e servizi custom del compose Trasi. |
| `fastapi-templates` | `wshobson/agents` | 24.2K | `trasi-shim` | Struttura app FastAPI, dependency injection, gestione errori = contratto §9.1. |
| `pytest-coverage` | `github/awesome-copilot` | 12.6K | `trasi-shim` | Suite pytest dello shim (26+ test nominati nel piano). |

**Scartate per duplicazione** (nessun analogo installato): `postgres-rls` (troykelly, 213 inst. — coperta meglio da supabase), `docker-patterns`, `fastapi-python`/`fastapi-expert` (ridondanti con `fastapi-templates`), `wcag-accessibility-audit` (il piano fa V-08 con checklist + axe), `rag-*` (generiche, il RAG è già validato su Onyx).

**Preesistenti, non reinstallate:** `beads-ops`, `find-skills`, `orchestration` (a livello utente, `/root/.agents/skills/`).

## Dove sono — e perché solo lì

**`.omp/skills/<nome>/` — copie reali, non symlink.** Layout nativo OMP (`<root>/skills/<name>/SKILL.md`). È l'unica fonte.

`.claude/skills/<nome>` contiene **symlink** alla stessa fonte (li crea `npx skills`): servono solo se si usa anche Claude Code, non incidono sulla discovery OMP.

Due scoperte sperimentali, entrambe costate tempo:

1. **I symlink rompono il filtro `--skills`.** Con `.omp/skills/*` come symlink a `.agents/skills/*`, un pattern singolo filtrava ma una lista `a,b` **non** filtrava (restituiva tutte le skill presenti). Sostituiti con copie reali → il filtro multi-pattern funziona. Causa probabile: la risoluzione del glob non attraversa il link.
2. **Una sola root, per evitare ambiguità.** Tenere le skill *sia* in `.omp/skills/` *sia* in `.agents/skills/` rendeva incoerenti le misurazioni (doppia discovery). Ora la fonte è **una sola**: `.omp/skills/` (progetto); `.agents/` è stato rimosso e i symlink di `.claude/skills/` ripuntati alla fonte reale (senza questo, restavano pendenti).

## Scoperta: la lista skill è uno snapshot all'avvio

**Verificato con agenti reali.** Skill installate *dopo* l'avvio della sessione non sono visibili — in nessuna root (progetto/utente/globale) e a nessun subagente. Sintomo: `read skill://<nuova>` → `Unknown skill: <nuova> — Available: beads-ops`.

Prova: sessione avviata il 14/09 13:42; le 4 skill installate il 15/09 17:54; l'unica skill risolvibile era `beads-ops` (13/09, preesistente). In un **processo nuovo** (`omp -p`) tutte e 7 sono scoperte.

**Conseguenza operativa:** dopo aver installato o modificato skill, **avviare una sessione nuova**. Nella sessione corrente l'`autoloadSkills` degli agenti viene ignorato **in silenzio** (il runtime logga e procede).

## Scoping reale: `--skills=<glob>`

Unico meccanismo che restringe davvero la discovery. **Verificato con probe deterministica** (lettura di `skill://<nome>` e verifica di "Unknown skill"):

```bash
omp -p --skills='pytest-coverage,fastapi-templates' "…"
# → skill://fastapi-templates: SI
#   skill://pytest-coverage:   SI
#   skill://multi-stage-dockerfile: NO
#   skill://supabase-postgres-best-practices: NO
#   skill://beads-ops: NO
```

Supportati: nome singolo, lista separata da virgole, glob (`*docker*` → solo `multi-stage-dockerfile`). La sintassi brace `{a,b}` **non** è supportata.

### ⚠️ Come NON misurare

Le probe "elenca i nomi delle skill nel tuo contesto" sono **inaffidabili**: il modello allucina voci, fonde descrizioni e talvolta elenca *agenti* (`scout`, `task`, `sonic`) invece di skill. Misurazioni così hanno prodotto conclusioni contraddittorie durante il setup.

**Probe corretta:** chiedere al modello di eseguire `read` su URI `skill://<nome>` specifiche e riportare SI/NO per ciascuna. Deterministico, non interpretabile.

## `autoloadSkills`: cosa fa e cosa non fa

**Fa:** inietta il contenuto della skill dichiarata nell'agente prima del primo prompt (utile: il worker parte già con la skill in contesto).

**Non fa:** **non nasconde le altre skill.** Il subagente eredita la lista completa della sessione padre — confermato da due agenti indipendenti che vedevano tutte le skill, non solo la propria.

Per un isolamento stretto serve la **sessione con `--skills`**, non il solo `autoloadSkills`.

## Agenti definiti (`.omp/agents/`)

| Agente | Ruolo | `autoloadSkills` | Tool |
|---|---|---|---|
| `trasi-stack` | Compose, container, cron, backup, tunnel | `multi-stage-dockerfile` | pieni |
| `trasi-dati` | Schema, RLS, indici, seed, test SQL | `supabase-postgres-best-practices` | pieni |
| `trasi-shim` | Endpoint FastAPI, Overpass, biglietto, pytest | `fastapi-templates`, `pytest-coverage` | pieni |
| `trasi-onyx` | LLM provider, persona, tool custom, Drive, RAG | *(nessuna — usa il sorgente in `/opt/onyx`)* | pieni |
| `trasi-review` | Revisione read-only (invarianti, criteri osservabili) | *(nessuna)* | `read, grep, glob, web_search` |

Ogni file agente porta i **vincoli di progetto** estratti dal piano (RLS senza GUC, nessuna scrittura diretta al dominio, log senza corpo, `additionalProperties:false`, copertura OSM reale 7.7%, limiti RAM misurati), così il worker non deve rileggere il piano per ricordare le regole non negoziabili.

## Delega con lo scoping corretto

```bash
# dati — solo Postgres/RLS
omp -p --skills='supabase-postgres-best-practices' "…"

# stack — solo Docker
omp -p --skills='multi-stage-dockerfile' "…"

# shim — FastAPI + pytest
omp -p --skills='fastapi-templates,pytest-coverage' "…"

# review — nessuna skill
omp -p --skills='nessuna' "…"
```

Dalla sessione corrente con il tool `task` l'agente riceve la skill dichiarata in `autoloadSkills` **e** vede le altre: per l'isolamento stretto serve la sessione con `--skills`.

## Orchestrazione (skill `orchestration`)

La skill `orchestration` è un **discovery stub**: rimanda alla guida version-matched del binario Orca. In questo ambiente il CLI corretto è **`orca-ide`** (Linux, fuori da terminale Orca-managed — mai `orca` nudo, che è lo screen reader GNOME).

```bash
orca-ide skills get orchestration            # guida compatta del loop supervisionato
orca-ide skills get orchestration --references   # elenca i reference condizionali
```

Copre: Run/Task/Dispatch (autorità del ciclo di vita), il loop del coordinatore (`run-create` → `worker-start` → `check --wait` → `reply`/`worker-release`), il contratto della task-spec (Target/Change/Constraints/Ownership/Observable acceptance), l'accounting di completamento. Va usata **quando serve supervisione reale** di worker con stato Orca; non sostituisce il tool `task` per il fan-out ordinario.
