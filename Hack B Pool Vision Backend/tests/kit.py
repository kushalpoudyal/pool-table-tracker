"""A table with no camera, no model and no network: an Observer fed scripted look answers.

    table = Table(["Ada", "Sam"])              # a game between two made-up players, Ada breaking
    table.look(potted=[["5", "solid", "top right", "Ada"]], groups={"Ada": "solids"})
    table.said()                               # the lines in the Watch payload, as (text, priority)
    table.writer.asks                          # the colour requests, each answered with table.writer.answer(...)
    table.clock.advance(21); table.observer.commentator.tick()
"""
import shutil
import tempfile
import unittest.mock
from pathlib import Path

import numpy as np

from app import llm
from app.commentator import Commentator
from app.observer import Observer


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class Camera:
    frame_time = 0.0

    def latest(self):
        return 0, None


class Writer:
    """The colour-line writer, answered by the test: answer(text) delivers the oldest open request's line."""

    def __init__(self):
        self.asks = []  # [(request, deliver)]
        self.fail = False

    def ask(self, request, deliver):
        if self.fail:
            raise RuntimeError("the writer is broken")
        self.asks.append((request, deliver))

    def answer(self, text, index=0):
        request, deliver = self.asks[index]
        deliver(text)

    @property
    def kinds(self):
        return [r.kind for r, _ in self.asks]


class Voice:
    """Speech made instantly: each chunk names the text it is for."""

    def __init__(self):
        self.spoken = []

    def synthesize(self, text):
        self.spoken.append(text)
        yield b"ID3"
        yield text.encode()


def now(work, *args):
    work(*args)


class Table:
    def __init__(self, players=("Ada", "Sam"), stats=None, writer=True, voice=None, enabled=True):
        self.clock = Clock()
        self.writer = Writer() if writer else None
        self.voice = voice
        from app.voice import Clips
        clips = Clips(voice, spawn=now) if voice else None
        commentator = Commentator(self.writer, clock=self.clock, enabled=enabled, clips=clips)
        self.folder = Path(tempfile.mkdtemp(prefix="pool-test-"))
        self.observer = Observer("test", Camera(), lambda: None, active=False, commentator=commentator)
        self.observer.folder, self.observer.log = self.folder / "looks", self.folder / "game.jsonl"
        self.observer.new_game(list(players), match=7, stats=stats)

    def close(self):
        self.observer.stop()
        shutil.rmtree(self.folder, ignore_errors=True)

    def look(self, **answer):
        """One look whose LLM answer is `answer` (keys as in the observer's prompt), applied like a real one."""
        full = {"shooting": None, "playing": [], "potted": [], "back": [], "groups": None, "foul": None,
                "looks": {}, "on_table": [], "winner": None, "summary": "", **answer}

        def stream_json(prompt, images, key, early):
            early(full["shooting"])
            return full

        frames = [(t, np.zeros((36, 64, 3), np.uint8)) for t in (0.0, 1.0)]
        with unittest.mock.patch.object(llm, "stream_json", stream_json):
            self.observer._handle(self.observer.game_id, frames)
        errors = [f["error"] for f in self.observer.feed if f.get("error")]
        if errors:
            raise AssertionError(errors[0])

    def lines(self):
        return self.observer.summary()["lines"]

    def said(self):
        return [(line["text"], line["priority"]) for line in self.lines()]

    def texts(self):
        return [line["text"] for line in self.lines()]
