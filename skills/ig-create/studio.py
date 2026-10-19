#!/usr/bin/env python3
"""
studio.py - مرورگر بی‌سر برای ساخت تصویر و موشن‌گرافیک با HTML/CSS، بدون نصب برنامه روی ویندوز.

با Chrome DevTools Protocol از راه لوله (--remote-debugging-pipe) با کروم حرف می‌زند؛ پس هیچ
کتابخانهٔ پایتونی یا Node ای لازم نیست. کروم را به این ترتیب پیدا می‌کند:
  ۱. متغیر IGFA_BROWSER
  ۲. Chromium ای که Playwright نصب کرده
  ۳. Chrome / Chromium / Edge نصب‌شده روی سیستم
  ۴. Chromium قابل‌حمل (بستهٔ @sparticuz/chromium از npm): یک بار در پوشهٔ ابزار پیج‌ها دانلود
     می‌شود (~۶۶ مگابایت، قابل ادامه) و در هر جلسه در چند ثانیه در /tmp باز می‌شود.

استفاده:
  python studio.py status            # کدام مرورگر در دسترس است
  python studio.py setup             # آماده‌سازی Chromium قابل‌حمل؛ تا «READY» تکرار کن
  python studio.py shot page.html out.png --size 1080x1350 [--transparent]
"""

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SPARTICUZ_URL = "https://registry.npmjs.org/@sparticuz/chromium/-/chromium-131.0.1.tgz"
SPARTICUZ_SIZE = 66145807
EXTRACT_DIR = os.path.join(tempfile.gettempdir(), "igfa-chromium")

ARGS = [
    "--headless=new", "--no-sandbox", "--no-zygote", "--disable-setuid-sandbox", "--disable-dev-shm-usage",
    "--disable-gpu", "--hide-scrollbars", "--mute-audio", "--no-first-run", "--no-default-browser-check",
    "--disable-extensions", "--disable-background-networking", "--disable-sync", "--disable-breakpad",
    "--disable-component-update", "--disable-default-apps", "--force-color-profile=srgb",
    "--font-render-hinting=none", "--disable-features=Translate,MediaRouter,OptimizationHints",
    "--allow-file-access-from-files", "--remote-debugging-pipe",
]
SHELL_ARGS = ["--headless='shell'", "--single-process", "--use-gl=angle", "--use-angle=swiftshader",
              "--in-process-gpu"]


def tools_dir():
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(HERE), "ig-setup"))
        import page  # noqa
        base = page.home()
    except Exception:
        base = os.path.join(os.path.expanduser("~"), "instagram-fa")
    return os.path.join(base, ".tools")


# ---------------------------------------------------------------- finding a browser

def find_browser():
    """(path, kind) یا (None, None). kind: chrome | shell"""
    env = os.environ.get("IGFA_BROWSER")
    if env and os.path.exists(env):
        return env, "chrome"
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            exe = p.chromium.executable_path
        if exe and os.path.exists(exe):
            return exe, "chrome"
    except Exception:
        pass
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "msedge",
                 "microsoft-edge"):
        p = shutil.which(name)
        if p:
            return p, "chrome"
    for c in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"):
        if os.path.exists(c):
            return c, "chrome"
    exe = os.path.join(EXTRACT_DIR, "chromium")
    if os.path.exists(exe):
        return exe, "shell"
    return None, None


def _brotli(src, dst):
    node = shutil.which("node")
    if node:
        js = ("const z=require('zlib'),fs=require('fs');"
              "fs.writeFileSync(process.argv[2],z.brotliDecompressSync(fs.readFileSync(process.argv[1])))")
        subprocess.run([node, "-e", js, src, dst], check=True)
        return
    try:
        import brotli
    except ImportError:
        raise RuntimeError("برای باز کردن Chromium یا node لازم است یا `pip install brotli`.")
    with open(src, "rb") as f, open(dst, "wb") as g:
        g.write(brotli.decompress(f.read()))


