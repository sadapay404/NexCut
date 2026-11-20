#!/usr/bin/env python3
"""Ask Google directly whether the key in .env works — none of app code in the path.

    python3 tools/check_key.py                 # uses .env + gemini-2.5-flash
    python3 tools/check_key.py gemini-2.0-flash # another model id

Prints the HTTP status and the response body, so a failure is Google's own words.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def read_env(path: Path = ROOT / ".env") -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        values[name.strip()] = value.strip().strip('"').strip("'")
    return values


def main(argv: list[str]) -> int:
    env = read_env()
    key = (env.get("NEXCUT_API_KEY") or os.environ.get("NEXCUT_API_KEY", "")).strip()
    model = argv[1] if len(argv) > 1 else (
        (env.get("NEXCUT_MODELS") or os.environ.get("NEXCUT_MODELS", "")).split(",")[0].strip()
        or "gemini-2.5-flash"
    )

    if not key:
        print("No NEXCUT_API_KEY in .env or the environment.")
        return 2
    print(f"key  {key[:6]}…{key[-4:]}  ({len(key)} chars)")
    print(f"model {model}")

    body = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": "Reply with the single word READY."}]}],
        "generationConfig": {"maxOutputTokens": 16, "temperature": 0},
    }).encode()
    req = urllib.request.Request(
        ENDPOINT.format(model=model), data=body, method="POST",
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            payload = json.loads(r.read().decode() or "{}")
            text = "".join(
                p.get("text", "") for p in
                payload["candidates"][0]["content"]["parts"]
            ).strip()
            print(f"\nHTTP {r.status}  OK")
            print(f"reply: {text or '(empty)'}")
            return 0
    except urllib.error.HTTPError as exc:
        print(f"\nHTTP {exc.code}  FAILED")
        print(exc.read().decode()[:800])
        return 1
    except urllib.error.URLError as exc:
        print(f"\nCould not reach Google: {exc.reason}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
