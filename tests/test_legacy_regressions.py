"""Regression tests migrated from the deployed processor."""

from music_processor.naming import (
    artists_match,
    clean_title,
    is_clean_title,
    normalise_artist_case,
)


def test_standard_case() -> None:
    assert (
        normalise_artist_case("The Presidents Of The United States Of America")
        == "The Presidents of the United States of America"
    )


def test_already_correct() -> None:
    assert (
        normalise_artist_case("The Presidents of the United States of America")
        == "The Presidents of the United States of America"
    )


def test_mixed_variant() -> None:
    assert (
        normalise_artist_case("The Presidents of The United States of America")
        == "The Presidents of the United States of America"
    )


def test_ac_dc() -> None:
    assert normalise_artist_case("AC/DC") == "AC/DC"


def test_dj_shadow() -> None:
    assert normalise_artist_case("DJ Shadow") == "DJ Shadow"


def test_queens_of_the_stone_age() -> None:
    assert normalise_artist_case("Queens Of The Stone Age") == "Queens of the Stone Age"


def test_single_name() -> None:
    assert normalise_artist_case("adele") == "Adele"


def test_bjork() -> None:
    assert normalise_artist_case("Björk") == "Björk"


def test_sigur_ros() -> None:
    assert normalise_artist_case("Sigur Rós") == "Sigur Rós"


def test_guns_n_roses() -> None:
    assert normalise_artist_case("Guns N' Roses") == "Guns N' Roses"


def test_10000_maniacs() -> None:
    assert normalise_artist_case("10,000 Maniacs") == "10,000 Maniacs"


def test_pink() -> None:
    assert normalise_artist_case("P!nk") == "P!nk"


def test_mgmt() -> None:
    assert normalise_artist_case("MGMT") == "MGMT"


def test_simon_garfunkel() -> None:
    assert normalise_artist_case("Simon & Garfunkel") == "Simon & Garfunkel"


def test_feat_lowercase() -> None:
    assert normalise_artist_case("Artist feat. Other Artist") == "Artist feat. Other Artist"


def test_ft_lowercase() -> None:
    assert normalise_artist_case("Eminem ft. Dido") == "Eminem ft. Dido"


def test_vs_lowercase() -> None:
    assert normalise_artist_case("Artist vs. Other") == "Artist vs. Other"


def test_jay_z() -> None:
    assert normalise_artist_case("Jay-Z") == "Jay-Z"


def test_run_dmc() -> None:
    assert normalise_artist_case("Run-DMC") == "Run-DMC"


def test_earth_wind_fire() -> None:
    assert normalise_artist_case("Earth Wind & Fire") == "Earth Wind & Fire"


def test_crosby_stills() -> None:
    assert normalise_artist_case("Crosby Stills Nash & Young") == "Crosby Stills Nash & Young"


def test_the_the() -> None:
    assert normalise_artist_case("The The") == "The The"


def test_alt_j() -> None:
    assert normalise_artist_case("Alt-J") == "Alt-J"


def test_clipping() -> None:
    assert normalise_artist_case("clipping.") == "Clipping."


def test_deadmau5() -> None:
    assert normalise_artist_case("deadmau5") == "Deadmau5"


def test_will_i_am_capitalised_since_indistinguishable() -> None:
    assert normalise_artist_case("will.i.am") == "Will.i.am"


def test_lcd_soundsystem() -> None:
    assert normalise_artist_case("LCD Soundsystem") == "LCD Soundsystem"


def test_nwa() -> None:
    assert normalise_artist_case("N.W.A") == "N.W.A"


def test_asap_rocky() -> None:
    assert normalise_artist_case("ASAP Rocky") == "ASAP Rocky"


def test_flying_lotus() -> None:
    assert normalise_artist_case("Flying Lotus") == "Flying Lotus"


def test_of_montreal() -> None:
    assert normalise_artist_case("of Montreal") == "Of Montreal"


def test_panic_at_the_disco() -> None:
    assert normalise_artist_case("Panic! At The Disco") == "Panic! at the Disco"


