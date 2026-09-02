"""build_home.py - Stage B: generate the sessions HOME PAGE.

Scans output/<venue>/ for every timing sheet (from raw/timesheets.json) and, where a
session has telemetry, its analytics.json + render dashboards. Emits:
  - output/index.html          home page: cards grouped by venue -> session
  - <session>/dataset/render/landing.html   per-session dashboard hub (telemetry only)

Each card headlines, in order: CONSISTENCY (lap-time CV %) -> BEST lap -> AVG lap.
Consistency uses telemetry clean-lap CV when available, else the sheet-derived CV so
EVERY session (even timing-only, no telemetry) shows a consistency number.

Static HTML/JS, no deps. Serve with:  python -m http.server 8800 -d output
Run:  python kart/stage_b/build_home.py
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUTPUT = REPO / "output"

DASHBOARDS = [("onboard", "Onboard"), ("coaching", "Coaching"), ("replay", "Replay"),
              ("ghost", "Ghost"), ("cockpit", "Cockpit"), ("sector1", "Sector 1")]


def load_json(p):
    with open(p) as f:
        return json.load(f)


def fmt_time(t):
    return f"{t:.3f}s" if isinstance(t, (int, float)) else "-"


def collect_sessions(vdir: Path):
    """Return list of session dicts for a venue (telemetry + timing-only)."""
    ts_path = vdir / "raw" / "timesheets.json"
    if not ts_path.exists():
        return []
    sheets = load_json(ts_path)["sheets"]
    sessions = []
    for sh in sheets:
        key = sh["session_key"]
        ds = vdir / key / "dataset"
        has_tel = (ds / "analytics.json").exists()
        # consistency: prefer telemetry clean-lap CV, else sheet CV
        cv = sh.get("consistency", {}).get("cv")
        clean_n = sh.get("consistency", {}).get("n")
        cv_src = "sheet"
        analytics = None
        if has_tel:
            analytics = load_json(ds / "analytics.json")
            lc = analytics.get("lap_clean", {})
            if lc.get("cv") is not None:
                cv, clean_n, cv_src = lc["cv"], lc.get("n"), "telemetry (clean laps)"
        # available dashboards
        rdir = ds / "render"
        dash = [(slug, label) for slug, label in DASHBOARDS
                if (rdir / f"{slug}.html").exists()]
        videos = sorted((vdir / key / "video").glob("*.mp4")) if (vdir / key / "video").exists() else []
        sessions.append({
            "key": key, "event": sh.get("event"), "type": sh.get("session_type"),
            "datetime": sh.get("datetime_local"), "config": sh.get("configuration"),
            "driver": sh.get("driver"), "position": sh.get("position"),
            "field_size": sh.get("field_size"),
            "laps": len(sh.get("lap_times", [])),
            "best": sh.get("best_lap"), "avg": sh.get("avg_lap"),
            "ranking_metric": sh.get("ranking_metric", "best"),
            "cv": cv, "cv_n": clean_n, "cv_src": cv_src,
            "telemetry": has_tel, "dashboards": dash,
            "videos": [v.name for v in videos],
            "render_rel": f"{key}/dataset/render" if has_tel else None,
        })
    sessions.sort(key=lambda s: s["datetime"] or "")
    return sessions


def session_card(venue, s):
    cv_pct = f"{s['cv']*100:.1f}%" if s["cv"] is not None else "-"
    rank = s["ranking_metric"]
    best_lead = "lead" if rank == "best" else ""
    avg_lead = "lead" if rank == "average" else ""
    pos = (f"P{s['position']}" + (f"/{s['field_size']}" if s['field_size'] else "")
           if s.get("position") else "")
    when = (s["datetime"] or "").replace("T", " ")
    cfg = f" · {s['config']}" if s.get("config") else ""

    links = ""
    if s["telemetry"]:
        btns = " ".join(
            f'<a class="btn" href="{venue}/{s["render_rel"]}/{slug}.html">{label}</a>'
            for slug, label in s["dashboards"])
        hub = f'<a class="btn hub" href="{venue}/{s["render_rel"]}/landing.html">Open ▸</a>'
        links = f'<div class="links">{hub}{btns}</div>'
    else:
        links = '<div class="links"><span class="tag timing">Timing only — no telemetry</span></div>'

    return f"""
    <div class="card {'tel' if s['telemetry'] else 'notel'}">
      <div class="chead">
        <div class="event">{s['event'] or s['key']}</div>
        <div class="when">{when}{cfg}{('  ·  '+pos) if pos else ''}</div>
      </div>
      <div class="metrics">
        <div class="metric primary"><div class="mlabel">Consistency (CV)</div>
          <div class="mval">{cv_pct}</div>
          <div class="msub">{s['cv_src']}{(' · '+str(s['cv_n'])+' laps') if s['cv_n'] else ''}</div></div>
        <div class="metric {best_lead}"><div class="mlabel">Best lap</div>
          <div class="mval">{fmt_time(s['best'])}</div></div>
        <div class="metric {avg_lead}"><div class="mlabel">Avg lap</div>
          <div class="mval">{fmt_time(s['avg'])}</div>
          <div class="msub">{'ranking metric' if rank=='average' else ''}</div></div>
        <div class="metric"><div class="mlabel">Laps</div>
          <div class="mval">{s['laps']}</div></div>
      </div>
      {links}
    </div>"""


def venue_title(v):
    return v.replace("-", " ").title().replace("Kartplex", "Kartplex")


def build_home():
    venues = [p for p in sorted(OUTPUT.iterdir())
              if p.is_dir() and (p / "raw" / "timesheets.json").exists()]
    sections = []
    for vdir in venues:
        v = vdir.name
        sessions = collect_sessions(vdir)
        if not sessions:
            continue
        cards = "\n".join(session_card(v, s) for s in sessions)
        rev = "Reverse" if "reversed" in v else "Standard"
        sections.append(f"""
    <section class="venue">
      <h2>{venue_title(v)} <span class="dir">{rev} layout</span></h2>
      <div class="cards">{cards}</div>
    </section>""")
        # per-session landing pages
        for s in sessions:
            if s["telemetry"]:
                write_landing(vdir, v, s)

    html = HOME_TEMPLATE.replace("{{SECTIONS}}", "\n".join(sections))
    (OUTPUT / "index.html").write_text(html)
    print(f"[build_home] wrote {OUTPUT/'index.html'}  ({len(venues)} venues)")
    print(f"[build_home] serve:  python -m http.server 8800 -d {OUTPUT}")
    print("[build_home] open:   http://localhost:8800/index.html")


def write_landing(vdir, venue, s):
    rdir = vdir / s["key"] / "dataset" / "render"
    btns = "\n".join(
        f'<a class="btn" href="{slug}.html">{label}</a>'
        for slug, label in s["dashboards"])
    vids = "\n".join(
        f'<li><a href="../../video/{v}">{v}</a></li>' for v in s["videos"])
    vids_block = f'<h3>Videos</h3><ul class="vids">{vids}</ul>' if vids else ""
    pos = (f"P{s['position']}" + (f"/{s['field_size']}" if s['field_size'] else "")
           if s.get("position") else "")
    html = LANDING_TEMPLATE.format(
        event=s["event"] or s["key"], key=s["key"],
        when=(s["datetime"] or "").replace("T", " "),
        cfg=s.get("config") or "", pos=pos,
        best=fmt_time(s["best"]), avg=fmt_time(s["avg"]),
        cv=(f"{s['cv']*100:.1f}%" if s["cv"] is not None else "-"),
        laps=s["laps"], btns=btns, vids=vids_block,
        home_rel="../../../../index.html")
    (rdir / "landing.html").write_text(html)


HOME_TEMPLATE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kart Telemetry — Sessions</title>
<style>
:root{--bg:#0b0e13;--card:#151a22;--line:#232b36;--txt:#e7edf5;--dim:#8b97a8;
--accent:#ff5c39;--good:#31d67a;}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);
font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
header{padding:34px 28px 10px;border-bottom:1px solid var(--line)}
h1{margin:0;font-size:26px;letter-spacing:.3px}
.sub{color:var(--dim);margin-top:6px;font-size:13px}
main{padding:24px 28px 60px;max-width:1200px;margin:0 auto}
.venue{margin-top:30px}
.venue h2{font-size:18px;border-left:3px solid var(--accent);padding-left:10px;margin:0 0 14px}
.dir{color:var(--dim);font-size:12px;font-weight:400;margin-left:8px}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px 16px 14px}
.card.notel{opacity:.82}
.chead{display:flex;justify-content:space-between;align-items:baseline;gap:10px;margin-bottom:12px}
.event{font-weight:650;font-size:15px}
.when{color:var(--dim);font-size:11.5px;text-align:right}
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:12px}
.metric{background:#0f141b;border:1px solid var(--line);border-radius:8px;padding:8px 9px}
.metric.primary{border-color:#2c6b45}
.metric.lead{border-color:var(--accent)}
.mlabel{font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:.4px}
.mval{font-size:18px;font-weight:700;margin-top:3px}
.metric.primary .mval{color:var(--good)}
.msub{font-size:9.5px;color:var(--dim);margin-top:2px;min-height:11px}
.links{display:flex;flex-wrap:wrap;gap:6px}
.btn{display:inline-block;background:#1d2530;border:1px solid var(--line);color:var(--txt);
text-decoration:none;padding:5px 10px;border-radius:6px;font-size:12px}
.btn:hover{border-color:var(--accent)}
.btn.hub{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600}
.tag.timing{color:var(--dim);font-size:12px;font-style:italic}
</style></head><body>
<header><h1>Kart Telemetry — Sessions</h1>
<div class="sub">Pick a session to open its dashboards. Headline metric: consistency (lap-time CV), then best lap, then average lap.</div>
</header><main>{{SECTIONS}}</main></body></html>"""


