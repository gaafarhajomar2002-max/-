#!/usr/bin/env python3
"""رسم صيغ إسقاط فيشر للسكريات، وشجرة اشتقاق السكريات D (ألدوزات وكيتوزات).

    python3 tools/fischer.py sugar D-glucose -o glucose.png        # سكر واحد
    python3 tools/fischer.py sugars D-glucose D-mannose -o x.png   # عدة سكريات جنباً إلى جنب
    python3 tools/fischer.py tree aldose -o tree.png               # شجرة الألدوزات D (3 → 6 كربون)
    python3 tools/fischer.py tree ketose -o tree.png               # شجرة الكيتوزات D
    python3 tools/fischer.py --list

النمط: لكل ذرة كربون غير متناظرة من الأعلى للأسفل: R = OH على اليمين، L = OH على اليسار.
آخر حرف دائماً R في سكريات D (وهذا تعريف D).
"""
import argparse
import sys

from PIL import Image, ImageDraw, ImageFont

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_B = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# الألدوزات D: أنماط C2.. (من الأعلى)
ALDOSES = {
    "D-glyceraldehyde": "R",
    "D-erythrose": "RR", "D-threose": "LR",
    "D-ribose": "RRR", "D-arabinose": "LRR", "D-xylose": "RLR", "D-lyxose": "LLR",
    "D-allose": "RRRR", "D-altrose": "LRRR", "D-glucose": "RLRR", "D-mannose": "LLRR",
    "D-gulose": "RRLR", "D-idose": "LRLR", "D-galactose": "RLLR", "D-talose": "LLLR",
}
# الكيتوزات D: C1 = CH2OH، C2 = C=O، ثم أنماط C3..
KETOSES = {
    "dihydroxyacetone": "",
    "D-erythrulose": "R",
    "D-ribulose": "RR", "D-xylulose": "LR",
    "D-psicose": "RRR", "D-fructose": "LRR", "D-sorbose": "RLR", "D-tagatose": "LLR",
}
# الكحولات السكرية (إرجاع CHO أو C=O إلى CH2OH): نفس نمط السكر الأصلي لكن الأعلى CH2OH
ALDITOLS = {"D-sorbitol": "RLRR", "D-mannitol": "LLRR", "ribitol": "RRR", "xylitol": "RLR"}


def mirror(p):  # L-sugar
    return "".join("L" if c == "R" else "R" for c in p)


def resolve(name):
    for table, kind in ((ALDOSES, "aldose"), (KETOSES, "ketose"), (ALDITOLS, "alditol")):
        if name in table:
            return table[name], kind
        if name.startswith("L-") and "D-" + name[2:] in table:
            return mirror(table["D-" + name[2:]]), kind
    raise SystemExit(f"غير معروف: {name}")


def draw_sugar(name, scale=1.0, highlight_last=True):
    pattern, kind = resolve(name)
    f = ImageFont.truetype(FONT, int(22 * scale))
    fb = ImageFont.truetype(FONT_B, int(22 * scale))
    fl = ImageFont.truetype(FONT_B, int(19 * scale))
    row = int(40 * scale)
    top = {"aldose": ["CHO"], "ketose": ["CH₂OH", "C=O"], "alditol": ["CH₂OH"]}[kind]
    rows = top + list(pattern) + ["CH₂OH"]
    if kind == "ketose" and not pattern:
        rows = ["CH₂OH", "C=O", "CH₂OH"]
    W = int(190 * scale)
    H = row * len(rows) + int(60 * scale)
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    cx = W // 2
    y0 = int(14 * scale)
    centers = []
    for i, r in enumerate(rows):
        y = y0 + i * row + row // 2
        centers.append(y)
        if r in ("R", "L"):
            last = highlight_last and i == len(rows) - 2
            col = (200, 40, 60) if last else (20, 20, 20)
            d.text((cx, y), "C", font=fb, fill=(20, 20, 20), anchor="mm")
            lw = int(36 * scale)
            d.line((cx - lw, y, cx - int(12 * scale), y), fill=(20, 20, 20), width=max(2, int(2 * scale)))
            d.line((cx + int(12 * scale), y, cx + lw, y), fill=(20, 20, 20), width=max(2, int(2 * scale)))
            left, right = ("H", "OH") if r == "R" else ("HO", "H")
            d.text((cx - lw - 4, y), left, font=fb if left != "H" else f,
                   fill=col if left != "H" else (20, 20, 20), anchor="rm")
            d.text((cx + lw + 4, y), right, font=fb if right != "H" else f,
                   fill=col if right != "H" else (20, 20, 20), anchor="lm")
        else:
            d.text((cx, y), r, font=fb, fill=(20, 20, 20), anchor="mm")
    for a, b in zip(centers, centers[1:]):  # الروابط العمودية
        d.line((cx, a + int(13 * scale), cx, b - int(13 * scale)), fill=(20, 20, 20), width=max(2, int(2 * scale)))
    d.text((cx, H - int(22 * scale)), name, font=fl, fill=(30, 60, 120), anchor="mm")
    return img


