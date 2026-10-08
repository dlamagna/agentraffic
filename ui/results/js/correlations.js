/**
 * Correlation explorer: Spearman heatmap of every per-run metric (summary.correlations),
 * grouped by layer, for all runs or one topology. A cell (or the two selects) picks a pair;
 * its scatter is drawn from runs.json (lazy), coloured by topology, with rho overall and per
 * topology for the runs the filter bar selects (topologies, task; shell.js). Clicking a point
 * opens that run on the Runs page.
 */

import {
  h, s, svgRoot, linear, log10, axisBottom, axisLeft, niceTicks, responsive, showTip, hideTip,
  tipTitle, tipRow, tipNote, diverging, inkOn, metricInfo, loadRuns, runsError, spearman, formatMetric,
  TOPOS, TOPO_LABEL, TOPO_COLOR, swatch, fixed, int, compact, logTimeLabel, dataTable,
} from './util.js';
import { getFilter, onFilterChange, resultsHref } from './shell.js';
import { onThemeChange } from '../../common/js/theme.js';

const GROUPS = [['all', 'All runs'], ...TOPOS.map((t) => [t, TOPO_LABEL[t]])];
const LAYER_LABEL = { application: 'Application', llm: 'LLM backend', traffic: 'Traffic', network: 'Network' };

const state = {
  group: 'all',
  x: null, // column metric
  y: null, // row metric
  filter: getFilter(), // topologies + task of the filter bar (scatter only)
  focus: [0, 0], // keyboard cursor [row, col] in display order
  plotted: false,
};

let summary;
let info;
let order;       // metric keys in display order (grouped by layer), without duplicate / constant metrics
let idx;         // key -> index in summary.correlations.metric_keys
let paperPairs;  // Set of "a|b"
let paperKeys;   // Set of keys in the paper's heatmap
let heat;        // responsive handle
let scatter;     // responsive handle
let live;        // aria-live region
let keyboardNav = false; // refocus the redrawn heatmap only after keyboard use

const pairKey = (a, b) => `${a}|${b}`;
const rhoOf = (group, a, b) => summary.correlations.groups[group].rho[idx.get(a)][idx.get(b)];

export function renderCorrelations(sum) {
  summary = sum;
  info = metricInfo(summary);
  const keys = summary.correlations.metric_keys;
  idx = new Map(keys.map((k, i) => [k, i]));
  // duplicate and constant metrics carry no information of their own: they stay out of the matrix and the lists
  order = summary.layers.flatMap((layer) => keys.filter((k) => info.get(k).layer === layer && !info.get(k).dim));
  paperPairs = new Set(summary.correlations.selected.flatMap((p) => [pairKey(p.x, p.y), pairKey(p.y, p.x)]));
  paperKeys = new Set(summary.correlations.paper_heatmap.map((p) => p.key));
  const first = summary.correlations.selected[0];
  state.x = first.x;
  state.y = first.y;

  // group toggle
  const seg = document.getElementById('corrGroup');
  seg.replaceChildren(...GROUPS.map(([key, label]) => {
    const b = h('button', { type: 'button', role: 'radio', 'aria-checked': String(key === state.group), 'data-group': key },
      [key !== 'all' ? swatch(key) : null, label]);
    b.addEventListener('click', () => setGroup(key));
    return b;
  }));
  seg.addEventListener('keydown', (ev) => {
    if (!['ArrowLeft', 'ArrowRight'].includes(ev.key)) return;
    const i = GROUPS.findIndex(([k]) => k === state.group);
    const j = (i + (ev.key === 'ArrowRight' ? 1 : GROUPS.length - 1)) % GROUPS.length;
    setGroup(GROUPS[j][0]);
    seg.querySelector(`[data-group="${GROUPS[j][0]}"]`).focus();
    ev.preventDefault();
  });

  // selects
  const xs = document.getElementById('corrX');
  const ys = document.getElementById('corrY');
  for (const sel of [xs, ys]) {
    for (const layer of summary.layers) {
      const og = h('optgroup', { label: LAYER_LABEL[layer] || layer });
      for (const k of order.filter((key) => info.get(key).layer === layer)) {
        const m = info.get(k);
        og.append(h('option', { value: k, text: m.label }));
      }
      sel.append(og);
    }
  }
  xs.value = state.x;
  ys.value = state.y;
  xs.addEventListener('change', () => selectPair(xs.value, state.y));
  ys.addEventListener('change', () => selectPair(state.x, ys.value));
  onFilterChange((f) => {
    state.filter = f;
    if (state.plotted) drawScatterNow(); else updateRhoList();
  });

  live = h('p', { class: 'visually-hidden', 'aria-live': 'polite' });
  document.getElementById('corrHeatmap').after(live);

  const host = document.getElementById('corrHeatmap');
  heat = responsive(host, (w) => drawHeatmap(host, w));
  renderScaleLegend();
  // the cell colours are computed per theme (diverging()); everything else follows CSS variables
  onThemeChange(() => { heat.rerender(); renderScaleLegend(); });
  renderGreyed();
  document.getElementById('corrSource').textContent = sourceText();

  const sc = document.getElementById('corrScatter');
  sc.replaceChildren(
    h('p', { class: 'placeholder', text: 'Select a cell, or two metrics above, to plot the runs behind a correlation.' }),
    h('button', { type: 'button', class: 'btn btn--small', id: 'corrPlotBtn', text: `Plot ${info.get(state.x).label} vs ${info.get(state.y).label}` }),
  );
  document.getElementById('corrPlotBtn').addEventListener('click', () => selectPair(state.x, state.y));
  updateRhoList();
}

