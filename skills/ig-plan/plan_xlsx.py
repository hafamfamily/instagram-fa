#!/usr/bin/env python3
"""
plan_xlsx.py - تبدیل برنامهٔ هفتگی (plan.json) به فایل اکسل مرتب، رنگی، راست‌به‌چپ و قابل چاپ.

دو برگه می‌سازد:
  «پست‌ها»     هر ردیف یک پست/ریلز، رنگ‌بندی بر اساس نوع، ستون وضعیت با فهرست کشویی
  «استوری‌ها»  هر روز، هر قاب استوری با نقش و استیکرش

قالب plan.json:
{
  "page": "نام پیج", "week_start": "2026-10-24",
  "posts": [{"date": "2026-10-24", "day": "شنبه", "time": "19:00", "type": "carousel",
             "pillar": "...", "title": "...", "hook": "...", "cta": "...", "status": "ایده"}],
  "stories": [{"date": "2026-10-24", "day": "شنبه",
               "frames": [{"time": "09:00", "role": "سلام و زمینه", "idea": "...", "sticker": "poll"}]}]
}

پیش‌نیاز: pip install openpyxl
استفاده:  python plan_xlsx.py plan.json --out plan.xlsx
"""

import argparse
import json
import sys

TYPE_FA = {"carousel": "کاروسل", "single": "پست تکی", "reel": "ریلز", "story": "استوری"}
TYPE_COLOR = {"carousel": "DCEFEA", "single": "E8EEF9", "reel": "FDECD2", "story": "F3E8FA"}
STICKER_FA = {"poll": "نظرسنجی", "question": "سؤال", "link": "لینک", "quiz": "کوییز", "slider": "اسلایدر",
              "countdown": "شمارش معکوس", "mention": "منشن", "dm": "پیام", "none": "-", "": "-"}
STATUSES = ["ایده", "در حال ساخت", "منتظر تأیید", "تأییدشده", "منتشرشده"]


def g2j(gy, gm, gd):
    """تبدیل میلادی به شمسی (الگوریتم استاندارد)."""
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400 + gd + g_d_m[gm - 1]
    jy = -1595 + 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    jm = 1 + days // 31 if days < 186 else 7 + (days - 186) // 30
    jd = 1 + (days % 31 if days < 186 else (days - 186) % 30)
    return jy, jm, jd


