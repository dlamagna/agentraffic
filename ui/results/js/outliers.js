/**
 * Unusual runs: the runs that scripts/demo/analysis_outliers.py
 * flagged in runs.json (`outliers` at the top level, `flags` on each flagged run). A chip per
 * rule with its count, the per-topology limits, and a paged list of flagged runs; a run id opens
 * the drill-down (#run=<id>, handled by runs.js). Honours the filter bar (topology + task).
 * Loaded only by results/run-explorer/; runs.json is shared with runs.js (util.loadRuns).
 */

import { h, loadRuns, runsError, swatch, int, TOPOS, TOPO_LABEL } from './util.js';
import { getFilter, onFilterChange } from './shell.js';

const PAGE = 10;
const ANY = '';
const state = { rule: ANY, page: 0 };
let data = null;
let taskLabel = {};

const host = document.getElementById('outliers');
if (host) init();

/** Resolves once main.js has loaded summary.json and set up the filter bar. */
function whenReady() {
  return new Promise((resolve) => {
    if (document.body.dataset.ready === 'true') { resolve(); return; }
    const mo = new MutationObserver(() => {
      if (document.body.dataset.ready === 'true') { mo.disconnect(); resolve(); }
    });
    mo.observe(document.body, { attributes: true, attributeFilter: ['data-ready'] });
  });
}

async function init() {
  const body = document.getElementById('outlierBody');
  await whenReady();
  const summary = window.__results?.summary;
  if (summary) taskLabel = Object.fromEntries(summary.tasks.map((t) => [t.key, t.label]));
  try {
    data = await loadRuns();
  } catch (err) {
    body.replaceChildren(h('p', { class: 'placeholder', text: runsError(err) }));
    return;
  }
  if (!data.outliers) {
    body.replaceChildren(h('p', { class: 'placeholder', text: 'This runs.json has no outlier flags. Rebuild it with python -m scripts.demo.analysis_outliers.' }));
    return;
  }
  onFilterChange(() => { state.page = 0; render(); });
  render();
}

function inFilter(run, filter) {
  return filter.topos.has(run.topology) && (!filter.task || run.task === filter.task);
}

/** Flagged runs first by number of flags, then by id (stable across reloads). */
function flaggedRuns(filter, rule) {
  return data.runs
    .filter((r) => r.flags && inFilter(r, filter) && (rule === ANY || r.flags.some((f) => f.rule === rule)))
    .sort((a, b) => b.flags.length - a.flags.length || a.id.localeCompare(b.id));
}

