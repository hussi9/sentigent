# launchd — Sentigent route-reconcile schedule

`com.sentigent.reconcile-routes.plist` runs the routing self-correction daily so
the embedding router keeps folding skill-router follow/ignore signal into
`routing_seeds.outcome` without manual runs. Cheap (no model load), idempotent.

## Install (macOS)

The plist ships with two placeholders — `__SENTIGENT_REPO__` (absolute path to
your clone) and `__HOME__` (your home directory) — substitute them before
loading:

```bash
sed -e "s#__SENTIGENT_REPO__#$(pwd)#g" -e "s#__HOME__#$HOME#g" \
  ops/launchd/com.sentigent.reconcile-routes.plist > /tmp/com.sentigent.reconcile-routes.plist
cp /tmp/com.sentigent.reconcile-routes.plist ~/Library/LaunchAgents/
launchctl load -w ~/Library/LaunchAgents/com.sentigent.reconcile-routes.plist
launchctl list | grep sentigent            # confirm registered
launchctl start com.sentigent.reconcile-routes   # run once now (optional)
tail ~/Library/Logs/sentigent-reconcile-routes.log
```

## Uninstall

```bash
launchctl unload -w ~/Library/LaunchAgents/com.sentigent.reconcile-routes.plist
mv ~/Library/LaunchAgents/com.sentigent.reconcile-routes.plist <your-repo>/.archive/
```

## Notes

- Paths are absolute (venv python + repo working dir). Re-run the `sed` step
  above if the repo moves.
- Manual equivalent: `.venv/bin/python -m sentigent.scripts.reconcile_routing_outcomes`
  (add `--dry-run` to preview, `--days N` to window).
- In-session equivalent: the `sentigent_reconcile_routes` MCP tool.
