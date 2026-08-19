import subprocess
from pathlib import Path

from music_processor.fingerprint import calculate_fingerprint


def test_short_track_limits_fpcalc_below_audio_duration(monkeypatch, tmp_path: Path) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr("music_processor.fingerprint.audio_duration", lambda path: 66.2)

    def run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            '{"duration": 65, "fingerprint": "value"}',
            "",
        )

    monkeypatch.setattr(subprocess, "run", run)

    result = calculate_fingerprint(tmp_path / "short.mp3")

    assert result is not None
    assert result.duration == 65
    assert commands == [["fpcalc", "-json", "-length", "65", str(tmp_path / "short.mp3")]]


def test_full_digest_fingerprints_entire_file(monkeypatch, tmp_path: Path) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr("music_processor.fingerprint.audio_duration", lambda path: 360.8)

    def run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            '{"duration": 360, "fingerprint": "value"}',
            "",
        )

    monkeypatch.setattr(subprocess, "run", run)

    assert calculate_fingerprint(tmp_path / "album.mp3", maximum_length=None) is not None
    assert commands[0][3] == "359"
