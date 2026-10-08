/**
 * Overview page: headline findings, motivation and set-up facts, topology cards and Table 2
 * (rendered as published). Every number in the page text is refilled from summary.json.
 */

import { h, s, TOPOS, TOPO_LABEL, TOPO_COLOR, swatch, pct, fixed, int } from './util.js';
import { PAPER_URL, REPO_URL } from '../../common/js/site.js';

/** The paper's landing page (ACM Digital Library), from the shared common/js/site.js. */
export { PAPER_URL };

/** The hero's "Read the paper" / "View the code" pair (before the data loads). */
export function renderPaperLinks() {
  const paper = document.getElementById('paperLink');
  if (PAPER_URL) paper.href = PAPER_URL;
  paper.hidden = !PAPER_URL;
  document.getElementById('codeLink').href = REPO_URL;
}

/** A Table 2 cell's leading number ("0.207 calls/s (-0%)" -> "0.207"), or null. */
function table2Number(summary, metric, topo) {
  for (const section of summary.table2.sections) {
    const row = section.rows.find((r) => r.metric === metric);
    if (row) return /^[\d.,]+/.exec(row.values[topo])?.[0] ?? null;
  }
  return null;
}

/** The headline findings, the motivation and the set-up, filled from summary.json. */
export function renderHeader(summary) {
  const iat = summary.iat.per_topology;
  const fill = (key, text) => {
    if (text == null) return;
    document.querySelectorAll(`[data-fill="${key}"]`).forEach((el) => { el.textContent = text; });
  };
  for (const t of TOPOS) {
    fill(`burst-${t}`, pct(iat[t].burst_fraction));
    fill(`ks-${t}`, fixed(summary.iat.fits[t].lognormal.ks, 3));
    fill(`rate-${t}`, table2Number(summary, 'Discussion call rate', t));
  }
  const agg = summary.aggregates.by_topology;
  const inflight = (t) => agg[t].llm_inflight_mean.mean;
  fill('inflight', `${fixed(inflight('horizontal'), 2)} → ${fixed(inflight('full_mesh'), 2)}`);
  fill('inflight-star', `${Math.round((inflight('vertical') / inflight('horizontal') - 1) * 100)}%`);
  const tcp = agg.full_mesh.tcp_bytes_llm_mean_Bps.mean / agg.horizontal.tcp_bytes_llm_mean_Bps.mean - 1;
  fill('tcp', `${Math.round(tcp * 100)}%`);

  const src = summary.source;
  const n = src.n_runs;
  fill('n-runs', int(src.n_runs_total));
  fill('runs-per-topo', `${int(n.horizontal)} Sequential, ${int(n.vertical)} Star and ${int(n.full_mesh)} Full mesh`);
  document.getElementById('dataNote').textContent =
    `Every number and chart on this page comes from ${int(src.n_runs_total)} recorded runs of the paper's ` +
    `experiments (Sequential ${int(n.horizontal)}, Star ${int(n.vertical)}, Full mesh ${int(n.full_mesh)}).`;
}

/** The footer's data source line (every results page). */
export function renderSource(summary) {
  const el = document.getElementById('footSource');
  if (el) el.textContent = `the paper's ${int(summary.source.n_runs_total)} recorded runs`;
}

// ---------------------------------------------------------------------------
// Topology cards
// ---------------------------------------------------------------------------

const NODES = [[38, 12], [64, 38], [38, 64], [12, 38]]; // 4 agents on a diamond
const TOPO_INFO = {
  horizontal: {
    edges: [[0, 1], [1, 2], [2, 3]],
    text: 'Agents speak one at a time in a fixed turn order, each seeing the previous turns.',
  },
  vertical: {
    edges: [[0, 1], [0, 2], [0, 3]],
    text: 'A solver proposes; the other three review it in parallel. Repeats per round.',
  },
  full_mesh: {
    edges: [[0, 1], [0, 2], [0, 3], [1, 2], [1, 3], [2, 3]],
    text: 'All 12 directed peer messages per round are sent concurrently, five at a time.',
  },
};

