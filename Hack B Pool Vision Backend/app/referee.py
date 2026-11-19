"""The LLM referee. Cuts the stream into shots from ball movement, asks the LLM what happened in each
one, and keeps the game state. The rules (rules/8ball.md) decide the game; the app only checks the
answer is physically sane.

Computer vision and the LLM work together on each shot: the tracker notes which ball moved first,
which ball it set moving first (and grabs that frame: the first contact), which balls vanished and
whether the cue ball is still there; the LLM gets those hints with the frames and calls pots and
fouls (scratch, no ball hit, wrong ball first) by the house rules.
"""
import json
import queue
import threading
import time
from pathlib import Path

import cv2
import numpy as np

from app import llm

ROOT = Path(__file__).resolve().parent.parent
RULES = ROOT / "rules" / "8ball.md"
MOVE_PX = 4  # a ball moving more than this between detector frames (camera shift taken out) is motion
START_FRAMES = 3  # moving frames within half a second that start a shot (a single flicker doesn't)
QUIET = 0.6  # seconds without motion that end a shot
MAX_SHOT = 40.0  # seconds; a shot is cut here even if something keeps moving
STARTED_PX = 10  # a ball this far from where it rested has been set moving
LIMITS = {"solid": 7, "stripe": 7, "eight": 1}

PROMPT = """You are the referee of a pool game seen by one camera above the table (it may move a little: judge balls against the table, not the frame).

House rules (follow these exactly, including the fouls):
{rules}

Game so far (JSON): {state}
Last shots: {recent}
Tracker hints for this shot (computer vision: usually right about what moved first and what vanished, but check the images): {hints}

The {n} images are one possible shot, in time order: {order}. The shooter is {shooter}.
Compare before and after to see which balls are gone. A ball in the jaws of a pocket that has not dropped is NOT potted. If the cue ball was not struck (practice strokes, placing the ball, the camera moving), set shot to false.
Fouls: the cue ball potted or off the table (scratch), the cue ball hitting nothing, or the first ball it hits not being the shooter's group (on an open table, the 8 first). Name the foul in "foul".
Reply with compact JSON only, keys exactly:
{{"shot": true, "break": false, "hit": "first ball the cue ball hit, e.g. 3, or null",
 "pot": [["ball number or colour", "solid|stripe|eight", "pocket"]], "scratch": false, "foul": null,
 "group": {{"<player>": "solids|stripes"}} or null, "next": one of {players}, "hand": false, "win": null or one of {players},
 "say": "one short commentator line saying what happened (and any foul) and who is up"}}"""


def shrink(frame, width):
    h, w = frame.shape[:2]
    return frame if w <= width else cv2.resize(frame, (width, round(h * width / w)))


