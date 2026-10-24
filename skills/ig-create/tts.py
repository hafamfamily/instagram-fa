#!/usr/bin/env python3
"""
tts.py - گوینده‌ی فارسی رایگان برای ریلز و استوری.

هر بیت (اسلاید) spec جدا خوانده می‌شود، با مکث کوتاه بین بیت‌ها، و زمان دقیق هر بیت در کنار
فایل صدا ذخیره می‌شود (voice.json) تا video.py تصویر را دقیقاً با صدا هماهنگ کند.

موتورها (رایگان):
  edge    صدای عصبی مایکروسافت (fa-IR-DilaraNeural زن، fa-IR-FaridNeural مرد)؛ طبیعی‌ترین.
          نصب: pip install edge-tts   ·  به اینترنت نیاز دارد (سرویس رسمی و مستند برای این کار نیست؛
          ممکن است روزی قطع یا محدود شود).
  piper   آفلاین، روی خود کامپیوتر (fa_IR-amir-medium مرد، fa_IR-gyro-medium). کیفیت کمتر ولی همیشه
          در دسترس. نصب: pip install piper-tts  ·  مدل (~۶۰ مگابایت) بار اول خودکار دانلود می‌شود.
          مجوز صدای amir فقط استفادهٔ غیرتجاری است؛ پیش از استفادهٔ تجاری، مجوز هر صدا را ببین.
  auto    اول edge، اگر نبود piper.

متن هر بیت: فیلد "say" در اسلاید؛ اگر نبود، title و body بدون علامت‌های ** . عددها به حروف
خوانده می‌شوند («۲ دقیقه» ← «دو دقیقه»، «۴۰٪» ← «چهل درصد»).

استفاده:
  python tts.py <محتوا>/spec.json --out <محتوا>/media/voice.wav [--voice dilara] [--rate +5%] [--skip-cover]
  python tts.py --text "سلام، این یک تست است" --out test.wav
  python tts.py --voices          صداهای موجود
  python tts.py --check           کدام موتور روی این سیستم آماده است

بعد: python video.py spec.json --out reel.mp4 --voice <محتوا>/media/voice.wav
"""

import argparse
import asyncio
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.request
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from fa_text import setup_stdout  # noqa: E402

VOICES = {
    "dilara": ("edge", "fa-IR-DilaraNeural", "زن، طبیعی (edge)"),
    "farid": ("edge", "fa-IR-FaridNeural", "مرد، طبیعی (edge)"),
    "amir": ("piper", "fa_IR-amir-medium", "مرد، آفلاین (piper؛ فقط غیرتجاری)"),
    "gyro": ("piper", "fa_IR-gyro-medium", "آفلاین (piper)"),
}
PIPER_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/fa/fa_IR/{spk}/medium/{name}.onnx{ext}"
SR = 48000

# ---------- عدد به حروف ----------

ONES = ["", "یک", "دو", "سه", "چهار", "پنج", "شش", "هفت", "هشت", "نه"]
TEENS = ["ده", "یازده", "دوازده", "سیزده", "چهارده", "پانزده", "شانزده", "هفده", "هجده", "نوزده"]
TENS = ["", "", "بیست", "سی", "چهل", "پنجاه", "شصت", "هفتاد", "هشتاد", "نود"]
HUNDS = ["", "صد", "دویست", "سیصد", "چهارصد", "پانصد", "ششصد", "هفتصد", "هشتصد", "نهصد"]
SCALES = ["", "هزار", "میلیون", "میلیارد", "تریلیون"]


def _three(n):
    parts = []
    h, r = divmod(n, 100)
    if h:
        parts.append(HUNDS[h])
    if 10 <= r < 20:
        parts.append(TEENS[r - 10])
    else:
        t, o = divmod(r, 10)
        if t:
            parts.append(TENS[t])
        if o:
            parts.append(ONES[o])
    return " و ".join(parts)


