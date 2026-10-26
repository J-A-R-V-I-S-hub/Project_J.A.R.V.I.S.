# PROJECT J.A.R.V.I.S.

> Inizializzazione sistemi...

**Status:** Online

### Assistente personale sperimentale ispirato a J.A.R.V.I.S. di Iron Man.

- Apprende.
- Analizza.
- Coordina.
- Evolve.

---

_"A volte bisogna correre prima ancora di imparare a camminare." — Tony Stark_

## Cosa sa fare

**Conversazione e memoria**
- Memoria persistente per chat (sessioni Agno + memoria a lungo termine)
- Profilo strutturato: fatti, obiettivi, progetti
- Personalità selezionabile (`butler`, `friendly`, `concise`, `mentor`, `stark`)

**Input multimodale**
- Testo, vocali e audio con trascrizione
- Immagini, PDF, DOCX, CSV ed Excel
- Screenshot dello schermo e webcam con analisi vision

**Analisi e report**
- Grafici: barre, barre raggruppate, linee, torta, Pareto
- Report PDF, CSV, simulazioni what-if
- Analisi qualità/difetti con Pareto, top offender e trend storico
- Watcher automatico su `data/quality/`

**Voce e presenza**
- TTS OpenAI oppure macOS `say`
- Voice loop locale con wake word ("Hey Jarvis") o push-to-talk
- Meeting assistant: registra, trascrive, riassume, action item

**Casa e Mac**
- Controllo macOS: app, volume, musica, screenshot, clipboard, notifiche, Shortcuts, lock
- Home Assistant: luci, clima, scene, sensori
- Presenza via ping del telefono
- Protocolli con nome (stile "House Party Protocol")

**Proattività**
- Brief mattutino con meteo e promemoria
- Avvisi su email, GitHub, calendario, meteo e presenza
- Sentinella webcam con rilevamento movimento

**Conoscenza e codice**
- Knowledge base locale SQLite FTS5 con citazioni
- Indicizzazione automatica degli allegati
- Copilot del repository: stato git, ricerca codice, indice del progetto

**Sicurezza e operatività**
- Allowlist single-user
- Audit log delle azioni
- Approvazioni per azioni sensibili (`/confirm`, `/cancel`)
- Shell con allowlist
- Sandbox Python locale o Docker (senza rete)
- Backup automatici dei database
- Routing modelli (economico/potente) e fallback Ollama
- HUD locale con metriche e stato

## Setup

1. Crea e attiva un virtualenv:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Installa il core:

```bash
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

3. Extra opzionali:

```bash
# Voce locale + meeting (sounddevice, faster-whisper, openwakeword)
python -m pip install -e '.[voice]'

# Browser automation
python -m pip install -e '.[browser]'

