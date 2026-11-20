"""The observer keeps the score. Every second it keeps a frame; every 5 seconds (or as soon as the
balls stop after a shot) it stitches the frames, in order, into one image and asks the LLM what
happened, together with what it remembers of the game so far. Each look also starts with the
previous look's last photo, so a ball that drops between two looks is still seen there in one photo
and gone in a later one of the same image.

The LLM writes who is at the table first and the answer is streamed, so the player shows ~1.3 s
after a look is sent; pots follow when the whole answer is in (~4 s).

Players are recognised from the labelled photos in assets/players/ (app/players.py stitches them into
one roster sheet). With no names typed, a game's first looks carry the sheet and the LLM works out who
is playing from faces, hair and build, and notes today's clothes; once every player has today's
clothes, the sheet stops being sent and looks stay small. With names given (Rackroom), the sheet and
descriptions carry only those players.

The app keeps the score: a pocketed ball counts once, and comes off the score only when a later look
clearly sees it back on the table (a mistake corrected, e.g. a ball that was only hidden by an arm).
After each shot a table check counts the balls on the table from full-size photos, and a ball it can't
find counts as potted (rather a false pot than a missed one). A player who pots their own ball stays at
the table; any other change of player takes two looks in a row. When the 8 goes down, a final check
decides the winner by the rules from the balls really left; then looks stop and the final score goes to
whoever started the game (Rackroom records it).

The commentator (app/commentator.py) hears every applied look and turns it into lines to be spoken; they
go out with the score (summary()["lines"]).
"""
import json
import queue
import threading
import time
from pathlib import Path

import cv2
import httpx
import numpy as np

from app import commentator as commentary, llm, players as roster_photos

ROOT = Path(__file__).resolve().parent.parent
RULES = ROOT / "rules" / "8ball.md"
EVERY = 1.0  # seconds between kept frames
WINDOW = 5  # frames per look when nothing triggers one sooner
MOVE_PX = 4  # a ball moving more than this between detector frames is motion
SETTLE = 0.6  # seconds without motion after movement: the shot is over, look now
GUEST = "Guest"  # someone playing who is not in the labelled photos
GUEST_LOOKS = 6  # looks to keep trying to recognise a Guest before accepting they really are one
TILE = (640, 360)  # 3 x 2 tiles = 1920 x 720: wide images keep the most detail in the model
LIMITS = {"solid": 7, "stripe": 7, "eight": 1}

PROMPT = """You are the referee and live commentator of a pool game, watching it from one camera in short looks.

House rules and the balls:
{rules}

{players_line}{roster}
What you remember so far (JSON): {memory}
Your last looks: {recent}

The {stitched} is {n} photos taken about one second apart, numbered 1 to {n} in order (left to right, top row first), covering {t0}-{t1} s of the game.{overlap}
Look for any ball dropping into a pocket: it is on the table in one photo and gone in a later one (also compare photo 1 with the balls you remember on the table). A ball sitting in the jaws has not dropped. Check every ball you remember on the table: one that is gone and that you can't find anywhere on the table has been potted, even if you didn't see it drop, so report it. Work out who is at the table and shooting, and whether a shot broke the rules.
Reply with compact JSON only, keys exactly, "shooting" first:
{{"shooting": one of {names} or null,
 "playing": [the names of everyone playing, from {names}],
 "potted": [["ball number or colour", "solid|stripe|eight|cue", "pocket", "player who potted it"]],
 "back": ["balls your memory lists as potted that you can clearly see on the table now (a mistake to correct)"],
 "groups": {{"<player>": "solids|stripes"}} or null,
 "foul": null or "who fouled and how",
 "looks": {{"<player>": "what they are wearing today, to recognise them from above"}}, only for players your memory has no looks for, else {{}},
 "on_table": ["balls you can see on the table now"],
 "winner": null, or one of {names} once the rules decide the game,
 "summary": "one line of live commentary: what happened in these seconds, and who is ahead"}}"""

CHECK_PROMPT = """Photos of a pool table a second or more apart: the end of the last shot, and now. A ball hidden by a person or a cue in one photo may show in the other.
List every ball on the table (a ball sitting in a pocket's jaws is still on the table). Look at each ball closely: a solid is all one colour, a stripe is white with a coloured band (from above it can look mostly white or mostly colour), the 8 is black, the cue ball is plain white. Solids: 1 yellow, 2 blue, 3 red, 4 purple, 5 orange, 6 green, 7 maroon; stripes 9-15 have the same colours in that order.
Say also whether every part of the playing surface is in view in at least one photo (not cut off, nobody covering it).
JSON only: {"balls": [["number if readable, else null", "colour", "solid|stripe|eight|cue"]], "whole_table": true or false}"""
NUMBERS = {"solid": range(1, 8), "stripe": range(9, 16)}


