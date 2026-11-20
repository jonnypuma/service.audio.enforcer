# -*- coding: utf-8 -*-
"""Find an original language in file metadata, TheMovieDB Helper, or TheMovieDB."""

import json
import os
import re
import sqlite3
import tempfile
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

_CACHE_LOCK = threading.Lock()

API = "https://api.themoviedb.org/3"
USER_AGENT = "AudioEnforcer/1.0"
HIT_TTL = 30 * 24 * 3600
MISS_TTL = 3 * 24 * 3600
HELPER_ID = "plugin.video.themoviedb.helper"

_REJECT = {
    "und",
    "unknown",
    "unk",
    "xx",
    "nul",
    "none",
    "mis",
    "zxx",
    "undetermined",
    "default",
    "original",
    "mediadefault",
    "true",
    "false",
    "n/a",
    "na",
}


def usable_language(value):
    raw = (value or "").strip()
    if not raw or len(raw) > 40:
        return False
    key = raw.lower().replace("_", "-")
    if key in _REJECT:
        return False
    return re.search(r"[a-z]", key) is not None


def _flag(value):
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def original_from_streams(streams):
    """Language of a stream the file marks as the original language."""
    found = []
    for stream in streams or []:
        if not isinstance(stream, dict) or not _flag(stream.get("isoriginal")):
            continue
        language = (stream.get("language") or "").strip()
        if usable_language(language):
            found.append(stream)
    if not found:
        return ""
    found.sort(key=lambda stream: (
        0 if _flag(stream.get("isdefault")) else 1,
        int(stream.get("index") or 0),
    ))
    return (found[0].get("language") or "").strip()


def original_from_properties(values):
    for value in values or []:
        if usable_language(value):
            return str(value).strip()
    return ""


def _tv(info):
    return (info or {}).get("mediatype") in ("episode", "season", "tvshow")


def lookup_title(info):
    info = info or {}
    if _tv(info):
        return (info.get("showtitle") or info.get("title") or "").strip()
    return (info.get("title") or info.get("showtitle") or "").strip()


def _loose(text):
    normalized = unicodedata.normalize("NFKC", text or "").casefold()
    return " ".join(part for part in re.split(r"[^\w]+|_", normalized) if part)


def _digits(value):
    text = str(value or "").strip()
    if text.isdigit():
        return str(int(text))
    return ""


def _item_year(item):
    text = str(item.get("release_date") or item.get("first_air_date") or "")
    return text[:4] if len(text) >= 4 and text[:4].isdigit() else ""


def _year_close(left, right):
    if not left or not right:
        return False
    try:
        return abs(int(left) - int(right)) <= 1
    except ValueError:
        return False


def names_of(item):
    return [
        item.get("title"),
        item.get("name"),
        item.get("original_title"),
        item.get("original_name"),
    ]


def pick_result(results, title, year):
    """Original language of the search hit with this exact title."""
    want = _loose(title)
    if not want:
        return ""
    exact = []
    for item in results or []:
        if not isinstance(item, dict):
            continue
        if any(_loose(name) == want for name in names_of(item) if name):
            exact.append(item)
    if not exact:
        return ""
    if year:
        dated = [item for item in exact if _item_year(item) == str(year)]
        close = [item for item in exact if _year_close(_item_year(item), year)]
        if dated:
            exact = dated
        elif close:
            exact = close
        else:
            return ""
    exact.sort(key=lambda item: -(item.get("popularity") or 0))
    language = exact[0].get("original_language") or ""
    return language if usable_language(language) else ""


def cache_keys(info):
    info = info or {}
    kind = "tv" if _tv(info) else "movie"
    keys = []
    tmdb = _digits(info.get("tmdb"))
    imdb = str(info.get("imdb") or "").strip().lower()
    title = _loose(lookup_title(info))
    year = str(info.get("year") or "")
    if tmdb:
        keys.append("{0}:tmdb:{1}".format(kind, tmdb))
    if imdb.startswith("tt"):
        keys.append("{0}:imdb:{1}".format(kind, imdb))
    if title:
        keys.append("{0}:title:{1}:{2}".format(kind, title, year))
    return keys


