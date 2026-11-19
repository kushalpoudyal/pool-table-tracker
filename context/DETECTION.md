# Calibration, detection and motion (proposal + probes, 19 Nov 2026)

Scope (Kushal 19/11): before any game rules, recognise the **players, the balls and their
movement**, and **calibrate the camera to the table** so a different table or a moved
camera still works. The custom 8-ball rules come later.

## Our table (from Kushal's photo)

- **Black cloth**, light-oak frame, stainless pocket rings, X-legs.
- Measure the playing surface (cushion to cushion) before calibrating.
- **Black cloth is harder than green:**
  - The 8-ball and the dark blue / maroon / green balls have low contrast.
  - Players in black shirts look like the cloth.
- Bright windows give a light gradient across the cloth and glare on the balls.
- Cue sticks and chalk get left lying on the table.

## Probes on that photo (laptop CPU, PyTorch, no OpenVINO yet)

The photo has 7 balls and no 8-ball.

| Model | Balls found | Other | Speed (1280 px) |
|---|---|---|---|
| Stock **YOLO26n** (COCO, "sports ball") | 4 of 7 (missed the 3 far ones) | People 7; cue stick called a "skateboard" | 73 ms (39 ms at 640) |
| **YOLO26n-pose** | – | 6 people with skeletons (4 at conf ≥ 0.83) | – |
| **YOLOE-26s** open-vocabulary, text prompt "billiard ball" | **7 of 7**, including both dark blues | Both cue sticks; 10 people; 1 false ball (chalk cube on the rail, conf 0.11) | 266 ms |

- **Auto table finding by cloth colour:**
  - A loose threshold got the 2 near corners right, but the far side leaked into dark shirts and frames.
  - A tight threshold was split up by the cue sticks on the cloth and the window light.
  - Verdict: auto-suggest only. A person confirms or clicks the 4 corners.

### Second table (Kushal's photo 2, 19/11)
Grey cloth, the same timber frame and steel pocket rings, shot from high up at an angle. It
has a full rack (15 balls including the 8) plus the cue ball.

- **Auto cloth corners:** failed again. Only part of the cloth was found, because window light
  shades it unevenly. Auto-finding failed on both tables, so calibration = **click the 4
  corners**.
  - A possible auto-suggest: the 6 pocket holes, which are dark round holes in steel rings
    on both tables.
- **YOLOE zero-shot on the tight rack:**
  - 4 of 16 balls at 1280 px; 8 of 16 at 1920 px (5 of them at conf ≥ 0.3).
  - The cue ball was found.
  - Verdict: zero-shot is fine for spread-out balls (7/7 on table 1) but weak on clusters.
    **Fine-tuning on pool data (step 5) is needed, not optional.**
  - At the break we can assume 15 + cue racked.

## Proposed approach

### Camera position
- **High at one short end, tilted down** (like the photo, but about 2.2-2.5 m up), so the
  whole table and the players are in frame.
- Straight overhead would be easier for the balls, but shows only heads. The homography
  handles the angle for the balls.

### Calibration (per table / per camera move)
1. **Calibrate button** on the page. It takes the median of about 2 s of frames, so anyone
   walking past disappears.
2. **Corners:** auto-suggest the 4 corners of the playing surface, and the user drags them to
   fit (about 10 s).
3. The user taps the **head (break) end**, which fixes orientation if sides swap, and picks
   the **table size**.
4. Compute and save to `calibration.json`:
   - the homography to a top-down 2:1 table in mm;
   - the 6 pocket zones (4 corners + 2 long-rail midpoints);
   - the ball radius in px;
   - a "player zone" (the table plus about 1 m around it).
5. **Camera moved?** Match ORB features on the wooden rails against the calibration frame
   every few seconds. Correct small shifts automatically; ask for a recalibration after a big one.
6. **Lens distortion:** check that straight rails look straight on the ultra-wide. If they
   bend, do a one-time checkerboard calibration for the phone.

### Objects
- **Balls:**
  - Start with YOLOE "billiard ball" (works zero-shot, about 4 fps on CPU).
  - Keep only detections inside the calibrated cloth. That drops the chalk and anything off-table.
  - Identity from colour inside each ball: white = cue, black = 8, hue = number,
    lots of white = stripe.
  - Then use YOLOE to **auto-label** recorded frames of our table, and fine-tune the fast
    YOLO26n (about 39 ms on CPU, faster with OpenVINO on the Arc iGPU, not measured).
- **Players:**
  - YOLO26n-pose.
  - Player = a person inside the player zone; spectators outside it are ignored.
  - Tracked by ID. P1/P2 are registered at game start by appearance (shirt colour).
  - Shooter = the player whose wrist is near the cue ball when the shot starts.
- **Cue sticks:** YOLOE "cue stick". Ignore cues lying on the cloth; a held cue gives the
  aiming line later.
- **Pockets:** come from calibration, no detection needed.

### Motion
- Ball tracks (ByteTrack) are mapped into table mm, giving position, speed, direction and trails.
- **Table state:** moving or still.
- **Shot start:** a spike in cue ball speed.
- **Shot end:** everything still for 0.7 s.
- **Pot:** a track ends inside a pocket zone, confirmed by the ball count.
- **Players:** at the table / leaning in / away.
- **Audio, later:** the cue-strike click gives the exact shot start.

### Build order (each step visible on the page)
1. Calibration: 4-corner editor, head end and size, top-down minimap.
2. Balls: boxes on the video plus dots on the minimap, with an event log.
3. Players: skeletons, player-zone filter, P1/P2.
4. Motion: trails, speed, moving / still, shot start / end, pots.
5. Record clips → auto-label → fine-tune the fast model → 30+ fps.

## Open questions
- Playing-surface size of this table (or its model)?
- Camera position: high at a short end (proposed) or straight overhead?
- A test photo with the **8-ball on the cloth**, to check black-on-black detection.
- Players by name (P1/P2) now, or "people at the table" for the first cut?
