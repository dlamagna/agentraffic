/**
 * Traffic page analyses, and the traffic model playground on the Beta page. Loaded only by
 * results/traffic-patterns/ and results/beta/. Data: traffic.json of the active data set (ui/data/, scripts/demo/analysis_traffic.py) plus
 * summary.json (the paper's log-normal fits and the IAT histograms).
 *
 *   #bursts      calls by burst size (small multiples) and ON / OFF periods on a log time axis
 *   #gaps        IAT histograms after merging each burst into one arrival, against all gaps
 *   #robustness  KS rejection rate over 500 subsamples at n = 50 / 100 / 200 (the paper's published table)
 *   #playground  K workflows from the burst + log-normal model vs Poisson, simulated here (the Beta page)
 *
 * The goodness-of-fit table (#fits) is drawn by iat.js. Sets body[data-traffic-ready] when done.
 */

import {
  h, s, svgRoot, linear, log10, axisBottom, axisLeft, barPath, niceMax, niceTicks, logTimeLabel, responsive,
  showTip, showTipAt, hideTip, tipTitle, tipRow, tipNote, TOPOS, TOPO_LABEL, TOPO_COLOR, swatch,
  fixed, int, pct, seconds, dataTable, loadSummary, loadData,
} from './util.js';
import { addFullscreen } from './fullscreen.js';
import { clipGroup, effectiveDomain, attachBrush, logTicks, onRange, zoomBar, countInRange, scrollToAnchor } from './zoom.js';

const LOG_DOMAIN = [1e-4, 300]; // as the IAT histograms (iat.js X_DOMAIN)
const FAMILIES = ['exponential', 'weibull', 'lognormal'];
const FAM_LABEL = { lognormal: 'Log-normal', exponential: 'Exponential', weibull: 'Weibull' };
const FAM_SHORT = { lognormal: 'Log-n.', exponential: 'Exp.', weibull: 'Weib.' };
const FAM_STROKE = { lognormal: 'var(--fit-lognormal)', exponential: 'var(--fit-exponential)', weibull: 'var(--fit-weibull)' };
const FAM_DASH = { lognormal: null, exponential: 'dashed', weibull: 'dotted' };
const POISSON = 'var(--fit-exponential)';

const host = (id) => document.getElementById(id);

function guard(id, fn) {
  const el = host(id);
  if (!el) return false;
  try {
    fn(el);
    return true;
  } catch (err) {
    console.error(`[traffic] ${id} failed:`, err);
    el.replaceChildren(h('p', { class: 'placeholder', text: `This chart could not be drawn (${err.message}).` }));
    return false;
  }
}

const percentile = (sorted, q) => {
  if (!sorted.length) return NaN;
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.min(lo + 1, sorted.length - 1);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
};

/** A labelled line key (legend), solid / dashed / dotted. */
const lineKey = (color, dash = null) => h('span', {
  class: 'tr-key', 'aria-hidden': 'true', style: `border-top-color:${color};${dash ? `border-top-style:${dash};` : ''}`,
});

// ---------------------------------------------------------------------------
// Burst structure
// ---------------------------------------------------------------------------

const MAX_SIZE = 5;
const sizeCharts = [];
const sizeFs = [];
const gapCharts = [];
const gapFs = [];
const onOffFs = [];

function drawBurstSizes(el, T) {
  const pending = [];
  el.replaceChildren(...TOPOS.map((t) => {
    const b = T.bursts[t];
    const counts = new Map(b.sizes);
    const rows = [];
    for (let k = 1; k <= MAX_SIZE; k++) {
      const n = counts.get(k) || 0;
      rows.push({ k, bursts: n, calls: n * k, share: (n * k) / b.n_calls });
    }
    const chart = h('div', { class: 'chart-body' });
    const sub = b.bursts_per_run
      ? `${fixed(b.bursts_per_run, 1)} bursts of 2+ calls per run · ${pct(b.calls_in_bursts, 0)} of calls in one`
      : 'No bursts: every call waits for the previous reply';
    const fig = h('figure', { class: 'chart', 'data-topology': t }, [h('h3', {}, [swatch(t), TOPO_LABEL[t]]), h('p', { class: 'chart-sub', text: sub }), chart]);
    // target: where to draw; height: set for the full-screen view; brush: range selection (in-page only)
    const drawSizes = (target, w, height = null, brush = true) => {
      const M = { top: 18, right: 8, bottom: 34, left: 40 };
      const H = height || 170;
      const svg = svgRoot(w, H, `${TOPO_LABEL[t]}: share of discussion calls by burst size`);
      const g = s('g');
      const { domain: [k0, k1] } = effectiveDomain('size', [1, MAX_SIZE]);
      const shown = rows.filter((r) => r.k >= k0 && r.k <= k1);
      const band = (w - M.left - M.right) / shown.length;
      const y = linear([0, 100], [H - M.bottom, M.top]);
      axisLeft(g, y, M.left, { format: (v) => `${v}%`, ticks: [0, 50, 100], gridRight: w - M.right });
      const bars = s('g');
      const hits = s('g');
      shown.forEach((r, i) => {
        const x0 = M.left + i * band;
        const bw = Math.min(height ? 90 : 36, band * 0.62);
        const bx = x0 + (band - bw) / 2;
        const yv = y(r.share * 100);
        if (r.share > 0) bars.append(s('path', { d: barPath(bx, yv, bw, y(0) - yv, 4), fill: TOPO_COLOR[t] }));
        if (r.share >= 0.01) bars.append(s('text', { class: 'annot', x: bx + bw / 2, y: yv - 5, 'text-anchor': 'middle', text: pct(r.share, 0) }));
        g.append(s('text', { x: x0 + band / 2, y: H - M.bottom + 14, 'text-anchor': 'middle', text: r.k === 1 ? '1 (alone)' : String(r.k) }));
        const hit = s('rect', { class: 'hit', x: x0, y: M.top, width: band, height: H - M.bottom - M.top, tabindex: '0' });
        const tip = () => [
          tipTitle(r.k === 1 ? 'Calls on their own' : `Bursts of ${r.k} calls`),
          tipRow(pct(r.share, 1), `of calls (${int(r.calls)})`, TOPO_COLOR[t]),
          tipRow(int(r.bursts), r.k === 1 ? 'single calls' : 'bursts'),
        ];
        hit.addEventListener('pointermove', (ev) => showTip(tip(), ev.clientX, ev.clientY));
        hit.addEventListener('pointerleave', hideTip);
        hit.addEventListener('focus', () => showTipAt(tip(), hit));
        hit.addEventListener('blur', hideTip);
        hits.append(hit);
      });
      g.append(s('line', { class: 'baseline', x1: M.left, x2: w - M.right, y1: y(0), y2: y(0) }));
      g.append(s('text', { class: 'axis-title', x: (M.left + w - M.right) / 2, y: H - 4, 'text-anchor': 'middle', text: 'calls in the burst' }));
      g.append(bars, hits);
      svg.append(g);
      if (brush) {
        attachBrush(svg, {
          id: `size:${t}`, axis: 'size', mode: 'index', full: [1, MAX_SIZE], current: [k0, k1],
          plot: { left: M.left, right: w - M.right, top: M.top, bottom: H - M.bottom },
          toValue: (px) => k0 + Math.min(shown.length - 1, Math.max(0, Math.floor((px - M.left) / band))),
        });
      }
      target.replaceChildren(svg);
    };
    pending.push(() => sizeCharts.push(responsive(chart, (w) => drawSizes(chart, w))));
    sizeFs.push(addFullscreen(fig, {
      title: `${TOPO_LABEL[t]}: calls by burst size`,
      subtitle: sub,
      draw: (el, w, ht) => drawSizes(el, w, Math.max(240, ht - 4), false),
    }));
    return fig;
  }));
  pending.forEach((f) => f());

  const zoomHost = h('div');
  el.before(zoomHost);
  const size = (r) => (r[0] === r[1] ? `bursts of ${r[0]} call${r[0] === 1 ? '' : 's'}` : `bursts of ${r[0]} to ${r[1]} calls`);
  zoomBar(zoomHost, {
    axis: 'size',
    hint: 'Drag across the bars to zoom into a range of burst sizes.',
    describe: size,
    readout: (r) => TOPOS.map((t) => {
      const counts = new Map(T.bursts[t].sizes);
      let calls = 0;
      for (let k = r[0]; k <= r[1]; k++) calls += (counts.get(k) || 0) * k;
      return { topo: t, text: `${pct(calls / T.bursts[t].n_calls)} of calls (${int(calls)})` };
    }),
  });
  onRange('size', () => { sizeCharts.forEach((c) => c.rerender()); sizeFs.forEach((f) => f.refresh()); });
}

