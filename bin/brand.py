#!/usr/bin/env python3
"""brand.py - a look per show: caption and hook-card styles.

  brand.py list                                      brands in brands/
  brand.py show    <brand>                           the brand merged with the default look
  brand.py preview <brand> [project] [--at SECONDS] [--hook "text"] [--words "three caption words"]
                                                     one 1080x1920 still -> brands/<brand>/preview.png

A brand is brands/<name>/brand.json, plus (optionally) its own .ttf / .otf files in the same folder.
Every field is optional; a missing field keeps the default look (see DEFAULT below and
brands/README.md). A plan picks a brand with "brand": "<name>", for all its shorts or per short.
plan.py save freezes a copy of the brand into the version, so editing a brand later never changes
how an old version renders.
"""
import copy, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

SF = Path(os.environ.get("CUTCANNON") or Path(__file__).resolve().parent.parent)
BRANDS = SF / "brands"
FONTS = SF / "fonts"

# The default look: exactly what CutCannon rendered before brands existed.
# Sizes and margins are in pixels of a 1080-wide frame (scaled for other widths).
DEFAULT = {
    "captions": {
        "font": "Montserrat Black", "bold": False, "size": 84,
        "color": "#FFFFFF", "outline": "#000000", "outline_width": 7,
        "shadow": 3, "shadow_color": "#000000", "shadow_opacity": 0.5,
        "highlight": "#FFE500",          # the word being spoken
        "highlight_style": "color",      # "color": the word turns this color; "box": a box of this color behind it
        "highlight_text": None,          # "box" only: the word's text color (default: color)
        "highlight_padding": 10,         # "box" only: how far the box reaches past the word
        "uppercase": True,
        "margin_bottom": 560, "margin_side": 80,
    },
    "hook": {
        "font": "Montserrat Black", "bold": False, "size": 96,
        "color": "#111111", "box": "#FFFFFF", "box_opacity": 1.0, "box_padding": 28,
        "uppercase": True,
        "align": "center",               # left | center | right
        "margin_top": 300, "margin_side": 90,
        "prefix": "", "prefix_color": None,   # e.g. "> " in another color: a typed-terminal card
        "cursor": "", "cursor_color": None,   # e.g. "_" after the text
    },
}
ALIGN = {"left": 7, "center": 8, "right": 9}  # ASS top-row alignments
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def names():
    return sorted(p.parent.name for p in BRANDS.glob("*/brand.json"))


def problems(raw):
    """Readable problems with a brand.json (empty list = fine)."""
    probs = []
    if not isinstance(raw, dict):
        return ["brand.json must be a JSON object"]
    for sec, val in raw.items():
        if sec in ("description", "name"):
            continue
        if sec not in DEFAULT:
            probs.append(f"unknown section {sec!r} (captions | hook)")
            continue
        if not isinstance(val, dict):
            probs.append(f"{sec} must be an object")
            continue
        for k, v in val.items():
            if k not in DEFAULT[sec]:
                probs.append(f"{sec}.{k}: unknown field")
            elif k in ("color", "outline", "shadow_color", "highlight", "box") or (
                    k in ("highlight_text", "prefix_color", "cursor_color") and v is not None):
                if not (isinstance(v, str) and _HEX.match(v)):
                    probs.append(f"{sec}.{k}: {v!r} is not a #RRGGBB color")
            elif k in ("shadow_opacity", "box_opacity"):
                if not (isinstance(v, (int, float)) and 0 <= v <= 1):
                    probs.append(f"{sec}.{k}: must be 0..1")
            elif k in ("size", "outline_width", "shadow", "highlight_padding", "margin_bottom",
                       "margin_side", "box_padding", "margin_top"):
                if not (isinstance(v, (int, float)) and v >= 0):
                    probs.append(f"{sec}.{k}: must be a number >= 0")
            elif k in ("bold", "uppercase") and not isinstance(v, bool):
                probs.append(f"{sec}.{k}: must be true or false")
            elif k in ("font", "prefix", "cursor") and not isinstance(v, str):
                probs.append(f"{sec}.{k}: must be text")
    cap, hook = raw.get("captions", {}), raw.get("hook", {})
    if isinstance(cap, dict):
        hs = cap.get("highlight_style", "color")
        if not isinstance(hs, str) or hs not in ("color", "box"):
            probs.append("captions.highlight_style: color | box")
    if isinstance(hook, dict):
        al = hook.get("align", "center")
        if not isinstance(al, str) or al not in ALIGN:
            probs.append("hook.align: left | center | right")
    return probs


def read(name):
    """brands/<name>/brand.json as written (what plan.py freezes). ValueError with a readable message."""
    p = BRANDS / str(name) / "brand.json"
    if not p.exists():
        raise ValueError(f"unknown brand {name!r} (have: {', '.join(names()) or 'none yet'}; see brands/README.md)")
    try:
        raw = json.loads(p.read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f"brand {name}: bad JSON in {p}: {e}")
    probs = problems(raw)
    if probs:
        raise ValueError(f"brand {name}: " + "; ".join(probs))
    return raw


