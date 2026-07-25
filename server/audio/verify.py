#!/usr/bin/env python3
"""Is this upload actually a TOEIC listening test?

cut.py's layout is hard-coded to a full listening test (Q1-100), so any other
recording produces garbage clips. Two gates, both cheap enough to run inside
the HTTP request so the customer sees the rejection on screen:

  1. duration — a real listening test runs ~45 min.
  2. the spoken opening — transcribe the first 90s and look for the stock
     directions. prompt="" on purpose: CUE_PROMPT would prime the model with
     TOEIC phrasing, which is exactly how you'd make any file look like TOEIC.

Cost: ffmpeg on 90s + one small Groq call, ~5s. A file that fails never pays
for the full transcription.

Self-check:  .venv/bin/python -m server.audio.verify
CLI:         .venv/bin/python -m server.audio.verify <input.mp3>
"""

import os
import re
import subprocess
import sys
import tempfile

from server.audio.cut import ffprobe_duration
from server.audio.groq_asr import MODEL, post_audio, to_asr_mp3

# A full listening test is ~45 min. Wide band so a re-encode or a trimmed
# lead-in doesn't get rejected.
MIN_MINUTES = 35
MAX_MINUTES = 60
SAMPLE_SECONDS = 90

# ponytail: keyword vote over the opening directions. 2 hits has no realistic
# false positive on ordinary speech, and every real test says most of these in
# its first minute. Upgrade path if it ever misfires: transcribe the whole file
# and require N question cues before cutting (costs a full ASR call to reject).
MARKERS = (
    r"listening test",
    r"\bpart\s+(?:one|1)\b",
    r"\bdirections?\b",
    r"test book",
    r"answer sheet",
    r"statements? about a picture",
    r"look at the (?:example|picture)",
)
MIN_MARKERS = 2


def looks_like_toeic(text):
    """True when the transcribed opening reads as TOEIC listening directions."""
    return sum(1 for p in MARKERS if re.search(p, text, re.I)) >= MIN_MARKERS


def verify_toeic(audio, model=MODEL):
    """Return None when audio looks like a TOEIC listening test, else a short
    English reason. The caller turns that into a user-facing Vietnamese error."""
    if not os.path.exists(audio):
        raise FileNotFoundError(f"input not found: {audio}")

    try:
        minutes = ffprobe_duration(audio) / 60
    except (ValueError, OSError):
        return "ffprobe found no duration — not a readable audio file"
    if not MIN_MINUTES <= minutes <= MAX_MINUTES:
        return (f"duration {minutes:.0f} min, a TOEIC listening test is "
                f"{MIN_MINUTES}-{MAX_MINUTES} min")

    try:
        with tempfile.TemporaryDirectory() as tmp:
            sample = to_asr_mp3(audio, os.path.join(tmp, "head.mp3"),
                                seconds=SAMPLE_SECONDS)
            payload = post_audio(sample, model, prompt="")
    except subprocess.CalledProcessError:
        return "ffmpeg could not decode the audio"

    text = payload.get("text") or " ".join(
        s.get("text", "") for s in payload.get("segments") or [])
    if not looks_like_toeic(text):
        return f"opening is not TOEIC directions: {text[:200]!r}"
    return None


def _self_check():
    real = ("This is the TOEIC Listening test. Part One. Directions: For each "
            "question in this part, you will hear four statements about a "
            "picture in your test book.")
    assert looks_like_toeic(real)
    # A single incidental "directions" must not be enough.
    assert not looks_like_toeic("Follow the directions on the screen, please.")
    assert not looks_like_toeic(
        "Welcome back to the podcast. Today we discuss interest rates and "
        "what the central bank does next.")
    assert not looks_like_toeic("")
    print("looks_like_toeic: ok")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        _self_check()
    else:
        reason = verify_toeic(sys.argv[1])
        print("TOEIC" if reason is None else f"NOT TOEIC — {reason}")
        sys.exit(0 if reason is None else 1)
