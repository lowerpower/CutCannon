---
name: cutcannon-editor
description: Edit video recordings locally with Claude, either as vertical shorts (captions, hook card, speaker-tracking crop) or as a full-length cleanup (false starts, fillers and dead pauses removed, audio at -14 LUFS). Every cut is a versioned, undoable plan and every render is QA-checked. Use whenever the user wants to cut, clip, propose, clean up, re-cut or re-render a video or a project in projects/, including vague requests like "let's make some clips" or "what's in my projects", where you start by asking which project, what job, and how many clips. Never uploads or posts anything.
---

# cutcannon editor

Toolkit lives in `~/cutcannon`. Always run commands as:

    cd ~/cutcannon && . ./env.sh && python bin/<script>.py ...

## Session start: ask before you cut

Settle three things before any plan or render. **Skip any question the user's request already
answers** ("make 3 shorts from podcast-ep12" answers all three). Ask everything that's still open
in ONE message. If a multiple-choice question tool is available (e.g. AskUserQuestion), use it.

1. **Which project?** Run `python bin/projects.py` and show the table.
   - No project named: ask which one. With exactly one project, just confirm it.
   - `new - not transcribed`: offer to transcribe it. A loose video in `projects/`: offer to import it (the table prints the command).
   - `N videos - pick one`: ask which file is the source.
2. **What job?**
   - **Shorts**: vertical 9:16 clips, captions, hook card.
   - **Cleanup**: the full video in its original frame, with false starts, fillers and dead pauses removed and audio at -14 LUFS.
   Suggest the likely one (screen recording or demo: cleanup; long talk or podcast: shorts), but let the user choose.
3. **How many clips?** (shorts only) Offer: **3**, **5**, **a number**, or **auto**.
   **auto** = you read the whole transcript and propose as many as the material genuinely supports (see below).

Once the project is chosen and it isn't transcribed yet, start transcribing right away, since every
next step needs the transcript.

## Proposing clips

Always **propose first and render only what the user picks**, unless they said to go ahead ("just make 3").

Read the whole `transcript.txt`, plus the speaker `.vtt` if there is one. A clip qualifies only if:
- it opens on (or can be re-ordered to open on) a line that works as a hook,
- it holds one idea with a payoff or punchline, and stands alone with no "as I said earlier",
- it fits 20-55 s after tightening.

**Counts**
- **auto**: propose every clip that clears that bar, strongest first, capped at 8. As a guide, expect
  roughly one per 4-6 minutes of conversation and 1-2 from a short take. **Never pad**: if only 2
  are strong, propose 2 and say why.
- **A number N**: propose the best N. If fewer than N are strong, say so rather than padding. If more
  are, add up to 3 runners-up in one line each.

**Per proposed clip, give:** rank, hook-card text, approximate timecode range, who speaks, one or two
sentences on why it works, estimated length, and any **flags**:
- names a company or person in an unverified or negative claim (propose cutting around the name),
- inserted footage or B-roll in the range (possible third-party video, and no face to track),
- speaker changes inside the clip (it will be split, one track per speaker),
- a low-resolution source that will look soft when cropped to vertical.

End by asking which to render ("all", numbers, or changes). Then plan and render only those.

## Projects

Each recording lives in its own folder: `projects/<name>/` holds the source video (plus an
optional speaker-labelled `.vtt`/`.srt`) and everything generated from it (transcript, plans/,
renders/). Renders stay in the project folder; never copy them elsewhere unless asked.

## Pipeline

1. **Transcribe** (GPU, seconds):
   `python bin/transcribe.py <name>` when the user dropped the file into `projects/<name>/`, or
   `python bin/transcribe.py /path/to/recording.mov [--name <name>]` to import it (the file is MOVED into `projects/<name>/`).
   Read `projects/<name>/transcript.txt` — one numbered line per sentence, `[L012 83.42-88.10] text`, with long pauses marked.
   If the project has a `.vtt` with speaker labels (`<v Name>`), read it too: it tells you WHO says each line, which Whisper can't.