def merged(raw=None):
    look = copy.deepcopy(DEFAULT)
    for sec in DEFAULT:
        look[sec].update((raw or {}).get(sec, {}))
    return look


def for_short(short):
    """(look, brand name) for a resolved short: its frozen copy, else the named brand, else the default."""
    name = short.get("brand")
    raw = short.get("_brand")
    if raw is None and name:
        raw = read(name)
    return merged(raw), name


# ---------------------------------------------------------------- ASS
def ass_escape(s):
    return s.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def color(hex_, opacity=1.0):
    """#RRGGBB (+ opacity) -> ASS style colour &HAABBGGRR."""
    h = hex_.lstrip("#").upper()
    return f"&H{round((1 - opacity) * 255):02X}{h[4:6]}{h[2:4]}{h[0:2]}"


def tag_color(hex_):
    """#RRGGBB -> colour for an inline override (\\c, \\3c)."""
    h = hex_.lstrip("#").upper()
    return f"&H00{h[4:6]}{h[2:4]}{h[0:2]}&"


def ass_header(look, W, H):
    k = W / 1080
    px = lambda v: int(v * k)  # noqa: E731
    c, h = look["captions"], look["hook"]
    hb = color(h["box"], h["box_opacity"])
    return [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Cap,{c['font']},{px(c['size'])},{color(c['color'])},{color(c['color'])},{color(c['outline'])},"
        f"{color(c['shadow_color'], c['shadow_opacity'])},{-1 if c['bold'] else 0},0,0,0,100,100,0,0,1,"
        f"{px(c['outline_width'])},{px(c['shadow'])},2,{px(c['margin_side'])},{px(c['margin_side'])},"
        f"{px(c['margin_bottom'])},1",
        f"Style: Hook,{h['font']},{px(h['size'])},{color(h['color'])},{color(h['color'])},{hb},{hb},"
        f"{-1 if h['bold'] else 0},0,0,0,100,100,0,0,3,{px(h['box_padding'])},0,{ALIGN[h['align']]},"
        f"{px(h['margin_side'])},{px(h['margin_side'])},{px(h['margin_top'])},1",
        *box_style(look, W),
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]


def box_style(look, W):
    """For highlight_style "box": a CapBox style laid out exactly like Cap, with an opaque box
    (BorderStyle 3) in the highlight color. libass draws that box per glyph and honours each glyph's
    border alpha, so making every word but the spoken one transparent leaves a box behind that word."""
    c = look["captions"]
    if c["highlight_style"] != "box":
        return []
    k = W / 1080
    px = lambda v: int(v * k)  # noqa: E731
    hi = color(c["highlight"])
    return [f"Style: CapBox,{c['font']},{px(c['size'])},{hi},{hi},{hi},{hi},{-1 if c['bold'] else 0},"
            f"0,0,0,100,100,0,0,3,{px(c['highlight_padding'])},0,2,{px(c['margin_side'])},"
            f"{px(c['margin_side'])},{px(c['margin_bottom'])},1"]


def hook_text(look, text):
    """The hook card's ASS text: optional prefix, the hook, optional cursor."""
    h = look["hook"]
    base = tag_color(h["color"])

    def part(s, col):
        if not s:
            return ""
        return f"{{\\c{tag_color(col)}}}{ass_escape(s)}{{\\c{base}}}" if col else ass_escape(s)

    return part(h["prefix"], h["prefix_color"]) + ass_escape(text.upper() if h["uppercase"] else text) \
        + part(h["cursor"], h["cursor_color"])


def caption_text(look, chunk, wi, W):
    """One caption card (a few words) with word wi highlighted."""
    c = look["captions"]
    k = W / 1080
    up = str.upper if c["uppercase"] else (lambda s: s)
    hi, base = tag_color(c["highlight"]), tag_color(c["color"])
    out = []
    for j, x in enumerate(chunk):
        w = ass_escape(up(x["w"]))
        if j == wi and c["highlight_style"] == "box":
            # the box itself is the CapBox layer underneath; here the word just gets its text color
            tc = tag_color(c["highlight_text"]) if c["highlight_text"] else base
            w = (f"{{\\c{tc}\\bord0\\shad0}}{w}"
                 f"{{\\c{base}\\bord{int(c['outline_width'] * k)}\\shad{int(c['shadow'] * k)}}}")
        elif j == wi:
            w = f"{{\\c{hi}}}{w}{{\\c{base}}}"
        out.append(w)
    return " ".join(out)


def box_text(look, chunk, wi):
    """CapBox layer text: the same words, all transparent except the box behind word wi."""
    up = str.upper if look["captions"]["uppercase"] else (lambda s: s)
    out = []
    for j, x in enumerate(chunk):
        w = ass_escape(up(x["w"]))
        out.append(f"{{\\1a&HFF&\\3a&H00&}}{w}{{\\alpha&HFF&}}" if j == wi else w)
    return "{\\alpha&HFF&}" + " ".join(out)


