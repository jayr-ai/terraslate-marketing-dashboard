#!/usr/bin/env python3
"""
build_dashboard.py - the reconcile + derive gate for the consolidated marketing dashboard.

Reads data.json (which the pull step has already filled with per-channel headline numbers
and, optionally, a `daily` array of {date, channel, spend, impressions, clicks, orders, revenue}
rows). It then:

  1. RECONCILES: if daily rows exist for a connected channel, their sums must equal that
     channel's headline totals (orders/clicks/impressions exact; spend/revenue within $0.01).
     A mismatch exits non-zero so a wrong dashboard can never be published.
  2. DERIVES: computes every ratio the dashboard shows (ROAS, CTR, CPC, CVR, AOV, CAC, and
     ACoS/TACoS for marketplaces), grand totals across connected channels, the blended
     ROAS / MER, and period-over-period deltas vs `prior`.
  3. GENERATES INSIGHTS: ranks anomalies (big deltas, best/worst ROAS, marketplace ACoS,
     disconnected sources) into data.insights so the narrative is never hand-typed.

Nothing here writes HTML. Numbers live in data.json; render.js turns them into the page.
Run: python3 build_dashboard.py
"""
import json, sys, datetime
from pathlib import Path

DATA = Path(__file__).with_name("data.json")
CENT = 0.011  # spend/revenue tolerance in dollars

def die(msg):
    print(f"RECONCILE FAIL: {msg}", file=sys.stderr)
    sys.exit(1)

def pct_delta(now, was):
    if not was:
        return None
    return round((now - was) / was * 100, 1)

def safe_div(a, b):
    return round(a / b, 2) if b else None

