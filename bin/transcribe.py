#!/usr/bin/env python3
"""transcribe.py <project | video> [--name NAME] [--model medium.en]

Two ways in:
  transcribe.py product-demo                  media already in projects/product-demo/
  transcribe.py ~/Downloads/take.mov        creates projects/take/ and MOVES the file
                                            (and a same-named .vtt/.srt) into it
Writes into the project folder:
  transcript.json     words with start/end times (seconds); fillers flagged "f"
  transcript.txt      numbered lines "[L012 83.42-88.10] text" for Claude to read
  meta.json           source file name, duration, width, height, fps
"""
import argparse, json, os, re, shutil, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import plan as P  # noqa: E402

SF = P.SF

# Whisper drops disfluencies unless the prompt shows them; this keeps um/uh in the
# transcript so they can be seen, flagged and cut.
PROMPT = "Umm, let me think like, hmm... Okay, here's what I'm, like, thinking. Uh, so, you know, um."
FILLER = re.compile(r"^(um+|uh+|uhm+|hmm+|mm+|ah+|er+|erm+)[,.?!]*$", re.I)


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "project"


def probe(path):
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate:format=duration",
        "-of", "json", str(path)])
    j = json.loads(out)
    s = j["streams"][0]
    num, den = s["r_frame_rate"].split("/")
    return {"width": s["width"], "height": s["height"],
            "fps": round(float(num) / float(den), 3),
            "duration": float(j["format"]["duration"])}


def resolve_target(target, name):
    """Return (project_dir, source_path), moving an outside file into its project."""
    t = Path(target).expanduser()
    if t.is_file():
        proj = SF / "projects" / (name or slug(t.stem))
        proj.mkdir(parents=True, exist_ok=True)
        if t.resolve().parent == proj.resolve():
            return proj, t
        dest = proj / t.name
        if dest.exists():
            sys.exit(f"{dest} already exists - not overwriting")
        shutil.move(str(t), dest)
        print(f"moved {t} -> {dest}")
        for ext in (".vtt", ".srt"):  # a transcript that came with the recording
            side = t.with_suffix(ext)
            if side.exists() and not (proj / side.name).exists():
                shutil.move(str(side), proj / side.name)
                print(f"moved {side.name} along with it")
        return proj, dest
    proj = t if t.is_dir() else SF / "projects" / target
    if not proj.is_dir():
        sys.exit(f"no project folder {proj} and no file {t}.\n"
                 f"Create projects/<name>/, put the recording in it, then: transcribe.py <name>")
    return proj, P.source(proj)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("target", help="project name, project folder, or path to a video")
    ap.add_argument("--name", help="project name when importing a video (default: from file name)")
    ap.add_argument("--model", default="medium.en")
    a = ap.parse_args()

    proj, src = resolve_target(a.target, a.name)
    (proj / "plans").mkdir(exist_ok=True)
    (proj / "renders").mkdir(exist_ok=True)
    meta = {"source": src.name, **probe(src)}
    (proj / "meta.json").write_text(json.dumps(meta, indent=2))

    import asr
    t0 = time.time()
    segs = asr.transcribe(str(src), prompt=PROMPT, vad=True, model=a.model)

    # one "line" per sentence (or per 0.6s+ pause), so cuts are sentence-precise
    lines, words, cur = [], [], []

    def flush():
        if not cur:
            return
        lid = f"L{len(lines):03d}"
        for w in cur:
            w["line"] = lid
        lines.append({"id": lid, "s": cur[0]["s"], "e": cur[-1]["e"],
                      "text": " ".join(f"({w['w']})" if w.get("f") else w["w"] for w in cur)})
        cur.clear()

    for s in segs:
        for w in (s.words or []):
            t = w.word.strip()
            if not t:
                continue
            ww = {"w": t, "s": round(w.start, 3), "e": round(w.end, 3), "p": round(w.probability, 3)}
            if FILLER.match(t):
                ww["f"] = True
            if cur and ww["s"] - cur[-1]["e"] > 0.6:
                flush()
            cur.append(ww)
            words.append(ww)
            if t[-1] in ".?!":
                flush()
    flush()

    (proj / "transcript.json").write_text(json.dumps({"lines": lines, "words": words}, indent=1))
    with open(proj / "transcript.txt", "w") as f:
        f.write(f"# {proj.name}  source={src.name}  duration={meta['duration']:.1f}s  "
                f"{meta['width']}x{meta['height']}@{meta['fps']}\n")
        prev = 0.0
        for L in lines:
            gap = L["s"] - prev
            if gap > 1.5:
                f.write(f"   ...pause {gap:.1f}s\n")
            f.write(f"[{L['id']} {L['s']:.2f}-{L['e']:.2f}] {L['text']}\n")
            prev = L["e"]
    nf = sum(1 for w in words if w.get("f"))
    print(f"project: {proj}")
    print(f"{len(lines)} lines, {len(words)} words ({nf} fillers, shown as (um)), {meta['duration']:.1f}s source, "
          f"transcribed in {time.time()-t0:.1f}s with {asr.describe(a.model)}")


if __name__ == "__main__":
    main()
