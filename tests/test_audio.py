# -*- coding: utf-8 -*-
"""Selection, show rules, and original-language lookup."""

import json
import os
import sqlite3
import sys
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "resources", "lib"))

from choose import choose_audio, map_kodi_audio, resolve_priorities
from identify import merge_info, normalize_info
from languages import (
    LANGUAGE_CHOICES,
    LANGUAGES,
    SETTING_ROWS,
    is_audio_description,
    is_commentary,
    language_matches,
    priority_value,
    spec_from_text,
)
from paths import is_extra_path, is_trailer_path, suggested_name, title_match, year_from_parents
from rules import canonicalize_action, load_rules, match_rule, playback_plan, save_rules, upsert_rule
from tmdb import (
    LanguageCache,
    clear_language_cache,
    helper_api_key_from_source,
    lookup_helper_db,
    pick_result,
    resolve_original,
    search_original,
    search_titles,
)
from titles import merge_hits


def stream(index, language, name="", channels=2, default=False, original=False, bitrate=0):
    return {
        "index": index,
        "language": language,
        "name": name,
        "channels": channels,
        "bitrate": bitrate,
        "isdefault": default,
        "isoriginal": original,
    }


class LanguageTests(unittest.TestCase):
    def test_known_codes_and_names(self):
        self.assertTrue(language_matches(stream(0, "en"), spec_from_text("English")))
        self.assertTrue(language_matches(stream(0, "deu"), spec_from_text("German")))
        self.assertTrue(language_matches(stream(0, "jp"), spec_from_text("Japanese")))
        self.assertTrue(language_matches(stream(0, "nb"), spec_from_text("Norwegian")))
        self.assertTrue(language_matches(stream(0, "zh"), spec_from_text("Chinese")))
        self.assertTrue(language_matches(stream(0, "pt"), spec_from_text("Portuguese")))
        self.assertTrue(language_matches(stream(0, "pt-br", "Portuguese"), spec_from_text("Portuguese (Brazil)")))

    def test_portuguese_leaves_brazilian_tracks(self):
        brazilian = stream(0, "pt-br", "Brazilian Portuguese")
        self.assertFalse(language_matches(brazilian, spec_from_text("Portuguese")))
        self.assertTrue(language_matches(brazilian, spec_from_text("Portuguese (Brazil)")))
        self.assertFalse(language_matches(stream(0, "pt", "Brazil"), spec_from_text("por")))

    def test_short_codes_stay_out_of_track_names(self):
        self.assertFalse(language_matches(stream(0, "", "this is high quality"), spec_from_text("Hindi")))
        self.assertFalse(language_matches(stream(0, "", "normal dialogue"), spec_from_text("Norwegian")))
        self.assertFalse(language_matches(stream(0, "", "jp"), spec_from_text("Japanese")))

    def test_custom_code(self):
        spec = spec_from_text("cym")
        self.assertEqual(spec["label"], "cym")
        self.assertTrue(language_matches(stream(0, "cym"), spec))

    def test_multilingual_commentary_and_audio_description(self):
        self.assertTrue(is_commentary({"language": "ger", "name": "Audiokommentar"}))
        self.assertTrue(is_commentary({"language": "fre", "name": "Commentaire du réalisateur"}))
        self.assertTrue(is_commentary({"language": "jpn", "name": "オーディオコメンタリー"}))
        self.assertTrue(is_commentary({"language": "eng", "name": "Stereo", "iscommentary": True}))
        self.assertFalse(is_commentary({"language": "eng", "name": "English 5.1"}))

        self.assertTrue(is_audio_description({"language": "eng", "name": "English (Audio Description)"}))
        self.assertTrue(is_audio_description({"language": "eng", "name": "English [AD]"}))
        self.assertTrue(is_audio_description({"language": "ger", "name": "Audiodeskription"}))
        self.assertTrue(is_audio_description({"language": "eng", "name": "English 5.1", "isvisualimpaired": True}))
        self.assertFalse(is_audio_description({"language": "eng", "name": "English 5.1"}))
        self.assertFalse(is_audio_description({"language": "eng", "name": "Headphone mix"}))


