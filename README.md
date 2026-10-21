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

- Conversazione con memoria persistente per chat.
- Trascrizione di vocali e audio.
- Descrizione e analisi di immagini.
- Estrazione testo da PDF e analisi di CSV.
- Generazione di grafici (barre, barre raggruppate, linee, torta, Pareto), report PDF e CSV.
- Web search, accesso ai file e sandbox Python/shell.
- Memoria a lungo termine delle preferenze.

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

## Struttura

```text
src/jarvis_bot/
  main.py         entrypoint e logging
  config.py       impostazioni da .env
  service.py      bot Telegram, handler e consegna artefatti
  agent.py        agente Agno, tool e coda artefatti
  attachments.py  preparazione di PDF, CSV e immagini
  schemas.py      modelli di dominio
  reporting.py    grafici, CSV e report PDF
data/             runtime locale (ignorato da git)
tests/            test unitari
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
dati o macchine non fidati.
