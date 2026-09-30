#!/usr/bin/env python3
"""plan.py - versioned edit plans. Plans are immutable; CURRENT points at one.

  plan.py save    <proj> <draft.json> [--note "..."]   validate + store as next version
  plan.py list    <proj>                               history
  plan.py show    <proj> [vN]                          resolved plan (times, durations)
  plan.py undo    <proj>                               CURRENT -> parent version
  plan.py use     <proj> vN                            CURRENT -> vN
  plan.py approve <proj> [short_id ...]                record approval of CURRENT

Draft format (Claude writes this):
{
  "note": "why this version exists",
  "shorts": [{
    "id": "s1",
    "title": "internal name",
    "hook_text": "Big text on the hook card",
    "hook_seconds": 2.5,
    "reframe": "face" | "center" | "left" | "right",
    "clips": [ {"from": "L004", "to": "L007"},        # whole transcript lines
               {"start": 41.20, "end": 47.85} ],      # or exact seconds
    "trim": {"head": 0.0, "tail": 0.0},              # optional, applied per clip
    "tighten": {"fillers": true, "max_pause": 0.2},   # default: cut um/uh, cap pauses
    "punch_in": true                                   # default: alternate zoom at cuts
  }]
}
save fills tighten/punch_in defaults and freezes the resolved clip times into the
version (_resolved), so re-transcribing never changes what an old version renders.
"""
import json, os, sys, time
from pathlib import Path

# repo root: $CUTCANNON if set, else wherever this checkout lives
SF = Path(os.environ.get("CUTCANNON") or Path(__file__).resolve().parent.parent)
PAD = 0.08  # breathing room around line-based clips
VIDEO_EXT = (".mov", ".mp4", ".m4v", ".mkv", ".webm")


def videos_in(d):
    """Source-media candidates at the top of a project folder (renders/ is never searched)."""
    return sorted(p for p in Path(d).iterdir()
                  if p.is_file() and p.suffix.lower() in VIDEO_EXT and not p.name.startswith("."))


def source(d):
    """The project's source recording: the file named in meta.json, else the only video there."""
    d = Path(d)
    mf = d / "meta.json"
    if mf.exists():
        name = json.loads(mf.read_text()).get("source")
        if name and (d / name).exists():
            return d / name
    vids = videos_in(d)
    if len(vids) == 1:
        return vids[0]
    sys.exit(f"{d}: expected one source video, found {len(vids)}: {[v.name for v in vids]}")


def proj_dir(p):
    d = Path(p)
    if not d.is_absolute():
        d = SF / "projects" / p
    if not (d / "transcript.json").exists():
        sys.exit(f"no transcript in {d} - run transcribe.py first")
    return d


def versions(d):
    return sorted(int(f.stem[1:]) for f in (d / "plans").glob("v*.json"))


def current(d):
    c = d / "plans" / "CURRENT"
    return int(c.read_text().strip()) if c.exists() else None


def set_current(d, v):
    (d / "plans" / "CURRENT").write_text(str(v))


def load(d, v):
    return json.loads((d / "plans" / f"v{v:03d}.json").read_text())


