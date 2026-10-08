/**
 * System page, at the model server and on the network.
 * Loaded by results/system-load/ and results/beta/ (#contention) and, through breakdown.js (renderNetwork), by main.js.
 *
 *   #network       flow diagram of TCP bytes between components (summary.json aggregates;
 *                  drawn synchronously by main.js, so it exists once the page is ready)
 *   #concurrency   calls in flight: share of discussion time per level, mean and true peak
 *   #contention    latency, output tokens, time per token and queue wait vs calls in flight
 *   #comparisons   median of every metric per topology, with the change from Sequential
 *
 * The last three read load.json of the active data set (ui/data/, scripts/demo/analysis_load.py), fetched on page open.
 */

import {
  h, s, svgRoot, linear, axisLeft, niceMax, responsive, showTip, showTipAt, hideTip,
  tipTitle, tipRow, tipNote, dataTable, formatMetric, diverging, inkOn, barPath,
  TOPOS, TOPO_LABEL, TOPO_COLOR, swatch, fixed, int, pct, seconds, compact, loadData, loadSummary,
} from './util.js';
import { onThemeChange } from '../../common/js/theme.js';

const SHORT = { horizontal: 'Seq.', vertical: 'Star', full_mesh: 'Mesh' };
const LAYER_LABEL = { application: 'Application', llm: 'LLM backend', traffic: 'Traffic', network: 'Network' };
const bps = (v) => (v >= 1000 ? `${fixed(v / 1000, 2)} kB/s` : `${int(v)} B/s`);
const msOf = (sec) => `${int(sec * 1000)} ms`;
const trim = (v) => String(+v.toFixed(2));

function tipOn(el, content) {
  el.addEventListener('pointermove', (ev) => showTip(content(), ev.clientX, ev.clientY));
  el.addEventListener('pointerleave', hideTip);
  el.addEventListener('focus', () => showTipAt(content(), el));
  el.addEventListener('blur', hideTip);
}

// ---------------------------------------------------------------------------
// Network flows (summary.json)
// ---------------------------------------------------------------------------

const FLOWS = [
  { key: 'tcp_bytes_a_to_llm_mean_Bps', label: 'Agent A → LLM', what: 'requests from the orchestrator' },
  { key: 'tcp_bytes_b_to_llm_mean_Bps', label: 'Agent B → LLM', what: 'requests from the experts (summed over the B instances)' },
  { key: 'tcp_bytes_a_to_b_mean_Bps', label: 'Agent A → Agent B', what: 'tasks and messages relayed to the experts (summed)' },
  { key: 'tcp_bytes_llm_mean_Bps', label: 'LLM → agents', what: 'responses from the model server (Table 2’s LLM TCP byte rate)' },
];

/** A straight band from p0 to p1, `w` wide, with an arrowhead ending at p1. */
function arrowBand([x0, y0], [x1, y1], w) {
  const len = Math.hypot(x1 - x0, y1 - y0);
  const dx = (x1 - x0) / len, dy = (y1 - y0) / len;
  const nx = -dy, ny = dx;
  const head = Math.min(10, len / 3);
  const hw = w / 2, hh = w / 2 + 4;
  const qx = x1 - dx * head, qy = y1 - dy * head;
  const pts = [
    [x0 + nx * hw, y0 + ny * hw], [qx + nx * hw, qy + ny * hw], [qx + nx * hh, qy + ny * hh], [x1, y1],
    [qx - nx * hh, qy - ny * hh], [qx - nx * hw, qy - ny * hw], [x0 - nx * hw, y0 - ny * hw],
  ];
  return `M${pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join('L')}Z`;
}

function node(g, x, y, w, hgt, title, sub) {
  g.append(s('rect', { class: 'flow-node', x, y, width: w, height: hgt, rx: 6 }));
  g.append(s('text', { class: 'flow-node__t', x: x + w / 2, y: y + hgt / 2 - (sub ? 2 : -4), 'text-anchor': 'middle', text: title }));
  if (sub) g.append(s('text', { class: 'flow-node__s', x: x + w / 2, y: y + hgt / 2 + 11, 'text-anchor': 'middle', text: sub }));
}

