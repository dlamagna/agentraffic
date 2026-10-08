/**
 * Run explorer: a filterable, sortable, paged table of all runs (runs.json, lazy) and a
 * drill-down for one run: stat tiles, a Gantt of its LLM calls by agent (stages shaded,
 * discussion highlighted), in-flight calls over time, and its metrics against the topology
 * median, and its inter-arrival times (the charts are shared with the workflow runner, see
 * run-charts.js; this file adds the zoom). Deep link: #run=<id>. Demo fixtures link to their replay and viewer pages.
 * Topology and task come from the filter bar (shell.js); the table has its own iteration,
 * run id and demo-run filters.
 */

import {
  h, loadRuns, runsError, metricInfo, formatMetric, TOPOS, TOPO_LABEL, STAGE_LABEL,
  swatch, fixed, int, ms,
} from './util.js';
import { buildRunAnalysis, concurrency, iterationsOf, roleOf } from './run-charts.js';
import { getFilter, onFilterChange, badge } from './shell.js';
import { clipGroup, effectiveDomain, attachBrush, onRange, setRange, zoomBar } from './zoom.js';
import { siteHref } from '../../common/js/nav.js';
import { noticeElement, modeLabels } from '../../common/js/mode.js';

const PAGE = 20;
const COLUMNS = [
  { key: 'id', label: 'Run', get: (r) => r.id, type: 'str' },
  { key: 'topology', label: 'Topology', get: (r) => TOPOS.indexOf(r.topology), type: 'num' },
  { key: 'task', label: 'Task', get: (r) => r.task, type: 'str', cls: 'hide-sm' },
  { key: 'score', label: 'Score', get: (r) => r.score, type: 'num', num: true },
  { key: 'iterations', label: 'Iter.', get: (r) => r.iterations, type: 'num', num: true, cls: 'hide-sm' },
  { key: 'disc_n_requests', label: 'Disc. calls', metric: true, num: true, cls: 'hide-sm' },
  { key: 'disc_duration_s', label: 'Disc. time', metric: true, num: true },
  { key: 'disc_total_tokens', label: 'Tokens', metric: true, num: true, cls: 'hide-sm' },
  { key: 'disc_mean_iat_s', label: 'Mean IAT', metric: true, num: true, cls: 'hide-sm' },
  { key: 'llm_inflight_mean', label: 'In-flight', metric: true, num: true, cls: 'hide-sm' },
  { key: 'tcp_bytes_llm_mean_Bps', label: 'LLM TCP', metric: true, num: true, cls: 'hide-sm' },
];
const state = { filter: getFilter(), iter: '', search: '', fixtures: false, flagged: false, sort: 'id', dir: 1, page: 0, selected: null };
let summary;
let info;
let taskLabel;
let data = null;
let detailHandles = [];
let detailUnsubs = []; // zoom subscriptions of the open drill-down

export function renderRuns(sum) {
  summary = sum;
  info = metricInfo(summary);
  taskLabel = Object.fromEntries(summary.tasks.map((t) => [t.key, t.label]));

  const bind = (id, key, ev = 'change', read = (el) => el.value) => {
    const el = document.getElementById(id);
    el.addEventListener(ev, () => { state[key] = read(el); state.page = 0; renderTable(); });
  };
  onFilterChange((f) => { state.filter = f; state.page = 0; renderTable(); });
  bind('runIter', 'iter');
  bind('runSearch', 'search', 'input', (el) => el.value.trim().toLowerCase());
  bind('runFixtures', 'fixtures', 'change', (el) => el.checked);
  bind('runFlagged', 'flagged', 'change', (el) => el.checked);

  document.getElementById('runLoad').addEventListener('click', () => ensureTable());
  // Fetch runs.json when the section comes near the viewport (not on page open).
  const io = new IntersectionObserver((entries) => {
    if (entries.some((e) => e.isIntersecting)) { io.disconnect(); ensureTable(); }
  }, { rootMargin: '300px 0px' });
  io.observe(document.getElementById('runs'));
}

async function ensureData() {
  if (!data) data = await loadRuns();
  return data;
}

async function ensureTable() {
  const host = document.getElementById('runTable');
  if (host.querySelector('table')) return;
  host.replaceChildren(h('p', { class: 'loading', text: 'Loading runs (2.3 MB)…' }));
  try {
    await ensureData();
  } catch (err) {
    host.replaceChildren(h('p', { class: 'placeholder', text: runsError(err) }));
    return;
  }
  renderTable();
}

