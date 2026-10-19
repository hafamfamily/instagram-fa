#!/usr/bin/env python3
"""
render.py - ساخت تصویرهای آمادهٔ انتشار (پست، کاروسل، استوری، کاور و فریم ریلز)
از یک فایل spec.json، با فونت وزیرمتن و چیدمان راست‌به‌چپ.

هر اسلاید یک صفحهٔ HTML می‌شود و با مرورگر بی‌سر (Chrome، Edge یا Chromium) عکس گرفته
می‌شود. متن‌های بلند خودکار کوچک می‌شوند تا جا شوند؛ اگر حتی با کوچک‌ترین اندازه هم
جا نشوند، اسلاید با «سرریز» علامت می‌خورد و باید متنش کوتاه شود.

اندازه‌ها:
  post   1080×1350  (کاروسل و پست تکی؛ نسبت ۴:۵)
  square 1080×1080
  story  1080×1920  (استوری؛ ۲۵۰ پیکسل بالا و ۳۴۰ پایین خالی می‌ماند برای رابط اینستاگرام)
  reel   1080×1920  (فریم و کاور ریلز؛ متن اصلی در میانهٔ امن)

استفاده:
  python render.py spec.json --page <پوشهٔ پیج> --out <پوشهٔ خروجی>
  python render.py spec.json --page ... --out ... --only 3      # فقط اسلاید ۳
  python render.py --check                                      # آیا مرورگر پیدا می‌شود؟

قالب spec.json را در ig-create/SKILL.md ببین. نمونه: ig-create/examples/
"""

import argparse
import base64
import glob
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from fa_text import setup_stdout, to_fa_digits  # noqa: E402

SIZES = {"post": (1080, 1350), "square": (1080, 1080), "story": (1080, 1920), "reel": (1080, 1920)}
TYPE_FORMAT = {"carousel": "post", "single": "post", "square": "square", "story": "story", "reel": "reel"}

DEFAULT_BRAND = {
    "name": "", "handle": "@your.page",
    "bg": "#FBF7F1", "surface": "#FFFFFF", "text": "#1E2430", "muted": "#6B7280",
    "primary": "#0F766E", "accent": "#F59E0B", "on_primary": "#FFFFFF",
    "theme": "light", "digits": "fa", "corner": 28,
}
DARK = {"bg": "#111827", "surface": "#1F2937", "text": "#F9FAFB", "muted": "#9CA3AF"}

WEIGHTS = {"Regular": 400, "Medium": 500, "Bold": 700, "Black": 900}


# ---------------------------------------------------------------- brand & fonts

