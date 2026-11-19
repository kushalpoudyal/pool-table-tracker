"""Runs the object detector and tracker on the newest camera frame in a background thread.

Zero-shot YOLOE told what to look for in words (no training yet), exported once to OpenVINO so
it runs on the laptop's Intel GPU. BallTracker (app/tracker.py) gives every ball an ID that follows it.
Ball names (cue / eight / solid / stripe + number): the LLM reads all balls at once on
"Identify balls", and again whenever the table is still and a ball has no name; every reading is
a vote on the ball's ID, and BallNames (app/names.py) turns the votes into names that obey 8-ball
(1 cue, 1 eight, 7 solids, 7 stripes, numbers unique).
After changing CLASSES, delete models/yoloe-26s-seg_openvino_model so it re-exports.
"""
import json
import threading
import time
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO, YOLOE

from app import llm
from app.names import BallNames
from app.tracker import BallTracker

ROOT = Path(__file__).resolve().parent.parent
MODEL = ROOT / "models" / "yoloe-26s-seg.pt"
EXPORTED = ROOT / "models" / "yoloe-26s-seg_openvino_model"
CLASSES = ["billiard ball", "cue stick", "person"]
LABELS = {"billiard ball": "ball", "cue stick": "cue"}
IMGSZ = 1280
CONF = 0.25


def load_model():
    if not EXPORTED.exists():  # first run: download YOLOE, bake in our classes, export
        model = YOLOE(str(MODEL))
        model.set_classes(CLASSES, model.get_text_pe(CLASSES))
        model.export(format="openvino", imgsz=IMGSZ)
    return YOLO(str(EXPORTED), task="segment")


def order_corners(corners):
    """Corners in order around the centre, whatever order they were clicked in."""
    pts = np.float32(corners)
    centre = pts.mean(0)
    return pts[np.argsort(np.arctan2(pts[:, 1] - centre[1], pts[:, 0] - centre[0]))]


def rect(box):
    x1, y1, x2, y2 = box
    return np.float32([[x1, y1], [x2, y1], [x2, y2], [x1, y2]])


def overlap(box, table):
    """Share of a person's box that lies over the table outline."""
    area, _ = cv2.intersectConvexConvex(rect(box), table)
    return area / max((box[2] - box[0]) * (box[3] - box[1]), 1)


