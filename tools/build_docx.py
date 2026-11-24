#!/usr/bin/env python3
"""يبني ملف وورد عربي (RTL) منسّق من lecture.md.

    python3 tools/build_docx.py lectures/03-vitamin-d/lecture.md [--no-cover]

الترتيب في الملف الناتج:
  1. الغلاف (صورة كاملة الصفحة من make_cover.py)
  2. بطاقة المحاضرة + نمط الدكتور + دليل الرموز + الفهرس
  3. الشرح (فصول، صور، صناديق تنبيهات الدكتور والأسئلة والتوضيحات)
  4. ملحق المراجعة: كل تنبيهات الدكتور + بنك الأسئلة مع الفكرة/الجواب (يُجمع تلقائياً)
"""
import argparse
import json
import re
import sys
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

sys.path.insert(0, str(Path(__file__).parent))
from lecture_md import parse  # noqa: E402
from make_cover import THEMES, make_cover  # noqa: E402

# ───────────────────────── ترتيب عناصر XML (Word يتشدد بالترتيب) ─────────────────────────
SEQ = {
    "w:pPr": ["w:pStyle", "w:keepNext", "w:keepLines", "w:pageBreakBefore", "w:framePr", "w:widowControl",
              "w:numPr", "w:suppressLineNumbers", "w:pBdr", "w:shd", "w:tabs", "w:suppressAutoHyphens",
              "w:kinsoku", "w:wordWrap", "w:overflowPunct", "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN",
              "w:bidi", "w:adjustRightInd", "w:snapToGrid", "w:spacing", "w:ind", "w:contextualSpacing",
              "w:mirrorIndents", "w:suppressOverlap", "w:jc", "w:textDirection", "w:textAlignment",
              "w:textboxTightWrap", "w:outlineLvl", "w:divId", "w:cnfStyle", "w:rPr", "w:sectPr", "w:pPrChange"],
    "w:rPr": ["w:rStyle", "w:rFonts", "w:b", "w:bCs", "w:i", "w:iCs", "w:caps", "w:smallCaps", "w:strike",
              "w:dstrike", "w:outline", "w:shadow", "w:emboss", "w:imprint", "w:noProof", "w:snapToGrid",
              "w:vanish", "w:webHidden", "w:color", "w:spacing", "w:w", "w:kern", "w:position", "w:sz",
              "w:szCs", "w:highlight", "w:u", "w:effect", "w:bdr", "w:shd", "w:fitText", "w:vertAlign",
              "w:rtl", "w:cs", "w:em", "w:lang", "w:eastAsianLayout", "w:specVanish", "w:oMath"],
    "w:tblPr": ["w:tblStyle", "w:tblpPr", "w:tblOverlap", "w:bidiVisual", "w:tblStyleRowBandSize",
                "w:tblStyleColBandSize", "w:tblW", "w:jc", "w:tblCellSpacing", "w:tblInd", "w:tblBorders",
                "w:shd", "w:tblLayout", "w:tblCellMar", "w:tblLook"],
    "w:tcPr": ["w:cnfStyle", "w:tcW", "w:gridSpan", "w:hMerge", "w:vMerge", "w:tcBorders", "w:shd",
               "w:noWrap", "w:tcMar", "w:textDirection", "w:tcFitText", "w:vAlign", "w:hideMark"],
    "w:trPr": ["w:cnfStyle", "w:divId", "w:gridBefore", "w:gridAfter", "w:wBefore", "w:wAfter", "w:cantSplit",
               "w:trHeight", "w:tblHeader", "w:tblCellSpacing", "w:jc", "w:hidden"],
    "w:sectPr": ["w:headerReference", "w:footerReference", "w:footnotePr", "w:endnotePr", "w:type", "w:pgSz",
                 "w:pgMar", "w:paperSrc", "w:pgBorders", "w:lnNumType", "w:pgNumType", "w:cols", "w:formProt",
                 "w:vAlign", "w:noEndnote", "w:titlePg", "w:textDirection", "w:bidi", "w:rtlGutter",
                 "w:docGrid", "w:printerSettings"],
}


def put(parent, tag, **attrs):
    """أضف/استبدل عنصراً داخل parent في مكانه الصحيح حسب SEQ."""
    seq = SEQ[parent.tag.replace("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}", "w:")]
    old = parent.find(qn(tag))
    if old is not None:
        parent.remove(old)
    el = OxmlElement(tag)
    for k, v in attrs.items():
        el.set(qn(f"w:{k}"), str(v))
    idx = seq.index(tag)
    after = {qn(t) for t in seq[idx + 1:]}
    for i, child in enumerate(parent):
        if child.tag in after:
            parent.insert(i, el)
            return el
    parent.append(el)
    return el


AR = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
NON_AR = re.compile(r"[^\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]+")
EDGE_PUNCT = " \t.,،:;؛!?؟\"'«»=→←×÷≈≤≥<>"
FORMULA_RE = re.compile(r"(?:[A-Za-z0-9()\[\]+\-–−=/]|~[^~\s]+~|\^[^^\s]+\^)+")  # صيغة متصلة بلا فراغات
LEAD_ONLY = "+"  # "+" في أول المقطع تتبع العربي (بين حدّين)، أما في آخره فهي شحنة (Ca2+) فتبقى


