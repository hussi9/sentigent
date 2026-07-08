# Sentigent demo — recorded for real against a prepared demo directory.
#
# Every command below genuinely executes and genuinely produces the output
# shown: a real `sentigent init` run, a real practice added and enforced,
# a `git commit` genuinely blocked by the real PreToolUse hook (wired up via
# ~/.bashrc in the demo HOME so `git`/`pytest` route through
# claude-plugin/hooks/sentigent_hook.py exactly as Claude Code does), a real
# failing pytest run, a real one-line fix, a real passing pytest run, and a
# real commit that the same hook then approves because the practice was
# satisfied this session.
#
# Render with:
#   HOME=/tmp/sentigent-demo-home vhs docs/demo.tape
# (from /tmp/sentigent-demo-repo as the working directory — see
# docs/demo-README.md for the full prepare-and-render recipe.)

Output docs/assets/demo.gif

Set Shell "bash"
Set FontSize 15
Set Width 1100
Set Height 620
Set Theme "Catppuccin Mocha"
Set Padding 20
Set TypingSpeed 45ms

# VHS spawns bash with --norc/--noprofile (no shell startup files loaded) for
# reproducibility, so the git/pytest -> real PreToolUse hook wiring has to be
# sourced explicitly. This still genuinely executes and defines the real
# functions in this live shell — Hide/Show only affects which frames are
# captured, not what runs.
Hide
Type "source /tmp/sentigent-demo-home/.bashrc" Enter
Sleep 300ms
Show

Type "sentigent init" Enter
Sleep 900ms
Enter
Sleep 500ms
Enter
Sleep 500ms
Enter
Sleep 500ms
Enter
Sleep 500ms
Enter
Sleep 1800ms

Type `sentigent practices add "Run the tests before committing"` Enter
Sleep 1200ms

Type "sentigent practices enforce 1 block" Enter
Sleep 1200ms

Type `git commit -m "wip"` Enter
Sleep 2200ms

Type "pytest -q" Enter
Sleep 1600ms

Type `sed -i '' "s/return float(s)/return float(s.replace(',', ''))/" parser.py` Enter
Sleep 700ms

Type "pytest -q" Enter
Sleep 1400ms

Type `git commit -am "feat: parser"` Enter
Sleep 1600ms

Type "sentigent score" Enter
Sleep 2200ms
