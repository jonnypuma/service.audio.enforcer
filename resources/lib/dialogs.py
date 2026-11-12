# -*- coding: utf-8 -*-
"""Show-rule manager and the language picker."""

import xbmc
import xbmcgui

import kodiio
from languages import LANGUAGE_CHOICES, LANGUAGES, SETTING_ROWS, priority_value
from paths import suggested_name
from rules import (
    format_rule,
    load_rules,
    remove_rule,
    rule_key,
    save_rules,
    title_for_context,
    upsert_rule,
)
from titles import hit_from_playback, hit_label, linked


def _mode_rows(include_leave):
    rows = [
        ("original", kodiio.localized(32087, "Original language")),
        ("default", kodiio.localized(32088, "Default track")),
        ("kodi", kodiio.localized(32089, "Kodi audio language")),
    ]
    if include_leave:
        rows.append(("leave", kodiio.localized(32090, "Leave unchanged")))
    rows.append(("custom", kodiio.localized(32150, "Custom audio language")))
    return rows


def language_rows():
    """Language picker rows. String ids match the settings list."""
    rows = []
    for index, code in enumerate(LANGUAGE_CHOICES):
        rows.append((code, kodiio.localized(32100 + index, LANGUAGES[code]["label"])))
    return rows


def _select_language(dialog, heading, current):
    rows = language_rows()
    labels = [label for _code, label in rows]
    selected = 0
    for index, (code, _label) in enumerate(rows):
        if code == current:
            selected = index
            break
    choice = _select(dialog, heading, labels, selected)
    if choice < 0:
        return None
    return rows[choice][0]


def pick_language(dialog, heading, include_leave):
    """Return (action, custom) or (None, None) when cancelled."""
    rows = _mode_rows(include_leave)
    choice = dialog.select(heading, [label for _action, label in rows])
    if choice < 0:
        return None, None
    action = rows[choice][0]
    if action != "custom":
        return action, ""
    code = _select_language(dialog, kodiio.localized(32150, "Custom audio language"), "")
    if code is None:
        return None, None
    return code, ""


_PRIORITY_SETTINGS = ("lang_1", "lang_2", "lang_3", "lang_4", "lang_5")


def _priority_rows():
    return [
        (code, kodiio.localized(string_id, fallback))
        for code, string_id, fallback in SETTING_ROWS
    ]


def _select(dialog, heading, labels, selected):
    try:
        return dialog.select(heading, labels, 0, selected)
    except TypeError:
        return dialog.select(heading, labels)


def pick_audio_setting(setting_id):
    """Language opens five choices. Custom audio language opens the language list."""
    if setting_id not in _PRIORITY_SETTINGS:
        return
    # The settings window closes first. Wait until it is gone so this list is on screen.
    xbmc.sleep(400)
    try:
        _pick_audio_setting(setting_id)
    finally:
        xbmc.executebuiltin("Addon.OpenSettings({0})".format(kodiio.ADDON_ID))


def _pick_audio_setting(setting_id):
    kodiio.log("Language list for {0}".format(setting_id))
    addon = kodiio.addon()
    try:
        current = addon.getSetting(setting_id) or ""
    except Exception:
        current = ""
    resolved = priority_value(current)
    dialog = xbmcgui.Dialog()
    rows = _priority_rows()
    labels = [label for _action, label in rows]
    selected = {"off": 0, "original": 1, "default": 2, "kodi": 3}.get(resolved, 4 if resolved else 0)
    choice = _select(dialog, kodiio.localized(32027, "Language"), labels, selected)
    if choice < 0:
        return
    action = rows[choice][0]
    if action != "custom":
        addon.setSetting(setting_id, SETTING_ROWS[choice][2])
        return
    code = _select_language(
        dialog,
        kodiio.localized(32150, "Custom audio language"),
        resolved if resolved in LANGUAGES else "",
    )
    if code is None:
        return
    addon.setSetting(setting_id, LANGUAGES[code]["label"])


def _notify(message):
    icon = xbmcgui.NOTIFICATION_INFO
    try:
        path = kodiio.addon().getAddonInfo("icon")
        if path:
            icon = path
    except Exception:
        pass
    xbmcgui.Dialog().notification(kodiio.ADDON_NAME, message, icon, 4000, False)


def _hit_text(hit):
    return hit_label(
        hit,
        kodiio.localized(32099, "TV"),
        kodiio.localized(32151, "Movie"),
        kodiio.localized(32152, "In your library"),
    )


def _store(name, action, custom, identity=None):
    path = kodiio.show_rules_path()
    rules = upsert_rule(load_rules(path), name, action, custom, identity)
    save_rules(rules, path)
    target = dict(identity or {})
    target["name"] = name
    saved = [rule for rule in rules if rule_key(rule) == rule_key(target)]
    label = format_rule(saved[0]) if saved else name
    _notify("{0}: {1}".format(kodiio.localized(32083, "Saved"), label))
    kodiio.log("Saved show rule {0}".format(label))


