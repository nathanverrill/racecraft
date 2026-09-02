"""export_video.py - Stage B: render a dashboard to an MP4 with synced engine audio.

Drives the dashboard's window.__seekFrame(t) hook in headless Chromium, captures one
PNG per output frame, pipes them to ffmpeg, then muxes the session's DRIFT-CORRECTED
session.wav (which already maps 1:1 to telemetry t) so the video is frame-accurate to
the audio - the moving dot and engine note stay locked together.

CLI:
  python kart/stage_b/export_video.py <render_dir> [--html onboard.html]
      [--lap N | --t0 S --t1 S] [--fps 30] [--w 1920] [--h 1080] [--scale 1]
      [--out path.mp4]

Examples:
  # full session, onboard, 1080p30
  python kart/stage_b/export_video.py output/gateway-kartplex/2026-06-25_14-40/dataset/render
  # just the best lap window
  python ... --lap 11
"""
from __future__ import annotations
import argparse
import functools
import http.server
import json
import socketserver
import subprocess
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright


def _serve(directory):
    h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), h)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]


def lap_window(render_dir, lap):
    rj = json.load(open(Path(render_dir) / "render.json"))
    for l in rj["laps"]:
        if int(l["lap"]) == lap:
            # find session-time window from laps.csv via series lap index
            t = rj["series"]["t"]; lp = rj["series"]["lap"]
            idx = [i for i, x in enumerate(lp) if x == lap]
            if idx:
                return t[idx[0]], t[idx[-1]]
    return None


def export(render_dir, html="onboard.html", t0=None, t1=None, fps=30, w=1920, h=1080,
           scale=1, out=None, lap=None, relative_seek=False, audio=None):
    render_dir = Path(render_dir).resolve()
    rj = json.load(open(render_dir / "render.json"))
    dur = rj["duration_s"]
    if lap is not None:
        win = lap_window(render_dir, lap)
        if win:
            t0, t1 = win
    t0 = 0.0 if t0 is None else float(t0)
    t1 = dur if t1 is None else float(t1)
    tag = f"lap{lap}" if lap is not None else (f"{int(t0)}-{int(t1)}" if (t0 or t1 != dur) else "full")
    out = Path(out) if out else render_dir.parent.parent / "video" / f"{Path(html).stem}_{tag}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)

    n_frames = int(round((t1 - t0) * fps))
    print(f"[export] {html} {tag}: {t1-t0:.1f}s -> {n_frames} frames @{fps}fps {w}x{h} (x{scale})")

    httpd, port = _serve(render_dir)
    url = f"http://127.0.0.1:{port}/{html}"
    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "error", "-f", "image2pipe", "-vcodec", "png",
         "-r", str(fps), "-i", "-",
         "-vf", "format=yuv420p", "-c:v", "libx264", "-preset", "medium",
         "-crf", "18", str(out.with_suffix(".noaudio.mp4"))],
        stdin=subprocess.PIPE)
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
            pg = b.new_page(viewport={"width": w, "height": h}, device_scale_factor=scale)
            errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            pg.goto(url)
            pg.wait_for_function("window.__ready === true", timeout=20000)
            for k in range(n_frames):
                t = t0 + k / fps
                seek_t = (t - t0) if relative_seek else t
                pg.evaluate(f"window.__seekFrame({seek_t})")
                png = pg.screenshot(type="png")
                ff.stdin.write(png)
                if k % (fps * 10) == 0:
                    print(f"   frame {k}/{n_frames} (t={t:.0f}s)")
            b.close()
            if errs:
                print(f"[export] WARN page errors: {errs[:3]}")
    finally:
        ff.stdin.close(); ff.wait(); httpd.shutdown()

    # mux audio for the window: extract [t0,t1] from session.wav (already 1:1 with t)
    if audio:
        wav = render_dir / audio
        # narration.wav is already the lap window (starts at 0) -> no -ss
        amux = ["-i", str(wav)]
    else:
        wav = render_dir / "session.wav"
        amux = ["-ss", f"{t0:.3f}", "-t", f"{t1-t0:.3f}", "-i", str(wav)]
    print(f"[export] muxing audio ({audio or 'session.wav'}) -> {out.name}")
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-i", str(out.with_suffix(".noaudio.mp4"))] + amux +
        ["-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", str(out)],
        check=True)
    out.with_suffix(".noaudio.mp4").unlink(missing_ok=True)
    print(f"[export] DONE -> {out}")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("render_dir")
    ap.add_argument("--html", default="onboard.html")
    ap.add_argument("--lap", type=int, default=None)
    ap.add_argument("--t0", type=float, default=None)
    ap.add_argument("--t1", type=float, default=None)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--w", type=int, default=1920)
    ap.add_argument("--h", type=int, default=1080)
    ap.add_argument("--scale", type=int, default=1)
    ap.add_argument("--relative-seek", action="store_true",
                    help="pass lap-relative time to __seekFrame (for replay.html)")
    ap.add_argument("--audio", default=None, help="audio file in render/ to mux (e.g. narration.wav)")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    export(a.render_dir, a.html, a.t0, a.t1, a.fps, a.w, a.h, a.scale, a.out, a.lap,
           a.relative_seek, a.audio)
