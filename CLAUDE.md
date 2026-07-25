# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# deps (.venv already exists in the project root)
.venv/bin/python -m pip install -r requirements.txt

# run the service
.venv/bin/uvicorn server.app:app --reload      # http://127.0.0.1:8000

# run the audio steps standalone (fastest way to debug cue detection).
# groq_asr also prints per-stage wall-clock — that's the speed test.
.venv/bin/python -m server.audio.groq_asr test-files/Test_07.mp3 transcript.json
.venv/bin/python -m server.audio.cut test-files/Test_07.mp3 clips transcript.json

# is a file accepted as TOEIC? (no arg = run the keyword-vote self-check)
.venv/bin/python -m server.audio.verify test-files/Test_07.mp3
.venv/bin/python -m server.audio.verify
```

`python server/audio/cut.py ...` also works: neither module imports from `server`, which is
the point of the split — the audio core has no dependency on the web layer.

No test suite, no linter config, no build step — the one check that exists is
`server/audio/verify.py`'s `_self_check()` (run the module with no args). `ffmpeg` +
`ffprobe` must be on PATH.

Uploads go to `jobs/<uuid>/` and are deleted in `finally`; when Drive is unconfigured the
zip lands in `results/<job_id>_<name>_clips.zip` and the "email" is printed to the server log.
Both dirs plus `clips/` and `*.mp3` are gitignored.

## Architecture

Python only: FastAPI + Groq Whisper + ffmpeg. Two earlier prototypes — `cut.js` and the
in-browser Transformers.js player under `web/` — were deleted per the design spec once
`cut.py` matched them; comments still referencing `cut.js` are historical.

`server/` is the web layer (`app.py`, `pipeline.py`, `config.py`, `drive.py`, `sheets.py`,
`mailer.py`); `server/audio/` is the audio core (`verify.py`, `groq_asr.py`, `cut.py`) and
imports nothing from its parent. Keep that arrow one-way — that's why the audio package
reads its own `GROQ_*` env vars and calls `load_dotenv()` in its `__init__.py`, rather than
importing `server.config`.

### ASR

Groq hosted Whisper (`whisper-large-v3-turbo`) is the only backend, ~150MB RSS — which is
why it replaced faster-whisper (~700MB–1GB per worker, doesn't fit the 2GB VPS). Don't add
a local backend back without a reason; `server/config.py` fails at import when
`GROQ_API_KEY` is missing, so a misconfigured box dies at startup instead of mid-job.

`groq_asr.py` re-encodes to 16kHz mono 32kbps mp3 before upload: measured 43.7MB → 10.0MB in
6s on a 45-min file, which keeps it under Groq's 25MB free-tier cap (100MB on the dev tier,
`GROQ_MAX_UPLOAD_MB`). Don't "improve" this to FLAC — lossless 16kHz mono is ~128kbps and
inflated the same file to 81.6MB. `CUE_PROMPT` biases the model toward the stock TOEIC
phrasings, which is what makes the spoken question numbers reliable.

### Service flow

`POST /submit` (`server/app.py`) gates in cheapest-first order, and every gate the customer
can trip answers on screen: email shape → `.mp3` → **per-email quota** (one Sheets read) →
stream to disk under `MAX_UPLOAD_MB` (never trusts a header) → **`verify_toeic`** (~5s).
Only then does it log a `pending` Sheets row and `pool.submit(...)`. `pool` is a
`ThreadPoolExecutor(max_workers=2)` — deliberately replaces the spec's Redis+RQ queue while
keeping the "max 2 concurrent jobs" guarantee. Jobs do **not** survive a restart; add RQ if
that matters.

`server/pipeline.py::process_job` runs transcribe → cut → zip → Drive upload → email →
mark the Sheets row → cleanup. Every failure marks the row `error`, logs the traceback, and
sends **two** mails through `_notify` (independent, so a bad mailbox on one side can't
swallow the other): an apology to the customer, and the raw traceback to
`config.ADMIN_EMAIL` — otherwise an `error` row is the only trace and nobody notices.
`server/drive.py`, `server/sheets.py` and `server/mailer.py` are all no-op/raise-guarded on
missing creds so local testing needs no `.env`.

`server/drive.py` passes `supportsAllDrives=True` and expects `GDRIVE_FOLDER_ID` to live on a
**Shared drive**. This is not optional: a service account has no storage quota of its own, so
uploading into a My Drive folder fails with `403 storageQuotaExceeded` no matter how the
folder is shared. `_explain()` turns Drive's 20-line JSON errors into one actionable line —
it's the last line of the traceback, so it survives a `journalctl` page and lands at the
bottom of the admin mail.

`ponytail:` a Sheets outage during `POST /submit` (the 503 path) only logs — no admin mail,
because that fires once per attempt and would flood the mailbox. Failures there are visible
to the customer immediately; job failures are not, which is why only jobs mail out.

### Quota + customer log (`server/sheets.py`)

One Google Sheet row per accepted job, tab `customers-info`:
`A Email | B Status | C Link resource | D Time` (E is intentionally unused). Status goes
`pending` → `done` / `error`.

The quota counts only `done` rows, so a job that fails doesn't burn one of the customer's
`MAX_JOBS_PER_EMAIL` (5) tries. A Sheets outage returns **503, never a free job** — the
service must not hand out work it can't quota-check. `ponytail:` the count-then-append is
not atomic, so two simultaneous submits from the same email can both squeeze past the 5th;
the fix if it ever matters is a per-email lock, not a database.

### TOEIC format gate (`server/audio/verify.py`)

`cut.py`'s layout is hard-coded to a full Q1–100 listening test, so anything else yields
garbage. `verify_toeic` runs two cheap gates inside the request: duration (35–60 min), then
a Groq transcription of the **first 90s** which must hit ≥2 of `MARKERS` (the stock
directions wording). It calls `post_audio(..., prompt="")` on purpose — `CUE_PROMPT` would
prime the model with TOEIC phrasing, which is precisely how you'd make any file look like
TOEIC. Consequence to know: a real test with its opening directions trimmed off is
**rejected**, since the evidence we check for is gone.

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
- `server/audio/{cut,groq_asr,verify}.py` are dual-purpose: importable module + `__main__` CLI. Keep both working.
- Config is read once at import in `server/config.py`; no other `os.environ` reads outside it (except `server/audio/groq_asr.py`, which must stay independent of the web layer).
