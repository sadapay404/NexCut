#!/usr/bin/env python3
"""Ask Google directly whether the key in .env works — none of app code in the path.

    python3 tools/check_key.py                 # uses .env + gemini-2.5-flash
    python3 tools/check_key.py gemini-2.0-flash # another model id

Prints the HTTP status and the response body, so a failure is Google's own words.
"""

from __future__ import annotations

import json
import os
import re
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


def load_env(env: dict[str, str]) -> None:
    """Let .env stand in for exported vars, so the tool and the server agree."""
    for name, value in env.items():
        os.environ.setdefault(name, value)


def shipped_default_model() -> str:
    """Stay in step with the app instead of repeating a model id here."""
    sys.path.insert(0, str(ROOT))
    try:
        from nexcut.providers import default_model  # noqa: PLC0415
        return default_model()
    except Exception:  # noqa: BLE001 - the tool must run standalone
        return "gemini-3.8-flash"


def list_models(key: str) -> int:
    """Print every id this key can call generateContent on."""
    url = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=200"
    req = urllib.request.Request(url, headers={"x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            payload = json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}\n{exc.read().decode()[:600]}")
        return 1
    except urllib.error.URLError as exc:
        print(f"Could not reach Google: {exc.reason}")
        return 1
    usable = []
    for model in payload.get("models", []):
        methods = model.get("supportedGenerationMethods") or []
        if "generateContent" in methods:
            usable.append(model["name"].split("/")[-1])
    usable.sort(reverse=True)
    print(f"{len(usable)} model(s) this key may call:\n")
    for name in usable:
        print(f"  {name}")
    print("\nUse one of them:")
    print(f"  echo 'NEXCUT_MODELS={','.join(usable[:3])}' >> .env")
    return 0


SUGGESTION = re.compile(r"use (?:the )?models?/([A-Za-z0-9._\-]+)")


def check_key_suggestion(body: str) -> str:
    found = SUGGESTION.search(body or "")
    return found.group(1) if found else ""


def main(argv: list[str]) -> int:
    env = read_env()
    load_env(env)
    key = (env.get("NEXCUT_API_KEY") or os.environ.get("NEXCUT_API_KEY", "")).strip()
    if len(argv) > 1:
        model = argv[1]
    else:
        for name in ("NEXCUT_MODELS", "NEXCUT_MODEL"):
            value = (env.get(name) or os.environ.get(name, "")).split(",")[0].strip()
            if value:
                model = value
                break
        else:
            model = shipped_default_model()

    if not key:
        print("No NEXCUT_API_KEY in .env or the environment.")
        return 2
    print(f"key  {key[:6]}…{key[-4:]}  ({len(key)} chars)")
    print(f"model {model}")

    if model in ("--list", "-l", "list"):
        return list_models(key)

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
        body_text = exc.read().decode()
        print(f"\nHTTP {exc.code}  FAILED")
        print(body_text[:800])
        suggestion = check_key_suggestion(body_text)
        if suggestion and suggestion != model:
            print(f"\nGoogle names a replacement — try:")
            print(f"  python3 tools/check_key.py {suggestion}")
        if exc.code in (401, 403):
            print("\nThe key itself was refused: re-copy it from AI Studio, or enable "
                  "the Generative Language API for its project.")
        return 1
    except urllib.error.URLError as exc:
        print(f"\nCould not reach Google: {exc.reason}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
