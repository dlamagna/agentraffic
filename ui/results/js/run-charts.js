/**
 * Run analysis, shared by the Run explorer drill-down (runs.js) and the workflow runner
 * (playground/js/run-analysis.js): the stat tiles, the Gantt of a run's LLM calls by agent
 * (stages shaded), the in-flight calls over time, the run's metrics against its topology's
 * distribution, and its inter-arrival times (IAT) against the topology's histogram.
 *
 * A run is passed in as data: { id, topology, roles, roles_by_iteration?, calls, iterations,
 * score, goal_achieved, discussion_rounds, consensus_reached, m }, calls in the runs.json column
 * order [start ms, duration ms, stage code, agent, peer, round, prompt tokens, completion
 * tokens, TTFT ms]. runs.json already has runs in that shape; runFromResponse() builds one from
 * a replayed (or live) AgentVerse response, so a finished run in the runner needs no runs.json.
 * The topology's distribution comes from summary.json (the public aggregates), never from
 * private data.
 *
 * Zoom is optional: pass `zoom` ({ domain, clip, brush }, see results/js/zoom.js and runs.js)
 * for the drill-down's brush-to-zoom; without it the charts show the whole run and this
 * module does not touch the page's URL hash.
 */

import {
  h, s, svgRoot, linear, log10, axisBottom, axisLeft, niceTicks, barPath, logTimeLabel, responsive, showTip, hideTip,
  tipTitle, tipRow, tipNote, formatMetric, quantile, TOPO_LABEL, TOPO_COLOR, STAGE_LABEL, OVERLAP_EPS_MS,
  MAX_PARALLEL_WORKERS, fixed, int, pct, seconds, compact, ms,
} from './util.js';

/** runs.json `stage_codes`: the stage code of a call is its index here. */
export const STAGE_CODES = ['recruitment', 'discussion', 'discussion_synthesis', 'execution', 'evaluation', 'final_output'];
const DISCUSSION = 1;
const BURST_S = 0.05; // summary.iat.burst_threshold_s

/** Metrics shown against the topology median. Those a run lacks (e.g. TCP bytes of a replay) are left out. */
export const DETAIL_METRICS = [
  'disc_n_requests', 'disc_duration_s', 'disc_total_tokens', 'disc_mean_latency_s', 'disc_mean_iat_s',
  'iat_jitter_p50_mean_s', 'burstiness_max', 'llm_inflight_mean', 'llm_ttft_p95_mean_s',
  'prompt_tokens_per_s_mean', 'completion_tokens_per_s_mean', 'tcp_bytes_llm_mean_Bps',
];

/** Used when a chart is drawn without the drill-down's zoom: the whole run, a plain group. */
const NO_ZOOM = {
  domain: (full) => ({ domain: full, zoomed: false }),
  clip: () => s('g'),
  brush: () => {},
};

// ---------------------------------------------------------------------------
// From a response to a run
// ---------------------------------------------------------------------------

/** ms since the epoch of an ISO timestamp, keeping the microseconds Date.parse drops. */
function parseStart(iso) {
  const m = /^(.*?\.\d{3})(\d{0,3})(.*)$/.exec(iso);
  const t = Date.parse(m ? `${m[1]}${m[3]}` : iso);
  return m && m[2] ? t + Number(`0.${m[2]}`) : t;
}

function stageCode(req) {
  if (req.stage === 'recruitment') return 0;
  if (req.stage === 'decision') return String(req.label || '').startsWith('synthesize') ? 2 : DISCUSSION;
  if (req.stage === 'execution') return 3;
  if (req.stage === 'evaluation') return 4;
  return 5;
}

/**
 * A run in runs.json's shape from an AgentVerse response (the replayed fixtures and the live
 * backend share it): `llm_requests` give the calls, `stages` / `iteration_history` the roster.
 * Returns null when there are no timed calls.
 */
export function runFromResponse(data, fallbackTopology = '') {
  const reqs = (data?.llm_requests || []).filter((r) => r && r.start_time_utc && !Number.isNaN(parseStart(r.start_time_utc)));
  if (!reqs.length) return null;
  const timed = reqs.map((r) => ({ r, t: parseStart(r.start_time_utc) })).sort((a, b) => a.t - b.t);
  const t0 = timed[0].t;
  const stages = data.stages || {};
  const roles = (stages.recruitment?.experts || []).map((e) => e.role);
  const rosters = (data.iteration_history || []).map((it) => it.recruitment?.experts).filter(Array.isArray);
  const topology = stages.decision?.structure_used || stages.recruitment?.communication_structure || fallbackTopology;

  const agentOf = (r) => {
    const m = /^agent-b-(\d+)$/.exec(r.source || '');
    if (m) return Number(m[1]) - 1;
    const i = r.agent_role ? roles.indexOf(r.agent_role) : -1;
    return r.stage === 'recruitment' || r.source === 'Agent A' ? -1 : i;
  };
  const solver = timed.find(({ r }) => String(r.label || '').startsWith('vertical_solver'));
  const solverIdx = solver ? agentOf(solver.r) : -1;
  const calls = timed.map(({ r, t }) => {
    const meta = r.llm_meta || {};
    const pair = /agent(\d+)_to_agent(\d+)/.exec(r.label || '');
    let peer = -1;
    if (pair) peer = Number(pair[2]) - 1;
    else if (String(r.label || '').startsWith('vertical_reviewer')) peer = solverIdx;
    const dur = meta.latency_ms ?? (r.duration_seconds != null ? r.duration_seconds * 1000 : 0);
    return [
      t - t0, dur, stageCode(r), agentOf(r), peer, r.round ?? null,
      meta.prompt_tokens ?? 0, meta.completion_tokens ?? 0, meta.queue_wait_s != null ? meta.queue_wait_s * 1000 : null,
    ];
  });
  return {
    id: data.task_id || 'this run',
    task_id: data.task_id || '',
    topology,
    roles,
    roles_by_iteration: rosters.length > 1 ? rosters : null,
    calls,
    iterations: data.iterations || 1,
    score: stages.evaluation?.score ?? null,
    goal_achieved: Boolean(stages.evaluation?.goal_achieved),
    discussion_rounds: (stages.decision?.discussion_rounds || []).length,
    consensus_reached: Boolean(stages.decision?.consensus_reached),
    m: runMetrics(calls),
  };
}

