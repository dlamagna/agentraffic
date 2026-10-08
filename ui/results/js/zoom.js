/**
 * Range selection and zoom for the distribution charts (Traffic page).
 *
 * The charts show distributions, not timelines, so the "range" is a range on the chart's x
 * axis: a span of inter-arrival time ('iat', in seconds) or a span of burst sizes ('size', in
 * calls). A range belongs to an axis, not to a chart: every chart that shares the axis redraws
 * when it changes (all IAT histograms and the burst-removed gap charts share 'iat').
 *
 *   getRange(axis) / setRange(axis, [lo, hi] | null) / onRange(axis, fn)   shared state
 *   effectiveDomain(axis, full)    the chart's x domain: the range clipped to the chart's own
 *   attachBrush(svg, opts)         drag / keyboard / double-click on one chart's SVG
 *   zoomBar(el, opts)              Select range + Reset zoom buttons, range text, per-topology readout
 *   logTicks(domain, width)        decade, 1-2-5 or 1-9 ticks for a zoomed log axis
 *
 * The range lives in the URL hash as `#<anchor>&zoom=0.05,5&sizes=2,4`: the first token without
 * `=` stays the section anchor (the browser cannot scroll to it any more, so scrollToAnchor()
 * does), other tokens (e.g. `run=`) are kept. The query (?topo=, ?task=, ?demo=) is never touched.
 */

import { h, s, hideTip, niceTicks, TOPO_LABEL, swatch } from './util.js';

// the styles ship with the module, so pages need no extra <link>
if (typeof document !== 'undefined' && !document.querySelector('link[data-zoom-css]')) {
  document.head.append(h('link', { rel: 'stylesheet', href: new URL('../css/zoom.css', import.meta.url).href, 'data-zoom-css': '' }));
}

const AXES = {
  iat: { param: 'zoom', index: false, range: null, subs: [] },
  size: { param: 'sizes', index: true, range: null, subs: [] },
  time: { param: 'tzoom', index: false, range: null, subs: [] }, // run drill-down: ms since the first call
};

let selectMode = false; // touch: drags select instead of scrolling the page
let pendingFocus = null; // chart id to refocus after a keyboard change redrew the charts
const focusTargets = new Map();
const bars = [];
/** Update the control bars still on the page; forget the ones a redraw removed. */
function refreshBars() {
  for (let i = bars.length - 1; i >= 0; i--) {
    if (bars[i].el.isConnected) bars[i].update(); else bars.splice(i, 1);
  }
}
let clipCount = 0;
/** A <g> that clips what it holds to `rect` (so zoomed marks do not spill into the labels). */
export function clipGroup(svg, { x, y, width, height }) {
  const id = `zoomclip${clipCount++}`;
  const defs = s('defs', {}, s('clipPath', { id }, s('rect', { x, y, width, height })));
  svg.append(defs);
  return s('g', { 'clip-path': `url(#${id})` });
}

// --- state ------------------------------------------------------------------

export const getRange = (axis) => AXES[axis].range;
export const isZoomed = (axis) => AXES[axis].range !== null;

/** Calls fn(range) whenever the axis' range changes; returns a function that stops it. */
export function onRange(axis, fn) {
  AXES[axis].subs.push(fn);
  return () => { AXES[axis].subs = AXES[axis].subs.filter((f) => f !== fn); };
}

const same = (a, b) => (a === null && b === null) || (a && b && a[0] === b[0] && a[1] === b[1]);

function clean(axis, range) {
  if (!range) return null;
  let [lo, hi] = range;
  if (![lo, hi].every(Number.isFinite)) return null;
  if (lo > hi) [lo, hi] = [hi, lo];
  if (AXES[axis].index) {
    lo = Math.round(lo); hi = Math.round(hi);
    if (lo < 1 || hi < lo) return null;
    return [lo, hi];
  }
  if (lo < 0 || !(hi > lo)) return null;
  const r = (v) => +v.toPrecision(3);
  return [r(lo), r(hi)];
}

