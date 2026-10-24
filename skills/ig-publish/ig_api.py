#!/usr/bin/env python3
"""
ig_api.py - اتصال به API رسمی اینستاگرام (Instagram API with Instagram Login) برای انتشار.

فقط کتابخانهٔ استاندارد پایتون. مستندات: developers.facebook.com/documentation/instagram-platform

پیش‌نیاز (یک بار، راهنمای قدم‌به‌قدم در ig-publish/API-SETUP.md):
  حساب اینستاگرام حرفه‌ای (Business یا Creator) + یک اپ در Meta for Developers با محصول
  «Instagram API with Instagram Login» و دسترسی instagram_business_basic و
  instagram_business_content_publish + یک توکن بلندمدت.

دستورها:
  python ig_api.py login  --page <پیج>     توکن را خودت (در ترمینال، نه در گفتگو) وارد می‌کنی؛ بررسی و ذخیره
  python ig_api.py status --page <پیج>     حساب وصل‌شده، عمر توکن، سهمیهٔ انتشار امروز
  python ig_api.py refresh --page <پیج>    تمدید توکن (۶۰ روز دیگر)؛ publish.py خودش هم خودکار تمدید می‌کند
  python ig_api.py logout --page <پیج>     پاک کردن توکن
  python ig_api.py secret ftp_password --page <پیج>   ذخیرهٔ رمز FTP (برای میزبانی روی هاست خودت)

توکن هرگز در خروجی چاپ نمی‌شود و فقط در فایل رمزهای همان پیج می‌ماند.
"""

import argparse
import datetime as dt
import getpass
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import settings  # noqa: E402

VERSION = os.environ.get("IGFA_GRAPH_VERSION", "v26.0")
BASE = os.environ.get("IGFA_GRAPH_BASE", "https://graph.instagram.com")
UA = "instagram-fa/1.2"
REFRESH_AFTER_DAYS = 30   # توکن ۶۰ روز اعتبار دارد؛ از روز ۳۰ به بعد در هر اجرا تمدید می‌شود


class ApiError(Exception):
    def __init__(self, msg, code=None, transient=False):
        super().__init__(msg)
        self.code, self.transient = code, transient


def _err(body, status):
    try:
        e = json.loads(body).get("error", {})
    except ValueError:
        return ApiError(f"HTTP {status}: {body[:300]}", transient=status >= 500)
    code = e.get("code")
    msg = e.get("error_user_msg") or e.get("message") or body[:300]
    # 1، 2: خطای موقت سرور؛ 4، 17، 32، 613: محدودیت تعداد درخواست؛ 9007: محتوا هنوز آماده نیست
    transient = bool(e.get("is_transient")) or code in (1, 2, 4, 17, 32, 613, 9007) or status >= 500
    hint = {190: " (توکن نامعتبر یا منقضی است؛ ig_api.py login را دوباره اجرا کن)",
            10: " (دسترسی کافی نیست؛ instagram_business_content_publish را در اپ فعال کن)",
            200: " (دسترسی کافی نیست)",
            9004: " (اینستاگرام نتوانست فایل را از آدرس عمومی بردارد؛ سرویس میزبانی را عوض کن)",
            36003: " (نسبت ابعاد تصویر مجاز نیست؛ پست باید بین ۴:۵ و ۱٫۹۱:۱ باشد)"}.get(code, "")
    return ApiError(f"{msg}{hint} [کد {code}]", code=code, transient=transient)