const onOffCharts = [];

function drawOnOff(el, T) {
  const rows = [];
  for (const t of TOPOS) {
    rows.push({ t, kind: 'ON', d: T.bursts[t].on });
    rows.push({ t, kind: 'OFF', d: T.bursts[t].off });
  }
  // the chart host gets a figure around it so the full-screen button has a corner to sit in
  const fig = h('figure', { class: 'chart' });
  el.replaceWith(fig);
  fig.append(el);
  const drawPeriods = (target, w, height = null, brush = true) => {
    const narrow = w < 480;
    // narrow: the topology name goes on its own line above its two rows
    const M = { top: 8, right: narrow ? 12 : 120, bottom: 40, left: narrow ? 40 : 112 };
    const groupGap = narrow ? 22 : 10;
    const fixedH = M.top + (narrow ? 14 : 0) + (TOPOS.length - 1) * groupGap + M.bottom;
    const rowH = height ? Math.max(24, Math.min(90, Math.floor((height - fixedH) / rows.length))) : 24;
    const H = fixedH + rows.length * rowH;
    const bh = Math.round(rowH / 4); // bar half-height (6 at the in-page row height)
    const svg = svgRoot(w, H, 'ON and OFF period lengths per topology on a log time axis');
    const g = s('g');
    const { domain, zoomed } = effectiveDomain('iat', LOG_DOMAIN);
    const x = log10(domain, [M.left, w - M.right]);
    const yBase = H - M.bottom;
    axisBottom(g, x, yBase, {
      ticks: zoomed ? logTicks(domain, w) : undefined,
      format: (v) => (narrow && !zoomed && Math.round(Math.log10(v)) % 2 !== 0 ? '' : logTimeLabel(v)),
      gridTop: M.top,
      title: `period length (log scale${zoomed ? ', zoomed' : ''})`,
      titleY: 32,
    });
    const marks = s('g');
    const cm = clipGroup(svg, { x: M.left, y: 0, width: w - M.left - M.right, height: H }); // bars and lines stay inside the plot
    marks.append(cm);
    rows.forEach((r, i) => {
      const yc = M.top + (narrow ? 14 : 0) + i * rowH + Math.floor(i / 2) * groupGap + rowH / 2;
      if (r.kind === 'ON') {
        marks.append(narrow
          ? s('text', { class: 'tr-row-label', x: 0, y: yc - rowH / 2 - 3, text: TOPO_LABEL[r.t] })
          : s('text', { class: 'tr-row-label', x: 4, y: yc + rowH / 2 + 2, text: TOPO_LABEL[r.t] }));
      }
      marks.append(s('text', { class: 'annot-muted', x: M.left - 8, y: yc + 4, 'text-anchor': 'end', text: r.kind }));
      const d = r.d;
      if (!d.n) {
        marks.append(s('text', { class: 'annot-muted', x: M.left + 6, y: yc + 4, text: 'no bursts' }));
        return;
      }
      const col = TOPO_COLOR[r.t];
      cm.append(s('line', { x1: x(d.p5_s), x2: x(d.p95_s), y1: yc, y2: yc, stroke: col, 'stroke-width': 1.5 }));
      const x25 = x(d.p25_s);
      const x75 = x(d.p75_s);
      cm.append(s('rect', { x: x25, y: yc - bh, width: Math.max(2, x75 - x25), height: 2 * bh, rx: 3, fill: col, 'fill-opacity': r.kind === 'ON' ? 0.55 : 1 }));
      cm.append(s('line', { class: 'tr-median', x1: x(d.p50_s), x2: x(d.p50_s), y1: yc - bh - 2, y2: yc + bh + 2 }));
      if (!narrow) cm.append(s('text', { class: 'annot', x: x(d.p95_s) + 8, y: yc + 4, text: `median ${seconds(d.p50_s)}` }));
      const hit = s('rect', { class: 'hit', x: M.left, y: yc - rowH / 2, width: w - M.left - M.right, height: rowH, tabindex: '0' });
      const tip = () => [
        tipTitle(`${TOPO_LABEL[r.t]}: ${r.kind === 'ON' ? 'ON (inside a burst)' : 'OFF (between bursts)'}`),
        tipRow(seconds(d.p50_s), 'median', col),
        tipRow(`${seconds(d.p25_s)} – ${seconds(d.p75_s)}`, 'interquartile range'),
        tipRow(`${seconds(d.p5_s)} – ${seconds(d.p95_s)}`, '5th – 95th percentile'),
        tipNote(`${int(d.n)} periods`),
      ];
      hit.addEventListener('pointermove', (ev) => showTip(tip(), ev.clientX, ev.clientY));
      hit.addEventListener('pointerleave', hideTip);
      hit.addEventListener('focus', () => showTipAt(tip(), hit));
      hit.addEventListener('blur', hideTip);
      marks.append(hit);
    });
    g.append(marks);
    svg.append(g);
    if (brush) {
      attachBrush(svg, {
        id: 'onoff', axis: 'iat', mode: 'log', full: LOG_DOMAIN, current: domain,
        plot: { left: M.left, right: w - M.right, top: M.top, bottom: yBase }, toValue: x.invert,
      });
    }
    target.replaceChildren(svg);
  };
  onOffCharts.push(responsive(el, (w) => drawPeriods(el, w)));
  onOffFs.push(addFullscreen(fig, {
    title: 'ON and OFF periods',
    subtitle: 'ON: first to last call start of a burst of two or more calls. OFF: the silence until the next burst. Bar: interquartile range; line: 5th to 95th percentile; tick: median.',
    draw: (host2, w, ht) => drawPeriods(host2, w, Math.max(240, ht - 4), false),
  }));

  const zoomHost = h('div');
  el.before(zoomHost);
  zoomBar(zoomHost, {
    axis: 'iat',
    hint: 'Drag on the chart to zoom into a range of period length; the range is shared with the IAT and gap charts.',
    describe: ([a, b]) => `${logTimeLabel(a)} to ${logTimeLabel(b)} of period length`,
    readout: () => [],
  });
  onRange('iat', () => { onOffCharts.forEach((c) => c.rerender()); onOffFs.forEach((f) => f.refresh()); });
}

