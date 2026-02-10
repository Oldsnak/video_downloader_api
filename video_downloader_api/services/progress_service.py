# video_downloader_api/services/progress_service.py

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from video_downloader_api.core.logger import get_logger
from video_downloader_api.repositories.job_repo import JobRepository
from video_downloader_api.services.events_service import EventsService


class ProgressService:
    """
    Converts downloader progress hook data (yt-dlp) -> DB updates + events publish.

    yt-dlp hook dict examples (common keys):
    - status: "downloading" | "finished" | "error"
    - downloaded_bytes
    - total_bytes
    - total_bytes_estimate
    - speed
    - eta
    """

    def __init__(self, repo_factory: Callable[[], JobRepository], events: EventsService) -> None:
        self.repo_factory = repo_factory
        self.events = events
        self.logger = get_logger(self.__class__.__name__)

    def _safe_int(self, v: Any) -> Optional[int]:
        try:
            if v is None:
                return None
            return int(v)
        except Exception:
            return None

    def _safe_float(self, v: Any) -> Optional[float]:
        try:
            if v is None:
                return None
            return float(v)
        except Exception:
            return None

    def handle_hook(self, job_id: str, hook_data: Dict[str, Any]) -> None:
        """
        Called repeatedly by yt-dlp progress_hooks.
        - Extract downloaded/total/speed/eta
        - Update DB via JobRepository
        - Publish events for SSE/WebSocket
        """
        try:
            status = str(hook_data.get("status") or "")

            downloaded_bytes = self._safe_int(hook_data.get("downloaded_bytes")) or 0

            total_bytes = self._safe_int(hook_data.get("total_bytes"))
            if total_bytes is None:
                total_bytes = self._safe_int(hook_data.get("total_bytes_estimate"))

            speed_bps = self._safe_float(hook_data.get("speed"))
            eta_sec = self._safe_int(hook_data.get("eta"))

            percent: Optional[float] = None
            if total_bytes and total_bytes > 0:
                percent = round((downloaded_bytes / total_bytes) * 100.0, 2)

            # Save progress to DB
            repo = self.repo_factory()
            repo.update_progress(
                job_id=job_id,
                downloaded_bytes=downloaded_bytes,
                total_bytes=total_bytes,
                speed_bps=speed_bps,
                eta_sec=eta_sec,
            )

            # Publish event (client can render live progress)
            payload = {
                "job_id": job_id,
                "status": status,
                "progress": {
                    "downloaded_bytes": downloaded_bytes,
                    "total_bytes": total_bytes,
                    "speed_bps": speed_bps,
                    "eta_sec": eta_sec,
                    "percent": percent,
                },
            }
            self.events.publish(job_id, payload)

        except Exception:
            # Never crash the download because of progress parsing issues
            self.logger.exception("ProgressService.handle_hook failed for job_id=%s", job_id)