def split_scripts(text: str):
    """يقسم النص إلى (مقطع, rtl). المقاطع اللاتينية/الرقمية (مصطلحات، صيغ، أرقام) تبقى LTR كوحدة واحدة،
    والأقواس غير المتوازنة والترقيم على أطرافها تُترك للعربي حتى لا ينقلب ترتيبها."""
    out, pos = [], 0
    for m in NON_AR.finditer(text):
        a, b = m.start(), m.end()
        chunk = text[a:b]
        if not re.search(r"[A-Za-z0-9\u00B5\u0370-\u03FF]", chunk):
            continue  # فراغات/ترقيم فقط: تبقى مع العربي
        # قصّ الأطراف: ترقيم، فراغات، وأقواس غير متوازنة
        while chunk and (chunk[0] in EDGE_PUNCT or (chunk[0] in LEAD_ONLY and len(chunk) > 1 and chunk[1] == " ")
                         or (chunk[0] == "(" and chunk.count("(") > chunk.count(")"))
                         or chunk[0] == ")"):
            chunk, a = chunk[1:], a + 1
        while chunk and (chunk[-1] in EDGE_PUNCT or (chunk[-1] == ")" and chunk.count(")") > chunk.count("("))
                         or chunk[-1] == "("
                         # شَرطة ملتصقة بكلمة عربية بعدها (9,10-ثنائي) تتبع العربي
                         or (chunk[-1] in "-–" and b < len(text) and AR.match(text[b]))):
            chunk, b = chunk[:-1], b - 1
        while chunk and chunk[0] in "-–" and a > 0 and AR.match(text[a - 1]):  # (أوميغا-3)
            chunk, a = chunk[1:], a + 1
        if not chunk:
            continue
        if a > pos:
            out.append((text[pos:a], True))
        out.append((chunk, False))
        pos = b
    if pos < len(text):
        out.append((text[pos:], True))
    return out