function filtered() {
  const col = COLUMNS.find((c) => c.key === state.sort);
  const get = col.metric ? (r) => r.m[col.key] : col.get;
  const { topos, task } = state.filter;
  const rows = data.runs.filter((r) => topos.has(r.topology)
    && (!task || r.task === task)
    && (!state.iter || r.iterations === Number(state.iter))
    && (!state.fixtures || r.fixture)
    && (!state.flagged || r.flags)
    && (!state.search || r.id.includes(state.search) || r.task_id.includes(state.search)));
  rows.sort((a, b) => {
    const va = get(a);
    const vb = get(b);
    if (va == null && vb == null) return 0;
    if (va == null) return 1;
    if (vb == null) return -1;
    const c = typeof va === 'string' ? va.localeCompare(vb) : va - vb;
    return c * state.dir || a.id.localeCompare(b.id);
  });
  return rows;
}

function renderTable() {
  if (!data) return;
  const rows = filtered();
  const pages = Math.max(1, Math.ceil(rows.length / PAGE));
  state.page = Math.min(state.page, pages - 1);
  const slice = rows.slice(state.page * PAGE, state.page * PAGE + PAGE);

  const table = h('table', { class: 'data runs' });
  table.append(h('caption', { class: 'visually-hidden', text: 'Recorded runs. Activate a run id to open its details.' }));
  table.append(h('thead', {}, h('tr', {}, COLUMNS.map((c) => {
    const btn = h('button', { type: 'button', text: c.label });
    btn.addEventListener('click', () => {
      if (state.sort === c.key) state.dir = -state.dir;
      else { state.sort = c.key; state.dir = c.num ? -1 : 1; }
      renderTable();
      document.querySelector(`#runTable th[data-col="${c.key}"] button`)?.focus();
    });
    return h('th', {
      scope: 'col', 'data-col': c.key, class: [c.num ? 'num' : '', c.cls || ''].join(' ').trim() || null,
      'aria-sort': state.sort === c.key ? (state.dir > 0 ? 'ascending' : 'descending') : null,
    }, btn);
  }))));
  const body = h('tbody');
  for (const r of slice) {
    const link = h('a', { href: `#run=${r.id}`, text: r.id });
    const cells = COLUMNS.map((c) => {
      let content;
      if (c.key === 'id') content = [link, r.fixture ? h('span', { class: 'tag tag--fixture', text: 'demo' }) : null, flagTag(r)];
      else if (c.key === 'topology') content = [swatch(r.topology), TOPO_LABEL[r.topology]];
      else if (c.key === 'task') content = taskLabel[r.task];
      else if (c.key === 'score') content = String(r.score);
      else if (c.key === 'iterations') content = String(r.iterations);
      else content = formatMetric(r.m[c.key], info.get(c.key).unit, c.key);
      return h('td', { class: [c.num ? 'num' : '', c.cls || '', c.key === 'topology' ? 'topo' : ''].join(' ').trim() || null }, content);
    });
    const tr = h('tr', { 'data-run': r.id, class: state.selected === r.id ? 'selected' : null }, cells);
    tr.addEventListener('click', (ev) => {
      if (ev.target.closest('a')) return; // the link updates the hash itself
      openRun(r.id, { scroll: true });
    });
    body.append(tr);
  }
  if (!slice.length) body.append(h('tr', {}, h('td', { colspan: COLUMNS.length, text: 'No runs match these filters.' })));
  table.append(body);
  document.getElementById('runTable').replaceChildren(table);

  document.getElementById('runCount').textContent =
    `${int(rows.length)} of ${int(data.runs.length)} runs${rows.length > PAGE ? ` · showing ${state.page * PAGE + 1}–${state.page * PAGE + slice.length}` : ''}`;
  const pager = document.getElementById('runPager');
  const prev = h('button', { type: 'button', class: 'btn btn--ghost btn--small', text: '← Previous', disabled: state.page === 0 });
  const next = h('button', { type: 'button', class: 'btn btn--ghost btn--small', text: 'Next →', disabled: state.page >= pages - 1 });
  prev.addEventListener('click', () => { state.page--; renderTable(); });
  next.addEventListener('click', () => { state.page++; renderTable(); });
  pager.replaceChildren(prev, h('span', { text: `Page ${state.page + 1} of ${pages}` }), next);
}