class LanguageCache(object):
    def __init__(self, path, now=None):
        self.path = path
        self.now = now or time.time
        self.data = {}
        self._load()

    def _load(self):
        if not self.path or not os.path.isfile(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return
        if isinstance(data, dict):
            self.data = data

    def get(self, keys):
        now = self.now()
        for key in keys or []:
            row = self.data.get(key)
            if not isinstance(row, dict):
                continue
            try:
                age = now - float(row.get("at") or 0)
            except (TypeError, ValueError):
                continue
            language = row.get("language") or ""
            if age <= (HIT_TTL if language else MISS_TTL):
                return language, row.get("source") or "cache", True
        return "", "", False

    def _prune(self, now):
        expired = []
        for key, row in self.data.items():
            if not isinstance(row, dict):
                expired.append(key)
                continue
            try:
                age = now - float(row.get("at") or 0)
            except (TypeError, ValueError):
                expired.append(key)
                continue
            language = row.get("language") or ""
            if age > (HIT_TTL if language else MISS_TTL):
                expired.append(key)
        for key in expired:
            self.data.pop(key, None)

    def put(self, keys, language, source):
        if not self.path or not keys:
            return
        with _CACHE_LOCK:
            self._load()
            stamp = self.now()
            self._prune(stamp)
            for key in keys:
                self.data[key] = {
                    "language": language or "",
                    "source": source or "",
                    "at": stamp,
                }
            directory = os.path.dirname(self.path) or "."
            if directory and not os.path.isdir(directory):
                os.makedirs(directory)
            fd, temporary = tempfile.mkstemp(prefix=".cache_", suffix=".tmp", dir=directory)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(self.data, handle, ensure_ascii=False, indent=2)
                    handle.write("\n")
                os.replace(temporary, self.path)
            except Exception:
                try:
                    os.remove(temporary)
                except OSError:
                    pass
                raise


def clear_language_cache(path):
    """Remove the saved original-language cache file if it exists."""
    if not path:
        return False
    with _CACHE_LOCK:
        if not os.path.isfile(path):
            return False
        try:
            os.remove(path)
            return True
        except OSError:
            return False


def _safe_name(name):
    return re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name or "") is not None


def _connect_ro(path):
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=1)
    connection.execute("PRAGMA query_only = ON")
    return connection


def _item_ids(info):
    tmdb = _digits((info or {}).get("tmdb"))
    if not tmdb:
        return []
    if _tv(info):
        return ["tv.{0}".format(tmdb), "tvshow.{0}".format(tmdb)]
    return ["movie.{0}".format(tmdb)]


def _json_language(text):
    try:
        data = json.loads(text or "")
    except (TypeError, ValueError):
        return ""
    return _walk_language(data, 0)


def _walk_language(value, depth):
    if depth > 6:
        return ""
    if isinstance(value, dict):
        language = value.get("original_language")
        if usable_language(language):
            return str(language).strip()
        for child in value.values():
            found = _walk_language(child, depth + 1)
            if found:
                return found
    elif isinstance(value, list):
        for child in value[:40]:
            found = _walk_language(child, depth + 1)
            if found:
                return found
    return ""


def lookup_helper_db(path, info):
    """Read original_language from a TheMovieDB Helper database, if it has one."""
    if not path or not os.path.isfile(path):
        return ""
    try:
        connection = _connect_ro(path)
    except (sqlite3.Error, OSError):
        return ""
    try:
        language = _from_columns(connection, info)
        if language:
            return language
        return _from_cached_rows(connection, info)
    except sqlite3.Error:
        return ""
    finally:
        connection.close()


def _from_columns(connection, info):
    tmdb = _digits((info or {}).get("tmdb"))
    imdb = str((info or {}).get("imdb") or "").strip()
    try:
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )]
    except sqlite3.Error:
        return ""
    for name in tables:
        if not _safe_name(name):
            continue
        try:
            columns = [row[1] for row in connection.execute('PRAGMA table_info("{0}")'.format(name))]
        except sqlite3.Error:
            continue
        lower = {column.lower(): column for column in columns if _safe_name(column)}
        if "original_language" not in lower:
            continue
        clauses = []
        args = []
        if tmdb and "tmdb_id" in lower:
            clauses.append('"{0}" = ?'.format(lower["tmdb_id"]))
            args.append(int(tmdb))
        if imdb and "imdb_id" in lower:
            clauses.append('"{0}" = ?'.format(lower["imdb_id"]))
            args.append(imdb)
        if tmdb and "id" in lower:
            for item_id in _item_ids(info):
                clauses.append('"{0}" = ?'.format(lower["id"]))
                args.append(item_id)
        if not clauses:
            continue
        query = 'SELECT "{0}" FROM "{1}" WHERE {2} LIMIT 8'.format(
            lower["original_language"], name, " OR ".join(clauses)
        )
        try:
            for row in connection.execute(query, args):
                if usable_language(row[0]):
                    return str(row[0]).strip()
        except sqlite3.Error:
            continue
    return ""


