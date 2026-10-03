#!/usr/bin/env python3
"""render.py <proj> [short_id ...] [--version vN] [--preview]

Renders the CURRENT plan (or --version) to renders/<id>_vNNN.mp4 at 1080x1920.
--preview renders 540x960 fast for review.
Nothing is uploaded or posted anywhere.
"""
import json, os, subprocess, sys, time
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).parent))
import plan as P  # noqa: E402

SF = P.SF
FONTS = SF / "fonts"
PUNCH = 1.08  # zoom on alternate segments; hides jump cuts


# ---------------------------------------------------------------- reframe
def _faces():
    """YuNet. Returns f(frame) -> [(x_center_norm, width_norm), ...] for every face."""
    import cv2
    try:
        cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
    except Exception:
        pass
    model = str(SF / "models" / "yunet.onnx")
    state = {"fd": None, "size": None}

    def det(frame):
        h, w = frame.shape[:2]
        small = cv2.resize(frame, (640, int(h * 640 / w)))
        if state["size"] != small.shape[:2]:
            state["fd"] = cv2.FaceDetectorYN.create(model, "", (small.shape[1], small.shape[0]), 0.6)
            state["size"] = small.shape[:2]
        _, faces = state["fd"].detect(small)
        return [] if faces is None else [(float((f[0] + f[2] / 2) / 640), float(f[2] / 640)) for f in faces]
    return det


def _detector():
    """f(frame) -> normalized x of the largest face, or None (used by QA)."""
    det = _faces()

    def one(frame):
        fs = det(frame)
        return max(fs, key=lambda f: f[1])[0] if fs else None
    return one


PICK = {"left": lambda fs: min(fs), "right": lambda fs: max(fs),
        "largest": lambda fs: max(fs, key=lambda f: f[1])}


def _shot_cut(cap, a, b):
    """Exact time of the camera cut between samples a and b: max frame difference."""
    import cv2, numpy as np
    cap.set(cv2.CAP_PROP_POS_MSEC, a * 1000)
    prev, best, best_t = None, -1.0, b
    while True:
        t = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
        ok, fr = cap.read()
        if not ok or t > b + 0.05:
            break
        g = cv2.cvtColor(cv2.resize(fr, (160, 90)), cv2.COLOR_BGR2GRAY).astype(np.float32)
        if prev is not None:
            dd = float(np.abs(g - prev).mean())
            if dd > best:
                best, best_t = dd, t
        prev = g
    return best_t


def crop_track(cap, det, c, track):
    """Keyframes [(t_rel, x_norm), ...] following one person through camera switches.
    track: left | right | largest. Faces under 6% of frame width (photos, screens,
    people in the background) are ignored."""
    import cv2
    ts, xs, t = [], [], c["start"]
    while t < c["end"]:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, fr = cap.read()
        if ok:
            fs = [f for f in det(fr) if f[1] > 0.06]
            if fs:
                ts.append(t)
                xs.append(PICK[track](fs)[0])
        t += 0.5
    if not xs:
        return [(0.0, 0.5)]
    runs = [[0]]
    for i in range(1, len(xs)):
        if abs(xs[i] - median(xs[j] for j in runs[-1])) > 0.08:
            runs.append([i])
        else:
            runs[-1].append(i)
    # a single odd sample mid-clip is a detection glitch, not a shot: fold it away
    runs = [r for k, r in enumerate(runs) if len(r) > 1 or k in (0, len(runs) - 1)]
    merged = [runs[0]]
    for r in runs[1:]:
        if abs(median(xs[j] for j in r) - median(xs[j] for j in merged[-1])) <= 0.08:
            merged[-1] += r
        else:
            merged.append(r)
    keys = [(0.0, median(xs[j] for j in merged[0]))]
    for prev, r in zip(merged, merged[1:]):
        cut = _shot_cut(cap, ts[prev[-1]], ts[r[0]])
        keys.append((round(cut - c["start"], 3), median(xs[j] for j in r)))
    return keys


