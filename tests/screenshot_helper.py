"""Capture the primary screen to a PNG file (acceptance test helper)."""
import sys

from mss import mss
from PIL import Image

out = sys.argv[1] if len(sys.argv) > 1 else "screen.png"
with mss() as sct:
    monitor = sct.monitors[1]
    img = sct.grab(monitor)
    Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX").save(out)
print(f"saved {out}")
