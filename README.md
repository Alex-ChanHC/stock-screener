# Automated Stock Screener

A Python application that retrieves market data, applies configurable screening
steps, ranks candidates, and sends a concise notification. The project is
designed to be adapted to a user's own data providers, screening configuration,
and notification destination.

## Project layout

- `main.py` — command-line entry point and pipeline orchestration
- `src/` — market-data, screening, ranking, and notification modules
- `tests/` — offline unit tests; external data and notification requests are mocked
- `.env.example` — notification configuration template
- `.screening.env.example` — private screening configuration template
- `.github/workflows/screener.yml` — scheduled and manually-triggered workflow

## Local setup

Use Python 3.10 or newer. From PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
Copy-Item .screening.env.example .screening.env
```

Fill in `.env` with the credentials and settings for one notification provider.
The supported providers are Telegram, ntfy, and Discord. Choose one with
`NOTIFICATION_PROVIDER`; the command-line `--notifier` option can override it.
Keep all populated environment files private and never commit them.

Populate `.screening.env` with settings appropriate for your own use. The
template lists every required key; values are intentionally left blank. Lists
use the formats below:

- `SCREENING_SECTOR_ETFS`: semicolon-separated `ticker|display name|provider token`
  entries
- `SCREENING_RETURN_WINDOWS`: comma-separated `label:trading-days` entries
- `SCREENING_FINVIZ_FILTERS`: comma-separated provider selector IDs
- `SCREENING_SCTR_STOCK_REPORTS`: semicolon-separated `report ID|universe name`
  entries
- Numeric settings: positive integers for day counts and numeric percentages for
  the 52-week range distances

Missing or invalid settings stop the run with an explicit configuration error.

## Verify and run

Send a sample notification without calling market-data providers:

```powershell
python main.py --test-notification
```

Run the offline unit tests and then the configured pipeline:

```powershell
python -m pytest -q
python main.py
```

The pipeline logs provider results and screening counts. External websites and
data feeds can change or be temporarily unavailable; consult the logs and
notification when a run produces no candidates. A successful ntfy publish
confirms server acceptance, not delivery to a particular device.

For a live data check that prints the candidates and exact notification preview
without sending it:

```powershell
$env:RUN_LIVE_SCREENING = "1"
python -m pytest -s tests/test_live_screening.py
Remove-Item Env:RUN_LIVE_SCREENING
```

This opt-in integration test uses real market-data providers and requires the
local `.screening.env`. It is skipped during the regular test suite unless
`RUN_LIVE_SCREENING=1` is set. Review the preview, then run `python main.py`
separately when ready to send the live notification.

If a screening phase raises an error during a normal run, later phases are
skipped and the notification includes a short warning identifying the failed
phase. Check the workflow or terminal logs for diagnostic details. If the
notification provider itself is unavailable, delivery cannot be reported in
the notification; the run logs the delivery failure instead.

## GitHub Actions setup

The stock screener workflow uses the schedule configured in
`.github/workflows/screener.yml` and can also be started manually from the
Actions tab. Configure repository secrets for:

- `SCREENING_ENV_FILE` — the complete contents of your private screening
  environment file, in dotenv format
- `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` when using Telegram
- `NTFY_TOPIC` when using ntfy
- `DISCORD_WEBHOOK_URL` when using Discord

Set the `NOTIFICATION_PROVIDER` and `NTFY_SERVER` repository variables when
needed. Tests use synthetic settings and do not require the private configuration
or notification secrets.

The separate **Finviz compatibility check** runs every Saturday at 21:00 Hong
Kong time, about 24 hours before the scheduled Sunday screener, and can also be
started manually from the Actions tab. It runs its offline parser tests and
checks a broad, public Finviz screener response. It does not
read the private screening configuration, send notifications, or change
screening results. If it cannot parse ticker links, it creates or updates one
diagnostic issue with a link to the workflow logs; after a later successful
check, it closes that issue.

The workflow uses the built-in `GITHUB_TOKEN` with `issues: write` permission.
If organization or repository policy prevents issue creation, enable read/write
workflow permissions in **Settings → Actions → General**, or ask an organization
administrator. For a code investigation, assign the diagnostic issue to Copilot
or start Copilot coding agent from the issue. It will propose changes for review;
the health workflow itself never changes or merges code. GitHub may delay
scheduled workflows, so the lead time is not guaranteed.

## Adopting the project

Replace the example configuration with your own selectors, benchmark choices,
data sources, and notification settings. Confirm each provider's terms, rate
limits, and data availability before scheduling automated runs. The project
does not provide investment advice.

## Public repository note

Replacing documentation or removing configuration from the current checkout
does not erase information in earlier Git commits. Before publishing this
repository, inspect the complete history and prior pull requests, or publish a
new sanitized repository with no sensitive history. Rotate any credentials that
may previously have been committed.
