#!/usr/bin/env python3
"""مقارنة التفريغات لكشف نفس المحاضرة مسجّلة مرتين (من جهازين مثلاً) — حالة قد لا تكشفها البصمة الصوتية.

    python3 tools/compare_transcripts.py lectures/            # كل transcript.txt تحت المجلد
    python3 tools/compare_transcripts.py a/transcript.txt b/transcript.txt

يحسب نسبة "الاحتواء": كم من عبارات (4 كلمات متتالية) التفريغ الأقصر موجودة في الآخر،
ويحدد المدى الزمني المشترك. نسبة > 20% تعني غالباً نفس الكلام.
"""
import re
import sys
from itertools import combinations
from pathlib import Path

TS = re.compile(r"^\[(\d\d:\d\d:\d\d)\]\s*(?:⚠\s*)?(.*)$")


def norm(t: str) -> list[str]:
    t = re.sub(r"[\u064B-\u0652\u0640]", "", t)
    t = re.sub("[إأآا]", "ا", t).replace("ة", "ه").replace("ى", "ي").lower()
    return re.findall(r"[\w]+", t)


def load(path: Path):
    lines = []
    for ln in path.read_text(encoding="utf-8").splitlines():
        m = TS.match(ln)
        if m:
            lines.append((m.group(1), norm(m.group(2))))
    return lines


def shingles(words, n=4):
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def compare(pa: Path, pb: Path):
    A, B = load(pa), load(pb)
    sa = shingles([w for _, ws in A for w in ws])
    sb = shingles([w for _, ws in B for w in ws])
    if not sa or not sb:
        return None
    common = sa & sb
    contain = len(common) / min(len(sa), len(sb))
    # المدى الزمني في A الذي يحوي عبارات مشتركة
    hits = [ts for ts, ws in A if shingles(ws) & common]
    return contain, (hits[0], hits[-1]) if hits else None


def main():
    args = [Path(x) for x in sys.argv[1:]]
    if len(args) == 1 and args[0].is_dir():
        files = sorted(args[0].rglob("transcript.txt"))
    else:
        files = args
    if len(files) < 2:
        raise SystemExit("يلزم تفريغان على الأقل")
    found = False
    for a, b in combinations(files, 2):
        r = compare(a, b)
        if r and r[0] >= 0.10:
            found = True
            rng = f" (في {a.parent.name}: {r[1][0]} → {r[1][1]})" if r[1] else ""
            verdict = "نفس المحاضرة غالباً" if r[0] >= 0.20 else "تشابه جزئي، راجع يدوياً"
            print(f"{r[0]:.0%}  {a.parent.name}  ↔  {b.parent.name}: {verdict}{rng}")
    if not found:
        print("لا يوجد تشابه ملحوظ بين التفريغات.")


if __name__ == "__main__":
    main()
