const fmt = new Intl.NumberFormat('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

async function loadJSON(path) {
  const res = await fetch(path + '?t=' + Date.now());
  if (!res.ok) throw new Error('Failed: ' + path);
  return res.json();
}

function renderStocks(data) {
  const tbody = document.querySelector('#stocks tbody');
  if (!data.stocks || !data.stocks.length) {
    tbody.innerHTML = '<tr><td colspan="5" class="muted">No data available.</td></tr>';
    return;
  }
  tbody.innerHTML = data.stocks.map(s => {
    const cls = s.change >= 0 ? 'up' : 'down';
    const sign = s.change >= 0 ? '+' : '';
    return `<tr>
      <td>${s.name}</td>
      <td class="muted">${s.ticker}</td>
      <td class="num">${fmt.format(s.close)}</td>
      <td class="num ${cls}">${sign}${fmt.format(s.change)}</td>
      <td class="num ${cls}">${sign}${fmt.format(s.changePercent)}%</td>
    </tr>`;
  }).join('');
}

function renderNews(data) {
  const ul = document.querySelector('#news');
  if (!data.items || !data.items.length) {
    ul.innerHTML = '<li class="muted">No recent items.</li>';
    return;
  }
  ul.innerHTML = data.items.map(n => {
    const when = n.published ? new Date(n.published).toLocaleString() : '';
    return `<li>
      <a href="${n.url}" target="_blank" rel="noopener">${n.title}</a>
      <span class="news-meta">${n.source}${when ? ' · ' + when : ''}</span>
    </li>`;
  }).join('');
}

function setUpdated(stocks, news) {
  const ts = stocks?.updated || news?.updated;
  if (!ts) return;
  const d = new Date(ts);
  document.getElementById('updated').textContent =
    'Last updated: ' + d.toLocaleString();
}

(async () => {
  try {
    const [stocks, news] = await Promise.all([
      loadJSON('data/stocks.json').catch(() => ({ stocks: [] })),
      loadJSON('data/news.json').catch(() => ({ items: [] })),
    ]);
    renderStocks(stocks);
    renderNews(news);
    setUpdated(stocks, news);
  } catch (e) {
    document.getElementById('updated').textContent = 'Error loading data.';
    console.error(e);
  }
})();
