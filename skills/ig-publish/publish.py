#!/usr/bin/env python3
"""
publish.py - تأیید و انتشار محتوا.

حالت پیج (publish.json، با «mode» عوض می‌شود):
  manual  هیچ محتوایی بدون «بله»ی صاحب پیج آمادهٔ انتشار نمی‌شود (پیش‌فرض)
  auto    محتوا بعد از چک‌های فنی، بدون سؤال تأیید می‌شود؛ اگر چکی رد شد، منتشر نمی‌شود و گزارش می‌گیرد
روش انتشار (method):
  manual  پوشهٔ ready/ با کپشن و چک‌لیست؛ خودت از گوشی منتشر می‌کنی
  api     انتشار خودکار با API رسمی اینستاگرام (ig_api.py login)

دستورها:
  python publish.py mode --page <پیج> [manual|auto]          نمایش یا تغییر حالت
  python publish.py check <محتوا>                             چک‌های فنی پیش از انتشار
  python publish.py approve <محتوا> --approved-by "بله"       تأیید دستی (متن دقیق جواب صاحب پیج)
  python publish.py approve <محتوا> --auto                    تأیید خودکار (فقط وقتی حالت پیج auto است)
  python publish.py publish <محتوا> [--dry-run]               انتشار همین حالا با API
  python publish.py due --page <پیج> | --all [--dry-run]      انتشار هر چه وقتش رسیده (برای زمان‌بند)
  python publish.py schedule [--apply] [--remove] [--every 15]   اجرای خودکار due روی همین کامپیوتر
  python publish.py revise  <محتوا> --note "قلاب ضعیف است"
  python publish.py posted  <محتوا> [--url ...]                ثبت انتشار دستی
  python publish.py list --page <پیج> [--status draft]

در هر دو حالت، محتوایی که چک فنی‌اش FAIL دارد منتشر نمی‌شود.
"""

import argparse
import csv
import datetime as dt
import glob
import json
import os
import platform
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import settings  # noqa: E402

TYPE_FA = {"carousel": "کاروسل", "single": "پست تکی", "reel": "ریلز", "story": "استوری"}
STATUS_FA = {"draft": "پیش‌نویس (منتظر تأیید)", "revise": "نیاز به اصلاح", "approved": "تأییدشده، آمادهٔ انتشار",
             "posted": "منتشرشده", "failed": "انتشار ناموفق"}
MAX_ATTEMPTS = 3


def setup_stdout():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass


def load(d):
    p = os.path.join(d, "status.json")
    if not os.path.exists(p):
        print(f"status.json در {d} نیست؛ این پوشهٔ محتوا نیست.", file=sys.stderr)
        sys.exit(2)
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save(d, st):
    tmp = os.path.join(d, "status.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
    os.replace(tmp, os.path.join(d, "status.json"))


def now():
    return dt.datetime.now().isoformat(timespec="minutes")


def page_of(item_dir):
    return os.path.dirname(os.path.dirname(os.path.abspath(item_dir)))


def log(page, msg):
    line = f"{dt.datetime.now().isoformat(timespec='seconds')}  {msg}"
    print(msg)
    try:
        with open(os.path.join(page, "publish.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def history(st, action, **kw):
    st.setdefault("history", []).append(dict({"at": now(), "action": action}, **kw))


# ---------- فایل‌های محتوا ----------

def media_of(d, st):
    """فایل‌های قابل انتشار به ترتیب: تصویرها و ویدیوها."""
    slides = sorted(glob.glob(os.path.join(d, "slides", "*.png")) + glob.glob(os.path.join(d, "slides", "*.jpg")))
    vids = sorted(glob.glob(os.path.join(d, "slides", "*.mp4")))
    reel = os.path.join(d, "reel.mp4")
    t = st["type"]
    if t == "reel":
        return {"video": reel if os.path.exists(reel) else None, "cover": slides[0] if slides else None}
    if t == "story":
        # استوری: تصویرها و ویدیوها به ترتیب نام
        return {"items": sorted(slides + vids, key=os.path.basename)}
    return {"items": sorted(slides + vids, key=os.path.basename)}


def sticker_frames(d):
    """نام فایل قاب‌های استوری که جای خالی استیکر دارند (API استیکر نمی‌گذارد)."""
    p = os.path.join(d, "spec.json")
    if not os.path.exists(p):
        return set()
    try:
        with open(p, encoding="utf-8") as f:
            slides = json.load(f).get("slides", [])
    except (ValueError, OSError):
        return set()
    out = set()
    for i, s in enumerate(slides, 1):
        if s.get("sticker") and s.get("sticker") != "none":
            out.update({f"{i:02d}.png", f"{i:02d}.jpg"})
    return out


def caption_of(d):
    p = os.path.join(d, "caption.txt")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return f.read().strip()
    return ""


def ffprobe_info(path):
    fp = shutil.which("ffprobe")
    if not fp:
        return {}
    r = subprocess.run([fp, "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height:format=duration",
                        "-of", "json", path], capture_output=True, text=True)
    try:
        j = json.loads(r.stdout)
    except ValueError:
        return {}
    info = {"duration": float(j.get("format", {}).get("duration", 0) or 0), "audio": False}
    for s in j.get("streams", []):
        if s.get("codec_type") == "video":
            info.update(vcodec=s.get("codec_name"), width=s.get("width"), height=s.get("height"))
        elif s.get("codec_type") == "audio":
            info["audio"] = True
    return info


def banned_words(page):
    """کلمه‌های ممنوع از page.md (بخش لحن) و خطوط قرمز صریح."""
    p = os.path.join(page, "page.md")
    if not os.path.exists(p):
        return []
    words = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            if "ممنوع است" in line and ":" in line:
                rest = line.split(":", 1)[1]
                for w in rest.replace("،", ",").replace("؛", ",").split(","):
                    w = w.strip(" «»\"'.-\n")
                    if len(w) >= 2:
                        words.append(w)
    return words


# ---------- چک فنی ----------

def preflight(d, st):
    """[(سطح, پیام)]؛ سطح FAIL یعنی منتشر نشود."""
    out = []
    t = st["type"]
    page = page_of(d)
    m = media_of(d, st)
    from PIL import Image

    if t == "reel":
        v = m["video"]
        if not v:
            out.append(("FAIL", "ویدیوی reel.mp4 ساخته نشده."))
        else:
            info = ffprobe_info(v)
            dur = info.get("duration", 0)
            if info and not (3 <= dur <= 900):
                out.append(("FAIL", f"طول ریلز {dur:.1f} ثانیه است؛ باید بین ۳ ثانیه و ۱۵ دقیقه باشد."))
            if info.get("vcodec") and info["vcodec"] not in ("h264", "hevc"):
                out.append(("FAIL", f"کدک ویدیو {info['vcodec']} است؛ اینستاگرام H.264 یا HEVC می‌خواهد."))
            if info.get("width") and info["width"] > 1920:
                out.append(("WARN", "عرض ویدیو بیشتر از ۱۹۲۰ است؛ هنگام انتشار کوچک می‌شود."))
    else:
        items = m["items"]
        if not items:
            out.append(("FAIL", "هیچ تصویری ساخته نشده؛ اول render.py را اجرا کن."))
        if t == "carousel" and not (2 <= len(items) <= 20):
            out.append(("FAIL", f"کاروسل {len(items)} آیتم دارد؛ باید بین ۲ و ۲۰ باشد."))
        if t == "single" and len(items) > 1:
            out.append(("WARN", f"پست تکی {len(items)} تصویر دارد؛ فقط اولی منتشر می‌شود."))
        for p in items:
            if p.endswith(".mp4"):
                info = ffprobe_info(p)
                lim = 60 if t == "story" else 900
                if info and not (3 <= info.get("duration", 0) <= lim):
                    out.append(("FAIL", f"{os.path.basename(p)}: طول {info.get('duration', 0):.1f} ثانیه؛ مجاز ۳ تا {lim}."))
                continue
            if os.path.exists(p + ".overflow"):
                out.append(("FAIL", f"{os.path.basename(p)}: متن از کادر بیرون زده."))
            if t != "story":
                w, h = Image.open(p).size
                r = w / h
                if not (0.8 - 0.005 <= r <= 1.91 + 0.005):
                    out.append(("FAIL", f"{os.path.basename(p)}: نسبت ابعاد {w}×{h} برای فید مجاز نیست (۴:۵ تا ۱٫۹۱:۱)."))

    if t == "story":
        st_frames = sorted(sticker_frames(d) & {os.path.basename(p) for p in m["items"]})
        if st_frames:
            out.append(("WARN", f"قاب‌های {'، '.join(st_frames)} جای خالی استیکر دارند؛ API استیکر نمی‌گذارد، پس "
                                "این قاب‌ها خودکار منتشر نمی‌شوند و در ready/ برای انتشار دستی می‌مانند."))
            if len(st_frames) == len(m["items"]):
                out.append(("FAIL", "همهٔ قاب‌های استوری جای استیکر دارند؛ چیزی برای انتشار خودکار نمی‌ماند."))

    cap = caption_of(d)
    if t != "story":
        if not cap:
            out.append(("FAIL", "caption.txt نیست یا خالی است."))
        else:
            sys.path.insert(0, os.path.join(SKILLS, "ig-caption"))
            try:
                import caption as C
                res, _ = C.check(cap, [])
                for r in res:
                    if r["status"] in ("FAIL", "WARN"):
                        out.append((r["status"], f"کپشن، {r['name']}: {r['detail']}"))
            except Exception as e:  # ابزار کپشن نباید انتشار را از کار بیندازد
                out.append(("WARN", f"بررسی کپشن انجام نشد: {e}"))
            if len(cap) > 2200:
                out.append(("FAIL", f"کپشن {len(cap)} حرف است؛ سقف ۲۲۰۰."))
        bad = [w for w in banned_words(page) if w in cap]
        if bad:
            out.append(("FAIL", f"کپشن کلمه‌های ممنوع پیج را دارد: {'، '.join(bad)}"))
    return out


def print_checks(res):
    if not res:
        print("  PASS  همهٔ چک‌ها")
    for lvl, msg in res:
        print(f"  {lvl:<4}  {msg}")


def fails(res):
    return [m for lvl, m in res if lvl == "FAIL"]


# ---------- تأیید ----------

def checklist(st, files, has_video):
    t = st["type"]
    lines = [f"# انتشار: {st['title']}", "",
             f"نوع: {TYPE_FA.get(t, t)}  ·  تاریخ پیشنهادی: {st.get('date', '')} {st.get('time', '')}", "",
             "## انتقال به گوشی", "",
             "یکی از این راه‌ها: پیام‌های ذخیره‌شدهٔ تلگرام (فایل را به‌صورت «فایل» بفرست، نه «عکس»، تا کیفیت کم نشود)، "
             "گوگل‌درایو، یا کابل.", "", "## مراحل در اینستاگرام", ""]
    if t == "story":
        lines += ["1. استوری‌ها را به ترتیب شماره (۰۱، ۰۲، ...) بگذار؛ هر کدام جدا.",
                  "2. جاهای خط‌چین «استیکر ... را اینجا بگذار» را با همان استیکر بپوشان (نظرسنجی، سؤال، لینک...).",
                  "3. فاصلهٔ استوری‌ها را در طول روز پخش کن؛ لازم نیست همه با هم باشند.",
                  "4. استوری‌های مهم را به هایلایت مرتبط اضافه کن."]
    elif t == "reel":
        lines += ["1. + ← Reel ← ویدیو `reel.mp4` را انتخاب کن.",
                  "2. موسیقی را از کتابخانهٔ خود اینستاگرام اضافه کن (صدای ترند مرتبط، با صدای کم زیر متن).",
                  "3. Edit cover ← از گالری `cover.png` را انتخاب کن." if any("cover" in f for f in files) else
                  "3. کاور: فریمی را انتخاب کن که متن قلاب کامل دیده شود.",
                  "4. کپشن را از `caption.txt` کپی کن.",
                  "5. اگر قلاب‌ها دو گزینه داشت، Trial reel را برای نسخهٔ دوم امتحان کن (اگر برایت فعال است).",
                  "6. Share."]
        if not has_video:
            lines.insert(-6, "توجه: ویدیو ساخته نشده؛ با فیلم‌نامه و بیت‌شیت `script.md` خودت ضبط کن.")
    else:
        lines += ["1. + ← Post ← چند انتخابی ← تصویرها را به ترتیب شماره انتخاب کن.",
                  "2. اندازه را روی ۴:۵ (عمودی) بگذار تا چیزی بریده نشود.",
                  "3. کپشن را از `caption.txt` کپی کن.",
                  "4. اگر محصول یا آدم دیگری در تصویر است، تگ کن.",
                  "5. Share."]
    lines += ["", "## بعد از انتشار", "",
              "- تا ۳۰ دقیقهٔ اول به همهٔ کامنت‌ها جواب بده (ig-engage کمکت می‌کند).",
              "- به Claude بگو «منتشر کردم» تا در دفتر انتشار ثبت شود.", ""]
    return "\n".join(lines)


def make_ready(d, st):
    """پوشهٔ ready/ برای انتشار دستی (و نسخهٔ پشتیبان در روش API)."""
    slides = sorted(glob.glob(os.path.join(d, "slides", "*.png")))
    video = os.path.join(d, "reel.mp4")
    has_video = os.path.exists(video)
    out = os.path.join(page_of(d), "ready", os.path.basename(d))
    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(out)
    copied = []
    if st["type"] == "reel":
        if has_video:
            shutil.copy(video, os.path.join(out, "reel.mp4"))
            copied.append("reel.mp4")
        if slides:
            shutil.copy(slides[0], os.path.join(out, "cover.png"))
            copied.append("cover.png")
        if os.path.exists(os.path.join(d, "script.md")):
            shutil.copy(os.path.join(d, "script.md"), os.path.join(out, "script.md"))
            copied.append("script.md")
    else:
        for i, s in enumerate(media_of(d, st)["items"], 1):
            name = f"{i:02d}{os.path.splitext(s)[1]}"
            shutil.copy(s, os.path.join(out, name))
            copied.append(name)
    if os.path.exists(os.path.join(d, "caption.txt")):
        shutil.copy(os.path.join(d, "caption.txt"), os.path.join(out, "caption.txt"))
        copied.append("caption.txt")
    with open(os.path.join(out, "انتشار.md"), "w", encoding="utf-8") as f:
        f.write(checklist(st, copied, has_video))
    return out, copied + ["انتشار.md"]


def approve(d, st, by, auto=False):
    res = preflight(d, st)
    bad = fails(res)
    if bad:
        return False, res
    out, files = make_ready(d, st)
    st["status"] = "approved"
    st["ready_dir"] = out
    st.pop("error", None)
    history(st, "approved", by=by, auto=auto)
    save(d, st)
    return True, res


def cmd_approve(a):
    d = os.path.abspath(a.item)
    st = load(d)
    page = page_of(d)
    cfg = settings.load(page)
    if st["status"] == "posted":
        print("این محتوا قبلاً منتشر شده.", file=sys.stderr)
        sys.exit(1)
    if a.auto:
        if cfg["mode"] != "auto":
            print("حالت این پیج «دستی» است؛ تأیید خودکار مجاز نیست. یا --approved-by با جواب صاحب پیج،"
                  " یا: publish.py mode --page <پیج> auto", file=sys.stderr)
            sys.exit(2)
        by = "خودکار (حالت auto)"
    else:
        if not a.approved_by or len(a.approved_by.strip()) < 2:
            print("بدون متن تأیید صاحب پیج نمی‌شود تأیید کرد (--approved-by).", file=sys.stderr)
            sys.exit(2)
        by = a.approved_by.strip()
    ok, res = approve(d, st, by, auto=a.auto)
    print_checks(res)
    if not ok:
        print("\nتأیید نشد؛ اول ایرادهای FAIL را درست کن.", file=sys.stderr)
        sys.exit(1)
    st = load(d)
    print(json.dumps({"status": "approved", "ready_dir": st["ready_dir"], "method": cfg["method"],
                      "when": f"{st.get('date', '')} {st.get('time', '')}".strip()}, ensure_ascii=False, indent=2))


def cmd_check(a):
    d = os.path.abspath(a.item)
    res = preflight(d, load(d))
    print_checks(res)
    sys.exit(1 if fails(res) else 0)


def cmd_mode(a):
    cfg = settings.load(a.page)
    if a.value:
        cfg["mode"] = a.value
        settings.save(a.page, cfg)
    print(f"حالت تأیید: {settings.MODES[cfg['mode']]}")
    print(f"روش انتشار: {settings.METHODS[cfg['method']]}")
    print(f"میزبانی فایل: {cfg['hosting'].get('provider')}")


def cmd_revise(a):
    d = os.path.abspath(a.item)
    st = load(d)
    st["status"] = "revise"
    history(st, "revise", note=a.note or "")
    save(d, st)
    print(f"برگشت برای اصلاح: {st['title']}")


def record_posted(d, st, url="", media_id="", method="manual"):
    st["status"] = "posted"
    st["posted_at"] = now()
    if url:
        st["url"] = url
    if media_id:
        st["media_id"] = media_id
    st.pop("error", None)
    history(st, "posted", url=url, method=method)
    save(d, st)
    log_path = os.path.join(page_of(d), "published.csv")
    new = not os.path.exists(log_path)
    with open(log_path, "a", encoding="utf-8-sig" if new else "utf-8", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["تاریخ انتشار", "نوع", "عنوان", "پوشه", "لینک"])
        w.writerow([st["posted_at"], TYPE_FA.get(st["type"], st["type"]), st["title"], os.path.basename(d), url])


def cmd_posted(a):
    d = os.path.abspath(a.item)
    st = load(d)
    if st["status"] != "approved":
        print("فقط محتوای تأییدشده را می‌شود «منتشرشده» ثبت کرد.", file=sys.stderr)
        sys.exit(1)
    record_posted(d, st, a.url or "")
    print(f"ثبت شد: {st['title']}")


def cmd_list(a):
    root = os.path.join(a.page, "content")
    rows = []
    for sp in sorted(glob.glob(os.path.join(root, "*", "status.json"))):
        with open(sp, encoding="utf-8") as f:
            st = json.load(f)
        if a.status and st["status"] != a.status:
            continue
        extra = f"  ← {st['error']}" if st.get("status") == "failed" and st.get("error") else ""
        rows.append((st.get("date", ""), st.get("time", ""), STATUS_FA.get(st["status"], st["status"]),
                     TYPE_FA.get(st["type"], st["type"]), st["title"] + extra, os.path.dirname(sp)))
    if not rows:
        print("محتوایی نیست.")
    for r in rows:
        print(f"{r[0]} {r[1]:<5}  {r[2]:<24} {r[3]:<9} {r[4]}\n            {r[5]}")


# ---------- آماده‌سازی فایل برای API ----------

def to_jpeg(src, dst):
    from PIL import Image, ImageCms  # noqa: F401
    im = Image.open(src)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    if im.width > 1440:
        im = im.resize((1440, round(im.height * 1440 / im.width)), Image.LANCZOS)
    q = 92
    while True:
        im.save(dst, "JPEG", quality=q, optimize=True, progressive=False, subsampling=0 if q >= 90 else 2)
        if os.path.getsize(dst) <= 8 * 1024 * 1024 or q <= 60:
            return dst
        q -= 8


def prep_video(src, dst):
    """MP4 سازگار با اینستاگرام: H.264، صدای AAC ۴۸ کیلوهرتز ۱۲۸ کیلوبیت (اگر صدا نیست، سکوت)، moov اول فایل."""
    ff = shutil.which("ffmpeg")
    if not ff:
        shutil.copy(src, dst)
        return dst
    info = ffprobe_info(src)
    vcopy = info.get("vcodec") == "h264" and (info.get("width") or 0) <= 1920
    cmd = [ff, "-y", "-hide_banner", "-loglevel", "error", "-i", src]
    if not info.get("audio"):
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-shortest", "-map", "0:v:0", "-map", "1:a:0"]
    else:
        cmd += ["-map", "0:v:0", "-map", "0:a:0"]
    cmd += (["-c:v", "copy"] if vcopy else
            ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
             "-vf", "scale='min(1080,iw)':-2", "-r", "30"])
    cmd += ["-c:a", "aac", "-ar", "48000", "-b:a", "128k", "-movflags", "+faststart", dst]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError("آماده‌سازی ویدیو نشد: " + r.stderr.decode("utf-8", "ignore")[-400:])
    return dst


class Uploader:
    def __init__(self, page, cfg, dry):
        import hosting
        self.h, self.cfg, self.sec, self.dry, self.page = hosting, cfg.get("hosting"), settings.secrets(page), dry, page

    def __call__(self, path):
        if self.dry:
            return "https://example.invalid/" + os.path.basename(path)
        url = self.h.upload(path, self.cfg, self.sec)
        log(self.page, f"   آپلود شد: {os.path.basename(path)}")
        return url


# ---------- انتشار با API ----------

def publish_item(d, dry=False):
    """یک محتوای تأییدشده را منتشر می‌کند. True اگر منتشر شد."""
    import ig_api
    import hosting
    st = load(d)
    page = page_of(d)
    cfg = settings.load(page)
    title = f"{TYPE_FA.get(st['type'], st['type'])} «{st['title']}»"
    if st["status"] not in ("approved", "failed"):
        log(page, f"✗ {title}: وضعیت «{STATUS_FA.get(st['status'], st['status'])}» است؛ فقط تأییدشده منتشر می‌شود.")
        return False
    res = preflight(d, st)
    if fails(res):
        st["status"] = "failed"
        st["error"] = "؛ ".join(fails(res))
        history(st, "failed", error=st["error"])
        save(d, st)
        log(page, f"✗ {title}: چک فنی رد شد: {st['error']}")
        return False
    if cfg["method"] != "api" and not dry:
        log(page, f"• {title}: روش انتشار این پیج «دستی» است؛ فایل‌ها در ready/ آماده‌اند.")
        return False

    work = os.path.join(d, ".upload")
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)
    up = Uploader(page, cfg, dry)
    cap = caption_of(d) or None
    ai = bool(cfg.get("ai_label")) and bool(st.get("ai_generated"))
    try:
        if dry:
            token, uid = "DRY", "DRY"
        else:
            token, uid = ig_api.ensure_token(page)
        log(page, f"→ انتشار {title}" + ("  (آزمایشی، بدون ارسال)" if dry else ""))

        def mk(**kw):
            if dry:
                log(page, "   ظرف: " + json.dumps({k: v for k, v in kw.items() if v is not None},
                                                    ensure_ascii=False)[:200])
                return "C" + str(len(kw))
            return ig_api.create(uid, token, **kw)

        def ready(cid, video=False):
            if not dry:
                ig_api.wait(cid, token, timeout=900 if video else 120, every=15 if video else 3,
                            log=(lambda m: log(page, m)) if video else None)

        def img_or_vid(path, n, **kw):
            if path.endswith(".mp4"):
                url = up(prep_video(path, os.path.join(work, f"{n:02d}.mp4")))
                return mk(video_url=url, **kw), True
            url = up(to_jpeg(path, os.path.join(work, f"{n:02d}.jpg")))
            return mk(image_url=url, **kw), False

        published = []
        m = media_of(d, st)
        t = st["type"]
        if t == "reel":
            vurl = up(prep_video(m["video"], os.path.join(work, "reel.mp4")))
            curl = up(to_jpeg(m["cover"], os.path.join(work, "cover.jpg"))) if m.get("cover") else None
            cid = mk(media_type="REELS", video_url=vurl, cover_url=curl, caption=cap,
                     share_to_feed=bool(cfg.get("share_to_feed", True)), is_ai_generated=ai or None)
            ready(cid, video=True)
            published.append(cid)
        elif t == "carousel":
            kids = []
            for n, p in enumerate(m["items"][:20], 1):
                cid, is_vid = img_or_vid(p, n, is_carousel_item=True)
                kids.append((cid, is_vid))
            for cid, is_vid in kids:
                ready(cid, video=is_vid)
            cid = mk(media_type="CAROUSEL", children=",".join(c for c, _ in kids), caption=cap,
                     is_ai_generated=ai or None)
            ready(cid)
            published.append(cid)
        elif t == "single":
            p = m["items"][0]
            if p.endswith(".mp4"):
                cid, _ = img_or_vid(p, 1, media_type="REELS", caption=cap, is_ai_generated=ai or None)
                ready(cid, video=True)
            else:
                cid, _ = img_or_vid(p, 1, caption=cap, alt_text=st.get("alt_text"), is_ai_generated=ai or None)
                ready(cid)
            published.append(cid)
        elif t == "story":
            # هر قاب یک استوری جدا؛ ترتیب حفظ می‌شود
            done = st.get("story_done", [])
            manual = sticker_frames(d)
            for n, p in enumerate(m["items"], 1):
                if os.path.basename(p) in done:
                    continue
                if os.path.basename(p) in manual:
                    log(page, f"   استوری {n} جای استیکر دارد؛ در ready/ ماند تا دستی منتشر شود")
                    st.setdefault("manual_frames", [])
                    if os.path.basename(p) not in st["manual_frames"]:
                        st["manual_frames"].append(os.path.basename(p))
                    if not dry:
                        save(d, st)
                    continue
                cid, is_vid = img_or_vid(p, n, media_type="STORIES")
                ready(cid, video=is_vid)
                if not dry:
                    ig_api.publish(uid, token, cid)
                    done.append(os.path.basename(p))
                    st["story_done"] = done
                    save(d, st)
                log(page, f"   استوری {n} منتشر شد")
            published = []

        url, mid = "", ""
        for cid in published:
            if dry:
                mid, url = "DRY", ""
            else:
                mid, url = ig_api.publish(uid, token, cid)
        if dry:
            log(page, f"✓ آزمایش {title} بی‌ایراد بود (چیزی ارسال نشد).")
            return True
        st = load(d)
        record_posted(d, st, url, mid, method="api")
        log(page, f"✓ منتشر شد: {title}" + (f"  {url}" if url else ""))
        return True
    except (ig_api.ApiError, hosting.HostingError, RuntimeError, OSError) as e:
        st = load(d)
        st["attempts"] = st.get("attempts", 0) + 1
        transient = getattr(e, "transient", False) or isinstance(e, hosting.HostingError)
        st["error"] = str(e)
        if transient and st["attempts"] < MAX_ATTEMPTS:
            st["status"] = "approved"   # دفعهٔ بعد دوباره امتحان می‌شود
            history(st, "retry", error=str(e))
            log(page, f"! {title}: {e}  (تلاش {st['attempts']} از {MAX_ATTEMPTS}؛ دفعهٔ بعد دوباره)")
        else:
            st["status"] = "failed"
            history(st, "failed", error=str(e))
            log(page, f"✗ {title}: {e}")
        save(d, st)
        return False
    finally:
        shutil.rmtree(work, ignore_errors=True)


def cmd_publish(a):
    d = os.path.abspath(a.item)
    with Lock(page_of(d)):
        ok = publish_item(d, dry=a.dry_run)
    sys.exit(0 if ok else 1)


# ---------- صف زمان‌بندی ----------

class Lock:
    """جلوی دو اجرای هم‌زمان روی یک پیج را می‌گیرد (مثلاً زمان‌بند و دستی)."""

    def __init__(self, page):
        self.p = os.path.join(page, ".publish.lock")

    def __enter__(self):
        if os.path.exists(self.p) and time.time() - os.path.getmtime(self.p) < 3600:
            print("یک انتشار دیگر روی این پیج در حال اجراست.", file=sys.stderr)
            sys.exit(3)
        with open(self.p, "w") as f:
            f.write(str(os.getpid()))
        return self

    def __exit__(self, *exc):
        try:
            os.remove(self.p)
        except OSError:
            pass


def due_time(st):
    try:
        day = dt.date.fromisoformat(st.get("date", ""))
    except ValueError:
        return dt.datetime.min
    hh, mm = 0, 0
    if st.get("time"):
        try:
            hh, mm = (int(x) for x in st["time"].split(":")[:2])
        except ValueError:
            pass
    return dt.datetime.combine(day, dt.time(hh, mm))


def pages_home():
    sys.path.insert(0, os.path.join(SKILLS, "ig-setup"))
    import page as P
    return P.home()


def run_due(page, dry=False, at=None):
    cfg = settings.load(page)
    at = at or dt.datetime.now()
    items = []
    for sp in sorted(glob.glob(os.path.join(page, "content", "*", "status.json"))):
        with open(sp, encoding="utf-8") as f:
            st = json.load(f)
        if due_time(st) <= at:
            items.append((due_time(st), os.path.dirname(sp), st))
    items.sort(key=lambda x: x[0])
    n = 0
    for _, d, st in items:
        s = st["status"]
        if s == "draft" and cfg["mode"] == "auto":
            ok, res = approve(d, st, "خودکار (حالت auto)", auto=True)
            if not ok:
                st = load(d)
                st["status"] = "failed"
                st["error"] = "؛ ".join(fails(res))
                history(st, "failed", error=st["error"])
                save(d, st)
                log(page, f"✗ «{st['title']}»: تأیید خودکار نشد: {st['error']}")
                continue
            s = "approved"
        # «failed» دوباره امتحان نمی‌شود (خطای موقت خودش به approved برمی‌گردد)؛ برای تلاش دستی: publish <محتوا>
        if s == "approved" and (cfg["method"] == "api" or dry):
            n += publish_item(d, dry=dry)
    return n


def cmd_due(a):
    pages = []
    if a.all:
        h = pages_home()
        pages = [os.path.join(h, x) for x in sorted(os.listdir(h)) if os.path.exists(os.path.join(h, x, "page.md"))]
    elif a.page:
        pages = [os.path.abspath(a.page)]
    else:
        print("--page یا --all لازم است.", file=sys.stderr)
        sys.exit(2)
    total = 0
    for p in pages:
        with Lock(p):
            total += run_due(p, dry=a.dry_run)
    if not total:
        print("چیزی برای انتشار در این لحظه نبود.")


def cmd_schedule(a):
    """اجرای «due --all» هر چند دقیقه روی همین کامپیوتر؛ کامپیوتر باید روشن و به اینترنت وصل باشد."""
    py = sys.executable
    me = os.path.abspath(__file__)
    name = "instagram-fa"
    system = platform.system()
    if system == "Windows":
        pyw = os.path.join(os.path.dirname(py), "pythonw.exe")
        runner = pyw if os.path.exists(pyw) else py
        if a.remove:
            cmd = ["schtasks", "/Delete", "/F", "/TN", name]
        else:
            cmd = ["schtasks", "/Create", "/F", "/SC", "MINUTE", "/MO", str(a.every), "/TN", name,
                   "/TR", f'"{runner}" "{me}" due --all']
        shown = " ".join(cmd)
    else:
        line = f'*/{a.every} * * * * "{py}" "{me}" due --all >/dev/null 2>&1  # {name}'
        if a.remove:
            cmd = ["sh", "-c", f"crontab -l 2>/dev/null | grep -v '# {name}$' | crontab -"]
        else:
            cmd = ["sh", "-c", f"(crontab -l 2>/dev/null | grep -v '# {name}$'; echo '{line}') | crontab -"]
        shown = line if not a.remove else "حذف خط instagram-fa از crontab"
    if not a.apply:
        print("این دستور زمان‌بند را تنظیم می‌کند (برای اجرا --apply بزن):\n")
        print("  " + shown)
        return
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("تنظیم زمان‌بند نشد:\n" + (r.stderr or r.stdout), file=sys.stderr)
        sys.exit(1)
    print("زمان‌بند حذف شد." if a.remove else
          f"زمان‌بند تنظیم شد: هر {a.every} دقیقه محتوای رسیده منتشر می‌شود. گزارش: <پوشهٔ پیج>/publish.log")


def main():
    setup_stdout()
    ap = argparse.ArgumentParser(description="تأیید و انتشار")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("mode")
    p.add_argument("value", nargs="?", choices=list(settings.MODES))
    p.add_argument("--page", required=True)
    p.set_defaults(fn=cmd_mode)
    p = sub.add_parser("check")
    p.add_argument("item")
    p.set_defaults(fn=cmd_check)
    p = sub.add_parser("approve")
    p.add_argument("item")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--approved-by", help="متن دقیق تأیید صاحب پیج")
    g.add_argument("--auto", action="store_true", help="تأیید خودکار؛ فقط در حالت auto")
    p.set_defaults(fn=cmd_approve)
    p = sub.add_parser("publish")
    p.add_argument("item")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_publish)
    p = sub.add_parser("due")
    p.add_argument("--page")
    p.add_argument("--all", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_due)
    p = sub.add_parser("schedule")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--remove", action="store_true")
    p.add_argument("--every", type=int, default=15)
    p.set_defaults(fn=cmd_schedule)
    p = sub.add_parser("revise")
    p.add_argument("item")
    p.add_argument("--note")
    p.set_defaults(fn=cmd_revise)
    p = sub.add_parser("posted")
    p.add_argument("item")
    p.add_argument("--url")
    p.set_defaults(fn=cmd_posted)
    p = sub.add_parser("list")
    p.add_argument("--page", required=True)
    p.add_argument("--status", choices=list(STATUS_FA))
    p.set_defaults(fn=cmd_list)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
