#!/usr/bin/env python3
"""
Weekly Portfolio Review — snapshots, diff, evaluation, Telegram report.
Compares current week vs previous week to summarise trading activity.
"""
import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trading212 import fetch_portfolio, fetch_cash, enrich_positions

# ── Config ──────────────────────────────────────────────────────────
MAX_SNAPSHOTS = 52  # Keep 1 year of weekly snapshots
SNAPSHOT_DIR = Path(__file__).resolve().parent.parent / "snapshots"
EURUSD_DEFAULT = 1.08

# Chinese ticker names (same as monitor.py convention)
TICKER_NAMES = {
    "NVDA": "英伟达", "TSLA": "特斯拉", "GOOGL": "谷歌", "MSFT": "微软",
    "AMZN": "亚马逊", "MRVL": "迈威尔科技", "RKLB": "火箭实验室",
    "PLTR": "Palantir", "TSM": "台积电", "AMD": "AMD", "MU": "美光",
    "INTC": "英特尔", "AVGO": "博通", "AMAT": "应用材料",
    "AAOI": "AAOI", "SOI": "Soitec", "2DG": "Sivers", "IFX": "英飞凌",
    "LPK": "LPKF", "XFAB": "X-FAB", "AXTI": "AXTI",
    "VUAA": "标普500ETF", "SXRV": "纳斯达克ETF", "DRAM": "存储ETF",
    "NPA": "NPA",
}

# ── Helpers ─────────────────────────────────────────────────────────

# Sector ETFs for weekly fund flow reference
SECTORS = {
    "XLF": "金融", "XLK": "科技", "XLV": "医疗",
    "XLE": "能源", "XLI": "工业", "XLP": "必需消费",
    "XLU": "公用事业", "XLB": "材料", "XLY": "可选消费",
    "XLC": "通信", "IBB": "生物科技",
}

def week_label(dt: datetime) -> str:
    iso = dt.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def fetch_eurusd() -> float:
    url = "https://query1.finance.yahoo.com/v8/finance/chart/EURUSD=X?interval=1d&range=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return float(data["chart"]["result"][0]["meta"]["regularMarketPrice"])
    except Exception:
        return EURUSD_DEFAULT


def fetch_sector_weekly() -> list[dict]:
    """Fetch weekly performance for all sector ETFs. Returns sorted list."""
    results = []
    for ticker, name in SECTORS.items():
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=1mo"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read())
                quotes = data["chart"]["result"][0]["indicators"]["quote"][0]
                closes = [c for c in quotes.get("close", []) if c is not None]
                if len(closes) >= 6:
                    wk_chg = (closes[-1] - closes[-6]) / closes[-6] * 100
                    results.append({
                        "ticker": ticker, "name": name,
                        "weekly_chg": round(wk_chg, 1),
                    })
        except Exception as e:
            print(f"  [WARN] sector {ticker}: {e}")
    results.sort(key=lambda x: -x["weekly_chg"])
    return results


