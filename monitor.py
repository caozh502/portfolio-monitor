#!/usr/bin/env python3
"""
Portfolio Monitor — daily close report with weekly / quarterly extras.
Fetches portfolio from Trading212, analyses positions, sends Telegram briefing.
"""
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, date

from trading212 import fetch_portfolio, fetch_cash, enrich_positions


# ── Report type detection ────────────────────────────────

def report_type(now: datetime) -> str:
    """Determine report type: 'daily', 'weekly', or 'quarterly'."""
    wd = now.weekday()  # Mon=0, Sun=6
    m = now.month
    d = now.day

    is_friday = wd == 4
    is_quarter_month = m in (3, 6, 9, 12)

    # Quarter-end: last 3 trading days of Mar/Jun/Sep/Dec
    if is_quarter_month and wd < 5:  # weekday
        # Approximate last week of the month
        last_day = {3: 31, 6: 30, 9: 30, 12: 31}[m]
        days_from_end = last_day - d
        if 0 <= days_from_end <= 3:
            return "quarterly"

    if is_friday:
        return "weekly"
    return "daily"


def quarter_label(m: int) -> str:
    return {1: "Q1", 2: "Q1", 3: "Q2", 4: "Q2", 5: "Q2",
            6: "Q2", 7: "Q3", 8: "Q3", 9: "Q3",
            10: "Q4", 11: "Q4", 12: "Q4"}[m]


# ── Price helpers ────────────────────────────────────────

def fetch_today_data(yahoo_ticker: str) -> dict | None:
    """Fetch today's price and day change.
    Uses range=2mo to get enough data for prev close + 30d high.
    Computes daily change from actual closes array (not chartPreviousClose meta),
    which is more reliable for European cross-listed stocks.
    """
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_ticker}?interval=1d&range=2mo"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            result = data["chart"]["result"][0]
            meta = result["meta"]
            quotes = result["indicators"]["quote"][0]
            timestamps = result.get("timestamp", [])
            closes_all = quotes.get("close", [])
            # Build (close, ts) pairs and drop None
            pairs = [(c, ts) for c, ts in zip(closes_all, timestamps)
                     if c is not None]
            if len(pairs) < 2:
                return None

            current = float(pairs[-1][0])
            prev_close = float(pairs[-2][0])
            change_pct = (current - prev_close) / prev_close * 100 if prev_close else 0

            # True 30-day high from the data we have (~40 trading days)
            closes_only = [c for c, _ in pairs]
            high_30d = max(closes_only[-30:]) if len(closes_only) >= 30 else max(closes_only)

            return {
                "price": current,
                "change_pct": round(change_pct, 2),
                "prev_close": prev_close,
                "high_30d": high_30d,
                "is_near_high": current >= high_30d * 0.97 if high_30d else False,
            }
    except Exception as e:
        print(f"  [WARN] {yahoo_ticker}: {e}")
        return None


def fetch_weekly_data(yahoo_ticker: str) -> dict | None:
    """Fetch price change over the last 5 trading days.
    Computes from actual closes in the data, not meta fields.
    Uses range=1mo for enough historical data.
    """
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{yahoo_ticker}?interval=1d&range=1mo"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            quotes = data["chart"]["result"][0]["indicators"]["quote"][0]
            timestamps = data["chart"]["result"][0].get("timestamp", [])
            closes_all = quotes.get("close", [])
            closes = [c for c in closes_all if c is not None]
            if len(closes) < 6:
                return None
            # Compare last close vs close 5 trading days ago
            week_change = (closes[-1] - closes[-6]) / closes[-6] * 100
            return {"week_change_pct": round(week_change, 2)}
    except Exception as e:
        print(f"  [WARN] weekly {yahoo_ticker}: {e}")
        return None


def fetch_eurusd() -> float:
    url = "https://query1.finance.yahoo.com/v8/finance/chart/EURUSD=X?interval=1d&range=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return float(data["chart"]["result"][0]["meta"]["regularMarketPrice"])
    except Exception:
        return 1.08


# ── Sell logic ───────────────────────────────────────────

def suggest_limit(today: dict, avg_cost: float, currency: str) -> dict | None:
    price = today["price"]
    profit_pct = (price - avg_cost) / avg_cost * 100
    if today["is_near_high"]:
        limit = round(today["high_30d"], 2)
        reason = f"接近30日高，设限价于{today['high_30d']:.2f}"
    elif today["change_pct"] > 0:
        limit = round(price * 1.03, 2)
        reason = f"今日上涨+{today['change_pct']:.1f}%，限价+3%"
    else:
        limit = round(price * 1.02, 2)
        reason = f"今日下跌{today['change_pct']:.1f}%，限价+2%等反弹"
    return {
        "limit_price": limit, "currency": currency,
        "current_price": round(price, 2),
        "profit_pct": round(profit_pct, 1),
        "avg_cost": round(avg_cost, 2), "reason": reason,
    }


