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

from music_processor.fingerprint import calculate_fingerprint
from music_processor.naming import artists_match, normalise_artist

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

    def fingerprint(
        self,
        path: Path,
        expected_artist: str = "",
        expected_title: str = "",
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
            response.raise_for_status()
            return self._select_recording(response.json(), expected_artist, expected_title)
        except requests.RequestException as error:
            LOGGER.warning(
                "AcoustID HTTP request failed for %s (%s)", path.name, type(error).__name__
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
            try:
                return self.session.get(
                    "https://api.acoustid.org/v2/lookup",
                    params=params,
                    timeout=self.timeout,
                )
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
    ) -> FingerprintResult:
        if payload.get("status") != "ok":
            return FingerprintResult()

        candidates: list[tuple[float, FingerprintResult]] = []
        for result in payload.get("results", []):
            score = float(result.get("score", 0))
            if score < 0.5:
                continue
            for recording in result.get("recordings", []):
                artists = [
                    artist.get("name", "").strip()
                    for artist in recording.get("artists", [])
                    if artist.get("name", "").strip()
                ]
                artist_credit = AcoustIDClient._artist_credit(recording, artists)
                artist_candidates = {
                    artist_credit,
                    ", ".join(artists),
                    " & ".join(artists),
                    *artists,
                }
                if expected_artist and not any(
                    artists_match(expected_artist, candidate)
                    for candidate in artist_candidates
                    if candidate
                ):
                    continue

                album = ""
                release_group_id = ""
                for release_group in recording.get("releasegroups", []):
                    if release_group.get("type") == "Album" and not release_group.get(
                        "secondarytypes", []
                    ):
                        album = release_group.get("title", "")
                        release_group_id = release_group.get("id", "")
                        break
                title = recording.get("title", "")
                title_similarity = AcoustIDClient._title_similarity(expected_title, title)
                candidate = FingerprintResult(
                    artist=artist_credit or (artists[0] if artists else ""),
                    album_artist=artists[0] if artists else "",
                    title=title,
                    album=album,
                    recording_id=recording.get("id", ""),
                    release_group_id=release_group_id,
                    acoustid_id=result.get("id", ""),
                    score=score,
                )
                candidates.append((score + title_similarity * 0.15, candidate))

        if not candidates:
            return FingerprintResult()
        return max(candidates, key=lambda item: item[0])[1]

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
        self.session.headers.update({"User-Agent": f"music-upload-processor/0.1.0 ({contact})"})
        self.max_attempts = 1 if session is not None else 3
        self.request_interval = 0.0 if session is not None else 1.0
        self._last_request = 0.0
        self._artist_ids: dict[str, str] = {}
        self._album_cache: dict[tuple[str, str], str] = {}
        self._release_group_cache: dict[tuple[str, str], str] = {}

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
        except Exception as error:
            LOGGER.warning("MusicBrainz lookup failed for %s - %s: %s", artist, title, error)
            return ""

        best_album = ""
        best_date = "9999"
        for recording in result.get("recordings", []):
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
        except Exception as error:
            LOGGER.warning("MusicBrainz album lookup failed for %s - %s: %s", artist, query, error)
            return ""

        album = next(
            (
                candidate.get("title", "")
                for candidate in result.get("release-groups", [])
                if int(candidate.get("score", "0")) >= 95
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
        except Exception as error:
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
                    if int(candidate.get("score", "0")) >= 90
                    and artists_match(artist, candidate.get("name", ""))
                ),
                None,
            )
        if selected is None:
            return ""
        artist_id = selected["id"]
        self._artist_ids[artist] = artist_id
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
