#!/usr/bin/env python3
"""postkit.py <project> [short_id ...] [--force]

Everything needed to post each rendered short, written next to the video in renders/:

  <tag>_cover.jpg   cover / thumbnail: the frame showing the hook card
  <tag>.srt         caption file for platforms that take one (YouTube, LinkedIn): the same
                    words and word_fixes as the burned-in captions
  <tag>_post.md     YouTube Shorts / TikTok / Instagram Reels copy, formatted from <tag>_post.json

<tag> is the newest full render of each short (e.g. s3_v004). An existing cover or .srt is kept
unless --force. The _post.md is always regenerated from the JSON.

The copy lives in <tag>_post.json (written by Claude or by hand):
  {"source_range": "34:49-36:32",
   "youtube":   {"title": "... (max 100 chars)", "description": "...", "hashtags": "#Shorts #AI",
                 "tags": ["robots", "welding"]},
   "tiktok":    {"caption": "... #robots #maker"},
   "instagram": {"caption": "...", "hashtags": "#robots #maker"},
   "alt_text": "...", "pinned_comment": "...", "notes": ["..."]}

Shared details go once in projects/<project>/post.json:
  {"source_title": "Show: Episode title", "credits": "From <show>. Full episode: {episode_link}",
   "instagram_credit": "... Full episode: link in bio.", "episode_link": "https://..."}
"""
import json, re, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import plan as P  # noqa: E402
import render as R  # noqa: E402


def latest_render(d, sid):
    rs = sorted((d / "renders").glob(f"{sid}_v[0-9][0-9][0-9].mp4"))
    return rs[-1] if rs else None


def plan_short(d, ver, sid):
    res, _ = P.resolve(d, P.load(d, ver))
    return next((s for s in res["shorts"] if s["id"] == sid), None)


def srt_time(t):
    h, r = divmod(max(t, 0.0), 3600)
    m, s = divmod(r, 60)
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{int(round((s % 1) * 1000)) % 1000:03d}"


def write_srt(words, path):
    """Readable cues: up to 7 words or 2.6 s, breaking at sentence ends."""
    cues, cur = [], []
    for w in words:
        cur.append(w)
        if len(cur) >= 7 or cur[-1]["e"] - cur[0]["s"] > 2.6 or w["w"][-1:] in ".?!":
            cues.append(cur)
            cur = []
    if cur:
        cues.append(cur)
    path.write_text("\n".join(f"{i}\n{srt_time(c[0]['s'])} --> {srt_time(c[-1]['e'])}\n"
                              f"{' '.join(x['w'] for x in c)}\n" for i, c in enumerate(cues, 1)))
    return len(cues)


def caption_source(d, mp4, short):
    """Output-timeline caption words. Uses the exact segments from the render log; renders made
    before render logs recorded segments fall back to transcribing the finished video."""
    info_f = mp4.with_name(mp4.stem + "_render.json")
    info = json.loads(info_f.read_text()) if info_f.exists() else {}
    if info.get("clips"):
        words = json.loads((d / "transcript.json").read_text())["words"]
        return R.caption_words(words, info["clips"], short)[0], "render segments"
    import asr
    from transcribe import PROMPT, FILLER
    segs = asr.transcribe(str(mp4), prompt=PROMPT, vad=True)
    words = [{"w": w.word.strip(), "s": w.start, "e": w.end,
              **({"f": True} if FILLER.match(w.word.strip()) else {})}
             for s in segs for w in (s.words or []) if w.word.strip()]
    dur = max((w["e"] for w in words), default=0.0) + 1
    return R.caption_words(words, [{"start": 0.0, "end": dur}], short)[0], "transcribed from the video"


