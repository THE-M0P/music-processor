import wave
from pathlib import Path

from music_processor.tags import Tags, read_tags, write_tags


def test_wav_tags_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "sample.wav"
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8_000)
        output.writeframes(b"\x00\x00" * 800)

    expected = Tags(
        artist="Artist feat. Guest",
        album_artist="Artist",
        album="Album",
        title="Title (Live)",
        source_title="Artist - Title (Live) [HD]",
        match_source="acoustid",
        confidence=0.925,
        recording_id="recording-id",
        release_group_id="release-group-id",
        acoustid_id="acoustid-id",
        source_url="https://www.youtube.com/watch?v=video-id",
        artist_source="source+acoustid",
        album_artist_source="derived-artist",
        album_source="musicbrainz",
        title_source="acoustid+source-version",
    )
    write_tags(path, expected)

    assert read_tags(path) == expected


def test_rewrite_clears_stale_processor_identifiers(tmp_path: Path) -> None:
    path = tmp_path / "sample.wav"
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8_000)
        output.writeframes(b"\x00\x00" * 800)

    write_tags(
        path,
        Tags(
            artist="Artist",
            album_artist="Artist",
            album="Album",
            title="Title",
            recording_id="stale-recording",
            acoustid_id="stale-acoustid",
            source_url="https://www.youtube.com/watch?v=old",
        ),
    )
    replacement = Tags(
        artist="Artist",
        album_artist="Artist",
        album="Album",
        title="Title",
    )

    write_tags(path, replacement)

    assert read_tags(path) == replacement


def test_mp3_approval_marker_round_trip_and_clear(tmp_path: Path) -> None:
    import shutil
    import subprocess

    import pytest

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("ffmpeg is required for this MP3 tag test")

    path = tmp_path / "approved.mp3"
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel", "error",
            "-f", "lavfi",
            "-i", "sine=frequency=440:duration=1",
            "-q:a", "9",
            "-y",
            str(path),
        ],
        check=True,
    )

    pending_tags = Tags(
        artist="Test Artist",
        album="Singles & Miscellaneous",
        title="Test Track",
        album_artist="Test Artist",
        review_status="pending",
        review_reason="No reliable AcoustID match",
    )

    write_tags(path, pending_tags)
    assert read_tags(path) == pending_tags

    approved_tags = Tags(
        artist="Test Artist",
        album="Singles & Miscellaneous",
        title="Test Track",
        album_artist="Test Artist",
        approved=True,
    )

    write_tags(path, approved_tags)
    assert read_tags(path) == approved_tags

    unapproved_tags = Tags(
        artist="Test Artist",
        album="Singles & Miscellaneous",
        title="Test Track",
        album_artist="Test Artist",
        approved=False,
    )

    write_tags(path, unapproved_tags)
    assert read_tags(path) == unapproved_tags
