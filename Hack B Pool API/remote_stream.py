import os
from contextlib import ExitStack

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ValidationError
from starlette.background import BackgroundTask

router = APIRouter(prefix="/api/stream-server")


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