def test_twenty_one_pilots() -> None:
    assert normalise_artist_case("twenty one pilots") == "Twenty One Pilots"


def test_echo_the_bunnymen() -> None:
    assert normalise_artist_case("Echo & The Bunnymen") == "Echo & the Bunnymen"


def test_frank_ocean() -> None:
    assert normalise_artist_case("Frank Ocean") == "Frank Ocean"


def test_tyler_the_creator() -> None:
    assert normalise_artist_case("Tyler, The Creator") == "Tyler, The Creator"


def test_exact() -> None:
    assert artists_match("The Beatles", "The Beatles")


def test_case_insensitive() -> None:
    assert artists_match("the beatles", "THE BEATLES")


def test_the_prefix() -> None:
    assert artists_match("The Beatles", "Beatles")


def test_different_artists() -> None:
    assert not artists_match("The Beatles", "The Rolling Stones")


def test_united_states_vs_presidents() -> None:
    assert not artists_match(
        "The United States of America", "The Presidents of the United States of America"
    )


def test_the_quitters_vs_presidents() -> None:
    assert not artists_match("The Quitters", "The Presidents of the United States of America")


def test_feat() -> None:
    assert artists_match("Eminem", "Eminem feat. Dido")


def test_both_feat() -> None:
    assert artists_match("Eminem feat. Dido", "Eminem feat. Someone Else")


def test_ft() -> None:
    assert artists_match("Eminem", "Eminem ft. Dido")


def test_featuring() -> None:
    assert artists_match("Eminem", "Eminem featuring Dido")


def test_short_vs_long() -> None:
    assert not artists_match("Air", "The Presidents of the United States of America")


def test_empty() -> None:
    assert artists_match("", "The Beatles")


def test_jay_z_vs_jay_z() -> None:
    assert artists_match("Jay-Z", "JAY-Z")


def test_accent() -> None:
    assert artists_match("Beyoncé", "Beyonce")


def test_jay_z_vs_kanye() -> None:
    assert not artists_match("Jay-Z", "Kanye West")


def test_the_weeknd() -> None:
    assert artists_match("The Weeknd", "Weeknd")


def test_war_vs_war_on_drugs() -> None:
    assert not artists_match("War", "The War on Drugs")


def test_eagles_vs_eagles_of_death_metal() -> None:
    assert not artists_match("Eagles", "Eagles of Death Metal")


def test_nick_cave_bad_seeds() -> None:
    assert artists_match("Nick Cave", "Nick Cave & the Bad Seeds")


def test_ratm_case() -> None:
    assert artists_match("Rage Against the Machine", "Rage Against The Machine")


def test_ac_dc_case() -> None:
    assert artists_match("AC/DC", "ac/dc")


def test_metallica_vs_metallica_tribute() -> None:
    assert not artists_match("Metallica", "Ameritz - Tributes")


def test_comma_separated_feat() -> None:
    assert not artists_match("Metallica", "Metallica, Marianne Faithfull")


def test_drake_vs_drake_bell() -> None:
    assert not artists_match("Drake", "Drake Bell")


def test_kanye_vs_kanye_west_short_names_too_risky() -> None:
    assert not artists_match("Kanye", "Kanye West")


def test_plain() -> None:
    assert is_clean_title("Peaches")


def test_legit_brackets() -> None:
    assert is_clean_title("Man (Opposable Thumb)")


def test_feat_in_title() -> None:
    assert is_clean_title("Song (feat. Someone)")


def test_satisfaction() -> None:
    assert is_clean_title("(I Can't Get No) Satisfaction")


def test_song_2() -> None:
    assert is_clean_title("Song 2")


def test_99_problems() -> None:
    assert is_clean_title("99 Problems")


def test_7_nation_army() -> None:
    assert is_clean_title("7 Nation Army")


def test_bare_year_title() -> None:
    assert is_clean_title("1979")


def test_mr_brightside() -> None:
    assert is_clean_title("Mr. Brightside")


def test_ellipsis() -> None:
    assert is_clean_title("...Baby One More Time")


