# -*- coding: utf-8 -*-
"""Language codes and track-name matching shared by settings and playback."""

import re

# code, label, extra ISO codes, name stems, special matcher
# Two-letter codes are matched against the stream language, not inside a
# track name, so a short tag cannot be read as a language.
_LANGUAGE_ROWS = (
    ("ara", "Arabic", "ar", "arabic", ""),
    ("bul", "Bulgarian", "bg", "bulgarian", ""),
    ("cat", "Catalan", "ca", "catalan", ""),
    ("chi", "Chinese", "zho zh", "chinese", ""),
    ("zhs", "Chinese (Simplified)", "zh-cn zh-sg zh-hans chs", "", "simplified"),
    ("zht", "Chinese (Traditional)", "zh-tw zh-hk zh-mo zh-hant cht", "", "traditional"),
    ("hrv", "Croatian", "hr", "croatian", ""),
    ("cze", "Czech", "ces cs", "czech", ""),
    ("dan", "Danish", "da", "danish", ""),
    ("dut", "Dutch", "nld nl", "dutch", ""),
    ("eng", "English", "en", "english", ""),
    ("est", "Estonian", "et", "estonian", ""),
    ("fin", "Finnish", "fi", "finnish", ""),
    ("fre", "French", "fra fr", "french", ""),
    ("ger", "German", "deu de", "german", ""),
    ("gre", "Greek", "ell el", "greek", ""),
    ("heb", "Hebrew", "he", "hebrew", ""),
    ("hin", "Hindi", "hi", "hindi", ""),
    ("hun", "Hungarian", "hu", "hungarian", ""),
    ("ice", "Icelandic", "isl is", "icelandic", ""),
    ("ind", "Indonesian", "id", "indonesian", ""),
    ("ita", "Italian", "it", "italian", ""),
    ("jpn", "Japanese", "ja jp", "japanese", ""),
    ("kor", "Korean", "ko", "korean", ""),
    ("lav", "Latvian", "lv", "latvian", ""),
    ("lit", "Lithuanian", "lt", "lithuanian", ""),
    ("may", "Malay", "msa ms", "malay", ""),
    ("nor", "Norwegian", "nob nno no nb nn", "norwegian", ""),
    ("per", "Persian", "fas fa", "persian|farsi", ""),
    ("pol", "Polish", "pl", "polish", ""),
    ("por", "Portuguese", "pt", "portuguese", ""),
    ("pob", "Portuguese (Brazil)", "pt-br pb", "", "brazilian"),
    ("rum", "Romanian", "ron ro", "romanian", ""),
    ("rus", "Russian", "ru", "russian", ""),
    ("srp", "Serbian", "sr", "serbian", ""),
    ("slo", "Slovak", "slk sk", "slovak", ""),
    ("slv", "Slovenian", "sl", "slovenian|slovene", ""),
    ("spa", "Spanish", "es", "spanish", ""),
    ("swe", "Swedish", "sv", "swedish", ""),
    ("tha", "Thai", "th", "thai", ""),
    ("tur", "Turkish", "tr", "turkish", ""),
    ("ukr", "Ukrainian", "uk", "ukrainian", ""),
    ("vie", "Vietnamese", "vi", "vietnamese", ""),
)

LANGUAGES = {}
LANGUAGE_CHOICES = []
for _code, _label, _extra, _names, _match in _LANGUAGE_ROWS:
    LANGUAGES[_code] = {
        "label": _label,
        "codes": frozenset([_code] + _extra.split()),
        "names": tuple(part for part in _names.split("|") if part),
        "match": _match,
    }
    LANGUAGE_CHOICES.append(_code)

# Priority values that are rules, not languages.
RULE_CODES = ("off", "original", "default", "kodi", "custom")

# First dialog for a priority. Custom opens the language list.
SETTING_ROWS = (
    ("off", 32095, "Off"),
    ("original", 32087, "Original language"),
    ("default", 32088, "Default track"),
    ("kodi", 32089, "Kodi audio language"),
    ("custom", 32150, "Custom audio language"),
)

_PRIORITY_TEXT = {}
for _code, _string_id, _fallback in SETTING_ROWS:
    _PRIORITY_TEXT[_code] = _code
    _PRIORITY_TEXT[_fallback.lower()] = _code


