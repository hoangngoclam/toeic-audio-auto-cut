# TOEIC Listening Player

A static web app: upload a TOEIC listening mp3 → it's transcribed **in the browser**
(no server, nothing uploaded) → the test is split into per-question buttons that jump
into the audio. Part 3 & 4 keep their 3 questions together (e.g. `32–34`, `71–73`).

## How it works

- `public/index.html` — the whole app (HTML + CSS + JS, no build step).
- Transcription runs via [Transformers.js](https://github.com/huggingface/transformers.js)
  (`whisper-base.en`) loaded from a CDN. The model (~40 MB) downloads once and is cached.
- Question boundaries come from the spoken cues ("Number 7.", "Questions 32 through 34…",
  "Question 80-82.") matched against the standard TOEIC structure
  (Part 1: Q1–6, Part 2: Q7–31, Part 3: Q32–70 in 3s, Part 4: Q71–100 in 3s).
- Playback uses one `<audio>` element and seeks (`currentTime`) to each question's start,
  auto-stopping at the next question.

## Deploy to Vercel

```bash
cd web
npx vercel        # or: connect this folder in the Vercel dashboard
```

`vercel.json` sets `outputDirectory: public` and the **required**
`Cross-Origin-Opener-Policy` / `Cross-Origin-Embedder-Policy` headers — without them the
browser blocks the threaded WebAssembly that whisper needs (`crossOriginIsolated` must be
true).

## Run locally

A plain static server is **not** enough — you need the COOP/COEP headers. Use a server
that sets both:

```
Cross-Origin-Opener-Policy: same-origin
Cross-Origin-Embedder-Policy: require-corp
```

then open the page.

## Notes / limits

- The part ranges assume a **standard 100-question TOEIC test**. A non-standard file will
  mis-map; adjust the ranges in `partOf()` and `detectQuestions()` in `index.html`.
- A 45-minute file takes a few minutes to transcribe on a laptop and is heavy on phones.
- `whisper-base.en` is English-only; that's correct for TOEIC listening.
