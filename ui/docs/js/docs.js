/**
 * ui/docs/js/docs.js
 * Docs pages: draws the topology diagrams into <svg data-topology-diagram="horizontal |
 * vertical | full_mesh"> and shows each talk's slides link only once its PDF exists.
 * Header, footer, citation and paper links come from ../../common/js/nav.js.
 */

const SVG_NS = 'http://www.w3.org/2000/svg';
let uid = 0;

function s(tag, attrs = {}, text) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (text != null) node.textContent = text;
  return node;
}

/** A line from node a to node b (centres, radius r), shortened so arrowheads sit on the rims. */
function edge(svg, [x1, y1], [x2, y2], r, { start = false, end = true, back = false, marker }) {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const len = Math.hypot(dx, dy);
  const ux = dx / len;
  const uy = dy / len;
  const pad = r + 3;
  const attrs = {
    class: `edge${back ? ' edge--back' : ''}`,
    x1: x1 + ux * pad, y1: y1 + uy * pad, x2: x2 - ux * pad, y2: y2 - uy * pad,
  };
  if (end) attrs['marker-end'] = `url(#${marker})`;
  if (start) attrs['marker-start'] = `url(#${marker})`;
  svg.append(s('line', attrs));
}

const DIAGRAMS = {
  horizontal: {
    title: 'Sequential: four agents speak one at a time in a fixed order; the round then starts again.',
    draw(svg, marker) {
      const r = 15;
      const nodes = [[30, 50], [86, 50], [142, 50], [198, 50]];
      for (let i = 0; i < 3; i++) edge(svg, nodes[i], nodes[i + 1], r, { marker });
      svg.append(s('path', { class: 'edge edge--back', d: 'M198 67 C 198 108, 30 108, 30 70', 'marker-end': `url(#${marker})` }));
      nodes.forEach(([cx, cy], i) => {
        svg.append(s('circle', { class: 'node', cx, cy, r }));
        svg.append(s('text', { x: cx, y: cy }, String(i + 1)));
      });
      svg.append(s('text', { class: 'note', x: 114, y: 112 }, 'next round'));
    },
  },
  vertical: {
    title: 'Star: a solver proposes, then three reviewers critique the proposal in parallel.',
    draw(svg, marker) {
      const r = 15;
      const hub = [52, 64];
      const leaves = [[176, 20], [176, 64], [176, 108]];
      for (const leaf of leaves) edge(svg, hub, leaf, r, { marker });
      svg.append(s('circle', { class: 'node node--hub', cx: hub[0], cy: hub[1], r: r + 2 }));
      svg.append(s('text', { class: 'node-label--hub', x: hub[0], y: hub[1] }, 'S'));
      leaves.forEach(([cx, cy]) => {
        svg.append(s('circle', { class: 'node', cx, cy, r }));
        svg.append(s('text', { x: cx, y: cy }, 'R'));
      });
    },
  },
  full_mesh: {
    title: 'Full mesh: every agent messages every other agent each round, 12 directed messages for four agents.',
    draw(svg, marker) {
      const r = 15;
      const nodes = [[64, 20], [164, 20], [164, 108], [64, 108]];
      for (let a = 0; a < 4; a++) {
        for (let b = a + 1; b < 4; b++) edge(svg, nodes[a], nodes[b], r, { marker, start: true });
      }
      nodes.forEach(([cx, cy], i) => {
        svg.append(s('circle', { class: 'node', cx, cy, r }));
        svg.append(s('text', { x: cx, y: cy }, String(i + 1)));
      });
    },
  },
};

export function drawTopology(svg) {
  const topo = svg.dataset.topologyDiagram;
  const spec = DIAGRAMS[topo];
  if (!spec) return;
  const marker = `topo-head-${topo}-${++uid}`;
  svg.setAttribute('viewBox', '0 0 228 128');
  svg.setAttribute('role', 'img');
  svg.classList.add('topo-diagram');
  const title = s('title', {}, spec.title);
  const defs = s('defs');
  const m = s('marker', {
    id: marker, viewBox: '0 0 10 10', refX: '8.5', refY: '5', markerWidth: '6', markerHeight: '6', orient: 'auto-start-reverse',
  });
  m.append(s('path', { class: 'head', d: 'M0,0 L10,5 L0,10 z' }));
  defs.append(m);
  svg.replaceChildren(title, defs);
  spec.draw(svg, marker);
}

/** <li data-slides="../slides/x.pdf">: link the PDF if the server has it, else say it is coming. */
async function checkSlides(item) {
  const link = item.querySelector('[data-slides-link]');
  const status = item.querySelector('[data-slides-status]');
  const src = item.dataset.slides;
  try {
    const res = await fetch(src, { method: 'HEAD', cache: 'no-store' });
    const type = res.headers.get('content-type') || '';
    if (res.ok && /pdf/i.test(type)) {
      const bytes = Number(res.headers.get('content-length'));
      link.href = src;
      link.hidden = false;
      status.textContent = bytes ? `PDF, ${(bytes / 1048576).toFixed(1)} MB` : 'PDF';
      item.dataset.state = 'available';
      return;
    }
  } catch (_) { /* offline or blocked: treat as not available */ }
  status.textContent = 'Slides to be added';
  item.dataset.state = 'missing';
}

document.querySelectorAll('svg[data-topology-diagram]').forEach(drawTopology);
document.querySelectorAll('[data-slides]').forEach(checkSlides);
