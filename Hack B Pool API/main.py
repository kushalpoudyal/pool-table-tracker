from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from tracker import router
from remote_stream import router as stream_router

app = FastAPI(title="Hack B Pool API")
app.include_router(router)
app.include_router(stream_router)


class HealthResponse(BaseModel):
    status: str


class MessageResponse(BaseModel):
    message: str


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/api/message", response_model=MessageResponse)
def get_message() -> MessageResponse:
    return MessageResponse(message="Hello from the Hack B Pool API!")


client_dist = Path(__file__).resolve().parent.parent / "Hack B Pool Client" / "dist"
if (client_dist / "index.html").is_file() and (client_dist / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=client_dist / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    @app.get("/play", include_in_schema=False)
    @app.get("/watch", include_in_schema=False)
    def clubhouse():
        return FileResponse(client_dist / "index.html", headers={"Cache-Control": "no-store"})
