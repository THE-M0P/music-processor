"""Quarantine inventory reporting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class QuarantineEntry:
    reason: str
    files: int
    bytes: int
    oldest: datetime


def quarantine_inventory(root: Path) -> tuple[QuarantineEntry, ...]:
    grouped: dict[str, list[tuple[int, datetime]]] = {}
    if not root.is_dir():
        return ()
    for path in root.rglob("*"):
        if not path.is_file() and not path.is_symlink():
            continue
        relative = path.relative_to(root)
        reason = relative.parts[0] if len(relative.parts) > 1 else "unclassified"
        try:
            details = path.lstat()
        except OSError:
            continue
        modified = datetime.fromtimestamp(details.st_mtime, UTC)
        grouped.setdefault(reason, []).append((details.st_size, modified))
    return tuple(
        QuarantineEntry(
            reason=reason,
            files=len(values),
            bytes=sum(size for size, _ in values),
            oldest=min(modified for _, modified in values),
        )
        for reason, values in sorted(grouped.items())
    )