class Referee:
    def __init__(self, name):
        self.folder = ROOT / "recordings" / f"{name}-shots"
        self.log = ROOT / "logs" / f"game-{name}.jsonl"
        self.jobs = queue.Queue()
        self.judging = False
        self.new_game(["Player 1", "Player 2"])
        self.moving = False
        self.before = None  # (time, frame, {ball id: (centre, name)}) of the latest still moment
        self.recent_moves = []
        threading.Thread(target=self._work, daemon=True).start()

    def new_game(self, players):
        self.state = {"players": players, "shooter": players[0], "groups": {p: None for p in players},
                      "potted": [], "shots": 0, "ball_in_hand": False, "winner": None, "broken": False}
        self.feed = []  # newest first
        self.game_id = time.strftime("%Y%m%d-%H%M%S")
        self.clips = 0  # every clip judged, shots or not: names the debug folders

    def watch(self, t, moved, frame, balls):
        """Called by the detector on every frame: t in seconds (video time in the sandbox), moved in px,
        balls = {track id: ((x, y), name)}."""
        if not self.moving:
            self.recent_moves = [x for x in self.recent_moves if t - x <= 0.5] + ([t] if moved > MOVE_PX else [])
            if len(self.recent_moves) >= START_FRAMES and self.before is not None:
                self.moving, self.start, self.quiet_since, self.last_sample = True, t, None, 0.0
                self.during, self.started, self.contact, self.seen = [], {}, None, {}
            elif moved <= MOVE_PX and (self.before is None or t - self.before[0] >= 0.5):
                self.before = (t, shrink(frame, 1024), dict(balls))  # kept fresh while the table is still
            return
        rest = self.before[2]
        for tid, (centre, _) in balls.items():  # which balls have been set moving, in order
            self.seen[tid] = t
            if tid in rest and tid not in self.started and np.hypot(*np.subtract(centre, rest[tid][0])) > STARTED_PX:
                self.started[tid] = t
                if len(self.started) == 2:  # the second ball to move: the cue ball has just hit it
                    self.contact = shrink(frame, 768)
        if t - self.last_sample >= 0.25:
            self.during.append(shrink(frame, 640))
            self.last_sample = t
        self.quiet_since = None if moved > MOVE_PX else (self.quiet_since or t)
        if (self.quiet_since is not None and t - self.quiet_since >= QUIET) or t - self.start > MAX_SHOT:
            after = shrink(frame, 1024)
            # gone = not seen at all while the table settled (missing from one frame is just detector flicker)
            gone = [tid for tid in rest if self.seen.get(tid, self.start) < t - QUIET]
            self.jobs.put((self.game_id, self.before[1], self._frames(), after, self._hints(rest, balls, gone)))
            self.moving, self.before, self.recent_moves = False, (t, after, dict(balls)), []

    def _frames(self):
        """The contact frame if the tracker caught one, then the middle of the shot; or a third and two-thirds."""
        n = len(self.during)
        if self.contact is not None:
            return [("contact", self.contact)] + ([("during", self.during[n // 2])] if n else [])
        if not n:
            return []
        return [("during", self.during[n // 3]), ("during", self.during[2 * n // 3])]

    def _hints(self, rest, after, gone):
        order = sorted(self.started, key=self.started.get)
        name = lambda tid: rest[tid][1]
        hints = []
        if order:
            hints.append(f"first ball to move: {name(order[0])}")
            hints.append(f"first ball it set moving: {name(order[1])} (the contact image is that moment)" if len(order) > 1
                         else "it set no other ball moving")
        hints.append("balls gone from the table: " + (", ".join(name(tid) for tid in gone) if gone else "none"))
        names = [n for _, n in after.values()]
        hints.append("cue ball on the table after: " + (
            "yes" if "cue ball" in names else "not seen" if any(n != "unnamed ball" for n in names) else "unknown"))
        return "; ".join(hints)

    def _work(self):
        while True:
            game_id, before, during, after, hints = self.jobs.get()
            if game_id != self.game_id:
                continue  # a new game started meanwhile
            self.judging = True
            try:
                self._judge(before, during, after, hints)
            except Exception as e:
                self.feed.insert(0, {"time": time.strftime("%H:%M:%S"), "error": f"couldn't judge a shot: {e}"})
            self.judging = False

    def _judge(self, before, during, after, hints):
        s = self.state
        players = s["players"]
        recent = [f["summary"] for f in self.feed[:3] if f.get("summary")]
        order = ", ".join(["before (table still)"] + [kind for kind, _ in during] + ["after (table still again)"])
        prompt = PROMPT.format(rules=RULES.read_text(encoding="utf-8"), state=json.dumps(s), recent=json.dumps(recent),
                               hints=hints, n=len(during) + 2, order=order, shooter=s["shooter"], players=json.dumps(players))
        images = [llm.image_part(before)] + [llm.image_part(f) for _, f in during] + [llm.image_part(after)]
        started = time.time()
        a = llm.ask_json(prompt, images)
        took = round(time.time() - started, 1)
        self.clips += 1
        folder = self.folder / f"{self.game_id}-{self.clips:03d}"
        folder.mkdir(parents=True, exist_ok=True)
        for i, img in enumerate([before, *[f for _, f in during], after]):
            cv2.imwrite(str(folder / f"{i}.jpg"), img)
        (folder / "answer.json").write_text(json.dumps({"hints": hints, "answer": a}, indent=2))
        entry = {"time": time.strftime("%H:%M:%S"), "took": took, "shooter": s["shooter"], "clip": folder.name, "hints": hints}
        if not a.get("shot"):
            entry["summary"] = "not a shot: " + str(a.get("say", ""))
            entry["ignored"] = True
        else:
            entry.update(self._apply(a))
        self.feed.insert(0, entry)
        with self.log.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"game": self.game_id, **entry, "answer": a, "state": self.state}) + "\n")

    def _apply(self, a):
        """Takes the referee's answer into the game state, keeping only what is physically possible."""
        s, players, notes = self.state, self.state["players"], []
        shooter = s["shooter"]
        s["shots"] += 1
        s["broken"] = True
        counts = {k: sum(p["kind"] == k for p in s["potted"]) for k in LIMITS}
        down = {str(p["ball"]) for p in s["potted"]}
        potted = []
        for ball, kind, pocket in [(list(x) + [None, None, None])[:3] for x in a.get("pot") or []]:
            if str(ball) in down and str(ball).isdigit():
                notes.append(f"ignored {ball}: already potted")
            elif kind in LIMITS and counts[kind] >= LIMITS[kind]:
                notes.append(f"ignored a {kind}: all {LIMITS[kind]} already down")
            else:
                if kind in counts:
                    counts[kind] += 1
                potted.append({"ball": ball, "kind": kind, "pocket": pocket, "by": shooter, "shot": s["shots"]})
        s["potted"] += potted
        for p, g in (a.get("group") or {}).items():
            if p in players and g in ("solids", "stripes") and s["groups"][p] is None:
                s["groups"][p] = g
                other = next(q for q in players if q != p)
                if s["groups"][other] is None:
                    s["groups"][other] = "stripes" if g == "solids" else "solids"
        if a.get("next") in players:
            s["shooter"] = a["next"]
        s["ball_in_hand"] = bool(a.get("hand"))
        if a.get("win") in players:
            s["winner"] = a["win"]
        foul = a.get("foul") if a.get("foul") not in (None, "null", "", False) else None
        return {"shot": s["shots"], "summary": a.get("say"), "announcement": a.get("say"), "potted": potted,
                "foul": foul, "cue_ball_potted": bool(a.get("scratch")), "first_contact": a.get("hit"),
                "is_break": bool(a.get("break")), "next": s["shooter"], "notes": notes}

    def status(self):
        s = self.state
        left = {k: LIMITS[k] - sum(p["kind"] == k for p in s["potted"]) for k in ("solid", "stripe")}
        return {"state": s, "left": left, "feed": self.feed[:30], "judging": self.judging or not self.jobs.empty(),
                "watching": "shot in progress" if self.moving else "waiting for a shot"}
