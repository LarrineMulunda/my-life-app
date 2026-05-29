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

async function api(method, url, body) {
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
}

/* ══════════════════════════════════════════════════════════════════════════
   OVERVIEW
══════════════════════════════════════════════════════════════════════════ */
let _netWorthChart = null;

async function loadOverview() {
  const d = await api("GET", "/api/investments/overview");
  const set = (id, v) => { const el=document.getElementById(id); if(el) el.textContent=v; };
  const col = (id, v) => { const el=document.getElementById(id); if(el) el.style.color=v>=0?"var(--green)":"var(--red)"; };

  set("ov-cost",     "KES " + fmt(d.total_cost));
  set("ov-mkt",      "KES " + fmt(d.total_value));
  set("ov-gain",     sign(d.total_gain) + "KES " + fmt(Math.abs(d.total_gain)));
  set("ov-realized", sign(d.total_realized) + "KES " + fmt(Math.abs(d.total_realized)));
  col("ov-gain",     d.total_gain);
  col("ov-realized", d.total_realized);

  const badge = document.getElementById("ov-total-badge");
  if (badge) badge.textContent = "Total: KES " + fmt(d.total_value);

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
              <span class="ac-value">KES ${fmt(v.value)}</span>
              <span class="ac-pct">${pct}%</span>
              ${v.gain !== 0 ? `<span class="ac-gain ${gainCls}">${sign(v.gain)}KES ${fmt(Math.abs(v.gain))}</span>` : ""}
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
          <span class="broker-val">KES ${fmt(val)}</span>
          <span class="broker-pct">${(val/total*100).toFixed(1)}%</span>
        </div>
      </div>`).join("");
  }

  await loadNetWorthChart();
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
      ? `<span class="${pos?"pos":"neg"}">${sign(h.gain_loss)}${cur} ${fmt(Math.abs(h.gain_loss))}</span>`
      : `<span style="color:var(--text3)">—</span>`;
    const pct    = hasP
      ? `<span class="${pos?"pos":"neg"}">${sign(h.pct_return)}${h.pct_return}%</span>`
      : "—";
    const mktVal = hasP
      ? `<span style="color:var(--gold2)">${cur} ${fmt(h.market_value)}</span>`
      : `<span style="color:var(--text3)">—</span>`;
    const mktKes = (hasP && h.market_value_kes != null)
      ? `<span style="color:var(--text2)">KES ${fmt(h.market_value_kes)}</span>`
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
      <td class="num-col hide-sm" style="color:var(--text2)">${cur} ${fmt(h.total_cost)}</td>
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
      <td class="mo gold">${cur} ${fmt(localVal)}</td>
      <td class="mo" style="color:var(--text2)">
        ${isForeign ? `KES ${fmt(kesVal)}<span style="font-size:.6rem;color:var(--text3);display:block">@${fxRate} per ${cur}</span>` : `KES ${fmt(kesVal)}`}
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
async function fetchPricesAI() {
  const btn = document.getElementById("fetch-btn");
  const st  = document.getElementById("fetch-status");
  btn.disabled = true; btn.textContent = "Fetching…";
  st.textContent = "Calling Gemini AI with Google Search…"; st.className="fetch-status";
  try {
    // Auto-fetch FX rates first if they look stale (empty global_fx table)
    const fxCheck = await api("GET", "/api/fx-rates");
    const fxEmpty = !fxCheck.rates || Object.keys(fxCheck.rates).filter(k=>k!=="KES").length === 0;
    if (fxEmpty) {
      st.textContent = "Fetching FX rates first…";
      await api("POST", "/api/fx-rates/fetch", {});
    }

    const d = await api("POST","/api/stocks/fetch-prices",{});
    if (d.ok) {
      const skipped = d.skipped?.length ? ` · ${d.skipped.length} already up-to-date` : "";
      const names   = d.saved.map(s=>`${s.ticker} ${s.price}`).join(" · ");
      st.textContent = `✓ ${d.saved.length} updated (${d.date})${skipped}`;
      if (names) st.textContent += `: ${names}`;
      st.className = "fetch-status ok";
      toast(`${d.saved.length} price${d.saved.length!==1?"s":""} updated ✓`);
      loadStocks(); loadOverview(); loadFxRates();
    } else if (d.error?.includes("API key")) {
      toast("Add your Gemini API key in Settings first.", "error");
      switchTab("settings");
    } else {
      st.textContent = `✗ ${d.error}`; st.className="fetch-status err";
    }
  } catch(e) { st.textContent="Network error"; st.className="fetch-status err"; toast("Network error","error"); }
  finally { btn.disabled=false; btn.textContent="Fetch Current Prices"; }
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
  // Update both buttons (one on Stocks tab, one on Settings tab)
  ["fetch-fx-btn","fetch-fx-btn2"].forEach(id => {
    const el = document.getElementById(id);
    if (el) { el.textContent="Fetching FX…"; el.disabled=true; }
  });
  const res     = document.getElementById("fx-result");
  const inlineEl= document.getElementById("fx-inline-status");

  const d = await api("POST", "/api/fx-rates/fetch", {});

  ["fetch-fx-btn","fetch-fx-btn2"].forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.textContent = id==="fetch-fx-btn2" ? "↻ Update FX Rates" : "↻ Update FX Rates via Gemini";
      el.disabled = false;
    }
  });

  if (d.ok) {
    if (res) res.innerHTML = `<span style="color:var(--green)">✓ Rates updated ${d.date}</span>`;
    if (inlineEl) {
      const ratesList = Object.entries(d.rates||{})
        .filter(([k])=>k!=="KES").map(([k,v])=>`1 ${k} = ${parseFloat(v).toFixed(2)} KES`).join(" · ");
      inlineEl.innerHTML = `<span style="color:var(--green)">✓ FX updated ${d.date}</span> · ${ratesList}`;
    }
    toast("FX rates updated ✓");
    loadFxRates();
    loadStocks();
    loadOverview();
  } else {
    if (res) res.innerHTML = `<span style="color:var(--red)">✗ ${d.error}</span>`;
    if (inlineEl) inlineEl.innerHTML = `<span style="color:var(--red)">✗ ${d.error||"FX fetch failed"}</span>`;
    toast(d.error || "FX fetch failed", "error");
  }
}

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
    net.textContent = "KES " + fmt(data.net_total);
    net.style.color = data.net_total >= 0 ? "var(--gold2)" : "var(--red)";
  }

  // Asset class summary badges (all in KES)
  const sumEl = document.getElementById("asset-summary");
  if (sumEl) sumEl.innerHTML = Object.entries(data.totals_by_class||{}).map(([cls,val])=>`
    <div class="asset-badge">
      <span class="badge-label">${cls}</span>
      <span class="badge-val ${val>=0?"pos":"neg"}">KES ${fmt(val)}</span>
    </div>`).join("") || `<span style="color:var(--text3);font-size:.85rem">No entries yet.</span>`;

  const tbody = document.getElementById("savings-body");
  if (!tbody) return;
  tbody.innerHTML = (data.entries||[]).length ? data.entries.map(e => {
    const cur       = e.currency || "KES";
    const sign      = e.type === "deposit" ? 1 : -1;
    const amtDisp   = (sign > 0 ? "+" : "−") + cur + " " + fmt(Math.abs(e.amount));
    const kesDisp   = e.is_foreign
      ? "KES " + fmt(Math.abs(e.amount_kes))
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
    toast("Entry added ✓");
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
  if (d.ok) { closeModal("edit-saving-modal"); toast("Entry updated ✓"); loadSavings(); loadOverview(); }
}

async function deleteSaving(id) {
  if (!confirm("Delete this entry?")) return;
  const d = await api("DELETE",`/api/savings/${id}`);
  if (d.ok) { toast("Deleted."); loadSavings(); loadOverview(); }
}

/* ══════════════════════════════════════════════════════════════════════════
   PORTFOLIO REVIEW
══════════════════════════════════════════════════════════════════════════ */
async function loadReview() {
  const d = await api("GET","/api/portfolio/review");
  renderReview(d.review);
}

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

async function generateReview() {
  const btn=document.getElementById("gen-review-btn");
  const ld=document.getElementById("review-loading");
  btn.disabled=true; btn.textContent="Generating…"; if(ld) ld.style.display="block";
  try {
    const d = await api("POST","/api/portfolio/review",{});
    if (d.ok) { toast("Review generated ✓"); renderReview({date:today(),...d.review}); }
    else if (d.error?.includes("API key")) { toast("Add Gemini key in Settings.","error"); switchTab("settings"); }
  } catch(e) { toast("Network error","error"); }
  finally { btn.disabled=false; btn.textContent="✦ Generate Review"; if(ld) ld.style.display="none"; }
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
    toast(`✓ ${data.saved} lot(s) imported`);
    setTimeout(() => { cancelUpload(); loadStocks(); loadOverview(); loadActiveLots(); }, 1500);
  }
}

function cancelUpload() {
  document.getElementById("upload-preview").style.display = "none";
  const inp = document.getElementById("excel-file-input");
  if (inp) inp.value = "";
  _uploadRows = [];
}
