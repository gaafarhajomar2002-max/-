#!/usr/bin/env python3
"""تنزيل مجلد Google Drive عام ("أي شخص لديه الرابط") إلى مجلد محلي.

    python3 tools/drive_fetch.py <رابط المجلد> inbox/drive

gdown يجلب قائمة الملفات فقط؛ التنزيل نفسه من drive.usercontent.google.com مباشرة، لأن الطريق العادي
يحوّل إلى doc-XX-docs.googleusercontent.com (اسم متغير لا تسمح به بيئة الشبكة).
الأسماء تُنظَّف من رموز الاتجاه المخفية (التي يضيفها واتساب للأسماء العربية). الملفات الموجودة بنفس الحجم تُتخطّى.
"""
import re
import sys
from pathlib import Path

import gdown
import requests

URL = "https://drive.usercontent.google.com/download"
BIDI = re.compile("[‎‏‪-‮⁦-⁩؜﻿]")


def clean(name: str) -> str:
    name = BIDI.sub("", name).strip()
    return re.sub(r'[\\/:*?"<>|]', "_", name)


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    folder_url, out = sys.argv[1], Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    files = gdown.download_folder(folder_url, output=str(out), skip_download=True, quiet=True)
    s = requests.Session()
    for k, f in enumerate(files, 1):
        dest = out / clean(Path(f.path).name)
        r = s.get(URL, params={"id": f.id, "export": "download", "confirm": "t"}, stream=True, timeout=120)
        r.raise_for_status()
        size = int(r.headers.get("content-length") or 0)
        if dest.exists() and size and dest.stat().st_size == size:
            print(f"[{k}/{len(files)}] موجود: {dest.name}")
            r.close()
            continue
        if "text/html" in r.headers.get("content-type", ""):
            raise SystemExit(f"Drive أعاد صفحة بدل الملف لـ {dest.name} (هل المجلد مشارك لأي شخص لديه الرابط؟)")
        tmp = dest.with_suffix(dest.suffix + ".part")
        with tmp.open("wb") as fh:
            for chunk in r.iter_content(1 << 20):
                fh.write(chunk)
        tmp.rename(dest)
        print(f"[{k}/{len(files)}] {dest.name}  {dest.stat().st_size / 1e6:.1f} MB", flush=True)


if __name__ == "__main__":
    main()
