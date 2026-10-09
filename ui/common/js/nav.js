/**
 * ui/common/js/nav.js
 * -------------------
 * Site chrome shared by every page: the header links with the Playground, Results and Docs menus, the paper footer,
 * the BibTeX block, and links / text filled from the paper metadata in ./site.js.
 *
 * Load it as a module; on import it fills every placeholder on the page:
 *
 *   <nav class="header-links" data-site-nav="runner" aria-label="Site"></nav>
 *       header links for page "runner" (see MENUS; the 'playground' entry is the Playground ▾
 *       menu of the interactive tools, 'results' the Results ▾ menu of the four results pages plus the secondary Beta entry),
 *       then Docs ▾, Paper ↗, Code ↗ and Portal ▾ (connect your own backend, sign in)
 *   <footer data-site-footer></footer>          paper title, authors, DOI, GitHub, cite
 *   <div data-site-cite></div>                  BibTeX with a copy button
 *   <a data-site-href="paper | doi | repo | repo:<path> | cite | agentverse-paper | agentverse-repo">
 *                                               href from site.js
 *   <span data-site-text="doi | title | venue | authors">         text from site.js
 *
 *   <script type="module" src="../common/js/nav.js"></script>
 *
 * Links are made relative to the page (this file sits in ui/common/js/, two levels below
 * ui/), so the site works from any sub-path. Each page styles its own header links
 * (.site-link, .docs-menu__button) to match its header; the Docs panel, footer and BibTeX
 * block are styled by ../css/site.css.
 *
 * Playground, Results and Docs menus: each a disclosure button (aria-expanded / aria-controls) over a list of links.
 * Enter / Space toggle it, ArrowDown / ArrowUp open it on the first / last entry and move
 * between entries (Home / End jump), Esc closes it and returns focus to the button; it also
 * closes on a click outside or when focus leaves it.
 */

import {
  AGENTVERSE, AUTHORS, BIBTEX, DOI, DOI_URL, PAPER_URL, PUBLIC_SITE_URL, REPO_URL, SIGN_IN_URL, TITLE, VENUE, VENUE_SHORT, repoUrl,
} from './site.js';
import { backendReachable, getCustomEndpoint, parseEndpoint, setCustomEndpoint } from './backend.js';
import { getDataMode } from './data.js';
import { mountMode, switchElement } from './mode.js';

const ROOT = new URL('../../', import.meta.url); // ui/

/** Pages a header can link to; paths are relative to ui/. */
export const PAGES = {
  home: { label: 'Home', path: '', title: 'All tools' },
  playground: { label: 'Playground', path: 'playground/run/', title: 'The interactive tools' },
  runner: { label: 'Run a workflow', path: 'playground/run/', title: 'Start an AgentVerse run, or replay a recorded one' },
  viewer: { label: 'Open a saved run', path: 'playground/open/', title: 'Load a response.json or a run ID' },
  compare: { label: 'Compare topologies', path: 'playground/compare/', title: 'One task under all three topologies, side by side' },
  results: { label: 'Results', path: 'results/', title: "The paper's findings from 1,481 recorded runs" },
  chat: { label: 'Chat with Agent A', path: 'playground/chat/', title: 'Send one task to the orchestrator; needs the live backend' },
};

/**
 * The Playground menu (the interactive tools), in order. The old URLs (agentverse/,
 * agentverse/viewer.html, chat/) are redirect stubs to these, so old links and ?replay= deep
 * links keep working. 'chat' needs the live backend: in demo / public mode
 * (./backend.js) its hint becomes CHAT_OFFLINE and it gets data-backend="offline".
 */
export const PLAYGROUND = ['runner', 'viewer', 'compare', 'chat'].map((id) => ({
  id, label: PAGES[id].label, path: PAGES[id].path, description: PAGES[id].title,
}));
const CHAT_OFFLINE = 'Send one task to the orchestrator; needs the local backend';

/** The Docs menu, in order. Add an entry here when a new docs page is written. */
export const DOCS = [
  {
    id: 'blog', label: 'Blog post', path: 'docs/blog/',
    description: `A short blog post about our ${VENUE_SHORT} paper`,
  },
  {
    id: 'agentverse', label: 'AgentVerse', path: 'docs/agentverse/',
    description: 'The workflow, its three topologies and how it is measured',
  },
];

