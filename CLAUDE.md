# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# deps (.venv already exists in the project root)
.venv/bin/python -m pip install -r requirements.txt

# run the service
.venv/bin/uvicorn server.app:app --reload      # http://127.0.0.1:8000

# run the audio steps standalone (fastest way to debug cue detection)
.venv/bin/python -m server.audio.transcribe test-files/Test_07.mp3 [model]  # -> transcript.json
.venv/bin/python -m server.audio.cut test-files/Test_07.mp3 clips transcript.json
```

`python server/audio/cut.py ...` also works: neither module imports from `server`, which is
the point of the split — the audio core has no dependency on the web layer.

No test suite, no linter config, no build step. `ffmpeg` + `ffprobe` must be on PATH.

Uploads go to `jobs/<uuid>/` and are deleted in `finally`; when Drive is unconfigured the
zip lands in `results/<job_id>_<name>_clips.zip` and the "email" is printed to the server log.
Both dirs plus `clips/` and `*.mp3` are gitignored.

## Architecture

Python only: FastAPI + faster-whisper + ffmpeg. Two earlier prototypes — `cut.js` and the
in-browser Transformers.js player under `web/` — were deleted per the design spec once
`cut.py` matched them; comments still referencing `cut.js` are historical.

`server/` is the web layer (`app.py`, `pipeline.py`, `config.py`, `drive.py`, `mailer.py`);
`server/audio/` is the audio core (`transcribe.py`, `cut.py`) and imports nothing from its
parent. Keep that arrow one-way.

### Service flow

`POST /submit` (`server/app.py`) validates email + `.mp3`, streams the upload to disk while
enforcing `MAX_UPLOAD_MB` (never trusts a header), then `pool.submit(...)` and returns 200
immediately. `pool` is a `ThreadPoolExecutor(max_workers=2)` — deliberately replaces the
spec's Redis+RQ queue while keeping the "max 2 concurrent jobs" guarantee. Jobs do **not**
survive a restart; add RQ if that matters.

`server/pipeline.py::process_job` runs transcribe → cut → zip → Drive upload → email →
cleanup. Every failure is caught, emails the customer a friendly Vietnamese message, and
logs the traceback. `server/drive.py` and `server/mailer.py` are both no-op/raise-guarded on
missing creds so local testing needs no `.env`.

### How cutting actually works (`server/audio/cut.py`)

Clip boundaries come from what the recording *says*, not from fixed offsets. Two separate
maps are built from the transcript because the right anchor differs per part:

- `group_start_of[a]` — "Questions 32 through 34 refer to…" → true start of a Part 3/4 passage.
- `single_start_of[n]` — "Number 7." → start of a Part 1/2 question.

A group's questions are *also* read individually, so single cues must never override a group
announcement. Layout is hard-coded to a standard test: Q1–31 one clip each, Q32–100 in
groups of 3 (`SINGLES_END`, `GROUP_STARTS`). Each clip ends where the next one starts; the
last ends at the `ffprobe` duration. ffmpeg uses `-c copy` (no re-encode), so cutting is I/O
cheap — transcription dominates job time.

Missing cues are warned about on stderr but don't fail the job; zero cues raises
`RuntimeError`.

## Conventions

- User-facing strings (HTTP errors, emails, UI) are **Vietnamese**. Code, comments and logs are English.
- Deliberate simplifications are marked with `# ponytail:` comments naming the ceiling and the upgrade path. Don't refactor them into abstractions without a reason.
- `server/audio/cut.py` and `transcribe.py` are dual-purpose: importable module + `__main__` CLI. Keep both working.
- Config is read once at import in `server/config.py`; no other `os.environ` reads outside it (except `transcribe.py`'s CLI default).
