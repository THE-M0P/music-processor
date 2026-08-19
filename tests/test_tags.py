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
    )
    write_tags(path, expected)

    assert read_tags(path) == expected
