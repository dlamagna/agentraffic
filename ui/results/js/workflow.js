/**
 * Workflow analyses. Loaded by results/system-load/ (stages, roles) and results/beta/ (the other four).
 * Data: workflow.json of the active data set (ui/data/, from scripts/demo/analysis_workflow.py), lazy-loaded.
 *
 * Six sections inside #workflowSections ("Inside the workflow"): stage breakdown and execution
 * parallelism, per-role tokens and latency, the full-mesh message matrix and consensus per round,
 * context growth across rounds, retries and their cost, quality vs cost. Every chart follows the
 * filter bar (topology chips; Task picks the per-task aggregates). Colours are CSS variables, so
 * the charts recolour with the theme without a redraw.
 */

import {
  h, s, svgRoot, linear, axisBottom, axisLeft, niceMax, responsive, showTip, showTipAt, hideTip,
  tipTitle, tipRow, tipNote, barPath, dataTable, TOPOS, TOPO_LABEL, TOPO_COLOR, STAGE_LABEL, swatch,
  fixed, int, pct, seconds, compact, loadData,
} from './util.js';
import { getFilter, onFilterChange } from './shell.js';

const ROLE_LABEL = {
  planner: 'Planner', researcher: 'Researcher', critic: 'Critic', executor: 'Executor',
  summarizer: 'Summarizer', orchestrator: 'Orchestrator',
};
const ROLE_SHORT = { planner: 'Plan.', researcher: 'Res.', critic: 'Crit.', executor: 'Exec.', summarizer: 'Summ.' };
const roleLabel = (r) => ROLE_LABEL[r] || r;
const TASK_LABEL = { math: 'Math', research: 'Research', consulting: 'Consulting', coding: 'Software dev.' };

const state = {
  data: null,
  filter: getFilter(),
  stageMeasure: 'calls',
  roleMetric: 'prompt_tokens',
  roleScope: 'all',
  msgMeasure: 'count',
  qualCost: 'tokens',
};
const views = []; // { rerender } handles, redrawn on filter change

// ---------------------------------------------------------------------------
// Shared bits
// ---------------------------------------------------------------------------

const $ = (id) => document.getElementById(id);

/** The aggregates for the current Task filter (all tasks if none) and the visible topologies. */
function view() {
  const { data, filter } = state;
  const groups = data.groups[filter.task] || data.groups.all;
  const topos = TOPOS.filter((t) => filter.topos.has(t) && groups[t]);
  return { g: groups, topos, task: data.groups[filter.task] ? filter.task : '' };
}

const scopeText = () => {
  const { task } = view();
  return task ? `${TASK_LABEL[task] || task} tasks` : 'all tasks';
};

function sourceLine(extra = '') {
  return extra;
}

/** A radiogroup of buttons with arrow-key support. */
function segmented(host, options, value, onChange) {
  let current = value;
  const set = (v, focus = false) => {
    current = v;
    host.querySelectorAll('button').forEach((b) => b.setAttribute('aria-checked', String(b.dataset.value === v)));
    if (focus) host.querySelector(`[data-value="${v}"]`).focus();
    onChange(v);
  };
  host.replaceChildren(...options.map(([v, label]) => {
    const b = h('button', { type: 'button', role: 'radio', 'aria-checked': String(v === value), 'data-value': v, text: label });
    b.addEventListener('click', () => set(v));
    return b;
  }));
  host.addEventListener('keydown', (ev) => {
    if (!['ArrowLeft', 'ArrowRight'].includes(ev.key)) return;
    const i = options.findIndex(([v]) => v === current);
    const j = (i + (ev.key === 'ArrowRight' ? 1 : options.length - 1)) % options.length;
    set(options[j][0], true);
    ev.preventDefault();
  });
}

/** Tooltip on pointer and keyboard focus for a hit target. */
function hover(el, content) {
  el.setAttribute('tabindex', '0');
  el.addEventListener('pointermove', (ev) => showTip(content(), ev.clientX, ev.clientY));
  el.addEventListener('pointerleave', hideTip);
  el.addEventListener('focus', () => showTipAt(content(), el));
  el.addEventListener('blur', hideTip);
  return el;
}

const legend = (topos, extra = []) => h('div', { class: 'legend' }, [
  ...topos.map((t) => h('span', {}, [swatch(t), TOPO_LABEL[t]])),
  ...extra,
]);

function mount(hostId, draw) {
  const host = $(hostId);
  const body = h('div', { class: 'chart-body' });
  const top = h('div');
  host.replaceChildren(top, body);
  const handle = responsive(body, (w) => draw(body, w, top));
  views.push(handle);
  return handle;
}

// ---------------------------------------------------------------------------
// 1. Stage breakdown
// ---------------------------------------------------------------------------

