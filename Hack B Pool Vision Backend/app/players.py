"""Who may play: labelled photos in assets/players/ turned into one roster sheet for the LLM.

Each photo shows people labelled with their names. One LLM call per photo returns every labelled
person's name, how to recognise them and where their head and upper body are; the app cuts those out
and stitches them into one small sheet of named tiles. The sheet goes with a game's first looks so
the LLM can tell who is at the table; it is rebuilt only when the photos change.
Photos from the day of the game work best (clothes are the main clue from a camera above the table).
The photos are git-ignored: real faces and names, and the repo is public.
"""
import json
from pathlib import Path

import cv2
import numpy as np

from app import llm

ROOT = Path(__file__).resolve().parent.parent
FOLDER = ROOT / "assets" / "players"
CACHE = FOLDER / ".cache"
TILE = (160, 200)
PER_ROW = 8

PROMPT = ("This photo shows people labelled with their names (white boxes with names next to them). For every "
          "labelled person give: the name exactly as written; how to recognise them: face shape, hair, skin tone, "
          "facial hair, build (not glasses, which people take on and off), then what they wear in this photo, marked "
          "as possibly different on another day; and a box around their head and upper body down to the waist "
          "(clothes help on the same day) as fractions "
          "of the image width and height, [x1, y1, x2, y2]. Match each label to the person it sits on or next to. "
          'Answer JSON only: {"people": [{"name": "...", "looks": "...", "box": [0.1, 0.2, 0.3, 0.5]}]}')


def photos():
    return sorted(p for p in FOLDER.glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))


def _read_photo(path):
    img = cv2.imread(str(path))
    people = llm.ask_json(PROMPT, [llm.image_part(img, 1600)])["people"]
    h, w = img.shape[:2]
    for p in people:
        x1, y1, x2, y2 = (float(v) for v in p["box"])
        crop = img[max(int(y1 * h), 0):min(int(y2 * h), h), max(int(x1 * w), 0):min(int(x2 * w), w)]
        p["tile"] = crop if crop.size else None
    return people


def _sheet(people):
    tiles = []
    for p in people:
        tile = cv2.resize(p["tile"], TILE, interpolation=cv2.INTER_AREA)
        cv2.rectangle(tile, (0, TILE[1] - 26), (TILE[0], TILE[1]), (255, 255, 255), -1)
        cv2.putText(tile, p["name"][:14], (4, TILE[1] - 7), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
        tiles.append(tile)
    blank = np.full_like(tiles[0], 255)
    rows = [np.hstack(tiles[i:i + PER_ROW] + [blank] * (PER_ROW - len(tiles[i:i + PER_ROW])))
            for i in range(0, len(tiles), PER_ROW)]
    return np.vstack(rows)


def roster():
    """[{"name", "looks"}] for everyone in the photos, plus the stitched sheet (or None if there are no photos).
    Built once and cached; rebuilt when a photo is added, changed or removed."""
    files = photos()
    if not files:
        return [], None
    key = [[p.name, p.stat().st_mtime] for p in files]
    index, sheet = CACHE / "roster.json", CACHE / "sheet.jpg"
    if index.exists() and sheet.exists():
        cached = json.loads(index.read_text(encoding="utf-8"))
        if cached["key"] == key:
            return cached["people"], cv2.imread(str(sheet))
    people = [p for f in files for p in _read_photo(f) if p.get("tile") is not None]
    CACHE.mkdir(parents=True, exist_ok=True)
    img = _sheet(people)
    cv2.imwrite(str(sheet), img)
    people = [{"name": p["name"].strip().title(), "looks": p["looks"]} for p in people]
    index.write_text(json.dumps({"key": key, "people": people}, indent=2), encoding="utf-8")
    return people, img


def only(people, sheet, names):
    """The roster cut down to these names: their descriptions and their tiles of the sheet, or ([], None)."""
    wanted = {n.casefold() for n in names}
    keep = [i for i, p in enumerate(people) if p["name"].casefold() in wanted]
    if not keep:
        return [], None
    w, h = TILE
    tiles = [sheet[i // PER_ROW * h:(i // PER_ROW + 1) * h, i % PER_ROW * w:(i % PER_ROW + 1) * w] for i in keep]
    return [people[i] for i in keep], np.hstack(tiles)


def cached_names():
    """Names in the roster as last built, without building it (for the page)."""
    index = CACHE / "roster.json"
    return list(dict.fromkeys(p["name"] for p in json.loads(index.read_text(encoding="utf-8"))["people"])) if index.exists() else []


def add_photo(data, filename):
    """Saves an uploaded labelled photo into the folder (the roster rebuilds on next use)."""
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("not an image")
    FOLDER.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(FOLDER / (Path(filename).stem + ".jpg")), img)
    return roster()[0]