def call(method, path, params, token, tries=4, timeout=120):
    """درخواست به API. توکن در بدنهٔ POST یا پارامتر GET می‌رود، هیچ‌وقت در لاگ."""
    params = dict(params or {}, access_token=token)
    url = path if path.startswith("http") else f"{BASE}/{VERSION}/{path.lstrip('/')}"
    last = None
    for k in range(tries):
        if method == "GET":
            req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers={"User-Agent": UA})
        else:
            req = urllib.request.Request(url, data=urllib.parse.urlencode(params).encode(), method="POST",
                                         headers={"User-Agent": UA,
                                                  "Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = _err(e.read().decode("utf-8", "replace"), e.code)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = ApiError(f"اتصال به اینستاگرام برقرار نشد: {e}. اینترنت (و در ایران فیلترشکن) را بررسی کن.",
                            transient=True)
        if not last.transient:
            raise last
        time.sleep(min(60, 5 * 2 ** k))
    raise last


# ---------- توکن ----------

def _now():
    return dt.datetime.now(dt.timezone.utc)


def token_info(page):
    s = settings.secrets(page)
    t = s.get("instagram")
    if not t or not t.get("access_token"):
        raise ApiError("هنوز به اینستاگرام وصل نشده‌ای. اجرا کن: python ig_api.py login --page <پیج>")
    return s, t


def ensure_token(page, quiet=True):
    """توکن معتبر را برمی‌گرداند و اگر کهنه شده، بی‌سروصدا تمدیدش می‌کند."""
    s, t = token_info(page)
    saved = dt.datetime.fromisoformat(t["saved_at"])
    age = (_now() - saved).days
    if age >= REFRESH_AFTER_DAYS:
        try:
            refresh(page)
            s, t = token_info(page)
        except ApiError as e:
            if not quiet:
                print(f"تمدید توکن نشد: {e}", file=sys.stderr)
    return t["access_token"], t["user_id"]


def refresh(page):
    s, t = token_info(page)
    r = call("GET", f"{BASE}/refresh_access_token", {"grant_type": "ig_refresh_token"}, t["access_token"])
    t["access_token"] = r["access_token"]
    t["saved_at"] = _now().isoformat(timespec="seconds")
    if r.get("expires_in"):
        t["expires_at"] = (_now() + dt.timedelta(seconds=int(r["expires_in"]))).isoformat(timespec="seconds")
    s["instagram"] = t
    settings.save_secrets(page, s)
    return t


def whoami(token):
    return call("GET", "me", {"fields": "user_id,username,account_type"}, token)


# ---------- انتشار ----------

def create(user_id, token, **params):
    params = {k: v for k, v in params.items() if v is not None}
    for k, v in list(params.items()):
        if isinstance(v, bool):
            params[k] = "true" if v else "false"
    return call("POST", f"{user_id}/media", params, token)["id"]


def wait(container, token, timeout=600, every=10, log=None):
    """تا آماده شدن محتوا (مخصوصاً ویدیو) صبر می‌کند."""
    t0 = time.time()
    while True:
        st = call("GET", container, {"fields": "status_code,status"}, token).get("status_code")
        if st in ("FINISHED", "PUBLISHED"):
            return st
        if st in ("ERROR", "EXPIRED"):
            detail = call("GET", container, {"fields": "status"}, token).get("status", "")
            raise ApiError(f"پردازش فایل در اینستاگرام ناموفق بود ({st}): {detail}")
        if time.time() - t0 > timeout:
            raise ApiError("پردازش ویدیو بیش از حد طول کشید؛ بعداً دوباره امتحان کن.", transient=True)
        if log:
            log(f"   در حال پردازش در اینستاگرام ({int(time.time() - t0)} ثانیه)…")
        time.sleep(every)


def publish(user_id, token, creation_id):
    # گاهی ظرف تازه FINISHED شده ولی هنوز قابل انتشار نیست (کد 9007)؛ call خودش دوباره امتحان می‌کند
    media_id = call("POST", f"{user_id}/media_publish", {"creation_id": creation_id}, token)["id"]
    try:
        link = call("GET", media_id, {"fields": "permalink"}, token).get("permalink", "")
    except ApiError:
        link = ""
    return media_id, link


def quota(user_id, token):
    r = call("GET", f"{user_id}/content_publishing_limit", {"fields": "config,quota_usage"}, token)
    d = (r.get("data") or [{}])[0]
    return d.get("quota_usage"), (d.get("config") or {}).get("quota_total")


# ---------- خط فرمان ----------

def cmd_login(a):
    print("توکن بلندمدت اینستاگرام را وارد کن (دیده نمی‌شود؛ بعد Enter).")
    print("راهنمای گرفتن توکن: ig-publish/API-SETUP.md")
    tok = os.environ.get(a.from_env) if a.from_env else getpass.getpass("توکن: ")
    tok = (tok or "").strip()
    if len(tok) < 20:
        print("توکن خالی یا کوتاه است.", file=sys.stderr)
        sys.exit(2)
    me = whoami(tok)
    uid = me.get("user_id") or me.get("id")
    s = settings.secrets(a.page)
    s["instagram"] = {"access_token": tok, "user_id": str(uid), "username": me.get("username", ""),
                      "account_type": me.get("account_type", ""),
                      "saved_at": _now().isoformat(timespec="seconds")}
    settings.save_secrets(a.page, s)
    cfg = settings.load(a.page)
    cfg["method"] = "api"
    settings.save(a.page, cfg)
    print(f"وصل شد: @{me.get('username', '?')} ({me.get('account_type', '')})")
    print("روش انتشار این پیج روی «API» گذاشته شد.")


def cmd_status(a):
    try:
        tok, uid = ensure_token(a.page, quiet=False)
    except ApiError as e:
        print(e)
        sys.exit(1)
    _, t = token_info(a.page)
    me = whoami(tok)
    print(f"حساب: @{me.get('username')}  ·  نوع: {me.get('account_type', '?')}  ·  شناسه: {uid}")
    print(f"توکن ذخیره/تمدید شده: {t['saved_at'][:10]}" + (f"  ·  انقضا: {t['expires_at'][:10]}"
                                                           if t.get("expires_at") else ""))
    try:
        used, total = quota(uid, tok)
        print(f"انتشار با API در ۲۴ ساعت گذشته: {used} از {total or '?'}")
    except ApiError as e:
        print(f"سهمیه خوانده نشد: {e}")


def cmd_refresh(a):
    t = refresh(a.page)
    print("توکن تمدید شد" + (f" تا {t['expires_at'][:10]}." if t.get("expires_at") else "."))


def cmd_logout(a):
    s = settings.secrets(a.page)
    s.pop("instagram", None)
    settings.save_secrets(a.page, s)
    cfg = settings.load(a.page)
    cfg["method"] = "manual"
    settings.save(a.page, cfg)
    print("توکن پاک شد؛ روش انتشار به «دستی» برگشت.")


def cmd_secret(a):
    val = getpass.getpass(f"{a.name}: ").strip()
    s = settings.secrets(a.page)
    s[a.name] = val
    settings.save_secrets(a.page, s)
    print("ذخیره شد.")


def main():
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="اتصال به API اینستاگرام")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("login", cmd_login), ("status", cmd_status), ("refresh", cmd_refresh), ("logout", cmd_logout)):
        p = sub.add_parser(name)
        p.add_argument("--page", required=True)
        if name == "login":
            p.add_argument("--from-env", help="توکن را از این متغیر محیطی بخوان (برای اسکریپت‌ها)")
        p.set_defaults(fn=fn)
    p = sub.add_parser("secret")
    p.add_argument("name", choices=["ftp_password"])
    p.add_argument("--page", required=True)
    p.set_defaults(fn=cmd_secret)
    a = ap.parse_args()
    try:
        a.fn(a)
    except ApiError as e:
        print(f"خطا: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
