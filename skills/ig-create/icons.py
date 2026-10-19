#!/usr/bin/env python3
"""
icons.py - جست‌وجو در ۱۸۹۱ آیکون Lucide (مجوز ISC) که در اسلایدها با "icon": "<نام>" می‌آیند.
جست‌وجو با کلمهٔ انگلیسی:  python icons.py search shop money phone
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    for s in (sys.stdout,):
        try:
            s.reconfigure(encoding="utf-8")
        except Exception:
            pass
    words = [w.lower() for w in sys.argv[2:]] if len(sys.argv) > 2 and sys.argv[1] == "search" else []
    if not words:
        print(__doc__)
        return
    with open(os.path.join(HERE, "assets", "icons", "lucide-tags.json"), encoding="utf-8") as f:
        tags = json.load(f)
    for w in words:
        hits = [n for n, t in tags.items() if w in n or any(w in x for x in t)]
        hits.sort(key=lambda n: (w not in n, len(n)))
        print(f"{w}: {', '.join(hits[:18]) or '—'}")


if __name__ == "__main__":
    main()
