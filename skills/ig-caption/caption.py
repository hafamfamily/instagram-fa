#!/usr/bin/env python3
"""
caption.py - بررسی کپشن اینستاگرام و نشان دادن دقیق آنچه فید پیش از «... بیشتر» نشان می‌دهد.

بر پایهٔ caption.py از instagram-agent-skill (Jake Schincariol, MIT)، بازنویسی برای فارسی.

اینستاگرام حدود ۱۲۵ حرف اول کپشن را در فید نشان می‌دهد و بقیه را پشت «بیشتر»
پنهان می‌کند (عدد دقیق با دستگاه و فونت فرق دارد؛ ۱۲۵ تقریب محتاطانه است).
بیشتر کپشن‌هایی که شکست می‌خورند همان‌جا شکست می‌خورند.

چک‌ها:
  طول کل (حداکثر ۲۲۰۰)، خط اول در پنجرهٔ دید، شروع بدون سلام و مقدمه، وجود عدد یا
  مورد مشخص در پنجرهٔ دید، تعداد هشتگ (حداکثر ۵ در هر پست)، یک دعوت به اقدام،
  کلمه‌های جست‌وجو، و درستی نوشتار فارسی (نیم‌فاصله، ی/ک عربی، رقم‌های مخلوط).

استفاده:
  python caption.py caption.txt
  python caption.py caption.txt --keywords "لیست قیمت,هوش مصنوعی"
  python caption.py caption.txt --json
"""

import argparse
import json
import os
import re
import sys
import textwrap

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fa_text import (setup_stdout, numbers, latin_names, HASHTAG_RE, EMOJI_RE,  # noqa: E402
                     visible_len, normalize, words, low)

WINDOW = 125
MAX_LEN = 2200
MAX_TAGS = 5

GREETING_RE = re.compile(r"^\s*(?:سلام|درود|وقت(?:تون)? بخیر|عرض ادب|دوستان عزیز|همراهان عزیز|hi|hello)")
PREAMBLE_RE = re.compile(r"^\s*(?:در این پست|توی این پست|تو این پست|امروز می‌خوام|امروز میخوام|"
                         r"قراره امروز|در دنیای (?:امروز|پرشتاب)|همانطور که می‌دانید)")
CTA_PATTERNS = {
    "کامنت کلمه": r"(?:کامنت|بنویس)\S*\s.{0,25}(?:«|\"|کلمه)|(?:«[^»\n]{1,25}»|کلمه)[^.\n]{0,20}کامنت",
    "کامنت": r"کامنت (?:کن|کنید|بذار|بگذارید|بنویس)|تو کامنت|در کامنت|زیر همین پست",
    "ذخیره": r"ذخیره(?:‌ش)? کن|سیو کن|ذخیره کنید|سیو کنید|نگهش دار",
    "اشتراک": r"بفرست برای|بفرستید برای|بفرستش|برای .{1,20} بفرست|شیر کن|به اشتراک",
    "دایرکت": r"دایرکت|پیام بده|پیام بدید|پیام بدهید|DM",
    "لینک بایو": r"لینک (?:بایو|توی بایو|در بیو|در بایو)|بیو",
    "فالو": r"فالو کن|فالو کنید|دنبال کنید|دنبال کن",
}
NO_ZWNJ_RE = re.compile(r"(?<![\w‌])(?:ن?می) (?=[آ-ی]{2,})|(?<=[آ-ی]) (?:ها|های|هایی|ترین|تر)(?=[\s.,،!؟?]|$)")


def visible_window(text):
    """متنی که پیش از «بیشتر» دیده می‌شود: تا ۱۲۵ حرف، یا تا شکست خط دوم."""
    lines = text.strip().split("\n")
    shown, used = [], 0
    for i, line in enumerate(lines[:2]):
        room = WINDOW - used
        if room <= 0:
            break
        shown.append(line[:room])
        used += len(line) + 1
        if len(line) > room:
            break
    return "\n".join(shown), len(text.strip()) > used - 1


