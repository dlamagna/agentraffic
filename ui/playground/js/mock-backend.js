/**
 * Demo mode: a fake Agent A backend that replays recorded paper runs.
 *
 * Importing this module patches window.fetch. Requests to the Agent A API
 * (POST /agentverse, GET /agentverse/<task_id>) are answered from the fixtures in
 * fixtures/ of the active data set (ui/data/private/ = recorded runs, built by
 * scripts/demo/generate_fixtures.py; ui/data/public/ = synthetic runs; see common/js/data.js)
 * when demo mode is on;
 * everything else, and every request when demo mode is off, goes to the real fetch.
 *
 * Streaming requests get a real text/event-stream body replayed with the recorded
 * delays, so streaming.js parses it exactly as it would the live server.
 *
 * Demo mode: ?demo=1 forces it on, ?demo=0 off. Otherwise it is on for static hosts
 * (*.github.io, *.netlify.app) and whenever the Agent A endpoint is unreachable.
 * Replay speed: ?speed=N or the selector in the demo banner.
 * ?replay=<topology>/<task> starts that recorded run as soon as the page loads.
 */

import { EXAMPLE_TASKS } from './config.js';
import { getDefaultEndpoint } from './utils.js';
import { getCustomEndpoint } from '../../common/js/backend.js';
import { getDataMode } from '../../common/js/data.js';
import { NOTICES, modeLabels, portalLink, switchElement } from '../../common/js/mode.js';

const realFetch = window.fetch.bind(window);
let FIXTURES = null;
let MODE = null; // the active data set (common/js/data.js): decides the banner and provenance wording
 // base URL of the active data set's fixtures/, set once demo mode is decided
const DEFAULT_TOPOLOGY = 'vertical'; // used for "Auto": the recorded runs always force one
const SPEEDS = [1, 5, 20];
const SPEED_KEY = 'agentverse.demoSpeed';
const PROBE_TIMEOUT_MS = 2000;

const ORIGINAL_EXAMPLES = { ...EXAMPLE_TASKS };
const params = new URLSearchParams(window.location.search);

const state = {
  speed: initialSpeed(),
  index: null,
  replays: new Set(),
  current: null, // the latest run's Replay, for the status-bar clock
};

function initialSpeed() {
  const fromParam = Number(params.get('speed'));
  if (fromParam > 0) return fromParam;
  try {
    const stored = Number(window.localStorage.getItem(SPEED_KEY));
    if (SPEEDS.includes(stored)) return stored;
  } catch (_) { /* storage unavailable */ }
  return 5;
}

const normalise = (text) => String(text || '').replace(/^\|+/, '').replace(/\s+/g, ' ').trim();

// ---------------------------------------------------------------------------
// Demo-mode decision
// ---------------------------------------------------------------------------

async function backendReachable() {
  try {
    await realFetch(getDefaultEndpoint(), {
      method: 'GET',
      mode: 'no-cors',
      signal: AbortSignal.timeout(PROBE_TIMEOUT_MS),
    });
    return true;
  } catch (_) {
    return false;
  }
}

async function decideDemo() {
  const flag = params.get('demo');
  if (flag === '1' || flag === 'true') return true;
  if (flag === '0' || flag === 'false') return false;
  if (!getCustomEndpoint() && /\.(github\.io|netlify\.app)$/.test(window.location.hostname)) return true;
  return !(await backendReachable());
}

export const demoReady = decideDemo().then(async (on) => {
  if (!on) return false;
  const data = await getDataMode();
  FIXTURES = new URL('fixtures/', data.base);
  MODE = data;
  try {
    await loadIndex();
  } catch (err) {
    // a data set without fixtures (the public one, until its synthetic runs are added) is not an error
    const log = data.mode === 'public' ? console.info : console.error;
    log('[AgentVerse demo] Could not load fixtures; demo mode disabled:', err);
    return false;
  }
  useRecordedExampleTasks();
  window.agentverseReplaySpeed = state.speed;
  // ui-state.js shows this (recorded ms of the current replay) instead of wall-clock time
  window.agentverseReplayClock = () => (state.current ? state.current.now() : null);
  showBanner(data);
  startRequestedReplay();
  console.info('[AgentVerse demo] Demo mode on: replaying recorded runs from', FIXTURES.href);
  return true;
});

