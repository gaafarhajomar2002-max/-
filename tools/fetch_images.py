#!/usr/bin/env python3
"""البحث عن صور تعليمية حرة (ويكيميديا كومنز / ويكيبيديا) وتنزيلها مع بيانات الترخيص.

أمثلة:
    # بحث عام (يفضل بالإنجليزية لأن كومنز أغنى)
    python3 tools/fetch_images.py search "vitamin D synthesis skin"

    # كل الصور الموجودة في مقالة ويكيبيديا
    python3 tools/fetch_images.py article "Vitamin D" [--lang en|ar]

    # تنزيل صورة (رابط upload.wikimedia.org أو اسم ملف File:...) إلى مجلد المحاضرة
    python3 tools/fetch_images.py get "File:Vitamin_D_metabolism.svg" --dir lectures/03/images --name vitd_metabolism

كل تنزيل يُسجَّل في images/credits.json (المؤلف، الترخيص، المصدر) ليُذكر تحت الصورة في ملف الوورد.
"""
import argparse
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

import requests

UA = "LectureNotesTool/1.0 (educational, non-commercial)"
S = requests.Session()
S.headers["User-Agent"] = UA
WIDTH = 960  # من المقاسات القياسية لويكيميديا (330/500/960/1280)


def _get(url, **kw):
    for i in range(5):
        r = S.get(url, timeout=30, **kw)
        if r.status_code != 429:
            return r
        time.sleep(5 * (i + 1))
    return r


def filename_from(ref: str) -> str:
    """يقبل File:X أو رابط upload.wikimedia.org أو رابط صفحة كومنز، ويعيد اسم الملف."""
    ref = urllib.parse.unquote(ref)
    if ref.startswith("File:") or ref.startswith("ملف:"):
        return ref.split(":", 1)[1].replace(" ", "_")
    m = re.search(r"/commons/(?:thumb/)?[0-9a-f]/[0-9a-f]{2}/([^/?#]+)", ref)
    if m:
        return m.group(1)
    m = re.search(r"File:([^?#]+)", ref)
    if m:
        return m.group(1).replace(" ", "_")
    raise SystemExit(f"لم أفهم مرجع الصورة: {ref}")


def thumb_urls(fname: str, width: int = WIDTH):
    import hashlib
    h = hashlib.md5(fname.encode()).hexdigest()
    q = urllib.parse.quote(fname)
    ext = fname.rsplit(".", 1)[-1].lower()
    suffix = f"{width}px-{q}" + (".png" if ext in ("svg", "tif", "tiff", "pdf") else "")
    path = f"wikipedia/commons/thumb/{h[0]}/{h[:2]}/{q}/{suffix}"
    return [f"https://thumb.wikimedia.org/{path}", f"https://upload.wikimedia.org/{path}"]


def lic(it) -> str:
    l = (it.get("license") or "").lower()
    v = it.get("license_version") or ""
    if l in ("cc0", "pdm"):
        return "Public Domain" if l == "pdm" else "CC0"
    return f"CC {l.upper()} {v}".strip()


def search(query: str, n: int = 12):
    """بحث عبر Openverse (يفهرس كومنز) مع الترخيص."""
    r = _get("https://api.openverse.org/v1/images/",
             params={"q": query, "source": "wikimedia", "page_size": n})
    r.raise_for_status()
    out = []
    for it in r.json().get("results", []):
        out.append({
            "file": "File:" + filename_from(it["url"]) if "wikimedia" in it["url"] else it["url"],
            "title": it.get("title"),
            "creator": it.get("creator"),
            "license": lic(it),
            "size": f"{it.get('width')}x{it.get('height')}",
            "page": it.get("foreign_landing_url"),
        })
    return out


def article(title: str, lang: str = "en"):
    t = urllib.parse.quote(title.replace(" ", "_"))
    r = _get(f"https://{lang}.wikipedia.org/api/rest_v1/page/media-list/{t}")
    r.raise_for_status()
    out = []
    for it in r.json().get("items", []):
        if it.get("type") != "image":
            continue
        cap = (it.get("caption") or {}).get("text", "")
        out.append({"file": it["title"].replace("ملف:", "File:"), "caption": cap[:150]})
    return out


def meta_from_commons(fname: str):
    """الترخيص من API كومنز مباشرة (قد يرفض بـ 429 من خوادم السحابة، فنرجع لـ Openverse)."""
    try:
        r = S.get("https://commons.wikimedia.org/w/api.php", timeout=20, params={
            "action": "query", "format": "json", "titles": f"File:{fname}", "prop": "imageinfo",
            "iiprop": "extmetadata", "iiextmetadatafilter": "Artist|LicenseShortName"})
        if r.ok:
            for page in r.json()["query"]["pages"].values():
                md = page["imageinfo"][0]["extmetadata"]
                artist = re.sub(r"<[^>]+>", "", md.get("Artist", {}).get("value", "")).strip()
                return {"creator": artist[:80], "license": md.get("LicenseShortName", {}).get("value")}
    except Exception:
        pass
    return {}


def meta_from_openverse(fname: str):
    r = _get("https://api.openverse.org/v1/images/",
             params={"q": fname.rsplit(".", 1)[0].replace("_", " "), "source": "wikimedia", "page_size": 20})
    if r.ok:
        for it in r.json().get("results", []):
            if filename_from(it["url"]) == fname:
                return {
                    "creator": it.get("creator"),
                    "license": lic(it),
                }
    return {}


def get(ref: str, dest: Path, name: str | None, width: int = WIDTH):
    fname = filename_from(ref)
    dest.mkdir(parents=True, exist_ok=True)
    data = None
    for url in thumb_urls(fname, width):
        r = _get(url)
        if r.ok and r.headers.get("content-type", "").startswith("image/"):
            data = r.content
            ctype = r.headers["content-type"]
            break
    if data is None:
        raise SystemExit(f"فشل تنزيل {fname} (آخر رد {r.status_code})")
    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/gif": ".gif", "image/webp": ".webp"}.get(ctype, ".img")
    stem = name or re.sub(r"[^\w\-]+", "_", fname.rsplit(".", 1)[0])[:60]
    out = dest / f"{stem}{ext}"
    out.write_bytes(data)

    credits_path = dest / "credits.json"
    credits = json.loads(credits_path.read_text(encoding="utf-8")) if credits_path.exists() else {}
    m = meta_from_commons(fname) or meta_from_openverse(fname)
    credits[out.name] = {
        "source": f"https://commons.wikimedia.org/wiki/File:{urllib.parse.quote(fname)}",
        "creator": m.get("creator") or "Wikimedia Commons",
        "license": m.get("license") or "راجع صفحة الملف",
    }
    credits_path.write_text(json.dumps(credits, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search"); s.add_argument("query"); s.add_argument("-n", type=int, default=12)
    a = sub.add_parser("article"); a.add_argument("title"); a.add_argument("--lang", default="en")
    g = sub.add_parser("get"); g.add_argument("ref"); g.add_argument("--dir", required=True)
    g.add_argument("--name"); g.add_argument("--width", type=int, default=WIDTH)
    args = ap.parse_args()

    if args.cmd == "search":
        for i, x in enumerate(search(args.query, args.n), 1):
            print(f"{i:2d}. {x['file']}\n    {x['title']} | {x['creator']} | {x['license']} | {x['size']}")
    elif args.cmd == "article":
        for i, x in enumerate(article(args.title, args.lang), 1):
            print(f"{i:2d}. {x['file']}  — {x['caption']}")
    else:
        get(args.ref, Path(args.dir), args.name, args.width)


if __name__ == "__main__":
    sys.exit(main())
