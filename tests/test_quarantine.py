from datetime import UTC, datetime
from pathlib import Path

from music_processor.quarantine import quarantine_inventory


def test_quarantine_inventory_groups_reasons(tmp_path: Path) -> None:
    first = tmp_path / "unsupported" / "notes.txt"
    second = tmp_path / "unsupported" / "image.bin"
    failed = tmp_path / "tagging-error" / "song.mp3"
    first.parent.mkdir(parents=True)
    failed.parent.mkdir(parents=True)
    first.write_bytes(b"12")
    second.write_bytes(b"345")
    failed.write_bytes(b"6789")

    inventory = quarantine_inventory(tmp_path)

    assert [(entry.reason, entry.files, entry.bytes) for entry in inventory] == [
        ("tagging-error", 1, 4),
        ("unsupported", 2, 5),
    ]
    assert all(entry.oldest <= datetime.now(UTC) for entry in inventory)


def test_missing_quarantine_is_empty(tmp_path: Path) -> None:
    assert quarantine_inventory(tmp_path / "missing") == ()