const STAGE_MEASURES = [
  ['calls', 'Calls', 'calls', (v) => fixed(v, 1)],
  ['tokens', 'Tokens', 'tokens', compact],
  ['llm_time', 'LLM time', 'llm_time_s', seconds],
  ['wall_time', 'Wall time', 'wall_time_s', seconds],
];

function drawStages(host, width, top) {
  const { g, topos } = view();
  const [key, label, perRunKey, fmt] = STAGE_MEASURES.find((m) => m[0] === state.stageMeasure);
  const stages = state.data.stages;
  top.replaceChildren(legend(topos));
  const narrow = width < 520;
  const M = { top: 4, right: 44, bottom: 36, left: narrow ? 86 : 120 };
  const barH = 9, gap = 2, groupGap = 12;
  const groupH = topos.length * (barH + gap) - gap;
  const H = M.top + stages.length * (groupH + groupGap) - groupGap + M.bottom;
  const max = Math.max(...topos.flatMap((t) => g[t].stages.share[key].map((v) => v || 0)));
  const x = linear([0, niceMax(max)], [M.left, width - M.right]);
  const svg = svgRoot(width, H, `${label}: each stage's share of a run, per topology`);
  const yEnd = H - M.bottom;
  axisBottom(svg, x, yEnd, { ticks: x.ticks(narrow ? 3 : 5), format: (v) => pct(v, 0), gridTop: M.top, title: `Share of ${label.toLowerCase()}` });
  stages.forEach((stage, si) => {
    const y0 = M.top + si * (groupH + groupGap);
    svg.append(s('text', { x: M.left - 8, y: y0 + groupH / 2 + 4, 'text-anchor': 'end', class: 'wf-cat', text: STAGE_LABEL[stage] || stage }));
    topos.forEach((t, i) => {
      const v = g[t].stages.share[key][si] || 0;
      const y = y0 + i * (barH + gap);
      const w = x(v) - x(0);
      if (w > 0) svg.append(s('path', { d: barPath(x(0), y, w, barH, 3, 'right'), fill: TOPO_COLOR[t] }));
      svg.append(s('text', { x: x(v) + 4, y: y + barH - 1, class: 'wf-val', text: pct(v, v < 0.1 && v > 0 ? 1 : 0) }));
      svg.append(hover(s('rect', { class: 'hit', x: M.left, y: y - gap / 2, width: width - M.left - M.right + M.right - 4, height: barH + gap }), () => [
        tipTitle(`${STAGE_LABEL[stage]} · ${TOPO_LABEL[t]}`),
        tipRow(pct(v, 1), `of all ${label.toLowerCase()}`, TOPO_COLOR[t]),
        tipRow(fmt(g[t].stages.per_run[perRunKey][si] || 0), 'per run (mean)'),
      ]));
    });
  });
  host.replaceChildren(svg);
}

function renderExec() {
  const { g, topos } = view();
  const rows = topos.map((t) => {
    const e = g[t].execution;
    const peaks = Object.entries(e.peak);
    const top = peaks.reduce((a, b) => (b[1] > a[1] ? b : a), ['0', 0]);
    return [
      h('span', {}, [swatch(t), TOPO_LABEL[t]]),
      fixed(e.calls.median, 0),
      fixed(e.parallelism.mean, 1),
      `${top[0]} (${pct(top[1] / e.stages, 0)})`,
      seconds(e.span_s.median),
    ];
  });
  $('wfExec').replaceChildren(
    h('div', { class: 'table-wrap' }, dataTable(
      ['Topology', 'Calls', 'Mean in flight', 'Peak (share of stages)', 'Stage length (median)'], rows,
      { caption: 'Execution stage parallelism per topology', numeric: [1, 2, 4] },
    )),
    h('p', { class: 'wf-note', text: 'Experts run their subtasks at the same time, so execution is parallel in every topology. Mean in flight = total call time ÷ stage length.' }),
  );
}

function renderStages() {
  segmented($('wfStageMeasure'), STAGE_MEASURES.map(([k, l]) => [k, l]), state.stageMeasure, (v) => {
    state.stageMeasure = v;
    stagesView.rerender();
  });
  const stagesView = mount('wfStagesChart', drawStages);
  const update = () => {
    renderExec();
    $('wfStagesSource').textContent = sourceLine('Wall time: from the first call to the last call of each stage.');
  };
  update();
  return update;
}

// ---------------------------------------------------------------------------
// 2. Roles
// ---------------------------------------------------------------------------

const ROLE_METRICS = [
  ['prompt_tokens', 'Prompt tokens per call', compact],
  ['completion_tokens', 'Completion tokens per call', compact],
  ['latency_s', 'Latency per call', seconds],
];