def num_words(n):
    if n == 0:
        return "صفر"
    if n < 0:
        return "منفی " + num_words(-n)
    groups = []
    k = 0
    while n:
        n, g = divmod(n, 1000)
        if g:
            w = _three(g)
            if k == 1 and g == 1:
                w = ""          # «هزار» نه «یک هزار»
            groups.append((w + " " + SCALES[k]).strip())
        k += 1
    return " و ".join(reversed(groups))


DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def say_numbers(text):
    t = text.translate(DIGITS)
    t = re.sub(r"(?<=\d)[,٬](?=\d{3})", "", t)

    def dec(m):
        a, b = m.group(1), m.group(2)
        return f"{num_words(int(a))} ممیز {num_words(int(b))}"

    t = re.sub(r"(\d+)[.٫](\d+)\s*[%٪]", lambda m: dec(m) + " درصد", t)
    t = re.sub(r"(\d+)\s*[%٪]", lambda m: num_words(int(m.group(1))) + " درصد", t)
    t = re.sub(r"(\d{1,2}):(\d{2})", lambda m: num_words(int(m.group(1))) +
               ("" if m.group(2) == "00" else " و " + num_words(int(m.group(2)))), t)
    t = re.sub(r"(\d+)[.٫](\d+)", dec, t)
    t = re.sub(r"\d+", lambda m: num_words(int(m.group(0))) if len(m.group(0)) <= 15 else m.group(0), t)
    return t


def clean(text):
    t = re.sub(r"\*\*(.+?)\*\*", r"\1", text or "")
    t = re.sub(r"[«»\"“”]", "", t)
    t = re.sub(r"[\U0001F300-\U0001FAFF☀-➿️]", "", t)
    t = re.sub(r"\s*\n+\s*", "، ", t)
    t = re.sub(r"\s+", " ", t).strip(" ،")
    return say_numbers(t)


def beat_text(s):
    if s.get("say") is not None:
        return clean(s["say"])
    parts = [s.get("title", ""), s.get("body", "")]
    return clean("، ".join(p for p in parts if p))


# ---------- موتورها ----------

class EngineError(Exception):
    pass


def has_edge():
    try:
        import edge_tts  # noqa: F401
        return True
    except ImportError:
        return False


def has_piper():
    try:
        import piper  # noqa: F401
        return True
    except ImportError:
        return False


def ffmpeg():
    ff = shutil.which("ffmpeg")
    if not ff:
        raise EngineError("ffmpeg پیدا نشد (ویندوز: winget install ffmpeg).")
    return ff


def to_wav(src, dst):
    r = subprocess.run([ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", src, "-ac", "1", "-ar", str(SR),
                        "-sample_fmt", "s16", dst], capture_output=True)
    if r.returncode != 0:
        raise EngineError("تبدیل صدا نشد: " + r.stderr.decode("utf-8", "ignore")[-300:])


def synth_edge(text, voice, rate, pitch, out_wav):
    try:
        import edge_tts
    except ImportError:
        raise EngineError("edge-tts نصب نیست: pip install edge-tts")
    tmp = out_wav + ".mp3"

    async def go():
        await edge_tts.Communicate(text, voice, rate=rate, pitch=pitch).save(tmp)
    last = None
    for _ in range(3):
        try:
            asyncio.run(go())
            break
        except Exception as e:  # شبکه یا سرویس
            last = e
    else:
        raise EngineError(f"edge-tts جواب نداد ({last}). اینترنت/فیلترشکن را بررسی کن یا --engine piper.")
    to_wav(tmp, out_wav)
    os.remove(tmp)


def piper_model(name, cache):
    os.makedirs(cache, exist_ok=True)
    onnx = os.path.join(cache, name + ".onnx")
    spk = name.split("-")[1]
    for ext in ("", ".json"):
        p = onnx + ext
        if os.path.exists(p) and os.path.getsize(p) > 0:
            continue
        url = PIPER_URL.format(spk=spk, name=name, ext=ext)
        print(f"دانلود مدل {name}{ext} (یک بار)…", file=sys.stderr)
        try:
            with urllib.request.urlopen(url, timeout=120) as r, open(p + ".part", "wb") as f:
                shutil.copyfileobj(r, f)
            os.replace(p + ".part", p)
        except Exception as e:
            raise EngineError(f"دانلود مدل piper نشد ({e}). فایل‌ها را دستی از {url} بگیر و در {cache} بگذار.")
    return onnx


