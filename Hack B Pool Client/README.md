# Hack B Pool Client

Rackroom is a React pool scoreboard and phone camera controller. Requires Node.js 22.12+.
Use `/` to add players and see standings and match history; use `/play` to
choose players, preview the rear camera and record a game. The controller
uploads video only (no audio) and waits for an external analysis result.

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

The sibling FastAPI app serves the built `dist` on `/` and `/play`.
See the [local server guide](../Hack%20B%20Pool%20API/README.md) for SQLite
storage, trusted HTTPS for physical phones, and the analyzer handoff.
