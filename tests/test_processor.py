import errno
import json
import os
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

    def canonical_artist_name(self, artist: str) -> str:
        return artist


class FakeAcoustID:
    def fingerprint(
        self,
        path: Path,
        expected_artist: str = "",
        expected_title: str = "",
        alternate_artists: tuple[str, ...] = (),
    ) -> FingerprintResult:
        return FingerprintResult()


def make_processor(
    tmp_path: Path,
    *,
    dry_run: bool = False,
    source_db: Path | None = None,
) -> MusicProcessor:
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    settings = Settings(
        uploads=uploads,
        library=tmp_path / "library",
        quarantine=tmp_path / "quarantine",
        lock_file=tmp_path / "processor.lock",
        acoustid_api_key=None,
        musicbrainz_contact="https://example.com",
        source_db=source_db,
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
        lambda path: Tags(artist="Artist", album="Album", title="Title", approved=True),
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
        lambda path: Tags(artist="Artist", album="Album", title="Title", approved=True),
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
        lambda path: Tags(artist="Tyler, The Creator", album="IGOR", title="EARFQUAKE", approved=True),
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
            alternate_artists: tuple[str, ...] = (),
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
    assert written[0].artist_source == "source+acoustid"
    assert written[0].album_source == "musicbrainz"
    assert written[0].title_source == "acoustid+source-version"
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
            approved=True,
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
        lambda path: Tags(artist="Artist", album="Album", title="Title", approved=True),
    )
    monkeypatch.setattr("music_processor.processor.write_tags", lambda path, tags: None)

    processor.process_pending()

    records = [
        json.loads(line)
        for line in processor.settings.decision_log.read_text(encoding="utf-8").splitlines()
    ]
    assert records[0]["metadata"]["match_source"] == "manual-approval"
    assert records[0]["metadata"]["album_artist"] == "Artist"
    assert records[0]["metadata"]["artist_source"] == "manual-approval"
    assert records[0]["metadata"]["album_source"] == "manual-approval"


def test_long_album_upload_is_deferred_for_manual_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    musicbrainz = FakeMusicBrainz()
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

    summary = processor.process_pending()

    assert summary.deferred == 0
    assert summary.imported == 1
    assert musicbrainz.calls == []
    assert musicbrainz.release_calls == []
    assert len(written) == 1
    assert written[0].review_status == "pending"
    assert written[0].review_reason

    assert not uploaded.exists()
    assert list(processor.settings.library.rglob("*.mp3"))


def test_title_artist_replaces_uploader_for_fingerprinting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SnooperFingerprint:
        def fingerprint(
            self,
            path: Path,
            expected_artist: str = "",
            expected_title: str = "",
            alternate_artists: tuple[str, ...] = (),
        ) -> FingerprintResult:
            assert expected_artist == "Harakiri Diat"
            assert alternate_artists == ("Snõõper",)
            return FingerprintResult(
                artist="Snõõper",
                album_artist="Snõõper",
                title="Inventory",
                score=0.99,
            )

    processor = make_processor(tmp_path)
    processor.acoustid = SnooperFingerprint()  # type: ignore[assignment]
    uploaded = (
        processor.settings.uploads
        / "Harakiri Diat - SNÕÕPER - INVENTORY (OFFICIAL MUSIC VIDEO).mp3"
    )
    uploaded.write_bytes(b"audio")
    monkeypatch.setattr(
        "music_processor.processor.read_tags",
        lambda path: Tags(
            artist="Harakiri Diat",
            album_artist="Harakiri Diat",
            title="SNÕÕPER - INVENTORY (OFFICIAL MUSIC VIDEO)",
        ),
    )
    monkeypatch.setattr("music_processor.processor.write_tags", lambda path, tags: None)

    processor.process_pending()

    assert (
        processor.settings.library / "Snõõper" / "Singles & Miscellaneous" / "Inventory.mp3"
    ).exists()



