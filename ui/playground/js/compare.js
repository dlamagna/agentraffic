/**
 * playground/compare/: the same task under all three topologies at once.
 *
 * Loads the three recorded (or synthetic, in public mode) fixtures of one task from the active
 * data set (common/js/data.js) and replays their events on one shared clock: a panel per
 * topology (a lane per agent, a bar per LLM call) and one timeline of call arrivals with the
 * calls in flight. A call arrives when it is sent: the event's t_ms is when the response came
 * back, so its start is t_ms minus its duration_seconds.
 *
 * Independent of the mock backend: it reads fixtures/index.json and the *.events.json files
 * directly, so it needs no backend and no private data. Query: ?task=<math|coding|...>,
 * ?speed=<n>, ?play=0 (start paused), ?t=<seconds> (start there).
 */

import { dataUrl, fetchData, getDataMode } from '../../common/js/data.js';

const TOPOLOGIES = [
  { id: 'horizontal', label: 'Sequential' },
  { id: 'vertical', label: 'Star' },
  { id: 'full_mesh', label: 'Full mesh' },
];
const BURST_GAP_S = 1; // an arrival less than this after the previous one is "back-to-back"
const SVG_NS = 'http://www.w3.org/2000/svg';

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(window.location.search);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const fmt = (x, d = 1) => Number(x).toFixed(d);

const state = {
  runs: null, // [{ topo, label, calls, stages, duration, stats, steps }]
  max: 0, // the longest run (s): the shared time axis
  peak: 1, // the highest in-flight count over the three runs: the shared concurrency scale
  t: 0, // replay clock (s)
  playing: false,
  speed: 5,
  last: 0, // performance.now() of the previous frame
  raf: 0,
};

// ---------------------------------------------------------------------------
// Model
// ---------------------------------------------------------------------------

function median(xs) {
  if (!xs.length) return 0;
  const s = [...xs].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}

/** Calls, stage windows and whole-run statistics from a fixture's event list. */
function buildRun(topo, events) {
  const calls = [];
  const stages = [];
  let duration = 0;
  for (const ev of events) {
    duration = Math.max(duration, ev.t_ms / 1000);
    const d = ev.data || {};
    if (ev.event === 'llm_request') {
      const dur = Number(d.duration_seconds ?? (d.llm_meta && d.llm_meta.latency_ms / 1000) ?? 0);
      const end = ev.t_ms / 1000;
      calls.push({ start: Math.max(0, end - dur), end, agent: d.source || 'agent', role: d.agent_role || '', stage: d.stage || '' });
    } else if (ev.event === 'stage_start') {
      stages.push({ stage: d.stage, start: ev.t_ms / 1000, end: null });
    } else if (ev.event === 'stage_complete') {
      const open = [...stages].reverse().find((s) => s.stage === d.stage && s.end == null);
      if (open) open.end = ev.t_ms / 1000;
    }
  }
  calls.sort((a, b) => a.start - b.start || a.end - b.end);
  const agents = [];
  for (const c of calls) if (!agents.includes(c.agent)) agents.push(c.agent);
  const gaps = calls.slice(1).map((c, i) => c.start - calls[i].start);
  // in-flight step function: [{ t, n }] from the call edges
  const edges = calls.flatMap((c) => [[c.start, 1], [c.end, -1]]).sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const steps = [{ t: 0, n: 0 }];
  let n = 0;
  for (const [t, dn] of edges) {
    n += dn;
    steps.push({ t, n });
  }
  const peak = Math.max(0, ...steps.map((s) => s.n));
  return {
    topo: topo.id,
    label: topo.label,
    calls,
    stages,
    agents,
    duration,
    steps,
    stats: {
      calls: calls.length,
      duration,
      peak,
      medianGap: median(gaps),
      burstShare: gaps.length ? gaps.filter((g) => g < BURST_GAP_S).length / gaps.length : 0,
    },
  };
}

const inFlight = (run, t) => run.calls.filter((c) => c.start <= t && t < c.end).length;
const arrived = (run, t) => run.calls.filter((c) => c.start <= t).length;
const stageAt = (run, t) => {
  const cur = run.stages.filter((s) => s.start <= t && (s.end == null || t < s.end)).pop();
  return cur ? cur.stage : '';
};

// ---------------------------------------------------------------------------
// Drawing (SVG as strings; widths come from the element so text stays readable at 375 px)
// ---------------------------------------------------------------------------

