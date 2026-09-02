"""webapp.py - browser front end for the kart telemetry pipeline.

  python kart/webapp.py [--port 8800] [--venue gateway-kartplex]

Serves a home page describing the sample sessions in the inbox with a button that
runs Stage A and Stage B. Pipeline output streams into the page; when it finishes,
the page lists the sessions with links into their dashboards. The output directory
is served as the site root, so the existing per-session pages keep working.
No dependencies beyond the standard library.
"""
from __future__ import annotations

import argparse
import csv
import html
import io
import json
import subprocess
import sys
import threading
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent          # ingestion/kart
ING = HERE.parent                                # ingestion
INBOX = ING / "inbox"
OUTPUT = ING / "output"
ASSETS = HERE / "assets"

# Channels previewed on the home page: file -> (label, columns to show)
PREVIEW_CHANNELS = [
    ("Location.csv", "GPS, 1 Hz", ["latitude", "longitude", "speed", "bearing", "horizontalAccuracy"]),
    ("Accelerometer.csv", "Accelerometer, 100 Hz", ["x", "y", "z"]),
    ("Gyroscope.csv", "Gyroscope, 100 Hz", ["x", "y", "z"]),
    ("Gravity.csv", "Gravity, 100 Hz", ["x", "y", "z"]),
    ("Headphone.csv", "AirPods head motion, 100 Hz", ["yaw", "pitch", "roll", "rotationRateZ"]),
    ("Microphone.csv", "Microphone loudness, 10 Hz", ["dBFS"]),
]
PREVIEW_ROWS = 4
PREVIEW_AT_S = 300.0        # sample rows from this far into the recording (mid-stint)

DASHBOARDS = [
    ("onboard", "Onboard"), ("coaching", "Coaching"), ("replay", "Replay"),
    ("ghost", "Ghost lap"), ("cockpit", "Cockpit"), ("sector1", "Sector 1"),
]

# CLI hints from the batch scripts that mean nothing in the browser.
NOISE = ("http.server", "export_video", "View dashboards", "Export video",
         "To view, run", "http://localhost", "[build_home] serve", "[build_home] open")

STAGE_A_STEPS = [
    ("Ingest", "unpack the Sensor Logger recording and check the required channels"),
    ("Timing sheet", "load the venue's official lap times for each session"),
    ("Sessions", "split one recording into its separate stints"),
    ("Audio sync", "fit the audio clock to the sensor clock as a drift rate"),
    ("Fusion", "fuse 1 Hz GPS with the 100 Hz IMU into a smooth trace"),
    ("Laps", "find start/finish crossings and validate against the sheet"),
    ("Dataset", "write the per-session dataset"),
]
STAGE_B_STEPS = [
    ("Sectors", "three sectors split by distance, per-lap sector table"),
    ("Analytics", "pace, consistency, theoretical best, clean-lap filtering"),
    ("Coaching", "debrief, ranked corners to work on, next-session plan"),
    ("Render", "30 Hz replay series and drift-corrected audio"),
    ("Ghost", "your best lap against an ideal lap stitched from best sectors"),
    ("Dashboards", "onboard, coaching, replay, ghost, cockpit and sector pages"),
]


_preview_cache: dict = {}


