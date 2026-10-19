#!/usr/bin/env python3
"""
detect.py - پنل پنج‌گانهٔ «ماشینی به نظر می‌رسد؟» برای متن فارسی.

بر پایهٔ detect.py از instagram-agent-skill (Jake Schincariol, MIT)، بازنویسی برای فارسی.

پنج سنجه (۰ تا ۱۰۰، بالاتر یعنی انسانی‌تر):
  تنوع جمله      طول جمله‌ها چقدر بالا و پایین می‌رود. متن ماشینی یکنواخت است.
  مشخص‌بودن      عدد، مبلغ، اسم و جزئیات در هر ۱۰۰ کلمه.
  کلیشه          تعداد عبارت‌های slop.json در هر ۱۰۰ کلمه (کمتر بهتر).
  اثر انگشت      کاراکترهای نامرئی، خط تیرهٔ بلند، گیومهٔ انگلیسی (نیم‌فاصله حساب نمی‌شود).
  صدا            ضمیر من/ما/تو/شما، فعل‌های محاوره، سؤال واقعی.

امتیاز کل: میانگین × ۰٫۶ + ضعیف‌ترین × ۰٫۴. زیر ۶۰ یعنی «پرچم خورده».

این ابزار یک آشکارساز رسمی نیست؛ فقط نشانه‌هایی را می‌شمارد که خواننده‌ها حس می‌کنند.

استفاده:
  python detect.py draft.txt
  python detect.py before.txt after.txt       # مقایسهٔ دو پیش‌نویس
  python detect.py draft.txt --json
"""

import argparse
import json
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from fa_text import setup_stdout, words, sentences, numbers, latin_names, bar, clamp, normalize  # noqa: E402

PRONOUNS = re.compile(r"(?:^|\s)(?:من|ما|تو|شما|خودم|خودت|برام|برات|بهت|بهتون|i|we|you)(?=\s|$|[،,.!?؟])")
COLLOQUIAL = re.compile(r"(?:^|\s)(?:یه|اینو|اونو|رو|میشه|نمیشه|می‌شه|نمی‌شه|دیگه|چیه|اینه|اونه|"
                        r"خب|آره|نه|هست|(?:ن?می‌|ن?می)\S+(?:ه|ن|ین))(?=\s|$|[،,.!?؟])")


def load_slop():
    with open(os.path.join(HERE, "slop.json"), encoding="utf-8") as f:
        return json.load(f)


def burstiness(text):
    lens = [len(words(s)) for s in sentences(text)]
    lens = [x for x in lens if x]
    if len(lens) < 4:
        return 50.0, "برای قضاوت کوتاه است"
    mean = statistics.mean(lens)
    cv = statistics.pstdev(lens) / mean if mean else 0
    score = clamp(cv / 0.6 * 100)
    return score, f"میانگین {mean:.1f} کلمه در جمله، ضریب تغییر {cv:.2f} (بالای ۰٫۵ خوب است)"


def specificity(text):
    n = len(words(text))
    if n < 25:
        return 50.0, "برای قضاوت کوتاه است"
    hits = len(numbers(text)) + len(latin_names(text)) + len(re.findall(r"«[^»]{2,30}»", text))
    per100 = hits / n * 100
    return clamp(per100 / 4 * 100), f"{hits} مورد مشخص؛ {per100:.1f} در هر ۱۰۰ کلمه (۴ یا بیشتر خوب است)"


def slop_density(text, lex):
    n = len(words(text))
    if not n:
        return 50.0, "خالی"
    t = normalize(text)
    hits = []
    for item in lex["phrases"]:
        c = t.count(item["find"])
        if c:
            hits.append((item["find"], c))
    for s in lex["structures"]:
        try:
            c = len(re.findall(s["regex"], t))
        except re.error:
            c = 0
        if c:
            hits.append((s["name"], c))
    total = sum(c for _, c in hits)
    per100 = total / n * 100
    detail = f"{total} کلیشه" + (f": {'، '.join(h for h, _ in hits[:4])}" if hits else "")
    return clamp(100 - per100 * 40), detail


def fingerprint(text):
    invisible = len(re.findall(r"[​‍⁠﻿­‪-‮⁦-⁩]", text))
    em = text.count("—")
    curly = sum(text.count(c) for c in "“”‘’")
    nbsp = text.count(" ") + text.count(" ")
    arabic = len(re.findall(r"[يك]", text))
    per1k = (invisible * 4 + em * 2 + curly + nbsp + arabic * 0.5) / max(len(text), 1) * 1000
    detail = (f"{invisible} نامرئی، {em} خط تیرهٔ بلند، {curly} گیومهٔ انگلیسی، {nbsp} فاصلهٔ سخت، "
              f"{arabic} ی/ک عربی (نیم‌فاصله ایراد نیست)")
    return clamp(100 - per1k * 10), detail


def voice(text):
    n = len(words(text))
    if n < 25:
        return 50.0, "برای قضاوت کوتاه است"
    t = " " + normalize(text) + " "
    pron = len(PRONOUNS.findall(t))
    coll = len(COLLOQUIAL.findall(t))
    q = len(re.findall(r"[؟?]", text))
    per100 = (pron + coll * 0.3 + q) / n * 100
    return clamp(per100 / 6 * 100), f"{pron} ضمیر شخصی، {coll} نشانهٔ محاوره، {q} سؤال"


CHECKS = ["تنوع جمله", "مشخص‌بودن", "کلیشه", "اثر انگشت", "صدا"]


def panel(text, lex):
    r = {"تنوع جمله": burstiness(text), "مشخص‌بودن": specificity(text),
         "کلیشه": slop_density(text, lex), "اثر انگشت": fingerprint(text), "صدا": voice(text)}
    scores = [r[c][0] for c in CHECKS]
    total = clamp(statistics.mean(scores) * 0.6 + min(scores) * 0.4)
    return r, total, ("انسانی" if total >= 75 else "مرزی" if total >= 60 else "پرچم خورده")


def show(name, r, total, verdict):
    print(f"\nپنل تشخیص ماشینی  {name}\n" + "=" * 62)
    for c in CHECKS:
        s, d = r[c]
        print(f"  {c:<11} {bar(s)} {s:5.1f}\n  {'':<11} {d}")
    print("-" * 62)
    print(f"  {'امتیاز انسانی':<11} {bar(total)} {total:5.1f}   {verdict}\n")


def main():
    setup_stdout()
    ap = argparse.ArgumentParser(description="پنل تشخیص متن ماشینی برای فارسی")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    lex = load_slop()
    out = []
    for f in a.files:
        text = sys.stdin.read() if f == "-" else open(f, encoding="utf-8").read()
        r, total, verdict = panel(text, lex)
        out.append({"file": f, "score": round(total, 1), "verdict": verdict,
                    "checks": {k: {"score": round(v[0], 1), "detail": v[1]} for k, v in r.items()}})
        if not a.json:
            show(f, r, total, verdict)
    if a.json:
        print(json.dumps(out if len(out) > 1 else out[0], ensure_ascii=False, indent=2))
    elif len(out) == 2:
        d = out[1]["score"] - out[0]["score"]
        print(f"تغییر: {d:+.1f} امتیاز ({out[0]['score']} → {out[1]['score']})\n")


if __name__ == "__main__":
    main()