/**
 * The results pages (Results ▾ menu and the tabs of ui/results/), in order. The results
 * pages add their filter query (?topo=…&task=…) to these links (ui/results/js/shell.js).
 */
export const RESULTS = [
  { id: 'overview', label: 'Overview', path: 'results/', description: 'Headline findings, the testbed and Table 2' },
  { id: 'traffic', label: 'Traffic patterns', path: 'results/traffic-patterns/', description: 'Inter-arrival times, distribution fits, agent count' },
  { id: 'system', label: 'System load', path: 'results/system-load/', description: 'Network bytes, cross-layer correlations, tasks' },
  { id: 'runs', label: 'Run explorer', path: 'results/run-explorer/', description: 'All recorded runs and their LLM calls' },
];

/**
 * The Beta page: exploratory analyses outside the research. Listed last in the Results ▾ menu,
 * visibly secondary, and not one of the four core tabs (shell.js adds no tab or Next link for it).
 */
export const BETA = {
  id: 'beta', label: 'Beta', path: 'results/beta/', description: 'Ideas for further analysis, outside the scope of the research',
};

/**
 * Header links per page (data-site-nav value), before Docs / Paper / Code. An entry is a
 * PAGES key or { id, label?, strong?, accent? }; a page listing itself shows as current.
 * 'results' renders as the Results ▾ menu (RESULTS), 'playground' as the Playground ▾ menu
 * (PLAYGROUND). Every page: Home · Playground ▾ · Results ▾ · Docs ▾ · Paper ↗ · Code ↗ · Portal ▾.
 */
const MAIN = ['home', 'playground', 'results'];
const MENUS = {
  launcher: MAIN,
  runner: ['home', 'playground', { id: 'results', strong: true }],
  viewer: ['home', 'playground', { id: 'results', strong: true }],
  compare: ['home', 'playground', { id: 'results', strong: true }],
  chat: MAIN,
  results: MAIN,
  'docs-blog': MAIN,
  'docs-agentverse': MAIN,
};

const SVG_NS = 'http://www.w3.org/2000/svg';
const ICONS = {
  caret: '<path d="M6 9l6 6 6-6"/>',
  external: '<path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/>',
};

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === false || v == null) continue;
    if (k === 'text') node.textContent = v;
    else node.setAttribute(k, v === true ? '' : v);
  }
  node.append(...[].concat(children));
  return node;
}

function icon(name, cls) {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('class', cls);
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  svg.innerHTML = ICONS[name];
  return svg;
}

/** A path under ui/ as an href relative to the current page ('' -> the ui/ index). */
export function siteHref(path) {
  const target = new URL(path, ROOT);
  const here = new URL('.', window.location.href);
  if (here.origin !== ROOT.origin || !here.pathname.startsWith(ROOT.pathname)) return target.href;
  const depth = here.pathname.slice(ROOT.pathname.length).split('/').filter(Boolean).length;
  const [file, hash = ''] = path.split('#');
  return ('../'.repeat(depth) + file || './') + (hash ? `#${hash}` : '');
}

function isCurrent(path) {
  const strip = (p) => p.replace(/index\.html$/, '');
  return strip(new URL(path, ROOT).pathname) === strip(window.location.pathname);
}

function externalLink(label, href, title, cls = '') {
  return el('a', { class: `site-link site-link--ext ${cls}`.trim(), href, target: '_blank', rel: 'noopener', title }, [
    label,
    icon('external', 'site-link__icon'),
    el('span', { class: 'site-sr', text: ' (opens in a new tab)' }),
  ]);
}

// ---------------------------------------------------------------------------
// Menus (Docs ▾, Results ▾)
// ---------------------------------------------------------------------------

let menuCount = 0;

/**
 * A disclosure menu. `kind` names it ('docs' | 'results' | 'playground'): every element carries the shared
 * .site-menu* class (styles) plus .<kind>-menu* (so each menu can be found on its own).
 * `entries`: [{ id, label, description, path }]; `dataKey` is the item's data attribute.
 */