def test_censored() -> None:
    assert is_clean_title("F**k You (Forget You)")


def test_hyphenated() -> None:
    assert is_clean_title("Rock-a-bye Baby")


def test_part_number() -> None:
    assert is_clean_title("Song, Pt. 1")


def test_number_in_title() -> None:
    assert is_clean_title("99 Luftballons")


def test_punctuation_title() -> None:
    assert is_clean_title("Y.M.C.A.")


def test_slash_in_title() -> None:
    assert is_clean_title("Back in Black / You Shook Me")


def test_question_mark() -> None:
    assert is_clean_title("Should I Stay or Should I Go?")


def test_official_audio() -> None:
    assert not is_clean_title("Song (Official Audio)")


def test_official_music_video() -> None:
    assert not is_clean_title("Song (Official Music Video)")


def test_lyric_video() -> None:
    assert not is_clean_title("Song (Lyric Video)")


def test_hd_music_video() -> None:
    assert not is_clean_title("Song (Official HD Music Video)")


def test_album_version() -> None:
    assert is_clean_title("Munky River (Love Everybody album version 2005)")


def test_version_a() -> None:
    assert is_clean_title("Lump (Version A)")


def test_remastered() -> None:
    assert is_clean_title("Song (Remastered 2011)")


def test_year_brackets() -> None:
    assert is_clean_title("Song [2023]")


def test_explicit() -> None:
    assert not is_clean_title("Song [Explicit]")


def test_live() -> None:
    assert is_clean_title("Song [Live]")


def test_hq() -> None:
    assert not is_clean_title("Song [HQ]")


def test_radio_edit() -> None:
    assert is_clean_title("Song (Radio Edit)")


def test_extended_mix() -> None:
    assert is_clean_title("Song (Extended Mix)")


def test_single_edit() -> None:
    assert is_clean_title("Song (Single Edit)")


def test_album_edit() -> None:
    assert is_clean_title("Song (Album Edit)")


def test_acoustic_version() -> None:
    assert is_clean_title("Song (Acoustic Version)")


def test_live_at_venue() -> None:
    assert is_clean_title("Song (Live at Wembley)")


def test_demo() -> None:
    assert is_clean_title("Song (Demo)")


def test_standard_dash() -> None:
    assert clean_title("The Beatles - Hey Jude (Official Audio)", "The Beatles") == "Hey Jude"


def test_repeated_dash() -> None:
    assert (
        clean_title("The Beatles - The Beatles - Hey Jude (Official Audio)", "The Beatles")
        == "Hey Jude"
    )


def test_eminem_style() -> None:
    assert clean_title("Eminem - Lose Yourself (Official Music Video)", "Eminem") == "Lose Yourself"


def test_beyonce() -> None:
    assert clean_title("Beyoncé - Halo (Video)", "Beyoncé") == "Halo"


def test_radiohead() -> None:
    assert clean_title("Radiohead - Creep (Official Video)", "Radiohead") == "Creep"


def test_nirvana_remastered() -> None:
    assert (
        clean_title("Nirvana - Smells Like Teen Spirit (Remastered 2021)", "Nirvana")
        == "Smells Like Teen Spirit (Remastered 2021)"
    )


def test_explicit_stripped() -> None:
    assert clean_title("Song [Explicit]") == "Song"


def test_radio_edit_2() -> None:
    assert clean_title("Song (Radio Edit)") == "Song (Radio Edit)"


def test_extended_mix_2() -> None:
    assert clean_title("Song (Extended Mix)") == "Song (Extended Mix)"


def test_single_edit_2() -> None:
    assert clean_title("Song (Single Edit)") == "Song (Single Edit)"


def test_acoustic() -> None:
    assert clean_title("Song (Acoustic Version)") == "Song (Acoustic Version)"


def test_album_version_2() -> None:
    assert (
        clean_title("Munky River (Love Everybody album version 2005)")
        == "Munky River (Love Everybody album version 2005)"
    )


