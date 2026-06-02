/**
 * ui/common/js/nav.js
 * -------------------
 * Benchmark registry for navigation.
 * Add a new benchmark here when its ui/<name>/ directory is created.
 *
 * Usage (ES module):
 *   <script type="module">
 *     import { renderNav } from '../common/js/nav.js';
 *     renderNav('#benchmark-nav', import.meta.url);
 *   </script>
 *
 * The element matching the selector will be populated with .benchmark-nav
 * links. The current benchmark is highlighted as .active based on the URL.
 */

export const BENCHMARKS = [
  { name: 'AgentVerse', path: '../agentverse/',  description: '4-stage multi-agent orchestration' },
  { name: 'MARBLE',     path: '../marble/',       description: 'Multi-agent topology benchmark' },
  { name: 'Chat',       path: '../chat/',         description: 'Direct agent chat interface' },
];

/**
 * Renders benchmark navigation links into `selector`.
 * `callerUrl` should be `import.meta.url` so the active link can be detected.
 *
 * @param {string} selector  CSS selector for the container element
 * @param {string} callerUrl import.meta.url of the calling page
 */
export function renderNav(selector, callerUrl) {
  const container = document.querySelector(selector);
  if (!container) return;

  const nav = document.createElement('nav');
  nav.className = 'benchmark-nav';

  for (const bm of BENCHMARKS) {
    const a = document.createElement('a');
    a.href = bm.path;
    a.textContent = bm.name;
    a.title = bm.description;
    // Mark active if the caller's URL contains the benchmark path segment.
    if (callerUrl && callerUrl.includes('/' + bm.path.replace('../', ''))) {
      a.classList.add('active');
    }
    nav.appendChild(a);
  }

  // Home link
  const home = document.createElement('a');
  home.href = '../';
  home.textContent = '← Home';
  nav.appendChild(home);

  container.replaceChildren(nav);
}