2. **Plan** — read the whole transcript, then write a draft JSON and save it:
   `python bin/plan.py save <slug> /tmp/draft.json --note "what changed"`
   Draft shape:
   ```json
   {"shorts": [{
     "id": "s1", "title": "internal name",
     "hook_text": "≤ 6 words, on screen first 2.5s",
     "hook_seconds": 2.5,
     "reframe": "face",
     "clips": [{"from": "L004", "to": "L009"}, {"from": "L014", "to": "L016"}],
     "word_fixes": {"chip": "Ship"}
   }]}
   ```
   - `clips` play in the order listed; you may reorder to put the strongest line first.
   - Use `{"start": s, "end": e}` in seconds when a cut must fall mid-sentence.
   - `reframe`: `face` (auto, static crop per clip), or `center` / `left` / `right`.
   - `word_fixes`: caption corrections for mis-heard words (case-insensitive).
   - Fillers appear in the transcript as `(um,)` / `(uh)`. With the defaults you do NOT cut them by hand: `"tighten": {"fillers": true, "max_pause": 0.2}` removes every um/uh and caps pauses at 0.2 s at render time, and `"punch_in": true` alternates a 108% zoom at each cut to hide jump cuts. Set `"punch_in": false` for a calmer look, or `"tighten": {"fillers": false, "max_pause": null}` to keep the speaker's natural rhythm.
   - "like", "you know", "I guess" are NOT auto-cut — cut them with clip boundaries only where they're pure filler.
   - Plans freeze resolved clip times at save, so re-transcribing never changes what an old version renders.
   - **Two or more people on camera (landscape source):** give each clip `"track": "left" | "right" | "largest"` for the speaker it features. The crop follows that person through camera switches automatically. Split a clip where the speaker changes. Work out who sits where from the .vtt speaker labels plus the face positions, and confirm with the user if unsure.
   - **Full-video cleanup instead of shorts** ("clean it up", demos, screen recordings): one entry with `"format": "source"` keeps the original frame and length (no crop, no 60 s limit), `"captions": false`, `"punch_in": false`, `"hook_text": ""`, clips covering the whole video minus false starts/repeats, `"tighten": {"fillers": true, "max_pause": 0.4}`, `"audio": {"compress": true}`. Pauses are only cut when the screen is also still (webcam bubble masked), so demo actions are kept. Only add `highpass`/`denoise` to `audio` if the source actually has rumble or hiss.
   - Default to 1–3 shorts, each 20–45s, never over 60s (save rejects it).

   Editing rules:
   - Open on the hook. If the best line is mid-recording, move it to the front.
   - Cut false starts ("let me start over"), filler-only sentences, tangents, and repeated takes (keep the last clean take).
   - Each short must stand alone: no "as I said earlier".
   - End on the takeaway line; don't trail into "anyway…".
   - Check `word_fixes` against names/jargon in the transcript (product names, acronyms).

3. **Render** — preview first, then full:
   `python bin/render.py <slug> --preview` (540×960, fast)
   `python bin/render.py <slug>` (1080×1920, NVENC) → `projects/<slug>/renders/<id>_vNNN.mp4`
   Render one short: `python bin/render.py <slug> s2`

   **QA runs automatically after every render** and prints one line per short, e.g.
   `QA PASS: av_sync=ok duration=ok color=ok loudness=ok captions=ok hook_card=ok fillers=ok framing=ok`,
   followed by a timing line (prep / encode / loudnorm / qa).
   It writes `renders/<tag>_qa.json` and a contact sheet `renders/<tag>_frames.png`
   (hook, 25%, 50%, 75%, end). Re-run alone with `python bin/qa.py <slug> [id]`.
   - Read the QA line before reporting a render as done. Never call a FAIL "done".
   - `av_sync` / `duration` FAIL → re-render; if it repeats, report the drift numbers.
   - `loudness` FAIL → report LUFS/true-peak; usually a very quiet or clipped source.
   - `captions` FAIL → `uncaptioned_at_s` lists output times with speech but no caption; check those words in the transcript (often dropped by the word filter at a clip edge — widen the clip slightly).
   - `color` FAIL → the HDR source wasn't tone-mapped or the output is mis-tagged; re-render.
   - `fillers` FAIL → more than one um/uh survived; `at_s` lists output times. Usually a filler Whisper missed in the source transcript — cut it with a clip boundary.
   - `framing` FAIL → face near the edge; set `reframe` to `left`/`right`/`center`. `n/a` means no face was found (screen recording, or the camera faced away) — say so.
   - Tell the user the path to `_frames.png` so they can eyeball the look.

4. **Review loop** — tell the user each short's duration, hook text, which lines were kept/cut and why, the QA result, and the file paths. Then take changes. Every change is a NEW version via `plan.py save`; never edit files in `plans/` directly.
   - `python bin/plan.py list <slug>` — history (`*` = CURRENT)
   - `python bin/plan.py show <slug> [vN]` — resolved times
   - `python bin/plan.py undo <slug>` — back to parent version (nothing deleted)
   - `python bin/plan.py use <slug> vN` — jump to any version

5. **Approve** only when the user says so: `python bin/plan.py approve <slug> [ids]`.
   Approval is a record, not an action. Do not upload, post, schedule, or copy renders anywhere unless the user explicitly asks for that specific action.

## Troubleshooting
- `REJECTED:` from save lists exact problems (unknown line id, >60s, bad reframe) — fix the draft and save again.
- Wrong crop: set `reframe` to `left`/`right`/`center` for that short.
- Captions drift: re-transcribe with `--model medium.en`.