/** Outlier flags (scripts/demo/analysis_outliers.py): rule labels from runs.json. */
function flagLabel(rule) {
  return data?.outliers?.rules.find((r) => r.key === rule)?.label || rule;
}

function flagTag(run) {
  if (!run.flags) return null;
  const labels = run.flags.map((f) => flagLabel(f.rule));
  return h('span', { class: 'tag tag--flag', title: `Unusual: ${labels.join(', ')}`, text: run.flags.length > 1 ? `${run.flags.length} flags` : 'flag' });
}

// ---------------------------------------------------------------------------
// Deep links
// ---------------------------------------------------------------------------

export function openRunFromHash() {
  const m = /^#run=([0-9a-z-]+)(?:&.*)?$/i.exec(window.location.hash); // may carry &tzoom= (zoom.js)
  if (!m) return;
  const id = m[1].toLowerCase();
  // synthetic ids (syn-0001d4eb) are whole; private UUIDs are shortened to their 8-character id
  openRun(id.startsWith('syn-') ? id : id.slice(0, 8), { scroll: true, fromHash: true });
}

export async function openRun(id, { scroll = false, fromHash = false } = {}) {
  const detail = document.getElementById('runDetail');
  detail.hidden = false;
  if (!data) detail.replaceChildren(h('p', { class: 'loading', text: 'Loading runs (2.3 MB)…' }));
  try {
    await ensureData();
  } catch (err) {
    detail.replaceChildren(h('p', { class: 'placeholder', text: runsError(err) }));
    return;
  }
  if (!document.querySelector('#runTable table')) renderTable();
  const run = data.byId.get(id);
  if (!run) {
    detail.replaceChildren(h('p', { class: 'placeholder', text: `No run with id ${id}.` }));
    return;
  }
  // another run: its time range does not carry over (the first load keeps a shared #run=..&tzoom=..)
  if (state.selected !== id && !(fromHash && /[#&]tzoom=/.test(window.location.hash))) setRange('time', null);
  if (!fromHash && window.location.hash !== `#run=${id}`) {
    history.replaceState(null, '', `#run=${id}`);
  }
  state.selected = id;
  document.querySelectorAll('#runTable tr[data-run]').forEach((tr) => tr.classList.toggle('selected', tr.dataset.run === id));
  renderDetail(run);
  if (scroll) {
    detail.scrollIntoView({ block: 'start', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
    detail.focus({ preventScroll: true });
  }
}

// ---------------------------------------------------------------------------
// Drill-down
// ---------------------------------------------------------------------------

/** The drill-down's brush-to-zoom (zoom.js), handed to the shared charts (run-charts.js). */
const ZOOM = { domain: (full) => effectiveDomain('time', full), clip: clipGroup, brush: attachBrush };

function renderDetail(run) {
  detailHandles.forEach((hd) => hd.disconnect());
  detailHandles = [];
  detailUnsubs.forEach((off) => off());
  detailUnsubs = [];
  const detail = document.getElementById('runDetail');
  const calls = run.calls;
  const stages = data.stage_codes;
  const end = Math.max(...calls.map((c) => c[0] + c[1]));
  // the experiment folder is shown for a real run only, never for a synthetic one
  const experiment = data.experiments[run.experiment];
  const synthetic = Boolean(run.synthetic || data.synthetic);

  const actions = h('div', { class: 'run-actions' });
  if (run.fixture) {
    actions.append(
      h('a', { class: 'btn btn--small', href: siteHref(`playground/run/?replay=${run.topology}/${run.task}`), 'data-action': 'replay', text: '▶ Replay in AgentVerse' }),
      h('a', { class: 'btn btn--ghost btn--small', href: siteHref(`playground/open/?demo=1&task_id=${run.task_id}`), 'data-action': 'view', text: 'View recorded run' }),
    );
  }
  const close = h('button', { type: 'button', class: 'btn btn--ghost btn--small', text: 'Close' });
  close.addEventListener('click', () => {
    detail.hidden = true;
    state.selected = null;
    document.querySelectorAll('#runTable tr.selected').forEach((tr) => tr.classList.remove('selected'));
    setRange('time', null, { fromHash: true });
    history.replaceState(null, '', window.location.pathname + window.location.search);
    document.getElementById('runsTitle').scrollIntoView({ block: 'start' });
  });
  actions.append(close);

  const header = h('div', { class: 'run-head' }, [
    h('div', {}, [
      h('h3', {}, ['Run ', h('code', { text: run.id }), swatch(run.topology), TOPO_LABEL[run.topology], ' · ', taskLabel[run.task],
        run.fixture ? h('span', { class: 'tag tag--fixture', text: 'demo run' }) : null, badge('runs')]),
      h('p', { class: 'run-task', text: synthetic ? `${modeLabels({ mode: 'public' }).runKind} ${run.task_id}, generated to illustrate the UI` : `${experiment} · task ${run.task_id}` }),
    ]),
    actions,
  ]);

  const flagNote = run.flags
    ? h('div', { class: 'callout callout--flag', 'data-run-flags': '' }, [
      h('strong', { text: 'Unusual for its topology. ' }),
      h('ul', { class: 'outlier-reasons' }, run.flags.map((f) => h('li', {}, [
        h('span', { class: 'tag tag--flag', text: flagLabel(f.rule) }), ' ', f.reason,
      ]))),
    ])
    : null;

  const zoomHost = h('div', { 'data-chart': 'time-zoom' });
  const view = buildRunAnalysis(run, { summary, info, stages, zoom: ZOOM, before: [zoomHost] });

  detail.replaceChildren(
    header,
    ...(synthetic ? [noticeElement('runs')] : []),
    view.tiles,
    flagNote,
    h('div', { class: 'detail-grid' }, [view.gantt, view.conc, view.metrics, view.iat, callsTable(run, stages)]),
    h('p', { class: 'source', text: 'Times are relative to the run’s first LLM call.' }),
  );

  const { handles, ganttH, concH } = view.mount();
  detailHandles.push(...handles);
  detailUnsubs.push(onRange('time', () => { ganttH.rerender(); concH.rerender(); }));
  const secs = (v) => `${+(v / 1000).toPrecision(3)} s`;
  const allConc = concurrency(calls);
  zoomBar(zoomHost, {
    axis: 'time',
    hint: 'Drag on the chart to zoom into a span of the run; the in-flight chart below follows it.',
    describe: ([a, b]) => `${secs(a)} to ${secs(b)} since the first call (both charts of this run)`,
    readout: ([a, b]) => {
      const started = calls.filter((c) => c[0] >= a && c[0] < b);
      let peak = 0;
      allConc.pts.forEach(([tt, v], i) => {
        const next = i + 1 < allConc.pts.length ? allConc.pts[i + 1][0] : end;
        if (next > a && tt < b) peak = Math.max(peak, v);
      });
      return [
        { label: 'Calls started', text: `${started.length} of ${calls.length} (${started.filter((c) => c[2] === 1).length} in the discussion)` },
        { label: 'Peak in flight', text: String(peak) },
      ];
    },
  });
}

function callsTable(run, stages) {
  const iters = iterationsOf(run.calls);
  const det = h('details', { class: 'explain toggle-table' }, [h('summary', { text: `All ${run.calls.length} LLM calls as a table` })]);
  det.addEventListener('toggle', () => {
    if (!det.open || det.querySelector('table')) return;
    const table = h('table', { class: 'data' });
    table.append(h('thead', {}, h('tr', {}, ['#', 'Start', 'Duration', 'Stage', 'Agent', 'Round', 'Tokens (in + out)', 'TTFT']
      .map((t, i) => h('th', { scope: 'col', class: [1, 2, 6, 7].includes(i) ? 'num' : null, text: t })))));
    const body = h('tbody');
    run.calls.forEach((c, i) => {
      const who = roleOf(run, iters[i], c[3]);
      const peer = c[4] >= 0 ? ` → ${roleOf(run, iters[i], c[4])}` : '';
      body.append(h('tr', {}, [
        h('th', { scope: 'row', text: String(i + 1) }),
        h('td', { class: 'num', text: `${fixed(c[0] / 1000, 3)} s` }),
        h('td', { class: 'num', text: ms(c[1]) }),
        h('td', { text: STAGE_LABEL[stages[c[2]]] || stages[c[2]] }),
        h('td', { text: `${who}${peer}` }),
        h('td', { text: c[5] == null ? '–' : String(c[5]) }),
        h('td', { class: 'num', text: `${int(c[6])} + ${int(c[7])}` }),
        h('td', { class: 'num', text: c[8] == null ? '–' : `${fixed(c[8], 0)} ms` }),
      ]));
    });
    table.append(body);
    det.append(h('div', { class: 'calls-table table-wrap' }, table));
  });
  return det;
}
