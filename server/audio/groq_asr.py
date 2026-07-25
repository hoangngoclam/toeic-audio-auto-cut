#!/usr/bin/env python3
"""Transcribe via Groq's hosted Whisper (OpenAI-compatible endpoint).

Why this exists: faster-whisper needs ~700MB-1GB RSS per worker, which doesn't
fit a 2GB VPS. Groq does the inference, so this process stays under ~150MB.

Why we re-encode first: Groq caps uploads at 25MB (free tier) / 100MB (dev
tier) and downsamples to 16kHz mono server-side anyway. Measured on a 45-min
test file: 43.7MB -> 10.0MB as 16kHz mono 32kbps mp3, 6s of ffmpeg.
NOT FLAC — lossless 16kHz mono lands around 128kbps, which inflated the same
file to 81.6MB and blew the cap. 32kbps is plenty for speech, and all we need
out of the transcript is "Number seven." and the group announcements.

response_format=verbose_json returns segments as {start, end, text} — the same
shape cut.py already reads, so nothing downstream changes.

CLI (this is the speed test — prints per-stage wall-clock):
    .venv/bin/python -m server.audio.groq_asr <input.mp3> [out.json]
"""

import json
import os
import subprocess
import sys
import tempfile
import time

import requests

ENDPOINT = "https://api.groq.com/openai/v1/audio/transcriptions"
API_KEY = os.environ.get("GROQ_API_KEY", "")
MODEL = os.environ.get("GROQ_MODEL", "whisper-large-v3-turbo")
# Free tier is 25MB; raise via env if you're on the dev tier.
MAX_UPLOAD_MB = int(os.environ.get("GROQ_MAX_UPLOAD_MB", "25"))
# (connect, read) — a 45-min file is a long single request.
TIMEOUT = (10, 900)


def to_asr_mp3(src, dst, seconds=None):
    """Re-encode to 16kHz mono 32kbps mp3. Raises CalledProcessError on failure.

    seconds: keep only the first N seconds (verify.py samples the opening)."""
    head = ["-t", str(seconds)] if seconds else []
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", src, *head,
         "-ar", "16000", "-ac", "1", "-map", "0:a",
         "-c:a", "libmp3lame", "-b:a", "32k", dst],
        check=True,
    )
    return dst


def post_audio(path, model, prompt=""):
    """POST the audio file, return parsed JSON. Raises RuntimeError on API error.

    NO PROMPT, ON PURPOSE — leave it empty. Whisper treats the prompt as
    preceding context and regurgitates it verbatim over the long answer pauses
    a TOEIC test is full of, destroying the real cue in that 30s window. Cues
    recovered by cut.py, measured on both test files:

        prompt                        Test_07              Test_01
        stock TOEIC phrasing     22/23 grp, 6 lost    21/23 grp, 9 lost
        numbers only             12/23 grp, 4 lost              -
        "" (this)                23/23 grp, 0 lost    23/23 grp, 0 lost

    Priming made the spoken numbers *less* reliable, not more: one prompt line
    ("Questions 71 through 73 refer to the following talk.") came back as runs
    of "Questions 72 through 34 refer to the following talk." every 30s, each
    one eating a "Number N." Don't add a prompt back without re-running that
    table. verify.py also passes "" so a non-TOEIC file can't be primed into
    looking like one."""
    size_mb = os.path.getsize(path) / 1024 / 1024
    if size_mb > MAX_UPLOAD_MB:
        raise RuntimeError(
            f"{path} is {size_mb:.1f}MB, over the {MAX_UPLOAD_MB}MB upload cap. "
            "Raise GROQ_MAX_UPLOAD_MB if you're on the dev tier (100MB), or "
            "split the file.")

    with open(path, "rb") as f:
        r = requests.post(
            ENDPOINT,
            headers={"Authorization": f"Bearer {API_KEY}"},
            files={"file": (os.path.basename(path), f, "audio/mpeg")},
            # timestamp_granularities defaults to "segment" for verbose_json.
            data={"model": model, "language": "en", "temperature": "0",
                  "response_format": "verbose_json", "prompt": prompt},
            timeout=TIMEOUT,
        )

    if r.status_code != 200:
        # Body may carry a useful reason (bad key, rate limit, file too long).
        # The key lives in the header, so echoing the body leaks nothing.
        raise RuntimeError(f"Groq API {r.status_code}: {r.text[:500]}")
    return r.json()


def transcribe_groq(audio, out_path="transcript.json", model=MODEL):
    """Transcribe audio via Groq -> list of {start, end, text}, written to out_path.

    Raises RuntimeError if the key is missing or the API rejects the request,
    FileNotFoundError if audio doesn't exist.
    """
    if not API_KEY:
        raise RuntimeError("GROQ_API_KEY not set (put it in .env).")
    if not os.path.exists(audio):
        raise FileNotFoundError(f"input not found: {audio}")

    with tempfile.TemporaryDirectory() as tmp:
        small = to_asr_mp3(audio, os.path.join(tmp, "asr.mp3"))
        payload = post_audio(small, model)

    segments = payload.get("segments")
    if not segments:
        # verbose_json without segments means we can't cut anything.
        raise RuntimeError(
            "Groq returned no segments — check response_format/verbose_json.")

    out = [{"start": s["start"], "end": s["end"], "text": s["text"].strip()}
           for s in segments]
    with open(out_path, "w") as f:
        json.dump(out, f, indent=1)
    print(f"{len(out)} segments -> {out_path}")
    return out


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python -m server.audio.groq_asr <input.mp3> [out.json]")
    audio = sys.argv[1]
    out_path = sys.argv[2] if len(sys.argv) > 2 else "transcript.json"

    if not API_KEY:
        sys.exit("GROQ_API_KEY not set (put it in .env).")

    t0 = time.perf_counter()
    with tempfile.TemporaryDirectory() as tmp:
        small = to_asr_mp3(audio, os.path.join(tmp, "asr.mp3"))
        t1 = time.perf_counter()
        src_mb = os.path.getsize(audio) / 1024 / 1024
        up_mb = os.path.getsize(small) / 1024 / 1024
        print(f"preprocess  {t1 - t0:6.1f}s   {src_mb:.1f}MB -> {up_mb:.1f}MB")

        payload = post_audio(small, MODEL)
        t2 = time.perf_counter()
        print(f"api         {t2 - t1:6.1f}s   model={MODEL}")

    segments = payload.get("segments") or []
    out = [{"start": s["start"], "end": s["end"], "text": s["text"].strip()}
           for s in segments]
    with open(out_path, "w") as f:
        json.dump(out, f, indent=1)

    audio_len = payload.get("duration") or (out[-1]["end"] if out else 0)
    total = t2 - t0
    speed = audio_len / total if total else 0
    print(f"total       {total:6.1f}s   {len(out)} segments -> {out_path}")
    print(f"audio {audio_len / 60:.1f} min -> {speed:.0f}x realtime")