# ---------------------------------------------------------------- screen motion
MOTION_T = 0.3  # 3-frame mean abs diff at 160x120; static UI ~0.003, clicks/loads > 1


def screen_motion(src):
    """Per-frame screen motion with any persistent webcam bubble masked out (a talking
    face moves constantly and would make every pause look 'active').
    Returns (f(a, b) -> peak motion between a and b seconds, mask box or None)."""
    import cv2, numpy as np
    cap = cv2.VideoCapture(str(src))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fd, boxes = None, []
    for k in range(8):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * (k + 0.5) / 8))
        ok, fr = cap.read()
        if not ok:
            continue
        h, w = fr.shape[:2]
        sm = fr  # full resolution: a webcam bubble face can be ~50 px, invisible at 640 wide
        if fd is None:
            fd = cv2.FaceDetectorYN.create(str(SF / "models" / "yunet.onnx"), "", (w, h), 0.6)
        _, f = fd.detect(sm)
        if f is not None and len(f):
            x, y, fw, fh = max(f, key=lambda b: b[2] * b[3])[:4]
            boxes.append(((x + fw / 2) / sm.shape[1], (y + fh / 2) / sm.shape[0], fw / sm.shape[1]))
    mask = None
    if len(boxes) >= 5:
        cx, cy, fw = (float(np.median([b[i] for b in boxes])) for i in range(3))
        if sum(abs(b[0] - cx) < 0.03 and abs(b[1] - cy) < 0.03 for b in boxes) >= 5:
            r = 1.75 * fw
            mask = (max(0, cx - r), max(0, cy - r * 4 / 3), min(1, cx + r), min(1, cy + r * 4 / 3))
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    prev, m = None, []
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        g = cv2.cvtColor(cv2.resize(fr, (160, 120)), cv2.COLOR_BGR2GRAY).astype(np.float32)
        if mask:
            g[int(mask[1] * 120):int(mask[3] * 120) + 1, int(mask[0] * 160):int(mask[2] * 160) + 1] = 0
        if prev is not None:
            m.append(float(np.abs(g - prev).mean()))
        prev = g
    cap.release()
    ms = np.convolve(np.array(m + [0.0]), np.ones(3) / 3, mode="same")

    def motion(a, b):
        i0, i1 = int(a * fps), int(b * fps)
        return float(ms[i0:i1].max()) if i1 > i0 else 0.0
    return motion, mask


# ---------------------------------------------------------------- tightening
_ENV = {}


