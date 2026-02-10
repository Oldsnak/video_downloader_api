# video_downloader_api/services/events_service.py

from __future__ import annotations

import json
import queue
import threading
from typing import Dict, Iterator, Optional


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
                payload = q.get()  # blocks until an event arrives
                yield payload
        finally:
            # Cleanup subscriber on disconnect
            with self._lock:
                if job_id in self._subscribers and q in self._subscribers[job_id]:
                    self._subscribers[job_id].remove(q)
                if job_id in self._subscribers and not self._subscribers[job_id]:
                    del self._subscribers[job_id]
