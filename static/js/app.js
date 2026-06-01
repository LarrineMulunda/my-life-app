/* ── Utilities ────────────────────────────────────────────────────────────── */
const fmt = (n, cur="KES") => n == null ? "—" :
  cur + " " + Number(n).toLocaleString("en-KE", {minimumFractionDigits:0, maximumFractionDigits:0});
const fmtP = (n, cur="KES") => n == null ? "—" :
  cur + " " + Number(n).toLocaleString("en-KE", {minimumFractionDigits:2, maximumFractionDigits:2});
const fmtDate = s => !s ? "—" :
  new Date(s+"T00:00:00").toLocaleDateString("en-KE", {day:"numeric", month:"short", year:"numeric"});
const today = () => new Date().toISOString().split("T")[0];
const sign  = n => n >= 0 ? "+" : "";

let _tt;
function toast(msg, type="success") {
  const el = document.getElementById("toast");
  if (!el) return;
  el.textContent = msg; el.className = "show " + type;
  clearTimeout(_tt); _tt = setTimeout(() => el.className = "", 3200);
}

// ── Client cache (30s TTL for GET requests) ──────────────────────────────────
const _cache = {};
const _CACHE_TTL = 30000;
const _NO_CACHE  = ["/api/portfolio/review/poll", "/api/prices/anomalies"];

function clearCache(prefix) {
  Object.keys(_cache).forEach(k => { if (!prefix || k.startsWith(prefix)) delete _cache[k]; });
}

async function api(method, url, body) {
  const canCache = method === "GET" && !_NO_CACHE.some(p => url.startsWith(p));
  if (canCache && _cache[url]) {
    const {data, ts} = _cache[url];
    if (Date.now() - ts < _CACHE_TTL) return data;
  }
  const r = await fetch(url, {
    method,
    headers: body ? {"Content-Type":"application/json"} : {},
    body: body ? JSON.stringify(body) : undefined
  });
  const d = await r.json();
  if (!r.ok && d.error) toast(d.error, "error");
  return d;
}

function closeModal(id) { const el=document.getElementById(id); if(el) el.style.display="none"; }
document.addEventListener("click", e => {
  if (e.target.classList.contains("modal-overlay")) e.target.style.display="none";
});

function switchTab(name) {
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
  document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));
  document.querySelector(`[onclick="switchTab('${name}')"]`).classList.add("active");
  document.getElementById("tab-"+name).classList.add("active");
  // Always reload review from DB when switching to review tab
  if (name === "review") {
    delete _cache["/api/portfolio/review"]; // force fresh read
    loadReview();
  }
}

/* ══════════════════════════════════════════════════════════════════════════
   OVERVIEW
══════════════════════════════════════════════════════════════════════════ */
let _netWorthChart = null;

async function loadAll() {
  // One round trip — pre-warms the cache for each individual endpoint
  const d = await api("GET", "/api/investments/all");
  if (d && d.ok) {
    // Pre-populate cache so individual load functions return instantly
    const now = Date.now();
    if (d.stocks)   _cache["/api/stocks"]               = {data: d.stocks, ts: now};
    if (d.overview) _cache["/api/investments/overview"]  = {data: d.overview, ts: now};
    if (d.lots)     _cache["/api/stocks/lots"]           = {data: {lots: d.lots}, ts: now};
    // Reconstruct savings response to match /api/savings exact structure
    if (d.savings && Array.isArray(d.savings)) {
      const totals = {}, fxr = d.fx_rates || {};
      let net = 0;
      d.savings.forEach(e => {
        const sign = ["deposit","interest"].includes(e.type) ? 1 : -1;
        const v = (e.amount_kes != null ? e.amount_kes : e.amount) * sign;
        totals[e.asset_class] = (totals[e.asset_class]||0) + v;
        net += v;
      });
      _cache["/api/savings"] = {data:{
        entries: d.savings,
        totals_by_class: totals,
        net_total: Math.round(net * 100) / 100,
        fx_rates: fxr,
      }, ts: now};
    }
    // Reconstruct fx-rates response to match /api/fx-rates exact structure
    if (d.fx_rates) {
      _cache["/api/fx-rates"] = {data:{rates: d.fx_rates, as_of: "today"}, ts: now};
    }
  }
  // Now call individual functions — they read from cache (instant) or fetch if cache miss
  await Promise.all([
    loadOverview(),
    loadStocks(),
    loadSavings(),
    loadFxRates(),
    loadActiveLots(),
  ]);
  // Review loads separately (always reads from DB, not affected by combined endpoint)
  loadReview();
  // Show anomaly panel if needed
  if (d?.pending_anomalies > 0) loadAnomalies();
}

async function loadOverview() {
  const d = await api("GET", "/api/investments/overview");
  const set = (id, v) => { const el=document.getElementById(id); if(el) el.textContent=v; };
  const col = (id, v) => { const el=document.getElementById(id); if(el) el.style.color=v>=0?"var(--green)":"var(--red)"; };

  set("ov-cost",     fmt(d.total_cost));
  set("ov-mkt",      fmt(d.total_value));
  set("ov-gain",     sign(d.total_gain) + fmt(Math.abs(d.total_gain)));
  set("ov-realized", sign(d.total_realized) + fmt(Math.abs(d.total_realized)));
  col("ov-gain",     d.total_gain);
  col("ov-realized", d.total_realized);

  const badge = document.getElementById("ov-total-badge");
  if (badge) badge.textContent = "Total: " + fmt(d.total_value);

  const note = document.getElementById("currency-note");
  if (note) note.style.display = d.currency_note ? "block" : "none";

  // Asset class breakdown
  const container = document.getElementById("asset-class-breakdown");
  if (container) {
    const entries = Object.entries(d.asset_summary || {}).sort((a,b) => b[1].value - a[1].value);
    const total   = entries.reduce((s,[,v]) => s + v.value, 0) || 1;
    container.innerHTML = entries.length ? `
      <div class="ac-table">
        ${entries.map(([cls, v]) => {
          const pct     = (v.value / total * 100).toFixed(1);
          const barW    = Math.max(2, (v.value / total * 100)).toFixed(1);
          const gainCls = v.gain > 0 ? "pos" : v.gain < 0 ? "neg" : "";
          return `<div class="ac-row">
            <div class="ac-name">${cls}</div>
            <div class="ac-bar-wrap">
              <div class="ac-bar${v.type==="stocks"?" stocks-bar":""}" style="width:${barW}%"></div>
            </div>
            <div class="ac-nums">
              <span class="ac-value">${fmt(v.value)}</span>
              <span class="ac-pct">${pct}%</span>
              ${v.gain !== 0 ? `<span class="ac-gain ${gainCls}">${sign(v.gain)}${fmt(Math.abs(v.gain))}</span>` : ""}
            </div>
          </div>`;
        }).join("")}
      </div>` : `<p class="empty-msg">No assets recorded yet.</p>`;
  }

  // Broker breakdown — all in KES
  const brokers = d.broker_totals || {};
  const bp = document.getElementById("broker-panel");
  const bb = document.getElementById("broker-breakdown");
  if (bp && bb && Object.keys(brokers).length) {
    bp.style.display = "block";
    const total = Object.values(brokers).reduce((a,b) => a+b, 0) || 1;
    bb.innerHTML = Object.entries(brokers).map(([broker, val]) => `
      <div class="broker-row">
        <div class="broker-name">${broker}</div>
        <div class="broker-bar-wrap">
          <div class="broker-bar" style="width:${(val/total*100).toFixed(1)}%"></div>
        </div>
        <div class="broker-nums">
          <span class="broker-val">${fmt(val)}</span>
          <span class="broker-pct">${(val/total*100).toFixed(1)}%</span>
        </div>
      </div>`).join("");
  }

  await loadNetWorthChart();

  // Show portfolio badges if cached from last review
  const rv = await api("GET", "/api/portfolio/review");
  if (rv.review?.portfolio_badges?.length || rv.review?.agents?.health?.portfolio_badges?.length) {
    const badges = rv.review.portfolio_badges || rv.review.agents?.health?.result?.portfolio_badges || [];
    renderPortfolioBadges(badges);
  }
  // Render investor type from health agent or summary
  const investorProfile = rv.review?.investor_profile
    || rv.review?.agents?.health?.investor_profile
    || rv.review?.agents?.summary?.investor_profile
    || null;
  if (investorProfile) renderInvestorProfile(investorProfile);
}

const BADGE_ICONS = {
  "Diversification Master": "🌍",
  "Dividend Investor":      "💰",
  "Growth Hunter":          "🚀",
  "Africa First":           "🌍",
  "Tech Forward":           "💻",
  "Income Builder":         "📈",
  "Risk Manager":           "🛡️",
  "Long Term Thinker":      "⏳",
  "Global Citizen":         "🌐",
  "Growth Potential":       "📈",
  "Risk Management":        "🛡️",
  "Diversification Needed": "🥧",
};

function badgeIcon(b) {
  // Use our known map first; fall back to icon field only if it's an emoji
  const known = BADGE_ICONS[b.badge];
  if (known) return known;
  // Detect emoji: code point > 0x2000
  const ico = (b.icon||"").trim();
  if (ico && ico.codePointAt(0) > 0x2000) return ico;
  return "✦";
}

function renderPortfolioBadges(badges) {
  const el = document.getElementById("portfolio-badges");
  if (!el || !badges?.length) return;
  const valid = badges.filter(b => b.awarded !== false && b.badge);
  if (!valid.length) return;
  el.style.cssText = "display:flex;flex-wrap:wrap;gap:.5rem;margin-bottom:1rem";
  el.innerHTML = valid.map(b => `
    <div class="portfolio-badge" title="${b.description||""}">
      <span class="badge-icon">${badgeIcon(b)}</span>
      <span class="badge-name">${b.badge}</span>
    </div>`).join("");
}

function renderInvestorProfile(profile) {
  if (!profile?.type) return;
  const banner   = document.getElementById("investor-type-banner");
  const icon     = document.getElementById("investor-icon");
  const typeEl   = document.getElementById("investor-type-label");
  const subEl    = document.getElementById("investor-sub-label");
  const riskEl   = document.getElementById("investor-risk");
  const horizEl  = document.getElementById("investor-horizon");
  const goalEl   = document.getElementById("investor-goal");

  if (!banner) return;

  const RISK_COLOR = {
    CONSERVATIVE:"var(--green)", MODERATE:"var(--gold)", AGGRESSIVE:"var(--red)"
  };
  const ICONS = {
    "Growth Investor":"🚀", "Income Investor":"💰", "Value Investor":"🔍",
    "Balanced Investor":"⚖️", "Speculative Trader":"⚡", "Africa-Focused Investor":"🌍",
    "Conservative Saver":"🛡️", "Thematic Investor":"🌐"
  };

  if (icon)    icon.textContent   = ICONS[profile.type] || "📊";
  if (typeEl)  typeEl.textContent = profile.type || "—";
  if (subEl)   subEl.textContent  = profile.sub_type || "";
  if (riskEl) {
    riskEl.textContent = profile.risk_appetite || "—";
    riskEl.style.borderColor = RISK_COLOR[profile.risk_appetite] || "var(--gold)";
    riskEl.style.color       = RISK_COLOR[profile.risk_appetite] || "var(--gold)";
  }
  if (horizEl) horizEl.textContent = profile.time_horizon || "—";
  if (goalEl)  goalEl.textContent  = profile.primary_goal  || "—";

  banner.style.display = "block";
}

async function loadNetWorthChart() {
  const d = await api("GET", "/api/portfolio/snapshots");
  const snaps = d.snapshots || [];
  const wrap  = document.getElementById("chart-wrap");
  const empty = document.getElementById("chart-empty");

  if (!snaps.length) {
    if (wrap)  wrap.style.display = "none";
    if (empty) empty.style.display = "block";
    return;
  }
  if (wrap)  wrap.style.display = "block";
  if (empty) empty.style.display = "none";

  const labels     = snaps.map(s => fmtDate(s.date));
  const totalVals  = snaps.map(s => s.total_value);
  const stockVals  = snaps.map(s => s.stock_value);
  const otherVals  = snaps.map(s => s.other_value);

  const ctx = document.getElementById("net-worth-chart");
  if (!ctx) return;

  if (_netWorthChart) _netWorthChart.destroy();
  _netWorthChart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        { label:"Total", data:totalVals, borderColor:"#c9a84c", backgroundColor:"rgba(201,168,76,.08)",
          tension:.35, pointRadius:3, pointBackgroundColor:"#c9a84c", fill:true },
        { label:"Stocks", data:stockVals, borderColor:"#5b87b5", backgroundColor:"transparent",
          tension:.35, pointRadius:2, borderDash:[4,3] },
        { label:"Other", data:otherVals, borderColor:"#5c9e6a", backgroundColor:"transparent",
          tension:.35, pointRadius:2, borderDash:[4,3] },
      ]
    },
    options: {
      responsive:true, maintainAspectRatio:false,
      plugins: {
        legend: { labels:{ color:"#a09880", font:{size:11}, boxWidth:16 } },
        tooltip: { callbacks: { label: ctx => fmt(ctx.raw) } }
      },
      scales: {
        x: { ticks:{color:"#6b6456",font:{size:10}}, grid:{color:"rgba(255,255,255,.04)"} },
        y: { ticks:{color:"#6b6456",font:{size:10}, callback:v => fmt(v)},
             grid:{color:"rgba(255,255,255,.04)"} }
      }
    }
  });
}

async function takeSnapshot() {
  const d = await api("POST", "/api/portfolio/snapshot", {});
  if (d.ok) { toast("Snapshot saved ✓"); loadNetWorthChart(); }
}

/* ══════════════════════════════════════════════════════════════════════════
   STOCKS
══════════════════════════════════════════════════════════════════════════ */
let _allLots = [];

