"""
fa_text.py - ابزارهای مشترک متن فارسی برای همهٔ اسکریپت‌های این بسته.

این فایل در چند پوشه کپی شده تا هر اسکیل به‌تنهایی هم کار کند.
نسخهٔ اصلی در skills/ig-human/fa_text.py است؛ اگر عوضش کردی، کپی‌ها را هم به‌روز کن.

نکته‌های فارسی که اینجا رعایت می‌شود:
  - نیم‌فاصله (U+200C) جزء کلمه است، نه «کاراکتر نامرئی». «می‌خوام» یک کلمه است.
  - ي و ك عربی به ی و ک فارسی تبدیل می‌شوند.
  - رقم‌های فارسی (۰-۹)، عربی (٠-٩) و لاتین هر سه «عدد» حساب می‌شوند.
  - جمله‌ها با . ! ? ؟ … و خط جدید جدا می‌شوند.
"""

import re
import sys

ZWNJ = "‌"

FA_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
AR_DIGITS = "٠١٢٣٤٥٦٧٨٩"
EN_DIGITS = "0123456789"

_TO_EN = str.maketrans(FA_DIGITS + AR_DIGITS, EN_DIGITS * 2)
_TO_FA = str.maketrans(EN_DIGITS + AR_DIGITS, FA_DIGITS * 2)
_ARABIC_LETTERS = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ۀ": "هٔ", "ة": "ه"})

PERSIAN_LETTER = r"؀-ۿﭐ-﷿ﹰ-﻿"
# a word: letters/digits (any script) joined by ZWNJ, plus $ % ' -
WORD_RE = re.compile(r"[\w" + ZWNJ + r"$%'’\-]+", re.UNICODE)
SENT_RE = re.compile(r"[^.!?؟…\n]+[.!?؟…]*")
NUMBER_RE = re.compile(r"[$]?\s?[\d۰-۹٠-٩][\d۰-۹٠-٩,٬.]*\s?(?:%|٪)?")
LATIN_NAME_RE = re.compile(r"\b[A-Z][A-Za-z0-9]{1,}\b")
HASHTAG_RE = re.compile(r"(?:^|\s)#[\w" + ZWNJ + r"_]+")
EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF☀-➿\U0001F000-\U0001F2FF]")
PERSIAN_RE = re.compile(r"[" + PERSIAN_LETTER + r"]")


def setup_stdout():
    """ویندوز معمولاً خروجی را با cp1252 می‌نویسد و فارسی را خراب می‌کند."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


def to_en_digits(text):
    return text.translate(_TO_EN)


def to_fa_digits(text):
    return text.translate(_TO_FA)


def normalize(text):
    """یکدست کردن حروف عربی؛ نیم‌فاصله‌ها دست نمی‌خورند."""
    return text.translate(_ARABIC_LETTERS)


def is_persian(text):
    letters = re.findall(r"[^\W\d_]", text)
    if not letters:
        return False
    fa = len(PERSIAN_RE.findall(text))
    return fa / len(letters) >= 0.4


def words(text):
    """کلمه‌ها، با نیم‌فاصله به‌عنوان بخشی از کلمه. «۱۸٬۰۰۰» یک کلمه است."""
    t = re.sub(r"(?<=[\d۰-۹٠-٩])[,٬](?=[\d۰-۹٠-٩])", "", normalize(text))
    return [w.strip("-'’") for w in WORD_RE.findall(t) if w.strip("-'’")]


def low(token):
    return normalize(token).lower().strip("'’")


def sentences(text):
    return [s.strip() for s in SENT_RE.findall(normalize(text)) if s.strip()]


def numbers(text):
    return [n.strip() for n in NUMBER_RE.findall(text) if re.search(r"[\d۰-۹٠-٩]", n)]


def latin_names(text):
    """در فارسی حرف بزرگ نداریم؛ فقط اسم‌های لاتین (ChatGPT، Canva) را می‌شود تشخیص داد."""
    return LATIN_NAME_RE.findall(text)


def visible_len(text):
    """طول متن بدون نیم‌فاصله، همان‌طور که چشم می‌بیند."""
    return len(text.replace(ZWNJ, ""))


def bar(score, width=24):
    filled = round(max(0, min(100, score)) / 100 * width)
    return "#" * filled + "." * (width - filled)


def clamp(n):
    return max(0.0, min(100.0, n))
