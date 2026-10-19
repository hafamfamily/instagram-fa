#!/usr/bin/env python3
"""
hookscore.py - امتیاز دادن به جملهٔ اول ریلز (قلاب) و رتبه‌بندی چند قلاب.

بر پایهٔ hookscore.py از بستهٔ instagram-agent-skill (Jake Schincariol, MIT)،
بازنویسی‌شده برای فارسی (و جمله‌های مخلوط فارسی-انگلیسی).

این چیست:  پنج سنجهٔ ساده که فقط از روی متن حساب می‌شوند:
  طول (در کمتر از ~۳ ثانیه گفته شود)، مشخص بودن (عدد، مبلغ، اسم)،
  تنش (چیزی در خطر است)، جلو بودن حرف اصلی، و خطاب به بیننده.

این چه نیست:  پیش‌بین بازدید. خوب جدا می‌کند قلاب بد (سلام‌واحوال، مقدمه،
حرف کلی) را از قلاب معقول؛ ولی بین دو قلاب خوب نمی‌تواند برنده را بگوید.
آن را چهره، تدوین، صدا و الگوریتم تعیین می‌کند. آمار ریتنشن را جدی‌تر بگیر.

هر سنجه ۰ تا ۱۰۰. بالاتر بهتر.

استفاده:
  python hookscore.py hooks.txt               # هر خط یک قلاب، رتبه‌بندی
  python hookscore.py --hook "۱۸ میلیون تومن ضرر کردم سر یه قرارداد"
  python hookscore.py hooks.txt --json
"""

import argparse
import json
import os
import re
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fa_text import (setup_stdout, words, low, numbers, latin_names, HASHTAG_RE,  # noqa: E402
                     EMOJI_RE, clamp, bar, visible_len, normalize)

WPS = 2.6  # کلمه در ثانیه، گفتار فارسی محاوره (~۱۵۵ کلمه در دقیقه)

SPOKEN_NUMBERS = {
    "دو", "سه", "چهار", "پنج", "شش", "شیش", "هفت", "هشت", "ده", "دوازده",
    "پونزده", "پانزده", "بیست", "سی", "چهل", "پنجاه", "شصت", "صد", "دویست",
    "سیصد", "پونصد", "پانصد", "هزار", "میلیون", "میلیارد", "تریلیون", "نصف",
    "دوبرابر", "سه‌برابر", "دوتا", "سه‌تا", "چهارتا", "پنج‌تا", "ده‌تا", "صدتا",
    "two", "three", "five", "ten", "hundred", "thousand", "million",
}
MONEY_WORDS = {
    "تومن", "تومان", "ریال", "دلار", "درصد", "درآمد", "سود", "ضرر", "فروش",
    "قیمت", "اجاره", "حقوق", "قسط", "وام", "مشتری", "سفارش", "دقیقه", "ثانیه",
    "ساعت", "روز", "هفته", "ماه", "سال",
}
# کلمه‌هایی که چیزی را در خطر می‌گذارند.
STAKES = {
    "نه", "نکن", "نکنید", "نزن", "نخر", "نخرید", "نفرست", "هیچ‌وقت", "هرگز",
    "هیچ‌کس", "هیچکس", "اشتباه", "اشتباهی", "غلط", "ضرر", "باختم", "سوخت",
    "سوختم", "ازدست", "دادم", "هزینه", "گرون", "گران", "رایگان", "مجانی",
    "خطر", "خطرناک", "هشدار", "ممنوع", "دروغ", "راز", "پنهان", "مخفی", "فقط",
    "بدون", "به‌جای", "بجای", "ولی", "اما", "قبل", "دیگه", "دیگر", "واقعاً",
    "واقعا", "پشیمون", "پشیمان", "حیف", "کلاهبرداری", "ورشکست", "اخراج",
    "جریمه", "بدترین", "مشکل", "اشتباهات", "نمی‌دونستم", "نمیدونستم",
    "نمی‌گه", "نمی‌گن", "نمیگن", "نگفت", "نگفتن", "حذف", "تعطیل", "قطع",
    "بلاک", "شکست", "خراب", "ترس", "استرس", "عقب", "جا", "موندی", "باخت",
    "never", "stop", "mistake", "free", "secret", "wrong",
}
NEG_VERB_RE = re.compile(r"^(?:نمی‌|نمی|ن(?:کن|زن|خر|ده|گو|فرست|ذار|گذار|ریز|خور|رو|بین|خون|نویس))")

