import json
import os
import secrets
from contextlib import ExitStack

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ValidationError
from starlette.background import BackgroundTask

from tracker import EXTERNAL, db, recorder_status

router = APIRouter(prefix="/api/stream-server")


class StreamGame(BaseModel):
    a: int
    b: int


class CameraStatus(BaseModel):
    connected: bool
    source: str
    width: int
    height: int
    fps: float


def server_url():
    url = os.getenv("POOL_STREAM_SERVER", "").rstrip("/")
    if not url:
        raise HTTPException(503, "No external stream server configured.")
    return url


@router.get("/status")
def status():
    if not os.getenv("POOL_STREAM_SERVER"):
        return {"configured": False}
    try:
        with httpx.Client(timeout=5) as client:
            response = client.get(server_url() + "/status")
            response.raise_for_status()
            camera = CameraStatus.model_validate_json(response.content)
    except (httpx.HTTPError, ValidationError) as exc:
        raise HTTPException(502, "Cannot read the external camera status.") from exc
    return {"configured": True, **camera.model_dump()}


@router.get("/game")
def game():
    """The stream server's score for the Watch tab: players (group, potted, left, at the table),
    winner, match and the latest moments of play."""
    if not os.getenv("POOL_STREAM_SERVER"):
        return {"configured": False}
    try:
        with httpx.Client(timeout=5) as client:
            response = client.get(server_url() + "/watch")
            response.raise_for_status()
            watch = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, "Cannot read the external camera score.") from exc
    return {"configured": True, **watch}


@router.post("/game", status_code=201)
def start_game(game: StreamGame, request: Request):
    """Start a game on the external camera: a Rackroom match for the leaderboard, and the two names
    (Player A breaks) handed to the stream server, which keeps the score from there. It also gets where to
    send the final score when it sees the game decided (POST .../result, with this match's recorder key)."""
    url = server_url()
    with db() as c:
        names = dict(c.execute("SELECT id,name FROM players WHERE id IN (?,?)", (game.a, game.b)).fetchall())
        if game.a == game.b or len(names) != 2:
            raise HTTPException(422, "Choose two different registered players.")
        token = secrets.token_urlsafe(32)
        match_id = c.execute("INSERT INTO matches(a,b,mime,token) VALUES(?,?,?,?)",
                             (game.a, game.b, EXTERNAL, token)).lastrowid
    players = [names[game.a], names[game.b]]
    report = {"url": f"{request.base_url}api/stream-server/game/{match_id}/result", "token": token}
    try:
        with httpx.Client(timeout=5) as client:
            client.post(url + "/game", json={"players": players, "match": match_id, "report": report}).raise_for_status()
    except httpx.HTTPError as exc:
        with db() as c:
            c.execute("UPDATE matches SET status='interrupted' WHERE id=?", (match_id,))
        raise HTTPException(502, "Cannot start the game on the external camera.") from exc
    return {"id": match_id, "token": token, "players": players}


def open_game(match_id, key):
    """The players of an open external-camera game, by lower-case name, if this recorder key may close it."""
    with db() as c:
        if recorder_status(c, match_id, key) != "recording":
            raise HTTPException(409, "This game is already closed.")
        match = c.execute("SELECT a,b,mime FROM matches WHERE id=?", (match_id,)).fetchone()
        if match["mime"] != EXTERNAL:
            raise HTTPException(409, "This game is not on the external camera.")
        return {name.casefold(): pid for pid, name in
                c.execute("SELECT id,name FROM players WHERE id IN (?,?)", (match["a"], match["b"]))}


def record(match_id, ids, final):
    """The stream server's final score decides: its winner (a name) becomes the match winner and the game
    counts; no winner means the game is not counted. The final score is kept with the match (board: details)."""
    if final.get("match") != match_id:
        raise HTTPException(409, "The external camera is scoring a different game.")
    winner = ids.get(str(final.get("winner") or "").casefold())
    status = "complete" if winner else "interrupted"
    with db() as c:
        closed = c.execute("UPDATE matches SET status=?,winner=? WHERE id=? AND status='recording'",
                           (status, winner, match_id)).rowcount
        if not closed:  # Stop and the end-game trigger at the same moment: the first one counts
            raise HTTPException(409, "This game is already closed.")
        c.execute("INSERT OR REPLACE INTO match_details(match_id,details) VALUES(?,?)", (match_id, json.dumps(final)))
    return {"status": status, "winner": winner, "details": final}


@router.post("/game/{match_id}/end")
def end_game(match_id: int, x_recorder_key: str = Header()):
    """Stop game: stop the external camera's game and record its final score (every moment of the game)."""
    url = server_url()
    ids = open_game(match_id, x_recorder_key)
    try:  # outside the transaction: the stream server may take a moment
        with httpx.Client(timeout=5) as client:
            response = client.post(url + "/game/end")
            response.raise_for_status()
            final = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, "Cannot read the final score from the external camera.") from exc
    return record(match_id, ids, final)


@router.post("/game/{match_id}/result")
def result(match_id: int, final: dict, x_recorder_key: str = Header()):
    """The end-game trigger: the stream server saw the game decided and sends its final score, recorded like
    Stop game's."""
    return record(match_id, open_game(match_id, x_recorder_key), final)


@router.get("/video")
def video():
    url = server_url()
    try:
        with ExitStack() as stack:
            client = stack.enter_context(httpx.Client(timeout=httpx.Timeout(5, read=10)))
            upstream = stack.enter_context(client.stream("GET", url + "/video"))
            upstream.raise_for_status()
            content_type = upstream.headers.get("content-type", "")
            if not content_type.lower().startswith("multipart/x-mixed-replace;"):
                raise HTTPException(502, "The stream server did not return an MJPEG feed.")
            resources = stack.pop_all()
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Cannot connect to the external camera feed.") from exc
    return StreamingResponse(
        upstream.iter_raw(),
        headers={"Content-Type": content_type, "Cache-Control": "no-store",
                 "X-Accel-Buffering": "no"},
        background=BackgroundTask(resources.close),
    )