LANDING_TEMPLATE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{event} — {key}</title>
<style>
body{{margin:0;background:#0b0e13;color:#e7edf5;font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}}
header{{padding:28px;border-bottom:1px solid #232b36}}
a.back{{color:#8b97a8;text-decoration:none;font-size:13px}}
h1{{margin:8px 0 2px;font-size:24px}} .when{{color:#8b97a8;font-size:13px}}
main{{padding:24px 28px;max-width:900px;margin:0 auto}}
.metrics{{display:flex;gap:14px;flex-wrap:wrap;margin:8px 0 22px}}
.m{{background:#151a22;border:1px solid #232b36;border-radius:10px;padding:12px 16px;min-width:120px}}
.m .l{{font-size:11px;color:#8b97a8;text-transform:uppercase}} .m .v{{font-size:22px;font-weight:700;margin-top:4px}}
.m.primary .v{{color:#31d67a}}
.btns{{display:flex;flex-wrap:wrap;gap:10px}}
.btn{{background:#1d2530;border:1px solid #232b36;color:#e7edf5;text-decoration:none;padding:10px 16px;border-radius:8px;font-size:14px}}
.btn:hover{{border-color:#ff5c39}}
.vids a{{color:#7fb0ff}}
</style></head><body>
<header><a class="back" href="{home_rel}">← All sessions</a>
<h1>{event}</h1><div class="when">{when} · {cfg} · {pos}</div></header>
<main>
<div class="metrics">
  <div class="m primary"><div class="l">Consistency (CV)</div><div class="v">{cv}</div></div>
  <div class="m"><div class="l">Best lap</div><div class="v">{best}</div></div>
  <div class="m"><div class="l">Avg lap</div><div class="v">{avg}</div></div>
  <div class="m"><div class="l">Laps</div><div class="v">{laps}</div></div>
</div>
<h3>Dashboards</h3>
<div class="btns">{btns}</div>
{vids}
</main></body></html>"""


def run(venue=None):
    build_home()


if __name__ == "__main__":
    build_home()
