#!/usr/bin/env python3
"""Run the whole pipeline headlessly and say which stage failed.

    python3 tools/smoke_run.py https://www.youtube.com/watch?v=XXXXXXXXXXX
    python3 tools/smoke_run.py <url> --no-cut        # stop after extraction
    python3 tools/smoke_run.py <url> --transcript t.txt   # skip the caption fetch
    python3 tools/smoke_run.py <url> --server http://localhost:8080

Same endpoints the browser uses, so a failure here is a backend failure and the
log line is the whole story — no devtools, no guessing which stage it was in.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

DEFAULT_SERVER = "http://localhost:8080"


def call(server: str, path: str, body: dict | None = None, timeout: int = 120) -> dict:
    url = server.rstrip("/") + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method="POST" if body is not None else "GET",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = {"detail": raw[:400]}
        raise SystemExit(f"\n  HTTP {exc.code} on {path}\n  {json.dumps(payload, indent=2)}")
    except urllib.error.URLError as exc:
        raise SystemExit(f"\n  Cannot reach {url} — is the server running? ({exc.reason})")


def wait(server: str, path: str, label: str, timeout: int = 480) -> dict:
    started = time.monotonic()
    last = ""
    while time.monotonic() - started < timeout:
        payload = call(server, path)
        stage = payload.get("stage") or payload.get("status") or ""
        progress = payload.get("progress", 0)
        line = f"  {progress:>3}%  {stage}"
        if line != last:
            print(line, flush=True)
            last = line
        if payload.get("status") in ("done", "error"):
            return payload
        time.sleep(1.5)
    raise SystemExit(f"\n  {label} timed out after {timeout}s")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    url = argv[1]
    server = DEFAULT_SERVER
    if "--server" in argv:
        server = argv[argv.index("--server") + 1]
    do_cut = "--no-cut" not in argv
    transcript_file = None
    if "--transcript" in argv:
        transcript_file = argv[argv.index("--transcript") + 1]

    print(f"server   {server}")
    tools = call(server, "/api/tools")
    print(f"tools    ffmpeg={tools.get('ffmpeg')} yt-dlp={tools.get('yt_dlp')} "
          f"can_cut={tools.get('can_cut')}")

    print("\n[1/4] captions")
    if transcript_file:
        from pathlib import Path
        text = Path(transcript_file).read_text(encoding="utf-8")
        info = {"title": f"(local {transcript_file})", "lines": len(text.splitlines()),
                "kind": "pasted"}
        print(f"  using {transcript_file} — {info['lines']} lines")
    else:
        info = call(server, "/api/transcript", {"url": url}, timeout=180)
        text = info.get("text") or ""
    print(f"  {info.get('title', '(no title)')}")
    print(f"  {info.get('lines', len(text.splitlines()))} caption lines, "
          f"{len(text)} chars, kind={info.get('kind', '?')}")
    if not text:
        raise SystemExit("  No transcript came back — that is the failure, right there.")

    print("\n[2/4] extraction")
    submitted = call(server, "/api/extract", {
        "youtube_url": url,
        "transcript_text": text,
        "niche": "auto",
        "audience": "U.S. English",
        "language": "U.S. English",
        "num_clips": 0,              # AUTO
        "window": "40-50",
        "model": "",
        "cascade": True,
    })
    job_id = submitted["job_id"]
    print(f"  job {job_id}")
    job = wait(server, f"/api/jobs/{job_id}", "extraction")
    if job["status"] == "error":
        print(f"\n  FAILED: {job['error']}\n  hint: {job.get('error_hint', '')}")
        print("\n  tail of the server log:")
        return 1

    results = call(server, f"/api/jobs/{job_id}/results")
    clips = results.get("clips") or []
    print(f"\n  {len(clips)} clip(s), {results.get('model', '?')}, "
          f"{results.get('elapsed_s', '?')}s")
    for clip in clips[:5]:
        print(f"    {clip.get('start_stamp', '?'):>8}  {clip.get('title', '')[:60]}")
    if not do_cut:
        return 0
    if not clips:
        raise SystemExit("  No clips to cut — extraction produced nothing.")

    print("\n[3/4] cutting at 1080p")
    cut = call(server, f"/api/jobs/{job_id}/cut", {"height": 1080})
    cut_id = cut["cut_id"]
    print(f"  cut {cut_id}")
    done = wait(server, f"/api/cuts/{cut_id}", "cut", timeout=900)
    if done["status"] == "error":
        print(f"\n  FAILED: {done['error']}\n  hint: {done.get('error_hint', '')}")
        print("\n  This is usually YouTube's bot-check. Fix: export cookies.txt, put it")
        print("  in the repo root, restart the server.")
        return 1

    print(f"\n[4/4] files ({done.get('quality', '?')})")
    for item in done.get("files") or []:
        print(f"  {item.get('path')}  {round(item.get('bytes', 0) / 1e6, 1)} MB")
    print(f"\n  ZIP: {server}/api/cuts/{cut_id}/zip")
    print("\n  everything green.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
