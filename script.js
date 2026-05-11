// ── Formatters ────────────────────────────────────────
const fmt = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtInt = new Intl.NumberFormat('en-US');

const CURRENCY_SYM = { USD: '$', INR: '₹', HKD: 'HK$', KRW: '₩', EUR: '€' };
function sym(c) { return CURRENCY_SYM[c] || (c ? c + ' ' : ''); }

function fmtMarketCap(n, currency) {
  if (!n) return '—';
  const s = sym(currency);
  if (n >= 1e12) return s + (n / 1e12).toFixed(2) + 'T';
  if (n >= 1e9)  return s + (n / 1e9).toFixed(2)  + 'B';
  if (n >= 1e6)  return s + (n / 1e6).toFixed(2)  + 'M';
  return s + fmtInt.format(n);
}

function fmtPct(n) {
  if (n === null || n === undefined) return '—';
  const sign = n >= 0 ? '+' : '';
  return sign + n.toFixed(2) + '%';
}

function fmtPrice(n, currency) {
  if (n === null || n === undefined) return '—';
  return sym(currency) + fmt.format(n);
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
  const rows = stocks.map(s => {
    const chgCls = s.change >= 0 ? 'up' : 'down';
    const ytdCls = (s.ytdPercent ?? 0) >= 0 ? 'up' : 'down';
    return `<tr>
      <td><strong>${escapeHtml(s.name)}</strong></td>
      <td class="muted">${escapeHtml(s.ticker)}</td>
      <td class="muted">${escapeHtml(s.sector || '')}</td>
      <td class="num">${fmtPrice(s.price, s.currency)}</td>
      <td class="num ${chgCls}">${fmtPct(s.changePercent)}</td>
      <td class="num">${fmtMarketCap(s.marketCap, s.currency)}</td>
      <td class="num">${s.peRatio ? s.peRatio.toFixed(2) : '—'}</td>
      <td class="num">${fmtPrice(s.high52w, s.currency)} / ${fmtPrice(s.low52w, s.currency)}</td>
      <td class="num ${ytdCls}">${fmtPct(s.ytdPercent)}</td>
      <td class="num">${s.dividendYield !== null && s.dividendYield !== undefined ? s.dividendYield.toFixed(2) + '%' : '—'}</td>
    </tr>`;
  }).join('');
  return `<table>
    <thead><tr>
      <th>Company</th><th>Ticker</th><th>Sector</th>
      <th>Price</th><th>Day %</th><th>Mkt Cap</th>
      <th>P/E</th><th>52w H/L</th><th>YTD %</th><th>Div Yield</th>
    </tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

function renderPrivate(companies) {
  if (!companies || !companies.length) {
    return '<p class="muted">No private-company data yet.</p>';
  }
  return '<div class="private-grid">' + companies.map(c => {
    const newsHtml = (c.news || []).length
      ? '<ul>' + c.news.map(n => `
          <li>
            <a href="${n.url}" target="_blank" rel="noopener">${escapeHtml(n.title)}</a>
            <span class="news-meta">${escapeHtml(n.source)} · ${fmtRelative(n.published)}</span>
          </li>`).join('') + '</ul>'
      : '<p class="muted">No recent news found.</p>';
    return `<div class="private-card">
      <h3>${escapeHtml(c.name)}</h3>
      <div class="tag">${escapeHtml(c.tag || '')}</div>
      ${newsHtml}
    </div>`;
  }).join('') + '</div>';
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
let privateData = null;

function showStockRegion(region) {
  document.querySelectorAll('.subtab').forEach(b => b.classList.toggle('active', b.dataset.region === region));
  const container = document.getElementById('stocks-content');
  if (region === 'private') {
    container.innerHTML = renderPrivate(privateData?.companies || []);
  } else {
    const list = stocksData?.regions?.[region] || [];
    container.innerHTML = renderStocksTable(list);
  }
}

document.querySelectorAll('.subtab').forEach(b => {
  b.addEventListener('click', () => showStockRegion(b.dataset.region));
});

// ── Init ──────────────────────────────────────────────
function setUpdated(...sources) {
  const ts = sources.map(s => s?.updated).filter(Boolean).sort().pop();
  if (!ts) return;
  document.getElementById('updated').textContent = 'Updated ' + fmtRelative(ts);
}

(async () => {
  try {
    const [stocks, priv, tech, india, global] = await Promise.all([
      loadJSON('data/stocks.json').catch(() => ({ regions: {} })),
      loadJSON('data/private.json').catch(() => ({ companies: [] })),
      loadJSON('data/news_tech.json').catch(() => ({ items: [] })),
      loadJSON('data/news_india.json').catch(() => ({ items: [] })),
      loadJSON('data/news_global.json').catch(() => ({ items: [] })),
    ]);
    stocksData = stocks;
    privateData = priv;
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
    setUpdated(stocks, priv, tech, india, global);

    if (window.innerWidth >= 820) body.classList.add('menu-open');
  } catch (e) {
    document.getElementById('updated').textContent = 'Error loading data.';
    console.error(e);
  }
})();
