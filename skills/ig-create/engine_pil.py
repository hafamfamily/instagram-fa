"""
engine_pil.py - موتور ساخت تصویر بدون مرورگر، با Pillow.

چرا: محیطی که Claude در آن اجرا می‌شود همیشه مرورگر ندارد. Pillow با libraqm متن فارسی را
درست می‌چسباند و راست‌به‌چپ می‌چیند؛ این موتور همهٔ چیدمان‌های render.py را با همان spec.json
می‌سازد، به‌علاوهٔ چیدمان‌هایی که با عکس و گرافیک کار می‌کنند:

  photo    عکس تمام‌صفحه با سایهٔ رنگی و متن روی آن
  chat     شبیه‌سازی گفت‌وگوی دایرکت (حباب‌های پیام)
  phone    اسکرین‌شات داخل قاب گوشی
  chart    نمودار میله‌ای ساده با برچسب فارسی

و برای ویدیو، «لایهٔ رو» (overlay): متن با پس‌زمینهٔ شفاف که روی کلیپ یا عکس می‌نشیند.

پیش‌نیاز: Pillow با پشتیبانی raqm (features.check('raqm') == True).
"""

import os
import re

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps, features

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(HERE, "fonts")
W_REG, W_MED, W_BOLD, W_BLACK = "Regular", "Medium", "Bold", "Black"

PERSIAN = re.compile(r"[؀-ۿﭐ-﷿ﹰ-﻿]")
LATIN = re.compile(r"[A-Za-z]")
EMOJI = re.compile(r"[\U0001F000-\U0001FAFF☀-➿️‍⭐⬆↔-⇿]")
FA_DIG = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def available():
    try:
        return features.check("raqm")
    except Exception:
        return False


# ---------------------------------------------------------------- basics

_FONTS = {}


def font(weight, size):
    key = (weight, int(size))
    if key not in _FONTS:
        _FONTS[key] = ImageFont.truetype(os.path.join(FONT_DIR, f"Vazirmatn-{weight}.ttf"), int(size),
                                         layout_engine=ImageFont.Layout.RAQM)
    return _FONTS[key]


def rgb(hexstr, alpha=255):
    h = hexstr.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha)


def mix(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def fa_digits(text, on=True):
    if not on:
        return text
    return re.sub(r"(?<![A-Za-z\-_.])\d+(?:[.,]\d+)*(?![A-Za-z])", lambda m: m.group().translate(FA_DIG), text)


def clean(text):
    # وزیرمتن پیکان ندارد؛ به جایش ‹ و › (به همان جهت پیکان)
    t = str(text or "").replace("←", "‹").replace("→", "›").replace("✓", "•").replace("✔", "•")
    return EMOJI.sub("", t).strip()


def load_image(path, base):
    p = path if os.path.isabs(path) else os.path.join(base, path)
    if not os.path.exists(p):
        raise FileNotFoundError(f"تصویر پیدا نشد: {p}")
    im = Image.open(p)
    im = ImageOps.exif_transpose(im)
    return im.convert("RGBA")


def cover_fit(im, size, focus=(0.5, 0.5)):
    return ImageOps.fit(im, size, method=Image.LANCZOS, centering=tuple(focus))


def contain_fit(im, size):
    im = im.copy()
    im.thumbnail(size, Image.LANCZOS)
    return im


def round_mask(size, radius):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=radius, fill=255)
    return m


def dashed_rect(d, box, color, width=4, dash=18, gap=12, radius=0):
    x0, y0, x1, y1 = box
    for (ax, ay, bx, by) in ((x0 + radius, y0, x1 - radius, y0), (x0 + radius, y1, x1 - radius, y1),
                             (x0, y0 + radius, x0, y1 - radius), (x1, y0 + radius, x1, y1 - radius)):
        length = max(abs(bx - ax), abs(by - ay))
        pos = 0
        while pos < length:
            end = min(pos + dash, length)
            if ay == by:
                d.line((ax + pos, ay, ax + end, by), fill=color, width=width)
            else:
                d.line((ax, ay + pos, bx, ay + end), fill=color, width=width)
            pos += dash + gap
    if radius:
        for cx, cy, start in ((x0 + radius, y0 + radius, 180), (x1 - radius, y0 + radius, 270),
                              (x1 - radius, y1 - radius, 0), (x0 + radius, y1 - radius, 90)):
            d.arc((cx - radius, cy - radius, cx + radius, cy + radius), start, start + 90, fill=color, width=width)


