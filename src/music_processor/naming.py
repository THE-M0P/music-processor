"""Filename and metadata normalisation."""

from __future__ import annotations

import re
import unicodedata

SMALL_WORDS = {
    "a",
    "an",
    "the",
    "and",
    "but",
    "or",
    "for",
    "nor",
    "of",
    "on",
    "at",
    "to",
    "by",
    "in",
    "up",
    "as",
    "feat.",
    "ft.",
    "vs.",
    "vs",
}

_TITLE_NOISE_EXPRESSIONS = (
    r"\s*[\(\[]\s*(?:official\s+)?(?:hd\s+)?music\s+video\s*[\)\]]",
    r"\s*[\(\[]\s*(?:official\s+)?video\s*[\)\]]",
    r"\s*[\(\[]\s*(?:official\s+)?lyric(?:s)?(?:\s+video)?\s*[\)\]]",
    r"\s*[\(\[]\s*(?:official\s+)?visuali[sz]er\s*[\)\]]",
    r"\s*[\(\[]\s*(?:official\s+)?audio\s*[\)\]]",
    r"\s*[\(\[]\s*full\s+album\s+stream\s*[\)\]]",
    r"\s*[\(\[]\s*(?:official|hd|hq|4k|lyrics?|explicit)\s*[\)\]]",
    r"\s*[-\u2013\u2014|]\s*(?:official\s+)?"
    r"(?:music\s+video|lyric(?:s)?(?:\s+video)?|audio|visuali[sz]er)\s*$",
    r"\s*\+\s*chronicle[^$]*$",
    r"\s*[\(\[]\s*yule\s+log[^\)\]]*[\)\]]",
)
TITLE_JUNK_PATTERNS = tuple(re.compile(value, re.IGNORECASE) for value in _TITLE_NOISE_EXPRESSIONS)

_VERSION_WORDS = (
    r"live|acoustic|demo|remix|mix|edit|version|remaster(?:ed)?|instrumental|"
    r"alternate(?:\s+take)?|session|festival|reprise|medley|mono|stereo|"
    r"anniversary|cover|with\s+intro|bonus\s+track"
)
_VERSION_TOKEN = rf"\b(?:{_VERSION_WORDS})\b"
_VERSION_GROUP = re.compile(
    rf"(?P<wrapped>\((?P<paren>[^()]*(?:{_VERSION_TOKEN})[^()]*)\)"
    rf"|\[(?P<bracket>[^\[\]]*(?:{_VERSION_TOKEN})[^\[\]]*)\])",
    re.IGNORECASE,
)
_TRAILING_VERSION = re.compile(
    rf"\s*[-\u2013\u2014|]\s*(?P<label>(?:{_VERSION_TOKEN}).*)$",
    re.IGNORECASE,
)

_ALBUM_JUNK_EXPRESSIONS = (
    r"\s*[\(\[].*\bremaster(ed)?\b.*[\)\]]",
    r"\s*[\(\[].*\bdeluxe\b.*[\)\]]",
    r"\s*[\(\[].*\bexpanded\b.*[\)\]]",
    r"\s*[\(\[].*\banniversary\b.*[\)\]]",
    r"\s*[\(\[].*\bbonus\b.*[\)\]]",
    r"\s*[\(\[].*\bspecial edition\b.*[\)\]]",
)
ALBUM_JUNK_PATTERNS = tuple(re.compile(value, re.IGNORECASE) for value in _ALBUM_JUNK_EXPRESSIONS)

_CREDIT_SEPARATOR = re.compile(
    r"\s+(?:feat\.?|ft\.?|featuring|with|vs\.?)\s+",
    re.IGNORECASE,
)


