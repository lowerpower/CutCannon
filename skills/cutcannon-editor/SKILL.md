---
name: cutcannon-editor
description: Edit video recordings locally with Claude, either as vertical shorts (captions, hook card, speaker-tracking crop) or as a full-length cleanup (false starts, fillers and dead pauses removed, audio at -14 LUFS). Every cut is a versioned, undoable plan and every render is QA-checked. For each finished short it also writes a social media post kit (YouTube Shorts / TikTok / Instagram Reels title, description and hashtags, plus a cover image and caption file). Use whenever the user wants to cut, clip, propose, clean up, re-cut or re-render a video or a project in projects/, or wants titles, descriptions, hashtags, captions or social media posts for its clips, including vague requests like "let's make some clips" or "what's in my projects", where you start by asking which project, what job, and how many clips. Also use it when the user wants a short or video scheduled or uploaded to YouTube. Never uploads or posts on its own: it schedules a YouTube upload (bin/ytpost.py) only when the user asks for that specific upload and says yes to its dry run.
---

# cutcannon editor

Toolkit lives in `~/cutcannon`. Always run commands as:

    cd ~/cutcannon && . ./env.sh && python bin/<script>.py ...

**Where commands run.** The toolkit lives on one machine (usually a GPU box). When you reach it through a remote-execution connector such as NoBGP MCP, run every command on that node; source files, plans and renders stay there unless the user asks to copy something to another machine.

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

## Unattended runs

When no one can answer (a `claude -p` batch, an overnight or scheduled job), the request is the
whole brief. It must name the project, the job and the clips or how many; if one is missing, don't
guess: stop and say what's missing. Otherwise the request counts as "go ahead": choose the clips by
the rules in **Proposing clips**, render them, and list the runners-up you didn't render.

- **Done** means every requested short is rendered, its QA line is PASS, and the final report gives
  each short's QA line, every `note:` line and the file paths. Don't stop early with a list of
  what's left or a "shall I continue?".
- **Fix it and continue, without asking:** a failed or timed-out render or transcription is an
  ordinary obstacle. Re-rendering, re-transcribing, nudging a clip edge by a few words and changing
  `reframe` are pre-approved.
- **Leave for the user:** which moments are clipped, and how many shorts. If a short can't pass QA
  without such a change, report it as FAIL with the change it needs, and finish the others.