def _parent_ids(connection, info):
    ids = list(_item_ids(info))
    imdb = str((info or {}).get("imdb") or "").strip()
    if not imdb:
        return ids
    try:
        rows = connection.execute(
            "SELECT parent_id FROM unique_id WHERE key = ? AND value = ? LIMIT 5",
            ("imdb", imdb),
        )
    except sqlite3.Error:
        return ids
    for row in rows:
        if row[0] and row[0] not in ids:
            ids.append(row[0])
    return ids


def _from_cached_rows(connection, info):
    try:
        ids = _parent_ids(connection, info)
    except sqlite3.Error:
        return ""
    for item_id in ids:
        try:
            rows = connection.execute(
                "SELECT value FROM custom WHERE parent_id = ? AND lower(key) IN "
                "('original_language', 'originallanguage') LIMIT 3",
                (item_id,),
            )
        except sqlite3.Error:
            rows = []
        for row in rows:
            if usable_language(row[0]):
                return str(row[0]).strip()
        try:
            stored = connection.execute(
                "SELECT data FROM stored_metadata WHERE item_id = ? OR family_id = ? LIMIT 3",
                (item_id, item_id),
            )
        except sqlite3.Error:
            continue
        for row in stored:
            language = _json_language(row[0])
            if language:
                return language
    return ""


def search_titles(query, api_key, opener, timeout=6):
    """Shows and movies matching a typed name. Each row has name, year, mediatype, and tmdb."""
    query = " ".join(str(query or "").split())
    api_key = (api_key or "").strip()
    if len(query) < 2 or not api_key or opener is None:
        return []
    found = []
    searches = (
        ("tvshow", "/search/tv", ("name", "original_name")),
        ("movie", "/search/movie", ("title", "original_title")),
    )
    for mediatype, path, name_keys in searches:
        try:
            data = _request_json(opener, path, api_key, timeout, {"query": query})
        except Exception:
            continue
        results = (data or {}).get("results") if isinstance(data, dict) else []
        for item in results or []:
            if not isinstance(item, dict):
                continue
            name = ""
            for key in name_keys:
                name = str(item.get(key) or "").strip()
                if name:
                    break
            tmdb = _digits(item.get("id"))
            if not name or not tmdb:
                continue
            found.append({
                "name": name,
                "year": _item_year(item),
                "mediatype": mediatype,
                "tmdb": tmdb,
                "imdb": "",
                "library_id": "",
            })
            if len(found) >= 30:
                return found
    return found


def helper_api_key_from_source(addon_path):
    """Read TheMovieDB Helper's own API key from an installed copy.

    The key stays in that add-on. Nothing here copies it into Audio Enforcer.
    """
    if not addon_path:
        return ""
    path = os.path.join(
        addon_path, "resources", "tmdbhelper", "lib", "api", "api_keys", "tmdb.py"
    )
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return ""
    match = re.search(r"^[ \t]*API_KEY\s*=\s*['\"]([0-9a-fA-F]{16,})['\"]", text, re.M)
    return match.group(1) if match else ""


def _request_json(opener, path, api_key, timeout, params=None):
    query = {"api_key": api_key}
    if params:
        query.update({key: value for key, value in params.items() if value not in (None, "")})
    url = API + path + "?" + urllib.parse.urlencode(query)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with opener(request, timeout=timeout) as response:
        payload = response.read()
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return json.loads(payload.decode("utf-8"))