class ChooseTests(unittest.TestCase):
    def test_commentary_is_skipped_when_a_dialogue_track_exists(self):
        streams = [
            stream(0, "eng", "Director commentary", channels=2, default=True),
            stream(1, "eng", "Stereo", channels=2),
        ]
        priorities = [{"slot": 1, "code": "eng", "custom": ""}]
        resolved, waiting = resolve_priorities(priorities, None, "eng", False)
        self.assertFalse(waiting)
        pref, picked = choose_audio(streams, resolved, "", True)
        self.assertEqual(picked["index"], 1)

    def test_commentary_only_misses_that_priority(self):
        streams = [stream(0, "eng", "Commentary", default=True), stream(1, "deu", "Deutsch")]
        priorities = [
            {"slot": 1, "code": "eng", "custom": ""},
            {"slot": 2, "code": "ger", "custom": ""},
        ]
        resolved, _waiting = resolve_priorities(priorities, None, "", True)
        _pref, picked = choose_audio(streams, resolved, "", True)
        self.assertEqual(picked["index"], 1)

    def test_default_priority_skips_a_commentary_default(self):
        streams = [stream(0, "eng", "Commentary", default=True)]
        resolved, _waiting = resolve_priorities([{"slot": 1, "code": "default", "custom": ""}], None, "", True)
        pref, picked = choose_audio(streams, resolved, "", True)
        self.assertIsNone(pref)
        self.assertIsNone(picked)

    def test_default_flag_outranks_channel_count(self):
        streams = [
            stream(0, "eng", channels=8),
            stream(1, "eng", channels=2, default=True),
            stream(2, "eng", channels=6, original=True),
        ]
        resolved, _waiting = resolve_priorities([{"slot": 1, "code": "eng", "custom": ""}], None, "", True)
        _pref, picked = choose_audio(streams, resolved, "", True)
        self.assertEqual(picked["index"], 1)

    def test_original_flag_outranks_channels_when_nothing_is_default(self):
        streams = [
            stream(0, "eng", channels=8),
            stream(1, "eng", channels=2, original=True),
        ]
        resolved, _waiting = resolve_priorities([{"slot": 1, "code": "eng", "custom": ""}], None, "", True)
        _pref, picked = choose_audio(streams, resolved, "", True)
        self.assertEqual(picked["index"], 1)

    def test_prefer_quality_outranks_default_flag(self):
        streams = [
            stream(0, "eng", "AC3 5.1", channels=6, default=True, bitrate=640000),
            stream(1, "eng", "TrueHD 7.1", channels=8, bitrate=4500000),
        ]
        resolved, _waiting = resolve_priorities([{"slot": 1, "code": "eng", "custom": ""}], None, "", True)
        _pref, picked_default = choose_audio(streams, resolved, "", True, prefer_quality=False)
        self.assertEqual(picked_default["index"], 0)
        _pref, picked_quality = choose_audio(streams, resolved, "", True, prefer_quality=True)
        self.assertEqual(picked_quality["index"], 1)

    def test_audio_description_is_skipped_when_avoid_ad_enabled(self):
        streams = [
            stream(0, "eng", "English (Audio Description)", channels=6, default=True),
            stream(1, "eng", "English 5.1", channels=6),
        ]
        resolved, _waiting = resolve_priorities([{"slot": 1, "code": "eng", "custom": ""}], None, "", True)
        _pref, picked = choose_audio(streams, resolved, "", True, avoid_ad=True)
        self.assertEqual(picked["index"], 1)
        _pref, picked_allow = choose_audio(streams, resolved, "", True, avoid_ad=False)
        self.assertEqual(picked_allow["index"], 0)

    def test_original_language_uses_the_lookup_before_the_flag(self):
        streams = [
            stream(0, "eng", original=True),
            stream(1, "jpn", "日本語", channels=6),
        ]
        resolved, _waiting = resolve_priorities([{"slot": 1, "code": "original", "custom": ""}], None, "", True)
        _pref, picked = choose_audio(streams, resolved, "ja", True)
        self.assertEqual(picked["index"], 1)

    def test_kodi_setting_waits_until_it_can_be_read(self):
        priorities = [{"slot": 1, "code": "kodi", "custom": ""}]
        resolved, waiting = resolve_priorities(priorities, None, "eng", False)
        self.assertTrue(waiting)
        self.assertEqual(resolved, [])
        resolved, waiting = resolve_priorities(priorities, "mediadefault", "eng", False)
        self.assertFalse(waiting)
        self.assertEqual(resolved[0]["kind"], "default")
        self.assertEqual(map_kodi_audio("original", "eng")["kind"], "original")
        self.assertEqual(map_kodi_audio("default", "fra")["label"], "French")
        self.assertIsNone(map_kodi_audio("none", "eng"))