- **Limits:** at most 1 `transcribe.py` and 1 `render.py` running at a time (`render.py` already
  renders a project's shorts one after another, and its QA loads Whisper on the same GPU), and at
  most 3 renders of one short per run. A short still failing after 3 is reported as FAIL.
- Never upload, post, schedule or approve anything in an unattended run.

## Proposing clips

Always **propose first and render only what the user picks**, unless they said to go ahead ("just make 3").

Read the whole `transcript.txt`, plus the speaker `.vtt` if there is one. A clip qualifies only if:
- it opens on (or can be re-ordered to open on) a line that works as a hook,
- it holds one idea with a payoff or punchline, and stands alone with no "as I said earlier",
- it fits 20-55 s after tightening,
- it doesn't re-tell something already said. When one speaker repeats a story or setup another
  just told (common in interviews), keep the better telling and cut the repeat, inside a clip and
  across proposals: never propose two clips that tell the same story.

**Counts**
- **auto**: propose every clip that clears that bar, strongest first, capped at 8. As a guide, expect
  roughly one per 4-6 minutes of conversation and 1-2 from a short take. **Never pad**: if only 2
  are strong, propose 2 and say why.
- **A number N**: propose the best N. If fewer than N are strong, say so rather than padding. If more
  are, add up to 3 runners-up in one line each.

**Score every proposed clip 1-5 on:** hook (does the first line stop a scroll), flow (does it hold
together with no dead spots), value (does the viewer leave with something: a laugh, an idea, a
story), and shareability (would someone send it to a friend). Rank by the total and show the scores,
e.g. `hook 5 · flow 4 · value 4 · share 5 = 18/20`. Score honestly: a 12 is fine to list as a
runner-up, but never inflate scores to fill a requested count.

**Per proposed clip, give:** rank, scores, hook-card text, approximate timecode range, who speaks, one or two
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
   - When a cut must fall mid-sentence, cut by word, not by computed seconds: run
     `python bin/plan.py words <slug> L140 L141` to see each line's numbered words (fillers in
     brackets count), then use `{"from": "L140", "from_word": 11, "to": "L141", "to_word": 8}`.
     `from_word` starts at that word; `to_word` ends after it. Either may be omitted to use the
     whole line edge. After `save`, read the "mid-line cuts" lines it prints (`words before | words
     after`) and fix any edge that splits a phrase wrongly. Use `{"start": s, "end": e}` seconds
     only for picture-only cuts with no speech at the edge (B-roll, reactions).
   - `reframe`: `face` (auto, static crop per clip), or `center` / `left` / `right`.
   - `stabilize`: `true` for **handheld, walking, vehicle or boat** footage (shaky phone video). It removes the camera shake and keeps deliberate pans. Leave it off (the default) for tripod or desk shots and screen recordings: there is nothing to fix, and it costs time. The first render with it stabilizes the whole source once (roughly 3x the source length on the Linux box; cached in `<project>/cache/`), so later renders and versions are as fast as before. It slightly zooms in (a few percent) to hide the edges the correction exposes; say so if framing is tight. If the user mentions shake, wobble or jitter, offer it.
   - `word_fixes`: caption corrections for mis-heard words (case-insensitive).
   - `brand`: the show's look (see **Brands** below). Put `"brand": "<name>"` at the top of the draft
     so every short uses it. If earlier versions of this project used a brand, keep using it unless
     the user says otherwise. Without one, shorts get the default look.
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
   `QA PASS: av_sync=ok duration=ok color=ok loudness=ok captions=ok hook_card=ok fillers=ok joins=ok framing=ok motion=ok`,
   followed by a timing line (prep / encode / loudnorm / qa).
   It writes `renders/<tag>_qa.json` and a contact sheet `renders/<tag>_frames.png`
   (hook, 25%, 50%, 75%, end). Re-run alone with `python bin/qa.py <slug> [id]`.
   - Read the QA line before reporting a render as done. Never call a FAIL "done".
   - `av_sync` / `duration` FAIL → re-render; if it repeats, report the drift numbers.
   - `loudness` FAIL → report LUFS/true-peak; usually a very quiet or clipped source.
   - `joins` FAIL → a `note:` names each join (output seconds), the kind and the words. `missing` = a word clipped at the cut: move that clip edge to include the whole word (word cuts make this exact). `doubled` = the same word or phrase on both sides of a cut: drop one.
   - `joins` warnings appear as `note:` lines even when QA PASSes, and must be reported too, never skipped because the line says PASS: `extra` = a word at the cut the captions don't have (usually a real word the transcript skipped, sometimes a cut-off fragment): tell the user where, and move the edge off it if it's a fragment. `filler` = an um/uh survived at a cut: nudge that clip edge past it. `repeat` = the speaker really says it twice; it's the user's call. Treat all of these as "listen here", not certainties: give the times so the user can check by ear.
   - Always read `checks.joins.edits` in the QA json: the words either side of every edit (a join between two plan clips). Judge whether each one reads as one connected thought; if one doesn't, say which and propose a fix. Technical checks passing does not mean the edit makes sense. `edits: null` means the render can't say which joins are edits (an old render): re-render to get the list, or review the plan's clip boundaries instead.
   - After `plan.py save`, read any `WARN incomplete thoughts` lines: a clip starting or ending mid-sentence. Fine when intended (opening on the second half of a sentence); otherwise move the edge.
   - `captions` FAIL → `uncaptioned_at_s` lists output times with speech but no caption; check those words in the transcript (often dropped by the word filter at a clip edge — widen the clip slightly).
   - `color` FAIL → the HDR source wasn't tone-mapped or the output is mis-tagged; re-render.
   - `fillers` FAIL → more than one um/uh survived; `at_s` lists output times. Usually a filler Whisper missed in the source transcript — cut it with a clip boundary.
   - `framing` FAIL → face near the edge; set `reframe` to `left`/`right`/`center`. `n/a` means no face was found (screen recording, or the camera faced away) — say so. A `face small in frame` note means a wide shot where the speaker reads small on a phone: say so in the report.
   - `motion` FAIL → the picture is frozen for 2 s or more (the `note:` gives the output times). Sampled frames can't show this, so look at the source at those times: a stuck or dropped-frame stretch in the source is cut around with a clip edge; a freeze the source doesn't have means re-render. A 1-2 s freeze is a `note:` to report. A `motion not checked` note means the scan itself failed: run `python bin/doctor.py`. `n/a` for a full-video cleanup, where still screens are normal: report its one summary note.
   - Tell the user the path to `_frames.png` so they can eyeball the look.

4. **Review loop** — tell the user each short's duration, hook text, which lines were kept/cut and why, the QA result, and the file paths. Then take changes. Every change is a NEW version via `plan.py save`; never edit files in `plans/` directly.
   - When a short passes QA, end the report with a one-line offer of its post kit (step 5), e.g. *"Want the post kit for s3? YouTube Shorts, TikTok and Instagram Reels titles, descriptions and hashtags, plus a cover and caption file."* Users often don't know CutCannon writes these, so always offer it once per short.
   - `python bin/plan.py list <slug>` — history (`*` = CURRENT)
   - `python bin/plan.py show <slug> [vN]` — resolved times
   - `python bin/plan.py undo <slug>` — back to parent version (nothing deleted)
   - `python bin/plan.py use <slug> vN` — jump to any version

