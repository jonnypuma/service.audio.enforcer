# -*- coding: utf-8 -*-
"""Kodi settings, JSON-RPC, and paths. Imported only while the add-on is running."""

import json
import os

import xbmc
import xbmcaddon
import xbmcvfs

from tmdb import HELPER_ID, helper_api_key_from_source

ADDON_ID = "service.audio.enforcer"
ADDON = None
ADDON_NAME = "Audio Enforcer"

_FILE_ORIGINAL_LABELS = (
    "VideoPlayer.Property(original_language)",
    "VideoPlayer.Property(OriginalLanguage)",
)
_HELPER_ORIGINAL_LABELS = (
    "VideoPlayer.Property(TMDbHelper.original_language)",
    "Window(home).Property(TMDbHelper.Player.original_language)",
    "Window(home).Property(TMDbHelper.original_language)",
)

_ID_LABELS = {
    "tmdb": (
        "VideoPlayer.UniqueID(tmdb)",
        "VideoPlayer.Property(tmdb_id)",
        "VideoPlayer.Property(tmdb)",
        "Window(home).Property(TMDbHelper.Player.tmdb)",
    ),
    "imdb": (
        "VideoPlayer.UniqueID(imdb)",
        "VideoPlayer.Property(imdb_id)",
        "VideoPlayer.Property(imdb)",
        "Window(home).Property(TMDbHelper.Player.imdb)",
    ),
}


def translate(path):
    if hasattr(xbmcvfs, "translatePath"):
        return xbmcvfs.translatePath(path)
    return xbmc.translatePath(path)


def log(message, level=None):
    xbmc.log("{0}: {1}".format(ADDON_NAME, message), xbmc.LOGINFO if level is None else level)


def addon():
    global ADDON, ADDON_NAME
    if ADDON is None:
        ADDON = xbmcaddon.Addon(ADDON_ID)
        ADDON_NAME = ADDON.getAddonInfo("name") or ADDON_NAME
    return ADDON


def reset_addon():
    """Discard the cached Addon handle so updated settings are read fresh."""
    global ADDON
    ADDON = None


def profile_path():
    path = translate(addon().getAddonInfo("profile"))
    if path and not os.path.isdir(path):
        try:
            os.makedirs(path)
        except OSError:
            pass
    return path


def show_rules_path():
    return os.path.join(profile_path(), "showrules.json")


def language_cache_path():
    return os.path.join(profile_path(), "original_language.json")


def _setting(addon_obj, setting_id, default=""):
    try:
        value = addon_obj.getSettingString(setting_id)
    except Exception:
        try:
            value = addon_obj.getSetting(setting_id)
        except Exception:
            return default
    if value is None:
        return default
    return str(value).strip()


def _bool_setting(addon_obj, setting_id, default=False):
    try:
        return bool(addon_obj.getSettingBool(setting_id))
    except Exception:
        raw = _setting(addon_obj, setting_id, "")
        if not raw:
            return default
        return raw.lower() in {"1", "true", "yes"}


def string_setting(setting_id, default=""):
    value = _setting(addon(), setting_id, default)
    return value or default


def bool_setting(setting_id, default=False):
    return _bool_setting(addon(), setting_id, default)


def localized(string_id, fallback):
    try:
        text = addon().getLocalizedString(string_id)
    except Exception:
        text = ""
    text = (text or "").strip()
    if not text or text == str(string_id):
        return fallback
    return text


def notify_mode():
    """Return 'off', 'changed', or 'always'. Maps legacy boolean values."""
    raw = string_setting("notify", "changed").strip().lower()
    if raw in ("off", "false", "0", "no"):
        return "off"
    if raw in ("always", "true", "1", "yes"):
        return "always"
    return "changed"