# ---------------------------------------------------------------- rich text

class Tok:
    __slots__ = ("text", "hl", "ltr", "w")

    def __init__(self, text, hl):
        self.text, self.hl = text, hl
        self.ltr = bool(LATIN.search(text)) and not PERSIAN.search(text)
        self.w = 0


def tokenize(text, digits_on=True):
    """«**پررنگ**» به نوبت‌های پررنگ؛ خط جدید به None (شکست اجباری)."""
    text = clean(text)
    out = []
    for li, line in enumerate(text.split("\n")):
        if li:
            out.append(None)
        parts = re.split(r"(\*\*.+?\*\*)", line)
        for part in parts:
            if not part:
                continue
            hl = part.startswith("**") and part.endswith("**") and len(part) > 4
            body = part[2:-2] if hl else part
            body = fa_digits(body, digits_on)
            for w in body.split():
                out.append(Tok(w, hl))
    # کلمه‌های لاتین پشت‌سرهم یک واحد شوند تا ترتیبشان در خط راست‌به‌چپ برعکس نشود
    merged = []
    for t in out:
        prev = merged[-1] if merged else None
        if (t is not None and prev is not None and prev.ltr and prev.hl == t.hl
                and (t.ltr or re.fullmatch(r"[\d.,:%+\-/]+", t.text))):
            prev.text += " " + t.text
            continue
        merged.append(t)
    return merged


class Block:
    """یک پاراگراف چیده‌شده: خط‌ها، اندازه، رنگ."""

    def __init__(self, text, size, weight, color, hl_color, max_w, line_h=1.6, align="right",
                 hl_weight=None, digits_on=True, tracking=0):
        self.size, self.weight, self.color, self.hl_color = size, weight, color, hl_color
        self.hl_weight = hl_weight or (W_BLACK if weight in (W_BLACK, W_BOLD) else W_BOLD)
        self.align, self.line_h, self.max_w = align, line_h, max_w
        f, fh = font(weight, size), font(self.hl_weight, size)
        self.space = f.getlength(" ", direction="rtl", language="fa")
        self.lines = [[]]
        width = 0
        for t in tokenize(text, digits_on):
            if t is None:
                self.lines.append([])
                width = 0
                continue
            ff = fh if t.hl else f
            t.w = ff.getlength(t.text, direction="ltr" if t.ltr else "rtl", language=None if t.ltr else "fa")
            need = t.w + (self.space if self.lines[-1] else 0)
            if self.lines[-1] and width + need > max_w:
                self.lines.append([t])
                width = t.w
            else:
                self.lines[-1].append(t)
                width += need
        self.widths = [sum(t.w for t in ln) + self.space * max(0, len(ln) - 1) for ln in self.lines]
        self.height = int(len(self.lines) * size * line_h)
        self.width = max(self.widths) if self.widths else 0
        self.overflow_w = any(w > max_w + 1 for w in self.widths)

    def draw(self, img, x_right, y, shadow=None):
        d = ImageDraw.Draw(img)
        f, fh = font(self.weight, self.size), font(self.hl_weight, self.size)
        lh = self.size * self.line_h
        # Vazirmatn: خط پایه را کمی پایین‌تر از بالای سطر می‌گذاریم تا وسط سطر بنشیند
        dy = (lh - self.size * 1.25) / 2
        for i, ln in enumerate(self.lines):
            lw = self.widths[i]
            if self.align == "center":
                x = x_right - (self.max_w - lw) / 2
            elif self.align == "left":
                x = x_right - self.max_w + lw
            else:
                x = x_right
            yy = y + i * lh + dy
            for t in ln:
                x -= t.w
                ff = fh if t.hl else f
                col = self.hl_color if t.hl else self.color
                kw = dict(font=ff, direction="ltr" if t.ltr else "rtl")
                if not t.ltr:
                    kw["language"] = "fa"
                if shadow:
                    d.text((x + 3, yy + 4), t.text, fill=shadow, **kw)
                d.text((x, yy), t.text, fill=col, **kw)
                x -= self.space