WEAK_OPENERS = [
    "سلام", "درود", "خب", "خوب", "دوستان", "بچه‌ها", "بچه ها", "امروز",
    "توی این ویدیو", "تو این ویدیو", "توی این پست", "تو این پست", "می‌خوام",
    "میخوام", "قراره", "ببینید", "راستش", "اول از همه", "همونطور که",
    "همانطور که", "بیاید", "بیایید", "حتماً براتون", "حتما براتون", "آیا شما",
    "عزیزان", "سلام به", "یه سوال", "یک سوال", "خیلی وقته", "اگه دوست",
    "hi", "hey", "hello", "so", "today",
]
IMPERATIVES = {
    "بخون", "بخوانید", "ببین", "ببینید", "بنویس", "بفرست", "بساز", "بزن",
    "نکن", "نکنید", "نزن", "نخر", "امتحان", "ذخیره", "کپی", "پاک", "شروع",
    "استفاده", "بگو", "بپرس", "برو", "بذار", "بگذار", "دست", "نگه", "حواست",
    "حواستون", "صبر", "هیچ‌وقت", "هرگز", "stop", "try", "save", "copy",
}
YOU_RE = re.compile(r"(?:^|\s)(?:تو|شما|خودت|خودتون|خودتان|برات|براتون|بهت|بهتون|"
                    r"ازت|ازتون|you|your)(?=\s|$|[،,.!?؟])")
YOU_VERB_RE = re.compile(r"^(?:می‌|می|نمی‌|نمی)?\S{2,}(?:ی|ید|ین|ت|تون)$")
IMPERATIVE_END_RE = re.compile(r"^(?:ب|بی|نک|نز)\S{1,5}$")  # بساز، بده، بزن، بخر، بنویس
PAST_I_RE = re.compile(r"(?:کردم|دادم|گرفتم|شدم|زدم|خریدم|فروختم|رفتم|ساختم|باختم|دیدم|گفتم|فهمیدم|داشتم|بودم|نوشتم|فرستادم)$")
I_RE = re.compile(r"(?:^|\s)(?:من|ما|خودم|برام|بهم|مون|i|my|we)(?=\s|$|[،,.!?؟])")

DEALBREAKERS = [
    (re.compile(r"^\s*(?:اسکرول نکن|رد نشو|ورق نزن|stop scrolling)"),
     "با «اسکرول نکن» شروع شده. التماسِ توجه یعنی هنوز توجه را به‌دست نیاورده‌ای."),
    (re.compile(r"(?:تو|توی|در) (?:این|اين) (?:ویدیو|ویدئو|ریلز|پست|کلیپ)|"
                r"می‌خوام (?:بهتون|براتون) (?:بگم|نشون بدم|توضیح بدم)|میخوام بهتون|"
                r"قراره (?:بهتون|براتون)"),
     "مقدمهٔ ویدیو. حذفش کن و از خود نتیجه شروع کن."),
    (re.compile(r"^\s*(?:سلام|درود|عرض ادب|وقت بخیر|hi |hey |hello )"),
     "سلام‌واحوال‌پرسی. کسی برای سلام شنیدن به فید نیامده."),
    (HASHTAG_RE, "هشتگ در قلاب. جای هشتگ ته کپشن است."),
    (EMOJI_RE, "ایموجی در قلاب. متن روی صفحه یا جای کلمه دارد یا ایموجی، نه هر دو."),
]


