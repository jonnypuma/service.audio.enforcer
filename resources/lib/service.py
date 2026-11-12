# -*- coding: utf-8 -*-
"""Select an audio track when a video starts."""

import threading
import time
import traceback
import urllib.request

import xbmc

import kodiio
from choose import (
    choose_audio,
    describe_stream,
    format_streams,
    needs_original,
    resolve_priorities,
    selection_message,
)
from rules import format_rule, load_rules, match_rule, playback_plan
from languages import same_language
from tmdb import LanguageCache, original_from_properties, original_from_streams, resolve_original

# How long to wait for audio streams to show up and settle.
AUDIO_WAIT = 8.0
STABLE_SECONDS = 1.0
# TheMovieDB is allowed a little longer than the stream list.
LOOKUP_WAIT = 14.0


class _Lookup(object):
    def __init__(self):
        self.done = False
        self.language = ""
        self.source = ""
        self.error = ""

    def start(self, func):
        def run():
            try:
                language, source = func()
                self.language = language or ""
                self.source = source or ""
            except Exception:
                self.error = traceback.format_exc()
            self.done = True

        threading.Thread(target=run, daemon=True).start()


class AudioEnforcer(xbmc.Player):
    """Switches the audio track once each time a video starts."""

    def __init__(self):
        xbmc.Player.__init__(self)
        self._session_mark = 0.0
        self._switch_at = 0.0
        self._stopped = False
        self._reset()
        kodiio.log("Service initialized")

    def _reset(self):
        self._pending = False
        self._active = False
        self._path = ""
        self._started = 0.0
        self._playerid = None
        self._done = False
        self._logged_streams = False
        self._not_playing_since = None
        self._last_sig = None
        self._sig_since = 0.0
        self._info = None
        self._lookup = None
        self._original = None
        self._original_source = ""
        self._switch_try = 0.0

    def onPlayBackStarted(self):
        try:
            self._request_session()
        except Exception:
            kodiio.log(
                "Error in onPlayBackStarted\n{0}".format(traceback.format_exc()),
                xbmc.LOGERROR,
            )

    def onAVStarted(self):
        try:
            if not self._pending and not self._active:
                self._request_session()
        except Exception:
            kodiio.log(
                "Error in onAVStarted\n{0}".format(traceback.format_exc()),
                xbmc.LOGERROR,
            )

    def onPlayBackStopped(self):
        self._stopped = True
        self._reset_if_idle()

    def onPlayBackEnded(self):
        self._stopped = True
        self._reset_if_idle()

    def onPlayBackError(self):
        self._stopped = True
        self._reset_if_idle()

    def _request_session(self):
        now = time.monotonic()
        try:
            path = self.getPlayingFile()
        except Exception:
            path = ""
        # Switching audio can emit another start event for the same file.
        if self._switch_at and (now - self._switch_at) < 3.0 and (not path or path == self._path):
            self._stopped = False
            return
        if self._stopped:
            self._stopped = False
        elif path and path == self._path and (self._pending or self._active):
            return
        elif not path and self._pending and (now - self._session_mark) < 1.0:
            return
        self._reset()
        self._pending = True
        self._path = path or ""
        self._session_mark = now

    def _reset_if_idle(self):
        try:
            if self.isPlaying():
                return
        except Exception:
            pass
        self._reset()

    def tick(self):
        if not kodiio.bool_setting("enabled", True):
            self._pending = False
            self._active = False
            return
        self._promote()
        if not self._active:
            return
        try:
            playing_video = self.isPlayingVideo()
        except Exception:
            playing_video = False
        if not playing_video:
            if self._not_playing_since is None:
                self._not_playing_since = time.monotonic()
            elif time.monotonic() - self._not_playing_since > 0.7:
                self._reset()
            return
        self._not_playing_since = None
        self._enforce()

    def _promote(self):
        if not self._pending or self._active:
            return
        try:
            video = self.isPlayingVideo()
            playing = self.isPlaying()
        except Exception:
            return
        if video:
            self._activate()
            return
        age = time.monotonic() - self._session_mark
        if playing and age > 2.0:
            self._pending = False
            kodiio.log("Audio playback, nothing to do", xbmc.LOGDEBUG)
        elif age > 8.0:
            self._pending = False

    def _activate(self):
        try:
            path = self.getPlayingFile()
        except Exception:
            path = ""
        if path:
            self._path = path
        self._pending = False
        self._active = True
        self._started = time.monotonic()
        self._playerid = None
        self._done = False
        self._logged_streams = False
        self._not_playing_since = None
        self._last_sig = None
        self._sig_since = 0.0
        self._info = None
        self._lookup = None
        self._original = None
        self._original_source = ""
        self._switch_try = 0.0
        name = self._path.replace("\\", "/").rsplit("/", 1)[-1] or "video"
        kodiio.log("Video playback started ({0})".format(name))

    def _player_id(self):
        if self._playerid is not None:
            return self._playerid
        playerid = kodiio.video_player_id()
        if playerid is not None:
            self._playerid = playerid
        return playerid

    def _remember_info(self, playerid):
        from identify import merge_info

        try:
            info = kodiio.playing_info(playerid)
        except Exception:
            kodiio.log("Could not read the playing item\n{0}".format(traceback.format_exc()), xbmc.LOGERROR)
            info = {"path": self._path}
        if self._path and not info.get("path"):
            info["path"] = self._path
        self._info = merge_info(self._info, info)
        return self._info

    def _enforce(self):
        if self._done:
            return
        elapsed = time.monotonic() - self._started
        timed_out = elapsed > AUDIO_WAIT
        playerid = self._player_id()
        if playerid is None:
            if timed_out:
                self._give_up("No video player was available for audio selection")
            return

        info = self._remember_info(playerid)
        if not _identified(info) and elapsed < 3.0 and not timed_out:
            return
        prefs = kodiio.load_preferences()
        try:
            rules = load_rules(kodiio.show_rules_path())
        except Exception:
            kodiio.log("Could not read show rules\n{0}".format(traceback.format_exc()), xbmc.LOGERROR)
            rules = []
        kind, plan, reason = _as_plan(playback_plan(info, prefs, rules))
        if kind == "skip":
            self._done = True
            kodiio.log("Left {0} unchanged".format(_skip_name(reason, info)))
            return

        streams, current = kodiio.audio_state(playerid)
        if streams is None:
            if timed_out:
                self._give_up("Audio streams could not be read")
            return
        if streams and not self._logged_streams:
            self._logged_streams = True
            kodiio.log("Audio streams: {0}".format(format_streams(streams)))

        signature = _signature(streams)
        if signature != self._last_sig:
            self._last_sig = signature
            self._sig_since = time.monotonic()
        stable = (time.monotonic() - self._sig_since) >= STABLE_SECONDS
        if not streams and not timed_out:
            return
        if streams and not stable and not timed_out:
            return

        kodi_value = None
        if any(pref.get("code") == "kodi" for pref in plan):
            kodi_value = kodiio.read_kodi_audio_setting()
        resolved, waiting = resolve_priorities(
            plan, kodi_value, kodiio.gui_language_code(), timed_out
        )
        if waiting:
            return
        if not resolved:
            self._done = True
            kodiio.log("No audio language priorities are set")
            return

        original = ""
        if needs_original(resolved):
            original, ready = self._original_language(streams, info, prefs, elapsed)
            if not ready:
                return

        pref, stream = choose_audio(
            streams, resolved, original, prefs.get("avoid_commentary", True)
        )
        if pref is None:
            self._give_up("No audio track matched. Available: {0}".format(format_streams(streams)))
            return

        current_index = current.get("index") if isinstance(current, dict) else None
        if current_index is not None and int(current_index) == int(stream["index"]):
            self._finish(pref, stream, reason, info, rules, changed=False)
            return
        if time.monotonic() - self._switch_try < 0.4:
            return
        self._switch_try = time.monotonic()
        if not kodiio.set_audio_stream(playerid, stream["index"]):
            self._playerid = None
            if timed_out:
                self._give_up("Could not select {0}".format(describe_stream(stream)))
            return
        self._switch_at = time.monotonic()
        self._finish(pref, stream, reason, info, rules, changed=True)

    def _original_language(self, streams, info, prefs, elapsed):
        """Return (language, ready). Ready is false while TheMovieDB Helper is still being read."""
        if self._original is not None:
            return self._original, True
        file_language = original_from_streams(streams)
        meta_language = "" if file_language else original_from_properties(info.get("original_hints"))
        local = file_language or meta_language
        if not prefs.get("use_tmdb", True):
            self._original = local
            self._original_source = "file" if file_language else ("metadata" if meta_language else "")
            self._log_original(local, self._original_source, "")
            return local, True
        if self._lookup is None:
            api_key, db_paths = kodiio.tmdb_credentials(prefs.get("tmdb_apikey"))
            cache = LanguageCache(kodiio.language_cache_path())
            snapshot = dict(info)
            snapshot["original_hints"] = list(info.get("original_hints") or [])
            snapshot["helper_hints"] = list(info.get("helper_hints") or [])
            stream_rows = [dict(stream) for stream in streams or [] if isinstance(stream, dict)]
            hint_rows = list(snapshot["original_hints"])
            helper_rows = list(snapshot["helper_hints"])
            lookup = _Lookup()
            lookup.start(lambda: resolve_original(
                stream_rows,
                hint_rows,
                snapshot,
                True,
                api_key,
                db_paths,
                cache,
                opener=urllib.request.urlopen,
                helper_hints=helper_rows,
            ))
            self._lookup = lookup
            kodiio.log("Checking the original language with TheMovieDB Helper")
        if not self._lookup.done:
            if elapsed > LOOKUP_WAIT:
                self._original = local
                self._original_source = "file" if file_language else ("metadata" if local else "")
                kodiio.log("Original language lookup did not finish in time")
                return self._original, True
            return "", False
        if self._lookup.error:
            kodiio.log("Original language lookup failed\n{0}".format(self._lookup.error), xbmc.LOGERROR)
        self._original = self._lookup.language or ""
        self._original_source = self._lookup.source or ""
        if not self._original and local:
            self._original = local
            self._original_source = "file" if file_language else "metadata"
        self._log_original(self._original, self._original_source, local)
        return self._original, True

    def _log_original(self, language, source, local):
        if language and local and source == "tmdbhelper" and not same_language(language, local):
            kodiio.log(
                "Original language {0} does not match TheMovieDB Helper ({1}). Using {1}.".format(
                    local, language
                )
            )
            return
        if language:
            kodiio.log("Original language {0} from {1}".format(language, _source_name(source)))
            return
        kodiio.log("Original language was not found")

    def _finish(self, pref, stream, reason, info, rules, changed):
        self._done = True
        prefix = "Selected" if changed else "Already using"
        rule = ""
        if reason == "show":
            matched = match_rule(info, rules)
            if matched is not None:
                rule = " ({0})".format(format_rule(matched))
        kodiio.log("{0} priority {1} {2}: {3}{4}".format(
            prefix, pref.get("slot") or 0, pref.get("label") or "", describe_stream(stream), rule
        ))
        kodiio.notify(selection_message(pref, stream))

    def _give_up(self, message):
        self._done = True
        kodiio.log(message)