function burstTable(el, T) {
  const rows = TOPOS.map((t) => {
    const b = T.bursts[t];
    return [
      h('span', {}, [swatch(t), TOPO_LABEL[t]]),
      fixed(b.bursts_per_run, 1),
      pct(b.calls_in_bursts, 0),
      b.on.n ? seconds(b.on.p50_s) : '–',
      seconds(b.off.p50_s),
    ];
  });
  el.replaceChildren(dataTable(
    ['Topology', 'Bursts per run', 'Calls in a burst', 'ON median', 'OFF median'],
    rows, { caption: 'Burst structure per topology (bursts of two or more calls)', numeric: [1, 2, 3, 4], className: 'tr-compact' },
  ));
  host('burstSource').textContent = '';
}

// ---------------------------------------------------------------------------
// Gaps with bursts removed
// ---------------------------------------------------------------------------

function drawGaps(el, T, summary) {
  const bins = T.gaps.bins_s;
  const per = T.gaps.per_topology;
  const raw = summary.iat.per_topology;
  const share = (c, n) => (c / n) * 100;
  // one y scale for all three charts, over the bins inside the zoomed range
  const yMaxFor = (lo, hi) => niceMax(Math.max(...TOPOS.flatMap((t) => bins.slice(0, -1).flatMap((b, i) => (
    bins[i + 1] > lo && b < hi ? [share(per[t].counts[i], per[t].merged.n), share(raw[t].counts[i], raw[t].n)] : [])))));
  host('gapLegend').replaceChildren(
    h('span', {}, [h('span', { class: 'tr-swatch-row', 'aria-hidden': 'true' }, TOPOS.map((t) => swatch(t))), 'Gaps between bursts (each burst merged)']),
    h('span', {}, [lineKey('var(--ink-3)'), 'All gaps, as in the first chart']),
  );
  const pending = [];
  el.replaceChildren(...TOPOS.map((t) => {
    const p = per[t];
    const chart = h('div', { class: 'chart-body' });
    const fig = h('figure', { class: 'chart', 'data-topology': t }, [
      h('h3', {}, [swatch(t), TOPO_LABEL[t]]),
      h('p', { class: 'chart-sub', text: `${int(p.merged.n)} of ${int(p.raw.n)} gaps left · median ${seconds(p.raw.p50_s)} → ${seconds(p.merged.p50_s)}` }),
      chart,
    ]);
    const drawGap = (target, w, height = null, brush = true) => {
      const narrow = w < 360;
      const M = { top: 14, right: 10, bottom: 38, left: 42 };
      const H = height || (narrow ? 190 : 210);
      const svg = svgRoot(w, H, `${TOPO_LABEL[t]}: gaps between merged bursts against all gaps`);
      const g = s('g');
      const { domain, zoomed } = effectiveDomain('iat', LOG_DOMAIN);
      const yMax = yMaxFor(...domain);
      const x = log10(domain, [M.left, w - M.right]);
      const y = linear([0, yMax], [H - M.bottom, M.top]);
      const xb = Math.min(x(T.burst_threshold_s), w - M.right);
      if (xb > M.left) g.append(s('rect', { class: 'burst-zone', x: M.left, y: M.top, width: xb - M.left, height: H - M.bottom - M.top }));
      axisLeft(g, y, M.left, { format: (v) => `${fixed(v, 0)}%`, ticks: y.ticks(4), gridRight: w - M.right });
      axisBottom(g, x, H - M.bottom, {
        ticks: zoomed ? logTicks(domain, w) : undefined,
        format: (v) => (narrow && !zoomed && Math.round(Math.log10(v)) % 2 !== 0 ? '' : logTimeLabel(v)),
        gridTop: M.top, title: `gap (log scale${zoomed ? ', zoomed' : ''})`, titleY: 32,
      });
      const bars = s('g');
      const hits = s('g');
      let outline = '';
      for (let i = 0; i < bins.length - 1; i++) {
        const lo = bins[i];
        const hi = bins[i + 1];
        if (hi <= domain[0] || lo >= domain[1]) continue;
        const x0 = x(Math.max(lo, domain[0]));
        const x1 = x(Math.min(hi, domain[1]));
        const m = share(p.counts[i], p.merged.n);
        const r = share(raw[t].counts[i], raw[t].n);
        if (m > 0) {
          const yt = y(Math.min(m, yMax));
          bars.append(s('path', { d: barPath(x0, yt, Math.max(0.5, x1 - x0 - 1), y(0) - yt, 2), fill: TOPO_COLOR[t] }));
        }
        const yr = y(Math.min(r, yMax));
        outline += `${outline ? 'L' : 'M'}${x0.toFixed(1)},${yr.toFixed(1)}H${x1.toFixed(1)}`;
        if (m > 0 || r > 0) {
          const hit = s('rect', { class: 'hit', x: x0, y: M.top, width: x1 - x0, height: H - M.bottom - M.top });
          hit.addEventListener('pointermove', (ev) => showTip([
            tipTitle(`${logTimeLabel(lo)} – ${logTimeLabel(hi)}`),
            tipRow(`${fixed(m, 2)}%`, `of merged gaps (${int(p.counts[i])})`, TOPO_COLOR[t]),
            tipRow(`${fixed(r, 2)}%`, `of all gaps (${int(raw[t].counts[i])})`, 'var(--ink-3)'),
          ], ev.clientX, ev.clientY));
          hit.addEventListener('pointerleave', hideTip);
          hits.append(hit);
        }
      }
      g.append(bars, s('path', { class: 'tr-outline', d: outline }), hits);
      svg.append(g);
      if (brush) {
        attachBrush(svg, {
          id: `gap:${t}`, axis: 'iat', mode: 'log', full: LOG_DOMAIN, current: domain,
          plot: { left: M.left, right: w - M.right, top: M.top, bottom: H - M.bottom }, toValue: x.invert,
        });
      }
      target.replaceChildren(svg);
    };
    pending.push(() => gapCharts.push(responsive(chart, (w) => drawGap(chart, w))));
    gapFs.push(addFullscreen(fig, {
      title: `${TOPO_LABEL[t]}: gaps with bursts removed`,
      subtitle: `${int(p.merged.n)} of ${int(p.raw.n)} gaps left · median ${seconds(p.raw.p50_s)} → ${seconds(p.merged.p50_s)}. Bars: gaps between merged bursts; line: all gaps.`,
      draw: (el, w, ht) => drawGap(el, w, Math.max(240, ht - 4), false),
    }));
    return fig;
  }));
  pending.forEach((f) => f());

  // the same shared range as the IAT histograms above (iat.js)
  const zoomHost = h('div');
  host('gapLegend').after(zoomHost);
  zoomBar(zoomHost, {
    axis: 'iat',
    hint: 'Drag on a chart to zoom into a range of gap length; the range is shared with the IAT histograms above.',
    describe: ([a, b]) => `${logTimeLabel(a)} to ${logTimeLabel(b)} of gap length`,
    readout: (r) => TOPOS.map((t) => {
      const c = countInRange(bins, per[t].counts, r);
      const a = countInRange(bins, raw[t].counts, r);
      return { topo: t, text: `${pct(c / per[t].merged.n)} of merged gaps (about ${int(c)}); ${pct(a / raw[t].n)} of all gaps` };
    }),
  });
  onRange('iat', () => { gapCharts.forEach((c) => c.rerender()); gapFs.forEach((f) => f.refresh()); });

  const arrow = (a, b, f) => h('span', {}, [h('span', { class: 'tr-nw', text: `${f(a)} →` }), ' ', h('span', { class: 'tr-nw', text: f(b) })]);
  host('gapTable').replaceChildren(dataTable(
    ['Topology', 'Gaps', 'Median', 'p95', 'CV'],
    TOPOS.map((t) => {
      const { raw: a, merged: b } = per[t];
      return [h('span', {}, [swatch(t), TOPO_LABEL[t]]), arrow(a.n, b.n, int), arrow(a.p50_s, b.p50_s, seconds), arrow(a.p95_s, b.p95_s, seconds), arrow(a.cv, b.cv, (v) => fixed(v, 2))];
    }),
    { caption: 'Gaps before and after merging bursts (p95: 95th percentile)', numeric: [1, 2, 3, 4], className: 'tr-compact' },
  ));
  host('gapNotes').replaceChildren(
    h('p', { text: 'Each cell: all gaps → gaps after merging each burst into one arrival. CV = standard deviation ÷ mean; Poisson arrivals give 1.' }),
  );
}