def load_brand(page_dir, override=None):
    brand = dict(DEFAULT_BRAND)
    if page_dir:
        p = os.path.join(page_dir, "brand.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                brand.update(json.load(f))
    brand.update(override or {})
    if brand.get("theme") == "dark":
        for k, v in DARK.items():
            if brand.get(k) == DEFAULT_BRAND[k]:
                brand[k] = v
    return brand


_FONT_CSS = None


def font_css():
    global _FONT_CSS
    if _FONT_CSS is None:
        parts = []
        for name, w in WEIGHTS.items():
            path = os.path.join(HERE, "fonts", f"Vazirmatn-{name}.ttf")
            if os.path.exists(path):
                with open(path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode()
                parts.append(f"@font-face{{font-family:'Vazirmatn';font-weight:{w};"
                             f"src:url(data:font/ttf;base64,{b64}) format('truetype');}}")
        _FONT_CSS = "\n".join(parts)
    return _FONT_CSS


# ---------------------------------------------------------------- text helpers

def digits(text, brand):
    if brand.get("digits") != "fa":
        return text
    # رقم‌های چسبیده به حروف لاتین (مثل GPT-4o) دست نمی‌خورند
    return re.sub(r"(?<![A-Za-z\-_.])\d+(?:[.,]\d+)*(?![A-Za-z])", lambda m: to_fa_digits(m.group()), text)


def rich(text, brand, keep_digits=False):
    """متن ساده به HTML: **پررنگ** با رنگ تأکید، خط جدید به <br>."""
    if text is None:
        return ""
    t = html.escape(str(text))
    if not keep_digits:
        t = digits(t, brand)
    t = re.sub(r"\*\*(.+?)\*\*", r'<b class="hl">\1</b>', t)
    return t.replace("\n", "<br>")


def img_data(path, base_dir):
    if not path:
        return ""
    p = path if os.path.isabs(path) else os.path.join(base_dir, path)
    if not os.path.exists(p):
        raise FileNotFoundError(f"تصویر پیدا نشد: {p}")
    ext = os.path.splitext(p)[1].lower().lstrip(".")
    mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp", "gif": "gif"}.get(ext, "png")
    with open(p, "rb") as f:
        return f"data:image/{mime};base64,{base64.b64encode(f.read()).decode()}"


# ---------------------------------------------------------------- layouts

def layout_body(s, brand, ctx):
    L = s.get("layout", "text")
    r = lambda k, **kw: rich(s.get(k), brand, **kw)  # noqa: E731
    kicker = f'<div class="kicker">{r("kicker")}</div>' if s.get("kicker") else ""

    if L == "cover":
        return f"""{kicker}
<div class="fit grow center-v"><h1 class="title xl">{r('title')}</h1>
{f'<p class="sub">{r("subtitle")}</p>' if s.get('subtitle') else ''}</div>"""

    if L == "text":
        return f"""{kicker}{f'<h2 class="title">{r("title")}</h2>' if s.get('title') else ''}
<div class="fit grow center-v"><p class="body">{r('body')}</p></div>"""

    if L in ("list", "steps"):
        items = "".join(
            f'<li><span class="num">{digits(str(i), brand)}</span><span class="it">{rich(x, brand)}</span></li>'
            for i, x in enumerate(s.get("items", []), 1))
        return f"""{kicker}{f'<h2 class="title">{r("title")}</h2>' if s.get('title') else ''}
<div class="fit grow center-v"><ol class="list {'steps' if L == 'steps' else ''}">{items}</ol></div>"""

    if L == "quote":
        return f"""{kicker}<div class="fit grow center-v"><div class="qwrap">
<p class="quote">{r('text')}</p></div>{f'<p class="by">— {r("by")}</p>' if s.get('by') else ''}</div>"""

    if L == "compare":
        return f"""{kicker}{f'<h2 class="title">{r("title")}</h2>' if s.get('title') else ''}
<div class="fit grow cmp">
 <div class="box bad"><div class="lab">{rich(s.get('left_label', 'قبل'), brand)}</div><p>{r('left')}</p></div>
 <div class="box good"><div class="lab">{rich(s.get('right_label', 'بعد'), brand)}</div><p>{r('right')}</p></div>
</div>"""

    if L == "stat":
        src = f'<p class="src">منبع: {r("source")}</p>' if s.get("source") else ""
        return f"""{kicker}<div class="fit grow center-v"><div class="stat">{r('number')}</div>
<p class="sub">{r('label')}</p>{src}</div>"""

    if L == "prompt":
        return f"""{kicker}{f'<h2 class="title">{r("title")}</h2>' if s.get('title') else ''}
<div class="fit grow center-v"><div class="prompt"><div class="ptag">{rich(s.get('tag', 'پرامپت'), brand)}</div>
<p dir="auto">{rich(s.get('text'), brand, keep_digits=True)}</p></div>
{f'<p class="note">{r("note")}</p>' if s.get('note') else ''}</div>"""

    if L == "image":
        src = img_data(s.get("src"), ctx["base"])
        return f"""{kicker}{f'<h2 class="title">{r("title")}</h2>' if s.get('title') else ''}
<div class="grow imgwrap"><img src="{src}" alt=""></div>
{f'<div class="fit capbox"><p class="note">{r("caption")}</p></div>' if s.get('caption') else ''}"""

    if L == "cta":
        return f"""{kicker}<div class="fit grow center-v"><h2 class="title xl">{r('title')}</h2>
<div class="action">{r('action')}</div>
{f'<p class="sub">{r("subtitle")}</p>' if s.get('subtitle') else ''}</div>"""

    if L in ("story", "reel-frame", "reel-cover"):
        sticker = s.get("sticker")
        stk = ""
        if sticker and sticker != "none":
            names = {"poll": "استیکر نظرسنجی", "question": "استیکر سؤال", "link": "استیکر لینک",
                     "quiz": "استیکر کوییز", "slider": "استیکر اسلایدر", "mention": "منشن",
                     "countdown": "استیکر شمارش معکوس", "dm": "دکمهٔ پیام"}
            stk = (f'<div class="sticker">{names.get(sticker, sticker)} را اینجا بگذار'
                   f'{"<br><small>" + rich(s.get("sticker_note"), brand) + "</small>" if s.get("sticker_note") else ""}</div>')
        img = ""
        if s.get("src"):
            img = f'<div class="simg"><img src="{img_data(s.get("src"), ctx["base"])}" alt=""></div>'
        size = "xl" if L == "reel-cover" else ("l" if L == "reel-frame" else "")
        return f"""{kicker}<div class="fit grow center-v">{img}
{f'<h1 class="title {size}">{r("title")}</h1>' if s.get('title') else ''}
{f'<p class="body">{r("body")}</p>' if s.get('body') else ''}</div>{stk}"""

    raise ValueError(f"چیدمان ناشناخته: {L}")


CSS = """
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:%(w)dpx;height:%(h)dpx;overflow:hidden}
body{font-family:'Vazirmatn',Tahoma,sans-serif;background:%(bg)s;color:%(text)s;direction:rtl;
 -webkit-font-smoothing:antialiased}
.frame{position:absolute;top:0;right:0;width:%(w)dpx;height:%(h)dpx;padding:%(pt)dpx %(pr)dpx %(pb)dpx %(px)dpx;display:flex;flex-direction:column;gap:28px}
.frame.v-primary{background:%(primary)s;color:%(on_primary)s}
.frame.v-primary .hl{color:%(accent)s}
.frame.v-primary .kicker{background:rgba(255,255,255,.16);color:%(on_primary)s}
.bar{position:absolute;top:0;right:0;width:100%%;height:14px;background:%(primary)s}
.bar i{display:block;width:28%%;height:100%%;background:%(accent)s}
.grow{flex:1 1 auto;min-height:0;overflow:hidden}
.center-v{display:flex;flex-direction:column;justify-content:center}
.kicker{align-self:flex-start;background:%(primary)s1A;color:%(primary)s;font-weight:700;
 font-size:32px;padding:10px 26px;border-radius:999px}
.title{font-weight:900;font-size:64px;line-height:1.35;letter-spacing:-.5px}
.title.xl{font-size:96px;line-height:1.3}
.title.l{font-size:80px;line-height:1.35}
.sub{font-size:40px;line-height:1.7;margin-top:28px;color:%(muted)s;font-weight:500}
.v-primary .sub{color:%(on_primary)s;opacity:.85}
.body{font-size:48px;line-height:1.85;font-weight:400}
.hl{color:%(primary)s;font-weight:900}
.list{list-style:none;display:flex;flex-direction:column;gap:30px}
.list li{display:flex;gap:26px;align-items:flex-start;font-size:48px;line-height:1.7}
.list .num{flex:0 0 auto;width:78px;height:78px;border-radius:22px;background:%(primary)s;color:%(on_primary)s;
 font-weight:900;font-size:38px;display:flex;align-items:center;justify-content:center;margin-top:4px}
.qwrap{border-right:14px solid %(accent)s;padding-right:44px}
.quote{font-size:60px;line-height:1.6;font-weight:700}
.by{font-size:36px;color:%(muted)s;margin-top:30px}
.cmp{display:flex;flex-direction:column;gap:34px;justify-content:center}
.box{border-radius:%(corner)dpx;padding:38px 42px;background:%(surface)s;border:3px solid transparent}
.box p{font-size:44px;line-height:1.75}
.box .lab{font-weight:900;font-size:36px;margin-bottom:14px}
.box.bad{border-color:#DC262655}.box.bad .lab{color:#DC2626}
.box.good{border-color:%(primary)s}.box.good .lab{color:%(primary)s}
.stat{font-size:220px;font-weight:900;color:%(primary)s;line-height:1.1}
.v-primary .stat{color:%(accent)s}
.src{font-size:28px;color:%(muted)s;margin-top:24px}
.prompt{margin-top:34px;background:%(surface)s;border-radius:%(corner)dpx;padding:44px;border:3px dashed %(primary)s;position:relative}
.prompt p{font-size:42px;line-height:1.75;unicode-bidi:plaintext}
.ptag{position:absolute;top:-28px;right:40px;background:%(primary)s;color:%(on_primary)s;font-weight:700;
 font-size:28px;padding:6px 22px;border-radius:999px}
.note{font-size:34px;line-height:1.7;color:%(muted)s;margin-top:26px}
.imgwrap{display:flex;align-items:center;justify-content:center;border-radius:%(corner)dpx;overflow:hidden;background:%(surface)s}
.imgwrap img{max-width:100%%;max-height:100%%;object-fit:contain}
.capbox{flex:0 0 auto;max-height:220px}
.action{margin-top:40px;align-self:flex-start;background:%(accent)s;color:#1E2430;font-weight:900;font-size:46px;
 padding:24px 44px;border-radius:%(corner)dpx;line-height:1.5}
.foot{flex:0 0 auto;display:flex;justify-content:space-between;align-items:center;font-size:30px;color:%(muted)s;font-weight:500}
.v-primary .foot{color:%(on_primary)s;opacity:.8}
.foot .swipe{color:%(primary)s;font-weight:900}
.v-primary .foot .swipe{color:%(accent)s}
.sticker{flex:0 0 auto;border:4px dashed %(muted)s;border-radius:%(corner)dpx;height:300px;display:flex;
 flex-direction:column;align-items:center;justify-content:center;text-align:center;font-size:34px;color:%(muted)s;
 font-weight:700;line-height:1.6;padding:20px}
.sticker small{font-size:28px;font-weight:400}
.simg{border-radius:%(corner)dpx;overflow:hidden;margin-bottom:40px;max-height:900px;display:flex;justify-content:center}
.simg img{max-width:100%%;max-height:900px;object-fit:contain}
.story .title{font-size:92px;line-height:1.4}
.story .title.l{font-size:104px}
.story .title.xl{font-size:124px}
.story .body{font-size:56px;margin-top:24px}
.story .kicker{font-size:40px;padding:12px 30px}
.v-primary .sticker{border-color:rgba(255,255,255,.6);color:%(on_primary)s}
"""

FIT_JS = """
<script>
(function(){
  var MIN=0.5, over=false;
  document.querySelectorAll('.fit').forEach(function(box){
    var els=box.querySelectorAll('h1,h2,p,li,.stat,.action,.lab');
    var base=[];els.forEach(function(e){base.push(parseFloat(getComputedStyle(e).fontSize));});
    var k=1;
    while(box.scrollHeight>box.clientHeight+2 && k>MIN){
      k-=0.04;els.forEach(function(e,i){e.style.fontSize=(base[i]*k)+'px';});
    }
    if(box.scrollHeight>box.clientHeight+2){over=true;box.style.outline='6px solid red';}
  });
  document.body.setAttribute('data-overflow', over?'1':'0');
  document.body.setAttribute('data-ready','1');
})();
</script>
"""


def page_html(s, idx, total, fmt, brand, ctx):
    w, h = SIZES[fmt]
    story_like = fmt in ("story", "reel")
    pad = {"pt": 250 if story_like else 110, "pb": 340 if story_like else 80, "px": 90, "pr": 90}
    if s.get("layout") == "reel-frame":
        # منطقهٔ امن ریلز: بالای ۲۳۰ و پایین ۱۴۴۰ زیر رابط اینستاگرام است و ستون دکمه‌ها
        # (لایک، کامنت، ...) سمت راست ۲۳۰ پیکسل را می‌پوشاند.
        pad.update(pt=260, pb=500, pr=250)
    if s.get("layout") == "reel-cover":
        pad.update(pt=420, pb=420)  # در شبکهٔ پروفایل فقط میانهٔ کاور دیده می‌شود
    css = CSS % {**brand, **pad, "w": w, "h": h}
    variant = s.get("style", "")
    cls = "frame" + (" v-primary" if variant == "primary" else "") + (" story" if story_like else "")
    foot = ""
    if not story_like:
        left = ""
        if ctx["type"] == "carousel" and total > 1:
            left = (f'<span class="swipe">ورق بزن ←</span>' if idx < total
                    else f'<span>{digits(f"{idx}/{total}", brand)}</span>')
            if idx < total:
                left = f'<span>{digits(f"{idx}/{total}", brand)}</span>&nbsp;&nbsp;' + left
        foot = (f'<div class="foot"><span dir="ltr" class="handle">{html.escape(brand.get("handle", ""))}</span>'
                f'<span>{left}</span></div>')
    elif s.get("handle", True) and fmt == "story":
        foot = ""
    bar = '<div class="bar"><i></i></div>' if not story_like and variant != "primary" else ""
    body = layout_body(s, brand, ctx)
    return f"""<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<style>{font_css()}{css}</style></head><body>{bar}<div class="{cls}">{body}{foot}</div>{FIT_JS}</body></html>"""


# ---------------------------------------------------------------- browsers

def find_browser():
    env = os.environ.get("IGFA_BROWSER")
    if env and os.path.exists(env):
        return ("cli", env)
    try:
        import playwright.sync_api  # noqa: F401
        return ("playwright", None)
    except Exception:
        pass
    for name in ("google-chrome", "chrome", "chromium", "chromium-browser", "msedge", "microsoft-edge"):
        p = shutil.which(name)
        if p:
            return ("cli", p)
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]
    for c in candidates:
        if os.path.exists(c):
            return ("cli", c)
    return (None, None)


class Shooter:
    def __init__(self):
        self.kind, self.exe = find_browser()
        if not self.kind:
            raise RuntimeError(
                "هیچ مرورگری پیدا نشد. یکی از این‌ها کافی است: Google Chrome، Microsoft Edge، "
                "یا `pip install playwright` و بعد `playwright install chromium`. "
                "اگر مرورگر جای دیگری نصب است، مسیرش را در متغیر IGFA_BROWSER بگذار.")
        self.pw = self.browser = None
        self.delta = 0

    def _cli_base(self, td, w, h):
        args = [self.exe, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                "--force-device-scale-factor=1", f"--window-size={w},{h}",
                "--virtual-time-budget=4000", "--no-first-run", "--no-default-browser-check",
                f"--user-data-dir={os.path.join(td, 'profile')}"]
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            args.append("--no-sandbox")  # کروم روی لینوکس با کاربر root بدون این اجرا نمی‌شود
        return args

    def _probe(self):
        """در حالت بی‌سرِ جدید، ارتفاع صفحهٔ واقعی چند ده پیکسل کمتر از اندازهٔ پنجره است.
        یک بار اندازه می‌گیریم تا عکس دقیقاً هم‌اندازهٔ طرح دربیاید."""
        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, "probe.html")
            with open(src, "w", encoding="utf-8") as f:
                f.write('<html><body><script>document.body.setAttribute("data-ih",innerHeight)</script></body></html>')
            url = "file:///" + src.replace("\\", "/").lstrip("/")
            out = subprocess.run(self._cli_base(td, 1080, 1920) + ["--dump-dom", url],
                                 capture_output=True, timeout=120).stdout.decode("utf-8", "ignore")
        m = re.search(r'data-ih="(\d+)"', out)
        self.delta = max(0, 1920 - int(m.group(1))) if m else 0

    def __enter__(self):
        if self.kind == "playwright":
            from playwright.sync_api import sync_playwright
            self.pw = sync_playwright().start()
            self.browser = self.pw.chromium.launch()
        else:
            self._probe()
        return self

    def __exit__(self, *a):
        if self.browser:
            self.browser.close()
        if self.pw:
            self.pw.stop()

    def shoot(self, html_text, out_png, size):
        w, h = size
        if self.kind == "playwright":
            page = self.browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
            page.set_content(html_text, wait_until="load")
            page.evaluate("document.fonts.ready")
            page.wait_for_function("document.body.getAttribute('data-ready')==='1'")
            over = page.evaluate("document.body.getAttribute('data-overflow')") == "1"
            page.screenshot(path=out_png, full_page=False)
            page.close()
            return over
        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, "slide.html")
            with open(src, "w", encoding="utf-8") as f:
                f.write(html_text)
            url = "file:///" + src.replace("\\", "/").lstrip("/")
            common = self._cli_base(td, w, h + self.delta)
            shot = subprocess.run(common + [f"--screenshot={os.path.abspath(out_png)}", url],
                                  capture_output=True, timeout=120)
            dom = subprocess.run(common + ["--dump-dom", url], capture_output=True, timeout=120)
            over = 'data-overflow="1"' in dom.stdout.decode("utf-8", "ignore")
            ok = os.path.exists(out_png)
            if ok and self.delta:
                try:
                    from PIL import Image
                except ImportError:
                    raise RuntimeError("برای برش دقیق عکس، Pillow لازم است: pip install pillow")
                with Image.open(out_png) as im:
                    im.crop((0, 0, w, h)).save(out_png)
        if not ok:
            raise RuntimeError(f"مرورگر عکس نساخت ({self.exe}).\n"
                               + shot.stderr.decode("utf-8", "ignore")[-800:])
        return over


