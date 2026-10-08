/**
 * IAT distributions per topology: log-x histograms (% of the topology's discussion IATs per
 * 1/8-decade bin, or per 0.25 s bin on the linear scale) with the paper's log-normal /
 * exponential / Weibull fits overlaid, and the
 * KS / AIC table (Traffic page). Also exports the histogram panel for the agent-count scaling
 * section and the small IAT histograms of the Overview page.
 */

import {
  h, s, svgRoot, log10, linear, axisBottom, axisLeft, barPath, niceMax, niceTicks, logTimeLabel, responsive,
  showTip, hideTip, tipTitle, tipRow, TOPOS, TOPO_LABEL, TOPO_COLOR, swatch,
  fixed, int, pct, seconds, dataTable,
} from './util.js';
import { resultsHref } from './shell.js';
import { addFullscreen } from './fullscreen.js';
import { effectiveDomain, attachBrush, logTicks, onRange, zoomBar, countInRange } from './zoom.js';

export const X_DOMAIN = [1e-4, 300];
const BINS_PER_DECADE = 8;
const NEUTRAL = 'var(--neutral-mark)'; // bars outside the fit sample
const FITS = ['lognormal', 'exponential', 'weibull'];
const FIT_LABEL = { lognormal: 'Log-normal', exponential: 'Exponential', weibull: 'Weibull' };
const FIT_STROKE = { lognormal: 'var(--fit-lognormal)', exponential: 'var(--fit-exponential)', weibull: 'var(--fit-weibull)' };
const FIT_DASH = { lognormal: null, exponential: 'dashed', weibull: 'dotted' };
const shown = new Set(FITS);
const LIN_DOMAIN = [0, 30]; // linear view: summary.iat.linear_bins_s (0.25 s bins)
let xScale = 'log'; // 'log' | 'linear', IAT section toggle
const iatCharts = []; // responsive handles of the IAT panels, re-rendered on toggle

/** x * pdf(x): the density per unit ln(x), so expected count in a log bin = n * xf(x) * ln(10)/8. */
const XPDF = {
  lognormal: ({ mu, sigma }) => (x) => {
    const z = (Math.log(x) - mu) / sigma;
    return Math.exp(-0.5 * z * z) / (sigma * Math.sqrt(2 * Math.PI));
  },
  exponential: ({ lambda }) => (x) => lambda * x * Math.exp(-lambda * x),
  weibull: ({ shape, scale_s: scale }) => (x) => {
    const u = (x / scale) ** shape;
    return shape * u * Math.exp(-u);
  },
};
const binWidthLn = Math.LN10 / BINS_PER_DECADE;

/**
 * One histogram panel.
 *  hist: { n, counts, fit_counts?, burst_fraction }
 *  fit:  summary.iat.fits[topo] or null; curves: [{ key, xpdf, range }]
 */
