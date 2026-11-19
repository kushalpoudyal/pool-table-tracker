# Pool Table Tracker: specification (draft, 19 Nov 2026)

One phone mounted above a pool table films the table and the 2 players and listens with its
microphone. The phone only captures. The laptop (or a server, see `AWS.md`) tracks the
balls, hears the impacts (`AUDIO.md`), works out what happened in each shot under 8-ball
rules, shows live feedback on screen and announces it out loud.

Status: research only, nothing built or tested. Claims marked *unverified* came from search
results or forums, not from a page we could open.

## 1. What the demo does

| Must have (MVP) | Stretch |
|---|---|
| Live video with ball boxes and trails, plus a top-down minimap | Shot-line prediction from the cue stick angle |
| Detects shot start / shot end, pots, scratches | Ball numbers (1-15), not just solid / stripe |
| 8-ball rules: open table, solids / stripes assigned, turn changes, ball in hand on a scratch, win / loss on the 8 | Telling the 2 players apart by shirt colour (person detection) |
| Scoreboard: player names, group, balls left, current turn | End-of-game highlight reel |
| Voice: instant announcements ("Stripe in the corner! Paul stays at the table") | Premium commentator voice (ElevenLabs) |
| Voice: short LLM colour commentary in the pauses | |
| Shot stats: cue ball speed (km/h), pots per turn, longest run | |
| Manual keys: undo, switch turn, mark a foul | |

Out of scope for the MVP: first-contact and no-rail fouls. At 30 fps a fast cue ball moves
about 2 ball widths per frame, so video alone can't catch them; players use the manual foul
key. Stretch: the mic times the first click to the millisecond, which can bring
first-contact back (`AUDIO.md`).

## 2. Hardware

| Item | Notes | Rough cost |
|---|---|---|
| Phone (the camera) | Kushal's phone for now. **Use the ultra-wide lens.** Keep it plugged in, because streaming drains the battery and heats the phone. | have |
| Laptop | Kushal's: Core Ultra 7 255H with Intel Arc 140T iGPU, so the model runs on the iGPU through OpenVINO | have |
| Overhead mount | Light stand + boom arm with sandbag: NEEWER ST-260AC 2.6 m stand ($69.99) + NEEWER boom arm ($59.99). Ceiling clamp alternative: iBOLT ceiling mount ($149.95) | ~$130 |
| Phone clamp for the mount | Any 1/4" tripod phone holder | ~$10 |
| USB cable / power bank | Power for the phone; USB is also the fallback when Wi-Fi blocks the stream | have |
| Speaker | Laptop speaker works; a Bluetooth speaker is better in a noisy room | optional |
| Big screen / TV | For the live scoreboard | optional |

### Camera placement

Playing surfaces: 7 ft = 0.99 x 1.98 m, 8 ft = 1.12 x 2.24 m (home), 9 ft = 1.27 x 2.54 m.
Ball = 57 mm. Table bed is about 0.75 m off the floor.

| Lens height above the table bed | 7 ft | 8 ft | 9 ft |
|---|---|---|---|
| Ultra-wide, table + rails only | 0.93 m | 1.01 m | 1.12 m |
| Ultra-wide, table + players around it (16:9) | ~1.9-2.1 m | ~1.9-2.1 m | ~2.1 m |
| Main lens, table only | 1.7-1.9 m | 1.9-2.0 m | 2.1-2.2 m (often above the ceiling) |

- The main lens has to sit too high for most rooms, so **use the ultra-wide**. Check that the
  camera app lets you pick it (unverified for every app).
- **Framing:** table plus about 0.5 m around it. A player is in frame while leaning in to
  shoot, which is when it matters. From overhead you mostly see heads, arms and cues.
- **Ball size:** about 40 px at 1080p with table-only framing, and about 20 px with players in
  frame. So **crop to the table before running the model**, and stream 1080p if the app allows it.
- **Lock exposure, focus and white balance** in the camera app. Auto exposure shifts colours
  every time someone leans over the table.

### Getting the phone feed into Python

**Decided (Kushal 19/11):** Samsung Galaxy Z Fold7 (Android 17), connected to the laptop by
**USB-C**. **No app on the phone.**

- **How:** `app/capture.py` pushes scrcpy 5.0.1's server over adb, starts it with
  `video_source=camera`, and decodes its H.264 stream with PyAV. It's a little under
  100 lines, following scrcpy's documented protocol.