def check(text, keywords):
    t = normalize(text)
    res = []

    def add(status, name, detail):
        res.append({"status": status, "name": name, "detail": detail})

    n = visible_len(t)
    add("PASS" if n <= MAX_LEN else "FAIL", "طول", f"{n} از {MAX_LEN} حرف")

    first = t.strip().split("\n")[0]
    fl = len(first)
    add("PASS" if fl <= WINDOW else "WARN", "خط اول",
        f"{fl} حرف" + ("" if fl <= WINDOW else f"؛ در {WINDOW} وسط جمله بریده می‌شود"))

    if GREETING_RE.search(t):
        add("FAIL", "شروع", "با سلام شروع شده؛ پنجرهٔ دید را با سلام هدر نده")
    elif PREAMBLE_RE.search(t):
        add("FAIL", "شروع", "با مقدمه شروع شده؛ از خود حرف اصلی شروع کن")
    else:
        add("PASS", "شروع", "بدون سلام و مقدمه")

    window, _ = visible_window(t)
    marks = numbers(window) + latin_names(window)
    add("PASS" if marks else "WARN", "قلاب مشخص",
        f"{len(marks)} عدد یا اسم در پنجرهٔ دید" if marks else "در پنجرهٔ دید هیچ عدد یا مورد مشخصی نیست")

    tags = [x.strip() for x in HASHTAG_RE.findall(t)]
    if len(tags) > MAX_TAGS:
        add("FAIL", "هشتگ", f"{len(tags)} هشتگ؛ سقف اینستاگرام {MAX_TAGS} تا در هر پست است")
    elif any(t.strip().startswith(x) for x in tags):
        add("WARN", "هشتگ", "کپشن با هشتگ شروع شده")
    else:
        add("PASS", "هشتگ", f"{len(tags)} هشتگ" + (f": {' '.join(tags)}" if tags else ""))

    ctas = [name for name, pat in CTA_PATTERNS.items() if re.search(pat, t)]
    if "کامنت کلمه" in ctas:  # کامنت کلمه و ارسال در دایرکت یک دعوت است، نه دو تا
        ctas = [c for c in ctas if c not in ("کامنت", "دایرکت")]
    if not ctas:
        add("WARN", "دعوت به اقدام", "هیچ دعوتی نیست؛ بگو بیننده دقیقاً چه کند")
    elif len(ctas) > 1:
        add("WARN", "دعوت به اقدام", f"{len(ctas)} دعوت ({'، '.join(ctas)})؛ یکی را نگه دار")
    else:
        add("PASS", "دعوت به اقدام", f"یک دعوت: {ctas[0]}")

    if keywords:
        missing = [k for k in keywords if normalize(k) not in t]
        add("PASS" if not missing else "WARN", "کلمه‌های جست‌وجو",
            f"{len(keywords) - len(missing)} از {len(keywords)}" + (f"؛ نیست: {'، '.join(missing)}" if missing else ""))

    issues = []
    if re.search(r"[يك]", text):
        issues.append("ی/ک عربی")
    zw = NO_ZWNJ_RE.findall(t)
    if zw:
        issues.append(f"{len(zw)} جای بدون نیم‌فاصله (مثل «می خوام» یا «کتاب ها»)")
    if re.search(r"[0-9]", t) and re.search(r"[۰-۹]", t):
        issues.append("رقم فارسی و لاتین قاطی")
    add("PASS" if not issues else "WARN", "نوشتار", "درست" if not issues else "؛ ".join(issues))

    emojis = len(EMOJI_RE.findall(t))
    if emojis > 6:
        add("WARN", "ایموجی", f"{emojis} ایموجی؛ زیاد است و متن را ارزان نشان می‌دهد")
    return res, window


def render(text, res, window):
    print("\n  آنچه فید نشان می‌دهد")
    print("  +" + "-" * 56 + "+")
    for line in window.split("\n"):
        for part in textwrap.wrap(line, 52) or [""]:
            print(f"  | {part:<54} |")
    print("  +" + "-" * 44 + " ... بیشتر +\n")
    for r in res:
        print(f"  {r['status']:<5} {r['name']:<16} {r['detail']}")
    fails = sum(r["status"] == "FAIL" for r in res)
    warns = sum(r["status"] == "WARN" for r in res)
    print(f"\n  {fails} ایراد جدی، {warns} هشدار.\n")


def main():
    setup_stdout()
    ap = argparse.ArgumentParser(description="بررسی کپشن اینستاگرام")
    ap.add_argument("input", nargs="?", default="-")
    ap.add_argument("--keywords", default="", help="کلمه‌های جست‌وجو، جدا با ویرگول")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    text = sys.stdin.read() if a.input == "-" else open(a.input, encoding="utf-8").read()
    kws = [k.strip() for k in re.split(r"[,،]", a.keywords) if k.strip()]
    res, window = check(text, kws)
    if a.json:
        print(json.dumps({"window": window, "checks": res}, ensure_ascii=False, indent=2))
    else:
        render(text, res, window)
    sys.exit(1 if any(r["status"] == "FAIL" for r in res) else 0)


if __name__ == "__main__":
    main()
