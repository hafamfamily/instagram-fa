#!/usr/bin/env python3
"""
publish.py - دروازهٔ تأیید. هیچ محتوایی بدون تأیید صریح صاحب پیج به «آماده» نمی‌رود.

این اسکریپت چیزی را در اینستاگرام منتشر نمی‌کند. فقط:
  approve  محتوای تأییدشده را با نام‌گذاری مرتب در پوشهٔ ready/ می‌گذارد، همراه با
           کپشن آمادهٔ کپی و چک‌لیست انتشار از گوشی. بدون --approved-by اجرا نمی‌شود؛
           متن دقیق تأیید صاحب پیج (مثلاً «بله، این رو منتشر کن») در تاریخچه ثبت می‌شود.
  revise   محتوا را با یادداشت به «نیاز به اصلاح» برمی‌گرداند.
  posted   بعد از اینکه صاحب پیج خودش منتشر کرد، در دفتر انتشار ثبت می‌شود.
  list     فهرست محتواها بر اساس وضعیت.

استفاده:
  python publish.py list --page <پوشهٔ پیج>
  python publish.py approve <پوشهٔ محتوا> --approved-by "بله منتشرش کن"
  python publish.py revise  <پوشهٔ محتوا> --note "قلاب ضعیف است"
  python publish.py posted  <پوشهٔ محتوا> [--url https://instagram.com/p/...]
"""

import argparse
import csv
import datetime as dt
import glob
import json
import os
import shutil
import sys

TYPE_FA = {"carousel": "کاروسل", "single": "پست تکی", "reel": "ریلز", "story": "استوری"}
STATUS_FA = {"draft": "پیش‌نویس (منتظر تأیید)", "revise": "نیاز به اصلاح", "approved": "تأییدشده، آمادهٔ انتشار",
             "posted": "منتشرشده"}


def setup_stdout():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass


