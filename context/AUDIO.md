# Audio: hearing ball impacts with the phone mic (research 19 Nov 2026)

The phone's microphone gives precise timing that 30 fps video can't. A fast cue ball moves
about 2 ball widths per frame, but a click is timed to the millisecond. Video says *which
ball and where*; audio says *exactly when*. Claims marked *unverified* or *inference* weren't
confirmed on an opened page.

> **Update 19/11:** the camera now comes through scrcpy's server, not IP Webcam (SPEC.md §2). Its mic stream (`audio_source=mic`, raw 16-bit PCM, 48 kHz stereo) carries timestamps from the same phone clock as the video, which replaces the RTSP route below.

## Getting audio and video on one timeline (original IP Webcam plan)

- **Use IP Webcam's RTSP stream:** `rtsp://<ip>:8080/h264_pcm.sdp`, with "ONVIF/RTSP" turned
  on in the app. It carries H.264 video plus PCM audio at 44.1 kHz.
- **Avoid:**
  - `h264_ulaw.sdp`: 8 kHz audio cuts everything above 4 kHz, which is where the clicks are.
  - The separate HTTP streams (`/audio.wav` next to `/video`): no shared timestamps, and they
    drift apart.
- **Over USB:** `adb forward tcp:8080 tcp:8080`, then `rtsp://127.0.0.1:8080/h264_pcm.sdp`.
  RTSP must use **TCP** transport, because adb forwards TCP only.
- **Read it in Python with PyAV:**
  - Open with `av.open(url, options={"rtsp_transport": "tcp", "fflags": "nobuffer"})`.
  - Use `container.demux(video, audio)`, and timestamp everything with `frame.time`.
  - OpenCV can't read audio.
- **Calibrate a fixed audio/video offset:** take the median, over about 10 shots, of (strike
  time in audio − first video frame where the cue ball moves). Re-check it now and then; RTSP
  offsets of 0.8-1.2 s have been reported through relays.
- **Fallback app:** Larix Broadcaster in SRT Listen mode (AAC/Opus audio, about 250 ms extra buffer).

## What the impacts sound like

| Event | Contact time | Sound |
|---|---|---|
| Ball on ball | 0.1-0.6 ms | Sharpest, brightest click |
| Cue tip on ball | 0.8-3 ms | Duller click |
| Cushion | rubber, longer | Lower thump (*inference*) |
| Pocket drop | hundreds of ms | Thud plus rattle (*inference*) |

- No billiards-specific detector or pretrained class exists. YAMNet and PANNs have no
  billiards label, and their 0.96 s windows are far too coarse anyway.
- **Closest prior art:** a table-tennis paper. It used a high-pass filter and energy peaks
  against a moving average, got ≤0.2 ms timing error, and a small CNN separated hit types at
  0.97 precision.

## Detection recipe (hackathon)

1. High-pass at about 2-4 kHz (scipy), tuned on our recordings.
2. Energy in 1-2 ms frames, compared with a moving average × k. Relative, not absolute,
   because the phone's automatic gain control is probably on.
3. Ignore new hits for 30 ms after each one.
4. Telling hit types apart: start with the event sequence, not a classifier.
   - The first hit after a still table = cue strike.
   - Later clicks = collisions.
   - A long, low sound near a pocket, with a ball vanishing in video, = a pot.
5. Only accept hits while the video shows a shot is possible. That filters out claps,
   drums and talking (speech sits mostly below 4 kHz).
6. Latency is about 6 ms of processing plus the stream delay.

## How it plugs into the game

- **Shot start:** the cue strike sound gives the exact shot start.
- **First contact:** the first click after the strike. Interpolate the cue ball's path to
  that moment and pick the nearest ball. That brings back the first-contact foul as a stretch goal.
- **Pots:** a pocket sound plus a ball vanishing near that pocket confirms the pot.

## Sources

- https://c3voc.de/wiki/howto:android-camera-obs
- https://github.com/AlexxIT/go2rtc/issues/291
- https://community.home-assistant.io/t/add-audio-support-to-android-ip-webcam-integration/489339
- https://ip-webcam.appspot.com/cheats.html
- https://softvelum.com/larix/android/
- https://pyav.basswood.io/docs/stable/api/container.html
- https://github.com/bluenviron/mediamtx/issues/6300
- https://drdavepoolinfo.com/faq/ball/contact-time/
- https://drdavepoolinfo.com/faq/cue-tip/contact-time/
- https://arxiv.org/html/2409.11760v1
- https://aubio.org/manpages/latest/aubioonset.1.html
- https://developer.android.com/reference/android/media/MediaRecorder.AudioSource