function drawRoles(host, width, top) {
  const { g, topos } = view();
  const [key, label, fmt] = ROLE_METRICS.find((m) => m[0] === state.roleMetric);
  const scope = state.roleScope;
  const roles = [...state.data.roles, 'orchestrator'].filter((r) => topos.some((t) => g[t].roles[scope][r]));
  top.replaceChildren(legend(topos));
  const narrow = width < 520;
  const M = { top: 4, right: 16, bottom: 38, left: narrow ? 88 : 110 };
  const rowH = 13, groupGap = 12;
  const groupH = topos.length * rowH;
  const H = M.top + roles.length * (groupH + groupGap) - groupGap + M.bottom;
  const max = Math.max(...roles.flatMap((r) => topos.map((t) => g[t].roles[scope][r]?.[key].p75 || 0)));
  const x = linear([0, niceMax(max)], [M.left, width - M.right]);
  const svg = svgRoot(width, H, `${label} by role and topology: median and interquartile range`);
  const yEnd = H - M.bottom;
  axisBottom(svg, x, yEnd, { ticks: x.ticks(narrow ? 3 : 6), format: key === 'latency_s' ? (v) => `${v} s` : compact, gridTop: M.top, title: label });
  roles.forEach((role, ri) => {
    const y0 = M.top + ri * (groupH + groupGap);
    svg.append(s('text', { x: M.left - 8, y: y0 + groupH / 2 + 4, 'text-anchor': 'end', class: 'wf-cat', text: roleLabel(role) }));
    topos.forEach((t, i) => {
      const r = g[t].roles[scope][role];
      if (!r) return;
      const d = r[key];
      const cy = y0 + i * rowH + rowH / 2;
      svg.append(s('line', { x1: x(d.p25), x2: x(d.p75), y1: cy, y2: cy, stroke: TOPO_COLOR[t], 'stroke-width': 3, 'stroke-linecap': 'round' }));
      svg.append(s('circle', { cx: x(d.median), cy, r: 4.5, fill: TOPO_COLOR[t], stroke: 'var(--mark-ring)', 'stroke-width': 2 }));
      svg.append(hover(s('rect', { class: 'hit', x: M.left, y: cy - rowH / 2, width: width - M.left - M.right, height: rowH }), () => [
        tipTitle(`${roleLabel(role)} · ${TOPO_LABEL[t]}`),
        tipRow(fmt(d.median), 'median', TOPO_COLOR[t]),
        tipRow(`${fmt(d.p25)} to ${fmt(d.p75)}`, 'interquartile range'),
        tipRow(fixed(r.calls_per_run, 1), 'calls per run'),
        tipRow(pct(r.token_share, 0), `of the ${scope === 'all' ? 'run' : 'discussion'}'s tokens`),
        tipNote(`${int(d.n)} calls`),
      ]));
    });
  });
  host.replaceChildren(svg);
}

function renderRoles() {
  const sel = $('wfRoleMetric');
  sel.replaceChildren(...ROLE_METRICS.map(([k, l]) => h('option', { value: k, text: l })));
  sel.value = state.roleMetric;
  const rolesView = mount('wfRolesChart', drawRoles);
  sel.addEventListener('change', () => { state.roleMetric = sel.value; rolesView.rerender(); });
  segmented($('wfRoleScope'), [['all', 'All calls'], ['discussion', 'Discussion only']], state.roleScope, (v) => {
    state.roleScope = v;
    rolesView.rerender();
  });
  const update = () => {
    const { g, topos } = view();
    const parts = [];
    if (topos.includes('vertical')) {
      if (g.vertical.roles.discussion.planner) parts.push('In Star, the planner is also the solver.');
    }
    $('wfRolesNote').textContent = parts.join(' ');
    $('wfRolesSource').textContent = sourceLine('Latency includes queueing.');
  };
  update();
  return update;
}

// ---------------------------------------------------------------------------
// 3. Messages (full mesh) and consensus
// ---------------------------------------------------------------------------