def synth_piper(text, name, rate, out_wav, cache):
    try:
        from piper import PiperVoice
    except ImportError:
        raise EngineError("piper نصب نیست: pip install piper-tts")
    voice = PiperVoice.load(piper_model(name, cache))
    tmp = out_wav + ".raw.wav"
    speed = 1.0
    m = re.match(r"([+-]\d+)%", rate or "")
    if m:
        speed = max(0.5, min(2.0, 1 + int(m.group(1)) / 100))
    with wave.open(tmp, "wb") as wf:
        if hasattr(voice, "synthesize_wav"):          # piper 1.3+
            try:
                from piper import SynthesisConfig
                voice.synthesize_wav(text, wf, syn_config=SynthesisConfig(length_scale=1 / speed))
            except ImportError:
                voice.synthesize_wav(text, wf)
        else:                                          # piper-tts 1.2
            voice.synthesize(text, wf, length_scale=1 / speed)
    to_wav(tmp, out_wav)
    os.remove(tmp)


def synth_tone(text, out_wav):
    """فقط برای تست: بوق با طول متناسب با متن."""
    dur = max(0.6, len(text) * 0.06)
    with wave.open(out_wav, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        frames = b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 220 * i / SR)))
                          for i in range(int(dur * SR)))
        wf.writeframes(frames)


def pick(engine, voice):
    if voice:
        if voice not in VOICES:
            raise EngineError(f"صدای ناشناخته «{voice}». صداها: {', '.join(VOICES)}")
        eng = VOICES[voice][0]
        if engine not in ("auto", eng):
            raise EngineError(f"صدای {voice} مال موتور {eng} است، نه {engine}.")
        return eng, VOICES[voice][1]
    if engine == "tone":
        return "tone", ""
    if engine in ("auto", "edge") and (engine == "edge" or has_edge()):
        return "edge", VOICES["dilara"][1]
    if engine in ("auto", "piper") and (engine == "piper" or has_piper()):
        return "piper", VOICES["amir"][1]
    raise EngineError("هیچ موتور گوینده‌ای نصب نیست. یکی را نصب کن:\n"
                      "  pip install edge-tts      (طبیعی‌تر، آنلاین)\n"
                      "  pip install piper-tts     (آفلاین)")


def synth(text, eng, name, rate, pitch, out_wav, cache):
    if eng == "edge":
        synth_edge(text, name, rate, pitch, out_wav)
    elif eng == "piper":
        synth_piper(text, name, rate, out_wav, cache)
    else:
        synth_tone(text, out_wav)


# ---------- ساخت ----------

def wav_len(p):
    with wave.open(p) as w:
        return w.getnframes() / w.getframerate()


def trim_silence(src, dst):
    """سکوت ابتدا و انتهای هر تکه را برمی‌دارد تا مکث‌ها فقط همان gap باشند."""
    ff = shutil.which("ffmpeg")
    if not ff:
        shutil.copy(src, dst)
        return
    flt = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,"
           "areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.08,areverse")
    r = subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error", "-i", src, "-af", flt, "-ar", str(SR),
                        "-ac", "1", "-sample_fmt", "s16", dst], capture_output=True)
    if r.returncode != 0 or wav_len(dst) < 0.2:
        shutil.copy(src, dst)