def side_by_side(names, scale=1.0):
    ims = [draw_sugar(n, scale) for n in names]
    H = max(i.size[1] for i in ims)
    W = sum(i.size[0] for i in ims)
    out = Image.new("RGB", (W, H), "white")
    x = 0
    for im in ims:
        out.paste(im, (x, H - im.size[1]))
        x += im.size[0]
    return out


def tree(kind, scale=0.78):
    """شجرة: كل سكر يعطي ولدين بإضافة كربون جديد تحت C=O / CHO (OH يمين ثم يسار)."""
    table = ALDOSES if kind == "aldose" else KETOSES
    levels = {}
    for n, p in table.items():
        levels.setdefault(len(p), []).append(n)
    # ترتيب كل مستوى حسب ترتيب الآباء: الولد يُشتق بإضافة حرف في البداية (الكربون الجديد تحت الزمرة الوظيفية)
    order = {min(levels): levels[min(levels)]}
    for L in sorted(levels)[1:]:
        kids = []
        for parent in order[L - 1]:
            pp = table[parent]
            for c in "RL":
                kids += [n for n in levels[L] if table[n] == c + pp]
        order[L] = kids
    tiles = {L: [draw_sugar(n, scale) for n in order[L]] for L in order}
    tw = max(t.size[0] for ts in tiles.values() for t in ts)
    ncol = max(len(v) for v in order.values())
    W = tw * ncol + 40
    gap = int(64 * scale)
    heights = {L: max(t.size[1] for t in tiles[L]) for L in tiles}
    H = sum(heights.values()) + gap * (len(tiles) - 1) + 40
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    y = 20
    pos = {}
    for L in sorted(tiles):
        n = len(tiles[L])
        slot = (W - 40) / n
        for i, (name, t) in enumerate(zip(order[L], tiles[L])):
            x = int(20 + slot * i + (slot - t.size[0]) / 2)
            img.paste(t, (x, y + heights[L] - t.size[1]))
            pos[name] = (x + t.size[0] // 2, y, y + heights[L])
        y += heights[L] + gap
    for L in sorted(tiles)[1:]:  # خطوط الأب ← الولد
        for name in order[L]:
            parent = next(p for p in order[L - 1] if table[name][1:] == table[p])
            px, _, pbot = pos[parent]
            cx, ctop, _ = pos[name]
            d.line((px, pbot + 4, cx, ctop + 2), fill=(150, 150, 150), width=max(2, int(2.5 * scale)))
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", nargs="?", choices=["sugar", "sugars", "tree"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("-o", "--out", default="fischer.png")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--scale", type=float, default=2.0, help="دقة الرسم (2 = مناسب للوورد)")
    a = ap.parse_args()
    if a.list or not a.cmd:
        print("ألدوزات:", ", ".join(ALDOSES))
        print("كيتوزات:", ", ".join(KETOSES))
        print("كحولات سكرية:", ", ".join(ALDITOLS))
        print("وأي اسم بـ L- بدل D- يعطي الصورة المرآتية")
        return
    if a.cmd == "sugar":
        im = draw_sugar(a.args[0], a.scale)
    elif a.cmd == "sugars":
        im = side_by_side(a.args, a.scale)
    else:
        im = tree(a.args[0] if a.args else "aldose", a.scale * 0.75)
    im.save(a.out)
    print(a.out, im.size)


if __name__ == "__main__":
    sys.exit(main())
