import json
from dataclasses import replace
from pathlib import Path

import pytest

from music_processor.clients import FingerprintResult
from music_processor.config import Settings
from music_processor.processor import MusicProcessor
from music_processor.tags import TaggingError, Tags


class FakeMusicBrainz:
    def __init__(self, album: str = "") -> None:
        self.album = album
        self.calls: list[tuple[str, str]] = []
        self.release_calls: list[tuple[str, str]] = []

    def find_earliest_studio_album(self, artist: str, title: str) -> str:
        self.calls.append((artist, title))
        return self.album

    def find_studio_album_release(self, artist: str, title: str) -> str:
        self.release_calls.append((artist, title))
        return ""


class FakeAcoustID:
    def fingerprint(
        self,
        path: Path,
        expected_artist: str = "",
        expected_title: str = "",
    ) -> FingerprintResult:
        return FingerprintResult()


def make_processor(tmp_path: Path, *, dry_run: bool = False) -> MusicProcessor:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    settings = Settings(
        uploads=uploads,
        library=tmp_path / "library",
        quarantine=tmp_path / "quarantine",
        lock_file=tmp_path / "processor.lock",
        acoustid_api_key=None,
        musicbrainz_contact="https://example.com",
        stability_wait=0,
        dry_run=dry_run,
    )
    return MusicProcessor(settings, FakeMusicBrainz(), FakeAcoustID())  # type: ignore[arg-type]


def test_completed_download_sidecar_is_deleted(tmp_path: Path) -> None:
    processor = make_processor(tmp_path)
    uploaded = processor.settings.uploads / "cover.jpg"
    uploaded.write_bytes(b"image")

    summary = processor.process_pending()

    assert summary.sidecars_removed == 1
    assert not uploaded.exists()
    assert not any(processor.settings.quarantine.iterdir())


def test_dry_run_does_not_move_non_audio_file(tmp_path: Path) -> None:
    processor = make_processor(tmp_path, dry_run=True)
    uploaded = processor.settings.uploads / "cover.jpg"
    uploaded.write_bytes(b"image")

    processor.process_pending()

    assert uploaded.exists()
    assert not processor.settings.quarantine.exists()


def test_incomplete_download_is_never_deleted_or_quarantined(tmp_path: Path) -> None:
    processor = make_processor(tmp_path)
    uploaded = processor.settings.uploads / "song.webm.part"
    uploaded.write_bytes(b"partial")

    summary = processor.process_pending()

    assert summary.deferred == 1
    assert uploaded.read_bytes() == b"partial"
    assert not any(processor.settings.quarantine.iterdir())


def test_symlink_is_quarantined_without_moving_target(tmp_path: Path) -> None:
    processor = make_processor(tmp_path)
    target = tmp_path / "outside.mp3"
    target.write_bytes(b"audio")
    uploaded = processor.settings.uploads / "linked.mp3"
    uploaded.symlink_to(target)

    summary = processor.process_pending()

    assert summary.quarantined == 1
    assert target.read_bytes() == b"audio"
    quarantined = processor.settings.quarantine / "symlink" / "linked.mp3"
    assert quarantined.is_symlink()
    assert quarantined.resolve() == target


def test_import_uses_collision_safe_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    processor = make_processor(tmp_path)
    uploaded = processor.settings.uploads / "song.mp3"
    uploaded.write_bytes(b"audio")
    existing = processor.settings.library / "Artist" / "Album" / "Title.mp3"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"existing")
    monkeypatch.setattr(
        "music_processor.processor.read_tags",
        lambda path: Tags(artist="Artist", album="Album", title="Title"),
    )
    monkeypatch.setattr("music_processor.processor.write_tags", lambda path, tags: None)

    summary = processor.process_pending()

    assert summary.imported == 1
    assert existing.read_bytes() == b"existing"
    assert (existing.parent / "Title (2).mp3").read_bytes() == b"audio"


def test_tagging_failure_moves_file_to_quarantine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    processor = make_processor(tmp_path)
    uploaded = processor.settings.uploads / "song.mp3"
    uploaded.write_bytes(b"audio")
    monkeypatch.setattr(
        "music_processor.processor.read_tags",
        lambda path: Tags(artist="Artist", album="Album", title="Title"),
    )

    def fail_to_write(path: Path, tags: Tags) -> None:
        raise TaggingError("broken")

    monkeypatch.setattr("music_processor.processor.write_tags", fail_to_write)

    summary = processor.process_pending()

    assert summary.failed == 1
    assert (processor.settings.quarantine / "tagging-error" / "song.mp3").exists()


def test_tyler_the_creator_is_preserved_in_tags_and_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processor = make_processor(tmp_path)
    uploaded = processor.settings.uploads / "song.mp3"
    uploaded.write_bytes(b"audio")
    written: list[Tags] = []
    monkeypatch.setattr(
        "music_processor.processor.read_tags",
        lambda path: Tags(artist="Tyler, The Creator", album="IGOR", title="EARFQUAKE"),
    )
    monkeypatch.setattr(
        "music_processor.processor.write_tags",
        lambda path, tags: written.append(tags),
    )

    summary = processor.process_pending()

    destination = processor.settings.library / "Tyler, The Creator" / "IGOR" / "EARFQUAKE.mp3"
    assert summary.imported == 1
    assert written[0].artist == "Tyler, The Creator"
    assert destination.exists()