// ---------------------------------------------------------------------------
// Subsampling robustness
// ---------------------------------------------------------------------------

function drawRobustness(el, T) {
  const R = T.robustness;
  const ns = R.ns.map(String);
  host('robLegend').replaceChildren(
    ...FAMILIES.map((f) => h('span', {}, [h('span', { class: `key key--${f}`, 'aria-hidden': 'true', style: 'margin-right:6px' }), FAM_LABEL[f]])),
  );
  const pending = [];
  el.replaceChildren(...TOPOS.map((t) => {
    const P = R.per_topology[t];
    const chart = h('div', { class: 'chart-body' });
    const fig = h('figure', { class: 'chart', 'data-topology': t }, [
      h('h3', {}, [swatch(t), TOPO_LABEL[t]]),
      chart,
    ]);
    pending.push(() => responsive(chart, (w) => {
      const M = { top: 12, right: 74, bottom: 38, left: 42 };
      const H = 200;
      const svg = svgRoot(w, H, `${TOPO_LABEL[t]}: KS rejection rate by sample size`);
      const g = s('g');
      const x = (i) => M.left + 18 + (i * (w - M.left - M.right - 30)) / (ns.length - 1);
      const y = linear([0, 100], [H - M.bottom, M.top]);
      axisLeft(g, y, M.left, { format: (v) => `${v}%`, ticks: [0, 25, 50, 75, 100], gridRight: w - M.right });
      ns.forEach((n, i) => g.append(s('text', { x: x(i), y: H - M.bottom + 14, 'text-anchor': 'middle', text: n })));
      g.append(s('text', { class: 'axis-title', x: (M.left + w - M.right) / 2, y: H - 6, 'text-anchor': 'middle', text: 'gaps per sample (n)' }));
      g.append(s('line', { class: 'baseline', x1: M.left, x2: w - M.right, y1: y(0), y2: y(0) }));
      const ends = [];
      for (const f of FAMILIES) {
        const ours = ns.map((n) => P.cells[n][f].reject_rate * 100);
        g.append(s('polyline', { class: `fit fit--${f}`, points: ours.map((v, i) => `${x(i)},${y(v)}`).join(' ') }));
        ours.forEach((v, i) => {
          g.append(s('circle', { class: 'tr-ours', cx: x(i), cy: y(v), r: 3.5, fill: FAM_STROKE[f] }));
        });
        ends.push({ f, y: y(ours[ours.length - 1]) });
      }
      // direct labels at the right end, nudged apart
      ends.sort((a, b) => a.y - b.y);
      for (let i = 1; i < ends.length; i++) ends[i].y = Math.max(ends[i].y, ends[i - 1].y + 12);
      ends.forEach((e) => g.append(s('text', { class: 'annot', x: x(ns.length - 1) + 9, y: e.y + 4, text: FAM_LABEL[e.f] })));
      ns.forEach((n, i) => {
        const half = (w - M.left - M.right) / (ns.length - 1) / 2;
        const hit = s('rect', { class: 'hit', x: x(i) - half, y: M.top, width: half * 2, height: H - M.bottom - M.top, tabindex: '0' });
        const tip = () => [
          tipTitle(`${TOPO_LABEL[t]}, n = ${n}`),
          ...FAMILIES.slice().reverse().map((f) => tipRow(pct(P.cells[n][f].reject_rate, 0), FAM_LABEL[f], FAM_STROKE[f], FAM_DASH[f])),
          tipNote(`KS critical value at α = ${R.alpha}: ${fixed(R.ks_critical[n], 3)}`),
        ];
        hit.addEventListener('pointermove', (ev) => showTip(tip(), ev.clientX, ev.clientY));
        hit.addEventListener('pointerleave', hideTip);
        hit.addEventListener('focus', () => showTipAt(tip(), hit));
        hit.addEventListener('blur', hideTip);
        g.append(hit);
      });
      svg.append(g);
      chart.replaceChildren(svg);
    }));
    return fig;
  }));
  pending.forEach((f) => f());

  // table: n × family rows, one column per topology
  const table = h('table', { class: 'data tr-rob' });
  table.append(h('caption', { class: 'visually-hidden', text: 'KS rejection rate per sample size, family and topology' }));
  table.append(h('thead', {}, h('tr', {}, [
    h('th', { scope: 'col', text: 'n' }), h('th', { scope: 'col', text: 'Family' }),
    ...TOPOS.map((t) => h('th', { scope: 'col', class: 'num' }, [swatch(t), TOPO_LABEL[t]])),
  ])));
  const body = h('tbody');
  for (const n of ns) {
    FAMILIES.forEach((f, i) => {
      body.append(h('tr', { class: i === 0 ? 'tr-group' : null }, [
        i === 0 ? h('th', { scope: 'rowgroup', rowspan: FAMILIES.length, text: n }) : null,
        h('td', {}, [
          h('span', { class: `key key--${f}`, 'aria-hidden': 'true', style: 'margin-right:6px' }),
          h('span', { class: 'tr-long', text: FAM_LABEL[f] }),
          h('span', { class: 'tr-short', 'aria-hidden': 'true', text: FAM_SHORT[f] }),
        ]),
        ...TOPOS.map((t) => h('td', { class: 'num' }, [h('b', { text: pct(R.per_topology[t].cells[n][f].reject_rate, 0) })])),
      ]));
    });
  }
  table.append(body);
  host('robTable').replaceChildren(table);
  host('robNotes').replaceChildren(
    h('p', { text: `A sample is n gaps drawn at random from the discussion gaps over 50 ms; every family is refitted to it by maximum likelihood (location 0) and tested with a one-sample KS test, and counted as rejected when p < ${R.alpha}. The rate is the share of the ${R.draws} samples in which that happens.` }),
  );
}

