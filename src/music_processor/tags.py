"""Audio metadata access."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from mutagen import File as MutagenFile
from mutagen.id3 import TALB, TIT2, TPE1, TPE2, TXXX

LOGGER = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".mp3"}


@dataclass(frozen=True, slots=True)
class Tags:
    artist: str = ""
    album: str = ""
    title: str = ""
    album_artist: str = ""
    source_title: str = ""
    match_source: str = ""
    confidence: float = 0.0
    recording_id: str = ""
    release_group_id: str = ""
    acoustid_id: str = ""
    source_url: str = ""
    artist_source: str = ""
    album_artist_source: str = ""
    album_source: str = ""
    title_source: str = ""
    approved: bool = False


class TaggingError(RuntimeError):
    pass


def read_tags(path: Path) -> Tags:
    try:
        if path.suffix.lower() in {".mp3", ".wav"}:
            return _read_id3_tags(path)
        audio = MutagenFile(path, easy=True)
        if audio is None:
            return Tags()
        return Tags(
            artist=_first_value(audio.get("artist")),
            album=_first_value(audio.get("album")),
            title=_first_value(audio.get("title")),
            album_artist=_first_value(audio.get("albumartist")),
        )
    except Exception as error:
        LOGGER.warning("Could not read metadata from %s: %s", path.name, error)
        return Tags()


def _read_id3_tags(path: Path) -> Tags:
    audio = MutagenFile(path)
    if audio is None or audio.tags is None:
        return Tags()
    return Tags(
        artist=_id3_value(audio.tags.get("TPE1")),
        album=_id3_value(audio.tags.get("TALB")),
        title=_id3_value(audio.tags.get("TIT2")),
        album_artist=_id3_value(audio.tags.get("TPE2")),
        source_title=_txxx_value(audio.tags, "Music Processor Source Title"),
        match_source=_txxx_value(audio.tags, "Music Processor Match Source"),
        confidence=_float_value(_txxx_value(audio.tags, "Music Processor Confidence")),
        recording_id=_txxx_value(audio.tags, "MusicBrainz Recording Id"),
        release_group_id=_txxx_value(audio.tags, "MusicBrainz Release Group Id"),
        acoustid_id=_txxx_value(audio.tags, "AcoustID Id"),
        source_url=(
            _txxx_value(audio.tags, "Music Processor Source URL") or _txxx_value(audio.tags, "purl")
        ),
        artist_source=_txxx_value(audio.tags, "Music Processor Artist Source"),
        album_artist_source=_txxx_value(audio.tags, "Music Processor Album Artist Source"),
        album_source=_txxx_value(audio.tags, "Music Processor Album Source"),
        title_source=_txxx_value(audio.tags, "Music Processor Title Source"),
        approved=(
            _txxx_value(audio.tags, "Music Processor Approved").casefold() == "yes"
        ),
    )


def write_tags(path: Path, tags: Tags) -> None:
    try:
        if path.suffix.lower() in {".mp3", ".wav"}:
            _write_id3_tags(path, tags)
        else:
            _write_easy_tags(path, tags)
    except Exception as error:
        raise TaggingError(f"could not write metadata to {path.name}: {error}") from error


def audio_duration(path: Path) -> float:
    try:
        audio = MutagenFile(path)
        return float(getattr(getattr(audio, "info", None), "length", 0.0))
    except Exception:
        return 0.0


def audio_chapter_count(path: Path) -> int:
    try:
        audio = MutagenFile(path)
        tags = getattr(audio, "tags", None)
        return sum(str(key).startswith("CHAP:") for key in tags or ())
    except Exception:
        return 0


def _write_id3_tags(path: Path, tags: Tags) -> None:
    audio = MutagenFile(path)
    if audio is None:
        raise TaggingError("unsupported audio container")
    if audio.tags is None:
        audio.add_tags()
    audio.tags.setall("TPE1", [TPE1(encoding=3, text=tags.artist)])
    audio.tags.setall("TIT2", [TIT2(encoding=3, text=tags.title)])
    audio.tags.setall("TALB", [TALB(encoding=3, text=tags.album)])
    audio.tags.setall("TPE2", [TPE2(encoding=3, text=tags.album_artist or tags.artist)])
    _set_txxx(audio.tags, "Music Processor Source Title", tags.source_title)
    _set_txxx(audio.tags, "Music Processor Match Source", tags.match_source)
    _set_txxx(
        audio.tags,
        "Music Processor Confidence",
        f"{tags.confidence:.3f}" if tags.confidence else "",
    )
    _set_txxx(audio.tags, "MusicBrainz Recording Id", tags.recording_id)
    _set_txxx(audio.tags, "MusicBrainz Release Group Id", tags.release_group_id)
    _set_txxx(audio.tags, "AcoustID Id", tags.acoustid_id)
    _set_txxx(audio.tags, "Music Processor Source URL", tags.source_url)
    _set_txxx(audio.tags, "Music Processor Artist Source", tags.artist_source)
    _set_txxx(audio.tags, "Music Processor Album Artist Source", tags.album_artist_source)
    _set_txxx(audio.tags, "Music Processor Album Source", tags.album_source)
    _set_txxx(audio.tags, "Music Processor Title Source", tags.title_source)
    _set_txxx(
        audio.tags,
        "Music Processor Approved",
        "yes" if tags.approved else "",
    )
    audio.save()


def _write_easy_tags(path: Path, tags: Tags) -> None:
    audio = MutagenFile(path, easy=True)
    if audio is None:
        raise TaggingError("unsupported audio container")
    if audio.tags is None:
        audio.add_tags()
    audio["artist"] = [tags.artist]
    audio["title"] = [tags.title]
    audio["album"] = [tags.album]
    audio["albumartist"] = [tags.album_artist or tags.artist]
    audio.save()


def _first_value(value: list[str] | str | None) -> str:
    if isinstance(value, list):
        return (value[0] if value else "").strip()
    return (value or "").strip()


def _id3_value(frame: object | None) -> str:
    values = getattr(frame, "text", None)
    if not values:
        return ""
    return str(values[0]).strip()


def _txxx_value(tags: object, description: str) -> str:
    getter = getattr(tags, "get", None)
    if getter is None:
        return ""
    return _id3_value(getter(f"TXXX:{description}"))


def _set_txxx(tags: object, description: str, value: str) -> None:
    setter = getattr(tags, "setall", None)
    if setter is None:
        return
    if not value:
        setter(f"TXXX:{description}", [])
        return
    setter(
        f"TXXX:{description}",
        [TXXX(encoding=3, desc=description, text=[value])],
    )


def _float_value(value: str) -> float:
    try:
        return float(value)
    except ValueError:
        return 0.0