function sourceText() {
  const g = summary.correlations.groups[state.group];
  return '';
}

function setGroup(group) {
  state.group = group;
  document.querySelectorAll('#corrGroup button').forEach((b) => b.setAttribute('aria-checked', String(b.dataset.group === group)));
  heat.rerender();
  document.getElementById('corrSource').textContent = sourceText();
  updateRhoList();
}

export function selectPair(x, y) {
  state.x = x;
  state.y = y;
  document.getElementById('corrX').value = x;
  document.getElementById('corrY').value = y;
  heat.rerender();
  updateRhoList();
  drawScatterNow();
}

// ---------------------------------------------------------------------------
// Heatmap
// ---------------------------------------------------------------------------

function fitLabel(text, maxChars) {
  return text.length > maxChars ? `${text.slice(0, maxChars - 1).trimEnd()}…` : text;
}

function markerFor(m) {
  if (m.duplicate_of) return ' =';
  if (m.degenerate) return ' ∅';
  return '';
}

function drawHeatmap(host, width) {
  const n = order.length;
  const narrow = width < 560;
  const labelW = narrow ? 140 : 166;
  const maxChars = Math.floor((labelW - 30) / 5.4);
  const cell = Math.max(narrow ? 13 : 12, Math.min(22, Math.floor((width - labelW - 8) / n)));
  const topH = narrow ? 120 : 142;
  const W = labelW + cell * n + 8;
  const H = topH + cell * n + 6;
  host.style.overflowX = W > width ? 'auto' : '';
  document.getElementById('corrHint').hidden = W <= width;
  const svg = svgRoot(W, H, null);
  svg.style.width = `${W}px`;
  svg.style.height = `${H}px`;
  svg.setAttribute('tabindex', '0');
  svg.setAttribute('role', 'application');
  svg.setAttribute('aria-roledescription', 'correlation heatmap');
  svg.setAttribute('aria-label', `Spearman correlation heatmap, ${n} by ${n} metrics. Arrow keys move, Enter plots the pair.`);
  const ox = labelW;
  const oy = topH;
  const group = state.group;

  // hatch for greyed-out (duplicate / constant) metrics; used via --cell-dim on light
  svg.append(s('defs', {}, s('pattern', { id: 'corrDimHatch', width: 4, height: 4, patternUnits: 'userSpaceOnUse', patternTransform: 'rotate(45)' }, [
    s('rect', { class: 'hatch-bg', width: 4, height: 4 }),
    s('line', { class: 'hatch-line', x1: 0, y1: 0, x2: 0, y2: 4 }),
  ])));

  // cells
  const cells = s('g');
  for (let r = 0; r < n; r++) {
    for (let c = 0; c < n; c++) {
      const a = order[r];
      const b = order[c];
      const dim = info.get(a).dim || info.get(b).dim;
      const rho = rhoOf(group, a, b);
      const attrs = { class: `cell${dim ? ' cell-dim' : ''}`, x: ox + c * cell, y: oy + r * cell, width: cell - 1, height: cell - 1 };
      if (!dim && rho != null) attrs.fill = r === c ? 'var(--cell-diag)' : diverging(rho);
      if (!dim && rho == null) attrs.fill = 'var(--cell-null)';
      cells.append(s('rect', attrs));
    }
  }
  svg.append(cells);

  // values in the selected row when cells are big enough
  if (cell >= 20) {
    const r = order.indexOf(state.y);
    const vals = s('g', { 'aria-hidden': 'true' });
    for (let c = 0; c < n; c++) {
      const b = order[c];
      if (info.get(b).dim || info.get(state.y).dim || c === r) continue;
      const rho = rhoOf(group, state.y, b);
      if (rho == null) continue;
      vals.append(s('text', {
        x: ox + c * cell + (cell - 1) / 2, y: oy + r * cell + cell / 2 + 3, 'text-anchor': 'middle',
        style: `font-size:8.5px;fill:${inkOn(diverging(rho))}`, text: fixed(rho, 1).replace('0.', '.'),
      }));
    }
    svg.append(vals);
  }

  // layer separators + labels
  let start = 0;
  for (const layer of summary.layers) {
    const count = order.filter((k) => info.get(k).layer === layer).length;
    if (start > 0) {
      const p = start * cell - 1;
      svg.append(s('line', { class: 'layer-sep', x1: ox + p + 0.5, x2: ox + p + 0.5, y1: oy - 4, y2: oy + n * cell }));
      svg.append(s('line', { class: 'layer-sep', x1: ox - 4, x2: ox + n * cell, y1: oy + p + 0.5, y2: oy + p + 0.5 }));
    }
    start += count;
  }

  // row labels
  const labelsG = s('g');
  order.forEach((k, r) => {
    const m = info.get(k);
    const labelClass = `row-label${m.dim ? ' dim' : ''}${paperKeys.has(k) ? ' paper' : ''}`;
    labelsG.append(s('text', {
      class: labelClass,
      x: ox - 6, y: oy + r * cell + cell / 2 + 3.5, 'text-anchor': 'end',
      text: `${fitLabel(m.label, maxChars - markerFor(m).length)}${markerFor(m)}`,
    }));
    labelsG.append(s('text', {
      class: labelClass,
      transform: `translate(${ox + r * cell + cell / 2 + 3},${oy - 6}) rotate(-60)`,
      text: `${fitLabel(m.label, 24)}${markerFor(m)}`,
    }));
  });
  svg.append(labelsG);

  // layer captions on the left gutter (vertical bars)
  start = 0;
  for (const layer of summary.layers) {
    const count = order.filter((k) => info.get(k).layer === layer).length;
    const y0 = oy + start * cell;
    svg.append(s('rect', { x: 2, y: y0, width: 3, height: count * cell - 2, rx: 1.5, fill: 'var(--layer-bar)' }));
    svg.append(s('text', {
      class: 'layer-label', transform: `translate(14,${y0 + 2}) rotate(90)`, 'text-anchor': 'start',
      style: 'font-size:9px', text: count * cell > 60 ? (LAYER_LABEL[layer] || layer) : '',
    }));
    start += count;
  }

  // paper-selected rings
  const rings = s('g');
  for (let r = 0; r < n; r++) {
    for (let c = 0; c < n; c++) {
      if (paperPairs.has(pairKey(order[r], order[c]))) {
        rings.append(s('rect', { class: 'cell-paper', x: ox + c * cell + 0.5, y: oy + r * cell + 0.5, width: cell - 2, height: cell - 2, rx: 2 }));
      }
    }
  }
  svg.append(rings);

  // selection + keyboard focus
  const sr = order.indexOf(state.y);
  const sc = order.indexOf(state.x);
  if (sr >= 0 && sc >= 0) {
    svg.append(s('rect', { class: 'cell-sel', x: ox + sc * cell - 1, y: oy + sr * cell - 1, width: cell + 1, height: cell + 1, rx: 2 }));
  }
  const focusRect = s('rect', { class: 'cell-focus', width: cell + 1, height: cell + 1, rx: 2, display: 'none' });
  svg.append(focusRect);

  // interaction layer
  const overlay = s('rect', { class: 'hit', x: ox, y: oy, width: n * cell, height: n * cell });
  svg.append(overlay);
  const cellAt = (ev) => {
    const pt = svg.getBoundingClientRect();
    const c = Math.floor((ev.clientX - pt.left - ox) / cell);
    const r = Math.floor((ev.clientY - pt.top - oy) / cell);
    return r >= 0 && r < n && c >= 0 && c < n ? [r, c] : null;
  };
  const tipFor = (r, c) => {
    const a = order[r];
    const b = order[c];
    const ma = info.get(a);
    const mb = info.get(b);
    const rho = rhoOf(group, a, b);
    const rows = [tipTitle(`${ma.label} × ${mb.label}`)];
    rows.push(tipRow(rho == null ? 'n/a' : `ρ = ${fixed(rho, 2)}`, `${group === 'all' ? 'all runs' : TOPO_LABEL[group]}, n = ${int(summary.correlations.groups[group].n)}`));
    if (paperPairs.has(pairKey(a, b))) rows.push(tipNote('Reported in the paper'));
    for (const m of [ma, mb]) {
      if (m.duplicate_of) rows.push(tipNote(`${m.label} duplicates ${info.get(m.duplicate_of).label}`));
      else if (m.degenerate) rows.push(tipNote(`${m.label} is constant in every run: ρ is noise`));
    }
    rows.push(tipNote('Click to plot the runs'));
    return rows;
  };
  overlay.addEventListener('pointermove', (ev) => {
    const rc = cellAt(ev);
    if (!rc) { hideTip(); return; }
    showTip(tipFor(...rc), ev.clientX, ev.clientY);
  });
  overlay.addEventListener('pointerleave', hideTip);
  overlay.addEventListener('click', (ev) => {
    const rc = cellAt(ev);
    if (!rc) return;
    state.focus = rc;
    selectPair(order[rc[1]], order[rc[0]]);
  });

  const placeFocus = () => {
    const [r, c] = state.focus;
    focusRect.setAttribute('x', ox + c * cell - 1);
    focusRect.setAttribute('y', oy + r * cell - 1);
    focusRect.removeAttribute('display');
    const rho = rhoOf(group, order[r], order[c]);
    live.textContent = `${info.get(order[r]).label} by ${info.get(order[c]).label}: rho ${rho == null ? 'not available' : fixed(rho, 2)}` +
      `${paperPairs.has(pairKey(order[r], order[c])) ? ', reported in the paper' : ''}`;
  };
  svg.addEventListener('focus', () => {
    if (sr >= 0 && sc >= 0 && state.focus[0] === 0 && state.focus[1] === 0) state.focus = [sr, sc];
    placeFocus();
  });
  svg.addEventListener('blur', () => focusRect.setAttribute('display', 'none'));
  svg.addEventListener('keydown', (ev) => {
    const d = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] }[ev.key];
    if (d) {
      state.focus = [Math.min(n - 1, Math.max(0, state.focus[0] + d[0])), Math.min(n - 1, Math.max(0, state.focus[1] + d[1]))];
      placeFocus();
      ev.preventDefault();
    } else if (ev.key === 'Enter' || ev.key === ' ') {
      const [r, c] = state.focus;
      ev.preventDefault();
      keyboardNav = true;
      selectPair(order[c], order[r]);
      keyboardNav = false;
    }
  });
  const hadFocus = keyboardNav && host.contains(document.activeElement);
  host.replaceChildren(svg);
  if (hadFocus) svg.focus();
}

