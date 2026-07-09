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

## GitHub Secrets

| Secret | Description |
|--------|-------------|
| TG_BOT_TOKEN | Telegram Bot Token |
| TG_CHAT_ID | Telegram Chat ID |
| TRADING212_API_KEY | Trading212 API Key |
| TRADING212_API_SECRET | Trading212 API Secret |

## Ticker Overrides

Some cross-listed stocks have different prices on European exchanges vs US. Manual overrides:

| Raw Ticker | Mapped To | Description |
|------------|-----------|-------------|
| 6RJ | RKLB | Rocket Lab |
| 9MW | MRVL | Marvell Technology |
| TSFA | TSM | TSMC ADR |

Edit `_TICKER_OVERRIDE` in `trading212.py` to add more.

## Snapshot Management

- Weekly snapshots saved to `snapshots/` and committed to GitHub
- Max **52 weeks** (1 year), oldest auto-deleted
- ~1KB per snapshot, ~50KB total per year

---
_Portfolio Monitor - [GitHub](https://github.com/caozh502/portfolio-monitor)_
