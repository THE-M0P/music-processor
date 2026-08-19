import logging
import subprocess
from pathlib import Path

import requests

from music_processor.clients import AcoustIDClient, FingerprintResult, MusicBrainzClient


def test_acoustid_selects_matching_recording_instead_of_highest_wrong_artist() -> None:
    payload = {
        "status": "ok",
        "results": [
            {
                "score": 0.99,
                "recordings": [
                    {
                        "title": "Wrong song",
                        "artists": [{"name": "Wrong artist"}],
                        "releasegroups": [],
                    }
                ],
            },
            {
                "score": 0.91,
                "recordings": [
                    {
                        "title": "Right song",
                        "artists": [{"name": "Expected artist"}],
                        "releasegroups": [
                            {
                                "title": "Right album",
                                "type": "Album",
                                "secondarytypes": [],
                            }
                        ],
                    }
                ],
            },
        ],
    }

    result = AcoustIDClient._select_recording(payload, "Expected artist")

    assert result == FingerprintResult(
        artist="Expected artist",
        album_artist="Expected artist",
        title="Right song",
        album="Right album",
        score=0.91,
    )


def test_acoustid_rejects_low_confidence_result() -> None:
    payload = {
        "status": "ok",
        "results": [
            {
                "score": 0.49,
                "recordings": [
                    {"title": "Song", "artists": [{"name": "Artist"}], "releasegroups": []}
                ],
            }
        ],
    }

    assert AcoustIDClient._select_recording(payload, "") == FingerprintResult()


def test_acoustid_matches_structured_comma_credit_without_splitting_artist_name() -> None:
    payload = {
        "status": "ok",
        "results": [
            {
                "id": "acoustid-id",
                "score": 0.95,
                "recordings": [
                    {
                        "id": "recording-id",
                        "title": "The Memory Remains",
                        "artists": [
                            {"name": "Metallica"},
                            {"name": "Marianne Faithfull"},
                        ],
                        "releasegroups": [],
                    }
                ],
            }
        ],
    }

    result = AcoustIDClient._select_recording(
        payload,
        "Metallica, Marianne Faithfull",
        "The Memory Remains",
    )

    assert result.artist == "Metallica, Marianne Faithfull"
    assert result.album_artist == "Metallica"
    assert result.recording_id == "recording-id"


def test_acoustid_does_not_match_tyler_the_creator_to_tyler() -> None:
    payload = {
        "status": "ok",
        "results": [
            {
                "score": 0.99,
                "recordings": [
                    {
                        "title": "Wrong",
                        "artists": [{"name": "Tyler"}],
                        "releasegroups": [],
                    }
                ],
            }
        ],
    }

    assert AcoustIDClient._select_recording(payload, "Tyler, The Creator") == FingerprintResult()


def test_acoustid_request_error_does_not_log_api_key(monkeypatch, caplog, tmp_path: Path) -> None:
    secret = "not-a-real-secret"
    fingerprint = "not-a-real-fingerprint"

    class FailingSession:
        def get(self, *args, **kwargs):
            raise requests.Timeout(f"request failed with client={secret}&fingerprint={fingerprint}")

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=f'{{"duration": 10, "fingerprint": "{fingerprint}"}}',
            stderr="",
        ),
    )
    client = AcoustIDClient(secret, session=FailingSession())  # type: ignore[arg-type]

    with caplog.at_level(logging.WARNING):
        result = client.fingerprint(tmp_path / "sample.mp3")

    assert result == FingerprintResult()
    assert secret not in caplog.text
    assert fingerprint not in caplog.text


def test_musicbrainz_searches_enough_recordings_to_find_studio_album(monkeypatch) -> None:
    monkeypatch.setattr(
        "music_processor.clients.musicbrainzngs.search_artists",
        lambda **kwargs: {
            "artist-list": [{"id": "artist-id", "name": "Pearl Jam", "ext:score": "100"}]
        },
    )

    def search_recordings(**kwargs):
        assert kwargs["limit"] == 100
        return {
            "recording-list": [
                {
                    "release-list": [
                        {
                            "title": "Bootleg",
                            "status": "Bootleg",
                            "date": "1992",
                            "release-group": {
                                "type": "Live",
                                "secondary-type-list": ["Live"],
                            },
                        },
                        {
                            "title": "Ten",
                            "status": "Official",
                            "date": "2009-03-24",
                            "release-group": {"type": "Album", "secondary-type-list": []},
                        },
                    ]
                }
            ]
        }

    monkeypatch.setattr(
        "music_processor.clients.musicbrainzngs.search_recordings",
        search_recordings,
    )
    client = MusicBrainzClient("https://example.com")

    assert client.find_earliest_studio_album("Pearl Jam", "Alive") == "Ten"


def test_musicbrainz_recognises_long_form_album_title(monkeypatch) -> None:
    monkeypatch.setattr(
        "music_processor.clients.musicbrainzngs.search_artists",
        lambda **kwargs: {"artist-list": [{"id": "artist-id", "name": "TISM", "ext:score": "100"}]},
    )
    monkeypatch.setattr(
        "music_processor.clients.musicbrainzngs.search_release_groups",
        lambda **kwargs: {
            "release-group-list": [
                {
                    "title": "Hot Dogma",
                    "primary-type": "Album",
                    "ext:score": "100",
                }
            ]
        },
    )
    client = MusicBrainzClient("https://example.com")

    assert client.find_studio_album_release("TISM", "Hot Dogma (1990)") == "Hot Dogma"