function renderScaleLegend() {
  const stops = [];
  for (let v = -1; v <= 1.0001; v += 0.25) stops.push(`${diverging(v)} ${((v + 1) / 2) * 100}%`);
  document.getElementById('corrScale').replaceChildren(
    h('span', { text: 'ρ −1' }),
    h('span', { class: 'ramp', style: `background:linear-gradient(90deg, ${stops.join(', ')})`, 'aria-hidden': 'true' }),
    h('span', { text: '+1' }),
    h('span', { class: 'paper-key', 'aria-hidden': 'true' }), h('span', { text: 'reported in the paper' }),
    h('span', {}, [h('b', { text: 'Bold', style: 'color:var(--ink-1)' }), ' label: in the paper’s heatmap']),
  );
}

function renderGreyed() {
  const items = [];
  for (const k of summary.correlations.metric_keys) {
    const m = info.get(k);
    if (m.duplicate_of) {
      items.push(h('li', {}, [h('strong', { text: `${m.label} (=)` }), ` is the same series as ${info.get(m.duplicate_of).label}: `, m.description]));
    } else if (m.degenerate) {
      items.push(h('li', {}, [h('strong', { text: `${m.label} (∅)` }), ' is constant: ', m.description, ' Its non-zero ρ values come from floating-point noise.']));
    }
  }
  document.getElementById('corrGreyedBody').replaceChildren(
    h('p', { text: 'These metrics are in the paper’s per-run metrics file but are left out of the matrix, because their cells carry no information of their own:' }),
    h('ul', {}, items),
  );
}