def send_telegram(message: str):
    """Send report via Telegram Bot API (sync, no async needed)."""
    token = os.environ.get("TG_BOT_TOKEN", "")
    chat_id = os.environ.get("TG_CHAT_ID", "")
    if not token or not chat_id:
        print("[SKIP] No TG secrets — printing report instead")
        print(message)
        return
    # Telegram limit: 4096 chars, split if needed
    max_len = 4000
    parts = []
    if len(message) <= max_len:
        parts = [message]
    else:
        current = []
        for line in message.split("\n"):
            current.append(line)
            if sum(len(l) + 1 for l in current) > max_len:
                parts.append("\n".join(current[:-1]))
                current = [current[-1]]
        if current:
            parts.append("\n".join(current))

    for i, part in enumerate(parts):
        payload = json.dumps({
            "chat_id": chat_id, "text": part,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req, timeout=15)
            print(f"  [OK] Part {i+1}/{len(parts)} sent ({len(part)} chars)")
        except Exception as e:
            print(f"  [ERROR] Telegram part {i+1}: {e}")


# ── Snapshot ────────────────────────────────────────────────────────

def build_snapshot(positions: list[dict], cash: float, total_ppl: float,
                   eurusd: float, label: str, now_str: str) -> dict:
    """Build a snapshot dict from current portfolio data."""
    total_pos_value = sum(p["current_value"] for p in positions)
    pos_list = []
    for p in positions:
        cs = p.get("clean_symbol", "")
        qty = float(p.get("quantity", 0))
        avg = float(p.get("averagePrice", 0))
        curr = float(p.get("currentPrice", 0))
        val = p["current_value"]
        ppl = p.get("total_ppl", 0)
        weight = (val / total_pos_value * 100) if total_pos_value > 0 else 0
        cur = p.get("currency", "EUR")
        pos_list.append({
            "ticker": cs,
            "name": TICKER_NAMES.get(cs, cs),
            "qty": round(qty, 4),
            "avg_price": round(avg, 4),
            "current_price": round(curr, 4),
            "value": round(val, 2),
            "ppl": round(ppl, 2),
            "currency": cur,
            "weight_pct": round(weight, 1),
        })
    pos_list.sort(key=lambda x: -x["value"])

    return {
        "week": label,
        "date": now_str,
        "eurusd": round(eurusd, 4),
        "total_position_value": round(total_pos_value, 2),
        "free_cash": round(cash, 2),
        "total_value": round(total_pos_value + cash, 2),
        "total_ppl": round(total_ppl, 2),
        "position_count": len(pos_list),
        "positions": pos_list,
    }


def save_snapshot(snapshot: dict):
    """Write snapshot JSON to disk."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOT_DIR / f"{snapshot['week']}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)
    print(f"  [OK] Snapshot saved: {path.name}")
    return path


def load_snapshot(week_label: str) -> dict | None:
    """Load a previous snapshot by week label."""
    path = SNAPSHOT_DIR / f"{week_label}.json"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_previous_week(week_label: str) -> str | None:
    """Find the previous week's snapshot file that actually exists."""
    files = sorted(SNAPSHOT_DIR.glob("*.json"))
    current_idx = None
    for i, f in enumerate(files):
        if f.stem == week_label:
            current_idx = i
            break
    if current_idx and current_idx > 0:
        return files[current_idx - 1].stem
    # Fallback: if current week isn't saved yet, take the last available
    if files:
        return files[-1].stem
    return None


def cleanup_snapshots():
    """Remove snapshots beyond MAX_SNAPSHOTS, keeping the newest ones."""
    files = sorted(SNAPSHOT_DIR.glob("*.json"))
    if len(files) > MAX_SNAPSHOTS:
        to_delete = files[:len(files) - MAX_SNAPSHOTS]
        for f in to_delete:
            f.unlink()
            print(f"  [CLEANUP] Removed old snapshot: {f.name}")


# ── Diff & Analysis ────────────────────────────────────────────────

def diff_snapshots(current: dict, previous: dict) -> dict:
    """Compare two snapshots and summarise changes."""
    cur_pos = {p["ticker"]: p for p in current["positions"]}
    prev_pos = {p["ticker"]: p for p in previous["positions"]}

    # Detect changes
    new_positions = []
    closed_positions = []
    increased_positions = []
    decreased_positions = []

    all_tickers = set(list(cur_pos.keys()) + list(prev_pos.keys()))

    for t in all_tickers:
        cp = cur_pos.get(t)
        pp = prev_pos.get(t)
        if cp and not pp:
            new_positions.append(cp)
        elif pp and not cp:
            closed_positions.append(pp)
        elif cp and pp:
            qty_diff = cp["qty"] - pp["qty"]
            if qty_diff > 0.001:
                increased_positions.append({
                    "ticker": t, "name": cp["name"],
                    "prev_qty": pp["qty"], "new_qty": cp["qty"],
                    "added_qty": round(qty_diff, 4),
                    "currency": cp["currency"],
                })
            elif qty_diff < -0.001:
                decreased_positions.append({
                    "ticker": t, "name": cp["name"],
                    "prev_qty": pp["qty"], "new_qty": cp["qty"],
                    "removed_qty": round(-qty_diff, 4),
                    "currency": cp["currency"],
                })

    # Value changes
    total_val_change = current["total_value"] - previous["total_value"]
    total_val_pct = (total_val_change / previous["total_value"] * 100) if previous["total_value"] > 0 else 0
    ppl_change = current["total_ppl"] - previous["total_ppl"]
    cash_change = current["free_cash"] - previous["free_cash"]

    # Position count change
    count_change = current["position_count"] - previous["position_count"]

    # Weight changes for top positions
    weight_changes = {}
    for t in all_tickers:
        cp = cur_pos.get(t)
        pp = prev_pos.get(t)
        if cp and pp:
            w_diff = cp["weight_pct"] - pp["weight_pct"]
            if abs(w_diff) > 0.5:  # Only report meaningful changes
                weight_changes[t] = {
                    "name": cp["name"],
                    "prev_wt": pp["weight_pct"],
                    "new_wt": cp["weight_pct"],
                    "diff": round(w_diff, 1),
                }

    return {
        "total_val_change": round(total_val_change, 2),
        "total_val_pct": round(total_val_pct, 2),
        "ppl_change": round(ppl_change, 2),
        "cash_change": round(cash_change, 2),
        "count_change": count_change,
        "new_positions": new_positions,
        "closed_positions": closed_positions,
        "increased": increased_positions,
        "decreased": decreased_positions,
        "weight_changes": weight_changes,
        "prev_total": previous["total_value"],
        "cur_total": current["total_value"],
    }


def evaluate_trading(diff: dict, current: dict) -> tuple[str, list[str], list[str]]:
    """
    Grade the week's trading (A/B/C/D) and return (grade, good_points, bad_points).
    Rule-based evaluation.
    """
    good = []
    bad = []
    grade_score = 100  # Start at A, deduct for issues

    # 1. Cash management
    cash_ratio = current["free_cash"] / current["total_value"] * 100 if current["total_value"] > 0 else 0
    if cash_ratio < 10:
        bad.append(f"现金仅{cash_ratio:.0f}%，风险偏高，建议补至20%+")
        grade_score -= 15
    elif cash_ratio > 40:
        good.append(f"现金{cash_ratio:.0f}%充足，可择机加仓")
        grade_score += 5
    elif cash_ratio >= 20:
        good.append(f"现金{cash_ratio:.0f}%合理，仓位管理不错")

    # 2. New positions — good if adding to watchlist, bad if random
    if diff["new_positions"]:
        new_names = ", ".join(f"{p['name']}({p['ticker']})" for p in diff["new_positions"])
        good.append(f"新增仓: {new_names}")
        grade_score += 5

    # 3. Closed positions — assess if it's good discipline
    if diff["closed_positions"]:
        closed_names = ", ".join(f"{p['name']}({p['ticker']})" for p in diff["closed_positions"])
        bad.append(f"清仓: {closed_names}（需确认是主动止损还是其他原因）")
        grade_score -= 10

    # 4. Adding to existing positions — good if adding to winners
    if diff["increased"]:
        names = ", ".join(f"{p['name']}+{p['added_qty']:.0f}股" for p in diff["increased"][:3])
        good.append(f"加仓: {names}")
        grade_score += 5

    # 5. Reducing positions — good if taking profit or cutting losers
    if diff["decreased"]:
        names = ", ".join(f"{p['name']}-{p['removed_qty']:.0f}股" for p in diff["decreased"][:3])
        good.append(f"减仓: {names}")
        grade_score += 5

    # 6. Too many changes in one week
    total_moves = len(diff["increased"]) + len(diff["decreased"]) + len(diff["new_positions"]) + len(diff["closed_positions"])
    if total_moves > 5:
        bad.append(f"本周操作{total_moves}次偏多，注意交易成本")
        grade_score -= 10

    # 7. Concentration risk
    top3_weight = sum(p["weight_pct"] for p in current["positions"][:3]) if current["positions"] else 0
    if top3_weight > 65:
        bad.append(f"前3持仓占{top3_weight:.0f}%，集中度过高")
        grade_score -= 15
    elif top3_weight > 50:
        bad.append(f"前3持仓占{top3_weight:.0f}%，注意分散")
        grade_score -= 5

    # 8. Overall direction — did they trade WITH the market?
    val_change = diff["total_val_pct"]
    if val_change > 0:
        good.append(f"总资产增长{val_change:+.1f}%，方向正确")
        grade_score += 10 if val_change > 5 else 5
    elif val_change < -5:
        bad.append(f"总资产下跌{val_change:.1f}%，注意风险敞口")
        grade_score -= 10

    # Determine grade
    if grade_score >= 90:
        grade = "A"
    elif grade_score >= 75:
        grade = "B"
    elif grade_score >= 60:
        grade = "C"
    else:
        grade = "D"

    return grade, good, bad


# ── Report Builder ─────────────────────────────────────────────────

def build_report(current: dict, previous: dict | None, diff_data: dict | None,
                 grade: str, good: list[str], bad: list[str],
                 sector_flow: list[dict] | None = None) -> str:
    """Build the full Telegram report text."""
    lines = []
    week = current["week"]
    now = datetime.now(timezone.utc)
    now_cest = now.astimezone(timezone(timedelta(hours=2)))
    date_str = now_cest.strftime("%Y-%m-%d %H:%M")

    # Header
    lines.append(f"📊 <b>第{week.split('-W')[1]}周 投资操作复盘</b>")
    lines.append(f"<i>{date_str} CEST</i>")
    lines.append("")

    # ── Operation summary ──
    lines.append("<b>📋 本周操作</b>")
    has_ops = False

    if diff_data and diff_data["new_positions"]:
        has_ops = True
        items = [f"  🟢 {p['name']}({p['ticker']}) 开仓{p['qty']:.0f}股 @ {p['currency']}{p['avg_price']:.2f}"
                 for p in diff_data["new_positions"]]
        lines.extend(items)

    if diff_data and diff_data["closed_positions"]:
        has_ops = True
        items = [f"  🔴 {p['name']}({p['ticker']}) 清仓 (此前{p['qty']:.0f}股)"
                 for p in diff_data["closed_positions"]]
        lines.extend(items)

    if diff_data and diff_data["increased"]:
        has_ops = True
        items = [f"  📈 {p['name']}({p['ticker']}) +{p['added_qty']:.0f}股 → {p['new_qty']:.0f}股"
                 for p in diff_data["increased"]]
        lines.extend(items)

    if diff_data and diff_data["decreased"]:
        has_ops = True
        items = [f"  📉 {p['name']}({p['ticker']}) -{p['removed_qty']:.0f}股 → {p['new_qty']:.0f}股"
                 for p in diff_data["decreased"]]
        lines.extend(items)

    if not has_ops:
        lines.append("  ➖ 本周无操作")
    lines.append("")

    # ── Account changes ──
    lines.append("<b>💰 账户变化</b>")
    if previous and diff_data:
        arrow = "▲" if diff_data["total_val_change"] > 0 else "▼"
        lines.append(f"  总资产 {arrow} €{previous['total_value']:,.0f} → €{current['total_value']:,.0f} ({diff_data['total_val_pct']:+.1f}%)")
        if abs(diff_data["ppl_change"]) > 0.01:
            ppl_arrow = "▲" if diff_data["ppl_change"] > 0 else "▼"
            lines.append(f"  累计盈亏 {ppl_arrow} €{diff_data['ppl_change']:+,.0f}")
        cash_arrow = "▲" if diff_data["cash_change"] > 0 else "▼"
        lines.append(f"  现金 {cash_arrow} €{previous['free_cash']:,.0f} → €{current['free_cash']:,.0f}")
    else:
        lines.append(f"  总资产 €{current['total_value']:,.0f}")
        lines.append(f"  现金 €{current['free_cash']:,.0f}")
    cash_ratio = current["free_cash"] / current["total_value"] * 100 if current["total_value"] > 0 else 0
    lines.append(f"  现金比例 {cash_ratio:.0f}%")
    lines.append("")

    # ── Top holdings ──
    lines.append("<b>📌 当前前5持仓</b>")
    cur = current.get("currency", "€")
    for p in current["positions"][:5]:
        display = "$" if p["currency"] == "USD" else "€"
        pp = ""
        if previous and diff_data and p["ticker"] in diff_data.get("weight_changes", {}):
            wc = diff_data["weight_changes"][p["ticker"]]
            diff_w = wc["diff"]
            w_arrow = "▲" if diff_w > 0 else "▼"
            pp = f" ({w_arrow}{diff_w:+.1f}%)"
        lines.append(
            f"  {p['name']:<8} {p['weight_pct']:>5.1f}%  "
            f"{display}{p['current_price']:<8}  "
            f"{p['qty']:.0f}股  PPL{display}{p['ppl']:+,.0f}{pp}"
        )
    if current["position_count"] > 5:
        lines.append(f"  ... 还有{current['position_count'] - 5}个标的")
    lines.append("")

    # ── Sector Flow ──
    if sector_flow:
        lines.append("<b>🏭 板块资金流向（本周）</b>")
        top3 = sector_flow[:3]
        bot3 = sector_flow[-3:]
        lines.append("  🔥 流入TOP3:")
        for s in top3:
            arrow = "▲" if s["weekly_chg"] > 0 else "▼"
            lines.append(f"    {s['ticker']} {s['name']}  {arrow}{s['weekly_chg']:+.1f}%")
        lines.append("  ❄️ 流出TOP3:")
        for s in reversed(bot3):
            arrow = "▲" if s["weekly_chg"] > 0 else "▼"
            lines.append(f"    {s['ticker']} {s['name']}  {arrow}{s['weekly_chg']:+.1f}%")
        lines.append("")

    # ── Evaluation ──
    lines.append(f"<b>🏆 本周评级: {grade}</b>")
    if good:
        lines.append("  ✅ 好的方面")
        for g in good:
            lines.append(f"    • {g}")
    if bad:
        lines.append("  ⚠️ 待改进")
        for b in bad:
            lines.append(f"    • {b}")
    lines.append("")

    # ── Suggestions ──
    lines.append("<b>🎯 下周行动建议</b>")
    suggestions = []

    # Cash suggestion
    if cash_ratio < 15:
        suggestions.append(f"  现金{cash_ratio:.0f}%偏低，优先补充现金至20%+")
    elif cash_ratio > 35 and (diff_data and len(diff_data.get("new_positions", [])) == 0):
        suggestions.append(f"  现金{cash_ratio:.0f}%充裕，可考虑定投宽基ETF")

    # Concentration
    top1 = current["positions"][0] if current["positions"] else None
    if top1 and top1["weight_pct"] > 25:
        suggestions.append(f"  {top1['name']}占比{top1['weight_pct']:.0f}%偏高，加仓其他标的平衡")

    # Position count
    if current["position_count"] > 15:
        suggestions.append(f"  持有{current['position_count']}个标的偏多，建议精简到12-15个")

    # Loss-making positions
    heavy_losers = [p for p in current["positions"] if p["ppl"] < -500]
    if heavy_losers:
        loser_names = ", ".join(f"{p['name']}({p['ppl']:+.0f})" for p in heavy_losers[:3])
        suggestions.append(f"  大额亏损: {loser_names}，评估是否止损")

    if not suggestions:
        suggestions.append("  当前持仓和现金比例合理，以静制动")

    lines.extend(suggestions)
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━")
    lines.append("⚠️ <i>数据来源：Trading212 API，评价基于规则模型，仅供参考</i>")

    return "\n".join(lines)


# ── Main ───────────────────────────────────────────────────────────

def main():
    now = datetime.now(timezone.utc)
    label = week_label(now)
    # ISO week starts Monday; run on Saturday, so the week label is the CURRENT week
    now_str = now.strftime("%Y-%m-%d %H:%M UTC")
    print(f"=== Weekly Review — {label} ({now_str}) ===\n")

    # 1. Fetch portfolio
    print("Fetching portfolio...")
    positions = fetch_portfolio()
    if not positions:
        print("  No positions. Exiting.")
        return
    enrich_positions(positions)
    print(f"  {len(positions)} positions loaded\n")

    # 2. Fetch cash + EUR/USD
    cash_data = fetch_cash()
    free_cash = float(cash_data.get("free", 0)) if cash_data else 0
    print(f"  Cash: €{free_cash:,.2f}")
    eurusd = fetch_eurusd()
    print(f"  EUR/USD: {eurusd:.4f}\n")

    # 3. Compute PPL
    total_ppl = sum(p.get("total_ppl", 0) for p in positions)

    # 4. Build and save snapshot
    snapshot = build_snapshot(positions, free_cash, total_ppl, eurusd, label, now_str)
    print(f"  Total value: €{snapshot['total_value']:,.2f}")
    save_snapshot(snapshot)

    # 5. Load previous snapshot
    prev_label = get_previous_week(label)
    previous = None
    diff_data = None
    if prev_label:
        previous = load_snapshot(prev_label)
        if previous:
            print(f"  Previous snapshot: {prev_label}")
            diff_data = diff_snapshots(snapshot, previous)
            print(f"  Changes: {len(diff_data['new_positions'])} new, "
                  f"{len(diff_data['closed_positions'])} closed, "
                  f"{len(diff_data['increased'])} increased, "
                  f"{len(diff_data['decreased'])} decreased")
        else:
            print("  No previous snapshot found")
    else:
        print("  No previous snapshot available (first run)")

    # 6. Evaluate
    grade, good, bad = evaluate_trading(diff_data or {}, snapshot)

    # 7. Fetch sector fund flow data
    print("\nFetching sector fund flow...")
    sector_flow = fetch_sector_weekly()
    print(f"  {len(sector_flow)} sectors loaded")
    if sector_flow:
        print(f"  Top inflow: {sector_flow[0]['name']} ({sector_flow[0]['weekly_chg']:+.1f}%)")
        print(f"  Top outflow: {sector_flow[-1]['name']} ({sector_flow[-1]['weekly_chg']:+.1f}%)")

    # 8. Build report
    report = build_report(snapshot, previous, diff_data, grade, good, bad, sector_flow)
    print(f"\n── Report ({len(report)} chars) ──\n")
    print(report)

    # 8. Send
    print(f"\n── Sending to Telegram ──")
    send_telegram(report)

    # 9. Cleanup old snapshots
    print(f"\n── Cleanup ──")
    cleanup_snapshots()

    print("\nDone.")


if __name__ == "__main__":
    main()
