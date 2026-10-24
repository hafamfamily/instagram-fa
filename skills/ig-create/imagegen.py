#!/usr/bin/env python3
"""
imagegen.py - ساخت تصویر با هوش مصنوعی از سرویس‌های رایگان، در اندازهٔ دقیق اینستاگرام.

فقط کتابخانهٔ استاندارد پایتون و Pillow.

سرویس‌ها:
  pollinations  بدون ثبت‌نام. حدود یک تصویر در هر ۱۵ ثانیه؛ ممکن است واترمارک کوچک بگذارد.
                با ثبت‌نام رایگان در auth.pollinations.ai و ذخیرهٔ توکن، محدودیت و واترمارک برداشته می‌شود.
  cloudflare    حساب رایگان Cloudflare، مدل FLUX.1 schnell، حدود ۱۷۰ تصویر در روز رایگان (۱۰٬۰۰۰
                Neuron روزانه). کیفیت بهتر و پایدارتر. شناسهٔ حساب و توکن API لازم است.
  auto          اگر کلید cloudflare ذخیره شده، cloudflare؛ وگرنه pollinations.

کلیدها (هیچ‌وقت در گفتگو نفرست؛ در ترمینال وارد کن):
  python ../ig-publish/ig_api.py secret cf_account_id --page <پیج>
  python ../ig-publish/ig_api.py secret cf_token --page <پیج>
  python ../ig-publish/ig_api.py secret pollinations_token --page <پیج>     (اختیاری)
یا متغیرهای محیطی CF_ACCOUNT_ID، CF_API_TOKEN، POLLINATIONS_TOKEN.

پرامپت انگلیسی بهتر جواب می‌دهد. متن فارسی را روی تصویر نخواه (مدل‌ها فارسی را خراب می‌نویسند)؛
متن را موتور طراحی (render.py) می‌گذارد. به هر پرامپت «no text, no letters, no watermark» اضافه می‌شود.

استفاده:
  python imagegen.py "a tidy shop counter, warm morning light" --out <محتوا>/media/shop.jpg --size post
  python imagegen.py --batch prompts.json --page <پیج>      [{"prompt": "...", "out": "...", "size": "story"}, ...]
  python imagegen.py --check --page <پیج>

اندازه‌ها: post ۱۰۸۰×۱۳۵۰ (۴:۵)، story ۱۰۸۰×۱۹۲۰ (۹:۱۶)، square ۱۰۸۰×۱۰۸۰
اگر خروجی داخل پوشهٔ یک محتوا باشد، در status.json آن «ai_generated» ثبت می‌شود تا هنگام انتشار
برچسب رسمی «ساخته‌شده با هوش مصنوعی» بخورد.
"""

import argparse
import base64
import io
import json
import os
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from fa_text import setup_stdout  # noqa: E402

POLL = os.environ.get("IGFA_POLLINATIONS_URL", "https://image.pollinations.ai/prompt/")
CF = os.environ.get("IGFA_CLOUDFLARE_URL",
                    "https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/@cf/black-forest-labs/flux-1-schnell")
SIZES = {"post": (1080, 1350), "story": (1080, 1920), "square": (1080, 1080)}
SUFFIX = "no text, no letters, no words, no watermark, no logo"
UA = "instagram-fa/1.2"
POLL_GAP = 16


class GenError(Exception):
    pass


def secrets_for(page):
    s = {}
    if page:
        sys.path.insert(0, os.path.join(os.path.dirname(HERE), "ig-publish"))
        try:
            import settings
            s = settings.secrets(page)
        except Exception:
            s = {}
    return {
        "cf_account_id": os.environ.get("CF_ACCOUNT_ID") or s.get("cf_account_id"),
        "cf_token": os.environ.get("CF_API_TOKEN") or s.get("cf_token"),
        "pollinations_token": os.environ.get("POLLINATIONS_TOKEN") or s.get("pollinations_token"),
    }


def http(req, timeout=180, tries=3):
    last = None
    for k in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read(), r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:300]
            last = f"HTTP {e.code}: {body}"
            if e.code in (401, 403):
                raise GenError(f"دسترسی رد شد ({last}). کلید یا توکن را بررسی کن.")
            if e.code == 429:
                time.sleep(20 * (k + 1))
                continue
            if e.code < 500:
                raise GenError(last)
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = f"اتصال نشد: {e}. اینترنت (و در ایران فیلترشکن) را بررسی کن."
        time.sleep(5 * (k + 1))
    raise GenError(last)


def gen_pollinations(prompt, w, h, seed, keys):
    q = {"width": w, "height": h, "seed": seed, "nologo": "true", "model": "flux"}
    url = POLL + urllib.parse.quote(prompt, safe="") + "?" + urllib.parse.urlencode(q)
    headers = {"User-Agent": UA}
    if keys.get("pollinations_token"):
        headers["Authorization"] = "Bearer " + keys["pollinations_token"]
    data, ctype = http(urllib.request.Request(url, headers=headers))
    return data