function _sparklineSVG(history) {
  if (!history || history.length < 2) return "";
  const prices = history.map(h => h.price);
  const min = Math.min(...prices), max = Math.max(...prices);
  const range = max - min || 1;
  const W = 80, H = 28, pad = 2;
  const points = prices.map((p, i) => {
    const x = pad + (i / (prices.length-1)) * (W - 2*pad);
    const y = pad + (1 - (p-min)/range) * (H - 2*pad);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const last = prices[prices.length-1], first = prices[0];
  const color = last >= first ? "#5c9e6a" : "#c0564e";
  return `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" style="overflow:visible">
    <polyline points="${points}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>`;
}

async function loadStocks() {
  const d = await api("GET", "/api/stocks");
  const set = (id, v) => { const el=document.getElementById(id); if(el) el.textContent=v; };
  const col = (id, v) => { const el=document.getElementById(id); if(el) el.style.color=v>=0?"var(--green)":"var(--red)"; };

  set("p-cost", fmt(d.total_cost));
  set("p-mkt",  d.total_market ? fmt(d.total_market) : "—");
  set("p-gain", sign(d.total_gain) + fmt(d.total_gain));
  set("p-pct",  sign(d.portfolio_pct) + d.portfolio_pct + "%");
  col("p-gain", d.total_gain); col("p-pct", d.portfolio_pct);

  // Holdings table
  _holdings = d.holdings || [];
  renderHoldingsTable(_holdings);

  // Ticker datalist
  // Ticker datalist
  const dl = document.getElementById("ticker-list");
  if (dl) dl.innerHTML = [...new Set((d.lots||[]).map(l=>l.ticker))].map(t=>`<option value="${t}">`).join("");

  // Lots table
  _allLots = d.lots || [];
  renderLotsTable(_allLots);

  // Price history
  const ph = document.getElementById("price-history-panel");
  const pb = document.getElementById("prices-body");
  if (pb && (d.price_history||[]).length) {
    ph.style.display="block";
    pb.innerHTML = d.price_history.map(p=>`<tr>
      <td>${fmtDate(p.date)}</td><td class="wht mo">${p.ticker}</td>
      <td><span class="hc-exchange-badge">${p.exchange||"NSE"}</span></td>
      <td class="mo gold">${p.price.toFixed(2)}</td><td>${p.note||"—"}</td>
      <td><button class="btn-icon" onclick="deletePrice(${p.id})">✕</button></td>
    </tr>`).join("");
  } else if (ph) ph.style.display="none";

  // Sales tab
  const rz = document.getElementById("rz-total");
  if (rz) { rz.textContent = sign(d.total_realized) + fmt(d.total_realized); rz.style.color = d.total_realized >= 0 ? "var(--green)" : "var(--red)"; }
  const sb = document.getElementById("sales-body");
  if (sb) sb.innerHTML = (d.sales||[]).length ? d.sales.map(s => {
    const gain = (s.sale_price - s.purchase_price) * s.shares;
    const pos = gain >= 0;
    return `<tr><td>${fmtDate(s.date)}</td><td class="wht mo">${s.ticker}</td>
      <td><span class="hc-exchange-badge">${s.exchange}</span></td>
      <td class="mo">${s.shares.toLocaleString()}</td>
      <td class="mo">${s.purchase_price.toFixed(2)}</td>
      <td class="mo">${s.sale_price.toFixed(2)}</td>
      <td class="mo ${pos?"dep":"wit"}">${sign(gain)}${fmt(gain)}</td>
      <td>${s.broker||"—"}</td>
      <td><button class="btn-icon" onclick="deleteSale(${s.id})">✕</button></td></tr>`;
  }).join("") : `<tr><td colspan="9" class="empty">No sales recorded yet.</td></tr>`;
}



// ── Universal CSV export ──────────────────────────────────────────────────────
function tableToCSV(tableId, filename) {
  var table = document.getElementById(tableId);
  if (!table) return;
  var rows = Array.from(table.querySelectorAll("tr"));
  var lines = rows.map(function(row) {
    var cells = Array.from(row.querySelectorAll("th,td"));
    return cells.map(function(c) {
      var t = (c.innerText || "").replace(/[\r\n]+/g, " ").trim();
      return (t.indexOf(",") >= 0 || t.indexOf('"') >= 0) ? '"' + t.replace(/"/g, '""') + '"' : t;
    }).join(",");
  });
  var csv = lines.join("\n");
  var blob = new Blob([csv], {type:"text/csv"});
  var url = URL.createObjectURL(blob);
  var a = document.createElement("a");
  a.href = url; a.download = filename || "export.csv";
  document.body.appendChild(a); a.click();
  document.body.removeChild(a); URL.revokeObjectURL(url);
}

// ── Holdings table (replaces cards) ─────────────────────────────────────────
let _holdings = [];

function renderHoldingsTable(holdings) {
  const tbody = document.getElementById("holdings-body");
  if (!tbody) return;
  if (!holdings.length) {
    tbody.innerHTML = `<tr><td colspan="11" class="empty">No holdings yet. Add a purchase lot to begin.</td></tr>`;
    return;
  }
  tbody.innerHTML = holdings.map(h => {
    const hasP = h.market_price !== null && h.market_price !== undefined;
    const cur  = h.currency || "KES";
    const pos  = hasP && h.gain_loss >= 0;
    const neg  = hasP && h.gain_loss < 0;
    const rowCls = hasP ? (pos ? "row-gain" : "row-loss") : "";
    const spark  = _sparklineSVG(h.price_history || []);
    const pnl    = hasP
      ? `<span class="${pos?"pos":"neg"}">${sign(h.gain_loss)}${fmt(Math.abs(h.gain_loss), cur)}</span>`
      : `<span style="color:var(--text3)">—</span>`;
    const pct    = hasP
      ? `<span class="${pos?"pos":"neg"}">${sign(h.pct_return)}${h.pct_return}%</span>`
      : "—";
    const mktVal = hasP
      ? `<span style="color:var(--gold2)">${fmt(h.market_value, cur)}</span>`
      : `<span style="color:var(--text3)">—</span>`;
    const mktKes = (hasP && h.market_value_kes != null)
      ? `<span style="color:var(--text2)">${fmt(h.market_value_kes)}</span>`
      : "—";
    const mktP   = hasP
      ? `<span style="color:var(--gold2)">${cur} ${h.market_price.toFixed(2)}</span>`
      : `<span style="color:var(--text3);font-size:.72rem">no price</span>`;

    return `<tr class="${rowCls}" style="cursor:default">
      <td><span class="tk-badge">${h.ticker}</span></td>
      <td class="hide-xs"><span class="hc-exchange-badge">${h.exchange}</span></td>
      <td class="num-col">${h.total_shares.toLocaleString()}</td>
      <td class="num-col hide-sm" style="color:var(--text2)">${cur} ${h.avg_cost.toFixed(2)}</td>
      <td class="num-col">${mktP}</td>
      <td class="num-col hide-sm" style="color:var(--text2)">${fmt(h.total_cost, cur)}</td>
      <td class="num-col">${mktVal}</td>
      <td class="num-col">${pnl}</td>
      <td class="num-col hide-sm">${pct}</td>
      <td class="num-col hide-sm">${mktKes}</td>
      <td class="hide-sm">${spark}</td>
    </tr>`;
  }).join("");
}

function filterHoldings() {
  const q = (document.getElementById("holdings-search")?.value || "").toLowerCase();
  renderHoldingsTable(q ? _holdings.filter(h =>
    h.ticker.toLowerCase().includes(q) || (h.exchange||"").toLowerCase().includes(q)
  ) : _holdings);
}

function sortHoldings() {
  const s = document.getElementById("holdings-sort")?.value || "value_desc";
  const arr = [..._holdings];
  if      (s === "ticker")       arr.sort((a,b) => a.ticker.localeCompare(b.ticker));
  else if (s === "value_desc")   arr.sort((a,b) => (b.market_value_kes||b.market_value||b.total_cost) - (a.market_value_kes||a.market_value||a.total_cost));
  else if (s === "gain_pct_desc") arr.sort((a,b) => (b.pct_return||0) - (a.pct_return||0));
  else if (s === "gain_abs_desc") arr.sort((a,b) => (b.gain_loss||0) - (a.gain_loss||0));
  else if (s === "cost_desc")    arr.sort((a,b) => b.total_cost - a.total_cost);
  renderHoldingsTable(arr);
}

function renderLotsTable(lots) {
  const tbody = document.getElementById("lots-body");
  if (!tbody) return;
  tbody.innerHTML = lots.length ? lots.map(l => {
    const cur      = l.currency || "KES";
    const localVal = l.lot_cost_local != null ? l.lot_cost_local : (l.shares * l.purchase_price);
    const kesVal   = l.lot_cost_kes   != null ? l.lot_cost_kes   : localVal;
    const fxRate   = l.fx_rate_kes    != null ? l.fx_rate_kes    : 1;
    const isForeign = cur !== "KES";
    return `<tr data-ticker="${l.ticker}">
      <td>${fmtDate(l.date)}</td>
      <td class="wht mo">${l.ticker}</td>
      <td><span class="hc-exchange-badge">${l.exchange||"NSE"}</span></td>
      <td class="mo" style="color:var(--gold2)">${cur}</td>
      <td class="mo">${parseFloat(l.shares).toLocaleString()}</td>
      <td class="mo">${cur} ${parseFloat(l.purchase_price).toFixed(2)}</td>
      <td class="mo gold">${fmt(localVal, cur)}</td>
      <td class="mo" style="color:var(--text2)">
        ${isForeign ? `${fmt(kesVal)}<span style="font-size:.6rem;color:var(--text3);display:block">@${fxRate} per ${cur}</span>` : `${fmt(kesVal)}`}
      </td>
      <td>${l.broker||"—"}</td>
      <td style="display:flex;gap:.3rem">
        <button class="btn-icon" onclick="openEditLot(${JSON.stringify(l).replace(/"/g,'&quot;')})" title="Edit">✎</button>
        <button class="btn-icon" onclick="deleteLot(${l.id})" title="Delete">✕</button>
      </td></tr>`;
  }).join("") :
  `<tr><td colspan="10" class="empty">No purchases yet.</td></tr>`;
}

function filterLots() {
  const q = (document.getElementById("lot-search")?.value||"").toUpperCase().trim();
  renderLotsTable(q ? _allLots.filter(l => l.ticker.includes(q)) : _allLots);
}

async function addLot() {
  const ticker   = document.getElementById("lot-ticker").value.trim().toUpperCase();
  const exchange = document.getElementById("lot-exchange").value;
  const shares   = document.getElementById("lot-shares").value;
  const price    = document.getElementById("lot-price").value;
  const date     = document.getElementById("lot-date").value;
  const broker   = document.getElementById("lot-broker").value.trim();
  const currency = document.getElementById("lot-currency")?.value || "KES";
  const d = await api("POST","/api/stocks/lot",{ticker,exchange,shares,purchase_price:price,currency,date,broker});
  if (d.ok) {
    toast(`${shares} × ${ticker} @ ${price} added ✓`);
    ["lot-ticker","lot-shares","lot-price","lot-broker"].forEach(id=>document.getElementById(id).value="");
    loadStocks(); loadOverview();
  }
}

function openEditLot(lot) {
  document.getElementById("el-id").value     = lot.id;
  document.getElementById("el-ticker").value = lot.ticker;
  document.getElementById("el-exchange").value = lot.exchange||"NSE";
  document.getElementById("el-shares").value = lot.shares;
  document.getElementById("el-price").value  = lot.purchase_price;
  document.getElementById("el-date").value   = lot.date;
  document.getElementById("el-broker").value = lot.broker||"";
  document.getElementById("edit-lot-modal").style.display = "flex";
}
async function saveLotEdit() {
  const id = document.getElementById("el-id").value;
  const payload = {
    ticker: document.getElementById("el-ticker").value.toUpperCase().trim(),
    exchange: document.getElementById("el-exchange").value,
    shares: document.getElementById("el-shares").value,
    purchase_price: document.getElementById("el-price").value,
    date: document.getElementById("el-date").value,
    broker: document.getElementById("el-broker").value.trim()
  };
  const d = await api("PUT", `/api/stocks/lot/${id}`, payload);
  if (d.ok) { closeModal("edit-lot-modal"); toast("Lot updated ✓"); loadStocks(); loadOverview(); }
}

async function addPrice() {
  const ticker   = document.getElementById("price-ticker").value.trim().toUpperCase();
  const exchange = document.getElementById("price-exchange").value;
  const price    = document.getElementById("price-val").value;
  const date     = document.getElementById("price-date").value;
  const d = await api("POST","/api/stocks/price",{ticker,exchange,price,date});
  if (d.ok) {
    toast(`${ticker} price updated ✓`);
    document.getElementById("price-ticker").value = "";
    document.getElementById("price-val").value = "";
    loadStocks(); loadOverview();
  }
}

async function deleteLot(id) {
  if (!confirm("Remove this purchase lot?")) return;
  const d = await api("DELETE",`/api/stocks/lot/${id}`);
  if (d.ok) { toast("Lot removed."); loadStocks(); loadOverview(); }
}
async function deletePrice(id) {
  if (!confirm("Remove this price entry?")) return;
  const d = await api("DELETE",`/api/stocks/price/${id}`);
  if (d.ok) { toast("Price removed."); loadStocks(); loadOverview(); }
}

// ── Gemini ─────────────────────────────────────────────────────────────────
const PRICE_AGENTS = [
  {id:"agent1", icon:"📡", name:"Price Fetcher",    desc:"Fetching all ticker prices"},
  {id:"agent2", icon:"🔎", name:"Anomaly Checker",  desc:"Comparing to previous prices"},
  {id:"agent3", icon:"✅", name:"Reviewer",          desc:"Re-verifying flagged prices"},
];

async function fetchPricesAI() {
  const btn = document.getElementById("fetch-btn");
  const st  = document.getElementById("fetch-status");
  const ppl = document.getElementById("price-agent-status");
  const trk = document.getElementById("price-pipeline-track");

  btn.disabled = true; btn.textContent = "Running pipeline…";
  st.textContent = ""; st.className = "fetch-status";

  // Show pipeline UI
  if (ppl) ppl.style.display = "block";
  if (trk) renderPriceAgents({});

  try {
    // Auto-fetch FX first if stale
    const fxCheck = await api("GET", "/api/fx-rates");
    const fxEmpty = !fxCheck.rates || Object.keys(fxCheck.rates).filter(k=>k!=="KES").length === 0;
    if (fxEmpty) {
      st.textContent = "⬡ Agent 0: Fetching FX rates first…";
      await api("POST", "/api/fx-rates/fetch", {});
    }

    // Show agent 1 running
    if (trk) renderPriceAgents({agent1:{status:"running"}, agent2:{status:"waiting"}, agent3:{status:"waiting"}});

    const d = await api("POST", "/api/stocks/fetch-prices", {});

    if (d.ok) {
      // Update pipeline display with results
      if (trk && d.agents) renderPriceAgents(d.agents);
      if (ppl) setTimeout(() => { if(ppl) ppl.style.display="none"; }, 5000);

      const a1 = d.agents?.agent1 || {};
      const a2 = d.agents?.agent2 || {};
      const a3 = d.agents?.agent3 || {};

      let msg = `✓ ${d.written} prices written`;
      if (a2.flagged) msg += ` · ${a2.flagged} flagged`;
      if (a3.confirmed) msg += ` · ${a3.confirmed} confirmed`;
      if (a3.corrected) msg += ` · ${a3.corrected} corrected`;
      if (a3.manual_review) msg += ` · ${a3.manual_review} need review`;
      if (d.skipped?.length) msg += ` · ${d.skipped.length} already up-to-date`;

      st.textContent = msg;
      st.className   = d.agents?.agent3?.manual_review ? "fetch-status" : "fetch-status ok";
      toast("Price pipeline complete ✓");

      // Show anomalies panel if there are pending items
      if (d.manual_review?.length > 0) {
        loadAnomalies();
      }

      loadStocks(); loadOverview(); loadFxRates();

    } else if (d.error?.includes("API key")) {
      toast("Add your Gemini API key in Settings first.", "error");
      switchTab("settings");
      if (ppl) ppl.style.display = "none";
    } else {
      st.textContent = `✗ ${d.error||"Pipeline error"}`;
      st.className   = "fetch-status err";
      if (ppl) ppl.style.display = "none";
    }
  } catch(e) {
    st.textContent = "Network error — " + e.message;
    st.className   = "fetch-status err";
    if (ppl) ppl.style.display = "none";
  }
  finally {
    btn.disabled = false;
    btn.textContent = "Fetch Current Prices";
  }
}

function renderPriceAgents(agents) {
  const trk = document.getElementById("price-pipeline-track");
  if (!trk) return;
  trk.innerHTML = PRICE_AGENTS.map(a => {
    const ag  = agents[a.id] || {};
    const st  = ag.status || "waiting";
    const cls = st==="done"?"agent-done":st==="running"?"agent-running":st==="error"?"agent-err":"agent-wait";
    const spin= st==="running" ? '<span class="agent-spinner"></span>' : "";
    const extra = st === "done" ? (() => {
      if (a.id==="agent1") return ` · ${ag.prices_fetched||0} prices`;
      if (a.id==="agent2") return ` · ${ag.clean||0} clean, ${ag.flagged||0} flagged`;
      if (a.id==="agent3") return ` · ${ag.confirmed||0} confirmed, ${ag.corrected||0} corrected, ${ag.manual_review||0} manual`;
      return "";
    })() : "";
    return `<div class="agent-step ${cls}">
      <div class="agent-step-icon">${a.icon}${spin}</div>
      <div class="agent-step-info">
        <div class="agent-step-name">Agent ${a.id.replace("agent","")} — ${a.name}</div>
        <div class="agent-step-desc">${st==="error"?(ag.error||"Error"):(a.desc+extra)}</div>
      </div>
      <div class="agent-step-status">${st==="done"?"✓":st==="running"?"…":st==="error"?"✗":"·"}</div>
    </div>`;
  }).join("");
}

// ── Anomaly management ────────────────────────────────────────────────────────
async function loadAnomalies() {
  const d = await api("GET", "/api/prices/anomalies");
  const panel = document.getElementById("anomalies-panel");
  const body  = document.getElementById("anomalies-body");
  if (!panel || !body) return;

  if (!d.pending?.length && !d.resolved?.length) {
    panel.style.display = "none";
    return;
  }

  panel.style.display = "block";

  const pendingRows = (d.pending||[]).map(a => `
    <div class="anomaly-row" id="anomaly-${a.id}">
      <div class="anomaly-head">
        <div class="anomaly-ticker">
          <span class="${a.type==='fx'?'':'wht'} mo">${a.ticker}</span>
          ${a.exchange && a.exchange!=='FX' ? `<span class="hc-exchange-badge">${a.exchange}</span>` : ''}
          <span class="badge-err">⚠ Manual Review</span>
          <span class="badge-info" style="font-size:.62rem">${a.reason||''}</span>
        </div>
        <div class="anomaly-actions">
          <button class="btn btn-ghost btn-sm" onclick="acceptAnomaly(${a.id})">Accept</button>
          <button class="btn btn-ghost btn-sm" onclick="correctAnomaly(${a.id}, ${a.fetched_value})">Correct</button>
          <button class="btn btn-ghost btn-sm" style="color:var(--text3)" onclick="dismissAnomaly(${a.id})">Dismiss</button>
        </div>
      </div>
      <div class="anomaly-detail">
        <span>Previous: <strong>${a.previous_value!=null ? a.previous_value : "—"}</strong></span>
        <span>Fetched: <strong style="color:${(a.pct_change||0)>0?'var(--green)':'var(--red)'}">${a.fetched_value}</strong></span>
        <span class="${(a.pct_change||0)>0?'pos':'neg'}">${a.pct_change!=null?((a.pct_change>0?'+':'')+a.pct_change+'%'):'—'}</span>
        <span style="color:var(--text3);font-size:.75rem">${a.review_note||''}</span>
      </div>
    </div>`).join("");

  const resolvedCount = d.resolved?.length || 0;
  body.innerHTML = pendingRows + (resolvedCount > 0
    ? `<div style="font-family:var(--font-mono);font-size:.7rem;color:var(--text3);margin-top:.8rem;padding-top:.8rem;border-top:1px solid var(--border)">${resolvedCount} resolved anomalies (confirmed, corrected, or dismissed)</div>`
    : "");
}

async function acceptAnomaly(id) {
  const d = await api("POST", `/api/prices/anomalies/${id}/resolve`, {action:"accept"});
  if (d.ok) { toast("Price accepted ✓"); loadAnomalies(); loadStocks(); }
}

async function dismissAnomaly(id) {
  const d = await api("POST", `/api/prices/anomalies/${id}/resolve`, {action:"dismiss"});
  if (d.ok) { toast("Anomaly dismissed."); loadAnomalies(); }
}

async function correctAnomaly(id, currentPrice) {
  const corrected = prompt(`Enter the correct price (current fetched: ${currentPrice}):`, currentPrice);
  if (!corrected || isNaN(parseFloat(corrected))) return;
  const d = await api("POST", `/api/prices/anomalies/${id}/resolve`,
    {action:"correct", price: parseFloat(corrected)});
  if (d.ok) { toast("Price corrected ✓"); loadAnomalies(); loadStocks(); }
}


// ── Settings ───────────────────────────────────────────────────────────────
async function loadKeyStatus() {
  const d = await api("GET","/api/config");
  const el  = document.getElementById("key-status");
  const smNote = document.getElementById("sm-note");
  const manualForm = document.getElementById("manual-key-form");
  if (d.using_secret_manager) {
    if (smNote) smNote.style.display = "block";
    if (manualForm) manualForm.style.display = "none";
    if (el) el.textContent = "";
  } else {
    if (smNote) smNote.style.display = "none";
    if (manualForm) manualForm.style.display = "block";
    if (el) el.textContent = d.gemini_key_set
      ? `✓ Key saved (${d.gemini_key_masked})`
      : "No key saved yet — enter your Gemini API key below.";
  }
}
async function saveGeminiKey() {
  const key = document.getElementById("gemini-key-input")?.value.trim();
  if (!key) return toast("Enter a key first.","error");
  const d = await api("POST","/api/config",{gemini_api_key:key});
  if (d.ok) { toast("Gemini key saved ✓"); document.getElementById("gemini-key-input").value=""; loadKeyStatus(); }
}

// ── FX rate management ────────────────────────────────────────────────────────


// ── Ticker search ──────────────────────────────────────────────────────────
let _tickerSearchTimeout = null;
let _activeLots = [];

async function searchTickers(prefix) {
  const input = document.getElementById(`${prefix}-ticker`);
  const sugEl = document.getElementById(`${prefix}-ticker-suggestions`);
  if (!input || !sugEl) return;

  const q = input.value.trim();
  if (q.length < 1) { sugEl.style.display = "none"; return; }

  clearTimeout(_tickerSearchTimeout);
  _tickerSearchTimeout = setTimeout(async () => {
    // Get exchange filter if available
    const exchEl = document.getElementById(`${prefix}-exchange`);
    const exch   = (exchEl && exchEl.value) ? `&exchange=${exchEl.value}` : "";
    const d = await api("GET", `/api/tickers?q=${encodeURIComponent(q)}${exch}&limit=8`);
    const tickers = d.tickers || [];
    if (!tickers.length) { sugEl.style.display = "none"; return; }

    sugEl.innerHTML = tickers.map(t => `
      <div class="ticker-suggestion" onmousedown="selectTicker('${prefix}', '${t.symbol}', '${t.exchange}', '${t.name}', '${t.currency}')">
        <span class="ts-symbol">${t.symbol}</span>
        <span class="ts-type ${t.type}">${t.type}</span>
        <span class="ts-name">${t.name}</span>
        <span class="ts-exch">${t.exchange}</span>
      </div>`).join("");
    sugEl.style.display = "block";
  }, 200);
}

function selectTicker(prefix, symbol, exchange, name, currency) {
  const input  = document.getElementById(`${prefix}-ticker`);
  const exchEl = document.getElementById(`${prefix}-exchange`);
  const sugEl  = document.getElementById(`${prefix}-ticker-suggestions`);
  if (input)  input.value  = symbol;
  if (exchEl) exchEl.value = exchange;
  const curEl = document.getElementById(`${prefix}-currency`);
  if (curEl && currency) curEl.value = currency;
  if (sugEl)  sugEl.style.display = "none";
}

function hideSuggestions(prefix) {
  setTimeout(() => {
    const el = document.getElementById(`${prefix}-ticker-suggestions`);
    if (el) el.style.display = "none";
  }, 200);
}

// ── Realized gains (lot-based) ──────────────────────────────────────────────

async function loadActiveLots() {
  const d = await api("GET", "/api/stocks/lots");
  _activeLots = d.lots || [];
  const sel = document.getElementById("sale-lot-id");
  if (!sel) return;
  sel.innerHTML = "<option value=''>— choose a lot —</option>" +
    _activeLots.map(l =>
      `<option value="${l.id}">${l.ticker} (${l.exchange}) · ${l.shares.toLocaleString()} shares @ ${fmtP(l.purchase_price, l.exchange==='NSE'?'KES':l.exchange==='LSE'?'GBP':'USD')} · ${fmtDate(l.date)}</option>`
    ).join("");
}

function onLotSelected() {
  const sel    = document.getElementById("sale-lot-id");
  const detail = document.getElementById("lot-detail");
  const lotId  = parseInt(sel.value);
  const lot    = _activeLots.find(l => l.id === lotId);

  if (!lot) {
    if (detail) detail.style.display = "none";
    return;
  }

  const cur = lot.exchange === "NSE" ? "KES" : lot.exchange === "LSE" ? "GBP" :
              lot.exchange === "JSE" ? "ZAR" : "USD";

  document.getElementById("ld-ticker").textContent   = lot.ticker;
  document.getElementById("ld-exchange").textContent  = lot.exchange;
  document.getElementById("ld-date").textContent      = fmtDate(lot.date);
  document.getElementById("ld-price").textContent     = `${cur} ${lot.purchase_price.toFixed(2)}`;
  document.getElementById("ld-shares").textContent    = `${lot.shares.toLocaleString()} shares available`;
  document.getElementById("ld-orig").textContent      = `${lot.original_shares.toLocaleString()} shares originally`;
  document.getElementById("ld-value").textContent     = fmt(lot.lot_value, cur);
  detail.style.display = "flex";

  // Auto-fill purchase price (readonly)
  document.getElementById("sale-buy-price").value = lot.purchase_price.toFixed(4);

  // Update max shares hint
  document.getElementById("sale-shares").max = lot.shares;
  document.getElementById("sale-shares-max").textContent =
    `Max: ${lot.shares.toLocaleString()} shares`;

  document.getElementById("sale-broker").value = lot.broker || "";
  updateSalePreview();
}

function updateSalePreview() {
  const lotId  = parseInt(document.getElementById("sale-lot-id")?.value);
  const lot    = _activeLots.find(l => l.id === lotId);
  const shares = parseFloat(document.getElementById("sale-shares")?.value)||0;
  const buyP   = parseFloat(document.getElementById("sale-buy-price")?.value)||0;
  const saleP  = parseFloat(document.getElementById("sale-price")?.value)||0;
  const el     = document.getElementById("sale-preview");
  if (!el) return;

  if (!lot || !shares || !buyP || !saleP) { el.textContent = ""; return; }

  if (shares > lot.shares) {
    el.textContent = `⚠ Cannot sell ${shares} — only ${lot.shares} available`;
    el.style.color = "var(--red)";
    return;
  }

  const gain = (saleP - buyP) * shares;
  const cur  = lot.exchange === "NSE" ? "KES" : lot.exchange === "LSE" ? "GBP" :
               lot.exchange === "JSE" ? "ZAR" : "USD";
  el.innerHTML =
    `<span style="color:${gain>=0?"var(--green)":"var(--red)"}">
       ${sign(gain)}${fmt(gain,cur)} gain/loss
     </span>
     &nbsp;&nbsp;
     <span style="color:var(--text3)">
       Remaining after sale: ${(lot.shares - shares).toFixed(lot.shares % 1 ? 4 : 0)} shares
     </span>`;
  el.style.color = "";
}

async function recordSale() {
  const lot_id       = document.getElementById("sale-lot-id").value;
  const shares       = document.getElementById("sale-shares").value;
  const sale_price   = document.getElementById("sale-price").value;
  const date         = document.getElementById("sale-date").value;
  const broker       = document.getElementById("sale-broker").value.trim();
  const note         = document.getElementById("sale-note").value.trim();

  if (!lot_id)      return toast("Select a lot to sell from.", "error");
  if (!shares)      return toast("Enter shares to sell.", "error");
  if (!sale_price)  return toast("Enter the sale price.", "error");

  const lot = _activeLots.find(l => l.id === parseInt(lot_id));
  if (lot && parseFloat(shares) > lot.shares) {
    return toast(`Cannot sell ${shares} — only ${lot.shares} available in this lot.`, "error");
  }

  const d = await api("POST","/api/stocks/sale",
    {lot_id: parseInt(lot_id), shares_to_sell: parseFloat(shares), sale_price, date, broker, note});

  if (d.ok) {
    const cur = lot?.exchange === "NSE" ? "KES" : lot?.exchange === "LSE" ? "GBP" : "USD";
    const msg = d.remaining > 0
      ? `Sale recorded — ${sign(d.gain_loss)}${fmt(d.gain_loss,cur)} · ${d.remaining} shares remain in lot ✓`
      : `Sale recorded — ${sign(d.gain_loss)}${fmt(d.gain_loss,cur)} · Lot fully sold ✓`;
    toast(msg);
    ["sale-shares","sale-price","sale-broker","sale-note"].forEach(id => document.getElementById(id).value="");
    document.getElementById("sale-preview").textContent = "";
    document.getElementById("lot-detail").style.display = "none";
    document.getElementById("sale-lot-id").value = "";
    loadStocks(); loadOverview(); loadActiveLots();
  }
}

async function deleteSale(id) {
  if (!confirm("Remove this sale? Shares will be restored to the lot.")) return;
  const d = await api("DELETE",`/api/stocks/sale/${id}`);
  if (d.ok) { toast("Sale removed — shares restored to lot."); loadStocks(); loadOverview(); loadActiveLots(); }
}

/* ══════════════════════════════════════════════════════════════════════════
   OTHER SAVINGS
══════════════════════════════════════════════════════════════════════════ */

// Update amount label to show selected currency
function updateAmountLabel(selectId, labelId) {
  const cur = document.getElementById(selectId)?.value || "KES";
  const lbl = document.getElementById(labelId);
  if (lbl) lbl.textContent = cur === "KES" ? "Amount (KES)" : `Amount (${cur})`;
}
async function loadSavings() {
  const data = await api("GET","/api/savings");

  // Net total in KES
  const net = document.getElementById("stat-net");
  if (net) {
    net.textContent = fmt(data.net_total);
    net.style.color = data.net_total >= 0 ? "var(--gold2)" : "var(--red)";
  }

  // Asset class summary badges (all in KES)
  const sumEl = document.getElementById("asset-summary");
  if (sumEl) sumEl.innerHTML = Object.entries(data.totals_by_class||{}).map(([cls,val])=>`
    <div class="asset-badge">
      <span class="badge-label">${cls}</span>
      <span class="badge-val ${val>=0?"pos":"neg"}">${fmt(val)}</span>
    </div>`).join("") || `<span style="color:var(--text3);font-size:.85rem">No entries yet.</span>`;

  const tbody = document.getElementById("savings-body");
  if (!tbody) return;
  tbody.innerHTML = (data.entries||[]).length ? data.entries.map(e => {
    const cur       = e.currency || "KES";
    const sign      = e.type === "deposit" ? 1 : -1;
    const amtDisp   = (sign > 0 ? "+" : "−") + cur + " " + fmt(Math.abs(e.amount));
    const kesDisp   = e.is_foreign
      ? fmt(Math.abs(e.amount_kes))
      : "—";
    const fxNote    = e.is_foreign
      ? `<span style="font-size:.6rem;color:var(--text3);display:block">@${parseFloat(e.fx_rate_kes).toFixed(4)}</span>`
      : "";
    const amtColor  = e.type === "deposit" ? "var(--green)" : "var(--red)";

    return `<tr>
      <td>${fmtDate(e.date)}</td>
      <td class="wht">${e.label}</td>
      <td><span class="asset-badge" style="display:inline-flex;padding:.15rem .55rem">${e.asset_class}</span></td>
      <td class="${e.type}">${e.type==="deposit"?"↑ Deposit":"↓ Withdrawal"}</td>
      <td class="mo" style="color:var(--gold2)">${cur}</td>
      <td class="mo" style="color:${amtColor}">${amtDisp}</td>
      <td class="mo" style="color:var(--text2)">${kesDisp}${fxNote}</td>
      <td>${e.note||"—"}</td>
      <td style="display:flex;gap:.3rem">
        <button class="btn-icon" onclick="openEditSaving(${JSON.stringify(e).replace(/"/g,'&quot;')})" title="Edit">✎</button>
        <button class="btn-icon" onclick="deleteSaving(${e.id})" title="Delete">✕</button>
      </td></tr>`;
  }).join("") : `<tr><td colspan="9" class="empty">No entries yet.</td></tr>`;
}

async function addSaving() {
  const label=document.getElementById("s-label").value.trim();
  const cls  =document.getElementById("s-class").value;
  const amt  =document.getElementById("s-amount").value;
  const type =document.getElementById("s-type").value;
  const date =document.getElementById("s-date").value;
  const note =document.getElementById("s-note").value.trim();
  const currency = document.getElementById("s-currency")?.value || "KES";
  const d = await api("POST","/api/savings",{label,asset_class:cls,amount:amt,type,currency,date,note});
  if (d.ok) {
    toast("Entry added ✓"); clearCache("/api/savings"); clearCache("/api/investments");
    document.getElementById("s-label").value="";
    document.getElementById("s-amount").value="";
    document.getElementById("s-note").value="";
    loadSavings(); loadOverview();
  }
}

function openEditSaving(entry) {
  document.getElementById("es-id").value       = entry.id;
  document.getElementById("es-label").value    = entry.label;
  document.getElementById("es-class").value    = entry.asset_class;
  document.getElementById("es-amount").value   = entry.amount;
  document.getElementById("es-type").value     = entry.type;
  document.getElementById("es-date").value     = entry.date;
  document.getElementById("es-note").value     = entry.note||"";
  const cur = entry.currency || "KES";
  const esCur = document.getElementById("es-currency");
  if (esCur) { esCur.value = cur; updateAmountLabel("es-currency","es-amount-label"); }
  document.getElementById("edit-saving-modal").style.display="flex";
}
async function saveSavingEdit() {
  const id = document.getElementById("es-id").value;
  const payload = {
    label:      document.getElementById("es-label").value.trim(),
    asset_class:document.getElementById("es-class").value,
    amount:     document.getElementById("es-amount").value,
    type:       document.getElementById("es-type").value,
    date:       document.getElementById("es-date").value,
    note:       document.getElementById("es-note").value.trim(),
    currency:   document.getElementById("es-currency")?.value || "KES",
  };
  const d = await api("PUT",`/api/savings/${id}`,payload);
  if (d.ok) { closeModal("edit-saving-modal"); toast("Entry updated ✓"); clearCache("/api/savings"); clearCache("/api/investments"); loadSavings(); loadOverview(); }
}

async function deleteSaving(id) {
  if (!confirm("Delete this entry?")) return;
  const d = await api("DELETE",`/api/savings/${id}`);
  if (d.ok) { toast("Deleted."); loadSavings(); loadOverview(); }
}

/* ══════════════════════════════════════════════════════════════════════════
   PORTFOLIO REVIEW
══════════════════════════════════════════════════════════════════════════ */

function renderReview(r) {
  const el = document.getElementById("review-content");
  if (!el) return;
  if (!r) { el.innerHTML=`<div class="panel" style="text-align:center;padding:2.5rem"><p style="font-family:var(--font-serif);font-size:1.2rem;font-weight:300;margin-bottom:.6rem">No review yet</p><p style="color:var(--text2);font-size:.86rem">Click Generate Review for your first Friday analysis.</p></div>`; return; }
  const signals = (r.stock_analysis||[]).map(s=>`<div class="signal-item"><div><div class="signal-ticker">${s.ticker} <span class="signal-exch">${s.exchange}</span></div></div><span class="signal-badge sig-${s.signal}">${s.signal}</span><span class="signal-note">${s.reasoning||""}</span></div>`).join("");
  const divs    = (r.dividend_calendar||[]).map(d=>`<div class="div-row"><span class="div-ticker">${d.ticker} <span style="color:var(--text3);font-size:.7rem">${d.exchange}</span></span><span class="div-date">${d.expected_date}</span><span class="div-yield">${d.estimated_yield||"—"} · ${d.amount_hint||""}</span></div>`).join("");
  const adds    = (r.add_recommendations||[]).map(rec=>`<div class="rec-item add"><span class="rec-priority pri-${rec.priority||"MEDIUM"}">${rec.priority||"MED"}</span><div><div class="rec-asset">${rec.asset}</div><div class="rec-reason">${rec.reason}</div><div class="rec-action">${rec.action}</div></div></div>`).join("");
  const trims   = (r.trim_recommendations||[]).map(rec=>`<div class="rec-item trim"><span class="rec-priority pri-${rec.priority||"MEDIUM"}">${rec.priority||"MED"}</span><div><div class="rec-asset">${rec.asset}</div><div class="rec-reason">${rec.reason}</div><div class="rec-action">${rec.action}</div></div></div>`).join("");
  const watches = (r.watchlist||[]).map(w=>`<div class="rec-item watch"><div style="flex:1"><div style="display:flex;align-items:center;gap:.6rem;margin-bottom:.3rem"><span style="font-family:var(--font-mono);color:var(--blue)">${w.ticker} <span style="color:var(--text3)">${w.exchange}</span></span><span style="font-family:var(--font-mono);font-size:.72rem;color:var(--gold)">${w.entry_range||""}</span></div><div class="rec-reason">${w.reason}</div><div class="rec-action">${w.thesis||""}</div></div></div>`).join("");
  el.innerHTML=`<div class="review-card">
    <div class="review-header"><div><div class="review-date">Review · ${fmtDate(r.date)}</div><div class="review-headline">${r.week_summary||"Portfolio Review"}</div></div><span class="rating-badge rating-${r.overall_rating||"NEUTRAL"}">${r.overall_rating||"NEUTRAL"}</span></div>
    <div class="review-body">
      <div class="review-section"><div class="review-section-title">Performance Summary</div><div class="review-perf">${r.performance_summary||"—"}</div></div>
      ${signals?`<div class="review-section"><div class="review-section-title">Stock Signals</div><div class="signal-grid">${signals}</div></div>`:""}
      ${divs?`<div class="review-section"><div class="review-section-title">Dividend Calendar</div>${divs}</div>`:""}
      ${adds?`<div class="review-section"><div class="review-section-title">What to Add ↑</div><div class="rec-list">${adds}</div></div>`:""}
      ${trims?`<div class="review-section"><div class="review-section-title">What to Trim ↓</div><div class="rec-list">${trims}</div></div>`:""}
      ${watches?`<div class="review-section"><div class="review-section-title">Watchlist — Not Yet Owned</div><div class="rec-list">${watches}</div></div>`:""}
    </div></div>`;
}

// ── 7-Agent Review Pipeline ──────────────────────────────────────────────────
let _pollTimer  = null;
let _activeJobId = null;

const AGENT_META = {
  performance: { icon:"📊", name:"Performance Analyst",    desc:"Metrics, returns, health score, winners & losers" },
  rebalancing: { icon:"⚖️", name:"Rebalancing Advisor",    desc:"Allocation advice with trim figures" },
  analyst:     { icon:"🔍", name:"Analyst Intelligence",   desc:"Multi-source ratings per ticker (parallel)" },
  thematic:    { icon:"🌐", name:"Thematic Researcher",    desc:"10–30yr megatrends & exposure radar" },
  corporate:   { icon:"📅", name:"Corporate Actions",      desc:"Future-dated dividends, earnings, splits" },
  dividend:    { icon:"💰", name:"Dividend Intelligence",  desc:"YTD income received + full-year projection" },
  health:      { icon:"🏥", name:"Portfolio Health",       desc:"Sharpe ratio, stress tests, investor profile" },
  verifier:    { icon:"✅", name:"Fact Verifier",           desc:"Cross-checks all findings, resends low-confidence" },
  summary:     { icon:"✦",  name:"Executive Summary",      desc:"Badges, investor type, top actions, watchlist" },
};

async function startAgenticReview() {
  const btn = document.getElementById("gen-review-btn");
  btn.disabled = true;
  btn.textContent = "Starting…";

  const r = await api("POST", "/api/portfolio/review", {});
  if (r.error) {
    if (r.error.includes("API key")) { switchTab("settings"); }
    toast(r.error, "error");
    btn.disabled = false; btn.textContent = "✦ Generate Review";
    return;
  }

  if (!r.job_id) {
    toast("Could not start review — no job_id returned. Check API key in Settings.", "error");
    btn.disabled = false; btn.textContent = "✦ Generate Review";
    console.error("[review] No job_id in response:", r);
    return;
  }

  _activeJobId = r.job_id;
  console.log("[review] Started job:", _activeJobId);
  btn.textContent = "Running…";

  // Show pipeline
  const pipeline = document.getElementById("agent-pipeline");
  if (pipeline) pipeline.style.display = "block";
  renderPipeline({});

  // Start polling
  if (_pollTimer) clearInterval(_pollTimer);
  _pollTimer = setInterval(() => pollReview(_activeJobId), 3000);
}

async function pollReview(jobId) {
  if (!jobId || jobId === "undefined") {
    console.error("[review] pollReview called with invalid jobId:", jobId);
    clearInterval(_pollTimer); _pollTimer = null;
    return;
  }
  const job = await api("GET", `/api/portfolio/review/poll/${jobId}`);
  if (job.error) {
    console.warn("[review] poll error:", job.error, "for job:", jobId);
    // If job not found after a while, stop polling and load from config
    if (job.error === "Job not found") {
      clearInterval(_pollTimer); _pollTimer = null;
      const btn = document.getElementById("gen-review-btn");
      if (btn) { btn.disabled=false; btn.textContent="✦ Generate Review"; }
      setTimeout(() => loadReview(), 1000); // try to show whatever was saved
    }
    return;
  }

  const agents = job.agents || {};
  renderPipeline(agents);

  if (job.status === "completed") {
    clearInterval(_pollTimer);
    _pollTimer = null;

    const btn = document.getElementById("gen-review-btn");
    if (btn) { btn.disabled = false; btn.textContent = "✦ Generate Review"; }

    const noteEl = document.getElementById("pipeline-note");
    if (noteEl) noteEl.textContent = "✓ Complete — " +
      new Date(agents._finished_at || "").toLocaleTimeString();

    toast("Review complete ✓");

    // Always render from cfg (loadReview) — cfg is guaranteed saved before
    // the job status flips to completed. Retry up to 3x in case of lag.
    let _renderAttempts = 0;
    async function _renderFromCfg() {
      _renderAttempts++;
      const raw = await api("GET", "/api/portfolio/review");
      if (raw?.review?.agentic && raw?.review?.agents?.summary) {
        loadReview();
      } else if (_renderAttempts < 3) {
        setTimeout(_renderFromCfg, 1000);
      } else {
        // Last resort: render directly from job data
        const summary = agents.summary?.result || {};
        const wrap    = document.getElementById("review-content");
        if (wrap) renderAgenticReview(agents, summary);
      }
    }
    _renderFromCfg();
  }
}

function renderPipeline(agents) {
  const track = document.getElementById("pipeline-track");
  if (!track) return;
  const order = ["performance","rebalancing","analyst","thematic","corporate","dividend","health","verifier","summary"];
  track.innerHTML = order.map(id => {
    const a    = agents[id] || {};
    const meta = AGENT_META[id] || {};
    const st    = a.status || "waiting";
    const pass2 = id === "verifier" && a.pass === 2;
    const cls   = st === "done"    ? "agent-done"    :
                  st === "running" ? "agent-running"  :
                  st === "revising"? "agent-running"  :
                  st === "error"   ? "agent-err"      : "agent-wait";
    const spin  = (st === "running" || st === "revising")
                  ? '<span class="agent-spinner"></span>' : "";
    const statusIcon = st==="done"?"✓":st==="revising"?"↻":st==="running"?"…":st==="error"?"✗":"·";

    // Dynamic description based on state
    let descText = meta.desc;
    if (st === "error")    descText = a.error || "Error";
    else if (st === "revising") descText = "Revising based on verifier feedback…";
    else if (pass2 && st === "running") descText = "Re-verifying revised outputs…";
    else if (pass2 && st === "done")    descText = "Second-pass verification complete";

    // Name badge
    const nameBadge = a.revised
      ? '<span style="font-size:.6rem;color:var(--gold2);margin-left:.4rem">↻ revised</span>'
      : pass2 && st === "done"
      ? '<span style="font-size:.6rem;color:var(--green);margin-left:.4rem">✓ pass 2</span>'
      : "";

    return `<div class="agent-step ${cls}">
      <div class="agent-step-icon">${meta.icon}${spin}</div>
      <div class="agent-step-info">
        <div class="agent-step-name">${meta.name}${nameBadge}</div>
        <div class="agent-step-desc">${descText}</div>
      </div>
      <div class="agent-step-status">${statusIcon}</div>
    </div>`;
  }).join("");
}

function renderAgenticReview(agents, summary) {
  const wrap = document.getElementById("review-content");
  if (!wrap) { console.warn("[review] review-content div not found"); return; }
  try {
    _renderAgenticReviewInner(agents, summary, wrap);
  } catch(err) {
    console.error("[review] renderAgenticReview error:", err);
    wrap.innerHTML = `
      <div class="panel" style="text-align:center;padding:2rem">
        <p style="color:var(--red);font-family:var(--font-mono);font-size:.82rem">
          ⚠ Error rendering review: ${err.message}
        </p>
        <p style="color:var(--text3);font-size:.78rem;margin-top:.5rem">Open browser console for details.</p>
        <button class="btn btn-primary" style="margin-top:1rem" onclick="startAgenticReview()">↻ Re-run Review</button>
      </div>`;
  }
}

function _renderAgenticReviewInner(agents, summary, wrap) {

  /* ── Declare all 9 agent result objects ────────────────────────────────── */
  const perf     = agents.performance?.result || {};
  const reb      = agents.rebalancing?.result || {};
  const analyst  = agents.analyst?.result     || {};
  const thematic = agents.thematic?.result    || {};
  const corp     = agents.corporate?.result   || {};
  const dividend = agents.dividend?.result    || {};
  const health   = agents.health?.result      || {};
  const verifier = agents.verifier?.result    || {};
  // summary already passed as param

  const RISK_C = {CONSERVATIVE:"var(--green)",MODERATE:"var(--gold)",AGGRESSIVE:"var(--red)"};
  const ICONS  = {"Growth Investor":"🚀","Income Investor":"💰","Value Investor":"🔍",
    "Balanced Investor":"⚖️","Speculative Trader":"⚡","Africa-Focused Investor":"🌍",
    "Conservative Saver":"🛡️","Thematic Investor":"🌐"};

  const today    = new Date().toISOString().split("T")[0];
  const isFuture = d => !d || d >= today;
  const date     = new Date().toLocaleDateString("en-KE",
    {weekday:"long",year:"numeric",month:"long",day:"numeric"});

  const RATING_C = {STRONG:"var(--green)",GOOD:"var(--green)",
    NEUTRAL:"var(--gold2)",CAUTION:"var(--gold)",REVIEW:"var(--red)"};
  const ratingColor = RATING_C[summary.overall_rating] || "var(--gold2)";

  /* ── Verifier confidence filter ────────────────────────────────────────── */
  const hcTickers = new Set(
    (verifier.high_confidence_only?.analyst_views||[]).map(t=>t.toUpperCase()));

  /* ── Filtered data ─────────────────────────────────────────────────────── */
  const filteredViews = (analyst.analyst_views||[])
    .filter(a => a.key_thesis && a.key_thesis.length > 10
      && (hcTickers.size===0 || hcTickers.has(a.ticker?.toUpperCase())));
  const filteredPicks = (analyst.hot_picks||[])
    .filter(p => p.thesis && p.thesis.length > 10).slice(0,4);
  const filteredDivs  = (corp.dividends||[])
    .filter(d => isFuture(d.ex_date)||isFuture(d.payment_date));
  const filteredCorp  = (corp.corporate_actions||[]).filter(a => isFuture(a.date));
  const badges        = (health.portfolio_badges||summary.portfolio_badges||[])
    .filter(b => b.awarded!==false && b.badge);
  const ip            = health.investor_profile || summary.investor_profile || {};

  /* ── Top actions ───────────────────────────────────────────────────────── */
  const actions = (summary.top_3_actions||[]).map((a,i) => `
    <div class="action-row">
      <div class="action-num">${i+1}</div>
      <div class="action-body">
        <div class="action-title">${a.action}</div>
        <div class="action-rationale">${a.rationale||""}</div>
      </div>
      <span class="urgency-badge ${a.urgency==="NOW"?"badge-err":a.urgency==="THIS_WEEK"?"badge-warn":"badge-info"}">${a.urgency||""}</span>
    </div>`).join("");

  /* ── Risk colour helper ────────────────────────────────────────────────── */
  const rc = v => v==="LOW"?"var(--green)":v==="MEDIUM"?"var(--gold)":v==="HIGH"||v==="VERY_HIGH"?"var(--red)":"var(--text3)";

  /* ── Radar row helper (shared by thematic) ─────────────────────────────── */
  const radarRow = r => {
    const pct = r.current_pct||0, tgt = r.target_pct||10;
    const sc  = r.status==="ON_TARGET"?"var(--green)":r.status==="OVERWEIGHT"?"var(--gold)":r.status==="UNDERWEIGHT"?"var(--gold2)":"var(--red)";
    return `<div class="radar-row">
      <div class="radar-theme">${r.theme}</div>
      <div class="radar-bar-wrap">
        <div class="radar-bar" style="width:${Math.min(100,pct*5)}%;background:${sc}"></div>
        <div class="radar-target-line" style="left:${Math.min(100,tgt*5)}%"></div>
      </div>
      <div class="radar-nums">
        <span style="color:${sc};font-family:var(--font-mono);font-size:.72rem">${pct}%</span>
        <span style="color:var(--text3);font-size:.65rem">/ ${tgt}% target</span>
        <span class="${r.status==="ON_TARGET"?"badge-ok":r.status==="OVERWEIGHT"?"badge-warn":r.status==="MISSING"?"badge-err":"badge-info"}" style="font-size:.58rem">${(r.status||"").replace("_"," ")}</span>
      </div>
    </div>`;
  };

  /* ════════════════════════════════════════════════════════════════════════
     BUILD HTML
  ════════════════════════════════════════════════════════════════════════ */
  wrap.innerHTML = `

  <!-- ① SUMMARY HEADER ─────────────────────────────────────────────────── -->
  <div class="review-header-card" style="
    background:var(--bg2);border:1px solid var(--border);border-radius:14px;
    padding:1.4rem 1.6rem;margin-bottom:1.2rem">

    <!-- Rating + Date -->
    <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:.5rem;margin-bottom:.8rem">
      <div style="display:flex;align-items:center;gap:.7rem">
        <div style="font-family:var(--font-mono);font-size:.68rem;color:var(--text3);text-transform:uppercase">
          ${date}
        </div>
        <span class="urgency-badge ${summary.overall_rating==="STRONG"||summary.overall_rating==="GOOD"?"badge-ok":summary.overall_rating==="CAUTION"||summary.overall_rating==="REVIEW"?"badge-err":"badge-warn"}"
              style="font-size:.65rem">
          ${summary.overall_rating||"—"}
        </span>
        ${health.health_score ? `<span style="font-family:var(--font-mono);font-size:.72rem;color:${health.health_score>=70?"var(--green)":health.health_score>=50?"var(--gold)":"var(--red)"}">Health ${health.health_score}/100</span>` : ""}
      </div>
      ${verifier.overall_confidence ? `
        <span style="font-family:var(--font-mono);font-size:.62rem;color:${rc(verifier.overall_confidence)}">
          ✅ Verified · ${verifier.overall_confidence} confidence
          ${verifier.passes_completed===2?"· 2-pass":""}
        </span>` : ""}
    </div>

    <!-- Headline -->
    ${summary.headline ? `
      <div style="font-family:var(--font-serif);font-size:1.35rem;font-weight:300;color:var(--text);margin-bottom:.6rem;line-height:1.3">
        ${summary.headline}
      </div>` : ""}

    <!-- Executive summary -->
    ${summary.executive_summary ? `
      <p style="font-size:.88rem;color:var(--text2);line-height:1.6;margin-bottom:.9rem">
        ${summary.executive_summary}
      </p>` : ""}

    <!-- Investor type strip -->
    ${ip.type ? `
      <div style="display:flex;align-items:center;gap:.7rem;flex-wrap:wrap;padding:.6rem .9rem;
                  background:var(--bg3);border-radius:10px;margin-bottom:.8rem">
        <span style="font-size:1.4rem">${ICONS[ip.type]||"📊"}</span>
        <span style="font-family:var(--font-serif);font-size:.95rem;color:var(--text)">${ip.type}</span>
        ${ip.sub_type?`<span style="font-family:var(--font-mono);font-size:.6rem;color:var(--gold2)">${ip.sub_type}</span>`:""}
        <span class="investor-pill" style="border-color:${RISK_C[ip.risk_appetite]||"var(--gold)"};color:${RISK_C[ip.risk_appetite]||"var(--gold)"}">${ip.risk_appetite||""}</span>
        <span class="investor-pill">${ip.time_horizon||""}</span>
        <span class="investor-pill">${ip.primary_goal||""}</span>
      </div>` : ""}

    <!-- Portfolio badges -->
    ${badges.length ? `
      <div style="display:flex;flex-wrap:wrap;gap:.45rem">
        ${badges.map(b=>`
          <div class="portfolio-badge" title="${b.description||""}">
            <span class="badge-icon">${badgeIcon(b)}</span>
            <span class="badge-name">${b.badge}</span>
          </div>`).join("")}
      </div>` : ""}

    <!-- Income KPIs strip -->
    ${(dividend.summary?.projected_annual_kes||summary.income_summary?.projected_annual_kes) ? `
      <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:.5rem;margin-top:.8rem">
        <div style="text-align:center;padding:.4rem;background:var(--bg3);border-radius:8px">
          <div style="font-size:.62rem;color:var(--text3)">Received YTD</div>
          <div style="font-family:var(--font-mono);font-size:.82rem;color:var(--green)">${fmt(dividend.summary?.ytd_income_kes||summary.income_summary?.ytd_income_kes||0)}</div>
        </div>
        <div style="text-align:center;padding:.4rem;background:var(--bg3);border-radius:8px">
          <div style="font-size:.62rem;color:var(--text3)">Expected Remaining</div>
          <div style="font-family:var(--font-mono);font-size:.82rem;color:var(--gold2)">${fmt(dividend.summary?.expected_remaining_kes||0)}</div>
        </div>
        <div style="text-align:center;padding:.4rem;background:var(--bg3);border-radius:8px">
          <div style="font-size:.62rem;color:var(--text3)">Projected Annual</div>
          <div style="font-family:var(--font-mono);font-size:.82rem;color:var(--text)">${fmt(dividend.summary?.projected_annual_kes||summary.income_summary?.projected_annual_kes||0)}</div>
        </div>
      </div>` : ""}
  </div>

  <!-- ② TOP ACTIONS ────────────────────────────────────────────────────── -->
  ${actions ? `
  <div class="panel">
    <div class="panel-title">⚡ Top Actions This Week</div>
    <div class="actions-list">${actions}</div>
    ${summary.next_review_focus ? `
      <div style="font-size:.75rem;color:var(--text3);font-family:var(--font-mono);margin-top:.8rem;padding-top:.6rem;border-top:1px solid var(--border)">
        Next review focus: ${summary.next_review_focus}
      </div>` : ""}
  </div>` : ""}

  <!-- ③ PERFORMANCE + REBALANCING (side by side) ──────────────────────── -->
  <div class="review-grid-2">

    <!-- Performance -->
    ${(perf.health_score||perf.performance_commentary||perf.top_performers?.length) ? `
    <div class="panel">
      <div class="panel-title" style="justify-content:space-between">
        <span>📊 Performance</span>
        ${perf.overall_rating?`<span class="urgency-badge ${perf.overall_rating==="STRONG"||perf.overall_rating==="GOOD"?"badge-ok":"badge-warn"}" style="font-size:.6rem">${perf.overall_rating}</span>`:""}
      </div>
      ${perf.health_score!=null ? `
        <div style="display:flex;align-items:center;gap:.6rem;margin-bottom:.7rem">
          <div style="flex:1;height:8px;background:var(--bg3);border-radius:4px;overflow:hidden">
            <div style="height:100%;width:${perf.health_score}%;background:${perf.health_score>=70?"var(--green)":perf.health_score>=50?"var(--gold)":"var(--red)"};border-radius:4px"></div>
          </div>
          <span style="font-family:var(--font-mono);font-size:.72rem">${perf.health_score}/100</span>
        </div>` : ""}
      ${perf.performance_commentary?`<p style="font-size:.82rem;color:var(--text2);margin-bottom:.7rem">${perf.performance_commentary}</p>`:""}
      ${(perf.top_performers||[]).length ? `
        <div class="review-sub" style="margin-bottom:.4rem">Top performers</div>
        ${perf.top_performers.slice(0,3).map(h=>`
          <div style="display:flex;justify-content:space-between;align-items:center;padding:.3rem 0;border-bottom:1px solid var(--border)">
            <span style="font-size:.82rem;color:var(--text)">${h.ticker} <span style="color:var(--text3);font-size:.7rem">${h.exchange||""}</span></span>
            <span style="font-family:var(--font-mono);font-size:.78rem;color:var(--green)">+${h.return_pct||0}%</span>
          </div>`).join("")}` : ""}
      ${(perf.underperformers||[]).length ? `
        <div class="review-sub" style="margin:.6rem 0 .4rem">Watch</div>
        ${perf.underperformers.slice(0,2).map(h=>`
          <div style="display:flex;justify-content:space-between;align-items:center;padding:.3rem 0;border-bottom:1px solid var(--border)">
            <span style="font-size:.82rem;color:var(--text)">${h.ticker}</span>
            <span style="font-family:var(--font-mono);font-size:.78rem;color:var(--red)">${h.return_pct||0}%</span>
          </div>`).join("")}` : ""}
    </div>` : ""}

    <!-- Rebalancing (trim actions) -->
    ${(reb.rebalancing_actions||[]).length ? `
    <div class="panel">
      <div class="panel-title" style="justify-content:space-between">
        <span>⚖️ Rebalancing</span>
        ${reb.overall_balance?`<span style="font-family:var(--font-mono);font-size:.62rem;color:var(--text3)">${reb.overall_balance}</span>`:""}
      </div>
      ${reb.rebalancing_summary?`<p style="font-size:.82rem;color:var(--text2);margin-bottom:.7rem">${reb.rebalancing_summary}</p>`:""}
      ${reb.rebalancing_actions.slice(0,5).map(a=>`
        <div style="display:flex;justify-content:space-between;align-items:center;padding:.35rem 0;border-bottom:1px solid var(--border);flex-wrap:wrap;gap:.3rem">
          <div style="display:flex;align-items:center;gap:.5rem">
            <span class="reb-action ${["BUY","ADD"].includes(a.action)?"pos":["SELL","TRIM"].includes(a.action)?"neg":""}">${a.action}</span>
            <span style="font-size:.82rem;color:var(--text);font-weight:500">${a.ticker||a.asset_class_or_sector||"—"}</span>
            <span class="hc-exchange-badge hide-xs">${a.exchange||""}</span>
          </div>
          <div style="text-align:right;font-family:var(--font-mono);font-size:.72rem">
            ${a.trim_pct?`<span style="color:var(--gold2)">${a.trim_pct}%</span> `:""}
            ${a.trim_value_kes_approx?`<span style="color:var(--text3)">${fmt(a.trim_value_kes_approx)}</span>`:""}
          </div>
          <div style="font-size:.72rem;color:var(--text3);width:100%">${a.rationale||""}</div>
        </div>`).join("")}
    </div>` : ""}
  </div>

  <!-- ④ PORTFOLIO HEALTH ──────────────────────────────────────────────── -->
  ${(health.risk_metrics||health.stress_tests?.length||health.health_score) ? `
  <div class="panel">
    <div class="panel-title" style="justify-content:space-between">
      <span>🏥 Portfolio Health</span>
      ${health.health_score?`<span style="font-family:var(--font-mono);font-size:.9rem;color:${health.health_score>=70?"var(--green)":health.health_score>=50?"var(--gold)":"var(--red)"}">${health.health_score}/100</span>`:""}
    </div>
    ${health.health_commentary?`<p style="font-size:.84rem;color:var(--text2);margin-bottom:1rem">${health.health_commentary}</p>`:""}

    <!-- 4-dimension score bars -->
    ${health.health_breakdown ? `
    <div style="margin-bottom:1rem">
      ${Object.entries(health.health_breakdown).map(([dim,score])=>`
        <div style="display:flex;align-items:center;gap:.8rem;margin-bottom:.4rem">
          <div style="font-size:.7rem;color:var(--text3);width:110px;flex-shrink:0;text-transform:capitalize">${dim.replace(/_/g," ")}</div>
          <div style="flex:1;height:6px;background:var(--bg3);border-radius:3px;overflow:hidden">
            <div style="height:100%;width:${(score/25)*100}%;background:${score>=20?"var(--green)":score>=13?"var(--gold)":"var(--red)"};border-radius:3px"></div>
          </div>
          <div style="font-family:var(--font-mono);font-size:.7rem;color:var(--text3);width:36px;text-align:right">${score}/25</div>
        </div>`).join("")}
    </div>` : ""}

    <!-- Risk metrics grid -->
    ${health.risk_metrics ? `
    <div style="display:grid;grid-template-columns:repeat(2,1fr);gap:.5rem;margin-bottom:.8rem">
      <div class="kpi-card">
        <div class="kpi-label">Sharpe Ratio</div>
        <div class="kpi-val" style="color:${(health.risk_metrics.sharpe_ratio||0)>=1?"var(--green)":(health.risk_metrics.sharpe_ratio||0)>=0?"var(--gold)":"var(--red)"}">${health.risk_metrics.sharpe_ratio||"—"}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Risk-Free Rate</div>
        <div class="kpi-val">${health.risk_metrics.risk_free_rate_pct||"—"}%</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Volatility</div>
        <div class="kpi-val" style="color:${rc(health.risk_metrics.estimated_volatility)}">${health.risk_metrics.estimated_volatility||"—"}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Largest Position</div>
        <div class="kpi-val" style="color:${(health.risk_metrics.largest_position_pct||0)>30?"var(--red)":(health.risk_metrics.largest_position_pct||0)>20?"var(--gold)":"var(--green)"}">
          ${health.risk_metrics.largest_position_ticker||""} ${health.risk_metrics.largest_position_pct||"—"}%
        </div>
      </div>
    </div>
    <div style="display:flex;gap:.4rem;flex-wrap:wrap;margin-bottom:.8rem">
      ${[["Concentration",health.risk_metrics.concentration_risk],["Currency",health.risk_metrics.currency_risk],["Liquidity",health.risk_metrics.liquidity_risk]]
        .map(([l,v])=>`<div style="flex:1;min-width:80px;background:var(--bg3);border:1px solid var(--border);border-radius:8px;padding:.4rem;text-align:center">
          <div style="font-size:.6rem;color:var(--text3)">${l}</div>
          <div style="font-family:var(--font-mono);font-size:.75rem;color:${rc(v)}">${v||"—"}</div>
        </div>`).join("")}
    </div>` : ""}

    <!-- Asset class health table -->
    ${(health.asset_class_health||[]).length ? `
    <div class="review-sub" style="margin-bottom:.4rem">Asset Class Health</div>
    <div class="table-wrap" style="margin-bottom:.8rem">
      <table class="data-table" style="font-size:.75rem">
        <thead><tr><th>Class</th><th class="num-col">Alloc %</th><th>Status</th><th class="hide-sm">Comment</th></tr></thead>
        <tbody>${health.asset_class_health.map(ac=>`<tr>
          <td class="mo">${ac.class||""}</td>
          <td class="num-col mo" style="font-family:var(--font-mono)">${ac.allocation_pct||0}%</td>
          <td><span class="${ac.health==="STRONG"||ac.health==="GOOD"?"badge-ok":ac.health==="NEUTRAL"?"badge-info":"badge-err"}">${ac.health||"—"}</span></td>
          <td class="hide-sm" style="font-size:.72rem;color:var(--text2)">${ac.comment||""}</td>
        </tr>`).join("")}</tbody>
      </table>
    </div>` : ""}

    <!-- Stress tests -->
    ${(health.stress_tests||[]).length ? `
    <div class="review-sub" style="margin-bottom:.4rem">⚡ Stress Tests</div>
    ${health.stress_tests.map(st=>`
      <div style="display:flex;justify-content:space-between;align-items:flex-start;padding:.5rem 0;border-bottom:1px solid var(--border);gap:.5rem;flex-wrap:wrap">
        <div style="flex:1;min-width:0">
          <div style="font-size:.82rem;color:var(--text)">${st.scenario}</div>
          <div style="font-size:.7rem;color:var(--text3)">${st.description||""}</div>
          ${st.most_affected?.length?`<div style="font-size:.65rem;color:var(--text3);margin-top:.2rem">Affected: ${st.most_affected.join(", ")}</div>`:""}
        </div>
        <div style="text-align:right;flex-shrink:0">
          <div style="font-family:var(--font-mono);font-size:.88rem;color:var(--red)">-${Math.abs(st.estimated_loss_pct||0)}%</div>
          <div style="font-size:.65rem;color:var(--text3)">${fmt(st.estimated_loss_kes||0)}</div>
        </div>
      </div>`).join("")}` : ""}

    ${(health.improvement_suggestions||[]).length ? `
    <div class="review-sub" style="margin:.8rem 0 .4rem">💡 Suggestions</div>
    ${health.improvement_suggestions.map(s=>`
      <div style="font-size:.8rem;color:var(--text2);padding:.25rem 0">→ ${s}</div>`).join("")}` : ""}
  </div>` : ""}

  <!-- ⑤ DIVIDEND INTELLIGENCE ────────────────────────────────────────── -->
  ${(dividend.summary||dividend.ytd_received?.length) ? `
  <div class="panel">
    <div class="panel-title" style="justify-content:space-between">
      <span>💰 Dividend Intelligence</span>
      ${dividend.summary?.portfolio_yield_pct?`<span style="font-family:var(--font-mono);font-size:.7rem;color:var(--text3)">${dividend.summary.portfolio_yield_pct}% yield</span>`:""}
    </div>
    ${dividend.summary?.income_commentary?`<p style="font-size:.84rem;color:var(--text2);margin-bottom:.8rem">${dividend.summary.income_commentary}</p>`:""}
    <!-- 3-KPI strip -->
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:.5rem;margin-bottom:1rem">
      <div class="kpi-card"><div class="kpi-label">Received YTD</div><div class="kpi-val" style="color:var(--green)">${fmt(dividend.summary?.ytd_income_kes||0)}</div></div>
      <div class="kpi-card"><div class="kpi-label">Expected Remaining</div><div class="kpi-val" style="color:var(--gold2)">${fmt(dividend.summary?.expected_remaining_kes||0)}</div></div>
      <div class="kpi-card"><div class="kpi-label">Projected Annual</div><div class="kpi-val">${fmt(dividend.summary?.projected_annual_kes||0)}</div></div>
    </div>
    <!-- Received table -->
    ${(dividend.ytd_received||[]).length ? `
    <div class="review-sub" style="margin-bottom:.4rem">Received This Year</div>
    <div class="table-wrap" style="margin-bottom:1rem">
      <table class="data-table" style="font-size:.76rem">
        <thead><tr><th>Ticker</th><th class="hide-xs">Exch</th><th>Ex-Date</th><th class="num-col">Per Share</th><th class="num-col">Total (Native)</th><th class="num-col">KES</th></tr></thead>
        <tbody>${dividend.ytd_received.map(d=>`<tr>
          <td class="wht mo">${d.ticker}</td>
          <td class="hide-xs"><span class="hc-exchange-badge">${d.exchange||""}</span></td>
          <td style="font-family:var(--font-mono);font-size:.7rem">${d.ex_date||"—"}</td>
          <td class="num-col mo">${d.currency||"KES"} ${(+d.amount_per_share||0).toFixed(2)}</td>
          <td class="num-col mo pos">+${d.currency||"KES"} ${(+(d.total_received||0)).toLocaleString("en-KE")}</td>
          <td class="num-col" style="color:var(--green)">${fmt(d.total_kes||0)}</td>
        </tr>`).join("")}</tbody>
      </table>
    </div>` : `<div style="font-size:.8rem;color:var(--text3);margin-bottom:.8rem">No dividends received yet this year.</div>`}
    <!-- Expected pills -->
    ${(dividend.expected_remaining||[]).length ? `
    <div class="review-sub" style="margin-bottom:.4rem">Expected Remaining (${dividend.expected_remaining.length})</div>
    <div style="display:flex;flex-wrap:wrap;gap:.4rem">
      ${dividend.expected_remaining.map(d=>`
        <div style="background:var(--bg3);border:1px solid var(--border);border-radius:8px;padding:.35rem .6rem;font-size:.72rem">
          <span style="color:var(--text);font-weight:500">${d.ticker}</span>
          <span style="color:var(--text3);margin:0 .25rem">·</span>
          <span style="color:var(--gold2);font-family:var(--font-mono)">${fmt(d.total_kes_expected||0)}</span>
          <span style="color:var(--text3);font-size:.62rem;margin-left:.25rem">${d.expected_ex_date||""}</span>
          <span class="${d.confidence==="HIGH"?"badge-ok":d.confidence==="MEDIUM"?"badge-warn":"badge-info"}" style="font-size:.55rem;margin-left:.2rem">${d.confidence||""}</span>
        </div>`).join("")}
    </div>` : ""}
  </div>` : ""}

  <!-- ⑥ ANALYST INTELLIGENCE ─────────────────────────────────────────── -->
  ${(() => {
    const covered = (analyst.analyst_views||[]).filter(a => !a.skip && !a.no_coverage && a.key_thesis);
    if (!covered.length) return "";
    return `<div class="panel">
      <div class="panel-title" style="justify-content:space-between">
        <span>🔍 Analyst Intelligence</span>
        <span style="font-family:var(--font-mono);font-size:.65rem;color:var(--text3)">
          ${covered.length} of ${(analyst.analyst_views||[]).length} tickers covered
        </span>
      </div>
      <div class="table-wrap">
        <table class="data-table" style="font-size:.76rem">
          <thead><tr>
            <th>Ticker</th>
            <th class="hide-xs">Exch</th>
            <th>Consensus</th>
            <th class="num-col hide-sm">Target</th>
            <th class="num-col hide-sm">Upside</th>
            <th>Thesis</th>
          </tr></thead>
          <tbody>
            ${covered.map(a => {
              const cc = a.consensus==="BUY"?"badge-ok":a.consensus==="SELL"?"badge-err":a.consensus==="HOLD"?"badge-info":"badge-info";
              return `<tr>
                <td class="wht mo">${a.ticker}</td>
                <td class="hide-xs"><span class="hc-exchange-badge">${a.exchange||""}</span></td>
                <td><span class="${cc}" style="font-size:.62rem">${a.consensus||"—"}</span></td>
                <td class="num-col hide-sm" style="font-family:var(--font-mono);font-size:.7rem">${a.avg_price_target||"—"}</td>
                <td class="num-col hide-sm" style="font-family:var(--font-mono);font-size:.7rem;color:${(a.upside_pct||0)>0?"var(--green)":(a.upside_pct||0)<0?"var(--red)":"var(--text3)"}">
                  ${a.upside_pct!=null?(a.upside_pct>0?"+":"")+a.upside_pct+"%":"—"}
                </td>
                <td style="font-size:.74rem;color:var(--text2)">
                  ${a.key_thesis||""}
                  ${a.recent_changes?.length?`
                    <div style="font-size:.65rem;color:var(--text3);margin-top:.1rem">
                      ${a.recent_changes.slice(0,1).map(c=>`${c.action||""} · ${c.institution||c.analyst||""} · ${c.date||""}`).join("")}
                    </div>`:""}
                </td>
              </tr>`;
            }).join("")}
          </tbody>
        </table>
      </div>
    </div>`;
  })()}

  <!-- Hot Picks -->
  ${filteredPicks.length ? `
  <div class="panel">
    <div class="panel-title">🔥 Hot Picks <small style="font-size:.62rem;color:var(--text3);font-weight:normal">(max 4 · external picks)</small></div>
    ${filteredPicks.map(p=>`
      <div style="padding:.5rem 0;border-bottom:1px solid var(--border)">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:.2rem;flex-wrap:wrap;gap:.3rem">
          <span style="font-size:.84rem;color:var(--gold2);font-weight:500">${p.ticker}
            <span class="hc-exchange-badge" style="font-size:.6rem">${p.exchange||""}</span>
          </span>
          <span style="font-size:.68rem;color:var(--text3)">${p.source||""}</span>
        </div>
        ${p.thesis?`<div style="font-size:.76rem;color:var(--text2);margin-bottom:.2rem">${p.thesis}</div>`:""}
        <div style="display:flex;gap:.6rem;flex-wrap:wrap">
          ${p.catalyst?`<div style="font-size:.68rem;color:var(--text3)">Catalyst: ${p.catalyst}</div>`:""}
          ${p.price_target?`<div style="font-size:.68rem;color:var(--gold2);font-family:var(--font-mono)">Target: ${p.price_target}</div>`:""}
          ${p.time_horizon?`<div style="font-size:.68rem;color:var(--text3)">${p.time_horizon}</div>`:""}
        </div>
      </div>`).join("")}
  </div>` : ""}

  <!-- ⑦ THEMATIC (with radar inline) ─────────────────────────────────── -->
  ${(thematic.megatrends?.length||thematic.exposure_radar?.length) ? `
  <div class="panel">
    <div class="panel-title">🌐 Thematic Opportunities</div>
    ${thematic.thematic_summary?`<p style="font-size:.84rem;color:var(--text2);margin-bottom:1rem">${thematic.thematic_summary}</p>`:""}
    <!-- Exposure radar ONCE -->
    ${(thematic.exposure_radar||[]).length ? `
    <div class="review-sub" style="margin-bottom:.5rem">Exposure Radar</div>
    <div class="thematic-radar" style="margin-bottom:1rem">
      ${thematic.exposure_radar.map(radarRow).join("")}
    </div>` : ""}
    <!-- Megatrend cards -->
    ${(thematic.megatrends||[]).slice(0,8).map(t=>`
      <div style="padding:.7rem 0;border-top:1px solid var(--border)">
        <!-- Theme header -->
        <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:.3rem;margin-bottom:.3rem">
          <span style="font-size:.86rem;color:var(--text);font-weight:500">${t.theme}</span>
          <div style="display:flex;gap:.3rem;align-items:center;flex-wrap:wrap">
            <span class="badge-info" style="font-size:.56rem">${t.horizon||""}</span>
            <span class="${t.conviction==="HIGH"?"badge-ok":t.conviction==="MEDIUM"?"badge-warn":"badge-info"}" style="font-size:.56rem">${t.conviction||""}</span>
            ${t.current_exposure?`<span class="${t.current_exposure==="ADEQUATE"?"badge-ok":t.current_exposure==="NONE"||t.current_exposure==="LOW"?"badge-warn":"badge-info"}" style="font-size:.56rem">${t.current_exposure}</span>`:""}
            ${t.current_exposure_pct?`<span style="font-family:var(--font-mono);font-size:.58rem;color:var(--text3)">${t.current_exposure_pct}%</span>`:""}
          </div>
        </div>
        ${t.rationale?`<div style="font-size:.78rem;color:var(--text2);margin-bottom:.3rem">${t.rationale}</div>`:""}
        ${t.exposure_commentary?`<div style="font-size:.7rem;color:var(--text3);font-style:italic;margin-bottom:.3rem">${t.exposure_commentary}</div>`:""}
        ${t.current_holdings_in_theme?.length?`<div style="font-size:.68rem;color:var(--text3);margin-bottom:.35rem">Currently held: ${t.current_holdings_in_theme.join(", ")}</div>`:""}

        <!-- Recommended ETFs for this theme -->
        ${(t.recommended_etfs||[]).length ? `
        <div style="margin-top:.3rem">
          <div style="font-size:.62rem;color:var(--text3);text-transform:uppercase;letter-spacing:.05em;margin-bottom:.3rem">Recommended ETFs</div>
          <div style="display:flex;flex-direction:column;gap:.3rem">
            ${(t.recommended_etfs||[]).slice(0,3).map(e=>`
              <div style="display:flex;align-items:flex-start;gap:.5rem;padding:.35rem .5rem;
                          background:var(--bg3);border:1px solid var(--border);border-radius:8px">
                <div style="flex:1;min-width:0">
                  <div style="display:flex;align-items:center;gap:.4rem;flex-wrap:wrap">
                    <span style="font-family:var(--font-mono);font-size:.78rem;color:var(--gold2);font-weight:500">${e.ticker}</span>
                    <span class="hc-exchange-badge" style="font-size:.58rem">${e.exchange||""}</span>
                    ${e.ter_pct?`<span style="font-size:.62rem;color:var(--text3)">TER ${e.ter_pct}%</span>`:""}
                    ${e.aum_usd_bn?`<span style="font-size:.62rem;color:var(--text3)">AUM $${e.aum_usd_bn}bn</span>`:""}
                    ${e.kenya_accessible===true?`<span style="font-size:.58rem;color:var(--green)">✓ KE accessible</span>`:e.kenya_accessible===false?`<span style="font-size:.58rem;color:var(--text3)">✗ Not via KE brokers</span>`:""}
                  </div>
                  ${e.name?`<div style="font-size:.7rem;color:var(--text2)">${e.name}</div>`:""}
                  ${e.why?`<div style="font-size:.68rem;color:var(--text3)">${e.why}</div>`:""}
                </div>
              </div>`).join("")}
          </div>
        </div>` : ""}
      </div>`).join("")}

    <!-- Africa opportunities -->
    ${(thematic.africa_specific||[]).length ? `
    <div class="review-sub" style="margin:.9rem 0 .4rem">🌍 Africa Opportunities</div>
    ${thematic.africa_specific.slice(0,4).map(a=>`
      <div style="padding:.5rem 0;border-bottom:1px solid var(--border)">
        <div style="font-size:.82rem;color:var(--text);font-weight:500;margin-bottom:.2rem">${a.opportunity}</div>
        <div style="font-size:.76rem;color:var(--text2);margin-bottom:.3rem">${a.rationale}</div>
        ${(a.recommended_etfs||[]).length ? `
          <div style="display:flex;flex-wrap:wrap;gap:.3rem">
            ${a.recommended_etfs.slice(0,2).map(e=>`
              <div style="background:var(--bg3);border:1px solid var(--border);border-radius:6px;padding:.25rem .5rem;font-size:.7rem">
                <span style="font-family:var(--font-mono);color:var(--gold2)">${e.ticker}</span>
                ${e.name?` · <span style="color:var(--text2)">${e.name}</span>`:""}
              </div>`).join("")}
          </div>` : ""}
      </div>`).join("")}` : ""}
  </div>` : ""}

  <!-- ⑧ CORPORATE ACTIONS ──────────────────────────────────────────── -->
  ${(filteredDivs.length||filteredCorp.length) ? `
  <div class="panel">
    <div class="panel-title" style="justify-content:space-between">
      <span>📅 Corporate Actions (Upcoming)</span>
      <span style="font-family:var(--font-mono);font-size:.65rem;color:var(--text3)">Future-dated only</span>
    </div>
    ${filteredDivs.length ? `
    <div class="review-sub" style="margin-bottom:.4rem">Dividends</div>
    <div class="table-wrap" style="margin-bottom:.8rem">
      <table class="data-table" style="font-size:.75rem">
        <thead><tr><th>Ticker</th><th>Ex-Date</th><th class="num-col">Amount</th><th class="hide-sm">Type</th></tr></thead>
        <tbody>${filteredDivs.map(d=>`<tr>
          <td class="wht mo">${d.ticker} <span class="hc-exchange-badge hide-xs" style="font-size:.6rem">${d.exchange||""}</span></td>
          <td style="font-family:var(--font-mono);font-size:.7rem;color:var(--gold2)">${d.ex_date||"—"}</td>
          <td class="num-col mo">${d.currency||""} ${d.amount_per_share||"TBA"}</td>
          <td class="hide-sm">${d.type||"—"}</td>
        </tr>`).join("")}</tbody>
      </table>
    </div>` : ""}
    ${filteredCorp.length ? `
    ${filteredCorp.slice(0,4).map(a=>`
      <div style="font-size:.78rem;color:var(--text2);padding:.3rem 0;border-bottom:1px solid var(--border)">
        <span style="color:var(--text);font-weight:500">${a.ticker}</span> · ${a.action_type||a.type||"event"} · <span style="color:var(--gold2)">${a.date||""}</span>
        ${a.description?` — ${a.description}`:""}
      </div>`).join("")}` : ""}
  </div>` : ""}

  <!-- ⑨ WATCHLIST + RISKS + OPPORTUNITIES ─────────────────────────── -->
  <div class="review-grid-2">
    ${(summary.watchlist||[]).length ? `
    <div class="panel">
      <div class="panel-title">👁 Watchlist</div>
      ${summary.watchlist.map(w=>`
        <div style="padding:.4rem 0;border-bottom:1px solid var(--border)">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <span style="font-size:.84rem;color:var(--text)">${w.ticker} <span class="hc-exchange-badge hide-xs" style="font-size:.6rem">${w.exchange||""}</span></span>
            ${w.entry_range?`<span style="font-family:var(--font-mono);font-size:.7rem;color:var(--gold2)">${w.entry_range}</span>`:""}
          </div>
          <div style="font-size:.74rem;color:var(--text3)">${w.reason||""} ${w.time_horizon?`· ${w.time_horizon}`:""}</div>
        </div>`).join("")}
    </div>` : ""}
    <div class="panel">
      ${(summary.risks_to_watch||[]).length ? `
        <div class="panel-title">⚠ Risks to Watch</div>
        ${summary.risks_to_watch.map(r=>`<div style="font-size:.8rem;color:var(--text2);padding:.25rem 0;border-bottom:1px solid var(--border)">→ ${r}</div>`).join("")}
        <div style="margin-top:.7rem"></div>` : ""}
      ${(summary.opportunities||[]).length ? `
        <div class="panel-title">✦ Opportunities</div>
        ${summary.opportunities.map(o=>`<div style="font-size:.8rem;color:var(--text2);padding:.25rem 0;border-bottom:1px solid var(--border)">→ ${o}</div>`).join("")}` : ""}
    </div>
  </div>

  <!-- ⑩ VERIFICATION FOOTER ──────────────────────────────────────── -->
  <div style="background:rgba(92,158,106,.04);border:1px solid rgba(92,158,106,.2);border-radius:10px;padding:.8rem 1rem;margin-top:.5rem">
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:.4rem;margin-bottom:.4rem">
      <span style="font-size:.75rem;color:var(--green)">
        ✅ Verification${verifier.passes_completed>1?" · "+verifier.passes_completed+" passes":""}
      </span>
      ${verifier.overall_confidence?`<span style="font-family:var(--font-mono);font-size:.65rem;color:${rc(verifier.overall_confidence)}">Overall: ${verifier.overall_confidence}</span>`:""}
      ${verifier.coherence_score!=null?`<span style="font-family:var(--font-mono);font-size:.65rem;color:var(--text3)">Coherence: ${verifier.coherence_score}/10</span>`:""}
    </div>
    ${verifier.verifier_note?`<div style="font-size:.78rem;color:var(--text2);margin-bottom:.5rem">${verifier.verifier_note}</div>`:""}
    <!-- Sub-verifier grid -->
    ${Object.keys(verifier.sub_verifier_results||{}).length ? `
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(110px,1fr));gap:.3rem;margin-bottom:.4rem">
        ${Object.entries(verifier.sub_verifier_results||{}).map(([aid,sv])=>`
          <div style="background:var(--bg3);border:1px solid var(--border);border-radius:6px;padding:.3rem .5rem;font-size:.62rem">
            <div style="color:var(--text3);margin-bottom:.1rem;text-transform:capitalize">${aid}</div>
            <div style="font-family:var(--font-mono);color:${sv.confidence==="HIGH"?"var(--green)":sv.confidence==="MEDIUM"?"var(--gold)":"var(--red)"}">
              ${sv.confidence||"?"}
              ${sv.needs_revision?` ↻`:""}
            </div>
          </div>`).join("")}
      </div>` : ""}
    <!-- Contradictions found by meta-verifier -->
    ${(verifier.contradictions||[]).length ? `
      <div style="font-size:.72rem;color:var(--gold2);margin-bottom:.3rem">
        ${verifier.contradictions.map(c=>`⚠ ${c.description||""}`).join(" · ")}
      </div>` : ""}
    <!-- Retry detail -->
    ${Object.keys(verifier.retry_counts||{}).length ? `
      <div style="display:flex;flex-wrap:wrap;gap:.3rem">
        ${Object.entries(verifier.retry_counts||{}).map(([aid,n])=>`
          <span style="font-family:var(--font-mono);font-size:.58rem;padding:.1rem .35rem;border-radius:4px;background:var(--bg3)">
            ${aid} ↻${n}/3${(verifier.forced_accepted||[]).includes(aid)?" ✓":""}
          </span>`).join("")}
      </div>` : ""}
  </div>

  `;

  /* ── Post-render: update overview badges + investor banner ─────────────── */
  if (badges.length)    renderPortfolioBadges(badges);
  if (ip.type)          renderInvestorProfile(ip);
  const dateEl = document.getElementById("review-last-date");
  if (dateEl) dateEl.textContent = "Last: " + new Date().toLocaleDateString("en-KE");
}

async function loadReview() {
  const wrap = document.getElementById("review-content");
  // Always read latest from DB — never serve stale cached review
  delete _cache["/api/portfolio/review"];
  const raw  = await api("GET", "/api/portfolio/review");
  console.log("[review] GET /api/portfolio/review →", raw?.review ? "has data" : "no data",
    raw?.review?.date, "agents:", Object.keys(raw?.review?.agents||{}).join(","));

  if (!raw || !raw.review) {
    if (wrap) wrap.innerHTML = `
      <div class="panel" style="text-align:center;padding:2.5rem 1.5rem">
        <div style="font-size:2rem;margin-bottom:.7rem">✦</div>
        <div style="font-family:var(--font-serif);font-size:1.2rem;color:var(--text);margin-bottom:.5rem">No review yet</div>
        <p style="color:var(--text3);font-size:.84rem;max-width:380px;margin:0 auto 1.2rem">
          Click <strong>✦ Generate Review</strong> to run the 9-agent AI pipeline.
        </p>
        <button class="btn btn-primary" onclick="startAgenticReview()">✦ Generate Review</button>
      </div>`;
    return;
  }

  const rev    = raw.review;
  const dateEl = document.getElementById("review-last-date");
  if (dateEl && rev.date) dateEl.textContent = "Last: " + rev.date;

  if (!rev.agentic || !rev.agents) {
    if (wrap) wrap.innerHTML = `
      <div class="panel" style="text-align:center;padding:2rem">
        <p style="color:var(--text3);font-size:.84rem;margin-bottom:1rem">
          Old review format — re-run to get the full 9-agent analysis.
        </p>
        <button class="btn btn-primary" onclick="startAgenticReview()">✦ Re-run Full Review</button>
      </div>`;
    return;
  }

  // rev.agents[aid] = the stored result object directly (already unwrapped from state)
  // Wrap each into {status:"done", result:v} so renderAgenticReview can do agent.result
  const agentMap = Object.fromEntries(
    Object.entries(rev.agents).map(([k, v]) => [k, { status: "done", result: v }])
  );
  console.log("[review] agentMap keys:", Object.keys(agentMap).join(","));

  // summary is the stored result object — also available top-level in rev
  // Prefer rev.agents.summary, fall back to top-level rev fields
  const summaryFromAgents = rev.agents.summary || {};
  console.log("[review] summaryFromAgents keys:", Object.keys(summaryFromAgents).join(","),
    "headline:", summaryFromAgents.headline?.substring?.(0,30));
  const summary = Object.keys(summaryFromAgents).length > 0
    ? summaryFromAgents
    : {
        headline:          rev.headline          || "",
        overall_rating:    rev.overall_rating    || "NEUTRAL",
        executive_summary: rev.executive_summary || "",
        top_3_actions:     rev.top_3_actions     || [],
        watchlist:         rev.watchlist         || [],
        risks_to_watch:    rev.risks_to_watch    || [],
        opportunities:     rev.opportunities     || [],
        portfolio_badges:  rev.portfolio_badges  || [],
        investor_profile:  rev.investor_profile  || {},
        income_summary:    rev.income_summary    || {},
        kes_impact_note:   rev.kes_impact_note   || "",
        next_review_focus: rev.next_review_focus || "",
      };

  renderAgenticReview(agentMap, summary);
}

async function loadFxRates() {
  const statusEl = document.getElementById("fx-status");
  const tableEl  = document.getElementById("fx-table-wrap");
  if (!statusEl) return;

  const d = await api("GET", "/api/fx-rates");
  if (!d || !d.rates) { statusEl.textContent = "No rates loaded yet."; return; }

  const asOf = d.as_of && d.as_of !== "—" ? `as of ${d.as_of}` : "defaults (not yet fetched)";
  statusEl.innerHTML = `<span style="color:var(--text3)">Rates ${asOf}</span>`;

  const CURRENCIES = ["USD","GBP","EUR","ZAR","TZS","UGX","GHS","HKD"];
  if (tableEl) {
    tableEl.innerHTML = `<table class="data-table" style="max-width:340px">
      <thead><tr><th>Currency</th><th>Rate to KES</th></tr></thead>
      <tbody>${CURRENCIES.filter(c => d.rates[c]).map(c =>
        `<tr><td class="mo" style="color:var(--gold2)">${c}</td>
             <td class="mo">1 ${c} = ${d.rates[c].toFixed(4)} KES</td></tr>`
      ).join("")}</tbody></table>`;
  }
}

async function fetchFxRates() {
  const FX_AGENTS = [
    {id:"agent1", icon:"📡", name:"FX Fetcher",   desc:"Fetching exchange rates"},
    {id:"agent2", icon:"🔎", name:"Rate Checker",  desc:"Checking for anomalies"},
    {id:"agent3", icon:"✅", name:"Rate Verifier", desc:"Verifying flagged rates"},
  ];

  // Show FX progress panel if it exists
  const fxPanel = document.getElementById("fx-agent-progress");
  if (fxPanel) {
    fxPanel.style.display = "block";
    fxPanel.innerHTML = `
      <div class="pipeline-title" style="margin-bottom:.5rem">FX Rate Pipeline</div>
      <div id="fx-agent-track" class="pipeline-track">
        ${FX_AGENTS.map(a=>`<div class="agent-step agent-running">
          <div class="agent-step-icon">${a.icon}<span class="agent-spinner"></span></div>
          <div class="agent-step-info"><div class="agent-step-name">${a.name}</div><div class="agent-step-desc">${a.desc}</div></div>
          <div class="agent-step-status">…</div>
        </div>`).join("")}
      </div>`;
  }

  ["fetch-fx-btn","fetch-fx-btn2"].forEach(id => {
    const el = document.getElementById(id);
    if (el) { el.textContent="Running FX Pipeline…"; el.disabled=true; }
  });

  const res      = document.getElementById("fx-result");
  const inlineEl = document.getElementById("fx-inline-status");
  if (inlineEl) inlineEl.textContent = "Fetching FX rates via 3-agent pipeline…";

  const d = await api("POST", "/api/fx-rates/fetch", {});

  // Update agent progress
  if (fxPanel && d.agents) {
    const trk = document.getElementById("fx-agent-track");
    if (trk) {
      trk.innerHTML = FX_AGENTS.map(a => {
        const ag  = d.agents[a.id] || {};
        const st  = ag.status || "done";
        const cls = st==="done"?"agent-done":st==="error"?"agent-err":"agent-wait";
        const extra = a.id==="agent1" ? ` · ${ag.fetched||Object.keys(ag.rates||{}).length} rates`
                    : a.id==="agent2" ? ` · ${ag.clean||0} clean, ${ag.flagged||0} flagged`
                    : ` · ${ag.confirmed||0} confirmed`;
        return `<div class="agent-step ${cls}">
          <div class="agent-step-icon">${a.icon}</div>
          <div class="agent-step-info"><div class="agent-step-name">${a.name}</div><div class="agent-step-desc">${a.desc+extra}</div></div>
          <div class="agent-step-status">${st==="done"?"✓":st==="error"?"✗":"·"}</div>
        </div>`;
      }).join("");
    }
    setTimeout(() => { if(fxPanel) fxPanel.style.display="none"; }, 7000);
  }

  ["fetch-fx-btn","fetch-fx-btn2"].forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.textContent = id==="fetch-fx-btn2" ? "↻ Update FX Rates" : "↻ Update FX Rates via Gemini";
      el.disabled = false;
    }
  });

  if (d.ok) {
    const rates     = d.rates || {};
    const ratesList = Object.entries(rates)
      .filter(([k])=>k!=="KES")
      .map(([k,v])=>`1 ${k} = ${parseFloat(v).toFixed(2)} KES`)
      .join("  ·  ");
    const anomalyNote = (d.manual_review?.length)
      ? ` · <span style="color:var(--gold)">⚠ ${d.manual_review.length} rate(s) need review</span>` : "";
    if (res) res.innerHTML = `<span style="color:var(--green)">✓ ${d.written||Object.keys(rates).length-1} rates updated ${d.date}</span>${anomalyNote}`;
    if (inlineEl) inlineEl.innerHTML = `<span style="color:var(--green)">✓ Updated</span> · ${ratesList}`;
    toast("FX rates updated ✓");
    loadFxRates();
    loadStocks();
    loadOverview();
    if (d.manual_review?.length) loadAnomalies();
  } else {
    const errMsg = d.error || "FX fetch failed";
    if (res) res.innerHTML = `<span style="color:var(--red)">✗ ${errMsg}</span>`;
    if (inlineEl) inlineEl.innerHTML = `<span style="color:var(--red)">✗ ${errMsg}</span>`;
    if (fxPanel) fxPanel.style.display = "none";
    toast(errMsg, "error");
  }
}


