#!/usr/bin/env python3
"""
mock_meta.py - سرور شبیه‌ساز API اینستاگرام و سرویس آپلود، فقط برای تست publish.py بدون حساب واقعی.

  python tools/mock_meta.py 8765
  IGFA_GRAPH_BASE=http://127.0.0.1:8765 IGFA_LITTERBOX_URL=http://127.0.0.1:8765/litterbox python publish.py ...

رفتار:
  - هر فایل آپلودشده در حافظه نگه داشته و با /files/<نام> برگردانده می‌شود.
  - ساخت ظرف (media) بررسی می‌کند که image_url/video_url واقعاً قابل دریافت است و تصویر JPEG است.
  - ظرف ویدیو اول IN_PROGRESS و بعد FINISHED می‌شود.
  - GET /_log همهٔ درخواست‌ها را برمی‌گرداند (برای بررسی در تست).
  - POST /_fail?code=2&times=1  دفعه‌های بعدی ساخت ظرف را با این کد خطا رد می‌کند.
"""

import json
import sys
import threading
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = "TESTTOKEN_0123456789abcdef"
UID = "17841400000000001"
state = {"files": {}, "containers": {}, "media": {}, "log": [], "fail": None, "n": 0}
lock = threading.Lock()


def parse_multipart(body, ctype):
    boundary = ctype.split("boundary=")[1].encode()
    out = {}
    for part in body.split(b"--" + boundary):
        if b"\r\n\r\n" not in part:
            continue
        head, data = part.split(b"\r\n\r\n", 1)
        data = data[:-2] if data.endswith(b"\r\n") else data
        h = head.decode("utf-8", "replace")
        name = h.split('name="')[1].split('"')[0]
        fn = h.split('filename="')[1].split('"')[0] if 'filename="' in h else None
        out[name] = (fn, data)
    return out


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, obj, ctype="application/json"):
        body = obj if isinstance(obj, bytes) else (json.dumps(obj) if not isinstance(obj, str) else obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def err(self, code, msg, http=400, transient=False):
        self.send(http, {"error": {"message": msg, "code": code, "is_transient": transient}})

    def params(self):
        u = urllib.parse.urlparse(self.path)
        q = dict(urllib.parse.parse_qsl(u.query))
        if self.command == "POST" and "multipart" not in self.headers.get("Content-Type", ""):
            n = int(self.headers.get("Content-Length", 0))
            q.update(urllib.parse.parse_qsl(self.rfile.read(n).decode()))
        return u.path, q

    def do_GET(self):
        path, q = self.params()
        with lock:
            state["log"].append({"m": "GET", "path": path, "q": {k: v for k, v in q.items() if k != "access_token"}})
        if path.startswith("/files/"):
            data = state["files"].get(path[7:])
            return self.send(200, data, "application/octet-stream") if data else self.send(404, "nf", "text/plain")
        if path == "/_log":
            return self.send(200, state["log"])
        if path == "/refresh_access_token":
            if q.get("access_token") != TOKEN:
                return self.err(190, "Invalid OAuth access token", 400)
            return self.send(200, {"access_token": TOKEN, "token_type": "bearer", "expires_in": 5183944})
        if q.get("access_token") != TOKEN:
            return self.err(190, "Invalid OAuth access token", 400)
        parts = path.strip("/").split("/")[1:]
        if parts == ["me"]:
            return self.send(200, {"user_id": UID, "id": "99", "username": "test_page", "account_type": "BUSINESS"})
        if parts == [UID, "content_publishing_limit"]:
            return self.send(200, {"data": [{"quota_usage": len(state["media"]), "config": {"quota_total": 100}}]})
        if len(parts) == 1 and parts[0] in state["containers"]:
            c = state["containers"][parts[0]]
            if c["polls"] > 0:
                c["polls"] -= 1
                return self.send(200, {"status_code": "IN_PROGRESS", "id": parts[0]})
            return self.send(200, {"status_code": "PUBLISHED" if c.get("published") else "FINISHED", "id": parts[0]})
        if len(parts) == 1 and parts[0] in state["media"]:
            return self.send(200, {"permalink": f"https://www.instagram.com/p/{parts[0]}/", "id": parts[0]})
        return self.err(100, f"Unknown path {path}", 404)

    def do_POST(self):
        ctype = self.headers.get("Content-Type", "")
        if self.path.startswith("/litterbox") or self.path.startswith("/cloudinary"):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            parts = parse_multipart(body, ctype)
            key = "fileToUpload" if "fileToUpload" in parts else "file"
            fn, data = parts[key]
            with lock:
                state["n"] += 1
                name = f"{state['n']}-{fn}"
                state["files"][name] = data
                state["log"].append({"m": "UPLOAD", "name": name, "size": len(data)})
            url = f"http://127.0.0.1:{self.server.server_port}/files/{name}"
            return self.send(200, url if key == "fileToUpload" else {"secure_url": url},
                             "text/plain" if key == "fileToUpload" else "application/json")
        path, q = self.params()
        if path == "/_fail":
            state["fail"] = {"code": int(q.get("code", 2)), "times": int(q.get("times", 1))}
            return self.send(200, {"ok": True})
        with lock:
            state["log"].append({"m": "POST", "path": path, "q": {k: v for k, v in q.items() if k != "access_token"}})
        if q.get("access_token") != TOKEN:
            return self.err(190, "Invalid OAuth access token", 400)
        parts = path.strip("/").split("/")[1:]
        if parts == [UID, "media"]:
            f = state["fail"]
            if f and f["times"] > 0:
                f["times"] -= 1
                return self.err(f["code"], "simulated failure", 500 if f["code"] in (1, 2) else 400,
                                transient=f["code"] in (1, 2))
            kind = "image" if "image_url" in q else "video" if "video_url" in q else None
            if q.get("media_type") == "CAROUSEL":
                kids = q.get("children", "").split(",")
                if not (2 <= len(kids) <= 20) or any(k not in state["containers"] for k in kids):
                    return self.err(100, "bad children")
                if "caption" not in q:
                    pass
            elif kind is None:
                return self.err(100, "image_url or video_url required")
            else:
                url = q.get("image_url") or q.get("video_url")
                try:
                    data = urllib.request.urlopen(url, timeout=10).read()
                except Exception as e:
                    return self.err(9004, f"Media download failed: {e}")
                if kind == "image" and not data.startswith(b"\xff\xd8"):
                    return self.err(9004, "Only JPEG images are supported")
                if kind == "video" and b"ftyp" not in data[:64]:
                    return self.err(9004, "Not an MP4")
                if q.get("is_carousel_item") == "true" and "caption" in q:
                    return self.err(100, "caption not supported on carousel items")
                if q.get("media_type") in ("STORIES",) and "caption" in q:
                    return self.err(100, "caption not supported on stories")
            with lock:
                state["n"] += 1
                cid = f"c{state['n']}"
                state["containers"][cid] = {"q": q, "polls": 2 if kind == "video" else 0}
            return self.send(200, {"id": cid})
        if parts == [UID, "media_publish"]:
            cid = q.get("creation_id")
            c = state["containers"].get(cid)
            if not c:
                return self.err(100, "bad creation_id")
            if c["polls"] > 0:
                return self.err(9007, "Media not ready", 400, transient=True)
            if c.get("published"):
                return self.err(100, "already published")
            c["published"] = True
            with lock:
                state["n"] += 1
                mid = f"m{state['n']}"
                state["media"][mid] = cid
            return self.send(200, {"id": mid})
        return self.err(100, f"Unknown path {path}", 404)


def serve(port):
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    return srv


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    print(f"mock on {port}")
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
