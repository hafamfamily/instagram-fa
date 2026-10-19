"""
design.py - سیستم طراحی HTML/CSS برای پست، استوری و ریلز؛ با چهار سبک بصری، آیکون، فونت‌های
نمایشی فارسی، و موشن قابل‌جست‌وجو در زمان (برای ساخت ویدیو فریم‌به‌فریم).

ایده‌ها از:
  - anthropics/skills → canvas-design (هر پیج یک «فلسفهٔ بصری» دارد) و theme-factory (پالت‌ها)
  - remotion-dev/skills → موشن قطعی و قابل‌جست‌وجو در زمان: هر حرکت تابعی از t است، نه تایمر

سبک‌ها (brand.json → "theme"):
  paper   کاغذ و جوهر: زمینهٔ روشن با بافت، لکه‌های رنگی نرم، هایلایت ماژیکی، خط موجی که در
          کاروسل از اسلایدی به اسلاید بعد ادامه دارد
  pop     بازارچه: رنگ‌های اشباع، فونت لاله‌زار، قاب‌های ضخیم و سایهٔ تخت، برچسب‌های کج
  night   شب: زمینهٔ تیره با نور رنگی، کارت‌های شیشه‌ای، متن گرادیانی
  naskh   مجله: تیتر نسخ، فضای سفید زیاد، خط‌های نازک، شماره‌های درشت توخالی

حالت‌ها: still (تصویر ثابت؛ همه چیز در حالت نهایی)، motion (ویدیو؛ ورود عناصر با زمان‌بندی)،
overlay (لایهٔ شفاف متن روی کلیپ یا عکس).
"""

import base64
import hashlib
import html as H
import json
import math
import os
import random
import re

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, "fonts")
ICONS = os.path.join(HERE, "assets", "icons", "lucide-nodes.json")
FA_DIG = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

THEMES = {
    "paper": {"bg": "#F3F1EA", "surface": "#FFFFFF", "ink": "#1B2233", "muted": "#5F6676",
              "primary": "#1F6F5C", "accent": "#F2B134", "display": "Vazirmatn", "dw": 900,
              "radius": 34, "label": "کاغذ و جوهر"},
    "pop": {"bg": "#FFF6E5", "surface": "#FFFFFF", "ink": "#16130F", "muted": "#4A443B",
            "primary": "#E8462A", "accent": "#FFC93C", "display": "Lalezar", "dw": 400,
            "radius": 22, "label": "بازارچه"},
    "night": {"bg": "#0D1222", "surface": "#161D33", "ink": "#F4F6FB", "muted": "#A3ACC2",
              "primary": "#7C5CFF", "accent": "#2EE6C5", "display": "Vazirmatn", "dw": 900,
              "radius": 30, "label": "شب"},
    "naskh": {"bg": "#FAF8F4", "surface": "#FFFFFF", "ink": "#22201C", "muted": "#6E685E",
              "primary": "#8A2C2C", "accent": "#C9A227", "display": "Noto Naskh Arabic", "dw": 700,
              "radius": 6, "label": "مجله"},
}
SIZES = {"post": (1080, 1350), "square": (1080, 1080), "story": (1080, 1920), "reel": (1080, 1920)}


# ---------------------------------------------------------------- helpers

def tokens(brand):
    """سبک + رنگ‌های برند. رنگ‌های brand.json بر پیش‌فرض سبک غالب‌اند."""
    name = brand.get("theme", "paper")
    if name in ("light", "", None):
        name = "paper"
    if name == "dark":
        name = "night"
    t = dict(THEMES.get(name, THEMES["paper"]))
    t["name"] = name if name in THEMES else "paper"
    keymap = {"bg": "bg", "surface": "surface", "text": "ink", "muted": "muted", "primary": "primary",
              "accent": "accent"}
    defaults_old = {"bg": "#FBF7F1", "surface": "#FFFFFF", "text": "#1E2430", "muted": "#6B7280"}
    for k, tk in keymap.items():
        v = brand.get(k)
        if v and defaults_old.get(k) != v:  # مقدارهای پیش‌فرض قالب قدیمی، سبک را بازنویسی نکنند
            t[tk] = v
    t["on_primary"] = brand.get("on_primary") or ("#FFFFFF" if lum(t["primary"]) < 0.55 else "#111111")
    t["on_accent"] = "#111111" if lum(t["accent"]) > 0.45 else "#FFFFFF"
    t["handle"] = brand.get("handle", "")
    t["digits"] = brand.get("digits", "fa") == "fa"
    if brand.get("display_font"):  # اسم یکی از فونت‌های داخلی یا اسم فایل (بدون پسوند) در پوشهٔ fonts کاربر
        t["display"] = brand["display_font"]
        t["dw"] = brand.get("display_weight", 400 if brand["display_font"] not in ("Vazirmatn",) else 900)
    t["body_font"] = brand.get("body_font", "Vazirmatn")
    return t


def lum(hexc):
    h = hexc.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def rgba(hexc, a):
    h = hexc.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{a})"


def fa(text, on=True):
    if not on:
        return text
    return re.sub(r"(?<![A-Za-z\-_.#])\d+(?:[.,]\d+)*(?![A-Za-z])", lambda m: m.group().translate(FA_DIG), text)


def rich(text, T, words=False, keep_digits=False):
    """متن ساده → HTML. **x** هایلایت؛ \\n خط جدید. words=True: هر کلمه یک span برای موشن."""
    if text is None:
        return ""
    t = H.escape(str(text))
    if not keep_digits:
        t = fa(t, T["digits"])
    out, i = [], 0
    parts = re.split(r"(\*\*.+?\*\*)", t)
    for part in parts:
        if not part:
            continue
        hl = part.startswith("**") and part.endswith("**")
        body = part[2:-2] if hl else part
        if words:
            lines = body.split("\n")
            segs = []
            for li, line in enumerate(lines):
                if li:
                    segs.append("<br>")
                for w in line.split(" "):
                    if not w:
                        continue
                    segs.append(f'<span class="w" style="--i:{i}">{w}</span>')
                    i += 1
            lead = " " if body[:1] == " " else ""
            trail = " " if body[-1:] == " " else ""
            body = lead + " ".join(segs).replace(" <br> ", "<br>") + trail
        else:
            body = body.replace("\n", "<br>")
        out.append(f'<mark style="--i:{i}">{body}</mark>' if hl else body)
    return "".join(out)


