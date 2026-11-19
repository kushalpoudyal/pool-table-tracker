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
            return httpx.Response(200, stream=Frames(), headers={
                "Content-Type": "multipart/x-mixed-replace; boundary=frame",
            })

        client_type = httpx.Client
        with patch.dict(os.environ, POOL_STREAM_SERVER="http://camera.test"), patch(
            "remote_stream.httpx.Client",
            side_effect=lambda **kwargs: client_type(transport=httpx.MockTransport(respond), **kwargs),
        ), TestClient(app) as client:
            self.assertTrue(client.get("/api/stream-server/status").json()["connected"])
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
            self.assertEqual(client.get("/api/stream-server/video").status_code, 502)
        with patch.dict(os.environ, POOL_STREAM_SERVER=""), TestClient(app) as client:
            self.assertEqual(client.get("/api/stream-server/status").json(), {"configured": False})
            self.assertEqual(client.get("/api/stream-server/video").status_code, 503)


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
