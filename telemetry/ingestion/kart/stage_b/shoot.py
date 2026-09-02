"""shoot.py - Stage B: headless screenshot / QA of a dashboard at a given time.

Serves the session render/ dir over HTTP (fetch() needs http, not file://), loads the
dashboard in headless Chromium, drives the render clock to t seconds via a JS hook,
captures a PNG, and reports console errors.

Run: python kart/stage_b/shoot.py <html_path> [t_seconds] [out_png]
"""
from __future__ import annotations
import functools
import http.server
import socketserver
import sys
import threading
from pathlib import Path
from playwright.sync_api import sync_playwright

W, H = 1920, 1080


def _serve(directory):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
    httpd.allow_reuse_address = True
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    return httpd, httpd.server_address[1]


def shoot(html_path, t=20.0, out_png=None, w=W, h=H, verbose=True):
    html_path = Path(html_path).resolve()
    out_png = Path(out_png) if out_png else html_path.with_suffix(f".t{int(t)}.png")
    serve_dir = html_path.parent
    httpd, port = _serve(serve_dir)
    url = f"http://127.0.0.1:{port}/{html_path.name}"
    errors = []
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
            pg = b.new_page(viewport={"width": w, "height": h}, device_scale_factor=2)
            pg.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.goto(url)
            try:
                pg.wait_for_function("window.__ready === true", timeout=15000)
                pg.evaluate(f"window.__seekFrame({t})")
                pg.wait_for_timeout(300)
            except Exception as e:
                errors.append(f"ready/seek failed: {e}")
            pg.screenshot(path=str(out_png))
            b.close()
    finally:
        httpd.shutdown()
    if verbose:
        print(f"[shoot] {html_path.name} @t={t}s -> {out_png}")
        if errors:
            print(f"[shoot] PAGE ERRORS ({len(errors)}):")
            for e in errors[:10]:
                print("   ", e)
        else:
            print("[shoot] no page errors")
    return out_png, errors


if __name__ == "__main__":
    html = sys.argv[1]
    t = float(sys.argv[2]) if len(sys.argv) > 2 else 20.0
    out = sys.argv[3] if len(sys.argv) > 3 else None
    shoot(html, t, out)