def test_remastered_2() -> None:
    assert clean_title("Song (Remastered 2011)") == "Song (Remastered 2011)"


def test_feat_preserved() -> None:
    assert clean_title("Song (feat. Someone)") == "Song (feat. Someone)"


def test_legit_brackets_2() -> None:
    assert clean_title("Man (Opposable Thumb)") == "Man (Opposable Thumb)"


def test_ellipsis_2() -> None:
    assert clean_title("...", "") == "..."


def test_satisfaction_2() -> None:
    assert clean_title("(I Can't Get No) Satisfaction", "") == "(I Can't Get No) Satisfaction"


def test_non_latin() -> None:
    assert clean_title("Sigur Rós - Ára bátur (Official Audio)", "Sigur Rós") == "Ára bátur"


def test_empty_2() -> None:
    assert clean_title("") == ""


def test_metallica_colon() -> None:
    assert (
        clean_title("Metallica: Enter Sandman (Official Music Video)", "Metallica")
        == "Enter Sandman"
    )


def test_metallica_colon_no_junk() -> None:
    assert clean_title("Metallica: One", "Metallica") == "One"


def test_repeated_colon() -> None:
    assert clean_title("Metallica: Metallica: Enter Sandman", "Metallica") == "Enter Sandman"


def test_colon_with_remastered() -> None:
    assert (
        clean_title("Metallica: Master of Puppets (Remastered)", "Metallica")
        == "Master of Puppets (Remastered)"
    )


def test_colon_non_metallica() -> None:
    assert clean_title("Radiohead: Creep (Official Video)", "Radiohead") == "Creep"


def test_colon_with_feat() -> None:
    assert (
        clean_title("Jay-Z: Empire State of Mind (feat. Alicia Keys)", "Jay-Z")
        == "Empire State of Mind (feat. Alicia Keys)"
    )


def test_colon_with_explicit() -> None:
    assert clean_title("Eminem: Lose Yourself [Explicit]", "Eminem") == "Lose Yourself"


def test_ac_dc_colon() -> None:
    assert clean_title("AC/DC: Highway to Hell (Official Video)", "AC/DC") == "Highway to Hell"


def test_pipe_suffix_removed() -> None:
    assert clean_title("Song Title | Official Audio", "Artist") == "Song Title"


def test_hashtag_in_title() -> None:
    assert clean_title("#1 Crush", "") == "#1 Crush"


def test_cover_tag_preserved() -> None:
    assert clean_title("Creep (Cover)", "") == "Creep (Cover)"


def test_tribute_preserved() -> None:
    assert (
        clean_title("Smells Like Teen Spirit (Tribute)", "") == "Smells Like Teen Spirit (Tribute)"
    )


def test_part_1() -> None:
    assert clean_title("Song, Pt. 1 (Official Audio)", "Artist") == "Song, Pt. 1"


def test_chapter_format() -> None:
    assert clean_title("Artist - Song (Chapter 1)", "Artist") == "Song (Chapter 1)"


def test_vevo_suffix() -> None:
    assert clean_title("Song - Artist - Vevo", "Artist") == "Song"


def test_topic_format_artist_prefix() -> None:
    assert clean_title("Song - Artist - Topic", "Artist") == "Song"


def test_em_dash_separator() -> None:
    assert (
        clean_title(
            "Daryl Hall & John Oates – Hold on to Yourself (Official Audio)",
            "Daryl Hall & John Oates",
        )
        == "Hold on to Yourself"
    )


def test_em_dash_with_remaster() -> None:
    assert clean_title("Rednex – Bottleneck Bob (Official Video)", "Rednex") == "Bottleneck Bob"


def test_pipe_separator() -> None:
    assert clean_title("STYX | These Are the Times", "STYX") == "These Are the Times"


def test_quoted_title_stripped() -> None:
    assert clean_title("The Offspring - “Self Esteem”", "The Offspring") == "Self Esteem"


def test_quoted_with_junk() -> None:
    assert (
        clean_title("The Offspring - “Bad Habit” (Full Album Stream)", "The Offspring")
        == "Bad Habit"
    )


