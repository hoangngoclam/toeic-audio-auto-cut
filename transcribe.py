#!/usr/bin/env python3
# Transcribe an audio file to timestamped segments -> transcript.json
# CLI:    .venv/bin/python transcribe.py <input.mp3> [model]
# Module: from transcribe import transcribe ; transcribe(audio, out_path)
# ponytail: faster-whisper does everything; we just dump segments to JSON.

import json
import os
import sys

from faster_whisper import WhisperModel

MODEL_SIZE = os.environ.get("WHISPER_MODEL", "small")


def transcribe(audio, out_path="transcript.json", model_size=MODEL_SIZE):
    """Transcribe audio -> list of {start, end, text}, also written to out_path."""
    # int8 on CPU = fast enough for a 45-min English file on Apple Silicon.
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(audio, language="en", word_timestamps=False)
    out = [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segments]
    with open(out_path, "w") as f:
        json.dump(out, f, indent=1)
    print(f"{len(out)} segments -> {out_path}")
    return out


if __name__ == "__main__":
    audio = sys.argv[1]
    model = sys.argv[2] if len(sys.argv) > 2 else MODEL_SIZE
    transcribe(audio, "transcript.json", model)