# ── Telegram ─────────────────────────────────────────────

def send_telegram(message: str):
    token = os.environ.get("TG_BOT_TOKEN", "")
    chat_id = os.environ.get("TG_CHAT_ID", "")
    if not token or not chat_id:
        print("[SKIP] No TG secrets")
        print(message)
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id, "text": message,
        "disable_web_page_preview": True,
    }).encode()
    req = urllib.request.Request(url, data=payload,
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=15)
        print("  [OK] Telegram sent")
    except Exception as e:
        print(f"  [ERROR] Telegram: {e}")


# ── Report builders ─────────────────────────────────────

def build_daily(enriched, total_pos_value, free_cash, total_ppl, today):
    """Standard daily report."""
    total_val = total_pos_value + free_cash
    with_today = [e for e in enriched if e.get("today")]
    gainers = sorted(with_today, key=lambda e: e["today"]["change_pct"], reverse=True)[:3]
    losers = sorted(with_today, key=lambda e: e["today"]["change_pct"])[:3]
    sell_signals = [e["sell_signal"] for e in enriched if e.get("sell_signal")]
    up = sum(1 for e in with_today if e["today"]["change_pct"] > 0)
    dn = sum(1 for e in with_today if e["today"]["change_pct"] < 0)

    lines = [f"📊 收盘日报 — {today}\n"]
    lines.append(f"总净值 €{total_val:,.0f}")
    lines.append(f"持仓 €{total_pos_value:,.0f}  ·  现金 €{free_cash:,.0f}")
    lines.append(f"累计盈亏 €{total_ppl:+,.0f}   |   今日 {up}涨 {dn}跌\n")

    if gainers and gainers[0]["today"]["change_pct"] > 0:
        lines.append("📈 涨幅前3")
        for e in gainers:
            d = e["today"]
            lines.append(f"  {e['cs']}  {e['display']}{d['price']:.2f}  ({d['change_pct']:+.1f}%)")
        lines.append("")

    if losers and losers[0]["today"]["change_pct"] < 0:
        lines.append("📉 跌幅前3")
        for e in losers:
            d = e["today"]
            lines.append(f"  {e['cs']}  {e['display']}{d['price']:.2f}  ({d['change_pct']:+.1f}%)")
        lines.append("")

    if sell_signals:
        lines.append(f"💡 卖出建议 ({len(sell_signals)}个)")
        for s in sell_signals[:5]:
            lines.append(f"  {s['name']}  盈利{s['profit_pct']:+.1f}%")
            lines.append(f"    限价: {s['currency']}{s['limit_price']}  |  现价 {s['currency']}{s['current_price']}")
        lines.append("")

    near_high = [e for e in with_today if e["today"]["is_near_high"] and e["ppl"] > 0]
    if near_high:
        lines.append("🔔 接近高位（关注）")
        for e in near_high[:3]:
            d = e["today"]
            lines.append(f"  {e['cs']}  {e['display']}{d['price']:.2f} (30日高 {e['display']}{d['high_30d']:.2f})")
        lines.append("")

    return "\n".join(lines)


def build_weekly(enriched, total_pos_value, free_cash, total_ppl, today):
    """Weekly report — adds weekly change column."""
    total_val = total_pos_value + free_cash
    with_today = [e for e in enriched if e.get("today")]
    sell_signals = [e["sell_signal"] for e in enriched if e.get("sell_signal")]
    up_d = sum(1 for e in with_today if e["today"]["change_pct"] > 0)
    dn_d = sum(1 for e in with_today if e["today"]["change_pct"] < 0)

    # Weekly movers
    weekly_movers = [(e, e.get("weekly", {}).get("week_change_pct", 0))
                     for e in with_today if e.get("weekly")]
    weekly_gainers = sorted(weekly_movers, key=lambda x: -x[1])[:3]
    weekly_losers = sorted(weekly_movers, key=lambda x: x[1])[:3]

    lines = [f"📅 周报 — {today}\n"]
    lines.append(f"总净值 €{total_val:,.0f}")
    lines.append(f"持仓 €{total_pos_value:,.0f}  ·  现金 €{free_cash:,.0f}")
    lines.append(f"累计盈亏 €{total_ppl:+,.0f}   |   今日 {up_d}涨 {dn_d}跌\n")

    # Weekly top movers
    if weekly_gainers:
        lines.append("📈 本周涨幅前3")
        for e, chg in weekly_gainers:
            lines.append(f"  {e['cs']}  ({chg:+.1f}%)")
        lines.append("")

    if weekly_losers:
        lines.append("📉 本周跌幅前3")
        for e, chg in weekly_losers:
            lines.append(f"  {e['cs']}  ({chg:+.1f}%)")
        lines.append("")

    # Sell signals
    if sell_signals:
        lines.append(f"💡 卖出建议")
        for s in sell_signals[:5]:
            lines.append(f"  {s['name']}  盈利{s['profit_pct']:+.1f}%")
            lines.append(f"    限价: {s['currency']}{s['limit_price']}")
        lines.append("")

    lines.append("💡 下周关注：财报、宏观数据")
    return "\n".join(lines)


