"""Model providers.

    GeminiProvider  : Google Generative Language API (stdlib HTTP, no SDK)
    OpenAIProvider  : any OpenAI-compatible chat endpoint (OpenAI, OpenRouter,
                      Groq, Together, LM Studio, Ollama's /v1 ...)
    StubProvider    : offline, deterministic — builds a contract-valid report
                      from the transcript so the app runs with no key at all

The prompt is *not* built here any more: `nexcut.prompts.compose()` produces
(system, user) from your master prompt file, and providers only transport it.
That is what lets you swap the prompt without touching code.

Failover is explicit: chosen model -> other models (if cascade) -> backup key.
Every step is named in the error so a failure is diagnosable from the UI text.
"""

from __future__ import annotations

import json
import os
import re
import socket
import urllib.error
import urllib.request

from .parse import ExtractError, TimeoutError_
from .schema import WINDOWS, hms

GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
OPENAI_ENDPOINT = "{base}/chat/completions"

# Newest first: Google retires ids for accounts that never used them, and a 404
# now self-heals (see _suggested_model), so this list is a starting point, not law.
GEMINI_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-3.5-flash",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
]
OPENAI_MODELS = ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini"]

# Groq speaks the OpenAI wire format; ids drift, so `check_key.py --list` is truth.
GROQ_BASE = "https://api.groq.com/openai/v1"
GROQ_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "openai/gpt-oss-120b",
]

TIMEOUT_MSG = "Gemini is slow right now — the request timed out before it answered."


def provider_kind() -> str:
    kind = (os.environ.get("NEXCUT_PROVIDER") or "stub").strip().lower()
    return "openai" if kind in ("groq",) else kind


def provider_label() -> str:
    """What the user called it — 'groq' stays groq in messages and logs."""
    return (os.environ.get("NEXCUT_PROVIDER") or "stub").strip().lower()


def request_timeout() -> int:
    try:
        return max(10, int(os.environ.get("NEXCUT_TIMEOUT", "180")))
    except ValueError:
        return 180


DEFAULT_GEMINI_MODEL = GEMINI_MODELS[0]

# "…please update your code to use models/gemini-3.8-flash…"
_SUGGESTION = re.compile(r"use (?:the )?models?/([A-Za-z0-9._\-]+)")


def _suggested_model(message: str) -> str:
    """The replacement id Google names in a retired-model 404, or ''."""
    found = _SUGGESTION.search(message or "")
    return found.group(1) if found else ""


def default_model() -> str:
    """NEXCUT_MODEL, else the head of NEXCUT_MODELS, else the catalog head."""
    explicit = (os.environ.get("NEXCUT_MODEL") or "").strip()
    if explicit:
        return explicit
    return model_catalog()[0]["id"]


def health_candidates(limit: int = 3) -> list[str]:
    """Models worth trying for a key check: the default, then the catalogue."""
    first = default_model()
    rest = [m["id"] for m in model_catalog() if m["id"] != first]
    return [m for m in ([first] + rest) if m != "offline-demo"][:limit]


def model_catalog() -> list[dict[str, str]]:
    raw = os.environ.get("NEXCUT_MODELS")
    if raw:
        ids = [m.strip() for m in raw.split(",") if m.strip()]
    elif provider_kind() == "openai":
        ids = list(GROQ_MODELS if provider_label() == "groq" else OPENAI_MODELS)
    elif provider_kind() == "gemini":
        ids = list(GEMINI_MODELS)
    else:
        ids = ["offline-demo"]
    return [{"id": m, "label": m} for m in ids]


def resolve_model(alias: str) -> str:
    try:
        mapping = json.loads(os.environ.get("NEXCUT_MODEL_MAP", "") or "{}")
    except json.JSONDecodeError:
        mapping = {}
    return mapping.get(alias, alias)


class ProviderError(ExtractError):
    """Non-retryable unless `retryable` is set (then the cascade moves on)."""

    def __init__(self, message: str, *, retryable: bool = False,
                 hint: str = "") -> None:
        super().__init__(message)
        self.retryable = retryable
        self.hint = hint


