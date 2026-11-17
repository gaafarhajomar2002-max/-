#!/usr/bin/env python3
"""رسم صيغ كيميائية نظيفة (بدل صور اللوح) باستخدام RDKit.

    # بالاسم من القاموس (حموض دهنية، حموض أمينية، ...)
    python3 tools/chem_draw.py oleic -o lectures/.../images/oleic.png
    # أو بصيغة SMILES مباشرة
    python3 tools/chem_draw.py "CCCC(=O)O" --legend "Butyric acid" -o out.png
    # عرض القاموس
    python3 tools/chem_draw.py --list

للحموض الدهنية يضاف تلقائياً: ترقيم C1 عند COOH، أرقام Δ على الروابط المضاعفة (ملونة)، و ω عند نهاية الميثيل.
"""
import argparse
import sys

from rdkit import Chem
from rdkit.Chem import rdDepictor
from rdkit.Chem.Draw import rdMolDraw2D

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"  # فيه Δ و ω
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def sat(n: int) -> str:
    return "C" * (n - 1) + "C(=O)O"


# الاسم: (SMILES, وصف إنجليزي يظهر تحت الرسم)
LIB = {
    # ── حموض دهنية مشبعة ──
    "butyric": (sat(4), "Butyric acid  C4:0"),
    "caproic": (sat(6), "Caproic acid  C6:0"),
    "caprylic": (sat(8), "Caprylic acid  C8:0"),
    "capric": (sat(10), "Capric acid  C10:0"),
    "lauric": (sat(12), "Lauric acid  C12:0"),
    "myristic": (sat(14), "Myristic acid  C14:0"),
    "palmitic": (sat(16), "Palmitic acid  C16:0"),
    "stearic": (sat(18), "Stearic acid  C18:0"),
    "arachidic": (sat(20), "Arachidic acid  C20:0"),
    # ── حموض دهنية غير مشبعة (cis = Z) ──
    "oleic": ("CCCCCCCC/C=C\\CCCCCCCC(=O)O", "Oleic acid  C18:1 Δ9  (ω-9)"),
    "elaidic": ("CCCCCCCC/C=C/CCCCCCCC(=O)O", "Elaidic acid (trans)  C18:1 Δ9t  (ω-9)"),
    "linoleic": ("CCCCC/C=C\\C/C=C\\CCCCCCCC(=O)O", "Linoleic acid  C18:2 Δ9,12  (ω-6)"),
    "linolenic": ("CC/C=C\\C/C=C\\C/C=C\\CCCCCCCC(=O)O", "α-Linolenic acid  C18:3 Δ9,12,15  (ω-3)"),
    "arachidonic": ("CCCCC/C=C\\C/C=C\\C/C=C\\C/C=C\\CCCC(=O)O", "Arachidonic acid  C20:4 Δ5,8,11,14  (ω-6)"),
    "epa": ("CC/C=C\\C/C=C\\C/C=C\\C/C=C\\C/C=C\\CCCC(=O)O", "EPA  C20:5 Δ5,8,11,14,17  (ω-3)"),
    "dha": ("CC/C=C\\C/C=C\\C/C=C\\C/C=C\\C/C=C\\C/C=C\\CCC(=O)O", "DHA  C22:6 Δ4,7,10,13,16,19  (ω-3)"),
    # ── تماكب هندسي ──
    "maleic": ("OC(=O)/C=C\\C(=O)O", "Maleic acid (cis)"),
    "fumaric": ("OC(=O)/C=C/C(=O)O", "Fumaric acid (trans)"),
    # ── ليبيدات ──
    "glycerol": ("OCC(O)CO", "Glycerol"),
    "tristearin": ("CCCCCCCCCCCCCCCCCC(=O)OCC(COC(=O)CCCCCCCCCCCCCCCCC)OC(=O)CCCCCCCCCCCCCCCCC",
                   "Tristearin (triglyceride)"),
    # ── الحموض الأمينية (L) ──
    "glycine": ("NCC(=O)O", "Glycine (Gly, G)"),
    "alanine": ("C[C@@H](C(=O)O)N", "Alanine (Ala, A)"),
    "valine": ("CC(C)[C@@H](C(=O)O)N", "Valine (Val, V)"),
    "leucine": ("CC(C)C[C@@H](C(=O)O)N", "Leucine (Leu, L)"),
    "isoleucine": ("CC[C@H](C)[C@@H](C(=O)O)N", "Isoleucine (Ile, I)"),
    "serine": ("C([C@@H](C(=O)O)N)O", "Serine (Ser, S)"),
    "threonine": ("C[C@H]([C@@H](C(=O)O)N)O", "Threonine (Thr, T)"),
    "cysteine": ("C([C@@H](C(=O)O)N)S", "Cysteine (Cys, C)"),
    "methionine": ("CSCC[C@@H](C(=O)O)N", "Methionine (Met, M)"),
    "aspartic": ("C([C@@H](C(=O)O)N)C(=O)O", "Aspartic acid (Asp, D)"),
    "glutamic": ("C(CC(=O)O)[C@@H](C(=O)O)N", "Glutamic acid (Glu, E)"),
    "asparagine": ("C([C@@H](C(=O)O)N)C(=O)N", "Asparagine (Asn, N)"),
    "glutamine": ("C(CC(=O)N)[C@@H](C(=O)O)N", "Glutamine (Gln, Q)"),
    "lysine": ("C(CCN)C[C@@H](C(=O)O)N", "Lysine (Lys, K)"),
    "arginine": ("C(C[C@@H](C(=O)O)N)CN=C(N)N", "Arginine (Arg, R)"),
    "histidine": ("C1=C(NC=N1)C[C@@H](C(=O)O)N", "Histidine (His, H)"),
    "phenylalanine": ("C1=CC=C(C=C1)C[C@@H](C(=O)O)N", "Phenylalanine (Phe, F)"),
    "tyrosine": ("C1=CC(=CC=C1C[C@@H](C(=O)O)N)O", "Tyrosine (Tyr, Y)"),
    "tryptophan": ("C1=CC=C2C(=C1)C(=CN2)C[C@@H](C(=O)O)N", "Tryptophan (Trp, W)"),
    "proline": ("C1C[C@H](NC1)C(=O)O", "Proline (Pro, P)"),
    # ── سكريات ──
    "glucose": ("C([C@@H]1[C@H]([C@@H]([C@H](C(O1)O)O)O)O)O", "D-Glucose (pyranose)"),
    "fructose": ("C([C@@H]1[C@H]([C@@H](C(O1)(CO)O)O)O)O", "D-Fructose (furanose)"),
}


