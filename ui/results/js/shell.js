/**
 * Chrome shared by the four results pages (Overview, Traffic, System, Runs; ui/results/,
 * results/traffic-patterns/, results/system-load/, results/run-explorer/):
 *
 *   <nav data-results-tabs>            sticky tabs, the current page marked with aria-current
 *   <div data-results-filter data-applies="…">
 *                                      filter bar: topology chips + Task select, kept in the URL
 *                                      query (?topo=vertical,full_mesh&task=math); only on pages
 *                                      whose charts can filter
 *   [data-badge="aggregate|runs|…"]    a small badge naming where a chart's data comes from (BADGES)
 *   <a data-results-link="traffic#iat">  link to another results page, carrying the filter query
 *   <nav data-results-end>             "Next →" (the "On this page" row goes in the page hero)
 *
 * The page is named by <body data-results-page="overview|traffic|system|runs"> (or "beta": the secondary Beta page, no tab). The filter
 * query is carried by the tabs, the Next link, [data-results-link] links and the header's
 * Results ▾ menu, so it survives moving between pages.
 */

import { RESULTS, BETA } from '../../common/js/nav.js';
import { h, TOPOS, TOPO_LABEL, swatch } from './util.js';
import { getDataMode } from '../../common/js/data.js';
import { LABELS } from '../../common/js/mode.js';

export const PAGE = document.body.dataset.resultsPage || 'overview';
const PREFIX = PAGE === 'overview' ? '' : '../';

/**
 * Badge label per data kind. A chart names its kind (data-badge="aggregate"); the label comes
 * from here, so a later data mode (e.g. synthetic runs) only has to change the kind.
 */
export const BADGES = {
  aggregate: 'Real aggregate',
  runs: 'Recorded runs',
  synthetic: 'Synthetic illustration',
};

// ---------------------------------------------------------------------------
// Filter state (URL query)
// ---------------------------------------------------------------------------

const filter = { topos: new Set(TOPOS), task: '' };
const listeners = [];
let taskKeys = null; // valid task keys, once summary.json is loaded

function readQuery() {
  const q = new URLSearchParams(window.location.search);
  const topos = (q.get('topo') || '').split(',').filter((t) => TOPOS.includes(t));
  filter.topos = new Set(topos.length ? topos : TOPOS);
  const task = q.get('task') || '';
  filter.task = !taskKeys || taskKeys.includes(task) ? task : '';
}
readQuery();

/** The current filter: { topos: Set of topology keys, task: '' (all) or a task key }. */
export const getFilter = () => ({ topos: new Set(filter.topos), task: filter.task });

/** Calls fn(filter) whenever the filter changes. */
export function onFilterChange(fn) { listeners.push(fn); }

/** The filter as a query string ('' when nothing is filtered). */
export function filterQuery() {
  const parts = [];
  if (filter.topos.size < TOPOS.length) parts.push(`topo=${TOPOS.filter((t) => filter.topos.has(t)).join(',')}`);
  if (filter.task) parts.push(`task=${encodeURIComponent(filter.task)}`);
  return parts.length ? `?${parts.join('&')}` : '';
}

/** href from this page to results page `id` (RESULTS), with the filter query and an optional hash. */
export function resultsHref(id, hash = '') {
  const page = [...RESULTS, BETA].find((p) => p.id === id) || RESULTS[0];
  const sub = page.path.slice('results/'.length);
  return `${PREFIX}${sub}` + filterQuery() + hash || './';
}

function updateLinks() {
  document.querySelectorAll('[data-results-link]').forEach((a) => {
    const [id, hash] = a.dataset.resultsLink.split('#');
    a.href = resultsHref(id, hash ? `#${hash}` : '');
  });
  // the header's Results ▾ menu (common/js/nav.js) keeps the filter too
  document.querySelectorAll('.results-menu__item[data-page]').forEach((a) => {
    a.href = resultsHref(a.dataset.page);
  });
}

function setFilter(next) {
  Object.assign(filter, next);
  const url = window.location.pathname + filterQuery() + window.location.hash;
  history.replaceState(history.state, '', url);
  updateLinks();
  syncFilterBar();
  listeners.forEach((fn) => fn(getFilter()));
}

// ---------------------------------------------------------------------------
// Tabs, filter bar, badges, end-of-page links
// ---------------------------------------------------------------------------

function mountTabs() {
  const host = document.querySelector('[data-results-tabs]');
  if (!host) return;
  host.classList.add('results-tabs');
  if (!host.hasAttribute('aria-label')) host.setAttribute('aria-label', 'Results pages');
  host.replaceChildren(h('ul', {}, RESULTS.map((p) => h('li', {}, h('a', {
    'data-results-link': p.id,
    'data-tab': p.id,
    'aria-current': p.id === PAGE ? 'page' : null,
    title: p.description,
    text: p.label,
  })))));
}

let bar = null;