class RuleTests(unittest.TestCase):
    def test_titles_match_with_a_year_and_leave_longer_titles(self):
        self.assertTrue(title_match("Dark", "Dark"))
        self.assertTrue(title_match("Dark", "Dark (2017)"))
        self.assertFalse(title_match("Dark", "Dark Matter"))
        self.assertTrue(title_match("Amélie", "Amélie (2001)"))
        self.assertTrue(title_match("進撃の巨人", "進撃の巨人 (2013)"))
        self.assertFalse(title_match("進撃の巨人", "進撃の巨人 劇場版"))

    def test_show_rule_fallback_appends_main_priorities(self):
        prefs = self._prefs()
        rules = [{"name": "Bluey", "action": "jpn", "custom": ""}]
        info = {"mediatype": "episode", "showtitle": "Bluey", "title": "Keepy Uppy", "path": "/x.mkv"}
        kind, plan, reason = playback_plan(info, prefs, rules)
        self.assertEqual((kind, reason), ("use", "show"))
        self.assertEqual([item["code"] for item in plan], ["jpn", "original", "default"])
        prefs["show_rule_fallback"] = False
        kind, plan, reason = playback_plan(info, prefs, rules)
        self.assertEqual([item["code"] for item in plan], ["jpn"])

    def test_paths_and_years(self):
        self.assertTrue(is_trailer_path(r"D:\films\Trailers\teaser.mkv"))
        self.assertTrue(is_trailer_path("/films/Movie-trailer.mkv"))
        self.assertFalse(is_trailer_path("/films/Movie.mkv"))
        self.assertTrue(is_extra_path("/films/extras/intro.mkv"))
        self.assertTrue(is_extra_path("/films/Behind the Scenes.mkv"))
        self.assertTrue(is_extra_path("/films/deleted scene.mkv"))
        self.assertEqual(year_from_parents(r"D:\shows\Dark (2017)\Season 1\e.mkv"), "2017")

    def test_episode_title_is_not_a_candidate(self):
        prefs = self._prefs()
        rules = [{"name": "Pilot", "action": "eng", "custom": ""}]
        info = {
            "mediatype": "episode",
            "showtitle": "Other Show",
            "title": "Pilot",
            "path": "/shows/Other Show/Season 1/Pilot.mkv",
        }
        kind, _plan, reason = playback_plan(info, prefs, rules)
        self.assertEqual((kind, reason), ("use", "main"))
        self.assertEqual(suggested_name(info), "Other Show")

    def test_playback_plan_for_trailers_extras_and_shows(self):
        prefs = self._prefs()
        prefs["extra_mode"] = "original"
        rules = [
            {"name": "Bluey", "action": "eng", "custom": ""},
            {"name": "Dark", "action": "leave", "custom": ""},
        ]
        self.assertEqual(
            playback_plan({"path": "/films/Trailers/teaser.mkv", "title": "Teaser"}, prefs, rules)[:2],
            ("skip", "trailer"),
        )
        kind, plan, reason = playback_plan({"path": "/films/extras/intro.mkv", "title": "Intro"}, prefs, rules)
        self.assertEqual((kind, reason), ("use", "extra"))
        self.assertEqual(plan, [{"slot": 0, "code": "original", "custom": ""}])
        kind, plan, reason = playback_plan(
            {"mediatype": "episode", "showtitle": "Bluey", "title": "Hammerbarn", "path": "/x.mkv"},
            prefs,
            rules,
        )
        self.assertEqual((kind, reason, plan[0]["code"]), ("use", "show", "eng"))
        self.assertEqual(
            playback_plan(
                {"mediatype": "episode", "showtitle": "Dark", "title": "Secrets", "path": "/x.mkv"},
                prefs,
                rules,
            ),
            ("skip", "show"),
        )

    def test_names_become_language_codes(self):
        self.assertEqual(canonicalize_action("German"), ("ger", ""))
        self.assertEqual(canonicalize_action("English"), ("eng", ""))
        self.assertEqual(canonicalize_action("Welsh"), ("custom", "welsh"))

    def test_rules_roundtrip_and_replace(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "showrules.json")
            rules = upsert_rule([], "Bluey", "English")
            rules = upsert_rule(rules, "bluey", "German")
            save_rules(rules, path)
            loaded = load_rules(path)
            self.assertEqual(loaded, [{"name": "Bluey", "action": "ger", "custom": ""}])
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{")
            self.assertEqual(load_rules(path), [])

    def test_linked_shows_stay_separate_and_match_by_id(self):
        dark = {"tmdb": "70523", "year": "2017", "mediatype": "tvshow", "imdb": "tt5753856"}
        other = {"tmdb": "999", "year": "2015", "mediatype": "tvshow"}
        rules = upsert_rule([], "Dark", "English", identity=dark)
        rules = upsert_rule(rules, "Dark", "German", identity=other)
        self.assertEqual(sorted(rule["action"] for rule in rules), ["eng", "ger"])
        episode = {
            "mediatype": "episode",
            "showtitle": "Dunkel",
            "title": "Secrets",
            "year": "2017",
            "tmdb": "70523",
            "path": "/shows/Dark/e.mkv",
        }
        self.assertEqual(match_rule(episode, rules)["action"], "eng")
        episode["tmdb"] = "999"
        self.assertEqual(match_rule(episode, rules)["action"], "ger")
        movie = {"mediatype": "movie", "title": "Dark", "year": "2017", "tmdb": "70523", "path": "/m.mkv"}
        self.assertIsNone(match_rule(movie, rules))
        folder = {
            "mediatype": "episode",
            "showtitle": "",
            "title": "Secrets",
            "path": "/shows/Dark (2017)/Season 1/Secrets.mkv",
        }
        self.assertEqual(match_rule(folder, rules)["tmdb"], "70523")
        unnamed = {"mediatype": "episode", "showtitle": "Dark", "title": "Secrets", "path": "/x.mkv"}
        self.assertIsNone(match_rule(unnamed, rules))
        original = [rule for rule in rules if rule["tmdb"] == "70523"][0]
        rules = upsert_rule(rules, "dark", "Japanese", identity=original)
        updated = [rule for rule in rules if rule["tmdb"] == "70523"][0]
        self.assertEqual(updated["name"], "Dark")
        self.assertEqual(updated["action"], "jpn")
        self.assertEqual(len(rules), 2)

    def _prefs(self):
        return {
            "priorities": [
                {"slot": 1, "code": "original", "custom": ""},
                {"slot": 2, "code": "default", "custom": ""},
            ],
            "trailer_mode": "leave",
            "trailer_language": "eng",
            "trailer_custom": "",
            "extra_mode": "leave",
            "extra_language": "eng",
            "extra_custom": "",
        }


class IdentifyTests(unittest.TestCase):
    def test_show_year_and_ids_win_for_an_episode(self):
        info = normalize_info(
            {
                "type": "episode",
                "title": "Winter Is Coming",
                "showtitle": "Game of Thrones",
                "year": 2011,
                "premiered": "2011-04-17",
                "tvshowid": 12,
                "uniqueid": {"tmdb": "63056", "imdb": "tt1480055"},
                "file": "/shows/Game of Thrones/e.mkv",
            },
            {"original_language": ["en", ""]},
            {
                "title": "Game of Thrones",
                "year": 2011,
                "premiered": "2011-04-17",
                "tvshowid": 12,
                "uniqueid": {"tmdb": "1399", "imdb": "tt0944947"},
            },
        )
        self.assertEqual(info["tmdb"], "1399")
        self.assertEqual(info["imdb"], "tt0944947")
        self.assertEqual(info["library_id"], "12")
        self.assertEqual(info["year"], "2011")
        self.assertEqual(info["original_hints"], ["en"])
        episode_year = normalize_info(
            {"type": "episode", "title": "E", "showtitle": "Show", "year": 2020, "file": "/a.mkv"},
            {},
            {"title": "Show", "year": 2011},
        )
        self.assertEqual(episode_year["year"], "2011")

    def test_merge_keeps_an_earlier_id(self):
        current = {"tmdb": "603", "title": "", "original_hints": ["en"]}
        merged = merge_info(current, {"tmdb": "1", "title": "The Matrix", "original_hints": ["en", "ja"]})
        self.assertEqual(merged["tmdb"], "603")
        self.assertEqual(merged["title"], "The Matrix")
        self.assertEqual(merged["original_hints"], ["en", "ja"])


class TmdbTests(unittest.TestCase):
    def test_pick_result_requires_the_exact_title_and_year(self):
        results = [
            {"title": "Dark Matter", "release_date": "2015-01-01", "original_language": "en", "popularity": 5},
            {"title": "Dark", "release_date": "2017-12-01", "original_language": "de", "popularity": 9},
            {"title": "Dark", "release_date": "1999-01-01", "original_language": "fr", "popularity": 1},
            {"name": "進撃の巨人", "first_air_date": "2013-04-07", "original_language": "ja", "popularity": 50},
            {"title": "Amélie", "release_date": "2001-04-25", "original_language": "fr", "popularity": 30},
        ]
        self.assertEqual(pick_result(results, "Dark", "2017"), "de")
        self.assertEqual(pick_result(results, "Dark", "2016"), "de")
        self.assertEqual(pick_result(results, "Dark", "1990"), "")
        self.assertEqual(pick_result(results, "Dark Matter", ""), "en")
        self.assertEqual(pick_result(results, "進撃の巨人", "2013"), "ja")
        self.assertEqual(pick_result(results, "Amélie", "2001"), "fr")

    def test_title_search_returns_the_show_and_the_movie(self):
        class Response(object):
            def __init__(self, payload):
                self.payload = json.dumps(payload).encode("utf-8")

            def read(self):
                return self.payload

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        def opener(request, timeout=6):
            if "/search/tv" in request.full_url:
                return Response({"results": [
                    {"id": 70523, "name": "Dark", "first_air_date": "2017-12-01"},
                ]})
            if "/search/movie" in request.full_url:
                return Response({"results": [
                    {"id": 286928, "title": "Dark", "release_date": "2015-04-17"},
                ]})
            raise AssertionError("unexpected")

        hits = search_titles("Dark", "testkey", opener)
        self.assertEqual(
            [(hit["mediatype"], hit["tmdb"], hit["year"]) for hit in hits],
            [("tvshow", "70523", "2017"), ("movie", "286928", "2015")],
        )
        library = [{
            "name": "Dark",
            "year": "2017",
            "mediatype": "tvshow",
            "tmdb": "70523",
            "imdb": "tt5753856",
            "library_id": "4",
        }]
        merged = merge_hits(library, hits)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["library_id"], "4")
        self.assertEqual(merged[0]["imdb"], "tt5753856")
        self.assertEqual(merged[1]["mediatype"], "movie")

    def test_cache_keeps_hits_longer_than_misses(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "original_language.json")
            now = {"at": 1_000_000.0}
            cache = LanguageCache(path, now=lambda: now["at"])
            cache.put(["movie:tmdb:603"], "en", "tmdb")
            cache.put(["movie:title:missing:"], "", "tmdb")
            now["at"] += 4 * 24 * 3600
            again = LanguageCache(path, now=lambda: now["at"])
            self.assertEqual(again.get(["movie:tmdb:603"]), ("en", "tmdb", True))
            self.assertEqual(again.get(["movie:title:missing:"]), ("", "", False))
            now["at"] += 40 * 24 * 3600
            later = LanguageCache(path, now=lambda: now["at"])
            self.assertFalse(later.get(["movie:tmdb:603"])[2])

    def test_helper_database_reads_column_custom_and_json(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "ItemDetails.db")
            connection = sqlite3.connect(path)
            connection.execute(
                "CREATE TABLE movie (id TEXT, tmdb_id INTEGER, imdb_id TEXT, original_language TEXT, language TEXT)"
            )
            connection.execute(
                "INSERT INTO movie VALUES ('movie.603', 603, 'tt0133093', 'en', 'en-US')"
            )
            connection.execute("CREATE TABLE custom (key TEXT, value TEXT, parent_id TEXT)")
            connection.execute(
                "INSERT INTO custom VALUES ('original_language', 'ko', 'tv.1399')"
            )
            connection.execute("CREATE TABLE stored_metadata (item_id TEXT, family_id TEXT, data TEXT)")
            connection.execute(
                "INSERT INTO stored_metadata VALUES ('movie.550', 'movie.550', ?)",
                (json.dumps({"original_language": "en", "spoken_languages": [{"iso_639_1": "fr"}]}),),
            )
            connection.execute("CREATE TABLE unique_id (key TEXT, value TEXT, parent_id TEXT)")
            connection.execute("INSERT INTO unique_id VALUES ('imdb', 'tt0137523', 'movie.550')")
            connection.execute("CREATE TABLE baseitem (id TEXT, language TEXT)")
            connection.execute("INSERT INTO baseitem VALUES ('movie.1', 'en-US')")
            connection.commit()
            connection.close()

            self.assertEqual(lookup_helper_db(path, {"mediatype": "movie", "tmdb": "603"}), "en")
            self.assertEqual(lookup_helper_db(path, {"mediatype": "episode", "tmdb": "1399"}), "ko")
            self.assertEqual(lookup_helper_db(path, {"mediatype": "movie", "imdb": "tt0137523"}), "en")
            self.assertEqual(lookup_helper_db(path, {"mediatype": "movie", "tmdb": "1"}), "")

    def test_api_search_and_direct_id(self):
        calls = []

        class Response(object):
            def __init__(self, payload):
                self.payload = json.dumps(payload).encode("utf-8")

            def read(self):
                return self.payload

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        def opener(request, timeout=6):
            calls.append(request.full_url)
            url = request.full_url
            if "/movie/603" in url:
                return Response({"original_language": "en"})
            if "/search/tv" in url:
                return Response({"results": [
                    {"name": "Dark Matter", "first_air_date": "2015-06-01", "original_language": "en", "popularity": 4},
                    {"name": "Dark", "first_air_date": "2017-12-01", "original_language": "de", "popularity": 20},
                ]})
            if "/find/tt0944947" in url:
                return Response({"tv_results": [{"original_language": "en"}], "movie_results": []})
            raise AssertionError(url)

        with tempfile.TemporaryDirectory() as folder:
            cache = LanguageCache(os.path.join(folder, "cache.json"), now=lambda: time.time())
            language, source = search_original(
                {"mediatype": "movie", "tmdb": "603", "title": "The Matrix"},
                "testkey",
                [],
                cache,
                opener=opener,
            )
            self.assertEqual((language, source), ("en", "tmdb"))
            self.assertIn("api_key=testkey", calls[0])
            calls.clear()
            language, source = search_original(
                {"mediatype": "episode", "showtitle": "Dark", "title": "Secrets", "year": "2017"},
                "testkey",
                [],
                cache,
                opener=opener,
            )
            self.assertEqual((language, source), ("de", "tmdb"))
            language, source = search_original(
                {"mediatype": "tvshow", "imdb": "tt0944947", "showtitle": "Game of Thrones"},
                "testkey",
                [],
                cache,
                opener=opener,
            )
            self.assertEqual((language, source), ("en", "tmdb"))

    def test_file_language_wins_over_the_network(self):
        def opener(_request, timeout=6):
            raise AssertionError("network")

        class Cache(object):
            def get(self, _keys):
                return "en", "tmdb", True

            def put(self, *_args):
                raise AssertionError("cache write")

        language, source = resolve_original(
            [stream(0, "ja", original=True), stream(1, "eng", default=True)],
            ["de"],
            {"title": "Film"},
            True,
            "testkey",
            [],
            Cache(),
            opener=opener,
        )
        self.assertEqual((language, source), ("ja", "file"))

    def test_helper_language_wins_when_the_file_disagrees(self):
        def opener(_request, timeout=6):
            raise AssertionError("network")

        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "ItemDetails.db")
            connection = sqlite3.connect(path)
            connection.execute(
                "CREATE TABLE movie (id TEXT, tmdb_id INTEGER, original_language TEXT)"
            )
            connection.execute("INSERT INTO movie VALUES ('movie.603', 603, 'ko')")
            connection.commit()
            connection.close()
            language, source = resolve_original(
                [stream(0, "ja", original=True), stream(1, "eng", default=True)],
                ["de"],
                {"mediatype": "movie", "tmdb": "603", "title": "Parasite"},
                True,
                "testkey",
                [path],
                None,
                opener=opener,
            )
            self.assertEqual((language, source), ("ko", "tmdbhelper"))
            language, source = resolve_original(
                [stream(0, "eng", default=True)],
                ["ja"],
                {"mediatype": "movie", "tmdb": "603", "title": "Parasite"},
                True,
                "testkey",
                [path],
                None,
                opener=opener,
            )
            self.assertEqual((language, source), ("ko", "tmdbhelper"))

        language, source = resolve_original(
            [stream(0, "eng", original=True)],
            [],
            {"title": "Film"},
            True,
            "testkey",
            [],
            None,
            opener=opener,
            helper_hints=["ja"],
        )
        self.assertEqual((language, source), ("ja", "tmdbhelper"))

    def test_matching_helper_language_keeps_the_file_value(self):
        language, source = resolve_original(
            [stream(0, "jpn", original=True)],
            [],
            {"title": "Film"},
            True,
            "",
            [],
            None,
            helper_hints=["ja"],
        )
        self.assertEqual((language, source), ("jpn", "file"))

    def test_helper_key_reader_ignores_the_token(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "resources", "tmdbhelper", "lib", "api", "api_keys")
            os.makedirs(path)
            with open(os.path.join(path, "tmdb.py"), "w", encoding="utf-8") as handle:
                handle.write(
                    "API_KEY = '0123456789abcdef'\n"
                    "API_TOKEN = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.payload.sig'\n"
                )
            self.assertEqual(helper_api_key_from_source(folder), "0123456789abcdef")

    def test_a_miss_is_cached_only_when_a_key_was_used(self):
        def opener(_request, timeout=6):
            return _Empty()

        class _Empty(object):
            def read(self):
                return b'{"results": []}'

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "cache.json")
            cache = LanguageCache(path, now=lambda: 10.0)
            language, source = search_original(
                {"mediatype": "movie", "title": "Nope"},
                "",
                [],
                cache,
            )
            self.assertEqual((language, source), ("", ""))
            self.assertFalse(os.path.isfile(path))

    def test_network_error_is_not_cached_and_expired_entries_are_pruned(self):
        def failing_opener(_request, timeout=6):
            raise OSError("temporary network outage")

        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "cache.json")
            now = {"at": 1_000_000.0}
            cache = LanguageCache(path, now=lambda: now["at"])
            language, source = search_original(
                {"mediatype": "movie", "tmdb": "603", "title": "The Matrix"},
                "testkey",
                [],
                cache,
                opener=failing_opener,
            )
            self.assertEqual((language, source), ("", ""))
            self.assertFalse(os.path.isfile(path))

            cache.put(["movie:title:stale:"], "", "tmdb")
            now["at"] += 4 * 24 * 3600
            cache.put(["movie:tmdb:603"], "en", "tmdb")
            with open(path, "r", encoding="utf-8") as handle:
                stored = json.load(handle)
            self.assertNotIn("movie:title:stale:", stored)
            self.assertIn("movie:tmdb:603", stored)
            self.assertTrue(clear_language_cache(path))
            self.assertFalse(os.path.isfile(path))
            self.assertFalse(clear_language_cache(path))


