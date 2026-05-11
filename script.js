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

// ── News rendering ────────────────────────────────────
function renderNews(targetId, items) {
  const container = document.getElementById(targetId);
  if (!items || !items.length) {
    container.innerHTML = '<p class="muted">No recent items.</p>';
    return;
  }
  container.innerHTML = items.map((n, i) => `
    <article class="news-card" data-idx="${i}">
      <div class="news-head">
        <div>
          <div class="news-title">${escapeHtml(n.title)}</div>
          <div class="news-meta-row">${escapeHtml(n.source)} · ${fmtRelative(n.published)}</div>
        </div>
        <span class="chev">▼</span>
      </div>
      <div class="news-body">
        <div>${escapeHtml(n.summary || 'No summary available.')}</div>
        ${n.url ? `<a class="read-more" href="${n.url}" target="_blank" rel="noopener">Read full story →</a>` : ''}
      </div>
    </article>
  `).join('');
  container.querySelectorAll('.news-card').forEach(card => {
    card.querySelector('.news-head').addEventListener('click', () => {
      card.classList.toggle('expanded');
    });
  });
}

// ── Sidebar / hamburger ───────────────────────────────
const body = document.body;
document.getElementById('menuBtn').addEventListener('click', () => {
  body.classList.toggle('menu-open');
});

document.querySelectorAll('.nav-item').forEach(a => {
  a.addEventListener('click', e => {
    e.preventDefault();
    const target = a.dataset.section;
    document.querySelectorAll('.nav-item').forEach(n => n.classList.toggle('active', n === a));
    document.querySelectorAll('.section').forEach(s => {
      s.classList.toggle('active', s.id === 'section-' + target);
    });
    if (window.innerWidth < 820) body.classList.remove('menu-open');
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
    showStockRegion('us');
    renderNews('news-tech',   tech.items);
    renderNews('news-india',  india.items);
    renderNews('news-global', global.items);
    setUpdated(stocks, priv, tech, india, global);

    if (window.innerWidth >= 820) body.classList.add('menu-open');
  } catch (e) {
    document.getElementById('updated').textContent = 'Error loading data.';
    console.error(e);
  }
})();