def main():
    d = json.loads(DATA.read_text())
    channels = d["channels"]
    daily = d.get("daily", [])
    win_start, win_end = d["meta"]["dateStart"], d["meta"]["dateEnd"]

    # ---- 1. RECONCILE per-channel daily -> headline ---------------------------
    # daily[] can hold long-term history (for the client-side date-range toggle); only the
    # rows inside the current headline window [dateStart, dateEnd] must reconcile to it.
    window_rows = [r for r in daily if win_start <= r["date"] <= win_end]
    if window_rows:
        agg = {}
        for r in window_rows:
            c = r["channel"]
            a = agg.setdefault(c, {"spend": 0.0, "impressions": 0, "clicks": 0, "orders": 0, "revenue": 0.0})
            a["spend"] += r.get("spend", 0)
            a["impressions"] += r.get("impressions", 0)
            a["clicks"] += r.get("clicks", 0)
            a["orders"] += r.get("orders", 0)
            a["revenue"] += r.get("revenue", 0)
        for c, head in channels.items():
            if not head.get("connected"):
                continue
            if c not in agg:
                die(f"channel '{c}' is connected but has no daily rows")
            a = agg[c]
            for intfield in ("impressions", "clicks", "orders"):
                if int(a[intfield]) != int(head.get(intfield, 0)):
                    die(f"{c} {intfield}: daily sum {int(a[intfield])} != headline {head.get(intfield)}")
            for cash in ("spend", "revenue"):
                if abs(a[cash] - head.get(cash, 0)) > CENT:
                    die(f"{c} {cash}: daily sum {a[cash]:.2f} != headline {head.get(cash,0):.2f}")

    # ---- 2. DERIVE per-channel ratios ----------------------------------------
    connected = {c: h for c, h in channels.items() if h.get("connected")}
    for c, h in channels.items():
        h["roas"] = safe_div(h.get("revenue", 0), h.get("spend", 0))
        h["ctr"] = safe_div(h.get("clicks", 0) * 100.0, h.get("impressions", 0))
        h["cpc"] = safe_div(h.get("spend", 0), h.get("clicks", 0))
        h["cvr"] = safe_div(h.get("orders", 0) * 100.0, h.get("clicks", 0))
        h["aov"] = safe_div(h.get("revenue", 0), h.get("orders", 0))
        if h.get("newCustomers"):
            h["cac"] = safe_div(h.get("spend", 0), h["newCustomers"])
        if h.get("kind") == "marketplace" and h.get("connected"):
            # ACoS = ad spend / ad-attributed revenue; TACoS = ad spend / total revenue
            h["acos"] = safe_div(h.get("spend", 0) * 100.0, h.get("adRevenue", 0))
            h["tacos"] = safe_div(h.get("spend", 0) * 100.0, h.get("totalRevenue", h.get("revenue", 0)))

    # ---- 2b. DERIVE grand totals + blended -----------------------------------
    tot = {"spend": 0.0, "revenue": 0.0, "orders": 0, "clicks": 0, "impressions": 0, "newCustomers": 0}
    for h in connected.values():
        tot["spend"] += h.get("spend", 0)
        tot["revenue"] += h.get("revenue", 0)
        tot["orders"] += h.get("orders", 0)
        tot["clicks"] += h.get("clicks", 0)
        tot["impressions"] += h.get("impressions", 0)
        tot["newCustomers"] += h.get("newCustomers", 0)
    tot["spend"] = round(tot["spend"], 2)
    tot["revenue"] = round(tot["revenue"], 2)
    tot["aov"] = safe_div(tot["revenue"], tot["orders"])
    tot["blendedRoas"] = safe_div(tot["revenue"], tot["spend"])  # a.k.a. MER
    tot["cac"] = safe_div(tot["spend"], tot["newCustomers"])

    prior = d.get("prior", {})
    tot["delta"] = {
        "spend": pct_delta(tot["spend"], prior.get("spend")),
        "revenue": pct_delta(tot["revenue"], prior.get("revenue")),
        "orders": pct_delta(tot["orders"], prior.get("orders")),
        "blendedRoas": pct_delta(tot["blendedRoas"] or 0, prior.get("blendedRoas")),
    }

    # spend / revenue mix shares (for the channel-mix panel)
    for c, h in channels.items():
        h["spendShare"] = safe_div(h.get("spend", 0) * 100.0, tot["spend"]) if h.get("connected") else 0
        h["revenueShare"] = safe_div(h.get("revenue", 0) * 100.0, tot["revenue"]) if h.get("connected") else 0

    # ---- 3. GENERATE INSIGHTS (ranked) ---------------------------------------
    ins = []
    ranked = sorted(connected.items(), key=lambda kv: (kv[1].get("roas") or 0))
    if ranked:
        worst_c, worst = ranked[0]
        best_c, best = ranked[-1]
        if best.get("roas"):
            ins.append({"severity": "info",
                        "text": f"{best['label']} is the strongest channel at {best['roas']}x ROAS on ${best['spend']:,.0f} spend."})
        if worst.get("roas") is not None and worst.get("roas") < 2 and worst["spend"] > 0:
            ins.append({"severity": "high",
                        "text": f"{worst['label']} ROAS is {worst['roas']}x, below a 2x break-even guide on ${worst['spend']:,.0f} spend - review targeting/creative."})
    for c, h in connected.items():
        if h.get("kind") == "marketplace" and h.get("acos") is not None and h["acos"] > 35:
            ins.append({"severity": "high",
                        "text": f"{h['label']} ACoS is {h['acos']}% (ad spend eating >35% of ad sales); tighten bids or negative keywords."})
    if tot["delta"]["revenue"] is not None and abs(tot["delta"]["revenue"]) >= 30:
        arrow = "up" if tot["delta"]["revenue"] > 0 else "down"
        ins.append({"severity": "high",
                    "text": f"Total revenue is {arrow} {abs(tot['delta']['revenue'])}% vs the prior period - investigate the driving channel."})
    for c, h in channels.items():
        if not h.get("connected"):
            ins.append({"severity": "warn",
                        "text": f"{h['label']} is not connected - its tiles read NO DATA and it is excluded from blended totals."})

    d["totals"] = tot
    d["insights"] = ins
    d["provenance"] = [
        {"source": h["label"],
         "connected": h.get("connected", False),
         "attribution": h.get("attribution", ""),
         "dateRange": f"{d['meta']['dateStart']} to {d['meta']['dateEnd']}"}
        for h in channels.values()
    ]
    d["meta"]["builtAt"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")

    DATA.write_text(json.dumps(d, indent=2))
    print(f"OK reconciled + derived: blended ROAS {tot['blendedRoas']}x on ${tot['spend']:,.0f} spend, "
          f"${tot['revenue']:,.0f} revenue, {len(ins)} insights.")

if __name__ == "__main__":
    main()