function dropdown(kind, label, entries, { dataKey = 'item', strong = false, content = null } = {}) {
  const k = (part) => `site-menu${part} ${kind}-menu${part}`;
  const id = `site-${kind}-menu-${++menuCount}`;
  const wrap = el('div', { class: k('') });
  const current = entries.some((d) => isCurrent(d.path));
  const button = el('button', {
    type: 'button', class: `${k('__button')}${current ? ' is-current' : ''}${strong ? ' site-link--strong' : ''}`,
    'aria-expanded': 'false', 'aria-controls': id,
  }, [label, icon('caret', 'site-menu__caret')]);
  const panel = el('div', { class: k('__panel'), id, hidden: true });
  const list = el('ul', { class: 'site-menu__list' });
  for (const item of entries) {
    const a = el('a', { class: k('__item'), href: siteHref(item.path), [`data-${dataKey}`]: item.id }, [
      el('span', { class: k('__label'), text: item.label }),
    ]);
    if (item.description) a.title = item.description; // a tooltip, not a second line: menus stay short
    if (item.tag) {
      a.classList.add('site-menu__item--secondary');
      a.append(el('span', { class: 'site-menu__tag site-menu__tag--beta', text: item.tag }));
    }
    if (isCurrent(item.path)) a.setAttribute('aria-current', 'page');
    list.append(el('li', {}, a));
  }
  if (content) panel.append(content); // a menu of forms and links (Portal ▾) instead of a plain list
  else panel.append(list);
  wrap.append(button, panel);

  const items = () => [...panel.querySelectorAll('a[href], button, input, summary')].filter((n) => !n.closest('[hidden]:not(.site-menu__panel)'));
  const isOpen = () => button.getAttribute('aria-expanded') === 'true';

  function place() {
    // keep the panel inside the viewport (it hangs from the button's left edge)
    panel.style.left = '0px';
    const margin = 8;
    const vw = document.documentElement.clientWidth;
    const r = panel.getBoundingClientRect();
    let shift = 0;
    if (r.right > vw - margin) shift = vw - margin - r.right;
    if (r.left + shift < margin) shift = margin - r.left;
    panel.style.left = `${shift}px`;
  }
  function onDocPointer(ev) { if (!wrap.contains(ev.target)) close(); }
  function onDocKey(ev) { if (ev.key === 'Escape') { close(); button.focus(); } }
  function open() {
    if (isOpen()) return;
    button.setAttribute('aria-expanded', 'true');
    panel.hidden = false;
    place();
    document.addEventListener('pointerdown', onDocPointer, true);
    document.addEventListener('keydown', onDocKey);
    window.addEventListener('resize', place);
  }
  function close() {
    if (!isOpen()) return;
    button.setAttribute('aria-expanded', 'false');
    panel.hidden = true;
    document.removeEventListener('pointerdown', onDocPointer, true);
    document.removeEventListener('keydown', onDocKey);
    window.removeEventListener('resize', place);
  }

  button.addEventListener('click', () => (isOpen() ? close() : open()));
  wrap.addEventListener('focusout', (ev) => {
    if (ev.relatedTarget && !wrap.contains(ev.relatedTarget)) close();
  });
  wrap.addEventListener('keydown', (ev) => {
    const list = items();
    const i = list.indexOf(document.activeElement);
    let next = null;
    if (ev.key === 'ArrowDown') next = i < 0 ? 0 : (i + 1) % list.length;
    else if (ev.key === 'ArrowUp') next = i < 0 ? list.length - 1 : (i - 1 + list.length) % list.length;
    else if ((ev.key === 'Home' || ev.key === 'End') && i >= 0 && document.activeElement.tagName !== 'INPUT') next = ev.key === 'Home' ? 0 : list.length - 1;
    else if (ev.key === 'Escape' && isOpen()) {
      close();
      button.focus();
      ev.preventDefault();
      ev.stopPropagation();
      return;
    }
    if (next === null) return;
    open();
    list[next].focus();
    ev.preventDefault();
  });
  wrap.openMenu = () => { open(); return panel; };
  wrap.menuButton = button;
  return wrap;
}

// ---------------------------------------------------------------------------
// Portal ▾: real connectivity (Connect, no login) and the real-data switch (owner's machine)
// ---------------------------------------------------------------------------