FA_DIG = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def shamsi(iso):
    try:
        y, m, d = (int(x) for x in iso[:10].split("-"))
        jy, jm, jd = g2j(y, m, d)
        return f"{jy}/{jm:02d}/{jd:02d}".translate(FA_DIG)
    except Exception:
        return ""


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
        from openpyxl.worksheet.datavalidation import DataValidation
    except ImportError:
        print("openpyxl نصب نیست: pip install openpyxl", file=sys.stderr)
        sys.exit(2)

    with open(a.plan, encoding="utf-8") as f:
        plan = json.load(f)

    font = "Vazirmatn"
    thin = Side(style="thin", color="C9CED6")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill("solid", fgColor="0F766E")
    head_font = Font(name=font, bold=True, color="FFFFFF", size=11)
    body_font = Font(name=font, size=10)
    wrap = Alignment(horizontal="right", vertical="center", wrap_text=True, readingOrder=2)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True, readingOrder=2)

    def sheet(ws, title, headers, widths, rows, color_of=None):
        ws.sheet_view.rightToLeft = True
        ws.append([title])
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(headers))
        c = ws.cell(1, 1)
        c.font = Font(name=font, bold=True, size=14, color="0F766E")
        c.alignment = center
        ws.row_dimensions[1].height = 30
        ws.append(headers)
        for j in range(1, len(headers) + 1):
            h = ws.cell(2, j)
            h.fill, h.font, h.alignment, h.border = head_fill, head_font, center, border
        ws.row_dimensions[2].height = 24
        for r in rows:
            ws.append(r["cells"])
            i = ws.max_row
            fill = PatternFill("solid", fgColor=r.get("color", "FFFFFF"))
            for j in range(1, len(headers) + 1):
                cell = ws.cell(i, j)
                cell.font, cell.border, cell.fill = body_font, border, fill
                cell.alignment = center if j in r.get("center", ()) else wrap
            ws.row_dimensions[i].height = r.get("height", 36)
        for j, w in enumerate(widths, 1):
            ws.column_dimensions[ws.cell(2, j).column_letter].width = w
        ws.freeze_panes = "A3"
        ws.page_setup.orientation = "landscape"
        ws.page_setup.paperSize = ws.PAPERSIZE_A4
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 0
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ws.print_title_rows = "2:2"
        ws.print_options.horizontalCentered = True

    wb = Workbook()
    ws = wb.active
    ws.title = "پست‌ها"
    headers = ["تاریخ", "روز", "ساعت", "نوع", "ستون محتوا", "عنوان / ایده", "قلاب", "دعوت به اقدام", "وضعیت"]
    rows = []
    for p in plan.get("posts", []):
        t = p.get("type", "")
        rows.append({"cells": [shamsi(p.get("date", "")) or p.get("date", ""), p.get("day", ""), p.get("time", ""), TYPE_FA.get(t, t),
                               p.get("pillar", ""), p.get("title", ""), p.get("hook", ""), p.get("cta", ""),
                               p.get("status", "ایده")],
                     "color": TYPE_COLOR.get(t, "FFFFFF"), "center": (1, 2, 3, 4, 9), "height": 48})
    sheet(ws, f"برنامهٔ پست‌ها · {plan.get('page', '')} · هفتهٔ {shamsi(plan.get('week_start', ''))}",
          headers, [12, 9, 8, 10, 16, 34, 38, 26, 14], rows)
    dv = DataValidation(type="list", formula1='"' + ",".join(STATUSES) + '"', allow_blank=True)
    ws.add_data_validation(dv)
    if rows:
        dv.add(f"I3:I{ws.max_row}")

    ws2 = wb.create_sheet("استوری‌ها")
    headers2 = ["تاریخ", "روز", "شماره", "ساعت", "نقش قاب", "ایده / متن", "استیکر", "وضعیت"]
    rows2 = []
    alt = ["FFFFFF", "F6F7F9"]
    for k, day in enumerate(plan.get("stories", [])):
        for n, fr in enumerate(day.get("frames", []), 1):
            rows2.append({"cells": [shamsi(day.get("date", "")) or day.get("date", ""), day.get("day", ""), n, fr.get("time", ""), fr.get("role", ""),
                                    fr.get("idea", ""), STICKER_FA.get(fr.get("sticker", ""), fr.get("sticker", "")),
                                    fr.get("status", "ایده")],
                          "color": alt[k % 2], "center": (1, 2, 3, 4, 7, 8), "height": 32})
    sheet(ws2, f"برنامهٔ استوری · {plan.get('page', '')}", headers2, [12, 9, 7, 8, 18, 50, 12, 14], rows2)
    dv2 = DataValidation(type="list", formula1='"' + ",".join(STATUSES) + '"', allow_blank=True)
    ws2.add_data_validation(dv2)
    if rows2:
        dv2.add(f"H3:H{ws2.max_row}")

    ws3 = wb.create_sheet("راهنمای رنگ")
    ws3.sheet_view.rightToLeft = True
    for i, (t, c) in enumerate(TYPE_COLOR.items(), 1):
        ws3.cell(i, 1, TYPE_FA[t]).fill = PatternFill("solid", fgColor=c)
        ws3.cell(i, 1).font = body_font
        ws3.cell(i, 1).border = border
    ws3.column_dimensions["A"].width = 18

    wb.save(a.out)
    print(f"ساخته شد: {a.out}  ·  {len(rows)} پست، {len(rows2)} قاب استوری")


if __name__ == "__main__":
    main()