_ICONS = None


def icon(name, size=64, stroke=2, cls="ic"):
    global _ICONS
    if not name:
        return ""
    if _ICONS is None:
        try:
            with open(ICONS, encoding="utf-8") as f:
                _ICONS = json.load(f)
        except Exception:
            _ICONS = {}
    nodes = _ICONS.get(name)
    if not nodes:
        return ""
    inner = "".join(f"<{tag} " + " ".join(f'{k}="{H.escape(str(v))}"' for k, v in attrs.items()) + "/>"
                    for tag, attrs in nodes)
    return (f'<svg class="{cls}" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">{inner}</svg>')


def file_url(path):
    return "file://" + os.path.abspath(path).replace("\\", "/")


def img_url(path, base):
    p = path if os.path.isabs(path) else os.path.join(base, path)
    if not os.path.exists(p):
        raise FileNotFoundError(f"تصویر پیدا نشد: {p}")
    return file_url(p)


USER_FONT_DIRS = []  # render.py پوشهٔ fonts خانهٔ پیج‌ها و پوشهٔ پیج را اینجا می‌گذارد


def user_fonts():
    """فونت‌های کاربر: هر فایل در پوشه‌های fonts کاربر یک خانواده به نام خود فایل (بدون پسوند) می‌سازد."""
    out = {}
    for d in USER_FONT_DIRS:
        if d and os.path.isdir(d):
            for fn in sorted(os.listdir(d)):
                stem, ext = os.path.splitext(fn)
                if ext.lower() in (".ttf", ".otf", ".woff", ".woff2"):
                    out.setdefault(stem, os.path.join(d, fn))
    return out


def font_faces():
    f = []
    fmt = {".ttf": "truetype", ".otf": "opentype", ".woff": "woff", ".woff2": "woff2"}
    for fam, path in user_fonts().items():
        f.append(f"@font-face{{font-family:'{fam}';src:url('{file_url(path)}') format('{fmt[os.path.splitext(path)[1].lower()]}')}}")
    for name, w in (("Regular", 400), ("Medium", 500), ("Bold", 700), ("Black", 900)):
        f.append(f"@font-face{{font-family:'Vazirmatn';font-weight:{w};src:url('{file_url(os.path.join(FONTS, f'Vazirmatn-{name}.ttf'))}')}}")
    extra = [("Lalezar", 400, "lalezar-arabic-400-normal.woff2"), ("Lalezar", 400, "lalezar-latin-400-normal.woff2"),
             ("Noto Naskh Arabic", 400, "noto-naskh-arabic-arabic-400-normal.woff2"),
             ("Noto Naskh Arabic", 700, "noto-naskh-arabic-arabic-700-normal.woff2"),
             ("Reem Kufi", 700, "reem-kufi-arabic-700-normal.woff2")]
    for fam, w, fn in extra:
        p = os.path.join(FONTS, fn)
        if os.path.exists(p):
            f.append(f"@font-face{{font-family:'{fam}';font-weight:{w};src:url('{file_url(p)}') format('woff2')}}")
    return "\n".join(f)


def seeded(key):
    return random.Random(int(hashlib.md5(key.encode()).hexdigest()[:8], 16))


def blob_path(rng, cx, cy, r, points=7, wobble=0.28):
    pts = []
    for k in range(points):
        a = 2 * math.pi * k / points
        rr = r * (1 + rng.uniform(-wobble, wobble))
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    d = f"M{(pts[0][0] + pts[-1][0]) / 2:.1f},{(pts[0][1] + pts[-1][1]) / 2:.1f}"
    for k in range(points):
        p, q = pts[k], pts[(k + 1) % points]
        d += f" Q{p[0]:.1f},{p[1]:.1f} {(p[0] + q[0]) / 2:.1f},{(p[1] + q[1]) / 2:.1f}"
    return d + "Z"


GRAIN = ("data:image/svg+xml;utf8," + re.sub(r"\s+", " ", """
<svg xmlns='http://www.w3.org/2000/svg' width='300' height='300'><filter id='n'><feTurbulence type='fractalNoise'
baseFrequency='.9' numOctaves='3' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 .55 0'/>
</filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>""").strip())


# ---------------------------------------------------------------- decor per theme