/** The Connect group: the visitor's own backend, saved in this browser (./backend.js). */
function connectGroup() {
  const input = el('input', {
    type: 'url', id: 'portalEndpoint', name: 'endpoint', autocomplete: 'off', spellcheck: 'false',
    placeholder: 'https://your-backend.example.com', 'aria-label': 'Your backend endpoint (Agent A)',
  });
  const status = el('p', { class: 'portal-menu__status', role: 'status' });
  const save = el('button', { type: 'submit', text: 'Save' });
  const clear = el('button', { type: 'button', class: 'portal-menu__clear', text: 'Clear', hidden: true });
  const form = el('form', { class: 'portal-menu__field', novalidate: true }, [input, save]);
  const show = () => {
    const current = getCustomEndpoint();
    input.value = current;
    clear.hidden = !current;
    status.textContent = current ? `Using your backend: ${current}` : 'No backend set: the Playground uses the demo.';
  };
  form.addEventListener('submit', (ev) => {
    ev.preventDefault();
    const endpoint = parseEndpoint(input.value);
    if (!endpoint) {
      status.textContent = 'Enter an http:// or https:// URL, e.g. https://your-backend.example.com';
      return;
    }
    if (!setCustomEndpoint(endpoint)) {
      status.textContent = 'This browser would not save it (storage is blocked).';
      return;
    }
    show();
    status.textContent = `Saved. Reload to use ${endpoint}.`;
  });
  clear.addEventListener('click', () => {
    setCustomEndpoint('');
    show();
    status.textContent = 'Cleared. Reload to go back to the demo.';
  });
  show();
  return el('fieldset', { class: 'portal-menu__group', 'data-portal-group': 'connect' }, [
    el('legend', { text: 'Connect your own LLM backend' }),
    el('p', { class: 'portal-menu__text', text: 'Send the Playground and Chat to your own stack: enter the entry point of Agent A, the orchestrator every task goes to. Kept in this browser only.' }),
    el('label', { class: 'portal-menu__label', for: 'portalEndpoint', text: 'Agent A entry point' }),
    form,
    clear,
    status,
    el('a', { class: 'portal-menu__link portal-menu__readme', href: `${repoUrl('README.md')}#connect-the-website-to-your-stack`, target: '_blank', rel: 'noopener', text: 'Where to find the entry point (README) ↗' }),
  ]);
}

/** True on the login-protected copy itself (production or a preview URL), not on a local `make local`. */
function onPrivateCopy() {
  const host = new URL(SIGN_IN_URL).hostname;
  return location.hostname === host || location.hostname.endsWith(`.${host}`);
}

/** Ends the Cloudflare Access session, then goes to the public site. */
function signOutButton() {
  const button = el('button', { type: 'button', class: 'portal-menu__signout', 'data-portal-link': 'signout', text: 'Sign out' });
  button.addEventListener('click', async () => {
    button.disabled = true;
    // The logout answer clears the Access cookies, then redirects to the team login domain: that redirect is
    // not followed (redirect: 'manual'), so the request cannot fail on it. Either way, go to the public site.
    try {
      await fetch('/cdn-cgi/access/logout', { credentials: 'same-origin', cache: 'no-store', redirect: 'manual' });
    } catch (_) { /* still signed out of this site, or nothing to sign out of */ }
    location.href = PUBLIC_SITE_URL;
  });
  return button;
}

/** The real-data state and the Real / Synthetic switch, shown only when the real data is reachable. */
function signInGroup(data) {
  if (!(data && data.privateAvailable)) {
    // public site: a way in to the copy with the real data
    return el('section', { class: 'portal-menu__group portal-menu__card', 'data-portal-group': 'signin', 'aria-labelledby': 'portalSignInTitle' }, [
      el('h3', { class: 'portal-menu__card-title', id: 'portalSignInTitle', text: 'Sign in to see the real runs' }),
      el('p', { class: 'portal-menu__text', text: 'The research group can see the data behind the paper:' }),
      el('ul', { class: 'portal-menu__benefits' }, [
        el('li', { text: 'every recorded run in the Run explorer' }),
        el('li', { text: 'replays of real runs, with their prompts and replies' }),
        el('li', { text: 'the Beta analyses' }),
      ]),
      el('a', { class: 'portal-menu__signin', href: SIGN_IN_URL, 'data-portal-link': 'signin', target: '_blank', rel: 'noopener', text: 'Sign in ↗' }),
      el('p', { class: 'portal-menu__fine', text: 'This public site shows the real aggregates with synthetic runs.' }),
    ]);
  }
  const group = el('section', { class: 'portal-menu__group portal-menu__card', 'data-portal-group': 'signin', 'aria-labelledby': 'portalSignInTitle' }, [
    el('h3', { class: 'portal-menu__card-title', id: 'portalSignInTitle', text: 'Signed in: real data' }),
    el('p', { class: 'portal-menu__text', text: 'You are seeing the recorded runs. Switch to the synthetic data to see what the public site shows.' }),
  ]);
  const sw = switchElement(data);
  if (sw) group.append(sw);
  if (onPrivateCopy()) group.append(signOutButton());
  return group;
}