/** Gaps between the starts of consecutive discussion calls, seconds. */
export function discussionIats(calls) {
  const starts = calls.filter((c) => c[2] === DISCUSSION).map((c) => c[0]).sort((a, b) => a - b);
  return starts.slice(1).map((t, i) => (t - starts[i]) / 1000);
}

/** The runs.json metrics that can be derived from a run's calls (the TCP ones cannot). */
export function runMetrics(calls) {
  const disc = calls.filter((c) => c[2] === DISCUSSION);
  const m = {};
  const n = disc.length;
  m.disc_n_requests = n;
  if (!n) return m;
  const starts = disc.map((c) => c[0]);
  const t0 = Math.min(...starts);
  const t1 = Math.max(...starts);
  const dur = (t1 - t0) / 1000;
  const iats = discussionIats(calls);
  const sorted = [...iats].sort((a, b) => a - b);
  const sum = (f) => disc.reduce((a, c) => a + f(c), 0);
  m.disc_duration_s = dur;
  m.disc_total_tokens = sum((c) => c[6] + c[7]);
  m.disc_mean_latency_s = sum((c) => c[1]) / n / 1000;
  if (iats.length) {
    const mean = iats.reduce((a, v) => a + v, 0) / iats.length;
    m.disc_mean_iat_s = mean;
    m.iat_jitter_p50_mean_s = quantile(sorted, 0.5);
    m.iat_jitter_p95_mean_s = quantile(sorted, 0.95);
    m.burstiness_max = sorted[sorted.length - 1];
    if (iats.length >= 2 && mean > 0) m.burstiness_mean = sorted[sorted.length - 1] / mean;
  }
  if (dur > 0) {
    let busy = 0;
    for (const c of disc) busy += Math.max(0, Math.min(c[0] + Math.max(0, c[1] - OVERLAP_EPS_MS), t1) - Math.max(c[0], t0));
    m.llm_inflight_mean = busy / (t1 - t0);
    m.prompt_tokens_per_s_mean = sum((c) => c[6]) / dur;
    m.completion_tokens_per_s_mean = sum((c) => c[7]) / dur;
  }
  const ttft = disc.map((c) => c[8]).filter((v) => v != null).sort((a, b) => a - b);
  if (ttft.length) m.llm_ttft_p95_mean_s = quantile(ttft, 0.95) / 1000;
  return m;
}

// ---------------------------------------------------------------------------
// Call helpers
// ---------------------------------------------------------------------------

/** Iteration index of each call (each iteration starts with its recruitment call). */
export function iterationsOf(calls) {
  let it = -1;
  return calls.map((c) => { if (c[2] === 0) it++; return Math.max(0, it); });
}

export function roleOf(run, iter, agent) {
  if (agent < 0) return 'orchestrator';
  const roster = run.roles_by_iteration ? run.roles_by_iteration[iter] || run.roles : run.roles;
  return roster[agent] ?? `agent ${agent + 1}`;
}

/** In-flight calls over time, overlaps < OVERLAP_EPS_MS removed. Returns step points + peaks. */
export function concurrency(calls, stage = null) {
  const ev = [];
  for (const c of calls) {
    if (stage != null && c[2] !== stage) continue;
    const start = c[0];
    const end = Math.max(start, c[0] + c[1] - OVERLAP_EPS_MS);
    ev.push([start, 1], [end, -1]);
  }
  ev.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const pts = [[0, 0]];
  let cur = 0;
  let peak = 0;
  for (const [t, d] of ev) {
    cur += d;
    peak = Math.max(peak, cur);
    pts.push([t, cur]);
  }
  return { pts, peak };
}

/** Peak of one stage's calls without the overlap rule (durations as recorded). */
export function rawPeak(calls, stage) {
  const ev = [];
  for (const c of calls) if (c[2] === stage) ev.push([c[0], 1], [c[0] + c[1], -1]);
  ev.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  let cur = 0;
  let peak = 0;
  for (const [, d] of ev) { cur += d; peak = Math.max(peak, cur); }
  return peak;
}

export const runEnd = (calls) => Math.max(...calls.map((c) => c[0] + c[1]));

export function tile(label, value, sub = null) {
  return h('div', { class: 'tile' }, [
    h('div', { class: 'tile-label', text: label }),
    h('div', { class: 'tile-value', text: value }),
    sub ? h('div', { class: 'tile-sub', text: sub }) : null,
  ]);
}