def decor(T, s, idx, total, fmt, W, Hh, key):
    rng = seeded(f"{key}-{idx}")
    th = T["name"]
    out = []
    if s.get("bg") or s.get("layout") == "photo":
        return ""
    if th == "paper":
        for k in range(2):
            r = rng.uniform(170, 320)
            cx = rng.choice([rng.uniform(-60, 220), rng.uniform(W - 220, W + 60)])
            cy = rng.uniform(80, Hh - 80)
            col = T["primary"] if k == 0 else T["accent"]
            out.append(f'<path class="drift" style="--dx:{rng.uniform(-30,30):.0f}px;--dy:{rng.uniform(-30,30):.0f}px" '
                       f'd="{blob_path(rng, cx, cy, r)}" fill="{rgba(col, 0.10 if k == 0 else 0.16)}"/>')
        if fmt in ("post", "square") and total > 1:
            # خط موجی پیوسته در کل کاروسل: لبهٔ چپ اسلاید i به لبهٔ راست اسلاید i+1 وصل است
            pts = []
            y0 = Hh * 0.86
            for gx in range(-total * W, W + 1, 20):
                gy = y0 + 34 * math.sin(gx / 260) + 18 * math.sin(gx / 97)
                pts.append(f"{gx},{gy:.1f}")
            out.append(f'<g transform="translate({(idx - 1) * W},0)"><polyline class="draw" points="{" ".join(pts)}" '
                       f'fill="none" stroke="{rgba(T["accent"], 0.9)}" stroke-width="6" stroke-linecap="round"/></g>')
    elif th == "pop":
        for k in range(26):
            x, y = rng.uniform(0, W), rng.uniform(0, Hh)
            out.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{rng.uniform(4, 9):.1f}" fill="{rgba(T["ink"], 0.12)}"/>')
        if s.get("layout", "text") not in ("cover", "cta", "text", "quote", "stat", "story", "reel-cover", "reel-frame"):
            return (f'<svg class="decor" width="{W}" height="{Hh}" viewBox="0 0 {W} {Hh}">' + "".join(out) + "</svg>")
        cx, cy = rng.choice([(W - 130, 150), (150, Hh - 300)]) if fmt in ("post", "square") else (W - 150, 200)
        star = []
        n = 14
        for k in range(2 * n):
            rr = 120 if k % 2 == 0 else 86
            a = math.pi * k / n
            star.append(f"{cx + rr * math.cos(a):.1f},{cy + rr * math.sin(a):.1f}")
        out.append(f'<polygon class="spin" style="transform-origin:{cx:.0f}px {cy:.0f}px" points="{" ".join(star)}" '
                   f'fill="{T["accent"]}" stroke="{T["ink"]}" stroke-width="5"/>')
    elif th == "night":
        for k, col in enumerate((T["primary"], T["accent"])):
            cx = rng.uniform(0, W)
            cy = rng.uniform(0, Hh)
            r = rng.uniform(380, 560)
            out.append(f'<circle class="drift" style="--dx:{rng.uniform(-50,50):.0f}px;--dy:{rng.uniform(-50,50):.0f}px" '
                       f'cx="{cx:.0f}" cy="{cy:.0f}" r="{r:.0f}" fill="{col}" opacity="{0.38 if k == 0 else 0.22}" '
                       f'filter="url(#blur)"/>')
        grid = "".join(f'<line x1="{x}" y1="0" x2="{x}" y2="{Hh}" />' for x in range(0, W + 1, 90))
        grid += "".join(f'<line x1="0" y1="{y}" x2="{W}" y2="{y}" />' for y in range(0, Hh + 1, 90))
        out.append(f'<g stroke="{rgba("#FFFFFF", 0.045)}" stroke-width="1">{grid}</g>')
    elif th == "naskh":
        out.append(f'<line x1="90" y1="80" x2="{W - 90}" y2="80" stroke="{T["ink"]}" stroke-width="2"/>')
        out.append(f'<line x1="90" y1="92" x2="{W - 90}" y2="92" stroke="{T["ink"]}" stroke-width="1"/>')
    return (f'<svg class="decor" width="{W}" height="{Hh}" viewBox="0 0 {W} {Hh}"><defs><filter id="blur" '
            f'x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="110"/></filter></defs>'
            + "".join(out) + "</svg>")


# ---------------------------------------------------------------- CSS

