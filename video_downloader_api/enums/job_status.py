from enum import Enum


class JobStatus(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    FINISHED = "finished"
    FAILED = "failed"
    CANCELED = "canceled"
