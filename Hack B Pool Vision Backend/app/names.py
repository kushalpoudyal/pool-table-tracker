"""Turns the LLM's readings of each ball into names that obey the rules of 8-ball.

Every LLM reading is a vote for a ball's kind and number, kept per track ID, so one bad look
(a stripe showing only its white cap reads as the cue ball) can't flip a ball. The names shown
are then solved for all visible balls together, with fixed slots: 1 cue, 1 eight, at most 7
solids, at most 7 stripes, each number at most once. When two balls claim the one cue ball the
whiter one gets it (the darker one for the 8); the loser goes back to unknown and is re-read
when the table is next still.
"""
from collections import Counter, defaultdict

import cv2
import numpy as np
from scipy.optimize import linear_sum_assignment

SLOTS = ["cue", "eight"] + ["solid"] * 7 + ["stripe"] * 7
NUMBERS = {"cue": {0}, "eight": {8}, "solid": set(range(1, 8)), "stripe": set(range(9, 16))}
UNKNOWN = 0.9  # cost of leaving a ball unnamed: any kind with a clear majority of its votes beats it
LOOK = 0.3  # how much colour can tip a contested cue / 8


def looks(crop):
    """(whiteness, darkness) inside the ball: share of near-white and of near-black pixels."""
    h, w = crop.shape[:2]
    yy, xx = np.mgrid[:h, :w]
    inside = (xx - w / 2) ** 2 + (yy - h / 2) ** 2 <= (0.4 * min(w, h)) ** 2
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[inside].astype(int)
    return ((hsv[:, 1] < 60) & (hsv[:, 2] > 140)).mean(), (hsv[:, 2] < 60).mean()


class BallNames:
    def __init__(self):
        self.kinds = defaultdict(Counter)  # track id -> votes per kind
        self.numbers = defaultdict(Counter)  # track id -> votes per number
        self.look = {}  # track id -> (whiteness, darkness) at the last reading

    def add(self, tid, name, crop):
        if name.get("kind"):
            self.kinds[tid][name["kind"]] += 1
        if name.get("number") is not None:
            self.numbers[tid][name["number"]] += 1
        self.look[tid] = looks(crop)

    def resolve(self, tids):
        """{track id: {"kind", "number"}} for the visible balls, obeying the slots. Unknown balls are left out."""
        tids = [t for t in tids if self.kinds[t]]
        if not tids:
            return {}
        options = SLOTS + ["not_ball"] * len(tids) + ["unknown"] * len(tids)
        white = np.array([self.look.get(t, (0, 0))[0] for t in tids])
        dark = np.array([self.look.get(t, (0, 0))[1] for t in tids])
        rank = lambda v: (v.argsort().argsort() / max(len(v) - 1, 1)) if len(v) > 1 else np.ones(1)
        cost = np.zeros((len(tids), len(options)))
        for i, t in enumerate(tids):
            total = sum(self.kinds[t].values())
            for j, kind in enumerate(options):
                if kind == "unknown":
                    cost[i, j] = UNKNOWN
                    continue
                cost[i, j] = 1 - self.kinds[t][kind] / total
                if kind == "cue":
                    cost[i, j] -= LOOK * rank(white)[i]
                elif kind == "eight":
                    cost[i, j] -= LOOK * rank(dark)[i]
        rows, cols = linear_sum_assignment(cost)
        out, used = {}, {}
        for i, j in zip(rows, cols):
            kind = options[j]
            if kind == "unknown":
                continue
            t = tids[i]
            # the number most voted for that fits the kind, once 2 readings agree (single readings of
            # ~25 px balls get numbers wrong); a number held by a better-voted ball is dropped
            fits = [(n, c) for n, c in self.numbers[t].most_common() if n in NUMBERS.get(kind, ()) and c >= 2]
            number = fits[0][0] if fits else (0 if kind == "cue" else 8 if kind == "eight" else None)
            if number is not None and number in used and used[number][1] >= self.numbers[t][number]:
                number = None
            elif number is not None:
                if number in used:
                    out[used[number][0]]["number"] = None
                used[number] = (t, self.numbers[t][number])
            out[t] = {"kind": kind, "number": number}
        return out
