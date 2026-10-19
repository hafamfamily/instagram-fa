#!/usr/bin/env python3
"""
media.py - آماده کردن عکس و فیلم‌های خودت (گوشی، دوربین، اسکرین‌شات، تصویر ساخته‌شده با هوش مصنوعی)
برای ساخت پست و ریلز.

  probe   فهرست فایل‌ها با نوع، اندازه، جهت (عمودی/افقی) و مدت فیلم
  import  کپی به پوشهٔ media محتوا: عکس‌ها چرخش درست (EXIF)، حداکثر ۲۴۰۰ پیکسل، JPG؛
          HEIC آیفون هم اگر pillow-heif نصب باشد (`pip install pillow-heif`). فیلم‌ها همان‌طور کپی می‌شوند
          (ffmpeg فیلم HEVC/MOV آیفون را می‌خواند).

استفاده:
  python media.py probe <پوشه یا فایل‌ها>
  python media.py import <پوشهٔ منبع> --to <پوشهٔ محتوا>/media
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

IMG = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".bmp", ".gif"}
VID = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".3gp"}
AUD = {".m4a", ".mp3", ".wav", ".aac", ".ogg", ".opus"}


def setup_stdout():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass


def files_of(paths):
    out = []
    for p in paths:
        if os.path.isdir(p):
            for fn in sorted(os.listdir(p)):
                out.append(os.path.join(p, fn))
        else:
            out.append(p)
    return [f for f in out if os.path.splitext(f)[1].lower() in IMG | VID | AUD]


def open_image(path):
    from PIL import Image, ImageOps
    if os.path.splitext(path)[1].lower() in (".heic", ".heif"):
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError:
            raise RuntimeError("برای عکس HEIC آیفون: pip install pillow-heif  (یا در گوشی: تنظیمات ← Camera ← "
                               "Formats ← Most Compatible)")
    im = Image.open(path)
    return ImageOps.exif_transpose(im)


def vinfo(path):
    ff = shutil.which("ffprobe")
    if not ff:
        return {}
    r = subprocess.run([ff, "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height:stream_side_data=rotation:format=duration", "-of", "json", path],
                       capture_output=True, text=True)
    try:
        d = json.loads(r.stdout)
        st = (d.get("streams") or [{}])[0]
        w, h = st.get("width", 0), st.get("height", 0)
        rot = 0
        for sd in st.get("side_data_list", []) or []:
            rot = abs(int(sd.get("rotation", 0) or 0))
        if rot in (90, 270):
            w, h = h, w
        return {"w": w, "h": h, "dur": float(d.get("format", {}).get("duration", 0) or 0)}
    except Exception:
        return {}


def cmd_probe(a):
    for f in files_of(a.paths):
        ext = os.path.splitext(f)[1].lower()
        name = os.path.basename(f)
        if ext in IMG:
            try:
                im = open_image(f)
                w, h = im.size
                ori = "عمودی" if h > w * 1.05 else ("افقی" if w > h * 1.05 else "مربع")
                print(f"عکس   {name:<34} {w}×{h}  {ori}")
            except Exception as e:
                print(f"عکس   {name:<34} ⚠️ {e}")
        elif ext in VID:
            v = vinfo(f)
            ori = "عمودی" if v.get("h", 0) > v.get("w", 0) else "افقی"
            print(f"فیلم  {name:<34} {v.get('w')}×{v.get('h')}  {ori}  {v.get('dur', 0):.1f} ثانیه")
        else:
            v = vinfo(f)
            print(f"صدا   {name:<34} {v.get('dur', 0):.1f} ثانیه")


def cmd_import(a):
    os.makedirs(a.to, exist_ok=True)
    n = 0
    for f in files_of([a.src]):
        ext = os.path.splitext(f)[1].lower()
        stem = os.path.splitext(os.path.basename(f))[0]
        if ext in IMG:
            try:
                im = open_image(f).convert("RGB")
            except Exception as e:
                print(f"⚠️ {os.path.basename(f)}: {e}")
                continue
            im.thumbnail((2400, 2400))
            out = os.path.join(a.to, stem + ".jpg")
            im.save(out, quality=92)
        else:
            out = os.path.join(a.to, os.path.basename(f))
            shutil.copy(f, out)
        n += 1
        print(f"✓ {out}")
    print(f"{n} فایل آماده شد.")


def main():
    setup_stdout()
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("probe")
    p.add_argument("paths", nargs="+")
    p.set_defaults(fn=cmd_probe)
    p = sub.add_parser("import")
    p.add_argument("src")
    p.add_argument("--to", required=True)
    p.set_defaults(fn=cmd_import)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
