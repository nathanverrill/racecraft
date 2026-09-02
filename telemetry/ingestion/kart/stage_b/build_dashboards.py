"""build_dashboards.py - Stage B: assemble the interactive dashboards per session.

Copies the HTML templates into each session's dataset/render/ directory (next to
render.json + session.wav so the relative fetches resolve), and prints how to view.

Run:  python kart/stage_b/build_dashboards.py [venue]
View: python -m http.server inside a session's render/ dir, or use serve.py.
"""
from __future__ import annotations
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUTPUT = REPO / "output"
TPL = Path(__file__).resolve().parent / "templates"

TEMPLATES = ["onboard.html", "coaching.html", "replay.html", "ghost.html",
             "cockpit.html", "sector1.html"]


def run(venue="gateway-kartplex"):
    vdir = OUTPUT / venue
    sessions = [p for p in vdir.iterdir()
                if p.is_dir() and not p.name.startswith("_") and p.name != "raw"]
    built = []
    for sdir in sorted(sessions):
        ds = sdir / "dataset"
        rdir = ds / "render"
        if not (rdir / "render.json").exists():
            continue
        for tpl in TEMPLATES:
            src = TPL / tpl
            if src.exists():
                shutil.copy(src, rdir / tpl)
        # copy data the dashboards fetch (must sit next to the HTML for http fetch)
        for extra in ["coaching.json", "analytics.json", "sectors.json"]:
            if (ds / extra).exists():
                shutil.copy(ds / extra, rdir / extra)
        built.append(rdir)
        print(f"[build_dashboards] {sdir.name}: dashboards -> {rdir}")
    print("-" * 64)
    print("[build_dashboards] To view, run a static server at the venue root, e.g.:")
    print(f"   ingestion/.venv/bin/python -m http.server 8800 -d {vdir}")
    for b in built:
        rel = b.relative_to(vdir)
        print(f"   http://localhost:8800/{rel}/onboard.html")
    return built


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "gateway-kartplex")
