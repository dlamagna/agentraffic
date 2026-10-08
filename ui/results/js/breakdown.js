/**
 * Task breakdown (metric picker; median + IQR per topology x task, narrowed by the filter
 * bar's topologies and task; System page), agent-count scaling (full mesh with 3 / 4 / 5
 * agents; Traffic page). The System page's network flows are re-exported from load.js.
 */

import {
  h, s, svgRoot, linear, log10, axisBottom, niceTicks, responsive, showTip, hideTip, tipTitle,
  tipRow, tipNote, metricInfo, formatMetric, dataTable, TOPOS, TOPO_LABEL, TOPO_COLOR,
  swatch, fixed, int, pct, seconds, compact, logTimeLabel,
} from './util.js';
import { renderScalingHistograms } from './iat.js';
import { getFilter, onFilterChange } from './shell.js';

const SHORT_TASK = { math: 'Math', research: 'Research', consulting: 'Consulting', coding: 'Software dev.' };
const LAYER_LABEL = { application: 'Application', llm: 'LLM backend', traffic: 'Traffic', network: 'Network' };

function domainFor(values) {
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  if (lo > 0 && hi / lo > 30) {
    return { log: true, d: [10 ** Math.floor(Math.log10(lo)), 10 ** Math.ceil(Math.log10(hi))] };
  }
  const t = niceTicks(Math.min(0, lo), hi, 5);
  const step = t.length > 1 ? t[1] - t[0] : 1;
  const top = t[t.length - 1] >= hi ? t[t.length - 1] : t[t.length - 1] + step;
  return { log: false, d: [Math.min(0, lo, t[0]), top] };
}

// ---------------------------------------------------------------------------
// Task breakdown
// ---------------------------------------------------------------------------

export function renderTaskBreakdown(summary) {
  const info = metricInfo(summary);
  const sel = document.getElementById('taskMetric');
  for (const layer of summary.layers) {
    const og = h('optgroup', { label: LAYER_LABEL[layer] || layer });
    for (const m of summary.metrics) {
      if (m.layer !== layer || info.get(m.key).dim) continue;
      og.append(h('option', { value: m.key, text: m.label }));
    }
    sel.append(og);
  }
  sel.value = 'disc_mean_iat_s';
  let filter = getFilter();
  const view = () => ({
    topos: TOPOS.filter((t) => filter.topos.has(t)),
    groups: [{ key: null, label: 'All tasks' }, ...summary.tasks.filter((t) => !filter.task || t.key === filter.task)],
  });
  const host = document.getElementById('taskChart');
  const tableHost = h('details', { class: 'explain' }, [h('summary', { text: 'Show as a table' })]);
  const chart = h('div', { class: 'chart-body' });
  const legend = h('div', { class: 'legend' });
  host.replaceChildren(legend, chart, tableHost);
  const handle = responsive(chart, (w) => drawTaskChart(chart, w, summary, info.get(sel.value), view()));
  const update = () => {
    handle.rerender();
    const m = info.get(sel.value);
    const { topos, groups } = view();
    legend.replaceChildren(...topos.map((t) => h('span', {}, [swatch(t), TOPO_LABEL[t]])));
    const rows = [];
    for (const task of groups) {
      for (const t of topos) {
        const a = task.key ? summary.aggregates.by_topology_task[t][task.key][m.key] : summary.aggregates.by_topology[t][m.key];
        rows.push([`${task.label} · ${TOPO_LABEL[t]}`, formatMetric(a.median, m.unit), `${formatMetric(a.p25, m.unit)} – ${formatMetric(a.p75, m.unit)}`, int(a.n)]);
      }
    }
    tableHost.replaceChildren(h('summary', { text: 'Show as a table' }), h('div', { class: 'table-wrap' },
      dataTable(['Task · topology', 'Median', 'IQR', 'Runs'], rows, { caption: `${m.label} by topology and task`, numeric: [1, 3] })));
    document.getElementById('taskSource').textContent = '';
  };
  sel.addEventListener('change', update);
  onFilterChange((f) => { filter = f; update(); });
  update();
}

