#!/usr/bin/env python3
"""qa.py <proj> [short_id ...] [--version vN] [--preview]

Checks a rendered short and writes, next to the render:
  <tag>_qa.json     sync, duration, loudness, caption coverage, hook card, face framing
  <tag>_frames.png  contact sheet: hook, 25%, 50%, 75%, end
render.py runs this automatically after every render.
"""
import json, re, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import plan as P  # noqa: E402

LUFS_TARGET, LUFS_TOL, TP_MAX = -14.0, 1.5, -1.0


def stream_durations(mp4):
    """Measure what actually DECODES, not container metadata: AAC priming/padding makes
    the audio stream's stated duration ~0.1s longer than the sound it contains."""
    out = subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
                                   "-show_entries", "stream=nb_read_packets,r_frame_rate", "-of", "json", str(mp4)])
    s = json.loads(out)["streams"][0]
    n, d = map(int, s["r_frame_rate"].split("/"))
    vd = int(s["nb_read_packets"]) * d / n
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(mp4), "-map", "0:a:0",
                          "-f", "s16le", "-ac", "1", "-ar", "48000", "-"], capture_output=True).stdout
    ad = len(pcm) / 2 / 48000
    return vd, ad, max(vd, ad)


def loudness(mp4):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-vn", "-i", str(mp4),
                        "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True)
    err = r.stderr
    i = re.findall(r"I:\s+(-?[\d.]+) LUFS", err)
    tp = re.findall(r"Peak:\s+(-?[\d.]+) dBFS", err)
    lra = re.findall(r"LRA:\s+(-?[\d.]+) LU\b", err)
    loudness.lra = float(lra[-1]) if lra else None
    return (float(i[-1]) if i else None), (float(tp[-1]) if tp else None)


def ass_events(ass_path):
    def t(s):
        h, m, sec = s.split(":")
        return int(h) * 3600 + int(m) * 60 + float(sec)
    ev = []
    for line in Path(ass_path).read_text().splitlines():
        if line.startswith("Dialogue:"):
            f = line.split(",", 9)
            ev.append({"start": t(f[1]), "end": t(f[2]), "style": f[3]})
    return ev


def merge(iv):
    iv = sorted(iv)
    out = []
    for s, e in iv:
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out


def overlap(a, b):
    tot = 0.0
    for s1, e1 in a:
        for s2, e2 in b:
            tot += max(0.0, min(e1, e2) - max(s1, s2))
    return tot


def speech_intervals(words, clips):
    iv, off = [], 0.0
    for c in clips:
        for w in words:
            if w.get("f"):
                continue  # fillers are never captioned
            if c["start"] <= (w["s"] + w["e"]) / 2 <= c["end"]:  # same midpoint rule as render
                iv.append((max(w["s"], c["start"]) - c["start"] + off, min(w["e"], c["end"]) - c["start"] + off))
        off += c["end"] - c["start"]
    return merge(iv)


def remaining_fillers(mp4):
    """Re-transcribe the finished render with the disfluency prompt; list fillers left in."""
    import asr
    from transcribe import PROMPT, FILLER
    segs = asr.transcribe(str(mp4), prompt=PROMPT)
    return [round(w.start, 2) for s in segs for w in (s.words or []) if FILLER.match(w.word.strip())]