def _as_plan(plan):
    if plan[0] == "skip":
        return "skip", [], plan[1]
    return "use", plan[1], plan[2]


def _skip_name(reason, info):
    if reason == "show":
        return (info or {}).get("showtitle") or (info or {}).get("title") or "this title"
    if reason == "trailer":
        return "trailer"
    if reason == "extra":
        return "extra"
    return reason or "item"


def _source_name(source):
    return {
        "file": "the file",
        "metadata": "item metadata",
        "cache": "a saved TheMovieDB result",
        "tmdbhelper": "TheMovieDB Helper",
        "tmdb": "TheMovieDB",
    }.get(source, source or "lookup")


def _identified(info):
    """True once a title is known, or the path is already a trailer or extra."""
    from paths import is_extra_path, is_trailer_path

    info = info or {}
    path = info.get("path") or ""
    if is_trailer_path(path) or is_extra_path(path):
        return True
    return bool(info.get("showtitle") or info.get("title") or info.get("tmdb") or info.get("imdb"))


def _signature(streams):
    rows = []
    for stream in streams:
        if not isinstance(stream, dict):
            continue
        rows.append((
            stream.get("index"),
            stream.get("language") or "",
            stream.get("name") or "",
            stream.get("channels"),
            bool(stream.get("isdefault")),
            bool(stream.get("isoriginal")),
        ))
    return tuple(rows)


def main():
    version = kodiio.addon().getAddonInfo("version")
    kodiio.log("{0} service starting".format(version))
    player = AudioEnforcer()
    monitor = xbmc.Monitor()
    try:
        while not monitor.abortRequested():
            try:
                player.tick()
            except Exception:
                kodiio.log("Service tick failed\n{0}".format(traceback.format_exc()), xbmc.LOGERROR)
            if monitor.waitForAbort(0.1):
                break
    except KeyboardInterrupt:
        pass
    finally:
        kodiio.log("Service stopped")