def resolve(d, plan):
    """Turn line refs into seconds; return (resolved_plan, problems)."""
    tr = json.loads((d / "transcript.json").read_text())
    meta = json.loads((d / "meta.json").read_text())
    lines = {L["id"]: L for L in tr["lines"]}
    probs, out = [], []
    ids = set()
    for sh in plan.get("shorts", []):
        sid = sh.get("id")
        if not sid or sid in ids:
            probs.append(f"short missing/duplicate id: {sid}")
        ids.add(sid)
        trim = sh.get("trim", {})
        frozen = "_resolved" in sh
        clips = [dict(c) for c in sh["_resolved"]] if frozen else []
        for c in ([] if frozen else sh.get("clips", [])):
            if "from" in c:
                a, b = lines.get(c["from"]), lines.get(c.get("to", c["from"]))
                if not a or not b:
                    probs.append(f"{sid}: unknown line in {c}")
                    continue
                s, e = a["s"] - PAD, b["e"] + PAD
            else:
                s, e = float(c["start"]), float(c["end"])
            s = max(0.0, s + trim.get("head", 0.0))
            e = min(meta["duration"], e - trim.get("tail", 0.0))
            if e - s < 0.3:
                probs.append(f"{sid}: clip too short {c}")
                continue
            clips.append({"start": round(s, 3), "end": round(e, 3),
                          **({"track": c["track"]} if "track" in c else {})})
            if c.get("track", "largest") not in ("left", "right", "largest"):
                probs.append(f"{sid}: bad track {c.get('track')} (left | right | largest)")
        if not clips:
            probs.append(f"{sid}: no usable clips")
        dur = sum(c["end"] - c["start"] for c in clips)
        fmt = sh.get("format", "vertical")
        if fmt not in ("vertical", "source"):
            probs.append(f"{sid}: bad format {fmt} (vertical | source)")
        if fmt == "vertical" and dur > 60:
            probs.append(f"{sid}: {dur:.1f}s is over 60s")
        if sh.get("reframe", "face") not in ("face", "center", "left", "right"):
            probs.append(f"{sid}: bad reframe {sh.get('reframe')}")
        out.append({**sh, "clips": clips, "duration": round(dur, 2),
                    "hook_seconds": sh.get("hook_seconds", 2.5),
                    "reframe": sh.get("reframe", "face"),
                    # absent = plan predates tightening: render it exactly as it was
                    "tighten": sh.get("tighten", {"fillers": False, "max_pause": None}),
                    "punch_in": sh.get("punch_in", False),
                    # vertical = 9:16 short; source = keep the original frame (cleanup of a full video)
                    "format": fmt,
                    "captions": sh.get("captions", fmt == "vertical"),
                    "audio": sh.get("audio", {})})
    return {**plan, "shorts": out}, probs


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    cmd, d = sys.argv[1], proj_dir(sys.argv[2])
    args = sys.argv[3:]

    if cmd == "save":
        draft = json.loads(Path(args[0]).read_text())
        if "--note" in args:
            draft["note"] = args[args.index("--note") + 1]
        for s in draft.get("shorts", []):
            s.pop("_resolved", None)  # never trust a copied snapshot; resolve fresh
            s.setdefault("tighten", {"fillers": True, "max_pause": 0.2})
            s.setdefault("punch_in", s.get("format", "vertical") == "vertical")
        res, probs = resolve(d, draft)
        if probs:
            print("REJECTED:\n  " + "\n  ".join(probs))
            sys.exit(1)
        vs = versions(d)
        v = (vs[-1] + 1) if vs else 1
        for s, r in zip(draft["shorts"], res["shorts"]):
            s["_resolved"] = r["clips"]
        rec = {"version": v, "parent": current(d), "created": time.strftime("%Y-%m-%d %H:%M:%S"),
               **draft}
        (d / "plans" / f"v{v:03d}.json").write_text(json.dumps(rec, indent=2))
        set_current(d, v)
        print(f"saved v{v:03d} (parent v{rec['parent'] or 0:03d}) - CURRENT")
        for s in res["shorts"]:
            print(f"  {s['id']:4} {s['duration']:5.1f}s  {len(s['clips'])} clips  hook: {s.get('hook_text','')!r}")

    elif cmd == "list":
        cur = current(d)
        for v in versions(d):
            p = load(d, v)
            mark = "*" if v == cur else " "
            print(f"{mark} v{v:03d}  parent=v{p.get('parent') or 0:03d}  {p['created']}  "
                  f"{len(p.get('shorts', []))} shorts  {p.get('note', '')}")

    elif cmd == "show":
        v = int(args[0].lstrip("v")) if args else current(d)
        res, probs = resolve(d, load(d, v))
        print(json.dumps(res, indent=2))
        for p in probs:
            print("WARN", p, file=sys.stderr)

    elif cmd == "undo":
        cur = current(d)
        parent = load(d, cur).get("parent") if cur else None
        if not parent:
            sys.exit("nothing to undo")
        set_current(d, parent)
        print(f"CURRENT: v{cur:03d} -> v{parent:03d}  (v{cur:03d} kept, `use` to return)")

    elif cmd == "use":
        v = int(args[0].lstrip("v"))
        load(d, v)
        set_current(d, v)
        print(f"CURRENT -> v{v:03d}")

    elif cmd == "approve":
        cur = current(d)
        plan = load(d, cur)
        ids = args or [s["id"] for s in plan["shorts"]]
        f = d / "approvals.json"
        log = json.loads(f.read_text()) if f.exists() else []
        log.append({"version": cur, "shorts": ids, "at": time.strftime("%Y-%m-%d %H:%M:%S")})
        f.write_text(json.dumps(log, indent=2))
        print(f"approved v{cur:03d}: {', '.join(ids)}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