function drawMatrix(host, width, top) {
  const { g, topos } = view();
  const m = g.full_mesh?.messages;
  if (!topos.includes('full_mesh') || !m) {
    top.replaceChildren();
    host.replaceChildren(h('p', { class: 'placeholder', text: 'Full mesh is filtered out: the message matrix only exists for Full mesh.' }));
    return;
  }
  const roles = m.roles.filter((r, i) => m.count[i].some((c) => c > 0) || m.count.some((row) => row[i] > 0));
  const idx = roles.map((r) => m.roles.indexOf(r));
  const isCount = state.msgMeasure === 'count';
  const val = (i, j) => (isCount ? m.count[i][j] : m.completion_tokens_mean[i][j]);
  const values = idx.flatMap((i) => idx.map((j) => val(i, j))).filter((v) => v);
  const max = Math.max(...values);
  const k = roles.length;
  const left = width < 360 ? 74 : 86;
  const cell = Math.max(30, Math.min(56, Math.floor((width - left - 4) / k)));
  const short = cell < 62;
  const topH = 22;
  const W = left + cell * k + 4;
  const H = topH + cell * k + 4;
  const svg = svgRoot(W, H, `Full mesh discussion messages by sender (rows) and receiver (columns): ${isCount ? 'message count' : 'mean message length in tokens'}`);
  svg.classList.add('wf-matrix');
  roles.forEach((r, c) => svg.append(s('text', { x: left + c * cell + cell / 2, y: topH - 8, 'text-anchor': 'middle', class: 'wf-cat', text: short ? ROLE_SHORT[r] || r : roleLabel(r) })));
  roles.forEach((sender, a) => {
    const y = topH + a * cell;
    svg.append(s('text', { x: left - 8, y: y + cell / 2 + 4, 'text-anchor': 'end', class: 'wf-cat', text: roleLabel(sender) }));
    roles.forEach((receiver, b) => {
      const x = left + b * cell;
      const v = val(idx[a], idx[b]);
      const n = m.count[idx[a]][idx[b]];
      const t = v ? 0.12 + 0.88 * (v / max) : 0;
      svg.append(s('rect', { x: x + 1, y: y + 1, width: cell - 2, height: cell - 2, rx: 3, class: v ? 'wf-cell' : 'wf-cell wf-cell--empty', 'fill-opacity': v ? fixed(t, 3) : null }));
      svg.append(s('text', { x: x + cell / 2, y: y + cell / 2 + 4, 'text-anchor': 'middle', class: `wf-cell-text${t >= 0.6 ? ' hi' : ''}`, text: v ? int(v) : '–' }));
      svg.append(hover(s('rect', { class: 'hit', x, y, width: cell, height: cell }), () => [
        tipTitle(`${roleLabel(sender)} → ${roleLabel(receiver)}`),
        tipRow(int(n), 'messages', 'var(--topo-full_mesh)'),
        tipRow(fixed(n / m.runs, 2), 'per run'),
        m.completion_tokens_mean[idx[a]][idx[b]] != null ? tipRow(compact(m.completion_tokens_mean[idx[a]][idx[b]]), 'tokens per message (mean)') : null,
        sender === receiver && n ? tipNote('Two experts with the same role in one run.') : null,
      ]));
    });
  });
  top.replaceChildren(h('div', { class: 'legend' }, [
    h('span', {}, [h('span', { class: 'wf-ramp', 'aria-hidden': 'true' }), isCount ? `0 to ${int(max)} messages` : `0 to ${int(max)} tokens per message`]),
  ]));
  host.replaceChildren(h('div', { class: 'wf-matrix-wrap' }, svg));
}

function drawConsensus(host, width, top) {
  const { g, topos } = view();
  top.replaceChildren(legend(topos));
  const rounds = Math.max(...topos.map((t) => g[t].consensus.per_round.length));
  const M = { top: 18, right: 8, bottom: 36, left: 40 };
  const H = 220;
  const y = linear([0, 1], [H - M.bottom, M.top]);
  const groupW = (width - M.left - M.right) / rounds;
  const barW = Math.min(28, (groupW - 16) / topos.length - 2);
  const svg = svgRoot(width, H, 'Consensus rate per discussion round, per topology');
  axisLeft(svg, y, M.left, { ticks: [0, 0.25, 0.5, 0.75, 1], format: (v) => pct(v, 0), gridRight: width - M.right });
  svg.append(s('line', { class: 'baseline', x1: M.left, x2: width - M.right, y1: y(0), y2: y(0) }));
  for (let r = 0; r < rounds; r++) {
    const cx = M.left + groupW * (r + 0.5);
    svg.append(s('text', { x: cx, y: H - M.bottom + 15, 'text-anchor': 'middle', text: `Round ${r + 1}` }));
    const x0 = cx - (topos.length * (barW + 2) - 2) / 2;
    topos.forEach((t, i) => {
      const pr = g[t].consensus.per_round[r];
      const x = x0 + i * (barW + 2);
      if (!pr) return;
      const v = pr.rate || 0;
      if (v > 0) svg.append(s('path', { d: barPath(x, y(v), barW, y(0) - y(v), 3), fill: TOPO_COLOR[t] }));
      else svg.append(s('line', { x1: x, x2: x + barW, y1: y(0) - 1, y2: y(0) - 1, stroke: TOPO_COLOR[t], 'stroke-width': 2 }));
      svg.append(s('text', { x: x + barW / 2, y: y(v) - 4, 'text-anchor': 'middle', class: 'wf-val', text: pct(v, 0) }));
      svg.append(hover(s('rect', { class: 'hit', x: x - 1, y: M.top, width: barW + 2, height: y(0) - M.top }), () => [
        tipTitle(`${TOPO_LABEL[t]} · round ${r + 1}`),
        tipRow(pct(v, 1), 'agreed in this round', TOPO_COLOR[t]),
        tipNote(`${int(pr.agreed)} of ${int(pr.reached)} discussions that got this far`),
      ]));
    });
  }
  svg.append(s('text', { class: 'axis-title', x: M.left + (width - M.left - M.right) / 2, y: H - 4, 'text-anchor': 'middle', text: 'Discussion round (Star: solver iteration)' }));
  host.replaceChildren(svg);
}