def check_length(text):
    w = words(text)
    n = len(w)
    secs = n / WPS
    chars = visible_len(text.strip())
    if 5 <= n <= 12:
        score = 100.0
    elif n < 5:
        score = clamp(100 - (5 - n) * 20)
    else:
        score = clamp(100 - (n - 12) * 11)
    if chars > 60:
        score -= 12
    return clamp(score), f"{n} کلمه، {chars} حرف، ~{secs:.1f} ثانیه گفتار (ایده‌آل ۵ تا ۱۲ کلمه)"


def concrete_markers(text):
    nums = numbers(text)
    names = set(latin_names(text))
    spoken = [x for x in (low(t) for t in words(text)) if x in SPOKEN_NUMBERS or x in MONEY_WORDS]
    return nums, names, spoken


def check_specificity(text):
    nums, names, spoken = concrete_markers(text)
    hits = len(nums) + len(names) + len(spoken)
    score = 15.0 if hits == 0 else clamp(45 + hits * 30)
    found = "، ".join(nums[:2] + sorted(names)[:2] + spoken[:2])
    return score, (f"{hits} نشانهٔ مشخص" + (f": {found}" if found else
                   " - نه عدد، نه مبلغ، نه اسم؛ هیچ چیز قابل‌سنجش"))


def is_stake(token):
    t = low(token)
    return t in STAKES or bool(NEG_VERB_RE.match(t))


def check_stakes(text):
    markers = sorted({low(t) for t in words(text) if is_stake(t)})
    if re.search(r"تومن|تومان|\$\s?\d", text):
        markers.append("مبلغ")
    n = len(markers)
    score = {0: 20.0, 1: 70.0}.get(n, 100.0)
    return score, f"{n} نشانهٔ تنش" + (f": {'، '.join(markers[:4])}" if markers else
                                       " - هیچ چیزی در خطر نیست")


def check_frontload(text):
    w = words(text)
    if not w:
        return 0.0, "خالی"
    lw = [low(x) for x in w]
    head = " ".join(lw[:3])
    penalty, hit = 0, None
    for weak in WEAK_OPENERS:
        if head.startswith(weak) or lw[0] == weak:
            penalty, hit = 30, weak
            break
    payload = None
    for i, tok in enumerate(lw):
        if (is_stake(tok) or tok in SPOKEN_NUMBERS or tok in MONEY_WORDS
                or re.search(r"[\d۰-۹٠-٩]", tok) or re.match(r"[A-Z]", w[i])):
            payload = i
            break
    if payload is None:
        base, where = 30.0, "هیچ کلمهٔ اصلی‌ای در جمله نیست"
    elif payload <= 3:
        base, where = 100.0, f"حرف اصلی در کلمهٔ {payload + 1}"
    elif payload <= 6:
        base, where = 70.0, f"حرف اصلی در کلمهٔ {payload + 1}؛ می‌شود جلوتر آورد"
    else:
        base, where = 40.0, f"حرف اصلی در کلمهٔ {payload + 1}؛ خیلی دیر است"
    return clamp(base - penalty), where + (f"؛ شروع ضعیف «{hit}»" if hit else "")


def check_address(text):
    t = " " + normalize(text) + " "
    w = [low(x) for x in words(text)]
    if YOU_RE.search(t):
        return 100.0, "با بیننده حرف می‌زند"
    if w and w[0] in IMPERATIVES:
        return 90.0, f"شروع با فعل امری («{w[0]}»)"
    if w and (w[-1] in IMPERATIVES or IMPERATIVE_END_RE.match(w[-1])):
        return 90.0, f"فعل امری در آخر جمله («{w[-1]}»)"
    if any(YOU_VERB_RE.match(x) and (x.startswith("می") or x.startswith("نمی")) for x in w):
        return 90.0, "فعل دوم‌شخص («...ی / ...ید»)"
    if I_RE.search(t) or any(re.match(r"^(?:می‌|می|نمی‌)\S+م$", x) or PAST_I_RE.search(x) for x in w):
        return 70.0, "اول‌شخص؛ بیننده خطاب نشده"
    return 35.0, "سوم‌شخص؛ کسی در اتاق نیست"


