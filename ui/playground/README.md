# AgentVerse UI

A modern, modular web interface for the AgentVerse multi-agent collaboration system.

> **Part of the AgenTraffic UI suite.**
> The top-level launcher at `ui/index.html` also links to:
> - **Results** (`ui/results/`): the paper's traffic findings, with Traffic patterns, System load and Run explorer pages
> - **Docs** (`ui/docs/`): the blog post on the paper and the AgentVerse workflow explained
> - **Chat with Agent A** (`ui/playground/chat/`): ad-hoc Agent A chat interface for manual testing
>
> Serve `ui/` with `make local` (http://localhost:8080/, real data if you have it) or `make public`
> (the public-only build on http://localhost:8081/). All paths are relative, so the same tree also
> works under a sub-path such as GitHub Pages.

## Features

- **Live Streaming Updates**: Real-time progress updates via Server-Sent Events (SSE)
- **Stage Visualization**: Visual workflow with 4 main stages
- **LLM Request Tracking**: Detailed view of all LLM requests and responses
- **Iteration History**: Track multiple iterations with scoring
- **Graph & Table Views**: Visualize agent communication flow

## Project Structure

```
ui/playground/
├── run/index.html          # Run a workflow: live runner UI (URL playground/run/)
├── open/index.html         # Open a saved run: offline/local response.json viewer (URL playground/open/)
├── chat/index.html         # Chat with Agent A (URL playground/chat/)
├── css/
│   └── styles.css          # All CSS styles
├── js/
│   ├── app.js              # Main application entry point
│   ├── config.js           # Configuration and constants
│   ├── utils.js            # Utility functions
│   ├── renderers.js        # HTML rendering functions
│   ├── ui-state.js         # UI state management
│   ├── streaming.js        # SSE streaming handler
│   ├── mock-backend.js     # Demo mode: answers the Agent A API from <data base>/fixtures/ (ui/data/{private,public}/, chosen by ../../common/js/data.js)
│   └── viewer.js           # response.json file/URL viewer logic
└── README.md               # This file
```

### Demo data

The replay data lives in `ui/data/` and is chosen by `ui/common/js/data.js` (`?data=public|private`,
then the saved choice, then `private` if `ui/data/private/manifest.json` loads, else `public`):

- `ui/data/private/` (gitignored): the real recorded runs and fixtures (`fixtures/`), built by
  `make data` (`scripts/demo/generate_fixtures.py`, `scripts/demo/export_results.py`).
- `ui/data/public/` (committed): real aggregates plus synthetic runs and fixtures.

`make local` serves `ui/` on :8080, `make public` builds and serves the public-only tree.

The old URLs `ui/agentverse/`, `ui/agentverse/viewer.html`, `ui/agentverse/viewer/` and `ui/chat/`
are redirect stubs to these pages that keep the query and hash.

## File Descriptions

### HTML Files

- **`run/index.html`**: The runner page. It loads the shared theme and header from `../../common/` and the modules in `../js/` (entry point `js/app.js`) with relative URLs.
- **`open/index.html`**: The run viewer (see "Run Viewer" below).
- **`chat/index.html`**: The Agent A chat page.

### CSS

- **`css/styles.css`**: All visual styles including layout, components, animations, and responsive design.

### JavaScript Modules

- **`js/app.js`**: Main application class that initializes the UI, binds event listeners, and coordinates other modules.

- **`js/config.js`**: Constants and configuration including:
  - Default settings
  - Example tasks
  - Timeouts and limits

- **`js/utils.js`**: Utility functions including:
  - HTML escaping
  - Text truncation
  - Color/badge mapping
  - Default endpoint generation

- **`js/renderers.js`**: Pure functions for rendering UI components:
  - Expert cards
  - Discussion rounds (horizontal/vertical)
  - Execution results
  - Evaluation metrics
  - LLM request table and graph
  - Iteration history

- **`js/ui-state.js`**: UIState class that manages:
  - UI element references
  - Timer functionality
  - Stage updates
  - Progress tracking
  - Reset/initialization

- **`js/streaming.js`**: StreamingHandler class that handles:
  - SSE connection and parsing
  - Real-time event processing
  - Error handling and fallback to non-streaming
  - Progress updates

## Live Streaming Features

The UI supports Server-Sent Events (SSE) for real-time updates:

### Event Types

- `iteration_start`: New iteration beginning
- `stage_start`: Stage starting (recruitment, decision, execution, evaluation, synthesis)
- `stage_complete`: Stage completed with results
- `llm_request`: Individual LLM request/response logged
- `discussion_round`: Discussion round completed (horizontal mode)
- `vertical_iteration`: Solver/reviewer iteration (vertical mode)
- `execution_result`: Individual agent execution completed
- `complete`: Workflow finished
- `error`: Error occurred

### Visual Indicators

- **LIVE badge**: Pulsing red badge when streaming is active
- **LLM Request Counter**: Shows number of LLM requests in real-time
- **Stage Progress**: Stages update from Pending → Running → Complete
- **Auto-expansion**: Relevant stages automatically expand as they complete
- **Progress Bar**: Smooth progress indication based on current stage

### Fallback Behavior

If streaming is not supported or fails:
1. Attempt streaming first
2. If streaming fails, automatically retry with non-streaming mode
3. Display clear error messages if both modes fail

## Usage

### Development

Edit the files under `js/` and `css/` and reload; there is no build step. Serve `ui/` with
`make local` (it sends no-store caching headers, so a plain reload picks up your changes).

### Run Viewer (load saved response.json)

`open/index.html` lets you inspect already-completed runs in the browser with:
- stage cards
- detailed flow graph/table
- full request/response expansion
- iteration history

Recommended startup (from the repo root):

```bash
make local
```

Then open:

```text
http://localhost:8080/playground/open/
```

You can load data in two ways:

1. **Drag & drop** a `response.json` file into the viewer.
2. **Direct URL query param**:

```text
http://localhost:8080/playground/open/?json=/data/runs/<run_dir>/response.json
```

3. **Load by persisted task ID (fixed backend endpoint)**:

```text
http://localhost:8080/playground/open/?task_id=<task_id>
```

Optional custom backend endpoint:

```text
http://localhost:8080/playground/open/?task_id=<task_id>&endpoint=http://localhost:8101/agentverse
```

Notes:
- The `json` path is fetched by the browser, so serve a root that contains the file (the path is resolved by the browser against the page's server).
- `task_id` mode calls `GET <endpoint>/<task_id>` (defaults to `http://<current-host>:8101/agentverse/<task_id>`).
- Opening `open/index.html` directly via `file://` may block module loading in some browsers; prefer a local HTTP server.

## API Integration

The UI communicates with Agent A's `/agentverse` endpoint:

### Request Format

```json
{
  "task": "Your task description",
  "max_iterations": 3,
  "stream": true
}
```

### Non-Streaming Response

```json
{
  "task_id": "...",
  "completed": true,
  "iterations": 1,
  "final_output": "...",
  "stages": { ... },
  "iteration_history": [...],
  "llm_requests": [...]
}
```

### Streaming Events

```
event: stage_start
data: {"stage": "recruitment", "stage_number": 1, "message": "..."}

event: llm_request
data: {"seq": 1, "prompt": "...", "response": "..."}

event: complete
data: {...full response...}
```

## Browser Compatibility

- **Streaming**: Requires modern browser with Fetch API and ReadableStream support
- **Fallback**: Automatically falls back to non-streaming for older browsers
- **Tested**: Chrome 90+, Firefox 88+, Safari 14+, Edge 90+

## Customization

### Adding New Event Types

1. Add handler in `js/streaming.js` → `handleStreamEvent()`
2. Emit event in backend `orchestrator.py` → `_send_progress()`
3. Add visual feedback in `js/ui-state.js` or `js/renderers.js`

### Styling

All styles are in `css/styles.css`, on top of the shared light / dark theme tokens in
`../common/css/theme.css`. Each theme sets its own role variables: light (the default) in
`:root`, dark in `:root[data-theme="dark"]`:

```css
:root {
  --primary: var(--accent);       /* navy on light */
  --agent-1: #256abf;             /* topology diagram agent colours */
  --stage-recruitment: #256abf;   /* flow-graph stage colours */
  /* ... */
}
:root[data-theme="dark"] {
  --primary: #2563eb;
  /* ... */
}
```

The header toggle (Light / Dark, default light, from `../common/js/theme.js`) stores the choice in
`localStorage['agentraffic-theme']`; an inline script in each page's `<head>` applies it as
`<html data-theme>` before first paint. SVG drawn in JS paints with these variables
(`stroke="var(--stage-decision)"`, `fill: var(--agent)`), so it recolours with the theme without a redraw.

## Performance

- Minimal overhead per SSE event (~50-200 bytes)
- Events only sent at significant milestones
- Efficient incremental DOM updates
- No polling - server pushes updates

## Troubleshooting

### No response when clicking "Run"

1. Check browser console for errors
2. Verify Agent A endpoint is correct
3. Ensure agent-a service is running
4. Check CORS headers if accessing from different origin

### Streaming not working

1. Check if `stream: true` is sent in request
2. Verify browser supports ReadableStream
3. Check backend logs for SSE errors
4. UI will automatically fall back to non-streaming

### Elements not updating

1. Hard refresh browser (Ctrl+Shift+R)
2. Clear browser cache
3. Check console for JavaScript errors
4. Verify HTML elements have correct IDs
