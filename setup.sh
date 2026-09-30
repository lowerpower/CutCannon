#!/usr/bin/env bash
# setup.sh - install cutcannon + Claude Code skills. Idempotent; safe to re-run.
#   Linux + NVIDIA : GPU transcription (CUDA wheels, no system CUDA needed) + NVENC if ffmpeg has it
#   Linux CPU / macOS : CPU transcription (int8), libx264 encode
# Needs (not installed by this script): python3 (+venv), ffmpeg, curl.
#   Ubuntu: sudo apt install -y python3-venv ffmpeg curl     macOS: brew install ffmpeg python
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
say() { printf '\033[1;33m==>\033[0m %s\n' "$*"; }
die() { printf '\033[1;31mxx\033[0m %s\n' "$*" >&2; exit 1; }

say "checking prerequisites"
command -v python3 >/dev/null || die "python3 missing"
command -v ffmpeg  >/dev/null || die "ffmpeg missing (apt install ffmpeg / brew install ffmpeg)"
command -v curl    >/dev/null || die "curl missing"
python3 -c 'import venv, ensurepip' 2>/dev/null || die "python venv missing (Ubuntu: sudo apt install python3-venv)"

GPU=cpu
if command -v nvidia-smi >/dev/null && nvidia-smi -L >/dev/null 2>&1; then GPU=cuda; fi
say "accelerator: $GPU  ($(uname -s)/$(uname -m))"

say "python venv + packages"
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt
[ "$GPU" = cuda ] && pip install -q -r requirements-cuda.txt

say "env.sh"
cat > env.sh <<'EOF'
# source this before running any cutcannon script
CUTCANNON="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
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
if [ "$(uname -s)" = Darwin ]; then FD="$HOME/Library/Fonts"; else FD="$HOME/.local/share/fonts"; fi
mkdir -p "$FD" && cp -n fonts/*.ttf "$FD/" 2>/dev/null || true
command -v fc-cache >/dev/null && fc-cache -f >/dev/null || true

say "Claude Code skills -> ~/.claude/skills"
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
import cv2, faster_whisper
from faster_whisper.audio import decode_audio
d = cv2.FaceDetectorYN.create("$ROOT/models/yunet.onnx", "", (320, 320))
a = decode_audio("/tmp/cutcannon-selftest.wav", sampling_rate=16000)  # the media path transcription uses
assert abs(len(a) - 16000) < 400, len(a)
dev = "$GPU"
if dev == "cuda":
    from faster_whisper import WhisperModel
    WhisperModel("tiny.en", device="cuda", compute_type="float16")
print("  whisper:", dev, "| audio decode: ok | face model: ok | opencv", cv2.__version__)
EOF
rm -f /tmp/cutcannon-selftest.wav
ENC="$(ffmpeg -hide_banner -encoders 2>/dev/null || true)"
if [[ "$ENC" == *h264_nvenc* ]] && \
   ffmpeg -hide_banner -loglevel error -f lavfi -i color=s=256x256:d=0.1 -c:v h264_nvenc -f null - 2>/dev/null; then
  echo "  encoder: h264_nvenc"; else echo "  encoder: libx264 (no working NVENC)"; fi
FONTS_SEEN="$(fc-list 2>/dev/null || true)"
if [[ "$FONTS_SEEN" == *"Montserrat Black"* ]]; then echo "  font: Montserrat Black"
elif [ "$(uname -s)" = Darwin ]; then echo "  font: installed to ~/Library/Fonts"
else echo "  font: NOT visible to fontconfig (captions will fall back to a default font)"; fi

say "done. Start with:  cd $ROOT && claude   then: \"cut shorts from /path/to/take.mp4\""
