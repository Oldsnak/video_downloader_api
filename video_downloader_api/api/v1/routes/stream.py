# video_downloader_api/api/v1/routes/stream.py

from __future__ import annotations

import json
from typing import Iterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from video_downloader_api.middleware.auth import verify_api_key
from video_downloader_api.services.events_service import EventsService

router = APIRouter(prefix="/download")

# NOTE:
# This is an in-memory events bus.
# For real production (separate worker process), replace EventsService with Redis pubsub.
events = EventsService()


@router.get("/stream/{job_id}", dependencies=[Depends(verify_api_key)])
def stream_progress(job_id: str) -> StreamingResponse:
    """
    SSE stream of progress updates.
    Yields: data: {json}\n\n
    """

    def event_generator() -> Iterator[str]:
        for payload in events.subscribe(job_id):
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")
