"""Music upload processing workflow."""

from __future__ import annotations

import errno
import json
import logging
import os
import re
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from music_processor.clients import AcoustIDClient, FingerprintResult, MusicBrainzClient
from music_processor.config import Settings
from music_processor.fingerprint import acoustic_content_digest
from music_processor.naming import (
    artists_match,
    canonical_song_title,
    clean_album,
    clean_title,
    merge_version_title,
    normalise_artist_case,
    normalise_filename_artist_case,
    prefer_filename_artist,
    preferred_artist_name,
    primary_artist,
    release_lookup_title,
    safe_name,
    split_upload_filename,
)
from music_processor.source_registry import SourceRecord, SourceRegistry
from music_processor.tags import (
    SUPPORTED_EXTENSIONS,
    TaggingError,
    Tags,
    audio_chapter_count,
    audio_duration,
    read_tags,
    write_tags,
)

LOGGER = logging.getLogger(__name__)
SIDECAR_EXTENSIONS = {".webp", ".jpg", ".jpeg", ".png"}
INCOMPLETE_EXTENSIONS = {".part", ".ytdl", ".tmp"}
RELEASE_UPLOAD_PATTERN = re.compile(
    r"\b(?:full|complete)\s+(?:album|ep)\b|\balbum\s+stream\b",
    re.IGNORECASE,
)


@dataclass(slots=True)
class ProcessingSummary:
    discovered: int = 0
    imported: int = 0
    sidecars_removed: int = 0
    quarantined: int = 0
    deferred: int = 0
    failed: int = 0
    duplicates_removed: int = 0
    sources_updated: int = 0


@dataclass(frozen=True, slots=True)
class ResolutionContext:
    current: Tags
    artist: str
    album_artist: str
    source_title: str
    guessed_artist: str
    guessed_title: str
    filename_artist: str
    filename_title: str
    release_title: str
    chapter_count: int
    is_release_upload: bool


