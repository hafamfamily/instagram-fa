"""
settings.py - تنظیمات انتشار هر پیج (publish.json) و فایل رمزها.

publish.json کنار page.md در پوشهٔ پیج است و چیز محرمانه‌ای ندارد:
  {
    "mode": "manual" | "auto",      manual: هر محتوا با «بله»ی صاحب پیج؛ auto: بعد از چک‌های فنی، بی‌سؤال
    "method": "manual" | "api",     manual: خودش از گوشی منتشر می‌کند؛ api: انتشار خودکار با API رسمی
    "hosting": {"provider": "litterbox", "time": "24h"},
    "share_to_feed": true,          ریلز در تب فید هم بیاید
    "ai_label": true                اگر تصویر با هوش مصنوعی ساخته شده، برچسب is_ai_generated بخورد
  }

رمزها (توکن اینستاگرام، رمز FTP) در فایل جدا:
  <خانهٔ پیج‌ها>/.secrets/<نام پیج>.json
که فقط برای کاربر خود سیستم خواندنی است. این فایل را هیچ‌وقت در گیت، گفتگو یا جای عمومی نگذار.
"""

import json
import os
import stat

DEFAULTS = {
    "mode": "manual",
    "method": "manual",
    "hosting": {"provider": "litterbox", "time": "24h"},
    "share_to_feed": True,
    "ai_label": True,
}
MODES = {"manual": "دستی (با تأیید تو)", "auto": "خودکار (بدون پرسیدن)"}
METHODS = {"manual": "خودت از گوشی منتشر می‌کنی", "api": "انتشار خودکار با API رسمی اینستاگرام"}


def path(page):
    return os.path.join(page, "publish.json")


def load(page):
    cfg = json.loads(json.dumps(DEFAULTS))
    p = path(page)
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            user = json.load(f)
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    return cfg


def save(page, cfg):
    with open(path(page), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def secrets_path(page):
    page = os.path.abspath(page)
    return os.path.join(os.path.dirname(page), ".secrets", os.path.basename(page) + ".json")


def secrets(page):
    p = secrets_path(page)
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save_secrets(page, data):
    p = secrets_path(page)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    os.replace(tmp, p)