/** The stat tiles of a run. */
export function runTiles(run) {
  const calls = run.calls;
  const disc = calls.filter((c) => c[2] === DISCUSSION);
  const tokens = calls.reduce((a, c) => a + c[6] + c[7], 0);
  const peak = concurrency(calls, DISCUSSION).peak;
  return h('div', { class: 'tiles' }, [
    tile('Evaluation score', run.score != null ? `${run.score}/100` : '–', run.goal_achieved ? 'goal achieved' : 'goal not achieved'),
    tile('Iterations', String(run.iterations), run.iterations > 1 ? 'score below threshold, re-ran' : 'single pass'),
    tile('LLM calls', int(calls.length), `${disc.length} in the discussion`),
    tile('Run time', ms(runEnd(calls)), `discussion ${formatMetric(run.m.disc_duration_s, 's')}`),
    tile('Peak in flight', String(peak), 'discussion calls'),
    tile('Tokens', compact(tokens), `${compact(run.m.disc_total_tokens)} in the discussion`),
  ]);
}

// ---------------------------------------------------------------------------
// Time axis, stage bands
// ---------------------------------------------------------------------------

function stageSegments(calls) {
  const segs = [];
  for (const c of calls) {
    const last = segs[segs.length - 1];
    const e = c[0] + c[1];
    if (last && last.stage === c[2]) {
      last.end = Math.max(last.end, e);
    } else {
      segs.push({ stage: c[2], start: c[0], end: e });
    }
  }
  return segs;
}

function timeTicks(x, width) {
  const [d0, d1] = x.domain;
  return niceTicks(d0 / 1000, d1 / 1000, width < 500 ? 4 : 8).map((v) => v * 1000);
}

/** Tick label in seconds, with decimals once the zoomed span is short. */
const timeLabel = (x) => {
  const span = x.domain[1] - x.domain[0];
  const d = span < 4000 ? 2 : span < 40000 ? 1 : 0;
  return (v) => `${fixed(v / 1000, d)} s`;
};

function drawStageBands(g, x, top, bottom, segs, stages, topo, withLabels) {
  segs.forEach((seg, i) => {
    const name = stages[seg.stage];
    const isDisc = name === 'discussion';
    const x0 = x(seg.start);
    const x1 = x(seg.end);
    g.append(s('rect', {
      x: x0, y: top, width: Math.max(1, x1 - x0), height: bottom - top,
      fill: isDisc ? TOPO_COLOR[topo] : 'var(--stage-band)', 'fill-opacity': isDisc ? 0.12 : (i % 2 ? 0.05 : 0.09),
    }));
    if (withLabels) {
      const label = STAGE_LABEL[name] || name;
      const room = x1 - x0;
      const text = room > label.length * 6.2 ? label : room > 16 ? label[0] : '';
      if (text) {
        g.append(s('text', {
          x: x0 + 3, y: top - 4, class: isDisc ? 'annot' : 'annot-muted',
          style: isDisc ? 'font-weight:600' : null, text,
        }));
      }
    }
  });
}

// ---------------------------------------------------------------------------
// Gantt
// ---------------------------------------------------------------------------

