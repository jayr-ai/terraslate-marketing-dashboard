#!/usr/bin/env python3
"""
backfill_merge.py - one-time loader that merges pull/_backfill/chunk*.json (raw Meta MCP
daily-series responses covering 2025-01-01 through yesterday) into data.json's daily[]
array for channel "facebook", replacing whatever partial history is there.

Reuses the same row-normalization rules as meta_from_mcp.py. Run once, then rely on the
daily refresh routine (meta_from_mcp.py) to extend history day by day.
"""
import json, sys
from pathlib import Path

HERE = Path(__file__).parent
DATA = HERE.parent / "data.json"
sys.path.insert(0, str(HERE))
from meta_from_mcp import load_rows, normalize, to_iso  # noqa: E402


def main():
    chunks = sorted(HERE.glob("_backfill/chunk*.json"))
    if not chunks:
        print("ERROR: no chunk files found in pull/_backfill/", file=sys.stderr)
        sys.exit(1)

    by_date = {}
    for path in chunks:
        rows = load_rows(path)
        for row in rows:
            date = to_iso(row["date_start"])
            n = normalize(row)
            by_date[date] = {"date": date, "channel": "facebook", **n}

    fb_daily = [by_date[d] for d in sorted(by_date)]
    if not fb_daily:
        print("ERROR: no rows parsed from chunks", file=sys.stderr)
        sys.exit(1)

    d = json.loads(DATA.read_text())
    other_channels = [r for r in d.get("daily", []) if r.get("channel") != "facebook"]
    d["daily"] = other_channels + fb_daily
    DATA.write_text(json.dumps(d, indent=2))
    print(f"OK merged {len(fb_daily)} facebook daily rows "
          f"({fb_daily[0]['date']} to {fb_daily[-1]['date']}) into data.json")


if __name__ == "__main__":
    main()