def build_quarterly(enriched, total_pos_value, free_cash, total_ppl, today):
    """Quarterly report — full allocation review + rebalancing suggestions."""
    total_val = total_pos_value + free_cash
    q = quarter_label(datetime.now().month)
    with_today = [e for e in enriched if e.get("today")]

    # Sector allocation
    sectors = {}
    for e in enriched:
        sec = "科技" if e["cs"] in ("AAOI","AXTI","SOI","2DG","IFX","INL","9MW","TSFA",
                                     "YDX","NOA3","4S0","ABEA","GOOGL","SPX","SXRV","VUAA","DRAM") else \
              "工业" if e["cs"] in ("LPK",) else \
              "公用事业" if e["cs"] in ("FLNC",) else \
              "通信" if e["cs"] in ("6RJ",) else "其他"
        sectors[sec] = sectors.get(sec, 0) + e["value"]

    # Compare vs target allocation
    target_allocation = {
        "宽基ETF": 0.30,    # VUAA/SXRV
        "科技成长": 0.25,
        "半导体": 0.15,
        "防御/债券": 0.10,
        "现金": 0.20,
    }

    # Map current to categories
    etf_val = sum(e["value"] for e in enriched if e["cs"] in ("VUAA","SXRV"))
    semi_val = sum(e["value"] for e in enriched if e["cs"] in ("SOI","2DG","XFAB","AXTI","TSFA","IFX","INL","DRAM"))
    tech_val = sum(e["value"] for e in enriched if e["cs"] not in ("VUAA","SXRV","SOI","2DG","XFAB","AXTI","TSFA","IFX","INL","DRAM","LPK","FLNC","6RJ","NPA"))
    other_val = total_pos_value - etf_val - semi_val - tech_val

    sell_signals = [e["sell_signal"] for e in enriched if e.get("sell_signal")]

    lines = [f"📊 季度报告 — {q} {today}\n"]
    lines.append(f"总净值 €{total_val:,.0f}")
    lines.append(f"持仓 €{total_pos_value:,.0f}  ·  现金 €{free_cash:,.0f}")
    lines.append(f"累计盈亏 €{total_ppl:+,.0f}\n")

    # Allocation review
    lines.append("📋 配置分析")
    cats = [
        ("宽基ETF", etf_val, target_allocation["宽基ETF"]),
        ("科技成长", tech_val, target_allocation["科技成长"]),
        ("半导体", semi_val, target_allocation["半导体"]),
        ("其他", other_val, 0.05),
        ("现金", free_cash, target_allocation["现金"]),
    ]
    for label, val, target_pct in cats:
        actual_pct = val / total_val * 100
        target_show = target_pct * 100
        diff = actual_pct - target_show
        marker = "✅" if abs(diff) < 5 else ("🔴偏高" if diff > 0 else "🔵偏低")
        lines.append(f"  {label:<8}  {actual_pct:>5.1f}%  (目标{target_show:.0f}%)  {marker}")
    lines.append("")

    # Rebalancing suggestions
    suggestions = []
    if abs(etf_val / total_val - target_allocation["宽基ETF"]) > 0.05:
        if etf_val / total_val < target_allocation["宽基ETF"]:
            suggestions.append(f"  宽基ETF({etf_val/total_val*100:.0f}%)偏低，建议定投增加")
        else:
            suggestions.append(f"  宽基ETF({etf_val/total_val*100:.0f}%)偏高，考虑止盈部分")

    if free_cash / total_val > 0.40:
        suggestions.append(f"  现金比例{free_cash/total_val*100:.0f}%偏高，建议分批入场")

    if len(enriched) > 15:
        suggestions.append(f"  持有{len(enriched)}个标的偏多，建议精简到12-15个")

    if sell_signals:
        suggestions.append(f"  {len(sell_signals)}个标的有卖出信号")

    if suggestions:
        lines.append("🔄 调仓建议")
        for s in suggestions:
            lines.append(s)
        lines.append("")

    # Current holdings summary
    lines.append("📌 当前持仓")
    sorted_pos = sorted(enriched, key=lambda e: -e["value"])
    for e in sorted_pos[:10]:
        pct = e["value"] / total_val * 100
        lines.append(f"  {e['cs']:>6}  {e['display']}{e['price_t212']:<8}  {pct:>4.1f}%  PPL{e['display']}{e['ppl']:<+}")
    if len(sorted_pos) > 10:
        lines.append(f"  ... 还有{len(sorted_pos)-10}个标的")
    lines.append("")

    return "\n".join(lines)


