/**
 * Entry point of the four results pages (results/, results/traffic-patterns/,
 * results/system-load/, results/run-explorer/). Loads summary.json and renders the sections present on this page (each one
 * isolated, so a failure in one leaves the others working). The Runs page routes #run=<id>
 * deep links. runs.json is only fetched when a section needs per-run data.
 */

import { loadSummary, h } from './util.js';
import { PAGE, initShell } from './shell.js';
import { renderPaperLinks, renderHeader, renderSource, renderTopologyCards, renderTable2 } from './overview.js';
import { renderIat, renderIatThumbs } from './iat.js';
import { renderCorrelations } from './correlations.js';
import { renderRuns, openRunFromHash } from './runs.js';
import { renderTaskBreakdown, renderScaling, renderNetwork } from './breakdown.js';

const has = (id) => document.getElementById(id) !== null;

if (has('paperLink')) renderPaperLinks(); // header links, footer and citation: common/js/nav.js

function guard(name, fn) {
  if (!has(name)) return;
  try {
    fn();
  } catch (err) {
    console.error(`[results] ${name} failed:`, err);
    const host = document.getElementById(name);
    host.append(h('p', { class: 'placeholder', text: `This section could not be drawn (${err.message}).` }));
  }
}

async function main() {
  let summary;
  try {
    summary = await loadSummary();
  } catch (err) {
    console.error('[results] could not load data:', err);
    document.querySelector('main section.card')?.append(
      h('p', { class: 'placeholder', text: `Could not load the summary (${err.message}). Serve ui/ over HTTP.` }),
    );
    return;
  }
  window.__results = { summary, page: PAGE };
  initShell(summary);
  renderSource(summary);

  // Overview
  guard('setup', () => { renderHeader(summary); renderTopologyCards(summary); });
  guard('iatGlance', () => renderIatThumbs(summary));
  guard('table2', () => renderTable2(summary));
  // Traffic
  guard('iat', () => renderIat(summary));
  guard('scaling', () => renderScaling(summary));
  // System
  guard('network', () => renderNetwork(summary));
  guard('correlations', () => renderCorrelations(summary));
  guard('tasks', () => renderTaskBreakdown(summary));
  // Runs
  guard('runs', () => renderRuns(summary));

  document.body.dataset.ready = 'true';
  if (has('runs')) {
    window.addEventListener('hashchange', () => openRunFromHash());
    openRunFromHash();
  }
}

main();
