#!/usr/bin/env python3
"""فرز دفعة تسجيلات قبل التفريغ: كشف المكرر، تخمين المادة، والترتيب الزمني.

    python3 tools/triage.py inbox/            # كل ملفات الصوت في المجلد
    python3 tools/triage.py inbox/ --no-asr   # بدون سماع مقاطع (أسرع، بدون تخمين المادة)

يكتب inbox/_triage/report.md و report.json:
  - المدة، الحجم، تاريخ التسجيل من بيانات الملف (إن وجد)
  - مجموعات التكرار: نسخة مطابقة، أو إعادة ترميز، أو جزء مقصوص من تسجيل أطول (ببصمة chromaprint)
  - 3 مقاطع قصيرة مفرّغة (بداية/وسط/نهاية) + تخمين المادة من مفردات courses.json
القرار النهائي (أي ملف لأي مادة وأي محاضرة) يأخذه Claude بقراءة المقاطع، ثم يؤكده مع المستخدم.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

AUDIO_EXT = {".m4a", ".mp3", ".wav", ".ogg", ".oga", ".opus", ".aac", ".amr", ".3gp", ".mp4", ".webm",
             ".flac", ".wma", ".caf", ".mpeg", ".m4b"}
ITEM_SEC = 0.1238  # مدة عنصر واحد من بصمة chromaprint
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).parent))
from transcribe import HALLUCINATIONS  # noqa: E402


# ───────────── معلومات الملف ─────────────
def probe(p: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(p)],
                         capture_output=True, text=True)
    if out.returncode:
        return {"error": out.stderr.strip()[:200]}
    j = json.loads(out.stdout)
    fmt = j.get("format", {})
    tags = {k.lower(): v for k, v in (fmt.get("tags") or {}).items()}
    for s in j.get("streams", []):
        tags.update({k.lower(): v for k, v in (s.get("tags") or {}).items() if k.lower() not in tags})
    created = (tags.get("com.apple.quicktime.creationdate") or tags.get("creation_time") or tags.get("date") or "")
    dur = float(fmt.get("duration") or 0)
    br = int(fmt.get("bit_rate") or 0) or (p.stat().st_size * 8 / dur if dur else 0)  # احتياط: من الحجم
    return {
        "duration": dur,
        "bitrate_kbps": round(br / 1000),
        "created": created,
        "title": tags.get("title", ""),
    }


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def fingerprint(p: Path) -> np.ndarray:
    out = subprocess.run(["fpcalc", "-raw", "-json", "-length", "0", str(p)], capture_output=True, text=True)
    if out.returncode:
        return np.zeros(0, dtype=np.uint32)
    return np.array(json.loads(out.stdout)["fingerprint"], dtype=np.int64).astype(np.uint32)


# ───────────── مقارنة البصمات ─────────────
_POP = np.array([bin(i).count("1") for i in range(256)], dtype=np.uint8)


def popcount32(x: np.ndarray) -> np.ndarray:
    x = x.astype(np.uint32)
    return (_POP[x & 0xFF] + _POP[(x >> 8) & 0xFF] + _POP[(x >> 16) & 0xFF] + _POP[x >> 24]).astype(np.int32)


def overlap(a: np.ndarray, b: np.ndarray, min_abs_off: int = 0, detail: bool = False):
    """أفضل إزاحة بين بصمتين وطول الجزء المتطابق (بالثواني). يعتمد على تطابق القيم ثم التحقق بنسبة الخطأ بالبتات.
    min_abs_off: لتجاهل الإزاحات الصغيرة (عند مقارنة الملف بنفسه لكشف جزء مكرر داخله).
    detail=True يعيد أيضاً (بداية، نهاية) الجزء المتطابق بالثواني داخل a."""
    if len(a) < 50 or len(b) < 50:
        return (0, 0.0, None) if detail else (0, 0.0)
    # مطابقة على أعلى 20 بت (أكثر تحمّلاً لإعادة الترميز)
    ka, kb = a >> 12, b >> 12
    order = np.argsort(kb, kind="stable")
    kb_sorted = kb[order]
    lo = np.searchsorted(kb_sorted, ka, "left")
    hi = np.searchsorted(kb_sorted, ka, "right")
    offs = []
    for i in np.nonzero(hi - lo)[0]:
        if hi[i] - lo[i] > 20:  # قيمة شائعة جداً (صمت) لا تفيد
            continue
        offs.extend((order[lo[i]:hi[i]] - i).tolist())
    offs = [o for o in offs if abs(o) >= min_abs_off]
    if not offs:
        return (0, 0.0, None) if detail else (0, 0.0)
    vals, counts = np.unique(np.array(offs), return_counts=True)
    best_secs, best_off, best_rng = 0.0, 0, None
    for off in vals[np.argsort(counts)[-5:]]:  # أفضل 5 إزاحات مرشحة
        ia = np.arange(max(0, -off), min(len(a), len(b) - off))
        if len(ia) < 50:
            continue
        err = popcount32(a[ia] ^ b[ia + off])
        # تنعيم: نافذة ~5 ثوان، يعتبر متطابقاً إذا متوسط الخطأ < 10 بتات من 32
        k = 40
        sm = np.convolve(err, np.ones(k) / k, mode="same")
        ok = sm < 10
        secs = float(ok.sum() * ITEM_SEC)
        if secs > best_secs:
            best_secs, best_off = secs, int(off)
            # المدى = أطول جزء متصل متطابق (لا أول/آخر نقطة، فقد تكون تطابقاً عشوائياً معزولاً)
            best_rng = None
            if ok.any():
                d = np.diff(np.concatenate(([0], ok.astype(np.int8), [0])))
                st, en = np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]
                k = int(np.argmax(en - st))
                best_rng = (float(ia[st[k]] * ITEM_SEC), float(ia[en[k] - 1] * ITEM_SEC))
    return (best_off, best_secs, best_rng) if detail else (best_off, best_secs)


def gaps(p: Path, noise_db: int = -38, min_sec: int = 45):
    """فترات صمت طويلة (استراحة، انقطاع، نهاية محاضرة) بـ silencedetect."""
    out = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(p), "-af", f"silencedetect=noise={noise_db}dB:d={min_sec}",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", out)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", out)]
    return [(s0, e0) for s0, e0 in zip(starts, ends)]


# ───────────── تخمين المادة ─────────────
def norm_ar(t: str) -> str:
    t = re.sub(r"[ً-ْـ]", "", t)  # تشكيل وتطويل
    t = re.sub("[إأآا]", "ا", t)
    return t.replace("ة", "ه").replace("ى", "ي").lower()


STOP = {"محاضره", "باللهجه", "السوريه", "الدكتور", "المريض", "الحاله"}


def course_terms():
    data = json.loads((ROOT / "courses.json").read_text(encoding="utf-8"))
    terms = {}
    for key, c in data.items():
        if key.startswith("_"):
            continue
        words = set()
        for part in re.split(r"[،,.:()]", c["prompt"]):
            part = norm_ar(part.strip())
            if len(part) < 3 or "باللهجه" in part:
                continue
            words.add(part)                                   # العبارة كاملة
            words.update(w for w in part.split() if len(w) >= 5 and w not in STOP)  # والكلمات الطويلة منها
        terms[key] = (c["name"], words)
    return terms


def guess_course(text: str, terms) -> list:
    t = norm_ar(text)
    scores = []
    for key, (name, words) in terms.items():
        s = sum(t.count(w) for w in words)
        if s:
            scores.append((s, key, name))
    return sorted(scores, reverse=True)[:3]


def snippet_times(dur: float, step: float):
    """أوقات المقاطع: بعد دقيقة من البداية، ثم كل step ثانية، وقبل النهاية بدقيقة ونصف."""
    if dur <= 0:
        return []
    ts = [min(60.0, dur * 0.1)]
    t = step
    while t < dur - 120:
        ts.append(t)
        t += step
    if dur > 240:
        ts.append(dur - 90)
    return ts


def snippets_text(p: Path, dur: float, model, prompt=None, step=600.0, length=35):
    out = []
    for start in snippet_times(dur, step):
        raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-ss", f"{start:.1f}", "-t", str(length), "-i", str(p),
                              "-f", "f32le", "-ac", "1", "-ar", "16000", "-"], capture_output=True).stdout
        audio = np.frombuffer(raw, dtype=np.float32)
        if len(audio) < 16000 * 3:
            out.append({"at": start, "text": ""})
            continue
        segs, _ = model.transcribe(audio, language="ar", beam_size=3, vad_filter=True,
                                   condition_on_previous_text=False, initial_prompt=prompt)
        text = " ".join(s.text.strip() for s in segs)
        for h in HALLUCINATIONS:
            text = text.replace(h, "")
        out.append({"at": start, "text": re.sub(r"\s+", " ", text).strip()})
    return out


def fmt_dur(s: float) -> str:
    s = int(s)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--no-asr", action="store_true")
    ap.add_argument("--step", type=float, default=600, help="ثوانٍ بين المقاطع المسموعة (افتراضي 10 دقائق)")
    a = ap.parse_args()
    folder = Path(a.folder).resolve()
    files = sorted(p for p in folder.rglob("*") if p.suffix.lower() in AUDIO_EXT and "_triage" not in p.parts)
    if not files:
        raise SystemExit(f"لا توجد ملفات صوت في {folder}")
    outdir = folder / "_triage"
    outdir.mkdir(exist_ok=True)
    print(f"{len(files)} ملف", flush=True)

    info = []
    for i, p in enumerate(files, 1):
        d = {"file": str(p.relative_to(folder)), "size_mb": round(p.stat().st_size / 1e6, 1), **probe(p)}
        d["sha256"] = sha256(p)
        print(f"[{i}/{len(files)}] بصمة {d['file']} ({fmt_dur(d.get('duration', 0))})", flush=True)
        d["_fp"] = fingerprint(p)
        # جزء مكرر داخل الملف نفسه (≥ 60 ثانية، بإزاحة ≥ 90 ثانية)
        off, secs, rng = overlap(d["_fp"], d["_fp"], min_abs_off=int(90 / ITEM_SEC), detail=True)
        if secs >= 60 and rng:
            t1, t2 = sorted((rng[0], rng[0] + off * ITEM_SEC))
            d["self_repeat"] = {"seconds": round(secs), "first": fmt_dur(t1), "again_at": fmt_dur(t2)}
        d["gaps"] = [{"from": fmt_dur(s0), "to": fmt_dur(e0), "sec": round(e0 - s0)} for s0, e0 in gaps(p)]
        info.append(d)

    # مجموعات التكرار (union-find)
    parent = list(range(len(info)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    relations = []
    for i in range(len(info)):
        for j in range(i + 1, len(info)):
            A, B = info[i], info[j]
            if A["sha256"] == B["sha256"]:
                kind, secs = "نسخة مطابقة تماماً", min(A["duration"], B["duration"])
            else:
                _, secs = overlap(A["_fp"], B["_fp"])
                shorter = min(A["duration"], B["duration"]) or 1
                if secs >= 0.85 * shorter:
                    kind = "نفس التسجيل (أو أحدهما جزء من الآخر)"
                elif secs >= 60:
                    kind = f"جزء مشترك ≈ {fmt_dur(secs)}"
                else:
                    continue
            relations.append({"a": A["file"], "b": B["file"], "kind": kind, "shared": fmt_dur(secs)})
            parent[find(i)] = find(j)
    groups = {}
    for i in range(len(info)):
        groups.setdefault(find(i), []).append(i)
    gid = 0
    for members in groups.values():
        if len(members) > 1:
            gid += 1
            # الأطول (لأن الأقصر قد يكون جزءاً منه)، ثم الأعلى جودة (الأصل لا النسخة المضغوطة)
            best = max(members, key=lambda k: (round(info[k]["duration"] / 15), info[k].get("bitrate_kbps", 0)))
            for k in members:
                info[k]["dup_group"] = gid
                info[k]["keep"] = (k == best)

    # مقاطع + تخمين المادة
    if not a.no_asr:
        sys.path.insert(0, str(Path(__file__).parent))
        from faster_whisper import WhisperModel
        from transcribe import ensure_model
        model = WhisperModel(ensure_model("turbo"), device="cpu", compute_type="int8")
        terms = course_terms()
        for i, d in enumerate(info, 1):
            if d.get("dup_group") and not d.get("keep"):
                continue  # لا داعي لسماع النسخ المكررة
            print(f"[{i}/{len(info)}] سماع مقاطع من {d['file']}", flush=True)
            d["snippets"] = snippets_text(files[i - 1], d.get("duration", 0), model, step=a.step)
            d["course_guess"] = guess_course(" ".join(s["text"] for s in d["snippets"]), terms)
            prev = None
            for sn in d["snippets"]:
                g = guess_course(sn["text"], terms)
                sn["guess"] = g[0][2] if g and g[0][0] >= 2 else ""
                if sn["guess"] and prev and sn["guess"] != prev:
                    d.setdefault("topic_changes", []).append(f"{fmt_dur(sn['at'])}: {prev} ← {sn['guess']}")
                if sn["guess"]:
                    prev = sn["guess"]

    for d in info:
        d.pop("_fp", None)
    (outdir / "report.json").write_text(json.dumps({"files": info, "duplicates": relations}, ensure_ascii=False,
                                                   indent=2), encoding="utf-8")

    # تقرير مقروء
    def sort_key(d):
        return (d.get("created") or "9999", d["file"])
    lines = [f"# تقرير الفرز ({datetime.now():%Y-%m-%d %H:%M})", "", f"عدد الملفات: {len(info)}", ""]
    lines += ["| # | الملف | المدة | تاريخ التسجيل | الحجم MB | تكرار | تخمين المادة |", "|---|---|---|---|---|---|---|"]
    for n, d in enumerate(sorted(info, key=sort_key), 1):
        dup = f"مجموعة {d['dup_group']}{' ✔ الأفضل' if d.get('keep') else ' ✗ مكرر'}" if d.get("dup_group") else "—"
        cg = "، ".join(f"{name} ({s})" for s, _, name in d.get("course_guess", [])) or "؟"
        lines.append(f"| {n} | {d['file']} | {fmt_dur(d.get('duration', 0))} | {d.get('created') or '—'} | "
                     f"{d['size_mb']} | {dup} | {cg} |")
    if relations:
        lines += ["", "## التكرارات", ""]
        lines += [f"- `{r['a']}` ↔ `{r['b']}`: {r['kind']} (مشترك {r['shared']})" for r in relations]
    inner = [d for d in info if d.get("self_repeat") or d.get("topic_changes") or d.get("gaps")]
    if inner:
        lines += ["", "## داخل الملفات: تكرار، تغيّر مادة، استراحات", ""]
        for d in inner:
            lines.append(f"- **{d['file']}**")
            if d.get("self_repeat"):
                r = d["self_repeat"]
                lines.append(f"  - جزء مكرر داخل الملف ≈ {r['seconds']} ث: من {r['first']} ويتكرر عند {r['again_at']}")
            for c in d.get("topic_changes", []):
                lines.append(f"  - احتمال تغيّر المادة عند {c}")
            for g in d.get("gaps", []):
                lines.append(f"  - صمت/انقطاع من {g['from']} إلى {g['to']} ({g['sec']} ث)")
    lines += ["", "## خط زمني لكل ملف (مقطع كل بضع دقائق)", ""]
    for d in sorted(info, key=sort_key):
        if not d.get("snippets"):
            continue
        lines.append(f"### {d['file']}  ({fmt_dur(d.get('duration', 0))})")
        for s in d["snippets"]:
            tag = f" `{s['guess']}`" if s.get("guess") else ""
            lines.append(f"- **[{fmt_dur(s['at'])}]**{tag} {s['text'][:300] or '(لا كلام / صمت)'}")
        lines.append("")
    (outdir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"\nالتقرير: {outdir / 'report.md'}")


if __name__ == "__main__":
    sys.exit(main())