def css(T, W, Hh, fmt, mode):
    th = T["name"]
    disp = f"'{T['display']}','Vazirmatn',sans-serif"
    big = fmt in ("story", "reel")
    base = f"""
*{{box-sizing:border-box;margin:0;padding:0}}
html,body{{width:{W}px;height:{Hh}px;overflow:hidden}}
body{{font-family:'{T['body_font']}','Vazirmatn',sans-serif;background:{T['bg']};color:{T['ink']};direction:rtl;
 -webkit-font-smoothing:antialiased;text-rendering:geometricPrecision}}
.overlay-mode body,body.overlay{{background:transparent}}
.decor{{position:absolute;inset:0;z-index:0;pointer-events:none}}
.frame{{position:absolute;inset:0;z-index:2;display:flex;flex-direction:column;gap:30px;padding:var(--pt) var(--pr) var(--pb) var(--pl)}}
.grow{{flex:1 1 auto;min-height:0;display:flex;flex-direction:column}}
.center{{justify-content:center}}
.fit{{overflow:hidden}}
h1,h2{{font-family:{disp};font-weight:{T['dw']};line-height:1.32;letter-spacing:0}}
h1{{font-size:{124 if big else 98}px}}
h2{{font-size:{86 if big else 66}px}}
.kicker{{align-self:flex-start;display:inline-flex;align-items:center;gap:14px;font-weight:700;font-size:{40 if big else 32}px;
 color:{T['primary']};padding:12px 28px;border-radius:999px;background:{rgba(T['primary'], .10)}}}
.kicker .ic{{width:1.15em;height:1.15em}}
.sub{{font-size:{54 if big else 42}px;line-height:1.7;color:{T['muted']};font-weight:500;margin-top:26px}}
.body{{font-size:{58 if big else 48}px;line-height:1.85}}
.list{{list-style:none;display:flex;flex-direction:column;gap:30px}}
.list li{{display:flex;gap:28px;align-items:flex-start;font-size:{56 if big else 47}px;line-height:1.62}}
.list .num{{flex:0 0 auto;width:84px;height:84px;border-radius:26px;display:grid;place-items:center;
 font-weight:900;font-size:40px;background:{T['primary']};color:{T['on_primary']};margin-top:2px}}
.list .num .ic{{width:46px;height:46px}}
.list .it{{padding-top:6px}}
.grid4{{display:grid;grid-template-columns:1fr 1fr;gap:26px}}
.tile{{background:{T['surface']};border-radius:{T['radius']}px;padding:36px 34px;display:flex;flex-direction:column;gap:18px}}
.tile .ic{{width:72px;height:72px;color:{T['primary']}}}
.tile b{{font-size:40px;font-weight:900;line-height:1.4}}
.tile span{{font-size:32px;line-height:1.6;color:{T['muted']}}}
.quote{{font-family:{disp};font-size:{80 if big else 64}px;font-weight:{T['dw']};line-height:1.55}}
.qbar{{border-right:14px solid {T['accent']};padding-right:48px}}
.by{{font-size:36px;color:{T['muted']};margin-top:30px}}
.cmp{{display:flex;flex-direction:column;gap:34px}}
.box{{border-radius:{T['radius']}px;padding:40px 44px;background:{T['surface']}}}
.box .lab{{display:flex;align-items:center;gap:14px;font-weight:900;font-size:38px;margin-bottom:14px}}
.box .lab .ic{{width:44px;height:44px}}
.box p{{font-size:46px;line-height:1.7}}
.box.bad .lab{{color:#D23B2E}} .box.good .lab{{color:{T['primary']}}}
.stat{{font-family:{disp};font-size:250px;font-weight:{T['dw']};line-height:1.08;color:{T['primary']}}}
.src{{font-size:28px;color:{T['muted']};margin-top:22px}}
.prompt{{position:relative;margin-top:36px;background:{T['surface']};border-radius:{T['radius']}px;padding:56px 48px 46px;
 border:3px dashed {rgba(T['primary'], .55)}}}
.prompt p{{font-size:43px;line-height:1.75;unicode-bidi:plaintext}}
.ptag{{position:absolute;top:-30px;right:40px;display:flex;gap:10px;align-items:center;background:{T['primary']};
 color:{T['on_primary']};font-weight:700;font-size:30px;padding:8px 24px;border-radius:999px}}
.ptag .ic{{width:34px;height:34px}}
.note{{font-size:34px;line-height:1.7;color:{T['muted']};margin-top:28px}}
.imgwrap{{flex:1;min-height:0;display:flex;align-items:center;justify-content:center;border-radius:{T['radius']}px;overflow:hidden}}
.imgwrap img{{max-width:100%;max-height:100%;object-fit:contain;border-radius:{T['radius']}px}}
.action{{margin-top:44px;align-self:flex-start;display:inline-flex;gap:16px;align-items:center;background:{T['accent']};
 color:{T['on_accent']};font-weight:900;font-size:{56 if big else 46}px;padding:26px 46px;border-radius:{T['radius']}px;line-height:1.45}}
.action .ic{{width:1.1em;height:1.1em}}
.foot{{position:absolute;z-index:3;left:90px;right:90px;bottom:54px;display:flex;justify-content:space-between;align-items:center;
 font-size:30px;color:{T['muted']};font-weight:500}}
.foot .handle{{direction:ltr}}
.foot .swipe{{display:flex;align-items:center;gap:12px;font-weight:900;color:{T['primary']}}}
.foot .swipe .ic{{width:38px;height:38px}}
body[style*="background"] .foot,.v-primary ~ .foot{{color:currentColor}}
body[style*="background"] .foot .swipe{{color:inherit}}
body[style*="background"] .sub{{color:inherit;opacity:.85}}
body[style*="background"] .bigic{{color:{T['accent']}}}
body[style*="background"] .kicker{{background:rgba(255,255,255,.16);color:inherit}}
.sticker{{flex:0 0 auto;border:5px dashed {rgba(T['ink'], .35)};border-radius:{T['radius']}px;height:290px;display:flex;
 flex-direction:column;align-items:center;justify-content:center;gap:10px;text-align:center;font-size:36px;color:{T['muted']};font-weight:700}}
.sticker small{{font-size:29px;font-weight:400}}
.simg{{border-radius:{T['radius']}px;overflow:hidden;margin-bottom:44px;max-height:880px;display:flex;justify-content:center}}
.simg img{{max-width:100%;max-height:880px;object-fit:cover;border-radius:{T['radius']}px}}
.bigic{{color:{T['primary']};margin-bottom:28px}}
.bigic .ic{{width:150px;height:150px}}
mark{{color:inherit;background:none}}
/* photo */
.photo-bg{{position:absolute;inset:0;z-index:0;background-size:cover;background-position:var(--fx,50%) var(--fy,50%)}}
.photo-shade{{position:absolute;inset:0;z-index:1}}
.on-photo{{color:#fff}} .on-photo .sub{{color:rgba(255,255,255,.86)}} .on-photo .kicker{{background:rgba(255,255,255,.18);color:#fff;
 backdrop-filter:blur(8px)}} .on-photo h1,.on-photo h2{{text-shadow:0 4px 30px rgba(0,0,0,.35)}}
/* chat */
.chat{{background:{T['surface']};border-radius:{T['radius'] + 10}px;padding:26px 30px 34px;display:flex;flex-direction:column;gap:22px;
 box-shadow:0 30px 60px {rgba(T['ink'], .10)}}}
.chat .hd{{display:flex;align-items:center;gap:18px;padding-bottom:20px;border-bottom:2px solid {rgba(T['ink'], .08)};font-weight:700;font-size:34px}}
.chat .av{{width:66px;height:66px;border-radius:50%;background:{rgba(T['primary'], .15)};display:grid;place-items:center;color:{T['primary']}}}
.chat .av .ic{{width:36px;height:36px}}
.bub{{max-width:78%;padding:22px 30px;border-radius:36px;font-size:38px;line-height:1.55}}
.bub.them{{align-self:flex-start;background:{rgba(T['ink'], .07)};border-top-right-radius:10px}}
.bub.me{{align-self:flex-end;background:{T['primary']};color:{T['on_primary']};border-top-left-radius:10px}}
/* phone */
.phone{{align-self:center;height:100%;aspect-ratio:9/19.5;max-height:100%;border-radius:76px;background:#14161C;padding:20px;
 box-shadow:0 40px 80px {rgba(T['ink'], .25)};position:relative}}
.phone img{{width:100%;height:100%;object-fit:cover;object-position:top;border-radius:58px;display:block}}
.phone:after{{content:'';position:absolute;top:36px;left:50%;transform:translateX(-50%);width:130px;height:34px;border-radius:20px;background:#14161C}}
/* chart */
.chart{{display:flex;flex-direction:column;gap:34px}}
.bar{{display:grid;grid-template-columns:270px 1fr;align-items:center;gap:28px}}
.bar .lb{{font-size:38px;font-weight:700;line-height:1.35}}
.bar .tr{{height:96px;position:relative}}
.bar .fill{{height:100%;width:var(--w);border-radius:{min(T['radius'], 30)}px;background:{T['primary']};display:flex;align-items:center;
 justify-content:flex-end;padding:0 26px;transform-origin:right;color:{T['on_primary']};font-weight:900;font-size:38px;white-space:nowrap}}
.bar.hl .fill{{background:{T['accent']};color:{T['on_accent']}}}
.bar .fill.small{{justify-content:flex-start}}
.bar .fill.small span{{transform:translateX(-110%);color:{T['ink']}}}
"""
    themecss = {
        "paper": f"""
body:before{{content:'';position:absolute;inset:0;z-index:1;opacity:.22;mix-blend-mode:multiply;background-image:url("{GRAIN}")}}
mark{{background:linear-gradient(transparent 58%,{rgba(T['accent'], .85)} 58% 92%,transparent 92%);
 background-size:var(--sw,100%) 100%;background-repeat:no-repeat;background-position:right;padding:0 .08em}}
.tile,.box,.prompt,.chat{{box-shadow:0 18px 40px {rgba(T['ink'], .07)}}}
.v-primary{{background:{T['primary']};color:{T['on_primary']}}}
.v-primary .kicker{{background:rgba(255,255,255,.16);color:{T['on_primary']}}}
.v-primary .sub,.v-primary .foot{{color:{rgba('#FFFFFF', .82)}}}
.v-primary mark{{background:linear-gradient(transparent 58%,{rgba(T['accent'], .9)} 58% 92%,transparent 92%);
 background-size:var(--sw,100%) 100%;background-repeat:no-repeat;background-position:right;color:{T['on_primary']}}}
.v-primary .foot .swipe{{color:{T['accent']}}}
""",
        "pop": f"""
h1,h2{{line-height:1.25;letter-spacing:.5px}}
h1{{font-size:{150 if big else 118}px}} h2{{font-size:{100 if big else 78}px}}
.kicker{{background:{T['accent']};color:{T['ink']};border:4px solid {T['ink']};border-radius:14px;transform:rotate(-2.5deg);
 box-shadow:6px 6px 0 {T['ink']}}}
mark{{background:{T['accent']};color:{T['ink']};padding:0 .18em;border-radius:10px;box-decoration-break:clone;
 -webkit-box-decoration-break:clone;display:inline;box-shadow:5px 5px 0 {T['ink']}}}
.tile,.box,.prompt,.chat{{border:5px solid {T['ink']};box-shadow:12px 12px 0 {T['ink']}}}
.prompt{{border-style:solid}}
.list .num{{border:4px solid {T['ink']};box-shadow:5px 5px 0 {T['ink']}}}
.action{{border:5px solid {T['ink']};box-shadow:10px 10px 0 {T['ink']}}}
.bar .fill{{border:4px solid {T['ink']};box-shadow:7px 7px 0 {T['ink']}}}
.v-primary{{background:{T['primary']};color:#fff}}
.v-primary .sub,.v-primary .foot{{color:rgba(255,255,255,.9)}}
.v-accent{{background:{T['accent']};color:{T['ink']}}}
.v-accent mark{{background:{T['primary']};color:#fff}}
.stat{{-webkit-text-stroke:5px {T['ink']};color:{T['accent']};text-shadow:12px 12px 0 {T['ink']}}}
""",
        "night": f"""
h1,h2{{letter-spacing:-.5px}}
mark{{background:linear-gradient(100deg,{T['accent']},{T['primary']});-webkit-background-clip:text;background-clip:text;color:transparent}}
.kicker{{background:{rgba('#FFFFFF', .08)};color:{T['accent']};border:1.5px solid {rgba('#FFFFFF', .16)};backdrop-filter:blur(10px)}}
.tile,.box,.prompt,.chat{{background:{rgba('#FFFFFF', .06)};border:1.5px solid {rgba('#FFFFFF', .14)};backdrop-filter:blur(18px)}}
.prompt{{border-style:solid}}
.bub.them{{background:{rgba('#FFFFFF', .10)}}}
.stat{{background:linear-gradient(100deg,{T['accent']},{T['primary']});-webkit-background-clip:text;background-clip:text;color:transparent}}
.list .num{{background:linear-gradient(135deg,{T['primary']},{T['accent']});color:#fff}}
.action{{background:linear-gradient(100deg,{T['accent']},{T['primary']});color:#0B0F1C}}
.v-primary{{background:radial-gradient(circle at 80% 10%,{T['primary']},{T['bg']} 70%)}}
""",
        "naskh": f"""
h1,h2{{line-height:1.55}}
h1{{font-size:{112 if big else 92}px}}
.kicker{{background:none;padding:0;border-radius:0;color:{T['primary']};font-family:'Noto Naskh Arabic';font-weight:700;
 font-size:{44 if big else 36}px;border-bottom:3px solid {T['accent']};padding-bottom:6px}}
mark{{color:{T['primary']};background:linear-gradient({T['accent']},{T['accent']}) no-repeat right bottom;
 background-size:var(--sw,100%) 6px;padding-bottom:4px}}
.body,.list li,.box p,.sub{{font-family:'Noto Naskh Arabic','Vazirmatn';}}
.body{{line-height:2}}
.list .num{{background:none;color:transparent;-webkit-text-stroke:2.5px {T['primary']};font-family:'Noto Naskh Arabic';
 font-size:76px;width:90px;border-radius:0}}
.list .num .ic{{color:{T['primary']};-webkit-text-stroke:0}}
.tile,.box,.prompt,.chat{{border:1.5px solid {rgba(T['ink'], .18)};box-shadow:none}}
.stat{{color:{T['primary']}}}
.qbar{{border-right:4px solid {T['accent']}}}
.v-primary{{background:{T['ink']};color:{T['bg']}}}
.v-primary mark{{color:{T['accent']}}}
""",
    }[th]
    motion = """
/* موشن: همهٔ حرکت‌ها با animation و fill-mode both تعریف شده‌اند و __seek(t) زمانشان را تنظیم می‌کند */
@keyframes rise{from{opacity:0;transform:translateY(46px)}to{opacity:1;transform:none}}
@keyframes pop{0%{opacity:0;transform:scale(.6)}70%{opacity:1;transform:scale(1.06)}100%{transform:scale(1)}}
@keyframes fadein{from{opacity:0}to{opacity:1}}
@keyframes sweep{from{--sw:0%;background-size:0% 100%}to{background-size:100% 100%}}
@keyframes sweepline{from{background-size:0% 6px}to{background-size:100% 6px}}
@keyframes growx{from{transform:scaleX(0)}to{transform:scaleX(1)}}
@keyframes drift{0%{transform:translate(0,0)}50%{transform:translate(var(--dx),var(--dy))}100%{transform:translate(0,0)}}
@keyframes spin{from{transform:rotate(0)}to{transform:rotate(360deg)}}
@keyframes draw{from{stroke-dashoffset:8000}to{stroke-dashoffset:0}}
@keyframes slidein{from{opacity:0;transform:translateX(-60px)}to{opacity:1;transform:none}}
.m .w{display:inline-block;animation:rise .55s cubic-bezier(.2,.8,.2,1) both;animation-delay:calc(var(--t0,.15s) + var(--i)*.07s)}
.m mark{animation:sweep .6s ease-out both;animation-delay:calc(var(--t0,.15s) + var(--i)*.07s + .35s)}
.m.th-naskh mark{animation-name:sweepline}
.m .kicker{animation:pop .5s cubic-bezier(.2,.8,.2,1) both}
.m .a{animation:rise .6s cubic-bezier(.2,.8,.2,1) both;animation-delay:var(--d,.6s)}
.m .a-pop{animation:pop .55s cubic-bezier(.2,.8,.2,1) both;animation-delay:var(--d,.6s)}
.m .bar .fill{animation:growx .9s cubic-bezier(.2,.8,.2,1) both;animation-delay:var(--d,.6s)}
.m .drift{animation:drift 9s ease-in-out infinite}
.m .spin{animation:spin 24s linear infinite}
.m .draw{stroke-dasharray:8000;animation:draw 2.4s ease-out both}
.m .bub.me{animation-name:slidein}
.still *{animation:none!important}
"""
    return base + themecss + motion


