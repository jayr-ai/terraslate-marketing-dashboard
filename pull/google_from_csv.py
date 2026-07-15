#!/usr/bin/env python3
"""
pull/google_from_csv.py - one-time backfill of Google Ads history from the
"TerraSlate Ad Performance Summary" Google Sheet, exported as CSV.

The sheet is one row per day per campaign. This aggregates campaigns within each day into the
unified google channel and merges into data.json (overwriting google rows for the dates it
covers, keeping every other channel and any google days outside the CSV). Reconciles by
construction (headline is derived from daily rows in build_dashboard.py).

CSV columns: EXCLUDE, Day, Campaign Name, Cost (Spend), Conversions, Total conv. value,
             Clicks, Impressions, Conversions By Conversion Date, Conversions Value By Conversion Date

Usage: python3 pull/google_from_csv.py "<path-to-csv>"
"""
import csv, json, sys, re
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data.json"


def num(v):
    if v is None:
        return 0.0
    try:
        return float(str(v).replace(",", "").replace("$", "").strip() or 0)
    except ValueError:
        return 0.0


def main():
    if len(sys.argv) < 2:
        print("usage: google_from_csv.py <path-to-csv>", file=sys.stderr)
        sys.exit(2)
    path = Path(sys.argv[1]).expanduser()
    if not path.exists():
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    by_date = {}
    kept, skipped = 0, 0
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if str(row.get("EXCLUDE", "")).strip().upper() == "TRUE":
                skipped += 1
                continue
            day = str(row.get("Day", "")).strip()
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", day):
                skipped += 1
                continue
            a = by_date.setdefault(day, {"spend": 0.0, "impressions": 0, "clicks": 0, "orders": 0.0, "revenue": 0.0})
            a["spend"] += num(row.get("Cost (Spend)"))
            a["impressions"] += int(num(row.get("Impressions")))
            a["clicks"] += int(num(row.get("Clicks")))
            a["orders"] += num(row.get("Conversions"))
            a["revenue"] += num(row.get("Total conv. value"))
            kept += 1

    if not by_date:
        print("ERROR: no usable rows parsed", file=sys.stderr)
        sys.exit(1)

    g_rows = [{"date": d, "channel": "google", "spend": round(v["spend"], 2),
               "impressions": v["impressions"], "clicks": v["clicks"],
               "orders": int(round(v["orders"])), "revenue": round(v["revenue"], 2)}
              for d, v in by_date.items()]
    g_rows.sort(key=lambda r: r["date"])

    d = json.loads(DATA.read_text())
    pulled = {r["date"] for r in g_rows}
    d["daily"] = [r for r in d.get("daily", []) if r.get("channel") != "google" or r["date"] not in pulled] + g_rows
    d["daily"].sort(key=lambda r: (r["date"], r["channel"]))
    d["channels"]["google"] = {
        "connected": True, "label": "Google Ads", "kind": "ads",
        "attribution": "Google conversion tracking",
        "spend": round(sum(r["spend"] for r in g_rows), 2),
        "impressions": sum(r["impressions"] for r in g_rows),
        "clicks": sum(r["clicks"] for r in g_rows),
        "orders": sum(r["orders"] for r in g_rows),
        "revenue": round(sum(r["revenue"] for r in g_rows), 2),
    }
    DATA.write_text(json.dumps(d, indent=2))
    tot_sp = sum(r["spend"] for r in g_rows)
    tot_rev = sum(r["revenue"] for r in g_rows)
    print(f"OK loaded Google history: {g_rows[0]['date']} to {g_rows[-1]['date']}, "
          f"{len(g_rows)} days, ${tot_sp:,.0f} spend, ${tot_rev:,.0f} revenue "
          f"({kept} rows aggregated, {skipped} skipped/excluded).")


if __name__ == "__main__":
    main()