function drawHistogram(host, width, { bins, hist, color, yMax, curves = [], label, annotate = null, fixedCurves = false, scale = 'log', linBins = null, yMaxLin = null, compact = false, zoomId = null, height = null }) {
  const visible = (key) => fixedCurves || shown.has(key);
  const isLog = scale !== 'linear';
  const { domain, zoomed } = effectiveDomain('iat', isLog ? X_DOMAIN : LIN_DOMAIN);
  const top = isLog ? yMax : yMaxLin;
  const edges = isLog ? bins : linBins;
  const counts = isLog ? hist.counts : hist.linear_counts;
  const fitCounts = isLog ? hist.fit_counts : hist.linear_fit_counts;
  const linBin = isLog ? 0 : linBins[1] - linBins[0];
  // expected % of the topology's IATs in the bin around xv, from a fitted density
  const expectedPct = (cv, xv) => cv.scale * (isLog ? cv.xpdf(xv) * binWidthLn : (cv.xpdf(xv) / xv) * linBin) * 100;
  const binLabel = (lo, hi) => (isLog ? `${logTimeLabel(lo)} – ${logTimeLabel(hi)}` : `${fixed(lo, 2)} – ${fixed(hi, 2)} s`);
  const narrow = width < 360 || compact;
  const M = compact ? { top: 20, right: 8, bottom: 22, left: 36 } : { top: 22, right: 10, bottom: 38, left: 42 };
  const H = height || (compact ? 130 : narrow ? 200 : 220);
  const svg = svgRoot(width, H, label);
  const x = isLog ? log10(domain, [M.left, width - M.right]) : linear(domain, [M.left, width - M.right]);
  const y = linear([0, top], [H - M.bottom, M.top]);
  const g = s('g');
  svg.append(g);

  // burst zone
  const xb = Math.min(x(0.05), width - M.right);
  if (xb > M.left) {
    g.append(s('rect', { class: 'burst-zone', x: M.left, y: M.top, width: xb - M.left, height: H - M.bottom - M.top }));
    if (domain[1] > 0.05) g.append(s('line', { class: 'annot-line', x1: xb, x2: xb, y1: M.top - 4, y2: H - M.bottom }));
    // log axis: label left of the 50 ms line; linear axis: that line hugs the y axis, so start at the plot edge
    if (!zoomed || xb - M.left > 90) g.append(s('text', { class: 'annot-muted', x: isLog ? xb - 4 : M.left, y: M.top - 8, 'text-anchor': isLog ? 'end' : 'start', text: `< 50 ms: ${pct(hist.burst_fraction)}` }));
  }

  axisLeft(g, y, M.left, { format: (v) => `${fixed(v, 0)}%`, ticks: y.ticks(compact ? 2 : 4), gridRight: width - M.right });
  axisBottom(g, x, H - M.bottom, {
    ticks: isLog ? (zoomed ? logTicks(domain, width) : x.ticks()) : niceTicks(domain[0], domain[1], narrow ? 3 : 6),
    format: isLog
      ? (v) => (narrow && !zoomed && Math.round(Math.log10(v)) % 2 !== 0 ? '' : logTimeLabel(v))
      : (v) => `${+v.toPrecision(3)} s`,
    gridTop: M.top,
    title: compact ? null : `gap between discussion-call starts (${isLog ? 'log' : 'linear'} scale${zoomed ? ', zoomed' : ''})`,
    titleY: 32,
  });

  // bars: fit sample (colour) at the bottom, the rest (neutral) on top
  const pctOf = (c) => (c / hist.n) * 100;
  const bars = s('g');
  const hits = s('g');
  const clipped = s('g');
  for (let i = 0; i < counts.length; i++) {
    const c = counts[i];
    const lo = edges[i];
    const hi = edges[i + 1];
    if (hi <= domain[0] || lo >= domain[1]) continue;
    const x0 = x(Math.max(lo, domain[0]));
    const x1 = x(Math.min(hi, domain[1]));
    const gap = x1 - x0 > 5 ? 1 : 0.5;
    const bw = Math.max(0.5, x1 - x0 - gap);
    if (c > 0) {
      const fc = fitCounts ? fitCounts[i] : c;
      const yTop = y(Math.min(pctOf(c), top));
      const yFit = y(Math.min(pctOf(fc), top));
      if (pctOf(c) > top) {
        // off-scale bin (the burst spike on the linear axis): clip it and print its real height
        clipped.append(s('text', { class: 'annot', x: x0 + bw + 4, y: M.top + 10, text: `${fixed(pctOf(c), 0)}% in the first ${fixed(hi, 2)} s ↑` }));
      }
      if (fc > 0) bars.append(s('path', { d: barPath(x0, yFit, bw, y(0) - yFit, c === fc ? 2 : 0), fill: color }));
      if (c > fc) bars.append(s('path', { d: barPath(x0, yTop, bw, yFit - yTop - (fc > 0 ? 1 : 0), 2), fill: NEUTRAL }));
    }
    const hit = s('rect', { class: 'hit', x: x0, y: M.top, width: x1 - x0, height: H - M.bottom - M.top });
    const tipContent = () => {
      const rows = [tipTitle(binLabel(lo, hi)), tipRow(`${fixed(pctOf(c), 2)}%`, `of IATs (${int(c)})`)];
      if (fitCounts && c) rows.push(tipRow(int(fitCounts[i]), 'in the fit sample', color));
      for (const cv of curves) {
        if (!visible(cv.key)) continue;
        const mid = isLog ? Math.sqrt(lo * hi) : (lo + hi) / 2;
        if (mid < cv.range[0] || mid > cv.range[1]) continue;
        rows.push(tipRow(`${fixed(expectedPct(cv, mid), 2)}%`, `${FIT_LABEL[cv.key]} fit`, FIT_STROKE[cv.key], FIT_DASH[cv.key]));
      }
      return rows;
    };
    hit.addEventListener('pointermove', (ev) => showTip(tipContent(), ev.clientX, ev.clientY));
    hit.addEventListener('pointerleave', hideTip);
    hits.append(hit);
  }
  g.append(bars, clipped);
  if (!isLog && hist.linear_overflow && domain[1] >= LIN_DOMAIN[1]) {
    g.append(s('text', { class: 'annot-muted', x: width - M.right, y: M.top - 8, 'text-anchor': 'end', text: `+${int(hist.linear_overflow)} beyond ${LIN_DOMAIN[1]} s` }));
  }

  // fit curves (sampled on a fine log grid inside the fitted range)
  const curveG = s('g');
  for (const cv of curves) {
    const pts = [];
    const a0 = Math.max(cv.range[0], domain[0], isLog ? X_DOMAIN[0] : 1e-3);
    const a1 = Math.min(cv.range[1], domain[1]);
    if (!(a1 > a0)) continue;
    for (let k = 0; k <= 160; k++) {
      const xv = isLog ? 10 ** (Math.log10(a0) + ((Math.log10(a1) - Math.log10(a0)) * k) / 160) : a0 + ((a1 - a0) * k) / 160;
      const yv = Math.min(top, expectedPct(cv, xv));
      pts.push(`${x(xv).toFixed(1)},${y(yv).toFixed(1)}`);
    }
    curveG.append(s('polyline', { class: `fit fit--${cv.key}`, points: pts.join(' '), 'data-fit': fixedCurves ? null : cv.key, display: visible(cv.key) ? null : 'none' }));
  }
  g.append(curveG);
  if (annotate && isLog && !zoomed) annotate(g, x, y, M, H, width);
  g.append(hits);
  if (zoomId) {
    attachBrush(svg, {
      id: zoomId, axis: 'iat', mode: isLog ? 'log' : 'linear', full: isLog ? X_DOMAIN : LIN_DOMAIN, current: domain,
      plot: { left: M.left, right: width - M.right, top: M.top, bottom: H - M.bottom }, toValue: x.invert,
    });
  }
  host.replaceChildren(svg);
}