class Builder:
    def __init__(self, meta, base: Path):
        self.meta, self.base = meta, base
        # plain: yes ← ملف بنفس محتوى المصدر فقط (بلا ملحق مراجعة ولا دليل صناديق، والفصول متتابعة بلا صفحة جديدة)
        self.source_only = str(meta.get("plain", "")).strip().lower() in ("yes", "true", "1", "نعم")
        pr, dk, lt, ac = THEMES.get(meta.get("theme", "nutrition"), THEMES["nutrition"])
        self.c = {k: RGBColor.from_string(v[1:]) for k, v in dict(pr=pr, dk=dk, lt=lt, ac=ac).items()}
        self.hex = dict(pr=pr[1:], dk=dk[1:], lt=lt[1:], ac=ac[1:])
        self.font = meta.get("font", "Arial")
        self.doc = Document()
        self.fig = 0
        self.bm = 0
        self.h1s = []          # (text, bookmark)
        self.current_h1 = ""
        self.collected = {k: [] for k in ("admin", "doctor", "define", "why", "problem", "exam")}
        credits = base / "images" / "credits.json"
        self.credits = json.loads(credits.read_text(encoding="utf-8")) if credits.exists() else {}
        self._setup_styles()

    # ─────────────── إعداد الأنماط الافتراضية ───────────────
    def _setup_styles(self):
        st = self.doc.styles
        rpr_default = self.doc.styles.element.find(qn("w:docDefaults")).find(qn("w:rPrDefault")).find(qn("w:rPr"))
        put(rpr_default, "w:rFonts", ascii=self.font, hAnsi=self.font, cs=self.font, eastAsia=self.font)
        put(rpr_default, "w:lang", val="en-US", bidi="ar-SY")
        normal = st["Normal"]
        normal.font.name = self.font
        normal.font.size = Pt(13)
        rpr = normal.element.get_or_add_rPr()
        put(rpr, "w:szCs", val=28)  # 14pt للعربي
        ppr = normal.element.get_or_add_pPr()
        put(ppr, "w:bidi")
        pf = normal.paragraph_format
        pf.space_after = Pt(6)
        pf.line_spacing = 1.3
        for name, size, color in (("Heading 1", 20, "pr"), ("Heading 2", 16, "dk"), ("Heading 3", 14, "pr")):
            s = st[name]
            s.font.name = self.font
            s.font.size = Pt(size)
            s.font.bold = True
            s.font.color.rgb = self.c[color]
            r = s.element.get_or_add_rPr()
            put(r, "w:rFonts", ascii=self.font, hAnsi=self.font, cs=self.font, eastAsia=self.font)
            put(r, "w:bCs")
            put(r, "w:szCs", val=size * 2)
            put(s.element.get_or_add_pPr(), "w:bidi")
            s.paragraph_format.space_before = Pt(14 if name != "Heading 1" else 6)
            s.paragraph_format.space_after = Pt(6)
            s.paragraph_format.keep_with_next = True

    # ─────────────── أدوات الفقرات والنص ───────────────
    def para(self, align=None, style=None, space_after=None, keep=False):
        p = self.doc.add_paragraph(style=style)
        put(p._p.get_or_add_pPr(), "w:bidi")
        if align == "center":
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif align == "justify":
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        if space_after is not None:
            p.paragraph_format.space_after = Pt(space_after)
        if keep:
            p.paragraph_format.keep_with_next = True
        return p

    def run(self, p, text, bold=False, italic=False, size=None, color=None, highlight=False, vert=None, ltr=False,
            lrm=(True, True)):
        """يقسم النص إلى مقاطع عربية/لاتينية حتى تظهر المصطلحات الإنجليزية بالاتجاه الصحيح.
        ltr=True: النص قطعة من صيغة كيميائية، يُكتب كله من اليسار لليمين (مع أقواسه) دون تقسيم."""
        ppr = p._p.pPr
        rtl_para = ppr is not None and ppr.find(qn("w:bidi")) is not None
        for chunk, rtl in ([(text, False)] if ltr else split_scripts(text)):
            if not rtl:
                # عزل اتجاه مخفي على الطرفين (LRI … PDI): يُبقي الصيغة/المصطلح وحدة واحدة من اليسار لليمين
                # (كانت علامات LRM، لكنها تجعل LibreOffice يكسر الكلمة الإنجليزية في آخر السطر: "(B" | "otulic")
                # (بدونها تنتقل + و - والأقواس والأرقام في أول الصيغة إلى الجهة الخطأ داخل السطر العربي)
                # داخل الصيغة الواحدة توضع فقط على طرفيها (lrm) حتى لا ينكسر السطر بين قطعها
                chunk = ("\u2066" if lrm[0] else "") + chunk + ("\u2069" if lrm[1] else "")
            elif rtl_para and not AR.search(chunk):
                # فاصل محايد (سهم، +، =) بين صيغتين لاتينيتين داخل سطر عربي: علامة RLM تجعله يتبع العربي،
                # وإلا اندمجت الصيغتان والسهم في جزيرة لاتينية واحدة وانعكس ترتيب المعادلة
                chunk = "\u200f" + chunk + "\u200f"
            r = p.add_run(chunk)
            rp = r._r.get_or_add_rPr()
            put(rp, "w:rFonts", ascii=self.font, hAnsi=self.font, cs=self.font)
            if bold:
                r.bold = True; put(rp, "w:bCs")
            if italic:
                r.italic = True; put(rp, "w:iCs")
            if color is not None:
                r.font.color.rgb = color
            if size:
                r.font.size = Pt(size); put(rp, "w:szCs", val=int(size * 2))
            if highlight:
                put(rp, "w:shd", val="clear", color="auto", fill="FFF1A8")
            if vert:
                put(rp, "w:vertAlign", val=vert)
            if rtl:
                put(rp, "w:rtl")
        return p

    def rich(self, p, text, size=None, color=None, base_bold=False, italic=False, highlight=False):
        """**غامق** ==تظليل== *مائل*  H~2~O (سفلي)  Ca^2+^ (علوي) — ويمكن تداخلها."""
        kw = dict(size=size, color=color)
        for tok in re.split(r"(\{ص[^{}]*\}|\*\*.+?\*\*|==.+?==|(?<!\*)\*[^*]+?\*(?!\*))", text):
            if not tok:
                continue
            if tok.startswith("{ص") and tok.endswith("}"):  # مرجع صفحة في المصدر المكتوب
                self.run(p, " [" + tok[1:-1].strip() + "]", size=8.5, color=RGBColor(0x8A, 0x8A, 0x8A))
            elif tok.startswith("**") and len(tok) > 4:
                self.rich(p, tok[2:-2], base_bold=True, italic=italic, highlight=highlight, **kw)
            elif tok.startswith("==") and len(tok) > 4:
                self.rich(p, tok[2:-2], base_bold=True, italic=italic, highlight=True, **kw)
            elif tok.startswith("*") and len(tok) > 2 and not tok.startswith("**"):
                self.rich(p, tok[1:-1], base_bold=base_bold, italic=True, highlight=highlight, **kw)
            else:
                self.plain(p, tok, bold=base_bold, italic=italic, highlight=highlight, **kw)
        return p

    def plain(self, p, text, **kw):
        """نص بلا تنسيق غامق/مائل: الصيغ التي فيها سفلي/علوي (CH~3~(CH~2~)~16~COOH، N^+^(CH~3~)~3~)
        تُكتب كوحدة واحدة من اليسار لليمين، وإلا تنقلب أقواسها وتتبعثر قطعها داخل السطر العربي."""
        pos = 0
        for m in FORMULA_RE.finditer(text):
            a, b = m.start(), m.end()
            span = text[a:b]
            if "~" not in span and "^" not in span:
                continue
            # أقواس غير متوازنة وإشارات على الطرفين تبقى للنص العربي حولها
            while span and (span[0] in "+=/-–−" or span[0] == ")"
                            or (span[0] == "(" and span.count("(") > span.count(")"))):
                span, a = span[1:], a + 1
            while span and (span[-1] in "=/-–(" or (span[-1] == ")" and span.count(")") > span.count("("))):
                span, b = span[:-1], b - 1
            if "~" not in span and "^" not in span:
                continue
            if a > pos:
                self.subsup(p, text[pos:a], **kw)
            self.subsup(p, span, ltr=True, **kw)
            pos = b
        if pos < len(text):
            self.subsup(p, text[pos:], **kw)

    def subsup(self, p, text, ltr=False, **kw):
        toks = [x for x in re.split(r"(~[^~\s]+~|\^[^^\s]+\^)", text) if x]
        for i, tok in enumerate(toks):
            lrm = (i == 0, i == len(toks) - 1) if ltr else (True, True)
            # وصلة كلمات (WJ) بين قطع الصيغة: لا يُكسر السطر في منتصفها
            wj = "\u2060" if ltr and i > 0 else ""
            if len(tok) > 2 and tok[0] == tok[-1] and tok[0] in "~^":
                self.run(p, wj + tok[1:-1], vert="subscript" if tok[0] == "~" else "superscript", ltr=ltr, lrm=lrm, **kw)
            else:
                self.run(p, wj + tok, ltr=ltr, lrm=lrm, **kw)

    def shade_par(self, p, fill):
        put(p._p.get_or_add_pPr(), "w:shd", val="clear", color="auto", fill=fill)

    def indent_start(self, p, cm_start, cm_hanging=0):
        ind = put(p._p.get_or_add_pPr(), "w:ind", right=int(cm_start * 567))
        if cm_hanging:
            ind.set(qn("w:hanging"), str(int(cm_hanging * 567)))

    def bookmark(self, p, name):
        self.bm += 1
        s = OxmlElement("w:bookmarkStart"); s.set(qn("w:id"), str(self.bm)); s.set(qn("w:name"), name)
        e = OxmlElement("w:bookmarkEnd"); e.set(qn("w:id"), str(self.bm))
        p._p.insert(1, s); p._p.append(e)

    def link(self, p, text, anchor, color):
        h = OxmlElement("w:hyperlink"); h.set(qn("w:anchor"), anchor)
        r = OxmlElement("w:r"); rp = OxmlElement("w:rPr")
        r.append(rp)
        put(rp, "w:rFonts", ascii=self.font, hAnsi=self.font, cs=self.font)
        put(rp, "w:color", val=color)
        put(rp, "w:sz", val=26); put(rp, "w:szCs", val=28)
        put(rp, "w:rtl")
        t = OxmlElement("w:t"); t.text = text; t.set(qn("xml:space"), "preserve")
        r.append(t); h.append(r); p._p.append(h)

    def field(self, p, instr, size=10, color=None):
        def mk(tag, **a):
            r = OxmlElement("w:r")
            rp = OxmlElement("w:rPr"); r.append(rp)
            put(rp, "w:sz", val=size * 2); put(rp, "w:szCs", val=size * 2)
            if color:
                put(rp, "w:color", val=color)
            el = OxmlElement(tag)
            for k, v in a.items():
                el.set(qn(k), v)
            if tag == "w:instrText":
                el.text = instr; el.set(qn("xml:space"), "preserve")
            r.append(el)
            return r
        p._p.append(mk("w:fldChar", **{"w:fldCharType": "begin"}))
        p._p.append(mk("w:instrText"))
        p._p.append(mk("w:fldChar", **{"w:fldCharType": "separate"}))
        r = mk("w:t"); r[-1].text = "1"; p._p.append(r)
        p._p.append(mk("w:fldChar", **{"w:fldCharType": "end"}))

    # ─────────────── جداول وصناديق ───────────────
    def table(self, rows, cols, widths_cm=None):
        t = self.doc.add_table(rows=rows, cols=cols)
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        tblPr = t._tbl.tblPr
        put(tblPr, "w:bidiVisual")
        put(tblPr, "w:tblW", w=5000, type="pct")
        put(tblPr, "w:tblLayout", type="fixed" if widths_cm else "autofit")
        if widths_cm:
            for row in t.rows:
                for c, w in zip(row.cells, widths_cm):
                    c.width = Cm(w)
            # Word و LibreOffice يعتمدان على tblGrid في التخطيط الثابت
            for gc, w in zip(t._tbl.tblGrid.findall(qn("w:gridCol")), widths_cm):
                gc.set(qn("w:w"), str(int(w * 567)))
        return t

    def cell_fmt(self, cell, fill=None, borders=None, margin_cm=0.25):
        tcPr = cell._tc.get_or_add_tcPr()
        if borders:
            b = put(tcPr, "w:tcBorders")
            for side in ("top", "left", "bottom", "right"):
                e = OxmlElement(f"w:{side}")
                color, sz = borders
                e.set(qn("w:val"), "single" if color else "nil")
                if color:
                    e.set(qn("w:sz"), str(sz)); e.set(qn("w:color"), color)
                b.append(e)
        if fill:
            put(tcPr, "w:shd", val="clear", color="auto", fill=fill)
        mar = put(tcPr, "w:tcMar")
        for side in ("top", "left", "bottom", "right"):
            e = OxmlElement(f"w:{side}")
            e.set(qn("w:w"), str(int(margin_cm * 567 * (0.6 if side in ("top", "bottom") else 1))))
            e.set(qn("w:type"), "dxa")
            mar.append(e)

    def keep_together(self, t, header_rows=0, whole=True):
        """يمنع انقسام الصف، ويكرر رأس الجدول، ويُبقي الجدول الصغير كاملاً في صفحة واحدة."""
        n = len(t.rows)
        for i, row in enumerate(t.rows):
            trPr = row._tr.get_or_add_trPr()
            put(trPr, "w:cantSplit")
            if i < header_rows:
                put(trPr, "w:tblHeader")
            if whole and i < n - 1:
                for c in row.cells:
                    for p in c.paragraphs:
                        p.paragraph_format.keep_with_next = True

    def cell_para(self, cell, first=False):
        p = cell.paragraphs[0] if first else cell.add_paragraph()
        put(p._p.get_or_add_pPr(), "w:bidi")
        p.paragraph_format.space_after = Pt(3)
        return p

    CALLOUTS = {
        #  kind: (العنوان, لون الشريط, لون الخلفية)
        "doctor":   ("★ الدكتور شدّد على هذا",           "C98A0B", "FFF7E0"),
        "exam":     ("؟ سؤال متوقّع بالامتحان",          "B23A48", "FDEDEF"),
        "note":     ("✎ توضيح إضافي (لم يُشرح بشكل كافٍ)", "2F5D9E", "EAF1FB"),
        "remember": ("◆ تذكّر",                           "2E7D5B", "E7F4EC"),
        "tip":      ("✓ طريقة للحفظ",                     "6A4C93", "F1ECF8"),
        "mistake":  ("✗ خطأ شائع",                        "C4622D", "FCEFE6"),
        "summary":  ("≡ خلاصة الفصل",                     "1F7A8C", "E3F3F6"),
        "define":   ("§ عرّف",                            "00796B", "E0F2F1"),
        "why":      ("∵ علّل",                            "283593", "E8EAF6"),
        "problem":  ("∑ مسألة محلولة",                    "37474F", "ECEFF1"),
        "check":    ("⚠ تحقّق من هذه النقطة (غير واضحة بالتسجيل)", "D84315", "FBE9E7"),
        "admin":    ("☰ معلومة من الدكتور (امتحان، مراجع، مواعيد)", "5D4037", "EFEBE9"),
        "explain":  ("✦ شرح النقطة: كيف نكتبها، لماذا، من أين، وكيف تحدث", "00838F", "E0F7FA"),
        "style":    ("نمط الدكتور في الشرح والأسئلة",     "6A4C93", "F1ECF8"),
    }

    def callout(self, kind, head, body, title_override=None):
        title, bar, bg = self.CALLOUTS.get(kind, self.CALLOUTS["note"])
        title = title_override or title
        t = self.table(2, 1)
        c0, c1 = t.cell(0, 0), t.cell(1, 0)
        self.cell_fmt(c0, fill=bar, borders=(bar, 8))
        self.cell_fmt(c1, fill=bg, borders=(bar, 8), margin_cm=0.35)
        p = self.cell_para(c0, first=True); p.paragraph_format.space_after = Pt(0)
        self.run(p, title, bold=True, size=11.5, color=RGBColor(255, 255, 255))
        p = self.cell_para(c1, first=True)
        bold_head = kind in self.QA_KINDS
        if head:
            self.rich(p, head, base_bold=bold_head)
        for j, ln in enumerate(body):
            q = self.cell_para(c1) if (head or j) else p
            self.labeled_line(q, ln, RGBColor.from_string(bar))
        self.keep_together(t)
        sp = self.para(space_after=2)  # فاصل بعد الصندوق
        sp.paragraph_format.line_spacing = 0.6

    QA_KINDS = ("exam", "define", "why", "problem", "explain")
    LABEL_RE = re.compile(r"^(الجواب|الفكرة|الحل|لأن|لأنّ|السبب|التعريف|المعطيات|المطلوب|القانون|النتيجة|"
                          r"التعويض|الوحدة|ملاحظة|الخطوة\s*\d+|كيف نكتبها|كيف نكتبه|لماذا|من أين|كيف تحدث|"
                          r"كيف يحدث|كيف تعمل|كيف يعمل|المصدر)\s*[:：؟?]?\s*[:：]\s*(.*)$")

    def labeled_line(self, p, ln, color):
        if not AR.search(ln) and re.search(r"[→←⇌=+]", ln):
            # سطر رموز فقط (معادلة داخل صندوق): فقرة LTR في الوسط حتى لا ينقلب ترتيب المتفاعلات والنواتج
            pPr = p._p.get_or_add_pPr()
            for el in pPr.findall(qn("w:bidi")):
                pPr.remove(el)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            self.rich(p, ln, base_bold=True)
            return
        m = self.LABEL_RE.match(ln)
        if m:
            self.run(p, f"{m.group(1)}: ", bold=True, color=color)
            self.rich(p, m.group(2))
        else:
            self.list_or_rich(p, ln)

    def list_or_rich(self, p, ln):
        m = re.match(r"^[-*•]\s+(.*)$", ln)
        if m:
            self.run(p, "•  ", bold=True)
            self.rich(p, m.group(1))
        else:
            self.rich(p, ln)

    # ─────────────── الصفحات الخاصة ───────────────
    def cover(self):
        img = make_cover(self.base / "lecture.md")
        sec = self.doc.sections[0]
        sec.page_width, sec.page_height = Cm(21), Cm(29.7)
        for side in ("top_margin", "bottom_margin", "left_margin", "right_margin"):
            setattr(sec, side, Cm(0))
        sec.header_distance = sec.footer_distance = Cm(0)
        p = self.doc.paragraphs[0] if self.doc.paragraphs else self.doc.add_paragraph()
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.line_spacing = 1.0
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.add_run().add_picture(str(img), width=Cm(21), height=Cm(29.6))
        new = self.doc.add_section(WD_SECTION.NEW_PAGE)
        self._content_section(new)

    def _content_section(self, sec):
        sec.page_width, sec.page_height = Cm(21), Cm(29.7)
        sec.top_margin = sec.bottom_margin = Cm(2.2)
        sec.left_margin = sec.right_margin = Cm(2.0)
        sec.header_distance = sec.footer_distance = Cm(1.0)
        sp = sec._sectPr
        put(sp, "w:pgNumType", start=1)
        put(sp, "w:bidi")
        # رأس الصفحة
        sec.header.is_linked_to_previous = False
        hp = sec.header.paragraphs[0]
        put(hp._p.get_or_add_pPr(), "w:bidi")
        hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        pbdr = put(hp._p.get_or_add_pPr(), "w:pBdr")
        b = OxmlElement("w:bottom")
        for k, v in (("val", "single"), ("sz", "6"), ("space", "4"), ("color", self.hex["pr"])):
            b.set(qn(f"w:{k}"), v)
        pbdr.append(b)
        m = self.meta
        self.run(hp, f"{m.get('course', '')}  •  المحاضرة {m.get('lecture', '')}: {m.get('title', '')}",
                 size=9.5, color=self.c["pr"])
        # تذييل: رقم الصفحة
        sec.footer.is_linked_to_previous = False
        fp = sec.footer.paragraphs[0]
        put(fp._p.get_or_add_pPr(), "w:bidi")
        fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        self.run(fp, "— ", size=10, color=self.c["pr"])
        self.field(fp, "PAGE", 10, self.hex["pr"])
        self.run(fp, " —", size=10, color=self.c["pr"])

    def info_page(self, blocks):
        m = self.meta
        p = self.para(align="center", space_after=10)
        self.run(p, "بطاقة المحاضرة", bold=True, size=20, color=self.c["pr"])
        rows = [(k, m.get(key)) for k, key in (
            ("المقرر", "course"), ("رقم المحاضرة", "lecture"), ("العنوان", "title"), ("المحاضِر", "doctor"),
            ("التاريخ", "date"), ("مدة التسجيل", "duration"), ("المصدر", "source"),
            ("السنة / الفصل", "year")) if m.get(key)]
        t = self.table(len(rows), 2, widths_cm=[4.2, 12.8])
        for i, (k, v) in enumerate(rows):
            a, b = t.cell(i, 0), t.cell(i, 1)
            self.cell_fmt(a, fill=self.hex["pr"], borders=("FFFFFF", 6))
            self.cell_fmt(b, fill=self.hex["lt"] if i % 2 == 0 else "FFFFFF", borders=("FFFFFF", 6))
            self.run(self.cell_para(a, True), k, bold=True, color=RGBColor(255, 255, 255), size=11.5)
            self.rich(self.cell_para(b, True), str(v))
        self.para(space_after=4)

        # الفهرس
        p = self.para(space_after=4, keep=True)
        self.run(p, "الفهرس", bold=True, size=13, color=self.c["dk"])
        for i, bl in enumerate([b for b in blocks if b["t"] == "h1"], 1):
            q = self.para(space_after=1)
            self.indent_start(q, 0.4)
            self.run(q, f"{i}.  ", bold=True, color=self.c["pr"])
            self.link(q, bl["text"], f"sec{i}", self.hex["dk"])
        if self.source_only:
            # نسخة "نفس المحتوى فقط": لا ملحق ولا دليل صناديق، ويبدأ المحتوى بعد الفهرس مباشرة
            self.para(space_after=2)
            return
        q = self.para(space_after=1); self.indent_start(q, 0.4)
        self.run(q, "★  ", bold=True, color=self.c["ac"])
        self.link(q, "ملحق المراجعة: تنبيهات الدكتور وبنك الأسئلة", "review", self.hex["dk"])
        self.page_break()

        # نمط الدكتور: صناديق [!style] الموجودة قبل أول فصل، ثم باقي الصناديق التي قبل أول فصل
        # (وظيفة، موعد امتحان، ملاحظة عن المصادر...) في نفس الصفحة، وتُجمع في الملحق أيضاً
        pre = []
        for bl in blocks:
            if bl["t"] == "h1":
                break
            if bl["t"] == "callout":
                pre.append(bl)
        for bl in blocks:
            if bl["t"] == "callout" and bl["kind"] == "style":
                self.callout("style", bl["head"], bl["body"])
        for bl in pre:
            if bl["kind"] == "style":
                continue
            self.callout(bl["kind"], bl["head"], bl["body"])
            if bl["kind"] in self.collected:
                self.collected[bl["kind"]].append(("قبل الفصل الأول", bl["head"], bl["body"]))

        # دليل الرموز
        p = self.para(space_after=4, keep=True)
        self.run(p, "دليل الصناديق في هذا الملف", bold=True, size=13, color=self.c["dk"])
        legend = ["doctor", "exam", "define", "why", "problem", "explain", "note", "remember", "tip", "mistake",
                  "check", "admin"]
        t = self.table((len(legend) + 1) // 2, 2)
        for i, k in enumerate(legend):
            title, bar, bg = self.CALLOUTS[k]
            c = t.cell(i // 2, i % 2)
            self.cell_fmt(c, fill=bg, borders=(bar, 6), margin_cm=0.2)
            self.run(self.cell_para(c, True), title, bold=True, size=10.5, color=RGBColor.from_string(bar))
        self.para(space_after=2)

        self.page_break()

    def page_break(self):
        self.doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    # ─────────────── المحتوى ───────────────
    def drop_trailing_spacer(self):
        """يحذف الفقرة الفارغة الأخيرة (فاصل بعد صندوق) قبل عنوان يبدأ بصفحة جديدة،
        لأنها إن وقعت أول صفحة جديدة يصبح عندنا صفحة فارغة تماماً."""
        body = self.doc.element.body
        last = body[-2] if body[-1].tag == qn("w:sectPr") else body[-1]
        if last.tag == qn("w:p") and not "".join(last.itertext()).strip() and last.find(".//" + qn("w:drawing")) is None \
                and last.find(".//" + qn("w:sectPr")) is None and last.find(".//" + qn("w:br")) is None:
            body.remove(last)

    def h1(self, text, new_page=False):
        n = len(self.h1s) + 1
        self.h1s.append(text)
        self.current_h1 = text
        if new_page:
            self.drop_trailing_spacer()
        p = self.doc.add_heading(level=1)
        p.paragraph_format.page_break_before = new_page
        put(p._p.get_or_add_pPr(), "w:bidi")
        self.shade_par(p, self.hex["pr"])
        self.run(p, f"  {n}.  {text}  ", bold=True, size=19, color=RGBColor(255, 255, 255))
        self.bookmark(p, f"sec{n}")

    def heading(self, level, text):
        p = self.doc.add_heading(level=level)
        put(p._p.get_or_add_pPr(), "w:bidi")
        if level == 2:
            pbdr = put(p._p.get_or_add_pPr(), "w:pBdr")
            b = OxmlElement("w:bottom")
            for k, v in (("val", "single"), ("sz", "8"), ("space", "2"), ("color", self.hex["ac"])):
                b.set(qn(f"w:{k}"), v)
            pbdr.append(b)
        self.rich(p, text, size=16 if level == 2 else 14, color=self.c["dk" if level == 2 else "pr"], base_bold=True)

    def image(self, src, caption):
        # خيارات اختيارية بعد | في المسار: w=عرض بالسم، h=أقصى ارتفاع بالسم. مثال: images/map.png|h=22
        opts = {}
        if "|" in src:
            src, raw = src.split("|", 1)
            for kv in raw.split(","):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    opts[k.strip()] = float(v)
        path = (self.base / src).resolve()
        if not path.exists():
            p = self.para(align="center"); self.run(p, f"[صورة مفقودة: {src}]", color=RGBColor(200, 0, 0))
            return
        orig_name = path.name
        path = self._normalize(path)
        from PIL import Image
        with Image.open(path) as im:
            w, h = im.size
        width = opts.get("w", 16.5 if w / h >= 2 else 12.5)   # الصور العريضة (معادلات، سلاسل، مقارنات) بعرض الصفحة
        maxh = opts.get("h", 9)     # حدّ أقصى للارتفاع حتى لا تترك الصور فراغات كبيرة
        if h / w * width > maxh:
            width = maxh * w / h
        p = self.para(align="center", space_after=2, keep=True)
        p.add_run().add_picture(str(path), width=Cm(width))
        self.fig += 1
        p = self.para(align="center", space_after=10)
        self.run(p, f"الشكل {self.fig}: ", bold=True, size=10.5, color=self.c["pr"])
        self.rich(p, caption, size=10.5)
        cr = self.credits.get(orig_name)
        if cr:
            q = self.para(align="center", space_after=10)
            p.paragraph_format.space_after = Pt(0)
            self.run(q, f"المصدر: Wikimedia Commons — {cr.get('creator', '')} — {cr.get('license', '')}",
                     size=8, color=RGBColor(0x88, 0x88, 0x88))

    def _normalize(self, path: Path) -> Path:
        """تحويل أي صورة إلى RGB على خلفية بيضاء (الشفافية والرمادي تسبب مشاكل في وورد)."""
        from PIL import Image
        cache = self.base / "_build"
        cache.mkdir(exist_ok=True)
        with Image.open(path) as im:
            im.load()
            if im.mode in ("RGBA", "LA", "P", "PA") or "transparency" in im.info:
                im = im.convert("RGBA")
                bg = Image.new("RGB", im.size, (255, 255, 255))
                bg.paste(im, mask=im.split()[-1])
                im = bg
            else:
                im = im.convert("RGB")
            photo = path.suffix.lower() in (".jpg", ".jpeg")
            out = cache / (path.stem + (".jpg" if photo else ".png"))
            im.save(out, quality=88) if photo else im.save(out, optimize=True)
        return out

    def equation(self, text):
        """معادلة كيميائية في الوسط داخل إطار خفيف.
        رموز فقط → فقرة LTR. فيها كلمات عربية → فقرة RTL والسهم ← (المتفاعلات يميناً والنواتج يساراً)."""
        p = self.doc.add_paragraph()
        if AR.search(text):
            put(p._p.get_or_add_pPr(), "w:bidi")
            text = text.replace("→", "←")
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(4)
        p.paragraph_format.space_after = Pt(8)
        p.paragraph_format.keep_together = True
        self.shade_par(p, self.hex["lt"])
        plain = re.sub(r"[~^]", "", text)
        size = 13.5 if len(plain) <= 52 else max(9.5, 13.5 * 52 / len(plain))
        self.rich(p, text, size=size, color=self.c["dk"], base_bold=True)

    def md_table(self, rows):
        ncol = max(len(r) for r in rows)
        # عرض كل عمود حسب أطول نص فيه (بدون رموز التنسيق)، مجموعها = عرض الصفحة 17 سم
        def plen(x):
            return len(re.sub(r"[*=~^]", "", x))
        need = []
        for j in range(ncol):
            body = [plen(r[j]) for r in rows[1:] if j < len(r)] or [0]
            head = plen(rows[0][j]) if j < len(rows[0]) else 0
            need.append(max(max(body), head * 0.6, 4))
        tot = sum(need)
        widths = [max(2.4, 17.0 * n / tot) for n in need]
        k = 17.0 / sum(widths)
        t = self.table(len(rows), ncol, widths_cm=[w * k for w in widths])
        for i, r in enumerate(rows):
            for j in range(ncol):
                c = t.cell(i, j)
                txt = r[j] if j < len(r) else ""
                if i == 0:
                    self.cell_fmt(c, fill=self.hex["pr"], borders=(self.hex["pr"], 6))
                    self.rich(self.cell_para(c, True), txt, color=RGBColor(255, 255, 255), base_bold=True, size=11.5)
                else:
                    self.cell_fmt(c, fill=self.hex["lt"] if i % 2 == 0 else "FFFFFF", borders=("BFBFBF", 4))
                    self.rich(self.cell_para(c, True), txt, size=11.5)
        self.keep_together(t, header_rows=1, whole=len(rows) <= 15)
        self.para(space_after=4)

    def content(self, blocks):
        first_h1 = True
        for bl in blocks:
            t = bl["t"]
            if t == "h1":
                # page_break_before بدل فقرة فاصلة (الفقرة الفاصلة قد تولّد صفحة فارغة إذا امتلأت الصفحة قبلها)
                self.h1(bl["text"], new_page=not first_h1 and not self.source_only)
                first_h1 = False
            elif t in ("h2", "h3"):
                self.heading(int(t[1]), bl["text"])
            elif t == "p":
                self.rich(self.para(align="justify"), bl["text"])
            elif t == "li":
                p = self.para(space_after=3)
                self.indent_start(p, 0.7 + 0.7 * bl["level"], 0.5)
                self.run(p, ("●" if bl["level"] == 0 else "○") + "  ", color=self.c["pr"], size=10)
                self.rich(p, bl["text"])
            elif t == "ol":
                p = self.para(space_after=3)
                self.indent_start(p, 0.8 + 0.7 * bl["level"], 0.6)
                self.run(p, f"{bl['n']}.  ", bold=True, color=self.c["pr"])
                self.rich(p, bl["text"])
            elif t == "img":
                self.image(bl["src"], bl["caption"])
            elif t == "eq":
                self.equation(bl["text"])
            elif t == "table":
                self.md_table(bl["rows"])
            elif t == "pagebreak":
                self.page_break()
            elif t == "callout":
                if bl["kind"] == "style":
                    continue  # تُعرض في صفحة البطاقة
                if first_h1:
                    continue  # صناديق ما قبل أول فصل تُعرض في صفحة نمط الدكتور
                self.callout(bl["kind"], bl["head"], bl["body"])
                if bl["kind"] in self.collected:
                    self.collected[bl["kind"]].append((self.current_h1, bl["head"], bl["body"]))

    def review(self):
        self.drop_trailing_spacer()
        p = self.doc.add_heading(level=1)
        p.paragraph_format.page_break_before = True
        put(p._p.get_or_add_pPr(), "w:bidi")
        self.shade_par(p, self.hex["dk"])
        self.run(p, "  ★  ملحق المراجعة قبل الامتحان  ", bold=True, size=19, color=RGBColor(255, 255, 255))
        self.bookmark(p, "review")
        self.rich(self.para(align="justify"),
                  "هذا الملحق يجمع تلقائياً من كل المحاضرة: ما **شدّد عليه الدكتور**، و**التعاريف**، "
                  "و**علّل**، و**المسائل المحلولة**، و**الأسئلة المتوقعة**، مرتبةً حسب الفصول، "
                  "حتى تراجعها بسرعة ليلة الامتحان.")
        ordinals = iter(["أولاً", "ثانياً", "ثالثاً", "رابعاً", "خامساً", "سادساً"])
        c = self.collected

        if c["admin"]:
            self.heading(2, f"{next(ordinals)}: معلومات من الدكتور عن الامتحان والمقرر ({len(c['admin'])})")
            for sec, head, body in c["admin"]:
                p = self.para(space_after=3)
                self.indent_start(p, 0.9, 0.7)
                self.run(p, "☰  ", bold=True, color=RGBColor.from_string("5D4037"))
                self.rich(p, head)
                for ln in body:
                    q = self.para(space_after=2)
                    self.indent_start(q, 1.6, 0)
                    self.rich(q, re.sub(r"^[-*•]\s+", "• ", ln), size=12)

        if c["doctor"]:
            self.heading(2, f"{next(ordinals)}: ما شدّد عليه الدكتور ({len(c['doctor'])})")
            last = None
            for i, (sec, head, body) in enumerate(c["doctor"], 1):
                if sec != last:
                    q = self.para(space_after=2, keep=True)
                    self.run(q, f"◂ {sec}", bold=True, size=11, color=self.c["pr"])
                    last = sec
                p = self.para(space_after=3)
                self.indent_start(p, 0.9, 0.7)
                self.run(p, f"{i}.  ", bold=True, color=RGBColor.from_string("C98A0B"))
                self.rich(p, head)
                for ln in body:
                    q = self.para(space_after=2)
                    self.indent_start(q, 1.6, 0)
                    self.rich(q, re.sub(r"^[-*•]\s+", "• ", ln), size=12)

        if c["define"]:
            self.heading(2, f"{next(ordinals)}: التعاريف ({len(c['define'])})")
            rows = [["المصطلح", "التعريف"]] + [[h, " ".join(b)] for _, h, b in c["define"]]
            t = self.table(len(rows), 2, widths_cm=[4.5, 12.5])
            for i, r in enumerate(rows):
                for j, txt in enumerate(r):
                    cell = t.cell(i, j)
                    if i == 0:
                        self.cell_fmt(cell, fill="00796B", borders=("00796B", 6))
                        self.run(self.cell_para(cell, True), txt, bold=True, size=11.5, color=RGBColor(255, 255, 255))
                    else:
                        self.cell_fmt(cell, fill="E0F2F1" if i % 2 == 0 else "FFFFFF", borders=("BFBFBF", 4))
                        self.rich(self.cell_para(cell, True), txt, size=11.5, base_bold=(j == 0))
            self.keep_together(t, header_rows=1, whole=False)
            self.para(space_after=4)

        for kind, title, prefix in (("why", "علّل", "علّل"), ("problem", "المسائل المحلولة", "مسألة"),
                                    ("exam", "بنك الأسئلة", "س")):
            if not c[kind]:
                continue
            _, bar, bg = self.CALLOUTS[kind]
            self.heading(2, f"{next(ordinals)}: {title} ({len(c[kind])})")
            for i, (sec, head, body) in enumerate(c[kind], 1):
                t = self.table(1, 1)
                cell = t.cell(0, 0)
                self.cell_fmt(cell, fill=bg if i % 2 else "FFFFFF", borders=(bar, 4), margin_cm=0.3)
                p = self.cell_para(cell, True)
                self.run(p, f"{prefix} {i}: " if prefix != "س" else f"س{i}: ", bold=True,
                         color=RGBColor.from_string(bar))
                self.rich(p, head, base_bold=True)
                for ln in body:
                    self.labeled_line(self.cell_para(cell), ln, self.c["pr"])
                q = self.cell_para(cell)
                self.run(q, f"(من: {sec})", size=9, color=RGBColor(0x88, 0x88, 0x88))
                self.keep_together(t)
                self.para(space_after=0).paragraph_format.line_spacing = 0.5


def build(md_path: Path, cover=True) -> Path:
    meta, blocks = parse(md_path.read_text(encoding="utf-8"))
    b = Builder(meta, md_path.parent)
    if cover:
        b.cover()
    else:
        b._content_section(b.doc.sections[0])
    b.info_page(blocks)
    b.content(blocks)
    if not b.source_only:
        b.review()
    name = meta.get("output") or f"المحاضرة {meta.get('lecture', '')} - {meta.get('title', 'محاضرة')}"
    out = md_path.parent / (re.sub(r'[\\/:*?"<>|]+', "-", name).strip() + ".docx")
    b.doc.core_properties.title = meta.get("title", "")
    b.doc.core_properties.subject = meta.get("course", "")
    b.doc.save(out)
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("md")
    ap.add_argument("--no-cover", action="store_true")
    a = ap.parse_args()
    print(build(Path(a.md), cover=not a.no_cover))
