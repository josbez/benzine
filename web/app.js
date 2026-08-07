/* Benzineprijs forecaster -- renders web/forecast.json.
 *
 * The chart is deliberately hand-rolled SVG: one series, a fan, and a
 * crosshair is not worth a charting dependency, and inlining it keeps the
 * page self-contained. Shared formatting helpers live in shared.js.
 */

const CHART_DAYS_DEFAULT = 5; // of history to show alongside the 5-day forecast, matches the range select's default

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
      message: 'Deze voorspelling draait op een synthetische reeks, niet op ' +
        'echte marktdata. De cijfers tonen aan dat de pipeline werkt &mdash; ' +
        'ze zeggen niets over de benzineprijs.',
    });
  }

  renderHero(data);
  renderDays(data);
  renderDrivers(data);
  renderSkill(data);
  document.getElementById('footer').textContent =
    'bijgewerkt ' + new Date(data.generated_at).toLocaleString('nl-NL');

  const chart = new FanChart(document.getElementById('chart'), data, CHART_DAYS_DEFAULT);
  chart.draw();
  window.addEventListener('resize', () => chart.draw());

  document.getElementById('chart-range').addEventListener('change', (ev) => {
    chart.historyDays = Number(ev.target.value);
    chart.draw();
  });
}

function showLoadError() {
  document.getElementById('app-grid').hidden = true;
  document.getElementById('footer').textContent = '';
  renderBanner(document.getElementById('banner-slot'), {
    kind: 'error',
    title: 'Kan de voorspelling niet laden.',
    message: 'forecast.json ontbreekt of kon niet worden opgehaald. Draai ' +
      'eerst <code>python -m benzine all</code> en herlaad de pagina.',
    actionLabel: 'Opnieuw proberen',
    onAction: () => window.location.reload(),
  });
}

/* -- panels ----------------------------------------------------------- */

function renderHero(data) {
  const a = data.anchor;
  document.getElementById('hero').textContent = a.price.toFixed(3).replace('.', ',');
  document.getElementById('anchor-label').textContent =
    a.source === 'adviesprijs' ? 'Landelijke adviesprijs' : 'Laatst gemeten prijs';

  const when = a.staleness_days === 0
    ? 'van vandaag'
    : `van ${a.staleness_days} dag${a.staleness_days === 1 ? '' : 'en'} geleden`;
  document.getElementById('anchor-meta').textContent =
    `${a.source} · ${when} (${formatDateDutch(parseDate(a.date))})`;
  document.getElementById('fuel-line').textContent =
    `${data.fuel} · landelijk gemiddelde`;

  const chipEl = document.getElementById('trend-chip');
  if (data.forecast && data.forecast.length) {
    const last = data.forecast[data.forecast.length - 1];
    const move = (last.q50 - a.price) * 100;
    const { className, label } = trendChip(move, { verb: true });
    chipEl.className = 'chip ' + className;
    chipEl.textContent = label;
  } else {
    chipEl.hidden = true;
  }
}

function renderDays(data) {
  const host = document.getElementById('days');
  const base = data.anchor.price;
  host.innerHTML = '';

  if (!data.forecast || !data.forecast.length) {
    renderEmptyState(host, {
      title: 'Geen voorspelling beschikbaar',
      message: 'Er zijn geen dagramingen om te tonen.',
    });
    document.getElementById('days-note').textContent = '';
    return;
  }

  data.forecast.forEach((row, i) => {
    const d = parseDate(row.date);
    const delta = (row.q50 - base) * 100;
    const dir = delta > 0.25 ? 'up' : delta < -0.25 ? 'down' : '';
    const arrow = dir === 'up' ? '↑' : dir === 'down' ? '↓' : '→';
    const isLast = i === data.forecast.length - 1;

    const el = document.createElement('div');
    el.className = 'day' + (isLast ? ' is-highlight' : '');
    el.innerHTML = `
      <div class="dow">${DOW[d.getUTCDay()]} ${d.getUTCDate()}</div>
      <div class="price">${row.q50.toFixed(3).replace('.', ',')}</div>
      <div class="delta">${arrow} ${fmtCents(delta)}</div>
      <div class="spread">${(row.q10).toFixed(2).replace('.', ',')}–${(row.q90).toFixed(2).replace('.', ',')}</div>`;
    host.appendChild(el);
  });

  document.getElementById('days-note').textContent =
    'Middelste waarde is de meest waarschijnlijke prijs; daaronder de band waar ' +
    'de prijs met 80% kans in valt.';
}

