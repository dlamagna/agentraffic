/**
 * ui/common/js/site.js
 * --------------------
 * The paper and code base, in one place. Every page takes the paper / DOI / GitHub links and
 * the citation from here (header links, footer, citation block, results page, docs pages), so
 * a change of URL is made once. No side effects: safe to import from anywhere.
 */

export const TITLE = 'Towards Traffic Modelling of Multi-Agent Systems: The Role of Coordination Topology';

export const AUTHORS = [
  { name: 'Davide Lamagna', short: 'Lamagna', affiliation: 'UPC, BarcelonaTech' },
  { name: 'Albert Cabellos', short: 'Cabellos', affiliation: 'UPC, BarcelonaTech' },
  { name: 'Alberto Rodriguez-Natal', short: 'Rodriguez-Natal', affiliation: 'Cisco Research' },
  { name: 'Gábor Rétvári', short: 'Rétvári', affiliation: 'Budapest University of Technology and Economics' },
  { name: 'Berta Serracanta', short: 'Serracanta', affiliation: 'UPC, BarcelonaTech' },
];

export const VENUE = '3rd ACM SIGCOMM Workshop on Networks for AI Computing';
export const VENUE_SHORT = 'NAIC 2026';
export const YEAR = 2026;

export const DOI = '10.1145/3789240.3828749';
export const DOI_URL = `https://doi.org/${DOI}`;
/** The paper's landing page in the ACM Digital Library. */
export const PAPER_URL = `https://dl.acm.org/doi/${DOI}`;

export const REPO_URL = 'https://github.com/dlamagna/agentraffic';

/** The login-protected copy of the site with the real per-run data (research group only). */
export const SIGN_IN_URL = 'https://agentraffic-private.pages.dev';
export const REPO_BRANCH = 'main';

/** A file or directory in the code base on GitHub, e.g. repoUrl('scripts/experiment/'). */
export function repoUrl(path = '') {
  if (!path) return REPO_URL;
  const kind = path.endsWith('/') ? 'tree' : 'blob';
  return `${REPO_URL}/${kind}/${REPO_BRANCH}/${path.replace(/\/$/, '')}`;
}

/** The original AgentVerse framework (Chen et al.) that the workflow is based on. */
export const AGENTVERSE = {
  title: 'AgentVerse: Facilitating Multi-Agent Collaboration and Exploring Emergent Behaviors',
  authors: 'Chen et al.',
  arxiv: '2308.10848',
  paperUrl: 'https://arxiv.org/abs/2308.10848',
  repoUrl: 'https://github.com/OpenBMB/AgentVerse',
};

export const BIBTEX = String.raw`@inproceedings{lamagna2026agentraffic,
  title     = {Towards Traffic Modelling of Multi-Agent Systems: The Role of Coordination Topology},
  author    = {Lamagna, Davide and Cabellos, Albert and Rodriguez-Natal, Alberto and R{\'e}tv{\'a}ri, G{\'a}bor and Serracanta, Berta},
  booktitle = {3rd ACM SIGCOMM Workshop on Networks for AI Computing (NAIC)},
  year      = {2026},
  publisher = {ACM},
  doi       = {10.1145/3789240.3828749},
  url       = {https://doi.org/10.1145/3789240.3828749}
}`;

/** "Davide Lamagna, Albert Cabellos, ..." */
export const AUTHOR_LIST = AUTHORS.map((a) => a.name).join(', ');