def fit_block(text, max_w, max_h, size, min_size, **kw):
    """بزرگ‌ترین اندازه‌ای که در max_w × max_h جا شود. (block, overflow)"""
    s = size
    while True:
        b = Block(text, s, max_w=max_w, **kw)
        if b.height <= max_h and not b.overflow_w:
            return b, False
        if s <= min_size:
            return b, True
        s = max(min_size, s - max(2, s * 0.06))


# ---------------------------------------------------------------- page

class Page:
    def __init__(self, w, h, brand, fmt, base, style=""):
        self.w, self.h, self.brand, self.fmt, self.base = w, h, brand, fmt, base
        self.primary = style == "primary"
        B = brand
        self.c = {
            "bg": rgb(B["primary"] if self.primary else B["bg"]),
            "text": rgb(B["on_primary"] if self.primary else B["text"]),
            "muted": rgb(B["on_primary"], 210) if self.primary else rgb(B["muted"]),
            "hl": rgb(B["accent"] if self.primary else B["primary"]),
            "primary": rgb(B["primary"]), "accent": rgb(B["accent"]), "on_primary": rgb(B["on_primary"]),
            "surface": rgb(B["surface"]),
        }
        self.digits = B.get("digits") == "fa"
        self.corner = int(B.get("corner", 28))
        self.img = Image.new("RGBA", (w, h), self.c["bg"])
        self.overflow = False

    def block(self, text, size, weight=W_REG, color=None, hl=None, max_w=None, max_h=None, min_size=None,
              line_h=1.6, align="right"):
        max_w = max_w or self.cw
        kw = dict(weight=weight, color=color or self.c["text"], hl_color=hl or self.c["hl"],
                  line_h=line_h, align=align, digits_on=self.digits)
        if max_h is None:
            b = Block(text, size, max_w=max_w, **kw)
            if b.overflow_w:
                b, ov = fit_block(text, max_w, 10 ** 6, size, min_size or size * 0.5, **kw)
            return b
        b, ov = fit_block(text, max_w, max_h, size, min_size or size * 0.5, **kw)
        self.overflow |= ov
        return b

    def box(self, pt, pr, pb, pl):
        self.top, self.right, self.bottom, self.left = pt, self.w - pr, self.h - pb, pl
        self.cw = self.right - self.left

    # ------------------------------------------------ pieces

    def bar(self):
        d = ImageDraw.Draw(self.img)
        d.rectangle((0, 0, self.w, 14), fill=self.c["primary"])
        d.rectangle((int(self.w * 0.72), 0, self.w, 14), fill=self.c["accent"])

    def kicker(self, text, y, on_photo=False):
        b = self.block(text, 32 if self.fmt in ("post", "square") else 40, W_BOLD,
                       color=self.c["on_primary"] if (self.primary or on_photo) else self.c["primary"])
        b.align = "right"
        padx, pady = 26, 10
        w, h = int(b.width + padx * 2), int(b.height + pady * 2 - b.size * 0.2)
        x1 = self.right
        fill = (255, 255, 255, 46) if (self.primary or on_photo) else self.c["primary"][:3] + (30,)
        layer = Image.new("RGBA", self.img.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).rounded_rectangle((x1 - w, y, x1, y + h), radius=h // 2, fill=fill)
        self.img.alpha_composite(layer)
        b.max_w = b.width
        b.draw(self.img, x1 - padx, y + pady - b.size * 0.1)
        return h

    def footer(self, idx, total, typ):
        if self.fmt not in ("post", "square"):
            return
        y = self.bottom - 30
        handle = clean(self.brand.get("handle", ""))
        f = font(W_MED, 30)
        d = ImageDraw.Draw(self.img)
        d.text((self.right - f.getlength(handle), y - 22), handle, font=f, fill=self.c["muted"])
        if typ == "carousel" and total > 1:
            cnt = fa_digits(f"{idx}/{total}", self.digits)
            x = self.left
            if idx < total:
                col = self.c["hl"] if not self.primary else self.c["accent"]
                # پیکان: فونت وزیرمتن «←» ندارد، پس می‌کشیمش
                d.line((x, y - 2, x + 30, y - 2), fill=col, width=4)
                d.polygon([(x - 4, y - 2), (x + 10, y - 12), (x + 10, y + 8)], fill=col)
                x += 44
                sw = "ورق بزن"
                fb = font(W_BLACK, 30)
                d.text((x, y - 22), sw, font=fb, fill=col, direction="rtl", language="fa")
                x += fb.getlength(sw, direction="rtl", language="fa") + 24
            d.text((x, y - 22), cnt, font=f, fill=self.c["muted"], direction="rtl", language="fa")

    def photo_bg(self, path, focus=(0.5, 0.5), shade="bottom", strength=0.78):
        im = cover_fit(load_image(path, self.base), (self.w, self.h), focus)
        self.img = im.convert("RGBA")
        grad = Image.new("L", (1, 256))
        for i in range(256):
            t = i / 255
            if shade == "top":
                a = (1 - t) ** 1.4
            elif shade == "full":
                a = 0.75
            elif shade == "center":
                a = 0.55
            else:
                a = t ** 1.3
            grad.putpixel((0, i), int(255 * min(1, a * strength + 0.12)))
        alpha = grad.resize((self.w, self.h))
        dark = Image.new("RGBA", (self.w, self.h), (10, 12, 18, 255))
        dark.putalpha(alpha)
        self.img.alpha_composite(dark)
        self.c["text"] = (255, 255, 255, 255)
        self.c["muted"] = (235, 235, 235, 230)
        self.c["hl"] = self.c["accent"]

    def paste_rounded(self, im, box_xy, radius=None):
        radius = self.corner if radius is None else radius
        mask = round_mask(im.size, radius)
        self.img.paste(im, box_xy, mask)

    # ------------------------------------------------ vertical stack

    def stack(self, items, y0, y1, valign="center"):
        """items: list of (height, draw_fn(y), gap_after). در بازهٔ y0..y1 می‌چیند."""
        total = sum(h for h, _, _ in items) + sum(g for _, _, g in items[:-1])
        if total > y1 - y0 + 2:
            self.overflow = True
        y = y0 if valign == "top" else y0 + max(0, (y1 - y0 - total) / 2)
        for h, fn, g in items:
            fn(int(y))
            y += h + g


# ---------------------------------------------------------------- layouts

def render_slide(s, idx, total, fmt, brand, ctx, size, overlay=False):
    """یک اسلاید → (Image RGBA، overflow)"""
    W, H = size
    L = s.get("layout", "text")
    p = Page(W, H, brand, fmt, ctx["base"], s.get("style", ""))
    story_like = fmt in ("story", "reel")
    pt, pb, px, pr = (250, 340, 90, 90) if story_like else (110, 110, 90, 90)
    if L == "reel-frame":
        pt, pb, pr = 260, 500, 250
    if L == "reel-cover":
        pt, pb = 420, 420
    p.box(pt, pr, pb, px)
    big = story_like

    if overlay:
        p.img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        return render_overlay(p, s), p.overflow

    bg = s.get("bg")
    if L == "photo":
        bg = s.get("src")
    if bg:
        p.photo_bg(bg, s.get("focus", (0.5, 0.5)),
                   s.get("shade", "bottom" if L == "photo" else "full"))
    elif not story_like and not p.primary:
        p.bar()

    T = lambda k: s.get(k)  # noqa: E731
    items = []
    head = []

    def add_kicker():
        if T("kicker"):
            head.append((60 if not big else 72, lambda y: p.kicker(T("kicker"), y, on_photo=bool(bg)), 36))

    def add_title(size, max_h=None, gap=36, weight=W_BLACK, align="right"):
        if T("title"):
            b = p.block(T("title"), size, weight, max_h=max_h, line_h=1.38, align=align)
            head.append((b.height, lambda y, b=b: b.draw(p.img, p.right, y), gap))

    footer_h = 0 if story_like else 70
    y_top, y_bot = p.top, p.bottom - footer_h

    if L in ("cover", "cta", "reel-cover", "photo"):
        add_kicker()
        tsize = {"reel-cover": 124, "photo": 88}.get(L, 96 if not big else 112)
        b = p.block(T("title") or "", tsize, W_BLACK, max_h=(y_bot - y_top) * 0.6, line_h=1.32)
        items = head + [(b.height, lambda y: b.draw(p.img, p.right, y), 30)]
        if L == "photo" and T("body"):
            bb = p.block(T("body"), 46, W_MED, color=p.c["muted"], max_h=320)
            items.append((bb.height, lambda y: bb.draw(p.img, p.right, y), 30))
        if L == "cta" and T("action"):
            a = p.block(T("action"), 46, W_BLACK, color=(30, 36, 48, 255), hl=(30, 36, 48, 255),
                        max_w=p.cw - 90, line_h=1.5)
            aw, ah = a.width + 88, a.height + 40

            def draw_action(y, a=a, aw=aw, ah=ah):
                ImageDraw.Draw(p.img).rounded_rectangle((p.right - aw, y, p.right, y + ah), radius=p.corner,
                                                        fill=p.c["accent"])
                a.max_w = a.width
                a.draw(p.img, p.right - 44, y + 20)
            items.append((ah, draw_action, 30))
        if T("subtitle"):
            sb = p.block(T("subtitle"), 40 if not big else 52, W_MED, color=p.c["muted"], max_h=300)
            items.append((sb.height, lambda y: sb.draw(p.img, p.right, y), 0))
        valign = "bottom" if L == "photo" and s.get("position", "bottom") == "bottom" else "center"
        if valign == "bottom":
            total_h = sum(h for h, _, _ in items) + sum(g for _, _, g in items[:-1])
            p.stack(items, y_bot - total_h, y_bot, "top")
        elif L == "photo" and s.get("position") == "top":
            p.stack(items, y_top, y_bot, "top")
        else:
            p.stack(items, y_top, y_bot)

    elif L in ("text", "list", "steps", "prompt", "compare", "quote", "stat", "chat", "phone", "chart", "image"):
        add_kicker()
        add_title(64 if not big else 84, max_h=(y_bot - y_top) * 0.3)
        head_h = sum(h + g for h, _, g in head)
        p.stack(head, y_top, y_top + head_h, "top")
        region = (y_top + head_h, y_bot - 20)
        draw_body(p, s, L, region, big)

    elif L in ("story", "reel-frame"):
        add_kicker()
        tsize = 104 if L == "reel-frame" else 92
        img_h = 0
        if T("src"):
            im = contain_fit(load_image(T("src"), p.base), (p.cw, 820))
            img_h = im.size[1]
            items.append((img_h, lambda y, im=im: p.paste_rounded(im, (p.left + (p.cw - im.size[0]) // 2, y)), 40))
        stick_h = 300 if (T("sticker") and T("sticker") != "none") else 0
        room = (y_bot - y_top) - img_h - stick_h - 160
        if T("title"):
            b = p.block(T("title"), tsize, W_BLACK, max_h=max(200, room * 0.62), line_h=1.38)
            items.append((b.height, lambda y, b=b: b.draw(p.img, p.right, y, shadow=(0, 0, 0, 120) if bg else None), 24))
        if T("body"):
            bb = p.block(T("body"), 56, W_REG, max_h=max(160, room * 0.38), line_h=1.6)
            items.append((bb.height, lambda y, bb=bb: bb.draw(p.img, p.right, y), 24))
        if stick_h:
            items.append((stick_h, lambda y: draw_sticker(p, s, y), 0))
        items = head + items
        p.stack(items, y_top, y_bot)
    else:
        raise ValueError(f"چیدمان ناشناخته: {L}")

    p.footer(idx, total, ctx["type"])
    return p.img, p.overflow


STICKER_FA = {"poll": "استیکر نظرسنجی", "question": "استیکر سؤال", "link": "استیکر لینک", "quiz": "استیکر کوییز",
              "slider": "استیکر اسلایدر", "mention": "منشن", "countdown": "استیکر شمارش معکوس", "dm": "دکمهٔ پیام"}


def draw_sticker(p, s, y):
    d = ImageDraw.Draw(p.img)
    col = p.c["muted"]
    dashed_rect(d, (p.left, y, p.right, y + 280), col, width=4, radius=p.corner)
    name = STICKER_FA.get(s.get("sticker"), s.get("sticker"))
    b = p.block(f"{name} را اینجا بگذار", 38, W_BOLD, color=col, max_w=p.cw - 80, align="center", line_h=1.5)
    yy = y + 140 - (b.height + (60 if s.get("sticker_note") else 0)) / 2
    b.draw(p.img, p.right - 40, yy)
    if s.get("sticker_note"):
        n = p.block(s["sticker_note"], 30, W_REG, color=col, max_w=p.cw - 80, align="center", line_h=1.5)
        n.draw(p.img, p.right - 40, yy + b.height + 6)


def draw_body(p, s, L, region, big):
    y0, y1 = region
    avail = y1 - y0
    T = s.get
    d = ImageDraw.Draw(p.img)
    items = []

    if L == "text":
        b = p.block(T("body") or "", 48 if not big else 56, W_REG, max_h=avail, line_h=1.85)
        items = [(b.height, lambda y: b.draw(p.img, p.right, y), 0)]

    elif L in ("list", "steps"):
        rows = T("items") or []
        size = 48
        while True:
            blocks = [p.block(it, size, W_REG, max_w=p.cw - 110, line_h=1.65) for it in rows]
            total = sum(max(b.height, 78) for b in blocks) + 32 * (len(blocks) - 1)
            if total <= avail or size <= 28:
                if total > avail:
                    p.overflow = True
                break
            size -= 3
        num = int(min(78, size * 1.62))
        for i, b in enumerate(blocks, 1):
            def draw_row(y, b=b, i=i):
                d.rounded_rectangle((p.right - num, y + 4, p.right, y + 4 + num), radius=num * 0.28,
                                    fill=p.c["primary"] if not p.primary else p.c["accent"])
                t = fa_digits(str(i), p.digits)
                fn = font(W_BLACK, int(num * 0.5))
                tw = fn.getlength(t)
                d.text((p.right - num / 2 - tw / 2, y + 4 + num * 0.18), t, font=fn,
                       fill=p.c["on_primary"] if not p.primary else (30, 36, 48, 255))
                b.draw(p.img, p.right - num - 28, y)
            items.append((max(b.height, num + 8), draw_row, 32))

    elif L == "quote":
        b = p.block(T("text") or "", 62 if not big else 76, W_BOLD, max_w=p.cw - 60, max_h=avail * 0.75,
                    line_h=1.6)

        def dq(y):
            d.rectangle((p.right - 14, y, p.right, y + b.height), fill=p.c["accent"])
            b.draw(p.img, p.right - 46, y)
        items = [(b.height, dq, 30)]
        if T("by"):
            by = p.block("— " + T("by"), 36, W_REG, color=p.c["muted"], max_w=p.cw - 60)
            items.append((by.height, lambda y: by.draw(p.img, p.right - 46, y), 0))

    elif L == "stat":
        n = p.block(T("number") or "", 220, W_BLACK, color=p.c["hl"], hl=p.c["hl"], max_h=avail * 0.5,
                    line_h=1.15)
        items = [(n.height, lambda y: n.draw(p.img, p.right, y), 26)]
        if T("label"):
            lb = p.block(T("label"), 42, W_MED, color=p.c["muted"], max_h=avail * 0.3)
            items.append((lb.height, lambda y: lb.draw(p.img, p.right, y), 20))
        if T("source"):
            sc = p.block("منبع: " + T("source"), 28, W_REG, color=p.c["muted"])
            items.append((sc.height, lambda y: sc.draw(p.img, p.right, y), 0))

    elif L == "prompt":
        inner = p.cw - 88
        b = p.block(T("text") or "", 42, W_REG, max_w=inner, max_h=avail * 0.72, line_h=1.75)
        bh = b.height + 88

        def dp(y):
            d.rounded_rectangle((p.left, y, p.right, y + bh), radius=p.corner, fill=p.c["surface"])
            dashed_rect(d, (p.left, y, p.right, y + bh), p.c["primary"], width=3, radius=p.corner)
            b.draw(p.img, p.right - 44, y + 44)
            tag = clean(T("tag") or "پرامپت")
            ft = font(W_BOLD, 28)
            tw = ft.getlength(tag, direction="rtl", language="fa")
            d.rounded_rectangle((p.right - 40 - tw - 44, y - 26, p.right - 40, y + 26), radius=26,
                                fill=p.c["primary"])
            d.text((p.right - 62 - tw, y - 20), tag, font=ft, fill=p.c["on_primary"], direction="rtl", language="fa")
        items = [(bh, dp, 30)]
        if T("note"):
            nt = p.block(T("note"), 34, W_REG, color=p.c["muted"], max_h=avail * 0.2)
            items.append((nt.height, lambda y: nt.draw(p.img, p.right, y), 0))

    elif L == "compare":
        boxes = []
        for side, label_def, colr in (("left", "قبل", (220, 38, 38, 255)), ("right", "بعد", p.c["primary"])):
            lab = p.block(T(f"{side}_label") or label_def, 36, W_BLACK, color=colr, hl=colr, max_w=p.cw - 84)
            body = p.block(T(side) or "", 44, W_REG, max_w=p.cw - 84, max_h=avail * 0.36, line_h=1.7)
            boxes.append((lab, body, colr))
        for lab, body, colr in boxes:
            h = lab.height + body.height + 76

            def dbx(y, lab=lab, body=body, colr=colr, h=h):
                d.rounded_rectangle((p.left, y, p.right, y + h), radius=p.corner, fill=p.c["surface"],
                                    outline=colr[:3] + (140,) if colr[0] == 220 else colr, width=3)
                lab.draw(p.img, p.right - 42, y + 34)
                body.draw(p.img, p.right - 42, y + 34 + lab.height)
            items.append((h, dbx, 34))

    elif L == "image":
        cap_h = 0
        cap = None
        if T("caption"):
            cap = p.block(T("caption"), 34, W_REG, color=p.c["muted"], max_h=200)
            cap_h = cap.height + 26
        im = contain_fit(load_image(T("src"), p.base), (p.cw, int(avail - cap_h)))
        items = [(im.size[1], lambda y: p.paste_rounded(im, (p.left + (p.cw - im.size[0]) // 2, y)), 26)]
        if cap:
            items.append((cap.height, lambda y: cap.draw(p.img, p.right, y), 0))

    elif L == "phone":
        cap = None
        cap_h = 0
        if T("caption"):
            cap = p.block(T("caption"), 34, W_REG, color=p.c["muted"], max_h=150, align="center")
            cap_h = cap.height + 24
        ph_h = int(avail - cap_h - 10)
        ph_w = int(min(p.cw * 0.72, ph_h * 0.5))
        ph_h = int(min(ph_h, ph_w * 2.05))
        shot = load_image(T("src"), p.base)
        border = 18
        inner = (ph_w - 2 * border, ph_h - 2 * border)
        sc = ImageOps.fit(shot, inner, Image.LANCZOS, centering=tuple(s.get("focus", (0.5, 0.0))))

        def dph(y):
            x0 = p.left + (p.cw - ph_w) // 2
            shadow = Image.new("RGBA", p.img.size, (0, 0, 0, 0))
            ImageDraw.Draw(shadow).rounded_rectangle((x0 + 10, y + 18, x0 + ph_w + 10, y + ph_h + 18), radius=70,
                                                     fill=(0, 0, 0, 70))
            p.img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(18)))
            d.rounded_rectangle((x0, y, x0 + ph_w, y + ph_h), radius=70, fill=(20, 22, 28, 255))
            p.img.paste(sc, (x0 + border, y + border), round_mask(inner, 54))
            d.rounded_rectangle((x0 + ph_w / 2 - 60, y + border + 14, x0 + ph_w / 2 + 60, y + border + 40),
                                radius=13, fill=(20, 22, 28, 255))
        items = [(ph_h, dph, 24 if cap else 0)]
        if cap:
            items.append((cap.height, lambda y: cap.draw(p.img, p.right, y), 0))

    elif L == "chat":
        msgs = T("messages") or []
        hdr_h = 96
        bw = int(p.cw * 0.74)
        size = 40
        while True:
            bl = [p.block(m.get("text", ""), size, W_REG, max_w=bw - 60, line_h=1.55,
                          color=p.c["on_primary"] if m.get("from") == "me" else p.c["text"],
                          hl=p.c["accent"] if m.get("from") == "me" else p.c["primary"]) for m in msgs]
            total = hdr_h + 30 + sum(b.height + 44 for b in bl) + 22 * max(0, len(bl) - 1) + 40
            if total <= avail or size <= 26:
                if total > avail:
                    p.overflow = True
                break
            size -= 2
        panel_h = total

        def dchat(y):
            d.rounded_rectangle((p.left, y, p.right, y + panel_h), radius=p.corner + 8, fill=p.c["surface"])
            # سربرگ: آواتار و نام
            d.ellipse((p.right - 30 - 64, y + 16, p.right - 30, y + 80), fill=p.c["primary"][:3] + (60,))
            nm = p.block(T("name") or "مشتری", 34, W_BOLD, max_w=p.cw - 140)
            nm.max_w = nm.width
            nm.draw(p.img, p.right - 112, y + 22)
            d.line((p.left + 24, y + hdr_h, p.right - 24, y + hdr_h), fill=p.c["muted"][:3] + (60,), width=2)
            yy = y + hdr_h + 30
            for m, b in zip(msgs, bl):
                me = m.get("from") == "me"
                w = b.width + 60
                h = b.height + 44
                if me:  # پیام خودمان: سمت چپ، رنگ اصلی (چیدمان راست‌به‌چپ اینستاگرام)
                    x0 = p.left + 30
                    d.rounded_rectangle((x0, yy, x0 + w, yy + h), radius=34, fill=p.c["primary"])
                else:
                    x0 = p.right - 30 - w
                    d.rounded_rectangle((x0, yy, x0 + w, yy + h), radius=34, fill=mix(p.c["bg"], p.c["muted"], 0.18))
                b.max_w = b.width
                b.draw(p.img, x0 + w - 30, yy + 22)
                yy += h + 22
        items = [(panel_h, dchat, 0)]

    elif L == "chart":
        bars = T("bars") or []
        vmax = max([float(b.get("value", 0)) for b in bars] or [1]) or 1
        row_h = min(150, (avail - 60) / max(1, len(bars)))
        lab_w = int(p.cw * 0.28)
        track = p.cw - lab_w - 30

        def dch(y):
            for i, bar in enumerate(bars):
                yy = y + i * row_h
                lb = p.block(bar.get("label", ""), 36, W_BOLD, max_w=lab_w, max_h=row_h * 0.8)
                lb.draw(p.img, p.right, yy + (row_h * 0.62 - lb.height) / 2)
                frac = float(bar.get("value", 0)) / vmax
                bw = max(12, int(track * frac))
                x1 = p.right - lab_w - 30
                col = p.c["accent"] if bar.get("hl") else p.c["primary"]
                d.rounded_rectangle((x1 - bw, yy, x1, yy + row_h * 0.62), radius=18, fill=col)
                disp = fa_digits(str(bar.get("display", bar.get("value", ""))), p.digits)
                fv = font(W_BLACK, 34)
                tw = fv.getlength(disp, direction="rtl", language="fa")
                if tw + 40 < bw:
                    d.text((x1 - bw + 22, yy + row_h * 0.31 - 26), disp, font=fv, fill=(255, 255, 255, 255),
                           direction="rtl", language="fa")
                else:
                    d.text((x1 - bw - tw - 16, yy + row_h * 0.31 - 26), disp, font=fv, fill=p.c["text"],
                           direction="rtl", language="fa")
        items = [(int(row_h * len(bars)), dch, 20)]
        if T("source"):
            sc = p.block("منبع: " + T("source"), 28, W_REG, color=p.c["muted"])
            items.append((sc.height, lambda y: sc.draw(p.img, p.right, y), 0))

    p.stack(items, y0, y1)


def render_overlay(p, s):
    """لایهٔ متن شفاف برای ویدیو: متن در کادر نیمه‌شفاف، در منطقهٔ امن."""
    pos = s.get("text_pos", "top" if s.get("layout") in ("reel-cover",) else "center")
    W, H = p.w, p.h
    maxw = W - 90 - 250
    parts = []
    if s.get("title"):
        parts.append(p.block(s["title"], 84, W_BLACK, color=(255, 255, 255, 255), hl=p.c["accent"],
                             max_w=maxw, max_h=520, line_h=1.4))
    if s.get("body"):
        parts.append(p.block(s["body"], 50, W_MED, color=(240, 240, 240, 255), hl=p.c["accent"],
                             max_w=maxw, max_h=300, line_h=1.55))
    if not parts:
        return p.img
    gap = 18
    th = sum(b.height for b in parts) + gap * (len(parts) - 1)
    tw = max(b.width for b in parts)
    padx, pady = 44, 34
    bw, bh = tw + padx * 2, th + pady * 2
    x1 = W - 250  # ستون دکمه‌های اینستاگرام سمت راست
    x0 = x1 - bw
    if pos == "top":
        y0 = 300
    elif pos == "bottom":
        y0 = 1440 - bh
    else:
        y0 = (300 + 1440) / 2 - bh / 2
    box = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(box).rounded_rectangle((x0, y0, x1, y0 + bh), radius=30, fill=(12, 14, 20, 165))
    p.img.alpha_composite(box)
    y = y0 + pady
    for b in parts:
        b.max_w = tw
        b.draw(p.img, x1 - padx, y)
        y += b.height + gap
    return p.img
