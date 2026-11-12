# -*- coding: utf-8 -*-
"""Context menu: set the audio language for this show or movie."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dialogs import set_rule_for_context


if __name__ == "__main__":
    set_rule_for_context()
