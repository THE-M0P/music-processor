import stat
from pathlib import Path

from music_processor.source_registry import SourceRegistry, source_identity_key


def test_youtube_url_forms_have_the_same_identity() -> None:
    urls = (
        "https://www.youtube.com/watch?v=abc123&list=playlist",
        "https://youtu.be/abc123?t=20",
        "https://www.youtube.com/shorts/abc123",
        "https://music.youtube.com/watch?v=abc123",
    )

    assert {source_identity_key(url) for url in urls} == {"youtube:abc123"}


def test_generic_url_identity_ignores_fragment() -> None:
    assert source_identity_key("https://Example.com/audio?id=2#time") == (
        "url:https://example.com/audio?id=2"
    )


def test_registry_round_trip_and_update(tmp_path: Path) -> None:
    registry = SourceRegistry(tmp_path / "state" / "sources.db")
    source_url = "https://youtu.be/video-id"

    assert registry.lookup(source_url) is None
    registry.register(source_url, Path("/music/old.mp3"), "first")
    first = registry.lookup(source_url)
    assert first is not None
    assert first.path == Path("/music/old.mp3")
    assert first.content_digest == "first"
    assert stat.S_IMODE((tmp_path / "state" / "sources.db").stat().st_mode) == 0o600

    registry.register(source_url, Path("/music/new.mp3"), "second")
    second = registry.lookup(source_url)
    assert second is not None
    assert second.path == Path("/music/new.mp3")
    assert second.content_digest == "second"


def test_disabled_registry_does_not_create_state(tmp_path: Path) -> None:
    registry = SourceRegistry(None)

    registry.register("https://youtu.be/video-id", tmp_path / "song.mp3", "digest")

    assert not any(tmp_path.iterdir())


def test_corrupt_registry_does_not_block_processing_state(tmp_path: Path) -> None:
    database = tmp_path / "sources.db"
    database.write_bytes(b"not sqlite")
    registry = SourceRegistry(database)

    assert registry.lookup("https://youtu.be/video-id") is None
    registry.register("https://youtu.be/video-id", tmp_path / "song.mp3", "digest")

    assert database.read_bytes() == b"not sqlite"


def test_uncreatable_registry_parent_does_not_block_import_state(tmp_path: Path) -> None:
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("blocked", encoding="utf-8")
    registry = SourceRegistry(blocker / "sources.db")

    registry.register("https://youtu.be/video-id", tmp_path / "song.mp3", "digest")

    assert blocker.read_text(encoding="utf-8") == "blocked"
