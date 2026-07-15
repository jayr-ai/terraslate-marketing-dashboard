#!/usr/bin/env python3
"""
pull/windsor.py - pull Google Ads + Amazon + Walmart from Windsor.ai's API into data.json.
Pure stdlib. Meta is NOT touched here (it stays on the Meta MCP pull).

Windsor's `all` endpoint returns one row per source-per-day. We split rows by source into our
channels, sum per (channel, date), and write each connected channel + its daily rows. Headline
= sum of daily rows, so it reconciles by construction. Other channels (facebook) are preserved.

Credentials (env or gitignored pull/.windsor_creds.json):
  WINDSOR_API_KEY    your Windsor.ai API key
  WINDSOR_BASE_URL   optional, defaults to https://connectors.windsor.ai/all

Usage:
  python3 pull/windsor.py                                   # last 30 days ending yesterday
  python3 pull/windsor.py --since 2025-01-01 --until 2026-07-14   # backfill a range

Field mapping is tolerant (Windsor field names vary a little by plan/connector); after you
connect, run once and we confirm the exact keys against the real response.
"""
import json, os, sys, datetime, urllib.parse, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data.json"
CREDS_FILE = HERE / ".windsor_creds.json"

# which Windsor sources map to which dashboard channel (Meta deliberately excluded)
SOURCE_MAP = {"google": "google", "google_ads": "google", "googleads": "google",
              "amazon": "amazon", "amazon_ads": "amazon", "amazon_advertising": "amazon",
              "walmart": "walmart", "walmart_connect": "walmart"}
CHANNEL_META = {
    "google":  {"label": "Google Ads", "kind": "ads",        "attribution": "Google conversion tracking (via Windsor.ai)"},
    "amazon":  {"label": "Amazon",     "kind": "marketplace","attribution": "14-day (via Windsor.ai)"},
    "walmart": {"label": "Walmart",    "kind": "marketplace","attribution": "14-day (via Windsor.ai)"},
}
# tolerant field-name aliases (first match wins)
F = {
    "source": ["source", "datasource", "data_source", "connector", "account_type"],
    "date":   ["date", "day", "date_start"],
    "spend":  ["spend", "cost", "total_cost", "costs"],
    "impressions": ["impressions", "impr"],
    "clicks": ["clicks"],
    "conversions": ["conversions", "conv", "orders", "purchases", "total_conversions"],
    # Google exposes value as conversions_value (revenue field is empty); marketplaces may use
    # revenue/sales. Prefer the known-good value fields first, fall back to generic revenue.
    "revenue": ["conversions_value", "conversion_value", "all_conversions_value", "revenue",
                "sales", "total_revenue", "total_conversion_value", "conv_value"],
}


def cfg(key, required=True, default=None):
    val = os.environ.get(key)
    if not val and CREDS_FILE.exists():
        try:
            val = json.loads(CREDS_FILE.read_text()).get(key)
        except Exception:
            val = None
    if not val:
        val = default
    if required and not val:
        print(f"ERROR: missing {key} (set env var or add to pull/.windsor_creds.json)", file=sys.stderr)
        sys.exit(1)
    return val


def pick(row, names):
    for n in names:
        if n in row and row[n] not in (None, ""):
            return row[n]
    return None


def to_num(v):
    if v is None:
        return 0.0
    try:
        return float(str(v).replace(",", "").replace("$", ""))
    except ValueError:
        return 0.0


def channel_of(row):
    raw = pick(row, F["source"])
    if raw is None:
        return None
    key = str(raw).strip().lower().replace(" ", "_")
    for frag, ch in SOURCE_MAP.items():
        if frag in key:
            return ch
    return None


def fetch(base, api_key):
    # NOTE: Windsor ignores URL date params (date_from/date_preset/etc) for the /all endpoint -
    # the date range is whatever the saved query in the Windsor UI is set to. So we fetch what
    # the saved query returns and (optionally) filter locally by --since/--until below.
    params = {
        "api_key": api_key,
        "fields": "source,date,spend,impressions,clicks,conversions,conversions_value,revenue",
        "_renderer": "json",
    }
    url = base + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(url, timeout=120) as r:
            payload = json.loads(r.read())
    except urllib.error.HTTPError as e:
        print("Windsor API error:", e.read().decode()[:800], file=sys.stderr)
        sys.exit(1)
    if isinstance(payload, dict):
        return payload.get("data", payload.get("rows", []))
    return payload