def test_low_confidence_fingerprint_is_deferred(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class LowConfidenceFingerprint:
        def fingerprint(
            self,
            path: Path,
            expected_artist: str = "",
            expected_title: str = "",
            alternate_artists: tuple[str, ...] = (),
        ) -> FingerprintResult:
            return FingerprintResult(
                artist="Artist",
                title="Title",
                score=0.89,
            )

    processor = make_processor(tmp_path)
    processor.acoustid = LowConfidenceFingerprint()  # type: ignore[assignment]
    uploaded = processor.settings.uploads / "Artist - Title.mp3"
    uploaded.write_bytes(b"audio")
    monkeypatch.setattr(
        "music_processor.processor.read_tags",
        lambda path: Tags(artist="Artist", title="Title"),
    )
    written: list[Tags] = []
    monkeypatch.setattr(
        "music_processor.processor.write_tags",
        lambda path, tags: written.append(tags),
    )

    summary = processor.process_pending()

    assert summary.deferred == 0
    assert summary.imported == 1
    assert summary.quarantined == 0
    assert not uploaded.exists()
    assert list(processor.settings.library.rglob("*.mp3"))
    assert len(written) == 1
    assert written[0].review_status == "pending"
    assert written[0].review_reason



@pytest.mark.parametrize(
    "tags",
    [
        Tags(artist="", title="Title", approved=True),
        Tags(artist="Artist", title="", approved=True),
    ],
)
def test_approval_with_missing_artist_or_title_is_deferred(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tags: Tags,
) -> None:
    processor = make_processor(tmp_path)
    uploaded = processor.settings.uploads / "song.mp3"
    uploaded.write_bytes(b"audio")
    monkeypatch.setattr(
        "music_processor.processor.read_tags",
        lambda path: tags,
    )
    written: list[Tags] = []
    monkeypatch.setattr(
        "music_processor.processor.write_tags",
        lambda path, tags: written.append(tags),
    )

    summary = processor.process_pending()

    assert summary.deferred == 1
    assert summary.imported == 0
    assert summary.quarantined == 0
    assert uploaded.read_bytes() == b"audio"
    assert written == []

def test_same_source_url_removes_repeat_instead_of_creating_collision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processor = make_processor(tmp_path)
    uploaded = processor.settings.uploads / "Artist - Title.mp3"
    uploaded.write_bytes(b"repeat")
    existing = processor.settings.library / "Artist" / "Album" / "Title.mp3"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"original")
    source_url = "https://www.youtube.com/watch?v=video-id"

    def tags_for(path: Path) -> Tags:
        return Tags(
            artist="Artist",
            album_artist="Artist",
            album="Album",
            title="Title",
            source_url=source_url,
            approved=True,
        )

    monkeypatch.setattr("music_processor.processor.read_tags", tags_for)
    monkeypatch.setattr("music_processor.processor.acoustic_content_digest", lambda path: "same")
    monkeypatch.setattr(
        "music_processor.processor.write_tags",
        lambda path, tags: pytest.fail("duplicate must not be retagged"),
    )

    summary = processor.process_pending()

    assert summary.duplicates_removed == 1
    assert summary.imported == 0
    assert not uploaded.exists()
    assert existing.read_bytes() == b"original"


def test_same_source_with_improved_metadata_relocates_existing_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_db = tmp_path / "state" / "sources.db"
    processor = make_processor(tmp_path, source_db=source_db)
    uploaded = processor.settings.uploads / "Artist - Better Title.mp3"
    uploaded.write_bytes(b"fresh")
    existing = processor.settings.library / "Artist" / "Old Album" / "Old Title.mp3"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"old")
    source_url = "https://youtu.be/video-id"
    processor.source_registry.register(source_url, existing, "same")

    def tags_for(path: Path) -> Tags:
        if path == uploaded:
            return Tags(
                artist="Artist",
                album="Better Album",
                title="Better Title",
                source_url=source_url,
                approved=True,
            )
        return Tags(
            artist="Artist",
            album="Old Album",
            title="Old Title",
            source_url=source_url,
            approved=True,
        )

    monkeypatch.setattr("music_processor.processor.read_tags", tags_for)
    monkeypatch.setattr("music_processor.processor.acoustic_content_digest", lambda path: "same")
    monkeypatch.setattr("music_processor.processor.write_tags", lambda path, tags: None)

    summary = processor.process_pending()

    destination = processor.settings.library / "Artist" / "Better Album" / "Better Title.mp3"
    assert summary.sources_updated == 1
    assert not existing.exists()
    assert destination.read_bytes() == b"fresh"
    record = processor.source_registry.lookup(source_url)
    assert record is not None
    assert record.path == destination


