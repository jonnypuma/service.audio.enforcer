# -*- coding: utf-8 -*-
"""Open the show-rule manager from the add-on settings."""

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import xbmc

from dialogs import clear_cache, manage_show_rules


def _action(argv):
    for arg in argv[1:]:
        cleaned = (arg or "").strip().lower()
        if cleaned:
            return cleaned
    return ""


if __name__ == "__main__":
    try:
        xbmc.log("Audio Enforcer script {0}".format(sys.argv[1:]), xbmc.LOGINFO)
        if _action(sys.argv) == "clear_cache":
            clear_cache()
        else:
            manage_show_rules()
    except Exception:
        xbmc.log("Audio Enforcer script failed\n{0}".format(traceback.format_exc()), xbmc.LOGERROR)