function topoGlyph(topo) {
  const { edges } = TOPO_INFO[topo];
  const svg = s('svg', { viewBox: '0 0 76 76', 'aria-hidden': 'true' });
  for (const [a, b] of edges) {
    const [x1, y1] = NODES[a];
    const [x2, y2] = NODES[b];
    svg.append(s('line', { x1, y1, x2, y2, stroke: TOPO_COLOR[topo], 'stroke-width': 2, 'stroke-linecap': 'round', opacity: 0.85 }));
  }
  NODES.forEach(([cx, cy], i) => {
    const hub = topo === 'vertical' && i === 0;
    svg.append(s('circle', { cx, cy, r: hub ? 8 : 6.5, fill: hub ? TOPO_COLOR[topo] : 'var(--surface-2)', stroke: TOPO_COLOR[topo], 'stroke-width': 2 }));
  });
  return svg;
}

export function renderTopologyCards(summary) {
  const host = document.getElementById('topoCards');
  host.replaceChildren(...TOPOS.map((t) => h('div', { class: 'topo-card' }, [
    topoGlyph(t),
    h('div', {}, [
      h('h3', {}, [swatch(t), TOPO_LABEL[t], ' ', h('code', { text: t })]),
      h('p', { text: TOPO_INFO[t].text }),
      h('p', { text: `${int(summary.source.n_runs[t])} runs · ${int(summary.iat.per_topology[t].n)} discussion IATs` }),
    ]),
  ])));
}

// ---------------------------------------------------------------------------
// Table 2
// ---------------------------------------------------------------------------


/** "16.29 (+16%)" -> value + muted percentage. */
function cellContent(text) {
  const m = /^(.*?)\s*(\([+\-−]?\d.*%\))$/.exec(text);
  if (!m) return [text];
  return [m[1], ' ', h('span', { class: 'pct', text: m[2] })];
}

/** Shows the first rows of Table 2 and puts a button under it that opens the rest. */
function collapseTable2(host) {
  host.classList.add('t2-clip');
  const button = h('button', { type: 'button', class: 'btn btn--ghost t2-toggle', 'aria-expanded': 'false', text: 'Show the full table' });
  button.addEventListener('click', () => {
    const open = host.classList.toggle('t2-clip') === false;
    button.setAttribute('aria-expanded', String(open));
    button.textContent = open ? 'Show fewer rows' : 'Show the full table';
  });
  host.after(button);
}

export function renderTable2(summary) {
  const t2 = summary.table2;
  const table = h('table', { class: 'data t2' });
  table.append(h('caption', { class: 'visually-hidden', text: t2.title }));
  table.append(h('thead', {}, h('tr', {}, [
    h('th', { scope: 'col', text: 'Metric' }),
    ...TOPOS.map((t) => h('th', { scope: 'col' }, [swatch(t), TOPO_LABEL[t], h('br'), h('span', { class: 'pct', text: `n = ${int(t2.runs[t])}` })])),
  ])));
  const body = h('tbody');
  for (const section of t2.sections) {
    body.append(h('tr', { class: 'section' }, h('th', { colspan: 4, scope: 'colgroup', text: section.title })));
    for (const row of section.rows) {
      const label = [row.metric];
      if (row.footnote) label.push(h('sup', { text: row.footnote }));
      if (row.note) label.push(h('br'), h('span', { class: 'pct', text: row.note }));
      body.append(h('tr', {}, [
        h('th', { scope: 'row' }, label),
        ...TOPOS.map((t) => h('td', {}, cellContent(row.values[t]))),
      ]));
    }
  }
  table.append(body);
  const host = document.getElementById('table2Body');
  host.replaceChildren(table);
  host.removeAttribute('aria-busy');
  collapseTable2(host);

  const notes = document.getElementById('table2Notes');
  notes.replaceChildren(
    ...t2.footnotes.map((f) => h('p', {}, [h('sup', { text: f.mark }), ' ', f.text])),
    ...t2.notes.map((n) => h('p', { text: n })),
  );
}