/** Overview: one small log-axis histogram per topology (no fits), each linking to the Traffic page. */
export function renderIatThumbs(summary) {
  const { bins_s: bins, per_topology: per } = summary.iat;
  const yMax = niceMax(Math.max(...TOPOS.map((t) => Math.max(...per[t].counts) / per[t].n * 100)));
  const host = document.getElementById('iatThumbs');
  const pending = [];
  host.replaceChildren(...TOPOS.map((t) => {
    const chart = h('div', { class: 'chart-body' });
    const link = h('a', {
      class: 'thumb', 'data-topology': t, 'data-results-link': 'traffic#iat', href: resultsHref('traffic', '#iat'),
      'aria-label': `${TOPO_LABEL[t]}: ${pct(per[t].burst_fraction)} of gaps under 50 ms. Open the IAT charts on the Traffic page`,
    }, [
      h('h3', {}, [swatch(t), TOPO_LABEL[t], h('span', { class: 'thumb__go', 'aria-hidden': 'true', text: '→' })]),
      chart,
    ]);
    pending.push(() => responsive(chart, (w) => drawHistogram(chart, w, {
      bins, hist: per[t], color: TOPO_COLOR[t], yMax, compact: true,
      label: `${TOPO_LABEL[t]} discussion IAT histogram`,
    })));
    return link;
  }));
  pending.forEach((draw) => draw());
}

