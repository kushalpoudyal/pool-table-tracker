# Hackathon: Pool Table Tracker

Shared team context for the hackathon (project 2). Everything related to it gets recorded here.
Decisions and progress go in `LOG.md` (append-only). The full build spec is `SPEC.md`.

## Brief (Kushal 19/11)

> A pool table tracker: a camera tracks the pool table and the 2 people playing, and gives them
> live feedback and announcements with a voice. For now use a webcam or phone camera, put up
> high over the table, taking in the footage of the people playing.

- **Camera:** Kushal's Samsung (Android) phone (19/11), with the laptop webcam as fallback.
- **Game:** plain 8-ball, 2 players (Kushal 19/11).

## Step 0: MVP first (Kushal 19/11)

Before the full spec: phone camera (and mic) connected → objects detected → detections
written out as text. The phone only captures; the laptop does all the processing.

1. **Phone (done, step 1):** no app on the phone. It's plugged in by **USB-C**, and
   `app/capture.py` streams the camera through scrcpy's server: 1080p at 60 fps on
   http://127.0.0.1:8000 (SPEC.md §2).
   - **Mic, later:** the same server streams the mic (`audio_source=mic`) on the phone's
     clock. Log audio "hit" lines too (`AUDIO.md`).
2. **Detector A (hour 1):** stock YOLO26n (COCO). It finds `person` well and `sports ball`
   weakly, which is enough to prove the camera → detect → log pipe. No account or training needed.
3. **Detector B (same day):** YOLO26n trained on Colab with the Roboflow "8-Ball Pool"
   dataset (`cue_ball`, `8_ball`, `solid_ball`, `stripes_ball`). Swap the weights file in;
   the code doesn't change.
4. **Output:** a live window with boxes and FPS, plus one line per detection snapshot
   appended to `detections.jsonl` and printed to the console.

Not in the MVP: calibration, tracking, rules, voice, FastAPI, OpenVINO, AWS.

## Research files

- `SPEC.md`: the full build spec.
- `AUDIO.md`: phone mic → ball-impact timing.
- `DETECTION.md`: calibration + ball / player / motion detection plan, with probe results on our table.
- `AWS.md`: what AWS can and can't do here. Short version: the laptop does vision, audio and
  rules; Bedrock + Polly are optional for commentary and voice; one EC2 GPU box is the fallback.

## Proposed stack (pending team agreement, see SPEC.md)

| Part | Proposal |
|---|---|
| Camera feed | Phone on a high stand, ultra-wide lens, USB-C to the laptop; scrcpy's server (no phone app). Built: `app/capture.py` |
| Ball detection | Ultralytics YOLO26n fine-tuned on Roboflow "8-Ball Pool" + our own frames, run with OpenVINO on the laptop's Intel iGPU, ByteTrack for IDs |
| Game logic | Python shot state machine (moving / still, before / after ball counts) + simplified 8-ball rules engine |
| Server + UI | One FastAPI app: MJPEG video stream + WebSocket events → one static HTML page |
| Voice | Stream server: instant template lines + Claude Haiku 5.5 colour, spoken with ElevenLabs Flash v2.5 and streamed to Rackroom (browser `speechSynthesis` as fallback); see the vision backend README, Commentator |

## Open questions

1. ~~Android or iPhone?~~ Samsung Android → IP Webcam (Kushal 19/11).
2. Table size (7 / 8 / 9 ft) and the room: ceiling height, lights, where a stand can go.
3. Same team as project 1 (Cody, Paul, Hessam)? Who takes which workstream (SPEC.md §6)?
4. Hackathon dates and judging criteria, which decide how much goes into stretch goals.
5. ~~House rules?~~ Plain 8-ball (Kushal 19/11).
6. Venue Wi-Fi: does it allow phone-to-laptop traffic, or do we use a hotspot / USB?