class PackageTests(unittest.TestCase):
    def test_settings_match_the_language_table_and_strings(self):
        settings = ET.parse(os.path.join(ROOT, "resources", "settings.xml"))
        strings = _string_ids()
        for node in settings.iter():
            for attr in ("label", "help"):
                value = node.attrib.get(attr, "")
                if value.isdigit():
                    self.assertIn(value, strings)
            if node.tag == "option" and (node.attrib.get("label") or "").isdigit():
                self.assertIn(node.attrib["label"], strings)
        by_id = {node.attrib["id"]: node for node in settings.iter("setting")}
        self.assertEqual(by_id["lang_1"].find("default").text, "original")
        self.assertEqual(by_id["lang_2"].find("default").text, "default")
        self.assertEqual(by_id["lang_3"].find("default").text, "off")
        self.assertEqual(by_id["avoid_commentary"].find("default").text, "true")
        self.assertEqual(by_id["avoid_ad"].find("default").text, "true")
        self.assertEqual(by_id["prefer_quality"].find("default").text, "false")
        self.assertEqual(by_id["use_tmdb"].find("default").text, "true")
        self.assertEqual(by_id["notify"].find("default").text, "changed")
        self.assertEqual(by_id["show_rule_fallback"].find("default").text, "true")
        self.assertEqual(by_id["trailer_mode"].find("default").text, "leave")
        self.assertEqual(by_id["extra_mode"].find("default").text, "leave")
        self.assertEqual(
            by_id["manage_shows"].find("data").text,
            "RunScript(service.audio.enforcer)",
        )
        self.assertEqual(
            by_id["clear_cache"].find("data").text,
            "RunScript(service.audio.enforcer, clear_cache)",
        )
        for data_node in settings.iter("data"):
            text = data_node.text or ""
            for forbidden in ("C:/", "C:\\", "/Users/", "/home/"):
                self.assertNotIn(forbidden, text)
        names = _string_messages()
        self.assertEqual([row[0] for row in SETTING_ROWS], ["off", "original", "default", "kodi", "custom"])
        self.assertEqual(names.get("32150"), "Custom audio language")
        self.assertEqual(names.get(str(SETTING_ROWS[-1][1])), SETTING_ROWS[-1][2])
        for code, string_id, fallback in SETTING_ROWS:
            self.assertEqual(names.get(str(string_id)), fallback)
            self.assertNotIn(code, LANGUAGE_CHOICES)
        for setting_id in ("lang_1", "lang_2", "lang_3", "lang_4", "lang_5"):
            stored = by_id[setting_id]
            options = stored.findall("./constraints/options/option")
            values = [item.text for item in options]
            labels = [item.attrib.get("label") for item in options]
            self.assertEqual(stored.find("control").attrib.get("type"), "list")
            self.assertEqual(values[:4], ["off", "original", "default", "kodi"])
            self.assertEqual(labels[:4], ["32095", "32087", "32088", "32089"])
            self.assertEqual(values[4:], list(LANGUAGE_CHOICES))
            _assert_language_labels(self, options[4:], names)
            self.assertNotIn("RunScript", ET.tostring(stored, encoding="unicode"))
            self.assertNotIn(setting_id + "_text", by_id)
        for setting_id in ("trailer_language", "extra_language"):
            options = by_id[setting_id].findall("./constraints/options/option")
            values = [item.text for item in options]
            self.assertEqual(values, list(LANGUAGE_CHOICES))
            self.assertEqual(by_id[setting_id].find("default").text, "eng")
            self.assertEqual(by_id[setting_id].find("control").attrib.get("type"), "list")
            _assert_language_labels(self, options, names)
        self.assertNotIn("trailer_custom", by_id)
        self.assertNotIn("extra_custom", by_id)
        edits = [
            node.attrib.get("id")
            for node in settings.iter("setting")
            if (
                node.find("control") is not None
                and node.find("control").attrib.get("type") == "edit"
                and _visible_rules(node) < 2
            )
        ]
        self.assertEqual(edits, ["tmdb_apikey"])

    def test_addon_manifest(self):
        addon = ET.parse(os.path.join(ROOT, "addon.xml")).getroot()
        self.assertEqual(addon.attrib["id"], "service.audio.enforcer")
        self.assertEqual(addon.attrib["version"], "1.1.0")
        self.assertEqual(addon.attrib["name"], "Audio Enforcer")
        points = [node.attrib["point"] for node in addon.findall("extension")]
        self.assertEqual(points[0], "xbmc.service")
        self.assertIn("xbmc.python.script", points)
        script = addon.find("extension[@point='xbmc.python.script']")
        self.assertEqual(script.find("provides").text, "executable")
        self.assertEqual(script.attrib["library"], "resources/lib/showrules.py")
        strings = _string_ids()
        for node in addon.iter("label"):
            if (node.text or "").isdigit():
                self.assertIn(node.text, strings)

    def test_modules_import_without_kodi(self):
        self.assertIn("eng", LANGUAGES)
        self.assertTrue(LANGUAGE_CHOICES)

    def test_priority_value_reads_labels_and_codes(self):
        self.assertEqual(priority_value("Original language"), "original")
        self.assertEqual(priority_value("original"), "original")
        self.assertEqual(priority_value("Default track"), "default")
        self.assertEqual(priority_value("Kodi audio language"), "kodi")
        self.assertEqual(priority_value("Off"), "off")
        self.assertEqual(priority_value("English"), "eng")
        self.assertEqual(priority_value("eng"), "eng")
        self.assertEqual(priority_value("Japanese"), "jpn")
        self.assertEqual(priority_value(""), "")

    def test_sources_do_not_vendor_a_tmdb_key(self):
        banned = "a07324c669cac4d9" + "6789197134ce272b"
        for folder, _dirs, names in os.walk(ROOT):
            for name in names:
                if name.endswith((".png", ".pyc")):
                    continue
                path = os.path.join(folder, name)
                with open(path, "r", encoding="utf-8", errors="ignore") as handle:
                    self.assertNotIn(banned, handle.read(), path)