def stitch(frames):
    """[(t, frame)] -> one image: numbered, timestamped tiles in a 3 x 2 grid."""
    tiles = []
    for i, (t, f) in enumerate(frames):
        tile = cv2.resize(f, TILE, interpolation=cv2.INTER_AREA)
        cv2.rectangle(tile, (0, 0), (150, 34), (0, 0, 0), -1)
        cv2.putText(tile, f"{i + 1}  {t:.0f}s", (6, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        tiles.append(tile)
    tiles += [np.zeros_like(tiles[0])] * (6 - len(tiles))
    return np.vstack([np.hstack(tiles[0:3]), np.hstack(tiles[3:6])])


class Observer:
    def __init__(self, name, camera, table, active=True, commentator=None):
        self.camera, self.table = camera, table  # table(): the marked outline or None
        self.folder = ROOT / "recordings" / f"{name}-looks"
        self.log = ROOT / "logs" / f"game-{name}.jsonl"
        self.commentator = commentator or commentary.from_env()
        self.commentator.on_line(self._log_line)
        self.jobs = queue.Queue()
        self.lock = threading.Lock()
        self.busy = False
        self.running = True
        self.new_game([], announce=active)  # no names: recognise the players from assets/players
        self.active = active  # live only looks between New game and End game; the sandbox from the start
        self.moving, self.recent_moves, self.quiet_since = False, [], None
        threading.Thread(target=self._collect, daemon=True).start()
        threading.Thread(target=self._work, daemon=True).start()

    def stop(self):
        self.running = False

    def new_game(self, players, match=None, report=None, stats=None, announce=True):
        """players: names in break order, or [] to recognise them from the labelled photos.
        match: the caller's id for this game (Rackroom's match id), kept with the game.
        report: {"url", "token"} to send the final score to once the game is decided (Rackroom records it).
        stats: each player's record from Rackroom, for the commentator (see app/commentator.py).
        announce: the commentator calls the break (not for the live camera's idle state at startup)."""
        if not players and not roster_photos.photos():
            players = ["Player 1", "Player 2"]  # nothing to recognise people from
        with self.lock:
            self.memory = {"players": players, "looks": {}, "groups": {p: None for p in players},
                           "potted": [], "shooting": players[0] if players else None, "on_table": [], "winner": None,
                           "match": match}
            self.feed = []  # newest first
            self.game_id = time.strftime("%Y%m%d-%H%M%S")
            self.frames, self.previous = [], None  # previous: last frame of the last look, photo 1 of the next
            self.started_at = None  # camera time of the first frame of this game
            self.guest_looks = 0  # looks so far with a provisional Guest among the players
            self.turn_claim = None  # a new player at the table named by the last look, waiting for the next look to agree
            self.look_shooter = self.memory["shooting"]  # who was at the table when the current look was sent
            self.decide = False  # the 8 is down or a look says the game is over: the final check decides the winner
            self.eight_foul = False  # the look that saw the 8 go down also saw a foul
            self.report = report  # not in memory: memory goes to the LLM and the token must not
            self.active = True
            self.commentator.new_game(self.game_id, players, stats, announce=announce)

    def end_game(self):
        with self.lock:
            self.active, self.frames = False, []

    def watch(self, t, moved, frame, balls):
        """Called by the detector on every frame: when the balls stop after moving, look straight away."""
        if not self.active:
            return
        if not self.moving:
            self.recent_moves = [x for x in self.recent_moves if t - x <= 0.5] + ([t] if moved > MOVE_PX else [])
            if len(self.recent_moves) >= 3:  # moving for real, not one flicker
                self.moving, self.quiet_since = True, None
            return
        self.quiet_since = None if moved > MOVE_PX else (self.quiet_since or t)
        if self.quiet_since is not None and t - self.quiet_since >= SETTLE:
            self.moving, self.recent_moves = False, []
            with self.lock:  # the shot is over: this frame closes the look early
                if self.frames and t - self.frames[-1][0] > 0.3:
                    self.frames.append((t, self._crop(frame)))
                if len(self.frames) >= 2:
                    self._send(settled=True)

    def _send(self, settled=False):
        """Queue the frames gathered so far as one look (caller holds the lock). settled: a shot just ended,
        so the balls are counted after the look."""
        self.jobs.put((self.game_id, ([self.previous] if self.previous else []) + self.frames, settled))
        self.previous, self.frames = self.frames[-1], []

    def _crop(self, frame):
        """The table plus room around it for the players, if the table is marked; else the whole frame."""
        table = self.table()
        if table is None:
            return frame
        h, w = frame.shape[:2]
        x1, y1 = table.min(0)
        x2, y2 = table.max(0)
        mx, my = 0.35 * (x2 - x1), 0.35 * (y2 - y1)
        return frame[max(int(y1 - my), 0):min(int(y2 + my), h), max(int(x1 - mx), 0):min(int(x2 + mx), w)]

    def _collect(self):
        last = None
        while self.running:
            _, frame = self.camera.latest()
            t = self.camera.frame_time  # video time in the sandbox
            if self.active and frame is not None and (last is None or t - last >= EVERY or t < last):
                last = t
                with self.lock:
                    self.frames.append((t, self._crop(frame)))
                    if len(self.frames) >= WINDOW:
                        self._send()
            if self.active:
                self.commentator.tick()
            time.sleep(0.05)

    def _work(self):
        while True:
            self._handle(*self.jobs.get())

    def _handle(self, game_id, frames, settled=False):
        """One queued look: read it, take it into memory, check the table after a settled shot, and finish
        the game if it is decided."""
        if game_id != self.game_id:
            return  # a new game started meanwhile
        self.busy = True
        try:
            self._look(frames)
            entry = self.feed[0]
            heard = len(entry["notes"])
            if self.active and self.decide:
                self._final_check()
            elif self.active and settled:
                self._check_table()
            if len(entry["notes"]) > heard:  # the checks changed the score or decided the game: say so too
                self.commentator.heard({"potted": [], "notes": entry["notes"][heard:], "summary": None,
                                        "shooting": self.memory["shooting"]}, self.memory)
            if self.memory["winner"] and self.active:
                self._finish()
        except Exception as e:
            self.feed.insert(0, {"time": time.strftime("%H:%M:%S"), "error": f"couldn't read a look: {e}"})
        self.busy = False

    def _look(self, frames):
        m = self.memory
        if self.started_at is None:
            self.started_at = frames[0][0]
        t0, t1 = frames[0][0] - self.started_at, frames[-1][0] - self.started_at
        image = stitch([(t - self.started_at, f) for t, f in frames])
        recent = [f["summary"] for f in self.feed[:4] if f.get("summary")][::-1]
        overlap = (" Photo 1 is the last photo of your previous look, repeated so nothing falls between looks:"
                   " don't count anything twice that you already reported.") if self.feed else ""
        people, sheet = roster_photos.roster() if roster_photos.photos() else ([], None)
        known = list(dict.fromkeys(p["name"] for p in people))  # someone can be in several photos
        # recognising until there are two players; a Guest is provisional for GUEST_LOOKS more looks, since
        # someone small or turned away in the first look is often on the roster after all
        if GUEST in m["players"]:
            self.guest_looks += 1
        identifying = known and (len(m["players"]) < 2 or (GUEST in m["players"] and self.guest_looks <= GUEST_LOOKS))
        names = (known + [GUEST]) if identifying else (m["players"] or ["Player 1", "Player 2"])
        if not identifying and sheet is not None:  # the players are named: only their photos, not everyone's
            people, sheet = roster_photos.only(people, sheet, m["players"])
        images = [llm.image_part(image)]
        # the roster sheet only until both players are known and their clothes today are noted
        if sheet is not None and (identifying or any(p not in m["looks"] for p in m["players"])):
            images.insert(0, llm.image_part(sheet))
        players_line = (f"Players: {json.dumps(m['players'])} ({m['players'][0]} broke first)." if not identifying else
                        f"Players known so far: {json.dumps(m['players'])}. Work out who is playing (the people at the "
                        f'table with cues, not onlookers) and list them all in "playing"; someone playing who is not on '
                        f'the roster sheet is "{GUEST}".')
        prompt = PROMPT.format(
            rules=RULES.read_text(encoding="utf-8"), players_line=players_line, names=json.dumps(names),
            roster=(" The first image is a roster sheet: photos of everyone who may play, labelled with their names, "
                    "taken on other days (clothes and glasses can differ today, so match face shape, hair, skin and build; "
                    "a person can appear on the sheet more than once): " +
                    "; ".join(f"{p['name']}: {p['looks']}" for p in people) + ". Use these names only.") if images[1:] else "",
            stitched="second image" if images[1:] else "image", memory=json.dumps(m), recent=json.dumps(recent),
            n=len(frames), t0=round(t0), t1=round(t1), overlap=overlap)
        started = time.time()
        first = {}

        self.look_shooter = m["shooting"]

        def early(shooting):  # who is at the table, ~1.3 s in: show it before the rest of the answer arrives
            first["took"] = round(time.time() - started, 1)
            # a different player shows only when the last look already named them (two looks in a row)
            if shooting in (names if identifying else m["players"]) and m["shooting"] in (None, shooting) \
                    or shooting == self.turn_claim:
                m["shooting"] = shooting

        a = llm.stream_json(prompt, images, "shooting", early)
        took = round(time.time() - started, 1)
        self.folder.mkdir(parents=True, exist_ok=True)
        name = f"{self.game_id}-{len(self.feed) + 1:03d}"
        cv2.imwrite(str(self.folder / f"{name}.jpg"), image)
        (self.folder / f"{name}.json").write_text(json.dumps(a, indent=2))
        entry = {"time": time.strftime("%H:%M:%S"), "took": took, "player_after": first.get("took"),
                 "t0": round(t0), "t1": round(t1), "roster_sheet": bool(images[1:]),
                 **self._apply(a, names if identifying else ())}
        self.feed.insert(0, entry)
        self._write_log({"game": self.game_id, **entry, "answer": a, "memory": self.memory})
        self.commentator.heard(entry, self.memory)

    def _write_log(self, record):
        self.log.parent.mkdir(parents=True, exist_ok=True)
        with self.log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")

    def _log_line(self, line):
        """Every line the commentator says goes into the game's look log, next to the looks that led to it."""
        try:
            self._write_log({"game": line["game"], "time": time.strftime("%H:%M:%S"), "line": line})
        except OSError:
            pass

    def _apply(self, a, known=()):
        """Takes the look into memory, keeping only what is possible: corrections first, then new pots, each counted once."""
        m, notes = self.memory, []
        if known and GUEST in m["players"]:  # the Guest turned out to be on the roster: rename them everywhere
            named = [p for p in a.get("playing") or [] if p in known and p not in (m["players"] + [GUEST])]
            if named:
                self._rename(GUEST, named[0])
                notes.append(f"recognised: {GUEST} is {named[0]}")
        if known:  # recognising the players: add whoever the LLM says is playing, until there are two
            new = [p for p in a.get("playing") or [] if p in known and p not in m["players"]][:2 - len(m["players"])]
            if new:
                m["players"] += new
                m["groups"].update({p: None for p in new})
                m["shooting"] = m["shooting"] or new[0]
                notes.append("recognised: " + ", ".join(new))
        players = m["players"]
        for ball in a.get("back") or []:  # a pot that a later look sees back on the table was a mistake
            if any(str(p["ball"]) == str(ball) for p in m["potted"]):
                m["potted"] = [p for p in m["potted"] if str(p["ball"]) != str(ball)]
                notes.append(f"correction: the {ball} is still on the table, not potted")
        counts = {k: sum(p["kind"] == k for p in m["potted"]) for k in LIMITS}
        down = {str(p["ball"]) for p in m["potted"]}
        new = []
        for ball, kind, pocket, by in [(list(x) + [None] * 4)[:4] for x in a.get("potted") or []]:
            if kind == "cue":
                if not a.get("foul"):  # the foul note below says it otherwise
                    notes.append("cue ball potted (scratch)")
                continue
            if str(ball) in down and str(ball).isdigit():
                continue  # already counted in an earlier look
            if kind in LIMITS and counts[kind] >= LIMITS[kind]:
                notes.append(f"ignored a {kind}: all {LIMITS[kind]} already down")
                continue
            counts[kind] = counts.get(kind, 0) + 1
            new.append({"ball": ball, "kind": kind, "pocket": pocket,
                        "by": by if by in players else self.look_shooter or m["shooting"]})
        m["potted"] += new
        if a.get("foul"):
            notes.append(f"foul: {a['foul']}")
        if any(b["kind"] == "eight" for b in new):  # the final check decides who won, from the balls really left
            self.decide, self.eight_foul = True, bool(a.get("foul")) or any(
                (list(x) + [None] * 2)[1] == "cue" for x in a.get("potted") or [])
        for p, g in (a.get("groups") or {}).items():
            if p in players and g in ("solids", "stripes") and m["groups"][p] is None:
                m["groups"][p] = g
                others = [q for q in players if q != p]
                if len(others) == 1 and m["groups"][others[0]] is None:
                    m["groups"][others[0]] = "stripes" if g == "solids" else "solids"
        for p, look in (a.get("looks") or {}).items():
            if p in players and look:
                m["looks"][p] = look  # today's clothes: once every player has them, the roster sheet stops
        # who is at the table: a legal pot keeps the shooter there; any other change of player takes two looks in
        # a row (one look often catches the other player walking round the table, or misses a pot)
        shooter, said = self.look_shooter, a.get("shooting")
        group = (m["groups"].get(shooter) or "")[:-1]
        potted_own = any(b["by"] == shooter and b["kind"] in ((group,) if group else ("solid", "stripe")) for b in new)
        if shooter not in players:
            m["shooting"] = said if said in players else m["shooting"]
        elif potted_own and not a.get("foul"):
            m["shooting"], self.turn_claim = shooter, None
        elif said in players and said != shooter:
            if said == self.turn_claim:
                m["shooting"], self.turn_claim = said, None
            else:
                m["shooting"], self.turn_claim = shooter, said
        else:
            m["shooting"], self.turn_claim = shooter, None
        if a.get("on_table"):
            m["on_table"] = a["on_table"]
        if a.get("winner") in players:  # a look says the game is over: the final check decides who won
            self.decide = True
        return {"summary": a.get("summary"), "potted": new, "notes": notes, "shooting": m["shooting"]}

    def _rename(self, old, new):
        m = self.memory
        m["players"] = [new if p == old else p for p in m["players"]]
        m["groups"] = {(new if p == old else p): g for p, g in m["groups"].items()}
        m["looks"] = {(new if p == old else p): v for p, v in m["looks"].items()}
        for b in m["potted"]:
            if b["by"] == old:
                b["by"] = new
        if m["shooting"] == old:
            m["shooting"] = new
        self.look_shooter = new if self.look_shooter == old else self.look_shooter
        self.turn_claim = new if self.turn_claim == old else self.turn_claim

    def _table_now(self, whole=False):
        """A count of the balls on the table from full-size photos: the end of the last look and now (a ball hidden
        in one may show in the other). {"solid", "stripe", "eight", "cue": count, "seen": numbers read}; with
        whole=True, None when part of the table is out of view."""
        _, frame = self.camera.latest()
        photos = ([self.previous[1]] if self.previous else []) + ([self._crop(frame)] if frame is not None else [])
        a = llm.ask_json(CHECK_PROMPT, [llm.image_part(p, 1600) for p in photos])
        with self.log.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"game": self.game_id, "time": time.strftime("%H:%M:%S"), "table_check": a}) + "\n")
        if whole and not a.get("whole_table"):
            return None
        balls = [(list(b) + [None] * 3)[:3] for b in a.get("balls") or []]
        count = {k: sum(b[2] == k for b in balls) for k in ("solid", "stripe", "eight", "cue")}
        return {**count, "seen": {str(b[0]) for b in balls if b[0] is not None}}

    def _missed_pots(self, c):
        """Counts every ball the table check can't find as potted (pots the looks missed; Kushal: rather a false pot
        than a missed one). A missing ball goes to the player whose group it is, else to the shooter."""
        m, notes = self.memory, []
        for kind in ("solid", "stripe"):
            down = [b for b in m["potted"] if b["kind"] == kind]
            gone = LIMITS[kind] - len(down) - c[kind]
            if gone <= 0:
                continue
            missing = [str(n) for n in NUMBERS[kind] if str(n) not in {str(b["ball"]) for b in down} | c["seen"]]
            owner = next((p for p, g in m["groups"].items() if g == kind + "s"), None)
            for i in range(gone):
                m["potted"].append({"ball": missing[i] if len(missing) == gone else kind, "kind": kind,
                                    "pocket": None, "by": owner or m["shooting"]})
            notes.append(f"table check: {gone} {kind}{'s' if gone > 1 else ''} gone from the table, counted as potted")
        return notes

    def _check_table(self):
        """After each shot: count the balls on the table and add the pots the looks missed, even if part of the
        table is covered (Kushal: rather a false pot than a missed one). A missing 8 means the game may be over,
        which the final check decides."""
        c = self._table_now()
        self.feed[0]["notes"] += self._missed_pots(c)
        if not c["eight"] and not any(b["kind"] == "eight" for b in self.memory["potted"]):
            self._final_check()

    def _final_check(self):
        """The 8 is down, or a look says the game is over. Decide who won by the rules from the balls really left on
        the table, not from the score kept so far (a missed pot made a legal 8 look like a loss): the player who
        potted the 8 wins if none of their group is left and that shot was not a foul; else the other player wins."""
        self.decide = False
        m = self.memory
        c = self._table_now(whole=True) or (time.sleep(2) or self._table_now(whole=True))
        if c is None:  # someone is in the way: try again after the next look
            self.decide = True
            self.feed[0]["notes"].append("final check: couldn't see the whole table, checking again")
            return
        if c["eight"]:  # the 8 is still on the table: no game over
            m["potted"] = [b for b in m["potted"] if b["kind"] != "eight"]
            self.feed[0]["notes"].append("final check: the 8 is still on the table, the game goes on")
            return
        notes = self._missed_pots(c)
        eight = next((b for b in m["potted"] if b["kind"] == "eight"), None)
        if eight is None:  # gone without a look seeing it drop
            eight = {"ball": "8", "kind": "eight", "pocket": None, "by": m["shooting"]}
            m["potted"].append(eight)
        shooter = eight["by"] if eight["by"] in m["players"] else m["shooting"]
        group = (m["groups"].get(shooter) or "")[:-1]
        if not group:  # groups never recorded: the shooter's group is the one cleared, if just one is
            cleared = [k for k in ("solid", "stripe") if not c[k]]
            group = cleared[0] if len(cleared) == 1 else ""
        left = c[group] if group else None
        others = [p for p in m["players"] if p != shooter]
        won = bool(group) and left == 0 and not self.eight_foul
        m["winner"] = shooter if won else (others[0] if others else None)
        notes.append(f"final check: {shooter} potted the 8 with "
                     + (f"{left} {group}{'' if left == 1 else 's'} left" if group else "no group cleared")
                     + (" on a foul" if self.eight_foul else "") + f": {m['winner']} wins")
        self.feed[0]["notes"] += notes

    def _finish(self):
        """The game is decided: stop looking and send the final score to whoever started the game. If sending
        fails, Stop game in Rackroom still records it (POST /game/end returns the same final score)."""
        self.end_game()
        if not self.report:
            return
        try:
            httpx.post(self.report["url"], json=self.summary(None), headers={"X-Recorder-Key": self.report["token"]},
                       timeout=10).raise_for_status()
            note = "game over: result sent"
        except httpx.HTTPError as e:
            note = f"game over: couldn't send the result ({e})"
        self.feed[0]["notes"].append(note)

    def summary(self, latest=8):
        """What a Watch screen needs, in one small payload: each player's group, balls potted and balls left,
        who is at the table, the winner, the caller's match id, the latest moments of play (newest first;
        latest=None: the whole game, for the final score), and the commentator's lines (oldest first: the
        latest 20, or all of them in the final score)."""
        m = self.memory
        down = {k: sum(b["kind"] == k for b in m["potted"]) for k in LIMITS}
        players = [{"name": p, "group": m["groups"].get(p), "at_table": m["shooting"] == p,
                    "potted": [str(b["ball"]) for b in m["potted"] if b["by"] == p],
                    "left": LIMITS[m["groups"][p][:-1]] - down[m["groups"][p][:-1]] if m["groups"].get(p) else None}
                   for p in m["players"]]
        events = [{"time": f["time"], "summary": f.get("summary"), "notes": f.get("notes", []),
                   "potted": [{"ball": str(b["ball"]), "pocket": b["pocket"], "by": b["by"]} for b in f.get("potted", [])]}
                  for f in self.feed[:latest] if not f.get("error")]
        lines = self.commentator.lines(None if latest is None else commentary.SHOWN)
        return {"active": self.active, "match": m.get("match"), "winner": m["winner"], "players": players,
                "events": events, "lines": lines}

    def status(self):
        m = self.memory
        score = {p: [b["ball"] for b in m["potted"] if b["by"] == p] for p in m["players"]}
        left = {k: LIMITS[k] - sum(b["kind"] == k for b in m["potted"]) for k in ("solid", "stripe")}
        return {"memory": m, "score": score, "left": left, "feed": self.feed[:40], "active": self.active,
                "busy": self.busy or not self.jobs.empty(), "collecting": len(self.frames),
                "roster": roster_photos.cached_names()}