export const isDemoMode = () => demoReady;

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

async function loadJson(relPath) {
  const resp = await realFetch(new URL(relPath, FIXTURES));
  if (!resp.ok) {
    resp.body?.cancel(); // an unread body keeps the request open
    throw new Error(`HTTP ${resp.status} for fixtures/${relPath}`);
  }
  return resp.json();
}

async function loadIndex() {
  if (!state.index) state.index = await loadJson('index.json');
  return state.index;
}

/** The recorded tasks differ from EXAMPLE_TASKS (except math), so show what was really run. */
function useRecordedExampleTasks() {
  for (const entry of state.index.fixtures) {
    if (entry.topology === DEFAULT_TOPOLOGY) EXAMPLE_TASKS[entry.task] = entry.original_task;
  }
}

/** ?replay=<topology>/<task> (e.g. from the results page) starts that recorded run on load. */
function startRequestedReplay() {
  const [topology, task] = (params.get('replay') || '').split('/');
  if (!findEntry(topology, task)) return;
  const run = () => {
    const select = document.getElementById('topology');
    const runBtn = document.getElementById('runBtn');
    if (!window.agentverse || !select || !runBtn) return false;
    select.value = topology;
    window.agentverse.loadExample(task);
    runBtn.click();
    return true;
  };
  if (!run()) window.addEventListener('load', run, { once: true });
}

function taskKeyFor(text) {
  const wanted = normalise(text);
  for (const entry of state.index.fixtures) {
    if (normalise(entry.original_task) === wanted) return { key: entry.task, custom: false };
  }
  for (const [key, example] of Object.entries(ORIGINAL_EXAMPLES)) {
    if (normalise(example) === wanted) return { key, custom: false };
  }
  return { key: 'math', custom: true };
}

function findEntry(topology, task) {
  return state.index.fixtures.find((e) => e.topology === topology && e.task === task);
}

/** Cosmetic: drop the stray "||" the paper's runner put in front of every recorded task. */
function forDisplay(response) {
  return { ...response, original_task: normalise(response.original_task) };
}

// ---------------------------------------------------------------------------
// Replay
// ---------------------------------------------------------------------------

/**
 * Feeds SSE frames into a stream controller on the recorded schedule. Delays are in
 * recorded milliseconds divided by the current speed; a speed change reschedules the
 * pending frame so it takes effect immediately. now() is the replay clock in recorded
 * milliseconds (it runs N times faster at N×), which the status-bar timer shows.
 */
class Replay {
  constructor(events, controller, onDone) {
    this.events = events;
    this.controller = controller;
    this.onDone = onDone;
    this.encoder = new TextEncoder();
    this.i = 0;
    this.timer = null;
    this.pending = false;
    // clock anchor: recorded time t at wall time `wall`, advancing at `speed`
    this.clock = { t: 0, wall: performance.now(), speed: state.speed };
  }

  /** Recorded milliseconds since the run's first event; frozen once the replay stops. */
  now() {
    const { t, wall, speed } = this.clock;
    if (!this.pending) return t;
    return Math.min(this.events[this.i].t_ms, t + (performance.now() - wall) * speed);
  }

  _anchor(t) {
    this.clock = { t, wall: performance.now(), speed: state.speed };
  }

  start() {
    this._emitDue();
  }