export function drawGantt(host, width, run, xDomain, { stages = STAGE_CODES, zoom = NO_ZOOM } = {}) {
  const calls = run.calls;
  const iters = iterationsOf(calls);
  const nAgents = run.roles.length;
  const narrow = width < 520;
  const labelW = narrow ? 74 : 108;
  const M = { top: 20, right: 10, bottom: 34, left: labelW };
  const laneH = 8;
  const laneGap = 2;
  const rowPad = 6;
  const minRowH = 30; // fits the two-line agent label (role + expert N)

  // lanes per agent row
  const rows = [-1, ...Array.from({ length: nAgents }, (_, i) => i)];
  const lanesByRow = new Map(rows.map((r) => [r, []]));
  const laneOf = new Array(calls.length);
  calls.forEach((c, i) => {
    if (!lanesByRow.has(c[3])) lanesByRow.set(c[3], []);
    const lanes = lanesByRow.get(c[3]);
    let lane = lanes.findIndex((endT) => endT <= c[0]);
    if (lane < 0) { lane = lanes.length; lanes.push(0); }
    lanes[lane] = c[0] + c[1] - OVERLAP_EPS_MS;
    laneOf[i] = lane;
  });
  for (const r of lanesByRow.keys()) if (!rows.includes(r)) rows.push(r); // an agent beyond the roster
  let y = M.top;
  const rowY = new Map();
  for (const r of rows) {
    const nl = Math.max(1, lanesByRow.get(r).length);
    const barsH = nl * (laneH + laneGap) - laneGap;
    const hgt = Math.max(minRowH, barsH + rowPad * 2);
    rowY.set(r, { y, h: hgt, pad: (hgt - barsH) / 2 });
    y += hgt;
  }
  const H = y + M.bottom;
  const svg = svgRoot(width, H, `Gantt chart of the ${calls.length} LLM calls of run ${run.id} by agent`);
  const { domain, zoomed } = zoom.domain(xDomain);
  const x = linear(domain, [M.left, width - M.right]);
  const g = s('g');
  svg.append(g);
  const cg = zoom.clip(svg, { x: M.left, y: 0, width: width - M.left - M.right, height: H }); // marks stay inside the plot

  drawStageBands(cg, x, M.top, y, stageSegments(calls), stages, run.topology, true);
  g.append(cg);
  // row separators + labels
  rows.forEach((r) => {
    const { y: ry, h: rh } = rowY.get(r);
    g.append(s('line', { x1: M.left, x2: width - M.right, y1: ry + rh, y2: ry + rh, stroke: 'var(--row-sep)', 'shape-rendering': 'crispEdges' }));
    let label = r < 0 ? 'Agent A' : run.roles[r] ?? `Agent ${r + 1}`;
    if (r >= 0 && run.roles_by_iteration) {
      const names = [...new Set(run.roles_by_iteration.map((roster) => roster[r]))];
      if (names.length > 1) label = `Agent ${r + 1}`;
    }
    const sub = r < 0 ? 'orchestrator' : `expert ${r + 1}`;
    g.append(s('text', { x: M.left - 6, y: ry + rh / 2 - (narrow ? 0 : 2), 'text-anchor': 'end', style: 'fill:var(--chart-label);font-size:11px', text: label.length > 13 && narrow ? `${label.slice(0, 12)}…` : label }));
    if (!narrow) g.append(s('text', { x: M.left - 6, y: ry + rh / 2 + 10, 'text-anchor': 'end', class: 'annot-muted', text: sub }));
  });
  // iteration boundaries
  calls.forEach((c, i) => {
    if (c[2] === 0 && i > 0) {
      const xx = x(c[0]);
      cg.append(s('line', { x1: xx, x2: xx, y1: M.top - 14, y2: y, stroke: 'var(--ink-1)', 'stroke-width': 1, 'stroke-opacity': 0.5 }));
      cg.append(s('text', { x: xx + 3, y: M.top - 12, class: 'annot', text: `iteration ${iters[i] + 1}` }));
    }
  });
  axisBottom(g, x, y, { ticks: timeTicks(x, width), format: timeLabel(x), title: `time since the first LLM call${zoomed ? ' (zoomed)' : ''}`, titleY: 30 });

  const bars = s('g');
  const hits = s('g');
  calls.forEach((c, i) => {
    if (c[0] + c[1] < domain[0] || c[0] > domain[1]) return;
    const { y: ry, pad } = rowY.get(c[3]);
    const by = ry + pad + laneOf[i] * (laneH + laneGap);
    const x0 = x(c[0]);
    const w = Math.max(1.5, x(c[0] + c[1]) - x0 - 1);
    const stage = stages[c[2]];
    const fill = stage === 'discussion' ? TOPO_COLOR[run.topology] : stage === 'discussion_synthesis' ? 'var(--stage-bar-synth)' : 'var(--stage-bar-other)';
    bars.append(s('rect', { x: x0, y: by, width: w, height: laneH, rx: 2, fill }));
    const hit = s('rect', { class: 'hit', x: x0 - 2, y: by - 1, width: Math.max(8, w + 4), height: laneH + 2 });
    hit.addEventListener('pointermove', (ev) => showTip(callTip(run, c, iters[i], i, stages), ev.clientX, ev.clientY));
    hit.addEventListener('pointerleave', hideTip);
    hits.append(hit);
  });
  cg.append(bars, hits);
  zoom.brush(svg, {
    id: 'time:gantt', axis: 'time', mode: 'linear', full: xDomain, current: domain,
    plot: { left: M.left, right: width - M.right, top: M.top, bottom: y }, toValue: x.invert,
  });
  host.replaceChildren(svg);
}

function callTip(run, c, iter, i, stages) {
  const stage = stages[c[2]];
  const who = roleOf(run, iter, c[3]);
  const peer = c[4] >= 0 ? roleOf(run, iter, c[4]) : null;
  const rows = [tipTitle(`#${i + 1} · ${STAGE_LABEL[stage] || stage}${c[5] != null ? ` · round ${c[5]}` : ''}`)];
  rows.push(tipRow(ms(c[1]), 'duration'));
  rows.push(tipRow(`${fixed(c[0] / 1000, 3)} s`, 'start'));
  rows.push(tipRow(peer ? `${who} → ${peer}` : who, run.topology === 'vertical' && peer ? '(reviewer → solver)' : ''));
  rows.push(tipRow(`${int(c[6])} + ${int(c[7])}`, 'prompt + completion tokens'));
  if (c[8] != null) rows.push(tipRow(`${fixed(c[8], 0)} ms`, 'TTFT (queue + prefill)'));
  if (run.iterations > 1) rows.push(tipNote(`iteration ${iter + 1}`));
  return rows;
}

// ---------------------------------------------------------------------------
// In-flight calls over time
// ---------------------------------------------------------------------------

