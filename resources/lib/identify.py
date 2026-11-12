# -*- coding: utf-8 -*-
"""Turn Kodi player and library fields into one plain item description."""

from paths import year_from_parents

_EMPTY = {"", "none", "null", "unknown", "-1", "0"}


def _text(value):
    if value is None:
        return ""
    return str(value).strip()


def _token(value):
    text = _text(value)
    if text.lower() in _EMPTY:
        return ""
    return text


def _imdb(value):
    text = _token(value)
    if text.lower().startswith("tt") and text[2:].isdigit():
        return text
    return ""


def _tmdb(value):
    text = _token(value)
    if text.isdigit() and int(text) > 0:
        return str(int(text))
    return ""


def _library_id(value):
    return _tmdb(value)


def _year(value):
    text = _token(value)
    if len(text) >= 4 and text[:4].isdigit():
        year = int(text[:4])
        if 1900 <= year <= 2100:
            return str(year)
    return ""


def _unique(value):
    if not isinstance(value, dict):
        return {}
    return value


def normalize_info(item, labels=None, show=None):
    """Merge player item fields, info labels, and the parent show.

    `labels` uses short keys: showtitle, title, file, dbtype, year, premiered,
    tmdb, imdb, imdbnumber, original_language, and helper_language
    (one value or a list). helper_language is TheMovieDB Helper's own value.
    """
    item = item if isinstance(item, dict) else {}
    labels = labels if isinstance(labels, dict) else {}
    show = show if isinstance(show, dict) else {}
    unique = _unique(item.get("uniqueid"))
    show_unique = _unique(show.get("uniqueid"))

    mediatype = (_text(item.get("type")) or _text(labels.get("dbtype"))).lower()
    if mediatype in ("unknown", "video"):
        mediatype = ""
    showtitle = _text(item.get("showtitle")) or _text(labels.get("showtitle")) or _text(show.get("title"))
    title = _text(item.get("title")) or _text(labels.get("title"))
    if showtitle and not mediatype:
        mediatype = "episode"
    if show and not mediatype:
        mediatype = "episode"
    if not mediatype and title and not showtitle:
        mediatype = "movie"

    show_known = bool(
        _text(show.get("title"))
        or show_unique
        or _imdb(show.get("imdbnumber"))
        or _year(show.get("year"))
        or _year(show.get("premiered"))
    )
    if mediatype in ("episode", "season", "tvshow") and show_known:
        tmdb = _tmdb(show_unique.get("tmdb")) or _tmdb(labels.get("tmdb"))
        imdb = (
            _imdb(show_unique.get("imdb"))
            or _imdb(show.get("imdbnumber"))
            or _imdb(labels.get("imdb"))
            or _imdb(labels.get("imdbnumber"))
        )
    else:
        tmdb = (
            _tmdb(unique.get("tmdb"))
            or _tmdb(labels.get("tmdb"))
            or _tmdb(show_unique.get("tmdb"))
        )
        imdb = (
            _imdb(unique.get("imdb"))
            or _imdb(labels.get("imdb"))
            or _imdb(item.get("imdbnumber"))
            or _imdb(labels.get("imdbnumber"))
            or _imdb(show_unique.get("imdb"))
            or _imdb(show.get("imdbnumber"))
        )
    if mediatype in ("episode", "season", "tvshow"):
        library_id = _library_id(item.get("tvshowid")) or _library_id(show.get("tvshowid"))
        if mediatype == "tvshow":
            library_id = library_id or _library_id(item.get("id"))
    elif mediatype == "movie":
        library_id = _library_id(item.get("id"))
    else:
        library_id = ""
    path = _text(item.get("file")) or _text(labels.get("file"))
    if mediatype in ("episode", "season", "tvshow") and show:
        year = _year(show.get("year")) or _year(show.get("premiered"))
    else:
        year = ""
    if not year:
        year = (
            _year(item.get("year"))
            or _year(labels.get("year"))
            or _year(item.get("premiered"))
            or _year(labels.get("premiered"))
            or year_from_parents(path)
        )

    def _hint_list(value):
        if isinstance(value, (list, tuple)):
            return [str(item).strip() for item in value if str(item).strip()]
        if value:
            text = str(value).strip()
            return [text] if text else []
        return []

    return {
        "mediatype": mediatype,
        "title": title,
        "showtitle": showtitle,
        "year": year,
        "tmdb": tmdb,
        "imdb": imdb,
        "library_id": library_id,
        "path": path,
        "original_hints": _hint_list(labels.get("original_language")),
        "helper_hints": _hint_list(labels.get("helper_language")),
    }


def merge_info(current, update):
    """Fill blank fields from a later read without wiping what we already have."""
    current = dict(current or {})
    update = update or {}
    for key in ("mediatype", "title", "showtitle", "year", "tmdb", "imdb", "library_id", "path"):
        if update.get(key) and not current.get(key):
            current[key] = update[key]
    for key in ("original_hints", "helper_hints"):
        hints = list(current.get(key) or [])
        for hint in update.get(key) or []:
            if hint not in hints:
                hints.append(hint)
        current[key] = hints
    return current