def caption_events(look, chunk, wi, W):
    """[(layer, style, text)] for one caption card: the Cap line, plus a CapBox layer under it for box highlights."""
    ev = [(1, "Cap", caption_text(look, chunk, wi, W))]
    if look["captions"]["highlight_style"] == "box":
        ev.insert(0, (0, "CapBox", box_text(look, chunk, wi)))
    return ev


# ---------------------------------------------------------------- fonts
def fonts_dir(name):
    """(fontsdir for libass, temp dir to delete or None). A brand's own font files join fonts/."""
    extra = [f for f in (BRANDS / name).glob("*") if f.suffix.lower() in (".ttf", ".otf")] if name else []
    if not extra:
        return FONTS, None
    tmp = Path(tempfile.mkdtemp(prefix="cutcannon-fonts-"))
    for f in [*FONTS.glob("*.ttf"), *FONTS.glob("*.otf"), *extra]:
        if not (tmp / f.name).exists():
            (tmp / f.name).symlink_to(f.resolve())
    return tmp, tmp


def font_warnings(look, name):
    """Fonts the brand names that this machine doesn't have (libass would quietly substitute)."""
    if not shutil.which("fc-scan"):
        return []
    have = set()
    files = [*FONTS.glob("*.[ot]tf"), *((BRANDS / name).glob("*.[ot]tf") if name else [])]
    for f in files:
        r = subprocess.run(["fc-scan", "--format", "%{family}\n%{fullname}\n", str(f)], capture_output=True, text=True)
        for line in r.stdout.splitlines():
            have.update(x.strip().lower() for x in line.split(","))
    out = []
    for sec in ("captions", "hook"):
        f = look[sec]["font"]
        if f.lower() in have:
            continue
        if shutil.which("fc-list"):
            r = subprocess.run(["fc-list", f"{f}"], capture_output=True, text=True)
            if r.stdout.strip():
                continue
        out.append(f"{sec}.font {f!r} not found in fonts/, the brand folder or the system: it will fall back to another font")
    return out


# ---------------------------------------------------------------- preview
def preview(name, project=None, at=None, hook="The bug took 3 weeks. The fix took 1 line.",
            words="took one line"):
    look = merged(read(name))
    W, H = 1080, 1920
    tmp = Path(tempfile.mkdtemp(prefix="cutcannon-brand-"))
    fdir, ftmp = fonts_dir(name)
    try:
        ws = words.split()
        chunk = [{"w": w} for w in ws]
        lines = ass_header(look, W, H)
        lines.append(f"Dialogue: 2,0:00:00.00,0:00:05.00,Hook,,0,0,0,,{hook_text(look, hook)}")
        for layer, style, text in caption_events(look, chunk, len(ws) // 2, W):
            lines.append(f"Dialogue: {layer},0:00:00.00,0:00:05.00,{style},,0,0,0,,{text}")
        (tmp / "preview.ass").write_text("\n".join(lines) + "\n")
        vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},subtitles=preview.ass:fontsdir={fdir}"
        if project:
            sys.path.insert(0, str(Path(__file__).parent))
            import plan as P
            import render as R
            d = P.proj_dir(project)
            src = P.source(d)
            meta = json.loads((d / "meta.json").read_text())
            t = float(at) if at is not None else meta["duration"] * 0.25
            inp = ["-ss", f"{t:.2f}", "-i", str(src)]
            if R.source_transfer(src) in R.HDR_TRC:
                vf = R.TONEMAP + "," + vf
        else:
            inp = ["-f", "lavfi", "-i", f"color=c=0x3a4350:s={W}x{H}:d=1"]
        out = BRANDS / name / "preview.png"
        r = subprocess.run(["ffmpeg", "-y", "-v", "error", *inp, "-frames:v", "1", "-vf", vf, str(out)],
                           cwd=tmp, capture_output=True, text=True)
        if r.returncode:
            sys.exit(r.stderr[-1500:])
        for w in font_warnings(look, name):
            print("  warning:", w)
        print(out)
        return out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        if ftmp:
            shutil.rmtree(ftmp, ignore_errors=True)


def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    cmd = a.pop(0)
    if cmd == "list":
        for n in names():
            raw = json.loads((BRANDS / n / "brand.json").read_text())
            print(f"{n:16s} {raw.get('description', '')}")
        if not names():
            print("no brands yet: see brands/README.md")
    elif cmd == "show":
        print(json.dumps(merged(read(a[0])), indent=1))
    elif cmd == "preview":
        opt = {}
        for key in ("--at", "--hook", "--words"):
            if key in a:
                i = a.index(key)
                opt[key[2:]] = a[i + 1]
                del a[i:i + 2]
        try:
            preview(a[0], a[1] if len(a) > 1 else None, **opt)
        except ValueError as e:
            sys.exit(str(e))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