# Fallback locale con Ollama
python -m pip install -e '.[ollama]'
```

4. Configura `.env`:

```bash
cp .env.example .env
```

Inserisci solo valori reali nel tuo `.env` locale, mai nel repository.

5. Controlla che tutto sia a posto:

```bash
jarvis-doctor
```

## Avvio

```bash
source .venv/bin/activate
python -m jarvis_bot.main
# oppure
jarvis
```

HUD locale:

```bash
jarvis-dashboard
# http://127.0.0.1:8765
```

Voice loop:

```bash
jarvis-voice              # wake word "Hey Jarvis"
jarvis-voice --push-to-talk
```

## Comandi Telegram

| Comando | Descrizione |
|---|---|
| `/start`, `/help` | Presentazione e capacità |
| `/reset` | Azzera la conversazione |
| `/stats` | Sessioni, token, latenza, tool |
| `/files` | Ultimi file generati |
| `/voice on\|off` | Risposte vocali automatiche |
| `/persona [nome]` | Cambia personalità |
| `/protocol [nome]` | Elenca o esegue protocolli |
| `/index [file]` | Indicizza documenti |
| `/ask <domanda>` | Cerca nella knowledge base |
| `/sources` | Documenti indicizzati |
| `/brief` | Brief di oggi |
| `/reminders` | Promemoria attivi |
| `/quality <file>` | Analisi difetti CSV/Excel |
| `/meeting start\|stop\|list\|show` | Meeting assistant |
| `/look screen\|camera [domanda]` | Analisi schermo/webcam |
| `/sentinel on\|off\|status` | Sentinella webcam |
| `/profile [categoria]` | Profilo strutturato |
| `/repo status\|index\|search` | Copilot del codice |
| `/proactive on\|off\|status` | Controlli proattivi |
| `/audit` | Ultime azioni registrate |
| `/approvals` | Azioni in attesa (con bottoni Approva/Annulla) |
| `/confirm <id>`, `/cancel <id>` | Gestione approvazioni |
| `/backup` | Backup manuale |
| `/doctor` | Autodiagnosi configurazione |

## Protocolli

Protocolli predefiniti: `lavoro`, `focus`, `buonanotte`, `emergenza`.

```text
/protocol lavoro
```

Passi supportati: `open_app`, `open_url`, `notify`, `volume`, `lock`, `screenshot`,
`shortcut`, `sleep`, `music`, `home_assistant`, `backup`.

## Configurazione

Tutto passa da `.env`. Gruppi principali:

| Gruppo | Variabili |
|---|---|
| Telegram | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_ID` |
| LLM | `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `OPENROUTER_VISION_MODEL`, `OPENROUTER_AUDIO_MODEL` |
| Agente | `JARVIS_TIMEZONE`, `JARVIS_HISTORY_RUNS`, `JARVIS_TOOL_CALL_LIMIT`, `JARVIS_PERSONA` |
| Brief e meteo | `JARVIS_DAILY_BRIEF_*`, `JARVIS_LOCATION`, `JARVIS_LATITUDE`, `JARVIS_LONGITUDE` |
| Qualità | `JARVIS_QUALITY_WATCH_DIR`, `JARVIS_QUALITY_WATCH_ENABLED` |
| Media | `OPENAI_API_KEY`, `JARVIS_TTS_*`, `JARVIS_IMAGE_MODEL` |
| Knowledge | `JARVIS_KNOWLEDGE_*` |
| Voce | `JARVIS_VOICE_*`, `JARVIS_MEETING_DIR` |
| HUD | `JARVIS_DASHBOARD_HOST`, `JARVIS_DASHBOARD_PORT` |
| Casa/presenza | `HOME_ASSISTANT_URL`, `HOME_ASSISTANT_TOKEN`, `JARVIS_PHONE_IP` |
| Visione | `JARVIS_VISION_ENABLED`, `JARVIS_SENTINEL_*` |
| Proattività | `JARVIS_PROACTIVE_*` |
| Integrazioni | `GITHUB_TOKEN`, `NOTION_TOKEN`, `CALENDAR_ICS_URL`, `EMAIL_*` |
| Fondamenta | `JARVIS_REQUIRE_APPROVAL`, `JARVIS_SAFE_SHELL_ENABLED`, `JARVIS_BACKUP_*`, `JARVIS_MODEL_ROUTING_*` |
| Sandbox | `JARVIS_SANDBOX_BACKEND`, `JARVIS_SANDBOX_IMAGE`, `JARVIS_SANDBOX_MEMORY` |

Le integrazioni si attivano **solo** se le relative credenziali sono presenti.
Senza `OPENAI_API_KEY` il TTS usa macOS `say`; la generazione immagini resta disabilitata.

## Qualità / difetti

Metti un CSV o Excel in `data/quality/`: Jarvis lo analizza automaticamente e invia
barre raggruppate, Pareto per prodotto, Pareto per categoria, trend storico e PDF.
In alternativa: `/quality /percorso/file.csv`.

Ogni file viene elaborato una volta sola; per rielaborarlo usa `/quality` o rinominalo.

## Plugin

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
  main.py           entrypoint bot e logging
  config.py         impostazioni da .env
  service.py        bot Telegram, comandi, scheduler, approvazioni
  agent.py          agente Agno, tool, memoria, routing modelli
  attachments.py    preparazione PDF/CSV/Excel/immagini
  schemas.py        modelli di dominio e ChartSpec
  reporting.py      grafici, CSV e PDF
  reminders.py      promemoria
  quality.py        analisi difetti e trend
  simulation.py     scenari what-if
  knowledge.py      knowledge base FTS5
  profile.py        profilo strutturato
  proactive.py      regole proattive
  protocols.py      protocolli/macro
  meetings.py       meeting assistant
  voice_loop.py     voce locale e wake word
  vision.py         schermo, camera, sentinella
  dashboard.py      HUD locale
  codebase.py       copilot del repository
  models.py         routing modelli
  security.py       shell sicura
  sandbox.py        esecuzione Python isolata (Docker opzionale)
  approvals.py      approvazioni
  audit.py          audit log
  backup.py         backup database
  doctor.py         autodiagnosi
  persona.py        personalità
  app_state.py      preferenze chat
  plugins.py        registry plugin
  media.py          TTS e immagini
  integrations/     GitHub, email, calendario, Notion, meteo, Home Assistant, macOS, musica
data/               runtime locale (ignorato da git)
tests/              test unitari
```

## Test e qualità

```bash
source .venv/bin/activate
pytest
ruff check src tests
```

La CI esegue lint e test su Python 3.11, 3.12 e 3.13.

## Sicurezza

Il bot risponde **solo** all'utente indicato in `TELEGRAM_ALLOWED_USER_ID`.
Il progetto è pensato per uso personale: non è multi-utente e non va esposto
pubblicamente. La shell è limitata da una allowlist; le azioni sensibili possono
richiedere approvazione (`JARVIS_REQUIRE_APPROVAL=true`). I file inviabili sono
limitati a `output/`, `reports/` e `workspace/`, con blocco di database e file sensibili.
Con `JARVIS_SANDBOX_BACKEND=docker` il codice Python gira in un container senza rete,
con limiti di memoria e CPU. L'HUD ascolta solo su `127.0.0.1` per default.
