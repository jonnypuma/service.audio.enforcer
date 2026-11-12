# -*- coding: utf-8 -*-
"""Pick one audio stream from the priority list."""

from languages import LANGUAGES, flag, is_commentary, language_label, language_matches, spec_from_text

_LAYOUTS = {1: "mono", 2: "stereo", 6: "5.1", 8: "7.1"}


def priority_item(code, custom, slot):
    """Return a resolved priority, or None when this slot should be skipped."""
    code = (code or "").strip().lower()
    custom = custom or ""
    if code == "original":
        return {"slot": slot, "kind": "original", "label": "Original language"}
    if code == "default":
        return {"slot": slot, "kind": "default", "label": "Default track"}
    if code == "custom":
        spec = spec_from_text(custom)
        if spec is None:
            return None
        return {"slot": slot, "kind": "language", "spec": spec, "label": spec["label"]}
    spec = LANGUAGES.get(code)
    if spec is None:
        spec = spec_from_text(code)
    if spec is None:
        return None
    return {"slot": slot, "kind": "language", "spec": spec, "label": spec["label"]}


def map_kodi_audio(value, gui_language):
    """Map Kodi's preferred audio language to one priority, or None to skip it."""
    value = (value or "").strip().lower()
    if value in ("", "none"):
        return None
    if value == "original":
        return {"kind": "original", "label": "Original language"}
    if value == "mediadefault":
        return {"kind": "default", "label": "Default track"}
    if value == "default":
        spec = spec_from_text(gui_language)
        if spec is None:
            return None
        return {"kind": "language", "spec": spec, "label": spec["label"]}
    return priority_item(value, "", 0)


def resolve_priorities(priorities, kodi_value, gui_language, timed_out):
    """Return (resolved priorities, still waiting for Kodi's setting)."""
    priorities = priorities or []
    if any(pref.get("code") == "kodi" for pref in priorities) and kodi_value is None and not timed_out:
        return [], True
    resolved = []
    for pref in priorities:
        code = pref.get("code")
        slot = pref.get("slot") or 0
        if code == "kodi":
            if kodi_value is None:
                continue
            mapped = map_kodi_audio(kodi_value, gui_language)
            if mapped is None:
                continue
            mapped["slot"] = slot
            resolved.append(mapped)
            continue
        item = priority_item(code, pref.get("custom") or "", slot)
        if item is not None:
            resolved.append(item)
    return resolved, False


def needs_original(priorities):
    return any(pref.get("kind") == "original" for pref in priorities or [])


def _number(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def best_stream(streams, avoid_commentary):
    """Prefer a real dialogue track, then the file default, then more channels."""
    rows = [stream for stream in streams or [] if isinstance(stream, dict) and stream.get("index") is not None]
    if avoid_commentary:
        plain = [stream for stream in rows if not is_commentary(stream)]
        if not plain:
            return None
        rows = plain
    if not rows:
        return None

    def sort_key(stream):
        return (
            0 if flag(stream.get("isdefault")) else 1,
            0 if flag(stream.get("isoriginal")) else 1,
            -_number(stream.get("channels")),
            -_number(stream.get("bitrate")),
            _number(stream.get("index")),
        )

    rows.sort(key=sort_key)
    return rows[0]


def choose_audio(streams, priorities, original_language, avoid_commentary):
    """Return (priority, stream) for the first priority that has an allowed track."""
    usable = [stream for stream in streams or [] if isinstance(stream, dict)]
    for pref in priorities or []:
        kind = pref.get("kind")
        if kind == "default":
            candidates = [stream for stream in usable if flag(stream.get("isdefault"))]
        elif kind == "original":
            if original_language:
                spec = spec_from_text(original_language)
                if spec is None:
                    continue
                candidates = [stream for stream in usable if language_matches(stream, spec)]
            else:
                candidates = [stream for stream in usable if flag(stream.get("isoriginal"))]
        elif kind == "language":
            spec = pref.get("spec")
            if spec is None:
                continue
            candidates = [stream for stream in usable if language_matches(stream, spec)]
        else:
            continue
        picked = best_stream(candidates, avoid_commentary)
        if picked is not None:
            return pref, picked
    return None, None


def describe_stream(stream):
    language = (stream.get("language") or "").strip() or "?"
    name = (stream.get("name") or "").strip()
    flags = []
    if flag(stream.get("isdefault")):
        flags.append("default")
    if flag(stream.get("isoriginal")):
        flags.append("original")
    if is_commentary(stream):
        flags.append("commentary")
    channels = _number(stream.get("channels"))
    if channels:
        flags.append("{0}ch".format(channels))
    codec = (stream.get("codec") or "").strip()
    if codec:
        flags.append(codec)
    title = name or language_label(language) or language
    return "{0} [{1}, {2}]".format(title, language, ", ".join(flags) or "audio")


def selection_message(pref, stream):
    label = language_label(stream.get("language")) or (stream.get("name") or "").strip() or pref.get("label") or "Audio"
    notes = []
    if is_commentary(stream):
        notes.append("commentary")
    channels = _number(stream.get("channels"))
    if channels in _LAYOUTS and channels > 2:
        notes.append(_LAYOUTS[channels])
    elif channels > 2:
        notes.append("{0}ch".format(channels))
    if notes:
        return "{0} ({1})".format(label, ", ".join(notes))
    return label


def format_streams(streams):
    shown = [stream for stream in streams or [] if isinstance(stream, dict)]
    text = "; ".join(describe_stream(stream) for stream in shown[:30])
    extra = len(shown) - 30
    if extra > 0:
        text += "; +{0} more".format(extra)
    return text or "none"
