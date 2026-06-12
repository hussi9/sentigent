#!/bin/bash
# Sentigent PostToolUse Hook — records traces (never blocks)
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cat | python3 "$SCRIPT_DIR/sentigent_hook.py" post 2>/dev/null || echo '{"decision": "approve"}'
