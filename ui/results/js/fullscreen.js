/**
 * "View full screen" for a chart: addFullscreen(figure, { title, draw }) puts a small button in the
 * figure's corner; it opens a modal <dialog> filling the viewport and calls draw(host, width, height)
 * to redraw the chart at that size (same drawing code, larger canvas). Esc or the close button
 * closes it, focus returns to the button, the page behind is inert (native modal) and does not
 * scroll. (The browser Fullscreen API is deliberately not used: Esc would exit it before closing the view.)
 *
 *   draw(host, width, height): render into host (replace its children)
 *   controls(container, redraw): optional, builds extra controls (e.g. a copy of an axis toggle)
 *   returns { refresh } : redraw the open view (call after shared state changed); no-op when closed
 */

import { h } from './util.js';
import { onThemeChange } from '../../common/js/theme.js';

const ICON = 'M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5'; // four corner brackets
let active = null; // the open view: { dialog, redraw }

const icon = () => {
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  p.setAttribute('d', ICON);
  svg.append(p);
  return svg;
};

function open(opener, { title, subtitle, draw, controls }) {
  const host = h('div', { class: 'fs-body' });
  const closeBtn = h('button', { type: 'button', class: 'fs-close', 'aria-label': `Close full screen view of ${title}`, title: 'Close (Esc)' }, ['Close ', h('span', { 'aria-hidden': 'true', text: '×' })]);
  const bar = h('div', { class: 'fs-controls' });
  const dialog = h('dialog', { class: 'fs-dialog', 'aria-label': `${title}, full screen` }, [
    h('div', { class: 'fs-head' }, [h('h2', { class: 'fs-title', text: title }), closeBtn]),
    subtitle ? h('p', { class: 'fs-sub', text: subtitle }) : null,
    bar,
    host,
  ]);
  document.body.append(dialog);

  let last = '';
  const redraw = (force = false) => {
    const w = Math.floor(host.clientWidth);
    const ht = Math.floor(host.clientHeight);
    if (w <= 0 || ht <= 0) return;
    if (!force && `${w}x${ht}` === last) return;
    last = `${w}x${ht}`;
    draw(host, w, ht);
  };
  if (controls) controls(bar, () => redraw(true));
  else bar.hidden = true;

  const tipEl = document.getElementById('tooltip'); // lives under <body>, i.e. beneath the top layer
  const tipHome = tipEl && tipEl.parentNode;
  if (tipEl) dialog.append(tipEl);
  let timer = null;
  const ro = new ResizeObserver(() => { clearTimeout(timer); timer = setTimeout(() => redraw(), 60); });
  const offTheme = onThemeChange(() => redraw(true));
  let closed = false;
  const finish = () => {
    if (closed) return;
    closed = true;
    clearTimeout(timer);
    ro.disconnect();
    if (typeof offTheme === 'function') offTheme();
    if (tipEl) { tipEl.hidden = true; tipHome.append(tipEl); }
    document.documentElement.classList.remove('fs-lock');
    dialog.remove();
    active = null;
    opener.focus();
  };
  dialog.addEventListener('close', finish);
  dialog.addEventListener('cancel', () => { /* Esc: native close, finish runs on 'close' */ });
  closeBtn.addEventListener('click', () => dialog.close());
  // a click on the backdrop (the dialog element itself, outside its padding box) closes too
  dialog.addEventListener('click', (ev) => { if (ev.target === dialog) dialog.close(); });

  document.documentElement.classList.add('fs-lock');
  dialog.showModal();
  closeBtn.focus();
  ro.observe(host);
  redraw(true);
  active = { dialog, redraw };
}

export function addFullscreen(figure, opts) {
  const label = `View ${opts.title} full screen`;
  const btn = h('button', { type: 'button', class: 'fs-btn', 'aria-label': label, title: label, 'aria-haspopup': 'dialog' });
  btn.append(icon());
  btn.addEventListener('click', () => open(btn, opts));
  figure.classList.add('has-fs');
  figure.append(btn);
  return { button: btn, refresh: () => { if (active) active.redraw(true); } };
}
