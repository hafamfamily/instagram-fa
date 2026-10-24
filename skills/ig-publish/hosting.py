#!/usr/bin/env python3
"""
hosting.py - بالا بردن عکس و ویدیو روی یک آدرس عمومی، چون API اینستاگرام فایل را خودش از
یک URL عمومی برمی‌دارد و فایل روی کامپیوتر تو را نمی‌بیند.

فقط کتابخانهٔ استاندارد پایتون؛ نصب چیزی لازم نیست.

سرویس‌ها (در publish.json پیج، بخش "hosting"):
  litterbox   پیش‌فرض. رایگان، بدون ثبت‌نام. فایل بعد از مدت کوتاهی (پیش‌فرض ۲۴ ساعت) خودش پاک
              می‌شود؛ برای انتشار کافی است چون اینستاگرام در همان لحظه فایل را برمی‌دارد.
              {"provider": "litterbox", "time": "24h"}
  cloudinary  رایگان با ثبت‌نام (پلن Free). یک «upload preset» از نوع Unsigned بساز.
              {"provider": "cloudinary", "cloud_name": "...", "upload_preset": "..."}
  ftp         هاست خودت (مثلاً دامنهٔ خودت). فایل‌ها در یک پوشه آپلود و با آدرس پایه خوانده می‌شوند.
              {"provider": "ftp", "host": "ftp.example.com", "user": "...", "dir": "/public_html/ig",
               "base_url": "https://example.com/ig", "tls": true}
              رمز FTP در فایل رمزها (secrets) نگه داشته می‌شود، نه در publish.json.

استفاده (تست دستی):
  python hosting.py upload <فایل> --page <پوشهٔ پیج>
"""

import argparse
import ftplib
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

UA = "instagram-fa/1.2 (+https://github.com/hafamfamily/instagram-fa)"
# برای تست با سرور شبیه‌ساز می‌شود این آدرس‌ها را با متغیر محیطی عوض کرد
LITTERBOX = os.environ.get("IGFA_LITTERBOX_URL", "https://litterbox.catbox.moe/resources/internals/api.php")
CLOUDINARY = os.environ.get("IGFA_CLOUDINARY_URL", "https://api.cloudinary.com/v1_1/{cloud}/auto/upload")


class HostingError(Exception):
    pass


def multipart(fields, files):
    """fields: {name: value}، files: {name: path} ← (body, content_type)"""
    boundary = "----igfa" + uuid.uuid4().hex
    parts = []
    for k, v in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for k, path in files.items():
        name = os.path.basename(path)
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        with open(path, "rb") as f:
            data = f.read()
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{name}"\r\n'
                     f"Content-Type: {ctype}\r\n\r\n".encode() + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def post(url, fields, files, timeout=300, tries=3):
    body, ctype = multipart(fields, files)
    last = None
    for k in range(tries):
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={"Content-Type": ctype, "User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}"
            if e.code < 500:
                break
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last = str(e)
        time.sleep(3 * (k + 1))
    raise HostingError(f"آپلود به {url.split('/')[2]} نشد: {last}")


def up_litterbox(path, cfg, secrets):
    t = cfg.get("time", "24h")
    if t not in ("1h", "12h", "24h", "72h"):
        t = "24h"
    out = post(LITTERBOX, {"reqtype": "fileupload", "time": t}, {"fileToUpload": path}).strip()
    if not out.startswith("http"):
        raise HostingError(f"جواب نامعتبر litterbox: {out[:200]}")
    return out


def up_cloudinary(path, cfg, secrets):
    cloud, preset = cfg.get("cloud_name"), cfg.get("upload_preset")
    if not cloud or not preset:
        raise HostingError("برای cloudinary باید cloud_name و upload_preset در publish.json باشد.")
    out = post(CLOUDINARY.format(cloud=cloud), {"upload_preset": preset}, {"file": path})
    try:
        return json.loads(out)["secure_url"]
    except (ValueError, KeyError):
        raise HostingError(f"جواب نامعتبر cloudinary: {out[:200]}")


def up_ftp(path, cfg, secrets):
    for k in ("host", "user", "dir", "base_url"):
        if not cfg.get(k):
            raise HostingError(f"برای ftp باید «{k}» در publish.json باشد.")
    pw = secrets.get("ftp_password")
    if not pw:
        raise HostingError("رمز FTP ذخیره نشده؛ اجرا کن: python ig_api.py secret ftp_password --page <پیج>")
    name = f"{int(time.time())}-{uuid.uuid4().hex[:8]}{os.path.splitext(path)[1].lower()}"
    cls = ftplib.FTP_TLS if cfg.get("tls", True) else ftplib.FTP
    try:
        ftp = cls(cfg["host"], timeout=60)
        ftp.login(cfg["user"], pw)
        if cls is ftplib.FTP_TLS:
            ftp.prot_p()
        ftp.cwd(cfg["dir"])
        with open(path, "rb") as f:
            ftp.storbinary(f"STOR {name}", f)
        ftp.quit()
    except ftplib.all_errors as e:
        raise HostingError(f"FTP نشد: {e}")
    return cfg["base_url"].rstrip("/") + "/" + name


PROVIDERS = {"litterbox": up_litterbox, "cloudinary": up_cloudinary, "ftp": up_ftp}


def upload(path, cfg=None, secrets=None):
    cfg = cfg or {"provider": "litterbox"}
    prov = cfg.get("provider", "litterbox")
    if prov not in PROVIDERS:
        raise HostingError(f"سرویس میزبانی ناشناخته: {prov} (یکی از {', '.join(PROVIDERS)})")
    return PROVIDERS[prov](path, cfg, secrets or {})


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="آپلود فایل روی آدرس عمومی")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("upload")
    p.add_argument("file")
    p.add_argument("--page", required=True)
    a = ap.parse_args()
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import settings
    cfg = settings.load(a.page).get("hosting")
    try:
        print(upload(a.file, cfg, settings.secrets(a.page)))
    except HostingError as e:
        print(e, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