function renderDrivers(data) {
  const host = document.getElementById('drivers');
  const a = data.anchor;

  if (!data.forecast || !data.forecast.length) {
    host.innerHTML = '';
    return;
  }

  const last = data.forecast[data.forecast.length - 1];
  const move = (last.q50 - a.price) * 100;

  const items = [
    ['Doorwerking uit Rotterdam',
     'De groothandelsprijs van vandaag bereikt de pomp pas over enkele dagen. ' +
     'Die vertraging is het grootste deel van wat hier voorspeld wordt.'],
    ['Marge loopt terug naar normaal',
     'Ligt de pompmarge boven het gebruikelijke niveau, dan zakt hij meestal ' +
     'terug — en andersom. Dat trekt de prijs richting de kostprijs.'],
    ['Stijgingen gaan sneller dan dalingen',
     'Een hogere inkoopprijs is binnen dagen zichtbaar, een lagere sijpelt ' +
     'er langzamer uit. Het model rekent met beide snelheden apart.'],
  ];

  if (a.staleness_days >= 3) {
    items.unshift(['Meetvertraging',
      `De laatste officiële prijs is ${a.staleness_days} dagen oud. Een deel van ` +
      'de verwachting is dus inhalen wat al gebeurd is, niet vooruitkijken.']);
  }

  const summary = Math.abs(move) < 0.5
    ? 'Er zit weinig beweging in de pijplijn: de prijs blijft naar verwachting vlak.'
    : `Op basis hiervan verwachten we over ${last.horizon} dagen ` +
      `${fmtCents(move)} ten opzichte van nu.`;

  host.innerHTML = items.map(([t, b]) => `
    <li class="driver">
      <span class="dot"></span>
      <div class="driver-body"><strong>${t}</strong><span>${b}</span></div>
    </li>`).join('') +
    `<p class="note">${summary}</p>`;
}

function renderSkill(data) {
  const body = document.querySelector('#skill-table tbody');
  const rows = (data.backtest || []).slice().sort((a, b) => a.horizon - b.horizon);

  if (!rows.length) {
    document.getElementById('skill-table').hidden = true;
    document.getElementById('skill-note').textContent =
      'Nog geen backtest beschikbaar — draai: python -m benzine all';
    return;
  }

  body.innerHTML = rows.map((r) => `
    <tr>
      <td>${r.horizon} dag${r.horizon === 1 ? '' : 'en'}</td>
      <td>${r.mae_cents.toFixed(2)} ct</td>
      <td class="naive">${r.mae_naive_cents.toFixed(2)} ct</td>
      <td>${(r.skill_vs_naive * 100).toFixed(0)}%</td>
    </tr>`).join('');

  document.getElementById('skill-note').textContent =
    'Gemiddelde afwijking bij een test op historische data, vergeleken met de ' +
    'simpelste voorspelling ("de prijs blijft gelijk"). Hoe hoger het percentage, ' +
    'hoe meer het model toevoegt.';
}

/* -- chart ------------------------------------------------------------- */

class FanChart {
  constructor(svg, data, historyDays) {
    this.svg = svg;
    this.data = data;
    this.historyDays = historyDays;
    this.tooltip = document.getElementById('tooltip');
    this.NS = 'http://www.w3.org/2000/svg';
    this.bindPointer();
  }

