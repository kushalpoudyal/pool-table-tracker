import json
import unittest
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import httpx

from fastapi.testclient import TestClient

from main import app


class ApiTests(unittest.TestCase):
    def test_health(self) -> None:
        with TestClient(app) as client:
            response = client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_message(self) -> None:
        with TestClient(app) as client:
            response = client.get("/api/message")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {"message": "Hello from the Hack B Pool API!"}
        )


class RemoteStreamTests(unittest.TestCase):
    def test_external_feed_proxy(self):
        body = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n\xff\xd8test\xff\xd9\r\n"

        class Frames(httpx.SyncByteStream):
            def __iter__(self):
                yield body

        def respond(request):
            if request.url.path == "/status":
                return httpx.Response(200, json={
                    "connected": True, "source": "phone", "width": 640, "height": 360, "fps": 5,
                })
            if request.url.path == "/watch":
                return httpx.Response(200, json={
                    "active": True, "match": 7, "winner": None, "events": [],
                    "players": [{"name": "Ana", "group": "solids", "at_table": True, "potted": ["3"], "left": 6}],
                })
            return httpx.Response(200, stream=Frames(), headers={
                "Content-Type": "multipart/x-mixed-replace; boundary=frame",
            })

        client_type = httpx.Client
        with patch.dict(os.environ, POOL_STREAM_SERVER="http://camera.test"), patch(
            "remote_stream.httpx.Client",
            side_effect=lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs),
        ), TestClient(app) as client:
            self.assertTrue(client.get("/api/stream-server/status").json()["connected"])
            game = client.get("/api/stream-server/game").json()
            self.assertTrue(game["configured"])
            self.assertEqual(game["players"][0]["potted"], ["3"])
            response = client.get("/api/stream-server/video")
            self.assertEqual(response.content, body)
            self.assertEqual(response.headers["content-type"], "multipart/x-mixed-replace; boundary=frame")
            self.assertEqual(response.headers["cache-control"], "no-store")

    def test_upstream_errors_are_explicit(self):
        client_type = httpx.Client
        with patch.dict(os.environ, POOL_STREAM_SERVER="http://camera.test"), patch(
            "remote_stream.httpx.Client",
            side_effect=lambda **kwargs: client_type(
                transport=httpx.MockTransport(lambda request: httpx.Response(503)),
                **kwargs,
            ),
        ), TestClient(app) as client:
            self.assertEqual(client.get("/api/stream-server/status").status_code, 502)
            self.assertEqual(client.get("/api/stream-server/game").status_code, 502)
            self.assertEqual(client.get("/api/stream-server/video").status_code, 502)
        with patch.dict(os.environ, POOL_STREAM_SERVER=""), TestClient(app) as client:
            self.assertEqual(client.get("/api/stream-server/status").json(), {"configured": False})
            self.assertEqual(client.get("/api/stream-server/game").json(), {"configured": False})
            self.assertEqual(client.get("/api/stream-server/video").status_code, 503)


