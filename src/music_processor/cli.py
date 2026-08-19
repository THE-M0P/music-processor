"""Command-line entry point."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from music_processor.clients import AcoustIDClient, MusicBrainzClient
from music_processor.config import Settings
from music_processor.locking import AlreadyRunningError, single_instance
from music_processor.processor import MusicProcessor

DEFAULT_CONTACT = "https://github.com/THE-M0P/music-processor"


def environment_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Identify, tag, and organise files from a music upload directory."
    )
    parser.add_argument(
        "--uploads",
        type=Path,
        default=Path(os.environ.get("MUSIC_UPLOADS_DIR", "/mnt/music/uploads")),
    )
    parser.add_argument(
        "--library",
        type=Path,
        default=Path(os.environ.get("MUSIC_LIBRARY_DIR", "/mnt/music/Music")),
    )
    parser.add_argument(
        "--quarantine",
        type=Path,
        default=Path(os.environ.get("MUSIC_QUARANTINE_DIR", "/mnt/music/failed")),
    )
    parser.add_argument(
        "--lock-file",
        type=Path,
        default=Path(os.environ.get("MUSIC_PROCESSOR_LOCK_FILE", "/tmp/music-processor.lock")),
    )
    parser.add_argument(
        "--musicbrainz-contact",
        default=os.environ.get("MUSICBRAINZ_CONTACT", DEFAULT_CONTACT),
    )
    parser.add_argument(
        "--decision-log",
        type=Path,
        default=(
            Path(os.environ["MUSIC_PROCESSOR_DECISION_LOG"])
            if os.environ.get("MUSIC_PROCESSOR_DECISION_LOG")
            else None
        ),
    )
    parser.add_argument(
        "--fallback-album",
        default=os.environ.get("MUSIC_PROCESSOR_FALLBACK_ALBUM", "Singles & Miscellaneous"),
    )
    parser.add_argument("--stability-wait", type=float, default=2.0)
    parser.add_argument("--request-timeout", type=float, default=15.0)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=environment_flag("MUSIC_PROCESSOR_DRY_RUN"),
    )
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default=os.environ.get("MUSIC_PROCESSOR_LOG_LEVEL", "INFO"),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = Settings(
        uploads=args.uploads,
        library=args.library,
        quarantine=args.quarantine,
        lock_file=args.lock_file,
        acoustid_api_key=os.environ.get("ACOUSTID_API_KEY") or None,
        musicbrainz_contact=args.musicbrainz_contact,
        decision_log=args.decision_log,
        fallback_album=args.fallback_album,
        stability_wait=args.stability_wait,
        request_timeout=args.request_timeout,
        dry_run=args.dry_run,
    )
    acoustid = (
        AcoustIDClient(settings.acoustid_api_key, timeout=settings.request_timeout)
        if settings.acoustid_api_key
        else None
    )
    processor = MusicProcessor(
        settings,
        musicbrainz=MusicBrainzClient(settings.musicbrainz_contact),
        acoustid=acoustid,
    )
    try:
        with single_instance(settings.lock_file):
            summary = processor.process_pending()
    except AlreadyRunningError:
        logging.getLogger(__name__).info("Another processor instance is already running")
        return 0

    logging.getLogger(__name__).info(
        "Finished: discovered=%d imported=%d sidecars_removed=%d quarantined=%d "
        "deferred=%d failed=%d",
        summary.discovered,
        summary.imported,
        summary.sidecars_removed,
        summary.quarantined,
        summary.deferred,
        summary.failed,
    )
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
