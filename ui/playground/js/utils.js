/**
 * Utility Functions
 */

import { CONFIG } from './config.js';
import { getCustomEndpoint } from '../../common/js/backend.js';

/**
 * Escape HTML to prevent XSS
 */
export function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

/**
 * Truncate text to a maximum length
 */
export function truncate(text, maxLen = CONFIG.TRUNCATE_LENGTH) {
  if (!text || text.length <= maxLen) return text;
  return text.substring(0, maxLen) + '...';
}

/**
 * Get stage badge CSS class
 */
export function getStageBadgeClass(stage) {
  const map = {
    recruitment: 'flow-stage-recruitment',
    decision: 'flow-stage-decision',
    execution: 'flow-stage-execution',
    evaluation: 'flow-stage-evaluation',
    synthesis: 'flow-stage-synthesis'
  };
  return map[stage] || 'flow-stage-recruitment';
}

const STAGES = new Set(['recruitment', 'decision', 'execution', 'evaluation', 'synthesis']);

/**
 * Get stage color for graph edges: a CSS variable (css/styles.css, --stage-*), so SVG that
 * uses it recolours with the light / dark theme without a redraw.
 */
export function getStageColor(stage) {
  return `var(--stage-${STAGES.has(stage) ? stage : 'unknown'})`;
}

/**
 * Initialize endpoint URL based on current location
 */
export function getDefaultEndpoint() {
  const custom = getCustomEndpoint(); // Portal ▾ → Connect: the visitor's own backend
  if (custom) return custom;
  const protocol = window.location.protocol === 'file:' ? 'http:' : window.location.protocol;
  const host = window.location.hostname || 'localhost';
  return `${protocol}//${host}:8101/agentverse`;
}