function binsTable(summary) {
  const bins = summary.iat.bins_s;
  const per = summary.iat.per_topology;
  const rows = [];
  for (let i = 0; i < bins.length - 1; i++) {
    if (!TOPOS.some((t) => per[t].counts[i])) continue;
    rows.push([`${logTimeLabel(bins[i])} – ${logTimeLabel(bins[i + 1])}`, ...TOPOS.map((t) => `${int(per[t].counts[i])} (${fixed((per[t].counts[i] / per[t].n) * 100, 1)}%)`)]);
  }
  return dataTable(['IAT bin', ...TOPOS.map((t) => TOPO_LABEL[t])], rows, { caption: 'IAT histogram counts per topology', numeric: [1, 2, 3] });
}

export function renderIat(summary) {
  const { bins_s: bins, per_topology: per, fits } = summary.iat;
  // linear view: scale to the tallest bin after the first (the burst spike is clipped and labelled)
  const linBins = summary.iat.linear_bins_s;
  // y scales follow the visible range (all three charts share one scale)
  const yMaxFor = (edges, key, lo, hi, skipFirst) => {
    let top = 0;
    TOPOS.forEach((t) => {
      const n = per[t].n;
      const idx = [];
      for (let i = 0; i < edges.length - 1; i++) if (edges[i + 1] > lo && edges[i] < hi) idx.push(i);
      const use = skipFirst && idx.length > 1 ? idx.filter((i) => i > 0) : idx;
      for (const i of use) top = Math.max(top, (per[t][key][i] / n) * 100);
    });
    return niceMax(skipFirst ? top * 1.05 : top);
  };
  const yMaxes = (scale) => {
    const { domain } = effectiveDomain('iat', scale === 'linear' ? LIN_DOMAIN : X_DOMAIN);
    return { yMax: yMaxFor(bins, 'counts', ...domain, false), yMaxLin: yMaxFor(linBins, 'linear_counts', ...domain, true) };
  };
  const host = document.getElementById('iatCharts');
  iatCharts.length = 0;
  const pending = [];
  const fullscreens = [];
  let setScaleRef = () => {};
  const panels = TOPOS.map((t) => {
    const fit = fits[t];
    const p = per[t];
    const sub = t === 'full_mesh'
      ? 'Waves of 5: a round’s 12 messages go out 5 at a time; the rest start as workers free up.'
      : t === 'vertical'
        ? 'Three reviewers dispatched together: two near-zero gaps per round.'
        : 'One call at a time: every gap is a full LLM call.';
    const chart = h('div', { class: 'chart-body' });
    const panel = h('figure', { class: 'chart', 'data-topology': t }, [
      h('h3', {}, [swatch(t), TOPO_LABEL[t]]),
      h('p', { class: 'chart-sub' }, [
        `${int(p.n)} IATs from ${int(p.n_runs)} runs · median ${seconds(p.median_s)} · fit on ${int(fit.n)}${fit.fraction_of_iats == null ? '' : ` (${pct(fit.fraction_of_iats, 0)})`}. `,
        sub,
      ]),
      chart,
    ]);
    const curves = FITS.map((key) => ({
      key,
      xpdf: XPDF[key](fit[key]),
      range: fit.range_s,
      scale: (fit.sample ? fit.sample.n : fit.n) / p.n,
    }));
    const annotate = t !== 'full_mesh' ? null : (g, x, y, M) => {
      // bracket over the worker-refill gaps
      const x0 = x(0.1), x1 = x(1.2);
      const yy = M.top + 10;
      g.append(s('path', { class: 'annot-line', d: `M${x0},${yy + 5}V${yy}H${x1}V${yy + 5}`, fill: 'none' }));
      g.append(s('text', { class: 'annot', x: (x0 + x1) / 2, y: yy - 3, 'text-anchor': 'middle', text: 'waves of 5' }));
    };
    const histOpts = (extra) => ({
      bins, hist: p, color: TOPO_COLOR[t], ...yMaxes(xScale), curves, scale: xScale, linBins,
      label: `${TOPO_LABEL[t]} discussion IAT histogram with fitted distributions`,
      annotate, ...extra,
    });
    pending.push(() => iatCharts.push(responsive(chart, (w) => drawHistogram(chart, w, histOpts({ zoomId: `iat:${t}` })))));
    // full-screen view: the same drawing at the overlay's size, with its own copy of the axis toggle
    fullscreens.push(addFullscreen(panel, {
      title: `${TOPO_LABEL[t]} distribution`,
      subtitle: `${int(p.n)} IATs from ${int(p.n_runs)} runs · median ${seconds(p.median_s)}. Curves: fitted density × fit sample size.`,
      draw: (el, w, ht) => drawHistogram(el, w, histOpts({ height: Math.max(240, ht - 4) })),
      controls: (bar) => {
        const seg = h('div', { class: 'segmented', role: 'radiogroup', 'aria-label': 'X-axis scale (full screen view)' },
          ['log', 'linear'].map((v) => h('button', { type: 'button', role: 'radio', 'aria-checked': String(xScale === v), 'data-scale': v, text: v === 'log' ? 'Log' : 'Linear' })));
        seg.addEventListener('click', (ev) => { const b = ev.target.closest('button'); if (b) setScaleRef(b.dataset.scale); });
        bar.append(h('span', { class: 'controls__label', text: 'X axis' }), seg);
        bar.append(h('span', { class: 'fs-legend' }, [
          ...FITS.map((k) => h('span', { class: 'fs-legend__item' }, [h('span', { class: `key key--${k}`, 'aria-hidden': 'true' }), FIT_LABEL[k]])),
          h('span', { class: 'fs-legend__item' }, [h('span', { class: 'swatch', style: `background:${TOPO_COLOR[t]}`, 'aria-hidden': 'true' }), 'fit sample']),
          h('span', { class: 'fs-legend__item' }, [h('span', { class: 'swatch swatch--neutral', 'aria-hidden': 'true' }), 'not fitted']),
        ]));
      },
    }));
    return panel;
  });
  host.replaceChildren(...panels);
  pending.forEach((draw) => draw()); // after insertion, so the panels have a width

  // shared range: the same selection drives the burst-removed gap charts (traffic.js)
  const zoomHost = h('div');
  host.before(zoomHost);
  zoomBar(zoomHost, {
    axis: 'iat',
    hint: 'Drag on a chart to zoom into a range of gap length (inter-arrival time); every chart below follows it.',
    describe: ([a, b]) => `${logTimeLabel(a)} to ${logTimeLabel(b)} of inter-arrival time (all topologies, and the burst-removed gap charts)`,
    readout: (r) => TOPOS.map((t) => {
      const c = countInRange(bins, per[t].counts, r);
      return { topo: t, text: `${pct(c / per[t].n)} of gaps (about ${int(c)} of ${int(per[t].n)})` };
    }),
    note: 'The range selects gap lengths, not a stretch of time.',
  });
  onRange('iat', () => { iatCharts.forEach((c) => c.rerender()); fullscreens.forEach((f) => f.refresh()); });

  const scaleSeg = document.getElementById('iatScale');
  const setScale = (value) => {
    xScale = value;
    scaleSeg.querySelectorAll('button').forEach((b) => b.setAttribute('aria-checked', String(b.dataset.scale === value)));
    iatCharts.forEach((c) => c.rerender());
    document.querySelectorAll('.fs-dialog .segmented button').forEach((b) => b.setAttribute('aria-checked', String(b.dataset.scale === value)));
    fullscreens.forEach((f) => f.refresh()); // the open full-screen view, if any
  };
  setScaleRef = setScale;
  scaleSeg.querySelectorAll('button').forEach((b) => b.addEventListener('click', () => setScale(b.dataset.scale)));
  scaleSeg.addEventListener('keydown', (ev) => {
    if (!['ArrowLeft', 'ArrowRight'].includes(ev.key)) return;
    const next = xScale === 'log' ? 'linear' : 'log';
    setScale(next);
    scaleSeg.querySelector(`[data-scale="${next}"]`).focus();
    ev.preventDefault();
  });

  document.querySelectorAll('#iat [data-fit]').forEach((box) => {
    if (box.tagName !== 'INPUT') return;
    box.addEventListener('change', () => {
      if (box.checked) shown.add(box.dataset.fit); else shown.delete(box.dataset.fit);
      document.querySelectorAll(`#iatCharts polyline[data-fit="${box.dataset.fit}"]`).forEach((pl) => {
        if (box.checked) pl.removeAttribute('display'); else pl.setAttribute('display', 'none');
      });
    });
  });

  const n = summary.source.n_runs;
  document.getElementById('iatSource').replaceChildren(
    'Bars: share of gaps per bin, same scale in all three. Coloured: the gaps used for the fit; grey: bursts and outliers. Curves: the fitted distributions.',
    h('details', { class: 'explain' }, [h('summary', { text: 'Histogram data table' }), h('div', { class: 'table-wrap' }, binsTable(summary))]),
  );

  renderFitTable(summary);
}