  draw() {
    const { svg, data } = this;
    if (!data.history || !data.history.length || !data.forecast || !data.forecast.length) {
      svg.innerHTML = '';
      return;
    }

    const width = svg.clientWidth || 360;
    const height = Math.max(200, Math.min(260, width * 0.62));
    const pad = { t: 12, r: 12, b: 22, l: 40 };

    svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    svg.setAttribute('height', height);
    svg.innerHTML = '';

    const history = data.history.slice(-this.historyDays).map((d) => ({
      t: parseDate(d.date).getTime(), v: d.price,
    }));
    const anchorT = parseDate(data.anchor.date).getTime();

    // The fan starts at the anchor so the dashed line joins the solid one.
    const fan = [{
      t: anchorT, q10: data.anchor.price, q25: data.anchor.price,
      q50: data.anchor.price, q75: data.anchor.price, q90: data.anchor.price,
    }].concat(data.forecast.map((r) => ({
      t: parseDate(r.date).getTime(),
      q10: r.q10, q25: r.q25, q50: r.q50, q75: r.q75, q90: r.q90,
    })));

    const xs = history.map((d) => d.t).concat(fan.map((d) => d.t));
    const ys = history.map((d) => d.v)
      .concat(fan.map((d) => d.q10), fan.map((d) => d.q90));

    const x0 = Math.min(...xs), x1 = Math.max(...xs);
    const [y0, y1, ticks] = niceScale(Math.min(...ys), Math.max(...ys));

    const X = (t) => pad.l + ((t - x0) / (x1 - x0 || 1)) * (width - pad.l - pad.r);
    const Y = (v) => height - pad.b - ((v - y0) / (y1 - y0 || 1)) * (height - pad.t - pad.b);
    this.X = X; this.Y = Y; this.geom = { pad, width, height };
    this.points = history.map((d) => ({ ...d, kind: 'past' }))
      .concat(fan.slice(1).map((d) => ({ ...d, v: d.q50, kind: 'future' })));

    // gridlines + y ticks -- drawn inside the viewBox, with room reserved
    // in `pad.l` for the labels, so they never spill past the card edge.
    for (const tick of ticks) {
      this.add('line', {
        x1: pad.l, x2: width - pad.r, y1: Y(tick), y2: Y(tick),
        stroke: 'var(--outline-variant)', 'stroke-width': 1,
      });
      this.add('text', {
        x: pad.l - 7, y: Y(tick) + 3.5, 'text-anchor': 'end',
        fill: 'var(--on-surface-variant)', 'font-size': 10,
        'font-variant-numeric': 'tabular-nums',
      }, tick.toFixed(2).replace('.', ','));
    }

    // uncertainty bands, widest first
    this.add('path', {
      d: band(fan, 'q10', 'q90', X, Y),
      fill: 'var(--primary)', 'fill-opacity': 0.10,
    });
    this.add('path', {
      d: band(fan, 'q25', 'q75', X, Y),
      fill: 'var(--primary)', 'fill-opacity': 0.16,
    });

    // "now" divider
    this.add('line', {
      x1: X(anchorT), x2: X(anchorT), y1: pad.t, y2: height - pad.b,
      stroke: 'var(--outline)', 'stroke-width': 1,
    });

    // measured history
    this.add('path', {
      d: line(history.map((d) => [X(d.t), Y(d.v)])),
      fill: 'none', stroke: 'var(--primary)', 'stroke-width': 2,
      'stroke-linejoin': 'round', 'stroke-linecap': 'round',
    });

    // forecast median
    this.add('path', {
      d: line(fan.map((d) => [X(d.t), Y(d.q50)])),
      fill: 'none', stroke: 'var(--primary)', 'stroke-width': 2,
      'stroke-dasharray': '4 3', 'stroke-linecap': 'round',
    });

    // end marker with a surface ring so it reads over the band
    const last = fan[fan.length - 1];
    this.add('circle', {
      cx: X(last.t), cy: Y(last.q50), r: 4.5,
      fill: 'var(--primary)', stroke: 'var(--surface-container-lowest)', 'stroke-width': 2,
    });

    this.xAxis(history, fan, X, height, pad);
    this.crosshair = this.add('line', {
      y1: pad.t, y2: height - pad.b, stroke: 'var(--outline)',
      'stroke-width': 1, opacity: 0,
    });
  }