def audio_env(src, hop=0.01):
    """RMS envelope of the source audio in 10 ms hops, plus a silence threshold."""
    key = str(src)
    if key not in _ENV:
        import numpy as np
        pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(src), "-map", "0:a:0", "-ac", "1",
                              "-ar", "16000", "-f", "s16le", "-"], capture_output=True).stdout
        a = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768
        n = int(16000 * hop)
        rms = np.sqrt((a[: len(a) // n * n].reshape(-1, n) ** 2).mean(axis=1) + 1e-12)
        _ENV[key] = (rms, hop, float(np.percentile(rms, 15)) * 2.5)
    return _ENV[key]


def quiet_edge(env, t, direction, limit):
    """From t, walk forward (+1) or back (-1) up to `limit` s to the first quiet hop.
    Whisper word edges can be ~50-100 ms off; this keeps cuts out of words."""
    rms, hop, thr = env
    i = int(t / hop)
    for k in range(int(limit / hop) + 1):
        j = i + direction * k
        if 0 <= j < len(rms) and rms[j] < thr:
            return j * hop
    return t


def tighten(clips, words, env, fillers=True, max_pause=0.2, motion=None):
    """Split each clip around filler words and over-long pauses. With `motion` (screen
    recordings), a pause is only cut when the screen is also still during it."""
    segs = []
    for c in clips:
        extra = {k: c[k] for k in ("track",) if k in c}
        ws = [w for w in words if c["start"] <= (w["s"] + w["e"]) / 2 <= c["end"]]
        keep = [w for w in ws if not (fillers and w.get("f"))]
        if not keep:
            # no speech in this clip: it was chosen for its picture (B-roll, a reaction shot),
            # so keep it whole instead of dropping it
            segs.append({"start": c["start"], "end": c["end"], **extra})
            continue
        # clip edges snap to the first / last REAL word: drops leading/trailing fillers and
        # noise even when Whisper didn't transcribe them (energy check keeps word onsets)
        start = max(c["start"], quiet_edge(env, keep[0]["s"], -1, 0.15) - 0.06)
        end = min(c["end"], quiet_edge(env, keep[-1]["e"], +1, 0.12) + 0.06)
        cur = start
        for p, n in zip(keep, keep[1:]):
            has_filler = fillers and any(w.get("f") and p["e"] - 0.01 <= w["s"] <= n["s"] for w in ws)
            gap = n["s"] - p["e"]
            if not has_filler and (max_pause is None or gap <= max_pause):
                continue
            if not has_filler and motion is not None and motion(p["e"], n["s"]) > MOTION_T:
                continue  # the screen is doing something during this pause: it's content, keep it
            qa = quiet_edge(env, p["e"], +1, 0.12)
            qb = quiet_edge(env, n["s"], -1, 0.15)
            keep_pad = 0.06 if has_filler else (max_pause or 0.2) / 2
            a, b = qa + keep_pad, qb - keep_pad
            if b - a > 0.08:
                segs.append({"start": cur, "end": a, **extra})
                cur = b
        segs.append({"start": cur, "end": end, **extra})
    return [s for s in segs if s["end"] - s["start"] >= 0.15]


# ---------------------------------------------------------------- captions
def ass_escape(s):
    return s.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def ts(t):
    t = max(0.0, t)
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def build_ass(words, clips, short, W, H, path):
    fixes = {k.lower(): v for k, v in short.get("word_fixes", {}).items()}

    def fix(w):
        core = w.rstrip(".,?!;:")
        return fixes.get(core.lower(), core) + w[len(core):]

    # remap source-time words onto the output timeline (fillers never get captions).
    # A word belongs to a clip if its MIDPOINT is inside: start-based matching dropped words
    # that begin a few ms before a clip edge ("You know" rendered as just "KNOW").
    out_words, off = [], 0.0
    for c in clips:
        for w in words:
            if w.get("f"):
                continue
            if c["start"] <= (w["s"] + w["e"]) / 2 <= c["end"]:
                t = fix(w["w"])
                if t.startswith("-") and out_words:  # "anti" + "-AI" -> "anti-AI" on one card
                    out_words[-1]["w"] += t
                    out_words[-1]["e"] = min(w["e"], c["end"]) - c["start"] + off
                    continue
                out_words.append({"w": t, "s": max(w["s"], c["start"]) - c["start"] + off,
                                  "e": min(w["e"], c["end"]) - c["start"] + off})
        off += c["end"] - c["start"]
    total = off

    chunks, cur = [], []
    for w in out_words:
        cur.append(w)
        if len(cur) >= 3 or (cur[-1]["e"] - cur[0]["s"]) > 1.3 or w["w"][-1:] in ".,?!;:":
            chunks.append(cur)
            cur = []
    if cur:
        chunks.append(cur)

    k = W / 1080
    cap_size, hook_size = int(84 * k), int(96 * k)
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 0", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Cap,Montserrat Black,{cap_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,"
        f"0,0,0,0,100,100,0,0,1,{int(7*k)},{int(3*k)},2,{int(80*k)},{int(80*k)},{int(560*k)},1",
        f"Style: Hook,Montserrat Black,{hook_size},&H00111111,&H00111111,&H00FFFFFF,&H00FFFFFF,"
        f"0,0,0,0,100,100,0,0,3,{int(28*k)},0,8,{int(90*k)},{int(90*k)},{int(300*k)},1",
        "", "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    hook = short.get("hook_text", "").strip()
    if hook:
        hs = min(short["hook_seconds"], total)
        lines.append(f"Dialogue: 2,{ts(0)},{ts(hs)},Hook,,0,0,0,,"
                     f"{{\\fad(120,180)}}{ass_escape(hook.upper())}")
    HI = "&H0000E5FF&"
    for ci, ch in enumerate(chunks):
        end_chunk = chunks[ci + 1][0]["s"] if ci + 1 < len(chunks) else ch[-1]["e"] + 0.3
        end_chunk = min(end_chunk, ch[-1]["e"] + 0.6)
        for wi, w in enumerate(ch):
            s = w["s"] if wi else ch[0]["s"]
            e = ch[wi + 1]["s"] if wi + 1 < len(ch) else end_chunk
            txt = " ".join(
                (f"{{\\c{HI}}}{ass_escape(x['w'].upper())}{{\\c&H00FFFFFF&}}" if j == wi
                 else ass_escape(x["w"].upper())) for j, x in enumerate(ch))
            lines.append(f"Dialogue: 1,{ts(s)},{ts(e)},Cap,,0,0,0,,{txt}")
    Path(path).write_text("\n".join(lines) + "\n")
    return total


# ---------------------------------------------------------------- color
HDR_TRC = {"arib-std-b67", "smpte2084"}  # HLG (iPhone), PQ (HDR10)
TONEMAP = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
           "tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p")


def source_transfer(src):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=color_transfer", "-of", "csv=p=0", str(src)], capture_output=True, text=True)
    return out.stdout.strip().strip(",").strip()  # csv output carries a trailing comma


# ---------------------------------------------------------------- encode
# encoder name -> (ffmpeg encode args, matching hardware-decode args)
ENCODERS = {
    "nvenc": (["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "21", "-b:v", "0"], ["-hwaccel", "cuda"]),
    "videotoolbox": (["-c:v", "h264_videotoolbox", "-q:v", "65", "-allow_sw", "0"], ["-hwaccel", "videotoolbox"]),
}


def _encoder_works(codec):
    t = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=s=256x256:d=0.1",
                        "-c:v", codec, "-f", "null", "-"], capture_output=True)
    return t.returncode == 0


def pick_encoder():
    """The hardware H.264 encoder that actually works here: nvenc (NVIDIA), videotoolbox
    (Apple Silicon), else libx264 on the CPU. CUTCANNON_ENCODER=nvenc|videotoolbox|x264 overrides."""
    forced = os.environ.get("CUTCANNON_ENCODER")
    if forced in ("nvenc", "videotoolbox", "x264"):
        return forced
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    except Exception:
        return "x264"
    for name, codec in (("nvenc", "h264_nvenc"), ("videotoolbox", "h264_videotoolbox")):
        if codec in out and _encoder_works(codec):
            return name
    return "x264"


def has_nvenc():  # kept for older callers
    return pick_encoder() == "nvenc"


def two_pass_loudnorm(mp4, I=-14.0, TP=-2.0, LRA=11):
    """Measure, then re-apply loudnorm linearly; video stream is copied untouched.
    TP -2.0 (not -1.5) leaves headroom for the inter-sample peaks AAC encoding adds."""
    m = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-vn", "-i", str(mp4), "-af",
                        f"loudnorm=I={I}:TP={TP}:LRA={LRA}:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    j = json.loads(m[m.rindex("{"):m.rindex("}") + 1])
    af = (f"loudnorm=I={I}:TP={TP}:LRA={LRA}:measured_I={j['input_i']}:measured_TP={j['input_tp']}:"
          f"measured_LRA={j['input_lra']}:measured_thresh={j['input_thresh']}:"
          f"offset={j['target_offset']}:linear=true")
    tmp = mp4.with_suffix(".ln.mp4")
    r = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(mp4),
                        "-c:v", "copy", "-af", af, "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
                        "-movflags", "+faststart", str(tmp)], capture_output=True, text=True)
    if r.returncode == 0:
        tmp.replace(mp4)
    else:
        tmp.unlink(missing_ok=True)
        print("    loudnorm pass 2 failed; kept single-pass audio")


