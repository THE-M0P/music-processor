import logging
from pathlib import Path

import requests

from music_processor.clients import AcoustIDClient, FingerprintResult, MusicBrainzClient
from music_processor.fingerprint import FingerprintData


class FakeResponse:
    def __init__(self, payload) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self.payload


class QueueSession:
    def __init__(self, *payloads) -> None:
        self.payloads = list(payloads)
        self.headers: dict[str, str] = {}
        self.calls = []
        self.post_calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.payloads.pop(0))

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return FakeResponse(self.payloads.pop(0))


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


def test_acoustid_rejects_unrelated_title_without_artist_evidence() -> None:
    payload = {
        "status": "ok",
        "results": [
            {
                "score": 0.95,
                "recordings": [
                    {
                        "title": "Completely Different Song",
                        "artists": [{"name": "Unknown Artist"}],
                        "releasegroups": [],
                    }
                ],
            }
        ],
    }

    assert AcoustIDClient._select_recording(payload, "", "Expected Title") == FingerprintResult()


def test_acoustid_request_error_does_not_log_api_key(monkeypatch, caplog, tmp_path: Path) -> None:
    secret = "not-a-real-secret"
    fingerprint = "not-a-real-fingerprint"

    class FailingSession:
        def post(self, *args, **kwargs):
            raise requests.Timeout(f"request failed with client={secret}&fingerprint={fingerprint}")

    monkeypatch.setattr(
        "music_processor.clients.calculate_fingerprint",
        lambda path: FingerprintData(duration=10, fingerprint=fingerprint),
    )
    client = AcoustIDClient(secret, session=FailingSession())  # type: ignore[arg-type]

    with caplog.at_level(logging.WARNING):
        result = client.fingerprint(tmp_path / "sample.mp3")

    assert result == FingerprintResult()
    assert secret not in caplog.text
    assert fingerprint not in caplog.text


def test_acoustid_uses_post_for_long_fingerprint(monkeypatch, tmp_path: Path) -> None:
    session = QueueSession({"status": "ok", "results": []})
    monkeypatch.setattr(
        "music_processor.clients.calculate_fingerprint",
        lambda path: FingerprintData(duration=180, fingerprint="fingerprint-data"),
    )

    result = AcoustIDClient("application-key", session=session).fingerprint(
        tmp_path / "sample.mp3",
        expected_artist="Artist",
        expected_title="Title",
    )

    assert result == FingerprintResult()
    assert not session.calls
    assert session.post_calls[0][1]["data"]["fingerprint"] == "fingerprint-data"


def test_musicbrainz_searches_enough_recordings_to_find_studio_album() -> None:
    session = QueueSession(
        {"artists": [{"id": "artist-id", "name": "Pearl Jam", "score": 100}]},
        {
            "recordings": [
                {
                    "title": "Alive",
                    "score": 100,
                    "releases": [
                        {
                            "title": "Bootleg",
                            "status": "Bootleg",
                            "date": "1992",
                            "release-group": {
                                "primary-type": "Album",
                                "secondary-types": ["Live"],
                            },
                        },
                        {
                            "title": "Ten",
                            "status": "Official",
                            "date": "2009-03-24",
                            "release-group": {
                                "primary-type": "Album",
                                "secondary-types": [],
                            },
                        },
                    ],
                }
            ]
        },
    )
    client = MusicBrainzClient("https://example.com", session=session)  # type: ignore[arg-type]

    assert client.find_earliest_studio_album("Pearl Jam", "Alive") == "Ten"
    assert session.calls[1][1]["params"]["limit"] == 100
    assert session.calls[1][1]["timeout"] == 15.0
    assert session.headers["User-Agent"].startswith("music-upload-processor/0.1.0")


def test_musicbrainz_retains_canonical_artist_spelling() -> None:
    session = QueueSession(
        {"artists": [{"id": "artist-id", "name": "Snõõper", "score": 100}]},
        {"recordings": []},
    )
    client = MusicBrainzClient("https://example.com", session=session)  # type: ignore[arg-type]

    client.find_earliest_studio_album("Snooper", "Unknown")

    assert client.canonical_artist_name("Snooper") == "Snõõper"


def test_musicbrainz_ignores_fuzzy_recording_with_wrong_title() -> None:
    session = QueueSession(
        {"artists": [{"id": "artist-id", "name": "Artist", "score": 100}]},
        {
            "recordings": [
                {
                    "title": "Wrong Song",
                    "score": 100,
                    "releases": [
                        {
                            "title": "Wrong Album",
                            "status": "Official",
                            "date": "1980",
                            "release-group": {
                                "primary-type": "Album",
                                "secondary-types": [],
                            },
                        }
                    ],
                },
                {
                    "title": "Right Song",
                    "score": 98,
                    "releases": [
                        {
                            "title": "Right Album",
                            "status": "Official",
                            "date": "2000",
                            "release-group": {
                                "primary-type": "Album",
                                "secondary-types": [],
                            },
                        }
                    ],
                },
            ]
        },
    )

    client = MusicBrainzClient("https://example.com", session=session)  # type: ignore[arg-type]

    assert client.find_earliest_studio_album("Artist", "Right Song") == "Right Album"


def test_musicbrainz_recognises_long_form_album_title() -> None:
    session = QueueSession(
        {"artists": [{"id": "artist-id", "name": "TISM", "score": 100}]},
        {
            "release-groups": [
                {
                    "title": "Hot Dogma",
                    "primary-type": "Album",
                    "secondary-types": [],
                    "score": 100,
                }
            ]
        },
    )
    client = MusicBrainzClient("https://example.com", session=session)  # type: ignore[arg-type]

    assert client.find_studio_album_release("TISM", "Hot Dogma (1990)") == "Hot Dogma"


def test_musicbrainz_accepts_ep_release_group() -> None:
    session = QueueSession(
        {"artists": [{"id": "artist-id", "name": "Snõõper", "score": 100}]},
        {
            "release-groups": [
                {
                    "title": "Snõõper",
                    "primary-type": "EP",
                    "secondary-types": [],
                    "score": 100,
                }
            ]
        },
    )

    assert (
        MusicBrainzClient(
            "https://example.com",
            session=session,  # type: ignore[arg-type]
        ).find_studio_album_release("Snõõper", "Snõõper")
        == "Snõõper"
    )


def test_musicbrainz_timeout_returns_no_match() -> None:
    class TimeoutSession(QueueSession):
        def get(self, url, **kwargs):
            raise requests.Timeout("unavailable")

    client = MusicBrainzClient(
        "https://example.com",
        timeout=2,
        session=TimeoutSession(),  # type: ignore[arg-type]
    )

    assert client.find_earliest_studio_album("Artist", "Title") == ""
