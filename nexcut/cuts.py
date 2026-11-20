"""Cut job manager: one download, many clips, pollable progress.

Order matters for perceived speed: the source download dominates wall-clock time
and is shared by every clip, so it runs once up front (0–55 %) and each clip then
cuts from the local file (55–100 %). Second runs on the same video skip the
download entirely because the source is cached by (video_id, height).
"""

from __future__ import annotations

import shutil
import threading
import time
import uuid
from pathlib import Path

from .cutter import CUTS, CutterError, CutJob, cut, download, files_for, safe_name

MAX_CUTS = 30
RETENTION_DAYS = 3


class CutManager:
    def __init__(self) -> None:
        self._cuts: dict[str, CutJob] = {}
        self._lock = threading.Lock()
        self._prune()

    # -- housekeeping ------------------------------------------------------
    def _prune(self) -> None:
        if not CUTS.is_dir():
            return
        cutoff = time.time() - RETENTION_DAYS * 86400
        for child in CUTS.iterdir():
            try:
                if child.is_dir() and child.stat().st_mtime < cutoff:
                    shutil.rmtree(child, ignore_errors=True)
            except OSError:
                continue

    def get(self, cut_id: str) -> CutJob | None:
        with self._lock:
            return self._cuts.get(cut_id)

    def directory(self, cut_id: str) -> Path:
        return CUTS / cut_id

    # -- submission --------------------------------------------------------
    def submit(self, *, video_id: str, clips: list[dict], height: int,
               title: str = "", details: str = "") -> CutJob:
        job = CutJob(id=uuid.uuid4().hex[:12], created=time.time(),
                     quality=f"{height}p" if height < 2160 else "2160p (4K)")
        with self._lock:
            self._cuts[job.id] = job
            if len(self._cuts) > MAX_CUTS:
                for old in sorted(self._cuts.values(), key=lambda j: j.created)[:-MAX_CUTS]:
                    self._cuts.pop(old.id, None)
        out_dir = self.directory(job.id)
        out_dir.mkdir(parents=True, exist_ok=True)
        if details:
            (out_dir / "details.md").write_text(details, encoding="utf-8")
        threading.Thread(
            target=self._run, args=(job, video_id, clips, height), daemon=True
        ).start()
        return job

    def _step(self, job: CutJob, progress: int, stage: str) -> None:
        job.progress = progress
        job.stage = stage

    # -- pipeline ----------------------------------------------------------
    def _run(self, job: CutJob, video_id: str, clips: list[dict], height: int) -> None:
        out_dir = self.directory(job.id)
        try:
            job.status = "running"
            usable = [c for c in clips if c.get("end_sec", 0) > c.get("start_sec", 0)]
            if not usable:
                raise CutterError("No clip in this session has a usable time range.")

            self._step(job, 4, "Reading available qualities…")
            self._step(job, 10, "Downloading source video (this is the slow part)…")
            source = download(video_id, height)

            total = len(usable)
            for i, clip in enumerate(usable, start=1):
                pct = 55 + int(45 * (i - 1) / total)
                self._step(job, pct, f"Cutting clip {i} of {total}…")
                name = safe_name(int(clip.get("n") or i), clip["start_sec"], clip["end_sec"])
                cut(source, clip["start_sec"], clip["end_sec"], out_dir / name, height=height)
                job.files = files_for(job.id, out_dir)

            job.files = files_for(job.id, out_dir)
            if not job.files:
                raise CutterError("ffmpeg reported success but produced no files.")
            self._step(job, 100, f"{len(job.files)} clip(s) ready")
            job.status = "done"
        except CutterError as exc:
            job.status = "error"
            job.error = str(exc)
            job.error_hint = getattr(exc, "hint", "")
            job.stage = "Failed"
        except Exception as exc:  # noqa: BLE001 - never leave a job spinning
            job.status = "error"
            job.error = f"Unexpected failure: {type(exc).__name__}: {exc}"
            job.stage = "Failed"
