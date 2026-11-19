"""Keeps one ID per ball across frames, matching by predicted position and colour.

Box-overlap trackers (ByteTrack) lose a pool ball the moment it moves: it is ~25 px wide and
travels several widths between detector frames, so its old and new boxes never overlap.
Here each ball is matched to the nearest prediction (last position + velocity) of a similar
colour, within a generous radius, and a ball that vanishes for a moment (hand, cue, motion blur)
keeps its ID for KEEP seconds so it is picked up again when it reappears.
"""
import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment

KEEP = 10.0  # seconds an unseen ball keeps its track (balls only leave the table through pockets)
REACH = 12  # how far a ball may jump between detector frames, in ball diameters
COLOUR_WEIGHT = 1 / 25  # one ball diameter of distance costs as much as 25 Lab units of colour difference


def colour(frame, box):
    """Mean Lab colour inside the ball (inner circle of its box)."""
    x1, y1, x2, y2 = (int(v) for v in box)
    patch = frame[max(y1, 0):y2, max(x1, 0):x2]
    if patch.size == 0:
        return np.zeros(3)
    h, w = patch.shape[:2]
    yy, xx = np.mgrid[:h, :w]
    inside = (xx - w / 2) ** 2 + (yy - h / 2) ** 2 <= (0.4 * min(w, h)) ** 2
    return cv2.cvtColor(patch, cv2.COLOR_BGR2LAB)[inside].mean(0)


class BallTracker:
    def __init__(self):
        self.tracks = {}  # id -> {"pos", "vel", "size", "colour", "seen"}
        self.next_id = 1

    def update(self, balls, frame, now):
        """balls: detection dicts with "box"; sets d["id"] on each, returns them."""
        centres = np.array([((b["box"][0] + b["box"][2]) / 2, (b["box"][1] + b["box"][3]) / 2) for b in balls]).reshape(-1, 2)
        colours = [colour(frame, b["box"]) for b in balls]
        ids = list(self.tracks)
        if ids and len(balls):
            cost = np.full((len(ids), len(balls)), 1e6)
            for i, tid in enumerate(ids):
                t = self.tracks[tid]
                pred = t["pos"] + t["vel"] * min(now - t["seen"], 0.5)  # don't extrapolate far
                dist = np.hypot(*(centres - pred).T) / t["size"]  # in ball diameters
                col = np.array([np.linalg.norm(c - t["colour"]) for c in colours]) * COLOUR_WEIGHT
                cost[i] = np.where(dist <= REACH, dist + col, 1e6)
            rows, cols = linear_sum_assignment(cost)
            matched = [(ids[r], c) for r, c in zip(rows, cols) if cost[r, c] < 1e6]
        else:
            matched = []
        taken = {c for _, c in matched}
        for tid, c in matched:
            t = self.tracks[tid]
            dt = max(now - t["seen"], 1e-3)
            t["vel"] = 0.5 * t["vel"] + 0.5 * (centres[c] - t["pos"]) / dt
            t["pos"], t["seen"], t["colour"] = centres[c], now, 0.8 * t["colour"] + 0.2 * colours[c]
            t["size"] = max(balls[c]["box"][2] - balls[c]["box"][0], 8)
            balls[c]["id"] = tid
        for c, b in enumerate(balls):
            if c not in taken:  # a ball we have not seen before
                self.tracks[self.next_id] = {"pos": centres[c], "vel": np.zeros(2), "seen": now, "colour": colours[c],
                                             "size": max(b["box"][2] - b["box"][0], 8)}
                b["id"] = self.next_id
                self.next_id += 1
        for tid in [t for t, v in self.tracks.items() if now - v["seen"] > KEEP]:
            del self.tracks[tid]
        return balls
