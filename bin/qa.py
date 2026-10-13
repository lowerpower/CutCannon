#!/usr/bin/env python3
"""qa.py <proj> [short_id ...] [--version vN] [--preview]

Checks a rendered short and writes, next to the render:
  <tag>_qa.json     sync, duration, color, loudness, captions, hook card, fillers, joins, framing
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


def retranscribe(mp4):
    """Transcribe the finished render once, with the disfluency prompt (so fillers show up).
    Used by the fillers and joins checks."""
    import asr
    from transcribe import PROMPT
    segs = asr.transcribe(str(mp4), prompt=PROMPT, vad=True)  # VAD: no phantom words over music
    return [{"w": w.word.strip(), "s": w.start, "e": w.end} for s in segs for w in (s.words or [])
            if w.word.strip()]


def remaining_fillers(heard):
    from transcribe import FILLER
    return [round(w["s"], 2) for w in heard if FILLER.match(w["w"])]


JOIN_WIN = 0.35   # a word problem this close to a join (s) is blamed on the join


def _tokens(words):
    """Comparable tokens with times: lowercase, punctuation dropped, '15,000' == '15000',
    hyphenated / multi-word strings split."""
    merged = []
    for w in words:  # continuation tokens join the previous word, as in the captions
        if merged and re.match(r"^(-|,\d)", w["w"]):
            merged[-1] = {**merged[-1], "w": merged[-1]["w"] + w["w"], "e": w["e"]}
        else:
            merged.append(w)
    out = []
    for w in merged:
        for t in re.split(r"[\s\-]+", w["w"].lower()):
            t = re.sub(r"[^\w']", "", t.replace(",", "")).strip("'")
            if t:
                out.append((t, w["s"], w["e"]))
    return out


def join_audit(words, short, heard, total):
    """Compare what the render SHOULD say (the transcript words kept, on the output timeline)
    with what a fresh transcription of the render DOES say, and blame differences that sit on a
    join: a word missing there was clipped by the cut; an unexpected word there is a doubled
    word, a cut-off fragment, or a filler stub. Differences away from joins are transcription
    noise and ignored. Also lists the words either side of every edit (a join between two
    different plan clips) so a reviewer can judge whether the thought connects."""
    import difflib
    import render as R
    from transcribe import FILLER
    clips = short["clips"]
    if not clips or not all("n" in c for c in clips):
        # no record of the segments actually rendered (a render from before render logs kept
        # them): the joins can't be located, so don't guess
        return {"joins": None, "edits": [], "issues": [], "pass": None,
                "note": "render predates segment logging - re-render to audit joins"}
    expected, _ = R.caption_words(words, clips, {**short, "word_fixes": {}})
    exp, got = _tokens(expected), _tokens([w for w in heard if not FILLER.match(w["w"])])
    # join times on the output timeline (render segments are exactly n frames when known)
    k = total / sum(c["n"] for c in clips)
    lens = [c["n"] * k for c in clips]
    joins, t = [], 0.0
    for i, (a, b) in enumerate(zip(clips, clips[1:])):
        t += lens[i]
        if "clip" in a and "clip" in b and a["clip"] is not None and b["clip"] is not None:
            edit = a["clip"] != b["clip"]
        else:  # older render log: an edit jumps backwards or skips over a second or more
            edit = b["start"] < a["end"] or b["start"] - a["end"] > 1.0
        joins.append({"at_s": round(t, 2), "edit": edit})

    def near(t0, t1):
        return [j for j in joins if t0 - JOIN_WIN <= j["at_s"] <= t1 + JOIN_WIN]

    issues = []
    sm = difflib.SequenceMatcher(None, [x[0] for x in exp], [x[0] for x in got], autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        miss, extra = exp[i1:i2], got[j1:j2]
        span = miss or extra
        js = near(min(x[1] for x in span), max(x[2] for x in span))
        if not js:
            continue
        kind = {"delete": "missing", "insert": "extra", "replace": "changed"}[op]
        # a doubled word reads as an insert equal to its neighbour
        if op == "insert" and j1 > 0 and got[j1][0] == got[j1 - 1][0]:
            kind = "doubled"
        # the speaker repeats words across the join ("it's, it's saved, saved") and the fresh
        # transcription tidied the repeat away: a stutter worth hearing, not a clipped word
        if op == "delete":
            near_exp = {x[0] for x in exp[max(0, i1 - len(miss)):i1] + exp[i2:i2 + len(miss)]}
            if all(x[0] in near_exp for x in miss):
                kind = "repeat"
        issues.append({"at_s": js[0]["at_s"], "kind": kind,
                       "expected": " ".join(x[0] for x in miss), "heard": " ".join(x[0] for x in extra)})

    shown, _ = R.caption_words(words, clips, short)  # as captioned (word_fixes applied)

    def ctx(t0, n=5):
        before = [w["w"] for w in shown if (w["s"] + w["e"]) / 2 < t0][-n:]
        after = [w["w"] for w in shown if (w["s"] + w["e"]) / 2 >= t0][:n]
        return f"{' '.join(before)} | {' '.join(after)}"

    edits = [{"at_s": j["at_s"], "words": ctx(j["at_s"])} for j in joins if j["edit"]]
    # 'changed' near a join is usually a mis-hearing, so it's reported but doesn't fail QA
    bad = [x for x in issues if x["kind"] in ("missing", "extra", "doubled")]
    return {"joins": len(joins), "edits": edits, "issues": issues, "pass": not bad}


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
    heard = retranscribe(mp4)
    fl = remaining_fillers(heard)
    checks["fillers"] = {"remaining": len(fl), "at_s": fl[:10],
                         "pass": (len(fl) <= 1) if tg.get("fillers") else None}

    # joins: clipped / doubled / stray words at cuts; words either side of every edit
    checks["joins"] = join_audit(words, short, heard, fd)
    for x in checks["joins"]["issues"]:
        if x["kind"] != "changed":
            notes.append(f"join at {x['at_s']}s: {x['kind']} word(s) "
                         f"(expected '{x['expected']}', heard '{x['heard']}')")
    if checks["joins"].get("note"):
        notes.append(checks["joins"]["note"])

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
        info_f = d / "renders" / f"{tag}_render.json"
        if info_f.exists():  # check against the tightened segments the render actually used
            info = json.loads(info_f.read_text())
            if info.get("clips"):
                s = {**s, "clips": info["clips"], "duration": info["final_s"]}
        print(f"  {tag}")
        run(d, s, mp4, tag)


if __name__ == "__main__":
    main()
