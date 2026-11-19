"""Captures a few seconds of the stream to recordings/ and asks the LLM what happened in it."""
import json
import threading
import time
from pathlib import Path

import cv2

from app import llm

RECORDINGS = Path(__file__).resolve().parent.parent / "recordings"


class Recorder:
    def __init__(self, camera, detector, name):
        self.camera, self.detector, self.name = camera, detector, name
        self.state = {"status": "idle"}

    def start(self, seconds=5, fps=5):
        if self.state["status"] in ("recording", "analysing"):
            return False
        self.state = {"status": "recording"}
        threading.Thread(target=self._run, args=(seconds, fps), daemon=True).start()
        return True

    def _run(self, seconds, fps):
        folder = RECORDINGS / f"{self.name}-{time.strftime('%Y%m%d-%H%M%S')}"
        folder.mkdir(parents=True)
        frames, t0 = [], time.time()
        while time.time() - t0 < seconds:
            _, frame = self.camera.latest()
            if frame is not None:
                frames.append({"t": round(time.time() - t0, 1), "frame": frame, "detections": list(self.detector.detections)})
                cv2.imwrite(str(folder / f"{len(frames):03d}.jpg"), frame)
            time.sleep(1 / fps)
        (folder / "detections.json").write_text(json.dumps([{"t": f["t"], "detections": f["detections"]} for f in frames]))
        if not frames:
            self.state = {"status": "failed", "folder": folder.name, "error": "no camera frames"}
            return
        self.state = {"status": "analysing", "folder": folder.name}
        try:
            picks = frames[::max(1, len(frames) // 6)][:6]  # 6 frames spread over the clip
            analysis = llm.describe_clip(picks, seconds)
            (folder / "analysis.json").write_text(json.dumps(analysis, indent=2))
            self.state = {"status": "done", "folder": folder.name, "analysis": analysis}
        except Exception as e:
            self.state = {"status": "failed", "folder": folder.name, "error": str(e)}
