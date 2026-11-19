"""OpenAI calls: naming balls from crops, and describing a captured clip.

Key, model and reasoning effort come from .env (OPENAI_API_KEY, the same key as project 1;
OPENAI_MODEL, OPENAI_REASONING). gpt-6.2-sol at "low" was the fastest accurate model when we compared
four on shots from a real game (19/11, context/LOG.md).
"""
import base64
import json
import os
import re
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
MODEL = os.getenv("OPENAI_MODEL", "gpt-6.2-sol")
REASONING = os.getenv("OPENAI_REASONING", "low")
# naming balls is a simpler look at small crops and has to keep up with play: a faster model
NAMING_MODEL = os.getenv("OPENAI_NAMING_MODEL", "gpt-6-luna")
NAMING_REASONING = os.getenv("OPENAI_NAMING_REASONING", "none")
_client = None

BALL_PROMPT = (
    "Each numbered tile is a crop around one detected object on a pool table (8-ball pool, American balls). "
    "The tiles are everything on the table at one moment, so each ball number appears at most once. "
    "Ball colours: 1 yellow, 2 blue, 3 red, 4 purple, 5 orange, 6 green, 7 maroon (solids 1-7); 8 black; "
    "9 yellow, 10 blue, 11 red, 12 purple, 13 orange, 14 green, 15 maroon (stripes 9-15: white ball with a coloured band); "
    "cue ball plain white with no colour (a stripe showing its white cap is not the cue ball). "
    "If a number is readable, it decides the ball; otherwise use colour plus solid/stripe. "
    "For every tile return its kind: cue (white cue ball), eight (black 8), solid (1-7), stripe (9-15), or not_ball; "
    "and the ball number if you can tell (0 for cue, null if unsure). "
    'Answer JSON only: {"tiles": [{"tile": 1, "kind": "...", "number": n}, ...]}')

CLIP_PROMPT = (
    "You are watching {seconds} seconds of an 8-ball pool game from a fixed camera beside the table. "
    "The {n} images are frames in time order, at t = {times} seconds. "
    "Our live detector's labels per frame (ball number/kind and box centre in pixels of the images you see, "
    "{width}x{height}; people as player/spectator):\n"
    "{labels}\n"
    "Describe what actually happened. Answer JSON only: "
    '{{"summary": "2-3 sentences", "events": [{{"t": seconds, "what": "..."}}], '
    '"players": [{{"description": "...", "holding_cue": true, "shooting": false}}], '
    '"balls_potted": ["..."], "detector_misses": "what our labels got wrong or missed"}}')


def client():
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


def image_part(img, width=None):
    if width and img.shape[1] > width:
        img = cv2.resize(img, (width, round(img.shape[0] * width / img.shape[1])))
    ok, jpg = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return {"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(jpg.tobytes()).decode()}


def ask_json(prompt, images, model=None, effort=None):
    r = client().responses.create(
        model=model or MODEL, reasoning={"effort": effort or REASONING},
        input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}, *images]}])
    return json.loads(r.output_text.strip().removeprefix("```json").removeprefix("```").removesuffix("```"))


def stream_json(prompt, images, early_key, on_early):
    """Like ask_json, but streams the answer and calls on_early(value) as soon as `early_key` (a string
    or null, asked for first in the JSON) has arrived: about 1.3 s instead of ~4 s for the whole answer."""
    text, sent = "", False
    pattern = re.compile(r'"%s"\s*:\s*("(?:[^"\\]|\\.)*"|null)' % re.escape(early_key))
    with client().responses.stream(model=MODEL, reasoning={"effort": REASONING},
                                   input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}, *images]}]) as s:
        for ev in s:
            if ev.type == "response.output_text.delta":
                text += ev.delta
                if not sent and (m := pattern.search(text)):
                    on_early(json.loads(m.group(1)))
                    sent = True
    return json.loads(text.strip().removeprefix("```json").removeprefix("```").removesuffix("```"))


LIMITS = {"solid": 7, "stripe": 7, "eight": 1, "cue": 1}