- **Camera:** camera 0 at zoom 0.6 = ultra-wide, 1920×1080 at 60 fps.
  - Measured: 60 fps on the page, live about 3 s after start.
  - The phone also offers 120/240 fps high-speed capture at 1080p.
- **Recovery:** a killed camera server is back in 2.3 s. Before each start the app stops any
  leftover server, because only one app can hold the camera.
- **Microphone (later):** scrcpy's server also streams the mic (`audio_source=mic`, raw
  16-bit PCM, 48 kHz stereo). It carries timestamps from the same phone clock as the video,
  so it replaces the RTSP plan in `AUDIO.md`.
- **Dropped:** IP Webcam (ads, extra app). Android's built-in USB webcam mode isn't enabled
  on this phone (`ro.usb.uvc.enabled` unset).
- **Cable:** it must be a *data* cable. At 2 m up you need 3 m of cable or an extension.
- **Latency:** not measured yet. Film a stopwatch on the laptop screen to measure it.
- The same reader must accept a **video file**, so everyone can develop against recordings
  without the table.

## 3. Software pipeline

```
phone ──► capture thread (newest frame only)
            │
            ▼
       crop to table ──► YOLO26n (OpenVINO, iGPU) + ByteTrack ──► ball positions (px)
            │                                                        │ homography
            ▼                                                        ▼
     frame differencing ──► moving / still ──────────────────► table coords (mm)
                                                                     │
                                                    shot state machine + 8-ball rules
                                                                     │ events (JSON)
                         ┌───────────────────────────────────────────┤
                         ▼                                           ▼
             FastAPI /video (MJPEG + overlays)          FastAPI /ws (WebSocket)
                         │                                           │
                         └──────────► one browser page ◄─────────────┘
                                 video, minimap, scoreboard, feed,
                                 voice (speechSynthesis) + LLM colour lines
```

### 3.1 Calibration (once per setup)
- Click the 4 corners of the playing surface on a frame and save them to `calibration.json`,
  with the table size.
- Compute a homography from the clicked corners to a 2:1 rectangle in millimetres.
- Pockets need no clicks: 4 corners plus the 2 long-side midpoints, with a radius.

### 3.2 Ball detection and tracking
- **Model:** Ultralytics **YOLO26n**, the current release (Jan 2026). AGPL-3.0, which is fine
  for a public repo.