function renderMessages() {
  segmented($('wfMsgMeasure'), [['count', 'Messages'], ['tokens', 'Message length']], state.msgMeasure, (v) => {
    state.msgMeasure = v;
    matrixView.rerender();
  });
  const matrixView = mount('wfMsgMatrix', drawMatrix);
  mount('wfConsensusChart', drawConsensus);
  const update = () => {
    const { g, topos } = view();
    const parts = topos.map((t) => {
      const c = g[t].consensus;
      return `${TOPO_LABEL[t]} agreed in ${pct(c.rate, 0)} of discussions (${fixed(c.rounds_mean, 1)} rounds on average)`;
    });
    let note = `${parts.join('; ')}.`;
    if (topos.includes('vertical') && g.vertical.consensus.agreed === 0) note += ' Star never reached full approval, so every Star discussion ran all three solver iterations.';
    if (topos.includes('full_mesh')) {
      const m = g.full_mesh.messages;
      note += ` A Full mesh run sends ${fixed(m.per_run, 1)} messages on average: every agent to every other agent, each round. Row and column totals follow how often each role is recruited (the summarizer rarely is).`;
    }
    $('wfMsgNote').textContent = note;
    $('wfMsgSource').textContent = sourceLine('A discussion stops at the first round where everyone agrees.');
  };
  update();
  return update;
}

// ---------------------------------------------------------------------------
// 4. Context growth
// ---------------------------------------------------------------------------

const KIND_LABEL = { discussion: '', message: '', solver: 'solver', reviewer: 'reviewers' };

function contextSeries() {
  const { g, topos } = view();
  const out = [];
  for (const t of topos) {
    for (const kind of state.data.context_kinds[t]) {
      const pts = g[t].context[kind] || [];
      if (pts.length) out.push({ t, kind, pts, label: `${TOPO_LABEL[t]}${KIND_LABEL[kind] ? ` ${KIND_LABEL[kind]}` : ''}`, dash: kind === 'reviewer' ? '5 3' : null });
    }
  }
  return out;
}

function drawContext(host, width, top) {
  const series = contextSeries();
  top.replaceChildren(h('div', { class: 'legend' }, series.map((sr) => h('span', {}, [
    h('span', { class: 'wf-key', style: `border-color:${TOPO_COLOR[sr.t]};${sr.dash ? 'border-top-style:dashed' : ''}`, 'aria-hidden': 'true' }),
    sr.label,
  ]))));
  const rounds = Math.max(...series.flatMap((sr) => sr.pts.map((p) => p.round)));
  const narrow = width < 520;
  const M = { top: 12, right: narrow ? 12 : 120, bottom: 40, left: 52 };
  const H = narrow ? 240 : 280;
  const max = Math.max(...series.flatMap((sr) => sr.pts.map((p) => p.prompt_tokens.p75)));
  const y = linear([0, niceMax(max)], [H - M.bottom, M.top]);
  const step = (width - M.left - M.right) / rounds;
  const off = Math.min(9, step / (series.length * 2.2));
  const svg = svgRoot(width, H, 'Prompt tokens per discussion call by round and topology: median and interquartile range');
  axisLeft(svg, y, M.left, { ticks: y.ticks(5), format: compact, gridRight: width - M.right, title: 'Prompt tokens per call' });
  svg.append(s('line', { class: 'baseline', x1: M.left, x2: width - M.right, y1: y(0), y2: y(0) }));
  for (let r = 1; r <= rounds; r++) {
    svg.append(s('text', { x: M.left + step * (r - 0.5), y: H - M.bottom + 15, 'text-anchor': 'middle', text: `Round ${r}` }));
  }
  series.forEach((sr, si) => {
    const dx = (si - (series.length - 1) / 2) * off;
    const px = (p) => M.left + step * (p.round - 0.5) + dx;
    const color = TOPO_COLOR[sr.t];
    svg.append(s('polyline', { points: sr.pts.map((p) => `${px(p)},${y(p.prompt_tokens.median)}`).join(' '), fill: 'none', stroke: color, 'stroke-width': 2, 'stroke-dasharray': sr.dash, 'stroke-linejoin': 'round' }));
    for (const p of sr.pts) {
      const d = p.prompt_tokens;
      svg.append(s('line', { x1: px(p), x2: px(p), y1: y(d.p25), y2: y(d.p75), stroke: color, 'stroke-width': 3, 'stroke-linecap': 'round', 'stroke-opacity': 0.45 }));
      svg.append(s('circle', { cx: px(p), cy: y(d.median), r: 4.5, fill: color, stroke: 'var(--mark-ring)', 'stroke-width': 2 }));
      svg.append(hover(s('rect', { class: 'hit', x: px(p) - 7, y: y(d.p75) - 7, width: 14, height: Math.max(14, y(d.p25) - y(d.p75) + 14) }), () => [
        tipTitle(`${sr.label} · round ${p.round}`),
        tipRow(compact(d.median), 'prompt tokens (median)', color, sr.dash ? 'dashed' : null),
        tipRow(`${compact(d.p25)} to ${compact(d.p75)}`, 'interquartile range'),
        tipRow(compact(p.completion_tokens.median), 'completion tokens (median)'),
        tipNote(`${int(d.n)} calls`),
      ]));
    }
    if (!narrow) {
      const last = sr.pts[sr.pts.length - 1];
      svg.append(s('text', { x: px(last) + 10, y: y(last.prompt_tokens.median) + 4, class: 'wf-direct', text: sr.label }));
    }
  });
  // keep end labels apart
  if (!narrow) spreadLabels(svg.querySelectorAll('.wf-direct'), 12);
  host.replaceChildren(svg);
}

