#!/usr/bin/env python3
"""تفريغ محاضرة صوتية عربية (لهجة سورية غالباً) إلى نص.

الاستخدام:
    python3 tools/transcribe.py lectures/<course>/<NN-topic>/audio.m4a [part2.m4a ...]
            [--course food-chem] [--model large-v3|turbo] [--out DIR]

المادة (--course) تُكتشف تلقائياً من المسار lectures/<course>/... وتعطي النموذج مفردات المادة
(من courses.json)، وهذا يحسّن كتابة المصطلحات العلمية كثيراً.

الخرج (في نفس مجلد الصوت افتراضياً):
    transcript.txt        نص مع طوابع زمنية [hh:mm:ss] لكل مقطع (⚠ = مقطع ثقة النموذج فيه منخفضة)
    transcript_uncertain.txt  قائمة المقاطع غير الأكيدة للمراجعة
    transcript_plain.txt  نص متصل بدون طوابع
    transcript.srt        ترجمة بصيغة SRT (للمراجعة مع الصوت)
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

MODELS = {
    "large-v3": ("Systran/faster-whisper-large-v3", "/home/user/models/large-v3"),
    "turbo": ("deepdml/faster-whisper-large-v3-turbo-ct2", "/home/user/models/large-v3-turbo"),
}

# يساعد النموذج على توقع المفردات: لهجة شامية + مصطلحات تغذية/طب.
DEFAULT_PROMPT = (
    "محاضرة جامعية في كلية التغذية العلاجية باللهجة السورية. "
    "البروتينات والكربوهيدرات والدهون والفيتامينات والمعادن، الاستقلاب، السعرات الحرارية."
)
DIALECT_TAIL = " يعني هلق منشوف، هاد الشي مهم، انتبهوا عليه، بيجي بالامتحان، عرّف وعلّل."
COURSES = Path(__file__).resolve().parent.parent / "courses.json"


def course_prompt(course: str | None, srcs: list[Path]) -> tuple[str | None, str]:
    data = json.loads(COURSES.read_text(encoding="utf-8")) if COURSES.exists() else {}
    if not course:  # اكتشاف من المسار: lectures/<course>/...
        for part in srcs[0].parts:
            if part in data and not part.startswith("_"):
                course = part
                break
    if course and course in data:
        return course, data[course]["prompt"] + DIALECT_TAIL
    return None, DEFAULT_PROMPT + DIALECT_TAIL


def uncertain(seg) -> bool:
    return seg.avg_logprob < -0.8 or seg.compression_ratio > 2.4 or seg.no_speech_prob > 0.5


# جمل يختلقها Whisper عادةً في الصمت/الضجيج — تُحذف إذا كانت هي كل المقطع.
HALLUCINATIONS = [
    "اشتركوا في القناة", "اشترك في القناة", "ترجمة نانسي قنقر", "شكرا للمشاهدة",
    "شكراً للمشاهدة", "شكرا لكم على المشاهدة", "سبحان الله", "موسيقى",
    "Thanks for watching", "Subscribe", "نانسي قنقر",
]


def is_hallucination(text: str) -> bool:
    t = text.strip(" .!،,؟?")
    return len(t) < 40 and any(h.lower() in t.lower() for h in HALLUCINATIONS)


def fmt_ts(sec: float, srt: bool = False) -> str:
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    if srt:
        ms = int((sec - int(sec)) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    return f"{h:02d}:{m:02d}:{s:02d}"


def ensure_model(name: str) -> str:
    repo, local = MODELS[name]
    if not (Path(local) / "model.bin").exists():
        from huggingface_hub import snapshot_download
        print(f"تنزيل النموذج {repo} ...", flush=True)
        snapshot_download(repo, local_dir=local)
    return local


def to_wav(srcs: list[Path], dst: Path) -> None:
    """mono 16kHz + توحيد مستوى الصوت (مفيد لتسجيلات القاعة). عدة ملفات تُدمج بالترتيب."""
    inputs = []
    for s in srcs:
        inputs += ["-i", str(s)]
    n = len(srcs)
    chain = "".join(f"[{i}:a]" for i in range(n)) + f"concat=n={n}:v=0:a=1,highpass=f=80,dynaudnorm[a]"
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", *inputs, "-filter_complex", chain,
         "-map", "[a]", "-ac", "1", "-ar", "16000", str(dst)],
        check=True,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("audio", nargs="+", help="ملف صوت واحد أو عدة أجزاء بالترتيب")
    ap.add_argument("--model", default="large-v3", choices=MODELS)
    ap.add_argument("--course", default=None, help="مفتاح المادة من courses.json (يُكتشف من المسار إن لم يُعطَ)")
    ap.add_argument("--out", default=None)
    ap.add_argument("--multilingual", action="store_true",
                    help="كشف اللغة لكل مقطع (مفيد إذا قرأ الدكتور جملاً إنجليزية كاملة). "
                         "الافتراضي: عربي فقط، لأنه أأمن مع اللهجة السورية")
    ap.add_argument("--start", default=None, help="بداية الجزء المطلوب (hh:mm:ss) — مثلاً لتسجيل فيه محاضرتان")
    ap.add_argument("--end", default=None, help="نهاية الجزء المطلوب (hh:mm:ss)")
    ap.add_argument("--threads", type=int, default=os.cpu_count() or 4)
    args = ap.parse_args()

    srcs = [Path(a).resolve() for a in args.audio]
    out = Path(args.out).resolve() if args.out else srcs[0].parent
    out.mkdir(parents=True, exist_ok=True)

    wav = out / "_audio16k.wav"
    to_wav(srcs, wav)
    dur = float(subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(wav)]
    ).strip())
    course, prompt = course_prompt(args.course, srcs)
    print(f"مدة الصوت: {fmt_ts(dur)}  |  المادة: {course or 'عامة'}  |  النموذج: {args.model}", flush=True)

    from faster_whisper import WhisperModel
    model = WhisperModel(ensure_model(args.model), device="cpu",
                         compute_type="int8", cpu_threads=args.threads)

    # نقرأ الصوت بـ ffmpeg مباشرة كمصفوفة (بدون PyAV)
    import numpy as np
    def secs(t):
        parts = [float(x) for x in str(t).split(":")]
        return sum(v * 60 ** k for k, v in enumerate(reversed(parts)))
    t_off = secs(args.start) if args.start else 0.0
    rng = (["-ss", str(t_off)] if args.start else []) + (["-to", str(secs(args.end))] if args.end else [])
    raw = subprocess.check_output(
        ["ffmpeg", "-loglevel", "error", "-i", str(wav), *rng, "-f", "f32le", "-ac", "1", "-ar", "16000", "-"]
    )
    audio = np.frombuffer(raw, dtype=np.float32)

    t0 = time.time()
    segments, _info = model.transcribe(
        audio,
        language=None if args.multilingual else "ar",
        multilingual=args.multilingual,
        task="transcribe",
        beam_size=5,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 700},
        initial_prompt=prompt,
        condition_on_previous_text=False,  # يقلل التكرار/الهلوسة بالتسجيلات الطويلة
        temperature=[0.0, 0.2, 0.4],
        no_speech_threshold=0.6,
    )

    lines, plain, srt, unsure = [], [], [], []
    # يُكتب أولاً بأول في ملف مؤقت (خارج git، يمكن قراءته أثناء التفريغ)، ويُعاد تسميته عند الانتهاء
    partial = out / "transcript.partial.txt"
    live = partial.open("w", encoding="utf-8")
    for i, seg in enumerate(segments, 1):
        text = seg.text.strip()
        if not text or is_hallucination(text):
            continue
        seg_start, seg_end = seg.start + t_off, seg.end + t_off  # أوقات حسب التسجيل الأصلي
        flag = "⚠ " if uncertain(seg) else ""
        if flag:
            unsure.append(f"[{fmt_ts(seg_start)} – {fmt_ts(seg_end)}] {text}")
        lines.append(f"[{fmt_ts(seg_start)}] {flag}{text}")
        live.write(lines[-1] + "\n"); live.flush()
        plain.append(text)
        srt.append(f"{i}\n{fmt_ts(seg_start, True)} --> {fmt_ts(seg_end, True)}\n{text}\n")
        el = time.time() - t0
        print(f"\r{fmt_ts(seg_end)} / {fmt_ts(dur)}  ({seg_end / dur:5.1%})  مضى {fmt_ts(el)}",
              end="", flush=True)

    live.close()
    partial.replace(out / "transcript.txt")
    (out / "transcript_uncertain.txt").write_text("\n".join(unsure) + "\n", encoding="utf-8")
    (out / "transcript_plain.txt").write_text(" ".join(plain) + "\n", encoding="utf-8")
    (out / "transcript.srt").write_text("\n".join(srt), encoding="utf-8")
    wav.unlink(missing_ok=True)
    el = time.time() - t0
    print(f"\nانتهى خلال {fmt_ts(el)} (سرعة {dur / el:.2f}x من الزمن الحقيقي) → {out}")
    print(f"مقاطع غير أكيدة: {len(unsure)} من {len(lines)} (راجع transcript_uncertain.txt)")


if __name__ == "__main__":
    sys.exit(main())