// ---------------------------------------------------------------------------
// Playground: K workflows from the burst + log-normal model vs Poisson
// ---------------------------------------------------------------------------

const HORIZON_S = 1800; // simulated time per run of the headline numbers
const WARMUP_S = 120;
const WINDOW_S = 120; // timeline window
const SWEEP_K = [1, 2, 5, 10, 20, 30, 50];
const SWEEP_HORIZON_S = 900;
const WAIT_TARGET = 0.05;

/** mulberry32: small deterministic PRNG, so a seed always gives the same picture. */
function prng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function gauss(r) {
  let u = 0;
  while (u === 0) u = r();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * r());
}

function topoModel(T, summary, t) {
  const ln = summary.iat.fits[t].lognormal;
  const b = T.bursts[t];
  const P = T.playground[t];
  const sizes = b.sizes.map(([k]) => k);
  let c = 0;
  const cdf = b.sizes.map(([, n]) => (c += n / b.n_bursts));
  const q = P.duration_quantiles_s;
  return {
    t, mu: ln.mu, sigma: ln.sigma, sizes, cdf, q,
    rate: P.calls_per_s, // calls per second per workflow (burst size / log-normal mean gap)
    meanInflight: P.model_mean_inflight,
    measured: P.measured_mean_inflight,
  };
}

/** Arrivals of K workflows over [-WARMUP, horizon): sorted times and their durations. */
function arrivals(m, K, horizon, kind, r) {
  const ts = [];
  const ds = [];
  const q = m.q;
  const dur = () => {
    const pos = r() * (q.length - 1);
    const i = Math.floor(pos);
    return q[i] + (q[Math.min(i + 1, q.length - 1)] - q[i]) * (pos - i);
  };
  for (let w = 0; w < K; w++) {
    let t = -WARMUP_S - r() * 30;
    while (t < horizon) {
      let k = 1;
      let gap;
      if (kind === 'model') {
        const u = r();
        let j = 0;
        while (j < m.cdf.length - 1 && u > m.cdf[j]) j++;
        k = m.sizes[j];
        gap = Math.exp(m.mu + m.sigma * gauss(r));
      } else {
        gap = -Math.log(1 - r()) / m.rate;
      }
      for (let i = 0; i < k; i++) { ts.push(t); ds.push(dur()); }
      t += gap;
    }
  }
  const idx = ts.map((_, i) => i).sort((a, b) => ts[a] - ts[b]);
  return { t: Float64Array.from(idx, (i) => ts[i]), d: Float64Array.from(idx, (i) => ds[i]) };
}

