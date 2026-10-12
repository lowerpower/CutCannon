#!/usr/bin/env python3
"""doctor.py - check this machine for everything cutcannon needs, and say how to fix what's missing.

  python bin/doctor.py          quick checks (a few seconds, no model loading)
  python bin/doctor.py --full   also loads the speech model and transcribes a test tone

Run it after installing, after a `brew upgrade` / `apt upgrade`, or whenever a render fails
in a way that looks environmental. Exit code is non-zero if anything required is broken.
"""
import importlib.util, json, os, platform, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bin"))
MAC = sys.platform == "darwin"
OK, WARN, FAIL = "ok  ", "WARN", "FAIL"
results = []


def check(status, what, detail="", fix=""):
    results.append(status)
    line = f"[{status}] {what}" + (f": {detail}" if detail else "")
    print(line)
    if fix and status != OK:
        print(f"       fix: {fix}")


def run(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except Exception as e:
        return subprocess.CompletedProcess(cmd, 1, "", str(e))


# --- python + venv -----------------------------------------------------------------------
v = sys.version_info
check(OK if v >= (3, 10) else FAIL, "python", f"{v.major}.{v.minor}.{v.micro} at {sys.executable}",
      "use Python 3.10+")
in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix) and Path(sys.prefix).resolve() == (ROOT / ".venv").resolve()
check(OK if in_venv else FAIL, "virtualenv", "cutcannon .venv active" if in_venv else f"running from {sys.prefix}",
      f"cd {ROOT} && . ./env.sh   (or run ./setup.sh first)")

# --- ffmpeg --------------------------------------------------------------------------------
ff = shutil.which("ffmpeg")
if not ff:
    check(FAIL, "ffmpeg", "not on PATH", "brew install ffmpeg-full" if MAC else "sudo apt install ffmpeg")
else:
    ver = run("ffmpeg", "-version").stdout.split("\n")[0][:40]
    check(OK, "ffmpeg", f"{ver}  ({ff})")
    filters = run("ffmpeg", "-hide_banner", "-filters").stdout
    missing = [f for f in ("subtitles", "zscale", "loudnorm", "ebur128") if f" {f} " not in filters]
    check(OK if not missing else FAIL, "ffmpeg filters",
          "subtitles, zscale, loudnorm, ebur128" if not missing else f"missing: {', '.join(missing)}",
          "brew install ffmpeg-full   (Homebrew's plain ffmpeg lacks libass/zimg; setup.sh puts "
          "ffmpeg-full first on PATH)" if MAC else "install an ffmpeg built with libass and zimg")
    if not shutil.which("ffprobe"):
        check(FAIL, "ffprobe", "not on PATH", "it ships with ffmpeg; check your PATH")

# --- encoder / GPU ---------------------------------------------------------------------------
try:
    import render
    enc = render.pick_encoder()
    hw = {"nvenc": "NVIDIA NVENC", "videotoolbox": "Apple VideoToolbox"}.get(enc)
    check(OK if hw else WARN, "video encoder", hw or "libx264 on the CPU (works, slower)",
          "NVIDIA: install the driver; Apple Silicon: use ffmpeg-full")
except Exception as e:
    check(FAIL, "video encoder", f"render.py failed to import: {e}")