/* ══════════════════════════════════════════════════════════════════════════
   SUBSCRIPTIONS
══════════════════════════════════════════════════════════════════════════ */
async function loadSubscriptions() {
  const d = await api("GET","/api/subscriptions");
  const container = document.getElementById("sub-cards");
  if (!container) return;
  const subs = d.subscriptions||[];
  container.innerHTML = subs.length ? subs.map(s => renderSubCard(s)).join("") :
    `<p class="empty-msg">No subscriptions yet. Click "+ New Subscription" to get started.</p>`;
}

async function loadExpiryAlerts() {
  const d = await api("GET","/api/subscriptions/expiring?days=7");
  const banner = document.getElementById("expiry-banner");
  if (!banner) return;
  const items = d.expiring||[];
  if (!items.length) { banner.style.display="none"; return; }
  banner.style.display="block";
  banner.innerHTML=`<span class="expiry-icon">⚠</span>
    <span class="expiry-text">Expiring soon: </span>
    ${items.map(i=>`<span class="expiry-item"><strong>${i.name}</strong> expires ${fmtDate(i.end_date)} (${Math.ceil(i.days_left)}d)</span>`).join(", ")}`;
}

async function loadMonthlySpend() {
  const d = await api("GET","/api/subscriptions/monthly-spend");
  const container = document.getElementById("monthly-summary");
  if (!container) return;
  const months = (d.monthly||[]).slice(0,6);
  if (!months.length) { container.style.display="none"; return; }
  container.style.display="block";
  container.innerHTML=`<div class="monthly-title">Monthly Spend</div>
    <div class="monthly-grid">
      ${months.map(m=>`<div class="monthly-cell">
        <div class="monthly-month">${m.month}</div>
        <div class="monthly-total">${fmt(m.total)}</div>
        <div class="monthly-cats">${Object.entries(m.categories).map(([c,v])=>`<span class="monthly-cat">${c} ${fmt(v)}</span>`).join("")}</div>
      </div>`).join("")}
    </div>`;
}

