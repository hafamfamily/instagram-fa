#!/usr/bin/env python3
"""
swipe.py - رتبه‌بندی ریلزهای موفق دیگران بر اساس «چند برابرِ میانهٔ خودِ همان پیج»
و ساختن فایل الهام (swipe file).

بر پایهٔ swipe.py از instagram-agent-skill (Jake Schincariol, MIT)، بازنویسی برای فارسی.

چرا میانه؟ یک ریلز ۵۰ هزار بازدیدی برای پیجی که معمولاً ۲ هزار می‌گیرد اتفاق بزرگی است
(۲۵ برابر)؛ همان عدد برای پیجی که معمولاً ۸۰ هزار می‌گیرد شکست است. رتبه‌بندی با تعداد
فالوور یا بازدید خام، فقط پیج‌های بزرگ را بالا می‌آورد و چیزی یاد نمی‌دهد.

ورودی: فایل TSV (جدا شده با Tab) با سطر عنوان. ستون‌های لازم:
  account  followers  median  views  hook
ستون‌های اختیاری: length  cta  url
عددها می‌توانند فارسی یا لاتین باشند و «12K» یا «1.2M» هم قبول است.

استفاده:
  python swipe.py captured.tsv
  python swipe.py captured.tsv --out swipe.md
"""

import argparse
import csv
import json
import os
import re
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from fa_text import setup_stdout, to_en_digits  # noqa: E402

REEL_DIR = os.path.join(os.path.dirname(HERE), "ig-reel")
sys.path.insert(0, REEL_DIR)
try:
    import hookscore  # noqa: E402
except Exception:  # اسکیل ig-reel کنار این اسکیل نصب نیست
    hookscore = None


def num(x):
    s = to_en_digits(str(x)).strip().replace(",", "").replace("٬", "").lower()
    mult = 1
    if s.endswith("k") or s.endswith("هزار"):
        mult, s = 1000, s.rstrip("k").replace("هزار", "")
    elif s.endswith("m") or s.endswith("میلیون"):
        mult, s = 1_000_000, s.rstrip("m").replace("میلیون", "")
    try:
        return float(s) * mult
    except ValueError:
        return 0.0


def load_formulas():
    path = os.path.join(REEL_DIR, "hooks.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    by_id = {h["id"]: h for h in data["hooks"]}
    return [(by_id[i]["name"], re.compile(by_id[i]["match"])) for i in data["classify_order"] if i in by_id]


def classify(hook, formulas):
    for name, pat in formulas:
        if pat.search(hook):
            return name
    return "دسته‌بندی‌نشده"


def main():
    setup_stdout()
    ap = argparse.ArgumentParser(description="رتبه‌بندی ریلزها با ضریب میانه")
    ap.add_argument("input")
    ap.add_argument("--out")
    a = ap.parse_args()

    with open(a.input, encoding="utf-8") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    if not rows:
        print("فایل خالی است", file=sys.stderr)
        sys.exit(2)
    formulas = load_formulas()
    items = []
    for r in rows:
        median = num(r.get("median", 0))
        views = num(r.get("views", 0))
        hook = (r.get("hook") or "").strip()
        mult = views / median if median else 0
        score = hookscore.run(hook)[1] if (hookscore and hook) else None
        items.append({**r, "views_n": views, "median_n": median, "multiple": mult,
                      "formula": classify(hook, formulas), "hookscore": score})
    items.sort(key=lambda x: -x["multiple"])

    third = max(1, len(items) // 3)
    top, bottom = items[:third], items[-third:]

    out = ["# فایل الهام (Swipe)\n",
           "رتبه با «چند برابرِ میانهٔ همان پیج». الگو را برمی‌داریم، نه ویدیو را؛ منبع هر ردیف کنارش است.\n",
           "| رتبه | پیج | ضریب | بازدید | فرمول | امتیاز قلاب | قلاب |",
           "|---|---|---|---|---|---|---|"]
    for i, it in enumerate(items, 1):
        hs = f"{it['hookscore']:.0f}" if it["hookscore"] is not None else "-"
        out.append(f"| {i} | {it.get('account', '')} | {it['multiple']:.1f}× | {int(it['views_n']):,} | "
                   f"{it['formula']} | {hs} | {it.get('hook', '').strip()} |")

    def summary(group):
        forms = {}
        for it in group:
            forms[it["formula"]] = forms.get(it["formula"], 0) + 1
        lens = [num(it.get("length", 0)) for it in group if num(it.get("length", 0))]
        scores = [it["hookscore"] for it in group if it["hookscore"] is not None]
        return forms, (statistics.median(lens) if lens else None), (statistics.mean(scores) if scores else None)

    tf, tl, ts = summary(top)
    bf, bl, bs = summary(bottom)
    out.append("\n## یک‌سوم بالا در برابر یک‌سوم پایین\n")
    out.append(f"- فرمول‌های پرتکرار بالا: {'، '.join(f'{k} ({v})' for k, v in sorted(tf.items(), key=lambda x: -x[1]))}")
    out.append(f"- فرمول‌های پرتکرار پایین: {'، '.join(f'{k} ({v})' for k, v in sorted(bf.items(), key=lambda x: -x[1]))}")
    if tl and bl:
        out.append(f"- میانهٔ طول: بالا {tl:.0f} ثانیه، پایین {bl:.0f} ثانیه")
    if ts is not None and bs is not None:
        out.append(f"- میانگین امتیاز قلاب: بالا {ts:.0f}، پایین {bs:.0f}")
    out.append("\nیادت باشد: با چند ده ردیف، این‌ها نشانه‌اند، نه قانون.\n")

    text = "\n".join(out)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"نوشته شد: {a.out}")
    print(text)


if __name__ == "__main__":
    main()