def post_md(tag, sid, short, copy, shared, mp4, has_kit):
    yt, tt, ig = copy.get("youtube", {}), copy.get("tiktok", {}), copy.get("instagram", {})
    link = shared.get("episode_link") or "[EPISODE LINK]"
    credits = shared.get("credits", "Full episode: {episode_link}").replace("{episode_link}", link)
    dur = json.loads(mp4.with_name(mp4.stem + "_qa.json").read_text())["checks"]["duration"]["actual_s"] \
        if mp4.with_name(mp4.stem + "_qa.json").exists() else None
    out = [f"# {sid}: \"{short.get('hook_text') or short.get('title', sid)}\"", "",
           f"**Video:** `{tag}.mp4`" + (f" \u00b7 {dur:.1f} s" if dur else "") + " \u00b7 1080\u00d71920"
           + (f" \u00b7 cover `{tag}_cover.jpg` \u00b7 captions `{tag}.srt`" if has_kit else "")]
    if shared.get("source_title") or copy.get("source_range"):
        out.append(f"**Source:** {shared.get('source_title', '')}"
                   + (f", {copy['source_range']}" if copy.get("source_range") else ""))
    out += ["", "## YouTube Shorts", "", f"**Title:** {yt.get('title', '')}", "", "**Description:**", "",
            yt.get("description", ""), "", credits, ""]
    if yt.get("hashtags"):
        out += [yt["hashtags"], ""]
    out += [f"**Tags:** {', '.join(yt.get('tags', []))}", "",
            "## TikTok", "", "**Caption:**", "", tt.get("caption", ""), "",
            "## Instagram Reels", "", "**Caption:**", "", ig.get("caption", ""), ""]
    if shared.get("instagram_credit"):
        out += [shared["instagram_credit"], ""]
    if ig.get("hashtags"):
        out += [ig["hashtags"], ""]
    out += [f"**Alt text:** {copy.get('alt_text', '')}", "", "## All platforms", "",
            f"**Pinned comment:** {copy.get('pinned_comment', '')}", "",
            "- Turn **off** auto-captions on TikTok and Instagram (captions are burned in)."]
    if has_kit:
        out.append(f"- YouTube / LinkedIn: upload `{tag}.srt` as the caption track; set `{tag}_cover.jpg` as the cover.")
    if link == "[EPISODE LINK]":
        out.append("- Replace `[EPISODE LINK]`: set `episode_link` in the project's post.json and re-run postkit.")
    if copy.get("notes"):
        out += ["", "## Notes", ""] + [f"- {n}" for n in copy["notes"]]
    return "\n".join(out) + "\n"


def check_copy(sid, copy):
    probs = []
    t = copy.get("youtube", {}).get("title", "")
    if not t or len(t) > 100:
        probs.append(f"{sid}: YouTube title must be 1-100 characters (is {len(t)})")
    for plat, field in (("tiktok", "caption"), ("instagram", "caption")):
        if len(copy.get(plat, {}).get(field, "")) > 2200:
            probs.append(f"{sid}: {plat} caption over 2200 characters")
    n_ig = len(re.findall(r"#\w+", copy.get("instagram", {}).get("hashtags", "") + copy.get("instagram", {}).get("caption", "")))
    if n_ig > 30:
        probs.append(f"{sid}: Instagram allows at most 30 hashtags (has {n_ig})")
    return probs


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    d = P.proj_dir(args.pop(0))
    force = "--force" in args
    ids = [a for a in args if not a.startswith("--")]
    shared_f = d / "post.json"
    shared = json.loads(shared_f.read_text()) if shared_f.exists() else {}
    res, _ = P.resolve(d, P.load(d, P.current(d)))
    for sid in ids or [s["id"] for s in res["shorts"]]:
        mp4 = latest_render(d, sid)
        if not mp4:
            print(f"  {sid}: not rendered yet")
            continue
        tag = mp4.stem
        short = plan_short(d, int(tag.split("_v")[1]), sid) or {}
        cover, srt = mp4.with_name(f"{tag}_cover.jpg"), mp4.with_name(f"{tag}.srt")
        made = []
        if force or not cover.exists():
            t = min(float(short.get("hook_seconds", 2.5)) * 0.5, 1.2) if short.get("hook_text") else 0.5
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(mp4), "-frames:v", "1",
                            "-q:v", "2", str(cover)], check=True)
            made.append("cover")
        if force or not srt.exists():
            words, how = caption_source(d, mp4, short)
            made.append(f"srt ({write_srt(words, srt)} cues, {how})")
        copy_f = mp4.with_name(f"{tag}_post.json")
        if copy_f.exists():
            copy = json.loads(copy_f.read_text())
            probs = check_copy(sid, copy)
            if probs:
                print("  " + "\n  ".join(probs))
                continue
            mp4.with_name(f"{tag}_post.md").write_text(post_md(tag, sid, short, copy, shared, mp4, True))
            made.append("post.md")
        else:
            made.append(f"no {copy_f.name} yet (write the copy, then re-run)")
        print(f"  {tag}: " + ", ".join(made or ["up to date"]))


if __name__ == "__main__":
    main()