class _HttpProvider:
    """Shared transport: one attempt, precise error classification."""

    name = "http"

    def __init__(self, api_key: str, *, backup_key: str = "", timeout: int | None = None) -> None:
        self.api_key = (api_key or "").strip()
        self.backup_key = (backup_key or os.environ.get("NEXCUT_BACKUP_KEY", "")).strip()
        self.timeout = timeout or request_timeout()

    # subclass hook -----------------------------------------------------
    def _attempt(self, model: str, system: str, user: str, key: str) -> str:
        raise NotImplementedError

    def _post(self, url: str, body: dict, headers: dict, *, label: str = "the model") -> dict:
        req = urllib.request.Request(
            url, data=json.dumps(body).encode(), method="POST",
            headers={"Content-Type": "application/json", **headers},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode() or "{}")
        except socket.timeout as exc:
            raise TimeoutError_() from exc
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode()[:400]
            if exc.code in (429, 500, 502, 503, 504):
                hint = ""
                if exc.code == 429:
                    hint = ("Rate limit. Free tiers cap tokens per minute, and a long "
                            "transcript is a big request — retry shortly, or use a "
                            "shorter video / higher tier.")
                raise ProviderError(
                    f"{label} was unavailable (HTTP {exc.code}).",
                    retryable=True, hint=hint,
                ) from exc
            if exc.code in (401, 403):
                raise ProviderError(
                    "That API key was rejected. Check it was copied fully and is enabled."
                ) from exc
            if exc.code == 404:
                raise ProviderError(
                    f"{label} was not found at this provider: {detail}",
                    hint="Set NEXCUT_MODELS to a model your key can use, then restart.",
                ) from exc
            if "model name format" in detail or "unexpected model name" in detail:
                raise ProviderError(
                    "That model id is not in a form Google accepts.",
                    hint="Copy an id from `python3 tools/check_key.py --list` and set "
                         "NEXCUT_MODELS to it, then restart.",
                ) from exc
            raise ProviderError(f"Provider error {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"Could not reach the model provider: {exc.reason}") from exc

    # public ------------------------------------------------------------
    def complete(self, *, system: str, user: str, model: str, cascade: bool) -> tuple[str, str]:
        order = [model]
        if cascade:
            order += [m["id"] for m in model_catalog() if m["id"] != model]
        keys = [self.api_key] + ([self.backup_key] if self.backup_key else [])
        if not keys[0] and not self.backup_key:
            raise ProviderError(
                "No API key. Put NEXCUT_API_KEY=... in .env next to the repo root, "
                "or export it before starting the server.",
                hint="NEXCUT_API_KEY was empty when the server started — .env is only "
                     "read at startup, so restart after editing it.")

        last: ProviderError | None = None
        for key in keys:
            for candidate in order:
                try:
                    text = self._attempt(candidate, system, user, key)
                    return text, getattr(self, "served_model", candidate)
                except TimeoutError_:
                    raise
                except ProviderError as exc:
                    last = exc
                    if not exc.retryable:
                        raise
        if len(order) == 1 and last is not None:
            raise last
        raise ProviderError(
            "Every model in the fallback chain failed. " + (str(last) if last else "")
        )


class GeminiProvider(_HttpProvider):
    name = "gemini"

    def _attempt(self, model: str, system: str, user: str, key: str) -> str:
        try:
            return self._attempt_once(model, system, user, key)
        except ProviderError as exc:
            replacement = _suggested_model(str(exc))
            if replacement and replacement != model:
                return self._attempt_once(replacement, system, user, key)
            raise

    def _attempt_once(self, model: str, system: str, user: str, key: str) -> str:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": 0.6,
                "responseMimeType": "application/json",
                "maxOutputTokens": 8192,
            },
        }
        url = GEMINI_ENDPOINT.format(model=resolve_model(model))
        # ?key= for older keys, header for the newer AQ.… AI Studio keys: send both
        served = resolve_model(model)
        payload = self._post(url + f"?key={key}", body, {"x-goog-api-key": key},
                             label=served)
        self.served_model = served
        try:
            parts = payload["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts)
        except (KeyError, IndexError, TypeError) as exc:
            reason = (payload.get("promptFeedback") or {}).get("blockReason")
            if reason:
                raise ProviderError(f"Google blocked this request ({reason}).") from exc
            raise ProviderError("Google returned no text for this request.") from exc
        if not text.strip():
            raise ProviderError("Google returned an empty answer.")
        return text


class OpenAIProvider(_HttpProvider):
    name = "openai"

    def __init__(self, api_key: str, **kw) -> None:
        super().__init__(api_key, **kw)
        default_base = GROQ_BASE if provider_label() == "groq" else "https://api.openai.com/v1"
        self.base = (os.environ.get("NEXCUT_OPENAI_BASE") or default_base).rstrip("/")

    @property
    def name(self) -> str:  # "groq" in logs when that's what was configured
        return provider_label() if provider_label() in ("groq", "openai") else "openai"

    def _attempt(self, model: str, system: str, user: str, key: str) -> str:
        body = {
            "model": resolve_model(model),
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.6,
            "response_format": {"type": "json_object"},
        }
        payload = self._post(
            OPENAI_ENDPOINT.format(base=self.base), body,
            {"Authorization": f"Bearer {key}"}, label=model,
        )
        try:
            text = payload["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("The provider returned no message content.") from exc
        if not text.strip():
            raise ProviderError("The provider returned an empty answer.")
        return text


class StubProvider:
    """Offline demo provider — no network, no key, same output contract."""

    name = "stub"

    def complete(self, *, system: str, user: str, model: str, cascade: bool,
                 ctx: dict | None = None) -> tuple[str, str]:
        ctx = ctx or {}
        return json.dumps(self._compose(**ctx)), "offline-demo"

    def _compose(self, *, transcript: str = "", window: str = "E", num_clips: int = 5,
                 custom_min: int | None = None, custom_max: int | None = None,
                 niche: str = "True Crime", **_) -> dict:
        from .prompt import split_transcript

        lines = split_transcript(transcript)
        if not lines:
            raise ExtractError(
                "NO TIMESTAMPS in the transcript — this run needs [00:12:30]-style stamps."
            )

        if custom_min and custom_max:
            lo, hi = int(custom_min), int(custom_max)
        else:
            _, lo, hi = WINDOWS.get(window, WINDOWS["E"])
        target = max(lo + 5, min(hi - 5, lo + 40))

        clips: list[dict] = []
        i, n = 0, 1
        while i < len(lines) - 1 and len(clips) < num_clips:
            start_sec, start_text = lines[i]
            j = i + 1
            while j < len(lines) and lines[j][0] - start_sec < target:
                j += 1
            if j >= len(lines):
                j = len(lines) - 1
            end_sec, end_text = lines[j]
            dur = end_sec - start_sec
            if j > i and lo <= dur <= hi:
                scores = {"curiosity": 8.5, "stakes": 8.0, "specificity": 8.5, "speed": 8.0}
                clips.append({
                    "n": n,
                    "hook_summary": start_text[:60],
                    "start_sec": start_sec,
                    "start_stamp": hms(start_sec),
                    "start_sentence": start_text,
                    "end_sec": end_sec,
                    "end_stamp": hms(end_sec),
                    "end_sentence": end_text,
                    "duration_line": f"{int(dur // 60)} min {int(dur % 60)} sec",
                    "titles": {
                        "clickbait": start_text[:48],
                        "search": " ".join(start_text.split()[:5]),
                        "debate": "Was this avoidable?",
                    },
                    "scores": {**scores, "avg": round(sum(scores.values()) / 4, 2)},
                    "verbal_hook": start_text[:40],
                    "ending": end_text[:40],
                    "why_it_works": "opens a concrete loop on the first line.",
                    "share_trigger": "argument bait",
                    "safety": "none",
                    "overlays": [{"offset": "00:02", "text": start_text[:24]}],
                    "sfx": "low pulse",
                    "captions": "2-line bold, keyword highlighted",
                    "upload_caption": start_text[:70],
                    "hashtags": "#shorts #viral",
                    "pinned_comment": "what did we miss?",
                    "transcript_ts": "\n".join(f"{hms(s)} - {t}" for s, t in lines[i:j + 1]),
                    "transcript": " ".join(t for _s, t in lines[i:j + 1]),
                })
                n += 1
                i = j + 1
            else:
                i += 1

        return {
            "sweep": {
                "window": WINDOWS.get(window, ("", 0, 0))[0] if not custom_min else f"custom {lo}-{hi}s",
                "ranges": f"{hms(lines[0][0])}-{hms(lines[-1][0])}",
                "longlist": len(clips) + 2,
                "cleared": len(clips),
            },
            "longlist": [{"start": hms(s), "gist": t[:50]} for s, t in lines[: len(clips) + 2]],
            "clips": clips,
        }


def make_provider(api_key: str = "") -> object:
    # the browser no longer asks for a key: NEXCUT_API_KEY (or .env) wins
    api_key = (api_key or os.environ.get("NEXCUT_API_KEY", "")).strip()
    kind = provider_kind()
    if kind == "gemini":
        return GeminiProvider(api_key)
    if kind == "openai":
        return OpenAIProvider(api_key)
    return StubProvider()
