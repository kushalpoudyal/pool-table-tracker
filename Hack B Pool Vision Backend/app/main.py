"""The camera feed with live detection, plus a sandbox that runs an uploaded video the same way.

Run from this folder:  python -m app.main
Then open http://127.0.0.1:8000 (live phone) or http://127.0.0.1:8000/sandbox (uploaded video).

Rackroom (Hack B Pool API / Client) talks to the live camera through the plain routes at the end of
this file: GET /status, GET /video, POST /game (two names in break order), GET /watch (the score for
its Watch tab), GET /game (everything), POST /game/end.
"""
import asyncio
import json
import os
import shutil
from pathlib import Path

import cv2
import uvicorn
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from app.capture import Camera
from app.detector import Detector, order_corners
from app.recorder import RECORDINGS, Recorder
from app import players as roster_photos
from app.observer import Observer

ROOT = Path(__file__).resolve().parent.parent
SOURCE = os.getenv("CAMERA_SOURCE", "phone")
UPLOADS = RECORDINGS / "uploads"
COLORS = {"cue": (255, 255, 255), "eight": (200, 80, 200), "solid": (0, 215, 255), "stripe": (0, 140, 255),
          "ball": (0, 180, 180), "cue stick": (255, 200, 0), "player": (80, 220, 100), "spectator": (150, 150, 150)}


class Pipeline:
    """One video source with its own detector, table outline and recorder."""

    def __init__(self, name, source):
        self.name = name
        self.table_file = ROOT / ("calibration.json" if name == "live" else f"calibration-{name}.json")
        table = order_corners(json.loads(self.table_file.read_text())["corners"]) if self.table_file.exists() else None
        self.camera = Camera(source)
        # live only sends looks between New game and End game; an uploaded video from the start
        self.observer = Observer(name, self.camera, lambda: getattr(self, "detector", None) and self.detector.table,
                                 active=name != "live")
        active = (lambda: not sandbox_playing()) if name == "live" else (lambda: True)
        self.detector = Detector(self.camera, table, log=name, active=active, on_motion=self.observer.watch)
        self.recorder = Recorder(self.camera, self.detector, name)

    def stop(self):
        self.camera.stop()
        self.detector.stop()
        self.observer.stop()


app = FastAPI()
pipelines = {"live": Pipeline("live", SOURCE)}  # "sandbox" appears after the first upload


def sandbox_playing():
    p = pipelines.get("sandbox")
    return p is not None and not p.camera.ended


def get(name):
    if name not in pipelines:
        raise HTTPException(404, "upload a video first" if name == "sandbox" else "unknown pipeline")
    return pipelines[name]


