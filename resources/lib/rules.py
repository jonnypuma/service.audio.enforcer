# -*- coding: utf-8 -*-
"""Per-show audio rules, stored as a JSON list."""

import json
import os
import re

from languages import LANGUAGES, spec_from_text
from paths import candidate_titles, loose_title, title_match
from titles import make_hit

_FIXED = {
    "original": "original",
    "original language": "original",
    "default": "default",
    "default track": "default",
    "mediadefault": "default",
    "kodi": "kodi",
    "kodi audio language": "kodi",
    "leave": "leave",
    "skip": "leave",
    "off": "leave",
    "none": "leave",
    "unchanged": "leave",
    "ignore": "leave",
    "custom": "custom",
}

_LABELS = {
    "original": "Original language",
    "default": "Default track",
    "kodi": "Kodi audio language",
    "leave": "Leave unchanged",
}


def canonicalize_action(action, custom=""):
    """Return (action, custom) or None when the text is not a rule."""
    action = " ".join((action or "").strip().lower().split())
    custom = (custom or "").strip()
    if action in _FIXED:
        action = _FIXED[action]
    if action == "custom":
        if not custom:
            return None
        return "custom", custom
    if action in ("original", "default", "kodi", "leave"):
        return action, ""
    if action in LANGUAGES:
        return action, ""
    spec = spec_from_text(action)
    if spec is None:
        return None
    for code in LANGUAGES:
        known = LANGUAGES[code]
        raw = action
        if raw == code or raw in known["codes"] or raw in known["names"] or raw == known["label"].lower():
            return code, ""
    return "custom", (custom or action)


def action_label(rule):
    action = rule.get("action")
    if action in _LABELS:
        return _LABELS[action]
    if action == "custom":
        return rule.get("custom") or "Custom"
    known = LANGUAGES.get(action)
    if known:
        return known["label"]
    return action or ""


def format_rule(rule):
    name = rule.get("name") or ""
    year = str(rule.get("year") or "")
    if year and year not in name:
        name = "{0} ({1})".format(name, year)
    kind = {"tvshow": "TV", "movie": "Movie"}.get(rule.get("mediatype") or "")
    if kind:
        name = "{0} · {1}".format(name, kind)
    return "{0} — {1}".format(name, action_label(rule))


def _identity(item):
    hit = make_hit(
        "title",
        (item or {}).get("year"),
        (item or {}).get("mediatype"),
        (item or {}).get("tmdb"),
        (item or {}).get("imdb"),
        (item or {}).get("library_id"),
    )
    return {key: hit[key] for key in ("year", "mediatype", "tmdb", "imdb", "library_id")}


def specific_rule(rule):
    """A rule that names one show or movie, not every title with the same words."""
    rule = rule or {}
    return bool(rule.get("tmdb") or rule.get("imdb") or rule.get("library_id") or rule.get("year"))


def rule_key(rule):
    """Identity used to replace or remove one saved rule."""
    rule = rule or {}
    name = " ".join(str(rule.get("name") or "").split()).lower()
    mediatype = rule.get("mediatype") or ""
    if rule.get("tmdb") and mediatype:
        return "tmdb:{0}:{1}".format(mediatype, rule.get("tmdb"))
    imdb = str(rule.get("imdb") or "").lower()
    if imdb:
        return "imdb:{0}".format(imdb)
    if rule.get("library_id") and mediatype:
        return "library:{0}:{1}".format(mediatype, rule.get("library_id"))
    if rule.get("year"):
        return "title:{0}:{1}:{2}".format(mediatype, name, rule.get("year"))
    return "name:{0}".format(name)


def normalize_rules(data):
    if not isinstance(data, list):
        return []
    rules = []
    seen = set()
    for item in data:
        if not isinstance(item, dict):
            continue
        name = " ".join(str(item.get("name") or "").split())
        if not name:
            continue
        parsed = canonicalize_action(item.get("action"), item.get("custom"))
        if parsed is None:
            continue
        rule = {"name": name, "action": parsed[0], "custom": parsed[1]}
        for field, value in _identity(item).items():
            if value:
                rule[field] = value
        key = rule_key(rule)
        if key in seen:
            continue
        seen.add(key)
        rules.append(rule)
    rules.sort(key=lambda rule: rule["name"].lower())
    return rules


def load_rules(path):
    if not path or not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return []
    return normalize_rules(data)


def save_rules(rules, path):
    rules = normalize_rules(rules)
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(rules, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temporary, path)
    return rules


def upsert_rule(rules, name, action, custom="", identity=None):
    parsed = canonicalize_action(action, custom)
    name = " ".join((name or "").split())
    if not name or parsed is None:
        return normalize_rules(rules)
    existing = normalize_rules(rules)
    target = {"name": name}
    target.update({key: value for key, value in _identity(identity).items() if value})
    if not specific_rule(target):
        same_name = [rule for rule in existing if rule["name"].lower() == name.lower()]
        if len(same_name) == 1:
            for field in ("year", "mediatype", "tmdb", "imdb", "library_id"):
                if same_name[0].get(field):
                    target[field] = same_name[0][field]
            name = same_name[0]["name"]
    target["name"] = name
    key = rule_key(target)
    kept = []
    for rule in existing:
        if rule_key(rule) == key:
            if loose_title(rule.get("name")) == loose_title(name):
                name = rule.get("name") or name
            continue
        kept.append(rule)
    entry = {"name": name, "action": parsed[0], "custom": parsed[1]}
    for field in ("year", "mediatype", "tmdb", "imdb", "library_id"):
        if target.get(field):
            entry[field] = target[field]
    kept.append(entry)
    return normalize_rules(kept)


