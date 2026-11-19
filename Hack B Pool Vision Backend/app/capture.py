"""Reads the camera in a background thread and keeps only the newest frame.

Source "phone" (default): the Android phone's camera over USB, through scrcpy's server.
Nothing is installed on the phone: the server is pushed over adb and runs while plugged in.
A video file (the sandbox) plays once in real time, like a live camera, through PyAV.
Any other source goes to OpenCV, e.g. "0" for the laptop webcam.
"""
import os
import random
import shutil
import socket
import struct
import subprocess
import threading
import time
from pathlib import Path

import av
import cv2

ADB = os.getenv("ADB") or shutil.which("adb") or "adb"
SCRCPY_VERSION = "5.0.1"  # the server only talks to a client of the exact same version
SCRCPY_SERVER = os.getenv("SCRCPY_SERVER") or str(
    Path(shutil.which("scrcpy") or "scrcpy").resolve().parent / "scrcpy-server")
PORT = 27183
FILE_WIDTH = 1920  # video files are shrunk to this as they are decoded (a 4K frame costs 4x to convert)
FILE_FPS = 30  # at most this many frames a second of a video file are converted for the detector
# Back camera 0 zoomed out to 0.6 = the ultra-wide lens, for the overhead view.
CAMERA = ["camera_id=0", "camera_zoom=0.6", "camera_size=1920x1080", "camera_fps=60"]


def adb(*args):
    return subprocess.run([ADB, *args], capture_output=True, timeout=10, check=True)


def recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("stream closed")
        buf += chunk
    return bytes(buf)


class Camera:
    def __init__(self, source: str):
        self.source = source
        self.frame = None
        self.frame_id = 0
        self.fps = 0.0
        self.last_frame_at = 0.0
        self.frame_time = 0.0  # when the newest frame was taken: wall clock, or position in a video file
        self.running = True
        self.ended = False  # a video file played to the end
        self.duration = 0.0  # length of a video file, in seconds
        self._count, self._window_start = 0, time.time()
        self._lock = threading.Lock()
        run = self._run_phone if source == "phone" else self._run_file if Path(source).is_file() else self._run_opencv
        threading.Thread(target=run, daemon=True).start()

    def _publish(self, frame, at=None):
        now = time.time()
        with self._lock:
            self.frame = frame
            self.frame_time = now if at is None else at
            self.frame_id += 1
            self.last_frame_at = now
        self._count += 1
        if now - self._window_start >= 1:
            self.fps = self._count / (now - self._window_start)
            self._count, self._window_start = 0, now

    def _run_phone(self):
        last_error = None
        while self.running:  # unplugged, locked or crashed: start again
            server = None
            try:
                # only one app can hold the camera: stop any server left from a previous run
                subprocess.run([ADB, "shell", "pkill", "-f", "scrcpy.Server"], capture_output=True, timeout=10)
                scid = f"{random.getrandbits(31):08x}"
                adb("push", SCRCPY_SERVER, "/data/local/tmp/scrcpy-server.jar")
                adb("forward", f"tcp:{PORT}", f"localabstract:scrcpy_{scid}")
                server = subprocess.Popen(
                    [ADB, "shell", "CLASSPATH=/data/local/tmp/scrcpy-server.jar", "app_process", "/",
                     "com.genymobile.scrcpy.Server", SCRCPY_VERSION, f"scid={scid}", "video_source=camera",
                     *CAMERA, "audio=false", "control=false", "tunnel_forward=true", "send_device_meta=false"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self._stream_phone(self._connect())
            except Exception as e:  # the reader thread must never die
                if str(e) != last_error:
                    print(f"camera: {e} (retrying)")
                    last_error = str(e)
            finally:
                if server:
                    server.kill()
            time.sleep(1)

    @staticmethod
    def _connect():
        deadline = time.time() + 5
        while time.time() < deadline:  # the server takes a moment to start listening
            sock = socket.create_connection(("127.0.0.1", PORT), timeout=5)
            if sock.recv(1) == b"\x00":  # the server's first byte: it is up
                return sock
            sock.close()
            time.sleep(0.2)
        raise ConnectionError("camera server did not start")

    def _stream_phone(self, sock):
        codec = recv_exact(sock, 4)
        if codec != b"h264":  # 0 or 1 = the phone could not open the camera
            raise ConnectionError(f"camera did not start (code {codec.hex()})")
        decoder = av.CodecContext.create("h264", "r")
        config = b""
        while True:
            pts_and_flags, size = struct.unpack(">QI", recv_exact(sock, 12))
            if pts_and_flags & (1 << 63):  # session header (width, height), no payload
                continue
            data = recv_exact(sock, size)
            if pts_and_flags & (1 << 62):  # codec config: belongs in front of the next frame
                config = data
                continue
            for frame in decoder.decode(av.Packet(config + data)):
                self._publish(frame.to_ndarray(format="bgr24"))
            config = b""

    def _run_file(self):
        """Threaded decode (4K60 HEVC keeps up), frames converted and shrunk in one step, and only
        FILE_FPS of them a second: the detector takes the newest, exactly as with the live camera."""
        with av.open(self.source) as container:
            stream = container.streams.video[0]
            stream.thread_type = "AUTO"
            self.duration = float(container.duration or 0) / 1e6
            start, last = time.time(), -1.0
            for frame in container.decode(stream):
                if not self.running:
                    return
                t = float(frame.time or 0)
                ahead = start + t - time.time()
                if ahead > 0:
                    time.sleep(ahead)  # never faster than the file's own speed
                # behind (4K decoding with the detector busy): feed the detector at a third of the rate while
                # catching up, never nothing, or shot detection goes blind
                if t - last < (1 / FILE_FPS if ahead > -0.2 else 3 / FILE_FPS):
                    continue
                last = t
                w = min(frame.width, FILE_WIDTH)
                self._publish(frame.to_ndarray(format="bgr24", width=w, height=round(frame.height * w / frame.width)), t)
        self.ended = True

    def _run_opencv(self):
        source = int(self.source) if self.source.isdigit() else self.source
        while self.running:
            cap = cv2.VideoCapture(source)
            while self.running and cap.isOpened():
                ok, frame = cap.read()
                if not ok:
                    break
                self._publish(frame)
            cap.release()
            time.sleep(1)

    def stop(self):
        self.running = False

    def latest(self):
        with self._lock:
            return self.frame_id, self.frame

    def status(self):
        age = time.time() - self.last_frame_at if self.last_frame_at else None
        connected = age is not None and age < 2
        h, w = self.frame.shape[:2] if self.frame is not None else (0, 0)
        return {
            "connected": connected,
            "ended": self.ended,
            "source": Path(self.source).name if self.source != "phone" else "phone",
            "width": w,
            "height": h,
            "fps": round(self.fps, 1) if connected else 0,
            "position": round(self.frame_time, 1) if self.duration else None,
            "duration": round(self.duration, 1) if self.duration else None,
        }
