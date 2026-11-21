# CutCannon

**Record once. Claude does the edit.**

`cutcannon` turns raw recordings (a phone take, a two-person podcast, a screen-recorded demo) into finished video on your own GPU machine. You drive it in plain English from a **Claude chat**, which reaches that machine through the **NoBGP MCP connector**. You work from anywhere while the heavy lifting runs on your own hardware. Running [Claude Code](https://docs.claude.com/en/docs/claude-code/overview) directly on the machine works too. It does two jobs:

- **Shorts:** cut vertical 1080×1920 clips with word-by-word captions, a hook card, and a crop that follows whoever is speaking.
- **Cleanup:** keep the full video in its original frame, and remove false starts, ums, and dead pauses (only pauses where the screen is also still), with audio at −14 LUFS.

**It writes the social media posts too.** For every short, CutCannon makes a ready-to-paste **post kit**: a `_post.md` with the title, description and hashtags for YouTube Shorts, TikTok and Instagram Reels, plus a cover image and a caption file. Ask for it with *"write the post kit for s3"* or *"give me titles and hashtags for all of them"*, and Claude offers it whenever a short passes QA. See [Post kit](#6-post-kit-social-media-copy-for-every-short).

Every edit is a versioned plan you can undo, every render is QA-checked automatically, and **nothing is uploaded or posted unless you ask**: the opt-in `ytpost` schedules a YouTube upload, private until its publish time, only when you run it. See [Schedule uploads to YouTube](#8-schedule-uploads-to-youtube-opt-in).

```
record ─▶ transcribe ─▶ plan ─▶ render ─▶ QA ─▶ tweak / undo ─▶ post kit ─▶ approve
          whisper       Claude   ffmpeg    auto   new version      social copy  log only
```

## Features

- **Idea picker.** Scores your video ideas (hook, specificity, payoff, one-take fit, authority) and writes the hook line and hook-card text before you record.
- **Sentence-level transcript** with word timings, and fillers kept visible as `(um)`. A speaker-labelled `.vtt` that comes with the recording is used to tell who said what.
- **Claude-written edit plans.** Claude reads the transcript and picks the cuts. Plans are immutable JSON (`v001`, `v002`, …) with frozen clip times; `undo` and `use vN` move a pointer, and nothing is overwritten.
- **Filler and pause tightening.** Removes every um/uh, re-scanning the chosen ranges because Whisper drops fillers on long files. It caps pauses, snaps clip edges to real words, and checks audio energy so a cut never lands inside a word.
- **Speaker-aware vertical crop.** Per clip, `track: left | right | largest`. It follows that person through the source's camera switches, which are detected and pinned to the exact frame.
- **Full-frame cleanup mode** for demos and screen recordings. A pause is only cut when the screen is also still, with the webcam bubble masked out of the motion measurement.
- **Captions and hook card.** Burned in, word-by-word highlighted, with per-plan `word_fixes` for misheard names.
- **Stabilization.** For handheld, walking, vehicle or boat footage, `"stabilize": true` in a plan removes camera shake (vid.stab, two passes): deliberate pans stay, the jitter goes. The source is stabilized once per project and cached, with the same frames, timestamps and audio, so cuts, transcript and captions still line up; HDR is tone-mapped in the same pass. Off by default (tripod shots and screen recordings don't need it).
- **Brands: a look per show.** Caption font, colors and word highlight (colored word or a box behind it), and the hook card (colors, alignment, an optional prompt and cursor for a typed-terminal card), set once per show in `brands/<name>/brand.json`. `brand.py preview` shows it on a still in seconds. Ships with two examples, `terminal` and `gold`.
- **Color.** iPhone HDR (HLG/PQ) is tone-mapped to SDR BT.709, so it looks right everywhere.
- **Audio.** Two-pass loudnorm to −14 LUFS with the true peak at or below −2 dBTP, measured on the finished AAC file (AAC encoding adds peaks, so pass 2 is redone with a lower target when it does), with optional compression, high-pass, and denoise.
- **Social media post kit** per short: cover image, `.srt` caption file, and `_post.md` with title, description and tags for YouTube Shorts, TikTok and Instagram Reels (from a `_post.json` Claude writes; the episode link is set once per project).
- **Scheduled YouTube uploads (opt-in).** `ytpost.py` uploads a short with its post kit's title, description, tags and caption track, as a private video with a scheduled publish time (the next free daily slot, or a time you pick), so you can check it in YouTube Studio first. It uses the official YouTube Data API through your own Google Cloud project.
- **Automatic QA** on every render: A/V sync measured on decoded content, duration, color, loudness, caption coverage, hook card, fillers remaining (the output is re-transcribed), joins (clipped, doubled or stray words at every cut), framing, and motion (a frozen picture, judged on every frame, since sampled stills can't show one). Each render also gets a contact sheet.
- **Local and private.** Recordings, transcripts, and renders stay on your disk. The only code that sends anything anywhere is `ytpost.py`, and only when you run it.

## Requirements

Runs on **Apple Silicon Macs** (Whisper on the Metal GPU via MLX, VideoToolbox encode/decode) and on
**Linux** (Whisper on an NVIDIA GPU via CUDA, NVENC encode), or on any CPU, slowly. `setup.sh` picks
the backend for you.

| | macOS (Apple Silicon) | Linux |
|---|---|---|
| Speech-to-text | mlx-whisper on the Metal GPU | faster-whisper on CUDA (CPU fallback) |
| Video encode | h264_videotoolbox | h264_nvenc (libx264 fallback) |
| Software | `python3`, `curl`, ffmpeg **with libass + zimg** | `python3-venv`, `curl`, ffmpeg |
| GPU driver | nothing extra | NVIDIA driver only. CUDA/cuDNN come as pip wheels in the venv |
| Agent | Claude chat + NoBGP MCP connector (remote) | or [Claude Code](https://docs.claude.com/en/docs/claude-code/overview) on the machine |

```bash
# macOS: Homebrew's plain ffmpeg lacks the subtitles and zscale filters; ffmpeg-full has them
brew install ffmpeg-full

# Ubuntu
sudo apt install -y python3-venv ffmpeg curl
```

**Measured render times** (render + QA, as a multiple of the finished clip's length; lower is faster):

| Job | Mac mini M4, 16 GB | Linux, RTX 3050 + 4-core CPU |
|---|---|---|
| HDR short (10-bit HLG HEVC, tone-mapped to SDR) | **~0.7×** | ~2× (CPU tone mapping dominates) |
| SDR short | ~0.7× | ~1.2–1.35× (podcast, with speaker tracking) |
| Full-length cleanup (8 min interview / 3 min screen recording) | **~0.35×** | ~0.6× |
| Transcription, `medium.en` (8 min interview) | ~0.1× audio length | ~0.08× audio length |

## Install

```bash
git clone https://github.com/lowerpower/cutcannon.git
cd cutcannon
./setup.sh
```

If something breaks later (say, after a `brew upgrade`), run `python bin/doctor.py`: it checks ffmpeg, the GPU, the speech model and the rest, and prints the exact fix for anything wrong.

`setup.sh` is idempotent and uses no `sudo`. It creates `.venv/`, installs CUDA wheels only if an NVIDIA GPU is present, downloads the Montserrat font and the YuNet face model, installs the two skills into `~/.claude/skills/` (where Claude Code finds them), and finishes with a self-test:

```
  whisper: cuda | face model: ok | opencv 5.0.0
  encoder: h264_nvenc
  font: Montserrat Black
```

## Connect Claude

**Option A: Claude chat + NoBGP (the usual way).** Your conversation runs in Claude; every command runs on the GPU machine.

1. Put the GPU machine on your NoBGP network (install the NoBGP agent; the NoBGP connector can generate the registration command).
2. In Claude, add the NoBGP MCP connector: `https://mcp.nobgp.com/mcp`.
3. Give Claude the workflow: add `skills/cutcannon-editor/SKILL.md` and `skills/cutcannon-idea-picker/SKILL.md` to your Claude account as custom skills, or paste them into a Claude Project's instructions.
4. Tell Claude where the toolkit lives, e.g. *"cutcannon is in ~/cutcannon on my gpu-box node."*

Renders stay on the GPU machine. Ask Claude to copy finished files to another of your nodes (a laptop, say) when you want them there.

**Option B: Claude Code on the machine.** `setup.sh` already installed the skills, so just run `claude` in the repo.

**Unattended batches** (overnight, or from a script) use Claude Code's print mode. Pin the model with `--model`, so a long batch runs, and bills, on the model you chose rather than on whatever the machine's default happens to be:

```bash
cd ~/cutcannon && claude -p --model sonnet "Use the cutcannon-editor skill, unattended: make 5 shorts from podcast-ep12, render them, and report each short's QA line and notes."
```

A headless run also needs permission to run the toolkit's commands (Claude Code's `--allowedTools` and `--permission-mode` options). The skill's *Unattended runs* section sets what such a run fixes on its own, what it leaves for you, and how many jobs it runs at once. It never uploads or posts.

## Quick start

Put each recording in its own project folder on the GPU machine:

```bash
mkdir projects/product-demo && mv ~/Downloads/ProductDemo.mov projects/product-demo/
```

Then just ask Claude. If you don't say which project, what job, or how many clips, Claude shows the
project list and asks. Pick a number of clips, or **auto** to have Claude read the whole transcript
and propose as many as the material supports. It always proposes first and renders only what you pick.

> **"Let's make some clips."** → which project? shorts or cleanup? 3, 5, or auto?
> **"Clean up product-demo: remove the false starts, dead pauses, and get the audio to −14 LUFS."**
> **"Recommend 5 clips from podcast-ep12."** → **"Generate the first one."**
> **"Open on the second story and lose the last sentence."** → new version, re-rendered.
> **"Write the post kit for s1."** → `s1_v002_post.md`: YouTube Shorts, TikTok and Instagram Reels titles, descriptions and hashtags, plus a cover and a caption file.
> **"Undo that."**   **"Approve s1."** (recorded, still nothing posted)
> **"Create a CutCannon brand for my show from its look."** → a preview still to tweak, then every short uses it.

Before recording, try: **"Score these ideas: …"** → the idea picker ranks them and writes your hook.

## Layout

```
cutcannon/
├── setup.sh                 install + self-test
├── requirements*.txt        pinned, verified versions: Linux, -cuda (NVIDIA only), -mac (Apple Silicon)
├── bin/
│   ├── projects.py          status of every project (what's new, transcribed, rendered, QA)
│   ├── postkit.py           cover, caption file and YouTube / TikTok / Instagram copy per short
│   ├── ytpost.py            opt-in: scheduled YouTube uploads (private until their publish time)
│   ├── brand.py             per-show looks: list / show / preview
│   ├── doctor.py            checks the machine, says exactly what to fix (run anytime)
│   ├── asr.py               speech-to-text backends: mlx-whisper (Apple) / faster-whisper (CUDA, CPU)
│   ├── transcribe.py        recording → sentence lines, word timings, fillers
│   ├── plan.py              versioned plans: save / list / show / undo / use / approve / words
│   ├── render.py            tighten → crop/track → captions + hook → encode → loudnorm → QA
│   └── qa.py                9 checks + contact sheet
├── brands/                  a look per show: brand.json (+ fonts); terminal and gold examples
├── skills/
│   ├── cutcannon-idea-picker/SKILL.md
│   └── cutcannon-editor/SKILL.md
└── projects/                one folder per recording (git-ignored, see projects/README.md)
    └── <name>/
        ├── <source>.mov  [+ optional speaker .vtt]
        ├── transcript.json / transcript.txt / meta.json
        ├── plans/v001.json … CURRENT
        ├── renders/<id>_vNNN.mp4  _qa.json  _frames.png  _render.json
        │          + post kit: _cover.jpg  .srt  _post.json  _post.md
        │          + _youtube.json    the upload's record, once scheduled with ytpost
        ├── post.json            shared post details: credits, source title, episode link
        └── approvals.json
```

## How it works

### 1. Transcribe

```bash
python bin/transcribe.py product-demo                     # media already in projects/product-demo/
python bin/transcribe.py ~/Downloads/take.mov --name x  # or import: the file is MOVED into projects/x/
```

```
# product-demo  source=ProductDemo.mov  duration=182.0s  1440x1080@30.0
[L000 0.40-3.12] (Uh,) so this is, (uh,) the quick demo.
[L001 3.42-5.62] (Um,) first we'll log in and open the dashboard.
   ...pause 1.6s
```

### 2. Plan

Claude writes a draft and saves it as a new version. Clips are transcript lines, lines cut at a
word, or exact seconds:

```json
{ "shorts": [{
    "id": "s1",
    "hook_text": "The bug took 3 weeks. The fix took 1 line.",
    "clips": [
      { "from": "L140", "from_word": 11, "to": "L141", "track": "left" },
      { "from": "L148", "to": "L152",                   "track": "right" },
      { "start": 732.48, "end": 739.08,                  "track": "right" }
    ],
    "word_fixes": { "postgress": "Postgres" }
}]}
```

```bash
python bin/plan.py words podcast-ep12 L140 L141   # numbered words, for word cuts
python bin/plan.py save  podcast-ep12 draft.json --note "why this version exists"
```

`words` prints each line as `1:and 2:I 3:think …`, fillers in brackets (they count). `from_word`
starts the clip at that word of the `from` line, `to_word` ends it after that word of the `to`
line. `save` and `show` print the words either side of every mid-line cut, so a wrong number is
obvious before anything renders.

| Field | Default | Meaning |
|---|---|---|
| `clips` | | played in order; `{"from","to"}` line ids, optionally `from_word` / `to_word` (1-based), or `{"start","end"}` seconds |
| `clips[].track` | `largest` | whose face the vertical crop follows: `left`, `right`, `largest` |
| `format` | `vertical` | `vertical` = 1080×1920 short (≤ 60 s); `source` = original frame, any length |
| `hook_text`, `hook_seconds` | `""`, 2.5 | on-screen hook card |
| `captions` | on for vertical | word-by-word burned-in captions |
| `tighten` | `{"fillers": true, "max_pause": 0.2}` | cut um/uh and cap pauses (seconds) |
| `punch_in` | on for vertical | alternate 108% zoom at cuts to hide jump cuts |
| `audio` | `{}` | `compress`, `highpass` (Hz), `denoise`; loudnorm to −14 LUFS always |
| `reframe` | `face` | or fixed `center` / `left` / `right` crop |
| `word_fixes` | `{}` | caption corrections, case-insensitive |
| `brand` | none | the show's look from `brands/<name>/brand.json`; at the top of the plan for every short, or per short |

`save` validates first, with exact error messages, and freezes the resolved clip times into the version, so re-transcribing later can never change what an old version renders.

### 3. Render

```bash
python bin/render.py podcast-ep12         # every short in the CURRENT plan
python bin/render.py podcast-ep12 s3      # one short
python bin/render.py product-demo --preview   # half resolution, fast
```

### 4. QA (automatic)

```
s3_v004.mp4  49.6s -> 46.8s  (9 segments, punch-in)  nvenc
  QA PASS: av_sync=ok duration=ok color=ok loudness=ok captions=ok hook_card=ok fillers=ok joins=ok framing=ok motion=ok
  time: prep 22.9s | encode 17.4s | loudnorm 8.3s | qa 10.2s | total 58.8s = 1.21x the video length
```

| Check | Passes when |
|---|---|
| `av_sync` | decoded audio and video lengths within 45 ms (about 1 frame) |
| `duration` | matches the plan; ≤ 60 s for vertical |
| `color` | 8-bit BT.709 output, and an HDR source was actually tone-mapped |
| `loudness` | −14 ± 1.5 LUFS, true peak ≤ −1.0 dBTP (renders aim for ≤ −2.0; loudness range reported) |
| `captions` | ≥ 95% of speech captioned (n/a when captions are off) |
| `hook_card` | present if and only if the plan has one |
| `fillers` | ≤ 1 um/uh found when the output is re-transcribed |
| `joins` | at every cut, the re-transcription has no word or phrase missing (clipped) or doubled. Warnings that don't fail but are printed as `note:` lines even on a PASS, to check by ear: `extra` (a word at the cut that the captions don't have: usually a real word the transcript skipped, sometimes a cut-off fragment), `filler` (an um/uh left at a cut when fillers were meant to be cut) and `repeat` (the speaker really repeats words). `changed` (probably a mis-hearing) is only listed in `_qa.json`. The words either side of every edit are listed in `_qa.json` for review. n/a for renders older than segment logging |
| `framing` | tracked face within the middle 60% of a vertical frame. A `note:` when the face is under 10% of the frame width in most sampled frames: a wide shot, where the speaker reads small on a phone |
| `motion` | no stretch of 2 s or more where the picture doesn't change at all, judged on every frame. On a captioned vertical short only the picture above the captions counts: captions change with every word, so they can't hide a stuck picture. A 1-2 s freeze is a `note:`. `_qa.json` also has `change_per_s`, how much the picture changes each second, to spot dead stretches and check that cuts register. n/a for a full-video cleanup: screen recordings hold still by nature, so their still stretches are reported, not judged |

### 5. Review, undo, approve

```bash
python bin/plan.py list  podcast-ep12     # history, * = CURRENT
python bin/plan.py undo  podcast-ep12     # back to the parent version (nothing deleted)
python bin/plan.py use   podcast-ep12 v2
python bin/plan.py approve podcast-ep12 s1
```

### 6. Post kit: social media copy for every short

When you're happy with a short, ask for its post kit: *"write the post kit for s3"*, *"titles and
hashtags for all of them"*, *"what should I post this with?"*. Claude writes the copy into
`renders/<tag>_post.json`, matched to what the clip actually says, then runs:

```bash
python bin/postkit.py podcast-ep12        # every short in the CURRENT plan
python bin/postkit.py podcast-ep12 s3     # one short
```

Next to each render (`<tag>` is the newest render, e.g. `s3_v004`) you get:

| File | What it is |
|---|---|
| `<tag>_post.md` | ready-to-paste copy: YouTube Shorts title, description, hashtags and tags; TikTok caption; Instagram Reels caption and hashtags; alt text; a pinned comment; posting notes |
| `<tag>_cover.jpg` | cover / thumbnail: the frame showing the hook card |
| `<tag>.srt` | caption file for YouTube or LinkedIn, with the same words and fixes as the burned-in captions |

Details every short shares (show title, credits, the full-episode link) go once in
`projects/<name>/post.json`. `postkit.py` checks platform limits (YouTube title up to 100 characters,
at most 30 Instagram hashtags) and flags a missing episode link. It only writes files: post them yourself,
or schedule a YouTube upload with `ytpost.py` ([section 8](#8-schedule-uploads-to-youtube-opt-in)).

A `_post.md` looks like this:

```markdown
# s3: "The bug took 3 weeks. The fix took 1 line."

**Video:** `s3_v004.mp4` · 46.8 s · 1080×1920 · cover `s3_v004_cover.jpg` · captions `s3_v004.srt`

## YouTube Shorts

**Title:** Three weeks chasing a bug. The fix was one line.

**Description:**

Why a missing index took down checkout for three weeks, and the one-line fix.

#Shorts #debugging #postgres

## TikTok

**Caption:**

3 weeks of debugging, 1 line of code 😅 #debugging #coding #devlife

## Instagram Reels

**Caption:**

Three weeks for one line. Here's what it was.

#debugging #coding #softwareengineering
```

### 7. Brands: a look per show

Every show can have its own captions and hook card. Ask *"create a CutCannon brand for my show from
its look"*, or write `brands/<name>/brand.json` yourself. Only the fields you change are needed:

```json
{
 "description": "Typed-terminal hook card and captions with the spoken word on a blue box",
 "captions": {"font": "Montserrat ExtraBold", "highlight": "#2F6FEB", "highlight_style": "box"},
 "hook": {"font": "JetBrains Mono", "bold": true, "color": "#F2F2F2", "box": "#0D1117",
          "uppercase": false, "align": "left", "prefix": "> ", "prefix_color": "#4FA3FF", "cursor": "_"}
}
```

```bash
python bin/brand.py preview terminal podcast-ep12   # one still -> brands/terminal/preview.png
```

Then put `"brand": "terminal"` in the plan. Saving freezes a copy of the brand into that version,
so old versions keep their look. Fields and defaults: [brands/README.md](brands/README.md).

### 8. Schedule uploads to YouTube (opt-in)

`ytpost.py` uploads a video through the official YouTube Data API as **private, with a scheduled
publish time**: it goes public on its own at that time, and you can check it in YouTube Studio first.
The title, description, tags and caption track come from the post kit. Nothing is uploaded unless you
run it, or ask Claude to schedule a specific short and say yes to its dry run.

**One-time setup** (about 5 minutes, in the Google Cloud console, as the account that owns the channel):

1. Create a project and enable **YouTube Data API v3**.
2. **Google Auth Platform → Get started**: any app name. Audience **External** for a channel on a
   personal Google account (**Internal** if it's on a Workspace account in the same organization as the
   project). For External, then click **Audience → Publish app**: an app left in *Testing* has its
   sign-in expire after 7 days, and scheduled uploads stop working.
3. **Clients → Create client → Desktop app**, and download its JSON.
4. Sign in, once per channel (`mycal` is just your name for the channel):

```bash
python bin/ytpost.py auth mycal --client-secret ~/Downloads/client_secret_XXXX.json
#   (add --scope upload for a token that can't edit or delete anything; see Permissions below)
#   prints a Google link: open it on any device, sign in, pick the channel. Google then sends you to a
#   127.0.0.1 page that won't load; copy that page's address, then:
python bin/ytpost.py auth mycal --code 'http://127.0.0.1:8765/?state=...&code=...'
```

Google says "Google hasn't verified this app" because the app is yours and unreviewed: **Advanced →
Go to (your app)**. The client secret, each channel's sign-in token and its settings stay in
`~/.config/cutcannon/youtube/`, readable only by you.

**Permissions.** You choose at sign-in how much the token may do, with `--scope`:

| `--scope` | Google permissions | Can | Can't |
|---|---|---|---|
| `full` (default) | `youtube.upload` + `youtube.force-ssl` | upload, schedule, thumbnails, caption tracks, playlists | |
| `upload` | `youtube.upload` + `youtube.readonly` | upload, schedule, thumbnails, check the channel, `queue` | caption tracks, playlists, or editing or deleting anything |

`full` is needed for caption tracks and playlist adds, and Google only offers those in a permission
that also lets the token edit and delete the channel's videos, captions and comments. If the token
is stolen, `upload` limits the damage to new videos (which you can delete); `full` puts the existing
videos at risk too. Pick `upload` if your shorts have burned-in captions and you don't need playlists.
Either way the token reaches YouTube only, not the rest of the Google account.

To change permissions, sign in again with the other `--scope` (`set` won't change them). To revoke
access entirely: Google Account → Security → Third-party apps → your app → remove access.

Sign in with the Google account that owns the channel. People invited through YouTube Studio →
Permissions (Manager, Editor) can't sign in to a channel through the API; only its owner (or an
owner or manager of its Brand Account) can.

**Use:**

```bash
python bin/ytpost.py post mycal podcast-ep12 s3 --dry-run        # what would go up, and when
python bin/ytpost.py post mycal podcast-ep12 s3                  # next free daily slot
python bin/ytpost.py post mycal podcast-ep12 s3 --at "2026-12-01 18:30"
python bin/ytpost.py post mycal --video ~/videos/talk.mp4 --meta ~/videos/talk_post.json   # any video
python bin/ytpost.py queue mycal                                 # scheduled and recent uploads
python bin/ytpost.py set mycal slots=10:00,18:00 category_id=28  # change the channel's defaults
```

| Setting (`set`) | Default | Meaning |
|---|---|---|
| `slots` | `10:00` | daily publish times `post` picks from; `--slots` overrides them for one upload |
| `tz` | `America/Los_Angeles` | time zone for the slots and `--at` |
| `category_id` | `22` (People & Blogs) | e.g. `28` Science & Technology, `10` Music, `24` Entertainment |
| `playlist_id` | none | add every upload to this playlist (`--playlist` for one upload) |
| `min_lead_minutes` | `120` | `post` never picks a slot sooner than this |
| `caption_language` | `en` | language of the `.srt` caption track |

Other `post` options: `--synthetic` sets YouTube's disclosure for realistic AI-generated or altered
content; `--thumbnail FILE` sets a custom thumbnail (long-form videos; Shorts don't take one);
`--no-captions` skips the `.srt`. Each upload writes `<tag>_youtube.json` next to the video, which
stops the same file going up twice (`--force` overrides). A vertical or square video up to 3 minutes
becomes a Short.

**Limits.** By default the API allows 100 uploads a day per Google Cloud project, plus 10,000 units a
day for everything else; a caption track costs 400 units and a playlist add 50, so roughly 20 fully
dressed uploads a day. The quota resets at midnight Pacific.

## Known limitations

- The vertical crop assumes the speaker is on camera. B-roll inserted in the source falls back to a center crop.
- A 720p source cropped to vertical is upscaled about 2.7×, so it looks soft. Use the highest-resolution original you have.
- HDR tone mapping runs on the CPU. On Apple Silicon that's fast (~0.7× clip length); on a small Linux CPU it dominates render time. GPU tone mapping via libplacebo works on Linux but produces a different look and is not the default yet.
- Whisper can invent text over music or applause. Every transcription runs a voice-activity detector first (Silero, on both platforms) and drops lines spoken at impossible speed, so this is filtered out, but check captions on clips that cut into music.
- Whisper occasionally won't transcribe a filler at all and stretches the neighboring word instead. QA catches it, and it's fixed with a clip boundary.

## Acknowledgements

Inspired by the workflow in Single Grain's open-source `video-editor`; this is an independent implementation. Built on [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [FFmpeg](https://ffmpeg.org/), [OpenCV](https://opencv.org/) with the [YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) face detector, and the [Montserrat](https://github.com/JulietaUla/Montserrat) typeface (SIL OFL).

## Roadmap

See [ROADMAP.md](ROADMAP.md).

## License

MIT. See [LICENSE](LICENSE).
