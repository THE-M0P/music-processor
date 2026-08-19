from music_processor.naming import (
    artists_match,
    canonical_song_title,
    clean_title,
    merge_version_title,
    prefer_filename_artist,
    primary_artist,
    release_lookup_title,
    safe_name,
    split_upload_filename,
    version_labels,
)


def test_live_title_keeps_display_detail_but_has_canonical_search_title() -> None:
    display = clean_title("Radiohead - Creep (Live at Glastonbury 1997) [HD]", "Radiohead")

    assert display == "Creep (Live at Glastonbury 1997)"
    assert canonical_song_title(display) == "Creep"


def test_fingerprint_title_inherits_source_version() -> None:
    assert (
        merge_version_title("Creep", "Creep (Live at Glastonbury 1997) [Official Video]")
        == "Creep (Live at Glastonbury 1997)"
    )


def test_trailing_live_description_is_preserved() -> None:
    source = "Creep - Live at Glastonbury 1997"

    assert version_labels(source) == ("Live at Glastonbury 1997",)
    assert merge_version_title("Creep", source) == "Creep (Live at Glastonbury 1997)"


def test_short_trailing_live_marker_is_preserved() -> None:
    assert merge_version_title("Creep", "Creep - Live") == "Creep (Live)"


def test_version_already_in_canonical_title_is_not_lost_or_duplicated() -> None:
    assert merge_version_title("Song (Acoustic)", "Song (Acoustic)") == "Song (Acoustic)"


def test_unrelated_word_containing_mix_is_not_a_version() -> None:
    assert version_labels("Song (Delivery Mixup)") == ()


def test_non_version_parenthetical_stays_in_search_title() -> None:
    assert canonical_song_title("Man (Opposable Thumb)") == "Man (Opposable Thumb)"


def test_tyler_the_creator_is_not_reduced_to_tyler() -> None:
    assert not artists_match("Tyler, The Creator", "Tyler")
    assert artists_match("Tyler, The Creator", "tyler the creator")


def test_explicit_feature_credit_has_primary_artist() -> None:
    assert primary_artist("Eminem feat. Dido") == "Eminem"


def test_uploader_prefix_is_not_mistaken_for_title_artist() -> None:
    assert split_upload_filename("WelshTISMFan - TISM - Hot Dogma (1990)") == (
        "TISM",
        "Hot Dogma (1990)",
    )


def test_topic_channel_is_reduced_to_artist() -> None:
    assert split_upload_filename("Dan Hartman - Topic - Forever In A Moment") == (
        "Dan Hartman",
        "Forever In A Moment",
    )


def test_trailing_version_does_not_become_artist() -> None:
    assert split_upload_filename("Radiohead - Creep - Live") == (
        "Radiohead",
        "Creep - Live",
    )


def test_official_channel_name_is_cleaned() -> None:
    assert split_upload_filename("Official Great White TV - Bad Boys") == (
        "Great White",
        "Bad Boys",
    )


def test_embedded_title_artist_wins_over_unrelated_uploader_tag() -> None:
    assert (
        prefer_filename_artist(
            "Harakiri Diat - SNÕÕPER - INVENTORY (OFFICIAL MUSIC VIDEO)",
            "Harakiri Diat",
        )
        == "Snõõper"
    )


def test_channel_suffix_is_removed_when_channel_is_the_artist() -> None:
    assert (
        prefer_filename_artist(
            "SNõõPER TV - Snõõper - Powerball (Official Music Video)",
            "SNõõPER TV",
        )
        == "Snõõper"
    )


def test_official_channel_spelling_canonicalises_plain_title_artist() -> None:
    assert (
        prefer_filename_artist(
            "SNõõPER TV - Snooper - Guard Dog (Official Video)",
            "SNõõPER TV",
        )
        == "Snõõper"
    )


def test_equivalent_diacritic_artist_prefix_without_spaced_dash_is_removed() -> None:
    assert clean_title("Snōōper- DEFECT", "Snõõper") == "DEFECT"


def test_self_titled_ep_uses_artist_as_release_lookup() -> None:
    assert release_lookup_title("S⧸T EP", "Snõõper") == "Snõõper"


def test_safe_name_obeys_utf8_component_budget() -> None:
    name = safe_name("🎵" * 100, "fallback")

    assert len(name.encode("utf-8")) <= 180
    assert name