def test_alternate_take() -> None:
    assert is_clean_title("Song (Alternate Take)")


def test_bonus_track() -> None:
    assert is_clean_title("Song (Bonus Track)")


def test_reprise() -> None:
    assert is_clean_title("Song (Reprise Version)")


def test_medley() -> None:
    assert is_clean_title("Song (Medley)")


def test_yule_log_visualizer() -> None:
    assert not is_clean_title("Song (Yule Log Visualizer)")


def test_visualiser_uk_spelling() -> None:
    assert not is_clean_title("Song (Official Visualiser)")


def test_visualizer_us_spelling() -> None:
    assert not is_clean_title("Song (Visualizer)")


def test_stereo_mix() -> None:
    assert is_clean_title("Song (Stereo Mix)")


def test_pcm_stereo() -> None:
    assert is_clean_title("Song (PCM Stereo)")


def test_audio_alone() -> None:
    assert not is_clean_title("Song (Audio)")


def test_7_inch_version() -> None:
    assert is_clean_title("Song (7-inch Mono Edit)")


def test_square_bracket_remaster_with_dash() -> None:
    assert is_clean_title("Song [2019 - Remaster]")


def test_chronicle_in_title_preserved() -> None:
    assert is_clean_title("Chronicle, Part 1")


def test_medley_as_part_of_real_title() -> None:
    assert is_clean_title("Medley of Songs")


def test_alternate_take_preserved() -> None:
    assert clean_title("Song (Alternate Take)") == "Song (Alternate Take)"


def test_bonus_track_preserved() -> None:
    assert clean_title("Song (Bonus Track)") == "Song (Bonus Track)"


def test_reprise_preserved() -> None:
    assert clean_title("Song (Reprise Version)") == "Song (Reprise Version)"


def test_rednex_chronicle_stripped() -> None:
    assert (
        clean_title("Rednex - Riding Alone (Official Audio) + Chronicle 1992-94 (Part 1)", "Rednex")
        == "Riding Alone"
    )


def test_stereo_mix_preserved() -> None:
    assert clean_title("Song (Stereo Mix)") == "Song (Stereo Mix)"


def test_audio_alone_stripped() -> None:
    assert clean_title("Song (Audio)") == "Song"


def test_visualiser_stripped() -> None:
    assert clean_title("Song (Official Visualiser)") == "Song"


def test_7_inch_preserved() -> None:
    assert clean_title("Song (7-inch Mono Edit)") == "Song (7-inch Mono Edit)"


def test_square_bracket_remaster_with_dash_2() -> None:
    assert clean_title("Song [2019 - Remaster]") == "Song [2019 - Remaster]"


def test_ozzy_all_caps_prefix() -> None:
    assert (
        clean_title("OZZY OSBOURNE - No More Tears (Official Video)", "Ozzy Osbourne")
        == "No More Tears"
    )


def test_question_mark_in_title_preserved() -> None:
    assert clean_title("Is Anybody There?", "") == "Is Anybody There?"


def test_54_46_number_title_preserved() -> None:
    assert clean_title("54-46 That's My Number", "") == "54-46 That's My Number"


def test_hall_and_oates_ampersand() -> None:
    assert artists_match("Daryl Hall & John Oates", "Daryl Hall And John Oates")


def test_huey_lewis_ampersand_vs_and() -> None:
    assert artists_match("Huey Lewis & The News", "Huey Lewis And The News")


def test_george_thorogood_ampersand_vs_and() -> None:
    assert artists_match("George Thorogood & The Destroyers", "George Thorogood And The Destroyers")


def test_comma_does_not_imply_artist_separator() -> None:
    assert not artists_match("Elton John", "Elton John, Kiki Dee")


def test_ozzy_all_caps_vs_normal() -> None:
    assert artists_match("OZZY OSBOURNE", "Ozzy Osbourne")


def test_black_sabbath_all_caps_vs_normal() -> None:
    assert artists_match("BLACK SABBATH", "Black Sabbath")