def carboxyl_chain(mol):
    """ترقيم سلسلة حمض دهني غير متفرعة من C1 (COOH). يعيد قائمة فهارس الذرات بالترتيب أو None."""
    for a in mol.GetAtoms():
        if a.GetSymbol() != "C":
            continue
        os_ = [n for n in a.GetNeighbors() if n.GetSymbol() == "O"]
        if len(os_) == 2 and any(mol.GetBondBetweenAtoms(a.GetIdx(), o.GetIdx()).GetBondTypeAsDouble() == 2
                                 for o in os_):
            chain, prev, cur = [a.GetIdx()], None, a
            while True:
                nxt = [n for n in cur.GetNeighbors() if n.GetSymbol() == "C" and n.GetIdx() != (prev or -1)
                       and n.GetIdx() not in chain]
                if len(nxt) != 1:
                    break
                prev, cur = cur.GetIdx(), nxt[0]
                chain.append(cur.GetIdx())
            if len(chain) >= 4 and all(mol.GetAtomWithIdx(i).GetDegree() <= 3 for i in chain):
                return chain
    return None


def draw(smiles: str, out: str, legend: str = "", width: int = 1400, height: int = 520, fa_notes=True):
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        raise SystemExit(f"SMILES غير صالح: {smiles}")
    rdDepictor.SetPreferCoordGen(True)
    rdDepictor.Compute2DCoords(mol)

    hl_bonds, hl_colors = [], {}
    omega_idx = None
    chain = carboxyl_chain(mol) if fa_notes else None
    if chain and len(chain) >= 6:
        mol.GetAtomWithIdx(chain[0]).SetProp("atomNote", "1")
        omega_idx = chain[-1]
        for k in range(len(chain) - 1):
            b = mol.GetBondBetweenAtoms(chain[k], chain[k + 1])
            if b.GetBondTypeAsDouble() == 2:
                mol.GetAtomWithIdx(chain[k]).SetProp("atomNote", str(k + 1))
                mol.GetAtomWithIdx(chain[k + 1]).SetProp("atomNote", str(k + 2))
                hl_bonds.append(b.GetIdx())
                hl_colors[b.GetIdx()] = (0.85, 0.2, 0.25)

    legend_h = 70 if legend else 0
    d = rdMolDraw2D.MolDraw2DCairo(width, height - legend_h)
    o = d.drawOptions()
    o.bondLineWidth = 3
    o.annotationFontScale = 0.75
    o.padding = 0.08
    o.highlightBondWidthMultiplier = 10
    o.setBackgroundColour((1, 1, 1, 1))
    d.DrawMolecule(mol, highlightAtoms=[], highlightBonds=hl_bonds,
                   highlightAtomColors={}, highlightBondColors=hl_colors)
    omega_xy = None
    if omega_idx is not None:
        pt = d.GetDrawCoords(omega_idx)
        omega_xy = (pt.x, pt.y)
    d.FinishDrawing()

    # النصوص اليونانية (Δ ω) لا تظهر صحيحة في RDKit، فنكتبها بـ Pillow
    import io
    from PIL import Image, ImageDraw, ImageFont
    mol_img = Image.open(io.BytesIO(d.GetDrawingText())).convert("RGB")
    img = Image.new("RGB", (width, height), "white")
    img.paste(mol_img, (0, 0))
    dr = ImageDraw.Draw(img)
    if omega_xy:
        f = ImageFont.truetype(FONT_BOLD, 34)
        x, y = omega_xy
        dr.text((x + 14, y + 6), "ω", font=f, fill=(217, 51, 64))
    if legend:
        f = ImageFont.truetype(FONT, 32)
        tw = dr.textlength(legend, font=f)
        dr.text(((width - tw) / 2, height - legend_h + 12), legend, font=f, fill=(20, 20, 20))
    img.save(out)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("what", nargs="*", help="اسم من القاموس أو SMILES (عدة أسماء = رسمها جنباً إلى جنب)")
    ap.add_argument("-o", "--out")
    ap.add_argument("--legend")
    ap.add_argument("--size", default=None, help="WxH مثل 1400x520")
    ap.add_argument("--plain", action="store_true", help="بدون ترقيم Δ/ω")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list or not a.what:
        for k, (_, lg) in LIB.items():
            print(f"{k:14s} {lg}")
        return
    if len(a.what) > 1:  # مقارنة جنباً إلى جنب
        from PIL import Image
        import tempfile
        w, h = (int(x) for x in a.size.split("x")) if a.size else (700 * len(a.what), 560)
        tiles = []
        for name in a.what:
            smi, lg = LIB.get(name.lower(), (name, ""))
            tmp = tempfile.mktemp(suffix=".png")
            tiles.append(Image.open(draw(smi, tmp, lg, w // len(a.what), h, fa_notes=not a.plain)))
        img = Image.new("RGB", (w, h), "white")
        for i, t in enumerate(tiles):
            img.paste(t, (i * (w // len(a.what)), 0))
        out = a.out or "_".join(a.what) + ".png"
        img.save(out)
        print(out)
        return
    name = a.what[0]
    smi, lg = LIB.get(name.lower(), (name, ""))
    w, h = (int(x) for x in a.size.split("x")) if a.size else (1400, 520)
    if name.lower() in LIB and not a.size and len(Chem.MolFromSmiles(smi).GetAtoms()) < 16:
        w, h = 800, 600  # الجزيئات الصغيرة (حموض أمينية...)
    print(draw(smi, a.out or f"{name}.png", a.legend if a.legend is not None else lg, w, h,
               fa_notes=not a.plain))


if __name__ == "__main__":
    sys.exit(main())
