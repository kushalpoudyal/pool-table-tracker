# Pool Table Tracker

Hackathon project: a phone above a pool table watches an 8-ball game. The app tracks the balls and
players, keeps the score and gives live feedback.

| Folder | What it is |
|---|---|
| [`Hack B Pool API/`](Hack%20B%20Pool%20API/README.md) | Rackroom: FastAPI + SQLite. Players, matches, leaderboard, phone controller and Watch tab. |
| [`Hack B Pool Client/`](Hack%20B%20Pool%20Client/README.md) | Rackroom's React client: scoreboard, `/play` controller, `/watch`, leaderboard. |
| [`Hack B Pool Vision Backend/`](Hack%20B%20Pool%20Vision%20Backend/README.md) | Camera, detection and LLM scoring: the phone over USB to the laptop, YOLOE ball and player tracking, and an LLM that keeps the score. It's Rackroom's external camera server (`POOL_STREAM_SERVER`). |

`compose.yaml` runs Rackroom (API + client) locally; the vision backend runs on the laptop the phone
is plugged into (see its README).

- **Decisions and research:** [`context/`](context/CONTEXT.md), with an append-only [`context/LOG.md`](context/LOG.md).
- **The team's agreed product spec:** [`docs/SPEC.md`](docs/SPEC.md).
