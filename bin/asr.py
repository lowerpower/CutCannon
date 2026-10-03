#!/usr/bin/env python3
"""asr.py - one speech-to-text interface over two Whisper backends.

  Apple Silicon (macOS arm64)  mlx-whisper on the Metal GPU
  everything else              faster-whisper: CUDA if available, else CPU (int8)

transcribe(audio, prompt=None, vad=False, model=None)
    audio: a media file path, or 16 kHz mono float32 numpy array
    returns segments in faster-whisper's shape, which the rest of cutcannon uses:
    seg.start, seg.end, seg.text, seg.words -> [w.word, w.start, w.end, w.probability]

Overrides: CUTCANNON_ASR=mlx|faster, CUTCANNON_ASR_MODEL=<size> (default medium.en).
"""
import os, platform, sys
from types import SimpleNamespace

DEFAULT_MODEL = os.environ.get("CUTCANNON_ASR_MODEL", "medium.en")

# faster-whisper size name -> converted MLX weights on Hugging Face
MLX_REPOS = {
    "tiny.en": "mlx-community/whisper-tiny.en-mlx",
    "base.en": "mlx-community/whisper-base.en-mlx",
    "small.en": "mlx-community/whisper-small.en-mlx",
    "medium.en": "mlx-community/whisper-medium.en-mlx",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
    "large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
}

_FASTER = {}


def backend():
    b = os.environ.get("CUTCANNON_ASR")
    if b in ("mlx", "faster"):
        return b
    return "mlx" if sys.platform == "darwin" and platform.machine() == "arm64" else "faster"


def _faster_model(model):
    if model not in _FASTER:
        from faster_whisper import WhisperModel
        try:
            _FASTER[model] = (WhisperModel(model, device="cuda", compute_type="float16"), "cuda")
        except Exception as e:
            print(f"cuda unavailable ({str(e)[:80]}); using cpu", file=sys.stderr)
            _FASTER[model] = (WhisperModel(model, device="cpu", compute_type="int8"), "cpu")
    return _FASTER[model]


def describe(model=None):
    """Human-readable backend/device, e.g. 'mlx (Metal)' or 'faster-whisper (cuda)'."""
    model = model or DEFAULT_MODEL
    if backend() == "mlx":
        return f"mlx-whisper {model} (Metal GPU)"
    return f"faster-whisper {model} ({_faster_model(model)[1]})"


_VAD_SCRIPT = r"""
import sys, json, numpy as np
from faster_whisper.vad import get_speech_timestamps, VadOptions
src = sys.argv[1]
if src.endswith('.f32'):
    a = np.fromfile(src, dtype=np.float32)
else:
    from faster_whisper.audio import decode_audio
    a = decode_audio(src, sampling_rate=16000)
ts = get_speech_timestamps(a, VadOptions(min_silence_duration_ms=400, speech_pad_ms=200))
print(json.dumps([[t['start'] / 16000, t['end'] / 16000] for t in ts]))
"""


def _speech_clips(audio):
    """Silero VAD (shipped with faster-whisper) -> flat [start, end, start, end, ...] in seconds.
    Used to give mlx-whisper only the stretches where someone is talking: on music, applause
    or silence Whisper can loop on an invented sentence (seen: 31 copies of one line), or add
    a phantom word over B-roll.

    Runs in a SUBPROCESS on purpose: faster-whisper loads PyAV, and on macOS PyAV and OpenCV
    both bundle libavdevice with the same Objective-C classes; loading both into the render
    process crashed it. A separate process keeps them apart."""
    import json, subprocess, tempfile
    import numpy as np
    tmp = None
    if isinstance(audio, str):
        src = audio
    else:
        tmp = tempfile.NamedTemporaryFile(suffix=".f32", delete=False)
        np.asarray(audio, dtype=np.float32).tofile(tmp.name)
        tmp.close()
        src = tmp.name
    try:
        r = subprocess.run([sys.executable, "-c", _VAD_SCRIPT, src], capture_output=True, text=True)
    finally:
        if tmp:
            os.unlink(tmp.name)
    if r.returncode != 0:
        raise RuntimeError(f"VAD failed: {r.stderr.strip()[-300:]}")
    spans = json.loads(r.stdout.strip().splitlines()[-1])
    return [round(x, 3) for a, b in spans for x in (a, b)]


def transcribe(audio, prompt=None, vad=False, model=None):
    model = model or DEFAULT_MODEL
    if backend() == "mlx":
        import mlx_whisper
        clips = "0"
        if vad:
            clips = _speech_clips(audio)
            if not clips:
                return []  # no speech at all
        r = mlx_whisper.transcribe(audio, path_or_hf_repo=MLX_REPOS.get(model, model),
                                   word_timestamps=True, initial_prompt=prompt, verbose=None,
                                   clip_timestamps=clips, hallucination_silence_threshold=2.0)
        segs = []
        for s in r.get("segments", []):
            words = [SimpleNamespace(word=w["word"], start=float(w["start"]), end=float(w["end"]),
                                     probability=float(w.get("probability", 1.0)))
                     for w in s.get("words", [])]
            segs.append(SimpleNamespace(start=float(s["start"]), end=float(s["end"]),
                                        text=s.get("text", ""), words=words))
        return segs
    m, _ = _faster_model(model)
    kw = {"word_timestamps": True, "initial_prompt": prompt}
    if vad:
        kw.update(vad_filter=True, vad_parameters={"min_silence_duration_ms": 400})
    segs, _ = m.transcribe(audio, **kw)
    return list(segs)


if __name__ == "__main__":  # quick check: python bin/asr.py file.wav [model]
    import time
    t = time.time()
    out = transcribe(sys.argv[1], model=sys.argv[2] if len(sys.argv) > 2 else None)
    print(describe(sys.argv[2] if len(sys.argv) > 2 else None), f"{time.time() - t:.1f}s")
    print(" ".join(w.word.strip() for s in out for w in s.words))