function spreadLabels(nodes, minGap) {
  const items = [...nodes].map((n) => ({ n, y: +n.getAttribute('y') })).sort((a, b) => a.y - b.y);
  for (let i = 1; i < items.length; i++) {
    if (items[i].y - items[i - 1].y < minGap) items[i].y = items[i - 1].y + minGap;
  }
  items.forEach((it) => it.n.setAttribute('y', it.y));
}

function renderContext() {
  mount('wfContextChart', drawContext);
  const update = () => {
    const series = contextSeries();
    const parts = series.filter((sr) => sr.pts.length > 1).map((sr) => {
      const a = sr.pts[0].prompt_tokens.median;
      const b = sr.pts[sr.pts.length - 1].prompt_tokens.median;
      return `${sr.label} ${compact(a)} → ${compact(b)}`;
    });
    $('wfCtxNote').textContent = parts.length
      ? `Median prompt tokens from the first to the last round: ${parts.join(', ')}. Round 1 prompts carry only the task; from round 2 on, they carry the discussion so far, which levels off once the history is cut.`
      : '';
    $('wfCtxSource').textContent = sourceLine('For Star, a round is one solver iteration. Retried iterations start again at round 1.');
  };
  update();
  return update;
}

// ---------------------------------------------------------------------------
// 5. Retries
// ---------------------------------------------------------------------------

function drawRetries(host, width, top) {
  const { g, topos } = view();
  top.replaceChildren(h('div', { class: 'legend' }, [
    h('span', {}, [h('span', { class: 'wf-seg wf-seg--2', 'aria-hidden': 'true' }), '2 iterations']),
    h('span', {}, [h('span', { class: 'wf-seg wf-seg--3', 'aria-hidden': 'true' }), '3 iterations']),
  ]));
  const narrow = width < 520;
  const M = { top: 4, right: 60, bottom: 36, left: narrow ? 80 : 110 };
  const barH = 18, gap = 10;
  const H = M.top + topos.length * (barH + gap) - gap + M.bottom;
  const share = (t, k) => (g[t].retries.iterations[k] || 0) / g[t].retries.runs;
  const max = Math.max(...topos.map((t) => share(t, '2') + share(t, '3')));
  const x = linear([0, niceMax(Math.max(max, 0.05))], [M.left, width - M.right]);
  const svg = svgRoot(width, H, 'Share of runs that needed a second or third iteration, per topology');
  axisBottom(svg, x, H - M.bottom, { ticks: x.ticks(narrow ? 3 : 5), format: (v) => pct(v, 0), gridTop: M.top, title: 'Runs that needed a retry' });
  topos.forEach((t, i) => {
    const y = M.top + i * (barH + gap);
    const a = share(t, '2'), b = share(t, '3');
    svg.append(s('text', { x: M.left - 8, y: y + barH / 2 + 4, 'text-anchor': 'end', class: 'wf-cat', text: TOPO_LABEL[t] }));
    const wa = x(a) - x(0);
    const wb = x(a + b) - x(a);
    if (wa > 0) svg.append(s('rect', { x: x(0), y, width: Math.max(0, wa - (wb > 0 ? 1 : 0)), height: barH, fill: TOPO_COLOR[t] }));
    if (wb > 0) svg.append(s('path', { d: barPath(x(a) + 1, y, Math.max(0, wb - 1), barH, 4, 'right'), fill: TOPO_COLOR[t], 'fill-opacity': 0.45 }));
    svg.append(s('text', { x: x(a + b) + 6, y: y + barH / 2 + 4, class: 'wf-val', text: pct(a + b, 0) }));
    svg.append(hover(s('rect', { class: 'hit', x: M.left, y, width: width - M.left - 4, height: barH }), () => {
      const r = g[t].retries;
      return [
        tipTitle(TOPO_LABEL[t]),
        tipRow(pct(a, 1), 'needed 2 iterations', TOPO_COLOR[t]),
        tipRow(pct(b, 1), 'needed 3 iterations'),
        tipRow(pct(r.never_accepted / r.runs, 1), 'never accepted'),
        tipNote(`${int(r.runs)} runs`),
      ];
    }));
  });
  host.replaceChildren(svg);
}