def draw(p, frame):
    out = frame.copy()
    if p.detector.table is not None:
        cv2.polylines(out, [p.detector.table.astype("int32")], True, (255, 255, 255), 2)
    for d in p.detector.detections:
        x1, y1, x2, y2 = d["box"]
        if d["label"] == "ball":
            key = d.get("kind") if d.get("kind") in COLORS else "ball"
            text = "cue" if key == "cue" else f"{d.get('number') or ''} {key}".strip()
        else:
            key = text = "cue stick" if d["label"] == "cue" else d["label"]
        cv2.rectangle(out, (x1, y1), (x2, y2), COLORS[key], 2)
        cv2.putText(out, text, (x1, max(y1 - 8, 16)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, COLORS[key], 2)
    return out


@app.get("/")
@app.get("/sandbox")
def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.post("/sandbox/upload")
def upload(file: UploadFile):
    """A phone video of a game from the start; it replaces any earlier sandbox video."""
    UPLOADS.mkdir(parents=True, exist_ok=True)
    path = UPLOADS / Path(file.filename).name
    with path.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    (ROOT / "calibration-sandbox.json").unlink(missing_ok=True)  # a new video has its own camera position
    return restart(str(path))


@app.post("/sandbox/restart")
def restart(path: str | None = None):
    """Play the sandbox video again from the start, with fresh tracks and ball names."""
    old = pipelines.get("sandbox")
    source = path or (old and str(UPLOADS / old.camera.status()["source"]))
    if not source:
        raise HTTPException(404, "upload a video first")
    if old:
        old.stop()
    pipelines["sandbox"] = Pipeline("sandbox", source)
    return {"ok": True, "video": Path(source).name}


@app.get("/{name}/status")
def status(name: str):
    p = get(name)
    return {**p.camera.status(), "detector": p.detector.status(), "capture": p.recorder.state["status"]}


@app.post("/{name}/table")
def set_table(name: str, body: dict):
    """The 4 corners of the playing surface, in video pixels, clicked on the page."""
    p = get(name)
    p.detector.table = order_corners(body["corners"])
    p.table_file.write_text(json.dumps({"corners": p.detector.table.tolist()}))
    return {"ok": True}


@app.post("/{name}/identify")
def identify(name: str):
    """At the rack, ready to break: name every ball once; tracking carries the names from there."""
    get(name).detector.identify()
    return {"ok": True}


@app.get("/{name}/game")
def game(name: str):
    """The observer's memory, score and feed of 5-second looks."""
    return get(name).observer.status()


@app.get("/{name}/watch")
def watch(name: str):
    """The score for a Watch screen: players (group, potted, left, at the table), winner, match, latest moments."""
    return get(name).observer.summary()


@app.post("/{name}/game")
def new_game(name: str, body: dict):
    """Start a new game with these player names (the first one breaks), and optionally the caller's match id
    and where to send the final score once the game is decided: "report": {"url", "token"}."""
    typed = list(dict.fromkeys(p.strip() for p in body.get("players", []) if p.strip()))
    # no names typed: the observer recognises the players from the labelled photos in assets/players
    get(name).observer.new_game(typed, match=body.get("match"), report=body.get("report"))
    return {"ok": True, "players": typed or "recognising from assets/players", "match": body.get("match")}


@app.post("/{name}/game/end")
def end_game(name: str):
    """Stop sending looks (the live camera costs a look every 5 s while a game is on). Returns the final score
    with every moment of the game, which Rackroom records."""
    observer = get(name).observer
    observer.end_game()
    return observer.summary(None)


@app.post("/players-photo")
async def players_photo(file: UploadFile):
    """A photo with people labelled by name, added to assets/players (git-ignored); players are recognised from these."""
    try:
        return {"people": [p["name"] for p in roster_photos.add_photo(await file.read(), file.filename)]}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/{name}/capture")
def capture(name: str):
    """Record 5 seconds and ask the LLM what happened."""
    return {"started": get(name).recorder.start()}


@app.get("/{name}/capture")
def capture_result(name: str):
    return get(name).recorder.state


@app.get("/{name}/video")
async def video(name: str):
    get(name)

    async def frames():
        last_id = 0
        while True:
            p = pipelines.get(name)
            frame_id, frame = p.camera.latest() if p else (0, None)
            if frame is None or frame_id == last_id:
                await asyncio.sleep(0.01)
                continue
            last_id = frame_id
            ok, jpg = cv2.imencode(".jpg", draw(p, frame), [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpg.tobytes() + b"\r\n"

    return StreamingResponse(frames(), media_type="multipart/x-mixed-replace; boundary=frame")


# Rackroom's contract for the live camera: the same as /live/..., without the prefix.
# It reads /status and /video (POOL_STREAM_SERVER), starts a game with the two names it picked and
# reads the score back from /game.
@app.get("/status")
def live_status():
    return status("live")


@app.get("/video")
async def live_video():
    return await video("live")


@app.get("/game")
def live_game():
    return game("live")


@app.get("/watch")
def live_watch():
    return watch("live")


@app.post("/game")
def live_new_game(body: dict):
    """Rackroom starts a game: {"players": ["breaker", "other"], "match": <match id>, "report": {"url", "token"}}."""
    return new_game("live", body)


@app.post("/game/end")
def live_end_game():
    return end_game("live")


if __name__ == "__main__":
    # HOST=0.0.0.0 lets other computers on the network open the page (no login: anyone on it can watch).
    # PORT: Rackroom's API also defaults to 8000, so run one of them elsewhere on a shared machine.
    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")))
