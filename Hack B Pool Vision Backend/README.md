# Pool Table Tracker: vision backend

The camera, detection and LLM side of the pool table tracker. A phone above the table streams over
USB to this laptop server, which tracks the balls and players and keeps the score with an LLM
(`gpt-6.2-sol`) looking at the game every few seconds. Rackroom (`../Hack B Pool API`,
`../Hack B Pool Client`) shows its feed and hands it the players' names; see **Rackroom** below.

All commands below run from this folder.

## Run it

No app on the phone. The laptop streams the camera over USB with
[scrcpy](https://github.com/Genymobile/scrcpy)'s server, which it pushes over adb and which
runs only while the phone is plugged in.

**Phone (Android 12+), once:**
1. Turn on Developer options: Settings → About phone → Software information → tap
   *Build number* 7 times.
2. Turn on Settings → Developer options → **USB debugging**.

**Laptop, once:**
```sh
winget install Google.PlatformTools       # adb
winget install Genymobile.scrcpy          # must be 5.0.1, see SCRCPY_VERSION in app/capture.py
# open a new terminal so both are on PATH
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

**Each session:**
1. Plug the phone in by USB-C. The first time, tap **Allow** on "Allow USB debugging?".
2. Start the server: `.venv\Scripts\python -m app.main`
3. Open http://127.0.0.1:8000. It shows "live" with the resolution and fps, and reconnects
   by itself after an unplug.

**Detection and tracking:**
- **Live boxes:** balls, cue sticks and people, tracked with IDs.
  - Balls: solid = yellow, stripe = orange, cue = white, 8 = purple, not yet named = teal.
  - People: player = green, spectator = grey.
- **Mark table:** click the 4 corners of the cloth.
  - Balls off the cloth (chalk on the rail) are then ignored.
  - The outline is saved to `calibration.json` (`calibration-sandbox.json` for the sandbox).
- **Players:** up to 2 people who hold a cue or touch the table outline. Everyone else is a spectator.
- **Identify balls:** press it at the rack, ready to break.
  - The LLM names every ball (cue / 8 / solid / stripe + number) from crops, in one call of about 2 s (`gpt-6-luna`; `OPENAI_NAMING_MODEL` to change).
  - The names then follow each ball's track.
  - A ball that loses its track (a hard break) is re-named the next time the table is still.
- **Capture 5 s:** records 5 s to `recordings/` and asks the LLM what happened (summary,
  events, players, pots, what the detector missed). The answer shows in the side panel.
- **Log:** one line a second to `logs/detections-<live|sandbox>.jsonl`.
- **LLM:** needs `OPENAI_API_KEY` in `.env`; `OPENAI_MODEL` (default `gpt-6.2-sol`) and `OPENAI_REASONING` (default `low`) are optional.
- **First run without `models/`:** the detector (YOLOE) downloads and exports itself to
  OpenVINO, which takes a minute or two.

**The observer (LLM, `app/observer.py`) keeps the score:**
- **Every second** it keeps a photo; **every 5 s** it stitches the 5 photos, in order, into one image
  (a 3 x 2 grid of numbered, timestamped tiles, cropped to the table if it's marked).
- **It asks the LLM** what happened, together with what it remembers of the game:
  - who is who (it learns the players by their clothes);
  - groups, balls potted, balls still on the table;
  - its last few looks.
  The house rules and ball colours come from [`rules/8ball.md`](rules/8ball.md).
- **The LLM reports:** balls pocketed (which, which pocket, by whom), who is at the table, groups,
  a winner, and one sentence on what happened.
- **Overlap:** each look starts with the previous look's last photo, so a ball that drops between two
  looks is still seen there and gone in the same image.
- **The app keeps the score:** a pocketed ball counts once, and a potted cue ball is noted as a
  scratch. A later look that clearly sees a "potted" ball back on the table takes it off the score
  (shown as a correction). A ball hidden by an arm or the photo's edge doesn't count as potted.
- **Speed and cost:** one look every 5 s, read in ~3.5-5 s (`gpt-6.2-sol`), so it keeps up; about
  $0.004 a look.
- **Game panel:** player names and **New game** (the first name breaks), a score table, and the
  feed of looks.
- **Saved:** each look's image and answer go to `recordings/<live|sandbox>-looks/`, and the game
  log to `logs/game-<live|sandbox>.jsonl`.
- **Speed:** looks also go as soon as the balls stop after a shot. The answer is streamed with
  "who's at the table" first, so the player shows ~1.3 s after a look is sent; pots come with the
  full answer (~3.5 s).
- **Live camera:** looks only run between **New game** and **End game**. The sandbox starts on its own.
- **Recognising players:**
  - Put labelled photos in `assets/players/` (git-ignored: real faces and names, public repo).
  - `app/players.py` cuts each labelled person out into one roster sheet, cached until the photos change.
  - Press New game with the names empty, and the first looks carry the sheet until two players are
    named, with today's clothes.
  - Someone not on the sheet is "Guest" (provisional for 6 looks, renamed if recognised). Typed names skip this.
  - **Same-day photos work best:** from above, clothes are the main clue; old photos only give faces.
- `app/referee.py` (the earlier shot-by-shot referee) is no longer used.

**Sandbox (test without the table):**
1. Open http://127.0.0.1:8000/sandbox and upload a phone video of a game from the start.
   H.264 and HEVC both work.
2. It plays at its own speed through the same pipeline.
3. Mark the table, press Identify balls at the rack, and use Capture 5 s.
4. **Restart video** replays it with fresh tracks.

The camera is back camera 0 at 0.6× zoom (ultra-wide), 1920×1080 at 60 fps. To change it,
edit `CAMERA` in `app/capture.py`. To use the laptop webcam instead, set `CAMERA_SOURCE=0`.

**Open the page from another computer:**
1. Start the server with `HOST=0.0.0.0` (PowerShell: `$env:HOST="0.0.0.0"` first).
2. Allow port 8000 through Windows Firewall, once, in an admin PowerShell:
   `New-NetFirewallRule -DisplayName "Pool Table Tracker" -Direction Inbound -Protocol TCP -LocalPort 8000 -RemoteAddress LocalSubnet -Action Allow`
3. Open `http://<laptop-ip>:8000` from the other computer.

There's no login, so anyone on the same network can watch the camera.

## Commentator

`app/commentator.py` (with the fixed wording in `app/calls.py` and the voice in `app/voice.py`) hears
every look the observer applies and turns it into lines to be heard on Rackroom's Controller and Watch
screens.

- **Instant lines**, fixed wording, ready the moment a look is applied: the break ("New game. Ada to
  break against Sam."), a pot ("Ada pots the 5 in the top right."), a scratch, a foul with the
  observer's reason, groups taken, a turn change ("Sam to shoot."), a correction ("Correction. The 5 is
  still on the table, not potted."), a recognised player, the winner ("Game over. Ada wins."). One
  line per look. Critical: winner, foul, scratch, correction. Normal: the rest.
- **Colour lines** from Claude Haiku 5.5 (`claude-haiku-5-5`, streamed, thinking off, low effort) as a
  calm, dry broadcaster: on the 1st, 3rd, 5th ... look that holds play (never on the look that decides
  the winner), and once per quiet spell 20 s after the last event. One request in flight; an answer is
  dropped if the game moved on, a critical line went out, it took over 5 s, or it is empty. It is told
  the running game, in-game stats (pots, fouls, scratches, the current run, time since the last pot)
  and the players' records Rackroom sends with `POST /game`, and states nothing beyond them.
- **Audio:** each line is made into speech here with ElevenLabs Flash v2.5 as soon as it is said and
  streamed at `GET /commentary/{id}/audio` (MP3). Fixed wording that repeats is made once. Without a
  voice key, or when a clip fails, the browser speaks the line's text with `speechSynthesis`.
- **Logged** with the looks in `logs/game-<live|sandbox>.jsonl` (`"line": {...}` records).
- **Cost:** instant lines nothing; colour about 1k input + 30 output tokens a request on Haiku 5.5
  ($0.10 / $0.50 per 1M); voice about 2,500 characters a game on Flash v2.5.

Settings (`.env`, all optional; keys stay on the server):

| Setting | |
|---|---|
| `ANTHROPIC_API_KEY` | colour lines; without it, instant lines only |
| `ELEVENLABS_API_KEY` | server-made speech; without it, browsers speak the text |
| `ELEVENLABS_VOICE_ID` | the voice (default: ElevenLabs' example voice `JBFqnCBsd6RMkjVDRZzb`) |
| `COMMENTARY=0` | no lines at all (a silent demo) |

`python -m app.commentator` asks Claude for one real colour line and prints it with the wait.

Tests (no camera, model download or network): `.venv\Scripts\python -m unittest` from this folder.
They drive the observer with a stub camera, scripted look answers, a fake writer, voice and clock.

## Context

Research, decisions and open questions live in [`../context/`](../context/CONTEXT.md); log decisions
in [`../context/LOG.md`](../context/LOG.md). The team's agreed product spec is [`../docs/SPEC.md`](../docs/SPEC.md).

## Rackroom

Rackroom reaches the live camera through plain routes (the same as `/live/...`):

| Route | What it does |
|---|---|
| `GET /status` | camera status: `connected`, `source`, `width`, `height`, `fps` (Rackroom's `POOL_STREAM_SERVER` contract) |
| `GET /video` | the live MJPEG feed with the detection overlay |
| `POST /game` | start a game: `{"players": ["<breaker>", "<other>"], "match": <Rackroom match id>, "report": {"url", "token"}, "stats": {...}}`; names in break order. `stats` (optional): each player's `played`, `won`, `streak` (`{"type": "W"\|"L", "n"}`), `best_streak`, `avg_potted`, `last_played`, plus `head_to_head` (`played`, `wins` by name), for the commentator. Recognition from photos is skipped, and the photos only map the names to faces. `report`: where to send the final score once the game is decided |
| `GET /watch` | the score for a Watch screen: `players` (name, group, potted, left, at_table), `winner`, `match`, `events` (latest moments, newest first), `lines` (the commentator's latest 20, oldest first: `{id, text, priority, game, audio}`; see **Commentator**). Rackroom's API forwards it as `/api/stream-server/game` and the Watch tab shows it under the table camera |
| `GET /commentary/{id}/audio` | one line's speech, MP3, streamed as it is made; 404 without a voice key (the browser speaks the text). Rackroom proxies it as `/api/stream-server/commentary/{id}/audio` |
| `GET /game` | everything: `memory` (players, groups, potted balls with who potted them, who is at the table, winner, match id), `score`, and the feed of looks |
| `POST /game/end` | stop looking (the live camera costs an LLM look every few seconds while a game is on); returns the final score: the `/watch` fields with every moment of the game |

How Rackroom uses them: its Controller (`/play`), when `POOL_STREAM_SERVER` is set, starts a game with
`POST /api/stream-server/game {"a": <player id>, "b": <player id>}`. That makes a Rackroom match and sends
the two names here (`POST /game`). It shows `/video` and the score while the game is on. Stop calls
`POST /api/stream-server/game/{id}/end`: Rackroom calls `POST /game/end` and records the final score it returns.
The end-game trigger needs no Stop: when two looks in a row name the winner, this server stops looking and sends
the final score to the `report` URL (`POST /api/stream-server/game/{id}/result`, with the match's
`X-Recorder-Key`), and the Controller shows the result. Either way our `winner` (matched to a player by name)
becomes the match winner and counts on the leaderboard; no winner means the match is `interrupted` and not
counted. The final score is kept with the match (`details` in `/api/board`) and shown in Match history.

Rackroom's API also defaults to port 8000: on a shared machine start this one with `PORT=8100`
(PowerShell: `$env:PORT="8100"`) and set `POOL_STREAM_SERVER` to match.

## Status

Built: phone camera page with live detection + tracking of balls, cues, players and spectators; rule-enforced ball names; LLM observer keeping the score from 5-second stitched looks; 5 s LLM capture; video sandbox (`app/`). Live voice commentator: instant lines, Claude colour and ElevenLabs audio streamed to Rackroom (see **Commentator**).
