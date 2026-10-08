/**
 * Which data set the site shows: the real (private) one or the public one.
 *
 *   ui/data/private/   real summary, runs and recorded fixtures: gitignored, only on the owner's
 *                      machine
 *   ui/data/public/    real aggregates plus synthetic runs and fixtures: committed, hosted
 *
 * The mode is, in order:
 *   1. `?data=public|private` in the page URL (this page view only; not saved)
 *   2. the saved choice (localStorage key `agentraffic-data`, set by setDataMode())
 *   3. `private` if `data/private/manifest.json` loads (and says so), else `public`
 * A requested `private` falls back to `public` when the private data is not reachable, so a
 * link with `?data=private` never breaks the public site.
 *
 * Every loader goes through this module (results/js/util.js and the per-page analyses,
 * playground/js/mock-backend.js), so a page never hard-codes a data path. Plain ES module,
 * no dependencies.
 *
 * Note for loaders: `runs.json` and `fixtures/` may not exist in `public/` (they are added by
 * scripts/demo/generate_synthetic.py), so treat a 404 there as "not available".
 */

const STORAGE_KEY = 'agentraffic-data';
const MODES = ['private', 'public'];
/** ui/data/, relative to this file (ui/common/js/data.js). */
const DATA_ROOT = new URL('../../data/', import.meta.url);

let modePromise = null;

function validMode(value) {
  return MODES.includes(value) ? value : null;
}

function savedMode() {
  try {
    return validMode(window.localStorage.getItem(STORAGE_KEY));
  } catch (_) {
    return null; // storage unavailable (private window, blocked site data)
  }
}

function requestedMode() {
  try {
    const fromUrl = validMode(new URLSearchParams(window.location.search).get('data'));
    if (fromUrl) return fromUrl;
  } catch (_) { /* no location (should not happen in a page) */ }
  return savedMode();
}

/** The private manifest, or null when the private data is not here. */
async function probePrivate() {
  try {
    const resp = await fetch(new URL('private/manifest.json', DATA_ROOT), { cache: 'no-store' });
    if (!resp.ok) {
      resp.body?.cancel(); // an unread body keeps the request open (and the page 'loading')
      return null;
    }
    const manifest = await resp.json(); // a host that answers every path with a page is not it
    return manifest && manifest.mode === 'private' ? manifest : null;
  } catch (_) {
    return null;
  }
}

async function resolve() {
  const manifest = await probePrivate();
  const privateAvailable = manifest !== null;
  const wanted = requestedMode();
  const mode = wanted === 'public' ? 'public' : privateAvailable ? 'private' : 'public';
  return {
    mode,
    base: new URL(`${mode}/`, DATA_ROOT),
    synthetic: mode === 'public',
    privateAvailable,
    manifest: mode === 'private' ? manifest : null,
  };
}

/**
 * `{ mode: 'private'|'public', base: URL, synthetic: boolean, privateAvailable: boolean,
 *    manifest }`; resolved once per page (every caller gets the same object). `base` ends in a
 * slash (resolve files against it); `synthetic` is true when the runs and fixtures are
 * generated (public); `privateAvailable` says whether to offer the Real / Synthetic switch;
 * `manifest` is the private manifest (`{mode, generated}`) in private mode, else null.
 */
export function getDataMode() {
  if (!modePromise) modePromise = resolve();
  return modePromise;
}

/** URL of a file in the active data set, e.g. `await dataUrl('summary.json')`. */
export async function dataUrl(path) {
  const { base } = await getDataMode();
  return new URL(String(path).replace(/^\/+/, ''), base);
}

/** Fetches a JSON file of the active data set; throws `Error('<path>: HTTP <status>')`. */
export async function fetchData(path) {
  const resp = await fetch(await dataUrl(path));
  if (!resp.ok) {
    resp.body?.cancel();
    throw new Error(`${path}: HTTP ${resp.status}`);
  }
  return resp.json();
}

/**
 * Saves the choice and reloads the page in that mode. A `?data=` in the URL would override
 * the saved choice, so it is dropped first.
 */
export function setDataMode(mode) {
  if (!validMode(mode)) throw new Error(`unknown data mode: ${mode}`);
  try {
    window.localStorage.setItem(STORAGE_KEY, mode);
  } catch (_) { /* not saved: only this page view changes, via ?data= below */ }
  const url = new URL(window.location.href);
  url.searchParams.delete('data');
  if (savedMode() !== mode) url.searchParams.set('data', mode);
  if (url.href === window.location.href) window.location.reload();
  else window.location.replace(url.href);
}