def problems(names):
    """What can't be right in one table's worth of ball names, by the rules of 8-ball:
    7 solids (1-7), 7 stripes (9-15), one 8, one cue, at most 16 balls, each number once."""
    issues = []
    kinds = Counter(n.get("kind") for n in names)
    for kind, limit in LIMITS.items():
        if kinds[kind] > limit:
            issues.append(f"{kinds[kind]} {kind} balls, but there are only {limit}")
    if len(names) - kinds["not_ball"] > 16:
        issues.append(f"{len(names) - kinds['not_ball']} balls, but a table has at most 16, so some are not balls")
    numbers = Counter(n.get("number") for n in names if n.get("number") is not None)
    twice = sorted(n for n, c in numbers.items() if c > 1)
    if twice:
        issues.append("numbers used more than once: " + ", ".join(map(str, twice)))
    clash = [i + 1 for i, n in enumerate(names) if n.get("number") is not None and (
        (n.get("kind") == "solid" and not 1 <= n["number"] <= 7) or (n.get("kind") == "stripe" and not 9 <= n["number"] <= 15))]
    if clash:
        issues.append("kind and number disagree on tiles " + ", ".join(map(str, clash)))
    return issues


def identify_balls(crops, retries=1):
    """One crop per detected ball in, [{"kind", "number"}] out in the same order.
    The crops go as one grid image of numbered tiles (one call, ~4 s, ~$0.0002). If the answer
    breaks the rules of 8-ball (problems()), the model is shown its answer and the mistakes and
    asked to look again, up to `retries` times. Returns (names, corrections made)."""
    tiles = []
    for i, crop in enumerate(crops):
        t = cv2.resize(crop, (128, 128), interpolation=cv2.INTER_CUBIC)
        t = cv2.copyMakeBorder(t, 22, 0, 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        cv2.putText(t, str(i + 1), (4, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
        tiles.append(t)
    blank = np.full_like(tiles[0], 255)
    rows = [np.hstack(tiles[i:i + 8] + [blank] * (8 - len(tiles[i:i + 8]))) for i in range(0, len(tiles), 8)]
    grid = image_part(np.vstack(rows))
    prompt, corrections = BALL_PROMPT, 0
    while True:
        answer = ask_json(prompt, [grid], NAMING_MODEL, NAMING_REASONING)
        by_tile = {t.get("tile"): t for t in answer["tiles"]}
        out = []
        for i in range(len(crops)):
            t = by_tile.get(i + 1, {})
            kind, number = t.get("kind"), t.get("number")
            if number == 8:
                kind = "eight"  # it sometimes says "solid" for the 8
            elif number == 0:
                kind = "cue"
            out.append({"kind": kind, "number": number})
        issues = problems(out)
        if not issues or corrections == retries:
            return out, corrections
        corrections += 1
        prompt = (BALL_PROMPT + "\nYour previous answer was:\n" + json.dumps(answer) +
                  "\nIt cannot be right: " + "; ".join(issues) + ". Look at every tile again and correct your mistakes.")


def describe_clip(frames, seconds, width=1024):
    """frames: [{"t", "frame", "detections"}], a handful spread over the clip, sent `width` px wide."""
    h, w = frames[0]["frame"].shape[:2]
    scale = min(1.0, width / w)  # positions must match the shrunk images the model sees
    labels = []
    for f in frames:
        parts = []
        for d in f["detections"]:
            x, y = round((d["box"][0] + d["box"][2]) / 2 * scale), round((d["box"][1] + d["box"][3]) / 2 * scale)
            name = f"{d.get('number')} {d['kind']}" if d.get("kind") else d["label"]
            parts.append(f"{name}@({x},{y})")
        labels.append(f"t={f['t']}: " + ", ".join(parts))
    prompt = CLIP_PROMPT.format(seconds=seconds, n=len(frames), times=[f["t"] for f in frames], labels="\n".join(labels),
                                width=round(w * scale), height=round(h * scale))
    return ask_json(prompt, [image_part(f["frame"], width=width) for f in frames])
