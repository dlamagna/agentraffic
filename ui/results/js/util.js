/**
 * Shared helpers for the results page: data loading, formatting, statistics, DOM/SVG
 * construction, scales and axes, the tooltip, and responsive re-rendering.
 * Everything is plain ES modules with no dependencies (no build step, no CDN).
 */

import { currentTheme } from '../../common/js/theme.js';
import { dataUrl } from '../../common/js/data.js';

// ---------------------------------------------------------------------------
// Data
// ---------------------------------------------------------------------------

let runsPromise = null;

/** Fetches a JSON file of the active data set (ui/data/private/ or ui/data/public/, see common/js/data.js). */
export async function loadData(name) {
  const resp = await fetch(await dataUrl(name));
  if (!resp.ok) {
    resp.body?.cancel(); // an unread body keeps the request open
    const err = new Error(`${name}: HTTP ${resp.status}`);
    err.status = resp.status;
    err.missing = resp.status === 404;
    throw err;
  }
  return resp.json();
}

/** What to show where runs.json could not be loaded (it is absent from a data set without runs). */
export const runsError = (err) => (err && err.missing
  ? 'Individual runs are not available in this data set.'
  : `Could not load runs.json (${err && err.message}).`);

export const loadSummary = () => loadData('summary.json');

/**
 * runs.json (2.3 MB) is fetched once, on first use. Each run gets `m` (metrics by key).
 * The public data set has no runs.json until the synthetic runs are added: the promise then
 * rejects with `err.missing === true` ("runs.json: HTTP 404"); callers show runsError(err).
 */
export function loadRuns() {
  if (!runsPromise) {
    runsPromise = loadData('runs.json')
      .then((data) => {
        const keys = data.metric_keys;
        data.byId = new Map();
        for (const run of data.runs) {
          run.m = {};
          keys.forEach((k, i) => { run.m[k] = run.metrics ? run.metrics[i] : null; });
          data.byId.set(run.id, run);
        }
        return data;
      })
      .catch((err) => { runsPromise = null; throw err; });
  }
  return runsPromise;
}

export const runsLoaded = () => runsPromise !== null;

// ---------------------------------------------------------------------------
// Topologies, tasks, metrics
// ---------------------------------------------------------------------------

export const TOPOS = ['horizontal', 'vertical', 'full_mesh'];
export const TOPO_LABEL = { horizontal: 'Sequential', vertical: 'Star', full_mesh: 'Full mesh' };
/** CSS variables (css/results.css), so marks recolour with the light / dark theme without a redraw. */
export const TOPO_COLOR = { horizontal: 'var(--topo-horizontal)', vertical: 'var(--topo-vertical)', full_mesh: 'var(--topo-full_mesh)' };
export const STAGE_LABEL = {
  recruitment: 'Recruitment',
  discussion: 'Discussion',
  discussion_synthesis: 'Synthesis',
  execution: 'Execution',
  evaluation: 'Evaluation',
  final_output: 'Final output',
};
/** Recorded durations are rounded to 10 ms, so overlaps shorter than this are not real. */
export const OVERLAP_EPS_MS = 10;
export const MAX_PARALLEL_WORKERS = 5;

/**
 * Metrics that carry no information. summary.metrics flags duplicates (`duplicate_of`);
 * a `degenerate` flag is honoured if a later export adds one, otherwise these keys apply:
 * the TCP RTT histogram quantiles are the same value in every run (below the first bucket).
 */
const DEGENERATE_FALLBACK = new Set(['tcp_rtt_p50_mean_s', 'tcp_rtt_p95_mean_s']);

export function metricInfo(summary) {
  const byKey = new Map();
  for (const m of summary.metrics) {
    const degenerate = m.degenerate ?? DEGENERATE_FALLBACK.has(m.key);
    byKey.set(m.key, { ...m, degenerate: Boolean(degenerate), dim: Boolean(degenerate || m.duplicate_of) });
  }
  return byKey;
}

export const swatch = (topo) => h('span', { class: 'swatch', style: `background:${TOPO_COLOR[topo]}`, 'aria-hidden': 'true' });

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

