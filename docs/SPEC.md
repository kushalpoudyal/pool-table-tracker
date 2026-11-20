# Pool Table Tracker — Agreed Spec

Agreed 2026-11-19 via design grilling session. Open items at the bottom.

## Product
A PWA (Android Chrome + iOS Safari) on a phone mounted above a pool table. It streams the table to a cloud server that tracks an **8-ball** game, enforces the rules, and drives spoken pro-broadcast-style commentary through the phone speakers. Results are recorded in Rackroom's own leaderboard. Rackroom is kept separate from the CORTO Pool app: no CORTO integration.

Scope: hackathon demo, one known table/lighting first; concurrent tables supported by design (session-keyed).

## Rules (WPA-lite 8-ball)
- Rules engine is pure logic on the server, behind an interface (9-ball later).
- 2 players, no teams. Turns inferred from rules + ball state.
- Break: app randomly picks breaker and announces it. 8 on the break = breaker wins. Break scratch = ball in hand to opponent, table stays open. Illegal-break (4 balls to rail) rule skipped.
- Open table until first legally pocketed ball assigns solids/stripes.
- **No pocket calling** — legally pocketing the 8 after clearing your group wins.
- Loss: 8 pocketed before group cleared; 8 pocketed on a shot that also scratches/fouls; 8 off the table.
- Auto-detected fouls: scratch, wrong ball first (incl. 8 first on open table), no ball hit. Stretch goal (off by default): no rail after contact. Out of scope: double hits, push shots.
- Foul → ball in hand to opponent.

## Existing code: Rackroom
The repo already contains Rackroom (`Hack B Pool API` FastAPI + SQLite, `Hack B Pool Client` React 19 + Vite). We build on it:
- Keep: React client, FastAPI app shell, static serving of the built client, the `/play` phone controller as the starting UI, unittest + TestClient test style.
- Replace: Rackroom's record-whole-game → chunked upload → external analyzer flow with live frame streaming and on-server analysis.
- Keep: Rackroom's SQLite roster, matches and `/` standings board as **the leaderboard** (see Leaderboard).

## Phone (PWA)
- React + Vite (Rackroom client), extending `/play`.
- Setup: player picker (from the Rackroom roster), Practice toggle, 4-corner table calibration (tap/confirm).
- Start tap unlocks audio (iOS) and requests Screen Wake Lock.
- Crops/downscales to table (~960×480) and sends JPEG frames over WSS: ~5 fps when still, 30 fps during shots (server signals motion start/stop).
- UI: live view with detected-ball overlays, scoreboard, whose turn, large override buttons.
- Overrides: undo last event, toggle ball pocketed/on table, force turn switch, declare foul.
- Auto-reconnect; resumes session.
- Speech via browser `speechSynthesis` through a priority queue (critical lines preempt; stale color lines dropped; never overlaps).

## Server
- Python FastAPI + OpenCV. Per-session in-memory state, retained 30 min after disconnect.
- Vision: homography to top-down using calibration corners; Hough circles + color/white-fraction classifier → cue, 8, solids, stripes (no individual numbers). YOLO only if classical proves flaky.
- Shot segmentation: shot starts when the cue ball moves after a still period (arm/cue motion ignored); ends when all balls still ~1 s. Rules evaluate the before/after diff plus trajectories.
- First contact inferred from the first object ball to start moving near the cue ball's path (30 fps during shots).
- Pocketed only if a ball vanishes within a pocket zone during a shot AND remains absent after settle (occlusion-safe).
- Ball-in-hand placement state: cue-ball-only movement = placement, not a shot.
- On reconnect after missed shots: diff table, ask user to confirm via override UI.

## Commentary
- Hybrid: instant template line per event; Claude color line on ~1 in 2 events plus an idle line after >20 s without a shot.
- Model: Claude Haiku 5.5 (`claude-haiku-5-5`) for live lines, streamed, 1–2 sentences, no facts beyond provided state. Optional Claude Sonnet 5.5 (`claude-sonnet-5-5`) post-game summary.
- Context: running game state (score, streaks, recent events) plus each player's leaderboard record (record, current and best streak, head-to-head, average balls potted), sent by Rackroom when it starts a table-camera game.
- Table camera: the stream server writes the lines; the Controller and Watch screens speak them with `speechSynthesis`.
- Persona: single calm, dry pro broadcaster with occasional wit; persona is one system prompt, setting left open for future personas.
- Practice games are announced as such once.

## Leaderboard
- Rackroom's SQLite roster, matches and `/` standings board. Players are picked from the Rackroom roster.
- On game end: announce winner, 10 s Confirm/Cancel countdown, then the result is recorded in Rackroom. "Undo result" available until the next game starts.
- Per-game **Practice** toggle: never records a result.
- Tests use a temp DB via `POOL_DB`.

## Hosting
- AWS ECS Fargate, single task (~1 vCPU / 2 GB), behind ALB with ACM cert (HTTPS + WSS); likely ap-southeast-2.
- Same server serves the PWA static files.
- Rackroom's SQLite must persist across deploys and task restarts (e.g. EFS volume via `POOL_DB`).
- Secrets Manager: Anthropic API key.
- IaC: CDK (TypeScript).

## Testing
- Main seam: a game session driven through the phone's WebSocket protocol with recorded frames; Rackroom on a temp DB, stubbed Claude, fake clock; assert emitted game events, commentary requests and Rackroom result writes. Follows Rackroom's existing unittest + FastAPI TestClient style.
- Rules engine: pure unit tests over synthetic shot diffs.
- Vision: record real games from the mounted phone (video + calibration corners), replay harness feeds frames through the pipeline, hand-labelled event JSON per clip for regression.

## Open items
- AWS details (account/VPC, domain, region confirmation) — user to provide.
