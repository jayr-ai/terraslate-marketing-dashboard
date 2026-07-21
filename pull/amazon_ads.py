#!/usr/bin/env python3
"""
pull/amazon_ads.py - pull Amazon Ads (Sponsored Products/Brands/Display) into data.json's
amazon channel via the Amazon Ads API v3 async reporting flow. Pure stdlib.

Amazon's API only serves ~recent data (roughly last 60 days); deep history comes from the
one-time sheet/CSV backfill (see pull/amazon_from_csv.py). This keeps recent days fresh.

Credentials (env or gitignored pull/.amazon_creds.json):
  AMAZON_ADS_CLIENT_ID       LWA app client id
  AMAZON_ADS_CLIENT_SECRET   LWA app client secret
  AMAZON_ADS_REFRESH_TOKEN   OAuth refresh token (scope advertising::campaign_management)
  AMAZON_ADS_PROFILE_ID      advertising profile id for the TerraSlate US marketplace
  AMAZON_ADS_REGION          NA (default) | EU | FE

Usage:
  python3 pull/amazon_ads.py                       # last 30 days ending yesterday
  python3 pull/amazon_ads.py --since 2026-05-20 --until 2026-07-15

The async flow per ad product: create report -> poll until COMPLETED -> download gzip JSON ->
aggregate by day. Writes only the amazon channel (marketplace). adRevenue = ad sales; total
sales (for true TACoS) would come from a separate Seller Central source later, so for now
totalRevenue = adRevenue.
"""
import json, os, sys, time, gzip, io, datetime, urllib.parse, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data.json"
CREDS_FILE = HERE / ".amazon_creds.json"
TOKEN_URL = "https://api.amazon.com/auth/o2/token"
REGION_HOST = {"NA": "advertising-api.amazon.com",
               "EU": "advertising-api-eu.amazon.com",
               "FE": "advertising-api-fe.amazon.com"}
CT_V3 = "application/vnd.createasyncreportrequest.v3+json"

# per ad product: report type + the metric columns to request (tolerant parsing handles variants)
PRODUCTS = [
    {"adProduct": "SPONSORED_PRODUCTS", "reportTypeId": "spCampaigns",
     "columns": ["date", "impressions", "clicks", "cost", "purchases14d", "sales14d"]},
    {"adProduct": "SPONSORED_BRANDS", "reportTypeId": "sbCampaigns",
     "columns": ["date", "impressions", "clicks", "cost", "purchases", "sales"]},
    {"adProduct": "SPONSORED_DISPLAY", "reportTypeId": "sdCampaigns",
     "columns": ["date", "impressions", "clicks", "cost", "purchases", "sales"]},
]
COST_KEYS = ["cost", "spend"]
ORDER_KEYS = ["purchases14d", "purchases", "purchases7d", "purchases30d", "purchases1d"]
SALES_KEYS = ["sales14d", "sales", "sales7d", "sales30d", "sales1d"]


def cfg(key, required=True, default=None):
    val = os.environ.get(key)
    if not val and CREDS_FILE.exists():
        try:
            val = json.loads(CREDS_FILE.read_text()).get(key)
        except Exception:
            val = None
    val = val or default
    if required and not val:
        print(f"ERROR: missing {key} (set env var or add to pull/.amazon_creds.json)", file=sys.stderr)
        sys.exit(1)
    return val


def api(url, data=None, headers=None, method="GET", timeout=90):
    req = urllib.request.Request(url, data=data, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def get_token():
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token", "refresh_token": cfg("AMAZON_ADS_REFRESH_TOKEN"),
        "client_id": cfg("AMAZON_ADS_CLIENT_ID"), "client_secret": cfg("AMAZON_ADS_CLIENT_SECRET"),
    }).encode()
    return api(TOKEN_URL, data=body, method="POST",
               headers={"Content-Type": "application/x-www-form-urlencoded"})["access_token"]


