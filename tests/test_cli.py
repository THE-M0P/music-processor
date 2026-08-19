import os

from music_processor.cli import default_lock_file, environment_flag


def test_environment_flag(monkeypatch) -> None:
    monkeypatch.setenv("FLAG", "yes")
    assert environment_flag("FLAG")


def test_environment_flag_defaults_to_false(monkeypatch) -> None:
    monkeypatch.delenv("FLAG", raising=False)
    assert not environment_flag("FLAG")


def test_default_lock_uses_runtime_directory(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))

    assert default_lock_file() == tmp_path / f"music-processor-{os.getuid()}.lock"
