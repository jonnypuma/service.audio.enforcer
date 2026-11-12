# -*- coding: utf-8 -*-
"""Open the show-rule manager from the add-on settings."""

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import xbmc

from dialogs import manage_show_rules, pick_audio_setting


def _setting_to_pick(argv):
    args = [part.strip() for part in argv if part and part.strip()]
    for index, arg in enumerate(args):
        if arg == "pick" and index + 1 < len(args):
            return args[index + 1]
        if arg.startswith("pick,"):
            return arg.split(",", 1)[1].strip()
    return ""


if __name__ == "__main__":
    try:
        xbmc.log("Audio Enforcer script {0}".format(sys.argv[1:]), xbmc.LOGINFO)
        setting_id = _setting_to_pick(sys.argv)
        if setting_id:
            pick_audio_setting(setting_id)
        else:
            manage_show_rules()
    except Exception:
        xbmc.log("Audio Enforcer script failed\n{0}".format(traceback.format_exc()), xbmc.LOGERROR)
