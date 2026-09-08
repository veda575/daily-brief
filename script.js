// ── Formatters ────────────────────────────────────────
const fmtInt = new Intl.NumberFormat('en-US');

const CURRENCY_SYM = { USD: '$', INR: '₹', HKD: 'HK$', KRW: '₩', EUR: '€' };
function sym(c) { return CURRENCY_SYM[c] || (c ? c + ' ' : ''); }

function fmtMarketCap(n, currency) {
  if (!n) return '—';
  const s = sym(currency);
  // Indian stocks: quote in Lakh Crore (1 L Cr = 1e12) / Crore (1 Cr = 1e7),
  // matching how Google/screener show them in India.
  if (currency === 'INR') {
    if (n >= 1e12) return s + (n / 1e12).toFixed(2) + ' L Cr';
    if (n >= 1e7)  return s + (n / 1e7).toFixed(0) + ' Cr';
    return s + fmtInt.format(Math.round(n));
  }
  // Everything else (USD etc.): Trillions / Billions / Millions.
  if (n >= 1e12) return s + (n / 1e12).toFixed(2) + 'T';
  if (n >= 1e9)  return s + (n / 1e9).toFixed(2) + 'B';
  if (n >= 1e6)  return s + (n / 1e6).toFixed(2) + 'M';
  return s + fmtInt.format(Math.round(n));
}

function fmtRelative(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  const diff = (Date.now() - d.getTime()) / 1000;
  if (diff < 3600)   return Math.max(1, Math.floor(diff / 60)) + 'm ago';
  if (diff < 86400)  return Math.floor(diff / 3600) + 'h ago';
  if (diff < 604800) return Math.floor(diff / 86400) + 'd ago';
  return d.toLocaleDateString();
}

function fmtCurrentDate() {
  return new Intl.DateTimeFormat('en-GB', {
    day: '2-digit',
    month: 'long',
    year: 'numeric',
  }).format(new Date()).replace(/^0/, '');
}

function fmtCurrentDateTime() {
  const parts = new Intl.DateTimeFormat('en-IN', {
    timeZone: 'Asia/Kolkata',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
    timeZoneName: 'short',
  }).formatToParts(new Date()).reduce((acc, part) => {
    acc[part.type] = part.value;
    return acc;
  }, {});
  return `${parts.day} ${parts.month} ${parts.year}, ${parts.hour}:${parts.minute} ${parts.dayPeriod.toUpperCase()} ${parts.timeZoneName}`;
}

function fmtGainLossPercent(n, exact) {
  if (n === null || n === undefined || n === '') return 'DATA UNAVAILABLE';
  if (exact) return (Number(n) > 0 ? '+' : '') + formatDecimal(exact) + '%';
  const value = Number(n);
  if (!Number.isFinite(value)) return '—';
  return (value > 0 ? '+' : '') + value.toFixed(2) + '%';
}

