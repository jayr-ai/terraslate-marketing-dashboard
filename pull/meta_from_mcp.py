#!/usr/bin/env python3
"""
pull/meta_from_mcp.py - transform raw Meta Ads MCP output into data.json (LOCAL path).

The scheduled agent calls the `ads_get_ad_entities` MCP tool twice (current 30-day daily
series, and prior 30-day total) and saves each raw tool result to a file. This script parses
those files - handling Meta's display formatting like "$18,145.30 USD", "1,600,837", and
"July 12, 2026" - reconciles, and writes data.json. Other channels are preserved untouched.

daily[] is a long-term history (powers the dashboard's date-range toggle), not just the
current window: newly parsed facebook rows overwrite same-date rows (fresher attribution)
but every earlier day is kept, so history only grows across runs. See pull/backfill_merge.py
for the one-time loader that seeded this history from pull/_backfill/chunk*.json.

Usage:
  python3 pull/meta_from_mcp.py <daily_result.json> <prior_result.json>

Each input file is whatever the MCP tool returned: either the full {"ad_entities": "[...]"}
wrapper or the inner array itself. No external dependencies.
"""
import json, re, sys, datetime
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data.json"
MONTHS = {m: i for i, m in enumerate(
    ["January","February","March","April","May","June","July",
     "August","September","October","November","December"], 1)}


def load_rows(path):
    """Accept the MCP wrapper or a bare array; return a list of row dicts."""
    raw = Path(path).read_text().strip()
    obj = json.loads(raw)
    if isinstance(obj, dict) and "ad_entities" in obj:
        obj = obj["ad_entities"]
    if isinstance(obj, str):
        obj = json.loads(obj)
    if isinstance(obj, dict):
        obj = [obj]
    return obj


def money(v):
    if v is None:
        return 0.0
    return round(float(re.sub(r"[^0-9.]", "", str(v)) or 0), 2)


def integer(v):
    if v is None:
        return 0
    return int(re.sub(r"[^0-9]", "", str(v)) or 0)


def to_iso(datestr):
    # "July 12, 2026" -> "2026-07-12"
    m = re.match(r"([A-Za-z]+)\s+(\d+),\s+(\d+)", datestr.strip())
    if not m:
        return datestr  # already ISO, leave it
    mon, day, year = m.group(1), int(m.group(2)), int(m.group(3))
    return f"{year:04d}-{MONTHS[mon]:02d}-{day:02d}"


def normalize(row):
    spend = money(row.get("amount_spent"))
    orders = integer(row.get("actions:omni_purchase"))
    roas = float(row.get("purchase_roas") or 0)
    revenue = round(spend * roas, 2)   # Meta MCP exposes ROAS, not a direct revenue field
    return {"spend": spend, "impressions": integer(row.get("impressions")),
            "clicks": integer(row.get("clicks")), "orders": orders, "revenue": revenue}


def main():
    if len(sys.argv) < 3:
        print("usage: meta_from_mcp.py <daily_result.json> <prior_result.json>", file=sys.stderr)
        sys.exit(2)
    daily_raw = load_rows(sys.argv[1])
    prior_raw = load_rows(sys.argv[2])

    fb_daily, sp, im, cl, od, rev = [], 0.0, 0, 0, 0, 0.0
    for row in sorted(daily_raw, key=lambda r: to_iso(r.get("date_start", ""))):
        n = normalize(row)
        fb_daily.append({"date": to_iso(row["date_start"]), "channel": "facebook", **n})
        sp += n["spend"]; im += n["impressions"]; cl += n["clicks"]; od += n["orders"]; rev += n["revenue"]
    sp, rev = round(sp, 2), round(rev, 2)
    if not fb_daily:
        print("ERROR: no daily rows parsed", file=sys.stderr)
        sys.exit(1)

    p = normalize(prior_raw[0]) if prior_raw else {"spend": 0, "revenue": 0, "orders": 0}
    start, end = fb_daily[0]["date"], fb_daily[-1]["date"]

    d = json.loads(DATA.read_text())
    d["meta"].update({
        "client": "TerraSlate Paper", "currency": "USD", "reportingTz": "America/Denver",
        "windowLabel": "Last 30 days", "dateStart": start, "dateEnd": end,
        "priorLabel": "Prior 30 days", "generatedAt": datetime.date.today().isoformat(),
    })
    pulled_dates = {r["date"] for r in fb_daily}
    kept = [r for r in d.get("daily", [])
            if r.get("channel") != "facebook" or r["date"] not in pulled_dates]
    d["daily"] = sorted(kept + fb_daily, key=lambda r: (r["date"], r["channel"]))
    d["channels"]["facebook"] = {
        "connected": True, "label": "Facebook / Instagram", "kind": "ads",
        "attribution": "Meta default (mixed per ad set)",
        "spend": sp, "impressions": im, "clicks": cl, "orders": od, "revenue": rev,
        "revenueBasis": "derived from purchase ROAS",
    }
    d["prior"] = {"spend": p["spend"], "revenue": p["revenue"], "orders": p["orders"],
                  "blendedRoas": round(p["revenue"] / p["spend"], 2) if p["spend"] else None}
    DATA.write_text(json.dumps(d, indent=2))
    print(f"OK parsed Meta {start} to {end}: spend ${sp:,.2f}, revenue ${rev:,.2f}, orders {od}, {len(fb_daily)} days")


if __name__ == "__main__":
    main()
