# Audio Enforcer

**Project page:** [jonnypuma.github.io/#/service.audio.enforcer](https://jonnypuma.github.io/#/service.audio.enforcer) · **All add-ons and apps by jonnypuma:** [jonnypuma.github.io](https://jonnypuma.github.io/)

Kodi service add-on that selects a preferred audio track when a video starts.

## What it does

On every video playback start:

1. Reads the audio tracks Kodi has found (if there is only one track, it is left as is).
2. Walks your list from priority 1 to priority 5.
3. Selects the first priority that has an allowed track.
4. Shows a short message naming that track (when **Show the chosen audio** is set to **Only when changed** or **Always**).

The choice is made once for that playback. Music plays as it is. When no priority has an allowed track, the track already playing stays on. The same lines are written to `kodi.log`, each beginning with `Audio Enforcer`.

## Priorities

Set up to five choices. Leave a priority on **Off** to skip it. The defaults are **Original language**, then **Default track**, then three unused priorities.

Each priority can be:

- **Original language**. The file's original language, then a lookup when the file does not name one.
- **Default track**. The track marked as the default in the file.
- **Kodi audio language**. Settings → Player → Language → Preferred audio language. Original and Default there map to the choices above. The interface language maps to that language. An empty value skips this priority.
- A language from the list, such as English or Japanese.

Within one language, a track marked default comes first, then a track marked original, then the one with more channels, then the higher bitrate. Turn on **Prefer highest quality over file default** to rank channel count and bitrate ahead of the file's default flag.

## Original language

When original language is needed (no higher priority has already matched), Audio Enforcer checks TheMovieDB Helper. If the helper names a language and the file names a different one, the helper's language is used. If the helper has no original language, the file's original track is used, then a value stored on the item. If none of those name one, TheMovieDB is searched.

A found language is remembered for 30 days. A title with no match is remembered for 3 days (network errors are not cached). Use **Clear original language cache** in settings to reset saved lookups. TV episodes are looked up as the show. A search uses the exact title, and the year when one is known.

## Commentary and audio description

**Avoid commentary tracks** is on by default. Tracks flagged as commentary or whose name says commentary (including common non-English terms) are skipped, and the next priority is tried.

**Avoid audio description tracks** is also on by default. Tracks flagged for visually impaired listeners or named as audio description (`Audio Description`, `AD`, `DVS`, etc.) are skipped in the same way. Turn either setting off to let those tracks be selected like any other track.

## Trailers and extras

A trailer is a file whose name ends with "trailer", or a file inside a Trailers folder. Extras are samples, featurettes, interviews, deleted scenes, behind-the-scenes videos, and files inside those folders.

Each of trailers and extras can:

- **Leave unchanged**
- **Use the main priorities**
- Play the **original language**, the **default track**, or the **Kodi audio language**
- Play one **specific language**

Both default to leaving the audio as it is.

## Show rules

A show or movie can keep its own choice: the original language, the default track, Kodi's audio language, a language from the list, or leave unchanged. Open **Shows → Manage show rules**. **Search for a show or movie** looks in the Kodi library and on TheMovieDB, then you pick the result to link. **Add the title that is playing** links the show or movie that is already playing.

In the library, **Set audio language for this title** links that movie or show (or lets you edit/remove an existing rule). On an episode or season, it links the show. When **Fall back to main priorities** is enabled (default), Audio Enforcer tries your main priority list if the rule's language is missing from the file.

A linked rule follows that show's library id, TheMovieDB id, or IMDb id. A file that has none of those still matches the same title and year, including a folder named `Dark (2017)`. A different show with the same name does not match. An older rule that is only a name still matches that name, and `Dark` still leaves `Dark Matter` alone.

Rules are stored in `userdata/addon_data/service.audio.enforcer/showrules.json`:

```json
[
  {
    "name": "Dark",
    "year": "2017",
    "mediatype": "tvshow",
    "tmdb": "70523",
    "imdb": "tt5753856",
    "library_id": "4",
    "action": "eng",
    "custom": ""
  }
]
```

`action` is `original`, `default`, `kodi`, `leave`, a language code such as `eng`, or `custom` with the name in `custom`.

## Install

1. Zip the `service.audio.enforcer` folder, or copy it to the Kodi add-ons folder:
   - **Windows**: `%APPDATA%\Kodi\addons\`
   - **Linux**: `~/.kodi/addons/`
   - **macOS**: `~/Library/Application Support/Kodi/addons/`
   - **Android**: `/sdcard/Android/data/org.xbmc.kodi/files/.kodi/addons/`
2. In Kodi, use **Settings → Add-ons → Install from zip file**, or restart Kodi and enable **Audio Enforcer** under **My add-ons → Services**.

Restart Kodi after copying the folder in place. The add-on id is `service.audio.enforcer`. It needs Kodi 19 or newer.

## Tests

From the add-on folder:

```
python -m unittest discover -s tests
```