def test_pending_download_cannot_replace_existing_approved_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processor = make_processor(tmp_path, source_db=tmp_path / "state" / "sources.db")
    uploaded = processor.settings.uploads / "Artist - Uncertain Title.mp3"
    uploaded.write_bytes(b"repeat")
    existing = processor.settings.library / "Artist" / "Album" / "Title.mp3"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"approved-original")
    source_url = "https://youtu.be/video-id"
    processor.source_registry.register(source_url, existing, "same")

    def tags_for(path: Path) -> Tags:
        if path == uploaded:
            return Tags(
                artist="Artist",
                album="Uncertain Album",
                title="Uncertain Title",
                source_url=source_url,
                review_status="pending",
                review_reason="Low confidence fingerprint",
            )
        return Tags(
            artist="Artist",
            album="Album",
            title="Title",
            source_url=source_url,
            approved=True,
        )

    monkeypatch.setattr("music_processor.processor.read_tags", tags_for)
    monkeypatch.setattr("music_processor.processor.acoustic_content_digest", lambda path: "same")
    monkeypatch.setattr(
        "music_processor.processor.write_tags",
        lambda path, tags: pytest.fail("existing approved source must not be retagged"),
    )

    summary = processor.process_pending()

    assert summary.duplicates_removed == 1
    assert summary.sources_updated == 0
    assert not uploaded.exists()
    assert existing.read_bytes() == b"approved-original"


def test_approved_download_replaces_existing_pending_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processor = make_processor(tmp_path, source_db=tmp_path / "state" / "sources.db")
    uploaded = processor.settings.uploads / "Artist - Approved Title.mp3"
    uploaded.write_bytes(b"approved-audio")
    existing = processor.settings.library / "Artist" / "Pending Album" / "Pending Title.mp3"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"pending-audio")
    source_url = "https://youtu.be/video-id"
    processor.source_registry.register(source_url, existing, "same")

    def tags_for(path: Path) -> Tags:
        if path == uploaded:
            return Tags(
                artist="Artist",
                album="Approved Album",
                title="Approved Title",
                source_url=source_url,
                approved=True,
            )
        return Tags(
            artist="Artist",
            album="Pending Album",
            title="Pending Title",
            source_url=source_url,
            review_status="pending",
            review_reason="No reliable metadata match",
        )

    monkeypatch.setattr("music_processor.processor.read_tags", tags_for)
    monkeypatch.setattr("music_processor.processor.acoustic_content_digest", lambda path: "same")
    monkeypatch.setattr("music_processor.processor.write_tags", lambda path, tags: None)

    summary = processor.process_pending()

    destination = processor.settings.library / "Artist" / "Approved Album" / "Approved Title.mp3"
    assert summary.sources_updated == 1
    assert not existing.exists()
    assert destination.read_bytes() == b"approved-audio"
    record = processor.source_registry.lookup(source_url)
    assert record is not None
    assert record.path == destination


def test_pending_download_preserves_existing_pending_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processor = make_processor(tmp_path, source_db=tmp_path / "state" / "sources.db")
    uploaded = processor.settings.uploads / "Artist - Second Uncertain Title.mp3"
    uploaded.write_bytes(b"repeat")
    existing = processor.settings.library / "Artist" / "Pending Album" / "Pending Title.mp3"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"original-pending-audio")
    source_url = "https://youtu.be/video-id"
    processor.source_registry.register(source_url, existing, "same")

    def tags_for(path: Path) -> Tags:
        if path == uploaded:
            return Tags(
                artist="Artist",
                album="Another Uncertain Album",
                title="Another Uncertain Title",
                source_url=source_url,
                review_status="pending",
                review_reason="Low confidence fingerprint",
            )
        return Tags(
            artist="Artist",
            album="Pending Album",
            title="Pending Title",
            source_url=source_url,
            review_status="pending",
            review_reason="Original review reason",
        )

    monkeypatch.setattr("music_processor.processor.read_tags", tags_for)
    monkeypatch.setattr(
        "music_processor.processor.acoustic_content_digest",
        lambda path: "same",
    )
    monkeypatch.setattr(
        "music_processor.processor.write_tags",
        lambda path, tags: pytest.fail("existing pending source must not be retagged"),
    )

    summary = processor.process_pending()

    assert summary.duplicates_removed == 1
    assert summary.sources_updated == 0
    assert not uploaded.exists()
    assert existing.read_bytes() == b"original-pending-audio"
    assert tags_for(existing).review_reason == "Original review reason"


