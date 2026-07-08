# Regenerating `docs/assets/demo.gif`

`docs/demo.tape` is a [VHS](https://github.com/charmbracelet/vhs) script. Every
command it types is executed for real against a prepared demo directory —
nothing in the recording is scripted/faked output. In particular, `git commit`
and `pytest` are routed through the *real*
`claude-plugin/hooks/sentigent_hook.py` PreToolUse entry point (the same code
Claude Code calls on every tool call), so the "blocked" and "approved" commit
outcomes in the GIF are the engine's genuine decisions, not printed text.

## Prepare the demo environment (one time, or whenever re-recording)

```bash
# 1. Build the wheel from source
cd sentigent-public
rm -f dist/*.whl
.venv/bin/python -m build --wheel -o dist

# 2. Fresh venv + fresh HOME (never the real ~/.sentigent)
rm -rf /tmp/sentigent-demo-home /tmp/sentigent-demo-venv /tmp/sentigent-demo-repo
mkdir -p /tmp/sentigent-demo-home
python3 -m venv /tmp/sentigent-demo-venv
/tmp/sentigent-demo-venv/bin/pip install -q --upgrade pip
/tmp/sentigent-demo-venv/bin/pip install -q "$(pwd)/dist/sentigent-0.1.0-py3-none-any.whl[mcp]" pytest

# 3. A tiny git repo with a genuinely failing test (fixed live in the recording)
mkdir -p /tmp/sentigent-demo-repo/tests
cd /tmp/sentigent-demo-repo
git init -q && git config user.email demo@sentigent.xyz && git config user.name "Sentigent Demo"
cat > parser.py <<'EOF'
def parse_amount(s: str) -> float:
    """Parse a formatted number string like '1,234.56' into a float."""
    return float(s)
EOF
cat > tests/test_parser.py <<'EOF'
from parser import parse_amount

def test_parse_amount():
    assert parse_amount("1,234.56") == 1234.56
EOF
cat > pytest.ini <<'EOF'
[pytest]
pythonpath = .
EOF
printf '__pycache__/\n*.pyc\n.pytest_cache/\n' > .gitignore
git add -A && git commit -q -m "initial commit"
```

## The `git`/`pytest` -> real hook wiring

`/tmp/sentigent-demo-home/.bashrc` defines `git()` and `pytest()` shell
functions that pipe the exact command line to
`claude-plugin/hooks/sentigent_hook.py pre` as JSON on stdin — precisely the
payload shape Claude Code's PreToolUse hook sends. If the hook returns
`{"decision": "block", ...}`, the wrapper prints the real reason and returns
non-zero *without running the real command*. Otherwise it runs the real
binary. See that file for the full implementation.

VHS spawns `bash --norc --noprofile` for reproducibility, so the tape
explicitly (and honestly) `source`s that file at the start, hidden from the
recorded frames via `Hide`/`Show` (which only affects which frames are
captured, not what actually executes).

## Render

```bash
cd /tmp/sentigent-demo-repo
HOME=/tmp/sentigent-demo-home vhs /path/to/sentigent-public/docs/demo.tape
cp docs/assets/demo.gif /path/to/sentigent-public/docs/assets/demo.gif
```

(VHS writes relative to its own working directory, hence the `cd` into the
demo repo and the `cp` back into the real repo afterward.)

## Fallback if VHS is unavailable

If `brew install vhs` fails or is impractical, `asciinema` + `agg` can record
the same session and convert to GIF (`asciinema rec demo.cast`, then
`agg demo.cast docs/assets/demo.gif`). As a last resort, ship `docs/demo.tape`
alone and mark the GIF as pending in the README rather than fabricate one.
