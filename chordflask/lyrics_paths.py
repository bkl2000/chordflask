"""The two independent, ordinary Lyrics sidecars beside a media file."""
from pathlib import Path


def lyrics_path(media, version="v1"):
    if version not in ("v1", "v2"):
        raise ValueError("Unknown Lyrics version")
    return Path(media).with_suffix(".cho" if version == "v1" else ".v2.cho")