function renderFitTable(summary) {
  const fits = summary.iat.fits;
  const table = h('table', { class: 'data' });
  table.append(h('caption', { class: 'visually-hidden', text: 'Goodness of fit per topology and distribution' }));
  table.append(h('thead', {}, h('tr', {}, [
    h('th', { scope: 'col', text: 'Topology' }),
    h('th', { scope: 'col', text: 'Distribution' }),
    h('th', { scope: 'col', class: 'hide-sm', text: 'Parameters' }),
    h('th', { scope: 'col', class: 'num', text: 'KS D' }),
    h('th', { scope: 'col', class: 'num hide-sm', text: 'KS p' }),
    h('th', { scope: 'col', class: 'num', text: 'AIC' }),
    h('th', { scope: 'col', class: 'num', text: 'ΔAIC' }),
  ])));
  const body = h('tbody');
  for (const t of TOPOS) {
    const f = fits[t];
    const minAic = Math.min(...FITS.map((k) => f[k].aic));
    FITS.forEach((k, i) => {
      const p = f[k];
      const params = k === 'lognormal' ? `μ = ${fixed(p.mu, 3)}, σ = ${fixed(p.sigma, 3)} (median ${seconds(p.median_s)})`
        : k === 'exponential' ? `λ = ${fixed(p.lambda, 3)}/s (mean ${seconds(p.mean_s)})`
          : `k = ${fixed(p.shape, 3)}, scale ${seconds(p.scale_s)}`;
      const bestKs = f.best_ks === k;
      const bestAic = f.best_aic === k;
      const pv = p.p_value === 0 ? '< 1e-300' : p.p_value.toExponential(1);
      body.append(h('tr', {}, [
        i === 0 ? h('th', { scope: 'rowgroup', rowspan: 3 }, [swatch(t), TOPO_LABEL[t], h('br'), h('span', { class: 'pct', text: `n = ${int(f.n)}` })]) : null,
        h('td', {}, [h('span', { class: `key key--${k}`, 'aria-hidden': 'true', style: 'margin-right:6px' }), FIT_LABEL[k],
          h('span', { class: 'show-sm pct', 'aria-hidden': 'true', text: params })]),
        h('td', { class: 'hide-sm', text: params }),
        h('td', { class: `num ${bestKs ? 'best' : ''}` }, [fixed(p.ks, 3), bestKs ? h('span', { class: 'visually-hidden', text: ' (lowest)' }) : null]),
        h('td', { class: 'num hide-sm', text: pv }),
        h('td', { class: `num ${bestAic ? 'best' : ''}` }, [int(p.aic), bestAic ? h('span', { class: 'visually-hidden', text: ' (lowest)' }) : null]),
        h('td', { class: 'num', text: p.aic === minAic ? '0' : `+${int(p.aic - minAic)}` }),
      ]));
    });
  }
  table.append(body);
  document.getElementById('iatTable').replaceChildren(table);

  document.getElementById('iatNotes').replaceChildren(
    h('p', { text: 'Bold: the lowest KS statistic and AIC per topology. Log-normal has the lowest AIC everywhere; for Full mesh, Weibull has a slightly lower KS statistic. The exponential (Poisson arrivals) is the worst fit in every case.' }),
    h('p', { text: 'Fitted by maximum likelihood to the gaps above 50 ms, outliers removed. With thousands of gaps every fit fails the KS test formally, so compare the statistics rather than the p-values.' }),
  );
}

