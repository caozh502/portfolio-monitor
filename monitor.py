#!/usr/bin/env python3
"""
Portfolio Monitor — weekly check of sell targets + market alerts.
Sends Telegram notification when conditions are met.

Usage:
    export TG_BOT_TOKEN=xxx TG_CHAT_ID=xxx
    python monitor.py
"""

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

from config import TARGETS, DCA_CONFIG

# ── FX rate ──────────────────────────────────────────────

def fetch_eurusd() -> float:
    """Fetch live EUR/USD exchange rate."""
    url = "https://query1.finance.yahoo.com/v8/finance/chart/EURUSD=X?interval=1d&range=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            price = data["chart"]["result"][0]["meta"]["regularMarketPrice"]
            return float(price)
    except Exception:
        return 1.08  # fallback


# ── Price helpers ────────────────────────────────────────

def fetch_price(yahoo_ticker: str) -> float | None:
    """Fetch current price from Yahoo Finance chart API."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_ticker}?interval=1d&range=5d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            result = data["chart"]["result"][0]
            return float(result["meta"]["regularMarketPrice"])
    except Exception as e:
        print(f"  [WARN] Failed to fetch {yahoo_ticker}: {e}")
        return None


def fetch_historical(ticker: str, days: int = 250) -> list[float]:
    """Fetch historical close prices."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range={days}d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            quotes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
            return [c for c in quotes if c is not None]
    except Exception as e:
        print(f"  [WARN] Failed to fetch history for {ticker}: {e}")
        return []


# ── Currency conversion ──────────────────────────────────

def convert(amount: float, from_cur: str, to_cur: str, eurusd: float) -> float:
    """Convert amount from from_cur to to_cur."""
    if from_cur == to_cur:
        return amount
    if from_cur == "EUR" and to_cur == "USD":
        return amount * eurusd
    if from_cur == "USD" and to_cur == "EUR":
        return amount / eurusd
    return amount


# ── Telegram ─────────────────────────────────────────────

def send_telegram(message: str):
    token = os.environ.get("TG_BOT_TOKEN", "")
    chat_id = os.environ.get("TG_CHAT_ID", "")
    if not token or not chat_id:
        print("[SKIP] TG_BOT_TOKEN or TG_CHAT_ID not set — printing instead:")
        print(message)
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": True,
    }).encode()
    req = urllib.request.Request(url, data=payload,
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=15)
        print("  [OK] Telegram sent")
    except Exception as e:
        print(f"  [ERROR] Telegram failed: {e}")


def escape_md(text: str) -> str:
    """Escape Telegram MarkdownV2 special chars."""
    for ch in r"_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text


# ── Target checks ────────────────────────────────────────

def check_targets(eurusd: float) -> list[str]:
    alerts = []

    for item in TARGETS:
        name = item["name"]
        ticker = item["ticker"]
        avg = item["avg_price"]
        cost_cur = item["cost_currency"]
        ticker_cur = item["ticker_currency"]

        price = fetch_price(ticker)
        if price is None:
            continue

        # Convert target prices from cost_currency to ticker_currency
        # so we can compare directly with Yahoo price
        def to_ticker_cur(price_val, cur):
            return convert(price_val, cur, ticker_cur, eurusd)

        # Convert the user's cost basis to ticker_currency
        avg_in_ticker_cur = convert(avg, cost_cur, ticker_cur, eurusd)
        change_pct = (price - avg_in_ticker_cur) / avg_in_ticker_cur * 100

        print(f"  {ticker}: {ticker_cur} {price:.2f} (cost {ticker_cur} {avg_in_ticker_cur:.2f}, {change_pct:+.1f}%)")

        # Format display price (show in cost_currency for user)
        price_in_cost_cur = convert(price, ticker_cur, cost_cur, eurusd)
        display_cur = "€" if cost_cur == "EUR" else "$"

        # Check stop loss
        sl = item.get("stop_loss")
        if sl:
            sl_in_ticker = to_ticker_cur(sl["price"], sl.get("currency", cost_cur))
            if price <= sl_in_ticker:
                alerts.append(
                    f"🔴 *止损触发: {name}*\n"
                    f"现价 {display_cur}{price_in_cost_cur:.2f} ≤ 止损 {display_cur}{sl['price']:.2f}\n"
                    f"成本 {display_cur}{avg:.2f} ({change_pct:+.1f}%)\n"
                    f"操作: {sl['action']}"
                )
                continue

        # Check targets
        for t in item["targets"]:
            t_in_ticker = to_ticker_cur(t["price"], t.get("currency", cost_cur))
            if price >= t_in_ticker:
                display_target = f"{'€' if t.get('currency', cost_cur) == 'EUR' else '$'}{t['price']:.2f}"
                alerts.append(
                    f"🎯 *目标达成: {name}*\n"
                    f"现价 {display_cur}{price_in_cost_cur:.2f} ≥ {display_target}\n"
                    f"成本 {display_cur}{avg:.2f} ({change_pct:+.1f}%)\n"
                    f"操作: {t['action']}"
                )
                break

    return alerts


# ── DCA alerts ──────────────────────────────────────────

def check_dca() -> list[str]:
    alerts = []

    for label, ticker in [("VUAA", "VUAA.DE"), ("SXRV", "SXRV.DE")]:
        prices = fetch_historical(ticker, days=7)
        if len(prices) >= 5:
            week_change = (prices[-1] - prices[0]) / prices[0] * 100
            if week_change <= DCA_CONFIG["weekly_drop_threshold"]:
                alerts.append(
                    f"⚠️ *{label} 单周下跌 {week_change:.1f}%*\n"
                    f"阈值 {DCA_CONFIG['weekly_drop_threshold']}%\n"
                    f"建议: 暂停定投，等企稳"
                )

    prices = fetch_historical("VUAA.DE", days=250)
    if len(prices) >= DCA_CONFIG["ma_period"]:
        ma200 = sum(prices[-DCA_CONFIG["ma_period"]:]) / DCA_CONFIG["ma_period"]
        current = prices[-1]
        if current < ma200:
            pct = (current - ma200) / ma200 * 100
            alerts.append(
                f"📉 *VUAA 跌破200日线*\n"
                f"现价 {current:.2f} < MA200 {ma200:.2f} ({pct:+.1f}%)\n"
                f"建议: 暂停定投，等站回均线"
            )

    return alerts


# ── Main ────────────────────────────────────────────────

def main():
    now = datetime.now(timezone.utc)
    print(f"=== Portfolio Monitor — {now.strftime('%Y-%m-%d %H:%M UTC')} ===\n")

    print("── FX rate ──")
    eurusd = fetch_eurusd()
    print(f"  EUR/USD: {eurusd:.4f}\n")

    all_alerts = []

    print("── Sell targets ──")
    all_alerts.extend(check_targets(eurusd))

    print("\n── DCA conditions ──")
    all_alerts.extend(check_dca())

    if not all_alerts:
        print("\n✅ No alerts. All quiet.")
        return

    today = now.strftime("%Y-%m-%d")
    msg_lines = [f"📊 *Portfolio Monitor — {today}*\n"]
    for alert in all_alerts:
        msg_lines.append(escape_md(alert) + "\n")

    msg = "\n".join(msg_lines)
    print("\n── Sending ──")
    send_telegram(msg)
    print("Done.")


if __name__ == "__main__":
    main()
