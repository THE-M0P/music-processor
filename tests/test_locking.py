from pathlib import Path

import pytest

from music_processor.locking import AlreadyRunningError, single_instance


def test_single_instance_rejects_second_lock(tmp_path: Path) -> None:
    lock_path = tmp_path / "processor.lock"
    with (
        single_instance(lock_path),
        pytest.raises(AlreadyRunningError),
        single_instance(lock_path),
    ):
        pass
