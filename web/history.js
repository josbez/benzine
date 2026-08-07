/* Geschiedenis -- built from the same forecast.json as the dashboard.
 * There is no separate "history" data source: `data.history` is the
 * measured daily price series the fan chart already draws from, so this
 * page reuses it instead of inventing a second endpoint.
 */

const PAGE_SIZE = 9;

let allEntries = [];
let visibleCount = PAGE_SIZE;

init();

async function init() {
  let data;
  try {
    const res = await fetch('forecast.json', { cache: 'no-store' });
    if (!res.ok) throw new Error(String(res.status));
    data = await res.json();
  } catch (err) {
    showLoadError();
    return;
  }

  const bannerSlot = document.getElementById('banner-slot');
  if (data.data_source === 'synthetic') {
    renderBanner(bannerSlot, {
      kind: 'info',
      title: 'Demodata.',
      message: 'Deze geschiedenis komt uit een synthetische reeks, niet uit ' +
        'echte marktdata.',
    });
  }

  allEntries = buildEntries(data.history || []);

  if (!allEntries.length) {
    renderEmptyState(document.getElementById('history-grid'), {
      title: 'Nog geen geschiedenis',
      message: 'Er is nog niet genoeg gemeten data om een verloop te tonen.',
    });
    return;
  }

  document.getElementById('search-input').addEventListener('input', render);
  document.getElementById('history-more').addEventListener('click', (ev) => {
    if (ev.target.closest('[data-action="load-more"]')) {
      visibleCount += PAGE_SIZE;
      render();
    }
  });

  render();
}

function buildEntries(history) {
  const ascending = history.slice().sort((a, b) => (a.date < b.date ? -1 : 1));
  const entries = [];

  if (ascending.length === 1) {
    const only = ascending[0];
    entries.push({ date: parseDate(only.date), price: only.price, deltaCents: null });
  }

  for (let i = 1; i < ascending.length; i++) {
    const prev = ascending[i - 1];
    const cur = ascending[i];
    entries.push({
      date: parseDate(cur.date),
      price: cur.price,
      deltaCents: (cur.price - prev.price) * 100,
    });
  }

  return entries.reverse(); // most recent first
}

function render() {
  const query = document.getElementById('search-input').value.trim().toLowerCase();
  const matches = query
    ? allEntries.filter((e) => searchText(e).includes(query))
    : allEntries;

  const grid = document.getElementById('history-grid');
  const moreHost = document.getElementById('history-more');
  const countEl = document.getElementById('history-count');

  if (!matches.length) {
    renderEmptyState(grid, {
      title: `Geen resultaten voor "${escapeHtml(document.getElementById('search-input').value.trim())}"`,
      message: 'Probeer een andere datum, of wis de zoekopdracht.',
    });
    moreHost.innerHTML = '';
    countEl.textContent = '';
    return;
  }

  const shown = query ? matches : matches.slice(0, visibleCount);
  grid.innerHTML = shown.map(entryCard).join('');

  if (!query && matches.length > shown.length) {
    moreHost.innerHTML =
      '<button class="btn btn-outline" data-action="load-more">Meer laden</button>';
  } else {
    moreHost.innerHTML = '';
  }

  countEl.textContent = query
    ? `${matches.length} resulta${matches.length === 1 ? 'at' : 'ten'}`
    : `${shown.length} van ${matches.length} dagen`;
}

function entryCard(entry) {
  const rel = relativeDayLabel(entry.date);
  const abs = formatDateDutch(entry.date);
  const chip = entry.deltaCents === null
    ? { className: 'chip-flat', label: '—' }
    : trendChip(entry.deltaCents);

  return `
    <div class="history-entry">
      <div class="history-entry-head">
        <div>
          <p class="history-entry-rel">${rel}</p>
          <p class="history-entry-date">${abs}</p>
        </div>
        <span class="chip ${chip.className}">${chip.label}</span>
      </div>
      <div class="history-entry-price"><p>${fmtPrice(entry.price)}</p></div>
    </div>`;
}

function searchText(entry) {
  return `${relativeDayLabel(entry.date)} ${formatDateDutch(entry.date)}`.toLowerCase();
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function showLoadError() {
  document.getElementById('history-count').textContent = '';
  renderBanner(document.getElementById('banner-slot'), {
    kind: 'error',
    title: 'Kan de geschiedenis niet laden.',
    message: 'forecast.json ontbreekt of kon niet worden opgehaald. Draai ' +
      'eerst <code>python -m benzine all</code> en herlaad de pagina.',
    actionLabel: 'Opnieuw proberen',
    onAction: () => window.location.reload(),
  });
}
