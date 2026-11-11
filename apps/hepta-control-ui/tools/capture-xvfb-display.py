"""Capture the isolated CI Xvfb display, without changing the renderer."""

import os
import sys

from PIL import ImageGrab

display = os.environ.get("DISPLAY")
if not os.environ.get("CI") or not display or not display.startswith(":"):
    raise RuntimeError("Only the isolated CI X display may be captured")
image = ImageGrab.grab(xdisplay=display)
if image.width * image.height > 8_000_000:
    raise ValueError("CI display exceeds the diagnostic pixel bound")
image.save(sys.argv[1], format="PNG")
