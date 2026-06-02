#!/usr/bin/env bash
# =============================================================================
# install_mcp.sh — Register the testbed queue as an MCP server
# =============================================================================
#
# Writes (or updates) the .mcp.json file at the project root so that
# Claude Code and compatible MCP clients discover the queue server.
#
# Usage:
#   ./scripts/queue/install_mcp.sh
#
# What it does:
#   1. Verifies that fastmcp is available in the .venv
#   2. Writes / merges the testbed-queue entry into .mcp.json
#   3. Prints a quick smoke-test command
#
# Re-running is idempotent: the entry is overwritten with the current paths.
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
MCP_JSON="$REPO_ROOT/.mcp.json"

PYTHON="${REPO_ROOT}/.venv/bin/python3"
if [[ ! -x "$PYTHON" ]]; then
    echo "ERROR: .venv/bin/python3 not found. Activate the venv first:"
    echo "  source .venv/bin/activate"
    exit 1
fi

# Verify fastmcp is installed
if ! "$PYTHON" -c "import fastmcp" 2>/dev/null; then
    echo "ERROR: fastmcp not installed. Run:"
    echo "  pip install fastmcp"
    exit 1
fi

echo "Installing testbed-queue MCP server into $MCP_JSON …"

# ---------------------------------------------------------------------------
# Build / merge .mcp.json using Python for safe JSON handling
# ---------------------------------------------------------------------------
"$PYTHON" - <<PYEOF
import json, os, sys
from pathlib import Path

repo_root = Path("$REPO_ROOT")
mcp_file  = Path("$MCP_JSON")
python    = "$PYTHON"

new_entry = {
    "type":    "stdio",
    "command": python,
    "args":    ["-m", "scripts.queue.server"],
    "cwd":     str(repo_root),
    "env": {
        "PYTHONPATH": str(repo_root),
        "VIRTUAL_ENV": str(repo_root / ".venv"),
    },
}

if mcp_file.exists():
    try:
        data = json.loads(mcp_file.read_text())
    except json.JSONDecodeError:
        data = {}
else:
    data = {}

data.setdefault("mcpServers", {})
existed = "testbed-queue" in data["mcpServers"]
data["mcpServers"]["testbed-queue"] = new_entry

mcp_file.write_text(json.dumps(data, indent=2) + "\n")

action = "Updated" if existed else "Added"
print(f"  {action} 'testbed-queue' in {mcp_file}")
PYEOF

echo ""
echo "Done. To verify the server starts correctly, run:"
echo "  $PYTHON -m scripts.queue.server"
echo ""
echo "To test with the MCP inspector:"
echo "  npx @modelcontextprotocol/inspector $PYTHON -m scripts.queue.server"
echo ""
echo "In Claude Code, reload the window (Ctrl+Shift+P → 'Reload Window') for"
echo "the new MCP server to be picked up."