const nf = (digits) => new Intl.NumberFormat('en-US', { maximumFractionDigits: digits, minimumFractionDigits: digits });
const nfCache = new Map();
export function fixed(x, digits = 0) {
  if (!nfCache.has(digits)) nfCache.set(digits, nf(digits));
  return nfCache.get(digits).format(x);
}
export const int = (x) => fixed(Math.round(x), 0);
export const pct = (x, d = 1) => `${fixed(x * 100, d)}%`;

/** Seconds with a unit that suits the magnitude: 0.41 ms, 236 ms, 4.56 s. */
export function seconds(s) {
  if (s == null || Number.isNaN(s)) return '–';
  const a = Math.abs(s);
  if (a === 0) return '0 s';
  if (a < 0.001) return `${fixed(s * 1e3, 2)} ms`;
  if (a < 0.01) return `${fixed(s * 1e3, 2)} ms`;
  if (a < 1) return `${fixed(s * 1e3, 0)} ms`;
  if (a < 10) return `${fixed(s, 2)} s`;
  if (a < 100) return `${fixed(s, 1)} s`;
  return `${fixed(s, 0)} s`;
}

/** Compact number: 1,284 / 12.9k / 4.2M. */
export function compact(x) {
  if (x == null || Number.isNaN(x)) return '–';
  const a = Math.abs(x);
  if (a >= 1e6) return `${fixed(x / 1e6, a >= 1e7 ? 0 : 1)}M`;
  if (a >= 1e4) return `${fixed(x / 1e3, a >= 1e5 ? 0 : 1)}k`;
  if (a >= 100) return int(x);
  if (a >= 10) return fixed(x, 1);
  if (a >= 1) return fixed(x, 2);
  if (a === 0) return '0';
  return x.toPrecision(2);
}

/** A metric value in its unit. */
export function formatMetric(value, unit, key = '') {
  if (value == null || Number.isNaN(value)) return '–';
  switch (unit) {
    case 's': return seconds(value);
    case 'B/s': return value >= 1000 ? `${fixed(value / 1000, 2)} kB/s` : `${int(value)} B/s`;
    case 'tok/s': return `${compact(value)} tok/s`;
    case 'tokens': return compact(value);
    case 'calls': return Number.isInteger(value) && !key.endsWith('_mean') ? int(value) : fixed(value, 2);
    case 'ratio': return fixed(value, 2);
    default: return compact(value);
  }
}

export const ms = (v) => (v >= 1000 ? `${fixed(v / 1000, 2)} s` : `${int(v)} ms`);

// ---------------------------------------------------------------------------
// Statistics
// ---------------------------------------------------------------------------