class StreamServerGameTests(unittest.TestCase):
    """A game scored by the external camera: start hands it the names, end records its winner."""

    def setUp(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        env = patch.dict(os.environ, POOL_DB=str(Path(folder.name) / "test.sqlite3"),
                         POOL_STREAM_SERVER="http://camera.test")
        env.start()
        self.addCleanup(env.stop)
        self.sent, self.final = [], {}

        def respond(request):
            self.sent.append((request.method, request.url.path, request.content and json.loads(request.content)))
            return httpx.Response(200, json=self.final if request.url.path == "/game/end" else {"ok": True})

        self.client_type = client_type = httpx.Client
        mock = patch("remote_stream.httpx.Client",
                     side_effect=lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs))
        mock.start()
        self.addCleanup(mock.stop)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.a, self.b = [self.client.post("/api/players", json={"name": n}).json()["id"] for n in ("Ada", "Sam")]

    def test_game_is_recorded_with_the_stream_servers_winner(self):
        game = self.client.post("/api/stream-server/game", json={"a": self.a, "b": self.b}).json()
        report = {"url": f"http://testserver/api/stream-server/game/{game['id']}/result", "token": game["token"]}
        zero = {"played": 0, "won": 0, "streak": None, "best_streak": 0, "avg_potted": None, "last_played": None}
        self.assertEqual(self.sent, [("POST", "/game", {
            "players": ["Ada", "Sam"], "match": game["id"], "report": report,
            "stats": {"Ada": zero, "Sam": zero, "head_to_head": {"played": 0, "wins": {"Ada": 0, "Sam": 0}}}})])
        self.final = {"match": game["id"], "winner": "sam", "players": [{"name": "Sam", "potted": ["9", "8"]}]}
        url = f"/api/stream-server/game/{game['id']}/end"
        self.assertEqual(self.client.post(url, headers={"X-Recorder-Key": "wrong"}).status_code, 403)
        ended = self.client.post(url, headers={"X-Recorder-Key": game["token"]}).json()
        self.assertEqual((ended["status"], ended["winner"]), ("complete", self.b))
        self.assertEqual(self.sent[-1][:2], ("POST", "/game/end"))
        match = self.client.get("/api/board").json()["matches"][0]
        self.assertEqual((match["status"], match["winner"], match["external"]), ("complete", self.b, 1))
        self.assertEqual(match["details"]["players"][0]["potted"], ["9", "8"])
        self.assertEqual(self.client.post(url, headers={"X-Recorder-Key": game["token"]}).status_code, 409)

    def test_end_game_trigger_records_the_stream_servers_result(self):
        game = self.client.post("/api/stream-server/game", json={"a": self.a, "b": self.b}).json()
        url, final = f"/api/stream-server/game/{game['id']}/result", {"match": game["id"], "winner": "Ada", "events": []}
        self.assertEqual(self.client.post(url, json=final, headers={"X-Recorder-Key": "wrong"}).status_code, 403)
        recorded = self.client.post(url, json=final, headers={"X-Recorder-Key": game["token"]}).json()
        self.assertEqual((recorded["status"], recorded["winner"]), ("complete", self.a))
        self.assertEqual(self.client.get("/api/board").json()["matches"][0]["details"], final)
        stop = self.client.post(f"/api/stream-server/game/{game['id']}/end", headers={"X-Recorder-Key": game["token"]})
        self.assertEqual(stop.status_code, 409)  # already recorded by the trigger

    def test_game_without_a_winner_is_not_counted(self):
        game = self.client.post("/api/stream-server/game", json={"a": self.a, "b": self.b}).json()
        self.final = {"match": game["id"], "winner": None, "players": []}
        ended = self.client.post(f"/api/stream-server/game/{game['id']}/end", headers={"X-Recorder-Key": game["token"]})
        self.assertEqual(ended.json()["status"], "interrupted")
        self.assertIsNone(self.client.get("/api/board").json()["matches"][0]["winner"])

    def test_bad_matchup_and_unreachable_camera(self):
        self.assertEqual(self.client.post("/api/stream-server/game", json={"a": self.a, "b": self.a}).status_code, 422)
        with patch("remote_stream.httpx.Client", side_effect=lambda **kwargs: self.client_type(
                transport=httpx.MockTransport(lambda request: httpx.Response(503)), **kwargs)):
            self.assertEqual(self.client.post("/api/stream-server/game", json={"a": self.a, "b": self.b}).status_code, 502)
        self.assertEqual(self.client.get("/api/board").json()["matches"][0]["status"], "interrupted")


