#!/bin/bash
# Sentigent PreToolUse Hook — safe evaluation via helper script
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cat | python3 "$SCRIPT_DIR/sentigent_hook.py" pre 2>/dev/null || echo '{"decision": "approve"}'