def remove_rule(rules, name, identity=None):
    name = " ".join((name or "").split())
    target = {"name": name}
    target.update({key: value for key, value in _identity(identity).items() if value})
    if not specific_rule(target):
        key = "name:{0}".format(name.lower())
    else:
        key = rule_key(target)
    return [rule for rule in normalize_rules(rules) if rule_key(rule) != key]


def _kind_ok(rule, info, allow_unknown):
    rule_type = rule.get("mediatype") or ""
    info_type = (info.get("mediatype") or "").lower()
    if rule_type not in ("tvshow", "movie"):
        return True
    if info_type not in ("episode", "season", "tvshow", "movie"):
        return allow_unknown
    rule_tv = rule_type == "tvshow"
    info_tv = info_type in ("episode", "season", "tvshow")
    return rule_tv == info_tv


def _ids_match(rule, info):
    if not _kind_ok(rule, info, False):
        return False
    if rule.get("library_id") and str(info.get("library_id") or "") == str(rule.get("library_id")):
        return True
    if rule.get("tmdb") and str(info.get("tmdb") or "") == str(rule.get("tmdb")):
        return True
    imdb = str(rule.get("imdb") or "").lower()
    if imdb and imdb == str(info.get("imdb") or "").lower():
        return True
    return False


def _id_conflict(rule, info):
    if rule.get("tmdb") and info.get("tmdb") and str(rule.get("tmdb")) != str(info.get("tmdb")):
        return True
    if rule.get("imdb") and info.get("imdb") and str(rule.get("imdb")).lower() != str(info.get("imdb")).lower():
        return True
    if (
        rule.get("library_id")
        and info.get("library_id")
        and str(rule.get("library_id")) != str(info.get("library_id"))
        and _kind_ok(rule, info, False)
    ):
        return True
    return False


def _years_in_titles(rule_name, titles):
    wanted = loose_title(rule_name)
    years = []
    for title in titles:
        candidate = loose_title(title)
        if not wanted or not candidate.startswith(wanted + " "):
            continue
        rest = candidate[len(wanted):].strip()
        if re.fullmatch(r"(19|20)\d{2}", rest):
            years.append(rest)
    return years


def _title_matches_specific(rule, info):
    if _id_conflict(rule, info) or not _kind_ok(rule, info, True):
        return False
    titles = candidate_titles(info)
    if not any(title_match(rule.get("name"), title) for title in titles):
        return False
    year = str(rule.get("year") or "")
    if not year:
        return True
    info_year = str(info.get("year") or "")
    if info_year:
        return info_year == year
    return year in _years_in_titles(rule.get("name"), titles)


def match_rule(info, rules):
    """The linked show wins. A typed name with no link still matches that name."""
    rules = [rule for rule in rules or [] if isinstance(rule, dict)]
    specific = [rule for rule in rules if specific_rule(rule)]
    plain = [rule for rule in rules if not specific_rule(rule)]
    for rule in specific:
        if _ids_match(rule, info):
            return rule
    titled = [rule for rule in specific if _title_matches_specific(rule, info)]
    if len(titled) == 1:
        return titled[0]
    if len(titled) > 1:
        return None
    for rule in plain:
        for title in candidate_titles(info):
            if title_match(rule.get("name"), title):
                return rule
    return None


def mode_priorities(mode, language, custom):
    """Return 'leave', 'main', or a one-entry priority list."""
    mode = (mode or "leave").strip().lower()
    if mode == "leave":
        return "leave"
    if mode == "main":
        return "main"
    if mode == "language":
        return [{"slot": 0, "code": (language or "off").strip().lower(), "custom": custom or ""}]
    if mode in ("original", "default", "kodi"):
        return [{"slot": 0, "code": mode, "custom": ""}]
    return "leave"


def rule_priorities(rule):
    if rule is None:
        return None
    action = rule.get("action")
    if action == "leave":
        return "leave"
    if action == "custom":
        return [{"slot": 0, "code": "custom", "custom": rule.get("custom") or ""}]
    return [{"slot": 0, "code": action, "custom": ""}]


def playback_plan(info, prefs, rules):
    """Return ('skip', reason) or ('use', unresolved priorities, reason)."""
    from paths import is_extra_path, is_trailer_path

    prefs = prefs or {}
    path = (info or {}).get("path") or ""
    if is_trailer_path(path):
        mode = mode_priorities(prefs.get("trailer_mode"), prefs.get("trailer_language"), prefs.get("trailer_custom"))
        if mode == "leave":
            return ("skip", "trailer")
        if mode != "main":
            return ("use", mode, "trailer")
    elif is_extra_path(path):
        mode = mode_priorities(prefs.get("extra_mode"), prefs.get("extra_language"), prefs.get("extra_custom"))
        if mode == "leave":
            return ("skip", "extra")
        if mode != "main":
            return ("use", mode, "extra")
    rule = match_rule(info, rules)
    if rule is not None:
        planned = rule_priorities(rule)
        if planned == "leave":
            return ("skip", "show")
        return ("use", planned, "show")
    return ("use", list(prefs.get("priorities") or []), "main")


def title_for_context(dbtype, show, title, label):
    """Name a library item the way a show rule should store it."""
    dbtype = (dbtype or "").lower()
    show = (show or "").strip()
    title = (title or "").strip()
    label = (label or "").strip()
    if dbtype in ("episode", "season", "tvshow"):
        return show or title or label
    if dbtype == "movie":
        return title or label
    if show:
        return show
    return title or label
