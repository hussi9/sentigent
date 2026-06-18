"""metrics() accepts id-or-state, and drive() surfaces FAP on its return (leak fixes)."""
from __future__ import annotations

from sentigent.operator import loop_driver as L


def test_drive_returns_fap_and_metrics_accepts_id(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "LOOP_DIR", tmp_path / "loops")
    lid = L.start("demo", [{"text": "a", "verify": "true"},
                           {"text": "b", "verify": "true"}])["loop_id"]
    # dry-run still honors the per-step gate ("true" passes) → both steps verify → done
    res = L.drive(lid, execute=False)
    assert res["status"] == "done"
    # the leak fix: FAP is on the returned dict, not buried/derived
    assert res["FAP"] == 1.0
    assert res["metrics"]["FAP"] == 1.0
    # metrics() now accepts a loop_id string OR a state dict (was crash-on-str)
    assert L.metrics(lid)["FAP"] == 1.0
    assert L.metrics(res)["FAP"] == 1.0
    # the on-disk record must agree with the return — drive() now persists the
    # headline, so a later load() (and the dashboard) sees FAP, not None (3rd leak).
    reloaded = L.load(lid)
    assert reloaded["FAP"] == 1.0
    assert reloaded["metrics"]["FAP"] == 1.0


def test_failed_gate_lowers_fap(tmp_path, monkeypatch):
    monkeypatch.setattr(L, "LOOP_DIR", tmp_path / "loops")
    lid = L.start("demo", [{"text": "a", "verify": "true"},
                           {"text": "b", "verify": "false"}],  # gate fails → never verified
                  max_attempts=1)["loop_id"]
    res = L.drive(lid, execute=False)
    assert res["FAP"] == 0.5            # 1 of 2 verified — honest partial
    assert res["status"] != "done"
