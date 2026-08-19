"""Durable mapping between source media and imported files."""

from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit, urlunsplit

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SourceRecord:
    source_key: str
    source_url: str
    path: Path
    content_digest: str


def source_identity_key(source_url: str) -> str:
    if not source_url:
        return ""
    parsed = urlsplit(source_url.strip())
    host = (parsed.hostname or "").casefold()
    path_parts = [part for part in parsed.path.split("/") if part]
    video_id = ""
    if host in {"youtu.be", "www.youtu.be"} and path_parts:
        video_id = path_parts[0]
    elif host in {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}:
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [""])[0]
        elif len(path_parts) >= 2 and path_parts[0] in {"embed", "live", "shorts"}:
            video_id = path_parts[1]
    if video_id:
        return f"youtube:{video_id}"
    normalised = urlunsplit(
        (
            parsed.scheme.casefold(),
            parsed.netloc.casefold(),
            parsed.path,
            parsed.query,
            "",
        )
    )
    return f"url:{normalised}"


class SourceRegistry:
    def __init__(self, path: Path | None) -> None:
        self.path = path

    def lookup(self, source_url: str) -> SourceRecord | None:
        source_key = source_identity_key(source_url)
        if not source_key or self.path is None or not self.path.is_file():
            return None
        try:
            with closing(sqlite3.connect(self.path)) as database:
                row = database.execute(
                    """
                    SELECT source_url, path, content_digest
                    FROM source_media
                    WHERE source_key = ?
                    """,
                    (source_key,),
                ).fetchone()
        except sqlite3.Error as error:
            LOGGER.warning("Could not read source registry %s: %s", self.path, error)
            return None
        if row is None:
            return None
        return SourceRecord(
            source_key=source_key,
            source_url=row[0],
            path=Path(row[1]),
            content_digest=row[2],
        )

    def register(self, source_url: str, path: Path, content_digest: str) -> None:
        source_key = source_identity_key(source_url)
        if not source_key or self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with closing(sqlite3.connect(self.path)) as database:
                self._create_schema(database)
                database.execute(
                    """
                    INSERT INTO source_media(
                        source_key, source_url, path, content_digest, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(source_key) DO UPDATE SET
                        source_url = excluded.source_url,
                        path = excluded.path,
                        content_digest = excluded.content_digest,
                        updated_at = excluded.updated_at
                    """,
                    (
                        source_key,
                        source_url,
                        str(path),
                        content_digest,
                        datetime.now(UTC).isoformat(),
                    ),
                )
                database.commit()
            os.chmod(self.path, 0o600)
        except (OSError, sqlite3.Error) as error:
            LOGGER.warning("Could not update source registry %s: %s", self.path, error)

    @staticmethod
    def _create_schema(database: sqlite3.Connection) -> None:
        database.execute(
            """
            CREATE TABLE IF NOT EXISTS source_media(
                source_key TEXT PRIMARY KEY,
                source_url TEXT NOT NULL,
                path TEXT NOT NULL,
                content_digest TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
