"""In-process job manager.

A run is: link -> captions -> transcript check -> coverage plan -> model ->
parse -> gate -> results. The UI gets a `job_id` immediately and polls
`progress` + `stage`, so a two-minute model call never sits on one socket.

Stages are emitted by the real pipeline functions, so a stuck run can be
localised instead of showing a generic spinner.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from .ingest import IngestError, fetch_transcript
from .parse import ExtractError, build_result, ensure_timestamps
from .prompt import format_ranges, plan_sweep
from .prompts import compose
from .schema import WINDOWS
from .validate import apply_rules

MAX_JOBS = 60
JOB_TTL_SEC = 2 * 60 * 60


@dataclass
class Job:
    id: str
    status: str = "pending"          # pending | running | done | error
    progress: int = 0
    stage: str = "Queued"
    error: str | None = None
    error_hint: str = ""
    result: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)
    created: float = field(default_factory=time.time)
    params: dict[str, Any] = field(default_factory=dict)
    elapsed_s: float = 0.0

    def status_payload(self) -> dict[str, Any]:
        return {
            "job_id": self.id,
            "status": self.status,
            "progress": self.progress,
            "stage": self.stage,
            "error": self.error,
            "error_hint": self.error_hint,
            "warnings": self.warnings,
            "elapsed_s": round(self.elapsed_s, 2),
        }


class JobManager:
    def __init__(self, provider_factory: Callable[[str], Any]) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._provider_factory = provider_factory

    # -- lifecycle ---------------------------------------------------------
    def submit(self, params: dict[str, Any]) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], params=params)
        with self._lock:
            self._prune_locked()
            self._jobs[job.id] = job
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def _prune_locked(self) -> None:
        now = time.time()
        for k in [k for k, j in self._jobs.items() if now - j.created > JOB_TTL_SEC]:
            self._jobs.pop(k, None)
        if len(self._jobs) > MAX_JOBS:
            keep = sorted(self._jobs.items(), key=lambda kv: kv[1].created)[-MAX_JOBS:]
            self._jobs = dict(keep)

    # -- pipeline ----------------------------------------------------------
    def _step(self, job: Job, progress: int, stage: str) -> None:
        job.progress = progress
        job.stage = stage

    def _run(self, job: Job) -> None:
        started = time.time()
        p = job.params
        try:
            job.status = "running"

            transcript = (p.get("transcript_text") or "").strip()
            title = p.get("episode_title") or ""
            channel = p.get("channel_show") or ""
            video_id = p.get("video_id") or ""

            # 1. capture: link -> captions, unless the user pasted text
            if not transcript:
                url = p.get("youtube_url") or ""
                if not url:
                    raise ExtractError(
                        "Nothing to work from. Paste a YouTube link, or paste a transcript."
                    )
                self._step(job, 6, "Fetching captions from YouTube…")
                tr = fetch_transcript(url, language=(p.get("caption_lang") or "en"))
                transcript = tr.text
                video_id = video_id or tr.video_id
                title = title or tr.title
                channel = channel or tr.channel
                job.params["transcript_source"] = tr.source
                job.params["transcript_chars"] = len(transcript)
                job.params["video_title"] = title
                job.params["is_auto_captions"] = tr.is_auto

            # 2. pre-flight: never spend tokens on a transcript we cannot cite
            self._step(job, 16, "Checking the transcript…")
            ensure_timestamps(transcript)

            # 3. coverage plan
            self._step(job, 24, "Planning coverage…")
            ranges = plan_sweep(transcript)
            if not ranges:
                raise ExtractError("Could not read a single timestamp from the transcript.")

            self._step(job, 32, f"Covering {len(ranges)} range(s): {format_ranges(ranges)[:70]}")

            window = p.get("window") or "E"
            custom_min = p.get("custom_min_sec")
            custom_max = p.get("custom_max_sec")
            label = (
                f"custom {custom_min}-{custom_max}s"
                if custom_min and custom_max
                else WINDOWS.get(window, WINDOWS["E"])[0]
            )

            # 4. prompt from YOUR master file, then the model
            self._step(job, 44, "Building the prompt…")
            system, user, warnings = compose(
                transcript=transcript,
                niche=p.get("niche") or "True Crime",
                audience=p.get("audience") or "U.S. English",
                language=p.get("language") or "U.S. English",
                window=window,
                num_clips=int(p.get("num_clips") or 5),
                channel_show=channel,
                episode_title=title,
                host_guest=p.get("host_guest") or "",
                already_extracted=p.get("already_extracted") or "",
                custom_min=custom_min,
                custom_max=custom_max,
                video_id=video_id,
                ranges_text=format_ranges(ranges),
            )
            job.warnings.extend(warnings)
            job.params["prompt_chars"] = len(system) + len(user)

            self._step(job, 56, "Asking the model for candidates…")
            provider = self._provider_factory(p.get("api_key") or "")
            answer, model_used = provider.complete(
                system=system, user=user,
                model=p.get("model") or "gemini-2.5-flash",
                cascade=bool(p.get("cascade", True)),
                ctx={
                    "transcript": transcript,
                    "window": window,
                    "num_clips": int(p.get("num_clips") or 5),
                    "custom_min": custom_min,
                    "custom_max": custom_max,
                    "niche": p.get("niche") or "True Crime",
                },
            )

            # 5. parse
            self._step(job, 72, "Parsing the clip report…")
            result = build_result(
                answer, video_id=video_id, video_title=title, window_label=label
            )
            result.oracle_report = answer

            # 6. score + gate
            self._step(job, 84, "Applying the rule gate…")
            result = apply_rules(
                result, transcript, window=window,
                custom_min=custom_min, custom_max=custom_max,
                limit=int(p.get("num_clips") or 5),
            )
            result.sweep.ranges = result.sweep.ranges or format_ranges(ranges)

            payload = result.to_dict()
            payload.update({
                "video_title": title or payload.get("video_title", ""),
                "channel": channel,
                "video_id": video_id,
                "model_used": model_used,
                "ranges_planned": format_ranges(ranges),
                "transcript_source": job.params.get("transcript_source", "pasted"),
                "transcript_chars": len(transcript),
                "warnings": job.warnings,
            })
            job.result = payload

            self._step(job, 100, "Done")
            job.status = "done"
        except (ExtractError, IngestError) as exc:
            job.status = "error"
            job.error = str(exc)
            job.error_hint = getattr(exc, "hint", "") or ""
            job.stage = "Failed"
        except Exception as exc:  # noqa: BLE001 - never lose the thread silently
            job.status = "error"
            job.error = f"Unexpected failure: {type(exc).__name__}: {exc}"
            job.stage = "Failed"
        finally:
            job.elapsed_s = time.time() - started