def _lookup_tmdb_api(info, api_key, opener, timeout=6):
    """Return (language, ok). ok is False when a network or API error prevented a lookup."""
    info = info or {}
    api_key = (api_key or "").strip()
    if not api_key or opener is None:
        return "", False
    kind = "tv" if _tv(info) else "movie"
    tmdb = _digits(info.get("tmdb"))
    imdb = str(info.get("imdb") or "").strip()
    try:
        if tmdb:
            data = _request_json(opener, "/{0}/{1}".format(kind, tmdb), api_key, timeout)
            language = (data or {}).get("original_language") or ""
            return (language if usable_language(language) else ""), True
        if imdb.lower().startswith("tt"):
            data = _request_json(
                opener, "/find/{0}".format(urllib.parse.quote(imdb)), api_key, timeout,
                {"external_source": "imdb_id"},
            )
            if not isinstance(data, dict):
                return "", True
            first = "tv_results" if kind == "tv" else "movie_results"
            second = "movie_results" if first == "tv_results" else "tv_results"
            results = data.get(first) or data.get(second) or []
            if results and usable_language(results[0].get("original_language")):
                return str(results[0].get("original_language")).strip(), True
            return "", True
        title = lookup_title(info)
        if not title:
            return "", False
        year = str(info.get("year") or "")
        if kind == "tv":
            params = {"query": title}
            if year:
                params["first_air_date_year"] = year
            data = _request_json(opener, "/search/tv", api_key, timeout, params)
        else:
            params = {"query": title}
            if year:
                params["year"] = year
            data = _request_json(opener, "/search/movie", api_key, timeout, params)
        results = (data or {}).get("results") if isinstance(data, dict) else []
        return pick_result(results or [], title, year), True
    except Exception:
        return "", False


def lookup_tmdb_api(info, api_key, opener, timeout=6):
    """Search or fetch TheMovieDB and return an ISO 639-1 code, or ''."""
    language, _ok = _lookup_tmdb_api(info, api_key, opener, timeout=timeout)
    return language


def lookup_helper(info, db_paths, hints=None):
    """Return (language, 'tmdbhelper') from Helper's player value or its database."""
    language = original_from_properties(hints)
    if language:
        return language, "tmdbhelper"
    for path in db_paths or []:
        language = lookup_helper_db(path, info)
        if language:
            return language, "tmdbhelper"
    return "", ""


def choose_original(local, local_source, found, found_source):
    """Helper wins when it names a different language from the file or metadata."""
    from languages import same_language

    found = (found or "").strip()
    local = (local or "").strip()
    if found and found_source == "tmdbhelper" and local and not same_language(found, local):
        return found, "tmdbhelper"
    if found and not local:
        return found, found_source or "tmdbhelper"
    if local:
        return local, local_source or "file"
    if found:
        return found, found_source or ""
    return "", ""


def search_original(info, api_key, db_paths, cache, opener=None, timeout=6):
    """Return (language, source) from the cache, Helper database, or TheMovieDB.

    source is 'cache', 'tmdbhelper', or 'tmdb'. An empty language means the
    lookup ran and found nothing.
    """
    keys = cache_keys(info)
    if cache is not None and keys:
        language, source, hit = cache.get(keys)
        if hit:
            return language, source or "cache"
    for path in db_paths or []:
        language = lookup_helper_db(path, info)
        if language:
            if cache is not None:
                cache.put(keys, language, "tmdbhelper")
            return language, "tmdbhelper"
    language, ok = _lookup_tmdb_api(info, api_key, opener, timeout=timeout) if api_key else ("", False)
    if cache is not None and api_key and ok:
        cache.put(keys, language, "tmdb")
    if language:
        return language, "tmdb"
    return "", ""


def resolve_original(
    streams, hints, info, allow_search, api_key, db_paths, cache, opener=None, helper_hints=None
):
    """Return (language, source). TheMovieDB Helper wins a disagreement with the file."""
    file_language = original_from_streams(streams)
    meta_language = "" if file_language else original_from_properties(hints)
    local = file_language or meta_language
    local_source = "file" if file_language else ("metadata" if meta_language else "")
    if not allow_search:
        return (local, local_source) if local else ("", "")
    helper, helper_source = lookup_helper(info, db_paths, helper_hints)
    if helper:
        return choose_original(local, local_source, helper, helper_source)
    if local:
        return local, local_source
    return search_original(info, api_key, db_paths, cache, opener=opener)
