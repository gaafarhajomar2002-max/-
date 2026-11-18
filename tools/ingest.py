#!/usr/bin/env python3
"""تحضير محاضرة مكتوبة (PDF، Word، PowerPoint، صور صفحات) للقراءة صفحة صفحة.

    python3 tools/ingest.py <ملف أو مجلد صور> lectures/<course>/NN-slug/

يكتب في <مجلد المحاضرة>/source/:
  original/            الملف الأصلي كما هو
  pages/page_NN.png    كل صفحة صورة (150 dpi) — Claude يقرأ كل صفحة بعينه (Read)، لأن ذلك أدق من OCR
                       مع العربية والكتابة باليد والصيغ والجداول والرسوم
  text/page_NN.txt     النص المستخرج من الصفحة إن كان الملف فيه طبقة نص (للمقارنة والبحث)
  index.md             عدد الصفحات، وأي صفحات بلا نص (ممسوحة/صور) فلا بد من قراءتها بالصورة

المرجع في lecture.md يكون برقم الصفحة: {ص 3} — يظهر في الوورد كمرجع صغير رمادي.
"""
import shutil
import subprocess
import sys
from pathlib import Path

IMG = {".png", ".jpg", ".jpeg", ".webp", ".heic", ".bmp", ".tif", ".tiff"}
OFFICE = {".docx", ".doc", ".pptx", ".ppt", ".odt", ".odp", ".rtf"}


def to_pdf(src: Path, outdir: Path) -> Path:
    subprocess.run(["soffice", "--headless", "--convert-to", "pdf", "--outdir", str(outdir), str(src)],
                   check=True, capture_output=True, timeout=300)
    return outdir / (src.stem + ".pdf")


def pdf_pages(pdf: Path, pages: Path, text: Path) -> int:
    n = int(next(ln.split()[-1] for ln in subprocess.check_output(["pdfinfo", str(pdf)], text=True).splitlines()
                 if ln.startswith("Pages:")))
    subprocess.run(["pdftoppm", "-r", "150", "-png", str(pdf), str(pages / "page")], check=True)
    # pdftoppm يسمّي page-1.png أو page-01.png حسب العدد: نوحّد إلى page_NN.png
    for f in sorted(pages.glob("page-*.png")):
        k = int(f.stem.split("-")[-1])
        f.rename(pages / f"page_{k:02d}.png")
    for k in range(1, n + 1):
        out = subprocess.run(["pdftotext", "-layout", "-f", str(k), "-l", str(k), str(pdf), "-"],
                             capture_output=True, text=True).stdout
        (text / f"page_{k:02d}.txt").write_text(out, encoding="utf-8")
    return n


def main():
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    src, lec = Path(sys.argv[1]), Path(sys.argv[2])
    base = lec / "source"
    orig, pages, text = base / "original", base / "pages", base / "text"
    for d in (orig, pages, text):
        d.mkdir(parents=True, exist_ok=True)

    if src.is_dir():  # مجلد صور صفحات (مثلاً صور موبايل لملخص ورقي)
        imgs = sorted(p for p in src.iterdir() if p.suffix.lower() in IMG)
        from PIL import Image, ImageOps
        for k, p in enumerate(imgs, 1):
            shutil.copy2(p, orig / p.name)
            im = ImageOps.exif_transpose(Image.open(p)).convert("RGB")
            im.thumbnail((2000, 2000))
            im.save(pages / f"page_{k:02d}.png")
        n = len(imgs)
    else:
        shutil.copy2(src, orig / src.name)
        ext = src.suffix.lower()
        if ext == ".pdf":
            n = pdf_pages(src, pages, text)
        elif ext in OFFICE:
            n = pdf_pages(to_pdf(src, base), pages, text)
        elif ext in IMG:
            from PIL import Image, ImageOps
            im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
            im.thumbnail((2000, 2000))
            im.save(pages / "page_01.png")
            n = 1
        else:
            raise SystemExit(f"نوع غير مدعوم: {ext}")

    no_text = [k for k in range(1, n + 1)
               if not (text / f"page_{k:02d}.txt").exists()
               or len((text / f"page_{k:02d}.txt").read_text(encoding="utf-8").strip()) < 40]
    lines = [f"# المصدر المكتوب: {src.name}", "", f"- عدد الصفحات: **{n}**",
             f"- صفحات بلا طبقة نص (ممسوحة/صور، تُقرأ بالصورة فقط): {', '.join(map(str, no_text)) or 'لا يوجد'}",
             "", "كل الصفحات تُقرأ بالصورة (pages/) حتى لو فيها نص: الصيغ والجداول والرسوم لا تظهر صحيحة في النص المستخرج."]
    (base / "index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