/** Set (or, with null, clear) the shared range of an axis; redraws every chart on it. */
export function setRange(axis, range, { focusId = null, fromHash = false } = {}) {
  const next = clean(axis, range);
  if (same(next, AXES[axis].range)) return;
  AXES[axis].range = next;
  if (!fromHash) writeHash();
  pendingFocus = focusId;
  hideTip();
  AXES[axis].subs.forEach((fn) => fn(next));
  refreshBars();
  if (pendingFocus && focusTargets.has(pendingFocus)) focusTargets.get(pendingFocus).focus({ preventScroll: true });
  pendingFocus = null;
}

/**
 * The x domain a chart draws: the shared range clipped to the chart's own full domain, or the
 * full domain when there is no range (or it lies outside what this chart can show).
 */
export function effectiveDomain(axis, full) {
  const r = AXES[axis].range;
  if (!r) return { domain: full, zoomed: false };
  const lo = Math.max(r[0], full[0]);
  const hi = Math.min(r[1], full[1]);
  if (AXES[axis].index) {
    return hi >= lo && (lo > full[0] || hi < full[1]) ? { domain: [lo, hi], zoomed: true } : { domain: full, zoomed: false };
  }
  const eps = (full[1] - full[0]) * 1e-9;
  if (!(hi - lo > eps) || (lo <= full[0] + eps && hi >= full[1] - eps)) return { domain: full, zoomed: false };
  return { domain: [lo, hi], zoomed: true };
}

// --- URL hash ---------------------------------------------------------------