def safe_name(value: str | None, fallback: str) -> str:
    cleaned = (value or "").strip() or fallback
    cleaned = re.sub(r'[<>:"/\\|?*]', "_", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if not cleaned or cleaned in {".", ".."}:
        cleaned = fallback
    return cleaned[:150]


def normalise_artist_case(name: str) -> str:
    if not name:
        return name

    result: list[str] = []
    for index, word in enumerate(name.split()):
        follows_comma = bool(result and result[-1].endswith(","))
        if word.upper() == word and len(word) > 1 and word.isalpha():
            result.append(word)
        elif index == 0 or follows_comma:
            result.append(word[0].upper() + word[1:])
        elif word.lower() in SMALL_WORDS:
            if word.lower() == result[-1].lower():
                result.append(word[0].upper() + word[1:])
            else:
                result.append(word.lower())
        else:
            result.append(word[0].upper() + word[1:])
    return " ".join(result)


def _comparison_key(value: str) -> str:
    normalised = unicodedata.normalize("NFKD", value.casefold().strip())
    normalised = "".join(
        character for character in normalised if unicodedata.category(character) != "Mn"
    )
    normalised = re.sub(r"\s*&\s*", " and ", normalised)
    return re.sub(r"[^a-z0-9]+", " ", normalised).strip()


def primary_artist(name: str) -> str:
    return _CREDIT_SEPARATOR.split(name.strip(), maxsplit=1)[0].strip()


def clean_channel_artist(name: str) -> str:
    cleaned = re.sub(r"^official\s+", "", name.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+(?:official|tv)$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"vevo$", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" -")


def artist_match_keys(name: str) -> set[str]:
    if not name:
        return set()

    values = {name.strip(), primary_artist(name)}
    for separator in (" & the ", " and the "):
        position = name.casefold().find(separator)
        if position > 0:
            values.add(name[:position].strip())

    keys = {_comparison_key(value) for value in values if value}
    for key in tuple(keys):
        for prefix in ("the ", "a ", "an "):
            if key.startswith(prefix):
                keys.add(key[len(prefix) :])
                break
    return {key for key in keys if key}


def normalise_artist(name: str) -> str:
    return _comparison_key(name)


def artists_match(first: str, second: str) -> bool:
    if not first or not second:
        return True

    first_keys = artist_match_keys(first)
    second_keys = artist_match_keys(second)
    if first_keys & second_keys:
        return True

    for first_key in first_keys:
        for second_key in second_keys:
            shorter = min(len(first_key), len(second_key))
            longer = max(len(first_key), len(second_key))
            if (
                longer
                and shorter / longer >= 0.8
                and (first_key in second_key or second_key in first_key)
            ):
                return True
    return False


def is_clean_title(title: str) -> bool:
    return not any(pattern.search(title) for pattern in TITLE_JUNK_PATTERNS)


def clean_title(title: str, artist: str = "") -> str:
    cleaned = title.strip()
    if artist:
        for separator in (r"\s*[-\u2013\u2014]\s*", r"\s*:\s*", r"\s*\|\s*"):
            prefix = re.escape(artist.strip()) + separator
            while re.match(f"^{prefix}", cleaned, flags=re.IGNORECASE):
                cleaned = re.sub(f"^{prefix}", "", cleaned, flags=re.IGNORECASE).strip()

    for pattern in TITLE_JUNK_PATTERNS:
        cleaned = pattern.sub("", cleaned).strip()

    if artist:
        for suffix in (
            r"\s*-\s*" + re.escape(artist.strip()) + r"\s*-\s*vevo$",
            r"\s*-\s*" + re.escape(artist.strip()) + r"\s*-\s*topic$",
        ):
            cleaned = re.sub(suffix, "", cleaned, flags=re.IGNORECASE).strip()

    for opening, closing in (('"', '"'), ("“", "”"), ("'", "'"), ("‘", "’")):
        if cleaned.startswith(opening) and cleaned.endswith(closing) and len(cleaned) > 2:
            cleaned = cleaned[len(opening) : -len(closing)].strip()
            break

    for suffix in (r"\s*-\s*vevo$", r"\s*-\s*topic$"):
        cleaned = re.sub(suffix, "", cleaned, flags=re.IGNORECASE).strip()
    if artist:
        cleaned = re.sub(
            r"\s*-\s*" + re.escape(artist.strip()) + r"$",
            "",
            cleaned,
            flags=re.IGNORECASE,
        ).strip()

    cleaned = re.sub(r"[\(\[]\s*[\)\]]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -\u2013\u2014|")
    return cleaned or title


def version_labels(title: str) -> tuple[str, ...]:
    labels: list[str] = []
    for match in _VERSION_GROUP.finditer(title):
        label = (match.group("paren") or match.group("bracket") or "").strip()
        label = re.sub(r"\s+", " ", label)
        if label and _comparison_key(label) not in {_comparison_key(value) for value in labels}:
            labels.append(label)

    trailing = _TRAILING_VERSION.search(title)
    if trailing:
        label = re.sub(r"\s+", " ", trailing.group("label").strip())
        if label and _comparison_key(label) not in {_comparison_key(value) for value in labels}:
            labels.append(label)
    return tuple(labels)


def split_upload_filename(stem: str) -> tuple[str, str]:
    parts = [part.strip() for part in stem.split(" - ") if part.strip()]
    if len(parts) < 2:
        return "", stem.strip()
    if len(parts) == 2:
        return clean_channel_artist(parts[0]), parts[1]

    first, second = parts[:2]
    remaining = parts[2:]
    if second.casefold() in {"topic", "official", "vevo"}:
        return clean_channel_artist(first), " - ".join(remaining)
    if artists_match(first, second):
        return clean_channel_artist(first), " - ".join(remaining)
    if len(remaining) == 1 and version_labels(f"Song ({remaining[0]})"):
        return clean_channel_artist(first), " - ".join(parts[1:])
    return clean_channel_artist(second), " - ".join(remaining)


def canonical_song_title(title: str) -> str:
    canonical = _VERSION_GROUP.sub("", title)
    canonical = _TRAILING_VERSION.sub("", canonical)
    canonical = re.sub(r"\s+", " ", canonical).strip(" -\u2013\u2014|")
    return canonical or title.strip()


def merge_version_title(canonical_title: str, source_title: str) -> str:
    canonical = canonical_song_title(clean_title(canonical_title))
    labels: list[str] = []
    for label in (*version_labels(canonical_title), *version_labels(clean_title(source_title))):
        if _comparison_key(label) not in {_comparison_key(value) for value in labels}:
            labels.append(label)
    return canonical + "".join(f" ({label})" for label in labels)


def clean_album(album: str) -> str:
    if not album:
        return album

    cleaned = album.strip()
    for pattern in ALBUM_JUNK_PATTERNS:
        cleaned = pattern.sub("", cleaned).strip()
    cleaned = cleaned.replace("…", "...").replace("...", "... ").strip()
    cleaned = re.sub(r"\.\.\.", "... ", cleaned).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    result: list[str] = []
    first_word_found = False
    for word in cleaned.split():
        if all(not character.isalnum() for character in word):
            result.append(word)
        elif not first_word_found:
            result.append(word[0].upper() + word[1:])
            first_word_found = True
        elif word.upper() == word and len(word) > 1 and word.isalpha():
            result.append(word)
        elif word.lower() in SMALL_WORDS:
            if word.lower() == result[-1].lower():
                result.append(word[0].upper() + word[1:])
            else:
                result.append(word.lower())
        else:
            result.append(word[0].upper() + word[1:])

    cleaned = " ".join(result)
    cleaned = re.sub(r"\s+,", ",", cleaned)
    cleaned = re.sub(r"\s+\.", ".", cleaned)
    return cleaned or album