class StreamServerStatsTests(unittest.TestCase):
    """The players' records sent with start-game, for the stream server's commentator."""

    def play(self, a, b, winner, potted=None):
        """One game on the camera; winner: a player id (counted) or None (interrupted)."""
        game = self.client.post("/api/stream-server/game", json={"a": a, "b": b}).json()
        names = {self.a: "Ada", self.b: "Sam", self.c: "Kit"}
        final = {"match": game["id"], "winner": names.get(winner),
                 "players": [{"name": n, "potted": balls} for n, balls in (potted or {}).items()]}
        self.client.post(f"/api/stream-server/game/{game['id']}/result", json=final,
                         headers={"X-Recorder-Key": game["token"]})

    def stats_sent(self, a, b):
        self.client.post("/api/stream-server/game", json={"a": a, "b": b})
        return self.sent[-1][2]["stats"]

    def setUp(self):
        StreamServerGameTests.setUp(self)  # the same stubbed camera and fresh database, without its tests
        self.c = self.client.post("/api/players", json={"name": "Kit"}).json()["id"]

    def test_records_streaks_and_head_to_head_from_counted_games(self):
        a, b, c = self.a, self.b, self.c
        self.play(a, b, a, {"Ada": ["1", "2", "8"], "Sam": ["9"]})
        self.play(a, c, c)
        self.play(b, a, a, {"ada": ["3"], "Sam": []})  # names match whatever the case
        self.play(a, b, None)  # interrupted: never counted
        self.play(a, c, a)
        self.play(b, a, b)
        stats = self.stats_sent(a, b)
        ada, sam = stats["Ada"], stats["Sam"]
        self.assertEqual((ada["played"], ada["won"], ada["streak"], ada["best_streak"]), (5, 3, {"type": "L", "n": 1}, 2))
        self.assertEqual((sam["played"], sam["won"], sam["streak"], sam["best_streak"]), (3, 1, {"type": "W", "n": 1}, 1))
        self.assertEqual(ada["avg_potted"], 2.0)  # 3 and 1, from the two stored final scores naming her
        self.assertEqual(sam["avg_potted"], 0.5)
        self.assertIsNotNone(ada["last_played"])
        self.assertEqual(stats["head_to_head"], {"played": 3, "wins": {"Ada": 2, "Sam": 1}})

    def test_the_watch_passthrough_keeps_the_lines(self):
        lines = [{"id": 3, "text": "Ada pots the 5.", "priority": "normal", "game": "g", "audio": True}]
        self.final = {}
        def respond(request):
            return httpx.Response(200, json={"active": True, "players": [], "events": [], "lines": lines})
        with patch("remote_stream.httpx.Client", side_effect=lambda **kwargs: self.client_type(
                transport=httpx.MockTransport(respond), **kwargs)):
            self.assertEqual(self.client.get("/api/stream-server/game").json()["lines"], lines)

    def test_commentary_audio_is_proxied(self):
        def respond(request):
            if request.url.path == "/commentary/3/audio":
                class Clip(httpx.SyncByteStream):
                    def __iter__(self):
                        yield b"ID3"
                        yield b"mp3"
                return httpx.Response(200, stream=Clip(), headers={"content-type": "audio/mpeg"})
            return httpx.Response(404)
        with patch("remote_stream.httpx.Client", side_effect=lambda **kwargs: self.client_type(
                transport=httpx.MockTransport(respond), **kwargs)):
            audio = self.client.get("/api/stream-server/commentary/3/audio")
            self.assertEqual((audio.status_code, audio.content, audio.headers["content-type"]), (200, b"ID3mp3", "audio/mpeg"))
            self.assertEqual(self.client.get("/api/stream-server/commentary/4/audio").status_code, 404)