export function drawConcurrency(host, width, run, xDomain, { stages = STAGE_CODES, zoom = NO_ZOOM } = {}) {
  const narrow = width < 520;
  const M = { top: 14, right: 10, bottom: 34, left: narrow ? 74 : 108 };
  const H = 150;
  const all = concurrency(run.calls);
  const disc = concurrency(run.calls, DISCUSSION);
  const fm = run.topology === 'full_mesh';
  const yMax = Math.max(all.peak, fm ? MAX_PARALLEL_WORKERS : 0) + 1;
  const svg = svgRoot(width, H, `In-flight LLM calls over time for run ${run.id}; discussion peak ${disc.peak}, run peak ${all.peak}`);
  const { domain, zoomed } = zoom.domain(xDomain);
  const x = linear(domain, [M.left, width - M.right]);
  const y = linear([0, yMax], [H - M.bottom, M.top]);
  const g = s('g');
  svg.append(g);
  const cg = zoom.clip(svg, { x: M.left, y: 0, width: width - M.left - M.right, height: H });
  drawStageBands(cg, x, M.top, H - M.bottom, stageSegments(run.calls), stages, run.topology, false);
  g.append(cg);
  axisLeft(g, y, M.left, { ticks: niceTicks(0, yMax, 4).filter((v) => Number.isInteger(v)), gridRight: width - M.right });
  axisBottom(g, x, H - M.bottom, { ticks: timeTicks(x, width), format: timeLabel(x), title: `time since the first LLM call${zoomed ? ' (zoomed)' : ''}`, titleY: 30 });

  const step = (pts) => {
    let d = '';
    pts.forEach(([t, v], i) => {
      const px = x(t).toFixed(1);
      const py = y(v).toFixed(1);
      d += i === 0 ? `M${px},${py}` : `H${px}V${py}`;
    });
    return `${d}H${x(domain[1]).toFixed(1)}`;
  };
  const color = TOPO_COLOR[run.topology];
  cg.append(s('path', { d: `${step(all.pts)}V${y(0)}H${x(0)}Z`, fill: color, 'fill-opacity': 0.12, stroke: 'none' }));
  cg.append(s('path', { d: step(all.pts), fill: 'none', stroke: color, 'stroke-width': 2, 'stroke-linejoin': 'round' }));

  if (fm) {
    const yy = y(MAX_PARALLEL_WORKERS);
    g.append(s('line', { class: 'annot-line', x1: M.left, x2: width - M.right, y1: yy, y2: yy, 'stroke-dasharray': '3 3' }));
    g.append(s('text', {
      class: 'annot', x: width - M.right - 2, y: yy - 4, 'text-anchor': 'end',
      text: narrow ? `${MAX_PARALLEL_WORKERS} workers: waves of ${MAX_PARALLEL_WORKERS}` : `${MAX_PARALLEL_WORKERS} workers: discussion arrives in waves of ${MAX_PARALLEL_WORKERS}`,
    }));
  }
  // label the discussion peak (for full mesh the workers line already marks it)
  const peakPt = disc.pts.find(([, v]) => v === disc.peak);
  if (peakPt && disc.peak > 0 && !fm) {
    const px = x(peakPt[0]);
    g.append(s('text', { class: 'annot', x: Math.min(px + 4, width - M.right - 90), y: y(disc.peak) - 4, text: `discussion peak ${disc.peak}` }));
  }

  // hover: crosshair snapping to the step value at the pointer's time
  const cross = s('line', { class: 'annot-line', y1: M.top, y2: H - M.bottom, display: 'none' });
  g.append(cross);
  const hit = s('rect', { class: 'hit', x: M.left, y: M.top, width: width - M.left - M.right, height: H - M.top - M.bottom });
  hit.addEventListener('pointermove', (ev) => {
    const b = svg.getBoundingClientRect();
    const t = x.invert(ev.clientX - b.left);
    let v = 0;
    for (const [pt, pv] of all.pts) { if (pt <= t) v = pv; else break; }
    cross.setAttribute('x1', ev.clientX - b.left);
    cross.setAttribute('x2', ev.clientX - b.left);
    cross.removeAttribute('display');
    showTip([tipTitle(`${fixed(t / 1000, 2)} s`), tipRow(String(v), 'calls in flight', color)], ev.clientX, ev.clientY);
  });
  hit.addEventListener('pointerleave', () => { cross.setAttribute('display', 'none'); hideTip(); });
  g.append(hit);
  zoom.brush(svg, {
    id: 'time:conc', axis: 'time', mode: 'linear', full: xDomain, current: domain,
    plot: { left: M.left, right: width - M.right, top: M.top, bottom: H - M.bottom }, toValue: x.invert,
  });
  host.replaceChildren(svg);
}

// ---------------------------------------------------------------------------
// The run against its topology's distribution
// ---------------------------------------------------------------------------

