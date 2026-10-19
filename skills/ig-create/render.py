#!/usr/bin/env python3
"""
render.py - ساخت تصویرهای آمادهٔ انتشار (کاروسل، پست، استوری، کاور و فریم ریلز) از spec.json.

دو موتور:
  studio  (پیش‌فرض اگر مرورگر هست) سیستم طراحی HTML/CSS در design.py: چهار سبک بصری، آیکون،
          فونت‌های نمایشی، فونت‌های خود کاربر، عکس، بافت و تزئین؛ با کروم بی‌سر (studio.py).
  pil     بدون مرورگر، با Pillow (engine_pil.py). ساده‌تر، ولی همیشه کار می‌کند.

اندازه‌ها: post 1080×1350 (۴:۵)، square 1080×1080، story و reel 1080×1920.
متن‌های بلند خودکار کوچک می‌شوند؛ اگر جا نشوند اسلاید «سرریز» علامت می‌خورد (کد خروج ۳).

استفاده:
  python render.py spec.json --page <پوشهٔ پیج> --out <پوشهٔ خروجی>
  python render.py spec.json --page ... --out ... --only 3
  python render.py --check
  python render.py spec.json --themes --page ... --out <پوشه>   # اسلاید اول با هر چهار سبک
"""

import argparse
import glob
import html
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from fa_text import setup_stdout  # noqa: E402

SIZES = {"post": (1080, 1350), "square": (1080, 1080), "story": (1080, 1920), "reel": (1080, 1920)}
TYPE_FORMAT = {"carousel": "post", "single": "post", "square": "square", "story": "story", "reel": "reel"}
DEFAULT_BRAND = {"handle": "@your.page", "theme": "paper", "digits": "fa"}
PIL_DEFAULTS = {"bg": "#F3F1EA", "surface": "#FFFFFF", "text": "#1B2233", "muted": "#5F6676",
                "primary": "#1F6F5C", "accent": "#F2B134", "on_primary": "#FFFFFF", "corner": 28}


def home_dir():
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(HERE), "ig-setup"))
        import page
        return page.home()
    except Exception:
        return None


