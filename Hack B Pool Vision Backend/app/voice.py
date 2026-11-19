"""The commentator's voice: each line made into speech here, on the server, and streamed to the browser.

    voice = voice.from_env()            # None without ELEVENLABS_API_KEY: browsers speak the text themselves
    clips = Clips(voice)
    clips.start(line_id, text)          # starts synthesising at once, in the background
    for chunk in clips.stream(line_id): # MP3 bytes as they arrive; a second reader gets them all too
        ...

The voice is the seam: anything with ``synthesize(text) -> iterator of MP3 chunks``. ``ElevenLabsVoice`` is
the real one (Flash v2.5, ~75-185 ms to first audio); tests use a fake. Fixed wording repeats ("Sam to
shoot."), so a finished clip is kept by its text and a repeat costs nothing.

The key stays here (.env); the browser only ever sees /commentary/{id}/audio.
"""
import logging
import os
import threading
from collections import OrderedDict

import httpx

log = logging.getLogger(__name__)

MODEL = "eleven_flash_v2_5"
VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"  # ElevenLabs' example voice in their API docs; ELEVENLABS_VOICE_ID to change
FORMAT = "mp3_44100_64"  # small enough to stream instantly on a phone, clear enough for speech
KEEP_CLIPS = 200  # lines whose audio is kept (a game is ~30-60 lines)
KEEP_TEXTS = 300  # finished clips kept by text, for fixed wording that repeats


class ElevenLabsVoice:
    def __init__(self, key, voice_id=VOICE_ID, model=MODEL, client=None):
        self._key, self._voice_id, self._model = key, voice_id, model
        self._client = client or httpx.Client(timeout=httpx.Timeout(10, read=15))

    def synthesize(self, text):
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self._voice_id}/stream"
        with self._client.stream("POST", url, params={"output_format": FORMAT},
                                 headers={"xi-api-key": self._key},
                                 json={"text": text, "model_id": self._model}) as r:
            r.raise_for_status()
            yield from r.iter_bytes()


class _Clip:
    def __init__(self):
        self.chunks, self.done, self.failed = [], False, False
        self.ready = threading.Condition()


def in_background(work, *args):
    threading.Thread(target=work, args=args, name="voice", daemon=True).start()


class Clips:
    """The audio of each line, by line id, made once and streamed to every reader."""

    def __init__(self, voice, spawn=in_background):
        self._voice, self._spawn = voice, spawn
        self._clips = OrderedDict()  # line id -> _Clip
        self._by_text = OrderedDict()  # text -> bytes of a finished clip
        self._lock = threading.Lock()
        self._logged = set()

    def start(self, line_id, text):
        clip = _Clip()
        with self._lock:
            self._clips[line_id] = clip
            while len(self._clips) > KEEP_CLIPS:
                self._clips.popitem(last=False)
            cached = self._by_text.get(text)
        if cached is not None:
            clip.chunks, clip.done = [cached], True
            return
        self._spawn(self._make, clip, text)

    def _make(self, clip, text):
        try:
            for chunk in self._voice.synthesize(text):
                if chunk:
                    with clip.ready:
                        clip.chunks.append(chunk)
                        clip.ready.notify_all()
        except Exception as e:  # never more than a silent line: the browser falls back to its own voice
            clip.failed = True
            reason = f"{type(e).__name__}" + (f" {e.response.status_code}" if isinstance(e, httpx.HTTPStatusError) else "")
            if reason not in self._logged:
                self._logged.add(reason)
                log.warning("No commentary audio: %s. The lines still show as text. (Logged once.)", reason)
        with clip.ready:
            clip.done = True
            clip.ready.notify_all()
        if not clip.failed and clip.chunks:
            with self._lock:
                self._by_text[text] = b"".join(clip.chunks)
                while len(self._by_text) > KEEP_TEXTS:
                    self._by_text.popitem(last=False)

    def has(self, line_id):
        """Whether there is (or will be) audio for this line: false for an unknown line or a failed synthesis."""
        clip = self._clips.get(line_id)
        if clip is None:
            return False
        with clip.ready:
            clip.ready.wait_for(lambda: clip.chunks or clip.done, timeout=10)
            return bool(clip.chunks)

    def stream(self, line_id, timeout=15):
        """The line's MP3, chunk by chunk as it is made. Ends early if synthesis fails or stalls."""
        clip = self._clips.get(line_id)
        if clip is None:
            return
        i = 0
        while True:
            with clip.ready:
                if not clip.ready.wait_for(lambda: len(clip.chunks) > i or clip.done, timeout=timeout):
                    return
                new, finished = clip.chunks[i:], clip.done
            for chunk in new:
                yield chunk
            i += len(new)
            if finished and i >= len(clip.chunks):
                return


def from_env(environ=os.environ):
    """ELEVENLABS_API_KEY (no key: no server audio, browsers speak the text), ELEVENLABS_VOICE_ID (optional)."""
    key = (environ.get("ELEVENLABS_API_KEY") or "").strip()
    if not key:
        log.warning("Commentary audio is off: ELEVENLABS_API_KEY is not set; browsers will speak the lines.")
        return None
    return ElevenLabsVoice(key, (environ.get("ELEVENLABS_VOICE_ID") or "").strip() or VOICE_ID)
