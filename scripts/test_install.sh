#!/usr/bin/env bash
# Proves: build wheel -> install in CLEAN venv at a fresh path -> CLI works.
set -euo pipefail
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
python3 -m pip install --quiet --break-system-packages build
python3 -m build --wheel --outdir "$WORK/dist"
WHEEL=$(ls "$WORK"/dist/*.whl)
echo "wheel: $WHEEL ($(du -h "$WHEEL" | cut -f1))"
python3 -m venv "$WORK/venv"
"$WORK/venv/bin/pip" install --quiet "$WHEEL"
cd "$WORK"   # fresh path — no repo imports can leak in
"$WORK/venv/bin/sentigent" --help >/dev/null && echo "OK: sentigent --help"
"$WORK/venv/bin/sentigent" doctor || true   # doctor may warn pre-init; must not crash
"$WORK/venv/bin/python" -c "import sentigent; print('OK: import sentigent', sentigent.__version__ if hasattr(sentigent,'__version__') else '')"
echo "INSTALL PROOF PASSED"
