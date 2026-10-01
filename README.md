# CutCannon

**Record once. Claude does the edit.**

`cutcannon` turns raw recordings (a phone take, a two-person podcast, a screen-recorded demo) into finished video on your own GPU machine. You drive it in plain English from a **Claude chat**, which reaches that machine through the **NoBGP MCP connector**. You work from anywhere while the heavy lifting runs on your own hardware. Running [Claude Code](https://docs.claude.com/en/docs/claude-code/overview) directly on the machine works too. It does two jobs:

- **Shorts:** cut vertical 1080×1920 clips with word-by-word captions, a hook card, and a crop that follows whoever is speaking.
- **Cleanup:** keep the full video in its original frame, and remove false starts, ums, and dead pauses (only pauses where the screen is also still), with audio at −14 LUFS.

Every edit is a versioned plan you can undo, every render is QA-checked automatically, and **nothing is ever uploaded or posted**.

```
record ─▶ transcribe ─▶ plan ─▶ render ─▶ QA ─▶ tweak / undo ─▶ approve
          whisper       Claude   ffmpeg    auto   new version      log only
```

## Features

- **Idea picker.** Scores your video ideas (hook, specificity, payoff, one-take fit, authority) and writes the hook line and hook-card text before you record.
- **Sentence-level transcript** with word timings, and fillers kept visible as `(um)`. A speaker-labelled `.vtt` that comes with the recording is used to tell who said what.
- **Claude-written edit plans.** Claude reads the transcript and picks the cuts. Plans are immutable JSON (`v001`, `v002`, …) with frozen clip times; `undo` and `use vN` move a pointer, and nothing is overwritten.
- **Filler and pause tightening.** Removes every um/uh, re-scanning the chosen ranges because Whisper drops fillers on long files. It caps pauses, snaps clip edges to real words, and checks audio energy so a cut never lands inside a word.
- **Speaker-aware vertical crop.** Per clip, `track: left | right | largest`. It follows that person through the source's camera switches, which are detected and pinned to the exact frame.
- **Full-frame cleanup mode** for demos and screen recordings. A pause is only cut when the screen is also still, with the webcam bubble masked out of the motion measurement.
- **Captions and hook card.** Burned in, word-by-word highlighted, with per-plan `word_fixes` for misheard names.
- **Color.** iPhone HDR (HLG/PQ) is tone-mapped to SDR BT.709, so it looks right everywhere.
- **Audio.** Two-pass loudnorm to −14 LUFS / −1.5 dBTP, with optional compression, high-pass, and denoise.
- **Automatic QA** on every render: A/V sync measured on decoded content, duration, color, loudness, caption coverage, hook card, fillers remaining (the output is re-transcribed), and framing. Each render also gets a contact sheet.
- **Local and private.** Recordings, transcripts, and renders stay on your disk. There is no posting code.

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
# macOS: Homebrew's default ffmpeg lacks the subtitles and zscale filters, so use the full build
brew tap homebrew-ffmpeg/ffmpeg && brew install homebrew-ffmpeg/ffmpeg/ffmpeg --with-zimg

# Ubuntu
sudo apt install -y python3-venv ffmpeg curl
```

**Measured render times** (render + QA, as a multiple of the finished clip's length; lower is faster):

| Job | Mac mini M4, 16 GB | Linux, RTX 3050 + 4-core CPU |
|---|---|---|
| HDR short (10-bit HLG HEVC, tone-mapped to SDR) | **~0.7×** | ~2× (CPU tone mapping dominates) |
| SDR short | ~0.7× | ~1.2–1.35× (podcast, with speaker tracking) |
| 3:02 → 2:35 full cleanup (screen recording) | not yet measured | ~0.6× |
| Transcription, `medium.en`, warm | ~0.18× audio length | ~0.08× audio length |

## Install

```bash
git clone https://github.com/lowerpower/cutcannon.git
cd cutcannon
./setup.sh
```

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
> **"Undo that."**   **"Approve s1."** (recorded, still nothing posted)

Before recording, try: **"Score these ideas: …"** → the idea picker ranks them and writes your hook.

## Layout

```
cutcannon/
├── setup.sh                 install + self-test
├── requirements*.txt        pinned, verified versions: Linux, -cuda (NVIDIA only), -mac (Apple Silicon)
├── bin/
│   ├── projects.py          status of every project (what's new, transcribed, rendered, QA)
│   ├── asr.py               speech-to-text backends: mlx-whisper (Apple) / faster-whisper (CUDA, CPU)
│   ├── transcribe.py        recording → sentence lines, word timings, fillers
│   ├── plan.py              versioned plans: save / list / show / undo / use / approve
│   ├── render.py            tighten → crop/track → captions + hook → encode → loudnorm → QA
│   └── qa.py                8 checks + contact sheet
├── skills/
│   ├── cutcannon-idea-picker/SKILL.md
│   └── cutcannon-editor/SKILL.md
└── projects/                one folder per recording (git-ignored, see projects/README.md)
    └── <name>/
        ├── <source>.mov  [+ optional speaker .vtt]
        ├── transcript.json / transcript.txt / meta.json
        ├── plans/v001.json … CURRENT
        ├── renders/<id>_vNNN.mp4  _qa.json  _frames.png  _render.json
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

Claude writes a draft and saves it as a new version. Clips are transcript lines or exact seconds:

```json
{ "shorts": [{
    "id": "s1",
    "hook_text": "The bug took 3 weeks. The fix took 1 line.",
    "clips": [
      { "start": 646.40, "end": 656.64, "track": "left" },
      { "from": "L148", "to": "L152",   "track": "right" }
    ],
    "word_fixes": { "postgress": "Postgres" }
}]}
```

```bash
python bin/plan.py save podcast-ep12 draft.json --note "why this version exists"
```

| Field | Default | Meaning |
|---|---|---|
| `clips` | | played in order; `{"from","to"}` line ids or `{"start","end"}` seconds |
| `clips[].track` | `largest` | whose face the vertical crop follows: `left`, `right`, `largest` |
| `format` | `vertical` | `vertical` = 1080×1920 short (≤ 60 s); `source` = original frame, any length |
| `hook_text`, `hook_seconds` | `""`, 2.5 | on-screen hook card |
| `captions` | on for vertical | word-by-word burned-in captions |
| `tighten` | `{"fillers": true, "max_pause": 0.2}` | cut um/uh and cap pauses (seconds) |
| `punch_in` | on for vertical | alternate 108% zoom at cuts to hide jump cuts |
| `audio` | `{}` | `compress`, `highpass` (Hz), `denoise`; loudnorm to −14 LUFS always |
| `reframe` | `face` | or fixed `center` / `left` / `right` crop |
| `word_fixes` | `{}` | caption corrections, case-insensitive |

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
  QA PASS: av_sync=ok duration=ok color=ok loudness=ok captions=ok hook_card=ok fillers=ok framing=ok
  time: prep 22.9s | encode 17.4s | loudnorm 8.3s | qa 10.2s | total 58.8s = 1.21x the video length
```

| Check | Passes when |
|---|---|
| `av_sync` | decoded audio and video lengths within 45 ms (about 1 frame) |
| `duration` | matches the plan; ≤ 60 s for vertical |
| `color` | 8-bit BT.709 output, and an HDR source was actually tone-mapped |
| `loudness` | −14 ± 1.5 LUFS, true peak ≤ −1.0 dBFS (loudness range reported) |
| `captions` | ≥ 95% of speech captioned (n/a when captions are off) |
| `hook_card` | present if and only if the plan has one |
| `fillers` | ≤ 1 um/uh found when the output is re-transcribed |
| `framing` | tracked face within the middle 60% of a vertical frame |

### 5. Review, undo, approve

```bash
python bin/plan.py list  podcast-ep12     # history, * = CURRENT
python bin/plan.py undo  podcast-ep12     # back to the parent version (nothing deleted)
python bin/plan.py use   podcast-ep12 v2
python bin/plan.py approve podcast-ep12 s1
```

## Known limitations

- The vertical crop assumes the speaker is on camera. B-roll inserted in the source falls back to a center crop.
- A 720p source cropped to vertical is upscaled about 2.7×, so it looks soft. Use the highest-resolution original you have.
- HDR tone mapping runs on the CPU. On Apple Silicon that's fast (~0.7× clip length); on a small Linux CPU it dominates render time. GPU tone mapping via libplacebo works on Linux but produces a different look and is not the default yet.
- mlx-whisper has no voice-activity filter, so very long silences can occasionally produce a stray phrase. QA's caption and filler checks catch it.
- Whisper occasionally won't transcribe a filler at all and stretches the neighboring word instead. QA catches it, and it's fixed with a clip boundary.

## Acknowledgements

Inspired by the workflow in Single Grain's open-source `video-editor`; this is an independent implementation. Built on [faster-whisper](https://github.com/SYSTRAN/faster-whisper), [FFmpeg](https://ffmpeg.org/), [OpenCV](https://opencv.org/) with the [YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) face detector, and the [Montserrat](https://github.com/JulietaUla/Montserrat) typeface (SIL OFL).

## License

MIT. See [LICENSE](LICENSE).
