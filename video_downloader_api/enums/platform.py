from enum import Enum


class Platform(str, Enum):
    YOUTUBE = "youtube"
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"
    TIKTOK = "tiktok"

    # Adult sites reachable from the app's 18+ section.
    PORNHUB = "pornhub"
    XHAMSTER = "xhamster"
    XNXX = "xnxx"
    XVIDEOS = "xvideos"
    DESITALES = "desitales"
    DARKERO = "darkero"

    UNKNOWN = "unknown"