def test_same_source_with_different_audio_is_retained_for_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processor = make_processor(tmp_path)
    uploaded = processor.settings.uploads / "Artist - Title.mp3"
    uploaded.write_bytes(b"new-audio")
    existing = processor.settings.library / "Artist" / "Album" / "Title.mp3"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"old-audio")
    source_url = "https://youtu.be/video-id"

    monkeypatch.setattr(
        "music_processor.processor.read_tags",
        lambda path: Tags(
            artist="Artist",
            album="Album",
            title="Title",
            source_url=source_url,
            approved=True,
        ),
    )
    monkeypatch.setattr(
        "music_processor.processor.acoustic_content_digest",
        lambda path: "new" if path == uploaded else "old",
    )
    monkeypatch.setattr("music_processor.processor.write_tags", lambda path, tags: None)

    summary = processor.process_pending()

    assert summary.imported == 1
    assert summary.duplicates_removed == 0
    assert existing.read_bytes() == b"old-audio"
    assert (existing.parent / "Title (2).mp3").read_bytes() == b"new-audio"


def test_registry_path_outside_library_is_never_replaced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_db = tmp_path / "state" / "sources.db"
    processor = make_processor(tmp_path, source_db=source_db)
    uploaded = processor.settings.uploads / "Artist - Title.mp3"
    uploaded.write_bytes(b"new-audio")
    outside = tmp_path / "outside.mp3"
    outside.write_bytes(b"must-survive")
    source_url = "https://youtu.be/video-id"
    processor.source_registry.register(source_url, outside, "same")

    monkeypatch.setattr(
        "music_processor.processor.read_tags",
        lambda path: Tags(
            artist="Artist",
            album="Album",
            title="Title",
            source_url=source_url,
            approved=True,
        ),
    )
    monkeypatch.setattr("music_processor.processor.write_tags", lambda path, tags: None)

    summary = processor.process_pending()

    assert summary.imported == 1
    assert outside.read_bytes() == b"must-survive"
    assert (processor.settings.library / "Artist" / "Album" / "Title.mp3").exists()


def test_same_title_from_different_source_keeps_both_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processor = make_processor(tmp_path)
    uploaded = processor.settings.uploads / "Artist - Title.mp3"
    uploaded.write_bytes(b"alternate")
    existing = processor.settings.library / "Artist" / "Album" / "Title.mp3"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"original")

    def tags_for(path: Path) -> Tags:
        source = "new" if path == uploaded else "old"
        return Tags(
            artist="Artist",
            album="Album",
            title="Title",
            source_url=source,
            approved=True,
        )

    monkeypatch.setattr("music_processor.processor.read_tags", tags_for)
    monkeypatch.setattr("music_processor.processor.write_tags", lambda path, tags: None)

    summary = processor.process_pending()

    assert summary.imported == 1
    assert (existing.parent / "Title (2).mp3").read_bytes() == b"alternate"