export function drawMetricDots(host, width, run, { summary, info }) {
  const agg = summary.aggregates.by_topology[run.topology];
  const keys = DETAIL_METRICS.filter((k) => info.has(k) && run.m[k] != null && agg[k]);
  const narrow = width < 520;
  const labelW = narrow ? 118 : 170;
  const valueW = narrow ? 64 : 150;
  const rowH = 26;
  const M = { top: 4, right: 8, bottom: 4 };
  const H = M.top + rowH * keys.length + M.bottom;
  const svg = svgRoot(width, H, `Metrics of run ${run.id} against the ${TOPO_LABEL[run.topology]} median`);
  const color = TOPO_COLOR[run.topology];
  const x0 = labelW;
  const x1 = width - valueW - M.right;
  keys.forEach((k, i) => {
    const m = info.get(k);
    const a = agg[k];
    const v = run.m[k];
    const lo = Math.min(a.p25, v, a.median);
    const hi = Math.max(a.p75, v, a.median);
    const pad = (hi - lo) * 0.12 || Math.abs(hi) * 0.1 || 1;
    const sc = linear([lo - pad, hi + pad], [x0, x1]);
    const cy = M.top + i * rowH + rowH / 2;
    const g = s('g');
    g.append(s('text', { x: x0 - 8, y: cy + 4, 'text-anchor': 'end', style: 'fill:var(--chart-label);font-size:11.5px', text: m.label }));
    g.append(s('line', { x1: x0, x2: x1, y1: cy, y2: cy, stroke: 'var(--row-sep)' }));
    g.append(s('rect', { x: sc(a.p25), y: cy - 5, width: Math.max(1, sc(a.p75) - sc(a.p25)), height: 10, rx: 3, fill: color, 'fill-opacity': 0.22 }));
    g.append(s('line', { x1: sc(a.median), x2: sc(a.median), y1: cy - 8, y2: cy + 8, stroke: 'var(--median-tick)', 'stroke-width': 2 }));
    g.append(s('circle', { cx: sc(v), cy, r: 5, fill: color, stroke: 'var(--mark-ring)', 'stroke-width': 2 }));
    const rel = a.median ? v / a.median - 1 : 0;
    const relText = Math.abs(rel) < 0.005 ? '±0%' : `${rel > 0 ? '+' : '−'}${fixed(Math.abs(rel) * 100, 0)}%`;
    g.append(s('text', {
      x: width - M.right, y: cy + 4, 'text-anchor': 'end', style: 'fill:var(--chart-value);font-size:11px;font-variant-numeric:tabular-nums',
      text: narrow ? relText : `${formatMetric(v, m.unit, k)} (${relText})`,
    }));
    const hit = s('rect', { class: 'hit', x: 0, y: cy - rowH / 2, width, height: rowH });
    hit.addEventListener('pointermove', (ev) => showTip([
      tipTitle(m.label),
      tipRow(formatMetric(v, m.unit), 'this run', color),
      tipRow(formatMetric(a.median, m.unit), `${TOPO_LABEL[run.topology]} median`),
      tipRow(`${formatMetric(a.p25, m.unit)} – ${formatMetric(a.p75, m.unit)}`, 'interquartile range'),
      tipNote(m.description),
    ], ev.clientX, ev.clientY));
    hit.addEventListener('pointerleave', hideTip);
    g.append(hit);
    svg.append(g);
  });
  host.replaceChildren(svg);
  // text equivalent for screen readers
  const list = h('ul', { class: 'visually-hidden' }, keys.map((k) => {
    const m = info.get(k);
    return h('li', { text: `${m.label}: ${formatMetric(run.m[k], m.unit)}; ${TOPO_LABEL[run.topology]} median ${formatMetric(agg[k].median, m.unit)}` });
  }));
  host.append(list);
}

// ---------------------------------------------------------------------------
// Inter-arrival times: the run's gaps on the topology's histogram
// ---------------------------------------------------------------------------

/** Log ticks for a span that may be under two decades: 1, 2, 5 x 10^k when decades alone are too few. */
function iatTicks(lo, hi) {
  const decades = [];
  for (let e = Math.ceil(Math.log10(lo) - 1e-9); e <= Math.floor(Math.log10(hi) + 1e-9); e++) decades.push(10 ** e);
  if (decades.length >= 4) return decades;
  const out = [];
  for (let e = Math.floor(Math.log10(lo)); e <= Math.ceil(Math.log10(hi)); e++) {
    for (const k of [1, 2, 5]) { const v = k * 10 ** e; if (v >= lo * 0.999 && v <= hi * 1.001) out.push(v); }
  }
  return out;
}

/**
 * The topology's discussion IATs (% per 1/8-decade bin, summary.iat) with this run's gaps
 * marked under the bars (one tick per gap) and its median against the topology's median.
 */
