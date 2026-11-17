"""قارئ صيغة lecture.md (Markdown مبسّط + صناديق خاصة).

الصيغة:
    ---
    key: value          (رأس الملف: title, subtitle, course, lecture, doctor, date, ...)
    ---
    # عنوان فصل          ## عنوان فرعي          ### عنوان أصغر
    فقرة عادية فيها **غامق** و ==تظليل== و *مائل*
    - نقطة              (مسافتان قبل - للمستوى الثاني)
    1. نقطة مرقمة
    > [!doctor] نص التنبيه           صندوق: الدكتور شدّد
    > [!exam] نص السؤال               صندوق: سؤال متوقع (الأسطر التالية = الجواب/الفكرة)
    > الجواب ...
    > [!note] / [!remember] / [!tip] / [!mistake] / [!style] / [!summary]
    ![تعليق الصورة](images/x.png)
    | جدول | ... |
    <<<pagebreak>>>
"""
import re

CALLOUT_RE = re.compile(r"^>\s*\[!(\w+)\]\s*(.*)$")


def read_front_matter(text: str):
    meta = {}
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line and not line.strip().startswith("#"):
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip().strip('"').strip("'")
        text = text[m.end():]
    return meta, text


def parse(text: str):
    meta, body = read_front_matter(text)
    lines = body.splitlines()
    blocks, i, para = [], 0, []

    def flush():
        if para:
            blocks.append({"t": "p", "text": " ".join(s.strip() for s in para)})
            para.clear()

    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if not s:
            flush(); i += 1; continue
        if s == "<<<pagebreak>>>":
            flush(); blocks.append({"t": "pagebreak"}); i += 1; continue
        m = re.match(r"^(#{1,3})\s+(.*)$", s)
        if m:
            flush(); blocks.append({"t": f"h{len(m.group(1))}", "text": m.group(2).strip()}); i += 1; continue
        m = CALLOUT_RE.match(s)
        if m:
            flush()
            kind, first = m.group(1).lower(), m.group(2).strip()
            body_lines = []
            i += 1
            while i < len(lines) and lines[i].strip().startswith(">") and not CALLOUT_RE.match(lines[i].strip()):
                body_lines.append(lines[i].strip()[1:].strip())
                i += 1
            blocks.append({"t": "callout", "kind": kind, "head": first, "body": body_lines})
            continue
        m = re.match(r"^!\[(.*?)\]\((.*?)\)$", s)
        if m:
            flush(); blocks.append({"t": "img", "caption": m.group(1), "src": m.group(2)}); i += 1; continue
        if s.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                r = lines[i].strip()
                if not re.match(r"^\|[\s:\-|]+\|$", r):
                    rows.append([c.strip() for c in r.strip("|").split("|")])
                i += 1
            blocks.append({"t": "table", "rows": rows})
            continue
        m = re.match(r"^(\s*)([-*•])\s+(.*)$", ln)
        if m:
            flush(); blocks.append({"t": "li", "level": len(m.group(1)) // 2, "text": m.group(3)}); i += 1; continue
        m = re.match(r"^(\s*)(\d+)[.)]\s+(.*)$", ln)
        if m:
            flush()
            blocks.append({"t": "ol", "level": len(m.group(1)) // 2, "n": m.group(2), "text": m.group(3)})
            i += 1; continue
        para.append(ln)
        i += 1
    flush()
    return meta, blocks