def load_preferences():
    """Current settings that decide which audio track is chosen."""
    from languages import priority_value

    priorities = []
    for slot in range(1, 6):
        code = priority_value(string_setting("lang_{0}".format(slot), "off"))
        if not code or code in ("off", "custom"):
            continue
        priorities.append({
            "slot": slot,
            "code": code,
            "custom": "",
        })
    mode = notify_mode()
    return {
        "enabled": bool_setting("enabled", True),
        "avoid_commentary": bool_setting("avoid_commentary", True),
        "avoid_ad": bool_setting("avoid_ad", True),
        "prefer_quality": bool_setting("prefer_quality", False),
        "notify": mode != "off",
        "notify_mode": mode,
        "use_tmdb": bool_setting("use_tmdb", True),
        "tmdb_apikey": string_setting("tmdb_apikey", ""),
        "show_rule_fallback": bool_setting("show_rule_fallback", True),
        "priorities": priorities,
        "trailer_mode": string_setting("trailer_mode", "leave").lower() or "leave",
        "trailer_language": string_setting("trailer_language", "eng").lower() or "eng",
        "trailer_custom": "",
        "extra_mode": string_setting("extra_mode", "leave").lower() or "leave",
        "extra_language": string_setting("extra_language", "eng").lower() or "eng",
        "extra_custom": "",
    }


def json_call(method, params=None):
    payload = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        payload["params"] = params
    raw = xbmc.executeJSONRPC(json.dumps(payload))
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("error"):
        return None
    return data.get("result")


def video_player_id():
    result = json_call("Player.GetActivePlayers")
    if not isinstance(result, list):
        return None
    for player in result:
        if isinstance(player, dict) and player.get("type") == "video":
            return player.get("playerid")
    return None


def player_item(playerid):
    properties = [
        "title",
        "originaltitle",
        "showtitle",
        "file",
        "season",
        "episode",
        "year",
        "premiered",
        "uniqueid",
        "imdbnumber",
        "tvshowid",
        "id",
        "type",
    ]
    result = json_call("Player.GetItem", {
        "playerid": playerid,
        "properties": properties,
    })
    if result is None:
        result = json_call("Player.GetItem", {
            "playerid": playerid,
            "properties": [name for name in properties if name != "tvshowid"],
        })
    if not isinstance(result, dict):
        return {}
    item = result.get("item")
    return item if isinstance(item, dict) else {}