export function drawRunIat(host, width, run, { summary }) {
  const topo = run.topology;
  const hist = summary.iat.per_topology[topo];
  const bins = summary.iat.bins_s;
  const iats = discussionIats(run.calls);
  const color = TOPO_COLOR[topo];
  const narrow = width < 420;
  const M = { top: 24, right: 10, bottom: 70, left: 42 };
  const H = 250;

  // visible span: the bins that hold data and this run's gaps
  const first = hist.counts.findIndex((c) => c > 0);
  const last = hist.counts.length - 1 - [...hist.counts].reverse().findIndex((c) => c > 0);
  const positive = iats.filter((v) => v > 0);
  let lo = Math.min(bins[first], positive.length ? Math.min(...positive) : Infinity);
  let hi = Math.max(bins[last + 1], positive.length ? Math.max(...positive) : 0);
  lo = Math.max(bins[0], lo / 1.5);
  hi = Math.min(bins[bins.length - 1], hi * 1.5);
  const zeros = iats.length - positive.length;
  const svg = svgRoot(width, H, `Inter-arrival times of run ${run.id} on the ${TOPO_LABEL[topo]} histogram: median ${seconds(run.m.iat_jitter_p50_mean_s)} against the topology's ${seconds(hist.median_s)}`);
  const x = log10([lo, hi], [M.left, width - M.right]);
  const plotBottom = H - M.bottom;
  const top = Math.max(...hist.counts.map((c) => (c / hist.n) * 100)) * 1.1 || 1;
  const y = linear([0, top], [plotBottom, M.top]);
  const g = s('g');
  svg.append(g);

  const xb = x(BURST_S);
  if (xb > M.left && xb < width - M.right) {
    g.append(s('rect', { class: 'burst-zone', x: M.left, y: M.top, width: xb - M.left, height: plotBottom - M.top }));
    g.append(s('line', { class: 'annot-line', x1: xb, x2: xb, y1: M.top - 4, y2: plotBottom }));
    g.append(s('text', { class: 'annot-muted', x: xb - 4, y: M.top - 8, 'text-anchor': 'end', text: `< 50 ms: ${pct(hist.burst_fraction)} of ${TOPO_LABEL[topo]} gaps` }));
  }
  axisLeft(g, y, M.left, { format: (v) => `${fixed(v, 0)}%`, ticks: y.ticks(4), gridRight: width - M.right });
  const ticks = iatTicks(lo, hi);
  axisBottom(g, x, plotBottom, {
    ticks, format: (v) => (narrow && ticks.length > 5 && Math.round(Math.log10(v) * 3) % 3 !== 0 ? '' : logTimeLabel(v)), gridTop: M.top,
    title: 'gap between discussion-call starts (log scale)', titleY: 62,
  });

  for (let i = 0; i < hist.counts.length; i++) {
    const c = hist.counts[i];
    const a = bins[i];
    const b = bins[i + 1];
    if (!c || b <= lo || a >= hi) continue;
    const x0 = x(Math.max(a, lo));
    const x1 = x(Math.min(b, hi));
    const bw = Math.max(0.5, x1 - x0 - (x1 - x0 > 5 ? 1 : 0.5));
    const yTop = y((c / hist.n) * 100);
    g.append(s('path', { d: barPath(x0, yTop, bw, plotBottom - yTop, 2), fill: color, 'fill-opacity': 0.45 }));
    const hit = s('rect', { class: 'hit', x: x0, y: M.top, width: x1 - x0, height: plotBottom - M.top });
    hit.addEventListener('pointermove', (ev) => showTip([
      tipTitle(`${logTimeLabel(a)} – ${logTimeLabel(b)}`),
      tipRow(`${fixed((c / hist.n) * 100, 2)}%`, `of ${TOPO_LABEL[topo]} gaps (${int(c)})`, color),
      tipRow(String(iats.filter((v) => v >= a && v < b).length), 'gaps of this run'),
    ], ev.clientX, ev.clientY));
    hit.addEventListener('pointerleave', hideTip);
    g.append(hit);
  }

  // topology median (dashed) and this run's median (solid), each labelled on its own row on the
  // side that has room
  const mark = (v, label, dash, row) => {
    if (!(v > 0) || v < lo || v > hi) return;
    const xx = x(v);
    const room = label.length * 6;
    const anchor = xx + 4 + room <= width - M.right ? 'start' : 'end';
    g.append(s('line', { x1: xx, x2: xx, y1: M.top, y2: plotBottom, stroke: 'var(--median-tick)', 'stroke-width': 1.5, 'stroke-dasharray': dash }));
    g.append(s('text', { class: 'annot', x: xx + (anchor === 'start' ? 4 : -4), y: M.top + 10 + row * 12, 'text-anchor': anchor, text: label }));
  };
  const runMed = run.m.iat_jitter_p50_mean_s;
  mark(hist.median_s, `${narrow ? 'topology' : TOPO_LABEL[topo]} median ${seconds(hist.median_s)}`, '4 3', 0);
  mark(runMed, `${narrow ? 'run' : 'this run'} ${seconds(runMed)}`, null, 1);

  // this run's gaps: one tick each under the plot, in the topology colour with a ring for contrast
  const rugY = plotBottom + 36;
  g.append(s('text', { class: 'annot-muted', x: M.left - 6, y: rugY + 4, 'text-anchor': 'end', text: 'this run' }));
  g.append(s('line', { x1: M.left, x2: width - M.right, y1: rugY, y2: rugY, stroke: 'var(--row-sep)' }));
  positive.forEach((v) => {
    const xx = x(Math.min(hi, Math.max(lo, v)));
    g.append(s('line', { x1: xx, x2: xx, y1: rugY - 7, y2: rugY + 7, stroke: color, 'stroke-width': 2, 'stroke-linecap': 'round' }));
  });
  const rugHit = s('rect', { class: 'hit', x: M.left, y: rugY - 10, width: width - M.left - M.right, height: 20 });
  rugHit.addEventListener('pointermove', (ev) => {
    const b = svg.getBoundingClientRect();
    const t = x.invert(ev.clientX - b.left);
    const near = positive.reduce((best, v) => (Math.abs(Math.log(v / t)) < Math.abs(Math.log(best / t)) ? v : best), positive[0]);
    showTip([tipTitle('A gap of this run'), tipRow(seconds(near), 'between two discussion-call starts', color)], ev.clientX, ev.clientY);
  });
  rugHit.addEventListener('pointerleave', hideTip);
  if (positive.length) g.append(rugHit);
  if (zeros) {
    g.append(s('text', { class: 'annot-muted', x: width - M.right, y: rugY + 24, 'text-anchor': 'end', text: `+ ${zeros} gap${zeros > 1 ? 's' : ''} of 0 s (calls starting together)` }));
  }
  host.replaceChildren(svg);
}