def gen_cloudflare(prompt, w, h, seed, keys):
    if not keys.get("cf_account_id") or not keys.get("cf_token"):
        raise GenError("برای cloudflare شناسهٔ حساب و توکن لازم است (ig_api.py secret cf_account_id / cf_token).")
    body = json.dumps({"prompt": prompt, "steps": 6, "seed": seed}).encode()
    req = urllib.request.Request(CF.format(acct=keys["cf_account_id"]), data=body, method="POST",
                                 headers={"Authorization": "Bearer " + keys["cf_token"], "User-Agent": UA,
                                          "Content-Type": "application/json"})
    data, ctype = http(req)
    try:
        j = json.loads(data)
        if not j.get("success", True):
            raise GenError(f"cloudflare: {j.get('errors')}")
        return base64.b64decode(j["result"]["image"])
    except (ValueError, KeyError, TypeError):
        raise GenError(f"جواب نامعتبر cloudflare: {data[:200]!r}")


def fit(data, w, h, focus=(0.5, 0.5)):
    """تصویر خام ← دقیقاً w×h، با برش از مرکز (یا نقطهٔ focus)."""
    from PIL import Image, ImageOps
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:
        raise GenError("سرویس تصویر برنگرداند (احتمالاً پیام خطا یا صفحهٔ وب): " + data[:120].decode("utf-8", "replace"))
    im = ImageOps.exif_transpose(im).convert("RGB")
    return ImageOps.fit(im, (w, h), Image.LANCZOS, centering=focus)


def mark_item(out):
    """اگر خروجی داخل پوشهٔ یک محتواست، ai_generated را در status.json ثبت کن."""
    d = os.path.dirname(os.path.abspath(out))
    for cand in (d, os.path.dirname(d)):
        sp = os.path.join(cand, "status.json")
        if os.path.exists(sp):
            with open(sp, encoding="utf-8") as f:
                st = json.load(f)
            if not st.get("ai_generated"):
                st["ai_generated"] = True
                with open(sp, "w", encoding="utf-8") as f:
                    json.dump(st, f, ensure_ascii=False, indent=2)
            return


def generate(prompt, out, size="post", provider="auto", seed=None, page=None, focus=(0.5, 0.5), keys=None):
    w, h = SIZES.get(size, SIZES["post"])
    keys = keys or secrets_for(page)
    if provider == "auto":
        provider = "cloudflare" if keys.get("cf_account_id") and keys.get("cf_token") else "pollinations"
    seed = seed if seed is not None else random.randint(1, 2 ** 31 - 1)
    full = prompt.strip().rstrip(".") + ". " + SUFFIX
    fn = {"pollinations": gen_pollinations, "cloudflare": gen_cloudflare}.get(provider)
    if not fn:
        raise GenError(f"سرویس ناشناخته: {provider}")
    data = fn(full, w, h, seed, keys)
    im = fit(data, w, h, focus)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    im.save(out, "JPEG", quality=92, optimize=True) if out.lower().endswith((".jpg", ".jpeg")) else im.save(out)
    with open(os.path.splitext(out)[0] + ".prompt.json", "w", encoding="utf-8") as f:
        json.dump({"provider": provider, "prompt": prompt, "seed": seed, "size": size}, f, ensure_ascii=False, indent=2)
    mark_item(out)
    return provider, seed


def main():
    setup_stdout()
    ap = argparse.ArgumentParser(description="تصویر با هوش مصنوعی (رایگان)")
    ap.add_argument("prompt", nargs="?")
    ap.add_argument("--out")
    ap.add_argument("--size", choices=list(SIZES), default="post")
    ap.add_argument("--provider", choices=["auto", "pollinations", "cloudflare"], default="auto")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--focus", default="0.5,0.5", help="نقطهٔ برش، مثلاً 0.5,0.35")
    ap.add_argument("--page")
    ap.add_argument("--batch", help="فایل JSON: فهرست {prompt, out, size, seed}")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    keys = secrets_for(a.page)
    if a.check:
        cf = bool(keys.get("cf_account_id") and keys.get("cf_token"))
        print(f"cloudflare:   {'کلید ذخیره شده' if cf else 'کلید ندارد'}")
        print(f"pollinations: {'با توکن' if keys.get('pollinations_token') else 'بدون توکن (کندتر، شاید با واترمارک)'}")
        print(f"پیش‌فرض: {'cloudflare' if cf else 'pollinations'}")
        return
    focus = tuple(float(x) for x in a.focus.split(","))
    jobs = []
    if a.batch:
        with open(a.batch, encoding="utf-8") as f:
            jobs = json.load(f)
        base = os.path.dirname(os.path.abspath(a.batch))
        for j in jobs:
            if not os.path.isabs(j["out"]):
                j["out"] = os.path.join(base, j["out"])
    elif a.prompt and a.out:
        jobs = [{"prompt": a.prompt, "out": a.out, "size": a.size, "seed": a.seed}]
    else:
        ap.error("پرامپت و --out، یا --batch لازم است")
    fails = 0
    last_poll = 0.0
    for k, j in enumerate(jobs, 1):
        prov = a.provider
        if prov in ("auto", "pollinations") and not (keys.get("cf_account_id") and keys.get("cf_token")) \
                and not keys.get("pollinations_token"):
            wait = POLL_GAP - (time.time() - last_poll)
            if last_poll and wait > 0:
                time.sleep(wait)
        try:
            used, seed = generate(j["prompt"], j["out"], j.get("size", a.size), prov, j.get("seed"), a.page,
                                  tuple(j.get("focus", focus)), keys)
            last_poll = time.time()
            print(f"  ✓ {k}/{len(jobs)}  {os.path.basename(j['out'])}  ({used}، seed {seed})")
        except GenError as e:
            fails += 1
            print(f"  ✗ {k}/{len(jobs)}  {os.path.basename(j['out'])}: {e}", file=sys.stderr)
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
