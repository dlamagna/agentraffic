/**
 * "Analyse this run": the Run explorer's drill-down for the run that just finished in the
 * workflow runner (stat tiles, Gantt of the LLM calls, calls in flight, the run's metrics and
 * its inter-arrival times against the topology's distribution), collapsed under the final output.
 *
 * The run's own numbers come from the response's `llm_requests` (a replayed demo run carries its
 * events; so does a live run), never from runs.json or private data. Only the topology's
 * distribution is loaded, from summary.json of the active data set, so it works on the public
 * site too. The charts are results/js/run-charts.js, shared with the Run explorer.
 */

import { h, loadSummary, metricInfo, TOPO_LABEL, int } from '../../results/js/util.js';
import { buildRunAnalysis, runFromResponse } from '../../results/js/run-charts.js';

let summaryPromise = null;
let handles = [];
let current = null; // { run, rendered }
let generation = 0; // a finished or reset run invalidates a summary load still in flight

const el = (id) => document.getElementById(id);

function loadSummaryOnce() {
  if (!summaryPromise) summaryPromise = loadSummary().catch(() => { summaryPromise = null; return null; });
  return summaryPromise;
}

function release() {
  handles.forEach((hd) => hd.disconnect());
  handles = [];
}

/** Hide and empty the section (a new run starts, the form is cleared, or the run was cancelled). */
export function resetRunAnalysis() {
  generation++;
  release();
  current = null;
  const section = el('runAnalysis');
  if (!section) return;
  section.hidden = true;
  section.open = false;
  el('runAnalysisBody').replaceChildren();
  el('runAnalysisHint').textContent = '';
}

/**
 * Offer the analysis of a finished run. `data` is the response (llm_requests, stages, ...);
 * `partial` marks a run that did not complete: it is analysed as far as it got.
 */
export function showRunAnalysis(data, { topology = '', partial = false } = {}) {
  resetRunAnalysis();
  const section = el('runAnalysis');
  if (!section) return;
  const run = runFromResponse(data, topology);
  if (!run || !TOPO_LABEL[run.topology]) return;
  current = { run, partial: partial || data.completed === false, rendered: false };
  el('runAnalysisHint').textContent = `${int(run.calls.length)} LLM calls · ${TOPO_LABEL[run.topology]}${current.partial ? ' · partial run' : ''}`;
  section.hidden = false;
}

async function render() {
  if (!current || current.rendered) return;
  current.rendered = true;
  const { run, partial } = current;
  const gen = generation;
  const body = el('runAnalysisBody');
  body.replaceChildren(h('p', { class: 'loading', text: 'Analysing…' }));
  const summary = await loadSummaryOnce();
  if (gen !== generation) return;
  const info = summary ? metricInfo(summary) : null;
  const view = buildRunAnalysis(run, { summary, info });
  const topo = TOPO_LABEL[run.topology];
  body.replaceChildren(...[
    partial ? h('p', { class: 'callout callout--flag', text: 'This run did not complete, so the figures cover only the calls made so far.' }) : null,
    view.tiles,
    h('div', { class: 'detail-grid' }, [view.gantt, view.conc, view.metrics, view.iat]),
    h('p', { class: 'run-analysis-source', text: summary
      ? `Computed in the browser from this run's ${int(run.calls.length)} LLM requests. The ${topo} distribution is from summary.json (${int(summary.source.n_runs[run.topology])} runs). Times are relative to the run's first LLM call.`
      : `Computed in the browser from this run's ${int(run.calls.length)} LLM requests. Times are relative to the run's first LLM call.` }),
  ].filter(Boolean));
  release();
  handles = view.mount().handles;
}

document.addEventListener('DOMContentLoaded', () => {
  el('runAnalysis')?.addEventListener('toggle', () => { if (el('runAnalysis').open) render(); });
});