function mountFilterBar(tasks) {
  const host = document.querySelector('[data-results-filter]');
  if (!host) return;
  const chips = TOPOS.map((t) => {
    const b = h('button', { type: 'button', class: 'chip', 'data-topo': t, 'aria-pressed': 'true' }, [swatch(t), TOPO_LABEL[t]]);
    b.addEventListener('click', () => {
      const topos = new Set(filter.topos);
      if (topos.has(t)) {
        if (topos.size === 1) return; // keep at least one topology
        topos.delete(t);
      } else {
        topos.add(t);
      }
      setFilter({ topos });
    });
    return b;
  });
  const task = h('select', { id: 'filterTask', 'aria-label': 'Task' }, [
    h('option', { value: '', text: 'All tasks' }),
    ...tasks.map((t) => h('option', { value: t.key, text: t.label })),
  ]);
  task.addEventListener('change', () => setFilter({ task: task.value }));
  const reset = h('button', { type: 'button', class: 'btn btn--ghost btn--small', id: 'filterReset', text: 'Show all' });
  reset.addEventListener('click', () => setFilter({ topos: new Set(TOPOS), task: '' }));
  host.classList.add('filter-bar');
  host.setAttribute('role', 'group');
  host.setAttribute('aria-label', 'Filter runs');
  host.replaceChildren(
    h('span', { class: 'filter-bar__label', id: 'filterTopoLabel', text: 'Topology' }),
    h('div', { class: 'chips', role: 'group', 'aria-labelledby': 'filterTopoLabel' }, chips),
    h('label', { class: 'filter-bar__task' }, [h('span', { class: 'filter-bar__label', text: 'Task' }), task]),
    reset,
    host.dataset.applies ? h('p', { class: 'filter-bar__scope', text: `Applies to ${host.dataset.applies}.` }) : null,
  );
  bar = { chips, task, reset };
  syncFilterBar();
}

function syncFilterBar() {
  if (!bar) return;
  bar.chips.forEach((b) => b.setAttribute('aria-pressed', String(filter.topos.has(b.dataset.topo))));
  bar.task.value = filter.task;
  bar.reset.hidden = filter.topos.size === TOPOS.length && !filter.task;
}

let publicMode = false; // set once the data mode is known (public: per-run data is synthetic)

/** In public mode the per-run views and the scatter carry the synthetic label (LABELS in common/js/mode.js). */
const kindFor = (kind) => (publicMode && kind === 'runs' ? LABELS.public.badge : kind);

/** A badge element for data kind `kind` (BADGES). */
export function badge(kind) {
  const k = kindFor(kind);
  return h('span', { class: `badge badge--${k}`, 'data-badge-kind': k, text: BADGES[k] || k });
}

/** Adds the badge to every [data-badge] under root: inside a heading, or as a row before other content. */
export function mountBadges(root = document) {
  root.querySelectorAll('[data-badge]').forEach((node) => {
    if (node.querySelector(':scope > .badge, :scope > .badge-row')) return;
    const b = badge(node.dataset.badge);
    if (/^H[1-6]$/.test(node.tagName)) node.append(' ', b);
    else node.prepend(h('div', { class: 'badge-row' }, b));
  });
}

/** "On this page": a row of jump links under the page question (sections with data-toc). */
function mountToc() {
  const hero = document.querySelector('main .hero--page') || document.querySelector('main .hero');
  const sections = [...document.querySelectorAll('main section[id][data-toc]')];
  if (!hero || sections.length < 2 || hero.querySelector('.page-toc')) return;
  hero.append(h('nav', { class: 'page-toc', 'aria-label': 'On this page' }, [
    h('span', { class: 'page-toc__title', text: 'On this page' }),
    h('ul', {}, sections.map((sec) => h('li', {}, h('a', { href: `#${sec.id}`, text: sec.dataset.toc })))),
  ]));
}

/** "Next →" at the end of the page. */
function mountEnd() {
  const host = document.querySelector('[data-results-end]');
  if (!host) return;
  const i = RESULTS.findIndex((p) => p.id === PAGE);
  const next = RESULTS[(i + 1) % RESULTS.length]; // Beta (i = -1) leads back to the Overview
  host.classList.add('page-end');
  if (!host.hasAttribute('aria-label')) host.setAttribute('aria-label', 'Next page');
  host.replaceChildren(
    h('a', { class: 'next-link', 'data-results-link': next.id, rel: 'next' }, [
      h('span', { class: 'next-link__kicker', text: 'Next →' }),
      h('span', { class: 'next-link__label', text: next.label }),
      h('span', { class: 'next-link__desc', text: next.description }),
    ]),
  );
}

// Static chrome right away (before summary.json); the filter bar needs the task list.
mountTabs();
mountToc();
mountEnd();
mountBadges();
updateLinks();
getDataMode().then(({ mode }) => {
  if (mode !== 'public') return;
  publicMode = true;
  document.querySelectorAll('.badge--runs').forEach((b) => b.replaceWith(badge('runs')));
}).catch(() => {});

// Overview: old single-page links (#run=<id>, #iat, …) forward to their new page. The first
// load is handled by the inline script in results/index.html; this covers later hash changes.
if (PAGE === 'overview' && typeof window.__resultsRedirect === 'function') {
  window.addEventListener('hashchange', () => window.__resultsRedirect());
}

/** Called once summary.json is loaded: validates the task, draws the filter bar. */
export function initShell(summary) {
  taskKeys = summary.tasks.map((t) => t.key);
  readQuery();
  mountFilterBar(summary.tasks);
  updateLinks();
}