function renderRetryTable() {
  const { g, topos } = view();
  const rows = topos.map((t) => {
    const r = g[t].retries;
    const na = r.not_accepted;
    const c1 = r.cost.first, c2 = r.cost.retry;
    return [
      h('span', {}, [swatch(t), TOPO_LABEL[t]]),
      na.iterations ? pct(na.unscored / na.iterations, 0) : '–',
      c2.n ? `${fixed(c2.calls, 0)} · ${compact(c2.tokens)} · ${seconds(c2.time_s)}` : '–',
      `${fixed(c1.calls, 0)} · ${compact(c1.tokens)} · ${seconds(c1.time_s)}`,
      r.retried_final_score.n ? fixed(r.retried_final_score.mean, 1) : '–',
      pct(r.never_accepted / r.runs, 1),
    ];
  });
  $('wfRetryTable').replaceChildren(dataTable(
    ['Topology', 'Rejections with no usable score', 'One retry (calls · tokens · time)', 'First iteration (calls · tokens · time)', 'Final score after a retry', 'Never accepted'],
    rows, { caption: 'Why runs are retried and what a retry costs', numeric: [1, 4, 5] },
  ));
}

function renderRetries() {
  mount('wfRetryChart', drawRetries);
  const update = () => {
    renderRetryTable();
    $('wfRetrySource').textContent = sourceLine('Cost is per iteration. "No usable score": the evaluator\'s reply could not be read.');
  };
  update();
  return update;
}

// ---------------------------------------------------------------------------
// 6. Quality vs cost
// ---------------------------------------------------------------------------

const QUAL_COSTS = [
  ['tokens', 'Tokens', 'Tokens per run', compact],
  ['calls', 'LLM calls', 'LLM calls per run', (v) => fixed(v, 0)],
  ['span_s', 'Run length', 'Run length', seconds],
];

function drawQuality(host, width, top) {
  const { g, topos } = view();
  const [key, , axisLabel, fmt] = QUAL_COSTS.find((c) => c[0] === state.qualCost);
  top.replaceChildren(legend(topos));
  const narrow = width < 520;
  const M = { top: 14, right: narrow ? 16 : 24, bottom: 40, left: 46 };
  const H = narrow ? 240 : 280;
  const qs = topos.map((t) => ({ t, q: g[t].quality })).filter((d) => d.q.score.n);
  const lo = Math.min(...qs.map((d) => d.q.score_ci95?.[0] ?? d.q.score.mean));
  const hi = Math.max(...qs.map((d) => d.q.score_ci95?.[1] ?? d.q.score.mean));
  const y = linear([Math.floor(lo - 0.5), Math.ceil(hi + 0.5)], [H - M.bottom, M.top]);
  const xMax = niceMax(Math.max(...qs.map((d) => d.q[key].p75)));
  const x = linear([0, xMax], [M.left, width - M.right]);
  const svg = svgRoot(width, H, `Mean evaluation score against ${axisLabel.toLowerCase()}, per topology`);
  axisLeft(svg, y, M.left, { ticks: y.ticks(4), format: (v) => fixed(v, 0), gridRight: width - M.right, title: 'Mean score' });
  axisBottom(svg, x, H - M.bottom, { ticks: x.ticks(narrow ? 3 : 5), format: key === 'span_s' ? (v) => `${v} s` : compact, title: `${axisLabel} (median, IQR)` });
  for (const { t, q } of qs) {
    const color = TOPO_COLOR[t];
    const cx = x(q[key].median), cy = y(q.score.mean);
    svg.append(s('line', { x1: x(q[key].p25), x2: x(q[key].p75), y1: cy, y2: cy, stroke: color, 'stroke-width': 2, 'stroke-opacity': 0.6 }));
    if (q.score_ci95) svg.append(s('line', { x1: cx, x2: cx, y1: y(q.score_ci95[0]), y2: y(q.score_ci95[1]), stroke: color, 'stroke-width': 2, 'stroke-opacity': 0.6 }));
    svg.append(s('circle', { cx, cy, r: 6, fill: color, stroke: 'var(--mark-ring)', 'stroke-width': 2 }));
    svg.append(s('text', { x: cx + 9, y: cy - 8, class: 'wf-direct', text: TOPO_LABEL[t] }));
    svg.append(hover(s('circle', { class: 'hit', cx, cy, r: 14 }), () => [
      tipTitle(TOPO_LABEL[t]),
      tipRow(fixed(q.score.mean, 1), `mean score (95% CI ${fixed(q.score_ci95[0], 1)} to ${fixed(q.score_ci95[1], 1)})`, color),
      tipRow(pct(q.goal_rate, 1), 'goal achieved'),
      tipRow(fmt(q[key].median), `${axisLabel.toLowerCase()} (median)`),
      tipNote(`${int(q.scored)} scored runs${q.unscored ? `, ${int(q.unscored)} without a usable score` : ''}`),
    ]));
  }
  spreadLabels(svg.querySelectorAll('.wf-direct'), 13);
  host.replaceChildren(svg);
}