function axisTicks(max) {
  const step = [5, 10, 20, 30, 60].find((s) => max / s <= 8) || 60;
  const out = [];
  for (let v = 0; v <= max + 1e-6; v += step) out.push(v);
  return out;
}

/** One topology's lanes: a row per agent, a bar per call started by now. */
function drawPanel(run, width, t) {
  const left = 66;
  const right = 6;
  const rowH = 15;
  const top = 4;
  const axisH = 18;
  const h = top + run.agents.length * rowH + axisH;
  const x = (s) => left + (s / state.max) * (width - left - right);
  let g = '';
  for (const v of axisTicks(state.max)) {
    g += `<line class="cmp-grid" x1="${x(v)}" x2="${x(v)}" y1="${top}" y2="${h - axisH}"/>`
      + `<text x="${x(v)}" y="${h - 5}" text-anchor="middle">${v}s</text>`;
  }
  run.agents.forEach((a, i) => {
    const y = top + i * rowH;
    g += `<rect class="cmp-lane" x="${left}" y="${y + 1}" width="${width - left - right}" height="${rowH - 2}" rx="2"/>`
      + `<text x="${left - 5}" y="${y + rowH - 4}" text-anchor="end">${esc(a.replace(/^agent-/, ''))}</text>`;
  });
  for (const c of run.calls) {
    if (c.start > t) continue;
    const done = c.end <= t;
    const y = top + run.agents.indexOf(c.agent) * rowH;
    const w = Math.max(2, x(Math.min(c.end, t)) - x(c.start));
    g += `<rect class="cmp-bar${done ? '' : ' cmp-bar--live'}" x="${x(c.start)}" y="${y + 2}" width="${w}" height="${rowH - 4}" rx="2"/>`;
  }
  const px = x(Math.min(t, state.max));
  g += `<line class="cmp-playhead" x1="${px}" x2="${px}" y1="${top}" y2="${h - axisH}"/>`;
  return { h, html: g };
}

/** The shared timeline: per topology, a tick per arrival and the in-flight area, on one axis. */
function drawTimeline(width, t) {
  const left = width < 520 ? 62 : 84;
  const right = 8;
  const rowH = 70;
  const tickH = 18;
  const areaH = 38;
  const top = 4;
  const axisH = 20;
  const h = top + state.runs.length * rowH + axisH;
  const x = (s) => left + (s / state.max) * (width - left - right);
  const y = (n) => areaH - (n / state.peak) * areaH;
  let g = '';
  for (const v of axisTicks(state.max)) {
    g += `<line class="cmp-grid" x1="${x(v)}" x2="${x(v)}" y1="${top}" y2="${h - axisH}"/>`
      + `<text x="${x(v)}" y="${h - 6}" text-anchor="middle">${v}s</text>`;
  }
  state.runs.forEach((run, i) => {
    const y0 = top + i * rowH;
    g += `<g style="--topo:var(--cmp-${run.topo})">`
      + `<text class="cmp-rowlabel" x="${left - 8}" y="${y0 + 13}" text-anchor="end">${esc(run.label)}</text>`
      + `<text x="${left - 8}" y="${y0 + 27}" text-anchor="end">${arrived(run, t)} / ${run.stats.calls}</text>`;
    for (const c of run.calls) {
      if (c.start <= t) g += `<line class="cmp-tick" x1="${x(c.start)}" x2="${x(c.start)}" y1="${y0}" y2="${y0 + tickH}"/>`;
    }
    // in-flight, clipped to now
    const base = y0 + tickH + 6;
    let d = `M${x(0)},${base + areaH}`;
    let prev = 0;
    for (const s of run.steps) {
      if (s.t > t) break;
      d += `L${x(s.t)},${base + y(prev)}L${x(s.t)},${base + y(s.n)}`;
      prev = s.n;
    }
    const tt = Math.min(t, run.duration);
    d += `L${x(tt)},${base + y(prev)}L${x(tt)},${base + areaH}Z`;
    g += `<path class="cmp-area" d="${d}"/>`
      + `<line class="cmp-axis" x1="${left}" x2="${width - right}" y1="${base + areaH}" y2="${base + areaH}"/></g>`;
  });
  const px = x(Math.min(t, state.max));
  g += `<line class="cmp-playhead" x1="${px}" x2="${px}" y1="${top}" y2="${h - axisH}"/>`;
  return { h, html: g };
}