// ---------------------------------------------------------------------------
// Scatter
// ---------------------------------------------------------------------------

function updateRhoList(computed = null) {
  const host = document.getElementById('corrRhos');
  const mx = info.get(state.x);
  const my = info.get(state.y);
  const parts = [];
  if (computed) {
    parts.push(h('span', {}, ['All: ', h('b', { text: computed.all.rho == null ? 'n/a' : fixed(computed.all.rho, 2) }), ` (n = ${int(computed.all.n)})`]));
    for (const t of TOPOS.filter((k) => state.filter.topos.has(k))) {
      const r = computed[t];
      parts.push(h('span', {}, [swatch(t), `${TOPO_LABEL[t]}: `, h('b', { text: r.rho == null ? 'n/a' : fixed(r.rho, 2) }), ` (${int(r.n)})`]));
    }
  } else {
    const all = rhoOf('all', state.x, state.y);
    parts.push(h('span', {}, ['All: ', h('b', { text: all == null ? 'n/a' : fixed(all, 2) })]));
    for (const t of TOPOS) {
      const r = rhoOf(t, state.x, state.y);
      parts.push(h('span', {}, [swatch(t), `${TOPO_LABEL[t]}: `, h('b', { text: r == null ? 'n/a' : fixed(r, 2) })]));
    }
  }
  const lead = h('span', { class: 'rho-lead' }, `Spearman ρ, ${my.label} vs ${mx.label}${computed ? filterNote() : ''}:`);
  host.replaceChildren(lead, ...parts);
  if (mx.dim || my.dim) host.append(h('span', { class: 'rho-warn', text: 'One of these metrics is a duplicate or constant; see the note below the heatmap.' }));
}