export function quantile(sorted, q) {
  if (!sorted.length) return NaN;
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

export function median(values) {
  return quantile([...values].sort((a, b) => a - b), 0.5);
}

/** Average ranks (ties share their mean rank), as pandas/scipy. */
function ranks(values) {
  const idx = values.map((v, i) => i).sort((a, b) => values[a] - values[b]);
  const out = new Array(values.length);
  for (let i = 0; i < idx.length;) {
    let j = i;
    while (j + 1 < idx.length && values[idx[j + 1]] === values[idx[i]]) j++;
    const r = (i + j) / 2 + 1;
    for (let k = i; k <= j; k++) out[idx[k]] = r;
    i = j + 1;
  }
  return out;
}

function pearson(a, b) {
  const n = a.length;
  let ma = 0, mb = 0;
  for (let i = 0; i < n; i++) { ma += a[i]; mb += b[i]; }
  ma /= n; mb /= n;
  let sab = 0, saa = 0, sbb = 0;
  for (let i = 0; i < n; i++) {
    const da = a[i] - ma, db = b[i] - mb;
    sab += da * db; saa += da * da; sbb += db * db;
  }
  return saa && sbb ? sab / Math.sqrt(saa * sbb) : null;
}

/** Spearman rho over pairwise-complete (x, y). null if fewer than 3 points or a constant column. */
export function spearman(xs, ys) {
  const a = [], b = [];
  for (let i = 0; i < xs.length; i++) {
    if (xs[i] != null && ys[i] != null && Number.isFinite(xs[i]) && Number.isFinite(ys[i])) {
      a.push(xs[i]); b.push(ys[i]);
    }
  }
  if (a.length < 3) return { rho: null, n: a.length };
  return { rho: pearson(ranks(a), ranks(b)), n: a.length };
}

// ---------------------------------------------------------------------------
// DOM / SVG
// ---------------------------------------------------------------------------

const SVG_NS = 'http://www.w3.org/2000/svg';

function apply(el, attrs, children) {
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'text') el.textContent = v;
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const c of [].concat(children ?? [])) {
    if (c == null || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

/** HTML element. Text children are always inserted as text nodes. */
export const h = (tag, attrs, children) => apply(document.createElement(tag), attrs, children);
/** SVG element. */
export const s = (tag, attrs, children) => apply(document.createElementNS(SVG_NS, tag), attrs, children);

export function svgRoot(width, height, label) {
  return s('svg', {
    class: 'viz',
    width,
    height,
    viewBox: `0 0 ${width} ${height}`,
    role: label ? 'img' : null,
    'aria-label': label || null,
  });
}

// ---------------------------------------------------------------------------
// Scales and axes
// ---------------------------------------------------------------------------

export function linear([d0, d1], [r0, r1]) {
  const k = d1 === d0 ? 0 : (r1 - r0) / (d1 - d0);
  const f = (v) => r0 + (v - d0) * k;
  f.invert = (p) => (k ? d0 + (p - r0) / k : d0);
  f.domain = [d0, d1];
  f.range = [r0, r1];
  f.ticks = (n = 5) => niceTicks(d0, d1, n);
  f.log = false;
  return f;
}

export function log10([d0, d1], [r0, r1]) {
  const l0 = Math.log10(d0), l1 = Math.log10(d1);
  const k = (r1 - r0) / (l1 - l0);
  const f = (v) => r0 + (Math.log10(Math.max(v, 1e-300)) - l0) * k;
  f.invert = (p) => 10 ** (l0 + (p - r0) / k);
  f.domain = [d0, d1];
  f.range = [r0, r1];
  f.ticks = () => {
    const out = [];
    for (let e = Math.ceil(l0 - 1e-9); e <= Math.floor(l1 + 1e-9); e++) out.push(10 ** e);
    return out;
  };
  f.log = true;
  return f;
}

export function niceTicks(lo, hi, n = 5) {
  if (!(hi > lo)) return [lo];
  const span = hi - lo;
  const step0 = span / Math.max(1, n);
  const mag = 10 ** Math.floor(Math.log10(step0));
  const err = step0 / mag;
  const step = (err >= 7.5 ? 10 : err >= 3.5 ? 5 : err >= 1.5 ? 2 : 1) * mag;
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + step * 1e-9; v += step) out.push(Math.abs(v) < step * 1e-9 ? 0 : v);
  return out;
}

export function niceMax(v) {
  if (!(v > 0)) return 1;
  const t = niceTicks(0, v, 4);
  const last = t[t.length - 1];
  return last >= v ? last : last + (t[1] - t[0]);
}

/** Time ticks for a log axis: 1 ms, 10 ms, 100 ms, 1 s, 10 s. */
export function logTimeLabel(v) {
  if (v < 1e-3) return `${+(v * 1e6).toPrecision(2)} µs`;
  if (v < 1) return `${+(v * 1e3).toPrecision(3)} ms`;
  return `${+v.toPrecision(3)} s`;
}

/**
 * Draws a horizontal axis at y (ticks + labels, optional vertical gridlines up to gridTop).
 */
export function axisBottom(g, scale, y, { format = String, ticks, gridTop = null, title = null, titleY = 30 } = {}) {
  const values = ticks || scale.ticks();
  const [r0, r1] = scale.range;
  const axis = s('g', { class: 'tick' });
  for (const v of values) {
    const x = scale(v);
    if (x < Math.min(r0, r1) - 0.5 || x > Math.max(r0, r1) + 0.5) continue;
    if (gridTop != null) axis.append(s('line', { x1: x, x2: x, y1: gridTop, y2: y }));
    axis.append(s('text', { x, y: y + 14, 'text-anchor': 'middle', text: format(v) }));
  }
  g.append(axis, s('line', { class: 'baseline', x1: r0, x2: r1, y1: y, y2: y }));
  if (title) g.append(s('text', { class: 'axis-title', x: (r0 + r1) / 2, y: y + titleY, 'text-anchor': 'middle', text: title }));
}

/** Draws a vertical axis at x with horizontal gridlines to gridRight. */
export function axisLeft(g, scale, x, { format = String, ticks, gridRight = null, title = null } = {}) {
  const values = ticks || scale.ticks();
  const axis = s('g', { class: 'grid' });
  for (const v of values) {
    const y = scale(v);
    if (gridRight != null) axis.append(s('line', { x1: x, x2: gridRight, y1: y, y2: y }));
    axis.append(s('text', { x: x - 6, y: y + 3.5, 'text-anchor': 'end', text: format(v) }));
  }
  g.append(axis);
  if (title) {
    const [r0, r1] = scale.range;
    g.append(s('text', {
      class: 'axis-title',
      transform: `translate(${x - 38},${(r0 + r1) / 2}) rotate(-90)`,
      'text-anchor': 'middle',
      text: title,
    }));
  }
}

/** A rect path with the data end rounded (r px) and the baseline end square. */
export function barPath(x, y, w, hgt, r = 4, orient = 'up') {
  if (w <= 0 || hgt <= 0) return '';
  if (orient === 'right') {
    const rr = Math.min(r, hgt / 2, w);
    return `M${x},${y}H${x + w - rr}Q${x + w},${y} ${x + w},${y + rr}V${y + hgt - rr}Q${x + w},${y + hgt} ${x + w - rr},${y + hgt}H${x}Z`;
  }
  const rr = Math.min(r, w / 2, hgt);
  return `M${x},${y + hgt}V${y + rr}Q${x},${y} ${x + rr},${y}H${x + w - rr}Q${x + w},${y} ${x + w},${y + rr}V${y + hgt}Z`;
}

// ---------------------------------------------------------------------------
// Colour: diverging blue <-> red through a neutral midpoint, mixed in OKLab
// ---------------------------------------------------------------------------

function hexToRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((c) => c / 255);
}
const toLin = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
const fromLin = (c) => (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);
function rgbToOklab([r, g, b]) {
  [r, g, b] = [r, g, b].map(toLin);
  const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
  const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
  const q = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
  return [
    0.2104542553 * l + 0.793617785 * m - 0.0040720468 * q,
    1.9779984951 * l - 2.428592205 * m + 0.4505937099 * q,
    0.0259040371 * l + 0.7827717662 * m - 0.808675766 * q,
  ];
}
function oklabToHex([L, a, b]) {
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const q = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  const rgb = [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * q,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * q,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * q,
  ];
  return `#${rgb.map((c) => Math.round(Math.min(1, Math.max(0, fromLin(c))) * 255).toString(16).padStart(2, '0')).join('')}`;
}
/**
 * Per theme: a neutral gray midpoint and two poles of matched lightness, so |rho| reads the
 * same on both arms. Light: near-white midpoint on the white card, poles OKLCH L ~0.52.
 */