def setup(budget=38):
    """گام‌به‌گام و قابل ادامه. خروجی: READY یا CONTINUE."""
    t0 = time.time()
    exe, kind = find_browser()
    if exe:
        return "READY", exe
    dl = os.path.join(tools_dir(), "dl")
    os.makedirs(dl, exist_ok=True)
    tgz = os.path.join(dl, os.path.basename(SPARTICUZ_URL))
    have = os.path.getsize(tgz) if os.path.exists(tgz) else 0
    if have < SPARTICUZ_SIZE:
        curl = shutil.which("curl")
        if not curl:
            raise RuntimeError("curl پیدا نشد")
        left = max(5, int(budget - (time.time() - t0)))
        subprocess.run([curl, "-s", "-L", "-C", "-", "--max-time", str(left), "-o", tgz, SPARTICUZ_URL])
        have = os.path.getsize(tgz) if os.path.exists(tgz) else 0
        if have < SPARTICUZ_SIZE:
            return "CONTINUE", f"دانلود {have * 100 // SPARTICUZ_SIZE}٪ — دوباره اجرا کن"
    os.makedirs(EXTRACT_DIR, exist_ok=True)
    work = tempfile.mkdtemp(prefix="igfa-sp-")
    subprocess.run(["tar", "xzf", tgz, "-C", work, "package/bin"], check=True)
    b = os.path.join(work, "package", "bin")
    _brotli(os.path.join(b, "swiftshader.tar.br"), os.path.join(work, "ss.tar"))
    subprocess.run(["tar", "xf", os.path.join(work, "ss.tar"), "-C", EXTRACT_DIR], check=True)
    _brotli(os.path.join(b, "chromium.br"), os.path.join(EXTRACT_DIR, "chromium.part"))
    os.chmod(os.path.join(EXTRACT_DIR, "chromium.part"), 0o755)
    os.replace(os.path.join(EXTRACT_DIR, "chromium.part"), os.path.join(EXTRACT_DIR, "chromium"))
    shutil.rmtree(work, ignore_errors=True)
    return "READY", os.path.join(EXTRACT_DIR, "chromium")


# ---------------------------------------------------------------- CDP over pipe

