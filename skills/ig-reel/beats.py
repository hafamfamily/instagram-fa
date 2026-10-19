#!/usr/bin/env python3
"""
beats.py - تبدیل متن ریلز به جدول زمان‌بندی (بیت‌شیت) پیش از ضبط.

بر پایهٔ beats.py از instagram-agent-skill (Jake Schincariol, MIT)، بازنویسی برای فارسی.

زمان هر خط را از تعداد کلمه‌ها تخمین می‌زند، روی هم می‌چیند و چهار چیزی را که
ریلز را در تدوین می‌کشد علامت می‌زند:
  ۱. قلابی که از ۳ ثانیه بیشتر طول بکشد
  ۲. یک بیت (تکه) که آن‌قدر طول بکشد که بیننده برود (بیش از ۴ ثانیه بدون تغییر تصویر)
  ۳. چند بیت پشت‌سرهم بدون هیچ چیز مشخص (عدد، اسم، مثال)
  ۴. فاصله با زمان هدف، و نبودِ «حلقه» (برگشت جملهٔ آخر به قلاب)

هر خط فایل یک بیت است. خط اول قلاب است و خط آخر دعوت به اقدام (CTA).
سرعت گفتار پیش‌فرض ۱۵۵ کلمه در دقیقه است؛ با --wpm سرعت خودت را بده.

استفاده:
  python beats.py script.txt --target 30
  python beats.py script.txt --wpm 170 --json
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fa_text import setup_stdout, words, low, numbers, latin_names  # noqa: E402

HOOK_WINDOW = 3.5
MAX_BEAT = 4.0
ABSTRACT_RUN = 3

STOPWORDS = set("""
و یا که از به با در برای این اون آن را رو هم یه یک تو من ما شما اونا آنها او
است هست بود شد شده کرد کن کنم کنی کنه می نمی هر چی چه چرا کی کجا اگه اگر ولی اما
پس تا دیگه خیلی همه همین بعد قبل روی توی سر بر هیچ بی باید نباید داره داری دارم
the a an and or of to in on for with is are you i
""".split())


def tc(seconds):
    m, s = divmod(seconds, 60)
    return f"{int(m)}:{s:04.1f}"


def is_concrete(text):
    if numbers(text) or latin_names(text):
        return True
    return any(low(w) in {"تومن", "تومان", "درصد", "دلار", "میلیون", "هزار"} for w in words(text))


def content_words(text):
    return {low(w) for w in words(text) if low(w) not in STOPWORDS and len(w) > 2}


def build(lines, wpm):
    wps = wpm / 60.0
    beats, t = [], 0.0
    for i, line in enumerate(lines):
        n = len(words(line))
        dur = max(0.8, n / wps + (0 if i == 0 else 0.25))  # مکث کوتاه بین جمله‌ها
        role = "قلاب" if i == 0 else ("CTA" if i == len(lines) - 1 and len(lines) > 2 else "")
        beats.append({"start": round(t, 1), "dur": round(dur, 1), "role": role,
                      "text": line, "words": n, "concrete": is_concrete(line)})
        t += dur
    return beats, t


def problems(beats, total, target):
    out = []
    if beats and beats[0]["dur"] > HOOK_WINDOW:
        out.append(f"قلاب {beats[0]['dur']} ثانیه طول می‌کشد. باید زیر {HOOK_WINDOW} ثانیه باشد؛ کوتاهش کن.")
    for i, b in enumerate(beats, 1):
        if b["dur"] > MAX_BEAT:
            out.append(f"بیت {i} {b['dur']} ثانیه است. یا جمله را دو تکه کن، یا وسطش تصویر/متن روی صفحه را عوض کن. "
                       "تصویر ثابت جایی است که بیننده می‌رود.")
    run = 0
    for i, b in enumerate(beats, 1):
        run = 0 if b["concrete"] else run + 1
        if run == ABSTRACT_RUN:
            out.append(f"بیت‌های {i - ABSTRACT_RUN + 1} تا {i} هیچ عدد، اسم یا مثال مشخصی ندارند. یکی‌شان را ملموس کن.")
    if len(beats) > 2:
        shared = content_words(beats[0]["text"]) & content_words(beats[-1]["text"])
        if shared:
            out.append(f"حلقه: جملهٔ آخر «{'، '.join(sorted(shared)[:3])}» را از قلاب تکرار می‌کند. "
                       "بازدید دوباره رایگان است.")
        else:
            out.append("حلقه ندارد: جملهٔ آخر به قلاب برنمی‌گردد. اگر بتوانی آخر را به اول وصل کنی، "
                       "بیننده ویدیو را دوباره می‌بیند.")
    if target:
        diff = total - target
        if diff > 2:
            out.append(f"{diff:.1f} ثانیه بیشتر از هدف. حدود {round(diff * 2.6)} کلمه کم کن.")
        elif diff < -2:
            out.append(f"{-diff:.1f} ثانیه کمتر از هدف. یا {round(-diff * 2.6)} کلمه اضافه کن یا کوتاه بساز؛ "
                       "کوتاه معمولاً درست‌تر است.")
    return out


def main():
    setup_stdout()
    ap = argparse.ArgumentParser(description="بیت‌شیت ریلز")
    ap.add_argument("input", nargs="?", default="-")
    ap.add_argument("--wpm", type=float, default=155)
    ap.add_argument("--target", type=float, default=0, help="زمان هدف به ثانیه")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    if not lines:
        print("متنی پیدا نشد", file=sys.stderr)
        sys.exit(2)
    beats, total = build(lines, args.wpm)
    notes = problems(beats, total, args.target)

    if args.json:
        print(json.dumps({"total": round(total, 1), "wpm": args.wpm, "beats": beats, "notes": notes},
                         ensure_ascii=False, indent=2))
        return

    nwords = sum(b["words"] for b in beats)
    head = f"بیت‌شیت  ·  {nwords} کلمه  ·  ~{total:.1f} ثانیه با سرعت {args.wpm:.0f}"
    if args.target:
        head += f"  ·  هدف {args.target:.0f} ثانیه"
    print("\n" + head + "\n" + "=" * 72)
    for b in beats:
        text = b["text"] if len(b["text"]) <= 50 else b["text"][:47] + "..."
        flag = "  <- طولانی" if b["dur"] > MAX_BEAT or (b["role"] == "قلاب" and b["dur"] > HOOK_WINDOW) else ""
        print(f"  {tc(b['start'])}  {b['dur']:4.1f}s  {b['role']:<5} {text}{flag}")
    print("-" * 72)
    for n in notes:
        print(f"  - {n}")
    print()


if __name__ == "__main__":
    main()
