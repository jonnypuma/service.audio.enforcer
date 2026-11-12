# -*- coding: utf-8 -*-
"""A show or movie that a rule can be linked to."""


def _text(value):
    return " ".join(str(value or "").split())


def _year(value):
    text = str(value or "").strip()
    if len(text) >= 4 and text[:4].isdigit():
        year = int(text[:4])
        if 1900 <= year <= 2100:
            return str(year)
    return ""


def _digits(value):
    text = str(value or "").strip()
    if text.isdigit() and int(text) > 0:
        return str(int(text))
    return ""


def _imdb(value):
    text = str(value or "").strip()
    if len(text) > 2 and text[:2].lower() == "tt" and text[2:].isdigit():
        return "tt" + text[2:]
    return ""


def _kind(value):
    kind = str(value or "").strip().lower()
    if kind in ("episode", "season", "tv", "show", "tvshow"):
        return "tvshow"
    if kind == "movie":
        return "movie"
    return ""


def make_hit(name, year="", mediatype="", tmdb="", imdb="", library_id=""):
    """One selectable show or movie. Empty fields stay empty strings."""
    return {
        "name": _text(name),
        "year": _year(year),
        "mediatype": _kind(mediatype),
        "tmdb": _digits(tmdb),
        "imdb": _imdb(imdb),
        "library_id": _digits(library_id),
    }


def linked(hit):
    """True when the title is tied to a library id or a TheMovieDB / IMDb id."""
    hit = hit or {}
    return bool(hit.get("tmdb") or hit.get("imdb") or hit.get("library_id"))


def hit_label(hit, tv="TV", movie="Movie", library=""):
    """Dialog text for one search result."""
    hit = hit or {}
    name = hit.get("name") or ""
    year = hit.get("year") or ""
    if year and year not in name:
        name = "{0} ({1})".format(name, year)
    kind = {"tvshow": tv, "movie": movie}.get(hit.get("mediatype") or "")
    parts = [name]
    if kind:
        parts.append(kind)
    if library and hit.get("library_id"):
        parts.append(library)
    return " — ".join(part for part in parts if part)


def hit_from_playback(info):
    """The show or movie described by a playing item."""
    info = info or {}
    kind = _kind(info.get("mediatype"))
    if kind == "tvshow":
        name = info.get("showtitle") or info.get("title") or ""
    else:
        name = info.get("title") or info.get("showtitle") or ""
    return make_hit(
        name,
        info.get("year"),
        kind,
        info.get("tmdb"),
        info.get("imdb"),
        info.get("library_id"),
    )


def hit_from_library_details(details, mediatype):
    """A Kodi GetTVShowDetails or GetMovieDetails record."""
    details = details if isinstance(details, dict) else {}
    unique = details.get("uniqueid") if isinstance(details.get("uniqueid"), dict) else {}
    id_key = "tvshowid" if _kind(mediatype) == "tvshow" else "movieid"
    return make_hit(
        details.get("title") or details.get("label") or "",
        details.get("year") or details.get("premiered"),
        mediatype,
        unique.get("tmdb"),
        unique.get("imdb") or details.get("imdbnumber"),
        details.get(id_key),
    )


def hits_from_library(shows, movies):
    """Search rows from VideoLibrary.GetTVShows and GetMovies."""
    found = []
    for row in shows or []:
        if not isinstance(row, dict):
            continue
        hit = hit_from_library_details(row, "tvshow")
        if hit["name"] and hit["library_id"]:
            found.append(hit)
    for row in movies or []:
        if not isinstance(row, dict):
            continue
        hit = hit_from_library_details(row, "movie")
        if hit["name"] and hit["library_id"]:
            found.append(hit)
    return found


def _keys(hit):
    keys = []
    if hit.get("tmdb") and hit.get("mediatype"):
        keys.append(("tmdb", hit["mediatype"], hit["tmdb"]))
    if hit.get("imdb"):
        keys.append(("imdb", hit["imdb"].lower()))
    if hit.get("library_id") and hit.get("mediatype"):
        keys.append(("library", hit["mediatype"], hit["library_id"]))
    if hit.get("name"):
        keys.append(("name", hit.get("mediatype") or "", hit["name"].lower(), hit.get("year") or ""))
    return keys


def merge_hits(primary, extra, limit=40):
    """Library rows win the displayed name. TheMovieDB fills in a missing id."""
    merged = []
    index = {}

    def add(raw):
        if not isinstance(raw, dict):
            return
        hit = make_hit(
            raw.get("name"),
            raw.get("year"),
            raw.get("mediatype"),
            raw.get("tmdb"),
            raw.get("imdb"),
            raw.get("library_id"),
        )
        if not hit["name"]:
            return
        existing = None
        for key in _keys(hit):
            if key in index:
                existing = index[key]
                break
        if existing is None:
            merged.append(hit)
            existing = hit
        else:
            for field in ("year", "mediatype", "tmdb", "imdb", "library_id"):
                if not existing.get(field) and hit.get(field):
                    existing[field] = hit[field]
        for key in _keys(existing):
            index[key] = existing

    for row in primary or []:
        add(row)
    for row in extra or []:
        add(row)
    return merged[:limit]