def data_preview(venue: str) -> dict:
    """Metadata and a few sample rows per channel, read straight from the ZIP."""
    if venue in _preview_cache:
        return _preview_cache[venue]
    zips = sorted((INBOX / venue).glob("*.zip"))
    if not zips:
        return {}
    out: dict = {"zip": zips[0].name, "size_mb": zips[0].stat().st_size / 1e6, "channels": []}
    with zipfile.ZipFile(zips[0]) as z:
        names = set(z.namelist())
        if "Metadata.csv" in names:
            meta = next(csv.DictReader(io.TextIOWrapper(z.open("Metadata.csv"), encoding="utf-8")))
            out["device"] = meta.get("device name")
            out["app_version"] = meta.get("appVersion")
            out["recorded"] = meta.get("recording time")
            out["timezone"] = meta.get("recording timezone")
        for fname, label, cols in PREVIEW_CHANNELS:
            if fname not in names:
                continue
            rows, n = [], 0
            with io.TextIOWrapper(z.open(fname), encoding="utf-8") as f:
                for rec in csv.DictReader(f):
                    n += 1
                    try:
                        t = float(rec.get("seconds_elapsed", "nan"))
                    except ValueError:
                        continue
                    if t >= PREVIEW_AT_S and len(rows) < PREVIEW_ROWS:
                        rows.append([f"{t:.2f}"] + [_short(rec.get(c, "")) for c in cols])
                    if len(rows) >= PREVIEW_ROWS and n > 200_000:
                        break
            out["channels"].append({"file": fname, "label": label, "rows_read": n,
                                    "cols": ["t (s)"] + cols, "rows": rows})
    _preview_cache[venue] = out
    return out


def _short(v: str) -> str:
    try:
        return f"{float(v):.6g}"
    except ValueError:
        return v


