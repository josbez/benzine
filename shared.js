/* Shared helpers for both pages -- formatting, dates, banners, empty
 * states. Loaded before app.js / history.js.
 */

const DOW = ['zo', 'ma', 'di', 'wo', 'do', 'vr', 'za'];

const fmtPrice = (v) => '€ ' + v.toFixed(3).replace('.', ',');

function fmtCents(v) {
  const rounded = Math.round(Math.abs(v) * 10) / 10; // avoid a "−0,0 ct" artifact
  const sign = v < 0 && rounded !== 0 ? '−' : '+';
  return sign + rounded.toFixed(1).replace('.', ',') + ' ct';
}

function parseDate(s) {
  const [y, m, d] = s.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

function formatDateDutch(date) {
  const dd = String(date.getUTCDate()).padStart(2, '0');
  const mm = String(date.getUTCMonth() + 1).padStart(2, '0');
  return `${dd}/${mm}/${date.getUTCFullYear()}`;
}

// Days between real today and `date` (positive = in the past), not vs. the
// freshest data point -- staleness is already surfaced elsewhere, this
// should read like a calendar.
function daysFromToday(date) {
  const today = new Date();
  const todayUTC = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
  return Math.round((todayUTC - date.getTime()) / 86400000);
}

function relativeDayLabel(date) {
  const diffDays = daysFromToday(date);
  if (diffDays === 0) return 'Vandaag';
  if (diffDays === 1) return 'Gisteren';
  if (diffDays > 1) return `${diffDays} dagen geleden`;
  if (diffDays === -1) return 'Morgen';
  return `over ${Math.abs(diffDays)} dagen`;
}

function trendChip(deltaCents, { verb = false } = {}) {
  const dir = deltaCents > 0.05 ? 'up' : deltaCents < -0.05 ? 'down' : 'flat';
  const arrow = dir === 'up' ? '↑' : dir === 'down' ? '↓' : '→';
  const label = verb
    ? (dir === 'up' ? 'Verwacht: stijgt' : dir === 'down' ? 'Verwacht: daalt' : 'Verwacht: stabiel')
    : `${arrow} ${fmtCents(deltaCents)}`;
  return { dir, className: `chip-${dir}`, label };
}

function renderBanner(host, { kind = 'info', title, message, actionLabel, onAction } = {}) {
  const el = document.createElement('div');
  el.className = `banner banner-${kind}`;
  el.innerHTML = `<div>${title ? `<strong>${title}</strong> ` : ''}${message || ''}</div>`;
  if (actionLabel && onAction) {
    const actions = document.createElement('div');
    actions.className = 'banner-actions';
    const btn = document.createElement('button');
    btn.className = 'btn btn-outline';
    btn.textContent = actionLabel;
    btn.addEventListener('click', onAction);
    actions.appendChild(btn);
    el.querySelector('div').appendChild(actions);
  }
  host.appendChild(el);
  return el;
}

function renderEmptyState(host, { title, message } = {}) {
  host.innerHTML = `
    <div class="empty-state">
      <p class="empty-title">${title || 'Niets te zien hier'}</p>
      ${message ? `<p>${message}</p>` : ''}
    </div>`;
}

const ICON_CHART =
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20V10"/><path d="M11 20V4"/><path d="M18 20v-7"/></svg>';

const ICON_CLOCK =
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 3"/></svg>';

const ICON_SEARCH =
  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>';

for (const [id, svg] of [
  ['nav-icon-forecast', ICON_CHART],
  ['nav-icon-history', ICON_CLOCK],
  ['search-icon', ICON_SEARCH],
]) {
  const host = document.getElementById(id);
  if (host) host.innerHTML = svg;
}