const DIVERGING = {
  light: { neutral: '#f0efec', pos: '#256abf', neg: '#b83232' }, // blue step 500, red L 0.52
  dark: { neutral: '#2f3b4e', pos: '#5598e7', neg: '#e66767' },  // blue step 350, red slot 8 (dark)
};
const divLab = Object.fromEntries(Object.entries(DIVERGING).map(([theme, c]) => [theme, {
  neutral: rgbToOklab(hexToRgb(c.neutral)), pos: rgbToOklab(hexToRgb(c.pos)), neg: rgbToOklab(hexToRgb(c.neg)),
}]));
const divCache = new Map();

/** rho in [-1, 1] -> colour for the current theme; |rho| -> distance from the neutral midpoint. */
export function diverging(rho) {
  const theme = currentTheme();
  const key = Math.round(rho * 100);
  const cacheKey = `${theme}:${key}`;
  if (!divCache.has(cacheKey)) {
    const { neutral, pos, neg } = divLab[theme];
    const t = Math.min(1, Math.abs(key / 100)) ** 0.85;
    const pole = key >= 0 ? pos : neg;
    divCache.set(cacheKey, oklabToHex(neutral.map((c, i) => c + (pole[i] - c) * t)));
  }
  return divCache.get(cacheKey);
}

/** Text colour that clears contrast on a given fill. */
export function inkOn(hex) {
  const [r, g, b] = hexToRgb(hex).map(toLin);
  const lum = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  return lum > 0.22 ? '#0b1222' : '#f1f5f9';
}

