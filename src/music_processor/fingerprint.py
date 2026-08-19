"""Chromaprint fingerprint generation."""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

from music_processor.tags import audio_duration

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FingerprintData:
    duration: float
    fingerprint: str


def calculate_fingerprint(
    path: Path,
    *,
    maximum_length: int | None = 120,
    timeout: float = 30,
) -> FingerprintData | None:
    duration = audio_duration(path)
    command = ["fpcalc", "-json"]
    if maximum_length is None:
        command.extend(("-length", "0"))
    elif duration > 1:
        length = max(1, int(duration) - 1)
        length = min(maximum_length, length)
        command.extend(("-length", str(length)))
    command.append(str(path))

    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as error:
        LOGGER.warning("Could not fingerprint %s: %s", path.name, error)
        return None

    if completed.returncode != 0:
        LOGGER.warning("fpcalc failed for %s: %s", path.name, completed.stderr.strip())
        return None
    try:
        payload = json.loads(completed.stdout)
        fingerprint = str(payload.get("fingerprint", ""))
        measured_duration = float(payload.get("duration", 0))
    except (json.JSONDecodeError, TypeError, ValueError) as error:
        LOGGER.warning("Invalid fpcalc output for %s: %s", path.name, error)
        return None
    if not fingerprint:
        return None
    return FingerprintData(duration=measured_duration, fingerprint=fingerprint)


def acoustic_content_digest(path: Path) -> str:
    data = calculate_fingerprint(path, maximum_length=None, timeout=120)
    if data is None:
        return ""
    value = f"{data.duration:.3f}\0{data.fingerprint}".encode()
    return hashlib.sha256(value).hexdigest()
