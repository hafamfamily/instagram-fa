#!/usr/bin/env python3
"""
selftest.py - تست سریع کل بسته پیش از انتشار نسخهٔ تازه.

  python tools/selftest.py            # همهٔ تست‌ها (بدون ویدیو)
  python tools/selftest.py --video    # همراه ساخت یک ریلز کوتاه (کندتر)
  python tools/selftest.py --sync     # fa_text.py اصلی (ig-create) را در بقیهٔ اسکیل‌ها کپی کن

fa_text.py عمداً کنار هر اسکیل تکرار شده تا هر اسکیل مستقل کار کند. نسخهٔ اصلی در
ig-create است؛ بعد از هر تغییر، --sync را اجرا کن.
"""

import argparse
import filecmp
import glob
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SK = os.path.join(ROOT, "skills")
MASTER = os.path.join(SK, "ig-create", "fa_text.py")
OK, BAD = "  ✓", "  ✗"
fails = []


def py(*args, cwd=None, timeout=300, env=None):
    r = subprocess.run([sys.executable, "-I", *args], capture_output=True, text=True, cwd=cwd,
                       timeout=timeout, env=env, encoding="utf-8", errors="replace")
    return r.returncode, r.stdout + r.stderr


def check(name, cond, detail=""):
    print(f"{OK if cond else BAD} {name}" + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        fails.append(name)


def copies():
    return [p for p in glob.glob(os.path.join(SK, "*", "fa_text.py")) if os.path.abspath(p) != MASTER]


def api_test(tmp, env, page):
    """کل مسیر انتشار خودکار در برابر mock_meta.py: ورود، حالت auto، کاروسل، چک‌های رد، خطای موقت."""
    import json
    import socket
    import urllib.request
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import mock_meta
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    srv = mock_meta.serve(port)
    base = f"http://127.0.0.1:{port}"
    e = dict(env, IGFA_GRAPH_BASE=base, IGFA_LITTERBOX_URL=base + "/litterbox", IGT=mock_meta.TOKEN, BAD="x" * 30)
    pub = os.path.join(SK, "ig-publish", "publish.py")
    api = os.path.join(SK, "ig-publish", "ig_api.py")
    pg = os.path.join(SK, "ig-setup", "page.py")
    try:
        rc, out = py(api, "login", "--page", page, "--from-env", "BAD", env=e)
        check("توکن نامعتبر رد می‌شود", rc != 0)
        rc, out = py(api, "login", "--page", page, "--from-env", "IGT", env=e)
        check("ورود با توکن", rc == 0 and "test_page" in out, out)
        sec = json.load(open(os.path.join(os.path.dirname(page), ".secrets", os.path.basename(page) + ".json")))
        check("توکن فقط در فایل رمزها", sec["instagram"]["access_token"] == mock_meta.TOKEN
              and mock_meta.TOKEN not in open(os.path.join(page, "publish.json"), encoding="utf-8").read())

        def item(kind, title, cap, date="2026-01-01", time_="09:00", src="carousel"):
            rc, out = py(pg, "item", "--type", kind, "--title", title, "--date", date, "--time", time_, env=e)
            d = out.strip().splitlines()[-1]
            shutil.copy(os.path.join(SK, "ig-create", "examples", src + ".json"), os.path.join(d, "spec.json"))
            py(os.path.join(SK, "ig-create", "render.py"), os.path.join(d, "spec.json"),
               "--page", page, "--out", os.path.join(d, "slides"), "--engine", "pil", env=e)
            if kind == "single":
                for f in sorted(glob.glob(os.path.join(d, "slides", "*.png")))[1:]:
                    os.remove(f)
            if cap is not None:
                open(os.path.join(d, "caption.txt"), "w", encoding="utf-8").write(cap)
            return d

        good = "لیست قیمت کل مغازه رو تو ۲ دقیقه بساز.\nکلمهٔ «لیست» رو کامنت کن.\n#مغازه"
        d1 = item("carousel", "کاروسل", good)
        d2 = item("single", "هشتگ زیاد", "۴۰ دقیقه صرفه‌جویی.\nکامنت کن.\n#a #b #c #d #e #f")
        d3 = item("story", "استوری", None, src="stories")
        d4 = item("single", "آینده", good, date="2099-01-01")
        rc, _ = py(pub, "approve", d1, "--auto", env=e)
        check("تأیید خودکار در حالت دستی رد می‌شود", rc != 0)
        py(pub, "mode", "--page", page, "auto", env=e)
        rc, out = py(pub, "due", "--page", page, env=e, timeout=300)
        st = {n: json.load(open(os.path.join(d, "status.json"), encoding="utf-8")) for n, d in
              (("c", d1), ("h", d2), ("s", d3), ("f", d4))}
        check("کاروسل خودکار منتشر شد", st["c"]["status"] == "posted" and "instagram.com" in st["c"].get("url", ""),
              out[-400:])
        check("کپشن FAIL منتشر نشد", st["h"]["status"] == "failed")
        check("استوری بدون قاب‌های استیکردار منتشر شد", st["s"]["status"] == "posted"
              and len(st["s"].get("manual_frames", [])) == 3 and len(st["s"].get("story_done", [])) == 2, out[-400:])
        check("پست آینده دست نخورد", st["f"]["status"] == "draft")
        log = json.loads(urllib.request.urlopen(base + "/_log").read())
        posts = [x for x in log if x["m"] == "POST" and x["path"].endswith("/media")]
        kids = [x for x in posts if x["q"].get("is_carousel_item") == "true"]
        carousel = [x for x in posts if x["q"].get("media_type") == "CAROUSEL"]
        check("کاروسل: ۶ فرزند بی‌کپشن و یک ظرف با کپشن",
              len(kids) == 6 and all("caption" not in k["q"] for k in kids) and carousel
              and carousel[0]["q"].get("caption", "").startswith("لیست"))
        d5 = item("single", "خطای موقت", good)
        urllib.request.urlopen(urllib.request.Request(base + "/_fail?code=100&times=1", method="POST"))
        rc, out = py(pub, "due", "--page", page, env=e, timeout=300)
        s5 = json.load(open(os.path.join(d5, "status.json"), encoding="utf-8"))
        check("خطای دائمی ثبت شد و منتشر نشد", s5["status"] == "failed" and s5.get("error"), out[-300:])
        rc, out = py(pub, "approve", d5, "--auto", env=e)
        rc, out = py(pub, "publish", d5, env=e, timeout=300)
        s5 = json.load(open(os.path.join(d5, "status.json"), encoding="utf-8"))
        check("تلاش دوباره بعد از رفع خطا", s5["status"] == "posted", out[-300:])
    finally:
        srv.shutdown()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", action="store_true")
    ap.add_argument("--sync", action="store_true")
    a = ap.parse_args()
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass

    if a.sync:
        for p in copies():
            shutil.copyfile(MASTER, p)
            print(f"{OK} {os.path.relpath(p, ROOT)}")
        return

    print("ساختار")
    for p in copies():
        check(f"fa_text یکسان: {os.path.relpath(p, ROOT)}", filecmp.cmp(MASTER, p, shallow=False),
              "اجرا کن: selftest.py --sync")
    for f in glob.glob(os.path.join(SK, "*", "*.py")):
        rc, out = py("-m", "py_compile", f)
        check(f"کامپایل {os.path.relpath(f, ROOT)}", rc == 0, out[-200:])
    for d in sorted(glob.glob(os.path.join(SK, "*"))):
        md = os.path.join(d, "SKILL.md")
        ok = os.path.exists(md) and open(md, encoding="utf-8").read().startswith("---\nname: ")
        check(f"SKILL.md {os.path.basename(d)}", ok)

    tmp = tempfile.mkdtemp(prefix="igfa-")
    env = dict(os.environ, HOME=os.path.join(tmp, "home"))
    os.makedirs(env["HOME"])
    try:
        print("\nپیج و محتوا")
        py(os.path.join(SK, "ig-setup", "page.py"), "home", os.path.join(tmp, "pages"), env=env)
        rc, out = py(os.path.join(SK, "ig-setup", "page.py"), "new", "selftest", env=env)
        check("ساخت پیج", rc == 0, out)
        page = os.path.join(tmp, "pages", "selftest")
        rc, out = py(os.path.join(SK, "ig-setup", "page.py"), "item", "--type", "carousel", "--title", "تست",
                     "--date", "2026-01-01", "--time", "19:00", env=env)
        item = out.strip().splitlines()[-1] if rc == 0 else ""
        check("ساخت پوشهٔ محتوا", rc == 0 and os.path.isdir(item), out)

        print("\nتصویر")
        ex = os.path.join(SK, "ig-create", "examples")
        for spec in ("carousel", "stories"):
            out_dir = os.path.join(item or tmp, "slides" if spec == "carousel" else spec)
            rc, out = py(os.path.join(SK, "ig-create", "render.py"), os.path.join(ex, spec + ".json"),
                         "--page", page, "--out", out_dir, "--engine", "pil", env=env)
            n = len(glob.glob(os.path.join(out_dir, "*.png")))
            check(f"{spec} با Pillow ({n} تصویر)", rc == 0 and n > 0, out[-300:])

        print("\nمتن")
        hooks = os.path.join(tmp, "hooks.txt")
        open(hooks, "w", encoding="utf-8").write("سلام دوستان امروز می‌خوام صحبت کنم\n"
                                                 "۹۰٪ مغازه‌دارها این اشتباه رو می‌کنن\n")
        rc, out = py(os.path.join(SK, "ig-reel", "hookscore.py"), hooks)
        first = [l for l in out.splitlines() if l.startswith("->")]
        check("امتیاز قلاب: قلاب عددی اول", rc == 0 and first and "۹۰" in first[0], out[-300:])
        cap = os.path.join(tmp, "cap.txt")
        open(cap, "w", encoding="utf-8").write("در دنیای امروز هوش مصنوعی نقش بسیار مهمی ایفا می‌کند.\n"
                                               "#a #b #c #d #e #f\n")
        rc, out = py(os.path.join(SK, "ig-caption", "caption.py"), cap)
        check("کپشن: بیش از ۵ هشتگ FAIL", "FAIL" in out, out[-300:])
        rc, out = py(os.path.join(SK, "ig-human", "humanize.py"), cap)
        clean = out.split("--- گزارش")[0]
        check("انسانی‌ساز: کلیشه‌ها حذف", rc == 0 and "دنیای امروز" not in clean and "ایفا" not in clean, out)
        rc, out = py(os.path.join(SK, "ig-human", "detect.py"), cap)
        check("پنل تشخیص اجرا شد", rc in (0, 1) and "امتیاز" in out, out[-300:])

        print("\nبرنامه و انتشار")
        xl = os.path.join(tmp, "plan.xlsx")
        rc, out = py(os.path.join(SK, "ig-plan", "plan_xlsx.py"), os.path.join(SK, "ig-plan", "examples", "plan.json"),
                     "--out", xl)
        check("اکسل برنامه", rc == 0 and os.path.exists(xl), out[-300:])
        if item:
            open(os.path.join(item, "caption.txt"), "w", encoding="utf-8").write("تست")
            pub = os.path.join(SK, "ig-publish", "publish.py")
            rc, _ = py(pub, "approve", item, env=env)
            check("تأیید بدون --approved-by رد می‌شود", rc != 0)
            rc, out = py(pub, "approve", item, "--approved-by", "بله", env=env)
            check("تأیید و پوشهٔ ready", rc == 0 and os.path.isdir(os.path.join(page, "ready")), out[-300:])
            rc, out = py(pub, "posted", item, env=env)
            check("ثبت در دفتر انتشار", rc == 0, out[-300:])

        print("\nانتشار با API (سرور شبیه‌ساز)")
        api_test(tmp, env, page)

        if a.video:
            print("\nویدیو")
            mp4 = os.path.join(tmp, "reel.mp4")
            frames = os.path.join(tmp, "frames")
            py(os.path.join(SK, "ig-create", "render.py"), os.path.join(ex, "reel.json"), "--page", page,
               "--out", frames, "--engine", "pil", env=env)
            rc, out = py(os.path.join(SK, "ig-create", "video.py"), os.path.join(ex, "reel.json"), "--page", page,
                         "--out", mp4, "--static", "--frames", frames, timeout=600, env=env)
            check("ریلز (بدون مرورگر)", rc == 0 and os.path.exists(mp4), out[-300:])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + ("همه درست است." if not fails else f"{len(fails)} تست شکست خورد."))
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
