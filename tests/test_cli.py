from music_processor.cli import environment_flag


def test_environment_flag(monkeypatch) -> None:
    monkeypatch.setenv("FLAG", "yes")
    assert environment_flag("FLAG")


def test_environment_flag_defaults_to_false(monkeypatch) -> None:
    monkeypatch.delenv("FLAG", raising=False)
    assert not environment_flag("FLAG")