function render() {
  const filter = getFilter();
  const { rules } = data.outliers;
  const label = Object.fromEntries(rules.map((r) => [r.key, r.label]));
  const shown = data.runs.filter((r) => inFilter(r, filter));
  const count = (rule) => shown.filter((r) => r.flags && (rule === ANY || r.flags.some((f) => f.rule === rule))).length;

  // Rule chips (single choice), with counts under the current filter.
  const chips = h('div', { class: 'chips outlier-chips', role: 'group', 'aria-label': 'Show runs flagged for' });
  for (const [key, text, title] of [[ANY, 'Any flag', 'Every flagged run'], ...rules.map((r) => [r.key, r.label, r.description])]) {
    const btn = h('button', {
      type: 'button', class: 'chip', 'data-rule': key, 'aria-pressed': String(state.rule === key), title,
    }, [text, h('span', { class: 'chip-count', text: int(count(key)) })]);
    btn.addEventListener('click', () => {
      state.rule = key;
      state.page = 0;
      render();
      host.querySelector(`.outlier-chips [data-rule="${key}"]`)?.focus();
    });
    chips.append(btn);
  }

  const rows = flaggedRuns(filter, state.rule);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE));
  state.page = Math.min(state.page, pages - 1);
  const slice = rows.slice(state.page * PAGE, state.page * PAGE + PAGE);

  const table = h('table', { class: 'data outlier-list' });
  table.append(h('caption', { class: 'visually-hidden', text: 'Flagged runs and why. Activate a run id to open its details.' }));
  table.append(h('thead', {}, h('tr', {}, [
    h('th', { scope: 'col', text: 'Run' }),
    h('th', { scope: 'col', text: 'Topology' }),
    h('th', { scope: 'col', class: 'hide-sm', text: 'Task' }),
    h('th', { scope: 'col', text: 'Why it stands out' }),
  ])));
  const tbody = h('tbody');
  for (const r of slice) {
    tbody.append(h('tr', { 'data-run': r.id }, [
      h('th', { scope: 'row' }, h('a', { href: `#run=${r.id}`, 'data-outlier-run': r.id, text: r.id })),
      h('td', { class: 'topo' }, [swatch(r.topology), TOPO_LABEL[r.topology]]),
      h('td', { class: 'hide-sm', text: taskLabel[r.task] || r.task }),
      h('td', {}, h('ul', { class: 'outlier-reasons' }, r.flags.map((f) => h('li', {}, [
        h('span', { class: 'tag tag--flag', text: label[f.rule] || f.rule }), ' ',
        h('span', { class: 'outlier-reason', text: f.reason }),
      ])))),
    ]));
  }
  if (!slice.length) tbody.append(h('tr', {}, h('td', { colspan: 4, text: 'No flagged runs match these filters.' })));
  table.append(tbody);

  const pager = h('div', { class: 'pager' });
  if (pages > 1) {
    const prev = h('button', { type: 'button', class: 'btn btn--ghost btn--small', text: '← Previous', disabled: state.page === 0 });
    const next = h('button', { type: 'button', class: 'btn btn--ghost btn--small', text: 'Next →', disabled: state.page >= pages - 1 });
    prev.addEventListener('click', () => { state.page--; render(); });
    next.addEventListener('click', () => { state.page++; render(); });
    pager.append(prev, h('span', { text: `Page ${state.page + 1} of ${pages}` }), next);
  }

  const anyCount = count(ANY);
  const what = state.rule === ANY ? 'flagged' : `flagged "${label[state.rule]}"`;
  document.getElementById('outlierBody').replaceChildren(
    chips,
    h('p', { class: 'count', id: 'outlierCount', 'aria-live': 'polite', text:
      `${int(rows.length)} ${what} of ${int(shown.length)} runs` +
      (state.rule !== ANY ? ` (${int(anyCount)} with any flag)` : '') +
      (rows.length > PAGE ? ` · showing ${state.page * PAGE + 1}–${state.page * PAGE + slice.length}` : '') },
    ),
    h('div', { class: 'table-wrap' }, table),
    pager,
    limits(filter),
  );
}

const fmtS = (x) => (x < 1 ? `${Math.round(x * 1000)} ms` : x < 10 ? `${x.toFixed(2)} s` : `${Math.round(x).toLocaleString('en-GB')} s`);
const fmtTok = (x) => (x >= 1000 ? `${(x / 1000).toFixed(1)}k` : String(Math.round(x)));

/** "How runs are flagged": the rules and each topology's limits. */
function limits(filter) {
  const { rules, thresholds } = data.outliers;
  const topos = TOPOS.filter((t) => filter.topos.has(t) && thresholds[t]);
  const fmt = (rule, x) => (rule === 'token_heavy' ? `${fmtTok(x)} tokens` : fmtS(x));
  const det = h('details', { class: 'explain' }, [h('summary', { text: 'How runs are flagged' })]);
  det.append(h('p', { text: 'Limits are set per topology, because the topologies differ by design: a long Full mesh run would be short for Star. A value counts as unusual above Q3 + 3 × IQR of its topology (the same far-out fence the paper uses before fitting). A run can carry several flags; a flag is a pointer, not an error.' }));
  det.append(h('ul', {}, rules.map((r) => {
    const parts = [h('strong', { text: `${r.label}: ` }), r.description];
    if (r.kind === 'fence') {
      parts.push(' Limits: ', topos.map((t) => {
        const st = thresholds[t][r.key];
        return st ? `${TOPO_LABEL[t]} ${fmt(r.key, st.fence)} (median ${fmt(r.key, st.median)})` : null;
      }).filter(Boolean).join('; '), '.');
    }
    return h('li', {}, parts);
  })));
  return det;
}