# ── Main ────────────────────────────────────────────────

def main():
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    rtype = report_type(now)
    print(f"=== Portfolio Monitor ({rtype}) — {today} {now.strftime('%H:%M')} UTC ===\n")

    # 1. Fetch
    positions = fetch_portfolio()
    if not positions:
        print("  No positions. Exiting.")
        return
    enrich_positions(positions)

    cash_data = fetch_cash()
    free_cash = float(cash_data.get("free", 0)) if cash_data else 0
    eurusd = fetch_eurusd()
    print(f"  {len(positions)} positions, EUR/USD={eurusd:.4f}\n")

    # 2. Analyse each position
    enriched = []
    total_pos_value = 0
    total_ppl = 0

    for pos in positions:
        cs = pos["clean_symbol"]
        yt = pos["yahoo_ticker"]
        qty = float(pos["quantity"])
        avg = float(pos["averagePrice"])
        curr_t212 = float(pos["currentPrice"])
        ppl = pos["total_ppl"]
        val = pos["current_value"]
        cur = pos.get("currency", "EUR")
        display = "$" if cur == "USD" else "€"
        total_pos_value += val
        total_ppl += ppl

        entry = {
            "cs": cs, "yt": yt, "qty": qty, "avg": avg,
            "price_t212": curr_t212, "ppl": ppl, "value": val,
            "cur": cur, "display": display,
            "today": None, "weekly": None, "sell_signal": None,
        }

        if not yt:
            raw_ticker = pos.get("ticker", "?")
            print(f"  {cs}: no Yahoo ticker (raw={raw_ticker})")
            enriched.append(entry)
            continue

        today_data = fetch_today_data(yt)
        entry["today"] = today_data

        if not today_data:
            raw_ticker = pos.get("ticker", "?")
            print(f"  {cs}: no live data (yt={yt}, raw={raw_ticker})")

        if today_data:
            entry["price_live"] = today_data["price"]
            pct_chg = (curr_t212 - avg) / avg * 100 if avg else 0
            line = (f"  {cs:>6} {display}{today_data['price']:<8} "
                    f"日涨跌{today_data['change_pct']:>+6.1f}%  "
                    f"PPL{display}{ppl:<+8}")
            print(line)
            # Full data for portfolio analysis
            print(f"    qty={qty:.0f} avg={display}{avg:.2f} val={display}{val:.0f} "
                  f"pct_chg_from_avg={pct_chg:+.1f}% cur={cur}")

            # Weekly data (only needed for weekly/quarterly reports)
            if rtype in ("weekly", "quarterly"):
                wk = fetch_weekly_data(yt)
                entry["weekly"] = wk
                if wk:
                    line += f"  周涨跌{wk['week_change_pct']:>+6.1f}%"

            # Sell signal
            if ppl > 20 or (ppl > 0 and (curr_t212 - avg) / avg * 100 > 5):
                signal = suggest_limit(today_data, avg, display)
                if signal:
                    signal["name"] = f"{cs} ({yt})"
                    signal["qty"] = qty
                    entry["sell_signal"] = signal
                    print(f"    → 建议限价卖: {display}{signal['limit_price']} ({signal['reason']})")
        else:
            print(f"  {cs}: no live data")

        enriched.append(entry)

    # 3. Build report by type
    if rtype == "quarterly":
        msg = build_quarterly(enriched, total_pos_value, free_cash, total_ppl, today)
    elif rtype == "weekly":
        msg = build_weekly(enriched, total_pos_value, free_cash, total_ppl, today)
    else:
        msg = build_daily(enriched, total_pos_value, free_cash, total_ppl, today)

    print(f"\n── Sending ({rtype}) ──")
    send_telegram(msg)
    print("Done.")


if __name__ == "__main__":
    main()
