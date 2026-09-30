#!/usr/bin/env python3
"""projects.py - status of every project, so you can pick one.

  projects.py            table of projects
  projects.py --json     same, machine-readable

Also flags videos dropped loose in projects/ (they need their own folder).
"""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import plan as P  # noqa: E402


def mmss(s):
    s = int(round(s))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def status(d):
    meta = json.loads((d / "meta.json").read_text()) if (d / "meta.json").exists() else {}
    vids = P.videos_in(d)
    src = meta.get("source") or (vids[0].name if len(vids) == 1 else None)
    vers = P.versions(d) if (d / "plans").is_dir() else []
    cur = P.current(d) if vers else None
    shorts = []
    if cur:
        try:
            shorts = [s["id"] for s in P.load(d, cur).get("shorts", [])]
        except Exception:
            pass
    # latest full (non-preview) render of each short in the current plan, and its QA verdict;
    # superseded renders from older versions don't count against the project
    latest = {}
    for sid in shorts:
        rs = sorted((d / "renders").glob(f"{sid}_v[0-9][0-9][0-9].mp4")) if (d / "renders").is_dir() else []
        if rs:
            q = rs[-1].with_name(rs[-1].stem + "_qa.json")
            latest[sid] = json.loads(q.read_text()).get("pass") if q.exists() else None
    renders = len(latest)
    qa = list(latest.values())
    appr = json.loads((d / "approvals.json").read_text()) if (d / "approvals.json").exists() else []
    if not vids:
        state = "no video"
    elif len(vids) > 1 and not meta.get("source"):
        state = f"{len(vids)} videos - pick one"
    elif not (d / "transcript.json").exists():
        state = "new - not transcribed"
    elif not vers:
        state = "transcribed - no plan yet"
    else:
        state = "in progress"
    return {
        "project": d.name, "state": state, "source": src,
        "duration": meta.get("duration"),
        "frame": f"{meta['width']}x{meta['height']}" if meta.get("width") else None,
        "speaker_vtt": any(p.suffix.lower() in (".vtt", ".srt") for p in d.iterdir()),
        "plan": f"v{cur:03d} of {len(vers)}" if cur else None, "shorts": shorts,
        "renders": renders, "qa_fail": qa.count(False), "approved": len(appr),
    }


def main():
    root = P.SF / "projects"
    rows = [status(d) for d in sorted(root.iterdir()) if d.is_dir() and not d.name.startswith(".")]
    loose = [p.name for p in P.videos_in(root)]
    if "--json" in sys.argv:
        print(json.dumps({"projects": rows, "loose_videos": loose}, indent=1))
        return
    if not rows and not loose:
        print("No projects yet. Make projects/<name>/ and put a recording in it.")
        return
    print(f"{'project':18} {'state':26} {'length':>7}  {'frame':10} {'vtt':3}  {'plan':9} {'shorts':14} rendered")
    for r in rows:
        ln = mmss(r["duration"]) if r["duration"] else "-"
        n = len(r["shorts"])
        rend = (f"{r['renders']}/{n}" + (f" ({r['qa_fail']} QA FAIL)" if r["qa_fail"] else ", QA ok" if r["renders"] else "")
                if n else "-") + (f", {r['approved']} approved" if r["approved"] else "")
        print(f"{r['project'][:18]:18} {r['state'][:26]:26} {ln:>7}  {(r['frame'] or '-'):10} "
              f"{'yes' if r['speaker_vtt'] else '-':3}  {(r['plan'] or '-'):9} "
              f"{(','.join(r['shorts']) or '-')[:14]:14} {rend}")
    for name in loose:
        print(f"\n! loose video in projects/: {name}\n  -> python bin/transcribe.py 'projects/{name}' --name <project>  (moves it into its own folder)")


if __name__ == "__main__":
    main()