def _po_entries():
    path = os.path.join(ROOT, "resources", "language", "resource.language.en_gb", "strings.po")
    entries = []
    current = None
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line.startswith("msgctxt "):
                current = line.split('"')[1].lstrip("#")
            elif line.startswith("msgid ") and current:
                entries.append((current, line.split('"')[1]))
                current = None
    return entries


def _string_ids():
    return {entry[0] for entry in _po_entries()}


def _string_messages():
    return {entry[0]: entry[1] for entry in _po_entries()}


def _visible_rules(node):
    return len([
        item for item in node.findall("./dependencies/dependency")
        if item.attrib.get("type") == "visible"
    ])


def _assert_language_labels(test, options, names):
    """Kodi hides an option unless its label is a string id."""
    for item in options:
        label = item.attrib.get("label") or ""
        test.assertTrue(label.isdigit(), item.text)
        test.assertEqual(names.get(label), LANGUAGES[item.text]["label"])


class ServiceTests(unittest.TestCase):
    def _import_service(self):
        import types

        fake_xbmc = types.ModuleType("xbmc")
        fake_xbmc.LOGINFO = 1
        fake_xbmc.LOGDEBUG = 0
        fake_xbmc.LOGERROR = 3

        class _Player(object):
            def __init__(self):
                self._playing_video = True
                self._playing = True
                self._file = "/shows/Dark (2017)/Season 1/e01.mkv"

            def isPlayingVideo(self):
                return self._playing_video

            def isPlaying(self):
                return self._playing

            def getPlayingFile(self):
                return self._file

        class _Monitor(object):
            def abortRequested(self):
                return False

            def waitForAbort(self, _timeout):
                return True

        fake_xbmc.Player = _Player
        fake_xbmc.Monitor = _Monitor
        fake_xbmc.log = lambda *_args, **_kwargs: None

        fake_addon = types.ModuleType("xbmcaddon")
        fake_vfs = types.ModuleType("xbmcvfs")

        saved = {name: sys.modules.get(name) for name in ("xbmc", "xbmcaddon", "xbmcvfs", "kodiio", "service")}
        sys.modules["xbmc"] = fake_xbmc
        sys.modules["xbmcaddon"] = fake_addon
        sys.modules["xbmcvfs"] = fake_vfs
        sys.modules.pop("kodiio", None)
        sys.modules.pop("service", None)
        import kodiio
        import service
        return service, kodiio, saved

    def _restore(self, saved):
        for name, mod in saved.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod

    def test_single_stream_short_circuits_without_tmdb_or_notification(self):
        service, kodiio, saved = self._import_service()
        try:
            notified = []
            tmdb_called = []
            kodiio.load_preferences = lambda: {
                "enabled": True,
                "avoid_commentary": True,
                "avoid_ad": True,
                "prefer_quality": False,
                "notify": True,
                "notify_mode": "changed",
                "use_tmdb": True,
                "tmdb_apikey": "key",
                "show_rule_fallback": True,
                "priorities": [{"slot": 1, "code": "original", "custom": ""}],
                "trailer_mode": "leave",
                "trailer_language": "eng",
                "trailer_custom": "",
                "extra_mode": "leave",
                "extra_language": "eng",
                "extra_custom": "",
            }
            kodiio.show_rules_path = lambda: ""
            kodiio.video_player_id = lambda: 1
            kodiio.playing_info = lambda _pid: {
                "mediatype": "movie",
                "title": "Solo",
                "path": "/movies/Solo.mkv",
            }
            kodiio.audio_state = lambda _pid: ([stream(0, "eng", default=True)], stream(0, "eng", default=True))
            kodiio.tmdb_credentials = lambda _key: (tmdb_called.append(True) or ("key", []))
            kodiio.notify = lambda msg, changed=True, mode=None: notified.append((msg, changed, mode))

            player = service.AudioEnforcer()
            player.onPlayBackStarted()
            player.tick()
            # Force stream stability window to elapse
            player._sig_since -= service.STABLE_SECONDS + 0.5
            player.tick()

            self.assertTrue(player._done)
            self.assertTrue(player.is_idle())
            self.assertEqual(tmdb_called, [])
            self.assertEqual(notified, [])
        finally:
            self._restore(saved)

    def test_settings_cached_until_invalidated_and_switch_notifies(self):
        service, kodiio, saved = self._import_service()
        try:
            pref_loads = []
            switched = []
            notified = []

            def load_prefs():
                pref_loads.append(1)
                return {
                    "enabled": True,
                    "avoid_commentary": True,
                    "avoid_ad": True,
                    "prefer_quality": False,
                    "notify": True,
                    "notify_mode": "changed",
                    "use_tmdb": False,
                    "tmdb_apikey": "",
                    "show_rule_fallback": True,
                    "priorities": [{"slot": 1, "code": "jpn", "custom": ""}],
                    "trailer_mode": "leave",
                    "trailer_language": "eng",
                    "trailer_custom": "",
                    "extra_mode": "leave",
                    "extra_language": "eng",
                    "extra_custom": "",
                }

            kodiio.load_preferences = load_prefs
            kodiio.show_rules_path = lambda: ""
            kodiio.video_player_id = lambda: 1
            kodiio.playing_info = lambda _pid: {
                "mediatype": "movie",
                "title": "Spirited Away",
                "path": "/movies/Spirited Away.mkv",
            }
            streams = [stream(0, "eng", default=True), stream(1, "jpn", channels=6)]
            kodiio.audio_state = lambda _pid: (streams, streams[0])
            kodiio.set_audio_stream = lambda pid, idx: (switched.append((pid, idx)) or True)
            kodiio.notify = lambda msg, changed=True, mode=None: notified.append((msg, changed, mode))

            player = service.AudioEnforcer()
            player.tick()
            player.tick()
            self.assertEqual(len(pref_loads), 1)

            player.invalidate_settings()
            player.onPlayBackStarted()
            player.tick()
            self.assertEqual(len(pref_loads), 2)
            player._sig_since -= service.STABLE_SECONDS + 0.5
            player.tick()

            self.assertEqual(switched, [(1, 1)])
            self.assertEqual(len(notified), 1)
            self.assertTrue(notified[0][1])
            self.assertEqual(notified[0][2], "changed")
            self.assertTrue(player.is_idle())
        finally:
            self._restore(saved)


if __name__ == "__main__":
    unittest.main()
