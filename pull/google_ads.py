#!/usr/bin/env python3
"""
pull/google_ads.py - pull TerraSlate's Google Ads numbers from the Google Ads API and write
them into data.json under the "google" channel. Pure stdlib (urllib), no google-ads library.

Credentials (either as env vars, or in a gitignored JSON file pull/.google_creds.json):
  GOOGLE_ADS_DEVELOPER_TOKEN     developer token (Basic access, approved by Google)
  GOOGLE_ADS_CLIENT_ID           OAuth client id
  GOOGLE_ADS_CLIENT_SECRET       OAuth client secret
  GOOGLE_ADS_REFRESH_TOKEN       OAuth refresh token (offline access, scope adwords)
  GOOGLE_ADS_LOGIN_CUSTOMER_ID   manager (MCC) account id, digits only (no dashes)
  GOOGLE_ADS_CUSTOMER_ID         TerraSlate Google Ads account id, digits only
  GOOGLE_ADS_API_VERSION         optional, defaults to v18 (bump if Google rejects the version)

Usage:
  python3 pull/google_ads.py                         # last 30 days ending yesterday
  python3 pull/google_ads.py --since 2025-01-01 --until 2026-07-13   # backfill a range

Only the "google" channel and its daily rows are touched; every other channel (facebook,
amazon, walmart) and meta/prior are preserved. build_dashboard.py then reconciles: the
google headline is set to the sum of the google daily rows, so it reconciles by construction.
Google reports fractional conversions; each day's "orders" is the rounded conversion count.
"""
import json, os, sys, datetime, urllib.parse, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data.json"
CREDS_FILE = HERE / ".google_creds.json"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def cfg(key, required=True):
    val = os.environ.get(key)
    if not val and CREDS_FILE.exists():
        try:
            val = json.loads(CREDS_FILE.read_text()).get(key)
        except Exception:
            val = None
    if required and not val:
        print(f"ERROR: missing credential {key} (set env var or add to pull/.google_creds.json)", file=sys.stderr)
        sys.exit(1)
    return val


def get_access_token():
    body = urllib.parse.urlencode({
        "client_id": cfg("GOOGLE_ADS_CLIENT_ID"),
        "client_secret": cfg("GOOGLE_ADS_CLIENT_SECRET"),
        "refresh_token": cfg("GOOGLE_ADS_REFRESH_TOKEN"),
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())["access_token"]


def digits(s):
    return "".join(ch for ch in str(s) if ch.isdigit())


def run_query(access_token, since, until):
    ver = cfg("GOOGLE_ADS_API_VERSION", required=False) or "v18"
    customer = digits(cfg("GOOGLE_ADS_CUSTOMER_ID"))
    url = f"https://googleads.googleapis.com/{ver}/customers/{customer}/googleAds:searchStream"
    query = ("SELECT segments.date, metrics.cost_micros, metrics.impressions, metrics.clicks, "
             "metrics.conversions, metrics.conversions_value "
             f"FROM customer WHERE segments.date BETWEEN '{since}' AND '{until}'")
    req = urllib.request.Request(url, data=json.dumps({"query": query}).encode(), method="POST")
    req.add_header("Authorization", "Bearer " + access_token)
    req.add_header("developer-token", cfg("GOOGLE_ADS_DEVELOPER_TOKEN"))
    req.add_header("login-customer-id", digits(cfg("GOOGLE_ADS_LOGIN_CUSTOMER_ID")))
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            payload = json.loads(r.read())
    except urllib.error.HTTPError as e:
        print("Google Ads API error:", e.read().decode()[:800], file=sys.stderr)
        sys.exit(1)
    rows = []
    for chunk in payload:               # searchStream returns a list of result chunks
        for res in chunk.get("results", []):
            seg, m = res.get("segments", {}), res.get("metrics", {})
            rows.append({
                "date": seg.get("date"),
                "spend": round(int(m.get("costMicros", 0)) / 1_000_000, 2),
                "impressions": int(m.get("impressions", 0)),
                "clicks": int(m.get("clicks", 0)),
                "orders": round(float(m.get("conversions", 0))),
                "revenue": round(float(m.get("conversionsValue", 0)), 2),
            })
    return rows


def main():
    args = sys.argv[1:]
    today = datetime.date.today()
    until = today - datetime.timedelta(days=1)
    since = until - datetime.timedelta(days=29)
    if "--since" in args:
        since = datetime.date.fromisoformat(args[args.index("--since") + 1])
    if "--until" in args:
        until = datetime.date.fromisoformat(args[args.index("--until") + 1])

    token = get_access_token()
    rows = run_query(token, since.isoformat(), until.isoformat())
    if not rows:
        print(f"WARNING: no Google Ads rows for {since} to {until}; leaving data.json unchanged", file=sys.stderr)
        return

    g_daily, sp, im, cl, od, rev = [], 0.0, 0, 0, 0, 0.0
    for r in sorted(rows, key=lambda x: x["date"]):
        g_daily.append({"date": r["date"], "channel": "google", "spend": r["spend"],
                        "impressions": r["impressions"], "clicks": r["clicks"],
                        "orders": r["orders"], "revenue": r["revenue"]})
        sp += r["spend"]; im += r["impressions"]; cl += r["clicks"]; od += r["orders"]; rev += r["revenue"]
    sp, rev = round(sp, 2), round(rev, 2)

    d = json.loads(DATA.read_text())
    pulled = {r["date"] for r in g_daily}
    kept = [r for r in d.get("daily", []) if r.get("channel") != "google" or r["date"] not in pulled]
    d["daily"] = sorted(kept + g_daily, key=lambda r: (r["date"], r["channel"]))
    d["channels"]["google"] = {
        "connected": True, "label": "Google Ads", "kind": "ads",
        "attribution": "Google conversion tracking (data-driven)",
        "spend": sp, "impressions": im, "clicks": cl, "orders": od, "revenue": rev,
    }
    DATA.write_text(json.dumps(d, indent=2))
    print(f"OK pulled Google Ads {since} to {until}: spend ${sp:,.2f}, revenue ${rev:,.2f}, "
          f"orders {od}, {len(g_daily)} days")


if __name__ == "__main__":
    main()