// ---------------------------------------------------------------------------
// Tooltip
// ---------------------------------------------------------------------------

let tipEl = null;
const tip = () => (tipEl ||= document.getElementById('tooltip'));

/**
 * Show the tooltip near (x, y) in viewport coordinates. `content` is built with h(), so
 * labels from data are always text nodes.
 */
export function showTip(content, x, y) {
  const el = tip();
  el.replaceChildren(...[].concat(content));
  el.hidden = false;
  const pad = 8;
  const { width, height } = el.getBoundingClientRect();
  let left = x + 14;
  let top = y + 14;
  if (left + width > window.innerWidth - pad) left = Math.max(pad, x - width - 14);
  if (top + height > window.innerHeight - pad) top = Math.max(pad, y - height - 14);
  el.style.left = `${left}px`;
  el.style.top = `${top}px`;
}

/** Show the tooltip next to an element (keyboard focus). */
export function showTipAt(content, element) {
  const r = element.getBoundingClientRect();
  showTip(content, r.right, r.top);
}

export function hideTip() {
  const el = tip();
  if (el) el.hidden = true;
}

export const tipTitle = (text) => h('div', { class: 'tt-title', text });
export const tipRow = (value, label, color = null, dash = null) =>
  h('div', { class: 'tt-row' }, [
    color ? h('span', { class: 'tt-key', style: `border-color:${color};${dash ? `border-top-style:${dash}` : ''}` }) : null,
    h('b', { text: value }),
    h('span', { text: label }),
  ]);
export const tipNote = (text) => h('div', { class: 'tt-note', text });

// ---------------------------------------------------------------------------
// Responsive rendering
// ---------------------------------------------------------------------------

/**
 * Calls render(width) now and whenever the element's width changes (debounced).
 */
export function responsive(el, render) {
  let last = -1;
  let timer = null;
  const run = () => {
    const w = Math.floor(el.clientWidth);
    if (w > 0 && w !== last) {
      last = w;
      render(w);
    }
  };
  const ro = new ResizeObserver(() => {
    clearTimeout(timer);
    timer = setTimeout(run, 80);
  });
  ro.observe(el);
  run();
  return {
    rerender: () => { last = -1; run(); },
    disconnect: () => { clearTimeout(timer); ro.disconnect(); },
  };
}

/** A small table (array of header strings, array of row arrays of cells). */
export function dataTable(head, rows, { caption = null, numeric = [], className = '' } = {}) {
  const table = h('table', { class: `data ${className}`.trim() });
  if (caption) table.append(h('caption', { class: 'visually-hidden', text: caption }));
  table.append(h('thead', {}, h('tr', {}, head.map((t, i) => h('th', { scope: 'col', class: numeric.includes(i) ? 'num' : null }, t)))));
  const body = h('tbody');
  for (const row of rows) {
    body.append(h('tr', {}, row.map((c, i) => (i === 0
      ? h('th', { scope: 'row' }, c)
      : h('td', { class: numeric.includes(i) ? 'num' : null }, c)))));
  }
  table.append(body);
  return table;
}
