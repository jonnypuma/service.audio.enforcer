# -*- coding: utf-8 -*-
"""File-path checks for trailers, extras, and show-folder names."""

import re
import unicodedata

_EXTRA_DIRS = {
    "extra",
    "extras",
    "featurette",
    "featurettes",
    "interview",
    "interviews",
    "sample",
    "samples",
    "short",
    "shorts",
    "bonus",
    "behind the scenes",
    "behindthescenes",
    "deleted scenes",
    "deletedscenes",
}

_GENERIC_FOLDERS = {
    "extra",
    "extras",
    "trailer",
    "trailers",
    "sample",
    "samples",
    "featurette",
    "featurettes",
    "interview",
    "interviews",
    "bonus",
    "shorts",
    "short",
    "behind the scenes",
    "deleted scenes",
    "deleted scene",
}


def path_segments(path):
    return [part.strip() for part in (path or "").replace("\\", "/").split("/") if part.strip()]


def path_stem(path):
    name = path_segments(path)[-1] if path_segments(path) else ""
    if "." in name:
        name = name.rsplit(".", 1)[0]
    return name


def path_words(text):
    normalized = unicodedata.normalize("NFKC", text or "").casefold()
    return [part for part in re.split(r"[^\w]+|_", normalized) if part]


def loose_title(text):
    return " ".join(path_words(text))


def is_trailer_path(path):
    segments = path_segments(path)
    if any(segment.lower() in ("trailer", "trailers") for segment in segments[:-1]):
        return True
    words = path_words(path_stem(path))
    return bool(words) and words[-1] in ("trailer", "trailers")


def is_extra_path(path):
    segments = path_segments(path)
    if any(segment.lower() in _EXTRA_DIRS for segment in segments[:-1]):
        return True
    stem = path_stem(path).lower().replace("_", " ").replace(".", " ").replace("-", " ")
    if any(phrase in stem for phrase in ("behind the scenes", "deleted scene", "deleted scenes")):
        return True
    words = path_words(path_stem(path))
    return bool(words) and words[-1] in ("sample", "featurette", "interview", "extra")


def title_match(rule, candidate):
    """True when candidate is the rule title, or that title plus a year."""
    rule_name = loose_title(rule)
    candidate_name = loose_title(candidate)
    if not rule_name or not candidate_name:
        return False
    if candidate_name == rule_name:
        return True
    if candidate_name.startswith(rule_name + " "):
        rest = candidate_name[len(rule_name):].strip()
        if re.fullmatch(r"(19|20)\d{2}", rest):
            return True
    return False


def year_from_parents(path):
    """Year written on a parent folder, such as Show (2017)."""
    for segment in reversed(path_segments(path)[:-1]):
        match = re.search(r"\((19|20)\d{2}\)\s*$", segment.strip())
        if match:
            return match.group(0)[1:5]
    return ""


def is_generic_folder(name):
    loose = loose_title(name)
    if not loose or loose in _GENERIC_FOLDERS:
        return True
    if re.fullmatch(r"season \d+", loose):
        return True
    compact = loose.replace(" ", "")
    if re.fullmatch(r"s\d{1,2}", compact):
        return True
    return False


def suggested_name(info):
    """Title to store for a per-show rule, from a playing item."""
    info = info or {}
    mediatype = (info.get("mediatype") or "").lower()
    showtitle = (info.get("showtitle") or "").strip()
    title = (info.get("title") or "").strip()
    if mediatype in ("episode", "season", "tvshow"):
        if showtitle:
            return showtitle
    elif title:
        return title
    if showtitle:
        return showtitle
    for segment in reversed(path_segments(info.get("path"))[:-1]):
        if not is_generic_folder(segment):
            return segment.strip()
    return ""


def candidate_titles(info):
    """Names that may match a show rule for this item.

    Episode titles are not included, so a rule cannot catch every episode
    that happens to share a word with the episode name.
    """
    info = info or {}
    mediatype = (info.get("mediatype") or "").lower()
    titles = []
    showtitle = (info.get("showtitle") or "").strip()
    title = (info.get("title") or "").strip()
    if mediatype in ("episode", "season", "tvshow"):
        if showtitle:
            titles.append(showtitle)
        elif title and mediatype == "tvshow":
            titles.append(title)
    else:
        if title:
            titles.append(title)
        if showtitle and showtitle not in titles:
            titles.append(showtitle)
    for segment in path_segments(info.get("path"))[:-1]:
        titles.append(segment)
    return titles
