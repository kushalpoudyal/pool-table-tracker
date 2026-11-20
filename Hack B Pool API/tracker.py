import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager, closing
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api")
EXTERNAL = "external/stream-server"  # the mime of matches scored by the stream server: no video is uploaded here
SCHEMA = """
CREATE TABLE IF NOT EXISTS players(id INTEGER PRIMARY KEY, name TEXT NOT NULL, key TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS matches(
 id INTEGER PRIMARY KEY, a INTEGER NOT NULL, b INTEGER NOT NULL, mime TEXT NOT NULL,
 token TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'recording', winner INTEGER,
 started TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')));
CREATE TABLE IF NOT EXISTS chunks(match_id INTEGER, seq INTEGER, data BLOB NOT NULL,
 PRIMARY KEY(match_id,seq));
CREATE TABLE IF NOT EXISTS live_frames(
 match_id INTEGER PRIMARY KEY, data BLOB NOT NULL, updated REAL NOT NULL);
CREATE TABLE IF NOT EXISTS match_details(match_id INTEGER PRIMARY KEY, details TEXT NOT NULL);
"""


@contextmanager
def db():
    path = os.getenv("POOL_DB", str(Path(__file__).with_name("pool.sqlite3")))
    with closing(sqlite3.connect(path, timeout=10)) as conn:
        conn.row_factory = sqlite3.Row
        conn.executescript(SCHEMA)
        with conn:
            yield conn


class Player(BaseModel):
    name: str = Field(min_length=1, max_length=48)


class NewMatch(BaseModel):
    a: int
    b: int
    mime: Literal["video/webm", "video/mp4", "video/quicktime"]


class Verdict(BaseModel):
    winner: int


@router.get("/board")
def board():
    with db() as c:
        c.execute("BEGIN")
        players = c.execute("SELECT id,name FROM players ORDER BY name COLLATE NOCASE").fetchall()
        games = c.execute("""
            SELECT m.id,a,b,status,winner,started,
                   coalesce(f.updated > ?,0) AND status='recording' AS live, mime=? AS external, d.details
            FROM matches m LEFT JOIN live_frames f ON f.match_id=m.id
            LEFT JOIN match_details d ON d.match_id=m.id
            ORDER BY m.id DESC
        """, (time.time() - 5, EXTERNAL)).fetchall()
    # details: the external camera's final score for its games (see remote_stream.py), else null
    matches = [{**dict(g), "details": json.loads(g["details"]) if g["details"] else None} for g in games]
    return {"players": list(map(dict, players)), "matches": matches}


@router.post("/players", status_code=201)
def add_player(player: Player):
    name = " ".join(player.name.split())
    if not name:
        raise HTTPException(422, "Enter a player name.")
    with db() as c:
        try:
            cur = c.execute("INSERT INTO players(name,key) VALUES(?,?)", (name, name.casefold()))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "That player is already on the roster.") from None
        return {"id": cur.lastrowid, "name": name}


@router.post("/matches", status_code=201)
def new_match(game: NewMatch):
    with db() as c:
        if c.execute("SELECT count(*) FROM players WHERE id IN (?,?)", (game.a, game.b)).fetchone()[0] != 2:
            raise HTTPException(422, "Choose two different registered players.")
        token = secrets.token_urlsafe(32)
        cur = c.execute("INSERT INTO matches(a,b,mime,token) VALUES(?,?,?,?)", (game.a, game.b, game.mime, token))
        return {"id": cur.lastrowid, "token": token}


def recorder_status(c, match_id, token):
    c.execute("BEGIN IMMEDIATE")
    row = c.execute("SELECT status,token FROM matches WHERE id=?", (match_id,)).fetchone()
    if not row or not secrets.compare_digest(row["token"], token or ""):
        raise HTTPException(403, "Invalid recorder key.")
    return row["status"]


@router.put("/matches/{match_id}/chunks/{seq}")
async def upload(match_id: int, seq: int, request: Request, x_recorder_key: str = Header()):
    data = bytearray()
    async for part in request.stream():
        if len(data) + len(part) > 8 * 1024 * 1024:
            raise HTTPException(413, "Recording segment is too large.")
        data.extend(part)
    if not data:
        raise HTTPException(422, "Empty recording segment.")
    with db() as c:
        if recorder_status(c, match_id, x_recorder_key) != "recording":
            raise HTTPException(409, "This recording is already closed.")
        expected = c.execute("SELECT coalesce(max(seq)+1,0) FROM chunks WHERE match_id=?", (match_id,)).fetchone()[0]
        if seq != expected:
            raise HTTPException(409, "Unexpected recording segment.")
        c.execute("INSERT INTO chunks VALUES(?,?,?)", (match_id, seq, data))
    return {"received": seq}


