# -*- coding: utf-8 -*-
"""Context menu: set the audio language for this show or movie."""

import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import xbmc

from dialogs import set_rule_for_context


if __name__ == "__main__":
    try:
        set_rule_for_context()
    except Exception:
        xbmc.log("Audio Enforcer context menu failed\n{0}".format(traceback.format_exc()), xbmc.LOGERROR)