FIT_JS = """
<script>
window.__igfa_ready=function(){
  var MIN=0.55, over=false;
  document.querySelectorAll('.fit').forEach(function(box){
    var els=box.querySelectorAll('h1,h2,p,li,.stat,.action,.lab,.bub,.quote,.tile b,.tile span,.lb');
    var base=[];els.forEach(function(e){base.push(parseFloat(getComputedStyle(e).fontSize));});
    var k=1;
    while(box.scrollHeight>box.clientHeight+2 && k>MIN){
      k-=0.035;els.forEach(function(e,i){e.style.fontSize=(base[i]*k)+'px';});
    }
    if(box.scrollHeight>box.clientHeight+2){over=true;}
  });
  return {overflow:over};
};
window.__seek=function(t){
  document.getAnimations().forEach(function(a){a.pause();a.currentTime=t*1000;});
  document.querySelectorAll('[data-count]').forEach(function(el){
    var to=parseFloat(el.dataset.count), d=parseFloat(el.dataset.delay||'.6'), dur=1.2;
    var p=Math.max(0,Math.min(1,(t-d)/dur)); p=1-Math.pow(1-p,3);
    var v=to*p, dec=(el.dataset.dec|0);
    var s=v.toFixed(dec); if(el.dataset.fa==='1'){s=s.replace(/[0-9]/g,function(c){return '۰۱۲۳۴۵۶۷۸۹'[c];});}
    el.textContent=(el.dataset.pre||'')+s+(el.dataset.suf||'');
  });
  return true;
};
</script>
"""


