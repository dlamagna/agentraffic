/**
 * ui/common/js/mode.js
 * --------------------
 * What the site says about its data, written once so that every page says the same thing.
 * The rule: only the summary-level
 * data is real; everything below it (runs, timelines, call details, replays) is synthetic in
 * public mode.
 *
 *   NOTICES / LABELS            the wording, per mode
 *   noticeElement(kind)         a notice for 'runs' | 'playground' | 'chat' (a <p>, with the Portal pointer)
 *   switchElement(data)         the "Data: Real | Synthetic" switch, or null when private data is not here
 *   portalLink(text)            a link that opens the Portal ▾ menu (nav.js listens for the event)
 *   mountMode()                 fills every [data-mode-notice="kind"] (public mode only: hidden in
 *                               private mode) and [data-mode-switch]; on the results pages the switch
 *                               is added to the header
 *
 * nav.js calls mountMode() on every page. No dependency on nav.js (it listens for the
 * 'portal:open' event this module dispatches).
 */

import { getDataMode, setDataMode } from './data.js';

export const NOTICES = {
  runs: 'Individual runs, timelines and call details are synthetic, generated to match the real aggregates.',
  playground: 'Demo: synthetic data, replayed in the browser; nothing is sent to a real backend.',
  chat: 'Demo: synthetic data, replayed in the browser; nothing is sent to a real backend. '
    + 'This page needs a live backend, so Send is off.',
};

/** Wording that differs per data mode; private keeps today's wording. */
export const LABELS = {
  private: {
    replay: 'Replay of a recorded run from the paper experiments. No live backend. Timer shows recorded time.',
    runKind: 'Recorded run',
    badge: 'runs',
  },
  public: {
    replay: 'Synthetic run: generated to illustrate the UI, not a recorded run. Timer shows replayed time.',
    runKind: 'Synthetic run',
    badge: 'synthetic',
  },
};

export const modeLabels = (data) => LABELS[data && data.mode === 'public' ? 'public' : 'private'];

function node(tag, attrs = {}, children = []) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'text') n.textContent = v;
    else if (v !== false && v != null) n.setAttribute(k, v === true ? '' : v);
  }
  n.append(...[].concat(children));
  return n;
}

/** A link that opens the Portal ▾ menu (on the group: 'connect' | 'signin'). */
export function portalLink(text = 'Portal ▾', group = 'connect') {
  const a = node('a', { href: '#portal', class: 'portal-link', 'data-portal-open': group, text });
  a.addEventListener('click', (ev) => {
    ev.preventDefault();
    document.dispatchEvent(new CustomEvent('portal:open', { detail: { group } }));
  });
  return a;
}

/** The notice for `kind`: the shared sentence plus a pointer to the Portal menu. */
export function noticeElement(kind = 'runs') {
  return node('p', { class: 'mode-notice', 'data-mode-notice-text': kind, role: 'note' }, [
    node('span', { text: `${NOTICES[kind] || NOTICES.runs} ` }),
    node('span', { class: 'mode-notice__more' }, ['Real backend or real data: ', portalLink('Portal ▾'), '.']),
  ]);
}

/** "Data: Real | Synthetic" (a pressed-button pair), or null when the private data is not reachable. */
export function switchElement(data) {
  if (!data || !data.privateAvailable) return null;
  const choice = (mode, label) => {
    const b = node('button', {
      type: 'button', 'data-mode': mode, 'aria-pressed': String(data.mode === mode), text: label,
    });
    b.addEventListener('click', () => { if (data.mode !== mode) setDataMode(mode); });
    return b;
  };
  return node('div', { class: 'mode-switch', role: 'group', 'aria-label': 'Data shown' }, [
    node('span', { class: 'mode-switch__label', text: 'Data' }),
    choice('private', 'Real'),
    choice('public', 'Synthetic'),
  ]);
}

/** Notices (public mode) and the switch (when private data is reachable) for the whole page. */
export async function mountMode(root = document) {
  let data;
  try { data = await getDataMode(); } catch (_) { return; }
  root.querySelectorAll('[data-mode-notice]').forEach((host) => {
    if (data.mode === 'public') {
      host.replaceChildren(noticeElement(host.dataset.modeNotice));
      host.hidden = false;
    } else {
      host.replaceChildren();
      host.hidden = true;
    }
  });
  let hosts = [...root.querySelectorAll('[data-mode-switch]')];
  if (!hosts.length && document.body.dataset.resultsPage && data.privateAvailable) {
    const end = document.querySelector('.site-header .header-end');
    if (end) {
      const host = node('div', { 'data-mode-switch': '' });
      end.insertBefore(host, end.querySelector('[data-theme-toggle]'));
      hosts = [host];
    }
  }
  hosts.forEach((host) => {
    const sw = switchElement(data);
    if (sw) host.replaceChildren(sw);
    else host.remove();
  });
}