function renderSubCard(s) {
  const isCls = s.sub_type === "classes";
  let headerStats="", bodyContent="";
  if (isCls) {
    const streakHtml = s.current_streak > 0
      ? `<span class="streak-badge">🔥 ${s.current_streak} streak</span>` : "";
    headerStats=`
      <div class="sub-stat"><div class="sub-stat-val">${s.remaining}</div><div class="sub-stat-lbl">remaining</div></div>
      <div class="sub-stat"><div class="sub-stat-val" style="font-size:1rem;color:var(--text2)">${s.attended}/${s.total_approved}</div><div class="sub-stat-lbl">attended</div></div>`;
    const dots = (s.classes||[]).map((c,i) =>
      `<div class="slot-dot ${c.attended?"attended":""}" title="${c.attended?`Attended ${fmtDate(c.scheduled_date)}`:`Session #${i+1}`}"
        onclick="${c.attended?`unmarkAttend(${c.id})`:`openAttend(${c.id})`}">${c.attended?"✓":i+1}</div>`).join("");
    bodyContent=`<div class="slots-mini">${dots}</div>
      ${streakHtml ? `<div style="margin-bottom:.8rem">${streakHtml}${s.best_streak>s.current_streak?` <span style="font-size:.74rem;color:var(--text3)">Best: ${s.best_streak}</span>`:""}</div>`:""}
      <div style="font-size:.78rem;color:var(--text2);margin-bottom:1rem">Total paid: <strong>${fmt(s.total_paid)}</strong> · ${s.payments.length} payment${s.payments.length!==1?"s":""}</div>`;
  } else {
    const ap = s.active_period;
    if (ap) {
      const diff = Math.ceil((new Date(ap.end_date+"T00:00:00")-new Date())/(864e5));
      const urgent = diff <= 7;
      headerStats=`<div class="sub-stat"><div class="sub-stat-val" style="color:${urgent?"var(--red)":"var(--green)"}">${diff}d</div><div class="sub-stat-lbl">remaining</div></div>`;
      bodyContent=`<div class="period-pill ${urgent?"expired":"active"}">Active until ${fmtDate(ap.end_date)} (${diff}d left)</div>
        <div style="font-size:.78rem;color:var(--text2);margin-bottom:1rem">Total paid: <strong>${fmt(s.total_paid)}</strong></div>`;
    } else {
      headerStats=`<div class="sub-stat"><div class="sub-stat-val" style="color:var(--text3)">—</div><div class="sub-stat-lbl">inactive</div></div>`;
      bodyContent=`<div class="period-pill none">No active period — record a payment to activate</div>`;
    }
  }
  const payRows = s.payments.map(p=>`<tr>
    <td>${fmtDate(p.date)}</td><td class="mo gold">${fmt(p.amount)}</td>
    <td>${isCls?`${p.classes_bought} session${p.classes_bought!==1?"s":""}`:
      `${fmtDate(p.start_date)} → ${fmtDate(p.end_date)}`}</td>
    <td>${p.note||"—"}</td></tr>`).join("");
  return `<div class="sub-card" id="sub-${s.id}">
    <div class="sub-card-header" onclick="toggleSubCard(${s.id})">
      <div class="sub-hdr-left">
        <div class="sub-name">${s.name}</div>
        <span class="sub-cat-badge">${s.category}</span>
        <span class="sub-type-badge ${s.sub_type}">${isCls?"sessions":"duration"}</span>
        ${s.note?`<span style="font-size:.75rem;color:var(--text3)">${s.note}</span>`:""}
      </div>
      <div class="sub-hdr-right">${headerStats}<span style="color:var(--text3)">▾</span></div>
    </div>
    <div class="sub-card-body" id="sub-body-${s.id}">
      ${bodyContent}
      <div class="sub-actions">
        <button class="sub-btn" onclick="openPayModal(${s.id},'${s.sub_type}','${s.name.replace(/'/g,"\\'")}')">+ Record Payment</button>
        <button class="sub-btn" onclick="openEditSub(${JSON.stringify(s).replace(/"/g,'&quot;')})">Edit</button>
        <button class="sub-btn danger" onclick="deleteSub(${s.id})">Delete</button>
      </div>
      ${payRows?`<table class="data-table" style="font-size:.78rem;margin-top:.8rem">
        <thead><tr><th>Date</th><th>Amount</th><th>${isCls?"Sessions":"Period"}</th><th>Note</th></tr></thead>
        <tbody>${payRows}</tbody></table>`:""}
    </div></div>`;
}

function toggleSubCard(id) { document.getElementById(`sub-body-${id}`)?.classList.toggle("open"); }
function openNewSubModal() { document.getElementById("new-sub-modal").style.display="flex"; }
function toggleSubTypeHint() {
  const t=document.getElementById("ns-type").value;
  const h=document.getElementById("sub-type-hint");
  if(h) h.textContent=t==="classes"?"Track individual sessions — each payment buys N sessions you can mark attended.":"Track by time period — each payment covers a start and end date (e.g. 1-month gym pass).";
}
async function createSubscription() {
  const name=document.getElementById("ns-name").value.trim();
  const cat=document.getElementById("ns-category").value;
  const type=document.getElementById("ns-type").value;
  const note=document.getElementById("ns-note").value.trim();
  const d=await api("POST","/api/subscriptions",{name,category:cat,sub_type:type,note});
  if(d.ok){toast(`"${name}" created ✓`);closeModal("new-sub-modal");document.getElementById("ns-name").value="";document.getElementById("ns-note").value="";loadSubscriptions();}
}
function openEditSub(s) {
  document.getElementById("esub-id").value      = s.id;
  document.getElementById("esub-name").value    = s.name;
  document.getElementById("esub-category").value= s.category;
  document.getElementById("esub-note").value    = s.note||"";
  document.getElementById("edit-sub-modal").style.display="flex";
}
async function saveSubEdit() {
  const id=document.getElementById("esub-id").value;
  const d=await api("PUT",`/api/subscriptions/${id}`,{name:document.getElementById("esub-name").value.trim(),category:document.getElementById("esub-category").value,note:document.getElementById("esub-note").value.trim()});
  if(d.ok){closeModal("edit-sub-modal");toast("Subscription updated ✓");loadSubscriptions();}
}
async function deleteSub(id){if(!confirm("Delete this subscription and all its data?"))return;const d=await api("DELETE",`/api/subscriptions/${id}`);if(d.ok){toast("Deleted.");loadSubscriptions();}}
function openPayModal(subId,type,name){
  if(type==="classes"){
    document.getElementById("pc-sub-id").value=subId;
    document.getElementById("pay-classes-title").textContent=`Record Payment — ${name}`;
    ["pc-amount","pc-classes","pc-note"].forEach(id=>document.getElementById(id).value="");
    document.getElementById("pc-date").value=today();
    document.getElementById("pay-classes-modal").style.display="flex";
  }else{
    document.getElementById("pd-sub-id").value=subId;
    document.getElementById("pay-duration-title").textContent=`Record Payment — ${name}`;
    ["pd-amount","pd-note"].forEach(id=>document.getElementById(id).value="");
    document.getElementById("pd-date").value=today();
    document.getElementById("pd-start").value=today();
    const e=new Date();e.setMonth(e.getMonth()+1);
    document.getElementById("pd-end").value=e.toISOString().split("T")[0];
    document.getElementById("pay-duration-modal").style.display="flex";
  }
}
async function saveClassPayment(){const sid=document.getElementById("pc-sub-id").value;const amount=document.getElementById("pc-amount").value;const classes=document.getElementById("pc-classes").value;const date=document.getElementById("pc-date").value;const note=document.getElementById("pc-note").value.trim();const d=await api("POST",`/api/subscriptions/${sid}/payment`,{amount,classes_bought:classes,date,note});if(d.ok){toast(`${classes} sessions added ✓`);closeModal("pay-classes-modal");loadSubscriptions();loadExpiryAlerts();loadMonthlySpend();}}
async function saveDurationPayment(){const sid=document.getElementById("pd-sub-id").value;const amount=document.getElementById("pd-amount").value;const date=document.getElementById("pd-date").value;const start=document.getElementById("pd-start").value;const end=document.getElementById("pd-end").value;const note=document.getElementById("pd-note").value.trim();const d=await api("POST",`/api/subscriptions/${sid}/payment`,{amount,start_date:start,end_date:end,date,note});if(d.ok){toast("Payment recorded ✓");closeModal("pay-duration-modal");loadSubscriptions();loadExpiryAlerts();loadMonthlySpend();}}
function openAttend(id){document.getElementById("m-class-id").value=id;document.getElementById("m-date").value=today();document.getElementById("m-note").value="";document.getElementById("attend-modal").style.display="flex";}
async function confirmSubAttend(){const id=document.getElementById("m-class-id").value;const date=document.getElementById("m-date").value;const note=document.getElementById("m-note").value.trim();const d=await api("PUT",`/api/subscriptions/class/${id}/attend`,{attended:true,scheduled_date:date,note});if(d.ok){closeModal("attend-modal");toast("Session marked attended ✓");loadSubscriptions();}}
async function unmarkAttend(id){const d=await api("PUT",`/api/subscriptions/class/${id}/attend`,{attended:false});if(d.ok){toast("Attendance unmarked.");loadSubscriptions();}}


// ── Excel upload ─────────────────────────────────────────────────────────────
let _uploadRows = [];

function handleFileDrop(e) {
  e.preventDefault();
  document.getElementById("upload-zone").classList.remove("drag-over");
  const file = e.dataTransfer.files[0];
  if (file) processUploadFile(file);
}

function handleFileSelect(input) {
  const file = input.files[0];
  if (file) processUploadFile(file);
}

async function processUploadFile(file) {
  if (!file.name.match(/\.xlsx?$/i)) { toast("Please upload an .xlsx file.", "error"); return; }
  if (file.size > 5 * 1024 * 1024)   { toast("File is too large — max 5MB.", "error"); return; }

  const zone = document.getElementById("upload-zone");
  zone.querySelector(".upload-label").textContent = `Parsing ${file.name}...`;

  const form = new FormData();
  form.append("file", file);

  let data;
  try {
    const resp = await fetch("/api/upload/lots-preview", { method: "POST", body: form });
    data = await resp.json();
  } catch(e) {
    toast("Upload failed — " + e.message, "error");
    zone.querySelector(".upload-label").textContent = "Click to choose file or drag & drop here";
    return;
  }
  zone.querySelector(".upload-label").textContent = "Click to choose file or drag & drop here";
  if (data.error) { toast(data.error, "error"); return; }

  _uploadRows = data.rows || [];
  renderUploadPreview(data);
}

function renderUploadPreview(data) {
  document.getElementById("upload-preview").style.display = "block";
  const hasErr = data.errors && data.errors.length > 0;
  document.getElementById("upload-summary").innerHTML =
    `<span style="color:var(--green)">✓ ${data.count} row(s) ready to import</span>` +
    (hasErr ? `<span style="color:var(--red);margin-left:1rem">⚠ ${data.errors.length} row(s) skipped</span>` : "");

  const errBox = document.getElementById("upload-errors");
  if (hasErr) {
    errBox.style.display = "block";
    errBox.innerHTML = data.errors.map(e => `<div class="upload-err-row">⚠ ${e}</div>`).join("");
  } else {
    errBox.style.display = "none";
  }

  const tbody = document.getElementById("upload-body");
  tbody.innerHTML = _uploadRows.map((r, i) => `
    <tr>
      <td class="row-check"><input type="checkbox" checked data-idx="${i}" onchange="updateRowSelection()"/></td>
      <td class="mo wht">${r.ticker}</td>
      <td><span style="font-family:var(--font-mono);font-size:.66rem;background:var(--bg3);border:1px solid var(--border2);padding:.05rem .3rem;border-radius:3px">${r.exchange}</span></td>
      <td class="mo">${r.shares.toLocaleString()}</td>
      <td class="mo">${Number(r.purchase_price).toFixed(4)}</td>
      <td class="mo" style="color:var(--gold2)">${r.currency}</td>
      <td class="mo">${r.date}</td>
      <td style="color:var(--text2)">${r.broker || "—"}</td>
      <td class="mo" style="color:var(--gold2)">${r.currency} ${Number(r.lot_value).toLocaleString()}</td>
    </tr>`).join("");

  document.getElementById("import-result").textContent = "";
  document.getElementById("confirm-import-btn").textContent = `Import ${_uploadRows.length} Row(s)`;
}

function updateRowSelection() {
  const n = document.querySelectorAll("#upload-body input[type=checkbox]:checked").length;
  const btn = document.getElementById("confirm-import-btn");
  if (btn) btn.textContent = `Import ${n} Row(s)`;
}

async function confirmImport() {
  const checked = Array.from(
    document.querySelectorAll("#upload-body input[type=checkbox]:checked"))
    .map(cb => _uploadRows[parseInt(cb.dataset.idx)]);
  if (!checked.length) { toast("Select at least one row to import.", "error"); return; }

  const btn = document.getElementById("confirm-import-btn");
  btn.textContent = "Importing...";
  btn.disabled    = true;

  const data = await api("POST", "/api/upload/lots-confirm", { rows: checked });
  btn.disabled    = false;
  btn.textContent = `Import ${checked.length} Row(s)`;

  if (data.ok) {
    document.getElementById("import-result").innerHTML =
      `<span style="color:var(--green)">✓ ${data.message}</span>`;
    toast(`✓ ${data.saved} lot(s) imported`); clearCache("/api/investments"); clearCache("/api/stocks");
    setTimeout(() => { cancelUpload(); loadStocks(); loadOverview(); loadActiveLots(); }, 1500);
  }
}

function cancelUpload() {
  document.getElementById("upload-preview").style.display = "none";
  const inp = document.getElementById("excel-file-input");
  if (inp) inp.value = "";
  _uploadRows = [];
}


// ── Exchange / Convert assets ────────────────────────────────────────────────
let _exchangeSavingsData = null; // cached savings for balance hints

function toggleExchange() {
  const f = document.getElementById("exchange-form");
  const c = document.getElementById("exchange-chevron");
  if (!f) return;
  const open = f.style.display !== "none";
  f.style.display = open ? "none" : "block";
  if (c) c.textContent = open ? "▼" : "▲";
  if (!open) {
    // Populate lot selector
    _populateExchangeLots();
    // Set today
    const ed = document.getElementById("ex-date");
    if (ed && !ed.value) ed.value = new Date().toISOString().split("T")[0];
    // Pre-load savings data for balance hints
    api("GET", "/api/savings").then(d => {
      _exchangeSavingsData = d;
      // Populate the label datalist
      const dl = document.getElementById("ex-label-list");
      if (dl && d.entries) {
        const labels = [...new Set(d.entries.map(e => e.label).filter(Boolean))];
        dl.innerHTML = labels.map(l => `<option value="${l}">`).join("");
      }
    });
  }
}

function _populateExchangeLots() {
  const lotSel = document.getElementById("ex-from-lot");
  if (!lotSel) return;
  if (_activeLots?.length) {
    lotSel.innerHTML = _activeLots.map(l =>
      `<option value="${l.id}" data-shares="${l.shares}" data-ticker="${l.ticker}"
               data-exchange="${l.exchange}" data-price="${l.purchase_price}">
        ${l.ticker} (${l.exchange}) · ${l.shares.toLocaleString("en-KE", {maximumFractionDigits:4})} shares
      </option>`
    ).join("");
    onExchangeLotChange(); // populate hints for default selection
  } else {
    lotSel.innerHTML = `<option value="">No active lots found</option>`;
  }
}

function onExchangeFromChange() {
  const t = document.getElementById("ex-from-type")?.value;
  document.getElementById("ex-from-savings").style.display = t === "savings" ? "" : "none";
  document.getElementById("ex-from-stocks").style.display  = t === "stocks"  ? "" : "none";
}

function onExchangeToChange() {
  const t = document.getElementById("ex-to-type")?.value;
  document.getElementById("ex-to-savings").style.display = t === "savings" ? "" : "none";
  document.getElementById("ex-to-stocks").style.display  = t === "stocks"  ? "" : "none";
}

function onExchangeLotChange() {
  const sel  = document.getElementById("ex-from-lot");
  const opt  = sel?.selectedOptions?.[0];
  const avEl = document.getElementById("ex-lot-available");
  const hint = document.getElementById("ex-proceeds-hint");
  if (!opt || !opt.value) return;

  const shares = parseFloat(opt.dataset.shares || 0);
  const ticker = opt.dataset.ticker;
  const exch   = opt.dataset.exchange;

  if (avEl) avEl.textContent = `Available: ${shares.toLocaleString("en-KE", {maximumFractionDigits:4})} shares`;

  // Auto-fill shares input if empty
  const sharesInput = document.getElementById("ex-from-shares");
  if (sharesInput && !sharesInput.value) sharesInput.value = shares;

  onExchangeSharesInput();
}

function onExchangeSharesInput() {
  const sel        = document.getElementById("ex-from-lot");
  const opt        = sel?.selectedOptions?.[0];
  const sharesIn   = parseFloat(document.getElementById("ex-from-shares")?.value || 0);
  const amountIn   = document.getElementById("ex-amount");
  const hint       = document.getElementById("ex-proceeds-hint");

  if (!opt || !sharesIn) return;

  const totalShares = parseFloat(opt.dataset.shares || 0);
  const isPartial   = sharesIn < totalShares - 0.000001;
  const pct         = totalShares > 0 ? Math.round(sharesIn / totalShares * 100) : 0;

  if (hint) {
    hint.textContent = isPartial
      ? `Partial sale: ${sharesIn.toLocaleString("en-KE",{maximumFractionDigits:4})} of ${totalShares.toLocaleString("en-KE",{maximumFractionDigits:4})} shares (${pct}%) · ${(totalShares-sharesIn).toLocaleString("en-KE",{maximumFractionDigits:4})} shares remain in lot`
      : `Full sale: entire lot of ${totalShares.toLocaleString("en-KE",{maximumFractionDigits:4})} shares · lot will be closed`;
    hint.style.color = isPartial ? "var(--gold2)" : "var(--text3)";
  }
}

function sellAllShares() {
  const sel = document.getElementById("ex-from-lot");
  const opt = sel?.selectedOptions?.[0];
  if (!opt) return;
  const inp = document.getElementById("ex-from-shares");
  if (inp) { inp.value = parseFloat(opt.dataset.shares || 0); onExchangeSharesInput(); }
}

function onExchangeSavingsChange() {
  const cls    = document.getElementById("ex-from-class")?.value;
  const label  = document.getElementById("ex-from-label")?.value?.trim();
  const hint   = document.getElementById("ex-savings-balance");
  if (!hint || !_exchangeSavingsData?.entries) return;

  // Filter entries by class and optionally by label
  const entries = _exchangeSavingsData.entries.filter(e =>
    (!cls   || e.asset_class === cls) &&
    (!label || e.label === label)
  );
  const bal = entries.reduce((s, e) =>
    s + (["deposit","interest"].includes(e.type) ? e.amount_kes : -e.amount_kes), 0);

  hint.textContent = bal > 0
    ? `Available balance: KES ${bal.toLocaleString("en-KE", {minimumFractionDigits:2, maximumFractionDigits:2})}`
    : label || cls
      ? `No balance found for ${label || cls}`
      : "";
  hint.style.color = bal > 0 ? "var(--green)" : "var(--red)";
}

async function recordExchange() {
  const fromType = document.getElementById("ex-from-type")?.value;
  const toType   = document.getElementById("ex-to-type")?.value;
  const amount   = parseFloat(document.getElementById("ex-amount")?.value || "0");
  const date     = document.getElementById("ex-date")?.value;
  const currency = document.getElementById("ex-currency")?.value || "KES";
  const note     = document.getElementById("ex-note")?.value || "";

  if (!amount || amount <= 0) { toast("Enter an amount", "error"); return; }
  if (!date)                  { toast("Select a date",   "error"); return; }

  const payload = { from_type: fromType, to_type: toType, amount, date, currency, note };

  if (fromType === "savings") {
    payload.from_class = document.getElementById("ex-from-class")?.value;
    payload.from_label = document.getElementById("ex-from-label")?.value?.trim();
    if (!payload.from_class) { toast("Select source asset class", "error"); return; }
  } else {
    payload.from_lot_id = parseInt(document.getElementById("ex-from-lot")?.value || "0");
    const sharesVal     = document.getElementById("ex-from-shares")?.value;
    if (sharesVal) payload.from_shares = parseFloat(sharesVal);
    if (!payload.from_lot_id) { toast("Select a stock lot", "error"); return; }
    if (!payload.from_shares || payload.from_shares <= 0) { toast("Enter shares to sell", "error"); return; }
  }

  if (toType === "savings") {
    payload.to_class = document.getElementById("ex-to-class")?.value;
    payload.to_label = document.getElementById("ex-to-label")?.value?.trim();
    if (!payload.to_class) { toast("Select destination asset class", "error"); return; }
  } else {
    payload.to_ticker   = document.getElementById("ex-to-ticker")?.value?.toUpperCase();
    payload.to_exchange = document.getElementById("ex-to-exchange")?.value;
    payload.to_shares   = parseFloat(document.getElementById("ex-to-shares")?.value || "0");
    if (!payload.to_ticker)  { toast("Enter a ticker",        "error"); return; }
    if (!payload.to_shares)  { toast("Enter shares bought",   "error"); return; }
  }

  const r = await api("POST", "/api/savings/exchange", payload);
  if (r.error) { toast(r.error, "error"); return; }

  // Show each action in the toast
  toast(`✓ ${(r.actions||[]).join(" · ")}`);

  clearCache("/api/savings"); clearCache("/api/stocks"); clearCache("/api/investments");
  clearCache("/api/stocks/lots");
  loadAll();   // reload everything

  // Reset form fields
  ["ex-amount","ex-from-shares","ex-to-shares","ex-note"].forEach(id => {
    const el = document.getElementById(id); if (el) el.value = "";
  });
  const hint = document.getElementById("ex-proceeds-hint"); if (hint) hint.textContent = "";
  const bh   = document.getElementById("ex-savings-balance"); if (bh) bh.textContent = "";
  toggleExchange(); // collapse panel
}