def rescan_fillers(d, src, clips):
    """On long recordings Whisper's disfluency prompt only shapes the first 30 s window, so
    most um/uh never get flagged, and neighbouring words get stretched over them. For each
    chosen clip range (<=25 s chunks, 0.5 s audio margin), re-transcribe with the prompt and
    REPLACE the long-file words in that range with the rescan's tighter-timed words.
    Plans freeze resolved seconds, so this never changes what a saved version cuts.
    Scanned ranges are recorded in transcript.json and not redone."""
    import numpy as np
    import asr
    from transcribe import PROMPT, FILLER
    tf = d / "transcript.json"
    tr = json.loads(tf.read_text())
    done = tr.setdefault("rescanned", [])
    todo = []
    for c in clips:
        t = c["start"]
        while t < c["end"] - 0.05:
            e = min(t + 25, c["end"])
            if not any(a <= t + 0.01 and e <= b + 0.01 for a, b in done):
                todo.append((t, e))
            t = e
    added = 0
    for a, b in todo:
        a0 = max(0.0, a - 0.5)
        pcm = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{a0:.3f}", "-t", f"{b + 0.5 - a0:.3f}",
                              "-i", str(src), "-map", "0:a:0", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                             capture_output=True).stdout
        audio = np.frombuffer(pcm, np.int16).astype(np.float32) / 32768
        segs = asr.transcribe(audio, prompt=PROMPT, vad=True)  # VAD: no phantom words over B-roll/music
        new = []
        for s in segs:
            for w in (s.words or []):
                txt, ws, we = w.word.strip(), a0 + w.start, a0 + w.end
                if txt and a <= ws < b:
                    nw = {"w": txt, "s": round(ws, 3), "e": round(we, 3), "p": round(w.probability, 3), "rescan": True}
                    if FILLER.match(txt):
                        nw["f"] = True
                        added += 1
                    new.append(nw)
        old = [x for x in tr["words"] if a <= x["s"] < b]
        if new:  # a silent/failed rescan never deletes the original words
            for nw in new:  # keep line ids so transcript lines stay meaningful
                if old:
                    nw["line"] = min(old, key=lambda x: abs(x["s"] - nw["s"])).get("line")
            tr["words"] = [x for x in tr["words"] if not (a <= x["s"] < b)] + new
        done.append([round(a, 3), round(b, 3)])
    if todo:
        tr["words"].sort(key=lambda x: x["s"])
        tf.write_text(json.dumps(tr, indent=1))
    return tr["words"], added, len(todo)


