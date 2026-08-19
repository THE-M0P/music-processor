import os

import pytest

from music_processor.cli import build_parser, default_lock_file, environment_flag, main


def test_environment_flag(monkeypatch) -> None:
    monkeypatch.setenv("FLAG", "yes")
    assert environment_flag("FLAG")


def test_environment_flag_defaults_to_false(monkeypatch) -> None:
    monkeypatch.delenv("FLAG", raising=False)
    assert not environment_flag("FLAG")


def test_default_lock_uses_runtime_directory(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))

    assert default_lock_file() == tmp_path / f"music-processor-{os.getuid()}.lock"


def test_quarantine_report_does_not_require_upload_directory(tmp_path, capsys) -> None:
    quarantined = tmp_path / "failed" / "tagging-error"
    quarantined.mkdir(parents=True)
    (quarantined / "song.mp3").write_bytes(b"broken")

    assert main(["--quarantine", str(tmp_path / "failed"), "--report-quarantine"]) == 0
    output = capsys.readouterr().out
    assert "tagging-error: files=1 bytes=6" in output


@pytest.mark.parametrize(
    "arguments",
    (
        ["--stability-wait", "-1"],
        ["--request-timeout", "0"],
        ["--request-timeout", "nan"],
        ["--fallback-album", ".."],
        ["--fallback-album", ""],
    ),
)
def test_invalid_operational_values_are_rejected(arguments) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(arguments)


def test_invalid_environment_log_level_is_rejected(monkeypatch) -> None:
    monkeypatch.setenv("MUSIC_PROCESSOR_LOG_LEVEL", "verbose")

    with pytest.raises(SystemExit):
        build_parser().parse_args([])
