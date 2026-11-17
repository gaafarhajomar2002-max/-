#!/usr/bin/env python3
"""تفريغ محاضرة صوتية عربية (لهجة سورية غالباً) إلى نص.

الاستخدام:
    python3 tools/transcribe.py lectures/<name>/audio.m4a [part2.m4a ...] [--model large-v3|turbo] [--out DIR]

الخرج (في نفس مجلد الصوت افتراضياً):
    transcript.txt        نص مع طوابع زمنية [hh:mm:ss] لكل مقطع
    transcript_plain.txt  نص متصل بدون طوابع
    transcript.srt        ترجمة بصيغة SRT (للمراجعة مع الصوت)
"""
import argparse
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
INITIAL_PROMPT = (
    "محاضرة جامعية في كلية التغذية والصحة باللهجة السورية. "
    "يشرح الدكتور عن البروتينات والكربوهيدرات والدهون والفيتامينات والمعادن، "
    "الاستقلاب، السعرات الحرارية، الجهاز الهضمي، الكبد، الأنسولين، الغلوكوز. "
    "يعني هلق منشوف، هاد الشي مهم، انتبهوا عليه، بيجي بالامتحان."
)


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
    ap.add_argument("--out", default=None)
    ap.add_argument("--multilingual", action="store_true",
                    help="كشف اللغة لكل مقطع (مفيد إذا قرأ الدكتور جملاً إنجليزية كاملة). "
                         "الافتراضي: عربي فقط، لأنه أأمن مع اللهجة السورية")
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
    print(f"مدة الصوت: {fmt_ts(dur)}", flush=True)

    from faster_whisper import WhisperModel
    model = WhisperModel(ensure_model(args.model), device="cpu",
                         compute_type="int8", cpu_threads=args.threads)

    # نقرأ الصوت بـ ffmpeg مباشرة كمصفوفة (بدون PyAV)
    import numpy as np
    raw = subprocess.check_output(
        ["ffmpeg", "-loglevel", "error", "-i", str(wav), "-f", "f32le", "-ac", "1", "-ar", "16000", "-"]
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
        initial_prompt=INITIAL_PROMPT,
        condition_on_previous_text=False,  # يقلل التكرار/الهلوسة بالتسجيلات الطويلة
        temperature=[0.0, 0.2, 0.4],
        no_speech_threshold=0.6,
    )

    lines, plain, srt = [], [], []
    for i, seg in enumerate(segments, 1):
        text = seg.text.strip()
        if not text or is_hallucination(text):
            continue
        lines.append(f"[{fmt_ts(seg.start)}] {text}")
        plain.append(text)
        srt.append(f"{i}\n{fmt_ts(seg.start, True)} --> {fmt_ts(seg.end, True)}\n{text}\n")
        el = time.time() - t0
        print(f"\r{fmt_ts(seg.end)} / {fmt_ts(dur)}  ({seg.end / dur:5.1%})  مضى {fmt_ts(el)}",
              end="", flush=True)

    (out / "transcript.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "transcript_plain.txt").write_text(" ".join(plain) + "\n", encoding="utf-8")
    (out / "transcript.srt").write_text("\n".join(srt), encoding="utf-8")
    wav.unlink(missing_ok=True)
    el = time.time() - t0
    print(f"\nانتهى خلال {fmt_ts(el)} (سرعة {dur / el:.2f}x من الزمن الحقيقي) → {out}")


if __name__ == "__main__":
    sys.exit(main())
