#!/usr/bin/env python3
"""
render.py - deterministic renderer (pure Python, no Node needed).

Reads data.json + index.template.html and produces index.html by (a) rebuilding whole
panels inside <!--X_START-->..<!--X_END--> marker regions and (b) resolving every
{%dotted.path%} token from data.json. No LLM ever writes a number into the HTML; that is
what stops the dashboard from drifting.

Two hard guards abort the render (non-zero exit) so a broken page can never ship:
  - DASH GUARD: any em/en dash (house style forbids them; they read as an AI tell).
  - MARKER/TOKEN GUARD: a missing marker region or an unresolved {%token%}.

Run: python3 render.py
(render.js is kept as a Node-parity twin; either produces the same index.html.)
"""
import json, re, sys
from pathlib import Path

HERE = Path(__file__).parent
d = json.loads((HERE / "data.json").read_text())
tpl = (HERE / "index.template.html").read_text()

def die(msg):
    print(f"RENDER FAIL: {msg}", file=sys.stderr)
    sys.exit(1)

def money(n):  return "$" + f"{float(n or 0):,.0f}"
def money2(n): return "$" + f"{float(n or 0):,.2f}"
def num(n):    return f"{int(n or 0):,}"
def na(v, suffix=""):
    return '<span class="na">NO DATA</span>' if v is None else f"{v}{suffix}"

def delta_badge(pct):
    if pct is None:
        return ""
    up = pct >= 0
    arrow = "▲" if up else "▼"  # triangles, never dashes
    return f'<span class="delta {"up" if up else "down"}">{arrow} {abs(pct)}%</span>'

ch = d["channels"]
t = d["totals"]
dl = t.get("delta", {})

def r_kpi_cards():
    def card(label, value, badge=""):
        return f'<div class="kpi"><div class="kpi-label">{label}</div><div class="kpi-value">{value}</div>{badge}</div>'
    return "\n".join([
        card("Total spend", money(t["spend"]), delta_badge(dl.get("spend"))),
        card("Total revenue", money(t["revenue"]), delta_badge(dl.get("revenue"))),
        card("Blended ROAS (MER)", f'{t.get("blendedRoas","n/a")}x', delta_badge(dl.get("blendedRoas"))),
        card("Orders", num(t["orders"]), delta_badge(dl.get("orders"))),
        card("AOV", money2(t["aov"]) if t.get("aov") is not None else "n/a"),
    ])

def r_channels_table():
    rows = []
    for h in ch.values():
        if not h.get("connected"):
            rows.append(f'<tr class="off"><td>{h["label"]}</td><td colspan="8" class="na">NO DATA (not connected)</td></tr>')
            continue
        rows.append(f'''<tr>
      <td>{h["label"]}</td>
      <td>{money(h["spend"])}</td>
      <td>{money(h["revenue"])}</td>
      <td>{na(h.get("roas"),"x")}</td>
      <td>{num(h["orders"])}</td>
      <td>{money2(h["aov"]) if h.get("aov") is not None else "n/a"}</td>
      <td>{na(h.get("ctr"),"%")}</td>
      <td>{money2(h["cpc"]) if h.get("cpc") is not None else "n/a"}</td>
      <td>{na(h.get("cvr"),"%")}</td>
    </tr>''')
    return "\n".join(rows)

def r_marketplace():
    mk = [h for h in ch.values() if h.get("kind") == "marketplace"]
    if not mk:
        return '<p class="na">No marketplace channels configured.</p>'
    out = []
    for h in mk:
        if not h.get("connected"):
            out.append(f'<div class="mk-card off"><h4>{h["label"]}</h4><p class="na">NO DATA (not connected)</p></div>')
            continue
        out.append(f'''<div class="mk-card">
      <h4>{h["label"]}</h4>
      <div class="mk-row"><span>Ad spend</span><b>{money(h["spend"])}</b></div>
      <div class="mk-row"><span>Ad revenue</span><b>{money(h.get("adRevenue",0))}</b></div>
      <div class="mk-row"><span>Total revenue</span><b>{money(h.get("totalRevenue",0))}</b></div>
      <div class="mk-row"><span>ACoS</span><b>{na(h.get("acos"),"%")}</b></div>
      <div class="mk-row"><span>TACoS</span><b>{na(h.get("tacos"),"%")}</b></div>
    </div>''')
    return "\n".join(out)

def r_channel_mix():
    out = []
    for h in ch.values():
        if not h.get("connected"):
            continue
        out.append(f'''<div class="mix-row">
       <div class="mix-name">{h["label"]}</div>
       <div class="mix-bars">
         <div class="mix-bar"><div class="fill spend" style="width:{h.get("spendShare",0)}%"></div><span>{h.get("spendShare",0)}% spend</span></div>
         <div class="mix-bar"><div class="fill rev" style="width:{h.get("revenueShare",0)}%"></div><span>{h.get("revenueShare",0)}% revenue</span></div>
       </div>
     </div>''')
    return "\n".join(out)

def r_insights():
    if not d.get("insights"):
        return "<li>No anomalies flagged this period.</li>"
    order = {"high": 0, "warn": 1, "info": 2}
    items = sorted(d["insights"], key=lambda i: order.get(i["severity"], 9))
    return "\n".join(f'<li class="ins {i["severity"]}"><span class="sev">{i["severity"].upper()}</span> {i["text"]}</li>' for i in items)

def r_provenance():
    rows = []
    for p in d["provenance"]:
        status = "connected" if p["connected"] else '<span class="na">not connected</span>'
        attr = p.get("attribution") or "n/a"
        rows.append(f'<tr><td>{p["source"]}</td><td>{status}</td><td>{attr}</td><td>{p["dateRange"]}</td></tr>')
    return "\n".join(rows)

def r_chart_data():
    payload = json.dumps({"daily": d.get("daily", []), "channels": ch, "totals": t})
    return f'<script id="dash-data" type="application/json">{payload}</script>'

REGIONS = {
    "KPI_CARDS": r_kpi_cards, "CHANNELS_TABLE": r_channels_table, "MARKETPLACE": r_marketplace,
    "CHANNEL_MIX": r_channel_mix, "INSIGHTS": r_insights, "PROVENANCE": r_provenance,
    "CHART_DATA": r_chart_data,
}

out = tpl
for name, build in REGIONS.items():
    pat = re.compile(rf"(<!--{name}_START-->)([\s\S]*?)(<!--{name}_END-->)")
    if not pat.search(out):
        die(f"marker region {name} not found in template")
    out = pat.sub(lambda m: f"{m.group(1)}\n{build()}\n{m.group(3)}", out, count=1)

def resolve(m):
    val = d
    for k in m.group(1).split("."):
        val = val.get(k) if isinstance(val, dict) else None
        if val is None:
            die(f"unresolved token {{%{m.group(1)}%}}")
    return str(val)

out = re.sub(r"\{%([a-zA-Z0-9_.]+)%\}", resolve, out)

if re.search(r"[‒–—―]", out):
    die("em/en dash found in output (house style forbids them)")
if re.search(r"\{%[^%]+%\}", out):
    die("an unresolved {%token%} remains")

(HERE / "index.html").write_text(out)
print("OK rendered index.html")
