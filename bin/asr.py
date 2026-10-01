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


def transcribe(audio, prompt=None, vad=False, model=None):
    model = model or DEFAULT_MODEL
    if backend() == "mlx":
        import mlx_whisper
        # mlx-whisper has no VAD; `vad` is ignored (long silences can occasionally
        # produce a stray hallucinated phrase - QA's caption and filler checks catch it)
        r = mlx_whisper.transcribe(audio, path_or_hf_repo=MLX_REPOS.get(model, model),
                                   word_timestamps=True, initial_prompt=prompt, verbose=None)
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
