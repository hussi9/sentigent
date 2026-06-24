"""Operator dashboard — see the loop engine in real time.

A tiny, dependency-free local web view over the REAL on-disk state: every loop's
FAP, its DoD contract, token cost, what's pending (the scheduler's view), and any
project-map drift. Stdlib only (http.server) — no build step, nothing leaves the box.

    python -m sentigent.operator.dashboard          # serve on http://127.0.0.1:8787
    sentigent loop dashboard                          # (if wired in cli)

`state()` is the pure data layer (assembled from loop_driver / cost / scheduler /
project_map) and is what the tests exercise; the server is a thin shell around it.
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from . import loop_driver

# fail-soft optional imports — the dashboard still renders if a module is absent
try:
    from . import cost as _cost
except Exception:  # pragma: no cover
    _cost = None
try:
    from . import scheduler as _scheduler
except Exception:  # pragma: no cover
    _scheduler = None
try:
    from . import project_map as _project_map
except Exception:  # pragma: no cover
    _project_map = None


def _safe(fn, default):
    try:
        return fn()
    except Exception:
        return default


def state(loop_dir: Any = None, cost_dir: Any = None, root: str = ".") -> dict:
    """Assemble the whole picture from real on-disk state. Never raises."""
    # ── loops + aggregate FAP (the receipt is the scoreboard) ──
    rec = _safe(lambda: loop_driver.receipt(loop_dir), {}) or {}
    rows = rec.get("rows", []) if isinstance(rec, dict) else []
    loops = []
    for r in rows:
        lid = r.get("loop_id")
        entry = {
            "loop_id": lid,
            "goal": r.get("goal", ""),
            "fap": r.get("FAP", r.get("fap", 0)),
            "plan_distance": r.get("plan_distance", 0),
            "asks": r.get("asks", 0),
        }
        # the per-loop DoD contract (criteria checklist) if available
        if lid:
            c = _safe(lambda: loop_driver.contract(lid), None)
            if isinstance(c, dict):
                entry["criteria"] = c.get("criteria", [])
                entry["all_passed"] = c.get("all_passed", False)
        loops.append(entry)

    aggregate = {
        "loops": rec.get("loops", len(loops)) if isinstance(rec, dict) else len(loops),
        "completed": rec.get("completed", 0) if isinstance(rec, dict) else 0,
        "mean_fap": rec.get("mean_FAP", rec.get("mean_fap", 0)) if isinstance(rec, dict) else 0,
    }

    # ── pending work (the scheduler's view) ──
    pending = []
    if _scheduler is not None:
        pending = _safe(lambda: _scheduler.pending_loops(loop_dir), []) or []

    # ── token cost ──
    cost = {"total_usd": 0, "by_model": {}, "events": 0}
    if _cost is not None:
        cost = _safe(lambda: _cost.summary(None, cost_dir), cost) or cost
    aggregate["cost_usd"] = cost.get("total_usd", 0)

    # ── project map: what's where + drift ──
    pmap = {"areas": [], "drift": []}
    if _project_map is not None:
        pmap["areas"] = _safe(lambda: _project_map.areas(root), []) or []
        pmap["drift"] = _safe(lambda: _project_map.validate(root), []) or []

    return {"aggregate": aggregate, "loops": loops, "pending": pending,
            "cost": cost, "project_map": pmap}


# ─────────────────────────────── the page ───────────────────────────────

_PAGE = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>Sentigent · operator</title>
<link rel=preconnect href=https://fonts.googleapis.com><link rel=preconnect href=https://fonts.gstatic.com crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Figtree:wght@400;500;600;700;800&display=swap" rel=stylesheet>
<style>
:root{--bg:#0E0E0E;--panel:#161616;--bd:#2a2a2a;--tx:#fff;--mut:#9aa3ad;--faint:#6b7178;--ac:#00cc5f;--ac2:#00FF77;--am:#ffcf6b;
--mono:ui-monospace,"SF Mono",monospace;--sans:Figtree,-apple-system,system-ui,sans-serif}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);font-family:var(--sans);font-size:15px}
.wrap{max-width:1100px;margin:0 auto;padding:22px}
header{display:flex;align-items:center;gap:12px;border-bottom:1px solid var(--bd);padding-bottom:16px;margin-bottom:20px}
.dot{width:11px;height:11px;border-radius:50%;background:var(--ac);box-shadow:0 0 12px var(--ac)}
.brand{font-weight:800;letter-spacing:-.02em}.brand small{color:var(--faint);font-weight:500;margin-left:6px}
.live{margin-left:auto;font-family:var(--mono);font-size:12px;color:var(--faint)}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:22px}
.kpi{border:1px solid var(--bd);border-radius:13px;background:var(--panel);padding:16px}
.kpi .v{font-size:26px;font-weight:800}.kpi .l{font-family:var(--mono);font-size:11px;letter-spacing:.1em;text-transform:uppercase;color:var(--faint);margin-top:4px}
.kpi .v.ac{color:var(--ac)}
h2{font-size:13px;font-family:var(--mono);letter-spacing:.12em;text-transform:uppercase;color:var(--ac2);margin:26px 0 12px}
.loop{border:1px solid var(--bd);border-radius:13px;background:var(--panel);padding:16px;margin-bottom:12px}
.loop .top{display:flex;align-items:center;gap:12px;cursor:pointer}
.loop .goal{font-weight:650}.loop .id{font-family:var(--mono);font-size:11px;color:var(--faint)}
.bar{flex:1;height:8px;border-radius:99px;background:#0a0a0a;overflow:hidden;min-width:80px;max-width:260px}
.bar i{display:block;height:100%;background:linear-gradient(90deg,var(--ac),var(--ac2))}
.fap{font-family:var(--mono);font-weight:700;color:var(--ac);min-width:48px;text-align:right}
.crit{margin:12px 0 0;padding:12px 0 0;border-top:1px solid var(--bd);display:none;font-family:var(--mono);font-size:13px;line-height:1.8}
.loop.open .crit{display:block}
.crit .ok{color:var(--ac)}.crit .no{color:#ff6b6b}.crit .pend{color:var(--faint)}.crit .vc{color:var(--faint)}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.card{border:1px solid var(--bd);border-radius:13px;background:var(--panel);padding:16px}
.card ul{margin:8px 0 0;padding:0;list-style:none;font-size:14px;color:var(--mut)}
.card li{padding:5px 0;display:flex;gap:8px;font-family:var(--mono);font-size:12.5px}
.tag{font-family:var(--mono);font-size:10px;padding:1px 7px;border-radius:99px}
.tag.live{background:rgba(0,204,95,.13);color:var(--ac)}.tag.build{background:rgba(255,207,107,.12);color:var(--am)}
.empty{color:var(--faint);font-size:13px}
.drift{color:var(--am)}
@media(max-width:760px){.kpis{grid-template-columns:repeat(2,1fr)}.cols{grid-template-columns:1fr}}
</style></head><body><div class=wrap>
<header><span class=dot></span><span class=brand>Sentigent <small>operator · loop engine, live</small></span><span class=live id=live>loading…</span></header>
<div class=kpis id=kpis></div>
<h2>Loops</h2><div id=loops></div>
<div class=cols>
  <div><h2>Pending · scheduler</h2><div class=card id=pending></div></div>
  <div><h2>Token cost</h2><div class=card id=cost></div></div>
</div>
<h2>Project map · what's where</h2><div class=card id=pmap></div>
</div>
<script>
const e=(h)=>{const d=document.createElement('div');d.innerHTML=h;return d.firstChild};
const pct=(x)=>Math.round((x||0)*100);
async function tick(){
  let s; try{s=await (await fetch('/api/state',{cache:'no-store'})).json()}catch(_){document.getElementById('live').textContent='offline';return}
  const a=s.aggregate||{};
  document.getElementById('kpis').innerHTML=
   `<div class=kpi><div class="v ac">${pct(a.mean_fap)}%</div><div class=l>mean FAP</div></div>`+
   `<div class=kpi><div class=v>${a.loops||0}</div><div class=l>loops</div></div>`+
   `<div class=kpi><div class=v>${a.completed||0}</div><div class=l>completed</div></div>`+
   `<div class=kpi><div class=v>$${(a.cost_usd||0).toFixed(2)}</div><div class=l>token cost</div></div>`;
  const lc=document.getElementById('loops');lc.innerHTML='';
  if(!(s.loops||[]).length) lc.innerHTML='<div class=empty>No loops yet. Start one: <code>sentigent loop start …</code></div>';
  (s.loops||[]).forEach(l=>{
    const crit=(l.criteria||[]).map(c=>{const m=c.mark==='✅'?'ok':c.mark==='❌'?'no':'pend';
      return `<div><span class=${m}>${c.mark||'○'}</span> ${c.text||''} <span class=vc>${c.verify?('— '+c.verify):''}</span></div>`}).join('')||'<span class=empty>no criteria</span>';
    const el=e(`<div class=loop><div class=top><span class=goal>${l.goal||'(no goal)'}</span><span class=id>${l.loop_id||''}</span><span class=bar><i style="width:${pct(l.fap)}%"></i></span><span class=fap>FAP ${pct(l.fap)}%</span></div><div class=crit>${crit}</div></div>`);
    el.querySelector('.top').onclick=()=>el.classList.toggle('open');lc.appendChild(el)});
  const p=s.pending||[];
  document.getElementById('pending').innerHTML=p.length?('<ul>'+p.map(x=>`<li>↻ ${x}</li>`).join('')+'</ul>'):'<div class=empty>Nothing pending — all loops are done or idle.</div>';
  const c=s.cost||{};const bm=Object.entries(c.by_model||{});
  document.getElementById('cost').innerHTML=`<div style="font-size:22px;font-weight:800">$${(c.total_usd||0).toFixed(4)}</div><div class=empty>${c.events||0} events · ${(c.in_tokens||0)+(c.out_tokens||0)} tokens</div>`+(bm.length?('<ul>'+bm.map(([m,v])=>`<li>${m} <span style="margin-left:auto">$${(+v).toFixed(4)}</span></li>`).join('')+'</ul>'):'');
  const pm=s.project_map||{};const areas=pm.areas||[],drift=pm.drift||[];
  document.getElementById('pmap').innerHTML=
    (drift.length?`<div class=drift>⚠ ${drift.length} drift: `+drift.map(d=>`${d.kind} (${d.detail})`).join(' · ')+'</div>':'<div style="color:var(--ac)">✓ no drift</div>')+
    '<ul style="margin-top:10px">'+areas.map(x=>`<li>${x.path} <span style="color:var(--faint)">${x.purpose||''}</span> <span class="tag ${x.status==='building'?'build':'live'}" style="margin-left:auto">${x.status||'live'}</span></li>`).join('')+'</ul>';
  const t=new Date().toLocaleTimeString();document.getElementById('live').textContent='live · '+t;
}
tick();setInterval(tick,3000);
</script></body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/api/state"):
            self._send(200, json.dumps(state()).encode(), "application/json")
        elif self.path in ("/", "/index.html"):
            self._send(200, _PAGE.encode(), "text/html; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain")

    def log_message(self, *a):  # quiet
        pass


def serve(host: str = "127.0.0.1", port: int = 8787) -> None:
    srv = ThreadingHTTPServer((host, port), _Handler)
    print(f"Sentigent operator dashboard → http://{host}:{port}  (ctrl-c to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        srv.shutdown()


def main() -> None:
    serve(port=int(os.environ.get("SENTIGENT_DASHBOARD_PORT", "8787")))


if __name__ == "__main__":
    main()