# ---------------------------------------------------------------- layouts

def kicker_html(s, T, d=None):
    if not s.get("kicker"):
        return ""
    ic = icon(s.get("kicker_icon"), 40)
    return f'<div class="kicker">{ic}{rich(s["kicker"], T)}</div>'


def title_html(s, T, tag="h2", words=True, key="title"):
    if not s.get(key):
        return ""
    return f"<{tag}>{rich(s[key], T, words=words)}</{tag}>"


def stat_html(s, T):
    raw = str(s.get("number", ""))
    m = re.match(r"^(\D*?)(\d+(?:[.,]\d+)?)(.*)$", raw)
    if not m:
        return f'<div class="stat a-pop" style="--d:.3s">{rich(raw, T)}</div>'
    pre, num, suf = m.groups()
    num = num.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    dec = len(num.split(".")[1]) if "." in num else 0
    shown = fa(raw, T["digits"])
    return (f'<div class="stat a-pop" style="--d:.2s"><span data-count="{num.replace(",", "")}" data-dec="{dec}" '
            f'data-pre="{H.escape(fa(pre, T["digits"]))}" data-suf="{H.escape(fa(suf, T["digits"]))}" data-delay=".4" '
            f'data-fa="{1 if T["digits"] else 0}">{H.escape(shown)}</span></div>')


