#!/usr/bin/env python3
# Cut a TOEIC listening test into one clip per question (or per Part 3/4
# passage) by reading the spoken "Questions X through Y..." cues from a
# whisper transcript, and naming files by the real question numbers.
#
# 1-1 port of cut.js. Same regexes, same TOEIC layout (Q1-31 singles,
# Q32-100 in groups of 3). ffmpeg does the cutting; structure comes from
# what the recording literally says.
#
# CLI:   .venv/bin/python -m server.audio.cut <input.mp3> [outDir] [transcript.json]
# Module: from server.audio.cut import cut ; cut(input, out_dir, transcript_path)

import json
import os
import re
import subprocess
import sys

# --- number words -> digits, so "thirty-two" also matches -----------------
ONES = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
        "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
        "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
        "seventy": 70, "eighty": 80, "ninety": 90, "hundred": 100}


def words_to_num(s):
    ok = False
    n = 0
    for t in re.split(r"\s+", s.lower().replace("-", " ")):
        if not t:
            continue
        if t in ONES:
            n += ONES[t]
            ok = True
        elif t in TENS:
            n += TENS[t]
            ok = True
    return n if ok else None


def parse_num(token):
    d = re.search(r"\d+", token)
    if d:
        return int(d.group(0))
    return words_to_num(token)


# Group cue, two phrasings TOEIC uses interchangeably:
#   "Questions 32 through 34 refer to..."   (words / "to" / "and")
#   "Question 80-82. Refer to..."           (digit hyphen digit)
# Single cue: "Question 7." / "Number 7." / "Look at ... number 1"
GROUP_WORD = re.compile(r"questions?\s+([\w-]+)\s+(?:through|to|and)\s+([\w-]+)", re.I)
GROUP_DASH = re.compile(r"questions?\s+(\d+)\s*[-–]\s*(\d+)", re.I)
SINGLE = re.compile(r"(?:^|\s)(?:question|number)\s+([\w-]+)\b", re.I)


def pad3(n):
    return "q" + str(n).zfill(3)


def range_label(a, b):
    return "q" + str(a).zfill(3) + "-" + str(b).zfill(3)


def ffprobe_duration(input_path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", input_path],
        capture_output=True, text=True,
    ).stdout.strip()
    return float(out)


def cut(input_path, out_dir="clips", transcript_path="transcript.json"):
    """Cut input_path into per-question clips. Returns list of clip dicts.

    Raises FileNotFoundError on bad input, RuntimeError if no cues are found
    (caller turns that into a friendly job error).
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"input not found: {input_path}")
    if not os.path.exists(transcript_path):
        raise FileNotFoundError(f"{transcript_path} not found")

    with open(transcript_path, encoding="utf-8") as f:
        segments = json.load(f)

    # Two maps, because the right anchor differs by part:
    #   group_start_of[a] = when "Questions a-b refer to..." is announced
    #                       -> true start of a Part 3/4 passage
    #   single_start_of[n] = when "Number n." is read aloud
    #                        -> true start of a Part 1/2 question
    # A group's questions are also read individually, so single cues must NOT
    # override the group announcement for Part 3/4.
    group_start_of = {}
    single_start_of = {}
    for s in segments:
        t = s["text"]
        g = GROUP_WORD.search(t) or GROUP_DASH.search(t)
        if g:
            a = parse_num(g.group(1))
            if a and 1 <= a <= 100 and a not in group_start_of:
                group_start_of[a] = s["start"]
            continue  # a group line is not a single cue
        m = SINGLE.search(t)
        if m:
            n = parse_num(m.group(1))
            if n and 1 <= n <= 100 and n not in single_start_of:
                single_start_of[n] = s["start"]

    # Standard TOEIC listening layout. Part 1/2 = one clip per question;
    # Part 3/4 = one clip per 3-question passage.
    # ponytail: hard-coded to the real test structure — change here for a
    # variant test with different ranges.
    SINGLES_END = 31
    GROUP_STARTS = list(range(32, 101, 3))  # 32,35,...,98

    clean = []
    for q in range(1, SINGLES_END + 1):
        if q in single_start_of:
            clean.append({"start": single_start_of[q], "label": pad3(q)})
    for a in GROUP_STARTS:
        b = min(a + 2, 100)
        # Prefer the group announcement (true passage start); fall back to the
        # first single cue only when no announcement was transcribed.
        start = group_start_of.get(a)
        if start is None:
            start = single_start_of.get(a, single_start_of.get(a + 1, single_start_of.get(b)))
        if start is not None:
            clean.append({"start": start, "label": range_label(a, b)})

    clean.sort(key=lambda x: x["start"])

    missing = []
    for q in range(1, SINGLES_END + 1):
        if q not in single_start_of:
            missing.append(str(q))
    for a in GROUP_STARTS:
        b = min(a + 2, 100)
        heard = (a in group_start_of or a in single_start_of
                 or (a + 1) in single_start_of or b in single_start_of)
        if not heard:
            missing.append(f"{a}-{b}")
    if missing:
        print(f"WARNING: no cue found for: {', '.join(missing)}\n", file=sys.stderr)

    if not clean:
        raise RuntimeError(
            "No question cues found in transcript. The directions may be "
            "phrased differently.")

    duration = ffprobe_duration(input_path)
    os.makedirs(out_dir, exist_ok=True)
    ext = os.path.splitext(input_path)[1] or ".mp3"

    print(f"{len(clean)} questions/passages detected\n")
    results = []
    for i, mk in enumerate(clean):
        start = mk["start"]
        end = clean[i + 1]["start"] if i + 1 < len(clean) else duration
        out = os.path.join(out_dir, mk["label"] + ext)
        r = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-ss", str(start),
             "-to", str(end), "-i", input_path, "-c", "copy", out],
            capture_output=True, text=True,
        )
        status = "" if r.returncode == 0 else f"  FAILED: {r.stderr.strip()}"
        print(f"  {mk['label']}  {start:.1f}s - {end:.1f}s  ({end - start:.1f}s){status}")
        results.append({"label": mk["label"], "path": out, "start": start, "end": end})

    print(f"\nDone -> {out_dir}/")
    return results


if __name__ == "__main__":
    inp = sys.argv[1] if len(sys.argv) > 1 else "Test_07.mp3"
    outd = sys.argv[2] if len(sys.argv) > 2 else "clips"
    tpath = sys.argv[3] if len(sys.argv) > 3 else "transcript.json"
    cut(inp, outd, tpath)