@router.put("/matches/{match_id}/frame")
async def send_frame(match_id: int, request: Request, x_recorder_key: str = Header()):
    data = bytearray()
    async for part in request.stream():
        if len(data) + len(part) > 512 * 1024:
            raise HTTPException(413, "Live preview frame is too large.")
        data.extend(part)
    if not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
        raise HTTPException(422, "Live preview requires a JPEG frame.")
    with db() as c:
        if recorder_status(c, match_id, x_recorder_key) != "recording":
            raise HTTPException(409, "This recording is already closed.")
        c.execute(
            "INSERT OR REPLACE INTO live_frames VALUES(?,?,?)",
            (match_id, data, time.time()),
        )
    return {"received": True}


@router.get("/matches/{match_id}/frame")
def live_frame(match_id: int):
    with db() as c:
        row = c.execute("""
            SELECT f.data FROM live_frames f JOIN matches m ON m.id=f.match_id
            WHERE m.id=? AND m.status='recording' AND f.updated>?
        """, (match_id, time.time() - 5)).fetchone()
    headers = {"Cache-Control": "no-store"}
    if not row:
        return Response(status_code=204, headers=headers)
    return Response(content=bytes(row["data"]), media_type="image/jpeg", headers=headers)


@router.post("/matches/{match_id}/close")
def close(match_id: int, outcome: Literal["finish", "discard"], x_recorder_key: str = Header()):
    with db() as c:
        previous = recorder_status(c, match_id, x_recorder_key)
        if (outcome == "finish" and previous in ("pending", "complete")) or (
            outcome == "discard" and previous == "interrupted"
        ):
            return {"status": previous}
        if previous != "recording":
            raise HTTPException(409, "This recording is already closed.")
        if outcome == "discard":
            c.execute("DELETE FROM chunks WHERE match_id=?", (match_id,))
            status = "interrupted"
        else:
            if not c.execute("SELECT 1 FROM chunks WHERE match_id=? LIMIT 1", (match_id,)).fetchone():
                raise HTTPException(409, "No video received.")
            status = "pending"
        c.execute("UPDATE matches SET status=? WHERE id=?", (status, match_id))
        c.execute("DELETE FROM live_frames WHERE match_id=?", (match_id,))
    return {"status": status}


@router.post("/matches/{match_id}/winner")
def correct_winner(match_id: int, verdict: Verdict, x_recorder_key: str = Header()):
    """Correct a finished game's result (the table camera or the analyzer got it wrong, or saw no winner). Only
    the device that ran the game holds its recorder key; the game then counts with this winner."""
    with db() as c:
        if recorder_status(c, match_id, x_recorder_key) not in ("complete", "interrupted"):
            raise HTTPException(409, "Only a finished game's winner can be corrected.")
        updated = c.execute("UPDATE matches SET status='complete',winner=? WHERE id=? AND ? IN (a,b)",
                            (verdict.winner, match_id, verdict.winner))
        if not updated.rowcount:
            raise HTTPException(422, "The winner must be one of the two players.")
    return {"status": "complete", "winner": verdict.winner}


def authorize_worker(key):
    secret = os.getenv("POOL_ANALYZER_KEY")
    if not secret or not secrets.compare_digest(secret, key):
        raise HTTPException(403, "Analyzer access is not enabled for this key.")


@router.get("/matches/{match_id}/video")
def video(match_id: int, x_analyzer_key: str = Header()):
    authorize_worker(x_analyzer_key)
    with db() as c:
        row = c.execute("SELECT mime FROM matches WHERE id=? AND status='pending'", (match_id,)).fetchone()
    if not row:
        raise HTTPException(404, "No pending recording.")

    def segments():
        with db() as c:
            for item in c.execute("SELECT data FROM chunks WHERE match_id=? ORDER BY seq", (match_id,)):
                yield item[0]

    return StreamingResponse(segments(), media_type=row["mime"])


@router.post("/matches/{match_id}/result")
def result(match_id: int, verdict: Verdict, x_analyzer_key: str = Header()):
    authorize_worker(x_analyzer_key)
    with db() as c:
        updated = c.execute(
            "UPDATE matches SET status='complete',winner=? WHERE id=? AND status='pending' AND ? IN (a,b)",
            (verdict.winner, match_id, verdict.winner),
        )
        if not updated.rowcount:
            raise HTTPException(409, "Result requires a pending match and one of its players.")
        c.execute("DELETE FROM chunks WHERE match_id=?", (match_id,))
    return {"status": "complete"}