// ---------------------------------------------------------------------------
// Agent-count scaling panels (reused by breakdown.js)
// ---------------------------------------------------------------------------

export function renderScalingHistograms(host, summary) {
  const bins = summary.iat.bins_s;
  const agents = summary.scaling.agents;
  const pending = [];
  const handles = [];
  const fullscreens = [];
  // one y scale over the bins inside the zoomed range
  const yMaxNow = () => {
    const [lo, hi] = effectiveDomain('iat', X_DOMAIN).domain;
    let top = 0;
    for (const a of agents) a.counts.forEach((c, i) => { if (bins[i + 1] > lo && bins[i] < hi) top = Math.max(top, (c / a.n) * 100); });
    return niceMax(top);
  };
  host.replaceChildren(...agents.map((a) => {
    const chart = h('div', { class: 'chart-body' });
    const pairs = a.n_agents * (a.n_agents - 1);
    const fig = h('figure', { class: 'chart', 'data-agents': a.n_agents }, [
      h('h3', {}, [swatch('full_mesh'), `${a.n_agents} agents`]),
      h('p', { class: 'chart-sub', text: `${int(a.n_runs)} runs · ${int(a.n)} IATs · ${pairs} messages per round · median ${seconds(a.median_s)}` }),
      chart,
    ]);
    const ln = a.lognormal_reasoning;
    const nReason = ln.n;
    const curves = [{ key: 'lognormal', xpdf: XPDF.lognormal(ln), range: [0.05, X_DOMAIN[1]], scale: nReason / a.n }];
    const histOpts = (extra) => ({
      bins, hist: { n: a.n, counts: a.counts, burst_fraction: a.burst_fraction }, color: TOPO_COLOR.full_mesh, yMax: yMaxNow(), curves,
      label: `Full mesh with ${a.n_agents} agents: discussion IAT histogram`,
      fixedCurves: true, ...extra,
    });
    pending.push(() => handles.push(responsive(chart, (w) => drawHistogram(chart, w, histOpts({ zoomId: `scaling:${a.n_agents}` })))));
    fullscreens.push(addFullscreen(fig, {
      title: `Full mesh, ${a.n_agents} agents: distribution`,
      subtitle: `${int(a.n_runs)} runs · ${int(a.n)} IATs · median ${seconds(a.median_s)}. Curve: log-normal fit to the reasoning-mode gaps (over 50 ms) × its sample size.`,
      draw: (el, w, ht) => drawHistogram(el, w, histOpts({ height: Math.max(240, ht - 4) })),
    }));
    return fig;
  }));
  pending.forEach((draw) => draw());

  // the same shared IAT range as the histograms and gap charts above
  const zoomHost = h('div');
  host.before(zoomHost);
  zoomBar(zoomHost, {
    axis: 'iat',
    hint: 'Drag on a chart to zoom into a range of gap length (shared with the other IAT charts on this page).',
    describe: ([lo, hi]) => `${logTimeLabel(lo)} to ${logTimeLabel(hi)} of inter-arrival time`,
    readout: (r) => agents.map((a) => {
      const c = countInRange(bins, a.counts, r);
      return { label: `${a.n_agents} agents`, text: `${pct(c / a.n)} of gaps (about ${int(c)} of ${int(a.n)})` };
    }),
  });
  onRange('iat', () => { handles.forEach((c) => c.rerender()); fullscreens.forEach((f) => f.refresh()); });
}