def load(d):
    p = os.path.join(d, "status.json")
    if not os.path.exists(p):
        print(f"status.json در {d} نیست؛ این پوشهٔ محتوا نیست.", file=sys.stderr)
        sys.exit(2)
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save(d, st):
    with open(os.path.join(d, "status.json"), "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)


def now():
    return dt.datetime.now().isoformat(timespec="minutes")


def page_of(item_dir):
    return os.path.dirname(os.path.dirname(os.path.abspath(item_dir)))


def checklist(st, files, has_video):
    t = st["type"]
    lines = [f"# انتشار: {st['title']}", "",
             f"نوع: {TYPE_FA.get(t, t)}  ·  تاریخ پیشنهادی: {st.get('date', '')} {st.get('time', '')}", "",
             "## انتقال به گوشی", "",
             "یکی از این راه‌ها: پیام‌های ذخیره‌شدهٔ تلگرام (فایل را به‌صورت «فایل» بفرست، نه «عکس»، تا کیفیت کم نشود)، "
             "گوگل‌درایو، یا کابل.", "", "## مراحل در اینستاگرام", ""]
    if t == "story":
        lines += ["1. استوری‌ها را به ترتیب شماره (۰۱، ۰۲، ...) بگذار؛ هر کدام جدا.",
                  "2. جاهای خط‌چین «استیکر ... را اینجا بگذار» را با همان استیکر بپوشان (نظرسنجی، سؤال، لینک...).",
                  "3. فاصلهٔ استوری‌ها را در طول روز پخش کن؛ لازم نیست همه با هم باشند.",
                  "4. استوری‌های مهم را به هایلایت مرتبط اضافه کن."]
    elif t == "reel":
        lines += ["1. + ← Reel ← ویدیو `reel.mp4` را انتخاب کن.",
                  "2. موسیقی را از کتابخانهٔ خود اینستاگرام اضافه کن (صدای ترند مرتبط، با صدای کم زیر متن).",
                  "3. Edit cover ← از گالری `cover.png` را انتخاب کن." if any("cover" in f for f in files) else
                  "3. کاور: فریمی را انتخاب کن که متن قلاب کامل دیده شود.",
                  "4. کپشن را از `caption.txt` کپی کن.",
                  "5. اگر قلاب‌ها دو گزینه داشت، Trial reel را برای نسخهٔ دوم امتحان کن (اگر برایت فعال است).",
                  "6. Share."]
        if not has_video:
            lines.insert(-6, "توجه: ویدیو ساخته نشده؛ با فیلم‌نامه و بیت‌شیت `script.md` خودت ضبط کن.")
    else:
        lines += ["1. + ← Post ← چند انتخابی ← تصویرها را به ترتیب شماره انتخاب کن.",
                  "2. اندازه را روی ۴:۵ (عمودی) بگذار تا چیزی بریده نشود.",
                  "3. کپشن را از `caption.txt` کپی کن.",
                  "4. اگر محصول یا آدم دیگری در تصویر است، تگ کن.",
                  "5. Share."]
    lines += ["", "## بعد از انتشار", "",
              "- تا ۳۰ دقیقهٔ اول به همهٔ کامنت‌ها جواب بده (ig-engage کمکت می‌کند).",
              "- به Claude بگو «منتشر کردم» تا در دفتر انتشار ثبت شود.", ""]
    return "\n".join(lines)


def cmd_approve(a):
    d = os.path.abspath(a.item)
    st = load(d)
    if not a.approved_by or len(a.approved_by.strip()) < 2:
        print("بدون متن تأیید صاحب پیج نمی‌شود تأیید کرد (--approved-by).", file=sys.stderr)
        sys.exit(2)
    if st["status"] == "posted":
        print("این محتوا قبلاً منتشر شده.", file=sys.stderr)
        sys.exit(1)
    slides = sorted(glob.glob(os.path.join(d, "slides", "*.png")))
    video = os.path.join(d, "reel.mp4")
    has_video = os.path.exists(video)
    if not slides and not has_video and st["type"] != "reel":
        print("هیچ تصویری ساخته نشده؛ اول render.py را اجرا کن.", file=sys.stderr)
        sys.exit(1)
    over = [os.path.basename(s) for s in slides if os.path.exists(s + ".overflow")]
    if over:
        print(f"این اسلایدها سرریز متن دارند: {', '.join(over)}. اول درستشان کن.", file=sys.stderr)
        sys.exit(1)

    out = os.path.join(page_of(d), "ready", os.path.basename(d))
    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(out)
    copied = []
    if st["type"] == "reel":
        if has_video:
            shutil.copy(video, os.path.join(out, "reel.mp4"))
            copied.append("reel.mp4")
        if slides:
            shutil.copy(slides[0], os.path.join(out, "cover.png"))
            copied.append("cover.png")
        for name in ("script.md",):
            if os.path.exists(os.path.join(d, name)):
                shutil.copy(os.path.join(d, name), os.path.join(out, name))
                copied.append(name)
    else:
        for i, s in enumerate(slides, 1):
            name = f"{i:02d}.png"
            shutil.copy(s, os.path.join(out, name))
            copied.append(name)
    cap = os.path.join(d, "caption.txt")
    if os.path.exists(cap):
        shutil.copy(cap, os.path.join(out, "caption.txt"))
        copied.append("caption.txt")
    elif st["type"] != "story":
        print("هشدار: caption.txt نیست.", file=sys.stderr)
    with open(os.path.join(out, "انتشار.md"), "w", encoding="utf-8") as f:
        f.write(checklist(st, copied, has_video))

    st["status"] = "approved"
    st["ready_dir"] = out
    st.setdefault("history", []).append({"at": now(), "action": "approved", "by": a.approved_by.strip()})
    save(d, st)
    print(json.dumps({"ready_dir": out, "files": copied + ["انتشار.md"]}, ensure_ascii=False, indent=2))


def cmd_revise(a):
    d = os.path.abspath(a.item)
    st = load(d)
    st["status"] = "revise"
    st.setdefault("history", []).append({"at": now(), "action": "revise", "note": a.note or ""})
    save(d, st)
    print(f"برگشت برای اصلاح: {st['title']}")


def cmd_posted(a):
    d = os.path.abspath(a.item)
    st = load(d)
    if st["status"] != "approved":
        print("فقط محتوای تأییدشده را می‌شود «منتشرشده» ثبت کرد.", file=sys.stderr)
        sys.exit(1)
    st["status"] = "posted"
    st["posted_at"] = now()
    if a.url:
        st["url"] = a.url
    st.setdefault("history", []).append({"at": now(), "action": "posted", "url": a.url or ""})
    save(d, st)
    log = os.path.join(page_of(d), "published.csv")
    new = not os.path.exists(log)
    with open(log, "a", encoding="utf-8-sig" if new else "utf-8", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["تاریخ انتشار", "نوع", "عنوان", "پوشه", "لینک"])
        w.writerow([st["posted_at"], TYPE_FA.get(st["type"], st["type"]), st["title"], os.path.basename(d), a.url or ""])
    print(f"ثبت شد: {st['title']}")


def cmd_list(a):
    root = os.path.join(a.page, "content")
    rows = []
    for sp in sorted(glob.glob(os.path.join(root, "*", "status.json"))):
        with open(sp, encoding="utf-8") as f:
            st = json.load(f)
        if a.status and st["status"] != a.status:
            continue
        rows.append((st.get("date", ""), STATUS_FA.get(st["status"], st["status"]),
                     TYPE_FA.get(st["type"], st["type"]), st["title"], os.path.dirname(sp)))
    if not rows:
        print("محتوایی نیست.")
    for r in rows:
        print(f"{r[0]}  {r[1]:<24} {r[2]:<9} {r[3]}\n            {r[4]}")


def main():
    setup_stdout()
    ap = argparse.ArgumentParser(description="دروازهٔ تأیید انتشار")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("approve")
    p.add_argument("item")
    p.add_argument("--approved-by", required=True, help="متن دقیق تأیید صاحب پیج")
    p.set_defaults(fn=cmd_approve)
    p = sub.add_parser("revise")
    p.add_argument("item")
    p.add_argument("--note")
    p.set_defaults(fn=cmd_revise)
    p = sub.add_parser("posted")
    p.add_argument("item")
    p.add_argument("--url")
    p.set_defaults(fn=cmd_posted)
    p = sub.add_parser("list")
    p.add_argument("--page", required=True)
    p.add_argument("--status", choices=list(STATUS_FA))
    p.set_defaults(fn=cmd_list)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