def run(d, short, mp4, tag):
    import cv2
    import render as R
    mp4, rdir = Path(mp4), Path(mp4).parent
    words = json.loads((d / "transcript.json").read_text())["words"]
    checks, notes = {}, []

    # sync + duration
    vd, ad, fd = stream_durations(mp4)
    drift = abs(vd - ad)
    checks["av_sync"] = {"video_s": round(vd, 3), "audio_s": round(ad, 3),
                         "drift_ms": round(drift * 1000), "pass": drift <= 0.045}  # ~1 frame at 30fps
    exp = short["duration"]
    checks["duration"] = {"expected_s": exp, "actual_s": round(fd, 2),
                          "pass": abs(fd - exp) <= 0.25 and (fd <= 60.5 or short.get("format") == "source")}

    # color: output must be tagged SDR BT.709 8-bit (HDR tags on 8-bit = washed out or banded)
    cj = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
        "stream=pix_fmt,color_transfer,color_primaries,color_space", "-of", "json", str(mp4)]))["streams"][0]
    trc = cj.get("color_transfer", "unknown")
    info_f = rdir / f"{tag}_render.json"
    info = json.loads(info_f.read_text()) if info_f.exists() else {}
    src_hdr = info.get("source_transfer") in ("arib-std-b67", "smpte2084")
    tags_ok = cj.get("pix_fmt") == "yuv420p" and trc in ("bt709", "unknown")
    pixels_ok = (not src_hdr) or info.get("tonemapped") is True
    checks["color"] = {"pix_fmt": cj.get("pix_fmt"), "transfer": trc,
                       "source_transfer": info.get("source_transfer"), "tonemapped": info.get("tonemapped"),
                       "pass": tags_ok and pixels_ok and bool(info)}
    if not info:
        notes.append("no render record - re-render to verify color processing")
    elif src_hdr and not info.get("tonemapped"):
        notes.append("HDR source was not tone-mapped - colors will look flat")

    # loudness
    i, tp = loudness(mp4)
    checks["loudness"] = {"integrated_lufs": i, "true_peak_dbfs": tp, "lra_lu": loudness.lra,
                          "target_lufs": LUFS_TARGET,
                          "pass": i is not None and abs(i - LUFS_TARGET) <= LUFS_TOL
                          and tp is not None and tp <= TP_MAX}

    # captions + hook card
    ass = rdir / f"{tag}.ass"
    ev = ass_events(ass) if ass.exists() else []
    caps = merge([(e["start"], e["end"]) for e in ev if e["style"] == "Cap"])
    speech = speech_intervals(words, short["clips"])
    sp_total = sum(e - s for s, e in speech)
    cov = overlap(speech, caps) / sp_total if sp_total else 0.0
    gaps = [round(s, 2) for s, e in speech if overlap([[s, e]], caps) < 0.5 * (e - s)]
    checks["captions"] = {"speech_s": round(sp_total, 2), "coverage": round(cov, 3),
                          "uncaptioned_at_s": gaps[:10],
                          "pass": (cov >= 0.95) if short.get("captions", True) else None}
    hook = [e for e in ev if e["style"] == "Hook"]
    has_hook = bool(short.get("hook_text", "").strip())
    checks["hook_card"] = {"expected": has_hook, "present": bool(hook),
                           "shown_s": [round(hook[0]["start"], 2), round(hook[0]["end"], 2)] if hook else None,
                           "pass": bool(hook) == has_hook}

    # fillers: only judged when the plan asked for them to be cut
    tg = short.get("tighten") or {}
    fl = remaining_fillers(mp4)
    checks["fillers"] = {"remaining": len(fl), "at_s": fl[:10],
                         "pass": (len(fl) <= 1) if tg.get("fillers") else None}

    # frames + face framing
    times = [min(short["hook_seconds"] / 2, fd / 2), fd * .25, fd * .5, fd * .75, max(fd - 0.5, 0)]
    cap = cv2.VideoCapture(str(mp4))
    det = R._detector()
    thumbs, faces = [], []
    for t in times:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, fr = cap.read()
        if not ok:
            continue
        x = det(fr)
        faces.append(None if x is None else round(x, 2))
        th = cv2.resize(fr, (270, int(270 * fr.shape[0] / fr.shape[1])))
        cv2.putText(th, f"{t:.1f}s", (8, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 229, 255), 2)
        thumbs.append(th)
    cap.release()
    sheet = rdir / f"{tag}_frames.png"
    if thumbs:
        import numpy as np
        cv2.imwrite(str(sheet), np.hstack(thumbs))
    found = [x for x in faces if x is not None]
    if short.get("format") == "source":
        checks["framing"] = {"face_x": faces, "pass": None}  # original frame, nothing cropped
    elif not found:
        checks["framing"] = {"face_x": faces, "pass": None}
        notes.append("no face detected in sampled frames - framing not checked")
    else:
        off = [x for x in found if abs(x - 0.5) > 0.3]
        checks["framing"] = {"face_x": faces, "pass": not off}
        if off:
            notes.append("face near frame edge - try reframe left/right/center")

    verdicts = [c["pass"] for c in checks.values() if c["pass"] is not None]
    report = {"render": mp4.name, "short": short["id"], "pass": all(verdicts),
              "checks": checks, "notes": notes, "frames": sheet.name if thumbs else None}
    (rdir / f"{tag}_qa.json").write_text(json.dumps(report, indent=2))

    flags = " ".join(f"{k}={'ok' if v['pass'] else ('n/a' if v['pass'] is None else 'FAIL')}"
                     for k, v in checks.items())
    print(f"    QA {'PASS' if report['pass'] else 'FAIL'}: {flags}"
          f"  (LUFS {i}, TP {tp}, captions {cov:.0%})")
    for n in notes:
        print(f"    note: {n}")
    return report


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
    res, _ = P.resolve(d, P.load(d, ver))
    for s in res["shorts"]:
        if args and s["id"] not in args:
            continue
        tag = f"{s['id']}_v{ver:03d}" + ("_preview" if preview else "")
        mp4 = d / "renders" / f"{tag}.mp4"
        if not mp4.exists():
            print(f"  {tag}: not rendered")
            continue
        print(f"  {tag}")
        run(d, s, mp4, tag)


if __name__ == "__main__":
    main()
