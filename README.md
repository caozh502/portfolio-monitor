<p align="center">
  <a href="README.zh.md">[CN] Chinese</a>
  |
  <a href="README.md">[EN] English</a>
</p>

# Portfolio Monitor

Automatically fetches Trading212 portfolio and sends daily reports / weekly review summaries to Telegram.

[GitHub](https://github.com/caozh502/portfolio-monitor)

## Features

| Report | Frequency | File | Content |
|--------|-----------|------|---------|
| **Daily Portfolio Review** | Every trading day, 18:00 CEST | `monitor.py` | Daily P&L, top gainers/losers, sell signals, near-high alerts |
| **Weekly Portfolio Review** | Every Saturday, 14:00 CEST | `scripts/weekly_review.py` | Trade recap (buys/sells/adds/reduces), account changes, rating, suggestions |

## File Structure

```
portfolio-monitor/
|-- .github/workflows/
|   |-- monitor.yml            # Daily Portfolio Review - Mon-Fri 16:00 UTC
|   +-- weekly_review.yml      # Weekly Portfolio Review - Sat 12:00 UTC
|-- scripts/
|   +-- weekly_review.py       # Weekly review script
|-- snapshots/                  # Weekly portfolio snapshots (JSON, auto-clean 52wks)
|   |-- 2026-W28.json
|   +-- ...
|-- monitor.py                  # Daily report: fetch -> analyze -> Telegram
|-- trading212.py               # Trading212 API wrapper + auto ticker resolver
|-- README.md
+-- .gitignore
```

## How It Works

### Daily Portfolio Review
1. Fetch all positions + cash from Trading212 API
2. Auto-resolve Yahoo Finance tickers (US -> direct, EU -> try .DE/.PA/.F etc.)
3. Get daily change (computed from actual close array, not chartPreviousClose), 30-day high
4. Calculate limit-sell suggestions for profitable positions
5. Push to Telegram (HTML format)

### Weekly Portfolio Review
1. Fetch all positions + cash from Trading212
2. Save snapshot to snapshots/{week}.json
3. Load previous week's snapshot, detect: new/closed/increased/reduced positions
4. Rule engine evaluates the week (cash management, diversification, trade frequency)
5. Generate suggestions for next week
6. Push to Telegram
7. Auto-clean snapshots older than 52 weeks

## Deployment (VPS — since 2026-08-17)

GitHub Actions workflows are **disabled**; both reports now run on the VPS cron
(`calebhomelist.duckdns.org`, Europe/Berlin timezone):

```cron
# Daily close report — 18:00 Berlin (16:00 UTC) weekdays
0 18 * * 1-5 cd /home/ubuntu/portfolio-monitor && set -a && . ./.env && set +a && /usr/bin/python3 monitor.py >> daily.log 2>&1
# Weekly review — Sat 14:00 Berlin (12:00 UTC)
0 14 * * 6 cd /home/ubuntu/portfolio-monitor && set -a && . ./.env && set +a && /usr/bin/python3 scripts/weekly_review.py >> weekly.log 2>&1
```

Secrets live in `~/portfolio-monitor/.env` (chmod 600): `TG_BOT_TOKEN`, `TG_CHAT_ID`,
`TRADING212_API_KEY`, `TRADING212_API_SECRET`.

**Privacy**: snapshots are written to `~/portfolio-monitor/snapshots/` on the VPS only.
`snapshots/` is gitignored. The GitHub history was rewritten with `git filter-repo`
to purge all previously committed snapshots.

**Update flow**: `cd ~/portfolio-monitor && git pull` (deps unchanged, stdlib only).
No deploy script needed — cron picks up new code on next run.

## Ticker Overrides

Some cross-listed stocks have different prices on European exchanges vs US. Manual overrides:

| Raw Ticker | Mapped To | Description |
|------------|-----------|-------------|
| 6RJ | RKLB | Rocket Lab |
| 9MW | MRVL | Marvell Technology |
| TSFA | TSM | TSMC ADR |
| NPA | ASTS | AST SpaceMobile (Yahoo NPA.F is a different company) |

Edit `_TICKER_OVERRIDE` in `trading212.py` to add more.

## Snapshot Management

- Weekly snapshots saved to `snapshots/` locally on the VPS — **never committed to GitHub** (privacy). The repo itself stays public with no portfolio data in its history.
- Max **52 weeks** (1 year), oldest auto-deleted
- ~1KB per snapshot, ~50KB total per year

---
_Portfolio Monitor - [GitHub](https://github.com/caozh502/portfolio-monitor)_