def test_live_version_uses_studio_album_without_losing_live_title(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    musicbrainz = FakeMusicBrainz(album="Pablo Honey")

    class LiveFingerprint:
        def fingerprint(
            self,
            path: Path,
            expected_artist: str = "",
            expected_title: str = "",
        ) -> FingerprintResult:
            assert expected_artist == "Radiohead"
            assert expected_title == "Creep"
            return FingerprintResult(
                artist="Radiohead",
                album_artist="Radiohead",
                title="Creep",
                recording_id="recording-id",
                score=0.94,
            )

    processor = make_processor(tmp_path)
    processor.musicbrainz = musicbrainz  # type: ignore[assignment]
    processor.acoustid = LiveFingerprint()  # type: ignore[assignment]
    uploaded = processor.settings.uploads / "Radiohead - Creep live.mp3"
    uploaded.write_bytes(b"audio")
    written: list[Tags] = []
    monkeypatch.setattr(
        "music_processor.processor.read_tags",
        lambda path: Tags(
            artist="Radiohead",
            title="Creep (Live at Glastonbury 1997) [HD]",
        ),
    )
    monkeypatch.setattr(
        "music_processor.processor.write_tags",
        lambda path, tags: written.append(tags),
    )

    summary = processor.process_pending()

    assert summary.imported == 1
    assert musicbrainz.calls == [("Radiohead", "Creep")]
    assert written[0].title == "Creep (Live at Glastonbury 1997)"
    assert written[0].album == "Pablo Honey"
    assert (
        processor.settings.library
        / "Radiohead"
        / "Pablo Honey"
        / "Creep (Live at Glastonbury 1997).mp3"
    ).exists()


def test_track_credit_and_album_artist_are_kept_separate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processor = make_processor(tmp_path)
    uploaded = processor.settings.uploads / "song.mp3"
    uploaded.write_bytes(b"audio")
    written: list[Tags] = []
    monkeypatch.setattr(
        "music_processor.processor.read_tags",
        lambda path: Tags(
            artist="Metallica feat. Marianne Faithfull",
            album_artist="Metallica",
            album="Reload",
            title="The Memory Remains",
        ),
    )
    monkeypatch.setattr(
        "music_processor.processor.write_tags",
        lambda path, tags: written.append(tags),
    )

    processor.process_pending()

    assert written[0].artist == "Metallica feat. Marianne Faithfull"
    assert written[0].album_artist == "Metallica"
    assert (processor.settings.library / "Metallica" / "Reload" / "The Memory Remains.mp3").exists()


def test_decision_log_records_metadata_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processor = make_processor(tmp_path)
    processor.settings = replace(
        processor.settings,
        decision_log=tmp_path / "state" / "decisions.jsonl",
    )
    uploaded = processor.settings.uploads / "song.mp3"
    uploaded.write_bytes(b"audio")
    monkeypatch.setattr(
        "music_processor.processor.read_tags",
        lambda path: Tags(artist="Artist", album="Album", title="Title"),
    )
    monkeypatch.setattr("music_processor.processor.write_tags", lambda path, tags: None)

    processor.process_pending()

    records = [
        json.loads(line)
        for line in processor.settings.decision_log.read_text(encoding="utf-8").splitlines()
    ]
    assert records[0]["metadata"]["match_source"] == "existing-tags"
    assert records[0]["metadata"]["album_artist"] == "Artist"


def test_long_album_upload_uses_title_artist_and_release_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class AlbumMusicBrainz(FakeMusicBrainz):
        def find_studio_album_release(self, artist: str, title: str) -> str:
            self.release_calls.append((artist, title))
            return "Hot Dogma"

    musicbrainz = AlbumMusicBrainz()
    processor = make_processor(tmp_path)
    processor.musicbrainz = musicbrainz  # type: ignore[assignment]
    uploaded = processor.settings.uploads / "WelshTISMFan - TISM - Hot Dogma (1990).mp3"
    uploaded.write_bytes(b"audio")
    written: list[Tags] = []
    monkeypatch.setattr("music_processor.processor.read_tags", lambda path: Tags())
    monkeypatch.setattr("music_processor.processor.audio_duration", lambda path: 3600.0)
    monkeypatch.setattr(
        "music_processor.processor.write_tags",
        lambda path, tags: written.append(tags),
    )

    processor.process_pending()

    assert musicbrainz.calls == [("TISM", "Hot Dogma (1990)")]
    assert musicbrainz.release_calls == [("TISM", "Hot Dogma (1990)")]
    assert written[0].artist == "TISM"
    assert written[0].album == "Hot Dogma"
    assert (processor.settings.library / "TISM" / "Hot Dogma" / "Hot Dogma (1990).mp3").exists()