class TrackerTests(unittest.TestCase):
    def setUp(self):
        temp = self.enterContext(TemporaryDirectory()) if hasattr(self, "enterContext") else None
        if temp is None:
            folder = TemporaryDirectory()
            self.addCleanup(folder.cleanup)
            temp = folder.name
        env = patch.dict(os.environ, POOL_DB=str(Path(temp) / "test.sqlite3"), POOL_ANALYZER_KEY="unit-test")
        env.start()
        self.addCleanup(env.stop)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.a, self.b = [
            self.client.post("/api/players", json={"name": name}).json()["id"] for name in ("Ada", "Sam")
        ]

    def test_scored_recording(self):
        game = self.client.post("/api/matches", json={"a": self.a, "b": self.b, "mime": "video/mp4"}).json()
        url = f"/api/matches/{game['id']}"
        recorder = {"X-Recorder-Key": game["token"]}
        worker = {"X-Analyzer-Key": "unit-test"}
        self.assertEqual(self.client.post(url + "/close?outcome=finish", headers=recorder).status_code, 409)
        for i, part in enumerate((b"first", b"second")):
            self.assertEqual(self.client.put(f"{url}/chunks/{i}", headers=recorder, content=part).status_code, 200)
        self.assertEqual(self.client.post(url + "/close?outcome=finish", headers=recorder).json()["status"], "pending")
        self.assertEqual(self.client.get(url + "/video", headers={"X-Analyzer-Key":"wrong"}).status_code, 403)
        self.assertEqual(self.client.get(url + "/video", headers=worker).content, b"firstsecond")
        self.assertEqual(self.client.post(url + "/result", headers=worker, json={"winner": -1}).status_code, 409)
        self.assertEqual(self.client.post(url + "/result", headers=worker, json={"winner": self.b}).status_code, 200)
        with TestClient(app) as new_client:
            match = new_client.get("/api/board").json()["matches"][0]
            self.assertEqual((match["a"], match["b"], match["winner"], match["status"]), (self.a,self.b,self.b,"complete"))

    def test_invalid_matchup_and_duplicate_name(self):
        self.assertEqual(self.client.post("/api/players", json={"name":"  ADA "}).status_code, 409)
        self.assertEqual(self.client.post("/api/matches", json={"a":self.a,"b":self.a,"mime":"video/webm"}).status_code, 422)

    def test_saved_quicktime_video(self):
        created = self.client.post("/api/matches", json={
            "a": self.a, "b": self.b, "mime": "video/quicktime",
        })
        self.assertEqual(created.status_code, 201)
        game = created.json()
        url = f"/api/matches/{game['id']}"
        headers = {"X-Recorder-Key": game["token"]}
        parts = [b"a" * (2 * 1024 * 1024), b"final segment"]
        for i, part in enumerate(parts):
            self.assertEqual(self.client.put(f"{url}/chunks/{i}", content=part, headers=headers).status_code, 200)
        self.assertEqual(self.client.post(url + "/close?outcome=finish", headers=headers).json()["status"], "pending")
        res = self.client.get(url + "/video", headers={"X-Analyzer-Key": "unit-test"})
        self.assertEqual(res.headers["content-type"], "video/quicktime")
        self.assertEqual(res.content, b"".join(parts))

    def test_live_feed_lifecycle(self):
        game = self.client.post("/api/matches", json={
            "a": self.a, "b": self.b, "mime": "video/webm",
        }).json()
        url = f"/api/matches/{game['id']}"
        headers = {"X-Recorder-Key": game["token"]}
        frame = b"\xff\xd8test-frame\xff\xd9"
        self.assertEqual(self.client.get(url + "/frame").status_code, 204)
        self.assertEqual(self.client.put(url + "/frame", content=frame, headers={"X-Recorder-Key":"wrong"}).status_code, 403)
        self.assertEqual(self.client.put(url + "/frame", content=b"bad", headers=headers).status_code, 422)
        self.assertEqual(self.client.put(url + "/frame", content=frame, headers=headers).status_code, 200)
        self.assertEqual(self.client.get(url + "/frame").content, frame)
        self.assertEqual(self.client.get("/api/board").json()["matches"][0]["live"], 1)
        with patch("tracker.time.time", return_value=99999999999):
            self.assertEqual(self.client.get(url + "/frame").status_code, 204)
            self.assertEqual(self.client.get("/api/board").json()["matches"][0]["live"], 0)
        self.client.post(url + "/close?outcome=discard", headers=headers)
        self.assertEqual(self.client.get(url + "/frame").status_code, 204)
        self.assertEqual(self.client.put(url + "/frame", content=frame, headers=headers).status_code, 409)


if __name__ == "__main__":
    unittest.main()
