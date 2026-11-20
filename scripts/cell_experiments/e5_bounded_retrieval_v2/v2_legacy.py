"""Reuse only the hash-pinned v1 byte and edit primitives, without changing v1."""

import importlib
import sys
from pathlib import Path

from v2_common import require, sha

PINS = {
    "source_units": "84fc4633fc32e2e644ebc10c28f2c39f61f8e4378cb64201ba804973a6a2a736",
    "source_actions": "f30747a5ddcfab036911b34806e067e02d4600f14ebd7e7f29a4ff07e8e657fc",
    "visible_material": "c83612abb2b31ee8dd5857d659a4ce08104fc701c37f4c4a88d4172a69013ca5",
}
ROOT = Path(__file__).resolve().parent.parent / "e5_source_codec_v1"
for name, expected in PINS.items():
    path = ROOT / (name + ".py")
    require(sha(path.read_bytes()) == expected, "v1 source pin changed: " + name)
    if name in sys.modules:
        old = Path(sys.modules[name].__file__).resolve()
        require(
            sha(old.read_bytes()) == expected, "different preloaded v1 module: " + name
        )
sys.path.insert(0, str(ROOT))
try:
    source_units = importlib.import_module("source_units")
    source_actions = importlib.import_module("source_actions")
    visible_material = importlib.import_module("visible_material")
finally:
    sys.path.remove(str(ROOT))
