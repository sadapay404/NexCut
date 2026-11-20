#!/usr/bin/env python3
"""Ask the provider directly whether the key in .env works — app code not in the path.

    python3 tools/check_key.py --list          # every model id this key may call
    python3 tools/check_key.py                 # one tiny call, default model
    python3 tools/check_key.py <model-id>      # one tiny call, that model

Understands the providers the app understands:
  NEXCUT_PROVIDER=gemini            -> generativelanguage.googleapis.com
  NEXCUT_PROVIDER=groq | openai     -> {NEXCUT_OPENAI_BASE:-provider}/chat/completions
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
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GEMINI_LIST = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=200"
GROQ_BASE = "https://api.groq.com/openai/v1"
OPENAI_BASE = "https://api.openai.com/v1"

SUGGESTION = re.compile(r"use (?:the )?models?/([A-Za-z0-9._\-]+)")


# ── .env ──────────────────────────────────────────────────────────────
def read_env(path: Path | None = None) -> dict[str, str]:
    path = path or (ROOT / ".env")
    values: dict[str, str] = {}
    if not Path(path).is_file():
        return values
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
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


def provider() -> str:
    return (os.environ.get("NEXCUT_PROVIDER") or "gemini").strip().lower()


def base_url() -> str:
    if provider() == "groq":
        default = GROQ_BASE
    elif provider() == "openai":
        default = OPENAI_BASE
    else:
        default = ""
    return (os.environ.get("NEXCUT_OPENAI_BASE") or default).rstrip("/")


def shipped_default_model() -> str:
    """Stay in step with the app instead of repeating a model id here."""
    sys.path.insert(0, str(ROOT))
    try:
        from nexcut.providers import default_model  # noqa: PLC0415
        return default_model()
    except Exception:  # noqa: BLE001 - the tool must run standalone
        from nexcut.providers import GEMINI_MODELS  # noqa: PLC0415
        return GEMINI_MODELS[0]


def configured_model() -> str:
    for name in ("NEXCUT_MODELS", "NEXCUT_MODEL"):
        value = (os.environ.get(name, "") or "").split(",")[0].strip()
        if value:
            return value
    return shipped_default_model()


# ── http ──────────────────────────────────────────────────────────────
DEFAULT_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/126.0.0.0 Safari/537.36")


def _headers(extra: dict[str, str]) -> dict[str, str]:
    return {"Accept": "application/json", "User-Agent": DEFAULT_UA, **extra}


def is_edge_block(detail: str) -> bool:
    low = (detail or "").lower()
    return ("error code: 1010" in low or "cloudflare" in low
            or "just a moment" in low or "<html" in low)


def _get(url: str, headers: dict[str, str]) -> dict:
    req = urllib.request.Request(url, headers=_headers(headers))
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode() or "{}")


def _post(url: str, body: dict, headers: dict) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), method="POST",
        headers=_headers({"Content-Type": "application/json", **headers}),
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode() or "{}")


def list_models(key: str) -> int:
    """Print every id this key can actually call."""
    kind = provider()
    try:
        if kind in ("groq", "openai"):
            base = base_url()
            payload = _get(f"{base}/models", {"Authorization": f"Bearer {key}"})
            ids = sorted({m.get("id", "") for m in payload.get("data", []) if m.get("id")},
                         reverse=True)
            print(f"{len(ids)} model(s) at {base}:")
        else:
            payload = _get(GEMINI_LIST, {"x-goog-api-key": key})
            ids = sorted(
                {m["name"].split("/")[-1] for m in payload.get("models", [])
                 if "generateContent" in (m.get("supportedGenerationMethods") or [])},
                reverse=True,
            )
            print(f"{len(ids)} model(s) this key may call:")
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}\n{exc.read().decode()[:600]}")
        return 1
    except urllib.error.URLError as exc:
        print(f"Could not reach the provider: {exc.reason}")
        return 1

    for name in ids:
        print(f"  {name}")
    if ids:
        print("\nUse one (or three) of them:")
        print(f"  echo 'NEXCUT_MODELS={','.join(ids[:3])}' >> .env")
    return 0


def test_keys(model: str | None = None) -> int:
    """One tiny call per configured key — which of them actually work."""
    keys = env_key_list()
    if not keys:
        print("No keys in .env (NEXCUT_API_KEY / NEXCUT_BACKUP_KEY / NEXCUT_API_KEYS).")
        return 2
    model = model or configured_model()
    limit = keys if len(keys) <= 25 else keys[:25]
    print(f"provider {provider()}  model {model}  {len(keys)} key(s)"
          + (f" — testing the first {len(limit)}" if len(limit) < len(keys) else "") + "\n")

    working: list[int] = []
    for index, key in enumerate(limit, start=1):
        status, note = probe(key, model)
        mark = "ok  " if status == 200 else "fail"
        if status == 200:
            working.append(index)
        print(f"  {mark} #{index:<3} {mask(key):<14} {status or '---':<4} {note}")

    print()
    if working:
        print(f"{len(working)} of {len(limit)} worked: key #{working[0]}"
              + (f" (also {', '.join('#' + str(i) for i in working[1:])})"
                 if len(working) > 1 else ""))
        print(f"Put it first in NEXCUT_API_KEYS, or leave the list — the app rotates.")
        return 0
    print("None of them worked. If every line says 'key refused', the keys are invalid;")
    print("if they say 'cloudflare edge block', it is the network, not the keys.")
    return 1


def check_key_suggestion(body: str) -> str:
    found = SUGGESTION.search(body or "")
    return found.group(1) if found else ""


def request_spec(model: str):
    """(url, body, extract, header builder) for the configured provider."""
    kind = provider()
    if kind in ("groq", "openai"):
        base = base_url()
        body = {
            "model": model,
            "messages": [{"role": "user", "content": "Reply with the single word READY."}],
            "temperature": 0,
            "max_tokens": 16,
        }

        def extract(payload: dict) -> str:
            return (payload["choices"][0]["message"]["content"] or "").strip()

        return f"{base}/chat/completions", body, extract, \
            lambda key: {"Authorization": f"Bearer {key}"}

    body = {
        "contents": [{"role": "user", "parts": [{"text": "Reply with the single word READY."}]}],
        "generationConfig": {"maxOutputTokens": 16, "temperature": 0},
    }

    def extract(payload: dict) -> str:
        return "".join(p.get("text", "") for p in
                       payload["candidates"][0]["content"]["parts"]).strip()

    return GEMINI_ENDPOINT.format(model=model), body, extract, \
        lambda key: {"x-goog-api-key": key}


def probe(key: str, model: str) -> tuple[int, str]:
    """(http status or 0, spoken result) for one key and one model."""
    url, body, extract, headers = request_spec(model)
    try:
        payload = _post(url, body, headers(key))
        return 200, extract(payload) or "(empty)"
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()
        if is_edge_block(detail):
            return exc.code, "cloudflare edge block (not the key)"
        if exc.code in (401, 403):
            return exc.code, "key refused"
        if exc.code == 404:
            return 404, f"no model {model}"
        if exc.code == 429:
            return 429, "rate limited / out of quota"
        return exc.code, detail.strip().replace("\n", " ")[:120]
    except (urllib.error.URLError, TimeoutError) as exc:
        return 0, f"network: {getattr(exc, 'reason', exc)}"


def env_key_list() -> list[str]:
    sys.path.insert(0, str(ROOT))
    try:
        from nexcut.providers import env_keys  # noqa: PLC0415
        return env_keys()
    except Exception:  # noqa: BLE001
        raw = " ".join(os.environ.get(n, "") for n in
                       ("NEXCUT_API_KEY", "NEXCUT_BACKUP_KEY", "NEXCUT_API_KEYS"))
        return [k for k in re.split(r"[,\s]+", raw) if k]


def mask(key: str) -> str:
    return f"{key[:4]}…{key[-4:]}" if len(key) > 10 else "…"


# ── main ──────────────────────────────────────────────────────────────
def main(argv: list[str]) -> int:
    env = read_env()
    load_env(env)
    key = (env.get("NEXCUT_API_KEY") or os.environ.get("NEXCUT_API_KEY", "")).strip()
    model = argv[1] if len(argv) > 1 else configured_model()

    if not key:
        print("No NEXCUT_API_KEY in .env or the environment.")
        return 2
    if model in ("--list", "-l", "list"):
        return list_models(key)
    if model in ("--keys", "-k", "keys"):
        return test_keys(argv[2] if len(argv) > 2 else None)

    kind = provider()
    print(f"key  {key[:6]}…{key[-4:]}  ({len(key)} chars)")
    print(f"provider {kind}")
    print(f"model {model}")

    if kind in ("groq", "openai"):
        base = base_url()
        url = f"{base}/chat/completions"
        headers = {"Authorization": f"Bearer {key}"}
        body = {
            "model": model,
            "messages": [{"role": "user", "content": "Reply with the single word READY."}],
            "temperature": 0,
            "max_tokens": 16,
        }

        def extract(payload: dict) -> str:
            return (payload["choices"][0]["message"]["content"] or "").strip()
    else:
        url = GEMINI_ENDPOINT.format(model=model)
        headers = {"x-goog-api-key": key}
        body = {
            "contents": [{"role": "user", "parts": [{"text": "Reply with the single word READY."}]}],
            "generationConfig": {"maxOutputTokens": 16, "temperature": 0},
        }

        def extract(payload: dict) -> str:
            return "".join(p.get("text", "") for p in
                           payload["candidates"][0]["content"]["parts"]).strip()

    try:
        payload = _post(url, body, headers)
        print("\nHTTP 200  OK")
        print(f"reply: {extract(payload) or '(empty)'}")
        return 0
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()
        print(f"\nHTTP {exc.code}  FAILED")
        print(detail[:800])
        suggestion = check_key_suggestion(detail)
        if suggestion and suggestion != model:
            print("\nGoogle names a replacement — try:")
            print(f"  python3 tools/check_key.py {suggestion}")
        if is_edge_block(detail):
            print("\nCloudflare refused this client (error 1010) — that is the network "
                  "signature, not the key. Set NEXCUT_USER_AGENT to a browser UA, or "
                  "send the request from a different network.")
            print("Already carrying a browser UA in the app — if this is the tool only, "
                  "the app may still work.")
        elif exc.code in (401, 403):
            print("\nThe key itself was refused: re-copy it, check it is enabled for "
                  "this provider, and restart the server after editing .env.")
        if exc.code == 404 and kind in ("groq", "openai"):
            print("\nNo such model here — list them: python3 tools/check_key.py --list")
        return 1
    except urllib.error.URLError as exc:
        print(f"\nCould not reach the provider: {exc.reason}")
        return 1
    except TimeoutError:
        print("\nThe provider did not answer within 60s.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