/** FIFO server with C slots (Infinity: no queue). Returns each call's wait and finish time. */
function serve(arr, C) {
  const n = arr.t.length;
  const wait = new Float64Array(n);
  const fin = new Float64Array(n);
  if (!Number.isFinite(C)) {
    for (let i = 0; i < n; i++) fin[i] = arr.t[i] + arr.d[i];
    return { wait, fin };
  }
  const heap = new Float64Array(C).fill(-Infinity); // slot free times, min-heap
  for (let i = 0; i < n; i++) {
    const a = arr.t[i];
    const start = Math.max(a, heap[0]);
    wait[i] = start - a;
    fin[i] = start + arr.d[i];
    // replace the root and sift down
    let j = 0;
    const v = fin[i];
    for (;;) {
      const l = 2 * j + 1;
      if (l >= C) break;
      const rr = l + 1;
      const c = rr < C && heap[rr] < heap[l] ? rr : l;
      if (heap[c] >= v) break;
      heap[j] = heap[c];
      j = c;
    }
    heap[j] = v;
  }
  return { wait, fin };
}

function waitShare(arr, sv, horizon) {
  let n = 0;
  let waited = 0;
  for (let i = 0; i < arr.t.length; i++) {
    if (arr.t[i] < 0 || arr.t[i] >= horizon) continue;
    n++;
    if (sv.wait[i] > 1e-3) waited++;
  }
  return n ? waited / n : 0;
}

/** Calls at the server (waiting + served) over [0, horizon]: time-weighted p99, max, mean and a step series. */
function occupancy(arr, sv, horizon, window) {
  const n = arr.t.length;
  const ev = new Float64Array(2 * n);
  const dl = new Int8Array(2 * n);
  for (let i = 0; i < n; i++) { ev[2 * i] = arr.t[i]; dl[2 * i] = 1; ev[2 * i + 1] = sv.fin[i]; dl[2 * i + 1] = -1; }
  const order = Array.from({ length: 2 * n }, (_, i) => i).sort((a, b) => ev[a] - ev[b] || dl[a] - dl[b]);
  const time = new Map();
  let level = 0;
  let last = 0;
  let max = 0;
  const series = [[0, 0]];
  for (const k of order) {
    const t = ev[k];
    if (t > 0 && last < horizon) {
      const t1 = Math.min(t, horizon);
      if (t1 > last) time.set(level, (time.get(level) || 0) + (t1 - last));
      last = Math.max(last, t1);
    }
    level += dl[k];
    if (t >= 0 && t < horizon) max = Math.max(max, level);
    if (t <= 0) series[0][1] = level;
    else if (t < window) series.push([t, level]);
  }
  if (last < horizon) time.set(level, (time.get(level) || 0) + (horizon - last));
  const levels = [...time.keys()].sort((a, b) => a - b);
  let acc = 0;
  let p99 = levels[levels.length - 1];
  let mean = 0;
  for (const l of levels) mean += (l * time.get(l)) / horizon;
  for (const l of levels) {
    acc += time.get(l) / horizon;
    if (acc >= 0.99) { p99 = l; break; }
  }
  return { p99, max, mean, series };
}

function peakPerSecond(arr, horizon) {
  let best = 0;
  let j = 0;
  const t = arr.t;
  for (let i = 0; i < t.length; i++) {
    if (t[i] < 0 || t[i] >= horizon) continue;
    while (t[j] < 0 || t[i] - t[j] >= 1) j++;
    best = Math.max(best, i - j + 1);
  }
  return best;
}

function slotsNeeded(arr, horizon) {
  const occ = occupancy(arr, serve(arr, Infinity), horizon, 0);
  let lo = 1;
  let hi = Math.max(1, occ.max);
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (waitShare(arr, serve(arr, mid), horizon) <= WAIT_TARGET) hi = mid; else lo = mid + 1;
  }
  return lo;
}

function simulate(m, K, C, seed) {
  const out = {};
  for (const kind of ['model', 'poisson']) {
    const r = prng(seed * 7919 + (kind === 'model' ? 1 : 2) + K * 31);
    const arr = arrivals(m, K, HORIZON_S, kind, r);
    const sv = serve(arr, C);
    const occ = occupancy(arr, sv, HORIZON_S, WINDOW_S);
    const waits = [];
    for (let i = 0; i < arr.t.length; i++) if (arr.t[i] >= 0 && arr.t[i] < HORIZON_S) waits.push(sv.wait[i]);
    waits.sort((a, b) => a - b);
    out[kind] = {
      ...occ,
      perSecond: peakPerSecond(arr, HORIZON_S),
      waited: waits.filter((w) => w > 1e-3).length / waits.length,
      p95wait: percentile(waits, 0.95),
      n: waits.length,
    };
  }
  return out;
}

const sweepCache = new Map();
function sweep(m, seed) {
  const key = `${m.t}:${seed}`;
  if (!sweepCache.has(key)) {
    sweepCache.set(key, SWEEP_K.map((K) => {
      const row = { K };
      for (const kind of ['model', 'poisson']) {
        const r = prng(seed * 104729 + (kind === 'model' ? 11 : 13) + K * 17);
        row[kind] = slotsNeeded(arrivals(m, K, SWEEP_HORIZON_S, kind, r), SWEEP_HORIZON_S);
      }
      return row;
    }));
  }
  return sweepCache.get(key);
}

const relDiff = (poisson, model) => (model ? (poisson - model) / model : 0);
function vsPoisson(poisson, model, fmt) {
  const d = relDiff(poisson, model);
  const word = Math.abs(d) < 0.03 ? 'about the same' : d < 0 ? `${pct(-d, 0)} lower` : `${pct(d, 0)} higher`;
  return `Poisson: ${fmt(poisson)} (${word})`;
}

