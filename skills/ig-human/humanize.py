#!/usr/bin/env python3
"""
humanize.py - پاک کردن ردّ پای متن ماشینی از پیش‌نویس فارسی، بدون خراب کردن املای فارسی.

بر پایهٔ humanize.py از instagram-agent-skill (Jake Schincariol, MIT)، بازنویسی برای فارسی.
مهم‌ترین تفاوت با نسخهٔ اصلی: نیم‌فاصله (U+200C) هرگز حذف نمی‌شود.

مراحل:
  ۱. نامرئی‌ها: فاصلهٔ صفرعرض، BOM، کاراکترهای کنترل جهت و تگ‌های یونیکد حذف؛ فاصلهٔ سخت به فاصلهٔ عادی.
  ۲. نشانه‌گذاری: خط تیرهٔ بلند به «، »؛ گیومهٔ انگلیسی به «»؛ ی و ک عربی به فارسی.
  ۳. نیم‌فاصله: «می خوام» به «می‌خوام»، «کتاب ها» به «کتاب‌ها»، «بزرگ تر» به «بزرگ‌تر».
  ۴. عبارت‌های کلیشه‌ای از slop.json جایگزین یا حذف می‌شوند.
  ۵. ساختارهای کلیشه‌ای فقط گزارش می‌شوند؛ درست کردنشان کار نویسنده است، نه regex.
  ۶. تمیزکاری: فاصله‌های تکراری، فاصلهٔ پیش از نشانه‌ها، ویرگول‌های تکراری.

استفاده:
  python humanize.py draft.txt                 # متن تمیز در خروجی + گزارش
  python humanize.py draft.txt --out clean.txt
  python humanize.py draft.txt --report-only
  python humanize.py draft.txt --no-zwnj       # به نیم‌فاصله دست نزن
"""

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from fa_text import setup_stdout, normalize, ZWNJ  # noqa: E402

FA = "آ-ی"


def load_lexicon(path=None):
    with open(path or os.path.join(HERE, "slop.json"), encoding="utf-8") as f:
        return json.load(f)


def cp_range(spec):
    parts = [p.strip().replace("U+", "") for p in spec.split("-")]
    lo = int(parts[0], 16)
    hi = int(parts[-1], 16)
    return lo, hi


def strip_invisible(text, lex, log):
    for item in lex["invisible"]:
        lo, hi = cp_range(item["cp"])
        if lo <= 0x200C <= hi:
            continue  # نیم‌فاصله مقدس است
        cls = "[" + "".join(chr(c) for c in range(lo, hi + 1)) + "]" if hi - lo < 200 else \
              "[" + chr(lo) + "-" + chr(hi) + "]"
        rep = " " if item["action"] == "space" else ""
        text, n = re.subn(cls, rep, text)
        if n:
            log.append(f"{n} × {item['name']}")
    return text


def typography(text, lex, log):
    for item in lex["typographic"]:
        n = text.count(item["from"])
        if n:
            text = text.replace(item["from"], item["to"])
            log.append(f"{n} × {item['name']}")
    before = text
    text = normalize(text)
    if text != before:
        log.append("ی/ک عربی به فارسی")
    return text


def fix_zwnj(text, log):
    total = 0
    # می / نمی جدا از فعل
    text, n = re.subn(rf"(?<![{FA}{ZWNJ}])(ن?می) (?=[{FA}]{{2,}})", rf"\1{ZWNJ}", text)
    total += n
    # ها، های، هایی، هایم... و تر، ترین جدا از کلمهٔ قبل
    text, n = re.subn(rf"(?<=[{FA}]) (ها|های|هایی|هایم|هایت|هایش|هایمان|هایتان|هایشان|تر|ترین)(?=[\s.,،!؟?:؛»)]|$)",
                      rf"{ZWNJ}\1", text)
    total += n
    # فاصلهٔ معمولی که به‌جای نیم‌فاصله پیش از «ای» و «اش» آمده: خانه ای -> خانه‌ای
    text, n = re.subn(rf"(?<=[{FA}]ه) (ای|اش|ام|ات)(?=[\s.,،!؟?]|$)", rf"{ZWNJ}\1", text)
    total += n
    if total:
        log.append(f"{total} نیم‌فاصلهٔ جاافتاده درست شد")
    return text


def phrases(text, lex, log):
    hits = {}
    for item in sorted(lex["phrases"], key=lambda x: -len(x["find"])):
        pat = re.compile(rf"(?<![{FA}{ZWNJ}]){re.escape(item['find']).replace(chr(92) + ' ', r'\s+')}(?![{FA}{ZWNJ}])")
        text, n = pat.subn(item["replace"], text)
        if n:
            hits[item["find"]] = hits.get(item["find"], 0) + n
    for k, v in hits.items():
        log.append(f"«{k}» × {v}")
    return text


def structures(text, lex):
    found = []
    for s in lex["structures"]:
        try:
            n = len(re.findall(s["regex"], text))
        except re.error:
            continue
        if n:
            found.append(f"{s['name']} × {n} → {s['fix']}")
    return found


def tidy(text):
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r" +([،,.!?؟:؛»)])", r"\1", text)
    text = re.sub(r"([«(]) +", r"\1", text)
    text = re.sub(r"(،\s*){2,}", "، ", text)
    text = re.sub(r"(?m)^[ \t]*[،,]\s*", "", text)
    text = re.sub(r"(?m)[ \t]+$", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"([.!؟?])(?:\s*[.!؟?،])+", r"\1", text)   # «. .» بعد از حذف عبارت
    text = re.sub(r"(?m)^[\s.،,!؟?]+$\n?", "", text)
    return text.strip() + "\n"


def humanize(text, lex, zwnj=True):
    log = []
    text = strip_invisible(text, lex, log)
    text = typography(text, lex, log)
    if zwnj:
        text = fix_zwnj(text, log)
    text = phrases(text, lex, log)
    text = tidy(text)
    return text, log, structures(text, lex)


def main():
    setup_stdout()
    ap = argparse.ArgumentParser(description="انسانی‌ساز متن فارسی")
    ap.add_argument("input", nargs="?", default="-")
    ap.add_argument("--out")
    ap.add_argument("--lexicon")
    ap.add_argument("--no-zwnj", action="store_true", help="نیم‌فاصله‌ها را اصلاح نکن")
    ap.add_argument("--report-only", action="store_true")
    a = ap.parse_args()

    raw = sys.stdin.read() if a.input == "-" else open(a.input, encoding="utf-8").read()
    clean, log, struct = humanize(raw, load_lexicon(a.lexicon), zwnj=not a.no_zwnj)

    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(clean)
    elif not a.report_only:
        print(clean)

    print("\n--- گزارش انسانی‌ساز ---", file=sys.stderr)
    for line in log or ["تغییری لازم نبود"]:
        print(f"  اصلاح شد:  {line}", file=sys.stderr)
    for line in struct:
        print(f"  دستی درست کن:  {line}", file=sys.stderr)
    if not struct:
        print("  ساختار کلیشه‌ای پیدا نشد.", file=sys.stderr)


if __name__ == "__main__":
    main()