def priority_value(text):
    """Map a saved priority to off, original, default, kodi, custom, or a language code."""
    raw = " ".join((text or "").strip().lower().split())
    if not raw:
        return ""
    if raw in _PRIORITY_TEXT:
        return _PRIORITY_TEXT[raw]
    if raw in LANGUAGES:
        return raw
    for code in LANGUAGE_CHOICES:
        spec = LANGUAGES[code]
        if raw == spec["label"].lower() or raw in spec["names"] or raw in spec["codes"]:
            return code
    return ""


def same_language(left, right):
    """True when two codes or names are the same language."""
    left_spec = spec_from_text(left)
    right_spec = spec_from_text(right)
    if not left_spec or not right_spec:
        return False
    return left_spec["label"].lower() == right_spec["label"].lower()


def spec_from_text(text):
    """Build a language spec from a name or code, including ones not in the list."""
    raw = _normalize_language(text)
    if not raw or raw in RULE_CODES or raw in ("none", "leave", "mediadefault"):
        return None
    for code in LANGUAGE_CHOICES:
        spec = LANGUAGES[code]
        if (
            raw == code
            or raw in spec["codes"]
            or raw in spec["names"]
            or raw == spec["label"].lower()
        ):
            return spec
    codes = {raw}
    base = raw.split("-", 1)[0]
    if base and base != raw:
        codes.add(base)
    names = (raw,) if (" " in raw or len(raw) > 3) else ()
    label = (text or "").strip() or raw
    return {
        "label": label,
        "codes": frozenset(codes),
        "names": names,
        "match": "",
    }


def language_label(text):
    """English label for a code or name, or '' when it is not a language."""
    spec = spec_from_text(text)
    if spec is None:
        return ""
    return spec["label"]


def _token(text, word):
    return re.search(
        r"(?:^|[^a-z0-9])" + re.escape(word) + r"(?:[^a-z0-9]|$)",
        text,
    ) is not None


def _normalize_language(value):
    return (value or "").strip().lower().replace("_", "-")


def stream_text(stream):
    language = _normalize_language(stream.get("language"))
    name = (stream.get("name") or "").strip().lower()
    return language, name


def _field_matches_codes(language, codes):
    if not language:
        return False
    if language in codes:
        return True
    base = language.split("-", 1)[0]
    return base != language and base in codes


def _name_has_code(name, codes):
    for code in codes:
        if len(code) < 3:
            continue
        if _token(name, code):
            return True
    return False


def _name_matches_stem(name, names):
    for stem in names:
        if (
            name == stem
            or name.startswith(stem + " ")
            or name.startswith(stem + "(")
            or name.startswith(stem + "[")
            or name.startswith(stem + "-")
            or name.startswith(stem + ":")
            or name.startswith(stem + ".")
        ):
            return True
    return False


def _is_simplified(language, name):
    if language in {"zhs", "zh-cn", "zh-sg", "zh-hans", "chs", "sc"}:
        return True
    if "hans" in language:
        return True
    return "simplified" in name or _token(name, "hans")


def _is_traditional(language, name):
    if language in {"zht", "zh-tw", "zh-hk", "zh-mo", "zh-hant", "cht", "tc"}:
        return True
    if "hant" in language:
        return True
    return "traditional" in name or _token(name, "hant")


def _is_brazilian(language, name):
    if language in {"pob", "pt-br", "pb", "por-br"}:
        return True
    return "brazil" in name


def language_matches(stream, spec):
    language, name = stream_text(stream)
    kind = spec["match"]
    if kind == "simplified":
        return _is_simplified(language, name) or _name_has_code(name, spec["codes"])
    if kind == "traditional":
        return _is_traditional(language, name) or _name_has_code(name, spec["codes"])
    if kind == "brazilian":
        return _is_brazilian(language, name) or _name_has_code(name, spec["codes"])
    # European Portuguese does not claim a Brazilian track.
    if spec["codes"] == LANGUAGES["por"]["codes"] and _is_brazilian(language, name):
        return False
    if _field_matches_codes(language, spec["codes"]) or language in spec["names"]:
        return True
    if _name_matches_stem(name, spec["names"]):
        return True
    return _name_has_code(name, spec["codes"])


def flag(value):
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def is_commentary(stream):
    """True when the track name says it is a commentary."""
    _language, name = stream_text(stream)
    return _token(name, "commentary") or _token(name, "commentaries")