/** Gap statistics of a run beside the topology's, as tiles. */
export function iatTiles(run, summary) {
  const hist = summary?.iat?.per_topology?.[run.topology];
  const iats = discussionIats(run.calls);
  if (!iats.length) return null;
  const label = TOPO_LABEL[run.topology];
  const m = run.m;
  const burst = iats.filter((v) => v < BURST_S).length / iats.length;
  const agg = summary?.aggregates?.by_topology?.[run.topology] || {};
  const vs = (key, text) => (agg[key] ? `${label} median ${text(agg[key].median)}` : null);
  return h('div', { class: 'tiles' }, [
    tile('Gaps', int(iats.length), 'between discussion-call starts'),
    tile('Median gap (jitter)', seconds(m.iat_jitter_p50_mean_s), vs('iat_jitter_p50_mean_s', seconds)),
    tile('Longest gap (burstiness)', seconds(m.burstiness_max), vs('burstiness_max', seconds)),
    tile('Gaps under 50 ms', pct(burst, 0), hist ? `${label}: ${pct(hist.burst_fraction, 0)} of gaps` : null),
  ]);
}

// ---------------------------------------------------------------------------
// The blocks, assembled
// ---------------------------------------------------------------------------

function block(title, sub, ...children) {
  return h('div', { class: 'detail-block' }, [h('h4', { text: title }), sub ? h('p', { class: 'chart-sub', text: sub }) : null, ...children.flat()]);
}

/**
 * The analysis of one run: stat tiles and the four chart blocks (calls by agent, in flight, run
 * against the topology, inter-arrival times), as elements to lay out, plus mount() which starts
 * their responsive drawing and returns the handles ({ rerender, disconnect }) to release.
 *
 *   summary   summary.json (public aggregates); without it the two topology comparisons say so
 *   info      metricInfo(summary)
 *   stages    stage codes (runs.json `stage_codes`)
 *   zoom      the drill-down's brush-to-zoom (see NO_ZOOM)
 *   before    elements to put between the Gantt's caption and the chart (the zoom bar)
 *   unavailable  text shown where a comparison cannot be drawn (default: the summary is missing)
 */
export function buildRunAnalysis(run, { summary = null, info = null, stages = STAGE_CODES, zoom = NO_ZOOM, before = [], unavailable = 'The topology aggregates (summary.json) could not be loaded, so this comparison is not available.' } = {}) {
  const topoLabel = TOPO_LABEL[run.topology];
  const xDomain = [0, runEnd(run.calls)];
  const fm = run.topology === 'full_mesh';
  const wavesNote = fm
    ? h('p', { class: 'callout' }, [
      h('strong', { text: 'Full mesh arrives in waves of 5. ' }),
      `Each round has ${run.roles.length * (run.roles.length - 1)} directed peer messages, but Agent A sends them through a pool of ${MAX_PARALLEL_WORKERS} workers: five start together, and each of the rest starts when a worker frees up.`,
    ])
    : null;
  const ganttHost = h('div', { class: 'chart-body', 'data-chart': 'gantt' });
  const concHost = h('div', { class: 'chart-body', 'data-chart': 'concurrency' });
  const metricsHost = h('div', { class: 'chart-body', 'data-chart': 'metrics' });
  const iatHost = h('div', { class: 'chart-body', 'data-chart': 'run-iat' });
  const haveSummary = Boolean(summary && info && summary.aggregates?.by_topology?.[run.topology]);
  const note = () => h('p', { class: 'placeholder', text: unavailable });

  const gantt = block('LLM calls by agent',
    `Each bar is one LLM call (start to end). Discussion calls in the topology colour, other stages grey; overlapping calls of one agent stack. Rounds: ${run.discussion_rounds}${run.consensus_reached ? ', consensus reached' : ''}.`,
    wavesNote, ...before, ganttHost);
  const conc = block('LLM calls in flight',
    'All calls of the run as seen by the LLM backend.', concHost);
  const metrics = block(`This run against the ${topoLabel} median`,
    haveSummary ? `Dot: this run. Tick: median of the ${int(summary.source.n_runs[run.topology])} ${topoLabel} runs; band: their interquartile range. Each row has its own scale.` : null,
    haveSummary ? metricsHost : note());
  const iatTilesEl = haveSummary ? iatTiles(run, summary) : null;
  const iat = block('Inter-arrival times',
    haveSummary ? `The gaps between this run's discussion-call starts (one tick each) on the histogram of all ${int(summary.iat.per_topology[run.topology].n)} ${topoLabel} gaps; the dashed line is the topology median.` : null,
    haveSummary && discussionIats(run.calls).length ? [iatTilesEl, iatHost] : (haveSummary ? h('p', { class: 'placeholder', text: 'This run has fewer than two discussion calls, so it has no gaps.' }) : note()));

  return {
    tiles: runTiles(run),
    gantt, conc, metrics, iat,
    mount() {
      const handles = [];
      const ganttH = responsive(ganttHost, (w) => drawGantt(ganttHost, w, run, xDomain, { stages, zoom }));
      const concH = responsive(concHost, (w) => drawConcurrency(concHost, w, run, xDomain, { stages, zoom }));
      handles.push(ganttH, concH);
      if (haveSummary) {
        handles.push(responsive(metricsHost, (w) => drawMetricDots(metricsHost, w, run, { summary, info })));
        if (discussionIats(run.calls).length) handles.push(responsive(iatHost, (w) => drawRunIat(iatHost, w, run, { summary })));
      }
      return { handles, ganttH, concH };
    },
  };
}
