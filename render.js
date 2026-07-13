#!/usr/bin/env node
/*
 * render.js - deterministic renderer. Reads data.json + index.template.html and produces
 * index.html by (a) rebuilding whole panels inside <!--X_START-->..<!--X_END--> marker
 * regions and (b) resolving every {%dotted.path%} token from data.json.
 *
 * No LLM ever writes a number into the HTML. That is what stops the dashboard from drifting.
 *
 * Two hard guards abort the render (non-zero exit) so a broken page can never ship:
 *   - DASH GUARD: any em/en dash (house style forbids them - they read as an AI tell).
 *   - MARKER/TOKEN GUARD: a missing marker region or an unresolved {%token%}.
 *
 * Run: node render.js
 */
const fs = require("fs");
const path = require("path");

const d = JSON.parse(fs.readFileSync(path.join(__dirname, "data.json"), "utf8"));
const tpl = fs.readFileSync(path.join(__dirname, "index.template.html"), "utf8");

const money = (n) => "$" + Number(n || 0).toLocaleString("en-US", { maximumFractionDigits: 0 });
const money2 = (n) => "$" + Number(n || 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const num = (n) => Number(n || 0).toLocaleString("en-US");
const na = (v, suffix = "") => (v === null || v === undefined ? '<span class="na">NO DATA</span>' : v + suffix);

function deltaBadge(pct) {
  if (pct === null || pct === undefined) return "";
  const up = pct >= 0;
  const cls = up ? "up" : "down";
  const arrow = up ? "▲" : "▼"; // triangles, not dashes
  return `<span class="delta ${cls}">${arrow} ${Math.abs(pct)}%</span>`;
}

// ---- marker region builders -------------------------------------------------
const regions = {};

regions.KPI_CARDS = () => {
  const t = d.totals, dl = t.delta || {};
  const card = (label, value, badge) =>
    `<div class="kpi"><div class="kpi-label">${label}</div><div class="kpi-value">${value}</div>${badge || ""}</div>`;
  return [
    card("Total spend", money(t.spend), deltaBadge(dl.spend)),
    card("Total revenue", money(t.revenue), deltaBadge(dl.revenue)),
    card("Blended ROAS (MER)", (t.blendedRoas ?? "n/a") + "x", deltaBadge(dl.blendedRoas)),
    card("Orders", num(t.orders), deltaBadge(dl.orders)),
    card("AOV", t.aov != null ? money2(t.aov) : "n/a", ""),
  ].join("\n");
};

regions.CHANNELS_TABLE = () => {
  const rows = Object.entries(d.channels).map(([key, h]) => {
    if (!h.connected)
      return `<tr class="off"><td>${h.label}</td><td colspan="8" class="na">NO DATA (not connected)</td></tr>`;
    return `<tr>
      <td>${h.label}</td>
      <td>${money(h.spend)}</td>
      <td>${money(h.revenue)}</td>
      <td>${na(h.roas, "x")}</td>
      <td>${num(h.orders)}</td>
      <td>${h.aov != null ? money2(h.aov) : "n/a"}</td>
      <td>${na(h.ctr, "%")}</td>
      <td>${h.cpc != null ? money2(h.cpc) : "n/a"}</td>
      <td>${na(h.cvr, "%")}</td>
    </tr>`;
  });
  return rows.join("\n");
};

regions.MARKETPLACE = () => {
  const mk = Object.values(d.channels).filter((h) => h.kind === "marketplace");
  if (!mk.length) return '<p class="na">No marketplace channels configured.</p>';
  return mk.map((h) => {
    if (!h.connected) return `<div class="mk-card off"><h4>${h.label}</h4><p class="na">NO DATA (not connected)</p></div>`;
    return `<div class="mk-card">
      <h4>${h.label}</h4>
      <div class="mk-row"><span>Ad spend</span><b>${money(h.spend)}</b></div>
      <div class="mk-row"><span>Ad revenue</span><b>${money(h.adRevenue)}</b></div>
      <div class="mk-row"><span>Total revenue</span><b>${money(h.totalRevenue)}</b></div>
      <div class="mk-row"><span>ACoS</span><b>${na(h.acos, "%")}</b></div>
      <div class="mk-row"><span>TACoS</span><b>${na(h.tacos, "%")}</b></div>
    </div>`;
  }).join("\n");
};

regions.CHANNEL_MIX = () => {
  return Object.values(d.channels).filter((h) => h.connected).map((h) =>
    `<div class="mix-row">
       <div class="mix-name">${h.label}</div>
       <div class="mix-bars">
         <div class="mix-bar"><div class="fill spend" style="width:${h.spendShare || 0}%"></div><span>${h.spendShare || 0}% spend</span></div>
         <div class="mix-bar"><div class="fill rev" style="width:${h.revenueShare || 0}%"></div><span>${h.revenueShare || 0}% revenue</span></div>
       </div>
     </div>`).join("\n");
};

regions.INSIGHTS = () => {
  if (!d.insights.length) return "<li>No anomalies flagged this period.</li>";
  const order = { high: 0, warn: 1, info: 2 };
  return [...d.insights].sort((a, b) => order[a.severity] - order[b.severity])
    .map((i) => `<li class="ins ${i.severity}"><span class="sev">${i.severity.toUpperCase()}</span> ${i.text}</li>`).join("\n");
};

regions.PROVENANCE = () => {
  return d.provenance.map((p) =>
    `<tr><td>${p.source}</td><td>${p.connected ? "connected" : '<span class="na">not connected</span>'}</td><td>${p.attribution || "n/a"}</td><td>${p.dateRange}</td></tr>`).join("\n");
};

// Embed the raw series the inline chart script draws from (data injected, logic static).
regions.CHART_DATA = () =>
  `<script id="dash-data" type="application/json">${JSON.stringify({ daily: d.daily, channels: d.channels, totals: d.totals })}</script>`;

// ---- fill marker regions ----------------------------------------------------
let out = tpl;
for (const [name, build] of Object.entries(regions)) {
  const re = new RegExp(`(<!--${name}_START-->)([\\s\\S]*?)(<!--${name}_END-->)`);
  if (!re.test(out)) {
    console.error(`RENDER FAIL: marker region ${name} not found in template`);
    process.exit(1);
  }
  out = out.replace(re, `$1\n${build()}\n$3`);
}

// ---- resolve {%dotted.path%} tokens -----------------------------------------
out = out.replace(/\{%([a-zA-Z0-9_.]+)%\}/g, (_, pathStr) => {
  const val = pathStr.split(".").reduce((o, k) => (o == null ? o : o[k]), d);
  if (val === undefined || val === null) {
    console.error(`RENDER FAIL: unresolved token {%${pathStr}%}`);
    process.exit(1);
  }
  return String(val);
});

// ---- guards -----------------------------------------------------------------
if (/[‒–—―]/.test(out)) {
  console.error("RENDER FAIL: em/en dash found in output (house style forbids them)");
  process.exit(1);
}
if (/\{%[^%]+%\}/.test(out)) {
  console.error("RENDER FAIL: an unresolved {%token%} remains");
  process.exit(1);
}

fs.writeFileSync(path.join(__dirname, "index.html"), out);
console.log("OK rendered index.html");