/** The Portal ▾ menu. The data mode is known a moment later: the real-data group is then redrawn. */
function portalMenu() {
  const content = el('div', { class: 'portal-menu__content' }, [signInGroup(null), connectGroup()]);
  const menu = dropdown('portal', 'Portal', [], { content });
  getDataMode().then((data) => {
    content.querySelector('[data-portal-group="signin"]').replaceWith(signInGroup(data));
    if (data.privateAvailable) menu.menuButton.dataset.signedIn = '';
  }).catch(() => {});
  document.addEventListener('portal:open', (ev) => {
    const panel = menu.openMenu();
    const target = panel.querySelector(`[data-portal-group="${ev.detail?.group || 'connect'}"]`);
    (target?.querySelector('input, a[href], button') || menu.menuButton).focus();
  });
  return menu;
}

// ---------------------------------------------------------------------------
// Header links
// ---------------------------------------------------------------------------

/** The Playground ▾ menu; the chat entry's hint says "needs the local backend" when no Agent A answers. */
function playgroundMenu(label, strong) {
  const menu = dropdown('playground', label, PLAYGROUND, { dataKey: 'tool', strong });
  backendReachable().then((live) => {
    if (live) return;
    const chat = menu.querySelector('[data-tool="chat"]');
    chat.dataset.backend = 'offline';
    chat.title = CHAT_OFFLINE;
    chat.append(el('span', { class: 'site-menu__tag', text: 'offline' }));
  });
  return menu;
}

/** Fills `host` with the header links of page `pageId` (a MENUS key). */
export function mountNav(host, pageId = host.dataset.siteNav) {
  const entries = (MENUS[pageId] || MENUS.results).map((e) => (typeof e === 'string' ? { id: e } : e));
  const links = entries.map((e) => {
    const page = PAGES[e.id];
    if (e.id === 'results') {
      return dropdown('results', e.label || page.label, [...RESULTS, { ...BETA, tag: 'exploratory' }], { dataKey: 'page', strong: e.strong });
    }
    if (e.id === 'playground') return playgroundMenu(e.label || page.label, e.strong);
    const cls = ['site-link', e.strong && 'site-link--strong', e.accent && 'site-link--accent'].filter(Boolean).join(' ');
    const a = el('a', { class: cls, href: siteHref(page.path), title: page.title, text: e.label || page.label });
    if (isCurrent(page.path)) {
      a.setAttribute('aria-current', 'page');
      a.classList.add('active');
    }
    return a;
  });
  host.classList.add('site-links');
  if (!host.hasAttribute('aria-label')) host.setAttribute('aria-label', 'Site');
  host.replaceChildren(
    ...links,
    dropdown('docs', 'Docs', DOCS, { dataKey: 'doc' }),
    externalLink('Paper', PAPER_URL, `Read the paper in the ACM Digital Library (DOI ${DOI})`),
    externalLink('Code', REPO_URL, 'The code on GitHub: github.com/dlamagna/agentraffic'),
    portalMenu(),
  );
}

// ---------------------------------------------------------------------------
// Footer, citation, filled links
// ---------------------------------------------------------------------------

/** Fills `host` with the paper footer: title, authors and venue, DOI, GitHub, cite. */
export function mountFooter(host) {
  const sep = () => el('span', { class: 'paper-footer__sep', 'aria-hidden': 'true', text: '·' });
  const box = el('div', { class: 'paper-footer' }, [
    el('p', { class: 'paper-footer__title' }, el('strong', { text: TITLE })),
    el('p', { class: 'paper-footer__meta', text: `${AUTHORS.map((a) => a.short).join(', ')} · ${VENUE_SHORT}, ${VENUE}` }),
    el('p', { class: 'paper-footer__links' }, [
      el('a', { href: DOI_URL, text: `DOI ${DOI}` }), sep(),
      el('a', { href: PAPER_URL, text: 'ACM Digital Library' }), sep(),
      el('a', { href: REPO_URL, text: 'Code on GitHub' }), sep(),
      el('a', { href: siteHref('docs/blog/#cite'), text: 'Cite' }), sep(),
      el('a', { href: siteHref('docs/blog/'), text: 'About the blog post' }),
    ]),
  ]);
  host.classList.add('site-footer-host');
  host.replaceChildren(box);
}