function drawFlowPanel(host, width, topo, agg, maxV) {
  const H = 214;
  const nodeW = Math.max(72, Math.min(96, width * 0.27));
  const A = { x: 2, y: 10, h: 38 };
  const B = { x: 2, y: H - 48, h: 38 };
  const L = { x: width - nodeW - 2, y: 66, h: 82 };
  const cx = A.x + nodeW / 2;
  const maxW = 20;
  const wOf = (v) => Math.max(1.5, (v / maxV) * maxW);
  const v = Object.fromEntries(FLOWS.map((f) => [f.key, agg[topo][f.key]]));
  const svg = svgRoot(width, H, `${TOPO_LABEL[topo]}: median TCP byte rate between Agent A, the Agent B instances and the LLM backend`);
  const g = s('g');
  svg.append(g);
  const color = TOPO_COLOR[topo];
  const wRet = wOf(v.tcp_bytes_llm_mean_Bps.median);
  const wAB = wOf(v.tcp_bytes_a_to_b_mean_Bps.median);
  const geo = {
    tcp_bytes_a_to_llm_mean_Bps: { p0: [A.x + nodeW, A.y + A.h / 2], p1: [L.x, L.y + 14] },
    tcp_bytes_b_to_llm_mean_Bps: { p0: [A.x + nodeW, B.y + B.h / 2], p1: [L.x, L.y + L.h - 14] },
    tcp_bytes_a_to_b_mean_Bps: { p0: [cx, A.y + A.h], p1: [cx, B.y] },
    tcp_bytes_llm_mean_Bps: { p0: [L.x, L.y + L.h / 2], p1: [cx + wAB / 2 + 8, L.y + L.h / 2], ret: true },
  };
  for (const f of FLOWS) {
    const a = v[f.key];
    const { p0, p1, ret } = geo[f.key];
    const w = wOf(a.median);
    const band = s('path', {
      d: arrowBand(p0, p1, w), fill: color, 'fill-opacity': ret ? 0.45 : 0.85,
      class: 'flow-band', tabindex: 0, role: 'img', 'aria-label': `${f.label}: median ${bps(a.median)}`,
    });
    tipOn(band, () => [
      tipTitle(`${f.label} · ${TOPO_LABEL[topo]}`),
      tipRow(bps(a.median), 'median run', color),
      tipRow(`${bps(a.p25)} – ${bps(a.p75)}`, 'interquartile range'),
      tipRow(bps(a.mean), 'mean'),
      tipNote(`${f.what}; ${int(a.n)} runs`),
    ]);
    g.append(band);
  }
  node(g, A.x, A.y, nodeW, A.h, 'Agent A', 'orchestrator');
  node(g, B.x, B.y, nodeW, B.h, 'Agent B ×4', 'experts');
  node(g, L.x, L.y, nodeW, L.h, 'LLM', 'vLLM backend');
  // value labels, one per band, in text ink (the band carries the colour)
  const mid = (k) => { const { p0, p1 } = geo[k]; return [(p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2]; };
  const label = (x, y, text, anchor = 'middle') => g.append(s('text', { class: 'flow-value', x, y, 'text-anchor': anchor, text }));
  const [ax, ay] = mid('tcp_bytes_a_to_llm_mean_Bps');
  label(ax + 6, ay - wOf(v.tcp_bytes_a_to_llm_mean_Bps.median) / 2 - 7, bps(v.tcp_bytes_a_to_llm_mean_Bps.median));
  const [bx, by] = mid('tcp_bytes_b_to_llm_mean_Bps');
  label(bx + 6, by + wOf(v.tcp_bytes_b_to_llm_mean_Bps.median) / 2 + 15, bps(v.tcp_bytes_b_to_llm_mean_Bps.median));
  label(cx + wAB / 2 + 6, A.y + A.h + 24, bps(v.tcp_bytes_a_to_b_mean_Bps.median), 'start');
  const [rx, ry] = mid('tcp_bytes_llm_mean_Bps');
  label(rx, ry + wRet / 2 + 13, `replies ${bps(v.tcp_bytes_llm_mean_Bps.median)}`);
  host.replaceChildren(svg);
}

/** Replaces the old per-pair bars: called by main.js (via breakdown.js renderNetwork). */
export function renderNetworkFlows(summary) {
  const agg = summary.aggregates.by_topology;
  const maxV = Math.max(...TOPOS.flatMap((t) => FLOWS.map((f) => agg[t][f.key].median)));
  const panels = TOPOS.map((t) => {
    const body = h('div', { class: 'chart-body' });
    const into = agg[t].tcp_bytes_a_to_llm_mean_Bps.median + agg[t].tcp_bytes_b_to_llm_mean_Bps.median;
    const fig = h('figure', { class: 'chart flow-panel', 'data-topology': t }, [
      h('h3', {}, [swatch(t), TOPO_LABEL[t]]),
      h('p', { class: 'chart-sub', text: `Into the model server ${bps(into)}, back out ${bps(agg[t].tcp_bytes_llm_mean_Bps.median)}` }),
      body,
    ]);
    return { t, fig, body };
  });
  document.getElementById('netChart').replaceChildren(h('div', { class: 'multiples multiples--3' }, panels.map((p) => p.fig)));
  panels.forEach((p) => responsive(p.body, (w) => drawFlowPanel(p.body, w, p.t, agg, maxV)));

  const rows = FLOWS.map((f) => [f.label, ...TOPOS.map((t) => {
    const a = agg[t][f.key];
    return `${bps(a.median)} (${bps(a.p25)}–${bps(a.p75)}); mean ${bps(a.mean)}`;
  })]);
  document.getElementById('netTable').replaceChildren(h('details', { class: 'explain' }, [
    h('summary', { text: 'Show as a table' }),
    h('div', { class: 'table-wrap' }, dataTable(['Flow', ...TOPOS.map((t) => TOPO_LABEL[t])], rows, { caption: 'TCP byte rate per flow: median (IQR); mean' })),
  ]));

  const rate = (summary.table2.sections || []).flatMap((sec) => sec.rows || []).find((r) => r.metric === 'Discussion call rate');
  const note = document.getElementById('netNote');
  if (note && rate) {
    const r = (t) => rate.values[t].split(' calls/s')[0];
    const llm = (t) => agg[t].tcp_bytes_llm_mean_Bps.median;
    note.textContent =
      `Sequential and Star make discussion calls at the same rate (${r('horizontal')} and ${r('vertical')} per second), ` +
      `yet in the median run Star’s model server sends ${pct(llm('vertical') / llm('horizontal') - 1, 0)} more bytes per second and full mesh ` +
      `${pct(llm('full_mesh') / llm('horizontal') - 1, 0)} more. An average call rate hides how the load arrives.`;
  }
  document.getElementById('netSource').textContent =
    'Arrow width: the median run’s byte rate, same scale in all panels; hover an arrow for the spread. ' +
    'B→LLM and A→B are summed over the Agent B instances. “Replies” goes to both agents.';
}

// ---------------------------------------------------------------------------
// Concurrency
// ---------------------------------------------------------------------------

function drawConcPanel(host, width, topo, c, levels) {
  const H = 176;
  const M = { top: 24, right: 6, bottom: 36, left: 38 };
  const band = (width - M.left - M.right) / levels;
  const xc = (k) => M.left + band * (k + 0.5);
  const y = linear([0, 1], [H - M.bottom, M.top]);
  const svg = svgRoot(width, H, `${TOPO_LABEL[topo]}: share of discussion time with 0 to ${levels - 1} calls in flight`);
  const g = s('g');
  svg.append(g);
  axisLeft(g, y, M.left, { ticks: [0, 0.25, 0.5, 0.75, 1], format: (v) => `${v * 100}%`, gridRight: width - M.right });
  const bw = Math.min(34, band * 0.62);
  const top = c.time_share.indexOf(Math.max(...c.time_share));
  c.time_share.forEach((share, k) => {
    const x0 = xc(k) - bw / 2;
    if (share > 0) g.append(s('path', { d: barPath(x0, y(share), bw, y(0) - y(share), 4), fill: TOPO_COLOR[topo] }));
    if (k === top) {
      // beside the bar when the mean label would sit on top of it
      const clash = Math.abs(xc(0) + c.mean * band - xc(k)) < 34 && y(share) < M.top + 16;
      g.append(s('text', clash
        ? { class: 'annot', x: xc(k) + bw / 2 + 4, y: y(share) + 12, 'text-anchor': 'start', text: pct(share, 0) }
        : { class: 'annot', x: xc(k), y: y(share) - 5, 'text-anchor': 'middle', text: pct(share, 0) }));
    }
    const hit = s('rect', { class: 'hit', x: xc(k) - band / 2, y: M.top, width: band, height: y(0) - M.top });
    tipOn(hit, () => [
      tipTitle(`${TOPO_LABEL[topo]} · ${k === levels - 1 ? `${k} or more` : k} in flight`),
      tipRow(pct(share, 1), 'of discussion time', TOPO_COLOR[topo]),
    ]);
    g.append(hit);
  });
  g.append(s('line', { class: 'baseline', x1: M.left, x2: width - M.right, y1: y(0), y2: y(0) }));
  const ticks = s('g', { class: 'tick' });
  for (let k = 0; k < levels; k++) ticks.append(s('text', { x: xc(k), y: y(0) + 14, 'text-anchor': 'middle', text: String(k) }));
  g.append(ticks, s('text', { class: 'axis-title', x: (M.left + width - M.right) / 2, y: H - 4, 'text-anchor': 'middle', text: 'calls in flight' }));
  // mean marker on the same (continuous) level axis
  const xm = xc(0) + c.mean * band;
  g.append(s('line', { class: 'conc-mean', x1: xm, x2: xm, y1: M.top - 6, y2: y(0) }));
  const anchor = xm > width - 60 ? 'end' : xm < M.left + 40 ? 'start' : 'middle';
  g.append(s('text', { class: 'annot', x: xm, y: M.top - 10, 'text-anchor': anchor, text: `mean ${fixed(c.mean, 2)}` }));
  host.replaceChildren(svg);
}

function renderConcurrency(load, summary) {
  const conc = load.concurrency;
  const levels = conc[TOPOS[0]].time_share.length;
  const panels = TOPOS.filter((t) => conc[t]).map((t) => {
    const c = conc[t];
    const body = h('div', { class: 'chart-body' });
    const fig = h('figure', { class: 'chart', 'data-topology': t }, [
      h('h3', {}, [swatch(t), TOPO_LABEL[t]]),
      h('p', { class: 'chart-sub' }, [
        'Peak ', h('b', { class: 'conc-peak', text: String(c.true_peak) }),
        ` in every run · mean ${fixed(c.mean, 2)}`,
      ]),
      body,
    ]);
    return { t, fig, body };
  });
  document.getElementById('concChart').replaceChildren(h('div', { class: 'multiples multiples--3' }, panels.map((p) => p.fig)));
  panels.forEach((p) => responsive(p.body, (w) => drawConcPanel(p.body, w, p.t, conc[p.t], levels)));

  const rows = TOPOS.filter((t) => conc[t]).map((t) => {
    const c = conc[t];
    const allRuns = Object.keys(c.true_peak_runs).length === 1;
    return [
      TOPO_LABEL[t], fixed(c.mean, 2), `${fixed(c.mean_quartiles.p25, 2)} – ${fixed(c.mean_quartiles.p75, 2)}`,
      `${c.true_peak}${allRuns ? ' (every run)' : ''}`,
      ...c.time_share.map((v) => pct(v, 1)),
    ];
  });
  document.getElementById('concTable').replaceChildren(h('details', { class: 'explain' }, [
    h('summary', { text: 'Show as a table' }),
    h('div', { class: 'table-wrap' }, dataTable(
      ['Topology', 'Mean', 'IQR of run means', 'Peak', ...Array.from({ length: levels }, (_, k) => `${k === levels - 1 ? `${k}+` : k} in flight`)],
      rows, { caption: 'Discussion-stage concurrency per topology', numeric: [1, 2, 3, 4, 5, 6, 7, 8, 9] },
    )),
  ]));
  document.getElementById('concSource').textContent = '';
}

// ---------------------------------------------------------------------------
// Contention
// ---------------------------------------------------------------------------

const CONT_PANELS = [
  { key: 'latency_s', title: 'Latency', sub: 'server time per call', fmt: seconds, axis: (v) => `${trim(v)} s` },
  { key: 'completion_tokens', title: 'Output tokens', sub: 'completion tokens per call', fmt: (v) => int(v), axis: (v) => compact(v) },
  { key: 'ms_per_token', title: 'Time per output token', sub: 'latency ÷ output tokens', fmt: (v) => `${fixed(v, 1)} ms`, axis: (v) => `${trim(v)} ms` },
  { key: 'queue_wait_s', title: 'Queue wait', sub: 'submission to first token', fmt: msOf, axis: (v) => `${int(v * 1000)} ms` },
];

function drawContPanel(host, width, panel, cont) {
  const H = 196;
  const M = { top: 10, right: 10, bottom: 38, left: 48 };
  const levels = cont.levels;
  const band = (width - M.left - M.right) / levels.length;
  const xc = (i) => M.left + band * (i + 0.5);
  const all = TOPOS.flatMap((t) => cont.per_topology[t]).filter(Boolean).map((b) => b[panel.key]?.p75 ?? 0);
  const y = linear([0, niceMax(Math.max(...all))], [H - M.bottom, M.top]);
  const svg = svgRoot(width, H, `${panel.title}: median and interquartile range by calls in flight at start, per topology`);
  const g = s('g');
  svg.append(g);
  axisLeft(g, y, M.left, { ticks: y.ticks(4), format: panel.axis, gridRight: width - M.right });
  g.append(s('line', { class: 'baseline', x1: M.left, x2: width - M.right, y1: y(0), y2: y(0) }));
  const ticks = s('g', { class: 'tick' });
  levels.forEach((k, i) => ticks.append(s('text', { x: xc(i), y: y(0) + 14, 'text-anchor': 'middle', text: i === levels.length - 1 ? `${k}+` : String(k) })));
  g.append(ticks, s('text', { class: 'axis-title', x: (M.left + width - M.right) / 2, y: H - 6, 'text-anchor': 'middle', text: 'calls in flight when the call started' }));
  const dodge = Math.min(8, band / 5);
  TOPOS.forEach((t, ti) => {
    const bins = cont.per_topology[t];
    const off = (ti - 1) * dodge;
    const color = TOPO_COLOR[t];
    const pts = bins.map((b, i) => (b && b[panel.key] ? [xc(i) + off, y(b[panel.key].median)] : null));
    let run = [];
    const flush = () => { if (run.length > 1) g.append(s('polyline', { class: 'cont-line', points: run.map((p) => p.join(',')).join(' '), stroke: color })); run = []; };
    pts.forEach((p) => { if (p) run.push(p); else flush(); });
    flush();
    bins.forEach((b, i) => {
      if (!b || !b[panel.key]) return;
      const q = b[panel.key];
      const x = xc(i) + off;
      g.append(s('line', { class: 'cont-iqr', x1: x, x2: x, y1: y(q.p25), y2: y(q.p75), stroke: color }));
      g.append(s('circle', { class: 'cont-dot', cx: x, cy: y(q.median), r: 4, fill: color }));
      const hit = s('circle', { class: 'hit', cx: x, cy: y(q.median), r: 11 });
      tipOn(hit, () => [
        tipTitle(`${TOPO_LABEL[t]} · ${b.inflight}${i === levels.length - 1 ? '+' : ''} in flight`),
        tipRow(panel.fmt(q.median), `median ${panel.title.toLowerCase()}`, color),
        tipRow(`${panel.fmt(q.p25)} – ${panel.fmt(q.p75)}`, 'interquartile range'),
        tipNote(`${int(b.calls)} calls`),
      ]);
      g.append(hit);
    });
  });
  host.replaceChildren(svg);
}

function renderContention(load) {
  const cont = load.contention;
  const legend = h('div', { class: 'legend' }, TOPOS.map((t) => h('span', {}, [swatch(t), TOPO_LABEL[t]])));
  const panels = CONT_PANELS.map((p) => {
    const body = h('div', { class: 'chart-body' });
    return { p, body, fig: h('figure', { class: 'chart' }, [h('h3', { text: p.title }), h('p', { class: 'chart-sub', text: p.sub }), body]) };
  });
  document.getElementById('contChart').replaceChildren(legend, h('div', { class: 'multiples load-grid-2' }, panels.map((x) => x.fig)));
  panels.forEach((x) => responsive(x.body, (w) => drawContPanel(x.body, w, x.p, cont)));

  // Finding, from the pooled bins and the discussion-call tail
  const bins = cont.all.filter(Boolean);
  const alone = bins[0];
  const busiest = bins.reduce((a, b) => (b.ms_per_token.median > a.ms_per_token.median ? b : a), alone);
  const d = cont.discussion;
  const worst = TOPOS.filter((t) => d[t]).reduce((a, t) => (d[t].latency_p95_s > d[a].latency_p95_s ? t : a), TOPOS[0]);
  const w = d[worst];
  const share = 1 - w.latency_p95_alone_s / w.latency_p95_s;
  document.getElementById('contFinding').replaceChildren(
    h('strong', { text: `Mostly not. ` }),
    `A call running alone takes ${fixed(alone.ms_per_token.median, 1)} ms per output token; with ${busiest.inflight} in flight it takes ` +
    `${fixed(busiest.ms_per_token.median, 1)} ms (+${pct(busiest.ms_per_token.median / alone.ms_per_token.median - 1, 0)}). ` +
    `${TOPO_LABEL[worst]} has the slowest discussion calls (p95 ${seconds(w.latency_p95_s)}), but at the speed of a lone call its p95 would still be ` +
    `${seconds(w.latency_p95_alone_s)}, so contention accounts for about ${pct(Math.max(0, share), 0)} of the tail. The rest is longer answers: ` +
    `p95 ${int(w.completion_tokens_p95)} output tokens, against ${TOPOS.filter((t) => t !== worst && d[t]).map((t) => `${int(d[t].completion_tokens_p95)} for ${TOPO_LABEL[t]}`).join(' and ')}.`,
  );

  // measures as rows, topologies as columns: four columns fit a phone
  const tops = TOPOS.filter((t) => d[t]);
  const row = (label, f) => [label, ...tops.map((t) => f(d[t]))];
  const rows = [
    row('Latency p50', (x) => seconds(x.latency_p50_s)),
    row('Latency p95', (x) => seconds(x.latency_p95_s)),
    row('p95 at lone-call speed', (x) => seconds(x.latency_p95_alone_s)),
    row('Output tokens p50', (x) => int(x.completion_tokens_p50)),
    row('Output tokens p95', (x) => int(x.completion_tokens_p95)),
    row('Time per output token', (x) => `${fixed(x.ms_per_token_median, 1)} ms`),
    row('Queue wait p50', (x) => msOf(x.queue_wait_p50_s)),
    row('Queue wait p95', (x) => msOf(x.queue_wait_p95_s)),
    row('In flight at start (mean)', (x) => fixed(x.inflight_mean, 2)),
  ];
  const binRows = [];
  for (const t of [...TOPOS, 'all']) {
    (t === 'all' ? cont.all : cont.per_topology[t]).forEach((b) => {
      if (!b) return;
      binRows.push([
        `${t === 'all' ? 'All' : TOPO_LABEL[t]} · ${b.inflight}`, int(b.calls), seconds(b.latency_s.median),
        int(b.completion_tokens.median), `${fixed(b.ms_per_token.median, 2)} ms`, msOf(b.queue_wait_s.median),
      ]);
    });
  }
  document.getElementById('contTable').replaceChildren(
    h('h3', { class: 'subhead', text: 'Discussion calls (Table 2 scope): where the latency tail comes from' }),
    h('div', { class: 'table-wrap' }, dataTable(
      ['Discussion calls', ...tops.map((t) => TOPO_LABEL[t])],
      rows, { caption: 'Discussion-call latency decomposition per topology', numeric: [1, 2, 3] },
    )),
    h('details', { class: 'explain' }, [
      h('summary', { text: 'Show the charts as a table' }),
      h('div', { class: 'table-wrap' }, dataTable(['Topology · in flight', 'Calls', 'Latency', 'Output tokens', 'Time per token', 'Queue wait'], binRows,
        { caption: 'Median per in-flight bin', numeric: [1, 2, 3, 4, 5] })),
    ]),
  );
  document.getElementById('contSource').textContent =
    'In flight: calls already running, plus any started at the same moment. ' +
    'Lone-call speed: the typical time per token and queue wait of calls that ran alone.';
}

// ---------------------------------------------------------------------------
// Topology comparisons
// ---------------------------------------------------------------------------

const signed = (v, d = 2) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${fixed(Math.abs(v), d)}`;
const pFmt = (p) => (p < 0.001 ? '< 0.001' : fixed(p, 3));
const pairName = ([a, b]) => `${TOPO_LABEL[a]} vs ${TOPO_LABEL[b]}`;
const pairShort = ([a, b]) => `${SHORT[a]} vs ${SHORT[b]}`;

/** The change from the Sequential median, as "+12%" (or "n/a" when the baseline is zero). */
function changeFrom(base, v) {
  if (base === 0) return v === 0 ? '0%' : 'n/a';
  const p = Math.round(((v - base) / Math.abs(base)) * 100);
  return `${p > 0 ? '+' : p < 0 ? '−' : ''}${int(Math.abs(p))}%`;
}

function renderComparisonTable(cmp) {
  const table = h('table', { class: 'data cmp-table' });
  table.append(h('caption', { class: 'visually-hidden', text: 'Median of every metric per topology, with the change from Sequential' }));
  table.append(h('thead', {}, h('tr', {}, [
    h('th', { scope: 'col', text: 'Metric' }),
    ...TOPOS.map((t) => h('th', { scope: 'col', class: 'num' }, [swatch(t), TOPO_LABEL[t]])),
  ])));
  const body = h('tbody');
  let layer = null;
  for (const m of cmp.metrics) {
    if (m.layer !== layer) {
      layer = m.layer;
      body.append(h('tr', { class: 'section' }, h('th', { colspan: TOPOS.length + 1, scope: 'colgroup', text: LAYER_LABEL[layer] || layer })));
    }
    // every pair holds the medians of its two topologies
    const median = {};
    cmp.pairs.forEach(([a, b], i) => { median[a] = m.pairs[i].median[0]; median[b] = m.pairs[i].median[1]; });
    const fmt = (v) => formatMetric(v, m.unit, m.key);
    body.append(h('tr', {}, [
      h('th', { scope: 'row', text: m.label }),
      ...TOPOS.map((t) => h('td', { class: 'num cmp-cell' }, t === 'horizontal'
        ? [fmt(median[t])]
        : [fmt(median[t]), ' ', h('span', { class: 'pct', text: `(${changeFrom(median.horizontal, median[t])})` })])),
    ]));
  }
  table.append(body);
  return table;
}

function renderComparisons(load, summary) {
  const cmp = load.comparisons;
  document.getElementById('cmpTable').replaceChildren(renderComparisonTable(cmp));
  document.getElementById('cmpSource').textContent = '';
}

// ---------------------------------------------------------------------------
// Entry
// ---------------------------------------------------------------------------

async function init() {
  const fail = (err) => {
    console.error('[load] could not draw:', err);
    for (const id of ['concChart', 'contChart', 'cmpTable']) {
      document.getElementById(id)?.replaceChildren(h('p', { class: 'placeholder', text: `Could not load load.json (${err.message}).` }));
    }
  };
  let load;
  let summary;
  try {
    const [l, sm] = await Promise.all([
      loadData('load.json'),
      loadSummary(),
    ]);
    load = l;
    summary = sm;
  } catch (err) {
    fail(err);
    return;
  }
  for (const [id, fn] of [['concurrency', renderConcurrency], ['contention', renderContention], ['comparisons', renderComparisons]]) {
    if (!document.getElementById(id)) continue; // contention is on the Beta page, the others on System load
    try {
      fn(load, summary);
    } catch (err) {
      console.error(`[load] ${id} failed:`, err);
      document.getElementById(id)?.append(h('p', { class: 'placeholder', text: `This section could not be drawn (${err.message}).` }));
    }
  }
  document.body.dataset.loadReady = 'true';
}

if (document.getElementById('concurrency') || document.getElementById('contention')) init();