/** " (Star, Full mesh; Math)" for the filter bar's selection, '' when it selects everything. */
function filterNote() {
  const { topos, task } = state.filter;
  const parts = [];
  if (topos.size < TOPOS.length) parts.push(TOPOS.filter((t) => topos.has(t)).map((t) => TOPO_LABEL[t]).join(', '));
  if (task) parts.push(summary.tasks.find((t) => t.key === task)?.label || task);
  return parts.length ? ` (${parts.join('; ')})` : '';
}

/** Opens a run on the Runs page (with the filter query). */
function openRun(id) {
  window.location.href = resultsHref('runs', `#run=${id}`);
}

async function drawScatterNow() {
  const host = document.getElementById('corrScatter');
  state.plotted = true;
  if (!host.querySelector('svg')) host.replaceChildren(h('p', { class: 'loading', text: 'Loading runs (2.3 MB)…' }));
  let data;
  try {
    data = await loadRuns();
  } catch (err) {
    host.replaceChildren(h('p', { class: 'placeholder', text: runsError(err) }));
    return;
  }
  const xk = state.x;
  const yk = state.y;
  const { topos, task } = state.filter;
  const pts = data.runs.filter((r) => topos.has(r.topology) && (!task || r.task === task) && r.m[xk] != null && r.m[yk] != null);
  const computed = { all: spearman(pts.map((r) => r.m[xk]), pts.map((r) => r.m[yk])) };
  for (const t of TOPOS) {
    const sub = pts.filter((r) => r.topology === t);
    computed[t] = spearman(sub.map((r) => r.m[xk]), sub.map((r) => r.m[yk]));
  }
  updateRhoList(computed);
  const mx = info.get(xk);
  const my = info.get(yk);
  document.getElementById('corrScatterSource').textContent =
    'One dot per run; click a dot to open it in the Run explorer.';
  if (scatter) scatter.disconnect();
  const legend = h('div', { class: 'legend' }, TOPOS.filter((t) => topos.has(t)).map((t) => h('span', {}, [swatch(t), TOPO_LABEL[t]])));
  if (!pts.length) {
    host.replaceChildren(h('p', { class: 'placeholder', text: 'No runs match the filter.' }));
    return;
  }
  const chart = h('div', { class: 'chart-body' });
  host.replaceChildren(legend, chart);
  scatter = responsive(chart, (w) => drawScatter(chart, w, pts, mx, my));
}