# --- speech-to-text backend ----------------------------------------------------------------------
try:
    import asr
    b = asr.backend()
    need = ["mlx_whisper", "faster_whisper", "onnxruntime"] if b == "mlx" else ["faster_whisper", "onnxruntime"]
    miss = [m for m in need if importlib.util.find_spec(m) is None]
    check(OK if not miss else FAIL, "speech-to-text packages", f"{b} backend" + (f", missing {miss}" if miss else ""),
          "./setup.sh  (reinstalls pinned requirements)")
    if b == "mlx":
        import mlx.core as mx
        check(OK if mx.metal.is_available() else WARN, "Metal GPU", "available" if mx.metal.is_available() else "not available")
    else:
        nv = run("nvidia-smi", "--query-gpu=name,driver_version", "--format=csv,noheader")
        if nv.returncode == 0 and nv.stdout.strip():
            check(OK, "NVIDIA GPU", nv.stdout.strip().split("\n")[0])
        else:
            check(WARN, "NVIDIA GPU", "none found: transcription runs on the CPU (slower)")
    try:
        # read the version from package metadata: importing PyAV next to OpenCV on macOS
        # triggers a duplicate-library warning (the clash asr.py works around)
        from importlib.metadata import version, PackageNotFoundError
        av_ver = version("av")
        bad = tuple(int(x) for x in av_ver.split(".")[:2]) >= (19, 0)
        check(FAIL if bad else OK, "PyAV", av_ver, "pip install av==18.1.0   (19.x breaks faster-whisper 1.2.1)")
    except PackageNotFoundError:
        pass
    cache = Path.home() / ".cache" / "huggingface" / "hub"
    model = asr.DEFAULT_MODEL
    have = any(model in p.name for p in cache.glob("models--*")) if cache.exists() else False
    check(OK if have else WARN, f"speech model {model}", "downloaded" if have else "not downloaded yet",
          "nothing to do: it downloads on first use (~1.5 GB, one time)")
except Exception as e:
    check(FAIL, "speech-to-text", str(e))

# --- assets --------------------------------------------------------------------------------------
check(OK if (ROOT / "models" / "yunet.onnx").exists() else FAIL, "face model", "models/yunet.onnx", "./setup.sh")
fonts = list((ROOT / "fonts").glob("Montserrat-*.ttf"))
check(OK if fonts else FAIL, "caption font", f"{len(fonts)} Montserrat file(s)", "./setup.sh")
try:
    import cv2
    check(OK, "opencv", cv2.__version__)
except Exception as e:
    check(FAIL, "opencv", str(e), "./setup.sh")

# --- skills (Claude Code) ------------------------------------------------------------------------
sk = Path.home() / ".claude" / "skills" / "cutcannon-editor" / "SKILL.md"
if sk.exists():
    current = str(ROOT) in sk.read_text()
    check(OK if current else WARN, "Claude Code skills", "installed" if current else "installed but point elsewhere",
          "./setup.sh  (re-installs them for this checkout)")
else:
    check(WARN, "Claude Code skills", "not installed (only needed for Claude Code)", "./setup.sh")

# --- disk + repo ------------------------------------------------------------------------------------
free = shutil.disk_usage(ROOT).free / 1e9
check(OK if free > 20 else WARN, "disk free", f"{free:.0f} GB", "renders and sources need room; free some space")
g = run("git", "-C", str(ROOT), "status", "-sb")
if g.returncode == 0:
    head = g.stdout.split("\n")[0]
    dirty = len([l for l in g.stdout.split("\n")[1:] if l.strip()])
    check(WARN if ("behind" in head or dirty) else OK, "git checkout",
          head.replace("## ", "") + (f", {dirty} uncommitted change(s)" if dirty else ""),
          "git pull   (and commit or stash local changes)")

# --- full: real transcription ---------------------------------------------------------------------
if "--full" in sys.argv:
    wav = Path("/tmp/cutcannon-doctor.wav")
    r = run("ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:d=1", "-ac", "1", str(wav))
    try:
        import time
        t = time.time()
        asr.transcribe(str(wav), model="tiny.en")
        check(OK, "test transcription", f"{asr.describe('tiny.en')} in {time.time() - t:.1f}s")
    except Exception as e:
        check(FAIL, "test transcription", str(e)[:200], "./setup.sh")
    finally:
        wav.unlink(missing_ok=True)

n_fail, n_warn = results.count(FAIL), results.count(WARN)
print(f"\n{'all good' if not n_fail and not n_warn else f'{n_fail} problem(s), {n_warn} warning(s)'}"
      f"  ({platform.system()} {platform.machine()})")
sys.exit(1 if n_fail else 0)