  xAxis(history, fan, X, height, pad) {
    const marks = [];
    if (history.length) marks.push(history[0]);
    const mid = history[Math.floor(history.length / 2)];
    if (mid) marks.push(mid);
    marks.push({ t: fan[fan.length - 1].t });

    for (const m of marks) {
      const d = new Date(m.t);
      this.add('text', {
        x: X(m.t), y: height - pad.b + 14, 'text-anchor': 'middle',
        fill: 'var(--on-surface-variant)', 'font-size': 10,
      }, `${d.getUTCDate()}/${d.getUTCMonth() + 1}`);
    }
  }

  bindPointer() {
    const shell = this.svg.parentElement;
    const move = (ev) => {
      if (!this.points || !this.points.length) return;
      const rect = this.svg.getBoundingClientRect();
      const px = (ev.clientX - rect.left) * (this.geom.width / rect.width);

      let best = this.points[0], bestD = Infinity;
      for (const p of this.points) {
        const d = Math.abs(this.X(p.t) - px);
        if (d < bestD) { bestD = d; best = p; }
      }
      this.showTip(best, rect);
    };
    shell.addEventListener('pointermove', move);
    shell.addEventListener('pointerdown', move);
    shell.addEventListener('pointerleave', () => this.hideTip());
  }

  showTip(p, rect) {
    const d = new Date(p.t);
    const label = `${DOW[d.getUTCDay()]} ${d.getUTCDate()}/${d.getUTCMonth() + 1}`;
    const range = p.kind === 'future'
      ? `<div class="tt-range">${fmtPrice(p.q10)} – ${fmtPrice(p.q90)}</div>`
      : '';

    this.tooltip.innerHTML =
      `<div class="tt-date">${label}${p.kind === 'future' ? ' · verwacht' : ''}</div>` +
      `<div class="tt-val">${fmtPrice(p.v)}</div>${range}`;
    this.tooltip.hidden = false;

    const scale = rect.width / this.geom.width;
    const cx = this.X(p.t) * scale;
    const w = this.tooltip.offsetWidth;
    this.tooltip.style.left =
      Math.max(0, Math.min(rect.width - w, cx - w / 2)) + 'px';
    this.tooltip.style.top = Math.max(0, this.Y(p.v) * scale - 62) + 'px';

    this.crosshair.setAttribute('x1', this.X(p.t));
    this.crosshair.setAttribute('x2', this.X(p.t));
    this.crosshair.setAttribute('opacity', 0.6);
  }

  hideTip() {
    this.tooltip.hidden = true;
    if (this.crosshair) this.crosshair.setAttribute('opacity', 0);
  }

  add(tag, attrs, text) {
    const el = document.createElementNS(this.NS, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    if (text !== undefined) el.textContent = text;
    this.svg.appendChild(el);
    return el;
  }
}

function line(pts) {
  return pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' ');
}

function band(rows, lo, hi, X, Y) {
  const top = rows.map((r) => [X(r.t), Y(r[hi])]);
  const bottom = rows.slice().reverse().map((r) => [X(r.t), Y(r[lo])]);
  return line(top) + ' ' + line(bottom).replace('M', 'L') + ' Z';
}

function niceScale(min, max) {
  const pad = (max - min) * 0.15 || 0.02;
  let lo = min - pad, hi = max + pad;
  const step = niceStep((hi - lo) / 4);
  lo = Math.floor(lo / step) * step;
  hi = Math.ceil(hi / step) * step;

  const ticks = [];
  for (let v = lo; v <= hi + step / 2; v += step) ticks.push(Math.round(v * 1e6) / 1e6);
  return [lo, hi, ticks];
}

function niceStep(raw) {
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const step = norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 5 ? 5 : 10;
  return step * mag;
}
