# Hack B Pool Client

Rackroom is a React pool scoreboard and phone camera controller. Requires Node.js 22.12+.
Use `/` to add players and see standings and match history; use `/play` to
choose players and tap **Start game & stream**. Camera permission is
requested and the game starts streaming immediately, without a separate
preview step. The controller
records live video without audio on HTTPS or localhost. The controller is
live-only; it does not offer saved-video uploads. Keep the page open until
it shows **Awaiting analysis** after stopping the game.

Starting live recording flags the game as started on the scoreboard.
The **Watch games** tab (`/watch`) displays each server-relayed table
preview (up to four frames per second) while the phone uploads the
complete recording for analysis. No sign-in is required for viewers.
Leave Watch games open on another screen; it discovers matches within
four seconds and removes the feed when the game stops. Live camera
access still depends on the phone browser exposing `getUserMedia`.
Watch games can also display an existing remote MJPEG camera via the
Python proxy. Configure `POOL_STREAM_SERVER` on the API server; the phone
controller continues uploading its local match to Rackroom.
Player selection enables **Start game & stream**; a denied or unavailable
camera reports an error without creating a match. To offer a link from an
HTTP controller to a separately configured live-camera endpoint, set
`VITE_LIVE_CAMERA_URL` in `.env.local` before building. This link does not
bypass the phone's certificate trust or camera permission requirements.

## Setup and run (PowerShell)

```powershell
npm.cmd install
npm.cmd run dev
```

Open http://127.0.0.1:5173.

If port 5173 is already in use, run `npm.cmd run dev -- --port 5187`
and open http://127.0.0.1:5187 instead.

Start the FastAPI server from the sibling `Hack B Pool API` folder first.
Vite proxies `/api` to http://127.0.0.1:8000.

## Production build

```powershell
npm.cmd run build
```

The sibling FastAPI app serves the built `dist` on `/`, `/play` and `/watch`.
See the [local server guide](../Hack%20B%20Pool%20API/README.md) for SQLite
storage, trusted HTTPS for physical phones, and the analyzer handoff.