def pick(row, keys):
    for k in keys:
        if k in row and row[k] not in (None, ""):
            try:
                return float(row[k])
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def run_report(base, headers, product, since, until):
    """Create one report, poll to completion, download + parse rows. Returns [] on failure."""
    body = json.dumps({
        "name": f"{product['adProduct']}-{since}-{until}",
        "startDate": since, "endDate": until,
        "configuration": {
            "adProduct": product["adProduct"], "groupBy": ["campaign"],
            "columns": product["columns"], "reportTypeId": product["reportTypeId"],
            "timeUnit": "DAILY", "format": "GZIP_JSON",
        },
    }).encode()
    try:
        created = api(base + "/reporting/reports", data=body, method="POST",
                      headers={**headers, "Content-Type": CT_V3, "Accept": CT_V3})
    except urllib.error.HTTPError as e:
        print(f"  {product['adProduct']}: create failed HTTP {e.code}: {e.read().decode()[:300]}", file=sys.stderr)
        return []
    report_id = created.get("reportId")
    for _ in range(40):  # ~10 min max
        time.sleep(15)
        st = api(base + f"/reporting/reports/{report_id}", headers=headers)
        status = st.get("status")
        if status == "COMPLETED":
            url = st.get("url")
            with urllib.request.urlopen(url, timeout=180) as r:
                raw = r.read()
            data = json.loads(gzip.GzipFile(fileobj=io.BytesIO(raw)).read())
            print(f"  {product['adProduct']}: {len(data)} rows")
            return data
        if status in ("FAILURE", "CANCELLED"):
            print(f"  {product['adProduct']}: report {status}", file=sys.stderr)
            return []
    print(f"  {product['adProduct']}: timed out waiting for report", file=sys.stderr)
    return []


def norm_date(v):
    s = str(v)
    if len(s) == 8 and s.isdigit():  # YYYYMMDD -> YYYY-MM-DD
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return s[:10]


def chunks(since, until, days=30):
    s = datetime.date.fromisoformat(since)
    e = datetime.date.fromisoformat(until)
    while s <= e:
        c = min(e, s + datetime.timedelta(days=days - 1))
        yield s.isoformat(), c.isoformat()
        s = c + datetime.timedelta(days=1)


def main():
    args = sys.argv[1:]
    today = datetime.date.today()
    until = args[args.index("--until") + 1] if "--until" in args else (today - datetime.timedelta(days=1)).isoformat()
    since = args[args.index("--since") + 1] if "--since" in args else (datetime.date.fromisoformat(until) - datetime.timedelta(days=29)).isoformat()

    region = cfg("AMAZON_ADS_REGION", required=False, default="NA").upper()
    base = "https://" + REGION_HOST.get(region, REGION_HOST["NA"])
    headers = {
        "Authorization": "Bearer " + get_token(),
        "Amazon-Advertising-API-ClientId": cfg("AMAZON_ADS_CLIENT_ID"),
        "Amazon-Advertising-API-Scope": str(cfg("AMAZON_ADS_PROFILE_ID")),
    }

    by_date = {}
    for cs, ce in chunks(since, until):          # Amazon caps a report's date range, so chunk it
        for product in PRODUCTS:
            for row in run_report(base, headers, product, cs, ce):
                dt = norm_date(row.get("date"))
                if not dt or dt == "None":
                    continue
                a = by_date.setdefault(dt, {"spend": 0.0, "impressions": 0, "clicks": 0, "orders": 0.0, "revenue": 0.0})
                a["spend"] += pick(row, COST_KEYS)
                a["impressions"] += int(pick(row, ["impressions"]))
                a["clicks"] += int(pick(row, ["clicks"]))
                a["orders"] += pick(row, ORDER_KEYS)
                a["revenue"] += pick(row, SALES_KEYS)

    if not by_date:
        print("WARNING: no Amazon rows returned; data.json unchanged", file=sys.stderr)
        return

    a_rows = [{"date": d, "channel": "amazon", "spend": round(v["spend"], 2),
               "impressions": v["impressions"], "clicks": v["clicks"],
               "orders": int(round(v["orders"])), "revenue": round(v["revenue"], 2)}
              for d, v in by_date.items()]
    a_rows.sort(key=lambda r: r["date"])

    d = json.loads(DATA.read_text())
    pulled = {r["date"] for r in a_rows}
    d["daily"] = [r for r in d.get("daily", []) if r.get("channel") != "amazon" or r["date"] not in pulled] + a_rows
    d["daily"].sort(key=lambda r: (r["date"], r["channel"]))
    rev = round(sum(r["revenue"] for r in a_rows), 2)
    d["channels"]["amazon"] = {
        "connected": True, "label": "Amazon", "kind": "marketplace",
        "attribution": "14-day (Amazon Ads API)",
        "spend": round(sum(r["spend"] for r in a_rows), 2),
        "impressions": sum(r["impressions"] for r in a_rows),
        "clicks": sum(r["clicks"] for r in a_rows),
        "orders": sum(r["orders"] for r in a_rows),
        "revenue": rev, "adRevenue": rev, "totalRevenue": rev,
    }
    DATA.write_text(json.dumps(d, indent=2))
    print(f"OK Amazon Ads {a_rows[0]['date']} to {a_rows[-1]['date']}: "
          f"${d['channels']['amazon']['spend']:,.2f} spend, ${rev:,.2f} ad sales, {len(a_rows)} days")


if __name__ == "__main__":
    main()
