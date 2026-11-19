import unittest
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

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


if __name__ == "__main__":
    unittest.main()