async function copyText(text, fallbackNode) {
  try {
    await navigator.clipboard.writeText(text);
    return 'copied';
  } catch (_) { /* no clipboard API (insecure context) or refused: select instead */ }
  const range = document.createRange();
  range.selectNodeContents(fallbackNode);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
  try {
    if (document.execCommand('copy')) return 'copied';
  } catch (_) { /* leave it selected */ }
  return 'selected';
}

/** Fills `host` with the BibTeX entry and a copy button. */
export function mountCite(host) {
  const code = el('code', { text: BIBTEX });
  const pre = el('pre', { class: 'cite-block__code', tabindex: '0', 'aria-label': 'BibTeX entry' }, code);
  const status = el('span', { class: 'cite-block__status', role: 'status' });
  const button = el('button', { type: 'button', class: 'cite-block__copy', text: 'Copy BibTeX' });
  let timer = 0;
  button.addEventListener('click', async () => {
    const result = await copyText(BIBTEX, code);
    status.textContent = result === 'copied' ? 'Copied to the clipboard' : 'Selected: press Ctrl+C (⌘C) to copy';
    button.textContent = result === 'copied' ? 'Copied' : 'Copy BibTeX';
    button.dataset.state = result;
    clearTimeout(timer);
    timer = setTimeout(() => {
      button.textContent = 'Copy BibTeX';
      delete button.dataset.state;
      status.textContent = '';
    }, 2500);
  });
  host.classList.add('cite-block');
  host.replaceChildren(
    el('div', { class: 'cite-block__bar' }, [el('span', { class: 'cite-block__label', text: 'BibTeX' }), status, button]),
    pre,
  );
}

const HREFS = {
  paper: () => PAPER_URL,
  doi: () => DOI_URL,
  repo: () => REPO_URL,
  cite: () => siteHref('docs/blog/#cite'),
  'agentverse-paper': () => AGENTVERSE.paperUrl,
  'agentverse-repo': () => AGENTVERSE.repoUrl,
};
const TEXTS = {
  doi: DOI,
  title: TITLE,
  venue: `${VENUE_SHORT} · ${VENUE}`,
  authors: AUTHORS.map((a) => a.name).join(', '),
};

/** Fills [data-site-href] / [data-site-text] (and [data-site-nav], footer, cite) under `root`. */
export function mountSite(root = document) {
  root.querySelectorAll('[data-site-nav]').forEach((host) => mountNav(host));
  root.querySelectorAll('[data-site-footer]').forEach(mountFooter);
  root.querySelectorAll('[data-site-cite]').forEach(mountCite);
  root.querySelectorAll('[data-site-href]').forEach((a) => {
    const key = a.dataset.siteHref;
    const href = key.startsWith('repo:') ? repoUrl(key.slice(5)) : HREFS[key]?.();
    if (href) a.href = href;
  });
  root.querySelectorAll('[data-site-text]').forEach((node) => {
    const text = TEXTS[node.dataset.siteText];
    if (text) node.textContent = text;
  });
}

/**
 * The Beta page is not part of the public build (`make dist-public` drops ui/results/beta/), so in public data mode it must not be linked. Done once here for every page:
 *   - the Beta entry of the Results ▾ menu is removed;
 *   - [data-beta-only] (a block that only makes sense with the Beta page, e.g. the System page's
 *     link line) is removed;
 *   - any other <a data-results-link="beta"> becomes plain text.
 * Private mode (the owner's machine) leaves everything as it is.
 */
export function applyBetaAvailability(root = document) {
  root.querySelectorAll('.results-menu__item[data-page="beta"]').forEach((a) => (a.closest('li') || a).remove());
  root.querySelectorAll('[data-beta-only]').forEach((n) => n.remove());
  root.querySelectorAll('a[data-results-link="beta"]').forEach((a) => {
    a.replaceWith(document.createTextNode(a.textContent));
  });
}

mountSite();
mountMode();
getDataMode()
  .then(({ mode }) => { if (mode === 'public') applyBetaAvailability(); })
  .catch(() => {});