def main():
    args = sys.argv[1:]
    # Optional LOCAL date filter (Windsor's own date range is set in its UI saved query).
    since = args[args.index("--since") + 1] if "--since" in args else None
    until = args[args.index("--until") + 1] if "--until" in args else None

    rows = fetch(cfg("WINDSOR_BASE_URL", required=False, default="https://connectors.windsor.ai/all"),
                 cfg("WINDSOR_API_KEY"))
    if not rows:
        print("WARNING: Windsor returned no rows (check the saved query in the Windsor UI); "
              "data.json unchanged", file=sys.stderr)
        return
    if since or until:
        rows = [r for r in rows if (not since or str(pick(r, F["date"]))[:10] >= since)
                and (not until or str(pick(r, F["date"]))[:10] <= until)]

    # accumulate per (channel, date)
    acc = {}
    for row in rows:
        ch = channel_of(row)
        date = pick(row, F["date"])
        if not ch or not date:
            continue
        date = str(date)[:10]
        a = acc.setdefault((ch, date), {"spend": 0.0, "impressions": 0, "clicks": 0, "orders": 0, "revenue": 0.0})
        a["spend"] += to_num(pick(row, F["spend"]))
        a["impressions"] += int(to_num(pick(row, F["impressions"])))
        a["clicks"] += int(to_num(pick(row, F["clicks"])))
        a["orders"] += int(round(to_num(pick(row, F["conversions"]))))
        a["revenue"] += to_num(pick(row, F["revenue"]))

    if not acc:
        print("WARNING: no google/amazon/walmart rows recognized in Windsor response; "
              "field names may differ - data.json unchanged", file=sys.stderr)
        return

    d = json.loads(DATA.read_text())
    channels_seen = sorted({ch for (ch, _) in acc})
    for ch in channels_seen:
        new_rows = [{"date": dt, "channel": ch,
                     "spend": round(v["spend"], 2), "impressions": v["impressions"],
                     "clicks": v["clicks"], "orders": v["orders"], "revenue": round(v["revenue"], 2)}
                    for (c, dt), v in acc.items() if c == ch]
        pulled = {r["date"] for r in new_rows}
        d["daily"] = [r for r in d.get("daily", []) if r.get("channel") != ch or r["date"] not in pulled] + new_rows
        sp = round(sum(r["spend"] for r in new_rows), 2)
        rev = round(sum(r["revenue"] for r in new_rows), 2)
        entry = {"connected": True, "label": CHANNEL_META[ch]["label"], "kind": CHANNEL_META[ch]["kind"],
                 "attribution": CHANNEL_META[ch]["attribution"],
                 "spend": sp, "impressions": sum(r["impressions"] for r in new_rows),
                 "clicks": sum(r["clicks"] for r in new_rows), "orders": sum(r["orders"] for r in new_rows),
                 "revenue": rev}
        if CHANNEL_META[ch]["kind"] == "marketplace":
            # Windsor ad connectors report ad-attributed sales; total sales (organic) not included,
            # so TACoS == ACoS until a total-sales source is added.
            entry["adRevenue"] = rev
            entry["totalRevenue"] = rev
        d["channels"][ch] = entry
        print(f"  {ch}: spend ${sp:,.2f}, revenue ${rev:,.2f}, {len(new_rows)} days")

    d["daily"] = sorted(d["daily"], key=lambda r: (r["date"], r["channel"]))
    DATA.write_text(json.dumps(d, indent=2))
    all_dates = sorted({dt for (_, dt) in acc})
    print(f"OK Windsor pull [{all_dates[0]}..{all_dates[-1]}]: channels {', '.join(channels_seen)}")


if __name__ == "__main__":
    main()
