"""Music upload processing workflow."""

from __future__ import annotations

import json
import logging
import shutil
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from music_processor.clients import AcoustIDClient, FingerprintResult, MusicBrainzClient
from music_processor.config import Settings
from music_processor.naming import (
    artists_match,
    canonical_song_title,
    clean_album,
    clean_title,
    merge_version_title,
    normalise_artist_case,
    primary_artist,
    safe_name,
    split_upload_filename,
)
from music_processor.tags import (
    SUPPORTED_EXTENSIONS,
    TaggingError,
    Tags,
    audio_duration,
    read_tags,
    write_tags,
)

LOGGER = logging.getLogger(__name__)
SIDECAR_EXTENSIONS = {".webp", ".jpg", ".jpeg", ".png"}
INCOMPLETE_EXTENSIONS = {".part", ".ytdl", ".tmp"}


@dataclass(slots=True)
class ProcessingSummary:
    discovered: int = 0
    imported: int = 0
    sidecars_removed: int = 0
    quarantined: int = 0
    deferred: int = 0
    failed: int = 0


class MusicProcessor:
    def __init__(
        self,
        settings: Settings,
        musicbrainz: MusicBrainzClient,
        acoustid: AcoustIDClient | None,
    ) -> None:
        self.settings = settings
        self.musicbrainz = musicbrainz
        self.acoustid = acoustid

    def process_pending(self) -> ProcessingSummary:
        if not self.settings.uploads.is_dir():
            raise FileNotFoundError(f"uploads directory does not exist: {self.settings.uploads}")
        if not self.settings.dry_run:
            self.settings.library.mkdir(parents=True, exist_ok=True)
            self.settings.quarantine.mkdir(parents=True, exist_ok=True)
            if self.settings.decision_log:
                self.settings.decision_log.parent.mkdir(parents=True, exist_ok=True)

        files = sorted(
            path for path in self.settings.uploads.iterdir() if path.is_file() or path.is_symlink()
        )
        summary = ProcessingSummary(discovered=len(files))
        for path in files:
            try:
                self._process_file(path, summary)
            except OSError:
                LOGGER.exception("Filesystem operation failed while processing %s", path.name)
                summary.failed += 1
        return summary

    def _process_file(self, path: Path, summary: ProcessingSummary) -> None:
        if path.is_symlink():
            self._quarantine(path, "symlink")
            summary.quarantined += 1
            return

        extension = path.suffix.lower()
        if extension in INCOMPLETE_EXTENSIONS:
            LOGGER.warning("Leaving incomplete download untouched: %s", path.name)
            summary.deferred += 1
            return
        if not self._is_stable(path):
            LOGGER.info("Deferring file that is still changing: %s", path.name)
            summary.deferred += 1
            return
        if extension in SIDECAR_EXTENSIONS:
            self._remove_sidecar(path)
            summary.sidecars_removed += 1
            return
        if extension not in SUPPORTED_EXTENSIONS:
            self._quarantine(path, "unsupported")
            summary.quarantined += 1
            return

        current = read_tags(path)
        artist = normalise_artist_case(current.artist.strip())
        album_artist = current.album_artist.strip() or primary_artist(artist)
        source_title = current.source_title or current.title or self._filename_title(path)
        LOGGER.info(
            "Read metadata for %s: artist=%r albumartist=%r album=%r title=%r",
            path.name,
            artist,
            album_artist,
            current.album,
            current.title,
        )

        if artist and current.album:
            tags = Tags(
                artist=artist,
                album_artist=album_artist or artist,
                album=clean_album(current.album),
                title=clean_title(current.title or source_title, artist),
                source_title=source_title,
                match_source=current.match_source or "existing-tags",
                confidence=current.confidence or 1.0,
                recording_id=current.recording_id,
                release_group_id=current.release_group_id,
                acoustid_id=current.acoustid_id,
            )
            self._finish_import(path, tags, summary)
            return

        cleaned_source_title = clean_title(source_title, artist)
        fingerprint = self._fingerprint(path, artist, cleaned_source_title)
        if fingerprint.artist or fingerprint.title:
            final_artist = fingerprint.artist or artist
            if artist and fingerprint.artist and artists_match(artist, fingerprint.artist):
                final_artist = artist
            final_artist = normalise_artist_case(final_artist)
            final_album_artist = (
                fingerprint.album_artist or album_artist or primary_artist(final_artist)
            )
            final_title = merge_version_title(
                fingerprint.title or cleaned_source_title,
                cleaned_source_title,
            )
            album = (
                self.musicbrainz.find_earliest_studio_album(
                    final_album_artist,
                    canonical_song_title(final_title),
                )
                or fingerprint.album
            )
            tags = Tags(
                artist=final_artist,
                album_artist=final_album_artist or final_artist,
                album=album,
                title=final_title,
                source_title=source_title,
                match_source="acoustid",
                confidence=fingerprint.score,
                recording_id=fingerprint.recording_id,
                release_group_id=fingerprint.release_group_id,
                acoustid_id=fingerprint.acoustid_id,
            )
            self._finish_import(path, tags, summary)
            return

        guessed_artist, guessed_title = self._guess_from_filename(
            path,
            artist,
            current.title,
        )
        if not guessed_artist and not guessed_title:
            self._quarantine(path, "unidentified")
            summary.quarantined += 1
            return

        guessed_album = ""
        lookup_artist = album_artist or primary_artist(guessed_artist)
        if lookup_artist and guessed_title:
            guessed_album = self.musicbrainz.find_earliest_studio_album(
                lookup_artist,
                canonical_song_title(guessed_title),
            )
            if not guessed_album and audio_duration(path) >= 20 * 60:
                guessed_album = self.musicbrainz.find_studio_album_release(
                    lookup_artist,
                    guessed_title,
                )
        tags = Tags(
            artist=guessed_artist,
            album_artist=lookup_artist or guessed_artist,
            album=guessed_album,
            title=guessed_title,
            source_title=source_title,
            match_source="filename",
            confidence=0.25,
        )
        self._finish_import(path, tags, summary)

    def _fingerprint(self, path: Path, artist: str, title: str) -> FingerprintResult:
        if self.acoustid is None:
            LOGGER.info("Skipping AcoustID lookup because ACOUSTID_API_KEY is not set")
            return FingerprintResult()
        return self.acoustid.fingerprint(
            path,
            expected_artist=artist,
            expected_title=canonical_song_title(title),
        )

    def _finish_import(
        self,
        path: Path,
        tags: Tags,
        summary: ProcessingSummary,
    ) -> None:
        final_tags = Tags(
            artist=tags.artist or "Unknown Artist",
            album_artist=tags.album_artist or tags.artist or "Unknown Artist",
            title=tags.title or path.stem,
            album=clean_album(tags.album) or self.settings.fallback_album,
            source_title=tags.source_title,
            match_source=tags.match_source,
            confidence=tags.confidence,
            recording_id=tags.recording_id,
            release_group_id=tags.release_group_id,
            acoustid_id=tags.acoustid_id,
        )
        destination = self._library_destination(path, final_tags)

        if self.settings.dry_run:
            LOGGER.info("Dry run: would import %s to %s", path, destination)
            summary.imported += 1
            return

        try:
            write_tags(path, final_tags)
        except TaggingError as error:
            LOGGER.error("%s", error)
            self._quarantine(path, "tagging-error")
            summary.failed += 1
            return

        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), destination)
        try:
            self._record_decision(path, destination, final_tags)
        except OSError:
            LOGGER.exception("Could not append import decision for %s", destination)
        LOGGER.info(
            "Imported %s using %s metadata (confidence %.3f)",
            destination,
            final_tags.match_source,
            final_tags.confidence,
        )
        summary.imported += 1

    def _library_destination(self, path: Path, tags: Tags) -> Path:
        album_artist = safe_name(tags.album_artist or tags.artist, "Unknown Artist")
        album = safe_name(tags.album, self.settings.fallback_album)
        title = safe_name(tags.title, path.stem)
        return self._available_path(
            self.settings.library / album_artist / album / f"{title}{path.suffix.lower()}"
        )

    def _remove_sidecar(self, path: Path) -> None:
        if self.settings.dry_run:
            LOGGER.info("Dry run: would remove completed-download sidecar %s", path)
            return
        path.unlink()
        LOGGER.info("Removed completed-download sidecar %s", path.name)

    def _quarantine(self, path: Path, reason: str) -> None:
        destination = self._available_path(self.settings.quarantine / reason / path.name)
        if self.settings.dry_run:
            LOGGER.info("Dry run: would quarantine %s as %s", path, destination)
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), destination)
        LOGGER.warning("Quarantined %s as %s", path.name, destination)

    def _record_decision(self, source: Path, destination: Path, tags: Tags) -> None:
        if self.settings.decision_log is None:
            return
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "source": source.name,
            "destination": str(destination),
            "metadata": asdict(tags),
        }
        with self.settings.decision_log.open("a", encoding="utf-8") as output:
            output.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    @staticmethod
    def _available_path(path: Path) -> Path:
        if not path.exists():
            return path
        counter = 2
        while True:
            candidate = path.with_name(f"{path.stem} ({counter}){path.suffix}")
            if not candidate.exists():
                return candidate
            counter += 1

    def _is_stable(self, path: Path) -> bool:
        try:
            first_size = path.stat().st_size
            time.sleep(self.settings.stability_wait)
            second_size = path.stat().st_size
            return first_size > 0 and first_size == second_size
        except OSError:
            return False

    @staticmethod
    def _filename_title(path: Path) -> str:
        return split_upload_filename(path.stem)[1]

    @staticmethod
    def _guess_from_filename(path: Path, artist: str, title: str) -> tuple[str, str]:
        guessed_artist, guessed_title = split_upload_filename(path.stem)
        final_artist = artist or normalise_artist_case(guessed_artist)
        raw_title = title or guessed_title
        return final_artist, clean_title(raw_title, final_artist)