def _positive_id(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return number if number > 0 else 0


def tvshow_details(tvshowid):
    try:
        tvshowid = int(tvshowid)
    except (TypeError, ValueError):
        return {}
    if tvshowid < 0:
        return {}
    result = json_call("VideoLibrary.GetTVShowDetails", {
        "tvshowid": tvshowid,
        "properties": ["title", "year", "premiered", "uniqueid", "imdbnumber"],
    })
    if not isinstance(result, dict):
        return {}
    details = result.get("tvshowdetails")
    return details if isinstance(details, dict) else {}


def movie_details(movieid):
    movieid = _positive_id(movieid)
    if not movieid:
        return {}
    result = json_call("VideoLibrary.GetMovieDetails", {
        "movieid": movieid,
        "properties": ["title", "year", "premiered", "uniqueid", "imdbnumber"],
    })
    if not isinstance(result, dict):
        return {}
    details = result.get("moviedetails")
    return details if isinstance(details, dict) else {}


def _child_show_id(method, id_name, details_name, item_id):
    item_id = _positive_id(item_id)
    if not item_id:
        return 0
    result = json_call(method, {
        id_name: item_id,
        "properties": ["tvshowid"],
    })
    if not isinstance(result, dict):
        return 0
    details = result.get(details_name)
    if not isinstance(details, dict):
        return 0
    return _positive_id(details.get("tvshowid"))


def search_library(query):
    """TV shows and movies in the Kodi library whose title contains the query."""
    from titles import hits_from_library

    query = " ".join(str(query or "").split())
    if len(query) < 2:
        return []
    properties = ["title", "year", "premiered", "uniqueid", "imdbnumber"]
    filt = {"field": "title", "operator": "contains", "value": query}
    limits = {"start": 0, "end": 25}
    shows = json_call("VideoLibrary.GetTVShows", {
        "filter": filt,
        "properties": properties,
        "limits": limits,
    })
    movies = json_call("VideoLibrary.GetMovies", {
        "filter": filt,
        "properties": properties,
        "limits": limits,
    })
    show_rows = shows.get("tvshows") if isinstance(shows, dict) else []
    movie_rows = movies.get("movies") if isinstance(movies, dict) else []
    return hits_from_library(show_rows, movie_rows)


def context_title():
    """The library show or movie the context menu was opened on."""
    from titles import hit_from_library_details, make_hit

    dbtype = _label("ListItem.DBType").lower()
    dbid = _label("ListItem.DBID")
    show_id = _positive_id(_label("ListItem.TvShowDBID"))
    if dbtype == "episode":
        show_id = show_id or _child_show_id(
            "VideoLibrary.GetEpisodeDetails", "episodeid", "episodedetails", dbid
        )
    elif dbtype == "season":
        show_id = show_id or _child_show_id(
            "VideoLibrary.GetSeasonDetails", "seasonid", "seasondetails", dbid
        )
    if dbtype in ("episode", "season", "tvshow") and (show_id or dbtype == "tvshow"):
        details = tvshow_details(show_id or dbid)
        if details and show_id and not details.get("tvshowid"):
            details = dict(details)
            details["tvshowid"] = show_id
        hit = hit_from_library_details(details, "tvshow")
        if hit.get("name"):
            return hit
    if dbtype == "movie":
        hit = hit_from_library_details(movie_details(dbid), "movie")
        if hit.get("name"):
            return hit
    show = _label("ListItem.TvShowTitle")
    title = _label("ListItem.Title") or _label("ListItem.Label")
    year = _label("ListItem.Year") or _label("ListItem.Premiered")
    if dbtype in ("episode", "season", "tvshow"):
        name = show or title
        kind = "tvshow"
        tmdb = ""
        imdb = ""
        library_id = show_id
    elif dbtype == "movie":
        name = title or show
        kind = "movie"
        tmdb = _label("ListItem.UniqueID(tmdb)") or _label("ListItem.Property(tmdb_id)")
        imdb = _label("ListItem.UniqueID(imdb)") or _label("ListItem.IMDBNumber")
        library_id = dbid
    else:
        name = show or title
        kind = "tvshow" if show else ""
        tmdb = ""
        imdb = ""
        library_id = ""
    if kind in ("tvshow", "movie") and not tmdb:
        tmdb = _label("ListItem.UniqueID(tmdb)") if dbtype in ("tvshow", "movie") else ""
    return make_hit(name, year, kind, tmdb, imdb, library_id)


def audio_state(playerid):
    """Return (streams, current stream). Streams is None when the player could not be read."""
    result = json_call("Player.GetProperties", {
        "playerid": playerid,
        "properties": ["audiostreams", "currentaudiostream"],
    })
    if not isinstance(result, dict):
        return None, None
    streams = result.get("audiostreams")
    if not isinstance(streams, list):
        streams = []
    current = result.get("currentaudiostream")
    if not isinstance(current, dict):
        current = {}
    return streams, current


def read_kodi_audio_setting():
    """Kodi's preferred audio language, '' when empty, or None if it could not be read."""
    result = json_call("Settings.GetSettingValue", {"setting": "locale.audiolanguage"})
    if isinstance(result, dict) and "value" in result:
        return str(result.get("value") or "").strip().lower()
    if isinstance(result, str):
        return result.strip().lower()
    return None


def gui_language_code():
    formats = (
        getattr(xbmc, "ISO_639_2", None),
        getattr(xbmc, "ISO_639_1", None),
        getattr(xbmc, "ENGLISH_NAME", None),
    )
    for fmt in formats:
        if fmt is None:
            continue
        try:
            value = xbmc.getLanguage(fmt)
        except Exception:
            value = ""
        value = (value or "").strip()
        if value:
            return value
    return ""


def _label(name):
    try:
        return (xbmc.getInfoLabel(name) or "").strip()
    except Exception:
        return ""


def is_live_tv():
    """True when Kodi reports that Live TV is currently playing."""
    try:
        if xbmc.getCondVisibility("VideoPlayer.Content(livetv)"):
            return True
    except Exception:
        pass
    return bool(_label("VideoPlayer.ChannelName"))


def player_labels():
    """Info labels that scrapers and TheMovieDB Helper may have set."""
    hints = [_label(name) for name in _FILE_ORIGINAL_LABELS]
    helper_hints = [_label(name) for name in _HELPER_ORIGINAL_LABELS]
    labels = {
        "showtitle": _label("VideoPlayer.TvShowTitle"),
        "title": _label("VideoPlayer.Title"),
        "file": _label("Player.Filenameandpath") or _label("VideoPlayer.Filenameandpath"),
        "dbtype": (_label("VideoPlayer.DBType") or "").lower(),
        "year": _label("VideoPlayer.Year"),
        "premiered": _label("VideoPlayer.Premiered") or _label("VideoPlayer.Year"),
        "imdbnumber": _label("VideoPlayer.IMDBNumber"),
        "livetv": is_live_tv(),
        "original_language": [value for value in hints if value],
        "helper_language": [value for value in helper_hints if value],
    }
    for key, names in _ID_LABELS.items():
        for name in names:
            value = _label(name)
            if value:
                labels[key] = value
                break
    return labels


def playing_info(playerid):
    """Best description of the video that is playing."""
    from identify import merge_info, normalize_info

    item = player_item(playerid) if playerid is not None else {}
    labels = player_labels()
    if not item.get("file"):
        try:
            labels["file"] = labels.get("file") or xbmc.Player().getPlayingFile()
        except Exception:
            pass
    show = {}
    mediatype = (item.get("type") or labels.get("dbtype") or "").lower()
    show_id = item.get("tvshowid")
    if show_id in (None, "", -1, 0) and mediatype in ("episode", "season", ""):
        show_id = _label("VideoPlayer.TvShowDBID")
    if _positive_id(show_id) and mediatype in ("episode", "season", "", "tvshow"):
        loaded = tvshow_details(show_id)
        if loaded:
            show = loaded
            if not show.get("tvshowid"):
                show = dict(show)
                show["tvshowid"] = _positive_id(show_id)
        elif mediatype in ("episode", "season", "tvshow"):
            show = {"tvshowid": _positive_id(show_id)}
    return normalize_info(item, labels, show)


def set_audio_stream(playerid, index):
    result = json_call("Player.SetAudioStream", {
        "playerid": playerid,
        "stream": int(index),
    })
    return result is not None


def notify(message, changed=True, mode=None):
    active_mode = mode if mode is not None else notify_mode()
    if active_mode == "off":
        return
    if active_mode == "changed" and not changed:
        return
    import xbmcgui
    icon = xbmcgui.NOTIFICATION_INFO
    try:
        path = addon().getAddonInfo("icon")
        if path:
            icon = path
    except Exception:
        pass
    xbmcgui.Dialog().notification(ADDON_NAME, message, icon, 4000, False)


def clear_language_cache():
    from tmdb import clear_language_cache as _clear

    return _clear(language_cache_path())


def helper_installed():
    try:
        return bool(xbmc.getCondVisibility("System.HasAddon({0})".format(HELPER_ID)))
    except Exception:
        return False


def tmdb_credentials(user_key):
    """Return (api key, helper database paths). The user key wins when it is set."""
    user_key = (user_key or "").strip()
    paths = []
    helper = None
    if helper_installed():
        try:
            helper = xbmcaddon.Addon(HELPER_ID)
        except Exception:
            helper = None
    if helper is not None:
        paths = _helper_databases(helper)
        if not user_key:
            for setting_id in ("tmdb_apikey", "tmdb_api_key"):
                value = _setting(helper, setting_id, "")
                if value:
                    user_key = value
                    break
            if not user_key:
                try:
                    user_key = helper_api_key_from_source(helper.getAddonInfo("path"))
                except Exception:
                    user_key = ""
    return user_key, paths


def _helper_databases(helper):
    found = []
    candidates = []
    custom = _setting(helper, "cache_location", "")
    if custom:
        candidates.append(os.path.join(custom, "ItemDetails.db"))
    try:
        helper_profile = translate(helper.getAddonInfo("profile"))
    except Exception:
        helper_profile = ""
    if helper_profile:
        candidates.append(os.path.join(helper_profile, "ItemDetails.db"))
    sibling = os.path.normpath(os.path.join(profile_path(), "..", HELPER_ID, "ItemDetails.db"))
    candidates.append(sibling)
    for path in candidates:
        if path and os.path.isfile(path) and path not in found:
            found.append(path)
    return found
