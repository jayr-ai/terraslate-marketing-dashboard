#!/usr/bin/env python3
"""
pull/meta.py - fetch TerraSlate's Facebook/Meta Ads numbers from the Graph API and write
them into data.json. This is the CLOUD path (GitHub Actions), replacing the local MCP pull.

Env vars (set as GitHub repo secrets):
  META_ACCESS_TOKEN   (required)  long-lived / system-user token with ads_read on the account
  META_AD_ACCOUNT_ID  (optional)  numeric id, defaults to 24540744 (TerraSlate Paper)
  GRAPH_API_VERSION   (optional)  defaults to v21.0

It pulls the last 30 days (ending yesterday) as a daily series plus the prior 30 days as a
total (for deltas), maps Meta's fields to the unified schema, and preserves the other channels
already in data.json (google/amazon/walmart stay as-is until they are wired). No external deps.
"""
import json, os, sys, urllib.parse, urllib.request, datetime
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data.json"
TOKEN = os.environ.get("META_ACCESS_TOKEN")
ACCOUNT = os.environ.get("META_AD_ACCOUNT_ID", "24540744")
VER = os.environ.get("GRAPH_API_VERSION", "v21.0")
BASE = f"https://graph.facebook.com/{VER}/act_{ACCOUNT}/insights"

if not TOKEN:
    print("ERROR: META_ACCESS_TOKEN not set", file=sys.stderr)
    sys.exit(1)


def get_insights(since, until, daily):
    params = {
        "fields": "spend,impressions,clicks,actions,action_values,purchase_roas",
        "time_range": json.dumps({"since": since, "until": until}),
        "level": "account",
        "access_token": TOKEN,
    }
    if daily:
        params["time_increment"] = "1"
    rows, url = [], BASE + "?" + urllib.parse.urlencode(params)
    while url:
        with urllib.request.urlopen(url, timeout=60) as r:
            payload = json.loads(r.read())
        if "error" in payload:
            print(f"Graph API error: {payload['error']}", file=sys.stderr)
            sys.exit(1)
        rows.extend(payload.get("data", []))
        url = payload.get("paging", {}).get("next")
    return rows


def action_val(row, key, types=("omni_purchase", "purchase")):
    """Pull the first matching action_type value from an actions/action_values list."""
    for t in types:
        for item in row.get(key, []):
            if item.get("action_type") == t:
                return float(item.get("value", 0))
    return 0.0


def normalize(row):
    spend = round(float(row.get("spend", 0)), 2)
    orders = int(action_val(row, "actions"))
    revenue = round(action_val(row, "action_values"), 2)
    if revenue == 0.0:  # fall back to spend x ROAS if conversion value is not reported
        roas = action_val(row, "purchase_roas")
        revenue = round(spend * roas, 2)
    return {
        "spend": spend,
        "impressions": int(row.get("impressions", 0)),
        "clicks": int(row.get("clicks", 0)),
        "orders": orders,
        "revenue": revenue,
    }


def main():
    today = datetime.date.today()
    end = today - datetime.timedelta(days=1)          # yesterday
    start = end - datetime.timedelta(days=29)          # 30-day window
    prior_end = start - datetime.timedelta(days=1)
    prior_start = prior_end - datetime.timedelta(days=29)

    daily_rows = get_insights(start.isoformat(), end.isoformat(), daily=True)
    prior_total = get_insights(prior_start.isoformat(), prior_end.isoformat(), daily=False)

    fb_daily, sp, im, cl, od, rev = [], 0.0, 0, 0, 0, 0.0
    for row in sorted(daily_rows, key=lambda r: r["date_start"]):
        n = normalize(row)
        fb_daily.append({"date": row["date_start"], "channel": "facebook", **n})
        sp += n["spend"]; im += n["impressions"]; cl += n["clicks"]; od += n["orders"]; rev += n["revenue"]
    sp, rev = round(sp, 2), round(rev, 2)

    prior = normalize(prior_total[0]) if prior_total else {"spend": 0, "revenue": 0, "orders": 0}

    d = json.loads(DATA.read_text())
    d["meta"].update({
        "client": "TerraSlate Paper", "currency": "USD", "reportingTz": "America/Denver",
        "windowLabel": "Last 30 days", "dateStart": start.isoformat(), "dateEnd": end.isoformat(),
        "priorLabel": "Prior 30 days", "generatedAt": today.isoformat(),
    })
    # replace facebook daily rows, keep any other channels' rows
    d["daily"] = [r for r in d.get("daily", []) if r.get("channel") != "facebook"] + fb_daily
    d["channels"]["facebook"] = {
        "connected": True, "label": "Facebook / Instagram", "kind": "ads",
        "attribution": "Meta default (mixed per ad set)",
        "spend": sp, "impressions": im, "clicks": cl, "orders": od, "revenue": rev,
        "revenueBasis": "purchase conversion value (or spend x ROAS fallback)",
    }
    d["prior"] = {
        "spend": prior["spend"], "revenue": prior["revenue"], "orders": prior["orders"],
        "blendedRoas": round(prior["revenue"] / prior["spend"], 2) if prior["spend"] else None,
    }
    DATA.write_text(json.dumps(d, indent=2))
    print(f"OK pulled Meta {start} to {end}: spend ${sp:,.2f}, revenue ${rev:,.2f}, orders {od}, {len(fb_daily)} days")


if __name__ == "__main__":
    main()