# ---------------------------------------------------------------- preview

def write_preview(out_dir, files, spec, overflow):
    cap = ""
    for name in ("caption.txt", "caption.md"):
        p = os.path.join(out_dir, name)
        if not os.path.exists(p):
            p = os.path.join(os.path.dirname(out_dir), name)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                cap = f.read()
            break
    imgs = "".join(
        f'<figure><img src="{os.path.basename(f)}"><figcaption>{i}'
        f'{" — ⚠️ سرریز متن" if os.path.basename(f) in overflow else ""}</figcaption></figure>'
        for i, f in enumerate(files, 1))
    page = f"""<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<title>پیش‌نمایش: {html.escape(spec.get('title', ''))}</title>
<style>body{{font-family:Vazirmatn,Tahoma,sans-serif;background:#f3f4f6;margin:0;padding:24px;color:#111}}
h1{{font-size:22px}} .grid{{display:flex;flex-wrap:wrap;gap:16px}}
figure{{margin:0;background:#fff;padding:8px;border-radius:12px;box-shadow:0 1px 3px #0002}}
img{{width:270px;display:block;border-radius:6px}} figcaption{{text-align:center;font-size:13px;padding-top:6px}}
pre{{white-space:pre-wrap;background:#fff;padding:16px;border-radius:12px;font-family:inherit;font-size:15px;line-height:1.9;max-width:720px}}
</style></head><body><h1>{html.escape(spec.get('title', 'پیش‌نمایش'))} · {html.escape(spec.get('type', ''))} · {len(files)} تصویر</h1>
<div class="grid">{imgs}</div>{'<h2>کپشن</h2><pre>' + html.escape(cap) + '</pre>' if cap else ''}</body></html>"""
    p = os.path.join(out_dir, "preview.html")
    with open(p, "w", encoding="utf-8") as f:
        f.write(page)
    return p


