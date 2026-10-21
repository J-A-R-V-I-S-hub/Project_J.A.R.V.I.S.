# PROJECT J.A.R.V.I.S.

> Inizializzazione sistemi...

**Status:** Online

### Assistente personale sperimentale su Telegram.

- Apprende.
- Analizza.
- Coordina.
- Evolve.

---

_"A volte bisogna correre prima ancora di imparare a camminare." — Tony Stark_

## Cosa sa fare

- Conversazione con memoria persistente per chat (sessioni Agno + memoria a lungo termine).
- Trascrizione di vocali e audio.
- Descrizione e analisi di immagini.
- Estrazione testo da PDF, DOCX, CSV ed Excel.
- Grafici (barre, barre raggruppate, linee, torta, Pareto), report PDF e CSV.
- Analisi qualità/difetti con Pareto, top offender, trend storico e watcher su `data/weldtrace/`.
- Promemoria, brief mattutino con meteo e comandi rapidi.
- Knowledge base locale con ricerca full-text (SQLite FTS5) e citazioni delle fonti.
- Risposte vocali (TTS) e generazione immagini.
- Integrazioni opzionali: GitHub, email, calendario ICS, Notion, meteo.
- Plugin estensibili via entry point `jarvis.plugins`.

## Setup

1. Crea e attiva un virtualenv:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Installa le dipendenze:

```bash
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

3. Crea il file `.env` partendo dai placeholder:

```bash
cp .env.example .env
```

4. Inserisci solo valori reali nel tuo `.env` locale, mai nel repository.

## Avvio

```bash
source .venv/bin/activate
python -m jarvis_bot.main
```

In alternativa, dopo l'installazione editable:

```bash
jarvis
```

## Comandi Telegram

- `/start` — presentazione e capacità.
- `/help` — elenco comandi.
- `/reset` — dimentica la conversazione corrente.
- `/stats` — sessioni, token, latenza e tool più usati.
- `/files` — ultimi file generati.
- `/voice on|off` — risposte vocali automatiche.
- `/index [file]` — indicizza la cartella `data/knowledge/` o un file specifico.
- `/ask <domanda>` — cerca nella knowledge base.
- `/sources` — documenti indicizzati.
- `/brief` — brief di oggi su richiesta.
- `/reminders` — promemoria attivi.
- `/quality <file>` — analisi difetti di un CSV/Excel.

## Configurazione

Tutto passa da `.env`. Le variabili principali:

| Gruppo | Variabili |
|---|---|
| Telegram | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_ID` |
| LLM | `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `OPENROUTER_VISION_MODEL`, `OPENROUTER_AUDIO_MODEL` |
| Comportamento | `JARVIS_TIMEZONE`, `JARVIS_HISTORY_RUNS`, `JARVIS_TOOL_CALL_LIMIT` |
| Brief | `JARVIS_DAILY_BRIEF_ENABLED`, `JARVIS_DAILY_BRIEF_TIME`, `JARVIS_LOCATION` |
| Qualità | `JARVIS_QUALITY_WATCH_DIR` |
| Knowledge | `JARVIS_KNOWLEDGE_DB_PATH`, `JARVIS_KNOWLEDGE_DIR` |
| Media | `OPENAI_API_KEY`, `JARVIS_TTS_MODEL`, `JARVIS_IMAGE_MODEL` |
| Integrazioni | `GITHUB_TOKEN`, `NOTION_TOKEN`, `CALENDAR_ICS_URL`, `EMAIL_*` |

Le integrazioni si attivano **solo** se le relative credenziali sono presenti.
Senza `OPENAI_API_KEY` il TTS usa il comando macOS `say`; la generazione immagini resta disabilitata.

## Qualità / difetti

Metti un CSV o Excel in `data/weldtrace/`: Jarvis lo analizza automaticamente, genera
grafico a barre raggruppate, Pareto per prodotto, Pareto per categoria, trend storico
(dopo almeno due analisi) e un report PDF, poi li invia su Telegram.

In alternativa: `/quality /percorso/del/file.csv`.

## Plugin

Un pacchetto esterno può contribuire tool e istruzioni:

```toml
[project.entry-points."jarvis.plugins"]
my_plugin = "my_package.jarvis_plugin:build"
```

```python
from jarvis_bot.plugins import Plugin, PluginContext

def build(context: PluginContext) -> Plugin:
    def hello(name: str = "") -> str:
        """Saluta."""
        return f"Ciao {name}"

    return Plugin(name="my_plugin", tools=[hello], instructions=["Usa hello per salutare."])
```

## Struttura

```text
src/jarvis_bot/
  main.py           entrypoint e logging
  config.py         impostazioni da .env
  service.py        bot Telegram, comandi, scheduler e consegna artefatti
  agent.py          agente Agno, tool, memoria e coda artefatti
  attachments.py    preparazione di PDF, CSV, Excel e immagini
  schemas.py        modelli di dominio e ChartSpec
  reporting.py      grafici, CSV e report PDF
  reminders.py      promemoria SQLite + parsing date
  quality.py        analisi difetti, Pareto e trend
  knowledge.py      knowledge base SQLite FTS5
  media.py          TTS e generazione immagini
  stats.py          statistiche d'uso dal DB Agno
  app_state.py      preferenze per chat
  plugins.py        registry plugin
  integrations/     GitHub, email, calendario ICS, Notion, meteo
data/               runtime locale (ignorato da git)
tests/              test unitari
```

## Test

```bash
source .venv/bin/activate
pytest
```

## Sicurezza

Il bot risponde **solo** all'utente indicato in `TELEGRAM_ALLOWED_USER_ID`.
Il progetto è pensato per uso personale: non è multi-utente e non va esposto
pubblicamente. Il motore Python/shell è una sandbox "soft": non eseguirlo su
dati o macchine non fidati. I file inviabili sono limitati a `output/`, `reports/`
e `workspace/`, con blocco di database e file sensibili.