function drawTimeline(el, res, C, t) {
  return responsive(el, (w) => {
    const M = { top: 12, right: 12, bottom: 36, left: 42 };
    const H = 210;
    const svg = svgRoot(w, H, `Calls at the server over ${WINDOW_S} seconds, model and Poisson`);
    const g = s('g');
    const top = niceMax(Math.max(C === Infinity ? 0 : C, ...res.model.series.map((p) => p[1]), ...res.poisson.series.map((p) => p[1])) * 1.08);
    const x = linear([0, WINDOW_S], [M.left, w - M.right]);
    const y = linear([0, top], [H - M.bottom, M.top]);
    axisLeft(g, y, M.left, { ticks: y.ticks(4), gridRight: w - M.right, format: (v) => int(v) });
    axisBottom(g, x, H - M.bottom, { ticks: niceTicks(0, WINDOW_S, w < 420 ? 4 : 6), format: (v) => `${v} s`, title: 'simulated time', titleY: 32 });
    const step = (series) => {
      let d = '';
      series.forEach(([tt, l], i) => {
        const px = x(tt).toFixed(1);
        const py = y(l).toFixed(1);
        d += i === 0 ? `M${px},${py}` : `H${px}V${py}`;
      });
      return `${d}H${x(WINDOW_S).toFixed(1)}`;
    };
    if (Number.isFinite(C)) {
      g.append(s('line', { class: 'tr-capacity', x1: M.left, x2: w - M.right, y1: y(C), y2: y(C) }));
      g.append(s('text', { class: 'annot-muted', x: w - M.right, y: y(C) - 4, 'text-anchor': 'end', text: `${C} slots` }));
    }
    g.append(s('path', { class: 'tr-step tr-step--poisson', d: step(res.poisson.series), stroke: POISSON }));
    g.append(s('path', { class: 'tr-step', d: step(res.model.series), stroke: TOPO_COLOR[t] }));
    const cross = s('line', { class: 'annot-line', y1: M.top, y2: H - M.bottom, visibility: 'hidden' });
    g.append(cross);
    const at = (series, tt) => {
      let lo = 0;
      let hi = series.length - 1;
      while (lo < hi) {
        const mid = (lo + hi + 1) >> 1;
        if (series[mid][0] <= tt) lo = mid; else hi = mid - 1;
      }
      return series[lo][1];
    };
    const hit = s('rect', { class: 'hit', x: M.left, y: M.top, width: w - M.left - M.right, height: H - M.bottom - M.top });
    hit.addEventListener('pointermove', (ev) => {
      const box = svg.getBoundingClientRect();
      const tt = Math.max(0, Math.min(WINDOW_S, x.invert(ev.clientX - box.left)));
      cross.setAttribute('x1', x(tt));
      cross.setAttribute('x2', x(tt));
      cross.setAttribute('visibility', 'visible');
      showTip([
        tipTitle(`t = ${fixed(tt, 1)} s`),
        tipRow(int(at(res.model.series, tt)), 'calls, burst + log-normal', TOPO_COLOR[t]),
        tipRow(int(at(res.poisson.series, tt)), 'calls, Poisson', POISSON, 'dashed'),
      ], ev.clientX, ev.clientY);
    });
    hit.addEventListener('pointerleave', () => { cross.setAttribute('visibility', 'hidden'); hideTip(); });
    g.append(hit);
    svg.append(g);
    el.replaceChildren(svg);
  });
}

function drawSweep(el, rows, K, t) {
  return responsive(el, (w) => {
    const M = { top: 12, right: 64, bottom: 36, left: 42 };
    const H = 200;
    const svg = svgRoot(w, H, 'Server slots needed so that at most 5% of calls wait, by number of workflows');
    const g = s('g');
    const x = linear([0, 50], [M.left, w - M.right]);
    const top = niceMax(Math.max(...rows.map((r) => Math.max(r.model, r.poisson))));
    const y = linear([0, top], [H - M.bottom, M.top]);
    axisLeft(g, y, M.left, { ticks: y.ticks(4), gridRight: w - M.right, format: (v) => int(v) });
    axisBottom(g, x, H - M.bottom, { ticks: [1, 10, 20, 30, 40, 50], format: String, title: 'workflows at once (K)', titleY: 32 });
    g.append(s('line', { class: 'annot-line', x1: x(K), x2: x(K), y1: M.top, y2: H - M.bottom }));
    const series = [
      { key: 'poisson', label: 'Poisson', color: POISSON, cls: 'tr-step tr-step--poisson' },
      { key: 'model', label: 'Model', color: TOPO_COLOR[t], cls: 'tr-step' },
    ];
    const ends = [];
    for (const sr of series) {
      g.append(s('polyline', { class: sr.cls, stroke: sr.color, points: rows.map((r) => `${x(r.K)},${y(r[sr.key])}`).join(' ') }));
      rows.forEach((r) => g.append(s('circle', { class: 'tr-ours', cx: x(r.K), cy: y(r[sr.key]), r: 3.5, fill: sr.color })));
      ends.push({ label: sr.label, y: y(rows[rows.length - 1][sr.key]) });
    }
    ends.sort((a, b) => a.y - b.y);
    if (ends[1].y - ends[0].y < 12) ends[1].y = ends[0].y + 12;
    ends.forEach((e) => g.append(s('text', { class: 'annot', x: x(50) + 8, y: e.y + 4, text: e.label })));
    rows.forEach((r, i) => {
      const prev = i ? x(rows[i - 1].K) : M.left;
      const next = i < rows.length - 1 ? x(rows[i + 1].K) : w - M.right;
      const x0 = (prev + x(r.K)) / 2;
      const x1 = (x(r.K) + next) / 2;
      const hit = s('rect', { class: 'hit', x: i ? x0 : M.left, y: M.top, width: (i < rows.length - 1 ? x1 : w - M.right) - (i ? x0 : M.left), height: H - M.bottom - M.top });
      hit.addEventListener('pointermove', (ev) => showTip([
        tipTitle(`K = ${r.K} workflows`),
        tipRow(int(r.model), 'slots, burst + log-normal', TOPO_COLOR[t]),
        tipRow(int(r.poisson), 'slots, Poisson', POISSON, 'dashed'),
      ], ev.clientX, ev.clientY));
      hit.addEventListener('pointerleave', hideTip);
      g.append(hit);
    });
    svg.append(g);
    el.replaceChildren(svg);
  });
}