def touches(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def crop(frame, box, margin=0.15):
    x1, y1, x2, y2 = box
    m = margin * (x2 - x1)
    h, w = frame.shape[:2]
    return frame[max(int(y1 - m), 0):min(int(y2 + m), h), max(int(x1 - m), 0):min(int(x2 + m), w)]


def ball_name(d):
    """How the referee hears about a ball: "cue ball", "8-ball", "13 (stripe)", "a solid", "unnamed ball"."""
    kind, number = d.get("kind"), d.get("number")
    if kind == "cue":
        return "cue ball"
    if kind == "eight":
        return "8-ball"
    if kind in ("solid", "stripe"):
        return f"{number} ({kind})" if number is not None else f"a {kind}"
    return "unnamed ball"


def classify(result, table, namer, tracker, frame, now):
    """Labels the boxes.
    Balls: dropped if off the cloth (when the table is marked); tracked by BallTracker; carry their
    name, and are dropped if named not_ball.
    People: a player holds a cue or touches the table outline; at most 2, the rest are spectators."""
    found, people, cues, balls = [], [], [], []
    for box, cls, conf in zip(result.boxes.xyxy.tolist(), result.boxes.cls.tolist(), result.boxes.conf.tolist()):
        name = result.names[int(cls)]
        d = {"id": None, "conf": round(conf, 2), "box": [round(v) for v in box]}
        if name == "person":
            people.append(d)
        elif name == "cue stick":
            cues.append(d["box"])
            found.append({**d, "label": "cue"})
        else:
            centre = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
            if table is not None and cv2.pointPolygonTest(table, centre, False) < 0:
                continue  # chalk on the rail, something off the table
            balls.append({**d, "label": "ball"})
    tracked = tracker.update(balls, frame, now)
    names = namer.resolve([b["id"] for b in tracked])
    for b in tracked:
        known = names.get(b["id"], {})
        if known.get("kind") != "not_ball":
            found.append({**b, **known})
    for p in people:
        p["has_cue"] = any(touches(p["box"], c) for c in cues)
        p["share"] = overlap(p["box"], table) if table is not None else 0.0
    people.sort(key=lambda p: (p["has_cue"], p["share"]), reverse=True)
    for i, p in enumerate(people):
        playing = i < 2 and (p["has_cue"] or p["share"] > 0.005)  # touching the outline: ~2%, spectators 0
        found.append({"id": p["id"], "conf": p["conf"], "box": p["box"], "label": "player" if playing else "spectator"})
    return found


class Detector:
    def __init__(self, camera, table=None, log="live", active=lambda: True, on_motion=None):
        self.camera = camera
        self.on_motion = on_motion  # called with (time, ball movement px, frame) on every frame: the referee
        self.active = active  # False = pause (live pauses while a sandbox video plays: they share the GPU)
        self.log = ROOT / "logs" / f"detections-{log}.jsonl"
        self.table = table  # 4 corners of the playing surface in video pixels, or None
        self.detections = []
        self.names = BallNames()  # LLM votes per ball track id -> names that obey 8-ball
        self.tracker = BallTracker()
        self.fps = 0.0
        self.device = "loading"
        self.naming = None  # None, "running" or the last error
        self.naming_note = ""  # self-corrections made / rule breaks left after the last naming
        self._identify_all = False
        self._last_naming = 0.0
        self.running = True
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self):
        self.running = False

    def identify(self):
        """New game, at the rack: forget all names and name every ball on the table."""
        self.names = BallNames()
        self._identify_all = True

    def _run(self):
        try:
            model = load_model()
        except Exception as e:
            self.device = f"failed to load: {e}"
            print(f"detector: {self.device}")
            return
        self.device = "xpu"  # Intel GPU through OpenVINO
        self.log.parent.mkdir(exist_ok=True)
        seen, count, window_start, last_log, still_since, last_pos = 0, 0, time.time(), 0.0, time.time(), {}
        while self.running:
            frame_id, frame = self.camera.latest()
            if frame is None or frame_id == seen or not self.active():
                time.sleep(0.005)
                continue
            seen = frame_id
            try:
                result = model.predict(frame, imgsz=IMGSZ, conf=CONF, device=self.device, verbose=False)[0]
            except Exception as e:
                if self.device == "cpu":
                    raise
                print(f"detector: Intel GPU unavailable ({e}), using CPU")
                self.device = "cpu"
                continue
            now = self.camera.frame_time  # video time in the sandbox, so a slow replay doesn't stretch shots
            self.detections = classify(result, self.table, self.names, self.tracker, frame, now)

            # still table = no tracked ball moved more than 3 px since the last frame, after taking out the
            # shift every ball shares (that is the camera moving, not the balls)
            balls = [d for d in self.detections if d["label"] == "ball" and d["id"] is not None]
            pos = {d["id"]: ((d["box"][0] + d["box"][2]) / 2, (d["box"][1] + d["box"][3]) / 2) for d in balls}
            shifts = np.array([np.subtract(pos[i], last_pos[i]) for i in pos if i in last_pos]).reshape(-1, 2)
            common = np.median(shifts, 0) if len(shifts) >= 3 else 0  # too few balls to tell camera from ball
            moved = np.hypot(*(shifts - common).T).max() if len(shifts) else 0
            if moved > 3:  # a ball blinking in or out of detection is not movement
                still_since = now
            last_pos = pos
            if self.on_motion:
                self.on_motion(now, moved, frame, {d["id"]: (pos[d["id"]], ball_name(d)) for d in balls})

            # naming: all balls together, so the LLM sees the whole table; on "Identify balls", and
            # whenever the table is still and a ball has no name (new, or it lost a contested slot)
            stale = any(not d.get("kind") for d in balls)  # new, or lost its slot to a better-voted ball
            if balls and self.naming != "running" and (
                    self._identify_all or (stale and now - still_since > 1 and
                                           now - self._last_naming > (30 if "still wrong" in self.naming_note else 5))):
                self._identify_all = False
                self.naming = "running"
                threading.Thread(target=self._name, args=([d["id"] for d in balls[:32]], [crop(frame, d["box"]) for d in balls[:32]]), daemon=True).start()

            count += 1
            wall = time.time()
            if wall - window_start >= 1:
                self.fps = count / (wall - window_start)
                count, window_start = 0, wall
            if wall - last_log >= 1:  # one line a second: what is on the table right now
                with self.log.open("a") as f:
                    f.write(json.dumps({"t": round(wall, 2), **self.counts(), "detections": self.detections}) + "\n")
                last_log = wall

    def _name(self, ids, crops):
        try:
            names, corrections = llm.identify_balls(crops)
            for tid, name, crop in zip(ids, names, crops):
                self.names.add(tid, name, crop)
            self.naming = None
            left = llm.problems(names)
            self.naming_note = (f"fixed its own mistakes {corrections}x" if corrections else "") + (
                f"; still wrong: {'; '.join(left)}" if left else "")
        except Exception as e:
            self.naming = f"failed: {e}"
            print(f"detector: naming balls {self.naming}")
        self._last_naming = time.time()

    def counts(self):
        c = Counter(d["label"] for d in self.detections)
        k = Counter(d.get("kind") for d in self.detections if d["label"] == "ball")
        return {**{x: c.get(x, 0) for x in ("ball", "cue", "player", "spectator")},
                **{x: k.get(x, 0) for x in ("solid", "stripe")}}

    def status(self):
        return {"device": self.device, "fps": round(self.fps, 1), "counts": self.counts(),
                "table": self.table is not None, "naming": self.naming,
                "named": sum(1 for d in self.detections if d.get("kind")),
                "naming_note": self.naming_note}
