#!/usr/bin/env python3
"""توليد غلاف المحاضرة كصورة A4 عالية الدقة من بيانات رأس ملف lecture.md.

    python3 tools/make_cover.py lectures/03-vitamin-d/lecture.md
→ lectures/03-vitamin-d/cover.jpg
"""
import base64
import html
import mimetypes
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lecture_md import read_front_matter  # noqa: E402

ROOT = Path(__file__).resolve().parent

THEMES = {
    # primary, dark, light, accent
    "nutrition": ("#2e7d5b", "#14402f", "#e7f4ec", "#f2a541"),
    "anatomy": ("#b03a48", "#5a1a23", "#fbeaec", "#f2c14e"),
    "biochem": ("#2f5d9e", "#142c4f", "#e8eff9", "#f28f3b"),
    "food": ("#c4622d", "#5e2a10", "#fcefe6", "#5aa469"),
    "health": ("#1f7a8c", "#0e3b44", "#e3f3f6", "#e9c46a"),
}


def data_uri(p: Path) -> str:
    mt = mimetypes.guess_type(p.name)[0] or "image/png"
    return f"data:{mt};base64," + base64.b64encode(p.read_bytes()).decode()


def build_html(meta: dict, base: Path) -> str:
    pr, dk, lt, ac = THEMES.get(meta.get("theme", "nutrition"), THEMES["nutrition"])
    e = lambda k, d="": html.escape(str(meta.get(k, d)))  # noqa: E731

    img_html = ""
    if meta.get("cover_image"):
        ip = (base / meta["cover_image"]).resolve()
        if ip.exists():
            img_html = f'<div class="photo"><img src="{data_uri(ip)}"></div>'
    if not img_html:  # زخرفة بديلة: رموز غذائية
        img_html = """<div class="photo deco"><svg viewBox="0 0 200 200">
        <circle cx="100" cy="100" r="92" fill="none" stroke="currentColor" stroke-width="3" stroke-dasharray="6 8"/>
        <path d="M100 40 C140 60 150 120 100 160 C50 120 60 60 100 40Z" fill="currentColor" opacity=".85"/>
        <path d="M100 55 L100 150" stroke="#fff" stroke-width="4"/>
        <path d="M100 85 L125 70 M100 105 L75 90 M100 125 L128 108" stroke="#fff" stroke-width="3"/>
        </svg></div>"""

    chips = []
    for key, label in (("course", "المقرر"), ("doctor", "المحاضِر"), ("year", "السنة"), ("date", "التاريخ")):
        if meta.get(key):
            chips.append(f'<div class="chip"><span>{label}</span><b>{e(key)}</b></div>')

    return f"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:794px;height:1123px;overflow:hidden}}
body{{font-family:'Noto Naskh Arabic','Noto Sans Arabic',sans-serif;background:{lt};color:{dk};position:relative}}
.band{{position:absolute;inset:0 0 auto 0;height:430px;background:linear-gradient(160deg,{pr} 0%,{dk} 100%);
  clip-path:polygon(0 0,100% 0,100% 82%,0 100%)}}
.pattern{{position:absolute;inset:0 0 auto 0;height:430px;opacity:.10;
  background-image:radial-gradient(circle at 20px 20px,#fff 2px,transparent 2.5px);background-size:34px 34px;
  clip-path:polygon(0 0,100% 0,100% 82%,0 100%)}}
.top{{position:relative;padding:46px 56px 0;color:#fff;display:flex;justify-content:space-between;align-items:flex-start}}
.uni{{font-family:'Noto Kufi Arabic';font-size:17px;line-height:1.7;opacity:.95}}
.uni small{{display:block;font-size:13px;opacity:.85;font-weight:400}}
.num{{background:{ac};color:{dk};border-radius:18px;padding:10px 20px;text-align:center;font-family:'Noto Kufi Arabic';
  box-shadow:0 6px 18px rgba(0,0,0,.25)}}
.num span{{display:block;font-size:13px}} .num b{{font-size:46px;line-height:1}}
.title{{position:relative;padding:34px 56px 0;color:#fff}}
.title h1{{font-family:'Noto Kufi Arabic';font-size:44px;line-height:1.35;font-weight:800;text-shadow:0 3px 10px rgba(0,0,0,.25)}}
.title h2{{font-family:'Noto Kufi Arabic';font-weight:500;font-size:21px;margin-top:10px;opacity:.92}}
.photo{{position:absolute;top:350px;left:50%;transform:translateX(-50%);width:330px;height:330px;border-radius:50%;
  border:10px solid #fff;overflow:hidden;box-shadow:0 18px 40px rgba(0,0,0,.22);background:#fff}}
.photo img{{width:100%;height:100%;object-fit:cover}}
.photo.deco{{display:flex;align-items:center;justify-content:center;color:{pr};background:{lt}}}
.photo.deco svg{{width:72%;height:72%}}
.chips{{position:absolute;top:720px;left:56px;right:56px;display:grid;grid-template-columns:1fr 1fr;gap:14px}}
.chip{{background:#fff;border-radius:14px;padding:12px 18px;border-right:6px solid {pr};box-shadow:0 4px 14px rgba(0,0,0,.06)}}
.chip span{{display:block;font-size:12.5px;color:{pr};font-family:'Noto Kufi Arabic'}}
.chip b{{font-size:18px;font-weight:700}}
.foot{{position:absolute;bottom:0;left:0;right:0;height:120px;background:{dk};color:#fff;
  clip-path:polygon(0 30%,100% 0,100% 100%,0 100%);display:flex;align-items:flex-end;justify-content:space-between;padding:0 56px 26px}}
.foot .by{{font-family:'Noto Kufi Arabic';font-size:14px;opacity:.9}}
.foot .tag{{font-size:13px;opacity:.75}}
</style></head><body>
<div class="band"></div><div class="pattern"></div>
<div class="top">
  <div class="uni">{e('university')}<small>{e('faculty')}</small></div>
  <div class="num"><span>المحاضرة</span><b>{e('lecture')}</b></div>
</div>
<div class="title"><h1>{e('title')}</h1><h2>{e('subtitle')}</h2></div>
{img_html}
<div class="chips">{''.join(chips)}</div>
<div class="foot"><div class="by">{e('prepared_by', 'ملخّص منسَّق للمحاضرة')}</div><div class="tag">{e('semester')}</div></div>
</body></html>"""


def make_cover(md_path: Path) -> Path:
    meta, _ = read_front_matter(md_path.read_text(encoding="utf-8"))
    base = md_path.parent
    tmp = base / "_cover.html"
    tmp.write_text(build_html(meta, base), encoding="utf-8")
    out = base / "cover.jpg"
    subprocess.run(["node", str(ROOT / "render_html.js"), str(tmp), str(out)], check=True)
    tmp.unlink()
    return out


if __name__ == "__main__":
    print(make_cover(Path(sys.argv[1])))
