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
