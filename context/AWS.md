# AWS options (research 19 Nov 2026)

The team may use the company AWS work account (Kushal 19/11). Prices are for
ap-southeast-2 (Sydney) unless noted. Claims marked *unverified* come from pages we couldn't open.

**Why Sydney:** a probe from Kushal's laptop measured about 190 ms round trip to us-west-2 (the
company's usual region) and about 27 ms to Sydney. Anything live should run in Sydney, if the
account's policies allow that region (to check after `aws sso login`).

## Verdict

- **No managed AWS vision service can track pool balls live.** Run the vision, audio and rules on the laptop.
- AWS is worth using for **commentary (Bedrock)** and **voice (Polly)**.
- Keep **one EC2 GPU box** as the fallback if the laptop can't keep up.

## 1. Getting the phone stream into AWS

| Option | Verdict |
|---|---|
| Kinesis Video Streams (KVS) | Available in Sydney, but the Python consumers lag 1-3 s (GetMedia, *unverified*) or 3-5 s (HLS). GetImages tops out at 5 fps. WebRTC ingestion caps sessions at 1 hour and needs a custom viewer. **Skip.** |
| Amazon IVS | Not offered in Sydney (nearest is Tokyo); real-time publish caps at 720p. **Skip.** |
| Larix Broadcaster (phone) → SRT → MediaMTX on EC2 | Simplest way to get the stream to a server, about 0.3-1 s (*unverified*). Larix's SRT/RTMP/RTSP output is free. **Use only for the cloud fallback.** |
| Phone → USB → laptop (IP Webcam + `adb forward`) | Lowest latency, no internet needed. **Default.** |

## 2. Managed vision: not usable

- **Rekognition streaming video:** closed to new customers since 30 Apr 2026. It only ever
  did faces and person/pet/package, never custom objects.
- **Rekognition DetectLabels:**
  - Generic labels only ("Ball"), with no ball identity.
  - $0.0013 per image, a few hundred ms per call. At 5 fps for 16 h that's about $374.
- **Rekognition Custom Labels:**
  - Still available, at $4 per inference hour.
  - It's a per-image API, so it can't keep up with 30 fps.
- **Shut down:** Lookout for Vision (Oct 2025), DeepLens (Jan 2024), Panorama (May 2026).

## 3. Hosting our own YOLO (fallback)

| Instance | GPU | On-demand $/h | Spot $/h (may be stale) |
|---|---|---|---|
| g4dn.xlarge | T4 | 0.684 | ~0.26 |
| g6.xlarge | L4 | 1.046 | not listed |
| g5.xlarge | A10G | 1.308 | ~0.58 |

- **Speed:** YOLO26n runs in about 1.7 ms per frame on a T4 with TensorRT, so 30 fps is easy.
  Video decoding and the network are the limit, not the GPU.
- **SageMaker real-time endpoints:** each frame becomes an HTTPS call, and they cost more than a
  plain EC2 box. **Skip.** SageMaker training needs a custom container; Colab is less effort.
- **GPU quota:** the account may have zero quota for G instances. Check the quota "Running
  On-Demand G and VT instances" early (*unverified*).

## 4. Voice and commentary

### Amazon Bedrock
- **Commentary model: Claude Haiku 5.5.**
  - Released 7 Oct 2026. Australia-only routing via the `au.` inference profile (global ID
    `global.anthropic.claude-haiku-5-5`).
  - About $0.11 / $0.55 per 1M tokens (AU routing). Supports images. Set effort low for speed.
  - No latency figures are published.
- **Faster fallback:** Nova Micro ($0.037 / $0.148). One benchmark measured about 0.4 s to the
  first token, against about 1.55 s for Haiku 4.5 (us-west-2).
- **Referee check (stretch):** send one still frame to Haiku 5.5 after each shot ("which balls
  are left?"). About 1,200 image tokens, so about $0.00013 per check and about 1-2 s (*unverified*).

### Amazon Polly
- **Price per 1M characters:** Standard $4, Neural $16, Generative $30.
- **Australian voices:** neural Olivia; generative Olivia, Russell and Curtis. Generative
  supports bidirectional streaming.
- **No sports or excited style.** The only style, Newscaster, is on US/UK voices only.
- **Use:** neural Olivia for the fastest instant calls (*unverified* that it's fastest; no
  published time-to-first-byte). Generative for colour lines.
- **Alternative to Polly:** the browser's free `speechSynthesis`, with Polly as the upgrade.

## 5. Audio

- Amazon Transcribe is speech-to-text only.
- No AWS service detects impact sounds. Ball-click detection is our own signal processing on
  the laptop (see `AUDIO.md`).

## 6. Cost for about 16 hours of use

| Setup | Cost |
|---|---|
| Laptop does vision, audio and rules; Bedrock + Polly do commentary and voice (~400 shots) | **under $3** |
| Full cloud: g4dn.xlarge on-demand + MediaMTX + data | about $15-25 (on-demand); about $4 for the instance on spot |

## Sources

- https://aws.amazon.com/kinesis/video-streams/pricing/
- https://docs.aws.amazon.com/kinesisvideostreams-webrtc-dg/latest/devguide/webrtc-ingestion.html
- https://docs.aws.amazon.com/kinesisvideostreams/latest/dg/API_reader_GetImages.html
- https://docs.aws.amazon.com/general/latest/gr/ivs.html
- https://softvelum.com/larix/android/
- https://github.com/bluenviron/mediamtx
- https://docs.aws.amazon.com/rekognition/latest/dg/rekognition-availability-changes.html
- https://aws.amazon.com/rekognition/pricing/
- https://docs.aws.amazon.com/general/latest/gr/full_shutdown_services.html
- https://docs.ultralytics.com/models/yolo26/
- https://aws.amazon.com/polly/pricing/
- https://docs.aws.amazon.com/polly/latest/dg/available-voices.html
- https://docs.aws.amazon.com/polly/latest/dg/generative-voices.html
- https://aws.amazon.com/blogs/machine-learning/introducing-claude-haiku-5-5-on-aws/
- https://builder.aws.com/content/3Bo5naX7p1ncmB4FOoy3dJ4SD5M/benchmarking-amazon-bedrock-llm-latency-a-multi-model-comparison