def render_short(d, meta, words, short, ver, preview, enc):
    T, t0 = {}, time.time()
    src = P.source(d)
    trc = source_transfer(src)
    hdr = trc in HDR_TRC
    fmt = short.get("format", "vertical")
    if fmt == "source":  # keep the original frame: full-video cleanup, no crop
        W, H = meta["width"] // 2 * 2, meta["height"] // 2 * 2
        if preview:
            W, H = W // 4 * 2, H // 4 * 2
    else:
        W, H = (540, 960) if preview else (1080, 1920)
    fps = meta["fps"] or 30
    # output at the source frame rate, so cut points (snapped to source frames) land exactly on
    # output frames; 23.976 fps footage at a forced 30 fps drifted ~0.4 s over 34 cuts
    fps_out = fps if 15 <= fps <= 60 else 30.0

    # 1. tighten: split clips around fillers / long pauses
    tg = short.get("tighten") or {}
    if tg.get("fillers"):
        words, added, scanned = rescan_fillers(d, src, short["clips"])
        if scanned:
            print(f"    filler rescan: {scanned} chunk(s) scanned, {added} filler(s) found")
    if tg.get("fillers") or tg.get("max_pause"):
        motion = None
        if fmt == "source":
            motion, mbox = screen_motion(src)
            print(f"    screen-motion guard on (webcam mask {'at ' + str(tuple(round(v, 2) for v in mbox)) if mbox else 'none'})")
        segs = tighten(short["clips"], words, audio_env(src), tg.get("fillers", False), tg.get("max_pause"), motion)
    else:
        segs = [dict(c) for c in short["clips"]]
    # 2. snap every cut to a source frame so audio and video trims are identical
    clips = []
    for c in segs:
        s, e = round(round(c["start"] * fps) / fps, 4), round(round(c["end"] * fps) / fps, 4)
        if e - s >= 3 / fps:
            clips.append({**c, "start": s, "end": e, "n": round((e - s) * fps_out)})
    planned = short["duration"]
    # each segment is exactly n output frames, with audio trimmed to exactly n frames' length,
    # so audio and video can never drift apart, however many cuts there are
    short = {**short, "clips": clips, "duration": round(sum(c["n"] for c in clips) / fps_out, 3)}

    sw, sh = meta["width"], meta["height"]
    vertical = sw / sh <= 9 / 16 + 0.01
    cw = sw if vertical else int(sh * 9 / 16) // 2 * 2
    # crop keyframes per segment: follow the tracked person through camera switches
    FIXED = {"center": 0.5, "left": 0.3, "right": 0.7}
    if vertical or fmt == "source":
        keys = [[(0.0, 0.5)] for _ in clips]
    elif short["reframe"] in FIXED:
        keys = [[(0.0, FIXED[short["reframe"]])] for _ in clips]
    else:
        import cv2
        cap, det = cv2.VideoCapture(str(src)), _faces()
        keys = [crop_track(cap, det, c, c.get("track", "largest")) for c in clips]
        cap.release()

    tag = f"{short['id']}_v{ver:03d}" + ("_preview" if preview else "")
    ass = d / "renders" / f"{tag}.ass"
    use_ass = bool(short.get("captions", True) or short.get("hook_text", "").strip())
    if use_ass:
        build_ass(words if short.get("captions", True) else [], clips, short, W, H, ass)
    T["prep"] = time.time() - t0

    # 3. one seeked input per segment: decodes only what is used
    inputs = []
    for c in clips:
        hw = ENCODERS[enc][1] if enc in ENCODERS else []
        inputs += [*hw, "-ss", f"{c['start']:.4f}", "-t", f"{c['end'] - c['start'] + 0.1:.4f}", "-i", str(src)]
    pw, ph = int(W * PUNCH) // 2 * 2, int(H * PUNCH) // 2 * 2
    fc = []
    for i, (c, kf) in enumerate(zip(clips, keys)):
        if fmt == "source":
            geo = f"scale={W}:{H}"
        elif vertical:
            geo = f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2"
        else:
            px = lambda x: int(min(max(x * sw - cw / 2, 0), sw - cw))  # noqa: E731
            cx = str(px(kf[-1][1]))
            for k in range(len(kf) - 1, 0, -1):  # piecewise crop x, switching on the cut frame
                cx = f"if(lt(t\\,{kf[k][0]:.3f})\\,{px(kf[k - 1][1])}\\,{cx})"
            geo = f"crop={cw}:{sh}:{cx}:0,scale={W}:{H}"
        if short.get("punch_in") and fmt == "vertical" and i % 2 == 1:
            geo += f",scale={pw}:{ph},crop={W}:{H}:(iw-{W})/2:(ih-{H})/2"
        tm = TONEMAP + "," if hdr else ""
        fc.append(f"[{i}:v:0]setpts=PTS-STARTPTS,{tm}{geo},setsar=1,fps={fps_out:.6f},"
                  f"tpad=stop_mode=clone:stop=3,trim=end_frame={c['n']},setpts=PTS-STARTPTS[v{i}]")
        dur = c["n"] / fps_out
        fc.append(f"[{i}:a:0]asetpts=PTS-STARTPTS,aresample=48000,apad,atrim=end={dur:.6f},asetpts=PTS-STARTPTS,"
                  f"afade=t=in:d=0.02,afade=t=out:st={max(dur-0.02,0):.3f}:d=0.02[a{i}]")
    n = len(clips)
    fc.append("".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[vc][ac]")
    fc.append(f"[vc]subtitles={ass.name}:fontsdir={FONTS}[vout]" if use_ass else "[vc]null[vout]")
    au = short.get("audio") or {}
    pre = ([f"highpass=f={au['highpass']}"] if au.get("highpass") else []) + \
          (["afftdn=nf=-25"] if au.get("denoise") else []) + \
          (["acompressor=threshold=-24dB:ratio=2.5:attack=15:release=250:makeup=2"] if au.get("compress") else [])
    fc.append(f"[ac]{','.join(pre + ['loudnorm=I=-14:TP=-2.0:LRA=11'])}[aout]")

    outp = d / "renders" / f"{tag}.mp4"
    venc = (ENCODERS[enc][0] if enc in ENCODERS
            else ["-c:v", "libx264", "-preset", "veryfast" if preview else "medium", "-crf", "20"])
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *inputs,
           "-filter_complex", ";".join(fc), "-map", "[vout]", "-map", "[aout]",
           *venc, "-pix_fmt", "yuv420p",
           "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709", "-color_range", "tv",
           "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart", str(outp)]
    t = time.time()
    r = subprocess.run(cmd, cwd=d / "renders", capture_output=True, text=True)
    if r.returncode:
        print(r.stderr[-2000:])
        sys.exit(f"render failed: {short['id']}")
    T["encode"] = time.time() - t
    t = time.time()
    two_pass_loudnorm(outp)
    T["loudnorm"] = time.time() - t

    info = {"source_transfer": trc, "tonemapped": hdr, "encoder": enc,
            "planned_s": planned, "final_s": short["duration"], "segments": n,
            # the exact segments used, so a later standalone QA run checks what was rendered
            "clips": [{"start": c["start"], "end": c["end"], "n": c["n"]} for c in clips],
            "tighten": tg, "punch_in": bool(short.get("punch_in")), "format": fmt, "audio": au,
            "crop_keyframes": [[(round(t, 2), round(x, 3)) for t, x in kf] for kf in keys]}
    info_f = d / "renders" / f"{tag}_render.json"
    info_f.write_text(json.dumps(info))
    print(f"  {outp.name}  {planned:.1f}s -> {short['duration']:.1f}s  ({n} segments"
          f"{', punch-in' if short.get('punch_in') else ''})  "
          f"{enc}{'  HDR->SDR' if hdr else ''}")

    import qa
    sw_n = sum(len(k) - 1 for k in keys)
    if sw_n:
        print(f"    tracked {sw_n} camera switch(es): " + "; ".join(
            f"seg{i}@{t:.2f}s->x{x:.2f}" for i, kf in enumerate(keys) for t, x in kf[1:]))
    t = time.time()
    qa.run(d, short, outp, tag)
    T["qa"] = time.time() - t
    total = sum(T.values())
    info["timings_s"] = {k: round(v, 1) for k, v in T.items()} | {"total": round(total, 1),
                                                                  "x_realtime": round(total / short["duration"], 2)}
    info_f.write_text(json.dumps(info, indent=2))
    print(f"    time: prep {T['prep']:.1f}s | encode {T['encode']:.1f}s | loudnorm {T['loudnorm']:.1f}s"
          f" | qa {T['qa']:.1f}s | total {total:.1f}s = {total / short['duration']:.2f}x the video length")
    return outp


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    d = P.proj_dir(args.pop(0))
    preview = "--preview" in args
    if preview:
        args.remove("--preview")
    ver = P.current(d)
    if "--version" in args:
        i = args.index("--version")
        ver = int(args[i + 1].lstrip("v"))
        del args[i:i + 2]
    if not ver:
        sys.exit("no plan yet - plan.py save first")
    res, probs = P.resolve(d, P.load(d, ver))
    if probs:
        sys.exit("plan problems:\n  " + "\n  ".join(probs))
    meta = json.loads((d / "meta.json").read_text())
    words = json.loads((d / "transcript.json").read_text())["words"]
    enc = pick_encoder()
    shorts = [s for s in res["shorts"] if not args or s["id"] in args]
    print(f"rendering v{ver:03d}: {len(shorts)} short(s){' [preview]' if preview else ''}")
    t = time.time()
    for s in shorts:
        render_short(d, meta, words, s, ver, preview, enc)
    print(f"all done in {time.time() - t:.1f}s")


if __name__ == "__main__":
    main()
