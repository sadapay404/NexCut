# How cutting works

Two external programs, both optional until you press **Cut clips**.

## Mechanism

```
YouTube URL ──► yt-dlp -J            list formats, keep height >= 1080
            ──► yt-dlp -f "…"       download video stream + audio stream, merge to MP4
                                    cached as data/source/<video_id>_<height>.mp4
            ──► ffmpeg -ss <in> -i src -t <dur> -c:v libx264 -c:a aac
                                    one standalone MP4 per clip
            ──► data/cuts/<cut_id>/clip-01_00-00-08_00-01-03.mp4
```

- **One download per (video, height).** Clips after the first are cut from the
  local file, so a second run on the same video skips the slow part entirely.
- **Re-encoded, not stream-copied.** `-c copy` snaps to keyframes, which would
  turn a 8.0 s start into 7.4 s or 8.6 s. The product claims exact timestamps,
  so each clip is re-encoded (libx264, CRF 20, AAC 128k, faststart).
- **Nothing below 1080p is offered.** If the probe fails, 1080 is the fallback
  rather than a hard error, matching the standing quality rule.
- **Files are pruned after 3 days** and the source cache lives under `data/`,
  which git ignores.

## Requirements

| Tool | Windows | macOS | Linux |
|---|---|---|---|
| ffmpeg + ffprobe | `winget install Gyan.FFmpeg` | `brew install ffmpeg` | `apt install ffmpeg` |
| yt-dlp | `pip install yt-dlp` | `pip install yt-dlp` | `pip install yt-dlp` |

The top bar shows `cutting ready` or `cutting unavailable`, and
`GET /api/tools` returns the same state with per-tool install hints. Extraction
works fully without either — only cutting needs them.

## API

```
GET  /api/tools                       tool availability + hints
GET  /api/video-quality/{video_id}    {"qualities":[2160,1440,1080]}
POST /api/jobs/{job_id}/cut           {"height":1440} -> {"cut_id": "..."}
GET  /api/cuts/{cut_id}               {status, progress, stage, quality, files[]}
GET  /api/cuts/{cut_id}/file/{name}   the MP4
```

## Failure messages are the interface

| Situation | Message |
|---|---|
| yt-dlp absent | "yt-dlp is not installed, so nothing can be downloaded." + install hint |
| ffmpeg absent | "ffmpeg is not installed, so clips cannot be cut." + install hint |
| YouTube bot-check | "That badge… sign-in required — its bot-check is blocking this network." |
| Pasted transcript, no video | "That session came from a pasted transcript, so there is no video to cut." |
| No usable spans | "No clip in this session has a usable time range." |

## Note on the timestamp bug this phase found

`OracleResult.to_dict()` serialised `end_stamp` but not `end_sec`, so every
results payload had `end_sec: null`. Extraction looked fine; cutting could never
have worked. Caught by the end-to-end cut test, fixed, and pinned by two
regression tests.