def body_html(s, T, L, base, big):
    r = lambda k, **kw: rich(s.get(k), T, **kw)  # noqa: E731
    head = kicker_html(s, T) + title_html(s, T, "h2")
    if L == "text":
        return head, f'<div class="grow fit center"><p class="body a" style="--d:.7s">{r("body")}</p></div>'
    if L in ("list", "steps"):
        items = []
        for i, it in enumerate(s.get("items", []), 1):
            if isinstance(it, dict):
                txt, ic = it.get("text", ""), it.get("icon")
            else:
                txt, ic = it, None
            marker = icon(ic, 46) if ic else fa(str(i), T["digits"])
            items.append(f'<li class="a" style="--d:{0.6 + i * 0.22:.2f}s"><span class="num">{marker}</span>'
                         f'<span class="it">{rich(txt, T)}</span></li>')
        return head, f'<div class="grow fit center"><ol class="list">{"".join(items)}</ol></div>'
    if L == "grid":
        tiles = []
        for i, it in enumerate(s.get("items", [])[:6], 1):
            it = it if isinstance(it, dict) else {"title": it}
            tiles.append(f'<div class="tile a-pop" style="--d:{0.5 + i * 0.18:.2f}s">{icon(it.get("icon"), 72)}'
                         f'<b>{rich(it.get("title"), T)}</b>{"<span>" + rich(it.get("text"), T) + "</span>" if it.get("text") else ""}</div>')
        return head, f'<div class="grow fit center"><div class="grid4">{"".join(tiles)}</div></div>'
    if L == "quote":
        by = f'<p class="by a" style="--d:1.4s">— {r("by")}</p>' if s.get("by") else ""
        return kicker_html(s, T), (f'<div class="grow fit center"><div class="qbar"><p class="quote">{r("text", words=True)}</p>'
                                   f'</div>{by}</div>')
    if L == "compare":
        def box(side, lab, cls, ic, d):
            return (f'<div class="box {cls} a" style="--d:{d}s"><div class="lab">{icon(ic, 44)}{rich(s.get(side + "_label") or lab, T)}</div>'
                    f'<p>{r(side)}</p></div>')
        return head, (f'<div class="grow fit center"><div class="cmp">{box("left", "قبل", "bad", "x", .6)}'
                      f'{box("right", "بعد", "good", "check", 1.0)}</div></div>')
    if L == "stat":
        src = f'<p class="src a" style="--d:1.4s">منبع: {r("source")}</p>' if s.get("source") else ""
        lab = f'<p class="sub a" style="--d:1.1s">{r("label")}</p>' if s.get("label") else ""
        return kicker_html(s, T) + title_html(s, T, "h2"), f'<div class="grow fit center">{stat_html(s, T)}{lab}{src}</div>'
    if L == "prompt":
        note = f'<p class="note a" style="--d:1.2s">{r("note")}</p>' if s.get("note") else ""
        return head, (f'<div class="grow fit center"><div class="prompt a" style="--d:.6s"><div class="ptag">{icon("sparkles", 34)}'
                      f'{rich(s.get("tag", "پرامپت"), T)}</div><p dir="auto">{rich(s.get("text"), T, keep_digits=True)}</p></div>{note}</div>')
    if L == "image":
        cap = f'<p class="note">{r("caption")}</p>' if s.get("caption") else ""
        return head, f'<div class="imgwrap a-pop" style="--d:.5s"><img src="{img_url(s["src"], base)}"></div><div class="fit">{cap}</div>'
    if L == "phone":
        cap = f'<p class="note" style="text-align:center">{r("caption")}</p>' if s.get("caption") else ""
        return head, (f'<div class="grow" style="align-items:center"><div class="phone a" style="--d:.4s">'
                      f'<img src="{img_url(s["src"], base)}"></div></div>{cap}')
    if L == "chat":
        msgs = []
        for i, m in enumerate(s.get("messages", [])):
            who = "me" if m.get("from") == "me" else "them"
            msgs.append(f'<div class="bub {who} a" style="--d:{0.6 + i * 0.55:.2f}s">{rich(m.get("text"), T)}</div>')
        return head, (f'<div class="grow fit center"><div class="chat a" style="--d:.35s"><div class="hd"><div class="av">'
                      f'{icon(s.get("avatar_icon", "user"), 36)}</div>{rich(s.get("name", "مشتری"), T)}</div>{"".join(msgs)}</div></div>')
    if L == "chart":
        bars = s.get("bars", [])
        vmax = max([float(b.get("value", 0)) for b in bars] or [1]) or 1
        rows = []
        for i, b in enumerate(bars):
            w = max(6, 100 * float(b.get("value", 0)) / vmax)
            disp = fa(str(b.get("display", b.get("value", ""))), T["digits"])
            rows.append(f'<div class="bar {"hl" if b.get("hl") else ""}"><div class="lb">{rich(b.get("label"), T)}</div>'
                        f'<div class="tr"><div class="fill {"small" if w < 30 else ""}" style="--w:{w:.1f}%;--d:{0.6 + i * 0.25:.2f}s">'
                        f'<span>{H.escape(disp)}</span></div></div></div>')
        src = f'<p class="src">منبع: {r("source")}</p>' if s.get("source") else ""
        return head, f'<div class="grow fit center"><div class="chart">{"".join(rows)}</div>{src}</div>'
    raise ValueError(f"چیدمان ناشناخته: {L}")


