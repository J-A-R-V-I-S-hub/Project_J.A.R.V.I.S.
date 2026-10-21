# PROJECT J.A.R.V.I.S.

> Inizializzazione sistemi...

**Status:** Online

### Assistente sperimentale.

- Apprende.
- Analizza.
- Coordina.
- Evolve.

---

_"A volte bisogna correre prima ancora di imparare a camminare." — Tony Stark_

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

Per partire in polling:

```bash
source .venv/bin/activate
python -m src.jarvis_bot.main
```

## Test

```bash
source .venv/bin/activate
pytest
```