def test_short_self_titled_ep_with_chapters_is_deferred(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnexpectedFingerprint:
        def fingerprint(self, *args, **kwargs):
            pytest.fail("release upload must not be fingerprinted as one recording")

    processor = make_processor(tmp_path)
    processor.acoustid = UnexpectedFingerprint()  # type: ignore[assignment]
    uploaded = processor.settings.uploads / "Harakiri Diat - Snõõper - S⧸T EP.mp3"
    uploaded.write_bytes(b"audio")
    written: list[Tags] = []
    monkeypatch.setattr(
        "music_processor.processor.read_tags",
        lambda path: Tags(artist="Harakiri Diat", title="Snõõper - S/T EP"),
    )
    monkeypatch.setattr("music_processor.processor.audio_duration", lambda path: 430.0)
    monkeypatch.setattr("music_processor.processor.audio_chapter_count", lambda path: 5)
    monkeypatch.setattr(
        "music_processor.processor.write_tags",
        lambda path, tags: written.append(tags),
    )

    summary = processor.process_pending()

    assert summary.deferred == 0
    assert summary.imported == 1
    assert len(written) == 1
    assert written[0].review_status == "pending"
    assert written[0].review_reason

    assert not uploaded.exists()
    assert list(processor.settings.library.rglob("*.mp3"))


def test_chaptered_release_without_match_is_deferred(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processor = make_processor(tmp_path)
    uploaded = processor.settings.uploads / "SNõõPER TV - Snõõper - Halloween.mp3"
    uploaded.write_bytes(b"audio")
    written: list[Tags] = []
    monkeypatch.setattr(
        "music_processor.processor.read_tags",
        lambda path: Tags(artist="SNõõPER TV", title="Snõõper - Halloween"),
    )
    monkeypatch.setattr("music_processor.processor.audio_duration", lambda path: 600.0)
    monkeypatch.setattr("music_processor.processor.audio_chapter_count", lambda path: 4)
    monkeypatch.setattr(
        "music_processor.processor.write_tags",
        lambda path, tags: written.append(tags),
    )

    summary = processor.process_pending()

    assert summary.deferred == 0
    assert summary.imported == 1
    assert len(written) == 1
    assert written[0].review_status == "pending"
    assert written[0].review_reason

    assert not uploaded.exists()
    assert list(processor.settings.library.rglob("*.mp3"))


def test_three_part_song_title_without_approval_is_deferred(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processor = make_processor(tmp_path)
    uploaded = processor.settings.uploads / "Pink Floyd - Another Brick in the Wall - Part 2.mp3"
    uploaded.write_bytes(b"audio")
    written: list[Tags] = []
    monkeypatch.setattr(
        "music_processor.processor.read_tags",
        lambda path: Tags(
            artist="Pink Floyd",
            title="Pink Floyd - Another Brick in the Wall - Part 2",
        ),
    )
    monkeypatch.setattr(
        "music_processor.processor.write_tags",
        lambda path, tags: written.append(tags),
    )

    summary = processor.process_pending()

    assert summary.deferred == 0
    assert summary.imported == 1
    assert len(written) == 1
    assert written[0].review_status == "pending"
    assert written[0].review_reason

    assert not uploaded.exists()
    assert list(processor.settings.library.rglob("*.mp3"))


def test_release_upload_without_approval_is_deferred(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    musicbrainz = FakeMusicBrainz()
    processor = make_processor(tmp_path)
    processor.musicbrainz = musicbrainz  # type: ignore[assignment]
    uploaded = processor.settings.uploads / "Uploader - Artist - Actual Album.mp3"
    uploaded.write_bytes(b"audio")
    written: list[Tags] = []
    monkeypatch.setattr(
        "music_processor.processor.read_tags",
        lambda path: Tags(artist="Uploader", title="Artist - Actual Album"),
    )
    monkeypatch.setattr("music_processor.processor.audio_duration", lambda path: 1800.0)
    monkeypatch.setattr(
        "music_processor.processor.write_tags",
        lambda path, tags: written.append(tags),
    )

    summary = processor.process_pending()

    assert summary.deferred == 0
    assert summary.imported == 1
    assert musicbrainz.calls == []
    assert musicbrainz.release_calls == []
    assert len(written) == 1
    assert written[0].review_status == "pending"
    assert written[0].review_reason

    assert not uploaded.exists()
    assert list(processor.settings.library.rglob("*.mp3"))


def test_ambiguous_filename_artist_without_approval_is_deferred(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    musicbrainz = FakeMusicBrainz()
    processor = make_processor(tmp_path)
    processor.musicbrainz = musicbrainz  # type: ignore[assignment]
    uploaded = (
        processor.settings.uploads
        / "Harakiri Diat - SNÕÕPER - INVENTORY (OFFICIAL MUSIC VIDEO).mp3"
    )
    uploaded.write_bytes(b"audio")
    written: list[Tags] = []
    monkeypatch.setattr(
        "music_processor.processor.read_tags",
        lambda path: Tags(
            artist="Harakiri Diat",
            title="SNÕÕPER - INVENTORY (OFFICIAL MUSIC VIDEO)",
        ),
    )
    monkeypatch.setattr(
        "music_processor.processor.write_tags",
        lambda path, tags: written.append(tags),
    )

    summary = processor.process_pending()

    assert summary.deferred == 0
    assert summary.imported == 1
    assert musicbrainz.calls == []
    assert musicbrainz.release_calls == []
    assert len(written) == 1
    assert written[0].review_status == "pending"
    assert written[0].review_reason

    assert not uploaded.exists()
    assert list(processor.settings.library.rglob("*.mp3"))


def test_filename_artist_spelling_without_approval_is_deferred(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    musicbrainz = FakeMusicBrainz("Super Snooper")
    processor = make_processor(tmp_path)
    processor.musicbrainz = musicbrainz  # type: ignore[assignment]
    uploaded = processor.settings.uploads / "SNOOPER - Xerox (Official video).mp3"
    uploaded.write_bytes(b"audio")
    written: list[Tags] = []
    monkeypatch.setattr("music_processor.processor.read_tags", lambda path: Tags())
    monkeypatch.setattr(
        "music_processor.processor.write_tags",
        lambda path, tags: written.append(tags),
    )

    summary = processor.process_pending()

    assert summary.deferred == 0
    assert summary.imported == 1
    assert musicbrainz.calls == []
    assert musicbrainz.release_calls == []
    assert len(written) == 1
    assert written[0].review_status == "pending"
    assert written[0].review_reason

    assert not uploaded.exists()
    assert list(processor.settings.library.rglob("*.mp3"))


def test_cross_filesystem_replacement_is_staged_before_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "incoming.mp3"
    destination = tmp_path / "library.mp3"
    source.write_bytes(b"new-audio")
    destination.write_bytes(b"old-audio")
    real_replace = os.replace

    def replace_with_cross_device_error(first, second) -> None:
        if Path(first) == source:
            raise OSError(errno.EXDEV, "cross-device link")
        real_replace(first, second)

    monkeypatch.setattr(os, "replace", replace_with_cross_device_error)

    MusicProcessor._move_file(source, destination, replace=True)

    assert destination.read_bytes() == b"new-audio"
    assert not source.exists()


def test_failed_cross_filesystem_copy_preserves_both_originals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "incoming.mp3"
    destination = tmp_path / "library.mp3"
    source.write_bytes(b"new-audio")
    destination.write_bytes(b"old-audio")

    def cross_device_error(first, second) -> None:
        raise OSError(errno.EXDEV, "cross-device link")

    def copy_error(_source_file, _destination_file) -> None:
        raise OSError("copy failed")

    monkeypatch.setattr(os, "replace", cross_device_error)
    monkeypatch.setattr("music_processor.processor.shutil.copyfileobj", copy_error)

    with pytest.raises(OSError, match="copy failed"):
        MusicProcessor._move_file(source, destination, replace=True)

    assert source.read_bytes() == b"new-audio"
    assert destination.read_bytes() == b"old-audio"


def test_cross_filesystem_symlink_move_never_reads_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "target.mp3"
    target.write_bytes(b"must-not-be-copied")
    source = tmp_path / "incoming-link.mp3"
    source.symlink_to(target)
    destination = tmp_path / "quarantined-link.mp3"

    def cross_device_error(first, second) -> None:
        raise OSError(errno.EXDEV, "cross-device link")

    monkeypatch.setattr(os, "rename", cross_device_error)

    MusicProcessor._move_file(source, destination)

    assert destination.is_symlink()
    assert destination.readlink() == target
    assert target.read_bytes() == b"must-not-be-copied"