# ---------------------------------------------------------------- main

def render(spec_path, page_dir, out_dir, only=None):
    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)
    brand = load_brand(page_dir, spec.get("brand"))
    typ = spec.get("type", "carousel")
    fmt = spec.get("format") or TYPE_FORMAT.get(typ, "post")
    slides = spec["slides"]
    if typ == "single" and len(slides) > 1:
        print("هشدار: نوع single بیش از یک اسلاید دارد؛ همه ساخته می‌شوند.", file=sys.stderr)
    if typ == "carousel" and len(slides) > 20:
        raise ValueError("کاروسل حداکثر ۲۰ اسلاید دارد.")
    os.makedirs(out_dir, exist_ok=True)
    ctx = {"type": typ, "base": os.path.dirname(os.path.abspath(spec_path))}
    files, overflow = [], []
    with Shooter() as sh:
        for i, s in enumerate(slides, 1):
            if only and i != only:
                continue
            sfmt = s.get("format", fmt)
            out = os.path.join(out_dir, f"{i:02d}.png")
            over = sh.shoot(page_html(s, i, len(slides), sfmt, brand, ctx), out, SIZES[sfmt])
            files.append(out)
            marker = out + ".overflow"  # publish.py اسلاید سرریزدار را تأیید نمی‌کند
            if over:
                overflow.append(os.path.basename(out))
                open(marker, "w").close()
            elif os.path.exists(marker):
                os.remove(marker)
            print(f"  {'⚠️ ' if over else '✓ '}{out}  ({s.get('layout', 'text')}, {sfmt})")
    for old in glob.glob(os.path.join(out_dir, "*.png")):
        if not only and old not in files:
            os.remove(old)
            if os.path.exists(old + ".overflow"):
                os.remove(old + ".overflow")
    if not only:
        prev = write_preview(out_dir, files, spec, overflow)
        print(f"\nپیش‌نمایش: {prev}")
    if overflow:
        print(f"\nسرریز متن در: {'، '.join(overflow)}. متن این اسلایدها را کوتاه کن و دوباره بساز.")
    return files, overflow


def main():
    setup_stdout()
    ap = argparse.ArgumentParser(description="ساخت تصویرهای اینستاگرام از spec.json")
    ap.add_argument("spec", nargs="?")
    ap.add_argument("--page", help="پوشهٔ پیج (برای brand.json)")
    ap.add_argument("--out", help="پوشهٔ خروجی تصویرها")
    ap.add_argument("--only", type=int, help="فقط همین شمارهٔ اسلاید")
    ap.add_argument("--check", action="store_true", help="فقط بررسی کن مرورگر پیدا می‌شود")
    a = ap.parse_args()
    if a.check:
        kind, exe = find_browser()
        print(f"مرورگر: {kind or 'پیدا نشد'} {exe or ''}")
        print(f"فونت: {'پیدا شد' if glob.glob(os.path.join(HERE, 'fonts', '*.ttf')) else 'پیدا نشد'}")
        sys.exit(0 if kind else 1)
    if not a.spec:
        ap.error("فایل spec.json را بده")
    out = a.out or os.path.join(os.path.dirname(os.path.abspath(a.spec)), "slides")
    _, overflow = render(a.spec, a.page, out, a.only)
    sys.exit(3 if overflow else 0)


if __name__ == "__main__":
    main()