def load_brand(page_dir, override=None):
    brand = dict(DEFAULT_BRAND)
    if page_dir:
        p = os.path.join(page_dir, "brand.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                brand.update(json.load(f))
    brand.update(override or {})
    return brand


def pil_brand(brand):
    import design
    T = design.tokens(brand)
    b = dict(PIL_DEFAULTS)
    b.update({"bg": T["bg"], "surface": T["surface"] if T["name"] != "night" else "#1C2440", "text": T["ink"],
              "muted": T["muted"], "primary": T["primary"], "accent": T["accent"], "on_primary": T["on_primary"],
              "handle": brand.get("handle", ""), "digits": brand.get("digits", "fa"), "corner": T["radius"]})
    return b


def setup_fonts(page_dir):
    import design
    dirs = []
    if page_dir:
        dirs.append(os.path.join(page_dir, "fonts"))
    h = home_dir()
    if h:
        dirs.append(os.path.join(h, "fonts"))
    design.USER_FONT_DIRS[:] = dirs


def pick_engine(want):
    import studio
    if want in ("studio", "auto"):
        exe, _ = studio.find_browser()
        if exe:
            return "studio"
        if want == "studio":
            raise RuntimeError("مرورگر آماده نیست؛ `python studio.py setup` را تا READY اجرا کن.")
    import engine_pil
    if not engine_pil.available():
        raise RuntimeError("نه مرورگر هست، نه Pillow با raqm. `python studio.py setup` را اجرا کن.")
    return "pil"


def write_preview(out_dir, files, spec, overflow):
    cap = ""
    for d in (out_dir, os.path.dirname(out_dir)):
        p = os.path.join(d, "caption.txt")
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
<style>body{{font-family:Vazirmatn,Tahoma,sans-serif;background:#eceef2;margin:0;padding:24px;color:#111}}
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


def render(spec_path, page_dir, out_dir, only=None, engine="auto", theme=None):
    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)
    brand = load_brand(page_dir, spec.get("brand"))
    if theme:
        brand["theme"] = theme
    setup_fonts(page_dir)
    typ = spec.get("type", "carousel")
    fmt = spec.get("format") or TYPE_FORMAT.get(typ, "post")
    slides = spec["slides"]
    if typ == "carousel" and len(slides) > 20:
        raise ValueError("کاروسل حداکثر ۲۰ اسلاید دارد.")
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.dirname(os.path.abspath(spec_path))
    ctx = {"type": typ, "base": base, "key": spec.get("title", "x")}
    eng = pick_engine(engine)
    files, overflow = [], []

    def emit(s, sfmt, over, out):
        files.append(out)
        marker = out + ".overflow"  # publish.py اسلاید سرریزدار را تأیید نمی‌کند
        if over:
            overflow.append(os.path.basename(out))
            open(marker, "w").close()
        elif os.path.exists(marker):
            os.remove(marker)
        print(f"  {'⚠️ ' if over else '✓ '}{out}  ({s.get('layout', 'text')}, {sfmt}, {eng})")

    todo = [(i, s) for i, s in enumerate(slides, 1) if not only or i == only]
    if eng == "studio":
        import design
        import studio
        tmp = tempfile.mkdtemp(prefix="igfa-html-")
        with studio.Browser() as b:
            for i, s in todo:
                sfmt = s.get("format", fmt)
                hp = os.path.join(tmp, f"{i:02d}.html")
                with open(hp, "w", encoding="utf-8") as f:
                    f.write(design.frame_html(s, i, len(slides), sfmt, brand, ctx, "still"))
                info = b.open(hp, SIZES[sfmt])
                out = os.path.join(out_dir, f"{i:02d}.png")
                with open(out, "wb") as f:
                    f.write(b.screenshot())
                emit(s, sfmt, bool(info.get("overflow")), out)
        shutil.rmtree(tmp, ignore_errors=True)
    else:
        import engine_pil
        pb = pil_brand(brand)
        for i, s in todo:
            sfmt = s.get("format", fmt)
            out = os.path.join(out_dir, f"{i:02d}.png")
            im, over = engine_pil.render_slide(s, i, len(slides), sfmt, pb, ctx, SIZES[sfmt])
            im.convert("RGB").save(out, optimize=True)
            emit(s, sfmt, over, out)

    if not only:
        for old in glob.glob(os.path.join(out_dir, "[0-9][0-9].png")):
            if old not in files:
                os.remove(old)
                if os.path.exists(old + ".overflow"):
                    os.remove(old + ".overflow")
        prev = write_preview(out_dir, files, spec, overflow)
        print(f"\nپیش‌نمایش: {prev}")
    if overflow:
        print(f"\nسرریز متن در: {'، '.join(overflow)}. متن این اسلایدها را کوتاه کن و دوباره بساز.")
    return files, overflow


def render_overlays(spec_path, page_dir, out_dir):
    """برای ویدیو با موتور Pillow: لایهٔ متن شفاف هر بیتی که کلیپ یا عکس دارد."""
    import engine_pil
    with open(spec_path, encoding="utf-8") as f:
        spec = json.load(f)
    brand = pil_brand(load_brand(page_dir, spec.get("brand")))
    ctx = {"type": "reel", "base": os.path.dirname(os.path.abspath(spec_path))}
    os.makedirs(out_dir, exist_ok=True)
    out = {}
    for i, s in enumerate(spec["slides"], 1):
        if s.get("clip") or s.get("photo"):
            im, over = engine_pil.render_slide(s, i, len(spec["slides"]), "reel", brand, ctx, SIZES["reel"],
                                               overlay=True)
            path = os.path.join(out_dir, f"ov-{i:02d}.png")
            im.save(path)
            out[i] = path
    return out


def main():
    setup_stdout()
    ap = argparse.ArgumentParser(description="ساخت تصویرهای اینستاگرام از spec.json")
    ap.add_argument("spec", nargs="?")
    ap.add_argument("--page", help="پوشهٔ پیج (brand.json و fonts)")
    ap.add_argument("--out", help="پوشهٔ خروجی تصویرها")
    ap.add_argument("--only", type=int, help="فقط همین شمارهٔ اسلاید")
    ap.add_argument("--engine", choices=["auto", "studio", "pil"], default="auto")
    ap.add_argument("--theme", help="سبک موقت برای همین ساخت: paper | pop | night | naskh")
    ap.add_argument("--check", action="store_true", help="بررسی موتورها، فونت‌ها و ffmpeg")
    ap.add_argument("--themes", action="store_true", help="اسلاید اول spec با هر چهار سبک")
    a = ap.parse_args()
    if a.check:
        import studio
        exe, kind = studio.find_browser()
        try:
            import engine_pil
            pil = engine_pil.available()
        except Exception:
            pil = False
        setup_fonts(a.page)
        import design
        print(f"موتور studio (مرورگر): {exe + ' (' + kind + ')' if exe else 'آماده نیست — python studio.py setup'}")
        print(f"موتور Pillow (raqm): {'آماده' if pil else 'نیست'}")
        print(f"فونت‌های کاربر: {', '.join(design.user_fonts()) or 'هیچ (پوشهٔ fonts در خانهٔ پیج‌ها)'}")
        print(f"ffmpeg: {shutil.which('ffmpeg') or 'پیدا نشد'}")
        sys.exit(0 if (exe or pil) else 1)
    if not a.spec:
        ap.error("فایل spec.json را بده")
    out = a.out or os.path.join(os.path.dirname(os.path.abspath(a.spec)), "slides")
    if a.themes:
        import design
        for th in design.THEMES:
            render(a.spec, a.page, os.path.join(out, th), only=1, engine=a.engine, theme=th)
        return
    _, overflow = render(a.spec, a.page, out, a.only, a.engine, a.theme)
    sys.exit(3 if overflow else 0)


if __name__ == "__main__":
    main()
