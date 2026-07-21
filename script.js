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

function fmtGainLossPercent(n) {
  const value = Number(n);
  if (!Number.isFinite(value)) return '—';
  return (value > 0 ? '+' : '') + value.toFixed(2) + '%';
}

function escapeHtml(s) {
  return (s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

// ── Data loading ──────────────────────────────────────
async function loadJSON(path) {
  const res = await fetch(path + '?t=' + Date.now());
  if (!res.ok) throw new Error('Failed: ' + path);
  return res.json();
}

// ── Stocks rendering ──────────────────────────────────
function renderStocksTable(stocks) {
  if (!stocks || !stocks.length) {
    return '<p class="muted" style="padding:20px;">No data — run the GitHub Action to populate this.</p>';
  }
  const sorted = stocks.slice().sort((a, b) =>
    (a.sortName || a.name || '').localeCompare(b.sortName || b.name || '', undefined, { sensitivity: 'base' })
  );
  const rows = sorted.map(s => {
    return `<tr>
      <td><strong>${escapeHtml(s.name)}</strong></td>
      <td class="muted">${escapeHtml(s.ticker)}</td>
      <td class="muted">${escapeHtml(s.sector || '')}</td>
      <td class="num">${fmtMarketCap(s.marketCap, s.currency)}</td>
      <td class="num">${fmtGainLossPercent(s.changePercent)}</td>
    </tr>`;
  }).join('');
  return `<table>
    <thead><tr>
      <th>Company</th><th>Ticker</th><th>Sector</th><th>Mkt Cap</th><th>Gain / Loss %</th>
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
    return age > win.minDays && age <= win.maxDays;
  });
  const ranked = rankWithin(inBand, section);

  if (!isTech) return ranked.slice(0, 20);

  // tech section: 15 AI + 5 other-tech, both ranked by importance within band
  const ai    = ranked.filter(i => i.isAI).slice(0, 15);
  const aiKeys = new Set(ai.map(i => i.url || i.title));
  const other = ranked.filter(i => !i.isAI && !aiKeys.has(i.url || i.title)).slice(0, 5);
  return rankWithin([...ai, ...other], section);
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
        ${n.url ? `<a class="read-more" href="${n.url}" target="_blank" rel="noopener">Read full story →</a>` : ''}
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

function showStockRegion(region) {
  document.querySelectorAll('.subtab').forEach(b => b.classList.toggle('active', b.dataset.region === region));
  const container = document.getElementById('stocks-content');
  const list = stocksData?.regions?.[region] || [];
  container.innerHTML = renderStocksTable(list);
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
  const relative = ts ? ' · Updated ' + fmtRelative(ts) : '';
  document.getElementById('updated').textContent = fmtCurrentDate() + relative;
}

(async () => {
  try {
    updateDateTime();
    setInterval(updateDateTime, 30000);

    const [stocks, tech, india, global] = await Promise.all([
      loadJSON('data/stocks.json').catch(() => ({ regions: {} })),
      loadJSON('data/news_tech.json').catch(() => ({ items: [] })),
      loadJSON('data/news_india.json').catch(() => ({ items: [] })),
      loadJSON('data/news_global.json').catch(() => ({ items: [] })),
    ]);
    stocksData = stocks;
    newsCache.tech   = tech.items   || [];
    newsCache.india  = india.items  || [];
    newsCache.global = global.items || [];

    showStockRegion('us');
    // Pre-render each section's default (24h) so switching is instant
    ['tech', 'india', 'global'].forEach(s => {
      const prevSection = currentSection, prevWin = currentWindow;
      currentWindow = '24h';
      renderNewsForCurrentWindow(s);
      currentSection = prevSection; currentWindow = prevWin;
    });
    setUpdated(stocks, tech, india, global);

    if (window.innerWidth >= 820) body.classList.add('menu-open');
  } catch (e) {
    document.getElementById('updated').textContent = 'Error loading data.';
    console.error(e);
  }
})();
