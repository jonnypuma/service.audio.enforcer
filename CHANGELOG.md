# Changelog

## Version 1.1.0

- Fixed hardcoded local `RunScript` path in settings and localized priority dropdown labels
- Added **Avoid audio description tracks** (`isvisualimpaired` and AD/DVS track-name matching) and expanded commentary detection to `iscommentary` and additional languages
- Added **Prefer highest quality over file default** to rank channels and bitrate ahead of the file's `default` flag
- Added **Fall back to main priorities** for show and movie rules when the rule's language is unavailable
- Changed **Show the chosen audio** to **Off**, **Only when changed**, or **Always**
- Added **Clear original language cache** in settings, thread-safe/pruned cache writes, and avoided caching transient network errors as misses
- Supported Unicode titles (accented and non-Latin characters) in path and TMDB matching
- Context menu now opens the edit/remove dialog directly when a title already has a rule
- Reduced idle polling and cached settings and `showrules.json` until changed; short-circuited single-track videos

## Version 1.0.0

- Selects an audio track from up to five priorities when a video starts
- Priorities can be the original language, the file's default track, Kodi's audio language, or a specific language
- Looks up a missing original language with TheMovieDB Helper, then TheMovieDB
- Skips commentary tracks and tries the next priority
- Trailers and extras can follow the main list, use one language, or stay as they are
- A show or movie can keep its own language. The manager searches the library and TheMovieDB and links the show you pick
