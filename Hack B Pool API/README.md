# Rackroom: local pool server

This machine hosts the club database (`pool.sqlite3` beside `main.py`).
Players, matchups, statuses, results and ordered video segments persist across
restarts. Tests use temporary databases. To change the storage location, set
`POOL_DB` to an absolute file path before starting the server.

## Setup (PowerShell, Python 3.10+)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Run the scoreboard and API together

Build the sibling React client (`npm.cmd run build` in `Hack B Pool Client`)
before starting FastAPI. One process serves both screens and the API:

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 5187
```

Open `/` for the desktop board, `/play` for the phone controller, or `/docs`
for interactive API docs. On a physical phone, localhost means the phone,
not the server. Place a trusted HTTPS reverse proxy on the club network in
front of the loopback server and open `https://<club-host>/play`. Plain HTTP
on a LAN IP is insufficient for camera access. Restrict access to trusted
participants: this initial local server does not implement user accounts.

## External video analyzer

The phone uploads ordered video segments during play. Stopping waits for
the final segment before changing the match from `recording` to `pending`.
Only `complete` matches count toward standings. No LLM is bundled.

1. Configure a secret `POOL_ANALYZER_KEY` on the server and worker, then
   restart the API. Never put this key in the React client.
2. The worker polls `GET /api/board` for pending matches. The IDs `a` and `b`
   refer to the two entries in `players`.
3. Fetch `GET /api/matches/{id}/video` with the `X-Analyzer-Key` header.
   The body is the complete MP4 or WebM recording in upload order.
4. After analysis, send `POST /api/matches/{id}/result` with the same header
   and JSON `{"winner": <winning player ID>}`. If there is no reliable
   winner, leave it pending. The board refreshes every four seconds.

Discarded captures and accepted results delete their video segments; player
and match history remain. Pending recordings consume local disk space until
processed. Abruptly closing the recorder tab may leave an unfinished match.
For a consistent backup, stop the server before copying the database.

## API-only development

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Interactive API documentation: http://127.0.0.1:8000/docs

- `GET /api/health` returns the API status.
- `GET /api/message` retains the original starter greeting.

The client lives in the sibling `Hack B Pool Client` folder. Its Vite development
server proxies `/api` requests here, so no CORS configuration is needed.
For production, route `/api` to this server using your web server or reverse proxy.

## Test

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest -v
```