function setSvg(host, { h, html }, width, label) {
  let svg = host.querySelector('svg');
  if (!svg) {
    svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('role', 'img');
    host.append(svg);
  }
  svg.setAttribute('viewBox', `0 0 ${width} ${h}`);
  svg.setAttribute('aria-label', label);
  svg.innerHTML = html;
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------

function render() {
  if (!state.runs) return;
  const t = state.t;
  $('cmpClock').textContent = `${fmt(t)} s / ${fmt(state.max)} s`;
  $('cmpScrub').value = String(Math.round((t / state.max) * 1000));
  const playBtn = $('cmpPlay');
  const finished = t >= state.max;
  playBtn.textContent = state.playing ? 'Pause' : finished ? 'Replay' : 'Play';
  for (const run of state.runs) {
    const panel = document.querySelector(`.cmp-panel[data-topo="${run.topo}"]`);
    const done = t >= run.duration;
    const n = arrived(run, t);
    panel.querySelector('[data-m="calls"]').textContent = `${n} / ${run.stats.calls}`;
    panel.querySelector('[data-m="flight"]').textContent = String(inFlight(run, t));
    panel.querySelector('[data-m="time"]').textContent = `${fmt(Math.min(t, run.duration))} s`;
    const badge = panel.querySelector('.cmp-badge');
    badge.textContent = done ? 'Complete' : t > 0 ? 'Running' : 'Waiting';
    badge.className = `cmp-badge${done ? ' is-done' : t > 0 ? ' is-live' : ''}`;
    panel.querySelector('.cmp-stage').textContent = done ? `Finished at ${fmt(run.duration)} s` : stageAt(run, t) ? `Stage: ${stageAt(run, t)}` : ' ';
    const host = panel.querySelector('.cmp-chart');
    const w = Math.max(240, host.clientWidth || 320);
    setSvg(host, drawPanel(run, w, t), w, `${run.label}: LLM calls per agent over time, ${n} of ${run.stats.calls} sent so far`);
  }
  const host = $('cmpTimeline');
  const w = Math.max(280, host.clientWidth || 600);
  setSvg(host, drawTimeline(w, t), w, `LLM-call arrivals under the three topologies, shared time axis, at ${fmt(t)} seconds`);
}

function frame(now) {
  if (!state.playing) return;
  state.t = Math.min(state.max, state.t + ((now - state.last) / 1000) * state.speed);
  state.last = now;
  if (state.t >= state.max) state.playing = false;
  render();
  if (state.playing) state.raf = requestAnimationFrame(frame);
}

function play() {
  if (state.t >= state.max) state.t = 0;
  state.playing = true;
  state.last = performance.now();
  cancelAnimationFrame(state.raf);
  state.raf = requestAnimationFrame(frame);
  render();
}

function pause() {
  state.playing = false;
  cancelAnimationFrame(state.raf);
  render();
}

function buildPanels() {
  $('cmpPanels').innerHTML = state.runs.map((run) => `
    <section class="card cmp-panel" data-topo="${run.topo}" style="--topo:var(--cmp-${run.topo})" aria-label="${esc(run.label)} replay">
      <div class="cmp-panel__head">
        <h3><span class="cmp-dot" aria-hidden="true"></span>${esc(run.label)}</h3>
        <span class="cmp-badge">Waiting</span>
      </div>
      <p class="cmp-metrics">
        <span>LLM calls <b data-m="calls"></b></span>
        <span>In flight <b data-m="flight"></b></span>
        <span>Time <b data-m="time"></b></span>
      </p>
      <p class="cmp-stage">&nbsp;</p>
      <div class="cmp-chart"></div>
    </section>`).join('');
}

function buildStats() {
  const rows = [
    ['LLM calls', (s) => s.calls],
    ['Duration', (s) => `${fmt(s.duration)} s`],
    ['Peak calls in flight', (s) => s.peak],
    ['Median gap between arrivals', (s) => `${fmt(s.medianGap, 2)} s`],
    [`Arrivals within ${BURST_GAP_S} s of the previous`, (s) => `${Math.round(s.burstShare * 100)}%`],
  ];
  $('cmpStats').innerHTML = `<thead><tr><th scope="col">Whole run</th>${state.runs.map((r) => `<th scope="col" data-topo="${r.topo}"><span class="cmp-dot" style="--topo:var(--cmp-${r.topo})" aria-hidden="true"></span>${esc(r.label)}</th>`).join('')}</tr></thead>`
    + `<tbody>${rows.map(([name, f]) => `<tr><th scope="row">${esc(name)}</th>${state.runs.map((r) => `<td>${f(r.stats)}</td>`).join('')}</tr>`).join('')}</tbody>`;
  const by = Object.fromEntries(state.runs.map((r) => [r.topo, r.stats]));
  const a = by.horizontal;
  const c = by.full_mesh;
  $('cmpTakeaway').textContent = `Full mesh sends ${c.calls} calls in ${fmt(c.duration, 0)} s with up to ${c.peak} in flight at once; `
    + `the sequential run sends ${a.calls} calls in ${fmt(a.duration, 0)} s, never more than ${a.peak} at a time. `
    + 'Same task, same model: only the coordination topology differs.';
}

async function loadTask(task) {
  pause();
  const index = await fetchData('fixtures/index.json');
  const entries = TOPOLOGIES.map((t) => index.fixtures.find((f) => f.task === task && f.topology === t.id));
  if (entries.some((e) => !e)) throw new Error(`task ${task} is missing a topology`);
  const events = await Promise.all(entries.map(async (e) => {
    const resp = await fetch(await dataUrl(`fixtures/${e.files.events}`));
    if (!resp.ok) throw new Error(`${e.files.events}: HTTP ${resp.status}`);
    return resp.json();
  }));
  state.runs = TOPOLOGIES.map((t, i) => buildRun(t, events[i]));
  state.max = Math.max(...state.runs.map((r) => r.duration));
  state.peak = Math.max(1, ...state.runs.map((r) => r.stats.peak));
  state.t = 0;
  $('cmpTaskText').textContent = entries[0].original_task || '';
  buildPanels();
  buildStats();
  render();
}

async function init() {
  const empty = $('cmpEmpty');
  let index;
  try {
    index = await fetchData('fixtures/index.json');
  } catch (_) {
    empty.textContent = 'No replayable runs are available in this data set, so there is nothing to compare here.';
    empty.hidden = false;
    document.body.dataset.cmp = 'empty';
    return;
  }
  const tasks = [...new Set(index.fixtures.map((f) => f.task))]
    .filter((task) => TOPOLOGIES.every((t) => index.fixtures.some((f) => f.task === task && f.topology === t.id)));
  if (!tasks.length) {
    empty.textContent = 'No task has a run under all three topologies in this data set.';
    empty.hidden = false;
    document.body.dataset.cmp = 'empty';
    return;
  }
  const names = { math: 'Math problem', coding: 'Coding', consulting: 'Consulting', research: 'Research' };
  const select = $('cmpTask');
  select.innerHTML = tasks.map((k) => `<option value="${esc(k)}">${esc(names[k] || k)}</option>`).join('');
  const want = params.get('task');
  select.value = tasks.includes(want) ? want : tasks.includes('math') ? 'math' : tasks[0];
  const sp = Number(params.get('speed'));
  state.speed = sp > 0 ? sp : 5;
  if (![...$('cmpSpeed').options].some((o) => Number(o.value) === state.speed)) {
    $('cmpSpeed').add(new Option(`${state.speed}x`, String(state.speed)));
  }
  $('cmpSpeed').value = String(state.speed);
  $('cmpControls').hidden = false;
  $('cmpTimelineCard').hidden = false;
  $('cmpStatsCard').hidden = false;

  select.addEventListener('change', async () => { await loadTask(select.value); play(); });
  $('cmpSpeed').addEventListener('change', (e) => { state.speed = Number(e.target.value); });
  $('cmpPlay').addEventListener('click', () => (state.playing ? pause() : play()));
  $('cmpRestart').addEventListener('click', () => { state.t = 0; play(); });
  $('cmpScrub').addEventListener('input', (e) => {
    state.t = (Number(e.target.value) / 1000) * state.max;
    if (state.playing) state.last = performance.now();
    render();
  });
  new ResizeObserver(() => render()).observe(document.querySelector('.cmp'));

  await loadTask(select.value);
  const start = Number(params.get('t'));
  if (start > 0) state.t = Math.min(start, state.max);
  document.body.dataset.cmp = 'ready';
  const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (params.get('play') === '0' || reduce) render();
  else play();
}

// A fetch cut short because the page is being left (a redirect, a click on a link) is not an error.
let leaving = false;
addEventListener('pagehide', () => { leaving = true; });
addEventListener('beforeunload', () => { leaving = true; });

getDataMode().then(init).catch((err) => {
  setTimeout(() => { if (!leaving) console.error('[compare]', err); }, 150);
});