function renderPlayground(T, summary) {
  const state = { t: 'full_mesh', K: 10, head: 0.3, seed: 1 };
  const models = Object.fromEntries(TOPOS.map((t) => [t, topoModel(T, summary, t)]));
  const seg = host('pgTopo');
  seg.replaceChildren(...TOPOS.map((t) => h('button', { type: 'button', role: 'radio', 'aria-checked': String(t === state.t), 'data-topo': t }, [swatch(t), TOPO_LABEL[t]])));
  const kIn = host('pgK');
  const headIn = host('pgHead');
  const tiles = host('pgTiles');
  let timer = null;
  let sweepTimer = null;
  let timelineHandle = null;
  let sweepHandle = null;

  const update = () => {
    const m = models[state.t];
    const meanLoad = state.K * m.meanInflight;
    const C = Math.max(1, Math.ceil(meanLoad * (1 + state.head)));
    host('pgKOut').textContent = String(state.K);
    host('pgHeadOut').textContent = pct(state.head, 0);
    host('pgSlotsOut').textContent = `= ${C} slots`;
    const res = simulate(m, state.K, C, state.seed);
    const M = res.model;
    const Pn = res.poisson;
    const tile = (label, value, sub, key) => h('div', { class: 'tile', 'data-tile': key }, [
      h('div', { class: 'tile-label', text: label }), h('div', { class: 'tile-value', text: value }), h('div', { class: 'tile-sub', text: sub }),
    ]);
    const util = meanLoad / C;
    tiles.replaceChildren(
      tile('Mean load', `${fixed(meanLoad, 1)} calls`, `${int(C)} slots, ${pct(util, 0)} busy on average`, 'load'),
      tile('Peak at the server, p99', int(M.p99), vsPoisson(Pn.p99, M.p99, int), 'p99'),
      tile('Most arrivals in 1 s', int(M.perSecond), vsPoisson(Pn.perSecond, M.perSecond, int), 'arrivals'),
      tile('Calls that wait', pct(M.waited, 0), vsPoisson(Pn.waited, M.waited, (v) => pct(v, 0)), 'waited'),
      tile('Wait, p95', seconds(M.p95wait), vsPoisson(Pn.p95wait, M.p95wait, seconds), 'wait'),
    );
    if (util > 0.95) tiles.append(h('p', { class: 'tr-warn', text: 'At or over capacity: the queue keeps growing, so waits depend on how long the simulation runs.' }));
    host('pgLegend').replaceChildren(
      h('span', {}, [lineKey(TOPO_COLOR[state.t]), `Burst + log-normal model (${TOPO_LABEL[state.t]})`]),
      h('span', {}, [lineKey(POISSON, 'dashed'), 'Poisson, same mean rate']),
      h('span', {}, [lineKey('var(--ink-3)', 'dashed'), 'server slots']),
    );
    timelineHandle?.disconnect();
    timelineHandle = drawTimeline(host('pgTimeline'), res, C, state.t);
    clearTimeout(sweepTimer);
    sweepTimer = setTimeout(() => {
      sweepHandle?.disconnect();
      sweepHandle = drawSweep(host('pgSweep'), sweep(m, state.seed), state.K, state.t);
      document.body.dataset.trafficReady = 'true';
    }, 30);
  };
  const later = () => { clearTimeout(timer); timer = setTimeout(update, 90); };

  const setTopo = (t) => {
    state.t = t;
    seg.querySelectorAll('button').forEach((b) => b.setAttribute('aria-checked', String(b.dataset.topo === t)));
    update();
  };
  seg.querySelectorAll('button').forEach((b) => b.addEventListener('click', () => setTopo(b.dataset.topo)));
  seg.addEventListener('keydown', (ev) => {
    if (!['ArrowLeft', 'ArrowRight'].includes(ev.key)) return;
    const i = TOPOS.indexOf(state.t) + (ev.key === 'ArrowRight' ? 1 : -1);
    const t = TOPOS[(i + TOPOS.length) % TOPOS.length];
    setTopo(t);
    seg.querySelector(`[data-topo="${t}"]`).focus();
    ev.preventDefault();
  });
  kIn.addEventListener('input', () => { state.K = Number(kIn.value); host('pgKOut').textContent = kIn.value; later(); });
  headIn.addEventListener('input', () => { state.head = Number(headIn.value) / 100; host('pgHeadOut').textContent = `${headIn.value}%`; later(); });
  host('pgResample').addEventListener('click', () => { state.seed += 1; update(); });
  update();

  const P = T.playground;
  const trio = (f) => TOPOS.map((t) => f(P[t])).join(' / ');
  host('pgNotes').replaceChildren(
    h('p', { text: `Each workflow sends bursts whose sizes follow the measured distribution, separated by gaps drawn from the paper’s log-normal fit (fit table on Traffic patterns). Every call holds one server slot for a duration drawn from the measured discussion calls. Calls queue first in, first out when every slot is busy. Poisson: single calls with exponential gaps at the same mean rate and the same durations, so the mean load is identical. Slots are the mean load plus the headroom, rounded up. ${int(HORIZON_S / 60)} simulated minutes per setting.` }),
    h('p', { text: `Model check: one workflow gives a mean load of ${trio((p) => fixed(p.model_mean_inflight, 2))} calls in flight (Sequential / Star / Full mesh); the runs measured ${trio((p) => fixed(p.measured_mean_inflight, 2))}. Full mesh is overstated because its refills wait for replies, which an open-loop model cannot know; for the same reason one simulated workflow can exceed the true peaks of 1 / 3 / 5.` }),
    h('p', { text: 'Sequential is more regular than Poisson (log-normal σ = 0.31), so Poisson overstates its peaks. For Star and Full mesh, Poisson understates the peaks, the arrivals per second and the queueing.' }),
  );
}

// ---------------------------------------------------------------------------

async function main() {
  if (!host('bursts') && !host('playground')) return;
  let T;
  let summary;
  try {
    [T, summary] = await Promise.all([loadData('traffic.json'), loadSummary()]);
  } catch (err) {
    console.error('[traffic] could not load data:', err);
    for (const id of ['burstSizes', 'gapCharts', 'robCharts', 'pgTiles']) {
      host(id)?.replaceChildren(h('p', { class: 'placeholder', text: `Could not load traffic.json (${err.message}). Run scripts/demo/analysis_traffic.py.` }));
    }
    return;
  }
  guard('burstSizes', (el) => drawBurstSizes(el, T));
  guard('onOff', (el) => drawOnOff(el, T));
  guard('burstTable', (el) => burstTable(el, T));
  guard('gapCharts', (el) => drawGaps(el, T, summary));
  guard('robCharts', (el) => drawRobustness(el, T));
  scrollToAnchor();
  // the playground marks the page ready once its sweep is drawn
  if (!guard('pgTiles', () => renderPlayground(T, summary))) document.body.dataset.trafficReady = 'true';
}

main();
