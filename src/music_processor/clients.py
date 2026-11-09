"""AcoustID and MusicBrainz clients."""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import requests

from music_processor import __version__
from music_processor.fingerprint import calculate_fingerprint
from music_processor.naming import artists_match, canonical_song_title, normalise_artist

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FingerprintResult:
    artist: str = ""
    album_artist: str = ""
    title: str = ""
    album: str = ""
    recording_id: str = ""
    release_group_id: str = ""
    acoustid_id: str = ""
    score: float = 0.0


class AcoustIDClient:
    def __init__(
        self,
        api_key: str,
        *,
        timeout: float = 15.0,
        session: requests.Session | None = None,
    ) -> None:
        self.api_key = api_key
        self.timeout = timeout
        self.session = session or requests.Session()
        self.max_attempts = 1 if session is not None else 3
        self.request_interval = 0.0 if session is not None else 0.34
        self._last_request = 0.0

    def fingerprint(
        self,
        path: Path,
        expected_artist: str = "",
        expected_title: str = "",
        alternate_artists: tuple[str, ...] = (),
    ) -> FingerprintResult:
        try:
            fingerprint_data = calculate_fingerprint(path)
            if fingerprint_data is None:
                return FingerprintResult()

            response = self._request(
                {
                    "client": self.api_key,
                    "duration": int(fingerprint_data.duration),
                    "fingerprint": fingerprint_data.fingerprint,
                    "meta": "recordings releasegroups",
                }
            )
            return self._select_recording(
                response.json(),
                expected_artist,
                expected_title,
                alternate_artists,
            )
        except requests.RequestException as error:
            response = error.response if isinstance(error, requests.HTTPError) else None
            status = response.status_code if response is not None else None
            details = ""

            if response is not None:
                try:
                    payload = response.json()
                except ValueError:
                    payload = {}

                if isinstance(payload, dict):
                    info = payload.get("error")
                    if isinstance(info, dict):
                        code = info.get("code")
                        message = info.get("message")
                        if isinstance(code, (int, str)) and isinstance(message, str):
                            safe_message = message.replace(self.api_key, "[redacted]")
                            if fingerprint_data is not None:
                                safe_message = safe_message.replace(
                                    fingerprint_data.fingerprint, "[redacted]"
                                )
                            details = f", AcoustID error {code}: {safe_message[:160]}"

            LOGGER.warning(
                "AcoustID HTTP request failed for %s (%s%s)%s",
                path.name,
                type(error).__name__,
                f", HTTP {status}" if status is not None else "",
                details,
            )
            return FingerprintResult()
        except (
            TypeError,
            ValueError,
        ) as error:
            LOGGER.warning("AcoustID lookup failed for %s: %s", path.name, error)
            return FingerprintResult()

    def _request(self, params: dict[str, Any]) -> requests.Response:
        for attempt in range(1, self.max_attempts + 1):
            delay = self.request_interval - (time.monotonic() - self._last_request)
            if delay > 0:
                time.sleep(delay)
            self._last_request = time.monotonic()
            try:
                response = self.session.post(
                    "https://api.acoustid.org/v2/lookup",
                    data=params,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                return response
            except requests.RequestException:
                if attempt == self.max_attempts:
                    raise
                time.sleep(0.5 * attempt)
        raise RuntimeError("unreachable")

    @staticmethod
    def _select_recording(
        payload: dict[str, Any],
        expected_artist: str,
        expected_title: str = "",
        alternate_artists: tuple[str, ...] = (),
    ) -> FingerprintResult:
        if payload.get("status") != "ok":
            return FingerprintResult()

        expected_artists = tuple(
            artist for artist in (expected_artist, *alternate_artists) if artist
        )
        candidates: list[tuple[float, FingerprintResult]] = []
        for result in payload.get("results", []):
            score = _float_score(result.get("score"))
            if score < 0.5:
                continue
            for recording in result.get("recordings", []):
                selected = AcoustIDClient._candidate(
                    result,
                    recording,
                    score,
                    expected_artists,
                    expected_title,
                )
                if selected is not None:
                    candidates.append(selected)

        if not candidates:
            return FingerprintResult()
        return max(candidates, key=lambda item: item[0])[1]

    @staticmethod
    def _candidate(
        result: dict[str, Any],
        recording: dict[str, Any],
        score: float,
        expected_artists: tuple[str, ...],
        expected_title: str,
    ) -> tuple[float, FingerprintResult] | None:
        artists = AcoustIDClient._artist_names(recording)
        artist_credit = AcoustIDClient._artist_credit(recording, artists)
        if not AcoustIDClient._artists_acceptable(
            expected_artists,
            artists,
            artist_credit,
        ):
            return None

        title = _text(recording.get("title"))
        title_similarity = AcoustIDClient._title_similarity(expected_title, title)
        if not AcoustIDClient._title_acceptable(
            expected_artists,
            expected_title,
            title_similarity,
            score,
        ):
            return None

        album, release_group_id = AcoustIDClient._studio_release_group(recording)
        candidate = FingerprintResult(
            artist=artist_credit or (artists[0] if artists else ""),
            album_artist=artists[0] if artists else "",
            title=title,
            album=album,
            recording_id=_text(recording.get("id")),
            release_group_id=release_group_id,
            acoustid_id=_text(result.get("id")),
            score=score,
        )
        return score + title_similarity * 0.15, candidate

    @staticmethod
    def _artist_names(recording: dict[str, Any]) -> list[str]:
        return [
            name
            for artist in recording.get("artists", [])
            if (name := _text(artist.get("name")).strip())
        ]

    @staticmethod
    def _artists_acceptable(
        expected_artists: tuple[str, ...],
        artists: list[str],
        artist_credit: str,
    ) -> bool:
        if not expected_artists:
            return True
        candidates = {artist_credit, ", ".join(artists), " & ".join(artists), *artists}
        return any(
            artists_match(expected, candidate)
            for expected in expected_artists
            for candidate in candidates
            if candidate
        )

    @staticmethod
    def _title_acceptable(
        expected_artists: tuple[str, ...],
        expected_title: str,
        title_similarity: float,
        score: float,
    ) -> bool:
        if expected_artists:
            return True
        if expected_title:
            return title_similarity >= 0.65
        return score >= 0.9

    @staticmethod
    def _studio_release_group(recording: dict[str, Any]) -> tuple[str, str]:
        for release_group in recording.get("releasegroups", []):
            if release_group.get("type") == "Album" and not release_group.get("secondarytypes", []):
                return _text(release_group.get("title")), _text(release_group.get("id"))
        return "", ""

    @staticmethod
    def _artist_credit(recording: dict[str, Any], artists: list[str]) -> str:
        raw_artists = recording.get("artists", [])
        if not raw_artists:
            return ""
        if any(artist.get("joinphrase") for artist in raw_artists):
            return "".join(
                artist.get("name", "").strip() + artist.get("joinphrase", "")
                for artist in raw_artists
            ).strip()
        return ", ".join(artists)

    @staticmethod
    def _title_similarity(expected: str, candidate: str) -> float:
        if not expected or not candidate:
            return 0.0
        return SequenceMatcher(
            None,
            normalise_artist(expected),
            normalise_artist(candidate),
        ).ratio()


class MusicBrainzClient:
    def __init__(
        self,
        contact: str,
        *,
        timeout: float = 15.0,
        session: requests.Session | None = None,
    ) -> None:
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update(
            {"User-Agent": f"music-upload-processor/{__version__} ({contact})"}
        )
        self.max_attempts = 1 if session is not None else 3
        self.request_interval = 0.0 if session is not None else 1.0
        self._last_request = 0.0
        self._artist_ids: dict[str, str] = {}
        self._artist_names: dict[str, str] = {}
        self._album_cache: dict[tuple[str, str], str] = {}
        self._release_group_cache: dict[tuple[str, str], str] = {}

    def canonical_artist_name(self, artist: str) -> str:
        if not self._get_artist_id(artist):
            return ""
        return self._artist_names.get(artist, "")

    def find_earliest_studio_album(self, artist: str, title: str) -> str:
        cache_key = (normalise_artist(artist), normalise_artist(title))
        if cache_key in self._album_cache:
            return self._album_cache[cache_key]
        try:
            artist_id = self._get_artist_id(artist)
            if not artist_id:
                return ""
            result = self._request(
                "recording",
                {
                    "query": f'recording:"{self._escape_query(title)}" AND arid:{artist_id}',
                    "limit": 100,
                },
            )
        except (requests.RequestException, TypeError, ValueError) as error:
            LOGGER.warning("MusicBrainz lookup failed for %s - %s: %s", artist, title, error)
            return ""

        best_album = ""
        best_date = "9999"
        expected_title = normalise_artist(canonical_song_title(title))
        for recording in result.get("recordings", []):
            candidate_title = normalise_artist(
                canonical_song_title(str(recording.get("title", "")))
            )
            if _integer_score(recording.get("score")) < 90 or candidate_title != expected_title:
                continue
            for release in recording.get("releases", []):
                release_group = release.get("release-group", {})
                date = release.get("date", "9999") or "9999"
                if (
                    release_group.get("primary-type") == "Album"
                    and not release_group.get("secondary-types", [])
                    and release.get("status") == "Official"
                    and date < best_date
                ):
                    best_date = date
                    best_album = release.get("title", "")
        self._album_cache[cache_key] = best_album
        return best_album

    def find_studio_album_release(self, artist: str, title: str) -> str:
        query = re.sub(r"\s*[\(\[]\d{4}[\)\]]\s*$", "", title).strip()
        cache_key = (normalise_artist(artist), normalise_artist(query))
        if cache_key in self._release_group_cache:
            return self._release_group_cache[cache_key]
        try:
            artist_id = self._get_artist_id(artist)
            if not artist_id:
                return ""
            result = self._request(
                "release-group",
                {
                    "query": (f'releasegroup:"{self._escape_query(query)}" AND arid:{artist_id}'),
                    "limit": 10,
                },
            )
        except (requests.RequestException, TypeError, ValueError) as error:
            LOGGER.warning("MusicBrainz album lookup failed for %s - %s: %s", artist, query, error)
            return ""

        album = next(
            (
                candidate.get("title", "")
                for candidate in result.get("release-groups", [])
                if _integer_score(candidate.get("score")) >= 95
                and normalise_artist(candidate.get("title", "")) == normalise_artist(query)
                and candidate.get("primary-type") in {"Album", "EP"}
                and not candidate.get("secondary-types", [])
            ),
            "",
        )
        self._release_group_cache[cache_key] = album
        return album

    def _get_artist_id(self, artist: str) -> str:
        if artist in self._artist_ids:
            return self._artist_ids[artist]
        try:
            result = self._request(
                "artist",
                {
                    "query": f'artist:"{self._escape_query(artist)}"',
                    "limit": 5,
                },
            )
        except (requests.RequestException, TypeError, ValueError) as error:
            LOGGER.warning("MusicBrainz artist lookup failed for %s: %s", artist, error)
            return ""

        artists = result.get("artists", [])
        if not artists:
            return ""
        selected = next(
            (
                candidate
                for candidate in artists
                if normalise_artist(candidate.get("name", "")) == normalise_artist(artist)
            ),
            None,
        )
        if selected is None:
            selected = next(
                (
                    candidate
                    for candidate in artists
                    if _integer_score(candidate.get("score")) >= 90
                    and artists_match(artist, candidate.get("name", ""))
                ),
                None,
            )
        if selected is None:
            return ""
        artist_id = _text(selected.get("id"))
        if not artist_id:
            return ""
        self._artist_ids[artist] = artist_id
        self._artist_names[artist] = _text(selected.get("name"))
        return artist_id

    def _request(self, resource: str, params: dict[str, Any]) -> dict[str, Any]:
        request_params = {**params, "fmt": "json"}
        for attempt in range(1, self.max_attempts + 1):
            delay = self.request_interval - (time.monotonic() - self._last_request)
            if delay > 0:
                time.sleep(delay)
            self._last_request = time.monotonic()
            try:
                response = self.session.get(
                    f"https://musicbrainz.org/ws/2/{resource}",
                    params=request_params,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("MusicBrainz response was not an object")
                return payload
            except (requests.RequestException, ValueError):
                if attempt == self.max_attempts:
                    raise
                time.sleep(0.5 * attempt)
        raise RuntimeError("unreachable")

    @staticmethod
    def _escape_query(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')


def _integer_score(value: object) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def _float_score(value: object) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return 0.0


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""