function hashTokens() {
  return window.location.hash.replace(/^#/, '').split('&').filter(Boolean);
}

function writeHash() {
  const tokens = hashTokens();
  const params = Object.values(AXES).map((a) => a.param);
  const keep = tokens.filter((t) => !params.some((p) => t.startsWith(`${p}=`)));
  for (const a of Object.values(AXES)) if (a.range) keep.push(`${a.param}=${a.range[0]},${a.range[1]}`);
  const hash = keep.length ? `#${keep.join('&')}` : '';
  try {
    history.replaceState(history.state, '', window.location.pathname + window.location.search + hash);
  } catch (_) { /* sandboxed: the range just is not shareable */ }
}

function readHash() {
  const tokens = hashTokens();
  for (const [axis, a] of Object.entries(AXES)) {
    const tok = tokens.find((t) => t.startsWith(`${a.param}=`));
    const parts = tok ? tok.slice(a.param.length + 1).split(',').map(Number) : null;
    if (parts && parts.length === 2) setRange(axis, parts, { fromHash: true });
    else if (a.range) writeHash(); // a link such as #bursts dropped our token: put it back
  }
}

for (const [axis, a] of Object.entries(AXES)) {
  const tok = hashTokens().find((t) => t.startsWith(`${a.param}=`));
  const parts = tok ? tok.slice(a.param.length + 1).split(',').map(Number) : null;
  if (parts && parts.length === 2) a.range = clean(axis, parts);
}
window.addEventListener('hashchange', readHash);

/** A hash like `#iat&zoom=...` has no element to scroll to: do it by hand (call once drawn). */
export function scrollToAnchor() {
  const anchor = hashTokens().find((t) => !t.includes('='));
  const el = anchor && document.getElementById(anchor);
  if (el && Object.values(AXES).some((a) => a.range)) el.scrollIntoView();
}

// --- readout ----------------------------------------------------------------

/**
 * Number of values of a log-binned histogram inside [lo, hi]: whole bins, and a bin the range
 * cuts is split in proportion (in log space), so edges between bins are approximate.
 */
export function countInRange(edges, counts, [lo, hi]) {
  let total = 0;
  for (let i = 0; i < counts.length; i++) {
    const a = edges[i];
    const b = edges[i + 1];
    if (b <= lo || a >= hi || !counts[i]) continue;
    const from = Math.max(a, lo);
    const to = Math.min(b, hi);
    total += counts[i] * (Math.log(to) - Math.log(from)) / (Math.log(b) - Math.log(a));
  }
  return total;
}

// --- ticks ------------------------------------------------------------------

/** Ticks for a zoomed log axis: decades when wide, then 1-2-5, then 1-9, then linear. */
export function logTicks(domain, width = 300) {
  const [lo, hi] = domain;
  const max = Math.max(3, Math.floor(width / 62));
  const inRange = (mults) => {
    const out = [];
    for (let e = Math.floor(Math.log10(lo)) - 1; e <= Math.ceil(Math.log10(hi)); e++) {
      for (const m of mults) {
        const v = m * 10 ** e;
        if (v >= lo * (1 - 1e-9) && v <= hi * (1 + 1e-9)) out.push(v);
      }
    }
    return out;
  };
  const levels = [[1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 5], [1]];
  for (const mults of levels) {
    const t = inRange(mults);
    if (t.length >= 2 && t.length <= max) return t;
  }
  return niceTicks(lo, hi, Math.min(max, 5));
}

// --- brush ------------------------------------------------------------------

const MIN_DRAG_PX = 5;

/**
 * Make one chart's SVG selectable. opts:
 *   id        unique per chart (keeps keyboard focus across redraws)
 *   axis      'iat' | 'size'
 *   mode      'log' | 'linear' | 'index': how the axis is laid out (drives keyboard steps)
 *   plot      { left, right, top, bottom } in svg coordinates
 *   toValue   (px) => axis value at an x pixel
 *   full      the chart's full domain
 *   current   the domain the chart now shows (effectiveDomain().domain)
 */
export function attachBrush(svg, { id, axis, mode, plot, toValue, full, current }) {
  svg.classList.add('zoomable');
  svg.setAttribute('tabindex', '0');
  svg.setAttribute('role', 'group');
  svg.setAttribute('aria-roledescription', 'zoomable chart');
  svg.setAttribute('aria-label', `${svg.getAttribute('aria-label') || 'Chart'}. Arrow keys select and move a range, Up and Down resize it, Escape resets.`);
  focusTargets.set(id, svg);

  const vbW = svg.viewBox.baseVal.width || svg.clientWidth || 1;
  const px = (ev) => {
    const r = svg.getBoundingClientRect();
    return Math.min(plot.right, Math.max(plot.left, ((ev.clientX - r.left) * vbW) / (r.width || 1)));
  };
  let drag = null;
  let sel = null;

  const end = () => { sel?.remove(); sel = null; drag = null; };
  svg.addEventListener('pointerdown', (ev) => {
    if (ev.button !== 0 || (ev.pointerType === 'touch' && !selectMode)) return;
    const r = svg.getBoundingClientRect();
    const x = ((ev.clientX - r.left) * vbW) / (r.width || 1);
    const y = ev.clientY - r.top;
    if (x < plot.left - 2 || x > plot.right + 2 || y < plot.top - 2 || y > plot.bottom + 2) return;
    drag = { x0: px(ev), x1: px(ev), pointer: ev.pointerId };
    try { svg.setPointerCapture(ev.pointerId); } catch (_) { /* no capture: moves outside are lost */ }
    ev.preventDefault();
  });
  svg.addEventListener('pointermove', (ev) => {
    if (!drag || ev.pointerId !== drag.pointer) return;
    drag.x1 = px(ev);
    hideTip();
    if (Math.abs(drag.x1 - drag.x0) < MIN_DRAG_PX) return;
    if (!sel) {
      sel = s('rect', { class: 'zoom-sel', y: plot.top, height: plot.bottom - plot.top });
      svg.append(sel);
    }
    sel.setAttribute('x', Math.min(drag.x0, drag.x1));
    sel.setAttribute('width', Math.abs(drag.x1 - drag.x0));
  });
  svg.addEventListener('pointerup', (ev) => {
    if (!drag || ev.pointerId !== drag.pointer) return;
    const { x0, x1 } = drag;
    end();
    if (Math.abs(x1 - x0) < MIN_DRAG_PX) return;
    const a = toValue(Math.min(x0, x1));
    const b = toValue(Math.max(x0, x1));
    setRange(axis, mode === 'index' ? [a, b] : [Math.max(a, full[0]), Math.min(b, full[1])], { focusId: id });
  });
  svg.addEventListener('pointercancel', end);
  svg.addEventListener('dblclick', () => setRange(axis, null, { focusId: id }));

  svg.addEventListener('keydown', (ev) => {
    if (ev.altKey || ev.ctrlKey || ev.metaKey) return;
    const k = ev.key;
    if (k === 'Escape') {
      if (isZoomed(axis)) { setRange(axis, null, { focusId: id }); ev.preventDefault(); }
      return;
    }
    const move = { ArrowLeft: -1, ArrowRight: 1 }[k];
    const size = { ArrowUp: 1, '+': 1, '=': 1, ArrowDown: -1, '-': -1 }[k];
    if (!move && !size) return;
    ev.preventDefault();
    const next = stepRange(mode, full, current, isZoomed(axis), move || 0, size || 0);
    if (next) setRange(axis, next, { focusId: id });
  });
}

/** The keyboard step: pan by a quarter of the range, resize by a factor of 1.5 (index: by one). */
function stepRange(mode, full, current, zoomed, move, size) {
  if (mode === 'index') {
    let [lo, hi] = current;
    if (!zoomed) return [full[0] + 1, full[1] - 1]; // first key press: the middle sizes
    if (move) { const d = Math.min(Math.max(move, full[0] - lo), full[1] - hi); lo += d; hi += d; }
    if (size > 0) { if (hi < full[1]) hi += 1; else if (lo > full[0]) lo -= 1; }
    if (size < 0 && hi > lo) hi -= 1;
    return lo === full[0] && hi === full[1] ? null : [lo, hi];
  }
  const f = mode === 'log' ? Math.log10 : (v) => v;
  const inv = mode === 'log' ? (v) => 10 ** v : (v) => v;
  const F0 = f(full[0]);
  const F1 = f(full[1]);
  let a = f(current[0]);
  let b = f(current[1]);
  if (!zoomed) { a = F0 + (F1 - F0) * 0.25; b = F0 + (F1 - F0) * 0.75; return [inv(a), inv(b)]; }
  let w = b - a;
  if (size) {
    const mid = (a + b) / 2;
    w = size > 0 ? w * 1.5 : w / 1.5;
    a = mid - w / 2;
    b = mid + w / 2;
  }
  if (move) { a += move * w * 0.25; b += move * w * 0.25; }
  if (b - a >= F1 - F0) return null;
  if (a < F0) { b += F0 - a; a = F0; }
  if (b > F1) { a -= b - F1; b = F1; }
  if (a <= F0 + 1e-9 && b >= F1 - 1e-9) return null;
  return [inv(a), inv(b)];
}

// --- control bar ------------------------------------------------------------

/**
 * Fills `el` with the zoom controls of one section. opts:
 *   axis      'iat' | 'size'
 *   describe  (range) => text, e.g. "5 ms to 2 s"
 *   hint      text while there is no range
 *   readout   (range) => [{ topo | label, text }]: the share inside the range per topology
 *   note      small print under the readout
 */
export function zoomBar(el, { axis, describe, hint, readout, note }) {
  const toggle = h('button', { type: 'button', class: 'btn btn--ghost btn--small', 'aria-pressed': 'false', title: 'On a touch screen, turn this on to drag a range instead of scrolling' }, 'Select range');
  const reset = h('button', { type: 'button', class: 'btn btn--ghost btn--small', disabled: true }, 'Reset zoom');
  const text = h('span', { class: 'zoom-bar__range', role: 'status', 'aria-live': 'polite' });
  const list = h('ul', { class: 'zoom-readout' });
  const small = h('p', { class: 'zoom-bar__note', text: note || '' });
  el.classList.add('zoom-bar');
  el.replaceChildren(...[h('div', { class: 'zoom-bar__row' }, [toggle, reset, text]), list, note ? small : null].filter(Boolean));
  const update = () => {
    const r = getRange(axis);
    reset.disabled = !r;
    toggle.setAttribute('aria-pressed', String(selectMode));
    text.textContent = r ? `Zoomed to ${describe(r)}` : hint;
    list.replaceChildren(...(r ? readout(r) : []).map((it) => h('li', {}, [
      it.topo ? swatch(it.topo) : null, h('b', { text: it.topo ? TOPO_LABEL[it.topo] : it.label }), ` ${it.text}`,
    ])));
  };
  toggle.addEventListener('click', () => {
    selectMode = !selectMode;
    document.body.classList.toggle('zoom-select', selectMode);
    refreshBars();
  });
  reset.addEventListener('click', () => setRange(axis, null));
  bars.push({ el, update });
  update();
}
