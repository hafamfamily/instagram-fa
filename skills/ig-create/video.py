#!/usr/bin/env python3
"""
video.py - ساخت ویدیوی ریلز «متن روی تصویر» از فریم‌هایی که render.py ساخته.

برای پیج‌هایی که نمی‌خواهند چهره نشان بدهند: هر بیتِ متن یک فریم ۱۰۸۰×۱۹۲۰ است،
هر فریم به اندازهٔ «dur» خودش (از spec.json) روی صفحه می‌ماند، با محو شدن نرم بین فریم‌ها
و در صورت تمایل یک بزرگ‌نمایی آرام (--motion) تا تصویر ثابت به نظر نرسد.

صدا: بهتر است موسیقی را داخل خود اینستاگرام از کتابخانهٔ صدای آن اضافه کنی (مجاز است و
الگوریتم صداهای ترند را می‌شناسد). اگر صداگذاری خودت را داری، با --audio بده.

پیش‌نیاز: ffmpeg  (ویندوز: winget install ffmpeg   |   مک: brew install ffmpeg)

استفاده:
  python video.py spec.json --frames <پوشهٔ فریم‌ها> --out reel.mp4
  python video.py spec.json --frames slides --out reel.mp4 --skip-cover --motion --audio voice.m4a
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from fa_text import setup_stdout  # noqa: E402

FPS = 30
FADE = 0.25


def main():
    setup_stdout()
    ap = argparse.ArgumentParser(description="ساخت ویدیوی ریلز از فریم‌ها")
    ap.add_argument("spec")
    ap.add_argument("--frames", required=True, help="پوشهٔ 01.png، 02.png، ...")
    ap.add_argument("--out", required=True)
    ap.add_argument("--skip-cover", action="store_true", help="اسلاید reel-cover را در ویدیو نیاور")
    ap.add_argument("--motion", action="store_true", help="بزرگ‌نمایی آرام روی هر فریم")
    ap.add_argument("--audio", help="فایل صدا (اختیاری)")
    ap.add_argument("--default-dur", type=float, default=2.5)
    a = ap.parse_args()

    ff = shutil.which("ffmpeg")
    if not ff:
        print("ffmpeg پیدا نشد. ویندوز: winget install ffmpeg  (بعد ترمینال را ببند و دوباره باز کن)",
              file=sys.stderr)
        sys.exit(2)
    with open(a.spec, encoding="utf-8") as f:
        spec = json.load(f)

    inputs, durs = [], []
    for i, s in enumerate(spec["slides"], 1):
        if a.skip_cover and s.get("layout") == "reel-cover":
            continue
        p = os.path.join(a.frames, f"{i:02d}.png")
        if not os.path.exists(p):
            print(f"فریم پیدا نشد: {p}. اول render.py را اجرا کن.", file=sys.stderr)
            sys.exit(2)
        inputs.append(p)
        durs.append(float(s.get("dur", a.default_dur)))
    if not inputs:
        print("هیچ فریمی نیست", file=sys.stderr)
        sys.exit(2)

    cmd = [ff, "-y", "-hide_banner", "-loglevel", "error"]
    for p, d in zip(inputs, durs):
        # با zoompan ورودی نباید loop شود؛ zoompan خودش از یک تصویر d فریم می‌سازد
        cmd += (["-i", p] if a.motion else ["-loop", "1", "-t", f"{d:.2f}", "-i", p])
    if a.audio:
        cmd += ["-i", a.audio]

    chains, labels = [], []
    for i, d in enumerate(durs):
        frames = max(1, int(d * FPS))
        v = f"[{i}:v]scale=1080:1920,setsar=1,fps={FPS}"
        if a.motion:
            v = (f"[{i}:v]scale=1080:1920,setsar=1,zoompan=z='min(zoom+0.0005,1.05)':d={frames}"
                 f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1080x1920:fps={FPS}")
        v += f",fade=t=in:st=0:d={FADE},fade=t=out:st={max(0, d - FADE):.2f}:d={FADE},format=yuv420p[v{i}]"
        chains.append(v)
        labels.append(f"[v{i}]")
    chains.append("".join(labels) + f"concat=n={len(labels)}:v=1:a=0[vout]")
    cmd += ["-filter_complex", ";".join(chains), "-map", "[vout]"]
    if a.audio:
        cmd += ["-map", f"{len(inputs)}:a", "-c:a", "aac", "-b:a", "160k", "-shortest"]
    cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "20", "-r", str(FPS),
            "-movflags", "+faststart", a.out]

    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        print(r.stderr.decode("utf-8", "ignore")[-1500:], file=sys.stderr)
        sys.exit(r.returncode)
    total = sum(durs)
    print(f"ساخته شد: {a.out}  ·  {len(inputs)} فریم  ·  {total:.1f} ثانیه")
    if total > 90:
        print("هشدار: بیشتر از ۹۰ ثانیه است؛ برای ریلز آموزشی کوتاه، ۱۵ تا ۴۵ ثانیه معمولاً بهتر است.")


if __name__ == "__main__":
    main()
