#!/usr/bin/env python3
"""
page.py - مدیریت پیج‌ها و پوشه‌های کاری بستهٔ instagram-fa.

هر پیج یک پوشه دارد:
  <خانه>/<نام-پیج>/
      page.md          شناسنامهٔ پیج (موضوع، مخاطب، لحن، برنامه، خطوط قرمز...)
      brand.json       رنگ‌ها، هندل، رقم فارسی (برای ساخت تصویر)
      plan/            برنامه‌های هفتگی (md و xlsx)
      content/         هر محتوا یک پوشه: spec.json، caption.txt، slides/، status.json
      ready/           محتوای تأییدشده و آمادهٔ انتشار دستی
      published.csv    دفتر انتشار
      swipe.md         فایل الهام از ig-viral
      insights.md      درس‌های ig-audit

«خانه» به‌طور پیش‌فرض ~/instagram-fa است. با `page.py home <مسیر>` عوضش کن
(مثلاً D:\\instagram)؛ انتخاب در ~/.instagram-fa.json ذخیره می‌شود.

استفاده:
  python page.py where                     # پیج فعال و مسیرها (JSON)
  python page.py list
  python page.py new my-page               # ساخت پیج تازه و فعال کردنش
  python page.py use my-page
  python page.py home "D:/instagram"
  python page.py item --type carousel --title "لیست قیمت" [--date 2026-10-24]
"""

import argparse
import datetime as dt
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CONF = os.path.join(os.path.expanduser("~"), ".instagram-fa.json")
TYPES = ("carousel", "single", "reel", "story")


def setup_stdout():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass


def conf():
    if os.path.exists(CONF):
        with open(CONF, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_conf(c):
    with open(CONF, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False, indent=2)


def home():
    return os.environ.get("IGFA_HOME") or conf().get("home") or os.path.join(os.path.expanduser("~"), "instagram-fa")


def active():
    return conf().get("active")


def page_dir(slug=None):
    slug = slug or active()
    return os.path.join(home(), slug) if slug else None


def slugify(text):
    s = re.sub(r"[^\w\u0600-\u06FF\-]+", "-", text.strip().lower()).strip("-")
    return s[:40] or "item"


def cmd_where(_):
    p = page_dir()
    print(json.dumps({
        "home": home(), "active": active(), "page_dir": p,
        "exists": bool(p and os.path.isdir(p)),
        "page_md": p and os.path.join(p, "page.md"),
        "brand_json": p and os.path.join(p, "brand.json"),
        "content": p and os.path.join(p, "content"),
        "plan": p and os.path.join(p, "plan"),
        "ready": p and os.path.join(p, "ready"),
        "skills_dir": os.path.dirname(HERE),
    }, ensure_ascii=False, indent=2))


def cmd_list(_):
    h = home()
    if not os.path.isdir(h):
        print("هنوز هیچ پیجی ساخته نشده. اول: page.py new <نام>")
        return
    for d in sorted(os.listdir(h)):
        if os.path.exists(os.path.join(h, d, "page.md")):
            print(("* " if d == active() else "  ") + d)


def cmd_new(a):
    slug = slugify(a.slug)
    p = page_dir(slug)
    if os.path.exists(os.path.join(p, "page.md")) and not a.force:
        print(f"این پیج از قبل هست: {p}  (برای فعال کردن: page.py use {slug})")
        sys.exit(1)
    for sub in ("plan", "content", "ready"):
        os.makedirs(os.path.join(p, sub), exist_ok=True)
    tpl = os.path.join(HERE, "templates")
    shutil.copy(os.path.join(tpl, "page.md"), os.path.join(p, "page.md"))
    shutil.copy(os.path.join(tpl, "brand.json"), os.path.join(p, "brand.json"))
    log = os.path.join(p, "published.csv")
    if not os.path.exists(log):
        with open(log, "w", encoding="utf-8-sig") as f:
            f.write("تاریخ انتشار,نوع,عنوان,پوشه,لینک\n")
    c = conf()
    c["active"] = slug
    save_conf(c)
    print(json.dumps({"created": p, "active": slug}, ensure_ascii=False))


def cmd_use(a):
    slug = slugify(a.slug)
    if not os.path.exists(os.path.join(page_dir(slug), "page.md")):
        print(f"پیج «{slug}» پیدا نشد. فهرست: page.py list")
        sys.exit(1)
    c = conf()
    c["active"] = slug
    save_conf(c)
    print(f"پیج فعال: {slug}")


def cmd_home(a):
    path = os.path.abspath(os.path.expanduser(a.path))
    os.makedirs(path, exist_ok=True)
    c = conf()
    c["home"] = path
    save_conf(c)
    print(f"خانهٔ پیج‌ها: {path}")


def cmd_item(a):
    p = page_dir()
    if not p or not os.path.isdir(p):
        print("پیج فعالی نیست. اول ig-setup را اجرا کن.")
        sys.exit(1)
    date = a.date or dt.date.today().isoformat()
    name = f"{date}-{a.type}-{slugify(a.title)}"
    d = os.path.join(p, "content", name)
    n = 2
    while os.path.exists(d):
        d = os.path.join(p, "content", f"{name}-{n}")
        n += 1
    os.makedirs(os.path.join(d, "slides"))
    status = {"status": "draft", "type": a.type, "title": a.title, "date": date,
              "time": a.time or "", "created": dt.datetime.now().isoformat(timespec="minutes"), "history": []}
    with open(os.path.join(d, "status.json"), "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
    print(d)


def main():
    setup_stdout()
    ap = argparse.ArgumentParser(description="مدیریت پیج‌های instagram-fa")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("where").set_defaults(fn=cmd_where)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    n = sub.add_parser("new")
    n.add_argument("slug")
    n.add_argument("--force", action="store_true")
    n.set_defaults(fn=cmd_new)
    u = sub.add_parser("use")
    u.add_argument("slug")
    u.set_defaults(fn=cmd_use)
    h = sub.add_parser("home")
    h.add_argument("path")
    h.set_defaults(fn=cmd_home)
    i = sub.add_parser("item")
    i.add_argument("--type", choices=TYPES, required=True)
    i.add_argument("--title", required=True)
    i.add_argument("--date")
    i.add_argument("--time")
    i.set_defaults(fn=cmd_item)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