function scaleFor(values, range, unit) {
  const pos = values.filter((v) => v > 0);
  let lo = Math.min(...values);
  let hi = Math.max(...values);
  if (pos.length === values.length && lo > 0 && hi / lo > 40) {
    const sc = log10([10 ** Math.floor(Math.log10(lo)), 10 ** Math.ceil(Math.log10(hi))], range);
    return sc;
  }
  if (lo === hi) { lo -= 1; hi += 1; }
  const pad = (hi - lo) * 0.04;
  const t = niceTicks(lo - pad, hi + pad, 5);
  const sc = linear([Math.min(lo - pad, t[0]), Math.max(hi + pad, t[t.length - 1])], range);
  sc.unit = unit;
  return sc;
}

function drawScatter(host, width, pts, mx, my) {
  const H = Math.min(380, Math.max(260, width * 0.75));
  const M = { top: 10, right: 12, bottom: 42, left: 56 };
  const svg = svgRoot(width, H, `Scatter of ${my.label} against ${mx.label}, ${pts.length} runs coloured by topology. Left and right arrow keys step through the runs, Enter opens one.`);
  svg.setAttribute('tabindex', '0');
  const x = scaleFor(pts.map((r) => r.m[mx.key]), [M.left, width - M.right], mx.unit);
  const y = scaleFor(pts.map((r) => r.m[my.key]), [H - M.bottom, M.top], my.unit);
  const g = s('g');
  svg.append(g);
  const fmt = (unit) => (v) => (unit === 's' ? logTimeLabel(v) : compact(v));
  axisLeft(g, y, M.left, { format: fmt(my.unit), ticks: y.log ? y.ticks() : y.ticks(5), gridRight: width - M.right });
  axisBottom(g, x, H - M.bottom, {
    format: fmt(mx.unit), ticks: x.log ? x.ticks() : x.ticks(width < 400 ? 4 : 6), gridTop: M.top,
    title: `${mx.label}${mx.unit && mx.unit !== 'ratio' ? ` (${mx.unit})` : ''}${x.log ? ', log' : ''}`, titleY: 32,
  });
  svg.append(s('text', {
    class: 'axis-title', transform: `translate(12,${(H - M.bottom + M.top) / 2}) rotate(-90)`, 'text-anchor': 'middle',
    text: `${my.label}${my.unit && my.unit !== 'ratio' ? ` (${my.unit})` : ''}${y.log ? ', log' : ''}`,
  }));

  // draw in topology order with a surface ring; deterministic shuffle so no topology always sits on top
  const order = pts.map((r, i) => i).sort((a, b) => ((a * 2654435761) % 1481) - ((b * 2654435761) % 1481));
  const dots = s('g');
  const xy = new Array(pts.length);
  for (const i of order) {
    const r = pts[i];
    const cx = x(r.m[mx.key]);
    const cy = y(r.m[my.key]);
    xy[i] = [cx, cy];
    dots.append(s('circle', { cx: cx.toFixed(1), cy: cy.toFixed(1), r: 3.5, fill: TOPO_COLOR[r.topology], stroke: 'var(--mark-ring)', 'stroke-width': 1, 'fill-opacity': 0.85 }));
  }
  g.append(dots);
  const hi = s('circle', { r: 6, fill: 'none', stroke: 'var(--hi-ring)', 'stroke-width': 2, display: 'none', 'pointer-events': 'none' });
  g.append(hi);

  const nearest = (px, py) => {
    let best = -1;
    let bd = 24 * 24;
    for (let i = 0; i < xy.length; i++) {
      const dx = xy[i][0] - px;
      const dy = xy[i][1] - py;
      const d = dx * dx + dy * dy;
      if (d < bd) { bd = d; best = i; }
    }
    return best;
  };
  const tipFor = (i) => {
    const r = pts[i];
    return [
      tipTitle(`Run ${r.id}`),
      tipRow(formatMetric(r.m[mx.key], mx.unit), mx.label),
      tipRow(formatMetric(r.m[my.key], my.unit), my.label),
      tipRow(TOPO_LABEL[r.topology], summary.tasks.find((t) => t.key === r.task).label, TOPO_COLOR[r.topology]),
      tipNote(r.fixture ? 'Demo run · click to open' : 'Click to open the run'),
    ];
  };
  let current = -1;
  const highlight = (i, ev) => {
    current = i;
    if (i < 0) { hi.setAttribute('display', 'none'); hideTip(); return; }
    hi.setAttribute('cx', xy[i][0]);
    hi.setAttribute('cy', xy[i][1]);
    hi.removeAttribute('display');
    if (ev) showTip(tipFor(i), ev.clientX, ev.clientY);
    else {
      const b = svg.getBoundingClientRect();
      showTip(tipFor(i), b.left + xy[i][0], b.top + xy[i][1]);
    }
  };
  const local = (ev) => {
    const b = svg.getBoundingClientRect();
    return [ev.clientX - b.left, ev.clientY - b.top];
  };
  svg.addEventListener('pointermove', (ev) => highlight(nearest(...local(ev)), ev));
  svg.addEventListener('pointerleave', () => highlight(-1));
  svg.addEventListener('click', (ev) => {
    const i = nearest(...local(ev));
    if (i >= 0) openRun(pts[i].id);
  });
  const byX = pts.map((r, i) => i).sort((a, b) => xy[a][0] - xy[b][0]);
  svg.addEventListener('keydown', (ev) => {
    if (ev.key === 'ArrowRight' || ev.key === 'ArrowLeft') {
      const pos = current < 0 ? -1 : byX.indexOf(current);
      const next = ev.key === 'ArrowRight' ? Math.min(byX.length - 1, pos + 1) : Math.max(0, pos - 1);
      highlight(byX[next]);
      ev.preventDefault();
    } else if ((ev.key === 'Enter' || ev.key === ' ') && current >= 0) {
      ev.preventDefault();
      openRun(pts[current].id);
    }
  });
  svg.addEventListener('blur', () => highlight(-1));
  host.replaceChildren(svg);
}