class Browser:
    def __init__(self, exe=None, kind=None):
        if not exe:
            exe, kind = find_browser()
        if not exe:
            raise RuntimeError("مرورگری پیدا نشد؛ اول `python studio.py setup` را تا READY اجرا کن.")
        self.exe, self.kind = exe, kind
        self.profile = tempfile.mkdtemp(prefix="igfa-prof-")
        args = [exe] + ARGS + [f"--user-data-dir={self.profile}"]
        if kind == "shell":
            args = [a for a in args if not a.startswith("--headless") and a != "--disable-gpu"] + SHELL_ARGS
        r_cmd, w_cmd = os.pipe()  # ما می‌نویسیم ← کروم از fd 3 می‌خواند
        r_res, w_res = os.pipe()  # کروم در fd 4 می‌نویسد ← ما می‌خوانیم

        def child():
            os.dup2(r_cmd, 3)
            os.dup2(w_res, 4)

        env = dict(os.environ)
        if kind == "shell":
            env["LD_LIBRARY_PATH"] = EXTRACT_DIR + ":" + env.get("LD_LIBRARY_PATH", "")
        self.proc = subprocess.Popen(args, pass_fds=(3, 4, r_cmd, w_res), preexec_fn=child, env=env,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.close(r_cmd)
        os.close(w_res)
        self.w = os.fdopen(w_cmd, "wb", buffering=0)
        self.r = os.fdopen(r_res, "rb", buffering=0)
        self.buf = b""
        self.id = 0
        self.events = []
        tid = self.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        self.sid = self.call("Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
        self.call("Page.enable", session=True)
        self.call("Runtime.enable", session=True)
        self.size = None

    def _read_msg(self, timeout=60):
        t0 = time.time()
        while b"\0" not in self.buf:
            chunk = self.r.read(1 << 16)
            if not chunk:
                raise RuntimeError("مرورگر بسته شد")
            self.buf += chunk
            if time.time() - t0 > timeout:
                raise TimeoutError("مرورگر جواب نداد")
        msg, self.buf = self.buf.split(b"\0", 1)
        return json.loads(msg)

    def call(self, method, params=None, session=False, timeout=60):
        self.id += 1
        msg = {"id": self.id, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = self.sid
        self.w.write(json.dumps(msg).encode() + b"\0")
        while True:
            m = self._read_msg(timeout)
            if m.get("id") == self.id:
                if "error" in m:
                    raise RuntimeError(f"{method}: {m['error']}")
                return m.get("result", {})
            self.events.append(m)

    def wait_event(self, name, timeout=30):
        t0 = time.time()
        while True:
            for i, e in enumerate(self.events):
                if e.get("method") == name:
                    self.events.pop(i)
                    return e
            if time.time() - t0 > timeout:
                raise TimeoutError(name)
            self.events.append(self._read_msg(timeout))

    def eval(self, expr, await_promise=True):
        r = self.call("Runtime.evaluate", {"expression": expr, "awaitPromise": await_promise,
                                           "returnByValue": True}, session=True)
        if r.get("exceptionDetails"):
            raise RuntimeError(f"JS: {r['exceptionDetails'].get('text')} {expr[:80]}")
        return r.get("result", {}).get("value")

    def open(self, html_path, size, transparent=False):
        if self.size != size:
            self.call("Emulation.setDeviceMetricsOverride", {"width": size[0], "height": size[1],
                                                             "deviceScaleFactor": 1, "mobile": False}, session=True)
            self.size = size
        self.call("Emulation.setDefaultBackgroundColorOverride",
                  {"color": {"r": 0, "g": 0, "b": 0, "a": 0}} if transparent else {}, session=True)
        self.events = [e for e in self.events if e.get("method") != "Page.loadEventFired"]
        url = "file://" + os.path.abspath(html_path).replace("\\", "/")
        self.call("Page.navigate", {"url": url}, session=True)
        self.wait_event("Page.loadEventFired")
        self.eval("document.fonts.ready.then(()=>new Promise(r=>requestAnimationFrame(()=>r(1))))")
        return self.eval("window.__igfa_ready ? window.__igfa_ready() : {}") or {}

    def screenshot(self, fmt="png", quality=92):
        p = {"format": fmt, "captureBeyondViewport": False, "optimizeForSpeed": fmt == "jpeg"}
        if fmt == "jpeg":
            p["quality"] = quality
        return base64.b64decode(self.call("Page.captureScreenshot", p, session=True)["data"])

    def close(self):
        try:
            self.call("Browser.close", timeout=5)
        except Exception:
            pass
        try:
            self.proc.wait(5)
        except Exception:
            self.proc.kill()
        shutil.rmtree(self.profile, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    st = sub.add_parser("setup")
    st.add_argument("--budget", type=int, default=38)
    sh = sub.add_parser("shot")
    sh.add_argument("html")
    sh.add_argument("out")
    sh.add_argument("--size", default="1080x1350")
    sh.add_argument("--transparent", action="store_true")
    a = ap.parse_args()
    if a.cmd == "status":
        exe, kind = find_browser()
        print(json.dumps({"browser": exe, "kind": kind, "tools": tools_dir()}, ensure_ascii=False))
    elif a.cmd == "setup":
        state, info = setup(a.budget)
        print(state, info)
        sys.exit(0 if state == "READY" else 10)
    elif a.cmd == "shot":
        w, h = (int(x) for x in a.size.split("x"))
        with Browser() as b:
            info = b.open(a.html, (w, h), a.transparent)
            with open(a.out, "wb") as f:
                f.write(b.screenshot())
        print(json.dumps(info, ensure_ascii=False))


if __name__ == "__main__":
    main()