function renderQualityTable() {
  const { g, topos } = view();
  const rows = topos.map((t) => {
    const q = g[t].quality;
    return [
      h('span', {}, [swatch(t), TOPO_LABEL[t]]),
      q.score_ci95 ? `${fixed(q.score.mean, 1)} (${fixed(q.score_ci95[0], 1)} to ${fixed(q.score_ci95[1], 1)})` : '–',
      fixed(q.score.median, 0),
      pct(q.goal_rate, 1),
      compact(q.tokens.median),
      fixed(q.calls.median, 0),
      seconds(q.span_s.median),
      q.rho.tokens == null ? '–' : fixed(q.rho.tokens, 2),
    ];
  });
  $('wfQualTable').replaceChildren(dataTable(
    ['Topology', 'Mean score (95% CI)', 'Median score', 'Goal achieved', 'Tokens', 'Calls', 'Run length', 'ρ score vs tokens'],
    rows, { caption: 'Evaluation score and cost per topology (medians for the costs)', numeric: [1, 2, 3, 4, 5, 6, 7] },
  ));
}

function renderQuality() {
  segmented($('wfQualCost'), QUAL_COSTS.map(([k, l]) => [k, l]), state.qualCost, (v) => {
    state.qualCost = v;
    qualView.rerender();
  });
  const qualView = mount('wfQualityChart', drawQuality);
  const update = () => {
    renderQualityTable();
    const { g, topos } = view();
    const qs = topos.map((t) => [t, g[t].quality]).filter(([, q]) => q.score.n);
    let note = '';
    if (qs.length) {
      const means = qs.map(([, q]) => q.score.mean);
      const at92 = qs.reduce((a, [, q]) => a + (q.score_counts['92'] || 0), 0) / qs.reduce((a, [, q]) => a + q.scored, 0);
      const rhos = qs.map(([, q]) => q.rho.tokens).filter((r) => r != null);
      note = `Mean scores lie between ${fixed(Math.min(...means), 1)} and ${fixed(Math.max(...means), 1)}, and ${pct(at92, 0)} of scored runs got exactly 92, so the evaluator barely tells the answers apart.`;
      if (rhos.length) note += ` Within a topology, spending more tokens hardly moves the score (Spearman ρ ${fixed(Math.min(...rhos), 2)} to ${fixed(Math.max(...rhos), 2)}).`;
      const fm = g.full_mesh?.quality, sq = g.horizontal?.quality;
      if (topos.includes('full_mesh') && topos.includes('horizontal') && fm && sq) {
        note += ` Full mesh makes ${fixed(fm.calls.median / sq.calls.median, 1)}× as many calls as Sequential for a mean score ${fm.score.mean >= sq.score.mean ? 'no better' : 'slightly lower'} (${fixed(fm.score.mean, 1)} vs ${fixed(sq.score.mean, 1)}): its extra traffic buys speed (parallel messages), not quality.`;
      }
    }
    $('wfQualNote').textContent = note;
    $('wfQualSource').textContent = sourceLine('Score from the final evaluation; runs without a usable score are left out.');
  };
  update();
  return update;
}

// ---------------------------------------------------------------------------
// Entry
// ---------------------------------------------------------------------------

function failAll(err) {
  for (const id of ['wfStagesChart', 'wfRolesChart', 'wfMsgMatrix', 'wfContextChart', 'wfRetryChart', 'wfQualityChart']) {
    $(id)?.replaceChildren(h('p', { class: 'placeholder', text: `Could not load the workflow data (${err.message}).` }));
  }
}

const ANCHOR = {
  stages: 'wfStagesChart', roles: 'wfRolesChart', messages: 'wfMsgMatrix',
  context: 'wfContextChart', retries: 'wfRetryChart', quality: 'wfQualityChart',
};

async function main() {
  if (!$('workflowSections')) return;
  try {
    state.data = await loadData('workflow.json');
  } catch (err) {
    console.error('[workflow] could not load data:', err);
    failAll(err);
    return;
  }
  const updates = [];
  for (const [name, fn] of [['stages', renderStages], ['roles', renderRoles], ['messages', renderMessages],
    ['context', renderContext], ['retries', renderRetries], ['quality', renderQuality]]) {
    try {
      if (!$(ANCHOR[name])) continue; // stages and roles are on System load, the rest on the Beta page
      updates.push(fn());
    } catch (err) {
      console.error(`[workflow] ${name} failed:`, err);
    }
  }
  onFilterChange((f) => {
    state.filter = f;
    views.forEach((v) => v.rerender());
    updates.forEach((u) => u());
  });
  $('workflowSections').dataset.ready = 'true';
}

main();