class Run:
    """State of the one pipeline run this server allows at a time."""

    def __init__(self, venue: str):
        self.venue = venue
        self.state = "idle"        # idle | running | done | failed
        self.lines: list[str] = []
        self.lock = threading.Lock()

    def start(self) -> bool:
        with self.lock:
            if self.state == "running":
                return False
            self.state = "running"
            self.lines = []
        threading.Thread(target=self._work, daemon=True).start()
        return True

    def _emit(self, line: str) -> None:
        with self.lock:
            self.lines.append(line)

    def _run(self, label: str, script: str) -> None:
        self._emit(f"### {label}")
        proc = subprocess.Popen(
            [sys.executable, "-u", str(HERE / script), self.venue],
            cwd=ING, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            if (line.strip("=- ") == "" or line.lstrip().startswith("lap_times=")
                    or any(k in line for k in NOISE)):
                continue
            self._emit(line)
        if proc.wait() != 0:
            raise RuntimeError(f"{script} exited with status {proc.returncode}")

    def _work(self) -> None:
        try:
            self._run("Stage A: recording to validated dataset", "run.py")
            self._run("Stage B: analytics, coaching, dashboards", "run_stage_b.py")
            self._emit("### Done")
            with self.lock:
                self.state = "done"
        except Exception as e:  # noqa: BLE001
            self._emit(f"!!! {e}")
            with self.lock:
                self.state = "failed"

    def snapshot(self, offset: int) -> dict:
        with self.lock:
            return {"state": self.state, "offset": len(self.lines),
                    "lines": self.lines[offset:]}


def inbox_sessions(venue: str) -> list[dict]:
    out = []
    for p in sorted((INBOX / venue).glob("*.json")):
        try:
            d = json.loads(p.read_text())
        except Exception:  # noqa: BLE001
            continue
        raw = d.get("lapTimes") or d.get("lap_times") or []
        laps = [x["time"] if isinstance(x, dict) else x for x in raw]
        best = min(laps) if laps else d.get("best_lap")
        out.append({"file": p.name, "date": d.get("date"), "time": d.get("time"),
                    "type": d.get("session_type") or d.get("event"),
                    "driver": d.get("driver"), "laps": len(laps), "best": best})
    return out


def finished_sessions(venue: str) -> list[dict]:
    out = []
    vdir = OUTPUT / venue
    if not vdir.exists():
        return out
    for sdir in sorted(p for p in vdir.iterdir() if p.is_dir() and not p.name.startswith("_")):
        cj = sdir / "dataset" / "coaching.json"
        sj = sdir / "dataset" / "session.json"
        if not cj.exists():
            continue
        c = json.loads(cj.read_text())
        s = json.loads(sj.read_text()) if sj.exists() else {}
        res = s.get("results", {})
        out.append({
            "key": sdir.name, "venue": venue,
            "event": s.get("event") or s.get("type") or sdir.name,
            "when": (s.get("datetime_local") or "").replace("T", " "),
            "best": res.get("best_lap_s"), "laps": (res.get("consistency") or {}).get("n"),
            "headline": c["debrief"]["headline"],
            "opportunity": c["debrief"]["biggest_opportunity"],
            "strategy": [f"{i['where']}: {i['do']}" for i in c["next_session_strategy"][:3]],
            "render": f"/{venue}/{sdir.name}/dataset/render",
        })
    return out


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kart Telemetry</title>
<style>
:root{--bg:#0b0e13;--card:#151a22;--line:#232b36;--txt:#e7edf5;--dim:#8b97a8;--accent:#ff5c39;--good:#31d67a;--bad:#ff5c5c}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
header{position:relative;padding:54px 28px 26px;border-bottom:1px solid var(--line);overflow:hidden;background:#0b0e13 url(/assets/kart-sector-1.png) center 30%/cover no-repeat}
header:before{content:"";position:absolute;inset:0;background:linear-gradient(90deg,rgba(11,14,19,.96) 0%,rgba(11,14,19,.86) 45%,rgba(11,14,19,.55) 100%)}
header>*{position:relative}
h1{margin:0;font-size:26px}.sub{color:var(--dim);margin-top:6px;font-size:13px}
main{padding:24px 28px 60px;max-width:1100px;margin:0 auto}
h2{font-size:18px;border-left:3px solid var(--accent);padding-left:10px;margin:30px 0 12px}
p{margin:8px 0;color:#c9d2de}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media(max-width:800px){.grid{grid-template-columns:1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px}
.card h3{margin:0 0 8px;font-size:14px;color:var(--dim);text-transform:uppercase;letter-spacing:.5px}
ol{margin:0;padding-left:20px}li{margin:4px 0}li b{color:var(--txt)}
table{border-collapse:collapse;width:100%}td,th{padding:6px 10px;border-bottom:1px solid var(--line);text-align:left;font-size:14px}th{color:var(--dim);font-weight:500}
button{background:var(--accent);color:#fff;border:0;border-radius:10px;padding:14px 26px;font-size:16px;font-weight:650;cursor:pointer;margin-top:18px}
button:disabled{opacity:.5;cursor:default}
#log{display:none;background:#05070a;border:1px solid var(--line);border-radius:12px;padding:14px;font:12.5px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;max-height:420px;overflow:auto;white-space:pre-wrap;margin-top:18px}
#log .h{color:var(--accent);font-weight:700}#log .ok{color:var(--good)}#log .bad{color:var(--bad)}
.status{display:inline-block;margin-left:14px;color:var(--dim);font-size:14px}
.sessions{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:16px}
.sess .top{display:flex;justify-content:space-between;align-items:baseline;gap:10px}
.sess .event{font-weight:650}.sess .when{color:var(--dim);font-size:12px}
.sess .head{margin:10px 0 6px;font-size:14px}.sess .opp{color:var(--dim);font-size:13px}
.sess ul{margin:8px 0 12px;padding-left:18px;font-size:13px;color:#c9d2de}
.btns a{display:inline-block;background:#0f141b;border:1px solid var(--line);border-radius:8px;padding:6px 11px;margin:3px 4px 0 0;color:var(--txt);text-decoration:none;font-size:13px}
.btns a.primary{border-color:var(--accent)}.btns a:hover{border-color:var(--accent)}
.shots{display:grid;grid-template-columns:1fr 1fr;gap:16px}@media(max-width:800px){.shots{grid-template-columns:1fr}}
.shots img{width:100%;border:1px solid var(--line);border-radius:10px;display:block}
.shots .cap{color:var(--dim);font-size:12.5px;margin-top:6px}
.raw .meta{color:var(--dim);font-size:13px;margin-bottom:10px}
.chan{margin:14px 0 0}.chan .lbl{font-size:13px;font-weight:600}.chan .lbl span{color:var(--dim);font-weight:400;margin-left:8px;font-size:12px}
.chan table{font:12px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;margin-top:4px}.chan td,.chan th{padding:3px 8px}
</style></head><body>
<header><h1>Kart telemetry coaching</h1>
<div class="sub">A phone in a pocket and AirPods in a helmet, turned into a debrief a driver can use.</div></header>
<main>
<h2>What this will do</h2>
<p>The inbox holds one Sensor Logger recording from a rental-kart session at Gateway Kartplex: 100&nbsp;Hz accelerometer and gyroscope, 1&nbsp;Hz GPS, in-helmet audio and head motion, plus the venue's printed timing sheet for each stint. Pressing the button runs the whole pipeline on it, about a minute, and every step validates itself against the timing sheet.</p>
<div class="grid">
<div class="card"><h3>Stage A: recording to dataset</h3><ol>__STAGE_A__</ol></div>
<div class="card"><h3>Stage B: analysis and coaching</h3><ol>__STAGE_B__</ol></div>
</div>
<h2>What you get</h2>
<div class="shots">
<div><img src="/assets/kart-debrief.png" alt="Coaching debrief dashboard"><div class="cap">Debrief: improvement priority, sector consistency, per-turn scores and cues, next-session plan.</div></div>
<div><img src="/assets/kart-sector-1.png" alt="Sector 1 study dashboard"><div class="cap">Sector study: braking and turn points on the GPS line, speed traces with a spread band, delta to best, where to brake next run.</div></div>
</div>
<h2>Raw data</h2>
<div class="card raw">__RAW__</div>
<h2>Sessions in the inbox</h2>
<div class="card"><table><tr><th>Date</th><th>Time</th><th>Session</th><th>Driver</th><th>Laps</th><th>Best (sheet)</th></tr>__INBOX__</table></div>
<button id="go">Begin analysis</button><span class="status" id="status"></span>
<div id="log"></div>
<div id="results"></div>
</main>
<script>
const go=document.getElementById('go'),log=document.getElementById('log'),
      status=document.getElementById('status'),results=document.getElementById('results');
let offset=0,timer=null;
function esc(s){return s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
function cls(l){if(l.startsWith('###'))return 'h';if(l.startsWith('!!!'))return 'bad';
  if(/STATUS: PASS|PASS$/.test(l))return 'ok';if(/FAIL|Traceback|Error/.test(l))return 'bad';return ''}
function append(lines){for(const l of lines){const d=document.createElement('div');
  const c=cls(l);if(c)d.className=c;d.textContent=l.replace(/^###\\s*/,'');log.appendChild(d)}
  log.scrollTop=log.scrollHeight}
function fmt(t){return t==null?'-':t.toFixed(3)+'s'}
function renderSessions(list){if(!list.length){results.innerHTML='';return}
  let h='<h2>Sessions</h2><div class="sessions">';
  for(const s of list){h+=`<div class="card sess"><div class="top"><span class="event">${esc(s.event)}</span><span class="when">${esc(s.when)} · ${s.laps||'-'} laps · best ${fmt(s.best)}</span></div>
    <div class="head">${esc(s.headline)}</div><div class="opp">${esc(s.opportunity)}</div>
    <ul>${s.strategy.map(x=>'<li>'+esc(x)+'</li>').join('')}</ul>
    <div class="btns"><a class="primary" href="${s.render}/landing.html">Open session</a>__DASH_LINKS__</div></div>`}
  results.innerHTML=h+'</div>'}
async function poll(){const r=await fetch('/api/status?offset='+offset);const j=await r.json();
  append(j.lines);offset=j.offset;
  if(j.state==='running'){status.textContent='Running…';go.disabled=true}
  else{clearInterval(timer);timer=null;go.disabled=false;
    status.textContent=j.state==='done'?'Complete':(j.state==='failed'?'Failed, see log':'');
    go.textContent=j.sessions.length?'Run analysis again':'Begin analysis';
    renderSessions(j.sessions);
    if(j.state==='done')results.scrollIntoView({behavior:'smooth'})}}
go.onclick=async()=>{go.disabled=true;log.style.display='block';log.innerHTML='';offset=0;results.innerHTML='';
  await fetch('/api/run',{method:'POST'});timer=setInterval(poll,700);poll()};
poll();
</script></body></html>"""


def render_page(venue: str) -> str:
    def steps(items):
        return "".join(f"<li><b>{html.escape(a)}</b>: {html.escape(b)}</li>" for a, b in items)
    rows = "".join(
        f"<tr><td>{html.escape(str(s['date'] or ''))}</td><td>{html.escape(str(s['time'] or ''))}</td>"
        f"<td>{html.escape(str(s['type'] or ''))}</td><td>{html.escape(str(s['driver'] or ''))}</td>"
        f"<td>{s['laps']}</td><td>{s['best']:.3f}s</td></tr>" if s['best'] else
        f"<tr><td colspan=6>{html.escape(s['file'])}</td></tr>"
        for s in inbox_sessions(venue)) or "<tr><td colspan=6>No timing sheets found in the inbox.</td></tr>"
    links = "".join(f'<a href="${{s.render}}/{slug}.html">{label}</a>' for slug, label in DASHBOARDS)
    pv = data_preview(venue)
    if pv:
        raw = (f"<p>Recorded with the <a href=\"https://www.tszheichoi.com/sensorlogger\" style=\"color:var(--accent)\">Sensor Logger</a> "
               f"app (v{html.escape(str(pv.get('app_version') or '?'))}) on an {html.escape(str(pv.get('device') or 'iPhone'))}, "
               f"with AirPods providing head motion and audio. One export, <code>{html.escape(pv['zip'])}</code> "
               f"({pv['size_mb']:.0f} MB), holds every channel as a CSV keyed on the same nanosecond clock. "
               f"Sample rows from {PREVIEW_AT_S / 60:.0f} minutes in:</p>")
        for ch in pv["channels"]:
            head = "".join(f"<th>{html.escape(c)}</th>" for c in ch["cols"])
            body = "".join("<tr>" + "".join(f"<td>{html.escape(v)}</td>" for v in r) + "</tr>" for r in ch["rows"])
            raw += (f'<div class="chan"><div class="lbl">{html.escape(ch["label"])}<span>{html.escape(ch["file"])}</span></div>'
                    f'<table><tr>{head}</tr>{body}</table></div>')
    else:
        raw = "<p>No recording found in the inbox.</p>"
    return (PAGE.replace("__STAGE_A__", steps(STAGE_A_STEPS))
                .replace("__STAGE_B__", steps(STAGE_B_STEPS))
                .replace("__INBOX__", rows)
                .replace("__DASH_LINKS__", links)
                .replace("__RAW__", raw))


def make_handler(run: Run):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            OUTPUT.mkdir(parents=True, exist_ok=True)
            super().__init__(*a, directory=str(OUTPUT), **kw)

        def log_message(self, fmt, *args):  # quiet
            pass

        def _json(self, obj, code=200):
            body = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                body = render_page(run.venue).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if path.startswith("/assets/"):
                f = ASSETS / Path(path).name
                if f.is_file() and f.suffix in (".png", ".jpg", ".jpeg", ".webp"):
                    body = f.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png" if f.suffix == ".png" else "image/jpeg")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "public, max-age=86400")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_error(404)
                return
            if path == "/api/status":
                q = self.path.partition("?")[2]
                offset = 0
                for kv in q.split("&"):
                    if kv.startswith("offset="):
                        try:
                            offset = int(kv[7:])
                        except ValueError:
                            pass
                snap = run.snapshot(offset)
                snap["sessions"] = finished_sessions(run.venue) if run.state != "running" else []
                self._json(snap)
                return
            super().do_GET()

        def do_POST(self):
            if self.path == "/api/run":
                started = run.start()
                self._json({"started": started, "state": run.state})
                return
            self.send_error(404)

    return Handler


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8800)
    ap.add_argument("--venue", default="gateway-kartplex")
    args = ap.parse_args()
    run = Run(args.venue)
    srv = ThreadingHTTPServer(("0.0.0.0", args.port), make_handler(run))
    print(f"[webapp] open http://localhost:{args.port}/   (venue={args.venue})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