function drawTaskChart(host, width, summary, m, { topos, groups }) {
  const cells = groups.map((task) => topos.map((t) => ({
    task, t,
    a: task.key ? summary.aggregates.by_topology_task[t][task.key][m.key] : summary.aggregates.by_topology[t][m.key],
  })));
  const values = cells.flat().flatMap((c) => [c.a.p25, c.a.p75, c.a.median]).filter((v) => v != null);
  const { log, d } = domainFor(values);
  const narrow = width < 520;
  const M = { top: 6, right: 16, bottom: 40, left: narrow ? 92 : 130 };
  const rowH = 14;
  const groupGap = 14;
  const H = M.top + groups.length * (topos.length * rowH + groupGap) + M.bottom;
  const svg = svgRoot(width, H, `${m.label}: median and interquartile range per topology and task`);
  const x = (log ? log10 : linear)(d, [M.left, width - M.right]);
  const g = s('g');
  svg.append(g);
  const yEnd = H - M.bottom;
  axisBottom(g, x, yEnd, {
    ticks: log ? x.ticks() : x.ticks(narrow ? 4 : 6),
    format: (v) => (m.unit === 's' ? (v === 0 ? '0' : logTimeLabel(v)) : compact(v)),
    gridTop: M.top,
    title: `${m.label}${m.unit && m.unit !== 'ratio' && m.unit !== 's' ? ` (${m.unit})` : ''}${log ? ', log scale' : ''}`,
    titleY: 32,
  });
  let y = M.top;
  cells.forEach((row, gi) => {
    const y0 = y;
    g.append(s('text', {
      x: M.left - 10, y: y0 + (topos.length / 2) * rowH + 4, 'text-anchor': 'end',
      style: `fill:var(--chart-label);font-size:11.5px;${gi === 0 ? 'font-weight:700' : ''}`,
      text: narrow && row[0].task.key ? SHORT_TASK[row[0].task.key] || row[0].task.label : row[0].task.label,
    }));
    row.forEach((c, i) => {
      const cy = y0 + i * rowH + rowH / 2;
      const color = TOPO_COLOR[c.t];
      g.append(s('line', { x1: x(c.a.p25), x2: x(c.a.p75), y1: cy, y2: cy, stroke: color, 'stroke-width': 3, 'stroke-linecap': 'round' }));
      g.append(s('circle', { cx: x(c.a.median), cy, r: 4.5, fill: color, stroke: 'var(--mark-ring)', 'stroke-width': 2 }));
      const hit = s('rect', { class: 'hit', x: M.left, y: cy - rowH / 2, width: width - M.left - M.right, height: rowH });
      hit.addEventListener('pointermove', (ev) => showTip([
        tipTitle(`${c.task.label} · ${TOPO_LABEL[c.t]}`),
        tipRow(formatMetric(c.a.median, m.unit), 'median', color),
        tipRow(`${formatMetric(c.a.p25, m.unit)} – ${formatMetric(c.a.p75, m.unit)}`, 'interquartile range'),
        tipNote(`${int(c.a.n)} runs`),
      ], ev.clientX, ev.clientY));
      hit.addEventListener('pointerleave', hideTip);
      g.append(hit);
    });
    y += topos.length * rowH + groupGap;
    if (gi === 0) g.append(s('line', { x1: 8, x2: width - M.right, y1: y - groupGap / 2, y2: y - groupGap / 2, stroke: 'var(--border)' }));
  });
  host.replaceChildren(svg);
}

// ---------------------------------------------------------------------------
// Agent-count scaling
// ---------------------------------------------------------------------------

export function renderScaling(summary) {
  renderScalingHistograms(document.getElementById('scalingCharts'), summary);
  const agents = summary.scaling.agents;
  const rows = [
    ['Runs', ...agents.map((a) => int(a.n_runs))],
    ['Peer messages per round', ...agents.map((a) => String(a.n_agents * (a.n_agents - 1)))],
    ['Discussion IATs', ...agents.map((a) => int(a.n))],
    ['Burst fraction (< 50 ms)', ...agents.map((a) => pct(a.burst_fraction))],
    ['Median IAT', ...agents.map((a) => seconds(a.median_s))],
    ['Mean IAT', ...agents.map((a) => seconds(a.mean_s))],
    ['IAT p95', ...agents.map((a) => seconds(a.p95_s))],
    ['Log-normal fit, IAT > 50 ms (μ, σ)', ...agents.map((a) => `${fixed(a.lognormal_reasoning.mu, 2)}, ${fixed(a.lognormal_reasoning.sigma, 2)}`)],
    ['Discussion calls / run (mean)', ...agents.map((a) => fixed(a.means.disc_n_requests, 1))],
    ['Discussion tokens / run (mean)', ...agents.map((a) => compact(a.means.disc_total_tokens))],
    ['Mean in-flight calls', ...agents.map((a) => fixed(a.means.llm_inflight_mean, 2))],
    ['Prompt tokens/s', ...agents.map((a) => compact(a.means.prompt_tokens_per_s_mean))],
  ];
  document.getElementById('scalingTable').replaceChildren(
    dataTable(['Full mesh', ...agents.map((a) => `${a.n_agents} agents`)], rows, { caption: 'Full mesh scaling with agent count', numeric: [1, 2, 3] }),
  );
  document.getElementById('scalingSource').textContent =
    'Curves: log-normal fitted to the gaps above 50 ms. Same y scale in all three panels.';
}

// ---------------------------------------------------------------------------
// Network: the flow diagram lives in load.js (System page); main.js keeps
// calling renderNetwork, so the section is drawn before the page reports ready.
// ---------------------------------------------------------------------------

export { renderNetworkFlows as renderNetwork } from './load.js';
