# video_downloader_api/services/events_service.py

from __future__ import annotations

import json
import queue
import threading
from typing import Dict, Iterator, Optional

_default: Optional["EventsService"] = None
_default_lock = threading.Lock()


def get_events() -> "EventsService":
    """Process-wide bus so the SSE route and the download thread share subscribers."""
    global _default
    with _default_lock:
        if _default is None:
            _default = EventsService()
        return _default


class EventsService:
    """
    In-memory pub/sub event service for progress streaming (SSE/WebSocket).

    - publish(job_id, payload): sends payload to all subscribers of job_id
    - subscribe(job_id): yields payload dicts as events arrive

    Note:
    This in-memory approach works for a single API instance.
    For multiple instances / production, replace with Redis pubsub and keep the same interface.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: Dict[str, list[queue.Queue]] = {}

    def publish(self, job_id: str, payload: dict) -> None:
        """
        Publish an event to all subscribers of the given job_id.
        """
        with self._lock:
            queues = list(self._subscribers.get(job_id, []))

        # Push outside lock
        for q in queues:
            try:
                q.put_nowait(payload)
            except Exception:
                # Ignore slow/broken subscribers
                pass

    def subscribe(self, job_id: str) -> Iterator[dict]:
        """
        Subscribe to events for a job_id and yield them as they arrive.

        This is used by the SSE route like:
            for event in events_service.subscribe(job_id):
                yield f"data: {json.dumps(event)}\\n\\n"
        """
        q: queue.Queue = queue.Queue(maxsize=200)

        with self._lock:
            self._subscribers.setdefault(job_id, []).append(q)

        try:
            while True:
                try:
                    payload = q.get(timeout=15)
                except queue.Empty:
                    # Keep-alive so Cloudflare / proxies do not idle-drop the SSE socket.
                    yield {"job_id": job_id, "type": "ping"}
                    continue
                yield payload
        finally:
            # Cleanup subscriber on disconnect
            with self._lock:
                if job_id in self._subscribers and q in self._subscribers[job_id]:
                    self._subscribers[job_id].remove(q)
                if job_id in self._subscribers and not self._subscribers[job_id]:
                    del self._subscribers[job_id]