  _emitDue() {
    this.timer = null;
    this.pending = false;
    const t = this.events[this.i].t_ms;
    this._anchor(t);
    while (this.i < this.events.length && this.events[this.i].t_ms === t) {
      const { event, data } = this.events[this.i++];
      this.controller.enqueue(this.encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`));
    }
    if (this.i >= this.events.length) {
      this.controller.close();
      this.stop();
      return;
    }
    this._schedule(this.events[this.i].t_ms - t);
  }

  _schedule(recordedDelay) {
    this.pending = true;
    this.timer = setTimeout(() => this._emitDue(), recordedDelay / state.speed);
  }

  reschedule() {
    if (!this.pending) return;
    clearTimeout(this.timer);
    const t = this.now(); // at the old speed, up to this moment
    this._anchor(t);
    this._schedule(Math.max(0, this.events[this.i].t_ms - t));
  }

  stop() {
    if (this.pending) this._anchor(this.now()); // freeze the clock where it stopped
    clearTimeout(this.timer);
    this.timer = null;
    this.pending = false;
    this.onDone(this);
  }
}

function prepareEvents(events, response, maxIterations) {
  return events.map((ev) => {
    if (ev.event === 'complete') return { ...ev, data: response };
    if (ev.event === 'iteration_start') {
      const max = Math.max(maxIterations || 0, ev.data.iteration + 1);
      const message = String(ev.data.message || '').replace(/ of \d+/, ` of ${max}`);
      return { ...ev, data: { ...ev.data, max_iterations: max, message } };
    }
    return ev;
  });
}

function streamResponse(events, signal) {
  let replay = null;
  const abortError = () => new DOMException('The operation was aborted.', 'AbortError');
  const body = new ReadableStream({
    start(controller) {
      if (signal?.aborted) {
        controller.error(abortError());
        return;
      }
      replay = new Replay(events, controller, (r) => {
        state.replays.delete(r);
        signal?.removeEventListener('abort', onAbort);
      });
      const onAbort = () => {
        replay.stop();
        try { controller.error(abortError()); } catch (_) { /* already closed */ }
      };
      signal?.addEventListener('abort', onAbort, { once: true });
      state.replays.add(replay);
      state.current = replay;
      replay.start();
    },
    cancel() {
      replay?.stop();
    },
  });
  return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } });
}

const jsonResponse = (status, obj) =>
  new Response(JSON.stringify(obj), { status, headers: { 'Content-Type': 'application/json' } });

async function handleRun(init) {
  let request = {};
  try {
    request = JSON.parse(init.body || '{}');
  } catch (_) { /* fall through with defaults */ }
  const topology = request.force_structure || DEFAULT_TOPOLOGY;
  const { key, custom } = taskKeyFor(request.task);
  const entry = findEntry(topology, key);
  if (!entry) return jsonResponse(404, { error: `No recorded run for ${topology}/${key}` });

  const response = forDisplay(await loadJson(entry.files.response));
  updateBanner(entry, custom);
  if (!request.stream || !entry.files.events) return jsonResponse(200, response);

  const events = await loadJson(entry.files.events);
  return streamResponse(prepareEvents(events, response, request.max_iterations), init.signal);
}

async function handleGet(taskId) {
  const entry = state.index.fixtures.find((e) => e.task_id === taskId);
  if (!entry) return jsonResponse(404, { error: 'Task not found', task_id: taskId });
  const result = forDisplay(await loadJson(entry.files.response));
  updateBanner(entry, false);
  return jsonResponse(200, {
    task_id: taskId,
    task: result.original_task,
    max_iterations: Math.max(3, result.iterations || 1),
    success_threshold: 70,
    result,
  });
}

/** Agent A API routes only (POST /agentverse, GET /agentverse/<task_id>); file paths (with a dot) pass through. */
function matchRoute(url, method) {
  const m = url.pathname.match(/\/agentverse(?:\/([^/.]+))?\/?$/);
  if (!m) return null;
  if (method === 'POST' && !m[1]) return { kind: 'run' };
  if (method === 'GET' && m[1]) return { kind: 'get', taskId: decodeURIComponent(m[1]) };
  return null;
}

window.fetch = async (input, init = {}) => {
  const href = typeof input === 'string' || input instanceof URL ? String(input) : input.url;
  const method = (init.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
  const route = matchRoute(new URL(href, window.location.href), method);
  if (route?.kind === 'run') state.current = null; // a new run: drop the previous replay's clock
  if (!route || !(await demoReady)) return realFetch(input, init);
  return route.kind === 'run' ? handleRun(init) : handleGet(route.taskId);
};

// ---------------------------------------------------------------------------
// Banner
// ---------------------------------------------------------------------------

let banner = null;

function showBanner(data) {
  if (banner) return;
  banner = document.createElement('div');
  banner.id = 'demoBanner';
  banner.setAttribute('role', 'status');
  banner.style.cssText = [
    'position:fixed', 'left:12px', 'right:12px', 'bottom:12px', 'z-index:1000',
    'display:flex', 'flex-wrap:wrap', 'align-items:center', 'gap:6px 12px',
    'padding:8px 12px', 'border-radius:8px', 'font-size:13px', 'line-height:1.4',
    // theme tokens (common/css/theme.css), so the banner follows light / dark
    'background:var(--bg-secondary)', 'color:var(--text-primary)',
    'border:1px solid var(--orange)', 'box-shadow:var(--shadow-2)',
  ].join(';');
  const options = SPEEDS.map((s) => `<option value="${s}">${s}×</option>`).join('');
  const synthetic = data.mode === 'public';
  banner.innerHTML = `
    <strong style="color:var(--orange)">Demo</strong>
    <span id="demoText"></span>
    <span id="demoProvenance" style="color:var(--text-secondary)"></span>
    <label style="margin-left:auto;display:flex;align-items:center;gap:6px;margin-bottom:0">
      Speed <select id="demoSpeed" aria-label="Replay speed" style="width:auto;padding:2px 6px;margin:0">${options}</select>
    </label>`;
  const text = banner.querySelector('#demoText');
  const results = Object.assign(document.createElement('a'), {
    id: 'demoResultsLink',
    href: new URL('../../results/', import.meta.url).href,
    textContent: 'See all results →',
    style: 'color:var(--accent-text);font-weight:600',
  });
  if (synthetic) {
    text.append(`${NOTICES.playground} Timer shows replayed time. `, 'Real backend or real data: ', portalLink('Portal ▾'), '. ', results);
  } else {
    text.append(`${modeLabels(data).replay} `, results);
  }
  const sw = switchElement(data); // only when the real data is reachable (owner's machine)
  if (sw) banner.querySelector('label').before(sw);
  document.body.appendChild(banner);
  document.body.style.paddingBottom = `${banner.offsetHeight + 24}px`;

  const select = banner.querySelector('#demoSpeed');
  if (!SPEEDS.includes(state.speed)) select.insertAdjacentHTML('beforeend', `<option value="${state.speed}">${state.speed}×</option>`);
  select.value = String(state.speed);
  select.addEventListener('change', () => {
    state.speed = Number(select.value);
    window.agentverseReplaySpeed = state.speed;
    try { window.localStorage.setItem(SPEED_KEY, String(state.speed)); } catch (_) { /* ignore */ }
    state.replays.forEach((r) => r.reschedule());
  });
}

function updateBanner(entry, custom) {
  const el = banner?.querySelector('#demoProvenance');
  if (!el) return;
  const viewerUrl = new URL(`../open/?demo=1&task_id=${encodeURIComponent(entry.task_id)}`, import.meta.url);
  const synthetic = MODE && MODE.mode === 'public';
  const date = (entry.recorded_start_utc || '').slice(0, 10);
  const note = custom ? `Custom tasks can't run in the demo; showing the ${synthetic ? 'synthetic' : 'recorded'} math task. ` : '';
  el.innerHTML = '';
  el.append(
    synthetic
      ? `${note}${entry.topology_label} · ${entry.task} · Synthetic run · task `
      : `${note}${entry.topology_label} · ${entry.task} · recorded ${date} · ${entry.experiment} · task `,
    Object.assign(document.createElement('a'), {
      href: viewerUrl.href,
      textContent: synthetic ? entry.task_id : entry.task_id.slice(0, 8),
      title: `Open the ${synthetic ? 'synthetic' : 'recorded'} response (task_id ${entry.task_id})`,
      target: '_blank',
      rel: 'noopener',
      style: 'color:var(--accent-text)', // default link blue is unreadable on the dark banner
    }),
  );
}