CHECKS = ["طول", "مشخص‌بودن", "تنش", "جلوبودن", "خطاب"]


def run(text):
    results = {
        "طول": check_length(text),
        "مشخص‌بودن": check_specificity(text),
        "تنش": check_stakes(text),
        "جلوبودن": check_frontload(text),
        "خطاب": check_address(text),
    }
    flags = [msg for pat, msg in DEALBREAKERS if pat.search(normalize(text))]
    scores = [results[c][0] for c in CHECKS]
    overall = clamp(statistics.mean(scores) * 0.6 + min(scores) * 0.4 - len(flags) * 15)
    verdict = "قوی" if overall >= 70 and min(scores) >= 55 and not flags else (
        "متوسط" if overall >= 50 else "ضعیف")
    return results, overall, verdict, flags


def render_one(text, results, overall, verdict, flags):
    print("\nامتیاز قلاب\n" + "=" * 62)
    print(f"  «{text.strip()}»\n")
    for name in CHECKS:
        score, detail = results[name]
        print(f"  {name:<11} {bar(score)} {score:5.1f}")
        print(f"  {'':<11} {detail}")
    print("-" * 62)
    print(f"  {'جمع':<11} {bar(overall)} {overall:5.1f}   {verdict}")
    for f in flags:
        print(f"\n  ردّی:  {f}")
    if verdict != "قوی":
        weakest = min(CHECKS, key=lambda c: results[c][0])
        print(f"\n  ضعیف‌ترین سنجه: {weakest}. همان را درست کن و دوباره اجرا کن.")
    print()


def render_table(rows):
    print("\nرتبه‌بندی قلاب‌ها\n" + "=" * 78)
    for i, r in enumerate(rows, 1):
        mark = "->" if i == 1 else "  "
        hook = r["hook"] if len(r["hook"]) <= 62 else r["hook"][:59] + "..."
        print(f"{mark} {r['score']:5.1f} {r['verdict']:<6} {hook}")
        print(f"        ضعیف‌ترین: {r['weakest']} ({r['checks'][r['weakest']]['score']:.0f})")
        for f in r["flags"]:
            print(f"        ردّی: {f}")
    print("\nاولی را بساز. اگر اولی زیر ۵۰ است، هیچ‌کدام قلاب نیستند.\n")


def main():
    setup_stdout()
    ap = argparse.ArgumentParser(description="امتیاز قلاب ریلز")
    ap.add_argument("input", nargs="?", default="-", help="فایل (هر خط یک قلاب) یا -")
    ap.add_argument("--hook", help="امتیاز یک قلاب")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.hook:
        lines = [args.hook]
    else:
        raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
    if not lines:
        print("چیزی برای امتیاز دادن نیست", file=sys.stderr)
        sys.exit(2)

    payload = []
    for line in lines:
        results, overall, verdict, flags = run(line)
        payload.append({
            "hook": line,
            "checks": {k: {"score": round(v[0], 1), "detail": v[1]} for k, v in results.items()},
            "weakest": min(CHECKS, key=lambda c: results[c][0]),
            "flags": flags, "score": round(overall, 1), "verdict": verdict,
        })

    if args.json:
        print(json.dumps(payload if len(payload) > 1 else payload[0], indent=2, ensure_ascii=False))
        return
    if len(payload) == 1:
        render_one(lines[0], *run(lines[0]))
    else:
        render_table(sorted(payload, key=lambda r: -r["score"]))


if __name__ == "__main__":
    main()