- **Training data:** Roboflow Universe [8-Ball Pool](https://universe.roboflow.com/james-hlfle/8-ball-pool-02a3e).
  - 3,133 overhead images, CC BY 4.0.
  - Classes: `cue_ball`, `8_ball`, `solid_ball`, `stripes_ball` (plus `red`, `yellow`, `table`).
  - Solid / stripe / cue / 8 is all the 8-ball rules need.
- **Fine-tune:** add 100-200 labelled frames from *our* table, filmed with our phone and our
  lighting. Label them in Roboflow Annotate, pre-labelled by the first model.
  - Train on free Google Colab (T4). Roboflow's tutorial did 654 images for 20 epochs in about
    9 minutes.
  - Universe model weights probably can't be downloaded (*unverified*), so we train our own.
- **Export to OpenVINO** for the Intel iGPU. Docs give YOLO26n at about 4 ms per 640 px frame
  on a Core Ultra iGPU. Our Arc 140T figure is *unverified*, so measure on day 1.
- **Inference:** run on the table crop at an image size close to the crop width (up to 1280),
  then map ball centres through the homography.
- **Tracking:** `model.track(persist=True, tracker="bytetrack.yaml")` gives IDs and trails.
- **Per-number balls (stretch):** [pool-ball-detection](https://universe.roboflow.com/kwinten-declercq-vsesb/pool-ball-detection-v8huq)
  has 2,585 images with classes 0-15, mAP50 85%.
- **Fallback if YOLO struggles:** a felt colour mask plus blobs (classical OpenCV). Teams report
  around 77% ball identity with it: it breaks on clusters and glare. Use it only for motion detection.

### 3.3 Shot state machine
1. **Still:** frame differencing on the table crop is below a threshold. Snapshot the ball
   counts per class and the cue ball position.
2. **Shot start:** the cue ball moves above a threshold for 2-3 frames. Record the shot speed
   from cue ball displacement in mm across the first frames (best-effort: a hard break blurs).
3. **Moving.** While balls move, a track lost inside a pocket zone is a *candidate* pot.
4. **Shot end:** everything still for about 0.7 s.
5. **Resolve:** compare ball counts per class before and after.
   - A drop in a class = a pot. Use the pocket from the candidate if there was one.
   - No cue ball = scratch.
   - The before/after count is the source of truth, because balls can rattle out of a pocket.
6. Pass the result to the rules engine.

### 3.4 8-ball rules engine (simplified WPA)
- **Start:** names for Player 1 and Player 2; Player 1 breaks. The table is open.
- **Groups:** the first legal pot after the break assigns solids or stripes to the shooter.
- **Turns:** the shooter stays on while legally potting their own group. Otherwise the turn passes.
- **Scratch or manual foul:** the turn passes and the next player has ball in hand.
- **8-ball potted:**
  - The shooter wins if their group is cleared and they didn't scratch.
  - Otherwise the shooter loses.
- **No called pocket**, as a house rule.
- **Manual keys** to undo the last shot, switch the turn and mark a foul, because the vision
  will sometimes be wrong.
- The rules engine is pure Python with no camera. Unit-test it with scripted shot results.

### 3.5 Events (the contract between modules)
Every module talks through one JSON event shape over the WebSocket:

```json
{"t": 12.4, "type": "pot", "player": "P1", "ball": "stripe", "pocket": "top-left", "speed_kmh": 14.2}
```

Types: `game_start`, `shot_start`, `shot_end`, `pot`, `scratch`, `groups_assigned`,
`turn_change`, `foul`, `game_over`, plus `state` (a full scoreboard snapshot after each
shot, so the page can redraw from it).

### 3.6 Voice and commentary
- **Instant lines:** templates per event ("Stripe down in the corner!", "Scratch! Ball in hand
  for Cody"), spoken by the browser's `speechSynthesis`.
  - Free and effectively zero latency.
  - Chrome only speaks after one click on the page, so add a Start button.
  - Tip: Edge exposes Microsoft's natural "Online" voices to `speechSynthesis` (*unverified*,
    so check on day 1).
- **Colour commentary:** after each `shot_end`, send the last few events and the scoreboard to
  OpenAI **`gpt-6-luna`** with reasoning effort `none`.
  - The team already has a key from project 1.
  - About 1.5 s to the first token; $0.10 / $0.50 per 1M tokens.
  - Ask for one sentence of 20 words or fewer.
  - Speak it only if no new shot has started and it arrived within about 3 s; otherwise drop it.
- **AWS alternative** (company account allowed, `AWS.md`):
  - Bedrock **Claude Haiku 5.5**, routed inside Australia, for the colour lines.
  - **Polly** for the voice: Australian voices Olivia, Russell and Curtis. Polly has no
    sports style.
  - Pick one provider before building.
- **Not used:**
  - `gpt-4o-mini-tts`: shuts down 6 Jan 2027 and has about 3.9 s P95 to first audio.
  - Realtime API: built for two-way voice and pricier.
  - `gpt-4o-mini`: shuts down 14 Jan 2027.
- **Stretch: ElevenLabs Flash v2.5** for a proper commentator voice.
  - About 185 ms median; the free tier is about 10 min a month and requires attribution.
  - Pre-generate the template lines once as clips, so a live call costs nothing.

### 3.7 UI
- **One FastAPI app.**
  - A background thread runs capture → detect → rules.
  - `/video` serves an MJPEG stream with overlays, shown in an `<img>`.
  - `/ws` pushes events.
  - One static HTML page shows the video, minimap, scoreboard, event feed and voice.
- **No front-end build step.** Move to React only if the page grows.
- **Pitfalls:**
  - Keep inference off the async event loop.
  - Each open MJPEG tab holds 1 of the browser's 6 connections to the server, so use one tab.
- **Not used:** Streamlit (reruns the script on every interaction) and Gradio (video chunks
  over 1 s add lag). `cv2.imshow` is fine for debugging only.

### 3.8 Audio hits (phone microphone)
- **What it's for:** the strike sound marks the exact shot start; clicks after it are
  collisions; a pocket sound plus a vanished ball confirms a pot.
- **How:** high-pass filter + short-frame energy against a moving average, with a 30 ms
  lockout after each hit. A hit only counts while the video says a shot is possible.
- **Details:** `AUDIO.md`.

### 3.9 Where it runs
- **Laptop:** vision, audio and rules. No managed AWS vision service can track pool balls
  live (`AWS.md`).
- **AWS fallback:** if the laptop is too slow, a g4dn.xlarge in Sydney (about $0.68/h, about
  $0.26 spot) runs the same code. The phone streams to it with Larix over SRT, through MediaMTX.

## 4. Accounts, keys and packages

- **Accounts:**
  - Roboflow (free): dataset download and labelling.
  - Google Colab (free): training.
  - OpenAI key: already have it; goes in `.env`.
  - ElevenLabs only for the stretch voice.
- **Python packages:** `ultralytics`, `openvino`, `opencv-python`, `av` (PyAV), `scipy`,
  `numpy`, `fastapi`, `uvicorn[standard]`, `python-dotenv`, `roboflow`, plus `openai` or
  `boto3` (AWS) for voice and commentary.
- **Laptop tools:** Android platform-tools (`adb`) for the USB link.
- **Python version:** the laptop has 3.13. Fall back to 3.12 if a wheel is missing.
- **Reuse ideas, not code:** most of the projects below have no licence.
  - [billiards-vision](https://github.com/joey15117983688-ops/billiards-vision): pot state machine and pocket calibration.
  - [Billiard_System](https://github.com/Eitiahwlwngu/Billiard_System): YOLO + ByteTrack + pocket-zone scoring.
  - [BilliardsOverlay](https://github.com/MatthewLarson/BilliardsOverlay): classical detection and cue-line projection.
  - [pooltool](https://github.com/ekiefl/pooltool): Apache-2.0 physics, for the shot-line stretch.

## 5. Proposed layout (not created yet)

```
app/
  main.py          FastAPI: /video, /ws, static page, keyboard overrides
  capture.py       newest-frame reader: IP Webcam URL, webcam index or video file
  calibrate.py     click 4 corners -> calibration.json
  detector.py      YOLO26n (OpenVINO) on the table crop + ByteTrack
  shots.py         moving / still state machine, before / after diff
  rules.py         8-ball rules engine (pure, unit-tested)
  commentary.py    template lines + gpt-6-luna colour lines
  static/index.html
training/          Colab notebook + data notes
recordings/        sample games (gitignored)
models/            trained weights (gitignored)
```

## 6. Build plan

**Do first: mount the phone and record 10-15 minutes of real play.** Those recordings unblock
everyone: they're the labelling data, the test input for the shot logic, and the demo backup.

| Workstream | Owner | Output | Works from |
|---|---|---|---|
| A. Camera + calibration | ? | `capture.py`, `calibrate.py`, mount and settings | the phone |
| B. Model | ? | dataset + our frames → Colab → OpenVINO weights, FPS measured | recordings |
| C. Shots + rules | ? | `shots.py`, `rules.py` + tests, emits events | recordings + scripted shots |
| D. UI + voice | ? | FastAPI, page, templates, LLM colour lines | fake event stream |

1. **Day 1 morning:** mount the phone and record. B starts labelling. C and D build against
   the event contract (§3.5) with fake data.
2. **Day 1 afternoon:** first model trained and exported. Calibration works. The page shows
   the live video and speaks fake events.
3. **Day 2 morning:** wire it end to end, tune thresholds on recordings, add manual override keys.
4. **Day 2 afternoon:** stretch goals, the demo script, and a recorded backup demo in case the
   venue Wi-Fi fails.

## 7. Risks

| Risk | Mitigation |
|---|---|
| Phone link drops | USB-C + `adb forward` (decided); Wi-Fi / hotspot as backup |
| Audio and video drift apart | One RTSP stream read by PyAV; offset calibrated from about 10 cue strikes |
| Room noise triggers false hits | High-pass above speech; accept hits only during a shot |
| Glare and auto exposure change ball colours | Lock exposure and white balance; angle the lights; fine-tune on our own frames |
| Balls too small with players in frame | Ultra-wide at 1080p, crop to the table, larger inference size |
| Clusters after the break confuse counts | Resolve on still frames only; before / after counts are the truth |
| Wrong call during the demo | Manual undo / switch / foul keys |
| Fast cue ball blurs out | Speed is best-effort; 60 fps if the app allows it |
| People filmed | Ask consent; recordings stay out of git (`.gitignore`) |
