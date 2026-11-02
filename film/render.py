"""Renders the film one exact frame at a time, then lays the sound under it.

  uv run --no-project --with playwright python film/render.py                 the whole film
  uv run --no-project --with playwright python film/render.py --stills 3,12.5  single frames, for checking the look
"""

from __future__ import annotations

import http.server
import subprocess
import sys
import threading
import time
from functools import partial
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "film"


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass


def main() -> int:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), partial(Quiet, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    stills = sys.argv[2].split(",") if len(sys.argv) > 2 and sys.argv[1] == "--stills" else None
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True, args=["--force-color-profile=srgb", "--hide-scrollbars"])
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.on("pageerror", lambda e: print("page error:", e))
        page.on("console", lambda m: print("console:", m.text) if m.type == "error" else None)
        page.goto(f"http://127.0.0.1:{server.server_address[1]}/film/film.html")
        page.wait_for_function("window.__ready === true", timeout=120000)
        fps, duration = page.evaluate("[window.__fps, window.__duration]")
        if stills:
            (OUT / "stills").mkdir(parents=True, exist_ok=True)
            for s in stills:
                page.evaluate("f => window.__frame(f)", round(float(s) * fps))
                page.screenshot(path=str(OUT / "stills" / f"{float(s):07.2f}.jpg"), type="jpeg", quality=88)
            browser.close()
            return 0
        silent = OUT / "film.silent.mp4"
        ff = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "image2pipe", "-framerate", str(fps), "-c:v", "mjpeg", "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "17", "-pix_fmt", "yuv420p", str(silent)], stdin=subprocess.PIPE)
        started = time.time()
        total = int(duration * fps)
        for i in range(total):
            page.evaluate("f => window.__frame(f)", i)
            ff.stdin.write(page.screenshot(type="jpeg", quality=97))
            if i % 300 == 0:
                print(f"frame {i}/{total} ({time.time() - started:.0f} s)", flush=True)
        ff.stdin.close()
        ff.wait()
        browser.close()
    final = OUT / "emerald-demo.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(silent), "-i", str(OUT / "film.wav"), "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-shortest", "-movflags", "+faststart", str(final)], check=True)
    print("wrote", final, f"{final.stat().st_size / 1e6:.0f} MB, {duration:.1f} s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