function escapeHtml(s) {
  return (s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// ── Data loading ──────────────────────────────────────
async function loadJSON(path) {
  const res = await fetch(path + '?t=' + Date.now(), { signal: AbortSignal.timeout(15000), cache: 'no-store' });
  if (!res.ok) throw new Error('Failed: ' + path);
  const data = await res.json();
  if (path === 'data/stocks.json') {
    const regions = data?.regions;
    if (!regions || !['us', 'asia', 'india', 'indexes', 'commodities', 'currency'].every(k =>
      Array.isArray(regions[k]) && regions[k].length && regions[k].every(r => typeof r?.ticker === 'string' && typeof r?.name === 'string'))) {
      throw new Error('Invalid market snapshot');
    }
  } else if (!Array.isArray(data?.items) || !data.items.every(i => typeof i?.title === 'string' && typeof i?.url === 'string')) {
    throw new Error('Invalid news snapshot');
  }
  return data;
}

// ── Stocks rendering ──────────────────────────────────
// Decimal strings are companion display metadata; numeric JSON fields remain compatible.
function formatDecimal(value) {
  const text = String(value);
  if (!/^-?\d+(?:\.\d+)?$/.test(text)) return 'DATA UNAVAILABLE';
  const [whole, fraction] = text.split('.');
  return whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + (fraction === undefined ? '' : '.' + fraction);
}
function exactValue(row, field) {
  const meta = row.field_metadata?.[field];
  return ['VERIFIED', 'STALE', 'INDICATIVE'].includes(meta?.validation_status) ? meta.decimal : null;
}
function canDisplay(row, field) {
  return row.verification_version === 1 && ['VERIFIED', 'STALE', 'INDICATIVE'].includes(row.validation_status)
    && row[field] !== null && row[field] !== undefined && !!exactValue(row, field);
}
function fmtIndexValue(n, exact) {
  if (n === null || n === undefined || !Number.isFinite(Number(n))) return 'DATA UNAVAILABLE';
  return formatDecimal(exact || String(n));
}
const fmtFxValue = fmtIndexValue;
function quoteTime(iso) {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? 'Unknown quote time' :
    date.toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' }) + ' IST';
}
function quoteStatus(row) {
  const ts = row.source_timestamp;
  if (!ts) return 'DATA UNAVAILABLE' + (row.error?.reason ? ' · ' + row.error.reason.replaceAll('_', ' ') : '');
  const age = Date.now() - new Date(ts).getTime();
  const maxAge = (row.quote_policy?.max_quote_age_seconds ?? (row.market_status === 'OPEN' ? 1800 : 7 * 86400)) * 1000;
  const stale = row.validation_status === 'STALE' || Object.values(row.field_metadata || {}).some(m => m.validation_status === 'STALE') ||
    !Number.isFinite(age) || age < -120000 || age > maxAge;
  return (stale ? 'STALE · ' : '') + (row.quote_quality === 'INDICATIVE' ? 'INDICATIVE' : row.market_status || 'UNKNOWN') + ' · Quote ' +
    quoteTime(ts) + ' · ' + (row.source || 'Source unavailable') + (row.quote_basis ? ' · ' + row.quote_basis : '');
}
function fieldStatus(row, field) {
  const meta = row.field_metadata?.[field];
  if (!meta || !['STALE','INDICATIVE'].includes(meta.validation_status) && meta.quality !== 'INDICATIVE') return '';
  const label = [meta.validation_status === 'STALE' ? 'STALE' : '', meta.quality === 'INDICATIVE' || meta.validation_status === 'INDICATIVE' ? 'INDICATIVE' : '', meta.calculation ? 'Calculated' : '', meta.source || '', quoteTime(meta.source_timestamp)].filter(Boolean).join(' · ');
  return '<br><small title="' + escapeHtml(meta.calculation || meta.timestamp_scope || '') + '">' + escapeHtml(label) + '</small>';
}

function fxHeroHtml(stocks) {
  const usdInr = stocks.find(s => s.ticker === 'INR=X');
  if (!usdInr) return '';
  const available = canDisplay(usdInr, 'indexValue');
  const dir = Number(usdInr.changePercent) < 0 ? 'down' : 'up';
  return `
    <div class="fx-hero">
      <div class="fx-hero-label">US Dollar → Indian Rupee, for easy comparison</div>
      <div class="fx-hero-value">${available ? '1 USD = ₹' + fmtFxValue(usdInr.indexValue, exactValue(usdInr, 'indexValue')) : 'DATA UNAVAILABLE'}</div>
      <div class="fx-hero-change ${dir}">${canDisplay(usdInr, 'changePercent') ? fmtGainLossPercent(usdInr.changePercent, exactValue(usdInr, 'changePercent')) + ' · ' : ''}${escapeHtml(quoteStatus(usdInr))}</div>
    </div>`;
}

function commodityDisplay(row, usdInr) {
  const units = {
    'USD/metric ton': ['1 Ton', '1 metric ton (1,000 kg)', 'USD'],
    'USD/lb': ['1 Lb', '1 pound', 'USD'],
    'US¢/bushel': ['1 Bushel', '1 bushel', 'US¢'],
    'USD/bbl': ['1 Barrel', '1 barrel', 'USD'],
    'USD/troy oz': ['1 Troy Oz', '1 troy ounce', 'USD'],
    'USD/MMBtu': ['1 MMBtu', '1 million British thermal units', 'USD'],
  };
  const goldGram = row.ticker === 'GC=F' && row.unit === 'USD/troy oz';
  const [quantity, quantityTitle, currency] = goldGram ? ['1 Grm', '1 gram', 'USD'] : units[row.unit] || ['—', row.unit || '', row.currency || ''];
  const exact = exactValue(row, 'indexValue');
  const available = canDisplay(row, 'indexValue');
  let rate = 'DATA UNAVAILABLE';
  let title = exact || 'DATA UNAVAILABLE';
  let note = '';
  const fx = usdInr && canDisplay(usdInr, 'indexValue') ? Number(exactValue(usdInr, 'indexValue')) : NaN;
  const fxValid = usdInr?.base_currency === 'USD' && usdInr?.quote_currency === 'INR' && Number.isFinite(fx) && fx > 0;
  if (available && fxValid && ['USD', 'US¢'].includes(currency)) {
    // Convert cents to dollars before applying USD/INR; gold is per gram.
    const dollars = Number(exact) / (currency === 'US¢' ? 100 : 1) / (goldGram ? 31.1034768 : 1);
    rate = '≈ ₹' + new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(dollars * fx);
    title = 'Source: ' + (row.source || 'Google Finance') + ' · ' + (row.google_instrument || row.ticker) + ' · ' + currency + ' ' + exact + ' · ' +
      (goldGram ? '1 troy ounce = 31.1034768 grams · ' : '') +
      'USD/INR ' + exactValue(usdInr, 'indexValue') + ' · FX quote ' + quoteTime(usdInr.source_timestamp) + ' · INR rounded to 2 decimals';
    const fxAge = Date.now() - new Date(usdInr.source_timestamp).getTime();
    const staleFx = usdInr.validation_status === 'STALE' || !Number.isFinite(fxAge) || fxAge > (usdInr.quote_policy?.max_quote_age_seconds || 480) * 1000;
    note = 'Indicative INR conversion' + (staleFx ? ' · FX stale' : '');
  } else if (available) {
    title = 'USD/INR conversion rate unavailable';
  }
  return {quantity, quantityTitle, rate, title, note};
}

function renderStocksTable(stocks, region, usdInr = null) {
  if (!stocks || !stocks.length) {
    return '<p class="muted" style="padding:20px;">No data — run the GitHub Action to populate this.</p>';
  }
  const isIndexes = region === 'indexes';
  const isCommodities = region === 'commodities';
  const isCurrency = region === 'currency';
  const hero = isCurrency ? fxHeroHtml(stocks) : '';
  const sorted = isCurrency ? stocks.slice() : stocks.slice().sort((a, b) =>
    (a.sortName || a.name || '').localeCompare(b.sortName || b.name || '', undefined, { sensitivity: 'base' })
  );
  const rows = sorted.map(s => {
    const commodity = isCommodities ? commodityDisplay(s, usdInr) : null;
    const field = (isCurrency || isIndexes || isCommodities) ? 'indexValue' : 'marketCap';
    const value = isCommodities ? escapeHtml(commodity.rate) : !canDisplay(s, field) ? 'DATA UNAVAILABLE' : isCurrency
      ? fmtFxValue(s.indexValue, exactValue(s, 'indexValue'))
      : isIndexes
        ? fmtIndexValue(s.indexValue, exactValue(s, 'indexValue'))
        : fmtMarketCap(s.marketCap, s.currency);
    return `<tr>
      <td><strong>${escapeHtml(isCommodities && s.ticker === 'ZS=F' ? 'Soyabeans' : s.name)}</strong></td>
      <td class="muted">${isCommodities ? escapeHtml(s.source_timestamp ? quoteTime(s.source_timestamp) : 'DATA UNAVAILABLE') : escapeHtml(s.ticker) + '<br><small>' + escapeHtml(quoteStatus(s)) + '</small>'}</td>
      <td class="muted">${escapeHtml(s.sector || '')}</td>
      ${isCommodities ? '<td title="' + escapeHtml(commodity.quantityTitle) + '">' + escapeHtml(commodity.quantity) + '</td>' : ''}
      <td class="num" title="${escapeHtml(isCommodities ? commodity.title : exactValue(s, field) || 'DATA UNAVAILABLE')}">${value}${isCommodities && commodity.note ? '<br><small>' + escapeHtml(commodity.note) + '</small>' : ''}${fieldStatus(s, field)}</td>
      <td class="num">${canDisplay(s, 'changePercent') ? fmtGainLossPercent(s.changePercent, exactValue(s, 'changePercent')) : 'DATA UNAVAILABLE'}${fieldStatus(s, 'changePercent')}</td>
    </tr>`;
  }).join('');
  return `${hero}<table>
    <thead><tr>
      <th>${isCommodities ? 'Commodity' : isCurrency ? 'Currency Pair' : 'Company'}</th><th>${isCommodities ? 'Quote' : 'Symbol'}</th><th>${isCommodities ? 'Category' : isCurrency ? 'Conversion' : 'Sector'}</th>${isCommodities ? '<th>Quantity</th>' : ''}<th>${isCurrency ? 'Exchange Rate' : isCommodities ? 'Market Rate (INR)' : isIndexes ? 'Index Value' : 'Mkt Cap'}</th><th>Gain / Loss %</th>
    </tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

// ── News rendering (one window at a time, chosen from sidebar) ──
// Non-overlapping bands so each window has distinct articles.
const WINDOWS = {
  '24h':   { label: 'Last 24 hours', minDays: 0, maxDays: 1  },
  'week':  { label: 'Last week',     minDays: 1, maxDays: 7  },
  'month': { label: 'Last month',    minDays: 7, maxDays: 30 },
};

function ageDays(iso) {
  const t = new Date(iso).getTime();
  if (isNaN(t)) return Infinity;
  return (Date.now() - t) / 86400000;
}

// Heuristic importance score so "big" stories surface above filler within each band.
const KW_MAJOR_EVENT = /\b(announce|launch|release|unveil|debut|breakthrough|deal|agreement|sign|partner|fund|raise|acqui|merger|ban|crackdown|ruling|verdict|indict|sanction|tariff|invasion|airstrike|attack|killed|crisis|summit|treaty|ceasefire|election|vote|impeach|resign)\b/i;
const KW_AI_BIG     = /\b(gpt[- ]?\d|claude\s?\d|gemini\s?\d|llama|sora|grok|nvidia|openai|anthropic|deepmind|mistral|hugging\s?face)\b/i;
const KW_INDIA_BIG  = /\b(modi|rahul gandhi|amit shah|supreme court|cabinet|parliament|bjp|congress\b|elect|verdict|policy|reform|bill\b)\b/i;
const KW_WORLD_BIG  = /\b(trump|biden|putin|xi |zelens|netanyahu|iran|russia|china|ukraine|gaza|hamas|hezbollah|nato|un security|nuclear|sanctions)\b/i;

function importanceScore(item, section) {
  const text = (item.title + ' ' + (item.summary || '')).toLowerCase();
  let s = 0;
  s += Math.min(8, item.xScore || 0);
  if (item.xSignal) s += 2;
  if (KW_MAJOR_EVENT.test(text)) s += 3;
  if (section === 'tech'   && KW_AI_BIG.test(text))    s += 2;
  if (section === 'india'  && KW_INDIA_BIG.test(text)) s += 2;
  if (section === 'global' && KW_WORLD_BIG.test(text)) s += 2;
  // Slight bias toward longer summaries (proxy for substantial stories)
  if ((item.summary || '').length > 200) s += 1;
  return s;
}

function rankWithin(items, section) {
  return items.slice().sort((a, b) => {
    const di = importanceScore(b, section) - importanceScore(a, section);
    if (di !== 0) return di;
    return new Date(b.published) - new Date(a.published);
  });
}

function sliceForWindow(items, win, isTech, section) {
  const inBand = (items || []).filter(i => {
    const age = ageDays(i.published);
    return i.verification_status === 'SOURCE_CONFIRMED' && age >= 0 && age > win.minDays && age <= win.maxDays;
  });
  const ranked = rankWithin(inBand, section);

  if (!isTech) return ranked.slice(0, 20);

  // tech section: 15 AI + 5 other-tech, both ranked by importance within band
  const ai    = ranked.filter(i => i.isAI).slice(0, 15);
  const aiKeys = new Set(ai.map(i => i.url || i.title));
  const other = ranked.filter(i => !i.isAI && !aiKeys.has(i.url || i.title)).slice(0, 5);
  return rankWithin([...ai, ...other], section);
}

function safeNewsUrl(value) {
  try {
    const url = new URL(value);
    return ['https:', 'http:'].includes(url.protocol) ? url.href : '#';
  } catch { return '#'; }
}
function newsCardHtml(n) {
  const aiTag = n.isAI === false
    ? ' · <span class="tag-pill tag-tech">Tech</span>'
    : (n.isAI === true ? ' · <span class="tag-pill tag-ai">AI</span>' : '');
  return `
    <article class="news-card">
      <div class="news-head">
        <div>
          <div class="news-title">${escapeHtml(n.title)}</div>
          <div class="news-meta-row">${escapeHtml(n.source)} · ${fmtRelative(n.published)}${aiTag}</div>
        </div>
        <span class="chev">▼</span>
      </div>
      <div class="news-body">
        <div>${escapeHtml(n.summary || 'No summary available.')}</div>
        ${n.url ? `<a class="read-more" href="${escapeHtml(safeNewsUrl(n.url))}" target="_blank" rel="noopener">Read full story →</a>` : ''}
      </div>
    </article>`;
}

// All news data, kept in memory so changing the time window doesn't refetch.
const newsCache = { tech: [], india: [], global: [] };

function renderNewsForCurrentWindow(section) {
  const containerId = 'news-' + section;
  const container = document.getElementById(containerId);
  const isTech = section === 'tech';
  const win = WINDOWS[currentWindow];
  const slice = sliceForWindow(newsCache[section], win, isTech, section);

  // Update the title-bar label so user sees which window is active
  const label = document.getElementById(section + '-window-label');
  if (label) label.textContent = win.label + ' · ' + slice.length + (slice.length === 1 ? ' item' : ' items');

  container.innerHTML = slice.length
    ? slice.map(newsCardHtml).join('')
    : '<p class="muted">No items in this window.</p>';

  container.querySelectorAll('.news-card').forEach(card => {
    card.querySelector('.news-head').addEventListener('click', () => {
      card.classList.toggle('expanded');
    });
  });
}

// ── Sidebar / hamburger / routing ─────────────────────
const body = document.body;
let currentSection = 'stocks';
let currentWindow  = '24h';

document.getElementById('menuBtn').addEventListener('click', () => {
  body.classList.toggle('menu-open');
});

function setActive(section, win) {
  currentSection = section;

  // Show the right main section
  document.querySelectorAll('.section').forEach(s => {
    s.classList.toggle('active', s.id === 'section-' + section);
  });

  // Sidebar active state
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  if (section === 'stocks') {
    document.querySelector('.nav-item[data-section="stocks"]').classList.add('active');
  } else {
    currentWindow = win || '24h';
    // Mark the chosen sub-item active; ensure its parent group is expanded
    const sub = document.querySelector(
      `.nav-sub[data-section="${section}"][data-window="${currentWindow}"]`
    );
    if (sub) sub.classList.add('active');
    document.querySelectorAll('.nav-group').forEach(g => {
      g.classList.toggle('expanded', g.dataset.section === section);
    });
    renderNewsForCurrentWindow(section);
  }

  if (window.innerWidth < 820) body.classList.remove('menu-open');
}

// Top-level "Stock Market" link
document.querySelector('.nav-item[data-section="stocks"]').addEventListener('click', e => {
  e.preventDefault();
  setActive('stocks');
});

// Parent items (Tech & AI / India / Geo): expand sub-menu + show 24h
document.querySelectorAll('.nav-parent').forEach(p => {
  p.addEventListener('click', e => {
    e.preventDefault();
    const section = p.dataset.section;
    const group = p.closest('.nav-group');
    const alreadyOpen = group.classList.contains('expanded') && currentSection === section;
    if (alreadyOpen) {
      group.classList.remove('expanded');     // toggle closed if already viewing it
    } else {
      setActive(section, '24h');
    }
  });
});

// Sub-items (Last 24h / week / month under each section)
document.querySelectorAll('.nav-sub').forEach(s => {
  s.addEventListener('click', e => {
    e.preventDefault();
    setActive(s.dataset.section, s.dataset.window);
  });
});

// ── Stock subtabs ─────────────────────────────────────
let stocksData = null;
let currentRegion = 'us';

function showStockRegion(region) {
  currentRegion = region;
  document.querySelectorAll('.subtab').forEach(b => b.classList.toggle('active', b.dataset.region === region));
  const container = document.getElementById('stocks-content');
  const list = stocksData?.regions?.[region] || [];
  container.innerHTML = renderStocksTable(list, region, stocksData?.regions?.currency?.find(row => row.ticker === 'INR=X'));
}

document.querySelectorAll('.subtab').forEach(b => {
  b.addEventListener('click', () => showStockRegion(b.dataset.region));
});

// ── Init ──────────────────────────────────────────────
function updateDateTime() {
  const el = document.getElementById('live-datetime');
  if (el) el.textContent = fmtCurrentDateTime();
}

function setUpdated(...sources) {
  const ts = sources.map(s => s?.updated).filter(Boolean).sort().pop();
  const relative = ts ? ' · Snapshot changed ' + fmtRelative(ts) : '';
  document.getElementById('updated').textContent = fmtCurrentDate() + relative;
}

let refreshing = false;
async function refreshData() {
  if (refreshing) return;
  refreshing = true;
  try {
    const results = await Promise.allSettled([
      loadJSON('data/stocks.json'), loadJSON('data/news_tech.json'),
      loadJSON('data/news_india.json'), loadJSON('data/news_global.json'),
    ]);
    const expanded = new Set([...document.querySelectorAll('.news-card.expanded .read-more')].map(a => a.href));
    if (results[0].status === 'fulfilled' && results[0].value?.regions) stocksData = results[0].value;
    ['tech', 'india', 'global'].forEach((section, i) => {
      const result = results[i + 1];
      if (result.status === 'fulfilled' && Array.isArray(result.value?.items)) newsCache[section] = result.value.items;
      renderNewsForCurrentWindow(section);
    });
    showStockRegion(currentRegion);
    document.querySelectorAll('.news-card .read-more').forEach(a => {
      if (expanded.has(a.href)) a.closest('.news-card').classList.add('expanded');
    });
    // This timestamp belongs to the market snapshot, never to unrelated news.
    setUpdated(stocksData);
    if (results.some(r => r.status === 'rejected')) {
      document.getElementById('updated').textContent += ' · Refresh failed; showing saved data';
    }
  } finally { refreshing = false; }
}
updateDateTime();
setInterval(() => {
  updateDateTime();
  if (stocksData) showStockRegion(currentRegion);
}, 30000);
refreshData();
setInterval(refreshData, 300000);
if (window.innerWidth >= 820) body.classList.add('menu-open');