def frame_html(s, idx, total, fmt, brand, ctx, mode="still"):
    T = tokens(brand)
    W, Hh = SIZES[fmt]
    L = s.get("layout", "text")
    base = ctx["base"]
    big = fmt in ("story", "reel")
    pt, pb, pl, pr = (250, 340, 90, 90) if big else (120, 150, 90, 90)
    if L == "reel-frame":
        pt, pb, pr = 260, 500, 250
    if L == "reel-cover":
        pt, pb = 400, 420
    if T["name"] == "naskh" and not big:
        pt = 150
    style = s.get("style", "")
    cls = ["frame"]
    if style == "primary":
        cls.append("v-primary")
    if style == "accent":
        cls.append("v-accent")
    photo = s.get("bg") or (s.get("src") if L == "photo" else None)
    pre = ""
    if photo:
        fx, fy = s.get("focus", (0.5, 0.5))
        shade = s.get("shade", "bottom" if L == "photo" else "full")
        grad = {"bottom": "linear-gradient(180deg,rgba(8,10,16,.05) 25%,rgba(8,10,16,.85) 100%)",
                "top": "linear-gradient(0deg,rgba(8,10,16,.05) 25%,rgba(8,10,16,.85) 100%)",
                "full": "linear-gradient(180deg,rgba(8,10,16,.55),rgba(8,10,16,.7))",
                "center": "radial-gradient(circle,rgba(8,10,16,.65),rgba(8,10,16,.35))"}[shade]
        pre = (f'<div class="photo-bg drift" style="--dx:-18px;--dy:-12px;--fx:{fx * 100:.0f}%;--fy:{fy * 100:.0f}%;'
               f'background-image:url(\'{img_url(photo, base)}\')"></div><div class="photo-shade" style="background:{grad}"></div>')
        cls.append("on-photo")

    if L in ("cover", "cta", "reel-cover", "photo"):
        ic = f'<div class="bigic a-pop" style="--d:.1s">{icon(s["icon"], 150)}</div>' if s.get("icon") else ""
        sub = f'<p class="sub a" style="--d:1.0s">{rich(s.get("subtitle") or s.get("body"), T)}</p>' if (s.get("subtitle") or s.get("body")) else ""
        act = (f'<div class="action a-pop" style="--d:1.1s">{icon(s.get("action_icon", "message-circle"), 50)}'
               f'{rich(s["action"], T)}</div>') if (L == "cta" and s.get("action")) else ""
        valign = "flex-end" if (L == "photo" and s.get("position", "bottom") == "bottom") else \
                 ("flex-start" if s.get("position") == "top" else "center")
        inner = (f'<div class="grow fit" style="justify-content:{valign}">{ic}{kicker_html(s, T)}'
                 f'<div style="height:30px"></div>{title_html(s, T, "h1")}{sub}{act}</div>')
    elif L in ("story", "reel-frame"):
        img = f'<div class="simg a-pop" style="--d:.2s"><img src="{img_url(s["src"], base)}"></div>' if s.get("src") else ""
        ic = f'<div class="bigic a-pop" style="--d:.1s">{icon(s["icon"], 150)}</div>' if s.get("icon") else ""
        sticker = ""
        if s.get("sticker") and s.get("sticker") != "none":
            names = {"poll": "استیکر نظرسنجی", "question": "استیکر سؤال", "link": "استیکر لینک", "quiz": "استیکر کوییز",
                     "slider": "استیکر اسلایدر", "mention": "منشن", "countdown": "استیکر شمارش معکوس", "dm": "دکمهٔ پیام"}
            ics = {"poll": "bar-chart-3", "question": "message-circle-question", "link": "link", "quiz": "circle-help",
                   "slider": "sliders-horizontal", "countdown": "timer", "mention": "at-sign", "dm": "send"}
            sticker = (f'<div class="sticker a" style="--d:1.2s">{icon(ics.get(s["sticker"], "sticker"), 56)}'
                       f'{names.get(s["sticker"], s["sticker"])} را اینجا بگذار'
                       f'{"<small>" + rich(s.get("sticker_note"), T) + "</small>" if s.get("sticker_note") else ""}</div>')
        tag = "h1" if L == "reel-frame" else "h2"
        bodyp = f'<p class="sub a" style="--d:1.0s">{rich(s.get("body"), T)}</p>' if s.get("body") else ""
        inner = (f'<div class="grow fit center">{img}{ic}{kicker_html(s, T)}<div style="height:24px"></div>'
                 f'{title_html(s, T, tag)}{bodyp}</div>{sticker}')
    else:
        head, body = body_html(s, T, L, base, big)
        inner = f"{head}{body}"

    foot = ""
    if not big:
        swipe = ""
        if ctx["type"] == "carousel" and total > 1:
            cnt = fa(f"{idx}/{total}", T["digits"])
            swipe = (f'<span class="swipe">{icon("arrow-left", 38, 2.6)}ورق بزن&nbsp;&nbsp;<span style="font-weight:500;'
                     f'color:inherit;opacity:.7">{cnt}</span></span>' if idx < total else f"<span>{cnt}</span>")
        foot = f'<div class="foot"><span class="handle">{H.escape(T["handle"])}</span>{swipe}</div>'

    page_cls = f"th-{T['name']} " + ("m" if mode == "motion" else "still")
    dec = decor(T, s, idx, total, fmt, W, Hh, ctx.get("key", "x")) if mode != "overlay" else ""
    style_vars = f"--pt:{pt}px;--pb:{pb}px;--pl:{pl}px;--pr:{pr}px"
    body_bg = ""
    if style in ("primary", "accent"):
        body_bg = (f"background:{T['primary']};color:{T['on_primary']}" if style == "primary"
                   else f"background:{T['accent']};color:{T['on_accent']}")
        if T["name"] == "naskh" and style == "primary":
            body_bg = f"background:{T['ink']};color:{T['bg']}"
        if T["name"] == "night" and style == "primary":
            body_bg = f"background:radial-gradient(circle at 80% 10%,{T['primary']},{T['bg']} 70%);color:{T['ink']}"
    return f"""<!doctype html><html lang="fa" dir="rtl" class="{page_cls}"><head><meta charset="utf-8">
<style>{font_faces()}{css(T, W, Hh, fmt, mode)}</style></head>
<body class="{'overlay' if mode == 'overlay' else ''}" style="{body_bg}">{pre}{dec}
<div class="{' '.join(cls)}" style="{style_vars}">{inner}</div>{foot}{FIT_JS}</body></html>"""


def overlay_html(s, brand, mode="motion"):
    """متن روی کلیپ/عکس: کادر نیمه‌شفاف در منطقهٔ امن ریلز، با موشن ورود."""
    T = tokens(brand)
    W, Hh = SIZES["reel"]
    pos = s.get("text_pos", "center")
    top = {"top": "300px", "center": "auto", "bottom": "auto"}[pos]
    bottom = {"top": "auto", "center": "auto", "bottom": f"{1920 - 1440}px"}[pos]
    center = "top:50%;transform:translateY(-50%);" if pos == "center" else ""
    title = f'<h2 style="font-size:84px;color:#fff;line-height:1.38">{rich(s.get("title"), T, words=True)}</h2>' if s.get("title") else ""
    body = f'<p class="a" style="--d:.8s;font-size:50px;line-height:1.55;color:rgba(255,255,255,.9);margin-top:14px">{rich(s.get("body"), T)}</p>' if s.get("body") else ""
    box_bg = {"night": "rgba(13,18,34,.62)", "pop": T["primary"], "naskh": "rgba(20,18,16,.66)"}.get(T["name"], "rgba(12,14,20,.58)")
    page_cls = f"th-{T['name']} " + ("m" if mode == "motion" else "still")
    return f"""<!doctype html><html lang="fa" dir="rtl" class="{page_cls}"><head><meta charset="utf-8">
<style>{font_faces()}{css(T, W, Hh, 'reel', 'overlay')}
html,body{{background:transparent!important}} body:before{{display:none}}
.ov{{position:absolute;right:250px;left:90px;top:{top};bottom:{bottom};{center}display:flex;justify-content:flex-start}}
.ovb{{background:{box_bg};backdrop-filter:blur(14px);border-radius:{T['radius']}px;padding:36px 46px;max-width:100%}}
.th-pop .ovb{{border:5px solid {T['ink']};box-shadow:10px 10px 0 {T['ink']}}}
mark{{color:{T["accent"]}!important;background:none!important;-webkit-text-fill-color:currentColor}}
</style></head><body class="overlay"><div class="ov"><div class="ovb a-pop" style="--d:.05s">{title}{body}</div></div>{FIT_JS}</body></html>"""