5. **Post kit** (the social media copy): when the user is happy with a short, says yes to your offer, or asks for titles, descriptions, tags, hashtags or social posts,
   write `renders/<tag>_post.json` (`<tag>` = the newest render, e.g. `s3_v004`) and run
   `python bin/postkit.py <slug> [ids]`. It writes the cover (`_cover.jpg`), the caption file (`.srt`,
   same words and fixes as the burned-in captions) and `_post.md`. JSON fields: `source_range`;
   `youtube` {`title` (max 100 chars), `description`, `hashtags` (start with #Shorts), `tags` [list]};
   `tiktok` {`caption` incl. 3-5 hashtags}; `instagram` {`caption`, `hashtags` (3-5)}; `alt_text`;
   `pinned_comment`; `notes` (flags: consent, third-party footage, wording). Shared details (credits,
   source title, `episode_link`) go once in `projects/<slug>/post.json`, so the episode URL is set in
   one place. Write copy that matches what the clip actually says; never promise what it doesn't show.

6. **Approve** only when the user says so: `python bin/plan.py approve <slug> [ids]`.
   Approval is a record, not an action. Do not upload, post, schedule, or copy renders anywhere unless the user explicitly asks for that specific action.

7. **Schedule on YouTube** (opt-in: only when the user asks to upload or schedule a specific short or video).
   Run `python bin/ytpost.py post <channel> <slug> <id> --dry-run` first and show the user its summary
   (channel, publish time, title, category, captions, and whether YouTube will treat it as a Short).
   Upload only after they say yes, with the same arguments minus `--dry-run`. Every upload goes up
   **private with a scheduled publish time**: `--next` (the default) takes the next free daily slot from
   the channel's settings, `--at "YYYY-MM-DD HH:MM"` a time they name. Report the youtu.be and Studio
   links it prints. Any video works, not just a CutCannon short: `--video FILE --meta <file>_post.json`.
   - Ask about `--synthetic` (YouTube's disclosure for realistic AI-generated or altered people, places
     or events) when the video might need it; don't guess.
   - The made-for-kids designation is the channel owner's to declare. If the dry run says the audience
     is NOT SET, ask the user, then `ytpost.py set <channel> made_for_kids=no|yes`; never pick it yourself.
   - `ytpost.py queue <channel>` lists scheduled and recent uploads; `ytpost.py set <channel> [key=value]`
     shows or changes the daily slots, category and playlist.
   - Never pass `--force` (a second upload of the same file) unless the user asks for a duplicate.
   - The Google sign-in is the user's: when a command says the channel isn't signed in, or its sign-in
     stopped working, run `ytpost.py auth <channel>`, give them the link, and finish with
     `ytpost.py auth <channel> --code '<address>'` using the 127.0.0.1 address they paste back.
     One-time Google Cloud setup: README, section 8.
   - Permissions are chosen at sign-in: `--scope full` (default: caption tracks and playlists, but the
     token can also edit and delete videos) or `--scope upload` (adds videos and can set any video's
     thumbnail, but can't delete videos or change their details). If an upload reports
     captions or playlist "skipped", the channel was signed in with `upload`; say so rather than
     re-signing in on your own.

## Brands (a look per show)

A brand sets the caption font, colors and word highlight, and the hook card, for every short of a
show. It lives in `brands/<name>/brand.json` (fields and defaults: `brands/README.md`; any field
left out keeps the default). The repo ships two examples: `terminal` (typed-terminal hook card,
captions with the spoken word on a blue box) and `gold` (black hook card with gold text, gold word
highlight). `python bin/brand.py list` shows what exists.

When the user asks for a brand ("create a CutCannon brand for <show> from the show's look"):
1. Look before you choose: grab frames from the show's episode or intro
   (`ffmpeg -ss <t> -i <video> -frames:v 1 /tmp/f.png`) and read the colors and type of its logo,
   wordmark and lower-thirds. Ask for the brand's hex colors or fonts if the user has them.
2. Write `brands/<slug>/brand.json` with only the fields that differ from the default, plus a
   one-line `description`. Use fonts already in `fonts/` or on the system (`fc-list : family`).
   A font file the user provides (one they have the rights to) goes in the brand folder.
3. `python bin/brand.py preview <slug> <project> [--at <seconds>] [--hook "a real hook"]` and show
   the user `brands/<slug>/preview.png`. It renders one still with the hook card and a caption, in
   seconds, with no plan version. Fix any `warning:` about a missing font. Adjust and preview again
   until they like it.
4. Use it: `"brand": "<slug>"` in the next plan draft, save, render. Saving freezes a copy of the
   brand into that version, so to pick up a later change to the brand, save a new version.

## Troubleshooting
- Anything environmental (missing ffmpeg filter, no GPU, import or model errors): run
  `python bin/doctor.py` and follow the fixes it prints.
- `REJECTED:` from save lists exact problems (unknown line id, >60s, bad reframe) — fix the draft and save again.
- Wrong crop: set `reframe` to `left`/`right`/`center` for that short.
- Captions drift: re-transcribe with `--model medium.en`.
