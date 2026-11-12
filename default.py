# -*- coding: utf-8 -*-
"""Audio Enforcer service. Selects a preferred audio track when playback starts."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources", "lib"))

from service import main


if __name__ == "__main__":
    main()
