#!/usr/bin/env python3
"""
video.py - ساخت ویدیوی ریلز ۱۰۸۰×۱۹۲۰ از spec.json: کلیپ‌های خودت، عکس‌ها، یا فریم‌های متنی،
با متن فارسی روی تصویر، صدای ضبط‌شدهٔ خودت و موسیقی.

هر اسلاید spec یک «بیت» است و یکی از این سه منبع را دارد:
  "clip": "media/a.mp4", "start": 3.5     تکه‌ای از ویدیوی خودت (برش و عمودی‌سازی خودکار)
  "photo": "media/shop.jpg", "focus": [.5,.4]   عکس، با بزرگ‌نمایی و حرکت آرام (Ken Burns)
  (هیچ‌کدام)                              فریم متنی که render.py ساخته (slides/NN.png)
و اگر title یا body دارد، روی کلیپ و عکس به‌شکل متن در کادر نیمه‌شفاف می‌نشیند
("text_pos": "top" | "center" | "bottom").

زمان هر بیت:
  "dur" در spec؛ یا با --voice صدای خودت و --sync:
    silence   صدا را در مکث‌ها تکه می‌کند و هر تکه را به یک بیت می‌دهد (فیلم‌نامه را خط‌به‌خط با
              مکث نیم‌ثانیه‌ای بخوان). اگر تعداد تکه‌ها با بیت‌ها جور نبود، نسبت dur ها را نگه می‌دارد.
    scale     dur ها را به نسبت کش می‌دهد تا با طول صدا یکی شود.

صدا:
  --voice voice.m4a        صدای راوی (گوشی، ضبط صدا، یا هر فایل صوتی که خودت ساخته‌ای)
  --music music.mp3        موسیقی زمینه (بی‌کلام؛ مطمئن شو حق استفاده‌اش را داری). زیر صدا آرام می‌شود.
  --keep-clip-audio        صدای خود کلیپ‌ها حفظ شود (وقتی صدا را با خود فیلم ضبط کرده‌ای)
بدون صدا هم می‌شود ساخت و موسیقی را داخل اینستاگرام گذاشت.

پیش‌نیاز: ffmpeg، و Pillow با raqm برای متن روی کلیپ و عکس.

استفاده:
  python video.py spec.json --frames slides --out reel.mp4 --skip-cover
  python video.py spec.json --frames slides --out reel.mp4 --voice media/voice.m4a --sync silence --music media/bg.mp3
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import hashlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from fa_text import setup_stdout  # noqa: E402

FPS = 30
W, H = 1080, 1920
FADE = 0.2


def run(cmd, what):
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        print(f"خطا در {what}:\n" + r.stderr.decode("utf-8", "ignore")[-1500:], file=sys.stderr)
        sys.exit(r.returncode or 1)
    return r


def duration(ffprobe, path):
    r = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def speech_segments(ff, path, noise="-32dB", min_sil=0.35):
    r = subprocess.run([ff, "-hide_banner", "-i", path, "-af", f"silencedetect=noise={noise}:d={min_sil}",
                        "-f", "null", "-"], capture_output=True, text=True)
    log = r.stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", log)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", log)
    total = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0
    # تکه‌های گفتار = فاصلهٔ بین سکوت‌ها
    segs, cur = [], 0.0
    for s, e in zip(starts, ends + [total] * (len(starts) - len(ends))):
        if s - cur > 0.25:
            segs.append((cur, s))
        cur = e
    if total - cur > 0.25:
        segs.append((cur, total))
    return segs, total


def resolve(path, base):
    """مسیر نسبی را اول نسبت به پوشهٔ spec و بعد نسبت به پوشهٔ جاری پیدا می‌کند."""
    if os.path.isabs(path):
        cands = [path]
    else:
        cands = [os.path.join(base, path), os.path.abspath(path)]
    for p in cands:
        if os.path.exists(p):
            return p
    print("فایل پیدا نشد: " + "  یا  ".join(cands), file=sys.stderr)
    sys.exit(2)


def main():
    setup_stdout()
    ap = argparse.ArgumentParser(description="ساخت ویدیوی ریلز")
    ap.add_argument("spec")
    ap.add_argument("--frames", help="پوشهٔ فریم‌های render.py؛ فقط وقتی مرورگر نیست لازم است")
    ap.add_argument("--out", required=True)
    ap.add_argument("--page", help="پوشهٔ پیج (رنگ برند برای متن روی کلیپ)")
    ap.add_argument("--skip-cover", action="store_true", help="اسلاید reel-cover در ویدیو نیاید")
    ap.add_argument("--static", action="store_true", help="بدون موشن مرورگر (فریم ثابت با بزرگ‌نمایی آرام)")
    ap.add_argument("--motion", action="store_true", help=argparse.SUPPRESS)  # سازگاری با نسخهٔ قبل
    ap.add_argument("--voice", help="فایل صدای راوی")
    ap.add_argument("--sync", choices=["silence", "scale", "none"], default="silence")
    ap.add_argument("--music", help="موسیقی زمینه")
    ap.add_argument("--music-vol", type=float, default=0.12)
    ap.add_argument("--keep-clip-audio", action="store_true")
    ap.add_argument("--default-dur", type=float, default=2.5)
    ap.add_argument("--budget", type=float, default=0,
                    help="حداکثر ثانیه برای این اجرا؛ اگر تمام نشد با کد ۱۰ خارج می‌شود و اجرای بعدی ادامه می‌دهد")
    a = ap.parse_args()

    ff, fp = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ff or not fp:
        print("ffmpeg پیدا نشد.", file=sys.stderr)
        sys.exit(2)
    with open(a.spec, encoding="utf-8") as f:
        spec = json.load(f)
    base = os.path.dirname(os.path.abspath(a.spec))

    beats = []
    for i, s in enumerate(spec["slides"], 1):
        if a.skip_cover and s.get("layout") == "reel-cover":
            continue
        beats.append((i, s))
    if not beats:
        print("هیچ بیتی نیست", file=sys.stderr)
        sys.exit(2)
    durs = [float(s.get("dur", a.default_dur)) for _, s in beats]

    voice_len = 0.0
    if a.voice:
        vpath = resolve(a.voice, base)
        voice_len = duration(fp, vpath)
        vmeta = None
        vjson = os.path.splitext(vpath)[0] + ".json"
        if a.sync != "none" and os.path.exists(vjson):
            try:
                with open(vjson, encoding="utf-8") as f:
                    vmeta = json.load(f)
            except (ValueError, OSError):
                vmeta = None
        if vmeta and len(vmeta.get("beats", [])) == len(beats):
            # زمان‌بندی دقیقِ tts.py: هر بیت از شروع جملهٔ خودش تا شروع جملهٔ بعدی
            tb = vmeta["beats"]
            starts = [0.0] + [max(0.0, tb[k]["start"] - 0.08) for k in range(1, len(tb))]
            ends = starts[1:] + [tb[-1]["end"] + 0.6]
            durs = [max(0.6, e - s) for s, e in zip(starts, ends)]
            print(f"هماهنگ با زمان‌بندی گوینده: {len(tb)} جمله ← {len(beats)} بیت")
        elif vmeta:
            print(f"هشدار: voice.json {len(vmeta.get('beats', []))} جمله دارد ولی ویدیو {len(beats)} بیت؛ "
                  f"--skip-cover در tts.py و video.py باید یکی باشد. هماهنگی با مکث‌ها انجام می‌شود.")
        if vmeta and len(vmeta.get("beats", [])) == len(beats):
            pass
        elif a.sync == "silence":
            segs, total = speech_segments(ff, vpath)
            if len(segs) == len(beats):
                starts = [0.0] + [segs[k][0] - 0.1 for k in range(1, len(segs))]
                ends = starts[1:] + [total + 0.4]
                durs = [max(0.6, e - s) for s, e in zip(starts, ends)]
                print(f"هماهنگ با صدا: {len(segs)} تکهٔ گفتار ← {len(beats)} بیت")
            else:
                k = (voice_len + 0.4) / sum(durs)
                durs = [d * k for d in durs]
                print(f"هشدار: {len(segs)} تکهٔ گفتار پیدا شد ولی {len(beats)} بیت داریم؛ زمان‌ها به نسبت "
                      f"کش آمدند. برای هماهنگی دقیق، هر خط را جدا با مکث بخوان یا dur ها را درست کن.")
        elif a.sync == "scale":
            k = (voice_len + 0.4) / sum(durs)
            durs = [d * k for d in durs]

    # موشن: اگر مرورگر هست، هر بیت متنی و هر متن روی کلیپ/عکس انیمیشن می‌گیرد
    browser = None
    if not a.static:
        try:
            import studio
            exe, kind = studio.find_browser()
            if exe:
                import design
                import render as R
                brand = R.load_brand(a.page, spec.get("brand"))
                R.setup_fonts(a.page)
                browser = studio.Browser(exe, kind)
        except Exception as e:  # بدون موشن ادامه می‌دهیم
            print(f"موشن در دسترس نیست ({e}); ویدیو ساده ساخته می‌شود.")
            browser = None
    overlays = {}
    if browser is None and any(s.get("clip") or s.get("photo") for _, s in beats):
        import render as R
        overlays = R.render_overlays(a.spec, a.page, os.path.join(tempfile.gettempdir(), "igfa-ov"))

    tmp = tempfile.mkdtemp(prefix="igfa-vid-")
    # بیت‌های ساخته‌شده در پوشهٔ موقت می‌مانند تا اجرای بعدی (با --budget) ادامه دهد
    parts = os.path.join(tempfile.gettempdir(), "igfa-parts-" + hashlib.md5(os.path.abspath(a.out).encode()).hexdigest()[:10])
    os.makedirs(parts, exist_ok=True)
    t_start = time.time()
    ctx = {"type": "reel", "base": base, "key": spec.get("title", "x")}

    def motion_html(i, s, overlay):
        hp = os.path.join(tmp, f"m{i:02d}.html")
        html_text = design.overlay_html(s, brand, "motion") if overlay else \
            design.frame_html(s, i, len(spec["slides"]), "reel", brand, ctx, "motion")
        with open(hp, "w", encoding="utf-8") as f:
            f.write(html_text)
        return hp

    def feed(proc, hp, d, transparent):
        """فریم‌ها را از مرورگر به ffmpeg می‌دهد. پس از جاافتادن حرکت‌ها، هر ۳ فریم یک عکس."""
        browser.open(hp, (W, H), transparent)
        n = max(1, round(d * FPS))
        last = None
        for k in range(n):
            t = k / FPS
            if last is None or t <= 2.2 or k % 3 == 0:
                browser.eval(f"window.__seek({t:.4f})", await_promise=False)
                last = browser.screenshot("png" if transparent else "jpeg", 90)
            proc.stdin.write(last)
        proc.stdin.close()
        if proc.wait() != 0:
            print(proc.stderr.read().decode("utf-8", "ignore")[-1200:], file=sys.stderr)
            sys.exit(1)

    seg_files, audio_parts = [], []
    brand_sig = json.dumps(brand, sort_keys=True, ensure_ascii=False) if browser is not None else ""

    def clip_audio_part(i, s, d):
        wav = os.path.join(tmp, f"seg{i:02d}.wav")
        ok = False
        if s.get("clip"):
            acmd = [ff, "-y", "-hide_banner", "-loglevel", "error", "-ss", str(s.get("start", 0)), "-t", f"{d:.3f}",
                    "-i", resolve(s["clip"], base), "-f", "lavfi", "-t", f"{d:.3f}", "-i", "anullsrc=r=48000:cl=stereo",
                    "-filter_complex", "[0:a]aresample=48000,aformat=channel_layouts=stereo[c];[c][1:a]amix=inputs=2:"
                    f"duration=longest:normalize=0,atrim=0:{d:.3f}[a]", "-map", "[a]", wav]
            ok = subprocess.run(acmd, capture_output=True).returncode == 0
        if not ok:  # کلیپ بی‌صدا، یا بیت غیرکلیپ
            run([ff, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-t", f"{d:.3f}", "-i",
                 "anullsrc=r=48000:cl=stereo", wav], "سکوت")
        return wav
    for (i, s), d in zip(beats, durs):
        sig = hashlib.md5(json.dumps([s, round(d, 3), a.static, browser is not None, brand_sig], sort_keys=True,
                                     ensure_ascii=False).encode()).hexdigest()[:10]
        out = os.path.join(parts, f"seg{i:02d}-{sig}.mp4")
        if os.path.exists(out):
            seg_files.append(out)
            print(f"  ✓ بیت {i}: از قبل ساخته شده")
            if a.keep_clip_audio:
                audio_parts.append(clip_audio_part(i, s, d))
            continue
        if a.budget and time.time() - t_start > a.budget:
            if browser is not None:
                browser.close()
            print(f"CONTINUE: {len(seg_files)} از {len(beats)} بیت ساخته شد؛ همین دستور را دوباره اجرا کن.")
            sys.exit(10)
        frames = max(1, round(d * FPS))
        fade = (f"fade=t=in:st=0:d={FADE},fade=t=out:st={max(0, d - FADE):.3f}:d={FADE}")
        tmp_out = out + ".tmp.mp4"
        enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(FPS), "-pix_fmt", "yuv420p", tmp_out]
        has_text = bool(s.get("title") or s.get("body"))
        ov = overlays.get(i)
        motion_ov = browser is not None and has_text and (s.get("clip") or s.get("photo"))
        q = [ff, "-y", "-hide_banner", "-loglevel", "error"]
        if s.get("clip") or s.get("photo"):
            if s.get("clip"):
                src = resolve(s["clip"], base)
                q += ["-ss", str(s.get("start", 0)), "-t", f"{d:.3f}", "-i", src]
                vf = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps={FPS}"
                      f",format=yuv420p[b]")
            else:
                src = resolve(s["photo"], base)
                from PIL import Image, ImageOps
                im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
                im = ImageOps.fit(im, (int(W * 1.25), int(H * 1.25)), Image.LANCZOS,
                                  centering=tuple(s.get("focus", (0.5, 0.5))))
                pp = os.path.join(tmp, f"photo{i:02d}.jpg")
                im.save(pp, quality=92)
                zoom = "min(zoom+0.0010,1.12)" if s.get("move", "in") == "in" else \
                    "if(eq(on,1),1.12,max(zoom-0.0010,1))"
                q += ["-i", pp]
                vf = (f"[0:v]zoompan=z='{zoom}':d={frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                      f":s={W}x{H}:fps={FPS},setsar=1,format=yuv420p[b]")
            if motion_ov:
                q += ["-f", "image2pipe", "-framerate", str(FPS), "-c:v", "png", "-i", "-"]
                vf += f";[1:v]format=rgba[o];[b][o]overlay=0:0:eof_action=repeat,{fade}[v]"
            elif ov:
                q += ["-i", ov]
                vf += f";[b][1:v]overlay=0:0,{fade}[v]"
            else:
                vf += f";[b]{fade}[v]"
            q += ["-filter_complex", vf, "-map", "[v]", "-frames:v", str(frames), "-an"] + enc
            if motion_ov:
                proc = subprocess.Popen(q, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
                feed(proc, motion_html(i, s, True), d, True)
            else:
                run(q, f"بیت {i}")
        elif browser is not None:
            q += ["-f", "image2pipe", "-framerate", str(FPS), "-c:v", "mjpeg", "-i", "-",
                  "-vf", f"scale={W}:{H},setsar=1,{fade}", "-frames:v", str(frames), "-an"] + enc
            proc = subprocess.Popen(q, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
            feed(proc, motion_html(i, s, False), d, False)
        else:
            if not a.frames:
                print("بدون مرورگر، --frames (خروجی render.py) لازم است.", file=sys.stderr)
                sys.exit(2)
            src = os.path.join(a.frames, f"{i:02d}.png")
            if not os.path.exists(src):
                print(f"فریم پیدا نشد: {src}. اول render.py را اجرا کن.", file=sys.stderr)
                sys.exit(2)
            q += ["-i", src, "-filter_complex",
                  f"[0:v]scale={W}:{H},setsar=1,zoompan=z='min(zoom+0.0005,1.05)':d={frames}"
                  f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS},format=yuv420p,{fade}[v]",
                  "-map", "[v]", "-frames:v", str(frames), "-an"] + enc
            run(q, f"بیت {i}")
        os.replace(tmp_out, out)
        seg_files.append(out)
        if a.keep_clip_audio:
            audio_parts.append(clip_audio_part(i, s, d))
        kind = "کلیپ" if s.get("clip") else "عکس" if s.get("photo") else "متن"
        print(f"  ✓ بیت {i}: {kind}، {d:.1f} ثانیه{' + متن' if (ov or motion_ov) else ''}"
              f"{' (موشن)' if browser is not None and (motion_ov or not (s.get('clip') or s.get('photo'))) else ''}")
    if browser is not None:
        browser.close()

    lst = os.path.join(tmp, "list.txt")
    with open(lst, "w", encoding="utf-8") as f:
        for p in seg_files:
            f.write(f"file '{p}'\n")
    joined = os.path.join(tmp, "joined.mp4")
    run([ff, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy",
         joined], "چسباندن بیت‌ها")
    total = sum(durs)
    clip_audio = None
    if a.keep_clip_audio:
        alst = os.path.join(tmp, "alist.txt")
        with open(alst, "w", encoding="utf-8") as f:
            for p in audio_parts:
                f.write(f"file '{p}'\n")
        clip_audio = os.path.join(tmp, "clipaudio.wav")
        run([ff, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", alst, clip_audio],
            "صدای کلیپ‌ها")

    if a.voice or a.music or clip_audio:
        cmd = [ff, "-y", "-hide_banner", "-loglevel", "error", "-i", joined]
        filt, n = [], 1
        labels = []
        if clip_audio:
            cmd += ["-i", clip_audio]
            labels.append(f"[{n}:a]")
            n += 1
        if a.voice:
            cmd += ["-i", resolve(a.voice, base)]
            filt.append(f"[{n}:a]aresample=48000,loudnorm=I=-16:TP=-1.5:LRA=11[vo]")
            labels.append("[vo]")
            n += 1
        if a.music:
            cmd += ["-stream_loop", "-1", "-i", resolve(a.music, base)]
            vol = a.music_vol if (a.voice or a.keep_clip_audio) else 0.6
            filt.append(f"[{n}:a]aresample=48000,volume={vol},afade=t=in:st=0:d=0.6,"
                        f"afade=t=out:st={max(0, total - 1.2):.2f}:d=1.2[mu]")
            labels.append("[mu]")
            n += 1
        # apad: اگر صدا کوتاه‌تر از تصویر است، با سکوت پر شود تا -shortest انتهای ویدیو را نبُرد
        filt.append("".join(labels) + f"amix=inputs={len(labels)}:duration=longest:normalize=0,"
                    f"apad,atrim=0:{total:.3f}[a]")
        cmd += ["-filter_complex", ";".join(filt), "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac",
                "-b:a", "160k", "-shortest", "-movflags", "+faststart", a.out]
        run(cmd, "صداگذاری")
    else:
        run([ff, "-y", "-hide_banner", "-loglevel", "error", "-i", joined, "-c", "copy", "-movflags", "+faststart",
             a.out], "خروجی")
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(parts, ignore_errors=True)
    print(f"ساخته شد: {a.out}  ·  {len(beats)} بیت  ·  {total:.1f} ثانیه"
          + (f"  ·  صدا {voice_len:.1f} ثانیه" if a.voice else ""))
    if total > 90:
        print("هشدار: بیشتر از ۹۰ ثانیه است؛ ریلز آموزشی کوتاه معمولاً ۱۵ تا ۴۵ ثانیه بهتر است.")


if __name__ == "__main__":
    main()
