import os

from music_processor.cli import default_lock_file, environment_flag, main


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
