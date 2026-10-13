# CutCannon roadmap

What's planned, roughly in order. Items move to **Done** as they ship.

## Next: cuts

- **Word-index cut points.** Let plans cut mid-sentence by word position
  (`{"from": "L140", "from_word": 8}`) instead of hand-computed seconds. Exact, and far less
  error-prone than timestamp arithmetic.
- **Join audit.** Before rendering, check that every clip starts and ends on a complete thought.
  After rendering, re-transcribe around each join and flag clipped words, doubled words, or a
  thought that doesn't connect. Becomes a QA check alongside the existing eight.

## Then: framing

- **Fit mode.** Show the whole 16:9 frame inside a 9:16 video over a blurred copy of itself, for
  two-shots where both people matter, screen recordings, and wide B-roll.
- **Active-speaker tracking.** `track: "speaker"` follows whoever is talking, detected from lip
  motion, with hysteresis so the crop doesn't flicker. Stereo channel levels as a cheap tiebreaker
  when each mic is panned to one side. Replaces per-clip `left` / `right`.
- **Square and 4:5 exports** alongside 9:16, for feeds that prefer them.

## Then: foundation

- **Test suite + CI.** Automated tests on generated clips: A/V sync across many cuts, 23.976 /
  30 / 59.94 fps sources, HDR tone mapping, B-roll clips with no speech, and the hallucination
  guards. Plus an optional end-to-end run on a small set of public-domain footage with measurable
  framing criteria (no jitter, no cut-off faces, speaker on screen while speaking). GitHub Actions
  runs the CPU path on every push.

## Then: editorial

- **Project brief.** A small `brief.json` per project: who it's for, the promise, the spoken hook,
  the call to action, claim limits, and the assets you've supplied. Proposals and plans are
  checked against it.
- **Closing card.** An optional end card with the call to action or a comment prompt, styled to
  match the hook card.
- **Proof and screen inserts.** When the speaker says "look at this," show the real screenshot or
  screen recording from the project's `assets/`, full frame or with the speaker in a corner
  window, timed to the words. Only assets you supply; nothing generated.
- **Opening lab.** For one strong clip, write three openings (problem, evidence, process), render
  four-second previews of each, and pick one before the full render. Each is its own plan version.

## Then: output and polish

- **Chapters and cover headlines.** Chapter timestamps in the post kit for full-length cleanups;
  optional headline text on the cover image.
- **Caption style presets** (bold pop, karaoke fill, clean lower third, boxed), per show.
- **Watermark / logo overlay** with position, size and opacity.
- **Import from a URL** (yt-dlp), for content you own or have the rights to process.
- **Sequential reels.** Split a whole video into a numbered series of consecutive clips.
- **Project "next step"** in `projects.py` (e.g. "rendered, not approved"), a `CHANGELOG.md`, and
  a "verified / not verified" section in the README.

## Non-goals

- **Posting to social platforms.** CutCannon makes files; nothing posts until you do it yourself.
- **Synthetic voices or AI-generated footage.** It edits real recordings.
- **A web UI.** You drive it in plain English from Claude.

## Done

- Post kit (`bin/postkit.py`): cover, `.srt`, YouTube / TikTok / Instagram copy from `_post.json`
- Doctor command (`bin/doctor.py`), and `ffmpeg-full` on macOS
- Clip proposals scored (hook, flow, value, shareability); re-told stories dropped
- Apple Silicon support: mlx-whisper on Metal, VideoToolbox encode/decode
- Voice-activity detection on every transcription; repetition-loop filter
- Frame-exact segment trimming at the source frame rate (no A/V drift on any frame rate)
- B-roll clips with no speech kept whole
- Speaker tracking through camera switches; full-frame cleanup mode with motion-guarded pause cuts
- Filler and pause tightening; HDR to SDR; two-pass -14 LUFS loudness; automatic QA on every render