@dataclass(frozen=True, slots=True)
class SourceComparison:
    existing: Path | None = None
    incoming_digest: str = ""
    result: Literal["none", "same", "different", "unverified"] = "none"


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
        self.source_registry = SourceRegistry(settings.source_db)

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

        self._process_audio(path, summary)

    def _process_audio(self, path: Path, summary: ProcessingSummary) -> None:
        context = self._resolution_context(path)
        LOGGER.info(
            "Read metadata for %s: artist=%r albumartist=%r album=%r title=%r",
            path.name,
            context.artist,
            context.album_artist,
            context.current.album,
            context.current.title,
        )
        tags = self._resolve_tags(path, context)
        if tags is None:
            LOGGER.info(
                "Deferring file pending metadata approval or a reliable match: %s",
                path.name,
            )
            summary.deferred += 1
            return
        self._finish_import(path, tags, summary)

    def _resolution_context(self, path: Path) -> ResolutionContext:
        current = read_tags(path)
        tagged_artist = normalise_artist_case(current.artist.strip())
        artist = tagged_artist
        if not current.album:
            artist = prefer_filename_artist(path.stem, tagged_artist)
        album_artist = current.album_artist.strip() or primary_artist(artist)
        if (
            current.album_artist
            and tagged_artist
            and artists_match(current.album_artist, tagged_artist)
            and not artists_match(current.album_artist, artist)
        ):
            album_artist = primary_artist(artist)
        source_title = current.source_title or current.title or self._filename_title(path)
        guessed_artist, guessed_title = self._guess_from_filename(
            path,
            artist,
            current.title,
        )
        filename_artist, filename_title = split_upload_filename(path.stem)
        filename_artist = normalise_filename_artist_case(filename_artist)
        filename_title = clean_title(filename_title, filename_artist)
        release_title = release_lookup_title(guessed_title, guessed_artist)
        duration = audio_duration(path)
        chapter_count = audio_chapter_count(path)
        is_release_upload = (
            duration >= 20 * 60
            or chapter_count > 1
            or release_title != guessed_title
            or bool(RELEASE_UPLOAD_PATTERN.search(source_title))
        )
        return ResolutionContext(
            current=current,
            artist=artist,
            album_artist=album_artist,
            source_title=source_title,
            guessed_artist=guessed_artist,
            guessed_title=guessed_title,
            filename_artist=filename_artist,
            filename_title=filename_title,
            release_title=release_title,
            chapter_count=chapter_count,
            is_release_upload=is_release_upload,
        )

    def _resolve_tags(self, path: Path, context: ResolutionContext) -> Tags | None:
        if context.current.approved:
            if not context.current.artist.strip() or not context.current.title.strip():
                LOGGER.warning(
                    "Approval marker found but Artist or Title is missing; deferring %s",
                    path.name,
                )
                return None
            LOGGER.info("Using manually approved metadata for %s", path.name)
            return self._approved_tags(context)

        cleaned_source_title = clean_title(context.source_title, context.artist)
        if context.is_release_upload:
            LOGGER.info("Skipping single-recording fingerprint for release upload %s", path.name)
            return None

        alternate_artists = (
            (context.filename_artist,)
            if context.filename_artist
            and not artists_match(context.artist, context.filename_artist)
            else ()
        )
        fingerprint = self._fingerprint(
            path,
            context.artist,
            cleaned_source_title,
            alternate_artists,
        )

        if (
            fingerprint.artist
            and fingerprint.title
            and fingerprint.score >= 0.90
        ):
            return self._fingerprint_tags(context, fingerprint, cleaned_source_title)

        LOGGER.info(
            "Deferring %s: no sufficiently reliable metadata match (confidence %.3f)",
            path.name,
            fingerprint.score,
        )
        return None

    @staticmethod
    def _approved_tags(context: ResolutionContext) -> Tags:
        current = context.current
        artist = current.artist.strip()
        title = current.title.strip()

        return Tags(
            artist=artist,
            album_artist=current.album_artist.strip() or primary_artist(artist),
            album=clean_album(current.album),
            title=title,
            source_title=current.source_title or title,
            match_source=current.match_source or "manual-approval",
            confidence=current.confidence or 1.0,
            recording_id=current.recording_id,
            release_group_id=current.release_group_id,
            acoustid_id=current.acoustid_id,
            source_url=current.source_url,
            artist_source=current.artist_source or "manual-approval",
            album_artist_source=current.album_artist_source or "manual-approval",
            album_source=current.album_source or "manual-approval",
            title_source=current.title_source or "manual-approval",
            approved=True,
        )

    @staticmethod
    def _existing_tags(context: ResolutionContext) -> Tags:
        current = context.current
        return Tags(
            artist=context.artist,
            album_artist=context.album_artist or context.artist,
            album=clean_album(current.album),
            title=clean_title(current.title or context.source_title, context.artist),
            source_title=context.source_title,
            match_source=current.match_source or "existing-tags",
            confidence=current.confidence or 1.0,
            recording_id=current.recording_id,
            release_group_id=current.release_group_id,
            acoustid_id=current.acoustid_id,
            source_url=current.source_url,
            artist_source=current.artist_source or "existing-tags",
            album_artist_source=current.album_artist_source or "existing-tags",
            album_source=current.album_source or "existing-tags",
            title_source=current.title_source or "existing-tags",
            approved=current.approved,
        )

    def _fingerprint_tags(
        self,
        context: ResolutionContext,
        fingerprint: FingerprintResult,
        cleaned_source_title: str,
    ) -> Tags:
        final_artist = preferred_artist_name(context.artist, fingerprint.artist)
        if fingerprint.album_artist and not artists_match(
            fingerprint.album_artist,
            final_artist,
        ):
            final_album_artist = fingerprint.album_artist
            album_artist_source = "acoustid"
        else:
            final_album_artist = primary_artist(final_artist)
            album_artist_source = "derived-artist"
        final_title = merge_version_title(
            fingerprint.title or cleaned_source_title,
            cleaned_source_title,
        )
        album = self.musicbrainz.find_earliest_studio_album(
            final_album_artist,
            canonical_song_title(final_title),
        )
        album_source = "musicbrainz" if album else ""
        artist_source = "source+acoustid" if context.artist else "acoustid"
        if album:
            canonical_artist = self._canonical_artist(final_album_artist)
            original_artist = final_artist
            original_album_artist = final_album_artist
            if artists_match(final_artist, final_album_artist):
                final_artist = preferred_artist_name(final_artist, canonical_artist)
            final_album_artist = canonical_artist
            if final_artist != original_artist:
                artist_source += "+musicbrainz"
            if final_album_artist != original_album_artist:
                album_artist_source += "+musicbrainz"
        if not album and fingerprint.album:
            album = fingerprint.album
            album_source = "acoustid-release"
        return Tags(
            artist=final_artist,
            album_artist=final_album_artist or final_artist,
            album=album,
            title=final_title,
            source_title=context.source_title,
            match_source="acoustid",
            confidence=fingerprint.score,
            recording_id=fingerprint.recording_id,
            release_group_id=fingerprint.release_group_id,
            acoustid_id=fingerprint.acoustid_id,
            source_url=context.current.source_url,
            artist_source=artist_source,
            album_artist_source=album_artist_source,
            album_source=album_source,
            title_source=("acoustid+source-version" if fingerprint.title else "source-title"),
        )

    def _filename_tags(self, context: ResolutionContext) -> Tags | None:
        if not context.guessed_artist and not context.guessed_title:
            return None
        alternate = self._alternate_filename_tags(context)
        if alternate is not None:
            return alternate
        lookup_artist = context.album_artist or primary_artist(context.guessed_artist)
        guessed_album, album_source = self._filename_album(context, lookup_artist)
        final_artist = context.guessed_artist
        final_album_artist = lookup_artist or final_artist
        artist_source = (
            "existing-tags"
            if context.current.artist
            and artists_match(context.guessed_artist, context.current.artist)
            else "filename"
        )
        if album_source.startswith("musicbrainz"):
            canonical_artist = self._canonical_artist(final_album_artist)
            original_artist = final_artist
            if artists_match(final_artist, final_album_artist):
                final_artist = preferred_artist_name(final_artist, canonical_artist)
            final_album_artist = canonical_artist
            if final_artist != original_artist:
                artist_source += "+musicbrainz"
        return Tags(
            artist=final_artist,
            album_artist=final_album_artist,
            album=guessed_album,
            title=context.guessed_title,
            source_title=context.source_title,
            match_source="filename",
            confidence=0.25,
            source_url=context.current.source_url,
            artist_source=artist_source,
            album_artist_source=(
                "existing-tags" if context.current.album_artist else "derived-artist"
            ),
            album_source=album_source,
            title_source="existing-tags" if context.current.title else "filename",
        )

    def _alternate_filename_tags(self, context: ResolutionContext) -> Tags | None:
        artist = context.filename_artist
        title = context.filename_title
        if not artist or not title or artists_match(artist, context.guessed_artist):
            return None
        if context.is_release_upload:
            release_title = release_lookup_title(title, artist)
            album = self.musicbrainz.find_studio_album_release(artist, release_title)
            album_source = "musicbrainz-release"
        else:
            release_title = title
            album = self.musicbrainz.find_earliest_studio_album(
                artist,
                canonical_song_title(title),
            )
            album_source = "musicbrainz"
        if not album:
            return None
        if release_title != title and artists_match(album, artist):
            album = clean_album(release_title)
        artist = self._canonical_artist(artist)
        return Tags(
            artist=artist,
            album_artist=primary_artist(artist),
            album=album,
            title=title,
            source_title=context.source_title,
            match_source="filename",
            confidence=0.5,
            source_url=context.current.source_url,
            artist_source=f"filename+{album_source}",
            album_artist_source="derived-artist",
            album_source=album_source,
            title_source="filename",
        )

    def _canonical_artist(self, artist: str) -> str:
        canonical = self.musicbrainz.canonical_artist_name(artist)
        return preferred_artist_name(artist, canonical) if canonical else artist

    def _filename_album(
        self,
        context: ResolutionContext,
        lookup_artist: str,
    ) -> tuple[str, str]:
        guessed_album = ""
        album_source = ""
        if lookup_artist and context.guessed_title:
            if context.is_release_upload:
                guessed_album = self.musicbrainz.find_studio_album_release(
                    lookup_artist,
                    context.release_title,
                )
                if guessed_album:
                    album_source = "musicbrainz-release"
            if context.release_title != context.guessed_title and (
                not guessed_album or artists_match(guessed_album, context.guessed_artist)
            ):
                guessed_album = clean_album(context.release_title)
                album_source = "filename-self-titled"
            if not guessed_album and context.chapter_count > 1:
                guessed_album = clean_album(context.guessed_title)
                album_source = "filename-release"
            if not guessed_album:
                guessed_album = self.musicbrainz.find_earliest_studio_album(
                    lookup_artist,
                    canonical_song_title(context.guessed_title),
                )
                if guessed_album:
                    album_source = "musicbrainz"
        return guessed_album, album_source

    def _fingerprint(
        self,
        path: Path,
        artist: str,
        title: str,
        alternate_artists: tuple[str, ...] = (),
    ) -> FingerprintResult:
        if self.acoustid is None:
            LOGGER.info("Skipping AcoustID lookup because ACOUSTID_API_KEY is not set")
            return FingerprintResult()
        return self.acoustid.fingerprint(
            path,
            expected_artist=artist,
            expected_title=canonical_song_title(title),
            alternate_artists=alternate_artists,
        )

    def _finish_import(
        self,
        path: Path,
        tags: Tags,
        summary: ProcessingSummary,
    ) -> None:
        final_tags = self._final_tags(path, tags)
        base_destination = self._base_library_destination(path, final_tags)
        comparison = self._compare_source(path, base_destination, final_tags.source_url)
        if comparison.result == "same" and comparison.existing is not None:
            self._handle_matching_source(
                path,
                comparison.existing,
                base_destination,
                final_tags,
                comparison.incoming_digest,
                summary,
            )
            return

        register_source = comparison.result in {"none", "same"}
        action = "imported"
        if comparison.result in {"different", "unverified"}:
            register_source = False
            action = f"source-content-{comparison.result}"
            LOGGER.warning(
                "Retaining %s because source identity matches %s but audio equality is %s",
                path.name,
                comparison.existing,
                "not confirmed" if comparison.result == "unverified" else "different",
            )
        self._import_new(
            path,
            base_destination,
            final_tags,
            summary,
            content_digest=comparison.incoming_digest,
            register_source=register_source,
            action=action,
        )

    def _final_tags(self, path: Path, tags: Tags) -> Tags:
        return Tags(
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
            source_url=tags.source_url,
            artist_source=tags.artist_source or "fallback",
            album_artist_source=tags.album_artist_source or "derived-artist",
            album_source=tags.album_source or "fallback",
            title_source=tags.title_source or "fallback",
            approved=tags.approved,
        )

    def _compare_source(
        self,
        path: Path,
        base_destination: Path,
        source_url: str,
    ) -> SourceComparison:
        registered = self.source_registry.lookup(source_url)
        existing = self._registered_path(registered) or self._matching_source_destination(
            base_destination,
            source_url,
        )
        if existing is None:
            return SourceComparison()
        incoming_digest = acoustic_content_digest(path)
        existing_digest = (
            registered.content_digest
            if registered is not None and registered.path == existing
            else ""
        ) or acoustic_content_digest(existing)
        if not incoming_digest or not existing_digest:
            return SourceComparison(existing, incoming_digest, "unverified")
        result: Literal["same", "different"] = (
            "same" if incoming_digest == existing_digest else "different"
        )
        return SourceComparison(existing, incoming_digest, result)

    def _import_new(
        self,
        path: Path,
        base_destination: Path,
        final_tags: Tags,
        summary: ProcessingSummary,
        *,
        content_digest: str,
        register_source: bool,
        action: str,
    ) -> None:
        destination = self._available_path(base_destination)

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
        self._move_file(path, destination)
        if register_source and final_tags.source_url:
            self.source_registry.register(final_tags.source_url, destination, content_digest)
        try:
            self._record_decision(path, destination, final_tags, action=action)
        except OSError:
            LOGGER.exception("Could not append import decision for %s", destination)
        LOGGER.info(
            "Imported %s using %s metadata (confidence %.3f)",
            destination,
            final_tags.match_source,
            final_tags.confidence,
        )
        summary.imported += 1

    def _registered_path(self, record: SourceRecord | None) -> Path | None:
        if record is None or record.path.is_symlink() or not record.path.is_file():
            return None
        try:
            record.path.resolve().relative_to(self.settings.library.resolve())
        except (OSError, ValueError):
            LOGGER.warning("Ignoring source registry path outside the library: %s", record.path)
            return None
        return record.path

    def _handle_matching_source(
        self,
        path: Path,
        existing: Path,
        base_destination: Path,
        tags: Tags,
        content_digest: str,
        summary: ProcessingSummary,
    ) -> None:
        existing_tags = read_tags(existing)
        metadata_matches = self._resolved_metadata_matches(existing_tags, tags)
        if metadata_matches and existing == base_destination:
            if self.settings.dry_run:
                LOGGER.info(
                    "Dry run: would remove duplicate %s already imported as %s",
                    path,
                    existing,
                )
            else:
                path.unlink()
                self.source_registry.register(tags.source_url, existing, content_digest)
                self._safe_record_decision(path, existing, tags, action="duplicate-removed")
                LOGGER.info(
                    "Removed duplicate download %s already imported as %s",
                    path.name,
                    existing,
                )
            summary.duplicates_removed += 1
            return

        destination = base_destination
        if destination.exists() and destination != existing:
            destination = self._available_path(destination)
        if self.settings.dry_run:
            LOGGER.info(
                "Dry run: would update source %s from %s to %s",
                path.name,
                existing,
                destination,
            )
            summary.sources_updated += 1
            return
        try:
            write_tags(path, tags)
        except TaggingError as error:
            LOGGER.error("%s", error)
            self._quarantine(path, "tagging-error")
            summary.failed += 1
            return

        destination.parent.mkdir(parents=True, exist_ok=True)
        self._move_file(path, destination, replace=destination == existing)
        if existing != destination:
            existing.unlink()
        self.source_registry.register(tags.source_url, destination, content_digest)
        self._safe_record_decision(path, destination, tags, action="source-updated")
        LOGGER.info("Updated source %s at %s", tags.source_url, destination)
        summary.sources_updated += 1

    @staticmethod
    def _resolved_metadata_matches(existing: Tags, resolved: Tags) -> bool:
        return (
            existing.artist == resolved.artist
            and existing.album_artist == resolved.album_artist
            and existing.album == resolved.album
            and existing.title == resolved.title
        )

    def _base_library_destination(self, path: Path, tags: Tags) -> Path:
        album_artist = safe_name(tags.album_artist or tags.artist, "Unknown Artist")
        album = safe_name(tags.album, self.settings.fallback_album)
        title = safe_name(tags.title, path.stem)
        return self.settings.library / album_artist / album / f"{title}{path.suffix.lower()}"

    def _matching_source_destination(self, path: Path, source_url: str) -> Path | None:
        if not source_url or not path.parent.is_dir():
            return None
        numbered = re.compile(rf"^{re.escape(path.stem)} \([0-9]+\)$")
        for candidate in path.parent.iterdir():
            if not candidate.is_file() or candidate.suffix.casefold() != path.suffix.casefold():
                continue
            if candidate.stem != path.stem and not numbered.fullmatch(candidate.stem):
                continue
            if read_tags(candidate).source_url == source_url:
                return candidate
        return None

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
        self._move_file(path, destination)
        LOGGER.warning("Quarantined %s as %s", path.name, destination)

    def _record_decision(
        self,
        source: Path,
        destination: Path,
        tags: Tags,
        *,
        action: str = "imported",
    ) -> None:
        if self.settings.decision_log is None:
            return
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "source": source.name,
            "destination": str(destination),
            "action": action,
            "metadata": asdict(tags),
        }
        with self.settings.decision_log.open("a", encoding="utf-8") as output:
            output.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    def _safe_record_decision(
        self,
        source: Path,
        destination: Path,
        tags: Tags,
        *,
        action: str,
    ) -> None:
        try:
            self._record_decision(source, destination, tags, action=action)
        except OSError:
            LOGGER.exception("Could not append %s decision for %s", action, destination)

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

    @staticmethod
    def _move_file(source: Path, destination: Path, *, replace: bool = False) -> None:
        operation = os.replace if replace else os.rename
        try:
            operation(source, destination)
            return
        except OSError as error:
            if error.errno != errno.EXDEV:
                raise

        if source.is_symlink():
            link_target = os.readlink(source)
            if replace:
                descriptor, temporary_name = tempfile.mkstemp(
                    prefix=f".{destination.name}.",
                    suffix=".tmp",
                    dir=destination.parent,
                )
                os.close(descriptor)
                temporary = Path(temporary_name)
                temporary.unlink()
                try:
                    os.symlink(link_target, temporary)
                    os.replace(temporary, destination)
                except BaseException:
                    temporary.unlink(missing_ok=True)
                    raise
            else:
                os.symlink(link_target, destination)
            source.unlink()
            return

        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".tmp",
            dir=destination.parent,
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as output, source.open("rb") as input_file:
                shutil.copyfileobj(input_file, output)
                output.flush()
                os.fsync(output.fileno())
            shutil.copystat(source, temporary)
            if replace:
                os.replace(temporary, destination)
            else:
                os.link(temporary, destination)
                temporary.unlink()
            source.unlink()
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise

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
