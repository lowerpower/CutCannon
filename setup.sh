#!/usr/bin/env bash
# setup.sh - install cutcannon (+ its skills for Claude Code). Idempotent; safe to re-run.
#   macOS, Apple Silicon : mlx-whisper on the Metal GPU, VideoToolbox encode/decode
#   Linux + NVIDIA       : faster-whisper on CUDA (pip wheels, no system CUDA), NVENC
#   anything else        : faster-whisper on CPU, libx264
# Needs (not installed by this script): python3 (+venv), curl, and ffmpeg WITH libass + zimg
# (the subtitles and zscale filters):
#   Ubuntu: sudo apt install -y python3-venv ffmpeg curl
#   macOS : brew tap homebrew-ffmpeg/ffmpeg && brew install homebrew-ffmpeg/ffmpeg/ffmpeg --with-zimg
#           (Homebrew's default ffmpeg has neither filter)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
say() { printf '\033[1;33m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }
OS=$(uname -s); ARCH=$(uname -m)
[ "$OS" = Darwin ] && export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"

say "checking prerequisites"
command -v python3 >/dev/null || die "python3 missing"
command -v ffmpeg  >/dev/null || die "ffmpeg missing (see the top of setup.sh)"
command -v curl    >/dev/null || die "curl missing"
python3 -c 'import venv, ensurepip' 2>/dev/null || die "python venv missing (Ubuntu: sudo apt install python3-venv)"
FILTERS="$(ffmpeg -hide_banner -filters 2>/dev/null || true)"
for f in subtitles zscale loudnorm ebur128; do
  if [[ "$FILTERS" != *" $f "* ]]; then
    if [ "$OS" = Darwin ]; then
      die "ffmpeg has no '$f' filter. Fix: brew uninstall ffmpeg; brew tap homebrew-ffmpeg/ffmpeg; brew install homebrew-ffmpeg/ffmpeg/ffmpeg --with-zimg"
    else
      die "ffmpeg has no '$f' filter. Install an ffmpeg built with libass and zimg."
    fi
  fi
done

if [ "$OS" = Darwin ] && [ "$ARCH" = arm64 ]; then ACC=mlx;  REQ=requirements-mac.txt
elif command -v nvidia-smi >/dev/null && nvidia-smi -L >/dev/null 2>&1; then ACC=cuda; REQ=requirements.txt
else ACC=cpu; REQ=requirements.txt; fi
say "accelerator: $ACC  ($OS/$ARCH)"

say "python venv + packages ($REQ)"
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r "$REQ"
[ "$ACC" = cuda ] && pip install -q -r requirements-cuda.txt

say "env.sh"
cat > env.sh <<'EOF'
# source this before running any cutcannon script
CUTCANNON="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
[ "$(uname -s)" = Darwin ] && export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
. "$CUTCANNON/.venv/bin/activate"
SITE=$(python -c 'import site;print(site.getsitepackages()[0])')
[ -d "$SITE/nvidia/cublas/lib" ] && export LD_LIBRARY_PATH="$SITE/nvidia/cublas/lib:$SITE/nvidia/cudnn/lib:${LD_LIBRARY_PATH:-}"
export CUTCANNON
EOF

say "fonts + face model"
mkdir -p fonts models projects
if [ ! -f fonts/Montserrat-Black.ttf ]; then
  base=https://raw.githubusercontent.com/JulietaUla/Montserrat/master/fonts/ttf
  curl -fsSL -o fonts/Montserrat-Black.ttf "$base/Montserrat-Black.ttf"
  curl -fsSL -o fonts/Montserrat-ExtraBold.ttf "$base/Montserrat-ExtraBold.ttf"
fi
[ -f models/yunet.onnx ] || curl -fsSL -o models/yunet.onnx \
  https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx
if [ "$OS" = Darwin ]; then FD="$HOME/Library/Fonts"; else FD="$HOME/.local/share/fonts"; fi
mkdir -p "$FD" && cp -n fonts/*.ttf "$FD/" 2>/dev/null || true
command -v fc-cache >/dev/null && fc-cache -f >/dev/null 2>&1 || true

say "skills -> ~/.claude/skills (for Claude Code)"
mkdir -p "$HOME/.claude/skills"
for s in skills/*/; do
  n=$(basename "$s"); mkdir -p "$HOME/.claude/skills/$n"
  sed "s#~/cutcannon#$ROOT#g" "$s/SKILL.md" > "$HOME/.claude/skills/$n/SKILL.md"
done
chmod +x bin/*.py

say "self-test"
. ./env.sh
ffmpeg -v error -y -f lavfi -i sine=f=440:d=1 -ac 1 /tmp/cutcannon-selftest.wav
python - <<EOF
import sys, cv2
sys.path.insert(0, "$ROOT/bin")
import asr, render
cv2.FaceDetectorYN.create("$ROOT/models/yunet.onnx", "", (320, 320))
asr.transcribe("/tmp/cutcannon-selftest.wav", model="tiny.en")  # real decode + model load on this backend
print("  whisper:", asr.describe("tiny.en"), "| face model: ok | opencv", cv2.__version__)
print("  encoder:", render.pick_encoder())
EOF
rm -f /tmp/cutcannon-selftest.wav
FONTS_SEEN="$(fc-list 2>/dev/null || true)"
if [[ "$FONTS_SEEN" == *"Montserrat Black"* ]]; then echo "  font: Montserrat Black"
elif [ "$OS" = Darwin ]; then echo "  font: installed to ~/Library/Fonts (captions also load it from ./fonts)"
else echo "  font: NOT visible to fontconfig (captions will fall back to a default font)"; fi

say "done. Drive it from a Claude chat via the NoBGP MCP connector, or locally: cd $ROOT && claude"