def build(texts, eng, name, rate, pitch, out, gap, lead, cache):
    tmp = tempfile.mkdtemp(prefix="igfa-tts-")
    try:
        pcm, beats, t = b"", [], lead
        pcm += b"\x00\x00" * int(lead * SR)
        for k, text in enumerate(texts, 1):
            if not text:
                beats.append({"start": round(t, 3), "end": round(t, 3), "text": ""})
                continue
            raw = os.path.join(tmp, f"{k}.wav")
            cut = os.path.join(tmp, f"{k}c.wav")
            synth(text, eng, name, rate, pitch, raw, cache)
            trim_silence(raw, cut)
            with wave.open(cut) as w:
                if w.getframerate() != SR or w.getnchannels() != 1:
                    to_wav(cut, raw)
                    cut = raw
            with wave.open(cut) as w:
                data = w.readframes(w.getnframes())
            d = len(data) / 2 / SR
            beats.append({"start": round(t, 3), "end": round(t + d, 3), "text": text})
            print(f"  ✓ بیت {k}: {d:.1f} ثانیه  «{text[:40]}{'…' if len(text) > 40 else ''}»")
            pcm += data + b"\x00\x00" * int(gap * SR)
            t += d + gap
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        wav_out = out if out.lower().endswith(".wav") else os.path.join(tmp, "all.wav")
        with wave.open(wav_out, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(pcm)
        if wav_out != out:
            r = subprocess.run([ffmpeg(), "-y", "-hide_banner", "-loglevel", "error", "-i", wav_out, out],
                               capture_output=True)
            if r.returncode != 0:
                raise EngineError("ذخیرهٔ خروجی نشد: " + r.stderr.decode("utf-8", "ignore")[-300:])
        return beats, t
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    setup_stdout()
    ap = argparse.ArgumentParser(description="گوینده‌ی فارسی")
    ap.add_argument("spec", nargs="?")
    ap.add_argument("--text")
    ap.add_argument("--out")
    ap.add_argument("--engine", choices=["auto", "edge", "piper", "tone"], default="auto")
    ap.add_argument("--voice", help="dilara | farid | amir | gyro")
    ap.add_argument("--rate", default="+0%", help="سرعت، مثلاً +10% یا -5%")
    ap.add_argument("--pitch", default="+0Hz", help="فقط edge، مثلاً -2Hz")
    ap.add_argument("--gap", type=float, default=0.45, help="مکث بین بیت‌ها (ثانیه)")
    ap.add_argument("--lead", type=float, default=0.15, help="سکوت اول فایل")
    ap.add_argument("--skip-cover", action="store_true", help="مثل video.py: اسلاید reel-cover خوانده نشود")
    ap.add_argument("--cache", help="پوشهٔ مدل‌های piper (پیش‌فرض ~/.instagram-fa/piper)")
    ap.add_argument("--voices", action="store_true")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()

    if a.voices:
        for k, (eng, name, desc) in VOICES.items():
            print(f"  {k:<7} {name:<22} {desc}")
        return
    if a.check:
        print(f"edge-tts: {'نصب است' if has_edge() else 'نصب نیست (pip install edge-tts)'}")
        print(f"piper:    {'نصب است' if has_piper() else 'نصب نیست (pip install piper-tts)'}")
        print(f"ffmpeg:   {shutil.which('ffmpeg') or 'نیست'}")
        return
    if not a.out or not (a.spec or a.text):
        ap.error("spec یا --text، و --out لازم است")
    cache = a.cache or os.path.join(os.path.expanduser("~"), ".instagram-fa", "piper")
    try:
        eng, name = pick(a.engine, a.voice)
        if a.text:
            texts, skip = [clean(a.text)], False
        else:
            with open(a.spec, encoding="utf-8") as f:
                spec = json.load(f)
            slides = [s for s in spec["slides"] if not (a.skip_cover and s.get("layout") == "reel-cover")]
            texts, skip = [beat_text(s) for s in slides], a.skip_cover
        print(f"گوینده: {eng} {name}".strip())
        beats, total = build(texts, eng, name, a.rate, a.pitch, a.out, a.gap, a.lead, cache)
    except EngineError as e:
        print(f"خطا: {e}", file=sys.stderr)
        sys.exit(1)
    meta = {"engine": eng, "voice": name, "skip_cover": skip, "gap": a.gap, "total": round(total, 3),
            "beats": beats}
    with open(os.path.splitext(a.out)[0] + ".json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"ساخته شد: {a.out}  ·  {len(beats)} بیت  ·  {total:.1f} ثانیه")
    if eng == "piper" and "amir" in name:
        print("یادآوری: مجوز صدای amir فقط برای استفادهٔ غیرتجاری است.")


if __name__ == "__main__":
    main()
