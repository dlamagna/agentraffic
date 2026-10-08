/**
 * ui/common/js/backend.js
 * -----------------------
 * Is the live Agent A backend reachable from this page? Used by the Playground menu
 * (./nav.js, the "Chat with Agent A" entry) and by the chat page (ui/playground/chat/), which need it.
 *
 * Same rule as the demo-mode decision in ui/playground/js/mock-backend.js:
 *   ?demo=1  no (demo / public mode)        ?demo=0  yes (use the endpoint, even if it fails)
 *   static hosts (*.github.io, *.netlify.app)  no
 *   otherwise a GET to http(s)://<host>:8101/agentverse, no-cors, 2 s timeout: any answer
 *   (even an opaque one) means something listens there.
 *
 *   import { backendReachable, agentAUrl } from '../common/js/backend.js';
 *   if (!(await backendReachable())) showOfflineNote();
 *
 * The first call probes; later calls share its promise unless { fresh: true } is passed.
 */

export const AGENT_A_PORT = 8101;
const PROBE_TIMEOUT_MS = 2000;
const STATIC_HOST = /\.(github\.io|netlify\.app)$/;

const ENDPOINT_KEY = 'agentraffic-endpoint';

/**
 * The visitor's own backend (Portal ▾ → Connect), saved in this browser: Agent A's full
 * endpoint, e.g. http://localhost:8101/agentverse, or '' when none is set.
 */
export function getCustomEndpoint() {
  try {
    return window.localStorage.getItem(ENDPOINT_KEY) || '';
  } catch (_) {
    return ''; // storage unavailable
  }
}

/**
 * Normalises what the visitor typed: an http(s) URL, with /agentverse added when no path is
 * given. Returns the endpoint, or null when it is not a usable URL.
 */
export function parseEndpoint(value) {
  let url;
  try { url = new URL(String(value).trim()); } catch (_) { return null; }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
  const path = url.pathname === '/' ? '/agentverse' : url.pathname.replace(/\/$/, '');
  return `${url.origin}${path}`;
}

/** Saves the endpoint ('' clears it); true when it was stored. */
export function setCustomEndpoint(value) {
  try {
    if (!value) window.localStorage.removeItem(ENDPOINT_KEY);
    else window.localStorage.setItem(ENDPOINT_KEY, value);
    pending = null; // probe again
    return true;
  } catch (_) {
    return false;
  }
}

/** Agent A's URL for `path`: the saved endpoint's origin, else this page's host (http: when the page is a file). */
export function agentAUrl(path = '') {
  const custom = getCustomEndpoint();
  if (custom) return `${new URL(custom).origin}${path}`;
  const protocol = window.location.protocol === 'file:' ? 'http:' : window.location.protocol;
  const host = window.location.hostname || 'localhost';
  return `${protocol}//${host}:${AGENT_A_PORT}${path}`;
}

let pending = null;

async function probe() {
  const flag = new URLSearchParams(window.location.search).get('demo');
  if (flag === '1' || flag === 'true') return false;
  if (flag === '0' || flag === 'false') return true;
  if (!getCustomEndpoint() && STATIC_HOST.test(window.location.hostname)) return false;
  try {
    await fetch(agentAUrl('/agentverse'), {
      method: 'GET',
      mode: 'no-cors',
      cache: 'no-store',
      signal: AbortSignal.timeout(PROBE_TIMEOUT_MS),
    });
    return true;
  } catch (_) {
    return false;
  }
}

/** Resolves true when Agent A answers (or ?demo=0), false in demo / public mode. */
export function backendReachable({ fresh = false } = {}) {
  if (!pending || fresh) pending = probe();
  return pending;
}