def _search_titles(query):
    import urllib.request

    from tmdb import search_titles
    from titles import merge_hits

    library = []
    remote = []
    try:
        library = kodiio.search_library(query)
    except Exception:
        kodiio.log("Library title search failed", xbmc.LOGERROR)
    try:
        api_key, _paths = kodiio.tmdb_credentials(kodiio.string_setting("tmdb_apikey", ""))
        if api_key:
            remote = search_titles(query, api_key, urllib.request.urlopen)
    except Exception:
        kodiio.log("TheMovieDB title search failed", xbmc.LOGERROR)
    return [hit for hit in merge_hits(library, remote) if linked(hit)]


def _choose_title(dialog, query):
    query = " ".join((query or "").split())
    if not query:
        return None
    if len(query) < 2:
        _notify(kodiio.localized(32086, "That title is empty."))
        return None
    busy = None
    try:
        busy = xbmcgui.DialogBusy()
        busy.create()
    except Exception:
        busy = None
    try:
        hits = _search_titles(query)
    finally:
        if busy is not None:
            try:
                busy.close()
            except Exception:
                pass
    if not hits:
        _notify(kodiio.localized(32092, "No matching show or movie."))
        return None
    choice = _select(
        dialog,
        kodiio.localized(32091, "Select the show or movie"),
        [_hit_text(hit) for hit in hits],
        0,
    )
    if choice < 0:
        return None
    return hits[choice]


def _add_hit(dialog, hit):
    name = " ".join((hit.get("name") or "").split())
    if not name:
        _notify(kodiio.localized(32086, "That title is empty."))
        return
    action, custom = pick_language(dialog, _hit_text(hit), True)
    if action is None:
        return
    _store(name, action, custom, hit)


def add_playing(dialog):
    playerid = kodiio.video_player_id()
    playing = False
    try:
        playing = xbmc.Player().isPlayingVideo()
    except Exception:
        playing = False
    if playerid is None or not playing:
        _notify(kodiio.localized(32076, "Play a video, or search for the title."))
        return
    info = kodiio.playing_info(playerid)
    hit = hit_from_playback(info)
    if hit.get("name") and linked(hit):
        _add_hit(dialog, hit)
        return
    _choose_and_add(dialog, hit.get("name") or suggested_name(info))


def add_typed(dialog):
    name = dialog.input(kodiio.localized(32077, "Show or movie title"), type=xbmcgui.INPUT_ALPHANUM)
    _choose_and_add(dialog, name)


def _choose_and_add(dialog, name):
    hit = _choose_title(dialog, name)
    if hit is None:
        return
    _add_hit(dialog, hit)


def _edit(dialog, rule):
    path = kodiio.show_rules_path()
    options = [
        kodiio.localized(32079, "Remove"),
        kodiio.localized(32081, "Change language"),
    ]
    choice = dialog.select(rule["name"], options)
    if choice < 0:
        return
    if choice == 0:
        prompt = kodiio.localized(32082, "Remove the rule for this title?")
        if dialog.yesno(kodiio.ADDON_NAME, prompt):
            save_rules(remove_rule(load_rules(path), rule["name"], rule), path)
            _notify("{0}: {1}".format(kodiio.localized(32084, "Removed"), rule["name"]))
            kodiio.log("Removed show rule {0}".format(rule["name"]))
        return
    action, custom = pick_language(dialog, format_rule(rule).split(" — ")[0], True)
    if action is None:
        return
    _store(rule["name"], action, custom, rule)


def manage_show_rules():
    """Modal list of show rules. Select a rule to remove it or change it."""
    dialog = xbmcgui.Dialog()
    while True:
        rules = load_rules(kodiio.show_rules_path())
        items = [
            kodiio.localized(32070, "Add the title that is playing"),
            kodiio.localized(32071, "Add a title"),
        ]
        offset = len(items)
        items.extend(format_rule(rule) for rule in rules)
        remove_all = None
        if rules:
            remove_all = len(items)
            items.append(kodiio.localized(32072, "Remove all"))
        choice = dialog.select(kodiio.localized(32073, "Show rules"), items)
        if choice < 0:
            return
        if choice == 0:
            add_playing(dialog)
        elif choice == 1:
            add_typed(dialog)
        elif remove_all is not None and choice == remove_all:
            if dialog.yesno(kodiio.ADDON_NAME, kodiio.localized(32074, "Remove every show rule?")):
                save_rules([], kodiio.show_rules_path())
                _notify(kodiio.localized(32084, "Removed"))
                kodiio.log("Removed every show rule")
        else:
            _edit(dialog, rules[choice - offset])


def set_rule_for_context():
    """Save a language for the show or movie focused in the library."""
    dialog = xbmcgui.Dialog()
    hit = kodiio.context_title()
    if hit.get("name") and linked(hit):
        _add_hit(dialog, hit)
        return
    name = hit.get("name") or title_for_context(
        xbmc.getInfoLabel("ListItem.DBType"),
        xbmc.getInfoLabel("ListItem.TvShowTitle"),
        xbmc.getInfoLabel("ListItem.Title"),
        xbmc.getInfoLabel("ListItem.Label"),
    )
    _choose_and_add(dialog, name)
