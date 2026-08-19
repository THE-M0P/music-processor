"""Application settings."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    uploads: Path
    library: Path
    quarantine: Path
    lock_file: Path
    acoustid_api_key: str | None
    musicbrainz_contact: str
    decision_log: Path | None = None
    fallback_album: str = "Singles & Miscellaneous"
    stability_wait: float = 2.0
    request_timeout: float = 15.0
    dry_run: bool = False
